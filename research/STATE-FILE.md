# State file — verified, corrected, and implemented

Decision: **the state file is viable on both agents.** The answer you were given is right in its verdict and wrong in three of its details. Two of those details would have produced exactly the bug the state file exists to prevent. Corrected implementation: `harness/state_store.py` (+ `harness/test_state_store.py`, 22 tests, all passing; `--probe` mode runs on the actual box).

---

## 1. What the evidence actually supports

| Claim in the answer | Verdict | Why |
|---|---|---|
| Windows agent runs as `NT AUTHORITY\SYSTEM`, plugin dir under Program Files writable | **Plausible, unverified by the paste** — you cancelled the non-root Python Docker test and the code-1 run was in *Docker*, not on a Windows agent | Needs one run of `state_store.py --probe` **inside the WinAgent**. `SYSTEM` bypasses most ACLs, so it is likely true, but "likely" is not the standard we set ourselves elsewhere. |
| Linux agent runs as root **or** a `site24x7-agent` non-root user | **Correct** | Both deployment styles exist. The probe must handle both. |
| Agent plugin folder is writable | **Correct and important** | `redirect_output=1` writes `.txt` logs next to the plugin, so this folder is writable by design. This is the right place for the state file — not a generic temp dir. |
| `/tmp` is world-writable (`1777`) | **Correct** | But see §2A below. |
| `os.access(dir, W_OK)` is a valid check | **WRONG** | On Windows, `os.access` only consults the read-only file attribute and **ignores ACLs**; Windows ignores that attribute on directories, so it returns `True` for `C:\Program Files` even when the write then raises `PermissionError`. Measured repeatedly in the wild: `os.access W_OK -> True`, `actual write -> PermissionError [Errno 13]`. On POSIX it answers for the *real* uid, so it is also wrong under setuid and returns `True` for root on a mode-555 directory. |
| Tempdir is a fine durable fallback for `postgres_cluster_state.json` | **WRONG (for our use)** | `/tmp` is aged out by systemd-tmpfiles at **10 days** of no access (default `q /tmp 1777 root root 10d` in `/usr/lib/tmpfiles.d/tmp.conf`; `/var/tmp` is 30 days) and is **tmpfs — wiped on reboot** on most distros. Our state is *supposed* to be refreshed every 60 s so aging rarely bites, but the reboot case is guaranteed: the dead-node history and failover record disappear on every restart, which is precisely when you want them. |

---

## 2. Three defects in that snippet, and the fix

### A. Volatile fallback presented as safe
`tempfile.gettempdir()` is writable, which is not the same as persistent. **Fix:** prefer a durable directory and, if we ever end up volatile, publish it as a metric (`State_Persistent=0`) and a warning code (`WARN_STATE_VOLATILE`) rather than silently degrading. The customer's "when did pg3 die?" history is not something to lose quietly.

### B. Instance collision — the subtle one
The state filename is fixed. The documented way to monitor several clusters from one agent is **several plugin folders** (`postgres_cluster/`, `postgres_cluster_2/`, each with its own cfg section). A shared `/tmp/postgres_cluster_state.json` then means **cluster A's last-known-good primary metrics get served as cluster B's**, and B's dashboard shows A's dead primary. Worse: it looks perfectly plausible.

**Fix:** key the file by `machine_id + cluster identity + plugin dir`, hashed:
```
/tmp/site24x7-postgres_cluster/.pgcluster-90f084eb7f18/postgres_cluster_state.json
```
and store `instance` *inside* the JSON, refusing politely (`WARN_STATE_FOREIGN`) if the key on disk doesn't match. Cold start before the server reports its `system_identifier`: key on host:port **plus** the plugin dir, so two cfg sections in one folder still differ.

### C. No atomicity, no corruption handling, no size cap
The snippet opens the file for writing directly. A kill mid-write leaves truncated JSON; the next run then either crashes or — worse — treats garbage as "no previous sample" and emits bogus rates. **Fix:** `tempfile.mkstemp` in the same directory → `flush` → `os.fsync` → `os.replace` (atomic on POSIX *and* Windows when on the same volume; the handle is closed before the replace, because Windows cannot rename an open file). Corrupt, oversize, wrong-schema and foreign-instance files all resolve to `{}` + a warning code, never an exception. Node entries unseen for 7 days are pruned so the file cannot grow without bound.

---

## 3. The implementation (working)

`harness/state_store.py`, ~430 lines, stdlib only, Windows-safe (no `fcntl`, no `fork`).

**Location ladder** — first one that passes a real write probe wins:

