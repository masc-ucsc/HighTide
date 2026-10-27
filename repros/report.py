#!/usr/bin/env python3
"""Render WS/*/result.json into repros/vslivehd-llmhdl.html (uncommitted; see .git/info/exclude)."""
from __future__ import annotations

import html
import json
import math
import platform
import socket
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import vsl  # noqa: E402

OUT = Path(__file__).resolve().parent / "vslivehd-llmhdl.html"
esc = html.escape


def num(v, digits=1, unit=""):
    if v is None:
        return "—"
    if isinstance(v, float) and (math.isnan(v) or abs(v) > 1e20):
        return "n/a"
    s = f"{v:,.{digits}f}"
    return s + unit


def secs(v):
    if v is None:
        return "—"
    if v >= 3600:
        return f"{v / 3600:.2f} h"
    if v >= 100:
        return f"{v:,.0f} s"
    return f"{v:,.1f} s"


def ratio(a, b):
    """a / b as a speed-up style factor; None when either side is missing or zero."""
    if a is None or b is None or not b:
        return None
    return a / b


def geomean(vals):
    vals = [v for v in vals if v and v > 0]
    return math.exp(sum(math.log(v) for v in vals) / len(vals)) if vals else None


# ----------------------------------------------------------------------- data
def load() -> dict:
    """Archived results (repros/data) first, then the live workspace on top when it is newer."""
    out, mtime = {}, {}
    for f in sorted([*(Path(__file__).resolve().parent / "data").glob("*/result.json"), *vsl.WS.glob("*/result.json")]):
        r = json.loads(f.read_text())
        if r["design"] not in out or f.stat().st_mtime >= mtime[r["design"]]:
            out[r["design"]], mtime[r["design"]] = r, f.stat().st_mtime
    return out


def a_groups(r):
    """OpenROAD flow: wall and CPU seconds per group (Yosys without ABC, ABC, floorplan, ...)."""
    A = r.get("A", {})
    steps = A.get("steps", {})
    if not steps or "place_done" not in steps or steps["place_done"]["status"] != "ok":
        return None
    abc = A.get("abc", {"wall_s": 0, "cpu_s": 0})

    def s(names, key):
        return sum(steps[n][key] or 0 for n in names if n in steps)

    g = {}
    for key in ("wall_s", "cpu_s"):
        y = s(("yosys_read", "yosys_synth"), key)
        a = abc["wall_s"] if key == "wall_s" else abc["cpu_s"]
        g[key] = {
            "yosys": max(y - a, 0), "abc": a,
            "floorplan": s(("netlist_import", "floorplan", "macro_place", "tapcell", "pdn"), key),
            "gp": s(("gp_skip_io", "global_place"), key), "io": s(("io_place",), key),
            "resize": s(("resize",), key), "dp": s(("detail_place", "place_done"), key)}
        g[key]["total"] = sum(g[key].values())
    g["ipc"] = ipc_total(steps.values())
    g["rss"] = max((v["rss_mib"] for v in steps.values()), default=None)
    return g


def ipc_total(recs):
    i = c = 0.0
    for v in recs:
        i += v.get("instructions") or 0
        c += v.get("cycles") or 0
    return i / c if c else None


def b_groups(r):
    B = r.get("B", {})
    if not B.get("phases") or B.get("status") != "ok":
        return None
    p, run = B["phases"], B["run"]
    wall_b = run["wall_s"] + B.get("compile_front_s", 0)
    place = min(p["place_s"], max(wall_b - p["compile_s"] - p["synth_s"] - p["sta_s"], 0))  # phases can overlap on big runs
    other = max(wall_b - (p["compile_s"] + p["synth_s"] + place + p["sta_s"]), 0)
    return {"compile": p["compile_s"], "synth": p["synth_s"], "place": place, "sta": p["sta_s"],
            "other": other, "wall": run["wall_s"] + B.get("compile_front_s", 0), "cpu": run["cpu_s"],
            "ipc": run["ipc"], "rss": run["rss_mib"]}


def s_groups(r):
    S = r.get("S", {})
    if S.get("status") != "ok" or not S.get("phases"):
        return None
    p = S["phases"]
    return {"compile": p["compile_s"], "synth": p["synth_s"], "wall": S["run"]["wall_s"] + S.get("compile_front_s", 0),
            "cpu": S["run"]["cpu_s"], "ipc": S["run"]["ipc"], "rss": S["run"]["rss_mib"]}


def d_groups(r):
    D = r.get("D", {})
    steps = D.get("steps", {})
    if not D.get("score"):
        return None
    wall = sum(v["wall_s"] for v in steps.values())
    cpu = sum(v["cpu_s"] or 0 for v in steps.values())
    return {"wall": wall, "cpu": cpu, "ipc": ipc_total(steps.values())}


