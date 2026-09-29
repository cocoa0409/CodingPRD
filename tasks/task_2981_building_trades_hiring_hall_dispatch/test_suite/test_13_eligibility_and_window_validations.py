"""
Validation rows read at their own edges: the two clauses of one group-eligibility
check, the endorsement fields another entity owns, a filing window closed at its
last millisecond, a row that only runs when the payload invites it, and a ladder
whose first rung must answer before the second is even computed.
"""

from test_helpers import (
    BUSINESS_MANAGER,
    CLAIM_OUT_OF_ORDER_DISPATCH,
    DISPATCHER,
    ERR_APPRENTICE_RATIO_EXCEEDED,
    ERR_GRIEVANCE_WINDOW_EXPIRED,
    ERR_LIST_GROUP_NOT_ELIGIBLE,
    ERR_NO_ACTIVE_RATIO_POLICY,
    ERR_SKILL_ENDORSEMENT_MISSING,
    ERR_TRAVELER_NOT_RECIPROCAL,
    GRIEVANCE_FILED,
    GRIEVANCE_FILING_WINDOW_DAYS,
    HALL_ADMIN,
    POLICY_ACTIVE,
    REFERRAL_KIND_SPECIAL_SKILL,
    REGISTRATION_REGISTERED,
    SKILL_WELDING_6G,
    SLOT_JOURNEYWORKER,
    VARIANT_STRICT_GROUP_ORDER,
    assert_instant_equals,
    expect_created,
    expect_error,
    expect_ok,
    factories as f,
    fixtures as fx,
    make_member_headers,
    plus_days,
    validate_list,
)

CLOCK = "2026-09-01T00:00:00.000Z"

# ─── The two clauses of the group-eligibility row ─────────────────────────────

TRAVELER_MEMBER = "Pia Solis"
TRAVELER_HOURS = 5000
SHORT_HOURS_MEMBER = "Rex Doyle"
SHORT_HOURS = 3000
GROUP_ONE_FLOOR = 4000
SISTER_FACTOR_BP = 5000
RAW_CREDIT_HOURS = 600
ROUNDED_CREDIT_HOURS = 300
CREDITED_HOURS = 5300

# ─── The endorsement fields a special-skill referral consults ────────────────

UNVERIFIED_MEMBER = "Sam Iyer"
UNVERIFIED_HOURS = 9000
EXPIRED_MEMBER = "Tess Aluko"
EXPIRED_HOURS = 8500
ENDORSED_MEMBER = "Uma Petrov"
ENDORSED_HOURS = 8000
LAPSED_AT = "2026-08-01T00:00:00.000Z"
CERTIFIED_UNTIL = "2027-01-01T00:00:00.000Z"
SKILL_JOB_SITE = "Alloy Header"
SKILL_REPORT_AT = "2026-09-25T07:00:00.000Z"
SKILL_RATE_CENTS = 6000
SKILL_DURATION_DAYS = 30
SKILL_JOURNEYWORKERS = 2
SKILL_SLOTS_REQUESTED = 1

# ─── The filing window's last millisecond ─────────────────────────────────────

FIRST_GRIEVANT = "Vera Lang"
FIRST_GRIEVANT_HOURS = 9000
SECOND_GRIEVANT = "Wes Toure"
SECOND_GRIEVANT_HOURS = 8000
FILING_DEADLINE = "2026-09-11T00:00:00.000Z"
ONE_MILLISECOND_LATE = "2026-09-11T00:00:00.001Z"
GRIEVANCE_JOB_SITE = "Feedwater Skid"
GRIEVANCE_REPORT_AT = "2026-09-25T07:00:00.000Z"
GRIEVANCE_DURATION_DAYS = 20
GRIEVANCE_RATE_CENTS = 5000
GRIEVANCE_JOURNEYWORKERS = 2
IN_WINDOW_NARRATIVE = "Filed on the last day of the window."
LATE_NARRATIVE = "Filed one millisecond too late."

# ─── The reciprocity row that only runs when invited ─────────────────────────

