"""Interlocutory sale requests: the eligibility ratio, its inclusive
boundary, cross-entity state gates, the approval cascade, and segregation
of duties."""

from test_helpers import (
    ApiErrorId,
    ASSET_MANAGER_USER_ID,
    COURT_OFFICIAL_USER_ID,
    TEST_USERS,
    accept_valuation,
    adjudicate_isr,
    assert_interlocutory_sale_request,
    complete_transfer,
    create_case,
    create_isr,
    create_isr_payload,
    create_valued_asset,
    dismiss_case,
    fresh_asset_version,
    get_asset,
    intake_asset,
    make_asset_manager_headers,
    make_court_official_headers,
    post_expense,
    run_holding_review,
    schedule_transfer,
    set_clock,
    submit_valuation,
    validate_error,
    validate_paginated,
)


def test_interlocutory_eligibility_forward_looking(api):
    """PRD §3.4: "the eligibility ratio must hold: the projected burden —
    `accumulated_net_holding_cost_cents` plus three months of carrying cost
    at the asset type's monthly rate — multiplied by one hundred must be
    greater than or equal to thirty times the asset's
    `appraised_value_cents`."
    PRD §3.4: "anything below rejects the request with
    `ERR_RATIO_BELOW_THRESHOLD`"
    PRD §3.3: the monthly carrying rates are "25,000 ($250) for `VEHICLE`"
    and "8,000 ($80) for `PERSONAL_PROPERTY`".

    Design: Difficulty/combinatorial_formula/interlocutory_eligibility_forward_looking
    """
    case = create_case(
        case_number="26-MJ-0003", judicial_district="E.D. Va.",
        forfeiture_type="CIVIL", lead_agency_code="ATF",
    )
    vehicle, _ = create_valued_asset(
        case["id"], raw_value_cents=400_000, grade="EXCELLENT",
        method="BLUE_BOOK", asset_type="VEHICLE", description="box truck",
    )
    post_expense(
        vehicle["id"], 60_000, entry_kind="COST", expense_type="STORAGE",
        incurred_on="2026-09-02T00:00:00Z",
    )
    personal, _ = create_valued_asset(
        case["id"], raw_value_cents=400_000, grade="EXCELLENT",
        method="CERTIFIED_APPRAISAL", asset_type="PERSONAL_PROPERTY",
        description="coin collection",
    )
    post_expense(
        personal["id"], 60_000, entry_kind="COST", expense_type="STORAGE",
        incurred_on="2026-09-02T00:00:00Z",
    )

    # Identical accumulated cost and appraised value; only the carrying-cost
    # tier differs: 60000 + 3 x 25000 = 135000 >= 120000 qualifies.
    isr = create_isr(vehicle["id"], justification="carrying cost burn")
    assert_interlocutory_sale_request(isr)
    assert isr["status"] == "PENDING"
    assert isr["projected_burden_cents"] == 135_000

    # 60000 + 3 x 8000 = 84000 < 120000 does not qualify.
    rejected = api.create_interlocutory_sale_request(
        create_isr_payload(
            personal["id"], fresh_asset_version(personal["id"]),
            justification="carrying cost burn",
        ),
        make_asset_manager_headers(ASSET_MANAGER_USER_ID),
    )
    validate_error(rejected, ApiErrorId.ERR_RATIO_BELOW_THRESHOLD)
    assert rejected.status_code == 422

    rows, meta = validate_paginated(
        api.list_asset_interlocutory_sale_requests(
            personal["id"], TEST_USERS["asset_manager_headers"]
        )
    )
    assert rows == [] and meta["total_count"] == 0, (
        "a ratio-rejected request must not be persisted"
    )


def test_ratio_exactly_at_threshold_eligible(api):
    """PRD §3.4: "The comparison is computed in integer form, and the
    boundary is inclusive: a burden sitting exactly at thirty percent of
    value qualifies, while anything below rejects the request with
    `ERR_RATIO_BELOW_THRESHOLD`."
    PRD §3.4: "the server snapshots the figures the court will review —
    `accumulated_costs_snapshot_cents` from the asset's accumulator,
    `projected_burden_cents` as that snapshot plus the three-month
    projection, and `appraised_value_snapshot_cents` from the asset's current
    appraised value"

    Design: Difficulty/boundary_precision_check/ratio_exactly_at_threshold_eligible
    """
    case = create_case(
        case_number="26-MJ-0011", judicial_district="D. Or.",
        forfeiture_type="CIVIL", lead_agency_code="USMS",
    )
    exact, _ = create_valued_asset(
        case["id"], raw_value_cents=500_000, grade="EXCELLENT",
        method="BLUE_BOOK", description="sedan E",
    )
    post_expense(
        exact["id"], 45_000, entry_kind="COST", expense_type="STORAGE",
        incurred_on="2026-09-02T00:00:00Z",
    )
    post_expense(
        exact["id"], 30_000, entry_kind="COST", expense_type="INSURANCE",
        incurred_on="2026-09-02T01:00:00Z",
    )
    short, _ = create_valued_asset(
        case["id"], raw_value_cents=500_000, grade="EXCELLENT",
        method="BLUE_BOOK", description="sedan F",
    )
    post_expense(
        short["id"], 74_999, entry_kind="COST", expense_type="STORAGE",
        incurred_on="2026-09-02T00:00:00Z",
    )

    # (75000 + 3 x 25000) x 100 == 30 x 500000: the inclusive boundary admits.
    isr = create_isr(exact["id"], justification="exactly at threshold")
    assert isr["status"] == "PENDING"
    assert isr["projected_burden_cents"] == 150_000
    assert isr["appraised_value_snapshot_cents"] == 500_000

    # (74999 + 75000) x 100 < 30 x 500000: one cent short flips the outcome.
    rejected = api.create_interlocutory_sale_request(
        create_isr_payload(
            short["id"], fresh_asset_version(short["id"]),
            justification="one cent short",
        ),
        TEST_USERS["asset_manager_headers"],
    )
    validate_error(rejected, ApiErrorId.ERR_RATIO_BELOW_THRESHOLD)
    assert rejected.status_code == 422


