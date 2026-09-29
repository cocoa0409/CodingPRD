"""Assessment disputes (PRD 3.6): proceedings and the three-hop resolution cascade."""
from flask import Blueprint

import config
import envelope
import serialize
import store
import validate
from auth import authenticate, require_action_role, require_owner
from errors import fail
from routes.common import ADMIN, AUDITOR, HEARING, OPERATOR
from services import core, plans as planservice
from store import put, touch

bp = Blueprint("disputes", __name__)


@bp.get("/assessment-disputes/<dispute_id>")
def read_dispute(dispute_id):
    authenticate([ADMIN, HEARING, AUDITOR, OPERATOR])
    return envelope.ok(serialize.dispute(validate.dispute(dispute_id)))


@bp.post("/assessment-disputes")
def create_dispute():
    actor = authenticate([OPERATOR, ADMIN])
    b = validate.body()
    statement_id = validate.id_ref(b, "assessment_statement_id")
    dispute_type = validate.enum(b, "dispute_type", config.DISPUTE_TYPES)
    claimed = validate.cents(b, "claimed_adjustment_cents", minimum=1)
    note = validate.text(b, "dispute_note", required=False)

    statement = validate.statement(statement_id)
    require_owner(actor, statement["lodging_business_id"])

    for existing in core.disputes_of_statement(statement["id"]):
        if existing["dispute_type"] == dispute_type and existing["status"] in config.DISPUTE_LIVE:
            fail("ERR_DISPUTE_ALREADY_OPEN",
                 "A live %s dispute already exists for this statement." % dispute_type)

    rec = store.new_record("dispute")
    rec.update({
        "assessment_statement_id": statement["id"],
        "lodging_business_id": statement["lodging_business_id"],
        "dispute_note": note,
        "dispute_type": dispute_type,
        "claimed_adjustment_cents": claimed,
        "granted_adjustment_cents": 0,
        "status": "SUBMITTED",
        "appeal_count": 0,
        "resolved_by_user_id": None,
        "resolution_note": None,
        "filed_on": store.clock(),
    })
    put("disputes", rec)
    return envelope.created(serialize.dispute(rec))


@bp.post("/assessment-disputes/<dispute_id>/proceedings")
def advance_dispute(dispute_id):
    actor = authenticate([HEARING, OPERATOR])
    b = validate.body()
    action = validate.enum(b, "action", config.PROCEEDING_ACTIONS)
    validate.text(b, "note", required=False)

    if action in config.HEARING_OFFICER_ACTIONS:
        require_action_role(actor.role, [HEARING],
                            "%s is reserved to the HearingOfficer." % action)
    else:
        require_action_role(actor.role, [OPERATOR],
                            "%s is reserved to the owning LodgingOperator." % action)

    dispute = validate.dispute(dispute_id)
    if action in config.OPERATOR_ACTIONS:
        require_owner(actor, dispute["lodging_business_id"])

    if action == "OPEN_REVIEW":
        if dispute["status"] != "SUBMITTED":
            fail("ERR_INVALID_STATE_TRANSITION",
                 "Only a SUBMITTED dispute may have review opened.")
        dispute["status"] = "UNDER_REVIEW"
    elif action == "REQUEST_INFO":
        if dispute["status"] != "UNDER_REVIEW":
            fail("ERR_INVALID_STATE_TRANSITION",
                 "Information may be requested only while UNDER_REVIEW.")
        dispute["status"] = "INFO_REQUESTED"
    elif action == "SUBMIT_RESPONSE":
        if dispute["status"] != "INFO_REQUESTED":
            fail("ERR_INVALID_STATE_TRANSITION",
                 "A response may be submitted only while INFO_REQUESTED.")
        dispute["status"] = "UNDER_REVIEW"
    elif action == "APPEAL":
        if dispute["status"] != "RESOLVED_UPHELD":
            fail("ERR_INVALID_STATE_TRANSITION",
                 "Only a RESOLVED_UPHELD dispute may be appealed.")
        if dispute["appeal_count"] >= 1:
            fail("ERR_APPEAL_LIMIT_EXCEEDED", "At most one appeal may be taken.")
        dispute["status"] = "UNDER_REVIEW"
        dispute["appeal_count"] = dispute["appeal_count"] + 1
        dispute["resolved_by_user_id"] = None
    else:
        if dispute["status"] != "SUBMITTED":
            fail("ERR_INVALID_STATE_TRANSITION",
                 "A dispute may be withdrawn only before review is opened.")
        dispute["status"] = "WITHDRAWN"

    touch(dispute)
    return envelope.ok(serialize.dispute(dispute))


