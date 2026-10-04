"""Role authorization: exclusive operations versus shared reads."""
from test_helpers import (
    ApiErrorId,
    HTTP_STATUS_CODES,
    create_certification_milestone_payload,
    create_placement_payload,
    err,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)

from test_helpers.fixtures import (
    COACH,
    COMPLETER,
    INSTITUTE_DIRECTOR,
    PLACEMENT_COORDINATOR,
    REVIEWER,
    applicant_headers,
    create_application,
    create_applicant,
    create_matched_placement,
    create_region,
    get_member,
    list_milestones,
    list_placements,
    milestones_by_type,
    record_practice_hours,
    setup_member_scenario,
    setup_offered_application,
    start_milestone,
)


class TestApplicantCannotReview:
    def test_owning_applicant_is_refused_the_review_operation(self, api):
        """PRD §4: the review operation is authorized to `SelectionManager` alone.
        PRD §2.1: "A request whose role is valid but is not on the authorized list of the target operation is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        Design: Corner/rbac/applicant_cannot_run_selection_review
        """
        region = create_region()
        applicant = create_applicant()
        application = create_application(applicant["id"], region["id"])

        response = api.review_application(
            application["id"], 4.0, applicant_headers(applicant["id"])
        )
        validate_error(response, err(ApiErrorId.ERR_FORBIDDEN_ROLE), 403)

        after = validate_success(api.get_application(application["id"], REVIEWER))
        assert after["status"] == "SUBMITTED"
        assert after.get("reviewed_by_user_id") is None


class TestCoachCannotCreatePlacementOrMilestone:
    def test_coach_is_refused_both_creation_operations(self, api):
        """PRD §2.1: "A request whose role is valid but is not on the authorized list of the target operation is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        The Coach role owns only the support-record creation operation.

        Design: Corner/rbac/coach_cannot_create_placement_or_milestone
        """
        scenario = setup_member_scenario()
        member_id = scenario["member_id"]
        member = get_member(member_id)

        placement_payload = create_placement_payload(
            member_id, scenario["school"]["id"], member["version"]
        )
        validate_error(
            api.create_placement(placement_payload, COACH),
            err(ApiErrorId.ERR_FORBIDDEN_ROLE),
            403,
        )

        milestone_payload = create_certification_milestone_payload(
            member_id,
            scenario["pathway"]["id"],
            member["version"],
            milestone_type="EXAM",
            required_hours=10,
            due_date="2026-11-01T00:00:00Z",
        )
        validate_error(
            api.create_certification_milestone(milestone_payload, COACH),
            err(ApiErrorId.ERR_FORBIDDEN_ROLE),
            403,
        )

        assert list_placements(member_id) == []
        assert len(list_milestones(member_id)) == 4


class TestCoordinatorCannotVerify:
    def test_shared_read_succeeds_but_verify_is_refused(self, api):
        """PRD §4: the milestone read is authorized to `PlacementCoordinator` and `CertificationOfficer`, while verify is authorized to `CertificationOfficer` alone.
        PRD §2.1: "A request whose role is valid but is not on the authorized list of the target operation is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        Design: Corner/rbac/placement_coordinator_cannot_verify_milestone
        """
        scenario = setup_member_scenario()
        member_id = scenario["member_id"]
        record_practice_hours(member_id, 240)
        milestone_id = milestones_by_type(member_id)["COURSEWORK"]["id"]

        start_milestone(milestone_id)
        validate_success(api.complete_certification_milestone(milestone_id, COMPLETER))

        read = validate_success(
            api.get_certification_milestone(milestone_id, PLACEMENT_COORDINATOR)
        )
        assert read["verification_status"] == "UNVERIFIED"

        response = api.verify_certification_milestone(
            milestone_id, "VERIFY", PLACEMENT_COORDINATOR
        )
        validate_error(response, err(ApiErrorId.ERR_FORBIDDEN_ROLE), 403)

        after = validate_success(
            api.get_certification_milestone(milestone_id, COMPLETER)
        )
        assert after["verification_status"] == "UNVERIFIED"
        assert after.get("verified_by_user_id") is None


class TestApplicantCannotAnswerAnothersOffer:
    def test_foreign_applicant_is_refused_and_the_owner_succeeds(self, api):
        """PRD §3.3: "The offer is answered by the applicant alone; any other role, or an applicant whose `X-User-ID` does not match the application's `applicant_id`, is turned away."
        PRD §2.10: "a transition requested from a state that does not permit it, or with a transition precondition unmet, is `ERR_INVALID_STATE` (HTTP 409)"

        Design: Corner/rbac/applicant_cannot_answer_another_applicants_offer
        """
        offered = setup_offered_application()
        app_id = offered["application"]["id"]

        stranger = create_applicant(full_name="Bo Chen", email="bo@x.edu")
        response = api.respond_to_offer(app_id, True, applicant_headers(stranger["id"]))
        # PRD §3.3 says only that a non-owning applicant "is turned away" and names
        # no error identifier for it, so either the authorization reading
        # (ERR_FORBIDDEN_ROLE) or the unmet-precondition reading (ERR_INVALID_STATE)
        # is conforming; the refusal and the untouched offer below are the pinned part.
        refused = validate_error_is_one_of(
            response,
            [err(ApiErrorId.ERR_FORBIDDEN_ROLE), err(ApiErrorId.ERR_INVALID_STATE)],
        )
        assert response.status_code == HTTP_STATUS_CODES[ApiErrorId(refused)], (
            f"{refused} must carry its catalogue HTTP status"
        )

        still_open = validate_success(api.get_application(app_id, REVIEWER))
        assert still_open["status"] == "OFFER_EXTENDED"

        accepted = validate_success(
            api.respond_to_offer(
                app_id, True, applicant_headers(offered["applicant"]["id"])
            )
        )
        assert accepted["status"] == "ACCEPTED"


class TestInstituteDirectorCannotExit:
    def test_shared_read_succeeds_but_exit_is_refused(self, api):
        """PRD §4: the member read is authorized to `InstituteDirector`, while the exit operation is authorized to `PlacementCoordinator` alone.
        PRD §2.1: "A request whose role is valid but is not on the authorized list of the target operation is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        Design: Corner/rbac/institute_director_cannot_exit_corps_member
        """
        scenario = setup_member_scenario()
        member_id = scenario["member_id"]

        read = validate_success(api.get_corps_member(member_id, INSTITUTE_DIRECTOR))
        assert read["service_status"] == "ACTIVE"

        response = api.exit_corps_member(member_id, "not my call to make", INSTITUTE_DIRECTOR)
        validate_error(response, err(ApiErrorId.ERR_FORBIDDEN_ROLE), 403)

        after = get_member(member_id)
        assert after["service_status"] == "ACTIVE"
        assert after.get("exit_reason") is None
