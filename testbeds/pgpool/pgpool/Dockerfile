FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends pgpool2 postgresql-client \
    && rm -rf /var/lib/apt/lists/* && useradd -m pgpooluser
COPY pgpool.conf /etc/pgpool2/pgpool.conf
USER pgpooluser
CMD ["pgpool", "-n", "-f", "/etc/pgpool2/pgpool.conf"]