LOCAL_MEMBER = "Xan Ferreira"
LOCAL_MEMBER_HOURS = 9000
ZERO_FACTOR_TRAVELER = "Yara Beck"
ZERO_FACTOR_TRAVELER_HOURS = 6000
ZERO_FACTOR_LOCAL_NUMBER = 99
ZERO_FACTOR_LOCAL_NAME = "Local 99 (no reciprocity)"
HOME_CREDIT_HOURS = 800

# ─── The ratio ladder's first rung ────────────────────────────────────────────

RATIO_JOURNEYWORKER = "Zola Marek"
RATIO_JOURNEYWORKER_HOURS = 9000
RATIO_APPRENTICE = "Ade Kovac"
RATIO_APPRENTICE_HOURS = 4200
RATIO_APPRENTICE_PERIOD = 1
FUTURE_POLICY_CODE = "FUTURE-2027"
FUTURE_EFFECTIVE_FROM = "2027-01-01T00:00:00.000Z"
LIVE_POLICY_CODE = "STD-2026"
LIVE_EFFECTIVE_FROM = "2026-01-01T00:00:00.000Z"
RATIO_JOB_SITE = "Rack 12"
RATIO_REPORT_AT = "2026-09-25T07:00:00.000Z"
RATIO_DURATION_DAYS = 30
RATIO_RATE_CENTS = 5000


def _sign(api, member_id, list_id, **overrides):
    """The registration attempt left unwrapped, so a refusal can be read."""
    return api.create_registration(
        f.registration_payload(member_id, list_id, **overrides), DISPATCHER
    )


def _registered_count(api, list_id):
    return fx.read_list_group(api, list_id)["registered_count"]


def _traveler_and_a_short_hours_local(api):
    """
    A rank-one group that refuses travelers and wants 4,000 hours, plus one
    member who fails only the traveler clause and one who fails only the hours.
    """
    fx.set_clock(api, CLOCK)
    home = fx.add_home_local(api)
    sister = fx.add_sister_local(api, reciprocity_factor_bp=SISTER_FACTOR_BP)
    group_one = fx.add_list_group(api, f.group_one_payload())
    traveler = fx.add_journeyworker(api, sister["id"], TRAVELER_MEMBER, TRAVELER_HOURS)
    local = fx.add_journeyworker(api, home["id"], SHORT_HOURS_MEMBER, SHORT_HOURS)
    return {
        "home": home,
        "sister": sister,
        "group_one": group_one,
        "traveler": traveler,
        "local": local,
    }


class TestGroupEligibilityHasTwoIndependentClauses:
    """One error code, two reasons, and neither attempt leaves a trace."""

    def test_hours_well_above_the_floor_do_not_admit_a_traveler(self, api):
        """
        PRD §3.3: "The member's `local_hours_in_trade` must be at least the group's
        `requires_local_hours`, and if the member's `is_traveler` is true the group's
        `accepts_travelers` must be true; failing either is `ERR_LIST_GROUP_NOT_ELIGIBLE`
        with HTTP 422."

        Design: Corner/validations/traveler_on_a_list_that_refuses_travelers_rejected
        """
        scene = _traveler_and_a_short_hours_local(api)
        assert scene["traveler"]["is_traveler"] is True
        assert scene["traveler"]["local_hours_in_trade"] == TRAVELER_HOURS
        assert TRAVELER_HOURS >= GROUP_ONE_FLOOR
        assert scene["group_one"]["accepts_travelers"] is False

        response = _sign(api, scene["traveler"]["id"], scene["group_one"]["id"])

        expect_error(response, ERR_LIST_GROUP_NOT_ELIGIBLE)

    def test_a_local_member_below_the_floor_fails_the_very_same_row(self, api):
        """
        PRD §3.2: "Its `requires_local_hours` sets the minimum `local_hours_in_trade` a
        member must have accumulated to sign that group, and its `accepts_travelers` flag
        decides whether a member whose `is_traveler` is true may sign it at all."

        Design: Corner/validations/traveler_on_a_list_that_refuses_travelers_rejected
        """
        scene = _traveler_and_a_short_hours_local(api)
        assert scene["local"]["is_traveler"] is False
        assert scene["group_one"]["requires_local_hours"] == GROUP_ONE_FLOOR

        response = _sign(api, scene["local"]["id"], scene["group_one"]["id"])

        expect_error(response, ERR_LIST_GROUP_NOT_ELIGIBLE)

    def test_neither_rejected_signature_was_written_to_the_book(self, api):
        """
        PRD §3.3: "Group eligibility is checked before anything is written."

        PRD §3.2: "A group's `registered_count` is computed as the number of
        registrations currently on it whose `status` is `REGISTERED`."

        Design: Corner/validations/traveler_on_a_list_that_refuses_travelers_rejected
        """
        scene = _traveler_and_a_short_hours_local(api)
        _sign(api, scene["traveler"]["id"], scene["group_one"]["id"])
        _sign(api, scene["local"]["id"], scene["group_one"]["id"])

        assert _registered_count(api, scene["group_one"]["id"]) == 0
        assert fx.registrations_on(api, scene["group_one"]["id"]) == []


