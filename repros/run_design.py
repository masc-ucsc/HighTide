#!/usr/bin/env python3
"""Run the four pre-CTS flows for one HighTide asap7 design in one CPU slot.

  A  Yosys+ABC -> OpenROAD (floorplan, global place, resize, detail place)   [HighTide reference]
  B  LiveHD     (compile, synth = color+ABC, native placer + repair)
  D  LiveHD netlist -> OpenROAD floorplan/place     (isolates the synthesis step)
  C  Yosys+ABC netlist -> LiveHD placer on OpenROAD's floorplan/IO (isolates the placer)

Results land in WS/<design>/result.json; every flow is scored by the same OpenSTA script.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import vsl  # noqa: E402

PRUNE_KEEP_MB = 150


def tool_times(work: Path) -> dict:
    """In-tool elapsed/CPU (ORFS epilogue) per measured step, excluding make/startup."""
    out = {}
    for log in sorted((work / "measure").glob("*/run.log")):
        t = log.read_text(errors="replace")
        m = re.findall(r"Elapsed time: (\d+):(\d+)\.(\d+)\[h:\]min:sec\. CPU time: user ([\d.]+) sys ([\d.]+)", t)
        if m:
            h, s, f, u, sy = m[-1]
            out[log.parent.name] = {"elapsed_s": int(h) * 60 + int(s) + float("0." + f),
                                    "cpu_s": float(u) + float(sy)}
    return out


def abc_times(work: Path) -> dict:
    f = work / "abc_time.tsv"
    wall = user = sys_ = 0.0
    runs = 0
    if f.exists():
        for line in f.read_text().splitlines():
            parts = line.split("\t")
            if len(parts) == 4:
                wall += float(parts[0]); user += float(parts[1]); sys_ += float(parts[2]); runs += 1
    return {"wall_s": wall, "cpu_s": user + sys_, "runs": runs}


def yosys_pass_times(work: Path) -> dict:
    """Yosys's own `Time spent` line (top passes) from the synthesis log, for the record."""
    log = work / "measure/yosys_synth/run.log"
    if not log.exists():
        return {}
    m = re.findall(r"Time spent: (.*)", log.read_text(errors="replace"))
    return {"time_spent": m[-1] if m else None}


def prune(work: Path) -> None:
    """Keep logs/measurements/scores; drop bulky intermediates (keep finals when small)."""
    for sub in ("results", "objects"):
        for p in (work / sub).rglob("*"):
            if p.is_file() and p.name not in ("3_place.odb",) and p.suffix in (".odb", ".rtlil", ".def", ".gz"):
                p.unlink()
    final = next((work / "results").rglob("3_place.odb"), None)
    if final and final.stat().st_size > PRUNE_KEEP_MB * 2**20:
        final.unlink()
    for name in ("w", "w_compile", "lg"):
        shutil.rmtree(work / name, ignore_errors=True)


