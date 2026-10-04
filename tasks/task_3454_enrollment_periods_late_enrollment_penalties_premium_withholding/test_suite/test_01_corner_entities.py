"""Corner coverage: entity computed fields, defaults, and uniqueness rules."""

from test_helpers import (
    ApiErrorId,
    BENEFIT_ADMINISTRATOR_HEADERS,
    FIELD_OFFICER_HEADERS,
    IRS_DATA_AGENT_HEADERS,
    NON_EXISTENT_UUID,
    assert_beneficiary,
    assert_employer_coverage_record,
    create_employer_coverage,
    is_valid_uuid,
    list_tax_records,
    make_beneficiary_headers,
    publish_rate_schedule,
    rate_schedule_payload,
    register_beneficiary,
    submit_tax_record,
    tax_record_payload,
    validate_error,
    validate_success,
)


class TestBeneficiaryComputedFields:
    def test_beneficiary_creation_computes_attainment_and_iep(self, client):
        """PRD section 3.1: "A beneficiary born on 1961-12-14 therefore attains
        in 2026-12" and "`iep_start_month` is three months before
        `attainment_month`, and `iep_end_month` is three months after it,
        inclusive on both ends." PRD section 3.1: "Every beneficiary carries a
        `credit_cents` balance, initially 0".

        Design: Corner/entities/beneficiary_creation_computes_attainment_and_iep
        """
        created = register_beneficiary(client, date_of_birth="1961-12-14")
        assert_beneficiary(created)
        assert created["attainment_month"] == "2026-12"
        assert created["iep_start_month"] == "2026-09"
        assert created["iep_end_month"] == "2027-03"
        assert created["credit_cents"] == 0

        read = validate_success(
            client.get_beneficiary(created["id"], headers=FIELD_OFFICER_HEADERS)
        )
        assert read["attainment_month"] == "2026-12"
        assert read["iep_start_month"] == "2026-09"
        assert read["iep_end_month"] == "2027-03"
        assert read["credit_cents"] == 0

    def test_first_of_month_birthday_shifts_attainment_back_one_month(self, client):
        """PRD section 3.1: "when the birth day is the first of the month,
        attainment falls in the month BEFORE the sixty-fifth-birthday month. A
        beneficiary born on 1961-12-14 therefore attains in 2026-12, while one
        born on 1961-12-01 attains in 2026-11."

        Design: Corner/entities/first_of_month_birthday_shifts_attainment_back_one_month
        """
        created = register_beneficiary(client, date_of_birth="1961-12-01")
        assert_beneficiary(created)
        assert created["attainment_month"] == "2026-11"
        assert created["iep_start_month"] == "2026-08"
        assert created["iep_end_month"] == "2027-02"


class TestEnrollmentEndpointValidation:
    def test_enrollment_create_missing_required_fields_rejected(self, client):
        """PRD section 3.2: "Enrollment into coverage is initiated by the
        `Beneficiary` or a `FieldOfficer` with a payload naming the
        `beneficiary_id` and the `part`." PRD section 2.8: "required fields are
        present, types are valid, enum values are in range, month strings parse
        as `YYYY-MM`, and money and MAGI fields are non-negative; otherwise
        `ERR_VALIDATION` (HTTP 400)."

        Design: Corner/entities/enrollment_create_missing_required_fields_rejected
        """
        beneficiary = register_beneficiary(client, date_of_birth="1961-12-14")
        response = client.create_enrollment(
            {}, headers=make_beneficiary_headers(beneficiary["id"])
        )
        validate_error(response, ApiErrorId.ERR_VALIDATION)

    def test_get_enrollment_unknown_id_returns_404(self, client):
        """PRD section 2.8: "then, as applicable, `ERR_ENROLLMENT_NOT_FOUND`,
        `ERR_COVERAGE_RECORD_NOT_FOUND`, `ERR_DETERMINATION_NOT_FOUND`,
        `ERR_APPEAL_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`,
        `ERR_ARRANGEMENT_NOT_FOUND`, or `ERR_RELIEF_CASE_NOT_FOUND` (all
        HTTP 404) for the corresponding nested resource."

        Design: Corner/entities/get_enrollment_unknown_id_returns_404
        """
        register_beneficiary(client, date_of_birth="1961-12-14")
        response = client.get_enrollment(
            NON_EXISTENT_UUID, headers=FIELD_OFFICER_HEADERS
        )
        validate_error(response, ApiErrorId.ERR_ENROLLMENT_NOT_FOUND)


