# Standalone pre-CTS scorer for the LiveHD-vs-OpenROAD sweeps.
#
# Same metric definitions as score.tcl (placement-estimated RC, ideal clocks,
# setup/hold worst and total negative slack, logical versus physical cells,
# instance area, HPWL), but it needs no ORFS flow scripts: every input is an
# explicit environment path, so one script scores an OpenROAD 3_place.odb and a
# LiveHD DEF with identical libraries, constraints and RC.
#
#   SCORE_INPUT      .odb (OpenROAD) or .def (LiveHD placement)
#   SCORE_OUT        output directory (score.json, coverage.rpt, ...)
#   SDC_FILE         constraints applied to both flows
#   LIB_FILES        space-separated Liberty files (the reference flow's list)
#   TECH_LEF SC_LEF  technology and standard-cell LEF (DEF input only)
#   ADDITIONAL_LEFS  space-separated macro LEFs (DEF input only; may be empty)
#   SET_RC_TCL       platform setRC.tcl (layer/wire RC)
set begin [clock milliseconds]
foreach lib $::env(LIB_FILES) {read_liberty $lib}
set input $::env(SCORE_INPUT)
if {[file extension $input] eq ".odb"} {
  read_db $input
} else {
  read_lef $::env(TECH_LEF)
  read_lef $::env(SC_LEF)
  if {[info exists ::env(ADDITIONAL_LEFS)]} {
    foreach lef $::env(ADDITIONAL_LEFS) {read_lef $lef}
  }
  read_def $input
}
set_cmd_units -time ps -capacitance fF -resistance kOhm -power mW -distance um
read_sdc $::env(SDC_FILE)
source $::env(SET_RC_TCL)
estimate_parasitics -placement
set block [ord::get_db_block]
set out $::env(SCORE_OUT)
file mkdir $out

set units [$block getDbUnitsPerMicron]
set hpwl 0.0;set measured 0
foreach net [$block getNets] {
  if {[$net getSigType] in {POWER GROUND}} {continue}
  set xs {};set ys {}
  foreach term [$net getITerms] {
    lassign [$term getAvgXY] ok x y
    if {$ok} {lappend xs $x;lappend ys $y}
  }
  foreach term [$net getBTerms] {
    lassign [$term getFirstPinLocation] ok x y
    if {$ok} {lappend xs $x;lappend ys $y}
  }
  if {[llength $xs]<2} {continue}
  set hpwl [expr {$hpwl+double([tcl::mathfunc::max {*}$xs]-[tcl::mathfunc::min {*}$xs]+[tcl::mathfunc::max {*}$ys]-[tcl::mathfunc::min {*}$ys])/$units}]
  incr measured
}
set area 0.0;set macros 0;set logical 0;set physical 0;set macro_area 0.0
foreach inst [$block getInsts] {
  set master [$inst getMaster]
  set phys [expr {[$master isFiller] || [$master isEndCap] || [$master getType] eq "CORE_WELLTAP"}]
  set a [expr {double([$master getWidth])*[$master getHeight]/($units*$units)}]
  if {$phys} {incr physical} else {incr logical;set area [expr {$area+$a}]}
  if {[$master isBlock]} {incr macros;set macro_area [expr {$macro_area+$a}]}
}
report_units
report_clock_properties [all_clocks]
check_setup -verbose > $out/coverage.rpt
report_checks -path_delay max -group_path_count 10 -fields {slew cap input net fanout} -digits 6 -format full_clock_expanded > $out/setup_paths.rpt
report_checks -path_delay min -group_path_count 3 -fields {slew cap input net fanout} -digits 6 -format full_clock_expanded > $out/hold_paths.rpt
set rect [$block getDieArea];set core [$block getCoreArea]
set f [open $out/score.json w]
puts $f [format { {"hpwl_um":%.9f,"measured_nets":%d,"setup_wns_ps":%.9f,"setup_tns_ps":%.9f,"hold_wns_ps":%.9f,"hold_tns_ps":%.9f,"instances":%d,"logical_cells":%d,"physical_cells":%d,"macros":%d,"instance_area_um2":%.9f,"macro_area_um2":%.9f,"die_um":[%.6f,%.6f,%.6f,%.6f],"core_um":[%.6f,%.6f,%.6f,%.6f],"scoring_seconds":%.6f} } \
 $hpwl $measured [sta::worst_slack -max] [sta::total_negative_slack -max] [sta::worst_slack -min] [sta::total_negative_slack -min] \
 [llength [$block getInsts]] $logical $physical $macros $area $macro_area \
 [expr {double([$rect xMin])/$units}] [expr {double([$rect yMin])/$units}] [expr {double([$rect xMax])/$units}] [expr {double([$rect yMax])/$units}] \
 [expr {double([$core xMin])/$units}] [expr {double([$core yMin])/$units}] [expr {double([$core xMax])/$units}] [expr {double([$core yMax])/$units}] \
 [expr {([clock milliseconds]-$begin)/1000.0}]]
close $f
