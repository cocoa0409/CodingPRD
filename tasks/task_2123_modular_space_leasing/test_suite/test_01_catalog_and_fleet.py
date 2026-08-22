"""Standing up the network: yards, authorities, catalog models, floorplans and units."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_branch,
    assert_building_spec,
    assert_floorplan_configuration,
    assert_unit,
    create_branch,
    create_building_spec,
    create_configuration,
    create_published_configuration,
    create_unit,
    get_branch,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_fleet_admin_headers,
    make_leasing_agent_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import (
    CONFIG_OPEN_PLAN,
    SPEC_MOB_2048,
    SPEC_MOB_2460,
    create_branch_payload,
    create_floorplan_configuration_payload,
    create_jurisdiction_payload,
    create_unit_payload,
)

# Well-formed UUIDs that were never minted by the server.
GHOST_BRANCH = "11111111-1111-4111-8111-111111111111"
GHOST_UNIT = "22222222-2222-4222-8222-222222222222"
GHOST_LEASE = "33333333-3333-4333-8333-333333333333"
GHOST_CUSTOMER = "44444444-4444-4444-8444-444444444444"
GHOST_CONFIG = "55555555-5555-4555-8555-555555555555"
GHOST_SPEC = "66666666-6666-4666-8666-666666666666"
GHOST_PERMIT = "77777777-7777-4777-8777-777777777777"
GHOST_JOB = "88888888-8888-4888-8888-888888888888"
GHOST_ASSESSMENT = "99999999-9999-4999-8999-999999999999"
GHOST_REFURB = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
GHOST_PACKAGE = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


def test_registering_a_branch_returns_zeroed_fleet_counters(api):
    """PRD §3.1: "A newly registered branch begins with `units_in_yard` and
    `units_available` at 0 and `utilization_pct` at 0.00, and those three
    counters thereafter behave exactly as §2.10 describes."
    PRD §3.1: "A branch also carries an operational posture in its `status`,
    which is either `OPERATIONAL` or `SUSPENDED` and defaults to `OPERATIONAL`
    when the caller omits it."

    PRD §2.2: "- The `api_request_id` is a server-generated unique identifier for
    the request that starts with `req_`. - The `api_request_timestamp` is a
    server-generated ISO 8601 UTC timestamp with three fractional digits."

    Design: Corner/entities/create_branch_returns_201_with_zeroed_fleet_counters
    """
    response = api.create_branch(create_branch_payload(), make_fleet_admin_headers())
    branch = validate_success(response, 201)
    assert_branch(branch)

    assert branch["units_in_yard"] == 0, (
        f"Expected units_in_yard 0 on a new branch, got {branch['units_in_yard']}")
    assert branch["units_available"] == 0, (
        f"Expected units_available 0 on a new branch, got {branch['units_available']}")
    assert float(branch["utilization_pct"]) == pytest.approx(0.00, abs=0.005), (
        f"Expected utilization_pct 0.00, got {branch['utilization_pct']}")
    assert branch["status"] == "OPERATIONAL", (
        f"Expected the omitted status to default to OPERATIONAL, "
        f"got {branch['status']}")

    body = response.json()
    assert body["response_type"] == "object", (
        f"Expected response_type 'object', got {body['response_type']}")
    assert body["meta"]["api_request_id"].startswith("req_"), (
        f"api_request_id must start with req_, got {body['meta']['api_request_id']}")
    assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"]), (
        f"api_request_timestamp must be ISO 8601, "
        f"got {body['meta']['api_request_timestamp']}")


def test_building_spec_floor_area_is_width_times_length(api):
    """PRD §3.1: "On registration the system derives `floor_area_sqft` as the
    width in feet multiplied by the length in feet."
    PRD §3.1: "That product is exact and is not rounded, and the section count
    never multiplies it."

    Design: Corner/entities/building_spec_floor_area_is_computed_and_client_input_ignored
    """
    response = api.create_building_spec(dict(SPEC_MOB_2460), make_fleet_admin_headers())
    spec = validate_success(response, 201)
    assert_building_spec(spec)

    assert float(spec["floor_area_sqft"]) == pytest.approx(1440.0, abs=0.001), (
        f"Expected 24 x 60 to derive 1440 sqft, got {spec['floor_area_sqft']}")
    assert float(spec["floor_area_sqft"]) != pytest.approx(2880.0, abs=0.001), (
        "the two-section count must not multiply the floor area")
    assert spec["sections"] == 2, f"Expected sections 2, got {spec['sections']}"


def test_jurisdiction_with_an_illegal_anchoring_standard_is_rejected(api):
    """PRD §3.1: "`anchoring_standard` declares the foundation class the
    authority mandates and is one of `NONE`, `GROUND_ANCHOR`, `PIER_FOUNDATION`,
    or `ENGINEERED_SLAB`."
    PRD §2.9: "**Body shape.** Required fields present, enum members legal,
    numeric fields inside their declared ranges, dates parsing as `yyyy-mm-dd`,
    and the two conditional logistics fields supplied exactly when they are due
    — `destination_branch_id` present for a teardown-and-return job and absent
    otherwise, `new_site_address` present for a relocation job and absent
    otherwise. Failure is `ERR_INVALID_REQUEST` with HTTP 422."

    Design: Corner/entities/create_jurisdiction_with_illegal_anchoring_enum_is_rejected
    """
    payload = create_jurisdiction_payload(
        code="TX-BAD", name="Bad County", permit_required=True, permit_lead_days=10,
        anchoring_standard="HELICAL_PILE", wind_zone=2, permit_fee_cents=100_000,
        ada_ramp_required=False, min_ramp_run_ratio=12.0)
    response = api.create_jurisdiction(payload, make_fleet_admin_headers())
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)

    # Nothing was persisted: a lease may only name jurisdictions that exist, and
    # the rejected code must not be reusable evidence of a row.
    retry = api.create_jurisdiction(
        create_jurisdiction_payload(code="TX-BAD", name="Bad County",
                                    permit_required=True, permit_lead_days=10,
                                    anchoring_standard="GROUND_ANCHOR", wind_zone=2,
                                    permit_fee_cents=100_000, ada_ramp_required=False,
                                    min_ramp_run_ratio=12.0),
        make_fleet_admin_headers())
    validate_success(retry, 201)


def test_new_unit_system_fields_are_server_minted(api):
    """PRD §2.4: "- **`id`** (string): a server-minted UUID. It carries no type
    prefix and no embedded meaning; clients must treat it as opaque."
    PRD §3.3: "A `FleetAdmin` adds one by supplying its `serial_number`, the
    `building_spec_id` of the model it is, and the `current_branch_id` of the
    yard that takes custody of it; an optional `condition_grade` may be
    supplied, and when it is omitted the unit is graded `A`."
    PRD §3.3: "A newly added unit enters the fleet in status `IN_FLEET`, and the
    receiving branch's three counters are recomputed immediately."
    PRD §3.3: "A fifth system-managed field, `installed_config_id`, records
    which floorplan configuration is physically installed in the unit; it is
    null until a delivery-and-install job completes, at which point it is
    written with that lease's configuration — and it is never cleared
    afterwards, so a unit back in the yard still reports the last floorplan it
    wore."

    PRD §2.4: "- **`created_at`** (string): an ISO 8601 timestamp in UTC with
    three fractional digits, recorded when the resource was first persisted. -
    **`updated_at`** (string): an ISO 8601 UTC timestamp with three fractional
    digits, refreshed on every mutation of the resource, including mutations the
    server performs on its own initiative as a downstream consequence of an
    operation on some other resource."

    Design: Corner/entities/unit_system_fields_are_server_minted_and_untyped
    """
    branch = create_branch()
    spec = create_building_spec(**SPEC_MOB_2048)

    payload = create_unit_payload(spec["id"], branch["id"])
    payload.pop("condition_grade")
    response = api.create_unit(payload, make_fleet_admin_headers())
    unit = validate_success(response, 201)
    assert_unit(unit)

    assert is_valid_uuid(unit["id"]), (
        f"Unit.id must be a bare UUID with no type prefix, got {unit['id']!r}")
    assert unit["status"] == "IN_FLEET", (
        f"Expected a new unit to be IN_FLEET, got {unit['status']}")
    assert unit["condition_grade"] == "A", (
        f"Expected the omitted condition_grade to default to A, "
        f"got {unit['condition_grade']}")
    assert unit["installed_config_id"] is None, (
        f"Expected installed_config_id null before any delivery completes, "
        f"got {unit['installed_config_id']}")
    assert unit["latest_quote_estimate_cents"] == 0, (
        f"Expected latest_quote_estimate_cents 0, "
        f"got {unit['latest_quote_estimate_cents']}")
    assert is_iso8601_timestamp(unit["created_at"]), (
        f"created_at must be an ISO 8601 UTC timestamp, got {unit['created_at']}")
    assert is_iso8601_timestamp(unit["updated_at"]), (
        f"updated_at must be an ISO 8601 UTC timestamp, got {unit['updated_at']}")


def test_reading_a_unit_echoes_the_stored_row(api):
    """PRD §3.3: "A `FleetAdmin` adds one by supplying its `serial_number`, the
    `building_spec_id` of the model it is, and the `current_branch_id` of the
    yard that takes custody of it; an optional `condition_grade` may be
    supplied, and when it is omitted the unit is graded `A`."
    PRD §3.3: "Four cumulative counters ride along with each unit for its whole
    service life. `lifetime_relocations` counts the relocation jobs completed
    against it."
    PRD §3.3: "All four start at zero."

    Design: Corner/entities/get_unit_by_id_returns_the_stored_row
    """
    branch = create_branch()
    spec = create_building_spec(**SPEC_MOB_2048)
    created = create_unit(spec["id"], branch["id"], serial_number="MSU-2001")

    unit = validate_success(api.get_unit(created["id"], make_fleet_admin_headers()))
    assert_unit(unit)

    assert unit["serial_number"] == "MSU-2001", (
        f"Expected serial_number MSU-2001, got {unit['serial_number']}")
    assert unit["building_spec_id"] == spec["id"]
    assert unit["current_branch_id"] == branch["id"]
    assert unit["status"] == "IN_FLEET", f"Expected IN_FLEET, got {unit['status']}"
    assert unit["condition_grade"] == "A"
    assert unit["installed_config_id"] is None
    assert unit["refurb_cycles"] == 0, (
        f"Expected refurb_cycles 0, got {unit['refurb_cycles']}")
    assert unit["lifetime_relocations"] == 0, (
        f"Expected lifetime_relocations 0, got {unit['lifetime_relocations']}")


def test_listing_units_paginates_with_total_count_and_has_more(api):
    """PRD §2.3: "The `limit` parameter caps the number of records returned; it
    defaults to 10, may not be smaller than 1, and may not be larger than 100.
    The `offset` parameter is the number of records to skip and defaults to 0."
    PRD §2.3: "List responses carry `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object of the envelope, where `total_count`
    reflects the size of the filtered set before pagination is applied."
    PRD §2.10: "`units_available` is the number of units whose
    `current_branch_id` is this branch and whose status is exactly `IN_FLEET`."

    PRD §2.2: "- The `response_type` is either "object" for a single resource or
    "array" for a list of resources."

    Design: Corner/entities/list_units_paginates_with_total_count_and_has_more
    """
    branch = create_branch()
    spec = create_building_spec(**SPEC_MOB_2048)
    for i in range(3):
        create_unit(spec["id"], branch["id"], serial_number=f"MSU-200{i + 1}")

    first_response = api.list_units(
        make_fleet_admin_headers(),
        params={"current_branch_id": branch["id"], "limit": 2, "offset": 0})
    first_page, first_meta = validate_paginated(first_response)
    assert first_response.json()["response_type"] == "array", (
        "a list endpoint must answer with response_type 'array'")
    assert len(first_page) == 2, f"Expected 2 rows on page one, got {len(first_page)}"
    assert first_meta["total_count"] == 3, (
        f"Expected total_count 3, got {first_meta['total_count']}")
    assert first_meta["limit"] == 2 and first_meta["offset"] == 0
    assert first_meta["has_more"] is True, "page one of three rows must report has_more"

    second_page, second_meta = validate_paginated(api.list_units(
        make_fleet_admin_headers(),
        params={"current_branch_id": branch["id"], "limit": 2, "offset": 2}))
    assert len(second_page) == 1, (
        f"Expected 1 row on page two, got {len(second_page)}")
    assert second_meta["total_count"] == 3
    assert second_meta["offset"] == 2
    assert second_meta["has_more"] is False, (
        "the last page must report has_more false")

    yard = get_branch(branch["id"])
    assert yard["units_in_yard"] == 3, (
        f"Expected units_in_yard 3, got {yard['units_in_yard']}")
    assert yard["units_available"] == 3, (
        f"Expected units_available 3, got {yard['units_available']}")


def test_listing_units_above_the_maximum_limit_is_rejected(api):
    """PRD §2.3: "The `limit` parameter caps the number of records returned; it
    defaults to 10, may not be smaller than 1, and may not be larger than 100.
    The `offset` parameter is the number of records to skip and defaults to 0."
    PRD §2.9: "**Body shape.** Required fields present, enum members legal,
    numeric fields inside their declared ranges, dates parsing as `yyyy-mm-dd`,
    and the two conditional logistics fields supplied exactly when they are due
    — `destination_branch_id` present for a teardown-and-return job and absent
    otherwise, `new_site_address` present for a relocation job and absent
    otherwise. Failure is `ERR_INVALID_REQUEST` with HTTP 422."

    Design: Corner/endpoints/list_units_with_limit_above_the_maximum_is_rejected
    """
    branch = create_branch()
    spec = create_building_spec(**SPEC_MOB_2048)
    create_unit(spec["id"], branch["id"], serial_number="MSU-2001")

    too_big = api.list_units(make_fleet_admin_headers(), params={"limit": 500})
    validate_error(too_big, ApiErrorId.ERR_INVALID_REQUEST.value)

    at_cap, meta = validate_paginated(
        api.list_units(make_fleet_admin_headers(), params={"limit": 100}))
    assert meta["limit"] == 100, f"Expected limit 100, got {meta['limit']}"
    assert meta["offset"] == 0, f"Expected offset 0, got {meta['offset']}"
    assert meta["total_count"] == 1, (
        f"Expected total_count 1, got {meta['total_count']}")
    assert meta["has_more"] is False
    assert len(at_cap) == 1

    _, default_meta = validate_paginated(api.list_units(make_fleet_admin_headers()))
    assert default_meta["limit"] == 10, (
        f"Expected the omitted limit to default to 10, got {default_meta['limit']}")


def test_unknown_ids_report_the_missing_entity_type(api):
    """PRD §2.7: "Identifiers named in a URL path are resolved strictly from
    left to right, and the first one that does not resolve decides the
    response."
    PRD §2.7: "Each entity type has its own dedicated 404:
    `ERR_BRANCH_NOT_FOUND`, `ERR_JURISDICTION_NOT_FOUND`,
    `ERR_BUILDING_SPEC_NOT_FOUND`, `ERR_CONFIG_NOT_FOUND`, `ERR_UNIT_NOT_FOUND`,
    `ERR_CUSTOMER_NOT_FOUND`, `ERR_LEASE_NOT_FOUND`,
    `ERR_ACCESSORY_PACKAGE_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`,
    `ERR_LOGISTICS_JOB_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`, and
    `ERR_REFURB_ORDER_NOT_FOUND`."
    PRD §2.7: "Foreign keys supplied in a request body are resolved after path
    identifiers, and they are resolved **in the order the fields are declared
    for that operation** — the first unresolvable reference decides the
    response."

    Design: Corner/entities/unknown_ids_return_entity_specific_not_found_errors
    """
    branch = create_branch()
    spec = create_building_spec(**SPEC_MOB_2048)

    admin = make_fleet_admin_headers()
    agent = make_leasing_agent_headers()

    validate_error(api.get_branch(GHOST_BRANCH, admin),
                   ApiErrorId.ERR_BRANCH_NOT_FOUND.value)
    validate_error(api.get_unit(GHOST_UNIT, admin),
                   ApiErrorId.ERR_UNIT_NOT_FOUND.value)
    validate_error(api.get_lease(GHOST_LEASE, agent),
                   ApiErrorId.ERR_LEASE_NOT_FOUND.value)
    validate_error(api.get_customer(GHOST_CUSTOMER, agent),
                   ApiErrorId.ERR_CUSTOMER_NOT_FOUND.value)
    validate_error(api.get_floorplan_configuration(GHOST_CONFIG, admin),
                   ApiErrorId.ERR_CONFIG_NOT_FOUND.value)
    validate_error(api.get_building_spec(GHOST_SPEC, admin),
                   ApiErrorId.ERR_BUILDING_SPEC_NOT_FOUND.value)
    validate_error(api.get_permit_application(GHOST_PERMIT, agent),
                   ApiErrorId.ERR_PERMIT_NOT_FOUND.value)
    validate_error(api.get_logistics_job(GHOST_JOB, admin),
                   ApiErrorId.ERR_LOGISTICS_JOB_NOT_FOUND.value)
    validate_error(api.get_damage_assessment(GHOST_ASSESSMENT, admin),
                   ApiErrorId.ERR_ASSESSMENT_NOT_FOUND.value)
    validate_error(api.get_refurbishment_order(GHOST_REFURB, admin),
                   ApiErrorId.ERR_REFURB_ORDER_NOT_FOUND.value)
    validate_error(api.get_accessory_package(GHOST_PACKAGE, agent),
                   ApiErrorId.ERR_ACCESSORY_PACKAGE_NOT_FOUND.value)

    # Body foreign keys carry the same entity-specific codes.
    validate_error(
        api.create_floorplan_configuration(
            create_floorplan_configuration_payload(
                GHOST_SPEC, name="Ghost Plan", private_offices=1, restrooms=1,
                partition_linear_ft=10, hvac_tons=1.0),
            admin),
        ApiErrorId.ERR_BUILDING_SPEC_NOT_FOUND.value)
    validate_error(
        api.create_unit(
            create_unit_payload(spec["id"], GHOST_BRANCH, serial_number="MSU-9999"),
            admin),
        ApiErrorId.ERR_BRANCH_NOT_FOUND.value)

    # Neither rejected create persisted a row.
    _, config_meta = validate_paginated(
        api.list_floorplan_configurations(admin))
    assert config_meta["total_count"] == 0, (
        f"Expected no configuration rows, got {config_meta['total_count']}")
    _, unit_meta = validate_paginated(
        api.list_units(admin, params={"current_branch_id": branch["id"]}))
    assert unit_meta["total_count"] == 0, (
        f"Expected no unit rows, got {unit_meta['total_count']}")


def test_duplicate_unit_serial_number_is_rejected(api):
    """PRD §3.1: "Three identifiers in this catalog are enforced as unique, and
    an attempt to reuse any of them is rejected with `ERR_DUPLICATE_IDENTIFIER`:
    a building spec's `model_code`, a jurisdiction's `code`, and a unit's
    `serial_number`."

    Design: Corner/validations/duplicate_unit_serial_number_is_rejected
    """
    branch = create_branch()
    spec = create_building_spec(**SPEC_MOB_2048)
    create_unit(spec["id"], branch["id"], serial_number="MSU-2001")

    duplicate = api.create_unit(
        create_unit_payload(spec["id"], branch["id"], serial_number="MSU-2001"),
        make_fleet_admin_headers())
    validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_IDENTIFIER.value)

    yard = get_branch(branch["id"])
    assert yard["units_in_yard"] == 1, (
        f"the rejected duplicate must not add to the yard: got "
        f"{yard['units_in_yard']}")
    _, meta = validate_paginated(api.list_units(
        make_fleet_admin_headers(), params={"current_branch_id": branch["id"]}))
    assert meta["total_count"] == 1, (
        f"Expected exactly 1 unit at the branch, got {meta['total_count']}")


def test_publishing_a_configuration_moves_it_out_of_draft(api):
    """PRD §3.2: "A configuration is born in `DRAFT`, recorded in its `status`,
    and only a `PUBLISHED` configuration may be named by a new lease."
    PRD §3.2: "Publishing is a `FleetAdmin` act that moves the configuration
    `DRAFT → PUBLISHED`; attempting it on a configuration that is already
    `PUBLISHED` is rejected with `ERR_INVALID_STATE`."
    PRD §3.2: "The office component charges $420.00 for each private office."

    PRD §3.2: "The restroom component charges $1,750.00 for each restroom."
    PRD §3.2: "The partition component charges $95.00 for each four-foot segment
    of partition wall, where the segment count is the partition length in feet
    divided by four and then rounded up to a whole number — a 13-foot partition
    is therefore charged as four segments."
    PRD §3.2: "The HVAC component is the interesting one, because a certain
    amount of tonnage comes free with the building: the included tonnage is half
    a ton for every complete 400 square feet of the spec's floor area, computed
    by dividing the floor area by 400, rounding that quotient **down** to a
    whole number, and halving the result."
    PRD §3.2: "The excess is then charged at $680.00 for each half ton, where
    the number of chargeable half-tons is the excess tonnage divided by one half
    and rounded up to a whole number."

    Design: Corner/state_machines/publish_moves_configuration_draft_to_published
    """
    spec = create_building_spec(**SPEC_MOB_2048)
    draft = create_configuration(spec["id"], **CONFIG_OPEN_PLAN)
    assert_floorplan_configuration(draft)
    assert draft["status"] == "DRAFT", (
        f"Expected a new configuration to be DRAFT, got {draft['status']}")
    assert draft["config_surcharge_cents"] == 452_000, (
        f"Expected config_surcharge_cents 452000, "
        f"got {draft['config_surcharge_cents']}")

    published = validate_success(
        api.publish_floorplan_configuration(draft["id"], make_fleet_admin_headers()))
    assert published["status"] == "PUBLISHED", (
        f"Expected PUBLISHED after publish, got {published['status']}")
    assert published["config_surcharge_cents"] == 452_000, (
        "publishing must not re-price the build-out surcharge")
    assert published["version"] > draft["version"], (
        f"publishing is a mutation, so version must advance from "
        f"{draft['version']}, got {published['version']}")


def test_publishing_an_already_published_configuration_is_rejected(api):
    """PRD §3.2: "Publishing is a `FleetAdmin` act that moves the configuration
    `DRAFT → PUBLISHED`; attempting it on a configuration that is already
    `PUBLISHED` is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/publish_an_already_published_configuration_is_rejected
    """
    spec = create_building_spec(**SPEC_MOB_2048)
    published = create_published_configuration(spec["id"], **CONFIG_OPEN_PLAN)
    version_before = published["version"]

    second = api.publish_floorplan_configuration(
        published["id"], make_fleet_admin_headers())
    validate_error(second, ApiErrorId.ERR_INVALID_STATE.value)

    after = validate_success(api.get_floorplan_configuration(
        published["id"], make_fleet_admin_headers()))
    assert after["status"] == "PUBLISHED"
    assert after["version"] == version_before, (
        f"the rejected publish wrote nothing, so version must stay "
        f"{version_before}, got {after['version']}")
