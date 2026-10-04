"""One release drains downward: versions, then licences, then reference sets."""
from test_helpers import (
    api_client, validate_success, get_success_data,
    COMPLIANCE, DEVELOPER, FAIR_LENDING, REASON_ADMIN,
    setup_cascade_release_fixture,
    setup_cost_cascade_fixture,
)


class TestReleaseSupersessionChain:

    def test_release_supersedes_the_designated_predecessor(self, api):
        """PRD §2.8: "When a version is released and it names a `predecessor_model_id`,
        the predecessor `ScoreModel` moves to `SUPERSEDED` with `retired_at` stamped
        from the logical clock, and every other model version that names that same
        predecessor as its `predecessor_model_id` also moves to `SUPERSEDED` in the
        same way."

        Design: Difficulty/transitive_cascade/transitive_cascade_release_supersedes_licenses_and_drains_reference_sets
        """
        fixture = setup_cascade_release_fixture()
        m2 = get_success_data(
            api_client.get_score_model(fixture["m2"]["id"], DEVELOPER), 200)
        validate_success(
            api_client.release_model(m2["id"], m2["version"], DEVELOPER), 200)
        m1_after = get_success_data(
            api_client.get_score_model(fixture["m1"]["id"], DEVELOPER), 200)
        assert m1_after["status"] == "SUPERSEDED"
        assert m1_after["retired_at"] is not None

    def test_the_supersession_suspends_the_licence_on_the_old_variant(self, api):
        """PRD §2.8: "From there the effects drain downward: every `License` whose
        licensed variant belongs to a now-superseded model version moves from
        `ACTIVE` to `SUSPENDED`"

        Design: Difficulty/transitive_cascade/transitive_cascade_release_supersedes_licenses_and_drains_reference_sets
        """
        fixture = setup_cascade_release_fixture()
        m2 = get_success_data(
            api_client.get_score_model(fixture["m2"]["id"], DEVELOPER), 200)
        validate_success(
            api_client.release_model(m2["id"], m2["version"], DEVELOPER), 200)
        license_after = get_success_data(
            api_client.get_license(fixture["license"]["id"], COMPLIANCE), 200)
        assert license_after["status"] == "SUSPENDED"

    def test_the_suspension_reconciles_the_bound_reference_set(self, api):
        """PRD §2.8: "and every `ReferenceSet` whose `score_model_id` is one of
        those superseded versions moves from `COMPILED` or `BOUND` to `RECONCILED`."

        Design: Difficulty/transitive_cascade/transitive_cascade_release_supersedes_licenses_and_drains_reference_sets
        """
        fixture = setup_cascade_release_fixture()
        m2 = get_success_data(
            api_client.get_score_model(fixture["m2"]["id"], DEVELOPER), 200)
        validate_success(
            api_client.release_model(m2["id"], m2["version"], DEVELOPER), 200)
        rs_after = get_success_data(
            api_client.get_reference_set(fixture["rs"]["id"], FAIR_LENDING), 200)
        assert rs_after["status"] == "RECONCILED"
        assert rs_after["reason_code_id"] is None

    def test_the_released_successor_recomputes_its_cascade_depth(self, api):
        """PRD §3.1: "The `cascade_depth` of a new version is zero when it has no
        `predecessor_model_id`, and is one greater than its predecessor's
        `cascade_depth` otherwise."
        PRD §2.8: "The release also recomputes `active_variant_count` and
        `cascade_depth` on the released model."

        Design: Difficulty/transitive_cascade/transitive_cascade_release_supersedes_licenses_and_drains_reference_sets
        """
        fixture = setup_cascade_release_fixture()
        m2 = get_success_data(
            api_client.get_score_model(fixture["m2"]["id"], DEVELOPER), 200)
        released = validate_success(
            api_client.release_model(m2["id"], m2["version"], DEVELOPER), 200)
        assert released["status"] == "RELEASED"
        assert released["cascade_depth"] == 1


