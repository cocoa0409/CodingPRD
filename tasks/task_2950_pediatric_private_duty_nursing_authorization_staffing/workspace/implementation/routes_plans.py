"""Plans of care, authorizations and authorization disputes."""
from flask import Blueprint

import auth as authmod
import cascade
import derive
import envelope
import lookup
import serialize
import store
import validate
from errors import fail
from store import db, new_row
from timeutil import add_days, fmt_instant, week_window

bp = Blueprint("plans", __name__)

PLAN_STATUSES = ("DRAFT", "SUBMITTED", "UNDER_REVIEW", "AUTHORIZED", "RETURNED")
AUTH_STATUSES = (
    "PENDING", "ACTIVE", "REDUCTION_NOTICED", "UNDER_APPEAL", "REDUCED", "EXPIRED", "SUPERSEDED",
)
STAFFABLE = ("ACTIVE", "REDUCTION_NOTICED", "UNDER_APPEAL", "REDUCED")
DISPUTE_STATUSES = ("FILED", "UNDER_REVIEW", "UPHELD", "OVERTURNED", "PARTIALLY_GRANTED")
DISPUTE_TYPES = ("REDUCTION_APPEAL", "DENIAL_APPEAL")
DISPUTE_OUTCOMES = ("UPHELD", "OVERTURNED", "PARTIALLY_GRANTED")
UTILIZATION_BASES = ("PROJECTED", "SETTLED")


# --------------------------------------------------------------------------- #
# 16-20. plans of care
# --------------------------------------------------------------------------- #
@bp.route("/plans-of-care", methods=["POST"])
def create_plan():
    authmod.require("CaseManager")
    data = validate.body()
    patient = lookup.get_patient(validate.req_fk(data, "patient_id"))
    requested = validate.req_int(data, "requested_hours_per_week", lo=1, hi=168)
    start_date = validate.req_date(data, "start_date")
    end_date = validate.req_date(data, "end_date")
    if not end_date > start_date:
        validate.bad("Field 'end_date' must be strictly after 'start_date'.")
    npi = validate.req_npi(data, "ordering_physician_npi")
    row = new_row(
        patient_id=patient["id"],
        requested_hours_per_week=requested,
        start_date=start_date,
        end_date=end_date,
        ordering_physician_npi=npi,
        status="DRAFT",
        revision_round=0,
    )
    db.plans[row["id"]] = row
    return cascade.respond(serialize.plan, row, 201)


@bp.route("/plans-of-care/<plan_id>", methods=["GET"])
def read_plan(plan_id):
    authmod.require("CaseManager", "PayerReviewer")
    return envelope.ok(serialize.plan(lookup.get_plan(plan_id)))


