"""Entity-surface breadth: creation envelopes, retrieval, listing, defaults,
computed-field protection, system-field protection, type constraints,
append-only rows, parent references and the zone graph's depth cap."""

from test_helpers import (
    ApiErrorId,
    COORDINATOR,
    get_success_data,
    is_valid_uuid,
    validate_error,
    validate_paginated,
)
from test_helpers import factories as f
from test_helpers.assertions import (
    assert_append_only_record,
    assert_envelope_meta,
    assert_instant_equals,
)
from test_helpers.constants import (
    AssessmentStatus,
    HouseholdStatus,
    PriorityBand,
    ZoneKind,
)
from test_helpers.fixtures import (
    create_assessed_zone,
    create_household,
    create_zone,
    pin_clock,
    read_household,
    read_zone,
)
from test_helpers.test_users import ANALYST

SUPPLIED_UUID = "11111111-1111-4111-8111-111111111111"
UNKNOWN_UUID = "00000000-0000-4000-8000-000000000000"


def test_01_zone_create_returns_the_full_envelope_and_initial_derived_fields(api):
    """A zone created with all eleven inputs starts unassessed, unscored and unserved.

    PRD: "A newly created zone starts with `assessment_status` at `UNASSESSED`,
    `zone_kind` at `LEAF`, and `risk_score`, `risk_tier`, `assessment_basis`,
    `current_assessment_id` and `service_start_date` all null. Its four field-derived
    counters start at zero: `surveyed_units`, `surveyed_units_without_alarm`,
    `post_service_alarm_loss_units` and `served_household_count`."

    Design: Corner/entities/zone_create_returns_full_envelope_and_initial_derived_fields
    """
    pin_clock(api)

    response = api.create_zone(f.zone_payload(zone_code="Z-NEW", name="New Leaf"), ANALYST)
    body = assert_envelope_meta(response)
    assert response.status_code == 201
    assert body["response_type"] == "object"

    zone = body["data"]
    assert "error_id" not in zone and "message" not in zone
    assert is_valid_uuid(zone["id"])
    assert zone["zone_kind"] == ZoneKind.LEAF
    assert zone["assessment_status"] == AssessmentStatus.UNASSESSED
    assert zone["risk_score"] is None
    assert zone["risk_tier"] is None
    assert zone["parent_zone_id"] is None
    assert zone["surveyed_units"] == 0
    assert zone["surveyed_units_without_alarm"] == 0
    assert zone["post_service_alarm_loss_units"] == 0
    assert zone["served_household_count"] == 0
    assert zone["version"] == 1
    assert_instant_equals(zone["created_at"], "2026-08-01T00:00:00Z", "created_at")


def test_02_household_read_echoes_the_stored_row_and_its_computed_counts(api):
    """Two sleeping areas over two storeys need four smoke devices; a hearing-impaired
    occupant makes a strobe mandatory and a fuel-burning appliance one CO alarm.

    PRD: "`required_smoke_devices` is the number of sleeping areas added to the number
    of storeys... `required_co_devices` is 1 when either `fuel_burning_appliance` or
    `attached_garage` is true... `required_strobe_devices` is 1 when
    `hearing_impaired_occupants` is greater than 0".

    Design: Corner/entities/household_get_by_id_returns_the_stored_row
    """
    pin_clock(api)
    zone = create_assessed_zone(api)
    created = create_household(
        api,
        zone["id"],
        address_line="9 Birch Road",
        occupant_count=3,
        sleeping_areas_count=2,
        storeys=2,
        hearing_impaired_occupants=1,
        fuel_burning_appliance=True,
    )

    response = api.get_household(created["id"], COORDINATOR)
    assert response.status_code == 200
    household = get_success_data(response, 200)

    assert household["id"] == created["id"]
    assert household["zone_id"] == zone["id"]
    assert household["address_line"] == "9 Birch Road"
    assert household["occupant_count"] == 3
    assert household["required_smoke_devices"] == 4
    assert household["required_co_devices"] == 1
    assert household["required_strobe_devices"] == 1
    assert household["status"] == HouseholdStatus.INTAKE_QUEUED
    # A vulnerable household in a TIER_2 zone is banded P2_ELEVATED.
    assert household["priority_band"] == PriorityBand.P2_ELEVATED


