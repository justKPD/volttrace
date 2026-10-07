"""End-to-end walkthrough of VoltTrace Studio in a real browser: every page, every feature, the session report and
the assistant.

    python scripts/studio_e2e.py http://127.0.0.1:8000/            # against `volttrace serve` (local Python engine)
    python scripts/studio_e2e.py http://127.0.0.1:8000/ --static   # against the static site (engine boots via Pyodide)

Fails (exit 1) if any page errors or any flow does not produce the expected result.
"""

import json
import os
import sys

from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000/"
STATIC = "--static" in sys.argv
CHROMIUM = os.environ.get("CHROMIUM_PATH")  # e.g. /opt/pw-browsers/chromium; default: Playwright's own
SHOTS = os.environ.get("SHOTS_DIR", "out/e2e")
SLOW = 600000 if STATIC else 180000
os.makedirs(SHOTS, exist_ok=True)
errors = []
checks = []


def check(name, ok, detail=""):
    checks.append((name, bool(ok), detail))
    print(("PASS " if ok else "FAIL ") + name + (f": {detail}" if detail and not ok else ""), flush=True)


def guarded(name, fn):
    """Run one flow; a timeout or exception fails that flow but not the whole walkthrough."""
    try:
        fn()
    except Exception as e:  # noqa: BLE001
        check(name, False, f"{type(e).__name__}: {str(e)[:300]}")


def downloaded(pg, selector):
    with pg.expect_download(timeout=20000) as d:
        pg.click(selector)
    path = d.value.path()
    with open(path, encoding="utf-8") as f:
        return d.value.suggested_filename, f.read()


def entries(pg):
    return pg.evaluate("window.volttrace.session.log.entries.length")


