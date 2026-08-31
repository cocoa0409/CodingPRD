"""Hazard trees beyond the right-of-way: scoring, segregation of duties, consent."""
import pytest

from test_helpers import (
    ARBORIST_A_ID, ARBORIST_B_ID, ApiErrorId, TEST_USERS, assert_hazard_tree,
    create_hazard_tree_payload, make_arborist_headers, new_hazard_tree,
    read_tree, setup_assessed_tree, setup_circuit,
    setup_notification_in_state, setup_released_span, validate_error, validate_success,
)

ARBORIST_A = TEST_USERS["arborist_headers"]
ARBORIST_B = TEST_USERS["arborist_b_headers"]
FORESTER = TEST_USERS["forester_headers"]


class TestStrikePotentialBoundary:

    def test_a_tree_exactly_as_far_away_as_it_is_tall_still_counts_as_a_strike(self, api):
        """PRD §3.6: "A tree has `strike_potential` when its `offset_ft` is less than or equal
        to its `height_ft` — a tree exactly as far from the line as it is tall counts as a
        strike, because it can reach the conductor lying down."
        PRD §3.6: "The proximity contribution is worth up to 30 points and falls off linearly
        with distance: divide `offset_ft` by `height_ft`, subtract that ratio from 1, multiply
        by 30, take zero if the result would be negative, and round that figure half-up to two
        decimal places **before** it enters the sum."

        Design: Difficulty/boundary_precision_check/hazard_strike_potential_at_offset_equals_height
        """
        world = setup_circuit()

        resp = api.create_hazard_tree(create_hazard_tree_payload(
            world["circuit"]["id"], species="SILVER_MAPLE", defect_class="DEAD",
            height_ft=40, offset_ft=40), make_arborist_headers(ARBORIST_A_ID))
        tree = validate_success(resp, 201)

        assert_hazard_tree(tree)
        assert tree["strike_potential"] is True
        assert tree["risk_score"] == pytest.approx(68.00, abs=0.001), \
            "40 defect + 20 species + 0.00 proximity + 8 target"
        assert tree["removal_required"] is True
        assert tree["identified_by_user_id"] == ARBORIST_A_ID

    def test_one_foot_beyond_its_own_height_scores_nothing(self, api):
        """PRD §3.6: "When there is no strike potential the `risk_score` is fixed at 0.00,
        `removal_required` is false, and no further arithmetic is performed."
        PRD §3.6: "The four are added, the total is rounded half-up to two decimal places, and
        the result is capped at 100.00."

        Design: Difficulty/boundary_precision_check/hazard_strike_potential_at_offset_equals_height
        """
        world = setup_circuit()
        circuit_id = world["circuit"]["id"]

        out_of_reach = new_hazard_tree(circuit_id, species="SILVER_MAPLE",
                                       defect_class="DEAD", height_ft=40, offset_ft=41)
        mid_corridor = new_hazard_tree(circuit_id, species="SILVER_MAPLE",
                                       defect_class="DEAD", height_ft=60, offset_ft=30)

        assert out_of_reach["strike_potential"] is False
        assert out_of_reach["risk_score"] == pytest.approx(0.00, abs=0.001)
        assert out_of_reach["removal_required"] is False
        assert mid_corridor["risk_score"] == pytest.approx(83.00, abs=0.001), \
            "40 defect + 20 species + 15.00 proximity + 8 target"

    def test_a_client_supplied_risk_score_is_discarded(self, api):
        """PRD §2.4: "Fields marked as computed or system-owned throughout this document are
        never accepted from the client. If a create or transition body contains such a field,
        the value is silently discarded; the server computes its own value and returns that."
        PRD §2.4: "This applies to every derived counter — `planned_unit_count` on a plan,
        `actual_units_completed`, `refusal_blocked_unit_count`, `entry_cents`, `risk_score`,
        and the whole billing settlement chain among them."

        Design: Corner/entities/corner_hazard_tree_risk_score_input_ignored
        """
        world = setup_circuit()

        resp = api.create_hazard_tree({
            "circuit_id": world["circuit"]["id"], "species": "SILVER_MAPLE",
            "defect_class": "DEAD", "height_ft": 60, "offset_ft": 30,
            "risk_score": 99.99}, make_arborist_headers(ARBORIST_A_ID))
        tree = validate_success(resp, 201)

        assert tree["risk_score"] == pytest.approx(83.00, abs=0.001)
        assert tree["strike_potential"] is True
        assert tree["status"] == "IDENTIFIED"


