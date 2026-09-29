"""Arithmetic that is only correct when it is done in exactly the declared order.

Rounding once on a sum is not the same as summing rounded rows, and the two appear side
by side on the same screening run. A per-rule threshold decides membership of the scoring
input set while the excluded row is still stored. A retention span is 2555 days rather
than seven calendar years. A cap applies to a total and not to the lines that feed it.
A clause ladder stops at its first match. Each case pins one of those.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_instant_equals,
    fixtures,
    make_advertiser_headers,
    validate_error,
)

SUP_HEALTH = "SUP_HEALTH"
FIN_CREDIT = "FIN_CREDIT"
POL_ISSUE = "POL_ISSUE"
ALC_SPIRITS = "ALC_SPIRITS"
GAM_CASINO = "GAM_CASINO"
ADULT_CONTENT = "ADULT_CONTENT"


def _wellspring_advertiser():
    return fixtures.create_verified_advertiser(
        legal_name="Wellspring Commerce Inc",
        country_code="US",
        industry_code="RETAIL",
    )["id"]


def _decisions_keyed_by_rule(run_id):
    """The run's decision rows indexed by the rule each one matched."""
    return {row["policy_rule_id"]: row for row in fixtures.decisions_for_run(run_id)}


def _bundle_creative_screened(advertiser_id, decisions):
    """One US creative declaring both retail codes, screened with the given rows."""
    creative, run = fixtures.screened_creative(
        advertiser_id,
        [SUP_HEALTH, FIN_CREDIT],
        decisions,
        ["US"],
        headline="Wellness and credit bundle",
        body_text=(
            "Buy our wellness supplement bundle now and finance it over twelve months."
        ),
        landing_page_url="https://www.wellspring.example/bundle",
        display_url="https://www.wellspring.example/bundle",
    )
    return creative, run


def test_the_audit_rows_round_individually_while_the_score_rounds_once_on_the_sum():
    """PRD §3.4: "Alongside the disposition each decision records
    `country_multiplier_applied`, which is the country multiplier of its rule for this
    creative as defined in §3.1, and `assessed_points`, which is the rule's
    `base_severity_weight` multiplied by that `country_multiplier_applied` and then
    multiplied by the decision's own `confidence`, with the product rounded half-up to 2
    decimals."

    PRD §3.4: "For each finding, take the matched rule's `base_severity_weight`, multiply
    it by the country multiplier of that rule for this creative, and multiply the result by
    the finding's own `confidence`; keep each of those products unrounded, add them all
    together, round the single total half-up to 2 decimals, and cap the outcome at 100.00."

    PRD §3.4: "The rounding happens once, on the sum — not per finding."

    Design: Corner/From Table 3 (Calculations)/precision_risk_score_sums_unrounded_products_while_each_decision_row_rounds_alone
    """
    sup = fixtures.create_policy_rule(
        SUP_HEALTH,
        "REGULATED",
        3.00,
        title="Health supplements",
        confidence_auto_disapprove_threshold=0.90,
        confidence_manual_threshold=0.20,
        default_queue="STANDARD",
    )
    fixtures.add_country_override(sup["id"], "US", "ALLOWED", severity_multiplier=1.15)
    fin = fixtures.create_policy_rule(
        FIN_CREDIT,
        "REGULATED",
        9.00,
        title="Consumer credit offers",
        confidence_auto_disapprove_threshold=0.95,
        confidence_manual_threshold=0.20,
        default_queue="STANDARD",
    )
    fixtures.add_country_override(fin["id"], "US", "ALLOWED", severity_multiplier=1.15)
    advertiser_id = _wellspring_advertiser()

    creative, run = _bundle_creative_screened(
        advertiser_id, [(sup["id"], 0.83), (fin["id"], 0.41)]
    )

    by_rule = _decisions_keyed_by_rule(run["id"])
    sup_row = by_rule[sup["id"]]
    fin_row = by_rule[fin["id"]]
    assert sup_row["disposition"] == "ROUTE_MANUAL"
    assert sup_row["country_multiplier_applied"] == pytest.approx(1.15, abs=0.01)
    # 3.00 * 1.15 * 0.83 = 2.8635, rounded on the row.
    assert sup_row["assessed_points"] == pytest.approx(2.86, abs=0.01)
    assert fin_row["disposition"] == "ROUTE_MANUAL"
    assert fin_row["country_multiplier_applied"] == pytest.approx(1.15, abs=0.01)
    # 9.00 * 1.15 * 0.41 = 4.2435, rounded on the row.
    assert fin_row["assessed_points"] == pytest.approx(4.24, abs=0.01)

    # 2.8635 + 4.2435 = 7.107 rounded once; summing the rounded rows gives 7.10.
    assert run["provisional_risk_score"] == pytest.approx(7.11, abs=0.01)
    assert run["outcome"] == "ROUTED_MANUAL"
    assert run["decision_count"] == 2
    assert run["max_confidence"] == pytest.approx(0.83, abs=0.01)

    assert creative["risk_score_provisional"] == pytest.approx(7.11, abs=0.01)
    # No destination evidence and no licence, so the final score matches.
    assert creative["risk_score_final"] == pytest.approx(7.11, abs=0.01)
    assert creative["destination_status"] == "DESTINATION_PENDING"