def _both_groups_and_the_same_traveler(api):
    """The rejecting group and the traveler-admitting group, side by side."""
    scene = _traveler_and_a_short_hours_local(api)
    scene["group_four"] = fx.add_list_group(api, f.group_four_payload())
    return scene


class TestTravelerAdmittedOnTheTravelerList:
    """The identical member and payload pass once the target list allows them."""

    def test_the_same_signature_succeeds_on_the_traveler_admitting_group(self, api):
        """
        PRD §3.3: "The registration's `credited_seniority_hours` — the value the
        `SENIORITY` ordering policy sorts on — is then computed as follows: start from the
        member's `local_hours_in_trade`, which are hours under the home local's own
        agreement and are always credited in full; then walk the declared credits in the
        order they were supplied in the array, and for each one multiply its `raw_hours`
        by that sister local's `reciprocity_factor_bp`, divide by 10,000, and round the
        result half up to a whole hour; finally add those individually rounded per-entry
        results to the base."

        Design: Corner/validations/same_traveler_registers_successfully_on_the_traveler_list
        """
        scene = _both_groups_and_the_same_traveler(api)
        assert scene["group_four"]["accepts_travelers"] is True
        assert scene["group_four"]["requires_local_hours"] == 0

        registration = expect_created(
            api.create_registration(
                f.traveler_registration_payload(
                    scene["traveler"]["id"],
                    scene["group_four"]["id"],
                    [
                        f.reciprocity_credit(
                            scene["sister"]["id"], RAW_CREDIT_HOURS
                        )
                    ],
                ),
                make_member_headers(scene["traveler"]["id"]),
            )
        )

        assert registration["status"] == REGISTRATION_REGISTERED
        assert registration["position_number"] == 1
        assert registration["list_id"] == scene["group_four"]["id"]
        assert registration["credited_seniority_hours"] == (
            TRAVELER_HOURS + ROUNDED_CREDIT_HOURS
        )
        assert registration["credited_seniority_hours"] == CREDITED_HOURS

    def test_only_the_admitting_group_records_the_registration(self, api):
        """
        PRD §3.3: "The new registration's `position_number` is the preserved
        predecessor's ordinal when preservation applies, and otherwise the group's
        `registered_count` plus one — the tail of the queue. The group's
        `registered_count` is then incremented."

        Design: Corner/validations/same_traveler_registers_successfully_on_the_traveler_list
        """
        scene = _both_groups_and_the_same_traveler(api)
        fx.sign_book(
            api,
            scene["traveler"]["id"],
            scene["group_four"]["id"],
            headers=make_member_headers(scene["traveler"]["id"]),
            reciprocity_credits=[
                f.reciprocity_credit(scene["sister"]["id"], RAW_CREDIT_HOURS)
            ],
        )

        assert _registered_count(api, scene["group_four"]["id"]) == 1
        assert _registered_count(api, scene["group_one"]["id"]) == 0
        rows = fx.registrations_on(api, scene["group_four"]["id"])
        assert len(rows) == 1
        assert rows[0]["member_id"] == scene["traveler"]["id"]


