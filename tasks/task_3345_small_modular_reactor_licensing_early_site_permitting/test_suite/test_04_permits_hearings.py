"""Site permits and public hearings: contention regression and recovery, the
strict future-only scheduling window, mark-held timing, the empty-hearing-set
grant boundary, the COL certification gate, and the default logical clock."""

from test_helpers import (
    ApiErrorId,
    DOE,
    INTERVENOR,
    PERMIT_APPLICANT,
    REVIEWER,
    create_dca,
    create_hearing,
    create_permit_in_hearings,
    create_site_permit,
    hearing_payload,
    read_hearing,
    read_site_permit,
    set_clock,
    validate_error,
    validate_success,
)


class TestHearingContentionRegression:
    """Contention regresses a HEARINGS permit back to environmental review."""

    def test_contend_regresses_permit_to_environmental_review(self, api):
        """PRD §3.6: "Before that instant, a `PublicIntervenor` may contend the
        hearing — `SCHEDULED → CONTENDED` — and contention cascades: the
        parent permit, if in `HEARINGS`, regresses to `ENVIRONMENTAL_REVIEW`
        with its `version` incremented, forcing the owner to re-run
        environmental review before hearings resume."

        Design: Difficulty/non_linear_state_machine/hearing_contention_regresses_permit_then_recovers
        """
        set_clock(api, "2026-09-01T00:00:00Z")
        world = create_permit_in_hearings(
            api, hearing_at="2026-10-01T00:00:00Z", docket_number="52-301"
        )
        permit, hearing = world["permit"], world["hearing"]
        assert permit["status"] == "HEARINGS"

        contended = validate_success(api.contend_hearing(hearing["id"], INTERVENOR))
        assert contended["status"] == "CONTENDED"
        assert read_site_permit(api, permit["id"])["status"] == "ENVIRONMENTAL_REVIEW"

    def test_permit_recovers_after_contention_rescheduled(self, api):
        """PRD §3.6: "A `CONTENDED` hearing is not dead: the applicant
        reschedules it back to `SCHEDULED` with a new strictly-future instant,
        clearing the contention."
        PRD §3.6: "From environmental review the applicant advances to
        `HEARINGS` — only while no hearing of the permit is currently
        `SCHEDULED`."

        Design: Difficulty/non_linear_state_machine/hearing_contention_regresses_permit_then_recovers
        """
        set_clock(api, "2026-09-01T00:00:00Z")
        world = create_permit_in_hearings(
            api, hearing_at="2026-10-01T00:00:00Z", docket_number="52-302"
        )
        permit, hearing = world["permit"], world["hearing"]
        validate_success(api.contend_hearing(hearing["id"], INTERVENOR))
        assert read_site_permit(api, permit["id"])["status"] == "ENVIRONMENTAL_REVIEW"

        # The contended hearing is not SCHEDULED, so the advance gate is
        # clear: the permit re-runs environmental review and returns to
        # HEARINGS. Rescheduling the hearing to a new strictly-future instant
        # then clears the contention.
        re_advanced = validate_success(api.advance_to_hearings(permit["id"], PERMIT_APPLICANT))
        assert re_advanced["status"] == "HEARINGS"
        rescheduled = validate_success(
            api.reschedule_hearing(
                hearing["id"], hearing_payload(scheduled_at="2026-11-01T00:00:00Z"), PERMIT_APPLICANT
            )
        )
        assert rescheduled["status"] == "SCHEDULED"


