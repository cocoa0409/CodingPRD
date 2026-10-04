"""Capacity economics: allocation, congestion, oversale ceiling and the cost book."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    create_agreement_payload,
    make_subscriber_headers,
    validate_error,
    validate_success,
)

from test_helpers.fixtures import (
    complete_activation,
    create_agreement,
    create_inventory,
    create_plan,
    create_subscriber,
    current_agreement_version,
    get_plan,
    get_summary,
    next_msisdn,
    offer_plan,
    provision_activation,
    purchase_term,
    quote_term,
    request_activation,
    set_clock,
    setup_active_agreement,
    setup_agreement_with_offered_plan,
    setup_offered_plan,
    setup_subscribers_at_oversale_ceiling,
)


def _resolve_purchase(agreement_id):
    return api_client.resolve_purchase(
        agreement_id, TEST_USERS["planner_headers"]
    ).json()["data"]


def test_agreement_creation_rejects_an_undersized_committed_volume(api):
    """PRD §3.1: "Each of the three committed volumes must be at least 1."

    Design: Corner/entities/capacity_agreement_create_missing_commitment_returns_invalid_request
    """
    set_clock()
    resp = api.create_agreement(
        create_agreement_payload(committed_data_mb=0), TEST_USERS["planner_headers"]
    )
    assert resp.status_code in (400, 422), (
        f"a zero committed volume must be refused, got {resp.status_code}"
    )


def test_forward_and_as_incurred_costs_diverge_on_unrolled_allotment(api):
    """PRD §3.1: "The forward-looking reading projects how much allotment the current
    catalogue would consume if it were fully placed: it sums, over every plan on the agreement
    whose `plan_status` is `OFFERED` or `ACTIVE`, that plan's `data_allotment_mb` multiplied by
    its `contributing_subscribers(p)`, giving `projected_allotment_mb`."

    Design: Difficulty/dual_variant_calc/wholesale_overage_forward_looking_vs_as_incurred
    """
    set_clock()
    agreement = setup_active_agreement(committed_data_mb=16000)
    create_inventory(state_code="CA", unit_count=40)
    plan_h = setup_offered_plan(
        agreement["id"], current_agreement_version(agreement["id"]),
        plan_code="H3", data_allotment_mb=3000,
    )
    plan_m = setup_offered_plan(
        agreement["id"], current_agreement_version(agreement["id"]),
        plan_code="M3", data_allotment_mb=15000,
        intro_price_cents=2999, renewal_price_cents=3850,
        voice_allotment_min=1000, sms_allotment_msg=2000,
    )

    sub_h = create_subscriber(state_code="CA")
    term_h = quote_term(sub_h["id"], plan_h["id"], current_agreement_version(agreement["id"]))
    purchase_term(term_h["id"], sub_h["id"])
    activation_h = api.create_activation(
        {
            "subscriber_id": sub_h["id"],
            "prepaid_term_id": term_h["id"],
            "activation_channel": "DIGITAL",
        },
        make_subscriber_headers(sub_h["id"]),
    ).json()["data"]
    api.provision_activation(activation_h["id"], TEST_USERS["planner_headers"])

    sub_m = create_subscriber(msisdn=next_msisdn(), state_code="CA")
    term_m = quote_term(sub_m["id"], plan_m["id"], current_agreement_version(agreement["id"]))
    purchase_term(term_m["id"], sub_m["id"])

    resolved = _resolve_purchase(agreement["id"])
    assert resolved["projected_overage_data_mb"] == 2000
    assert resolved["committed_volume_cost_microcents"] == 32992000
    assert resolved["marginal_tier_rate_microcents"] == 1139
    assert resolved["resolved_purchase_cost_microcents"] == 35838000

    summary = get_summary(agreement["id"])
    assert summary["as_incurred_cost_microcents"] == 32992000
    assert summary["as_incurred_overage_cost_microcents"] == 0
    assert summary["allocated_data_mb"] == 18000
    assert summary["remaining_data_mb"] == -2000
    # The two readings differ by exactly the projected overage: 2000 megabytes of
    # unsold H3 allotment priced at the overage rate of 1423 microcents.
    assert resolved["resolved_purchase_cost_microcents"] - summary[
        "as_incurred_cost_microcents"
    ] == 2000 * 1423


def test_forward_and_as_incurred_share_the_committed_volume_leg(api):
    """PRD §3.1: "The two readings share an identical committed-volume term and differ only in
    whether they charge projected or rolled overage, so the as-incurred figure is strictly
    lower whenever any offered plan has unsold allotment."

    Design: Difficulty/dual_variant_calc/wholesale_overage_forward_looking_vs_as_incurred
    """
    set_clock()
    # The sold catalogue overruns the commitment, so the forward reading charges
    # projected overage the as-incurred reading cannot see until a cycle has rolled.
    agreement = setup_active_agreement(committed_data_mb=14000)
    create_inventory(state_code="CA", unit_count=40)
    plan_m = setup_offered_plan(
        agreement["id"], current_agreement_version(agreement["id"]),
        plan_code="M3", data_allotment_mb=15000,
        intro_price_cents=2999, renewal_price_cents=3850,
    )
    subscriber = create_subscriber(state_code="CA")
    term = quote_term(subscriber["id"], plan_m["id"], current_agreement_version(agreement["id"]))
    purchase_term(term["id"], subscriber["id"])
    activation = request_activation(subscriber["id"], term["id"])
    provision_activation(activation["id"])
    complete_activation(activation["id"], subscriber["id"])
    assert get_summary(agreement["id"])["allocated_data_mb"] == 15000

    resolved = _resolve_purchase(agreement["id"])
    summary = get_summary(agreement["id"])
    assert resolved["committed_volume_cost_microcents"] == summary[
        "committed_volume_cost_microcents"
    ]
    assert resolved["resolved_purchase_cost_microcents"] > summary["as_incurred_cost_microcents"]
    assert summary["as_incurred_overage_cost_microcents"] == 0


def test_marginal_tier_breakpoint_and_retroactive_blend(api):
    """PRD §3.1: "once
    `committed_data_mb` strictly exceeds the `TIER1_DATA_MB` breakpoint of 500,000 megabytes,
    the ceilinged `tier2_rate` applies to the *whole* committed volume rather than only to the
    volume above the breakpoint, so the blended figure is lower than the marginal figure by the
    500,000-megabyte band's rate saving".

    Design: Difficulty/dual_variant_calc/tier_marginal_breakpoint_vs_retroactive
    """
    set_clock()
    # setup_active_agreement supplies an ACTIVE agreement (as resolve_purchase and the
    # usage summary both require), so the only variable here is the committed volume.
    on_break = setup_active_agreement(
        host_network_name="On Breakpoint Host", committed_data_mb=500000
    )
    over = setup_active_agreement(
        host_network_name="Over Breakpoint Host", committed_data_mb=620000
    )

    on_summary = get_summary(on_break["id"])
    assert on_summary["retroactive_volume_cost_microcents"] == 500000 * 1237
    assert on_summary["committed_volume_cost_microcents"] == 500000 * 1237 + 12000000 + 1200000

    resolved_over = _resolve_purchase(over["id"])
    assert resolved_over["data_volume_cost_microcents"] == 500000 * 1237 + 120000 * 1139
    assert resolved_over["marginal_tier_rate_microcents"] == 1139
    over_summary = get_summary(over["id"])
    assert over_summary["retroactive_volume_cost_microcents"] == 620000 * 1139
    assert (
        resolved_over["data_volume_cost_microcents"]
        - over_summary["retroactive_volume_cost_microcents"]
        == 500000 * (1237 - 1139)
    )


def test_marginal_tier_rounds_the_rate_once_then_multiplies(api):
    """PRD §3.1: "`overage_rate_data` is `data_rate_microcents_per_mb` multiplied by
    `OVERAGE_MULTIPLIER_NUM` divided by `OVERAGE_MULTIPLIER_DEN` — 115 percent of the headline
    rate — rounded up to the next whole microcent."

    Design: Difficulty/combinatorial_formula/wholesale_cost_nested_rounding_order_marginal_vs_retroactive
    """
    set_clock()
    over = setup_active_agreement(
        host_network_name="Over Breakpoint Host", committed_data_mb=620000
    )
    resolved = _resolve_purchase(over["id"])
    assert resolved["data_volume_cost_microcents"] == 500000 * 1237 + 120000 * 1139
    assert resolved["marginal_tier_rate_microcents"] == 1139

    summary = get_summary(over["id"])
    assert summary["retroactive_volume_cost_microcents"] == 620000 * 1139
    assert resolved["data_volume_cost_microcents"] != summary[
        "retroactive_volume_cost_microcents"
    ]


def test_below_the_breakpoint_both_tier_readings_coincide(api):
    """PRD §3.1: "Below the breakpoint the blended rate is simply
    `data_rate_microcents_per_mb`."

    Design: Difficulty/combinatorial_formula/agreement_oversale_ladder_with_below_breakpoint_tier_cost
    """
    set_clock()
    agreement = setup_active_agreement(committed_data_mb=100000)
    plan = setup_offered_plan(
        agreement["id"], current_agreement_version(agreement["id"]),
        plan_code="S3", data_allotment_mb=3000,
    )

    resolved = _resolve_purchase(agreement["id"])
    assert resolved["data_volume_cost_microcents"] == 100000 * 1237
    assert resolved["marginal_tier_rate_microcents"] == 1139

    summary = get_summary(agreement["id"])
    assert summary["retroactive_volume_cost_microcents"] == resolved[
        "data_volume_cost_microcents"
    ]
    assert summary["allocated_data_mb"] == 0
    assert summary["remaining_data_mb"] == 100000
    assert summary["congestion_index"] == 0


def test_volume_tier_below_and_on_the_breakpoint(api):
    """PRD §2.6: "The overage unit rate and the discounted tier rate are each rounded **up** to
    the next whole microcent at the moment the rate is derived, and that rounded rate is what
    every subsequent multiplication uses."

    Design: Corner/calculations/wholesale_volume_tier_breakpoint_behaviour
    """
    set_clock()
    below = setup_active_agreement(host_network_name="Below Host", committed_data_mb=200000)
    on = setup_active_agreement(host_network_name="On Host", committed_data_mb=500000)

    below_resolved = _resolve_purchase(below["id"])
    on_resolved = _resolve_purchase(on["id"])
    assert below_resolved["data_volume_cost_microcents"] == 200000 * 1237
    assert on_resolved["data_volume_cost_microcents"] == 500000 * 1237
    assert below_resolved["marginal_tier_rate_microcents"] == 1139
    assert on_resolved["marginal_tier_rate_microcents"] == 1139


def test_oversale_ceiling_admits_the_boundary_and_rejects_one_past(api):
    """PRD §3.1: "A sale is admitted while the agreement's `allocated_data_mb` plus the
    allotment being sold would stay at or below `committed_data_mb` multiplied by
    `OVERSALE_LIMIT_NUM` divided by `OVERSALE_LIMIT_DEN` — that is, 120 percent
    of the committed volume. At the boundary the sale succeeds; one megabyte past the boundary
    it is rejected with `ERR_INSUFFICIENT_AGREEMENT_CAPACITY` (HTTP 409)."

    Design: Difficulty/combinatorial_formula/agreement_oversale_ladder_with_below_breakpoint_tier_cost
    """
    set_clock()
    setup = setup_subscribers_at_oversale_ceiling(
        committed_data_mb=100000, allotment=3000
    )
    # The fortieth sale landed exactly on the boundary — 120 percent of 100000 — and
    # was admitted; that is the "at the boundary the sale succeeds" half.
    summary = get_summary(setup["agreement"]["id"])
    assert summary["allocated_data_mb"] == 120000
    assert summary["remaining_data_mb"] == -20000

    # One allotment past the boundary is refused. The same admission gate governs the
    # quote and the purchase (SCAFFOLD priority 10 applies to both POST /prepaid-terms
    # and POST /prepaid-terms/{id}/purchase), so the refusal surfaces on the quote; the
    # call is made directly rather than through the fixture, which asserts a 201.
    extra = create_subscriber(msisdn=next_msisdn(), state_code="CA")
    resp = api.create_term(
        {
            "subscriber_id": extra["id"],
            "plan_id": setup["plan"]["id"],
            "expected_CapacityAgreement_version": current_agreement_version(
                setup["agreement"]["id"]
            ),
        },
        make_subscriber_headers(extra["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_AGREEMENT_CAPACITY)