def test_03_households_list_is_paginated_and_filterable_by_zone(api):
    """Three households at limit 2 page as 2 + 1 with a stable total_count.

    PRD: "the `meta` object carries `limit` (the effective page size applied),
    `offset` (the effective starting position applied), `total_count` (the number of
    rows matching the filters before pagination), and `has_more` (true when rows
    remain beyond the current page)."

    Design: Corner/entities/households_list_is_paginated_and_filterable_by_zone
    """
    pin_clock(api)
    zone = create_assessed_zone(api)
    for address in ("1 Birch Road", "2 Birch Road", "3 Birch Road"):
        create_household(api, zone["id"], address_line=address)

    first_page, first_meta = validate_paginated(
        api.list_households(COORDINATOR, params={"zone_id": zone["id"], "limit": 2, "offset": 0})
    )
    assert len(first_page) == 2
    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True

    second_page, second_meta = validate_paginated(
        api.list_households(COORDINATOR, params={"zone_id": zone["id"], "limit": 2, "offset": 2})
    )
    assert len(second_page) == 1
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False

    for row in first_page + second_page:
        assert row["zone_id"] == zone["id"]


def test_04_visit_read_with_an_unknown_id_is_a_not_found(api):
    """A syntactically valid but unknown visit id is a 404, never an empty 200.

    PRD: "Existence of every identifier in the URL path, validated strictly left to
    right, with HTTP 404 and the code naming the first missing level:
    `ERR_ZONE_NOT_FOUND`, `ERR_HOUSEHOLD_NOT_FOUND`, `ERR_ROUTE_NOT_FOUND`,
    `ERR_VISIT_NOT_FOUND`..."

    Design: Corner/entities/visit_get_with_unknown_id_returns_not_found
    """
    pin_clock(api)

    response = api.get_visit(UNKNOWN_UUID, COORDINATOR)
    error = validate_error(response, ApiErrorId.VISIT_NOT_FOUND, 404)
    assert response.json()["response_type"] == "error"
    assert isinstance(error["message"], str) and error["message"]


def test_05_household_create_without_sleeping_areas_count_is_invalid(api):
    """The device requirement cannot be derived without the sleeping-area count.

    PRD: "Request-schema validity - every required body field present, every value of
    the declared JSON type, every enum value a declared member, every numeric
    constraint from §3 satisfied... - `ERR_INVALID_REQUEST` (400), on every endpoint."

    Design: Corner/entities/household_create_without_sleeping_areas_count_returns_invalid_request
    """
    pin_clock(api)
    zone = create_assessed_zone(api)

    payload = f.household_payload(
        zone["id"], address_line="4 Birch Road", sleeping_areas_count=...
    )
    assert "sleeping_areas_count" not in payload
    validate_error(
        api.create_household(payload, COORDINATOR), ApiErrorId.INVALID_REQUEST, 400
    )

    _, meta = validate_paginated(api.list_households(COORDINATOR, params={"zone_id": zone["id"]}))
    assert meta["total_count"] == 0


