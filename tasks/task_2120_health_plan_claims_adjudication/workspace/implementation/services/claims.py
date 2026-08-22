"""Claim intake: persistence, coverage matching and duplicate screening (PRD 3.4)."""

from store import db
from services.lookup import lines_of
from services.pipeline import apply_coverage_match

DUP_BILLED_TOLERANCE_CENTS = 500

TERMINAL_FOR_DUPLICATE_POOL = ("VOIDED", "ADJUSTED", "DUPLICATE_REJECTED")


def create_claim(claim_number, member_id, provider_id, line_payloads,
                 statement_from_date, statement_to_date, other_payer_paid_cents,
                 claim_type="ORIGINAL", original_claim_id=None):
    """Persist the claim and one ClaimLine per submitted element."""
    service_dates = [line["service_date"] for line in line_payloads]
    total_billed = sum(line["billed_amount_cents"] for line in line_payloads)
    claim = db.insert(
        "claims",
        {
            "claim_number": claim_number,
            "member_id": member_id,
            "provider_id": provider_id,
            "coverage_id": None,
            "original_claim_id": original_claim_id,
            "duplicate_of_claim_id": None,
            "claim_type": claim_type,
            "statement_from_date": statement_from_date or min(service_dates),
            "statement_to_date": statement_to_date or max(service_dates),
            "received_at": db.clock_iso(),
            "other_payer_paid_cents": other_payer_paid_cents,
            "cob_role": "PRIMARY",
            "pricing_variant": "UNPRICED",
            "total_billed_cents": total_billed,
            "total_allowed_cents": 0,
            "total_deductible_applied_cents": 0,
            "total_member_liability_cents": 0,
            "total_plan_paid_cents": 0,
            "pend_reason_code": None,
            "deny_reason_code": None,
            "adjudication_pass": 0,
            "last_adjudicated_by_user_id": None,
            "status": "RECEIVED",
            "payment_status": "NOT_REMITTED",
        },
    )
    for payload in line_payloads:
        db.insert(
            "claim_lines",
            {
                "claim_id": claim["id"],
                "line_number": payload["line_number"],
                "procedure_code": payload["procedure_code"],
                "modifier_code": payload.get("modifier_code"),
                "units": payload["units"],
                "billed_amount_cents": payload["billed_amount_cents"],
                "service_date": payload["service_date"],
                "allowed_amount_cents": 0,
                "deductible_applied_cents": 0,
                "copay_cents": 0,
                "coinsurance_cents": 0,
                "member_liability_cents": 0,
                "plan_paid_cents": 0,
                "authorization_id": None,
                "bundled_into_line_number": None,
                "edit_reason_code": None,
                "line_status": "PENDING",
            },
        )
    apply_coverage_match(claim, lines_of(claim))
    return claim


def _lines_match(prior_line, new_line):
    return (
        prior_line["procedure_code"] == new_line["procedure_code"]
        and (prior_line["modifier_code"] or "") == (new_line["modifier_code"] or "")
        and prior_line["service_date"] == new_line["service_date"]
        and prior_line["units"] == new_line["units"]
        and abs(prior_line["billed_amount_cents"] - new_line["billed_amount_cents"])
        <= DUP_BILLED_TOLERANCE_CENTS
    )


def detect_duplicate(claim):
    """The earliest matching prior claim by received_at ASC, created_at ASC."""
    if claim["claim_type"] != "ORIGINAL":
        return None
    new_lines = lines_of(claim)
    priors = [
        c
        for c in db.values("claims")
        if c["id"] != claim["id"]
        and c["member_id"] == claim["member_id"]
        and c["provider_id"] == claim["provider_id"]
        and c["claim_type"] == "ORIGINAL"
        and c["status"] not in TERMINAL_FOR_DUPLICATE_POOL
    ]
    matched = []
    for prior in priors:
        prior_lines = lines_of(prior)
        if any(
            _lines_match(prior_line, new_line)
            for prior_line in prior_lines
            for new_line in new_lines
        ):
            matched.append(prior)
    if not matched:
        return None
    matched.sort(key=lambda c: (c["received_at"], c["created_at"], c["_seq"]))
    return matched[0]
