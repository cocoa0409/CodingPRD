"""Fraud investigation, recovery assessment and collection (PRD §3.8)."""

from flask import Blueprint

import calc
import db
import enums
import envelope as env
import services
import validate as v
from errors import fail
from validate import endpoint

bp = Blueprint("fraud", __name__)


def _case_or_404(case_id):
    case = db.get("fraud_cases", case_id)
    if case is None:
        fail("ERR_FRAUD_CASE_NOT_FOUND")
    return case


# --------------------------------------------------------------------------
# Opening a case
# --------------------------------------------------------------------------
@bp.post("/fraud-cases")
@endpoint(["FraudInvestigator"])
def open_fraud_case():
    body = v.body()
    taxpayer_id = v.req_str(body, "taxpayer_id")
    grant_id = v.req_str(body, "grant_id")
    improper_start_tax_year = v.req_int(body, "improper_start_tax_year")
    improper_end_tax_year = v.req_int(body, "improper_end_tax_year")
    assessment_tax_year = v.req_int(body, "assessment_tax_year")
    if improper_start_tax_year > improper_end_tax_year:
        fail(
            "ERR_INVALID_REQUEST",
            "improper_start_tax_year must not be later than improper_end_tax_year.",
        )

    taxpayer = db.get("taxpayer_accounts", taxpayer_id)
    if taxpayer is None:
        fail("ERR_TAXPAYER_NOT_FOUND")
    grant = db.get("exemption_grants", grant_id)
    if grant is None:
        fail("ERR_GRANT_NOT_FOUND")

    case = db.insert("fraud_cases", {
        "taxpayer_id": taxpayer_id,
        "grant_id": grant_id,
        "improper_start_tax_year": improper_start_tax_year,
        "improper_end_tax_year": improper_end_tax_year,
        "assessment_tax_year": assessment_tax_year,
        "screening_risk_score": calc.fraud_risk_score(taxpayer_id, "SCREENING_SNAPSHOT"),
        "adjudication_risk_score": 0,
        "investigation_status": "OPEN",
        "recovery_status": "NONE",
        "back_tax_cents": 0,
        "penalty_cents": 0,
        "interest_cents": 0,
        "total_assessed_cents": 0,
        "recovery_paid_cents": 0,
        "opened_by_user_id": v.caller_id(),
        "substantiated_by_user_id": None,
    })

    if grant["benefit_status"] == "ACTIVE":
        services.set_grant_status(grant, "SUSPENDED", "FRAUD_INVESTIGATION")
        services.refresh_taxpayer_status(taxpayer)
        db.touch(taxpayer)
        services.mail_notice(
            grant["taxpayer_id"],
            "EXEMPTION_GRANT",
            grant["id"],
            "SUSPENSION",
            "Exemption grant suspended pending a fraud investigation.",
            appealable=True,
        )
    else:
        services.refresh_taxpayer_status(taxpayer)
        db.touch(taxpayer)

    return env.created(db.public(case))


@bp.get("/fraud-cases/<case_id>")
@endpoint(["FraudInvestigator", "RecoveryOfficer", "ExemptionsReviewer"])
def read_fraud_case(case_id):
    case = _case_or_404(case_id)
    return env.ok(db.public(case))


@bp.get("/fraud-cases")
@endpoint(["FraudInvestigator", "RecoveryOfficer", "ExemptionsReviewer"])
def list_fraud_cases():
    limit, offset = v.pagination()
    taxpayer_id = v.q_str("taxpayer_id")
    grant_id = v.q_str("grant_id")
    investigation_status = v.q_enum("investigation_status", enums.INVESTIGATION_STATUSES)
    recovery_status = v.q_enum("recovery_status", enums.RECOVERY_STATUSES)
    items = []
    for case in db.rows("fraud_cases"):
        if taxpayer_id is not None and case["taxpayer_id"] != taxpayer_id:
            continue
        if grant_id is not None and case["grant_id"] != grant_id:
            continue
        if investigation_status is not None and case["investigation_status"] != investigation_status:
            continue
        if recovery_status is not None and case["recovery_status"] != recovery_status:
            continue
        items.append(db.public(case))
    return env.listing(items, limit, offset)