def test_a_row_below_its_own_rules_threshold_is_stored_yet_scores_nothing():
    """PRD §3.4: "Risk scoring runs off the same evidence but with a narrower input set:
    only the decision rows of the creative's *latest* run count, and among those only the
    rows whose `confidence` is at least the `confidence_manual_threshold` of the rule they
    matched."

    PRD §3.4: "Rows below that threshold are excluded, and every row belonging to an
    earlier run is excluded outright."

    PRD §3.4: "This per-row `assessed_points` is an audit figure only; it is never summed
    to produce a risk score, because summing already-rounded rows is the wrong rounding
    order for that purpose."

    Design: Corner/From Table 3 (Calculations)/input_set_filtering_a_below_threshold_decision_is_stored_but_excluded_from_the_risk_score
    """
    sup = fixtures.create_policy_rule(
        SUP_HEALTH,
        "REGULATED",
        3.00,
        title="Health supplements",
        confidence_auto_disapprove_threshold=0.90,
        confidence_manual_threshold=0.20,
        default_queue="STANDARD",
    )
    fin = fixtures.create_policy_rule(
        FIN_CREDIT,
        "REGULATED",
        9.00,
        title="Consumer credit offers",
        confidence_auto_disapprove_threshold=0.95,
        # The only difference that matters: 0.41 no longer clears this bar.
        confidence_manual_threshold=0.60,
        default_queue="STANDARD",
    )
    advertiser_id = _wellspring_advertiser()

    creative, run = _bundle_creative_screened(
        advertiser_id, [(sup["id"], 0.83), (fin["id"], 0.41)]
    )

    by_rule = _decisions_keyed_by_rule(run["id"])
    fin_row = by_rule[fin["id"]]
    assert fin_row["disposition"] == "BELOW_THRESHOLD"
    # 9.00 * 1.00 * 0.41 is still written as the audit figure for the excluded row.
    assert fin_row["assessed_points"] == pytest.approx(3.69, abs=0.01)
    sup_row = by_rule[sup["id"]]
    assert sup_row["disposition"] == "ROUTE_MANUAL"
    assert sup_row["assessed_points"] == pytest.approx(2.49, abs=0.01)

    # Only the surviving row scores: 3.00 * 1.00 * 0.83.
    assert run["provisional_risk_score"] == pytest.approx(2.49, abs=0.01)
    # Both counters still see the excluded row.
    assert run["decision_count"] == 2
    assert run["max_confidence"] == pytest.approx(0.83, abs=0.01)

    assert creative["risk_score_provisional"] == pytest.approx(2.49, abs=0.01)
    assert creative["screening_run_count"] == 1
    assert creative["review_status"] == "PENDING_MANUAL_REVIEW"


