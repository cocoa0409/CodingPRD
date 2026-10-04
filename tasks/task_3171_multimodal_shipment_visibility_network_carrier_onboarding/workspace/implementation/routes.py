"""All route handlers. Each returns (data, status) for objects or
(items, status, pagination_meta) for lists."""

from datetime import timedelta
from decimal import Decimal

import db
from db import get_clock
from helpers import (
    ApiError, new_id, now_ts, parse_iso, rhu, minutes_between,
    err_missing_user_context, err_insufficient_permissions, err_data_share_forbidden,
    err_invalid_request, err_invalid_mode_config, err_not_found,
    err_connection_invalid_state, err_connection_not_active, err_remediation_not_proven,
    err_testing_window_conflict, err_quality_gate_not_met, err_shipment_not_trackable,
    err_shipment_not_cancellable, err_shipment_terminal, err_match_score_below_threshold,
    err_link_not_proposed, err_alert_invalid_state, err_facility_not_active,
    err_appointment_window_conflict, err_appointment_invalid_state,
    err_grant_already_revoked, err_stale_version,
)
from serializers import (
    serialize_carrier, serialize_shipper, serialize_consignee, serialize_connection,
    serialize_purchase_order, serialize_facility, serialize_shipment,
    serialize_tracking_event, serialize_identity_link, serialize_alert,
    serialize_appointment, serialize_data_share_grant, serialize_heartbeat_record,
    serialize_ops_run,
)
from services import (
    CADENCE_MINUTES, MODES, FREE_TIME_MINUTES, GRACE_MINUTES,
    touch, recompute_eta, derive_tracking_status,
    freeze_eta_on_delivered, delay_risk_assessment, score_connection_epoch,
    score_connection_instantaneous, compute_match_score, rederive_identity_state,
    recompute_facility_adherence, suspend_connection, resume_connection,
    has_active_grant,
)

ALL_ROLES = (
    "PlatformAdmin", "NetworkOps", "CarrierRep", "ShipperRep", "CustomerService", "ConsigneeRep"
)
READ_ROLES = ALL_ROLES  # all roles can GET most resources (visibility scoped where noted)

# -----------------------------------------------------------------------------
# Lookup helpers (existence checked left-to-right at call site)
# -----------------------------------------------------------------------------

NOT_FOUND_IDS = {
    "carrier": "ERR_CARRIER_NOT_FOUND",
    "shipper": "ERR_SHIPPER_NOT_FOUND",
    "consignee": "ERR_CONSIGNEE_NOT_FOUND",
    "connection": "ERR_CONNECTION_NOT_FOUND",
    "purchase_order": "ERR_PURCHASE_ORDER_NOT_FOUND",
    "facility": "ERR_FACILITY_NOT_FOUND",
    "shipment": "ERR_SHIPMENT_NOT_FOUND",
    "event": "ERR_EVENT_NOT_FOUND",
    "identity_link": "ERR_IDENTITY_LINK_NOT_FOUND",
    "alert": "ERR_ALERT_NOT_FOUND",
    "appointment": "ERR_APPOINTMENT_NOT_FOUND",
    "data_share_grant": "ERR_DATA_SHARE_GRANT_NOT_FOUND",
}


def _lookup(store, kind, entity_id):
    if entity_id not in store:
        raise err_not_found(NOT_FOUND_IDS[kind], "%s %s not found" % (kind, entity_id))
    return store[entity_id]


def get_carrier(cid):
    return _lookup(db.carriers, "carrier", cid)


def get_shipper(sid):
    return _lookup(db.shippers, "shipper", sid)


def get_consignee(cid):
    return _lookup(db.consignees, "consignee", cid)


def get_connection(cid):
    return _lookup(db.connections, "connection", cid)


def get_purchase_order(pid):
    return _lookup(db.purchase_orders, "purchase_order", pid)


def get_facility(fid):
    return _lookup(db.facilities, "facility", fid)


def get_shipment(sid):
    return _lookup(db.shipments, "shipment", sid)


def get_event(eid):
    return _lookup(db.tracking_events, "event", eid)


def get_identity_link(lid):
    return _lookup(db.identity_links, "identity_link", lid)


def get_alert(aid):
    return _lookup(db.alerts, "alert", aid)


def get_appointment(aid):
    return _lookup(db.appointments, "appointment", aid)


def get_grant(gid):
    return _lookup(db.data_share_grants, "data_share_grant", gid)


# -----------------------------------------------------------------------------
# Common helpers
# -----------------------------------------------------------------------------

def _common_new(entity_dict):
    """Set id/created_at/updated_at/version=1 on a new entity dict in place."""
    now = get_clock()
    entity_dict["id"] = new_id()
    entity_dict["created_at"] = now
    entity_dict["updated_at"] = now
    entity_dict["version"] = 1
    return entity_dict


