"""Service standards: facility creation, rule windows, committed-date computation."""
from test_helpers import (
    ApiErrorId,
    create_facility_payload,
    create_rule_payload,
    create_service_query_payload,
    get_success_data,
    reset_clock,
    set_clock,
    validate_error,
    validate_success,
    TEST_USERS,
    make_platform_admin_headers,
    NON_EXISTENT_UUID,
)

SSA = TEST_USERS["standards_admin_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]
SUP = TEST_USERS["supervisor_headers"]


class TestFacilityCreation:

    def test_facility_create_returns_declared_fields_and_active_status(self, api):
        """PRD §3.1: "New facilities enter with `status` set to `ACTIVE`".
        PRD §2.10: "All primary resources include a standard set of system-managed
        fields".

        Design: Corner/entities/facility_create_returns_declared_fields_and_active_status
        """
        reset_clock()
        resp = api.create_facility(
            create_facility_payload(
                facility_code="PDX", facility_type="S_AND_DC",
                region_class="CONTIGUOUS", dispatch_cutoff_local="16:30",
                operating_days=["MON", "TUE", "WED", "THU", "FRI", "SAT"]),
            SSA)
        data = validate_success(resp, expected_status=201)
        assert data["facility_code"] == "PDX"
        assert data["facility_type"] == "S_AND_DC"
        assert data["region_class"] == "CONTIGUOUS"
        assert data["status"] == "ACTIVE"
        assert data["version"] == 1


class TestCommittedDeliveryDate:

    def test_cutoff_rollover_advances_acceptance_to_next_operating_day(self, api):
        """PRD §3.2: "When `acceptance_time_local` is later than the origin
        facility's `dispatch_cutoff_local`, acceptance is treated as occurring on
        the next origin operating day: the acceptance date advances by one calendar
        day and then skips forward until it lands on a day present in the origin's
        `operating_days`."

        Design: Corner/calculations/service_standard_cutoff_rollover_and_operating_day_skips
        """
        reset_clock()
        lax = get_success_data(api.create_facility(
            create_facility_payload(facility_code="LAX", region_class="CONTIGUOUS",
                                    dispatch_cutoff_local="17:00"), SSA))
        jfk = get_success_data(api.create_facility(
            create_facility_payload(facility_code="JFK", region_class="CONTIGUOUS",
                                    dispatch_cutoff_local="18:00"), SSA))
        get_success_data(api.create_service_rule(
            lax["id"],
            create_rule_payload(jfk["id"], lax["version"], mail_class="PRIORITY",
                                service_days=2, non_contiguous_extra_days=2,
                                effective_from="2026-01-01"), SSA))
        # Friday 2026-09-04 at 17:01 — after the 17:00 cutoff → acceptance rolls to Sat 09-05.
        q_after = get_success_data(api.create_service_query(
            create_service_query_payload(lax["id"], jfk["id"], mail_class="PRIORITY",
                                         acceptance_date="2026-09-04",
                                         acceptance_time_local="17:01"), SSA))
        assert q_after["committed_delivery_date"] == "2026-09-07"
        assert q_after["variant_used"] == "CONTIGUOUS"
        assert q_after["committed_service_days"] == 2

    def test_before_cutoff_acceptance_day_starts_the_roll(self, api):
        """PRD §3.2: "When `acceptance_time_local` is later than the origin
        facility's `dispatch_cutoff_local`, acceptance is treated as occurring on
        the next origin operating day" — before the cutoff, no advance happens.

        Design: Corner/calculations/service_standard_cutoff_rollover_and_operating_day_skips
        """
        reset_clock()
        lax = get_success_data(api.create_facility(
            create_facility_payload(facility_code="LAX", region_class="CONTIGUOUS",
                                    dispatch_cutoff_local="17:00"), SSA))
        jfk = get_success_data(api.create_facility(
            create_facility_payload(facility_code="JFK", region_class="CONTIGUOUS",
                                    dispatch_cutoff_local="18:00"), SSA))
        get_success_data(api.create_service_rule(
            lax["id"],
            create_rule_payload(jfk["id"], lax["version"], mail_class="PRIORITY",
                                service_days=2, non_contiguous_extra_days=2,
                                effective_from="2026-01-01"), SSA))
        # Friday 2026-09-04 at 16:59 — before cutoff: Fri + Sat are the 2 service days.
        q_before = get_success_data(api.create_service_query(
            create_service_query_payload(lax["id"], jfk["id"], mail_class="PRIORITY",
                                         acceptance_date="2026-09-04",
                                         acceptance_time_local="16:59"), SSA))
        assert q_before["committed_delivery_date"] == "2026-09-05"
        assert q_before["variant_used"] == "CONTIGUOUS"
        assert q_before["committed_service_days"] == 2

    def test_no_service_rule_for_lane(self, api):
        """PRD §3.2: "Exactly one rule must match: zero matches are rejected with
        `ERR_NO_SERVICE_RULE` (HTTP 422)".

        Design: Corner/validations/no_service_rule_for_lane
        """
        reset_clock()
        lax = get_success_data(api.create_facility(
            create_facility_payload(facility_code="LAX", region_class="CONTIGUOUS"), SSA))
        jfk = get_success_data(api.create_facility(
            create_facility_payload(facility_code="JFK", region_class="CONTIGUOUS",
                                    dispatch_cutoff_local="18:00"), SSA))
        get_success_data(api.create_service_rule(
            lax["id"],
            create_rule_payload(jfk["id"], lax["version"], mail_class="MARKETING",
                                service_days=5, effective_from="2027-01-01"), SSA))
        # No rule at all for FIRST_CLASS.
        resp1 = api.create_service_query(
            create_service_query_payload(lax["id"], jfk["id"], mail_class="FIRST_CLASS",
                                         acceptance_date="2026-09-01",
                                         acceptance_time_local="10:00"), SSA)
        validate_error(resp1, ApiErrorId.ERR_NO_SERVICE_RULE)
        # MARKETING rule exists but its window opens 2027-01-01, after acceptance.
        resp2 = api.create_service_query(
            create_service_query_payload(lax["id"], jfk["id"], mail_class="MARKETING",
                                         acceptance_date="2026-09-01",
                                         acceptance_time_local="10:00"), SSA)
        validate_error(resp2, ApiErrorId.ERR_NO_SERVICE_RULE)


class TestRuleWindows:

    def test_end_adjacent_rule_window_is_conflict(self, api):
        """PRD §3.1: "the boundary is strict: end-adjacency, where one rule's
        `effective_to` equals the next rule's `effective_from`, is itself a conflict,
        so a succeeding window must begin strictly after the predecessor's last day.
        A violation of this overlap check is rejected with `ERR_WINDOW_OVERLAP`
        (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/service_rule_window_end_adjacency_is_conflict
        """
        reset_clock()
        lax = get_success_data(api.create_facility(
            create_facility_payload(facility_code="LAX", region_class="CONTIGUOUS"), SSA))
        jfk = get_success_data(api.create_facility(
            create_facility_payload(facility_code="JFK", region_class="CONTIGUOUS",
                                    dispatch_cutoff_local="18:00"), SSA))
        get_success_data(api.create_service_rule(
            lax["id"],
            create_rule_payload(jfk["id"], lax["version"], mail_class="FIRST_CLASS",
                                service_days=3, effective_from="2026-01-01",
                                effective_to="2026-06-30"), SSA))
        fac = get_success_data(api.get_facility(lax["id"], SSA))
        resp = api.create_service_rule(
            lax["id"],
            create_rule_payload(jfk["id"], fac["version"], mail_class="FIRST_CLASS",
                                service_days=2, effective_from="2026-06-30"), SSA)
        validate_error(resp, ApiErrorId.ERR_WINDOW_OVERLAP)


class TestRuleCreateOcc:

    def test_second_rule_create_with_stale_facility_version_rejected(self, api):
        """PRD §2.7: "Creating a service standard rule requires
        `expected_facility_version` matching the current `version` of the parent
        origin `ProcessingFacility`."
        PRD §2.7: "A concurrently landed rule change (a retirement or a new
        overlapping window) legitimately supersedes the client's intended window
        arithmetic, and the write is rejected with `ERR_STALE_VERSION`."

        Design: Corner/cross_cutting_layers/occ_rule_create_stale_facility_version
        """
        reset_clock()
        lax = get_success_data(api.create_facility(
            create_facility_payload(facility_code="LAX", region_class="CONTIGUOUS"), SSA))
        jfk = get_success_data(api.create_facility(
            create_facility_payload(facility_code="JFK", region_class="CONTIGUOUS",
                                    dispatch_cutoff_local="18:00"), SSA))
        first = api.create_service_rule(
            lax["id"],
            create_rule_payload(jfk["id"], lax["version"], mail_class="FIRST_CLASS",
                                service_days=3, effective_from="2026-01-01"), SSA)
        validate_success(first, expected_status=201)
        resp = api.create_service_rule(
            lax["id"],
            create_rule_payload(jfk["id"], lax["version"], mail_class="PRIORITY",
                                service_days=2, effective_from="2026-01-01"), SSA)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
