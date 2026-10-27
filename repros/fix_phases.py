#!/usr/bin/env python3
"""Recompute the stored compile/synth/placer split of every archived LiveHD run from its raw result.json
(use after changing vsl.phase_breakdown): data/<design>/{result.json,result_livehd_old.json} <- livehd*/{S,B}/result.json(.gz)."""
import gzip, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import vsl

def raw(p: Path):
    if p.exists():
        return json.loads(p.read_text())
    g = Path(str(p) + ".gz")
    return json.loads(gzip.open(g).read()) if g.exists() else None

for d in sorted((Path(__file__).resolve().parent / "data").iterdir()):
    for res_name, live in (("result.json", "livehd"), ("result_livehd_old.json", "livehd_old")):
        f = d / res_name
        if not f.exists():
            continue
        r = json.loads(f.read_text()); ch = False
        for tag in "SB":
            doc = raw(d / live / tag / "result.json")
            blk = r.get(tag)
            if doc and blk and blk.get("phases"):
                front = blk.get("compile_front_s", 0.0)
                ph = vsl.phase_breakdown(doc); ph["compile_s"] += front
                blk["phases"] = ph; ch = True
        if ch:
            f.write_text(json.dumps(r, indent=1)); print("updated", d.name, res_name)
