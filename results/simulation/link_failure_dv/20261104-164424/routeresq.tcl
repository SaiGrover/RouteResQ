# =====================================================================
# RouteResQ - NS2 wired topology for failure / congestion experiments
# =====================================================================
#
# Topology (6 nodes, all duplex wired links):
#
#                 n2
#      (primary) /  \ (primary)
#   n0 ---- n1          n4 ---- n5
#     source    \  /    destination
#                 n3
#           (alternative path)
#
#   n0 = source host        n5 = destination host
#   n1, n4 = edge routers   n2 = core router (primary path)
#   n3 = core router (alternative / backup path)
#
# Every parameter is passed on the command line as key=value, e.g.
#   ns routeresq.tcl routing=DV fail_link=1-2 fail_at=3.0 restore_at=6.0
# The Python runner (simulation/runner.py) builds these arguments from the
# JSON scenario files in simulation/scenarios/.
# =====================================================================

# ---------------- default parameters ----------------
array set opt {
    trace         out.tr
    events        events.log
    stop          10.0
    routing       DV
    access_bw     10Mb
    access_delay  2ms
    core_bw       2Mb
    core_delay    10ms
    alt_delay     15ms
    queue_limit   20
    alt_cost      3
    pkt_size      1000
    rate          1Mb
    traffic_start 1.0
    traffic_stop  9.0
    fail_link     none
    fail_at       -1
    restore_at    -1
    cross_rate    0
    cross_start   -1
    cross_stop    -1
    dv_advert     2
}

foreach arg $argv {
    set kv [split $arg =]
    if {[llength $kv] != 2} {
        puts stderr "Ignoring malformed argument: $arg"
        continue
    }
    set key [lindex $kv 0]
    if {![info exists opt($key)]} {
        puts stderr "Unknown parameter: $key"
        exit 2
    }
    set opt($key) [lindex $kv 1]
}

set ns [new Simulator]

# ---------------- routing ----------------
# DV  = distance-vector dynamic routing (reacts to link-down / link-up)
# Static = routes computed once from the initial topology
if {$opt(routing) == "DV"} {
    Agent/rtProto/DV set advertInterval $opt(dv_advert)
    $ns rtproto DV
} elseif {$opt(routing) != "Static"} {
    puts stderr "Unsupported routing protocol: $opt(routing)"
    exit 2
}

set tf [open $opt(trace) w]
$ns trace-all $tf
set ef [open $opt(events) w]

proc log_event {kind detail} {
    global ns ef
    puts $ef "[format %.6f [$ns now]] $kind $detail"
    flush $ef
}

# ---------------- nodes ----------------
for {set i 0} {$i < 6} {incr i} {
    set n($i) [$ns node]
}

# ---------------- links ----------------
# access links (fast)
$ns duplex-link $n(0) $n(1) $opt(access_bw) $opt(access_delay) DropTail
$ns duplex-link $n(4) $n(5) $opt(access_bw) $opt(access_delay) DropTail
# primary core path n1-n2-n4
$ns duplex-link $n(1) $n(2) $opt(core_bw) $opt(core_delay) DropTail
$ns duplex-link $n(2) $n(4) $opt(core_bw) $opt(core_delay) DropTail
# alternative core path n1-n3-n4 (longer delay, higher routing cost)
$ns duplex-link $n(1) $n(3) $opt(core_bw) $opt(alt_delay) DropTail
$ns duplex-link $n(3) $n(4) $opt(core_bw) $opt(alt_delay) DropTail

foreach {a b} {0 1 1 2 2 4 1 3 3 4 4 5} {
    $ns queue-limit $n($a) $n($b) $opt(queue_limit)
    $ns queue-limit $n($b) $n($a) $opt(queue_limit)
}

# Higher cost on the alternative path so routing prefers n1-n2-n4
# while all links are up (cost 1 per hop is the NS2 default).
foreach {a b} {1 3 3 4} {
    $ns cost $n($a) $n($b) $opt(alt_cost)
    $ns cost $n($b) $n($a) $opt(alt_cost)
}

# ---------------- traffic ----------------
# Flow 1: monitored application flow n0 -> n5 (UDP + CBR)
set udp1 [new Agent/UDP]
$udp1 set fid_ 1
$ns attach-agent $n(0) $udp1
set sink1 [new Agent/Null]
$ns attach-agent $n(5) $sink1
$ns connect $udp1 $sink1
set cbr1 [new Application/Traffic/CBR]
$cbr1 attach-agent $udp1
$cbr1 set packetSize_ $opt(pkt_size)
$cbr1 set rate_ $opt(rate)
$cbr1 set random_ 0

$ns at $opt(traffic_start) "$cbr1 start; log_event TRAFFIC_START flow=1"
$ns at $opt(traffic_stop)  "$cbr1 stop;  log_event TRAFFIC_STOP flow=1"

# Flow 2: optional competing (cross) traffic n0 -> n5 used to create congestion
if {$opt(cross_rate) != 0} {
    set udp2 [new Agent/UDP]
    $udp2 set fid_ 2
    $ns attach-agent $n(0) $udp2
    set sink2 [new Agent/Null]
    $ns attach-agent $n(5) $sink2
    $ns connect $udp2 $sink2
    set cbr2 [new Application/Traffic/CBR]
    $cbr2 attach-agent $udp2
    $cbr2 set packetSize_ $opt(pkt_size)
    $cbr2 set rate_ $opt(cross_rate)
    $cbr2 set random_ 0
    $ns at $opt(cross_start) "$cbr2 start; log_event CROSS_TRAFFIC_START flow=2"
    $ns at $opt(cross_stop)  "$cbr2 stop;  log_event CROSS_TRAFFIC_STOP flow=2"
}

# ---------------- controlled link failure ----------------
if {$opt(fail_link) != "none"} {
    set ends [split $opt(fail_link) -]
    set fa [lindex $ends 0]
    set fb [lindex $ends 1]
    if {$opt(fail_at) >= 0} {
        $ns rtmodel-at $opt(fail_at) down $n($fa) $n($fb)
        $ns at $opt(fail_at) "log_event LINK_DOWN $fa-$fb"
    }
    if {$opt(restore_at) >= 0} {
        $ns rtmodel-at $opt(restore_at) up $n($fa) $n($fb)
        $ns at $opt(restore_at) "log_event LINK_UP $fa-$fb"
    }
}

proc finish {} {
    global ns tf ef
    log_event SIM_END -
    $ns flush-trace
    close $tf
    close $ef
    exit 0
}

$ns at 0.0 "log_event SIM_START routing=$opt(routing)"
$ns at $opt(stop) "finish"
$ns run
