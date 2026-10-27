#!/usr/bin/env python3
"""Keep everything LiveHD needs to re-run its side of the benchmark without re-running OpenROAD.

  archive.py DESIGN [DESIGN...]      copy WS/<design> -> HighTide/repros/data/<design>/   (run_design.py does this itself)

Per design (data/<design>/):
  result.json            all flows' measurements and scores (A = OpenROAD reference)
  config.mk, abc_time.tsv   ORFS configuration (absolute paths) and ABC timing of the reference run
  constraint.sdc, libs.txt  the SDC and the exact Liberty files the OpenROAD flow read
  1_2_yosys.v.gz         Yosys+ABC netlist of the reference
  input.def.gz           OpenROAD floorplan/macros/IO with standard-cell positions removed (flow C input)
  3_place.odb.gz         reference placement, only when small
  A_score/               OpenSTA scoring reports of the reference
  A_logs.tar.gz          ORFS logs and per-step measurement records (time, perf, run.log)
  sources.tar.gz         RTL, include dirs, macro LEF/LIB (tar -P: absolute paths) + file list
  livehd/                LiveHD artefacts present so far (netlist, reports, commands, result.json)
"""
from __future__ import annotations

import gzip
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import vsl  # noqa: E402

DATA = vsl.HT / "repros/data"
SMALL_ODB_MB = 40  # keep 3_place.odb.gz only if the compressed file is smaller than this


def gz(src: Path, dst: Path) -> None:
    with open(src, "rb") as i, gzip.open(dst, "wb", compresslevel=3) as o:
        shutil.copyfileobj(i, o, 1 << 20)


def tar(dst: Path, members: list[Path]) -> None:
    members = [m for m in members if m.exists()]
    lst = dst.with_suffix(".list")
    lst.write_text("\n".join(map(str, members)) + "\n")
    subprocess.run(["tar", "-czPf", str(dst), "-T", str(lst)], check=True)


def source_files(d) -> list[Path]:
    out = list(d.verilog_files()) + list(d.include_dirs()) + list(d.macro_lefs())
    out += [p for p in vsl.lib_files(d) if "asap7sc7p5t" not in p.name]
    for key, val in d.vars.items():
        if key.endswith("_TCL") or key in ("IO_CONSTRAINTS", "SDC_FILE"):
            for tok in val.split():
                try:
                    out.append(vsl._resolve(tok))
                except FileNotFoundError:
                    pass
    seen, uniq = set(), []
    for p in out:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    return uniq


def archive(d, res: dict | None = None) -> Path:
    root = vsl.WS / d.safe
    dst = DATA / d.safe
    dst.mkdir(parents=True, exist_ok=True)
    wA, wB, wC, wD, wS = (root / n for n in "ABCDS")
    if (root / "result.json").exists():
        shutil.copy2(root / "result.json", dst / "result.json")
    have_a = wA.exists()  # a LiveHD-only (--restore) run has no OpenROAD workspace: keep the stored reference
    for f, name in ((wA / "config.mk", "config.mk"), (wA / "abc_time.tsv", "abc_time.tsv")):
        if f.exists():
            shutil.copy2(f, dst / name)
    sdc = vsl._resolve(d.vars["SDC_FILE"])
    shutil.copy2(sdc, dst / "constraint.sdc")
    r = json.loads((root / "result.json").read_text()) if (root / "result.json").exists() else {}
    if r.get("libs"):
        (dst / "libs.txt").write_text("\n".join(r["libs"]) + "\n")
    res_dir = vsl.orfs_results(d, wA)
    v = res_dir / "1_2_yosys.v"
    if v.exists() and v.stat().st_size:
        gz(v, dst / "1_2_yosys.v.gz")
    # flow C input: from the retained 3_2 database when still there, else the DEF already produced
    if have_a and r.get("A", {}).get("score"):
        try:
            inp = vsl.make_input_def(d, wA, wC)
            if inp.exists() and inp.stat().st_size:
                gz(inp, dst / "input.def.gz")
        except (subprocess.CalledProcessError, OSError) as exc:
            (dst / "input.def.MISSING").write_text(f"{exc}\n")
    odb = res_dir / "3_place.odb"
    if have_a and odb.exists() and odb.stat().st_size:
        tmp = dst / "3_place.odb.gz"
        gz(odb, tmp)
        if tmp.stat().st_size > SMALL_ODB_MB * 2**20:
            tmp.unlink()
    if have_a and (wA / "score").exists():
        shutil.copytree(wA / "score", dst / "A_score", dirs_exist_ok=True)
    logs = [p for p in (wA / "logs", wA / "reports", wA / "measure") if p.exists()]
    if have_a and logs:
        tar(dst / "A_logs.tar.gz", logs)
    try:
        if not (dst / "sources.tar.gz").exists():
            tar(dst / "sources.tar.gz", source_files(d))
    except Exception as exc:  # sources are a convenience copy; never fail the archive on them
        (dst / "sources.MISSING").write_text(f"{exc}\n")
    # LiveHD side so far
    live = dst / "livehd"
    for tag, w in (("S", wS), ("B", wB), ("C", wC), ("D", wD)):
        if not w.exists():
            continue
        t = live / tag
        t.mkdir(parents=True, exist_ok=True)
        for name in ("netlist.v", "netlist_struct.v", "result.json", "place.json", "repair.json", "prep.tcl",
                     "structural.ys"):
            f = w / name
            if f.exists():
                if f.stat().st_size > 1 << 20:
                    gz(f, t / (name + ".gz"))
                else:
                    shutil.copy2(f, t / name)
        for sub in ("rep", "score", "score_place", "score_repair"):
            if (w / sub).exists():
                shutil.copytree(w / sub, t / sub, dirs_exist_ok=True)
        for m in sorted(w.glob("measure*")):
            if m.is_dir():
                shutil.copytree(m, t / m.name, dirs_exist_ok=True,
                                ignore=shutil.ignore_patterns("perf.csv.tmp"))
        for sub in ("def", "livehd_place", "livehd_repair"):
            f = w / sub / "out.def"
            if f.exists():
                (t / sub).mkdir(exist_ok=True)
                gz(f, t / sub / "out.def.gz")
    man = {"design": d.key, "top": d.name, "tools": json.loads((vsl.BIN / "manifest.json").read_text())
           if (vsl.BIN / "manifest.json").exists() else {},
           "files": sorted(str(p.relative_to(dst)) for p in dst.rglob("*") if p.is_file())}
    (dst / "manifest.json").write_text(json.dumps(man, indent=1))
    return dst


if __name__ == "__main__":
    for key in sys.argv[1:]:
        d = vsl.get(key)
        out = archive(d)
        size = sum(p.stat().st_size for p in out.rglob("*") if p.is_file()) / 1e6
        print(f"{key}: {out} {size:.0f} MB")
