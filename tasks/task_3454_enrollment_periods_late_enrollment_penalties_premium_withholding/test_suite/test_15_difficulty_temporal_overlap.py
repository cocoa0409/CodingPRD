"""Difficulty coverage: interval-overlap geometry — closed month intervals on
employer coverage records vs half-open intervals on enrollments."""

from test_helpers import (
    ApiErrorId,
    adjudicate_relief_case,
    employer_coverage_payload,
    file_relief_case,
    list_enrollments,
    list_penalties,
    make_beneficiary_headers,
    register_beneficiary,
    relief_case_payload,
    setup_terminated_enrollment_interval,
    create_employer_coverage,
    validate_error,
    validate_success,
)


class TestEmployerCoverageClosedIntervalTouchRejected:
    """Record A covers the closed interval [2024-01, 2026-08]; a second ACME
    record starting in 2026-08 shares the boundary month and collides."""

    def _register_acme_record(self, client):
        beneficiary = register_beneficiary(
            client, date_of_birth="1961-03-10", full_name="Olive Overlap"
        )
        create_employer_coverage(
            client,
            beneficiary,
            employer_name="ACME",
            employer_size=30,
            coverage_start_month="2024-01",
            coverage_end_month="2026-08",
        )
        return beneficiary

    def test_record_sharing_boundary_month_collides(self, client):
        """PRD section 2.9: "An **EmployerCoverageRecord** covers the CLOSED
        month interval from `coverage_start_month` through
        `coverage_end_month`, both inclusive". PRD section 3.3: "Registration
        rejects — with
        `ERR_COVERAGE_PERIOD_OVERLAP` — any record whose closed coverage
        interval shares even one calendar month with another non-`REJECTED`
        record for the same beneficiary and the same `employer_name`."

        Design: Difficulty/resource_temporal_overlap/employer_coverage_closed_interval_touch_rejected
        """
        beneficiary = self._register_acme_record(client)
        response = client.create_employer_coverage(
            employer_coverage_payload(
                beneficiary["id"],
                employer_name="ACME",
                employer_size=30,
                coverage_start_month="2026-08",
            ),
            headers=make_beneficiary_headers(beneficiary["id"]),
        )
        validate_error(response, ApiErrorId.ERR_COVERAGE_PERIOD_OVERLAP)

    def test_record_starting_after_end_month_accepted(self, client):
        """PRD section 2.9: "Two records for the same beneficiary and the same
        `employer_name` that share even one calendar month collide." (The
        month after a closed interval's end shares no month with it.)

        Design: Difficulty/resource_temporal_overlap/employer_coverage_closed_interval_touch_rejected
        """
        beneficiary = self._register_acme_record(client)
        response = client.create_employer_coverage(
            employer_coverage_payload(
                beneficiary["id"],
                employer_name="ACME",
                employer_size=30,
                coverage_start_month="2026-09",
            ),
            headers=make_beneficiary_headers(beneficiary["id"]),
        )
        created = validate_success(response, 201)
        assert created["coverage_start_month"] == "2026-09"
        assert created["verification_status"] == "UNVERIFIED"


class TestReliefRetroIntervalHalfOpenTouchAllowed:
    """A terminated PART_B enrollment leaves the half-open interval
    [2026-01, 2026-06); a retro request at 2026-05 collides, one at 2026-06
    merely touches and is allowed."""

    def test_relief_month_inside_terminated_interval_collides(self, client):
        """PRD section 3.9: "The retroactive interval — from the
        `requested_effective_month` up to but not including the clock month —
        must not overlap any existing same-part enrollment interval, with
        half-open adjacency explicitly allowed: an existing interval ending
        exactly in the requested month does not collide." PRD section 3.9: "A
        collision is rejected with `ERR_RELIEF_PERIOD_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/relief_retro_interval_half_open_touch_allowed
        """
        beneficiary, enrollment = setup_terminated_enrollment_interval(client)
        assert enrollment["enrollment_status"] == "TERMINATED"
        assert enrollment["effective_month"] == "2026-01"
        assert enrollment["end_month"] == "2026-06"

        response = client.create_equitable_relief_case(
            relief_case_payload(
                beneficiary["id"],
                relief_type="RETROACTIVE_ENROLLMENT",
                part="PART_B",
                claimed_misinform_source="PLAN_REPRESENTATIVE",
                description="told coverage ended in May",
                requested_effective_month="2026-05",
            ),
            headers=make_beneficiary_headers(beneficiary["id"]),
        )
        validate_error(response, ApiErrorId.ERR_RELIEF_PERIOD_OVERLAP)

    def test_relief_month_touching_interval_end_allowed(self, client):
        """PRD section 2.9: "Two same-part intervals that merely touch — one
        ending in the month the other begins — do NOT overlap." PRD
        section 3.9: "one is created with `effective_month` set to the
        requested month — relief-created enrollments take that month verbatim,
        bypassing the window-based effective-month rules of §3.2, and are
        recorded with `enrolled_via_window` `RELIEF` — landing `ACTIVE`
        immediately when the requested month is not after the clock month and
        `PENDING` otherwise."

        Design: Difficulty/resource_temporal_overlap/relief_retro_interval_half_open_touch_allowed
        """
        beneficiary, enrollment = setup_terminated_enrollment_interval(client)
        case = file_relief_case(
            client,
            beneficiary,
            relief_type="RETROACTIVE_ENROLLMENT",
            part="PART_B",
            claimed_misinform_source="PLAN_REPRESENTATIVE",
            description="told coverage ended in May",
            requested_effective_month="2026-06",
        )
        assert case["status"] == "UNDER_INVESTIGATION"

        adjudicate_relief_case(client, case, decision="GRANTED")

        enrollments = list_enrollments(client, beneficiary)
        assert len(enrollments) == 2
        assert enrollments[0]["id"] == enrollment["id"]
        assert enrollments[0]["enrollment_status"] == "TERMINATED"
        retro = enrollments[1]
        assert retro["effective_month"] == "2026-06"
        assert retro["enrollment_status"] == "ACTIVE"
        assert retro["enrolled_via_window"] == "RELIEF"
        assert retro["part"] == "PART_B"

        # The retro span [2026-04 .. 2026-05] is fully covered by the
        # terminated interval, so no penalty arises from the new enrollment.
        assert list_penalties(client, beneficiary) == []
