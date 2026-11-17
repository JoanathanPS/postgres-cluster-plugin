"""
tester/test_e2e_negative.py
Negative E2E Pipeline Verification Test.
Runs the e2e.ps1 verification pipeline against a deliberately broken copy of the plugin
and confirms:
1. e2e.ps1 visibly prints [FAIL].
2. The pipeline finishes with the 'RESULT: FAIL' banner.
3. The report file (evidence/NEGATIVE_REPORT.md) is generated with 'Final Outcome: FAILED'.
4. PowerShell never crashes with an unhandled NativeCommandError.
5. e2e.ps1 exits with a non-zero exit code (1).
"""

import os
import sys
import subprocess
import shutil

def main():
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    broken_plugin = os.path.join(repo_root, "tester", "broken_plugin_sample.py")
    negative_report = os.path.join(repo_root, "evidence", "NEGATIVE_REPORT.md")

    # Write deliberately broken plugin that crashes and prints invalid JSON
    with open(broken_plugin, "w", encoding="utf-8") as f:
        f.write("# Deliberately broken plugin for negative testing\n")
        f.write("import sys\n")
        f.write("sys.stderr.write('FatalError: Deliberately broken plugin stderr stream\\n')\n")
        f.write("print('INVALID_NON_JSON_CORRUPTED_OUTPUT')\n")
        f.write("sys.exit(1)\n")

    cmd = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", os.path.join(repo_root, "tester", "e2e.ps1"),
        "-Mode", "quick",
        "-SkipConsole",
        "-ReportPath", negative_report,
        "-PluginScript", broken_plugin
    ]

    print("Running negative E2E test against broken plugin...")
    proc = subprocess.run(cmd, cwd=repo_root, capture_output=True, text=True)

    print(f"Negative test exit code: {proc.returncode}")

    failures = []

    # 1. Exit code must be 1
    if proc.returncode != 1:
        failures.append(f"Expected exit code 1, got {proc.returncode}")

    # 2. Must contain visible [FAIL]
    if "[FAIL]" not in proc.stdout:
        failures.append("Stdout does not contain visible '[FAIL]'")

    # 3. Must finish with RESULT: FAIL
    if "RESULT: FAIL" not in proc.stdout:
        failures.append("Stdout does not contain 'RESULT: FAIL'")

    # 4. Must NOT contain NativeCommandError
    if "NativeCommandError" in proc.stdout or "NativeCommandError" in proc.stderr:
        failures.append("PowerShell threw unhandled NativeCommandError")

    # 5. Report file must exist and contain FAILED
    if not os.path.exists(negative_report):
        failures.append(f"Report file '{negative_report}' was not written")
    else:
        with open(negative_report, "r", encoding="utf-8") as rf:
            content = rf.read()
        if "FAILED" not in content or "[FAIL]" not in content:
            failures.append("Report file does not contain '[FAIL]' or 'FAILED'")

    # Cleanup temporary files
    try:
        if os.path.exists(broken_plugin):
            os.remove(broken_plugin)
        if os.path.exists(negative_report):
            os.remove(negative_report)
    except Exception:
        pass

    if failures:
        print("\n" + "=" * 65)
        print(f"NEGATIVE TEST FAILED with {len(failures)} error(s):")
        for err in failures:
            print(f"  - {err}")
        print("=" * 65)
        print("Stdout preview:\n", proc.stdout[-500:])
        sys.exit(1)
    else:
        print("\n" + "=" * 65)
        print("RESULT: PASS")
        print("Negative test successfully verified: e2e.ps1 reported FAIL and generated report.")
        print("=" * 65)
        sys.exit(0)

if __name__ == "__main__":
    main()
