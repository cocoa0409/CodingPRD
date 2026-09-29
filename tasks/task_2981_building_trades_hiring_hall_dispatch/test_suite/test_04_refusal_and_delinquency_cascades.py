"""
The two four-hop cascades: a third bare turn-down that walks from the referral
out to the member's own eligibility, and a contractor's delinquency that walks
from the contractor down to every registrant's ordinal.
"""

from test_helpers import (
    DISPATCHER,
    ERR_JOB_REQUEST_SUSPENDED,
    ERR_REREGISTRATION_TOO_EARLY,
    EVENT_POSITION_RESTORED,
    EVENT_REFERRAL_WITHDRAWN,
    EVENT_REGISTRATION_REMOVED,
    JOB_REQUEST_OPEN,
    JOB_REQUEST_SUSPENDED,
    PURGE_RETAINED,
    REFERRAL_ISSUED,
    REFERRAL_REFUSED,
    REFERRAL_WITHDRAWN,
    REGISTRATION_REGISTERED,
    REGISTRATION_REMOVED,
    REMOVAL_THREE_REFUSALS,
    SLOT_JOURNEYWORKER,
    STANDING_GOOD,
    TERMINATED,
    assert_instant_equals,
    expect_error,
    factories as f,
    find_row,
    fixtures as fx,
    make_member_headers,
)

CLOCK = "2026-09-01T00:00:00.000Z"

# ─── The three-strike cascade ─────────────────────────────────────────────────

STRIKE_CALLS = (
    ("Call One", 20, "2026-09-20T07:00:00.000Z"),
    ("Call Two", 21, "2026-09-21T07:00:00.000Z"),
    ("Call Three", 22, "2026-09-22T07:00:00.000Z"),
)
STRIKE_RATE_CENTS = 5000
COOLING_OFF_ENDS_AT = "2026-10-01T00:00:00.000Z"
RETENTION_HORIZON = "2031-08-31T00:00:00.000Z"

# ─── The delinquency cascade ──────────────────────────────────────────────────

DELINQUENCY_JOB_SITE = "Tower Crane Base"
DELINQUENCY_REPORT_AT = "2026-09-25T07:00:00.000Z"
DELINQUENCY_RATE_CENTS = 5600
DELINQUENCY_DURATION_DAYS = 60


def _sole_registrant_with_three_calls(api):
    """
    One journeyworker alone on the rank-one group and three separate long calls,
    so each turn-down is charged against a different job request while the clock
    never moves.
    """
    hall = fx.standard_hall(api, clock=CLOCK)
    member = fx.add_journeyworker(api, hall["home_local_id"], "Tess Malik", 9000)
    registration = fx.sign_book(api, member["id"], hall["group_1_id"])
    contractor = fx.add_contractor(api, name="Fulton Mechanical")
    calls = [
        fx.open_job_request(
            api,
            contractor["id"],
            job_site=job_site,
            journeyworkers_requested=1,
            apprentices_requested=0,
            expected_duration_days=days,
            report_at=report_at,
            hourly_rate_cents=STRIKE_RATE_CENTS,
        )
        for job_site, days, report_at in STRIKE_CALLS
    ]
    return {
        "hall": hall,
        "member": member,
        "registration": registration,
        "contractor": contractor,
        "calls": calls,
    }


def _turn_down(api, job_request_id, member_id):
    """Issue a list-order referral and refuse it with no good cause at all."""
    referral = fx.issue_referral(api, job_request_id, slot_kind=SLOT_JOURNEYWORKER)
    return fx.refuse_referral(api, referral["id"], member_id)