@bp.route("/plans-of-care", methods=["GET"])
def list_plans():
    authmod.require("CaseManager", "PayerReviewer")
    limit, offset = validate.pagination()
    patient_id = validate.query_value("patient_id")
    status = validate.query_enum("status", PLAN_STATUSES)
    rows = store.ordered(db.plans)
    if patient_id is not None:
        rows = [r for r in rows if r["patient_id"] == patient_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    total = len(rows)
    body = [serialize.plan(r) for r in validate.page(rows, limit, offset)]
    return envelope.ok_list(body, limit, offset, total)


@bp.route("/plans-of-care/<plan_id>/submit", methods=["POST"])
def submit_plan(plan_id):
    authmod.require("CaseManager")
    plan = lookup.get_plan(plan_id)
    if plan["status"] not in ("DRAFT", "RETURNED"):
        fail("ERR_INVALID_STATE", "A plan of care may only be submitted from DRAFT or RETURNED.")
    if plan["status"] == "DRAFT":
        patient = db.patients.get(plan["patient_id"])
        if patient is not None and patient["status"] == "DISCHARGED":
            fail("ERR_INVALID_STATE", "The patient has been discharged.")
    plan["status"] = "SUBMITTED"
    cascade.touch(plan)
    return cascade.respond(serialize.plan, plan)


@bp.route("/plans-of-care/<plan_id>/return", methods=["POST"])
def return_plan(plan_id):
    uid, role = authmod.require("PayerReviewer")
    plan = lookup.get_plan(plan_id)
    authmod.payer_scope_for_plan(role, uid, plan)
    data = validate.body()
    validate.req_str(data, "return_reason")
    if plan["status"] not in ("SUBMITTED", "UNDER_REVIEW"):
        fail("ERR_INVALID_STATE", "A plan of care may only be returned from SUBMITTED or UNDER_REVIEW.")
    for row in db.authorizations.values():
        if row["plan_of_care_id"] == plan["id"] and row["status"] in STAFFABLE:
            fail("ERR_INVALID_STATE", "A plan of care with a live authorization cannot be returned.")
    plan["status"] = "RETURNED"
    plan["revision_round"] = int(plan["revision_round"]) + 1
    cascade.touch(plan)
    for row in store.ordered(db.authorizations):
        if row["plan_of_care_id"] == plan["id"] and row["status"] == "PENDING":
            row["status"] = "EXPIRED"
            cascade.touch(row)
    return cascade.respond(serialize.plan, plan)


# --------------------------------------------------------------------------- #
# 21-28. authorizations
# --------------------------------------------------------------------------- #
@bp.route("/authorizations", methods=["POST"])
def create_authorization():
    uid, role = authmod.require("PayerReviewer")
    data = validate.body()
    payer_id = validate.req_fk(data, "payer_id")
    authmod.payer_scope(role, uid, payer_id)
    plan = lookup.get_plan(validate.req_fk(data, "plan_of_care_id"))
    payer = lookup.get_payer(payer_id)
    supersedes_id = validate.opt_fk(data, "supersedes_authorization_id")
    if supersedes_id is not None:
        lookup.get_authorization(supersedes_id)
    approved = validate.req_hours(data, "approved_hours_per_week")
    effective_start = validate.req_instant(data, "effective_start")
    effective_end = validate.req_instant(data, "effective_end")
    if not effective_end > effective_start:
        validate.bad("Field 'effective_end' must be strictly after 'effective_start'.")
    expected = validate.req_int(data, "expected_plan_of_care_version")
    if expected != int(plan["version"]):
        fail("ERR_STALE_PLAN_OF_CARE_VERSION",
             "Plan of care version is %d." % int(plan["version"]))
    if plan["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE", "An authorization may only be issued against a SUBMITTED plan.")
    if approved > derive.dec(payer["weekly_hour_cap"]):
        fail("ERR_PAYER_HOUR_CAP_EXCEEDED", "Approved hours exceed the payer weekly hour cap.")
    if approved > derive.dec(plan["requested_hours_per_week"]):
        fail("ERR_APPROVED_EXCEEDS_REQUESTED", "Approved hours exceed the requested hours.")
    row = new_row(
        plan_of_care_id=plan["id"],
        payer_id=payer["id"],
        supersedes_authorization_id=supersedes_id,
        approved_hours_per_week=approved,
        noticed_hours_per_week=None,
        reduction_effective_at=None,
        effective_start=effective_start,
        effective_end=effective_end,
        status="PENDING",
        renewal_chain_depth=0,
    )
    db.authorizations[row["id"]] = row
    plan["status"] = "UNDER_REVIEW"
    cascade.touch(plan)
    return cascade.respond(serialize.authorization, row, 201)


@bp.route("/authorizations/<authorization_id>", methods=["GET"])
def read_authorization(authorization_id):
    authmod.require("PayerReviewer", "CaseManager", "Scheduler")
    return envelope.ok(serialize.authorization(lookup.get_authorization(authorization_id)))


@bp.route("/authorizations", methods=["GET"])
def list_authorizations():
    authmod.require("PayerReviewer", "CaseManager")
    limit, offset = validate.pagination()
    plan_of_care_id = validate.query_value("plan_of_care_id")
    payer_id = validate.query_value("payer_id")
    supersedes = validate.query_value("supersedes_authorization_id")
    status = validate.query_enum("status", AUTH_STATUSES)
    rows = store.ordered(db.authorizations)
    if plan_of_care_id is not None:
        rows = [r for r in rows if r["plan_of_care_id"] == plan_of_care_id]
    if payer_id is not None:
        rows = [r for r in rows if r["payer_id"] == payer_id]
    if supersedes is not None:
        rows = [r for r in rows if r["supersedes_authorization_id"] == supersedes]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    total = len(rows)
    body = [serialize.authorization(r) for r in validate.page(rows, limit, offset)]
    return envelope.ok_list(body, limit, offset, total)


@bp.route("/authorizations/<authorization_id>/activate", methods=["POST"])
def activate_authorization(authorization_id):
    uid, role = authmod.require("PayerReviewer")
    row = lookup.get_authorization(authorization_id)
    authmod.payer_scope(role, uid, row["payer_id"])
    if row["status"] != "PENDING":
        fail("ERR_INVALID_STATE", "Only a PENDING authorization may be activated.")
    if not db.clock < row["effective_end"]:
        fail("ERR_INVALID_STATE", "The authorization window has already closed.")
    predecessor = None
    if row["supersedes_authorization_id"] is not None:
        predecessor = db.authorizations.get(row["supersedes_authorization_id"])
        if predecessor is not None and predecessor["status"] not in ("ACTIVE", "REDUCED"):
            fail("ERR_INVALID_STATE", "The superseded authorization is no longer live.")
    row["status"] = "ACTIVE"
    cascade.touch(row)
    plan = db.plans.get(row["plan_of_care_id"])
    if plan is not None and plan["status"] == "UNDER_REVIEW":
        plan["status"] = "AUTHORIZED"
        cascade.touch(plan)
    if predecessor is not None:
        predecessor["status"] = "SUPERSEDED"
        cascade.touch(predecessor)
        for case in store.ordered(db.cases):
            if case["authorization_id"] == predecessor["id"]:
                case["authorization_id"] = row["id"]
                cascade.touch(case)
    return cascade.respond(serialize.authorization, row)


@bp.route("/authorizations/<authorization_id>/utilization", methods=["GET"])
def read_utilization(authorization_id):
    authmod.require("PayerReviewer", "CaseManager", "Scheduler")
    row = lookup.get_authorization(authorization_id)
    basis = validate.query_enum("basis", UTILIZATION_BASES) or "PROJECTED"
    week_of = validate.query_instant("week_of")
    result = derive.utilization(row, basis, week_of)
    result["week_start"] = fmt_instant(result["week_start"])
    result["week_end"] = fmt_instant(result["week_end"])
    return envelope.ok(result)


@bp.route("/authorizations/<authorization_id>/reduce", methods=["POST"])
def reduce_authorization(authorization_id):
    uid, role = authmod.require("PayerReviewer")
    row = lookup.get_authorization(authorization_id)
    authmod.payer_scope(role, uid, row["payer_id"])
    data = validate.body()
    noticed = validate.req_hours(data, "noticed_hours_per_week")
    validate.req_str(data, "reduction_reason")
    if noticed >= derive.dec(row["approved_hours_per_week"]):
        validate.bad("Field 'noticed_hours_per_week' must be below the approved hours.")
    if row["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE", "Only an ACTIVE authorization may be reduced.")
    payer = db.payers.get(row["payer_id"])
    notice_days = int(payer["reduction_notice_days"]) if payer is not None else 10
    row["noticed_hours_per_week"] = noticed
    row["reduction_effective_at"] = add_days(db.clock, notice_days)
    row["status"] = "REDUCTION_NOTICED"
    cascade.touch(row)
    return cascade.respond(serialize.authorization, row)


@bp.route("/authorizations/<authorization_id>/apply-reduction", methods=["POST"])
def apply_reduction(authorization_id):
    uid, role = authmod.require("PayerReviewer")
    row = lookup.get_authorization(authorization_id)
    authmod.payer_scope(role, uid, row["payer_id"])
    if row["status"] != "REDUCTION_NOTICED":
        fail("ERR_INVALID_STATE", "Only a REDUCTION_NOTICED authorization may be applied.")
    if row["reduction_effective_at"] is None or db.clock < row["reduction_effective_at"]:
        fail("ERR_REDUCTION_NOT_EFFECTIVE", "The reduction is not yet effective.")
    for dispute in db.disputes.values():
        if dispute["authorization_id"] == row["id"] and dispute["status"] in ("FILED", "UNDER_REVIEW"):
            fail("ERR_INVALID_STATE", "A dispute of this authorization is still open.")
    row["approved_hours_per_week"] = row["noticed_hours_per_week"]
    row["noticed_hours_per_week"] = None
    row["reduction_effective_at"] = None
    row["status"] = "REDUCED"
    cascade.touch(row)
    cascade.trim_cascade(row)
    return cascade.respond(serialize.authorization, row)


@bp.route("/authorizations/<authorization_id>/renew", methods=["POST"])
def renew_authorization(authorization_id):
    uid, role = authmod.require("PayerReviewer")
    row = lookup.get_authorization(authorization_id)
    authmod.payer_scope(role, uid, row["payer_id"])
    data = validate.body()
    effective_end = validate.req_instant(data, "effective_end")
    approved = validate.opt_hours(data, "approved_hours_per_week")
    if approved is None:
        approved = derive.dec(row["approved_hours_per_week"])
    effective_start = row["effective_end"]
    if not effective_end > effective_start:
        validate.bad("Field 'effective_end' must be strictly after the successor's effective_start.")
    if row["status"] not in ("ACTIVE", "REDUCED"):
        fail("ERR_INVALID_STATE", "Only an ACTIVE or REDUCED authorization may be renewed.")
    payer = lookup.get_payer(row["payer_id"])
    plan = lookup.get_plan(row["plan_of_care_id"])
    if approved > derive.dec(payer["weekly_hour_cap"]):
        fail("ERR_PAYER_HOUR_CAP_EXCEEDED", "Approved hours exceed the payer weekly hour cap.")
    if approved > derive.dec(plan["requested_hours_per_week"]):
        fail("ERR_APPROVED_EXCEEDS_REQUESTED", "Approved hours exceed the requested hours.")
    if derive.renewal_ratio(row) < derive.RENEWAL_MIN_RATIO:
        fail("ERR_RENEWAL_UTILIZATION_TOO_LOW",
             "Last completed week's utilization is below 0.5000.")
    successor = new_row(
        plan_of_care_id=row["plan_of_care_id"],
        payer_id=row["payer_id"],
        supersedes_authorization_id=row["id"],
        approved_hours_per_week=approved,
        noticed_hours_per_week=None,
        reduction_effective_at=None,
        effective_start=effective_start,
        effective_end=effective_end,
        status="PENDING",
        renewal_chain_depth=int(row["renewal_chain_depth"]) + 1,
    )
    db.authorizations[successor["id"]] = successor
    return cascade.respond(serialize.authorization, successor, 201)


# --------------------------------------------------------------------------- #
# 29-33. authorization disputes
# --------------------------------------------------------------------------- #
def _open_dispute_exists(authorization_id):
    for row in db.disputes.values():
        if row["authorization_id"] == authorization_id and row["status"] in ("FILED", "UNDER_REVIEW"):
            return True
    return False


def _denial_ceiling(dispute, authorization):
    """The smallest of the requested figure, the payer cap and the plan request."""
    payer = db.payers.get(authorization["payer_id"])
    plan = db.plans.get(authorization["plan_of_care_id"])
    values = [derive.dec(dispute["requested_hours_per_week"])]
    if payer is not None:
        values.append(derive.dec(payer["weekly_hour_cap"]))
    if plan is not None:
        values.append(derive.dec(plan["requested_hours_per_week"]))
    return min(values)


@bp.route("/authorization-disputes", methods=["POST"])
def create_dispute():
    uid, _role = authmod.require("CaseManager")
    data = validate.body()
    authorization = lookup.get_authorization(validate.req_fk(data, "authorization_id"))
    dispute_type = validate.req_enum(data, "dispute_type", DISPUTE_TYPES)
    requested = validate.req_hours(data, "requested_hours_per_week")
    reason = validate.req_str(data, "reason")
    # The generic transition-state check is deliberately skipped here (PRD 2.8 #9).
    if authorization["status"] not in ("ACTIVE", "REDUCTION_NOTICED", "UNDER_APPEAL"):
        fail("ERR_AUTHORIZATION_NOT_ACTIVE", "The authorization is not open to dispute.")
    if dispute_type == "REDUCTION_APPEAL":
        effective_at = authorization["reduction_effective_at"]
        if effective_at is None or not db.clock < effective_at:
            fail("ERR_DISPUTE_WINDOW_CLOSED", "The reduction notice window is closed.")
    if _open_dispute_exists(authorization["id"]):
        fail("ERR_DISPUTE_ALREADY_OPEN", "A dispute of this authorization is already open.")
    if dispute_type == "REDUCTION_APPEAL":
        if authorization["status"] != "REDUCTION_NOTICED":
            fail("ERR_INVALID_STATE", "No reduction notice is live on this authorization.")
    else:
        if authorization["status"] != "ACTIVE":
            fail("ERR_INVALID_STATE", "A denial appeal requires an ACTIVE authorization.")
        plan = db.plans.get(authorization["plan_of_care_id"])
        if plan is not None and not derive.dec(authorization["approved_hours_per_week"]) \
                < derive.dec(plan["requested_hours_per_week"]):
            fail("ERR_INVALID_STATE", "The plan of care was granted in full.")
    row = new_row(
        authorization_id=authorization["id"],
        dispute_type=dispute_type,
        requested_hours_per_week=requested,
        reason=reason,
        filed_by_user_id=uid,
        filed_at=db.clock,
        status="FILED",
        decided_hours_per_week=None,
        decided_at=None,
        reviewer_user_id=None,
    )
    db.disputes[row["id"]] = row
    authorization["status"] = "UNDER_APPEAL"
    cascade.touch(authorization)
    return cascade.respond(serialize.dispute, row, 201)


@bp.route("/authorization-disputes/<dispute_id>", methods=["GET"])
def read_dispute(dispute_id):
    authmod.require("CaseManager", "PayerReviewer")
    return envelope.ok(serialize.dispute(lookup.get_dispute(dispute_id)))


@bp.route("/authorization-disputes", methods=["GET"])
def list_disputes():
    authmod.require("CaseManager", "PayerReviewer")
    limit, offset = validate.pagination()
    authorization_id = validate.query_value("authorization_id")
    status = validate.query_enum("status", DISPUTE_STATUSES)
    rows = store.ordered(db.disputes)
    if authorization_id is not None:
        rows = [r for r in rows if r["authorization_id"] == authorization_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    total = len(rows)
    body = [serialize.dispute(r) for r in validate.page(rows, limit, offset)]
    return envelope.ok_list(body, limit, offset, total)


@bp.route("/authorization-disputes/<dispute_id>/review", methods=["POST"])
def review_dispute(dispute_id):
    uid, role = authmod.require("PayerReviewer")
    row = lookup.get_dispute(dispute_id)
    authorization = db.authorizations.get(row["authorization_id"])
    if authorization is not None:
        authmod.payer_scope(role, uid, authorization["payer_id"])
    if row["status"] != "FILED":
        fail("ERR_INVALID_STATE", "Only a FILED dispute may be taken under review.")
    row["status"] = "UNDER_REVIEW"
    row["reviewer_user_id"] = uid
    cascade.touch(row)
    return cascade.respond(serialize.dispute, row)


@bp.route("/authorization-disputes/<dispute_id>/decide", methods=["POST"])
def decide_dispute(dispute_id):
    uid, role = authmod.require("PayerReviewer")
    row = lookup.get_dispute(dispute_id)
    authorization = db.authorizations.get(row["authorization_id"])
    if authorization is not None:
        authmod.payer_scope(role, uid, authorization["payer_id"])
    data = validate.body()
    outcome = validate.req_enum(data, "outcome", DISPUTE_OUTCOMES)
    decided = validate.opt_hours(data, "decided_hours_per_week")
    validate.opt_str(data, "decision_note")
    if row["status"] != "UNDER_REVIEW":
        fail("ERR_INVALID_STATE", "Only an UNDER_REVIEW dispute may be decided.")
    approved = derive.dec(authorization["approved_hours_per_week"])
    if outcome == "PARTIALLY_GRANTED":
        if decided is None:
            fail("ERR_DECIDED_HOURS_OUT_OF_RANGE",
                 "decided_hours_per_week is required for PARTIALLY_GRANTED.")
        if row["dispute_type"] == "REDUCTION_APPEAL":
            noticed = derive.dec(authorization["noticed_hours_per_week"] or 0)
            if not (noticed < decided < approved):
                fail("ERR_DECIDED_HOURS_OUT_OF_RANGE",
                     "decided_hours_per_week must sit strictly inside the noticed-approved band.")
        else:
            ceiling = _denial_ceiling(row, authorization)
            if not (approved < decided <= ceiling):
                fail("ERR_DECIDED_HOURS_OUT_OF_RANGE",
                     "decided_hours_per_week must exceed the approved figure and stay within the ceiling.")
    row["status"] = outcome
    row["decided_at"] = db.clock
    row["decided_hours_per_week"] = decided if outcome == "PARTIALLY_GRANTED" else None
    cascade.touch(row)
    trim = False
    if row["dispute_type"] == "REDUCTION_APPEAL":
        if outcome == "UPHELD":
            authorization["approved_hours_per_week"] = authorization["noticed_hours_per_week"]
            authorization["status"] = "REDUCED"
            trim = True
        elif outcome == "PARTIALLY_GRANTED":
            authorization["approved_hours_per_week"] = decided
            authorization["status"] = "REDUCED"
            trim = True
        else:
            authorization["status"] = "ACTIVE"
        authorization["noticed_hours_per_week"] = None
        authorization["reduction_effective_at"] = None
    else:
        if outcome == "OVERTURNED":
            authorization["approved_hours_per_week"] = _denial_ceiling(row, authorization)
        elif outcome == "PARTIALLY_GRANTED":
            authorization["approved_hours_per_week"] = decided
        authorization["status"] = "ACTIVE"
    cascade.touch(authorization)
    if trim:
        cascade.trim_cascade(authorization)
    return cascade.respond(serialize.dispute, row)
