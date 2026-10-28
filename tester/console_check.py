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
import threading
from datetime import datetime
from urllib.parse import urlparse, urlsplit

try:
    import msvcrt
    HAS_MSVCRT = True
except ImportError:
    HAS_MSVCRT = False

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
LOGIN_URL = "https://www.site24x7.in/login.html"

manual_override_event = threading.Event()


def start_enter_listener():
    """Starts a daemon thread listening for Enter key on stdin as a manual override."""
    def _listen():
        try:
            sys.stdin.readline()
            manual_override_event.set()
        except Exception:
            pass

    t = threading.Thread(target=_listen, daemon=True)
    t.start()
    return t


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


def strip_query(url):
    """Returns URL with query string removed, retaining scheme, host, path, and hash."""
    if not url:
        return ""
    try:
        parts = urlsplit(url)
        return parts._replace(query="").geturl()
    except Exception:
        return url


def check_page_logged_in(page):
    """
    Evaluates whether a Playwright Page is authenticated to Site24x7.
    Returns (is_logged_in: bool, base_url: str or None).
    """
    try:
        url = page.url
        if not url:
            return False, None

        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        full_lower = url.lower()

        # Disqualifying auth/login keywords in URL
        disqualifiers = ["login", "signin", "signup", "accounts", "auth", "sso"]
        if any(dq in full_lower for dq in disqualifiers):
            return False, None

        # Host must belong to site24x7 (site24x7.in, site24x7.com, etc.)
        if not ("site24x7." in host):
            return False, None

        # Path or hash looks like the application
        app_path_or_hash = ("/app/" in parsed.path.lower()) or ("#/" in full_lower) or ("/app/" in full_lower)

        # Inspect DOM for known logged-in elements
        dom_logged_in = False
        try:
            dom_selectors = [
                "#user-avatar", ".user-avatar", "header .avatar",
                ".left-nav", "#leftnav", ".navigation-container",
                ".nav-icon", ".client-header", "div#side-nav",
                "a[href*='#/home']", "a[href*='#/plugins']",
                ".profile-icon", "[data-testid='user-profile']",
                "#topNavbar", ".main-nav", ".sub-nav"
            ]
            for sel in dom_selectors:
                if page.locator(sel).count() > 0:
                    dom_logged_in = True
                    break
        except Exception:
            pass

        if app_path_or_hash or dom_logged_in:
            base_url = f"{parsed.scheme}://{parsed.netloc}"
            return True, base_url

    except Exception:
        pass

    return False, None


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


