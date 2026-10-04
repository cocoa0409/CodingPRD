"""Sales: serial and allocation gates, the clearance pricing engine (tiers,
coverage bands, subsidy, pinned rounding), the return cascade, and channel
attach-rate arithmetic.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    adjudicate_claim,
    create_accessory,
    create_channel,
    create_claim,
    create_sale,
    create_sale_payload,
    make_channel_rep_headers,
    refetch_allocation,
    sale_transition_payload,
    set_logical_clock,
    setup_in_season,
    setup_in_season_with_sale,
    unique_suffix,
    validate_error,
    validate_paginated,
    validate_success,
)

PLANNER = TEST_USERS["planner_admin_headers"]
AGENT = TEST_USERS["service_agent_headers"]


def _sale_raw(api, season_id, model_id, channel_id, **overrides):
    """Raw sale create as the owning ChannelRep (identity threaded, PRD 2.1)."""
    payload = create_sale_payload(season_id, model_id, channel_id, **overrides)
    return api.create_sale(payload, headers=make_channel_rep_headers(channel_id))


def test_sale_create_rejected_when_serials_length_mismatches_quantity(api):
    """PRD 3.5: "When `serials` is present its length must equal `quantity`
    (`ERR_VALIDATION`), and every serial must be globally unique across all sales,
    else `ERR_DUPLICATE_SERIAL`."

    Design: Corner/entities/sale_create_rejected_when_serials_length_mismatches_quantity
    """
    bundle = setup_in_season()
    resp = _sale_raw(api, bundle["season"]["id"], bundle["model"]["id"],
                     bundle["channel"]["id"], quantity=2, serials=["SN-ONLY-ONE"])
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_duplicate_serial_across_sales_rejected(api):
    """PRD 3.5: "When `serials` is present its length must equal `quantity`
    (`ERR_VALIDATION`), and every serial must be globally unique across all sales,
    else `ERR_DUPLICATE_SERIAL`."

    Design: Corner/validations/duplicate_serial_across_sales_rejected
    """
    bundle = setup_in_season()
    create_sale(bundle["season"]["id"], bundle["model"]["id"], bundle["channel"]["id"],
                quantity=1, serials=["SN-100"])
    resp = _sale_raw(api, bundle["season"]["id"], bundle["model"]["id"],
                     bundle["channel"]["id"], quantity=1, serials=["SN-100"])
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_SERIAL)


def test_sale_without_matching_allocation_rejected(api):
    """PRD 3.5: "an active allocation — `ACCEPTED` or `PARTIALLY_CONSUMED` — must
    exist for the (season, channel, model) tuple, else `ERR_NO_ACTIVE_ALLOCATION`."

    Design: Corner/validations/sale_without_matching_allocation_rejected
    """
    bundle = setup_in_season(channel_over={"name": "CH-A"})
    ch_b = create_channel(name="CH-B", channel_type="SPECIALTY_DEALER",
                          allocation_priority=20, credit_limit_cents=100000000)
    resp = _sale_raw(api, bundle["season"]["id"], bundle["model"]["id"], ch_b["id"], quantity=1)
    validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_ALLOCATION)


def test_sale_return_cascades_open_claims_to_denied(api):
    """PRD 3.5: "Four things happen together: the live allocation for the (season,
    channel, model) tuple — `ACCEPTED`, `PARTIALLY_CONSUMED`, or `CONSUMED` — has its
    `committed_units` reduced by the returned `quantity` ... and every warranty claim
    of this sale still in flight — `SUBMITTED`, `UNDER_REVIEW`, `INFO_REQUESTED`,
    `ESCALATED`, or `REOPENED` — is force-denied, moving to `DENIED` with `denied_at`
    stamped from the logical clock."
    PRD 3.5: "The denominator counts the channel's sales in `SOLD` or `REGISTERED` —
    `RETURNED` sales are excluded from both numerator and denominator."

    Design: Corner/state_machines/sale_return_cascades_open_claims_to_denied
    """
    bundle = setup_in_season_with_sale(
        accessories=[create_accessory(sku="CVR-1", accessory_type="COVER", unit_price_cents=1999)])
    sale, channel, allocation = bundle["sale"], bundle["channel"], bundle["allocation"]
    claim = create_claim(sale["id"], component="BURNER", failure_description="Burner failed")
    adjudicate_claim(claim["id"], "REVIEW")  # claim now UNDER_REVIEW (in flight)
    returned = validate_success(api.transition_sale(
        sale["id"], sale_transition_payload("RETURN"),
        headers=make_channel_rep_headers(channel["id"])), 200)
    assert returned["status"] == "RETURNED"
    claims, _m1 = validate_paginated(api.list_sale_warranty_claims(sale["id"], headers=AGENT))
    assert claims[0]["status"] == "DENIED", f"the in-flight claim must be force-denied, got {claims[0]['status']}"
    alloc_after = refetch_allocation(allocation["id"])
    assert alloc_after["committed_units"] == 0, "committed units are restored to the reservation"
    channel_after = validate_success(api.get_channel(channel["id"], headers=PLANNER), 200)
    assert float(channel_after["accessory_attach_rate"]) == 0.0, (
        "the only sale left the denominator; an empty denominator reports exactly 0.0000"
    )


def test_clearance_price_tier_coverage_subsidy_composition(api):
    """PRD 3.5: "While the season is `IN_SEASON`, the unit price is simply the model's
    `base_price_cents` — no markdown, no subsidy."
    PRD 3.5: "The markdown tier follows from that week index: weeks 0 through 2 take a
    15 percent markdown; weeks 3 and 4 — the second tier begins at week index 3 — take
    30 percent; week 5 and beyond — the third tier begins at week index 5 — take 50
    percent."
    PRD 3.5: "Coverage of 6000 basis points or more — 60 percent of the build still
    unsold — signals overstock and adds 10 percentage points to the markdown"
    PRD 3.5: "the after-markdown price is the model's `base_price_cents` times (100
    minus the markdown percent) divided by 100, rounded half up to integer cents.
    Fifth and finally, the selling channel's subsidy is applied to that rounded figure"

    Design: Difficulty/combinatorial_formula/clearance_price_tier_coverage_subsidy_composition
    """
    bundle = setup_in_season(allocated_units=3, units_built=10, channel_type="HOME_CENTER")
    season_id, model_id, channel_id = bundle["season"]["id"], bundle["model"]["id"], bundle["channel"]["id"]
    for token in ("RCPT-1", "RCPT-2"):
        in_season_sale = validate_success(
            _sale_raw(api, season_id, model_id, channel_id, quantity=1, proof_of_purchase_token=token), 201)
        assert in_season_sale["unit_price_cents"] == 100000, "in-season price is the model base, unchanged"
    set_logical_clock("2026-09-06T00:00:00Z")  # 36 days after clearance_start: week index 5
    cleared = validate_success(
        api.advance_season(season_id, {"target_status": "CLEARANCE"}, headers=PLANNER), 200)
    assert cleared["status"] == "CLEARANCE"
    # Allocation survived the waterfall (2/3 consumed = 6666bp >= 5000bp); the lot shows
    # 7 of 10 unsold (7000bp coverage >= 6000bp -> overstock +10). Markdown 50+10=60;
    # round_half_up(100000 x 0.40) = 40000; HOME_CENTER subsidy 2000bp -> 40000 x 0.80.
    clearance_sale = validate_success(
        _sale_raw(api, season_id, model_id, channel_id, quantity=1, proof_of_purchase_token="RCPT-3"), 201)
    assert clearance_sale["unit_price_cents"] == 32000, (
        f"week-5 tier 50% + overstock 10% capped at 60%, then 20% subsidy: 32000 expected, "
        f"got {clearance_sale['unit_price_cents']}"
    )


def test_clearance_price_understock_relief_at_low_coverage(api):
    """PRD 3.5: "coverage of 2000 basis points or less — 20 percent or less remaining —
    signals understock and subtracts 5 percentage points as relief"
    PRD 3.4: "Step two releases the laggards: any allocation whose rate falls strictly
    below 5000 basis points — under 50 percent consumed — gives up its unconsumed
    remainder"

    Design: Corner/calculations/clearance_price_understock_relief_at_low_coverage
    """
    bundle = setup_in_season(
        allocated_units=98, units_built=100, channel_type="DIRECT",
        model_over={"model_code": "GX-300", "base_price_cents": 50000, "demand_share_bp": 2000},
    )
    season_id, model_id, channel_id = bundle["season"]["id"], bundle["model"]["id"], bundle["channel"]["id"]
    create_sale(season_id, model_id, channel_id, quantity=49,
                proof_of_purchase_token=f"RCPT-{unique_suffix()}")
    set_logical_clock("2026-08-05T00:00:00Z")  # 4 days into clearance: week index 0
    cleared = validate_success(
        api.advance_season(season_id, {"target_status": "CLEARANCE"}, headers=PLANNER), 200)
    assert cleared["status"] == "CLEARANCE"
    alloc_after = refetch_allocation(bundle["allocation"]["id"])
    # 49/98 consumed = exactly 5000bp, NOT strictly below: the waterfall keeps it.
    assert alloc_after["status"] == "PARTIALLY_CONSUMED", (
        f"rate exactly 5000bp survives the waterfall, got {alloc_after['status']}"
    )
    # Lot availability 2 of 100 = 200bp coverage <= 2000bp -> relief -5; markdown 15-5=10;
    # round_half_up(50000 x 0.90) = 45000; DIRECT subsidy 0 leaves 45000.
    sale = validate_success(
        _sale_raw(api, season_id, model_id, channel_id, quantity=1, proof_of_purchase_token="RCPT-CLR"), 201)
    assert sale["unit_price_cents"] == 45000, f"understock relief price must be 45000, got {sale['unit_price_cents']}"


def test_attach_rates_zero_for_fresh_channel(api):
    """PRD 3.5: "When the denominator is empty, both rates are exactly 0.0000 — an
    empty channel reports zeros rather than an error."

    Design: Corner/calculations/attach_rates_zero_for_fresh_channel
    """
    channel = validate_success(api.create_channel(
        {"name": "FreshCo", "channel_type": "SPECIALTY_DEALER", "allocation_priority": 3,
         "credit_limit_cents": 5000000}, headers=PLANNER), 201)
    assert float(channel["accessory_attach_rate"]) == 0.0
    assert float(channel["fuel_attach_rate"]) == 0.0


def test_attach_rates_exclude_returned_sales(api):
    """PRD 3.5: "The denominator counts the channel's sales in `SOLD` or `REGISTERED`
    — `RETURNED` sales are excluded from both numerator and denominator. The
    `accessory_attach_rate` is the count of those sales with `accessory_count` of at
    least 1, divided by the denominator, rounded half up to 4 decimal places. The
    `fuel_attach_rate` uses the same denominator with a numerator counting sales where
    `has_fuel` is true, also at 4 decimal places."

    Design: Corner/calculations/attach_rates_exclude_returned_sales
    """
    bundle = setup_in_season()
    season_id, model_id, channel_id = bundle["season"]["id"], bundle["model"]["id"], bundle["channel"]["id"]
    create_sale(season_id, model_id, channel_id, quantity=1,
                accessories=[create_accessory(sku="CVR-1", accessory_type="COVER", unit_price_cents=1999)])
    create_sale(season_id, model_id, channel_id, quantity=1,
                accessories=[create_accessory(sku="FUEL-1", accessory_type="FUEL", unit_price_cents=499)])
    create_sale(season_id, model_id, channel_id, quantity=1)
    s4 = create_sale(season_id, model_id, channel_id, quantity=1,
                     accessories=[create_accessory(sku="CVR-4", accessory_type="COVER", unit_price_cents=1999)],
                     proof_of_purchase_token="RCPT-4")
    before = validate_success(api.get_channel(channel_id, headers=PLANNER), 200)
    assert float(before["accessory_attach_rate"]) == 0.75, "3 of 4 sales carry accessories"
    assert float(before["fuel_attach_rate"]) == 0.25, "1 of 4 sales carries fuel"
    transition = api.transition_sale(s4["id"], sale_transition_payload("RETURN"),
                                     headers=make_channel_rep_headers(channel_id))
    validate_success(transition, 200)
    after = validate_success(api.get_channel(channel_id, headers=PLANNER), 200)
    # The returned sale leaves both numerator and denominator: 2/3 and 1/3 at 4dp half-up.
    assert float(after["accessory_attach_rate"]) == 0.6667, f"2/3 rounds half-up to 0.6667, got {after['accessory_attach_rate']}"
    assert float(after["fuel_attach_rate"]) == 0.3333, f"1/3 rounds half-up to 0.3333, got {after['fuel_attach_rate']}"


def test_sales_list_uses_pagination_defaults(api):
    """PRD 2.3: "The `limit` parameter specifies the maximum number of items to
    return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of
    100. The `offset` parameter specifies the number of items to skip and defaults to
    0."
    PRD 2.3: "Paginated and non-paginated list-based responses include the following
    fields in the `meta` object of the response envelope: `limit`, `offset`,
    `total_count`, and `has_more`."

    Design: Corner/endpoints/sales_list_uses_pagination_defaults
    """
    bundle = setup_in_season(channel_type="DIRECT")
    for _ in range(3):
        create_sale(bundle["season"]["id"], bundle["model"]["id"], bundle["channel"]["id"], quantity=1)
    resp = api.list_sales(headers=PLANNER)
    data, meta = validate_paginated(resp)
    assert resp.json()["response_type"] == "array"
    assert meta["limit"] == 10, f"default limit is 10, got {meta['limit']}"
    assert meta["offset"] == 0, f"default offset is 0, got {meta['offset']}"
    assert meta["total_count"] == 3
    assert meta["has_more"] is False
    assert len(data) == 3
