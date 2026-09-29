"""One rejection code per failing condition, distinguished from its neighbours."""

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_instant_equals,
    get_success_data,
    validate_error,
    validate_paginated,
)
from test_helpers.constants import (
    APPEAL_WINDOW_CLOSES,
    ISSUANCE_CLOCK,
    UNKNOWN_APPEAL_ID,
    UNKNOWN_APPLICANT_ID,
    UNKNOWN_APPLICATION_ID,
    UNKNOWN_CERTIFICATE_ID,
    UNKNOWN_COMPLETENESS_REVIEW_ID,
    UNKNOWN_CYCLE_ID,
    UNKNOWN_FORMULA_ID,
    UNKNOWN_HEARING_ID,
    UNKNOWN_HEARING_ROOM_ID,
    UNKNOWN_INTERVENTION_ID,
    UNKNOWN_LOI_ID,
)
from test_helpers.factories import (
    appeal_payload,
    application_payload,
    batching_cycle_payload,
    certificate_payload,
    public_hearing_payload,
)
from test_helpers.fixtures import (
    ADMIN,
    BOARD,
    INTAKE,
    OFFICER,
    advance_appeal,
    advance_cycle,
    create_application,
    decide_intervention,
    file_appeal,
    file_letter_of_intent,
    file_progress_report,
    refresh_appeal,
    refresh_application,
    refresh_certificate,
    refresh_cycle,
    refresh_health_service_area,
    refresh_letter_of_intent,
    refresh_public_hearing,
    request_intervention,
    seed_applicant,
    seed_application_deemed_complete,
    seed_batching_cycle,
    seed_completeness_window,
    seed_decided_cycle,
    seed_draft_application,
    seed_hearing_room,
    seed_issued_certificate,
    seed_second_applicant,
    set_clock,
    submit_application,
)
from test_helpers.test_users import build_user_headers, make_applicant_headers

LATE_CALENDAR = {
    "loi_deadline_at": "2026-10-10T00:00:00Z",
    "application_deadline_at": "2026-10-20T00:00:00Z",
    "comment_period_closes_at": "2026-10-25T00:00:00Z",
    "intervention_deadline_at": "2026-10-28T00:00:00Z",
    "completeness_deadline_at": "2026-11-05T00:00:00Z",
    "decision_deadline_at": "2026-11-30T00:00:00Z",
}
HEARING_START = "2026-08-26T09:00:00Z"
HEARING_END = "2026-08-26T11:00:00Z"
NEW_HEARING_START = "2026-08-27T14:00:00Z"
NEW_HEARING_END = "2026-08-27T16:00:00Z"
PAST_APPLICATION_DEADLINE_CLOCK = "2026-08-21T00:00:00Z"
APPEAL_FILING_CLOCK = "2026-10-01T00:00:00Z"
PAST_MILESTONE_CLOCK = "2027-07-01T00:00:00Z"


def _scheduled_hearing():
    world = seed_batching_cycle()
    world["room"] = seed_hearing_room(name="BOARD-A")
    world["hearing"] = get_success_data(
        api_client.create_public_hearing(
            public_hearing_payload(
                world["cycle"]["id"],
                world["room"]["id"],
                scheduled_start_at=HEARING_START,
                scheduled_end_at=HEARING_END,
            ),
            INTAKE,
        ),
        201,
    )
    return world


def _two_submitted_applications():
    """One cycle in COMPLETENESS_WINDOW carrying two submitted applications."""
    world = seed_batching_cycle()
    applicant_a = seed_applicant()
    applicant_b = seed_second_applicant()
    world["applicant"] = applicant_a
    world["applicant_b"] = applicant_b
    loi_a = file_letter_of_intent(world, applicant_a)
    loi_b = file_letter_of_intent(
        world,
        applicant_b,
        project_description="10-bed acute care expansion",
        capital_cost_cents=600000000,
        bed_delta=10,
    )
    world["application_a"] = create_application(world, applicant_a, loi_a)
    world["application_b"] = create_application(
        world,
        applicant_b,
        loi_b,
        requested_bed_count=10,
        projected_capital_cost_cents=600000000,
        narrative="Lakeview 10-bed acute care application",
        partial_award_acceptable=True,
    )
    advance_cycle(world["cycle"]["id"], "OPEN_FOR_APPLICATIONS")
    world["application_a"] = submit_application(world["application_a"], applicant_a)
    world["application_b"] = submit_application(world["application_b"], applicant_b)
    world["cycle"] = advance_cycle(world["cycle"]["id"], "COMPLETENESS_WINDOW")
    return world


