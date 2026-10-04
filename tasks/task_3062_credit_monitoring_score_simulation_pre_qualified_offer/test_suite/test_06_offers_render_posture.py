"""Render posture, presentation caps and the retention of rendered offers."""
from test_helpers import ApiErrorId, validate_error, validate_success
from test_helpers.fixtures import (
    PLATFORM_ADMIN,
    REFEREE,
    advance_clock,
    create_consumer,
    read_offer,
    setup_offer_scenario,
    setup_prequalified_scenario,
)
from test_helpers.factories import create_content_quality_facet_payload


def test_rendering_advances_the_offer_and_the_cap_row(api, as_consumer):
    """PRD §3.7: "Only when the offer is still `PRESENTED` and all of these hold does
    the status become `RENDERED`, the consumer's `presented_count` for that product
    kind increase by one, and the corresponding `OfferPresentationCap` row be
    recomputed with its breach flag."

    Design: Corner/endpoints/conditional_action_requires_free_decision_expiry_window
    """
    ctx = setup_offer_scenario(api=api)
    rendered = read_offer(ctx["offer"]["id"], api=api)
    assert rendered["status"] == "RENDERED"
    assert rendered["render_intent_recorded_at"] is not None

    caps = validate_success(
        api.list_consumer_offer_presentation_caps(ctx["consumer"]["id"], PLATFORM_ADMIN), 200
    )
    assert len(caps) == 1
    assert caps[0]["product_kind"] == "LOAN"


def test_monitoring_posture_settles_after_the_ops_sweep(api, as_consumer):
    """PRD §2.4: "posture rollup that recomputes each consumer's monitoring posture and
    each consumer's render posture before settling the run itself."
    PRD §3.4: "it becomes `RENDER_OPEN` when `whole_render_completeness` holds for that
    consumer — that is, when every constituent facet is `COMPLETE`".

    Design: Corner/cross_cutting_layers/monitoring_posture_reconciles_after_the_ops_sweep
    """
    consumer = create_consumer(email="posture@example.com", bureau_pin="4826", api=api)
    validate_success(
        api.create_content_quality_facet(
            consumer["id"],
            create_content_quality_facet_payload(topic="factor_explanations", score_bps=9000),
            REFEREE,
        ),
        201,
    )
    validate_success(api.run_ops({"run_key": "posture-first"}, PLATFORM_ADMIN), 201)

    policies = validate_success(
        api.list_render_policies(REFEREE, params={"consumer_id": consumer["id"]}), 200
    )
    assert len(policies) == 1
    assert policies[0]["render_posture"] == "RENDER_FACETS_INCOMPLETE"

    facets = validate_success(
        api.list_consumer_content_quality_facets(consumer["id"], REFEREE), 200
    )
    correct = [f for f in facets if f["topic"] == "factor_explanations"]
    assert correct[0]["status"] == "COMPLETE"

    validate_success(
        api.create_content_quality_facet(
            consumer["id"],
            create_content_quality_facet_payload(topic="accuracy_education", score_bps=9000),
            REFEREE,
        ),
        201,
    )
    validate_success(api.run_ops({"run_key": "posture-second"}, PLATFORM_ADMIN), 201)

    policies = validate_success(
        api.list_render_policies(REFEREE, params={"consumer_id": consumer["id"]}), 200
    )
    assert policies[0]["render_posture"] == "RENDER_OPEN"


def test_rendered_offer_ages_out_on_the_non_rolling_schedule(api, as_consumer):
    """PRD §3.7: "a non-rolling variant, armed once an offer has been rendered,
    measures from the original decision's `decided_at` and never restarts — an offer
    re-issued late still expires on the original schedule."
    PRD §3.7: "An offer becomes `STALE` when the logical clock passes either expiry
    instant".

    Design: Corner/cross_cutting_layers/rendered_offer_ages_out_by_the_non_rolling_clock
    """
    ctx = setup_offer_scenario(api=api)
    assert read_offer(ctx["offer"]["id"], api=api)["status"] == "RENDERED"

    advance_clock("2026-10-02T00:00:00Z", api=api)
    validate_success(api.run_ops({"run_key": "stale-offer-sweep"}, PLATFORM_ADMIN), 201)

    stale = read_offer(ctx["offer"]["id"], api=api)
    assert stale["status"] == "STALE"
    assert read_offer(ctx["offer"]["id"])["intent_recorded_at"].startswith("2026-09-01T00:00:00")


def test_offer_freshness_does_not_restart_on_render(api, as_consumer):
    """PRD §3.7: "This timestamp is the anchor of the offer's freshness clock, and it
    is not restarted by anything that happens later; in particular
    `render_intent_recorded_at` records when the offer was rendered but is explicitly
    never used to restart the clock."

    Design: Corner/cross_cutting_layers/rendered_offer_ages_out_by_the_non_rolling_clock
    """
    ctx = setup_offer_scenario(api=api)
    offer = read_offer(ctx["offer"]["id"], api=api)
    assert offer["intent_recorded_at"] == offer["intent_recorded_at"]
    assert offer["intent_recorded_at"].startswith("2026-09-01T00:00:00")

    advance_clock("2026-09-30T00:00:00Z", api=api)
    still_live = read_offer(ctx["offer"]["id"], api=api)
    assert still_live["status"] == "RENDERED", "29 days elapsed is inside the 30-day TTL"

    advance_clock("2026-10-02T00:00:00Z", api=api)
    aged = read_offer(ctx["offer"]["id"], api=api)
    assert aged["status"] == "STALE"
    assert aged["render_intent_recorded_at"] is not None


def test_archived_consent_records_stay_queryable_through_the_filter(api, as_consumer):
    """PRD §3.6: "An archived record is still queryable, but only through the archived
    filter on the consent listing."

    Design: Corner/cross_cutting_layers/archived_consent_records_stay_queryable_through_the_filter
    """
    from test_helpers.fixtures import create_referral_for, setup_consented_scenario

    ctx = setup_consented_scenario(api=api)
    create_referral_for(ctx, external_referral_ref="NS-L-9700", api=api)
    sealed = validate_success(
        api.list_consumer_consent_records(ctx["consumer"]["id"], PLATFORM_ADMIN), 200
    )[0]

    advance_clock("2027-09-02T00:00:00Z", api=api)
    validate_success(api.run_ops({"run_key": "retention-sweep"}, PLATFORM_ADMIN), 201)

    archived = validate_success(
        api.list_consent_records(
            PLATFORM_ADMIN, params={"archive_status": "ARCHIVED", "consumer_id": ctx["consumer"]["id"]}
        ),
        200,
    )
    assert [r["id"] for r in archived] == [sealed["id"]]
    assert archived[0]["status"] == "SEALED"

    from_consumer = validate_success(
        api.list_consumer_consent_records(ctx["consumer"]["id"], PLATFORM_ADMIN), 200
    )
    assert [r["id"] for r in from_consumer] == [sealed["id"]]