# ---------------------------------------------------------------------------
# Shared setup for the two political-notice cases
# ---------------------------------------------------------------------------
def _political_creative_claimed():
    """A political creative routed to the POLITICAL queue and claimed.

    The single classifier row sits at 0.30, below the rule's 0.55 manual threshold, so
    the run has no qualifying finding at all and it is the political clause alone that
    routes the creative to a human.
    """
    rule = fixtures.create_policy_rule(
        POL_ISSUE,
        "REGULATED",
        5.00,
        title="Political and social issue advertising",
        confidence_auto_disapprove_threshold=0.90,
        confidence_manual_threshold=0.55,
        review_sla_hours=24,
        default_queue="STANDARD",
    )
    advertiser = fixtures.create_verified_advertiser(
        legal_name="Civic Voice Committee",
        country_code="US",
        industry_code="POLITICAL_COMMITTEE",
    )
    advertiser_id = advertiser["id"]
    eligible = fixtures.record_verification(
        advertiser_id, "POLITICAL_ELIGIBILITY", "ELIGIBLE"
    )
    assert eligible["political_eligibility_status"] == "ELIGIBLE"
    reviewer_id = fixtures.create_reviewer(
        ["POLITICAL"], ["US"], display_name="P. Okafor", max_concurrent_claims=2
    )["id"]
    creative, run = fixtures.screened_creative(
        advertiser_id,
        [POL_ISSUE],
        [(rule["id"], 0.30)],
        ["US"],
        headline="Vote yes on measure four",
        body_text=(
            "Measure four funds neighbourhood transit repairs across the county."
        ),
        landing_page_url="https://www.civicvoice.example/measure4",
        display_url="https://www.civicvoice.example/measure4",
        political_flag=True,
        disclaimer_text="Paid for by Civic Voice Committee",
    )
    assert run["outcome"] == "ROUTED_MANUAL"
    assert run["provisional_risk_score"] == pytest.approx(0.00, abs=0.01)
    task = fixtures.only_task_for_creative(creative["id"])
    assert task["queue"] == "POLITICAL"
    assert task["primary_policy_rule_id"] is None
    fixtures.claim_task(task["id"], reviewer_id)
    return {
        "advertiser_id": advertiser_id,
        "reviewer_id": reviewer_id,
        "creative_id": creative["id"],
        "task_id": task["id"],
    }


def test_the_archive_entry_retains_for_2555_days_across_two_leap_days():
    """PRD §3.7: "Its `archived_at` is the logical clock and its `retention_until` is
    `archived_at` plus 2555 whole days, which is exactly seven 365-day years; nothing is
    ever deleted before that instant, and in fact no endpoint deletes or mutates an archive
    entry at all."

    PRD §3.7: "It snapshots the `ad_creative_id` and the `advertiser_id`, copies the
    creative's `disclaimer_text` into `disclosure_text`, copies the advertiser's
    `legal_name` into `payer_name` as the payer of record, copies the creative's `headline`
    into `headline_snapshot`, and records into `target_country_codes_snapshot` the countries
    the creative was cleared for — the full `target_country_codes` under a plain approval
    and the `limited_country_codes` under a limited approval."

    PRD §2.11: "`POLITICAL_ARCHIVE_MISSING` — satisfied when the creative's
    `political_flag` is false, or else when a political archive entry already exists for
    this creative and the owning advertiser's `political_eligibility_status` is
    `ELIGIBLE`."

    Design: Corner/From Table 3 (Calculations)/constants_applied_political_archive_retention_lands_2555_days_after_the_approving_clock
    """
    case = _political_creative_claimed()

    fixtures.decide_task(
        case["task_id"],
        case["reviewer_id"],
        "APPROVE",
        note="Disclosure text present and payer identified",
    )

    entries = fixtures.archive_entries_for_creative(case["creative_id"])
    assert len(entries) == 1
    entry = entries[0]
    assert_instant_equals(
        entry["archived_at"], "2026-08-01T00:00:00Z", "archived_at"
    )
    # 2026-08-01 plus 2555 days lands two days short of seven calendar years,
    # because 2028-02-29 and 2032-02-29 both fall inside the span.
    assert_instant_equals(
        entry["retention_until"], "2033-07-30T00:00:00Z", "retention_until"
    )
    assert entry["ad_creative_id"] == case["creative_id"]
    assert entry["advertiser_id"] == case["advertiser_id"]
    assert entry["disclosure_text"] == "Paid for by Civic Voice Committee"
    assert entry["payer_name"] == "Civic Voice Committee"
    assert entry["headline_snapshot"] == "Vote yes on measure four"
    assert entry["target_country_codes_snapshot"] == ["US"]
    assert entry["searchable"] is True

    approved = fixtures.read_creative(
        case["creative_id"], advertiser_id=case["advertiser_id"]
    )
    assert approved["review_status"] == "AUTO_APPROVED"
    assert approved["serving_eligible"] is False
    # The political conjunct now passes, so only the destination axis blocks it.
    assert approved["blocking_reason_codes"] == ["DESTINATION_NOT_CLEARED"]


