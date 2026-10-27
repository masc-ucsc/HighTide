# LiveHD issues found on the HighTide asap7 pre-CTS benchmark

Host llmHDL, 2026-10-26. Every number below was measured by the harness in this directory
(`run_design.py`, `vsl.py`, `score.tcl`) and is in `<WS>/<design>/result.json`; nothing here is estimated.
One run per flow and design, no repeats.

* LiveHD: `/home/renau/projs/livehd` HEAD `8e017a011`, binary `bazel-bin/lhd/lhd` (sha256 `4b7d0c48…`), `physical_repair` sha256 `ef969ea9…`.
* HighTide HEAD `9648393ce`; Yosys 0.64 + yosys-slang, OpenROAD from the bazel pin (frozen copies under `<WS>/bin`).
* Pinning: each run `taskset` to its own CPUs; LiveHD runs on **one hardware thread**
  (`synth.place.threads=1`, `pass.abc.threads=1`, `OMP_NUM_THREADS=1`); OpenROAD runs on 8 threads.
  Wall = GNU time, CPU = user+sys, IPC from `perf stat`.
* QoR for every flow is measured by the same OpenSTA script (`score.tcl`): same Liberty set, same HighTide SDC,
  `setRC.tcl` + `estimate_parasitics -placement`, ideal clocks, HPWL without clock/reset nets.
  LiveHD's own HPWL report (`rep/placement.json`) and my scorer agree (minimax: 107 230 vs 107 253 µm).
* Scope: LiveHD flows were stopped on request after the first designs, so this document covers the designs run so far
  (lfsr, minimax, NyuziProcessor, bp_uno, cnn, gemmini, NVDLA partition_c, eyeriss). OpenROAD results continue separately.


## Update 2026-10-27: rebuilt LiveHD, all designs rerun, fixed eyeriss and snitch_cluster RTL

Sections below this one (Issues 1 to 8) were measured with the first build (sha256 `4b7d0c48…`, livehd `8e017a011`); their raw results are kept under
`data/*/livehd_old/` and `data/*/result_livehd_old.json`. This update reruns every LiveHD flow on a rebuild of the local tree
(`bazel build -c opt //lhd:lhd //tools:physical_repair`, livehd `a7347ed2` plus two uncommitted files; hashes in `data/livehd_build_b.json`),
single LiveHD thread, 3 h cap per invocation, same OpenROAD reference, same scorer. Flows: **S** synthesis only, **B** full LiveHD flow,
**D** LiveHD netlist through OpenROAD's floorplan/placer, **C** Yosys netlist placed by LiveHD's placer on OpenROAD's floorplan.
Deltas are relative to the OpenROAD run of the same design (area and HPWL in %, WNS in ps absolute); "OpenROAD wall" is Yosys+ABC plus floorplan to legal placement.

