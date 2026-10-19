#!/bin/bash
# Freeze the current opt lhd (binary + runfiles) as artifacts/lhdsweep/bin/<name>/lhd
# so rebuilds cannot change a measured sweep. Usage: freeze_lhd.sh NAME
set -e
NAME=$1
SRC=${LIVEHD:-/lscratch/renau/livehd}/bazel-bin/lhd
DST=/lscratch/renau/HighTide/artifacts/lhdsweep/bin/$NAME
[ -e "$DST" ] && { echo "$DST exists"; exit 1; }
mkdir -p "$DST"
cp -L "$SRC/lhd" "$DST/lhd"
cp -rL "$SRC/lhd.runfiles" "$DST/lhd.runfiles"
chmod -R u+rwX "$DST"
sha256sum "$DST/lhd" | tee "$DST/lhd.sha256"
