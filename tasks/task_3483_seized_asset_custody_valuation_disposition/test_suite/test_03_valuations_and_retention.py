"""Valuation lifecycle, condition adjustment, retention-value variants, and
the fiscal gates on the retain-or-sell decision."""

from test_helpers import (
    CLOCK_EPOCH,
    ApiErrorId,
    TEST_USERS,
    accept_valuation,
    assert_valuation,
    create_case,
    create_valuation_payload,
    create_valued_asset,
    decide_retention,
    get_asset,
    intake_asset,
    post_expense,
    submit_valuation,
    validate_created,
    validate_error,
    validate_paginated,
)


def test_valuation_accept_side_effects_update_asset(api):
    """PRD §3.3: "Acceptance moves the valuation from `SUBMITTED` to
    `ACCEPTED` and carries much further effects. The asset's
    `appraised_value_cents` is overwritten with the accepted valuation's
    `adjusted_value_cents`, `appraised_at` is stamped with the logical clock
    time, and both retention-value estimates described below are recomputed."
    PRD §3.3: "an acceptance while `VALUATION_PENDING` advances the asset to
    `VALUED`".
    PRD §3.3: the provisional burden is "the accumulated net holding cost plus
    a six-month projection of carrying cost at the monthly rate for the
    asset's type".

    Design: Corner/state_machines/valuation_accept_side_effects_update_asset
    """
    case = create_case(
        case_number="26-MJ-1010", judicial_district="W.D. Tex.",
        forfeiture_type="CIVIL", lead_agency_code="DEA",
    )
    asset = intake_asset(
        case["id"], asset_type="VEHICLE", description="motorcycle",
        seized_on="2026-09-01T00:00:00Z", seizure_condition_grade="GOOD",
    )
    valuation = submit_valuation(
        asset["id"], method="CERTIFIED_APPRAISAL", raw_value_cents=1_000_000,
        assessed_condition_grade="GOOD",
    )
    pending = get_asset(asset["id"])
    assert pending["legal_state"] == "VALUATION_PENDING"
    assert pending["appraised_value_cents"] is None
    assert pending["final_net_retention_value_cents"] is None
    # SUBMITTED base 900000 minus (0 + 6 x 25000 VEHICLE) == 750000.
    assert pending["provisional_net_retention_value_cents"] == 750_000

    accept_valuation(valuation["id"])
    accepted = get_asset(asset["id"])
    assert accepted["appraised_value_cents"] == 900_000, (
        "raw 1000000 x GOOD factor 9000 bps rounds to 900000"
    )
    assert accepted["legal_state"] == "VALUED"
    assert accepted["appraised_at"] == CLOCK_EPOCH

    post_expense(
        asset["id"], 10_000, entry_kind="COST", expense_type="STORAGE",
        incurred_on="2026-09-02T00:00:00Z",
    )
    after_cost = get_asset(asset["id"])
    assert after_cost["provisional_net_retention_value_cents"] == 740_000, (
        "900000 - (10000 + 6 x 25000)"
    )
    assert after_cost["final_net_retention_value_cents"] == 890_000, (
        "900000 - 10000 (accepted base, posted costs only)"
    )


