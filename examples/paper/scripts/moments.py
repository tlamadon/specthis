"""Mean and population variance of log wages, by year, on positive wages."""
import csv
import json
import math
import pathlib

rows = list(csv.DictReader(open("data/raw/wages.csv")))
by_year: dict[str, list[float]] = {}
for r in rows:
    if float(r["wage"]) > 0:
        by_year.setdefault(r["year"], []).append(math.log(float(r["wage"])))

out = {}
for year, xs in sorted(by_year.items()):
    m = sum(xs) / len(xs)
    out[year] = {"n": len(xs), "mean": round(m, 4),
                 "var": round(sum((x - m) ** 2 for x in xs) / len(xs), 4)}

pathlib.Path("results").mkdir(exist_ok=True)
pathlib.Path("results/moments.json").write_text(json.dumps(out, indent=2) + "\n")
