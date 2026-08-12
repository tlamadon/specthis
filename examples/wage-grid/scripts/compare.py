"""One table across every country. Reads each country's moments."""
import json
import pathlib

countries = ["argentina", "chile"]
rows = [json.loads(pathlib.Path(f"results/{c}/moments.json").read_text()) for c in countries]

lines = ["| country | n | mean log wage | variance |", "|---|---|---|---|"]
lines += [f"| {r['country']} | {r['n']} | {r['mean']} | {r['var']} |" for r in rows]

pathlib.Path("reports").mkdir(exist_ok=True)
pathlib.Path("reports/comparison.md").write_text("\n".join(lines) + "\n")