| design | OpenROAD wall | OpenROAD Yosys+ABC | LiveHD synth only (S) | LiveHD full wall (B) | B: area / HPWL / WNS ps | D: area / HPWL / WNS ps | C: area / HPWL / WNS ps |
|---|--:|--:|--:|--:|---|---|---|
| lfsr | 1.9 min | 95 s | 1 s | 6 s | -6% / +21% / 23 | -2% / -9% / 37 | +0% / +63% / 60 |
| minimax | 85 s | 31 s | 10 s | 4.2 min | -1% / -8% / -486 | -3% / -13% / 64 | +3% / +228% / 35 |
| NVDLA/partition_m | 65 s | 9 s | 65 s | 2.1 min | +20% / +113% / -248 | +19% / +14% / 503 | +1% / +305% / 382 |
| sha3 | 85 s | 22 s | 21 s | 84 s | -6% / -15% / -83 | -8% / -20% / 316 | +2% / +117% / 107 |
| ternip | 97 s | 29 s | 32 s | 5.4 min | +196% / +515% / -472 | +23% / +36% / 107 | +3% / +263% / 108 |
| litedram | 88 s | 20 s | 12 s | 1.7 min | +0% / +16% / 117 | -24% / -29% / 439 | physical_repair failed: unsupported DEF signa |
| NVDLA/partition_a | 4.2 min | 29 s | 19 s | 5.7 min | +6% / +118% / -98,461 | +6% / +14% / 483 | +8% / +2395% / -1,380 |
| floonoc | 16.6 min | 10.1 min | 74 s | — | unmapped flop | OpenROAD cannot read netlist | +2% / +1357% / -525 |
| NVDLA/partition_p | 8.4 min | 58 s | 68 s | 9.2 min | -0% / +324% / -28,067 | -1% / -8% / 46 | +3% / +297% / -25,581 |
| coralnpu | 20.7 min | 4.6 min | 1.9 min | — | unmapped flop | OpenROAD cannot read netlist | +2% / +172% / -17,935 |
| NVDLA/partition_o | 24.5 min | 4.1 min | 7.1 min | 27.5 min | -2% / +516% / -133,964 | -4% / -6% / -169 | +4% / +494% / -37,853 |
| gemmini | 33.1 min | 6.9 min | 10 s | 38.6 min | -6% / +33% / 30 | -6% / -12% / 267 | +5% / +131% / 36 |
| liteeth | 4.2 min | 37 s | 41 s | — | cannot score (SDC names) | OpenROAD cannot read netlist | +0% / +162% / -828 |
| vortex | 21.1 min | 2.6 min | 43 s | 27.1 min | +5% / +16% / -2,466 | +5% / +17% / -454 | +1% / +28% / -795 |
| bp_processor/bp_uno | 28.3 min | 4.6 min | 96 s | — | unmapped flop | OpenROAD cannot read netlist | +1% / +38% / -4,521 |
| snitch_cluster | 3.03 h | 1.15 h | 8.8 min | — | unmapped flop | OpenROAD cannot read netlist | 64 GB cap |
| litepci | 11.2 min | 54 s | 20 s | — | lhd failed: placement failed: DREAMPlace macr | OpenROAD cannot read netlist | physical_repair failed: invalid terminal lega |
| NVDLA/partition_c | 37.3 min | 2.2 min | 95 s | 28.4 min | +0% / +239% / -1,037,009 | +1% / +20% / -3,104 | -1% / +311% / -57,065 |
| eyeriss | 3.38 h | 39 s | 17 s | 39.6 min | -2% / -40% / -428,040 | -1% / -4% / -788 | -0% / +42% / -15,134 |
| NyuziProcessor | 41.2 min | 9.9 min | 2.9 min | — | unmapped flop | OpenROAD cannot read netlist | physical_repair failed: pass.opentimer built  |
| cnn | 35.1 min | 5.6 min | 3.9 min | 43.4 min | -0% / -39% / -742,902 | -0% / -63% / -3,534 | -1% / -68% / -17,252 |

What the rebuild changed (compare with Issues 1 to 8): the placer is much faster (lfsr 88 s to 6 s, minimax 106 min to 4.2 min, partition_c 29 min vs a 3 h timeout before),
`cnn`, `gemmini` and `partition_c` now finish, and the macro-row error in flow C is gone (`bp_uno`, `Nyuzi`, `cnn`, `partition_c` now run through `physical_repair`).
What did not change or is new:

1. **Timing of LiveHD-placed results is extreme on macro designs.** B has WNS in the hundreds of nanoseconds to microseconds negative on `cnn` (-743 ns), `eyeriss` (-428 ns),
   `partition_c` (-1.04 µs), `partition_o` (-134 ns), `partition_a` (-98 ns), `partition_p` (-28 ns), while the same netlists placed by OpenROAD (flow D) are within a few ns of the reference.
   Wirelength is often better than OpenROAD (`cnn` -39 %, `eyeriss` -40 %) or much worse (NVDLA partitions +113 % to +516 %), so the macro/IO arrangement LiveHD produces is the likely cause; I did not investigate further.
2. **LiveHD's mapped netlist leaves native cells unmapped** (`$adff`, `$dff`, `$mux`, `$not`, `$logic_not` instances in the Verilog it emits): NyuziProcessor 61 `$adff`, coralnpu 535 `$adff` + 123 `$dff` + 574 `$mux`,
   floonoc 160 `$adff` (+ `$mux`/`$not`/`$logic_not`), bp_uno and snitch_cluster likewise. The full flow stops with `placement failed: unmapped physical object: flop` and OpenROAD cannot read the netlist (flow D fails).
3. **Names the common SDC needs are not preserved:** `liteeth` (`30 LiteEth transmit half-clock driver is missing`) and `litepci` (`pin not found`): the SDC cannot be applied to LiveHD's DEF or netlist, so those results cannot be scored.
4. **New `litepci` errors:** B `placement failed: DREAMPlace macro legalization ...`, C `physical_repair failed: invalid terminal legalization ...`; `litedram` C: `unsupported DEF signal port: sdram_dq[0]` (inout port).
5. **Quality of the Yosys netlist in LiveHD's placer (C)** is worse than OpenROAD on every design where it completes except `cnn` (HPWL +28 % to +2,395 %; `cnn` -68 %, but its reference is the macro-bound -7.5 ns case), and `snitch_cluster` C is killed at the 64 GB cap; `NyuziProcessor` C stops with `pass.opentimer built an incomplete timing graph: 2821 Liberty input pin(s) are unconnected`.
6. **Synthesis speed:** LiveHD synthesis only (S) is faster than Yosys+ABC on most designs (snitch_cluster 8.8 min vs 1.15 h, bp_quad 2 min vs 52 min, eyeriss 17 s vs 39 s) and slower on a few (NVDLA partition_m 65 s vs 9 s).
   The D rows show the synthesis result itself is competitive: area -24 % to +23 % and HPWL mostly better than the reference when OpenROAD places LiveHD's netlist.

