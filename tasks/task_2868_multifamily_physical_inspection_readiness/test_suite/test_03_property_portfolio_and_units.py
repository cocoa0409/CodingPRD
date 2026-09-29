"""Registering properties and their dwelling units, and amending both.

A property's id doubles as the owner's principal identifier, so this module also
covers the read surfaces an owner does and does not hold.
"""

from test_helpers import (
    ApiErrorId,
    assert_cents,
    assert_common_fields,
    assert_created,
    assert_error,
    assert_fields,
    assert_integer,
    assert_null,
    assert_ok,
    assert_pagination_meta,
    assert_property_state,
    assert_total_count,
    constants as K,
    factories as F,
    fixtures as X,
)
from test_helpers.test_users import (
    ROLE_HOUSING_AGENCY_INSPECTOR,
    make_headers,
    make_headers_without_user_id,
    make_platform_admin_headers,
    make_property_owner_headers,
)

ADMIN = make_platform_admin_headers()


class TestPropertyRegistration:
    """A registered property must materialise its whole derived block."""

    def test_registration_returns_every_derived_field_zeroed(self, api):
        """The four inputs come back alongside six derived fields.

        PRD: "A freshly registered property starts at `readiness_posture`
        `READY`, with `open_life_threatening_count`,
        `overdue_life_threatening_count`, `open_severe_count` and
        `allocated_reserve_total_cents` all 0, and with `last_final_score` and
        `last_sweep_closed_at` both null."

        Design: Corner/entities/create_property_returns_all_fields_with_zeroed_derived_counters
        """
        response = api.create_property(F.property_payload(K.MAPLE_COURT), ADMIN)

        row = assert_created(response)
        assert_fields(
            row,
            name="Maple Court",
            total_unit_count=4,
            owner_contact_email="owner@maple.example",
        )
        assert_cents(row["capital_reserve_cents"], 1000000, "capital_reserve_cents")
        assert_property_state(row, "READY", 0, 0, 0)
        assert_null(row, "last_final_score", "last_sweep_closed_at")
        assert_cents(
            row["allocated_reserve_total_cents"],
            0,
            "allocated_reserve_total_cents",
        )
        assert_common_fields(row, expected_version=1)


class TestUnitRegistration:
    """Units are registered one at a time under an existing property."""

    def test_omitting_property_id_is_a_request_shape_error(self, api):
        """A body with no `property_id` fails the shape check, not the FK check.

        PRD: "every required body field is present and correctly typed, and
        every numeric field lies inside its declared range, else
        `ERR_INVALID_REQUEST` (400)."

        Design: Corner/entities/create_unit_missing_required_property_id_returns_invalid_request
        """
        property_id = X.create_property(api, K.MAPLE_COURT)["id"]

        response = api.create_unit(
            F.unit_payload(F.OMIT, "101", bedroom_count=2), ADMIN
        )

        assert_error(response, ApiErrorId.INVALID_REQUEST)
        assert_total_count(api.list_units(ADMIN, property_id=property_id), 0)

    def test_omitting_occupancy_status_defaults_the_unit_to_occupied(self, api):
        """A minimal unit body materialises both declared defaults.

        PRD: "Its `occupancy_status` is one of `OCCUPIED`, `VACANT` or `DOWN`,
        defaulting to `OCCUPIED` when omitted, and `occupant_display_name` gives
        the household name printed on the tenant notice".

        Design: Corner/entities/create_unit_omitting_occupancy_status_defaults_to_occupied
        """
        property_id = X.create_property(api, K.MAPLE_COURT)["id"]

        response = api.create_unit(
            F.unit_payload(
                property_id, "101", bedroom_count=2, occupancy_status=F.OMIT
            ),
            ADMIN,
        )

        unit = assert_created(response)
        assert_fields(unit, occupancy_status="OCCUPIED")
        assert_null(unit, "occupant_display_name")
        assert_integer(
            unit["prior_deficiency_count"], 0, "prior_deficiency_count"
        )
        assert_integer(unit["open_deficiency_count"], 0, "open_deficiency_count")
        assert_common_fields(unit, expected_version=1)

    def test_supplied_deficiency_counters_do_not_seed_the_new_unit(self, api):
        """A body claiming 99 prior deficiencies still creates a unit at 0.

        PRD: "A new unit begins with `prior_deficiency_count` and
        `open_deficiency_count` both 0."

        Design: Corner/entities/create_unit_with_prior_deficiency_count_extra_field_is_ignored
        """
        property_id = X.create_property(api, K.MAPLE_COURT)["id"]

        response = api.create_unit(
            F.unit_payload(
                property_id,
                "101",
                bedroom_count=2,
                prior_deficiency_count=99,
                open_deficiency_count=99,
            ),
            ADMIN,
        )

        unit = assert_created(response)
        assert_integer(
            unit["prior_deficiency_count"], 0, "prior_deficiency_count"
        )
        assert_integer(unit["open_deficiency_count"], 0, "open_deficiency_count")

        reread = assert_ok(api.get_unit(unit["id"], ADMIN))
        assert_integer(
            reread["prior_deficiency_count"], 0, "prior_deficiency_count"
        )

    def test_unknown_parent_property_is_a_body_identifier_not_found(self, api):
        """An unresolvable `property_id` yields the property's own 404.

        PRD: "foreign-key identifiers carried in the body are resolved in the
        order the endpoint declares its inputs, each producing the 404 for its
        own resource type: `ERR_STANDARD_NOT_FOUND`, `ERR_PROPERTY_NOT_FOUND`".

        Design: Corner/entities/create_unit_under_unknown_property_returns_not_found
        """
        response = api.create_unit(
            F.unit_payload(
                "00000000-0000-4000-8000-000000000000", "101", bedroom_count=2
            ),
            ADMIN,
        )

        assert_error(response, ApiErrorId.PROPERTY_NOT_FOUND)

    def test_second_unit_reusing_a_unit_number_is_rejected(self, api):
        """Unit numbers are unique within one property.

        PRD: "carries a `unit_number` that must be unique among the units
        sharing that `property_id` - a collision is rejected with
        `ERR_DUPLICATE_UNIT_NUMBER` (HTTP 409)".

        Design: Corner/errors/second_unit_reusing_a_unit_number_on_one_property_is_rejected
        """
        bundle = X.property_with_units(
            api,
            K.MAPLE_COURT,
            [{"unit_number": "101", "bedroom_count": 2}],
        )

        response = api.create_unit(
            F.unit_payload(
                bundle["property_id"],
                "101",
                bedroom_count=1,
                occupancy_status="VACANT",
            ),
            ADMIN,
        )

        assert_error(response, ApiErrorId.DUPLICATE_UNIT_NUMBER)
        assert_total_count(
            api.list_units(ADMIN, property_id=bundle["property_id"]), 1
        )


