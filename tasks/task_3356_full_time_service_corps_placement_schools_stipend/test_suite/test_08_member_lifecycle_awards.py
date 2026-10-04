"""Member lifecycle and the education award: the semi-independent service /
stipend dimensions, exit-time award certification, the forward-looking
projection, the exit cascade into teams, and the depth-3 school-termination
cascade."""

from test_helpers import (
    ApiErrorId,
    fixtures,
    get_success_data,
    validate_error,
    validate_success,
)
from test_helpers.test_users import (
    PROGRAM_MANAGER_HEADERS,
    SITE_DIRECTOR_HEADERS,
    STIPEND_ADMIN_1_HEADERS,
)


def _twelve_hour_days(*days):
    return [(f"2026-09-{d:02d}", 12.0, "DIRECT_SERVICE") for d in days]


class TestSemiIndependentDimensions:
    def test_stipend_hold_and_resume_guard(self, api):
        """PRD §3.7: "a manual hold moves `ACTIVE` to `SUSPENDED`, and a
        resume moves `SUSPENDED` to `ACTIVE` — but the resume carries a
        cross-dimension guard, permitted only while the member's
        `service_status` is `ACTIVE`, else `ERR_MEMBER_NOT_ACTIVE`."

        Design: Difficulty/non_linear_state_machine/member_service_and_stipend_dimensions_evolve_independently
        """
        fixtures.set_clock(api)
        site = fixtures.create_active_site(api)
        member = fixtures.create_active_member(api, site["id"])

        # A stipend hold moves the stipend dimension alone.
        held = validate_success(
            api.transition_member(
                member["id"], {"to_status": "SUSPENDED", "dimension": "STIPEND"}, STIPEND_ADMIN_1_HEADERS
            )
        )
        assert held["service_status"] == "ACTIVE"
        assert held["stipend_status"] == "SUSPENDED"

        # Service suspension: stipend was already SUSPENDED, so the
        # conditional cascade leaves it there.
        suspended = fixtures.suspend_member_service(api, member["id"])
        assert suspended["service_status"] == "SUSPENDED"
        assert suspended["stipend_status"] == "SUSPENDED"

        # The cross-dimension guard rejects a stipend resume while the service
        # dimension is down.
        blocked = api.transition_member(
            member["id"], {"to_status": "ACTIVE", "dimension": "STIPEND"}, STIPEND_ADMIN_1_HEADERS
        )
        validate_error(blocked, ApiErrorId.ERR_MEMBER_NOT_ACTIVE.value)

    def test_service_suspension_and_resume_cascade_stipend(self, api):
        """PRD §3.7: "Suspension — `ACTIVE` to `SUSPENDED` — moves the stipend
        dimension from `ACTIVE` to `SUSPENDED` only when it is currently
        `ACTIVE`, again recomputing site obligations and posture."
        PRD §3.7: "Return from suspension — `SUSPENDED` back to `ACTIVE` —
        unconditionally moves `stipend_status` from `SUSPENDED` to `ACTIVE`
        and recomputes the same site fields."

        Design: Difficulty/non_linear_state_machine/member_service_and_stipend_dimensions_evolve_independently
        """
        fixtures.set_clock(api)
        site = fixtures.create_active_site(api)
        member = fixtures.create_active_member(api, site["id"])

        suspended = fixtures.suspend_member_service(api, member["id"])
        assert suspended["service_status"] == "SUSPENDED"
        assert suspended["stipend_status"] == "SUSPENDED"

        resumed = fixtures.activate_member_service(api, member["id"])
        assert resumed["service_status"] == "ACTIVE"
        assert resumed["stipend_status"] == "ACTIVE"


