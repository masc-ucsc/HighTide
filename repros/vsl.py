#!/usr/bin/env python3
"""Shared pieces for the HighTide asap7 OpenROAD-vs-LiveHD pre-CTS benchmark.

Layout of a measured workspace (WS):
  bin/            frozen openroad, yosys (+ timed yosys-abc), lhd, physical_repair
  <design>/       one directory per design; flow A (ORFS), B (LiveHD), C, D below
Every measured step runs through tools/vslivehd/measure.py (perf stat, GNU time,
sampled process-tree RSS limit) pinned to one CPU slot with taskset.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path

HT = Path("/home/renau/projs/HighTide")
LIVEHD = Path("/home/renau/projs/livehd")
BZ = Path("/home/renau/.cache/bazel/_bazel_renau/e89feab91b9c23a93bdaa11c75f4275f")
EXECROOT = BZ / "execroot/_main"
FASTBUILD = EXECROOT / "bazel-out/k8-fastbuild/bin"
EXEC_BIN = EXECROOT / "bazel-out/k8-opt-exec-ST-d57f47055a04/bin"
ORFS = BZ / "external/orfs+/flow"
PLATFORM = ORFS / "platforms/asap7"
TOOLS = HT / "tools/vslivehd"
WS = Path(os.environ.get("VSL_WS", "/tmp/vslivehd-llmhdl"))
BIN = WS / "bin"

# 32 logical CPUs = 16 cores x 2 SMT (cpu i and i+16 are siblings).  Each slot owns
# four physical cores (8 hardware threads); the last four cores stay free for the OS.
SLOTS = ["0-3,16-19", "4-7,20-23", "8-11,24-27"]
THREADS = 8
MEM_GIB = 64
TIMEOUT_S = float(os.environ.get("VSL_TIMEOUT_H", "6")) * 3600  # per measured OpenROAD/Yosys step
LHD_TIMEOUT_S = float(os.environ.get("VSL_LHD_TIMEOUT_H", "3")) * 3600  # per LiveHD invocation

sys.path.insert(0, str(TOOLS))
import lhdsweep as L  # noqa: E402
from measure import measure  # noqa: E402

L.HT, L.OB, L.EXEC = HT, BZ, EXECROOT
L.TOOLS, L.PLATFORM = TOOLS, PLATFORM
L.SWEEP = WS / "sweep"


def _resolve(path):
    p = Path(path)
    if p.is_absolute():
        return p
    for root in (EXECROOT, HT, BZ, FASTBUILD):
        if (root / p).exists():
            return (root / p).resolve()
    raise FileNotFoundError(path)


L.resolve = _resolve


RTL_FIXES = HT / "repros/rtl_fixes"
# LiveHD front end per design when design_config.json has none: snitch_cluster only compiles through yosys-slang
READER_OVERRIDE = {"snitch_cluster": "yosys"}


def _fixed_verilog_files(orig):
    """Design.verilog_files() with any file replaced by repros/rtl_fixes/<design>/<basename> when present."""
    def inner(self):
        out = []
        fixdir = RTL_FIXES / self.safe.split("__")[-1]
        for p in orig(self):
            f = fixdir / Path(p).name
            out.append(f if f.exists() else p)
        return out
    return inner


L.Design.verilog_files = _fixed_verilog_files(L.Design.verilog_files)


def discover() -> list:
    out = []
    for f in sorted(FASTBUILD.glob("designs/asap7/**/results/asap7/*/base/1_synth.args.json")):
        if ".runfiles" in str(f):
            continue
        key = str(f.relative_to(FASTBUILD / "designs/asap7")).split("/results/")[0]
        out.append(L.Design(key, f.parent))
    return out


def get(key: str):
    for d in discover():
        if d.key == key:
            return d
    raise SystemExit(f"unknown design {key}")


# ---------------------------------------------------------------- tool freeze
def freeze() -> None:
    """Copy every measured executable once so rebuilds cannot change a sweep."""
    if (BIN / "frozen.ok").exists():
        return
    BIN.mkdir(parents=True, exist_ok=True)
    shutil.copy2(EXEC_BIN / "external/openroad+/openroad", BIN / "openroad")
    ydir = BIN / "ys/bin"
    ydir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(EXEC_BIN / "external/yosys+/yosys", ydir / "yosys.bin")
    shutil.copy2(EXEC_BIN / "external/yosys+/yosys-abc", ydir / "yosys-abc.real")
    shutil.copytree(EXEC_BIN / "yosys_share_with_slang", BIN / "ys/share/yosys", dirs_exist_ok=True,
                    symlinks=False)
    # yosys locates yosys-abc next to its own executable; the wrapper times every ABC run.
    (ydir / "yosys-abc").write_text(
        "#!/bin/sh\n"
        f'exec /usr/bin/time -a -o "${{ABC_TIME_FILE:-/dev/null}}" -f "%e\\t%U\\t%S\\t%M" '
        f'{ydir}/yosys-abc.real "$@"\n')
    (BIN / "yosys").write_text(
        "#!/bin/sh\n"
        f"export YOSYS_PLUGIN_PATH={BIN}/ys/share/yosys/plugins\n"
        f'exec {ydir}/yosys.bin "$@"\n')
    for p in (ydir / "yosys-abc", BIN / "yosys"):
        p.chmod(p.stat().st_mode | stat.S_IXUSR)
    lhd = BIN / "lhd"
    lhd.mkdir(exist_ok=True)
    shutil.copy2(LIVEHD / "bazel-bin/lhd/lhd", lhd / "lhd")
    shutil.copytree(LIVEHD / "bazel-bin/lhd/lhd.runfiles", lhd / "lhd.runfiles", symlinks=True,
                    dirs_exist_ok=True)
    pr = BIN / "physical_repair_dir"
    pr.mkdir(exist_ok=True)
    shutil.copy2(LIVEHD / "bazel-bin/tools/physical_repair", pr / "physical_repair")
    shutil.copytree(LIVEHD / "bazel-bin/tools/physical_repair.runfiles", pr / "physical_repair.runfiles",
                    symlinks=True, dirs_exist_ok=True)
    manifest = {}
    for name, p in {"openroad": BIN / "openroad", "yosys": ydir / "yosys.bin", "lhd": lhd / "lhd",
                    "physical_repair": pr / "physical_repair"}.items():
        manifest[name] = L.sha(p)
    manifest["livehd_head"] = subprocess.check_output(
        ["git", "-C", str(LIVEHD), "rev-parse", "HEAD"], text=True).strip()
    manifest["hightide_head"] = subprocess.check_output(
        ["git", "-C", str(HT), "rev-parse", "HEAD"], text=True).strip()
    subprocess.run(["chmod", "-R", "u+w", str(BIN)], check=True)
    (BIN / "manifest.json").write_text(json.dumps(manifest, indent=2))
    (BIN / "frozen.ok").write_text("ok\n")


LHD = Path(os.environ.get("VSL_LHD", BIN / "lhd/lhd"))
LHD_THREADS = int(os.environ.get("VSL_LHD_THREADS", "1"))  # >1: ABC workers + OpenMP, pinned to the whole CPU slot
OPENROAD = BIN / "openroad"
PHYS_REPAIR = Path(os.environ.get("VSL_PHYS_REPAIR", BIN / "physical_repair_dir/physical_repair"))


# ------------------------------------------------------------------- measuring
def ipc(m: dict) -> float | None:
    p = m.get("perf", {})
    try:
        return p["instructions"]["value"] / p["cycles"]["value"]
    except (KeyError, ZeroDivisionError):
        return None


def run_measured(pinned: list, out: Path, cwd: Path, env: dict | None, timeout: float, mem_gib: float) -> dict:
    """measure() that survives a guard stop: GNU time writes nothing when it is killed."""
    t0 = time.monotonic()
    try:
        return measure(pinned, out, cwd=cwd, env=env, timeout_s=timeout, memory_gib=mem_gib)
    except IndexError:
        wall = time.monotonic() - t0
        reason = "wall-time limit" if wall >= timeout - 120 else "process-tree memory limit or kill"
        return {"status": "guard-stopped", "stop_reason": reason, "wall_s": wall, "command_wall_s": wall,
                "exit_code": None, "perf": {}, "max_process_rss_kb": 0, "tree_peak_rss_kb": 0}


def step(out: Path, argv: list, *, slot: int, cwd: Path, env: dict | None = None,
         timeout: float = TIMEOUT_S, mem_gib: float = MEM_GIB) -> dict:
    """One measured, CPU-pinned command.  Returns the measure.py record + ipc."""
    pinned = ["taskset", "-c", SLOTS[slot], *map(str, argv)]
    if out.exists():
        shutil.rmtree(out)
    rec = run_measured(pinned, out, cwd, env, timeout, mem_gib)
    rec["ipc"] = ipc(rec)
    (out / "measurement.json").write_text(json.dumps(rec, indent=2) + "\n")
    return rec


def summary(rec: dict) -> dict:
    """The fields the report needs from one measurement."""
    return {"status": rec["status"], "wall_s": rec.get("command_wall_s", rec["wall_s"]),
            "cpu_s": rec.get("cpu_s"), "rss_mib": (rec.get("max_process_rss_kb") or 0) / 1024,
            "tree_rss_mib": rec.get("tree_peak_rss_kb", 0) / 1024, "ipc": rec.get("ipc"),
            "instructions": rec.get("perf", {}).get("instructions", {}).get("value"),
            "cycles": rec.get("perf", {}).get("cycles", {}).get("value"),
            "stop": rec.get("stop_reason")}


# --------------------------------------------------------------- ORFS (flow A)
PATH_VARS = re.compile(r"^(VERILOG_FILES|VERILOG_INCLUDE_DIRS|SDC_FILE|ADDITIONAL_LEFS|ADDITIONAL_LIBS|"
                       r"ADDITIONAL_GDS|IO_CONSTRAINTS|FOOTPRINT_TCL|MACRO_PLACEMENT_TCL|PDN_TCL|"
                       r"SYNTH_SLANG_ARGS|.*_TCL|.*_FILE|.*_FILES|.*_DIRS)$")


def absolutize(value: str) -> str:
    out = []
    for tok in value.split():
        for prefix in ("-I", ""):
            body = tok[len(prefix):] if prefix and tok.startswith(prefix) else tok
            if prefix and not tok.startswith(prefix):
                continue
            if "/" in body and not body.startswith(("/", "$")):
                try:
                    tok = prefix + str(_resolve(body))
                except FileNotFoundError:
                    pass
            break
        out.append(tok)
    return " ".join(out)


def orfs_config(d, work: Path, extra: dict | None = None) -> Path:
    """ORFS config.mk with absolute inputs, equal to the variables of the bazel reference."""
    v = dict(d.vars)
    v["VERILOG_FILES"] = " ".join(map(str, d.verilog_files()))
    if "VERILOG_INCLUDE_DIRS" in v:
        v["VERILOG_INCLUDE_DIRS"] = " ".join(map(str, d.include_dirs()))
    lines = []
    for k, val in v.items():
        if k in ("WORK_HOME", "PLATFORM_DIR", "FLOW_HOME"):
            continue
        if PATH_VARS.match(k) and k not in ("VERILOG_FILES", "VERILOG_INCLUDE_DIRS"):
            val = absolutize(val)
        lines.append(f"export {k} = {val}")
    lines.append(f"export WORK_HOME = {work}")
    lines.append(f"export PLATFORM_DIR = {PLATFORM}")
    for k, val in (extra or {}).items():
        lines.append(f"export {k} = {val}")
    cfg = work / "config.mk"
    cfg.write_text("\n".join(lines) + "\n")
    return cfg


def orfs_env(work: Path) -> dict:
    return {"FLOW_HOME": str(ORFS), "MAKE_PATH": "make", "YOSYS_EXE": str(BIN / "yosys"),
            "OPENROAD_EXE": str(OPENROAD), "OPENSTA_EXE": str(OPENROAD),
            "KLAYOUT_CMD": "true", "STDBUF_CMD": "", "LEC_CHECK": "0",
            "QT_QPA_PLATFORM": "offscreen", "NUM_CORES": str(THREADS),
            "ABC_TIME_FILE": str(work / "abc_time.tsv")}


ORFS_STEPS = [
    ("yosys_read", "1_1_yosys_canonicalize.rtlil"),
    ("yosys_synth", "1_2_yosys.v"),
    ("netlist_import", "1_synth.odb"),
    ("floorplan", "2_1_floorplan.odb"),
    ("macro_place", "2_2_floorplan_macro.odb"),
    ("tapcell", "2_3_floorplan_tapcell.odb"),
    ("pdn", "2_4_floorplan_pdn.odb"),
    ("gp_skip_io", "3_1_place_gp_skip_io.odb"),
    ("io_place", "3_2_place_iop.odb"),
    ("global_place", "3_3_place_gp.odb"),
    ("resize", "3_4_place_resized.odb"),
    ("detail_place", "3_5_place_dp.odb"),
    ("place_done", "3_place.odb"),
]


def orfs_results(d, work: Path) -> Path:
    return work / "results/asap7" / d.name / "base"


def shrink(path: Path) -> None:
    """Empty a finished intermediate but keep its mtime so make still treats it as up to date."""
    try:
        st = path.stat()
        os.truncate(path, 0)
        os.utime(path, (st.st_atime, st.st_mtime))
    except OSError:
        pass


KEEP_ODB = ("3_2_place_iop.odb", "3_place.odb")  # flow C input, final score input


def run_orfs(d, work: Path, slot: int, *, steps=ORFS_STEPS, extra: dict | None = None,
             first: str | None = None) -> dict:
    """Run the HighTide ORFS flow step by step (RTL -> 3_place.odb), measuring each step."""
    work.mkdir(parents=True, exist_ok=True)
    cfg = orfs_config(d, work, extra)
    env = orfs_env(work)
    res = orfs_results(d, work)
    out = {}
    active = first is None
    for name, target in steps:
        if not active and name != first:
            continue
        active = True
        cmd = ["make", "--file", ORFS / "Makefile", f"DESIGN_CONFIG={cfg}", str(res / target)]
        rec = step(work / "measure" / name, cmd, slot=slot, cwd=work, env=env)
        out[name] = summary(rec)
        if rec["status"] == "ok":  # the disk quota is small: drop what no later step reads
            for _, prev in steps:
                if prev == target:
                    break
                if prev.endswith((".odb", ".rtlil")) and prev not in KEEP_ODB and (res / prev).exists():
                    shrink(res / prev)
            if target == "3_place.odb":
                shrink(res / "3_5_place_dp.odb")
        if rec["status"] == "ok" and not (res / target).exists():
            (res / target).touch()  # SYNTH_NETLIST_FILES exits before writing the canonical RTLIL
        if rec["status"] == "ok" and extra and "SYNTH_NETLIST_FILES" in extra and name == "yosys_synth":
            for f in ("1_2_yosys.v", "1_2_yosys.sdc"):  # `cp -p` kept the netlist's old mtime
                if (res / f).exists():
                    (res / f).touch()
        if rec["status"] != "ok":
            out[name]["log"] = str(work / "measure" / name / "run.log")
            break
    return out


# --------------------------------------------------------------------- scoring
def reset_ports(sdc: Path) -> list[str]:
    """Input ports that the SDC uses as false-path sources (the reset)."""
    text = sdc.read_text()
    ports = set()
    for m in re.finditer(r"set_false_path[^\n]*?-from\s+\[?get_ports\s+\{?\s*([^\]\}\n]+)", text):
        for tok in m.group(1).split():
            tok = tok.strip("{}\"")
            if tok and not tok.startswith("-"):
                ports.add(tok)
    return sorted(ports)


def lib_files(d, work: Path | None = None) -> list[Path]:
    """Liberty set the OpenROAD flow actually read (macro libraries included)."""
    if work is not None:
        seen = []
        log = work / "measure/yosys_read/run.log"
        for m in re.finditer(r"Executing Liberty frontend: (\S+)", log.read_text()):
            p = Path(m.group(1))
            p = p if p.is_absolute() else ORFS.parent.parent / p
            if p not in seen:
                seen.append(p)
        if seen:
            return seen
    return d.lib_files()


def score(d, source: Path, out: Path, slot: int, sdc: Path, libs: list, timeout=7200) -> dict:
    """OpenSTA scoring of an ODB/DEF; measured (wall/cpu) but not part of any flow total."""
    env = dict(LIB_FILES=" ".join(map(str, libs)), SCORE_INPUT=str(source), SCORE_OUT=str(out),
               SDC_FILE=str(sdc), SET_RC_TCL=str(PLATFORM / "setRC.tcl"),
               TECH_LEF=str(PLATFORM / "lef/asap7_tech_1x_201209.lef"),
               SC_LEF=str(PLATFORM / "lef/asap7sc7p5t_28_R_1x_220121a.lef"),
               ADDITIONAL_LEFS=" ".join(map(str, d.macro_lefs())),
               RESET_PORTS=" ".join(reset_ports(sdc)))
    out.mkdir(parents=True, exist_ok=True)
    rec = step(out.parent / (out.name + "_measure"), [OPENROAD, "-no_init", "-exit", "-threads", "4",
                                                      HT / "repros/score.tcl"], slot=slot, cwd=out, env=env)
    if rec["status"] != "ok" or not (out / "score.json").exists():
        raise RuntimeError(f"scoring failed: {out.parent / (out.name + '_measure') / 'run.log'}")
    res = json.loads((out / "score.json").read_text())
    pw = out / "power.rpt"
    if pw.exists():
        m = re.search(r"^Total\s+([0-9.eE+-]+)\s+([0-9.eE+-]+)\s+([0-9.eE+-]+)\s+([0-9.eE+-]+)", pw.read_text(), re.M)
        if m:
            res["power_mw"] = float(m.group(4))
    res["reset_ports"] = reset_ports(sdc)
    return res


# ------------------------------------------------------------- LiveHD (flow B)
def lhd_liberty(libs: list, out: Path) -> Path:
    """One merged standard-cell Liberty with the flow's dont_use applied (macro libs appended)."""
    if out.exists():
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    std = [p for p in libs if "asap7sc7p5t" in p.name]
    macro = [p for p in libs if "asap7sc7p5t" not in p.name]
    tmp = out.with_suffix(".tmp")
    cmd = [sys.executable, str(TOOLS / "merge_liberty.py")]
    for pat in L.DONT_USE:
        cmd += ["--dont-use", pat]
    cmd.append(str(tmp))
    cmd += map(str, std)
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL)
    with open(tmp, "a") as f:
        for p in macro:
            f.write("\n")
            f.write(Path(p).read_text())
    tmp.replace(out)
    return out


