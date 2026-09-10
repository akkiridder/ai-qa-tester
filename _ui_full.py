import io, sys
from playwright.sync_api import sync_playwright

PID = "59ad20d90fcf48c3"  # Seed Test Project (has 147 tcs, 127 results)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width":1440,"height":900})
    errors = []
    failed_reqs = []
    page.on("console", lambda m: errors.append(m.text) if m.type=="error" else None)
    page.on("pageerror", lambda e: errors.append("PAGEERR: "+str(e)))
    page.on("requestfailed", lambda r: failed_reqs.append((r.url, r.failure)))
    page.on("response", lambda r: failed_reqs.append((r.url, r.status)) if r.status>=400 and "/api/" in r.url else None)

    report = []
    def shot(name):
        page.screenshot(path=rf"C:\Users\AKSHAY~1\AppData\Local\Temp\opencode\qa2_{name}.png")
        report.append(f"screenshot: {name}")
    def note(msg):
        report.append(msg)
        print(msg)

    # 1 Dashboard
    page.goto("http://127.0.0.1:5000/", wait_until="domcontentloaded", timeout=40000)
    page.wait_for_timeout(2500)
    note("dashboard stat values: " + page.inner_text("#ds-projects").strip() if page.locator("#ds-projects").count() else "NO #ds-projects")
    note("dash-recent-runs loaded: " + ("yes" if "Loading" not in page.inner_text("#dash-recent-runs") else "still loading"))
    note("dash-projects-health loaded: " + ("yes" if "Loading" not in page.inner_text("#dash-projects-health") else "still loading"))
    shot("1_dashboard")

    # 2 Projects
    page.click("text=Projects")
    page.wait_for_timeout(2000)
    card_count = page.locator(".project-card, .projects-grid > *").count()
    note("projects cards: " + str(card_count))
    shot("2_projects")

    # 3 Open workspace of first project card containing name
    page.locator(".project-card").first.click()
    page.wait_for_timeout(2500)
    ws_name = page.inner_text("#ws-project-name").strip() if page.locator("#ws-project-name").count() else "(none)"
    note("workspace project name: " + ws_name)
    tc_count = page.inner_text("#ws-tc-count").strip()
    note("workspace tc count: " + tc_count)
    # device switcher present
    for mode in ["standard","mobile","both"]:
        page.click(f".device-btn[data-mode='{mode}']")
        page.wait_for_timeout(300)
    note("device switcher: all 3 modes clickable")
    shot("3_workspace")

    # run controls present
    note("run dropdown options: " + str(page.locator("#ws-tc-select option").count()))
    note("run all button: " + ("present" if page.locator("text=Run All").count() else "missing"))
    note("AI Discovery button: " + ("present" if page.locator("#ai-discovery-btn").count() else "missing"))

    # 4 Back to projects, then Results
    page.click("text=Back")
    page.wait_for_timeout(1500)
    page.click("text=Results")
    page.wait_for_timeout(2500)
    note("results page text sample: " + page.inner_text("#results-content")[:150].replace("\n"," "))
    shot("4_results")

    # open a result detail
    res_link = page.locator("a[href*='/results/'], [data-result], .result-item, .result-card").first
    clickable = page.locator("#results-content a").first
    if clickable.count():
        href = clickable.get_attribute("href")
        note("first result link href: " + str(href))
        clickable.click()
        page.wait_for_timeout(2500)
        note("result detail loaded")
        shot("5_result_detail")

    # 5 Settings
    page.click("text=Settings")
    page.wait_for_timeout(3000)
    cfg_html = page.eval_on_selector("#config-content","el=>el.innerHTML")
    note("settings has cfg-grid: " + str("cfg-grid" in cfg_html))
    note("settings has selected ollama: " + str('value="ollama" selected' in cfg_html))
    note("settings has qwen model option: " + str("qwen2.5-coder:3b" in cfg_html))
    note("settings has Connected status: " + str("Connected" in cfg_html))
    # switch provider to cloud and back to verify the toggle works
    page.select_option("#cfg-provider", "cloud")
    page.wait_for_timeout(500)
    note("cloud card visible after switch: " + str(page.locator("#cfg-cloud-card").is_visible()))
    page.select_option("#cfg-provider", "ollama")
    page.wait_for_timeout(500)
    shot("6_settings")

    # 6 Help
    page.click("text=Help & Resources")
    page.wait_for_timeout(1200)
    note("help cards: " + str(page.locator(".help-card").count()))
    shot("7_help")

    # Theme switch
    page.click("text=Light")
    page.wait_for_timeout(400)
    note("theme body class: " + str(page.evaluate("document.body.dataset.theme || document.body.className")))
    page.click("text=Dark")

    note("=== ERRORS ===")
    note("console errors: " + str(len(errors)))
    for e in errors[:20]: note("  CE: " + e)
    apifails = [f"{u} -> {s}" for u,s in failed_reqs if "/api/" in u]
    note("api/failed requests: " + str(len(apifails)))
    for f in apifails[:20]: note("  RF: " + f)

    with io.open(r"C:\Users\AKSHAY~1\AppData\Local\Temp\opencode\qa2_report.txt","w",encoding="utf-8") as f:
        f.write("\n".join(report))
    browser.close()
print("done")