class TestNotFoundCodesAreTyped:
    def test_each_identifier_class_answers_with_its_own_not_found_code(self):
        """Ten lookups, ten distinct codes, and nothing written along the way.

        PRD §2.8: "**Path-parameter existence**, resolved left to right along the
        path: a cycle identifier that resolves to nothing yields
        `ERR_CYCLE_NOT_FOUND`, a letter-of-intent identifier `ERR_LOI_NOT_FOUND`,
        an application identifier `ERR_APPLICATION_NOT_FOUND`, a
        completeness-review identifier `ERR_COMPLETENESS_REVIEW_NOT_FOUND`, an
        intervention identifier `ERR_INTERVENTION_NOT_FOUND`, a hearing identifier
        `ERR_HEARING_NOT_FOUND`, a certificate identifier
        `ERR_CERTIFICATE_NOT_FOUND`, an appeal identifier `ERR_APPEAL_NOT_FOUND`, a
        planning-area identifier `ERR_HSA_NOT_FOUND`, a formula identifier
        `ERR_FORMULA_NOT_FOUND` and an applicant identifier
        `ERR_APPLICANT_NOT_FOUND` — all at 404."
        PRD §2.8: "**Body foreign-key existence**, resolved in the order the
        fields appear in the endpoint's input list: `applicant_id` yields
        `ERR_APPLICANT_NOT_FOUND`, `hsa_id` yields `ERR_HSA_NOT_FOUND`,
        `formula_id` yields `ERR_FORMULA_NOT_FOUND`, `batching_cycle_id` yields
        `ERR_CYCLE_NOT_FOUND`, `loi_id` yields `ERR_LOI_NOT_FOUND`,
        `application_id` yields `ERR_APPLICATION_NOT_FOUND`,
        `affected_party_applicant_id` yields `ERR_APPLICANT_NOT_FOUND`,
        `hearing_room_id` yields `ERR_HEARING_ROOM_NOT_FOUND` and
        `certificate_id` yields `ERR_CERTIFICATE_NOT_FOUND` — all at 404."

        Design: Corner/errors/every_unknown_identifier_class_returns_its_own_not_found_code
        """
        world = seed_batching_cycle()

        validate_error(
            api_client.get_batching_cycle(UNKNOWN_CYCLE_ID, INTAKE),
            ApiErrorId.ERR_CYCLE_NOT_FOUND,
            404,
        )
        validate_error(
            api_client.get_letter_of_intent(UNKNOWN_LOI_ID, INTAKE),
            ApiErrorId.ERR_LOI_NOT_FOUND,
            404,
        )
        validate_error(
            api_client.get_application(UNKNOWN_APPLICATION_ID, INTAKE),
            ApiErrorId.ERR_APPLICATION_NOT_FOUND,
            404,
        )
        validate_error(
            api_client.file_cure(
                UNKNOWN_COMPLETENESS_REVIEW_ID,
                {"cure_response": "Documents attached"},
                make_applicant_headers(UNKNOWN_APPLICANT_ID),
            ),
            ApiErrorId.ERR_COMPLETENESS_REVIEW_NOT_FOUND,
            404,
        )
        validate_error(
            api_client.get_intervention(UNKNOWN_INTERVENTION_ID, INTAKE),
            ApiErrorId.ERR_INTERVENTION_NOT_FOUND,
            404,
        )
        validate_error(
            api_client.get_public_hearing(UNKNOWN_HEARING_ID, INTAKE),
            ApiErrorId.ERR_HEARING_NOT_FOUND,
            404,
        )
        validate_error(
            api_client.get_certificate(UNKNOWN_CERTIFICATE_ID, OFFICER),
            ApiErrorId.ERR_CERTIFICATE_NOT_FOUND,
            404,
        )
        validate_error(
            api_client.get_appeal(UNKNOWN_APPEAL_ID, BOARD),
            ApiErrorId.ERR_APPEAL_NOT_FOUND,
            404,
        )
        validate_error(
            api_client.create_batching_cycle(
                batching_cycle_payload(
                    world["hsa"]["id"], UNKNOWN_FORMULA_ID, **LATE_CALENDAR
                ),
                ADMIN,
            ),
            ApiErrorId.ERR_FORMULA_NOT_FOUND,
            404,
        )
        validate_error(
            api_client.create_public_hearing(
                public_hearing_payload(
                    world["cycle"]["id"],
                    UNKNOWN_HEARING_ROOM_ID,
                    scheduled_start_at=HEARING_START,
                    scheduled_end_at=HEARING_END,
                ),
                INTAKE,
            ),
            ApiErrorId.ERR_HEARING_ROOM_NOT_FOUND,
            404,
        )

        _, cycle_meta = validate_paginated(
            api_client.list_batching_cycles(
                ADMIN, params={"hsa_id": world["hsa"]["id"]}
            )
        )
        assert cycle_meta["total_count"] == 1
        _, hearing_meta = validate_paginated(
            api_client.list_public_hearings(
                INTAKE, params={"batching_cycle_id": world["cycle"]["id"]}
            )
        )
        assert hearing_meta["total_count"] == 0


