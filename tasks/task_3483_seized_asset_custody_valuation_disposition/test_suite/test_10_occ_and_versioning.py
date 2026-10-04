"""Optimistic concurrency control on the two guarded creation endpoints and
the honesty of the asset version counter."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accept_valuation,
    assert_interlocutory_sale_request,
    assert_valuation,
    create_case,
    create_isr,
    create_isr_payload,
    create_valuation_payload,
    create_valued_asset,
    fresh_asset_version,
    intake_asset,
    post_expense,
    submit_valuation,
    validate_created,
    validate_error,
    validate_paginated,
)


def test_valuation_create_stale_version_412(api):
    """PRD §2.7: "Submitting a valuation for an asset, and filing an
    interlocutory sale request against an asset, each require the request
    body to carry `expected_asset_version`, holding the `version` of the
    asset as the client last observed it. If the asset's current `version`
    has advanced since that observation — because a valuation was
    adjudicated, a custody transfer completed, an expense posted, an
    interlocutory request was filed, or a cascade fired — the request is
    rejected with `ERR_STALE_VERSION` (HTTP 412) and nothing is written."

    Design: Corner/cross_cutting_layers/valuation_create_stale_version_412
    """
    case = create_case(
        case_number="26-MJ-1035", judicial_district="D. Kan.",
        forfeiture_type="CIVIL", lead_agency_code="USMS",
    )
    asset = intake_asset(
        case["id"], asset_type="VEHICLE", description="suv",
        seized_on="2026-09-01T00:00:00Z", seizure_condition_grade="GOOD",
    )
    observed_version = asset["version"]
    first = submit_valuation(
        asset["id"], method="BLUE_BOOK", raw_value_cents=500_000,
        assessed_condition_grade="GOOD",
        expected_asset_version=observed_version,
    )
    accept_valuation(first["id"])

    # Creation (v1 -> v2) and acceptance (v2 -> v3) advanced the asset; the
    # carried version 1 is now stale.
    stale = api.create_valuation(
        create_valuation_payload(
            asset["id"], observed_version, method="MARKET_COMPARABLE",
            raw_value_cents=520_000, assessed_condition_grade="GOOD",
        ),
        TEST_USERS["appraiser_headers"],
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
    assert stale.status_code == 412

    fresh = fresh_asset_version(asset["id"])
    assert fresh == 3
    retried = validate_created(
        api.create_valuation(
            create_valuation_payload(
                asset["id"], fresh, method="MARKET_COMPARABLE",
                raw_value_cents=520_000, assessed_condition_grade="GOOD",
            ),
            TEST_USERS["appraiser_headers"],
        )
    )
    assert_valuation(retried)
    assert retried["status"] == "SUBMITTED"

    rows, meta = validate_paginated(
        api.list_asset_valuations(asset["id"], TEST_USERS["appraiser_headers"])
    )
    assert len(rows) == 2 and meta["total_count"] == 2, (
        "the ACCEPTED original and the new SUBMITTED valuation"
    )


def test_isr_create_stale_version_412(api):
    """PRD §2.7: "Submitting a valuation for an asset, and filing an
    interlocutory sale request against an asset, each require the request
    body to carry `expected_asset_version` ... If the asset's current
    `version` has advanced since that observation — because a valuation was
    adjudicated, a custody transfer completed, an expense posted, an
    interlocutory request was filed, or a cascade fired — the request is
    rejected with `ERR_STALE_VERSION` (HTTP 412) and nothing is written."
    PRD §2.7: "an interlocutory request's eligibility ratio is computed from
    the asset's current accumulators, so a stale-view request must be
    re-based on a fresh read rather than evaluated against figures the client
    can no longer see."

    Design: Corner/cross_cutting_layers/isr_create_stale_version_412
    """
    case = create_case(
        case_number="26-MJ-1036", judicial_district="E.D. Mich.",
        forfeiture_type="CIVIL", lead_agency_code="DEA",
    )
    asset, _valuation = create_valued_asset(
        case["id"], raw_value_cents=400_000, grade="EXCELLENT",
        method="BLUE_BOOK", description="van",
    )
    stale_version = fresh_asset_version(asset["id"])
    # An expense posting lands between the client's read and its submission.
    post_expense(
        asset["id"], 60_000, entry_kind="COST", expense_type="STORAGE",
        incurred_on="2026-09-02T00:00:00Z",
    )

    stale = api.create_interlocutory_sale_request(
        create_isr_payload(
            asset["id"], stale_version, justification="stale view",
        ),
        TEST_USERS["asset_manager_headers"],
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
    assert stale.status_code == 412

    isr = create_isr(
        asset["id"], justification="fresh view",
        expected_asset_version=fresh_asset_version(asset["id"]),
    )
    assert_interlocutory_sale_request(isr)
    assert isr["status"] == "PENDING"
    assert isr["projected_burden_cents"] == 135_000, "60000 + 3 x 25000"


def test_asset_version_increments_on_every_mutation(api):
    """PRD §2.5: "`version` (integer): starts at 1 when the resource is
    created and increments by exactly one on every mutation — including
    mutations the server applies as cascade side effects."
    PRD §3.3: "The very first valuation filed against an asset also moves the
    asset itself: `legal_state` advances automatically from `SEIZED` to
    `VALUATION_PENDING`, and the asset's `version` increments."
    PRD §3.4: "Each posting recomputes the asset's
    `accumulated_net_holding_cost_cents`, ... and increments the asset's
    `version`."
    PRD §3.3: "Both the valuation's and the asset's `version` increment on
    acceptance."

    Design: Corner/cross_cutting_layers/asset_version_increments_on_every_mutation
    """
    case = create_case(
        case_number="26-MJ-1037", judicial_district="D. Nev.",
        forfeiture_type="CIVIL", lead_agency_code="FBI",
    )
    asset = intake_asset(
        case["id"], asset_type="VEHICLE", description="coupe",
        seized_on="2026-09-01T00:00:00Z", seizure_condition_grade="GOOD",
    )
    assert asset["version"] == 1, "version starts at 1 at creation"

    post_expense(
        asset["id"], 10_000, entry_kind="COST", expense_type="STORAGE",
        incurred_on="2026-09-02T00:00:00Z",
    )
    v_after_expense = fresh_asset_version(asset["id"])
    assert v_after_expense == 2, "the expense posting bumped the asset"

    valuation = submit_valuation(
        asset["id"], method="BLUE_BOOK", raw_value_cents=300_000,
        assessed_condition_grade="GOOD",
        expected_asset_version=v_after_expense,
    )
    v_after_create = fresh_asset_version(asset["id"])
    assert v_after_create == 3, (
        "the valuation's creation itself mutates the asset's legal_state"
    )

    accept_valuation(valuation["id"])
    v_after_accept = fresh_asset_version(asset["id"])
    assert v_after_accept == 4, (
        "exactly one increment per mutation — no silent or double bumps"
    )