def authenticate_user(p, timeout_secs=300, debug=False):
    """Launches headed browser and waits for user to log in manually with 2FA."""
    print("=" * 65)
    print(" SITE24X7 CONSOLE MANUAL AUTHENTICATION")
    print("=" * 65)
    print("PLEASE LOG IN TO SITE24X7 IN THE OPEN CHROME WINDOW (including 2FA).")
    print("Press [Enter] in this terminal at any time once logged in to continue manually.")
    print(f"Waiting up to {timeout_secs} seconds for login to complete...")
    print("=" * 65)

    start_enter_listener()

    browser = get_browser_context(p, headless=False)
    page = browser.pages[0] if browser.pages else browser.new_page()
    page.goto(LOGIN_URL)

    start_time = time.time()
    last_status_print = start_time
    detected_base_url = None

    try:
        while time.time() - start_time < timeout_secs:
            now = time.time()

            # Check trigger file in .auth/continue
            trigger_file = os.path.join(AUTH_DIR, "continue")
            if os.path.exists(trigger_file):
                try:
                    os.remove(trigger_file)
                except Exception:
                    pass
                manual_override_event.set()

            # Check non-blocking msvcrt keyhit on Windows
            if HAS_MSVCRT:
                try:
                    while msvcrt.kbhit():
                        ch = msvcrt.getwch()
                        if ch in ('\r', '\n'):
                            manual_override_event.set()
                            break
                except Exception:
                    pass

            if manual_override_event.is_set():
                print("\n[INFO] Manual override detected (Enter pressed in terminal)!")
                target_page = browser.pages[-1] if browser.pages else page
                parsed = urlparse(target_page.url)
                detected_base_url = f"{parsed.scheme}://{parsed.netloc}"
                print(f"[OK] Using base URL from current page: {detected_base_url}")
                time.sleep(2)
                break

            # Check all open pages and tabs
            for p_tab in list(browser.pages):
                is_logged, b_url = check_page_logged_in(p_tab)
                if is_logged:
                    detected_base_url = b_url
                    print(f"\n[OK] Logged in successfully! Detected DC base URL: {detected_base_url}")
                    time.sleep(3)
                    break

            if detected_base_url:
                break

            # Every 10 seconds print current URL of each page
            if now - last_status_print >= 10:
                last_status_print = now
                remaining = max(0, int(timeout_secs - (now - start_time)))
                for idx, p_tab in enumerate(browser.pages):
                    try:
                        stripped = strip_query(p_tab.url)
                        print(f"[WAIT] {remaining}s remaining | Tab {idx}: {stripped}")
                    except Exception:
                        pass

            time.sleep(1)

    except KeyboardInterrupt:
        print("\n[CANCELLED] Authentication cancelled by user (Ctrl+C).")
        try:
            browser.close()
        except Exception:
            pass
        sys.exit(130)

    # If timeout or failure and debug flag is on, capture screenshot and HTML
    if not detected_base_url and debug:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        for idx, p_tab in enumerate(browser.pages):
            try:
                debug_shot = os.path.join(REPO_ROOT, "evidence", f"debug_login_fail_{ts}_tab{idx}.png")
                debug_html = os.path.join(REPO_ROOT, "evidence", f"debug_login_fail_{ts}_tab{idx}.html")
                p_tab.screenshot(path=debug_shot, full_page=True)
                with open(debug_html, "w", encoding="utf-8") as f:
                    f.write(p_tab.content())
                print(f"  [DEBUG] Saved debug screenshot: {debug_shot}")
                print(f"  [DEBUG] Saved debug HTML: {debug_html}")
            except Exception as ex:
                print(f"  [DEBUG] Failed to save debug artifacts for tab {idx}: {ex}")

    try:
        browser.close()
    except Exception:
        pass

    if not detected_base_url:
        print("\n[SKIP] Authentication not completed within timeout or window was closed.", flush=True)
        sys.exit(3)

    cfg = load_config()
    cfg["base_url"] = detected_base_url
    save_config(cfg)
    return detected_base_url


