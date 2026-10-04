"""Payer claims: submission, adjudication, denial, appeal and void."""

import db
from errors import ApiError
from registry import route
from routes._shared import filtered, paginate, serial
from services import claims as claim_service
from services import helpers
from services.helpers import as_int, as_str, check_occ
from utils import fmt_ts, utc_now_dt

READ_ROLES = [
    "NetworkAdmin",
    "PracticeAdmin",
    "RevenueCycleManager",
    "PayerAdjudicator",
    "NetworkAnalyst",
    "PlatformAdmin",
]

DENIAL_REASON_CODES = (
    "MEDICAL_NECESSITY",
    "NOT_COVERED",
    "AUTHORIZATION_MISSING",
    "CODING_ERROR",
    "DUPLICATE_CLAIM",
    "BENEFIT_EXHAUSTED",
)


@route("GET", "/networks/payer-claims", roles=READ_ROLES)
def list_claims(ctx):
    rows = filtered(
        db.all_records("claims"),
        ctx,
        {
            "practice_id": "practice_id",
            "treatment_id": "treatment_id",
            "status": "status",
        },
    )
    return paginate(ctx, rows)


@route("GET", "/networks/payer-claims/{claimId}", roles=READ_ROLES)
def get_claim(ctx):
    return serial(helpers.claim_or_404(ctx.path_id("claimId")))


@route("POST", "/networks/payer-claims/{claimId}/submit", roles=["RevenueCycleManager"], write=True)
def submit_claim(ctx):
    claim = helpers.claim_or_404(ctx.path_id("claimId"))
    treatment = helpers.treatment_or_404(claim["treatment_id"])
    practice = helpers.practice_or_404(claim["practice_id"])

    # Priority 3.5 — stale practice view rejected before any business logic.
    check_occ(ctx.body, practice)

    if treatment["status"] != "ADMINISTERED":
        raise ApiError("ERR_TREATMENT_NOT_ADMINISTERED")
    if claim["status"] != "DRAFT":
        raise ApiError("ERR_CLAIM_NOT_DRAFT")
    if practice["affiliation_status"] != "AFFILIATED":
        raise ApiError("ERR_PRACTICE_NOT_AFFILIATED")

    if not claim.get("payer_name") or claim.get("payer_name") != treatment.get("payer_name"):
        raise ApiError("ERR_INVALID_REQUEST", "payer_name does not match the treatment")

    disclosure = ctx.body.get("post_settlement_disclosure")
    if disclosure is not None:
        if not isinstance(disclosure, bool):
            raise ApiError("ERR_INVALID_REQUEST", "post_settlement_disclosure must be a boolean")
        claim["post_settlement_disclosure"] = disclosure

    tier = claim_service.resolve_write_off_tier(practice, ctx.body.get("write_off_tier"))
    claim["write_off_tier"] = tier

    assembly = claim_service.compute_billed_amount(treatment, claim)
    billed = assembly["billed_amount_cents"]
    if billed <= 0:
        raise ApiError("ERR_CLAIM_NOTHING_TO_BILL")

    claim["policy_admin_fee_cents"] = assembly["policy_admin_fee_cents"]
    claim["billed_amount_cents"] = billed
    claim["billed_admin_fee_cents"] = assembly["line_3"]
    claim["written_off_admin_fee_cents"] = (
        assembly["policy_admin_fee_cents"] if claim.get("post_settlement_disclosure") else 0
    )
    claim["write_off_cents"] = claim_service.write_off_cents(billed, tier)
    claim["status"] = "SUBMITTED"
    treatment["status"] = "BILLED"
    helpers.recompute_tier(practice)
    db.touch(practice)
    db.touch(treatment)
    db.touch(claim)
    return serial(claim)