class TestCompletionBoundary:
    def test_completion_hours_exactly_120_boundary(self, api):
        """PRD §3.7: "When `exit_type` is `COMPLETED_TERM`, the member must
        have reached at least 120 verified hours — `PENDING`, `REJECTED`, and
        `VOIDED` entries never count — else the exit is rejected with
        `ERR_COMPLETION_HOURS_NOT_MET`; a qualifying completion certifies
        `award_status` of `EARNED_FULL` with `award_amount_cents` of 739500,
        and the member's service ends in `COMPLETED`."

        Design: Difficulty/boundary_precision_check/completion_hours_exactly_120_boundary
        """
        fixtures.set_clock(api)
        site = fixtures.create_active_site(api)
        member = fixtures.create_active_member(api, site["id"])
        fixtures.accumulate_verified_hours(api, member["id"], [f"2026-09-{d:02d}" for d in range(1, 11)], verify_clock="2026-09-11T00:00:00Z")

        before = fixtures.get_member(api, member["id"])
        assert before["verified_hours_total"] == 120.0  # exactly at the bar

        exited = fixtures.exit_member(api, member["id"], "COMPLETED_TERM")
        assert exited["service_status"] == "COMPLETED"
        assert exited["award_status"] == "EARNED_FULL"
        assert exited["award_amount_cents"] == 739_500

    def test_completed_award_can_be_disbursed(self, api):
        """PRD §3.7: "an earned award can be disbursed: a
        `StipendAdministrator` drives the award dimension (`dimension` of
        `AWARD`) from `EARNED_FULL` or `EARNED_PARTIAL` to `DISBURSED`."

        Design: Difficulty/boundary_precision_check/completion_hours_exactly_120_boundary
        """
        fixtures.set_clock(api)
        site = fixtures.create_active_site(api)
        member = fixtures.create_active_member(api, site["id"])
        fixtures.accumulate_verified_hours(api, member["id"], [f"2026-09-{d:02d}" for d in range(1, 11)], verify_clock="2026-09-11T00:00:00Z")
        exited = fixtures.exit_member(api, member["id"], "COMPLETED_TERM")
        assert exited["exit_date"] == "2026-09-11"  # default is the clock date
        assert exited["award_status"] == "EARNED_FULL"

        disbursed = validate_success(
            api.transition_member(
                member["id"], {"to_status": "DISBURSED", "dimension": "AWARD"}, STIPEND_ADMIN_1_HEADERS
            )
        )
        assert disbursed["award_status"] == "DISBURSED"

    def test_completion_hours_119_75_rejected(self, api):
        """PRD §3.7: "When `exit_type` is `COMPLETED_TERM`, the member must
        have reached at least 120 verified hours — `PENDING`, `REJECTED`, and
        `VOIDED` entries never count — else the exit is rejected with
        `ERR_COMPLETION_HOURS_NOT_MET`; a qualifying completion certifies
        `award_status` of `EARNED_FULL` with `award_amount_cents` of 739500,
        and the member's service ends in `COMPLETED`."
        PRD §3.7: "Early exits (`COMPELLING_CIRCUMSTANCE`, `FOR_CAUSE`, or
        `NON_COMPELLING`) land the member in `EXITED_EARLY`: a compelling
        circumstance with at least 24 verified hours earns a partial award —
        `EARNED_PARTIAL` with `award_amount_cents` set to 739500 cents
        multiplied by the verified hours, divided by 120, rounded half up —
        while a compelling exit below 24 hours, or any for-cause or
        non-compelling exit, forfeits the award (`FORFEITED`, amount 0)."

        Design: Corner/validations/completion_hours_119_75_rejected"""
        fixtures.set_clock(api)
        site = fixtures.create_active_site(api)
        member = fixtures.create_active_member(api, site["id"])
        specs = _twelve_hour_days(*range(1, 10)) + [("2026-09-10", 11.75, "DIRECT_SERVICE")]
        fixtures.log_verified_hours(api, member["id"], specs, "2026-09-11T00:00:00Z")

        before = fixtures.get_member(api, member["id"])
        assert before["verified_hours_total"] == 119.75  # one quantum under the bar

        blocked = api.exit_member(
            member["id"],
            {"expected_member_version": before["version"], "exit_type": "COMPLETED_TERM"},
            PROGRAM_MANAGER_HEADERS,
        )
        validate_error(blocked, ApiErrorId.ERR_COMPLETION_HOURS_NOT_MET.value)

        # The rejection mutated nothing, so the same version still matches a
        # different exit type; the compelling exit certifies
        # round_half_up(739500 x 119.75 / 120) = 737959.
        exited = fixtures.exit_member(api, member["id"], "COMPELLING_CIRCUMSTANCE")
        assert exited["award_status"] == "EARNED_PARTIAL"
        assert exited["award_amount_cents"] == 737_959


