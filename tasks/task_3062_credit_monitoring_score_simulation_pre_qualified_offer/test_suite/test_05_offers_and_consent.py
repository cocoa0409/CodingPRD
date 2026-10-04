"""Presenting, rendering, consent and the data boundary."""
import pytest

from test_helpers import ApiErrorId, validate_error, validate_success
from test_helpers.factories import create_consent_payload, create_referral_attempt_payload
from test_helpers.fixtures import (
    COMPLIANCE_OFFICER,
    LENDER_OPS,
    PLATFORM_ADMIN,
    advance_clock,
    complete_consent,
    create_referral_for,
    qualify_decision,
    read_consumer_version,
    read_decision,
    read_offer,
    setup_consented_scenario,
    setup_offer_scenario,
    setup_prequalified_scenario,
)


def test_consent_chain_reaches_pending_with_the_decision_consented(api, as_consumer):
    """PRD §3.6: "The operation creates a `ConsentRecord` in status `PENDING` with
    `archive_status` `LIVE`, stamps `consented_at` with the logical clock, and moves
    the decision to `CONSENTED`. It also advances the consumer's `version`."
    PRD §3.6: "Until that instant, `consumer_pii_ciphertext` is null and the blob is
    withheld from every read".

    Design: Corner/validations/satisfaction_of_the_adverse_selection_gate_allows_rendering
    """
    ctx = setup_offer_scenario(api=api)
    version = read_consumer_version(ctx["consumer"]["id"], api=api)
    consent = validate_success(
        api.complete_consent(
            ctx["consumer"]["id"], ctx["decision"]["id"], create_consent_payload(version),
            as_consumer(ctx["consumer"]["id"]),
        ),
        201,
    )

    assert consent["status"] == "PENDING"
    assert consent["archive_status"] == "LIVE"
    assert consent["consumer_pii_ciphertext"] is None
    assert consent["lender_routing_netloc"] is None

    decision = read_decision(ctx["decision"]["id"], api=api)
    assert decision["decision_status"] == "CONSENTED"