def lhd_sets(d, lib: Path, sdc: Path) -> tuple[dict, str]:
    util = d.utilization()
    sets = {
        "synth.liberty": str(lib), "synth.sdc": str(sdc),
        "synth.lef": ",".join(map(str, d.lef_list())),
        "synth.place": "true", "synth.place.density": "%g" % d.density(),
        "synth.place.tech_rc": str(PLATFORM / "setRC.tcl"), "synth.place.threads": str(LHD_THREADS),
        "pass.abc.threads": str(LHD_THREADS),
        "synth.memory": "flops", "pass.abc.drop_init": "true", "pass.abc.derived_clock": "true",
        "synth.place.unknown_const": "zero",
    }
    if util:
        sets["synth.place.utilization"] = "%g" % util
    cfg = json.loads((TOOLS / "design_config.json").read_text()).get(d.key, {}).get("sets", {})
    sets.update(cfg)
    reader = os.environ.get("VSL_LHD_READER") or sets.pop("reader", None) or READER_OVERRIDE.get(d.key, "native")
    sets.pop("reader", None)
    return sets, reader


def phase_breakdown(doc: dict) -> dict:
    """compile / synth (color+ABC) / placer / final STA, from the sequential `phases` list."""
    phases = doc.get("phases", [])
    first_color = next((i for i, p in enumerate(phases) if p["name"] == "pass.color"), len(phases))
    compile_ms = sum(p["ms"] for p in phases[:first_color])
    synth_ms = place_ms = sta_ms = 0.0
    after_abc = False
    for p in phases[first_color:]:
        n, ms = p["name"], p["ms"]
        if not after_abc:
            synth_ms += ms
            if n == "pass.abc":
                after_abc = True
        elif n == "pass.opentimer":
            sta_ms += ms
        elif n.startswith("pass.opentimer."):
            continue  # incremental/ranking calls are nested inside the placement phases
        elif n.startswith("pass.place"):
            place_ms += ms
        # anything else (inou.cgen.* netlist emission, lg.save, ...) is neither synthesis nor placement
    detail = {}
    for p in phases[first_color:]:
        if p["name"].startswith("pass.place") or p["name"] == "pass.opentimer.incremental":
            detail[p["name"]] = detail.get(p["name"], 0.0) + p["ms"]
    wall_ms = doc.get("synthesis_invocation", {}).get("wall_ms")
    return {"compile_s": compile_ms / 1e3, "synth_s": synth_ms / 1e3, "place_s": place_ms / 1e3,
            "sta_s": sta_ms / 1e3, "invocation_s": wall_ms / 1e3 if wall_ms else None,
            "place_detail_s": {k: v / 1e3 for k, v in detail.items()}}