def test_a_political_notice_gets_a_168_hour_window_and_one_integrity_line():
    """PRD §3.9: "Its `appeal_window_hours` is 168 hours — seven days — when
    `political_at_issue` is true, and 72 hours — three days — otherwise; its
    `appeal_deadline_at` is the notice's `created_at` plus that many whole hours."

    PRD §3.9: "Its `political_at_issue` snapshots the creative's `political_flag` at the
    moment of issue."

    PRD §3.9: "Phase two writes one integrity line for each non-finding reason code the
    notice carries, taken in the fixed sequence `CERT_MISSING`, then `CLOAKING`, then
    `DESTINATION_MISMATCH`, then `POLITICAL_DISCLOSURE`, and skipping any of those four the
    notice does not carry."

    PRD §3.9: "The raw balance, stored as `violation_points_raw` and disclosed to the
    advertiser through a notice's `disclosed_points_total`, is the sum of every entry's
    `delta_points` at full weight forever, rounded half-up to 2 decimals and floored at
    0.00."

    Design: Corner/From Table 3 (Calculations)/correct_result_appeal_window_stretches_to_168_hours_on_a_political_notice
    """
    case = _political_creative_claimed()

    fixtures.decide_task(
        case["task_id"],
        case["reviewer_id"],
        "DISAPPROVE",
        reason_codes=["MANUAL_REVIEW", "POLITICAL_DISCLOSURE"],
        note="The payer disclosure does not name the sponsoring committee registration",
    )

    notice = fixtures.only_notice_for_creative(case["creative_id"])
    assert notice["political_at_issue"] is True
    assert notice["appeal_window_hours"] == 168
    assert_instant_equals(
        notice["appeal_deadline_at"], "2026-08-08T00:00:00Z", "appeal_deadline_at"
    )
    assert notice["status"] == "ISSUED"
    assert notice["decided_by_reviewer_id"] == case["reviewer_id"]

    lines = notice["assessment_lines"]
    # Phase one is empty because the only decision row was BELOW_THRESHOLD, and
    # MANUAL_REVIEW is a phase-one source reason that writes no line of its own.
    assert len(lines) == 1, f"expected only the disclosure integrity line: {lines}"
    assert lines[0]["policy_rule_code"] is None
    assert lines[0]["reason_code"] == "POLITICAL_DISCLOSURE"
    # 10.00 integrity base * 1.00 strictest multiplier * 1.50.
    assert lines[0]["line_points"] == pytest.approx(15.00, abs=0.01)
    assert notice["assessed_points"] == pytest.approx(15.00, abs=0.01)
    assert notice["policy_rule_codes"] == []
    assert notice["disclosed_points_total"] == pytest.approx(15.00, abs=0.01)

    advertiser = fixtures.read_advertiser(case["advertiser_id"])
    # Base 15.00 is under 20.00, so no surcharge lifts it out of the warning band.
    assert advertiser["severity_index"] == pytest.approx(15.00, abs=0.01)
    assert advertiser["account_status"] == "WARNED"

    disapproved = fixtures.read_creative(
        case["creative_id"], advertiser_id=case["advertiser_id"]
    )
    assert disapproved["review_status"] == "DISAPPROVED"
    # Nothing was ever approved, so the public record stays empty.
    assert fixtures.archive_entries_for_creative(case["creative_id"]) == []


