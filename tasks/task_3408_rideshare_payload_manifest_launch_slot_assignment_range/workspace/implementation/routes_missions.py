"""Mission routes: create/read, lock-manifest, launch, scrub, delay,
dispenser ports, range-slot / delay-event / anomaly listings."""
from decimal import Decimal
from flask import Blueprint, g, request

from calc import (
    BASE_GAP_S,
    SAME_INTERFACE_EXTRA_GAP_S,
    cola_blocked,
    integration_fee_unrounded,
    separation_order,
    weather_blocked,
)
from cascade import delay_mission, scrub_mission
from envelope import success, success_list
from errors import (
    ERR_DELAY_REGRESSION,
    ERR_INVALID_STATE,
    ERR_LAUNCH_WINDOW_VIOLATION,
    ERR_DUPLICATE_PORT_CODE,
    ERR_CONTRACT_NOT_FOUND,
    ERR_MISSION_NOT_FOUND,
    ERR_WEATHER_HOLD,
    bad_request,
    conflict,
    not_found,
    unprocessable,
)
from middleware import require_roles
from serialize import (
    ser_anomaly,
    ser_delay_event,
    ser_dispenser_port,
    ser_mission,
    ser_range_slot,
)
from store import bump, db, new_entity, now, touch
from util import round_half_up_int
from validate import (
    as_dt,
    as_enum,
    as_enum_list,
    as_int,
    as_positive_number,
    as_str,
    body_json,
    check_window,
    opt_enum_filter,
    opt_field,
    paginate,
    parse_pagination,
    req_field,
)

bp = Blueprint("missions", __name__)

ORBITS = {"SSO", "LEO", "GTO"}
INTERFACE_CLASSES = {"RING_15", "RING_24", "CUBESAT"}
RANGE_SLOT_STATUSES = {"REQUESTED", "RESERVED", "CONFIRMED", "CONSUMED", "RELEASED"}
ANOMALY_STATUSES = {"OPEN", "UNDER_INVESTIGATION", "ESCALATED", "RESOLVED"}
MISSION_READ_ROLES = (
    "MissionOps",
    "RangeOfficer",
    "IntegrationEngineer",
    "SafetyOfficer",
    "ContractManager",
    "Regulator",
    "PlatformAdmin",
    "Customer",
)


def _load_mission(mid):
    m = db["missions"].get(mid)
    if m is None:
        raise not_found(ERR_MISSION_NOT_FOUND, f"mission {mid} not found")
    return m


@bp.post("/rideshare/missions")
@require_roles("MissionOps")
def create_mission():
    body = body_json()
    mission_name = as_str(req_field(body, "mission_name"), "mission_name")
    target_orbit = as_enum(req_field(body, "target_orbit"), "target_orbit", ORBITS)
    wopen = as_dt(req_field(body, "window_open_utc"), "window_open_utc")
    wclose = as_dt(req_field(body, "window_close_utc"), "window_close_utc")
    check_window(wopen, wclose)
    mass_cap = as_positive_number(
        req_field(body, "mass_capacity_kg"), "mass_capacity_kg"
    )
    vol_cap = as_positive_number(
        req_field(body, "volume_capacity_m3"), "volume_capacity_m3"
    )

    m = new_entity()
    m.update(
        {
            "mission_name": mission_name,
            "target_orbit": target_orbit,
            "window_open_utc": wopen,
            "window_close_utc": wclose,
            "mass_capacity_kg": mass_cap,
            "volume_capacity_m3": vol_cap,
            "committed_mass_kg": Decimal("0"),
            "committed_volume_m3": Decimal("0"),
            "firm_mass_kg": Decimal("0"),
            "integration_revenue_cents": 0,
            "revenue_estimate_cents": 0,
            "status": "MANIFEST_OPEN",
        }
    )
    db["missions"][m["id"]] = m
    return success(ser_mission(m), 201)


@bp.get("/rideshare/missions/<mid>")
@require_roles(*MISSION_READ_ROLES)
def get_mission(mid):
    return success(ser_mission(_load_mission(mid)))