@route("POST", "/networks/payer-claims/{claimId}/adjudicate", roles=["PayerAdjudicator"], write=True)
def adjudicate_claim(ctx):
    claim = helpers.claim_or_404(ctx.path_id("claimId"))
    practice = helpers.practice_or_404(claim["practice_id"])
    if claim["status"] not in ("SUBMITTED", "APPEALED"):
        raise ApiError("ERR_CLAIM_NOT_SUBMITTED")

    paid = as_int(ctx.body, "paid_amount_cents", required_=True)
    if paid <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "paid_amount_cents must be greater than zero")
    billed = int(claim.get("billed_amount_cents") or 0)
    if paid > billed:
        raise ApiError("ERR_PAYER_OVERPAYMENT")

    if claim.get("post_settlement_disclosure"):
        # The fee line is reconstructed after settlement rather than billed up
        # front, so the remittance must equal the drug basis exactly.
        treatment = helpers.treatment_or_404(claim["treatment_id"])
        if paid != int(treatment.get("acquisition_cost_basis_cents") or 0):
            raise ApiError("ERR_INVALID_REQUEST", "remittance must equal the drug basis")
    else:
        drug_basis = int(
            helpers.treatment_or_404(claim["treatment_id"]).get("acquisition_cost_basis_cents") or 0
        )
        if paid != drug_basis + int(claim.get("policy_admin_fee_cents") or 0):
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "a routine whole claim is remitted at the drug basis plus the policy admin fee",
            )

    headroom = int(claim.get("write_off_cents") or claim_service.write_off_cents(billed, claim.get("write_off_tier") or "W1"))
    allowed = min(billed, paid + headroom)
    claim["status"] = "ADJUDICATED_PAID"
    claim["paid_amount_cents"] = paid
    claim["allowed_amount_cents"] = allowed
    claim["write_off_cents"] = headroom
    claim["_adjudicated_at"] = fmt_ts(utc_now_dt())
    helpers.denial_ratio_exact(practice)
    db.touch(practice)
    db.touch(claim)
    return serial(claim)


@route("POST", "/networks/payer-claims/{claimId}/deny", roles=["PayerAdjudicator"], write=True)
def deny_claim(ctx):
    claim = helpers.claim_or_404(ctx.path_id("claimId"))
    practice = helpers.practice_or_404(claim["practice_id"])
    if claim["status"] not in ("SUBMITTED", "APPEALED"):
        raise ApiError("ERR_CLAIM_NOT_SUBMITTED")
    reason = as_str(ctx.body, "denial_reason_code")
    if reason not in DENIAL_REASON_CODES:
        raise ApiError("ERR_INVALID_REQUEST", "denial_reason_code outside its enum")

    claim["status"] = "DENIED"
    claim["denial_reason_code"] = reason
    billed = int(claim.get("billed_amount_cents") or 0)
    practice["unsettled_balance_cents"] = int(practice.get("unsettled_balance_cents") or 0) + billed

    threshold = _threshold(practice)
    ratio = helpers.denial_ratio_exact(practice)
    if ratio > threshold:
        for agreement in helpers.agreements_of(practice["id"]):
            if agreement["status"] == "ACTIVE":
                agreement["status"] = "SUSPENDED"
                agreement["status_changed_by"] = "DENIAL_RATIO_BREACH"
                db.touch(agreement)
        helpers.recompute_tier(practice)
        network = db.get("networks", practice["network_id"])
        if network is not None:
            network["is_commercial_terms_frozen"] = True
            db.touch(network)

    db.touch(practice)
    db.touch(claim)
    return serial(claim)


def _threshold(practice):
    from decimal import Decimal

    from utils import num

    return num(practice.get("denial_ratio_threshold_pct")) or Decimal("0.20")


@route("POST", "/networks/payer-claims/{claimId}/appeal", roles=["RevenueCycleManager"], write=True)
def appeal_claim(ctx):
    claim = helpers.claim_or_404(ctx.path_id("claimId"))
    practice = helpers.practice_or_404(claim["practice_id"])
    if claim["status"] != "DENIED":
        raise ApiError("ERR_CLAIM_NOT_DENIED")
    if int(claim.get("appeal_round") or 0) >= 2:
        raise ApiError("ERR_APPEAL_LIMIT_REACHED")
    claim["status"] = "APPEALED"
    claim["appeal_round"] = int(claim.get("appeal_round") or 0) + 1
    billed = int(claim.get("billed_amount_cents") or 0)
    practice["unsettled_balance_cents"] = int(practice.get("unsettled_balance_cents") or 0) - billed
    helpers.denial_ratio_exact(practice)
    db.touch(practice)
    db.touch(claim)
    return serial(claim)


@route("POST", "/networks/payer-claims/{claimId}/void", roles=["NetworkAdmin"], write=True)
def void_claim(ctx):
    claim = helpers.claim_or_404(ctx.path_id("claimId"))
    practice = helpers.practice_or_404(claim["practice_id"])
    if claim["status"] == "DRAFT":
        claim["status"] = "VOIDED"
    elif claim["status"] == "DENIED" and int(claim.get("appeal_round") or 0) == 0:
        claim["status"] = "VOIDED"
        billed = int(claim.get("billed_amount_cents") or 0)
        practice["unsettled_balance_cents"] = (
            int(practice.get("unsettled_balance_cents") or 0) - billed
        )
    else:
        raise ApiError("ERR_CLAIM_NOT_VOIDABLE")
    helpers.denial_ratio_exact(practice)
    db.touch(practice)
    db.touch(claim)
    return serial(claim)