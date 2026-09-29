"""
Two occupied intervals and their edges: a member's employment interval, which is
half-open so that a new job may start the instant the old one ended, and a
registration's referral occupation, which is closed at both ends.
"""

from test_helpers import (
    DISPATCHER,
    DISPATCH_LAID_OFF,
    DISPATCH_WORKING,
    ERR_ACCEPTANCE_WINDOW_CLOSED,
    ERR_OVERLAPPING_DISPATCH,
    ERR_REFERRAL_ALREADY_OUTSTANDING,
    ERR_REGISTRATION_NOT_ACTIVE,
    LAYOFF_LACK_OF_WORK,
    REFERRAL_EXPIRED,
    REFERRAL_ISSUED,
    REFERRAL_WITHDRAWN,
    REGISTRATION_REGISTERED,
    SLOT_JOURNEYWORKER,
    assert_instant_equals,
    expect_created,
    expect_error,
    factories as f,
    fixtures as fx,
    make_member_headers,
    plus_millis,
)

# ─── The half-open employment interval ────────────────────────────────────────

BOOKS_AT = "2026-09-01T00:00:00.000Z"
FIRST_REPORT_AT = "2026-09-10T14:00:00.000Z"
LAYOFF_AT = "2026-09-20T14:00:00.000Z"
OVERLAPPING_REPORT_AT = "2026-09-15T14:00:00.000Z"
ADJACENT_REPORT_AT = "2026-09-20T14:00:00.000Z"
EMPLOYMENT_RATE_CENTS = 5200
EMPLOYMENT_DURATION_DAYS = 30
LAYOFF_HOURS = 80
WITHDRAWAL_REASON = "Reported time falls inside a prior employment"

# ─── The closed referral occupation ───────────────────────────────────────────

OCCUPATION_CLOCK = "2026-09-02T00:00:00.000Z"
OCCUPATION_DEADLINE = "2026-09-03T00:00:00.000Z"
ONE_MILLISECOND_LATE = "2026-09-03T00:00:00.001Z"
SECOND_DEADLINE = "2026-09-04T00:00:00.001Z"
OCCUPATION_CALLS = (
    ("Request A", "2026-09-25T07:00:00.000Z"),
    ("Request B", "2026-09-26T07:00:00.000Z"),
    ("Request C", "2026-09-27T07:00:00.000Z"),
)
OCCUPATION_RATE_CENTS = 5200
OCCUPATION_DURATION_DAYS = 30


def _member_laid_off_and_back_on_the_book(api):
    """
    One journeyworker who works a call, is laid off for lack of work, and signs
    the book again, so the hall holds one closed employment interval for them.
    """
    hall = fx.standard_hall(api, clock=BOOKS_AT)
    finn = fx.add_journeyworker(api, hall["home_local_id"], "Finn Ortiz", 9000)
    first_registration = fx.sign_book(api, finn["id"], hall["group_1_id"])
    contractor = fx.add_contractor(api, name="Summit Industrial")
    first_call = _call(api, contractor["id"], "Line 3 Rebuild", FIRST_REPORT_AT)
    first_referral = fx.issue_referral(
        api, first_call["id"], slot_kind=SLOT_JOURNEYWORKER
    )
    first_dispatch = fx.accept_referral(api, first_referral["id"], finn["id"])

    fx.set_clock(api, LAYOFF_AT)
    laid_off = fx.lay_off(
        api, first_dispatch["id"], contractor["id"], LAYOFF_HOURS, LAYOFF_LACK_OF_WORK
    )
    second_registration = fx.sign_book(
        api,
        finn["id"],
        hall["group_1_id"],
        headers=make_member_headers(finn["id"]),
    )
    return {
        "hall": hall,
        "finn": finn,
        "first_registration": first_registration,
        "second_registration": second_registration,
        "contractor": contractor,
        "first_dispatch": first_dispatch,
        "laid_off": laid_off,
    }


def _call(api, contractor_id, job_site, report_at, **overrides):
    return fx.open_job_request(
        api,
        contractor_id,
        job_site=job_site,
        journeyworkers_requested=1,
        apprentices_requested=0,
        expected_duration_days=EMPLOYMENT_DURATION_DAYS,
        report_at=report_at,
        hourly_rate_cents=EMPLOYMENT_RATE_CENTS,
        **overrides,
    )


