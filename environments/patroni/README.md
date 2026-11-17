# Patroni + etcd + HAProxy 3-Node PostgreSQL HA Cluster

This directory provides a 3-node High Availability PostgreSQL 17 cluster managed by **Patroni**, backed by **etcd v3** distributed consensus store, and fronted by **HAProxy** for load balancing.

## Architecture

```
                    HAProxy (127.0.0.1)
           ┌─────────────────┴─────────────────┐
           │                                   │
      Port 5000 (RW Primary)              Port 5001 (RO Replicas)
           │                                   │
   ┌───────┴──────────┬────────────────────────┴────────┐
   ▼ (check :8008)    ▼ (check :8008)                   ▼ (check :8008)
pg-node1           pg-node2                          pg-node3
127.0.0.1:5441     127.0.0.1:5442                    127.0.0.1:5443
REST: 8001         REST: 8002                        REST: 8003
   │                  │                                 │
   └──────────────────┼─────────────────────────────────┘
                      ▼
               etcd (127.0.0.1:2379)
             DCS / Leader Consensus
```

## Published Ports

| Component | Container Port | Published Host Port | Purpose |
|---|---|---|---|
| **pg-node1** | 5432 / 8008 | `127.0.0.1:5441` / `8001` | PostgreSQL node 1 & Patroni REST API |
| **pg-node2** | 5432 / 8008 | `127.0.0.1:5442` / `8002` | PostgreSQL node 2 & Patroni REST API |
| **pg-node3** | 5432 / 8008 | `127.0.0.1:5443` / `8003` | PostgreSQL node 3 & Patroni REST API |
| **etcd** | 2379 | `127.0.0.1:2379` | Distributed Configuration Store |
| **HAProxy** | 5000 / 5001 / 7000 | `127.0.0.1:5000` / `5001` / `7000` | RW Primary, RO Replicas, Stats UI |

## Quick Commands

### 1. Start the Cluster
```powershell
docker compose -f patroni-cluster/docker-compose.yml up -d --build
```

### 2. Check Patroni Cluster Status
```powershell
docker exec patroni-pg-node2 patronictl -c /home/postgres/config/patroni.yml list
```

### 3. Run the Site24x7 PostgreSQL Cluster Plugin
```powershell
py postgres_cluster/postgres_cluster.py --nodes "node1=localhost:5441,node2=localhost:5442,node3=localhost:5443" --username site24x7 --password site24x7 --db appdb --patroni_port 8008
```

### 4. Test Automatic Failover
```powershell
# Stop current leader
docker stop patroni-pg-node1

# Check cluster state (another node is promoted to Leader)
docker exec patroni-pg-node2 patronictl -c /home/postgres/config/patroni.yml list

# Run plugin again to observe timeline change & node1 marked down
py postgres_cluster/postgres_cluster.py --nodes "node1=localhost:5441,node2=localhost:5442,node3=localhost:5443" --username site24x7 --password site24x7 --db appdb --patroni_port 8008

# Recover node1
docker start patroni-pg-node1
```

### 5. Stop and Clean Up
```powershell
docker compose -f patroni-cluster/docker-compose.yml down -v
```
