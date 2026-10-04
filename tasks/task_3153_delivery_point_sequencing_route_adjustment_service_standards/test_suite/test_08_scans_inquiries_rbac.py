"""Delivery scans, weekly compliance, customer inquiries, RBAC, error envelope,
and FK reverse-reachability listings."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    adjustment_in_state,
    create_facility,
    create_facility_payload,
    create_inquiry,
    create_point_payload,
    create_rule_payload,
    create_unit,
    evaluation_consulted,
    get_inquiry,
    get_success_data,
    headers_without_credentials,
    make_carrier_headers,
    open_evaluation,
    raw_request,
    record_scan,
    reset_clock,
    setup_route_with_active_points,
    setup_unit_with_route,
    validate_error,
    validate_paginated,
    validate_success,
    NON_EXISTENT_UUID,
)

SSA = TEST_USERS["standards_admin_headers"]
SUP = TEST_USERS["supervisor_headers"]
PM = TEST_USERS["postmaster_headers"]
CSR = TEST_USERS["csr_headers"]
AMS = TEST_USERS["ams_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]

COUNTS = dict(letters_count_total=3600, flats_count_total=900, parcels_count_total=40,
              actual_street_minutes_total=2160, office_minutes_total=1440)


class TestScanCompliance:

    def test_empty_week_defaults_to_full_compliance(self, api):
        """PRD §3.11: "an empty week reports a rate of 1.0 rather than 0.0 — a
        pinned policy choice."

        Design: Corner/calculations/scan_compliance_empty_week_defaults_to_full_compliance
        """
        reset_clock()
        ctx = setup_unit_with_route()
        data = get_success_data(api.get_scan_compliance(
            ctx["unit"]["id"], SUP, params={"week_start": "2026-08-31"}))
        assert data["total_scans"] == 0
        assert data["compliant_scans"] == 0
        assert data["compliance_rate"] == 1.0
        assert data["meets_target"] is True

    def test_vacant_confirmed_on_occupied_point_noncompliant(self, api):
        """PRD §3.11: "a scan is compliant only when `gps_within_geofence` is true
        and the scan code agrees with the point's occupancy — a `VACANT_CONFIRMED`
        scan requires the point to actually be `VACANT`, and a `DELIVERED` scan
        requires a deliverable point."

        Design: Corner/calculations/scan_consistency_marks_vacant_confirmed_on_occupied_noncompliant
        """
        reset_clock()
        ctx = setup_route_with_active_points(1)
        unit_id, route_id = ctx["unit"]["id"], ctx["route"]["id"]
        point, car = ctx["points"][0], ctx["carrier"]
        ev = record_scan(unit_id, route_id, point["id"], car["id"],
                         scan_code="VACANT_CONFIRMED",
                         scan_datetime="2026-09-01T15:00:00Z",
                         gps_within_geofence=True)
        assert ev["is_compliant"] is False
        data = get_success_data(api.get_scan_compliance(
            unit_id, SUP, params={"week_start": "2026-08-31"}))
        assert data["total_scans"] == 1
        assert data["compliant_scans"] == 0
        assert data["compliance_rate"] == 0.0
        assert data["meets_target"] is False

    def test_compliance_rate_counts_gps_and_consistency(self, api):
        """PRD §3.11: "a scan is compliant only when `gps_within_geofence` is true
        and the scan code agrees with the point's occupancy".
        PRD §3.11: "The rate is the compliant count divided by the total, rounded
        half-up to four decimal places".

        Design: Corner/calculations/scan_compliance_target_boundary_equality_passes
        """
        reset_clock()
        ctx = setup_route_with_active_points(1)
        unit_id, route_id = ctx["unit"]["id"], ctx["route"]["id"]
        point, car = ctx["points"][0], ctx["carrier"]
        record_scan(unit_id, route_id, point["id"], car["id"],
                    scan_datetime="2026-08-31T10:00:00Z", gps_within_geofence=False)
        record_scan(unit_id, route_id, point["id"], car["id"],
                    scan_datetime="2026-09-01T10:00:00Z", gps_within_geofence=True)
        data = get_success_data(api.get_scan_compliance(
            unit_id, SUP, params={"week_start": "2026-08-31"}))
        assert data["total_scans"] == 2
        assert data["compliant_scans"] == 1
        assert data["compliance_rate"] == 0.5
        assert data["meets_target"] is False

    def test_target_boundary_equality_passes(self, api):
        """PRD §3.11: "`meets_target` is true when the rate is at least the unit's
        `scan_compliance_target`, and the boundary is inclusive: a rate exactly
        equal to the target (for example 0.9800 against a target of 0.98) passes."

        Design: Corner/calculations/scan_compliance_target_boundary_equality_passes
        """
        reset_clock()
        fac = create_facility()
        unit = create_unit(fac["id"], scan_compliance_target=0.98)
        from test_helpers import create_carrier, create_route, create_point, activate_point
        car = create_carrier(unit["id"])
        route = create_route(unit["id"], car["id"])
        point = create_point(unit["id"])
        activate_point(unit["id"], point["id"], route["id"])
        # 49 compliant (DELIVERED, GPS true) + 1 non-compliant (GPS false) = 0.98.
        for i in range(49):
            record_scan(unit["id"], route["id"], point["id"], car["id"],
                        scan_datetime=f"2026-09-01T{10 + i // 60:02d}:{i % 60:02d}:00Z",
                        gps_within_geofence=True)
        record_scan(unit["id"], route["id"], point["id"], car["id"],
                    scan_datetime="2026-09-02T10:00:00Z", gps_within_geofence=False)
        data = get_success_data(api.get_scan_compliance(
            unit["id"], SUP, params={"week_start": "2026-08-31"}))
        assert data["total_scans"] == 50
        assert data["compliant_scans"] == 49
        assert data["compliance_rate"] == 0.98
        assert data["meets_target"] is True


class TestScanEventShape:

    def test_scan_event_is_append_only_record(self, api):
        """PRD §2.10: "a `DeliveryScanEvent` (an append-only scan record)" carries
        "only `id` and `created_at` — both `updated_at` and `version` are absent".

        Design: Corner/entities/scan_event_immutable_no_update_endpoint
        """
        reset_clock()
        ctx = setup_route_with_active_points(1)
        ev = record_scan(ctx["unit"]["id"], ctx["route"]["id"],
                         ctx["points"][0]["id"], ctx["carrier"]["id"],
                         scan_code="DELIVERED",
                         scan_datetime="2026-09-01T15:00:00Z",
                         gps_within_geofence=True)
        assert "id" in ev and "created_at" in ev
        assert "version" not in ev
        assert "updated_at" not in ev
        assert ev["is_compliant"] is True


class TestInquiryLifecycle:

    def _resolved_inquiry(self, api, resolve_code="FOUND_AND_DELIVERED"):
        ctx = setup_route_with_active_points(1)
        unit_id, point_id = ctx["unit"]["id"], ctx["points"][0]["id"]
        inq = create_inquiry(unit_id, point_id)
        get_success_data(api.begin_investigation(unit_id, inq["id"], CSR))
        return ctx, inq

    def test_third_resolution_lands_resolved_final(self, api):
        """PRD §3.12: "while `reopened_count` is below two, resolution lands in
        `RESOLVED`; once `reopened_count` has reached two, the third resolution
        instead lands in `RESOLVED_FINAL`, locking the inquiry."

        Design: Corner/state_machines/inquiry_resolved_final_lockout_after_two_reopens
        """
        reset_clock()
        ctx, inq = self._resolved_inquiry(api)
        unit_id = ctx["unit"]["id"]
        for _ in range(2):
            get_success_data(api.resolve_inquiry(unit_id, inq["id"],
                                                 {"resolution_code": "NO_ERROR_FOUND"},
                                                 CSR))
            get_success_data(api.reopen_inquiry(unit_id, inq["id"], CSR))
            get_success_data(api.begin_investigation(unit_id, inq["id"], CSR))
        data = get_success_data(api.resolve_inquiry(
            unit_id, inq["id"], {"resolution_code": "FOUND_AND_DELIVERED"}, CSR))
        assert data["status"] == "RESOLVED_FINAL"
        assert data["reopened_count"] == 2
        resp = api.reopen_inquiry(unit_id, inq["id"], CSR)
        validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL)


class TestRbacAndAuth:

    def test_missing_auth_headers_rejected_before_anything(self, api):
        """PRD §2.1: "A request missing either header, or presenting an
        `X-User-Role` value that is not one of these declared roles, is rejected
        with `ERR_UNAUTHENTICATED` (HTTP 401)."
        PRD §2.9: "Authentication (401) comes first, then role authorization
        (403), then path existence left-to-right (404)".

        Design: Corner/validations/missing_auth_headers_rejected_before_anything
        """
        reset_clock()
        resp = raw_request(api, "GET", f"/api/delivery-units/{NON_EXISTENT_UUID}",
                           headers=headers_without_credentials())
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)

    def test_forbidden_role_denied_on_exclusive_endpoint(self, api):
        """PRD §2.1: "A request whose role is recognized but not permitted for the
        target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §3.4: "`AddressManagementSpecialist` operators maintain the delivery
        point file."

        Design: Corner/validations/forbidden_role_denied_on_exclusive_endpoint
        """
        reset_clock()
        fac = create_facility()
        unit = create_unit(fac["id"], code="DU33")
        resp = api.create_point(unit["id"], create_point_payload("90230010330"),
                                CSR)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        rows, meta = validate_paginated(
            api.list_points(unit["id"], AMS, params={"limit": 100}))
        assert meta["total_count"] == 0

    def test_body_fk_reference_not_found(self, api):
        """PRD §2.9: "then body-supplied foreign-key existence
        (`ERR_REFERENCE_NOT_FOUND`, 422)".

        Design: Corner/validations/body_fk_reference_not_found
        """
        reset_clock()
        resp = api.create_unit(
            {"unit_code": "DU34", "office_name": "Orphan Station",
             "delivery_office_facility_id": NON_EXISTENT_UUID,
             "case_slot_count_per_route": 500}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND)

    def test_carrier_identity_mismatch_on_scan_rejected(self, api):
        """PRD §2.1: "When `X-User-Role` is `Carrier`, `X-User-ID` is the `id` of
        the acting `Carrier` record; the role is entity-backed, so ownership-style
        checks (for example, a carrier reading their own record) compare a
        resource's carrier foreign key to `X-User-ID`."

        Design: Corner/rbac/carrier_entity_backed_identity_scans_own_route_only
        """
        reset_clock()
        ctx = setup_route_with_active_points(1)
        unit_id, route_id = ctx["unit"]["id"], ctx["route"]["id"]
        from test_helpers import create_carrier
        other = create_carrier(unit_id)
        resp = api.create_scan_event(
            unit_id, route_id,
            {"delivery_point_id": ctx["points"][0]["id"],
             "carrier_id": ctx["carrier"]["id"], "scan_code": "DELIVERED",
             "scan_datetime": "2026-09-01T12:00:00Z", "gps_within_geofence": True},
            make_carrier_headers(other["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        rows = get_success_data(api.list_scan_events(unit_id, route_id, SUP,
                                                     params={"limit": 100}))
        assert len(rows) == 0

    def test_ams_cannot_approve_adjustment(self, api):
        """PRD §2.1: "A request whose role is recognized but not permitted for the
        target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §2.6: "A `RouteSupervisor` authors and submits an adjustment; only a
        `Postmaster` may approve or reject it".

        Design: Corner/rbac/ams_cannot_approve_adjustment
        """
        reset_clock()
        ctx = evaluation_consulted(outcome="CONCURRED", counts=COUNTS,
                                   kind="MINI_SURVEY")
        ctx = adjustment_in_state(ctx, state="SUBMITTED",
                                  effective_date="2026-09-10")
        unit_id, route_id, ev = (ctx["unit"]["id"], ctx["route"]["id"],
                                 ctx["evaluation"]["id"])
        resp = api.approve_adjustment(unit_id, route_id, ev,
                                      ctx["adjustment"]["id"], AMS)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        from test_helpers import get_adjustment
        adj = get_adjustment(unit_id, route_id, ev, ctx["adjustment"]["id"])
        assert adj["status"] == "SUBMITTED"

    def test_service_standards_admin_exclusive_on_facility_create(self, api):
        """PRD §2.1: "A request whose role is recognized but not permitted for the
        target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §3.1: "A `ServiceStandardsAdmin` maintains the plant-level reference
        data on which all delivery-date commitments rest."

        Design: Corner/rbac/service_standards_admin_exclusive_on_facility_create
        """
        reset_clock()
        resp = api.create_facility(
            create_facility_payload(facility_code="SEA", facility_type="NDC",
                                    region_class="CONTIGUOUS",
                                    dispatch_cutoff_local="18:00",
                                    operating_days=["MON", "TUE", "WED", "THU",
                                                    "FRI"]), SUP)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestErrorEnvelope:

    def test_error_envelope_shape_on_rejection(self, api):
        """PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`" and "`error_id` is a unique,
        machine-readable string" and "The `message` provides a human-readable
        explanation of what went wrong."

        Design: Corner/errors/error_envelope_shape_on_rejection
        """
        reset_clock()
        resp = api.create_facility(
            create_facility_payload(facility_code="lx",
                                    operating_days=["MON"]), SSA)
        data = validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST,
                              expected_status=400)
        assert isinstance(data.get("message"), str) and len(data["message"]) > 0
        body = resp.json()
        assert body["response_type"] == "error"
        assert "api_request_id" in body["meta"]
        assert "api_request_timestamp" in body["meta"]


class TestReverseReachability:

    def test_fk_reverse_reachability_lists_children_from_parent(self, api):
        """PRD §4 endpoint table: routes are listed under their unit
        ("List routes of a unit"), evaluations under their route ("List
        evaluations of a route"), and rules under their origin facility ("List
        rules whose origin is this facility") — each filtered to the parent.

        Design: Corner/endpoints/fk_reverse_reachability_lists_children_from_parent
        """
        reset_clock()
        lax = get_success_data(api.create_facility(
            create_facility_payload(facility_code="LAX", region_class="CONTIGUOUS"),
            SSA))
        jfk = get_success_data(api.create_facility(
            create_facility_payload(facility_code="JFK", region_class="CONTIGUOUS",
                                    dispatch_cutoff_local="18:00"), SSA))
        rule = get_success_data(api.create_service_rule(
            lax["id"],
            create_rule_payload(jfk["id"], lax["version"],
                                mail_class="GROUND_ADVANTAGE", service_days=3,
                                effective_from="2026-01-01"), SSA))
        unit = create_unit(lax["id"], code="DU44")
        from test_helpers import create_carrier, create_route
        car = create_carrier(unit["id"])
        route = create_route(unit["id"], car["id"], route_type="RURAL")
        ev = open_evaluation(unit["id"], route["id"], kind="SPECIAL_INSPECTION")
        routes, rmeta = validate_paginated(api.list_routes(unit["id"], PM))
        assert rmeta["total_count"] == 1 and routes[0]["id"] == route["id"]
        evals, emeta = validate_paginated(
            api.list_evaluations(unit["id"], route["id"], PM))
        assert emeta["total_count"] == 1 and evals[0]["id"] == ev["id"]
        rules, mmeta = validate_paginated(
            api.list_rules_for_facility(lax["id"], SSA))
        assert mmeta["total_count"] == 1 and rules[0]["id"] == rule["id"]
        assert rules[0]["origin_facility_id"] == lax["id"]
