"""
The computations behind the dispatch: the windows derived from one clock reading,
the filter that decides who is even a candidate, the two constants read at their
exact boundaries, and the variant stamped onto whatever the ranking produced.
"""

from test_helpers import (
    ACCEPTANCE_WINDOW_HOURS,
    APPRENTICE_RATE_FACTOR_BP,
    BACK_PAY_ACTUAL_HOURS,
    BP_SCALE,
    BUSINESS_MANAGER,
    CLAIM_RATIO_VIOLATION,
    CLASSIFICATION_APPRENTICE,
    DECISION_SUSTAINED,
    DISPATCHER,
    DURATION_LONG_CALL,
    DURATION_SHORT_CALL,
    ERR_NAMED_CALL_ALLOWANCE_EXCEEDED,
    EVENT_MAKE_WHOLE_CREDITED,
    EVENT_REGISTRATION_CREATED,
    GOOD_CAUSE_MEDICAL,
    GRIEVANCE_SUSTAINED,
    GROUP_1,
    LAYOFF_LACK_OF_WORK,
    PURGE_RETAINED,
    REFERRAL_KIND_NAMED_CALL,
    REFERRAL_REFUSED,
    REFUSALS_BEFORE_REMOVAL,
    REGISTRATION_REGISTERED,
    REGISTRATION_REMOVED,
    REMEDY_MAKE_WHOLE_HOURS,
    REMOVAL_ADMINISTRATIVE,
    RESIGN_INTERVAL_DAYS,
    RETENTION_DAYS,
    SHORT_CALL_MAX_DAYS,
    SLOT_APPRENTICE,
    SLOT_JOURNEYWORKER,
    STANDING_DELINQUENT,
    VARIANT_NOT_APPLICABLE,
    VARIANT_SHORT_CALL_INTERFILED,
    VARIANT_STRICT_GROUP_ORDER,
    assert_instant_equals,
    assert_instant_shape,
    expect_created,
    expect_error,
    expect_ok,
    factories as f,
    fixtures as fx,
    make_contractor_rep_headers,
    plus_days,
    plus_hours,
)

CLOCK = "2026-09-01T00:00:00.000Z"

# ─── Three windows derived from that one clock reading ────────────────────────

RENEWAL_DUE_AT = "2026-10-01T00:00:00.000Z"
LEDGER_RETENTION_UNTIL = "2031-08-31T00:00:00.000Z"
REFERRAL_DEADLINE = "2026-09-02T00:00:00.000Z"
TIMING_MEMBER = "Rhea Castellan"

# ─── The four kinds of ineligible registrant ─────────────────────────────────

RANKED_MEMBER = "Ana Weiss"
DELINQUENT_MEMBER = "Ben Halloran"
OUTSTANDING_MEMBER = "Cleo Nakata"
REMOVED_MEMBER = "Dara Mbeki"
APPRENTICE_MEMBER = "Eli Farkas"
RANKED_HOURS = 9000
DELINQUENT_HOURS = 9500
OUTSTANDING_HOURS = 9400
REMOVED_HOURS = 9300
APPRENTICE_HOURS = 4200
APPRENTICE_PERIOD = 2
# The delinquent registrant keeps their REGISTERED row and their 9,500 hours, so
# the one surviving candidate holds list ordinal 2 even though the pool holds
# only them.
RANKED_LIST_POSITION = 2
FIRST_JOB_SITE = "Unit 1"
SECOND_JOB_SITE = "Unit 2"
FIRST_REPORT_AT = "2026-09-25T07:00:00.000Z"
SECOND_REPORT_AT = "2026-10-15T07:00:00.000Z"

# ─── The five-day threshold ───────────────────────────────────────────────────

SHORT_DURATION_DAYS = 5
LONG_DURATION_DAYS = 6
THRESHOLD_HEADCOUNT = 6
NAMED_TARGET = "Named Target"
SHORT_JOB_SITE = "Five Day Tie-In"
LONG_JOB_SITE = "Six Day Tie-In"
SHORT_NAMED_JOB_SITE = "Five Day Named"
LONG_NAMED_JOB_SITE = "Six Day Named"

# ─── The strike count and its excluded refusals ──────────────────────────────

STRIKE_MEMBER = "Tova Lindqvist"
STRIKE_HOURS = 9000
LONG_CALL_DAYS = 20
LONG_A_JOB_SITE = "Long A"
SHORT_B_JOB_SITE = "Short B"
LONG_C_JOB_SITE = "Long C"
LONG_A_REPORT_AT = "2026-09-25T07:00:00.000Z"
SHORT_B_REPORT_AT = "2026-09-26T07:00:00.000Z"
LONG_C_REPORT_AT = "2026-09-27T07:00:00.000Z"

# ─── The variant stamped on each referral kind ───────────────────────────────

