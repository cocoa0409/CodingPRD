"""The two timeliness variants of the damage-claim assessment."""

from test_helpers import (
    ASSESSOR,
    api_client,
    assert_cents,
    assert_instant_equals,
    damage_claim_payload,
    get_success_data,
    make_subscriber_headers,
    read_appointment,
    read_claim,
    set_clock,
    setup_filed_damage_claim,
    validate_success,
)

ON_TIME_FILING = "2026-10-06T00:00:00Z"
LATE_FILING = "2026-10-20T00:00:00Z"
RESTORATION_DUE_BY = "2026-10-12T11:00:00Z"


def _two_lawn_claims_against_one_visit():
    """One completed bury visit, one claim filed on time and one filed late."""
    base = setup_filed_damage_claim(
        filing_clock=ON_TIME_FILING,
        damage_type="LAWN",
        claimed_amount_cents=150000,
        claim_overrides={"description": "Sod torn along the trench line"},
    )
    account = base["accounts"][0]
    set_clock(LATE_FILING)
    late = get_success_data(
        api_client.create_damage_claim(
            damage_claim_payload(
                base["appointment"]["id"],
                base["addresses"][0]["id"],
                account["id"],
                damage_type="LAWN",
                claimed_amount_cents=150000,
                description="Second sod strip discovered later",
            ),
            make_subscriber_headers(account["id"]),
        )
    )
    base["late_claim"] = late
    return base


def test_on_time_lawn_claim_is_capped_and_priced_on_the_standard_schedule():
    """A 150,000-cent lawn claim filed before the due date caps to 120,000 and stays there.

    PRD 3.9: "The factor is 1.00 when the claim's `filed_at` is at or before the
    appointment's `restoration_due_by`, and in that case `assessment_variant` is recorded
    as `STANDARD_SCHEDULE`"

    Design: Difficulty/dual_variant_calc/damage_claim_late_filing_variant_reduces_assessment
    """
    base = _two_lawn_claims_against_one_visit()
    assert_instant_equals(
        read_appointment(base["appointment"]["id"])["restoration_due_by"],
        RESTORATION_DUE_BY,
        "restoration_due_by",
    )

    validate_success(api_client.assess_damage_claim(base["claim"]["id"], ASSESSOR))

    claim = read_claim(base["claim"]["id"])
    assert claim["assessment_variant"] == "STANDARD_SCHEDULE", claim["assessment_variant"]
    assert_cents(claim["assessed_amount_cents"], 120000, "assessed_amount_cents")
    assert claim["status"] == "UNDER_ASSESSMENT", claim["status"]


def test_late_lawn_claim_scales_the_capped_base_by_the_late_filing_factor():
    """An identical claim filed after the due date assesses at 72,000 under the 0.60 factor.

    PRD 3.9: "the factor is the campaign's `late_filing_factor`, which defaults to 0.60,
    when `filed_at` falls after `restoration_due_by`, and in that case the variant is
    `LATE_FILING_SCHEDULE`"

    Design: Difficulty/dual_variant_calc/damage_claim_late_filing_variant_reduces_assessment
    """
    base = _two_lawn_claims_against_one_visit()

    validate_success(api_client.assess_damage_claim(base["late_claim"]["id"], ASSESSOR))

    claim = read_claim(base["late_claim"]["id"])
    assert claim["assessment_variant"] == "LATE_FILING_SCHEDULE", (
        claim["assessment_variant"]
    )
    assert_cents(claim["assessed_amount_cents"], 72000, "assessed_amount_cents")
    assert claim["status"] == "UNDER_ASSESSMENT", claim["status"]


def test_variant_divergence_is_driven_by_filing_date_alone():
    """Two claims identical but for filing date diverge by exactly 48,000 cents.

    PRD 3.9: "Note that the variant is selected purely by *when* the claim was filed, not
    by what was damaged."

    Design: Difficulty/dual_variant_calc/damage_claim_late_filing_variant_reduces_assessment
    """
    base = _two_lawn_claims_against_one_visit()

    validate_success(api_client.assess_damage_claim(base["claim"]["id"], ASSESSOR))
    validate_success(api_client.assess_damage_claim(base["late_claim"]["id"], ASSESSOR))

    on_time = read_claim(base["claim"]["id"])
    late = read_claim(base["late_claim"]["id"])
    assert on_time["damage_type"] == late["damage_type"] == "LAWN"
    assert on_time["claimed_amount_cents"] == late["claimed_amount_cents"] == 150000
    assert_cents(
        on_time["assessed_amount_cents"] - late["assessed_amount_cents"],
        48000,
        "assessment gap",
    )
    for claim in (on_time, late):
        assert claim["assessed_by_user_id"] == ASSESSOR["X-User-ID"], (
            claim["assessed_by_user_id"]
        )
        assert claim["decided_by_user_id"] is None, claim["decided_by_user_id"]
        assert claim["paid_at"] is None, claim["paid_at"]