class TestAuthenticationOutranksShape:
    def test_an_empty_user_id_is_unauthenticated_even_with_an_invalid_body(self):
        """The header check runs first, so the missing field is never reported.

        PRD §2.1: "A request in which either header is missing, or present but an
        empty string, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401); an
        empty-string header counts as absent."
        PRD §2.8: "**Header presence.** `X-User-Role` and `X-User-ID` are both
        present and non-empty — otherwise `ERR_UNAUTHENTICATED` (401). Applies to
        every endpoint."

        Design: Corner/errors/empty_user_id_header_returns_unauthenticated_before_any_other_check
        """
        response = api_client.create_health_service_area(
            {"code": "HSA-GHOST", "name": "Unauthenticated Area"},
            build_user_headers("", "ProgramAdmin"),
        )

        body = validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED, 401)
        assert body["error_id"] != ApiErrorId.ERR_INVALID_REQUEST
        _, meta = validate_paginated(api_client.list_batching_cycles(ADMIN))
        assert meta["total_count"] == 0


class TestLetterOfIntentUsability:
    def test_a_non_reviewable_letter_cannot_be_converted(self):
        """The letter is FILED and owned by the caller; it simply needs no review.

        PRD §3.4: "A letter whose `review_determination` is `NON_REVIEWABLE` cannot
        become an application — the project does not need a certificate — and the
        attempt yields `ERR_LOI_NOT_REVIEWABLE`."
        PRD §2.8: "**Letter-of-intent usability.** The letter's
        `review_determination` is `REVIEWABLE` (`ERR_LOI_NOT_REVIEWABLE`) and its
        `status` is `FILED` (`ERR_LOI_ALREADY_CONVERTED`), both at 409. This rule
        guards application creation."

        Design: Corner/errors/converting_a_non_reviewable_letter_of_intent_returns_loi_not_reviewable
        """
        world = seed_batching_cycle()
        applicant = seed_applicant()
        world["applicant"] = applicant
        loi = file_letter_of_intent(
            world,
            applicant,
            project_description="Three-bed observation annex",
            capital_cost_cents=250000000,
            bed_delta=3,
        )
        assert loi["review_determination"] == "NON_REVIEWABLE"

        response = api_client.create_application(
            application_payload(
                loi["id"],
                requested_bed_count=3,
                projected_capital_cost_cents=250000000,
                narrative="Observation annex application",
            ),
            make_applicant_headers(applicant["id"]),
        )

        validate_error(response, ApiErrorId.ERR_LOI_NOT_REVIEWABLE, 409)
        assert refresh_letter_of_intent(loi["id"])["status"] == "FILED"
        _, meta = validate_paginated(
            api_client.list_applications(ADMIN, params={"loi_id": loi["id"]})
        )
        assert meta["total_count"] == 0


