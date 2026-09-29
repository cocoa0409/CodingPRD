"""Entity contracts: echoed inputs, declared defaults, listings and shape failures.

Every test builds all of its own preconditions -- the harness restarts the
server and empties the database before each individual test.
"""

import pytest

from test_helpers import (
    ACTIVITY_MODERATE,
    CONDUCIVE_EXCESS_MOISTURE,
    CONSTRUCTION_CRAWLSPACE,
    CONSTRUCTION_SLAB,
    ERR_BOND_NOT_FOUND,
    ERR_FIELD_COMBINATION_INVALID,
    ERR_INSPECTION_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_PROPERTY_MISMATCH,
    INSPECTION_DRAFT,
    INSPECTION_GRAPHED,
    LICENSE_STATUS_ACTIVE,
    MANAGER_HEADERS,
    METHOD_LIQUID_BARRIER,
    NON_EXISTENT_UUID,
    OFFICER_HEADERS,
    ORGANISM_NONE,
    PLAN_PROPOSED,
    add_finding,
    approve_plan,
    assert_conducive_counts_conserved,
    assert_created_at_ascending,
    assert_entity_shape,
    assert_instant_equals,
    assert_money,
    assert_page,
    assert_status,
    assert_version,
    clean_initial_graph,
    completed_bait_plan,
    conducive_finding_payload,
    damage_finding_payload,
    expected_quoted_price,
    expected_target_gallons,
    inspection_payload,
    list_stations,
    make_field_inspector_headers,
    open_graph,
    propose_plan,
    property_payload,
    record_application,
    register_inspector,
    register_property,
    register_property_and_inspector,
    retention_until,
    service_station,
    set_clock,
    sign_graph,
    treatment_plan_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK_START_RENDERED = "2026-08-01T00:00:00.000Z"

# A station's last_serviced_at is its installing plan's completed_at, and PRD 3.9
# requires a visit's serviced_at to be *strictly after* it, so a visit is only
# recordable once the clock has moved on from installation.
STATION_VISIT_INSTANT = "2026-08-31T00:00:00Z"
STATION_VISIT_RENDERED = "2026-08-31T00:00:00.000Z"


# ---------------------------------------------------------------------------
# Property registration
# ---------------------------------------------------------------------------


def test_property_create_returns_every_field_with_a_zeroed_ledger(api):
    """A freshly registered structure echoes its inputs and starts inert.

    PRD 3.1: "A freshly registered structure has `total_conducive_condition_count`,
    `waived_conducive_condition_count` and `open_conducive_condition_count` all
    equal to 0, and `active_infestation_on_record` false."

    Design: Corner/entities/property_create_returns_every_field_with_a_zeroed_conducive_ledger
    """
    payload = property_payload(
        address_line1="411 Cypress Row",
        state_code="FL",
        construction_type=CONSTRUCTION_SLAB,
        square_footage=2000,
        linear_footage=180,
        year_built=1995,
        has_attached_structures=False,
    )
    data = validate_success(api.create_property(payload, OFFICER_HEADERS), 201)

    assert_entity_shape(data, "property")
    assert data["address_line1"] == "411 Cypress Row"
    assert data["state_code"] == "FL"
    assert data["construction_type"] == CONSTRUCTION_SLAB
    assert data["square_footage"] == 2000
    assert data["linear_footage"] == 180
    assert data["year_built"] == 1995
    assert data["has_attached_structures"] is False
    assert data["crawl_clearance_inches"] is None
    assert data["total_conducive_condition_count"] == 0
    assert data["waived_conducive_condition_count"] == 0
    assert data["open_conducive_condition_count"] == 0
    assert data["active_infestation_on_record"] is False
    assert_version(data, 1, "property")
    assert_instant_equals(data["updated_at"], data["created_at"])
    assert_conducive_counts_conserved(data)


def test_property_create_ignores_client_supplied_system_fields(api):
    """A client may not seed the id, the version counter or a computed counter.

    PRD 2.4: "Every persisted resource carries a server-minted `id` ... Clients
    never supply an `id`; a client-supplied one is ignored."

    Design: Corner/entities/property_create_extra_field_system_values_input_ignored
    """
    supplied_id = "11111111-1111-4111-8111-111111111111"
    payload = property_payload(
        address_line1="411 Cypress Row",
        id=supplied_id,
        version=77,
        created_at="2000-01-01T00:00:00.000Z",
        total_conducive_condition_count=9,
    )
    data = validate_success(api.create_property(payload, OFFICER_HEADERS), 201)

    assert data["id"] != supplied_id
    assert_version(data, 1, "property")
    assert_instant_equals(data["created_at"], CLOCK_START_RENDERED)
    assert data["total_conducive_condition_count"] == 0

    stored = validate_success(api.get_property(data["id"], OFFICER_HEADERS))
    assert stored["id"] == data["id"]
    assert_version(stored, 1, "property")
    assert stored["total_conducive_condition_count"] == 0
    assert_instant_equals(stored["created_at"], CLOCK_START_RENDERED)


# ---------------------------------------------------------------------------
# Inspector read-after-write
# ---------------------------------------------------------------------------


def test_inspector_get_returns_the_stored_licence_row_unchanged(api):
    """A read-after-write returns the persisted licence row and its two defaults.

    PRD 3.2: "A `ComplianceOfficer` registers each licensee, supplying
    `full_name`, `license_number`, `license_state`, `license_categories` and
    `license_expires_on`, optionally `fumigation_endorsement` and `ce_credits`.
    The new record's `status` is `ACTIVE`."

    Design: Corner/entities/inspector_get_returns_the_stored_licence_row_unchanged
    """
    inspector = register_inspector(
        api,
        full_name="Rosa Vance",
        license_number="FL-10001",
        license_state="FL",
        license_categories=["WDO_INSPECTOR"],
        license_expires_on="2029-06-30",
    )

    data = validate_success(api.get_inspector(inspector["id"], OFFICER_HEADERS))

    assert_entity_shape(data, "inspector")
    assert data["id"] == inspector["id"]
    assert data["full_name"] == "Rosa Vance"
    assert data["license_number"] == "FL-10001"
    assert data["license_state"] == "FL"
    assert data["license_categories"] == ["WDO_INSPECTOR"]
    assert data["license_expires_on"] == "2029-06-30"
    assert data["status"] == LICENSE_STATUS_ACTIVE
    assert data["fumigation_endorsement"] is False
    assert data["ce_credits"] == 0
    assert_version(data, 1, "inspector")


# ---------------------------------------------------------------------------
# Collection reads
# ---------------------------------------------------------------------------


def _three_properties(api):
    """Register three structures at three distinct clock instants."""
    set_clock(api, "2026-08-01T00:00:00Z")
    first = register_property(
        api,
        address_line1="1 First St",
        state_code="FL",
        construction_type=CONSTRUCTION_SLAB,
        square_footage=1600,
        linear_footage=140,
        year_built=1990,
    )
    set_clock(api, "2026-08-01T01:00:00Z")
    second = register_property(
        api,
        address_line1="2 Second St",
        state_code="FL",
        construction_type=CONSTRUCTION_CRAWLSPACE,
        square_footage=1400,
        linear_footage=150,
        year_built=1988,
        crawl_clearance_inches=22,
    )
    set_clock(api, "2026-08-01T02:00:00Z")
    third = register_property(
        api,
        address_line1="3 Third St",
        state_code="GA",
        construction_type=CONSTRUCTION_SLAB,
        square_footage=2200,
        linear_footage=190,
        year_built=2004,
        has_attached_structures=True,
    )
    return first, second, third


def test_properties_first_page_reports_total_count_and_has_more(api):
    """The first page of a three-row collection still counts every matching row.

    PRD 2.3: "Both values are echoed back in `meta` alongside `total_count`, the
    number of rows matching the request before paging, and `has_more`, which is
    true exactly when rows remain beyond the current page."

    Design: Corner/entities/properties_list_paginates_with_total_count_and_has_more
    """
    first, second, _third = _three_properties(api)

    response = api.list_properties(OFFICER_HEADERS, limit=2, offset=0)
    rows, meta = assert_page(response, 3, expected_rows=2, expected_has_more=True)

    assert meta["limit"] == 2
    assert meta["offset"] == 0
    assert [row["id"] for row in rows] == [first["id"], second["id"]]
    assert_created_at_ascending(rows)


def test_properties_second_page_closes_the_collection(api):
    """The trailing page keeps the same total_count and reports no more rows.

    PRD 2.3: "`offset` controls the starting position: it defaults to 0 and may
    not be negative."

    Design: Corner/entities/properties_list_paginates_with_total_count_and_has_more
    """
    _first, _second, third = _three_properties(api)

    response = api.list_properties(OFFICER_HEADERS, limit=2, offset=2)
    rows, meta = assert_page(response, 3, expected_rows=1, expected_has_more=False)

    assert meta["offset"] == 2
    assert rows[0]["id"] == third["id"]


def test_properties_unpaginated_read_applies_the_declared_defaults(api):
    """An unqualified read takes limit 10 and offset 0 and orders oldest first.

    PRD 2.3: "`limit` controls page size: it defaults to 10 ... `offset`
    controls the starting position: it defaults to 0."

    Design: Corner/entities/properties_list_paginates_with_total_count_and_has_more
    """
    first, second, third = _three_properties(api)

    rows, meta = assert_page(
        api.list_properties(OFFICER_HEADERS), 3, expected_rows=3, expected_has_more=False
    )

    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert [row["id"] for row in rows] == [first["id"], second["id"], third["id"]]


def test_properties_state_code_filter_narrows_before_paging(api):
    """An exact-match state filter drops the out-of-state structure entirely.

    PRD 2.3: "Filters narrow a collection before paging is applied, and every
    filter is an exact-match equality test. Structures may be filtered by
    `state_code` and by `construction_type`."

    Design: Corner/entities/properties_list_paginates_with_total_count_and_has_more
    """
    first, second, third = _three_properties(api)

    rows, meta = assert_page(
        api.list_properties(OFFICER_HEADERS, state_code="FL"),
        2,
        expected_rows=2,
        expected_has_more=False,
    )

    ids = [row["id"] for row in rows]
    assert ids == [first["id"], second["id"]]
    assert third["id"] not in ids


# ---------------------------------------------------------------------------
# Path existence
# ---------------------------------------------------------------------------


def test_bond_get_with_unknown_uuid_returns_not_found(api):
    """A well-formed id naming no bond reports the bond's own not-found code.

    PRD 2.6: "Every identifier segment in the request path resolves to a
    persisted row of that segment's type, validated left to right; the leftmost
    segment that fails to resolve reports its own type's not-found code."

    Design: Corner/entities/bond_get_with_unknown_uuid_returns_not_found
    """
    response = api.get_bond(NON_EXISTENT_UUID, OFFICER_HEADERS)

    body = validate_error(response, ERR_BOND_NOT_FOUND)
    assert isinstance(body["message"], str) and body["message"].strip()
    assert set(body.keys()) == {"error_id", "message"}


# ---------------------------------------------------------------------------
# Request shape on graph creation
# ---------------------------------------------------------------------------


def test_inspection_create_without_purpose_is_a_shape_failure(api):
    """Omitting a required input is rejected before any referenced row is read.

    PRD 2.6: "On every write operation: each field the operation declares as
    required is present and non-null ... Any failure is `ERR_INVALID_REQUEST`."

    Design: Corner/entities/inspection_create_missing_required_purpose_returns_invalid_request
    """
    prop, inspector = register_property_and_inspector(api)
    payload = inspection_payload(prop["id"], inspector["id"])
    del payload["purpose"]

    response = api.create_inspection(
        payload, make_field_inspector_headers(inspector["id"])
    )

    validate_error(response, ERR_INVALID_REQUEST)

    rows, meta = validate_paginated(
        api.list_inspections(OFFICER_HEADERS, property_id=prop["id"])
    )
    assert meta["total_count"] == 0
    assert rows == []


def test_inspection_create_without_purpose_consumes_no_sequence_no(api):
    """A rejected graph never burns the structure's 1-based graph counter.

    PRD 3.3: "The new graph is created in status `DRAFT` and is stamped with a
    `sequence_no`: a 1-based counter that is one greater than the highest
    `sequence_no` yet issued for that structure."

    Design: Corner/entities/inspection_create_missing_required_purpose_returns_invalid_request
    """
    prop, inspector = register_property_and_inspector(api)
    rejected = inspection_payload(prop["id"], inspector["id"])
    del rejected["purpose"]
    validate_error(
        api.create_inspection(
            rejected, make_field_inspector_headers(inspector["id"])
        ),
        ERR_INVALID_REQUEST,
    )

    graph = open_graph(api, prop["id"], inspector["id"])

    assert graph["sequence_no"] == 1
    assert_status(graph, INSPECTION_DRAFT, "inspection")


# ---------------------------------------------------------------------------
# Notation defaults and the rollups they feed
# ---------------------------------------------------------------------------


def test_finding_create_applies_the_three_declared_defaults(api):
    """A conducive cell supplying nothing optional takes severity 1 and NONE.

    PRD 3.3: "`severity` is an integer weight from 1 to 5 defaulting to 1 ...
    `organism` ... defaulting to `NONE` ... `damage_estimate_usd` is the repair
    estimate for that cell, from 0.00 to 250000.00 with at most two decimal
    places, defaulting to 0.00 ... `pre_existing` is a flag, defaulting to
    false."

    Design: Corner/entities/finding_create_omits_optional_fields_and_defaults_are_applied
    """
    prop, inspector = register_property_and_inspector(api)
    graph = open_graph(api, prop["id"], inspector["id"])

    data = validate_success(
        api.create_finding(
            graph["id"],
            conducive_finding_payload("A1", CONDUCIVE_EXCESS_MOISTURE),
            make_field_inspector_headers(inspector["id"]),
        ),
        201,
    )

    assert_entity_shape(data, "graph_finding")
    assert data["inspection_id"] == graph["id"]
    assert data["grid_ref"] == "A1"
    assert data["conducive_code"] == CONDUCIVE_EXCESS_MOISTURE
    assert data["severity"] == 1
    assert data["organism"] == ORGANISM_NONE
    assert_money(data["damage_estimate_usd"], 0.00)
    assert data["pre_existing"] is False
    assert "version" not in data
    assert "updated_at" not in data


def test_signing_rolls_the_single_conducive_notation_up(api):
    """Signing the graph is where the four rollups are computed from its cells.

    PRD 3.3: "Signing stamps `graph_completed_at` with the current logical-clock
    instant ... and then recomputes four rollups from the graph's own notations.
    `findings_count` is the number of notations on the graph."

    Design: Corner/entities/finding_create_omits_optional_fields_and_defaults_are_applied
    """
    prop, inspector = register_property_and_inspector(api)
    graph = open_graph(api, prop["id"], inspector["id"])
    add_finding(
        api,
        graph["id"],
        inspector["id"],
        conducive_finding_payload("A1", CONDUCIVE_EXCESS_MOISTURE),
    )
    sign_graph(api, graph["id"], inspector["id"])

    data = validate_success(api.get_inspection(graph["id"], OFFICER_HEADERS))

    assert data["findings_count"] == 1
    assert data["conducive_condition_count"] == 1
    assert data["active_infestation_found"] is False
    assert_money(data["damage_estimate_total_usd"], 0.00)


# ---------------------------------------------------------------------------
# Treatment sizing and pricing on a non-slab structure
# ---------------------------------------------------------------------------


def test_plan_create_sizes_and_prices_a_crawlspace_structure(api):
    """A crawlspace trench takes the 1.5 rate with no drilling term at all.

    PRD 3.5: "The trench part is the structure's `linear_footage` multiplied by a
    per-foot trench rate that depends on the substructure: 1.0 gallon per linear
    foot for a slab, 1.5 for a crawlspace, 2.0 for a basement, and 1.25 for
    pier-and-beam construction. The drilling part applies to slab construction
    alone ... for every other substructure the drilling part is zero."

    Design: Corner/entities/plan_create_computes_gallons_and_quote_for_a_crawlspace_property
    """
    prop = register_property(
        api,
        address_line1="2 Second St",
        state_code="FL",
        construction_type=CONSTRUCTION_CRAWLSPACE,
        square_footage=1400,
        linear_footage=150,
        year_built=1988,
        crawl_clearance_inches=22,
        has_attached_structures=False,
    )
    inspector = register_inspector(api, license_state="FL")
    applicator = register_inspector(api, license_state="FL")
    graph = clean_initial_graph(api, prop["id"], inspector["id"])

    data = validate_success(
        api.create_treatment_plan(
            treatment_plan_payload(prop["id"], graph["id"], applicator["id"]),
            MANAGER_HEADERS,
        ),
        201,
    )

    assert_entity_shape(data, "treatment_plan")
    assert_money(
        data["target_gallons"],
        expected_target_gallons(
            CONSTRUCTION_CRAWLSPACE, METHOD_LIQUID_BARRIER, 1400, 150
        ),
    )
    assert_money(data["target_gallons"], 225.00)
    assert data["target_station_count"] == 0


def test_plan_create_quotes_a_crawlspace_at_the_construction_multiplier(api):
    """The quote loads a single-tier area subtotal by the 1.15 crawlspace factor.

    PRD 3.5: "The running figure is multiplied by a construction multiplier: 1.00
    for `SLAB`, 1.15 for `CRAWLSPACE`, 1.25 for `BASEMENT`, 1.10 for
    `PIER_AND_BEAM`." Only step 5 rounds, half up, to two decimal places.

    Design: Corner/entities/plan_create_computes_gallons_and_quote_for_a_crawlspace_property
    """
    prop = register_property(
        api,
        address_line1="2 Second St",
        state_code="FL",
        construction_type=CONSTRUCTION_CRAWLSPACE,
        square_footage=1400,
        linear_footage=150,
        year_built=1988,
        crawl_clearance_inches=22,
        has_attached_structures=False,
    )
    inspector = register_inspector(api, license_state="FL")
    applicator = register_inspector(api, license_state="FL")
    graph = clean_initial_graph(api, prop["id"], inspector["id"])

    data = validate_success(
        api.create_treatment_plan(
            treatment_plan_payload(prop["id"], graph["id"], applicator["id"]),
            MANAGER_HEADERS,
        ),
        201,
    )

    assert_money(
        data["quoted_price_usd"],
        expected_quoted_price(1400, METHOD_LIQUID_BARRIER, CONSTRUCTION_CRAWLSPACE, False),
    )
    assert_money(data["quoted_price_usd"], 992.45)


def test_plan_create_starts_undischarged_with_no_fumigation_fields(api):
    """A newly proposed non-fumigation plan carries every counter at its floor.

    PRD 3.5: "The new plan is created in status `PROPOSED`, and the act of
    proposing retires competition: every other plan on that same structure still
    sitting in `PROPOSED` is moved to `ABANDONED`."

    Design: Corner/entities/plan_create_computes_gallons_and_quote_for_a_crawlspace_property
    """
    prop = register_property(
        api,
        address_line1="2 Second St",
        state_code="FL",
        construction_type=CONSTRUCTION_CRAWLSPACE,
        square_footage=1400,
        linear_footage=150,
        year_built=1988,
        crawl_clearance_inches=22,
        has_attached_structures=False,
    )
    inspector = register_inspector(api, license_state="FL")
    applicator = register_inspector(api, license_state="FL")
    graph = clean_initial_graph(api, prop["id"], inspector["id"])

    data = validate_success(
        api.create_treatment_plan(
            treatment_plan_payload(prop["id"], graph["id"], applicator["id"]),
            MANAGER_HEADERS,
        ),
        201,
    )

    assert_status(data, PLAN_PROPOSED, "treatment_plan")
    assert_money(data["gallons_applied_total"], 0.00)
    assert data["escalated_station_count"] == 0
    assert data["retreat_required"] is False
    assert data["completed_at"] is None
    assert data["fumigation_permit_number"] is None
    assert data["fumigation_start_at"] is None
    assert data["fumigation_reentry_at"] is None


# ---------------------------------------------------------------------------
# Scalar and combination failures on one notation endpoint
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "overrides",
    [
        {"organism": "CARPENTER_BEE"},
        {"severity": 9},
        {"grid_ref": "K11"},
    ],
    ids=["unknown-organism", "severity-above-range", "grid-ref-off-the-graph"],
)
def test_finding_create_rejects_a_scalar_outside_its_declared_domain(api, overrides):
    """An unknown enum member, an out-of-range weight and a bad cell all fail shape.

    PRD 2.6: "every enumerated field holds a declared member ... a `grid_ref` is a
    single column letter from `A` through `J` immediately followed by a row number
    from 1 through 10. Numeric values outside their declared range fail here too.
    Any failure is `ERR_INVALID_REQUEST`."

    Design: Corner/entities/finding_create_with_invalid_enum_or_out_of_range_severity_rejected
    """
    prop, inspector = register_property_and_inspector(api)
    graph = open_graph(api, prop["id"], inspector["id"])
    payload = damage_finding_payload("A2", 500.00, severity=2, organism="FUNGUS")
    payload.update(overrides)

    response = api.create_finding(
        graph["id"], payload, make_field_inspector_headers(inspector["id"])
    )

    validate_error(response, ERR_INVALID_REQUEST)