SENIOR_MEMBER = "Ula Berg"
JUNIOR_MEMBER = "Vic Amara"
SENIOR_HOURS = 9000
JUNIOR_HOURS = 8000
LIST_JOB_SITE = "Long L"
INTERFILED_JOB_SITE = "Short S"
NAMED_JOB_SITE = "Named N"
LIST_REPORT_AT = "2026-09-25T07:00:00.000Z"
INTERFILED_REPORT_AT = "2026-10-05T07:00:00.000Z"
NAMED_REPORT_AT = "2026-10-20T07:00:00.000Z"
NAMED_HEADCOUNT = 6

# ─── The apprentice wage factor on an actual-hours award ─────────────────────

AWARD_JOB_SITE = "Rack 12"
AWARD_REPORT_AT = "2026-09-10T07:00:00.000Z"
AWARD_DURATION_DAYS = 30
AWARD_RATE_CENTS = 5000
AWARD_HOURS = 80
AWARD_CENTS = 275000
JOURNEYWORKER_FACTOR_CENTS = 400000
GRIEVANCE_CLOCK = "2026-09-02T00:00:00.000Z"
AWARD_LAYOFF_CLOCK = "2026-09-20T07:00:00.000Z"
AWARD_JOURNEYWORKER = "Wren Adeyemi"
AWARD_APPRENTICE = "Zev Okafor"
AWARD_NARRATIVE = "Apprentice dispatched outside the ratio."
AWARD_NOTE = "Ratio breach confirmed."
RATE_CENTS = 5000


def _call(api, contractor_id, job_site, report_at, days=LONG_CALL_DAYS, **overrides):
    """One manpower request, long by default, with room for variation."""
    fields = {
        "job_site": job_site,
        "journeyworkers_requested": 1,
        "apprentices_requested": 0,
        "expected_duration_days": days,
        "report_at": report_at,
        "hourly_rate_cents": RATE_CENTS,
    }
    fields.update(overrides)
    return fx.open_job_request(api, contractor_id, **fields)


def _raw_call(api, contractor_id, job_site, report_at, days, **overrides):
    """The same intake left unwrapped, for the legs that expect a refusal."""
    fields = {
        "job_site": job_site,
        "journeyworkers_requested": THRESHOLD_HEADCOUNT,
        "apprentices_requested": 0,
        "expected_duration_days": days,
        "report_at": report_at,
        "hourly_rate_cents": RATE_CENTS,
    }
    fields.update(overrides)
    return api.create_job_request(
        f.job_request_payload(contractor_id, **fields),
        make_contractor_rep_headers(contractor_id),
    )


def _hall_with_one_member_and_a_call(api, full_name, hours):
    """The hall and one unregistered member, so signing the book is the trigger."""
    hall = fx.standard_hall(api, clock=CLOCK)
    member = fx.add_journeyworker(api, hall["home_local_id"], full_name, hours)
    contractor = fx.add_contractor(api)
    job_request = _call(api, contractor["id"], FIRST_JOB_SITE, FIRST_REPORT_AT)
    return {
        "hall": hall,
        "member": member,
        "contractor": contractor,
        "job_request": job_request,
    }


def _dispatch_order(api, job_request_id, slot_kind=SLOT_JOURNEYWORKER):
    return expect_ok(
        api.get_dispatch_order(job_request_id, DISPATCHER, {"slot_kind": slot_kind})
    )


