"""Is there a newer USDA FoodData Central release than the one this repository is built from?

    python scripts/check_usda_release.py            # prints the latest release; exit 1 if it is newer than USDA_RELEASE

Reads USDA's download page (https://fdc.nal.usda.gov/download-datasets/) for the full CSV zips
(FoodData_Central_csv_<date>.zip) and compares the newest date with USDA_RELEASE. Standard library only.
"""

import re
import sys
import urllib.request
from pathlib import Path

PAGE = "https://fdc.nal.usda.gov/download-datasets/"
CURRENT = Path(__file__).resolve().parent.parent / "USDA_RELEASE"


def latest_release() -> str:
    req = urllib.request.Request(PAGE, headers={"User-Agent": "myfoodanalysis-data release check (+https://www.myfoodanalysis.com)"})
    html = urllib.request.urlopen(req, timeout=60).read().decode("utf-8", "replace")
    dates = re.findall(r"FoodData_Central_csv_(\d{4}-\d{2}-\d{2})\.zip", html)
    if not dates:
        raise SystemExit("no full CSV release found on the download page; has the page changed?")
    return max(dates)


if __name__ == "__main__":
    ours = CURRENT.read_text().strip()
    theirs = latest_release()
    print(f"ours {ours}, USDA's latest {theirs}")
    if theirs > ours:
        print(f"NEW_RELEASE={theirs}")
        sys.exit(1)