def _sole_registrant_named_on_two_calls(api):
    """
    One registrant holding one live referral, plus two further calls that both
    name that member, so a second referral can be attempted on demand.
    """
    hall = fx.standard_hall(api, clock=OCCUPATION_CLOCK)
    gia = fx.add_journeyworker(api, hall["home_local_id"], "Gia Roux", 9000)
    registration = fx.sign_book(api, gia["id"], hall["group_1_id"])
    contractor = fx.add_contractor(api, name="Redstone Mechanical")
    calls = {}
    for job_site, report_at in OCCUPATION_CALLS:
        calls[job_site] = fx.open_job_request(
            api,
            contractor["id"],
            job_site=job_site,
            journeyworkers_requested=1,
            apprentices_requested=0,
            expected_duration_days=OCCUPATION_DURATION_DAYS,
            report_at=report_at,
            hourly_rate_cents=OCCUPATION_RATE_CENTS,
            named_call_member_ids=[] if job_site == "Request A" else [gia["id"]],
        )
    first_referral = fx.issue_referral(
        api, calls["Request A"]["id"], slot_kind=SLOT_JOURNEYWORKER
    )
    return {
        "hall": hall,
        "gia": gia,
        "registration": registration,
        "calls": calls,
        "first_referral": first_referral,
    }


def _named_call(api, job_request_id, member_id):
    version = fx.job_request_version(api, job_request_id)
    return api.create_referral(
        job_request_id,
        f.named_call_referral_payload(version, member_id, slot_kind=SLOT_JOURNEYWORKER),
        DISPATCHER,
    )