def test_finding_create_rejects_a_damage_cell_with_a_zero_estimate(api):
    """Every scalar is in range, yet a damage cell worth nothing is illegal.

    PRD 2.6: "On graph creation and cell notation only: ... `damage_estimate_usd`
    greater than zero exactly when `finding_type` is `DAMAGE` ... Any failure is
    `ERR_FIELD_COMBINATION_INVALID`."

    Design: Corner/entities/finding_create_with_invalid_enum_or_out_of_range_severity_rejected
    """
    prop, inspector = register_property_and_inspector(api)
    graph = open_graph(api, prop["id"], inspector["id"])
    payload = damage_finding_payload("A2", 0.00, severity=2, organism="FUNGUS")

    response = api.create_finding(
        graph["id"], payload, make_field_inspector_headers(inspector["id"])
    )

    validate_error(response, ERR_FIELD_COMBINATION_INVALID)


def test_finding_create_rejections_leave_the_graph_empty(api):
    """Four refused notations write nothing at all to the draft graph.

    PRD 3.3: "`findings_count` is the number of notations on the graph."

    Design: Corner/entities/finding_create_with_invalid_enum_or_out_of_range_severity_rejected
    """
    prop, inspector = register_property_and_inspector(api)
    graph = open_graph(api, prop["id"], inspector["id"])
    headers = make_field_inspector_headers(inspector["id"])
    rejected = [
        damage_finding_payload("A2", 500.00, severity=2, organism="CARPENTER_BEE"),
        damage_finding_payload("A2", 500.00, severity=9, organism="FUNGUS"),
        damage_finding_payload("K11", 500.00, severity=2, organism="FUNGUS"),
        damage_finding_payload("A2", 0.00, severity=2, organism="FUNGUS"),
    ]
    for payload in rejected[:3]:
        validate_error(
            api.create_finding(graph["id"], payload, headers), ERR_INVALID_REQUEST
        )
    validate_error(
        api.create_finding(graph["id"], rejected[3], headers),
        ERR_FIELD_COMBINATION_INVALID,
    )

    rows, meta = validate_paginated(api.list_findings(graph["id"], OFFICER_HEADERS))
    assert meta["total_count"] == 0
    assert rows == []
    stored = validate_success(api.get_inspection(graph["id"], OFFICER_HEADERS))
    assert stored["findings_count"] == 0


