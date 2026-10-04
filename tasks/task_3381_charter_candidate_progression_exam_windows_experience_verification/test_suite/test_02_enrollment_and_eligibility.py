"""Program enrollment: request shape, pathway eligibility, initial state,
payments, ownership, and the computed curriculum-access list."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    PROGRAM_FEE_CENTS,
    assert_program_enrollment,
    create_candidate,
    create_curriculum_cycle,
    create_enrollment_pending,
    create_exam_level,
    create_program_enrollment_payload,
    get_program_enrollment,
    list_program_enrollments,
    make_candidate_headers,
    pay_enrollment,
    payment_payload,
    set_logical_clock,
    validate_error,
    validate_success,
)

CLOCK = "2027-01-05T00:00:00Z"


class TestEnrollmentAndEligibility:
    def test_enrollment_missing_pathway_returns_invalid_request(self, api, program_admin_headers):
        """PRD §3.1: "The enrollment request declares a `pathway` of either
        `EDUCATION` or `WORK_EXPERIENCE`, and each pathway demands its own
        inputs."
        PRD §2.6: "Required fields must be present, types must be correct, enum
        values must belong to their declared sets, numeric ranges must hold,
        payload fields unknown to the endpoint are rejected outright,
        pathway-conditional fields must accompany their pathway, a reschedule
        must carry at least one change field, and an adjudication with a
        sanctioning outcome must name a sanction type."

        Design: Corner/entities/c_enrollment_missing_pathway_returns_invalid_request
        """
        set_logical_clock(CLOCK)
        candidate = create_candidate()
        resp = api.create_program_enrollment(
            candidate["id"],
            {"degree_completed": True, "graduation_date": "2023-05-15"},
            program_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        assert resp.status_code == 400
        assert list_program_enrollments(params={"candidate_id": candidate["id"]}) == []

    def test_enrollment_scholarship_omitted_defaults_to_zero(self, api, program_admin_headers):
        """PRD §3.1: "An optional `scholarship_pct` between 0 and 0.5 inclusive,
        defaulting to 0, records a per-line discount that applies to the program
        fee and to exam fees — but never to reschedule fees."
        PRD §3.1: "Creation posts the program's enrollment charge: a list price
        of 35,003 cents, discounted per line by the enrollment's
        `scholarship_pct` with half-up rounding before the line enters
        `lifetime_charges_cents` (§2.8)."

        Design: Corner/entities/c_enrollment_scholarship_omitted_defaults_to_zero
        """
        set_logical_clock(CLOCK)
        candidate = create_candidate()
        resp = api.create_program_enrollment(
            candidate["id"], create_program_enrollment_payload(), program_admin_headers
        )
        data = validate_success(resp, 201)
        assert_program_enrollment(data)
        assert data["scholarship_pct"] == 0
        assert data["lifetime_charges_cents"] == PROGRAM_FEE_CENTS
        assert data["outstanding_balance_cents"] == PROGRAM_FEE_CENTS

    def test_enrollment_invalid_pathway_enum_rejected(self, api, program_admin_headers):
        """PRD §2.6: "Required fields must be present, types must be correct,
        enum values must belong to their declared sets, numeric ranges must
        hold, payload fields unknown to the endpoint are rejected outright,
        pathway-conditional fields must accompany their pathway, a reschedule
        must carry at least one change field, and an adjudication with a
        sanctioning outcome must name a sanction type."

        Design: Corner/entities/c_enrollment_invalid_pathway_enum_rejected
        """
        set_logical_clock(CLOCK)
        candidate = create_candidate()
        resp = api.create_program_enrollment(
            candidate["id"],
            create_program_enrollment_payload(
                pathway="PHD", degree_completed=True, graduation_date="2023-05-15"
            ),
            program_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        assert resp.status_code == 400
        assert list_program_enrollments(params={"candidate_id": candidate["id"]}) == []

    def test_enrollment_under_unknown_candidate_returns_404(self, api, program_admin_headers):
        """PRD §2.6: "Each identifier embedded in the URL path is resolved in
        left-to-right order, and the first one that does not exist fails the
        request with its own entity-specific error"

        Design: Corner/entities/c_enrollment_under_unknown_candidate_returns_404
        """
        set_logical_clock(CLOCK)
        resp = api.create_program_enrollment(
            NON_EXISTENT_UUID,
            create_program_enrollment_payload(),
            program_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_CANDIDATE_NOT_FOUND)
        assert resp.status_code == 404

    def test_enrollment_initial_state_pending_payment(self, api, program_admin_headers):
        """PRD §3.1: "The enrollment is born in `PENDING_PAYMENT`, and while it
        remains there its `curriculum_access_cycle_ids` list is empty."
        PRD §3.1: "Much later, a successful charter award stamps the
        enrollment's `chartered_at` with the logical clock (§3.8)."

        Design: Corner/state_machines/c_enrollment_initial_state_pending_payment
        """
        set_logical_clock(CLOCK)
        candidate = create_candidate()
        resp = api.create_program_enrollment(
            candidate["id"], create_program_enrollment_payload(), program_admin_headers
        )
        data = validate_success(resp, 201)
        assert_program_enrollment(data)
        assert data["status"] == "PENDING_PAYMENT"
        assert data["version"] == 1
        assert data["chartered_at"] is None

    def test_work_path_requires_both_months_and_hours(self, api, program_admin_headers):
        """PRD §3.1: "Under `WORK_EXPERIENCE`, the candidate qualifies when they
        declare at least 36 months of experience **and** at least 4,000 hours of
        it."
        PRD §3.1: "An ineligible request is rejected with
        `ERR_ELIGIBILITY_NOT_MET` (HTTP 422) and no enrollment is created."

        Design: Corner/validations/c_work_path_requires_both_months_and_hours
        """
        set_logical_clock(CLOCK)
        candidate = create_candidate()
        resp = api.create_program_enrollment(
            candidate["id"],
            {
                "pathway": "WORK_EXPERIENCE",
                "declared_work_months": 40,
                "declared_work_hours": 3999,
            },
            program_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_ELIGIBILITY_NOT_MET)
        assert resp.status_code == 422
        assert list_program_enrollments(params={"candidate_id": candidate["id"]}) == []

    def test_education_graduation_23_month_boundary(self, api, program_admin_headers):
        """PRD §3.1: "Under `EDUCATION`, the candidate qualifies when their
        degree is completed, or when the graduation date lies strictly in the
        future and the whole-calendar-month distance from today to that date is
        at most 23 months."
        PRD §2.9: "take the difference in calendar years multiplied by twelve,
        add the difference in month numbers, and subtract one if the end date's
        day-of-month is earlier than the start date's day-of-month."

        Design: Corner/validations/c_education_graduation_23_month_boundary
        """
        set_logical_clock(CLOCK)
        cand_e = create_candidate(
            email="e.cand@example.com",
            full_name="E Candidate",
            date_of_birth="1999-02-02",
            gov_id_number="GOV-E-1005",
        )
        cand_f = create_candidate(
            email="f.cand@example.com",
            full_name="F Candidate",
            date_of_birth="1999-03-03",
            gov_id_number="GOV-F-1006",
        )
        resp_e = api.create_program_enrollment(
            cand_e["id"],
            {
                "pathway": "EDUCATION",
                "degree_completed": False,
                "graduation_date": "2028-12-05",
            },
            program_admin_headers,
        )
        data_e = validate_success(resp_e, 201)
        assert data_e["status"] == "PENDING_PAYMENT"
        assert data_e["lifetime_charges_cents"] == PROGRAM_FEE_CENTS
        resp_f = api.create_program_enrollment(
            cand_f["id"],
            {
                "pathway": "EDUCATION",
                "degree_completed": False,
                "graduation_date": "2029-01-05",
            },
            program_admin_headers,
        )
        validate_error(resp_f, ApiErrorId.ERR_ELIGIBILITY_NOT_MET)
        assert resp_f.status_code == 422

    def test_payment_nonpositive_rejected(self, api, program_admin_headers):
        """PRD §3.1: "Payments are applied by the candidate or a `ProgramAdmin`
        in `amount_cents`; a non-positive amount is rejected with
        `ERR_INVALID_PAYMENT_AMOUNT`."

        Design: Corner/errors/c_payment_nonpositive_rejected
        """
        set_logical_clock(CLOCK)
        candidate = create_candidate()
        enrollment = create_enrollment_pending(candidate["id"])
        resp = api.post_enrollment_payment(
            enrollment["id"], payment_payload(0), program_admin_headers
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_PAYMENT_AMOUNT)
        assert resp.status_code == 400
        after = get_program_enrollment(enrollment["id"])
        assert after["lifetime_payments_cents"] == 0
        assert after["status"] == "PENDING_PAYMENT"

    def test_curriculum_access_empty_until_enrolled(self, api, program_admin_headers):
        """PRD §3.1: "The enrollment is born in `PENDING_PAYMENT`, and while it
        remains there its `curriculum_access_cycle_ids` list is empty."
        PRD §2.10: "While it is `ENROLLED`, the list contains the `PUBLISHED`
        curriculum cycles of every level up to and including the candidate's
        **lowest unpassed** level."
        PRD §3.1: "The moment the outstanding balance reaches zero, the
        enrollment automatically advances from `PENDING_PAYMENT` to `ENROLLED`
        and its curriculum access list is recomputed per §2.10."

        Design: Corner/entities/c_curriculum_access_empty_until_enrolled
        """
        set_logical_clock(CLOCK)
        candidate = create_candidate()
        level = create_exam_level()
        cycle = create_curriculum_cycle(level["id"])
        enrollment = create_enrollment_pending(candidate["id"])
        pre = list_program_enrollments(params={"candidate_id": candidate["id"]})
        assert pre[0]["curriculum_access_cycle_ids"] == []
        resp = api.post_enrollment_payment(
            enrollment["id"], payment_payload(PROGRAM_FEE_CENTS), program_admin_headers
        )
        data = validate_success(resp, 200)
        assert data["status"] == "ENROLLED"
        assert data["curriculum_access_cycle_ids"] == [cycle["id"]]

    def test_candidate_cannot_pay_others_enrollment(self, api):
        """PRD §2.1: "When `X-User-Role` is `Candidate`, `X-User-ID` is the `id`
        of the acting `Candidate`; ownership checks on any resource that
        references a candidate compare the resource's candidate foreign key to
        `X-User-ID`, and a mismatch is rejected with `ERR_OWNERSHIP_MISMATCH`
        (HTTP 403)."

        Design: Corner/rbac/c_candidate_cannot_pay_others_enrollment
        """
        set_logical_clock(CLOCK)
        cand_a = create_candidate()
        cand_b = create_candidate(
            email="b.cand@example.com",
            full_name="B Candidate",
            date_of_birth="1993-09-30",
            gov_id_number="GOV-B-1002",
        )
        enrollment = create_enrollment_pending(cand_a["id"])
        resp = api.post_enrollment_payment(
            enrollment["id"],
            payment_payload(PROGRAM_FEE_CENTS),
            make_candidate_headers(cand_b["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_OWNERSHIP_MISMATCH)
        assert resp.status_code == 403
        own = pay_enrollment(
            enrollment["id"], PROGRAM_FEE_CENTS, as_candidate_id=cand_a["id"]
        )
        assert own["status"] == "ENROLLED"