class TestSegregationOfDutiesAndRevision:

    def test_the_identifying_arborist_may_not_assess_its_own_tree(self, api):
        """PRD §3.6: "A second arborist must confirm the finding, and it may not be the first
        one: assessment requires the acting `X-User-ID` to differ from the record's
        `identified_by_user_id`, and an attempt by the same person is rejected with
        `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/errors/corner_same_arborist_assess_returns_segregation_of_duties
        """
        world = setup_circuit()
        tree = new_hazard_tree(world["circuit"]["id"], identified_by=ARBORIST_A_ID,
                               species="SILVER_MAPLE", defect_class="DEAD",
                               height_ft=60, offset_ft=30)

        resp = api.assess_hazard_tree(tree["id"], make_arborist_headers(ARBORIST_A_ID), {})

        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
        assert resp.status_code == 403
        stale = read_tree(tree["id"])
        assert stale["status"] == "IDENTIFIED"
        assert stale["assessed_by_user_id"] is None

        assessed = validate_success(
            api.assess_hazard_tree(tree["id"], make_arborist_headers(ARBORIST_B_ID), {}), 200)
        assert assessed["status"] == "ASSESSED"

    def test_a_deferred_tree_is_reassessed_and_rescored(self, api):
        """PRD §3.6: "An `outcome` of `DEFER` moves it `ASSESSED → DEFERRED` and likewise
        increments `version` by 1; a deferred tree is not finished, and a second arborist
        assessment takes it `DEFERRED → ASSESSED` again — still subject to the same rule that
        the assessor differs from the identifier — recomputing `strike_potential`,
        `risk_score` and `removal_required` on the way."
        PRD §3.6: "`removal_required` is true exactly when the `risk_score` is 60.00 or
        higher."

        Design: Corner/state_machines/corner_hazard_tree_defer_then_reassess_revision_loop
        """
        world = setup_circuit()
        tree = setup_assessed_tree(world["circuit"]["id"], species="CONIFER",
                                   defect_class="DEAD", height_ft=60, offset_ft=30)
        assert tree["risk_score"] == pytest.approx(68.00, abs=0.001)
        validate_success(api.decide_hazard_tree(tree["id"], {"outcome": "DEFER"}, FORESTER), 200)

        resp = api.assess_hazard_tree(
            tree["id"], make_arborist_headers(ARBORIST_B_ID), {"offset_ft": 46})
        revised = validate_success(resp, 200)

        assert revised["status"] == "ASSESSED"
        assert revised["offset_ft"] == pytest.approx(46, abs=0.001)
        assert revised["risk_score"] == pytest.approx(60.00, abs=0.001), \
            "40 defect + 5 species + 7.00 proximity + 8 target"
        assert revised["removal_required"] is True


class TestRemovalApprovalChecks:
    """Strike potential, then the 60.00 score, then off-right-of-way consent."""

    def test_a_tree_that_cannot_reach_the_line_fails_the_first_check(self, api):
        """PRD §3.6: "First, the tree must have `strike_potential` true; a tree that cannot
        reach the line is rejected with `ERR_NO_STRIKE_POTENTIAL` (HTTP 422)."
        PRD §3.6: "Because the checks are ordered, a scoreless tree off the right-of-way
        reports the strike-potential failure, not the consent failure."

        Design: Corner/errors/corner_no_strike_potential_blocks_removal_approval
        """
        world = setup_circuit()
        tree = setup_assessed_tree(world["circuit"]["id"], species="SILVER_MAPLE",
                                   defect_class="DEAD", height_ft=40, offset_ft=41)

        resp = api.decide_hazard_tree(tree["id"], {"outcome": "APPROVE_REMOVAL"}, FORESTER)

        error = validate_error(resp, ApiErrorId.ERR_NO_STRIKE_POTENTIAL.value)
        assert resp.status_code == 422
        assert error["error_id"] != ApiErrorId.ERR_HAZARD_RISK_BELOW_THRESHOLD.value
        after = read_tree(tree["id"])
        assert after["risk_score"] == pytest.approx(0.00, abs=0.001)
        assert after["status"] == "ASSESSED"

    def test_a_reaching_tree_scoring_below_sixty_fails_the_second_check(self, api):
        """PRD §3.6: "Second, its `risk_score` must be at least 60.00; below that it is
        rejected with `ERR_HAZARD_RISK_BELOW_THRESHOLD` (HTTP 422)."
        PRD §3.6: "The species weight is 20 for `SILVER_MAPLE`, 18 for `COTTONWOOD`, 15 for
        `ASH`, 8 for `OAK` and 5 for `CONIFER`."

        Design: Corner/validations/corner_hazard_decision_below_risk_threshold_is_rejected
        """
        world = setup_circuit()
        tree = setup_assessed_tree(world["circuit"]["id"], species="CONIFER",
                                   defect_class="DEAD", height_ft=60, offset_ft=47)

        resp = api.decide_hazard_tree(tree["id"], {"outcome": "APPROVE_REMOVAL"}, FORESTER)

        error = validate_error(resp, ApiErrorId.ERR_HAZARD_RISK_BELOW_THRESHOLD.value)
        assert resp.status_code == 422
        assert error["error_id"] != ApiErrorId.ERR_NO_STRIKE_POTENTIAL.value
        after = read_tree(tree["id"])
        assert after["risk_score"] == pytest.approx(59.50, abs=0.001), \
            "40 defect + 5 species + 6.50 proximity + 8 target"
        assert after["strike_potential"] is True
        assert after["removal_required"] is False
        assert after["status"] == "ASSESSED"