class TestRegistrationTimingWindows:
    """Three horizons, one clock reading, and twenty-four-hour day arithmetic."""

    def test_the_renewal_deadline_is_thirty_days_from_the_signature(self, api):
        """
        PRD §3.3: "In either case `last_renewed_at` is set to the current instant and is
        never inherited from a predecessor, and `renewal_due_at` is computed as
        `last_renewed_at` plus 30 days."

        Design: Corner/calculations/registration_timing_windows_compute_renewal_deadline_and_retention
        """
        scene = _hall_with_one_member_and_a_call(api, TIMING_MEMBER, RANKED_HOURS)

        registration = fx.sign_book(
            api, scene["member"]["id"], scene["hall"]["group_1_id"]
        )

        assert_instant_equals(registration["registered_at"], CLOCK)
        assert_instant_equals(registration["last_renewed_at"], CLOCK)
        assert_instant_equals(
            registration["renewal_due_at"], plus_days(CLOCK, RESIGN_INTERVAL_DAYS)
        )
        assert_instant_equals(registration["renewal_due_at"], RENEWAL_DUE_AT)

    def test_the_ledger_row_carries_an_1825_day_retention_horizon(self, api):
        """
        PRD §2.10: "Each entry's `retention_until` is its `recorded_at` plus 1,825 days,
        and its `purge_state` is `RETAINED` until the housekeeping sweep flips it to
        `PURGED` and clears `snapshot_json` to null."

        Design: Corner/calculations/registration_timing_windows_compute_renewal_deadline_and_retention
        """
        scene = _hall_with_one_member_and_a_call(api, TIMING_MEMBER, RANKED_HOURS)
        fx.sign_book(api, scene["member"]["id"], scene["hall"]["group_1_id"])

        rows = fx.ledger_rows(
            api,
            member_id=scene["member"]["id"],
            event_code=EVENT_REGISTRATION_CREATED,
        )

        assert len(rows) == 1
        entry = rows[0]
        assert entry["purge_state"] == PURGE_RETAINED
        assert entry["referral_id"] is None
        assert_instant_equals(entry["recorded_at"], CLOCK)
        assert_instant_equals(
            entry["retention_until"], plus_days(CLOCK, RETENTION_DAYS)
        )
        assert_instant_equals(entry["retention_until"], LEDGER_RETENTION_UNTIL)

    def test_the_acceptance_deadline_is_twenty_four_hours_from_issuance(self, api):
        """
        PRD §3.6: "A successful issuance creates a `Referral` in `ISSUED` status against
        the request named in `job_request_id`, recording the chosen `registration_id`,
        the `member_id` denormalized from that registration so record-retention lookups
        survive the registration's later removal, `issued_at` as the current instant,
        `acceptance_deadline` as `issued_at` plus 24 hours, `issued_by_user_id` as the
        dispatcher's `X-User-ID`, `list_position_at_issue` as a snapshot of the selected
        registration's `position_number` at that moment, and `variant_applied` as the
        variant that produced the ranking."

        PRD §2.5: "All instants are ISO 8601 UTC with three fractional digits, all
        comparisons are exact to the millisecond, and all day-denominated durations in
        this document are exact multiples of twenty-four hours."

        Design: Corner/calculations/registration_timing_windows_compute_renewal_deadline_and_retention
        """
        scene = _hall_with_one_member_and_a_call(api, TIMING_MEMBER, RANKED_HOURS)
        registration = fx.sign_book(
            api, scene["member"]["id"], scene["hall"]["group_1_id"]
        )

        referral = fx.issue_referral(
            api, scene["job_request"]["id"], slot_kind=SLOT_JOURNEYWORKER
        )

        assert_instant_equals(referral["issued_at"], CLOCK)
        assert_instant_equals(
            referral["acceptance_deadline"], plus_hours(CLOCK, ACCEPTANCE_WINDOW_HOURS)
        )
        assert_instant_equals(referral["acceptance_deadline"], REFERRAL_DEADLINE)
        for instant in (
            registration["renewal_due_at"],
            referral["issued_at"],
            referral["acceptance_deadline"],
        ):
            assert_instant_shape(instant)


def _four_kinds_of_ineligible_registrant(api):
    """
    Five registrants on one book, four of whom the candidate filter must drop: a
    delinquent member, one already holding an outstanding referral, one whose
    registration has been removed, and an apprentice on a journeyworker slot.
    """
    hall = fx.standard_hall(api, clock=CLOCK)
    people = {}
    registrations = {}
    for full_name, hours in (
        (RANKED_MEMBER, RANKED_HOURS),
        (DELINQUENT_MEMBER, DELINQUENT_HOURS),
        (OUTSTANDING_MEMBER, OUTSTANDING_HOURS),
        (REMOVED_MEMBER, REMOVED_HOURS),
    ):
        people[full_name] = fx.add_journeyworker(
            api, hall["home_local_id"], full_name, hours
        )
        registrations[full_name] = fx.sign_book(
            api, people[full_name]["id"], hall["group_1_id"]
        )
    people[APPRENTICE_MEMBER] = fx.add_apprentice(
        api,
        hall["home_local_id"],
        APPRENTICE_MEMBER,
        period=APPRENTICE_PERIOD,
        hours=APPRENTICE_HOURS,
    )
    registrations[APPRENTICE_MEMBER] = fx.sign_book(
        api, people[APPRENTICE_MEMBER]["id"], hall["group_1_id"]
    )

    delinquent = fx.set_standing(
        api, people[DELINQUENT_MEMBER]["id"], STANDING_DELINQUENT
    )
    contractor = fx.add_contractor(api)
    first_call = _call(api, contractor["id"], FIRST_JOB_SITE, FIRST_REPORT_AT)
    outstanding_referral = fx.issue_referral(
        api, first_call["id"], slot_kind=SLOT_JOURNEYWORKER
    )
    removed = expect_ok(
        api.remove_registration(
            registrations[REMOVED_MEMBER]["id"],
            f.removal_payload(REMOVAL_ADMINISTRATIVE),
            DISPATCHER,
        )
    )
    second_call = _call(api, contractor["id"], SECOND_JOB_SITE, SECOND_REPORT_AT)
    return {
        "hall": hall,
        "people": people,
        "registrations": registrations,
        "delinquent": delinquent,
        "outstanding_referral": outstanding_referral,
        "removed": removed,
        "second_call": second_call,
    }


