"""Vendor engagement lifecycle and capacity-window coverage rules."""
from test_helpers import (
    TEST_USERS,
    api_client,
    approve_disbursement,
    complete_engagement,
    create_disbursement,
    create_eligible_case,
    add_approved_project,
    add_project,
    propose_project,
    create_engagement,
    get_capacity_window_reserved,
    get_engagement,
    get_project,
    make_agent,
    make_capacity_window,
    make_listing_agent_headers,
    make_vendor,
    make_vendor_headers,
    make_vendor_with_window,
    release_disbursement,
    reset_clock,
    setup_case_with_approved_project,
    setup_engagement_in_work,
    setup_engagement_scheduled,
    start_engagement,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)
from test_helpers import ApiErrorId as ERR


class TestEngagementCreateRequiresApprovedProject:
    """The engagement's project gate fires at creation time: only an APPROVED
    project may be engaged against."""

    def test_engagement_create_on_draft_project_returns_project_not_approved(self, api):
        """PRD §3.4: "Creation requires the referenced project to be in `APPROVED`
        status; engaging against a project in any other state is rejected with
        `ERR_PROJECT_NOT_APPROVED`."

        Design: Difficulty/cross_entity_state_dependency/engagement_start_requires_project_approved
        """
        reset_clock()
        agent = make_agent()
        vendor, _window = make_vendor_with_window()
        case = create_eligible_case(agent)
        project = add_project(case["id"], agent)  # stays DRAFT
        resp = api_client.create_engagement(
            {
                "improvement_project_id": project["id"],
                "vendor_id": vendor["id"],
                "agreed_price_cents": 5_000_000,
                "start_date": "2026-09-05T00:00:00Z",
                "end_date": "2026-09-20T00:00:00Z",
            },
            make_listing_agent_headers(agent["id"]),
        )
        validate_error(resp, ERR.ERR_PROJECT_NOT_APPROVED)

    def test_engagement_create_on_proposed_project_returns_project_not_approved(self, api):
        """PRD §3.4: "Creation requires the referenced project to be in `APPROVED`
        status; engaging against a project in any other state is rejected with
        `ERR_PROJECT_NOT_APPROVED`."

        Design: Difficulty/cross_entity_state_dependency/engagement_start_requires_project_approved
        """
        reset_clock()
        agent = make_agent()
        vendor, _window = make_vendor_with_window()
        case = create_eligible_case(agent)
        project = add_project(case["id"], agent)
        propose_project(case["id"], project["id"], agent)  # PROPOSED, not APPROVED
        resp = api_client.create_engagement(
            {
                "improvement_project_id": project["id"],
                "vendor_id": vendor["id"],
                "agreed_price_cents": 5_000_000,
                "start_date": "2026-09-05T00:00:00Z",
                "end_date": "2026-09-20T00:00:00Z",
            },
            make_listing_agent_headers(agent["id"]),
        )
        validate_error(resp, ERR.ERR_PROJECT_NOT_APPROVED)


class TestVendorCapacityWindowHalfOpenOverlap:
    """Capacity windows are half-open [window_start, window_end); a start needs
    one OPEN window covering the whole engagement."""

    def _setup_two_adjacent_windows(self):
        ctx = setup_case_with_approved_project(with_vendor=False)
        vendor = make_vendor()
        make_capacity_window(
            vendor["id"], window_start="2026-09-01T00:00:00Z",
            window_end="2026-09-15T00:00:00Z", capacity_crew_days=10,
        )
        make_capacity_window(
            vendor["id"], window_start="2026-09-15T00:00:00Z",
            window_end="2026-09-30T00:00:00Z", capacity_crew_days=10,
        )
        ctx["vendor"] = vendor
        return ctx

    def test_engagement_inside_a_single_window_starts(self, api):
        """PRD §3.4: "The vendor starts the work, transitioning the engagement
        from `SCHEDULED` to `IN_WORK`."
        PRD §3.4: "the window covers the half-open interval from `window_start`
        inclusive to `window_end` exclusive"

        Design: Difficulty/resource_temporal_overlap/vendor_capacity_window_half_open_overlap
        """
        ctx = self._setup_two_adjacent_windows()
        # [2026-09-05, 2026-09-12) lies entirely inside the first window.
        engagement = create_engagement(
            ctx["project"]["id"], ctx["vendor"]["id"], ctx["agent"],
            start_date="2026-09-05T00:00:00Z", end_date="2026-09-12T00:00:00Z",
        )
        resp = api_client.start_engagement(
            engagement["id"], make_vendor_headers(ctx["vendor"]["id"])
        )
        started = validate_success(resp)
        assert started["status"] == "IN_WORK"