def test_the_decay_weight_steps_to_half_at_ninety_days_and_to_zero_at_one_eighty():
    """PRD §3.9: "The decayed balance, stored as `violation_points_decayed`, weights each
    entry by its own age: compute the entry's age in whole days by taking the difference
    between the logical clock and the entry's `created_at` in seconds, dividing by 86400
    and discarding the fraction; the entry then counts at full weight while its age is
    under 90 days, at half weight once its age is at least 90 days but still under 180
    days, and at zero weight once its age is 180 days or more."

    PRD §3.9: "Step one computes a base index: count the advertiser's enforcement actions
    whose `status` is `SUPERSEDED`, `LIFTED` or `EXPIRED` — actions still in force are
    excluded, so a currently effective action never inflates its own successor's index —
    multiply that closed-action count by 5.00, add the advertiser's
    `violation_points_decayed`, and round the total half-up to 2 decimals."

    PRD §3.9: "When `effective_until` is not supplied it defaults to `effective_from` plus
    the duration for the type: 30 days for a warning, 60 days for a restriction and 180
    days for a suspension."

    Design: Corner/From Table 3 (Calculations)/decay_function_factor_steps_from_one_half_to_zero_at_the_declared_day_boundary
    """
    rule = fixtures.create_policy_rule(
        FIN_CREDIT,
        "REGULATED",
        12.00,
        title="Consumer credit offers",
        confidence_auto_disapprove_threshold=0.90,
        confidence_manual_threshold=0.20,
        default_queue="STANDARD",
    )
    advertiser_id = fixtures.create_verified_advertiser(
        legal_name="Beacon Lending Co",
        country_code="US",
        industry_code="CONSUMER_FINANCE",
    )["id"]
    reviewer_id = fixtures.create_reviewer(
        ["STANDARD"], ["US"], display_name="R. Alvarez", max_concurrent_claims=3
    )["id"]
    creative, task = fixtures.creative_in_manual_review(
        advertiser_id,
        [FIN_CREDIT],
        [(rule["id"], 0.50)],
        ["US"],
        headline="Instant approval",
        body_text=(
            "Instant approval on a personal line of credit for qualified applicants."
        ),
        landing_page_url="https://www.beaconlending.example/instant",
        display_url="https://www.beaconlending.example/instant",
    )
    fixtures.claim_task(task["id"], reviewer_id)
    fixtures.decide_task(
        task["id"],
        reviewer_id,
        "DISAPPROVE",
        reason_codes=["MANUAL_REVIEW"],
        note="Rate disclosure is absent from the creative",
    )

    before = fixtures.read_advertiser(advertiser_id)
    assert before["violation_points_raw"] == pytest.approx(12.00, abs=0.01)
    assert before["violation_points_decayed"] == pytest.approx(12.00, abs=0.01)
    assert before["severity_index"] == pytest.approx(12.00, abs=0.01)
    assert before["account_status"] == "WARNED"
    action = fixtures.actions_for_advertiser(advertiser_id)[0]
    assert action["action_type"] == "WARNING"
    assert_instant_equals(
        action["effective_until"], "2026-08-31T00:00:00Z", "effective_until"
    )

    # 2026-08-01 to 2027-01-27 is 179 whole days: still inside the half-weight band.
    first = fixtures.advance_clock_and_sweep("2027-01-27T00:00:00Z")
    assert first["expired_enforcement_actions"] == 1
    assert first["lifted_enforcement_actions"] == 0
    assert fixtures.read_action(action["id"])["status"] == "EXPIRED"

    half = fixtures.read_advertiser(advertiser_id)
    assert half["violation_points_decayed"] == pytest.approx(6.00, abs=0.01)
    assert half["violation_points_raw"] == pytest.approx(12.00, abs=0.01)
    # 6.00 decayed plus 5.00 for the one closed action; base 11.00 earns no surcharge.
    assert half["severity_index"] == pytest.approx(11.00, abs=0.01)
    assert half["account_status"] == "ACTIVE"

    # One more day reaches the inclusive 180-day boundary.
    second = fixtures.advance_clock_and_sweep("2027-01-28T00:00:00Z")
    assert second["expired_enforcement_actions"] == 0

    zero = fixtures.read_advertiser(advertiser_id)
    assert zero["violation_points_decayed"] == pytest.approx(0.00, abs=0.01)
    assert zero["violation_points_raw"] == pytest.approx(12.00, abs=0.01)
    assert zero["severity_index"] == pytest.approx(5.00, abs=0.01)
    assert zero["ledger_entry_count"] == 1
    # Neither sweep mints an action; only cascades and operators do that.
    assert len(fixtures.actions_for_advertiser(advertiser_id)) == 1


