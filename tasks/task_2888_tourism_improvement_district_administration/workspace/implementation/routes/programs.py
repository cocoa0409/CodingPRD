"""Marketing programs, room-night claims and performance measurement (PRD 3.8)."""
from decimal import Decimal

from flask import Blueprint

import config
import envelope
import serialize
import store
import validate
from auth import authenticate, require_owner
from errors import fail
from routes.common import ADMIN, AUDITOR, BOARD, DMO, OPERATOR, VIEWER, narrow
from services import core, plans as planservice
from store import put, set_if_changed, touch

bp = Blueprint("programs", __name__)


def _interval(b, start_field, end_field):
    start = validate.instant(b, start_field)
    end = validate.instant(b, end_field)
    if end.dt <= start.dt:
        fail("ERR_INVALID_REQUEST", "%s must fall strictly after %s." % (end_field, start_field))
    return start, end


# ---------------------------------------------------------------------------
# reads
# ---------------------------------------------------------------------------
@bp.get("/marketing-programs/<program_id>")
def read_program(program_id):
    authenticate([ADMIN, BOARD, DMO, AUDITOR, VIEWER], public=True)
    return envelope.ok(serialize.program(validate.program(program_id)))


@bp.get("/marketing-programs/<program_id>/room-night-claims")
def list_program_claims(program_id):
    authenticate([ADMIN, DMO, AUDITOR])
    program = validate.program(program_id)
    status = envelope.enum_filter("status", config.CLAIM_STATUSES)
    business_id = envelope.str_filter("lodging_business_id")
    records = narrow(core.claims_of_program(program["id"]),
                     status=status, lodging_business_id=business_id)
    return envelope.paginate(records, serialize.claim)


@bp.get("/room-night-claims/<claim_id>")
def read_claim(claim_id):
    authenticate([ADMIN, DMO, AUDITOR, OPERATOR])
    return envelope.ok(serialize.claim(validate.claim(claim_id)))


# ---------------------------------------------------------------------------
# writes
# ---------------------------------------------------------------------------
@bp.post("/marketing-programs")
def create_program():
    authenticate([ADMIN, DMO])
    b = validate.body()
    plan_id = validate.id_ref(b, "annual_work_plan_id")
    name = validate.text(b, "name", max_len=120)
    if not name.strip():
        fail("ERR_INVALID_REQUEST", "name may not be blank.")
    channel = validate.enum(b, "channel", config.PROGRAM_CHANNELS)
    committed = validate.cents(b, "committed_cents", minimum=1)
    window_start, window_end = _interval(b, "booking_window_start", "booking_window_end")
    matched = validate.cents(b, "lodging_tax_matched_cents", required=False, default=0)

    plan = validate.plan(plan_id)
    district = core.district_of_plan(plan)
    if district["status"] in config.DISTRICT_TERMINAL:
        fail("ERR_DISTRICT_NOT_ACTIVE",
             "A %s district accepts no program activity." % district["status"])
    if plan["status"] != "APPROVED":
        fail("ERR_WORK_PLAN_NOT_APPROVED", "The funding work plan must be APPROVED.")

    live = sum(p["committed_cents"] for p in core.programs_of_plan(plan["id"])
               if p["status"] != "CANCELLED")
    if live + committed > plan["sales_and_marketing_cents"]:
        fail("ERR_PROGRAM_BUDGET_EXCEEDED",
             "Committed program spend may not exceed the plan's sales and marketing line of %d cents."
             % plan["sales_and_marketing_cents"])
    proposed_match = district["lodging_tax_match_committed_cents"] + matched
    if proposed_match > planservice.match_ceiling(plan):
        fail("ERR_LODGING_TAX_MATCH_CAP_EXCEEDED",
             "The lodging tax match may not exceed %d cents." % planservice.match_ceiling(plan))
    if proposed_match > district["lodging_tax_match_pool_cents"]:
        fail("ERR_LODGING_TAX_MATCH_EXHAUSTED",
             "The district's lodging tax match pool holds only %d cents."
             % district["lodging_tax_match_pool_cents"])

    rec = store.new_record("program")
    rec.update({
        "annual_work_plan_id": plan["id"],
        "name": name,
        "channel": channel,
        "committed_cents": committed,
        "lodging_tax_matched_cents": matched,
        "status": "PLANNED",
        "spend_frozen": False,
        "verified_room_nights": 0,
        "gross_cost_per_room_night_cents": None,
        "efficiency_tier": None,
        "dmo_cost_share_cents": 0,
        "net_district_cost_cents": 0,
        "net_cost_per_room_night_cents": None,
        "performance_index": Decimal("0.0000"),
        "performance_flag": "NOT_MEASURED",
        "launched_at": None,
        "closed_at": None,
    })
    validate.assign(rec, "booking_window_start", window_start)
    validate.assign(rec, "booking_window_end", window_end)
    put("programs", rec)

    planservice.recompute_committed_program_cents(plan)
    touch(plan)
    core.recompute_lodging_tax_committed(district)
    return envelope.created(serialize.program(rec))


