import json
import os

with open("payload_inspect.json", "r", encoding="utf-8") as f:
    data = json.load(f)

print("=" * 80)
print("PAYLOAD INSPECTION ANALYSIS")
print("=" * 80)

# 1. plugin_version
plugin_version = data.get("plugin_version")
print(f"plugin_version: {plugin_version}")

# 2. Tabs extraction
tabs = data.get("tabs", {})
print(f"\nTotal tabs in 'tabs': {len(tabs)}")
print("\nTabs keys in order:")
for i, tab_key in enumerate(tabs.keys(), 1):
    print(f"  {i}. {tab_key}")

# 3. Every tab's tablist
print("\n" + "=" * 80)
print("EVERY TAB'S TABLIST:")
print("=" * 80)
for tab_name, tab_info in tabs.items():
    tablist = tab_info.get("tablist", [])
    print(f"\nTab: '{tab_name}' (Count: {len(tablist)})")
    for m in tablist:
        in_payload = m in data
        in_units = m in data.get("units", {})
        unit_val = data.get("units", {}).get(m, "NO_UNIT")
        val = data.get(m, "<MISSING>")
        status_flag = "OK" if in_payload and in_units else ("NO_UNIT" if in_payload else "MISSING")
        print(f"    - {m}: value={repr(val)}, unit='{unit_val}', status={status_flag}")

# 4. Check specific requested tabs: Primary, Nodes, Replication, WAL and Archiver, Workload
req_tabs = ["Primary", "Nodes", "Replication", "WAL and Archiver", "Workload"]
print("\n" + "=" * 80)
print("REQUESTED TABS PRESENCE CHECK:")
print("=" * 80)
for rt in req_tabs:
    present = rt in tabs
    print(f"  - '{rt}': {'PRESENT' if present else 'ABSENT'}")
    if present:
        tlist = tabs[rt].get("tablist", [])
        missing_payload = [m for m in tlist if m not in data]
        missing_units = [m for m in tlist if m not in data.get("units", {})]
        print(f"      Metrics count: {len(tlist)}")
        print(f"      Missing from payload: {missing_payload if missing_payload else 'None (All present)'}")
        print(f"      Missing from units: {missing_units if missing_units else 'None (All present)'}")

# 5. Schema validation errors or warnings
print("\n" + "=" * 80)
print("SCHEMA VALIDATION & WARNINGS:")
print("=" * 80)
print(f"  status: {data.get('status')}")
print(f"  msg: {data.get('msg')}")
print(f"  Collect_Warnings: {data.get('Collect_Warnings')}")
print(f"  heartbeat_required: {data.get('heartbeat_required')}")
print(f"  s247config: {data.get('s247config')}")

# Check any tablist metric missing across all tabs
all_tablist_metrics = []
for t_name, t_info in tabs.items():
    all_tablist_metrics.extend(t_info.get("tablist", []))

missing_in_payload = [m for m in all_tablist_metrics if m not in data]
missing_in_units = [m for m in all_tablist_metrics if m not in data.get("units", {})]

print(f"\nOverall metrics defined in tabs: {len(all_tablist_metrics)}")
print(f"Metrics in tabs missing in payload: {len(missing_in_payload)} -> {missing_in_payload}")
print(f"Metrics in tabs missing in units: {len(missing_in_units)} -> {missing_in_units}")

# Check child tables
child_tables = [k for k, v in data.items() if isinstance(v, list) and v and isinstance(v[0], dict)]
print(f"\nChild tables discovered in payload ({len(child_tables)}):")
for ct in sorted(child_tables):
    rows = data[ct]
    cols = list(rows[0].keys()) if rows else []
    print(f"  - {ct}: {len(rows)} rows, columns: {cols}")
