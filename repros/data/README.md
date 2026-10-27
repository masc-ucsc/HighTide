# Archived OpenROAD results and LiveHD restart kit

`data/<design>/` keeps what is needed to re-run **LiveHD's side** of the HighTide asap7 pre-CTS benchmark
without re-running the OpenROAD reference. Written by `archive.py` (called automatically at the end of
`run_design.py`; `python3 archive.py <design>` archives by hand). Sizes are small (compressed), but do not `git add`
this directory blindly.

| file | content |
|---|---|
| `result.json` | all measurements and scores so far: `A` = OpenROAD reference (per-step wall/CPU/IPC/RSS, ABC time, OpenSTA score), `S/B/C/D` = LiveHD flows |
| `config.mk`, `abc_time.tsv` | ORFS configuration of the reference run (absolute paths) and its ABC timing |
| `constraint.sdc`, `libs.txt` | the SDC and the exact Liberty files the OpenROAD flow read |
| `1_2_yosys.v.gz` | Yosys+ABC netlist of the reference |
| `input.def.gz` | OpenROAD floorplan, macros, IO pins and tap cells with standard-cell positions removed: the input of flow C (LiveHD placer on the Yosys netlist) |
| `3_place.odb.gz` | reference placement (kept only when small); the score is in `A_score/` and `result.json` |
| `A_score/` | OpenSTA reports of the reference (`score.json`, paths, power, coverage) |
| `A_logs.tar.gz` | ORFS logs and the per-step `measure*/` records |
| `sources.tar.gz` | RTL, include dirs, macro LEF/LIB and TCL inputs, stored with absolute paths (`tar -xzPf` restores them where the bazel cache had them) |
| `livehd/{S,B,C,D}/` | LiveHD artefacts: netlist, `rep/` reports, `result.json` (per-pass `phases`), command/measurement records, scores, DEFs |

## Re-run LiveHD without OpenROAD

Prerequisites: the frozen tools in `$VSL_WS/bin` (`python3 -c "import vsl; vsl.freeze()"` from this directory creates them from the
current livehd/bazel build; edit paths at the top of `vsl.py` on another machine), and the RTL at the paths in `config.mk`
(otherwise `tar -xzPf data/<design>/sources.tar.gz`).

```bash
cd HighTide/repros
export VSL_WS=/tmp/vsl-ws                       # any scratch directory with a few GB
# LiveHD synthesis only (fast): flow S;   full LiveHD flow: B;   LiveHD placer on the Yosys netlist: C
python3 run_design.py lfsr --slot 0 --restore --flows SBC --redo SBC
python3 report.py                                 # rebuilds vslivehd-llmhdl.html from data/ (+ the workspace)
```

* `--restore` loads the reference (`A`) from `data/<design>` and unpacks `input.def.gz`; no OpenROAD step of the reference is run.
* `--redo SBC` discards the stored LiveHD results for those flows and re-measures them (without it the stored ones are kept).
* Flow `D` (LiveHD's netlist through OpenROAD's floorplan/placer) needs OpenROAD on the **LiveHD** netlist, so it runs OpenROAD
  but never the reference: `--flows SD --redo SD`.
* Timeouts: 3 h per LiveHD invocation (`VSL_LHD_TIMEOUT_H`), 6 h per OpenROAD step (`VSL_TIMEOUT_H`); `--slot N` picks one of the three
  8-thread CPU sets (`SLOTS` in `vsl.py`); LiveHD itself is pinned to the first CPU of the slot.
* Exact LiveHD command lines are in `livehd/*/measure*/command.json` and in `../issues.md`.
* Comparing a new LiveHD build: the OpenROAD numbers stay as measured; only re-run LiveHD flows and re-render the report.
  The scorer (`score.tcl`) is the same for both, so numbers stay comparable.
