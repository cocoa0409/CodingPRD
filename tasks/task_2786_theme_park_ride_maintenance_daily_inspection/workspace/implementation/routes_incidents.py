"""Guest incidents, the four-hop ride-hold cascade and the regulator branch."""

from datetime import timedelta

from flask import Blueprint, g

import derive
import fetch
import store
import validate
from auth import ALL_ROLES, require_roles
from envelope import list_response
from errors import (
    fail,
    ERR_INCIDENT_STATE_INVALID,
    ERR_NOTIFICATION_NOT_REQUIRED,
    ERR_REGULATOR_CLEARANCE_REQUIRED,
)
from reply import computed, made, saved

bp = Blueprint("incidents", __name__)

SEVERITIES = ("NONE", "MINOR", "SERIOUS", "FATAL")
REPORTABLE = ("SERIOUS", "FATAL")
REGULATOR_NOTIFICATION_HOURS = 24
CLEARABLE = ("REGULATOR_NOTIFIED", "INTERNAL_REVIEW_CLOSED")


def _hold_cascade(incident, attraction):
    """Hops one through four of PRD 3.8.

    Hop one (regulatory_hold) and hops two and four (posture and
    certified_operator_count) are derived at read time, so the only state this
    has to write is hop three: the suspension of the certified workforce.
    """
    certified = derive.certified_certifications(attraction)
    certified = sorted(certified, key=lambda c: (c["effective_from"], c["_seq"]))
    stamp = store.now_iso()
    for certification in certified:
        certification["suspended_at"] = stamp
        certification["suspension_reason"] = "RIDE_HOLD"
    incident["_suspended_certification_ids"] = [c["id"] for c in certified]
    incident["suspended_certification_count"] = len(certified)


@bp.post("/park-ops/incidents")
@require_roles("SafetyOfficer")
def file_incident():
    data = validate.body()
    attraction = fetch.fk("attractions", data.get("attraction_id"))
    validate.id_field(data, "attraction_id")
    occurred_at = validate.instant_field(data, "occurred_at")
    severity = validate.enum_field(data, "injury_severity", SEVERITIES)
    guest_count = validate.int_field(data, "guest_count_affected", minimum=0)
    narrative = validate.str_field(data, "narrative")
    reportable = severity in REPORTABLE
    due_at = None
    if reportable:
        due_at = store.iso(occurred_at
                           + timedelta(hours=REGULATOR_NOTIFICATION_HOURS))
    incident = store.create(
        "incidents",
        attraction_id=attraction["id"],
        occurred_at=store.iso(occurred_at),
        injury_severity=severity,
        guest_count_affected=guest_count,
        narrative=narrative,
        status="RIDE_HELD" if reportable else "REPORTED",
        regulator_notification_due_at=due_at,
        regulator_case_ref=None,
        notified_at=None,
        notified_late=False,
        investigator_user_id=None,
        regulator_clearance_ref=None,
        cleared_at=None,
        suspended_certification_count=0,
        _suspended_certification_ids=[],
    )
    if reportable:
        _hold_cascade(incident, attraction)
    return made(derive.ser_incident, incident)


@bp.get("/park-ops/incidents/<incident_id>")
@require_roles(*ALL_ROLES)
def read_incident(incident_id):
    return computed(derive.ser_incident(fetch.incident(incident_id)))


@bp.get("/park-ops/incidents")
@require_roles(*ALL_ROLES)
def list_incidents():
    return list_response(
        store.rows("incidents"),
        derive.ser_incident,
        filters=(("attraction_id", "str"), ("status", "str"),
                 ("injury_severity", "str"), ("notified_late", "bool")),
        order=("occurred_at",),
    )