def run_lhd(d, work: Path, slot: int, libs: list, sdc: Path, *, place: bool = True,
            util: float | None = None) -> dict:
    """flow B: `lhd synth` RTL -> mapped netlist + (place) legal DEF, one measured invocation."""
    work.mkdir(parents=True, exist_ok=True)
    lib = lhd_liberty(libs, WS / "lib" / f"{d.safe}.lib")
    sets, reader = lhd_sets(d, lib, sdc)
    sets["synth.place"] = "true" if place else "false"
    if util:
        sets["synth.place.utilization"] = "%.4f" % util
    slang = ["-D", "SYNTHESIS", "--compat=vcs", "--timescale=1ns/1ps"]
    if reader == "native":
        slang.insert(2, "--ignore-assertions")
    for inc in d.include_dirs():
        slang += ["-I", str(inc)]
    slang += d.defines()
    extra, _ = d.extra_slang()
    slang += extra
    sources = [str(p) for p in d.verilog_files()]
    env = {"OMP_NUM_THREADS": str(LHD_THREADS)}
    lhd_cpu = SLOTS[slot] if LHD_THREADS > 1 else SLOTS[slot].split(",")[0].split("-")[0]
    out: dict = {"compile_front_s": 0.0}
    wd = work / "w"
    if reader == "native":
        argv = [LHD, "synth", *sources, "--top", d.name]
        lg_in = None
    else:
        lg = work / "lg"
        pre = [LHD, "compile", *sources, "--reader", "yosys-slang", "--top", d.name,
               "--workdir", work / "w_compile", "--emit-dir", f"lg:{lg}/"]
        mlibs = [p for p in libs if "asap7sc7p5t" not in p.name]
        if mlibs:
            pre += ["--set", "compile.yosys.macrolib=" + ",".join(map(str, mlibs))]
        pre += ["--", *slang]
        rec = step_cpu(work / "measure_front", pre, lhd_cpu, work, env)
        out["frontend"] = summary(rec)
        out["compile_front_s"] = out["frontend"]["wall_s"]
        if rec["status"] != "ok":
            out["status"] = "failed"
            out["log"] = str(work / "measure_front/run.log")
            return out
        argv = [LHD, "synth", f"lg:{lg}", "--top", d.name]
    argv += ["--workdir", wd, "--emit", f"verilog:{work / 'netlist.v'}",
             "--emit-dir", f"report:{work / 'rep'}/", "--stats", "--result-json", work / "result.json"]
    if place:
        argv += ["--emit-dir", f"def:{work / 'def'}/"]
    for k, v in sets.items():
        argv += ["--set", f"{k}={v}"]
    if reader == "native":
        argv += ["--", *slang]
    rec = step_cpu(work / "measure", argv, lhd_cpu, work, env)
    out["run"] = summary(rec)
    out["status"] = rec["status"]
    doc = work / "result.json"
    if doc.exists():
        out["phases"] = phase_breakdown(json.loads(doc.read_text()))
        out["phases"]["compile_s"] += out["compile_front_s"]
    if rec["status"] != "ok":
        out["log"] = str(work / "measure/run.log")
        if doc.exists():
            out["message"] = json.loads(doc.read_text()).get("error", {}).get("message")
        out["message"] = out.get("message") or rec.get("stop_reason") or last_line(work / "measure/run.log")
    return out