class TestExitCascade:
    def test_member_exit_depth2_understaffed_cascade(self, api):
        """PRD §3.7: "Link 1: the member's `ACTIVE` team assignments end, with
        `end_date` set to the exit date. Link 2: each affected team recomputes
        its `active_assignment_count`, and a `DEPLOYED` team that drops below
        `min_active_members` automatically moves to `UNDERSTAFFED`."
        PRD §3.7: "a compelling exit below 24 hours, or any for-cause or
        non-compelling exit, forfeits the award (`FORFEITED`, amount 0)."

        Design: Difficulty/transitive_cascade/member_exit_depth2_understaffed_cascade
        """
        fixtures.set_clock(api)
        world = fixtures.setup_deployed_world(api)
        member = world["member"]
        team_id = world["team"]["id"]

        exited = fixtures.exit_member(api, member["id"], "NON_COMPELLING")
        assert exited["service_status"] == "EXITED_EARLY"
        assert exited["award_status"] == "FORFEITED"
        assert exited["award_amount_cents"] == 0
        assert exited["stipend_status"] == "ENDED"

        assignments = get_success_data(api.list_team_assignments(team_id, PROGRAM_MANAGER_HEADERS))
        assert assignments[0]["status"] == "ENDED"
        assert assignments[0]["end_date"] == "2026-09-01"  # exit date (clock date)

        team = fixtures.get_team(api, team_id)
        assert team["status"] == "UNDERSTAFFED"  # 0 < min_active_members 1
        assert team["active_assignment_count"] == 0

    def test_exit_leaves_team_deployed_when_staffing_holds(self, api):
        """PRD §3.7: "Link 2: each affected team recomputes its
        `active_assignment_count`, and a `DEPLOYED` team that drops below
        `min_active_members` automatically moves to `UNDERSTAFFED`."

        Design: Difficulty/transitive_cascade/member_exit_depth2_understaffed_cascade
        """
        fixtures.set_clock(api)
        world = fixtures.setup_deployed_world(api)
        member2 = fixtures.add_active_member(
            api, world["site"]["id"], "app-riley", "Riley Brooks",
            date_of_birth="2004-02-11", education_level="SOME_COLLEGE",
        )
        second = fixtures.assign_member(api, world["team"]["id"], member2["id"], start_date="2026-09-01")
        assert second["is_backfill"] is True

        exited = fixtures.exit_member(api, world["member"]["id"], "NON_COMPELLING")
        assert exited["service_status"] == "EXITED_EARLY"

        team = fixtures.get_team(api, world["team"]["id"])
        # One ACTIVE assignment remains; 1 is not below min_active_members 1.
        assert team["active_assignment_count"] == 1
        assert team["status"] == "DEPLOYED"

    def test_occ_member_exit_stale_version_rejected(self, api):
        """PRD §2.7: "Exiting a corps member requires
        `expected_member_version` matching the member's current `version`. A
        mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412): the award
        certification would otherwise be computed against verified-hour and
        placement data the client has not observed."

        Design: Corner/cross_cutting_layers/occ_member_exit_stale_version_rejected
        """
        fixtures.set_clock(api)
        site = fixtures.create_active_site(api)
        member = fixtures.create_active_member(api, site["id"])
        current = fixtures.get_member(api, member["id"])

        stale = api.exit_member(
            member["id"],
            {"expected_member_version": current["version"] - 1, "exit_type": "NON_COMPELLING"},
            PROGRAM_MANAGER_HEADERS,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION.value)

        after = fixtures.get_member(api, member["id"])
        assert after["service_status"] == "ACTIVE"
        assert after["award_status"] == "NOT_EARNED"

    def test_award_disburse_not_earned_rejected(self, api):
        """PRD §3.7: "Attempting disbursement while the award is in any other
        state is rejected with `ERR_AWARD_NOT_EARNED`; `DISBURSED` (like
        `FORFEITED`) is terminal."

        Design: Corner/validations/award_disburse_not_earned_rejected
        """
        fixtures.set_clock(api)
        site = fixtures.create_active_site(api)
        member = fixtures.create_active_member(api, site["id"])

        blocked = api.transition_member(
            member["id"], {"to_status": "DISBURSED", "dimension": "AWARD"}, STIPEND_ADMIN_1_HEADERS
        )
        validate_error(blocked, ApiErrorId.ERR_AWARD_NOT_EARNED.value)

        after = fixtures.get_member(api, member["id"])
        assert after["award_status"] == "NOT_EARNED"


