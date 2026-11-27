#!/usr/bin/env bash
# Synthesize and place a HighTide design with LiveHD (no CTS / routing).
#
#   tools/lhd_place.sh <asap7|sky130hd> <sha3|liteeth> [run-dir]
#
# Environment (defaults in brackets):
#   LHD       lhd binary             [../livehd/bazel-bin/lhd/lhd]
#   ORFS      OpenROAD-flow-scripts checkout, only flow/platforms is used [../OpenROAD-flow-scripts]
#   THREADS   lhd.jobs               [4]
#   BAZEL     bazel command used to generate the RTL [bazel]
#   EXTRA     extra "lhd synth" arguments, e.g. EXTRA="--set synth.place.policy.fast=true"
#
# The RTL comes from the Bazel generators (//designs/src/sha3:rtl,
# //designs/src/liteeth:liteeth_rtl). Technology inputs (Liberty, LEF, SDC, RC, tracks) are the
# ones the ORFS flow reads; die/core is derived from the design's ORFS CORE_UTILIZATION.
# Everything else keeps LiveHD's defaults.
set -euo pipefail
cd "$(dirname "$0")/.."

plat=${1:?usage: $0 <asap7|sky130hd> <sha3|liteeth> [run-dir]}
design=${2:?usage: $0 <asap7|sky130hd> <sha3|liteeth> [run-dir]}
run=${3:-runs/$plat-$design}
LHD=${LHD:-../livehd/bazel-bin/lhd/lhd}
ORFS=${ORFS:-../OpenROAD-flow-scripts}
THREADS=${THREADS:-4}
BAZEL=${BAZEL:-bazel}
P=$ORFS/flow/platforms/$plat
D=designs/$plat/$design

# ORFS CORE_UTILIZATION of each design (designs/<plat>/<design>/BUILD.bazel)
case "$plat/$design" in
  asap7/sha3)       top=sha3; util=0.70 ;;
  sky130hd/sha3)    top=sha3; util=0.30 ;;
  asap7/liteeth)    top=liteeth_udp_usp_gth_sgmii; util=0.38; halo=10,10; defs="-D USE_ASAP7_CELLS"; unk=zero ;;
  sky130hd/liteeth) top=liteeth_udp_usp_gth_sgmii; util=0.45; halo=30,30; defs="-D USE_SKY130HD_CELLS"; unk=zero ;;
  *) echo "unsupported $plat/$design" >&2; exit 2 ;;
esac

case $design in
  sha3)    gen=//designs/src/sha3:rtl;          rtl=(bazel-bin/designs/src/sha3/sha3.v) ;;
  liteeth) gen=//designs/src/liteeth:liteeth_rtl
           rtl=(bazel-bin/designs/src/liteeth/liteeth_udp_usp_gth_sgmii.v designs/src/liteeth/libraries/xilinx/*.v) ;;
esac

case $plat in
  asap7)
    nldm=$P/lib/NLDM/asap7sc7p5t
    std=($nldm"_AO_RVT_FF_nldm_211120.lib.gz" $nldm"_INVBUF_RVT_FF_nldm_220122.lib.gz"
         $nldm"_OA_RVT_FF_nldm_211120.lib.gz" $nldm"_SIMPLE_RVT_FF_nldm_250407.lib.gz"
         $nldm"_SEQ_RVT_FF_nldm_220123.lib")
    lefs=($P/lef/asap7_tech_1x_201209.lef $P/lef/asap7sc7p5t_28_R_1x_220121a.lef)
    tracks=$P/openRoad/make_tracks.tcl ;;
  sky130hd)
    std=($P/lib/sky130_fd_sc_hd__tt_025C_1v80.lib)
    lefs=($P/lef/sky130_fd_sc_hd.tlef $P/lef/sky130_fd_sc_hd_merged.lef)
    tracks=$P/make_tracks.tcl ;;
esac
srams=()
if [ -d "$D/sram/lib" ]; then
  for f in "$D"/sram/lib/*.lib; do srams+=("$f"); done
  for f in "$D"/sram/lef/*.lef; do lefs+=("$f"); done
fi

mkdir -p "$run"
lib=$run/liberty.lib
# LiveHD reads one Liberty file: merge the standard-cell libraries (same units) and append
# the macro libraries in their native units.
tmp=$(mktemp "$lib.XXXXXX"); trap 'rm -f "$tmp"' EXIT
if [ "$plat" = asap7 ]; then
  python3 tools/merge_liberty.py --dont-use '*x1p*_ASAP7*' --dont-use '*xp*_ASAP7*' \
    --dont-use 'SDF*' --dont-use 'ICG*' "$tmp" "${std[@]}"
else
  cat "${std[@]}" > "$tmp"
fi
for l in "${srams[@]}"; do printf '\n' >> "$tmp"; cat "$l" >> "$tmp"; done
mv "$tmp" "$lib"

$BAZEL build $gen ${BAZEL_FLAGS:-}

join() { local IFS=,; echo "$*"; }
flags=(--top "$top" --set lhd.jobs="$THREADS" --set synth.place=true --set synth.liberty="$lib"
       --set synth.lef="$(join "${lefs[@]}")" --set synth.sdc="$D/constraint.sdc"
       --set synth.wire_rc="$P/setRC.tcl" --set synth.place.tracks="$tracks"
       --set synth.place.utilization="$util" --set synth.drop_init=true)
[ -n "${halo:-}" ] && flags+=(--set synth.place.halo="$halo")
# liteeth: the ASIC patch comments out the $readmemh ROM inits (mem_6b5b ...), leaving ROM bits with
# no defined value; tie them low, as an ASIC flow does for undefined bits.
[ -n "${unk:-}" ] && flags+=(--set synth.place.unknown_const="$unk")
# shellcheck disable=SC2086
"$LHD" synth "${rtl[@]}" "${flags[@]}" --workdir "$run/livehd" --emit-dir "def:$run/handoff" \
  --emit "verilog:$run/netlist.v" --result-json "$run/result.json" ${EXTRA:-} \
  -- -D SYNTHESIS --ignore-assertions --compat=vcs --timescale=1ns/1ps ${defs:-} 2>&1 | tee "$run/lhd.log"
