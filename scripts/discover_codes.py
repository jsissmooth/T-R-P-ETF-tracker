import sys
import json
from playwright.sync_api import sync_playwright

ETFS = {
    "TURF": "https://www.troweprice.com/financial-intermediary/us/en/investments/etfs/natural-resources-etf.html",
    "TIER": "https://www.troweprice.com/financial-intermediary/us/en/investments/etfs/international-equity-research-etf.html",
    "TGLB": "https://www.troweprice.com/financial-intermediary/us/en/investments/etfs/global-equity-etf.html",
    "TACN": "https://www.troweprice.com/financial-intermediary/us/en/investments/etfs/active-core-international-equity-etf.html",
    "TACU": "https://www.troweprice.com/financial-intermediary/us/en/investments/etfs/active-core-us-equity-etf.html",
    "TOUS": "https://www.troweprice.com/financial-intermediary/us/en/investments/etfs/international-equity-etf.html",
    "THEQ": "https://www.troweprice.com/financial-intermediary/us/en/investments/etfs/hedged-equity-etf.html",
    "TGRT": "https://www.troweprice.com/financial-intermediary/us/en/investments/etfs/growth-etf.html",
    "TMED": "https://www.troweprice.com/financial-intermediary/us/en/investments/etfs/health-care-etf.html",
}


def discover(ticker, url):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
        )
        page = context.new_page()
        captured = []

        def handle_request(request):
            if "ds-dada/graphql" in request.url:
                try:
                    body = json.loads(request.post_data or "{}")
                    req = (body.get("variables", {})
                               .get("productRequest", {})
                               .get("productRequest", {}))
                    code = req.get("productCode")
                    if code:
                        captured.append(code)
                except Exception:
                    pass

        page.on("request", handle_request)

        page.goto(url, wait_until="networkidle", timeout=90000)
        page.wait_for_timeout(6000)

        # dismiss Financial Advisor dialog
        try:
            btn = page.get_by_role("button", name="Financial Advisor").first
            if btn.is_visible(timeout=2000):
                btn.click()
                page.wait_for_timeout(3000)
        except Exception:
            pass

        # click Holdings tab
        try:
            page.click("a[href='#holdings']", timeout=10000)
            page.wait_for_timeout(8000)
        except Exception:
            pass

        # select date from the 3rd dropdown -- this triggers the GraphQL call
        try:
            selects = page.locator("select").all()
            if len(selects) >= 3:
                selects[2].select_option(index=0)
                page.wait_for_timeout(8000)
            elif len(selects) >= 1:
                # fallback: try any date-looking select
                for sel in selects:
                    opts = sel.locator("option").all_text_contents()
                    joined = " ".join(opts)
                    if "/" in joined and len(opts) > 3:
                        sel.select_option(index=0)
                        page.wait_for_timeout(8000)
                        break
        except Exception:
            pass

        browser.close()
        return captured[0] if captured else "NOT FOUND"


for ticker, url in ETFS.items():
    print("Checking {}...".format(ticker), file=sys.stderr)
    code = discover(ticker, url)
    print("{} = {}".format(ticker, code))
    sys.stdout.flush()