class TestAwardProjectionVsCertification:
    def _ninety_hour_member(self, api):
        """90.00 VERIFIED hours by 2026-09-08, then the clock at 2027-03-01."""
        site = fixtures.create_active_site(api)
        member = fixtures.create_active_member(api, site["id"])
        specs = _twelve_hour_days(1, 2, 3, 4, 5, 6, 7) + [("2026-09-08", 6.0, "DIRECT_SERVICE")]
        fixtures.log_verified_hours(api, member["id"], specs, "2026-09-16T00:00:00Z")
        fixtures.set_clock(api, "2027-03-01T00:00:00Z")
        return member

    def test_projection_counts_future_days_at_full_award(self, api):
        """PRD §3.7: "The projection counts the calendar days from the day
        after the logical clock date through the site's `service_year_end`
        inclusive — zero once the clock has reached the year's end — and
        assumes 8.0 hours of service on each of those remaining days."
        PRD §3.7: "Adding that allowance to `verified_hours_total` yields
        `projected_hours_total`, and the projected award
        `award_projected_cents` follows: the full 739500 cents when the
        projection reaches at least 120 hours; a pro-rata share — 739500 cents
        multiplied by the projected hours, divided by 120, rounded half up —
        when the projection reaches at least 24 hours but fewer than 120; and
        zero below 24."

        Design: Difficulty/dual_variant_calc/education_award_projection_vs_certification"""
        fixtures.set_clock(api)
        member = self._ninety_hour_member(api)

        read = fixtures.get_member(api, member["id"])
        assert read["verified_hours_total"] == 90.0
        # 106 remaining days (2027-03-02..2027-06-15) x 8.0 on top of 90.0.
        assert read["projected_hours_total"] == 938.0
        # 938 >= 120: the projection certifies a full award on this data.
        assert read["award_projected_cents"] == 739_500

    def test_certification_uses_verified_only_pro_rata(self, api):
        """PRD §3.7: "Because certification counts only entries verified by
        exit time, the same member can project a full award mid-year yet
        certify a smaller pro-rata amount — the projection's assumed future
        hours are excluded at certification."
        PRD §3.7: "Early exits (`COMPELLING_CIRCUMSTANCE`, `FOR_CAUSE`, or
        `NON_COMPELLING`) land the member in `EXITED_EARLY`: a compelling
        circumstance with at least 24 verified hours earns a partial award —
        `EARNED_PARTIAL` with `award_amount_cents` set to 739500 cents
        multiplied by the verified hours, divided by 120, rounded half up —
        while a compelling exit below 24 hours, or any for-cause or
        non-compelling exit, forfeits the award (`FORFEITED`, amount 0)."

        Design: Difficulty/dual_variant_calc/education_award_projection_vs_certification"""
        fixtures.set_clock(api)
        member = self._ninety_hour_member(api)

        exited = fixtures.exit_member(api, member["id"], "COMPELLING_CIRCUMSTANCE")
        assert exited["service_status"] == "EXITED_EARLY"
        assert exited["award_status"] == "EARNED_PARTIAL"
        # round_half_up(739500 x 90 / 120) = 554625; the projected future hours
        # counted above are excluded at certification.
        assert exited["award_amount_cents"] == 554_625

    def test_award_projection_partial_at_year_end(self, api):
        """PRD §3.7: "The projection counts the calendar days from the day
        after the logical clock date through the site's `service_year_end`
        inclusive — zero once the clock has reached the year's end — and
        assumes 8.0 hours of service on each of those remaining days."
        PRD §3.7: "Adding that allowance to `verified_hours_total` yields
        `projected_hours_total`, and the projected award
        `award_projected_cents` follows: the full 739500 cents when the
        projection reaches at least 120 hours; a pro-rata share — 739500 cents
        multiplied by the projected hours, divided by 120, rounded half up —
        when the projection reaches at least 24 hours but fewer than 120; and
        zero below 24."

        Design: Corner/calculations/award_projection_partial_at_year_end"""
        fixtures.set_clock(api)
        site = fixtures.create_active_site(api)
        member = fixtures.create_active_member(api, site["id"])
        fixtures.accumulate_verified_hours(api, member["id"], [f"2026-09-{d:02d}" for d in range(1, 6)], verify_clock="2026-09-06T00:00:00Z")

        # At the service year end there are no remaining days to project.
        fixtures.set_clock(api, "2027-06-15T00:00:00Z")
        read = fixtures.get_member(api, member["id"])
        assert read["projected_hours_total"] == 60.0
        # 60 >= 24: the pro-rata band, round_half_up(739500 x 60 / 120) = 369750.
        assert read["award_projected_cents"] == 369_750


