"""Authentication, authorisation, ownership and listing behaviour."""
from test_helpers import (
    api_client as api,
    headers_for_role,
    make_carrier_headers,
    make_platform_admin_headers,
    make_shipper_headers,
    NON_EXISTENT_UUID,
    set_clock,
    setup_board,
)


def _posted(board, window=("2026-10-05T08:00:00Z", "2026-10-05T12:00:00Z"), **overrides):
    payload = {
        "shipper_id": board["shipper_id"],
        "origin_facility_id": board["origin_facility_id"],
        "destination_facility_id": board["destination_facility_id"],
        "pricing_mode": "SPOT",
        "equipment_type": "DRY_VAN",
        "commodity": "GENERAL",
        "weight_lbs": 40000,
        "declared_cargo_value_cents": 5000000,
        "distance_miles": 1200,
        "pickup_window_start": window[0],
        "pickup_window_end": window[1],
        "delivery_deadline": "2026-10-07T18:00:00Z",
        "market_band": "BALANCED",
    }
    payload.update(overrides)
    created = api.create_load(payload, make_shipper_headers(board["shipper_id"]))
    assert created.status_code == 201, created.text
    load_id = created.json()["data"]["id"]
    posted = api.post_load(load_id, make_shipper_headers(board["shipper_id"]))
    assert posted.status_code == 200, posted.text
    quote = api.list_load_rate_quotes(
        load_id, make_shipper_headers(board["shipper_id"])).json()["data"][-1]
    return posted.json()["data"], quote


class TestAuthenticationPrecedence:
    """Authentication runs before every other check, including existence."""

    def test_a_missing_role_header_beats_an_unknown_resource(self):
        """PRD section 2.1: "`X-User-ID` identifies the acting party and `X-User-Role` declares the capacity in which they act. A request missing either header, or presenting a role name that is not one of the six declared roles, is refused with `ERR_UNAUTHENTICATED` (HTTP 401) — and that check runs before every other check in the system, including resource existence, so a headerless request aimed at a path whose resource does not exist still answers 401 rather than 404."

        Design: Corner/validations/missing_role_header_wins_over_an_unknown_resource
        """
        set_clock("2026-09-20T00:00:00Z")
        response = api.get_load(NON_EXISTENT_UUID, {})
        assert response.status_code == 401, response.text
        assert response.json()["data"]["error_id"] == "ERR_UNAUTHENTICATED"
        assert response.json()["data"]["error_id"] != "ERR_LOAD_NOT_FOUND"
        assert response.json()["response_type"] == "error"

    def test_an_undeclared_role_name_is_also_unauthenticated(self):
        """PRD section 2.1: "`X-User-ID` identifies the acting party and `X-User-Role` declares the capacity in which they act. A request missing either header, or presenting a role name that is not one of the six declared roles, is refused with `ERR_UNAUTHENTICATED` (HTTP 401) — and that check runs before every other check in the system, including resource existence, so a headerless request aimed at a path whose resource does not exist still answers 401 rather than 404."

        Design: Corner/validations/missing_role_header_wins_over_an_unknown_resource
        """
        set_clock("2026-09-20T00:00:00Z")
        response = api.get_load(NON_EXISTENT_UUID, headers_for_role("Auditor"))
        assert response.status_code == 401, response.text
        assert response.json()["data"]["error_id"] == "ERR_UNAUTHENTICATED"


