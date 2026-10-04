"""Volunteer services, the append-only service-event log, service close
(completion / early termination with the readjustment ledger), and site
placements."""
from flask import Blueprint, request

from authz import auth, require_roles
from calc import months_served, penalized_month_cents, whole_days
from db import (ET_SHORT_SERVICE_THRESHOLD_MONTHS, NCE_DURATION_MONTHS,
                NCE_MIN_MONTHS_SERVED, READJUSTMENT_MONTHLY_RATE_CENTS, ROLES,
                STORE, fmt_ts, logical_now, new_id, new_record, now_iso,
                parse_dt, touch, ts_sec)
from errors import err, ok_object, paginate
from validate import as_bool, as_dt, as_enum, as_str, body

bp = Blueprint("service", __name__)

EVENT_TYPES = ("MEDICAL_CARE", "SAFETY_INCIDENT", "SECURITY_ALERT", "ALL_CLEAR",
               "COMMENDATION")
SEVERITIES = ("ROUTINE", "URGENT", "CRITICAL")
ET_REASONS = ("MEDICAL", "FAMILY", "SECURITY", "ADMINISTRATIVE")


def get_service_or_404(sid):
    service = STORE["volunteer_services"].get(sid)
    if service is None:
        err("ERR_SERVICE_NOT_FOUND", 404, "Volunteer service not found")
    return service


def get_placement_or_404(pid):
    placement = STORE["site_placements"].get(pid)
    if placement is None:
        err("ERR_PLACEMENT_NOT_FOUND", 404, "Site placement not found")
    return placement


@bp.get("/volunteer-portal/volunteer-services/<sid>")
def get_service(sid):
    auth()
    require_roles(request.headers.get("X-User-Role"), ROLES)
    return ok_object(get_service_or_404(sid))


@bp.get("/volunteer-portal/volunteer-services")
def list_services():
    auth()
    require_roles(request.headers.get("X-User-Role"), ROLES)
    args = request.args
    records = sorted(STORE["volunteer_services"].values(),
                     key=lambda r: r["created_at"])
    for field in ("application_id", "assignment_opening_id", "country_program_id",
                  "status"):
        if args.get(field) is not None:
            records = [r for r in records if r[field] == args[field]]
    return paginate(records)


# --- ServiceEvent ------------------------------------------------------------
@bp.post("/volunteer-portal/volunteer-services/<sid>/events")
def create_event(sid):
    auth()
    role = request.headers.get("X-User-Role")
    require_roles(role, ("CountryDirector", "MedicalOfficer"))
    data = body()
    # A MedicalOfficer may log only MEDICAL_CARE events (role grant).
    if role == "MedicalOfficer" and data.get("event_type") != "MEDICAL_CARE":
        err("ERR_FORBIDDEN", 403, "MedicalOfficer may log only MEDICAL_CARE events")
    service = get_service_or_404(sid)
    event_type = as_enum(data, "event_type", EVENT_TYPES)
    severity = as_enum(data, "severity", SEVERITIES)
    description = as_str(data, "description")
    occurred = as_dt(data, "occurred_at")
    # Append-only log: id + created_at only — no updated_at, no version.
    rec = {"id": new_id(), "created_at": now_iso()}
    rec.update({
        "volunteer_service_id": sid,
        "event_type": event_type,
        "severity": severity,
        "description": description,
        "occurred_at": fmt_ts(occurred),
    })
    STORE["service_events"][rec["id"]] = rec
    if (event_type == "SECURITY_ALERT" and severity == "CRITICAL"
            and service["status"] == "ACTIVE"):
        service["status"] = "SUSPENDED"
        touch(service)
    elif event_type == "ALL_CLEAR" and service["status"] == "SUSPENDED":
        service["status"] = "ACTIVE"
        touch(service)
    return ok_object(rec, 201)


@bp.get("/volunteer-portal/volunteer-services/<sid>/events")
def list_events(sid):
    auth()
    require_roles(request.headers.get("X-User-Role"), ROLES)
    get_service_or_404(sid)
    records = [e for e in STORE["service_events"].values()
               if e["volunteer_service_id"] == sid]
    # Chronological by occurred_at, tie-break created_at ascending.
    records.sort(key=lambda r: (parse_dt(r["occurred_at"]), r["created_at"]))
    return paginate(records)


# --- Close of service --------------------------------------------------------
def close_service(service, completion_type, et_reason):
    """Shared close path: stamp end, compute durations, write the completion
    record per readjustment_allowance, end every live site placement."""
    end = logical_now()
    start = parse_dt(service["service_start_date"])
    days = whole_days(end, start)
    months = months_served(days)
    service["actual_end_date"] = fmt_ts(end)
    service["days_served"] = days
    service["months_served"] = months
    touch(service)
    gross = months * READJUSTMENT_MONTHLY_RATE_CENTS
    if completion_type == "FULL" or months >= ET_SHORT_SERVICE_THRESHOLD_MONTHS:
        paid = gross
    else:
        paid = months * penalized_month_cents()
    nce_eligible = (months >= NCE_MIN_MONTHS_SERVED
                    and (completion_type == "FULL" or et_reason == "MEDICAL"))
    rec = new_record()
    rec.update({
        "volunteer_service_id": service["id"],
        "completion_type": completion_type,
        "et_reason": et_reason,
        "months_served": months,
        "gross_accrued_cents": gross,
        "allowance_paid_cents": paid,
        "allowance_forfeited_cents": gross - paid,
        "nce_eligible": nce_eligible,
        "nce_duration_months": NCE_DURATION_MONTHS if nce_eligible else 0,
    })
    STORE["completion_records"][rec["id"]] = rec
    for placement in STORE["site_placements"].values():
        if (placement["volunteer_service_id"] == service["id"]
                and placement["status"] in ("PROPOSED", "CONFIRMED", "REJECTED")):
            placement["status"] = "ENDED"
            touch(placement)


