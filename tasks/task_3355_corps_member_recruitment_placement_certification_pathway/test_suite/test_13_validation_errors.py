"""Business-rule violations and the auth ladder."""
from test_helpers import (
    ApiErrorId,
    assert_same_instant,
    build_user_headers,
    create_certification_milestone_payload,
    create_region_payload,
    err,
    validate_error,
    validate_success,
)

from test_helpers.fixtures import (
    ADMIN,
    COMPLETER,
    DECIDER,
    INSTITUTE_DIRECTOR,
    REVIEWER,
    applicant_headers,
    create_application,
    create_applicant,
    create_pathway,
    create_region,
    get_member,
    list_milestones,
    milestones_by_type,
    record_practice_hours,
    review,
    set_clock,
    setup_member_scenario,
    setup_offered_application,
    start_milestone,
)


class TestAuthenticationLadder:
    def test_undeclared_role_is_unauthenticated_not_forbidden(self, api):
        """PRD §2.1: "A request that omits either header, or that names a role outside that set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
        PRD §2.1: "A request whose role is valid but is not on the authorized list of the target operation is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        Design: Corner/validations/unknown_role_returns_unauthenticated_not_forbidden
        """
        ghost = build_user_headers("ghost_1", "Ghost")
        validate_error(
            api.create_region(create_region_payload(), ghost),
            err(ApiErrorId.ERR_UNAUTHENTICATED),
            401,
        )

        coach = build_user_headers("coach_lee", "Coach")
        validate_error(
            api.create_region(create_region_payload(), coach),
            err(ApiErrorId.ERR_FORBIDDEN_ROLE),
            403,
        )


class TestDuplicateApplication:
    def test_second_live_application_refused_but_a_rejected_one_frees_the_slot(self, api):
        """PRD §3.2: "An applicant may hold at most one application whose `status` is neither `REJECTED` nor `DECLINED`; a second submission while such an application exists is refused with `ERR_DUPLICATE_APPLICATION` (HTTP 409)."
        PRD §3.2: "Applications that have already been rejected or declined do not stand in the way of a fresh submission."

        Design: Corner/validations/duplicate_application_rejected
        """
        region = create_region()
        applicant = create_applicant()
        first = create_application(applicant["id"], region["id"], subject_area="MATH")

        duplicate = api.create_application(
            {
                "applicant_id": applicant["id"],
                "preferred_region_id": region["id"],
                "subject_area": "SCIENCE",
                "grade_preference": "HIGH",
            },
            REVIEWER,
        )
        validate_error(duplicate, err(ApiErrorId.ERR_DUPLICATE_APPLICATION), 409)

        review(first["id"], 4.0, REVIEWER)
        validate_success(api.decide_application(first["id"], "REJECT", DECIDER))

        second = validate_success(
            api.create_application(
                {
                    "applicant_id": applicant["id"],
                    "preferred_region_id": region["id"],
                    "subject_area": "SCIENCE",
                    "grade_preference": "HIGH",
                },
                REVIEWER,
            ),
            201,
        )
        assert second["status"] == "SUBMITTED"
        assert second["id"] != first["id"]


class TestMilestonePastDue:
    def test_completing_after_the_due_date_is_refused(self, api):
        """PRD §3.5: "A milestone may not be completed once its `due_date` has passed on the logical clock: comparing the clock's date against the milestone's due date, a completion attempted after that date is refused with `ERR_MILESTONE_PAST_DUE` (HTTP 422)."

        Design: Corner/validations/milestone_complete_past_due_rejected
        """
        scenario = setup_member_scenario()
        member_id = scenario["member_id"]
        record_practice_hours(member_id, 240)
        milestone_id = milestones_by_type(member_id)["COURSEWORK"]["id"]
        start_milestone(milestone_id)

        set_clock("2026-11-15T00:00:00Z")
        response = api.complete_certification_milestone(milestone_id, COMPLETER)
        validate_error(response, err(ApiErrorId.ERR_MILESTONE_PAST_DUE), 422)

        after = validate_success(
            api.get_certification_milestone(milestone_id, COMPLETER)
        )
        assert after["progress_status"] == "IN_PROGRESS"
        assert after.get("completed_at") is None