def _two_referrals_outstanding(api):
    """
    Two registrants each holding an ISSUED referral against one two-slot call, so
    nobody is on the job when the contractor goes delinquent.
    """
    hall = fx.standard_hall(api, clock=CLOCK)
    ada = fx.add_journeyworker(api, hall["home_local_id"], "Ada Cole", 9000)
    ben = fx.add_journeyworker(api, hall["home_local_id"], "Ben Ito", 8000)
    ada_registration = fx.sign_book(api, ada["id"], hall["group_1_id"])
    ben_registration = fx.sign_book(api, ben["id"], hall["group_1_id"])
    contractor = fx.add_contractor(api, name="Crestline Erectors")
    job_request = fx.open_job_request(
        api,
        contractor["id"],
        job_site=DELINQUENCY_JOB_SITE,
        journeyworkers_requested=2,
        apprentices_requested=0,
        expected_duration_days=DELINQUENCY_DURATION_DAYS,
        report_at=DELINQUENCY_REPORT_AT,
        hourly_rate_cents=DELINQUENCY_RATE_CENTS,
    )
    ada_referral = fx.issue_referral(
        api, job_request["id"], slot_kind=SLOT_JOURNEYWORKER
    )
    ben_referral = fx.issue_referral(
        api, job_request["id"], slot_kind=SLOT_JOURNEYWORKER
    )
    return {
        "hall": hall,
        "ada": ada,
        "ben": ben,
        "ada_registration": ada_registration,
        "ben_registration": ben_registration,
        "contractor": contractor,
        "job_request": job_request,
        "ada_referral": ada_referral,
        "ben_referral": ben_referral,
    }


class TestThirdBareRefusalCascade:
    """Referral, registration, member eligibility and the dispatch record."""

    def test_the_first_two_turn_downs_only_cost_position(self, api):
        """
        PRD §3.7: "This is the outcome whenever the member's strike count after
        the refusal stands at 1 or 2."

        Design: Difficulty/transitive_cascade/three_strike_refusal_cascade_depth_four
        """
        scene = _sole_registrant_with_three_calls(api)
        assert scene["member"]["dispatch_eligible"] is True
        assert scene["member"]["re_registration_eligible_at"] is None

        _turn_down(api, scene["calls"][0]["id"], scene["member"]["id"])
        after_one = fx.read_member(api, scene["member"]["id"])
        assert after_one["refusal_strike_count"] == 1
        assert after_one["dispatch_eligible"] is True

        _turn_down(api, scene["calls"][1]["id"], scene["member"]["id"])
        after_two = fx.read_member(api, scene["member"]["id"])
        assert after_two["refusal_strike_count"] == 2
        assert after_two["dispatch_eligible"] is True
        on_book = fx.read_registration(api, scene["registration"]["id"])
        assert on_book["status"] == REGISTRATION_REGISTERED
        assert on_book["demotion_count"] == 2
        assert on_book["position_number"] == 1

    def test_the_third_turn_down_removes_the_registration_for_three_refusals(
        self, api
    ):
        """
        PRD §3.7: "Second, because that refusal is the third bare turn-down inside
        the rolling window, the registration's `demotion_count` is incremented and
        its `status` becomes `REMOVED` with `removal_reason` of `THREE_REFUSALS`
        and a null `position_number`."

        Design: Difficulty/transitive_cascade/three_strike_refusal_cascade_depth_four
        """
        scene = _sole_registrant_with_three_calls(api)
        _turn_down(api, scene["calls"][0]["id"], scene["member"]["id"])
        _turn_down(api, scene["calls"][1]["id"], scene["member"]["id"])

        third = _turn_down(api, scene["calls"][2]["id"], scene["member"]["id"])

        assert third["status"] == REFERRAL_REFUSED
        assert third["refusal_good_cause_code"] is None
        removed = fx.read_registration(api, scene["registration"]["id"])
        assert removed["status"] == REGISTRATION_REMOVED
        assert removed["removal_reason"] == REMOVAL_THREE_REFUSALS
        assert removed["position_number"] is None
        assert removed["demotion_count"] == 3

    def test_removal_opens_a_cooling_off_period_and_empties_the_group(self, api):
        """
        PRD §3.7: "Third, because that registration was removed, the member's
        `re_registration_eligible_at` is set to the current instant plus 30 days
        and the group's `registered_count` is decremented."

        Design: Difficulty/transitive_cascade/three_strike_refusal_cascade_depth_four
        """
        scene = _sole_registrant_with_three_calls(api)
        for call in scene["calls"]:
            _turn_down(api, call["id"], scene["member"]["id"])

        member = fx.read_member(api, scene["member"]["id"])
        assert member["refusal_strike_count"] == 3
        assert_instant_equals(
            member["re_registration_eligible_at"], COOLING_OFF_ENDS_AT
        )
        assert fx.read_list_group(api, scene["hall"]["group_1_id"])[
            "registered_count"
        ] == 0

    def test_the_cooling_off_period_alone_makes_the_member_undispatchable(self, api):
        """
        PRD §3.7: "Fourth, because `re_registration_eligible_at` now lies in the
        future, the member's `dispatch_eligible` becomes false, which removes the
        member from every candidate pool the hall computes until the cooling-off
        period elapses."

        Design: Difficulty/transitive_cascade/three_strike_refusal_cascade_depth_four
        """
        scene = _sole_registrant_with_three_calls(api)
        for call in scene["calls"]:
            _turn_down(api, call["id"], scene["member"]["id"])

        member = fx.read_member(api, scene["member"]["id"])
        # Standing was never touched, so eligibility can only have fallen because
        # of the cooling-off horizon.
        assert member["standing"] == STANDING_GOOD
        assert member["dispatch_eligible"] is False

    def test_the_removal_is_recorded_in_the_retention_ledger(self, api):
        """
        PRD §2.10: "Each entry's `retention_until` is its `recorded_at` plus 1,825
        days, and its `purge_state` is `RETAINED` until the housekeeping sweep
        flips it to `PURGED` and clears `snapshot_json` to null."

        Design: Difficulty/transitive_cascade/three_strike_refusal_cascade_depth_four
        """
        scene = _sole_registrant_with_three_calls(api)
        for call in scene["calls"]:
            _turn_down(api, call["id"], scene["member"]["id"])

        rows = fx.ledger_rows(
            api,
            member_id=scene["member"]["id"],
            event_code=EVENT_REGISTRATION_REMOVED,
        )

        assert len(rows) == 1
        assert_instant_equals(rows[0]["recorded_at"], CLOCK)
        assert_instant_equals(rows[0]["retention_until"], RETENTION_HORIZON)
        assert rows[0]["purge_state"] == PURGE_RETAINED

    def test_the_member_cannot_sign_the_book_again_inside_the_cooling_off_period(
        self, api
    ):
        """
        PRD §3.3: "A member who was removed for three refusals cannot sign again
        until the cooling-off period has elapsed: the current instant must have
        reached or passed `re_registration_eligible_at`, or that field must be
        null, and an early attempt is refused with `ERR_REREGISTRATION_TOO_EARLY`."

        Design: Difficulty/transitive_cascade/three_strike_refusal_cascade_depth_four
        """
        scene = _sole_registrant_with_three_calls(api)
        for call in scene["calls"]:
            _turn_down(api, call["id"], scene["member"]["id"])

        response = api.create_registration(
            f.registration_payload(scene["member"]["id"], scene["hall"]["group_1_id"]),
            make_member_headers(scene["member"]["id"]),
        )

        expect_error(response, ERR_REREGISTRATION_TOO_EARLY)


