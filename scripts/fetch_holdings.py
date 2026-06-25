import json
import os
import sys
from datetime import date
from playwright.sync_api import sync_playwright
import pandas_market_calendars as mcal

URL = "https://www.troweprice.com/financial-intermediary/us/en/investments/etfs/capital-appreciation-equity-etf.html#holdings"
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

        print("Opening page with #holdings anchor...", file=sys.stderr)
        page.goto(URL, wait_until="networkidle", timeout=90000)
        page.wait_for_timeout(10000)

        # scroll to bottom to trigger lazy loading
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(5000)
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(5000)

        # how many tables exist on the page?
        table_info = page.evaluate("""
            () => {
                var tables = document.querySelectorAll('table');
                var info = [];
                tables.forEach(function(t, i) {
                    var rows = t.querySelectorAll('tbody tr');
                    var headers = Array.from(t.querySelectorAll('th')).map(function(h) { return h.innerText.trim(); });
                    var firstRow = rows[0] ? Array.from(rows[0].querySelectorAll('td')).map(function(c) { return c.innerText.trim().substring(0, 30); }) : [];
                    info.push({
                        index: i,
                        rowCount: rows.length,
                        headers: headers.slice(0, 8),
                        firstRow: firstRow.slice(0, 8)
                    });
                });
                return info;
            }
        """)

        print("Tables found on page:", file=sys.stderr)
        for t in table_info:
            print("  Table {}: {} rows, headers: {}".format(
                t["index"], t["rowCount"], t["headers"]), file=sys.stderr)
            print("    First row: {}".format(t["firstRow"]), file=sys.stderr)

        # check pagination state
        pagination = page.evaluate("""
            () => {
                var next = document.querySelector('div.next');
                var prev = document.querySelector('div.prev');
                var pageInfo = document.body.innerText.match(/\\d+\\s*-\\s*\\d+\\s*of\\s*\\d+/);
                return {
                    hasNext: !!next,
                    nextState: next ? (next.querySelector('beacon-icon-button') ? next.querySelector('beacon-icon-button').getAttribute('motion-state') : 'no btn') : 'no div',
                    hasPrev: !!prev,
                    pageInfo: pageInfo ? pageInfo[0] : 'not found',
                    allPaginationText: document.body.innerText.match(/page \\d+/gi) || []
                };
            }
        """)
        print("Pagination state: {}".format(json.dumps(pagination)), file=sys.stderr)

        # scroll specifically to holdings section and wait longer
        print("Scrolling to holdings section...", file=sys.stderr)
        page.evaluate("""
            () => {
                var el = document.querySelector('#holdings') || document.querySelector('[id*=holding]');
                if (el) el.scrollIntoView();
            }
        """)
        page.wait_for_timeout(8000)

        # re-check tables after scroll
        table_info2 = page.evaluate("""
            () => {
                var tables = document.querySelectorAll('table');
                return { count: tables.length };
            }
        """)
        print("Tables after scroll: {}".format(table_info2["count"]), file=sys.stderr)

        pagination2 = page.evaluate("""
            () => {
                var next = document.querySelector('div.next');
                return {
                    hasNext: !!next,
                    nextState: next ? (next.querySelector('beacon-icon-button') ? next.querySelector('beacon-icon-button').getAttribute('motion-state') : 'no btn') : 'no div',
                    pageInfo: (document.body.innerText.match(/\\d+\\s*-\\s*\\d+\\s*of\\s*\\d+/) || ['not found'])[0]
                };
            }
        """)
        print("Pagination after scroll: {}".format(json.dumps(pagination2)), file=sys.stderr)

        browser.close()


def main():
    today_str = date.today().isoformat()
    today = date.today()

    if not is_nyse_trading_day(today):
        print("{} is not a NYSE trading day -- skipping.".format(today_str), file=sys.stderr)
        sys.exit(0)

    print("Debugging TCAF page structure for {}...".format(today_str), file=sys.stderr)
    scrape_holdings()
    print("Debug done.", file=sys.stderr)


if __name__ == "__main__":
    main()
