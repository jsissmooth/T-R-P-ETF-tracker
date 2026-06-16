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
    records = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ))

        print("Opening page...", file=sys.stderr)
        page.goto(URL, wait_until="networkidle", timeout=90000)
        page.wait_for_timeout(5000)

        # scroll to holdings section
        page.evaluate("document.querySelector('#holdings') && document.querySelector('#holdings').scrollIntoView()")
        page.wait_for_timeout(3000)

        # wait for table
        page.wait_for_selector("table tbody tr", timeout=30000)
        page.wait_for_timeout(2000)

        page_num = 1
        while True:
            print("Scraping page {}...".format(page_num), file=sys.stderr)

            rows = page.query_selector_all("table tbody tr")
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

            # find next button inside div.next > beacon-icon-button
            next_disabled = page.evaluate("""
                () => {
                    var divNext = document.querySelector('div.next');
                    if (!divNext) return true;
                    var btn = divNext.querySelector('beacon-icon-button');
                    if (!btn) return true;
                    var inner = btn.shadowRoot && btn.shadowRoot.querySelector('button');
                    if (!inner) return true;
                    return inner.disabled || btn.getAttribute('motion-state') === 'disabled';
                }
            """)

            if next_disabled:
                print("Next button disabled or not found -- done.", file=sys.stderr)
                break

            # click the beacon-icon-button inside div.next
            clicked = page.evaluate("""
                () => {
                    var divNext = document.querySelector('div.next');
                    if (!divNext) return false;
                    var btn = divNext.querySelector('beacon-icon-button');
                    if (!btn) return false;
                    btn.click();
                    return true;
                }
            """)

            if not clicked:
                print("Could not click next button -- done.", file=sys.stderr)
                break

            page.wait_for_timeout(3000)
            page_num += 1

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
                "ticker":              t.get("ticker") or "",
                "name":                t.get("name") or "",
                "identifier":          t.get("identifier") or "",
                "status":              "added",
                "quantity_today":      t["quantity"] or 0,
                "quantity_prior":      None,
                "quantity_pct_change": None,
                "pct_of_fund_today":   t["pct_of_fund"] or 0,
                "pct_of_fund_prior":   None,
                "pct_of_fund_change":  None,
                "market_value_today":  t.get("market_value"),
            })
        else:
            rows.append({
                "ticker":              p.get("ticker") or "",
                "name":                p.get("name") or "",
                "identifier":          p.get("identifier") or "",
                "status":              "removed",
                "quantity_today":      None,
                "quantity_prior":      p["quantity"] or 0,
                "quantity_pct_change": None,
                "pct_of_fund_today":   None,
                "pct_of_fund_prior":   p["pct_of_fund"] or 0,
                "pct_of_fund_change":  None,
                "market_value_today":  None,
            })

    return {"date": today_str, "prior_date": prior_date_str, "diff": rows}


def append_history(today_str, diff):
    history_path = os.path.join(DATA_DIR, "history.json")
    if os.path.exists(history_path):
        with open(history_path) as f:
            history = json.load(f)
    else:
        history = []
    entry = {"date": today_str, "prior_date": diff["prior_date"]}
    if entry not in history:
        history.append(entry)
        history.sort(key=lambda x: x["date"], reverse=True)
    with open(history_path, "w") as f:
        json.dump(history, f, indent=2)


def main():
    today_str = date.today().isoformat()
    today     = date.today()

    if not is_nyse_trading_day(today):
        print("{} is not a NYSE trading day -- skipping.".format(today_str), file=sys.stderr)
        sys.exit(0)

    print("Scraping TCAF holdings for {}...".format(today_str), file=sys.stderr)
    raw     = scrape_holdings()
    records = normalize(raw)
    print("Found {} holdings.".format(len(records)), file=sys.stderr)

    save_snapshot(records, today_str)

    prior_path = find_prior_snapshot(today_str)
    if not prior_path:
        print("No prior snapshot -- skipping diff.", file=sys.stderr)
        diff = {"date": today_str, "prior_date": None, "diff": []}
    else:
        with open(prior_path) as f:
            prior_data = json.load(f)
        prior_date_str = prior_data["date"]
        print("Diffing vs {}...".format(prior_date_str), file=sys.stderr)
        diff = compute_diff(records, prior_data["holdings"], today_str, prior_date_str)

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