class TestEmploymentIntervalIsHalfOpen:
    """A reporting instant inside a past job collides; one on its edge does not."""

    def test_the_layoff_closes_the_interval_at_the_current_instant(self, api):
        """
        PRD §3.7: "**Accepting** moves the referral from `ISSUED` to `ACCEPTED` and
        the registration from `REFERRED` to the terminal `DISPATCHED_OUT`, and it
        creates the employment record: a `Dispatch` in `WORKING` status whose
        `start_at` is the job request's `report_at`, whose `hours_worked` begins at
        0, and whose `ended_at`, `layoff_reason`, `recall_of_dispatch_id`, and
        `recall_window_ends_at` all begin null."

        Design: Difficulty/resource_temporal_overlap/member_employment_interval_half_open_allows_adjacency
        """
        scene = _member_laid_off_and_back_on_the_book(api)

        assert_instant_equals(scene["first_dispatch"]["start_at"], FIRST_REPORT_AT)
        assert scene["laid_off"]["status"] == DISPATCH_LAID_OFF
        assert_instant_equals(scene["laid_off"]["ended_at"], LAYOFF_AT)
        assert scene["second_registration"]["position_number"] == 1

    def test_a_reporting_instant_inside_the_closed_interval_is_refused(self, api):
        """
        PRD §3.7: "A collision is refused with `ERR_OVERLAPPING_DISPATCH`; a
        reporting instant exactly equal to an earlier dispatch's `ended_at` is
        adjacency and is allowed."

        Design: Difficulty/resource_temporal_overlap/member_employment_interval_half_open_allows_adjacency
        """
        scene = _member_laid_off_and_back_on_the_book(api)
        overlapping_call = _call(
            api, scene["contractor"]["id"], "Line 4 Overlap", OVERLAPPING_REPORT_AT
        )

        referral = fx.issue_referral(
            api, overlapping_call["id"], slot_kind=SLOT_JOURNEYWORKER
        )
        assert referral["status"] == REFERRAL_ISSUED

        response = api.accept_referral(
            referral["id"], make_member_headers(scene["finn"]["id"])
        )

        # Issuance is indifferent to the reporting instant; only the acceptance
        # consults the member's employment intervals.
        expect_error(response, ERR_OVERLAPPING_DISPATCH)

    def test_a_reporting_instant_equal_to_the_prior_ending_is_adjacency(self, api):
        """
        PRD §2.5: "**A member's employment interval** is half-open — from `start_at`
        up to but not including `ended_at`, or from `start_at` forward without end
        while the dispatch is `WORKING` — which means a new acceptance whose
        reporting instant is exactly equal to a prior dispatch's `ended_at` is
        permitted as adjacency rather than blocked as overlap."

        Design: Difficulty/resource_temporal_overlap/member_employment_interval_half_open_allows_adjacency
        """
        scene = _member_laid_off_and_back_on_the_book(api)
        overlapping_call = _call(
            api, scene["contractor"]["id"], "Line 4 Overlap", OVERLAPPING_REPORT_AT
        )
        adjacent_call = _call(
            api, scene["contractor"]["id"], "Line 5 Adjacent", ADJACENT_REPORT_AT
        )
        blocked = fx.issue_referral(
            api, overlapping_call["id"], slot_kind=SLOT_JOURNEYWORKER
        )
        expect_error(
            api.accept_referral(
                blocked["id"], make_member_headers(scene["finn"]["id"])
            ),
            ERR_OVERLAPPING_DISPATCH,
        )
        withdrawn = fx.withdraw_referral(api, blocked["id"], WITHDRAWAL_REASON)
        assert withdrawn["status"] == REFERRAL_WITHDRAWN

        adjacent_referral = fx.issue_referral(
            api, adjacent_call["id"], slot_kind=SLOT_JOURNEYWORKER
        )
        dispatch = expect_created(
            api.accept_referral(
                adjacent_referral["id"], make_member_headers(scene["finn"]["id"])
            )
        )

        assert dispatch["status"] == DISPATCH_WORKING
        assert_instant_equals(dispatch["start_at"], ADJACENT_REPORT_AT)
        assert_instant_equals(dispatch["start_at"], scene["laid_off"]["ended_at"])
        assert dispatch["recall_of_dispatch_id"] is None

    def test_the_withdrawal_returns_the_registration_for_the_adjacent_call(self, api):
        """
        PRD §3.7: "**Withdrawal makes the member whole.**"

        Design: Difficulty/resource_temporal_overlap/member_employment_interval_half_open_allows_adjacency
        """
        scene = _member_laid_off_and_back_on_the_book(api)
        overlapping_call = _call(
            api, scene["contractor"]["id"], "Line 4 Overlap", OVERLAPPING_REPORT_AT
        )
        blocked = fx.issue_referral(
            api, overlapping_call["id"], slot_kind=SLOT_JOURNEYWORKER
        )
        fx.withdraw_referral(api, blocked["id"], WITHDRAWAL_REASON)

        restored = fx.read_registration(api, scene["second_registration"]["id"])
        assert restored["status"] == REGISTRATION_REGISTERED
        assert restored["position_number"] == 1
        assert restored["demotion_count"] == 0


