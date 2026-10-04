"""Profit period tests: variant computation, tier straddle, conservation,
reopen cycle, reference errors, OCC, temporal gates, and finalized reads."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    create_active_restaurant,
    create_open_period,
    create_partner,
    post_line_item,
    compute_period,
    finalize_period,
    current_period_version,
    setup_active_contract,
    setup_finalized_period,
    setup_dispute_under_review,
    set_clock,
    make_managing_partner_headers,
    TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]
HR = TEST_USERS["hr_recruiter_headers"]
CONTROLLER = TEST_USERS["corporate_controller_headers"]
AUDITOR = TEST_USERS["operations_auditor_headers"]


def test_period_create_unknown_restaurant_reference_not_found(api):
    """PRD §2.5 item 4: "Body reference existence — foreign keys supplied in
    the request body (partner_id, restaurant_id, market_group_id,
    source_period_id, profit_period_id, cut_code) must resolve to existing
    resources (ERR_REFERENCE_NOT_FOUND)."

    Design: Corner/entities/period_create_references_unknown_restaurant_returns_reference_not_found
    """
    set_clock("2026-09-01T00:00:00Z")
    resp = api.create_profit_period(
        {
            "restaurant_id": "00000000-0000-0000-0000-000000000000",
            "period_start_date": "2027-01-01",
            "period_end_date": "2027-02-01",
        },
        AUDITOR,
    )
    validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND)


def test_profit_provisional_includes_open_items_final_drops_them(api):
    """PRD §2.9: "The provisional variant, run by the compute action, includes
    line items in either PROVISIONAL or FINALIZED entry status and reads each
    item's amount_cents. The final variant, run by the finalize action,
    includes only FINALIZED line items and reads each item's
    actual_amount_cents."
    PRD §2.9: "CORPORATE_ADMIN_FEE items are the excluded corporate charge —
    their basis is EXCLUDED and they are skipped entirely in both variants."

    Design: Difficulty/dual_variant_calc/profit_provisional_includes_open_items_final_drops_them
    """
    setup = setup_active_contract()
    period = create_open_period(setup["restaurant"]["id"], "2027-01-01", "2027-02-01")
    set_clock("2027-01-10T00:00:00Z")
    post_line_item(period["id"], "REVENUE", 10000000, "FINALIZED")
    labor = post_line_item(period["id"], "LABOR", 3000000, "PROVISIONAL")
    post_line_item(period["id"], "COST_OF_GOODS", 2000000, "FINALIZED")
    post_line_item(period["id"], "CORPORATE_ADMIN_FEE", 500000, "FINALIZED")
    computed = compute_period(period["id"])
    assert computed["status"] == "COMPUTED"
    assert computed["provisional_profit_cents"] == 5000000

    validate_success(
        api.finalize_line_item(labor["id"], {"actual_amount_cents": 3100000}, AUDITOR)
    )
    finalized = finalize_period(period["id"])
    assert finalized["final_distributable_profit_cents"] == 4900000
    assert finalized["provisional_profit_cents"] != finalized["final_distributable_profit_cents"]
    # 5000000 provisional - 4900000 final == 100000 actualization delta.


def test_profit_final_variant_ignores_provisional_items(api):
    """PRD §2.9: "The **final variant**, run by the finalize action, includes
    only `FINALIZED` line items and reads each item's `actual_amount_cents`."
    PRD §3.6: "It requires that no line item on the period remains
    `PROVISIONAL` — any unfinalized item blocks with
    `ERR_UNFINALIZED_LINE_ITEMS`."

    Design: Difficulty/dual_variant_calc/profit_provisional_includes_open_items_final_drops_them
    """
    setup = setup_active_contract()
    period = create_open_period(setup["restaurant"]["id"], "2027-01-01", "2027-02-01")
    set_clock("2027-01-10T00:00:00Z")
    post_line_item(period["id"], "REVENUE", 10000000, "FINALIZED")
    labor = post_line_item(period["id"], "LABOR", 3000000, "PROVISIONAL")
    computed = compute_period(period["id"])
    # Provisional variant counts the PROVISIONAL labor estimate.
    assert computed["provisional_profit_cents"] == 7000000
    # Actualizing the estimate downward widens the final profit by the delta.
    validate_success(
        api.finalize_line_item(labor["id"], {"actual_amount_cents": 2500000}, AUDITOR)
    )
    finalized = finalize_period(period["id"])
    assert finalized["final_distributable_profit_cents"] == 7500000
    assert finalized["provisional_profit_cents"] == 7000000


def test_line_item_partner_basis_computed_not_client_supplied(api):
    """PRD §3.5: "Every line item also carries a computed partner_basis per
    §2.9: EXCLUDED for CORPORATE_ADMIN_FEE — the excluded corporate charge that
    partners never bear — and INCLUDED for every other category."
    PRD §3.5: "A line item posted as `PROVISIONAL` carries its estimate in
    `amount_cents`, and its `actual_amount_cents` equals `amount_cents` until
    it is finalized."

    Design: Corner/entities/line_item_partner_basis_computed_not_client_supplied
    """
    setup = setup_active_contract()
    period = create_open_period(setup["restaurant"]["id"], "2027-01-01", "2027-02-01")
    set_clock("2027-01-10T00:00:00Z")
    admin_fee = post_line_item(period["id"], "CORPORATE_ADMIN_FEE", 100000, "FINALIZED")
    labor = post_line_item(period["id"], "LABOR", 100000, "FINALIZED")
    assert admin_fee["partner_basis"] == "EXCLUDED"
    assert labor["partner_basis"] == "INCLUDED"
    assert admin_fee["entry_status"] == "FINALIZED"
    assert admin_fee["actual_amount_cents"] == admin_fee["amount_cents"]
    assert labor["actual_amount_cents"] == labor["amount_cents"]


def test_partner_share_marginal_tier_straddle(api):
    """PRD §3.6: "partner_share_cents — the tiered managing partner share. The
    tiers are marginal, not average-rate: 8% of the first 5,000,000 cents of
    final profit, 10% of the next band up to 10,000,000 cents, and 12% of
    everything above 10,000,000 cents."
    PRD §3.6: "corporate_retained_cents — the remainder bucket: the final
    distributable profit minus the partner share minus the market override."

    Design: Difficulty/combinatorial_formula/partner_share_marginal_tier_straddle
    """
    setup = setup_active_contract()
    period = create_open_period(setup["restaurant"]["id"], "2027-04-01", "2027-05-01")
    set_clock("2027-04-15T00:00:00Z")
    post_line_item(period["id"], "REVENUE", 15000000, "FINALIZED")
    post_line_item(period["id"], "LABOR", 3000000, "FINALIZED")
    compute_period(period["id"])
    finalized = finalize_period(period["id"])
    assert finalized["final_distributable_profit_cents"] == 12000000
    # Marginal tiers: 400000 + 500000 + 240000 = 1140000 (NOT 12% flat).
    assert finalized["partner_share_cents"] == 1140000
    assert finalized["market_override_cents"] == 0
    assert finalized["corporate_retained_cents"] == 10860000


def test_partner_share_stops_at_tier1_boundary(api):
    """PRD §3.6: "partner_share_cents — the tiered managing partner share. The
    tiers are marginal, not average-rate: 8% of the first 5,000,000 cents of
    final profit, 10% of the next band up to 10,000,000 cents, and 12% of
    everything above 10,000,000 cents."
    PRD §3.6: "corporate_retained_cents — the remainder bucket: the final
    distributable profit minus the partner share minus the market override.
    This allocation conservation invariant always holds."

    Design: Difficulty/combinatorial_formula/partner_share_marginal_tier_straddle
    """
    setup = setup_active_contract()
    period = create_open_period(setup["restaurant"]["id"], "2027-04-01", "2027-05-01")
    set_clock("2027-04-15T00:00:00Z")
    post_line_item(period["id"], "REVENUE", 5000000, "FINALIZED")
    compute_period(period["id"])
    finalized = finalize_period(period["id"])
    assert finalized["final_distributable_profit_cents"] == 5000000
    # Exactly at the tier-1 cap: only the 8% tier engages.
    assert finalized["partner_share_cents"] == 400000
    assert finalized["corporate_retained_cents"] == 4600000


def test_negative_profit_yields_zero_share_and_zero_override(api):
    """PRD §3.6: "When the final profit is zero or negative, the partner share
    is zero."
    PRD §3.8: "Under PER_RESTAURANT_POSITIVE, the override is the override_pct
    percentage of this restaurant's own positive profit — the final
    distributable profit floored at zero — rounded half-up."
    PRD §3.6: "This allocation conservation invariant always holds."

    Design: Corner/calculations/negative_profit_yields_zero_share_and_zero_override
    """
    from test_helpers import (
        create_active_market_group_with_restaurants,
        create_and_activate_agreement,
    )

    group, restaurants = create_active_market_group_with_restaurants(num_restaurants=2)
    setup = setup_active_contract(restaurant_id=restaurants[0]["id"])
    create_and_activate_agreement(
        group["id"], coverage_start_date="2027-01-01", coverage_end_date="2027-12-31"
    )
    period = create_open_period(restaurants[0]["id"], "2027-02-01", "2027-03-01")
    set_clock("2027-02-15T00:00:00Z")
    post_line_item(period["id"], "REVENUE", 1000000, "FINALIZED")
    post_line_item(period["id"], "LABOR", 3000000, "FINALIZED")
    compute_period(period["id"])
    finalized = finalize_period(period["id"])
    assert finalized["final_distributable_profit_cents"] == -2000000
    assert finalized["partner_share_cents"] == 0
    assert finalized["market_override_cents"] == 0
    assert finalized["corporate_retained_cents"] == -2000000


def test_compute_requires_active_family_contract_on_restaurant(api):
    """PRD §3.6: "Two referential gates apply: the restaurant must be ACTIVE
    (ERR_RESTAURANT_NOT_ACTIVE), and a contract for the restaurant must exist
    in ACTIVE, RENEWAL_OFFERED, or BUYOUT_PENDING
    (ERR_NO_ACTIVE_CONTRACT_FOR_RESTAURANT)."

    Design: Difficulty/cross_entity_state_dependency/compute_requires_active_family_contract_on_restaurant
    """
    set_clock("2026-09-01T00:00:00Z")
    partner = create_partner()
    restaurant = create_active_restaurant()
    from test_helpers import create_draft_contract, submit_contract

    contract = create_draft_contract(partner["id"], restaurant["id"])
    submit_contract(contract["id"])  # PENDING_FUNDING only, never activated
    period = create_open_period(restaurant["id"], "2027-01-01", "2027-02-01")
    set_clock("2027-01-10T00:00:00Z")
    post_line_item(period["id"], "REVENUE", 5000000, "FINALIZED")
    resp = api.compute_period(
        period["id"],
        {"expected_profit_period_version": current_period_version(period["id"])},
        AUDITOR,
    )
    validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_CONTRACT_FOR_RESTAURANT)
    fetched = validate_success(api.get_profit_period(period["id"], AUDITOR))
    assert fetched["status"] == "OPEN"


def test_compute_rejected_when_restaurant_has_no_contract(api):
    """PRD §3.6: "Two referential gates apply: the restaurant must be ACTIVE
    (ERR_RESTAURANT_NOT_ACTIVE), and a contract for the restaurant must exist
    in ACTIVE, RENEWAL_OFFERED, or BUYOUT_PENDING
    (ERR_NO_ACTIVE_CONTRACT_FOR_RESTAURANT)."

    Design: Difficulty/cross_entity_state_dependency/compute_requires_active_family_contract_on_restaurant
    """
    set_clock("2026-09-01T00:00:00Z")
    restaurant = create_active_restaurant()
    period = create_open_period(restaurant["id"], "2027-01-01", "2027-02-01")
    set_clock("2027-01-10T00:00:00Z")
    post_line_item(period["id"], "REVENUE", 5000000, "FINALIZED")
    resp = api.compute_period(
        period["id"],
        {"expected_profit_period_version": current_period_version(period["id"])},
        AUDITOR,
    )
    validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_CONTRACT_FOR_RESTAURANT)
    fetched = validate_success(api.get_profit_period(period["id"], AUDITOR))
    assert fetched["status"] == "OPEN"


def test_profit_period_half_open_adjacency_allowed(api):
    """PRD §3.5: "Periods of one restaurant may not overlap: a new period
    whose half-open interval intersects any existing non-LOCKED period of the
    same restaurant is rejected with ERR_PERIOD_OVERLAP; half-open adjacency —
    one period's start equal to another's end — is allowed."

    Design: Difficulty/resource_temporal_overlap/profit_period_half_open_adjacency_allowed
    """
    set_clock("2026-09-01T00:00:00Z")
    restaurant = create_active_restaurant()
    create_open_period(restaurant["id"], "2027-01-01", "2027-02-01")
    adjacent = validate_success(
        api.create_profit_period(
            {
                "restaurant_id": restaurant["id"],
                "period_start_date": "2027-02-01",
                "period_end_date": "2027-03-01",
            },
            AUDITOR,
        ),
        expected_status=201,
    )
    assert adjacent["status"] == "OPEN"
    resp = api.create_profit_period(
        {
            "restaurant_id": restaurant["id"],
            "period_start_date": "2027-01-31",
            "period_end_date": "2027-03-01",
        },
        AUDITOR,
    )
    validate_error(resp, ApiErrorId.ERR_PERIOD_OVERLAP)
    _, meta = validate_paginated(
        api.list_profit_periods(AUDITOR, params={"restaurant_id": restaurant["id"]})
    )
    assert meta["total_count"] == 2


def test_contained_period_creation_after_lock_rejected(api):
    """PRD §3.5: "Periods of one restaurant may not overlap: a new period
    whose half-open interval intersects any existing non-LOCKED period of the
    same restaurant is rejected with ERR_PERIOD_OVERLAP; half-open adjacency —
    one period's start equal to another's end — is allowed."

    Design: Difficulty/resource_temporal_overlap/profit_period_half_open_adjacency_allowed
    """
    set_clock("2026-09-01T00:00:00Z")
    restaurant = create_active_restaurant()
    create_open_period(restaurant["id"], "2027-01-01", "2027-02-01")
    resp = api.create_profit_period(
        {
            "restaurant_id": restaurant["id"],
            "period_start_date": "2027-01-15",
            "period_end_date": "2027-01-20",
        },
        AUDITOR,
    )
    validate_error(resp, ApiErrorId.ERR_PERIOD_OVERLAP)


def test_period_terminal_lockdown_locked_rejects_everything(api):
    """PRD §3.6: "Locking is terminal. A `CorporateController` locks a
    `FINALIZED` period, but only while no dispute on the period sits in
    `SUBMITTED`, `UNDER_REVIEW`, `EVIDENCE_REQUESTED`, or `ESCALATED` —
    otherwise the lock is rejected with `ERR_OPEN_DISPUTE_BLOCKS_LOCK`."
    PRD §2.5 item 5: "State — the target resource must be in a from-state that
    permits the requested transition (`ERR_INVALID_STATE`)"
    PRD §3.5: "While a period is `OPEN`, the `OperationsAuditor` posts statement
    line items to it."

    Design: Corner/state_machines/period_terminal_lockdown_locked_rejects_everything
    """
    setup = setup_finalized_period(line_items=[("REVENUE", 5000000)])
    validate_success(api.lock_period(setup["period"]["id"], CONTROLLER))
    resp_lock = api.lock_period(setup["period"]["id"], CONTROLLER)
    validate_error(resp_lock, ApiErrorId.ERR_INVALID_STATE)
    resp_item = api.post_line_item(
        setup["period"]["id"],
        {
            "category": "REVENUE",
            "amount_cents": 1,
            "entry_status": "FINALIZED",
            "expected_profit_period_version": current_period_version(setup["period"]["id"]),
        },
        AUDITOR,
    )
    validate_error(resp_item, ApiErrorId.ERR_INVALID_STATE)
    fetched = validate_success(api.get_profit_period(setup["period"]["id"], AUDITOR))
    assert fetched["status"] == "LOCKED"


def test_unfinalized_line_items_block_finalize(api):
    """PRD §3.6: "It requires that no line item on the period remains
    PROVISIONAL — any unfinalized item blocks with ERR_UNFINALIZED_LINE_ITEMS."

    Design: Corner/validations/unfinalized_line_items_block_finalize
    """
    setup = setup_active_contract()
    period = create_open_period(setup["restaurant"]["id"], "2027-04-01", "2027-05-01")
    set_clock("2027-04-15T00:00:00Z")
    post_line_item(period["id"], "REVENUE", 5000000, "FINALIZED")
    labor = post_line_item(period["id"], "LABOR", 1000000, "PROVISIONAL")
    compute_period(period["id"])
    resp = api.finalize_period(period["id"], CONTROLLER)
    validate_error(resp, ApiErrorId.ERR_UNFINALIZED_LINE_ITEMS)
    fetched = validate_success(api.get_profit_period(period["id"], AUDITOR))
    assert fetched["status"] == "COMPUTED"
    validate_success(api.finalize_line_item(labor["id"], {"actual_amount_cents": 1000000}, AUDITOR))
    finalized = finalize_period(period["id"])
    assert finalized["status"] == "FINALIZED"
    assert finalized["final_distributable_profit_cents"] == 4000000


def test_line_item_post_after_period_end_date_rejected(api):
    """PRD §3.5: "Posting is rejected once the logical clock's date has passed
    the period_end_date, with ERR_PERIOD_CLOSED_FOR_ENTRIES; posting also
    requires the period to be OPEN."

    Design: Corner/validations/line_item_post_after_period_end_date_rejected
    """
    setup = setup_active_contract()
    period = create_open_period(setup["restaurant"]["id"], "2027-01-01", "2027-02-01")
    set_clock("2027-02-15T00:00:00Z")
    resp = api.post_line_item(
        period["id"],
        {
            "category": "REVENUE",
            "amount_cents": 100,
            "entry_status": "FINALIZED",
            "expected_profit_period_version": current_period_version(period["id"]),
        },
        AUDITOR,
    )
    validate_error(resp, ApiErrorId.ERR_PERIOD_CLOSED_FOR_ENTRIES)
    _, meta = validate_paginated(api.list_line_items(period["id"], AUDITOR))
    assert meta["total_count"] == 0


def test_line_item_finalize_actualizes_amount(api):
    """PRD §3.5: "The OperationsAuditor finalizes a provisional line item by
    recording its actual_amount_cents, which moves the item's entry_status
    from PROVISIONAL to FINALIZED. Final profit accounting reads only these
    actualized figures."
    PRD §2.5 item 5: "State — the target resource must be in a from-state that
    permits the requested transition (ERR_INVALID_STATE) ..."

    Design: Corner/endpoints/line_item_finalize_actualizes_amount
    """
    setup = setup_active_contract()
    period = create_open_period(setup["restaurant"]["id"], "2027-01-01", "2027-02-01")
    set_clock("2027-01-10T00:00:00Z")
    labor = post_line_item(period["id"], "LABOR", 1000000, "PROVISIONAL")
    finalized = validate_success(
        api.finalize_line_item(labor["id"], {"actual_amount_cents": 1234567}, AUDITOR)
    )
    assert finalized["entry_status"] == "FINALIZED"
    assert finalized["actual_amount_cents"] == 1234567
    assert finalized["amount_cents"] == 1000000
    resp = api.finalize_line_item(labor["id"], {"actual_amount_cents": 9}, AUDITOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_stale_occ_version_rejected_412(api):
    """PRD §2.7: "Posting a statement line item to a profit period requires
    `expected_profit_period_version`, matching the period's current `version`.
    If another writer has advanced the period's version since the client last
    read it — for example by posting a line item of their own — the posting
    client's computed subtotal context is stale and the create is rejected."
    PRD §2.7: "a mismatch with the parent entity's current `version` is
    rejected with `ERR_STALE_VERSION` (HTTP 412)"

    Design: Corner/errors/stale_occ_version_rejected_412
    """
    setup = setup_active_contract()
    period = create_open_period(setup["restaurant"]["id"], "2027-01-01", "2027-02-01")
    set_clock("2027-01-10T00:00:00Z")
    captured_version = period["version"]
    post_line_item(period["id"], "REVENUE", 100, "FINALIZED")  # advances version
    resp = api.post_line_item(
        period["id"],
        {
            "category": "REVENUE",
            "amount_cents": 200,
            "entry_status": "FINALIZED",
            "expected_profit_period_version": captured_version,
        },
        AUDITOR,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    _, meta = validate_paginated(api.list_line_items(period["id"], AUDITOR))
    assert meta["total_count"] == 1


def test_compute_read_profit_period_summary_fields(api):
    """PRD §3.6: "Finalization also stamps `finalized_at` with the logical
    clock and computes `dispute_deadline` as exactly 30 days after
    `finalized_at`."
    PRD §3.8: "When no such agreement exists, `market_override_cents` is 0."
    PRD §3.4: "every profit period whose accrued share was swept into the
    order has its `partner_share_paid` set to true, so a period's share can
    never be paid out twice."

    Design: Corner/endpoints/compute_read_profit_period_summary_fields
    """
    setup = setup_finalized_period(
        line_items=[("REVENUE", 8000000), ("LABOR", 2000000)],
        clock_at="2027-04-15T00:00:00Z",
    )
    data = validate_success(api.get_profit_period(setup["period"]["id"], CONTROLLER))
    assert data["status"] == "FINALIZED"
    assert data["final_distributable_profit_cents"] == 6000000
    assert data["partner_share_cents"] == 500000
    assert data["finalized_at"] == "2027-04-15T00:00:00.000Z"
    assert data["dispute_deadline"] == "2027-05-15T00:00:00.000Z"
    assert data["partner_share_paid"] is False
    assert data["market_override_cents"] == 0
    assert data["provisional_profit_cents"] == 6000000


def test_allocation_conservation_negative_profit(api):
    """PRD §3.6: "corporate_retained_cents — the remainder bucket: the final
    distributable profit minus the partner share minus the market override.
    This allocation conservation invariant always holds."
    PRD §3.6: "When the final profit is zero or negative, the partner share is
    zero."

    Design: Difficulty/compensating_invariant/allocation_conservation_across_finalize
    """
    setup = setup_active_contract()
    period = create_open_period(setup["restaurant"]["id"], "2027-04-01", "2027-05-01")
    set_clock("2027-04-15T00:00:00Z")
    post_line_item(period["id"], "REVENUE", 1000000, "FINALIZED")
    post_line_item(period["id"], "LABOR", 3000000, "FINALIZED")
    compute_period(period["id"])
    finalized = finalize_period(period["id"])
    assert finalized["final_distributable_profit_cents"] == -2000000
    assert (
        finalized["partner_share_cents"]
        + finalized["market_override_cents"]
        + finalized["corporate_retained_cents"]
        == finalized["final_distributable_profit_cents"]
    )


def test_immediate_consistency_finalize_visible_in_same_read(api):
    """PRD §2.8: "The system's entities are peers joined by foreign keys
    rather than nested URL hierarchies, but mutations still propagate across
    aggregate boundaries, and every propagation is explicit and immediate."
    PRD §3.6: "On success, four figures are written in one step ..."

    Design: Corner/consistency_model/immediate_consistency_finalize_visible_in_same_read
    """
    setup = setup_active_contract()
    period = create_open_period(setup["restaurant"]["id"], "2027-04-01", "2027-05-01")
    set_clock("2027-04-15T00:00:00Z")
    post_line_item(period["id"], "REVENUE", 8000000, "FINALIZED")
    post_line_item(period["id"], "LABOR", 2000000, "FINALIZED")
    compute_period(period["id"])
    finalized = finalize_period(period["id"])
    assert finalized["status"] == "FINALIZED"
    assert finalized["partner_share_cents"] == 500000
    re_read = validate_success(api.get_profit_period(period["id"], CONTROLLER))
    assert re_read["final_distributable_profit_cents"] == 6000000
    assert re_read["partner_share_cents"] == 500000
    assert re_read["corporate_retained_cents"] == 5500000


def test_allocation_conservation_across_finalize(api):
    """PRD §3.6: "corporate_retained_cents — the remainder bucket: the final
    distributable profit minus the partner share minus the market override.
    This allocation conservation invariant always holds."
    PRD §3.8: "Under PER_RESTAURANT_POSITIVE, the override is the override_pct
    percentage of this restaurant's own positive profit — the final
    distributable profit floored at zero — rounded half-up."

    Design: Difficulty/compensating_invariant/allocation_conservation_across_finalize
    """
    from test_helpers import (
        create_active_market_group_with_restaurants,
        create_and_activate_agreement,
    )

    group, restaurants = create_active_market_group_with_restaurants(num_restaurants=2)
    setup = setup_active_contract(restaurant_id=restaurants[0]["id"])
    create_and_activate_agreement(
        group["id"],
        coverage_start_date="2027-01-01",
        coverage_end_date="2027-12-31",
        override_pct=5,
        basis="PER_RESTAURANT_POSITIVE",
    )
    period = create_open_period(restaurants[0]["id"], "2027-02-01", "2027-03-01")
    set_clock("2027-02-15T00:00:00Z")
    post_line_item(period["id"], "REVENUE", 9000000, "FINALIZED")
    post_line_item(period["id"], "COST_OF_GOODS", 3000000, "FINALIZED")
    compute_period(period["id"])
    finalized = finalize_period(period["id"])
    assert finalized["final_distributable_profit_cents"] == 6000000
    assert finalized["partner_share_cents"] == 500000
    assert finalized["market_override_cents"] == 300000
    assert finalized["corporate_retained_cents"] == 5200000
    assert (
        finalized["partner_share_cents"]
        + finalized["market_override_cents"]
        + finalized["corporate_retained_cents"]
        == finalized["final_distributable_profit_cents"]
    )
