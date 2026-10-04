"""Capitalization rates, market indices and forecast base selection."""

from test_helpers import (
    ApiErrorId,
    add_distinct_user,
    create_lease_comparable,
    create_property,
    create_sale_transaction,
    ensure_researching,
    get_property,
    get_success_data,
    open_enforcement_case,
    set_logical_clock,
    setup_active_contract,
    setup_provider_org,
    setup_subscriber_org,
    validate_error,
    validate_paginated,
    validate_success,
)


def _build_income_property(provider, *, income_cents=None):
    """A property carrying an optional VERIFIED in_place_income_annual_cents claim."""
    prop = create_property(
        provider["creator_headers"], market="TX-DALLAS", address_line="4100 Oak Lawn Ave",
        property_type="INDUSTRIAL", rentable_sqft=200_000, classification="CLASS_B",
    )
    if income_cents is not None:
        from test_helpers import build_verified_attribute

        build_verified_attribute(
            provider, prop["id"], field_name="in_place_income_annual_cents",
            value=str(income_cents),
            # Evidence must predate the logical clock (PRD 2.9), and the cases
            # that exercise this helper run as early as 2026-05-01.
            source_overrides={"obtained_at": "2026-04-01T00:00:00Z"},
        )
    return prop


def _subordination_ready_case(provider):
    subscriber = setup_subscriber_org(
        org_name="Cedar Point Capital Partners", service_tier="MID_MARKET",
    )
    active = setup_active_contract(
        subscriber, annual_fee_cents=100_000, seat_count=2,
        term_start="2026-05-01T00:00:00Z", term_end="2027-05-01T00:00:00Z",
        audit_intensity="ENHANCED",
    )
    case = open_enforcement_case(
        subscriber["org"]["id"], active["contract"]["id"], provider["officer_headers"],
        finding_cents=60_000_000, fee_rate_pct=1.25,
    )
    return subscriber, active, case


def test_cap_rate_uses_the_substitute_income_when_no_verified_income_exists(api):
    """PRD §3.5: "When the figure is 250,000,000 cents or lower — including the case where the property carries no verified `in_place_income_annual_cents` attribute at all, in which case the figure is read as 0 — the calculation instead takes the `substitute_income` variant: it substitutes 250,000,000 cents, the `SUBSTITUTE_INCOME_CENTS` constant, and records its income source as `SUBSTITUTE`."

    PRD §3.5: "On a five-billion-cent sale price the two variants disagree plainly: a researched income of 300,000,100 cents yields 600 basis points, while the substitute income of 250,000,000 cents yields 500."

    Design: Corner/calculations/cap_rate_uses_the_substitute_income_when_no_verified_income_exists
    """
    set_logical_clock("2026-09-01T00:00:00Z")
    provider = setup_provider_org()
    prop = _build_income_property(provider, income_cents=None)
    ensure_researching(prop["id"], provider["creator_headers"])
    tx = validate_success(
        api.create_sale_transaction(
            prop["id"],
            {"buyer_name": "Cedar Point Capital", "close_date": "2026-08-15T00:00:00Z",
             "gross_sale_price_cents": 5_000_000_000},
            provider["creator_headers"],
        ),
        201,
    )
    assert tx["cap_rate_bps"] == 500
    assert tx["subordination_status"] == "PENDING"
    assert tx["subordination_deadline"] == "2026-08-25T00:00:00Z"


def test_cap_rate_prefers_the_verified_income_above_the_substitute_threshold(api):
    """PRD §3.5: "When that verified figure is strictly greater than 250,000,000 cents, the calculation takes the `verified_income` variant: it uses the researched figure and records its income source as `VERIFIED`."

    Design: Corner/calculations/cap_rate_prefers_the_verified_income_above_the_substitute_threshold
    """
    set_logical_clock("2026-09-01T00:00:00Z")
    provider = setup_provider_org()
    prop = _build_income_property(provider, income_cents=300_000_100)
    ensure_researching(prop["id"], provider["creator_headers"])
    tx = validate_success(
        api.create_sale_transaction(
            prop["id"],
            {"buyer_name": "Cedar Point Capital", "close_date": "2026-08-15T00:00:00Z",
             "gross_sale_price_cents": 5_000_000_000},
            provider["creator_headers"],
        ),
        201,
    )
    assert tx["cap_rate_bps"] == 600


def test_cap_rate_boundary_uses_the_substitute_at_exactly_the_threshold(api):
    """PRD §3.5: "The boundary is deliberately strict: an in-place income of exactly 250,000,000 cents takes the substitute branch."

    Design: Difficulty/combinatorial_formula/cap_rate_round_per_line_then_sum_vs_sum_then_round
    """
    set_logical_clock("2026-09-01T00:00:00Z")
    provider = setup_provider_org()
    prop = _build_income_property(provider, income_cents=250_000_000)
    ensure_researching(prop["id"], provider["creator_headers"])
    tx = validate_success(
        api.create_sale_transaction(
            prop["id"],
            {"buyer_name": "Cedar Point Capital", "close_date": "2026-08-15T00:00:00Z",
             "gross_sale_price_cents": 5_000_000_000},
            provider["creator_headers"],
        ),
        201,
    )
    # The threshold comparison is strict, so exactly 250,000,000 takes the
    # substitute branch and the identical 5-billion-cent price yields 500 bps.
    assert tx["cap_rate_bps"] == 500


