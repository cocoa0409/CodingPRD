"""Wait observations, escalation tickets, referrals, surge details, analytics."""

from datetime import timedelta

from flask import Blueprint

import calc
import cascade
import consts
import derive
import envelope
import req
import serial
import store
from errors import bad_request, fail
from util import day_bounds

bp = Blueprint("ops", __name__)


def _guard_suspended(checkpoint):
    if checkpoint is not None and derive.posture(checkpoint) == "SUSPENDED":
        fail("ERR_CHECKPOINT_SUSPENDED", "the checkpoint is suspended")


# ---------------------------------------------------------------------------
# WaitTimeObservation
# ---------------------------------------------------------------------------
OBSERVATION_SPEC = [
    {"name": "lane_type", "kind": "enum", "required": True, "values": consts.LANE_TYPES},
    {
        "name": "sampled_wait_seconds",
        "kind": "integer",
        "required": True,
        "min": 0,
        "max": 7200,
    },
    {
        "name": "measurement_method",
        "kind": "enum",
        "required": True,
        "values": consts.MEASUREMENT_METHODS,
    },
    {"name": "sample_size", "kind": "integer", "required": True, "min": 1, "max": 500},
]


@bp.post("/checkpoints/<checkpoint_id>/wait-observations")
def create_observation(checkpoint_id):
    req.actor(["CheckpointManager", "DutyManager", "SupervisoryOfficer"])
    values = req.parse_body(OBSERVATION_SPEC)
    checkpoint = req.load("checkpoint", checkpoint_id)
    _guard_suspended(checkpoint)
    lane_type = values["lane_type"]
    row = store.base(versioned=False)
    row.update(
        {
            "checkpoint_id": checkpoint["id"],
            "lane_type": lane_type,
            "sampled_wait_seconds": values["sampled_wait_seconds"],
            "measurement_method": values["measurement_method"],
            "sample_size": values["sample_size"],
            "observed_at_utc": store.now(),
            "published_wait_minutes_snapshot": None,
            "breached_threshold": False,
        }
    )
    store.add("wait_time_observations", row)
    publication = calc.published_wait_time(checkpoint, lane_type)
    row["published_wait_minutes_snapshot"] = publication["published_wait_minutes"]
    row["breached_threshold"] = publication["breached"]
    cascade.handle_observation(
        checkpoint, lane_type, publication["published_wait_minutes"], publication["breached"]
    )
    cascade.bump_checkpoint(checkpoint)
    derive.refresh_checkpoint(checkpoint)
    return envelope.obj(serial.wait_time_observation(row), 201)


@bp.get("/wait-observations/<wait_time_observation_id>")
def read_observation(wait_time_observation_id):
    req.actor(req.READ_ROLES)
    row = req.load("wait_time_observation", wait_time_observation_id)
    return envelope.obj(serial.wait_time_observation(row))


@bp.get("/wait-observations")
def list_observations():
    req.actor(req.READ_ROLES)
    limit, offset = req.pagination()
    rows = req.filter_rows(
        store.rows("wait_time_observations"),
        {
            "checkpoint_id": req.query_value("checkpoint_id"),
            "lane_type": req.query_enum("lane_type", consts.LANE_TYPES),
            "measurement_method": req.query_enum(
                "measurement_method", consts.MEASUREMENT_METHODS
            ),
        },
    )
    rows.sort(key=lambda o: (o["observed_at_utc"], o["created_at"], o["_seq"]), reverse=True)
    page, total = req.paginate(rows, limit, offset)
    return envelope.listing(
        serial.many(serial.wait_time_observation, page), limit, offset, total
    )


@bp.get("/checkpoints/<checkpoint_id>/wait-time")
def read_wait_time(checkpoint_id):
    req.actor(req.READ_ROLES)
    lane_type = req.query_enum("lane_type", consts.LANE_TYPES, required=True)
    checkpoint = req.load("checkpoint", checkpoint_id)
    return envelope.obj(store.render(calc.published_wait_time(checkpoint, lane_type)))