class TestCandidateSetFiltering:
    """The pool keeps the one registrant nobody would have picked on hours."""

    def test_the_computed_pool_holds_the_lowest_seniority_registrant_alone(self, api):
        """
        PRD §3.2: "Ranks are one-based integer ordinals with no rounding, and every
        datetime comparison inside the ranking is exact to the millisecond. A
        `HallAdmin`, `Dispatcher`, or `BusinessManager` may inspect the computed pool for
        a job request's next open slot before committing to anything: supplying the
        `slot_kind` of interest returns the governing variant in `variant`, the size of
        the surviving pool in `candidate_count`, and a description of the top-ranked
        candidate in `top_registration_id`, `top_member_id`, `top_list_group_code`,
        `top_position_number`, and `top_credited_seniority_hours`."

        Design: Corner/calculations/dispatch_order_candidate_set_excludes_four_kinds_of_ineligible_registrant
        """
        scene = _four_kinds_of_ineligible_registrant(api)

        order = _dispatch_order(api, scene["second_call"]["id"])

        assert order["variant"] == VARIANT_STRICT_GROUP_ORDER
        assert order["candidate_count"] == 1
        assert order["top_member_id"] == scene["people"][RANKED_MEMBER]["id"]
        assert order["top_registration_id"] == scene["registrations"][RANKED_MEMBER]["id"]
        assert order["top_credited_seniority_hours"] == RANKED_HOURS
        assert order["top_list_group_code"] == GROUP_1

    def test_standing_and_an_outstanding_referral_each_drop_a_higher_registrant(
        self, api
    ):
        """
        PRD §3.2: "The member's `standing` is `GOOD_STANDING`."

        PRD §3.2: "No referral exists against that same registration whose `status` is
        `ISSUED` and whose `acceptance_deadline` is at or after the current instant."

        Design: Corner/calculations/dispatch_order_candidate_set_excludes_four_kinds_of_ineligible_registrant
        """
        scene = _four_kinds_of_ineligible_registrant(api)

        assert scene["delinquent"]["dispatch_eligible"] is False
        # The first issuance already skipped the highest-hours registrant, because
        # the delinquency had landed before the referral was cut.
        assert (
            scene["outstanding_referral"]["member_id"]
            == scene["people"][OUTSTANDING_MEMBER]["id"]
        )
        assert scene["outstanding_referral"]["member_id"] != (
            scene["people"][DELINQUENT_MEMBER]["id"]
        )

    def test_a_removed_registration_and_the_wrong_classification_are_never_candidates(
        self, api
    ):
        """
        PRD §3.2: "Registrations in `REFERRED`, `DISPATCHED_OUT`, `REMOVED`, or `EXPIRED`
        status are never candidates."

        PRD §3.2: "The registrant member's `classification` equals `JOURNEYWORKER` when
        the slot being filled is a journeyworker slot, and equals `APPRENTICE` when it is
        an apprentice slot."

        PRD §3.6: "`list_position_at_issue` as a snapshot of the selected
        registration's `position_number` at that moment"

        PRD §3.3: "Its `position_number` is the one-based rank of the registration
        within its own list among the rows whose `status` is `REGISTERED`, computed
        under the same intra-list key the strict-group-order variant uses"

        Design: Corner/calculations/dispatch_order_candidate_set_excludes_four_kinds_of_ineligible_registrant
        """
        scene = _four_kinds_of_ineligible_registrant(api)
        assert scene["removed"]["status"] == REGISTRATION_REMOVED
        assert scene["removed"]["removal_reason"] == REMOVAL_ADMINISTRATIVE
        assert (
            fx.read_member(api, scene["people"][APPRENTICE_MEMBER]["id"])[
                "classification"
            ]
            == CLASSIFICATION_APPRENTICE
        )
        # The candidate filter drops the delinquent registrant, but the list
        # ordinal does not: `position_number` ranks every REGISTERED row, so the
        # sole surviving candidate still sits behind the delinquent's 9,500 hours.
        before = fx.read_registration(
            api, scene["registrations"][RANKED_MEMBER]["id"]
        )
        assert before["position_number"] == RANKED_LIST_POSITION

        referral = fx.issue_referral(
            api, scene["second_call"]["id"], slot_kind=SLOT_JOURNEYWORKER
        )

        assert referral["member_id"] == scene["people"][RANKED_MEMBER]["id"]
        assert referral["registration_id"] == scene["registrations"][RANKED_MEMBER]["id"]
        assert referral["list_position_at_issue"] == before["position_number"]
        assert referral["list_position_at_issue"] == RANKED_LIST_POSITION


def _contractor_and_one_named_member(api):
    """A signatory contractor and one member the agreement lets it name by right."""
    hall = fx.standard_hall(api, clock=CLOCK)
    member = fx.add_journeyworker(api, hall["home_local_id"], NAMED_TARGET, SENIOR_HOURS)
    contractor = fx.add_contractor(api)
    return {"hall": hall, "member": member, "contractor": contractor}


