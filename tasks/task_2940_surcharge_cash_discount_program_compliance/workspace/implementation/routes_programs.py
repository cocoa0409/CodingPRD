"""Program construction, activation, the lifecycle actions and the two summaries."""

from decimal import Decimal

from flask import Blueprint, request

import auth
import calc
import cascades
import listing
import serialize
import validation as v
from auth import authorize, check_action_role
from envelope import created, ok
from errors import ApiError
from store import db, base_row, touch
from validation import MISSING, as_enum, as_int, as_string, field, parse_body, round_cents

bp = Blueprint("programs", __name__)

PROGRAM_TYPES = ("SURCHARGE", "CASH_DISCOUNT")
CONSISTENCY_SCOPES = ("BRAND_LEVEL", "PRODUCT_LEVEL")
PROGRAM_STATUSES = ("DRAFT", "PENDING_REGISTRATION", "ACTIVE", "SUSPENDED",
                    "REMEDIATION", "DISABLED", "WITHDRAWN")
STATUS_ACTIONS = ("SUSPEND", "RESUME", "WITHDRAW")


def jurisdiction_of(program):
    return db.jurisdictions.get(program["jurisdiction_id"])


def check_structure_permitted(program):
    """Ladder steps 16 and 17."""
    jur = jurisdiction_of(program)
    if program["program_type"] == "SURCHARGE":
        if not (jur and jur["surcharge_permitted"]):
            raise ApiError("ERR_SURCHARGE_PROHIBITED_JURISDICTION",
                           "Credit-card surcharging is not permitted in this jurisdiction.")
    else:
        if not (jur and jur["cash_discount_permitted"]):
            raise ApiError("ERR_CASH_DISCOUNT_PROHIBITED_JURISDICTION",
                           "Cash-discount programs are not permitted in this jurisdiction.")


def rule_in_effect(rule, clock):
    """Closed effectivity interval, both ends inclusive."""
    return rule["effective_from"] <= clock <= rule["effective_to"]


def any_rate_rule_in_effect(program):
    clock = db.now()
    return any(rule_in_effect(r, clock) for r in calc.program_rate_rules(program["id"]))


def check_segregation_of_duties(program, actor):
    """Ladder step 15: every artifact of the program, whatever its state."""
    for art in calc.program_artifacts(program["id"]):
        if art.get("attested_by_user_id") is not None and art["attested_by_user_id"] == actor.user_id:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                           "An officer who attested a disclosure artifact may not activate the program.")


def check_pinned_documentation_active(program):
    """Ladder step 25."""
    doc = db.cost_documentations.get(program.get("cost_documentation_id"))
    if doc is None or doc["state"] != "ACTIVE":
        raise ApiError("ERR_COST_DOCUMENTATION_STALE",
                       "The program's pinned cost documentation is no longer ACTIVE.")