def test_two_sixty_point_lines_report_uncapped_while_their_sum_is_clamped_to_a_hundred():
    """PRD §3.9: "Phase one writes one finding line per qualifying classifier decision of
    the creative's latest screening run — qualifying meaning the decision's `disposition` is
    `AUTO_DISAPPROVE` or `ROUTE_MANUAL`, so `BELOW_THRESHOLD` rows are excluded and earlier
    runs are ignored entirely — taken in ascending order of the matched rule's `code`."

    PRD §3.9: "The notice's `assessment_lines` is phase one's lines followed by phase
    two's, in exactly that order, and its `assessed_points` is the sum of the `line_points`
    of every line, capped at 100.00."

    PRD §3.9: "Step two picks an escalation surcharge keyed on the base index *alone*:
    0.00 when the base index is below 20.00, 3.50 when it is at least 20.00 but below
    35.00, and 9.00 when it is 35.00 or more."

    PRD §3.9: "Step four selects an action type keyed on the post-surcharge
    `severity_index`: `SUSPENSION` when it is at least 40.00, otherwise `RESTRICTION` when
    it is at least 25.00, otherwise `WARNING` when it is at least 10.00, and otherwise none
    at all."

    Design: Corner/From Table 3 (Calculations)/aggregation_assessed_points_are_capped_at_one_hundred_after_the_lines_are_summed
    """
    codes = {}
    for code, title in (
        (ALC_SPIRITS, "Alcohol - spirits"),
        (GAM_CASINO, "Casino gambling"),
    ):
        rule = fixtures.create_policy_rule(
            code,
            "REGULATED",
            20.00,
            title=title,
            confidence_auto_disapprove_threshold=0.90,
            confidence_manual_threshold=0.20,
            default_queue="STANDARD",
        )
        fixtures.add_country_override(
            rule["id"], "US", "ALLOWED", severity_multiplier=3.00
        )
        codes[code] = rule
    advertiser_id = fixtures.create_verified_advertiser(
        legal_name="Riverbend Gaming Inc",
        country_code="US",
        industry_code="GAMING",
    )["id"]
    reviewer_id = fixtures.create_reviewer(
        ["STANDARD"], ["US"], display_name="R. Alvarez", max_concurrent_claims=3
    )["id"]
    creative, task = fixtures.creative_in_manual_review(
        advertiser_id,
        [ALC_SPIRITS, GAM_CASINO],
        [(codes[ALC_SPIRITS]["id"], 0.50), (codes[GAM_CASINO]["id"], 0.50)],
        ["US"],
        headline="Casino and cocktails night",
        body_text=(
            "Join our casino and cocktails night with table games and a spirits tasting."
        ),
        landing_page_url="https://www.riverbend.example/night",
        display_url="https://www.riverbend.example/night",
    )
    # 20.00 * 3.00 * 0.50 twice, summed unrounded and rounded once.
    assert creative["risk_score_provisional"] == pytest.approx(60.00, abs=0.01)

    fixtures.claim_task(task["id"], reviewer_id)
    fixtures.decide_task(
        task["id"],
        reviewer_id,
        "DISAPPROVE",
        reason_codes=["MANUAL_REVIEW"],
        note="Neither age gating nor responsible gaming language is present",
    )

    notice = fixtures.only_notice_for_creative(creative["id"])
    lines = notice["assessment_lines"]
    assert len(lines) == 2, f"one finding line per qualifying decision: {lines}"
    assert [line["policy_rule_code"] for line in lines] == [ALC_SPIRITS, GAM_CASINO]
    for line in lines:
        assert line["reason_code"] == "MANUAL_REVIEW"
        # Each line is reported at its own uncapped 20.00 * 3.00 * 1.00.
        assert line["line_points"] == pytest.approx(60.00, abs=0.01)
    assert notice["assessed_points"] == pytest.approx(100.00, abs=0.01)
    assert notice["policy_rule_codes"] == [ALC_SPIRITS, GAM_CASINO]

    entries = fixtures.ledger_for_notice(notice["id"])
    assert len(entries) == 1
    # The cap lands before the ledger, not after it.
    assert entries[0]["delta_points"] == pytest.approx(100.00, abs=0.01)
    assert entries[0]["reason"] == "DISAPPROVAL_ASSESSED"

    advertiser = fixtures.read_advertiser(advertiser_id)
    assert advertiser["violation_points_raw"] == pytest.approx(100.00, abs=0.01)
    assert advertiser["violation_points_decayed"] == pytest.approx(100.00, abs=0.01)
    # Base 100.00 is at or above 35.00, so the surcharge is 9.00.
    assert advertiser["severity_index"] == pytest.approx(109.00, abs=0.01)
    assert advertiser["account_status"] == "SUSPENDED"

    actions = fixtures.actions_for_advertiser(advertiser_id)
    assert len(actions) == 1
    assert actions[0]["action_type"] == "SUSPENSION"
    assert actions[0]["origin"] == "SYSTEM_CASCADE"
    assert actions[0]["severity_index_at_issue"] == pytest.approx(109.00, abs=0.01)
    assert_instant_equals(
        actions[0]["effective_until"], "2027-01-28T00:00:00Z", "effective_until"
    )


