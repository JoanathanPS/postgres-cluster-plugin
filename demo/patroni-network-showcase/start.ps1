<#
.SYNOPSIS
    Starts a self-contained 3-node Patroni + PostgreSQL HA cluster with etcd on a dedicated Docker bridge network.

.DESCRIPTION
    Idempotent script that:
    1. Validates Docker availability and configuration files.
    2. Creates a dedicated Docker bridge network (pg-cluster-showcase-net).
    3. Builds or pulls pinned Docker images without using :latest.
    4. Creates persistent named volumes for etcd and postgres nodes.
    5. Starts showcase-etcd and verifies health.
    6. Starts showcase-pg-node1, showcase-pg-node2, showcase-pg-node3 with host port mappings.
    7. Waits for Patroni to report all 3 members and an elected leader via http://127.0.0.1:<patroni_port>/cluster.
#>

[CmdletBinding()]
param(
    [string]$NetworkName = "pg-cluster-showcase-net",
    [int]$Node1PgPort = 5441,
    [int]$Node1PatroniPort = 8001,
    [int]$Node2PgPort = 5442,
    [int]$Node2PatroniPort = 8002,
    [int]$Node3PgPort = 5443,
    [int]$Node3PatroniPort = 8003,
    [int]$TimeoutSeconds = 60
)

$ErrorActionPreference = "Continue"

# 1. Validate Docker availability
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Error "Docker CLI not found in PATH. Please install or enable Docker Desktop."
    exit 1
}

$null = docker info 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Error "Docker daemon is not running or unreachable."
    exit 1
}

# 2. Validate configuration files
$scriptDir = $PSScriptRoot
$configDir = Join-Path $scriptDir "config"
$dockerfilePath = Join-Path $scriptDir "Dockerfile"

if (-not (Test-Path $dockerfilePath)) {
    Write-Error "Missing Dockerfile at: $dockerfilePath"
    exit 1
}

$requiredConfigs = @(
    (Join-Path $configDir "post_init.sh"),
    (Join-Path $configDir "showcase-node1.yml"),
    (Join-Path $configDir "showcase-node2.yml"),
    (Join-Path $configDir "showcase-node3.yml")
)

foreach ($cfg in $requiredConfigs) {
    if (-not (Test-Path $cfg)) {
        Write-Error "Required showcase config missing: $cfg"
        exit 1
    }
}

# 3. Check for conflicting port bindings by other processes/containers
$portMap = @(
    @{ Name = "Node 1 PG"; Port = $Node1PgPort; Container = "showcase-pg-node1" },
    @{ Name = "Node 1 Patroni"; Port = $Node1PatroniPort; Container = "showcase-pg-node1" },
    @{ Name = "Node 2 PG"; Port = $Node2PgPort; Container = "showcase-pg-node2" },
    @{ Name = "Node 2 Patroni"; Port = $Node2PatroniPort; Container = "showcase-pg-node2" },
    @{ Name = "Node 3 PG"; Port = $Node3PgPort; Container = "showcase-pg-node3" },
    @{ Name = "Node 3 Patroni"; Port = $Node3PatroniPort; Container = "showcase-pg-node3" }
)

$conflicts = @()
foreach ($entry in $portMap) {
    $p = $entry.Port
    $runningOnPort = (docker ps --filter "publish=$p" --format "{{.Names}}" 2>$null) -split "`r?`n" | Where-Object { $_ -ne "" }
    foreach ($cName in $runningOnPort) {
        if ($cName -ne $entry.Container) {
            $conflicts += "$($entry.Name) (port $p, currently used by: $cName)"
        }
    }
}

if ($conflicts.Count -gt 0) {
    Write-Error "Host ports already in use:`n  - $($conflicts -join "`n  - ")`nPlease stop conflicting containers (e.g. existing patroni-pg-node containers) before starting showcase."
    exit 1
}

# 4. Ensure bridge network exists
$netId = (docker network ls --filter "name=^${NetworkName}$" -q 2>$null)
if (-not $netId) {
    Write-Host "Creating dedicated bridge network: $NetworkName..."
    docker network create --driver bridge $NetworkName | Out-Null
} else {
    Write-Host "Reusing existing bridge network: $NetworkName."
}

# 5. Ensure Docker images exist (pinned, no :latest)
$etcdImage = "quay.io/coreos/etcd:v3.5.11"
$etcdId = (docker images -q $etcdImage 2>$null)
if (-not $etcdId) {
    Write-Host "Pulling pinned etcd image: $etcdImage..."
    docker pull $etcdImage
}

$patroniImage = "patroni-showcase:v4.0.4-pg17.2"
$patroniId = (docker images -q $patroniImage 2>$null)
if (-not $patroniId) {
    Write-Host "Building pinned Patroni showcase image: $patroniImage..."
    docker build -t $patroniImage -f $dockerfilePath $scriptDir
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Failed to build $patroniImage"
        exit 1
    }
}

# 6. Ensure persistent named volumes exist
$volumes = @(
    "showcase-etcd-data",
    "showcase-pg-node1-data",
    "showcase-pg-node2-data",
    "showcase-pg-node3-data"
)

foreach ($vol in $volumes) {
    $volId = (docker volume ls --filter "name=^${vol}$" -q 2>$null)
    if (-not $volId) {
        Write-Host "Creating volume: $vol..."
        docker volume create $vol | Out-Null
    }
}