@bp.post("/marketing-programs/<program_id>/launch")
def launch_program(program_id):
    authenticate([ADMIN, DMO])
    b = validate.body()
    validate.text(b, "launch_note", required=False)

    program = validate.program(program_id)
    plan = core.plan_of_program(program)
    district = core.district_of_plan(plan)

    if program["status"] != "PLANNED":
        fail("ERR_INVALID_STATE_TRANSITION", "Only a PLANNED program may be launched.")
    if plan["status"] != "APPROVED":
        fail("ERR_WORK_PLAN_NOT_APPROVED", "The funding work plan must be APPROVED.")
    if district["status"] in config.DISTRICT_TERMINAL:
        fail("ERR_DISTRICT_NOT_ACTIVE",
             "A %s district accepts no program activity." % district["status"])
    if district["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE_TRANSITION", "The owning district must be ACTIVE.")
    if district["dmo_agreement_status"] != "EXECUTED":
        fail("ERR_DMO_AGREEMENT_NOT_EXECUTED",
             "The district's destination marketing organization agreement must be EXECUTED.")
    now = store.clock()
    if now < program["booking_window_start"] or now >= program["booking_window_end"]:
        fail("ERR_INVALID_STATE_TRANSITION",
             "The logical clock lies outside the program's booking window.")

    live = sum(p["committed_cents"] for p in core.programs_of_plan(plan["id"])
               if p["status"] != "CANCELLED")
    if live > plan["sales_and_marketing_cents"]:
        fail("ERR_PROGRAM_BUDGET_EXCEEDED",
             "Committed program spend now exceeds the plan's sales and marketing line.")

    program["status"] = "RUNNING"
    program["launched_at"] = now
    program["_raw"].pop("launched_at", None)
    touch(program)
    return envelope.ok(serialize.program(program))


@bp.post("/marketing-programs/<program_id>/closure")
def close_program(program_id):
    authenticate([ADMIN, DMO])
    b = validate.body()
    validate.text(b, "closure_note", required=False)

    program = validate.program(program_id)
    if program["status"] != "RUNNING":
        fail("ERR_INVALID_STATE_TRANSITION", "Only a RUNNING program may be closed.")
    if program["spend_frozen"]:
        fail("ERR_PROGRAM_SPEND_FROZEN",
             "Performance may not be published while spend is frozen.")
    if any(c["status"] == "SUBMITTED" for c in core.claims_of_program(program["id"])):
        fail("ERR_CLAIMS_PENDING_VERIFICATION",
             "Every room-night claim of the program must be verified or rejected first.")

    planservice.measure_performance(program)
    program["status"] = "CLOSED"
    program["closed_at"] = store.clock()
    program["_raw"].pop("closed_at", None)
    touch(program)
    return envelope.ok(serialize.program(program))