@bp.post("/rideshare/missions/<mid>/lock-manifest")
@require_roles("MissionOps")
def lock_manifest(mid):
    m = _load_mission(mid)
    if m["status"] != "MANIFEST_OPEN":
        raise conflict(
            ERR_INVALID_STATE,
            f"mission is {m['status']}, expected MANIFEST_OPEN",
        )
    assignments = [a for a in db["assignments"].values() if a["mission_id"] == m["id"]]
    confirmed = [a for a in assignments if a["status"] == "CONFIRMED"]
    if not confirmed:
        raise conflict(
            ERR_INVALID_STATE,
            "lock-manifest requires at least one CONFIRMED assignment",
        )
    if any(a["status"] not in ("CONFIRMED", "REMOVED") for a in assignments):
        raise conflict(
            ERR_INVALID_STATE,
            "every assignment must be CONFIRMED or REMOVED to lock the manifest",
        )
    confirmed.sort(key=lambda a: (a["created_at"], a["_seq"]))
    rounded_total = 0
    unrounded_total = Decimal("0")
    for a in confirmed:
        a["status"] = "INTEGRATED"
        bump(a)
        rounded_total += a["integration_fee_cents"]
        unrounded_total += integration_fee_unrounded(db["payloads"][a["payload_id"]])
    m["integration_revenue_cents"] = rounded_total
    m["revenue_estimate_cents"] = round_half_up_int(unrounded_total)
    m["status"] = "MANIFEST_LOCKED"
    touch(m)
    bump(m)
    return success(ser_mission(m))


@bp.post("/rideshare/missions/<mid>/launch")
@require_roles("MissionOps")
def launch(mid):
    m = _load_mission(mid)
    if m["status"] != "RANGE_SCHEDULED":
        raise conflict(
            ERR_INVALID_STATE,
            f"mission is {m['status']}, expected RANGE_SCHEDULED",
        )
    slot = next(
        (
            s
            for s in db["range_slots"].values()
            if s["mission_id"] == m["id"] and s["status"] == "CONFIRMED"
        ),
        None,
    )
    if slot is None:
        raise conflict(ERR_INVALID_STATE, "mission has no CONFIRMED range slot")
    t = now()
    if weather_blocked(slot["range_code"], t):
        raise unprocessable(
            ERR_WEATHER_HOLD,
            "launch instant falls inside a WEATHER exclusion window",
        )
    if not (m["window_open_utc"] <= t <= m["window_close_utc"]):
        raise unprocessable(
            ERR_LAUNCH_WINDOW_VIOLATION,
            "launch instant outside the mission window",
        )
    if not (slot["window_open_utc"] <= t <= slot["window_close_utc"]):
        raise unprocessable(
            ERR_LAUNCH_WINDOW_VIOLATION,
            "launch instant outside the confirmed slot window",
        )

    slot["status"] = "CONSUMED"
    touch(slot)  # CONFIRMED -> CONSUMED carries no version bump

    ordered = separation_order(m)
    prev_interface = None
    offset = 0
    for idx, a in enumerate(ordered):
        if idx > 0:
            gap = BASE_GAP_S
            payload = db["payloads"][a["payload_id"]]
            if payload["interface_class"] == prev_interface:
                gap += SAME_INTERFACE_EXTRA_GAP_S
            offset += gap
        ev = new_entity()
        ev.update(
            {
                "mission_id": m["id"],
                "assignment_id": a["id"],
                "sequence_index": idx,
                "offset_seconds": offset,
                "status": "PLANNED",
            }
        )
        db["separation_events"][ev["id"]] = ev
        prev_interface = db["payloads"][a["payload_id"]]["interface_class"]

    m["status"] = "LAUNCHED"
    bump(m)
    return success(ser_mission(m))


@bp.post("/rideshare/missions/<mid>/scrub")
@require_roles("MissionOps")
def scrub(mid):
    body = body_json()
    as_str(req_field(body, "reason_code"), "reason_code")
    m = _load_mission(mid)
    if m["status"] not in ("MANIFEST_LOCKED", "RANGE_SCHEDULED"):
        raise conflict(
            ERR_INVALID_STATE,
            f"mission is {m['status']}, expected MANIFEST_LOCKED or RANGE_SCHEDULED",
        )
    scrub_mission(m)
    return success(ser_mission(m))


@bp.post("/rideshare/missions/<mid>/delay")
@require_roles("MissionOps")
def delay(mid):
    body = body_json()
    new_open = as_dt(req_field(body, "new_window_open_utc"), "new_window_open_utc")
    new_close = as_dt(req_field(body, "new_window_close_utc"), "new_window_close_utc")
    check_window(new_open, new_close, "new_window_open_utc", "new_window_close_utc")
    reason_code = as_str(req_field(body, "reason_code"), "reason_code")

    m = _load_mission(mid)
    # lifecycle gate (pipeline stage 7): COMPLETED and SCRUBBED are terminal (§3.8)
    if m["status"] in ("COMPLETED", "SCRUBBED"):
        raise conflict(
            ERR_INVALID_STATE,
            f"mission is {m['status']}, a terminal state",
        )
    if not new_open > m["window_open_utc"]:
        raise unprocessable(
            ERR_DELAY_REGRESSION,
            "new_window_open_utc must be strictly after the current window_open_utc",
        )
    event = delay_mission(m, new_open, new_close, reason_code)
    return success(ser_delay_event(event), 201)