def test_isr_requires_asset_valued(api):
    """PRD §3.4: "The asset's `legal_state` must be `VALUED` or
    `DISPOSITION_REVIEW` (`ERR_INVALID_STATE` otherwise)"
    PRD §3.3: "an acceptance while `VALUATION_PENDING` advances the asset to
    `VALUED`".

    Design: Difficulty/cross_entity_state_dependency/isr_requires_asset_valued
    """
    case = create_case(
        case_number="26-MJ-0013", judicial_district="D. Utah",
        forfeiture_type="CIVIL", lead_agency_code="ATF",
    )
    asset = intake_asset(
        case["id"], asset_type="VEHICLE", description="flatbed",
        seized_on="2026-09-01T00:00:00Z", seizure_condition_grade="EXCELLENT",
    )
    valuation = submit_valuation(
        asset["id"], method="BLUE_BOOK", raw_value_cents=400_000,
        assessed_condition_grade="EXCELLENT",
    )
    post_expense(
        asset["id"], 60_000, entry_kind="COST", expense_type="STORAGE",
        incurred_on="2026-09-02T00:00:00Z",
    )

    early = api.create_interlocutory_sale_request(
        create_isr_payload(
            asset["id"], fresh_asset_version(asset["id"]),
            justification="too early",
        ),
        make_asset_manager_headers(ASSET_MANAGER_USER_ID),
    )
    validate_error(early, ApiErrorId.ERR_INVALID_STATE)
    assert early.status_code == 409, (
        "legal_state VALUATION_PENDING is not a valid from-state"
    )

    accept_valuation(valuation["id"])
    isr = create_isr(asset["id"], justification="now timely")
    assert isr["status"] == "PENDING"
    assert isr["projected_burden_cents"] == 135_000