def _three_welders_one_of_them_qualified(api):
    """
    Three registered journeyworkers in descending seniority, only the last of
    whom holds a verified, unexpired endorsement for the skill the call names.
    """
    hall = fx.standard_hall(api, clock=CLOCK)
    unverified = fx.add_journeyworker(
        api, hall["home_local_id"], UNVERIFIED_MEMBER, UNVERIFIED_HOURS
    )
    expired = fx.add_journeyworker(
        api, hall["home_local_id"], EXPIRED_MEMBER, EXPIRED_HOURS
    )
    endorsed = fx.add_journeyworker(
        api, hall["home_local_id"], ENDORSED_MEMBER, ENDORSED_HOURS
    )
    fx.add_endorsement(
        api,
        unverified["id"],
        skill_code=SKILL_WELDING_6G,
        certified_until=CERTIFIED_UNTIL,
        verified=False,
    )
    fx.add_endorsement(
        api,
        expired["id"],
        skill_code=SKILL_WELDING_6G,
        certified_until=LAPSED_AT,
        verified=True,
    )
    fx.add_endorsement(
        api,
        endorsed["id"],
        skill_code=SKILL_WELDING_6G,
        certified_until=CERTIFIED_UNTIL,
        verified=True,
    )
    for member in (unverified, expired, endorsed):
        fx.sign_book(api, member["id"], hall["group_1_id"])
    contractor = fx.add_contractor(api)
    job_request = fx.open_job_request(
        api,
        contractor["id"],
        job_site=SKILL_JOB_SITE,
        journeyworkers_requested=SKILL_JOURNEYWORKERS,
        apprentices_requested=0,
        expected_duration_days=SKILL_DURATION_DAYS,
        report_at=SKILL_REPORT_AT,
        hourly_rate_cents=SKILL_RATE_CENTS,
        required_skill_code=SKILL_WELDING_6G,
        special_skill_slots_requested=SKILL_SLOTS_REQUESTED,
    )
    return {
        "hall": hall,
        "unverified": unverified,
        "expired": expired,
        "endorsed": endorsed,
        "contractor": contractor,
        "job_request": job_request,
    }


def _special_skill_referral(api, job_request_id, member_id):
    """A special-skill issuance aimed at one named member, left unwrapped."""
    version = fx.job_request_version(api, job_request_id)
    return api.create_referral(
        job_request_id,
        f.special_skill_referral_payload(
            version, member_id=member_id, slot_kind=SLOT_JOURNEYWORKER
        ),
        DISPATCHER,
    )