class TestShortCallThresholdConstant:
    """Five days is a short call; six is not, and the allowance follows."""

    def test_a_five_day_call_is_short_and_grants_no_allowance(self, api):
        """
        PRD §3.5: "The computed `duration_type` is `SHORT_CALL` when
        `expected_duration_days` is 5 or fewer, and `LONG_CALL` otherwise."

        PRD §3.5: "The `named_call_allowance` is 0 for a short call."

        Design: Corner/calculations/short_call_threshold_constant_flips_duration_type_and_named_call_allowance
        """
        scene = _contractor_and_one_named_member(api)
        assert SHORT_DURATION_DAYS == SHORT_CALL_MAX_DAYS

        short_call = _call(
            api,
            scene["contractor"]["id"],
            SHORT_JOB_SITE,
            FIRST_REPORT_AT,
            days=SHORT_DURATION_DAYS,
            journeyworkers_requested=THRESHOLD_HEADCOUNT,
        )

        assert short_call["duration_type"] == DURATION_SHORT_CALL
        assert short_call["named_call_allowance"] == 0
        assert short_call["special_skill_allowance"] == 0
        assert short_call["required_skill_code"] is None

    def test_one_more_day_makes_it_long_and_grants_a_single_named_call(self, api):
        """
        PRD §3.5: "For a long call, take the total headcount requested —
        journeyworkers plus apprentices — divide it by 5 discarding any remainder, take
        the greater of that quotient and 1, and then take the lesser of the result and a
        hard ceiling of 4."

        Design: Corner/calculations/short_call_threshold_constant_flips_duration_type_and_named_call_allowance
        """
        scene = _contractor_and_one_named_member(api)

        long_call = _call(
            api,
            scene["contractor"]["id"],
            LONG_JOB_SITE,
            FIRST_REPORT_AT,
            days=LONG_DURATION_DAYS,
            journeyworkers_requested=THRESHOLD_HEADCOUNT,
        )

        assert long_call["duration_type"] == DURATION_LONG_CALL
        assert long_call["named_call_allowance"] == 1

    def test_the_same_named_call_is_refused_at_five_days_and_taken_at_six(self, api):
        """
        PRD §3.5: "First, if the number of entries in `named_call_member_ids` exceeds
        `named_call_allowance`, the intake is refused with
        `ERR_NAMED_CALL_ALLOWANCE_EXCEEDED`."

        Design: Corner/calculations/short_call_threshold_constant_flips_duration_type_and_named_call_allowance
        """
        scene = _contractor_and_one_named_member(api)
        named_ids = [scene["member"]["id"]]

        refused = _raw_call(
            api,
            scene["contractor"]["id"],
            SHORT_NAMED_JOB_SITE,
            FIRST_REPORT_AT,
            SHORT_DURATION_DAYS,
            named_call_member_ids=named_ids,
        )
        expect_error(refused, ERR_NAMED_CALL_ALLOWANCE_EXCEEDED)

        accepted = expect_created(
            _raw_call(
                api,
                scene["contractor"]["id"],
                LONG_NAMED_JOB_SITE,
                FIRST_REPORT_AT,
                LONG_DURATION_DAYS,
                named_call_member_ids=named_ids,
            )
        )

        assert accepted["duration_type"] == DURATION_LONG_CALL
        assert accepted["named_call_allowance"] == 1
        assert accepted["named_call_member_ids"] == named_ids


def _one_registrant_and_three_calls(api):
    """
    One registrant and three calls of the hall's two lengths, so successive
    refusals can be aimed at a long call or a short one on demand.
    """
    hall = fx.standard_hall(api, clock=CLOCK)
    member = fx.add_journeyworker(api, hall["home_local_id"], STRIKE_MEMBER, STRIKE_HOURS)
    registration = fx.sign_book(api, member["id"], hall["group_1_id"])
    contractor = fx.add_contractor(api)
    long_a = _call(api, contractor["id"], LONG_A_JOB_SITE, LONG_A_REPORT_AT)
    short_b = _call(
        api,
        contractor["id"],
        SHORT_B_JOB_SITE,
        SHORT_B_REPORT_AT,
        days=SHORT_DURATION_DAYS,
    )
    long_c = _call(api, contractor["id"], LONG_C_JOB_SITE, LONG_C_REPORT_AT)
    return {
        "hall": hall,
        "member": member,
        "registration": registration,
        "long_a": long_a,
        "short_b": short_b,
        "long_c": long_c,
    }


def _refuse(api, scene, job_request, good_cause=None):
    """Issue on the given call and have the sole registrant turn it down."""
    referral = fx.issue_referral(api, job_request["id"], slot_kind=SLOT_JOURNEYWORKER)
    return fx.refuse_referral(
        api, referral["id"], scene["member"]["id"], good_cause=good_cause
    )


