"""Registry resources: department/term/section creation rules (PRD Sections 2.5, 2.9, 3.1, 3.5)."""
from test_helpers import (
    ABSENT_UUID,
    ApiErrorId,
    assert_department,
    assert_section,
    create_department,
    create_term,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_success,
)


class TestDepartmentRegistry:
    def test_department_creation_applies_defaults_and_system_fields(self, api, hr_admin_headers):
        """PRD Section 3.1: "an `active` flag that defaults to true when omitted at
        creation."
        PRD Section 2.5: "Every entity exposed by the API carries an `id` — a
        server-minted UUID with no type prefix — and a `created_at` timestamp
        recording when the record was created."

        Design: Corner/entities/department_creation_applies_defaults_and_system_fields
        """
        resp = api.create_department(
            {"code": "GEOG", "name": "Geography", "contact_hour_value": 1.25},
            hr_admin_headers,
        )
        dept = validate_success(resp, 201)
        assert_department(dept)
        assert dept["active"] is True, "active must default to true when omitted"
        assert is_valid_uuid(dept["id"]), "id must be a server-minted bare UUID"
        assert is_iso8601_timestamp(dept["created_at"])
        assert is_iso8601_timestamp(dept["updated_at"])
        assert isinstance(dept["version"], int) and dept["version"] >= 1

    def test_department_duplicate_code_rejected(self, api, hr_admin_headers):
        """PRD Section 2.9: "Uniqueness violations surface as `ERR_DUPLICATE`
        (HTTP 409). A department's `code` is unique across all departments and must
        be two to twelve uppercase alphanumeric characters."

        Design: Corner/entities/department_duplicate_code_rejected
        """
        first = api.create_department(
            {"code": "GEOG", "name": "Geography", "contact_hour_value": 1.00},
            hr_admin_headers,
        )
        validate_success(first, 201)
        dup = api.create_department(
            {"code": "GEOG", "name": "Geology Duplicate", "contact_hour_value": 2.00},
            hr_admin_headers,
        )
        validate_error(dup, ApiErrorId.ERR_DUPLICATE)

    def test_department_get_not_found(self, api, hr_admin_headers):
        """PRD Section 2.5: "an unresolvable identifier anywhere in the path fails
        the request with `ERR_NOT_FOUND` before any query parameter or body field
        is examined."

        Design: Corner/entities/department_get_not_found
        """
        resp = api.get_department(ABSENT_UUID, hr_admin_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestTermRegistry:
    def test_term_creation_invalid_date_span(self, api, hr_admin_headers):
        """PRD Section 3.1: "Date coherence is enforced at creation: the `end_date`
        must fall after the `start_date` with a span of at least fourteen days, and
        the census boundaries must satisfy the ordering in which `start_date` falls
        on or before `early_census_date`, `early_census_date` falls strictly before
        `late_census_date`, and `late_census_date` falls on or before `end_date`.
        Violations are refused with `ERR_INVALID_DATE_RANGE`."

        Design: Corner/entities/term_creation_invalid_date_span
        """
        short_span = api.create_term(
            {
                "code": "2026WI",
                "start_date": "2026-01-05",
                "end_date": "2026-01-14",
                "early_census_date": "2026-01-08",
                "late_census_date": "2026-01-12",
                "load_cap_units": 4.50,
            },
            hr_admin_headers,
        )
        validate_error(short_span, ApiErrorId.ERR_INVALID_DATE_RANGE)

        inverted_census = api.create_term(
            {
                "code": "2026SP",
                "start_date": "2026-01-12",
                "end_date": "2026-05-08",
                "early_census_date": "2026-04-01",
                "late_census_date": "2026-02-01",
                "load_cap_units": 4.50,
            },
            hr_admin_headers,
        )
        validate_error(inverted_census, ApiErrorId.ERR_INVALID_DATE_RANGE)

    def test_term_duplicate_code_rejected(self, api, hr_admin_headers):
        """PRD Section 2.9: "A term's `code` is unique."

        Design: Corner/entities/term_duplicate_code_rejected
        """
        first = api.create_term(
            {
                "code": "2026FA",
                "start_date": "2026-08-24",
                "end_date": "2026-12-11",
                "early_census_date": "2026-09-14",
                "late_census_date": "2026-11-02",
                "load_cap_units": 4.50,
            },
            hr_admin_headers,
        )
        validate_success(first, 201)
        dup = api.create_term(
            {
                "code": "2026FA",
                "start_date": "2026-08-25",
                "end_date": "2026-12-12",
                "early_census_date": "2026-09-15",
                "late_census_date": "2026-11-03",
                "load_cap_units": 6.00,
            },
            hr_admin_headers,
        )
        validate_error(dup, ApiErrorId.ERR_DUPLICATE)


class TestSectionRegistry:
    def test_section_natural_key_uniqueness(self, api, chair_headers):
        """PRD Section 3.5: "The natural key of `term_code`, `course_code`, and
        `section_code` must be unique, with conflicts refused as `ERR_DUPLICATE`."

        Design: Corner/entities/section_natural_key_uniqueness
        """
        dept = create_department(code="PSYC", name="Psychology", contact_hour_value=1.00)
        create_term(code="2026FA")
        create_term(
            code="2027SP",
            start_date="2027-01-11",
            end_date="2027-05-07",
            early_census_date="2027-02-01",
            late_census_date="2027-03-29",
        )
        first = api.create_section(
            {
                "department_id": dept["id"],
                "term_code": "2026FA",
                "course_code": "PSY-101",
                "section_code": "01",
                "weekly_contact_hours": 3.0,
                "credit_hours": 3,
                "enrollment": 20,
                "min_enrollment": 5,
            },
            chair_headers,
        )
        validate_success(first, 201)

        dup = api.create_section(
            {
                "department_id": dept["id"],
                "term_code": "2026FA",
                "course_code": "PSY-101",
                "section_code": "01",
                "weekly_contact_hours": 4.0,
                "credit_hours": 4,
                "enrollment": 10,
                "min_enrollment": 2,
            },
            chair_headers,
        )
        validate_error(dup, ApiErrorId.ERR_DUPLICATE)

        other_term = api.create_section(
            {
                "department_id": dept["id"],
                "term_code": "2027SP",
                "course_code": "PSY-101",
                "section_code": "01",
                "weekly_contact_hours": 3.0,
                "credit_hours": 3,
                "enrollment": 10,
                "min_enrollment": 2,
            },
            chair_headers,
        )
        section = validate_success(other_term, 201)
        assert_section(section)
        assert section["term_code"] == "2027SP", (
            "same course+section in a different term is a different natural key"
        )