def test_verified_sale_value_counts_only_subordinated_transactions(api):
    """PRD §3.7: "The property is not left stale by this: its `verified_sale_value_cents` is recomputed as the sum of `gross_sale_price_cents` across that property's transactions whose `subordination_status` is `SUBORDINATED`, so the property's verified sale total only ever includes subordinated sales."

    Design: Difficulty/combinatorial_formula/cap_rate_round_per_line_then_sum_vs_sum_then_round
    """
    set_logical_clock("2026-05-01T00:00:00Z")
    provider = setup_provider_org(with_officer=True)
    prop = _build_income_property(provider, income_cents=300_000_100)
    ensure_researching(prop["id"], provider["creator_headers"])
    # close_date plus ten days must still lie ahead of the clock at 2026-05-01.
    tx_one = create_sale_transaction(
        prop["id"], provider["creator_headers"], close_date="2026-04-28T00:00:00Z",
        gross_sale_price_cents=5_000_000_000,
    )
    create_sale_transaction(
        prop["id"], provider["creator_headers"], close_date="2026-04-29T00:00:00Z",
        gross_sale_price_cents=5_000_000_000,
    )
    _, _, case = _subordination_ready_case(provider)
    subordinated = validate_success(
        api.subordinate_transaction(
            tx_one["id"],
            {"subordinating_case_id": case["id"],
             "expected_transaction_version": get_success_data(
                 api.get_sale_transaction(tx_one["id"], provider["officer_headers"])
             )["version"]},
            provider["officer_headers"],
        ),
        200,
    )
    assert subordinated["cap_rate_bps"] == 600
    assert subordinated["subordination_status"] == "SUBORDINATED"
    assert subordinated["subordinated_at"] == "2026-05-01T00:00:00Z"
    prop_after = get_property(prop["id"], provider["creator_headers"])
    assert prop_after["verified_sale_value_cents"] == 5_000_000_000


def test_identical_transactions_contribute_per_line_cap_rates_that_sum(api):
    """PRD §3.5: "One hundred times the ten-thousands scaled ratio of income to `gross_sale_price_cents` is then rounded half up to a whole number of basis points and stored as `cap_rate_bps`."

    Design: Difficulty/combinatorial_formula/cap_rate_round_per_line_then_sum_vs_sum_then_round
    """
    set_logical_clock("2026-05-01T00:00:00Z")
    provider = setup_provider_org(with_officer=True)
    prop = _build_income_property(provider, income_cents=300_000_100)
    ensure_researching(prop["id"], provider["creator_headers"])
    _, _, case = _subordination_ready_case(provider)
    caps = []
    for close_date in ("2026-04-28T00:00:00Z", "2026-04-29T00:00:00Z", "2026-04-30T00:00:00Z"):
        tx = create_sale_transaction(
            prop["id"], provider["creator_headers"], close_date=close_date,
            gross_sale_price_cents=5_000_000_000,
        )
        result = validate_success(
            api.subordinate_transaction(
                tx["id"],
                {"subordinating_case_id": case["id"],
                 "expected_transaction_version": get_success_data(
                     api.get_sale_transaction(tx["id"], provider["officer_headers"])
                 )["version"]},
                provider["officer_headers"],
            ),
            200,
        )
        caps.append(result["cap_rate_bps"])
    assert caps == [600, 600, 600]
    assert sum(caps) == 1800
    prop_after = get_property(prop["id"], provider["creator_headers"])
    assert prop_after["verified_sale_value_cents"] == 15_000_000_000


def test_index_run_over_a_single_qualifying_comparable_reports_its_mean(api):
    """PRD §3.5: "Otherwise `index_value` and `mean_effective_rent_psf` are both the arithmetic mean of the refined set's `effective_rent_psf` values, rounded half up to two decimal places, `comp_count` is the exact size of the refined set"

    Design: Difficulty/boundary_precision_check/market_index_run_on_an_empty_and_on_a_single_comparable_set
    """
    set_logical_clock("2026-05-01T00:00:00Z")
    provider = setup_provider_org()
    prop = create_property(
        provider["creator_headers"], market="TX-DALLAS", address_line="1400 Ross Ave",
        property_type="OFFICE", rentable_sqft=120_000, classification="CLASS_A",
    )
    from test_helpers import build_verified_attribute

    build_verified_attribute(
        provider, prop["id"], field_name="tenant_name", value="Harborline Logistics Inc",
        source_overrides={"obtained_at": "2026-04-01T00:00:00Z"},
    )
    validate_success(api.finalize_property(prop["id"], provider["creator_headers"]), 200)
    create_lease_comparable(
        prop["id"], provider["creator_headers"], lease_start="2026-01-01T00:00:00Z",
        lease_end="2026-12-01T00:00:00Z", effective_rent_psf=30.0,
    )
    run = validate_success(
        api.create_index_run(
            {"market": "TX-DALLAS", "window_start": "2026-01-01T00:00:00Z",
             "window_end": "2026-12-31T00:00:00Z", "adjustment_mode": "UNADJUSTED"},
            provider["creator_headers"],
        ),
        201,
    )
    assert run["comp_count"] == 1
    assert run["index_value"] == 30.00