class TestEngagementCancelAndCrewDayConservation:
    def test_cancel_scheduled_engagement_releases_and_keeps_reserved_at_zero(self, api):
        """PRD §3.4: "A homeowner may cancel an engagement while it is
        `SCHEDULED`, moving it to `CANCELLED`"
        PRD §3.4: "Cancelling an engagement releases the reserved crew-days on
        the matching capacity window."
        PRD §3.1: "A new window starts with `reserved_crew_days` at 0"
        PRD §3.4: "On a successful start, the engagement's `required_crew_days`
        are added to the matching window's `reserved_crew_days`."

        Design: Difficulty/compensating_invariant/reserved_crew_days_conserved_on_engagement_cancel
        """
        ctx = setup_engagement_scheduled(
            window_overrides={
                "window_start": "2026-09-01T00:00:00Z",
                "window_end": "2026-09-30T00:00:00Z",
                "capacity_crew_days": 10,
            }
        )
        # Nothing reserved yet: the add happens only on a successful start.
        assert get_capacity_window_reserved(ctx["vendor"]["id"], ctx["window"]["id"]) == 0
        resp = api_client.cancel_engagement(
            ctx["engagement"]["id"], TEST_USERS["homeowner_headers"]
        )
        cancelled = validate_success(resp)
        assert cancelled["status"] == "CANCELLED"
        assert get_capacity_window_reserved(ctx["vendor"]["id"], ctx["window"]["id"]) == 0

    def test_cancel_in_work_engagement_returns_invalid_state(self, api):
        """PRD §3.4: "An engagement in `IN_WORK` cannot be cancelled through this
        path; instead, a dispute referencing it moves it to `DISPUTED`, as
        described in §3.6."
        PRD §2.8: "State appropriateness comes fourth: a resource in the wrong
        state for the requested operation yields `ERR_INVALID_STATE` (HTTP 409)."

        Design: Difficulty/compensating_invariant/reserved_crew_days_conserved_on_engagement_cancel
        """
        ctx = setup_engagement_in_work()
        resp = api_client.cancel_engagement(
            ctx["engagement"]["id"], TEST_USERS["homeowner_headers"]
        )
        validate_error(resp, ERR.ERR_INVALID_STATE)


class TestProjectCompletionBubbleUp:
    def test_project_completes_when_all_engagements_complete(self, api):
        """PRD §3.4: "When every non-`CANCELLED` engagement of a project has
        reached `COMPLETE_ON_TIME` or `COMPLETE_LATE`, the project advances
        automatically from `IN_WORK` to `COMPLETE`."
        PRD §3.4: "If the current clock reading is at or before the
        `completion_deadline`, the engagement moves from `IN_WORK` to
        `COMPLETE_ON_TIME`"

        Design: Corner/state_machines/bubble_up_project_complete_when_all_engagements_complete
        """
        ctx = setup_engagement_in_work()
        complete_engagement(ctx["engagement"]["id"], ctx["vendor"])
        engagement = get_engagement(ctx["engagement"]["id"])
        project = get_project(ctx["case"]["id"], ctx["project"]["id"])
        assert engagement["status"] == "COMPLETE_ON_TIME"
        assert project["status"] == "COMPLETE"


class TestEngagementCancelWithReleasedDisbursement:
    def test_cancel_engagement_with_released_disbursement_rejected(self, api):
        """PRD §3.4: "cancelling an engagement with released funds is rejected
        with `ERR_ENGAGEMENT_HAS_RELEASED_DISBURSEMENT` (HTTP 409)"

        Design: Corner/errors/err_engagement_has_released_disbursement_on_cancel
        """
        ctx = setup_engagement_scheduled(plan_approved=True)
        disb = create_disbursement(
            ctx["case"]["id"], ctx["project"]["id"], ctx["engagement"]["id"]
        )
        approve_disbursement(disb["id"], ctx["case"]["id"])
        start_engagement(ctx["engagement"]["id"], ctx["vendor"])
        release_disbursement(disb["id"])
        resp = api_client.cancel_engagement(
            ctx["engagement"]["id"], TEST_USERS["homeowner_headers"]
        )
        # PRD §3.4 names ERR_ENGAGEMENT_HAS_RELEASED_DISBURSEMENT for cancelling
        # an engagement with released funds, but also states an IN_WORK
        # engagement "cannot be cancelled through this path" (ERR_INVALID_STATE,
        # and §2.8 ranks state-appropriateness fourth without ordering the
        # released-funds check). A released disbursement implies the engagement
        # left SCHEDULED, so both outcomes are PRD-consistent serializations.
        validate_error_is_one_of(
            resp,
            [ERR.ERR_ENGAGEMENT_HAS_RELEASED_DISBURSEMENT, ERR.ERR_INVALID_STATE],
        )