class TestSystemManagedFields:
    def test_beneficiary_create_client_supplied_system_fields_input_ignored(
        self, client
    ):
        """PRD section 2.5: "`id` (string): a unique, server-generated
        identifier formatted as a UUID, with no type prefix." PRD section 2.5:
        "`version` (integer): a system-managed integer that increments with
        every modification to the resource".

        Design: Corner/entities/beneficiary_create_client_supplied_system_fields_input_ignored
        """
        supplied_id = "11111111-1111-1111-1111-111111111111"
        response = client.create_beneficiary(
            {
                "full_name": "Sys Fields",
                "date_of_birth": "1961-12-14",
                "id": supplied_id,
                "version": 99,
            },
            headers=FIELD_OFFICER_HEADERS,
        )
        created = validate_success(response, 201)
        assert created["id"] != supplied_id, "server must mint its own id"
        assert is_valid_uuid(created["id"])
        assert created["version"] != 99, "client-supplied version must be ignored"

        read = validate_success(
            client.get_beneficiary(created["id"], headers=FIELD_OFFICER_HEADERS)
        )
        assert read["id"] == created["id"]
        assert read["version"] == created["version"]


class TestUniquenessConstraints:
    def test_rate_schedule_second_row_same_year_rejected(self, client):
        """PRD section 3.5: "the `coverage_year` (unique across all schedules —
        republishing a year is rejected with `ERR_DUPLICATE_RATE_SCHEDULE`)".

        Design: Corner/entities/rate_schedule_second_row_same_year_rejected
        """
        publish_rate_schedule(client, 2026)
        response = client.create_rate_schedule(
            rate_schedule_payload(
                part_b_standard_cents=18600, part_d_national_base_cents=3460
            ),
            headers=BENEFIT_ADMINISTRATOR_HEADERS,
        )
        validate_error(response, ApiErrorId.ERR_DUPLICATE_RATE_SCHEDULE)

    def test_tax_record_second_row_same_year_rejected(self, client):
        """PRD section 3.5: "A beneficiary may hold at most one record per tax
        year; a duplicate submission is rejected with `ERR_DUPLICATE_TAX_YEAR`."

        Design: Corner/entities/tax_record_second_row_same_year_rejected
        """
        beneficiary = register_beneficiary(client, date_of_birth="1960-01-15")
        submit_tax_record(client, beneficiary["id"], 2024, 9000000)
        response = client.create_tax_record(
            tax_record_payload(beneficiary["id"], 2024, 9100000),
            headers=IRS_DATA_AGENT_HEADERS,
        )
        validate_error(response, ApiErrorId.ERR_DUPLICATE_TAX_YEAR)

        records = list_tax_records(client, beneficiary)
        assert len(records) == 1, "the duplicate must not have been stored"
        assert records[0]["magi_cents"] == 9000000

    def test_employer_coverage_defaults_and_initial_states(self, client):
        """PRD section 3.3: "optionally the `coverage_end_month` (default null,
        meaning ongoing), the `employment_end_month` (default null, meaning
        still employed), and `is_drug_coverage_creditable` (default false)".
        PRD section 3.3: "A new record is created with `verification_status`
        `UNVERIFIED` and `record_status` `ACTIVE_COVERAGE`."

        Design: Corner/entities/employer_coverage_defaults_and_initial_states
        """
        beneficiary = register_beneficiary(client, date_of_birth="1961-03-10")
        record = create_employer_coverage(
            client,
            beneficiary,
            employer_name="ACME",
            employer_size=30,
            coverage_start_month="2024-01",
        )
        assert_employer_coverage_record(record)
        assert record["is_drug_coverage_creditable"] is False
        assert record["verification_status"] == "UNVERIFIED"
        assert record["record_status"] == "ACTIVE_COVERAGE"
        assert record["coverage_end_month"] is None
        assert record["employment_end_month"] is None