def save(path: Path, res: dict) -> None:
    path.write_text(json.dumps(res, indent=1, default=str))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("design")
    ap.add_argument("--slot", type=int, default=0)
    ap.add_argument("--flows", default="ASBDC")
    ap.add_argument("--restore", action="store_true",
                    help="start from repros/data/<design> (reference results, input DEF) instead of re-running OpenROAD")
    ap.add_argument("--redo", default="", help="with --restore: flows whose stored LiveHD result is discarded and re-run")
    a = ap.parse_args()
    vsl.freeze()
    d = vsl.get(a.design)
    root = vsl.WS / d.safe
    root.mkdir(parents=True, exist_ok=True)
    rj = root / "result.json"
    res = json.loads(rj.read_text()) if rj.exists() else {}
    if a.restore:
        import archive
        src = archive.DATA / d.safe
        stored = json.loads((src / "result.json").read_text())
        for k in ("A", "libs", "util_from_core"):
            if k in stored:
                res[k] = stored[k]
        for k in a.redo:
            res.pop(k, None)
        for k in "SBDC":  # keep stored LiveHD results unless asked to redo them
            if k in stored and k not in res and k not in a.redo:
                res[k] = stored[k]
        (root / "C").mkdir(exist_ok=True)
        if (src / "input.def.gz").exists() and not (root / "C/input.def").exists():
            import gzip
            with gzip.open(src / "input.def.gz", "rb") as i, open(root / "C/input.def", "wb") as o:
                shutil.copyfileobj(i, o, 1 << 20)
    res.update(design=d.key, top=d.name, slot=a.slot, utilization=d.utilization(), density=d.density())
    sdc = vsl._resolve(d.vars["SDC_FILE"])
    res["sdc"] = str(sdc)
    wA, wB, wC, wD, wS = (root / n for n in "ABCDS")

    def stage(tag, fn):
        if res.get(tag, {}).get("done"):
            return
        t0 = time.time()
        try:
            res[tag] = fn()
            res[tag]["done"] = True
        except Exception as exc:  # keep going: a failed flow is a result
            res[tag] = {"error": f"{type(exc).__name__}: {exc}", "trace": traceback.format_exc()[-1500:], "done": True}
        res[tag]["driver_s"] = time.time() - t0
        save(rj, res)

    libs = [Path(p) for p in res["libs"]] if res.get("libs") else None

    def get_libs():
        nonlocal libs
        if libs is None:
            libs = vsl.lib_files(d, wA)
            res["libs"] = [str(p) for p in libs]
        return libs

    # ---- A: OpenROAD reference
    if "A" in a.flows:
        def flow_a():
            steps = vsl.run_orfs(d, wA, a.slot)
            out = {"steps": steps, "tool": tool_times(wA), "abc": abc_times(wA), "yosys": yosys_pass_times(wA)}
            bad = [k for k, v in steps.items() if v["status"] != "ok"]
            if bad:
                out["error"] = f"step {bad[0]} {steps[bad[0]]['status']}: {steps[bad[0]].get('log')}"
                return out
            out["score"] = vsl.score(d, vsl.orfs_results(d, wA) / "3_place.odb", wA / "score", a.slot, sdc,
                                     get_libs())
            return out
        stage("A", flow_a)

    # ---- S: LiveHD synthesis only (no placement): the netlist for flow D and the synthesis timing
    if "S" in a.flows:
        def flow_s():
            util = res.get("util_from_core") or None
            if util is None and d.utilization() is None:
                sa = res.get("A", {}).get("score")
                if sa:
                    core = sa["core_um"]
                    util = min(max(sa["instance_area_um2"] / ((core[2] - core[0]) * (core[3] - core[1])), 0.2), 0.85)
            out = vsl.run_lhd(d, wS, a.slot, get_libs(), sdc, place=False, util=util)
            if out.get("status") != "ok":
                out["error"] = f"lhd synth {out.get('status')}: {out.get('message')}"
            return out
        stage("S", flow_s)

    # ---- B: LiveHD full flow
    if "B" in a.flows:
        def flow_b():
            util = None
            if d.utilization() is None:  # explicit DIE/CORE_AREA: match the OpenROAD core
                sa = res.get("A", {}).get("score")
                if sa:
                    core = sa["core_um"]
                    util = min(max(sa["instance_area_um2"] / ((core[2] - core[0]) * (core[3] - core[1])), 0.2), 0.85)
                    res["util_from_core"] = util
            out = vsl.run_lhd(d, wB, a.slot, get_libs(), sdc, util=util)
            if out.get("status") != "ok":
                out["error"] = f"lhd {out.get('status')}: {out.get('message')}"
                return out
            defs = sorted((wB / "def").glob("*.def"))
            if not defs:
                out["error"] = "no DEF produced"
                return out
            sd = vsl.L.adapt_sdc(sdc, wB / "score_pins.sdc")
            out["score"] = vsl.score(d, defs[0], wB / "score", a.slot, sd, get_libs())
            return out
        stage("B", flow_b)

    # ---- D: LiveHD netlist through the OpenROAD floorplan/placer
    if "D" in a.flows and res.get("S", {}).get("status") == "ok":
        def flow_d():
            netlist = vsl.structural(d, wS, vsl.WS / "lib" / f"{d.safe}.lib",
                                     [p for p in get_libs() if "asap7sc7p5t" not in p.name])
            steps = vsl.run_orfs(d, wD, a.slot, extra={"SYNTH_NETLIST_FILES": str(netlist)})
            out = {"steps": steps, "tool": tool_times(wD)}
            bad = [k for k, v in steps.items() if v["status"] != "ok"]
            if bad:
                out["error"] = f"step {bad[0]} {steps[bad[0]]['status']}: {steps[bad[0]].get('log')}"
                return out
            out["score"] = vsl.score(d, vsl.orfs_results(d, wD) / "3_place.odb", wD / "score", a.slot, sdc, get_libs())
            return out
        stage("D", flow_d)

    # ---- C: Yosys netlist through LiveHD's placer on OpenROAD's floorplan
    if "C" in a.flows and res.get("A", {}).get("score"):
        def flow_c():
            if "wall-time" in str(res.get("B", {}).get("run", {}).get("stop")):
                return {"error": "skipped: LiveHD placer already hit the wall-time limit in flow B"}
            out = vsl.run_c(d, wA, wC, a.slot, get_libs(), sdc)
            if "error" in out or out.get("log"):
                out["error"] = f"physical_repair failed: {out.get('message')}"
                return out
            out["score_place"] = vsl.score(d, wC / "livehd_place/out.def", wC / "score_place", a.slot, sdc, get_libs())
            out["score"] = vsl.score(d, wC / "livehd_repair/out.def", wC / "score_repair", a.slot, sdc, get_libs())
            return out
        stage("C", flow_c)

    save(rj, res)
    try:
        import archive
        archive.archive(d)
    except Exception:  # an archive problem must not lose the run
        traceback.print_exc()
    for w in (wA, wB, wC, wD, wS):
        if w.exists():
            prune(w)
    print(a.design, {k: ("ok" if res.get(k, {}).get("score") else res.get(k, {}).get("error", "-"))
                     for k in "ASBDC"}, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
