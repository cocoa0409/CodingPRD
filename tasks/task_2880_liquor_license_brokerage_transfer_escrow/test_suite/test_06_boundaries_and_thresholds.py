"""Inclusive edges: the exact-180-day nonuse period, the zero-open-offer
withdrawal gate, the empty comparable set and the exactly-9000-bps quota tier.
"""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_instant_equals,
    create_brokerage,
    create_county,
    create_license,
    create_listing,
    create_seller,
    activate_listing,
    draft_agreement,
    file_safekeeping,
    make_seller_headers,
    preview_valuation,
    read_county,
    read_license,
    read_listing,
    setup_scenario,
    validate_error,
    validate_paginated,
)


def _idle_licence_bench():
    """One county and two CLASS_41 licences idle for 180 and 179 days."""
    county = create_county(quota_licenses_total=100)
    seller = create_seller()
    on_the_edge = create_license(
        county["id"], seller["id"],
        license_number="EDGE-180",
        license_class="CLASS_41_ONSALE_BEER_WINE",
        annual_gross_receipts_cents=20000000,
        last_active_date="2026-02-02",
    )
    one_day_short = create_license(
        county["id"], seller["id"],
        license_number="EDGE-179",
        license_class="CLASS_41_ONSALE_BEER_WINE",
        annual_gross_receipts_cents=20000000,
        last_active_date="2026-02-03",
    )
    return county, seller, on_the_edge, one_day_short


def test_a_nonuse_period_of_exactly_180_days_admits_the_initial_filing():
    """The inclusive lower bound qualifies.

    PRD: "The nonuse period is the number of whole UTC calendar days between the
    license's `last_active_date` and the date part of the current logical instant,
    and it must be at least 180 days — exactly 180 qualifies."

    PRD: "For an initial filing, `extension_index` is 0, `granted_months` is the
    requested figure capped at 12 months, and `effective_from` is the current
    logical instant."

    PRD: "The filing fee doubles with each step: `fee_cents` is a base of 20000
    cents multiplied by two raised to the power of `extension_index`, giving 20000
    cents for an initial filing, 40000 cents for a first extension and 80000 cents
    for a second."

    PRD: "Filing also sets the license's `safekeeping_filing_pending` flag to true
    and advances the license's `version` by one, which is what makes a replayed
    `expected_license_version` fail."

    From 2026-02-02 to the clock's 2026-08-01 is exactly 180 whole days.

    Design: Difficulty/boundary_precision_check/nonuse_period_exactly_180_days
    """
    _county, seller, on_the_edge, _short = _idle_licence_bench()

    filing = file_safekeeping(
        on_the_edge["id"], on_the_edge["version"],
        filing_type="INITIAL", requested_months=12, seller_id=seller["id"],
    )

    assert filing["extension_index"] == 0
    assert filing["granted_months"] == 12
    assert_instant_equals(
        filing["effective_from"], "2026-08-01T00:00:00Z", "effective_from"
    )
    assert_instant_equals(filing["expires_at"], "2027-08-01T00:00:00Z", "expires_at")
    assert filing["fee_cents"] == 20000
    assert filing["status"] == "PENDING"
    assert filing["decided_at"] is None

    license_row = read_license(on_the_edge["id"])
    assert license_row["safekeeping_filing_pending"] is True
    assert license_row["version"] == 2