def c_groups(r):
    C = r.get("C", {})
    if not C.get("score"):
        return None
    pl, rp = C["place"], C["repair"]
    return {"place_wall": pl["wall_s"], "repair_wall": rp["wall_s"], "wall": pl["wall_s"] + rp["wall_s"],
            "cpu": (pl["cpu_s"] or 0) + (rp["cpu_s"] or 0), "ipc": ipc_total([pl, rp])}


def gp_state(r):
    """LiveHD's own placement convergence flags (B: rep/placement.json, C: livehd_place/qor.json)."""
    safe = r["design"].replace("/", "__")
    out = {}
    for tag, rel in (("B", "B/rep/placement.json"), ("C", "C/livehd_place/qor.json")):
        f = vsl.WS / safe / rel
        if not f.exists():  # fall back to the archive
            sub = "rep/placement.json" if tag == "B" else "livehd_place/qor.json"
            f = Path(__file__).resolve().parent / "data" / safe / "livehd" / tag / sub
        if f.exists():
            try:
                q = json.loads(f.read_text())
                out[tag] = {"converged": q.get("gp_converged"), "overflow": q.get("gp_overflow"),
                            "hpwl": q.get("hpwl_um"), "legal": q.get("legal")}
            except Exception:
                pass
    return out


def err(r, k):
    e = r.get(k, {}).get("error")
    return e.split("\n")[0][:160] if e else None


# ------------------------------------------------------------------- rendering
CSS = """
:root{--bg:#fff;--fg:#1b1f24;--mut:#59636e;--line:#d0d7de;--card:#f6f8fa;--good:#1a7f37;--bad:#cf222e;
--c1:#4e79a7;--c2:#f28e2b;--c3:#76b7b2;--c4:#59a14f;--c5:#edc948;--c6:#b07aa1;--c7:#e0707a;--c8:#9aa3ab}
@media (prefers-color-scheme:dark){:root{--bg:#0d1117;--fg:#e6edf3;--mut:#9198a1;--line:#30363d;--card:#161b22;
--good:#3fb950;--bad:#f85149}}
body{font:14px/1.45 system-ui,-apple-system,Segoe UI,sans-serif;background:var(--bg);color:var(--fg);margin:0;padding:24px 16px}
main{max-width:1280px;margin:0 auto}h1{font-size:24px;margin:0 0 4px}h2{font-size:18px;margin:34px 0 8px;border-bottom:1px solid var(--line);padding-bottom:4px}
h3{font-size:15px;margin:20px 0 6px}p,li{max-width:980px}.mut{color:var(--mut)}.scroll{overflow-x:auto}
table{border-collapse:collapse;margin:8px 0;font-variant-numeric:tabular-nums}th,td{padding:4px 9px;border:1px solid var(--line);text-align:right;white-space:nowrap}
th{background:var(--card);font-weight:600}td.l,th.l{text-align:left}tr.sum td{font-weight:600;background:var(--card)}
.good{color:var(--good)}.bad{color:var(--bad)}.err{color:var(--bad);font-size:12px;white-space:normal;max-width:360px;text-align:left}
.bar{display:flex;height:14px;min-width:260px;background:var(--card);border:1px solid var(--line)}.bar i{display:block;height:100%}
.leg span{display:inline-block;margin-right:14px}.leg b{display:inline-block;width:11px;height:11px;margin-right:4px;vertical-align:-1px}
details{margin:6px 0}summary{cursor:pointer;font-weight:600}code,pre{background:var(--card);padding:1px 4px;border-radius:3px;font-size:12.5px}
pre{padding:8px;overflow-x:auto}
"""

SEG = {"yosys": "--c1", "abc": "--c2", "floorplan": "--c3", "gp": "--c4", "io": "--c5", "resize": "--c6", "dp": "--c7",
       "compile": "--c1", "synth": "--c2", "place": "--c4", "sta": "--c8", "other": "--c8"}


def bar(parts: dict, scale: float, title: str) -> str:
    segs = []
    for k, v in parts.items():
        if v and scale:
            segs.append(f'<i style="width:{100 * v / scale:.2f}%;background:var({SEG[k]})" title="{esc(k)} {v:.1f} s"></i>')
    return f'<div class="bar" title="{esc(title)}">' + "".join(segs) + "</div>"


def fmt_q(s, key, digits=1):
    return num(s.get(key), digits) if s else "—"


