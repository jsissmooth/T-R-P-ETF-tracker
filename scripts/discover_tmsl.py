import json
from playwright.sync_api import sync_playwright

URL = "https://www.troweprice.com/financial-intermediary/us/en/investments/etfs/small-mid-cap-etf.html"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        viewport={"width": 1920, "height": 1080},
    )
    page = context.new_page()
    found = []

    def handle_request(request):
        if "ds-dada/graphql" in request.url:
            try:
                body = json.loads(request.post_data or "{}")
                code = (body.get("variables", {})
                            .get("productRequest", {})
                            .get("productRequest", {})
                            .get("productCode"))
                if code:
                    found.append(code)
            except Exception:
                pass

    page.on("request", handle_request)
    page.goto(URL, wait_until="networkidle", timeout=90000)
    page.wait_for_timeout(6000)

    try:
        btn = page.get_by_role("button", name="Financial Advisor").first
        if btn.is_visible(timeout=2000):
            btn.click()
            page.wait_for_timeout(3000)
    except Exception:
        pass

    try:
        page.click("a[href='#holdings']", timeout=8000)
        page.wait_for_timeout(6000)
    except Exception:
        pass

    try:
        selects = page.locator("select").all()
        if len(selects) >= 3:
            selects[2].select_option(index=0)
            page.wait_for_timeout(8000)
    except Exception:
        pass

    browser.close()
    print("TMSL product code: {}".format(found[0] if found else "NOT FOUND"))
