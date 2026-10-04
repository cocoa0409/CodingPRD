"""RBAC tiers and optimistic concurrency.

Authentication precedes role authorization, which precedes the MIC/scope
privilege tier; the two version-guarded writes reject stale views with
ERR_STALE_VERSION (PRD §2.1, §2.6, §2.8).
"""

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    create_forecaster,
    create_office,
    create_storm,
    create_watch_draft,
    create_zone,
    get_coordination_request,
    get_product,
    get_storm,
    list_coordination_requests,
    list_products,
    make_forecaster_headers,
    make_mic_headers,
    make_undeclared_role_headers,
    set_clock,
    setup_coordinated_offices,
    setup_mic_pair,
    setup_office_with_zone,
    setup_pending_coordination_watch,
    submit_coordination,
    validate_error,
    validate_success,
)


class TestAuthentication:
    def test_product_create_with_undeclared_role_returns_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, carrying a role outside
        this list, or — for the entity-backed roles below — carrying an
        `X-User-ID` that does not resolve to an existing `Forecaster` row is
        rejected with `ERR_UNAUTHENTICATED`."
        PRD §2.8: "First, authentication: headers present, role declared, and
        entity-backed identifiers resolving to an existing `Forecaster` row,
        else `ERR_UNAUTHENTICATED`."

        Design: Corner/rbac/product_create_with_undeclared_role_returns_unauthenticated
        """
        set_clock(api, "2026-09-01T00:00:00Z")
        resp = api.create_product(
            {
                "product_level": "WATCH",
                "hazard_type": "WINTER_STORM",
                "issuing_office_id": NON_EXISTENT_UUID,
                "expires_at": "2026-09-02T00:00:00Z",
            },
            make_undeclared_role_headers(),
        )
        err = validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
        assert err["error_id"] != "ERR_FORBIDDEN_ROLE"
        assert err["error_id"] != "ERR_OFFICE_NOT_FOUND", "authentication runs first"


class TestRoleAuthorization:
    def test_emergency_manager_cannot_create_product(self, api, emergency_manager_headers):
        """PRD §2.1: "A caller whose role is not authorized for the endpoint is
        rejected with `ERR_FORBIDDEN_ROLE`."
        PRD §4: "POST `/alerts/products` ... Forecaster, MeteorologistInCharge"

        Design: Corner/rbac/emergency_manager_cannot_create_product
        """
        bundle = setup_office_with_zone(api)
        resp = api.create_product(
            {
                "product_level": "WATCH",
                "hazard_type": "WINTER_STORM",
                "issuing_office_id": bundle.office["id"],
                "zone_ids": [bundle.zone["id"]],
                "effective_from": "2026-09-02T00:00:00Z",
                "expires_at": "2026-09-02T12:00:00Z",
            },
            emergency_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        assert list_products(api, bundle.headers, issuing_office_id=bundle.office["id"]) == []

    def test_coordination_respond_by_analyst_forbidden(self, api, verification_analyst_headers):
        """PRD §2.1: "A caller whose role is not authorized for the endpoint is
        rejected with `ERR_FORBIDDEN_ROLE`."
        PRD §4: "POST `/alerts/coordination-requests/{id}/respond` ...
        Forecaster, MeteorologistInCharge"

        Design: Corner/rbac/coordination_respond_by_analyst_forbidden
        """
        bundle = setup_pending_coordination_watch(api)
        request = bundle.requests[0]
        resp = api.respond_coordination_request(
            request["id"], {"outcome": "ACKNOWLEDGED"}, verification_analyst_headers
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        request = get_coordination_request(api, request["id"], bundle.headers_a)
        assert request["status"] == "REQUESTED"
        assert request["responded_at"] is None


class TestCoordinationOverridePrivilege:
    def test_coordination_override_by_non_mic_forbidden(self, api):
        """PRD §2.1: "it is additionally the only role permitted to issue a
        product with the coordination override flag set; that override requires
        the caller's `Forecaster` row to carry `level` equal to `MIC`, and an
        override attempted by any other caller is rejected with
        `ERR_MIC_REQUIRED`."

        Design: Corner/rbac/coordination_override_by_non_mic_forbidden
        """
        bundle = setup_pending_coordination_watch(api)
        junior = create_forecaster(api, bundle.office_a["id"], level="JOURNEYMAN")
        resp = api.issue_product(
            bundle.product["id"],
            {"expected_product_version": bundle.product["version"], "coordination_override": True},
            make_mic_headers(junior["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_MIC_REQUIRED)
        product = get_product(api, bundle.product["id"], bundle.headers_a)
        assert product["status"] == "PENDING_COORDINATION"
        request = get_coordination_request(api, bundle.requests[0]["id"], bundle.headers_a)
        assert request["status"] == "REQUESTED"

    def test_mic_override_issues_and_overrides_requests(self, api):
        """PRD §3.5: "From `PENDING_COORDINATION`, every linked coordination
        request must be `ACKNOWLEDGED` — unless a `MeteorologistInCharge`
        issues with `coordination_override` set to true, which sweeps the
        non-terminal requests into `OVERRIDDEN`"

        Design: Corner/rbac/mic_override_issues_and_overrides_requests
        """
        bundle = setup_mic_pair(api)
        draft = create_watch_draft(
            api,
            bundle.office_a,
            bundle.mic_headers,
            [bundle.zone_a["id"], bundle.zone_b["id"]],
            hazard_type="SEVERE_THUNDERSTORM",
            effective_from="2026-09-01T06:00:00Z",
            expires_at="2026-09-01T18:00:00Z",
        )
        submitted = submit_coordination(api, draft["id"], bundle.mic_headers)
        request = list_coordination_requests(api, draft["id"], bundle.mic_headers)[0]
        assert request["status"] == "REQUESTED"

        resp = api.issue_product(
            draft["id"],
            {"expected_product_version": submitted["version"], "coordination_override": True},
            bundle.mic_headers,
        )
        product = validate_success(resp)
        assert product["status"] == "ISSUED"
        assert product["issued_at"] is not None

        request = get_coordination_request(api, request["id"], bundle.mic_headers)
        assert request["status"] == "OVERRIDDEN"
        assert request["responded_at"] is None


class TestOfficeScope:
    def test_forecaster_outside_office_scope_forbidden(self, api):
        """PRD §2.1: "A forecaster-scoped caller acting on a product, storm
        event, or coordination request outside their own office is rejected
        with `ERR_OFFICE_SCOPE_VIOLATION`."

        Design: Corner/rbac/forecaster_outside_office_scope_forbidden
        """
        office_a = create_office(api)
        office_b = create_office(api)
        zone_a = create_zone(api, office_a["id"])
        fc_a = create_forecaster(api, office_a["id"])
        fc_b = create_forecaster(api, office_b["id"])
        headers_a = make_forecaster_headers(fc_a["id"])
        draft = create_watch_draft(
            api,
            office_a,
            headers_a,
            [zone_a["id"]],
            hazard_type="WINTER_STORM",
            effective_from="2026-09-02T00:00:00Z",
            expires_at="2026-09-02T12:00:00Z",
        )
        resp = api.issue_product(
            draft["id"],
            {"expected_product_version": draft["version"]},
            make_forecaster_headers(fc_b["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_OFFICE_SCOPE_VIOLATION)
        product = get_product(api, draft["id"], headers_a)
        assert product["status"] == "DRAFT"
        assert product["version"] == draft["version"]


class TestOptimisticConcurrency:
    def test_occ_storm_update_stale_version_returns_412(self, api):
        """PRD §2.6: "Updating a storm event's readings requires the request to
        carry `expected_storm_event_version` holding the client's last observed
        `version` of that storm event."
        PRD §2.6: "When the supplied value does not match the entity's current
        `version` — for example, because a coordination decline or a
        coordination deadline expiry reverted a pending product to `DRAFT`, and
        that reversion advanced the product's `version` after the client
        captured it — the write is rejected with `ERR_STALE_VERSION` (HTTP
        412), and the client must re-read the resource and retry against the
        current version."

        Design: Corner/cross_cutting_layers/occ_storm_update_stale_version_returns_412
        """
        bundle = setup_office_with_zone(api)
        storm = create_storm(
            api, bundle.office["id"], bundle.headers, "SEVERE_THUNDERSTORM", max_wind_mph=50
        )
        updated = validate_success(
            api.update_storm_event(
                storm["id"],
                {"expected_storm_event_version": storm["version"], "max_wind_mph": 55},
                bundle.headers,
            )
        )
        assert updated["version"] == storm["version"] + 1
        assert updated["status"] == "TRACKING"

        resp = api.update_storm_event(
            storm["id"],
            {"expected_storm_event_version": storm["version"], "max_hail_inches": 2.0},
            bundle.headers,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        storm = get_storm(api, storm["id"], bundle.headers)
        assert storm["max_wind_mph"] == 55
        assert storm["max_hail_inches"] == 0, "the stale write was rejected wholesale"

    def test_occ_issue_with_pre_revert_version_returns_412(self, api):
        """PRD §2.6: "Issuing a product requires `expected_product_version`
        holding the client's last observed `version` of the product being
        issued. When the supplied value does not match the entity's current
        `version` — for example, because a coordination decline or a
        coordination deadline expiry reverted a pending product to `DRAFT`, and
        that reversion advanced the product's `version` after the client
        captured it — the write is rejected with `ERR_STALE_VERSION` (HTTP
        412), and the client must re-read the resource and retry against the
        current version."

        Design: Corner/cross_cutting_layers/occ_issue_with_pre_revert_version_returns_412
        """
        bundle = setup_coordinated_offices(api, timeout_minutes=15)
        set_clock(api, "2026-09-01T09:00:00Z")
        draft = create_watch_draft(
            api,
            bundle.office_a,
            bundle.headers_a,
            [bundle.zone_a["id"], bundle.zone_b["id"]],
            hazard_type="SEVERE_THUNDERSTORM",
            effective_from="2026-09-01T12:00:00Z",
            expires_at="2026-09-01T20:00:00Z",
        )
        submitted = submit_coordination(api, draft["id"], bundle.headers_a)
        set_clock(api, "2026-09-01T09:16:00Z")  # past the 09:15 deadline: revert to DRAFT

        resp = api.issue_product(
            draft["id"],
            {"expected_product_version": submitted["version"]},
            bundle.headers_a,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        product = get_product(api, draft["id"], bundle.headers_a)
        assert product["status"] == "DRAFT"
        assert product["version"] == submitted["version"] + 1
        request = list_coordination_requests(api, draft["id"], bundle.headers_a)[0]
        assert request["status"] == "EXPIRED"
