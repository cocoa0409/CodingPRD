"""The enforcement ladder: proposal, issuance, effectuation and appeals (PRD §3.8)."""

from flask import Blueprint, request

import calc
import clock
import constants as K
import derive
import envelope
import helpers
import serialize
import store
import validate
from auth import authenticate, require_provider_owner
from errors import ApiError
from validate import F

bp = Blueprint("enforcement", __name__)

ACTION_READERS = ("AgencyAdmin", "Applicant", "LicensingSupervisor", "PublicPortalReader")

EFFECTUATION_LICENSE_STATES = {
    "WARNING": ("PROVISIONAL", "FULL", "PROBATION"),
    "PROBATION": ("PROVISIONAL", "FULL"),
    "SUSPENSION": ("FULL", "PROBATION"),
    "REVOCATION": ("PROBATION", "SUSPENDED"),
}


def _refresh_postings(provider):
    for posting in store.by_provider(store.postings, provider["id"]):
        if posting["posting_status"] not in ("POSTED", "CORRECTED"):
            continue
        inspection = store.inspections[posting["inspection_id"]]
        banner, score = calc.display_score(
            inspection["final_compliance_score"], provider["current_ladder_step"]
        )
        posting["enforcement_banner"] = banner
        posting["display_score"] = score
        store.touch(posting)


@bp.post("/licensing/enforcement-actions")
def propose_action():
    authenticate(("LicensingSupervisor",))
    vals = validate.body(
        [
            F("provider_id", "string", required=True),
            F("requested_action_type", "enum", required=True, values=K.ACTION_TYPES),
            F("source_inspection_id", "string"),
            F("rationale", "string", min_len=1, max_len=2000, not_blank=True),
        ]
    )
    provider = helpers.need("provider", vals["provider_id"])
    source = None
    if vals.get("source_inspection_id") is not None:
        source = helpers.need("inspection", vals["source_inspection_id"])

    points = provider["open_violation_points"]
    if points < K.WARNING_THRESHOLD:
        raise ApiError(
            "ERR_NO_ENFORCEMENT_BASIS",
            "The provider carries too few open violation points for any sanction.",
        )
    recommended = calc.recommended_action_type(points)
    requested = vals["requested_action_type"]
    if K.LADDER_STEP[requested] > K.LADDER_STEP[recommended]:
        raise ApiError(
            "ERR_LADDER_STEP_SKIP",
            "The requested rung exceeds the rung the open points recommend.",
        )
    record = {
        "provider_id": provider["id"],
        "source_inspection_id": source["id"] if source else None,
        "requested_action_type": requested,
        "action_type": requested,
        "ladder_step": K.LADDER_STEP[requested],
        "status": "PROPOSED",
        "basis_points": points,
        "fine_amount_cents": calc.fine_amount_cents(requested, points),
        "proposed_at": clock.now(),
        "issued_at": None,
        "effective_at": None,
        "appeal_deadline_at": None,
        "appealed_at": None,
        "appeal_note": None,
        "resolved_at": None,
        "appeal_decision": None,
        "issued_by_user_id": None,
        "capacity_held_slots": 0,
        "rationale": vals.get("rationale"),
    }
    store.create(store.actions, record)
    return envelope.created(serialize.action(record))


@bp.get("/licensing/enforcement-actions")
def list_actions():
    authenticate(ACTION_READERS)
    limit, offset = envelope.pagination(request.args)
    status = validate.query_enum("status", K.ENFORCEMENT_STATUSES)
    action_type = validate.query_enum("action_type", K.ACTION_TYPES)
    provider_id = validate.query_str("provider_id")
    source_inspection_id = validate.query_str("source_inspection_id")
    rows = store.ordered(store.actions)
    if provider_id is not None:
        rows = [r for r in rows if r["provider_id"] == provider_id]
    if source_inspection_id is not None:
        rows = [r for r in rows if r.get("source_inspection_id") == source_inspection_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if action_type is not None:
        rows = [r for r in rows if r["action_type"] == action_type]
    return helpers.listing(rows, serialize.action, limit, offset)


@bp.get("/licensing/enforcement-actions/<action_id>")
def read_action(action_id):
    authenticate(ACTION_READERS)
    record = helpers.need("action", action_id)
    return envelope.ok(serialize.action(record))


@bp.post("/licensing/enforcement-actions/<action_id>/issue")
def issue_action(action_id):
    user_id, _role = authenticate(("LicensingSupervisor",))
    validate.body([])
    action = helpers.need("action", action_id)
    if derive.cap_reviewer_conflict(user_id, action.get("source_inspection_id")):
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "The reviewer of a plan for this inspection may not issue its enforcement.",
        )
    if action["status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_ENFORCEMENT_STATE", "The action is not PROPOSED.")
    issued_at = clock.now_dt()
    action["status"] = "ISSUED"
    action["issued_at"] = clock.fmt(issued_at)
    action["issued_by_user_id"] = user_id
    action["appeal_deadline_at"] = clock.fmt(clock.add_days(issued_at, K.APPEAL_WINDOW_DAYS))
    store.touch(action)
    return envelope.ok(serialize.action(action))


