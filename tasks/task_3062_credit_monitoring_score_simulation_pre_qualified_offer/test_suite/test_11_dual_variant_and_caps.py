"""Dual-variant calculations, terminal-state lockdowns and window rollovers."""
from test_helpers import ApiErrorId, validate_error, validate_success
from test_helpers.factories import (
    create_consent_payload,
    create_referral_payload,
    create_targeting_criterion_payload,
)
from test_helpers.fixtures import (
    LENDER_OPS,
    PLATFORM_ADMIN,
    REFEREE,
    advance_clock,
    complete_consent,
    complete_render_facets,
    create_active_catalog_item,
    create_active_lender,
    create_active_program,
    create_active_score_tier,
    create_decision,
    create_monitored_consumer,
    create_referral_for,
    fund_referral,
    present_decision,
    qualify_decision,
    read_consumer_version,
    read_decision,
    read_offer,
    render_offer,
    reset_clock,
    setup_catalog_scenario,
    setup_monitored,
)


def _funnel(api, program_id, score, email, bureau_pin, dti_pct=35.0, balance_cents=480_000):
    """Consented, pulled consumer on `program_id` with an eligible decision."""
    consumer, snapshot = create_monitored_consumer(
        score=score, balance_cents=balance_cents, email=email, bureau_pin=bureau_pin,
        dti_pct=dti_pct, api=api,
    )
    decision = create_decision(consumer["id"], program_id, api=api)
    return consumer, snapshot, decision


def test_odds_settle_from_provisional_to_the_realized_integer(api, as_consumer):
    """PRD §3.5: "It stays false for as long as the decision is `ELIGIBLE` or
    `PREQUALIFIED`, and only becomes true once a realised terminal referral outcome has
    been folded back onto that same decision. When that happens the identical odds
    expression is evaluated and is then rounded to the integer 0 or 100 rather than to
    two decimals, so one and the same bureau snapshot can report an odds of 0.91
    provisionally and 100 once the outcome is known."

    Design: Difficulty/dual_variant_calc/odds_provisional_versus_settled_after_realized_outcome
    """
    reset_clock(api=api)
    ctx = setup_catalog_scenario(api=api, program_overrides={"max_dti_pct": 45.0})
    consumer, snapshot, decision = _funnel(
        api, ctx["program"]["id"], score=660, email="maya@example.com", bureau_pin="4823"
    )
    assert decision["modeled_odds_pct"] == 0.91
    assert decision["modeled_odds_settled"] is False

    qualified = qualify_decision(decision["id"], api=api)
    complete_render_facets(consumer["id"], run_key="seed-odds-variant", api=api)
    offer = present_decision(qualified["id"], consumer["id"], api=api)
    render_offer(offer["id"], consumer["id"], api=api)
    version = read_consumer_version(consumer["id"], api=api)
    validate_success(
        api.complete_consent(
            consumer["id"], qualified["id"], create_consent_payload(version),
            as_consumer(consumer["id"]),
        ),
        201,
    )
    before_funding = read_decision(qualified["id"], api=api)
    assert before_funding["modeled_odds_settled"] is False

    referral = validate_success(
        api.create_referral(
            create_referral_payload(offer["id"], external_referral_ref="NS-L-9001"), LENDER_OPS
        ),
        201,
    )
    fund_referral(referral["id"], funded_amount_cents=900_000, api=api)

    after_funding = read_decision(qualified["id"], api=api)
    assert after_funding["modeled_odds_settled"] is True
    assert after_funding["modeled_odds_pct"] == 100
    assert after_funding["decision_status"] == "CONSUMED"


def test_odds_stay_settled_and_provisional_reads_agree_before_any_outcome(api, as_consumer):
    """PRD §3.5: "The `modeled_odds_settled` flag starts false, because odds derived
    from a bureau snapshot alone are provisional — they model what the lender is
    expected to do, not what it did."

    Design: Difficulty/dual_variant_calc/odds_provisional_versus_settled_after_realized_outcome
    """
    reset_clock(api=api)
    ctx = setup_catalog_scenario(api=api)
    consumer, snapshot, decision = _funnel(
        api, ctx["program"]["id"], score=660, email="stillprov@example.com", bureau_pin="4824"
    )
    assert decision["modeled_odds_pct"] == 0.91
    assert decision["modeled_odds_settled"] is False
    qualified = qualify_decision(decision["id"], api=api)
    assert qualified["modeled_odds_settled"] is False
    assert qualified["decision_status"] == "PREQUALIFIED"


