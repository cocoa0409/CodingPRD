"""Grants, portability, compliance actions, retroactive claims and the annual
assessment roll (PRD §3.5, §3.6, §3.7).
"""

from flask import Blueprint

import calc
import db
import enums
import envelope as env
import services
import validate as v
from errors import fail
from validate import endpoint

bp = Blueprint("grants", __name__)


def _grant_or_404(grant_id):
    grant = db.get("exemption_grants", grant_id)
    if grant is None:
        fail("ERR_GRANT_NOT_FOUND")
    return grant


# --------------------------------------------------------------------------
# Reads
# --------------------------------------------------------------------------
@bp.get("/exemption-grants/<grant_id>")
@endpoint(["ExemptionsReviewer", "FraudInvestigator", "AssessorAnalyst", "Taxpayer"])
def read_grant(grant_id):
    grant = _grant_or_404(grant_id)
    if v.is_taxpayer() and grant["taxpayer_id"] != v.caller_id():
        fail("ERR_NOT_RESOURCE_OWNER")
    return env.ok(db.public(grant))


@bp.get("/exemption-grants")
@endpoint(["ExemptionsReviewer", "FraudInvestigator", "AssessorAnalyst", "Taxpayer"])
def list_grants():
    limit, offset = v.pagination()
    parcel_id = v.q_str("parcel_id")
    taxpayer_id = v.q_str("taxpayer_id")
    application_id = v.q_str("application_id")
    program_id = v.q_str("program_id")
    ported_from_grant_id = v.q_str("ported_from_grant_id")
    benefit_status = v.q_enum("benefit_status", enums.BENEFIT_STATUSES)

    if v.is_taxpayer():
        if taxpayer_id is not None and taxpayer_id != v.caller_id():
            fail("ERR_NOT_RESOURCE_OWNER")
        taxpayer_id = v.caller_id()

    items = []
    for grant in db.rows("exemption_grants"):
        if parcel_id is not None and grant["parcel_id"] != parcel_id:
            continue
        if taxpayer_id is not None and grant["taxpayer_id"] != taxpayer_id:
            continue
        if application_id is not None and grant["application_id"] != application_id:
            continue
        if program_id is not None and grant["program_id"] != program_id:
            continue
        if ported_from_grant_id is not None and grant["ported_from_grant_id"] != ported_from_grant_id:
            continue
        if benefit_status is not None and grant["benefit_status"] != benefit_status:
            continue
        items.append(db.public(grant))
    return env.listing(items, limit, offset)


# --------------------------------------------------------------------------
# Portability (PRD §3.6)
# --------------------------------------------------------------------------
@bp.post("/exemption-grants/<grant_id>/port")
@endpoint(["ExemptionsReviewer"])
def port_grant(grant_id):
    grant = _grant_or_404(grant_id)
    body = v.body()
    destination_parcel_id = v.req_str(body, "destination_parcel_id")
    transfer_value_cents = v.req_int(body, "transfer_value_cents", minimum=0)
    expected_grant_version = v.req_int(body, "expected_grant_version")

    destination = db.get("parcels", destination_parcel_id)
    if destination is None:
        fail("ERR_PARCEL_NOT_FOUND")

    if grant["version"] != expected_grant_version:
        fail("ERR_STALE_GRANT_VERSION")

    if grant["benefit_status"] in enums.TERMINAL_BENEFIT_STATUSES:
        fail("ERR_GRANT_ALREADY_TERMINAL")
    if grant["benefit_status"] != "ACTIVE":
        fail("ERR_GRANT_NOT_ACTIVE")

    if services.has_open_fraud_case(grant["taxpayer_id"]):
        fail("ERR_FRAUD_HOLD_ACTIVE")

    transfer_date = db.now_iso()[:10]
    destination_record = services.verified_ownership(
        destination["id"], grant["taxpayer_id"], "PRIMARY_RESIDENCE", transfer_date
    )
    if destination_record is None:
        fail("ERR_DESTINATION_NOT_OWNED")

    destination_assessed = calc.pre_event_assessed(destination)
    allocation = calc.portable_allocation(
        transfer_value_cents, grant["portable_balance_cents"], destination_assessed
    )
    if allocation < 1:
        fail("ERR_PORTABLE_BALANCE_EXHAUSTED")

    program = db.get("relief_programs", grant["program_id"])
    taxpayer = db.get("taxpayer_accounts", grant["taxpayer_id"])
    benefit_amount_cents = calc.benefit_amount(
        destination_assessed,
        program,
        grant["relief_multiplier_bps"],
        taxpayer["disability_rating_pct_bps"],
        destination_record["ownership_pct_bps"],
    )

    child = db.insert("exemption_grants", {
        "application_id": grant["application_id"],
        "parcel_id": destination["id"],
        "taxpayer_id": grant["taxpayer_id"],
        "program_id": grant["program_id"],
        "ported_from_grant_id": grant["id"],
        "exemption_type": grant["exemption_type"],
        "benefit_status": "ACTIVE",
        "suspension_reason": None,
        "effective_tax_year": grant["effective_tax_year"],
        "first_eligible_tax_year": grant["first_eligible_tax_year"],
        "ownership_pct_bps_snapshot": destination_record["ownership_pct_bps"],
        "relief_multiplier_bps": grant["relief_multiplier_bps"],
        "benefit_amount_cents": benefit_amount_cents,
        "applied_exempt_value_cents": 0,
        "frozen_value_cents": allocation,
        "portable_balance_cents": 0,
        "_supporting_ownership_record_id": destination_record["id"],
    })

    grant["portable_balance_cents"] = grant["portable_balance_cents"] - allocation
    if grant["portable_balance_cents"] == 0:
        grant["benefit_status"] = "TRANSFERRED"
        grant["suspension_reason"] = None
    db.touch(grant)

    source_parcel = db.get("parcels", grant["parcel_id"])
    if source_parcel is not None:
        calc.decompose(source_parcel)
    calc.decompose(destination)

    return env.created(db.public(child))


