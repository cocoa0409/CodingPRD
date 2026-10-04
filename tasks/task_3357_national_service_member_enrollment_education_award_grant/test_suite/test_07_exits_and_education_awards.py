"""Exits and education awards: full vs prorated variants, the min-hours and
15% proration floors, FOR_CAUSE debarment cascade, grievance gating, and exit
overpayment arithmetic (PRD §2.7, §3.3, §3.7, §3.9)."""
from datetime import date

from test_helpers import (
    ApiErrorId,
    award_version,
    certify_minutes,
    create_enrollment_payload,
    enroll,
    escalate_grievance,
    exit_member,
    file_grievance,
    get_enrollment,
    make_grantee_staff_headers,
    make_member_headers,
    match_line,
    pay_allowance,
    register_cleared_member,
    resolve_grievance_payload,
    setup_active_enrollment,
    setup_awarded_program,
    slot_request,
    validate_error,
    validate_paginated,
    validate_success,
)

MEMBER_B = {"full_name": "Blair Kim", "date_of_birth": "1999-05-20",
            "citizenship_status": "US_NATIONAL"}


def _get_award(api, award_id, headers):
    return validate_success(api.get_education_award(award_id, headers))


class TestFullVsProratedAward:
    def _setup_two_exits(self, api):
        """Member A FULL_TIME with 102000 certified exits SUCCESSFUL; member B
        FULL_TIME with 36000 certified exits COMPELLING_CIRCUMSTANCE."""
        program = setup_awarded_program()
        member_a = register_cleared_member(program["org_id"])
        enr_a = enroll(program["award_id"], program["org_id"], member_a)
        certify_minutes(enr_a["id"], program["org_id"], [48000, 48000, 6000])
        member_b = register_cleared_member(program["org_id"], **MEMBER_B)
        enr_b = enroll(program["award_id"], program["org_id"], member_b)
        certify_minutes(enr_b["id"], program["org_id"], [36000])
        exit_a = exit_member(enr_a["id"], program["org_id"], "SUCCESSFUL")
        exit_b = exit_member(enr_b["id"], program["org_id"], "COMPELLING_CIRCUMSTANCE")
        return program, exit_a, exit_b

    def test_successful_full_and_compelling_prorated_amounts(self, api, trust_admin_headers):
        """Same term category, two variants: a SUCCESSFUL exit issues the flat
        739500; a COMPELLING exit at 36000/102000 minutes issues the prorated
        round(739500 x 36000/102000) == 261000.

        PRD §3.7: "The system issues an EducationAward for the full category amount from the term table: `issued_amount_cents` is the flat award for the term regardless of hours served beyond the minimum"
        PRD §3.7: "The award is proportional: the category's full award multiplied by the ratio of `certified_minutes` to `term_minutes`, rounded half up to integer cents, so the same term category at a partial completion yields a strictly smaller award than full completion."

        Design: Difficulty/dual_variant_calc/education_award_full_vs_prorated_same_term
        """
        program, exit_a, exit_b = self._setup_two_exits(api)
        assert exit_a["status"] == "EXITED_SUCCESSFUL"
        assert exit_b["status"] == "EXITED_COMPELLING"
        edu_a = _get_award(api, exit_a["education_award_id"], trust_admin_headers)
        edu_b = _get_award(api, exit_b["education_award_id"], trust_admin_headers)
        assert edu_a["issued_amount_cents"] == 739500
        assert edu_a["remaining_balance_cents"] == 739500
        assert edu_b["issued_amount_cents"] == 261000
        assert edu_b["remaining_balance_cents"] == 261000
        assert edu_a["term_category"] == edu_b["term_category"] == "FULL_TIME", (
            "the 478500-cent delta comes from the exit variant, not the category"
        )

    def test_use_deadline_is_seven_calendar_years_from_issuance(self, api, trust_admin_headers):
        """Both exits stamp issued_at at the current logical time
        (2026-10-02T00:00:00Z) and set the deadline exactly seven calendar
        years later.

        PRD §3.7: "`issued_at` is the current logical time, and `use_deadline_at` is exactly seven calendar years later."
        PRD §3.7: "The seven-year use deadline runs from issuance exactly as on the full path"

        Design: Difficulty/dual_variant_calc/education_award_full_vs_prorated_same_term
        """
        program, exit_a, exit_b = self._setup_two_exits(api)
        edu_a = _get_award(api, exit_a["education_award_id"], trust_admin_headers)
        edu_b = _get_award(api, exit_b["education_award_id"], trust_admin_headers)
        assert edu_a["issued_at"].startswith("2026-10-02T00:00:00")
        assert edu_a["use_deadline_at"].startswith("2033-10-02T00:00:00")
        assert edu_b["use_deadline_at"].startswith("2033-10-02T00:00:00")


