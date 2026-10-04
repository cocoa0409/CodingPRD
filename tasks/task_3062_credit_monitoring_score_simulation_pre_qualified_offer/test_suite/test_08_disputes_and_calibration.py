"""Dispute referrals, calibration reads and derived catalog economics."""
from test_helpers import ApiErrorId, validate_error, validate_success
from test_helpers.factories import (
    create_dispute_referral_payload,
    create_referral_payload,
    create_targeting_criterion_payload,
)
from test_helpers.fixtures import (
    LENDER_OPS,
    PLATFORM_ADMIN,
    REFEREE,
    advance_clock,
    create_active_catalog_item,
    create_active_lender,
    create_active_program,
    create_active_score_tier,
    create_decision,
    create_referral_for,
    decline_referral,
    fund_referral,
    pull_bureau_snapshot,
    read_decision,
    reset_clock,
    setup_catalog_scenario,
    setup_consented_scenario,
    setup_monitored,
)


def test_dispute_referral_round_trips_through_the_list_routes(api, as_consumer):
    """PRD §3.9: "the `education_code` is not authored: it is computed on read as a
    lowercase snake_case token equal to the `inaccuracy_type`".
    PRD §3.9: "The draft starts in status `DRAFT` with `referral_count` at 0".

    Design: Corner/endpoints/dispute_referral_create_read_and_list_round_trip
    """
    ctx = setup_monitored(api=api)
    drafted = validate_success(
        api.create_dispute_referral(
            create_dispute_referral_payload(ctx["consumer"]["id"], ctx["snapshot"]["id"]), REFEREE
        ),
        201,
    )

    assert drafted["status"] == "DRAFT"
    assert drafted["referral_count"] == 0
    assert drafted["education_code"] == "account_info"
    assert drafted["narrative"] == (
        "An account that was closed in 2023 still reports an open balance on this file."
    )

    by_consumer = validate_success(
        api.list_dispute_referrals(REFEREE, params={"consumer_id": ctx["consumer"]["id"]}), 200
    )
    by_snapshot = validate_success(
        api.list_dispute_referrals(REFEREE, params={"snapshot_id": ctx["snapshot"]["id"]}), 200
    )
    assert [d["id"] for d in by_consumer] == [drafted["id"]]
    assert [d["id"] for d in by_snapshot] == [drafted["id"]]


def test_dispute_branch_forks_off_without_consuming_the_referral(api, as_consumer):
    """PRD §3.9: "A successful submission stamps `referral_id` with the supplied value,
    sets `referral_count` to 1, moves the dispute to `SUBMITTED_OFFLINE`, and increments
    the consumer's `open_dispute_count`."

    Design: Difficulty/non_linear_state_machine/referral_fork_join_with_divergent_side_effects
    """
    ctx = setup_consented_scenario(api=api)
    referral = create_referral_for(ctx, external_referral_ref="NS-L-9007", api=api)
    dispute = validate_success(
        api.create_dispute_referral(
            create_dispute_referral_payload(ctx["consumer"]["id"], ctx["snapshot"]["id"]), REFEREE
        ),
        201,
    )

    submitted = validate_success(
        api.submit_dispute_referral(dispute["id"], {"referral_id": referral["id"]}, REFEREE), 200
    )
    assert submitted["status"] == "SUBMITTED_OFFLINE"
    assert submitted["referral_count"] == 1

    still_sent = validate_success(api.get_referral(referral["id"], PLATFORM_ADMIN), 200)
    assert still_sent["status"] == "SENT", "the dispute branch must not consume the referral"


def test_decline_branch_releases_the_consent_without_recognizing_revenue(api, as_consumer):
    """PRD §3.8: "a `LenderOps` operator declines a referral in `SENT`, the status
    becomes `DECLINED`, the consent is released to `NOT_SEALED`, and the catalog item's
    calibration index is recomputed with the declined outcome."

    Design: Difficulty/non_linear_state_machine/referral_fork_join_with_divergent_side_effects
    """
    ctx = setup_consented_scenario(api=api)
    referral = create_referral_for(ctx, external_referral_ref="NS-L-9008", api=api)
    declined = decline_referral(referral["id"], api=api)

    assert declined["status"] == "DECLINED"
    records = validate_success(
        api.list_consumer_consent_records(ctx["consumer"]["id"], PLATFORM_ADMIN), 200
    )
    assert records[0]["status"] == "NOT_SEALED"
    assert records[0]["consumer_pii_ciphertext"] is None
    assert validate_success(
        api.list_referral_revenue_entries(referral["id"], PLATFORM_ADMIN), 200
    ) == []


