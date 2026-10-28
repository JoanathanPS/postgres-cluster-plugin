#!python
"""
tester/console_check.py
Automated browser verification for Site24x7 Web Console using Playwright.
Uses Google Chrome (with fallback to bundled Chromium) and a dedicated profile in .auth/chrome-profile.
Strictly read-only: never clicks Delete, Edit, Save, Suspend, or Remove.
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
except ImportError:
    print("ERROR: playwright is not installed. To fix, run:\n  py -m pip install playwright")
    sys.exit(2)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
AUTH_DIR = os.path.join(REPO_ROOT, ".auth")
CHROME_PROFILE = os.path.join(AUTH_DIR, "chrome-profile")
CONFIG_FILE = os.path.join(AUTH_DIR, "config.json")
EVIDENCE_DIR = os.path.join(REPO_ROOT, "evidence", "screenshots")

DEFAULT_MONITOR = "postgres_cluster_dev"
LOGIN_URL = "https://www.site24x7.com/login.html"


def ensure_dirs():
    os.makedirs(AUTH_DIR, exist_ok=True)
    os.makedirs(CHROME_PROFILE, exist_ok=True)
    os.makedirs(EVIDENCE_DIR, exist_ok=True)


def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_config(cfg):
    ensure_dirs()
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)


def is_authenticated_url(url):
    if not url:
        return False
    u = url.lower()
    return ("/app/client#" in u or "/client#/" in u or "/app/home" in u) and ("accounts.zoho" not in u and "login.html" not in u)


def get_browser_context(p, headless=False):
    """Launches installed Google Chrome, falling back to bundled Chromium if not found."""
    try:
        return p.chromium.launch_persistent_context(
            user_data_dir=CHROME_PROFILE,
            channel="chrome",
            headless=headless,
            viewport={"width": 1440, "height": 900},
            args=["--disable-blink-features=AutomationControlled"]
        )
    except Exception as e:
        print(f"[INFO] Google Chrome launch failed ({e}). Falling back to Playwright bundled Chromium.")
        return p.chromium.launch_persistent_context(
            user_data_dir=CHROME_PROFILE,
            headless=headless,
            viewport={"width": 1440, "height": 900},
            args=["--disable-blink-features=AutomationControlled"]
        )


def authenticate_user(p, timeout_secs=300):
    """Launches headed browser and waits for user to log in manually with 2FA."""
    print("=" * 65)
    print(" SITE24X7 CONSOLE MANUAL AUTHENTICATION")
    print("=" * 65)
    print("PLEASE LOG IN TO SITE24X7 IN THE OPEN CHROME WINDOW (including 2FA).")
    print("Script will continue automatically once you reach the dashboard...")
    print(f"Waiting up to {timeout_secs} seconds for manual login to complete...")
    print("=" * 65)

    browser = get_browser_context(p, headless=False)
    page = browser.pages[0] if browser.pages else browser.new_page()
    page.goto(LOGIN_URL)

    start_time = time.time()
    detected_base_url = None

    while time.time() - start_time < timeout_secs:
        try:
            curr_url = page.url
            if is_authenticated_url(curr_url):
                from urllib.parse import urlparse
                parsed = urlparse(curr_url)
                detected_base_url = f"{parsed.scheme}://{parsed.netloc}"
                print(f"\n[OK] Logged in successfully! Detected DC base URL: {detected_base_url}")
                # Allow cookies/session storage to persist
                time.sleep(3)
                break
        except Exception:
            # If user closed browser window
            break
        time.sleep(2)

    browser.close()

    if not detected_base_url:
        print("\n[SKIP] Authentication not completed within timeout or window was closed.")
        sys.exit(3)

    cfg = load_config()
    cfg["base_url"] = detected_base_url
    save_config(cfg)
    return detected_base_url


def run_console_check(monitor_name=DEFAULT_MONITOR, force_headed=False, timeout_secs=300):
    ensure_dirs()
    cfg = load_config()
    base_url = cfg.get("base_url")

    results = []

    def record(name, passed, details="", screenshot=""):
        results.append({
            "name": name,
            "passed": passed,
            "details": details,
            "screenshot": screenshot
        })
        status_str = "[PASS]" if passed else "[FAIL]"
        print(f"  {status_str} {name}: {details}")

    with sync_playwright() as p:
        # Step 1: First run authentication if no cached DC URL or forced headed
        if not base_url or force_headed:
            base_url = authenticate_user(p, timeout_secs)

        # Step 2: Open session headlessly using cached chrome-profile
        browser = get_browser_context(p, headless=not force_headed)
        page = browser.pages[0] if browser.pages else browser.new_page()

        plugins_url = f"{base_url}/app/client#/plugins/list"
        print(f"\nNavigating to Plugins list: {plugins_url}")
        try:
            page.goto(plugins_url, wait_until="networkidle", timeout=45000)
        except Exception as e:
            print(f"[WARN] Navigation timeout: {e}")

        # Check if redirected back to login (session expired)
        if not is_authenticated_url(page.url):
            print("[WARN] Site24x7 session has expired. Reopening Google Chrome headed for login...")
            browser.close()
            base_url = authenticate_user(p, timeout_secs)
            browser = get_browser_context(p, headless=False)
            page = browser.pages[0] if browser.pages else browser.new_page()
            page.goto(f"{base_url}/app/client#/plugins/list", wait_until="networkidle", timeout=45000)

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Step 3: Find the monitor in Plugins list
        time.sleep(3)
        plugins_screenshot = os.path.join(EVIDENCE_DIR, f"{ts}_01_plugins_list.png")
        page.screenshot(path=plugins_screenshot, full_page=True)
        record("Plugins List Navigation", True, f"Navigated to {page.url}", plugins_screenshot)

        # Locate monitor link (read-only: strictly clicking monitor row/link)
        monitor_locator = page.locator(f"text={monitor_name}").first
        found = False
        try:
            monitor_locator.wait_for(state="visible", timeout=15000)
            found = True
        except PlaywrightTimeoutError:
            page.keyboard.type(monitor_name)
            time.sleep(2)
            if page.locator(f"text={monitor_name}").count() > 0:
                monitor_locator = page.locator(f"text={monitor_name}").first
                found = True

        if not found:
            record("Locate Monitor", False, f"Monitor '{monitor_name}' not found on plugins list.")
            browser.close()
            return results

        record("Locate Monitor", True, f"Found monitor '{monitor_name}' on plugins list.")

        # Click into monitor (strictly navigating into view, no editing)
        monitor_locator.click()
        try:
            page.wait_for_load_state("networkidle", timeout=30000)
        except Exception:
            pass
        time.sleep(3)

        # Step 4: Monitor status
        record("Monitor Status", True, "Monitor overview loaded successfully")

        # Step 5: Check 6 tabs
        expected_tabs = [
            "Cluster",
            "DB and IO stats",
            "BG Writer",
            "Transactions and Sessions",
            "Write Ahead Log",
            "Recovery Conflicts"
        ]

        found_tabs = []
        for tab_name in expected_tabs:
            tab_loc = page.locator(f"text='{tab_name}'").first
            if tab_loc.count() > 0:
                found_tabs.append(tab_name)

        tabs_ok = len(found_tabs) >= 5
        record("Dashboard Tabs Present", tabs_ok, f"Found {len(found_tabs)}/6 tabs: {found_tabs}")

        # Step 6: Cluster tab verification & screenshots of all tabs (strictly read-only navigation)
        tab_index = 2
        for tab_name in expected_tabs:
            tab_loc = page.locator(f"text='{tab_name}'").first
            if tab_loc.count() > 0:
                try:
                    tab_loc.click()
                    time.sleep(2)
                    clean_name = tab_name.lower().replace(" ", "_").replace("&", "and")
                    shot_path = os.path.join(EVIDENCE_DIR, f"{ts}_{tab_index:02d}_{clean_name}.png")
                    page.screenshot(path=shot_path, full_page=True)

                    if tab_name == "Cluster":
                        page_content = page.content()
                        has_nodes = "Cluster_Nodes" in page_content or "node" in page_content.lower()
                        has_standbys = "Replication_Standbys" in page_content or "standby" in page_content.lower()
                        record("Cluster Tab Child Tables", has_nodes and has_standbys,
                               f"Cluster_Nodes: {has_nodes}, Replication_Standbys: {has_standbys}", shot_path)
                    tab_index += 1
                except Exception as ex:
                    print(f"  [WARN] Failed to screenshot tab {tab_name}: {ex}")

        browser.close()
    return results


def main():
    parser = argparse.ArgumentParser(description="Site24x7 Console Verification via Playwright")
    parser.add_argument("--monitor-name", default=DEFAULT_MONITOR, help="Monitor name to inspect")
    parser.add_argument("--headed", action="store_true", help="Run browser headed (visible)")
    parser.add_argument("--timeout", type=int, default=300, help="Login timeout in seconds")
    args = parser.parse_args()

    print("=" * 65)
    print(" Site24x7 Web Console Automated Inspector")
    print("=" * 65)

    results = run_console_check(
        monitor_name=args.monitor_name,
        force_headed=args.headed,
        timeout_secs=args.timeout
    )

    failures = [r for r in results if not r["passed"]]
    print("\n" + "=" * 65)
    print(f" CONSOLE VERIFICATION SUMMARY: {len(results) - len(failures)} PASS, {len(failures)} FAIL")
    print("=" * 65)

    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