### RTL fixes used for eyeriss and snitch_cluster (both flows read the same fixed files)

(`python3 make_rtl_fixes.py` regenerates `rtl_fixes/` from the bazel externals and the repository patches; the generated files are not committed.)

* **eyeriss** (`repros/rtl_fixes/eyeriss/eyeriss.v`): regenerated from pristine upstream with the two patches already in `MODULE.bazel`
  (`eyeriss-shape-compiler-synthesis.patch` guards the unfinished, never-instantiated `SCNN_shape_info_compiler` that referenced undeclared signals;
  `eyeriss-psum-router-width.patch` widens a 1-bit `internal_data` wire that silently dropped 20 of 21 data bits) and the current `dev/generate_rtl.py`
  (banked SRAM wrappers with sliced addresses). The benchmark had used a stale `eyeriss.v` whose wrappers connected full-width addresses to narrower macros (Yosys: `Resizing cell port ... from 12 bits to 9 bits`).
  Result: LiveHD's native reader compiles it in 1.8 s and all four flows run. The design is larger than the stale one (604,779 µm² and 384,497 cells vs 124,708 µm² and 298,485 cells), so the old eyeriss numbers are in `data/_superseded/eyeriss_orig_rtl/`.
* **snitch_cluster** (`repros/rtl_fixes/snitch_cluster/snitch.sv`, bazel patch `patches/snitch-cluster-fp-inst-comb-loop.patch`, committed on branch `snitch-fp-inst-comb-loop`): Yosys `check` found 660 logic loops, all through
  `alu_result -> consec_pc -> inst_addr_misaligned -> exception -> is_acc_inst -> is_fp_inst -> rs*_is_f2i -> opa/opb -> alu_result`;
  `is_fp_inst` now uses the decoder value before the exception sanitisation (`is_acc_inst_pre`); `check` reports 0 loops afterwards. LiveHD's native reader still reports a loop elsewhere (names not available), so LiveHD uses the yosys-slang reader for this design.
  The old OpenROAD result is in `data/_superseded/snitch_cluster_orig_rtl/`.

| fixed RTL | OpenROAD (A) | LiveHD S | LiveHD B | D | C |
|---|---|---|---|---|---|
| eyeriss | 3.38 h (Yosys+ABC 39 s), WNS -589 ps | 41 s | 39.6 min, area -2 %, HPWL -40 %, WNS -428,040 ps | area -1 %, HPWL -4 %, WNS -788 ps | area -0 %, HPWL +42 %, WNS -15,134 ps |
| snitch_cluster | 3.03 h (Yosys+ABC 1.15 h), WNS -90 ps | 8.8 min | fails: unmapped flop | fails: OpenROAD cannot read netlist | killed at 64 GB cap |

## Issues 1 to 8 below: first LiveHD build

## Summary

| # | Issue | Smallest design that shows it | Measured |
|---|-------|-------------------------------|----------|
| 1 | Global placement never reaches its overflow target; the placer dominates runtime even for a 133-cell design | `lfsr` (133 cells) | LiveHD 88 s, 86 s of it placer; OpenROAD floorplan→legal placement 17 s (each step includes ~1.1 s process start) |
| 2 | Placer runtime explodes with design size; ~88 % of it is the incremental timing engine | `minimax` (18 k cells) | 6 390 s (106 min) vs OpenROAD 54 s; 5 607 s inside `pass.opentimer.incremental` |
| 3 | Placement quality: HPWL far worse than OpenROAD, global placement not converged | `minimax` | HPWL 107 253 µm vs 47 587 µm (+125 %); `gp_converged=false` |
| 4 | Same degradation with a *Yosys+ABC* netlist (so it is the placer, not the synthesis) | `lfsr`, `minimax` | HPWL +63 % (lfsr), +177 % (minimax); 63 s / 959 s |
| 5 | Hard failures (front end, flop mapping, floorplan import) | `eyeriss`, `NyuziProcessor`, `bp_uno`, macro designs | see §5 |
| 6 | 3 h wall-time limit reached | `cnn` (232 k cells), `gemmini` (645 k), `NVDLA/partition_c` (273 k) | no result |

Synthesis itself is not the problem. With LiveHD's netlist pushed through OpenROAD's placer (flow D) minimax is
+3.0 % cells / +2.8 % area and has *better* HPWL (−8.9 %) and WNS than the Yosys+ABC reference; the whole LiveHD
synthesis (compile + color + ABC) takes 9.7 s against 31 s for Yosys+ABC.