class TestRefusalStrikeCountInputSet:
    """Two refusals that cost list position and still leave the strike count low."""

    def test_a_good_cause_refusal_on_a_long_call_charges_nothing_at_all(self, api):
        """
        PRD §3.7: "Count the referrals belonging to that member, across **all** of the
        member's registrations including registrations that have already gone terminal,
        where the referral either has `status` of `REFUSED` with a null
        `refusal_good_cause_code`, or has `status` of `EXPIRED`; where the referral's job
        request has `duration_type` of `LONG_CALL`; and where the referral's `issued_at`
        is at or after the current instant minus 365 days."

        Design: Corner/calculations/refusal_strike_count_ignores_good_cause_and_short_call_refusals
        """
        scene = _one_registrant_and_three_calls(api)
        assert scene["long_a"]["duration_type"] == DURATION_LONG_CALL

        refused = _refuse(api, scene, scene["long_a"], good_cause=GOOD_CAUSE_MEDICAL)

        assert refused["status"] == REFERRAL_REFUSED
        assert refused["refusal_good_cause_code"] == GOOD_CAUSE_MEDICAL
        assert fx.read_member(api, scene["member"]["id"])["refusal_strike_count"] == 0
        registration = fx.read_registration(api, scene["registration"]["id"])
        assert registration["demotion_count"] == 0
        assert registration["status"] == REGISTRATION_REGISTERED

    def test_a_bare_refusal_on_a_short_call_costs_position_but_not_a_strike(self, api):
        """
        PRD §3.7: "And **every short-call referral is excluded from the count entirely**
        — though a short-call no-cause refusal still increments `demotion_count`, so the
        member loses list position without accruing a strike."

        Design: Corner/calculations/refusal_strike_count_ignores_good_cause_and_short_call_refusals
        """
        scene = _one_registrant_and_three_calls(api)
        _refuse(api, scene, scene["long_a"], good_cause=GOOD_CAUSE_MEDICAL)
        assert scene["short_b"]["duration_type"] == DURATION_SHORT_CALL

        refused = _refuse(api, scene, scene["short_b"])

        assert refused["status"] == REFERRAL_REFUSED
        assert refused["refusal_good_cause_code"] is None
        assert fx.read_member(api, scene["member"]["id"])["refusal_strike_count"] == 0
        registration = fx.read_registration(api, scene["registration"]["id"])
        assert registration["demotion_count"] == 1
        assert registration["status"] == REGISTRATION_REGISTERED

    def test_only_the_bare_long_call_refusal_reaches_the_strike_count(self, api):
        """
        PRD §3.7: "Good-cause refusals never count. Withdrawn referrals never count."

        PRD §3.7: "This is the outcome whenever the member's strike count after the
        refusal stands at 1 or 2."

        Design: Corner/calculations/refusal_strike_count_ignores_good_cause_and_short_call_refusals
        """
        scene = _one_registrant_and_three_calls(api)
        _refuse(api, scene, scene["long_a"], good_cause=GOOD_CAUSE_MEDICAL)
        _refuse(api, scene, scene["short_b"])

        refused = _refuse(api, scene, scene["long_c"])

        assert refused["status"] == REFERRAL_REFUSED
        member = fx.read_member(api, scene["member"]["id"])
        assert member["refusal_strike_count"] == 1
        assert member["refusal_strike_count"] < REFUSALS_BEFORE_REMOVAL
        assert member["re_registration_eligible_at"] is None
        registration = fx.read_registration(api, scene["registration"]["id"])
        assert registration["demotion_count"] == 2
        assert registration["status"] == REGISTRATION_REGISTERED


def _two_registrants_and_three_kinds_of_call(api):
    """
    Two registrants on one seniority group, plus a long call, a short call, and a
    long call that names the junior registrant by right.
    """
    hall = fx.standard_hall(api, clock=CLOCK)
    senior = fx.add_journeyworker(api, hall["home_local_id"], SENIOR_MEMBER, SENIOR_HOURS)
    junior = fx.add_journeyworker(api, hall["home_local_id"], JUNIOR_MEMBER, JUNIOR_HOURS)
    senior_registration = fx.sign_book(api, senior["id"], hall["group_1_id"])
    junior_registration = fx.sign_book(api, junior["id"], hall["group_1_id"])
    contractor = fx.add_contractor(api)
    list_call = _call(api, contractor["id"], LIST_JOB_SITE, LIST_REPORT_AT)
    interfiled_call = _call(
        api,
        contractor["id"],
        INTERFILED_JOB_SITE,
        INTERFILED_REPORT_AT,
        days=SHORT_DURATION_DAYS,
    )
    named_call = _call(
        api,
        contractor["id"],
        NAMED_JOB_SITE,
        NAMED_REPORT_AT,
        journeyworkers_requested=NAMED_HEADCOUNT,
        named_call_member_ids=[junior["id"]],
    )
    return {
        "hall": hall,
        "senior": senior,
        "junior": junior,
        "senior_registration": senior_registration,
        "junior_registration": junior_registration,
        "named_call": named_call,
        "list_call": list_call,
        "interfiled_call": interfiled_call,
    }


