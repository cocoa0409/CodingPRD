"""Model version lifecycle, safety gate, deprecation, and pinned-support tests."""
from test_helpers import (
    ADMIN,
    BILLING,
    ApiErrorId,
    create_model_version_payload,
    create_safety_evaluation_payload,
    make_trust_analyst_headers,
    make_trust_lead_headers,
    set_clock,
    validate_error,
    validate_success,
)


class TestModelRevisionCycle:
    def test_failed_verdict_returns_model_to_draft(self, api):
        """PRD §3.2: "A failing verdict moves the evaluation `OPEN → FAILED` and returns the model `GATED → DRAFT`, likewise incrementing the model's `version`; the draft may then be revised and re-evaluated by opening a fresh evaluation."

        Design: Difficulty/non_linear_state_machine/model_version_draft_gated_revision_cycle
        """
        set_clock()
        mv = validate_success(
            api.create_model_version(
                create_model_version_payload(model_slug="claude-opus", version_tag="5-0"),
                ADMIN,
            ),
            expected_status=201,
        )
        eval1 = validate_success(
            api.create_safety_evaluation(
                mv["id"],
                create_safety_evaluation_payload(capability_class="STANDARD"),
                make_trust_analyst_headers("analyst-1"),
            ),
            expected_status=201,
        )
        verdict = validate_success(
            api.submit_safety_verdict(
                eval1["id"], {"score": 0.60}, make_trust_lead_headers("lead-1")
            )
        )
        assert verdict["status"] == "FAILED"
        mv_data = validate_success(api.get_model_version(mv["id"], ADMIN))
        assert mv_data["status"] == "DRAFT", (
            f"failing verdict must return the model to DRAFT, got {mv_data['status']}"
        )

    def test_second_evaluation_can_pass_after_failure(self, api):
        """PRD §3.2: "the draft may then be revised and re-evaluated by opening a fresh evaluation."
        PRD §3.2: "A passing verdict moves the evaluation `OPEN → PASSED` and the model `GATED → ACTIVE`, releasing it to broad availability and incrementing the model's `version`."

        Design: Difficulty/non_linear_state_machine/model_version_draft_gated_revision_cycle
        """
        set_clock()
        mv = validate_success(
            api.create_model_version(
                create_model_version_payload(model_slug="claude-opus", version_tag="5-0"),
                ADMIN,
            ),
            expected_status=201,
        )
        eval1 = validate_success(
            api.create_safety_evaluation(
                mv["id"],
                create_safety_evaluation_payload(capability_class="STANDARD"),
                make_trust_analyst_headers("analyst-1"),
            ),
            expected_status=201,
        )
        validate_success(
            api.submit_safety_verdict(
                eval1["id"], {"score": 0.60}, make_trust_lead_headers("lead-1")
            )
        )
        eval2 = validate_success(
            api.create_safety_evaluation(
                mv["id"],
                create_safety_evaluation_payload(capability_class="STANDARD"),
                make_trust_analyst_headers("analyst-1"),
            ),
            expected_status=201,
        )
        verdict2 = validate_success(
            api.submit_safety_verdict(
                eval2["id"], {"score": 0.85}, make_trust_lead_headers("lead-1")
            )
        )
        assert verdict2["status"] == "PASSED"
        mv_data = validate_success(api.get_model_version(mv["id"], ADMIN))
        assert mv_data["status"] == "ACTIVE", (
            f"passing second verdict must release the model to ACTIVE, got {mv_data['status']}"
        )