def test_calibration_variants_diverge_for_identical_decision_rows(api, as_consumer):
    """PRD §3.8: "The including-provisional variant takes the mean over every
    considered decision, so the provisional modeled odds of unconsumed decisions enter
    it. The settled-only variant takes the mean over only those decisions whose
    `modeled_odds_settled` flag is true — that is, over realised outcomes alone."
    PRD §3.8: "Otherwise the mean modeled odds across the considered decisions is taken
    and rounded half up to 4 decimal places, the realised success rate is taken as the
    success count divided by the considered count and rounded half up to 4 decimal
    places, and the index is the first divided by the second".

    Design: Difficulty/dual_variant_calc/calibration_index_including_provisional_versus_settled_only
    """
    reset_clock(api=api)
    ctx = setup_catalog_scenario(api=api, program_overrides={"max_dti_pct": 45.0})

    # First consumer: full funnel through a funded referral.
    first, snapshot, decision = _funnel(
        api, ctx["program"]["id"], score=660, email="cal1@example.com", bureau_pin="6001"
    )
    qualify_decision(decision["id"], api=api)
    complete_render_facets(first["id"], run_key="seed-cal-variant", api=api)
    offer = present_decision(decision["id"], first["id"], api=api)
    render_offer(offer["id"], first["id"], api=api)
    version = read_consumer_version(first["id"], api=api)
    validate_success(
        api.complete_consent(
            first["id"], decision["id"], create_consent_payload(version),
            as_consumer(first["id"]),
        ),
        201,
    )
    referral = validate_success(
        api.create_referral(
            create_referral_payload(offer["id"], external_referral_ref="NS-L-9004"), LENDER_OPS
        ),
        201,
    )
    fund_referral(referral["id"], funded_amount_cents=900_000, api=api)

    # Second consumer: a decision on the same catalog item left open and provisional.
    second, _, still_open = _funnel(
        api, ctx["program"]["id"], score=660, email="cal2@example.com", bureau_pin="6002"
    )
    assert still_open["decision_status"] == "ELIGIBLE"
    assert still_open["modeled_odds_pct"] == 0.91

    provisional = validate_success(
        api.get_catalog_item(ctx["item"]["id"], PLATFORM_ADMIN), 200
    )
    settled = validate_success(
        api.get_catalog_item_settled_index(ctx["item"]["id"], PLATFORM_ADMIN), 200
    )

    assert provisional["calibration_variant"] != settled["calibration_variant"]
    assert provisional["decision_count"] == 2
    assert settled["decision_count"] == 1
    assert provisional["modeled_odds_mean"] == 0.91
    assert provisional["realized_rate"] == 0.5
    assert provisional["approval_odds_calibration_index"] == 1.82
    assert settled["modeled_odds_mean"] == 0.91
    assert settled["realized_rate"] == 1.0
    assert settled["approval_odds_calibration_index"] == 0.91


def test_retired_tier_rejects_further_transitions(api):
    """PRD §3.5: "A tier that is retired leaves `ACTIVE` for the terminal `RETIRED`
    status."

    Design: Corner/state_machines/terminal_retired_tier_rejects_every_transition
    """
    reset_clock(api=api)
    create_active_score_tier(api=api)
    tiers = validate_success(api.list_score_tiers(PLATFORM_ADMIN), 200)
    assert len(tiers) == 1

    validate_success(api.retire_score_tier(tiers[0]["id"], PLATFORM_ADMIN), 200)
    response = api.activate_score_tier(tiers[0]["id"], PLATFORM_ADMIN)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)

    retired = validate_success(
        api.list_score_tiers(PLATFORM_ADMIN, params={"status": "RETIRED"}), 200
    )
    assert [t["id"] for t in retired] == [tiers[0]["id"]]