# --------------------------------------------------------------------------
# Compliance actions (PRD §3.5)
# --------------------------------------------------------------------------
@bp.post("/exemption-grants/<grant_id>/compliance-actions")
@endpoint(["ExemptionsReviewer"])
def compliance_action(grant_id):
    grant = _grant_or_404(grant_id)
    raw = v.body()

    if raw.get("action") == "REVOKE":
        for case in db.find("fraud_cases", grant_id=grant["id"]):
            if case["opened_by_user_id"] == v.caller_id():
                fail("ERR_SEGREGATION_OF_DUTIES")

    action = v.req_enum(raw, "action", enums.COMPLIANCE_ACTIONS)
    v.opt_str(raw, "reason", None)

    if grant["benefit_status"] in enums.TERMINAL_BENEFIT_STATUSES:
        fail("ERR_GRANT_ALREADY_TERMINAL")
    if action == "REINSTATE" and grant["benefit_status"] != "SUSPENDED":
        fail("ERR_GRANT_NOT_SUSPENDED")

    if services.has_open_fraud_case(grant["taxpayer_id"]):
        fail("ERR_FRAUD_HOLD_ACTIVE")

    if action == "REINSTATE":
        if grant["suspension_reason"] == "RECERTIFICATION_LAPSE":
            if not services.has_certified_from_year(
                grant["taxpayer_id"], grant["effective_tax_year"]
            ):
                fail("ERR_INCOME_CERTIFICATION_REQUIRED")
        services.set_grant_status(grant, "ACTIVE", None)
        return env.ok(db.public(grant))

    services.set_grant_status(grant, "REVOKED", None)
    services.mail_notice(
        grant["taxpayer_id"],
        "EXEMPTION_GRANT",
        grant["id"],
        "REVOCATION",
        "Exemption grant revoked.",
        appealable=True,
    )
    return env.ok(db.public(grant))


# --------------------------------------------------------------------------
# RetroactiveClaim (PRD §3.7)
# --------------------------------------------------------------------------
def _claim_or_404(claim_id):
    claim = db.get("retroactive_claims", claim_id)
    if claim is None:
        fail("ERR_CLAIM_NOT_FOUND")
    return claim


