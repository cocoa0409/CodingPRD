"""Initial states, terminal lockdowns and cross-entity preconditions."""
from test_helpers import (
    ApiErrorId,
    create_placement_payload,
    err,
    validate_error,
    validate_success,
)

from test_helpers.fixtures import (
    ADMIN,
    DECIDER,
    PLACEMENT_COORDINATOR,
    REVIEWER,
    activate_district,
    create_application,
    create_applicant,
    create_district,
    create_matched_placement,
    create_region,
    create_school,
    get_district,
    get_member,
    list_milestones,
    list_placements,
    record_practice_hours,
    setup_exited_member,
    setup_member_scenario,
)


class TestApplicationInitialState:
    def test_new_application_starts_submitted_with_zero_revisions(self, api):
        """PRD §3.2: "A newly submitted application enters the pipeline at `SUBMITTED`, with its `revision_count` set to 0, and its `selection_score` computed immediately using the provisional variant described below."

        Design: Corner/state_machines/application_initial_state_is_submitted
        """
        region = create_region()
        applicant = create_applicant()
        application = create_application(applicant["id"], region["id"])

        assert application["status"] == "SUBMITTED"
        assert application["revision_count"] == 0
        assert application.get("returned_at") is None
        assert application.get("reviewed_by_user_id") is None
        assert application.get("decided_by_user_id") is None
        assert application.get("created_corps_member_id") is None


class TestApplicationTerminalLockdown:
    def test_rejected_application_refuses_every_further_transition(self, api):
        """PRD §3.3: "Note that `REJECTED` and `ACCEPTED` are the application's two terminal states: once an application sits in either, further transitions against it are refused with `ERR_ALREADY_TERMINAL` (HTTP 409)."
        PRD §2.10: "a transition requested against a resource already sitting in one of its terminal states is `ERR_ALREADY_TERMINAL` (HTTP 409), which is reported on application review, return, resubmit, decision and offer"

        Design: Corner/state_machines/application_rejected_is_terminal
        """
        region = create_region()
        applicant = create_applicant()
        application = create_application(applicant["id"], region["id"])
        app_id = application["id"]

        validate_success(api.review_application(app_id, 4.0, REVIEWER))
        rejected = validate_success(
            api.decide_application(app_id, "REJECT", DECIDER, decision_reason="no open need")
        )
        assert rejected["status"] == "REJECTED"

        validate_error(
            api.review_application(app_id, 4.0, REVIEWER),
            err(ApiErrorId.ERR_ALREADY_TERMINAL),
            409,
        )
        validate_error(
            api.extend_offer(app_id, REVIEWER), err(ApiErrorId.ERR_ALREADY_TERMINAL), 409
        )

        after = validate_success(api.get_application(app_id, REVIEWER))
        assert after["status"] == "REJECTED"


class TestExitedMemberLockdown:
    def test_exited_member_refuses_leave_and_placement(self, api):
        """PRD §3.9: "`EXITED` is the service dimension's terminal state, and a member who has exited cannot be put on leave, returned from leave, or exited a second time — those attempts are refused with `ERR_ALREADY_TERMINAL` (HTTP 409)."
        PRD §2.10: "A member whose service is not `ACTIVE` where active service is required is `ERR_MEMBER_NOT_ACTIVE` (HTTP 409), reported on placement creation, confirmation and reinstatement."

        Design: Corner/state_machines/corps_member_exited_blocks_leave_and_placement
        """
        scenario = setup_exited_member()
        member_id = scenario["member_id"]
        member = validate_success(api.get_corps_member(member_id, PLACEMENT_COORDINATOR))
        assert member["service_status"] == "EXITED"

        validate_error(
            api.place_member_on_leave(member_id, PLACEMENT_COORDINATOR),
            err(ApiErrorId.ERR_ALREADY_TERMINAL),
            409,
        )

        payload = create_placement_payload(
            member_id, scenario["school"]["id"], member["version"]
        )
        validate_error(
            api.create_placement(payload, PLACEMENT_COORDINATOR),
            err(ApiErrorId.ERR_MEMBER_NOT_ACTIVE),
            409,
        )

        assert list_placements(member_id) == [], "no Placement row may exist"