@bp.post("/surcharge-programs")
def create_program():
    authorize(["ComplianceOfficer"])
    body, malformed = parse_body()
    if malformed:
        raise v.bad("The request body must be a JSON object.")
    v.require_present(body, ["merchant_id", "jurisdiction_id", "cost_documentation_id",
                            "program_type", "consistency_scope"])
    merchant_id = as_string(body["merchant_id"], "merchant_id", 1)
    jurisdiction_id = as_string(body["jurisdiction_id"], "jurisdiction_id", 1)
    doc_id = as_string(body["cost_documentation_id"], "cost_documentation_id", 1)
    program_type = as_enum(body["program_type"], "program_type", PROGRAM_TYPES)
    consistency_scope = as_enum(body["consistency_scope"], "consistency_scope", CONSISTENCY_SCOPES)

    merchant = auth.get_merchant(merchant_id)
    jur = auth.get_jurisdiction(jurisdiction_id)
    doc = auth.get_cost_documentation(doc_id)

    if program_type == "SURCHARGE":
        if not jur["surcharge_permitted"]:
            raise ApiError("ERR_SURCHARGE_PROHIBITED_JURISDICTION",
                           "Credit-card surcharging is not permitted in this jurisdiction.")
    else:
        if not jur["cash_discount_permitted"]:
            raise ApiError("ERR_CASH_DISCOUNT_PROHIBITED_JURISDICTION",
                           "Cash-discount programs are not permitted in this jurisdiction.")

    if merchant["jurisdiction_id"] != jur["id"]:
        raise ApiError("ERR_JURISDICTION_SCOPE_MISMATCH",
                       "The program's jurisdiction must equal the merchant's jurisdiction.")
    if doc["merchant_id"] != merchant["id"]:
        raise ApiError("ERR_COST_DOCUMENTATION_MERCHANT_MISMATCH",
                       "The pinned cost documentation belongs to another merchant.")

    row = base_row()
    row.update({
        "merchant_id": merchant["id"],
        "jurisdiction_id": jur["id"],
        "cost_documentation_id": doc["id"],
        "program_type": program_type,
        "consistency_scope": consistency_scope,
        "status": "DRAFT",
        "disable_reason": "NONE",
        "disclosure_ready": False,
        "network_exposure_score": Decimal(0),
        "ag_exposure_score": Decimal(0),
        "activated_at": None,
        "activated_by_user_id": None,
        "cost_documentation_pinned_at": db.now(),
    })
    calc.recompute_cap(row)
    db.programs[row["id"]] = row
    return created(serialize.program(row))


@bp.get("/surcharge-programs/<program_id>")
def read_program(program_id):
    authorize(auth.READ_ROLES)
    return ok(serialize.program(auth.get_program(program_id)))


@bp.get("/surcharge-programs")
def list_programs():
    authorize(auth.READ_ROLES)
    rows = listing.filtered(list(db.programs.values()), [
        (listing.arg("merchant_id"), "merchant_id"),
        (listing.arg("jurisdiction_id"), "jurisdiction_id"),
        (listing.arg("cost_documentation_id"), "cost_documentation_id"),
        (listing.enum_arg("status", PROGRAM_STATUSES), "status"),
        (listing.enum_arg("program_type", PROGRAM_TYPES), "program_type"),
    ])
    return listing.list_response(rows, serialize.program)


@bp.patch("/surcharge-programs/<program_id>")
def patch_program(program_id):
    authorize(["ComplianceOfficer"])
    program = auth.get_program(program_id)
    body, malformed = parse_body()
    if malformed:
        raise v.bad("The request body must be a JSON object.")
    v.require_present(body, ["expected_program_version"])
    expected = as_int(body["expected_program_version"], "expected_program_version", 0)

    doc_raw = field(body, "cost_documentation_id")
    new_doc_id = None
    if doc_raw is not MISSING and doc_raw is not None:
        new_doc_id = as_string(doc_raw, "cost_documentation_id", 1)
    scope_raw = field(body, "consistency_scope")
    new_scope = None
    if scope_raw is not MISSING and scope_raw is not None:
        new_scope = as_enum(scope_raw, "consistency_scope", CONSISTENCY_SCOPES)

    doc = auth.get_cost_documentation(new_doc_id) if new_doc_id is not None else None

    if expected != program["version"]:
        raise ApiError("ERR_STALE_PROGRAM_VERSION",
                       "expected_program_version %d does not match the program's current version %d."
                       % (expected, program["version"]))

    if program["status"] not in ("DRAFT", "PENDING_REGISTRATION"):
        raise ApiError("ERR_INVALID_PROGRAM_STATE",
                       "A program in status %s can no longer be adjusted." % program["status"])

    if doc is not None and doc["merchant_id"] != program["merchant_id"]:
        raise ApiError("ERR_COST_DOCUMENTATION_MERCHANT_MISMATCH",
                       "The replacement cost documentation belongs to another merchant.")

    if doc is not None:
        if doc["id"] != program["cost_documentation_id"]:
            program["cost_documentation_id"] = doc["id"]
            program["cost_documentation_pinned_at"] = db.now()
    if new_scope is not None:
        program["consistency_scope"] = new_scope
    calc.recompute_cap(program)
    touch(program)
    return ok(serialize.program(program))


