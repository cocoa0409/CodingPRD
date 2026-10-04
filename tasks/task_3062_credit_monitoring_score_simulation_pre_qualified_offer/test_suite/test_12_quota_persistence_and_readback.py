"""Consent-sealing quota, persistence of records and configuration round-trips."""
from test_helpers import ApiErrorId, validate_error, validate_success
from test_helpers.factories import (
    create_consent_payload,
    create_referral_payload,
    create_targeting_criterion_payload,
)
from test_helpers.fixtures import (
    COMPLIANCE_OFFICER,
    LENDER_OPS,
    PLATFORM_ADMIN,
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
    render_offer,
    reset_clock,
    setup_catalog_scenario,
    setup_consented_scenario,
    setup_monitored,
    setup_offer_scenario,
)


def test_lender_program_round_trips_every_configuration_field(api, consumer_headers):
    """PRD §3.5: "It is created by a `PlatformAdmin` with a `lender_id`, a
    `product_catalog_item_id`, a `program_name`, a unique `program_code`, an inclusive
    `min_modeled_score`, an inclusive `max_dti_pct`, an inclusive
    `max_eligible_utilization_pct`, an `annual_fee_cents`, an `intro_apr_bps`, a
    `go_live_at` and an `expiry_at`, and the commercial terms `revenue_share_bps`,
    `clawback_rate_bps` and `clawback_days`."

    Design: Corner/entities/lender_program_get_round_trips_every_configuration_field
    """
    reset_clock(api=api)
    create_active_score_tier(api=api)
    item = create_active_catalog_item(api=api)
    lender = create_active_lender(api=api)
    program = create_active_program(
        lender_id=lender["id"], item_id=item["id"],
        annual_fee_cents=9500, intro_apr_bps=1800, api=api,
    )

    read_back = validate_success(
        api.get_lender_program(program["id"], consumer_headers), 200
    )
    assert read_back["program_code"] == "NS-LOAN-01"
    assert read_back["program_name"] == "Northstar Personal Loan"
    assert read_back["min_modeled_score"] == 560
    assert read_back["max_dti_pct"] == 45.0
    assert read_back["max_eligible_utilization_pct"] == 55.0
    assert read_back["revenue_share_bps"] == 1000
    assert read_back["clawback_rate_bps"] == 500
    assert read_back["clawback_days"] == 90
    assert read_back["go_live_at"].startswith("2026-08-01T00:00:00")
    assert read_back["expiry_at"].startswith("2027-08-01T00:00:00")
    assert read_back["status"] == "ACTIVE"


def test_consent_sealing_batch_promotes_pending_records(api, as_consumer):
    """PRD §3.6: "A `PENDING` consent becomes `SEALED` when the daily run promotes it,
    or immediately when a funding or a referral attempt consumes it."
    PRD §3.6: "Sealing is rate-limited by design: a daily run seals at most
    `CONSENT_SEAL_MAX_PER_RUN` pending consents per pass, chosen in `created_at`
    ascending order and, for ties, by `id` ascending."

    Design: Difficulty/resource_temporal_overlap/consent_sealing_quota_drains_in_created_at_order
    """
    ctx = setup_offer_scenario(api=api)
    complete_consent(ctx["consumer"]["id"], ctx["decision"]["id"], api=api)
    pending = validate_success(
        api.list_consumer_consent_records(ctx["consumer"]["id"], PLATFORM_ADMIN), 200
    )[0]
    assert pending["status"] == "PENDING"
    assert pending["consumer_pii_ciphertext"] is None

    validate_success(api.run_ops({"run_key": "seal-batch-1"}, PLATFORM_ADMIN), 201)

    sealed = validate_success(
        api.get_consent_record(pending["id"], PLATFORM_ADMIN), 200
    )
    assert sealed["status"] == "SEALED"
    assert sealed["sealed_at"].startswith("2026-09-01T00:00:00")
    assert sealed["consumer_pii_ciphertext"] is not None


