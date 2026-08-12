"""Drop non-positive wages for one country. Usage: clean_wages.py COUNTRY"""
import csv
import pathlib
import sys

country = sys.argv[1]
rows = list(csv.DictReader(open(f"data/raw/{country}/wages.csv")))
kept = [r for r in rows if float(r["wage"]) > 0]

out = pathlib.Path(f"data/{country}")
out.mkdir(parents=True, exist_ok=True)
with open(out / "wages.csv", "w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=["id", "year", "wage"])
    w.writeheader()
    w.writerows(kept)
print(f"{country}: kept {len(kept)}/{len(rows)} rows")
