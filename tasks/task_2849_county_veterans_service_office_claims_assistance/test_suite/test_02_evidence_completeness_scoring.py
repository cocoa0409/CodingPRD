"""
Evidence completeness scoring: per-item rounding order and the ready threshold.

Every claim here carries two claimed conditions, so the denominator is the
same seventy required points and only the evidence file differs.
"""

import pytest
from test_helpers import (
    CLOCK_START_INSTANT,
    add_received_evidence,
    assert_pct_2dp,
    conditions,
    create_active_representative,
    create_claim_in_peer_review,
    create_represented_veteran,
    find_by_id,
    mark_ready_action,
    read_claim,
    read_claim_evidence,
    receive_evidence,
    request_evidence,
    set_clock,
    set_clock_date,
    validate_error,
)

TWO_CONDITIONS = ["tinnitus", "lumbar_strain"]


def _two_condition_claim(api, base, reviewer):
    """A two-condition claim parked in PEER_REVIEW with an empty evidence file."""
    return create_claim_in_peer_review(
        api,
        base,
        reviewer=reviewer,
        load_evidence=False,
        claimed_conditions=conditions(*TWO_CONDITIONS),
    )


@pytest.fixture
def mixed_punctuality_evidence(api):
    """
    One two-condition claim with four items: a nexus letter received inside the
    punctuality window and three items received well after it.
    """
    set_clock(api, CLOCK_START_INSTANT)
    preparer = create_active_representative(
        api, accreditation_type="COUNTY_CVSO", accreditation_expires_on="2029-12-31"
    )
    reviewer = create_active_representative(
        api, accreditation_type="VSO_ORG", accreditation_expires_on="2029-12-31"
    )
    base = create_represented_veteran(api, designee=preparer)
    ctx = _two_condition_claim(api, base, reviewer)
    officer = ctx["officer_headers"]
    claim_id = ctx["claim"]["id"]

    nexus = request_evidence(
        api,
        claim_id,
        officer,
        evidence_type="NEXUS_LETTER",
        nexus_opinion_strength="AT_LEAST_AS_LIKELY_AS_NOT",
    )
    dbq = request_evidence(api, claim_id, officer, evidence_type="DBQ")
    private = request_evidence(api, claim_id, officer, evidence_type="PRIVATE_MEDICAL")
    lay = request_evidence(api, claim_id, officer, evidence_type="LAY_STATEMENT")

    set_clock_date(api, "2026-08-20", "09:00:00")
    receive_evidence(api, nexus["id"], officer)
    set_clock_date(api, "2026-09-15", "09:00:00")
    for item in (dbq, private, lay):
        receive_evidence(api, item["id"], officer)

    ctx["items"] = {
        "nexus": nexus["id"],
        "dbq": dbq["id"],
        "private": private["id"],
        "lay": lay["id"],
    }
    return ctx


@pytest.fixture
def threshold_pair(api):
    """
    Two two-condition claims on one veteran: one whose four items all arrive
    inside the punctuality window, one whose lay statement arrives late.
    """
    set_clock(api, CLOCK_START_INSTANT)
    preparer = create_active_representative(
        api, accreditation_type="COUNTY_CVSO", accreditation_expires_on="2029-12-31"
    )
    reviewer = create_active_representative(
        api, accreditation_type="VSO_ORG", accreditation_expires_on="2029-12-31"
    )
    base = create_represented_veteran(api, designee=preparer)
    officer = base["officer_headers"]

    on_time = _two_condition_claim(api, base, reviewer)
    for evidence_type in (
        "SERVICE_TREATMENT_RECORD",
        "DBQ",
        "PRIVATE_MEDICAL",
        "LAY_STATEMENT",
    ):
        add_received_evidence(
            api, on_time["claim"]["id"], officer, evidence_type=evidence_type
        )

    late = _two_condition_claim(api, base, reviewer)
    for evidence_type in ("SERVICE_TREATMENT_RECORD", "DBQ", "PRIVATE_MEDICAL"):
        add_received_evidence(
            api, late["claim"]["id"], officer, evidence_type=evidence_type
        )
    lay = request_evidence(
        api, late["claim"]["id"], officer, evidence_type="LAY_STATEMENT"
    )
    set_clock_date(api, "2026-09-05", "09:00:00")
    receive_evidence(api, lay["id"], officer)

    return {"on_time": on_time, "late": late, "lay_id": lay["id"], "officer": officer}