# ---------------------------------------------------------------------------
# The two audit record types
# ---------------------------------------------------------------------------


def _plan_with_one_application(api):
    """A SLAB structure whose approved liquid plan carries one 190-gallon record."""
    prop = register_property(api, state_code="FL")
    inspector = register_inspector(api, license_state="FL")
    applicator = register_inspector(api, license_state="FL")
    graph = clean_initial_graph(api, prop["id"], inspector["id"])
    plan = propose_plan(api, prop["id"], graph["id"], applicator["id"])
    plan = approve_plan(api, plan["id"])
    record_application(
        api,
        plan["id"],
        applicator["id"],
        plan["version"],
        product_epa_number="432-1234",
        gallons_applied=190.00,
        concentration_pct=0.06,
    )
    return prop, applicator, plan


def test_pesticide_record_is_written_once_and_exposes_no_version(api):
    """A discharge record carries id and created_at and nothing else common.

    PRD 3.6: "The record itself never changes again: it has no `updated_at`, no
    `version`, and no update operation, and the records of one plan are listed
    back in creation order."

    Design: Corner/entities/pesticide_record_and_station_service_are_immutable_rows
    """
    _prop, _applicator, plan = _plan_with_one_application(api)

    rows, meta = validate_paginated(
        api.list_applications(plan["id"], OFFICER_HEADERS)
    )

    assert meta["total_count"] == 1
    assert len(rows) == 1
    row = rows[0]
    assert_entity_shape(row, "pesticide_record")
    assert "version" not in row
    assert "updated_at" not in row
    assert row["treatment_plan_id"] == plan["id"]
    assert row["product_epa_number"] == "432-1234"
    assert_money(row["gallons_applied"], 190.00)
    assert_money(row["concentration_pct"], 0.06)


