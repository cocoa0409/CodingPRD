"""
Two boundaries the hall must land on exactly: the millisecond either side of a
referral's acceptance deadline, and the apprentice cap that stays at zero until
the first journeyworker actually accepts.
"""

from test_helpers import (
    DISPATCHER,
    DISPATCH_WORKING,
    ERR_ACCEPTANCE_WINDOW_CLOSED,
    ERR_APPRENTICE_RATIO_EXCEEDED,
    JOB_REQUEST_PARTIALLY_FILLED,
    REFERRAL_EXPIRED,
    REFERRAL_ISSUED,
    REGISTRATION_DISPATCHED_OUT,
    REGISTRATION_REGISTERED,
    SLOT_APPRENTICE,
    SLOT_JOURNEYWORKER,
    assert_instant_equals,
    expect_created,
    expect_error,
    factories as f,
    fixtures as fx,
    make_member_headers,
    plus_hours,
    plus_millis,
)

# ─── The acceptance deadline ──────────────────────────────────────────────────

ISSUE_CLOCK = "2026-09-02T00:00:00.000Z"
DEADLINE = "2026-09-03T00:00:00.000Z"
ONE_MILLISECOND_LATE = "2026-09-03T00:00:00.001Z"
DEADLINE_CALLS = (
    ("Boiler House A", "2026-09-25T07:00:00.000Z"),
    ("Boiler House B", "2026-09-26T07:00:00.000Z"),
)
DEADLINE_RATE_CENTS = 5300
DEADLINE_DURATION_DAYS = 30

# ─── The apprentice ratio cap ─────────────────────────────────────────────────

RATIO_CLOCK = "2026-09-01T00:00:00.000Z"
RATIO_JOB_SITE = "Civic Center Fitout"
RATIO_REPORT_AT = "2026-09-28T07:00:00.000Z"
RATIO_RATE_CENTS = 5200
RATIO_DURATION_DAYS = 45


def _two_referrals_at_the_same_deadline(api):
    """
    Two registrants, two single-slot calls, and two referrals issued at the very
    instant the clock is parked at, so both deadlines fall together.
    """
    hall = fx.standard_hall(api, clock=ISSUE_CLOCK)
    zoe = fx.add_journeyworker(api, hall["home_local_id"], "Zoe Amin", 9000)
    ash = fx.add_journeyworker(api, hall["home_local_id"], "Ash Brar", 8000)
    zoe_registration = fx.sign_book(api, zoe["id"], hall["group_1_id"])
    ash_registration = fx.sign_book(api, ash["id"], hall["group_1_id"])
    contractor = fx.add_contractor(api, name="Lakeside Mechanical")

    calls = {}
    referrals = {}
    for job_site, report_at in DEADLINE_CALLS:
        calls[job_site] = fx.open_job_request(
            api,
            contractor["id"],
            job_site=job_site,
            journeyworkers_requested=1,
            apprentices_requested=0,
            expected_duration_days=DEADLINE_DURATION_DAYS,
            report_at=report_at,
            hourly_rate_cents=DEADLINE_RATE_CENTS,
        )
        referrals[job_site] = fx.issue_referral(
            api, calls[job_site]["id"], slot_kind=SLOT_JOURNEYWORKER
        )
    return {
        "hall": hall,
        "zoe": zoe,
        "ash": ash,
        "zoe_registration": zoe_registration,
        "ash_registration": ash_registration,
        "calls": calls,
        "referral_a": referrals["Boiler House A"],
        "referral_b": referrals["Boiler House B"],
    }