@bp.post("/retroactive-claims")
@endpoint(["Taxpayer", "IntakeClerk"])
def file_retroactive_claim():
    body = v.body()
    grant_id = v.req_str(body, "grant_id")
    grant = db.get("exemption_grants", grant_id)
    if grant is None:
        fail("ERR_GRANT_NOT_FOUND")
    if v.is_taxpayer() and grant["taxpayer_id"] != v.caller_id():
        fail("ERR_NOT_RESOURCE_OWNER")

    filing_tax_year = v.req_int(body, "filing_tax_year", minimum=2015, maximum=2100)
    requested_start_tax_year = v.req_int(
        body, "requested_start_tax_year", minimum=2015, maximum=2100
    )
    if requested_start_tax_year > filing_tax_year:
        fail("ERR_INVALID_REQUEST", "requested_start_tax_year must not exceed filing_tax_year.")

    program = db.get("relief_programs", grant["program_id"])
    lookback_floor = filing_tax_year - program["statutory_lookback_years"]
    last_eligible = filing_tax_year - 1
    first_eligible = max(
        lookback_floor, grant["first_eligible_tax_year"], requested_start_tax_year
    )
    if first_eligible > last_eligible:
        fail("ERR_NO_ELIGIBLE_CLAIM_YEARS")
    if requested_start_tax_year < lookback_floor:
        fail("ERR_STATUTORY_LOOKBACK_EXCEEDED")

    for other in db.rows("retroactive_claims"):
        if other["grant_id"] != grant["id"]:
            continue
        if other["status"] not in ("PENDING", "APPROVED"):
            continue
        if (
            first_eligible <= other["last_eligible_tax_year"]
            and other["first_eligible_tax_year"] <= last_eligible
        ):
            fail("ERR_CLAIM_YEARS_OVERLAP")

    years = list(range(first_eligible, last_eligible + 1))
    claim = db.insert("retroactive_claims", {
        "grant_id": grant["id"],
        "filing_tax_year": filing_tax_year,
        "requested_start_tax_year": requested_start_tax_year,
        "first_eligible_tax_year": first_eligible,
        "last_eligible_tax_year": last_eligible,
        "eligible_year_count": len(years),
        "gross_refund_cents": calc.gross_refund(years, grant["benefit_amount_cents"]),
        "offset_applied_cents": 0,
        "net_refund_cents": 0,
        "refund_interest_cents": 0,
        "total_payable_cents": 0,
        "status": "PENDING",
    })
    return env.created(db.public(claim))


@bp.get("/retroactive-claims/<claim_id>")
@endpoint(["ExemptionsReviewer", "IntakeClerk", "Taxpayer"])
def read_retroactive_claim(claim_id):
    claim = _claim_or_404(claim_id)
    grant = db.get("exemption_grants", claim["grant_id"])
    if v.is_taxpayer() and (grant is None or grant["taxpayer_id"] != v.caller_id()):
        fail("ERR_NOT_RESOURCE_OWNER")
    return env.ok(db.public(claim))


@bp.get("/exemption-grants/<grant_id>/retroactive-claims")
@endpoint(["ExemptionsReviewer", "IntakeClerk", "Taxpayer"])
def list_retroactive_claims(grant_id):
    limit, offset = v.pagination()
    status = v.q_enum("status", enums.CLAIM_STATUSES)
    grant = _grant_or_404(grant_id)
    if v.is_taxpayer() and grant["taxpayer_id"] != v.caller_id():
        fail("ERR_NOT_RESOURCE_OWNER")
    items = []
    for claim in db.rows("retroactive_claims"):
        if claim["grant_id"] != grant["id"]:
            continue
        if status is not None and claim["status"] != status:
            continue
        items.append(db.public(claim))
    return env.listing(items, limit, offset)