class TestMinHoursBoundary:
    def test_exactly_102000_minutes_exits_successful(self, api, trust_admin_headers):
        """At exactly the FULL_TIME requirement the member is eligible and
        receives the full 739500-cent award.

        PRD §3.7: "It requires the enrollment's `certified_minutes` to be at least its `term_minutes` — reaching the requirement exactly is eligible — else `ERR_MIN_HOURS_NOT_MET`."

        Design: Difficulty/boundary_precision_check/full_time_minutes_boundary_exit
        """
        program = setup_awarded_program()
        member_a = register_cleared_member(program["org_id"])
        enr_a = enroll(program["award_id"], program["org_id"], member_a)
        certify_minutes(enr_a["id"], program["org_id"], [48000, 48000, 6000])
        exited = exit_member(enr_a["id"], program["org_id"], "SUCCESSFUL")
        assert exited["status"] == "EXITED_SUCCESSFUL"
        edu = _get_award(api, exited["education_award_id"], trust_admin_headers)
        assert edu["issued_amount_cents"] == 739500

    def test_one_minute_short_is_rejected(self, api):
        """At 101999 certified minutes the SUCCESSFUL exit is rejected and the
        enrollment stays ACTIVE with no award issued.

        PRD §3.7: "It requires the enrollment's `certified_minutes` to be at least its `term_minutes` — reaching the requirement exactly is eligible — else `ERR_MIN_HOURS_NOT_MET`."

        Design: Difficulty/boundary_precision_check/full_time_minutes_boundary_exit
        """
        program = setup_awarded_program()
        member_b = register_cleared_member(program["org_id"], **MEMBER_B)
        enr_b = enroll(program["award_id"], program["org_id"], member_b)
        certify_minutes(enr_b["id"], program["org_id"], [48000, 48000, 5999])
        resp = api.exit_enrollment(
            enr_b["id"], {"exit_reason": "SUCCESSFUL"},
            make_grantee_staff_headers(program["org_id"]),
        )
        validate_error(resp, ApiErrorId.ERR_MIN_HOURS_NOT_MET)
        enrollment = get_enrollment(enr_b["id"])
        assert enrollment["status"] == "ACTIVE"
        assert enrollment["education_award_id"] is None


