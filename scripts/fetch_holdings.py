import json
import os
import sys
from datetime import date
from playwright.sync_api import sync_playwright
import pandas_market_calendars as mcal

TCAF_URL = "https://www.troweprice.com/financial-intermediary/us/en/investments/etfs/capital-appreciation-equity-etf.html"
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")


def is_nyse_trading_day(d):
    nyse = mcal.get_calendar("NYSE")
    schedule = nyse.schedule(start_date=d.isoformat(), end_date=d.isoformat())
    return not schedule.empty


def dismiss_popups(page):
    """Try to dismiss any popups or dialogs on the page."""
    popup_selectors = [
        # close buttons
        "button[aria-label='Close']",
        "button[aria-label='close']",
        "button.close",
        ".modal-close",
        # audience selection
        "a:has-text('Financial Advisors')",
        "a:has-text('Financial Advisor')",
        "button:has-text('Financial Advisor')",
        # generic accept/confirm
        "button:has-text('I Agree')",
        "button:has-text('I Accept')",
        "button:has-text('Accept All')",
        "button:has-text('Accept')",
        "button:has-text('Confirm')",
        "button:has-text('OK')",
        # T. Rowe Price specific
        "button:has-text('I am a Financial')",
        "a:has-text('Intermediar')",
    ]
    for sel in popup_selectors:
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=1500):
                text = el.inner_text()
                print("  Dismissing: '{}' ({})".format(text.strip()[:50], sel), file=sys.stderr)
                el.click()
                page.wait_for_timeout(2000)
        except Exception:
            pass


