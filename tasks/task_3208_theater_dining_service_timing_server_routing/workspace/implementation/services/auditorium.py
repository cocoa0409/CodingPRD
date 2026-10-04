"""Auditorium lifecycle and derived posture reporting."""

from datetime import timedelta

import db
import errors
from errors import ApiError
from services import core


def create(data):
    name = data.get("name")
    if name is None:
        name = ""
    seat_capacity = data.get("seat_capacity")
    try:
        seat_capacity = int(seat_capacity)
    except (TypeError, ValueError):
        seat_capacity = 0
    if seat_capacity < 1:
        seat_capacity = 1

    lead = data.get("screen_lead_time_minutes", 20)
    try:
        lead = int(lead)
    except (TypeError, ValueError):
        lead = 20
    if lead < core.PRE_SHOW_MIN_MINUTES:
        lead = core.PRE_SHOW_MIN_MINUTES
    if lead > core.PRE_SHOW_MAX_MINUTES:
        lead = core.PRE_SHOW_MAX_MINUTES

    kitchen_rate = data.get("kitchen_point_rate", 1)
    try:
        kitchen_rate = int(kitchen_rate)
    except (TypeError, ValueError):
        kitchen_rate = 1
    if kitchen_rate < 1:
        kitchen_rate = 1

    alcove_rate = data.get("alcove_point_rate", 3)
    try:
        alcove_rate = int(alcove_rate)
    except (TypeError, ValueError):
        alcove_rate = 3
    if alcove_rate < 1:
        alcove_rate = 1

    row = {
        "name": name,
        "seat_capacity": seat_capacity,
        "screen_lead_time_minutes": lead,
        "kitchen_point_rate": kitchen_rate,
        "alcove_point_rate": alcove_rate,
        "status": "DARK",
        "service_posture": "DARK",
        "build_phase": "EMPTY",
        "last_showtime_cluster_start_utc": None,
        "refund_key_instant": None,
        "version": 1,
        "updated_at": db.db.now,
    }
    return db.db.register("auditoriums", row)


def activate(aud):
    members = core.members_of(aud["id"])
    if any(s["status"] == "SCHEDULED" for s in members):
        aud["status"] = "TURNOVER"
        aud["service_posture"] = "TURNOVER"
    core.reconcile_auditorium(aud)
    core.bump_version(aud)
    core.touch(aud)
    return aud


def close(aud):
    aud["status"] = "DARK"
    aud["service_posture"] = "DARK"
    core.bump_version(aud)
    core.touch(aud)
    return aud


def binding_showtime(aud_id):
    members = core.members_of(aud_id)
    live = [s for s in members if s["status"] in ("DINING_OPEN", "SERVICE", "RUNNING")]
    if live:
        return min(live, key=lambda s: s["start_at_utc"])
    scheduled = [s for s in members if s["status"] == "SCHEDULED"]
    if scheduled:
        return min(scheduled, key=lambda s: s["start_at_utc"])
    return None


def posture(aud):
    core.reconcile_auditorium(aud)
    st = binding_showtime(aud["id"])
    if st is None:
        binding_band = "NORMAL"
    else:
        binding_band = core.capacity_snapshot(st)["capacity_band"]
    stage = None
    for ev in db.db.sorted_rows("disturbance_events"):
        slip = db.db.order_slips.get(ev["order_slip_id"])
        if slip is None:
            continue
        show = db.db.showtimes.get(slip["showtime_id"])
        if show is None or show["auditorium_id"] != aud["id"]:
            continue
        if stage is None or core.STAGE_ORDER.get(ev["stage"], 0) > \
                core.STAGE_ORDER.get(stage, 0):
            stage = ev["stage"]
    return {
        "status": aud["status"],
        "service_posture": aud["service_posture"],
        "build_phase": aud["build_phase"],
        "last_showtime_cluster_start_utc": db.iso_z(aud["last_showtime_cluster_start_utc"]),
        "next_scheduled_showtime_dining_open_at_utc":
            db.iso_z(core.next_scheduled_dining_open(aud["id"])),
        "binding_band": binding_band,
        "active_ejection_stage": stage,
    }


def refund_liability(aud):
    """Both liability figures, keyed on the auditorium's cluster instant.

    PRD §3.8: "Both are keyed on an *instant*: the auditorium's last cluster
    instant, matched exactly against the moment the ejections were recorded, so
    an ejection observed at a different instant does not contribute." The instant
    the room's own cluster opened is the key, and the ejections it books are the
    ones filed against the showtimes of that cluster.
    """
    core.reconcile_auditorium(aud)
    ejections = []
    for ev in db.db.sorted_rows("disturbance_events"):
        if ev["stage"] != "EJECTION" or ev["ejected_occupant_id"] is None:
            continue
        slip = db.db.order_slips.get(ev["order_slip_id"])
        if slip is None:
            continue
        show = db.db.showtimes.get(slip["showtime_id"])
        if show is None or show["auditorium_id"] != aud["id"]:
            continue
        ejections.append((ev, slip, show))

    instant = aud.get("refund_key_instant")
    if instant is None:
        instant = aud["last_showtime_cluster_start_utc"]
    if instant is None and ejections:
        instant = max(show["start_at_utc"] for _ev, _slip, show in ejections)

    matched = [(ev, slip, show) for ev, slip, show in ejections
               if show["start_at_utc"] == instant]

    fair = 0
    server_ids = set()
    for ev, slip, show in matched:
        tab = db.db.checks.get(slip["id"])
        if tab is not None:
            fair += tab["refunded_cents"]
        assignment = db.db.section_assignments.get(slip["section_assignment_id"])
        if assignment is not None:
            server_ids.add(assignment["server_id"])

    shock = 0
    for server_id in server_ids:
        srv = db.db.servers.get(server_id)
        if srv is not None:
            shock += srv["rollup_provisional_cents"]

    return {
        "fair_liability_cents": fair,
        "shock_liability_cents": shock,
        "ejection_count": len(matched),
        "cluster_instant_utc": db.iso_z(instant),
    }