class TestSpecialSkillReferralReadsAnotherEntitysFields:
    """Both endorsement fields have to hold, and seniority does not enter into it."""

    def test_an_unverified_endorsement_never_satisfies_the_slot(self, api):
        """
        PRD §3.1: "Its `verified` flag, which defaults to false, records whether the hall
        has physically sighted the certification card; an unverified endorsement never
        satisfies a special-skill referral no matter how current it is."

        PRD §3.5: "Otherwise it is half the journeyworkers requested rounded up —
        computed as the journeyworker count multiplied by 5,000 basis points and divided
        by 10,000 discarding the remainder, plus 1 when the journeyworker count is odd —
        and then capped at the journeyworker count itself."

        Design: Corner/validations/special_skill_referral_requires_a_verified_unexpired_endorsement
        """
        scene = _three_welders_one_of_them_qualified(api)
        assert scene["job_request"]["special_skill_allowance"] == SKILL_SLOTS_REQUESTED
        assert scene["job_request"]["required_skill_code"] == SKILL_WELDING_6G

        response = _special_skill_referral(
            api, scene["job_request"]["id"], scene["unverified"]["id"]
        )

        expect_error(response, ERR_SKILL_ENDORSEMENT_MISSING)

    def test_an_endorsement_that_lapsed_before_the_clock_is_no_endorsement(self, api):
        """
        PRD §3.1: "Its `certified_until` is the instant at which the certification lapses,
        and the endorsement counts only while the clock is strictly before that instant."

        Design: Corner/validations/special_skill_referral_requires_a_verified_unexpired_endorsement
        """
        scene = _three_welders_one_of_them_qualified(api)

        response = _special_skill_referral(
            api, scene["job_request"]["id"], scene["expired"]["id"]
        )

        expect_error(response, ERR_SKILL_ENDORSEMENT_MISSING)

    def test_the_endorsement_filter_and_not_seniority_picks_the_recipient(self, api):
        """
        PRD §3.2: "And when the referral being issued is a special-skill referral, the
        member must hold a skill endorsement whose `skill_code` equals the job request's
        `required_skill_code`, whose `verified` is true, and whose `certified_until` is
        strictly after the current instant."

        PRD §3.6: "A `SPECIAL_SKILL` referral goes to the top-ranked candidate in that
        same pool narrowed to members holding a verified, unexpired endorsement for the
        request's `required_skill_code`; a target without such an endorsement is refused
        with `ERR_SKILL_ENDORSEMENT_MISSING`."

        Design: Corner/validations/special_skill_referral_requires_a_verified_unexpired_endorsement
        """
        scene = _three_welders_one_of_them_qualified(api)
        assert ENDORSED_HOURS < EXPIRED_HOURS < UNVERIFIED_HOURS

        referral = expect_created(
            _special_skill_referral(
                api, scene["job_request"]["id"], scene["endorsed"]["id"]
            )
        )

        assert referral["member_id"] == scene["endorsed"]["id"]
        assert referral["referral_kind"] == REFERRAL_KIND_SPECIAL_SKILL
        assert referral["variant_applied"] == VARIANT_STRICT_GROUP_ORDER


def _two_referrals_issued_at_one_instant(api):
    """
    Two journeyworkers on one two-slot call, each holding a referral issued at
    the same instant, so both grievance windows close together.
    """
    hall = fx.standard_hall(api, clock=CLOCK)
    first = fx.add_journeyworker(
        api, hall["home_local_id"], FIRST_GRIEVANT, FIRST_GRIEVANT_HOURS
    )
    second = fx.add_journeyworker(
        api, hall["home_local_id"], SECOND_GRIEVANT, SECOND_GRIEVANT_HOURS
    )
    fx.sign_book(api, first["id"], hall["group_1_id"])
    fx.sign_book(api, second["id"], hall["group_1_id"])
    contractor = fx.add_contractor(api)
    job_request = fx.open_job_request(
        api,
        contractor["id"],
        job_site=GRIEVANCE_JOB_SITE,
        journeyworkers_requested=GRIEVANCE_JOURNEYWORKERS,
        apprentices_requested=0,
        expected_duration_days=GRIEVANCE_DURATION_DAYS,
        report_at=GRIEVANCE_REPORT_AT,
        hourly_rate_cents=GRIEVANCE_RATE_CENTS,
    )
    first_referral = fx.issue_referral(
        api, job_request["id"], slot_kind=SLOT_JOURNEYWORKER
    )
    second_referral = fx.issue_referral(
        api, job_request["id"], slot_kind=SLOT_JOURNEYWORKER
    )
    return {
        "first": first,
        "second": second,
        "job_request": job_request,
        "first_referral": first_referral,
        "second_referral": second_referral,
    }


def _file_grievance(api, referral_id, member_id, narrative):
    return api.create_grievance(
        f.grievance_payload(
            referral_id, claim_type=CLAIM_OUT_OF_ORDER_DISPATCH, narrative=narrative
        ),
        make_member_headers(member_id),
    )


