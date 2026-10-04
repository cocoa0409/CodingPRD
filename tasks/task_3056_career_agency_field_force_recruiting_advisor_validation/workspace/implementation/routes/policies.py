"""Policy, JointWorkCase, CommissionCredit and PersistencyRecord endpoints
(§1.5; PRD §3.6, §3.7)."""

from flask import Blueprint, request

from db import db
from errors import err, ERR_INVALID_REQUEST
from middleware import body, required, pagination, page
from response import ok, ok_list
from routes._shared import authed
from services import jointwork, persistency, policies, serialize

bp = Blueprint("policies", __name__)
READ = ["Any"]
MD = ["ManagingDirector"]
REP = ["FinancialRep"]

# Money/business reads are shared, so every role holds them via Any.


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------
@bp.post("/agency/policies")
@authed(MD)
def create(user_id, role):
    data = body()
    row = policies.create(data)
    return ok(serialize.policy(row), 201)


@bp.get("/agency/policies")
@authed(READ)
def list_policies(user_id, role):
    limit, offset = pagination()
    advisor_id = request.args.get("writing_advisor_id")
    product_line = request.args.get("product_line")
    status = request.args.get("status")
    orphaned = request.args.get("orphaned")
    items = [p for p in db.policies.values()
             if (advisor_id is None or p["writing_advisor_id"] == advisor_id)
             and (product_line is None or p["product_line"] == product_line)
             and (status is None or p["status"] == status)
             and (orphaned is None or str(p["orphaned"]).lower() == orphaned.lower())]
    selected = page(items, limit, offset)
    return ok_list([serialize.policy(p) for p in selected], limit, offset, len(items))


@bp.get("/agency/policies/<policy_id>")
@authed(READ)
def get_policy(user_id, role, policy_id):
    return ok(serialize.policy(policies.get(policy_id)))


@bp.post("/agency/policies/<policy_id>/activate")
@authed(MD)
def activate(user_id, role, policy_id):
    row = policies.get(policy_id)
    policies.activate(row)
    return ok(serialize.policy(row))


@bp.post("/agency/policies/<policy_id>/lapse")
@authed(MD)
def lapse(user_id, role, policy_id):
    row = policies.get(policy_id)
    lapse_date = body().get("lapse_date")
    if lapse_date is None:
        raise err(ERR_INVALID_REQUEST, "lapse_date is required")
    policies.lapse(row, lapse_date)
    return ok(serialize.policy(row))


@bp.post("/agency/policies/<policy_id>/reinstate")
@authed(MD)
def reinstate(user_id, role, policy_id):
    row = policies.get(policy_id)
    policies.reinstate(row)
    return ok(serialize.policy(row))


@bp.post("/agency/policies/<policy_id>/surrender")
@authed(MD)
def surrender(user_id, role, policy_id):
    row = policies.get(policy_id)
    policies.surrender(row)
    return ok(serialize.policy(row))


@bp.post("/agency/policies/<policy_id>/terminate")
@authed(MD)
def terminate(user_id, role, policy_id):
    row = policies.get(policy_id)
    policies.terminate(row)
    return ok(serialize.policy(row))


@bp.get("/agency/policies/<policy_id>/joint-work-cases")
@authed(READ)
def policy_joint_cases(user_id, role, policy_id):
    policies.get(policy_id)
    limit, offset = pagination()
    status = request.args.get("status")
    items = [c for c in db.joint_cases.values()
             if c["policy_id"] == policy_id
             and (status is None or c["status"] == status)]
    selected = page(items, limit, offset)
    return ok_list([serialize.joint(c) for c in selected], limit, offset, len(items))


@bp.get("/agency/policies/<policy_id>/commission-credits")
@authed(READ)
def policy_credits(user_id, role, policy_id):
    policies.get(policy_id)
    limit, offset = pagination()
    credit_type = request.args.get("credit_type")
    status = request.args.get("status")
    items = [c for c in db.credits.values()
             if c["policy_id"] == policy_id
             and (credit_type is None or c["credit_type"] == credit_type)
             and (status is None or c["status"] == status)]
    selected = page(items, limit, offset)
    return ok_list([serialize.credit(c) for c in selected], limit, offset, len(items))


@bp.get("/agency/policies/<policy_id>/orphan-policy-assignments")
@authed(READ)
def policy_orphans(user_id, role, policy_id):
    policies.get(policy_id)
    limit, offset = pagination()
    status = request.args.get("status")
    items = [o for o in db.orphans.values()
             if o["policy_id"] == policy_id
             and (status is None or o["status"] == status)]
    selected = page(items, limit, offset)
    return ok_list([serialize.orphan(o) for o in selected], limit, offset, len(items))


# ---------------------------------------------------------------------------
# JointWorkCase
# ---------------------------------------------------------------------------
@bp.post("/agency/joint-work-cases")
@authed(REP)
def create_case(user_id, role):
    data = body()
    row = jointwork.create(data)
    return ok(serialize.joint(row), 201)


@bp.get("/agency/joint-work-cases/<case_id>")
@authed(READ)
def get_case(user_id, role, case_id):
    return ok(serialize.joint(jointwork.get(case_id)))


