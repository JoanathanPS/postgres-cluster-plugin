FROM postgres:17
RUN apt-get update && apt-get install -y --no-install-recommends postgresql-17-repmgr && rm -rf /var/lib/apt/lists/*
COPY entry.sh /entry.sh
RUN chmod +x /entry.sh
USER postgres
ENV PATH="/usr/lib/postgresql/17/bin:${PATH}" PGDATA=/var/lib/postgresql/data/pgdata
ENTRYPOINT ["/entry.sh"]