## Issue 1: `lfsr`, 133 cells, placer takes 86 s

Design: `lfsr_prbs_gen`, die 5.8 × 5.9 µm, utilization 0.55.

| | OpenROAD flow (A) | LiveHD (B) |
|---|---|---|
| Wall, RTL → placed | 111 s (95 s of it Yosys, see note) | 88.0 s |
| Floorplan → legal placement | 17 s | 86.0 s (placer) |
| compile / synth (color+ABC) / final STA | – | 0.3 s / 0.9 s / 0.7 s |
| logic cells / area µm² | 146 / 19.58 | 133 / 18.17 |
| WNS / TNS ps | +20.6 / 0 | +22.5 / 0 |
| HPWL µm | 155.5 | 167.8 (+7.9 %) |
| power mW | 8.79e-5 | 9.45e-5 |

Placer phases (s): `pass.place` 42.9, `pass.place.timing_driven` 33.1, `pass.place.repair` 3.7,
`pass.place.final_legalize` 1.6, `pass.place.resize` 1.3, `pass.place.post_synth_timing` 1.9, `pass.place.io_resynth` 1.1.

Evidence that global placement does not converge on this trivial design (from the run log):

```
WARNING: native DREAMPlace GP stopped at 1500 iterations (iteration cap) with overflow 0.277741 (target 0.100000) ...
WARNING: native DREAMPlace GP stopped at  500 iterations (iteration cap) with overflow 0.399069 (target 0.100000) ...
WARNING: native DREAMPlace GP stopped at  500 iterations (iteration cap) with overflow 0.384592 (target 0.100000) ...
WARNING: native DREAMPlace GP stopped at  500 iterations (iteration cap) with overflow 0.403477 (target 0.100000) ...
```

`rep/placement.json`: `"gp_converged": false`, `"gp_overflow": 0.403`, `initial_hpwl_um 183.6`, `hpwl_um 148.0` at GP end.
The run also prints `synth-target-unreachable: timing target 280 ps (abc.delay) is out of reach: achieved 665 ps`.

Note on the OpenROAD side: Yosys `hierarchy` takes 88 s on this design (99 % of the Yosys read step). That is a Yosys outlier,
not a LiveHD issue, and it is why the OpenROAD total is 111 s.

## Issue 2 and 3: `minimax` (RV32 core, 16.6 k cells)

| | OpenROAD flow (A) | LiveHD (B) | LiveHD netlist → OpenROAD placer (D) | Yosys netlist → LiveHD placer (C) |
|---|---|---|---|---|
| Wall | 85 s (Yosys+ABC 31 s, floorplan→place 54 s) | 6 390 s | – | 959 s (place 495 + repair 464) |
| LiveHD compile / synth / placer / STA | – | 0.2 / 9.5 / 6 385 / 8.4 s | – | – |
| logic cells | 16 616 | 18 283 (+10.0 %) | 17 115 (+3.0 %) | 17 998 (+8.3 %) |
| area µm² | 1 990 | 2 147 (+7.9 %) | 2 047 (+2.8 %) | 2 096 (+5.3 %) |
| WNS ps | +53.7 | +87.9 | +82.4 | +62.4 |
| HPWL µm | 47 587 | 107 253 (+125 %) | 43 333 (−8.9 %) | 132 000 (+177 %) |
| power mW | 5.33e-3 | 7.43e-3 (+39 %) | 6.09e-3 (+14 %) | 5.57e-3 (+5 %) |

Placer phases in B (s): `pass.place` 4 637, `pass.place.timing_driven` 1 285, `pass.place.repair` 275,
`pass.place.resize` 156, `pass.place.final_legalize` 12. The nested `pass.opentimer.incremental` calls sum to 5 607 s
(88 % of the placer). CPU 6 387 s, IPC 1.49, 4.3e13 instructions, peak RSS 1.8 GB. LiveHD reports
`gp_converged: false`; the log shows the GP stopping at its 1500-iteration cap with overflow 0.19.

Sensitivity check (not part of the sweep): the same design with LiveHD defaults only (no HighTide knobs: utilization 0.30,
density 0.5, memory proxies instead of flops) took 1 235 s (placer 1 234 s, 981 s of it in `pass.opentimer.incremental`).
So the cost is not an artifact of the HighTide utilization/density, it is already ~23× OpenROAD's whole flow at defaults,
and ~5× worse at the HighTide settings. (Command: same as below but without the `synth.place.density`, `synth.place.utilization`,
`synth.memory`, `pass.abc.*` and `synth.place.threads` sets, and with `synth.place=true`.)

## Issue 4: the Yosys+ABC netlist through LiveHD's native placer (flow C)