class TestOffRightOfWayConsent:

    @staticmethod
    def _two_off_row_trees_with_opposite_consent():
        world = setup_released_span()
        span_id, circuit_id = world["span"]["id"], world["circuit"]["id"]
        refused = setup_notification_in_state(span_id, "REFUSED", premise_code="PRM-REFUSE",
                                              unit_count_at_premise=5)
        acknowledged = setup_notification_in_state(
            span_id, "ACKNOWLEDGED", premise_code="PRM-OK",
            contact_method="PHONE", unit_count_at_premise=5)
        world["tree_without_consent"] = setup_assessed_tree(
            circuit_id, species="SILVER_MAPLE", defect_class="DEAD", height_ft=60,
            offset_ft=30, work_order_id=span_id,
            assess_payload={"customer_notification_id": refused["id"]})
        world["tree_with_consent"] = setup_assessed_tree(
            circuit_id, species="SILVER_MAPLE", defect_class="DEAD", height_ft=60,
            offset_ft=30, work_order_id=span_id,
            assess_payload={"customer_notification_id": acknowledged["id"]})
        return world

    def test_removal_is_blocked_when_the_linked_premise_has_not_acknowledged(self, api):
        """PRD §3.6: "Third, consent: a tree whose `offset_ft` is exactly 0 sits on the
        right-of-way and needs no permission, but a tree whose `offset_ft` is greater than 0
        stands on someone's property, and it may only be approved when its
        `customer_notification_id` names a notification currently in `ACKNOWLEDGED`. A missing
        link, or a link to a record in any other state, is rejected with
        `ERR_OFF_ROW_CONSENT_REQUIRED` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/hazard_removal_blocked_by_unacknowledged_off_row_notification
        """
        world = self._two_off_row_trees_with_opposite_consent()
        tree_id = world["tree_without_consent"]["id"]

        resp = api.decide_hazard_tree(tree_id, {"outcome": "APPROVE_REMOVAL"}, FORESTER)

        validate_error(resp, ApiErrorId.ERR_OFF_ROW_CONSENT_REQUIRED.value)
        assert resp.status_code == 409
        after = read_tree(tree_id)
        assert after["status"] == "ASSESSED"
        assert after["risk_score"] == pytest.approx(83.00, abs=0.001)
        assert after["strike_potential"] is True

    def test_an_identical_tree_on_an_acknowledged_premise_is_approved(self, api):
        """PRD §3.5: "A `response` of `ACKNOWLEDGED` moves the record `NOTIFIED → ACKNOWLEDGED`,
        which is terminal and which also unblocks any hazard-tree removal decision linked to
        that record."
        PRD §3.6: "An `outcome` of `APPROVE_REMOVAL` moves the record
        `ASSESSED → APPROVED_REMOVAL` and increments its `version` by 1, but only after three
        checks that are evaluated in this order."

        Design: Difficulty/cross_entity_state_dependency/hazard_removal_blocked_by_unacknowledged_off_row_notification
        """
        world = self._two_off_row_trees_with_opposite_consent()
        tree_id = world["tree_with_consent"]["id"]

        approved = validate_success(
            api.decide_hazard_tree(tree_id, {"outcome": "APPROVE_REMOVAL"}, FORESTER), 200)

        assert approved["status"] == "APPROVED_REMOVAL"
        assert approved["assessed_by_user_id"] == ARBORIST_B_ID
        assert read_tree(world["tree_without_consent"]["id"])["status"] == "ASSESSED"