class TestRolePermission:
    """A legitimate role still needs permission for the operation."""

    def test_a_claims_adjuster_cannot_create_a_load(self):
        """PRD section 2.1: "A request whose role is legitimate but not permitted on
        the target operation is refused with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/claims_adjuster_cannot_create_a_load
        """
        board = setup_board(units=1)
        set_clock("2026-09-20T00:00:00Z")
        response = api.create_load(
            {
                "shipper_id": board["shipper_id"],
                "origin_facility_id": board["origin_facility_id"],
                "destination_facility_id": board["destination_facility_id"],
                "pricing_mode": "SPOT",
                "equipment_type": "DRY_VAN",
                "commodity": "GENERAL",
                "weight_lbs": 40000,
                "declared_cargo_value_cents": 5000000,
                "distance_miles": 1200,
                "pickup_window_start": "2026-10-05T08:00:00Z",
                "pickup_window_end": "2026-10-05T12:00:00Z",
                "delivery_deadline": "2026-10-07T18:00:00Z",
                "market_band": "BALANCED",
            },
            headers_for_role("ClaimsAdjuster"),
        )
        assert response.status_code == 403, response.text
        assert response.json()["data"]["error_id"] == "ERR_UNAUTHORIZED"

        loads = api.list_loads(make_shipper_headers(board["shipper_id"]),
                               {"shipper_id": board["shipper_id"]})
        assert loads.json()["data"] == []

    def test_a_compliance_reviewer_cannot_reprice_a_load(self):
        """PRD section 2.1: "A request whose role is legitimate but not permitted on
        the target operation is refused with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/compliance_reviewer_cannot_reprice_a_load
        """
        board = setup_board(units=1)
        set_clock("2026-10-05T00:00:00Z")
        load, quote = _posted(board)
        assert load["booked_rate_cents"] == 372240
        assert load["reprice_count"] == 0

        response = api.reprice_load(load["id"], "TIGHT",
                                    headers_for_role("ComplianceReviewer"))
        assert response.status_code == 403, response.text
        assert response.json()["data"]["error_id"] == "ERR_UNAUTHORIZED"

        refreshed = api.get_load(
            load["id"], make_shipper_headers(board["shipper_id"])).json()["data"]
        assert refreshed["booked_rate_cents"] == 372240
        assert refreshed["reprice_count"] == 0
        quotes = api.list_load_rate_quotes(
            load["id"], make_shipper_headers(board["shipper_id"])).json()["data"]
        assert len(quotes) == 1
        assert quotes[0]["repriced_rate_cents"] is None

    def test_a_carrier_cannot_void_a_load(self):
        """PRD section 2.1: "A request whose role is legitimate but not permitted on
        the target operation is refused with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/carrier_cannot_void_a_load
        """
        board = setup_board(units=1)
        set_clock("2026-10-05T00:00:00Z")
        load, quote = _posted(board)
        booked = api.create_booking(
            {"load_id": load["id"], "carrier_id": board["carrier_id"],
             "rate_quote_id": quote["id"], "equipment_id": board["equipment"][0]["id"],
             "expected_load_version": load["version"]},
            make_carrier_headers(board["carrier_id"]))
        assert booked.status_code == 201, booked.text
        invoiced = api.invoice_booking(booked.json()["data"]["id"],
                                       make_shipper_headers(board["shipper_id"]))
        assert invoiced.status_code in (200, 409), invoiced.text

        response = api.void_load(load["id"], "void-carrier-probe",
                                 make_carrier_headers(board["carrier_id"]))
        assert response.status_code == 403, response.text
        assert response.json()["data"]["error_id"] == "ERR_UNAUTHORIZED"
        assert api.get_load(
            load["id"], make_shipper_headers(board["shipper_id"])).json()["data"]["status"] \
            != "VOIDED"

    def test_a_platform_admin_can_broker_a_booking_on_a_carriers_behalf(self):
        """PRD section 2.1: "A `PlatformAdmin` may also broker a booking on a
        carrier's behalf and onboard shippers, carriers, and facilities."

        Design: Corner/rbac/claims_adjuster_cannot_create_a_load
        """
        board = setup_board(units=1)
        set_clock("2026-10-05T00:00:00Z")
        load, quote = _posted(board)
        brokered = api.create_booking(
            {"load_id": load["id"], "carrier_id": board["carrier_id"],
             "rate_quote_id": quote["id"], "equipment_id": board["equipment"][0]["id"],
             "expected_load_version": load["version"]},
            make_platform_admin_headers())
        assert brokered.status_code == 201, brokered.text
        assert brokered.json()["data"]["carrier_id"] == board["carrier_id"]