def scrape_holdings():
    records = []

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

        # Step 1: land on main T. Rowe Price homepage first to trigger audience selector
        print("Step 1: visiting main homepage...", file=sys.stderr)
        page.goto("https://www.troweprice.com", wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(4000)

        snippet = page.evaluate("() => document.body.innerText.substring(0, 400)")
        print("Main homepage snippet: {}".format(snippet[:200]), file=sys.stderr)

        dismiss_popups(page)
        page.wait_for_timeout(2000)

        # Step 2: navigate to FA section
        print("Step 2: navigating to FA homepage...", file=sys.stderr)
        page.goto(
            "https://www.troweprice.com/financial-intermediary/us/en/home.html",
            wait_until="networkidle", timeout=60000
        )
        page.wait_for_timeout(4000)

        dismiss_popups(page)
        page.wait_for_timeout(2000)

        snippet2 = page.evaluate("() => document.body.innerText.substring(0, 400)")
        print("FA homepage snippet: {}".format(snippet2[:200]), file=sys.stderr)

        # Step 3: navigate to TCAF page
        print("Step 3: navigating to TCAF page...", file=sys.stderr)
        page.goto(TCAF_URL, wait_until="networkidle", timeout=90000)
        page.wait_for_timeout(6000)

        dismiss_popups(page)
        page.wait_for_timeout(3000)

        # Step 4: click the Holdings tab
        print("Step 4: clicking Holdings tab...", file=sys.stderr)
        try:
            page.click("a[href='#holdings']", timeout=10000)
            page.wait_for_timeout(8000)
            print("  Holdings tab clicked.", file=sys.stderr)
        except Exception as e:
            print("  Holdings tab error: {}".format(e), file=sys.stderr)

        dismiss_popups(page)

        # Step 5: wait for table
        print("Step 5: waiting for table...", file=sys.stderr)
        try:
            page.wait_for_selector("table tbody tr", timeout=30000)
            page.wait_for_timeout(3000)
        except Exception as e:
            print("  Table wait error: {}".format(e), file=sys.stderr)

        # debug: count tables and pagination
        debug = page.evaluate("""
            () => {
                var tables = document.querySelectorAll('table');
                var next = document.querySelector('div.next');
                var rows = document.querySelectorAll('table tbody tr');
                var pageText = (document.body.innerText.match(/\\d+\\s*[-–]\\s*\\d+\\s*of\\s*\\d+/i) || ['not found'])[0];
                return {
                    tableCount: tables.length,
                    totalRows: rows.length,
                    hasNext: !!next,
                    nextState: next ? (next.querySelector('beacon-icon-button') ?
                        next.querySelector('beacon-icon-button').getAttribute('motion-state') : 'no btn') : 'no div',
                    pageText: pageText
                };
            }
        """)
        print("Debug: {}".format(json.dumps(debug)), file=sys.stderr)

        # Step 6: scrape all pages
        page_num = 1
        prev_first_row = None

        while True:
            print("Scraping page {}...".format(page_num), file=sys.stderr)

            rows = page.query_selector_all("table tbody tr")
            print("  {} rows".format(len(rows)), file=sys.stderr)

            if not rows:
                print("  No rows found -- stopping.", file=sys.stderr)
                break

            first_row_text = rows[0].inner_text().strip()
            if first_row_text == prev_first_row and page_num > 1:
                print("  Page unchanged -- stopping.", file=sys.stderr)
                break
            prev_first_row = first_row_text

            for row in rows:
                cells = row.query_selector_all("td")
                if len(cells) < 3:
                    continue
                texts = [c.inner_text().strip() for c in cells]
                record = {
                    "name":           texts[0] if len(texts) > 0 else "",
                    "pct_of_fund":    texts[1] if len(texts) > 1 else "",
                    "ticker":         texts[2] if len(texts) > 2 else "",
                    "identifier":     texts[3] if len(texts) > 3 else "",
                    "investments":    texts[4] if len(texts) > 4 else "",
                    "options_strike": texts[5] if len(texts) > 5 else "",
                    "quantity":       texts[6] if len(texts) > 6 else "",
                    "market_value":   texts[7] if len(texts) > 7 else "",
                }
                if record["name"] or record["ticker"]:
                    records.append(record)

            # try to go to next page
            print("  Checking next button...", file=sys.stderr)
            try:
                page.wait_for_function(
                    """() => {
                        var d = document.querySelector('div.next');
                        if (!d) return false;
                        var b = d.querySelector('beacon-icon-button');
                        if (!b) return false;
                        return b.getAttribute('motion-state') !== 'disabled';
                    }""",
                    timeout=10000
                )
                print("  Next enabled -- clicking.", file=sys.stderr)
                page.locator("div.next beacon-icon-button").click()
                page.wait_for_timeout(3000)
                page_num += 1
            except Exception:
                print("  No next page -- done.", file=sys.stderr)
                break

            if page_num > 20:
                break

        browser.close()

    return records


def safe_float(s):
    try:
        return round(float(str(s).replace(",", "").replace("%", "").replace("$", "").strip()), 6)
    except (ValueError, TypeError):
        return None


def normalize(records):
    out = []
    for r in records:
        out.append({
            "name":           r.get("name", ""),
            "ticker":         r.get("ticker", ""),
            "identifier":     r.get("identifier", ""),
            "pct_of_fund":    safe_float(r.get("pct_of_fund")),
            "quantity":       safe_float(r.get("quantity")),
            "market_value":   safe_float(r.get("market_value")),
            "investments":    r.get("investments", ""),
            "options_strike": r.get("options_strike", ""),
        })
    return out


def save_snapshot(records, today_str):
    os.makedirs(DATA_DIR, exist_ok=True)
    path = os.path.join(DATA_DIR, "{}.json".format(today_str))
    payload = {"date": today_str, "holdings": records}
    with open(path, "w") as f:
        json.dump(payload, f, indent=2)
    with open(os.path.join(DATA_DIR, "latest.json"), "w") as f:
        json.dump(payload, f, indent=2)
    print("Saved {} holdings".format(len(records)), file=sys.stderr)


def find_prior_snapshot(today_str):
    files = sorted(
        f for f in os.listdir(DATA_DIR)
        if f.endswith(".json") and f not in ("latest.json", "diff.json", "history.json")
    )
    prior = [f for f in files if f.replace(".json", "") < today_str]
    return os.path.join(DATA_DIR, prior[-1]) if prior else None


def compute_diff(today_records, prior_records, today_str, prior_date_str):
    today_map = {r["ticker"] or r["name"]: r for r in today_records}
    prior_map = {r["ticker"] or r["name"]: r for r in prior_records}
    all_keys  = sorted(set(today_map) | set(prior_map))
    rows = []
    for key in all_keys:
        t = today_map.get(key)
        p = prior_map.get(key)
        if t and p:
            q_today   = t["quantity"] or 0
            q_prior   = p["quantity"] or 0
            pct_today = t["pct_of_fund"] or 0
            pct_prior = p["pct_of_fund"] or 0
            qty_chg   = ((q_today - q_prior) / q_prior * 100) if q_prior != 0 else 0
            pct_chg   = round(pct_today - pct_prior, 4)
            rows.append({
                "ticker":              t.get("ticker") or p.get("ticker") or "",
                "name":                t.get("name") or p.get("name") or "",
                "identifier":          t.get("identifier") or "",
                "status":              "changed" if qty_chg != 0 else "unchanged",
                "quantity_today":      q_today,
                "quantity_prior":      q_prior,
                "quantity_pct_change": round(qty_chg, 4),
                "pct_of_fund_today":   pct_today,
                "pct_of_fund_prior":   pct_prior,
                "pct_of_fund_change":  pct_chg,
                "market_value_today":  t.get("market_value"),
            })
        elif t:
            rows.append({
                "ticker": t.get("ticker") or "", "name": t.get("name") or "",
                "identifier": t.get("identifier") or "", "status": "added",
                "quantity_today": t["quantity"] or 0, "quantity_prior": None,
                "quantity_pct_change": None,
                "pct_of_fund_today": t["pct_of_fund"] or 0, "pct_of_fund_prior": None,
                "pct_of_fund_change": None, "market_value_today": t.get("market_value"),
            })
        else:
            rows.append({
                "ticker": p.get("ticker") or "", "name": p.get("name") or "",
                "identifier": p.get("identifier") or "", "status": "removed",
                "quantity_today": None, "quantity_prior": p["quantity"] or 0,
                "quantity_pct_change": None, "pct_of_fund_today": None,
                "pct_of_fund_prior": p["pct_of_fund"] or 0,
                "pct_of_fund_change": None, "market_value_today": None,
            })
    return {"date": today_str, "prior_date": prior_date_str, "diff": rows}


def append_history(today_str, diff):
    history_path = os.path.join(DATA_DIR, "history.json")
    history = []
    if os.path.exists(history_path):
        with open(history_path) as f:
            history = json.load(f)
    entry = {"date": today_str, "prior_date": diff["prior_date"]}
    if entry not in history:
        history.append(entry)
        history.sort(key=lambda x: x["date"], reverse=True)
    with open(history_path, "w") as f:
        json.dump(history, f, indent=2)


def main():
    today_str = date.today().isoformat()
    today = date.today()

    if not is_nyse_trading_day(today):
        print("{} is not a NYSE trading day -- skipping.".format(today_str), file=sys.stderr)
        sys.exit(0)

    print("Scraping TCAF holdings for {}...".format(today_str), file=sys.stderr)
    raw = scrape_holdings()
    records = normalize(raw)
    print("Found {} total holdings.".format(len(records)), file=sys.stderr)

    save_snapshot(records, today_str)

    prior_path = find_prior_snapshot(today_str)
    if not prior_path:
        diff = {"date": today_str, "prior_date": None, "diff": []}
    else:
        with open(prior_path) as f:
            prior_data = json.load(f)
        diff = compute_diff(records, prior_data["holdings"], today_str, prior_data["date"])

    with open(os.path.join(DATA_DIR, "diff.json"), "w") as f:
        json.dump(diff, f, indent=2)

    append_history(today_str, diff)

    changed = sum(1 for r in diff["diff"] if r["status"] == "changed")
    added   = sum(1 for r in diff["diff"] if r["status"] == "added")
    removed = sum(1 for r in diff["diff"] if r["status"] == "removed")
    print("Done -- {} holdings | {} changed | {} added | {} removed".format(
        len(records), changed, added, removed), file=sys.stderr)


if __name__ == "__main__":
    main()