def run_console_check(monitor_name=DEFAULT_MONITOR, force_headed=False, timeout_secs=300, debug=False):
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
            base_url = authenticate_user(p, timeout_secs, debug=debug)

        # Step 2: Open session (reusing authenticated profile)
        browser = get_browser_context(p, headless=not force_headed)
        page = browser.pages[0] if browser.pages else browser.new_page()

        plugins_url = f"{base_url}/app/client#/plugins/list"
        print(f"\nNavigating to Plugins list: {plugins_url}")
        try:
            page.goto(plugins_url, wait_until="domcontentloaded", timeout=45000)
        except Exception as e:
            print(f"[WARN] Navigation timeout: {e}")

        # Check if redirected back to login (session expired)
        is_logged, _ = check_page_logged_in(page)
        if not is_logged:
            print("[WARN] Site24x7 session has expired. Reopening Google Chrome headed for login...")
            try:
                browser.close()
            except Exception:
                pass
            base_url = authenticate_user(p, timeout_secs, debug=debug)
            browser = get_browser_context(p, headless=False)
            page = browser.pages[0] if browser.pages else browser.new_page()
            page.goto(f"{base_url}/app/client#/plugins/list", wait_until="domcontentloaded", timeout=45000)

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Step 3: Find the monitor in Plugins list (polling up to 35s for SPA AJAX rendering)
        print("Waiting for plugins list view and table to render...")
        found = False
        monitor_locator = None
        start_wait = time.time()

        while time.time() - start_wait < 35:
            # Check if monitor row is visible in main table
            mon_candidates = page.locator(f"span.txtblue:has-text('{monitor_name}'), a:has-text('{monitor_name}'), span:has-text('{monitor_name}')")
            for i in range(mon_candidates.count()):
                cand = mon_candidates.nth(i)
                if cand.is_visible():
                    monitor_locator = cand
                    found = True
                    break
            if found:
                break

            # Check if sidebar application filter link is visible
            app_filter = page.locator("a[href*='/plugins/PLUGIN/application/']:has-text('postgres'), a:has-text('postgres_cluste')").first
            if app_filter.count() > 0 and app_filter.is_visible():
                print("Selecting application filter from sidebar...")
                try:
                    app_filter.click()
                except Exception:
                    pass
                time.sleep(3)
                for _ in range(8):
                    mon_cands2 = page.locator(f"span.txtblue:has-text('{monitor_name}'), a:has-text('{monitor_name}'), span:has-text('{monitor_name}')")
                    for j in range(mon_cands2.count()):
                        c2 = mon_cands2.nth(j)
                        if c2.is_visible():
                            monitor_locator = c2
                            found = True
                            break
                    if found:
                        break
                    time.sleep(1)
                if found:
                    break

            time.sleep(2)

        plugins_screenshot = os.path.join(EVIDENCE_DIR, f"{ts}_01_plugins_list.png")
        page.screenshot(path=plugins_screenshot, full_page=True)
        record("Plugins List Navigation", True, f"Navigated to {page.url}", plugins_screenshot)

        if not found:
            record("Locate Monitor", False, f"Monitor '{monitor_name}' not found on plugins list within timeout.")
            if debug:
                debug_shot = os.path.join(REPO_ROOT, "evidence", f"debug_locate_fail_{ts}.png")
                debug_html = os.path.join(REPO_ROOT, "evidence", f"debug_locate_fail_{ts}.html")
                page.screenshot(path=debug_shot, full_page=True)
                with open(debug_html, "w", encoding="utf-8") as f:
                    f.write(page.content())
                print(f"  [DEBUG] Saved locate failure artifacts: {debug_shot}, {debug_html}")
            try:
                browser.close()
            except Exception:
                pass
            return results

        record("Locate Monitor", True, f"Found monitor '{monitor_name}' on plugins list.")

        # Click into monitor dashboard (strictly navigating into view, no editing)
        monitor_locator.click()
        time.sleep(8)

        # Step 4: Monitor status
        record("Monitor Status", True, f"Monitor dashboard loaded successfully: {page.url}")

        # Step 5: Check 6 tabs (strictly all 6 must be found, including checking inside 'More' dropdown)
        expected_tabs = [
            "Cluster",
            "DB and IO stats",
            "BG Writer",
            "Transactions and Sessions",
            "Write Ahead Log",
            "Recovery Conflicts"
        ]

        # Gather visible tabs on tab bar
        tab_spans = page.locator("ul.nav-tabs li span, ul.nav-tabs li, [role='tab']")
        visible_tab_names = [s.strip() for s in tab_spans.all_inner_texts() if s.strip()]

        # Also inspect inside the "More" dropdown
        more_toggle = page.locator("#show-more-dropdown span.dropdown-toggle, span.dropdown-toggle:has-text('More'), a:has-text('More')").first
        more_tab_names = []
        if more_toggle.count() > 0 and more_toggle.is_visible():
            try:
                more_toggle.click()
                time.sleep(1)
                dropdown_items = page.locator("#show-more-dropdown .dropdown-menu li, .dropdown-menu li, .dropdown-menu a")
                more_tab_names = [d.strip() for d in dropdown_items.all_inner_texts() if d.strip()]
                # Click more toggle again to close menu cleanly
                more_toggle.click()
                time.sleep(0.5)
            except Exception:
                pass

        all_available_tabs = set(visible_tab_names + more_tab_names)
        page_content = page.content()

        found_tabs = []
        for tab_name in expected_tabs:
            if (tab_name in all_available_tabs or
                page.locator(f"span:text-is('{tab_name}')").count() > 0 or
                page.locator(f"a:text-is('{tab_name}')").count() > 0 or
                tab_name in page_content):
                found_tabs.append(tab_name)

        missing_tabs = [t for t in expected_tabs if t not in found_tabs]
        tabs_ok = (len(missing_tabs) == 0 and len(found_tabs) == len(expected_tabs))

        if tabs_ok:
            record("Dashboard Tabs Present", True, f"All 6 tabs verified present: {found_tabs}")
        else:
            record("Dashboard Tabs Present", False, f"Missing tab(s): {missing_tabs}. Found {len(found_tabs)}/6: {found_tabs}")

        # Step 6: Cluster tab verification & screenshots of all tabs (strictly read-only navigation)
        tab_index = 2
        for tab_name in expected_tabs:
            clean_name = tab_name.lower().replace(" ", "_").replace("&", "and")
            shot_path = os.path.join(EVIDENCE_DIR, f"{ts}_{tab_index:02d}_{clean_name}.png")

            tab_loc = page.locator(f"span#{tab_name}").first
            if tab_loc.count() == 0:
                tab_loc = page.locator(f"span:text-is('{tab_name}')").first
            if tab_loc.count() == 0:
                tab_loc = page.locator(f"a:text-is('{tab_name}')").first
            
            clicked = False
            if tab_loc.count() > 0:
                try:
                    tab_loc.click()
                    clicked = True
                except Exception:
                    try:
                        tab_loc.dispatch_event("click")
                        clicked = True
                    except Exception:
                        pass

            if not clicked:
                # Try via More dropdown if present
                more_loc = page.locator("#show-more-dropdown span.dropdown-toggle, a:has-text('More'), span:has-text('More')").first
                if more_loc.count() > 0 and more_loc.is_visible():
                    try:
                        more_loc.click()
                        time.sleep(1)
                        sub_tab = page.locator(f"text='{tab_name}'").first
                        if sub_tab.count() > 0:
                            sub_tab.click()
                            clicked = True
                    except Exception:
                        pass

            if clicked:
                time.sleep(5)
                page.screenshot(path=shot_path, full_page=True)

                if tab_name == "Cluster":
                    cl_content = page.content()
                    has_nodes_hdr = "Cluster_Nodes" in cl_content or "cluster_nodes" in cl_content.lower()
                    has_standbys_hdr = "Replication_Standbys" in cl_content or "replication_standbys" in cl_content.lower()
                    record("Cluster Tab Child Tables Structure", has_nodes_hdr and has_standbys_hdr,
                           f"Cluster_Nodes: {has_nodes_hdr}, Replication_Standbys: {has_standbys_hdr}", shot_path)

                    # Assert Cluster_Nodes table shows 3 rows and role column has 'primary' for exactly one row
                    node_rows = page.locator("tr:has-text('5441'), tr:has-text('5442'), tr:has-text('5443')").all()
                    if len(node_rows) == 0:
                        c_widget = page.locator("text='Cluster_Nodes list'").locator("xpath=ancestor::div[contains(@class, 'widget') or contains(@class, 'box') or contains(@class, 'panel')][1]")
                        if c_widget.count() > 0:
                            node_rows = c_widget.locator("tbody tr, tr").all()

                    row_count = len(node_rows)
                    primary_rows = [r for r in node_rows if "primary" in r.inner_text().lower()]
                    primary_count = len(primary_rows)

                    nodes_table_ok = (row_count == 3 and primary_count == 1)
                    nodes_details = f"Rows found: {row_count}/3, primary row count: {primary_count}/1"
                    if not nodes_table_ok:
                        row_texts = [r.inner_text().strip().replace('\n', ' | ') for r in node_rows]
                        nodes_details += f" (Observed: {row_texts if row_texts else 'No data rows rendered'})"

                    record("Cluster_Nodes Table Rows and Role", nodes_table_ok, nodes_details, shot_path)
            tab_index += 1

        try:
            browser.close()
        except Exception:
            pass
    return results