class TestHearingStateGuards:
    def test_a_still_scheduled_hearing_cannot_be_rescheduled(self):
        """Rescheduling is the way back from CANCELLED, not a way to move a live slot.

        PRD §3.6: "the hearing must currently be `CANCELLED`, or the request is
        refused with `ERR_HEARING_NOT_RESCHEDULABLE`, and the new buffered occupancy
        interval is checked for overlap against the `SCHEDULED` hearings of the
        target room exactly as at creation, with the same `ERR_HEARING_ROOM_CONFLICT`
        on failure."
        PRD §2.8: "**Participation-target state.** An intervention must be
        `REQUESTED` to be decided (`ERR_INTERVENTION_ALREADY_DECIDED`); a hearing
        must be `SCHEDULED` to be concluded or cancelled
        (`ERR_HEARING_NOT_SCHEDULED`); a hearing must be `CANCELLED` to be
        rescheduled (`ERR_HEARING_NOT_RESCHEDULABLE`); and the logical clock must be
        at or past `scheduled_end_at` to conclude (`ERR_HEARING_NOT_CONCLUDABLE`).
        All at 409."

        Design: Corner/errors/rescheduling_a_still_scheduled_hearing_returns_hearing_not_reschedulable
        """
        world = _scheduled_hearing()
        assert world["hearing"]["status"] == "SCHEDULED"

        response = api_client.reschedule_public_hearing(
            world["hearing"]["id"],
            {
                "scheduled_start_at": NEW_HEARING_START,
                "scheduled_end_at": NEW_HEARING_END,
            },
            INTAKE,
        )

        validate_error(response, ApiErrorId.ERR_HEARING_NOT_RESCHEDULABLE, 409)
        hearing = refresh_public_hearing(world["hearing"]["id"], INTAKE)
        assert hearing["status"] == "SCHEDULED"
        assert_instant_equals(hearing["scheduled_start_at"], HEARING_START)
        assert hearing["reschedule_count"] == 0

    def test_an_already_cancelled_hearing_cannot_be_cancelled_again(self):
        """The second cancellation neither succeeds nor rewrites the first reason.

        PRD §3.6: "A scheduled hearing may be cancelled, optionally with a `reason`;
        cancellation sets `status` to `CANCELLED`, increases `version` by 1, and
        releases the room: the cancelled row's buffered interval is ignored by every
        later overlap check."
        PRD §2.8: "**Participation-target state.** An intervention must be
        `REQUESTED` to be decided (`ERR_INTERVENTION_ALREADY_DECIDED`); a hearing
        must be `SCHEDULED` to be concluded or cancelled
        (`ERR_HEARING_NOT_SCHEDULED`); a hearing must be `CANCELLED` to be
        rescheduled (`ERR_HEARING_NOT_RESCHEDULABLE`); and the logical clock must be
        at or past `scheduled_end_at` to conclude (`ERR_HEARING_NOT_CONCLUDABLE`).
        All at 409."

        Design: Corner/errors/cancelling_an_already_cancelled_hearing_returns_hearing_not_scheduled
        """
        world = _scheduled_hearing()
        cancelled = get_success_data(
            api_client.cancel_public_hearing(
                world["hearing"]["id"], {"reason": "Room flooded"}, INTAKE
            )
        )
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["version"] == world["hearing"]["version"] + 1

        response = api_client.cancel_public_hearing(
            world["hearing"]["id"], {"reason": "Cancelled again by mistake"}, INTAKE
        )

        validate_error(response, ApiErrorId.ERR_HEARING_NOT_SCHEDULED, 409)
        hearing = refresh_public_hearing(world["hearing"]["id"], INTAKE)
        assert hearing["status"] == "CANCELLED"
        assert hearing["reschedule_count"] == 0
        assert hearing["attendee_count"] is None
        assert hearing["version"] == cancelled["version"]


class TestFilingWindowOnSubmission:
    def test_submitting_one_day_late_is_a_window_failure_not_a_state_failure(self):
        """DRAFT and OPEN_FOR_APPLICATIONS both hold; only the clock has moved on.

        PRD §3.4: "Only the owning applicant may submit, or the request fails with
        `ERR_NOT_FILING_OWNER`; the applicant's `standing` must be `GOOD`, or
        `ERR_APPLICANT_STANDING_RESTRICTED` applies; and the logical clock must be
        at or before the cycle's `application_deadline_at`, or the request is
        refused with `ERR_FILING_WINDOW_CLOSED`."
        PRD §2.8: "**Filing windows.** Letters of intent by `loi_deadline_at`
        (`ERR_LOI_WINDOW_CLOSED`); application submission and the completeness
        actions by `application_deadline_at` and `completeness_deadline_at`
        respectively (`ERR_FILING_WINDOW_CLOSED`); a cure by the review's
        `cure_deadline_at` (`ERR_CURE_DEADLINE_PASSED`). All bounds inclusive, all at
        409."

        Design: Corner/errors/submitting_after_the_application_deadline_returns_filing_window_closed
        """
        world = seed_draft_application()
        cycle = advance_cycle(world["cycle"]["id"], "OPEN_FOR_APPLICATIONS")
        assert cycle["status"] == "OPEN_FOR_APPLICATIONS"
        assert world["application"]["status"] == "DRAFT"
        set_clock(PAST_APPLICATION_DEADLINE_CLOCK)

        response = api_client.submit_application(
            world["application"]["id"],
            make_applicant_headers(world["applicant"]["id"]),
        )

        validate_error(response, ApiErrorId.ERR_FILING_WINDOW_CLOSED, 409)
        application = refresh_application(world["application"]["id"])
        assert application["status"] == "DRAFT"
        assert application["version"] == world["application"]["version"]
        assert refresh_cycle(world["cycle"]["id"])["status"] == "OPEN_FOR_APPLICATIONS"


