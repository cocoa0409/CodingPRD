"""Referrals, revenue recognition, reversal and the compensating invariant."""
from test_helpers import ApiErrorId, validate_error, validate_success
from test_helpers.fixtures import (
    COMPLIANCE_OFFICER,
    LENDER_OPS,
    PLATFORM_ADMIN,
    advance_clock,
    create_referral_for,
    decline_referral,
    fund_referral,
    read_decision,
    read_offer,
    read_referral_entries,
    reverse_referral,
    setup_consented_scenario,
    setup_funded_referral,
)
from test_helpers.factories import create_referral_payload


def test_funding_recognizes_the_gross_share(api, as_consumer):
    """PRD §3.8: "The platform writes a `RevenueRecognitionEntry` whose `entry_kind` is
    `REVENUE` for the referral, stamped with `recognized_at` at the logical clock and
    carrying a `realized_amount_cents` equal to the referral's `funded_amount_cents`
    multiplied by its `revenue_share_bps` and divided by 10000, with the result floored
    to whole cents."

    Design: Difficulty/dual_variant_calc/revenue_gross_then_net_versus_gross_only
    """
    ctx = setup_consented_scenario(api=api)
    referral = create_referral_for(ctx, external_referral_ref="NS-L-9002", api=api)
    funded = fund_referral(referral["id"], funded_amount_cents=900_000, api=api)

    assert funded["status"] == "FUNDED"
    assert funded["funded_at"].startswith("2026-09-01T00:00:00")

    entries = read_referral_entries(referral["id"], api=api)
    revenue = [e for e in entries if e["entry_kind"] == "REVENUE"]
    assert len(revenue) == 1
    assert revenue[0]["realized_amount_cents"] == 90_000
    assert all(e["entry_kind"] != "CLAWBACK" for e in entries)


def test_reversal_posts_the_compensating_clawback_leg(api, as_consumer):
    """PRD §3.8: "A successful reversal stamps `reversed_at` with the logical clock,
    posts a `RevenueRecognitionEntry` whose `entry_kind` is `CLAWBACK` and whose
    `realized_amount_cents` is the negation of the floor of the funded amount
    multiplied by the revenue share basis points and divided by 10000".

    Design: Difficulty/dual_variant_calc/revenue_gross_then_net_versus_gross_only
    """
    ctx = setup_consented_scenario(api=api)
    referral = create_referral_for(ctx, external_referral_ref="NS-L-9003", api=api)
    fund_referral(referral["id"], funded_amount_cents=900_000, api=api)

    advance_clock("2026-09-10T00:00:00Z", api=api)
    reversed_referral = reverse_referral(referral["id"], api=api)

    assert reversed_referral["status"] == "REVERSED"
    assert reversed_referral["reversed_at"].startswith("2026-09-10T00:00:00")

    entries = read_referral_entries(referral["id"], api=api)
    clawback = [e for e in entries if e["entry_kind"] == "CLAWBACK"]
    assert len(clawback) == 1
    assert clawback[0]["realized_amount_cents"] == -45_000

    net = sum(e["realized_amount_cents"] for e in entries)
    assert net == 90_000 - 45_000 == 45_000


def test_a_second_reversal_cannot_break_the_invariant(api, as_consumer):
    """PRD §3.8: "one requested for a referral already reversed fails as a state error,
    with a second clawback for an already-clawed referral surfacing as
    `ERR_CLAWBACK_ALREADY_APPLIED`."

    Design: Difficulty/compensating_invariant/referral_reversal_restores_zero_net_realized
    """
    ctx = setup_consented_scenario(api=api)
    referral = create_referral_for(ctx, external_referral_ref="NS-L-9009", api=api)
    fund_referral(referral["id"], funded_amount_cents=900_000, api=api)
    advance_clock("2026-09-10T00:00:00Z", api=api)
    reverse_referral(referral["id"], api=api)

    entries_before = read_referral_entries(referral["id"], api=api)
    second = api.reverse_referral(
        referral["id"], {"reason_code": "LENDER_RETURNED_FUNDS"}, COMPLIANCE_OFFICER
    )
    validate_error(second, ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)

    entries_after = read_referral_entries(referral["id"], api=api)
    assert len(entries_after) == len(entries_before)

    from test_helpers.fixtures import read_referral

    referral_after = validate_success(
        api.get_referral(referral["id"], PLATFORM_ADMIN), 200
    )
    assert referral_after["reversed_at"].startswith("2026-09-10T00:00:00")