def test_pesticide_record_snapshots_the_retention_deadline(api):
    """The record's retention deadline is its own applied_at date plus 4 x 365 days.

    PRD 3.6: "It also computes `retention_until`, the last calendar date on which
    the state requires the record to be kept, as the UTC date of `applied_at` plus
    the state's retention year count multiplied by 365 days."

    Design: Corner/entities/pesticide_record_and_station_service_are_immutable_rows
    """
    _prop, _applicator, plan = _plan_with_one_application(api)

    rows, _meta = validate_paginated(
        api.list_applications(plan["id"], OFFICER_HEADERS)
    )
    row = rows[0]

    assert_instant_equals(row["applied_at"], CLOCK_START_RENDERED)
    assert row["state_code"] == "FL"
    assert row["retention_until"] == retention_until(row["applied_at"], "FL")
    assert row["retention_until"] == "2030-07-31"


def test_the_parent_plan_absorbs_the_discharge_instead(api):
    """The immutable child cannot change, so the mutable parent carries the total.

    PRD 3.6: "The plan's `gallons_applied_total` — the running sum of
    `gallons_applied` over the plan's records — is increased by the gallons just
    discharged, and the plan's `version` rises by one."

    Design: Corner/entities/pesticide_record_and_station_service_are_immutable_rows
    """
    _prop, _applicator, plan = _plan_with_one_application(api)

    stored = validate_success(api.get_treatment_plan(plan["id"], OFFICER_HEADERS))

    assert_money(stored["gallons_applied_total"], 190.00)
    assert_version(stored, plan["version"] + 1, "treatment_plan")