class TestVariantAppliedPerReferralKind:
    """Three issuances against one book, each stamped with its own variant."""

    def test_a_long_list_order_referral_records_the_strict_group_variant(self, api):
        """
        PRD §3.2: "For a long call, the *strict group order* variant applies, and it sorts
        the surviving candidates by five components in this exact sequence: first by the
        list group's `priority_rank` ascending, so that every eligible rank-1 registrant
        outranks every rank-4 registrant regardless of when either signed"

        Design: Corner/calculations/variant_applied_is_recorded_per_referral_kind_and_duration
        """
        scene = _two_registrants_and_three_kinds_of_call(api)
        assert scene["list_call"]["duration_type"] == DURATION_LONG_CALL

        referral = fx.issue_referral(
            api, scene["list_call"]["id"], slot_kind=SLOT_JOURNEYWORKER
        )

        assert referral["variant_applied"] == VARIANT_STRICT_GROUP_ORDER
        assert referral["member_id"] == scene["senior"]["id"]
        assert referral["list_position_at_issue"] == 1
        assert referral["out_of_order_override"] is False

    def test_a_short_list_order_referral_records_the_interfiled_variant(self, api):
        """
        PRD §3.2: "For a short call, the *short-call interfiled* variant applies instead,
        and it deliberately discards both the group precedence and the group's
        `ordering_policy`."

        PRD §3.2: "Identical registration data therefore yields a different top-ranked
        registration under the two variants, and the variant that was actually used is
        stamped onto every referral as `variant_applied`, taking the value
        `STRICT_GROUP_ORDER` or `SHORT_CALL_INTERFILED`."

        Design: Corner/calculations/variant_applied_is_recorded_per_referral_kind_and_duration
        """
        scene = _two_registrants_and_three_kinds_of_call(api)
        fx.issue_referral(api, scene["list_call"]["id"], slot_kind=SLOT_JOURNEYWORKER)
        assert scene["interfiled_call"]["duration_type"] == DURATION_SHORT_CALL

        referral = fx.issue_referral(
            api, scene["interfiled_call"]["id"], slot_kind=SLOT_JOURNEYWORKER
        )

        assert referral["variant_applied"] == VARIANT_SHORT_CALL_INTERFILED
        assert referral["member_id"] == scene["junior"]["id"]
        assert referral["list_position_at_issue"] == 1

    def test_a_named_call_records_no_variant_and_no_list_position(self, api):
        """
        PRD §3.6: "A `NAMED_CALL` referral bypasses the ranking entirely and goes to the
        member the contractor named — which must be a member appearing in the request's
        `named_call_member_ids`, or the issuance is refused with
        `ERR_NAMED_CALL_NOT_DECLARED` — and records `variant_applied` as `NOT_APPLICABLE`
        with a null `list_position_at_issue`."

        Design: Corner/calculations/variant_applied_is_recorded_per_referral_kind_and_duration
        """
        scene = _two_registrants_and_three_kinds_of_call(api)
        assert scene["named_call"]["named_call_allowance"] == 1

        referral = fx.issue_referral(
            api,
            scene["named_call"]["id"],
            slot_kind=SLOT_JOURNEYWORKER,
            referral_kind=REFERRAL_KIND_NAMED_CALL,
            member_id=scene["junior"]["id"],
        )

        assert referral["variant_applied"] == VARIANT_NOT_APPLICABLE
        assert referral["member_id"] == scene["junior"]["id"]
        assert referral["list_position_at_issue"] is None
        assert referral["out_of_order_override"] is False


