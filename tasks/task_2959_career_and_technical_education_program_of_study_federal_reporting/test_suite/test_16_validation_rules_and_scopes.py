"""Validation rules, their declared order, and the scope of each unique key.

Every test here drives the public API only, against an empty database whose
logical clock starts at its startup default, and asserts an outcome the PRD
derives uniquely.
"""

from test_helpers import (
    Builder,
    CteApiClient,
    STOP_DRAFT,
    STOP_STATE_APPROVED,
    assert_cents,
    assert_ledger,
    assert_pct,
    assert_quorum_figures,
    assert_rate,
    assert_version,
    errors,
    f,
    k,
    users,
    validate_error,
    validate_paginated,
    validate_unpaginated,
)

# The clock reading that sits exactly on the last obligable day of the window
# the tests below open, and the first reading past it.
LAST_OBLIGABLE_INSTANT = "2027-06-30T23:00:00Z"
FIRST_CLOSED_INSTANT = "2027-07-01T00:00:00Z"
WINDOW_START_DATE = "2026-08-01"
WINDOW_END_DATE = "2027-06-30"

ALLOCATION_CENTS = 5000000
CONSUMABLE_UNIT_COST_CENTS = 100000
CONSUMABLE_APPROVED_CENTS = 85000

EQUIPMENT_MEETING_INSTANT = "2026-08-14T16:00:00.000Z"

# A roster that seats only one EMPLOYER, so a full-attendance filing clears the
# headcount check and then fails the employer check.
EMPLOYER_LIGHT_ROSTER = (
    ("Rosa Vega", k.SECTOR_EMPLOYER, "EMP-1", True),
    ("Iris Lund", k.SECTOR_POSTSECONDARY, "PSE-1", False),
    ("Owen Pike", k.SECTOR_LABOR, "LAB-1", False),
)


def _approved_program_with_award(build: Builder, cip_code: str, **grant_kwargs):
    """A STATE_APPROVED program of study and an OPEN award to charge it against."""
    scenario = build.program(cip_code, stop_at=STOP_STATE_APPROVED)
    grant = build.grant(allocation_cents=ALLOCATION_CENTS, **grant_kwargs)
    return scenario, grant


def _committee_with_equipment_meeting(build: Builder, cip_code: str, roster=None):
    """A chartered committee with a seated chair and one SCHEDULED meeting."""
    scenario = build.program(cip_code, stop_at=STOP_DRAFT)
    row = build.charter_committee(
        scenario.program_id, quorum_min_members=3, employer_seat_min=2
    )
    committee = (
        build.seat_roster(row["id"])
        if roster is None
        else build.seat_roster(row["id"], roster)
    )
    meeting = build.schedule_meeting(
        committee.committee_id,
        committee.chair_member_id,
        k.AGENDA_EQUIPMENT_REVIEW,
        EQUIPMENT_MEETING_INSTANT,
    )
    return committee, meeting["id"]