@bp.get("/checkpoints/<checkpoint_id>/throughput-analysis")
def read_throughput(checkpoint_id):
    req.actor(["PlatformAdmin", "CheckpointManager", "StaffingPlanner", "DutyManager"])
    checkpoint = req.load("checkpoint", checkpoint_id)
    return envelope.obj(store.render(calc.throughput_and_diversion_index(checkpoint)))


# ---------------------------------------------------------------------------
# EscalationTicket
# ---------------------------------------------------------------------------
@bp.get("/escalation-tickets/<escalation_ticket_id>")
def read_ticket(escalation_ticket_id):
    req.actor(req.READ_ROLES)
    row = req.load("escalation_ticket", escalation_ticket_id)
    return envelope.obj(serial.escalation_ticket(row))


@bp.get("/escalation-tickets")
def list_tickets():
    req.actor(req.READ_ROLES)
    limit, offset = req.pagination()
    rows = req.filter_rows(
        store.rows("escalation_tickets"),
        {
            "checkpoint_id": req.query_value("checkpoint_id"),
            "resolved_lane_id": req.query_value("resolved_lane_id"),
            "acknowledged_by_officer_id": req.query_value("acknowledged_by_officer_id"),
            "state": req.query_enum("state", consts.TICKET_STATES),
            "lane_type_scope": req.query_enum("lane_type_scope", consts.LANE_TYPE_SCOPES),
        },
    )
    rows.sort(key=lambda t: (t["raised_at_utc"], t["created_at"], t["_seq"]))
    page, total = req.paginate(rows, limit, offset)
    return envelope.listing(serial.many(serial.escalation_ticket, page), limit, offset, total)


def _require_supervisor(user_id):
    officer = store.get("officers", user_id)
    if officer is None or "SUPERVISOR" not in officer["certifications"]:
        fail(
            "ERR_SUPERVISOR_CERTIFICATION_REQUIRED",
            "the acting officer lacks the SUPERVISOR certification",
        )
    return officer


@bp.post("/escalation-tickets/<escalation_ticket_id>/acknowledge")
def acknowledge_ticket(escalation_ticket_id):
    _role, user_id = req.actor(["SupervisoryOfficer"])
    ticket = req.load("escalation_ticket", escalation_ticket_id)
    if ticket["state"] != "RAISED":
        fail(
            "ERR_INVALID_STATE_TRANSITION",
            "a %s ticket cannot be acknowledged" % ticket["state"],
        )
    _require_supervisor(user_id)
    ticket["state"] = "ACKNOWLEDGED"
    ticket["acknowledged_at_utc"] = store.now()
    ticket["acknowledged_by_officer_id"] = user_id
    store.touch(ticket)
    return envelope.obj(serial.escalation_ticket(ticket))


RESOLVE_TICKET_SPEC = [
    {
        "name": "resolution",
        "kind": "enum",
        "required": True,
        "values": ("LANE_OPENED", "MITIGATED_BY_DIVERSION"),
    },
    {"name": "resolved_lane_id", "kind": "string", "fk": "lane", "collection": "lanes"},
    {"name": "diverted_pax_count", "kind": "integer", "min": 1},
    {"name": "resolution_note", "kind": "string", "max_len": 500},
]