class TestPracticeHoursCeiling:
    def test_ceiling_is_enforced_inclusively_at_480(self, api):
        """PRD §3.4: "The member's current `practice_teaching_hours` plus the requested `practice_hours_delta` may not exceed 480 hours, and a record that would push the total past that ceiling is refused with `ERR_PRACTICE_HOURS_EXCEEDED` (HTTP 422)"

        Design: Corner/validations/practice_hours_ceiling_rejected
        """
        scenario = setup_member_scenario()
        member_id = scenario["member_id"]
        record_practice_hours(member_id, 240)

        response = api.record_practice_hours(member_id, 300, INSTITUTE_DIRECTOR)
        validate_error(response, err(ApiErrorId.ERR_PRACTICE_HOURS_EXCEEDED), 422)
        assert get_member(member_id)["practice_teaching_hours"] == 240

        accepted = record_practice_hours(member_id, 240)
        assert accepted["practice_teaching_hours"] == 480, (
            "the boundary value itself is allowed"
        )


class TestOfferExpiry:
    def test_response_after_the_window_is_refused(self, api):
        """PRD §3.3: "A successful extension moves the application to `OFFER_EXTENDED` and sets `offer_expires_at` to the current logical clock plus 14 days."
        PRD §3.3: "The clock must not have passed `offer_expires_at`; an answer that arrives after the window has closed is refused with `ERR_OFFER_EXPIRED` (HTTP 409)."

        Design: Corner/validations/offer_expired_rejected
        """
        set_clock("2026-09-01T00:00:00Z")
        offered = setup_offered_application()
        app_id = offered["application"]["id"]
        assert_same_instant(
            offered["application"]["offer_expires_at"],
            "2026-09-15T00:00:00Z",
            "offer_expires_at",
        )

        set_clock("2026-09-16T00:00:00Z")
        response = api.respond_to_offer(app_id, True, applicant_headers(offered["applicant"]["id"]))
        validate_error(response, err(ApiErrorId.ERR_OFFER_EXPIRED), 409)

        after = validate_success(api.get_application(app_id, REVIEWER))
        assert after["status"] == "OFFER_EXTENDED"
        assert after.get("created_corps_member_id") is None


class TestPathwayRegionMismatch:
    def test_milestone_under_another_regions_pathway_is_refused(self, api):
        """PRD §3.5: "A milestone must belong to the member's own jurisdiction. The pathway named on the milestone must sit in the same region the member's application selected — the pathway's `region_id` must equal the region that the member's owning application named as its `preferred_region_id`."
        PRD §3.5: "A milestone raised under a pathway from any other region is refused with `ERR_PATHWAY_REGION_MISMATCH` (HTTP 422)"

        Design: Corner/validations/pathway_region_mismatch_rejected
        """
        scenario = setup_member_scenario()
        member_id = scenario["member_id"]

        other_region = create_region(region_code="RIVER", name="River")
        other_pathway = create_pathway(
            other_region["id"],
            certification_track="PROVISIONAL",
            required_coursework_hours=40,
            required_practice_hours=80,
            deadline_days_before_term=45,
            coursework_fee_cents=180000,
        )

        member = get_member(member_id)
        payload = create_certification_milestone_payload(
            member_id,
            other_pathway["id"],
            member["version"],
            milestone_type="EXAM",
            required_hours=10,
            due_date="2026-11-01T00:00:00Z",
        )
        response = api.create_certification_milestone(payload, COMPLETER)
        validate_error(response, err(ApiErrorId.ERR_PATHWAY_REGION_MISMATCH), 422)

        assert len(list_milestones(member_id)) == 4, (
            "the refused milestone must not be appended to the schedule"
        )
