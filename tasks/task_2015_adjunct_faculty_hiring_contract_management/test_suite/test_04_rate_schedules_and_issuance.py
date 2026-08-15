"""Rate schedule publish/retire rules and contract issuance: gross pay formula,
schedule pinning, reference guard, load-cap guard, OCC (PRD Sections 2.7-2.9, 3.2, 3.5)."""
from test_helpers import (
    ApiErrorId,
    create_department,
    create_published_schedule,
    create_rate_schedule,
    create_section,
    create_term,
    get_faculty,
    get_success_data,
    hire_faculty,
    issue_contract,
    issue_contract_in,
    set_clock,
    standard_fall_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

ADMIN = TEST_USERS["hr_admin_headers"]
PAYROLL = TEST_USERS["payroll_headers"]


class TestRateScheduleOverlap:
    def _setup(self):
        dept = create_department(code="SOCI", contact_hour_value=1.00)
        create_published_schedule(
            dept["id"], education_tier="MASTERS", rate_basis="PER_COURSE",
            base_rate_cents=450000,
            effective_start_date="2026-08-01", effective_end_date="2027-01-31",
        )
        return dept

    def test_rate_schedule_half_open_adjacency_allowed(self, api):
        """PRD Section 3.2: "no other `PUBLISHED` schedule may exist for the same
        pairing of department and education tier whose half-open effective window
        intersects this schedule's window — half-open adjacency, where one
        schedule's end date equals the other's start date, is expressly not an
        overlap."

        Design: Difficulty/resource_temporal_overlap/rate_schedule_half_open_adjacency_allowed_overlap_rejected
        """
        dept = self._setup()
        adjacent = create_rate_schedule(
            dept["id"], education_tier="MASTERS", rate_basis="PER_COURSE",
            base_rate_cents=460000,
            effective_start_date="2027-01-31", effective_end_date="2027-07-31",
        )
        published = validate_success(api.publish_rate_schedule(adjacent["id"], ADMIN), 200)
        assert published["schedule_status"] == "PUBLISHED", (
            "start 2027-01-31 == existing end 2027-01-31 touches without overlapping"
        )

    def test_rate_schedule_one_day_overlap_rejected(self, api):
        """PRD Section 3.2: "A violation of the overlap guard is refused with
        `ERR_SCHEDULE_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/rate_schedule_half_open_adjacency_allowed_overlap_rejected
        """
        dept = self._setup()
        overlapping = create_rate_schedule(
            dept["id"], education_tier="MASTERS", rate_basis="PER_COURSE",
            base_rate_cents=470000,
            effective_start_date="2027-01-30", effective_end_date="2027-07-31",
        )
        refused = api.publish_rate_schedule(overlapping["id"], ADMIN)
        validate_error(refused, ApiErrorId.ERR_SCHEDULE_OVERLAP)
        after = get_success_data(api.get_rate_schedule(overlapping["id"], ADMIN))
        assert after["schedule_status"] == "DRAFT", "failed publish leaves the schedule in DRAFT"


class TestRateScheduleRetire:
    def test_retire_schedule_blocked_by_live_contract_reference(self, api):
        """PRD Section 3.2: "Retirement advances `schedule_status` from `PUBLISHED`
        to `RETIRED` and is permitted only while no contract in `ISSUED` or `ACTIVE`
        references the schedule; otherwise the retire is refused with
        `ERR_REFERENCE_IN_USE`."

        Design: Corner/validations/retire_schedule_blocked_by_live_contract_reference
        """
        scn = standard_fall_scenario(dept_code="RETI", load_cap_units=9.00,
                                     compliance="ONBOARDING_NO_COMPLIANCE_CREDS")
        contract = issue_contract_in(scn)

        blocked = api.retire_rate_schedule(scn["schedule"]["id"], ADMIN)
        validate_error(blocked, ApiErrorId.ERR_REFERENCE_IN_USE)

        voided = get_success_data(api.void_contract(contract["id"], ADMIN))
        assert voided["contract_status"] == "VOIDED"

        retired = validate_success(api.retire_rate_schedule(scn["schedule"]["id"], ADMIN), 200)
        assert retired["schedule_status"] == "RETIRED"


class TestGrossPay:
    def test_gross_pay_per_course_basis_ignores_contact_hours(self, api, hr_admin_headers):
        """PRD Section 3.5: "Under `PER_COURSE`, the gross is the effective rate
        applied once."
        PRD Section 3.5: "Its `load_units` is the section's `weekly_contact_hours`
        multiplied by the department's `contact_hour_value` at issuance, stored as a
        frozen snapshot immune to later schedule or section edits."

        Design: Corner/calculations/gross_pay_per_course_basis_ignores_contact_hours
        """
        scn = standard_fall_scenario(dept_code="PCRS", load_cap_units=9.00,
                                     weekly_contact_hours=3.0, course_code="PCR-101")
        sec_small = create_section(scn["dept"]["id"], term_code="2026FA",
                                   course_code="PCR-102", weekly_contact_hours=1.0,
                                   credit_hours=1)
        con_big = issue_contract_in(scn)
        con_small = issue_contract_in(scn, section=sec_small)

        big = get_success_data(api.get_contract(con_big["id"], hr_admin_headers))
        small = get_success_data(api.get_contract(con_small["id"], hr_admin_headers))
        assert big["gross_pay_cents"] == 450000
        assert small["gross_pay_cents"] == 450000, (
            "PER_COURSE gross is the effective rate applied once, regardless of hours"
        )
        assert big["load_units"] == 3.00
        assert small["load_units"] == 1.00, "load still uses contact hours"


class TestLongevityTieredGross:
    def _faculty_with_two_completed_terms(self, api):
        """Faculty with completed_terms == 2 via completions in 2026SP and 2026SU,
        ready to issue the measured contract into 2026FA."""
        set_clock("2025-11-01T00:00:00Z")
        dept = create_department(code="HIST", contact_hour_value=1.00)
        term_sp = create_term(
            code="2026SP", start_date="2026-01-12", end_date="2026-05-08",
            early_census_date="2026-02-02", late_census_date="2026-03-30",
            load_cap_units=9.00)
        term_su = create_term(
            code="2026SU", start_date="2026-06-01", end_date="2026-07-24",
            early_census_date="2026-06-15", late_census_date="2026-07-06",
            load_cap_units=9.00)
        term_fa = create_term(code="2026FA", load_cap_units=9.00)
        for t in (term_sp, term_su, term_fa):
            get_success_data(api.open_term(t["id"], ADMIN))
        schedule = create_published_schedule(
            dept["id"], education_tier="MASTERS", rate_basis="PER_CONTACT_HOUR",
            base_rate_cents=200000, longevity_step_cents=5000, longevity_step_cap=5,
            effective_start_date="2025-12-01", effective_end_date="2027-01-31",
        )
        hired = hire_faculty(
            dept["id"], term_code="2026SP", tier="MASTERS",
            tier_credential_kind="DEGREE", clock="2025-11-01T00:00:00Z",
            posting_open_date="2025-11-01", posting_close_date="2025-12-15",
        )
        faculty_id = hired["faculty"]["id"]

        def complete_one(term_code, course_code, activate_at, complete_after):
            section = create_section(dept["id"], term_code=term_code,
                                     course_code=course_code, weekly_contact_hours=3.0)
            issue_contract(faculty_id, section["id"], schedule["id"])
            set_clock(activate_at)
            set_clock(complete_after)
            done = get_success_data(api.complete_section(section["id"], TEST_USERS["chair_headers"]))
            assert done["section_status"] == "COMPLETED"

        complete_one("2026SP", "HIS-101", "2026-01-12T00:00:00Z", "2026-05-09T00:00:00Z")
        complete_one("2026SU", "HIS-201", "2026-06-01T00:00:00Z", "2026-07-25T00:00:00Z")

        sec_fa = create_section(dept["id"], term_code="2026FA", course_code="HIS-301",
                                weekly_contact_hours=3.0)
        return dept, schedule, faculty_id, sec_fa

    def test_gross_pay_tiered_longevity_interaction(self, api):
        """PRD Section 3.5: "Its `gross_pay_cents` is the full-term provisional
        gross: the server credits the faculty's longevity as the smaller of
        `completed_terms` and the schedule's `longevity_step_cap`, computes an
        effective rate of `base_rate_cents` plus that credited count times
        `longevity_step_cents`, and then branches on basis."
        PRD Section 3.5: "Under `PER_CONTACT_HOUR`, the term's length in whole weeks
        is the day count between `start_date` and `end_date` divided by seven with
        any fractional week discarded — only whole weeks count — and the billable
        units are the section's `weekly_contact_hours` multiplied by that whole-week
        count at full precision, with the gross equal to the effective rate times
        those units."

        completed_terms 2 against cap 5 credits 2 steps: rate 210000; the fall term
        spans 109 days -> 15 whole weeks: 210000 * 3.0 * 15 = 9,450,000.

        Design: Difficulty/combinatorial_formula/gross_pay_tiered_longevity_interaction
        """
        _, schedule, faculty_id, sec_fa = self._faculty_with_two_completed_terms(api)
        faculty = get_faculty(faculty_id)
        assert faculty["completed_terms"] == 2, (
            "one increment per completed contract (PRD Section 3.6)"
        )
        contract = issue_contract(faculty_id, sec_fa["id"], schedule["id"])
        assert contract["gross_pay_cents"] == 9450000, (
            "210000 effective rate * 3.0 contact hours * 15 whole weeks"
        )

    def test_longevity_contract_load_and_provisional_payable(self, api):
        """PRD Section 3.5: "The contract's `payable_cents` starts out equal to
        `gross_pay_cents` and stays there until a terminal event reprices it."
        PRD Section 3.5: "Its `load_units` is the section's `weekly_contact_hours`
        multiplied by the department's `contact_hour_value` at issuance"

        Design: Difficulty/combinatorial_formula/gross_pay_tiered_longevity_interaction
        """
        _, schedule, faculty_id, sec_fa = self._faculty_with_two_completed_terms(api)
        contract = issue_contract(faculty_id, sec_fa["id"], schedule["id"])
        assert contract["load_units"] == 3.00
        assert contract["payable_cents"] == 9450000, (
            "provisional payable equals gross before any terminal event"
        )
        assert contract["contract_status"] == "ISSUED"


class TestIssuanceComputedFields:
    def test_contract_response_pins_schedule_version(self, api):
        """PRD Section 3.5: "Its `pinned_schedule_version` captures the schedule's
        `published_version` at issuance for stale-pin detection."
        PRD Section 3.2: "At the moment of publish, the schedule records its own
        then-current `version` counter value as `published_version`"

        Design: Corner/endpoints/contract_response_pins_schedule_version
        """
        scn = standard_fall_scenario(dept_code="PINV", load_cap_units=9.00)
        published_version = scn["schedule"]["published_version"]
        assert isinstance(published_version, int)
        contract = issue_contract_in(scn)
        assert contract["pinned_schedule_version"] == published_version

    def test_computed_fields_client_input_ignored(self, api):
        """PRD Section 3.5: "Its `load_units` is the section's `weekly_contact_hours`
        multiplied by the department's `contact_hour_value` at issuance" — and the
        gross comes from the rate schedule, not from anything the caller sends.
        PRD Section 2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."

        Design: Corner/endpoints/computed_fields_client_input_ignored
        """
        scn = standard_fall_scenario(dept_code="CMPF", load_cap_units=9.00,
                                     contact_hour_value=2.00)
        contract = issue_contract_in(scn)
        assert contract["gross_pay_cents"] == 450000, "server-computed from the schedule"
        assert contract["load_units"] == 6.00, "3.0 weekly hours * contact_hour_value 2.00"


class TestIssuanceAuthorization:
    def test_unauthorized_role_cannot_issue_contract(self, api):
        """PRD Section 2.1: "A request that authenticates cleanly but whose role is
        not listed for the target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE`
        (HTTP 403)."
        PRD Section 4: POST /adjunct-hr/contracts is authorized for DepartmentChair
        only.

        Design: Corner/validations/unauthorized_role_cannot_issue_contract
        """
        scn = standard_fall_scenario(dept_code="RBAC", load_cap_units=9.00)
        version = get_faculty(scn["faculty"]["id"])["version"]
        resp = api.create_contract(
            {
                "faculty_id": scn["faculty"]["id"],
                "section_id": scn["section"]["id"],
                "rate_schedule_id": scn["schedule"]["id"],
                "expected_faculty_version": version,
            },
            PAYROLL,
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


class TestIssuanceOcc:
    def test_stale_faculty_version_occ_on_contract_issue(self, api, hr_admin_headers):
        """PRD Section 3.5: "The contract begins life in `ISSUED`, and the issuance
        bumps the faculty record's `version` by one — which is precisely why a
        second issuance against the same faculty must carry a freshly observed
        `expected_faculty_version`."
        PRD Section 2.7: "If the supplied token does not match the faculty record's
        current `version` at write time — because any earlier mutation, including a
        prior contract issuance or a prior reappointment decision, advanced it —
        the request is rejected with `ERR_STALE_FACULTY_VERSION` (HTTP 412)."

        Design: Corner/validations/stale_faculty_version_occ_on_contract_issue
        """
        scn = standard_fall_scenario(dept_code="OCCX", load_cap_units=9.00)
        sec_b = create_section(scn["dept"]["id"], term_code="2026FA",
                               course_code="OCC-102", weekly_contact_hours=3.0)
        observed = get_faculty(scn["faculty"]["id"])["version"]

        first = issue_contract(scn["faculty"]["id"], scn["section"]["id"],
                               scn["schedule"]["id"], expected_faculty_version=observed)
        assert first["contract_status"] == "ISSUED"

        stale = api.create_contract(
            {
                "faculty_id": scn["faculty"]["id"],
                "section_id": sec_b["id"],
                "rate_schedule_id": scn["schedule"]["id"],
                "expected_faculty_version": observed,
            },
            TEST_USERS["chair_headers"],
        )
        validate_error(stale, ApiErrorId.ERR_STALE_FACULTY_VERSION)

        contracts, meta = validate_paginated(
            api.list_faculty_contracts(scn["faculty"]["id"], hr_admin_headers))
        assert meta["total_count"] == 1, "the rejected issuance created nothing"


class TestLoadCapGuard:
    def test_load_cap_overage_boundary_exact_allowance_passes(self, api):
        """PRD Section 3.5: "Issuance is refused with `ERR_LOAD_CAP_EXCEEDED` only
        when that prospective sum is strictly greater than the term's
        `load_cap_units` plus an overage allowance of 1.00 load unit; a prospective
        load of exactly the cap plus 1.00 passes."

        Prospective sums: 3.00, then 4.50, then exactly 5.50 == 4.50 + 1.00 (passes),
        then 5.75 > 5.50 (refused).

        Design: Corner/validations/load_cap_overage_boundary_exact_allowance_passes
        """
        scn = standard_fall_scenario(dept_code="CAPX", load_cap_units=4.50,
                                     weekly_contact_hours=3.0, course_code="CAP-101")
        sec_b = create_section(scn["dept"]["id"], term_code="2026FA",
                               course_code="CAP-102", weekly_contact_hours=1.5,
                               credit_hours=1)
        sec_c = create_section(scn["dept"]["id"], term_code="2026FA",
                               course_code="CAP-103", weekly_contact_hours=1.0,
                               credit_hours=1)
        sec_d = create_section(scn["dept"]["id"], term_code="2026FA",
                               course_code="CAP-104", weekly_contact_hours=0.25,
                               credit_hours=0)
        fid = scn["faculty"]["id"]
        issue_contract(fid, scn["section"]["id"], scn["schedule"]["id"])
        issue_contract(fid, sec_b["id"], scn["schedule"]["id"])

        at_allowance = issue_contract(fid, sec_c["id"], scn["schedule"]["id"])
        assert at_allowance["load_units"] == 1.00, (
            "prospective 5.50 == cap 4.50 + allowance 1.00 passes"
        )

        version = get_faculty(fid)["version"]
        over = api.create_contract(
            {
                "faculty_id": fid,
                "section_id": sec_d["id"],
                "rate_schedule_id": scn["schedule"]["id"],
                "expected_faculty_version": version,
            },
            TEST_USERS["chair_headers"],
        )
        validate_error(over, ApiErrorId.ERR_LOAD_CAP_EXCEEDED)


class TestReferenceBeatsFiscal:
    def _setup(self, dept_code):
        scn = standard_fall_scenario(dept_code=dept_code, load_cap_units=4.50,
                                     weekly_contact_hours=4.5, course_code="ECO-101")
        contract_a = issue_contract_in(scn)  # load 4.50
        sec_b = create_section(scn["dept"]["id"], term_code="2026FA",
                               course_code="ECO-201", weekly_contact_hours=3.0)
        draft = create_rate_schedule(
            scn["dept"]["id"], education_tier="DOCTORATE", rate_basis="PER_COURSE",
            base_rate_cents=500000,
            effective_start_date="2026-08-01", effective_end_date="2027-01-31",
        )  # intentionally never published
        return scn, contract_a, sec_b, draft

    def test_referential_beats_fiscal_on_contract_issuance(self, api):
        """PRD Section 2.8: "A request that violates several rules at once receives
        exactly one error: the checks below run in a fixed order and the first
        failing check wins." — the pipeline lists "14. `ERR_CONTRACT_REFERENCE_INVALID`
        (422) — contract issuance references; applies to contract creation only."
        before "15. `ERR_LOAD_CAP_EXCEEDED` (422) — the load-cap guard; applies to
        contract creation only."

        The issuance references a DRAFT schedule (reference failure) AND would push
        prospective load to 7.50 > 5.50 (fiscal failure); the referential error wins.

        Design: Difficulty/priority_pair_validation_conflict/referential_beats_fiscal_on_contract_issuance
        """
        scn, _, sec_b, draft = self._setup("ECON")
        version = get_faculty(scn["faculty"]["id"])["version"]
        resp = api.create_contract(
            {
                "faculty_id": scn["faculty"]["id"],
                "section_id": sec_b["id"],
                "rate_schedule_id": draft["id"],
                "expected_faculty_version": version,
            },
            TEST_USERS["chair_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_CONTRACT_REFERENCE_INVALID)

    def test_rejected_issuance_creates_no_contract(self, api, hr_admin_headers):
        """PRD Section 3.5: "Reference validity is checked before anything computes,
        with any failure refused as `ERR_CONTRACT_REFERENCE_INVALID`: the named rate
        schedule must be `PUBLISHED`"

        Design: Difficulty/priority_pair_validation_conflict/referential_beats_fiscal_on_contract_issuance
        """
        scn, _, sec_b, draft = self._setup("ECO2")
        version = get_faculty(scn["faculty"]["id"])["version"]
        resp = api.create_contract(
            {
                "faculty_id": scn["faculty"]["id"],
                "section_id": sec_b["id"],
                "rate_schedule_id": draft["id"],
                "expected_faculty_version": version,
            },
            TEST_USERS["chair_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_CONTRACT_REFERENCE_INVALID)

        contracts, meta = validate_paginated(
            api.list_section_contracts(sec_b["id"], hr_admin_headers))
        assert meta["total_count"] == 0, "rejected issuance creates no contract"
        schedule = get_success_data(api.get_rate_schedule(draft["id"], hr_admin_headers))
        assert schedule["schedule_status"] == "DRAFT", "failed publish target untouched"
