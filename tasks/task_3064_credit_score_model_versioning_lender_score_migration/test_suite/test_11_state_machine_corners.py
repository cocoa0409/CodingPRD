"""Declared edges, undeclared edges, terminal lockdowns and initial states."""
from test_helpers import (
    api_client, validate_success, get_success_data,
    COMPLIANCE, DEVELOPER, ANALYST, FAIR_LENDING,
    create_and_activate_license,
    create_archive_sample,
    schedule_study,
    setup_released_dual_auto,
    setup_retired_model,
    setup_discovery_slot_consumed,
    licence_headers,
    create_score_result_payload,
    create_model,
    author_variant,
    setup_reference_set_bound_to_active_code,
)


class TestLicenceStateEdges:

    def test_a_second_activation_of_an_active_licence_is_an_undeclared_edge(self, api):
        """PRD §2.12: "the target must occupy the state named by the transition's
        originating clause and the transition must be declared on that entity"

        Design: Corner/state_machines/license_activate_from_active_returns_invalid_state_machine_edge
        """
        _, model, variant = setup_released_dual_auto()
        license_ = create_and_activate_license(variant["id"])
        current = get_success_data(api_client.get_license(license_["id"], COMPLIANCE), 200)
        assert current["status"] == "ACTIVE"
        res = api_client.activate_license(license_["id"], current["version"], COMPLIANCE)
        assert res.status_code == 409
        assert res.json()["data"]["error_id"] == "ERR_INVALID_STATE_MACHINE_EDGE"

    def test_the_refused_re_activation_leaves_the_licence_unchanged(self, api):
        """PRD §3.7: "Activation moves a pending licence to `ACTIVE` and recomputes
        `cumulative_score_count` and `cumulative_fee_cents` from the licence's fee
        ledger."

        Design: Corner/state_machines/license_activate_from_active_returns_invalid_state_machine_edge
        """
        _, model, variant = setup_released_dual_auto()
        license_ = create_and_activate_license(variant["id"])
        current = get_success_data(api_client.get_license(license_["id"], COMPLIANCE), 200)
        api_client.activate_license(license_["id"], current["version"], COMPLIANCE)
        after = get_success_data(api_client.get_license(license_["id"], COMPLIANCE), 200)
        assert after["status"] == "ACTIVE"
        assert after["version"] == current["version"]

    def test_a_retired_version_can_neither_be_reopened_nor_licensed(self, api):
        """PRD §3.7: "Activation, and equally reactivation, is refused when the
        licensed variant's model version has reached `SUPERSEDED` — reported as
        `ERR_MODEL_SUPERSEDED` — or `RETIRED`, reported as `ERR_MODEL_RETIRED`."

        Design: Corner/state_machines/score_model_retire_is_terminal_for_licensing
        """
        bureau, retired, variant = setup_retired_model()
        current = get_success_data(api_client.get_score_model(retired["id"], COMPLIANCE), 200)
        assert current["status"] == "RETIRED"
        assert current["retired_at"] is not None
        res = api_client.create_license(
            {"lender_name": "Late Bank", "lender_code": "LEND-LATE",
             "score_variant_id": variant["id"], "volume_tier": "VOLUME_TIER_1",
             "entitled_count": 100, "window_start_month": "2026-01",
             "window_end_month": "2027-01"}, COMPLIANCE)
        assert res.status_code == 409
        assert res.json()["data"]["error_id"] == "ERR_MODEL_RETIRED"

    def test_no_transition_leaves_the_retired_state(self, api):
        """PRD §3.2: "`RETIRED` is the only terminal state of the model lifecycle,
        and `retired_at` is stamped when it is reached."

        Design: Corner/state_machines/score_model_retire_is_terminal_for_licensing
        """
        bureau, retired, variant = setup_retired_model()
        current = get_success_data(api_client.get_score_model(retired["id"], COMPLIANCE), 200)
        res = api_client.reopen_model(retired["id"], current["version"], COMPLIANCE)
        assert res.status_code == 409
        assert res.json()["data"]["error_id"] == "ERR_INVALID_STATE_MACHINE_EDGE"

    def test_the_refused_licence_create_left_no_row(self, api):
        """PRD §3.7: "A `ComplianceOfficer` creates a licence in `PENDING` by naming
        the `lender_name`, a short `lender_code` that will be stamped onto every
        score settled under it"

        Design: Corner/state_machines/score_model_retire_is_terminal_for_licensing
        """
        bureau, retired, variant = setup_retired_model()
        api_client.create_license(
            {"lender_name": "Late Bank", "lender_code": "LEND-LATE",
             "score_variant_id": variant["id"], "volume_tier": "VOLUME_TIER_1",
             "entitled_count": 100, "window_start_month": "2026-01",
             "window_end_month": "2027-01"}, COMPLIANCE)
        res = api_client.list_licenses(COMPLIANCE, params={"lender_code": "LEND-LATE"})
        data = validate_success(res, 200)
        assert data == []