# ------------------------------------------------------------------- activation
def check_brand_coverage(program):
    """Ladder step 30: every network holding an EFFECTIVE registration is priced."""
    clock = db.now()
    rules = calc.program_rate_rules(program["id"])
    for reg in calc.program_registrations(program["id"]):
        if reg["state"] != "EFFECTIVE":
            continue
        covered = any(r["brand"] == reg["network"] and rule_in_effect(r, clock) for r in rules)
        if not covered:
            raise ApiError("ERR_BRAND_CONSISTENCY_VIOLATION",
                           "Network %s holds an effective registration but carries no rate rule in effect."
                           % reg["network"])


def check_registration_effective(program):
    """Ladder step 31 on the activation arm."""
    for reg in calc.program_registrations(program["id"]):
        if reg["state"] == "EFFECTIVE":
            return
    raise ApiError("ERR_REGISTRATION_NOT_EFFECTIVE",
                   "No network registration of this program is EFFECTIVE.")


def check_readiness(program):
    """Ladder step 32."""
    if not calc.disclosure_readiness(program):
        raise ApiError("ERR_DISCLOSURE_INCOMPLETE",
                       "The program's required disclosure artifacts are not attested and in window.")


def check_price_posting(program):
    """Ladder step 33."""
    jur = jurisdiction_of(program)
    if jur is not None and jur["price_posting_required"]:
        if not calc.price_list_posting_in_window(program):
            raise ApiError("ERR_PRICE_POSTING_REQUIRED",
                           "This jurisdiction demands an attested PRICE_LIST_POSTING in window.")


def check_rate_rule_in_effect(program):
    """Ladder step 34."""
    if not any_rate_rule_in_effect(program):
        raise ApiError("ERR_NO_RATE_RULE_IN_EFFECT",
                       "No rate rule of this program is in effect at the current logical clock.")


@bp.post("/surcharge-programs/<program_id>/activate")
def activate_program(program_id):
    actor = authorize(["ComplianceOfficer"])
    program = auth.get_program(program_id)
    body, malformed = parse_body()
    if malformed:
        raise v.bad("The request body must be a JSON object.")

    required_status = "PENDING_REGISTRATION" if program["program_type"] == "SURCHARGE" else "DRAFT"
    if program["status"] != required_status:
        raise ApiError("ERR_INVALID_PROGRAM_STATE",
                       "A %s program in status %s declares no activation transition."
                       % (program["program_type"], program["status"]))

    check_segregation_of_duties(program, actor)
    check_structure_permitted(program)
    check_pinned_documentation_active(program)
    if program["program_type"] == "SURCHARGE":
        check_brand_coverage(program)
        check_registration_effective(program)
        check_readiness(program)
    else:
        check_readiness(program)
        check_price_posting(program)
    check_rate_rule_in_effect(program)

    program["status"] = "ACTIVE"
    program["disable_reason"] = "NONE"
    program["activated_at"] = db.now()
    program["activated_by_user_id"] = actor.user_id
    calc.recompute_cap(program)
    calc.recompute_disclosure_ready(program)
    touch(program)
    return ok(serialize.program(program))


