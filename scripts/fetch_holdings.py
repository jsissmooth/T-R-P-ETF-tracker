import json
import os
import sys
import requests
from datetime import date
import pandas_market_calendars as mcal

GRAPHQL_URL = "https://api.public.troweprice.com/ds-dada/graphql"
API_KEY     = "dfalKOgR1TyFTzz9Uv35a7cUczNRrk1K"
DATA_DIR    = os.path.join(os.path.dirname(__file__), "..", "data")

QUERY = """
query getProduct($productRequest: DataRequest) {
  fetchData(req: $productRequest) {
    type
    fullHoldingsExhibit {
      availableDates
      effectiveDate
      holdings {
        name
        tickerSymbol
        shareQuantity
        percentageTotalNetAssets
        marketValue
        prioritizedIdentifier
        investmentType
        strikePrice
        sectorName
        __typename
      }
      __typename
    }
    __typename
  }
}
"""


def is_nyse_trading_day(d):
    nyse = mcal.get_calendar("NYSE")
    schedule = nyse.schedule(start_date=d.isoformat(), end_date=d.isoformat())
    return not schedule.empty


def fetch_holdings(as_of_date):
    payload = {
        "operationName": "getProduct",
        "variables": {
            "productRequest": {
                "type": "productRequest",
                "context": {
                    "audience": "INTERMEDIARY",
                    "country": "us",
                    "language": "en"
                },
                "productRequest": {
                    "productCode": "CFX",
                    "historicalDates": {
                        "fullHoldings": [as_of_date]
                    }
                }
            }
        },
        "extensions": {
            "clientLibrary": {
                "name": "@apollo/client",
                "version": "4.1.9"
            }
        },
        "query": QUERY
    }

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/graphql-response+json,application/json;q=0.9",
        "apikey": API_KEY,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://www.troweprice.com/",
        "Origin": "https://www.troweprice.com",
    }

    resp = requests.post(GRAPHQL_URL, json=payload, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.json()


def parse_holdings(api_response, today_str):
    exhibits = (
        api_response
        .get("data", {})
        .get("fetchData", {})
        .get("fullHoldingsExhibit", [])
    )

    if not exhibits:
        print("No fullHoldingsExhibit in response.", file=sys.stderr)
        return [], None

    exhibit = exhibits[0]
    available = exhibit.get("availableDates", [])
    print("Available dates: {}".format(available[:5]), file=sys.stderr)

    holdings = exhibit.get("holdings", [])
    effective = exhibit.get("effectiveDate", today_str)
    print("Effective date: {}, Holdings count: {}".format(effective, len(holdings)), file=sys.stderr)

    records = []
    for h in holdings:
        records.append({
            "name":       h.get("name") or "",
            "ticker":     h.get("tickerSymbol") or "",
            "identifier": h.get("prioritizedIdentifier") or "",
            "pct_of_fund":  round(h.get("percentageTotalNetAssets") or 0, 6),
            "quantity":     h.get("shareQuantity"),
            "market_value": h.get("marketValue"),
            "investments":  h.get("investmentType") or "",
            "options_strike": h.get("strikePrice"),
            "sector":       h.get("sectorName") or "",
        })

    return records, effective


def save_snapshot(records, today_str):
    os.makedirs(DATA_DIR, exist_ok=True)
    path = os.path.join(DATA_DIR, "{}.json".format(today_str))
    payload = {"date": today_str, "holdings": records}
    with open(path, "w") as f:
        json.dump(payload, f, indent=2)
    with open(os.path.join(DATA_DIR, "latest.json"), "w") as f:
        json.dump(payload, f, indent=2)
    print("Saved {} holdings to {}".format(len(records), path), file=sys.stderr)


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
                "sector":              t.get("sector") or "",
                "status":              "changed" if round(qty_chg, 6) != 0 else "unchanged",
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
                "identifier": t.get("identifier") or "", "sector": t.get("sector") or "",
                "status": "added",
                "quantity_today": t["quantity"] or 0, "quantity_prior": None,
                "quantity_pct_change": None,
                "pct_of_fund_today": t["pct_of_fund"] or 0, "pct_of_fund_prior": None,
                "pct_of_fund_change": None, "market_value_today": t.get("market_value"),
            })
        else:
            rows.append({
                "ticker": p.get("ticker") or "", "name": p.get("name") or "",
                "identifier": p.get("identifier") or "", "sector": p.get("sector") or "",
                "status": "removed",
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
    today     = date.today()

    if not is_nyse_trading_day(today):
        print("{} is not a NYSE trading day -- skipping.".format(today_str), file=sys.stderr)
        sys.exit(0)

    print("Fetching TCAF holdings for {}...".format(today_str), file=sys.stderr)
    api_response = fetch_holdings(today_str)
    records, effective = parse_holdings(api_response, today_str)

    if not records:
        print("No holdings returned -- exiting.", file=sys.stderr)
        sys.exit(1)

    print("Found {} holdings.".format(len(records)), file=sys.stderr)
    save_snapshot(records, today_str)

    prior_path = find_prior_snapshot(today_str)
    if not prior_path:
        print("No prior snapshot -- skipping diff.", file=sys.stderr)
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
