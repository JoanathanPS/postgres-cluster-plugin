#!/usr/bin/env python3
"""
state_store.py — the state file for postgres_cluster.py, done so it cannot
silently lie, plus a probe mode that reports what the agent environment allows.

WHY THIS EXISTS
---------------
The state file carries the three things a stateless plugin cannot:
  1. last-known-good primary metrics (so charts don't flatline while the primary is down)
  2. rates (deltas need a previous sample)
  3. dead-node history ("pg3 died 07:12:44, down 14 m")

Getting it wrong is worse than not having it, because a wrong state file produces
confidently wrong dashboards. The three ways it goes wrong in real deployments:

  A. Silently writing somewhere volatile. `tempfile.gettempdir()` is /tmp, which
     systemd-tmpfiles wipes after 10 days of no access (default `q /tmp 1777 root
     root 10d` in /usr/lib/tmpfiles.d/tmp.conf) and which is tmpfs (gone on reboot)
     on many distros. Your dead-node history and failover record evaporate.
  B. Two plugin instances colliding. The documented way to monitor many clusters
     from one agent is several plugin folders. A fixed filename in /tmp means
     cluster A's last-known-good primary is served as cluster B's.
  C. Trusting os.access(). On Windows os.access(dir, W_OK) only reads the
     read-only attribute, which Windows ignores for directories: it returns True
     for C:\\Program Files even when the write then fails with PermissionError.
     The Windows agent's plugin dir lives under exactly such a path.

So: probe by writing (EAFP), prefer a durable location, key the state by
machine+cluster+name, write atomically, merge instead of overwrite, and expose
where the state actually lives and whether it will survive a reboot as metrics.

USAGE
  # inside the plugin
  from state_store import StateStore
  st = StateStore(plugin_file=__file__, cluster_id="7421...", name="pg-cluster")
  st.probe()            # once per run; records path + persistence
  state = st.load()     # dict, {} when absent/corrupt
  st.save(state)        # atomic, merged, capped
  diag = st.diagnostics()   # -> State_File, State_Persistent, ...

  # standalone diagnosis on the box (or in the agent container)
  python3 state_store.py --probe
  python3 state_store.py --probe --json

Windows-safe: no fcntl, no os.fork, no POSIX-only calls; file handles are closed
before os.replace; UTF-8 explicit.
"""

from __future__ import annotations

import errno
import json
import os
import sys
import tempfile
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

SCHEMA = 1
MAX_STATE_BYTES = 64 * 1024          # keep the file small; it is read every poll
NODE_TTL_DAYS = 7                    # forget nodes unseen for longer than this
DEFAULT_FILENAME = "postgres_cluster_state.json"


# ------------------------------------------------------------------ primitives


def _machine_id() -> str:
    """Stable per-machine identifier, best effort, never raises.

    Linux: /etc/machine-id (systemd) or /var/lib/dbus/machine-id.
    Windows: HKLM\\SOFTWARE\\Microsoft\\Cryptography\\MachineGuid.
    macOS/BSD: ioctl-free fallback to the hostname hash.
    The point is only to namespace shared temp directories between endpoints.
    """
    for path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                value = f.read().strip()
            if value:
                return value[:64]
        except OSError:
            continue
    if os.name == "nt":
        try:
            import winreg  # type: ignore

            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Cryptography",
                0,
                winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0),
            ) as key:
                value, _ = winreg.QueryValueEx(key, "MachineGuid")
                if value:
                    return str(value)[:64]
        except Exception:
            pass
    try:
        import socket

        return "host-" + socket.gethostname()[:48]
    except Exception:
        return "host-unknown"


def _safe_token(raw: str, limit: int = 24) -> str:
    """Filesystem-safe, collision-resistant-enough slug."""
    keep = "".join(c if (c.isalnum() or c in "-_") else "-" for c in str(raw or ""))
    keep = keep.strip("-")
    return (keep[:limit] or "cluster")


def writable_by_write_probe(directory: str) -> Tuple[bool, str]:
    """Can this process actually create a file here?

    Never uses os.access(): on Windows it is meaningless for directories (it only
    reads the read-only attribute and ignores ACLs), on POSIX it answers for the
    real uid which is wrong under setuid. The only honest test is to write.

    Returns (ok, reason).
    """
    if not directory:
        return False, "no directory"
    if not os.path.isdir(directory):
        return False, "not a directory"
    probe = os.path.join(directory, f".pgcluster-probe.{uuid.uuid4().hex[:8]}")
    try:
        with open(probe, "wb") as f:
            f.write(b"ok")
            f.flush()
            os.fsync(f.fileno())
    except OSError as e:
        return False, f"{errno.errorcode.get(e.errno, 'OSError')}: {e.strerror or e}"
    finally:
        try:
            if os.path.exists(probe):
                os.remove(probe)
        except OSError:
            pass
    return True, "ok"


