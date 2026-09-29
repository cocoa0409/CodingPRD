"""
Two requests that break two rules at once, where the hall must always name the
earlier check: an outstanding referral ahead of an inactive registration, and a
mismatched predecessor ahead of an expired preservation window.
"""

from test_helpers import (
    DISPATCHER,
    DISPATCH_LAID_OFF,
    ERR_REFERRAL_ALREADY_OUTSTANDING,
    ERR_REGISTRATION_NOT_ACTIVE,
    ERR_REREGISTRATION_PREDECESSOR_MISMATCH,
    ERR_REREGISTRATION_WINDOW_EXPIRED,
    LAYOFF_LACK_OF_WORK,
    REFERRAL_ISSUED,
    REGISTRATION_DISPATCHED_OUT,
    REGISTRATION_REFERRED,
    REGISTRATION_REMOVED,
    REMOVAL_VOLUNTARY,
    SLOT_JOURNEYWORKER,
    assert_instant_equals,
    expect_error,
    factories as f,
    fixtures as fx,
    get_success_data,
    make_member_headers,
)

CLOCK = "2026-09-01T00:00:00.000Z"

# ─── Outstanding referral versus registration state ───────────────────────────

OUTSTANDING_CALLS = (
    ("Request A", "2026-09-25T07:00:00.000Z"),
    ("Request B", "2026-09-26T07:00:00.000Z"),
    ("Request C", "2026-09-27T07:00:00.000Z"),
)
OUTSTANDING_RATE_CENTS = 5200
OUTSTANDING_DURATION_DAYS = 30
FIRST_DEADLINE = "2026-09-02T00:00:00.000Z"

# ─── Predecessor identity versus the post-layoff window ───────────────────────

PRESERVATION_JOB_SITE = "Substation 4"
PRESERVATION_REPORT_AT = "2026-09-05T07:00:00.000Z"
PRESERVATION_RATE_CENTS = 5200
PRESERVATION_DURATION_DAYS = 30
LAYOFF_AT = "2026-09-10T07:00:00.000Z"
RECALL_WINDOW_ENDS_AT = "2026-09-17T07:00:00.000Z"
# Ten days past the layoff, so the five-day preservation window has long shut.
CLAIM_AT = "2026-09-20T07:00:00.000Z"
LAYOFF_HOURS = 40


