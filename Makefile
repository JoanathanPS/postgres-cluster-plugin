# ==============================================================================
# Makefile for the Site24x7 PostgreSQL plugin (v2) and its Patroni test bed
# ==============================================================================

COMPOSE_FILE = environments/patroni/docker-compose.yml
PYTHON ?= py

.PHONY: help up down status logs test

help:
	@echo "Available commands:"
	@echo "  make up            - Build and start Patroni + etcd + HAProxy cluster"
	@echo "  make down          - Stop and destroy the cluster and data volumes"
	@echo "  make status        - Show running cluster containers and Patroni state"
	@echo "  make test          - Run the plugin unit tests"

up:
	docker compose -f $(COMPOSE_FILE) up -d --build
	@echo "Waiting for cluster initialization..."
	@sleep 8
	docker exec patroni-pg-node2 patronictl -c /home/postgres/config/patroni.yml list || true

down:
	docker compose -f $(COMPOSE_FILE) down -v

status:
	docker compose -f $(COMPOSE_FILE) ps
	@echo ""
	docker exec patroni-pg-node2 patronictl -c /home/postgres/config/patroni.yml list || true

logs:
	docker compose -f $(COMPOSE_FILE) logs -f

test:
	$(PYTHON) -m pytest tests -q