def _jw_and_apprentice_on_one_call(api):
    """
    A journeyworker on the rank-one group, an apprentice on the rank-three group,
    one in-force ratio schedule and a call asking for one of each.
    """
    hall = fx.standard_hall(api, clock=RATIO_CLOCK, groups=("GROUP_1", "GROUP_3"))
    cy = fx.add_journeyworker(api, hall["home_local_id"], "Cy Boyd", 9000)
    dee = fx.add_apprentice(api, hall["home_local_id"], "Dee Kwan", period=2, hours=500)
    cy_registration = fx.sign_book(api, cy["id"], hall["group_1_id"])
    dee_registration = fx.sign_book(api, dee["id"], hall["group_3_id"])
    contractor = fx.add_contractor(api, name="Vantage Builders")
    job_request = fx.open_job_request(
        api,
        contractor["id"],
        job_site=RATIO_JOB_SITE,
        journeyworkers_requested=1,
        apprentices_requested=1,
        expected_duration_days=RATIO_DURATION_DAYS,
        report_at=RATIO_REPORT_AT,
        hourly_rate_cents=RATIO_RATE_CENTS,
    )
    return {
        "hall": hall,
        "cy": cy,
        "dee": dee,
        "cy_registration": cy_registration,
        "dee_registration": dee_registration,
        "contractor": contractor,
        "job_request": job_request,
    }


def _attempt_apprentice_referral(api, job_request_id):
    version = fx.job_request_version(api, job_request_id)
    return api.create_referral(
        job_request_id,
        f.apprentice_referral_payload(version),
        DISPATCHER,
    )


class TestAcceptanceDeadlineInclusiveInstant:
    """At the deadline the answer is in time; one millisecond later it is not."""

    def test_the_deadline_is_exactly_twenty_four_hours_after_issuance(self, api):
        """
        PRD §2.5: "**The acceptance window** on a referral runs for 24 hours from
        issuance and is open while the clock is at or before the referral's
        `acceptance_deadline`; an answer arriving exactly at the deadline is still
        in time, and expiry requires the clock to be strictly greater than the
        deadline."

        Design: Difficulty/boundary_precision_check/acceptance_deadline_exact_instant_is_inclusive
        """
        scene = _two_referrals_at_the_same_deadline(api)

        assert_instant_equals(scene["referral_a"]["issued_at"], ISSUE_CLOCK)
        assert_instant_equals(
            scene["referral_a"]["acceptance_deadline"], plus_hours(ISSUE_CLOCK, 24)
        )
        assert_instant_equals(scene["referral_a"]["acceptance_deadline"], DEADLINE)
        assert_instant_equals(scene["referral_b"]["acceptance_deadline"], DEADLINE)

    def test_an_answer_arriving_exactly_at_the_deadline_creates_the_dispatch(
        self, api
    ):
        """
        PRD §3.7: "From issuance the member has 24 hours to answer, and the window
        is open while the current instant is at or before the `acceptance_deadline`;
        an answer arriving strictly after the deadline is refused with
        `ERR_ACCEPTANCE_WINDOW_CLOSED`."

        Design: Difficulty/boundary_precision_check/acceptance_deadline_exact_instant_is_inclusive
        """
        scene = _two_referrals_at_the_same_deadline(api)
        fx.set_clock(api, DEADLINE)

        dispatch = expect_created(
            api.accept_referral(
                scene["referral_a"]["id"], make_member_headers(scene["zoe"]["id"])
            )
        )

        assert dispatch["status"] == DISPATCH_WORKING
        assert (
            fx.read_registration(api, scene["zoe_registration"]["id"])["status"]
            == REGISTRATION_DISPATCHED_OUT
        )

    def test_the_sweep_at_the_deadline_expires_nothing(self, api):
        """
        PRD §3.4: "A referral sitting exactly at its deadline is untouched — expiry
        needs the clock strictly past the deadline."

        Design: Difficulty/boundary_precision_check/acceptance_deadline_exact_instant_is_inclusive
        """
        scene = _two_referrals_at_the_same_deadline(api)
        fx.set_clock(api, DEADLINE)

        result = fx.run_sweep(api)

        assert_instant_equals(result["run_at"], DEADLINE)
        assert result["expired_referral_count"] == 0
        assert result["demoted_registration_count"] == 0
        assert fx.read_referral(api, scene["referral_b"]["id"])["status"] == (
            REFERRAL_ISSUED
        )

    def test_an_answer_one_millisecond_late_is_refused(self, api):
        """
        PRD §3.7: "**Accepting** moves the referral from `ISSUED` to `ACCEPTED` and
        the registration from `REFERRED` to the terminal `DISPATCHED_OUT`, and it
        creates the employment record: a `Dispatch` in `WORKING` status whose
        `start_at` is the job request's `report_at`, whose `hours_worked` begins at
        0, and whose `ended_at`, `layoff_reason`, `recall_of_dispatch_id`, and
        `recall_window_ends_at` all begin null."

        Design: Difficulty/boundary_precision_check/acceptance_deadline_exact_instant_is_inclusive
        """
        scene = _two_referrals_at_the_same_deadline(api)
        assert_instant_equals(ONE_MILLISECOND_LATE, plus_millis(DEADLINE, 1))
        fx.set_clock(api, ONE_MILLISECOND_LATE)

        response = api.accept_referral(
            scene["referral_b"]["id"], make_member_headers(scene["ash"]["id"])
        )

        expect_error(response, ERR_ACCEPTANCE_WINDOW_CLOSED)

    def test_the_sweep_one_millisecond_late_expires_and_demotes(self, api):
        """
        PRD §3.4: "Step two applies the consequences of those expiries to each
        affected registration, using the same strike arithmetic a no-cause refusal
        uses: the registration returns from `REFERRED` to `REGISTERED` with its
        `demotion_count` incremented by 1, unless the expiry brings the member's
        effective refusal strikes to the removal threshold, in which case the
        registration is instead removed with `removal_reason` of `THREE_REFUSALS`."

        Design: Difficulty/boundary_precision_check/acceptance_deadline_exact_instant_is_inclusive
        """
        scene = _two_referrals_at_the_same_deadline(api)
        fx.set_clock(api, DEADLINE)
        fx.accept_referral(api, scene["referral_a"]["id"], scene["zoe"]["id"])
        fx.set_clock(api, ONE_MILLISECOND_LATE)

        result = fx.run_sweep(api)

        assert result["expired_referral_count"] == 1
        assert result["demoted_registration_count"] == 1
        assert (
            fx.read_referral(api, scene["referral_b"]["id"])["status"]
            == REFERRAL_EXPIRED
        )
        ash_registration = fx.read_registration(api, scene["ash_registration"]["id"])
        assert ash_registration["status"] == REGISTRATION_REGISTERED
        assert ash_registration["demotion_count"] == 1
        assert ash_registration["position_number"] == 1


