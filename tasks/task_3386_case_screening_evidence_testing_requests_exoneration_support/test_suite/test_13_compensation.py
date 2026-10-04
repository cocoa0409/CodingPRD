"""Compensation claims: the jurisdictional statute gate, exact-cent payment,
and the denial feed into COMPENSATION_REFORM pattern counts."""
from test_helpers import (
    ANCHOR_CONVICTION_DATE,
    ANCHOR_EXONERATION_CLOCK,
    ApiErrorId,
    TEST_USERS,
    advance_compensation_claim,
    claim_advance_payload,
    create_compensation_claim,
    create_jurisdiction,
    file_claim,
    list_rows,
    record_claim_decision,
    record_claim_payment,
    setup_exonerated_case,
    setup_policy_initiative,
    validate_created,
    validate_error,
    validate_ok,
)

ATTORNEY = TEST_USERS["staff_attorney_headers"]
POLICY = TEST_USERS["policy_director_headers"]


def test_compensation_claim_blocked_without_statute(api):
    """PRD section 3.8: "A `StaffAttorney` opens a `CompensationClaim` against
    an `EXONERATED` case — any other status is `ERR_CASE_NOT_EXONERATED` — in a
    jurisdiction whose `compensation_statute_exists` flag is true, else
    `ERR_NO_COMPENSATION_STATUTE` (HTTP 422)."

    Design: Corner/validations/compensation_claim_blocked_without_statute
    """
    ctx = setup_exonerated_case(
        jurisdiction_overrides={
            "state_code": "AK",
            "name": "Alaska",
            "compensation_statute_exists": False,
        }
    )
    assert ctx["case"]["status"] == "EXONERATED"

    resp = api.create_compensation_claim(
        {"case_id": ctx["case"]["id"], "years_incarcerated_claimed": 12},
        ATTORNEY,
    )
    validate_error(resp, ApiErrorId.ERR_NO_COMPENSATION_STATUTE)


def test_compensation_claim_requires_statute_and_payment_exactness(api):
    """PRD section 3.8: "The provisional estimate is deliberately simple: a
    flat 5,000,000 cents per claimed year, capped at the jurisdiction's
    `compensation_cap_cents` when that cap is not null — with no exculpatory
    enhancement and no fee reimbursement."
    PRD section 3.8: "An `APPROVED` claim is paid by recording a
    `paid_amount_cents` that must equal `final_award_cents` exactly — any
    other figure is `ERR_PAYMENT_AMOUNT_MISMATCH` (HTTP 422) — moving the
    claim to its terminal `PAID` status."

    Design: Corner/validations/compensation_claim_requires_statute_and_payment_exactness
    """
    # Statute exists, cap null (uncapped), enhancement 0; the case carries no
    # exculpatory flag, so the tiered base is the whole award.
    ctx = setup_exonerated_case(
        jurisdiction_overrides={"state_code": "OR", "name": "Oregon"},
        intake_overrides={
            "conviction_date": ANCHOR_CONVICTION_DATE,
            "years_served": 10,
        },
        exoneration_clock=ANCHOR_EXONERATION_CLOCK,
    )

    claim = create_compensation_claim(ctx["case"]["id"])
    assert claim["status"] == "DRAFT"
    assert claim["provisional_estimate_cents"] == 50_000_000, (
        "10 claimed years x 5,000,000 flat, no cap"
    )
    assert claim["final_award_cents"] is None

    file_claim(claim["id"])
    approved = record_claim_decision(claim["id"], "APPROVED")
    # 10 verified years tiered: 5 x 5,000,000 + 5 x 7,500,000; no enhancement,
    # no cap, no fees.
    assert approved["status"] == "APPROVED"
    assert approved["final_award_cents"] == 62_500_000

    resp = api.advance_compensation_claim(
        claim["id"],
        claim_advance_payload("RECORD_PAYMENT", paid_amount_cents=62_500_001),
        ATTORNEY,
    )
    validate_error(resp, ApiErrorId.ERR_PAYMENT_AMOUNT_MISMATCH)

    paid = record_claim_payment(claim["id"], 62_500_000)
    assert paid["status"] == "PAID"
    assert paid["paid_amount_cents"] == 62_500_000


def test_compensation_denial_feeds_policy_pattern_count(api):
    """PRD section 3.8: "a denial re-derives the `pattern_case_count` of every
    `COMPENSATION_REFORM` initiative in the case's jurisdiction."
    PRD section 3.9: "for `COMPENSATION_REFORM`, a case with at least one
    compensation claim in `DENIED` or `APPEALED`".

    Design: Corner/calculations/compensation_denial_feeds_policy_pattern_count
    """
    jurisdiction = create_jurisdiction(
        state_code="NV", name="Nevada", compensation_cap_cents=100_000_000
    )
    setup_policy_initiative(
        jurisdiction["id"], topic="COMPENSATION_REFORM", title="Raise statutory caps"
    )
    ctx = setup_exonerated_case(jurisdiction_id=jurisdiction["id"])
    claim = create_compensation_claim(
        ctx["case"]["id"], years_incarcerated_claimed=11
    )
    file_claim(claim["id"])

    def pattern_count():
        data, _ = list_rows(
            api.list_jurisdiction_policy_initiatives(jurisdiction["id"], POLICY)
        )
        assert len(data) == 1
        return data[0]["pattern_case_count"]

    assert pattern_count() == 0, "a merely FILED claim is not in the DENIED/APPEALED input set"
    denied = record_claim_decision(claim["id"], "DENIED")
    assert denied["status"] == "DENIED"
    assert pattern_count() == 1