@bp.post("/escalation-tickets/<escalation_ticket_id>/resolve")
def resolve_ticket(escalation_ticket_id):
    _role, user_id = req.actor(["SupervisoryOfficer"])
    values = req.parse_body(RESOLVE_TICKET_SPEC)
    resolution = values["resolution"]
    if resolution == "LANE_OPENED":
        if "resolved_lane_id" not in values:
            bad_request("resolved_lane_id is required for a LANE_OPENED resolution")
        if "diverted_pax_count" in values:
            bad_request("diverted_pax_count must be absent for a LANE_OPENED resolution")
    else:
        if "diverted_pax_count" not in values:
            bad_request("diverted_pax_count is required for a MITIGATED_BY_DIVERSION resolution")
        if "resolved_lane_id" in values:
            bad_request("resolved_lane_id must be absent for a diversion resolution")
    parents = req.resolve_fks(values, RESOLVE_TICKET_SPEC)
    ticket = req.load("escalation_ticket", escalation_ticket_id)
    if ticket["state"] != "ACKNOWLEDGED":
        fail("ERR_INVALID_STATE_TRANSITION", "a %s ticket cannot be resolved" % ticket["state"])
    _require_supervisor(user_id)
    checkpoint = store.get("checkpoints", ticket["checkpoint_id"])
    if resolution == "LANE_OPENED":
        lane = parents["resolved_lane_id"]
        if (
            lane["checkpoint_id"] != ticket["checkpoint_id"]
            or lane["lane_type"] != ticket["lane_type_scope"]
            or lane["lane_state"] != "OPEN"
        ):
            fail("ERR_RESOLUTION_LANE_INVALID", "the nominated lane cannot resolve this ticket")
        ticket["state"] = "RESOLVED_LANE_OPENED"
        ticket["resolved_lane_id"] = lane["id"]
    else:
        ticket["state"] = "RESOLVED_DIVERTED"
        ticket["diverted_pax_count"] = values["diverted_pax_count"]
        if checkpoint is not None:
            checkpoint["diverted_pax_total"] += values["diverted_pax_count"]
    if "resolution_note" in values:
        ticket["resolution_note"] = values["resolution_note"]
    ticket["resolved_at_utc"] = store.now()
    store.touch(ticket)
    if checkpoint is not None:
        scope = ticket["lane_type_scope"]
        scopes = ("STANDARD", "EXPEDITED") if scope == "ALL" else (scope,)
        for one in scopes:
            checkpoint[cascade.breach_counter_field(one)] = 0
        cascade.bump_checkpoint(checkpoint)
        derive.refresh_checkpoint(checkpoint)
    return envelope.obj(serial.escalation_ticket(ticket))


# ---------------------------------------------------------------------------
# ScreeningReferral
# ---------------------------------------------------------------------------
REFERRAL_SPEC = [
    {"name": "lane_id", "kind": "string", "required": True, "fk": "lane", "collection": "lanes"},
    {
        "name": "referral_reason",
        "kind": "enum",
        "required": True,
        "values": consts.REFERRAL_REASONS,
    },
    {
        "name": "passenger_category",
        "kind": "enum",
        "required": True,
        "values": consts.PASSENGER_CATEGORIES,
    },
    {"name": "requires_private_screening", "kind": "boolean"},
]

CERT_BY_REASON = {
    "ALARM": "ETD_RESOLUTION",
    "DISABILITY_ACCOMMODATION": "SPECIAL_PROCEDURES",
    "MEDICAL_DEVICE": "SPECIAL_PROCEDURES",
    "YOUNG_CHILD": "SPECIAL_PROCEDURES",
}


@bp.post("/screening-referrals")
def create_referral():
    _role, user_id = req.actor(["ScreeningOfficer", "SupervisoryOfficer"])
    values = req.parse_body(REFERRAL_SPEC)
    parents = req.resolve_fks(values, REFERRAL_SPEC)
    lane = parents["lane_id"]
    checkpoint = cascade.checkpoint_of_lane(lane)
    _guard_suspended(checkpoint)
    row = store.base()
    row.update(
        {
            "lane_id": lane["id"],
            "detecting_officer_id": user_id,
            "resolving_officer_id": None,
            "referral_reason": values["referral_reason"],
            "passenger_category": values["passenger_category"],
            "requires_private_screening": values.get("requires_private_screening", False),
            "state": "RAISED",
            "secondary_slot_held": True,
            "resolution_note": None,
            "raised_at_utc": store.now(),
            "started_at_utc": None,
            "resolved_at_utc": None,
        }
    )
    store.add("screening_referrals", row)
    if checkpoint is not None:
        derive.refresh_checkpoint(checkpoint)
    return envelope.obj(serial.screening_referral(row), 201)