class TestForCauseExitCascade:
    def _setup_for_cause(self, api):
        program = setup_awarded_program()
        member_a = register_cleared_member(program["org_id"])
        enr_a = enroll(program["award_id"], program["org_id"], member_a)
        certify_minutes(enr_a["id"], program["org_id"], [15300])
        return program, member_a, enr_a

    def test_for_cause_exit_debars_member_and_creates_no_award(self, api, officer_headers):
        """The FOR_CAUSE exit releases the member with no education award and
        debars the member, incrementing the release count.

        PRD §3.7: "No education award is created (`education_award_id` stays null), the member is `DEBARRED` from further service, and the member's `for_cause_release_count` increments"

        Design: Difficulty/transitive_cascade/for_cause_exit_debars_member_and_recycles_slot
        """
        program, member_a, enr_a = self._setup_for_cause(api)
        exited = exit_member(enr_a["id"], program["org_id"], "FOR_CAUSE")
        assert exited["status"] == "RELEASED_FOR_CAUSE"
        assert exited["education_award_id"] is None
        member = validate_success(api.get_member(member_a, officer_headers))
        assert member["status"] == "DEBARRED"
        assert member["for_cause_release_count"] == 1
        awards, meta = validate_paginated(
            api.list_education_awards(officer_headers, params={"enrollment_id": enr_a["id"]})
        )
        assert awards == [] and meta["total_count"] == 0

    def test_slot_recycles_and_debarred_member_cannot_reenroll(self, api, officer_headers):
        """The vacated slot reopens (award ACTIVE, fill_count 1 < 2), but the
        debarred member's fresh enrollment attempt is rejected.

        PRD §3.3: "if the award is `ACTIVE` and the slot's `fill_count` is still below 2, the slot reopens (`VACATED` → `OPEN`)"
        PRD §3.7: "that debarment is what later enrollment attempts hit as `ERR_MEMBER_INELIGIBLE`."

        Design: Difficulty/transitive_cascade/for_cause_exit_debars_member_and_recycles_slot
        """
        program, member_a, enr_a = self._setup_for_cause(api)
        slot_id = enr_a["slot_id"]
        exit_member(enr_a["id"], program["org_id"], "FOR_CAUSE")
        slot = validate_success(api.get_slot(slot_id, officer_headers))
        assert slot["status"] == "OPEN" and slot["fill_count"] == 1
        resp = api.create_enrollment(
            program["award_id"],
            create_enrollment_payload(
                member_a,
                service_start_date="2026-11-01",
                service_end_date="2027-09-01",
                expected_award_version=award_version(program["award_id"]),
            ),
            make_grantee_staff_headers(program["org_id"]),
        )
        validate_error(resp, ApiErrorId.ERR_MEMBER_INELIGIBLE)