@bp.post("/agency/joint-work-cases/<case_id>/submit")
@authed(REP)
def submit_case(user_id, role, case_id):
    row = jointwork.get(case_id)
    jointwork.submit(row, user_id)
    return ok(serialize.joint(row))


@bp.post("/agency/joint-work-cases/<case_id>/close")
@authed(MD)
def close_case(user_id, role, case_id):
    row = jointwork.get(case_id)
    jointwork.close(row)
    return ok(serialize.joint(row))


@bp.post("/agency/joint-work-cases/<case_id>/void")
@authed(["FinancialRep", "ManagingDirector"])
def void_case(user_id, role, case_id):
    row = jointwork.get(case_id)
    jointwork.void(row, user_id, role)
    return ok(serialize.joint(row))


@bp.post("/agency/joint-work-cases/<case_id>/reopen")
@authed(REP)
def reopen_case(user_id, role, case_id):
    row = jointwork.get(case_id)
    jointwork.reopen(row)
    return ok(serialize.joint(row))


# ---------------------------------------------------------------------------
# CommissionCredit
# ---------------------------------------------------------------------------
@bp.get("/agency/commission-credits/<credit_id>")
@authed(READ)
def get_credit(user_id, role, credit_id):
    return ok(serialize.credit(policies.get_credit(credit_id)))


@bp.post("/agency/commission-credits/<credit_id>/pay")
@authed(MD)
def pay_credit(user_id, role, credit_id):
    row = policies.get_credit(credit_id)
    if row["status"] in ("VOIDED", "RECOVERED"):
        from errors import ERR_ALREADY_TERMINAL
        raise err(ERR_ALREADY_TERMINAL, "the credit is terminal")
    if row["status"] != "ACCRUED":
        from errors import ERR_INVALID_STATE
        raise err(ERR_INVALID_STATE, "the credit is not ACCRUED")
    # Posture gate (priority 7) — evaluated before payment executes.
    advisor = db.advisors.get(row["advisor_id"])
    if advisor is not None and advisor["validation_posture"] not in ("VALIDATING", "VALIDATED"):
        from errors import ERR_VALIDATION_POSTURE_BLOCKS_PAYOUT
        raise err(ERR_VALIDATION_POSTURE_BLOCKS_PAYOUT,
                  "the advisor's validation posture blocks payout")
    policies.pay(row)
    return ok(serialize.credit(row))


@bp.post("/agency/commission-credits/<credit_id>/void")
@authed(MD)
def void_credit(user_id, role, credit_id):
    row = policies.get_credit(credit_id)
    policies.void(row)
    return ok(serialize.credit(row))


@bp.post("/agency/commission-credits/<credit_id>/recover")
@authed(MD)
def recover_credit(user_id, role, credit_id):
    row = policies.get_credit(credit_id)
    amount = body().get("amount_cents")
    if amount is None:
        raise err(ERR_INVALID_REQUEST, "amount_cents is required")
    policies.recover(row, amount)
    return ok(serialize.credit(row))


# ---------------------------------------------------------------------------
# PersistencyRecord
# ---------------------------------------------------------------------------
@bp.post("/agency/persistency-records")
@authed(MD)
def create_persistency(user_id, role):
    data = body()
    row = persistency.open_record(data)
    return ok(serialize.persistency(row), 201)


@bp.get("/agency/persistency-records/<record_id>")
@authed(READ)
def get_persistency(user_id, role, record_id):
    return ok(serialize.persistency(persistency.get(record_id)))


@bp.post("/agency/persistency-records/<record_id>/dispute")
@authed(REP)
def dispute(user_id, role, record_id):
    row = persistency.get(record_id)
    persistency.dispute(row, user_id)
    return ok(serialize.persistency(row))


@bp.post("/agency/persistency-records/<record_id>/resolve-dispute")
@authed(MD)
def resolve(user_id, role, record_id):
    row = persistency.get(record_id)
    persistency.resolve_dispute(row)
    return ok(serialize.persistency(row))


@bp.post("/agency/persistency-records/<record_id>/finalize")
@authed(MD)
def finalize(user_id, role, record_id):
    row = persistency.get(record_id)
    persistency.finalize(row)
    return ok(serialize.persistency(row))


# ---------------------------------------------------------------------------
# OrphanPolicyAssignment
# ---------------------------------------------------------------------------
@bp.get("/agency/orphan-policy-assignments/<assignment_id>")
@authed(READ)
def get_orphan(user_id, role, assignment_id):
    from services import orphans
    return ok(serialize.orphan(orphans.get(assignment_id)))


@bp.post("/agency/orphan-policy-assignments/<assignment_id>/assign")
@authed(MD)
def assign_orphan(user_id, role, assignment_id):
    from services import orphans
    row = orphans.get(assignment_id)
    orphans.assign(row)
    return ok(serialize.orphan(row))


@bp.post("/agency/orphan-policy-assignments/<assignment_id>/reopen")
@authed(MD)
def reopen_orphan(user_id, role, assignment_id):
    from services import orphans
    row = orphans.get(assignment_id)
    orphans.reopen(row)
    return ok(serialize.orphan(row))