#!/usr/bin/env python3
"""Regenerate repros/rtl_fixes/ (the fixed RTL both flows read for eyeriss and snitch_cluster).

eyeriss:        pristine upstream + the repository's two patches (patches/eyeriss-*.patch) + designs/src/eyeriss/dev/generate_rtl.py
snitch_cluster: pristine snitch.sv + patches/snitch-cluster-fp-inst-comb-loop.patch

The files are not committed (generated, ~1.4 MB); run this once per checkout. Needs the bazel external repos
(`@eyeriss_src`, `@snitch_cluster_src`) fetched, i.e. a prior `bazel build` of the designs.
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import vsl  # noqa: E402

EXT = vsl.BZ / "external"
HT = vsl.HT
OUT = vsl.RTL_FIXES


def eyeriss() -> None:
    src = EXT / "+_repo_rules+eyeriss_src"
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        shutil.copytree(src / "FPGA_design", t / "FPGA_design")
        subprocess.run(["chmod", "-R", "u+w", str(t)], check=True)
        for p in ("eyeriss-shape-compiler-synthesis", "eyeriss-psum-router-width"):
            subprocess.run(["patch", "-p1", "--no-backup-if-mismatch", "-i", str(HT / f"patches/{p}.patch")],
                           cwd=t, check=True, stdout=subprocess.DEVNULL)
        skip = ("FPGA_design/src/UART/", "FPGA_design/src/display/", "FPGA_design/src/IO_processing/")
        drop = ("TOP_integration.v", "TOP_integration_rom.v", "TOP_integration_uart.v", "TOP_interface.v",
                "CSC_encoderr_FIFO.v")
        files = sorted(str(p) for p in (t / "FPGA_design/src").rglob("*.v")
                       if not str(p.relative_to(t)).startswith(skip) and p.name not in drop)
        (OUT / "eyeriss").mkdir(parents=True, exist_ok=True)
        subprocess.run([sys.executable, str(HT / "designs/src/eyeriss/dev/generate_rtl.py"),
                        "--cfg", str(HT / "designs/src/eyeriss/dev/generated/fakeram_asap7.cfg"),
                        "--template", str(HT / "designs/src/eyeriss/dev/macros_template.v"),
                        "--out", str(OUT / "eyeriss/eyeriss.v"), *files], check=True)


def snitch() -> None:
    src = EXT / "+_repo_rules+snitch_cluster_src/hw/snitch/src/snitch.sv"
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        (t / "hw/snitch/src").mkdir(parents=True)
        shutil.copy(src, t / "hw/snitch/src/snitch.sv")
        subprocess.run(["patch", "-p1", "--no-backup-if-mismatch", "-i",
                        str(HT / "patches/snitch-cluster-fp-inst-comb-loop.patch")],
                       cwd=t, check=True, stdout=subprocess.DEVNULL)
        (OUT / "snitch_cluster").mkdir(parents=True, exist_ok=True)
        shutil.copy(t / "hw/snitch/src/snitch.sv", OUT / "snitch_cluster/snitch.sv")


if __name__ == "__main__":
    eyeriss()
    snitch()
    print("wrote", OUT)