@bp.post("/licensing/enforcement-actions/<action_id>/effectuate")
def effectuate_action(action_id):
    authenticate(("AgencyAdmin",))
    validate.body([])
    action = helpers.need("action", action_id)
    if action["status"] != "ISSUED":
        raise ApiError("ERR_INVALID_ENFORCEMENT_STATE", "The action is not ISSUED.")
    provider = store.providers[action["provider_id"]]
    action_type = action["action_type"]
    if provider["license_status"] not in EFFECTUATION_LICENSE_STATES[action_type]:
        raise ApiError(
            "ERR_INVALID_LICENSE_STATE",
            "A %s may not be effectuated against a licence in %s."
            % (action_type, provider["license_status"]),
        )

    action["status"] = "EFFECTIVE"
    action["effective_at"] = clock.now()
    step = K.LADDER_STEP[action_type]
    if action_type == "WARNING":
        provider["current_ladder_step"] = max(provider["current_ladder_step"], step)
    elif action_type == "PROBATION":
        provider["license_status"] = "PROBATION"
        provider["current_ladder_step"] = max(provider["current_ladder_step"], step)
        provider["probation_cycle_count"] += 1
    elif action_type == "SUSPENSION":
        held = provider["licensed_capacity"]
        provider["license_status"] = "SUSPENDED"
        provider["current_ladder_step"] = max(provider["current_ladder_step"], step)
        action["capacity_held_slots"] = held
        provider["suspended_capacity"] += held
        provider["licensed_capacity"] = 0
    else:
        held = provider["licensed_capacity"] + provider["suspended_capacity"]
        provider["license_status"] = "REVOKED"
        provider["current_ladder_step"] = 4
        action["capacity_held_slots"] = held
        provider["licensed_capacity"] = 0
        provider["suspended_capacity"] = 0
        for amendment in store.by_provider(store.amendments, provider["id"]):
            if amendment["status"] in ("SUBMITTED", "PRE_INSPECTION_REQUIRED"):
                amendment["status"] = "WITHDRAWN"
                amendment["decided_at"] = clock.now()
                store.touch(amendment)
        for other in store.by_provider(store.actions, provider["id"]):
            if other["id"] != action["id"] and other["status"] == "PROPOSED":
                other["status"] = "WITHDRAWN"
                other["resolved_at"] = clock.now()
                store.touch(other)
        for inspection in store.provider_inspections(provider["id"]):
            if inspection["status"] in K.ACTIVE_INSPECTION_STATUSES:
                derive.void_inspection(inspection, "Licence revoked.")
    store.touch(action)
    if provider["suspended_capacity"] < 0:
        raise ApiError("ERR_CAPACITY_SLOT_IMBALANCE", "Suspended capacity may not go negative.")
    _refresh_postings(provider)
    derive.recompute_provider(provider)
    store.touch(provider)
    return envelope.ok(serialize.action(action))


@bp.post("/licensing/enforcement-actions/<action_id>/appeal")
def appeal_action(action_id):
    user_id, role = authenticate(("Applicant",))
    vals = validate.body(
        [F("appeal_note", "string", required=True, min_len=1, max_len=2000, not_blank=True)]
    )
    action = helpers.need("action", action_id)
    require_provider_owner(role, user_id, action["provider_id"])
    if action["status"] != "EFFECTIVE":
        raise ApiError("ERR_INVALID_ENFORCEMENT_STATE", "The action is not EFFECTIVE.")
    if clock.now_dt() > clock.at(action["appeal_deadline_at"]):
        raise ApiError("ERR_APPEAL_DEADLINE_PASSED", "The appeal window has closed.")
    action["status"] = "APPEALED"
    action["appealed_at"] = clock.now()
    action["appeal_note"] = vals["appeal_note"]
    store.touch(action)
    return envelope.ok(serialize.action(action))


@bp.post("/licensing/enforcement-actions/<action_id>/appeal-decision")
def decide_appeal(action_id):
    user_id, _role = authenticate(("AgencyAdmin",))
    vals = validate.body(
        [F("appeal_decision", "enum", required=True, values=K.APPEAL_DECISIONS)]
    )
    action = helpers.need("action", action_id)
    if user_id == action.get("issued_by_user_id"):
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES", "Nobody may decide the appeal against their own issuance."
        )
    if action["status"] != "APPEALED":
        raise ApiError("ERR_INVALID_ENFORCEMENT_STATE", "The action is not APPEALED.")

    provider = store.providers[action["provider_id"]]
    decision = vals["appeal_decision"]
    action["appeal_decision"] = decision
    action["resolved_at"] = clock.now()
    if decision == "UPHELD":
        action["status"] = "UPHELD"
        store.touch(action)
        return envelope.ok(serialize.action(action))

    action["status"] = "VACATED"
    action_type = action["action_type"]
    held = action["capacity_held_slots"]
    if action_type == "SUSPENSION":
        if held > provider["suspended_capacity"]:
            raise ApiError(
                "ERR_CAPACITY_SLOT_IMBALANCE", "Suspended capacity may not go negative."
            )
        provider["licensed_capacity"] += held
        provider["suspended_capacity"] -= held
        action["capacity_held_slots"] = 0
        provider["license_status"] = "PROBATION"
        provider["current_ladder_step"] = 2
    elif action_type == "REVOCATION":
        provider["licensed_capacity"] += held
        action["capacity_held_slots"] = 0
        provider["license_status"] = "PROBATION"
        provider["current_ladder_step"] = 2
    elif action_type == "PROBATION":
        provider["license_status"] = "FULL"
        provider["current_ladder_step"] = 1
    else:
        provider["current_ladder_step"] = 0
    store.touch(action)
    derive.recompute_provider(provider)
    store.touch(provider)
    return envelope.ok(serialize.action(action))