class TestApprenticeCapBeforeFirstAcceptance:
    """The cap is zero until an accepted journeyworker referral raises it."""

    def test_the_cap_starts_at_zero_on_a_freshly_opened_call(self, api):
        """
        PRD §3.5: "On successful intake the request's `open_journeyworker_slots` and
        `open_apprentice_slots` are initialized to the two requested counts, its
        `accepted_journeyworker_count` and `accepted_apprentice_count` begin at 0,
        and its `max_apprentices_allowed` is initialized from the ratio computation
        of §3.6 — which yields 0 until a journeyworker referral has actually been
        accepted."

        Design: Difficulty/boundary_precision_check/apprentice_ratio_cap_zero_before_first_journeyworker_accept
        """
        scene = _jw_and_apprentice_on_one_call(api)

        assert scene["job_request"]["max_apprentices_allowed"] == 0
        assert scene["job_request"]["accepted_journeyworker_count"] == 0
        assert scene["job_request"]["open_apprentice_slots"] == 1

    def test_an_outstanding_journeyworker_referral_does_not_raise_the_cap(self, api):
        """
        PRD §3.6: "**Step two** computes the cap, `max_apprentices_allowed`, from
        **accepted journeyworker referrals only**: count the referrals on the
        request whose `slot_kind` is `JOURNEYWORKER` and whose `status` is
        `ACCEPTED`; if that count is zero, the cap is zero; otherwise subtract the
        schedule's `first_apprentice_at_jw_count` from the count, floor the
        difference at zero, divide by `then_every_n_jw` discarding the remainder,
        and add one."

        Design: Difficulty/boundary_precision_check/apprentice_ratio_cap_zero_before_first_journeyworker_accept
        """
        scene = _jw_and_apprentice_on_one_call(api)

        referral = fx.issue_referral(
            api, scene["job_request"]["id"], slot_kind=SLOT_JOURNEYWORKER
        )
        assert referral["status"] == REFERRAL_ISSUED

        still_capped = fx.read_job_request(api, scene["job_request"]["id"])
        assert still_capped["accepted_journeyworker_count"] == 0
        assert still_capped["max_apprentices_allowed"] == 0

    def test_the_apprentice_referral_is_refused_while_the_cap_is_zero(self, api):
        """
        PRD §3.6: "The asymmetry between steps two and three is the rule, not an
        oversight: an outstanding journeyworker referral does **not** raise the cap,
        because a journeyworker who has not accepted may yet refuse, while an
        outstanding apprentice referral **does** consume the cap, because the hall
        must not promise the same apprentice slot twice."

        Design: Difficulty/boundary_precision_check/apprentice_ratio_cap_zero_before_first_journeyworker_accept
        """
        scene = _jw_and_apprentice_on_one_call(api)
        fx.issue_referral(api, scene["job_request"]["id"], slot_kind=SLOT_JOURNEYWORKER)

        response = _attempt_apprentice_referral(api, scene["job_request"]["id"])

        expect_error(response, ERR_APPRENTICE_RATIO_EXCEEDED)

    def test_the_first_acceptance_raises_the_cap_to_one(self, api):
        """
        PRD §3.7: "And on the request side, the matching acceptance counter is
        incremented, `max_apprentices_allowed` is re-derived from the new accepted
        journeyworker count, the open-slot counters are recomputed, the group's
        `registered_count` is decremented, the request's `status` is re-derived from
        the acceptance counts, and the request's `version` increments by 1."

        Design: Difficulty/boundary_precision_check/apprentice_ratio_cap_zero_before_first_journeyworker_accept
        """
        scene = _jw_and_apprentice_on_one_call(api)
        referral = fx.issue_referral(
            api, scene["job_request"]["id"], slot_kind=SLOT_JOURNEYWORKER
        )
        fx.accept_referral(api, referral["id"], scene["cy"]["id"])

        raised = fx.read_job_request(api, scene["job_request"]["id"])
        assert raised["accepted_journeyworker_count"] == 1
        assert raised["max_apprentices_allowed"] == 1
        assert raised["status"] == JOB_REQUEST_PARTIALLY_FILLED

    def test_the_identical_apprentice_referral_now_succeeds(self, api):
        """
        PRD §3.6: "**Step three** applies the consumption test, which counts
        apprentice referrals more broadly: count the referrals on the request whose
        `slot_kind` is `APPRENTICE` and whose `status` is `ISSUED` or `ACCEPTED`,
        add one for the apprentice about to be committed, and compare against the
        lesser of `max_apprentices_allowed` and the request's
        `apprentices_requested`."

        Design: Difficulty/boundary_precision_check/apprentice_ratio_cap_zero_before_first_journeyworker_accept
        """
        scene = _jw_and_apprentice_on_one_call(api)
        referral = fx.issue_referral(
            api, scene["job_request"]["id"], slot_kind=SLOT_JOURNEYWORKER
        )
        refused = _attempt_apprentice_referral(api, scene["job_request"]["id"])
        expect_error(refused, ERR_APPRENTICE_RATIO_EXCEEDED)

        fx.accept_referral(api, referral["id"], scene["cy"]["id"])
        issued = expect_created(
            _attempt_apprentice_referral(api, scene["job_request"]["id"])
        )

        assert issued["slot_kind"] == SLOT_APPRENTICE
        assert issued["registration_id"] == scene["dee_registration"]["id"]
        assert issued["member_id"] == scene["dee"]["id"]