class TestGrievanceFilingWindowClosesInclusive:
    """Ten days to the millisecond: the last instant is in, the next one is out."""

    def test_a_filing_at_the_exact_deadline_is_accepted(self, api):
        """
        PRD §3.9: "The grievance's `filed_at` is the current instant, and filing is only
        open while that instant is at or before the challenged referral's `issued_at` plus
        10 days; a later filing is refused with `ERR_GRIEVANCE_WINDOW_EXPIRED`."

        Design: Corner/validations/grievance_at_the_exact_filing_deadline_passes_and_one_millisecond_later_expires
        """
        scene = _two_referrals_issued_at_one_instant(api)
        assert_instant_equals(scene["first_referral"]["issued_at"], CLOCK)
        assert_instant_equals(scene["second_referral"]["issued_at"], CLOCK)
        assert_instant_equals(
            FILING_DEADLINE, plus_days(CLOCK, GRIEVANCE_FILING_WINDOW_DAYS)
        )
        fx.set_clock(api, FILING_DEADLINE)

        grievance = expect_created(
            _file_grievance(
                api,
                scene["first_referral"]["id"],
                scene["first"]["id"],
                IN_WINDOW_NARRATIVE,
            )
        )

        assert grievance["status"] == GRIEVANCE_FILED
        assert grievance["grievant_member_id"] == scene["first"]["id"]
        assert_instant_equals(grievance["filed_at"], FILING_DEADLINE)

    def test_one_millisecond_later_the_identical_filing_is_refused(self, api):
        """
        PRD §2.5: "**The grievance filing window** is open while the clock is at or before
        the challenged referral's `issued_at` plus 10 days."

        Design: Corner/validations/grievance_at_the_exact_filing_deadline_passes_and_one_millisecond_later_expires
        """
        scene = _two_referrals_issued_at_one_instant(api)
        fx.set_clock(api, ONE_MILLISECOND_LATE)

        response = _file_grievance(
            api, scene["second_referral"]["id"], scene["second"]["id"], LATE_NARRATIVE
        )

        expect_error(response, ERR_GRIEVANCE_WINDOW_EXPIRED)

    def test_only_the_in_window_grievance_is_on_the_hall_s_books(self, api):
        """
        PRD §3.9: "Grievances may be read individually and listed with filters on
        `referral_id`, `grievant_member_id`, `status`, and `claim_type`."

        Design: Corner/validations/grievance_at_the_exact_filing_deadline_passes_and_one_millisecond_later_expires
        """
        scene = _two_referrals_issued_at_one_instant(api)
        fx.set_clock(api, FILING_DEADLINE)
        expect_created(
            _file_grievance(
                api,
                scene["first_referral"]["id"],
                scene["first"]["id"],
                IN_WINDOW_NARRATIVE,
            )
        )
        fx.set_clock(api, ONE_MILLISECOND_LATE)
        _file_grievance(
            api, scene["second_referral"]["id"], scene["second"]["id"], LATE_NARRATIVE
        )

        rows, meta = validate_list(api.list_grievances(BUSINESS_MANAGER))

        assert meta["total_count"] == 1
        assert len(rows) == 1
        assert rows[0]["referral_id"] == scene["first_referral"]["id"]


def _two_sisters_two_lists_and_two_signers(api):
    """
    A hall with one reciprocal sister and one sister it has no agreement with,
    plus a local journeyworker and a traveler out of the non-reciprocal local.
    """
    fx.set_clock(api, CLOCK)
    home = fx.add_home_local(api)
    reciprocal_sister = fx.add_sister_local(api)
    zero_factor_sister = fx.add_sister_local(
        api,
        local_number=ZERO_FACTOR_LOCAL_NUMBER,
        name=ZERO_FACTOR_LOCAL_NAME,
        reciprocity_factor_bp=0,
    )
    group_one = fx.add_list_group(api, f.group_one_payload())
    group_four = fx.add_list_group(api, f.group_four_payload())
    local_member = fx.add_journeyworker(
        api, home["id"], LOCAL_MEMBER, LOCAL_MEMBER_HOURS
    )
    traveler = fx.add_journeyworker(
        api, zero_factor_sister["id"], ZERO_FACTOR_TRAVELER, ZERO_FACTOR_TRAVELER_HOURS
    )
    return {
        "home": home,
        "reciprocal_sister": reciprocal_sister,
        "zero_factor_sister": zero_factor_sister,
        "group_one": group_one,
        "group_four": group_four,
        "local_member": local_member,
        "traveler": traveler,
    }