def test_first_pull_writes_a_flat_suppressed_alert(api, as_consumer):
    """PRD §3.1: "If there is no previous score at all — the very first successful pull
    for that consumer — the movement comparison is skipped entirely and the alert's
    `alert_kind` is set to `SCORE_FLAT` regardless of magnitude."
    PRD §3.1: "One `ScoreAlert` row is written for every pull, with no exceptions."

    Design: Corner/calculations/score_alert_flat_row_is_written_suppressed_at_the_default_threshold
    """
    ctx = setup_monitored(api=api, score=700, email="firstpull@example.com", bureau_pin="7001")

    alerts = validate_success(
        api.list_consumer_score_alerts(
            ctx["consumer"]["id"], as_consumer(ctx["consumer"]["id"])
        ),
        200,
    )
    assert len(alerts) == 1
    assert alerts[0]["alert_kind"] == "SCORE_FLAT"
    assert alerts[0]["status"] == "SUPPRESSED"
    assert alerts[0]["threshold_used"] == 20
    assert alerts[0]["from_score"] is None
    assert alerts[0]["to_score"] == 700


def test_presentation_cap_blocks_the_second_offer_until_the_window_rolls(api, as_consumer):
    """PRD §3.4: "The cap is breached when `presented_count` is strictly greater than
    the product kind's basis points multiplied by the total offer count and divided by
    10000, with the result floored."
    PRD §3.4: "A daily run resets every cap's `presented_count` to 0 and recomputes the
    breach flag, which is what makes the window roll."

    Design: Corner/cross_cutting_layers/presentation_cap_resets_on_the_ops_window
    """
    reset_clock(api=api)
    create_active_score_tier(api=api)
    item = create_active_catalog_item(api=api)
    lender = create_active_lender(api=api)

    offers = []
    for index, code in enumerate(["NS-LOAN-11", "NS-LOAN-12"]):
        program = create_active_program(
            lender_id=lender["id"], item_id=item["id"], program_code=code, api=api
        )
        for criterion in (
            {"criterion_field": "UTILIZATION_PCT", "operator": "LTE", "criterion_value": "50",
             "is_hard_requirement": True},
            {"criterion_field": "DTI_PCT", "operator": "LTE", "criterion_value": "30",
             "is_hard_requirement": False},
        ):
            validate_success(
                api.create_targeting_criterion(
                    program["id"], create_targeting_criterion_payload(**criterion), LENDER_OPS
                ),
                201,
            )
        consumer, snapshot, decision = _funnel(
            api, program["id"], score=700,
            email=f"cap{index}@example.com", bureau_pin=f"80{index:02d}",
            dti_pct=25.0, balance_cents=300_000,
        )
        qualify_decision(decision["id"], api=api)
        complete_render_facets(consumer["id"], run_key=f"seed-cap-{index}", api=api)
        presented = present_decision(decision["id"], consumer["id"], api=api)
        offers.append((consumer, presented))

    first_consumer, first_offer = offers[0]
    assert read_offer(first_offer["id"])["status"] == "PRESENTED"

    # A single LOAN offer in the window floors the cap to zero, so rendering one
    # already breaches it for the second.
    validate_success(
        api.render_offer(first_offer["id"], as_consumer(first_consumer["id"])), 200
    )
    caps = validate_success(
        api.list_consumer_offer_presentation_caps(first_consumer["id"], PLATFORM_ADMIN), 200
    )
    assert len(caps) == 1
    assert caps[0]["product_kind"] == "LOAN"
    assert caps[0]["presented_count"] == 1

    second_consumer, second_offer = offers[1]
    validate_success(api.run_ops({"run_key": "cap-window-roll"}, PLATFORM_ADMIN), 201)
    validate_success(
        api.render_offer(second_offer["id"], as_consumer(second_consumer["id"])), 200
    )
    assert read_offer(second_offer["id"])["status"] == "RENDERED"