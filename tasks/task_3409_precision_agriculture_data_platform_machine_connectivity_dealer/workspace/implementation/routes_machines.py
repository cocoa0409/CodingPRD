"""Machines: registration, activation handshake, modem provisioning,
telemetry ingest, and the uptime-prediction computed read (PRD 3.1-3.2, 3.8)."""

from decimal import Decimal

from flask import Blueprint, request

from auth import (
    as_date,
    as_dt,
    as_enum,
    as_pos_int,
    as_str,
    as_num,
    body_json,
    caller,
    can_see_scope,
    get_or_404,
    list_resources,
    need,
    require_role,
    scoped_gate,
    access_denied,
)
from constants import PROVISIONING_MAX_ATTEMPTS, UPTIME_WINDOW_HOURS
from db import STORES, TELEMETRY, now
from domain import (
    compute_posture,
    compute_uptime,
    compute_usage_posture,
    machine_plan,
    new_record,
    parts_recommendation,
    recompute_posture,
    serialize,
    touch,
)
from envelope import created, ok, ok_list
from errors import (
    ERR_DUPLICATE_TELEMETRY_BATCH,
    ERR_DEALER_SUSPENDED,
    ERR_INVALID_REQUEST,
    ERR_MACHINE_POSTURE_BLOCKED,
    ERR_MODEM_NOT_PROVISIONED,
    ERR_NOT_FOUND,
    ERR_ORG_SUSPENDED,
    ERR_PLAN_NOT_ACTIVE,
    ERR_PROVISIONING_ATTEMPTS_EXHAUSTED,
    ApiError,
    invalid_state,
)

bp = Blueprint("machines", __name__)

READ_ROLES = {
    "GrowerManager",
    "DealerTechnician",
    "Agronomist",
    "CoopAnalyst",
    "PartnerApp",
    "PlatformAdmin",
}


@bp.post("/machines")
def create_machine():
    uid, role = caller()
    require_role(role, {"GrowerManager", "PlatformAdmin"})
    b = body_json()
    organization_id = as_str(need(b, "organization_id"), "organization_id")
    serial_number = as_str(need(b, "serial_number"), "serial_number")
    model_code = as_str(need(b, "model_code"), "model_code")
    selling_dealer_id = as_str(need(b, "selling_dealer_id"), "selling_dealer_id")
    modem_imei = as_str(need(b, "modem_imei"), "modem_imei")
    manufacture_date = as_date(need(b, "manufacture_date"), "manufacture_date")
    # Existence: body foreign keys in declared input order
    get_or_404("organizations", organization_id, "organization")
    get_or_404("dealers", selling_dealer_id, "dealer")
    # Scope: a GrowerManager registers machines only for its own organization
    if role == "GrowerManager" and uid != organization_id:
        raise access_denied("grower may register machines only for its own organization")
    for m in STORES["machines"].values():
        if m["serial_number"] == serial_number:
            raise ApiError(ERR_INVALID_REQUEST, 400, "serial_number must be unique")
        if m["modem_imei"] == modem_imei:
            raise ApiError(ERR_INVALID_REQUEST, 400, "modem_imei must be unique")
    rec = new_record(
        {
            "organization_id": organization_id,
            "serial_number": serial_number,
            "model_code": model_code,
            "selling_dealer_id": selling_dealer_id,
            "manufacture_date": manufacture_date,
            "modem_imei": modem_imei,
            "modem_status": "UNPROVISIONED",
            "provisioning_attempts": 0,
            "modem_firmware_version": None,
            "lifecycle_status": "REGISTERED",
            "connectivity_posture": "OFFLINE",
            "active_license_count": 0,
            "activating_dealer_id": None,
            "activated_at": None,
        }
    )
    STORES["machines"][rec["id"]] = rec
    return created(serialize(rec))


@bp.get("/machines/<mid>")
def get_machine(mid):
    uid, role = caller()
    require_role(role, READ_ROLES)
    m = get_or_404("machines", mid, "machine")
    scoped_gate(m["organization_id"], role, uid, "TELEMATICS")
    return ok(serialize(m))


@bp.get("/machines")
def list_machines():
    uid, role = caller()
    require_role(role, READ_ROLES)
    org_filter = request.args.get("organization_id")
    filters = []
    for f in ("organization_id", "selling_dealer_id", "activating_dealer_id", "lifecycle_status"):
        v = request.args.get(f)
        if v is not None:
            filters.append((f, v))
    if role == "PlatformAdmin":
        visible = lambda r: True
    elif role == "GrowerManager":
        if org_filter is not None and org_filter != uid:
            raise access_denied("grower may list only its own organization")
        visible = lambda r: r["organization_id"] == uid
    else:
        # Callers outside the owning-grower/admin roles must pass an
        # organization_id filter and hold TELEMATICS access to it.
        if org_filter is None:
            raise access_denied("organization_id filter is required")
        if not can_see_scope(org_filter, role, uid, "TELEMATICS"):
            raise access_denied("no TELEMATICS grant on the requested organization")
        visible = lambda r: r["organization_id"] == org_filter
    page, total, limit, offset = list_resources("machines", filters, visible)
    return ok_list([serialize(r) for r in page], total, limit, offset)