class TestContractorDelinquencyCascade:
    """Contractor, request, referrals and every pulled-back ordinal."""

    def test_termination_suspends_the_open_request_it_reaches(self, api):
        """
        PRD §3.5: "**Contractor delinquency reaches into live work in four
        hops.**"

        Design: Difficulty/transitive_cascade/contractor_delinquency_withdrawal_cascade_depth_four
        """
        scene = _two_referrals_outstanding(api)
        assert scene["ada_referral"]["status"] == REFERRAL_ISSUED
        assert scene["ben_referral"]["status"] == REFERRAL_ISSUED
        assert fx.read_list_group(api, scene["hall"]["group_1_id"])[
            "registered_count"
        ] == 0

        contractor = fx.set_signatory_status(api, scene["contractor"]["id"], TERMINATED)

        assert contractor["signatory_status"] == TERMINATED
        suspended = fx.read_job_request(api, scene["job_request"]["id"])
        assert suspended["status"] == JOB_REQUEST_SUSPENDED
        assert suspended["suspended_from_status"] == JOB_REQUEST_OPEN
        assert suspended["open_journeyworker_slots"] == 2

    def test_every_outstanding_referral_is_withdrawn(self, api):
        """
        PRD §3.5: "The second hop withdraws every referral on those requests whose
        `status` is `ISSUED`, processing them in `acceptance_deadline` ascending
        order with `created_at` ascending as the tie-break."

        Design: Difficulty/transitive_cascade/contractor_delinquency_withdrawal_cascade_depth_four
        """
        scene = _two_referrals_outstanding(api)

        fx.set_signatory_status(api, scene["contractor"]["id"], TERMINATED)

        rows = fx.referrals_on(api, scene["job_request"]["id"])
        assert len(rows) == 2
        assert {row["status"] for row in rows} == {REFERRAL_WITHDRAWN}
        assert (
            fx.read_referral(api, scene["ada_referral"]["id"])["status"]
            == REFERRAL_WITHDRAWN
        )
        assert (
            fx.read_referral(api, scene["ben_referral"]["id"])["status"]
            == REFERRAL_WITHDRAWN
        )

    def test_each_registration_returns_to_the_ordinal_it_left(self, api):
        """
        PRD §3.5: "The third hop returns each withdrawn referral's registration
        from `REFERRED` to `REGISTERED` with its `registered_at`,
        `credited_seniority_hours`, `demotion_count`, and `priority_flag` all
        unchanged and no refusal strike charged, after which the affected lists are
        renumbered and their `registered_count` values raised."

        Design: Difficulty/transitive_cascade/contractor_delinquency_withdrawal_cascade_depth_four
        """
        scene = _two_referrals_outstanding(api)

        fx.set_signatory_status(api, scene["contractor"]["id"], TERMINATED)

        ada_registration = fx.read_registration(api, scene["ada_registration"]["id"])
        ben_registration = fx.read_registration(api, scene["ben_registration"]["id"])
        for restored in (ada_registration, ben_registration):
            assert restored["status"] == REGISTRATION_REGISTERED
            assert restored["demotion_count"] == 0
        assert ada_registration["position_number"] == 1
        assert ben_registration["position_number"] == 2
        assert fx.read_list_group(api, scene["hall"]["group_1_id"])[
            "registered_count"
        ] == 2

    def test_no_pulled_back_member_is_charged_a_strike(self, api):
        """
        PRD §3.7: "No strike is charged and no demotion is recorded — a withdrawal
        is the hall's mistake, not the member's."

        Design: Difficulty/transitive_cascade/contractor_delinquency_withdrawal_cascade_depth_four
        """
        scene = _two_referrals_outstanding(api)

        fx.set_signatory_status(api, scene["contractor"]["id"], TERMINATED)

        for member_id in (scene["ada"]["id"], scene["ben"]["id"]):
            member = fx.read_member(api, member_id)
            assert member["refusal_strike_count"] == 0
            assert member["re_registration_eligible_at"] is None
            assert member["dispatch_eligible"] is True

    def test_the_dispatch_record_pairs_a_withdrawal_with_a_restored_position(
        self, api
    ):
        """
        PRD §3.5: "The fourth hop appends a `REFERRAL_WITHDRAWN` entry and a
        `POSITION_RESTORED` entry to the dispatch record for each affected
        registration."

        Design: Difficulty/transitive_cascade/contractor_delinquency_withdrawal_cascade_depth_four
        """
        scene = _two_referrals_outstanding(api)

        fx.set_signatory_status(api, scene["contractor"]["id"], TERMINATED)

        withdrawn = fx.ledger_rows(api, event_code=EVENT_REFERRAL_WITHDRAWN)
        restored = fx.ledger_rows(api, event_code=EVENT_POSITION_RESTORED)

        assert len(withdrawn) == 2
        assert len(restored) == 2
        for member, referral in (
            (scene["ada"], scene["ada_referral"]),
            (scene["ben"], scene["ben_referral"]),
        ):
            withdrawal_row = find_row(withdrawn, "member_id", member["id"])
            restoration_row = find_row(restored, "member_id", member["id"])
            assert withdrawal_row["referral_id"] == referral["id"]
            assert restoration_row["referral_id"] == referral["id"]

    def test_the_suspended_request_refuses_a_fresh_referral_from_the_dispatcher(
        self, api
    ):
        """
        PRD §3.5: "A referral issued against a suspended request is refused with
        `ERR_JOB_REQUEST_SUSPENDED`."

        Design: Difficulty/transitive_cascade/contractor_delinquency_withdrawal_cascade_depth_four
        """
        scene = _two_referrals_outstanding(api)
        fx.set_signatory_status(api, scene["contractor"]["id"], TERMINATED)

        # Both members are back on the book, yet the slots they vacated cannot be
        # dispatched while the request stays suspended.
        version = fx.job_request_version(api, scene["job_request"]["id"])
        response = api.create_referral(
            scene["job_request"]["id"],
            f.referral_payload(version, slot_kind=SLOT_JOURNEYWORKER),
            DISPATCHER,
        )

        expect_error(response, ERR_JOB_REQUEST_SUSPENDED)
        registered = fx.registrations_on(
            api, scene["hall"]["group_1_id"], status=REGISTRATION_REGISTERED
        )
        assert len(registered) == 2
