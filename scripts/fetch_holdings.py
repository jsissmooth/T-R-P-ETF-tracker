import json
import os
import sys
import requests
from datetime import date
import pandas_market_calendars as mcal

GRAPHQL_URL = "https://api.public.troweprice.com/ds-dada/graphql"
API_KEY     = "dfalKOgR1TyFTzz9Uv35a7cUczNRrk1K"
DATA_DIR    = os.path.join(os.path.dirname(__file__), "..", "data")

ETFS = {
    "TCAF": "CFX",
    "TURF": "NRX",
    "TIER": "IEX",
    "TGLB": "GEX",
    "TACN": "AIX",
    "TACU": "AUX",
    "TOUS": "INX",
    "THEQ": "HEX",
    "TGRT": "GRX",
    "TMED": "HCX",
    "TMSL": "SMX",
}

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


def fetch_holdings(product_code, as_of_date):
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
                    "productCode": product_code,
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


def parse_holdings(api_response):
    exhibits = (
        api_response
        .get("data", {})
        .get("fetchData", {})
        .get("fullHoldingsExhibit", [])
    )
    if not exhibits:
        return []

    holdings = exhibits[0].get("holdings", [])
    records = []
    for h in holdings:
        records.append({
            "name":           h.get("name") or "",
            "ticker":         h.get("tickerSymbol") or "",
            "identifier":     h.get("prioritizedIdentifier") or "",
            "pct_of_fund":    round(h.get("percentageTotalNetAssets") or 0, 6),
            "quantity":       h.get("shareQuantity"),
            "market_value":   h.get("marketValue"),
            "investments":    h.get("investmentType") or "",
            "options_strike": h.get("strikePrice"),
            "sector":         h.get("sectorName") or "",
        })
    return records


def get_etf_data_dir(etf_ticker):
    d = os.path.join(DATA_DIR, etf_ticker)
    os.makedirs(d, exist_ok=True)
    return d


def save_snapshot(records, today_str, etf_ticker):
    data_dir = get_etf_data_dir(etf_ticker)
    path = os.path.join(data_dir, "{}.json".format(today_str))
    payload = {"date": today_str, "ticker": etf_ticker, "holdings": records}
    with open(path, "w") as f:
        json.dump(payload, f, indent=2)
    with open(os.path.join(data_dir, "latest.json"), "w") as f:
        json.dump(payload, f, indent=2)


def find_prior_snapshot(today_str, etf_ticker):
    data_dir = get_etf_data_dir(etf_ticker)
    files = sorted(
        f for f in os.listdir(data_dir)
        if f.endswith(".json") and f not in ("latest.json", "diff.json", "history.json")
    )
    prior = [f for f in files if f.replace(".json", "") < today_str]
    return os.path.join(data_dir, prior[-1]) if prior else None


def compute_diff(today_records, prior_records, today_str, prior_date_str, etf_ticker):
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
    return {"date": today_str, "ticker": etf_ticker, "prior_date": prior_date_str, "diff": rows}


def append_history(today_str, diff, etf_ticker):
    data_dir = get_etf_data_dir(etf_ticker)
    history_path = os.path.join(data_dir, "history.json")
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


def process_etf(etf_ticker, product_code, today_str):
    print("Fetching {} ({})...".format(etf_ticker, product_code), file=sys.stderr)
    try:
        api_response = fetch_holdings(product_code, today_str)
        records = parse_holdings(api_response)
        if not records:
            print("  No holdings returned for {}.".format(etf_ticker), file=sys.stderr)
            return
        print("  {} holdings found.".format(len(records)), file=sys.stderr)
        save_snapshot(records, today_str, etf_ticker)

        prior_path = find_prior_snapshot(today_str, etf_ticker)
        if not prior_path:
            diff_rows = []
            for r in records:
                diff_rows.append({
                    "ticker":              r.get("ticker") or "",
                    "name":                r.get("name") or "",
                    "identifier":          r.get("identifier") or "",
                    "sector":              r.get("sector") or "",
                    "status":              "unchanged",
                    "quantity_today":      r["quantity"] or 0,
                    "quantity_prior":      r["quantity"] or 0,
                    "quantity_pct_change": 0,
                    "pct_of_fund_today":   r["pct_of_fund"] or 0,
                    "pct_of_fund_prior":   r["pct_of_fund"] or 0,
                    "pct_of_fund_change":  0,
                    "market_value_today":  r.get("market_value"),
                })
            diff = {"date": today_str, "ticker": etf_ticker, "prior_date": None, "diff": diff_rows}
        else:
            with open(prior_path) as f:
                prior_data = json.load(f)
            diff = compute_diff(records, prior_data["holdings"], today_str, prior_data["date"], etf_ticker)

        data_dir = get_etf_data_dir(etf_ticker)
        with open(os.path.join(data_dir, "diff.json"), "w") as f:
            json.dump(diff, f, indent=2)

        append_history(today_str, diff, etf_ticker)

        changed = sum(1 for r in diff["diff"] if r["status"] == "changed")
        added   = sum(1 for r in diff["diff"] if r["status"] == "added")
        removed = sum(1 for r in diff["diff"] if r["status"] == "removed")
        print("  Done -- {} changed | {} added | {} removed".format(
            changed, added, removed), file=sys.stderr)

    except Exception as e:
        print("  ERROR for {}: {}".format(etf_ticker, e), file=sys.stderr)


def main():
    today_str = date.today().isoformat()
    today     = date.today()

    if not is_nyse_trading_day(today):
        print("{} is not a NYSE trading day -- skipping.".format(today_str), file=sys.stderr)
        sys.exit(0)

    print("Running for {}...".format(today_str), file=sys.stderr)
    for etf_ticker, product_code in ETFS.items():
        process_etf(etf_ticker, product_code, today_str)
    print("All done.", file=sys.stderr)


if __name__ == "__main__":
    main()