def last_line(path: Path) -> str:
    try:
        lines = [l for l in path.read_text(errors="replace").splitlines() if l.strip() and "rebase spef" not in l]
        return lines[-1][:300] if lines else ""
    except OSError:
        return ""


def step_cpu(out: Path, argv: list, cpus: str, cwd: Path, env: dict | None = None,
             timeout: float = LHD_TIMEOUT_S) -> dict:
    """Like step() but pinned to explicit CPUs (LiveHD is single-threaded: one hardware thread)."""
    if out.exists():
        shutil.rmtree(out)
    rec = run_measured(["taskset", "-c", cpus, *map(str, argv)], out, cwd, env, timeout, MEM_GIB)
    rec["ipc"] = ipc(rec)
    (out / "measurement.json").write_text(json.dumps(rec, indent=2) + "\n")
    return rec


# --------------------------------------------- Yosys netlist -> LiveHD placer (C)
C_POLICY = dict(source_def=True, cell_place=True, timing_driven=True, iterations=1500,
                timing_rounds=3, min_iterations=500, density_upper_bound=True,
                fixed_macro_overlap_weight=5.0, halo=0, post_density_factor=4)


def make_input_def(d, wA: Path, wC: Path) -> Path:
    """OpenROAD floorplan/macros/IO of the reference run with the standard-cell positions removed.

    Skipped when wC/input.def already exists (e.g. restored from repros/data), so LiveHD can be
    re-evaluated without re-running OpenROAD."""
    wC.mkdir(parents=True, exist_ok=True)
    out = wC / "input.def"
    if out.exists() and out.stat().st_size:
        return out
    src = orfs_results(d, wA) / "3_2_place_iop.odb"
    prep = wC / "prep.tcl"
    prep.write_text(
        f"read_db {src}\n"
        "foreach inst [[ord::get_db_block] getInsts] {\n"
        "  if {![[$inst getMaster] isBlock] && [$inst getPlacementStatus] ne \"FIRM\" "
        "&& [$inst getPlacementStatus] ne \"LOCKED\"} {\n"
        "    if {![[$inst getMaster] isFiller] && [[$inst getMaster] getType] ne \"CORE_WELLTAP\"} "
        "{$inst setPlacementStatus NONE}\n  }\n}\n"
        f"write_def {out}\n")
    subprocess.run([OPENROAD, "-no_init", "-exit", str(prep)], check=True, stdout=subprocess.DEVNULL,
                   stderr=subprocess.STDOUT, cwd=wC)
    return out