# 7. Start showcase-etcd
$etcdContainer = "showcase-etcd"
$etcdRunning = (docker ps --filter "name=^/${etcdContainer}$" --format "{{.Status}}" 2>$null)
if ($etcdRunning -match "Up") {
    Write-Host "Container $etcdContainer is already running."
} else {
    $etcdExists = (docker ps -a --filter "name=^/${etcdContainer}$" --format "{{.Names}}" 2>$null)
    if ($etcdExists) {
        Write-Host "Starting existing stopped container: $etcdContainer..."
        docker start $etcdContainer | Out-Null
    } else {
        Write-Host "Starting new container: $etcdContainer..."
        docker run -d `
            --name $etcdContainer `
            --network $NetworkName `
            --restart unless-stopped `
            -v showcase-etcd-data:/etcd-data `
            $etcdImage `
            etcd `
            --name=showcase-etcd `
            --data-dir=/etcd-data `
            --listen-client-urls=http://0.0.0.0:2379 `
            --advertise-client-urls=http://showcase-etcd:2379 `
            --listen-peer-urls=http://0.0.0.0:2380 `
            --initial-advertise-peer-urls=http://showcase-etcd:2380 `
            --initial-cluster=showcase-etcd=http://showcase-etcd:2380 `
            --initial-cluster-token=showcase-etcd-token `
            --initial-cluster-state=new | Out-Null
    }
}

# Wait for etcd endpoint health
Write-Host "Waiting for showcase-etcd health check..."
$etcdReady = $false
for ($i = 0; $i -lt 15; $i++) {
    $health = docker exec $etcdContainer etcdctl endpoint health 2>&1
    if ($health -match "is healthy") {
        $etcdReady = $true
        break
    }
    Start-Sleep -Seconds 1
}
if (-not $etcdReady) {
    Write-Error "showcase-etcd failed to reach healthy state."
    exit 1
}

# 8. Start showcase Patroni nodes
$cfgMount = "$($configDir.Replace('\', '/'))"

$nodes = @(
    @{ Id = 1; Name = "showcase-pg-node1"; PgPort = $Node1PgPort; PatroniPort = $Node1PatroniPort; Cfg = "showcase-node1.yml"; Vol = "showcase-pg-node1-data" },
    @{ Id = 2; Name = "showcase-pg-node2"; PgPort = $Node2PgPort; PatroniPort = $Node2PatroniPort; Cfg = "showcase-node2.yml"; Vol = "showcase-pg-node2-data" },
    @{ Id = 3; Name = "showcase-pg-node3"; PgPort = $Node3PgPort; PatroniPort = $Node3PatroniPort; Cfg = "showcase-node3.yml"; Vol = "showcase-pg-node3-data" }
)

foreach ($node in $nodes) {
    $cName = $node.Name
    $cRunning = (docker ps --filter "name=^/${cName}$" --format "{{.Status}}" 2>$null)
    if ($cRunning -match "Up") {
        Write-Host "Container $cName is already running."
    } else {
        $cExists = (docker ps -a --filter "name=^/${cName}$" --format "{{.Names}}" 2>$null)
        if ($cExists) {
            Write-Host "Starting existing container: $cName..."
            docker start $cName | Out-Null
        } else {
            Write-Host "Launching container: $cName (PG:$($node.PgPort), REST:$($node.PatroniPort))..."
            docker run -d `
                --name $cName `
                --hostname $cName `
                --network $NetworkName `
                --restart unless-stopped `
                -p "127.0.0.1:$($node.PgPort):5432" `
                -p "127.0.0.1:$($node.PatroniPort):8008" `
                -v "${cfgMount}:/home/postgres/config:ro" `
                -v "$($node.Vol):/home/postgres/data" `
                $patroniImage `
                "/home/postgres/config/$($node.Cfg)" | Out-Null
        }
    }
}

# 9. Wait until Patroni reports all 3 members through http://127.0.0.1:$Node1PatroniPort/cluster
Write-Host "Waiting up to ${TimeoutSeconds}s for Patroni cluster to report 3 members on http://127.0.0.1:$Node1PatroniPort/cluster..."
$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
$clusterData = $null

while ((Get-Date) -lt $deadline) {
    try {
        $clusterData = Invoke-RestMethod -Uri "http://127.0.0.1:$Node1PatroniPort/cluster" -TimeoutSec 2 -ErrorAction Stop
        if ($clusterData -and $clusterData.members -and ($clusterData.members.Count -ge 3)) {
            $leader = $clusterData.members | Where-Object { $_.role -eq "leader" }
            if ($leader) {
                break
            }
        }
    } catch {
        # Patroni REST API still initializing
    }
    Start-Sleep -Seconds 2
}

if (-not ($clusterData -and $clusterData.members -and ($clusterData.members.Count -ge 3))) {
    Write-Error "Timed out waiting for Patroni cluster to report 3 members via http://127.0.0.1:$Node1PatroniPort/cluster."
    exit 1
}

Write-Host "`n======================================================="
Write-Host " Patroni Network Showcase Cluster is UP and HEALTHY!"
Write-Host "======================================================="
Write-Host "Scope: $($clusterData.scope)"
foreach ($m in $clusterData.members) {
    Write-Host " - Member: $($m.name) | Role: $($m.role) | State: $($m.state) | API: $($m.api_url) | HostPort: $($m.port)"
}
Write-Host "`nREST API: http://127.0.0.1:$Node1PatroniPort/cluster"
Write-Host "======================================================="