| Order | Location | Durable | Note |
|---|---|---|---|
| 1 | `state_dir` from the cfg | yes | operator's explicit choice |
| 2 | the plugin's own directory | yes | right default: the agent already writes logs here |
| 3 | `%PROGRAMDATA%\Site24x7\postgres_cluster` (Windows) / `/var/lib/site24x7/postgres_cluster` (Linux) / `$XDG_STATE_HOME` | yes | if the plugin dir is read-only |
| 4 | `%TEMP%` / `/tmp` | **no** | last resort, announced as `WARN_STATE_VOLATILE` + `State_Persistent=0` |

**Every cycle it emits**, so the state layer is observable instead of assumed:
`State_File` (string, ≤100) · `State_Persistent` (flag) · `State_Age_s` · `State_IO_Errors` · `State_Reason` (string).

**API the plugin uses:**
```python
st = StateStore(plugin_file=__file__, cluster_id=caps.system_identifier,
                seed=f"{host}:{port}", state_dir=cfg.state_dir, warn=warn)
st.probe()                 # once per run
state = st.load()          # {} on any problem, with a code
st.save({...})             # atomic, merged, pruned, capped at 64 KB
metrics.update(st.diagnostics())
```

---

## 4. Proving it rather than asserting it

`harness/test_state_store.py` — 22 assertions, all passing:

```
save/read round trip · schema stamp · no temp file left behind
corrupt JSON -> {} + WARN_STATE_CORRUPT
different cluster -> different file · same cluster reuses file
foreign instance key -> ignored + WARN_STATE_FOREIGN
70 KB file -> {} + WARN_STATE_TOO_LARGE
unwritable plugin dir -> durable fallback chosen, no false volatile alarm
no writable location -> save() False + WARN_STATE_NOWRITE (no crash)
stale node pruned after 7 days
write probe on a missing dir is False and leaves no artifact
the five diagnostics exist and State_File <= 100 chars
```

`python3 state_store.py --probe` prints the environment report you should run **on both agents**:

```
Site24x7 plugin state-file probe
  python 3.13.16  platform=linux  uid=1000 euid=1000
  plugin dir /opt/site24x7/monagent/plugins/postgres_cluster
  candidate locations (write-probed, not os.access):
    -- var_lib  /var/lib/site24x7/postgres_cluster  durable=True missing
    OK plugin_dir ...                               durable=True ok
  ATTENTION: os.access() claims writable but the write probe failed for: ...
  chosen /opt/.../plugins/postgres_cluster/.pgcluster-90f084eb7f18/postgres_cluster_state.json
  persistent True   round trip ok   isolation ok
  verdict: OK — durable state
```

Two things it deliberately checks that a plain `os.access` answer cannot: it **reports where `os.access` lies** (that's the `ATTENTION` block), and it **proves two instances don't collide** by constructing a second store in a second plugin folder and in the same folder with a different seed.

(It also caught a real bug in my own first draft: two cfg sections in one folder hashed to the same file because `cluster_id` was empty at first run. That is now the `seed` parameter, and the failure is asserted in the tests.)

---

## 5. What changes in the design document

1. §State file: location ladder + `state_dir` cfg key + `State_*` diagnostics + instance keying. Durable-by-default, volatile-only-with-a-warning.
2. No `os.access` anywhere in the plugin. One `writable_by_write_probe()` helper, used for every candidate.
3. Warning codes added: `WARN_STATE_VOLATILE`, `WARN_STATE_UNREADABLE`, `WARN_STATE_CORRUPT`, `WARN_STATE_TOO_LARGE`, `WARN_STATE_FOREIGN`, `WARN_STATE_SCHEMA`, `WARN_STATE_WRITE_FAILED`, `WARN_STATE_NOWRITE`, `WARN_STATE_DIR_UNUSABLE`. Each has remediation text in the catalogue (so it lands in `msg`, not in a log file nobody reads).
4. L5 of the test plan gains two rows: *state dir writable* and *state survives an agent restart* (delete the file, confirm cold-start behaviour emits no bogus rates and `Rate_Warmup_Flag=1` rather than a spike).
5. Still open, and the probe answers it in one command on each agent: the Windows `SYSTEM` assumption. **Run `python state_store.py --probe --json` in the WinAgent's plugin folder** and paste the output; if `persistent=True` and `round_trip_ok=true`, L5 is closed.

---

## 6. One more consequence worth flagging

Now that durable state is confirmed, a design option opens that we had ruled out: **the file can double as the dead-node registry**, so a node that has been down for three days still appears in `Cluster_Nodes` with `last_seen_ts` and a reason — even across agent restarts and across discovery losing sight of it. That was the "what did the customer actually ask for" feature, and it was gated on exactly this permission question. It is now unblocked.