class TestReciprocityRowRunsOnlyWhenTheConfigurationInvitesIt:
    """One row, three fates: a home-kind citation, a factorless home, and silence."""

    def test_a_credit_citing_a_home_kind_local_is_refused(self, api):
        """
        PRD §3.3: "Every cited local must have `kind` of `SISTER` and a
        `reciprocity_factor_bp` strictly greater than 0, and a traveler's own home local
        must likewise carry a non-zero reciprocity factor; a credit citing a home local,
        or a sister local with which the hall has no agreement, is refused with
        `ERR_TRAVELER_NOT_RECIPROCAL`."

        Design: Corner/validations/reciprocity_credit_is_only_validated_when_credits_are_supplied
        """
        scene = _two_sisters_two_lists_and_two_signers(api)
        assert scene["reciprocal_sister"]["reciprocity_factor_bp"] == SISTER_FACTOR_BP

        response = _sign(
            api,
            scene["local_member"]["id"],
            scene["group_one"]["id"],
            reciprocity_credits=[
                f.reciprocity_credit(scene["home"]["id"], HOME_CREDIT_HOURS)
            ],
        )

        expect_error(response, ERR_TRAVELER_NOT_RECIPROCAL)

    def test_a_traveler_out_of_a_factorless_local_is_refused_with_no_credits_at_all(
        self, api
    ):
        """
        PRD §3.3: "Every cited local must have `kind` of `SISTER` and a
        `reciprocity_factor_bp` strictly greater than 0, and a traveler's own home local
        must likewise carry a non-zero reciprocity factor; a credit citing a home local,
        or a sister local with which the hall has no agreement, is refused with
        `ERR_TRAVELER_NOT_RECIPROCAL`."

        Design: Corner/validations/reciprocity_credit_is_only_validated_when_credits_are_supplied
        """
        scene = _two_sisters_two_lists_and_two_signers(api)
        assert scene["traveler"]["is_traveler"] is True
        assert scene["group_four"]["accepts_travelers"] is True

        response = _sign(api, scene["traveler"]["id"], scene["group_four"]["id"])

        expect_error(response, ERR_TRAVELER_NOT_RECIPROCAL)

    def test_the_local_signing_without_a_credits_array_never_runs_the_row(self, api):
        """
        PRD §3.3: "A non-traveler may simply supply an empty array, in which case
        `credited_seniority_hours` equals `local_hours_in_trade` exactly."

        Design: Corner/validations/reciprocity_credit_is_only_validated_when_credits_are_supplied
        """
        scene = _two_sisters_two_lists_and_two_signers(api)

        registration = expect_created(
            _sign(api, scene["local_member"]["id"], scene["group_one"]["id"])
        )

        assert registration["status"] == REGISTRATION_REGISTERED
        assert registration["reciprocity_credits"] == []
        assert registration["credited_seniority_hours"] == LOCAL_MEMBER_HOURS


def _apprentice_call_with_no_schedule_in_force(api):
    """
    A one-journeyworker, one-apprentice call standing in a hall that has never
    published a ratio schedule, with both candidates already on the book.
    """
    hall = fx.standard_hall(api, clock=CLOCK, with_policy=False)
    journeyworker = fx.add_journeyworker(
        api, hall["home_local_id"], RATIO_JOURNEYWORKER, RATIO_JOURNEYWORKER_HOURS
    )
    apprentice = fx.add_apprentice(
        api,
        hall["home_local_id"],
        RATIO_APPRENTICE,
        RATIO_APPRENTICE_PERIOD,
        RATIO_APPRENTICE_HOURS,
    )
    fx.sign_book(api, journeyworker["id"], hall["group_1_id"])
    fx.sign_book(api, apprentice["id"], hall["group_1_id"])
    contractor = fx.add_contractor(api)
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
        "journeyworker": journeyworker,
        "apprentice": apprentice,
        "job_request": job_request,
    }


def _apprentice_issuance(api, job_request):
    """The apprentice-slot issuance, always pinned to the request's intake version."""
    return api.create_referral(
        job_request["id"],
        f.apprentice_referral_payload(job_request["version"]),
        DISPATCHER,
    )