Same netlist, floorplan, macros and IO pins as the OpenROAD run (`3_2_place_iop.odb`, standard-cell positions removed),
placed by `physical_repair` (cell placement, then its repair pass):

| | lfsr | minimax |
|---|---|---|
| OpenROAD placement (A) HPWL µm | 155.5 | 47 587 |
| LiveHD placer on that netlist HPWL µm | 253.2 (+63 %) | 132 000 (+177 %) |
| WNS ps (A → C) | +20.6 → +61.6 | +53.7 → +62.4 |
| time (place + repair) | 22.3 + 40.6 s | 495 + 464 s |

LiveHD's own `qor.json` for minimax: `gp_converged false`, `gp_overflow 0.168`, `initial_hpwl_um 114 967 → hpwl_um 130 149`.
The placer therefore trades wirelength for timing and does not converge; WNS improves slightly, HPWL is 2.8× OpenROAD's.

## Issue 5: hard failures (reproducible, fast)

| Design | Flow | Message |
|---|---|---|
| `eyeriss` | `lhd synth` (0.2 s) | `use of undeclared identifier 'psum_acc_times'; did you mean 'psum_acc_done'?` (the same RTL elaborates in yosys-slang) |
| `NyuziProcessor` | `lhd synth` (157 s, fails after ABC) | `placement failed: unmapped physical object: flop` |
| `bp_processor/bp_uno` | `lhd synth` (97 s) | `timing seed placement failed: unmapped physical object: flop` |
| `NyuziProcessor`, `bp_uno`, `cnn`, `NVDLA/partition_c`, `eyeriss` | `physical_repair` on OpenROAD's floorplan | `floorplan requires contiguous equal-width N/FS rows; row gaps and rotated rows are unsupported` (all designs with macros: OpenROAD cuts rows around them) |

For `eyeriss`, `bp_uno` and `NyuziProcessor` the synthesis-only step was added later and was not run before LiveHD was stopped.

## Issue 6: time limit

`cnn` (232 k cells), `gemmini` (645 k cells, no macros) and `NVDLA/partition_c` (273 k cells) did not finish `lhd synth`
within 3 h (`VSL_LHD_TIMEOUT_H`), so there is no LiveHD data for them. OpenROAD placed them in 26 to 35 min
(floorplan → legal placement: cnn 1 771 s, gemmini 1 572 s, partition_c 2 106 s), plus Yosys+ABC 133 to 412 s.

## How to reproduce

All reference (OpenROAD) results, netlists, the flow-C input DEF and the LiveHD artefacts are kept in `repros/data/<design>/`
(see `data/README.md`); LiveHD can be re-evaluated from them with `python3 run_design.py <design> --restore --flows SBC --redo SBC`
without re-running OpenROAD.

Variables used below:

```bash
BZ=/home/renau/.cache/bazel/_bazel_renau/e89feab91b9c23a93bdaa11c75f4275f
PLAT=$BZ/external/orfs+/flow/platforms/asap7
HT=/home/renau/projs/HighTide
WS=<workspace holding the frozen bin/>        # harness: /tmp/.../scratchpad/ws ; lhd = $WS/bin/lhd/lhd
LHD=/home/renau/projs/livehd/bazel-bin/lhd/lhd   # the frozen copy is byte-identical
RTL_LFSR=$BZ/external/+_repo_rules+lfsr_src/rtl
RTL_MINIMAX=$BZ/execroot/_main/bazel-out/k8-fastbuild/bin/designs/src/minimax
OUT=$WS/repro/<name>; mkdir -p $OUT
```

### Liberty merged for LiveHD (dont_use applied, same cell set the OpenROAD flow reads)

```bash
python3 $HT/tools/vslivehd/merge_liberty.py \
  --dont-use '*x1p*_ASAP7*' --dont-use '*xp*_ASAP7*' --dont-use 'SDF*' --dont-use 'ICG*' \
  $WS/lib/asap7.lib \
  $PLAT/lib/NLDM/asap7sc7p5t_AO_RVT_FF_nldm_211120.lib.gz \
  $PLAT/lib/NLDM/asap7sc7p5t_INVBUF_RVT_FF_nldm_220122.lib.gz \
  $PLAT/lib/NLDM/asap7sc7p5t_OA_RVT_FF_nldm_211120.lib.gz \
  $PLAT/lib/NLDM/asap7sc7p5t_SIMPLE_RVT_FF_nldm_211120.lib.gz \
  $PLAT/lib/NLDM/asap7sc7p5t_SEQ_RVT_FF_nldm_220123.lib
```

(`$WS/lib/lfsr.lib` and `$WS/lib/minimax.lib` in the recorded commands are this file.)

### Issue 1 (lfsr), pinned to one CPU exactly like the benchmark