class TestGrievanceBlocksForCauseExit:
    def _setup_escalated_grievance(self, api):
        scenario = setup_active_enrollment()
        grievance = file_grievance(scenario["enrollment_id"], scenario["member_id"])
        escalate_grievance(grievance["id"], scenario["member_id"])
        return scenario, grievance

    def test_for_cause_exit_blocked_while_grievance_escalated(self, api, officer_headers):
        """The FOR_CAUSE exit is rejected while the enrollment's grievance
        stands ESCALATED; nothing about the enrollment or member changes.

        PRD §3.7: "A `FOR_CAUSE` release is disciplinary. It is blocked while any grievance of the enrollment stands `ESCALATED` (`ERR_GRIEVANCE_PENDING`) — the member's appeal must run its course first."

        Design: Difficulty/cross_entity_state_dependency/for_cause_exit_blocked_by_escalated_grievance
        """
        scenario, grievance = self._setup_escalated_grievance(api)
        resp = api.exit_enrollment(
            scenario["enrollment_id"], {"exit_reason": "FOR_CAUSE"},
            make_grantee_staff_headers(scenario["org_id"]),
        )
        validate_error(resp, ApiErrorId.ERR_GRIEVANCE_PENDING)
        assert resp.status_code == 409
        assert get_enrollment(scenario["enrollment_id"])["status"] == "ACTIVE"
        member = validate_success(api.get_member(scenario["member_id"], officer_headers))
        assert member["status"] == "ACTIVE", "no debarment while the exit is blocked"

    def test_exit_succeeds_after_grievance_resolved(self, api, officer_headers):
        """Once the program officer resolves the grievance DISMISSED, the
        retried FOR_CAUSE exit releases the member and debars them, still with
        no education award.

        PRD §3.9: "Only a `CNCSProgramOfficer` may resolve an escalated grievance, recording an `outcome` of `UPHELD` or `DISMISSED` as it moves to `RESOLVED`."
        PRD §3.7: "No education award is created (`education_award_id` stays null), the member is `DEBARRED` from further service"

        Design: Difficulty/cross_entity_state_dependency/for_cause_exit_blocked_by_escalated_grievance
        """
        scenario, grievance = self._setup_escalated_grievance(api)
        api.exit_enrollment(
            scenario["enrollment_id"], {"exit_reason": "FOR_CAUSE"},
            make_grantee_staff_headers(scenario["org_id"]),
        )
        resolved = validate_success(
            api.resolve_grievance(grievance["id"], resolve_grievance_payload("DISMISSED"), officer_headers)
        )
        assert resolved["status"] == "RESOLVED"
        exited = exit_member(scenario["enrollment_id"], scenario["org_id"], "FOR_CAUSE")
        assert exited["status"] == "RELEASED_FOR_CAUSE"
        member = validate_success(api.get_member(scenario["member_id"], officer_headers))
        assert member["status"] == "DEBARRED"
        awards, meta = validate_paginated(
            api.list_education_awards(
                officer_headers, params={"enrollment_id": scenario["enrollment_id"]}
            )
        )
        assert awards == [] and meta["total_count"] == 0

    def test_resolve_filed_grievance_is_invalid_state(self, api, officer_headers):
        """Resolve requires ESCALATED; resolving a merely FILED grievance hits
        the generic transition guard.

        PRD §3.9: "Resolving a grievance that is not `ESCALATED`, or escalating one that is not `FILED`, trips the generic transition guard `ERR_INVALID_STATE`."

        Design: Corner/state_machines/resolve_filed_grievance_returns_invalid_state
        """
        scenario = setup_active_enrollment()
        grievance = file_grievance(scenario["enrollment_id"], scenario["member_id"])
        resp = api.resolve_grievance(
            grievance["id"], resolve_grievance_payload("DISMISSED"), officer_headers
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        rows, _ = validate_paginated(
            api.list_enrollment_grievances(scenario["enrollment_id"], officer_headers)
        )
        assert rows[0]["status"] == "FILED"
        assert rows[0]["outcome"] is None


class TestTermConstantsAndProrationFloor:
    def test_half_time_full_completion_award_constant(self, api, trust_admin_headers):
        """HALF_TIME requires 54000 minutes and its full award is exactly
        391500 cents; the deadline is seven calendar years from issuance.

        PRD §2.7: "Full education award on successful completion: 739500 cents ($7,395.00) for `FULL_TIME`, 391500 for `HALF_TIME`, 293625 for `REDUCED_HALF_TIME`, 195750 for `QUARTER_TIME`, 130500 for `MINIMUM_TIME`, and 43500 cents for `ABBREVIATED_TIME`."
        PRD §2.7: "`HALF_TIME` 54000 (900 hours)"

        Design: Corner/calculations/half_time_full_completion_award_constant
        """
        scenario = setup_active_enrollment(
            federal_share_requested_cents=1150000,
            slot_requests=[slot_request("HALF_TIME", 1)],
            match_lines=[match_line("CASH", 276000)],
            term_category="HALF_TIME",
            service_end_date="2027-04-15",
        )
        assert scenario["enrollment"]["term_minutes"] == 54000
        certify_minutes(scenario["enrollment_id"], scenario["org_id"], [48000])
        certify_minutes(
            scenario["enrollment_id"], scenario["org_id"], [6000],
            first_service_date=date(2026, 10, 17),
            activity_code="TRAINING",
        )
        exited = exit_member(scenario["enrollment_id"], scenario["org_id"], "SUCCESSFUL")
        edu = _get_award(api, exited["education_award_id"], trust_admin_headers)
        assert edu["issued_amount_cents"] == 391500
        assert edu["remaining_balance_cents"] == 391500
        assert edu["use_deadline_at"].startswith("2033-10-02T00:00:00")

    def test_proration_floor_exactly_15_percent(self, api, trust_admin_headers):
        """15300 certified minutes is exactly 15% of 102000 (15300 x 100 ==
        15 x 102000) and prorates to 110925 cents; 15299 minutes is below the
        floor and is rejected.

        PRD §3.7: "It requires the member to have certified at least fifteen percent of the term — `certified_minutes` multiplied by 100 must be at least 15 times `term_minutes`, and exactly fifteen percent is eligible — else `ERR_PRORATION_FLOOR_NOT_MET`."

        Design: Corner/calculations/proration_floor_exactly_15_percent
        """
        program = setup_awarded_program()
        member_a = register_cleared_member(program["org_id"])
        enr_a = enroll(program["award_id"], program["org_id"], member_a)
        certify_minutes(enr_a["id"], program["org_id"], [15300])
        member_b = register_cleared_member(program["org_id"], **MEMBER_B)
        enr_b = enroll(program["award_id"], program["org_id"], member_b)
        certify_minutes(enr_b["id"], program["org_id"], [15299])
        exited_a = exit_member(enr_a["id"], program["org_id"], "COMPELLING_CIRCUMSTANCE")
        assert exited_a["status"] == "EXITED_COMPELLING"
        edu = _get_award(api, exited_a["education_award_id"], trust_admin_headers)
        assert edu["issued_amount_cents"] == 110925
        resp = api.exit_enrollment(
            enr_b["id"], {"exit_reason": "COMPELLING_CIRCUMSTANCE"},
            make_grantee_staff_headers(program["org_id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PRORATION_FLOOR_NOT_MET)
        enrollment_b = get_enrollment(enr_b["id"])
        assert enrollment_b["status"] == "ACTIVE"
        assert enrollment_b["education_award_id"] is None


class TestExitOverpayment:
    def test_overpayment_zero_when_paid_below_earned(self, api, trust_admin_headers):
        """Member A (51000 certified, 800000 paid) earns 1100000; member B
        (36000 certified, 700000 paid) earns 776470 — both exits record zero
        overpayment, and B's prorated award is 261000.

        PRD §3.7: "the earned side of the overpayment calculation prorates the same way: the allowance total multiplied by the certified-minutes ratio, floored to integer cents, with `exit_overpayment_cents` the excess of `allowance_paid_cents` over that earned figure, never below zero."

        Design: Corner/calculations/exit_overpayment_computed_at_compelling_exit
        """
        program = setup_awarded_program()
        member_a = register_cleared_member(program["org_id"])
        enr_a = enroll(program["award_id"], program["org_id"], member_a)
        certify_minutes(enr_a["id"], program["org_id"], [48000, 3000])
        pay_allowance(enr_a["id"], program["org_id"], 100000, 8)
        member_b = register_cleared_member(program["org_id"], **MEMBER_B)
        enr_b = enroll(program["award_id"], program["org_id"], member_b)
        certify_minutes(enr_b["id"], program["org_id"], [36000])
        pay_allowance(enr_b["id"], program["org_id"], 100000, 7)
        exited_a = exit_member(enr_a["id"], program["org_id"], "COMPELLING_CIRCUMSTANCE")
        exited_b = exit_member(enr_b["id"], program["org_id"], "COMPELLING_CIRCUMSTANCE")
        assert exited_a["allowance_paid_cents"] == 800000
        assert exited_a["exit_overpayment_cents"] == 0, "earned 1100000 >= paid 800000"
        assert exited_b["allowance_paid_cents"] == 700000
        assert exited_b["exit_overpayment_cents"] == 0, "earned 776470 >= paid 700000"
        edu_b = _get_award(api, exited_b["education_award_id"], trust_admin_headers)
        assert edu_b["issued_amount_cents"] == 261000

    def test_for_cause_exit_uses_same_prorated_earned_floor(self, api):
        """A FOR_CAUSE exit computes the same floored prorated earned figure:
        700000 paid against 776470 earned yields zero overpayment and no award.

        PRD §3.7: "The enrollment lands in `RELEASED_FOR_CAUSE`, and the overpayment uses the same prorated, floored earned figure as a compelling-circumstance exit."

        Design: Corner/calculations/exit_overpayment_positive_when_paid_ahead_of_hours
        """
        scenario = setup_active_enrollment(minutes_chunks=[36000])
        pay_allowance(scenario["enrollment_id"], scenario["org_id"], 100000, 7)
        exited = exit_member(scenario["enrollment_id"], scenario["org_id"], "FOR_CAUSE")
        assert exited["status"] == "RELEASED_FOR_CAUSE"
        assert exited["exit_overpayment_cents"] == 0, (
            "max(0, 700000 - floor(2200000 x 36000/102000)) == max(0, -76470)"
        )
        assert exited["education_award_id"] is None
