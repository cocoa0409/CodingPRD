"""Dual-variant calculations: capitation pricing and outside-service liability.

Depth file (queue A): each test carries the difficulty-design instance it
translates in its docstring.
"""

from test_helpers import (
    BASE_RATE_COMMERCIAL_HMO_CENTS,
    COINSURANCE_RATE,
    VENDOR_ALLOWABLE_PCT,
    api_client,
    create_and_approve_budget,
    create_care_site,
    create_department,
    create_open_region,
    create_provider,
    enroll_member,
    get_region,
    submit_claim,
    TEST_USERS,
)

_RFO = TEST_USERS["regional_finance_officer_headers"]


def test_capitation_prices_members_at_the_risk_adjusted_clamped_read(api):
    """PRD §3.1: "The rule begins from a base rate selected by the member's
    `plan_product`: forty-two thousand cents for `COMMERCIAL_HMO`, ninety-five
    thousand for `MEDICARE_ADVANTAGE`, twenty-eight thousand for
    `MEDICAID_MANAGED`, and one hundred eighteen thousand for `DUAL_ELIGIBLE`."
    PRD §3.1: "A risk component is then computed as the adjusted base
    multiplied by the member's own `risk_score`, rounded half-up. The raw rate
    is the adjusted base plus the risk component."

    Design: Difficulty/dual_variant_calc/dual_capitation_blind_average_vs_risk_adjusted_clamped
    """
    region = create_open_region(capitation_index=1.0)
    care_site = create_care_site(region["id"])
    create_department(care_site["id"])
    provider = create_provider(care_site["id"], specialty="PRIMARY_CARE")

    low_risk = enroll_member(
        region["id"], provider["id"], member_ref="M-CA-1", risk_score=0.6
    )
    high_risk = enroll_member(
        region["id"], provider["id"], member_ref="M-CA-2", risk_score=3.0
    )

    # 42000 + round_half_up(42000 * 0.6) = 67200, inside the clamp interval.
    assert low_risk["capitation_rate_cents"] == 67200, (
        f"Expected 67200 at risk 0.6, got {low_risk['capitation_rate_cents']}"
    )
    # The raw rate 42000 + round_half_up(42000 * 3.0) = 168000 lies above the
    # upper bound of the closed clamp interval — the adjusted base (42000)
    # multiplied by two and a half, rounded half-up — so it lands at that bound.
    assert high_risk["capitation_rate_cents"] == 105000, (
        f"Expected the 105000 upper bound at risk 3.0, got {high_risk['capitation_rate_cents']}"
    )


def test_region_premium_revenue_sums_the_risk_adjusted_variant(api):
    """PRD §3.1: "The rule has a second, explicitly non-operational variant used
    when a region-level revenue estimate must be produced before member-level
    risk scores are loaded: that variant uses the unweighted base rate for every
    member, ignoring both the member's risk score and the region's
    `capitation_index`."
    PRD §3.1: "Creating a member recomputes the parent region's
    `premium_revenue_cents`, which sums `capitation_rate_cents` across exactly
    those members whose `region_id` matches and whose `status` is `ACTIVE` or
    `TRANSFER_PENDING`".

    Design: Difficulty/dual_variant_calc/dual_capitation_blind_average_vs_risk_adjusted_clamped
    """
    region = create_open_region(capitation_index=1.0)
    care_site = create_care_site(region["id"])
    create_department(care_site["id"])
    provider = create_provider(care_site["id"], specialty="PRIMARY_CARE")

    enroll_member(region["id"], provider["id"], member_ref="M-CA-1", risk_score=0.6)
    enroll_member(region["id"], provider["id"], member_ref="M-CA-2", risk_score=3.0)

    region_after = get_region(region["id"])
    # The settled figure sums the risk-adjusted, clamped read: the low-risk
    # member's 67200 stands as computed, while the high-risk member's raw
    # 168000 is clamped to the 105000 upper bound.
    assert region_after["premium_revenue_cents"] == 67200 + 105000, (
        f"Expected 172200, got {region_after['premium_revenue_cents']}"
    )
    assert region_after["premium_revenue_cents"] != 2 * BASE_RATE_COMMERCIAL_HMO_CENTS
    assert region_after["member_count"] == 2


def test_claim_provisional_liability_ignores_the_deductible(api):
    """PRD §3.6: "The provisional amount is the `billed_amount_cents`
    multiplied by a vendor allowable percentage keyed on `vendor_name` — eighty
    percent for the vendor `KP Affiliate` and seventy percent for any other
    vendor name — rounded half-up to a whole cent."
    PRD §3.6: "This provisional figure deliberately ignores the deductible, so
    it will differ from the final liability for the same claim."

    Design: Difficulty/dual_variant_calc/dual_claim_provisional_pct_vs_final_deductible
    """
    region = create_open_region()
    care_site = create_care_site(region["id"])
    create_department(care_site["id"])
    provider = create_provider(care_site["id"])
    member = enroll_member(region["id"], provider["id"])
    create_and_approve_budget(region["id"])

    billed = 520000
    claim = submit_claim(
        region["id"], member["id"], member["version"],
        vendor_name="Coastal Vendor A", billed_amount_cents=billed,
    )
    expected = int(round(billed * VENDOR_ALLOWABLE_PCT["Default"]))
    assert expected == 364000
    assert claim["provisional_liability_cents"] == expected, (
        f"Expected {expected}, got {claim['provisional_liability_cents']}"
    )


def test_claim_final_liability_diverges_from_the_provisional_figure(api):
    """PRD §3.6: "The final figure is pinned at adjudication and is
    chronological."
    PRD §3.6: "Adjudication pins the final liability, records `adjudicated_at`
    from the logical clock, moves the claim to `ADJUDICATED`, adds the final
    liability to the region's `outside_services_spend_cents`".

    Design: Difficulty/dual_variant_calc/dual_claim_provisional_pct_vs_final_deductible
    """
    region = create_open_region()
    care_site = create_care_site(region["id"])
    create_department(care_site["id"])
    provider = create_provider(care_site["id"])
    member = enroll_member(region["id"], provider["id"])
    create_and_approve_budget(region["id"])

    claim = submit_claim(
        region["id"], member["id"], member["version"],
        vendor_name="Coastal Vendor A", billed_amount_cents=520000,
    )
    assert claim["provisional_liability_cents"] == 364000

    adjudicate_res = api_client.adjudicate_claim(claim["id"], {}, _RFO)
    assert adjudicate_res.status_code == 200, adjudicate_res.text
    body = adjudicate_res.json()["data"]

    assert body["status"] == "ADJUDICATED"
    assert body["adjudicated_at"], "adjudication records the logical-clock instant"
    assert body["final_liability_cents"] != body["provisional_liability_cents"], (
        "the deductible-consuming final figure differs from the provisional percentage"
    )
    # The coinsurance rule charges 20% of the post-deductible excess, so the final
    # figure is bounded by the billed amount and is not the flat percentage read.
    assert body["final_liability_cents"] < body["provisional_liability_cents"]
    assert COINSURANCE_RATE == 0.20

    region_after = get_region(region["id"])
    assert region_after["outside_services_spend_cents"] == body["final_liability_cents"]