class TestFrontierGateBoundary:
    def _setup_frontier_cycle(self, api):
        set_clock()
        mv = validate_success(
            api.create_model_version(
                create_model_version_payload(model_slug="claude-opus", version_tag="5-1"),
                ADMIN,
            ),
            expected_status=201,
        )
        eval1 = validate_success(
            api.create_safety_evaluation(
                mv["id"],
                create_safety_evaluation_payload(capability_class="FRONTIER"),
                make_trust_analyst_headers("analyst-1"),
            ),
            expected_status=201,
        )
        validate_success(
            api.submit_safety_verdict(
                eval1["id"], {"score": 0.89}, make_trust_lead_headers("lead-1")
            )
        )
        eval2 = validate_success(
            api.create_safety_evaluation(
                mv["id"],
                create_safety_evaluation_payload(capability_class="FRONTIER"),
                make_trust_analyst_headers("analyst-1"),
            ),
            expected_status=201,
        )
        return mv, eval1, eval2

    def test_frontier_score_below_threshold_fails(self, api):
        """PRD §3.2: "`STANDARD` and `ELEVATED` require a score of at least 0.70, while `FRONTIER` requires a score of at least 0.90."
        PRD §3.2: "A failing verdict moves the evaluation `OPEN → FAILED` and returns the model `GATED → DRAFT`, likewise incrementing the model's `version`; the draft may then be revised and re-evaluated by opening a fresh evaluation."

        Design: Difficulty/cross_entity_state_dependency/model_activation_requires_safety_pass
        """
        set_clock()
        mv = validate_success(
            api.create_model_version(
                create_model_version_payload(model_slug="claude-opus", version_tag="5-1"),
                ADMIN,
            ),
            expected_status=201,
        )
        eval1 = validate_success(
            api.create_safety_evaluation(
                mv["id"],
                create_safety_evaluation_payload(capability_class="FRONTIER"),
                make_trust_analyst_headers("analyst-1"),
            ),
            expected_status=201,
        )
        verdict = validate_success(
            api.submit_safety_verdict(
                eval1["id"], {"score": 0.89}, make_trust_lead_headers("lead-1")
            )
        )
        assert verdict["status"] == "FAILED"
        mv_data = validate_success(api.get_model_version(mv["id"], ADMIN))
        assert mv_data["status"] == "DRAFT"

    def test_frontier_score_exactly_at_threshold_passes(self, api):
        """PRD §3.2: "The boundary is inclusive — a score exactly equal to the threshold passes — and the score is compared as supplied, without rounding."
        PRD §3.2: "A passing verdict moves the evaluation `OPEN → PASSED` and the model `GATED → ACTIVE`, releasing it to broad availability and incrementing the model's `version`."

        Design: Difficulty/cross_entity_state_dependency/model_activation_requires_safety_pass
        """
        mv, eval1, eval2 = self._setup_frontier_cycle(api)
        verdict2 = validate_success(
            api.submit_safety_verdict(
                eval2["id"], {"score": 0.90}, make_trust_lead_headers("lead-1")
            )
        )
        assert verdict2["status"] == "PASSED"
        mv_data = validate_success(api.get_model_version(mv["id"], ADMIN))
        assert mv_data["status"] == "ACTIVE", (
            f"inclusive 0.90 FRONTIER threshold must release the model, got {mv_data['status']}"
        )


class TestModelVersionBasics:
    def test_new_model_version_starts_draft(self, api):
        """PRD §3.2: "A freshly registered version is `DRAFT`, with `deprecation_announced_at`, `sunset_at`, and `safety_evaluation_id` all unset."

        Design: Corner/state_machines/model_version_initial_state_is_draft
        """
        set_clock()
        resp = api.create_model_version(create_model_version_payload(), ADMIN)
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "DRAFT"
        assert data["deprecation_announced_at"] is None
        assert data["sunset_at"] is None
        assert data["safety_evaluation_id"] is None

    def test_cached_rate_must_be_strictly_less_than_input(self, api):
        """PRD §3.2: "The pricing table carries three keys — `input_per_mtok_cents`, `output_per_mtok_cents`, and `cached_per_mtok_cents` — each a non-negative integer number of cents per million tokens, and the cached rate must be strictly less than the input rate."

        Design: Corner/entities/model_version_pricing_cached_must_be_less_than_input
        """
        set_clock()
        resp = api.create_model_version(
            create_model_version_payload(
                model_slug="claude-bad",
                version_tag="0-1",
                pricing={
                    "input_per_mtok_cents": 100,
                    "output_per_mtok_cents": 500,
                    "cached_per_mtok_cents": 100,
                },
            ),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestRBACModelLifecycle:
    def test_billing_contact_cannot_open_safety_evaluation(self, api):
        """PRD §2.1: "A `BillingContact` performs financial operations — invoicing and payment recording — and cannot modify the model lifecycle or enforcement state."
        PRD §2.1: "A well-authenticated request whose role is not authorized for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/billing_contact_cannot_open_safety_evaluation
        """
        set_clock()
        mv = validate_success(
            api.create_model_version(create_model_version_payload(), ADMIN),
            expected_status=201,
        )
        resp = api.create_safety_evaluation(
            mv["id"], create_safety_evaluation_payload(capability_class="STANDARD"), BILLING
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_trust_lead_cannot_create_model_version(self, api):
        """PRD §2.1: "A `PlatformAdmin` operates the platform's administrative surface: onboarding and activating organizations, registering and deprecating model versions, opening and countersigning enterprise agreements, settling payments, and driving the logical clock."
        PRD §2.1: "A well-authenticated request whose role is not authorized for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/trust_lead_cannot_create_model_version
        """
        set_clock()
        resp = api.create_model_version(
            create_model_version_payload(model_slug="claude-bad", version_tag="0-0"),
            make_trust_lead_headers("lead-9"),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
