-- Small demo application database (runs once, on the primary's first start).
-- Why: the plugin's table/index metrics (Index Scans, Heap Blocks Read/Hit,
-- Cache Hit Ratio, ...) come from pg_stat_user_indexes / pg_statio_user_tables,
-- which only cover the database the plugin connects to ("db" in postgres.cfg).
-- The default "postgres" database has no user tables, so those metrics would be
-- reported as the string "None". The plugin is therefore pointed at appdb.
-- Cluster-wide metrics (connections, commits, checkpoints, per-DB tables) are
-- the same whichever database is used.
CREATE DATABASE appdb;
\connect appdb

CREATE TABLE orders (
    id         bigserial PRIMARY KEY,
    customer   text        NOT NULL,
    amount     numeric(10,2) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX orders_customer_idx ON orders (customer);

INSERT INTO orders (customer, amount)
SELECT 'customer_' || (g % 100), round((random() * 500)::numeric, 2)
FROM generate_series(1, 1000) AS g;

ANALYZE orders;
