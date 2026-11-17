# Patroni Custom Docker Network Showcase

A self-contained demonstration of a 3-node High Availability PostgreSQL cluster managed by Patroni and backed by etcd DCS, orchestrated entirely via raw Docker CLI commands within a dedicated bridge network.

---

## Architecture Diagram

```text
showcase-pg-node1 ─┐
showcase-pg-node2 ─┼─→ showcase-etcd
showcase-pg-node3 ─┘
```

---

## Container DNS vs Production Cluster IP

> [!NOTE]
> The custom Docker bridge network (`pg-cluster-showcase-net`) provides **internal container DNS resolution** between containers (`showcase-pg-node1`, `showcase-pg-node2`, `showcase-pg-node3`, and `showcase-etcd`).
>
> It does **not** provide a virtual floating cluster IP or any software load balancer by itself.
>
> When the Site24x7 monitoring agent runs on the **Windows host**, the container hostnames and internal IP addresses (`172.x.x.x`) are not directly routable from the host. Therefore:
> 1. Each node maps container ports to published host ports:
>    - Node 1: `127.0.0.1:5441` (Postgres) and `127.0.0.1:8001` (Patroni REST)
>    - Node 2: `127.0.0.1:5442` (Postgres) and `127.0.0.1:8002` (Patroni REST)
>    - Node 3: `127.0.0.1:5443` (Postgres) and `127.0.0.1:8003` (Patroni REST)
> 2. The Site24x7 plugin uses the `address_map` setting to translate the container-internal connect addresses discovered from Patroni's REST API into their corresponding host-published ports.

---

## Commands

### 1. Start the Showcase
From PowerShell in the repository root:
```powershell
Set-Location "demo\patroni-network-showcase"
.\start.ps1
```

### 2. Inspect the Showcase
Check the Patroni cluster status directly from the REST API:
```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8001/cluster" | ConvertTo-Json -Depth 4
```

Inspect the leader and member state via `patronictl`:
```powershell
docker exec showcase-pg-node1 patronictl -c /home/postgres/config/patroni.yml list
```

### 3. Stop the Showcase
Cleanly stop and remove showcase containers (retaining data volumes and network):
```powershell
Set-Location "demo\patroni-network-showcase"
.\stop.ps1
```

To stop containers and purge all named volumes and the custom network:
```powershell
.\stop.ps1 -Purge
```

---

## Host-side Site24x7 Demo Configuration

To monitor this showcase cluster from the Windows host using the Site24x7 PostgreSQL cluster plugin, configure:

```ini
[postgres_cluster]
cluster_host="127.0.0.1"
postgres_port="5441"
patroni_port="8001"
username="site24x7"
password="site24x7"
db="postgres"
discover="auto"
address_map="showcase-pg-node1:5432=127.0.0.1:5441,showcase-pg-node1:8008=127.0.0.1:8001,showcase-pg-node2:5432=127.0.0.1:5442,showcase-pg-node2:8008=127.0.0.1:8002,showcase-pg-node3:5432=127.0.0.1:5443,showcase-pg-node3:8008=127.0.0.1:8003"
```
