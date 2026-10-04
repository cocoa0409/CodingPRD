"""The cyclic revision loops: a deprecation can be reversed, an archive restored."""
from test_helpers import (
    api_client, validate_success, get_success_data,
    COMPLIANCE, DEVELOPER, REASON_ADMIN, ADMIN,
    setup_deprecated_version_with_blocked_study,
    setup_reason_code_archive_cycle,
)


class TestModelVersionRevisionLoop:

    def test_reopening_a_deprecated_version_returns_it_to_released(self, api):
        """PRD §3.2: "A deprecation can be reversed by the same officer, subject to
        the same documentation requirement that governs release — a filed or
        supplemented `MODEL_RISK_REPORT` carrying the version label, or
        `ERR_MODEL_DOC_REQUIRED`."

        Design: Difficulty/non_linear_state_machine/non_linear_state_machine_version_deprecation_revision_loop
        """
        fixture = setup_deprecated_version_with_blocked_study()
        model = get_success_data(
            api_client.get_score_model(fixture["model"]["id"], COMPLIANCE), 200)
        assert model["status"] == "DEPRECATED"
        reopened = validate_success(
            api_client.reopen_model(model["id"], model["version"], COMPLIANCE), 200)
        assert reopened["status"] == "RELEASED"

    def test_reopening_refreshes_released_at_as_a_fresh_release_event(self, api):
        """PRD §3.2: "Reopening stamps `released_at` afresh from the logical clock,
        because the reopening is itself a release event"

        Design: Difficulty/non_linear_state_machine/non_linear_state_machine_version_deprecation_revision_loop
        """
        fixture = setup_deprecated_version_with_blocked_study()
        deprecated = get_success_data(
            api_client.get_score_model(fixture["model"]["id"], COMPLIANCE), 200)
        # The logical clock is frozen at its default instant, so the only way
        # "afresh" is observable is to advance business time between the release
        # and the reopening; the clock is driven by a BureauAdministrator.
        api_client.set_current_utc("2026-10-01T00:00:00Z", ADMIN)
        reopened = validate_success(
            api_client.reopen_model(deprecated["id"], deprecated["version"], COMPLIANCE), 200)
        assert reopened["released_at"] is not None
        assert reopened["released_at"] != deprecated["released_at"], (
            "the reopening must be a fresh release event"
        )

    def test_reopening_returns_blocked_studies_to_scheduled(self, api):
        """PRD §3.1: "if that counter reaches zero every study on the model that is
        still `SCHEDULED` moves to `BLOCKED`."
        PRD §3.2: "Reopening stamps `released_at` afresh from the logical clock,
        because the reopening is itself a release event, and returns every blocked
        study on the model to `SCHEDULED`."

        Design: Difficulty/non_linear_state_machine/non_linear_state_machine_version_deprecation_revision_loop
        """
        fixture = setup_deprecated_version_with_blocked_study()
        assert fixture["study_after"]["status"] == "BLOCKED"
        deprecated = get_success_data(
            api_client.get_score_model(fixture["model"]["id"], COMPLIANCE), 200)
        validate_success(
            api_client.reopen_model(deprecated["id"], deprecated["version"], COMPLIANCE), 200)
        study = get_success_data(
            api_client.get_validation_study(fixture["study"]["id"], COMPLIANCE), 200)
        assert study["status"] == "SCHEDULED"

    def test_recalling_the_last_active_variant_blocks_scheduled_studies(self, api):
        """PRD §3.1: "The reverse move, recalling a released variant, moves it
        `RELEASED` → `RECALLED`, recomputes the parent counter, and if that counter
        reaches zero every study on the model that is still `SCHEDULED` moves to
        `BLOCKED`."

        Design: Difficulty/non_linear_state_machine/non_linear_state_machine_version_deprecation_revision_loop
        """
        fixture = setup_deprecated_version_with_blocked_study()
        assert fixture["study_after"]["status"] == "BLOCKED"
        model = get_success_data(
            api_client.get_score_model(fixture["model"]["id"], DEVELOPER), 200)
        assert model["active_variant_count"] == 0


