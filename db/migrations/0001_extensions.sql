-- Extensions. btree_gist is required for the exclusion constraints in 0003.
CREATE EXTENSION IF NOT EXISTS btree_gist;
CREATE EXTENSION IF NOT EXISTS pgcrypto;   -- gen_random_uuid()