class TestPerItemRoundingOrder:
    """Each item is rounded before the sum, and the sum before the percentage."""

    def test_each_item_is_rounded_to_two_places_at_the_item_level(
        self, api, mixed_punctuality_evidence
    ):
        """
        "The item's `weight_points` is the product of base weight, opinion multiplier and status-and-timeliness multiplier"
        and that product is "rounded half-up to two decimal places at the item level".

        Design: Difficulty/combinatorial_formula/evidence_completeness_per_item_rounding_order_divergence
        """
        ctx = mixed_punctuality_evidence
        items = read_claim_evidence(api, ctx["claim"]["id"], ctx["officer_headers"])
        ids = ctx["items"]
        assert_pct_2dp(find_by_id(items, ids["nexus"])["weight_points"], 25.88)
        assert_pct_2dp(find_by_id(items, ids["dbq"])["weight_points"], 14.88)
        assert_pct_2dp(find_by_id(items, ids["private"])["weight_points"], 10.63)
        assert_pct_2dp(find_by_id(items, ids["lay"])["weight_points"], 5.10)

    def test_the_claim_score_sums_rounded_items_rather_than_raw_products(
        self, api, mixed_punctuality_evidence
    ):
        """
        "The rounding order is not negotiable: round each item, sum the rounded items, then round the percentage."
        Summing the raw products instead scores this same file at 80.68.

        Design: Difficulty/combinatorial_formula/evidence_completeness_per_item_rounding_order_divergence
        """
        ctx = mixed_punctuality_evidence
        claim = read_claim(api, ctx["claim"]["id"], ctx["officer_headers"])
        assert_pct_2dp(claim["evidence_completeness_pct"], 80.70)
        assert round(claim["evidence_completeness_pct"], 2) != 80.68

    def test_the_denominator_is_the_two_condition_required_points_figure(
        self, api, mixed_punctuality_evidence
    ):
        """
        "The denominator is the required-points figure for this claim: a base of 40 points plus 15 points for each element of `claimed_conditions`."
        Two conditions therefore require seventy points, and 56.49 earned of
        seventy is what produces the score.

        Design: Difficulty/combinatorial_formula/evidence_completeness_per_item_rounding_order_divergence
        """
        ctx = mixed_punctuality_evidence
        claim = read_claim(api, ctx["claim"]["id"], ctx["officer_headers"])
        assert len(claim["claimed_conditions"]) == 2
        items = read_claim_evidence(api, ctx["claim"]["id"], ctx["officer_headers"])
        earned = sum(round(item["weight_points"], 2) for item in items)
        assert round(earned, 2) == pytest.approx(56.49, abs=0.005)
        assert_pct_2dp(claim["evidence_completeness_pct"], 80.70)

    def test_the_punctuality_factor_separates_the_two_arrival_dates(
        self, api, mixed_punctuality_evidence
    ):
        """
        The nexus letter arrived nineteen days after request and the rest
        forty-five days after it, and
        "The comparison is strict, so an item received on exactly the thirtieth day after request is on time at 1.00 and one received on the thirty-first day is late at 0.85."

        Design: Difficulty/combinatorial_formula/evidence_completeness_per_item_rounding_order_divergence
        """
        ctx = mixed_punctuality_evidence
        items = read_claim_evidence(api, ctx["claim"]["id"], ctx["officer_headers"])
        nexus = find_by_id(items, ctx["items"]["nexus"])
        dbq = find_by_id(items, ctx["items"]["dbq"])
        assert nexus["received_on"] == "2026-08-20"
        assert nexus["status"] == "RECEIVED"
        assert dbq["received_on"] == "2026-09-15"
        assert_pct_2dp(dbq["weight_points"], 14.88)


class TestReadyToFileThresholdBoundary:
    """Exactly eighty percent is enough; a single late item is not."""

    def test_a_file_landing_exactly_on_the_threshold_marks_ready(
        self, api, threshold_pair
    ):
        """
        Four punctual items earn fifty-six of seventy points, and
        "the comparison is inclusive, so an exact 80.00 passes and 79.99 does not, and the refusal is `ERR_EVIDENCE_INCOMPLETE` at HTTP 409".

        Design: Difficulty/boundary_precision_check/evidence_completeness_exactly_at_threshold_marks_ready_while_one_late_item_is_rejected
        """
        ctx = threshold_pair["on_time"]
        claim = read_claim(api, ctx["claim"]["id"], ctx["officer_headers"])
        assert_pct_2dp(claim["evidence_completeness_pct"], 80.00)
        response = api.claim_transition(
            ctx["claim"]["id"], mark_ready_action(), ctx["reviewer_headers"]
        )
        assert response.status_code == 200
        assert read_claim(api, ctx["claim"]["id"], ctx["officer_headers"])["status"] == (
            "READY_TO_FILE"
        )

    def test_one_late_lay_statement_drops_the_score_under_the_threshold(
        self, api, threshold_pair
    ):
        """
        The same four types score less when one arrives late, because
        "if `received_on` is more than 30 days after `requested_on` the factor is 0.85, and otherwise it is 1.00".

        Design: Difficulty/boundary_precision_check/evidence_completeness_exactly_at_threshold_marks_ready_while_one_late_item_is_rejected
        """
        ctx = threshold_pair["late"]
        items = read_claim_evidence(api, ctx["claim"]["id"], ctx["officer_headers"])
        assert_pct_2dp(
            find_by_id(items, threshold_pair["lay_id"])["weight_points"], 5.10
        )
        claim = read_claim(api, ctx["claim"]["id"], ctx["officer_headers"])
        assert_pct_2dp(claim["evidence_completeness_pct"], 78.71)

    def test_marking_ready_under_the_threshold_is_refused(self, api, threshold_pair):
        """
        Marking ready "additionally requires `evidence_completeness_pct` to be at least the ready-to-file threshold of 80.00 percent".

        Design: Difficulty/boundary_precision_check/evidence_completeness_exactly_at_threshold_marks_ready_while_one_late_item_is_rejected
        """
        ctx = threshold_pair["late"]
        response = api.claim_transition(
            ctx["claim"]["id"], mark_ready_action(), ctx["reviewer_headers"]
        )
        validate_error(response, "ERR_EVIDENCE_INCOMPLETE", 409)

    def test_the_refused_claim_is_left_in_peer_review(self, api, threshold_pair):
        """
        A refusal changes nothing, and the claim keeps waiting on its reviewer:
        marking ready "is available only from `PEER_REVIEW`, only to the reviewer, and only while their accreditation is `ACTIVE`".

        Design: Difficulty/boundary_precision_check/evidence_completeness_exactly_at_threshold_marks_ready_while_one_late_item_is_rejected
        """
        ctx = threshold_pair["late"]
        api.claim_transition(
            ctx["claim"]["id"], mark_ready_action(), ctx["reviewer_headers"]
        )
        claim = read_claim(api, ctx["claim"]["id"], ctx["officer_headers"])
        assert claim["status"] == "PEER_REVIEW"