@bp.get("/screening-referrals/<screening_referral_id>")
def read_referral(screening_referral_id):
    req.actor(req.READ_ROLES)
    row = req.load("screening_referral", screening_referral_id)
    return envelope.obj(serial.screening_referral(row))


@bp.get("/screening-referrals")
def list_referrals():
    req.actor(req.READ_ROLES)
    limit, offset = req.pagination()
    rows = req.filter_rows(
        store.rows("screening_referrals"),
        {
            "lane_id": req.query_value("lane_id"),
            "detecting_officer_id": req.query_value("detecting_officer_id"),
            "resolving_officer_id": req.query_value("resolving_officer_id"),
            "state": req.query_enum("state", consts.REFERRAL_STATES),
            "referral_reason": req.query_enum("referral_reason", consts.REFERRAL_REASONS),
        },
    )
    rows.sort(key=lambda r: (r["raised_at_utc"], r["created_at"], r["_seq"]))
    page, total = req.paginate(rows, limit, offset)
    return envelope.listing(serial.many(serial.screening_referral, page), limit, offset, total)


BEGIN_SPEC = [
    {
        "name": "resolving_officer_id",
        "kind": "string",
        "required": True,
        "fk": "officer",
        "collection": "officers",
    }
]


@bp.post("/screening-referrals/<screening_referral_id>/begin")
def begin_referral(screening_referral_id):
    _role, user_id = req.actor(["SupervisoryOfficer"])
    values = req.parse_body(BEGIN_SPEC)
    parents = req.resolve_fks(values, BEGIN_SPEC)
    referral = req.load("screening_referral", screening_referral_id)
    resolver = parents["resolving_officer_id"]
    if resolver["id"] == referral["detecting_officer_id"]:
        fail(
            "ERR_SEGREGATION_OF_DUTIES",
            "the detecting officer may not work their own referral",
        )
    lane = store.get("lanes", referral["lane_id"])
    checkpoint = cascade.checkpoint_of_lane(lane) if lane is not None else None
    _guard_suspended(checkpoint)
    if referral["state"] != "RAISED":
        fail(
            "ERR_INVALID_STATE_TRANSITION",
            "a %s referral cannot be begun" % referral["state"],
        )
    if resolver["duty_status"] != "ON_DUTY":
        fail("ERR_INVALID_STATE_TRANSITION", "the nominated officer is not ON_DUTY")
    if lane is None or lane["lane_state"] != "OPEN":
        fail("ERR_INVALID_STATE_TRANSITION", "the referral's lane is not OPEN")
    reason = referral["referral_reason"]
    if reason == "ALARM":
        units = [
            u
            for u in derive.lane_units(lane["id"])
            if u["equipment_type"] == "ETD" and u["state"] in ("SERVICEABLE", "DEGRADED")
        ]
        if not units:
            fail(
                "ERR_LANE_EQUIPMENT_UNAVAILABLE",
                "the lane has no serviceable ETD unit",
            )
    needed = CERT_BY_REASON.get(reason)
    if needed is not None and needed not in resolver["certifications"]:
        fail("ERR_OFFICER_NOT_CERTIFIED", "the resolving officer lacks %s" % needed)
    if referral["requires_private_screening"]:
        _require_supervisor(user_id)
    if checkpoint is not None:
        in_use = len(
            [
                r
                for r in store.rows("screening_referrals")
                if r["id"] != referral["id"]
                and r["state"] in ("RAISED", "IN_PROGRESS")
                and (store.get("lanes", r["lane_id"]) or {}).get("checkpoint_id")
                == checkpoint["id"]
            ]
        )
        if in_use >= checkpoint["secondary_slot_capacity"]:
            fail("ERR_SECONDARY_CAPACITY_EXHAUSTED", "no secondary screening slot is free")
    referral["state"] = "IN_PROGRESS"
    referral["resolving_officer_id"] = resolver["id"]
    referral["started_at_utc"] = store.now()
    store.touch(referral)
    return envelope.obj(serial.screening_referral(referral))


