#!/usr/bin/env python3
"""
Read-only check of every `postgres` plugin monitor through the Site24x7 REST API.

Needs S247_CLIENT_ID, S247_CLIENT_SECRET and S247_REFRESH_TOKEN in the repo's
.env (a Zoho Self Client with Site24x7.*.Read scopes, India data center).

For each monitor it reports: up/down, how many metrics the registered template
has, which of them received no data in the period, and which metrics the
plugin catalogue defines but the template does not have. Full API responses are
saved under .api_reports/ for deeper inspection.

Usage: python scripts/api_check.py [--period 0|1|2] [--name-prefix postgres]
  period: 0 = last hour, 1 = last 24 hours, 2 = last 7 days
"""

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ACCOUNTS = "https://accounts.zoho.in/oauth/v2/token"
API = "https://www.site24x7.in/api"
OUT_DIR = os.path.join(ROOT, ".api_reports")


def load_env():
    env = {}
    with open(os.path.join(ROOT, ".env"), encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line.startswith("S247_") and "=" in line:
                k, v = line.split("=", 1)
                env[k] = v
    missing = [k for k in ("S247_CLIENT_ID", "S247_CLIENT_SECRET", "S247_REFRESH_TOKEN") if not env.get(k)]
    if missing:
        sys.exit("missing in .env: " + ", ".join(missing))
    return env


def access_token(env):
    body = urllib.parse.urlencode({
        "refresh_token": env["S247_REFRESH_TOKEN"], "client_id": env["S247_CLIENT_ID"],
        "client_secret": env["S247_CLIENT_SECRET"], "grant_type": "refresh_token"}).encode()
    tok = json.load(urllib.request.urlopen(urllib.request.Request(ACCOUNTS, data=body), timeout=20))
    if "access_token" not in tok:
        sys.exit("token refresh failed: %s" % tok.get("error", "unknown"))
    return tok["access_token"]


def api(token, path):
    req = urllib.request.Request(API + path, headers={
        "Authorization": "Zoho-oauthtoken " + token, "Accept": "application/json; version=2.0"})
    try:
        return json.load(urllib.request.urlopen(req, timeout=60)).get("data", {})
    except urllib.error.HTTPError as e:
        return {"_error": e.code, "_body": e.read()[:300].decode(errors="replace")}


def catalogue_keys():
    """Metric names the plugin can emit, in the API's key form (spaces removed)."""
    sys.path.insert(0, os.path.join(ROOT, "postgres"))
    import postgres as pg
    return {re.sub(r"[^A-Za-z0-9]", "", m.name): m.name for m in pg.all_metric_defs() if m.kind is not str}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--period", default="0")
    ap.add_argument("--name-prefix", default="postgres")
    args = ap.parse_args()

    token = access_token(load_env())
    os.makedirs(OUT_DIR, exist_ok=True)
    monitors = [m for m in api(token, "/monitors")
                if m.get("type") == "PLUGIN" and m.get("display_name", "").lower().startswith(args.name_prefix)]
    expected = catalogue_keys()
    summary = []
    for m in sorted(monitors, key=lambda m: m["display_name"]):
        mid, name = m["monitor_id"], m["display_name"]
        status = api(token, "/current_status/" + mid)
        perf = api(token, "/reports/performance/%s?period=%s" % (mid, args.period))
        with open(os.path.join(OUT_DIR, "%s.json" % re.sub(r"[^A-Za-z0-9_-]", "_", name)), "w", encoding="utf-8") as fh:
            json.dump({"status": status, "performance": perf}, fh, indent=1)
        charts = perf.get("chart_info", {}) if isinstance(perf, dict) else {}
        # chart_data: [{"<n>": {"<Attr>": {"chart_data": [[time, value], ...], ...}}}, ...]
        points = {}
        for entry in (perf.get("chart_data") or []) if isinstance(perf, dict) else []:
            for series in entry.values():
                for attr, body in (series or {}).items():
                    vals = [p[1] for p in (body or {}).get("chart_data") or [] if len(p) > 1 and p[1] is not None]
                    points[attr] = points.get(attr, 0) + len(vals)
        # child-table columns ("<id>_<column>") are charted per row, not here
        no_data = sorted(k for k in charts if not re.match(r"^\d+_", k) and not points.get(k))
        not_in_template = sorted(v for k, v in expected.items() if k not in charts)
        row = {"name": name, "status": status.get("status"), "template_metrics": len(charts),
               "no_data": no_data, "not_in_template": not_in_template,
               "last_polled": status.get("last_polled_time")}
        summary.append(row)
        print("%-36s status=%s template=%3d no_data=%d missing_from_template=%d" % (
            name, row["status"], row["template_metrics"], len(no_data), len(not_in_template)))
        if no_data:
            print("    no data:", ", ".join(no_data[:20]) + (" ..." if len(no_data) > 20 else ""))
        if not_in_template:
            print("    not in template:", ", ".join(not_in_template[:20]) + (" ..." if len(not_in_template) > 20 else ""))
    with open(os.path.join(OUT_DIR, "summary.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=1)
    print("full responses in", OUT_DIR)


if __name__ == "__main__":
    main()