def test_a_nonuse_period_of_179_days_is_one_day_premature():
    """A day short of the bound is refused and writes nothing.

    PRD: "A premature petition is refused with `ERR_NONUSE_PERIOD_NOT_REACHED`."

    PRD: "Only one filing per license may be awaiting decision at a time; a second
    one opened while the license's `safekeeping_filing_pending` flag is set is
    refused with `ERR_SAFEKEEPING_FILING_PENDING`."

    From 2026-02-03 to 2026-08-01 is 179 whole days. The refused petition leaves
    the licence's pending flag clear, its version at 1, and no filing on its
    reverse lookup at all.

    Design: Difficulty/boundary_precision_check/nonuse_period_exactly_180_days
    """
    _county, seller, _edge, one_day_short = _idle_licence_bench()

    refused = api_client.create_safekeeping_filing(
        {
            "license_id": one_day_short["id"],
            "filing_type": "INITIAL",
            "requested_months": 12,
            "expected_license_version": one_day_short["version"],
        },
        make_seller_headers(seller["id"]),
    )
    validate_error(refused, ApiErrorId.ERR_NONUSE_PERIOD_NOT_REACHED.value, 422)

    license_row = read_license(one_day_short["id"])
    assert license_row["safekeeping_filing_pending"] is False
    assert license_row["version"] == 1

    rows, meta = validate_paginated(
        api_client.list_license_safekeeping_filings(
            one_day_short["id"], TEST_USERS["platform_admin_headers"]
        )
    )
    assert meta["total_count"] == 0
    assert rows == []


def test_withdrawal_is_blocked_at_one_open_offer_and_allowed_at_zero():
    """The gate is `open_offer_count` greater than zero, so zero is permissive.

    PRD: "It is refused with `ERR_LISTING_HAS_OPEN_OFFERS` whenever
    `open_offer_count` is greater than zero — a broker must terminate its
    outstanding draft offers before retiring the listing — and on success the
    listing's `version` advances by one."

    PRD: "Pulling a listing back off the market moves it to `WITHDRAWN` from
    either `DRAFT` or `ACTIVE`, optionally recording a free-text `reason`."

    Design: Difficulty/boundary_precision_check/listing_withdraw_at_zero_open_offers
    """
    scenario = setup_scenario(
        stage="agreement_draft",
        county_overrides={"quota_licenses_total": 100},
    )
    listing_id = scenario["listing_id"]
    assert read_listing(listing_id)["open_offer_count"] == 1

    blocked = api_client.withdraw_listing(
        listing_id, scenario["broker_headers"], {"reason": "seller changed mind"}
    )
    validate_error(blocked, ApiErrorId.ERR_LISTING_HAS_OPEN_OFFERS.value, 409)
    assert read_listing(listing_id)["status"] == "ACTIVE"

    terminated = api_client.terminate_agreement(
        scenario["agreement_id"],
        {"reason": "buyer withdrew"},
        scenario["broker_headers"],
    )
    terminated_agreement = terminated.json()["data"]
    assert terminated_agreement["agreement_status"] == "TERMINATED"
    assert terminated_agreement["termination_reason"] == "buyer withdrew"
    assert read_listing(listing_id)["open_offer_count"] == 0

    withdrawn = api_client.withdraw_listing(
        listing_id, scenario["broker_headers"], {"reason": "seller changed mind"}
    )
    assert withdrawn.status_code == 200
    assert withdrawn.json()["data"]["status"] == "WITHDRAWN"
    assert read_listing(listing_id)["status"] == "WITHDRAWN"


