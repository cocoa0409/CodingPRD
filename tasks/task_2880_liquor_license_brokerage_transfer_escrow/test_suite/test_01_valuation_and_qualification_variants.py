"""Dual-variant valuation and dual-mode buyer qualification.

Both capabilities here compute two different numbers from one input set and
store only the number the selected variant or mode produced.
"""

from test_helpers import (
    activate_listing,
    assert_buyer_profile,
    assert_listing,
    create_buyer,
    create_county,
    preview_valuation,
    read_buyer,
    read_listing,
    read_premises,
    register_premises,
    review_buyer,
    setup_comparable_bench,
)

COMP_PRICES = (16000000, 18500000, 21000000)
SUBJECT_RECEIPTS_CENTS = 120000000
ASK_PRICE_CENTS = 18500000


def _valuation_bench():
    """Three priced peers in one county plus a high-revenue subject license."""
    return setup_comparable_bench(
        comp_prices=COMP_PRICES,
        subject_receipts_cents=SUBJECT_RECEIPTS_CENTS,
        ask_price_cents=ASK_PRICE_CENTS,
        county_overrides={
            "quota_licenses_total": 100,
            "default_valuation_basis": "COMPARABLE_SALES",
        },
    )


def test_valuation_preview_reports_both_variants_and_their_signed_divergence():
    """The preview runs both variants against one comparable set.

    PRD: "Because the two variants can differ dramatically, a read-only preview
    capability lets a `PlatformAdmin`, a `Broker` or a `RegulatorAnalyst` run
    both variants against the current comparable set and the license's current
    receipts without writing anything to the listing."

    PRD: "Its response reports the `listing_id` and `license_id` under
    examination, the `default_valuation_basis` configured on the county, the
    live `comp_count` and `comp_median_cents`, the live `scarcity_bps`, both
    `comparable_sales_price_cents` and `income_multiple_price_cents`, and
    `divergence_cents`, which is exactly the income-multiple price minus the
    comparable-sales price and is therefore signed — negative when the
    comparable market values the license more highly than its own revenue does."

    PRD: "When the count is odd, the median is the middle price."

    PRD: "Below that the uplift is zero."

    Three peers priced 16000000, 18500000 and 21000000 give an odd count, so
    the median is the middle price 18500000. Four of a hundred quota slots are
    occupied, so utilization sits below 5000 basis points and the uplift is
    zero: the comparable-sales price is the bare median 18500000, while
    eighteen percent of the subject's 120000000 receipts is 21600000. The
    signed divergence is 21600000 - 18500000 = 3100000.

    Design: Difficulty/dual_variant_calc/listing_valuation_basis_divergence
    """
    bench = _valuation_bench()
    preview = preview_valuation(bench["listing_id"], bench["broker_headers"])

    assert preview["listing_id"] == bench["listing_id"]
    assert preview["license_id"] == bench["license_id"]
    assert preview["default_valuation_basis"] == "COMPARABLE_SALES"
    assert preview["comp_count"] == 3
    assert preview["comp_median_cents"] == 18500000
    assert preview["scarcity_bps"] == 0
    assert preview["comparable_sales_price_cents"] == 18500000
    assert preview["income_multiple_price_cents"] == 21600000
    assert preview["divergence_cents"] == 3100000
    assert (
        preview["divergence_cents"]
        == preview["income_multiple_price_cents"]
        - preview["comparable_sales_price_cents"]
    )


def test_preview_writes_nothing_to_the_draft_listing():
    """A preview leaves every valuation field on the draft null.

    PRD: "A draft listing carries `open_offer_count` of 0 and has
    `valuation_basis`, `market_price_cents`, `scarcity_bps_at_activation`,
    `comp_count_at_activation` and `activated_at` all null; no valuation is
    computed while the listing is a draft."

    PRD: "`version`, an integer that starts at 1 on creation and increases by
    exactly one on every mutation of that resource."

    Design: Difficulty/dual_variant_calc/listing_valuation_basis_divergence
    """
    bench = _valuation_bench()
    preview_valuation(bench["listing_id"], bench["broker_headers"])

    after = read_listing(bench["listing_id"])
    assert after["status"] == "DRAFT"
    assert after["valuation_basis"] is None
    assert after["market_price_cents"] is None
    assert after["scarcity_bps_at_activation"] is None
    assert after["comp_count_at_activation"] is None
    assert after["activated_at"] is None
    assert after["open_offer_count"] == 0
    assert after["version"] == 1


