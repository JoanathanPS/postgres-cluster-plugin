#!/usr/bin/env python3
"""
Site24x7 payload validator — the "builder + tester" for a plugin that has neither.

Why this exists
---------------
A Site24x7 plugin has no compiler and no CI: the agent runs your script and posts
whatever JSON came out. If the JSON breaks a platform rule the failure is silent
and remote — the metric, the tab, or the whole table just never appears in the
console, and nobody tells you. Every one of the rules below is a documented
Site24x7 limit (10 tables / 15 columns / 25 rows / 5 string columns / 200 metrics
/ 520-char name / 50 s script budget).

This tool takes the plugin's JSON — pasted from a real agent run, or produced by
`postgres_cluster.py --json-out out.json` — and produces:

  * a ranked list of violations (errors block data, warnings are suspect)
  * coverage per tab, so you see which tabs are thin
  * duplicate-name and enum/unit sanity checks
  * a diff mode, to prove a change only changed what you meant to change

Usage
  python3 s247_validate.py out.json
  python3 s247_validate.py out.json --expect baseline.json      # diff mode
  python3 s247_validate.py out.json --json report.json
  python3 s247_validate.py --selftest                           # prove the validator
Exit code: 0 clean, 1 errors found, 2 bad input.

No third-party dependencies. Python 3.9+.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any, Dict, List, Tuple

# ---------------------------------------------------------------- platform rules
LIMITS = {
    "max_tables": 10,
    "max_columns": 15,
    "max_rows": 25,
    "max_string_columns": 5,       # includes "name"
    "max_name_chars": 520,
    "max_string_chars": 100,
    "max_metrics": 200,
}
RESERVED = {"plugin_version", "heartbeat_required", "status", "msg",
            "units", "tabs", "s4z7config"}
# keys that are structural, not metrics, and are therefore not counted
# against the 200-metric budget nor required to live in a tab
STRUCTURAL = RESERVED | {"units", "tabs", "s4z7config"}

METRIC_NAME_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_ .()%/+-]*$")


class Violation:
    __slots__ = ("level", "code", "where", "detail")

    def __init__(self, level: str, code: str, where: str, detail: str):
        self.level, self.code, self.where, self.detail = level, code, where, detail

    def __str__(self) -> str:
        tag = "ERROR  " if self.level == "error" else "warning"
        return f"{tag} [{self.code}] {self.where}: {self.detail}"


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _is_string(v: Any) -> bool:
    return isinstance(v, str)


def detect_tables(doc: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    """A child table is a top-level key whose value is a list of dicts."""
    out = {}
    for key, val in doc.items():
        if key in STRUCTURAL:
            continue
        if isinstance(val, list) and (not val or all(isinstance(r, dict) for r in val)):
            out[key] = val
    return out


def detect_metrics(doc: Dict[str, Any], tables: Dict[str, List[dict]]) -> Dict[str, Any]:
    """Numeric/string scalars at top level, excluding structural keys and tables."""
    return {
        k: v for k, v in doc.items()
        if k not in STRUCTURAL and k not in tables and (_is_number(v) or _is_string(v))
    }


def validate(doc: Any) -> Tuple[List[Violation], Dict[str, Any]]:
    v: List[Violation] = []
    stats: Dict[str, Any] = {}

    if not isinstance(doc, dict):
        v.append(Violation("error", "NOT_AN_OBJECT", "payload", "plugin output must be a JSON object"))
        return v, stats

    # ---- 1. mandatory / reserved keys
    if "plugin_version" not in doc:
        v.append(Violation("error", "MISSING_PLUGIN_VERSION", "payload", "plugin_version is mandatory"))
    pv = doc.get("plugin_version")
    if pv is not None and not (isinstance(pv, int) or (isinstance(pv, str) and pv.isdigit())):
        v.append(Violation("error", "BAD_PLUGIN_VERSION", "plugin_version", f"must be a whole number, got {pv!r}"))

    if "status" not in doc:
        v.append(Violation("error", "MISSING_STATUS", "payload", "status is reserved/mandatory"))
    elif doc.get("status") not in (0, 1):
        v.append(Violation("error", "BAD_STATUS", "status", f"must be 0 or 1, got {doc.get('status')!r}"))

    if "heartbeat_required" not in doc:
        v.append(Violation("warning", "MISSING_HEARTBEAT", "payload", "heartbeat_required absent; alerting on no-data may not fire"))

    if doc.get("msg") is not None and not isinstance(doc.get("msg"), str):
        v.append(Violation("error", "BAD_MSG", "msg", "msg must be a string"))
    elif isinstance(doc.get("msg"), str) and len(doc["msg"]) > 400:
        v.append(Violation("warning", "LONG_MSG", "msg",
                           f"{len(doc['msg'])} chars; Site24x7 shows a truncated line on the monitor card"))

    # ---- 2. tables
    tables = detect_tables(doc)
    stats["tables"] = sorted(tables)
    if len(tables) > LIMITS["max_tables"]:
        v.append(Violation("error", "TOO_MANY_TABLES", "payload",
                           f"{len(tables)} tables > {LIMITS['max_tables']} allowed; extras are dropped server-side"))

    for tname, rows in tables.items():
        # 2a. rows
        if len(rows) > LIMITS["max_rows"]:
            v.append(Violation("error", "TOO_MANY_ROWS", tname,
                               f"{len(rows)} rows > {LIMITS['max_rows']}; the tail is dropped silently"))
        if not rows:
            v.append(Violation("warning", "EMPTY_TABLE", tname,
                               "table present but empty; console keeps the last known rows"))
            continue

        # 2b. columns (union across rows, because row shapes must agree)
        col_keys: List[str] = []
        for r in rows:
            for k in r.keys():
                if k not in col_keys:
                    col_keys.append(k)
        if len(col_keys) > LIMITS["max_columns"]:
            v.append(Violation("error", "TOO_MANY_COLUMNS", tname,
                               f"{len(col_keys)} columns > {LIMITS['max_columns']}: {col_keys}"))

        # 2c. name column
        if "name" not in col_keys:
            v.append(Violation("error", "NO_NAME_COLUMN", tname,
                               '"name" is the reserved row key; without it rows cannot be addressed'))
        # 2d. status column
        if "status" not in col_keys:
            v.append(Violation("warning", "NO_STATUS_COLUMN", tname,
                               "no per-row status: a dead node keeps its last (green) row"))
        # 2e. schema consistency between rows
        shapes = {tuple(sorted(r.keys())) for r in rows}
        if len(shapes) > 1:
            v.append(Violation("error", "RAGGED_ROWS", tname,
                               f"rows have {len(shapes)} different column sets; keep one schema per table"))

        # 2f. string budget and lengths
        str_cols = set()
        for r in rows:
            for k, val in r.items():
                if _is_string(val):
                    str_cols.add(k)
        if len(str_cols) > LIMITS["max_string_columns"]:
            v.append(Violation("error", "TOO_MANY_STRING_COLUMNS", tname,
                               f"{len(str_cols)} string columns {sorted(str_cols)} > "
                               f"{LIMITS['max_string_columns']} (name included). Encode states as ints."))
        for r in rows:
            nm = r.get("name")
            if isinstance(nm, str) and len(nm) > LIMITS["max_name_chars"]:
                v.append(Violation("error", "NAME_TOO_LONG", tname,
                                   f"name is {len(nm)} chars > {LIMITS['max_name_chars']}"))
            for k, val in r.items():
                if k == "name" or not _is_string(val):
                    continue
                if len(val) > LIMITS["max_string_chars"]:
                    v.append(Violation("warning", "STRING_TRUNCATED", f"{tname}.{k}",
                                       f"{len(val)} chars will be truncated to {LIMITS['max_string_chars']}: {val[:40]!r}…"))

        # 2g. duplicate row names
        names = [r.get("name") for r in rows if isinstance(r.get("name"), str)]
        dupes = {n for n in names if names.count(n) > 1}
        if dupes:
            v.append(Violation("error", "DUPLICATE_ROW_NAME", tname,
                               f"duplicate name(s) {sorted(dupes)}; rows will overwrite each other"))

        # 2h. per-row status type
        for r in rows:
            if "status" in r and r["status"] not in (0, 1, True, False):
                v.append(Violation("error", "BAD_ROW_STATUS", tname,
                                   f"row {r.get('name')!r} status must be 0/1, got {r['status']!r}"))
                break

    # ---- 3. metrics
    metrics = detect_metrics(doc, tables)
    stats["metric_count"] = len(metrics)
    if len(metrics) > LIMITS["max_metrics"]:
        v.append(Violation("error", "TOO_MANY_METRICS", "payload",
                           f"{len(metrics)} metrics > {LIMITS['max_metrics']}"))
    for name, val in metrics.items():
        if not METRIC_NAME_RE.match(name):
            v.append(Violation("warning", "ODD_METRIC_NAME", name,
                               "metric names with unusual characters can break threshold configuration"))
        if _is_number(val) and (val != val):  # NaN
            v.append(Violation("error", "NAN_METRIC", name, "NaN is not valid JSON for a metric"))

    # at least one numeric parent metric, or the plugin refuses to register
    numeric = [k for k, val in metrics.items() if _is_number(val)]
    if not numeric:
        v.append(Violation("error", "NO_NUMERIC_METRIC", "payload",
                           "at least one integer parent metric is required to register the plugin"))

    # ---- 4. units <-> metrics <-> tabs, both directions
    units = doc.get("units") or {}
    tabs_raw = doc.get("tabs") or {}
    tabs = tabs_raw.get("tabs", tabs_raw) if isinstance(tabs_raw, dict) else {}

    tab_members: Dict[str, List[str]] = {}
    for tab_name, spec in tabs.items():
        for metric in (spec or {}).get("tablist", []) or []:
            tab_members.setdefault(metric, []).append(tab_name)
    stats["tabs"] = {t: len(s.get("tablist", []) or []) for t, s in tabs.items() if isinstance(s, dict)}

    for metric, where in tab_members.items():
        if len(where) > 1:
            v.append(Violation("warning", "METRIC_IN_MULTIPLE_TABS", metric, f"listed in tabs {where}"))
        if metric not in metrics and metric not in tables:
            v.append(Violation("error", "TAB_METRIC_NEVER_EMITTED", metric,
                               f"declared in tab {where[0]} but absent from the payload — the chart will be empty "
                               f"(this is the #1 silent bug in Site24x7 plugins)"))
        if metric not in units:
            v.append(Violation("warning", "TAB_METRIC_NO_UNIT", metric, "no entry in units{}"))

    for metric in metrics:
        if metric not in tab_members:
            v.append(Violation("warning", "METRIC_NOT_IN_ANY_TAB", metric,
                               "emitted but not shown in any tab; it can be alerted on but not seen"))
        if metric not in units and _is_number(metrics[metric]):
            v.append(Violation("warning", "METRIC_NO_UNIT", metric, "numeric metric without a unit"))

    for unit_name in units:
        if unit_name not in metrics and unit_name not in tables:
            v.append(Violation("warning", "UNIT_ORPHAN", unit_name,
                               "units{} entry for something never emitted"))

    # ---- 5. tab order sanity
    for tab_name, spec in tabs.items():
        order = (spec or {}).get("order")
        if order is None:
            v.append(Violation("warning", "TAB_NO_ORDER", tab_name, "no order field; tab position is undefined"))
        elif not str(order).isdigit():
            v.append(Violation("warning", "TAB_BAD_ORDER", tab_name, f"order must be numeric, got {order!r}"))

    # ---- 6. coverage
    stats["coverage"] = {t: len(s.get("tablist", []) or []) for t, s in tabs.items() if isinstance(s, dict)}
    stats["metrics_emitted"] = len(metrics)
    stats["metrics_declared_in_tabs"] = sum(len(x) for x in tab_members.values())
    stats["string_metrics"] = sorted(k for k, val in metrics.items() if _is_string(val))
    return v, stats


def diff(baseline: Dict[str, Any], current: Dict[str, Any]) -> List[Violation]:
    """Prove a change only changed what you meant."""
    out: List[Violation] = []
    b_tables = detect_tables(baseline)
    c_tables = detect_tables(current)
    for t in sorted(set(c_tables) - set(b_tables)):
        out.append(Violation("warning", "NEW_TABLE", t, "table did not exist in the baseline"))
    for t in sorted(set(b_tables) - set(c_tables)):
        out.append(Violation("error", "REMOVED_TABLE", t, "table disappeared — break existing templates/thresholds"))
    for t in sorted(set(b_tables) & set(c_tables)):
        b_cols = set().union(*[set(r) for r in b_tables[t]]) if b_tables[t] else set()
        c_cols = set().union(*[set(r) for r in c_tables[t]]) if c_tables[t] else set()
        for col in sorted(c_cols - b_cols):
            out.append(Violation("warning", "NEW_COLUMN", f"{t}.{col}", "new column"))
        for col in sorted(b_cols - c_cols):
            out.append(Violation("error", "REMOVED_COLUMN", f"{t}.{col}",
                                 "column disappeared — existing table widgets/thresholds break"))
        if len(c_tables[t]) != len(b_tables[t]):
            out.append(Violation("warning", "ROW_COUNT_CHANGED", t,
                                 f"{len(b_tables[t])} -> {len(c_tables[t])} rows"))

    b_m = set(detect_metrics(baseline, b_tables))
    c_m = set(detect_metrics(current, c_tables))
    for m in sorted(b_m - c_m):
        out.append(Violation("error", "REMOVED_METRIC", m, "metric disappeared — existing alarms on it go blind"))
    for m in sorted(c_m - b_m):
        out.append(Violation("warning", "NEW_METRIC", m, "new metric (expected after plugin_version bump)"))
    if baseline.get("plugin_version") == current.get("plugin_version") and (b_m != c_m or set(b_tables) != set(c_tables)):
        out.append(Violation("error", "VERSION_NOT_BUMPED", "plugin_version",
                             "metric surface changed without bumping plugin_version; "
                             "Site24x7 will not create a new template and old thresholds won't map"))
    return out


def selftest() -> int:
    """Prove the validator catches what it claims to catch."""
    cases = []

    good = {
        "plugin_version": 5, "heartbeat_required": True, "status": 1,
        "Primary_Up": 1, "Primary_Commits_s": 12.5,
        "units": {"Primary_Up": "flag", "Primary_Commits_s": "/s"},
        "tabs": {"tabs": {"Primary": {"order": "1", "tablist": ["Primary_Up", "Primary_Commits_s"]}}},
        "Cluster_Nodes": [{"name": "pg1", "role": 1, "status": 1, "last_seen_s": 0}],
    }
    cases.append(("clean payload", good, 0))

    tab_orphan = json.loads(json.dumps(good))
    tab_orphan["tabs"]["tabs"]["Primary"]["tablist"].append("Primary_Not_Emitted")
    cases.append(("tab declares missing metric", tab_orphan, 1))

    too_many_rows = json.loads(json.dumps(good))
    too_many_rows["Cluster_Nodes"] = [{"name": f"n{i}", "status": 1} for i in range(26)]
    cases.append(("26 rows", too_many_rows, 1))

    too_many_str = json.loads(json.dumps(good))
    too_many_str["Cluster_Nodes"] = [{"name": "pg1", "status": 1, "a": "x", "b": "x", "c": "x", "d": "x", "e": "x"}]
    cases.append(("6 string columns", too_many_str, 1))

    ragged = json.loads(json.dumps(good))
    ragged["Cluster_Nodes"] = [{"name": "a", "status": 1}, {"name": "b", "status": 1, "x": 1}]
    cases.append(("ragged rows", ragged, 1))

    dup = json.loads(json.dumps(good))
    dup["Cluster_Nodes"] = [{"name": "a", "status": 1}, {"name": "a", "status": 1}]
    cases.append(("duplicate names", dup, 1))

    no_status = json.loads(json.dumps(good))
    no_status["status"] = 7
    cases.append(("bad status", no_status, 1))

    bad_row_status = json.loads(json.dumps(good))
    bad_row_status["Cluster_Nodes"] = [{"name": "a", "status": "down"}]
    cases.append(("string row status", bad_row_status, 1))

    fails = 0
    for label, doc, expect_errors in cases:
        v, _ = validate(doc)
        n_err = sum(1 for x in v if x.level == "error")
        ok = (n_err > 0) == bool(expect_errors)
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}: expected errors={bool(expect_errors)}, got {n_err}")
        if not ok:
            fails += 1
            for x in v[:4]:
                print("        ", x)

    # diff mode
    base = json.loads(json.dumps(good))
    cur = json.loads(json.dumps(good))
    del cur["Primary_Commits_s"]
    cur["tabs"]["tabs"]["Primary"]["tablist"] = ["Primary_Up"]
    dv = diff(base, cur)
    ok = any(x.code == "REMOVED_METRIC" for x in dv) and any(x.code == "VERSION_NOT_BUMPED" for x in dv)
    print(f"  [{'PASS' if ok else 'FAIL'}] diff detects removed metric + unbumped version")
    fails += 0 if ok else 1

    print(f"\nselftest: {'OK' if not fails else f'{fails} FAILED'}")
    return 0 if not fails else 1


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description="Validate a Site24x7 plugin payload against platform limits.")
    ap.add_argument("payload", nargs="?", help="plugin JSON output file")
    ap.add_argument("--expect", help="baseline JSON to diff against")
    ap.add_argument("--json", dest="json_out", help="write the machine-readable report here")
    ap.add_argument("--selftest", action="store_true", help="run the validator's own tests")
    ap.add_argument("--quiet", action="store_true", help="errors only")
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()
    if not args.payload:
        ap.error("payload file required (or --selftest)")

    try:
        with open(args.payload, "r", encoding="utf-8") as f:
            doc = json.load(f)
    except Exception as e:
        print(f"ERROR  [BAD_JSON] {args.payload}: {e}")
        return 2

    violations, stats = validate(doc)
    if args.expect:
        try:
            with open(args.expect, "r", encoding="utf-8") as f:
                base = json.load(f)
            violations += diff(base, doc)
        except Exception as e:
            violations.append(Violation("error", "BASELINE_UNREADABLE", args.expect, str(e)))

    errors = [x for x in violations if x.level == "error"]
    warns = [x for x in violations if x.level == "warning"]

    print(f"payload: {args.payload}")
    print(f"tables: {len(stats.get('tables', []))}/{LIMITS['max_tables']}  "
          f"metrics: {stats.get('metric_count', 0)}/{LIMITS['max_metrics']}  "
          f"tabs: {len(stats.get('tabs', {}))}")
    for t, n in (stats.get("coverage") or {}).items():
        print(f"  tab {t!r}: {n} metrics")
    if stats.get("string_metrics"):
        print(f"  string metrics ({len(stats['string_metrics'])}): {', '.join(stats['string_metrics'][:8])}")

    print()
    for x in violations if not args.quiet else errors:
        print(x)

    print(f"\n{len(errors)} error(s), {len(warns)} warning(s)")
    verdict = "FAIL" if errors else ("PASS (with warnings)" if warns else "PASS")
    print(f"verdict: {verdict}")

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump({
                "verdict": verdict,
                "stats": stats,
                "violations": [{"level": x.level, "code": x.code, "where": x.where, "detail": x.detail}
                               for x in violations],
            }, f, indent=2)
        print(f"report written to {args.json_out}")

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