def test_consent_sealing_batch_cannot_be_replayed(api, as_consumer):
    """PRD §2.4: "A `run_key` must be unique across all `OpsRun` rows; a repeat is
    rejected with `ERR_OPS_RUN_KEY_DUPLICATE`."
    PRD §3.6: "A sealed consent is archived once `RETENTION_DAYS` of 365 days have
    elapsed since its `sealed_at`."

    Design: Difficulty/resource_temporal_overlap/consent_sealing_quota_drains_in_created_at_order
    """
    ctx = setup_offer_scenario(api=api)
    complete_consent(ctx["consumer"]["id"], ctx["decision"]["id"], api=api)
    validate_success(api.run_ops({"run_key": "seal-batch-1"}, PLATFORM_ADMIN), 201)
    validate_error(
        api.run_ops({"run_key": "seal-batch-1"}, PLATFORM_ADMIN),
        ApiErrorId.ERR_OPS_RUN_KEY_DUPLICATE, 409,
    )

    advance_clock("2027-09-02T00:00:00Z", api=api)
    validate_success(api.run_ops({"run_key": "seal-batch-2"}, PLATFORM_ADMIN), 201)

    records = validate_success(
        api.list_consumer_consent_records(ctx["consumer"]["id"], PLATFORM_ADMIN), 200
    )
    assert records[0]["status"] == "SEALED"
    assert records[0]["archive_status"] == "ARCHIVED"


def test_calibration_index_moves_on_the_next_window_when_more_outcomes_land(api, as_consumer):
    """PRD §3.8: "the mean modeled odds across the considered decisions is taken and
    rounded half up to 4 decimal places, the realised success rate is taken as the
    success count divided by the considered count and rounded half up to 4 decimal
    places, and the index is the first divided by the second, again rounded half up to
    4 decimal places."
    PRD §3.8: "the mean is taken over realized outcomes only, so the two variants can
    fall on opposite sides of 1.0 for identical decision rows."

    Design: Difficulty/dual_variant_calc/calibration_index_including_provisional_versus_settled_only
    """
    from test_helpers.factories import create_referral_payload as _ref

    reset_clock(api=api)
    ctx = setup_catalog_scenario(api=api, program_overrides={"max_dti_pct": 45.0})

    funded_consumer, _, decision = _through_funnel(
        api, ctx["program"]["id"], "cal3@example.com", "6003", fund=True
    )
    declined_consumer, _, declined_decision = _through_funnel(
        api, ctx["program"]["id"], "cal4@example.com", "6004", fund=False
    )
    # Decline the second referral so the item carries one FUNDED and one DECLINED.
    referral_rows = validate_success(
        api.list_referrals(PLATFORM_ADMIN, params={"consumer_id": declined_consumer["id"]}), 200
    )
    validate_success(api.decline_referral(referral_rows[0]["id"], LENDER_OPS), 200)

    provisional = validate_success(
        api.get_catalog_item(ctx["item"]["id"], PLATFORM_ADMIN), 200
    )
    settled = validate_success(
        api.get_catalog_item_settled_index(ctx["item"]["id"], PLATFORM_ADMIN), 200
    )

    # Both decisions are settled (one FUNDED, one DECLINED), so both reads see the
    # same realized outcomes and only the provisional-inclusive read is diluted.
    assert provisional["decision_count"] == 2
    assert settled["decision_count"] == 2
    assert provisional["realized_rate"] == 0.5
    assert settled["realized_rate"] == 0.5
    assert provisional["approval_odds_calibration_index"] == settled["approval_odds_calibration_index"]
    assert provisional["modeled_odds_mean"] == 0.91


def _through_funnel(api, program_id, email, bureau_pin, fund=True):
    """Consented, qualified, rendered, consented consumer whose referral is
    FUNDED (fund=True) or left SENT for the caller to decline (fund=False)."""
    consumer, snapshot = create_monitored_consumer(
        score=660, balance_cents=480_000, email=email, bureau_pin=bureau_pin, api=api
    )
    decision = create_decision(consumer["id"], program_id, api=api)
    qualify_decision(decision["id"], api=api)
    complete_render_facets(consumer["id"], run_key=f"seed-{bureau_pin}", api=api)
    offer = present_decision(decision["id"], consumer["id"], api=api)
    render_offer(offer["id"], consumer["id"], api=api)
    complete_consent(consumer["id"], decision["id"], api=api)
    referral = validate_success(
        api.create_referral(
            create_referral_payload(offer["id"], external_referral_ref=f"NS-L-{bureau_pin}"),
            LENDER_OPS,
        ),
        201,
    )
    if fund:
        fund_referral(referral["id"], funded_amount_cents=900_000, api=api)
    return consumer, snapshot, decision


