#!/usr/bin/env python3
"""Sweep all HighTide asap7 designs: at most len(SLOTS) design runs at once, each pinned to its own
CPU slot (8 hardware threads) and capped at 64 GiB by the measurement wrapper.

  sweep.py [--only a,b] [--order size|name] [--flows ABDC]
"""
import argparse
import json
import subprocess
import sys
import threading
import queue
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import vsl  # noqa: E402


def size_key(d) -> int:
    odb = d.base / "3_place.odb"
    return odb.stat().st_size if odb.exists() else -1  # reference never finished in bazel: run last


def done(d, flows) -> bool:
    """A flow counts as done when the live workspace or the archive (repros/data) has it."""
    for f in (vsl.WS / d.safe / "result.json", Path(__file__).resolve().parent / "data" / d.safe / "result.json"):
        if f.exists():
            r = json.loads(f.read_text())
            if all(r.get(k, {}).get("done") for k in flows):
                return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    ap.add_argument("--order", default="size")
    ap.add_argument("--flows", default="ASBDC")
    ap.add_argument("--restore", action="store_true", help="LiveHD-only rerun from repros/data (OpenROAD reference reused)")
    ap.add_argument("--slot-ids", default=",".join(map(str, range(len(vsl.SLOTS)))))
    a = ap.parse_args()
    vsl.freeze()
    designs = vsl.discover()
    if a.only:
        keep = set(a.only.split(","))
        designs = [d for d in designs if d.key in keep or d.safe in keep]
    if a.order == "size":
        designs.sort(key=size_key, reverse=True)
    elif a.order == "small":
        designs.sort(key=size_key)
    else:
        designs.sort(key=lambda d: d.key)
    q: queue.Queue = queue.Queue()
    for d in designs:
        if a.restore or not done(d, a.flows):
            q.put(d)
    (vsl.WS / "logs").mkdir(exist_ok=True)

    def worker(slot: int) -> None:
        while True:
            try:
                d = q.get_nowait()
            except queue.Empty:
                return
            try:  # claim: several sweep processes may share one queue
                (vsl.WS / "claims").mkdir(exist_ok=True)
                (vsl.WS / "claims" / d.safe).mkdir()
            except FileExistsError:
                continue
            log = vsl.WS / "logs" / f"{d.safe}.log"
            print(f"[slot {slot}] start {d.key}", flush=True)
            with open(log, "w") as f:
                extra = ["--restore", "--redo", a.flows] if a.restore else []
                rc = subprocess.call([sys.executable, str(Path(__file__).with_name("run_design.py")), d.key,
                                      "--slot", str(slot), "--flows", a.flows, *extra], stdout=f, stderr=subprocess.STDOUT)
            print(f"[slot {slot}] finished {d.key} rc={rc}", flush=True)

    threads = [threading.Thread(target=worker, args=(int(s),)) for s in a.slot_ids.split(",")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