def test_reversal_outside_the_clawback_window_is_refused(api, as_consumer):
    """PRD §3.8: "And the logical clock must fall at or before `funded_at` plus the
    referral's copied `clawback_days`; a reversal past that boundary is refused with
    `ERR_CLAWBACK_WINDOW_CLOSED`."

    Design: Corner/errors/reversal_outside_the_clawback_window_is_refused
    """
    ctx = setup_consented_scenario(api=api)
    referral = create_referral_for(ctx, external_referral_ref="NS-L-9500", api=api)
    fund_referral(referral["id"], funded_amount_cents=600_000, api=api)

    advance_clock("2026-12-01T00:00:00Z", api=api)
    response = api.reverse_referral(
        referral["id"], {"reason_code": "LENDER_RETURNED_FUNDS"}, COMPLIANCE_OFFICER
    )
    validate_error(response, ApiErrorId.ERR_CLAWBACK_WINDOW_CLOSED, 409)

    referral_after = validate_success(api.get_referral(referral["id"], PLATFORM_ADMIN), 200)
    assert referral_after["status"] == "FUNDED"

    entries = read_referral_entries(referral["id"], api=api)
    assert len(entries) == 1
    assert entries[0]["entry_kind"] == "REVENUE"
    assert entries[0]["realized_amount_cents"] == 60_000


def test_face_value_and_platform_revenue_floor_independently(api, as_consumer):
    """PRD §3.8: "It also computes `platform_revenue_cents` as the sum, over the same
    referrals, of the funded amount multiplied by the revenue share basis points and
    divided by 10000 with each term floored individually before summing."
    PRD §3.8: "Identical rows therefore produce two totals computed on different bases,
    and an implementation that floors only once at the end will diverge."

    Design: Corner/calculations/face_value_versus_platform_revenue_round_differently
    """
    ctx = setup_consented_scenario(api=api)
    referral = create_referral_for(ctx, external_referral_ref="NS-L-9400", api=api)
    fund_referral(referral["id"], funded_amount_cents=33_333, api=api)

    entries = read_referral_entries(referral["id"], api=api)
    revenue = [e for e in entries if e["entry_kind"] == "REVENUE"]
    assert len(revenue) == 1
    assert revenue[0]["realized_amount_cents"] == 3_333


def test_fee_breakeven_returns_null_when_the_balance_is_unknown(api, consumer_headers):
    """PRD §3.8: "When the monthly interest saved is zero — which is what happens when
    no card balance is supplied on the read — the breakeven is null, not 0 and not
    unbounded."
    PRD §3.8: "the monthly interest saved is the card balance multiplied by the
    introductory APR basis points, divided by 10000 and then by twelve, floored to
    whole cents."

    Design: Corner/calculations/fee_breakeven_returns_null_when_the_balance_is_unknown
    """
    from test_helpers.fixtures import (
        create_active_catalog_item,
        create_active_lender,
        create_active_program,
        create_active_score_tier,
    )

    create_active_score_tier(api=api)
    item = create_active_catalog_item(api=api)
    lender = create_active_lender(api=api)
    create_active_program(
        lender_id=lender["id"], item_id=item["id"],
        annual_fee_cents=9500, intro_apr_bps=1800, api=api,
    )

    with_balance = validate_success(
        api.get_catalog_item(item["id"], consumer_headers, params={"card_balance_cents": 500_000}),
        200,
    )
    without_balance = validate_success(
        api.get_catalog_item(item["id"], consumer_headers), 200
    )

    assert with_balance["fee_breakeven_months"] == 2
    assert without_balance["fee_breakeven_months"] is None


def test_referral_on_an_unrendered_offer_is_refused(api, as_consumer):
    """PRD §3.8: "An attempt against an offer that has not reached `RENDERED` is refused
    with `ERR_OFFER_NOT_RENDERED`."

    Design: Corner/errors/referral_funding_via_the_marketplace_consumes_the_consent
    """
    from test_helpers.fixtures import (
        complete_render_facets,
        present_decision,
        qualify_decision,
        setup_prequalified_scenario,
    )

    ctx = setup_prequalified_scenario(api=api)
    qualify_decision(ctx["decision"]["id"], api=api)
    complete_render_facets(ctx["consumer"]["id"], run_key="seed-unrendered", api=api)
    presented = present_decision(ctx["decision"]["id"], ctx["consumer"]["id"], api=api)
    assert presented["status"] == "PRESENTED"

    response = api.create_referral(
        create_referral_payload(presented["id"], external_referral_ref="NS-L-9900"), LENDER_OPS
    )
    validate_error(response, ApiErrorId.ERR_OFFER_NOT_RENDERED, 409)
    assert validate_success(
        api.list_referrals(PLATFORM_ADMIN, params={"consumer_id": ctx["consumer"]["id"]}), 200
    ) == []