def test_06_household_create_defaults_every_optional_occupant_count_to_zero(api):
    """With no vulnerability inputs the four counts default to 0 and both flags to false.

    PRD: "Four occupant-composition counts are optional and each default to 0, and none
    may be negative: `children_under5`, `adults_65plus`, `mobility_impaired_occupants`
    and `hearing_impaired_occupants`. Two optional booleans default to false:
    `fuel_burning_appliance` and `attached_garage`."

    Design: Corner/entities/household_create_omitting_optional_occupant_counts_defaults_them_to_zero
    """
    pin_clock(api)
    zone = create_assessed_zone(api)

    household = create_household(
        api,
        zone["id"],
        address_line="5 Birch Road",
        occupant_count=2,
        sleeping_areas_count=1,
        storeys=1,
    )

    assert household["children_under5"] == 0
    assert household["adults_65plus"] == 0
    assert household["mobility_impaired_occupants"] == 0
    assert household["hearing_impaired_occupants"] == 0
    assert household["fuel_burning_appliance"] is False
    assert household["attached_garage"] is False
    assert household["required_smoke_devices"] == 2
    assert household["required_co_devices"] == 0
    assert household["required_strobe_devices"] == 0
    # Not vulnerable, and the zone is TIER_2, so the band falls through to P3.
    assert household["priority_band"] == PriorityBand.P3_STANDARD
    assert household["canvass_attempt_count"] == 0
    assert household["alarm_retention_flag"] is None


def test_07_household_create_ignores_client_supplied_computed_fields(api):
    """A body that dictates required_smoke_devices 99 does not win over the formula.

    PRD: "Intake immediately derives the household's **device requirements** from its
    physical shape. `required_smoke_devices` is the number of sleeping areas added to
    the number of storeys - a two-storey home with three sleeping areas needs five
    smoke devices."

    Design: Corner/entities/household_create_computed_counts_ignore_extra_field_in_body
    """
    pin_clock(api)
    zone = create_assessed_zone(api)

    payload = f.household_payload(
        zone["id"],
        address_line="6 Birch Road",
        occupant_count=2,
        sleeping_areas_count=1,
        storeys=2,
        required_smoke_devices=99,
        priority_band=PriorityBand.P1_HIGH_RISK,
    )
    created = get_success_data(api.create_household(payload, COORDINATOR), 201)

    household = read_household(api, created["id"])
    assert household["required_smoke_devices"] == 3
    assert household["storeys"] == 2
    # The band is computed from the zone's own tier, not taken from the body.
    assert household["priority_band"] == PriorityBand.P3_STANDARD


def test_08_zone_create_ignores_client_supplied_system_fields(api):
    """The server mints the id, stamps created_at from the logical clock and starts
    the version at 1 regardless of what the body says.

    PRD: "**`id`** (string): a server-minted UUID... **`created_at`** (string): an ISO
    8601 UTC timestamp with exactly three fractional-second digits... It is taken from
    the logical clock... **`version`** (integer): a monotonically increasing counter
    that starts at 1 on creation".

    Design: Corner/entities/zone_create_system_fields_input_ignored
    """
    pin_clock(api)

    payload = f.zone_payload(
        zone_code="Z-SYS",
        name="System Fields Leaf",
        id=SUPPLIED_UUID,
        created_at="2020-01-01T00:00:00Z",
        version=42,
    )
    zone = get_success_data(api.create_zone(payload, ANALYST), 201)

    assert zone["id"] != SUPPLIED_UUID
    assert is_valid_uuid(zone["id"])
    assert_instant_equals(zone["created_at"], "2026-08-01T00:00:00Z", "created_at")
    assert_instant_equals(zone["updated_at"], "2026-08-01T00:00:00Z", "updated_at")
    assert zone["version"] == 1


def test_09_zone_create_with_a_percentage_above_one_hundred_is_rejected(api):
    """120.5 is outside the declared 0.0-100.0 range, so no zone is written at all.

    PRD: "...and five percentages that must each fall between 0.0 and 100.0 inclusive -
    `pre_1980_unit_pct` for the share of units built before 1980..."

    Design: Corner/entities/zone_create_with_percentage_above_one_hundred_rejected
    """
    pin_clock(api)

    validate_error(
        api.create_zone(
            f.zone_payload(zone_code="Z-BAD", name="Bad Pct Leaf", pre_1980_unit_pct=120.5),
            ANALYST,
        ),
        ApiErrorId.INVALID_REQUEST,
        400,
    )

    _, meta = validate_paginated(api.list_zones(ANALYST))
    assert meta["total_count"] == 0


