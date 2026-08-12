"""Mean and variance of log wages for one country. Usage: moments.py COUNTRY"""
import csv
import json
import math
import pathlib
import sys

country = sys.argv[1]
rows = list(csv.DictReader(open(f"data/{country}/wages.csv")))
xs = [math.log(float(r["wage"])) for r in rows]
m = sum(xs) / len(xs)

out = pathlib.Path(f"results/{country}")
out.mkdir(parents=True, exist_ok=True)
(out / "moments.json").write_text(json.dumps(
    {"country": country, "n": len(xs), "mean": round(m, 4),
     "var": round(sum((x - m) ** 2 for x in xs) / len(xs), 4)}, indent=2) + "\n")
