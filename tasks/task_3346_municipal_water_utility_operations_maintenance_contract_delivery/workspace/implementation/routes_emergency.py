"""Emergency event endpoints — PRD 3.7."""
from datetime import timedelta

import calc
import services
from core import (ApiError, DB, apply, arg, body, bump, create, dec, endpoint,
                  field, get, iso, now, now_iso, ordered, own, paginate,
                  parse_dt, set_status, str_field)

EVENT_TYPES = ("MAIN_BREAK", "SANITARY_OVERFLOW", "TREATMENT_UPSET", "POWER_LOSS",
               "CONTAMINATION")
SEVERITIES = ("LOW", "MEDIUM", "HIGH", "CRITICAL")
ESCALATION_MINUTES = 240
REQUIRED_ACKNOWLEDGEMENTS = 2


def event_or_404(event_id):
    return get("emergencies", event_id, "ERR_EMERGENCY_NOT_FOUND")


def load(event_id):
    event = event_or_404(event_id)
    own(event)
    return event


def _active_permit(contract_id):
    return services.active_permit(contract_id)


# --------------------------------------------------------------------------
# reporting / reading
# --------------------------------------------------------------------------
@endpoint("/contracts/<id>/emergency-events", ["GET"],
          ["PlatformAdmin", "MunicipalityAdmin", "OperatorAdmin"])
def list_contract_events(id):
    contract = get("contracts", id, "ERR_CONTRACT_NOT_FOUND")
    own(contract)
    return paginate(ordered(services.emergencies_of(
        contract_id=contract["id"], status=arg("status"),
        event_type=arg("event_type"), severity=arg("severity"))))


@endpoint("/contracts/<id>/emergency-events", ["POST"], ["OperatorAdmin"], status=201)
def report_event(id):
    contract = get("contracts", id, "ERR_CONTRACT_NOT_FOUND")
    own(contract)
    data = body()
    asset = get("assets", str_field(data, "asset_id"), "ERR_ASSET_NOT_FOUND")
    event_type = str_field(data, "event_type")
    severity = str_field(data, "severity")
    if event_type not in EVENT_TYPES:
        raise ApiError("ERR_INVALID_DATE_WINDOW", "Unknown event_type.")
    if severity not in SEVERITIES:
        raise ApiError("ERR_INVALID_DATE_WINDOW", "Unknown severity.")
    occurred_at = parse_dt(field(data, "occurred_at"))
    if asset["contract_id"] != contract["id"]:
        raise ApiError("ERR_ASSET_CONTRACT_MISMATCH")
    return create("emergencies",
                  contract_id=contract["id"],
                  asset_id=asset["id"],
                  event_type=event_type,
                  severity=severity,
                  occurred_at=occurred_at.isoformat().replace("+00:00", "Z"),
                  notify_deadline_at=None,
                  notified_at=None,
                  notification_late=False,
                  response_minutes=0.0,
                  status="REPORTED")


@endpoint("/emergency-events/<id>", ["GET"],
          ["PlatformAdmin", "MunicipalityAdmin", "OperatorAdmin"])
def read_event(id):
    return load(id)


# --------------------------------------------------------------------------
# lifecycle
# --------------------------------------------------------------------------
@endpoint("/emergency-events/<id>/dispatch", ["POST"], ["OperatorAdmin"])
def dispatch_event(id):
    event = load(id)
    if event["status"] == "CLOSED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if event["status"] != "REPORTED":
        raise ApiError("ERR_EMERGENCY_INVALID_STATE")
    contract = DB["contracts"][event["contract_id"]]
    if contract["status"] not in ("OPERATING", "UNDER_REVIEW", "RENEWED"):
        raise ApiError("ERR_EMERGENCY_INVALID_STATE")
    deadline = calc.notification_deadline(parse_dt(event["occurred_at"]),
                                          event["event_type"], event["severity"])
    set_status(event, "DISPATCHED", notify_deadline_at=iso(deadline))
    services.acknowledge(event, "dispatch")
    return event


@endpoint("/emergency-events/<id>/contain", ["POST"], ["OperatorAdmin"])
def contain_event(id):
    event = load(id)
    if event["status"] == "CLOSED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if event["status"] != "DISPATCHED":
        raise ApiError("ERR_EMERGENCY_INVALID_STATE")
    contained_at = parse_dt(field(body(), "contained_at"))
    occurred_at = parse_dt(event["occurred_at"])
    if contained_at < occurred_at:
        raise ApiError("ERR_CONTAINMENT_WINDOW_EXCEEDED")
    if event["severity"] == "CRITICAL":
        deadline = parse_dt(event.get("notify_deadline_at"))
        if deadline is None or contained_at > deadline:
            raise ApiError("ERR_CONTAINMENT_WINDOW_EXCEEDED")
    minutes = (contained_at - occurred_at).total_seconds() / 60.0
    set_status(event, "CONTAINED",
               _contained_at=iso(contained_at),
               response_minutes=round(minutes, 4))
    services.acknowledge(event, "contain")
    standard = calc.applicable_response_standard(event["contract_id"])
    if standard is not None and dec(minutes) > dec(standard["threshold_value"]):
        services.mark_breached(standard, standard["metric_type"])
    return event


