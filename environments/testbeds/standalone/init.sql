CREATE USER site24x7 WITH PASSWORD 'site24x7';
GRANT pg_monitor TO site24x7;
GRANT CONNECT ON DATABASE postgres TO site24x7;
CREATE USER unprivileged_user WITH PASSWORD 'wrong_password';