def test_aggregate_dispute_cap_blocks_the_fourth_submission(api, as_consumer):
    """PRD §3.9: "the consumer must hold fewer than 3 (`PENDING_DISPUTE_CAP`) dispute
    referrals in status `SUBMITTED_OFFLINE` at that moment — a fourth concurrent
    submission is refused with `ERR_DISPUTE_CAP_EXCEEDED`."

    Design: Corner/validations/aggregate_dispute_cap_blocks_the_fourth_submission
    """
    ctx = setup_consented_scenario(api=api)
    referral = create_referral_for(ctx, external_referral_ref="NS-L-9100", api=api)

    disputes = []
    for index, inaccuracy in enumerate(["ACCOUNT_INFO", "PERSONAL_INFO", "INQUIRY", "BALANCE"]):
        disputes.append(validate_success(
            api.create_dispute_referral(
                create_dispute_referral_payload(
                    ctx["consumer"]["id"], ctx["snapshot"]["id"], inaccuracy_type=inaccuracy,
                    narrative=f"Dispute number {index} reports an inaccuracy on this file.",
                ),
                REFEREE,
            ),
            201,
        ))

    for dispute in disputes[:3]:
        validate_success(
            api.submit_dispute_referral(dispute["id"], {"referral_id": referral["id"]}, REFEREE),
            200,
        )

    refused = api.submit_dispute_referral(
        disputes[3]["id"], {"referral_id": referral["id"]}, REFEREE
    )
    validate_error(refused, ApiErrorId.ERR_DISPUTE_CAP_EXCEEDED, 409)

    consumer = validate_success(
        api.get_consumer(ctx["consumer"]["id"], PLATFORM_ADMIN), 200
    )
    assert consumer["open_dispute_count"] == 3


def test_drafts_do_not_count_toward_open_disputes(api, as_consumer):
    """PRD §2.6: "The consumer's `open_dispute_count` is likewise derived: it counts
    the `DisputeReferral` rows in status `SUBMITTED_OFFLINE` or `ACKNOWLEDGED_BY_BUREAU`."

    Design: Corner/validations/aggregate_dispute_cap_blocks_the_fourth_submission
    """
    ctx = setup_monitored(api=api)
    for index, inaccuracy in enumerate(["ACCOUNT_INFO", "PERSONAL_INFO", "INQUIRY", "BALANCE"]):
        drafted = validate_success(
            api.create_dispute_referral(
                create_dispute_referral_payload(
                    ctx["consumer"]["id"], ctx["snapshot"]["id"], inaccuracy_type=inaccuracy,
                    narrative=f"Draft number {index} reports an inaccuracy on this file.",
                ),
                REFEREE,
            ),
            201,
        )
        assert drafted["status"] == "DRAFT"
        assert drafted["education_code"] == inaccuracy.lower()

    consumer = validate_success(
        api.get_consumer(ctx["consumer"]["id"], PLATFORM_ADMIN), 200
    )
    assert consumer["open_dispute_count"] == 0


def test_scoring_a_facet_below_the_minimum_is_refused(api, as_consumer):
    """PRD §3.9: "A content quality facet must reach 8000 basis points
    (`CONTENT_QUALITY_MIN`) of authoring completeness to count as `COMPLETE`; a facet
    scored below that line cannot reach `COMPLETE` at all and the attempt is refused
    with `ERR_FACET_SCORE_BELOW_MINIMUM`."

    Design: Corner/validations/conditional_facet_gate_applies_only_below_the_content_minimum
    """
    from test_helpers.factories import create_content_quality_facet_payload

    ctx = setup_monitored(api=api)
    facet = validate_success(
        api.create_content_quality_facet(
            ctx["consumer"]["id"],
            create_content_quality_facet_payload(topic="factor_explanations", score_bps=9000),
            REFEREE,
        ),
        201,
    )
    assert facet["status"] == "COMPLETE"

    refused = api.score_content_quality_facet(facet["id"], {"score_bps": 7999}, REFEREE)
    validate_error(refused, ApiErrorId.ERR_FACET_SCORE_BELOW_MINIMUM, 409)

    unchanged = validate_success(
        api.list_consumer_content_quality_facets(ctx["consumer"]["id"], REFEREE), 200
    )[0]
    assert unchanged["score_bps"] == 9000
    assert unchanged["status"] == "COMPLETE"


def test_a_facet_scored_exactly_at_the_minimum_stays_complete(api, as_consumer):
    """PRD §3.2: "the facet's `status` is set to `COMPLETE` when that score is at least
    8000, and to `INCOMPLETE` otherwise."

    Design: Corner/validations/conditional_facet_gate_applies_only_below_the_content_minimum
    """
    from test_helpers.factories import create_content_quality_facet_payload

    ctx = setup_monitored(api=api)
    facet = validate_success(
        api.create_content_quality_facet(
            ctx["consumer"]["id"],
            create_content_quality_facet_payload(topic="factor_explanations", score_bps=9000),
            REFEREE,
        ),
        201,
    )
    rescored = validate_success(
        api.score_content_quality_facet(facet["id"], {"score_bps": 8000}, REFEREE), 200
    )
    assert rescored["score_bps"] == 8000
    assert rescored["status"] == "COMPLETE"