```bash
taskset -c 0 env OMP_NUM_THREADS=1 \
$LHD synth $RTL_LFSR/lfsr.v $RTL_LFSR/lfsr_prbs_check.v $RTL_LFSR/lfsr_prbs_gen.v \
  --top lfsr_prbs_gen \
  --workdir $OUT/w \
  --emit verilog:$OUT/netlist.v \
  --emit-dir report:$OUT/rep/ --stats \
  --result-json $OUT/result.json \
  --emit-dir def:$OUT/def/ \
  --set synth.liberty=$WS/lib/asap7.lib \
  --set synth.sdc=$HT/designs/asap7/lfsr/constraint.sdc \
  --set synth.lef=$PLAT/lef/asap7_tech_1x_201209.lef,$PLAT/lef/asap7sc7p5t_28_R_1x_220121a.lef \
  --set synth.place=true \
  --set synth.place.density=0.6 \
  --set synth.place.tech_rc=$PLAT/setRC.tcl \
  --set synth.place.threads=1 \
  --set pass.abc.threads=1 \
  --set synth.memory=flops \
  --set pass.abc.drop_init=true \
  --set pass.abc.derived_clock=true \
  --set synth.place.unknown_const=zero \
  --set synth.place.utilization=0.55 \
  -- -D SYNTHESIS --ignore-assertions --compat=vcs --timescale=1ns/1ps
```

Per-pass milliseconds: `python3 -c "import json;[print(p['name'],p['ms']) for p in json.load(open('$OUT/result.json'))['phases']]"`.
The compile / synth / placer split used in this document sums these sequential phases:
compile = everything before `pass.color`; synth = `pass.color` + `pass.abc`; placer = all `pass.place*`
(the `pass.opentimer.incremental` entries are nested in them and not added again); final STA = the last `pass.opentimer`.

### Issues 2 and 3 (minimax)

```bash
taskset -c 0 env OMP_NUM_THREADS=1 \
$LHD synth $RTL_MINIMAX/minimax.v \
  --top minimax \
  --workdir $OUT/w \
  --emit verilog:$OUT/netlist.v \
  --emit-dir report:$OUT/rep/ --stats \
  --result-json $OUT/result.json \
  --emit-dir def:$OUT/def/ \
  --set synth.liberty=$WS/lib/asap7.lib \
  --set synth.sdc=$HT/designs/asap7/minimax/constraint.sdc \
  --set synth.lef=$PLAT/lef/asap7_tech_1x_201209.lef,$PLAT/lef/asap7sc7p5t_28_R_1x_220121a.lef \
  --set synth.place=true \
  --set synth.place.density=0.7 \
  --set synth.place.tech_rc=$PLAT/setRC.tcl \
  --set synth.place.threads=1 \
  --set pass.abc.threads=1 \
  --set synth.memory=flops \
  --set pass.abc.drop_init=true \
  --set pass.abc.derived_clock=true \
  --set synth.place.unknown_const=zero \
  --set synth.place.utilization=0.65 \
  -- -D SYNTHESIS --ignore-assertions --compat=vcs --timescale=1ns/1ps
```

Expected: about 106 minutes, `rep/placement.json` with `"gp_converged": false`, `"hpwl_um": 107230`.
The `synth.*` settings above come from the HighTide config of each design (`CORE_UTILIZATION` 55 / 65, `PLACE_DENSITY` 0.6 default / 0.7)
and from `tools/vslivehd/lhdsweep.py` (`synth.memory=flops`, `pass.abc.drop_init`, `pass.abc.derived_clock`, `synth.place.unknown_const`).

Synthesis only (fast, no placement; same command with `--set synth.place=false` and without the `--emit-dir def:` line)
takes ~10 s on minimax and produces the netlist that gives the good flow-D numbers.

### Issue 4 (Yosys netlist through `physical_repair`)

1. Run the OpenROAD reference up to `3_2_place_iop.odb` for the design, e.g. `python3 $HT/repros/run_design.py lfsr --flows A --slot 0`
   (`VSL_WS=$WS`); the ORFS config it generates is `$WS/lfsr/A/config.mk`.
2. Remove standard-cell positions (macros, IO and tap cells stay):

```tcl
read_db $WS/lfsr/A/results/asap7/lfsr_prbs_gen/base/3_2_place_iop.odb
foreach inst [[ord::get_db_block] getInsts] {
  if {![[$inst getMaster] isBlock] && [$inst getPlacementStatus] ne "FIRM" && [$inst getPlacementStatus] ne "LOCKED"} {
    if {![[$inst getMaster] isFiller] && [[$inst getMaster] getType] ne "CORE_WELLTAP"} {$inst setPlacementStatus NONE}
  }
}
write_def $WS/lfsr/C/input.def
```

