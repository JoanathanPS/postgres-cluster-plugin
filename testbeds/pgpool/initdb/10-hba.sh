#!/bin/bash
# Test bed only: let the standbys stream from this primary without a password.
echo "host replication all all trust" >> "$PGDATA/pg_hba.conf"