class TestVariantStateEdges:

    def test_recalling_a_draft_variant_is_refused(self, api):
        """PRD §3.1: "A variant runs a three-state life of `DRAFT`, `RELEASED` and
        `RECALLED`, and it has no terminal state — a recalled variant can always be
        brought back."

        Design: Corner/state_machines/score_variant_recall_from_draft_returns_invalid_state_machine_edge
        """
        model = create_model(version_label="CREDIT-DUAL-V1")
        variant = author_variant(model["id"])
        assert variant["status"] == "DRAFT"
        res = api_client.recall_variant(variant["id"], DEVELOPER)
        assert res.status_code == 409
        assert res.json()["data"]["error_id"] == "ERR_INVALID_STATE_MACHINE_EDGE"

    def test_the_same_recall_succeeds_once_the_variant_is_released(self, api):
        """PRD §3.1: "The reverse move, recalling a released variant, moves it
        `RELEASED` → `RECALLED`, recomputes the parent counter"

        Design: Corner/state_machines/score_variant_recall_from_draft_returns_invalid_state_machine_edge
        """
        model = create_model(version_label="CREDIT-DUAL-V1")
        variant = author_variant(model["id"])
        released = validate_success(api_client.release_variant(variant["id"], DEVELOPER), 200)
        assert released["status"] == "RELEASED"
        recalled = validate_success(api_client.recall_variant(variant["id"], DEVELOPER), 200)
        assert recalled["status"] == "RECALLED"


class TestStudyInitialAndTerminalStates:

    def test_a_new_study_starts_scheduled_with_a_seeded_replay_log(self, api):
        """PRD §3.3: "The study begins in `SCHEDULED`, its `touched_model_ids`
        replay log is seeded with the model's own id as the first entry, and its
        `required_reason_codes` are derived from the study path per §2.10."

        Design: Corner/state_machines/validation_study_create_starts_scheduled_with_seeded_replay_log
        """
        bureau, model, variant = setup_released_dual_auto()
        sample = create_archive_sample(model["id"], sample_ref="XFER-INIT",
                                       record_count=4000, segment_name="PRIME",
                                       sample_kind="VALIDATION",
                                       observation_window_months=24,
                                       window_start_month="2024-01",
                                       window_end_month="2026-01")
        study = schedule_study(model["id"], sample["id"], study_path="CROSS_BUREAU",
                               performed_by="va-init")
        assert study["status"] == "SCHEDULED"
        assert study["touched_model_ids"] == [model["id"]]

    def test_the_cross_bureau_diagnostic_starts_unset(self, api):
        """PRD §3.3: "a cross-bureau run computes the bureau-weighted and unweighted
        composites of §3.4 and stores their absolute difference as
        `reconciliation_variance`, leaving the impact ratio null."

        Design: Corner/state_machines/validation_study_create_starts_scheduled_with_seeded_replay_log
        """
        bureau, model, variant = setup_released_dual_auto()
        sample = create_archive_sample(model["id"], sample_ref="XFER-INIT",
                                       record_count=4000, segment_name="PRIME",
                                       sample_kind="VALIDATION",
                                       observation_window_months=24,
                                       window_start_month="2024-01",
                                       window_end_month="2026-01")
        study = schedule_study(model["id"], sample["id"], study_path="CROSS_BUREAU",
                               performed_by="va-init")
        assert study["reconciliation_variance"] is None

    def test_the_study_path_drives_the_required_reason_code_set(self, api):
        """PRD §2.10: "The set of codes required depends on the study path: a
        protected-class study requires `CREDIT-DUAL-DECISION-V1-SEGMENT_ZERO-STUDY-PRIMARY`
        and `CREDIT-DUAL-DECISION-V1-UNDECIDED-ESCALATED-SECONDARY`, while a
        cross-bureau study requires `CREDIT-DUAL-DECISION-V1-BUREAU_DISAGREEMENT-TERTIARY`
        and `CREDIT-DUAL-DECISION-V1-RECONCILIATION_SPREAD-STUDY-PRIMARY`."

        Design: Corner/state_machines/validation_study_create_starts_scheduled_with_seeded_replay_log
        """
        bureau, model, variant = setup_released_dual_auto()
        sample = create_archive_sample(model["id"], sample_ref="XFER-INIT",
                                       record_count=4000, segment_name="PRIME",
                                       sample_kind="VALIDATION",
                                       observation_window_months=24,
                                       window_start_month="2024-01",
                                       window_end_month="2026-01")
        study = schedule_study(model["id"], sample["id"], study_path="CROSS_BUREAU",
                               performed_by="va-init")
        assert len(study["required_reason_codes"]) == 2
        assert ("CREDIT-DUAL-DECISION-V1-RECONCILIATION_SPREAD-STUDY-PRIMARY"
                in study["required_reason_codes"])