RESOLVE_REFERRAL_SPEC = [
    {"name": "outcome", "kind": "enum", "required": True, "values": consts.REFERRAL_OUTCOMES},
    {"name": "resolution_note", "kind": "string", "max_len": 500},
]

SUPERVISOR_OUTCOMES = ("REFERRED_LEO", "DENIED_ENTRY", "WITHDRAWN")


@bp.post("/screening-referrals/<screening_referral_id>/resolve")
def resolve_referral(screening_referral_id):
    role, user_id = req.actor(["ScreeningOfficer", "SupervisoryOfficer"])
    values = req.parse_body(RESOLVE_REFERRAL_SPEC)
    outcome = values["outcome"]
    referral = req.load("screening_referral", screening_referral_id)
    if role == "ScreeningOfficer" and outcome != "CLEARED":
        fail(
            "ERR_FORBIDDEN_ACTION_FOR_ROLE",
            "a ScreeningOfficer may only send outcome CLEARED",
        )
    if user_id == referral["detecting_officer_id"]:
        fail(
            "ERR_SEGREGATION_OF_DUTIES",
            "the detecting officer may not resolve their own referral",
        )
    required_state = "RAISED" if outcome == "WITHDRAWN" else "IN_PROGRESS"
    if referral["state"] != required_state:
        fail(
            "ERR_INVALID_STATE_TRANSITION",
            "a %s referral cannot be resolved with %s" % (referral["state"], outcome),
        )
    if outcome == "CLEARED" and role == "ScreeningOfficer":
        needed = CERT_BY_REASON.get(referral["referral_reason"])
        officer = store.get("officers", user_id)
        certs = officer["certifications"] if officer is not None else []
        if needed is not None and needed not in certs:
            fail("ERR_OFFICER_NOT_CERTIFIED", "the acting officer lacks %s" % needed)
    if outcome in ("REFERRED_LEO", "DENIED_ENTRY"):
        _require_supervisor(user_id)
        if "resolution_note" not in values:
            bad_request("resolution_note is required for a %s outcome" % outcome)
    elif outcome == "WITHDRAWN":
        _require_supervisor(user_id)
    lane = store.get("lanes", referral["lane_id"])
    checkpoint = cascade.checkpoint_of_lane(lane) if lane is not None else None
    referral["state"] = outcome
    referral["resolved_at_utc"] = store.now()
    referral["secondary_slot_held"] = False
    if "resolution_note" in values:
        referral["resolution_note"] = values["resolution_note"]
    store.touch(referral)
    if checkpoint is not None:
        if outcome == "CLEARED":
            checkpoint["cleared_referral_count"] += 1
        elif outcome == "REFERRED_LEO":
            checkpoint["leo_referral_count"] += 1
        elif outcome == "DENIED_ENTRY":
            checkpoint["denied_entry_count"] += 1
            checkpoint["diverted_pax_total"] += 1
        before = derive.posture(checkpoint)
        if (
            outcome == "REFERRED_LEO"
            and referral["referral_reason"] == "ALARM"
            and lane is not None
            and lane["lane_state"] == "OPEN"
        ):
            cascade.pause_lane(lane, "SECURITY_INCIDENT")
        cascade.bump_checkpoint(checkpoint)
        cascade.settle_posture(checkpoint, before)
    return envelope.obj(serial.screening_referral(referral))


# ---------------------------------------------------------------------------
# SurgeDetail
# ---------------------------------------------------------------------------
from util import dec, half_up_int  # noqa: E402

