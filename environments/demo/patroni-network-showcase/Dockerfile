FROM ongres/patroni:v4.0.4-pg17.2-build-6.38

USER root
RUN mkdir -p /home/postgres/data /home/postgres/config /run/postgresql && \
    chown -R postgres:postgres /home/postgres /run/postgresql

USER postgres
WORKDIR /home/postgres

ENTRYPOINT ["patroni"]