class TestUnitListing:
    """Unit listings page over the property's units."""

    def test_two_pages_report_the_full_count_and_do_not_repeat_a_row(self, api):
        """Three units read back as 2 + 1 with `total_count` 3 on both pages.

        PRD: "List responses carry `limit`, `offset`, `total_count` and
        `has_more` inside the `meta` object of the envelope, where `total_count`
        is the size of the full filtered result set before pagination and
        `has_more` states whether rows remain beyond the returned page."

        Design: Corner/entities/list_units_paginates_with_total_count_and_has_more
        """
        bundle = X.property_with_units(
            api,
            K.MAPLE_COURT,
            [
                {
                    "unit_number": "101",
                    "bedroom_count": 2,
                    "occupancy_status": "OCCUPIED",
                    "occupant_display_name": "Household 101",
                },
                {
                    "unit_number": "102",
                    "bedroom_count": 1,
                    "occupancy_status": "VACANT",
                },
                {
                    "unit_number": "103",
                    "bedroom_count": 3,
                    "occupancy_status": "DOWN",
                },
            ],
        )
        property_id = bundle["property_id"]

        first_page = assert_pagination_meta(
            api.list_units(ADMIN, property_id=property_id, limit=2, offset=0),
            3,
            2,
            0,
            True,
        )
        second_page = assert_pagination_meta(
            api.list_units(ADMIN, property_id=property_id, limit=2, offset=2),
            3,
            2,
            2,
            False,
        )

        assert len(first_page) == 2 and len(second_page) == 1
        seen = [row["id"] for row in first_page] + [
            row["id"] for row in second_page
        ]
        assert len(set(seen)) == 3
        assert set(seen) == set(bundle["unit_ids"].values())