def test_station_service_is_written_once_and_exposes_no_version(api):
    """A station visit is the second audit row that carries no version at all.

    PRD 2.4: "Three record types are immutable by design and therefore carry
    neither `updated_at` nor `version`: a graph cell notation, a pesticide
    application record, and a bait-station service visit."

    Design: Corner/entities/pesticide_record_and_station_service_are_immutable_rows
    """
    prop = register_property(api, state_code="FL")
    inspector = register_inspector(api, license_state="FL")
    applicator = register_inspector(api, license_state="FL")
    graph = clean_initial_graph(api, prop["id"], inspector["id"])
    plan = completed_bait_plan(api, prop["id"], graph["id"], applicator["id"])
    stations = list_stations(api, plan["id"])

    # PRD 3.9: "the clock instant that will stamp `serviced_at` must be
    # **strictly after** the station's current `last_serviced_at`", which at
    # installation is the plan's completed_at, so the clock must move first.
    set_clock(api, STATION_VISIT_INSTANT)
    visit = service_station(
        api, stations[0]["id"], applicator["id"], ACTIVITY_MODERATE
    )

    assert_entity_shape(visit, "station_service")
    assert "version" not in visit
    assert "updated_at" not in visit
    assert visit["bait_station_id"] == stations[0]["id"]
    assert visit["activity_level"] == ACTIVITY_MODERATE
    assert visit["matrix_replaced"] is False
    assert_instant_equals(visit["serviced_at"], STATION_VISIT_RENDERED)