with sync_playwright() as p:
    b = p.chromium.launch(executable_path=CHROMIUM) if CHROMIUM else p.chromium.launch()
    ctx = b.new_context(viewport={"width": 1280, "height": 900}, accept_downloads=True)
    pg = ctx.new_page()
    # A rejected request (HTTP 400) is the local server's normal answer to invalid input, such as an unknown STL signal.
    pg.on(
        "console",
        lambda m: (
            errors.append(f"console.{m.type}: {m.text}")
            if m.type == "error" and not (not STATIC and "status of 400" in m.text)
            else None
        ),
    )
    pg.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    pg.goto(BASE)
    pg.wait_for_selector(".engine.ready", timeout=240000)
    mode = pg.inner_text("#engine")
    check("engine boots", "ready" in mode, mode)
    if STATIC:
        check("engine runs in the browser", "Pyodide" in mode, mode)
    pg.screenshot(path=f"{SHOTS}/start.png", full_page=True)

    def report_empty():
        pg.click("#nav a[data-route=report]")
        pg.wait_for_selector("text=Session Report")
        check("Report tab opens the live session report (not the static page)", "#/report" in pg.url, pg.url)
        check("empty session report offers first steps", pg.locator("[data-do=replay]").count() == 1)

    guarded("report empty", report_empty)

    def bench():
        pg.goto(BASE + "#/bench")
        pg.click("#runBtn")
        pg.wait_for_selector("#benchOut .banner .chip", timeout=SLOW)
        check(
            "TC-001 passes on the released software", pg.inner_text("#benchOut .banner .big").strip().endswith("PASS")
        )
        check(
            "the run is logged to the session (nav badge)",
            pg.inner_text("#reportCount") == "1",
            pg.inner_text("#reportCount"),
        )
        check("a toast points to the session report", "Session Report" in pg.inner_text("#toast"))
        pg.screenshot(path=f"{SHOTS}/bench.png", full_page=True)
        # parameters: blank -> back to the test's value (no NaN), out of range -> clamped
        pg.select_option("select[name=case]", "TC-003")
        pg.select_option("select[name=sut]", "M07VoltageGuardSign")
        pg.click("details summary")
        pg.fill("input[name=p_soc]", "")
        pg.dispatch_event("input[name=p_soc]", "change")
        check(
            "a blank parameter falls back to the test's value",
            pg.input_value("input[name=p_soc]") not in ("", "NaN"),
            pg.input_value("input[name=p_soc]"),
        )
        pg.fill("input[name=p_r_aging_factor]", "9")
        pg.dispatch_event("input[name=p_r_aging_factor]", "change")
        check(
            "an out-of-range parameter is clamped",
            pg.input_value("input[name=p_r_aging_factor]") == "3",
            pg.input_value("input[name=p_r_aging_factor]"),
        )
        pg.click("#resetParams")
        pg.click("#runBtn")
        pg.wait_for_function(
            "document.querySelector('#benchOut .banner') && document.querySelector('#benchOut .banner').innerText.includes('M07')",
            timeout=SLOW,
        )
        check(
            "M07 on TC-003 fails REQ-HV-001",
            "FAIL" in pg.inner_text("#benchOut .banner .big") and "FAIL" in pg.inner_text("tr[data-req='REQ-HV-001']"),
        )
        # channels, zoom, requirement click
        n_before = pg.locator("#charts figure").count()
        pg.click("#chanChips label:has-text('v_kph')")
        check("signal chips add or remove plots", pg.locator("#charts figure").count() != n_before)
        pg.click("#wViol")
        check(
            "zoom to the first violation fills the window", pg.input_value("#w0") != "" and pg.input_value("#w1") != ""
        )
        pg.click("#wAll")
        check("whole run clears the window", pg.input_value("#w0") == "")
        pg.click("tr[data-req='REQ-HV-001']")
        check("clicking a failed requirement zooms to it", pg.input_value("#w0") != "")
        # exports
        name, csv = downloaded(pg, "#dlCsv")
        check("signals CSV export", csv.startswith("t,") and name.endswith(".csv"))
        name, js = downloaded(pg, "#dlJson")
        check("verdicts JSON export", json.loads(js)["overall"] == "FAIL")
        name, xml = downloaded(pg, "#dlJunit")
        check("JUnit export", "<failure" in xml)
        # HiL tier with overlay
        pg.select_option("select[name=case]", "TC-005")
        pg.select_option("select[name=sut]", "baseline")
        pg.click("#benchForm label:has(input[name=env][value=hil_mock])")
        pg.fill("input[name=seed]", "2")
        pg.dispatch_event("input[name=seed]", "change")
        pg.click("#runBtn")
        pg.wait_for_function(
            "document.querySelector('#benchOut .banner') && document.querySelector('#benchOut .banner').innerText.includes('seed 2')",
            timeout=SLOW,
        )
        check(
            "TC-005 runs on the HiL mock with the chosen seed", "HiL mock, seed 2" in pg.inner_text("#benchOut .banner")
        )
        pg.select_option("select[name=sut]", "M11CanTimeoutTooTight")
        pg.check("input[name=overlay]")
        pg.click("#runBtn")
        pg.wait_for_function(
            "document.querySelector('#benchOut .banner') && document.querySelector('#benchOut .banner').innerText.includes('M11')",
            timeout=SLOW,
        )
        check("overlay draws the released software as a second series", "released" in pg.inner_text("#charts"))

    guarded("bench flow", bench)

    def findings():
        expect = {
            "F-001": "INCONCLUSIVE",
            "F-002": "FAIL",
            "F-003": "FAIL",
            "F-004": "FAIL",
            "F-005": "FAIL",
            "F-006": "FAIL",
        }
        req = {
            "F-001": "REQ-HV-001",
            "F-002": "REQ-HV-002",
            "F-003": "REQ-EM-006",
            "F-004": "REQ-FS-014",
            "F-005": "REQ-FS-014",
            "F-006": "REQ-FS-015",
        }
        for fid, verdict in expect.items():
            n = entries(pg)
            pg.goto(BASE + "#/findings")
            pg.click(f"button.replay[data-id='{fid}']")
            pg.wait_for_function(f"window.volttrace.session.log.entries.length > {n}", timeout=SLOW)
            pg.wait_for_selector("#benchOut .banner .chip")
            big = pg.inner_text("#benchOut .banner .big")
            row = pg.inner_text(f"tr[data-req='{req[fid]}']")
            check(f"{fid} replay: {verdict} on {req[fid]}", verdict in big and verdict in row, f"{big} / {row[:80]}")
            if fid == "F-002":
                check(
                    "F-002 replay draws overlay charts",
                    pg.locator("#charts figure").count() >= 2 and "released" in pg.inner_text("#charts"),
                )
                pg.screenshot(path=f"{SHOTS}/finding_f002.png", full_page=True)

    guarded("findings replays", findings)

    def stl():
        pg.goto(BASE + "#/requirements")
        pg.fill("#stlText", "always(nonsense <= 1)")
        pg.click("#stlRun")
        pg.wait_for_selector("#stlOut .note.bad", timeout=60000)
        check("STL playground reports an unknown signal", "unknown signal" in pg.inner_text("#stlOut"))
        pg.fill("#stlText", "always(v_bus <= 815)")
        pg.click("#stlRun")
        pg.wait_for_selector("#stlOut .banner", timeout=60000)
        out = pg.inner_text("#stlOut .banner")
        check(
            "STL playground evaluates on the last run and names it",
            "robustness" in out and "M14MissingVoltageAsZero" in out,
            out,
        )
        pg.click("code.usestl >> nth=0")
        check("clicking a requirement formula loads it", pg.input_value("#stlText").startswith("always("))

    guarded("STL playground", stl)

    def falsifier():
        pg.goto(BASE + "#/falsify")
        pg.fill("input[name=budget]", "12")
        pg.dispatch_event("input[name=budget]", "change")
        pg.click("#fzRun")
        pg.wait_for_selector("#fzOut .note", timeout=SLOW)
        check("falsifier rediscovers F-002 on M09", "Counterexample found" in pg.inner_text("#fzOut .note h3"))
        name, yml = downloaded(pg, "#dlYaml")
        check("counterexample downloads as a regression test", "requirements" in yml and name.endswith(".yaml"))
        pg.screenshot(path=f"{SHOTS}/falsifier.png", full_page=True)
        n = entries(pg)
        pg.click("#toBench")
        pg.wait_for_function(f"window.volttrace.session.log.entries.length > {n}", timeout=SLOW)
        pg.wait_for_selector("#benchOut .banner .chip")
        check("the counterexample fails on the Test Bench", "FAIL" in pg.inner_text("#benchOut .banner .big"))

    guarded("falsifier", falsifier)

    def ci():
        pg.goto(BASE + "#/ci")
        pg.select_option("select[name=change]", "M05DerateRampInverted")
        pg.click("#ciRun")
        pg.wait_for_selector("#ciOut .note h3", timeout=SLOW)
        check("CI policy C catches M05 on SiL", "TC-004@sil" in pg.inner_text("#ciOut .note h3"))
        pg.click("#ciForm label:has(input[name=policy][value=D])")
        pg.click("#ciRun")
        pg.wait_for_function(
            "document.querySelector('#ciOut .note p') && document.querySelector('#ciOut .note p').innerText.includes('policy D')",
            timeout=SLOW,
        )
        check("CI policy D runs and draws a schedule", pg.locator("#ciGantt svg").count() == 1)
        check(
            "the CI page lists your cycles on this change",
            pg.locator("text=Your cycles on M05DerateRampInverted").count() == 1,
        )
        pg.screenshot(path=f"{SHOTS}/ci.png", full_page=True)

    guarded("CI orchestrator", ci)

    def hunt():
        pg.goto(BASE + "#/hunt")
        pg.click("#huntStart")
        pg.wait_for_selector("#huntForm", timeout=60000)
        pg.click("#huntRun")
        pg.wait_for_selector("#hist button", timeout=SLOW)
        pg.click("#huntForm label:has(input[name=env][value=hil_mock])")
        pg.fill("#huntForm input[name=seed]", "3")
        pg.dispatch_event("#huntForm input[name=seed]", "change")
        pg.select_option("#huntForm select[name=case]", "TC-005")
        pg.click("#huntRun")
        pg.wait_for_function("document.querySelectorAll('#hist button').length === 2", timeout=SLOW)
        check(
            "hunt keeps tier, seed and test between runs",
            pg.is_checked("#huntForm input[name=env][value=hil_mock]")
            and pg.input_value("#huntForm input[name=seed]") == "3"
            and pg.input_value("#huntForm select[name=case]") == "TC-005",
        )
        check("hunt shows the latest run and its rig cost", "HiL mock, seed 3" in pg.inner_text("#huntOut .banner"))
        pg.click("#hist button >> nth=0")
        check("hunt history reopens an earlier run", "SiL" in pg.inner_text("#huntOut .banner"))
        pg.select_option("#guess", index=1)
        pg.click("#reveal")
        pg.wait_for_selector(".note h3:has-text('The change was')", timeout=60000)
        check("bug hunt reveals the change", True)
        pg.screenshot(path=f"{SHOTS}/hunt.png", full_page=True)

    guarded("bug hunt", hunt)

    def report():
        n = entries(pg)
        pg.click("#nav a[data-route=report]")
        pg.wait_for_selector(".tiles")
        tiles = pg.inner_text(".tiles")
        check("report tiles reflect the session", "Test runs" in tiles and "Counterexamples" in tiles)
        check("report has insights", pg.locator("#insights .note").count() >= 2)
        check(
            "report lists every activity",
            pg.locator("#activity tbody tr").count() == n,
            f"{pg.locator('#activity tbody tr').count()} vs {n}",
        )
        check("report shows requirement coverage", "REQ-HV-002" in pg.inner_text("main"))
        name, html = downloaded(pg, "#dlHtml")
        check("session report downloads as HTML", "VoltTrace session report" in html and "REQ-HV-001" in html)
        name, js = downloaded(pg, "#dlJson")
        check("session downloads as JSON", len(json.loads(js)["entries"]) == n)
        name, xml = downloaded(pg, "#dlJunit")
        check("session downloads as JUnit", xml.count("<testsuite ") >= 10 and "<failure" in xml)
        pg.screenshot(path=f"{SHOTS}/report.png", full_page=True)
        pg.click(".rerun >> nth=0")
        pg.wait_for_function(f"window.volttrace.session.log.entries.length > {n}", timeout=SLOW)
        check("'Run again' from the report re-runs that test", "#/bench" in pg.url)
        pg.reload()
        pg.wait_for_selector(".engine.ready", timeout=240000)
        check("the session survives a reload", entries(pg) == n + 1)

    guarded("session report", report)

    def assistant():
        pg.click("#askFab")
        pg.wait_for_selector("#askPanel:not([hidden])")

        def ask(text, timeout=SLOW):
            k = pg.locator("#askLog .msg.bot").count()
            pg.fill("#askInput", text)
            pg.press("#askInput", "Enter")
            pg.wait_for_function(
                f"document.querySelectorAll('#askLog .msg.bot').length > {k} && !document.querySelector('#askLog .spinner')",
                timeout=timeout,
            )
            return pg.locator("#askLog .msg.bot").last.inner_text()

        r = ask("help")
        check("assistant: help lists commands", "replay F-002" in r)
        r = ask("replay F-002")
        check("assistant: replays a finding", "REQ-HV-002" in r and "FAIL" in r and "#/bench" in pg.url, r)
        r = ask("zoom to violation")
        check("assistant: zooms the plots", "Zoomed" in r and pg.input_value("#w0") != "", r)
        r = ask("show v_bus and i_bat")
        check("assistant: chooses signals", pg.locator("#charts figure").count() == 2, r)
        r = ask("run TC-003 with M07 on sil")
        check("assistant: runs a test with version and tier", "M07" in r and "FAIL" in r and "REQ-HV-001" in r, r)
        r = ask("run tc-001 with released soc 50% temp 10")
        check(
            "assistant: edits scenario parameters",
            "Released" in r
            and pg.input_value("input[name=p_soc]") == "0.5"
            and pg.input_value("input[name=p_t_bat_c]") == "10",
            r,
        )
        r = ask("what is M09?")
        check("assistant: answers questions without running", "SOP" in r or "new pack" in r.lower(), r)
        r = ask("falsify M09 budget 10 seed 1")
        check("assistant: runs the falsifier", "COUNTEREXAMPLE" in r or "NONE FOUND" in r, r)
        r = ask("ci C01 policy C")
        check("assistant: runs a CI cycle", "GREEN BUILD" in r and "clean" in r, r)
        r = ask("always(v_bus <= 812)")
        check("assistant: evaluates STL", "robustness" in r, r)
        r = ask("start a hunt")
        check("assistant: starts a hunt", "hidden change is loaded" in r, r)
        r = ask("try TC-001")
        check("assistant: runs on the hidden change", "hidden change" in r, r)
        r = ask("guess no bug")
        check("assistant: reveals the hunt", "It was" in r, r)
        r = ask("explain inconclusive")
        check("assistant: explains concepts", "0.1" in r, r)
        r = ask("summary")
        check("assistant: summarises the session and opens the report", "Your session" in r and "#/report" in pg.url, r)
        r = ask("run TC-003 with M07 then zoom to violation")
        check(
            "assistant: chains steps with 'then'",
            "Zoomed" in r and "M07" in pg.locator("#askLog .msg.bot").nth(-2).inner_text(),
            r,
        )
        pg.click("#askMenuBtn")
        check("assistant: the features menu lists every area", pg.locator("#askMenu .grp").count() >= 8)
        k = pg.locator("#askLog .msg.bot").count()
        pg.click("#askMenu button:has-text('replay F-003')")
        pg.wait_for_function(
            f"document.querySelectorAll('#askLog .msg.bot').length > {k} && !document.querySelector('#askLog .spinner')",
            timeout=SLOW,
        )
        r = pg.locator("#askLog .msg.bot").last.inner_text()
        check("assistant: a menu item runs its command", "F-003" in r and "REQ-EM-006" in r, r)
        r = ask("blorp zzz")
        check("assistant: unknown input gets help, not an error", "did not catch" in r, r)
        pg.screenshot(path=f"{SHOTS}/assistant.png", full_page=False)
        pg.click("#askClose")

    guarded("assistant", assistant)

    def clear():
        pg.goto(BASE + "#/report")
        pg.once("dialog", lambda d: d.accept())
        pg.click("#clearLog")
        pg.wait_for_selector("[data-do=replay]")
        check("clear session empties the report", entries(pg) == 0)

    guarded("clear session", clear)

    # mobile
    m = ctx.new_page()
    m.set_viewport_size({"width": 390, "height": 800})
    m.goto(BASE)
    m.wait_for_selector(".engine.ready", timeout=240000)
    check("no horizontal scroll at 390 px", m.evaluate("document.documentElement.scrollWidth") <= 390)
    m.goto(BASE + "#/report")
    m.click("#askFab")
    check("report and assistant fit at 390 px", m.evaluate("document.documentElement.scrollWidth") <= 390)
    m.screenshot(path=f"{SHOTS}/mobile.png")
    b.close()
check("no console or page errors", not errors, "; ".join(errors))
failed = [n for n, ok, _ in checks if not ok]
print(f"\n{len(checks) - len(failed)}/{len(checks)} checks passed" + (f"; failed: {failed}" if failed else ""))
sys.exit(0 if not failed else 1)