class TestPlacementAndMilestoneInitialStates:
    def test_new_placement_and_synthesized_milestones_start_clean(self, api):
        """PRD §3.7: "A new placement starts at `status` `MATCHED` with `employment_eligible` false, and its creation advances the member's `version`."
        PRD §3.5: "Newly created milestones start at `progress_status` `PENDING` and `verification_status` `UNVERIFIED`, and the creation advances the member's `version` because the member's schedule has changed."

        Design: Corner/state_machines/placement_and_milestone_initial_states
        """
        scenario = setup_member_scenario()
        member_id = scenario["member_id"]

        placement = create_matched_placement(member_id, scenario["school"]["id"])
        assert placement["status"] == "MATCHED"
        assert placement["employment_eligible"] is False
        assert placement.get("confirmed_at") is None
        assert placement.get("activated_at") is None

        milestones = list_milestones(member_id)
        assert len(milestones) == 4
        assert all(m["progress_status"] == "PENDING" for m in milestones)
        assert all(m["verification_status"] == "UNVERIFIED" for m in milestones)

        district = get_district(scenario["district"]["id"])
        assert district["committed_placement_count"] == 0, (
            "a MATCHED placement does not count toward the hiring commitment"
        )


class TestDistrictActivationPrecondition:
    def test_activation_needs_a_school_and_advances_the_version(self, api):
        """PRD §3.6: "A draft becomes `ACTIVE` only once the district has at least one partner school on file, so an agreement cannot be signed before there is somewhere to place a corps member."
        PRD §2.10: "a transition requested from a state that does not permit it, or with a transition precondition unmet, is `ERR_INVALID_STATE` (HTTP 409) on every transition operation in this document"

        Design: Corner/state_machines/district_activation_requires_at_least_one_school
        """
        region = create_region()
        district = create_district(region["id"])
        assert district["version"] == 1

        validate_error(
            api.set_partner_district_status(district["id"], "ACTIVE", ADMIN),
            err(ApiErrorId.ERR_INVALID_STATE),
            409,
        )
        still_draft = get_district(district["id"])
        assert still_draft["agreement_status"] == "DRAFT"

        create_school(district)
        activated = activate_district(district["id"])
        assert activated["agreement_status"] == "ACTIVE"
        assert activated["version"] == 3, (
            "one advance for the school create and one for the activation"
        )


class TestActivationInstituteGate:
    def test_activate_blocked_while_institute_in_training(self, api):
        """PRD §3.7: "two conditions guard it: the member's `institute_status` must be `COMPLETED`, or the request fails with `ERR_INSTITUTE_INCOMPLETE` (HTTP 409), and the member's `readiness_score` must be at least 60.0"

        Design: Corner/state_machines/placement_activate_blocked_while_institute_incomplete
        """
        scenario = setup_member_scenario()
        member_id = scenario["member_id"]
        record_practice_hours(member_id, 240)
        assert get_member(member_id)["institute_status"] == "IN_TRAINING"

        placement = create_matched_placement(member_id, scenario["school"]["id"])
        confirmed = validate_success(api.confirm_placement(placement["id"], PLACEMENT_COORDINATOR))
        assert confirmed["status"] == "CONFIRMED"

        response = api.activate_placement(placement["id"], PLACEMENT_COORDINATOR)
        validate_error(response, err(ApiErrorId.ERR_INSTITUTE_INCOMPLETE), 409)

        after = validate_success(
            api.list_member_placements(member_id, PLACEMENT_COORDINATOR)
        )[0]
        assert after["status"] == "CONFIRMED"
        assert after.get("activated_at") is None
        assert after["employment_eligible"] is False