def test_valuation_double_adjudication_rejected(api):
    """PRD §3.3: "A `CourtOfficial` adjudicates a `SUBMITTED` valuation by
    supplying an `outcome` of `ACCEPT` or `REJECT`."
    PRD §2.10: "**State preconditions** — the entity is in a valid from-state
    for the requested transition, covering `ERR_INVALID_STATE` for invalid
    from-states in general".

    Design: Corner/state_machines/valuation_double_adjudication_rejected
    """
    case = create_case(
        case_number="26-MJ-1013", judicial_district="D. Idaho",
        forfeiture_type="CIVIL", lead_agency_code="ATF",
    )
    asset = intake_asset(
        case["id"], asset_type="VEHICLE", description="scooter",
        seized_on="2026-09-01T00:00:00Z", seizure_condition_grade="GOOD",
    )
    valuation = submit_valuation(
        asset["id"], method="BLUE_BOOK", raw_value_cents=1_000_000,
        assessed_condition_grade="GOOD",
    )
    accept_valuation(valuation["id"])
    resp = api.adjudicate_valuation(
        valuation["id"], "REJECT", TEST_USERS["court_official_headers"]
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert resp.status_code == 409
    rows, _ = validate_paginated(
        api.list_asset_valuations(asset["id"], TEST_USERS["court_official_headers"])
    )
    assert rows[0]["id"] == valuation["id"]
    assert rows[0]["status"] == "ACCEPTED", (
        "a failed second adjudication is not a state change"
    )
    assert get_asset(asset["id"])["appraised_value_cents"] == 900_000


def test_retained_asset_terminal_lockdown(api):
    """PRD §3.3: "A passing `RETAIN` sets `retention_decision` to `RETAIN` and
    moves the asset from `VALUED` to `RETAINED`, terminal on the legal track."
    PRD §3.3: "Requesting either decision while the asset is not `VALUED` is
    an `ERR_INVALID_STATE`."
    PRD §3.3: "The asset's `legal_state` must be `SEIZED`,
    `VALUATION_PENDING`, `VALUED`, or `DISPOSITION_REVIEW`; any other legal
    state rejects the submission with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/retained_asset_terminal_lockdown
    """
    case = create_case(
        case_number="26-MJ-1012", judicial_district="D. Minn.",
        forfeiture_type="CIVIL", lead_agency_code="USMS",
    )
    asset, _valuation = create_valued_asset(
        case["id"], raw_value_cents=2_000_000, grade="EXCELLENT",
        method="BLUE_BOOK", description="patrol car",
    )
    decide_retention(asset["id"], "RETAIN")
    retained = get_asset(asset["id"])
    assert retained["legal_state"] == "RETAINED"
    assert retained["retention_decision"] == "RETAIN"

    second = api.decide_retention(
        asset["id"], "SELL", TEST_USERS["asset_manager_headers"]
    )
    validate_error(second, ApiErrorId.ERR_INVALID_STATE)
    assert second.status_code == 409

    reval = api.create_valuation(
        create_valuation_payload(
            asset["id"], retained["version"], method="BLUE_BOOK",
            raw_value_cents=2_100_000, assessed_condition_grade="EXCELLENT",
        ),
        TEST_USERS["appraiser_headers"],
    )
    validate_error(reval, ApiErrorId.ERR_INVALID_STATE)
    assert reval.status_code == 409


def test_retention_floor_and_ratio_rejections(api):
    """PRD §3.3: "Retention is fiscally gated twice, and within the fiscal
    tier the floor is checked before the ratio. First,
    `final_net_retention_value_cents` must be at least 500,000 cents ($5,000);
    a lower figure rejects the retention with `ERR_RETENTION_VALUE_TOO_LOW`."
    PRD §3.3: "when the burden has already reached that thirty-percent line,
    retention is rejected with `ERR_RETENTION_BLOCKED_HOLDING_COST`, because
    holding costs have run too far for retention to be responsible."

    Design: Corner/errors/retention_floor_and_ratio_rejections
    """
    case = create_case(
        case_number="26-MJ-1031", judicial_district="D. Or.",
        forfeiture_type="CIVIL", lead_agency_code="DEA",
    )
    # Asset L: final 400000 < 500000 floor; ratio passes (burden 75000 < 30%
    # of 400000), so the floor failure is isolated.
    asset_l, _ = create_valued_asset(
        case["id"], raw_value_cents=400_000, grade="EXCELLENT",
        method="BLUE_BOOK", description="compact L",
    )
    # Asset M: final 630000 >= floor; burden 245000 >= 30% of 800000 (240000),
    # so the ratio failure is isolated.
    asset_m, _ = create_valued_asset(
        case["id"], raw_value_cents=800_000, grade="EXCELLENT",
        method="BLUE_BOOK", description="suv M",
    )
    post_expense(
        asset_m["id"], 100_000, entry_kind="COST", expense_type="STORAGE",
        incurred_on="2026-09-02T00:00:00Z",
    )
    post_expense(
        asset_m["id"], 70_000, entry_kind="COST", expense_type="MAINTENANCE",
        incurred_on="2026-09-03T00:00:00Z",
    )

    floor_resp = api.decide_retention(
        asset_l["id"], "RETAIN", TEST_USERS["asset_manager_headers"]
    )
    validate_error(floor_resp, ApiErrorId.ERR_RETENTION_VALUE_TOO_LOW)
    assert floor_resp.status_code == 422

    ratio_resp = api.decide_retention(
        asset_m["id"], "RETAIN", TEST_USERS["asset_manager_headers"]
    )
    validate_error(ratio_resp, ApiErrorId.ERR_RETENTION_BLOCKED_HOLDING_COST)
    assert ratio_resp.status_code == 422

    assert get_asset(asset_l["id"])["legal_state"] == "VALUED"
    assert get_asset(asset_m["id"])["legal_state"] == "VALUED", (
        "rejections do not move the legal track"
    )


def test_retention_value_provisional_vs_final(api):
    """PRD §3.3: "The final variant, `final_net_retention_value_cents`, is
    null until the first valuation is accepted; thereafter it is the
    `adjusted_value_cents` of the latest accepted valuation ... minus the
    asset's `accumulated_net_holding_cost_cents`. It uses accepted valuations
    and actually posted net costs only, no projection"
    PRD §3.3: "The provisional variant, `provisional_net_retention_value_cents`,
    is null until at least one valuation exists in any status; thereafter its
    base is the `adjusted_value_cents` of the latest `SUBMITTED` valuation
    when a submission is pending, falling back to the latest accepted
    valuation otherwise, and its burden is the accumulated net holding cost
    plus a six-month projection of carrying cost at the monthly rate for the
    asset's type."

    Design: Difficulty/dual_variant_calc/retention_value_provisional_vs_final
    """
    case = create_case(
        case_number="26-MJ-0001", judicial_district="S.D.N.Y.",
        forfeiture_type="CIVIL", lead_agency_code="DEA",
    )
    asset = intake_asset(
        case["id"], asset_type="VEHICLE", description="2022 freight tractor",
        seized_on="2026-09-01T00:00:00Z", seizure_condition_grade="GOOD",
    )
    v1 = submit_valuation(
        asset["id"], method="CERTIFIED_APPRAISAL", raw_value_cents=2_000_000,
        assessed_condition_grade="GOOD",
    )
    accept_valuation(v1["id"])
    post_expense(
        asset["id"], 70_000, entry_kind="COST", expense_type="STORAGE",
        incurred_on="2026-09-02T00:00:00Z",
    )
    post_expense(
        asset["id"], 50_000, entry_kind="COST", expense_type="MAINTENANCE",
        incurred_on="2026-09-03T00:00:00Z",
    )
    v2 = submit_valuation(
        asset["id"], method="MARKET_COMPARABLE", raw_value_cents=2_200_000,
        assessed_condition_grade="GOOD",
    )
    assert v2["status"] == "SUBMITTED", (
        "the revaluation is never adjudicated, yet it drives PROVISIONAL"
    )

    final = get_asset(asset["id"])
    # PROVISIONAL: latest SUBMITTED base 1980000 - (120000 + 6 x 25000).
    assert final["provisional_net_retention_value_cents"] == 1_710_000
    # FINAL: latest ACCEPTED base 1800000 - 120000 posted costs.
    assert final["final_net_retention_value_cents"] == 1_680_000
    assert (
        final["provisional_net_retention_value_cents"]
        != final["final_net_retention_value_cents"]
    ), "same asset, same instant: the two variants must diverge"


def test_income_approach_per_year_rounding(api):
    """PRD §3.3: "For `INCOME_APPROACH`, each of the three annual net revenues
    is capitalized at thirty-three percent (3,300 basis points) and that
    per-year product is rounded half up to a whole cent, and only then are the
    three rounded products summed — the rounding happens per year, before
    summation, so three years of 10,001 cents apiece capitalize to 3,300 cents
    each and 9,900 cents in total, not the 9,901 that rounding a single sum
    would produce."
    PRD §3.3: "The very first valuation filed against an asset also moves the
    asset itself: `legal_state` advances automatically from `SEIZED` to
    `VALUATION_PENDING`"

    Design: Difficulty/combinatorial_formula/income_approach_per_year_rounding
    """
    case = create_case(
        case_number="26-MJ-0004", judicial_district="D. Del.",
        forfeiture_type="CIVIL", lead_agency_code="IRS",
    )
    asset = intake_asset(
        case["id"], asset_type="BUSINESS", description="vending route",
        seized_on="2026-09-01T00:00:00Z", seizure_condition_grade="GOOD",
    )
    valuation = validate_created(
        api.create_valuation(
            create_valuation_payload(
                asset["id"], asset["version"], method="INCOME_APPROACH",
                annual_net_revenues_cents=[10001, 10001, 10001],
            ),
            TEST_USERS["appraiser_headers"],
        )
    )
    assert_valuation(valuation)
    assert valuation["adjusted_value_cents"] == 9_900, (
        "per-year round-then-sum: 3 x RHU(10001 x 3300, 10000) == 9900"
    )
    assert valuation["adjusted_value_cents"] != 9_901, (
        "the sum-then-round order is NOT used"
    )
    assert get_asset(asset["id"])["legal_state"] == "VALUATION_PENDING"