3. `place.json` (the policy of `tools/vslivehd/run.py`) and the run:

```json
{ "source_def": true, "cell_place": true, "timing_driven": true, "iterations": 1500, "timing_rounds": 3,
  "min_iterations": 500, "density_upper_bound": true, "fixed_macro_overlap_weight": 5.0, "halo": 0,
  "post_density_factor": 4, "top": "lfsr_prbs_gen", "def": "$WS/lfsr/C/input.def",
  "liberty": "$WS/lib/asap7.lib", "sdc": "$HT/designs/asap7/lfsr/constraint.sdc",
  "tech_rc": "$PLAT/setRC.tcl",
  "lefs": ["$PLAT/lef/asap7_tech_1x_201209.lef", "$PLAT/lef/asap7sc7p5t_28_R_1x_220121a.lef"],
  "density": 0.6, "threads": 1, "output": "$WS/lfsr/C/livehd_place" }
```

```bash
taskset -c 0 env OMP_NUM_THREADS=1 RUNFILES_DIR=$WS/bin/physical_repair_dir/physical_repair.runfiles \
  $WS/bin/physical_repair_dir/physical_repair $WS/lfsr/C/place.json
# repair pass: same JSON without "cell_place", "def": ".../livehd_place/out.def", "output": ".../livehd_repair"
```

Substitute the `$VAR`s in the JSON by hand (JSON does not expand them).

### Whole benchmark and scoring

```bash
export VSL_WS=$WS
python3 $HT/repros/run_design.py lfsr --slot 0 --flows ASBDC     # flows A (OpenROAD), S (LiveHD synth only), B, D, C
python3 $HT/repros/sweep.py --flows A                             # OpenROAD only, 3 designs at a time
```

Scoring (identical for every flow) is `$HT/repros/score.tcl`, driven by `vsl.score()`; the HTML report is
`python3 $HT/repros/report.py`.

## Issue 7: `snitch_cluster` (1.7 M cells in the OpenROAD flow) cannot be synthesized by LiveHD

Asked for the LiveHD synthesis time of `snitch_cluster` with 8 threads: there is none, both front ends fail before synthesis starts.
Binary: the local build at `livehd/bazel-bin/lhd/lhd` (sha256 `e96b3c1f…`, built 2026-10-26 13:55, working tree not clean), 8 threads
(`pass.abc.threads=8`, `synth.place.threads=8`, `OMP_NUM_THREADS=8`, pinned to 8 hardware threads), synthesis only (`synth.place=false`).

| Front end | Time to failure | Failure |
|---|---|---|
| native slang reader (`lhd synth`) | 3.6 s | 131 errors, among them `variable 'trace_entry' has a non-integral type`, `system task '$sformat' is not supported by --reader slang` (both in `snitch_cc.sv`), and the final `only packed-struct field access is supported` |
| yosys-slang reader (`lhd compile --reader yosys-slang`, as `design_config.json` uses for vortex) | 106.9 s (CPU 111 s, 2.8 GB, IPC 1.6) | `combinational loop in 'snitch_cluster_wrapper': get_mask -> ror -> ror -> eq -> get_mask -> mux -> ...` from `pass.legalize`, exit code 6, no message in the JSON result |

For comparison OpenROAD's Yosys+ABC on the same design takes 1.11 h (ABC 25.2 min, 437 ABC runs).
Exact command lines (377 RTL files, include dirs, macro Liberty) are recorded in
`data/snitch_cluster/livehd/S*/measure*/command.json`; the harness reproduces them:

```bash
cd HighTide/repros; export VSL_WS=<workspace>
# native reader, 8 threads
VSL_LHD=<path to lhd> VSL_LHD_THREADS=8 python3 run_design.py snitch_cluster --slot 1 --restore --flows S --redo S
# yosys-slang reader
VSL_LHD_READER=yosys VSL_LHD=<path to lhd> VSL_LHD_THREADS=8 python3 run_design.py snitch_cluster --slot 1 --restore --flows S --redo S
```

(`VSL_LHD` picks the lhd executable, `VSL_LHD_THREADS` the thread count; defaults are the frozen binary and 1 thread.)

## Issue 8: `lhd compile` alone (the equivalent of Yosys read) on the designs OpenROAD handles

Compile only (no synthesis, no placement), local LiveHD build `bazel-bin/lhd/lhd` sha256 `e96b3c1f…` (2026-10-26 13:55), native slang reader,
the same slang flags as the benchmark, `synth.liberty` set (as `lhd synth` hands it to its compile step, otherwise SRAM macros are unknown modules).
`default` = no per-design options; `per-design` = the `compile.*` options in `tools/vslivehd/design_config.json`. Data: `data/compile_check.json`,
script `compile_check.py` (the whole sweep takes a few minutes; the slowest is the yosys-slang path on snitch_cluster, 109 s).

