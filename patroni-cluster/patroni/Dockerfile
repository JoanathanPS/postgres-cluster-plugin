FROM ongres/patroni:latest

USER root
RUN mkdir -p /home/postgres/data /home/postgres/config /run/postgresql && \
    chown -R postgres:postgres /home/postgres /run/postgresql

USER postgres
WORKDIR /home/postgres

ENTRYPOINT ["patroni"]
