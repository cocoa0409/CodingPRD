"""Evaluations, retention-list ranking, and reappointment decisions
(PRD Sections 2.7, 3.8)."""
from test_helpers import (
    ApiErrorId,
    assert_evaluation,
    create_department,
    create_fall_term,
    create_published_schedule,
    create_section,
    create_term,
    evaluation_payload,
    get_faculty,
    get_success_data,
    hire_faculty,
    issue_contract,
    open_term,
    retention_entry_payload,
    set_clock,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

ADMIN = TEST_USERS["hr_admin_headers"]
CHAIR = TEST_USERS["chair_headers"]
DEAN = TEST_USERS["dean_headers"]


def _hired_faculty(dept_id, name, email, compliance="ONBOARDING_NO_COMPLIANCE_CREDS",
                   tier="BACHELORS"):
    """Minimal hire (verified TRANSCRIPT only, unless compliance says otherwise)."""
    return hire_faculty(
        dept_id, tier=tier, min_education_tier=tier,
        compliance=compliance, applicant_name=name, applicant_email=email,
    )["faculty"]


def _dept_with_term(code):
    set_clock("2026-06-01T00:00:00Z")
    dept = create_department(code=code, contact_hour_value=1.00)
    create_fall_term()
    return dept


class TestCompositeScore:
    def test_retention_composite_rounding_per_component_then_sum(self, api):
        """PRD Section 3.8: "Each evaluation's `composite_score` is a weighted blend
        with pinned weights: teaching contributes sixty percent, service
        twenty-five percent, and compliance fifteen percent. Each component is
        scaled first — the score multiplied by its weight and by one hundred — and
        rounded half up to an integer number of hundredths, and only then are the
        three rounded components summed; dividing that sum by one hundred yields
        the two-decimal composite. Rounding is per component before summation,
        always in that order."

        Scores 4.47/3.33/2.22: 268 + 83 + 33 = 384 -> 3.84 (sum-then-round would
        give 3.85).

        Design: Corner/calculations/retention_composite_rounding_per_component_then_sum
        """
        dept = _dept_with_term("EVAL")
        faculty = _hired_faculty(dept["id"], "Yan Adjunct", "yan@x.edu")
        resp = api.create_evaluation(
            evaluation_payload(faculty["id"], term_code="2026FA",
                               teaching_score=4.47, service_score=3.33,
                               compliance_score=2.22),
            DEAN,
        )
        record = validate_success(resp, 201)
        assert_evaluation(record)
        assert record["composite_score"] == 3.84, (
            "per-component rounding: rhu(4.47*60)+rhu(3.33*25)+rhu(2.22*15) = 268+83+33"
        )
        assert record["recorded_by_dean_id"] == "dean_1"


class TestRetentionRank:
    def test_retention_rank_rerank_on_new_entry(self, api, dean_headers):
        """PRD Section 3.8: "Creation re-ranks the entire scope: the server gathers
        every `LISTED` entry sharing the new entry's `department_id` and
        `list_term_code` — gathered after inserting the new one — and orders them
        by a ranking score, which for each faculty is the `composite_score` of that
        faculty's most recent evaluation whose `term_code` precedes the list term,
        the latest by that record's `created_at` when several qualify. Entries sort
        by that composite descending; ties break by the same evaluation record's
        `teaching_score` descending, then by that record's `created_at` ascending.
        A faculty with no qualifying prior evaluation sorts last, and among
        themselves such entries order by the faculty record's `created_at`
        ascending. The server then assigns `rank_position` from one upward in that
        order, rewriting every row in scope"

        Low scorer (3.55) listed first at rank 1; inserting the high scorer (4.45)
        rewrites the scope: high -> 1, low -> 2.

        Design: Corner/calculations/retention_rank_rerank_on_new_entry
        """
        dept = _dept_with_term("RANK")
        low = _hired_faculty(dept["id"], "Low Scorer", "low@x.edu")
        high = _hired_faculty(dept["id"], "High Scorer", "high@x.edu")
        get_success_data(api.create_evaluation(
            evaluation_payload(low["id"], term_code="2026SU",
                               teaching_score=3.00, service_score=4.00,
                               compliance_score=5.00), DEAN))
        get_success_data(api.create_evaluation(
            evaluation_payload(high["id"], term_code="2026SU",
                               teaching_score=4.50, service_score=4.00,
                               compliance_score=5.00), DEAN))

        entry_low = get_success_data(api.create_retention_entry(
            retention_entry_payload(low["id"], dept["id"], list_term_code="2027SP"), DEAN))
        assert entry_low["rank_position"] == 1, "sole entry ranks first"

        entry_high = get_success_data(api.create_retention_entry(
            retention_entry_payload(high["id"], dept["id"], list_term_code="2027SP"), DEAN))
        assert entry_high["rank_position"] == 1, "higher composite takes over rank 1"

        low_after = get_success_data(api.get_retention_entry(entry_low["id"], dean_headers))
        assert low_after["rank_position"] == 2, (
            "the whole scope re-ranked: prior rank-1 entry rewritten to 2"
        )


class TestReappoint:
    def _listed_compliant_faculty(self, api, dept_code):
        dept = _dept_with_term(dept_code)
        faculty = _hired_faculty(dept["id"], "Uma Adjunct", f"uma-{dept_code}@x.edu",
                                 compliance="COMPLIANT")
        entry = get_success_data(api.create_retention_entry(
            retention_entry_payload(faculty["id"], dept["id"], list_term_code="2027SP"),
            DEAN))
        return faculty, entry

    def test_retention_entry_reappoint_happy_path_and_double_reappoint_fails(self, api, dean_headers):
        """PRD Section 3.8: "A successful reappointment moves the entry from
        `LISTED` to `REAPPOINTED` and bumps both the entry's `version` and the
        faculty record's `version`, because the decision touches the faculty row."
        PRD Section 3.8: "Both terminal entry states — `REAPPOINTED` and
        `NON_REAPPOINTED` — are final." — a second reappoint has no transition and
        fails the state gate with `ERR_INVALID_STATE` (Section 2.8).

        Design: Corner/state_machines/retention_entry_reappoint_happy_path_and_double_reappoint_fails
        """
        faculty, entry = self._listed_compliant_faculty(api, "REAP")
        version = get_faculty(faculty["id"])["version"]

        reappointed = validate_success(api.reappoint(
            entry["id"], {"expected_faculty_version": version}, dean_headers), 200)
        assert reappointed["entry_status"] == "REAPPOINTED"

        fresh = get_faculty(faculty["id"])["version"]
        second = api.reappoint(entry["id"], {"expected_faculty_version": fresh}, dean_headers)
        validate_error(second, ApiErrorId.ERR_INVALID_STATE)

    def test_stale_faculty_version_occ_on_reappoint(self, api, dean_headers):
        """PRD Section 3.8: "it carries the OCC token `expected_faculty_version`,
        refused with `ERR_STALE_FACULTY_VERSION` when the token no longer matches
        per Section 2.7."
        PRD Section 3.8: "Creation also flips the faculty's `retention_status` from
        `PROVISIONAL` to `RETENTION_LISTED`, bumping the faculty `version`" — so a
        token observed before the listing is already stale.

        Design: Corner/validations/stale_faculty_version_occ_on_reappoint
        """
        dept = _dept_with_term("OCCR")
        faculty = _hired_faculty(dept["id"], "Flo Adjunct", "flo@x.edu",
                                 compliance="COMPLIANT")
        stale_version = get_faculty(faculty["id"])["version"]
        entry = get_success_data(api.create_retention_entry(
            retention_entry_payload(faculty["id"], dept["id"], list_term_code="2027SP"),
            DEAN))

        stale = api.reappoint(
            entry["id"], {"expected_faculty_version": stale_version}, dean_headers)
        validate_error(stale, ApiErrorId.ERR_STALE_FACULTY_VERSION)

        fresh_version = get_faculty(faculty["id"])["version"]
        ok = api.reappoint(
            entry["id"], {"expected_faculty_version": fresh_version}, dean_headers)
        reappointed = validate_success(ok, 200)
        assert reappointed["entry_status"] == "REAPPOINTED"


class TestNonReappointmentCascade:
    def _listed_faculty_with_future_contract(self, api, dept_code):
        """Compliant, RETENTION_LISTED (list 2027SP) faculty holding one ISSUED
        contract on a 2027SU section — a term starting strictly after the list
        term's start (2027-06-01 > 2027-01-11)."""
        set_clock("2026-06-01T00:00:00Z")
        dept = create_department(code=dept_code, contact_hour_value=1.00)
        create_fall_term()
        # The list term must exist so the cascade can compare term start dates.
        term_sp = create_term(
            code="2027SP", start_date="2027-01-11", end_date="2027-05-07",
            early_census_date="2027-02-01", late_census_date="2027-03-29",
            load_cap_units=9.00)
        open_term(term_sp["id"])
        term_su = create_term(
            code="2027SU", start_date="2027-06-01", end_date="2027-07-30",
            early_census_date="2027-06-14", late_census_date="2027-07-05",
            load_cap_units=9.00)
        open_term(term_su["id"])
        schedule = create_published_schedule(
            dept["id"], education_tier="MASTERS", rate_basis="PER_COURSE",
            base_rate_cents=450000,
            effective_start_date="2026-08-01", effective_end_date="2027-06-30",
        )
        # hired as MASTERS to match the schedule's education_tier
        faculty = _hired_faculty(dept["id"], "Ivy Adjunct", f"ivy-{dept_code}@x.edu",
                                 compliance="COMPLIANT", tier="MASTERS")
        entry = get_success_data(api.create_retention_entry(
            retention_entry_payload(faculty["id"], dept["id"], list_term_code="2027SP"),
            DEAN))
        section = create_section(dept["id"], term_code="2027SU", course_code="ART-101",
                                 weekly_contact_hours=2.0, credit_hours=2, enrollment=15)
        contract = issue_contract(faculty["id"], section["id"], schedule["id"])
        return faculty, entry, contract

    def test_non_reappointment_depth2_cascade_voids_future_contracts(self, api, dean_headers):
        """PRD Section 3.8: "Marking an entry non-reappointed — allowed while that
        entry belongs to the addressed faculty and sits in `LISTED`, and guarded by
        the same `expected_faculty_version` OCC token — moves the entry to
        `NON_REAPPOINTED` and cascades across the faculty record: the faculty's
        `retention_status` becomes `NON_REAPPOINTED`, every `ISSUED` contract of
        that faculty whose section's term starts after the entry's `list_term_code`
        term starts moves to `VOIDED` with `payable_cents` zeroed and any
        `OPEN`-period accruals reversed by clawbacks, and the faculty's load
        aggregates are recomputed."

        Design: Difficulty/transitive_cascade/non_reappointment_depth2_cascade_voids_future_contracts
        """
        faculty, entry, contract = self._listed_faculty_with_future_contract(api, "ART")
        version = get_faculty(faculty["id"])["version"]
        marked = validate_success(api.mark_non_reappointed(
            entry["id"], {"expected_faculty_version": version}, dean_headers), 200)
        assert marked["entry_status"] == "NON_REAPPOINTED"

        faculty_after = get_faculty(faculty["id"])
        assert faculty_after["retention_status"] == "NON_REAPPOINTED"

        contract_after = get_success_data(api.get_contract(contract["id"], ADMIN))
        assert contract_after["contract_status"] == "VOIDED", (
            "the faculty mutation voids the future-dated ISSUED contract"
        )
        assert contract_after["payable_cents"] == 0
        assert faculty_after["current_term_load_units"] == 0.00, (
            "load aggregates recomputed after the void cascade"
        )

    def test_non_reappointment_stale_occ_token_rejected(self, api, dean_headers):
        """PRD Section 2.7: "Three writes carry an optimistic concurrency token
        against the faculty record: `POST /adjunct-hr/contracts` (contract
        issuance), `POST /adjunct-hr/retention-entries/{id}/reappoint`
        (reappointment from a retention entry), and `POST
        /adjunct-hr/retention-entries/{id}/mark-non-reappointed`
        (non-reappointment)." and "If the supplied token does not match the faculty
        record's current `version` at write time — because any earlier mutation,
        including a prior contract issuance or a prior reappointment decision,
        advanced it — the request is rejected with `ERR_STALE_FACULTY_VERSION`
        (HTTP 412)."

        Design: Difficulty/transitive_cascade/non_reappointment_depth2_cascade_voids_future_contracts
        """
        faculty, entry, contract = self._listed_faculty_with_future_contract(api, "ART2")
        stale = api.mark_non_reappointed(
            entry["id"], {"expected_faculty_version": 0}, dean_headers)
        validate_error(stale, ApiErrorId.ERR_STALE_FACULTY_VERSION)
        after = get_success_data(api.get_retention_entry(entry["id"], dean_headers))
        assert after["entry_status"] == "LISTED", "rejected decision leaves the entry LISTED"
