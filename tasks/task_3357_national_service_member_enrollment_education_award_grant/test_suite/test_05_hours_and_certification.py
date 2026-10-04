"""Service hour recording and certification: entry defaults, enum shape,
service-date range, terminal-state guards, prohibited activities, and the
fundraising ten-percent cap (PRD §2.10, §3.5)."""
from test_helpers import (
    ApiErrorId,
    certify_minutes,
    get_enrollment,
    make_grantee_staff_headers,
    setup_active_enrollment,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestHourEntryCreation:
    def test_new_entry_is_pending_with_null_reject_reason(self, api, officer_headers):
        """A freshly recorded entry is PENDING with reject_reason null, and
        nothing accumulates onto the enrollment before certification.

        PRD §3.5: "Every entry is born `PENDING`."
        PRD §3.5: "Rejection is the other terminal outcome: the grantee supplies a `reason`, it is recorded as `reject_reason`, and the entry moves `PENDING` → `REJECTED`."

        Design: Corner/entities/hour_entry_defaults_reject_reason_null
        """
        scenario = setup_active_enrollment()
        staff = make_grantee_staff_headers(scenario["org_id"])
        resp = api.create_hour_entry(
            scenario["enrollment_id"],
            {"service_date": "2026-10-16", "minutes": 480, "activity_code": "DIRECT_SERVICE"},
            staff,
        )
        entry = validate_success(resp, 201)
        assert entry["status"] == "PENDING"
        assert entry["reject_reason"] is None
        assert get_enrollment(scenario["enrollment_id"])["certified_minutes"] == 0

    def test_unknown_activity_code_is_invalid_request(self, api, officer_headers):
        """An activity_code outside the six-value enum fails request-shape
        validation and never reaches the prohibited-activity safety check.

        PRD §3.5: "an `activity_code` of `DIRECT_SERVICE`, `CAPACITY_BUILDING`, `TRAINING`, `FUNDRAISING`, `PROSELYTIZING`, or `PARTISAN_LOBBYING`"
        PRD §2.10: "request shape (`ERR_INVALID_REQUEST` — missing required fields, unknown enum values, range violations)"

        Design: Corner/entities/hour_entry_invalid_activity_code_returns_invalid_request
        """
        scenario = setup_active_enrollment()
        staff = make_grantee_staff_headers(scenario["org_id"])
        resp = api.create_hour_entry(
            scenario["enrollment_id"],
            {"service_date": "2026-10-16", "minutes": 480, "activity_code": "LOBBYING"},
            staff,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        rows, meta = validate_paginated(
            api.list_hour_entries(scenario["enrollment_id"], officer_headers)
        )
        assert rows == [] and meta["total_count"] == 0

    def test_service_date_outside_half_open_period_rejected(self, api):
        """The day before service_start_date and the (exclusive) end date
        itself are out of range; the start date is accepted.

        PRD §3.5: "The `service_date` must fall inside the enrollment's half-open service period — on or after `service_start_date` and strictly before `service_end_date` — or the entry is rejected with `ERR_SERVICE_DATE_OUT_OF_RANGE`."

        Design: Corner/validations/service_date_outside_period_returns_out_of_range
        """
        scenario = setup_active_enrollment()
        staff = make_grantee_staff_headers(scenario["org_id"])
        before = api.create_hour_entry(
            scenario["enrollment_id"],
            {"service_date": "2026-10-14", "minutes": 60, "activity_code": "DIRECT_SERVICE"},
            staff,
        )
        validate_error(before, ApiErrorId.ERR_SERVICE_DATE_OUT_OF_RANGE)
        at_end = api.create_hour_entry(
            scenario["enrollment_id"],
            {"service_date": "2027-08-15", "minutes": 60, "activity_code": "DIRECT_SERVICE"},
            staff,
        )
        validate_error(at_end, ApiErrorId.ERR_SERVICE_DATE_OUT_OF_RANGE)
        at_start = api.create_hour_entry(
            scenario["enrollment_id"],
            {"service_date": "2026-10-15", "minutes": 60, "activity_code": "DIRECT_SERVICE"},
            staff,
        )
        validate_success(at_start, 201)


class TestCertification:
    def test_certify_twice_is_invalid_state_and_no_double_count(self, api):
        """CERTIFIED is terminal: a second certify is rejected and the minutes
        are not added twice.

        PRD §3.5: "A certified entry moves `PENDING` → `CERTIFIED` and adds its `minutes` to the enrollment's `certified_minutes`"
        PRD §2.10: "state guards (`ERR_INVALID_STATE` and its state-specific siblings)"

        Design: Corner/state_machines/certify_certified_entry_returns_invalid_state
        """
        scenario = setup_active_enrollment()
        staff = make_grantee_staff_headers(scenario["org_id"])
        entries = certify_minutes(scenario["enrollment_id"], scenario["org_id"], [480])
        resp = api.certify_hour_entry(entries[0]["id"], staff)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_enrollment(scenario["enrollment_id"])["certified_minutes"] == 480

    def test_prohibited_activity_never_certifies(self, api, officer_headers):
        """A PROSELYTIZING entry can be recorded but certification is always
        rejected, with no status change and no ledger movement.

        PRD §3.5: "the entry's `activity_code` must not be `PROSELYTIZING` or `PARTISAN_LOBBYING` — those two activities are prohibited during service hours and can never be certified (`ERR_PROHIBITED_ACTIVITY`)"

        Design: Corner/validations/prohibited_activity_entry_never_certifies
        """
        scenario = setup_active_enrollment()
        staff = make_grantee_staff_headers(scenario["org_id"])
        entry = validate_success(
            api.create_hour_entry(
                scenario["enrollment_id"],
                {"service_date": "2026-10-16", "minutes": 60, "activity_code": "PROSELYTIZING"},
                staff,
            ),
            201,
        )
        resp = api.certify_hour_entry(entry["id"], staff)
        validate_error(resp, ApiErrorId.ERR_PROHIBITED_ACTIVITY)
        rows, _ = validate_paginated(
            api.list_hour_entries(scenario["enrollment_id"], officer_headers)
        )
        assert rows[0]["status"] == "PENDING"
        assert get_enrollment(scenario["enrollment_id"])["certified_minutes"] == 0

    def test_fundraising_cap_exactly_ten_percent_boundary(self, api):
        """43200 DIRECT + 4800 FUNDRAISING is exactly one tenth of the new
        total (4800 x 10 == 48000 <= 48000, allowed); one further FUNDRAISING
        minute breaks the cap (4801 x 10 == 48010 > 48001).

        PRD §3.5: "the member's `fundraising_certified_minutes` plus the entry's `minutes`, multiplied by 10, must not exceed `certified_minutes` plus the entry's `minutes`. A fundraising share of exactly one tenth of the new total is allowed; one minute beyond it is `ERR_FUNDRAISING_CAP_EXCEEDED`."

        Design: Corner/calculations/fundraising_cap_exactly_10_percent_boundary
        """
        scenario = setup_active_enrollment()
        staff = make_grantee_staff_headers(scenario["org_id"])
        certify_minutes(scenario["enrollment_id"], scenario["org_id"], [43200])
        fund_entry = validate_success(
            api.create_hour_entry(
                scenario["enrollment_id"],
                {"service_date": "2026-10-17", "minutes": 4800, "activity_code": "FUNDRAISING"},
                staff,
            ),
            201,
        )
        certified = validate_success(api.certify_hour_entry(fund_entry["id"], staff))
        assert certified["status"] == "CERTIFIED", "exactly 10% is allowed"
        enrollment = get_enrollment(scenario["enrollment_id"])
        assert enrollment["certified_minutes"] == 48000
        assert enrollment["fundraising_certified_minutes"] == 4800
        over_entry = validate_success(
            api.create_hour_entry(
                scenario["enrollment_id"],
                {"service_date": "2026-10-18", "minutes": 1, "activity_code": "FUNDRAISING"},
                staff,
            ),
            201,
        )
        resp = api.certify_hour_entry(over_entry["id"], staff)
        validate_error(resp, ApiErrorId.ERR_FUNDRAISING_CAP_EXCEEDED)
        rows, _ = validate_paginated(
            api.list_hour_entries(
                scenario["enrollment_id"],
                make_grantee_staff_headers(scenario["org_id"]),
                params={"status": "PENDING"},
            )
        )
        assert any(r["id"] == over_entry["id"] for r in rows), "the rejected entry stays PENDING"
