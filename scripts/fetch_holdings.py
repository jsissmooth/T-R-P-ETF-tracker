import json
import os
import sys
from datetime import date
from playwright.sync_api import sync_playwright
import pandas_market_calendars as mcal

URL = "https://www.troweprice.com/financial-intermediary/us/en/investments/etfs/capital-appreciation-equity-etf.html"
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")


def is_nyse_trading_day(d):
    nyse = mcal.get_calendar("NYSE")
    schedule = nyse.schedule(start_date=d.isoformat(), end_date=d.isoformat())
    return not schedule.empty


def scrape_holdings():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1920, "height": 1080},
        )
        page = context.new_page()

        print("Opening TCAF page...", file=sys.stderr)
        page.goto(URL, wait_until="networkidle", timeout=90000)
        page.wait_for_timeout(8000)

        # click Financial Advisor
        try:
            btn = page.get_by_role("button", name="Financial Advisor").first
            if btn.is_visible(timeout=2000):
                btn.click()
                page.wait_for_timeout(3000)
                print("Clicked Financial Advisor.", file=sys.stderr)
        except Exception:
            pass

        # click Holdings tab
        page.click("a[href='#holdings']", timeout=10000)
        page.wait_for_timeout(10000)

        # select today's date in holdings picker
        selects = page.locator("select").all()
        for i, sel in enumerate(selects):
            try:
                opts = sel.locator("option").all_text_contents()
                joined = " ".join(opts)
                if "/" in joined and len(opts) > 10:
                    first_opt = sel.locator("option").first
                    val = first_opt.get_attribute("value")
                    print("Selecting date {} in select {}...".format(val, i), file=sys.stderr)
                    sel.select_option(index=0)
                    page.wait_for_timeout(15000)
                    break
            except Exception:
                pass

        # dump inner_text of every table
        tables = page.locator("table").all()
        print("Total tables: {}".format(len(tables)), file=sys.stderr)
        for i, tbl in enumerate(tables):
            try:
                txt = tbl.inner_text()
                print("\n=== TABLE {} ===".format(i), file=sys.stderr)
                print(txt[:800], file=sys.stderr)
            except Exception as e:
                print("Table {} error: {}".format(i, e), file=sys.stderr)

        browser.close()


def main():
    today_str = date.today().isoformat()
    today = date.today()

    if not is_nyse_trading_day(today):
        print("{} is not a NYSE trading day -- skipping.".format(today_str), file=sys.stderr)
        sys.exit(0)

    print("Dumping table contents for {}...".format(today_str), file=sys.stderr)
    scrape_holdings()
    print("Done.", file=sys.stderr)


if __name__ == "__main__":
    main()