class TestOwnership:
    """Ownership is enforced for entity-backed actors."""

    def test_a_shipper_cannot_read_another_shippers_file(self):
        """PRD section 2.1: "Ownership checks on any resource that references a
        `Shipper` compare the resource's shipper reference to `X-User-ID`, so a
        shipper may read and act only on its own loads, its own lane contracts, and
        settlements arising from its own freight."

        Design: Corner/rbac/shipper_cannot_read_another_shippers_file
        """
        board = setup_board(units=1)
        set_clock("2026-09-20T00:00:00Z")
        other = api.create_shipper(
            {"name": "Second Freight Buyer", "billing_state_code": "CA",
             "payment_terms_days": 15, "quick_pay_discount_pct": 0.02,
             "credit_limit_cents": 5000000, "load_credit_limit": 3},
            make_platform_admin_headers()).json()["data"]

        cross = api.get_shipper(other["id"], make_shipper_headers(board["shipper_id"]))
        assert cross.status_code == 403, cross.text
        assert cross.json()["data"]["error_id"] == "ERR_UNAUTHORIZED"

        own = api.get_shipper(board["shipper_id"], make_shipper_headers(board["shipper_id"]))
        assert own.status_code == 200, own.text
        assert own.json()["data"]["id"] == board["shipper_id"]

    def test_a_carrier_cannot_report_tracking_on_another_carriers_load(self):
        """PRD section 2.1: "Ownership checks compare the resource's carrier
        reference to `X-User-ID`: a carrier acts only on its own bookings, its own
        equipment units, its own quotes, and its own settlements."

        Design: Corner/validations/carrier_acting_on_another_carriers_booking_returns_unauthorized
        """
        board = setup_board(units=1)
        set_clock("2026-10-05T00:00:00Z")
        load, quote = _posted(board)
        booked = api.create_booking(
            {"load_id": load["id"], "carrier_id": board["carrier_id"],
             "rate_quote_id": quote["id"], "equipment_id": board["equipment"][0]["id"],
             "expected_load_version": load["version"]},
            make_carrier_headers(board["carrier_id"]))
        assert booked.status_code == 201, booked.text

        intruder = api.create_carrier(
            {"legal_name": "Rival Transport Co", "mc_number": "100999",
             "dot_number": "DOT-100999", "insurance_expires_at": "2027-06-01T00:00:00Z",
             "insurance_liability_limit_cents": 100000000,
             "cargo_coverage_limit_cents": 175000000, "safety_score": 70.0,
             "equipment_types": ["DRY_VAN"]},
            {"X-User-ID": "test-compliance-1", "X-User-Role": "ComplianceReviewer",
             "Content-Type": "application/json"})
        assert intruder.status_code == 201, intruder.text
        intruder = intruder.json()["data"]

        response = api.report_tracking_ping(
            load["id"],
            {"carrier_id": intruder["id"], "sequence": 1,
             "reported_status": "EN_ROUTE_PICKUP", "location_code": "9vg81",
             "eta_utc": "2026-10-07T18:00:00Z"},
            make_carrier_headers(intruder["id"]),
        )
        assert response.status_code == 403, response.text
        assert response.json()["data"]["error_id"] == "ERR_UNAUTHORIZED"
        assert response.json()["data"]["error_id"] != "ERR_TRACKING_SEQUENCE_OUT_OF_ORDER"

        pings = api.list_load_tracking_pings(
            load["id"], make_shipper_headers(board["shipper_id"])).json()["data"]
        assert pings == []


class TestListing:
    """List responses carry the four pagination fields and honour filters."""

    def test_filtered_listing_reports_the_whole_matching_set(self):
        """PRD section 2.3: "`offset` is the number of rows skipped from the front
        of the result set and defaults to 0."
        PRD section 2.3: "Every list response carries four pagination fields in the
        `meta` object of the standard envelope: `limit`, `offset`, `total_count`
        (the total number of rows matching the filter, before pagination), and
        `has_more` (true when further rows remain beyond the returned window)."

        Design: Corner/entities/carrier_equipment_listing_paginates_and_reports_total_count
        """
        board = setup_board(units=4)
        headers = make_carrier_headers(board["carrier_id"])
        third = board["equipment"][2]
        shipped = api.set_equipment_status(third["id"], "IN_SHOP", headers)
        assert shipped.status_code == 200, shipped.text

        page = api.list_equipment(
            make_platform_admin_headers(),
            {"carrier_id": board["carrier_id"], "limit": 2, "offset": 0})
        assert page.status_code == 200
        body = page.json()
        assert body["response_type"] == "array"
        rows, meta = body["data"], body["meta"]
        assert len(rows) == 2
        assert meta["total_count"] == 4
        assert meta["has_more"] is True
        assert meta["limit"] == 2
        assert meta["offset"] == 0

    def test_filters_narrow_the_matching_set(self):
        """PRD section 2.3: "Every list response carries four pagination fields in the `meta` object of the standard envelope: `limit`, `offset`, `total_count` (the total number of rows matching the filter, before pagination), and `has_more` (true when further rows remain beyond the returned window)."

        Design: Corner/entities/carrier_equipment_listing_paginates_and_reports_total_count
        """
        board = setup_board(units=4)
        headers = make_carrier_headers(board["carrier_id"])
        api.set_equipment_status(board["equipment"][2]["id"], "IN_SHOP", headers)

        second_page = api.list_equipment(
            make_platform_admin_headers(),
            {"carrier_id": board["carrier_id"], "limit": 2, "offset": 2})
        assert second_page.status_code == 200
        assert len(second_page.json()["data"]) == 2
        assert second_page.json()["meta"]["has_more"] is False

        in_shop = api.list_equipment(make_platform_admin_headers(),
                                     {"carrier_id": board["carrier_id"],
                                      "status": "IN_SHOP"})
        assert len(in_shop.json()["data"]) == 1
        assert in_shop.json()["data"][0]["status"] == "IN_SHOP"

        untouched = api.list_equipment(make_platform_admin_headers(),
                                       {"carrier_id": board["carrier_id"]})
        assert len(untouched.json()["data"]) == 4