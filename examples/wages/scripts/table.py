"""Render the moments as a markdown table."""
import json
import pathlib

m = json.loads(pathlib.Path("results/moments.json").read_text())
lines = ["| year | n | mean log wage | variance |", "|---|---|---|---|"]
lines += [f"| {y} | {v['n']} | {v['mean']} | {v['var']} |" for y, v in sorted(m.items())]

pathlib.Path("reports").mkdir(exist_ok=True)
pathlib.Path("reports/table.md").write_text("\n".join(lines) + "\n")