def test_consent_write_with_a_stale_version_is_rejected(api, as_consumer):
    """PRD §2.8: "When the supplied value differs from the consumer's current
    `version`, the request is rejected with `ERR_STALE_VERSION` and an HTTP 412 status.
    The three protected operations are the bureau snapshot refresh, the consent
    completion that records a consumer's consent for a decision, and the score
    simulation create."

    Design: Corner/cross_cutting_layers/stale_consumer_version_blocks_the_pre_consent_funnel
    """
    ctx = setup_offer_scenario(api=api)
    stale_version = read_consumer_version(ctx["consumer"]["id"], api=api) - 5

    response = api.complete_consent(
        ctx["consumer"]["id"], ctx["decision"]["id"], create_consent_payload(stale_version),
        as_consumer(ctx["consumer"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_STALE_VERSION, 412)

    assert validate_success(
        api.list_consumer_consent_records(ctx["consumer"]["id"], PLATFORM_ADMIN), 200
    ) == []
    assert read_decision(ctx["decision"]["id"], api=api)["decision_status"] == "PREQUALIFIED"

    fresh = read_consumer_version(ctx["consumer"]["id"], api=api)
    validate_success(
        api.complete_consent(
            ctx["consumer"]["id"], ctx["decision"]["id"], create_consent_payload(fresh),
            as_consumer(ctx["consumer"]["id"]),
        ),
        201,
    )


def test_consent_sealing_mints_the_blob_and_the_routing_netloc(api, as_consumer):
    """PRD §3.6: "At the sealing instant the platform mints a sealed personal-information
    blob into `consumer_pii_ciphertext`, stamps `lender_routing_netloc` with the
    sponsoring program's lender endpoint, and records `sealed_at`."

    Design: Difficulty/non_linear_state_machine/consent_record_parallel_axes_and_versioned_archive
    """
    ctx = setup_consented_scenario(api=api)
    referral = create_referral_for(ctx, external_referral_ref="NS-L-9006", api=api)
    assert referral["status"] == "SENT"

    records = validate_success(
        api.list_consumer_consent_records(ctx["consumer"]["id"], PLATFORM_ADMIN), 200
    )
    assert len(records) == 1
    sealed = records[0]
    assert sealed["status"] == "SEALED"
    assert sealed["archive_status"] == "LIVE"
    assert sealed["consumer_pii_ciphertext"] is not None
    assert sealed["lender_routing_netloc"] is not None
    assert sealed["sealed_at"] is not None


def test_consent_archive_axis_moves_independently_of_the_release_axis(api, as_consumer):
    """PRD §3.6: "The daily run's retention stage archives any consent record that has
    reached `SEALED` status and whose `sealed_at` is at or before the logical clock
    minus 365 days (`RETENTION_DAYS`), flipping its `archive_status` to `ARCHIVED`."

    Design: Difficulty/non_linear_state_machine/consent_record_parallel_axes_and_versioned_archive
    """
    ctx = setup_consented_scenario(api=api)
    create_referral_for(ctx, external_referral_ref="NS-L-9072", api=api)
    sealed = validate_success(
        api.list_consumer_consent_records(ctx["consumer"]["id"], PLATFORM_ADMIN), 200
    )[0]
    assert sealed["status"] == "SEALED"
    assert sealed["archive_status"] == "LIVE"

    advance_clock("2027-09-02T00:00:00Z", api=api)
    validate_success(api.run_ops({"run_key": "retention-sweep"}, PLATFORM_ADMIN), 201)

    after = validate_success(
        api.get_consent_record(sealed["id"], PLATFORM_ADMIN), 200
    )
    assert after["status"] == "SEALED"
    assert after["archive_status"] == "ARCHIVED"


def test_second_referral_on_the_same_offer_is_refused(api, as_consumer):
    """PRD §3.8: "Both paths require the linked consent record to still be `PENDING`;
    a consent that is no longer pending means the one-time grant has already been used,
    and the attempt is refused with `ERR_CONSENT_ALREADY_CONSUMED`."

    Design: Difficulty/cross_entity_state_dependency/referral_creation_requires_unsealed_consent
    """
    ctx = setup_consented_scenario(api=api)
    first = create_referral_for(ctx, external_referral_ref="NS-L-9010", api=api)
    assert first["status"] == "SENT"

    from test_helpers.factories import create_referral_payload

    second = api.create_referral(
        create_referral_payload(ctx["offer"]["id"], external_referral_ref="NS-L-9011"),
        LENDER_OPS,
    )
    validate_error(second, ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)

    rows = validate_success(
        api.list_referrals(PLATFORM_ADMIN, params={"consumer_id": ctx["consumer"]["id"]}), 200
    )
    assert len(rows) == 1


def test_first_referral_consumes_the_decision_offer_and_consent(api, as_consumer):
    """PRD §3.8: "Whichever path is used, the new referral starts in status `SENT`,
    copies `revenue_share_bps` and `clawback_days` from the sponsoring program, and
    advances the consumer's `version`. The consuming operation also seals the consent —
    minting the ciphertext, stamping the routing netloc — and drives both the offer and
    the decision to `CONSUMED`."

    Design: Difficulty/cross_entity_state_dependency/referral_creation_requires_unsealed_consent
    """
    ctx = setup_consented_scenario(api=api)
    referral = create_referral_for(ctx, external_referral_ref="NS-L-9012", api=api)

    assert referral["status"] == "SENT"
    assert referral["revenue_share_bps"] == 1000
    assert referral["clawback_days"] == 90
    assert read_decision(ctx["decision"]["id"], api=api)["decision_status"] == "CONSUMED"
    assert read_offer(ctx["offer"]["id"], api=api)["status"] == "CONSUMED"


def test_marketplace_attempt_consumes_the_same_one_time_consent(api, as_consumer):
    """PRD §3.8: "Both paths require the linked consent record to still be `PENDING`;
    a consent that is no longer pending means the one-time grant has already been used,
    and the attempt is refused with `ERR_CONSENT_ALREADY_CONSUMED`."

    Design: Corner/errors/referral_funding_via_the_marketplace_consumes_the_consent
    """
    ctx = setup_consented_scenario(api=api)
    attempt = validate_success(
        api.create_referral_attempt(
            create_referral_attempt_payload(ctx["decision"]["id"]), LENDER_OPS
        ),
        201,
    )
    assert read_decision(ctx["decision"]["id"], api=api)["decision_status"] == "CONSUMED"
    assert read_offer(ctx["offer"]["id"], api=api)["status"] == "CONSUMED"

    sealed = validate_success(
        api.list_consumer_consent_records(ctx["consumer"]["id"], PLATFORM_ADMIN), 200
    )
    assert len(sealed) == 1
    assert sealed[0]["status"] == "SEALED"
    assert sealed[0]["lender_routing_netloc"] is not None

    second = api.create_referral_attempt(
        create_referral_attempt_payload(ctx["decision"]["id"]), LENDER_OPS
    )
    validate_error(second, ApiErrorId.ERR_CONSENT_ALREADY_CONSUMED, 409)


def test_presenting_a_decision_requires_the_sponsoring_program_to_be_active(api, as_consumer):
    """PRD §3.5: "pausing cascades every decision pinned to that program whose status
    is `ELIGIBLE` or `PREQUALIFIED` to `INELIGIBLE`, stamping the reason
    `PROGRAM_PAUSED` and nulling the modeled odds."
    PRD §3.6: "The decision must be `PREQUALIFIED` before consent can be recorded;
    consenting to anything else is rejected with `ERR_CONSENT_DECISION_NOT_PREQUALIFIED`."

    Design: Difficulty/cross_entity_state_dependency/decision_presentation_requires_program_active
    """
    ctx = setup_consented_scenario(api=api)
    validate_success(
        api.pause_lender_program(ctx["program"]["id"], COMPLIANCE_OFFICER), 200
    )

    assert validate_success(
        api.get_lender_program(ctx["program"]["id"], PLATFORM_ADMIN), 200
    )["status"] == "PAUSED"

    decision = read_decision(ctx["decision"]["id"], api=api)
    assert decision["decision_status"] == "INELIGIBLE"
    assert decision["reason"] == "PROGRAM_PAUSED"
    assert decision["modeled_odds_pct"] is None

    version = read_consumer_version(ctx["consumer"]["id"], api=api)
    response = api.complete_consent(
        ctx["consumer"]["id"], ctx["decision"]["id"], create_consent_payload(version),
        as_consumer(ctx["consumer"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_CONSENT_DECISION_NOT_PREQUALIFIED, 409)


def test_expired_decision_outranks_a_malformed_consent_scope(api, as_consumer):
    """PRD §2.11: "Rankings below state validity are, in order: the expiry rule that
    bars consenting to or presenting a decision whose `fresh_until` has passed
    (`ERR_OFFER_EXPIRED`); ... request shape and ledger arithmetic including malformed
    bodies, undeclared enum members".
    PRD §2.11: "The practical consequence of this ladder is that a referral which is
    both non-consented and carries a malformed funding amount reports the consent error".

    Design: Difficulty/priority_pair_validation_conflict/expired_decision_beats_fiscal_cap_on_consent
    """
    ctx = setup_prequalified_scenario(api=api)
    qualify_decision(ctx["decision"]["id"], api=api)
    advance_clock("2026-12-15T00:00:00Z", api=api)
    version = read_consumer_version(ctx["consumer"]["id"], api=api)

    response = api.complete_consent(
        ctx["consumer"]["id"], ctx["decision"]["id"],
        create_consent_payload(version, consent_scope="SHARE_EVERYTHING"),
        as_consumer(ctx["consumer"]["id"]),
    )
    data = validate_error(response, ApiErrorId.ERR_OFFER_EXPIRED, 409)
    assert data["error_id"] != "ERR_INVALID_REQUEST"

    assert validate_success(
        api.list_consumer_consent_records(ctx["consumer"]["id"], PLATFORM_ADMIN), 200
    ) == []
    assert read_decision(ctx["decision"]["id"], api=api)["decision_status"] == "PREQUALIFIED"


def test_present_on_the_29th_day_succeeds_and_on_the_30th_day_fails(api, as_consumer):
    """PRD §3.5: "it stamps `decided_at` with the logical clock and `fresh_until` with
    `decided_at` plus 30 days."
    PRD §3.7: "The decision's `fresh_until` must not have passed, or the create is
    refused with `ERR_OFFER_EXPIRED`."

    Design: Difficulty/boundary_precision_check/prequal_freshness_expires_exactly_at_thirty_days
    """
    from test_helpers.fixtures import complete_render_facets, present_decision

    ctx = setup_prequalified_scenario(api=api)
    qualify_decision(ctx["decision"]["id"], api=api)
    complete_render_facets(ctx["consumer"]["id"], run_key="seed-boundary", api=api)

    decision = read_decision(ctx["decision"]["id"], api=api)
    assert decision["fresh_until"].startswith("2026-10-01T00:00:00")

    advance_clock("2026-09-29T00:00:00Z", api=api)
    fresh_offer = present_decision(ctx["decision"]["id"], ctx["consumer"]["id"], api=api)
    assert fresh_offer["status"] == "PRESENTED"

    advance_clock("2026-10-01T00:00:00Z", api=api)
    response = api.present_decision(
        ctx["decision"]["id"], {"channel": "WEB"}, as_consumer(ctx["consumer"]["id"])
    )
    validate_error(response, ApiErrorId.ERR_OFFER_EXPIRED, 409)
    assert read_decision(ctx["decision"]["id"], api=api)["decision_status"] == "PREQUALIFIED"


def test_present_one_day_past_the_boundary_also_fails(api, as_consumer):
    """PRD §3.5: "Expiry closes the branch permanently: once `fresh_until` has passed,
    the daily run moves the decision to `EXPIRED` and no consent record may thereafter
    be created for it."
    PRD §3.7: "The decision's `fresh_until` must not have passed, or the create is
    refused with `ERR_OFFER_EXPIRED`."

    Design: Difficulty/boundary_precision_check/prequal_freshness_expires_exactly_at_thirty_days
    """
    from test_helpers.fixtures import complete_render_facets

    ctx = setup_prequalified_scenario(api=api)
    qualify_decision(ctx["decision"]["id"], api=api)
    complete_render_facets(ctx["consumer"]["id"], run_key="seed-boundary-2", api=api)
    advance_clock("2026-10-02T00:00:00Z", api=api)

    response = api.present_decision(
        ctx["decision"]["id"], {"channel": "WEB"}, as_consumer(ctx["consumer"]["id"])
    )
    validate_error(response, ApiErrorId.ERR_OFFER_EXPIRED, 409)


def test_rendering_requires_the_offer_to_be_presented(api, as_consumer):
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
        api.list_consumer_offer_presentation_caps(ctx["consumer"]["id"], PLATFORM_ADMIN, params=None),
        200,
    )
    assert len(caps) == 1
    assert caps[0]["product_kind"] == "LOAN"


def test_referral_creation_is_immediately_visible_on_the_next_read(api, as_consumer):
    """PRD §2.10: "`updated_at` is the same format and moves on every mutation,
    including mutations performed by the server itself during a daily run rather than
    by a client request."

    Design: Corner/cross_cutting_layers/every_write_in_the_funnel_is_atomically_visible
    """
    ctx = setup_consented_scenario(api=api)
    referral = create_referral_for(ctx, external_referral_ref="NS-L-9800", api=api)
    assert referral["status"] == "SENT"
    assert referral["revenue_share_bps"] == 1000

    assert read_decision(ctx["decision"]["id"], api=api)["decision_status"] == "CONSUMED"
    assert read_offer(ctx["offer"]["id"], api=api)["status"] == "CONSUMED"
    records = validate_success(
        api.list_consumer_consent_records(ctx["consumer"]["id"], PLATFORM_ADMIN), 200
    )
    assert records[0]["status"] == "SEALED"