class TestGrantObligationWindowBounds:
    """Both ends of the obligation window are obligable days."""

    def test_certification_on_the_first_day_of_the_window_is_obligable(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §2.5: "Grant obligation windows and asset service periods are **closed** on both ends: `obligation_window_start` and `obligation_window_end` are both obligable days, and `service_period_start` and `service_period_end` are both days of possession."

        PRD §3.7: "The award must be inside its inclusive obligation window (`ERR_GRANT_WINDOW_CLOSED`)." — and "The approved amount of a line is its `gross_cents` multiplied by its `federal_share_pct`, rounded half-up to whole cents", where "`EQUIPMENT`, `CONSUMABLE` and `ADMINISTRATION` are each reimbursed at a share of 0.8500."

        Design: Corner/validations/grant_obligation_window_bounds_are_inclusive_and_the_day_after_is_refused
        """
        scenario, grant = _approved_program_with_award(
            build,
            "12.0508",
            obligation_window_start=WINDOW_START_DATE,
            obligation_window_end=WINDOW_END_DATE,
        )
        line = build.expenditure(
            grant.grant_id,
            scenario.program_id,
            k.CATEGORY_CONSUMABLE,
            CONSUMABLE_UNIT_COST_CENTS,
        )

        res = api.certify_allowability(
            line["id"],
            f.certification_payload(k.DECISION_CERTIFY),
            users.headers(users.FISCAL_OFFICER),
        )
        certified = validate_unpaginated(res, 200)
        assert certified["status"] == k.EXP_CERTIFIED
        assert_cents(
            certified["approved_cents"], CONSUMABLE_APPROVED_CENTS, "approved_cents"
        )
        assert_rate(certified["federal_share_pct"], 0.85, "federal_share_pct")

        award = validate_unpaginated(
            api.get_grant(grant.grant_id, users.headers(users.FISCAL_OFFICER))
        )
        assert_ledger(award, 85000, 0.0812, 6902, 91902, 4908098, 0)

    def test_certification_on_the_last_day_of_the_window_is_obligable(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §2.5: "Grant obligation windows and asset service periods are **closed** on both ends: `obligation_window_start` and `obligation_window_end` are both obligable days, and `service_period_start` and `service_period_end` are both days of possession."

        PRD §3.7: "The award must be inside its inclusive obligation window (`ERR_GRANT_WINDOW_CLOSED`)." — and "Step one computes `direct_obligated_cents` as the sum of `approved_cents` over the award's expenditures whose `status` is `CERTIFIED` or `OBLIGATED`", where "a direct total below 5,000,000 cents (fifty thousand dollars) takes the rate 0.0812".

        Design: Corner/validations/grant_obligation_window_bounds_are_inclusive_and_the_day_after_is_refused
        """
        scenario, grant = _approved_program_with_award(
            build,
            "12.0508",
            obligation_window_start=WINDOW_START_DATE,
            obligation_window_end=WINDOW_END_DATE,
        )
        first = build.expenditure(
            grant.grant_id,
            scenario.program_id,
            k.CATEGORY_CONSUMABLE,
            CONSUMABLE_UNIT_COST_CENTS,
        )
        second = build.expenditure(
            grant.grant_id,
            scenario.program_id,
            k.CATEGORY_CONSUMABLE,
            CONSUMABLE_UNIT_COST_CENTS,
        )
        build.certify(first["id"])
        build.set_clock(LAST_OBLIGABLE_INSTANT, users.FISCAL_OFFICER)

        res = api.certify_allowability(
            second["id"],
            f.certification_payload(k.DECISION_CERTIFY),
            users.headers(users.FISCAL_OFFICER),
        )
        certified = validate_unpaginated(res, 200)
        assert certified["status"] == k.EXP_CERTIFIED
        assert_cents(
            certified["approved_cents"], CONSUMABLE_APPROVED_CENTS, "approved_cents"
        )

        award = validate_unpaginated(
            api.get_grant(grant.grant_id, users.headers(users.FISCAL_OFFICER))
        )
        assert_ledger(award, 170000, 0.0812, 13804, 183804, 4816196, 0)

    def test_certification_one_day_past_the_window_end_is_refused(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §3.7: "The award must be inside its inclusive obligation window (`ERR_GRANT_WINDOW_CLOSED`)."

        PRD §2.5: "Grant obligation windows and asset service periods are **closed** on both ends: `obligation_window_start` and `obligation_window_end` are both obligable days, and `service_period_start` and `service_period_end` are both days of possession." — "Where a rule compares a calendar date against the clock, the clock's date component is used."

        Design: Corner/validations/grant_obligation_window_bounds_are_inclusive_and_the_day_after_is_refused
        """
        scenario, grant = _approved_program_with_award(
            build,
            "12.0508",
            obligation_window_start=WINDOW_START_DATE,
            obligation_window_end=WINDOW_END_DATE,
        )
        line = build.expenditure(
            grant.grant_id,
            scenario.program_id,
            k.CATEGORY_CONSUMABLE,
            CONSUMABLE_UNIT_COST_CENTS,
        )
        build.set_clock(FIRST_CLOSED_INSTANT, users.FISCAL_OFFICER)

        res = api.certify_allowability(
            line["id"],
            f.certification_payload(k.DECISION_CERTIFY),
            users.headers(users.FISCAL_OFFICER),
        )
        validate_error(res, errors.ERR_GRANT_WINDOW_CLOSED)

    def test_a_closed_window_refusal_leaves_the_ledger_and_the_line_untouched(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §3.7: "The award must be inside its inclusive obligation window (`ERR_GRANT_WINDOW_CLOSED`)." — "An accepted certification writes `federal_share_pct` and `approved_cents`, records `certified_by_user_id` from the acting `X-User-ID`, rebuilds the whole award ledger, and increments the `version` of both the expenditure and the award."

        PRD §3.7: "The stored row takes its `grant_award_id` from the addressed award, records `requested_by_user_id` from the acting `X-User-ID`, opens in `status` `REQUESTED`, computes `gross_cents` as `unit_cost_cents` multiplied by `quantity`, sets `federal_share_pct` from the category table below, leaves `approved_cents` null until certification".

        Design: Corner/validations/grant_obligation_window_bounds_are_inclusive_and_the_day_after_is_refused
        """
        scenario, grant = _approved_program_with_award(
            build,
            "12.0508",
            obligation_window_start=WINDOW_START_DATE,
            obligation_window_end=WINDOW_END_DATE,
        )
        first = build.expenditure(
            grant.grant_id,
            scenario.program_id,
            k.CATEGORY_CONSUMABLE,
            CONSUMABLE_UNIT_COST_CENTS,
        )
        second = build.expenditure(
            grant.grant_id,
            scenario.program_id,
            k.CATEGORY_CONSUMABLE,
            CONSUMABLE_UNIT_COST_CENTS,
        )
        build.certify(first["id"])
        build.set_clock(FIRST_CLOSED_INSTANT, users.FISCAL_OFFICER)

        refused = api.certify_allowability(
            second["id"],
            f.certification_payload(k.DECISION_CERTIFY),
            users.headers(users.FISCAL_OFFICER),
        )
        validate_error(refused, errors.ERR_GRANT_WINDOW_CLOSED)

        award = validate_unpaginated(
            api.get_grant(grant.grant_id, users.headers(users.FISCAL_OFFICER))
        )
        assert_ledger(award, 85000, 0.0812, 6902, 91902, 4908098, 0)

        stalled = validate_unpaginated(
            api.get_expenditure(second["id"], users.headers(users.FISCAL_OFFICER))
        )
        assert stalled["status"] == k.EXP_REQUESTED
        assert stalled["approved_cents"] is None


class TestAdministrativeCostCap:
    """The cap is tested against the award's running administrative total."""

    def test_the_first_administration_line_fits_under_the_cap(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §3.7: "An `ADMINISTRATION` line must fit under the administrative cost cap: the award's `admin_obligated_cents` plus this line's `approved_cents` may not exceed `admin_cap_cents`, and a breach is `ERR_ADMIN_CAP_EXCEEDED`."

        PRD §3.7: "A new award opens in `status` `OPEN` with `direct_obligated_cents`, `indirect_pool_cents`, `obligated_cents` and `admin_obligated_cents` all 0, `remaining_cents` equal to the full `allocation_cents`, `indirect_rate` at the tier that applies to a direct total of zero, and `admin_cap_cents` set to the allocation multiplied by five percent, rounded half-up to whole cents."

        Design: Corner/validations/admin_cap_is_evaluated_against_the_running_admin_total_not_the_single_line
        """
        scenario, grant = _approved_program_with_award(build, "52.0201")
        first = build.expenditure(
            grant.grant_id, scenario.program_id, k.CATEGORY_ADMINISTRATION, 200000
        )

        res = api.certify_allowability(
            first["id"],
            f.certification_payload(k.DECISION_CERTIFY),
            users.headers(users.FISCAL_OFFICER),
        )
        certified = validate_unpaginated(res, 200)
        assert certified["status"] == k.EXP_CERTIFIED
        assert_cents(certified["approved_cents"], 170000, "approved_cents")

        award = validate_unpaginated(
            api.get_grant(grant.grant_id, users.headers(users.FISCAL_OFFICER))
        )
        assert_cents(award["admin_cap_cents"], 250000, "admin_cap_cents")
        assert_ledger(award, 170000, 0.0812, 13804, 183804, 4816196, 170000)

    def test_a_second_line_that_fits_alone_but_not_cumulatively_is_refused(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §3.7: "An `ADMINISTRATION` line must fit under the administrative cost cap: the award's `admin_obligated_cents` plus this line's `approved_cents` may not exceed `admin_cap_cents`, and a breach is `ERR_ADMIN_CAP_EXCEEDED`."

        PRD §3.7: "Step six rebuilds the administrative sub-ledger with the same input-set discipline: `admin_obligated_cents` is the sum of `approved_cents` over the award's expenditures whose `category` is `ADMINISTRATION` and whose `status` is `CERTIFIED` or `OBLIGATED`, and `admin_cap_cents` is `allocation_cents` multiplied by five percent, rounded half-up to whole cents."

        Design: Corner/validations/admin_cap_is_evaluated_against_the_running_admin_total_not_the_single_line
        """
        scenario, grant = _approved_program_with_award(build, "52.0201")
        first = build.expenditure(
            grant.grant_id, scenario.program_id, k.CATEGORY_ADMINISTRATION, 200000
        )
        second = build.expenditure(
            grant.grant_id, scenario.program_id, k.CATEGORY_ADMINISTRATION, 100000
        )
        build.certify(first["id"])

        res = api.certify_allowability(
            second["id"],
            f.certification_payload(k.DECISION_CERTIFY),
            users.headers(users.FISCAL_OFFICER),
        )
        validate_error(res, errors.ERR_ADMIN_CAP_EXCEEDED)

    def test_a_cap_breach_leaves_the_sub_ledger_and_the_line_untouched(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §3.7: "An `ADMINISTRATION` line must fit under the administrative cost cap: the award's `admin_obligated_cents` plus this line's `approved_cents` may not exceed `admin_cap_cents`, and a breach is `ERR_ADMIN_CAP_EXCEEDED`."

        PRD §3.7: "The stored row takes its `grant_award_id` from the addressed award, records `requested_by_user_id` from the acting `X-User-ID`, opens in `status` `REQUESTED`, computes `gross_cents` as `unit_cost_cents` multiplied by `quantity`, sets `federal_share_pct` from the category table below, leaves `approved_cents` null until certification".

        Design: Corner/validations/admin_cap_is_evaluated_against_the_running_admin_total_not_the_single_line
        """
        scenario, grant = _approved_program_with_award(build, "52.0201")
        first = build.expenditure(
            grant.grant_id, scenario.program_id, k.CATEGORY_ADMINISTRATION, 200000
        )
        second = build.expenditure(
            grant.grant_id, scenario.program_id, k.CATEGORY_ADMINISTRATION, 100000
        )
        build.certify(first["id"])

        refused = api.certify_allowability(
            second["id"],
            f.certification_payload(k.DECISION_CERTIFY),
            users.headers(users.FISCAL_OFFICER),
        )
        validate_error(refused, errors.ERR_ADMIN_CAP_EXCEEDED)

        award = validate_unpaginated(
            api.get_grant(grant.grant_id, users.headers(users.FISCAL_OFFICER))
        )
        assert_ledger(award, 170000, 0.0812, 13804, 183804, 4816196, 170000)

        stalled = validate_unpaginated(
            api.get_expenditure(second["id"], users.headers(users.FISCAL_OFFICER))
        )
        assert stalled["status"] == k.EXP_REQUESTED
        assert stalled["approved_cents"] is None

    def test_a_smaller_line_still_fits_after_the_breach(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §3.7: "An `ADMINISTRATION` line must fit under the administrative cost cap: the award's `admin_obligated_cents` plus this line's `approved_cents` may not exceed `admin_cap_cents`, and a breach is `ERR_ADMIN_CAP_EXCEEDED`."

        PRD §3.7: "Step four sets `obligated_cents` to `direct_obligated_cents` plus `indirect_pool_cents`. Step five sets `remaining_cents` to `allocation_cents` minus `obligated_cents`."

        Design: Corner/validations/admin_cap_is_evaluated_against_the_running_admin_total_not_the_single_line
        """
        scenario, grant = _approved_program_with_award(build, "52.0201")
        first = build.expenditure(
            grant.grant_id, scenario.program_id, k.CATEGORY_ADMINISTRATION, 200000
        )
        second = build.expenditure(
            grant.grant_id, scenario.program_id, k.CATEGORY_ADMINISTRATION, 100000
        )
        third = build.expenditure(
            grant.grant_id, scenario.program_id, k.CATEGORY_ADMINISTRATION, 90000
        )
        build.certify(first["id"])
        validate_error(
            api.certify_allowability(
                second["id"],
                f.certification_payload(k.DECISION_CERTIFY),
                users.headers(users.FISCAL_OFFICER),
            ),
            errors.ERR_ADMIN_CAP_EXCEEDED,
        )

        res = api.certify_allowability(
            third["id"],
            f.certification_payload(k.DECISION_CERTIFY),
            users.headers(users.FISCAL_OFFICER),
        )
        certified = validate_unpaginated(res, 200)
        assert certified["status"] == k.EXP_CERTIFIED
        assert_cents(certified["approved_cents"], 76500, "approved_cents")

        award = validate_unpaginated(
            api.get_grant(grant.grant_id, users.headers(users.FISCAL_OFFICER))
        )
        assert_ledger(award, 246500, 0.0812, 20016, 266516, 4733484, 246500)


class TestQuorumFailureOrdering:
    """Headcount is answered first, then the employer seats, then the tallies."""

    def test_a_short_handed_meeting_with_an_impossible_tally_reports_the_headcount(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §3.3: "The three failure modes report separately and in this order: a headcount below `quorum_min_members` is `ERR_QUORUM_NOT_MET`; then an employer shortfall — either too few employers against `employer_seat_min` or employers holding strictly less than half the eligible attendance — is `ERR_EMPLOYER_SEAT_SHORTFALL`; then `vote_yes` plus `vote_no` exceeding `eligible_attendee_count` is `ERR_VOTE_COUNT_EXCEEDS_ATTENDANCE`. Because the headcount check precedes the employer check, a meeting that is both short-handed and employer-poor reports the headcount failure."

        Design: Corner/validations/quorum_headcount_is_checked_before_employer_parity_and_vote_arithmetic
        """
        committee, meeting_id = _committee_with_equipment_meeting(build, "01.0101")

        res = api.file_minutes(
            meeting_id,
            f.minutes_payload(
                EQUIPMENT_MEETING_INSTANT,
                committee.member_ids[:2],
                vote_yes=5,
                vote_no=0,
            ),
            users.chair_headers(committee.chair_member_id),
        )
        validate_error(res, errors.ERR_QUORUM_NOT_MET)

    def test_a_refused_filing_leaves_the_meeting_scheduled_with_no_attendance(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §3.3: "a headcount below `quorum_min_members` is `ERR_QUORUM_NOT_MET`"

        PRD §3.3: "The new meeting begins with `minutes_status` `SCHEDULED`, an empty `attendee_member_ids` list, `vote_yes` and `vote_no` both at 0, `quorum_met` and `endorsement_passed` both false, and `held_at`, `minutes_url` and `amendment_reason` all null; scheduling increments the owning committee's `version`."

        Design: Corner/validations/quorum_headcount_is_checked_before_employer_parity_and_vote_arithmetic
        """
        committee, meeting_id = _committee_with_equipment_meeting(build, "01.0101")
        validate_error(
            api.file_minutes(
                meeting_id,
                f.minutes_payload(
                    EQUIPMENT_MEETING_INSTANT,
                    committee.member_ids[:2],
                    vote_yes=5,
                    vote_no=0,
                ),
                users.chair_headers(committee.chair_member_id),
            ),
            errors.ERR_QUORUM_NOT_MET,
        )

        meeting = validate_unpaginated(
            api.get_meeting(meeting_id, users.headers(users.DIRECTOR))
        )
        assert meeting["minutes_status"] == k.MINUTES_SCHEDULED
        assert meeting["attendee_member_ids"] == []
        assert meeting["vote_yes"] == 0
        assert meeting["vote_no"] == 0
        assert meeting["quorum_met"] is False
        assert meeting["endorsement_passed"] is False
        assert meeting["held_at"] is None
        assert meeting["minutes_url"] is None

    def test_a_full_house_short_of_employer_seats_reports_the_employer_shortfall(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §3.3: "The three failure modes report separately and in this order: a headcount below `quorum_min_members` is `ERR_QUORUM_NOT_MET`; then an employer shortfall — either too few employers against `employer_seat_min` or employers holding strictly less than half the eligible attendance — is `ERR_EMPLOYER_SEAT_SHORTFALL`; then `vote_yes` plus `vote_no` exceeding `eligible_attendee_count` is `ERR_VOTE_COUNT_EXCEEDS_ATTENDANCE`."

        PRD §3.3: "Quorum requires three things simultaneously: `eligible_attendee_count` at least `quorum_min_members`, `employer_attendee_count` at least `employer_seat_min`, and employer parity — twice `employer_attendee_count` at least `eligible_attendee_count`, meaning employers must hold at least half of the eligible attendance."

        Design: Corner/validations/quorum_headcount_is_checked_before_employer_parity_and_vote_arithmetic
        """
        committee, meeting_id = _committee_with_equipment_meeting(
            build, "01.0101", roster=EMPLOYER_LIGHT_ROSTER
        )

        res = api.file_minutes(
            meeting_id,
            f.minutes_payload(
                EQUIPMENT_MEETING_INSTANT,
                committee.member_ids,
                vote_yes=3,
                vote_no=0,
            ),
            users.chair_headers(committee.chair_member_id),
        )
        validate_error(res, errors.ERR_EMPLOYER_SEAT_SHORTFALL)

    def test_a_quorate_meeting_with_more_votes_than_attendees_reports_the_tally(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §3.3: "then `vote_yes` plus `vote_no` exceeding `eligible_attendee_count` is `ERR_VOTE_COUNT_EXCEEDS_ATTENDANCE`."

        PRD §3.3: "Quorum requires three things simultaneously: `eligible_attendee_count` at least `quorum_min_members`, `employer_attendee_count` at least `employer_seat_min`, and employer parity — twice `employer_attendee_count` at least `eligible_attendee_count`, meaning employers must hold at least half of the eligible attendance. The parity clause is inclusive, so employers holding exactly half satisfies it."

        Design: Corner/validations/quorum_headcount_is_checked_before_employer_parity_and_vote_arithmetic
        """
        committee, meeting_id = _committee_with_equipment_meeting(build, "01.0101")

        res = api.file_minutes(
            meeting_id,
            f.minutes_payload(
                EQUIPMENT_MEETING_INSTANT,
                committee.member_ids,
                vote_yes=4,
                vote_no=0,
            ),
            users.chair_headers(committee.chair_member_id),
        )
        validate_error(res, errors.ERR_VOTE_COUNT_EXCEEDS_ATTENDANCE)

    def test_a_filing_that_clears_all_three_checks_finalizes_the_minutes(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §3.3: "`eligible_attendee_count` is then the number of eligible attendees, and `employer_attendee_count` is the number of those whose `sector` is `EMPLOYER`."

        PRD §3.3: "A filing without an `amendment_reason` moves the meeting `SCHEDULED → FINALIZED`, writing `held_at`, `attendee_member_ids`, `vote_yes`, `vote_no` and `minutes_url` from the request and recomputing `eligible_attendee_count`, `employer_attendee_count`, `quorum_met` and `endorsement_passed`." — and "`endorsement_passed` is a stricter reading of the same figures: it is true only when `quorum_met` is true, `vote_yes` is strictly greater than `vote_no`, and `vote_yes` plus `vote_no` is no greater than `eligible_attendee_count`."

        Design: Corner/validations/quorum_headcount_is_checked_before_employer_parity_and_vote_arithmetic
        """
        committee, meeting_id = _committee_with_equipment_meeting(build, "01.0101")

        res = api.file_minutes(
            meeting_id,
            f.minutes_payload(
                EQUIPMENT_MEETING_INSTANT,
                committee.member_ids,
                vote_yes=3,
                vote_no=0,
            ),
            users.chair_headers(committee.chair_member_id),
        )
        meeting = validate_unpaginated(res, 200)
        assert meeting["minutes_status"] == k.MINUTES_FINALIZED
        assert_quorum_figures(
            meeting, eligible=3, employer=2, quorum_met=True, endorsement_passed=True
        )


def _two_programs_with_a_prerequisite_chain(build: Builder):
    """Program A carries a two-hop postsecondary chain; program B one secondary course."""
    first = build.program("11.0101", stop_at=STOP_DRAFT)
    opener = build.add_course(
        first.program_id,
        f.postsecondary_course("PSE-1", 1, 3.0, 3.0, True),
    )
    follower = build.add_course(
        first.program_id,
        f.postsecondary_course(
            "PSE-2", 2, 3.0, 3.0, True, prerequisite_course_id=opener["id"]
        ),
    )
    second = build.program("11.0201", stop_at=STOP_DRAFT)
    build.add_course(second.program_id, f.secondary_course("SEC-1", 1, 4.0))
    return first, opener, follower, second


class TestPrerequisiteIntegrityAndAcyclicity:
    """Integrity is answered before acyclicity, and both are enforced."""

    def test_the_chain_records_one_prerequisite_hop_per_course(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §3.1: "The server computes `depth_from_root`, the number of prerequisite hops from the course back to a course whose `prerequisite_course_id` is null, by walking the chain; a course that opens the sequence has `depth_from_root` 0."

        Design: Corner/validations/prerequisite_integrity_and_acyclicity_are_both_enforced
        """
        _, opener, follower, _ = _two_programs_with_a_prerequisite_chain(build)

        assert opener["prerequisite_course_id"] is None
        assert opener["depth_from_root"] == 0
        assert follower["prerequisite_course_id"] == opener["id"]
        assert follower["depth_from_root"] == 1

    def test_a_prerequisite_from_another_program_is_refused(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §3.1: "First, integrity: the named prerequisite must belong to the same program as the course being written, must not be the course itself, must not be a `POSTSECONDARY` course named by a `SECONDARY` course (a `POSTSECONDARY` course naming a `SECONDARY` prerequisite is entirely legal), and must sit at a `position` strictly earlier than the course's own. A breach of any of those four is `ERR_PREREQUISITE_INVALID`."

        Design: Corner/validations/prerequisite_integrity_and_acyclicity_are_both_enforced
        """
        _, opener, _, second = _two_programs_with_a_prerequisite_chain(build)

        res = api.create_course(
            second.program_id,
            f.secondary_course("SEC-2", 2, 4.0, prerequisite_course_id=opener["id"]),
            users.headers(users.DIRECTOR),
        )
        validate_error(res, errors.ERR_PREREQUISITE_INVALID)

    def test_a_course_naming_itself_reports_the_integrity_breach(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §3.1: "the named prerequisite must belong to the same program as the course being written, must not be the course itself" and "A breach of any of those four is `ERR_PREREQUISITE_INVALID`. Second, acyclicity: following `prerequisite_course_id` onwards from the written course must reach a course with a null `prerequisite_course_id` without revisiting any course already on the walk, and a revisit is `ERR_PREREQUISITE_CYCLE`. Integrity is checked before acyclicity, so a self-reference reports the integrity breach."

        Design: Corner/validations/prerequisite_integrity_and_acyclicity_are_both_enforced
        """
        _, _, follower, _ = _two_programs_with_a_prerequisite_chain(build)

        res = api.patch_course(
            follower["id"],
            f.course_patch(prerequisite_course_id=follower["id"]),
            users.headers(users.DIRECTOR),
        )
        validate_error(res, errors.ERR_PREREQUISITE_INVALID)

    def test_a_secondary_course_may_not_name_a_postsecondary_prerequisite(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §3.1: "the named prerequisite" and "must not be a `POSTSECONDARY` course named by a `SECONDARY` course (a `POSTSECONDARY` course naming a `SECONDARY` prerequisite is entirely legal), and must sit at a `position` strictly earlier than the course's own. A breach of any of those four is `ERR_PREREQUISITE_INVALID`."

        Design: Corner/validations/prerequisite_integrity_and_acyclicity_are_both_enforced
        """
        first, _, follower, _ = _two_programs_with_a_prerequisite_chain(build)

        res = api.create_course(
            first.program_id,
            f.secondary_course("SEC-3", 3, 4.0, prerequisite_course_id=follower["id"]),
            users.headers(users.DIRECTOR),
        )
        validate_error(res, errors.ERR_PREREQUISITE_INVALID)

    def test_a_prerequisite_that_is_not_strictly_earlier_is_refused(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §3.1: "the named prerequisite" and "must sit at a `position` strictly earlier than the course's own. A breach of any of those four is `ERR_PREREQUISITE_INVALID`."

        PRD §3.1: "Revising a course accepts any subset of `status`, `credit_hours`, `articulated_credit_hours`, `articulation_verified`, `prerequisite_course_id` and `position`, and is subject to the same two prerequisite rules."

        Design: Corner/validations/prerequisite_integrity_and_acyclicity_are_both_enforced
        """
        _, opener, follower, _ = _two_programs_with_a_prerequisite_chain(build)

        res = api.patch_course(
            follower["id"],
            f.course_patch(position=1),
            users.headers(users.DIRECTOR),
        )
        validate_error(res, errors.ERR_PREREQUISITE_INVALID)

    def test_a_revision_that_would_close_the_chain_into_a_loop_is_refused(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §3.1: "Second, acyclicity: following `prerequisite_course_id` onwards from the written course must reach a course with a null `prerequisite_course_id` without revisiting any course already on the walk, and a revisit is `ERR_PREREQUISITE_CYCLE`."

        PRD §3.1: "Revising a course accepts any subset of `status`, `credit_hours`, `articulated_credit_hours`, `articulation_verified`, `prerequisite_course_id` and `position`, and is subject to the same two prerequisite rules."

        Design: Corner/validations/prerequisite_integrity_and_acyclicity_are_both_enforced
        """
        first, opener, follower, _ = _two_programs_with_a_prerequisite_chain(build)

        res = api.patch_course(
            opener["id"],
            f.course_patch(position=3, prerequisite_course_id=follower["id"]),
            users.headers(users.DIRECTOR),
        )
        validate_error(res, errors.ERR_PREREQUISITE_CYCLE)

        unchanged = validate_unpaginated(
            api.get_course(opener["id"], users.headers(users.DIRECTOR))
        )
        assert unchanged["position"] == 1
        assert unchanged["prerequisite_course_id"] is None
        assert unchanged["depth_from_root"] == 0

        courses, meta = validate_paginated(
            api.list_program_courses(
                first.program_id, users.headers(users.DIRECTOR)
            )
        )
        assert meta["total_count"] == 2


class TestDuplicateKeyScopes:
    """Each unique key is enforced over exactly the population it declares."""

    def test_a_repeated_cip_code_is_refused_across_the_district(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §3.1: "The `cip_code` must be unique across every program of study in the district — a collision is refused with `ERR_CIP_CODE_DUPLICATE`."

        Design: Corner/validations/duplicate_key_constraints_are_enforced_per_their_declared_scope
        """
        build.program("13.1319", stop_at=STOP_DRAFT)

        res = api.create_program(
            f.program_payload("13.1319", title="Second Program Of Study"),
            users.headers(users.DIRECTOR_TWO),
        )
        validate_error(res, errors.ERR_CIP_CODE_DUPLICATE)

    def test_a_repeated_course_code_is_refused_within_the_same_program(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §3.1: "Each `SequenceCourse` carries a `code` of 1 to 24 characters that must be unique among the courses of the same program (a repeat is `ERR_COURSE_CODE_DUPLICATE`), a `title`, a `segment` of either `SECONDARY` or `POSTSECONDARY`, a `position` from 1 through 8 fixing its ordinal place in the sequence, and `credit_hours` greater than zero at two decimal places."

        Design: Corner/validations/duplicate_key_constraints_are_enforced_per_their_declared_scope
        """
        scenario = build.program("13.1319", stop_at=STOP_DRAFT)
        build.add_course(scenario.program_id, f.secondary_course("ELT-1", 1, 4.0))

        res = api.create_course(
            scenario.program_id,
            f.secondary_course("ELT-1", 2, 3.0, title="Another Secondary Course"),
            users.headers(users.DIRECTOR),
        )
        validate_error(res, errors.ERR_COURSE_CODE_DUPLICATE)

    def test_the_same_course_code_is_accepted_under_a_second_program(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §3.1: "Each `SequenceCourse` carries a `code` of 1 to 24 characters that must be unique among the courses of the same program (a repeat is `ERR_COURSE_CODE_DUPLICATE`)"

        Design: Corner/validations/duplicate_key_constraints_are_enforced_per_their_declared_scope
        """
        first = build.program("13.1319", stop_at=STOP_DRAFT)
        second = build.program("13.1320", stop_at=STOP_DRAFT)
        build.add_course(first.program_id, f.secondary_course("ELT-1", 1, 4.0))

        res = api.create_course(
            second.program_id,
            f.secondary_course("ELT-1", 1, 4.0),
            users.headers(users.DIRECTOR),
        )
        twin = validate_unpaginated(res, 201)
        assert twin["code"] == "ELT-1"

        courses, meta = validate_paginated(
            api.list_program_courses(second.program_id, users.headers(users.DIRECTOR))
        )
        assert meta["total_count"] == 1
        assert courses[0]["id"] == twin["id"]

    def test_a_repeated_credential_code_is_refused_within_the_same_program(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §3.1: "A `Credential` carries a `code` of 1 to 32 characters unique within the program (a repeat is `ERR_CREDENTIAL_CODE_DUPLICATE`), a `title`, a `tier` of `STATE_RECOGNIZED`, `NATIONAL` or `LOCAL`, and an `exam_required` flag that defaults to true."

        Design: Corner/validations/duplicate_key_constraints_are_enforced_per_their_declared_scope
        """
        scenario = build.program("13.1319", stop_at=STOP_DRAFT)
        build.add_credential(scenario.program_id, "CERT-A")

        res = api.create_credential(
            scenario.program_id,
            f.credential_payload("CERT-A", title="Another Credential", tier=k.TIER_LOCAL),
            users.headers(users.DIRECTOR),
        )
        validate_error(res, errors.ERR_CREDENTIAL_CODE_DUPLICATE)

    def test_a_repeated_state_student_id_is_refused_within_the_same_program(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §3.6: "A `SchoolRegistrar` enrolls a student into a program with a `state_student_id` of exactly nine digits — unique among that program's students, a repeat being `ERR_STUDENT_ID_DUPLICATE` — a `cohort_year` between 2020 and 2035 naming the accountability cohort the student is reported under, and an optional `special_population_codes` list whose elements are drawn from `ECON_DISADV`, `IEP`, `EL`, `SINGLE_PARENT` and `NONTRADITIONAL` with no duplicates, defaulting to an empty list."

        Design: Corner/validations/duplicate_key_constraints_are_enforced_per_their_declared_scope
        """
        scenario = build.program("13.1319", stop_at=STOP_DRAFT)
        build.enroll(scenario.program_id, "100000001", cohort_year=2026)

        res = api.enroll_student(
            scenario.program_id,
            f.student_payload("100000001", 2027),
            users.headers(users.REGISTRAR),
        )
        validate_error(res, errors.ERR_STUDENT_ID_DUPLICATE)

    def test_the_same_state_student_id_is_accepted_under_a_second_program(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §3.6: "A `SchoolRegistrar` enrolls a student into a program with a `state_student_id` of exactly nine digits — unique among that program's students, a repeat being `ERR_STUDENT_ID_DUPLICATE`"

        Design: Corner/validations/duplicate_key_constraints_are_enforced_per_their_declared_scope
        """
        first = build.program("13.1319", stop_at=STOP_DRAFT)
        second = build.program("13.1320", stop_at=STOP_DRAFT)
        build.enroll(first.program_id, "100000001", cohort_year=2026)

        res = api.enroll_student(
            second.program_id,
            f.student_payload("100000001", 2026),
            users.headers(users.REGISTRAR),
        )
        twin = validate_unpaginated(res, 201)
        assert twin["state_student_id"] == "100000001"

        students, meta = validate_paginated(
            api.list_program_students(second.program_id, users.headers(users.REGISTRAR))
        )
        assert meta["total_count"] == 1
        assert students[0]["id"] == twin["id"]

    def test_a_repeated_fiscal_year_is_refused_across_all_awards(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §3.7: "A `GrantFiscalOfficer` records each year's federal award with a `fiscal_year` between 2020 and 2035 that must be unique across all awards (a repeat is `ERR_FISCAL_YEAR_DUPLICATE`), an `allocation_cents` total greater than zero, and an obligation window bounded by `obligation_window_start` and an `obligation_window_end` strictly after it."

        Design: Corner/validations/duplicate_key_constraints_are_enforced_per_their_declared_scope
        """
        build.grant(fiscal_year=2027, allocation_cents=ALLOCATION_CENTS)

        res = api.create_grant(
            f.grant_payload(2027, 9000000),
            users.headers(users.FISCAL_OFFICER_TWO),
        )
        validate_error(res, errors.ERR_FISCAL_YEAR_DUPLICATE)

    def test_a_repeated_indicator_code_and_reporting_year_is_refused_per_program(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §3.8: "The combination of program, `indicator_code` and `reporting_year` must be unique — a repeat is `ERR_INDICATOR_DUPLICATE`."

        Design: Corner/validations/duplicate_key_constraints_are_enforced_per_their_declared_scope
        """
        scenario = build.program("13.1319", stop_at=STOP_DRAFT)
        build.indicator(
            scenario.program_id,
            k.INDICATOR_4S1_CREDENTIAL,
            reporting_year=2027,
            baseline_pct=60.0,
            cohort_year=2026,
        )

        res = api.open_indicator(
            scenario.program_id,
            f.indicator_payload(k.INDICATOR_4S1_CREDENTIAL, 2027, 72.5, 2025),
            users.headers(users.REVIEWER_TWO),
        )
        validate_error(res, errors.ERR_INDICATOR_DUPLICATE)

    def test_a_second_chair_is_refused_on_a_committee_that_already_has_one(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §3.3: "Chairmanship is likewise exclusive — seating a member with `is_chair` true while the committee already has an `ACTIVE` member whose `is_chair` is true is refused with `ERR_CHAIR_ALREADY_SEATED`."

        Design: Corner/validations/duplicate_key_constraints_are_enforced_per_their_declared_scope
        """
        scenario = build.program("13.1319", stop_at=STOP_DRAFT)
        row = build.charter_committee(scenario.program_id)
        committee = build.seat_roster(row["id"])

        res = api.seat_member(
            committee.committee_id,
            f.member_payload("Nadia Okoro", k.SECTOR_EMPLOYER, "EMP-3", is_chair=True),
            users.headers(users.DIRECTOR),
        )
        validate_error(res, errors.ERR_CHAIR_ALREADY_SEATED)

        unchanged = validate_unpaginated(
            api.get_committee(committee.committee_id, users.headers(users.DIRECTOR))
        )
        assert unchanged["chair_member_id"] == committee.chair_member_id


NEGOTIATION_BASELINE_PCT = 85.00
#: Alternating offers, each by a party differing from the previous one in both
#: role and user id, spending the whole four-round budget.
FOUR_ROUND_EXCHANGE = (
    (95.00, users.REVIEWER),
    (86.00, users.DIRECTOR),
    (94.00, users.REVIEWER),
    (87.00, users.DIRECTOR),
)
FIFTH_OFFER_PCT = 93.00


def _indicator_at_the_budget_edge(build: Builder):
    """An indicator whose `negotiation_round` has reached the four-round budget."""
    scenario = build.program("14.0801", stop_at=STOP_DRAFT)
    indicator = build.indicator(
        scenario.program_id,
        k.INDICATOR_1S1_GRAD_RATE,
        reporting_year=2027,
        baseline_pct=NEGOTIATION_BASELINE_PCT,
        cohort_year=2026,
    )
    for offered_pct, actor in FOUR_ROUND_EXCHANGE:
        build.offer(indicator["id"], offered_pct, actor=actor)
    return indicator["id"]


def _arbitrated_indicator(api: CteApiClient, build: Builder) -> str:
    """An indicator driven one offer past the budget, so the fallback is binding."""
    indicator_id = _indicator_at_the_budget_edge(build)
    build.offer(indicator_id, FIFTH_OFFER_PCT, actor=users.REVIEWER)
    return indicator_id


class TestNegotiationBudget:
    """Four rounds of offers, then arbitration, then nothing further."""

    def test_the_state_opens_the_exchange_at_round_one(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §3.8: "The state opens the exchange: the first offer, tabled while `negotiation_round` is 0, moves the indicator `PROPOSED → NEGOTIATING`, and only a `StateComplianceReviewer` satisfies that opening edge — a director's attempt to open the exchange does not match any declared transition out of `PROPOSED` and is refused with `ERR_INVALID_INDICATOR_STATE`. The opening offer sets `negotiation_round` to 1, writes `last_offer_pct` from `offered_level_pct`, `last_offer_by_user_id` from the acting `X-User-ID`, and `last_offer_by_role` as `StateComplianceReviewer`."

        Design: Corner/validations/negotiation_budget_drives_arbitration_and_then_refuses_further_offers
        """
        scenario = build.program("14.0801", stop_at=STOP_DRAFT)
        indicator = build.indicator(
            scenario.program_id,
            k.INDICATOR_1S1_GRAD_RATE,
            reporting_year=2027,
            baseline_pct=NEGOTIATION_BASELINE_PCT,
            cohort_year=2026,
        )

        res = api.table_offer(
            indicator["id"],
            f.offer_payload(95.00, rationale="State opening position"),
            users.headers(users.REVIEWER),
        )
        opened = validate_unpaginated(res, 200)
        assert opened["status"] == k.PI_NEGOTIATING
        assert opened["negotiation_round"] == 1
        assert_pct(opened["last_offer_pct"], 95.00, "last_offer_pct")
        assert opened["last_offer_by_user_id"] == users.REVIEWER.user_id
        assert opened["last_offer_by_role"] == k.ROLE_STATE_COMPLIANCE_REVIEWER
        assert opened["negotiated_level_pct"] is None
        assert opened["met_threshold_pct"] is None

    def test_counter_offers_loop_while_the_round_stays_below_the_budget(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §3.8: "Thereafter each counter-offer loops `NEGOTIATING → NEGOTIATING` while `negotiation_round` is strictly below the four-round budget. Alternation is enforced twice over: the acting `X-User-Role` must differ from `last_offer_by_role` and the acting `X-User-ID` must differ from `last_offer_by_user_id`, and a party answering itself is refused with `ERR_SEGREGATION_OF_DUTIES`. Each accepted counter-offer increments `negotiation_round` by 1 and overwrites `last_offer_pct`, `last_offer_by_user_id` and `last_offer_by_role` with the new offer's values."

        Design: Corner/validations/negotiation_budget_drives_arbitration_and_then_refuses_further_offers
        """
        indicator_id = _indicator_at_the_budget_edge(build)

        standing = validate_unpaginated(
            api.get_indicator(indicator_id, users.headers(users.REVIEWER))
        )
        assert standing["status"] == k.PI_NEGOTIATING
        assert standing["negotiation_round"] == 4
        assert_pct(standing["last_offer_pct"], 87.00, "last_offer_pct")
        assert standing["last_offer_by_role"] == k.ROLE_CTE_DIRECTOR
        assert standing["last_offer_by_user_id"] == users.DIRECTOR.user_id
        assert standing["negotiated_level_pct"] is None

    def test_the_fifth_offer_arbitrates_onto_the_federal_fallback(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §3.8: "An offer tabled while `negotiation_round` is already exactly 4 drives `NEGOTIATING → ARBITRATED` instead of looping. It still increments `negotiation_round` and still records `offered_level_pct` into `last_offer_pct` along with the offering `last_offer_by_user_id` and `last_offer_by_role` — but **that offered level is discarded as a target**. The federal fallback becomes binding: `negotiated_level_pct` is set to `baseline_pct`, and `met_threshold_pct` becomes `baseline_pct` multiplied by 0.90, rounded half-up to two decimal places."

        Design: Corner/validations/negotiation_budget_drives_arbitration_and_then_refuses_further_offers
        """
        indicator_id = _indicator_at_the_budget_edge(build)

        res = api.table_offer(
            indicator_id,
            f.offer_payload(FIFTH_OFFER_PCT),
            users.headers(users.REVIEWER),
        )
        arbitrated = validate_unpaginated(res, 200)
        assert arbitrated["status"] == k.PI_ARBITRATED
        assert arbitrated["negotiation_round"] == 5
        assert_pct(arbitrated["last_offer_pct"], FIFTH_OFFER_PCT, "last_offer_pct")
        assert_pct(
            arbitrated["negotiated_level_pct"],
            NEGOTIATION_BASELINE_PCT,
            "negotiated_level_pct",
        )
        assert_pct(arbitrated["met_threshold_pct"], 76.50, "met_threshold_pct")

    def test_a_further_offer_against_an_arbitrated_indicator_is_refused(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §3.8: "Once the indicator is `ARBITRATED` the negotiation budget is spent and the arbitrated level is binding, so any further offer or any acceptance against it is refused with `ERR_NEGOTIATION_ROUNDS_EXHAUSTED` — as noted in §2.8, those two calls specifically are not caught by the state-transition check and fall through to this budget rule."

        Design: Corner/validations/negotiation_budget_drives_arbitration_and_then_refuses_further_offers
        """
        indicator_id = _arbitrated_indicator(api, build)

        res = api.table_offer(
            indicator_id,
            f.offer_payload(88.00),
            users.headers(users.DIRECTOR),
        )
        validate_error(res, errors.ERR_NEGOTIATION_ROUNDS_EXHAUSTED)

    def test_an_acceptance_against_an_arbitrated_indicator_is_refused(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §3.8: "Once the indicator is `ARBITRATED` the negotiation budget is spent and the arbitrated level is binding, so any further offer or any acceptance against it is refused with `ERR_NEGOTIATION_ROUNDS_EXHAUSTED` — as noted in §2.8, those two calls specifically are not caught by the state-transition check and fall through to this budget rule."

        Design: Corner/validations/negotiation_budget_drives_arbitration_and_then_refuses_further_offers
        """
        indicator_id = _arbitrated_indicator(api, build)

        res = api.accept_level(
            indicator_id,
            f.accept_level_payload(acceptance_note="District accepts the arbitrated level"),
            users.headers(users.DIRECTOR),
        )
        validate_error(res, errors.ERR_NEGOTIATION_ROUNDS_EXHAUSTED)

    def test_the_refusals_leave_the_arbitrated_level_and_version_untouched(
        self, api: CteApiClient, build: Builder
    ):
        """PRD §3.8: "The federal fallback becomes binding: `negotiated_level_pct` is set to `baseline_pct`, and `met_threshold_pct` becomes `baseline_pct` multiplied by 0.90, rounded half-up to two decimal places."

        PRD §3.8: "Once the indicator is `ARBITRATED` the negotiation budget is spent and the arbitrated level is binding, so any further offer or any acceptance against it is refused with `ERR_NEGOTIATION_ROUNDS_EXHAUSTED`"

        Design: Corner/validations/negotiation_budget_drives_arbitration_and_then_refuses_further_offers
        """
        indicator_id = _arbitrated_indicator(api, build)
        before = validate_unpaginated(
            api.get_indicator(indicator_id, users.headers(users.REVIEWER))
        )

        validate_error(
            api.table_offer(
                indicator_id, f.offer_payload(88.00), users.headers(users.DIRECTOR)
            ),
            errors.ERR_NEGOTIATION_ROUNDS_EXHAUSTED,
        )
        validate_error(
            api.accept_level(
                indicator_id, f.accept_level_payload(), users.headers(users.DIRECTOR)
            ),
            errors.ERR_NEGOTIATION_ROUNDS_EXHAUSTED,
        )

        after = validate_unpaginated(
            api.get_indicator(indicator_id, users.headers(users.REVIEWER))
        )
        assert after["status"] == k.PI_ARBITRATED
        assert after["negotiation_round"] == 5
        assert_pct(
            after["negotiated_level_pct"],
            NEGOTIATION_BASELINE_PCT,
            "negotiated_level_pct",
        )
        assert_pct(after["met_threshold_pct"], 76.50, "met_threshold_pct")
        assert_version(after, before["version"])