def test_activation_stores_the_income_multiple_price_and_still_snapshots_comps():
    """The selected variant alone reaches `market_price_cents`.

    PRD: "The broker may supply a `valuation_basis` to select the variant; when
    omitted, the county's `default_valuation_basis` is used."

    PRD: "Whichever variant the resolved basis selects becomes the listing's
    `market_price_cents`; the comparable count is stored as
    `comp_count_at_activation` in either case, including under the
    income-multiple variant where the comparables did not influence the price."

    PRD: "Activation then snapshots the county scarcity uplift onto
    `scarcity_bps_at_activation`, runs the valuation in the selected variant to
    write `market_price_cents` and `comp_count_at_activation`, records
    `activated_at` as the current logical instant, and advances the listing's
    `version` by one."

    The county defaults to comparable sales, which would have priced the
    license at 18500000; overriding the basis to income multiple stores
    21600000 instead, while the peer count 3 is snapshotted regardless.

    Design: Difficulty/dual_variant_calc/listing_valuation_basis_divergence
    """
    bench = _valuation_bench()
    listing = activate_listing(
        bench["listing_id"],
        bench["brokerage_id"],
        valuation_basis="INCOME_MULTIPLE",
    )

    assert_listing(listing)
    assert listing["status"] == "ACTIVE"
    assert listing["valuation_basis"] == "INCOME_MULTIPLE"
    assert listing["market_price_cents"] == 21600000
    assert listing["market_price_cents"] != 18500000
    assert listing["comp_count_at_activation"] == 3
    assert listing["scarcity_bps_at_activation"] == 0
    assert listing["activated_at"] is not None
    assert listing["version"] == 2


def test_comparable_sales_variant_ignores_the_subjects_own_receipts():
    """The other variant prices the same inventory differently.

    PRD: "**The comparable-sales variant** takes the comparable median,
    multiplies it by ten thousand plus the scarcity uplift, divides by ten
    thousand, and rounds half up once to whole cents."

    PRD: "It ignores the subject license's own receipts entirely, so two
    licenses in the same county and class with wildly different revenue are
    priced identically."

    Design: Difficulty/dual_variant_calc/listing_valuation_basis_divergence
    """
    bench = _valuation_bench()
    listing = activate_listing(
        bench["listing_id"],
        bench["brokerage_id"],
        valuation_basis="COMPARABLE_SALES",
    )

    assert listing["valuation_basis"] == "COMPARABLE_SALES"
    assert listing["market_price_cents"] == 18500000
    assert listing["market_price_cents"] != 21600000
    assert listing["comp_count_at_activation"] == 3
    assert listing["scarcity_bps_at_activation"] == 0


def _out_of_state_buyer_at_unresolved_premises():
    """An unverified out-of-state buyer named against a location whose permit
    and landlord consent are both still outstanding."""
    county = create_county()
    buyer = create_buyer(
        legal_name="Nevada Hospitality LLC",
        entity_type="LLC",
        residency_state="NV",
        citizenship_verified=False,
        felony_disclosure=False,
        prior_revocation_count=0,
    )
    premises = register_premises(buyer["id"], county["id"])
    return county, buyer, premises


def test_registration_leaves_the_premises_conditional_on_an_outstanding_permit():
    """Rule 6 fires on a lawfully sited but unpermitted parcel.

    PRD: "Two standing fields start pessimistically: `conditional_use_permit_status`
    begins at `REQUIRED_NOT_FILED` — its full enumeration being `NOT_REQUIRED`,
    `REQUIRED_NOT_FILED`, `PENDING`, `GRANTED` and `DENIED` — and
    `landlord_consent_status` begins at `PENDING`, drawn from `NOT_REQUIRED`,
    `PENDING`, `GRANTED` and `REFUSED`."

    PRD: "The conditional-use permit standing is either `REQUIRED_NOT_FILED` or
    `PENDING` — `CONDITIONAL` with reason `CUP_OUTSTANDING`."

    This is the location both qualification modes are scored against.

    Design: Difficulty/dual_variant_calc/buyer_qualification_mode_band_drop
    """
    _county, _buyer, premises = _out_of_state_buyer_at_unresolved_premises()

    assert premises["conditional_use_permit_status"] == "REQUIRED_NOT_FILED"
    assert premises["landlord_consent_status"] == "PENDING"
    assert premises["suitability_status"] == "CONDITIONAL"
    assert premises["suitability_reason_code"] == "CUP_OUTSTANDING"
    assert read_premises(premises["id"])["suitability_reason_code"] == "CUP_OUTSTANDING"