def test_adverse_action_summary_is_computed_from_a_single_snapshot(api, as_consumer):
    """PRD §3.2: "Volatility is computed over every snapshot of the consumer whose
    status is `ACTIVE` or `SUPERSEDED`, read in `snapshot_ordinal` ascending order."
    PRD §3.2: "`volatility_points` is the largest delta in that series minus the
    smallest, and it is 0 when fewer than two deltas exist".
    PRD §3.2: "`drift_points` is the last snapshot's score minus the first snapshot's
    score, a plain net movement across the consumer's whole observed history."

    Design: Corner/endpoints/adverse_action_summary_returns_the_derived_aggregate
    """
    ctx = setup_monitored(api=api, score=660)
    summary = validate_success(
        api.get_adverse_action_summary(ctx["consumer"]["id"], as_consumer(ctx["consumer"]["id"])),
        200,
    )

    assert summary["volatility_points"] == 0
    assert summary["drift_points"] == 0
    assert summary["current_score"] == 660
    assert summary["previous_score"] is None
    assert summary["education_topics_consumed"] == []

    # A second pull makes a one-element delta series, so volatility stays 0 by the
    # "< two deltas" rule while drift is the net movement across the history.
    advance_clock("2026-09-02T00:00:00Z", api=api)
    pull_bureau_snapshot(ctx["consumer"]["id"], score=700, api=api)
    trended = validate_success(
        api.get_adverse_action_summary(ctx["consumer"]["id"], as_consumer(ctx["consumer"]["id"])),
        200,
    )
    assert trended["volatility_points"] == 0
    assert trended["drift_points"] == 40


def test_calibration_index_is_null_when_no_outcome_succeeded(api, as_consumer):
    """PRD §3.8: "When the considered set is empty, or when it contains no successes
    at all, the index is null — the metric is undefined, and it is never reported as 0
    or as 1."
    PRD §3.8: "For a given catalog item, the index is computed over every
    `PreQualificationDecision` whose pinned program points at that item, considering
    decisions in status `NEEDS_SNAPSHOT`, `ELIGIBLE`, `INELIGIBLE`, `PREQUALIFIED`,
    `CONSENTED` or `CONSUMED`, and excluding every decision in status `EXPIRED`."

    Design: Difficulty/combinatorial_formula/calibration_index_zero_success_guard_and_null_branch
    """
    ctx = setup_consented_scenario(api=api)
    referral = create_referral_for(ctx, external_referral_ref="NS-L-9005", api=api)
    decline_referral(referral["id"], api=api)

    provisional = validate_success(
        api.get_catalog_item(ctx["item"]["id"], PLATFORM_ADMIN), 200
    )
    settled = validate_success(
        api.get_catalog_item_settled_index(ctx["item"]["id"], PLATFORM_ADMIN), 200
    )

    assert provisional["approval_odds_calibration_index"] is None
    assert settled["approval_odds_calibration_index"] is None
    assert provisional["realized_rate"] == 0.0
    assert settled["realized_rate"] == 0.0


def test_calibration_index_excludes_expired_decisions(api, as_consumer):
    """PRD §3.8: "considering decisions in status `NEEDS_SNAPSHOT`, `ELIGIBLE`,
    `INELIGIBLE`, `PREQUALIFIED`, `CONSENTED` or `CONSUMED`, and excluding every
    decision in status `EXPIRED`."
    PRD §3.8: "When the considered set is empty, or when it contains no successes at
    all, the index is null".

    Design: Difficulty/combinatorial_formula/calibration_index_zero_success_guard_and_null_branch
    """
    ctx = setup_consented_scenario(api=api)
    referral = create_referral_for(ctx, external_referral_ref="NS-L-9005B", api=api)
    decline_referral(referral["id"], api=api)

    # A second decision on the same item, left open and then swept into EXPIRED.
    other = setup_monitored_secondary(api=api, program_id=ctx["program"]["id"])
    stale_decision = create_decision(other["consumer"]["id"], ctx["program"]["id"], api=api)
    assert stale_decision["decision_status"] == "ELIGIBLE"

    advance_clock("2026-11-01T00:00:00Z", api=api)
    validate_success(api.run_ops({"run_key": "expire-sweep"}, PLATFORM_ADMIN), 201)

    assert read_decision(stale_decision["id"], api=api)["decision_status"] == "EXPIRED"

    provisional = validate_success(
        api.get_catalog_item(ctx["item"]["id"], PLATFORM_ADMIN), 200
    )
    assert provisional["decision_count"] == 1
    assert provisional["approval_odds_calibration_index"] is None


def setup_monitored_secondary(api, program_id):
    """A second consented consumer with an ACTIVE snapshot, on an existing program."""
    from test_helpers.fixtures import create_monitored_consumer

    consumer, snapshot = create_monitored_consumer(
        score=660, balance_cents=480_000, email="second@example.com", bureau_pin="9911", api=api
    )
    return {"consumer": consumer, "snapshot": snapshot, "program_id": program_id}