@bp.post("/park-ops/incidents/<incident_id>/hold-ride")
@require_roles("SafetyOfficer")
def hold_ride(incident_id):
    incident = fetch.incident(incident_id)
    validate.body()
    if incident["status"] != "REPORTED":
        fail(ERR_INCIDENT_STATE_INVALID,
             "Only a REPORTED incident may be placed on hold.")
    attraction = store.db.attractions.get(incident["attraction_id"])
    incident["status"] = "RIDE_HELD"
    _hold_cascade(incident, attraction)
    return saved(derive.ser_incident, incident)


@bp.post("/park-ops/incidents/<incident_id>/investigate")
@require_roles("SafetyOfficer")
def investigate_incident(incident_id):
    incident = fetch.incident(incident_id)
    validate.body()
    if incident["status"] != "RIDE_HELD":
        fail(ERR_INCIDENT_STATE_INVALID,
             "Only a RIDE_HELD incident may move under investigation.")
    incident["status"] = "UNDER_INVESTIGATION"
    incident["investigator_user_id"] = g.user_id
    return saved(derive.ser_incident, incident)


@bp.post("/park-ops/incidents/<incident_id>/notify-regulator")
@require_roles("SafetyOfficer")
def notify_regulator(incident_id):
    incident = fetch.incident(incident_id)
    data = validate.body()
    case_ref = validate.str_field(data, "regulator_case_ref")
    if incident["status"] != "UNDER_INVESTIGATION":
        fail(ERR_INCIDENT_STATE_INVALID,
             "Only an incident UNDER_INVESTIGATION may be notified to the "
             "regulator.")
    if incident["injury_severity"] not in REPORTABLE:
        fail(ERR_NOTIFICATION_NOT_REQUIRED,
             "Only a SERIOUS or FATAL incident is reportable to the regulator.")
    notified_at = store.now()
    due_at = store.instant_of(incident["regulator_notification_due_at"])
    incident["status"] = "REGULATOR_NOTIFIED"
    incident["regulator_case_ref"] = case_ref
    incident["notified_at"] = store.iso(notified_at)
    incident["notified_late"] = bool(due_at is not None
                                     and notified_at > due_at)
    return saved(derive.ser_incident, incident)


@bp.post("/park-ops/incidents/<incident_id>/close-internal")
@require_roles("SafetyOfficer")
def close_internal(incident_id):
    incident = fetch.incident(incident_id)
    validate.body()
    if incident["status"] != "UNDER_INVESTIGATION":
        fail(ERR_INCIDENT_STATE_INVALID,
             "Only an incident UNDER_INVESTIGATION may close its internal "
             "review.")
    incident["status"] = "INTERNAL_REVIEW_CLOSED"
    return saved(derive.ser_incident, incident)


@bp.post("/park-ops/incidents/<incident_id>/clear")
@require_roles("SafetyOfficer")
def clear_incident(incident_id):
    incident = fetch.incident(incident_id)
    data = validate.body()
    clearance_ref = validate.str_field(data, "regulator_clearance_ref",
                                       required=False, allow_empty=True)
    if incident["status"] not in CLEARABLE:
        fail(ERR_INCIDENT_STATE_INVALID,
             "Only a REGULATOR_NOTIFIED or INTERNAL_REVIEW_CLOSED incident may "
             "be cleared.")
    branch_a = incident["status"] == "REGULATOR_NOTIFIED"
    if branch_a and not (clearance_ref or "").strip():
        fail(ERR_REGULATOR_CLEARANCE_REQUIRED,
             "Clearing an incident that reached REGULATOR_NOTIFIED requires a "
             "non-empty regulator_clearance_ref.")
    incident["status"] = "CLEARED_TO_OPERATE"
    incident["cleared_at"] = store.now_iso()
    if branch_a:
        incident["regulator_clearance_ref"] = clearance_ref
    for certification_id in incident.get("_suspended_certification_ids", []):
        certification = store.db.certifications.get(certification_id)
        if certification is None or not certification.get("suspended_at"):
            continue
        certification["suspended_at"] = None
        certification["suspension_reason"] = None
    return saved(derive.ser_incident, incident)