DETAIL_SPEC = [
    {
        "name": "staffing_plan_id",
        "kind": "string",
        "required": True,
        "fk": "staffing_plan",
        "collection": "staffing_plans",
    },
    {
        "name": "officer_id",
        "kind": "string",
        "required": True,
        "fk": "officer",
        "collection": "officers",
    },
    {"name": "event_code", "kind": "enum", "required": True, "values": consts.EVENT_CODES},
    {"name": "window_start_utc", "kind": "datetime", "required": True},
    {"name": "detail_minutes", "kind": "integer", "required": True, "min": 1, "max": 720},
    {"name": "expected_officer_version", "kind": "integer", "required": True, "min": 0},
]


@bp.post("/surge-details")
def create_detail():
    _role, user_id = req.actor(["StaffingPlanner"])
    values = req.parse_body(DETAIL_SPEC)
    parents = req.resolve_fks(values, DETAIL_SPEC)
    plan = parents["staffing_plan_id"]
    officer = parents["officer_id"]
    if values["expected_officer_version"] != officer["version"]:
        fail(
            "ERR_STALE_OFFICER_VERSION",
            "expected_officer_version %s does not match %s"
            % (values["expected_officer_version"], officer["version"]),
        )
    if officer["duty_status"] == "SEPARATED":
        fail("ERR_INVALID_STATE_TRANSITION", "a SEPARATED officer cannot be detailed")
    day_start, day_end = day_bounds(plan["operational_date"])
    window_end = values["window_start_utc"] + timedelta(minutes=values["detail_minutes"])
    if values["window_start_utc"] < day_start or window_end > day_end:
        fail(
            "ERR_DETAIL_WINDOW_OUTSIDE_PLAN",
            "the detail window is not inside the plan's operational date",
        )
    row = store.base()
    row.update(
        {
            "staffing_plan_id": plan["id"],
            "officer_id": officer["id"],
            "event_code": values["event_code"],
            "window_start_utc": values["window_start_utc"],
            "detail_minutes": values["detail_minutes"],
            "state": "REQUESTED",
            "requested_by_user_id": user_id,
            "decided_by_user_id": None,
            "denial_reason_code": None,
            "detail_cost_cents": None,
            "decided_at_utc": None,
            "cancelled_at_utc": None,
        }
    )
    store.add("surge_details", row)
    cascade.bump_officer(officer)
    derive.refresh_officer(officer)
    return envelope.obj(serial.surge_detail(row), 201)


@bp.get("/surge-details/<surge_detail_id>")
def read_detail(surge_detail_id):
    req.actor(req.READ_ROLES)
    row = req.load("surge_detail", surge_detail_id)
    return envelope.obj(serial.surge_detail(row))


@bp.get("/surge-details")
def list_details():
    req.actor(req.READ_ROLES)
    limit, offset = req.pagination()
    rows = req.filter_rows(
        store.rows("surge_details"),
        {
            "staffing_plan_id": req.query_value("staffing_plan_id"),
            "officer_id": req.query_value("officer_id"),
            "state": req.query_enum("state", consts.DETAIL_STATES),
            "event_code": req.query_enum("event_code", consts.EVENT_CODES),
        },
    )
    rows.sort(key=lambda d: (d["window_start_utc"], d["created_at"], d["_seq"]))
    page, total = req.paginate(rows, limit, offset)
    return envelope.listing(serial.many(serial.surge_detail, page), limit, offset, total)


DETAIL_DECISION_SPEC = [
    {"name": "decision", "kind": "enum", "required": True, "values": ("APPROVE", "DENY")},
    {"name": "denial_reason_code", "kind": "enum", "values": consts.DENIAL_REASON_CODES},
]