class TestCycleAdvanceGates:
    def test_one_unresolved_sibling_blocks_the_whole_batch(self):
        """A is resolved, B is not, and the advance leaves both exactly as they were.

        PRD §3.5: "The gate first: no application of the cycle may still be in
        `SUBMITTED` or `COMPLETENESS_REVIEW`, because those are applications whose
        intake is mid-flight; if any is, the advance fails with
        `ERR_CYCLE_HAS_UNRESOLVED_APPLICATIONS`."
        PRD §3.5: "Every application of the cycle in `DEEMED_COMPLETE` is promoted to
        `COMPARATIVE_REVIEW` with its `version` increased by 1."
        PRD §2.8: "**Comparative-review quorum and pool.** The candidate set is
        non-empty (`ERR_NO_ELIGIBLE_APPLICATIONS`, 422); every candidate has at
        least 2 `ACTIVE` score sheets (`ERR_INSUFFICIENT_SCORE_SHEETS`, 422); no
        application of the cycle is still `SUBMITTED` or `COMPLETENESS_REVIEW` when
        advancing to `COMPARATIVE_REVIEW` (`ERR_CYCLE_HAS_UNRESOLVED_APPLICATIONS`,
        409); and every `GRANTED` intervention that demanded a hearing has a `HELD`
        hearing in the cycle (`ERR_MANDATORY_HEARING_NOT_HELD`, 409)."

        Design: Corner/errors/advancing_a_cycle_with_a_still_submitted_application_returns_unresolved_applications
        """
        world = _two_submitted_applications()
        deemed = get_success_data(
            api_client.deem_application_complete(world["application_a"]["id"], INTAKE)
        )
        assert deemed["status"] == "DEEMED_COMPLETE"

        response = api_client.advance_batching_cycle(
            world["cycle"]["id"], "COMPARATIVE_REVIEW", INTAKE
        )

        validate_error(
            response, ApiErrorId.ERR_CYCLE_HAS_UNRESOLVED_APPLICATIONS, 409
        )
        assert refresh_cycle(world["cycle"]["id"])["status"] == "COMPLETENESS_WINDOW"
        assert (
            refresh_application(world["application_a"]["id"])["status"]
            == "DEEMED_COMPLETE"
        )
        assert (
            refresh_application(world["application_b"]["id"])["status"] == "SUBMITTED"
        )

    def test_a_granted_hearing_request_blocks_the_advance_until_one_is_held(self):
        """Every application is resolved, but the promised hearing never happened.

        PRD §3.6: "The consequential case is a `GRANTED` intervention whose
        `requested_hearing` is true: from that moment the cycle cannot reach
        `COMPARATIVE_REVIEW` until at least one public hearing of that cycle has
        reached `HELD`, and an advance attempted before then is refused with
        `ERR_MANDATORY_HEARING_NOT_HELD`."
        PRD §2.8: "**Comparative-review quorum and pool.** The candidate set is
        non-empty (`ERR_NO_ELIGIBLE_APPLICATIONS`, 422); every candidate has at
        least 2 `ACTIVE` score sheets (`ERR_INSUFFICIENT_SCORE_SHEETS`, 422); no
        application of the cycle is still `SUBMITTED` or `COMPLETENESS_REVIEW` when
        advancing to `COMPARATIVE_REVIEW` (`ERR_CYCLE_HAS_UNRESOLVED_APPLICATIONS`,
        409); and every `GRANTED` intervention that demanded a hearing has a `HELD`
        hearing in the cycle (`ERR_MANDATORY_HEARING_NOT_HELD`, 409)."

        Design: Corner/errors/advancing_a_cycle_with_a_granted_hearing_request_not_yet_held_returns_mandatory_hearing_not_held
        """
        world = seed_completeness_window()
        affected_party = seed_second_applicant()
        intervention = request_intervention(
            world["application"],
            affected_party,
            requested_hearing=True,
            grounds="Lakeview serves the same census tracts and demands a hearing",
        )
        granted = decide_intervention(intervention, "GRANT")
        assert granted["status"] == "GRANTED"
        assert granted["requested_hearing"] is True
        deemed = get_success_data(
            api_client.deem_application_complete(world["application"]["id"], INTAKE)
        )
        assert deemed["status"] == "DEEMED_COMPLETE"

        response = api_client.advance_batching_cycle(
            world["cycle"]["id"], "COMPARATIVE_REVIEW", INTAKE
        )

        validate_error(response, ApiErrorId.ERR_MANDATORY_HEARING_NOT_HELD, 409)
        assert refresh_cycle(world["cycle"]["id"])["status"] == "COMPLETENESS_WINDOW"
        _, meta = validate_paginated(
            api_client.list_public_hearings(
                INTAKE, params={"batching_cycle_id": world["cycle"]["id"]}
            )
        )
        assert meta["total_count"] == 0


