"""The two write guards that read a version, and the two thresholds that are struck exactly.

Only screening ingest and manual enforcement carry a version pin, and both of them are
repeatable operations where the pin is the sole defence against acting on a row that has
moved. The last test walks the enforcement ladder across its own inclusive lower bounds,
where an implementation that used a strict comparison, or that forgot the escalation
surcharge, would mint the wrong action or none at all.
"""

import pytest

from test_helpers import (
    ADMIN,
    ApiErrorId,
    api_client,
    assert_instant_equals,
    factories,
    fixtures,
    make_advertiser_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

PROH_WEAPONS = "PROH_WEAPONS"
SEV_TEN = "SEV_TEN"
SEV_ELEVEN = "SEV_ELEVEN"


def test_a_classifier_run_is_pinned_to_the_text_it_read_across_the_revision_loop():
    """PRD §2.7: "If that value does not equal the creative's current `version`, the run is
    rejected with `ERR_STALE_CREATIVE_VERSION` (HTTP 412) and nothing is written."

    PRD §3.4: "An accepted run records `ad_creative_id`, takes `sequence_index` as one
    greater than the highest index already used on that creative — so indices are contiguous
    from 1 and the greatest index is always the latest run — and snapshots the creative's
    `version` at acceptance into `creative_version_at_run`."

    PRD §3.4: "For each finding, take the matched rule's `base_severity_weight`, multiply it
    by the country multiplier of that rule for this creative, and multiply the result by the
    finding's own `confidence`; keep each of those products unrounded, add them all together,
    round the single total half-up to 2 decimals, and cap the outcome at 100.00."

    PRD §3.4: "First, the outcome is `AUTO_DISAPPROVED` when some decision in the run has
    disposition `AUTO_DISAPPROVE` and the strictest disposition of that decision's rule for
    this creative is `BLOCKED`."

    PRD §3.1: "Finally, the **disposition of a rule in a country** is that country
    variation's `disposition` when a variation exists; when none exists it falls back to the
    rule's tier — `BLOCKED` for a `PROHIBITED` rule, `RESTRICTED_CERT_REQUIRED` for a
    `RESTRICTED` rule and `ALLOWED` for a `REGULATED` rule."

    Design: Corner/From Cross-Cutting Complexity Layers/occ_a_screening_run_against_a_stale_creative_version_is_rejected_across_the_revision_loop
    """
    rule = fixtures.create_policy_rule(
        PROH_WEAPONS,
        "PROHIBITED",
        12.00,
        title="Weapons and firearms",
        requires_certification=False,
        confidence_auto_disapprove_threshold=0.90,
        confidence_manual_threshold=0.20,
        default_queue="STANDARD",
    )
    advertiser = fixtures.create_verified_advertiser(
        legal_name="Ridgeline Outfitters",
        country_code="US",
        industry_code="SPORTING_GOODS",
    )
    advertiser_id = advertiser["id"]
    author = make_advertiser_headers(advertiser_id)
    draft = fixtures.create_creative(
        advertiser_id,
        [PROH_WEAPONS],
        ["US"],
        headline="Range day gear",
        body_text="Range day gear and accessories for the whole season.",
        landing_page_url="https://www.ridgeline.example/range",
        display_url="https://www.ridgeline.example/range",
    )
    assert draft["version"] == 1
    submitted = fixtures.submit_creative(draft["id"], advertiser_id)
    assert submitted["version"] == 2

    def ingest(confidence, snippet, expected_version, classifier_version):
        return api_client.create_screening_run(
            draft["id"],
            factories.create_screening_run_payload(
                [
                    factories.classifier_decision_payload(
                        rule["id"], confidence, snippet
                    )
                ],
                expected_version,
                classifier_version=classifier_version,
            ),
            ADMIN,
        )

    # The version the classifier saw before submission is already one write behind.
    validate_error(
        ingest(0.95, "range day gear", 1, "clf-2026.07"),
        ApiErrorId.ERR_STALE_CREATIVE_VERSION,
        412,
    )
    first_run = validate_success(
        ingest(0.95, "range day gear", 2, "clf-2026.07"), 201
    )
    assert first_run["sequence_index"] == 1
    assert first_run["creative_version_at_run"] == 2
    assert first_run["outcome"] == "AUTO_DISAPPROVED"
    assert first_run["provisional_risk_score"] == pytest.approx(11.40, abs=0.01)

    revised = validate_success(
        api_client.revise_ad_creative(
            draft["id"],
            factories.revise_ad_creative_payload(headline="Range day accessories"),
            author,
        ),
        200,
    )
    assert revised["review_status"] == "DRAFT"
    assert revised["version"] == 4
    resubmitted = fixtures.submit_creative(draft["id"], advertiser_id)
    assert resubmitted["version"] == 5

    # The same pin that worked a moment ago is stale once the text moves again.
    validate_error(
        ingest(0.50, "range day accessories", 4, "clf-2026.08"),
        ApiErrorId.ERR_STALE_CREATIVE_VERSION,
        412,
    )
    second_run = validate_success(
        ingest(0.50, "range day accessories", 5, "clf-2026.08"), 201
    )
    assert second_run["sequence_index"] == 2
    assert second_run["creative_version_at_run"] == 5
    assert second_run["outcome"] == "ROUTED_MANUAL"
    assert second_run["provisional_risk_score"] == pytest.approx(6.00, abs=0.01)

    runs, run_page = validate_paginated(
        api_client.list_screening_runs(draft["id"], ADMIN)
    )
    assert run_page["total_count"] == 2, "a refused ingest left a run behind"
    assert [row["sequence_index"] for row in runs] == [1, 2]

    stored = fixtures.read_creative(draft["id"], advertiser_id=advertiser_id)
    # One create, one submit, one run, one revision, one submit, one run.
    assert stored["version"] == 6
    assert stored["screening_run_count"] == 2
    assert stored["review_status"] == "PENDING_MANUAL_REVIEW"

    tasks = fixtures.list_tasks_for_creative(draft["id"])
    assert len(tasks) == 1
    assert tasks[0]["status"] == "QUEUED"
    assert tasks[0]["queue"] == "STANDARD"

    # 12.00 * 1.00 * 0.80 from the automatic notice the first run issued.
    entries = fixtures.ledger_for_advertiser(advertiser_id)
    assert len(entries) == 1
    assert entries[0]["delta_points"] == pytest.approx(9.60, abs=0.01)
    assert fixtures.read_advertiser(advertiser_id)["account_status"] == "ACTIVE"


def test_a_stale_enforcement_mint_is_reported_ahead_of_the_cooldown_conflict():
    """PRD §2.7: "Minting a manual enforcement action — `POST
    /ad-policy/advertisers/{id}/enforcement-actions` — requires `expected_advertiser_version`
    in the body, carrying the `version` of the `Advertiser` the operator read before
    deciding."

    PRD §2.7: "If that value does not equal the advertiser's current `version`, the action is
    rejected with `ERR_STALE_ADVERTISER_VERSION` (HTTP 412)."

    PRD §3.10: "A manual action is additionally blocked by a cooldown: the new
    `effective_from` — the logical clock — may not fall inside the blackout window of any
    existing action on the advertiser, where that window runs from that action's
    `effective_from` through its `effective_until` extended by a further 72 hours, inclusive
    at both ends, and where existing actions in every status — `ACTIVE`, `LIFTED`, `EXPIRED`
    and `SUPERSEDED` — are considered."

    PRD §2.10: "10. Version pinning — `ERR_STALE_CREATIVE_VERSION`,
    `ERR_STALE_ADVERTISER_VERSION`."

    PRD §2.10: "25. Enforcement cooldown blackout — `ERR_ENFORCEMENT_COOLDOWN_CONFLICT`."

    Design: Corner/From Cross-Cutting Complexity Layers/occ_a_manual_enforcement_against_a_stale_advertiser_version_outranks_the_cooldown_conflict
    """
    advertiser = fixtures.create_advertiser(
        legal_name="Beacon Lending Co",
        country_code="US",
        industry_code="CONSUMER_FINANCE",
    )
    advertiser_id = advertiser["id"]
    assert advertiser["version"] == 1
    after_identity = fixtures.record_verification(
        advertiser_id, "IDENTITY", "VERIFIED"
    )
    assert after_identity["version"] == 2
    after_standing = fixtures.record_verification(
        advertiser_id, "BUSINESS_STANDING", "VERIFIED"
    )
    assert after_standing["version"] == 3

    def mint(action_type, trigger_reason, expected_version):
        return api_client.create_enforcement_action(
            advertiser_id,
            factories.create_enforcement_action_payload(
                action_type, expected_version, trigger_reason=trigger_reason
            ),
            ADMIN,
        )

    validate_error(
        mint("WARNING", "Filed against a version that is one write behind", 2),
        ApiErrorId.ERR_STALE_ADVERTISER_VERSION,
        412,
    )

    warning = validate_success(
        mint("WARNING", "Repeated late responses to policy correspondence", 3), 201
    )
    assert warning["status"] == "ACTIVE"
    assert warning["origin"] == "MANUAL"
    assert warning["severity_index_at_issue"] == pytest.approx(0.00, abs=0.01)
    assert_instant_equals(
        warning["effective_from"], "2026-08-01T00:00:00Z", "effective_from"
    )
    assert_instant_equals(
        warning["effective_until"], "2026-08-31T00:00:00Z", "effective_until"
    )
    warned = fixtures.read_advertiser(advertiser_id)
    assert warned["account_status"] == "WARNED"
    assert warned["version"] == 4

    # Stale and inside the blackout at once: the version pin answers first.
    validate_error(
        mint("RESTRICTION", "Both stale and inside the cooldown blackout", 3),
        ApiErrorId.ERR_STALE_ADVERTISER_VERSION,
        412,
    )
    # With the version correct, the cooldown finally gets to speak.
    validate_error(
        mint("RESTRICTION", "Correct version but still inside the cooldown blackout", 4),
        ApiErrorId.ERR_ENFORCEMENT_COOLDOWN_CONFLICT,
        409,
    )

    _rows, pagination = validate_paginated(
        api_client.list_enforcement_actions(ADMIN, {"advertiser_id": advertiser_id})
    )
    assert pagination["total_count"] == 1, "three refusals wrote nothing"
    assert fixtures.read_advertiser(advertiser_id)["version"] == 4


def test_the_index_lands_exactly_on_the_warning_and_then_the_restriction_threshold():
    """PRD §3.9: "Each finding line records the matched rule's code as its
    `policy_rule_code`, the source reason as its `reason_code`, and as its `line_points` the
    matched rule's `base_severity_weight` multiplied by the country multiplier of that rule
    for this creative and then multiplied by the reason factor of the source reason, rounded
    half-up to 2 decimals."

    PRD §3.9: "The reason factors are fixed: 0.80 for `AUTO_SCREENING`, 1.00 for
    `MANUAL_REVIEW`, 0.60 for `CERT_MISSING`, 2.00 for `CLOAKING`, 1.25 for
    `DESTINATION_MISMATCH` and 1.50 for `POLITICAL_DISCLOSURE`."

    PRD §3.9: "Step one computes a base index: count the advertiser's enforcement actions
    whose `status` is `SUPERSEDED`, `LIFTED` or `EXPIRED` — actions still in force are
    excluded, so a currently effective action never inflates its own successor's index —
    multiply that closed-action count by 5.00, add the advertiser's
    `violation_points_decayed`, and round the total half-up to 2 decimals."

    PRD §3.9: "Step two picks an escalation surcharge keyed on the base index *alone*: 0.00
    when the base index is below 20.00, 3.50 when it is at least 20.00 but below 35.00, and
    9.00 when it is 35.00 or more."

    PRD §3.9: "Step four selects an action type keyed on the post-surcharge `severity_index`:
    `SUSPENSION` when it is at least 40.00, otherwise `RESTRICTION` when it is at least
    25.00, otherwise `WARNING` when it is at least 10.00, and otherwise none at all."

    PRD §3.9: "Creating an action moves any existing `ACTIVE` action on the advertiser to
    `SUPERSEDED`, points the new action's `prior_action_id` at it, re-derives `account_status`
    and increments the advertiser's `version` by 1; a `SUSPENSION` additionally sweeps the
    advertiser's creatives to `SUSPENDED_HOLD` and expires their review tasks."

    PRD §3.9: "When `effective_until` is not supplied it defaults to `effective_from` plus
    the duration for the type: 30 days for a warning, 60 days for a restriction and 180 days
    for a suspension."

    Design: Corner/From Cross-Cutting Complexity Layers/rate_threshold_the_severity_index_lands_exactly_on_the_warning_and_restriction_thresholds
    """
    ten = fixtures.create_policy_rule(
        SEV_TEN,
        "REGULATED",
        10.00,
        title="Threshold rule at ten points",
        requires_certification=False,
        confidence_auto_disapprove_threshold=0.90,
        confidence_manual_threshold=0.20,
        default_queue="STANDARD",
    )
    eleven = fixtures.create_policy_rule(
        SEV_ELEVEN,
        "REGULATED",
        11.50,
        title="Threshold rule at eleven and a half points",
        requires_certification=False,
        confidence_auto_disapprove_threshold=0.90,
        confidence_manual_threshold=0.20,
        default_queue="STANDARD",
    )
    advertiser = fixtures.create_verified_advertiser(
        legal_name="Harbourline Media Ltd",
        country_code="US",
        industry_code="MEDIA_SERVICES",
    )
    advertiser_id = advertiser["id"]
    reviewer = fixtures.create_reviewer(
        ["STANDARD"],
        ["US"],
        display_name="Rev Threshold Desk",
        max_concurrent_claims=3,
    )
    reviewer_id = reviewer["id"]

    first_creative, first_task = fixtures.creative_in_manual_review(
        advertiser_id,
        [SEV_TEN],
        [(ten["id"], 0.50)],
        ["US"],
        headline="Harbourline spring offer",
        body_text="Harbourline spring offer with flexible monthly terms.",
        landing_page_url="https://www.harbourline.example/spring",
        display_url="https://www.harbourline.example/spring",
    )
    second_creative, second_task = fixtures.creative_in_manual_review(
        advertiser_id,
        [SEV_ELEVEN],
        [(eleven["id"], 0.50)],
        ["US"],
        headline="Harbourline summer offer",
        body_text="Harbourline summer offer with flexible monthly terms.",
        landing_page_url="https://www.harbourline.example/summer",
        display_url="https://www.harbourline.example/summer",
    )
    fixtures.claim_task(first_task["id"], reviewer_id)
    fixtures.claim_task(second_task["id"], reviewer_id)

    fixtures.decide_task(
        first_task["id"],
        reviewer_id,
        "DISAPPROVE",
        reason_codes=["MANUAL_REVIEW"],
        note="Claims in the spring offer are not substantiated.",
    )

    # 10.00 * 1.00 * 1.00, so the balance sits exactly on the warning threshold.
    first_notice = fixtures.only_notice_for_creative(first_creative["id"])
    assert first_notice["assessed_points"] == pytest.approx(10.00, abs=0.01)
    after_first = fixtures.read_advertiser(advertiser_id)
    assert after_first["violation_points_raw"] == pytest.approx(10.00, abs=0.01)
    assert after_first["violation_points_decayed"] == pytest.approx(10.00, abs=0.01)
    # No action is closed yet, and a base index of 10.00 draws no surcharge.
    assert after_first["severity_index"] == pytest.approx(10.00, abs=0.01)
    assert after_first["account_status"] == "WARNED"

    warning = fixtures.in_force_action(advertiser_id)
    assert warning is not None, "an index of exactly 10.00 must mint a warning"
    assert warning["action_type"] == "WARNING"
    assert warning["origin"] == "SYSTEM_CASCADE"
    assert warning["status"] == "ACTIVE"
    assert warning["prior_action_id"] is None
    assert warning["source_notice_id"] == first_notice["id"]
    assert warning["severity_index_at_issue"] == pytest.approx(10.00, abs=0.01)
    assert_instant_equals(
        warning["effective_from"], "2026-08-01T00:00:00Z", "effective_from"
    )
    assert_instant_equals(
        warning["effective_until"], "2026-08-31T00:00:00Z", "effective_until"
    )

    fixtures.decide_task(
        second_task["id"],
        reviewer_id,
        "DISAPPROVE",
        reason_codes=["MANUAL_REVIEW"],
        note="Claims in the summer offer are not substantiated either.",
    )

    second_notice = fixtures.only_notice_for_creative(second_creative["id"])
    assert second_notice["assessed_points"] == pytest.approx(11.50, abs=0.01)
    after_second = fixtures.read_advertiser(advertiser_id)
    # The warning was still in force, so it adds nothing to the base index of 21.50,
    # which draws a 3.50 surcharge and lands the index exactly on 25.00.
    assert after_second["violation_points_decayed"] == pytest.approx(21.50, abs=0.01)
    assert after_second["severity_index"] == pytest.approx(25.00, abs=0.01)
    assert after_second["account_status"] == "RESTRICTED"

    restriction = fixtures.in_force_action(advertiser_id)
    assert restriction is not None
    assert restriction["action_type"] == "RESTRICTION"
    assert restriction["origin"] == "SYSTEM_CASCADE"
    assert restriction["prior_action_id"] == warning["id"]
    assert restriction["source_notice_id"] == second_notice["id"]
    assert restriction["severity_index_at_issue"] == pytest.approx(25.00, abs=0.01)
    assert_instant_equals(
        restriction["effective_from"], "2026-08-01T00:00:00Z", "effective_from"
    )
    assert_instant_equals(
        restriction["effective_until"], "2026-09-30T00:00:00Z", "effective_until"
    )
    assert fixtures.read_action(warning["id"])["status"] == "SUPERSEDED"

    actions = fixtures.actions_for_advertiser(advertiser_id)
    assert len(actions) == 2
    entries = fixtures.ledger_for_advertiser(advertiser_id)
    assert [entry["delta_points"] for entry in entries] == [
        pytest.approx(10.00, abs=0.01),
        pytest.approx(11.50, abs=0.01),
    ]