def run_c(d, wA: Path, wC: Path, slot: int, libs: list, sdc: Path) -> dict:
    """Same Yosys+ABC netlist, same floorplan/macros/IO as the OpenROAD run (3_2_place_iop),
    cell positions recomputed by LiveHD's native placer, then LiveHD's pre-CTS repair."""
    wC.mkdir(parents=True, exist_ok=True)
    make_input_def(d, wA, wC)
    lib = lhd_liberty(libs, WS / "lib" / f"{d.safe}.lib")
    lefs = [str(PLATFORM / "lef/asap7_tech_1x_201209.lef"), str(PLATFORM / "lef/asap7sc7p5t_28_R_1x_220121a.lef"),
            *map(str, d.macro_lefs())]
    cfg = dict(C_POLICY, top=d.name, **{"def": str(wC / "input.def")}, liberty=str(lib), sdc=str(sdc),
               tech_rc=str(PLATFORM / "setRC.tcl"), lefs=lefs, density=d.density(), threads=1,
               output=str(wC / "livehd_place"))
    (wC / "place.json").write_text(json.dumps(cfg, indent=2))
    rep = {k: v for k, v in cfg.items() if k != "cell_place"}
    rep["def"] = str(wC / "livehd_place/out.def")
    rep["output"] = str(wC / "livehd_repair")
    (wC / "repair.json").write_text(json.dumps(rep, indent=2))
    env = {"OMP_NUM_THREADS": "1",
           "RUNFILES_DIR": str(PHYS_REPAIR.parent / "physical_repair.runfiles")}
    cpu = SLOTS[slot].split(",")[0].split("-")[0]
    out = {}
    r1 = step_cpu(wC / "measure_place", [PHYS_REPAIR, wC / "place.json"], cpu, wC, env)
    out["place"] = summary(r1)
    if r1["status"] != "ok":
        out["log"] = str(wC / "measure_place/run.log")
        out["message"] = r1.get("stop_reason") or last_line(wC / "measure_place/run.log")
        return out
    r2 = step_cpu(wC / "measure_repair", [PHYS_REPAIR, wC / "repair.json"], cpu, wC, env)
    out["repair"] = summary(r2)
    if r2["status"] != "ok":
        out["log"] = str(wC / "measure_repair/run.log")
        out["message"] = r2.get("stop_reason") or last_line(wC / "measure_repair/run.log")
    return out


def structural(d, work: Path, lib: Path, macro_libs: list | None = None) -> Path:
    """LiveHD's Verilog declares nets as `reg`; elaborate wiring only (cells kept) so OpenSTA reads it."""
    out = work / "netlist_struct.v"
    script = work / "structural.ys"
    script.write_text(
        f"read_liberty -lib {lib}\n"
        + "".join(f"read_liberty -lib {m}\n" for m in (macro_libs or []))
        +
        f"read_verilog -sv -noblackbox {work / 'netlist.v'}\n"
        f"hierarchy -check -top {d.name}\nproc\nflatten\nsplitnets -ports\n"
        f"write_verilog -noattr -noexpr {out}\n")
    subprocess.run([BIN / "yosys", "-q", "-s", str(script)], check=True, cwd=work,
                   stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    return out