def _paginate(items, args):
    """Standard limit/offset pagination. items assumed pre-sorted by created_at ASC."""
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise err_invalid_request("limit must be an integer")
        if limit < 1 or limit > 100:
            raise err_invalid_request("limit must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise err_invalid_request("offset must be an integer")
        if offset < 0:
            raise err_invalid_request("offset must be >= 0")
    total = len(items)
    page = items[offset:offset + limit]
    has_more = (offset + len(page)) < total
    return page, {"limit": limit, "offset": offset, "total_count": total, "has_more": has_more}


def _body(request):
    return request.get_json(silent=True) or {}


def _require_field(body, name):
    v = body.get(name)
    if v is None:
        raise err_invalid_request("missing required field: %s" % name)
    return v


def _require_string(body, name):
    v = _require_field(body, name)
    if not isinstance(v, str) or v == "":
        raise err_invalid_request("%s must be a non-empty string" % name)
    return v


def _require_iso(body, name):
    v = _require_field(body, name)
    dt = parse_iso(v)
    if dt is None:
        raise err_invalid_request("%s must be a valid ISO 8601 timestamp" % name)
    return dt


def _check_ownership_shipper(user, shipper_id):
    if user["role"] == "ShipperRep" and user["user_id"] != shipper_id:
        raise err_insufficient_permissions("ShipperRep may only act on own shipper's resources")


def _check_ownership_carrier(user, carrier_id):
    if user["role"] == "CarrierRep" and user["user_id"] != carrier_id:
        raise err_insufficient_permissions("CarrierRep may only act on own carrier's resources")


def _check_ownership_consignee(user, consignee_id):
    if user["role"] == "ConsigneeRep" and user["user_id"] != consignee_id:
        raise err_insufficient_permissions("ConsigneeRep may only act as self")


# -----------------------------------------------------------------------------
# Data-share visibility check for shipment detail / events / alerts
# -----------------------------------------------------------------------------

def check_shipment_visibility(user, shipment, scope_needed="FULL_TRACE"):
    """Implements §2.11 visibility scoping.

    scope_needed: 'ETA_ONLY' (shipment detail + alerts) or 'FULL_TRACE' (events).
    """
    role = user["role"]
    uid = user["user_id"]
    # Opaque roles always allowed
    if role in ("PlatformAdmin", "NetworkOps", "CustomerService"):
        return
    # Own-shipper reads
    if role == "ShipperRep" and uid == shipment["shipper_id"]:
        return
    # Own-carrier reads (the carrier operating the shipment)
    if role == "CarrierRep" and uid == shipment["carrier_id"]:
        return
    # Cross-party reads need an ACTIVE grant covering the caller
    now = get_clock()
    if role in ("CarrierRep", "ConsigneeRep"):
        if has_active_grant(shipment["shipper_id"], uid, scope_needed, now):
            return
        raise err_data_share_forbidden()
    # ShipperRep of another shipper: no grant mechanism -> forbidden
    raise err_data_share_forbidden()


# =============================================================================
# Carrier endpoints
# =============================================================================

def create_carrier(user, request):
    body = _body(request)
    carrier_name = _require_string(body, "carrier_name")
    scac_code = _require_string(body, "scac_code")
    carrier = _common_new({
        "carrier_name": carrier_name,
        "scac_code": scac_code,
    })
    db.carriers[carrier["id"]] = carrier
    return serialize_carrier(carrier), 201


def get_carrier_endpoint(user, carrier_id):
    c = get_carrier(carrier_id)
    return serialize_carrier(c), 200


def list_carrier_connections(user, carrier_id, request):
    get_carrier(carrier_id)
    items = [c for c in db.connections.values() if c["carrier_id"] == carrier_id]
    items.sort(key=lambda c: c["created_at"])
    page, meta = _paginate([serialize_connection(c) for c in items], request.args)
    return page, 200, meta


def list_carrier_shipments(user, carrier_id, request):
    get_carrier(carrier_id)
    items = [s for s in db.shipments.values() if s["carrier_id"] == carrier_id]
    items.sort(key=lambda s: s["created_at"])
    page, meta = _paginate([serialize_shipment(s) for s in items], request.args)
    return page, 200, meta


# =============================================================================
# Shipper endpoints
# =============================================================================

def create_shipper(user, request):
    body = _body(request)
    company_name = _require_string(body, "company_name")
    shipper = _common_new({"company_name": company_name})
    db.shippers[shipper["id"]] = shipper
    return serialize_shipper(shipper), 201


def get_shipper_endpoint(user, shipper_id):
    s = get_shipper(shipper_id)
    return serialize_shipper(s), 200


def list_shipper_consignees(user, shipper_id, request):
    get_shipper(shipper_id)
    items = [c for c in db.consignees.values() if c["shipper_id"] == shipper_id]
    items.sort(key=lambda c: c["created_at"])
    page, meta = _paginate([serialize_consignee(c) for c in items], request.args)
    return page, 200, meta


def list_shipper_purchase_orders(user, shipper_id, request):
    get_shipper(shipper_id)
    items = [p for p in db.purchase_orders.values() if p["shipper_id"] == shipper_id]
    items.sort(key=lambda p: p["created_at"])
    page, meta = _paginate([serialize_purchase_order(p) for p in items], request.args)
    return page, 200, meta


def list_shipper_shipments(user, shipper_id, request):
    get_shipper(shipper_id)
    items = [s for s in db.shipments.values() if s["shipper_id"] == shipper_id]
    items.sort(key=lambda s: s["created_at"])
    page, meta = _paginate([serialize_shipment(s) for s in items], request.args)
    return page, 200, meta


def list_shipper_data_share_grants(user, shipper_id, request):
    get_shipper(shipper_id)
    items = [g for g in db.data_share_grants.values() if g["shipper_id"] == shipper_id]
    items.sort(key=lambda g: g["created_at"])
    page, meta = _paginate([serialize_data_share_grant(g) for g in items], request.args)
    return page, 200, meta


# =============================================================================
# Consignee endpoints
# =============================================================================

def create_consignee(user, shipper_id, request):
    # ownership check comes before existence per §2.12 (priority 2 before 4) ONLY
    # when both could apply; here we validate the path id exists (priority 4) then
    # ownership (priority 2 is role+ownership as a unit — role already enforced).
    # PRD: role authorization & ownership at priority 2 precedes existence at 4.
    _check_ownership_shipper(user, shipper_id)
    get_shipper(shipper_id)
    body = _body(request)
    company_name = _require_string(body, "company_name")
    destination_code = _require_string(body, "destination_code")
    consignee = _common_new({
        "shipper_id": shipper_id,
        "company_name": company_name,
        "destination_code": destination_code,
    })
    db.consignees[consignee["id"]] = consignee
    return serialize_consignee(consignee), 201


# =============================================================================
# CarrierConnection endpoints
# =============================================================================

def create_connection(user, carrier_id, request):
    get_carrier(carrier_id)
    body = _body(request)
    channel = _require_string(body, "channel")
    if channel not in ("TELEMATICS", "TMS", "MANUAL"):
        raise err_invalid_request("channel must be TELEMATICS, TMS, or MANUAL")
    modes = body.get("supported_modes")
    if not isinstance(modes, list) or not modes:
        raise err_invalid_mode_config("supported_modes must be a non-empty array")
    for m in modes:
        if m not in MODES:
            raise err_invalid_mode_config("supported_modes contains an invalid mode: %s" % m)
    if channel == "MANUAL" and "PARCEL" in modes:
        raise err_invalid_mode_config("MANUAL channel must not include PARCEL")
    conn = _common_new({
        "carrier_id": carrier_id,
        "channel": channel,
        "supported_modes": list(modes),
        "status": "DRAFT",
        "credential_ref": None,
        "testing_window_start": None,
        "testing_window_end": None,
        "cadence_minutes": CADENCE_MINUTES[channel],
        "data_quality_score": None,
        # Snapshot of data_quality_score as of the last COMPLETED ops-run
        # checkpoint; this (not the live field) feeds confidence intervals
        # (PRD §3.5: "the quality computed in the current run never feeds the
        # same run's confidence intervals"). Not serialized.
        "ci_quality_input": None,
        "instantaneous_quality_score": None,
        "health_status": None,
        "missed_heartbeat_streak": 0,
        "last_heartbeat_at": None,
        "suspended_at": None,
    })
    db.connections[conn["id"]] = conn
    return serialize_connection(conn), 201


def get_connection_endpoint(user, connection_id):
    c = get_connection(connection_id)
    return serialize_connection(c), 200


def submit_credentials(user, connection_id, request):
    conn = get_connection(connection_id)
    _check_ownership_carrier(user, conn["carrier_id"])
    body = _body(request)
    credential_ref = _require_string(body, "credential_ref")
    if conn["status"] != "DRAFT":
        raise err_connection_invalid_state("Connection must be DRAFT to submit credentials")
    conn["credential_ref"] = credential_ref
    conn["status"] = "CREDENTIALS_SUBMITTED"
    touch(conn)
    return serialize_connection(conn), 200


def begin_testing(user, connection_id, request):
    conn = get_connection(connection_id)
    body = _body(request)
    tws = _require_iso(body, "testing_window_start")
    twe = _require_iso(body, "testing_window_end")
    if twe <= tws:
        raise err_invalid_request("testing_window_end must be strictly after testing_window_start")
    if conn["status"] != "CREDENTIALS_SUBMITTED":
        raise err_connection_invalid_state("Connection must be CREDENTIALS_SUBMITTED to begin testing")
    # Closed-interval intersection against other TESTING connections of same carrier
    for other in db.connections.values():
        if other["id"] == conn["id"]:
            continue
        if other["carrier_id"] != conn["carrier_id"]:
            continue
        if other["status"] != "TESTING":
            continue
        o_start = other["testing_window_start"]
        o_end = other["testing_window_end"]
        # closed intervals: intersect iff not (new_end < o_start or new_start > o_end)
        if not (twe < o_start or tws > o_end):
            raise err_testing_window_conflict(
                "Testing window intersects another TESTING connection of the same carrier"
            )
    conn["testing_window_start"] = tws
    conn["testing_window_end"] = twe
    conn["status"] = "TESTING"
    touch(conn)
    return serialize_connection(conn), 200


def activate_connection(user, connection_id):
    conn = get_connection(connection_id)
    if conn["status"] != "TESTING":
        raise err_connection_invalid_state("Connection must be TESTING to activate")
    score = conn["data_quality_score"]
    if score is None or score < 70:
        raise err_quality_gate_not_met()
    conn["status"] = "ACTIVE"
    # health_status recomputed (already reflects latest score; no-op unless changed)
    if score >= 70:
        conn["health_status"] = "HEALTHY"
    elif score >= 40:
        conn["health_status"] = "DEGRADED"
    else:
        conn["health_status"] = "CRITICAL"
    touch(conn)
    return serialize_connection(conn), 200


def suspend_connection_endpoint(user, connection_id, request):
    conn = get_connection(connection_id)
    # reason is optional per spec text; validate shape only if present
    body = _body(request)
    if "reason" in body and body["reason"] is not None and not isinstance(body["reason"], str):
        raise err_invalid_request("reason must be a string")
    if conn["status"] != "ACTIVE":
        raise err_connection_invalid_state("Connection must be ACTIVE to suspend")
    suspend_connection(conn, get_clock())
    touch(conn)
    return serialize_connection(conn), 200


def resume_connection_endpoint(user, connection_id):
    conn = get_connection(connection_id)
    if conn["status"] != "SUSPENDED":
        raise err_connection_invalid_state("Connection must be SUSPENDED to resume")
    last = conn["last_heartbeat_at"]
    suspended_at = conn["suspended_at"]
    if last is None or suspended_at is None or not (last > suspended_at):
        raise err_remediation_not_proven()
    resume_connection(conn)
    touch(conn)
    return serialize_connection(conn), 200


def retire_connection(user, connection_id):
    conn = get_connection(connection_id)
    if conn["status"] not in ("DRAFT", "SUSPENDED"):
        raise err_connection_invalid_state("Connection must be DRAFT or SUSPENDED to retire")
    conn["status"] = "RETIRED"
    touch(conn)
    return serialize_connection(conn), 200


def post_heartbeat(user, connection_id, request):
    conn = get_connection(connection_id)
    _check_ownership_carrier(user, conn["carrier_id"])
    body = _body(request)
    reported_at = _require_iso(body, "reported_at")
    pcp = _require_field(body, "payload_completeness_pct")
    if isinstance(pcp, bool) or not isinstance(pcp, int):
        raise err_invalid_request("payload_completeness_pct must be an integer")
    if pcp < 0 or pcp > 100:
        raise err_invalid_request("payload_completeness_pct must be in [0,100]")
    if conn["status"] not in ("TESTING", "ACTIVE", "SUSPENDED"):
        raise err_connection_invalid_state(
            "Heartbeats allowed only in TESTING, ACTIVE, or SUSPENDED"
        )
    now = get_clock()
    gap_minutes = minutes_between(now, reported_at)
    on_time = gap_minutes <= Decimal(conn["cadence_minutes"])
    hb = {
        "id": new_id(),
        "connection_id": connection_id,
        "reported_at": reported_at,
        "recorded_at": now,
        "payload_completeness_pct": pcp,
        "on_time": on_time,
        "created_at": now,
    }
    db.heartbeat_records[hb["id"]] = hb
    conn["last_heartbeat_at"] = now
    score_connection_instantaneous(conn)
    touch(conn)
    return serialize_heartbeat_record(hb), 201


def list_heartbeats(user, connection_id, request):
    get_connection(connection_id)
    items = [h for h in db.heartbeat_records.values() if h["connection_id"] == connection_id]
    items.sort(key=lambda h: h["created_at"])
    page, meta = _paginate([serialize_heartbeat_record(h) for h in items], request.args)
    return page, 200, meta


# =============================================================================
# PurchaseOrder endpoints
# =============================================================================

def create_purchase_order(user, shipper_id, request):
    _check_ownership_shipper(user, shipper_id)
    get_shipper(shipper_id)
    body = _body(request)
    po_number = _require_string(body, "po_number")
    destination_code = _require_string(body, "destination_code")
    booking_reference = _require_string(body, "booking_reference")
    po = _common_new({
        "shipper_id": shipper_id,
        "po_number": po_number,
        "destination_code": destination_code,
        "booking_reference": booking_reference,
        "confirmed_link_count": 0,
    })
    db.purchase_orders[po["id"]] = po
    return serialize_purchase_order(po), 201


def get_purchase_order_endpoint(user, po_id):
    p = get_purchase_order(po_id)
    return serialize_purchase_order(p), 200


def list_po_identity_links(user, po_id, request):
    get_purchase_order(po_id)
    items = [l for l in db.identity_links.values() if l["purchase_order_id"] == po_id]
    items.sort(key=lambda l: l["created_at"])
    page, meta = _paginate([serialize_identity_link(l) for l in items], request.args)
    return page, 200, meta


# =============================================================================
# Facility endpoints
# =============================================================================

def create_facility(user, request):
    body = _body(request)
    facility_name = _require_string(body, "facility_name")
    facility_type = _require_string(body, "facility_type")
    if facility_type not in ("ORIGIN", "DESTINATION", "BOTH"):
        raise err_invalid_request("facility_type must be ORIGIN, DESTINATION, or BOTH")
    facility = _common_new({
        "facility_name": facility_name,
        "facility_type": facility_type,
        "status": "ACTIVE",
        "total_dwell_minutes": 0,
        "detention_exposure_minutes": 0,
        "appointment_adherence_pct": None,
    })
    db.facilities[facility["id"]] = facility
    return serialize_facility(facility), 201


def get_facility_endpoint(user, facility_id):
    f = get_facility(facility_id)
    return serialize_facility(f), 200


def patch_facility(user, facility_id, request):
    facility = get_facility(facility_id)
    body = _body(request)
    status = _require_string(body, "status")
    if status not in ("ACTIVE", "SUSPENDED"):
        raise err_invalid_request("status must be ACTIVE or SUSPENDED")
    if status == facility["status"]:
        raise err_invalid_request("target status equals current status")
    facility["status"] = status
    touch(facility)
    return serialize_facility(facility), 200


# =============================================================================
# Shipment endpoints
# =============================================================================

def create_shipment(user, shipper_id, request):
    _check_ownership_shipper(user, shipper_id)
    get_shipper(shipper_id)
    body = _body(request)
    carrier_id = _require_string(body, "carrier_id")
    connection_id = _require_string(body, "connection_id")
    mode = _require_string(body, "mode")
    if mode not in MODES:
        raise err_invalid_request("mode must be one of OCEAN, RAIL, PARCEL, TRUCKLOAD")
    tracking_reference = _require_string(body, "tracking_reference")
    mode_reference = _require_string(body, "mode_reference")
    destination_code = _require_string(body, "destination_code")
    po_reference_claim = body.get("po_reference_claim", "")
    if po_reference_claim is None:
        po_reference_claim = ""
    if not isinstance(po_reference_claim, str):
        raise err_invalid_request("po_reference_claim must be a string")
    planned_departure_at = _require_iso(body, "planned_departure_at")
    planned_arrival_at = _require_iso(body, "planned_arrival_at")
    if planned_arrival_at <= planned_departure_at:
        raise err_invalid_request("planned_arrival_at must be strictly after planned_departure_at")

    # Existence of carrier + connection
    get_carrier(carrier_id)
    conn = get_connection(connection_id)

    # Mode compatibility
    if mode not in conn["supported_modes"]:
        raise err_invalid_mode_config("shipment mode not in connection.supported_modes")

    # Connection state gate
    if conn["status"] not in ("TESTING", "ACTIVE"):
        raise err_connection_not_active()

    shipment = _common_new({
        "shipper_id": shipper_id,
        "carrier_id": carrier_id,
        "connection_id": connection_id,
        "mode": mode,
        "tracking_reference": tracking_reference,
        "mode_reference": mode_reference,
        "destination_code": destination_code,
        "po_reference_claim": po_reference_claim,
        "planned_departure_at": planned_departure_at,
        "planned_arrival_at": planned_arrival_at,
        "tracking_status": "BOOKED",
        "identity_state": "UNRESOLVED",
        "data_freshness": "FRESH",
        "eta_at": None,
        "eta_variant": None,
        "eta_confidence_halfwidth_minutes": None,
        "actual_delay_minutes": 0,
    })
    db.shipments[shipment["id"]] = shipment
    recompute_eta(shipment)
    # Shipment creation bumps nothing else; version stays 1.
    return serialize_shipment(shipment), 201


def list_shipments(user, request):
    args = request.args
    items = list(db.shipments.values())
    if "connection_id" in args:
        cid = args.get("connection_id")
        items = [s for s in items if s["connection_id"] == cid]
    if "mode" in args:
        m = args.get("mode")
        items = [s for s in items if s["mode"] == m]
    if "tracking_status" in args:
        ts = args.get("tracking_status")
        items = [s for s in items if s["tracking_status"] == ts]
    items.sort(key=lambda s: s["created_at"])
    page, meta = _paginate([serialize_shipment(s) for s in items], request.args)
    return page, 200, meta


def get_shipment_endpoint(user, shipment_id):
    s = get_shipment(shipment_id)
    check_shipment_visibility(user, s, scope_needed="ETA_ONLY")
    return serialize_shipment(s), 200


def ingest_event(user, shipment_id, request):
    shipment = get_shipment(shipment_id)
    _check_ownership_carrier(user, shipment["carrier_id"])
    body = _body(request)
    event_time = _require_iso(body, "event_time")
    event_type = _require_string(body, "event_type")
    if event_type not in (
        "DEPARTED", "ARRIVED_WAYPOINT", "POSITION_UPDATE",
        "DELAY_REPORTED", "RECOVERED", "OUT_FOR_DELIVERY", "DELIVERED",
    ):
        raise err_invalid_request("invalid event_type")
    delay_minutes = body.get("delay_minutes", 0)
    if delay_minutes is None:
        delay_minutes = 0
    if isinstance(delay_minutes, bool) or not isinstance(delay_minutes, int):
        raise err_invalid_request("delay_minutes must be an integer")
    if delay_minutes < 0:
        raise err_invalid_request("delay_minutes must be >= 0")

    # Connection must be ACTIVE
    conn = get_connection(shipment["connection_id"])
    if conn["status"] != "ACTIVE":
        raise err_connection_not_active("Connection must be ACTIVE for event ingest")

    # Shipment must not be terminal
    if shipment["tracking_status"] in ("DELIVERED", "CANCELLED"):
        raise err_shipment_not_trackable()

    # is_late: event_time earlier than max event_time already applied
    non_voided = [
        e for e in db.tracking_events.values()
        if e["shipment_id"] == shipment_id and not e["voided"]
    ]
    is_late = False
    if non_voided:
        max_et = max(e["event_time"] for e in non_voided)
        if event_time < max_et:
            is_late = True

    now = get_clock()
    evt = {
        "id": new_id(),
        "shipment_id": shipment_id,
        "event_time": event_time,
        "event_type": event_type,
        "delay_minutes": delay_minutes,
        "is_late": is_late,
        "voided": False,
        "created_at": now,
    }
    db.tracking_events[evt["id"]] = evt

    # Re-derive status by replay
    new_status = derive_tracking_status(shipment)
    shipment["tracking_status"] = new_status

    # Recompute ETA + confidence + delay-risk
    recompute_eta(shipment)
    if new_status == "DELIVERED":
        freeze_eta_on_delivered(shipment)
    delay_risk_assessment(shipment)
    touch(shipment)
    return serialize_tracking_event(evt), 201


def list_shipment_events(user, shipment_id, request):
    shipment = get_shipment(shipment_id)
    check_shipment_visibility(user, shipment, scope_needed="FULL_TRACE")
    items = [e for e in db.tracking_events.values() if e["shipment_id"] == shipment_id]
    items.sort(key=lambda e: e["created_at"])
    page, meta = _paginate([serialize_tracking_event(e) for e in items], request.args)
    return page, 200, meta


def void_event(user, shipment_id, event_id):
    shipment = get_shipment(shipment_id)
    evt = db.tracking_events.get(event_id)
    if evt is None or evt["shipment_id"] != shipment_id:
        raise err_not_found("ERR_EVENT_NOT_FOUND", "event %s not found" % event_id)
    evt["voided"] = True
    # Re-derive state
    new_status = derive_tracking_status(shipment)
    shipment["tracking_status"] = new_status
    recompute_eta(shipment)
    if new_status == "DELIVERED":
        freeze_eta_on_delivered(shipment)
    delay_risk_assessment(shipment)
    touch(shipment)
    return serialize_tracking_event(evt), 200


def recompute_eta_endpoint(user, shipment_id):
    shipment = get_shipment(shipment_id)
    recompute_eta(shipment)
    if shipment["tracking_status"] == "DELIVERED":
        freeze_eta_on_delivered(shipment)
    delay_risk_assessment(shipment)
    touch(shipment)
    return serialize_shipment(shipment), 200


def cancel_shipment(user, shipment_id):
    shipment = get_shipment(shipment_id)
    _check_ownership_shipper(user, shipment["shipper_id"])
    if shipment["tracking_status"] not in ("BOOKED", "IN_TRANSIT", "EXCEPTION"):
        raise err_shipment_not_cancellable()
    shipment["tracking_status"] = "CANCELLED"
    # Auto-resolve OPEN or ESCALATED alerts as FALSE_ALARM
    now = get_clock()
    for a in db.alerts.values():
        if a["shipment_id"] == shipment_id and a["status"] in ("OPEN", "ESCALATED"):
            a["status"] = "RESOLVED"
            a["resolution"] = "FALSE_ALARM"
            a["resolved_at"] = now
            touch(a)
    touch(shipment)
    return serialize_shipment(shipment), 200


# =============================================================================
# Identity link endpoints
# =============================================================================

def create_identity_link(user, shipment_id, request):
    shipment = get_shipment(shipment_id)
    body = _body(request)
    po_id = _require_string(body, "purchase_order_id")
    expected_po_version = body.get("expected_po_version")
    # PO existence at priority 4 (path/body refs)
    po = get_purchase_order(po_id)
    # OCC check at priority 9
    if expected_po_version is None:
        raise err_invalid_request("expected_po_version is required")
    if isinstance(expected_po_version, bool) or not isinstance(expected_po_version, int):
        raise err_invalid_request("expected_po_version must be an integer")
    if expected_po_version != po["version"]:
        raise err_stale_version("expected_po_version does not match current purchase order version")
    # Compute match score
    score = compute_match_score(shipment, po)
    link = _common_new({
        "shipment_id": shipment_id,
        "purchase_order_id": po_id,
        "match_score": score,
        "status": "PROPOSED",
    })
    db.identity_links[link["id"]] = link
    # Shipment identity_state -> MATCHED_PROVISIONAL (re-derive covers this)
    rederive_identity_state(shipment)
    touch(shipment)
    # PO version bump (OCC parent bump)
    touch(po)
    return serialize_identity_link(link), 201


def list_shipment_identity_links(user, shipment_id, request):
    get_shipment(shipment_id)
    items = [l for l in db.identity_links.values() if l["shipment_id"] == shipment_id]
    items.sort(key=lambda l: l["created_at"])
    page, meta = _paginate([serialize_identity_link(l) for l in items], request.args)
    return page, 200, meta


def confirm_identity_link(user, link_id):
    link = get_identity_link(link_id)
    po = get_purchase_order(link["purchase_order_id"])
    _check_ownership_shipper(user, po["shipper_id"])
    if link["status"] != "PROPOSED":
        raise err_link_not_proposed("Link must be PROPOSED to confirm")
    shipment = get_shipment(link["shipment_id"])
    if shipment["tracking_status"] in ("DELIVERED", "CANCELLED"):
        raise err_shipment_terminal()
    # Strict > 0.90
    if not (link["match_score"] > Decimal("0.90")):
        raise err_match_score_below_threshold()
    link["status"] = "CONFIRMED"
    touch(link)
    po["confirmed_link_count"] = po["confirmed_link_count"] + 1
    touch(po)
    rederive_identity_state(shipment)
    touch(shipment)
    return serialize_identity_link(link), 200


def reject_identity_link(user, link_id):
    link = get_identity_link(link_id)
    po = get_purchase_order(link["purchase_order_id"])
    _check_ownership_shipper(user, po["shipper_id"])
    if link["status"] not in ("PROPOSED", "CONFIRMED"):
        raise err_link_not_proposed("Link must be PROPOSED or CONFIRMED to reject")
    was_confirmed = link["status"] == "CONFIRMED"
    link["status"] = "REJECTED"
    touch(link)
    if was_confirmed:
        po["confirmed_link_count"] = max(0, po["confirmed_link_count"] - 1)
        touch(po)
    shipment = get_shipment(link["shipment_id"])
    rederive_identity_state(shipment)
    touch(shipment)
    return serialize_identity_link(link), 200


# =============================================================================
# Alert endpoints
# =============================================================================

def list_alerts(user, request):
    args = request.args
    items = list(db.alerts.values())
    if "status" in args:
        st = args.get("status")
        items = [a for a in items if a["status"] == st]
    if "severity" in args:
        sv = args.get("severity")
        items = [a for a in items if a["severity"] == sv]
    items.sort(key=lambda a: a["created_at"])
    page, meta = _paginate([serialize_alert(a) for a in items], request.args)
    return page, 200, meta


def list_shipment_alerts(user, shipment_id, request):
    shipment = get_shipment(shipment_id)
    check_shipment_visibility(user, shipment, scope_needed="ETA_ONLY")
    items = [a for a in db.alerts.values() if a["shipment_id"] == shipment_id]
    items.sort(key=lambda a: a["created_at"])
    page, meta = _paginate([serialize_alert(a) for a in items], request.args)
    return page, 200, meta


def acknowledge_alert(user, alert_id):
    a = get_alert(alert_id)
    if a["status"] not in ("OPEN", "ESCALATED"):
        raise err_alert_invalid_state("Alert must be OPEN or ESCALATED to acknowledge")
    a["status"] = "ACKNOWLEDGED"
    touch(a)
    return serialize_alert(a), 200


def resolve_alert(user, alert_id, request):
    a = get_alert(alert_id)
    body = _body(request)
    resolution = body.get("resolution")
    if resolution is not None and resolution not in ("DELAY_CONFIRMED", "FALSE_ALARM", "DELIVERY_OBSERVED"):
        raise err_invalid_request("resolution must be DELAY_CONFIRMED, FALSE_ALARM, or DELIVERY_OBSERVED")
    if a["status"] != "ACKNOWLEDGED":
        raise err_alert_invalid_state("Alert must be ACKNOWLEDGED to resolve")
    if resolution is None:
        raise err_invalid_request("resolution is required")
    now = get_clock()
    a["status"] = "RESOLVED"
    a["resolution"] = resolution
    a["resolved_at"] = now
    touch(a)
    if resolution == "DELAY_CONFIRMED":
        shipment = get_shipment(a["shipment_id"])
        # actual_delay_minutes = max(0, eta_at - planned_arrival_at)
        if shipment["eta_at"] is not None:
            delta = minutes_between(shipment["eta_at"], shipment["planned_arrival_at"])
            shipment["actual_delay_minutes"] = max(0, int(delta))
        else:
            shipment["actual_delay_minutes"] = 0
        # Cascade: every SCHEDULED appointment of this shipment whose window_end
        # is earlier than shipment.eta_at -> MISSED; recompute adherence per facility.
        affected_facilities = set()
        if shipment["eta_at"] is not None:
            for appt in db.appointments.values():
                if appt["shipment_id"] != shipment["id"]:
                    continue
                if appt["status"] != "SCHEDULED":
                    continue
                if appt["window_end"] < shipment["eta_at"]:
                    appt["status"] = "MISSED"
                    touch(appt)
                    affected_facilities.add(appt["facility_id"])
        touch(shipment)
        for fid in affected_facilities:
            facility = get_facility(fid)
            recompute_facility_adherence(facility)
            touch(facility)
    return serialize_alert(a), 200


# =============================================================================
# Appointment endpoints
# =============================================================================

def create_appointment(user, facility_id, request):
    facility = get_facility(facility_id)
    body = _body(request)
    shipment_id = _require_string(body, "shipment_id")
    shipment = get_shipment(shipment_id)  # 404 ERR_SHIPMENT_NOT_FOUND before OCC (priority 4 < 9)
    _check_ownership_carrier(user, shipment["carrier_id"])
    window_start = _require_iso(body, "window_start")
    window_end = _require_iso(body, "window_end")
    if window_end <= window_start:
        raise err_invalid_request("window_end must be strictly after window_start")
    # Facility must be ACTIVE
    if facility["status"] != "ACTIVE":
        raise err_facility_not_active()
    # Half-open window conflict vs SCHEDULED appointments at this facility
    for other in db.appointments.values():
        if other["facility_id"] != facility_id:
            continue
        if other["status"] != "SCHEDULED":
            continue
        o_start = other["window_start"]
        o_end = other["window_end"]
        # half-open overlap: NOT (new_end <= o_start or new_start >= o_end)
        if not (window_end <= o_start or window_start >= o_end):
            raise err_appointment_window_conflict()
    # OCC: expected_facility_version
    efv = body.get("expected_facility_version")
    if efv is None:
        raise err_invalid_request("expected_facility_version is required")
    if isinstance(efv, bool) or not isinstance(efv, int):
        raise err_invalid_request("expected_facility_version must be an integer")
    if efv != facility["version"]:
        raise err_stale_version("expected_facility_version does not match current facility version")
    appt = _common_new({
        "facility_id": facility_id,
        "shipment_id": shipment_id,
        "window_start": window_start,
        "window_end": window_end,
        "status": "SCHEDULED",
        "actual_arrival_at": None,
        "actual_departure_at": None,
        "dwell_minutes": None,
        "adherent": None,
        "exposure_minutes": None,
    })
    db.appointments[appt["id"]] = appt
    touch(facility)  # OCC parent bump
    return serialize_appointment(appt), 201


def list_facility_appointments(user, facility_id, request):
    get_facility(facility_id)
    args = request.args
    items = [a for a in db.appointments.values() if a["facility_id"] == facility_id]
    if "status" in args:
        st = args.get("status")
        items = [a for a in items if a["status"] == st]
    items.sort(key=lambda a: a["created_at"])
    page, meta = _paginate([serialize_appointment(a) for a in items], request.args)
    return page, 200, meta


def list_appointments(user, request):
    args = request.args
    items = list(db.appointments.values())
    if "shipment_id" in args:
        sid = args.get("shipment_id")
        items = [a for a in items if a["shipment_id"] == sid]
    if "facility_id" in args:
        fid = args.get("facility_id")
        items = [a for a in items if a["facility_id"] == fid]
    items.sort(key=lambda a: a["created_at"])
    page, meta = _paginate([serialize_appointment(a) for a in items], request.args)
    return page, 200, meta


def get_appointment_endpoint(user, appointment_id):
    a = get_appointment(appointment_id)
    return serialize_appointment(a), 200


def complete_appointment(user, appointment_id, request):
    appt = get_appointment(appointment_id)
    shipment = get_shipment(appt["shipment_id"])
    _check_ownership_carrier(user, shipment["carrier_id"])
    body = _body(request)
    arrival = _require_iso(body, "actual_arrival_at")
    departure = _require_iso(body, "actual_departure_at")
    if departure <= arrival:
        raise err_invalid_request("actual_departure_at must be strictly after actual_arrival_at")
    if appt["status"] != "SCHEDULED":
        raise err_appointment_invalid_state("Appointment must be SCHEDULED to complete")
    dwell = minutes_between(departure, arrival)
    dwell_int = int(dwell)  # whole minutes
    adherent = (appt["window_start"] <= arrival < appt["window_end"])
    free = Decimal(FREE_TIME_MINUTES[shipment["mode"]])
    if adherent:
        free += Decimal(GRACE_MINUTES)
    exposure = max(Decimal(0), Decimal(dwell_int) - free)
    exposure_int = int(exposure)

    appt["status"] = "COMPLETED"
    appt["actual_arrival_at"] = arrival
    appt["actual_departure_at"] = departure
    appt["dwell_minutes"] = dwell_int
    appt["adherent"] = adherent
    appt["exposure_minutes"] = exposure_int
    touch(appt)

    facility = get_facility(appt["facility_id"])
    facility["total_dwell_minutes"] = facility["total_dwell_minutes"] + dwell_int
    facility["detention_exposure_minutes"] = facility["detention_exposure_minutes"] + exposure_int
    recompute_facility_adherence(facility)
    touch(facility)
    return serialize_appointment(appt), 200


def void_completion(user, appointment_id):
    appt = get_appointment(appointment_id)
    if appt["status"] != "COMPLETED":
        raise err_appointment_invalid_state("Appointment must be COMPLETED to void")
    facility = get_facility(appt["facility_id"])
    facility["total_dwell_minutes"] = facility["total_dwell_minutes"] - (appt["dwell_minutes"] or 0)
    facility["detention_exposure_minutes"] = (
        facility["detention_exposure_minutes"] - (appt["exposure_minutes"] or 0)
    )
    appt["status"] = "VOIDED"
    touch(appt)
    recompute_facility_adherence(facility)
    touch(facility)
    return serialize_appointment(appt), 200


# =============================================================================
# DataShareGrant endpoints
# =============================================================================

def create_data_share_grant(user, shipper_id, request):
    _check_ownership_shipper(user, shipper_id)
    get_shipper(shipper_id)
    body = _body(request)
    grantee_type = _require_string(body, "grantee_type")
    if grantee_type not in ("CARRIER", "CONSIGNEE"):
        raise err_invalid_request("grantee_type must be CARRIER or CONSIGNEE")
    grantee_id = _require_string(body, "grantee_id")
    scope = _require_string(body, "scope")
    if scope not in ("ETA_ONLY", "FULL_TRACE"):
        raise err_invalid_request("scope must be ETA_ONLY or FULL_TRACE")
    effective_from = _require_iso(body, "effective_from")
    expires_at = _require_iso(body, "expires_at")
    if expires_at <= effective_from:
        raise err_invalid_request("expires_at must be strictly after effective_from")
    # Grantee referential check (priority 9)
    if grantee_type == "CARRIER":
        if grantee_id not in db.carriers:
            raise err_not_found("ERR_CARRIER_NOT_FOUND", "carrier %s not found" % grantee_id)
    else:
        consignee = db.consignees.get(grantee_id)
        if consignee is None or consignee["shipper_id"] != shipper_id:
            raise err_not_found(
                "ERR_CONSIGNEE_NOT_FOUND",
                "consignee %s not found for this shipper" % grantee_id,
            )
    grant = _common_new({
        "shipper_id": shipper_id,
        "grantee_type": grantee_type,
        "grantee_id": grantee_id,
        "scope": scope,
        "effective_from": effective_from,
        "expires_at": expires_at,
        "status": "ACTIVE",
    })
    db.data_share_grants[grant["id"]] = grant
    return serialize_data_share_grant(grant), 201


def revoke_data_share_grant(user, grant_id):
    grant = get_grant(grant_id)
    _check_ownership_shipper(user, grant["shipper_id"])
    if grant["status"] != "ACTIVE":
        raise err_grant_already_revoked()
    grant["status"] = "REVOKED"
    touch(grant)
    return serialize_data_share_grant(grant), 200


# =============================================================================
# Clock + ops-run endpoints
# =============================================================================

def set_clock(user, request):
    body = _body(request)
    to_iso8601 = _require_field(body, "to_iso8601")
    dt = parse_iso(to_iso8601)
    if dt is None:
        raise err_invalid_request("to_iso8601 must be a valid ISO 8601 timestamp")
    current = get_clock()
    if dt < current:
        raise err_invalid_request("logical clock cannot move backwards")
    db.set_clock(dt)
    return {"current_utc": now_ts()}, 200


def run_checkpoint(user):
    now = get_clock()
    prev_run_at = db.last_run_at

    connections_degraded = 0
    testing_connections_reset = 0
    etas_recomputed = 0
    alerts_created_counter = [0]
    alerts_escalated = 0
    # Alerts existing when this run begins; the escalation sweep (step 4) may
    # only touch these — an alert opened by this run's own staleness cascade is
    # not "still OPEN" at run time (PRD §3.7).
    run_start_alert_ids = set(db.alerts.keys())

    # 1. Score every non-RETIRED connection
    for conn in db.connections.values():
        if conn["status"] == "RETIRED":
            continue
        score_connection_epoch(conn, prev_run_at, now)
        touch(conn)

    # 2. Reset TESTING connections whose window has expired
    for conn in db.connections.values():
        if conn["status"] == "TESTING" and conn["testing_window_end"] is not None:
            if conn["testing_window_end"] < now:
                conn["status"] = "DRAFT"
                conn["testing_window_start"] = None
                conn["testing_window_end"] = None
                conn["credential_ref"] = None
                testing_connections_reset += 1
                touch(conn)

    # 3. Suspend ACTIVE connections that have gone silent > 2 * cadence
    just_suspended_ids = []
    for conn in list(db.connections.values()):
        if conn["status"] != "ACTIVE":
            continue
        last = conn["last_heartbeat_at"]
        if last is None:
            # never had a heartbeat — treat as silent since created_at
            gap = minutes_between(now, conn["created_at"])
        else:
            gap = minutes_between(now, last)
        if gap > Decimal(2 * conn["cadence_minutes"]):
            suspend_connection(conn, now)
            connections_degraded += 1
            just_suspended_ids.append(conn["id"])
            touch(conn)

    # Count shipments whose ETA was recomputed in this run (those moved to STALE
    # by cascade above).
    for s in db.shipments.values():
        if s["connection_id"] in just_suspended_ids and s["data_freshness"] == "STALE":
            etas_recomputed += 1

    # 4. Escalate overdue HIGH-severity OPEN alerts. Only alerts that existed
    # when this run began are eligible — an alert opened by this run's own
    # staleness cascade is not "still OPEN" at run time (PRD §3.7).
    for a in db.alerts.values():
        if a["id"] not in run_start_alert_ids:
            continue
        if a["status"] != "OPEN":
            continue
        if a["severity"] != "HIGH":
            continue
        age = minutes_between(now, a["opened_at"])
        if age > Decimal(240):
            a["status"] = "ESCALATED"
            touch(a)
            alerts_escalated += 1

    # Count alerts created during this run: alerts whose opened_at == now
    for a in db.alerts.values():
        if a["opened_at"] == now:
            alerts_created_counter[0] += 1

    run_index = (max(db.ops_runs.keys()) + 1) if db.ops_runs else 1
    ops_run = {
        "id": new_id(),
        "run_index": run_index,
        "executed_at": now,
        "connections_degraded": connections_degraded,
        "testing_connections_reset": testing_connections_reset,
        "etas_recomputed": etas_recomputed,
        "alerts_created": alerts_created_counter[0],
        "alerts_escalated": alerts_escalated,
        "created_at": now,
    }
    db.ops_runs[run_index] = ops_run
    db.last_run_at = now
    # The scores this run produced become the confidence-interval input for
    # SUBSEQUENT runs only (PRD §3.9) — snapshot them at completion.
    for conn in db.connections.values():
        conn["ci_quality_input"] = conn["data_quality_score"]
    return serialize_ops_run(ops_run), 200


# =============================================================================
# Route table
# =============================================================================

# Each entry: (method, path, handler, roles)
# handler signature: (user, request, **path_params) -> (data, status) | (items, status, meta)

ROUTES = [
    # Carriers
    ("POST", "/carriers", lambda u, r: create_carrier(u, r), ("NetworkOps",)),
    ("GET", "/carriers/<carrier_id>", lambda u, r, carrier_id: get_carrier_endpoint(u, carrier_id), READ_ROLES),
    ("GET", "/carriers/<carrier_id>/connections", lambda u, r, carrier_id: list_carrier_connections(u, carrier_id, r), READ_ROLES),
    ("GET", "/carriers/<carrier_id>/shipments", lambda u, r, carrier_id: list_carrier_shipments(u, carrier_id, r), READ_ROLES),

    # Shippers
    ("POST", "/shippers", lambda u, r: create_shipper(u, r), ("PlatformAdmin",)),
    ("GET", "/shippers/<shipper_id>", lambda u, r, shipper_id: get_shipper_endpoint(u, shipper_id), READ_ROLES),
    ("GET", "/shippers/<shipper_id>/consignees", lambda u, r, shipper_id: list_shipper_consignees(u, shipper_id, r), READ_ROLES),
    ("GET", "/shippers/<shipper_id>/purchase-orders", lambda u, r, shipper_id: list_shipper_purchase_orders(u, shipper_id, r), READ_ROLES),
    ("GET", "/shippers/<shipper_id>/shipments", lambda u, r, shipper_id: list_shipper_shipments(u, shipper_id, r), READ_ROLES),
    ("GET", "/shippers/<shipper_id>/data-share-grants", lambda u, r, shipper_id: list_shipper_data_share_grants(u, shipper_id, r), READ_ROLES),

    # Consignees
    ("POST", "/shippers/<shipper_id>/consignees", lambda u, r, shipper_id: create_consignee(u, shipper_id, r), ("ShipperRep",)),

    # Connections
    ("POST", "/carriers/<carrier_id>/connections", lambda u, r, carrier_id: create_connection(u, carrier_id, r), ("NetworkOps",)),
    ("GET", "/connections/<connection_id>", lambda u, r, connection_id: get_connection_endpoint(u, connection_id), READ_ROLES),
    ("POST", "/connections/<connection_id>/submit-credentials", lambda u, r, connection_id: submit_credentials(u, connection_id, r), ("CarrierRep",)),
    ("POST", "/connections/<connection_id>/begin-testing", lambda u, r, connection_id: begin_testing(u, connection_id, r), ("NetworkOps",)),
    ("POST", "/connections/<connection_id>/activate", lambda u, r, connection_id: activate_connection(u, connection_id), ("NetworkOps",)),
    ("POST", "/connections/<connection_id>/suspend", lambda u, r, connection_id: suspend_connection_endpoint(u, connection_id, r), ("NetworkOps",)),
    ("POST", "/connections/<connection_id>/resume", lambda u, r, connection_id: resume_connection_endpoint(u, connection_id), ("NetworkOps",)),
    ("POST", "/connections/<connection_id>/retire", lambda u, r, connection_id: retire_connection(u, connection_id), ("NetworkOps",)),
    ("POST", "/connections/<connection_id>/heartbeats", lambda u, r, connection_id: post_heartbeat(u, connection_id, r), ("CarrierRep",)),
    ("GET", "/connections/<connection_id>/heartbeats", lambda u, r, connection_id: list_heartbeats(u, connection_id, r), READ_ROLES),

    # Purchase orders
    ("POST", "/shippers/<shipper_id>/purchase-orders", lambda u, r, shipper_id: create_purchase_order(u, shipper_id, r), ("ShipperRep",)),
    ("GET", "/purchase-orders/<po_id>", lambda u, r, po_id: get_purchase_order_endpoint(u, po_id), READ_ROLES),
    ("GET", "/purchase-orders/<po_id>/identity-links", lambda u, r, po_id: list_po_identity_links(u, po_id, r), READ_ROLES),

    # Facilities
    ("POST", "/facilities", lambda u, r: create_facility(u, r), ("PlatformAdmin",)),
    ("GET", "/facilities/<facility_id>", lambda u, r, facility_id: get_facility_endpoint(u, facility_id), READ_ROLES),
    ("PATCH", "/facilities/<facility_id>", lambda u, r, facility_id: patch_facility(u, facility_id, r), ("PlatformAdmin",)),

    # Shipments
    ("POST", "/shippers/<shipper_id>/shipments", lambda u, r, shipper_id: create_shipment(u, shipper_id, r), ("ShipperRep",)),
    ("GET", "/shipments", lambda u, r: list_shipments(u, r), READ_ROLES),
    ("GET", "/shipments/<shipment_id>", lambda u, r, shipment_id: get_shipment_endpoint(u, shipment_id), READ_ROLES),
    ("POST", "/shipments/<shipment_id>/events", lambda u, r, shipment_id: ingest_event(u, shipment_id, r), ("CarrierRep",)),
    ("GET", "/shipments/<shipment_id>/events", lambda u, r, shipment_id: list_shipment_events(u, shipment_id, r), READ_ROLES),
    ("POST", "/shipments/<shipment_id>/events/<event_id>/void", lambda u, r, shipment_id, event_id: void_event(u, shipment_id, event_id), ("NetworkOps",)),
    ("POST", "/shipments/<shipment_id>/recompute-eta", lambda u, r, shipment_id: recompute_eta_endpoint(u, shipment_id), ("NetworkOps",)),
    ("POST", "/shipments/<shipment_id>/cancel", lambda u, r, shipment_id: cancel_shipment(u, shipment_id), ("ShipperRep",)),

    # Identity links
    ("POST", "/shipments/<shipment_id>/identity-links", lambda u, r, shipment_id: create_identity_link(u, shipment_id, r), ("NetworkOps",)),
    ("GET", "/shipments/<shipment_id>/identity-links", lambda u, r, shipment_id: list_shipment_identity_links(u, shipment_id, r), READ_ROLES),
    ("POST", "/identity-links/<link_id>/confirm", lambda u, r, link_id: confirm_identity_link(u, link_id), ("ShipperRep",)),
    ("POST", "/identity-links/<link_id>/reject", lambda u, r, link_id: reject_identity_link(u, link_id), ("ShipperRep",)),

    # Alerts
    ("GET", "/alerts", lambda u, r: list_alerts(u, r), ("CustomerService", "NetworkOps", "PlatformAdmin")),
    ("GET", "/shipments/<shipment_id>/alerts", lambda u, r, shipment_id: list_shipment_alerts(u, shipment_id, r), READ_ROLES),
    ("POST", "/alerts/<alert_id>/acknowledge", lambda u, r, alert_id: acknowledge_alert(u, alert_id), ("CustomerService",)),
    ("POST", "/alerts/<alert_id>/resolve", lambda u, r, alert_id: resolve_alert(u, alert_id, r), ("CustomerService",)),

    # Appointments
    ("POST", "/facilities/<facility_id>/appointments", lambda u, r, facility_id: create_appointment(u, facility_id, r), ("CarrierRep",)),
    ("GET", "/facilities/<facility_id>/appointments", lambda u, r, facility_id: list_facility_appointments(u, facility_id, r), READ_ROLES),
    ("GET", "/appointments", lambda u, r: list_appointments(u, r), READ_ROLES),
    ("GET", "/appointments/<appointment_id>", lambda u, r, appointment_id: get_appointment_endpoint(u, appointment_id), READ_ROLES),
    ("POST", "/appointments/<appointment_id>/complete", lambda u, r, appointment_id: complete_appointment(u, appointment_id, r), ("CarrierRep",)),
    ("POST", "/appointments/<appointment_id>/void-completion", lambda u, r, appointment_id: void_completion(u, appointment_id), ("NetworkOps",)),

    # Data-share grants
    ("POST", "/shippers/<shipper_id>/data-share-grants", lambda u, r, shipper_id: create_data_share_grant(u, shipper_id, r), ("ShipperRep",)),
    ("POST", "/data-share-grants/<grant_id>/revoke", lambda u, r, grant_id: revoke_data_share_grant(u, grant_id), ("ShipperRep",)),

    # Clock + ops
    ("POST", "/_clock/set_current_utc", lambda u, r: set_clock(u, r), ("PlatformAdmin",)),
    ("POST", "/_ops/run-checkpoint", lambda u, r: run_checkpoint(u), ("PlatformAdmin",)),
]