# ---------------------------------------------------------------------------
# Body references on a proposal
# ---------------------------------------------------------------------------


def test_plan_create_with_unknown_inspection_id_returns_not_found(api):
    """One unresolvable body reference decides the outcome on its own.

    PRD 2.6: "Every identifier carried in a request **body** resolves to a
    persisted row: `property_id`, `inspector_id`, `supersedes_inspection_id`,
    `inspection_id`, `treatment_plan_id`, `bond_id`, `verifying_inspection_id`
    and `reinstatement_inspection_id`. The applicable not-found code is reported
    at HTTP 404."

    Design: Corner/entities/plan_create_with_unknown_inspection_id_returns_not_found
    """
    prop = register_property(api, state_code="FL")
    applicator = register_inspector(api, license_state="FL")

    response = api.create_treatment_plan(
        treatment_plan_payload(prop["id"], NON_EXISTENT_UUID, applicator["id"]),
        MANAGER_HEADERS,
    )

    validate_error(response, ERR_INSPECTION_NOT_FOUND)

    rows, meta = validate_paginated(
        api.list_treatment_plans(OFFICER_HEADERS, property_id=prop["id"])
    )
    assert meta["total_count"] == 0
    assert rows == []


def test_plan_create_citing_another_structures_graph_is_a_mismatch(api):
    """Both references resolve, yet the graph justifies a different structure.

    PRD 3.5: "The graph named must belong to the same structure as
    `property_id`, or the proposal is refused with `ERR_PROPERTY_MISMATCH`."

    Design: Corner/entities/plan_create_with_inspection_from_another_property_rejected
    """
    first = register_property(api, address_line1="411 Cypress Row", state_code="FL")
    other = register_property(api, address_line1="413 Cypress Row", state_code="FL")
    inspector = register_inspector(api, license_state="FL")
    applicator = register_inspector(api, license_state="FL")
    foreign_graph = clean_initial_graph(api, other["id"], inspector["id"])

    response = api.create_treatment_plan(
        treatment_plan_payload(first["id"], foreign_graph["id"], applicator["id"]),
        MANAGER_HEADERS,
    )

    validate_error(response, ERR_PROPERTY_MISMATCH)