def qor_cells(s):
    if not s:
        return ["—"] * 6
    return [num(s["instance_area_um2"], 1), num(s["logical_cells"], 0), num(s["setup_wns_ps"], 1),
            num(s["setup_tns_ps"], 0), num(s["hpwl_um"], 0), num(s.get("power_mw"), 4)]


def delta(new, old, lower_better=True, digits=1, pct=True):
    if new is None or old in (None, 0):
        return "—"
    d = (new - old) / abs(old) * 100
    cls = "good" if (d < 0) == lower_better and abs(d) > 0.05 else ("bad" if abs(d) > 0.05 else "")
    return f'<span class="{cls}">{d:+.{digits}f}%</span>'


def slack_delta(new, old):
    if new is None or old is None:
        return "—"
    d = new - old
    cls = "good" if d > 0.5 else ("bad" if d < -0.5 else "")
    return f'<span class="{cls}">{d:+.1f} ps</span>'


def render() -> str:
    data = load()
    man = json.loads((vsl.BIN / "manifest.json").read_text()) if (vsl.BIN / "manifest.json").exists() else {}
    keys = sorted(data, key=lambda k: data[k].get("A", {}).get("score", {}).get("logical_cells") or 0)
    h = [f"<!doctype html><html lang=en><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
         f"<title>LiveHD vs OpenROAD pre-CTS (HighTide asap7)</title><style>{CSS}</style><main>"]
    h.append("<h1>LiveHD vs OpenROAD, pre-CTS, HighTide asap7</h1>")
    h.append(f'<p class="mut">host {esc(socket.gethostname())} · {esc(platform.platform())} · generated '
             f"{time.strftime('%Y-%m-%d %H:%M')} · {len(data)} designs · one run per design and flow · not committed</p>")

    # ---------------------------------------------------------------- setup
    h.append("<h2>Method</h2><ul>")
    h.append("<li><b>A · OpenROAD reference</b>: HighTide ORFS flow from RTL (Yosys 0.64 + yosys-slang, ABC speed script) through "
             "<code>3_place.odb</code> (floorplan, tapcell, PDN, global placement, IO placement, <code>repair_design</code> resize, "
             "detail placement/legalization). Each ORFS step is a separate measured <code>make</code>; the per-step sum includes "
             "OpenROAD process start and ODB load/store. ABC is timed by wrapping <code>yosys-abc</code>.</li>")
    h.append("<li><b>B · LiveHD</b>: one <code>lhd synth</code> invocation (own slang front end, color + ABC technology mapping, native "
             "DREAMPlace-based timing-driven placer with resize/repair, legal DEF). Breakdown from the tool's sequential "
             "<code>phases</code>: <i>compile</i> = everything before <code>pass.color</code>, <i>synth</i> = color + ABC, "
             "<i>placer</i> = all <code>pass.place*</code>, <i>sta</i> = the final OpenTimer report. Nested OpenTimer callbacks are not double counted.</li>")
    h.append("<li><b>S · LiveHD synthesis only</b>: <code>lhd synth</code> without placement (its own slang front end, color + ABC technology mapping, no placement); its mapped netlist and its compile/synth times are used for D and for the synthesis comparison, so the synthesis effect is measurable even where LiveHD placement fails or times out.</li>"
             "<li><b>D · LiveHD netlist → OpenROAD placer</b>: S's mapped Verilog goes through the same ORFS floorplan/place steps "
             "(<code>SYNTH_NETLIST_FILES</code>). Compared with A this isolates the <i>synthesis</i> (LiveHD ABC vs Yosys+ABC).</li>")
    h.append("<li><b>C · Yosys netlist → LiveHD placer</b>: A's netlist, floorplan, macros and IO placement (<code>3_2_place_iop</code>) with "
             "standard-cell positions removed, placed by LiveHD's native placer and then its pre-CTS repair "
             "(<code>physical_repair</code>, the policy in <code>tools/vslivehd/run.py</code>). Compared with A this isolates the <i>placer</i>.</li>")
    h.append("<li><b>Scoring</b>: the same OpenSTA/OpenROAD script for every result (<code>repros/score.tcl</code>): the Liberty files "
             "the OpenROAD flow read, the design's HighTide SDC, ASAP7 <code>setRC.tcl</code> with <code>estimate_parasitics -placement</code>, "
             "ideal clocks. Reset ports are the SDC false-path sources; clock nets and reset nets (including buffer trees below them) "
             "are excluded from HPWL. Area is logic-cell area (no tap/fill). Power is OpenSTA <code>report_power</code> with default activity. "
             "Scoring time is excluded from every flow time.</li>")
    h.append(f"<li><b>Resources</b>: each run is pinned with <code>taskset</code> to its own {vsl.THREADS} hardware threads (4 physical cores + SMT siblings; "
             f"slots never overlap), at most {len(vsl.SLOTS)} runs at once, tree-RSS limit {vsl.MEM_GIB} GiB per run. OpenROAD uses "
             f"{vsl.THREADS} threads; LiveHD is single-threaded (pinned to one hardware thread). Wall and CPU (user+sys incl. children) from GNU time; "
             "IPC = instructions/cycles from <code>perf stat</code> over the same process tree.</li></ul>")
    h.append("<li><b>RTL used</b>: the HighTide RTL as built by bazel, except <code>eyeriss</code> and <code>snitch_cluster</code>, which use fixed RTL for both flows "
             "(<code>repros/rtl_fixes/</code>): eyeriss regenerated from pristine upstream with the repository's two patches and the current banked-wrapper generator; "
             "snitch_cluster with <code>patches/snitch-cluster-fp-inst-comb-loop.patch</code> (breaks a real combinational loop that Yosys <code>check</code> reported 660 times). "
             "Old results of those two designs: <code>data/_superseded/</code>. LiveHD rows are from the rebuilt LiveHD described in <code>issues.md</code> (update 2026-10-27).</li>")
    if man:
        h.append("<p class='mut'>Frozen tools: " + " · ".join(f"{k} {esc(str(v)[:12])}" for k, v in man.items()) + "</p>")

    # ---------------------------------------------------------------- OpenROAD only
    h.append("<h2>0. OpenROAD flow, all designs (smallest to largest area)</h2><p>Yosys+ABC then OpenROAD floorplan, global placement, IO placement, "
             "resize and detail placement, 8 threads, one run per design. Area = logic cells plus macros after placement (no tap/fill). "
             "Wall includes OpenROAD process start and ODB load/store for every step.</p><div class=scroll><table><tr><th>#</th><th class=l>design</th>"
             "<th>area µm²</th><th>cells</th><th>macros</th><th>Yosys+ABC</th><th>(ABC)</th><th>OpenROAD floorplan→place</th><th>total wall</th>"
             "<th>total CPU</th><th>IPC</th><th>peak RSS GiB</th><th>WNS ps</th><th>TNS ps</th><th>HPWL µm</th></tr>")
    orows, ofail = [], []
    for k, r in data.items():
        ga = a_groups(r)
        sa = r.get("A", {}).get("score")
        if not ga or not sa:
            ofail.append((k, err(r, "A") or "not run"))
            continue
        w, c = ga["wall_s"], ga["cpu_s"]
        orows.append((sa["instance_area_um2"], k, sa, w, c, ga))
    for i, (area, k, sa, w, c, ga) in enumerate(sorted(orows, key=lambda x: x[0]), 1):
        h.append(f"<tr><td>{i}</td><td class=l>{esc(k)}</td><td>{num(area, 0)}</td><td>{num(sa['logical_cells'], 0)}</td><td>{sa['macros']}</td>"
                 f"<td>{secs(w['yosys'] + w['abc'])}</td><td>{secs(w['abc'])}</td><td>{secs(w['total'] - w['yosys'] - w['abc'])}</td>"
                 f"<td>{secs(w['total'])}</td><td>{secs(c['total'])}</td><td>{num(ga['ipc'], 2)}</td><td>{num((ga['rss'] or 0) / 1024, 1)}</td>"
                 f"<td>{num(sa['setup_wns_ps'], 0)}</td><td>{num(sa['setup_tns_ps'], 0)}</td><td>{num(sa['hpwl_um'], 0)}</td></tr>")
    for k, e in ofail:
        h.append(f"<tr><td></td><td class=l>{esc(k)}</td><td colspan=13 class=err>{esc(e)}</td></tr>")
    h.append("</table></div>")

    # ---------------------------------------------------------------- summary table
    h.append("<h2>1. Whole flow: LiveHD (B) vs OpenROAD (A)</h2>")
    h.append("<p>Time is RTL → legal pre-CTS placement. Δ columns are B relative to A (green = LiveHD better). "
             "Speed-up = A time / B time.</p><div class='scroll'><table><tr><th class=l rowspan=2>design</th><th rowspan=2>cells (A)</th>"
             "<th colspan=4>wall</th><th colspan=3>CPU</th><th colspan=4>QoR Δ (B vs A)</th></tr><tr>"
             "<th>A</th><th>B</th><th>speed-up</th><th>RSS A / B (MiB)</th><th>A</th><th>B</th><th>ratio</th>"
             "<th>area</th><th>WNS</th><th>TNS</th><th>HPWL</th></tr>")
    sp_w, sp_c = [], []
    for k in keys:
        r = data[k]
        ga, gb = a_groups(r), b_groups(r)
        sa, sb = r.get("A", {}).get("score"), r.get("B", {}).get("score")
        aw = ga["wall_s"]["total"] if ga else None
        ac = ga["cpu_s"]["total"] if ga else None
        bw = gb["wall"] if gb else None
        bc = gb["cpu"] if gb else None
        s_w, s_c = ratio(aw, bw), ratio(ac, bc)
        if s_w:
            sp_w.append(s_w)
        if s_c:
            sp_c.append(s_c)
        note = ""
        if not ga:
            note += f' <span class=err>A: {esc(err(r, "A") or "not run")}</span>'
        if not gb:
            note += f' <span class=err>B: {esc(err(r, "B") or "not run")}</span>'
        h.append(f"<tr><td class=l>{esc(k)}{note}</td><td>{num(sa['logical_cells'], 0) if sa else '—'}</td>"
                 f"<td>{secs(aw)}</td><td>{secs(bw)}</td><td>{num(s_w, 2)}×</td>"
                 f"<td>{num(ga['rss'], 0) if ga else '—'} / {num(gb['rss'], 0) if gb else '—'}</td>"
                 f"<td>{secs(ac)}</td><td>{secs(bc)}</td><td>{num(s_c, 2)}×</td>"
                 f"<td>{delta(sb and sb['instance_area_um2'], sa and sa['instance_area_um2'])}</td>"
                 f"<td>{slack_delta(sb and sb['setup_wns_ps'], sa and sa['setup_wns_ps'])}</td>"
                 f"<td>{slack_delta(sb and sb['setup_tns_ps'], sa and sa['setup_tns_ps'])}</td>"
                 f"<td>{delta(sb and sb['hpwl_um'], sa and sa['hpwl_um'])}</td></tr>")
    h.append(f"<tr class=sum><td class=l>geomean (designs with both)</td><td></td><td></td><td></td><td>{num(geomean(sp_w), 2)}×</td>"
             f"<td></td><td></td><td></td><td>{num(geomean(sp_c), 2)}×</td><td></td><td></td><td></td><td></td></tr></table></div>")

    # ---------------------------------------------------------------- breakdown
    h.append("<h2>2. Runtime breakdown (wall seconds)</h2><div class=leg>"
             + "".join(f'<span><b style="background:var({SEG[k]})"></b>{esc(n)}</span>' for k, n in [
                 ("yosys", "Yosys (read+synth, no ABC)"), ("abc", "ABC"), ("floorplan", "floorplan+tap+PDN"),
                 ("gp", "global place"), ("io", "IO place"), ("resize", "resize"), ("dp", "legalize+detail place"),
                 ("compile", "LiveHD compile"), ("synth", "LiveHD synth (color+ABC)"), ("place", "LiveHD placer"), ("sta", "LiveHD final STA/other")])
             + "</div>")
    h.append("<div class=scroll><table><tr><th class=l rowspan=2>design</th><th colspan=8>A · Yosys+ABC → OpenROAD</th>"
             "<th colspan=5>B · LiveHD</th><th rowspan=2 class=l>bars (A above, B below; same scale per design)</th></tr><tr>"
             "<th>Yosys</th><th>ABC</th><th>floorplan</th><th>global pl.</th><th>IO pl.</th><th>resize</th><th>legal+detail</th><th>total</th>"
             "<th>compile</th><th>synth</th><th>placer</th><th>sta/other</th><th>total</th></tr>")
    for k in keys:
        r = data[k]
        ga, gb, gs = a_groups(r), b_groups(r), s_groups(r)
        w = ga["wall_s"] if ga else {}
        row = f"<tr><td class=l>{esc(k)}</td>"
        for n in ("yosys", "abc", "floorplan", "gp", "io", "resize", "dp", "total"):
            row += f"<td>{secs(w.get(n))}</td>"
        for n in ("compile", "synth"):
            src = gb or gs
            row += f"<td>{secs(src[n]) if src else '—'}</td>"
        row += f"<td>{secs(gb['place']) if gb else '—'}</td>"
        row += f"<td>{secs(gb['sta'] + gb['other']) if gb else '—'}</td><td>{secs(gb['wall']) if gb else '—'}</td>"
        scale = max([w.get("total") or 0, gb["wall"] if gb else 0])
        parts_a = {n: w.get(n, 0) for n in ("yosys", "abc", "floorplan", "gp", "io", "resize", "dp")}
        parts_b = {"compile": gb["compile"], "synth": gb["synth"], "place": gb["place"], "sta": gb["sta"] + gb["other"]} if gb else {}
        row += f"<td class=l>{bar(parts_a, scale, 'A')}{bar(parts_b, scale, 'B')}</td></tr>"
        h.append(row)
    h.append("</table></div>")

    # CPU / IPC
    h.append("<h3>CPU time and IPC</h3><div class=scroll><table><tr><th class=l>design</th><th>A CPU</th><th>A Yosys+ABC CPU</th>"
             "<th>A OpenROAD CPU</th><th>A IPC</th><th>B CPU</th><th>B IPC</th><th>C CPU</th><th>C IPC</th><th>D CPU</th><th>D IPC</th></tr>")
    for k in keys:
        r = data[k]
        ga, gb, gc, gd = a_groups(r), b_groups(r), c_groups(r), d_groups(r)
        cs = ga["cpu_s"] if ga else {}
        h.append(f"<tr><td class=l>{esc(k)}</td><td>{secs(cs.get('total'))}</td><td>{secs((cs.get('yosys') or 0) + (cs.get('abc') or 0)) if cs else '—'}</td>"
                 f"<td>{secs(cs['total'] - cs['yosys'] - cs['abc']) if cs else '—'}</td><td>{num(ga and ga['ipc'], 2)}</td>"
                 f"<td>{secs(gb and gb['cpu'])}</td><td>{num(gb and gb['ipc'], 2)}</td>"
                 f"<td>{secs(gc and gc['cpu'])}</td><td>{num(gc and gc['ipc'], 2)}</td>"
                 f"<td>{secs(gd and gd['cpu'])}</td><td>{num(gd and gd['ipc'], 2)}</td></tr>")
    h.append("</table></div>")

    # ---------------------------------------------------------------- 2x2
    h.append("<h2>3. Where the difference comes from: synthesis × placer</h2>"
             "<p>Four combinations on the same RTL, same floorplan utilization/density and the same scoring. "
             "<b>Synthesis</b> = Yosys+ABC (Y) or LiveHD (L); <b>placer</b> = OpenROAD (O) or LiveHD (L). "
             "Effect of LiveHD synthesis = <b>L·O vs Y·O</b> (D vs A); effect of LiveHD placer = <b>Y·L vs Y·O</b> (C vs A) "
             "and <b>L·L vs L·O</b> (B vs D). Note: C reuses OpenROAD's floorplan/IO and starts from its netlist; B and D differ in the "
             "floorplan because the netlist area differs; B's DEF has no tap cells.</p>")
    h.append("<div class=scroll><table><tr><th class=l rowspan=2>design</th><th rowspan=2>combination</th><th rowspan=2>synthesis time</th>"
             "<th rowspan=2>place time</th><th colspan=6>QoR (common OpenSTA)</th></tr><tr><th>area µm²</th><th>cells</th><th>WNS ps</th>"
             "<th>TNS ps</th><th>HPWL µm</th><th>power mW</th></tr>")
    syn_ratio, plc_ratio_yo, plc_ratio_lo = [], [], []
    for k in keys:
        r = data[k]
        ga, gb, gc, gd, gs = a_groups(r), b_groups(r), c_groups(r), d_groups(r), s_groups(r)
        A, B, C, D = (r.get(x, {}) for x in "ABCD")
        syn_y = (ga["wall_s"]["yosys"] + ga["wall_s"]["abc"]) if ga else None
        syn_l = (gs["compile"] + gs["synth"]) if gs else ((gb["compile"] + gb["synth"]) if gb else None)
        plc_o = (ga["wall_s"]["total"] - ga["wall_s"]["yosys"] - ga["wall_s"]["abc"]) if ga else None
        plc_o_d = None
        if gd:
            plc_o_d = gd["wall"]
        plc_l = gb["place"] if gb else None
        rows = [("Y·O  (A: Yosys+ABC → OpenROAD)", syn_y, plc_o, A.get("score")),
                ("L·O  (D: LiveHD → OpenROAD)", syn_l, plc_o_d, D.get("score")),
                ("Y·L  (C: Yosys+ABC → LiveHD placer)", syn_y, gc["wall"] if gc else None, C.get("score")),
                ("L·L  (B: LiveHD → LiveHD placer)", syn_l, plc_l, B.get("score"))]
        if syn_y and syn_l:
            syn_ratio.append(syn_y / syn_l)
        if plc_o and gc and gc["wall"]:
            plc_ratio_yo.append(plc_o / gc["wall"])
        if plc_o_d and plc_l:
            plc_ratio_lo.append(plc_o_d / plc_l)
        for i, (name, st, pt, sc) in enumerate(rows):
            first = f"<td class=l rowspan=4>{esc(k)}</td>" if i == 0 else ""
            msg = ""
            if not sc:
                msg = f" <span class=err>{esc(err(r, 'ABDC'[[0, 2, 3, 1][i]]) or 'not run')}</span>"
            h.append(f"<tr>{first}<td class=l>{name}{msg}</td><td>{secs(st)}</td><td>{secs(pt)}</td>"
                     + "".join(f"<td>{c}</td>" for c in qor_cells(sc)) + "</tr>")
    h.append(f"<tr class=sum><td class=l colspan=2>geomean time ratios</td><td colspan=2>synthesis Y/L {num(geomean(syn_ratio), 2)}× · "
             f"placer O/L on Y netlist {num(geomean(plc_ratio_yo), 2)}× · O/L on L netlist {num(geomean(plc_ratio_lo), 2)}×</td><td colspan=6></td></tr></table></div>")
    h.append("<p class=mut>Times: synthesis = Yosys read+synth (incl. ABC) or LiveHD compile+synth; place time = OpenROAD floorplan→legal placement "
             "(incl. ODB import/stores) or LiveHD placer (+ repair for C, B's <code>pass.place*</code>).</p>")

    h.append("<h3>LiveHD global-placement convergence</h3><p>Reported by LiveHD itself: whether global placement reached its overflow target "
             "before the iteration cap, and whether the final placement is legal. Not converged means HPWL is not at its best.</p>"
             "<div class=scroll><table><tr><th class=l>design</th><th>B converged</th><th>B overflow</th><th>B legal</th>"
             "<th>C converged</th><th>C overflow</th><th>C legal</th></tr>")
    for k in keys:
        g = gp_state(data[k])
        row = f"<tr><td class=l>{esc(k)}</td>"
        for t in "BC":
            q = g.get(t)
            row += (f"<td>{'yes' if q['converged'] else 'no'}</td><td>{num(q['overflow'], 3)}</td><td>{'yes' if q['legal'] else 'no'}</td>"
                    if q else "<td>—</td><td>—</td><td>—</td>")
        h.append(row + "</tr>")
    h.append("</table></div>")

    # QoR deltas for the two isolated effects
    h.append("<h3>Isolated effects (relative change)</h3><div class=scroll><table><tr><th class=l rowspan=2>design</th>"
             "<th colspan=4>LiveHD synthesis vs Yosys+ABC (L·O vs Y·O)</th><th colspan=4>LiveHD placer vs OpenROAD on Y netlist (Y·L vs Y·O)</th>"
             "<th colspan=4>LiveHD placer vs OpenROAD on L netlist (L·L vs L·O)</th></tr><tr>" + "<th>area</th><th>WNS</th><th>TNS</th><th>HPWL</th>" * 3 + "</tr>")

    def quad(new, old):
        if not new or not old:
            return "<td>—</td>" * 4
        return (f"<td>{delta(new['instance_area_um2'], old['instance_area_um2'])}</td>"
                f"<td>{slack_delta(new['setup_wns_ps'], old['setup_wns_ps'])}</td>"
                f"<td>{slack_delta(new['setup_tns_ps'], old['setup_tns_ps'])}</td>"
                f"<td>{delta(new['hpwl_um'], old['hpwl_um'])}</td>")
    for k in keys:
        r = data[k]
        A, B, C, D = (r.get(x, {}).get("score") for x in "ABCD")
        h.append(f"<tr><td class=l>{esc(k)}</td>{quad(D, A)}{quad(C, A)}{quad(B, D)}</tr>")
    h.append("</table></div>")

    # ---------------------------------------------------------------- old vs new LiveHD build
    old = {}
    for f in (Path(__file__).resolve().parent / "data").glob("*/result_livehd_old.json"):
        r0 = json.loads(f.read_text())
        old[r0["design"]] = r0
    if old:
        h.append("<h2>4. LiveHD build comparison: first benchmark build vs rebuilt local tree</h2><p>Same OpenROAD reference, same scoring, same single-thread LiveHD settings. "
                 "Old build = sha256 4b7d0c48… (livehd 8e017a011); new build: see <code>data/livehd_build_b.json</code>. "
                 "Blank = that build produced no result for the flow (failure or limit).</p><div class=scroll><table><tr><th class=l rowspan=2>design</th>"
                 "<th colspan=3>full flow wall (B)</th><th colspan=3>placer time (B)</th><th colspan=3>HPWL µm (B)</th><th colspan=3>WNS ps (B)</th></tr><tr>"
                 + "<th>old</th><th>new</th><th>OpenROAD</th>" * 4 + "</tr>")
        for k in keys:
            n, o = data[k], old.get(k)
            ga = a_groups(n)
            sa = n.get("A", {}).get("score")
            def pick(r, f):
                try:
                    return f(r)
                except (KeyError, TypeError):
                    return None
            ow = pick(o, lambda r: b_groups(r)["wall"]) if o else None
            nw = pick(n, lambda r: b_groups(r)["wall"])
            op = pick(o, lambda r: b_groups(r)["place"]) if o else None
            np_ = pick(n, lambda r: b_groups(r)["place"])
            oh = pick(o, lambda r: r["B"]["score"]["hpwl_um"]) if o else None
            nh = pick(n, lambda r: r["B"]["score"]["hpwl_um"])
            owns = pick(o, lambda r: r["B"]["score"]["setup_wns_ps"]) if o else None
            nwns = pick(n, lambda r: r["B"]["score"]["setup_wns_ps"])
            h.append(f"<tr><td class=l>{esc(k)}</td><td>{secs(ow)}</td><td>{secs(nw)}</td><td>{secs(ga['wall_s']['total']) if ga else '—'}</td>"
                     f"<td>{secs(op)}</td><td>{secs(np_)}</td><td>{secs(ga['wall_s']['total'] - ga['wall_s']['yosys'] - ga['wall_s']['abc']) if ga else '—'}</td>"
                     f"<td>{num(oh, 0)}</td><td>{num(nh, 0)}</td><td>{num(sa['hpwl_um'], 0) if sa else '—'}</td>"
                     f"<td>{num(owns, 0)}</td><td>{num(nwns, 0)}</td><td>{num(sa['setup_wns_ps'], 0) if sa else '—'}</td></tr>")
        h.append("</table></div>")

    # ---------------------------------------------------------------- failures
    h.append("<h2>5. Incomplete runs</h2>")
    bad = []
    for k in keys:
        for f in "ASBDC":
            e = err(data[k], f)
            if e or (f in data[k] and not data[k][f].get("score") and not e):
                bad.append((k, f, e or "no score"))
    if bad:
        h.append("<table><tr><th class=l>design</th><th>flow</th><th class=l>reason</th></tr>"
                 + "".join(f"<tr><td class=l>{esc(k)}</td><td>{f}</td><td class=err>{esc(e)}</td></tr>" for k, f, e in bad) + "</table>")
    else:
        h.append("<p>None.</p>")

    # ---------------------------------------------------------------- per-design
    h.append("<h2>6. Per-step measurements</h2>")
    for k in keys:
        r = data[k]
        h.append(f"<details><summary>{esc(k)}</summary>")
        for f, title in (("A", "A · OpenROAD"), ("D", "D · LiveHD netlist → OpenROAD")):
            steps = r.get(f, {}).get("steps")
            if steps:
                tt = r[f].get("tool", {})
                h.append(f"<h3>{title}</h3><table><tr><th class=l>step</th><th>wall</th><th>CPU</th><th>in-tool elapsed</th><th>IPC</th><th>RSS MiB</th></tr>")
                for n, v in steps.items():
                    t = tt.get(n, {})
                    h.append(f"<tr><td class=l>{n}</td><td>{secs(v['wall_s'])}</td><td>{secs(v['cpu_s'])}</td>"
                             f"<td>{secs(t.get('elapsed_s'))}</td><td>{num(v['ipc'], 2)}</td><td>{num(v['rss_mib'], 0)}</td></tr>")
                h.append("</table>")
        if r.get("A", {}).get("abc"):
            h.append(f"<p class=mut>ABC runs: {json.dumps(r['A']['abc'])} · Yosys: {esc(str(r['A'].get('yosys')))}</p>")
        pd = r.get("B", {}).get("phases", {}).get("place_detail_s")
        if pd:
            h.append("<h3>B · LiveHD placer phases (s)</h3><table><tr><th class=l>phase</th><th>seconds</th></tr>"
                     + "".join(f"<tr><td class=l>{esc(n)}</td><td>{v:.2f}</td></tr>" for n, v in pd.items()) + "</table>")
        if r.get("C", {}).get("place") and r["C"].get("repair"):
            c = r["C"]
            h.append(f"<h3>C · LiveHD placer on Yosys netlist</h3><p>place {secs(c['place']['wall_s'])} (IPC {num(c['place']['ipc'], 2)}), "
                     f"repair {secs(c['repair']['wall_s'])} (IPC {num(c['repair']['ipc'], 2)}); after placement only: "
                     + (f"WNS {num(c['score_place']['setup_wns_ps'], 1)} ps, HPWL {num(c['score_place']['hpwl_um'], 0)} µm" if c.get('score_place') else '—') + "</p>")
        h.append("</details>")
    h.append("</main>")
    return "".join(h)


if __name__ == "__main__":
    OUT.write_text(render())
    print(OUT)
