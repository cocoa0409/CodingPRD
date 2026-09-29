"""Reference data, server-minted properties, request shape and not-found codes.

Every test in this module starts against an empty database and positions the
logical clock as its first call.
"""

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    assert_error_envelope_shape,
    assert_instants_equal,
    assert_rental_account,
    assert_service_site,
    assert_site_gate,
    factories as f,
    fixtures as fx,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
SALES = TEST_USERS["sales_rep_headers"]
COORDINATOR = TEST_USERS["permit_coordinator_headers"]
PLANNER = TEST_USERS["dispatch_planner_headers"]
DRIVER = TEST_USERS["driver_operator_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]


class TestOpeningTheBranch:
    """Creation contracts of the reference collections."""

    def test_01_opening_an_account_returns_201_with_a_zeroed_credit_ledger(self):
        """A new account echoes its inputs and reports an empty credit ledger.

        PRD 3.1: "A freshly opened account has `open_credit_balance_cents` of 0
        and `billing_hold` of false; both are derived fields, described in §3.6
        where the credits that drive them are generated."
        PRD 4: "Operations that bring a new resource into existence return
        `201 Created`."

        Design: Corner/entities/create_rental_account_returns_201_with_zeroed_credit_ledger
        """
        clock = fx.reposition_clock("2026-08-03T08:00:00Z")
        assert_instants_equal(
            clock["current_utc"], "2026-08-03T08:00:00.000Z", "current_utc"
        )

        response = api_client.create_rental_account(
            {
                "legal_name": "Alder Creek Rentals",
                "account_type": "EVENT",
                "credit_terms_days": 45,
                "status": "ACTIVE",
            },
            ADMIN,
        )
        account = validate_success(response, 201)

        assert_rental_account(account)
        assert account["legal_name"] == "Alder Creek Rentals"
        assert account["account_type"] == "EVENT"
        assert account["credit_terms_days"] == 45
        assert account["status"] == "ACTIVE"
        assert account["open_credit_balance_cents"] == 0, (
            "a freshly opened account carries an open credit balance of 0, got "
            f"{account['open_credit_balance_cents']}"
        )
        assert account["billing_hold"] is False, (
            f"a freshly opened account is not on hold, got {account['billing_hold']}"
        )
        assert account["version"] == 1, (
            f"a first write leaves version at 1, got {account['version']}"
        )
        assert is_valid_uuid(account["id"]), (
            f"the account id must be a server-minted uuid, got {account['id']!r}"
        )

    def test_02_reading_a_new_site_returns_its_inputs_with_a_restricted_posture(self):
        """A site with no filings reports NONE / RESTRICTED / 0 on read-back.

        PRD 3.1: "A newly registered site has `deployed_unit_count` of 0, a
        `permit_status` of `NONE`, and — following directly from §2.5 — a
        `site_posture` of `RESTRICTED`, because a site with no filings can be
        planned against but not mobilized onto."

        Design: Corner/entities/get_service_site_returns_stored_fields_with_derived_posture_restricted
        """
        fx.reposition_clock("2026-08-03T08:00:00Z")
        account = fx.open_account(
            "Alder Creek Rentals", account_type="EVENT", credit_terms_days=45
        )
        created = fx.register_site(
            account["id"],
            "Alder Creek Fairway",
            jurisdiction_code="OR-LA-CITY",
            access_class="STAIR_ACCESS",
            right_of_way_required=True,
            gate_open_minute=420,
            gate_close_minute=1140,
            max_truck_length_ft=30,
        )

        site = validate_success(
            api_client.get_service_site(created["id"], COORDINATOR)
        )

        assert_service_site(site)
        assert site["account_id"] == account["id"]
        assert site["site_label"] == "Alder Creek Fairway"
        assert site["jurisdiction_code"] == "OR-LA-CITY"
        assert site["access_class"] == "STAIR_ACCESS"
        assert site["right_of_way_required"] is True
        assert site["gate_open_minute"] == 420
        assert site["gate_close_minute"] == 1140
        assert site["max_truck_length_ft"] == 30
        assert_site_gate(site, permit_status="NONE", site_posture="RESTRICTED")
        assert site["deployed_unit_count"] == 0, (
            f"a new site has no deployed units, got {site['deployed_unit_count']}"
        )

    def test_03_omitting_the_optional_site_inputs_applies_the_declared_defaults(self):
        """Omitted optional inputs resolve to their declared defaults, not null.

        PRD 3.1: "`right_of_way_required`, defaulting to false, declares that
        units will sit on public right-of-way and therefore that a second permit
        kind is required"
        PRD 3.1: "`gate_open_minute`, defaulting to 0, is the earliest
        minute-of-day at which a truck may enter, accepted in the inclusive range
        from 0 to 1439"
        PRD 3.1: "`max_truck_length_ft`, defaulting to 24, is the longest
        transport length in feet the site can physically accept, accepted in the
        inclusive range from 8 to 60"
        PRD 3.1: "Payment terms are recorded in `credit_terms_days`, which may be
        omitted — it then defaults to 30"

        Design: Corner/entities/create_service_site_omitting_optional_inputs_applies_declared_defaults
        """
        fx.reposition_clock("2026-08-03T08:00:00Z")
        account = validate_success(
            api_client.create_rental_account(
                {"legal_name": "Cobblestone Events", "account_type": "EVENT"}, ADMIN
            ),
            201,
        )
        assert account["credit_terms_days"] == 30, (
            "an omitted credit_terms_days defaults to 30, got "
            f"{account['credit_terms_days']}"
        )
        assert account["status"] == "ACTIVE", (
            f"an omitted account status defaults to ACTIVE, got {account['status']}"
        )

        site = validate_success(
            api_client.create_service_site(
                {
                    "account_id": account["id"],
                    "site_label": "Cobblestone Square",
                    "jurisdiction_code": "NY-NY-CITY",
                    "access_class": "CRANE_ONLY",
                },
                SALES,
            ),
            201,
        )

        assert site["right_of_way_required"] is False
        assert site["gate_open_minute"] == 0, (
            f"an omitted gate_open_minute defaults to 0, got {site['gate_open_minute']}"
        )
        assert site["gate_close_minute"] == 1440, (
            "an omitted gate_close_minute defaults to 1440, got "
            f"{site['gate_close_minute']}"
        )
        assert site["max_truck_length_ft"] == 24, (
            "an omitted max_truck_length_ft defaults to 24, got "
            f"{site['max_truck_length_ft']}"
        )
        assert_site_gate(site, permit_status="NONE", site_posture="RESTRICTED")
        assert site["deployed_unit_count"] == 0
        for field in (
            "right_of_way_required",
            "gate_open_minute",
            "gate_close_minute",
            "max_truck_length_ft",
        ):
            assert site[field] is not None, (
                f"{field} must resolve to its declared default rather than null"
            )

    def test_04_account_identity_and_timestamps_are_minted_by_the_server(self):
        """id, created_at, updated_at and version are server-owned and stable.

        PRD 2.9: "`id` (string): a server-minted UUID. It carries no type prefix
        — the raw UUID is the identifier."
        PRD 2.9: "`created_at` (string): an ISO 8601 UTC timestamp with three
        fractional digits (for example `2026-08-01T00:00:00.000Z`) recording when
        the row was first created."
        PRD 2.4: "The server does not read wall-clock time."
        PRD 3.1: "Payment terms are recorded in `credit_terms_days`, which may be
        omitted — it then defaults to 30 — and which is only ever one of the four
        values 0, 15, 30 or 45."

        Design: Corner/entities/rental_account_id_created_at_and_version_are_server_minted
        """
        fx.reposition_clock("2026-08-03T08:00:00Z")

        account = validate_success(
            api_client.create_rental_account(
                {
                    "legal_name": "Redstone Municipal Works",
                    "account_type": "MUNICIPAL",
                    "credit_terms_days": 0,
                },
                ADMIN,
            ),
            201,
        )

        assert is_valid_uuid(account["id"]), (
            f"the id must be a raw uuid with no type prefix, got {account['id']!r}"
        )
        assert account["version"] == 1
        assert_instants_equal(
            account["created_at"], "2026-08-03T08:00:00.000Z", "created_at"
        )
        assert_instants_equal(
            account["updated_at"], "2026-08-03T08:00:00.000Z", "updated_at"
        )
        assert account["credit_terms_days"] == 0, (
            "credit_terms_days 0 is a declared member and must not fall back to "
            f"the default 30, got {account['credit_terms_days']}"
        )

        read_back = validate_success(
            api_client.get_rental_account(account["id"], ADMIN)
        )
        assert read_back["id"] == account["id"]
        assert_instants_equal(
            read_back["created_at"], account["created_at"], "created_at on read-back"
        )
        assert_instants_equal(
            read_back["updated_at"], account["updated_at"], "updated_at on read-back"
        )
        assert read_back["version"] == account["version"]


class TestListingAndPagination:
    """The shared pagination envelope over a reverse-lookup listing."""

    def test_05_site_permit_listing_reports_total_count_and_has_more(self):
        """Two windows over three filings report the same total and flip has_more.

        PRD 2.3: "`limit` caps the number of rows returned; when omitted it
        defaults to 10, its minimum accepted value is 1 and its maximum accepted
        value is 100."
        PRD 2.3: "`total_count` reports the number of rows matching the request's
        filters before the pagination window is applied, and `has_more` reports
        whether any matching row falls beyond that window."
        PRD 3.2: "Filings on a site can be listed by reverse lookup and narrowed
        by `permit_kind` or by `status`."

        Design: Corner/entities/list_site_permits_paginates_with_total_count_and_has_more
        """
        fx.reposition_clock("2026-08-03T08:00:00Z")
        account = fx.open_account(
            "Willow Bend Municipal", account_type="MUNICIPAL", credit_terms_days=45
        )
        site = fx.register_site(
            account["id"],
            "Willow Bend Park",
            jurisdiction_code="OH-FR-CITY",
            access_class="OPEN_LOT",
            right_of_way_required=True,
            gate_open_minute=360,
            gate_close_minute=1080,
            max_truck_length_ft=40,
        )
        permit_one = fx.file_permit(
            site["id"], "PL-9001", permit_kind="PLACEMENT",
            effective_from="2026-08-01", effective_to="2026-10-31",
        )
        permit_two = fx.file_permit(
            site["id"], "RW-9001", permit_kind="RIGHT_OF_WAY",
            effective_from="2026-08-01", effective_to="2026-10-31",
        )
        permit_three = fx.file_permit(
            site["id"], "PL-9002", permit_kind="PLACEMENT",
            effective_from="2026-09-01", effective_to="2026-12-31",
        )

        page_one, meta_one = validate_paginated(
            api_client.list_site_permits(
                site["id"], COORDINATOR, {"limit": 2, "offset": 0}
            )
        )
        assert len(page_one) == 2, f"expected a window of 2 rows, got {len(page_one)}"
        assert meta_one["limit"] == 2
        assert meta_one["offset"] == 0
        assert meta_one["total_count"] == 3, (
            f"three filings exist on the site, meta reports {meta_one['total_count']}"
        )
        assert meta_one["has_more"] is True, (
            "a third filing falls beyond the first window, so has_more must be true"
        )

        page_two, meta_two = validate_paginated(
            api_client.list_site_permits(
                site["id"], COORDINATOR, {"limit": 2, "offset": 2}
            )
        )
        assert len(page_two) == 1, f"expected the tail row only, got {len(page_two)}"
        assert meta_two["limit"] == 2
        assert meta_two["offset"] == 2
        assert meta_two["total_count"] == 3
        assert meta_two["has_more"] is False, (
            "no filing falls beyond the second window, so has_more must be false"
        )

        windowed_ids = [row["id"] for row in page_one] + [
            row["id"] for row in page_two
        ]
        assert len(set(windowed_ids)) == 3, (
            f"the two windows must not repeat a row, got {windowed_ids}"
        )
        assert set(windowed_ids) == {
            permit_one["id"], permit_two["id"], permit_three["id"]
        }

        filtered, meta_filtered = validate_paginated(
            api_client.list_site_permits(
                site["id"], COORDINATOR, {"permit_kind": "RIGHT_OF_WAY"}
            )
        )
        assert len(filtered) == 1
        assert filtered[0]["id"] == permit_two["id"]
        assert meta_filtered["total_count"] == 1, (
            "total_count counts the rows matching the filter, not every row on the "
            f"site, got {meta_filtered['total_count']}"
        )


class TestNotFoundResolution:
    """Unresolvable identifiers and their per-collection codes."""

    def test_06_reading_an_unminted_contract_id_returns_contract_not_found(self):
        """A never-minted uuid on the contract read path is a 404, not a 500.

        PRD 2.8: "Path identifiers are nonetheless validated left to right, and
        the first identifier in a path that does not resolve determines the
        error."
        PRD 2.8: "Each collection has its own not-found code: an unresolvable
        account identifier yields `ERR_ACCOUNT_NOT_FOUND`, a service site
        `ERR_SITE_NOT_FOUND`, a placement permit `ERR_PERMIT_NOT_FOUND`, a rental
        contract `ERR_CONTRACT_NOT_FOUND`, a route `ERR_ROUTE_NOT_FOUND`, a
        service schedule `ERR_SCHEDULE_NOT_FOUND`, a service visit
        `ERR_VISIT_NOT_FOUND`, a waste manifest `ERR_MANIFEST_NOT_FOUND`, a charge
        event `ERR_CHARGE_NOT_FOUND`, an asset unit `ERR_ASSET_UNIT_NOT_FOUND`, a
        unit deployment `ERR_DEPLOYMENT_NOT_FOUND` and a disposal facility
        `ERR_DISPOSAL_SITE_NOT_FOUND`."

        Design: Corner/entities/get_rental_contract_with_unknown_id_returns_contract_not_found
        """
        fx.reposition_clock("2026-08-03T08:00:00Z")

        error = validate_error(
            api_client.get_rental_contract(NON_EXISTENT_UUID, SALES),
            "ERR_CONTRACT_NOT_FOUND",
            404,
        )
        assert_error_envelope_shape(error)
        assert isinstance(error["message"], str) and error["message"].strip(), (
            f"the error message must be a non-empty string, got {error['message']!r}"
        )

    def test_07_a_body_foreign_key_that_does_not_resolve_reports_its_own_code(self):
        """An unminted account_id in the body yields ERR_ACCOUNT_NOT_FOUND.

        PRD 2.8: "Identifiers carried in a request body are resolved after path
        identifiers and after request-shape validation, in the order the fields
        are declared for that operation, using the same code mapping."
        PRD 2.11: "Body identifier resolution, in declared field order — the same
        per-collection not-found codes."

        Design: Corner/entities/create_service_site_with_unknown_account_id_returns_account_not_found
        """
        fx.reposition_clock("2026-08-03T08:00:00Z")

        validate_error(
            api_client.create_service_site(
                {
                    "account_id": NON_EXISTENT_UUID,
                    "site_label": "Orphan Lot",
                    "jurisdiction_code": "TX-DA-CITY",
                    "access_class": "OPEN_LOT",
                },
                SALES,
            ),
            "ERR_ACCOUNT_NOT_FOUND",
            404,
        )

    def test_08_every_collection_reports_a_distinct_not_found_code(self):
        """Twelve single-row reads of one unminted uuid yield twelve codes.

        PRD 2.8: "Each collection has its own not-found code: an unresolvable
        account identifier yields `ERR_ACCOUNT_NOT_FOUND`, a service site
        `ERR_SITE_NOT_FOUND`, a placement permit `ERR_PERMIT_NOT_FOUND`, a rental
        contract `ERR_CONTRACT_NOT_FOUND`, a route `ERR_ROUTE_NOT_FOUND`, a
        service schedule `ERR_SCHEDULE_NOT_FOUND`, a service visit
        `ERR_VISIT_NOT_FOUND`, a waste manifest `ERR_MANIFEST_NOT_FOUND`, a charge
        event `ERR_CHARGE_NOT_FOUND`, an asset unit `ERR_ASSET_UNIT_NOT_FOUND`, a
        unit deployment `ERR_DEPLOYMENT_NOT_FOUND` and a disposal facility
        `ERR_DISPOSAL_SITE_NOT_FOUND`."
        PRD 2.8: "All twelve are HTTP 404."

        Design: Corner/errors/every_not_found_code_is_triggerable_with_an_unminted_id
        """
        clock = fx.reposition_clock("2026-08-03T08:00:00Z")
        assert_instants_equal(
            clock["current_utc"], "2026-08-03T08:00:00.000Z", "current_utc"
        )

        probes = [
            (api_client.get_rental_account, ADMIN, "ERR_ACCOUNT_NOT_FOUND"),
            (api_client.get_service_site, SALES, "ERR_SITE_NOT_FOUND"),
            (api_client.get_placement_permit, COORDINATOR, "ERR_PERMIT_NOT_FOUND"),
            (api_client.get_asset_unit, PLANNER, "ERR_ASSET_UNIT_NOT_FOUND"),
            (api_client.get_disposal_site, DRIVER, "ERR_DISPOSAL_SITE_NOT_FOUND"),
            (api_client.get_route, PLANNER, "ERR_ROUTE_NOT_FOUND"),
            (api_client.get_rental_contract, SALES, "ERR_CONTRACT_NOT_FOUND"),
            (api_client.get_unit_deployment, PLANNER, "ERR_DEPLOYMENT_NOT_FOUND"),
            (api_client.get_service_schedule, PLANNER, "ERR_SCHEDULE_NOT_FOUND"),
            (api_client.get_service_visit, DRIVER, "ERR_VISIT_NOT_FOUND"),
            (api_client.get_waste_manifest, DRIVER, "ERR_MANIFEST_NOT_FOUND"),
            (api_client.get_charge_event, OFFICER, "ERR_CHARGE_NOT_FOUND"),
        ]

        observed = []
        for read, headers, expected_error_id in probes:
            error = validate_error(
                read(NON_EXISTENT_UUID, headers), expected_error_id, 404
            )
            observed.append(error["error_id"])

        assert len(set(observed)) == 12, (
            "all twelve collections must report pairwise distinct not-found "
            f"codes, got {observed}"
        )


class TestRequestShape:
    """Required fields, declared enums, declared ranges and conditional rules."""

    def test_09_adding_a_yard_asset_without_its_unit_class_is_refused(self):
        """unit_class has no default, so omitting it is a shape violation.

        PRD 3.1: "Each `AssetUnit` carries an `asset_tag` of 1 to 32 characters
        that must be unique across the whole fleet, a `unit_class` drawn from
        `STANDARD_PORTABLE`, `ADA_PORTABLE`, `HANDWASH_STATION`, `TRAILER_2STALL`
        and `TRAILER_8STALL`, a home `yard_code` of 2 to 16 characters, and a
        `tare_length_ft` between 4 and 60 inclusive that is the number compared
        against a site's accepted truck length."
        PRD 2.11: "Request shape: required fields present, types correct, enum
        values declared members, integers inside their declared ranges, and the
        same-payload ordering and conditional-field rules enumerated in §3 —
        `ERR_INVALID_REQUEST`."

        Design: Corner/entities/create_asset_unit_missing_required_unit_class_returns_invalid_request
        """
        fx.reposition_clock("2026-08-03T08:00:00Z")

        validate_error(
            api_client.create_asset_unit(
                {"asset_tag": "SP-000", "yard_code": "YD-1", "tare_length_ft": 8},
                ADMIN,
            ),
            "ERR_INVALID_REQUEST",
            400,
        )

        # The tag is unique across the whole fleet, so a well-formed create with
        # the same tag proves the refused request persisted nothing.
        recreated = validate_success(
            api_client.create_asset_unit(
                {
                    "asset_tag": "SP-000",
                    "unit_class": "STANDARD_PORTABLE",
                    "yard_code": "YD-1",
                    "tare_length_ft": 8,
                },
                ADMIN,
            ),
            201,
        )
        assert recreated["asset_tag"] == "SP-000"

    def test_10_contract_shape_violations_are_each_refused_with_invalid_request(self):
        """A non-member enum, an out-of-range integer, the EVENT_NA rule and a
        reversed term window are all refused, and none of them persists a row.

        PRD 3.3: "Escalation buckets are fixed at creation: `season_code` is one
        of `PEAK`, `SHOULDER` or `OFF`, and `construction_phase` is one of
        `SITEWORK`, `VERTICAL`, `FINISHES` or `EVENT_NA`."
        PRD 3.3: "Demand is described by `headcount`, the peak simultaneous
        population to serve, accepted from 1 to 20000 inclusive; by
        `event_duration_hours`, the hours that population is on site each day,
        accepted from 1 to 24 inclusive; and by `service_frequency_per_week`, the
        number of pump-and-restock visits per week, accepted from 1 to 7
        inclusive."
        PRD 3.3: "An `EVENT` contract must pass `EVENT_NA` as its
        `construction_phase`; any other combination is a request-shape violation
        rejected with `ERR_INVALID_REQUEST`."
        PRD 3.3: "The rental window is bounded by `term_start` and `term_end`,
        both inclusive `YYYY-MM-DD` dates with `term_end` on or after
        `term_start`."

        Design: Corner/entities/create_rental_contract_with_invalid_enum_season_code_is_rejected
        """
        fx.reposition_clock("2026-08-03T08:00:00Z")
        account = fx.open_account(
            "Bramble Hollow Fairs", account_type="EVENT", credit_terms_days=15
        )
        site = fx.register_site(
            account["id"],
            "Bramble Hollow Field",
            jurisdiction_code="VA-FA-CITY",
            access_class="OPEN_LOT",
        )

        base = {
            "account_id": account["id"],
            "site_id": site["id"],
            "contract_kind": "EVENT",
            "term_start": "2026-08-14",
            "term_end": "2026-08-16",
            "headcount": 250,
            "event_duration_hours": 10,
            "service_frequency_per_week": 3,
            "season_code": "PEAK",
            "construction_phase": "EVENT_NA",
            "ada_required": True,
        }
        probes = {
            "season_code outside its declared members": {"season_code": "WINTER"},
            "headcount above its declared range": {"headcount": 20001},
            "an EVENT contract not carrying EVENT_NA": {
                "construction_phase": "VERTICAL"
            },
            "term_end before term_start": {
                "term_start": "2026-08-16", "term_end": "2026-08-14"
            },
        }

        for label, mutation in probes.items():
            payload = dict(base)
            payload.update(mutation)
            error = validate_error(
                api_client.create_rental_contract(payload, SALES),
                "ERR_INVALID_REQUEST",
                400,
            )
            assert error["error_id"] == "ERR_INVALID_REQUEST", (
                f"{label} must be refused as a request-shape violation"
            )

        rows, meta = validate_paginated(
            api_client.list_rental_contracts(SALES, {"account_id": account["id"]})
        )
        assert meta["total_count"] == 0, (
            "none of the four refused requests may persist a contract, but "
            f"{meta['total_count']} rows exist"
        )
        assert rows == []

    def test_11_enum_members_the_system_owns_are_refused_from_a_client(self):
        """MISSED_SERVICE_CREDIT, RERUN and the severity pairing rules are refused.

        PRD 3.6: "The fourth kind, `RERUN`, is written by the system only and is
        refused with `ERR_INVALID_REQUEST` if a client supplies it."
        PRD 3.8: "A `DAMAGE` charge additionally requires a `severity` of
        `MINOR`, `MODERATE` or `TOTAL_LOSS`; a `TIP_OVER` charge must not carry a
        severity at all; both kinds require an `asset_unit_id`; and
        `MISSED_SERVICE_CREDIT` is never accepted from a client, since the system
        generates credits itself."
        PRD 3.8: "Any of those combinations violated is `ERR_INVALID_REQUEST`."

        Design: Corner/validations/system_only_field_values_are_never_accepted_from_a_client
        """
        env = fx.setup_active_contract_with_deployment(
            legal_name="Elderberry Contractors",
            site_label="Elderberry Rise",
            authority_ref="PL-11001",
            authority_decision_ref="AD-11001",
            site_overrides={"jurisdiction_code": "NV-CL-CITY"},
            asset_tag="SP-1201",
            yard_code="YD-12",
        )
        route = fx.create_route("RT-MON-96", truck_capacity_units=20)
        schedule = fx.attach_schedule(env["contract"]["id"], route["id"])

        validate_error(
            api_client.create_charge_event(
                {
                    "contract_id": env["contract"]["id"],
                    "asset_unit_id": env["asset"]["id"],
                    "charge_kind": "MISSED_SERVICE_CREDIT",
                },
                OFFICER,
            ),
            "ERR_INVALID_REQUEST",
            400,
        )
        validate_error(
            api_client.create_service_visit(
                {
                    "schedule_id": schedule["id"],
                    "visit_kind": "RERUN",
                    "scheduled_date": "2026-08-10",
                    "window_start_minute": 480,
                    "window_end_minute": 540,
                },
                PLANNER,
            ),
            "ERR_INVALID_REQUEST",
            400,
        )
        validate_error(
            api_client.create_charge_event(
                {
                    "contract_id": env["contract"]["id"],
                    "asset_unit_id": env["asset"]["id"],
                    "charge_kind": "TIP_OVER",
                    "severity": "MINOR",
                },
                OFFICER,
            ),
            "ERR_INVALID_REQUEST",
            400,
        )
        validate_error(
            api_client.create_charge_event(
                {
                    "contract_id": env["contract"]["id"],
                    "asset_unit_id": env["asset"]["id"],
                    "charge_kind": "DAMAGE",
                },
                OFFICER,
            ),
            "ERR_INVALID_REQUEST",
            400,
        )

        charges, charge_meta = validate_paginated(
            api_client.list_charge_events(
                OFFICER, {"contract_id": env["contract"]["id"]}
            )
        )
        assert charge_meta["total_count"] == 0, (
            f"no charge may be persisted by a refused request, got {charges}"
        )
        visits, visit_meta = validate_paginated(
            api_client.list_service_visits(PLANNER, {"schedule_id": schedule["id"]})
        )
        assert visit_meta["total_count"] == 0, (
            f"no visit may be persisted by a refused request, got {visits}"
        )