@endpoint("/emergency-events/<id>/restore", ["POST"], ["OperatorAdmin"])
def restore_event(id):
    event = load(id)
    if event["status"] == "CLOSED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if event["status"] != "CONTAINED":
        raise ApiError("ERR_EMERGENCY_INVALID_STATE")
    restored_at = parse_dt(field(body(), "restored_at"))
    if event["event_type"] == "SANITARY_OVERFLOW" and not event.get("_contained_at"):
        raise ApiError("ERR_OVERFLOW_CONTAINMENT_REQUIRED")
    for work_order in DB["work_orders"].values():
        if work_order["asset_id"] == event["asset_id"] \
                and work_order["status"] in ("IN_PROGRESS", "AWAITING_PARTS"):
            raise ApiError("ERR_EMERGENCY_INVALID_STATE")
    set_status(event, "RESTORED", _restored_at=iso(restored_at))
    services.acknowledge(event, "restore")
    return event


@endpoint("/emergency-events/<id>/notify", ["POST"], ["OperatorAdmin"])
def notify_event(id):
    event = load(id)
    if event["status"] == "CLOSED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if event["status"] not in ("CONTAINED", "RESTORED"):
        raise ApiError("ERR_EMERGENCY_INVALID_STATE")
    str_field(body(), "notification_reference")
    if services.is_critical_notification(event) and not event.get("_contained_at"):
        raise ApiError("ERR_CONTAMINATION_CONTAINMENT_REQUIRED")
    deadline = parse_dt(event.get("notify_deadline_at"))
    if deadline is None:
        deadline = calc.notification_deadline(parse_dt(event["occurred_at"]),
                                              event["event_type"], event["severity"])
    if now() > deadline:
        raise ApiError("ERR_NOTIFICATION_WINDOW_CLOSED")
    late = calc.is_notification_late(now(), deadline)
    was_contained = event["status"] == "CONTAINED"
    set_status(event, "NOTIFIED",
               notified_at=now_iso(),
               notification_late=late,
               notify_deadline_at=iso(deadline))
    services.acknowledge(event, "notify")
    if late and was_contained:
        permit = _active_permit(event["contract_id"])
        if permit is not None:
            set_status(permit, "NOTICE_OF_VIOLATION")
    return event


@endpoint("/emergency-events/<id>/escalate", ["POST"], ["MunicipalityAdmin"])
def escalate_event(id):
    event = load(id)
    if event["status"] == "CLOSED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    data = body()
    str_field(data, "escalation_basis")
    contract = DB["contracts"][event["contract_id"]]
    if event["status"] == "CONTAINED":
        if event["severity"] not in ("HIGH", "CRITICAL"):
            raise ApiError("ERR_EMERGENCY_INVALID_STATE")
        if now() < parse_dt(event["occurred_at"]) + timedelta(minutes=ESCALATION_MINUTES):
            raise ApiError("ERR_EMERGENCY_INVALID_STATE")
        for commitment in services.commitments_of(contract["id"]):
            if commitment["status"] in ("BINDING", "SATISFIED"):
                apply(commitment, _emergency_restaff=True)
        if contract["status"] == "OPERATING":
            set_status(contract, "UNDER_REVIEW")
    elif event["status"] == "RESTORED":
        if event["severity"] != "CRITICAL":
            raise ApiError("ERR_EMERGENCY_INVALID_STATE")
        if contract["status"] == "OPERATING":
            set_status(contract, "UNDER_REVIEW")
    else:
        raise ApiError("ERR_EMERGENCY_INVALID_STATE")
    set_status(event, "ESCALATED")
    return event


@endpoint("/emergency-events/<id>/investigate", ["POST"], ["MunicipalityAdmin"])
def investigate_event(id):
    event = load(id)
    if event["status"] == "CLOSED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    contract = DB["contracts"][event["contract_id"]]
    if event["status"] == "NOTIFIED":
        if not event.get("notified_at"):
            raise ApiError("ERR_EMERGENCY_INVALID_STATE")
    elif event["status"] == "ESCALATED":
        permit = _active_permit(event["contract_id"])
        if permit is not None:
            allocation = create("allocations",
                                permit_id=permit["id"],
                                contract_id=contract["id"],
                                violation_code=event["event_type"],
                                total_penalty_cents=0,
                                operator_share_cents=0,
                                municipality_share_cents=0,
                                state_baseline_share_cents=0,
                                status="ALLOCATED",
                                _emergency_event_id=event["id"])
            bump(contract)
    else:
        raise ApiError("ERR_EMERGENCY_INVALID_STATE")
    set_status(event, "UNDER_INVESTIGATION")
    return event


@endpoint("/emergency-events/<id>/close", ["POST"], ["MunicipalityAdmin"])
def close_event(id):
    event = load(id)
    if event["status"] == "CLOSED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if event["status"] != "UNDER_INVESTIGATION":
        raise ApiError("ERR_EMERGENCY_INVALID_STATE")
    if services.is_critical_notification(event) \
            and services.acknowledgements(event) < REQUIRED_ACKNOWLEDGEMENTS:
        raise ApiError("ERR_CRITICAL_ACKNOWLEDGEMENT_MISSING")
    for allocation in DB["allocations"].values():
        if allocation.get("_emergency_event_id") == event["id"] \
                and allocation["status"] in ("ALLOCATED", "CONTESTED"):
            raise ApiError("ERR_ALREADY_TERMINAL")
    set_status(event, "CLOSED")
    return event
