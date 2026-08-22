"""Closeout deliverables, the readiness read and the acceptance certificate."""

from test_helpers import (
    ApiErrorId,
    assert_closeout_deliverable,
    assert_readiness,
    create_issue,
    create_project,
    deliver_deliverable,
    get_deliverable,
    get_project,
    get_readiness,
    get_test,
    plan_deliverable,
    setup_dual_variant_completion_project,
    setup_prefunctional_verified_equipment,
    setup_project_in_acceptance_phase,
    validate_error,
    validate_success,
    void_issue,
)
from test_helpers import (
    CONTRACTOR,
    DESIGN,
    OWNER,
    make_cx_authority_headers,
    make_design_team_headers,
)


class TestCloseoutDeliverables:
    def test_required_attendee_count_defaults_to_zero_and_pins_coverage_to_one(self, api):
        """PRD §3.7: "An optional `equipment_id` ties it to a specific unit, and an optional
        `required_attendee_count` — which may not be negative and defaults to 0 — states how
        many of the owner's staff must attend; non-training deliverables leave it at 0."
        PRD §3.7: "That ratio is exactly 1.0 when `required_attendee_count` is 0; otherwise
        it is the attendee count divided by the required attendee count, capped at 1.0,
        rounded half up to four decimal places."

        Design: Corner/entities/closeout_deliverable_defaults_required_attendee_count_to_zero
        """
        project = create_project(
            name="Coverage Cx",
            building_name="Coverage Block",
            contract_value_cents=50_000_000,
        )
        planned = validate_success(
            api.create_closeout_deliverable(
                {
                    "project_id": project["id"],
                    "deliverable_kind": "SYSTEMS_MANUAL_SECTION",
                    "title": "Chapter 3 - controls",
                },
                DESIGN,
            ),
            201,
        )
        assert_closeout_deliverable(planned)
        assert planned["required_attendee_count"] == 0

        delivered = validate_success(
            api.deliver_closeout_deliverable(
                planned["id"], {"attendee_count": 0, "duration_minutes": 0}, DESIGN
            ),
            200,
        )
        assert delivered["coverage_ratio"] == 1.0
        assert delivered["status"] == "DELIVERED"
        assert get_deliverable(planned["id"])["status"] == "DELIVERED"

    def test_training_coverage_of_exactly_eighty_percent_is_accepted(self, api):
        """PRD §3.7: "For a `TRAINING_SESSION` there is one further gate: `coverage_ratio`
        must be at least 0.80, with the boundary inclusive so that exactly 0.80 is accepted,
        and a shortfall is refused with `ERR_TRAINING_COVERAGE_INSUFFICIENT`."
        PRD §3.7: "That gate does not apply to `SYSTEMS_MANUAL_SECTION` or `OM_DATA_PACKAGE`
        deliverables."

        Design: Corner/calculations/training_coverage_at_exactly_eighty_percent_is_acceptable
        """
        project = create_project(
            name="Training Cx",
            building_name="Training Block",
            contract_value_cents=50_000_000,
        )
        at_boundary = plan_deliverable(
            project["id"],
            "TRAINING_SESSION",
            title="Chiller plant training",
            required_attendee_count=10,
        )
        delivered_at_boundary = deliver_deliverable(
            at_boundary["id"], attendee_count=8, duration_minutes=90
        )
        assert delivered_at_boundary["coverage_ratio"] == 0.8

        below_boundary = plan_deliverable(
            project["id"],
            "TRAINING_SESSION",
            title="Boiler plant training",
            required_attendee_count=10,
        )
        delivered_below = deliver_deliverable(
            below_boundary["id"], attendee_count=7, duration_minutes=90
        )
        assert delivered_below["coverage_ratio"] == 0.7

        accepted = validate_success(
            api.accept_closeout_deliverable(
                at_boundary["id"], {"attestation_note": "Attendance sheet signed"}, OWNER
            ),
            200,
        )
        assert accepted["status"] == "ACCEPTED"

        refused = api.accept_closeout_deliverable(
            below_boundary["id"], {"attestation_note": "Attendance sheet signed"}, OWNER
        )
        validate_error(
            refused, ApiErrorId.ERR_TRAINING_COVERAGE_INSUFFICIENT.value, 422
        )

        after = get_deliverable(below_boundary["id"])
        assert after["status"] == "DELIVERED"
        assert after["accepted_by_user_id"] is None

    def test_acceptor_may_not_be_the_deliverer(self, api):
        """PRD §2.11: "The `X-User-ID` recorded as a checklist's `executed_by_user_id` may
        not be the `X-User-ID` that verifies that checklist, and the `X-User-ID` recorded as
        a deliverable's `delivered_by_user_id` may not be the `X-User-ID` that accepts it."
        PRD §3.7: "Acceptance moves the row `DELIVERED` → `ACCEPTED`, records
        `accepted_by_user_id`, recomputes the provisional acceptance completion score and
        increments the engagement's `version` by one."

        Design: Corner/rbac/deliverable_acceptor_may_not_be_its_deliverer
        """
        project = create_project(
            name="SoD2 Cx",
            building_name="SoD2 Block",
            contract_value_cents=50_000_000,
        )
        planned = validate_success(
            api.create_closeout_deliverable(
                {
                    "project_id": project["id"],
                    "deliverable_kind": "SYSTEMS_MANUAL_SECTION",
                    "title": "Chapter 1 - HVAC",
                },
                make_design_team_headers("u-shared-2"),
            ),
            201,
        )
        delivered = validate_success(
            api.deliver_closeout_deliverable(
                planned["id"],
                {"attendee_count": 0, "duration_minutes": 0},
                make_design_team_headers("u-shared-2"),
            ),
            200,
        )
        assert delivered["delivered_by_user_id"] == "u-shared-2"

        self_accept = api.accept_closeout_deliverable(
            planned["id"],
            {"attestation_note": "Self accepted"},
            make_cx_authority_headers("u-shared-2"),
        )
        validate_error(self_accept, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

        accepted = validate_success(
            api.accept_closeout_deliverable(
                planned["id"], {"attestation_note": "Independently reviewed"}, OWNER
            ),
            200,
        )
        assert accepted["status"] == "ACCEPTED"
        assert accepted["accepted_by_user_id"] == "u-owner-1"


class TestReadinessRead:
    def test_readiness_mirrors_the_persisted_engagement_figures(self, api):
        """PRD §3.9: "A dedicated computed read exposes the whole picture for one engagement
        without mutating anything. It answers with `readiness_posture`,
        `issue_severity_index`, `acceptance_completion_score_provisional` and
        `acceptance_completion_score_final` side by side, `open_blocking_issue_count`,
        `retainage_withheld_cents`, `retainage_cap_cents` (the engagement's
        `contract_value_cents` multiplied by 0.10 with any fractional cent discarded),
        `verified_prefunctional_units`, `total_weight_units`, `withdrawn_credit_count` and
        `total_awarded_points`."
        PRD §3.9: "The **pre-functional** sub-score is 1.0 when the unit's pre-functional
        checklist is `VERIFIED` and 0.0 otherwise, and it is identical in both variants."

        Design: Corner/endpoints/readiness_computed_read_mirrors_persisted_project_fields
        """
        project = create_project(name="Readiness Cx", building_name="Readiness Block")
        unit = setup_prefunctional_verified_equipment(
            project["id"], started_up=False, tag="AHU-RD"
        )
        create_issue(
            project["id"],
            "S3",
            description="Balancing report outstanding",
            equipment_id=unit["equipment"]["id"],
        )

        readiness = validate_success(
            api.get_readiness(project["id"], CONTRACTOR), 200
        )
        assert_readiness(readiness)
        stored = get_project(project["id"])

        assert readiness["readiness_posture"] == "OPEN"
        assert readiness["readiness_posture"] == stored["readiness_posture"]
        assert readiness["issue_severity_index"] == 8.00
        assert readiness["issue_severity_index"] == stored["issue_severity_index"]
        assert readiness["retainage_withheld_cents"] == 5_000
        assert readiness["retainage_cap_cents"] == 10_000_000
        assert readiness["verified_prefunctional_units"] == 10
        assert readiness["total_weight_units"] == 10
        assert readiness["acceptance_completion_score_provisional"] == 30.00
        assert readiness["acceptance_completion_score_final"] == 30.00
        assert readiness["open_blocking_issue_count"] == 0
        assert readiness["withdrawn_credit_count"] == 0
        assert readiness["total_awarded_points"] == 0

    def test_an_engagement_without_equipment_scores_zero(self, api):
        """PRD §3.9: "The denominator, `total_weight_units`, is the sum of `weight_units`
        over exactly those units; when that sum is 0 — because no equipment is registered,
        or every unit has been removed — the score is 0.00 and the walk stops there."

        Design: Corner/calculations/acceptance_score_is_zero_when_project_has_no_equipment
        """
        project = create_project(
            name="Empty Cx",
            building_name="Empty Block",
            contract_value_cents=50_000_000,
        )

        readiness = validate_success(api.get_readiness(project["id"], OWNER), 200)
        assert_readiness(readiness)
        assert readiness["acceptance_completion_score_provisional"] == 0.00
        assert readiness["acceptance_completion_score_final"] == 0.00
        assert readiness["total_weight_units"] == 0
        assert readiness["readiness_posture"] == "OPEN"
        assert readiness["issue_severity_index"] == 0.00
        assert readiness["retainage_cap_cents"] == 5_000_000


class TestDualVariantCompletionScore:
    def test_provisional_and_final_variants_diverge_on_one_unchanged_engagement(self, api):
        """PRD §3.9: "In the **`PROVISIONAL`** variant, the functional sub-score is 1.0 when
        the latest completed test is `PASSED` or `PASSED_WITH_EXCEPTIONS`; otherwise it is
        0.5 when the unit has at least one deferred test in `PLANNED` or `BLOCKED`;
        otherwise it is 0.0."
        PRD §3.9: "In the **`FINAL`** variant, the functional sub-score is 1.0 only when the
        latest completed test is `PASSED` **and** every deferred test of that unit is
        `EXECUTED_PASS`; otherwise it is 0.5 only when the latest completed test is
        `PASSED_WITH_EXCEPTIONS` **and** the unit's `blocking_issue_count` is 0; otherwise
        it is 0.0. Unexecuted seasonal work scores 0.0 here rather than 0.5."
        PRD §2.8: "`final_acceptance_score` — the `FINAL` variant, which starts as null and
        is persisted only when an acceptance certificate is issued."

        Design: Difficulty/dual_variant_calc/acceptance_score_provisional_vs_final_diverge_on_same_project
        """
        setup = setup_dual_variant_completion_project()

        readiness = get_readiness(setup["project"]["id"])
        assert readiness["acceptance_completion_score_provisional"] == 85.00
        assert readiness["acceptance_completion_score_final"] == 60.00
        assert readiness["total_weight_units"] == 15

        project = get_project(setup["project"]["id"])
        assert project["acceptance_completion_score"] == 85.00
        assert project["final_acceptance_score"] is None
        assert project["acceptance_kind"] is None

    def test_the_rows_behind_the_two_variants(self, api):
        """PRD §3.4: "A deviation of exactly the tolerance is therefore a pass, and a
        deviation of exactly twice the tolerance is a pass with exceptions."
        PRD §3.9: "The **closeout** sub-score is 1.0 when the unit has at least one closeout
        deliverable **and** every one of them is `ACCEPTED`, and 0.0 otherwise — a unit with
        no deliverables at all scores 0.0, not 1.0."
        PRD §3.9: "The `PROVISIONAL` variant is the one persisted on the engagement as
        `acceptance_completion_score`, and it is refreshed after every checklist
        verification and rejection, every functional test result, every deliverable
        acceptance and return, every deferred test creation and execution, and every
        equipment removal."

        Design: Difficulty/dual_variant_calc/acceptance_score_provisional_vs_final_diverge_on_same_project
        """
        setup = setup_dual_variant_completion_project()

        test = get_test(setup["test_a"]["id"])
        assert test["status"] == "PASSED_WITH_EXCEPTIONS"
        assert test["outcome_deviation_pct"] == 6.00

        assert setup["equipment_a"]["verification_status"] == "CONDITIONALLY_ACCEPTED"
        assert setup["equipment_a"]["blocking_issue_count"] == 0
        assert setup["deliverable_a"]["status"] == "ACCEPTED"
        assert setup["deferred_test_b"]["status"] == "PLANNED"


class TestAcceptanceCertificate:
    def test_substantial_acceptance_below_the_score_floor_is_refused(self, api):
        """PRD §3.9: "The score gate comes first: `SUBSTANTIAL` requires at least 70.00 and
        `FINAL` requires at least 95.00, and a shortfall is refused with
        `ERR_ACCEPTANCE_SCORE_TOO_LOW`."
        PRD §3.9: "The engagement must be in `delivery_phase` `ACCEPTANCE`, or the request
        is refused with `ERR_PHASE_NOT_ALLOWED`, and its posture must not be `FROZEN`."

        Design: Corner/errors/substantial_acceptance_blocked_when_final_score_below_seventy
        """
        setup = setup_project_in_acceptance_phase(with_functional_and_closeout=False)
        assert setup["project"]["delivery_phase"] == "ACCEPTANCE"

        readiness = get_readiness(setup["project"]["id"])
        assert readiness["acceptance_completion_score_final"] == 30.00

        response = api.issue_acceptance(
            setup["project"]["id"], {"acceptance_kind": "SUBSTANTIAL"}, OWNER
        )
        validate_error(response, ApiErrorId.ERR_ACCEPTANCE_SCORE_TOO_LOW.value, 422)

        project = get_project(setup["project"]["id"])
        assert project["final_acceptance_score"] is None
        assert project["acceptance_kind"] is None

    def test_final_acceptance_is_blocked_by_any_live_deficiency(self, api):
        """PRD §3.9: "The deficiency gate comes second and is deliberately asymmetric:
        `SUBSTANTIAL` requires that no issue of the engagement with `severity` `S1` remains
        `OPEN` or `IN_REVIEW`, tolerating lower-severity and deferred deficiencies; `FINAL`
        requires that **no** issue of the engagement remains `OPEN`, `IN_REVIEW` or
        `DEFERRED` at any severity."
        PRD §3.9: "When both gates pass, the computed `FINAL` variant is persisted to
        `final_acceptance_score`, `acceptance_kind` is written, and the engagement's
        `version` increments by one — which in turn unlocks the `ACCEPTANCE` → `WARRANTY`
        hop described in Section 3.1."

        Design: Corner/errors/final_acceptance_blocked_by_open_issue_then_succeeds_after_void
        """
        setup = setup_project_in_acceptance_phase(with_functional_and_closeout=True)
        minor = create_issue(
            setup["project"]["id"], "S4", description="As-built drawing typo"
        )
        assert minor["retainage_hold_cents"] == 0, "an S4 freezes a hold of zero"

        blocked = api.issue_acceptance(
            setup["project"]["id"], {"acceptance_kind": "FINAL"}, OWNER
        )
        validate_error(blocked, ApiErrorId.ERR_OPEN_BLOCKING_ISSUES.value, 422)

        void_issue(minor["id"], "Typo corrected in the record set")

        issued = validate_success(
            api.issue_acceptance(
                setup["project"]["id"], {"acceptance_kind": "FINAL"}, OWNER
            ),
            200,
        )
        assert issued["final_acceptance_score"] == 100.00
        assert issued["acceptance_kind"] == "FINAL"

        project = get_project(setup["project"]["id"])
        assert project["acceptance_completion_score"] == 100.00
        assert project["issue_severity_index"] == 0.00
        assert project["readiness_posture"] == "OPEN"