@bp.post("/retroactive-claims/<claim_id>/decide")
@endpoint(["ExemptionsReviewer"])
def decide_retroactive_claim(claim_id):
    claim = _claim_or_404(claim_id)
    grant = db.get("exemption_grants", claim["grant_id"])
    application = db.get("exemption_applications", grant["application_id"]) if grant else None
    if application is not None and application["determined_by_user_id"] == v.caller_id():
        fail("ERR_SEGREGATION_OF_DUTIES")

    body = v.body()
    action = v.req_enum(body, "action", enums.CLAIM_ACTIONS)
    v.opt_str(body, "note", None)

    if claim["status"] != "PENDING":
        fail("ERR_CLAIM_NOT_PENDING")

    if action == "DENY":
        claim["status"] = "DENIED"
        db.touch(claim)
        services.mail_notice(
            grant["taxpayer_id"],
            "RETROACTIVE_CLAIM",
            claim["id"],
            "REFUND_DETERMINATION",
            "Retroactive refund claim denied.",
            appealable=True,
        )
        return env.ok(db.public(claim))

    if grant["benefit_status"] in enums.TERMINAL_BENEFIT_STATUSES:
        fail("ERR_GRANT_ALREADY_TERMINAL")
    if services.has_open_fraud_case(grant["taxpayer_id"]):
        fail("ERR_FRAUD_HOLD_ACTIVE")

    taxpayer = db.get("taxpayer_accounts", grant["taxpayer_id"])
    years = list(range(claim["first_eligible_tax_year"], claim["last_eligible_tax_year"] + 1))
    outcome = calc.net_final_refund(
        years,
        grant["benefit_amount_cents"],
        services.outstanding_recovery(grant["taxpayer_id"]),
        claim["filing_tax_year"],
    )
    claim.update(outcome)
    claim["status"] = "APPROVED"
    db.touch(claim)

    services.add_refund(taxpayer, claim["total_payable_cents"])
    db.touch(taxpayer)

    if claim["offset_applied_cents"] > 0:
        remaining = claim["offset_applied_cents"]
        cases = [
            c
            for c in db.find("fraud_cases", taxpayer_id=taxpayer["id"])
            if c["recovery_status"] in ("ASSESSED", "PARTIALLY_PAID")
        ]
        cases.sort(key=lambda c: (c["assessment_tax_year"], c["created_at"], c["_seq"]))
        credited = 0
        for case in cases:
            if remaining <= 0:
                break
            outstanding = case["total_assessed_cents"] - case["recovery_paid_cents"]
            applied = min(outstanding, remaining)
            if applied <= 0:
                continue
            case["recovery_paid_cents"] += applied
            case["recovery_status"] = (
                "PAID" if case["recovery_paid_cents"] == case["total_assessed_cents"]
                else "PARTIALLY_PAID"
            )
            db.touch(case)
            remaining -= applied
            credited += applied
        if credited:
            services.add_recovery_collected(taxpayer, credited)
            db.touch(taxpayer)

    services.mail_notice(
        grant["taxpayer_id"],
        "RETROACTIVE_CLAIM",
        claim["id"],
        "REFUND_DETERMINATION",
        "Retroactive refund claim approved.",
        appealable=False,
    )
    return env.ok(db.public(claim))


# --------------------------------------------------------------------------
# The annual assessment roll (PRD §3.5)
# --------------------------------------------------------------------------
@bp.post("/assessment-roll-runs")
@endpoint(["AssessorAnalyst"])
def assessment_roll_run():
    body = v.body()
    target_tax_year = v.req_int(body, "target_tax_year", minimum=2015, maximum=2100)

    already_lapsed_suspensions = [
        g
        for g in db.rows("exemption_grants")
        if g["benefit_status"] == "SUSPENDED"
        and g["suspension_reason"] == "RECERTIFICATION_LAPSE"
    ]

    parcels_rolled_count = 0
    for parcel in db.rows("parcels"):
        if parcel["tax_year"] < target_tax_year:
            parcel["tax_year"] = target_tax_year
            calc.decompose(parcel)
            parcels_rolled_count += 1

    today = db.now_iso()[:10]
    certifications_lapsed_count = 0
    lapsed_taxpayers = []
    for certification in db.rows("income_certifications"):
        if certification["status"] != "CERTIFIED":
            continue
        if not certification["recertification_due_date"] < today:
            continue
        if services.has_certified_from_year(certification["taxpayer_id"], target_tax_year):
            continue
        certification["status"] = "LAPSED"
        db.touch(certification)
        certifications_lapsed_count += 1
        if certification["taxpayer_id"] not in lapsed_taxpayers:
            lapsed_taxpayers.append(certification["taxpayer_id"])

    grants_suspended_count = 0
    for taxpayer_id in lapsed_taxpayers:
        for grant in db.rows("exemption_grants"):
            if grant["taxpayer_id"] != taxpayer_id or grant["benefit_status"] != "ACTIVE":
                continue
            program = db.get("relief_programs", grant["program_id"])
            if program is None or not program["recertification_required"]:
                continue
            services.set_grant_status(grant, "SUSPENDED", "RECERTIFICATION_LAPSE")
            grants_suspended_count += 1

    grants_lapsed_count = 0
    for grant in already_lapsed_suspensions:
        if services.has_certified_from_year(grant["taxpayer_id"], target_tax_year):
            continue
        services.set_grant_status(grant, "LAPSED", None)
        grants_lapsed_count += 1

    return env.ok({
        "target_tax_year": target_tax_year,
        "parcels_rolled_count": parcels_rolled_count,
        "certifications_lapsed_count": certifications_lapsed_count,
        "grants_suspended_count": grants_suspended_count,
        "grants_lapsed_count": grants_lapsed_count,
    })
