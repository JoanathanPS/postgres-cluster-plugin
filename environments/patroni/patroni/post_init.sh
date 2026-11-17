#!/bin/bash
set -e

CONN_URL="${1:-postgres://postgres:postgres_password@127.0.0.1:5432/postgres}"
echo "Running post_init bootstrap script with URL: $CONN_URL..."

psql "$CONN_URL" << 'EOF'
-- Create monitoring user for Site24x7
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'site24x7') THEN
        CREATE ROLE site24x7 WITH LOGIN PASSWORD 'site24x7';
    ELSE
        ALTER ROLE site24x7 WITH LOGIN PASSWORD 'site24x7';
    END IF;
END
$$;

GRANT pg_read_all_stats TO site24x7;
GRANT pg_read_all_settings TO site24x7;
ALTER ROLE site24x7 SET default_transaction_read_only = on;
ALTER ROLE site24x7 CONNECTION LIMIT 10;

-- Create demo appdb for table metrics
SELECT 'CREATE DATABASE appdb' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'appdb')\gexec

\c appdb

CREATE TABLE IF NOT EXISTS cluster_status (
    id SERIAL PRIMARY KEY,
    cluster_name VARCHAR(100) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO cluster_status (cluster_name) VALUES ('patroni-demo-cluster');

GRANT CONNECT ON DATABASE appdb TO site24x7;
GRANT USAGE ON SCHEMA public TO site24x7;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO site24x7;
EOF

echo "post_init completed successfully!"