@bp.post("/assessment-disputes/<dispute_id>/resolution")
def resolve_dispute(dispute_id):
    actor = authenticate([HEARING])
    b = validate.body()
    outcome = validate.enum(b, "outcome", config.RESOLUTION_OUTCOMES)
    granted = validate.cents(b, "granted_adjustment_cents", required=False, minimum=1)
    exempt_granted = validate.enum(b, "exempt_status_granted", config.EXEMPT_STATUSES,
                                   required=False)
    resolution_note = validate.text(b, "resolution_note", required=False)

    dispute = validate.dispute(dispute_id)
    if dispute["status"] != "UNDER_REVIEW":
        fail("ERR_INVALID_STATE_TRANSITION",
             "Only a dispute UNDER_REVIEW may be resolved.")

    statement = core.statement_of_dispute(dispute)

    # Nothing is recorded on the dispute until an outcome is actually reached: a
    # refused resolution leaves resolved_by_user_id and resolution_note as they were
    # (PRD 3.6 records them on an outcome, and PRD 2.8 rejects without side effect).
    if outcome == "UPHELD":
        dispute["resolved_by_user_id"] = actor.user_id
        dispute["resolution_note"] = resolution_note
        dispute["status"] = "RESOLVED_UPHELD"
        touch(dispute)
        return envelope.ok(serialize.dispute(dispute))

    if granted is None:
        fail("ERR_INVALID_REQUEST",
             "granted_adjustment_cents is required for an ADJUSTED outcome.")
    if granted > dispute["claimed_adjustment_cents"]:
        fail("ERR_INVALID_REQUEST",
             "granted_adjustment_cents may not exceed claimed_adjustment_cents.")
    if dispute["dispute_type"] == "EXEMPT_PROPERTY" and (
            exempt_granted is None or exempt_granted == "NONE"):
        fail("ERR_INVALID_REQUEST",
             "exempt_status_granted other than NONE is required for an EXEMPT_PROPERTY dispute.")
    if granted > statement["effective_assessment_cents"]:
        fail("ERR_ADJUSTMENT_EXCEEDS_ASSESSMENT",
             "granted_adjustment_cents may not exceed the statement's effective assessment.")

    dispute["resolved_by_user_id"] = actor.user_id
    dispute["resolution_note"] = resolution_note
    dispute["status"] = "RESOLVED_ADJUSTED"
    dispute["granted_adjustment_cents"] = granted
    touch(dispute)

    # Hop one: the statement absorbs the adjustment.
    statement["granted_adjustment_cents"] = statement["granted_adjustment_cents"] + granted
    if statement["final_assessment_cents"] is not None:
        statement["final_assessment_cents"] = core.compute_final(statement)
    core.derive_payment_status(statement)
    touch(statement)

    district = core.district_of_statement(statement)
    core.recompute_period_billed(core.period_of_statement(statement))
    core.recompute_district_money(district)

    # The exemption grant is separate from the three hops.
    if dispute["dispute_type"] == "EXEMPT_PROPERTY":
        business = core.business_of_statement(statement)
        previous_status = business["status"]
        if previous_status == "ASSESSABLE":
            business["status"] = "EXEMPT"
            business["exempt_status"] = exempt_granted
            touch(business)
            core.apply_status_cascade(business, district, previous_status)

    # Hops two and three: the plan re-derives and its programs are suspended.
    planservice.reevaluate_plans(district)
    return envelope.ok(serialize.dispute(dispute))
