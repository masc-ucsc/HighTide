#!/usr/bin/env python3
"""`lhd compile` only (the equivalent of Yosys read) on every HighTide asap7 design.

  compile_check.py [--only a,b] [--readers native,tuned,yosys]

native : LiveHD's own slang reader, same slang flags as the benchmark, no per-design compile options
tuned  : native reader + the per-design `compile.*` options of tools/vslivehd/design_config.json
yosys  : yosys-slang front end (`--reader yosys-slang`) feeding LiveHD
Results: <WS>/compile_check/<design>/<reader>/ and data/compile_check.json
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import vsl  # noqa: E402

OUT = vsl.HT / "repros/data/compile_check.json"
TIMEOUT = 1800


def slang_args(d, native: bool) -> list[str]:
    a = ["-D", "SYNTHESIS", "--compat=vcs", "--timescale=1ns/1ps"]
    if native:
        a.insert(2, "--ignore-assertions")
    for inc in d.include_dirs():
        a += ["-I", str(inc)]
    a += d.defines()
    extra, _ = d.extra_slang()
    return a + extra


def first_errors(log: Path, n: int = 3) -> list[str]:
    out = []
    try:
        for line in log.read_text(errors="replace").splitlines():
            if '"severity":"error"' in line:
                try:
                    j = json.loads(line)
                    out.append(f"{j.get('code')}: {j.get('message')}"[:260])
                except json.JSONDecodeError:
                    out.append(line[:260])
                if len(out) >= n:
                    break
    except OSError:
        pass
    return out


def count_errors(log: Path) -> int:
    try:
        return sum(1 for l in log.read_text(errors="replace").splitlines() if '"severity":"error"' in l)
    except OSError:
        return -1


def run_one(d, reader: str, slot: int) -> dict:
    work = vsl.WS / "compile_check" / d.safe / reader
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    sources = [str(p) for p in d.verilog_files()]
    cfg = json.loads((vsl.TOOLS / "design_config.json").read_text()).get(d.key, {}).get("sets", {})
    compile_sets = {k: v for k, v in cfg.items() if k.startswith("compile.")}
    yosys_cfg = cfg.get("reader") == "yosys"
    argv = [vsl.LHD, "compile", *sources, "--top", d.name, "--workdir", work / "w",
            "--emit-dir", f"lg:{work / 'lg'}/", "--result-json", work / "result.json"]
    if reader == "yosys":
        argv += ["--reader", "yosys-slang"]
        mlibs = [p for p in d.lib_files() if "asap7sc7p5t" not in p.name]
        if mlibs:
            argv += ["--set", "compile.yosys.macrolib=" + ",".join(map(str, mlibs))]
        args = slang_args(d, native=False)
    else:
        libs = [Path(p) for p in (vsl.HT / "repros/data" / d.safe / "libs.txt").read_text().split()]
        lib = vsl.lhd_liberty(libs, vsl.WS / "lib" / f"{d.safe}.lib")
        argv += ["--set", f"synth.liberty={lib}"]  # `lhd synth` hands the same Liberty to its compile step (macro cells)
        if reader == "tuned":
            for k, v in compile_sets.items():
                argv += ["--set", f"{k}={v}"]
        args = slang_args(d, native=True)
    argv += ["--", *args]
    cpu = vsl.SLOTS[slot]
    rec = vsl.step_cpu(work / "measure", argv, cpu, work, {"OMP_NUM_THREADS": "1"}, timeout=TIMEOUT)
    log = work / "measure/run.log"
    res = {"status": rec["status"], "wall_s": rec.get("command_wall_s", rec["wall_s"]), "cpu_s": rec.get("cpu_s"),
           "rss_mib": (rec.get("max_process_rss_kb") or 0) / 1024, "stop": rec.get("stop_reason"),
           "errors": count_errors(log), "first_errors": first_errors(log),
           "compile_options": compile_sets if reader == "tuned" else {},
           "design_config_uses_yosys_reader": yosys_cfg, "sources": len(sources)}
    doc = work / "result.json"
    if doc.exists():
        try:
            j = json.loads(doc.read_text())
            res["message"] = (j.get("error") or {}).get("message")
            res["lhd_status"] = j.get("status")
        except json.JSONDecodeError:
            pass
    if rec["status"] != "ok" and not res.get("message"):
        res["message"] = vsl.last_line(log)
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    ap.add_argument("--readers", default="native,tuned,yosys")
    ap.add_argument("--slots", default="1,2")
    a = ap.parse_args()
    vsl.freeze()
    designs = vsl.discover()
    if a.only:
        keep = set(a.only.split(","))
        designs = [d for d in designs if d.key in keep or d.safe in keep]
    data = json.loads(OUT.read_text()) if OUT.exists() else {}
    slots = [int(s) for s in a.slots.split(",")]
    import queue
    import threading
    q: queue.Queue = queue.Queue()
    for d in designs:
        q.put(d)
    lock = threading.Lock()

    def worker(slot: int) -> None:
        while True:
            try:
                d = q.get_nowait()
            except queue.Empty:
                return
            row = {}
            for reader in a.readers.split(","):
                row[reader] = run_one(d, reader, slot)
                print(f"{d.key:24s} {reader:7s} {row[reader]['status']:8s} {row[reader]['wall_s']:7.1f}s "
                      f"{(row[reader].get('message') or '')[:90]}", flush=True)
            with lock:
                data.setdefault(d.key, {}).update(row)
                OUT.write_text(json.dumps(data, indent=1))

    ts = [threading.Thread(target=worker, args=(s,)) for s in slots]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