def test_the_destination_ladder_reports_only_its_first_matching_clause():
    """PRD §3.8: "First, the result is `MISMATCH` with `mismatch_detail`
    `DEST_UNREACHABLE` when the check's `http_status` is 400 or greater."

    PRD §3.8: "Fourth, the result is `MISMATCH` with `mismatch_detail`
    `CATEGORY_MISMATCH` when the `fetched_content_category` is not the literal `GENERAL`
    and is also not an element of the creative's `declared_category_codes`."

    PRD §3.8: "The destination axis is therefore genuinely cyclic: a destination that was
    cleared can be caught mismatching later and cleared again afterwards, any number of
    times."

    PRD §3.8: "A creative already sitting in `PENDING_MANUAL_REVIEW` keeps the review task
    it already has and gains no second one, and a creative in `DISAPPROVED` or
    `SUSPENDED_HOLD` has its review axis left alone entirely."

    Design: Corner/From Table 3 (Calculations)/projection_first_matching_destination_clause_wins_over_every_later_clause
    """
    fin = fixtures.create_policy_rule(
        FIN_CREDIT,
        "REGULATED",
        4.00,
        title="Consumer credit offers",
        confidence_auto_disapprove_threshold=0.90,
        confidence_manual_threshold=0.55,
    )
    # Exists only so that the wrong category names a real policy code and therefore
    # survives the category validation on its way to the clause ladder.
    fixtures.create_policy_rule(
        ADULT_CONTENT, "PROHIBITED", 18.00, title="Adult content"
    )
    advertiser_id = fixtures.create_verified_advertiser(
        legal_name="Beacon Lending Co",
        country_code="US",
        industry_code="CONSUMER_FINANCE",
    )["id"]
    creative, run = fixtures.screened_creative(
        advertiser_id,
        [FIN_CREDIT],
        [(fin["id"], 0.30)],
        ["US"],
        headline="Clause ladder",
        body_text="A creative used to walk every destination verdict clause in order.",
        landing_page_url="https://www.beaconlending.example/ladder",
        display_url="https://www.beaconlending.example/ladder",
    )
    assert run["outcome"] == "AUTO_APPROVED"
    creative_id = creative["id"]
    good_url = "https://www.beaconlending.example/ladder"

    # Clause 1 wins although the host and the category are also wrong.
    unreachable = fixtures.record_destination_check(
        creative_id,
        "https://down.other-host.example/ladder",
        check_type="INITIAL",
        user_agent_variant="CRAWLER",
        fetched_content_category=ADULT_CONTENT,
        http_status=503,
    )
    assert unreachable["result"] == "MISMATCH"
    assert unreachable["mismatch_detail"] == "DEST_UNREACHABLE"
    assert (
        fixtures.read_creative(creative_id, advertiser_id=advertiser_id)[
            "destination_status"
        ]
        == "MISMATCH_FLAGGED"
    )

    first_clear = fixtures.record_destination_check(
        creative_id, good_url, check_type="RECHECK", user_agent_variant="CRAWLER"
    )
    assert first_clear["result"] == "CLEARED"
    assert first_clear["mismatch_detail"] is None
    assert (
        fixtures.read_creative(creative_id, advertiser_id=advertiser_id)[
            "destination_status"
        ]
        == "DESTINATION_CLEARED"
    )

    # Clause 3 wins over clause 4 although the category is also wrong.
    wrong_host = fixtures.record_destination_check(
        creative_id,
        "https://promo.other-host.example/ladder",
        check_type="RECHECK",
        user_agent_variant="CRAWLER",
        fetched_content_category=ADULT_CONTENT,
    )
    assert wrong_host["result"] == "MISMATCH"
    assert wrong_host["mismatch_detail"] == "HOST_MISMATCH"

    second_clear = fixtures.record_destination_check(
        creative_id, good_url, check_type="RECHECK", user_agent_variant="CRAWLER"
    )
    assert second_clear["result"] == "CLEARED"

    # Only now, with clauses 1 to 3 all satisfied, is clause 4 reachable.
    wrong_category = fixtures.record_destination_check(
        creative_id,
        good_url,
        check_type="RECHECK",
        user_agent_variant="CRAWLER",
        fetched_content_category=ADULT_CONTENT,
    )
    assert wrong_category["result"] == "MISMATCH"
    assert wrong_category["mismatch_detail"] == "CATEGORY_MISMATCH"

    # Every fetch used the crawler variant, so the cloaking clause never applies.
    results = [check["result"] for check in fixtures.checks_for_creative(creative_id)]
    assert len(results) == 5
    assert "CLOAKING" not in results

    final = fixtures.read_creative(creative_id, advertiser_id=advertiser_id)
    assert final["destination_status"] == "MISMATCH_FLAGGED"
    # The first mismatch pulled it off AUTO_APPROVED; the later ones added no task.
    assert final["review_status"] == "PENDING_MANUAL_REVIEW"
    tasks = fixtures.list_tasks_for_creative(creative_id)
    assert len(tasks) == 1, f"the re-route mints exactly one task: {tasks}"


