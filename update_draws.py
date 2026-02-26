"""
ADS PathFinder — Automatic Express Entry Draw Updater
Runs daily via GitHub Actions. Scrapes IRCC website and updates your Gist.
"""

import json
import os
import re
import requests
from bs4 import BeautifulSoup
from datetime import datetime

GIST_ID       = "aad3e7558039efea6e8b107c66ab4ae9"
GIST_FILENAME = "ads_pathfinder_config.json"
IRCC_URL      = (
    "https://www.canada.ca/en/immigration-refugees-citizenship/services/"
    "immigrate-canada/express-entry/submit-profile/rounds-invitations.html"
)

# Map IRCC's full program names to the short names our app uses
PROGRAM_MAP = {
    "canadian experience class":              "Canadian Experience Class",
    "federal skilled worker":                 "Federal Skilled Worker",
    "federal skilled trades":                 "Federal Skilled Trades",
    "provincial nominee program":             "Provincial Nominee Program",
    "general":                                "General",
    "healthcare and social services":         "Healthcare & Social Services",
    "healthcare & social services":           "Healthcare & Social Services",
    "healthcare occupations":                 "Healthcare & Social Services",
    "french language proficiency":            "French Language Proficiency",
    "stem occupations":                       "STEM Occupations",
    "trade occupations":                      "Trade Occupations",
    "transport occupations":                  "Transport Occupations",
    "agriculture and agri-food occupations":  "Agriculture & Agri-Food",
    "education occupations":                  "Education Occupations",
}

MONTH_ABBR = {
    "January": "Jan", "February": "Feb", "March": "Mar",
    "April":   "Apr", "May":      "May", "June":  "Jun",
    "July":    "Jul", "August":   "Aug", "September": "Sep",
    "October": "Oct", "November": "Nov", "December":  "Dec",
}


def format_date(date_str):
    """'February 17, 2026'  →  'Feb 17, 2026'"""
    for full, abbr in MONTH_ABBR.items():
        if full in date_str:
            return date_str.replace(full, abbr)
    return date_str


def map_program(raw):
    """Map IRCC program name to the name our app uses."""
    lower = raw.lower().strip()
    for key, val in PROGRAM_MAP.items():
        if key in lower:
            return val
    return raw.strip()


def scrape_draws():
    """Scrape the latest Express Entry draws from the IRCC website."""
    headers = {"User-Agent": "Mozilla/5.0 (compatible; ADS-PathFinder-Bot/1.0)"}
    resp = requests.get(IRCC_URL, headers=headers, timeout=30)
    resp.raise_for_status()

    soup  = BeautifulSoup(resp.content, "html.parser")
    table = soup.find("table")
    if not table:
        raise RuntimeError("Could not find draws table on IRCC page — layout may have changed.")

    draws = []
    tbody = table.find("tbody") or table
    for row in tbody.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 5:
            continue
        try:
            # Columns: round | date | draw type | CRS cutoff | invitations
            date    = format_date(cells[1].get_text(strip=True))
            program = map_program(cells[2].get_text(strip=True))
            cutoff  = int(cells[3].get_text(strip=True).replace(",", ""))
            invited = int(re.sub(r"[^\d]", "", cells[4].get_text(strip=True)))

            # Skip PNP-only draws (CRS 700+) — irrelevant for regular pool
            if cutoff > 699:
                continue

            draws.append({"date": date, "program": program,
                          "cutoff": cutoff, "invited": invited})
        except (ValueError, IndexError) as err:
            print(f"  Warning: skipping row — {err}")

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

    print("Scraping IRCC website...")
    fresh = scrape_draws()
    if not fresh:
        raise RuntimeError("No draws parsed — check IRCC page structure.")
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

    today = datetime.utcnow().strftime("%-b %-d, %Y")   # "Feb 26, 2026"
    cutoff = cec_cutoff_approx(fresh)

    updated = {
        "lastUpdated":    today,
        "cecCutoffApprox": cutoff,
        "draws":          fresh[:15],                      # keep last 15
        "pnpNotices":     current.get("pnpNotices", []),   # preserve manual PNP notices
    }

    print(f"  CEC cutoff approx: {cutoff}")
    print(f"  Updating Gist with {len(updated['draws'])} draws...")
    update_gist(token, updated)


if __name__ == "__main__":
    main()
