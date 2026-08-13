"""Drop non-positive wages; one row per worker-year."""
import csv
import pathlib

rows = list(csv.DictReader(open("data/raw/wages.csv")))
kept = [r for r in rows if float(r["wage"]) > 0]

pathlib.Path("data").mkdir(exist_ok=True)
with open("data/wages.csv", "w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=["id", "year", "wage"])
    w.writeheader()
    w.writerows(kept)
print(f"kept {len(kept)}/{len(rows)} rows")