class TestReferralOccupationIsClosedAtBothEnds:
    """The registration stays occupied through the deadline instant itself."""

    def test_the_occupation_runs_from_issuance_through_the_deadline(self, api):
        """
        PRD §2.5: "**A registration's outstanding-referral occupation** is the
        closed interval from `issued_at` through `acceptance_deadline` with capacity
        one, so an attempt to issue a second referral against the same registration
        at the instant the clock exactly equals the existing `acceptance_deadline` is
        refused."

        Design: Difficulty/resource_temporal_overlap/registration_outstanding_referral_slot_closed_at_deadline
        """
        scene = _sole_registrant_named_on_two_calls(api)

        assert_instant_equals(scene["first_referral"]["issued_at"], OCCUPATION_CLOCK)
        assert_instant_equals(
            scene["first_referral"]["acceptance_deadline"], OCCUPATION_DEADLINE
        )

        fx.set_clock(api, OCCUPATION_DEADLINE)
        response = _named_call(
            api, scene["calls"]["Request B"]["id"], scene["gia"]["id"]
        )

        expect_error(response, ERR_REFERRAL_ALREADY_OUTSTANDING)

    def test_one_millisecond_later_the_slot_is_free_but_the_registration_is_not(
        self, api
    ):
        """
        PRD §3.6: "The member must hold no outstanding referral — no referral of any
        of that member's registrations may have `status` of `ISSUED` with an
        `acceptance_deadline` at or after the current instant — failing with
        `ERR_REFERRAL_ALREADY_OUTSTANDING`."

        Design: Difficulty/resource_temporal_overlap/registration_outstanding_referral_slot_closed_at_deadline
        """
        scene = _sole_registrant_named_on_two_calls(api)
        assert_instant_equals(
            ONE_MILLISECOND_LATE, plus_millis(OCCUPATION_DEADLINE, 1)
        )
        fx.set_clock(api, ONE_MILLISECOND_LATE)

        response = _named_call(
            api, scene["calls"]["Request B"]["id"], scene["gia"]["id"]
        )

        # The occupation has lapsed, so the reported failure moves on to the
        # registration's own status, which the sweep has not yet restored.
        error = expect_error(response, ERR_REGISTRATION_NOT_ACTIVE)
        assert error["error_id"] != ERR_REFERRAL_ALREADY_OUTSTANDING

    def test_the_sweep_past_the_deadline_returns_the_registration_demoted(self, api):
        """
        PRD §3.4: "Step one expires stale referrals: every referral whose `status` is
        `ISSUED` and whose `acceptance_deadline` is strictly earlier than the current
        instant becomes `EXPIRED`."

        Design: Difficulty/resource_temporal_overlap/registration_outstanding_referral_slot_closed_at_deadline
        """
        scene = _sole_registrant_named_on_two_calls(api)
        fx.set_clock(api, ONE_MILLISECOND_LATE)

        result = fx.run_sweep(api)

        assert result["expired_referral_count"] == 1
        assert result["demoted_registration_count"] == 1
        assert (
            fx.read_referral(api, scene["first_referral"]["id"])["status"]
            == REFERRAL_EXPIRED
        )
        registration = fx.read_registration(api, scene["registration"]["id"])
        assert registration["status"] == REGISTRATION_REGISTERED
        assert registration["demotion_count"] == 1
        assert registration["position_number"] == 1

    def test_a_fresh_named_call_opens_a_new_occupation_from_the_current_instant(
        self, api
    ):
        """
        PRD §3.6: "A successful issuance creates a `Referral` in `ISSUED` status
        against the request named in `job_request_id`, recording the chosen
        `registration_id`, the `member_id` denormalized from that registration so
        record-retention lookups survive the registration's later removal,
        `issued_at` as the current instant, `acceptance_deadline` as `issued_at` plus
        24 hours, `issued_by_user_id` as the dispatcher's `X-User-ID`,
        `list_position_at_issue` as a snapshot of the selected registration's
        `position_number` at that moment, and `variant_applied` as the variant that
        produced the ranking."

        Design: Difficulty/resource_temporal_overlap/registration_outstanding_referral_slot_closed_at_deadline
        """
        scene = _sole_registrant_named_on_two_calls(api)
        fx.set_clock(api, ONE_MILLISECOND_LATE)
        fx.run_sweep(api)

        issued = expect_created(
            _named_call(api, scene["calls"]["Request C"]["id"], scene["gia"]["id"])
        )

        assert issued["status"] == REFERRAL_ISSUED
        assert_instant_equals(issued["issued_at"], ONE_MILLISECOND_LATE)
        assert_instant_equals(issued["acceptance_deadline"], SECOND_DEADLINE)

    def test_answering_the_expired_referral_is_refused_outright(self, api):
        """
        PRD §3.7: "From issuance the member has 24 hours to answer, and the window is
        open while the current instant is at or before the `acceptance_deadline`; an
        answer arriving strictly after the deadline is refused with
        `ERR_ACCEPTANCE_WINDOW_CLOSED`."

        Design: Difficulty/resource_temporal_overlap/registration_outstanding_referral_slot_closed_at_deadline
        """
        scene = _sole_registrant_named_on_two_calls(api)
        fx.set_clock(api, ONE_MILLISECOND_LATE)

        response = api.accept_referral(
            scene["first_referral"]["id"], make_member_headers(scene["gia"]["id"])
        )

        expect_error(response, ERR_ACCEPTANCE_WINDOW_CLOSED)
