"""Corpus integration tests. Need ClickHouse loaded:

    make -f Makefile.data up ch-ddl
    python -m ingest.convert data/LCA_Disclosure_Data_FY2025_Q4.xlsx
    python -m ingest.load --fiscal-year 2025 data/LCA_Disclosure_Data_FY2025_Q4.csv

These lock down the four things the real DOL data exposed that no amount of reading
the spec would have caught.
"""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from fastapi.testclient import TestClient  # noqa: E402

from api import clickhouse as ch  # noqa: E402
from api.main import LEVEL_SQL, PERCENTILE_SQL, _sql, app  # noqa: E402

SOC_DEV = "15-1252"        # Software Developers, the corpus's dominant occupation
SOC_AIDE = "31-1121"       # Home Health Aides, 1 filing in the whole corpus

pytestmark = pytest.mark.skipif(
    not ch.available(), reason="ClickHouse not reachable or corpus not loaded")


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


def _loaded() -> bool:
    rows, _ = ch.query("SELECT count() AS n FROM lca_filings")
    return int(rows[0]["n"]) > 1000


needs_corpus = pytest.mark.skipif(not ch.available() or not _loaded(),
                                  reason="corpus not loaded")


# ----------------------------------------------------------- sql plumbing -----

def test_sql_extractor_survives_a_semicolon_in_the_comment_header():
    """The header prose contains a semicolon.

    Splitting on ';' before stripping comments yields an empty query, which comes
    back as a 503 that looks exactly like ClickHouse being down. This bit once.
    """
    for text in (PERCENTILE_SQL, LEVEL_SQL):
        stmt = _sql(text)
        assert stmt.upper().startswith("SELECT")
        assert "--" not in stmt


def test_sql_extractor_refuses_a_non_select():
    with pytest.raises(RuntimeError, match="non-SELECT"):
        _sql("DROP TABLE lca_filings;")


def test_soc_normalisation_collapses_the_two_spellings():
    assert ch.normalise_soc("15-1252.00") == "15-1252"
    assert ch.normalise_soc("15-1252") == "15-1252"
    assert ch.normalise_soc("  15-1252.03 ") == "15-1252"


# ------------------------------------------------------------- the corpus -----

@needs_corpus
def test_case_status_is_normalised_before_filtering():
    """The source value is 'Certified'. 'CERTIFIED' matches nothing.

    Every filter in the build spec used the uppercase form, so every view and every
    corpus query would have returned an empty result that looked like it worked.
    """
    raw, _ = ch.query("SELECT count() AS n FROM lca_filings WHERE case_status = 'CERTIFIED'")
    norm, _ = ch.query("SELECT count() AS n FROM lca_filings WHERE case_status_norm = 'CERTIFIED'")
    assert int(raw[0]["n"]) == 0, "if this is nonzero the source spelling changed"
    assert int(norm[0]["n"]) > 100_000


@needs_corpus
def test_soc_normalisation_is_worth_two_orders_of_magnitude():
    """Querying the raw column returns a confident percentile over ~1% of the data."""
    bare, _ = ch.query(
        "SELECT count() AS n FROM lca_filings WHERE soc_code = {soc:String}",
        {"soc": SOC_DEV})
    norm, _ = ch.query(
        "SELECT count() AS n FROM lca_filings WHERE soc_code_norm = {soc:String}",
        {"soc": SOC_DEV})
    assert int(norm[0]["n"]) > 20 * int(bare[0]["n"])


@needs_corpus
def test_prevailing_wage_uses_its_own_unit():
    """PW_UNIT_OF_PAY is a separate column from WAGE_UNIT_OF_PAY.

    On rows where they differ, annualising the prevailing wage with the offered-wage
    unit gives the wrong figure. This asserts the two columns genuinely differ on
    real rows, so the separate annualisation is not theoretical.
    """
    rows, _ = ch.query(
        "SELECT count() AS n FROM lca_filings WHERE pw_unit != wage_unit "
        "AND pw_unit != '' AND wage_unit != ''")
    assert int(rows[0]["n"]) > 0


@needs_corpus
def test_no_wage_falls_through_the_annualiser():
    """Fails closed: an unrecognised unit yields NULL, never a raw number."""
    rows, _ = ch.query(
        "SELECT countIf(annualized_wage IS NULL AND wage_rate_from IS NOT NULL) AS bad "
        "FROM lca_filings WHERE wage_unit IN "
        "('Year','Hour','Month','Week','Bi-Weekly')")
    assert int(rows[0]["bad"]) == 0


# --------------------------------------------------------------- endpoint -----

@needs_corpus
def test_the_fiscal_year_filter_actually_filters():
    """Regression: a parameter echoed under a column's own name kills the filter.

    `{fy:UInt16} AS fiscal_year` in the SELECT list created an alias that
    `WHERE fiscal_year = {fy:UInt16}` then resolved against, so the predicate compared
    the parameter to itself and was always true. Both fiscal years returned an
    identical 51 rows while each response claimed a single year. The percentile was
    computed over twice the data it said it was.

    This asserts the endpoint's count equals a direct single-year count, for each
    year independently.
    """
    for fy in (2024, 2025):
        direct, _ = ch.query(
            "SELECT count() AS n FROM lca_filings WHERE case_status_norm='CERTIFIED' "
            "AND soc_code_norm={soc:String} AND worksite_state={state:String} "
            "AND fiscal_year={fy:UInt16} AND wage_suspect=0",
            {"soc": SOC_DEV, "state": "CA", "fy": fy})
        via_sql, _ = ch.query(_sql(PERCENTILE_SQL),
                              {"soc": SOC_DEV, "state": "CA", "wage": 1, "fy": fy})
        assert int(via_sql[0]["n_filings"]) == int(direct[0]["n"]), f"FY{fy}"