class TestAmendments:
    """Both the owner and the platform operator may amend the two roots."""

    def test_patching_a_unit_to_down_updates_occupancy_and_bumps_the_version(
        self, api
    ):
        """The owner flips an occupied unit to DOWN in one amendment.

        PRD: "Either the owner or a `PlatformAdmin` may amend a unit, supplying
        any subset of `bedroom_count`, `occupancy_status` and
        `occupant_display_name`; the amendment increments the unit's `version`
        by 1."

        Design: Corner/endpoints/patch_unit_to_down_updates_occupancy_and_bumps_the_version
        """
        bundle = X.property_with_units(
            api,
            K.CEDAR_WALK,
            [
                {
                    "unit_number": "101",
                    "bedroom_count": 1,
                    "occupancy_status": "OCCUPIED",
                    "occupant_display_name": "Household 101",
                }
            ],
        )
        unit = bundle["units"]["101"]
        assert_integer(unit["version"], 1, "version")

        response = api.patch_unit(
            unit["id"],
            F.unit_patch_payload(
                occupancy_status="DOWN",
                occupant_display_name="Vacated for rehab",
            ),
            make_property_owner_headers(bundle["property_id"]),
        )

        amended = assert_ok(response)
        assert_fields(
            amended,
            version=2,
            occupancy_status="DOWN",
            occupant_display_name="Vacated for rehab",
            unit_number="101",
            bedroom_count=1,
            property_id=bundle["property_id"],
        )
        assert_integer(
            amended["prior_deficiency_count"], 0, "prior_deficiency_count"
        )
        assert_integer(
            amended["open_deficiency_count"], 0, "open_deficiency_count"
        )

        reread = assert_ok(api.get_unit(unit["id"], ADMIN))
        assert_fields(
            reread,
            version=2,
            occupancy_status="DOWN",
            occupant_display_name="Vacated for rehab",
        )

    def test_owner_and_platform_admin_share_the_property_update_operation(
        self, api
    ):
        """Two amendments by two roles land on one property, version 1 to 3.

        PRD: "Either the owner or a `PlatformAdmin` may amend a property,
        supplying any subset of `name`, `total_unit_count`,
        `capital_reserve_cents` and `owner_contact_email`; the amendment
        increments the property's `version` by 1."

        Design: Corner/rbac/property_owner_and_platform_admin_share_the_property_update_operation
        """
        row = X.create_property(api, K.CEDAR_WALK, total_unit_count=2)
        property_id = row["id"]
        assert_integer(row["version"], 1, "version")

        owner_amended = assert_ok(
            api.patch_property(
                property_id,
                F.property_patch_payload(
                    owner_contact_email="asset.manager@cedar.example"
                ),
                make_property_owner_headers(property_id),
            )
        )
        assert_integer(owner_amended["version"], 2, "version")

        response = api.patch_property(
            property_id,
            F.property_patch_payload(capital_reserve_cents=900000),
            ADMIN,
        )

        admin_amended = assert_ok(response)
        assert_fields(
            admin_amended,
            version=3,
            owner_contact_email="asset.manager@cedar.example",
            name="Cedar Walk",
            total_unit_count=2,
        )
        assert_cents(
            admin_amended["capital_reserve_cents"],
            900000,
            "capital_reserve_cents",
        )


class TestPropertyReadSurfaces:
    """The collection listing is the one property read an owner lacks."""

    def test_listing_properties_as_the_owner_is_unauthorized(self, api):
        """An owner may read its own property but not the collection.

        PRD: "Properties may be read singly by any role and listed, filtered by
        `readiness_posture`, by the four non-owner reviewing roles and the
        platform operator; the listing of all properties is the one read surface
        an owner does not hold."

        Design: Corner/rbac/listing_properties_as_property_owner_returns_unauthorized
        """
        property_id = X.create_property(api, K.CEDAR_WALK)["id"]
        owner_headers = make_property_owner_headers(property_id)

        response = api.list_properties(owner_headers, limit=10, offset=0)

        assert_error(response, ApiErrorId.UNAUTHORIZED)
        single = assert_ok(api.get_property(property_id, owner_headers))
        assert_fields(single, id=property_id)

    def test_a_read_without_an_x_user_id_header_is_unauthenticated(self, api):
        """Both a missing principal and an unknown role fail authentication.

        PRD: "If either header is absent, or if `X-User-Role` is not one of the
        six declared roles, the request is rejected with `ERR_UNAUTHENTICATED`
        (HTTP 401)."

        Design: Corner/rbac/reading_a_property_with_a_missing_x_user_id_header_is_unauthenticated
        """
        property_id = X.create_property(api, K.CEDAR_WALK)["id"]

        response = api.get_property(
            property_id, make_headers_without_user_id(ROLE_HOUSING_AGENCY_INSPECTOR)
        )

        assert_error(response, ApiErrorId.UNAUTHENTICATED)

        undeclared_role = api.get_property(
            property_id, make_headers("BuildingSuperintendent", "super-1")
        )

        assert_error(undeclared_role, ApiErrorId.UNAUTHENTICATED)