def test_terminating_the_sole_draft_offer_frees_the_listing_for_withdrawal():
    """The open-offer counter is recomputed, not merely decremented.

    PRD: "This guard exists precisely because competing draft offers on one active
    listing are legitimate product behaviour: no state precondition blocks a second
    offer, so the only thing that can protect a caller from drafting against a
    listing whose `open_offer_count`, `market_price_cents` and frozen scarcity
    snapshot have moved underneath it — all three of which feed the deposit
    requirement — is the version token."

    PRD: "It is refused with `ERR_LISTING_HAS_OPEN_OFFERS` whenever
    `open_offer_count` is greater than zero — a broker must terminate its
    outstanding draft offers before retiring the listing — and on success the
    listing's `version` advances by one."

    Two draft offers stand at a count of two; retiring one still leaves the gate
    shut, and only the second termination brings the count to the permissive zero.

    Design: Difficulty/boundary_precision_check/listing_withdraw_at_zero_open_offers
    """
    scenario = setup_scenario(
        stage="agreement_draft",
        county_overrides={"quota_licenses_total": 100},
    )
    listing_id = scenario["listing_id"]
    second = draft_agreement(
        listing_id, scenario["buyer_id"], scenario["premises_id"],
        read_listing(listing_id)["version"], scenario["brokerage_id"],
        closing_window_start="2026-12-30T00:00:00Z",
    )
    assert read_listing(listing_id)["open_offer_count"] == 2

    api_client.terminate_agreement(
        scenario["agreement_id"], {"reason": "buyer withdrew"},
        scenario["broker_headers"],
    )
    assert read_listing(listing_id)["open_offer_count"] == 1
    still_blocked = api_client.withdraw_listing(
        listing_id, scenario["broker_headers"], {"reason": "seller changed mind"}
    )
    validate_error(still_blocked, ApiErrorId.ERR_LISTING_HAS_OPEN_OFFERS.value, 409)

    api_client.terminate_agreement(
        second["id"], {"reason": "buyer withdrew"}, scenario["broker_headers"]
    )
    assert read_listing(listing_id)["open_offer_count"] == 0

    allowed = api_client.withdraw_listing(
        listing_id, scenario["broker_headers"], {"reason": "seller changed mind"}
    )
    assert allowed.status_code == 200
    assert allowed.json()["data"]["status"] == "WITHDRAWN"


def _lone_licence_bench():
    """A county holding exactly one license, so the comparable set is empty."""
    county = create_county(
        quota_licenses_total=100, default_valuation_basis="COMPARABLE_SALES"
    )
    seller = create_seller()
    brokerage = create_brokerage()
    license_row = create_license(
        county["id"], seller["id"],
        license_number="LONE-1",
        license_class="CLASS_47_ONSALE_GENERAL",
        annual_gross_receipts_cents=120000000,
    )
    listing = create_listing(
        license_row["id"], brokerage["id"], ask_price_cents=5000000
    )
    return county, brokerage, license_row, listing


def test_an_empty_comparable_set_falls_back_to_the_statutory_median_floor():
    """A comparable count of zero is the signal that the floor was applied.

    PRD: "When the count is zero, the comparable median is taken to be a statutory
    floor of 4500000 cents — forty-five thousand dollars — and a reported
    comparable count of zero is precisely the signal that this fallback was
    applied."

    PRD: "**The income-multiple variant** takes the subject license's
    `annual_gross_receipts_cents`, multiplies by 1800 and divides by ten thousand
    — eighteen percent of trailing annual receipts — then multiplies that by ten
    thousand plus the scarcity uplift and divides by ten thousand again, and rounds
    half up exactly once at the very end."

    PRD: "The subject is always excluded even when it carries its own prior
    transfer price."

    The lone license contributes nothing to its own comparable set, so the
    comparable price is the bare 4500000 floor while the income variant reads
    21600000 — a divergence of 17100000.

    Design: Difficulty/boundary_precision_check/valuation_with_empty_comparable_set
    """
    _county, brokerage, license_row, listing = _lone_licence_bench()

    preview = preview_valuation(listing["id"])
    assert preview["license_id"] == license_row["id"]
    assert preview["comp_count"] == 0
    assert preview["comp_median_cents"] == 4500000
    assert preview["scarcity_bps"] == 0
    assert preview["comparable_sales_price_cents"] == 4500000
    assert preview["income_multiple_price_cents"] == 21600000
    assert preview["divergence_cents"] == 17100000