def ensure_dir(path: str) -> bool:
    """mkdir -p, True if the directory exists afterwards."""
    try:
        os.makedirs(path, exist_ok=True)
        return os.path.isdir(path)
    except OSError:
        return False


class StateStore:
    """Atomic, keyed, self-describing JSON state for one monitored cluster."""

    def __init__(
        self,
        plugin_file: str,
        cluster_id: str = "",
        name: str = "",
        seed: str = "",
        state_dir: Optional[str] = None,
        filename: str = DEFAULT_FILENAME,
        allow_temp_fallback: bool = True,
        warn=None,
    ):
        self.plugin_file = plugin_file
        self.plugin_dir = os.path.dirname(os.path.abspath(plugin_file))
        self.cluster_id = str(cluster_id or "")
        self.name = str(name or "")
        # Until the server has told us its system_identifier we still need a distinct
        # identity per configured cluster, or two cfg sections sharing one folder would
        # share one state file (and one another's last-known-good primary).
        self.seed = str(seed or "")
        self.filename = filename
        self.explicit_dir = state_dir or ""
        self.allow_temp_fallback = allow_temp_fallback
        self._warn = warn or (lambda code, text: None)
        self._path: Optional[str] = None
        self._persistent: Optional[bool] = None
        self._reason: str = "not probed"
        self._machine = _machine_id()
        self._io_errors = 0
        self._last_written: Optional[float] = None

    # ------------------------------------------------------------- location

    def instance_key(self) -> str:
        """Namespaces the file. Two plugin folders on one agent = two files."""
        identity = self.cluster_id or self.seed or self.name or "unnamed"
        seed = "|".join([self._machine, identity, self.plugin_dir])
        import hashlib

        return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]

    def _candidates(self) -> List[Tuple[str, bool, str]]:
        """(directory, durable, label) in preference order."""
        cands: List[Tuple[str, bool, str]] = []
        if self.explicit_dir:
            cands.append((os.path.abspath(self.explicit_dir), True, "configured"))
        cands.append((self.plugin_dir, True, "plugin_dir"))
        if os.name == "nt":
            base = os.environ.get("PROGRAMDATA") or os.environ.get("ALLUSERSPROFILE")
            if base:
                cands.append((os.path.join(base, "Site24x7", "postgres_cluster"), True, "programdata"))
        else:
            # /var/lib needs root; an agent running as a service user can't use it.
            cands.append(("/var/lib/site24x7/postgres_cluster", True, "var_lib"))
            xdg = os.environ.get("XDG_STATE_HOME") or (
                os.path.join(os.path.expanduser("~"), ".local", "state") if os.path.expanduser("~") not in ("~", "") else ""
            )
            if xdg:
                cands.append((os.path.join(xdg, "site24x7", "postgres_cluster"), True, "xdg_state"))
        if self.allow_temp_fallback:
            # Last resort: writable, but volatile by policy (tmpfiles 10d, tmpfs on reboot).
            cands.append((os.path.join(tempfile.gettempdir(), "site24x7-postgres_cluster"), False, "tempdir"))
        return cands

    def probe(self, force: bool = False) -> "StateStore":
        """Pick the first location we can really write to; record why."""
        if self._path and not force:
            return self
        self._path, self._persistent, self._reason = None, None, "no writable location"
        for directory, durable, label in self._candidates():
            if label != "configured" and os.path.isdir(directory) is False:
                if label in ("configured", "plugin_dir"):
                    pass
                elif not ensure_dir(directory):
                    continue
            elif label == "configured" and not os.path.isdir(directory):
                if not ensure_dir(directory):
                    continue
            ok, why = writable_by_write_probe(directory)
            if not ok:
                if label == "configured":
                    self._warn("WARN_STATE_DIR_UNUSABLE",
                               f"state_dir {directory!r} is not writable ({why}); falling back")
                continue
            target_dir = os.path.join(directory, f".pgcluster-{self.instance_key()}")
            if not ensure_dir(target_dir):
                continue
            ok2, why2 = writable_by_write_probe(target_dir)
            if not ok2:
                continue
            self._path = os.path.join(target_dir, self.filename)
            self._persistent = durable
            self._reason = f"{label}: {target_dir}"
            if not durable:
                self._warn("WARN_STATE_VOLATILE",
                           "state stored in a temporary directory: dead-node history, rates and "
                           "last-known-good primary data will be lost on reboot or tmp cleanup; "
                           "set state_dir in the config to a durable path")
            return self
        return self

    @property
    def path(self) -> Optional[str]:
        if self._path is None:
            self.probe()
        return self._path

    # ------------------------------------------------------------- read/write

    def load(self) -> Dict[str, Any]:
        """Read state. Never raises: corrupt/unreadable => {} plus a warning."""
        path = self.path
        if not path or not os.path.exists(path):
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = f.read(MAX_STATE_BYTES * 2)
        except OSError as e:
            self._io_errors += 1
            self._warn("WARN_STATE_UNREADABLE", f"{type(e).__name__}: {e}")
            return {}
        if len(raw) > MAX_STATE_BYTES:
            self._warn("WARN_STATE_TOO_LARGE", f"{len(raw)} bytes; resetting")
            return {}
        try:
            data = json.loads(raw)
        except ValueError as e:
            self._warn("WARN_STATE_CORRUPT", f"state file is not valid JSON ({e}); starting fresh")
            return {}
        if not isinstance(data, dict):
            self._warn("WARN_STATE_CORRUPT", "state root is not an object; starting fresh")
            return {}
        if data.get("schema") != SCHEMA:
            self._warn("WARN_STATE_SCHEMA", f"schema {data.get('schema')} != {SCHEMA}; starting fresh")
            return {}
        if data.get("instance") != self.instance_key():
            # Same machine, different plugin folder/cluster: refuse rather than lie.
            self._warn("WARN_STATE_FOREIGN",
                       "state file belongs to a different instance; ignoring it")
            return {}
        return data

    def save(self, state: Dict[str, Any]) -> bool:
        """Atomic, size-capped, merged write. Returns True on success."""
        path = self.path
        if not path:
            self._warn("WARN_STATE_NOWRITE", "no writable location for state; "
                                             "primary clamp, rates and dead-node history unavailable")
            return False
        state = dict(state or {})
        state["schema"] = SCHEMA
        state["instance"] = self.instance_key()
        state["machine_id"] = self._machine
        state["cluster_id"] = self.cluster_id
        state["name"] = self.name
        state["updated"] = int(time.time())
        state["nodes"] = self._prune_nodes(state.get("nodes") or {})

        tmp = None
        directory = os.path.dirname(path)
        try:
            fd, tmp = tempfile.mkstemp(dir=directory, prefix=".state.", suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(state, f, separators=(",", ":"), default=str)
                f.flush()
                os.fsync(f.fileno())
            if os.name != "nt":
                try:
                    os.chmod(tmp, 0o600)
                except OSError:
                    pass
            os.replace(tmp, path)      # atomic on POSIX and Windows (same volume)
            tmp = None
            self._last_written = time.time()
            return True
        except OSError as e:
            self._io_errors += 1
            self._warn("WARN_STATE_WRITE_FAILED", f"{type(e).__name__}: {e}")
            return False
        finally:
            if tmp and os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass

    @staticmethod
    def _prune_nodes(nodes: Dict[str, Any]) -> Dict[str, Any]:
        """Forget nodes unseen for NODE_TTL_DAYS so the file cannot grow forever."""
        cutoff = time.time() - NODE_TTL_DAYS * 86400
        out = {}
        for alias, entry in (nodes or {}).items():
            if not isinstance(entry, dict):
                continue
            seen = max(float(entry.get("ts_ok") or 0), float(entry.get("ts_fail") or 0))
            if seen and seen < cutoff:
                continue
            out[alias] = entry
        return out

    # ------------------------------------------------------------ diagnostics

    def diagnostics(self) -> Dict[str, Any]:
        """Metrics to emit every cycle so the state layer is observable."""
        age = None
        if self._last_written:
            age = int(time.time() - self._last_written)
        elif self._path and os.path.exists(self._path):
            try:
                age = int(time.time() - os.path.getmtime(self._path))
            except OSError:
                age = None
        return {
            "State_File": (self._path or "none")[-100:],
            "State_Persistent": 1 if self._persistent else 0,
            "State_Age_s": age if age is not None else -1,
            "State_IO_Errors": self._io_errors,
            "State_Reason": (self._reason or "")[:100],
        }


# ---------------------------------------------------------------- probe mode


def _probe_report() -> Dict[str, Any]:
    """Everything the agent environment must answer before we trust the state file."""
    here = os.path.abspath(__file__)
    store = StateStore(plugin_file=here, cluster_id="probe-cluster", name="probe")
    warnings: List[str] = []
    store._warn = lambda code, text: warnings.append(f"{code}: {text}")
    store.probe(force=True)

    report: Dict[str, Any] = {
        "python": sys.version.split()[0],
        "platform": sys.platform,
        "os_name": os.name,
        "uid": getattr(os, "getuid", lambda: "n/a")(),
        "euid": getattr(os, "geteuid", lambda: "n/a")(),
        "cwd": os.getcwd(),
        "plugin_file": here,
        "plugin_dir": store.plugin_dir,
        "machine_id": _machine_id(),
        "instance_key": store.instance_key(),
        "tempdir": tempfile.gettempdir(),
    }

    # honest write probe for every candidate, including the ones we would skip
    candidates = []
    for directory, durable, label in store._candidates():
        ok, why = writable_by_write_probe(directory) if os.path.isdir(directory) else (False, "missing")
        candidates.append({"label": label, "dir": directory, "durable": durable,
                           "writable_by_probe": ok, "why": why})
    report["candidates"] = candidates
    report["os_access_lies"] = [
        c["dir"] for c in candidates
        if c["writable_by_probe"] is False and os.path.isdir(c["dir"]) and os.access(c["dir"], os.W_OK)
    ]

    chosen = store.path
    report["chosen_path"] = chosen
    report["persistent"] = bool(store._persistent)
    report["reason"] = store._reason

    # round-trip test: write, read back, verify identity enforcement
    if chosen:
        ok = store.save({"selftest": True, "nodes": {"pgX": {"ts_ok": time.time()}}})
        back = store.load() if ok else {}
        report["round_trip_ok"] = bool(ok and back.get("selftest") is True)
        # a) two plugin folders on one agent (the documented way to monitor two clusters)
        other_dir = os.path.join(tempfile.gettempdir(), f"pgcluster-probe-{uuid.uuid4().hex[:6]}")
        ensure_dir(other_dir)
        other = StateStore(plugin_file=os.path.join(other_dir, "postgres_cluster.py"),
                           cluster_id="probe-cluster", name="probe")
        other.probe(force=True)
        # b) two cfg sections in ONE folder, differing only by configured seed
        same_dir_a = StateStore(plugin_file=here, seed="pg-a:5432")
        same_dir_b = StateStore(plugin_file=here, seed="pg-b:5432")
        report["instances_isolated"] = bool(
            other.path and other.path != chosen
            and same_dir_a.instance_key() != same_dir_b.instance_key()
        )
        report["isolation_detail"] = {
            "two_folders_differ": bool(other.path and other.path != chosen),
            "two_seeds_same_folder_differ": same_dir_a.instance_key() != same_dir_b.instance_key(),
        }
        for cleanup in (os.path.dirname(other.path or ""), other_dir):
            try:
                if cleanup and os.path.isdir(cleanup):
                    for f in os.listdir(cleanup):
                        os.remove(os.path.join(cleanup, f))
                    os.rmdir(cleanup)
            except OSError:
                pass

    report["warnings"] = warnings
    report["verdict"] = (
        "OK — durable state" if report.get("persistent") and report.get("round_trip_ok")
        else "OK — volatile state (set state_dir)" if report.get("round_trip_ok")
        else "FAIL — no usable state location"
    )
    return report


def main(argv: List[str]) -> int:
    if "--probe" not in argv:
        print(__doc__)
        return 2
    import argparse

    ap = argparse.ArgumentParser(description="Report state-file viability in this environment.")
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--state-dir", default="", help="test a specific directory as state_dir")
    args = ap.parse_args(argv)

    report = _probe_report()
    if args.state_dir:
        ok, why = writable_by_write_probe(args.state_dir)
        report["state_dir_test"] = {"dir": args.state_dir, "writable": ok, "why": why}

    if args.json:
        print(json.dumps(report, indent=2, default=str))
        return 0 if "FAIL" not in report["verdict"] else 1

    print("Site24x7 plugin state-file probe")
    print(f"  python        {report['python']}  platform={report['platform']}  uid={report['uid']} euid={report['euid']}")
    print(f"  plugin dir    {report['plugin_dir']}")
    print(f"  tempdir       {report['tempdir']}")
    print(f"  machine id    {report['machine_id'][:24]}  instance={report['instance_key']}")
    print("\n  candidate locations (write-probed, not os.access):")
    for c in report["candidates"]:
        mark = "OK " if c["writable_by_probe"] else "-- "
        print(f"    {mark}{c['label']:<12} {c['dir']:<55} durable={c['durable']} {c['why']}")
    if report["os_access_lies"]:
        print("\n  ATTENTION: os.access() claims writable but the write probe failed for:")
        for d in report["os_access_lies"]:
            print(f"    {d}")
    print(f"\n  chosen        {report['chosen_path']}")
    print(f"  persistent    {report['persistent']}  ({report['reason']})")
    if "round_trip_ok" in report:
        print(f"  round trip     {'ok' if report['round_trip_ok'] else 'FAILED'}")
        print(f"  isolation      {'ok, two instances use different files' if report['instances_isolated'] else 'FAILED: instances collide'}")
    if report["warnings"]:
        print("  warnings:")
        for w in report["warnings"]:
            print(f"    - {w}")
    print(f"\n  verdict: {report['verdict']}")
    return 0 if "FAIL" not in report["verdict"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
