#!/usr/bin/env python3
import psycopg2

def parse_address_map(raw):
    m = {}
    if not raw:
        return m
    for part in raw.split(","):
        part = part.strip()
        if "=" in part:
            src, dst = part.split("=", 1)
        elif "->" in part:
            src, dst = part.split("->", 1)
        else:
            continue
        src = src.strip()
        dst = dst.strip()
        m[src] = dst
        # also match host without port or host:port
        if ":" in src:
            shost, sport = src.split(":", 1)
            try:
                m[(shost, int(sport))] = dst
            except ValueError:
                pass
    return m

def map_addr(host, port, amap):
    if (host, port) in amap:
        target = amap[(host, port)]
        if ":" in target:
            th, tp = target.split(":", 1)
            return th, int(tp)
        return target, port
    if host in amap:
        target = amap[host]
        if ":" in target:
            th, tp = target.split(":", 1)
            return th, int(tp)
        return target, port
    return host, port

def test_discovery():
    amap = parse_address_map("pg-mm1:5432=127.0.0.1:5451,pg-mm2:5432=127.0.0.1:5452,pg-mm3:5432=127.0.0.1:5453")
    print("Address map parsed:", amap)

    seed_host = "127.0.0.1"
    seed_port = 5451
    conn = psycopg2.connect(host=seed_host, port=seed_port, user="site24x7", password="site24x7", dbname="postgres")
    cur = conn.cursor()

    cur.execute("SELECT subname, subconninfo FROM pg_subscription;")
    subs = cur.fetchall()
    print("Subscriptions found on seed:", len(subs))

    peers = []
    for subname, conninfo in subs:
        host, port = None, None
        for tok in conninfo.split():
            if tok.startswith("host="):
                host = tok.split("=", 1)[1]
            elif tok.startswith("port="):
                port = int(tok.split("=", 1)[1])
        mapped_h, mapped_p = map_addr(host, port or 5432, amap)
        print(f"  sub: {subname} -> internal {host}:{port} -> mapped {mapped_h}:{mapped_p}")
        peers.append((mapped_h, mapped_p))

    conn.close()

    # Now verify each discovered peer is reachable and healthy
    for ph, pp in peers:
        pconn = psycopg2.connect(host=ph, port=pp, user="site24x7", password="site24x7", dbname="postgres")
        pcur = pconn.cursor()
        pcur.execute("SELECT pg_is_in_recovery();")
        in_rec = pcur.fetchone()[0]
        pconn.close()
        print(f"  Reachable peer {ph}:{pp} - in_recovery={in_rec}")

if __name__ == "__main__":
    test_discovery()