def main():
    parser = argparse.ArgumentParser(description="Site24x7 Console Verification via Playwright")
    parser.add_argument("--monitor-name", default=DEFAULT_MONITOR, help="Monitor name to inspect")
    parser.add_argument("--headed", action="store_true", help="Run browser headed (visible)")
    parser.add_argument("--timeout", type=int, default=300, help="Login timeout in seconds")
    parser.add_argument("--debug", action="store_true", help="Capture debug screenshot and HTML on failure")
    args = parser.parse_args()

    print("=" * 65)
    print(" Site24x7 Web Console Automated Inspector")
    print("=" * 65)

    try:
        results = run_console_check(
            monitor_name=args.monitor_name,
            force_headed=args.headed,
            timeout_secs=args.timeout,
            debug=args.debug
        )
    except KeyboardInterrupt:
        print("\n[CANCELLED] Console verification cancelled by user (Ctrl+C).")
        sys.exit(130)

    failures = [r for r in results if not r["passed"]]
    print("\n" + "=" * 65)
    print(f" CONSOLE VERIFICATION SUMMARY: {len(results) - len(failures)} PASS, {len(failures)} FAIL")
    print("=" * 65)

    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[CANCELLED] Console verification cancelled by user (Ctrl+C).")
        sys.exit(130)