class TestIssuanceRequiresAnApproval:
    def test_a_merely_complete_application_cannot_be_certificated(self):
        """The state gate fires before the appeal-window gate, which has no instant yet.

        PRD §3.8: "The application must be `APPROVED` or
        `APPROVED_WITH_CONDITIONS`, or the request is refused with
        `ERR_APPLICATION_NOT_APPROVED`."
        PRD §2.8: "**Certificate and appeal state.** A certificate's
        `lifecycle_status` must be `ISSUED`, `IMPLEMENTED` or `SUSPENDED` for
        extension, modification and progress reporting
        (`ERR_CERTIFICATE_NOT_ACTIVE`); an appeal must be in the status the requested
        action demands (`ERR_APPEAL_NOT_IN_REQUIRED_STATUS`); issuance requires the
        application `APPROVED` or `APPROVED_WITH_CONDITIONS`
        (`ERR_APPLICATION_NOT_APPROVED`). All at 409."

        Design: Corner/errors/certificate_issued_for_a_merely_complete_application_returns_application_not_approved
        """
        world = seed_application_deemed_complete()
        application = world["application"]
        assert application["status"] == "DEEMED_COMPLETE"
        assert application["appeal_window_closes_at"] is None

        response = api_client.create_certificate(
            certificate_payload(application["id"]), OFFICER
        )

        validate_error(response, ApiErrorId.ERR_APPLICATION_NOT_APPROVED, 409)
        _, meta = validate_paginated(
            api_client.list_certificates(
                ADMIN, params={"application_id": application["id"]}
            )
        )
        assert meta["total_count"] == 0
        assert (
            refresh_health_service_area(world["hsa"]["id"])[
                "approved_unimplemented_beds"
            ]
            == 0
        )


class TestAppealFilingAndStageGuards:
    def test_a_pending_appeal_blocks_a_duplicate_and_the_stage_cannot_be_skipped(self):
        """Two guards on one pending appeal: no second filing, no jump past briefing.

        PRD §3.9: "The filing must arrive while the logical clock is at or before the
        application's `appeal_window_closes_at`, otherwise
        `ERR_APPEAL_WINDOW_EXPIRED`; no other appeal on the same application may be
        in `FILED`, `BRIEFING`, `STAYED` or `HEARD`, otherwise `ERR_APPEAL_PENDING`;
        and a `BARRED` applicant may not file."
        PRD §3.9: "An `AppealBoardMember` drives the appeal forward by naming the
        destination as `to_status`: `FILED` → `BRIEFING`, then `BRIEFING` → `HEARD`."
        PRD §3.9: "Each advance increases the appeal's `version` by 1, and an advance
        requested from any other status is refused with
        `ERR_APPEAL_NOT_IN_REQUIRED_STATUS`."
        PRD §3.9: "The server stamps `filed_at` from the logical clock, sets `status`
        to `FILED`, sets `litigation_hold_active` to false, and leaves
        `status_before_hold`, `disposition` and `decided_by_user_id` null."

        Design: Corner/errors/appeal_guards_reject_a_duplicate_filing_and_a_skipped_briefing_stage
        """
        world = seed_decided_cycle()
        set_clock(APPEAL_FILING_CLOCK)
        appeal = file_appeal(
            world["application"],
            world["applicant"],
            "Need methodology misapplied to this project",
        )
        assert appeal["status"] == "FILED"
        assert_instant_equals(appeal["filed_at"], APPEAL_FILING_CLOCK)

        duplicate = api_client.create_appeal(
            appeal_payload(
                world["application"]["id"],
                world["applicant"]["id"],
                grounds="Duplicate filing of the same grievance",
            ),
            make_applicant_headers(world["applicant"]["id"]),
        )

        validate_error(duplicate, ApiErrorId.ERR_APPEAL_PENDING, 409)
        _, meta = validate_paginated(
            api_client.list_appeals(
                BOARD, params={"application_id": world["application"]["id"]}
            )
        )
        assert meta["total_count"] == 1

        skipped = api_client.advance_appeal(appeal["id"], "HEARD", BOARD)

        validate_error(skipped, ApiErrorId.ERR_APPEAL_NOT_IN_REQUIRED_STATUS, 409)
        stalled = refresh_appeal(appeal["id"], BOARD)
        assert stalled["status"] == "FILED"
        assert stalled["litigation_hold_active"] is False
        assert stalled["disposition"] is None

        briefed = advance_appeal(appeal, "BRIEFING")
        assert briefed["status"] == "BRIEFING"

    def test_the_appeal_window_is_inclusive_to_the_closing_instant(self):
        """One day late is expired; exactly at the closing instant is on time.

        PRD §3.9: "The filing must arrive while the logical clock is at or before the
        application's `appeal_window_closes_at`, otherwise
        `ERR_APPEAL_WINDOW_EXPIRED`; no other appeal on the same application may be
        in `FILED`, `BRIEFING`, `STAYED` or `HEARD`, otherwise `ERR_APPEAL_PENDING`;
        and a `BARRED` applicant may not file."
        PRD §3.4: "and `appeal_window_closes_at`, which is `decision_at` plus 30 days
        and is simultaneously the last instant an appeal may be filed and the earliest
        boundary past which a certificate may issue."

        Design: Corner/errors/appeal_filed_after_the_window_closed_returns_appeal_window_expired
        """
        world = seed_decided_cycle()
        application = refresh_application(world["application"]["id"])
        assert_instant_equals(
            application["appeal_window_closes_at"], APPEAL_WINDOW_CLOSES
        )
        payload = appeal_payload(
            application["id"],
            world["applicant"]["id"],
            grounds="Late challenge to the comparative ranking",
        )
        headers = make_applicant_headers(world["applicant"]["id"])
        set_clock(ISSUANCE_CLOCK)

        response = api_client.create_appeal(payload, headers)

        validate_error(response, ApiErrorId.ERR_APPEAL_WINDOW_EXPIRED, 409)
        _, meta = validate_paginated(
            api_client.list_appeals(BOARD, params={"application_id": application["id"]})
        )
        assert meta["total_count"] == 0
        assert refresh_application(application["id"])["status"] == "APPROVED"

        set_clock(APPEAL_WINDOW_CLOSES)
        on_time = get_success_data(api_client.create_appeal(payload, headers), 201)
        assert on_time["status"] == "FILED"
        assert_instant_equals(on_time["filed_at"], APPEAL_WINDOW_CLOSES)