def test_a_mismatched_proposal_writes_nothing_and_leaves_the_graph_alone(api):
    """The refusal is inert: no plan row appears and the cited graph is untouched.

    PRD 2.6: "A single malformed or ill-timed request frequently violates several
    rules at once ... the **first** violated check determines the response."

    Design: Corner/entities/plan_create_with_inspection_from_another_property_rejected
    """
    first = register_property(api, address_line1="411 Cypress Row", state_code="FL")
    other = register_property(api, address_line1="413 Cypress Row", state_code="FL")
    inspector = register_inspector(api, license_state="FL")
    applicator = register_inspector(api, license_state="FL")
    foreign_graph = clean_initial_graph(api, other["id"], inspector["id"])

    validate_error(
        api.create_treatment_plan(
            treatment_plan_payload(first["id"], foreign_graph["id"], applicator["id"]),
            MANAGER_HEADERS,
        ),
        ERR_PROPERTY_MISMATCH,
    )

    rows, meta = validate_paginated(
        api.list_treatment_plans(OFFICER_HEADERS, property_id=first["id"])
    )
    assert meta["total_count"] == 0
    assert rows == []

    stored = validate_success(api.get_inspection(foreign_graph["id"], OFFICER_HEADERS))
    assert_status(stored, INSPECTION_GRAPHED, "inspection")
    assert_version(stored, foreign_graph["version"], "inspection")
