"""End-to-end walkthrough of VoltTrace Studio in a real browser.

    python scripts/studio_e2e.py http://127.0.0.1:8000/            # against `volttrace serve` (local Python engine)
    python scripts/studio_e2e.py http://127.0.0.1:8000/ --static   # against the static site (engine boots via Pyodide)

Fails (exit 1) if any page errors or any flow does not produce the expected verdict.
"""

import os
import sys

from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000/"
STATIC = "--static" in sys.argv
CHROMIUM = os.environ.get("CHROMIUM_PATH")  # e.g. /opt/pw-browsers/chromium; default: Playwright's own
SHOTS = os.environ.get("SHOTS_DIR", "out/e2e")
os.makedirs(SHOTS, exist_ok=True)
errors = []
checks = []


def check(name, ok, detail=""):
    checks.append((name, bool(ok), detail))
    print(("PASS " if ok else "FAIL ") + name + (f": {detail}" if detail else ""), flush=True)


with sync_playwright() as p:
    b = p.chromium.launch(executable_path=CHROMIUM) if CHROMIUM else p.chromium.launch()
    pg = b.new_page(viewport={"width": 1280, "height": 900})
    pg.on("console", lambda m: errors.append(f"console.{m.type}: {m.text}") if m.type in ("error",) else None)
    pg.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    pg.goto(BASE)
    pg.wait_for_selector(".engine.ready", timeout=240000)
    mode = pg.inner_text("#engine")
    check("engine boots", "ready" in mode, mode)
    if STATIC:
        check("engine runs in the browser", "Pyodide" in mode, mode)
    pg.screenshot(path=f"{SHOTS}/start.png", full_page=True)
    # bench
    pg.goto(BASE + "#/bench")
    pg.click("#runBtn")
    pg.wait_for_selector(".banner .chip", timeout=120000)
    check("TC-001 passes on the released software", pg.inner_text(".banner .big").strip().endswith("PASS"))
    pg.screenshot(path=f"{SHOTS}/bench.png", full_page=True)
    # findings replay F-002
    pg.goto(BASE + "#/findings")
    pg.click("button.replay[data-id='F-002']")
    pg.wait_for_selector(".banner .chip", timeout=120000)
    check(
        "F-002 replay fails REQ-HV-002",
        "FAIL" in pg.inner_text(".banner .big") and "REQ-HV-002" in pg.inner_text("table"),
    )
    check("F-002 replay draws overlay charts", pg.locator("#charts figure").count() >= 2)
    pg.screenshot(path=f"{SHOTS}/finding_f002.png", full_page=True)
    # requirements playground (uses last run)
    pg.goto(BASE + "#/requirements")
    pg.click("#stlRun")
    pg.wait_for_selector("#stlOut .banner", timeout=60000)
    check("STL playground evaluates on the last run", "robustness" in pg.inner_text("#stlOut .banner"))
    # falsifier small
    pg.goto(BASE + "#/falsify")
    pg.fill("input[name=budget]", "12")
    pg.dispatch_event("input[name=budget]", "change")
    pg.click("#fzRun")
    pg.wait_for_selector("#fzOut .note", timeout=300000)
    check("falsifier rediscovers F-002 on M09", "Counterexample found" in pg.inner_text("#fzOut .note h3"))
    pg.screenshot(path=f"{SHOTS}/falsifier.png", full_page=True)
    # CI
    pg.goto(BASE + "#/ci")
    pg.select_option("select[name=change]", "M05DerateRampInverted")
    pg.click("#ciRun")
    pg.wait_for_selector("#ciOut .note h3", timeout=300000)
    check("CI policy C catches M05 on SiL", "TC-004@sil" in pg.inner_text("#ciOut .note h3"))
    pg.screenshot(path=f"{SHOTS}/ci.png", full_page=True)
    # hunt
    pg.goto(BASE + "#/hunt")
    pg.click("#huntStart")
    pg.wait_for_selector("#huntForm", timeout=60000)
    pg.click("#huntRun")
    pg.wait_for_selector("#huntOut .banner", timeout=120000)
    pg.select_option("#guess", index=1)
    pg.click("#reveal")
    pg.wait_for_selector(".note h3", timeout=60000)
    check("bug hunt reveals the change", "The change was" in pg.inner_text(".note h3"))
    pg.screenshot(path=f"{SHOTS}/hunt.png", full_page=True)
    # mobile
    m = b.new_page(viewport={"width": 390, "height": 800})
    m.goto(BASE)
    m.wait_for_selector(".engine.ready", timeout=60000)
    check("no horizontal scroll at 390 px", m.evaluate("document.documentElement.scrollWidth") <= 390)
    b.close()
check("no console or page errors", not errors, "; ".join(errors))
sys.exit(0 if all(ok for _, ok, _ in checks) else 1)
