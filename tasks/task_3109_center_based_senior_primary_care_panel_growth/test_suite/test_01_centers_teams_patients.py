"""Entity creation, retrieval, listing, defaults, computed fields, and input
validation claims for the core resources."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_center,
    assert_patient,
    create_center_payload,
    create_health_plan_payload,
    create_open_center,
    create_patient_payload,
    create_vehicle_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestCenterCreation:
    def test_center_create_returns_defaults_and_201(
        self, api, network_operator_headers
    ):
        """PRD §3.1: "A newly created center starts in `PRE_OPEN` with `maturity_months` of 0,
        `profitability_tier` of `RAMP`, and `cumulative_contribution_cents` of 0."
        PRD §4: "Operations that create new resources return a `201 Created` status code."

        Design: Corner/entities/center_create_returns_defaults_and_201
        """
        resp = api.create_center(
            create_center_payload(
                name="Harbor", neighborhood_code="CHI-HARBOR-02", opened_on="2026-09-01"
            ),
            network_operator_headers,
        )
        center = validate_success(resp, 201)
        assert_center(center)
        assert center["status"] == "PRE_OPEN"
        assert center["profitability_tier"] == "RAMP"
        assert center["maturity_months"] == 0
        assert center["cumulative_contribution_cents"] == 0
        assert center["version"] == 1

    def test_center_create_missing_opened_on_rejected(self, api, network_operator_headers):
        """PRD §2.7: "Request well-formedness — required fields present, enum values legal,
        and numeric ranges honored, including `risk_score` between 0.50 and 4.00,
        `panel_cap` at least 1, and an adjudicated amount within the claimed range
        (`ERR_INVALID_REQUEST`)."

        Design: Corner/entities/center_create_missing_opened_on_rejected
        """
        resp = api.create_center(
            {"name": "NoDate", "neighborhood_code": "N9"}, network_operator_headers
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400)


class TestPatientRetrieval:
    def test_patient_get_round_trips_stored_fields(
        self, api, enrollment_coordinator_headers
    ):
        """PRD §3.3: "an optional `transport_dependent` flag defaulting to false."
        PRD §3.3: "New patients start with `no_show_strikes` of 0."

        Design: Corner/entities/patient_get_round_trips_stored_fields
        """
        created = validate_success(
            api.create_patient(
                create_patient_payload(
                    full_name="Della Roe",
                    date_of_birth="1955-04-12",
                    zip_code="60607",
                    risk_score=1.75,
                ),
                enrollment_coordinator_headers,
            ),
            201,
        )
        patient = validate_success(
            api.get_patient(created["id"], enrollment_coordinator_headers), 200
        )
        assert_patient(patient)
        assert patient["full_name"] == "Della Roe"
        assert patient["risk_score"] == 1.75
        assert patient["transport_dependent"] is False
        assert patient["no_show_strikes"] == 0

    def test_get_missing_patient_returns_not_found(self, api, enrollment_coordinator_headers):
        """PRD §2.7: "Left-to-right existence of path resource identifiers (`ERR_NOT_FOUND`)."

        Design: Corner/entities/get_missing_patient_returns_not_found
        """
        resp = api.get_patient(NON_EXISTENT_UUID, enrollment_coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, expected_status=404)

    def test_patient_system_fields_generated_input_ignored(
        self, api, enrollment_coordinator_headers
    ):
        """PRD §2.5: "`id` (string): a unique, server-minted UUID with no type prefix."
        PRD §2.5: "`version` (integer): a system-managed integer that increments by 1 on
        every mutation, including mutations driven by cascading side effects."

        Design: Corner/entities/patient_system_fields_generated_input_ignored
        """
        bogus_id = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"
        payload = create_patient_payload(
            full_name="Sys", date_of_birth="1950-01-01", zip_code="60601", risk_score=1.00
        )
        payload["id"] = bogus_id
        payload["version"] = 42
        patient = validate_success(
            api.create_patient(payload, enrollment_coordinator_headers), 201
        )
        assert patient["id"] != bogus_id, "server must mint the id, ignoring client input"
        assert patient["version"] == 1


class TestCenterListingPagination:
    def test_centers_list_paginates_with_total_count_and_has_more(
        self, api, network_operator_headers, finance_analyst_headers
    ):
        """PRD §2.3: "The `limit` parameter specifies the maximum number of items to return;
        it defaults to 10 when omitted, accepts a minimum of 1, and is capped at a maximum
        of 100. The `offset` parameter specifies how many items to skip from the start of
        the result set and defaults to 0."
        PRD §2.3: "The `meta` object of every list response carries the four pagination
        fields `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/centers_list_paginates_with_total_count_and_has_more
        """
        for name in ("C1", "C2", "C3"):
            validate_success(
                api.create_center(
                    create_center_payload(name=name, neighborhood_code=f"N-{name}"),
                    network_operator_headers,
                ),
                201,
            )
        data, meta = validate_paginated(
            api.list_centers(finance_analyst_headers, params={"limit": 2, "offset": 0})
        )
        assert len(data) == 2
        assert meta["total_count"] == 3
        assert meta["has_more"] is True

        data2, meta2 = validate_paginated(
            api.list_centers(finance_analyst_headers, params={"limit": 2, "offset": 2})
        )
        assert len(data2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False


class TestVehicleDefaults:
    def test_vehicle_wheelchair_default_false(self, api, network_operator_headers):
        """PRD §3.1: "vehicles are registered with a `plate`, a `seat_capacity` of at least 1,
        and an optional `wheelchair_capable` flag defaulting to false."

        Design: Corner/entities/vehicle_wheelchair_default_false
        """
        center = validate_success(
            api.create_center(
                create_center_payload(name="D", neighborhood_code="ND"),
                network_operator_headers,
            ),
            201,
        )
        vehicle = validate_success(
            api.create_vehicle(
                center["id"],
                create_vehicle_payload(plate="IL-1234", seat_capacity=4),
                network_operator_headers,
            ),
            201,
        )
        assert vehicle["wheelchair_capable"] is False


class TestCareTeamComputedFields:
    def test_care_team_staffing_score_computed_ignores_input(
        self, api, network_operator_headers
    ):
        """PRD §3.2: "The team's `staffing_score` is computed as the physician count times 1.0,
        plus the community health worker count times 0.5, plus the behavioral clinician
        count times 0.75, rounded half-up to 2 decimal places; it is recomputed whenever
        any staffing field changes."
        PRD §3.2: "A client may suggest a `staffing_score` at creation, but the computed
        value governs."

        Design: Corner/entities/care_team_staffing_score_computed_ignores_input
        """
        center = validate_success(
            api.create_center(
                create_center_payload(name="E", neighborhood_code="NE"),
                network_operator_headers,
            ),
            201,
        )
        resp = api.create_care_team(
            center["id"],
            {
                "team_label": "T",
                "panel_cap": 10,
                "physician_count": 2,
                "chw_count": 2,
                "behavioral_count": 1,
                "staffing_score": 99.99,
            },
            network_operator_headers,
        )
        team = validate_success(resp, 201)
        assert team["staffing_score"] == 3.75, (
            f"expected 3.75 (2*1.0 + 2*0.5 + 1*0.75), got {team['staffing_score']}"
        )

    def test_care_team_create_requires_existing_center(self, api, network_operator_headers):
        """PRD §2.12: "The existence of each path identifier is confirmed in order, and the
        request is rejected immediately with `ERR_NOT_FOUND` (HTTP 404) for the first
        identifier that does not correspond to an existing resource."

        Design: Corner/entities/care_team_create_requires_existing_center
        """
        resp = api.create_care_team(
            NON_EXISTENT_UUID,
            {
                "team_label": "T",
                "panel_cap": 10,
                "physician_count": 1,
                "chw_count": 1,
                "behavioral_count": 0,
            },
            network_operator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, expected_status=404)


class TestEnumConstraints:
    def test_health_plan_invalid_contract_type_rejected(
        self, api, finance_controller_headers
    ):
        """PRD §2.7: "Request well-formedness — required fields present, enum values legal,
        and numeric ranges honored, including `risk_score` between 0.50 and 4.00,
        `panel_cap` at least 1, and an adjudicated amount within the claimed range
        (`ERR_INVALID_REQUEST`)."
        PRD §3.3: "a `contract_type` of `FULL_RISK` or `SHARED_SAVINGS`, a `base_pmpm_cents` capitation amount in cents."

        Design: Corner/entities/attribution_invalid_status_enum_rejected
        """
        payload = create_health_plan_payload(
            plan_name="Bad",
            contract_type="PARTIAL",
            base_pmpm_cents=50000,
            risk_adjust_factor=1.0,
            revenue_share_pct=0.8,
        )
        resp = api.create_health_plan(payload, finance_controller_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400)


class TestNewTeamDefaults:
    def test_care_team_creation_defaults(self, api, network_operator_headers):
        """PRD §3.2: "New teams start with `active_panel_count` of 0, `waitlist_depth` of 0,
        and `accepting` true."

        Design: Corner/entities/care_team_staffing_score_computed_ignores_input
        """
        center, team, room = create_open_center()
        assert team["active_panel_count"] == 0
        assert team["waitlist_depth"] == 0
        assert team["accepting"] is True
