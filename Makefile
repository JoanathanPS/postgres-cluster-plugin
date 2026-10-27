# ==============================================================================
# Makefile for PostgreSQL Patroni Cluster & Site24x7 Cluster Plugin
# ==============================================================================

COMPOSE_FILE = patroni-cluster/docker-compose.yml
PYTHON ?= py

.PHONY: help up down status logs failover-test test lag-demo

help:
	@echo "Available commands:"
	@echo "  make up            - Build and start Patroni + etcd + HAProxy cluster"
	@echo "  make down          - Stop and destroy the cluster and data volumes"
	@echo "  make status        - Show running cluster containers and Patroni state"
	@echo "  make test          - Run the Site24x7 cluster plugin validation test suite"
	@echo "  make failover-test - Execute automated failover simulation and assertions"
	@echo "  make lag-demo      - Generate load and demonstrate replication backlog"

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

failover-test:
	$(PYTHON) tester/test_cluster_plugin.py --failover

test:
	$(PYTHON) tester/test_cluster_plugin.py

lag-demo:
	$(PYTHON) tester/lag_demo.py