@needs_corpus
def test_no_query_echoes_a_parameter_under_a_column_name():
    """Guard the whole class of bug, not just the one instance.

    ClickHouse resolves SELECT aliases inside WHERE. Aliasing a parameter to a name
    that is also a column in the FROM clause silently removes any predicate on that
    column. Three separate bugs in this project came from alias shadowing.
    """
    import re
    cols = {"fiscal_year", "soc_code", "soc_code_norm", "worksite_state",
            "case_status", "case_status_norm", "wage_rate_from", "annualized_wage",
            "pw_level", "pw_median", "employer_name", "employer_fein"}
    for path in sorted(pathlib.Path("clickhouse/queries").glob("*.sql")):
        # Statement only. The header prose deliberately quotes the bug as an example,
        # and scanning comments would flag the documentation of the fix.
        text = "\n".join(l for l in path.read_text().splitlines()
                         if not l.strip().startswith("--"))
        for alias in re.findall(r"\{[a-z_]+:[A-Za-z0-9(),\s]+\}\s+AS\s+(\w+)", text):
            assert alias not in cols, f"{path.name} aliases a parameter to column {alias!r}"


@needs_corpus
def test_percentile_is_exact_and_carries_its_sample_size(client):
    r = client.get("/v1/corpus/wage-percentile",
                   params={"soc_code": SOC_DEV, "state": "CA", "wage": 188000,
                           "fiscal_year": 2025})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["n_filings"] > 1000
    assert 0 <= d["percentile"] <= 100
    assert set(d["quantiles"]) == {"p10", "p25", "p50", "p75", "p90"}
    assert d["source"]["dataset"] == "DOL OFLC LCA Disclosure Data"
    assert "not a selection probability" in d["message"]


@needs_corpus
def test_a_dotted_soc_code_returns_the_same_answer(client):
    def pct(soc):
        return client.get("/v1/corpus/wage-percentile",
                          params={"soc_code": soc, "state": "CA", "wage": 188000,
                                  "fiscal_year": 2025}).json()
    assert pct("15-1252.00")["n_filings"] == pct("15-1252")["n_filings"]


@needs_corpus
def test_state_is_case_insensitive(client):
    def n(state):
        return client.get("/v1/corpus/wage-percentile",
                          params={"soc_code": SOC_DEV, "state": state, "wage": 1,
                                  "fiscal_year": 2025}).json()["n_filings"]
    assert n("ca") == n("CA") > 0


@needs_corpus
def test_a_higher_wage_gives_a_higher_percentile(client):
    def pct(wage):
        return client.get("/v1/corpus/wage-percentile",
                          params={"soc_code": SOC_DEV, "state": "CA", "wage": wage,
                                  "fiscal_year": 2025}).json()["percentile"]
    assert pct(130_000) < pct(188_000) < pct(250_000)


@needs_corpus
def test_percentile_and_wage_level_can_disagree(client):
    """The point of REVIEW B10, as a test.

    A wage in the middle of the peer distribution can sit in an upper OES level. If
    these two numbers ever collapse into each other, the Standing screen has stopped
    telling the truth about what the selection mechanism measures.
    """
    d = client.get("/v1/corpus/wage-percentile",
                   params={"soc_code": SOC_DEV, "state": "CA", "wage": 188000,
                           "fiscal_year": 2025}).json()
    assert d["percentile"] < 60, "middling among peers"
    assert d["wage_level"] >= 3, "yet an upper OES level"
    assert len(d["level_bands"]) == 4
    # The two numbers must be allowed to disagree. If a future change makes the level
    # a function of the percentile, this is the test that should fail.
    assert d["wage_level"] != round(d["percentile"] / 25)


@needs_corpus
def test_next_level_wage_is_what_would_move_a_tier(client):
    d = client.get("/v1/corpus/wage-percentile",
                   params={"soc_code": SOC_DEV, "state": "CA", "wage": 130000,
                           "fiscal_year": 2025}).json()
    assert d["wage_level"] is None, "below Level I median"
    assert d["next_level_wage"] > 130000


@needs_corpus
def test_an_uncovered_occupation_says_so_instead_of_estimating(client):
    """The corpus is H-1B labour condition applications, concentrated in tech.

    It cannot answer a wage question for a home health aide, which is the build
    spec's own demo persona. Returning an honest refusal beats an invented number.
    See docs/REVIEW.md C8.
    """
    d = client.get("/v1/corpus/wage-percentile",
                   params={"soc_code": SOC_AIDE, "state": "CA", "wage": 62400,
                           "fiscal_year": 2025}).json()
    assert d["insufficient_data"] is True
    assert d["n_filings"] == 0
    assert d["percentile"] is None
    assert d["quantiles"] is None
    assert "cannot be computed and will not be estimated" in d["message"]


@needs_corpus
def test_small_samples_are_flagged(client):
    """A percentile over eleven filings is not a percentile."""
    rows, _ = ch.query(
        "SELECT soc_code_norm AS soc, worksite_state AS st, count() AS n "
        "FROM lca_filings WHERE case_status_norm='CERTIFIED' AND fiscal_year=2025 "
        "AND wage_suspect=0 GROUP BY soc, st HAVING n BETWEEN 1 AND 29 "
        "ORDER BY n DESC LIMIT 1")
    if not rows:
        pytest.skip("no small-sample group in this corpus")
    d = client.get("/v1/corpus/wage-percentile",
                   params={"soc_code": rows[0]["soc"], "state": rows[0]["st"],
                           "wage": 100000, "fiscal_year": 2025}).json()
    assert d["insufficient_data"] is True
    assert "indicative only" in d["message"]


@needs_corpus
def test_healthz_reports_corpus_state(client):
    assert client.get("/healthz").json()["corpus"] == "up"