@bp.post("/volunteer-portal/volunteer-services/<sid>/early-terminate")
def early_terminate(sid):
    auth()
    require_roles(request.headers.get("X-User-Role"), ("CountryDirector",))
    service = get_service_or_404(sid)
    if service["status"] not in ("ACTIVE", "SUSPENDED"):
        err("ERR_SERVICE_NOT_ACTIVE", 409,
            "early-terminate requires ACTIVE or SUSPENDED, found %s"
            % service["status"])
    data = body()
    reason = as_enum(data, "reason", ET_REASONS)
    service["status"] = "EARLY_TERMINATED"
    close_service(service, "EARLY", reason)
    return ok_object(service)


@bp.post("/volunteer-portal/volunteer-services/<sid>/complete")
def complete_service(sid):
    auth()
    require_roles(request.headers.get("X-User-Role"), ("CountryDirector",))
    service = get_service_or_404(sid)
    if service["status"] != "ACTIVE":
        err("ERR_SERVICE_NOT_ACTIVE", 409,
            "complete requires ACTIVE, found %s" % service["status"])
    # Temporal gate (priority 9): logical clock must have reached the term end.
    expected = parse_dt(service["expected_completion_date"])
    if ts_sec(logical_now()) < ts_sec(expected):
        err("ERR_SERVICE_TERM_NOT_REACHED", 422,
            "Logical clock has not reached expected_completion_date")
    service["status"] = "COMPLETED"
    close_service(service, "FULL", None)
    return ok_object(service)


@bp.get("/volunteer-portal/volunteer-services/<sid>/completion-record")
def get_completion_record(sid):
    auth()
    require_roles(request.headers.get("X-User-Role"), ROLES)
    get_service_or_404(sid)
    records = sorted(
        (cr for cr in STORE["completion_records"].values()
         if cr["volunteer_service_id"] == sid),
        key=lambda r: r["created_at"])
    return paginate(records)


# --- SitePlacement -----------------------------------------------------------
@bp.post("/volunteer-portal/volunteer-services/<sid>/site-placements")
def create_placement(sid):
    auth()
    require_roles(request.headers.get("X-User-Role"), ("CountryDirector",))
    service = get_service_or_404(sid)
    if service["status"] != "ACTIVE":
        err("ERR_SERVICE_NOT_ACTIVE", 409,
            "site placement requires an ACTIVE service, found %s"
            % service["status"])
    data = body()
    community = as_str(data, "host_community_name")
    org = as_str(data, "counterpart_org_name")
    rec = new_record()
    rec.update({
        "volunteer_service_id": sid,
        "host_community_name": community,
        "counterpart_org_name": org,
        "counterpart_agreement_signed": False,
        "has_running_water": False,
        "structurally_sound": False,
        "secure_locks": False,
        "inspection_passed": False,
        "status": "PROPOSED",
    })
    STORE["site_placements"][rec["id"]] = rec
    return ok_object(rec, 201)


@bp.get("/volunteer-portal/volunteer-services/<sid>/site-placements")
def list_placements(sid):
    auth()
    require_roles(request.headers.get("X-User-Role"), ROLES)
    get_service_or_404(sid)
    records = sorted(
        (p for p in STORE["site_placements"].values()
         if p["volunteer_service_id"] == sid),
        key=lambda r: r["created_at"])
    return paginate(records)


@bp.post("/volunteer-portal/site-placements/<pid>/review")
def review_placement(pid):
    auth()
    require_roles(request.headers.get("X-User-Role"), ("CountryDirector",))
    placement = get_placement_or_404(pid)
    # State guards (priority 6): placement reviewable, then service ACTIVE.
    if placement["status"] not in ("PROPOSED", "REJECTED"):
        err("ERR_INVALID_STATE", 409,
            "review requires PROPOSED or REJECTED, found %s" % placement["status"])
    service = STORE["volunteer_services"].get(placement["volunteer_service_id"])
    if service is None or service["status"] != "ACTIVE":
        err("ERR_SERVICE_NOT_ACTIVE", 409,
            "review requires an ACTIVE volunteer service")
    data = body()
    decision = data.get("decision")
    # Constraint gates (priority 8) for a valid CONFIRM decision.
    if decision == "CONFIRM":
        if data.get("counterpart_agreement_signed") is not True:
            err("ERR_AGREEMENT_NOT_SIGNED", 422,
                "CONFIRM requires counterpart_agreement_signed=true")
        if not (data.get("has_running_water") is True
                and data.get("structurally_sound") is True
                and data.get("secure_locks") is True):
            err("ERR_HOUSING_STANDARDS_NOT_MET", 422,
                "CONFIRM requires all three housing standards to be true")
    # Field shape (priority 10)
    decision = as_enum(data, "decision", ("CONFIRM", "REJECT"))
    agreement = as_bool(data, "counterpart_agreement_signed")
    water = as_bool(data, "has_running_water")
    sound = as_bool(data, "structurally_sound")
    locks = as_bool(data, "secure_locks")
    placement["counterpart_agreement_signed"] = agreement
    placement["has_running_water"] = water
    placement["structurally_sound"] = sound
    placement["secure_locks"] = locks
    placement["inspection_passed"] = bool(water and sound and locks)
    placement["status"] = "CONFIRMED" if decision == "CONFIRM" else "REJECTED"
    touch(placement)
    return ok_object(placement)