class TestSchoolTerminationCascade:
    def test_school_termination_depth3_cascade(self, api):
        """PRD §3.2: "Link 1: every team of the school in `FORMING`,
        `DEPLOYED`, or `UNDERSTAFFED` moves to `DISSOLVED`. Link 2: each
        dissolved team's `ACTIVE` assignments end, with `end_date` set to the
        clock date. Link 3: for each member whose last `ACTIVE` assignment
        ends in this cascade — the member's `active_assignment_count`
        reaching zero — and whose `service_status` is `ACTIVE`, the member's
        `stipend_status` moves from `ACTIVE` to `SUSPENDED` and that member's
        stipend payments in `SCHEDULED` are forfeited with `decision_reason`
        recorded as `TEAM_DISSOLVED`."

        Design: Difficulty/transitive_cascade/school_termination_depth3_cascade
        """
        fixtures.set_clock(api)
        world = fixtures.setup_deployed_world(api)
        member = world["member"]
        payment = fixtures.schedule_payment(api, member["id"])

        terminated = validate_success(
            api.transition_school(
                world["school"]["id"], {"to_status": "TERMINATED", "dimension": "AGREEMENT"},
                SITE_DIRECTOR_HEADERS,
            )
        )
        assert terminated["agreement_status"] == "TERMINATED"

        team = fixtures.get_team(api, world["team"]["id"])
        assert team["status"] == "DISSOLVED"
        assert team["active_assignment_count"] == 0

        assignments = get_success_data(
            api.list_team_assignments(world["team"]["id"], PROGRAM_MANAGER_HEADERS)
        )
        assert assignments[0]["status"] == "ENDED"
        assert assignments[0]["end_date"] == "2026-09-01"

        member_after = fixtures.get_member(api, member["id"])
        assert member_after["active_assignment_count"] == 0
        assert member_after["stipend_status"] == "SUSPENDED"
        assert member_after["service_status"] == "ACTIVE"

        payments = get_success_data(
            api.list_member_stipend_payments(member["id"], STIPEND_ADMIN_1_HEADERS)
        )
        assert payments[0]["id"] == payment["id"]
        assert payments[0]["status"] == "FORFEITED"
        assert payments[0]["decision_reason"] == "TEAM_DISSOLVED"

    def test_school_termination_releases_students_and_cost_share(self, api):
        """PRD §3.2: "In the same act, every student of the school with
        `enrollment_status` `ACTIVE` moves to `EXITED`, and any of them still
        `ASSIGNED` to a caseload are released: `caseload_status` returns to
        `UNASSIGNED`, `assigned_end_date` is set to the clock date, and
        `assigned_member_id` is cleared to null."
        PRD §3.2: "Finally, because a terminated school leaves the cost-share
        input set, the site's cost-share totals are recomputed."

        Design: Difficulty/transitive_cascade/school_termination_depth3_cascade
        """
        fixtures.set_clock(api)
        world = fixtures.setup_deployed_world(api)
        member = world["member"]
        student = fixtures.create_student(api, world["school"]["id"], "S01")
        fixtures.assign_caseload(api, student["id"], member["id"])

        before = fixtures.get_site(api, world["site"]["id"])
        assert before["cost_share_total_cents"] == 400_000

        validate_success(
            api.transition_school(
                world["school"]["id"], {"to_status": "TERMINATED", "dimension": "AGREEMENT"},
                SITE_DIRECTOR_HEADERS,
            )
        )

        students = get_success_data(api.list_school_students(world["school"]["id"], PROGRAM_MANAGER_HEADERS))
        mine = [s for s in students if s["id"] == student["id"]][0]
        assert mine["enrollment_status"] == "EXITED"
        assert mine["caseload_status"] == "UNASSIGNED"
        assert mine["assigned_end_date"] == "2026-09-01"
        assert mine["assigned_member_id"] is None

        member_after = fixtures.get_member(api, member["id"])
        assert member_after["active_caseload_count"] == 0

        site_after = fixtures.get_site(api, world["site"]["id"])
        assert site_after["cost_share_total_cents"] == 0
        assert site_after["cost_share_installment_1_cents"] == 0