@bp.post("/machines/<mid>/activate")
def activate_machine(mid):
    uid, role = caller()
    require_role(role, {"DealerTechnician"})
    m = get_or_404("machines", mid, "machine")
    dealer = STORES["dealers"].get(uid)
    if dealer is None:
        raise ApiError(ERR_NOT_FOUND, 404, "caller dealer not found")
    # Preconditions in the PRD's pinned order (section 3.1)
    if m["lifecycle_status"] != "REGISTERED":
        raise invalid_state("machine is not REGISTERED")
    if dealer["status"] != "ACTIVE":
        raise ApiError(ERR_DEALER_SUSPENDED, 409, "dealer is SUSPENDED")
    org = STORES["organizations"].get(m["organization_id"])
    if org is None or org["status"] != "ACTIVE":
        raise ApiError(ERR_ORG_SUSPENDED, 409, "owning organization is SUSPENDED")
    if m["modem_status"] != "PROVISIONED":
        raise ApiError(ERR_MODEM_NOT_PROVISIONED, 409, "modem is not PROVISIONED")
    plan = machine_plan(m["id"])
    if plan is None or plan["status"] != "ACTIVE":
        raise ApiError(ERR_PLAN_NOT_ACTIVE, 409, "no ACTIVE data plan for the machine")
    m["lifecycle_status"] = "ACTIVATED"
    m["activating_dealer_id"] = uid
    m["activated_at"] = now()
    touch(m)
    recompute_posture(m)
    return ok(serialize(m))


@bp.post("/machines/<mid>/provision-modem")
def provision_modem(mid):
    uid, role = caller()
    require_role(role, {"DealerTechnician", "PlatformAdmin"})
    m = get_or_404("machines", mid, "machine")
    if m["modem_status"] not in ("UNPROVISIONED", "PROVISION_FAILED"):
        raise invalid_state("modem provisioning cannot begin from %s" % m["modem_status"])
    if m["provisioning_attempts"] >= PROVISIONING_MAX_ATTEMPTS:
        raise ApiError(
            ERR_PROVISIONING_ATTEMPTS_EXHAUSTED, 409, "provisioning attempts exhausted"
        )
    m["modem_status"] = "PROVISIONING"
    m["provisioning_attempts"] += 1
    touch(m)
    recompute_posture(m)
    return ok(serialize(m))


@bp.post("/machines/<mid>/modem-provisioning-events")
def modem_provisioning_event(mid):
    uid, role = caller()
    require_role(role, {"System"})
    b = body_json()
    outcome = as_enum(
        need(b, "outcome"), "outcome", {"PROVISION_SUCCEEDED", "PROVISION_FAILED"}
    )
    m = get_or_404("machines", mid, "machine")
    if m["modem_status"] != "PROVISIONING":
        raise invalid_state("modem is not PROVISIONING")
    m["modem_status"] = "PROVISIONED" if outcome == "PROVISION_SUCCEEDED" else "PROVISION_FAILED"
    touch(m)
    recompute_posture(m)
    return ok(serialize(m))


@bp.post("/machines/<mid>/telemetry-ingest")
def telemetry_ingest(mid):
    uid, role = caller()
    require_role(role, {"System"})
    b = body_json()
    batch_id = as_str(need(b, "batch_id"), "batch_id")
    start_hour = as_dt(need(b, "start_hour_iso"), "start_hour_iso")
    hour_count = as_pos_int(need(b, "hour_count"), "hour_count")
    payload_mb = as_num(need(b, "payload_mb"), "payload_mb")
    if Decimal(str(payload_mb)) < 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, "payload_mb must be non-negative")
    m = get_or_404("machines", mid, "machine")
    # Acceptance gates in the pinned order: modem, then plan, then usage
    if m["modem_status"] != "PROVISIONED":
        raise ApiError(ERR_MODEM_NOT_PROVISIONED, 409, "modem is not PROVISIONED")
    plan = machine_plan(m["id"])
    if plan is None or plan["status"] != "ACTIVE":
        raise ApiError(ERR_PLAN_NOT_ACTIVE, 409, "no ACTIVE data plan for the machine")
    if plan["usage_posture"] == "EXHAUSTED":
        raise ApiError(ERR_MACHINE_POSTURE_BLOCKED, 409, "usage is EXHAUSTED")
    batches = TELEMETRY.setdefault(m["id"], {})
    if batch_id in batches:
        raise ApiError(
            ERR_DUPLICATE_TELEMETRY_BATCH, 409, "batch_id already accepted for this machine"
        )
    batches[batch_id] = {
        "start": start_hour,
        "hour_count": hour_count,
        "payload_mb": Decimal(str(payload_mb)),
    }
    plan["used_mb"] = plan["used_mb"] + Decimal(str(payload_mb))
    plan["usage_posture"] = compute_usage_posture(plan)
    touch(plan)
    recompute_posture(m)
    if m["lifecycle_status"] == "ACTIVATED":
        # The first accepted telemetry batch flips the machine IN_SERVICE
        m["lifecycle_status"] = "IN_SERVICE"
        touch(m)
    return created(serialize(m))


@bp.get("/machines/<mid>/uptime-prediction")
def uptime_prediction(mid):
    uid, role = caller()
    require_role(role, READ_ROLES)
    m = get_or_404("machines", mid, "machine")
    scoped_gate(m["organization_id"], role, uid, "TELEMATICS")
    conservative, optimistic, filled, bridged = compute_uptime(m["id"])
    return ok(
        {
            "optimistic_score": optimistic,
            "conservative_score": conservative,
            "window_hours": UPTIME_WINDOW_HOURS,
            "filled_hours": filled,
            "bridged_hours": bridged,
            "parts_recommendation": parts_recommendation(conservative),
        }
    )