def test_activation_on_an_empty_comparable_set_inherits_the_county_default_basis():
    """With no basis supplied the county's default resolves the variant.

    PRD: "The broker may supply a `valuation_basis` to select the variant; when
    omitted, the county's `default_valuation_basis` is used."

    PRD: "Whichever variant the resolved basis selects becomes the listing's
    `market_price_cents`; the comparable count is stored as
    `comp_count_at_activation` in either case, including under the income-multiple
    variant where the comparables did not influence the price."

    Design: Difficulty/boundary_precision_check/valuation_with_empty_comparable_set
    """
    _county, brokerage, _license_row, listing = _lone_licence_bench()

    activated = activate_listing(listing["id"], brokerage["id"])

    assert activated["valuation_basis"] == "COMPARABLE_SALES"
    assert activated["market_price_cents"] == 4500000
    assert activated["comp_count_at_activation"] == 0
    assert activated["scarcity_bps_at_activation"] == 0
    assert read_listing(listing["id"])["market_price_cents"] == 4500000


def _nine_of_ten_slots_bench():
    """Nine counted licences against a ceiling of ten, eight of them priced."""
    county = create_county(
        quota_licenses_total=10, default_valuation_basis="COMPARABLE_SALES"
    )
    seller = create_seller()
    brokerage = create_brokerage()
    for index in range(1, 9):
        create_license(
            county["id"], seller["id"],
            license_number=f"C41-{index}",
            license_class="CLASS_41_ONSALE_BEER_WINE",
            annual_gross_receipts_cents=20000000,
            last_transfer_price_cents=5000000,
        )
    subject = create_license(
        county["id"], seller["id"],
        license_number="C41-SUBJ",
        license_class="CLASS_41_ONSALE_BEER_WINE",
        annual_gross_receipts_cents=20000000,
    )
    listing = create_listing(subject["id"], brokerage["id"], ask_price_cents=6000000)
    return county, brokerage, subject, listing


def test_utilization_of_exactly_9000_bps_sits_in_the_top_scarcity_tier():
    """Nine of ten slots is the inclusive edge of the highest tier.

    PRD: "`quota_utilization_bps` is the counted figure multiplied by ten
    thousand, divided by `quota_licenses_total`, and rounded half up to an integer
    basis-point value; when `quota_licenses_total` is zero the utilization is
    reported as 10000 rather than attempting the division."

    PRD: "The bounds are inclusive, so a county with nine of its ten quota slots
    occupied — utilization of exactly 9000 basis points — sits in the top tier at
    2500, not the second tier at 1200."

    Design: Difficulty/boundary_precision_check/quota_utilization_exactly_9000_bps
    """
    county, brokerage, _subject, listing = _nine_of_ten_slots_bench()

    stored_county = read_county(county["id"])
    assert stored_county["quota_licenses_counted"] == 9
    assert stored_county["quota_available"] == 1
    assert stored_county["quota_utilization_bps"] == 9000

    preview = preview_valuation(listing["id"])
    assert preview["scarcity_bps"] == 2500
    assert preview["scarcity_bps"] != 1200
    assert preview["comp_count"] == 8
    assert preview["comp_median_cents"] == 5000000


def test_the_top_tier_uplift_is_snapshotted_onto_the_activated_listing():
    """2500 basis points of uplift lift the median to 6250000.

    PRD: "A utilization of 9000 basis points or more yields an uplift of 2500 basis
    points."

    PRD: "When the count is even, the median is the sum of the two middle prices
    divided by two, rounded half up to whole cents."

    PRD: "The uplift is read live when a valuation preview is computed, is
    snapshotted onto a listing at the moment of activation, and is thereafter read
    from that snapshot rather than recomputed."

    Eight peers all priced at 5000000 give an even count whose median is 5000000;
    5000000 * 12500 / 10000 = 6250000.

    Design: Difficulty/boundary_precision_check/quota_utilization_exactly_9000_bps
    """
    _county, brokerage, _subject, listing = _nine_of_ten_slots_bench()

    activated = activate_listing(listing["id"], brokerage["id"])

    assert activated["scarcity_bps_at_activation"] == 2500
    assert activated["scarcity_bps_at_activation"] != 1200
    assert activated["comp_count_at_activation"] == 8
    assert activated["market_price_cents"] == 6250000
