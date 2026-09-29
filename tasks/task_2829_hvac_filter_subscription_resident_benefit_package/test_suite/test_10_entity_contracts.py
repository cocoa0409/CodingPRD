"""
Entity-level contracts: creation payloads, defaulted and computed fields,
server-minted identity, the append-only observation shape, listing metadata and
the 404 family for unresolvable references.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_INVALID_REQUEST,
    ERR_PROPERTY_NOT_FOUND,
    ERR_SUBSCRIPTION_NOT_FOUND,
    ERR_UNIT_NOT_FOUND,
)
from test_helpers.test_users import OPERATOR


class TestCatalogAndPropertyContracts:
    """Creation and retrieval echo every declared field at its declared default."""

    def test_registering_a_sku_returns_it_active_at_version_one(self, api):
        """
        A POST carrying the seven catalog inputs answers 201 with each of them
        stored verbatim, the status defaulted to ACTIVE and version 1 on a
        server-minted bare UUID.

        PRD §3.1: "A newly registered SKU is `ACTIVE` with `version` 1."

        Design: Corner/entities/filtersku_creation_returns_201_with_every_declared_field
        """
        sku = validate_success(
            api.create_filter_sku(f.filter_sku_payload(), OPERATOR), 201
        )
        assert sku["sku_code"] == "SKU-16251-M8"
        assert sku["size_code"] == "16x25x1"
        assert sku["thickness_inches"] == 1
        assert sku["merv_rating"] == 8
        a.assert_cents(sku["unit_cost_cents"], 680, "unit_cost_cents")
        assert sku["ship_weight_oz"] == 14
        assert sku["pack_quantity"] == 1
        assert sku["status"] == "ACTIVE"
        assert is_valid_uuid(sku["id"])
        a.assert_mutable_entity(sku)
        assert sku["version"] == 1

    def test_a_fresh_property_reads_back_with_its_three_system_defaults(self, api):
        """
        GET on an untouched property echoes the seven stored inputs and reports
        ONBOARDING with a null suspend_reason, a zero balance and no units yet.

        PRD §3.2: "The new record starts with `outstanding_balance_cents` at 0, `unit_count` at 0, `suspend_reason` null and `version` 1."

        Design: Corner/entities/property_retrieval_returns_stored_and_defaulted_fields
        """
        created = fx.create_property(api)

        prop = validate_success(api.get_property(created["id"], OPERATOR))
        assert prop["name"] == "Cedar Ridge"
        assert prop["state_code"] == "TX"
        assert prop["billing_mode"] == "PM_BILLED"
        assert prop["benefit_tier"] == "PLUS"
        assert prop["damage_waiver_enabled"] is True
        assert prop["aqg_enabled"] is True
        a.assert_cents(prop["credit_limit_cents"], 5000000, "credit_limit_cents")
        assert prop["status"] == "ONBOARDING"
        assert prop["suspend_reason"] is None
        a.assert_cents(prop["outstanding_balance_cents"], 0, "outstanding_balance_cents")
        assert prop["unit_count"] == 0
        a.assert_mutable_entity(prop)
        assert prop["version"] == 1


def _two_pending_subscriptions(api):
    """Two PENDING_SETUP subscriptions at one property, on two units."""
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    fx.create_sku(api)
    prop = fx.create_property(api)
    unit_a = fx.create_unit(api, prop["id"])
    fx.activate_property(api, prop["id"])
    unit_b = fx.create_unit(api, prop["id"], unit_label="A-102")
    ada = fx.create_resident(api)
    ben = fx.create_resident(
        api, full_name="Ben Ortiz", email="ben.ortiz@example.com"
    )
    fx.set_clock(api, "2026-08-05T00:00:00Z")
    sub_a = fx.create_subscription(api, ada["id"], unit_a["id"])
    sub_b = fx.create_subscription(api, ben["id"], unit_b["id"])
    assert sub_a["status"] == "PENDING_SETUP" and sub_b["status"] == "PENDING_SETUP"
    return {
        "property_id": prop["id"],
        "resident_b_id": ben["id"],
        "sub_a_id": sub_a["id"],
        "sub_b_id": sub_b["id"],
    }


class TestSubscriptionListing:
    """total_count counts before pagination; has_more looks beyond the page."""

    def test_paging_and_filtering_report_consistent_metadata(self, api):
        """
        Two matching rows read one page at a time report total_count 2 throughout
        while has_more flips true then false, the two pages together yield both
        ids exactly once, and a resident_id filter narrows the count to one under
        the default limit and offset.

        PRD §2.3: "The `meta` object of a list response carries `limit`, `offset`, `total_count` and `has_more`, where `total_count` counts every row matching the filters before pagination is applied and `has_more` is true when rows remain beyond the returned page."

        Design: Corner/entities/subscriptions_list_reports_total_count_has_more_and_honours_filters
        """
        env = _two_pending_subscriptions(api)
        base = {"property_id": env["property_id"], "status": "PENDING_SETUP"}

        first, first_meta = validate_paginated(
            api.list_subscriptions(OPERATOR, dict(base, limit=1, offset=0))
        )
        assert len(first) == 1
        a.assert_page_meta(first_meta, limit=1, offset=0, total_count=2, has_more=True)

        second, second_meta = validate_paginated(
            api.list_subscriptions(OPERATOR, dict(base, limit=1, offset=1))
        )
        assert len(second) == 1
        a.assert_page_meta(second_meta, limit=1, offset=1, total_count=2, has_more=False)

        assert sorted([first[0]["id"], second[0]["id"]]) == sorted(
            [env["sub_a_id"], env["sub_b_id"]]
        )

        filtered, filtered_meta = validate_paginated(
            api.list_subscriptions(OPERATOR, {"resident_id": env["resident_b_id"]})
        )
        assert [row["id"] for row in filtered] == [env["sub_b_id"]]
        a.assert_page_meta(
            filtered_meta, limit=10, offset=0, total_count=1, has_more=False
        )


class TestDefaultedAndComputedFields:
    """What the client may omit, and what the client may not dictate."""

    def test_omitting_the_shipment_quantity_copies_filters_per_shipment(self, api):
        """
        A follow-up shipment created without a quantity takes the subscription's
        filters_per_shipment of 2 rather than a bare 1, and the omitted optional
        tracking code stays null.

        PRD §3.5: "When `quantity` is omitted it defaults to the subscription's `filters_per_shipment`; when it is supplied it must equal `filters_per_shipment` exactly, and any other value fails shape validation with `ERR_INVALID_REQUEST`."

        Design: Corner/entities/shipment_quantity_defaults_to_filters_per_shipment_when_omitted
        """
        env = fx.build_base_env(api)
        assert fx.read_subscription(api, env.subscription_id)["filters_per_shipment"] == 2

        created = validate_success(
            api.create_shipment(
                env.subscription_id, f.shipment_payload("2026-10-19"), OPERATOR
            ),
            201,
        )
        assert created["quantity"] == 2
        assert created["status"] == "SCHEDULED"
        assert created["sequence_number"] == 2
        assert created["sku_id"] == env.sku_id
        assert created["tracking_code"] is None
        assert created["version"] == 1

    def test_supplied_pricing_fields_are_discarded_for_the_derived_ones(self, api):
        """
        Enrolment accepts only the six documented inputs, so a body that also
        carries monthly_fee_cents 99, ship_cadence_days 999 and
        filters_per_shipment 42 is stored with the derived 3546, 75 and 2 instead,
        and both the SKU and the property are resolved server-side.

        PRD §3.3: "A `ProgramOperator` or the property's `PropertyManager` enrols a household on a unit by supplying the `resident_id` of the enrolled resident, the `unit_id` of the unit being filtered, a `billing_party` of either `PROPERTY_MANAGER` or `RESIDENT` naming who is invoiced for this particular subscription's fees, an `enrollment_channel` of `MOVE_IN_PACKET`, `RESIDENT_PORTAL` or `PM_BULK_UPLOAD` recording how the enrolment was captured, and the lease window as `lease_start_date` and `lease_end_date`, both date-only, with the end strictly later than the start."

        Design: Corner/entities/subscription_computed_pricing_fields_client_input_ignored
        """
        env = fx.build_base_env(
            api,
            activate=False,
            subscription_overrides={
                "monthly_fee_cents": 99,
                "ship_cadence_days": 999,
                "filters_per_shipment": 42,
            },
        )

        subscription = fx.read_subscription(api, env.subscription_id)
        a.assert_cents(subscription["monthly_fee_cents"], 3546, "monthly_fee_cents")
        assert subscription["ship_cadence_days"] == 75
        assert subscription["filters_per_shipment"] == 2
        assert subscription["assigned_sku_id"] == env.sku_id
        assert subscription["property_id"] == env.property_id

    def test_supplied_system_fields_are_discarded_on_catalog_creation(self, api):
        """
        A create body that also carries an id, a version and a status keeps none
        of them: the row comes back on a different server-minted UUID at version 1
        and ACTIVE, with both audit instants stamped by the server.

        PRD §2.4: "Every persisted record carries a server-minted `id` that is a UUID string with no type prefix, and a `created_at` timestamp in ISO 8601 UTC notation with exactly three fractional-second digits."

        Design: Corner/entities/filtersku_system_fields_client_extra_field_ignored
        """
        planted_id = "99999999-9999-4999-8999-999999999999"

        sku = validate_success(
            api.create_filter_sku(
                f.filter_sku_payload(id=planted_id, version=77, status="DISCONTINUED"),
                OPERATOR,
            ),
            201,
        )
        assert sku["id"] != planted_id
        assert sku["version"] == 1
        assert sku["status"] == "ACTIVE"
        a.assert_mutable_entity(sku)

        stored = validate_success(api.get_filter_sku(sku["id"], OPERATOR))
        assert stored["status"] == "ACTIVE"
        assert stored["version"] == 1

    def test_an_ingested_telemetry_window_exposes_no_version_or_updated_at(self, api):
        """
        A runtime reading is an append-only observation: the created row carries an
        id and a created_at and neither of the two mutation fields.

        PRD §2.4: "Three record types are append-only observations and therefore carry only `id` and `created_at` — for them both `updated_at` and `version` are absent from the payload entirely: `RuntimeReading` (an ingested telemetry window), `RenewalSurvey` (a resident's answered survey) and `LedgerEntry` (a money row)."

        Design: Corner/entities/runtime_reading_immutable_row_carries_no_version_field
        """
        env = fx.build_base_env(api, activate=False)
        fx.set_clock(api, "2026-08-07T00:00:00Z")

        reading = validate_success(
            api.create_runtime_reading(
                env.unit_id,
                f.runtime_reading_payload(
                    "2026-08-07T00:00:00Z", "2026-08-08T00:00:00Z", 168, 100, "PRESSURE_SENSOR"
                ),
                OPERATOR,
            ),
            201,
        )
        a.assert_immutable_entity(reading)
        assert reading["unit_id"] == env.unit_id
        assert reading["runtime_minutes"] == 168
        assert reading["static_pressure_delta_pa"] == 100
        assert reading["source"] == "PRESSURE_SENSOR"


class TestRejectedReferencesAndShapes:
    """The 404 family, and the shape gate that runs after it."""

    def test_a_well_formed_but_unknown_subscription_id_is_a_404(self, api):
        """
        A syntactically valid UUID that matches no row answers in the error
        envelope with ERR_SUBSCRIPTION_NOT_FOUND rather than an empty success.

        PRD §2.5: "Each missing referent has its own error: `ERR_PROPERTY_NOT_FOUND`, `ERR_UNIT_NOT_FOUND`, `ERR_SKU_NOT_FOUND`, `ERR_RESIDENT_NOT_FOUND`, `ERR_SUBSCRIPTION_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`, `ERR_CASE_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_TRANSFER_NOT_FOUND` and `ERR_ENTITLEMENT_NOT_FOUND`, all HTTP 404."

        Design: Corner/entities/get_subscription_with_unknown_id_returns_not_found
        """
        response = api.get_subscription(NON_EXISTENT_UUID, OPERATOR)
        error = validate_error(response, ERR_SUBSCRIPTION_NOT_FOUND, 404)
        assert error["message"].strip()
        a.assert_envelope_meta(response)

    def test_a_resident_created_without_an_email_is_rejected(self, api):
        """
        email is a required input with no default, so a body that omits it fails
        the shape gate with ERR_INVALID_REQUEST.

        PRD §2.4: "A malformed value in either family, a missing required field, a wrong JSON type, an unrecognised enumeration member, or an integer outside its declared range is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/create_resident_without_email_returns_invalid_request
        """
        payload = f.resident_payload()
        payload.pop("email")

        validate_error(api.create_resident(payload, OPERATOR), ERR_INVALID_REQUEST, 400)

    def test_an_unrecognised_hvac_system_type_is_rejected_and_counts_nothing(self, api):
        """
        MINI_SPLIT is not one of the four declared equipment types, so the unit is
        refused and the property's unit_count and version are both left alone.

        PRD §3.2: "Each unit records a `unit_label` of one to twenty-four characters that must be unique among that property's units, an `hvac_system_type` of `SINGLE_STAGE`, `TWO_STAGE`, `VARIABLE_SPEED` or `HEAT_PUMP`, a `filter_slot_count` of at least 1 and at most 6 giving the number of slots that must be re-filtered on every shipment, a `return_grille_count` of at least 1 and at most 6 that is documentation for the field crew and never an input to any fee, and a `nominal_size_code` in the same three-group dimension form as the catalog, read off the filter already sitting in the rack."

        Design: Corner/entities/create_unit_with_unknown_system_type_invalid_enum_rejected
        """
        prop = fx.create_property(api)

        validate_error(
            api.create_unit(
                prop["id"], f.unit_payload(hvac_system_type="MINI_SPLIT"), OPERATOR
            ),
            ERR_INVALID_REQUEST,
            400,
        )

        after = validate_success(api.get_property(prop["id"], OPERATOR))
        assert after["unit_count"] == 0
        assert after["version"] == 1

    def test_a_nested_create_under_an_unknown_parent_is_a_404(self, api):
        """
        The path identifier is resolved before the body is looked at, so creating a
        unit under a property that does not exist answers ERR_PROPERTY_NOT_FOUND.

        PRD §2.10: "Every resource the request references exists, path segments resolved left to right first and body foreign keys afterwards in declaration order — otherwise the matching 404 from §2.5."

        Design: Corner/entities/create_unit_under_unknown_property_returns_not_found
        """
        validate_error(
            api.create_unit(NON_EXISTENT_UUID, f.unit_payload(), OPERATOR),
            ERR_PROPERTY_NOT_FOUND,
            404,
        )

    def test_an_unknown_body_foreign_key_is_a_404_of_its_own(self, api):
        """
        Enrolment names its parents in the body; a unit_id resolving to nothing is
        ERR_UNIT_NOT_FOUND even though the resident id alongside it is real, and
        that resident is left a PROSPECT with no subscription behind it.

        PRD §2.5: "Only after every path segment resolves are foreign keys in the request body resolved, in the order they are declared for that endpoint."

        Design: Corner/entities/create_subscription_with_unknown_unit_id_not_found
        """
        fx.create_sku(api)
        resident = fx.create_resident(api)
        fx.set_clock(api, "2026-08-05T00:00:00Z")

        validate_error(
            api.create_subscription(
                f.subscription_payload(resident["id"], NON_EXISTENT_UUID), OPERATOR
            ),
            ERR_UNIT_NOT_FOUND,
            404,
        )

        assert validate_success(api.get_resident(resident["id"], OPERATOR))["status"] == (
            "PROSPECT"
        )
        rows, meta = validate_paginated(
            api.list_subscriptions(OPERATOR, {"resident_id": resident["id"]})
        )
        assert rows == [] and meta["total_count"] == 0