# ---------------------------------------------------------------------------
# room-night claims
# ---------------------------------------------------------------------------
@bp.post("/marketing-programs/<program_id>/room-night-claims")
def create_claim(program_id):
    actor = authenticate([OPERATOR, DMO])
    b = validate.body()
    business_id = validate.id_ref(b, "lodging_business_id")
    stay_start, stay_end = _interval(b, "stay_start", "stay_end")
    room_nights = validate.integer(b, "room_nights", minimum=1)
    method = validate.enum(b, "attribution_method", config.ATTRIBUTION_METHODS,
                           required=False, default="DIRECT_PICKUP")

    program = validate.program(program_id)
    business = validate.business(business_id)
    require_owner(actor, business["id"])

    if (program["status"] != "RUNNING"
            or stay_start.dt < program["booking_window_start"]
            or stay_end.dt > program["booking_window_end"]):
        fail("ERR_CLAIM_OUTSIDE_BOOKING_WINDOW",
             "The stay must fall entirely inside the booking window of a RUNNING program.")

    for other in core.claims_of_program(program["id"]):
        if other["lodging_business_id"] != business["id"]:
            continue
        if other["status"] not in ("SUBMITTED", "VERIFIED"):
            continue
        if stay_start.dt < other["stay_end"] and other["stay_start"] < stay_end.dt:
            fail("ERR_CLAIM_STAY_OVERLAP",
                 "The stay overlaps another live claim of this property on this program.")

    nights = store.whole_days_between(stay_start.dt, stay_end.dt)
    if room_nights > business["room_count"] * nights:
        fail("ERR_CLAIM_EXCEEDS_CAPACITY",
             "room_nights may not exceed %d." % (business["room_count"] * nights))

    rec = store.new_record("claim")
    rec.update({
        "marketing_program_id": program["id"],
        "lodging_business_id": business["id"],
        "room_nights": room_nights,
        "attribution_method": method,
        "status": "SUBMITTED",
        "verified_room_nights": None,
        "rejection_reason": "NONE",
        "verified_by_user_id": None,
    })
    validate.assign(rec, "stay_start", stay_start)
    validate.assign(rec, "stay_end", stay_end)
    put("claims", rec)
    return envelope.created(serialize.claim(rec))


@bp.post("/room-night-claims/<claim_id>/verification")
def verify_claim(claim_id):
    actor = authenticate([DMO, ADMIN])
    b = validate.body()
    decision = validate.enum(b, "decision", config.VERIFY_DECISIONS)
    verified = validate.integer(b, "verified_room_nights", required=False, minimum=1)
    reason = validate.enum(b, "rejection_reason", config.REJECTION_REASONS, required=False)

    claim = validate.claim(claim_id)
    if claim["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE_TRANSITION", "Only a SUBMITTED claim may be decided.")

    program = store.state.programs[claim["marketing_program_id"]]
    if decision == "ALLOW":
        if verified is None:
            verified = claim["room_nights"]
        if verified > claim["room_nights"]:
            fail("ERR_CLAIM_EXCEEDS_CAPACITY",
                 "verified_room_nights may not exceed the claim's room_nights.")
        claim["status"] = "VERIFIED"
        claim["verified_room_nights"] = verified
    else:
        if reason is None or reason == "NONE":
            fail("ERR_INVALID_REQUEST",
                 "a rejection_reason other than NONE is required to reject a claim.")
        claim["status"] = "REJECTED"
        claim["verified_room_nights"] = None
        claim["rejection_reason"] = reason
    claim["verified_by_user_id"] = actor.user_id
    touch(claim)

    set_if_changed(program, {
        "verified_room_nights": sum(
            c["verified_room_nights"] or 0 for c in core.claims_of_program(program["id"])
            if c["status"] == "VERIFIED")})
    return envelope.ok(serialize.claim(claim))