# --------------------------------------------------------------------------
# Adjudication
# --------------------------------------------------------------------------
@bp.post("/fraud-cases/<case_id>/decide")
@endpoint(["FraudInvestigator"])
def decide_fraud_case(case_id):
    case = _case_or_404(case_id)
    body = v.body()
    action = v.req_enum(body, "action", enums.FRAUD_ACTIONS)
    v.opt_str(body, "findings", None)

    if case["investigation_status"] != "OPEN":
        fail("ERR_CASE_ALREADY_ADJUDICATED")

    replayed = calc.fraud_risk_score(case["taxpayer_id"], "ADJUDICATION_REPLAY")

    grant = db.get("exemption_grants", case["grant_id"])
    taxpayer = db.get("taxpayer_accounts", case["taxpayer_id"])

    if action == "CLEAR":
        case["adjudication_risk_score"] = replayed
        case["investigation_status"] = "CLEARED"
        db.touch(case)
        if grant is not None and grant["benefit_status"] == "SUSPENDED":
            services.set_grant_status(grant, "ACTIVE", None)
        if taxpayer is not None:
            services.refresh_taxpayer_status(taxpayer)
            db.touch(taxpayer)
        return env.ok(db.public(case))

    if replayed < db.RISK_SUBSTANTIATION_THRESHOLD:
        fail("ERR_RISK_SCORE_BELOW_THRESHOLD")
    if case["improper_end_tax_year"] > case["assessment_tax_year"]:
        fail("ERR_INVALID_REQUEST", "improper_end_tax_year must not follow assessment_tax_year.")

    program = db.get("relief_programs", grant["program_id"])
    assessment = calc.recovery_assessment(case, grant, program)

    case["adjudication_risk_score"] = replayed
    case["investigation_status"] = "SUBSTANTIATED"
    case["substantiated_by_user_id"] = v.caller_id()
    case.update(assessment)
    case["recovery_status"] = "ASSESSED"
    db.touch(case)

    services.set_grant_status(grant, "REVOKED", None)

    for claim in db.rows("retroactive_claims"):
        if claim["grant_id"] != grant["id"] or claim["status"] != "APPROVED":
            continue
        claim["status"] = "REVERSED"
        db.touch(claim)
        services.add_refund(taxpayer, -claim["total_payable_cents"])
        db.touch(taxpayer)

    taxpayer["status"] = "BARRED"
    db.touch(taxpayer)

    for certification in db.rows("income_certifications"):
        if certification["taxpayer_id"] != case["taxpayer_id"]:
            continue
        if certification["status"] != "CERTIFIED":
            continue
        if not (
            case["improper_start_tax_year"]
            <= certification["certification_year"]
            <= case["improper_end_tax_year"]
        ):
            continue
        certification["status"] = "REVOKED"
        db.touch(certification)

    services.mail_notice(
        case["taxpayer_id"],
        "FRAUD_CASE",
        case["id"],
        "RECOVERY_ASSESSMENT",
        "Recovery assessment raised on a substantiated fraud case.",
        appealable=True,
    )
    return env.ok(db.public(case))


# --------------------------------------------------------------------------
# Collection
# --------------------------------------------------------------------------
@bp.post("/fraud-cases/<case_id>/recovery-actions")
@endpoint(["RecoveryOfficer"])
def recovery_action(case_id):
    case = _case_or_404(case_id)
    if case["substantiated_by_user_id"] is not None and (
        case["substantiated_by_user_id"] == v.caller_id()
    ):
        fail("ERR_SEGREGATION_OF_DUTIES")

    body = v.body()
    action = v.req_enum(body, "action", enums.RECOVERY_ACTIONS)
    v.opt_str(body, "reason", None)
    amount_cents = None
    if action == "PAY":
        amount_cents = v.req_int(body, "amount_cents", minimum=0)

    if case["recovery_status"] not in ("ASSESSED", "PARTIALLY_PAID"):
        fail("ERR_RECOVERY_NOT_ASSESSED")

    taxpayer = db.get("taxpayer_accounts", case["taxpayer_id"])

    if action == "PAY":
        outstanding = case["total_assessed_cents"] - case["recovery_paid_cents"]
        if amount_cents > outstanding:
            fail("ERR_PAYMENT_EXCEEDS_BALANCE")
        case["recovery_paid_cents"] += amount_cents
        case["recovery_status"] = (
            "PAID" if case["recovery_paid_cents"] == case["total_assessed_cents"]
            else "PARTIALLY_PAID"
        )
        db.touch(case)
        services.add_recovery_collected(taxpayer, amount_cents)
        db.touch(taxpayer)
        return env.ok(db.public(case))

    collected = case["recovery_paid_cents"]
    case["recovery_status"] = "ABATED"
    case["recovery_paid_cents"] = 0
    db.touch(case)
    if collected:
        services.add_recovery_collected(taxpayer, -collected)
        db.touch(taxpayer)
    return env.ok(db.public(case))