class TestSchedulePickingRunsBeforeTheRatioCap:
    """Step one answers first: no schedule in force is a different refusal than a full cap."""

    def test_with_no_policy_row_at_all_the_schedule_step_refuses(self, api):
        """
        PRD §3.6: "**Step one** picks the policy: among policies whose `status` is
        `ACTIVE` and whose `effective_from` is at or before the current instant, rank by
        `effective_from` descending with `created_at` ascending as the tie-break, and take
        the first row. If no such row exists, the operation is refused with
        `ERR_NO_ACTIVE_RATIO_POLICY`."

        Design: Corner/validations/missing_ratio_policy_is_reported_before_the_ratio_cap_is_computed
        """
        scene = _apprentice_call_with_no_schedule_in_force(api)

        response = _apprentice_issuance(api, scene["job_request"])

        expect_error(response, ERR_NO_ACTIVE_RATIO_POLICY)

    def test_an_active_policy_dated_in_the_future_does_not_satisfy_step_one(self, api):
        """
        PRD §3.6: "A policy's `status` is `ACTIVE` on creation; publishing a new policy
        sets the `status` of any previously `ACTIVE` policy whose `effective_from` is
        earlier to `SUPERSEDED`."

        PRD §3.6: "**Step one** picks the policy: among policies whose `status` is
        `ACTIVE` and whose `effective_from` is at or before the current instant, rank by
        `effective_from` descending with `created_at` ascending as the tie-break, and take
        the first row."

        Design: Corner/validations/missing_ratio_policy_is_reported_before_the_ratio_cap_is_computed
        """
        scene = _apprentice_call_with_no_schedule_in_force(api)

        future = fx.add_ratio_policy(
            api,
            policy_code=FUTURE_POLICY_CODE,
            effective_from=FUTURE_EFFECTIVE_FROM,
        )

        assert future["status"] == POLICY_ACTIVE
        assert_instant_equals(future["effective_from"], FUTURE_EFFECTIVE_FROM)
        expect_error(
            _apprentice_issuance(api, scene["job_request"]),
            ERR_NO_ACTIVE_RATIO_POLICY,
        )

    def test_once_a_schedule_is_in_force_the_same_call_reaches_the_cap(self, api):
        """
        PRD §3.6: "**Step two** computes the cap, `max_apprentices_allowed`, from
        **accepted journeyworker referrals only**: count the referrals on the request
        whose `slot_kind` is `JOURNEYWORKER` and whose `status` is `ACCEPTED`; if that
        count is zero, the cap is zero; otherwise subtract the schedule's
        `first_apprentice_at_jw_count` from the count, floor the difference at zero,
        divide by `then_every_n_jw` discarding the remainder, and add one."

        PRD §3.6: "If the committed count plus one exceeds that limit, the operation is
        refused with `ERR_APPRENTICE_RATIO_EXCEEDED`."

        Design: Corner/validations/missing_ratio_policy_is_reported_before_the_ratio_cap_is_computed
        """
        scene = _apprentice_call_with_no_schedule_in_force(api)
        future = fx.add_ratio_policy(
            api, policy_code=FUTURE_POLICY_CODE, effective_from=FUTURE_EFFECTIVE_FROM
        )
        live = fx.add_ratio_policy(
            api, policy_code=LIVE_POLICY_CODE, effective_from=LIVE_EFFECTIVE_FROM
        )
        assert live["status"] == POLICY_ACTIVE
        still_active = expect_ok(api.get_ratio_policy(future["id"], HALL_ADMIN))
        assert still_active["status"] == POLICY_ACTIVE

        expect_error(
            _apprentice_issuance(api, scene["job_request"]),
            ERR_APPRENTICE_RATIO_EXCEEDED,
        )

        after = fx.read_job_request(api, scene["job_request"]["id"])
        assert after["max_apprentices_allowed"] == 0
        assert after["version"] == scene["job_request"]["version"]
        assert fx.referrals_on(api, scene["job_request"]["id"]) == []