class TestHearingFutureOnlyScheduling:
    """A hearing instant equal to the clock is not strictly in the future."""

    def test_scheduling_at_now_rejected_one_second_later_accepted(self, api):
        """PRD §3.6: "Scheduling is future-only: the instant must be strictly
        after the current logical clock, both at initial scheduling and when
        rescheduling a contended hearing; a past or present instant is
        rejected with `ERR_HEARING_IN_PAST` (HTTP 422)."

        Design: Difficulty/resource_temporal_overlap/hearing_scheduling_requires_future_instant
        """
        set_clock(api, "2026-09-01T00:00:00Z")
        world = create_permit_in_hearings(api, docket_number="52-702")
        permit = world["permit"]
        # Equal to the current clock is a "present" instant: rejected.
        rejected = api.schedule_hearing(
            permit["id"],
            hearing_payload(scheduled_at="2026-09-01T00:00:00Z", location="Library"),
            PERMIT_APPLICANT,
        )
        validate_error(rejected, ApiErrorId.ERR_HEARING_IN_PAST, 422)
        # One second later is strictly future: accepted.
        hearing = validate_success(
            api.schedule_hearing(
                permit["id"],
                hearing_payload(scheduled_at="2026-09-01T00:00:01Z", location="Library"),
                PERMIT_APPLICANT,
            ),
            201,
        )
        assert hearing["status"] == "SCHEDULED"

    def test_past_instant_rejected(self, api):
        """PRD §3.6: "Scheduling is future-only: the instant must be strictly
        after the current logical clock, both at initial scheduling and when
        rescheduling a contended hearing; a past or present instant is
        rejected with `ERR_HEARING_IN_PAST` (HTTP 422)."

        Design: Difficulty/resource_temporal_overlap/hearing_scheduling_requires_future_instant
        """
        set_clock(api, "2026-09-01T00:00:00Z")
        world = create_permit_in_hearings(api, docket_number="52-705")
        resp = api.schedule_hearing(
            world["permit"]["id"],
            hearing_payload(scheduled_at="2026-08-31T23:59:59Z", location="Gym"),
            PERMIT_APPLICANT,
        )
        validate_error(resp, ApiErrorId.ERR_HEARING_IN_PAST, 422)


class TestHearingWindow:
    """Marking held requires the clock at or after the scheduled instant."""

    def test_mark_held_before_schedule_rejected_then_succeeds_at_instant(self, api):
        """PRD §3.6: "The window checks are symmetric and strict: marking held
        requires the clock to be at or after `scheduled_at`, while contending
        or cancelling requires the clock to be strictly before it; acting on
        the wrong side of the instant is rejected with `ERR_HEARING_WINDOW`
        (HTTP 422)."

        Design: Corner/validations/hearing_window_mark_held_before_schedule_rejected
        """
        set_clock(api, "2026-09-15T00:00:00Z")
        world = create_permit_in_hearings(
            api, hearing_at="2026-10-01T00:00:00Z", docket_number="52-943"
        )
        hearing = world["hearing"]
        # Clock is before scheduled_at: mark-held is on the wrong side.
        early = api.mark_hearing_held(hearing["id"], PERMIT_APPLICANT)
        validate_error(early, ApiErrorId.ERR_HEARING_WINDOW, 422)
        # At the scheduled instant, mark-held succeeds.
        set_clock(api, "2026-10-01T00:00:00Z")
        held = validate_success(api.mark_hearing_held(hearing["id"], PERMIT_APPLICANT))
        assert held["status"] == "HELD"

    def test_contend_at_or_after_schedule_rejected(self, api):
        """PRD §3.6: "The window checks are symmetric and strict: marking held
        requires the clock to be at or after `scheduled_at`, while contending
        or cancelling requires the clock to be strictly before it; acting on
        the wrong side of the instant is rejected with `ERR_HEARING_WINDOW`
        (HTTP 422)."

        Design: Corner/validations/hearing_window_mark_held_before_schedule_rejected
        """
        set_clock(api, "2026-09-15T00:00:00Z")
        world = create_permit_in_hearings(
            api, hearing_at="2026-10-01T00:00:00Z", docket_number="52-945"
        )
        hearing = world["hearing"]
        set_clock(api, "2026-10-01T00:00:00Z")
        late = api.contend_hearing(hearing["id"], INTERVENOR)
        validate_error(late, ApiErrorId.ERR_HEARING_WINDOW, 422)