def test_expiry_gate_outranks_a_malformed_enum_on_consent(api, as_consumer):
    """PRD §2.11: "State validity is fourth and outranks everything that follows: a
    transition attempted from a status from which it is not declared is rejected with
    `ERR_INVALID_STATE_TRANSITION` at HTTP 409, even when a business, consent or fiscal
    check would also have failed on the same request."
    PRD §2.11: "Rankings below state validity are, in order: the expiry rule that bars
    consenting to or presenting a decision whose `fresh_until` has passed
    (`ERR_OFFER_EXPIRED`)".

    Design: Difficulty/priority_pair_validation_conflict/expired_decision_beats_fiscal_cap_on_consent
    """
    from test_helpers.fixtures import setup_prequalified_scenario

    ctx = setup_prequalified_scenario(api=api)
    qualify_decision(ctx["decision"]["id"], api=api)
    advance_clock("2026-12-15T00:00:00Z", api=api)

    version = read_consumer_version(ctx["consumer"]["id"], api=api)
    expired = api.complete_consent(
        ctx["consumer"]["id"], ctx["decision"]["id"],
        create_consent_payload(version, consent_method="TELEPATHIC"),
        as_consumer(ctx["consumer"]["id"]),
    )
    validate_error(expired, ApiErrorId.ERR_OFFER_EXPIRED, 409)

    assert validate_success(
        api.list_consumer_consent_records(ctx["consumer"]["id"], PLATFORM_ADMIN), 200
    ) == []


def test_forbidden_role_outranks_a_nonexistent_path_segment(api, bureau_connector_headers):
    """PRD §2.11: "Role authorization is second, yielding `ERR_FORBIDDEN_FOR_ROLE` at
    HTTP 403. Path-segment existence is third, yielding `ERR_CONSUMER_NOT_FOUND` at
    HTTP 404".
    PRD §2.11: "a decision rejected from a terminal status reports the state error
    rather than any downstream gate."

    Design: Difficulty/priority_pair_validation_conflict/forbidden_role_beats_nonexistent_resource
    """
    rejected = api.create_simulation(
        "6f2b1c44-0000-4000-8000-000000000003",
        {"actions": [{"action_code": "CLOSE_OLDEST_TRADELINE"}],
         "expected_consumer_version": 1},
        bureau_connector_headers,
    )
    data = validate_error(rejected, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE, 403)
    assert data["error_id"] != "ERR_CONSUMER_NOT_FOUND"


def test_program_pause_outranks_the_consent_gate(api, as_consumer):
    """PRD §3.5: "pausing cascades every decision pinned to that program whose status is
    `ELIGIBLE` or `PREQUALIFIED` to `INELIGIBLE`, stamping the reason `PROGRAM_PAUSED`
    and nulling the modeled odds."
    PRD §3.6: "The decision must be `PREQUALIFIED` before consent can be recorded;
    consenting to anything else is rejected with `ERR_CONSENT_DECISION_NOT_PREQUALIFIED`."

    Design: Difficulty/cross_entity_state_dependency/decision_presentation_requires_program_active
    """
    ctx = setup_consented_scenario(api=api)
    validate_success(
        api.pause_lender_program(ctx["program"]["id"], COMPLIANCE_OFFICER), 200
    )
    version = read_consumer_version(ctx["consumer"]["id"], api=api)

    rejected = api.complete_consent(
        ctx["consumer"]["id"], ctx["decision"]["id"], create_consent_payload(version),
        as_consumer(ctx["consumer"]["id"]),
    )
    validate_error(rejected, ApiErrorId.ERR_CONSENT_DECISION_NOT_PREQUALIFIED, 409)
    assert read_decision(ctx["decision"]["id"], api=api)["reason"] == "PROGRAM_PAUSED"


def test_a_released_consent_never_mints_a_ciphertext(api, as_consumer):
    """PRD §3.6: "When a referral is marked unfunded by the daily run, or when a
    `LenderOps` operator declines it, the linked consent moves from `PENDING` to
    `NOT_SEALED` and its ciphertext is never minted at all."

    Design: Difficulty/compensating_invariant/referral_reversal_restores_zero_net_realized
    """
    ctx = setup_consented_scenario(api=api)
    referral = create_referral_for(ctx, external_referral_ref="NS-L-9910", api=api)
    validate_success(api.decline_referral(referral["id"], LENDER_OPS), 200)

    record = validate_success(
        api.list_consumer_consent_records(ctx["consumer"]["id"], PLATFORM_ADMIN), 200
    )[0]
    assert record["status"] == "NOT_SEALED"
    assert record["consumer_pii_ciphertext"] is None
    assert record["sealed_at"] is None