@bp.post("/surge-details/<surge_detail_id>/decision")
def decide_detail(surge_detail_id):
    _role, user_id = req.actor(["DutyManager"])
    values = req.parse_body(DETAIL_DECISION_SPEC)
    decision = values["decision"]
    if decision == "DENY" and "denial_reason_code" not in values:
        bad_request("denial_reason_code is required when denying")
    if decision == "APPROVE" and "denial_reason_code" in values:
        bad_request("denial_reason_code is forbidden when approving")
    detail = req.load("surge_detail", surge_detail_id)
    if user_id == detail["requested_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES", "the requester may not decide their own detail")
    if detail["state"] != "REQUESTED":
        fail("ERR_INVALID_STATE_TRANSITION", "a %s detail cannot be decided" % detail["state"])
    plan = store.get("staffing_plans", detail["staffing_plan_id"])
    officer = store.get("officers", detail["officer_id"])
    if decision == "DENY":
        detail["state"] = "DENIED"
        detail["denial_reason_code"] = values["denial_reason_code"]
        detail["decided_by_user_id"] = user_id
        detail["decided_at_utc"] = store.now()
        store.touch(detail)
        if officer is not None:
            cascade.bump_officer(officer)
        return envelope.obj(serial.surge_detail(detail))
    if plan is None or plan["state"] not in ("SUBMITTED", "APPROVED", "ACTIVATED"):
        fail(
            "ERR_INVALID_STATE_TRANSITION",
            "the owning plan does not accept detail approvals",
        )
    if officer is not None and officer["duty_status"] == "SEPARATED":
        fail("ERR_INVALID_STATE_TRANSITION", "a SEPARATED officer cannot be detailed")
    if officer is not None:
        ledger = calc.officer_duty_ledger(
            officer, "FORWARD_LOOKING_PLANNED", extra_detail_minutes=detail["detail_minutes"]
        )
        if ledger["overtime_minutes"] > officer["weekly_overtime_minutes_cap"]:
            fail(
                "ERR_OVERTIME_CAP_EXCEEDED",
                "the officer's overtime %d exceeds the cap %d"
                % (ledger["overtime_minutes"], officer["weekly_overtime_minutes_cap"]),
            )
    checkpoint = store.get("checkpoints", plan["checkpoint_id"])
    projected = calc.staffing_plan_cost(plan, extra_detail_minutes=detail["detail_minutes"])
    if checkpoint is not None and projected["total_cost_cents"] > checkpoint["plan_cost_cap_cents"]:
        fail(
            "ERR_PLAN_COST_CAP_EXCEEDED",
            "total cost %d exceeds the cap %d"
            % (projected["total_cost_cents"], checkpoint["plan_cost_cap_cents"]),
        )
    detail["state"] = "APPROVED"
    detail["decided_by_user_id"] = user_id
    detail["decided_at_utc"] = store.now()
    detail["detail_cost_cents"] = half_up_int(
        dec(detail["detail_minutes"]) * dec(consts.DETAIL_RATE_CENTS_PER_MINUTE)
    )
    store.touch(detail)
    if officer is not None:
        derive.refresh_officer(officer)
        cascade.bump_officer(officer)
    calc.apply_plan_cost(plan)
    return envelope.obj(serial.surge_detail(detail))


@bp.post("/surge-details/<surge_detail_id>/cancel")
def cancel_detail(surge_detail_id):
    req.actor(["DutyManager"])
    detail = req.load("surge_detail", surge_detail_id)
    if detail["state"] != "APPROVED":
        fail("ERR_INVALID_STATE_TRANSITION", "a %s detail cannot be cancelled" % detail["state"])
    detail["state"] = "CANCELLED"
    detail["cancelled_at_utc"] = store.now()
    detail["detail_cost_cents"] = None
    store.touch(detail)
    officer = store.get("officers", detail["officer_id"])
    if officer is not None:
        derive.refresh_officer(officer)
        cascade.bump_officer(officer)
    plan = store.get("staffing_plans", detail["staffing_plan_id"])
    if plan is not None:
        calc.apply_plan_cost(plan)
    return envelope.obj(serial.surge_detail(detail))
