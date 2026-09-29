"""Creation defaults, stored shapes and the not-found surface of the core entities."""

from test_helpers import (
    NON_EXISTENT_UUID,
    api_client,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.assertions import (
    assert_instant_equals,
    assert_power_kw,
    assert_row_shares,
    assert_tranche_balance_identity,
    assert_tranche_balances,
    assert_unit_balances,
)
from test_helpers.constants import FY2027_AVAILABLE_ON, FY2027_EXPIRES_ON

CLOCK = "2026-08-01T00:00:00Z"


def test_a_new_funding_unit_starts_with_a_zeroed_ledger_and_a_full_pool():
    """Registration seeds the pool and leaves every accumulated figure at zero.

    PRD 2.8: "On creation a unit's reserved_cents, committed_cents, disbursed_cents and
    refunded_cents are all 0, and available_pool_cents equals cost_share_pool_cents."

    Design: Corner/entities/corner_funding_unit_create_returns_zeroed_ledger_and_derived_pool
    """
    fixtures.set_clock(CLOCK)
    response = api_client.create_funding_unit(
        {"name": "College of Natural Sciences", "unit_type": "COLLEGE",
         "cost_share_pool_cents": 900_000_000},
        fixtures.DEAN_OFFICE,
    )
    unit = validate_success(response, expected_status=201)

    assert unit["unit_type"] == "COLLEGE"
    assert unit["parent_unit_id"] is None
    assert unit["cost_share_pool_cents"] == 900_000_000
    assert unit["available_pool_cents"] == 900_000_000
    assert_unit_balances(unit, reserved_cents=0, committed_cents=0, disbursed_cents=0,
                         refunded_cents=0)
    assert unit["version"] == 1
    assert_instant_equals(unit["created_at"], CLOCK)
    assert_instant_equals(unit["updated_at"], CLOCK)


def test_a_new_lab_space_is_available_with_no_installed_load():
    """A freshly registered room carries its envelope but nothing installed in it.

    PRD 3.5: "A room is created in status AVAILABLE with allocated_share_pct at 0,
    installed_power_kw at 0.00 and installed_fume_hoods at 0."

    Design: Corner/entities/corner_lab_space_create_defaults_available_with_zero_installed_load
    """
    fixtures.set_clock(CLOCK)
    space = fixtures.create_lab_space(building_code="CHEM", room_number="101",
                                      net_sq_ft=900, space_class="WET",
                                      power_kw_capacity=120.0, chilled_water_available=True,
                                      fume_hood_count=3, floor_load_psf=300)

    assert space["status"] == "AVAILABLE"
    assert space["allocated_share_pct"] == 0
    assert_power_kw(space["installed_power_kw"], 0)
    assert space["installed_fume_hoods"] == 0
    assert_power_kw(space["power_kw_capacity"], 120.00)
    assert space["fume_hood_count"] == 3
    assert space["floor_load_psf"] == 300
    assert space["chilled_water_available"] is True
    assert space["version"] == 1


def test_a_tranche_with_no_carryforward_stores_a_zero_cap():
    """An omitted cap on a NONE policy is stored as 0, and the tranche starts scheduled.

    PRD 3.2: "That percentage is carryforward_cap_pct, an integer between 0 and 100 that
    is required when carryforward_policy is CAPPED; a NONE or FULL tranche must not supply
    one and the server stores 0 for it."

    Design: Corner/entities/corner_tranche_create_defaults_scheduled_with_null_carryforward_cap
    """
    units = fixtures.setup_mini_units()
    faculty = fixtures.create_candidate_faculty(units["department"]["id"])
    package = fixtures.create_draft_package(faculty["id"], units["dean_office"]["id"],
                                            proposed_total_cents=20_000_000)
    tranche = fixtures.add_tranche(
        package["id"], category="EQUIPMENT", fiscal_year=2027, amount_cents=20_000_000,
        available_on=FY2027_AVAILABLE_ON, expires_on=FY2027_EXPIRES_ON,
        carryforward_policy="NONE",
    )

    assert tranche["carryforward_cap_pct"] == 0
    assert tranche["status"] == "SCHEDULED"
    assert tranche["opened_on"] is None
    assert_tranche_balances(tranche, available_balance_cents=20_000_000, encumbered_cents=0,
                            disbursed_cents=0, expired_cents=0, recaptured_cents=0,
                            carried_in_cents=0, carried_out_cents=0)
    assert_tranche_balance_identity(tranche)

    stored = fixtures.read_package(package["id"])
    assert stored["total_committed_cents"] == 20_000_000
    assert stored["total_available_cents"] == 20_000_000
    assert float(stored["spend_down_ratio"]) == 0.0


def test_a_package_with_no_tranches_reports_zero_rollups_and_derived_funders():
    """The headline figure is input only; every rollup comes from the tranche schedule.

    PRD 3.4: "Finally, spend_down_ratio is total_disbursed_cents plus
    total_encumbered_cents, divided by total_committed_cents, rounded half up to four
    decimal places, and defined as 0.0 when total_committed_cents is 0."

    Design: Corner/entities/corner_startup_package_computed_totals_derive_from_tranches_only
    """
    units = fixtures.setup_mini_units()
    faculty = fixtures.create_candidate_faculty(units["department"]["id"])
    package = fixtures.create_draft_package(faculty["id"], units["dean_office"]["id"],
                                            proposed_total_cents=20_000_000)

    assert package["proposed_total_cents"] == 20_000_000
    assert package["total_committed_cents"] == 0
    for field in ("total_encumbered_cents", "total_disbursed_cents", "total_available_cents",
                  "total_expired_cents", "total_recaptured_cents"):
        assert package[field] == 0, field
    assert float(package["spend_down_ratio"]) == 0.0
    assert package["negotiation_status"] == "DRAFT"
    assert package["spend_status"] == "NOT_YET_AVAILABLE"
    assert package["negotiation_round"] == 1
    assert package["counter_total_cents"] is None
    assert package["department_unit_id"] == units["department"]["id"]
    assert package["college_unit_id"] == units["college"]["id"]
    assert_unit_balances(fixtures.read_unit(units["department"]["id"]), reserved_cents=0)


def test_a_new_faculty_record_is_a_candidate_with_every_lifecycle_field_null():
    """The server, not the client, sets the appointment lifecycle fields.

    PRD 3.1: "The record is created in appointment_status CANDIDATE with retention_round at
    0, and activated_on, departure_intent, departure_effective_on, target_funding_unit_id
    and separated_on all null."

    Design: Corner/entities/corner_faculty_system_fields_are_server_generated
    """
    units = fixtures.setup_mini_units()
    faculty = fixtures.create_candidate_faculty(units["department"]["id"],
                                                full_name="Ada Reyes", rank="ASSISTANT",
                                                planned_start_date="2026-08-15")

    assert faculty["appointment_status"] == "CANDIDATE"
    for field in ("activated_on", "separated_on", "departure_intent",
                  "departure_effective_on", "target_funding_unit_id"):
        assert faculty[field] is None, field
    assert faculty["retention_round"] == 0
    assert faculty["version"] == 1
    assert_instant_equals(faculty["created_at"], CLOCK)
    assert_instant_equals(faculty["updated_at"], CLOCK)
    assert faculty["planned_start_date"] == "2026-08-15"


def test_reading_a_package_returns_the_stored_row_without_bumping_its_version():
    """A read is not a mutation, so the version the write left behind is what is read back.

    PRD 2.4: "version (integer): a counter that starts at 1 on creation and increments by
    exactly one on every mutation of that resource."

    Design: Corner/entities/corner_get_startup_package_returns_stored_row
    """
    scenario = fixtures.setup_draft_package()
    before = fixtures.read_package(scenario["package_id"])

    response = api_client.get_startup_package(scenario["package_id"], fixtures.DEAN_OFFICE)
    package = validate_success(response)

    assert package["id"] == scenario["package_id"]
    assert package["proposed_total_cents"] == 20_000_000
    assert package["spend_deadline_on"] == "2028-06-30"
    assert package["package_kind"] == "INITIAL"
    assert package["department_unit_id"] == scenario["department_id"]
    assert package["college_unit_id"] == scenario["college_id"]
    assert package["dean_unit_id"] == scenario["dean_office_id"]
    assert package["total_committed_cents"] == 20_000_000
    assert package["version"] == before["version"]


def test_the_tranche_listing_filters_before_it_paginates():
    """The category filter narrows the set the offset then walks, in creation order.

    PRD 2.3: "Unless a specific endpoint says otherwise, list results are ordered by the
    resource's creation timestamp, created_at, in ascending order."

    Design: Corner/entities/corner_list_package_tranches_with_category_filter_and_offset
    """
    units = fixtures.setup_mini_units()
    faculty = fixtures.create_candidate_faculty(units["department"]["id"])
    package = fixtures.create_draft_package(faculty["id"], units["dean_office"]["id"],
                                            proposed_total_cents=20_000_000)
    first = fixtures.add_tranche(package["id"], category="EQUIPMENT", fiscal_year=2027,
                                 amount_cents=9_000_000)
    second = fixtures.add_tranche(package["id"], category="EQUIPMENT", fiscal_year=2028,
                                  amount_cents=6_000_000,
                                  available_on="2027-07-01T00:00:00Z",
                                  expires_on="2028-07-01T00:00:00Z")
    third = fixtures.add_tranche(package["id"], category="RENOVATION", fiscal_year=2027,
                                 amount_cents=5_000_000)

    page, _ = validate_paginated(api_client.list_package_tranches(
        package["id"], fixtures.DEAN_OFFICE, {"category": "EQUIPMENT", "limit": 1, "offset": 1}
    ))
    assert [row["id"] for row in page] == [second["id"]]
    assert page[0]["amount_cents"] == 6_000_000
    assert page[0]["fiscal_year"] == 2028

    everything, _ = validate_paginated(api_client.list_package_tranches(
        package["id"], fixtures.DEAN_OFFICE
    ))
    assert [row["id"] for row in everything] == [first["id"], second["id"], third["id"]]


def test_reading_an_unknown_room_reports_the_room_specific_not_found_code():
    """The 404 names the entity type that failed to resolve.

    PRD 2.13: "ERR_SPACE_NOT_FOUND (404) - the LabSpace named by the path id, by space_id,
    or by install_space_id exists."

    Design: Corner/entities/corner_get_lab_space_unknown_id_returns_space_not_found
    """
    fixtures.set_clock(CLOCK)
    existing = fixtures.create_lab_space(building_code="CHEM", room_number="101")

    response = api_client.get_lab_space(NON_EXISTENT_UUID, fixtures.FACILITIES)
    validate_error(response, "ERR_SPACE_NOT_FOUND", expected_status=404)

    untouched = fixtures.read_space(existing["id"])
    assert untouched["status"] == "AVAILABLE"
    assert untouched["version"] == 1


def test_adding_a_tranche_to_an_unknown_package_reports_package_not_found():
    """The parent package in the path is resolved before the tranche body is honoured.

    PRD 2.13: "ERR_PACKAGE_NOT_FOUND (404) - the StartupPackage named by the path id, by
    package_id, or by superseded_package_id exists."

    Design: Corner/entities/corner_create_tranche_on_unknown_package_returns_package_not_found
    """
    units = fixtures.setup_mini_units()

    response = api_client.create_commitment_tranche(
        NON_EXISTENT_UUID,
        {"category": "EQUIPMENT", "fiscal_year": 2027, "amount_cents": 20_000_000,
         "available_on": FY2027_AVAILABLE_ON, "expires_on": FY2027_EXPIRES_ON,
         "carryforward_policy": "NONE"},
        fixtures.DEAN_OFFICE,
    )
    validate_error(response, "ERR_PACKAGE_NOT_FOUND", expected_status=404)
    assert_unit_balances(fixtures.read_unit(units["college"]["id"]), reserved_cents=0)


def test_a_package_created_without_a_spend_deadline_is_rejected():
    """A missing required field is a validation failure, not a defaulted value.

    PRD 2.13: "ERR_VALIDATION (400) - the body parses; every required input field is
    present and non-null; every enum value is a member of its declared set; integer cent
    fields are at least 0; fte is greater than 0 and at most 1.00; share percentages are
    within 1 through 100; dates are ISO 8601; and every interval is correctly ordered,
    meaning planned_start is at or before planned_end, effective_from is strictly before
    effective_to, available_on is strictly before expires_on, and start_date is at or
    before end_date."

    Design: Corner/entities/corner_create_startup_package_missing_required_spend_deadline_is_rejected
    """
    units = fixtures.setup_mini_units()
    faculty = fixtures.create_candidate_faculty(units["department"]["id"])

    response = api_client.create_startup_package(
        {"faculty_id": faculty["id"], "package_kind": "INITIAL",
         "dean_unit_id": units["dean_office"]["id"], "dept_share_pct": 45,
         "college_share_pct": 35, "dean_share_pct": 20,
         "proposed_total_cents": 20_000_000},
        fixtures.DEAN_OFFICE,
    )
    validate_error(response, "ERR_VALIDATION", expected_status=400)
    assert fixtures.read_faculty(faculty["id"])["appointment_status"] == "CANDIDATE"


def test_a_faculty_rank_outside_the_enum_is_rejected():
    """Rank is a closed enumeration of three values.

    PRD 3.1: "The dean's office supplies the candidate's full_name, the rank at which the
    appointment is offered - one of ASSISTANT, ASSOCIATE or FULL - the funding_unit_id of
    the home department, which must be a unit whose unit_type is DEPARTMENT, and the
    planned_start_date on which the appointment is expected to begin."

    Design: Corner/entities/corner_create_faculty_with_invalid_rank_enum_is_rejected
    """
    units = fixtures.setup_mini_units()

    response = api_client.create_faculty(
        {"full_name": "Ada Reyes", "rank": "DISTINGUISHED",
         "funding_unit_id": units["department"]["id"],
         "planned_start_date": "2026-08-15"},
        fixtures.DEAN_OFFICE,
    )
    validate_error(response, "ERR_VALIDATION", expected_status=400)

    listed, _ = validate_paginated(api_client.list_faculty(fixtures.DEAN_OFFICE))
    assert listed == []


def test_a_tranche_window_that_closes_before_it_opens_is_rejected():
    """The spending window must be a genuine forward interval.

    PRD 2.5: "expires_on must be strictly later than available_on."

    Design: Corner/entities/corner_create_tranche_with_inverted_window_is_rejected
    """
    units = fixtures.setup_mini_units()
    faculty = fixtures.create_candidate_faculty(units["department"]["id"])
    package = fixtures.create_draft_package(faculty["id"], units["dean_office"]["id"],
                                            proposed_total_cents=20_000_000)

    response = api_client.create_commitment_tranche(
        package["id"],
        {"category": "EQUIPMENT", "fiscal_year": 2027, "amount_cents": 20_000_000,
         "available_on": "2027-07-01T00:00:00Z", "expires_on": "2026-07-01T00:00:00Z",
         "carryforward_policy": "NONE"},
        fixtures.DEAN_OFFICE,
    )
    validate_error(response, "ERR_VALIDATION", expected_status=400)
    assert fixtures.read_package(package["id"])["total_committed_cents"] == 0


def test_a_ledger_row_carries_no_updated_at_and_no_version():
    """The append-only ledger row is the one entity without the full audit triple.

    PRD 2.4: "The one exception is SpendTransaction. Ledger rows are append-only and never
    edited after they are written, so a SpendTransaction carries only id and created_at:
    both updated_at and version are absent from its representation."

    Design: Corner/entities/corner_spend_transaction_is_immutable_and_versionless
    """
    scenario = fixtures.setup_mini_active()
    space = fixtures.create_lab_space(building_code="BIOL", room_number="12")
    order = fixtures.setup_placed_order(scenario["package_id"], space["id"],
                                        quoted_cents=12_000_010)
    tranche_id = scenario["tranche"]["equipment"]["id"]

    rows, _ = validate_paginated(api_client.list_tranche_spend_transactions(
        tranche_id, fixtures.DEAN_OFFICE, {"kind": "ENCUMBRANCE"}
    ))
    assert len(rows) == 1
    row = rows[0]
    assert row["kind"] == "ENCUMBRANCE"
    assert row["amount_cents"] == 12_000_010
    assert row["tranche_id"] == tranche_id
    assert row["source_kind"] == "EQUIPMENT_ORDER"
    assert row["source_id"] == order["id"]
    assert row["reverses_transaction_id"] is None
    assert "updated_at" not in row
    assert "version" not in row
    assert_instant_equals(row["created_at"], CLOCK)
    assert_row_shares(row, 5_400_005, 4_200_003, 2_400_002)


def test_an_order_aimed_at_an_unknown_room_reports_space_not_found():
    """The install room named in the body is resolved like a path identifier.

    PRD 2.11: "Identifiers arriving in a request body or as a query filter are
    checked with the same rigour as path identifiers, and the not-found code is
    specific to the entity type being resolved: ERR_FACULTY_NOT_FOUND for a faculty
    member, ERR_PACKAGE_NOT_FOUND for a package, ERR_TRANCHE_NOT_FOUND for a
    commitment tranche, ERR_SPACE_NOT_FOUND for a laboratory room"

    Design: Corner/entities/corner_create_equipment_order_with_unknown_space_returns_space_not_found
    """
    scenario = fixtures.setup_mini_active()

    response = api_client.create_equipment_order(
        {"package_id": scenario["package_id"], "install_space_id": NON_EXISTENT_UUID,
         "vendor_name": "Agilent", "item_description": "HPLC", "quoted_cents": 5_000_000,
         "lead_time_days": 30, "required_power_kw": 8.0, "requires_chilled_water": False,
         "required_fume_hoods": 0, "required_floor_load_psf": 100},
        fixtures.DEAN_OFFICE,
    )
    validate_error(response, "ERR_SPACE_NOT_FOUND", expected_status=404)
    assert_tranche_balances(fixtures.read_tranche(scenario["tranche"]["equipment"]["id"]),
                            encumbered_cents=0, available_balance_cents=20_000_000)


def test_a_faculty_member_cannot_be_homed_in_a_college_unit():
    """A unit that resolves but has the wrong type fails the slot check, not the id check.

    PRD 2.11: "ERR_RESOURCE_NOT_FOUND is also the code used when a referenced funding unit
    exists but its unit_type does not match the slot it was used in - a
    department_unit_id that names a COLLEGE, a dean_unit_id that names a DEPARTMENT, and so
    on."

    Design: Corner/entities/corner_create_faculty_in_college_unit_returns_resource_not_found
    """
    units = fixtures.setup_mini_units()

    response = api_client.create_faculty(
        {"full_name": "Ada Reyes", "rank": "ASSISTANT",
         "funding_unit_id": units["college"]["id"], "planned_start_date": "2026-08-15"},
        fixtures.DEAN_OFFICE,
    )
    validate_error(response, "ERR_RESOURCE_NOT_FOUND", expected_status=404)

    accepted = fixtures.create_candidate_faculty(units["department"]["id"])
    assert accepted["funding_unit_id"] == units["department"]["id"]