class TestCertificateActivityGuards:
    def test_a_lapsed_certificate_cannot_be_extended_back_to_life(self):
        """LAPSED is outside the active set, so the extension is refused outright.

        PRD §3.8: "Extension also requires an active certificate and no live
        litigation hold on the underlying application."
        PRD §2.8: "A certificate's `lifecycle_status` must be `ISSUED`,
        `IMPLEMENTED` or `SUSPENDED` for extension, modification and progress
        reporting (`ERR_CERTIFICATE_NOT_ACTIVE`); an appeal must be in the status the
        requested action demands (`ERR_APPEAL_NOT_IN_REQUIRED_STATUS`); issuance
        requires the application `APPROVED` or `APPROVED_WITH_CONDITIONS`
        (`ERR_APPLICATION_NOT_APPROVED`). All at 409."
        PRD §3.8: "Each lapse sets `lifecycle_status` to `LAPSED` and increases the
        certificate's `version` by 1, then unwinds every commitment the issuance
        made: the planning area's `approved_unimplemented_beds` is decreased by the
        certificate's `authorized_bed_count`, its
        `capital_authorization_committed_cents` is decreased by the certificate's
        `approved_expenditure_limit_cents`, the cycle's `unallocated_bed_need` is
        increased by the `authorized_bed_count` while the underlying application's
        `allocated_bed_count` is set to 0, and the applicant's
        `compliance_strike_count` increases by 1 with the standing consequences
        already described."

        Design: Corner/errors/extending_a_certificate_the_lapse_sweep_already_closed_returns_certificate_not_active
        """
        world = seed_issued_certificate()
        certificate = world["certificate"]
        file_progress_report(certificate, world["applicant"])
        set_clock(PAST_MILESTONE_CLOCK)
        summary = get_success_data(api_client.run_lapse_sweep(ADMIN))
        assert summary["lapsed_count"] == 1

        response = api_client.extend_certificate(
            certificate["id"],
            {
                "requested_days": 120,
                "justification": "Construction delayed by a utility easement dispute",
            },
            OFFICER,
        )

        validate_error(response, ApiErrorId.ERR_CERTIFICATE_NOT_ACTIVE, 409)
        lapsed = refresh_certificate(certificate["id"])
        assert lapsed["lifecycle_status"] == "LAPSED"
        assert lapsed["extension_days_granted_total"] == 0
        assert lapsed["implementation_milestone_date"] == "2027-06-30"
        hsa = refresh_health_service_area(world["hsa"]["id"])
        assert hsa["approved_unimplemented_beds"] == 0
        assert hsa["capital_authorization_committed_cents"] == 0

    def test_the_two_fiscal_modification_guards_each_answer_with_their_own_code(self):
        """A limit below what is spent and a bed rise beyond the pool are distinct faults.

        PRD §3.8: "a supplied `new_approved_expenditure_limit_cents` must be at least
        the governing cumulative expenditure already recognised on the lineage,
        otherwise `ERR_MODIFICATION_BELOW_COMMITTED` — and a `new_authorized_bed_count`
        set below the beds already released to the planning area is refused under the
        same code; and a supplied `new_authorized_bed_count` may exceed the current
        `authorized_bed_count` by no more than the cycle's `unallocated_bed_need`,
        otherwise `ERR_NEED_EXHAUSTED`."
        PRD §3.8: "The **governing** figure is `cumulative_expenditure_accrual_cents`
        when the certificate's `expenditure_basis` is `ACCRUAL` and
        `cumulative_expenditure_cash_cents` when it is `CASH`."
        PRD §3.8: "On the bed side, the signed bed delta — the new
        `authorized_bed_count` minus the old — is added to the area's
        `approved_unimplemented_beds` and subtracted from the cycle's
        `unallocated_bed_need`, which keeps the pool invariant of §2.10 intact in both
        directions."

        Design: Corner/errors/modification_guards_reject_a_below_committed_limit_and_a_bed_increase_beyond_the_pool
        """
        world = seed_issued_certificate()
        file_progress_report(
            world["certificate"],
            world["applicant"],
            disbursed_cents=400000000,
            obligated_cents=0,
        )
        certificate = refresh_certificate(world["certificate"]["id"])
        assert certificate["authorized_bed_count"] == 12
        assert certificate["cumulative_expenditure_cash_cents"] == 400000000
        assert refresh_cycle(world["cycle"]["id"])["unallocated_bed_need"] == 7

        below_committed = api_client.modify_certificate(
            certificate["id"],
            {
                "expected_certificate_version": certificate["version"],
                "new_approved_expenditure_limit_cents": 300000000,
            },
            OFFICER,
        )
        beyond_pool = api_client.modify_certificate(
            certificate["id"],
            {
                "expected_certificate_version": certificate["version"],
                "new_authorized_bed_count": 20,
            },
            OFFICER,
        )

        validate_error(
            below_committed, ApiErrorId.ERR_MODIFICATION_BELOW_COMMITTED, 422
        )
        validate_error(beyond_pool, ApiErrorId.ERR_NEED_EXHAUSTED, 409)
        unchanged = refresh_certificate(certificate["id"])
        assert unchanged["lifecycle_status"] == "ISSUED"
        assert unchanged["version"] == certificate["version"]
        _, meta = validate_paginated(
            api_client.list_certificates(
                ADMIN, params={"application_id": world["application"]["id"]}
            )
        )
        assert meta["total_count"] == 1
        assert refresh_cycle(world["cycle"]["id"])["unallocated_bed_need"] == 7
        assert (
            refresh_health_service_area(world["hsa"]["id"])[
                "capital_authorization_committed_cents"
            ]
            == 1000000000
        )

        successor = get_success_data(
            api_client.modify_certificate(
                certificate["id"],
                {
                    "expected_certificate_version": certificate["version"],
                    "new_authorized_bed_count": 19,
                },
                OFFICER,
            ),
            201,
        )
        assert successor["authorized_bed_count"] == 19
        assert successor["superseded_certificate_id"] == certificate["id"]

    def test_a_consumed_lineage_allowance_refuses_even_a_ten_day_request(self):
        """The cap is tested before the minimum, so 0 remaining days is an error.

        PRD §3.8: "The lineage's remaining allowance is 540 days minus the
        certificate's `extension_days_granted_total`, which is carried forward across
        every reissue so the cap binds the whole lineage rather than each row; when
        that remaining allowance is 0 or less the request is refused with
        `ERR_EXTENSION_CAP_EXHAUSTED`."
        PRD §3.8: "Otherwise the granted days are the smallest of three quantities:
        the `requested_days` asked for, the per-grant ceiling of 365 days, and the
        remaining lineage allowance."
        PRD §2.8: "**Extension capacity.** The certificate lineage must have a
        remaining cumulative extension allowance greater than zero — otherwise
        `ERR_EXTENSION_CAP_EXHAUSTED` (422). This rule guards certificate extension."

        Design: Corner/errors/extension_requested_after_the_lineage_cap_is_consumed_returns_extension_cap_exhausted
        """
        world = seed_issued_certificate()
        certificate = world["certificate"]
        first = get_success_data(
            api_client.extend_certificate(
                certificate["id"],
                {"requested_days": 365, "justification": "Site preparation delays"},
                OFFICER,
            )
        )
        assert first["extension_days_granted_total"] == 365
        assert first["implementation_milestone_date"] == "2028-06-29"
        second = get_success_data(
            api_client.extend_certificate(
                certificate["id"],
                {"requested_days": 200, "justification": "Commissioning slip"},
                OFFICER,
            )
        )
        assert second["extension_days_granted_total"] == 540
        assert second["implementation_milestone_date"] == "2028-12-21"

        response = api_client.extend_certificate(
            certificate["id"],
            {
                "requested_days": 10,
                "justification": "Final occupancy inspection slipped by ten days",
            },
            OFFICER,
        )

        validate_error(response, ApiErrorId.ERR_EXTENSION_CAP_EXHAUSTED, 422)
        stored = refresh_certificate(certificate["id"])
        assert stored["extension_days_granted_total"] == 540
        assert stored["implementation_milestone_date"] == "2028-12-21"
        assert stored["lifecycle_status"] == "ISSUED"
        assert stored["version"] == certificate["version"] + 2