def test_the_serving_gate_lists_its_failing_conjuncts_in_the_declared_order():
    """PRD §2.11: "Four conjuncts are evaluated in this fixed order, and each one that
    fails appends its code to `blocking_reason_codes` in that same order — the array is
    never sorted"

    PRD §2.11: "`POLITICAL_ARCHIVE_MISSING` — satisfied when the creative's
    `political_flag` is false, or else when a political archive entry already exists for
    this creative and the owning advertiser's `political_eligibility_status` is
    `ELIGIBLE`."

    PRD §3.7: "The sweep moves a creative to `SUSPENDED_HOLD` whenever the owning
    advertiser's posture has become `SUSPENDED` and the creative's `review_status` is
    `SCREENING`, `AUTO_APPROVED`, `PENDING_MANUAL_REVIEW` or `APPROVED_LIMITED`; that move
    expires every `QUEUED` or `CLAIMED` review task on the creative, decrements each holding
    reviewer's `claimed_task_count`, forces `serving_eligible` to false with
    `ACCOUNT_ENFORCEMENT` among the `blocking_reason_codes`, and increments the creative's
    `version` by 1."

    PRD §3.3: "Attempting submission from any `review_status` other than `DRAFT` is refused
    with `ERR_INVALID_CREATIVE_STATE` (HTTP 409); attempting it while the account is
    suspended is refused with `ERR_ADVERTISER_SUSPENDED`."

    Design: Corner/From Table 3 (Calculations)/constraint_propagation_serving_gate_appends_every_failing_conjunct_in_the_declared_order
    """
    fixtures.create_policy_rule(
        POL_ISSUE,
        "REGULATED",
        5.00,
        title="Political and social issue advertising",
    )
    advertiser = fixtures.create_verified_advertiser(
        legal_name="Civic Voice Committee",
        country_code="US",
        industry_code="POLITICAL_COMMITTEE",
    )
    advertiser_id = advertiser["id"]
    # The political axis is deliberately left where onboarding put it.
    assert advertiser["political_eligibility_status"] == "NOT_REQUESTED"

    political = fixtures.create_creative(
        advertiser_id,
        [POL_ISSUE],
        ["US"],
        headline="Vote yes on measure four",
        body_text="Measure four funds neighbourhood transit repairs across the county.",
        landing_page_url="https://www.civicvoice.example/measure4",
        display_url="https://www.civicvoice.example/measure4",
        political_flag=True,
        disclaimer_text="Paid for by Civic Voice Committee",
    )
    plain = fixtures.create_creative(
        advertiser_id,
        [POL_ISSUE],
        ["US"],
        headline="Volunteer with us",
        body_text="Volunteer with our committee at the county fair this weekend.",
        landing_page_url="https://www.civicvoice.example/volunteer",
        display_url="https://www.civicvoice.example/volunteer",
    )

    fixtures.mint_enforcement_action(
        advertiser_id,
        "SUSPENSION",
        advertiser["version"],
        trigger_reason="Account suspended pending an offline compliance review",
    )
    assert fixtures.read_advertiser(advertiser_id)["account_status"] == "SUSPENDED"

    blocked = fixtures.read_creative(political["id"], advertiser_id=advertiser_id)
    assert blocked["serving_eligible"] is False
    assert blocked["blocking_reason_codes"] == [
        "REVIEW_NOT_APPROVED",
        "DESTINATION_NOT_CLEARED",
        "ACCOUNT_ENFORCEMENT",
        "POLITICAL_ARCHIVE_MISSING",
    ]

    sibling = fixtures.read_creative(plain["id"], advertiser_id=advertiser_id)
    assert sibling["serving_eligible"] is False
    # The fourth conjunct passes outright for a non-political creative.
    assert sibling["blocking_reason_codes"] == [
        "REVIEW_NOT_APPROVED",
        "DESTINATION_NOT_CLEARED",
        "ACCOUNT_ENFORCEMENT",
    ]

    # Neither creative was in a status the hold reaches.
    for row in (blocked, sibling):
        assert row["review_status"] == "DRAFT"
        assert row["destination_status"] == "NOT_CHECKED"

    validate_error(
        api_client.submit_ad_creative(
            political["id"], make_advertiser_headers(advertiser_id)
        ),
        ApiErrorId.ERR_ADVERTISER_SUSPENDED,
        409,
    )
