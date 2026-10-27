# Common pre-CTS scorer: OpenSTA/OpenROAD on an ODB (OpenROAD flow) or a DEF (LiveHD).
# Same libraries, SDC, RC (setRC.tcl + estimate_parasitics -placement) and ideal clocks for
# every flow.  HPWL excludes clock and reset nets (reset ports are the SDC false-path
# sources); the buffer trees OpenROAD/LiveHD hang under them are excluded as well.
#   SCORE_INPUT SCORE_OUT SDC_FILE LIB_FILES SET_RC_TCL RESET_PORTS
#   TECH_LEF SC_LEF ADDITIONAL_LEFS   (DEF input only)
set begin [clock milliseconds]
foreach lib $::env(LIB_FILES) {read_liberty $lib}
set input $::env(SCORE_INPUT)
if {[file extension $input] eq ".odb"} {
  read_db $input
} else {
  read_lef $::env(TECH_LEF)
  read_lef $::env(SC_LEF)
  foreach lef $::env(ADDITIONAL_LEFS) {read_lef $lef}
  read_def $input
}
set_cmd_units -time ps -capacitance fF -resistance kOhm -power mW -distance um
read_sdc $::env(SDC_FILE)
source $::env(SET_RC_TCL)
estimate_parasitics -placement
set block [ord::get_db_block]
set out $::env(SCORE_OUT)
file mkdir $out
check_placement -verbose

# ---- nets excluded from HPWL: clock nets, reset-port nets and buffer/inverter trees below them
array set skip {}
foreach n [sta::find_all_clk_nets] {
  if {[catch {$n getName} nm]} {set nm [get_full_name $n]}
  set skip($nm) 1
}
set queue {}
foreach bt [$block getBTerms] {
  foreach p $::env(RESET_PORTS) {
    if {[string match $p [$bt getName]] && [$bt getNet] ne "NULL"} {lappend queue [$bt getNet]; break}
  }
}
while {[llength $queue]} {
  set net [lindex $queue 0]; set queue [lrange $queue 1 end]
  set nm [$net getName]
  if {[info exists skip($nm)]} {continue}
  set skip($nm) 1
  foreach it [$net getITerms] {
    if {![$it isInputSignal]} {continue}
    set inst [$it getInst]
    set master [$inst getMaster]
    set ins 0; set outs {}
    foreach t [$inst getITerms] {
      if {[$t isInputSignal]} {incr ins}
      if {[$t isOutputSignal] && [$t getNet] ne "NULL"} {lappend outs [$t getNet]}
    }
    if {$ins == 1 && ![$master isBlock]} {foreach o $outs {lappend queue $o}}
  }
}

set units [$block getDbUnitsPerMicron]
set hpwl 0.0; set hpwl_all 0.0; set measured 0; set skipped 0
foreach net [$block getNets] {
  if {[$net getSigType] in {POWER GROUND}} {continue}
  set xs {}; set ys {}
  foreach term [$net getITerms] {
    lassign [$term getAvgXY] ok x y
    if {$ok} {lappend xs $x; lappend ys $y}
  }
  foreach term [$net getBTerms] {
    lassign [$term getFirstPinLocation] ok x y
    if {$ok} {lappend xs $x; lappend ys $y}
  }
  if {[llength $xs] < 2} {continue}
  set w [expr {double([tcl::mathfunc::max {*}$xs]-[tcl::mathfunc::min {*}$xs]+[tcl::mathfunc::max {*}$ys]-[tcl::mathfunc::min {*}$ys])/$units}]
  set hpwl_all [expr {$hpwl_all+$w}]
  if {[info exists skip([$net getName])]} {incr skipped; continue}
  set hpwl [expr {$hpwl+$w}]; incr measured
}

set area 0.0; set macros 0; set logical 0; set physical 0; set macro_area 0.0
set seq 0; set bufs 0; set buf_area 0.0
foreach inst [$block getInsts] {
  set master [$inst getMaster]
  set phys [expr {[$master isFiller] || [$master isEndCap] || [$master getType] eq "CORE_WELLTAP"}]
  set a [expr {double([$master getWidth])*[$master getHeight]/($units*$units)}]
  if {$phys} {incr physical} else {incr logical; set area [expr {$area+$a}]}
  if {[$master isBlock]} {incr macros; set macro_area [expr {$macro_area+$a}]}
  if {!$phys && ![$master isBlock]} {
    set cell [get_lib_cells [$master getName]]
    if {[llength $cell] && ![catch {sta::LibertyCell_is_buffer [lindex $cell 0]} isbuf] && $isbuf} {
      incr bufs; set buf_area [expr {$buf_area+$a}]
    }
  }
}
report_units
report_clock_properties [all_clocks]
check_setup -verbose > $out/coverage.rpt
report_checks -path_delay max -group_path_count 10 -fields {slew cap input net fanout} -digits 6 -format full_clock_expanded > $out/setup_paths.rpt
report_checks -path_delay min -group_path_count 3 -digits 6 > $out/hold_paths.rpt
report_power > $out/power.rpt
set rect [$block getDieArea]; set core [$block getCoreArea]
set f [open $out/score.json w]
puts $f [format { {"hpwl_um":%.6f,"hpwl_all_nets_um":%.6f,"measured_nets":%d,"excluded_nets":%d,"setup_wns_ps":%.6f,"setup_tns_ps":%.6f,"hold_wns_ps":%.6f,"hold_tns_ps":%.6f,"instances":%d,"logical_cells":%d,"physical_cells":%d,"buffers":%d,"buffer_area_um2":%.4f,"macros":%d,"instance_area_um2":%.4f,"macro_area_um2":%.4f,"die_um":[%.4f,%.4f,%.4f,%.4f],"core_um":[%.4f,%.4f,%.4f,%.4f],"scoring_seconds":%.3f} } \
 $hpwl $hpwl_all $measured $skipped [sta::worst_slack -max] [sta::total_negative_slack -max] [sta::worst_slack -min] [sta::total_negative_slack -min] \
 [llength [$block getInsts]] $logical $physical $bufs $buf_area $macros $area $macro_area \
 [expr {double([$rect xMin])/$units}] [expr {double([$rect yMin])/$units}] [expr {double([$rect xMax])/$units}] [expr {double([$rect yMax])/$units}] \
 [expr {double([$core xMin])/$units}] [expr {double([$core yMin])/$units}] [expr {double([$core xMax])/$units}] [expr {double([$core yMax])/$units}] \
 [expr {([clock milliseconds]-$begin)/1000.0}]]
close $f