def test_index_run_over_a_market_with_no_qualifying_comparable_is_empty(api):
    """PRD §3.5: "When the refined set is empty, the run carries no index value: `index_value` is null and `comp_count` is 0, and the endpoint reports `ERR_EMPTY_INDEX_SET` (HTTP 409)."

    PRD §3.5: "A lease comparable qualifies when its property's `market` equals the run's market, when its comparable interval overlaps the window under the half-open test `lease_start` at or before `window_end` and `lease_end` strictly after `window_start`"

    Design: Difficulty/boundary_precision_check/market_index_run_on_an_empty_and_on_a_single_comparable_set
    """
    set_logical_clock("2026-05-01T00:00:00Z")
    provider = setup_provider_org()
    nm_analyst, nm_headers = add_distinct_user(
        provider["org"]["id"], role="RESEARCH_ANALYST",
        full_name="Yusuf Adeyemi", assigned_market="NM-ALBUQUERQUE",
    )
    prop = create_property(
        nm_headers, market="NM-ALBUQUERQUE", address_line="100 Central Ave NW",
        property_type="RETAIL", rentable_sqft=15_000, classification="CLASS_C",
    )
    ensure_researching(prop["id"], nm_headers)
    # Already-expired evidence: the lease ended before the clock, so the comp is
    # admissible but cannot overlap any forward window.
    create_lease_comparable(
        prop["id"], nm_headers, tenant_name="Route 66 Trading Co",
        lease_start="2027-01-01T00:00:00Z", lease_end="2028-01-01T00:00:00Z",
        escalated_rent_psf=14.0, effective_rent_psf=13.5,
    )
    resp = api.create_index_run(
        {"market": "NM-ALBUQUERQUE", "window_start": "2026-01-01T00:00:00Z",
         "window_end": "2026-12-31T00:00:00Z", "adjustment_mode": "UNADJUSTED"},
        provider["creator_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_EMPTY_INDEX_SET)
    assert resp.status_code == 409
    runs, meta = validate_paginated(
        api.list_index_runs(provider["creator_headers"], {"market": "NM-ALBUQUERQUE"})
    )
    assert len(runs) == 0
    assert meta["total_count"] == 0


def test_index_input_set_excludes_unverified_properties(api):
    """PRD §3.5: "and when three refinements hold: the comparable's property has `research_status` `VERIFIED`; the comparable's property is not named in the request's optional `excluded_property_ids` list; and the comparable's property does not sit under `FROZEN` or `RESTRICTED` posture."

    Design: Corner/calculations/index_input_set_excludes_unverified_and_frozen_properties
    """
    set_logical_clock("2026-09-01T00:00:00Z")
    provider = setup_provider_org()
    from test_helpers import build_verified_attribute

    verified = create_property(
        provider["creator_headers"], market="TX-DALLAS", address_line="1400 Ross Ave",
        property_type="OFFICE", rentable_sqft=120_000, classification="CLASS_A",
    )
    build_verified_attribute(
        provider, verified["id"], field_name="tenant_name", value="Harborline Logistics Inc",
    )
    validate_success(api.finalize_property(verified["id"], provider["creator_headers"]), 200)
    create_lease_comparable(
        verified["id"], provider["creator_headers"], lease_start="2026-06-01T00:00:00Z",
        lease_end="2027-06-01T00:00:00Z", effective_rent_psf=32.0,
    )
    researching = create_property(
        provider["creator_headers"], market="TX-DALLAS", address_line="5000 Maple Ave",
        property_type="OFFICE", rentable_sqft=90_000, classification="CLASS_B",
    )
    ensure_researching(researching["id"], provider["creator_headers"])
    create_lease_comparable(
        researching["id"], provider["creator_headers"], tenant_name="Fulcrum Interiors LLC",
        lease_start="2026-06-01T00:00:00Z", lease_end="2027-06-01T00:00:00Z",
        escalated_rent_psf=20.0, effective_rent_psf=18.0,
    )
    run = validate_success(
        api.create_index_run(
            {"market": "TX-DALLAS", "window_start": "2026-06-01T00:00:00Z",
             "window_end": "2027-06-01T00:00:00Z", "adjustment_mode": "UNADJUSTED"},
            provider["creator_headers"],
        ),
        201,
    )
    assert run["comp_count"] == 1
    assert run["index_value"] == 32.00