def _apprentice_laid_off_with_a_live_grievance(api):
    """
    One journeyworker and one apprentice on the same call, the apprentice off the
    job again by the time the manager takes up their ratio claim.
    """
    hall = fx.standard_hall(api, clock=CLOCK)
    journeyworker = fx.add_journeyworker(
        api, hall["home_local_id"], AWARD_JOURNEYWORKER, SENIOR_HOURS
    )
    apprentice = fx.add_apprentice(
        api,
        hall["home_local_id"],
        AWARD_APPRENTICE,
        period=APPRENTICE_PERIOD,
        hours=APPRENTICE_HOURS,
    )
    fx.sign_book(api, journeyworker["id"], hall["group_1_id"])
    fx.sign_book(api, apprentice["id"], hall["group_1_id"])
    contractor = fx.add_contractor(api)
    job_request = _call(
        api,
        contractor["id"],
        AWARD_JOB_SITE,
        AWARD_REPORT_AT,
        days=AWARD_DURATION_DAYS,
        journeyworkers_requested=1,
        apprentices_requested=1,
        hourly_rate_cents=AWARD_RATE_CENTS,
    )

    journeyworker_referral = fx.issue_referral(
        api, job_request["id"], slot_kind=SLOT_JOURNEYWORKER
    )
    fx.accept_referral(api, journeyworker_referral["id"], journeyworker["id"])
    apprentice_referral = fx.issue_referral(
        api, job_request["id"], slot_kind=SLOT_APPRENTICE
    )
    dispatch = fx.accept_referral(api, apprentice_referral["id"], apprentice["id"])

    fx.set_clock(api, GRIEVANCE_CLOCK)
    grievance = fx.grievance_under_review(
        api,
        apprentice_referral["id"],
        apprentice["id"],
        claim_type=CLAIM_RATIO_VIOLATION,
        narrative=AWARD_NARRATIVE,
    )

    fx.set_clock(api, AWARD_LAYOFF_CLOCK)
    laid_off = fx.lay_off(
        api, dispatch["id"], contractor["id"], AWARD_HOURS, LAYOFF_LACK_OF_WORK
    )
    return {
        "hall": hall,
        "journeyworker": journeyworker,
        "apprentice": apprentice,
        "job_request": fx.read_job_request(api, job_request["id"]),
        "apprentice_referral": apprentice_referral,
        "dispatch": dispatch,
        "grievance": grievance,
        "laid_off": laid_off,
    }


def _sustain_with_make_whole(api, grievance_id):
    return expect_ok(
        api.adjudicate_grievance(
            grievance_id,
            f.adjudication_payload(
                DECISION_SUSTAINED, REMEDY_MAKE_WHOLE_HOURS, note=AWARD_NOTE
            ),
            BUSINESS_MANAGER,
        )
    )


class TestApprenticeRateFactorConstant:
    """The period-two factor, not the full rate, prices the apprentice's award."""

    def test_the_award_is_scaled_by_the_period_two_basis_point_factor(self, api):
        """
        PRD §3.9: "First a wage factor is fixed from the grievant's own classification: a
        journeyworker is credited at the full 10,000 basis points of the job request's
        `hourly_rate_cents`, while an apprentice is credited at the basis-point factor for
        their `apprentice_period` — 5,625 basis points in period 1, 6,875 in period 2,
        8,125 in period 3, and 9,375 in period 4."

        PRD §3.9: "If the dispatch has already left `WORKING` — `LAID_OFF`,
        `TERMINATED_FOR_CAUSE`, or `QUIT` — the **actual-hours** variant applies and
        `back_pay_variant` records `ACTUAL_HOURS`."

        Design: Corner/calculations/apprentice_rate_factor_constant_scales_an_actual_hours_award
        """
        scene = _apprentice_laid_off_with_a_live_grievance(api)
        assert scene["job_request"]["max_apprentices_allowed"] == 1
        assert scene["laid_off"]["hours_worked"] == AWARD_HOURS
        factor = APPRENTICE_RATE_FACTOR_BP[APPRENTICE_PERIOD]

        decided = _sustain_with_make_whole(api, scene["grievance"]["id"])

        assert decided["status"] == GRIEVANCE_SUSTAINED
        assert decided["back_pay_variant"] == BACK_PAY_ACTUAL_HOURS
        assert decided["back_pay_hours"] == AWARD_HOURS
        assert decided["back_pay_amount_cents"] == (
            AWARD_HOURS * AWARD_RATE_CENTS * factor // BP_SCALE
        )
        assert decided["back_pay_amount_cents"] == AWARD_CENTS
        # A journeyworker grievant on the same call and the same hours would have
        # been credited at the full rate, which is a materially larger award.
        assert decided["back_pay_amount_cents"] != JOURNEYWORKER_FACTOR_CENTS

    def test_the_credited_award_is_written_to_the_dispatch_record(self, api):
        """
        PRD §3.9: "A `MAKE_WHOLE_CREDITED` ledger entry is appended with `hours_delta`
        equal to `back_pay_hours`."

        Design: Corner/calculations/apprentice_rate_factor_constant_scales_an_actual_hours_award
        """
        scene = _apprentice_laid_off_with_a_live_grievance(api)

        _sustain_with_make_whole(api, scene["grievance"]["id"])

        rows = fx.ledger_rows(
            api,
            member_id=scene["apprentice"]["id"],
            event_code=EVENT_MAKE_WHOLE_CREDITED,
        )
        assert len(rows) == 1
        assert rows[0]["hours_delta"] == AWARD_HOURS
        assert rows[0]["referral_id"] == scene["apprentice_referral"]["id"]
        assert_instant_equals(rows[0]["recorded_at"], AWARD_LAYOFF_CLOCK)
