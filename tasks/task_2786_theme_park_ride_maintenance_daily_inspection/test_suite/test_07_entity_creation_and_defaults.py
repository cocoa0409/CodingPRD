"""Registration shapes: declared defaults, ignored inputs and rejected shapes.

These cases pin what a create returns before any workflow has touched the row:
which fields the server authors for itself, which optional inputs have declared
defaults, and which malformed bodies are refused outright.
"""

from test_helpers import (
    ADMIN,
    INSPECTOR,
    MANAGER,
    TECHNICIAN,
    api_client,
    assert_attraction,
    assert_checklist_item,
    assert_component,
    assert_component_install_baseline,
    assert_fresh_attraction_baseline,
    assert_part_requisition,
    assert_work_order,
    factories,
    fixtures,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK_START = "2026-08-01T00:00:00.000Z"
UNKNOWN_ID = "00000000-0000-4000-8000-000000000000"


def test_registering_an_attraction_returns_every_declared_field_and_default():
    """A single create carries the supplied inputs and the whole derived baseline.

    PRD §3.1: "A `ParkOpsAdmin` registers an attraction into the maintenance system
    of record by supplying its public `name`, the `park_area` it sits in — one of
    `FRONTIER`, `LAGOON`, `SKYLINE` or `KIDS_COVE` — the `manufacturer` that built
    it, the manufacturer's `model_code`, and its thrill classification `ride_class`,
    which is one of `KIDDIE`, `FAMILY`, `THRILL` or `WATER`."
    PRD §3.1: "`operational_posture` initialises to `CLOSED_PENDING_INSPECTION`;
    `cumulative_cycles`, `parts_budget_committed_cents`, `ytd_downtime_minutes` and
    `certified_operator_count` all initialise to 0; `regulatory_hold` initialises to
    false; and `active_template_id` and `last_signed_off_service_date` both begin as
    null."

    Design: Corner/entities/attraction_create_returns_201_with_all_declared_fields_and_system_defaults
    """
    response = api_client.create_attraction(
        factories.create_attraction_payload(
            name="Thunder Ridge",
            park_area="FRONTIER",
            manufacturer="Vekoma",
            model_code="SLC-689",
            ride_class="THRILL",
            theoretical_hourly_capacity=1100,
            min_operators_required=3,
            parts_budget_cents=5000000,
            mean_repair_minutes=75,
        ),
        ADMIN,
    )
    attraction = validate_success(response, 201)
    assert_attraction(attraction)

    assert attraction["name"] == "Thunder Ridge"
    assert attraction["park_area"] == "FRONTIER"
    assert attraction["ride_class"] == "THRILL"
    assert attraction["manufacturer"] == "Vekoma"
    assert attraction["model_code"] == "SLC-689"
    assert attraction["theoretical_hourly_capacity"] == 1100
    assert attraction["min_operators_required"] == 3
    assert attraction["parts_budget_cents"] == 5000000
    assert attraction["mean_repair_minutes"] == 75

    assert_fresh_attraction_baseline(attraction)


def test_omitted_optional_inputs_take_their_declared_defaults():
    """Three optional inputs across three entities each fall back to a fixed default.

    PRD §3.1: "A fourth number, `mean_repair_minutes`, is optional and represents the
    historical mean repair duration in whole minutes; when it is omitted it defaults
    to 120, and when supplied it must be at least 1."
    PRD §3.1: "an optional documentation flag `requires_photo`, which defaults to
    false when omitted and is carried onto the result row without being enforced by
    the API."
    PRD §3.9: "an optional `expedite_requested` flag which defaults to false."

    Design: Corner/entities/attraction_and_child_defaults_are_applied_when_optional_inputs_omitted
    """
    created = validate_success(
        api_client.create_attraction(
            {
                "name": "Lagoon Racer",
                "park_area": "LAGOON",
                "manufacturer": "Mack",
                "model_code": "PW-12",
                "ride_class": "FAMILY",
                "theoretical_hourly_capacity": 900,
                "min_operators_required": 2,
                "parts_budget_cents": 9000000,
            },
            ADMIN,
        ),
        201,
    )
    attraction = fixtures.read_attraction(created["id"])
    assert attraction["mean_repair_minutes"] == 120

    component = fixtures.create_component(
        attraction["id"],
        name="Main Gearbox",
        component_type="GEARBOX",
        criticality="ESSENTIAL",
        ndt_interval_cycles=500000,
        ndt_interval_days=3650,
    )
    template = fixtures.create_template(attraction["id"], effective_from_date="2026-08-01")

    item = validate_success(
        api_client.append_checklist_item(
            template["id"],
            {
                "sequence_no": 1,
                "description": "Verify gearbox oil level",
                "severity_class": "ADVISORY",
            },
            ADMIN,
        ),
        201,
    )
    assert_checklist_item(item)
    assert item["requires_photo"] is False
    assert item["component_id"] is None

    shop_bay = fixtures.create_shop_bay("Bay Alpha", 1)
    work_order = validate_success(
        api_client.create_overhaul_work_order(
            {
                "attraction_id": attraction["id"],
                "component_id": component["id"],
                "shop_bay_id": shop_bay["id"],
                "expected_shop_bay_version": shop_bay["version"],
                "window_start_date": "2026-09-10",
                "window_end_date": "2026-09-12",
                "parts_subtotal_cents": 1000000,
                "labor_hours": 40,
            },
            MANAGER,
        ),
        201,
    )
    assert_work_order(work_order)
    assert work_order["expedite_requested"] is False
    assert work_order["expedite_fee_cents"] == 0
    assert work_order["off_season"] is False
    assert work_order["base_total_cents"] == 1380000
    assert work_order["off_season_discount_cents"] == 0
    assert work_order["discounted_base_cents"] == 1380000
    assert work_order["estimated_total_cents"] == 1380000


def test_client_supplied_identity_fields_are_discarded():
    """The server mints its own identity block and ignores the one the client sent.

    PRD §2.5: "Every resource this service persists carries an `id`, which is a
    server-minted UUID with no type prefix of any kind, and a `created_at`, which is
    the ISO 8601 UTC instant the row was created."
    PRD §2.5: "`version`, an integer that starts at 1 when the row is created and
    increments by exactly one on every mutation of that row."

    Design: Corner/entities/attraction_create_with_client_supplied_system_fields_input_ignored
    """
    attraction = validate_success(
        api_client.create_attraction(
            factories.create_attraction_payload(
                name="Skyline Drop",
                park_area="SKYLINE",
                manufacturer="Intamin",
                model_code="GD-40",
                ride_class="THRILL",
                theoretical_hourly_capacity=800,
                min_operators_required=3,
                parts_budget_cents=4000000,
                id=UNKNOWN_ID,
                created_at="2001-01-01T00:00:00.000Z",
                updated_at="2001-01-01T00:00:00.000Z",
                version=77,
                cumulative_cycles=999999,
            ),
            ADMIN,
        ),
        201,
    )
    assert is_valid_uuid(attraction["id"])
    assert attraction["id"] != UNKNOWN_ID
    assert attraction["version"] == 1
    assert attraction["cumulative_cycles"] == 0
    assert attraction["created_at"] != "2001-01-01T00:00:00.000Z"
    assert attraction["updated_at"] != "2001-01-01T00:00:00.000Z"

    stale = api_client.get_attraction(UNKNOWN_ID, ADMIN)
    validate_error(stale, "ERR_ATTRACTION_NOT_FOUND", 404)


def test_client_supplied_computed_fields_are_rederived():
    """Derived state is authored by the workflows that own it, never by the caller.

    PRD §3.1: "None of those fields is ever writable by a caller — each is either an
    aggregate over child rows or a stamp the server sets during a workflow."
    PRD §2.8: "`CLOSED_PENDING_INSPECTION` — if the attraction's
    `last_signed_off_service_date` is not the same as the logical clock's current UTC
    date."

    Design: Corner/entities/attraction_create_with_client_supplied_computed_fields_input_ignored
    """
    attraction = validate_success(
        api_client.create_attraction(
            factories.create_attraction_payload(
                name="Kids Cove Carousel",
                park_area="KIDS_COVE",
                manufacturer="Chance",
                model_code="CAR-2",
                ride_class="KIDDIE",
                theoretical_hourly_capacity=600,
                min_operators_required=1,
                parts_budget_cents=1000000,
                operational_posture="OPEN",
                regulatory_hold=True,
                parts_budget_committed_cents=123456,
                certified_operator_count=9,
                ytd_downtime_minutes=500,
            ),
            ADMIN,
        ),
        201,
    )
    assert attraction["operational_posture"] == "CLOSED_PENDING_INSPECTION"
    assert attraction["regulatory_hold"] is False
    assert attraction["parts_budget_committed_cents"] == 0
    assert attraction["certified_operator_count"] == 0
    assert attraction["ytd_downtime_minutes"] == 0


def test_a_freshly_installed_component_reads_back_its_testing_baseline():
    """Installation seeds the testing baselines, and the read reports them intact.

    PRD §3.1: "Installation seeds the testing baselines rather than leaving them
    empty: `last_ndt_at` is set to the current logical clock instant,
    `last_ndt_cycles` is set to the attraction's `cumulative_cycles` as observed at
    that moment, `ndt_status` starts at `CURRENT`, `condition_flag` starts at `OK`,
    and `last_ndt_method` starts as null because no test has been run yet."
    PRD §2.4: "At process start the logical clock reads exactly
    `2026-08-01T00:00:00Z`, and it never falls back to real time."

    Design: Corner/entities/component_retrieval_returns_stored_row_with_initialised_ndt_baselines
    """
    attraction = fixtures.create_attraction(
        name="Frontier Flyer",
        park_area="FRONTIER",
        manufacturer="Zierer",
        model_code="FL-8",
        ride_class="FAMILY",
        theoretical_hourly_capacity=700,
        min_operators_required=2,
        parts_budget_cents=3000000,
    )
    created = fixtures.create_component(
        attraction["id"],
        name="Left Brake Caliper",
        component_type="BRAKE",
        criticality="SAFETY_CRITICAL",
        ndt_interval_cycles=40000,
        ndt_interval_days=180,
    )

    component = validate_success(api_client.get_component(created["id"], INSPECTOR))
    assert_component(component)

    assert component["attraction_id"] == attraction["id"]
    assert component["name"] == "Left Brake Caliper"
    assert component["component_type"] == "BRAKE"
    assert component["criticality"] == "SAFETY_CRITICAL"
    assert component["ndt_interval_cycles"] == 40000
    assert component["ndt_interval_days"] == 180
    assert component["version"] == 1

    assert_component_install_baseline(component, CLOCK_START, 0)


def _three_units_across_two_park_areas():
    """Two FRONTIER units bracketing one LAGOON unit, created in a fixed order."""
    first = fixtures.create_attraction(
        name="Alpha Coaster",
        park_area="FRONTIER",
        manufacturer="Vekoma",
        model_code="SLC-689",
        ride_class="THRILL",
        theoretical_hourly_capacity=1000,
        min_operators_required=3,
        parts_budget_cents=2000000,
    )
    second = fixtures.create_attraction(
        name="Beta Splash",
        park_area="LAGOON",
        manufacturer="Mack",
        model_code="PW-12",
        ride_class="WATER",
        theoretical_hourly_capacity=800,
        min_operators_required=2,
        parts_budget_cents=2000000,
    )
    third = fixtures.create_attraction(
        name="Gamma Mine Train",
        park_area="FRONTIER",
        manufacturer="Vekoma",
        model_code="MT-3",
        ride_class="FAMILY",
        theoretical_hourly_capacity=600,
        min_operators_required=2,
        parts_budget_cents=2000000,
    )
    return [first, second, third]


def test_the_attraction_listing_paginates_filters_and_bounds_the_limit():
    """One page, its remainder, a filtered count and both ends of the limit range.

    PRD §2.3: "`limit` caps the number of rows returned; when it is omitted it
    defaults to 10, and a supplied value must be at least 1 and at most 100."
    PRD §2.3: "Every list response carries `limit`, `offset`, `total_count` and
    `has_more` inside the `meta` object of the envelope, where `total_count` counts
    every row matching the filters before pagination is applied and `has_more` is true
    exactly when rows remain beyond the current page."

    Design: Corner/entities/attraction_listing_paginates_filters_and_bounds_the_limit_range
    """
    first, _second, third = _three_units_across_two_park_areas()

    page, meta = validate_paginated(
        api_client.list_attractions(MANAGER, params={"limit": 2, "offset": 0})
    )
    assert len(page) == 2
    assert meta["total_count"] == 3
    assert meta["limit"] == 2
    assert meta["offset"] == 0
    assert meta["has_more"] is True

    remainder, remainder_meta = validate_paginated(
        api_client.list_attractions(MANAGER, params={"limit": 2, "offset": 2})
    )
    assert len(remainder) == 1
    assert remainder_meta["total_count"] == 3
    assert remainder_meta["offset"] == 2
    assert remainder_meta["has_more"] is False

    filtered, filtered_meta = validate_paginated(
        api_client.list_attractions(MANAGER, params={"park_area": "FRONTIER"})
    )
    assert len(filtered) == 2
    assert filtered_meta["total_count"] == 2
    assert filtered_meta["limit"] == 10
    assert filtered_meta["offset"] == 0
    assert filtered_meta["has_more"] is False
    assert {row["id"] for row in filtered} == {first["id"], third["id"]}

    validate_error(
        api_client.list_attractions(MANAGER, params={"limit": 0}),
        "ERR_INVALID_REQUEST",
        400,
    )
    validate_error(
        api_client.list_attractions(MANAGER, params={"limit": 101}),
        "ERR_INVALID_REQUEST",
        400,
    )


def test_omitting_a_required_input_registers_nothing():
    """A required input with no declared default cannot be defaulted away.

    PRD §2.6: "**Request shape.** All required fields are present, enum values are
    recognised members of their declared sets, integers sit inside their declared
    ranges, dates and instants are well formed".
    PRD §3.1: "`theoretical_hourly_capacity`, the number of guests the attraction
    carries per operating hour at design throughput, which must be at least 1".

    Design: Corner/entities/attraction_create_missing_required_field_returns_invalid_request
    """
    response = api_client.create_attraction(
        {
            "name": "No Capacity Ride",
            "park_area": "SKYLINE",
            "manufacturer": "Intamin",
            "model_code": "GD-40",
            "ride_class": "THRILL",
            "min_operators_required": 2,
            "parts_budget_cents": 1000000,
        },
        ADMIN,
    )
    error = validate_error(response, "ERR_INVALID_REQUEST", 400)
    assert isinstance(error["message"], str) and error["message"]
    assert response.json()["response_type"] == "error"

    _rows, meta = validate_paginated(api_client.list_attractions(ADMIN))
    assert meta["total_count"] == 0


def test_unknown_enum_members_and_out_of_range_integers_are_refused():
    """An unrecognised enum member and a below-floor integer are both malformed.

    PRD §3.1: "the `park_area` it sits in — one of `FRONTIER`, `LAGOON`, `SKYLINE` or
    `KIDS_COVE`".
    PRD §3.1: "its safety classification `criticality`, which is one of
    `SAFETY_CRITICAL`, `ESSENTIAL` or `NON_CRITICAL`".

    Design: Corner/entities/attraction_create_invalid_enum_and_out_of_range_integer_rejected
    """
    attraction = fixtures.create_attraction(
        name="Enum Probe",
        park_area="SKYLINE",
        manufacturer="Intamin",
        model_code="GD-40",
        ride_class="THRILL",
        theoretical_hourly_capacity=800,
        min_operators_required=2,
        parts_budget_cents=1000000,
    )

    validate_error(
        api_client.create_attraction(
            factories.create_attraction_payload(
                name="Bad Area",
                park_area="MIDWAY",
                manufacturer="Intamin",
                model_code="GD-40",
                ride_class="THRILL",
                theoretical_hourly_capacity=800,
                min_operators_required=2,
                parts_budget_cents=1000000,
            ),
            ADMIN,
        ),
        "ERR_INVALID_REQUEST",
        400,
    )
    validate_error(
        api_client.create_attraction(
            factories.create_attraction_payload(
                name="Zero Capacity",
                park_area="SKYLINE",
                manufacturer="Intamin",
                model_code="GD-40",
                ride_class="THRILL",
                theoretical_hourly_capacity=0,
                min_operators_required=2,
                parts_budget_cents=1000000,
            ),
            ADMIN,
        ),
        "ERR_INVALID_REQUEST",
        400,
    )
    validate_error(
        api_client.create_component(
            factories.create_component_payload(
                attraction["id"],
                name="Bad Criticality",
                component_type="AXLE",
                criticality="CRITICAL",
                ndt_interval_cycles=1000,
                ndt_interval_days=90,
            ),
            ADMIN,
        ),
        "ERR_INVALID_REQUEST",
        400,
    )

    _attractions, attraction_meta = validate_paginated(
        api_client.list_attractions(ADMIN)
    )
    assert attraction_meta["total_count"] == 1

    _components, component_meta = validate_paginated(
        api_client.list_components(ADMIN, params={"attraction_id": attraction["id"]})
    )
    assert component_meta["total_count"] == 0


def test_a_checklist_line_carries_no_version_and_no_updated_at():
    """The one immutable configuration row omits the audit pair the rest all carry.

    PRD §2.5: "A **checklist line** is a configuration row that is immutable once
    written: it carries only `id` and `created_at`. It has no `updated_at`, no
    `version`, and no update endpoint."
    PRD §3.1: "Appending a line sets the row's `template_id` from the revision being
    appended to and increments that revision's `item_count` by one."

    Design: Corner/entities/checklist_item_is_immutable_and_exposes_no_version_field
    """
    attraction = fixtures.create_attraction(
        name="Immutable Probe",
        park_area="FRONTIER",
        manufacturer="Zierer",
        model_code="FL-8",
        ride_class="FAMILY",
        theoretical_hourly_capacity=700,
        min_operators_required=2,
        parts_budget_cents=1000000,
    )
    component = fixtures.create_component(
        attraction["id"],
        name="Restraint Actuator 1",
        component_type="RESTRAINT_ACTUATOR",
        criticality="SAFETY_CRITICAL",
        ndt_interval_cycles=900000,
        ndt_interval_days=3650,
    )
    template = fixtures.create_template(attraction["id"], effective_from_date="2026-08-01")
    appended = fixtures.append_line(
        template["id"],
        sequence_no=1,
        severity_class="SAFETY_CRITICAL",
        description="Cycle restraint actuator",
        component_id=component["id"],
        requires_photo=True,
    )

    item = validate_success(
        api_client.get_checklist_item(appended["id"], TECHNICIAN)
    )
    assert_checklist_item(item)
    assert item["template_id"] == template["id"]
    assert item["component_id"] == component["id"]
    assert item["sequence_no"] == 1
    assert item["severity_class"] == "SAFETY_CRITICAL"
    assert item["requires_photo"] is True
    assert "version" not in item
    assert "updated_at" not in item

    rows, meta = validate_paginated(
        api_client.list_checklist_items(
            TECHNICIAN, params={"template_id": template["id"]}
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == appended["id"]


def test_installing_a_component_on_an_unknown_attraction_names_the_parent():
    """A body foreign key that resolves to nothing is a 404 naming the parent.

    PRD §2.6: "**Body foreign-key existence.** Every foreign key supplied in the
    request body resolves to a live row, validated in the order the fields are
    declared for that endpoint in §4's companion narrative."
    PRD §5: "`ERR_ATTRACTION_NOT_FOUND` | 404 | A referenced attraction does not
    exist."

    Design: Corner/entities/component_create_with_unknown_attraction_returns_attraction_not_found
    """
    response = api_client.create_component(
        factories.create_component_payload(
            UNKNOWN_ID,
            name="Orphan Axle",
            component_type="AXLE",
            criticality="ESSENTIAL",
            ndt_interval_cycles=20000,
            ndt_interval_days=365,
        ),
        ADMIN,
    )
    validate_error(response, "ERR_ATTRACTION_NOT_FOUND", 404)

    _rows, meta = validate_paginated(api_client.list_components(ADMIN))
    assert meta["total_count"] == 0


def test_the_two_requisition_parent_links_are_exclusive_and_same_attraction():
    """The polymorphic parentage is checked three ways on one create endpoint.

    PRD §3.5: "Two optional links express the reason for the part, and they are
    mutually exclusive: `downtime_event_id` attaches the requisition to a downtime
    repair, `bulletin_action_id` attaches it to a fleet corrective action, and a
    requisition may carry one of them or neither. Supplying both on the same request
    is refused with `ERR_INVALID_REQUEST`, and so is supplying a `downtime_event_id`
    or `bulletin_action_id` that belongs to a different attraction than the
    requisition's own `attraction_id`."
    PRD §3.5: "Creation computes `total_cost_cents` as the `quantity` multiplied by
    the `unit_cost_cents`, in whole cents, and leaves the requisition at `status`
    `REQUESTED` with `expected_availability_date` and `cancel_reason` both null."

    Design: Corner/entities/part_requisition_polymorphic_parent_links_cross_reference_integrity_rejected
    """
    first = fixtures.create_attraction(
        name="Cross Ref A1",
        park_area="FRONTIER",
        manufacturer="Gerstlauer",
        model_code="XR-1",
        ride_class="THRILL",
        theoretical_hourly_capacity=900,
        min_operators_required=2,
        parts_budget_cents=5000000,
    )
    second = fixtures.create_attraction(
        name="Cross Ref A2",
        park_area="LAGOON",
        manufacturer="Zamperla",
        model_code="XR-2",
        ride_class="FAMILY",
        theoretical_hourly_capacity=500,
        min_operators_required=1,
        parts_budget_cents=5000000,
    )
    foreign_event = fixtures.open_downtime(second["id"])
    fleet = fixtures.acknowledged_bulletin_with_actions(
        bulletin_ref="BR-XREF-1",
        manufacturer="Gerstlauer",
        model_code="XR-1",
        severity="ADVISORY",
        issued_date="2026-07-01",
        compliance_deadline_date="2026-12-01",
        attractions=[first],
    )
    action = fleet["actions"][0]

    base = {
        "attraction_id": first["id"],
        "part_number": "PN-XREF",
        "quantity": 2,
        "unit_cost_cents": 30000,
        "needed_by_date": "2026-08-20",
    }

    validate_error(
        api_client.create_part_requisition(
            dict(base, downtime_event_id=foreign_event["id"]), TECHNICIAN
        ),
        "ERR_INVALID_REQUEST",
        400,
    )
    validate_error(
        api_client.create_part_requisition(
            dict(
                base,
                downtime_event_id=foreign_event["id"],
                bulletin_action_id=action["id"],
            ),
            TECHNICIAN,
        ),
        "ERR_INVALID_REQUEST",
        400,
    )

    accepted = validate_success(
        api_client.create_part_requisition(
            dict(base, bulletin_action_id=action["id"]), TECHNICIAN
        ),
        201,
    )
    assert_part_requisition(accepted)
    assert accepted["status"] == "REQUESTED"
    assert accepted["total_cost_cents"] == 60000
    assert accepted["bulletin_action_id"] == action["id"]
    assert accepted["downtime_event_id"] is None

    assert fixtures.read_attraction(first["id"])["parts_budget_committed_cents"] == 0