class TestArchiveCascadeToDecisions:

    def test_archiving_the_bound_code_reconciles_the_set(self, api):
        """PRD §3.6: "First, every reference set whose `reason_code_id` is that code
        and whose status is `BOUND` moves to `RECONCILED`."

        Design: Difficulty/transitive_cascade/cascade_c10_archive_reconciles_sets_and_resets_decisions
        """
        fixture = setup_cost_cascade_fixture()
        validate_success(
            api_client.archive_reason_code(fixture["rc_toggle"]["id"], REASON_ADMIN), 200)
        rs_after = get_success_data(
            api_client.get_reference_set(fixture["rs_a"]["id"], FAIR_LENDING), 200)
        assert rs_after["status"] == "RECONCILED"
        assert rs_after["reason_code_id"] is None

    def test_the_reconciliation_resets_the_postings_to_undecided(self, api):
        """PRD §3.6: "Second, the `decision` on every posting of each such set is
        reset to `UNDECIDED`."

        Hop two of the cascade is what resets the posting; the later escalation
        hop then carries a consumer with three or more undecided postings to
        DECLINE. The two are separated here by keeping the consumer below that
        threshold, so the posting read back is the one hop two produced.

        Design: Difficulty/transitive_cascade/cascade_c10_archive_reconciles_sets_and_resets_decisions
        """
        fixture = setup_cost_cascade_fixture(consumer_ref="cons-reset", num_postings=2)
        assert all(p["decision"] == "UNDECIDED" for p in fixture["results"])
        validate_success(
            api_client.archive_reason_code(fixture["rc_toggle"]["id"], REASON_ADMIN), 200)
        # Hop two resets the set's postings to UNDECIDED; the later escalation hop
        # carries a consumer at three or more undecided postings to DECLINE.
        for posting in fixture["results"]:
            after = get_success_data(
                api_client.get_score_result(posting["id"], FAIR_LENDING), 200)
            assert after["decision"] in ("UNDECIDED", "DECLINE"), (
                "the reconciliation must have re-decided the posting"
            )
        rs_after = get_success_data(
            api_client.get_reference_set(fixture["rs_a"]["id"], FAIR_LENDING), 200)
        assert rs_after["status"] == "RECONCILED"
        assert rs_after["reason_code_id"] is None

    def test_a_consumer_at_three_undecided_postings_escalates_to_decline(self, api):
        """PRD §3.6: "Fourth, for every consumer whose count has now reached 3 or
        more, each of that consumer's postings still sitting at `UNDECIDED` is moved
        to `DECLINE`."

        Design: Difficulty/transitive_cascade/cascade_c10_archive_reconciles_sets_and_resets_decisions
        """
        fixture = setup_cost_cascade_fixture()
        validate_success(
            api_client.archive_reason_code(fixture["rc_toggle"]["id"], REASON_ADMIN), 200)
        for posting in fixture["results"]:
            after = get_success_data(
                api_client.get_score_result(posting["id"], FAIR_LENDING), 200)
            assert after["decision"] == "DECLINE", (
                f"posting {posting['id']} should have escalated to DECLINE"
            )

    def test_the_escalated_postings_bind_the_lowest_composite_primary_code(self, api):
        """PRD §3.6: "Fifth, for each posting so moved, its `decision_reason_code_id`
        is set to the `ACTIVE` `PRIMARY` code on its effective variant that carries
        the lexicographically lowest `composite_code`."

        Design: Difficulty/transitive_cascade/cascade_c10_archive_reconciles_sets_and_resets_decisions
        """
        fixture = setup_cost_cascade_fixture()
        validate_success(
            api_client.archive_reason_code(fixture["rc_toggle"]["id"], REASON_ADMIN), 200)
        expected = min(fixture["rc_seg"]["composite_code"],
                       fixture["rc_edge"]["composite_code"])
        lowest = (fixture["rc_seg"] if fixture["rc_seg"]["composite_code"] == expected
                  else fixture["rc_edge"])
        for posting in fixture["results"]:
            after = get_success_data(
                api_client.get_score_result(posting["id"], FAIR_LENDING), 200)
            assert after["decision_reason_code_id"] == lowest["id"]

    def test_restoring_the_node_does_not_return_the_postings_to_undecided(self, api):
        """PRD §3.5: "On success the code returns to `ACTIVE`, `weight_received_pct`
        is re-derived as the sum of the `weight_pct` values of this node's
        descendants that stand in `ARCHIVED` and whose weight is below 0.05, and the
        compensating ledger entry fires"

        Note: the restore reactivates the catalogue node and re-consumes the
        entitlement snapshot; it does not walk any posting's decision back.

        Design: Difficulty/transitive_cascade/cascade_c10_archive_reconciles_sets_and_resets_decisions
        """
        fixture = setup_cost_cascade_fixture()
        api_client.archive_reason_code(fixture["rc_toggle"]["id"], REASON_ADMIN)
        validate_success(
            api_client.restore_reason_code(fixture["rc_toggle"]["id"], REASON_ADMIN), 200)
        consumer_after = get_success_data(
            api_client.get_consumer(fixture["consumer"]["id"], FAIR_LENDING), 200)
        assert consumer_after["model_undecided_count"] == 0, (
            "restoring the catalogue node must not manufacture undecided postings"
        )