class TestReasonCodeArchiveCycle:

    def test_a_childless_code_archives_and_its_parent_can_then_archive(self, api):
        """PRD §3.5: "The code may only be archived when no child of it is still
        `ACTIVE` — otherwise `ERR_REASON_CODE_ARCHIVED` — and when its `bind_count`
        is below 2, since a code that has already been bound twice is spent and is
        refused with `ERR_REASON_CODE_REUSE_LIMIT`."

        Design: Difficulty/non_linear_state_machine/non_linear_state_machine_reason_code_archive_cycle
        """
        _, _, _, root, child = setup_reason_code_archive_cycle()
        archived_child = validate_success(
            api_client.archive_reason_code(child["id"], REASON_ADMIN), 200)
        assert archived_child["status"] == "ARCHIVED"
        archived_root = validate_success(
            api_client.archive_reason_code(root["id"], REASON_ADMIN), 200)
        assert archived_root["status"] == "ARCHIVED"

    def test_an_archived_code_returns_to_active_through_restore(self, api):
        """PRD §3.5: "On success the code returns to `ACTIVE`, `weight_received_pct`
        is re-derived as the sum of the `weight_pct` values of this node's
        descendants that stand in `ARCHIVED` and whose weight is below 0.05"

        Restore is only permitted when `parent_reason_code_id` "is null or points
        at a parent that is `ACTIVE`", so the root is brought back before its
        archived child (PRD §3.5).

        Design: Difficulty/non_linear_state_machine/non_linear_state_machine_reason_code_archive_cycle
        """
        _, _, _, root, child = setup_reason_code_archive_cycle()
        api_client.archive_reason_code(child["id"], REASON_ADMIN)
        api_client.archive_reason_code(root["id"], REASON_ADMIN)
        api_client.restore_reason_code(root["id"], REASON_ADMIN)
        restored = validate_success(
            api_client.restore_reason_code(child["id"], REASON_ADMIN), 200)
        assert restored["status"] == "ACTIVE"

    def test_a_below_floor_child_routes_its_whole_weight_to_the_parent(self, api):
        """PRD §3.5: "A child whose `weight_pct` is below 0.05 routes its entire
        weight to its `parent_reason_code_id`, and that parent's
        `weight_received_pct` becomes the sum of every such child's `weight_pct`."

        Design: Difficulty/non_linear_state_machine/non_linear_state_machine_reason_code_archive_cycle
        """
        _, _, _, root, child = setup_reason_code_archive_cycle()
        api_client.archive_reason_code(child["id"], REASON_ADMIN)
        parent = get_success_data(api_client.get_reason_code(root["id"], REASON_ADMIN), 200)
        assert parent["weight_received_pct"] == 0.03

    def test_restore_re_derives_only_the_restored_nodes_own_share(self, api):
        """PRD §3.5: "On success the code returns to `ACTIVE`, `weight_received_pct`
        is re-derived as the sum of the `weight_pct` values of this node's
        descendants that stand in `ARCHIVED` and whose weight is below 0.05, and the
        compensating ledger entry fires"

        Note: the parent's received share is not re-derived by the child's restore,
        because the restore re-derives only the restored node's own descendants.

        Design: Difficulty/non_linear_state_machine/non_linear_state_machine_reason_code_archive_cycle
        """
        _, _, _, root, child = setup_reason_code_archive_cycle()
        api_client.archive_reason_code(child["id"], REASON_ADMIN)
        parent_before = get_success_data(
            api_client.get_reason_code(root["id"], REASON_ADMIN), 200)
        api_client.archive_reason_code(root["id"], REASON_ADMIN)
        api_client.restore_reason_code(child["id"], REASON_ADMIN)
        parent_after = get_success_data(
            api_client.get_reason_code(root["id"], REASON_ADMIN), 200)
        assert parent_after["weight_received_pct"] == parent_before["weight_received_pct"]