def test_10_fire_incident_rows_are_append_only(api):
    """A recorded incident carries id and created_at but neither version nor updated_at.

    PRD: "Three record types are **append-only** and are declared with only `id` and
    `created_at`; they have neither an `updated_at` field nor a `version` field, and
    they have no update endpoint. Those three are the zone assessment, the follow-up
    contact and the fire incident."

    Design: Corner/entities/fire_incident_row_is_immutable_and_carries_no_version
    """
    pin_clock(api)
    zone = create_assessed_zone(api)

    response = api.create_fire_incident(
        zone["id"],
        f.fire_incident_payload(
            incident_number="INC-2026-0001",
            occurred_at="2026-05-01T03:20:00Z",
            working_alarm_present=False,
            injuries=2,
        ),
        ANALYST,
    )
    incident = get_success_data(response, 201)
    assert response.status_code == 201

    assert incident["zone_id"] == zone["id"]
    assert_instant_equals(incident["occurred_at"], "2026-05-01T03:20:00Z", "occurred_at")
    assert incident["injuries"] == 2
    assert incident["fatalities"] == 0
    assert_append_only_record(incident)

    rows, meta = validate_paginated(api.list_fire_incidents(zone["id"], ANALYST))
    assert meta["total_count"] == 1
    assert len(rows) == 1


def test_11_household_create_under_an_unknown_zone_is_a_zone_not_found(api):
    """A body zone_id matching no zone is a body-reference 404, not a schema 400.

    PRD: "Existence of every identifier referenced from the request **body**, with HTTP
    404 and one of `ERR_ZONE_NOT_FOUND`, `ERR_HOUSEHOLD_NOT_FOUND`,
    `ERR_ROUTE_NOT_FOUND`, `ERR_CREW_NOT_FOUND`, `ERR_LOT_NOT_FOUND`,
    `ERR_PARTNER_NOT_FOUND` or `ERR_GRANT_NOT_FOUND`."

    Design: Corner/entities/household_create_under_unknown_zone_returns_zone_not_found
    """
    pin_clock(api)

    validate_error(
        api.create_household(
            f.household_payload(UNKNOWN_UUID, address_line="7 Birch Road"), COORDINATOR
        ),
        ApiErrorId.ZONE_NOT_FOUND,
        404,
    )


def test_12_zone_create_under_a_child_zone_exceeds_the_nesting_depth(api):
    """A grandchild is refused, so the tree stays exactly one level deep.

    PRD: "The tree is exactly one level deep. A supplied `parent_zone_id` must
    reference an existing zone whose own `parent_zone_id` is null, and it must not
    reference the zone being created; a reference to a zone that already has a parent,
    or a self-reference, is rejected with `ERR_ZONE_NESTING_DEPTH` (HTTP 422)."

    Design: Corner/entities/zone_create_under_a_child_zone_rejected_for_nesting_depth
    """
    pin_clock(api)
    district = get_success_data(api.create_zone(f.district_payload(), ANALYST), 201)
    child = create_zone(api, parent_zone_id=district["id"])

    validate_error(
        api.create_zone(
            f.zone_payload(
                zone_code="Z-GRAND",
                name="Grandchild Leaf",
                occupied_units=500,
                structure_fire_count_5yr=2,
                fire_injury_count_5yr=0,
                pre_1980_unit_pct=10.0,
                senior_household_pct=5.0,
                under5_household_pct=2.0,
                disability_household_pct=1.0,
                assumed_alarm_absence_pct=20.0,
                daily_visit_cap=2,
                parent_zone_id=child["id"],
            ),
            ANALYST,
        ),
        ApiErrorId.ZONE_NESTING_DEPTH,
        422,
    )

    assert read_zone(api, district["id"])["zone_kind"] == ZoneKind.DISTRICT
    assert read_zone(api, child["id"])["zone_kind"] == ZoneKind.LEAF