@bp.post("/rideshare/missions/<mid>/dispenser-ports")
@require_roles("MissionOps")
def add_dispenser_port(mid):
    body = body_json()
    port_code = as_str(req_field(body, "port_code"), "port_code")
    stack_position = as_int(req_field(body, "stack_position"), "stack_position")
    max_mass = as_positive_number(req_field(body, "max_mass_kg"), "max_mass_kg")
    supported = as_enum_list(
        req_field(body, "supported_interface_classes"),
        "supported_interface_classes",
        INTERFACE_CLASSES,
    )
    m = _load_mission(mid)
    for p in db["dispenser_ports"].values():
        if p["mission_id"] != m["id"]:
            continue
        if p["port_code"] == port_code:
            raise unprocessable(
                ERR_DUPLICATE_PORT_CODE,
                f"port_code {port_code!r} already exists on this mission",
            )
        if p["stack_position"] == stack_position:
            raise unprocessable(
                ERR_DUPLICATE_PORT_CODE,
                f"stack_position {stack_position} already exists on this mission",
            )
    p = new_entity()
    p.update(
        {
            "mission_id": m["id"],
            "port_code": port_code,
            "stack_position": stack_position,
            "max_mass_kg": max_mass,
            "supported_interface_classes": supported,
        }
    )
    db["dispenser_ports"][p["id"]] = p
    return success(ser_dispenser_port(p), 201)


@bp.get("/rideshare/missions/<mid>/dispenser-ports")
@require_roles("MissionOps", "IntegrationEngineer")
def list_dispenser_ports(mid):
    m = _load_mission(mid)
    limit, offset = parse_pagination(request.args)
    ports = [p for p in db["dispenser_ports"].values() if p["mission_id"] == m["id"]]
    ports.sort(key=lambda p: (-p["stack_position"], p["_seq"]))
    page, total = paginate(ports, limit, offset)
    return success_list([ser_dispenser_port(p) for p in page], limit, offset, total)


@bp.get("/rideshare/missions/<mid>/range-slots")
@require_roles("MissionOps", "RangeOfficer")
def list_mission_range_slots(mid):
    m = _load_mission(mid)
    status = opt_enum_filter(
        request.args, "status", RANGE_SLOT_STATUSES
    )
    limit, offset = parse_pagination(request.args)
    slots = [s for s in db["range_slots"].values() if s["mission_id"] == m["id"]]
    if status is not None:
        slots = [s for s in slots if s["status"] == status]
    slots.sort(key=lambda s: (s["created_at"], s["_seq"]))
    page, total = paginate(slots, limit, offset)
    return success_list([ser_range_slot(s) for s in page], limit, offset, total)


def _customer_is_affected(customer_id, mission_id):
    """A Customer may see a mission's delay events only if one of its contracts
    targets this mission or holds (or held) an assignment on it."""
    for c in db["contracts"].values():
        if c["customer_id"] != customer_id:
            continue
        if c["target_mission_id"] == mission_id:
            return True
        contract_id = c["id"]
        for a in db["assignments"].values():
            if a["mission_id"] != mission_id:
                continue
            if db["payloads"][a["payload_id"]]["contract_id"] == contract_id:
                return True
    return False


@bp.get("/rideshare/missions/<mid>/delay-events")
@require_roles("MissionOps", "ContractManager", "Customer")
def list_delay_events(mid):
    m = _load_mission(mid)
    if g.user_role == "Customer" and not _customer_is_affected(g.user_id, m["id"]):
        raise not_found(
            ERR_CONTRACT_NOT_FOUND, "delay events are not visible to this customer"
        )
    limit, offset = parse_pagination(request.args)
    events = [
        e for e in db["delay_events"].values() if e["mission_id"] == m["id"]
    ]
    events.sort(key=lambda e: (e["created_at"], e["_seq"]))
    page, total = paginate(events, limit, offset)
    return success_list([ser_delay_event(e) for e in page], limit, offset, total)


@bp.get("/rideshare/missions/<mid>/anomalies")
@require_roles("MissionOps", "SafetyOfficer")
def list_mission_anomalies(mid):
    m = _load_mission(mid)
    status = opt_enum_filter(
        request.args, "status", ANOMALY_STATUSES
    )
    limit, offset = parse_pagination(request.args)
    rows = [a for a in db["anomalies"].values() if a["mission_id"] == m["id"]]
    if status is not None:
        rows = [a for a in rows if a["status"] == status]
    rows.sort(key=lambda a: (a["created_at"], a["_seq"]))
    page, total = paginate(rows, limit, offset)
    return success_list([ser_anomaly(a) for a in page], limit, offset, total)