class TestDiscoverySlotTerminality:

    def test_the_consuming_posting_is_recorded_on_the_slot(self, api):
        """PRD §3.8: "A supplied `discovery_tag` consumes a discovery slot: the
        registered request carrying that tag moves from `REGISTERED` to `CONSUMED`
        and its `consumed_score_result_id` is bound to this posting"

        Design: Corner/state_machines/score_discovery_request_consume_is_terminal
        """
        fixture = setup_discovery_slot_consumed()
        slot = get_success_data(
            api_client.get_discovery_request(fixture["slot"]["id"],
                                             licence_headers(fixture["license"]["id"])), 200)
        assert slot["status"] == "CONSUMED"
        assert slot["consumed_score_result_id"] == fixture["result"]["id"]

    def test_a_second_posting_carrying_the_same_tag_is_refused(self, api):
        """PRD §3.8: "and a second posting carrying the same tag is refused with
        `ERR_DISCOVERY_TAG_UNKNOWN` because the slot is terminal."
        PRD §2.11: "A discovery slot is registered in `REGISTERED` status with its
        `requested_at` stamped from the logical clock at the moment of registration,
        and it becomes consumable by exactly one later posting."

        Design: Corner/state_machines/score_discovery_request_consume_is_terminal
        """
        fixture = setup_discovery_slot_consumed()
        current = get_success_data(
            api_client.get_license(fixture["license"]["id"], COMPLIANCE), 200)
        res = api_client.create_score_result(
            create_score_result_payload(
                consumer_id=fixture["consumer"]["id"],
                score_variant_id=fixture["variant"]["id"],
                bureau_id=fixture["bureau"]["id"], license_id=fixture["license"]["id"],
                raw_posted_score=716, expected_license_version=current["version"],
                discovery_tag="DISC-1"),
            licence_headers(fixture["license"]["id"]))
        assert res.status_code == 404
        assert res.json()["data"]["error_id"] == "ERR_DISCOVERY_TAG_UNKNOWN"

    def test_the_refused_second_posting_settled_nothing(self, api):
        """PRD §3.8: "Settlement closes the posting. A `MARGINAL_PRICING` entry is
        appended to the fee ledger"

        Design: Corner/state_machines/score_discovery_request_consume_is_terminal
        """
        fixture = setup_discovery_slot_consumed()
        current = get_success_data(
            api_client.get_license(fixture["license"]["id"], COMPLIANCE), 200)
        api_client.create_score_result(
            create_score_result_payload(
                consumer_id=fixture["consumer"]["id"],
                score_variant_id=fixture["variant"]["id"],
                bureau_id=fixture["bureau"]["id"], license_id=fixture["license"]["id"],
                raw_posted_score=716, expected_license_version=current["version"],
                discovery_tag="DISC-1"),
            licence_headers(fixture["license"]["id"]))
        res = api_client.list_score_results(
            DEVELOPER, params={"consumer_id": fixture["consumer"]["id"]})
        _, meta = validate_success(res, 200), res.json()["meta"]
        assert meta["total_count"] == 1


class TestReferenceSetReconcilePrecondition:

    def test_reconciling_against_a_still_active_code_is_refused(self, api):
        """PRD §3.6: "Reconciling is the terminal move and requires the bound code to
        have been archived first — reconciling against a code that is still `ACTIVE`
        is refused with `ERR_REASON_CODE_ACTIVE`."

        Design: Corner/state_machines/reference_set_reconcile_requires_an_archived_reason_code
        """
        bureau, model, variant, rc, consumer, rs = setup_reference_set_bound_to_active_code()
        current = get_success_data(api_client.get_reference_set(rs["id"], FAIR_LENDING), 200)
        assert current["status"] == "BOUND"
        res = api_client.reconcile_reference_set(rs["id"], current["version"], FAIR_LENDING)
        assert res.status_code == 409
        assert res.json()["data"]["error_id"] == "ERR_REASON_CODE_ACTIVE"

    def test_the_declared_detach_path_returns_the_set_to_compiled(self, api):
        """PRD §3.6: "Detaching is the reversal that returns the set to `COMPILED`.
        Whichever route is taken, the `reason_code_id` is cleared to null"

        Design: Corner/state_machines/reference_set_reconcile_requires_an_archived_reason_code
        """
        bureau, model, variant, rc, consumer, rs = setup_reference_set_bound_to_active_code()
        current = get_success_data(api_client.get_reference_set(rs["id"], FAIR_LENDING), 200)
        detached = validate_success(
            api_client.detach_reason_code(rs["id"], current["version"], FAIR_LENDING), 200)
        assert detached["status"] == "COMPILED"
        assert detached["reason_code_id"] is None