def test_isr_state_beats_fiscal(api):
    """PRD §2.10: "Every request is evaluated against an ordered pipeline of
    checks, and the first failure wins: the response carries the error of the
    earliest tier that fails, and later tiers are never consulted."
    PRD §2.10: "6. **State preconditions**" precede "9. **Fiscal rules**".
    PRD §3.4: "The asset's `legal_state` must be `VALUED` or
    `DISPOSITION_REVIEW` (`ERR_INVALID_STATE` otherwise)"

    Design: Difficulty/priority_pair_validation_conflict/isr_state_beats_fiscal
    """
    case = create_case(
        case_number="26-MJ-0009", judicial_district="D. Colo.",
        forfeiture_type="CIVIL", lead_agency_code="DEA",
    )
    asset, _valuation = create_valued_asset(
        case["id"], raw_value_cents=500_000, grade="EXCELLENT",
        method="BLUE_BOOK", description="hatchback",
    )
    dismiss_case(case["id"])
    returned = get_asset(asset["id"])
    assert returned["legal_state"] == "RETURN_PENDING"
    assert returned["accumulated_net_holding_cost_cents"] == 0, (
        "projected burden 75000 < 150000: the fiscal gate would also fail "
        "if it were reached"
    )

    resp = api.create_interlocutory_sale_request(
        create_isr_payload(
            asset["id"], returned["version"], justification="both gates fail",
        ),
        make_asset_manager_headers(ASSET_MANAGER_USER_ID),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert resp.status_code == 409, (
        "state (tier 6) outranks fiscal (tier 9): ERR_INVALID_STATE wins "
        "over ERR_RATIO_BELOW_THRESHOLD"
    )


def test_isr_approval_cascade(api):
    """PRD §3.4: "An approval fires the three-link interlocutory cascade on
    the asset: link 1 moves `legal_state` to `SALE_AUTHORIZED` (from `VALUED`
    or `DISPOSITION_REVIEW`), moves `custody_state` to `RELEASED_FOR_SALE`,
    and sets `retention_decision` to `SELL`; link 2, caused by the custody
    release, cancels every `SCHEDULED` custody transfer of the asset to
    `CANCELLED`; link 3, caused by the legal advance, removes the asset from
    the holding-review sweep's input set, since the sweep only scans the
    pre-authorization legal states."

    Design: Difficulty/transitive_cascade/isr_approval_cascade
    """
    case = create_case(
        case_number="26-MJ-0007", judicial_district="S.D. Fla.",
        forfeiture_type="CIVIL", lead_agency_code="USMS",
    )
    asset, _valuation = create_valued_asset(
        case["id"], raw_value_cents=500_000, grade="EXCELLENT",
        method="BLUE_BOOK", description="tow truck",
    )
    t1 = schedule_transfer(
        asset["id"], to_location_kind="STORAGE", from_location_ref="impound-2",
        to_location_ref="warehouse-9",
        window_start="2026-09-01T08:00:00Z", window_end="2026-09-02T08:00:00Z",
    )
    complete_transfer(t1["id"], "EXCELLENT")
    t2 = schedule_transfer(
        asset["id"], to_location_kind="MAINTENANCE_SHOP",
        from_location_ref="warehouse-9", to_location_ref="shop-1",
        window_start="2026-09-02T08:00:00Z", window_end="2026-09-03T08:00:00Z",
    )
    post_expense(
        asset["id"], 75_000, entry_kind="COST", expense_type="STORAGE",
        incurred_on="2026-09-02T12:00:00Z",
    )

    set_clock("2026-09-15T00:00:00Z")
    run1 = run_holding_review()
    assert run1["accruals_posted"] == 1, (
        "the September sweep covers this asset before approval"
    )

    isr = create_isr(asset["id"], justification="burn equals 30 pct of value")
    approved = adjudicate_isr(isr["id"], "APPROVE")
    assert approved["status"] == "APPROVED"

    after = get_asset(asset["id"])
    assert after["legal_state"] == "SALE_AUTHORIZED"
    assert after["custody_state"] == "RELEASED_FOR_SALE"
    assert after["retention_decision"] == "SELL"

    transfers, _ = validate_paginated(
        api.list_asset_custody_transfers(
            asset["id"], TEST_USERS["fund_administrator_headers"]
        )
    )
    by_id = {row["id"]: row for row in transfers}
    assert by_id[t1["id"]]["status"] == "COMPLETED"
    assert by_id[t2["id"]]["status"] == "CANCELLED", (
        "link 2: the custody release cancels the SCHEDULED transfer"
    )

    set_clock("2026-10-02T00:00:00Z")
    run2 = run_holding_review()
    assert run2["accruals_posted"] == 0, (
        "link 3: SALE_AUTHORIZED excludes the asset from the October sweep"
    )

    entries, _ = validate_paginated(
        api.list_asset_expense_entries(
            asset["id"], TEST_USERS["fund_administrator_headers"]
        )
    )
    accruals = [e for e in entries if e["source"] == "SYSTEM_ACCRUAL"]
    assert len(accruals) == 1
    assert accruals[0]["amount_cents"] == 25_000
    assert accruals[0]["expense_type"] == "STORAGE_ACCRUAL"


def test_isr_requester_cannot_adjudicate_own_request(api):
    """PRD §3.4: "the adjudicator's `X-User-ID` must differ from the recorded
    `requested_by_user_id`, and a self-adjudication is rejected with
    `ERR_SOD_VIOLATION`."
    PRD §3.4: "Either way, the adjudicator is recorded as
    `adjudicated_by_user_id` and the request's `version` increments."

    Design: Corner/rbac/isr_requester_cannot_adjudicate_own_request
    """
    case = create_case(
        case_number="26-MJ-1032", judicial_district="D. Utah",
        forfeiture_type="CIVIL", lead_agency_code="ATF",
    )
    asset, _valuation = create_valued_asset(
        case["id"], raw_value_cents=400_000, grade="EXCELLENT",
        method="BLUE_BOOK", description="dump truck",
    )
    post_expense(
        asset["id"], 60_000, entry_kind="COST", expense_type="STORAGE",
        incurred_on="2026-09-02T00:00:00Z",
    )
    isr = create_isr(
        asset["id"], justification="burn",
        requester_user_id=ASSET_MANAGER_USER_ID,
    )

    # A CourtOfficial whose X-User-ID equals the requester's: SoD compares
    # person, not role.
    sod = api.adjudicate_interlocutory_sale_request(
        isr["id"], "APPROVE",
        make_court_official_headers(ASSET_MANAGER_USER_ID),
    )
    validate_error(sod, ApiErrorId.ERR_SOD_VIOLATION)
    assert sod.status_code == 403

    rows, _ = validate_paginated(
        api.list_asset_interlocutory_sale_requests(
            asset["id"], TEST_USERS["court_official_headers"]
        )
    )
    assert rows[0]["status"] == "PENDING", (
        "the SoD rejection leaves the request pending"
    )

    approved = adjudicate_isr(
        isr["id"], "APPROVE", adjudicator_user_id=COURT_OFFICIAL_USER_ID
    )
    assert approved["status"] == "APPROVED"
    assert approved["adjudicated_by_user_id"] == COURT_OFFICIAL_USER_ID
    assert approved["requested_by_user_id"] == ASSET_MANAGER_USER_ID
