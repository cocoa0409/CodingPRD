"""Sanitation logs, infection investigations and the logical clock with its sweeps."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

import auth
import derive
import envelope
import store
from errors import fail
from helpers import find, scope_establishment
from validate import (body_of, cents, d2, fk, opt_instant, opt_int, req_date, req_dec, req_enum,
                      req_instant, req_int, req_str)

health_bp = Blueprint("health", __name__)
clock_bp = Blueprint("clock", __name__)


def _minutes(value):
    micros = (Decimal(value) * Decimal("60000000")).quantize(Decimal("1"))
    return timedelta(microseconds=int(micros))


# ----------------------------------------------------------- sanitation logs
@health_bp.post("/sanitation-logs")
def create_sanitation_log():
    ctx = auth.authenticate(("BoardAdmin", "EstablishmentOwner", "Practitioner"))
    body = body_of(request)
    ws_id = fk(body, "workstation_id")
    ws = find("Workstation", ws_id) if ws_id is not None else None
    if ws is not None:
        scope_establishment(ctx, ws["establishment_id"])
        if ctx.is_prac and not auth.practitioner_touches_workstation(ctx.user_id, ws):
            auth.deny()
    if ws is None:
        fail("ERR_INVALID_REQUEST", "Field 'workstation_id' is required.")

    log_type = req_enum(body, "log_type", derive.LOG_TYPES)
    performed_at = req_instant(body, "performed_at")
    contact_minutes = req_dec(body, "contact_minutes", gt=0)
    epa = req_str(body, "disinfectant_epa_reg_number")
    batch_count = opt_int(body, "implement_batch_count", minimum=0)

    if log_type == "IMPLEMENT_DISINFECTION":
        if batch_count is None:
            fail("ERR_INVALID_REQUEST",
                 "Field 'implement_batch_count' is required for implement disinfection.")
    elif batch_count is not None:
        fail("ERR_INVALID_REQUEST",
             "Field 'implement_batch_count' must be null for a foot-spa protocol.")

    if d2(contact_minutes) < derive.MIN_CONTACT_MINUTES[log_type]:
        fail("ERR_DISINFECTANT_CONTACT_TIME_INSUFFICIENT",
             "%s requires at least %s minutes of wet contact."
             % (log_type, derive.MIN_CONTACT_MINUTES[log_type]))

    if log_type in derive.FOOT_SPA_LOG_TYPES:
        if ws["station_type"] != "FOOT_SPA":
            fail("ERR_SANITATION_LOG_STATION_TYPE_MISMATCH",
                 "%s may only be logged against a FOOT_SPA station." % log_type)
    elif ws["station_type"] not in derive.IMPLEMENT_STATION_TYPES:
        fail("ERR_SANITATION_LOG_STATION_TYPE_MISMATCH",
             "IMPLEMENT_DISINFECTION may not be logged against a %s station." % ws["station_type"])

    derive.compute_workstation(ws)
    if ws["posting_status"] != "COMPLIANT":
        fail("ERR_WORKSTATION_POSTING_NONCOMPLIANT",
             "The station's posting_status is %s, not COMPLIANT." % ws["posting_status"])

    occupancy_end_at = performed_at + _minutes(contact_minutes)
    if log_type in derive.FOOT_SPA_LOG_TYPES:
        gap = timedelta(minutes=derive.FOOT_SPA_CYCLE_GAP_MINUTES)
        for other in derive.logs_of_workstation(ws["id"]):
            if performed_at >= other["performed_at"]:
                ok = performed_at >= other["occupancy_end_at"] + gap
            else:
                ok = other["performed_at"] >= occupancy_end_at + gap
            if not ok:
                fail("ERR_FOOT_SPA_CYCLE_GAP_VIOLATION",
                     "A foot-spa cycle must begin at least five minutes after the previous "
                     "cycle's occupancy_end_at.")

    row = store.make_row(with_common=False)
    row.update({
        "workstation_id": ws["id"],
        "log_type": log_type,
        "performed_at": performed_at,
        "contact_minutes": d2(contact_minutes),
        "disinfectant_epa_reg_number": epa,
        "implement_batch_count": batch_count,
        "occupancy_end_at": occupancy_end_at,
    })
    store.sanitation_logs[row["id"]] = row

    if log_type == "FOOT_SPA_WEEKLY_BIOFILM":
        derive.refresh_workstation(ws, force=True)
    else:
        derive.compute_workstation(ws)
    est = store.establishments[ws["establishment_id"]]
    derive.refresh_establishment(est, force=True)
    return envelope.ok(derive.ser_sanitation_log(row), 201)


# ------------------------------------------------------- infection incidents
@health_bp.post("/infection-incidents")
def create_incident():
    ctx = auth.authenticate(("BoardAdmin", "Inspector", "EstablishmentOwner",
                             "HealthAuthorityLiaison"))
    body = body_of(request)
    est_id = fk(body, "establishment_id")
    est = find("Establishment", est_id) if est_id is not None else None
    prac_id = fk(body, "suspected_practitioner_id")
    if prac_id is not None:
        find("Practitioner", prac_id)
    if est is not None:
        scope_establishment(ctx, est["id"])
    if est is None:
        fail("ERR_INVALID_REQUEST", "Field 'establishment_id' is required.")

    case_count = req_int(body, "case_count", minimum=1)
    onset_date = req_date(body, "onset_date")
    narrative = req_str(body, "narrative")

    reported_at = store.now_utc()
    row = store.make_row()
    row.update({
        "establishment_id": est["id"],
        "suspected_practitioner_id": prac_id,
        "case_count": case_count,
        "onset_date": onset_date,
        "narrative": narrative,
        "status": "REPORTED",
        "reported_at": reported_at,
        "notification_deadline_at": derive.notification_deadline(reported_at, case_count),
        "notified_at": None,
        "health_authority_reference": None,
        "findings_summary": None,
    })
    store.infection_incidents[row["id"]] = row
    return envelope.ok(derive.ser_incident(row), 201)


@health_bp.post("/infection-incidents/<iid>/notification")
def notify_incident(iid):
    auth.authenticate(("BoardAdmin", "HealthAuthorityLiaison"))
    incident = find("InfectionIncident", iid)
    body = body_of(request)
    reference = req_str(body, "health_authority_reference")
    notified_at = opt_instant(body, "notified_at", default=store.now_utc())

    if incident["status"] not in ("REPORTED", "ESCALATED_OVERDUE"):
        fail("ERR_INCIDENT_NOT_NOTIFIABLE",
             "Incident status %s cannot be notified." % incident["status"])

    incident["status"] = "NOTIFIED"
    incident["notified_at"] = notified_at
    incident["health_authority_reference"] = reference
    store.bump(incident)
    return envelope.ok(derive.ser_incident(incident))


@health_bp.post("/infection-incidents/<iid>/resolution")
def resolve_incident(iid):
    auth.authenticate(("BoardAdmin", "HealthAuthorityLiaison"))
    incident = find("InfectionIncident", iid)
    body = body_of(request)
    resolution = req_enum(body, "resolution", derive.RESOLUTIONS)
    summary = req_str(body, "findings_summary")

    if incident["status"] != "NOTIFIED":
        fail("ERR_INCIDENT_NOT_NOTIFIED",
             "Incident status is %s, not NOTIFIED." % incident["status"])

    incident["findings_summary"] = summary
    if resolution == "UNSUBSTANTIATED":
        incident["status"] = "RESOLVED_UNSUBSTANTIATED"
        store.bump(incident)
        return envelope.ok(derive.ser_incident(incident))

    incident["status"] = "RESOLVED_SUBSTANTIATED"
    store.bump(incident)
    prac_id = incident["suspected_practitioner_id"]
    if prac_id is not None:
        prac = store.practitioners.get(prac_id)
        if prac is not None:
            derive.post_ledger("SANCTION_POINTS", "INFECTION_SANCTION_ASSESSMENT",
                               delta_points=derive.SUBSTANTIATED_SANCTION_POINTS,
                               practitioner_id=prac["id"])
            prac["sanction_points"] = derive.practitioner_sanction_points(prac["id"])
            derive.auto_suspend_practitioner(prac, store.now_utc())
            derive.refresh_practitioner(prac, force=True)
    return envelope.ok(derive.ser_incident(incident))


# ------------------------------------------------------------- logical clock
def _delinquency_sweep(new_value):
    for cit in list(store.citations.values()):
        if cit["status"] not in ("ISSUED", "AFFIRMED", "AMENDED"):
            continue
        if not cit["due_at"] < new_value:
            continue
        outstanding = derive.citation_outstanding(cit["id"])
        if outstanding <= 0:
            continue
        cit["status"] = "DELINQUENT"
        derive.post_ledger("FINE_CENTS", "CITATION_LATE_PENALTY",
                           delta_cents=cents(Decimal(outstanding) * derive.LATE_PENALTY_PCT),
                           citation_id=cit["id"])
        derive.recompute_citation_outstanding(cit)
        store.bump(cit)
        if cit["max_finding_severity"] not in ("CRITICAL", "IMMINENT_HAZARD"):
            continue
        est = derive.establishment_of_citation(cit)
        if est is None or est["license_status"] not in ("ACTIVE", "PROBATION"):
            continue
        est["license_status"] = "SUSPENDED"
        for rental in derive.rentals_of_establishment(est["id"]):
            if rental["status"] == "ACTIVE":
                rental["status"] = "TERMINATED"
                rental["terminated_at"] = new_value
                store.bump(rental)


def _infection_sweep(new_value):
    for incident in list(store.infection_incidents.values()):
        if incident["status"] == "REPORTED" and incident["notification_deadline_at"] < new_value:
            incident["status"] = "ESCALATED_OVERDUE"
            store.bump(incident)


def _expiry_sweep(new_value):
    today = new_value.date()
    for prac in list(store.practitioners.values()):
        if prac["license_status"] != "ACTIVE":
            continue
        expires = prac["license_expires_on"]
        if expires is not None and expires < today:
            prac["license_status"] = "LAPSED"
            store.bump(prac)


@clock_bp.post("/_clock/set_current_utc")
def set_clock():
    auth.authenticate(("BoardAdmin",))
    body = body_of(request)
    target = req_instant(body, "to_iso8601")
    if target <= store.now_utc():
        fail("ERR_CLOCK_MUST_ADVANCE", "The logical clock may only move forward.")

    before_est = dict((e["id"], derive.est_snapshot(e)) for e in store.establishments.values())
    before_ws = dict((w["id"], derive.ws_snapshot(w)) for w in store.workstations.values())

    store.set_clock(target)
    _delinquency_sweep(target)
    _infection_sweep(target)
    _expiry_sweep(target)

    for ws in store.workstations.values():
        derive.compute_workstation(ws)
        if derive.ws_snapshot(ws) != before_ws.get(ws["id"]):
            store.bump(ws)
    for est in store.establishments.values():
        derive.compute_establishment(est)
        if derive.est_snapshot(est) != before_est.get(est["id"]):
            store.bump(est)

    return envelope.ok({})
