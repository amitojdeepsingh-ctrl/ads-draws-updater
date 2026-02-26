"""
ADS PathFinder — Automatic Express Entry Draw Updater
Runs daily via GitHub Actions. Fetches IRCC JSON API and updates your Gist.
"""

import json
import os
import re
import requests
from datetime import datetime

GIST_ID       = "aad3e7558039efea6e8b107c66ab4ae9"
GIST_FILENAME = "ads_pathfinder_config.json"

# IRCC publishes draw data as a JSON file — much more reliable than scraping HTML
IRCC_JSON_URL = "https://www.canada.ca/content/dam/ircc/documents/json/ee_rounds_4_en.json"

MONTH_ABBR = {
    "January": "Jan", "February": "Feb", "March": "Mar",
    "April":   "Apr", "May":      "May", "June":  "Jun",
    "July":    "Jul", "August":   "Aug", "September": "Sep",
    "October": "Oct", "November": "Nov", "December":  "Dec",
}

# Map IRCC's drawName values to the short names our app uses
PROGRAM_MAP = [
    ("canadian experience class",              "Canadian Experience Class"),
    ("federal skilled worker",                 "Federal Skilled Worker"),
    ("federal skilled trades",                 "Federal Skilled Trades"),
    ("french language proficiency",            "French Language Proficiency"),
    ("healthcare and social services",         "Healthcare & Social Services"),
    ("healthcare & social services",           "Healthcare & Social Services"),
    ("healthcare occupations",                 "Healthcare & Social Services"),
    ("physicians",                             "Healthcare & Social Services"),
    ("stem occupations",                       "STEM Occupations"),
    ("trade occupations",                      "Trade Occupations"),
    ("transport occupations",                  "Transport Occupations"),
    ("agriculture and agri-food",              "Agriculture & Agri-Food"),
    ("education occupations",                  "Education Occupations"),
    ("provincial nominee program",             "Provincial Nominee Program"),
    ("general",                                "General"),
]


def format_date(date_str):
    """'February 17, 2026'  →  'Feb 17, 2026'"""
    for full, abbr in MONTH_ABBR.items():
        if full in date_str:
            return date_str.replace(full, abbr)
    return date_str.strip()


def map_program(draw_name):
    """Map IRCC drawName to a clean short program name."""
    lower = draw_name.lower()
    for key, val in PROGRAM_MAP:
        if key in lower:
            return val
    # Fallback: use first 40 chars of the draw name
    return draw_name.split(",")[0].strip()[:40]


def fetch_draws():
    """Fetch and parse the latest Express Entry draws from IRCC's JSON API."""
    headers = {"User-Agent": "Mozilla/5.0 (compatible; ADS-PathFinder-Bot/1.0)"}
    resp = requests.get(IRCC_JSON_URL, headers=headers, timeout=30)
    resp.raise_for_status()

    data = resp.json()
    rounds = data.get("rounds", [])
    if not rounds:
        raise RuntimeError("IRCC JSON returned no rounds data.")

    draws = []
    for r in rounds:
        try:
            cutoff  = int(str(r["drawCRS"]).replace(",", ""))
            invited = int(re.sub(r"[^\d]", "", str(r["drawSize"])))
            date    = format_date(r["drawDateFull"])
            program = map_program(r.get("drawName", r.get("drawText2", "General")))

            # Skip special draws outside the normal CRS range
            # (Physicians ~169, PNP ~700+)
            if cutoff < 300 or cutoff > 699:
                print(f"  Skipping draw {r.get('drawNumber','?')}: {program} CRS={cutoff}")
                continue

            draws.append({"date": date, "program": program,
                          "cutoff": cutoff, "invited": invited})
        except (KeyError, ValueError) as err:
            print(f"  Warning: skipping draw — {err}")

    return draws


def cec_cutoff_approx(draws):
    """Average cutoff of the 4 most recent CEC / FSW / General draws."""
    cec_programs = {"Canadian Experience Class", "Federal Skilled Worker", "General"}
    cec = [d for d in draws if d["program"] in cec_programs][:4]
    if not cec:
        return 510
    return round(sum(d["cutoff"] for d in cec) / len(cec))


def fetch_gist(token):
    headers = {"Authorization": f"token {token}",
               "Accept": "application/vnd.github.v3+json"}
    resp = requests.get(f"https://api.github.com/gists/{GIST_ID}", headers=headers)
    resp.raise_for_status()
    content = resp.json()["files"][GIST_FILENAME]["content"]
    return json.loads(content)


def update_gist(token, new_config):
    headers = {"Authorization": f"token {token}",
               "Accept": "application/vnd.github.v3+json"}
    payload = {"files": {GIST_FILENAME: {"content": json.dumps(new_config, indent=2)}}}
    resp = requests.patch(f"https://api.github.com/gists/{GIST_ID}",
                          headers=headers, json=payload)
    resp.raise_for_status()
    print("Gist updated successfully!")


def main():
    token = os.environ.get("GIST_TOKEN")
    if not token:
        raise EnvironmentError("GIST_TOKEN secret is not set.")

    print("Fetching IRCC draw data...")
    fresh = fetch_draws()
    if not fresh:
        raise RuntimeError("No draws parsed from IRCC JSON.")
    print(f"  Found {len(fresh)} draws.")

    print("Fetching current Gist...")
    current = fetch_gist(token)
    current_draws = current.get("draws", [])

    latest_fresh   = fresh[0]["date"]
    latest_current = current_draws[0]["date"] if current_draws else ""

    if latest_fresh == latest_current:
        print(f"No new draws. Latest is still {latest_fresh}. Nothing to update.")
        return

    print(f"New draw detected!  {latest_current}  →  {latest_fresh}")

    # strftime("%-d") uses no zero-padding on Linux (GitHub Actions runner)
    today  = datetime.utcnow().strftime("%-b %-d, %Y")
    cutoff = cec_cutoff_approx(fresh)

    updated = {
        "lastUpdated":     today,
        "cecCutoffApprox": cutoff,
        "draws":           fresh[:15],                     # keep last 15
        "pnpNotices":      current.get("pnpNotices", []), # preserve manual PNP notices
    }

    print(f"  CEC cutoff approx: {cutoff}")
    print(f"  Updating Gist with {len(updated['draws'])} draws...")
    update_gist(token, updated)
    print("Done!")


if __name__ == "__main__":
    main()