def test_pre_check_treats_every_unresolved_premises_condition_as_neutral():
    """`PRE_CHECK` scores 70 and bands as qualified.

    PRD: "Twenty points are deducted when `citizenship_verified` is false."

    PRD: "Ten points are deducted when the buyer's `residency_state` differs
    from the `state_code` of the county in which the named premises sits."

    PRD: "Under `PRE_CHECK` — the marketing-stage pre-qualification a broker
    runs before any location has been verified — the premises component is zero,
    so every unresolved condition is treated as neutral."

    PRD: "Otherwise a score of 70 or more is `QUALIFIED`, a score of 50 or more
    is `PROVISIONALLY_QUALIFIED`, and anything below 50 is `UNQUALIFIED`; the
    band bounds are inclusive lower bounds, so a score of exactly 70 is
    `QUALIFIED` and a score of exactly 50 is `PROVISIONALLY_QUALIFIED`."

    100 - 20 unverified - 10 out-of-state = 70, exactly on the inclusive lower
    bound of the qualified band.

    Design: Difficulty/dual_variant_calc/buyer_qualification_mode_band_drop
    """
    _county, buyer, premises = _out_of_state_buyer_at_unresolved_premises()

    reviewed = review_buyer(buyer["id"], premises["id"], review_mode="PRE_CHECK")

    assert_buyer_profile(reviewed)
    assert reviewed["qualification_score"] == 70
    assert reviewed["qualification_status"] == "QUALIFIED"
    assert reviewed["qualification_mode"] == "PRE_CHECK"
    assert reviewed["qualification_reviewed_at"] is not None
    assert reviewed["version"] == 2


def test_final_review_drops_the_same_buyer_two_bands_from_the_same_facts():
    """`FINAL_REVIEW` adds thirty points of premises deductions.

    PRD: "Under `FINAL_REVIEW` — the regulator's pre-execution review — fifteen
    points are deducted when the premises' `conditional_use_permit_status` is
    neither `NOT_REQUIRED` nor `GRANTED`, and a further fifteen points are
    deducted when its `landlord_consent_status` is neither `NOT_REQUIRED` nor
    `GRANTED`."

    PRD: "The same buyer against the same unresolved location therefore scores
    strictly higher under `PRE_CHECK` than under `FINAL_REVIEW`, and can drop
    two bands between the two."

    PRD: "The review reads the buyer's own declarations, the named premises, and
    that premises' county, and writes `qualification_score`,
    `qualification_status`, `qualification_mode` and `qualification_reviewed_at`
    (set to the current logical instant) back onto the buyer, advancing the
    buyer's `version` by one."

    70 under pre-check becomes 70 - 15 - 15 = 40 under final review: qualified
    to unqualified, skipping the provisional band entirely. Two reviews on a
    buyer created at version 1 leave it at version 3.

    Design: Difficulty/dual_variant_calc/buyer_qualification_mode_band_drop
    """
    _county, buyer, premises = _out_of_state_buyer_at_unresolved_premises()

    pre_check = review_buyer(buyer["id"], premises["id"], review_mode="PRE_CHECK")
    final = review_buyer(buyer["id"], premises["id"], review_mode="FINAL_REVIEW")

    assert final["qualification_score"] == 40
    assert final["qualification_score"] < pre_check["qualification_score"]
    assert final["qualification_status"] == "UNQUALIFIED"
    assert final["qualification_mode"] == "FINAL_REVIEW"
    assert final["version"] == 3

    stored = read_buyer(buyer["id"])
    assert stored["qualification_score"] == 40
    assert stored["qualification_status"] == "UNQUALIFIED"
    assert stored["qualification_mode"] == "FINAL_REVIEW"
    assert stored["version"] == 3
