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

        print("Opening TCAF page...", file=sys.stderr)
        page.goto(URL, wait_until="networkidle", timeout=90000)
        page.wait_for_timeout(8000)

        # click Financial Advisor if visible
        try:
            btn = page.get_by_role("button", name="Financial Advisor").first
            if btn.is_visible(timeout=2000):
                btn.click()
                page.wait_for_timeout(3000)
                print("Clicked Financial Advisor.", file=sys.stderr)
        except Exception:
            pass

        # click Holdings tab
        print("Clicking Holdings tab...", file=sys.stderr)
        try:
            page.click("a[href='#holdings']", timeout=10000)
            page.wait_for_timeout(10000)
        except Exception as e:
            print("Holdings tab error: {}".format(e), file=sys.stderr)

        # find the date selector (3rd select = daily holdings dates)
        # and select today's date to trigger full holdings load
        print("Finding date selector...", file=sys.stderr)
        selects = page.locator("select").all()
        print("  Found {} selects".format(len(selects)), file=sys.stderr)

        holdings_select = None
        for i, sel in enumerate(selects):
            try:
                opts = sel.locator("option").all_text_contents()
                # the holdings date picker has daily dates
                joined = " ".join(opts)
                if "/" in joined and len(opts) > 10:
                    today_str_fmt = date.today().strftime("%-m/%-d/%Y") if sys.platform != "win32" else date.today().strftime("%#m/%#d/%Y")
                    if today_str_fmt in joined or date.today().strftime("%m/%d/%Y") in joined:
                        print("  Select {} looks like holdings date picker ({} options)".format(i, len(opts)), file=sys.stderr)
                        holdings_select = sel
            except Exception:
                pass

        if holdings_select:
            print("Selecting today's date in holdings picker...", file=sys.stderr)
            try:
                # select the first option (most recent = today)
                opts = holdings_select.locator("option").all()
                first_val = opts[0].get_attribute("value") if opts else None
                print("  First option value: {}".format(first_val), file=sys.stderr)
                if first_val:
                    holdings_select.select_option(value=first_val)
                    page.wait_for_timeout(8000)
                    print("  Date selected, waiting for table to reload...", file=sys.stderr)
            except Exception as e:
                print("  Date select error: {}".format(e), file=sys.stderr)
        else:
            print("  Holdings date picker not found.", file=sys.stderr)

        # now find the HOLDINGS table specifically
        # look for tables with stock-like content (has letters, not just percentages)
        print("Finding holdings table...", file=sys.stderr)
        all_tables = page.locator("table").all()
        print("  Total tables: {}".format(len(all_tables)), file=sys.stderr)

        holdings_table = None
        for i, tbl in enumerate(all_tables):
            try:
                rows = tbl.locator("tbody tr").all()
                if not rows:
                    continue
                first_row_cells = rows[0].locator("td").all_text_contents()
                print("  Table {}: {} rows, first row: {}".format(
                    i, len(rows), [c[:25] for c in first_row_cells[:5]]), file=sys.stderr)
                # holdings table should have company names (not just percentages)
                first_cell = first_row_cells[0].strip() if first_row_cells else ""
                if first_cell and not first_cell.replace(".", "").replace("-", "").replace("%", "").replace(",", "").isnumeric():
                    if len(rows) >= 5:
                        print("  --> This looks like the holdings table!", file=sys.stderr)
                        holdings_table = tbl
                        break
            except Exception as e:
                print("  Table {} error: {}".format(i, e), file=sys.stderr)

        if not holdings_table:
            print("Holdings table not found, falling back to all rows.", file=sys.stderr)

        # check pagination state
        next_loc = page.locator("div.next beacon-icon-button")
        n = next_loc.count()
        state = next_loc.get_attribute("motion-state") if n > 0 else "not found"
        print("Next button: count={} state={}".format(n, state), file=sys.stderr)

        # scrape all pages
        page_num = 1
        prev_first_row = None

        while True:
            print("Scraping page {}...".format(page_num), file=sys.stderr)

            if holdings_table:
                rows = holdings_table.locator("tbody tr").all()
            else:
                rows = page.query_selector_all("table tbody tr")

            print("  {} rows".format(len(rows)), file=sys.stderr)

            if not rows:
                print("  No rows -- done.", file=sys.stderr)
                break

            first_row_text = rows[0].inner_text().strip() if hasattr(rows[0], 'inner_text') else ""
            if not first_row_text and rows:
                try:
                    first_row_text = rows[0].text_content().strip()
                except Exception:
                    pass

            if first_row_text == prev_first_row and page_num > 1:
                print("  Unchanged -- done.", file=sys.stderr)
                break
            prev_first_row = first_row_text

            for row in rows:
                try:
                    if hasattr(row, 'query_selector_all'):
                        cells = row.query_selector_all("td")
                        texts = [c.inner_text().strip() for c in cells]
                    else:
                        cells = row.locator("td").all()
                        texts = [c.text_content().strip() for c in cells]

                    if len(texts) < 3:
                        continue

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
                    # only keep rows that look like actual holdings
                    name = record["name"]
                    if name and not name.replace(".", "").replace("-", "").replace("%", "").replace(",", "").replace(" ", "").isnumeric():
                        records.append(record)
                except Exception:
                    pass

            # next page
            next_loc = page.locator("div.next beacon-icon-button")
            n = next_loc.count()
            state = next_loc.get_attribute("motion-state") if n > 0 else "not found"
            print("  Next: count={} state={}".format(n, state), file=sys.stderr)

            if n > 0 and state != "disabled":
                next_loc.click()
                page.wait_for_timeout(3000)
                page_num += 1
            else:
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
                "pct_of_fund_change":  round(pct_today - pct_prior, 4),
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
