"""Render the moments as the tabular the paper inputs."""
import json
import pathlib

m = json.loads(pathlib.Path("results/moments.json").read_text())
lines = [r"\begin{tabular}{lccc}", r"year & $n$ & mean log wage & variance \\ \hline"]
lines += [f"{y} & {v['n']} & {v['mean']:.4f} & {v['var']:.4f} \\\\" for y, v in sorted(m.items())]
lines += [r"\end{tabular}"]

pathlib.Path("paper/tables").mkdir(parents=True, exist_ok=True)
pathlib.Path("paper/tables/moments.tex").write_text("\n".join(lines) + "\n")
