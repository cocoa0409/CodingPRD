"""A row's own state is impeccable; the sibling row's state decides the outcome."""

from test_helpers import (
    ApiErrorId,
    api_client,
    get_success_data,
    validate_error,
)
from test_helpers.fixtures import (
    ADMIN,
    INTAKE,
    advance_cycle,
    create_application,
    file_letter_of_intent,
    refresh_application,
    refresh_intervention,
    request_intervention,
    seed_applicant,
    seed_batching_cycle,
    seed_draft_application,
    seed_second_applicant,
    submit_application,
)
from test_helpers.test_users import make_applicant_headers


def _requested_intervention_against_a_withdrawn_application():
    """An untouched REQUESTED intervention whose target application is WITHDRAWN."""
    world = seed_batching_cycle()
    applicant_a = seed_applicant()
    applicant_b = seed_second_applicant()
    world["applicant"] = applicant_a
    world["applicant_a"] = applicant_a
    world["applicant_b"] = applicant_b
    world["loi"] = file_letter_of_intent(world, applicant_a)
    world["application"] = create_application(world, applicant_a, world["loi"])
    world["cycle"] = advance_cycle(world["cycle"]["id"], "OPEN_FOR_APPLICATIONS")
    world["application"] = submit_application(world["application"], applicant_a)

    world["intervention"] = request_intervention(
        world["application"],
        applicant_b,
        grounds="Lakeview serves the same area and is materially affected",
    )
    world["application"] = get_success_data(
        api_client.withdraw_application(
            world["application"]["id"],
            {"reason": "Board deferred the project"},
            make_applicant_headers(applicant_a["id"]),
        )
    )
    return world


class TestSubmissionDependsOnTheCycleStage:
    def test_a_valid_draft_cannot_be_submitted_while_the_cycle_awaits_letters(self):
        """Nothing is wrong with the application; the cycle is simply not open yet.

        PRD §3.4: "Submission moves the application from `DRAFT` to `SUBMITTED`
        and is where the cross-entity guard bites: the application's own state is
        not enough, because the sibling cycle must be in `OPEN_FOR_APPLICATIONS`
        at that moment."
        PRD §3.4: "An application not in `DRAFT`, or whose cycle has not yet
        opened for applications or has already moved past that stage, is refused
        with `ERR_APPLICATION_NOT_SUBMITTABLE`."

        Design: Difficulty/cross_entity_state_dependency/application_submit_requires_cycle_open_for_applications
        """
        world = seed_draft_application()
        assert world["cycle"]["status"] == "OPEN_FOR_LOI"
        assert world["application"]["status"] == "DRAFT"

        response = api_client.submit_application(
            world["application"]["id"],
            make_applicant_headers(world["applicant"]["id"]),
        )

        validate_error(response, ApiErrorId.ERR_APPLICATION_NOT_SUBMITTABLE, 409)
        assert refresh_application(world["application"]["id"])["status"] == "DRAFT"

    def test_the_identical_call_succeeds_once_the_cycle_opens(self):
        """Only the sibling cycle changed, and the same request now writes.

        PRD §3.4: "Submission moves the application from `DRAFT` to `SUBMITTED`
        and is where the cross-entity guard bites: the application's own state is
        not enough, because the sibling cycle must be in `OPEN_FOR_APPLICATIONS`
        at that moment."
        PRD §3.4: "A successful submission increases the application's `version`
        by 1."

        Design: Difficulty/cross_entity_state_dependency/application_submit_requires_cycle_open_for_applications
        """
        world = seed_draft_application()
        headers = make_applicant_headers(world["applicant"]["id"])
        api_client.submit_application(world["application"]["id"], headers)
        version_before = world["application"]["version"]

        cycle = advance_cycle(world["cycle"]["id"], "OPEN_FOR_APPLICATIONS")
        response = api_client.submit_application(world["application"]["id"], headers)

        application = get_success_data(response, 200)
        assert cycle["status"] == "OPEN_FOR_APPLICATIONS"
        assert application["status"] == "SUBMITTED"
        assert application["version"] == version_before + 1


class TestInterventionGrantDependsOnTheApplication:
    def test_granting_against_a_withdrawn_application_is_refused(self):
        """The intervention is decidable; its target has left intake.

        PRD §3.6: "Granting additionally requires that the target application
        still be live in intake, meaning its `status` is one of `SUBMITTED`,
        `COMPLETENESS_REVIEW`, `INCOMPLETE` or `DEEMED_COMPLETE`; granting
        intervenor status against an application that has moved beyond intake is
        refused with `ERR_APPLICATION_NOT_IN_COMPLETENESS_REVIEW`."

        Design: Difficulty/cross_entity_state_dependency/intervention_grant_denied_when_target_application_withdrawn
        """
        world = _requested_intervention_against_a_withdrawn_application()
        assert world["intervention"]["status"] == "REQUESTED"
        assert world["application"]["status"] == "WITHDRAWN"

        response = api_client.decide_intervention(
            world["intervention"]["id"], {"decision": "GRANT"}, INTAKE
        )

        body = validate_error(
            response, ApiErrorId.ERR_APPLICATION_NOT_IN_COMPLETENESS_REVIEW, 409
        )
        assert body["error_id"] != ApiErrorId.ERR_INTERVENTION_ALREADY_DECIDED

    def test_the_refused_grant_leaves_the_intervention_undecided(self):
        """No decided_by_user_id is stamped by a rejected ruling.

        PRD §3.6: "The server stamps `filed_at` and initialises `status` to
        `REQUESTED`; `decided_by_user_id` and `denial_reason` are both null while
        the request is pending."
        PRD §3.6: "Either ruling sets `status` to `GRANTED` or `DENIED`, stamps
        `decided_by_user_id` from the acting analyst's `X-User-ID`, records
        `denial_reason` on a denial, and increases the intervention's `version` by
        1."

        Design: Difficulty/cross_entity_state_dependency/intervention_grant_denied_when_target_application_withdrawn
        """
        world = _requested_intervention_against_a_withdrawn_application()

        api_client.decide_intervention(
            world["intervention"]["id"], {"decision": "GRANT"}, INTAKE
        )

        intervention = refresh_intervention(world["intervention"]["id"], ADMIN)
        assert intervention["status"] == "REQUESTED"
        assert intervention["decided_by_user_id"] is None
        assert intervention["denial_reason"] is None