def _one_referred_one_removed(api):
    """
    Two signers on the rank-one group: the first is out on a live referral, and
    the second has taken themselves off the book voluntarily, so each candidate
    fails a different single check.
    """
    hall = fx.standard_hall(api, clock=CLOCK)
    uma = fx.add_journeyworker(api, hall["home_local_id"], "Uma Reed", 9000)
    vic = fx.add_journeyworker(api, hall["home_local_id"], "Vic Shah", 7000)
    uma_registration = fx.sign_book(api, uma["id"], hall["group_1_id"])
    vic_registration = fx.sign_book(api, vic["id"], hall["group_1_id"])

    removed = get_success_data(
        api.remove_registration(
            vic_registration["id"], f.removal_payload(REMOVAL_VOLUNTARY), DISPATCHER
        )
    )

    contractor = fx.add_contractor(api, name="Harbor Piping")
    named_by_request = {"Request A": [], "Request B": [uma["id"]], "Request C": [vic["id"]]}
    calls = {}
    for job_site, report_at in OUTSTANDING_CALLS:
        calls[job_site] = fx.open_job_request(
            api,
            contractor["id"],
            job_site=job_site,
            journeyworkers_requested=1,
            apprentices_requested=0,
            expected_duration_days=OUTSTANDING_DURATION_DAYS,
            report_at=report_at,
            hourly_rate_cents=OUTSTANDING_RATE_CENTS,
            named_call_member_ids=named_by_request[job_site],
        )

    first_referral = fx.issue_referral(
        api, calls["Request A"]["id"], slot_kind=SLOT_JOURNEYWORKER
    )
    return {
        "hall": hall,
        "uma": uma,
        "vic": vic,
        "uma_registration": uma_registration,
        "vic_registration": vic_registration,
        "removed": removed,
        "contractor": contractor,
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


def _laid_off_pair(api):
    """
    Two journeyworkers on the book; the first takes a call, is laid off for lack
    of work, and then lets the five-day preservation window lapse.
    """
    hall = fx.standard_hall(api, clock=CLOCK)
    wes = fx.add_journeyworker(api, hall["home_local_id"], "Wes Park", 9000)
    yuki = fx.add_journeyworker(api, hall["home_local_id"], "Yuki Tan", 8000)
    wes_registration = fx.sign_book(api, wes["id"], hall["group_1_id"])
    yuki_registration = fx.sign_book(api, yuki["id"], hall["group_1_id"])
    contractor = fx.add_contractor(api, name="Ironline Constructors")
    job_request = fx.open_job_request(
        api,
        contractor["id"],
        job_site=PRESERVATION_JOB_SITE,
        journeyworkers_requested=1,
        apprentices_requested=0,
        expected_duration_days=PRESERVATION_DURATION_DAYS,
        report_at=PRESERVATION_REPORT_AT,
        hourly_rate_cents=PRESERVATION_RATE_CENTS,
    )
    referral = fx.issue_referral(api, job_request["id"], slot_kind=SLOT_JOURNEYWORKER)
    dispatch = fx.accept_referral(api, referral["id"], wes["id"])

    fx.set_clock(api, LAYOFF_AT)
    laid_off = fx.lay_off(
        api, dispatch["id"], contractor["id"], LAYOFF_HOURS, LAYOFF_LACK_OF_WORK
    )

    fx.set_clock(api, CLAIM_AT)
    return {
        "hall": hall,
        "wes": wes,
        "yuki": yuki,
        "wes_registration": wes_registration,
        "yuki_registration": yuki_registration,
        "dispatch": dispatch,
        "laid_off": laid_off,
    }


def _claim_preservation(api, member, list_id, predecessor_registration_id):
    """The member themselves claims the ordinal their layoff was supposed to keep."""
    return api.create_registration(
        f.preserving_registration_payload(
            member["id"], list_id, predecessor_registration_id
        ),
        make_member_headers(member["id"]),
    )


class TestOutstandingReferralBeatsRegistrationState:
    """Check 11 is reported even though check 30 would also refuse."""

    def test_the_live_referral_takes_the_registration_off_the_active_book(self, api):
        """
        PRD §3.6: "A successful issuance creates a `Referral` in `ISSUED` status
        against the request named in `job_request_id`, recording the chosen
        `registration_id`, the `member_id` denormalized from that registration so
        record-retention lookups survive the registration's later removal,
        `issued_at` as the current instant, `acceptance_deadline` as `issued_at`
        plus 24 hours, `issued_by_user_id` as the dispatcher's `X-User-ID`,
        `list_position_at_issue` as a snapshot of the selected registration's
        `position_number` at that moment, and `variant_applied` as the variant that
        produced the ranking."

        Design: Difficulty/priority_pair_validation_conflict/outstanding_referral_constraint_beats_registration_state
        """
        scene = _one_referred_one_removed(api)

        assert scene["first_referral"]["status"] == REFERRAL_ISSUED
        assert scene["first_referral"]["registration_id"] == (
            scene["uma_registration"]["id"]
        )
        assert_instant_equals(
            scene["first_referral"]["acceptance_deadline"], FIRST_DEADLINE
        )
        referred = fx.read_registration(api, scene["uma_registration"]["id"])
        assert referred["status"] == REGISTRATION_REFERRED

    def test_a_named_call_on_a_referred_member_names_the_outstanding_referral(
        self, api
    ):
        """
        PRD §2.7: "This check sits deliberately ahead of the registration-state
        check at position 30, so that a member who is already out on a referral is
        reported as such rather than as the holder of an inactive registration."

        Design: Difficulty/priority_pair_validation_conflict/outstanding_referral_constraint_beats_registration_state
        """
        scene = _one_referred_one_removed(api)

        response = _named_call(
            api, scene["calls"]["Request B"]["id"], scene["uma"]["id"]
        )

        error = expect_error(response, ERR_REFERRAL_ALREADY_OUTSTANDING)
        assert error["error_id"] != ERR_REGISTRATION_NOT_ACTIVE

    def test_a_named_call_on_a_removed_registration_names_the_later_check(self, api):
        """
        PRD §2.7: "The target registration's `status` is `REGISTERED`, on referral
        issuance, re-signing, and removal, failing with
        `ERR_REGISTRATION_NOT_ACTIVE`."

        Design: Difficulty/priority_pair_validation_conflict/outstanding_referral_constraint_beats_registration_state
        """
        scene = _one_referred_one_removed(api)
        assert scene["removed"]["status"] == REGISTRATION_REMOVED

        response = _named_call(
            api, scene["calls"]["Request C"]["id"], scene["vic"]["id"]
        )

        # This member holds no referral at all, so the earlier check passes and the
        # registration-state check is the one that answers.
        expect_error(response, ERR_REGISTRATION_NOT_ACTIVE)

    def test_the_two_members_differ_only_in_which_check_they_trip(self, api):
        """
        PRD §2.7: "This ordering is contractual: a request that trips both a late
        check and an early one is reported under the early one."

        Design: Difficulty/priority_pair_validation_conflict/outstanding_referral_constraint_beats_registration_state
        """
        scene = _one_referred_one_removed(api)

        referred_response = _named_call(
            api, scene["calls"]["Request B"]["id"], scene["uma"]["id"]
        )
        removed_response = _named_call(
            api, scene["calls"]["Request C"]["id"], scene["vic"]["id"]
        )

        assert scene["calls"]["Request B"]["named_call_allowance"] == 1
        assert scene["calls"]["Request C"]["named_call_allowance"] == 1
        referred_error = expect_error(
            referred_response, ERR_REFERRAL_ALREADY_OUTSTANDING
        )
        removed_error = expect_error(removed_response, ERR_REGISTRATION_NOT_ACTIVE)
        assert referred_error["error_id"] != removed_error["error_id"]


class TestPredecessorIdentityBeatsPreservationWindow:
    """Check 22 is reported even though check 26 would also refuse."""

    def test_the_layoff_records_the_ending_instant_and_the_recall_horizon(self, api):
        """
        PRD §3.8: "`REDUCTION_IN_FORCE`, `JOB_COMPLETE`, and `LACK_OF_WORK` are all
        no-fault endings: the `status` becomes `LAID_OFF`, `ended_at` is set to the
        current instant, the reported `hours_worked` is recorded, and
        `recall_window_ends_at` is set to the current instant plus 7 days."

        Design: Difficulty/priority_pair_validation_conflict/reregistration_predecessor_referential_beats_window_temporal
        """
        scene = _laid_off_pair(api)

        assert_instant_equals(scene["dispatch"]["start_at"], PRESERVATION_REPORT_AT)
        assert scene["laid_off"]["status"] == DISPATCH_LAID_OFF
        assert_instant_equals(scene["laid_off"]["ended_at"], LAYOFF_AT)
        assert_instant_equals(
            scene["laid_off"]["recall_window_ends_at"], RECALL_WINDOW_ENDS_AT
        )
        assert (
            fx.read_registration(api, scene["wes_registration"]["id"])["status"]
            == REGISTRATION_DISPATCHED_OUT
        )

    def test_a_predecessor_belonging_to_another_member_is_the_reported_failure(
        self, api
    ):
        """
        PRD §3.3: "That predecessor must belong to the same member as the new
        registration; a mismatch is `ERR_REREGISTRATION_PREDECESSOR_MISMATCH` with
        HTTP 422."

        Design: Difficulty/priority_pair_validation_conflict/reregistration_predecessor_referential_beats_window_temporal
        """
        scene = _laid_off_pair(api)

        response = _claim_preservation(
            api,
            scene["wes"],
            scene["hall"]["group_1_id"],
            scene["yuki_registration"]["id"],
        )

        # The window has also lapsed by this instant, yet identity is checked first.
        error = expect_error(response, ERR_REREGISTRATION_PREDECESSOR_MISMATCH)
        assert error["error_id"] != ERR_REREGISTRATION_WINDOW_EXPIRED

    def test_the_member_own_predecessor_reaches_the_window_check(self, api):
        """
        PRD §3.3: "A claim outside that five-day window, or resting on a dispatch
        that ended in `TERMINATED_FOR_CAUSE` or `QUIT` instead, is refused with
        `ERR_REREGISTRATION_WINDOW_EXPIRED`."

        Design: Difficulty/priority_pair_validation_conflict/reregistration_predecessor_referential_beats_window_temporal
        """
        scene = _laid_off_pair(api)

        response = _claim_preservation(
            api,
            scene["wes"],
            scene["hall"]["group_1_id"],
            scene["wes_registration"]["id"],
        )

        expect_error(response, ERR_REREGISTRATION_WINDOW_EXPIRED)

    def test_the_same_claim_instant_yields_two_different_refusals(self, api):
        """
        PRD §2.7: "Checks are therefore evaluated in a fixed precedence, lowest
        number first, and evaluation stops at the first failure."

        Design: Difficulty/priority_pair_validation_conflict/reregistration_predecessor_referential_beats_window_temporal
        """
        scene = _laid_off_pair(api)

        mismatch = _claim_preservation(
            api,
            scene["wes"],
            scene["hall"]["group_1_id"],
            scene["yuki_registration"]["id"],
        )
        expired = _claim_preservation(
            api,
            scene["wes"],
            scene["hall"]["group_1_id"],
            scene["wes_registration"]["id"],
        )

        expect_error(mismatch, ERR_REREGISTRATION_PREDECESSOR_MISMATCH)
        expect_error(expired, ERR_REREGISTRATION_WINDOW_EXPIRED)
