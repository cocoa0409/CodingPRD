"""Corner coverage: single-rule validation failures mapped to error ids."""

from test_helpers import (
    FIELD_OFFICER_HEADERS,
    ApiErrorId,
    appeal_payload,
    create_election,
    enroll,
    enrollment_payload,
    make_beneficiary_headers,
    make_election,
    premium_determination_payload,
    publish_rate_schedule,
    register_beneficiary,
    set_clock,
    setup_beneficiary_with_ma_coverage,
    setup_billed_enrollment,
    setup_provisional_determination,
    submit_tax_record,
    switch_collection_method_payload,
    validate_error,
)


class TestEnrollmentEndpointRules:
    def test_enroll_part_c_via_enrollments_rejected(self, client):
        """PRD section 3.2: "This route accepts `PART_A`, `PART_B`, and
        `PART_D` only; `PART_C` rows are created exclusively by election
        effectivity (§3.8), and requesting `PART_C` here is rejected with
        `ERR_UNSUPPORTED_PART`."

        Design: Corner/validations/enroll_part_c_via_enrollments_rejected
        """
        set_clock(client, "2026-10-10T00:00:00Z")
        beneficiary = register_beneficiary(client, date_of_birth="1961-12-14")
        response = client.create_enrollment(
            enrollment_payload(beneficiary["id"], "PART_C"),
            headers=make_beneficiary_headers(beneficiary["id"]),
        )
        validate_error(response, ApiErrorId.ERR_UNSUPPORTED_PART)


class TestAppealFilingRules:
    def test_appeal_against_provisional_determination_rejected(self, client):
        """PRD section 3.6: "The target determination must be `FINAL`;
        appealing a `PROVISIONAL` or `SUPERSEDED` determination is rejected
        with `ERR_INVALID_STATE`."

        Design: Corner/validations/appeal_against_provisional_determination_rejected
        """
        beneficiary, _enrollment, determination = setup_provisional_determination(
            client
        )
        assert determination["status"] == "PROVISIONAL"
        response = client.create_appeal(
            appeal_payload(
                determination["id"],
                life_event_type="WORK_REDUCTION",
                event_date="2026-05-01",
                claimed_magi_cents=8000000,
            ),
            headers=make_beneficiary_headers(beneficiary["id"]),
        )
        validate_error(response, ApiErrorId.ERR_INVALID_STATE)


class TestElectionFilingRules:
    def test_oep_election_without_active_ma_rejected(self, client):
        """PRD section 3.8: "An `OEP_MA` election requires an `ACTIVE`
        `PART_C` enrollment to already exist, otherwise
        `ERR_OEP_REQUIRES_MA`". PRD section 3.8: "The checks on filing run in
        a pinned order: the stale-version check first, then the window check
        — a filing outside the requested window's bounds is rejected with
        `ERR_ELECTION_WINDOW_CLOSED` — then the OEP-specific constraints, then
        the target check."

        Design: Corner/validations/oep_election_without_active_ma_rejected
        """
        set_clock(client, "2025-01-10T00:00:00Z")
        beneficiary = register_beneficiary(client, date_of_birth="1960-01-15")
        enroll(client, beneficiary, part="PART_B")
        set_clock(client, "2027-02-10T00:00:00Z")
        response = make_election(client, beneficiary, "OEP_MA", "ORIGINAL")
        validate_error(response, ApiErrorId.ERR_OEP_REQUIRES_MA)

    def test_oep_second_election_same_season_rejected(self, client):
        """PRD section 3.8: "each OEP season admits exactly one election: a
        second attempt within the same season is rejected outright with
        `ERR_OEP_ELECTION_ALREADY_USED`." PRD section 3.8: "an `OEP_MA`
        election takes effect in the month after the election month."

        Design: Corner/validations/oep_second_election_same_season_rejected
        """
        beneficiary, aep_election = setup_beneficiary_with_ma_coverage(client)
        assert aep_election["status"] == "EFFECTIVE"

        set_clock(client, "2027-02-10T00:00:00Z")
        first = create_election(client, beneficiary, "OEP_MA", "ORIGINAL")
        assert first["status"] == "GOVERNING"
        assert first["season_key"] == "OEP-2027"
        assert first["effective_month"] == "2027-03"

        response = make_election(client, beneficiary, "OEP_MA", "MA")
        validate_error(response, ApiErrorId.ERR_OEP_ELECTION_ALREADY_USED)

    def test_election_target_same_as_current_rejected(self, client):
        """PRD section 3.8: "Finally, `target_coverage` must differ from the
        beneficiary's `current_coverage`, otherwise
        `ERR_ELECTION_TARGET_UNCHANGED`."

        Design: Corner/validations/election_target_same_as_current_rejected
        """
        set_clock(client, "2025-01-10T00:00:00Z")
        beneficiary = register_beneficiary(client, date_of_birth="1960-01-15")
        enroll(client, beneficiary, part="PART_B")
        set_clock(client, "2026-10-20T00:00:00Z")
        response = make_election(client, beneficiary, "AEP", "ORIGINAL")
        validate_error(response, ApiErrorId.ERR_ELECTION_TARGET_UNCHANGED)

    def test_election_outside_aep_window_rejected(self, client):
        """PRD section 3.8: "The Annual Election Period runs from October 15
        00:00 UTC through December 7 23:59:59 UTC of a year". PRD section 3.8:
        "a filing outside the requested window's bounds is rejected with
        `ERR_ELECTION_WINDOW_CLOSED`".

        Design: Corner/validations/election_outside_aep_window_rejected
        """
        set_clock(client, "2025-01-10T00:00:00Z")
        beneficiary = register_beneficiary(client, date_of_birth="1960-01-15")
        enroll(client, beneficiary, part="PART_B")
        set_clock(client, "2026-08-15T00:00:00Z")
        response = make_election(client, beneficiary, "AEP", "MA")
        validate_error(response, ApiErrorId.ERR_ELECTION_WINDOW_CLOSED)


