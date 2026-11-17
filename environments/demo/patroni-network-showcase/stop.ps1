<#
.SYNOPSIS
    Stops and removes only showcase Patroni containers.

.DESCRIPTION
    Cleanly stops and removes showcase containers (showcase-pg-node1, showcase-pg-node2,
    showcase-pg-node3, and showcase-etcd). Does NOT stop or touch other project containers.
    Preserves volumes and the dedicated bridge network unless -Purge is specified.
#>

[CmdletBinding()]
param(
    [switch]$Purge,
    [string]$NetworkName = "pg-cluster-showcase-net"
)

$ErrorActionPreference = "Continue"

$containers = @(
    "showcase-pg-node1",
    "showcase-pg-node2",
    "showcase-pg-node3",
    "showcase-etcd"
)

Write-Host "Stopping and removing showcase containers..."
foreach ($c in $containers) {
    $exists = docker ps -a --filter "name=^/${c}$" --format "{{.Names}}" 2>$null
    if ($exists) {
        Write-Host " - Stopping $c..."
        docker stop $c -t 5 2>$null | Out-Null
        Write-Host " - Removing $c..."
        docker rm -f $c 2>$null | Out-Null
    } else {
        Write-Host " - Container $c does not exist (skipped)."
    }
}

if ($Purge) {
    Write-Host "`nPurge switch specified. Removing showcase named volumes and network..."
    
    $volumes = @(
        "showcase-etcd-data",
        "showcase-pg-node1-data",
        "showcase-pg-node2-data",
        "showcase-pg-node3-data"
    )

    foreach ($v in $volumes) {
        $vExists = docker volume inspect $v 2>$null
        if ($LASTEXITCODE -eq 0) {
            Write-Host " - Removing volume $v..."
            docker volume rm $v 2>$null | Out-Null
        }
    }

    $netExists = docker network inspect $NetworkName 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Host " - Removing network $NetworkName..."
        docker network rm $NetworkName 2>$null | Out-Null
    }
} else {
    Write-Host "`nShowcase containers stopped. Volumes and network preserved. (Use -Purge to delete volumes and network)."
}

Write-Host "Done."