# --------------------------------------------------------------- status actions
@bp.post("/surcharge-programs/<program_id>/status-actions")
def program_status_action(program_id):
    actor = authorize(["ComplianceOfficer", "NetworkAuditor"])
    body, malformed = parse_body()
    raw_action = None if malformed else field(body, "action")
    check_action_role("program_status", raw_action, actor)
    program = auth.get_program(program_id)
    if malformed:
        raise v.bad("The request body must be a JSON object.")
    v.require_present(body, ["action"])
    action = as_enum(body["action"], "action", STATUS_ACTIONS)
    reason_raw = field(body, "reason")
    if reason_raw is not MISSING and reason_raw is not None:
        as_string(reason_raw, "reason", 1, 500)

    if action == "SUSPEND":
        if program["status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_PROGRAM_STATE",
                           "Only an ACTIVE program can be suspended.")
        cascades.suspend_program(program, "OPERATOR_SUSPENSION", "PROGRAM_SUSPENDED")
    elif action == "RESUME":
        if program["status"] != "SUSPENDED":
            raise ApiError("ERR_INVALID_PROGRAM_STATE",
                           "Only a SUSPENDED program can be resumed.")
        check_structure_permitted(program)
        if program["program_type"] == "SURCHARGE":
            for reg in calc.program_registrations(program["id"]):
                if reg["state"] == "REVOKED":
                    raise ApiError("ERR_REGISTRATION_NOT_EFFECTIVE",
                                   "A revoked network registration blocks the resume.")
        check_readiness(program)
        program["status"] = "ACTIVE"
        program["disable_reason"] = "NONE"
        program["activated_at"] = db.now()
        program["activated_by_user_id"] = actor.user_id
        calc.recompute_cap(program)
        calc.recompute_disclosure_ready(program)
        touch(program)
    else:
        if program["status"] == "WITHDRAWN":
            raise ApiError("ERR_INVALID_PROGRAM_STATE",
                           "A WITHDRAWN program cannot be withdrawn again.")
        cascades.withdraw_program(program)

    return ok(serialize.program(program))


# -------------------------------------------------------------------- summaries
@bp.get("/surcharge-programs/<program_id>/exposure-summary")
def exposure_summary(program_id):
    authorize(auth.SUMMARY_ROLES)
    program = auth.get_program(program_id)
    cases = calc.program_cases(program["id"])
    substantiated = sum(1 for c in cases if c["investigation_state"] == "SUBSTANTIATED")
    unresolved = sum(1 for c in cases if c["investigation_state"] in ("OPEN", "UNDER_REVIEW"))
    jur = jurisdiction_of(program)
    posture = calc.POSTURE_MULTIPLIER.get(jur["ag_enforcement_posture"], Decimal(1)) if jur else Decimal(1)
    return ok({
        "program_id": program["id"],
        "network_exposure_score": program["network_exposure_score"],
        "ag_exposure_score": program["ag_exposure_score"],
        "substantiated_case_count": substantiated,
        "unresolved_case_count": unresolved,
        "posture_multiplier": posture,
        "remediation_threshold": calc.REMEDIATION_EXPOSURE_THRESHOLD,
    })


@bp.get("/surcharge-programs/<program_id>/settlement-summary")
def settlement_summary(program_id):
    authorize(auth.SUMMARY_ROLES)
    program = auth.get_program(program_id)

    from_raw = listing.arg("from_iso8601")
    to_raw = listing.arg("to_iso8601")
    lower = v.as_instant(from_raw, "from_iso8601") if from_raw is not None else None
    upper = v.as_instant(to_raw, "to_iso8601") if to_raw is not None else None

    rows = []
    for tx in calc.program_transactions(program["id"]):
        occurred = tx["occurred_at"]
        if lower is not None and occurred < lower:
            continue
        if upper is not None and occurred >= upper:
            continue
        rows.append(tx)

    transaction_count = len(rows)
    base_total = sum(tx["base_amount_cents"] for tx in rows)
    per_line = sum(tx["surcharge_amount_cents"] for tx in rows)

    groups = {}
    for tx in rows:
        if tx["outcome"] != "APPROVED_WITH_SURCHARGE":
            continue
        rate = Decimal(tx["applied_rate_pct"])
        groups[rate] = groups.get(rate, 0) + tx["base_amount_cents"]
    pooled = 0
    for rate, base_sum in groups.items():
        pooled += round_cents(Decimal(base_sum) * rate / Decimal(100))

    in_scope_ids = set(tx["id"] for tx in rows)
    refunded = 0
    for refund in db.refunds.values():
        if refund["state"] == "ISSUED" and refund["transaction_id"] in in_scope_ids:
            refunded += refund["refund_amount_cents"]

    return ok({
        "program_id": program["id"],
        "transaction_count": transaction_count,
        "base_amount_total_cents": base_total,
        "per_line_rounded_surcharge_cents": per_line,
        "pooled_rounding_reference_cents": pooled,
        "rounding_divergence_cents": per_line - pooled,
        "refunded_surcharge_cents": refunded,
        "net_surcharge_cents": per_line - refunded,
    })