class TestDeterminationBusinessRules:
    def test_determination_without_enrollment_for_part_rejected(self, client):
        """PRD section 3.5: "then that a non-`CANCELLED` CoverageEnrollment
        exists for the requested part (`ERR_NO_ENROLLMENT_FOR_PART`)".

        Design: Corner/validations/determination_without_enrollment_for_part_rejected
        """
        publish_rate_schedule(client, 2027)
        beneficiary = register_beneficiary(client, date_of_birth="1960-01-15")
        submit_tax_record(client, beneficiary["id"], 2025, 5000000)
        response = client.create_premium_determination(
            premium_determination_payload(beneficiary["id"], 2027, "PART_B"),
            headers=FIELD_OFFICER_HEADERS,
        )
        validate_error(response, ApiErrorId.ERR_NO_ENROLLMENT_FOR_PART)

    def test_determination_for_unscheduled_year_rejected(self, client):
        """PRD section 3.5: "The endpoint's business checks run in a pinned
        order after the generic pipeline: the part check first, then that a
        RateSchedule exists for the requested `coverage_year`
        (`ERR_RATE_SCHEDULE_MISSING`), then that at least one of the tax years
        two or three years before the coverage year has a TaxReturnRecord
        (`ERR_TAX_DATA_MISSING`)".

        Design: Corner/validations/determination_for_unscheduled_year_rejected
        """
        publish_rate_schedule(client, 2027)
        set_clock(client, "2025-01-10T00:00:00Z")
        beneficiary = register_beneficiary(client, date_of_birth="1960-01-15")
        enroll(client, beneficiary, part="PART_B")
        response = client.create_premium_determination(
            premium_determination_payload(beneficiary["id"], 2029, "PART_B"),
            headers=FIELD_OFFICER_HEADERS,
        )
        validate_error(response, ApiErrorId.ERR_RATE_SCHEDULE_MISSING)

    def test_determination_without_any_tax_data_rejected(self, client):
        """PRD section 3.5: "then that at least one of the tax years two or
        three years before the coverage year has a TaxReturnRecord
        (`ERR_TAX_DATA_MISSING`)".

        Design: Corner/validations/determination_without_any_tax_data_rejected
        """
        publish_rate_schedule(client, 2027)
        set_clock(client, "2025-01-10T00:00:00Z")
        beneficiary = register_beneficiary(client, date_of_birth="1960-01-15")
        enroll(client, beneficiary, part="PART_B")
        response = client.create_premium_determination(
            premium_determination_payload(beneficiary["id"], 2027, "PART_B"),
            headers=FIELD_OFFICER_HEADERS,
        )
        validate_error(response, ApiErrorId.ERR_TAX_DATA_MISSING)


class TestCollectionSwitchRules:
    def test_switch_to_withholding_without_arrangement_rejected(self, client):
        """PRD section 3.7: "Switching to `WITHHOLDING` requires the
        enrollment to currently be in `DIRECT_BILL` — a `DELINQUENT`
        enrollment may not switch — and requires the beneficiary to hold an
        `ACTIVE` WithholdingArrangement, otherwise
        `ERR_NO_ACTIVE_WITHHOLDING`."

        Design: Corner/validations/switch_to_withholding_without_arrangement_rejected
        """
        beneficiary, enrollment, _invoice = setup_billed_enrollment(client)
        assert enrollment["collection_status"] == "DIRECT_BILL"
        response = client.switch_collection_method(
            enrollment["id"],
            switch_collection_method_payload("WITHHOLDING"),
            headers=make_beneficiary_headers(beneficiary["id"]),
        )
        validate_error(response, ApiErrorId.ERR_NO_ACTIVE_WITHHOLDING)