| group | designs | what it takes |
|---|---|---|
| compile with defaults (9) | lfsr, minimax, sha3, ternip, gemmini, floonoc, coralnpu, NyuziProcessor, bp_uno | nothing |
| compile only with per-design options (9) | NVDLA partition_a/c/m/o/p, cnn, litedram, liteeth, litepci | `compile.slang.*` flags (below) |
| no working native configuration (3) | eyeriss, snitch_cluster, vortex | vortex works through the yosys-slang reader; eyeriss and snitch_cluster do not compile at all |
| fails native, works only via yosys-slang reader (1) | bp_quad | `instance 'mem' refers to an unknown module` in the native reader (bp_uno, same RTL family, compiles) |

Default-flag failures and the options that fix them:

| design | default error | option that makes it compile |
|---|---|---|
| NVDLA ×5 | `use of undeclared identifier 'lut_in_oflow0'` (9 errors; implicit nets, which Yosys's Verilog-2005 front end accepts) | `compile.slang.ignore_uninstantiated_modules=true`, `compile.slang.translate_off=true` |
| cnn | `liberty-memory-name-collision: module 'fakeram_w16_l512' is defined in the design sources and as a synth.liberty memory macro` | `compile.slang.liberty_macro_precedence=true` |
| litedram | `unsupported-inout-port: port 'sdram_dq' is inout/ref, which --reader slang cannot lower` | `compile.slang.inout_as_driven=true` |
| liteeth | `port 'rw0_clk' does not exist in 'fakeram_1rw1r_64w64d_sram'` (21 errors) | `liberty_macro_precedence`, `ignore_uninstantiated_modules`, `liberty_cells`, `unconnected_input=one` (all `compile.slang.*`), `compile.specialize_modules=true` |
| litepci | `use of undeclared identifier 'ALIGN_COMMA_VALUE'` | the liteeth set plus `compile.slang.blackbox_attribute=true` |

Failures with no working option:

| design | error | detail |
|---|---|---|
| eyeriss | `use of undeclared identifier 'psum_acc_times'`, `'layer0_flag'`, `misplaced trailing ','` (11 errors) | fails after 0.2 s in the native reader and in the yosys-slang reader; OpenROAD's flow reads it with Yosys's own Verilog-2005 front end |
| snitch_cluster | 131 errors: `variable 'trace_entry' has a non-integral type`, `system task '$sformat' is not supported by --reader slang`, `only packed-struct field access is supported` | 4 s native; the yosys-slang path runs 109 s and ends in `combinational loop in 'snitch_cluster_wrapper'` (`pass.legalize`) |
| vortex | `'' is not a module (interfaces/programs unsupported)` (324 errors) | works with `--reader yosys-slang` (3 s), which is what `design_config.json` uses |
| bp_quad | `instance 'mem' refers to an unknown module` (5 errors) | yosys-slang reader compiles it in 13 s |

Front end used by the OpenROAD flow for the same RTL (from the Yosys read logs): Yosys's built-in Verilog-2005 front end for
cnn, eyeriss, gemmini, lfsr, litedram, liteeth, litepci, minimax, NVDLA ×5, NyuziProcessor, sha3 (Verilog-2005 accepts implicit nets and
other legacy constructs); yosys-slang for bp_quad, bp_uno, coralnpu, floonoc, ternip, vortex, snitch_cluster (`SYNTH_HDL_FRONTEND=slang`).
The `yosys` column in `data/compile_check.json` is not a fair test of the yosys-slang path: it does not pass the options ORFS passes (it fails,
for example, on ternip's assertions, which `--ignore-assertions` fixes in the native run); only the cases where it succeeds are meaningful.

Reproduce one design (compile only, native reader, per-design options, as in the table):

```bash
cd HighTide/repros; export VSL_WS=<workspace> VSL_LHD=<path to lhd>
python3 compile_check.py --only minimax,litedram --readers native,tuned
```

## Smallest things to look at first

1. `lfsr`: why do four global-placement runs hit their iteration caps at overflow 0.28 to 0.40 for 133 cells in a 5.8 µm die,
   and why does it then spend 43 s in `pass.place` and 33 s in `pass.place.timing_driven`?
2. `minimax`: number and cost of timing evaluations in the timing-driven loop (190 STA evaluations visible in the log,
   about 5 600 s in total, versus 160 s for the actual `resize` and `repair`).
3. Why HPWL is 2.3× to 2.8× OpenROAD's on minimax even when the final timing is better: the weights driving the placement
   toward timing at the cost of wirelength (`timing_max_weight 5.0`, `timing_fraction 0.2` in `placement.json`).