class TestGrantRequiresHearings:
    """Grant is blocked when the permit has no hearings at all."""

    def test_grant_with_zero_hearings_rejected(self, api):
        """PRD §3.6: "Granting moves `HEARINGS → GRANTED` and requires that at
        least one public hearing exists and every hearing of the permit is
        `HELD`."

        Design: Difficulty/boundary_precision_check/zero_hearings_grant_blocked_empty_set
        """
        world = create_permit_in_hearings(api, docket_number="52-601")
        resp = api.grant_site_permit(world["permit"]["id"], PERMIT_APPLICANT)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

    def test_grant_succeeds_once_hearing_held(self, api):
        """PRD §3.6: "Granting moves `HEARINGS → GRANTED` and requires that at
        least one public hearing exists and every hearing of the permit is
        `HELD`."

        Design: Difficulty/boundary_precision_check/zero_hearings_grant_blocked_empty_set
        """
        set_clock(api, "2026-09-01T00:00:00Z")
        world = create_permit_in_hearings(
            api, hearing_at="2026-10-01T00:00:00Z", docket_number="52-602"
        )
        permit, hearing = world["permit"], world["hearing"]
        set_clock(api, "2026-10-01T00:00:00Z")
        validate_success(api.mark_hearing_held(hearing["id"], PERMIT_APPLICANT))
        granted = validate_success(api.grant_site_permit(permit["id"], PERMIT_APPLICANT))
        assert granted["status"] == "GRANTED"


class TestColGate:
    """A Combined License requires the referenced application CERTIFIED."""

    def test_col_against_uncertified_dca_rejected(self, api):
        """PRD §3.6: "A Combined License additionally requires the referenced
        application to be `CERTIFIED`; filing a COL against an application
        still in review is rejected with `ERR_DCA_NOT_CERTIFIED` (HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/col_creation_depends_on_dca_certified
        """
        dca = create_dca(api, docket_number="52-701")
        resp = api.create_site_permit(
            {"permit_type": "COL", "dca_id": dca["id"], "site_name": "Early Site"},
            PERMIT_APPLICANT,
        )
        validate_error(resp, ApiErrorId.ERR_DCA_NOT_CERTIFIED, 422)

    def test_esp_against_same_uncertified_dca_accepted(self, api):
        """PRD §3.6: "A `SitePermitApplicant` creates a permit with a
        `permit_type` of `ESP` or `COL`, the referenced `dca_id`, and a
        `site_name`."
        PRD §3.6: "A Combined License additionally requires the referenced
        application to be `CERTIFIED`; filing a COL against an application
        still in review is rejected with `ERR_DCA_NOT_CERTIFIED` (HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/col_creation_depends_on_dca_certified
        """
        dca = create_dca(api, docket_number="52-706")
        # Only the COL flavor carries the CERTIFIED precondition; an ESP on
        # the same in-review application is accepted.
        esp = validate_success(
            api.create_site_permit(
                {"permit_type": "ESP", "dca_id": dca["id"], "site_name": "Early ESP"},
                PERMIT_APPLICANT,
            ),
            201,
        )
        assert esp["status"] == "DRAFT"


class TestDefaultClock:
    """The logical clock defaults to 2026-09-01 before any set call."""

    def test_august_hearing_rejected_without_any_clock_set(self, api):
        """PRD §2.5: "Before any administrative set call, the server's logical
        clock defaults to 2026-09-01T00:00:00Z and must never fall back to
        wall-clock time."

        Design: Corner/endpoints/clock_default_is_2026_09_01
        """
        # No clock-set call is made; an August instant must already be past.
        world = create_permit_in_hearings(api, docket_number="52-950")
        resp = api.schedule_hearing(
            world["permit"]["id"],
            hearing_payload(scheduled_at="2026-08-01T00:00:00Z", location="Hall"),
            PERMIT_APPLICANT,
        )
        validate_error(resp, ApiErrorId.ERR_HEARING_IN_PAST, 422)

    def test_september_hearing_accepted_without_any_clock_set(self, api):
        """PRD §2.5: "Before any administrative set call, the server's logical
        clock defaults to 2026-09-01T00:00:00Z and must never fall back to
        wall-clock time."
        PRD §3.6: "Scheduling is future-only: the instant must be strictly
        after the current logical clock, both at initial scheduling and when
        rescheduling a contended hearing; a past or present instant is
        rejected with `ERR_HEARING_IN_PAST` (HTTP 422)."

        Design: Corner/endpoints/clock_default_is_2026_09_01
        """
        world = create_permit_in_hearings(api, docket_number="52-951")
        # Strictly after the default clock instant: accepted with no set call.
        hearing = validate_success(
            api.schedule_hearing(
                world["permit"]["id"],
                hearing_payload(scheduled_at="2026-09-02T00:00:00Z", location="Hall"),
                PERMIT_APPLICANT,
            ),
            201,
        )
        assert hearing["status"] == "SCHEDULED"
