"""Entity shapes: declared defaults, computed fields, envelopes and body foreign keys."""

from test_helpers import (
    ANALYST_DRAFTER,
    COMPLIANCE_SCREENER,
    NON_EXISTENT_UUID,
    PLATFORM_ADMIN,
    VALET_OPS_MANAGER,
    ApiErrorId,
    api_client,
    assert_common_fields,
    assert_instants_equal,
    factories,
    fixtures,
    is_valid_uuid,
    make_property_manager_headers,
    make_valet_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


# --------------------------------------------------------------------------
# Creation defaults and computed zeros
# --------------------------------------------------------------------------
def test_registering_a_community_applies_the_declared_defaults_and_zeros():
    """Three inputs are enough; everything else is defaulted or computed.

    PRD 3.1: "An optional `compactor_capacity_lbs` records the rated capacity of
    the on-site compactor; it defaults to 6000 pounds and, when supplied, must be
    at least 1000."

    PRD 3.1: "A freshly registered community is born in `status` `ONBOARDING`
    with `active_contract_id` null, `escalation_level` 0,
    `pending_fine_revenue_cents` 0 and `delinquent_resident_count` 0."

    Design: Corner/entities/property_creation_applies_declared_defaults_and_computed_zeros
    """
    fixtures.set_clock("2026-09-01T00:00:00Z")

    prop = validate_success(
        api_client.create_property(
            {"name": "Cedar Ridge", "unit_count": 4, "market_code": "ATL"},
            PLATFORM_ADMIN,
        ),
        expected_status=201,
    )

    assert prop["name"] == "Cedar Ridge"
    assert prop["unit_count"] == 4
    assert prop["market_code"] == "ATL"
    assert prop["compactor_capacity_lbs"] == 6000
    assert prop["status"] == "ONBOARDING"
    assert prop["active_contract_id"] is None
    assert prop["escalation_level"] == 0
    assert prop["pending_fine_revenue_cents"] == 0
    assert prop["delinquent_resident_count"] == 0
    assert_common_fields(prop, "Property")
    assert prop["version"] == 1


def test_a_new_resident_defaults_to_passthrough_enabled_and_a_clean_ledger():
    """The optional pass-through flag defaults true and the ledger starts empty.

    PRD 3.2: "A new resident is born with `status` `ACTIVE`,
    `collections_status` `CURRENT`, `fines_outstanding_cents` 0,
    `fines_assessed_this_period_cents` 0 and `move_out_date` null."

    Design: Corner/entities/resident_create_defaults_fee_passthrough_enabled_true
    """
    fixtures.set_clock("2026-09-01T00:00:00Z")
    prop = fixtures.create_property(name="Cedar Ridge", unit_count=4)

    resident = validate_success(
        api_client.create_resident(
            prop["id"],
            {"unit_number": 101, "full_name": "Rosa One", "move_in_date": "2026-08-01"},
            make_property_manager_headers(prop["id"]),
        ),
        expected_status=201,
    )

    assert resident["fee_passthrough_enabled"] is True
    assert resident["status"] == "ACTIVE"
    assert resident["collections_status"] == "CURRENT"
    assert resident["move_out_date"] is None
    assert resident["fines_outstanding_cents"] == 0
    assert resident["fines_assessed_this_period_cents"] == 0
    assert resident["property_id"] == prop["id"], (
        "the parent is taken from the path, never from the body"
    )


# --------------------------------------------------------------------------
# Retrieval returns exactly what the write chain stored
# --------------------------------------------------------------------------
def test_reading_a_contractor_returns_its_stored_onboarding_state():
    """Document intake has moved the applicant on, but nothing else has changed.

    PRD 3.3: "The new record is born with `onboarding_status` `APPLIED`,
    `classification` `UNCLASSIFIED`, `classification_basis` null, `control_score`
    0, `observed_weekly_hours` 0, `tax_form_type` null,
    `direct_deposit_on_file` false, `background_checked_by_user_id` null and
    `deactivation_reason` null."

    Design: Corner/entities/contractor_retrieval_returns_stored_onboarding_state
    """
    fixtures.set_clock("2026-09-01T00:00:00Z")
    contractor = fixtures.create_contractor(legal_name="Val Ito")
    fixtures.submit_documents(contractor["id"], "W9", True)

    stored = validate_success(
        api_client.get_contractor(contractor["id"], COMPLIANCE_SCREENER)
    )

    assert stored["legal_name"] == "Val Ito"
    assert stored["onboarding_status"] == "BACKGROUND_PENDING"
    assert stored["classification"] == "UNCLASSIFIED"
    assert stored["tax_form_type"] == "W9"
    assert stored["direct_deposit_on_file"] is True
    assert stored["control_score"] == 0
    assert float(stored["observed_weekly_hours"]) == 0.0
    assert stored["background_checked_by_user_id"] is None
    assert stored["classification_basis"] is None


# --------------------------------------------------------------------------
# Listing envelope
# --------------------------------------------------------------------------
def test_the_resident_roster_paginates_with_a_total_count_and_a_has_more_flag():
    """Two pages over three rows, with the total counted before pagination.

    PRD 2.3: "List responses carry `limit`, `offset`, `total_count` and
    `has_more` in the `meta` object of the envelope, where `total_count` is the
    number of rows matching the filters before pagination is applied and
    `has_more` indicates whether rows remain beyond the current page."

    Design: Corner/entities/resident_listing_paginates_with_total_count_and_has_more
    """
    fixtures.set_clock("2026-09-01T00:00:00Z")
    prop = fixtures.create_property(name="Cedar Ridge", unit_count=4)
    for unit in (101, 102, 103):
        fixtures.create_resident(prop["id"], unit, move_in_date="2026-08-01")
    headers = make_property_manager_headers(prop["id"])

    first_rows, first_meta = validate_paginated(
        api_client.list_residents(
            headers, params={"property_id": prop["id"], "limit": 2, "offset": 0}
        )
    )
    second_rows, second_meta = validate_paginated(
        api_client.list_residents(
            headers, params={"property_id": prop["id"], "limit": 2, "offset": 2}
        )
    )

    assert len(first_rows) == 2
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True
    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0
    assert len(second_rows) == 1
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False
    assert second_meta["offset"] == 2
    ids = [row["id"] for row in first_rows] + [row["id"] for row in second_rows]
    assert len(set(ids)) == 3, "no row may repeat across the two pages"


# --------------------------------------------------------------------------
# Computed and system-stamped fields ignore client input
# --------------------------------------------------------------------------
def test_a_client_supplied_route_coverage_count_is_ignored():
    """The count is derived from the closed range, so 99 is discarded.

    PRD 3.5: "A new route is born `ASSIGNED`, with `accepted_at` and
    `completed_at` null, `abandon_reason` null, `scan_count` 0, and
    `unit_coverage_count` set to the number of doors in the range: the last door
    minus the first door plus one."

    Design: Corner/entities/route_assignment_coverage_count_is_computed_input_ignored
    """
    world = fixtures.build_active_community(
        name="Cedar Ridge", unit_count=4, resident_units=()
    )
    night = fixtures.schedule_night(world["contract"]["id"], "2026-09-01")

    route = validate_success(
        api_client.create_route_assignment(
            night["id"],
            factories.route_payload(
                world["contractor"]["id"],
                101,
                104,
                night["version"],
                unit_coverage_count=99,
            ),
            VALET_OPS_MANAGER,
        ),
        expected_status=201,
    )

    assert route["unit_coverage_count"] == 4
    assert route["status"] == "ASSIGNED"
    assert route["scan_count"] == 0
    assert route["accepted_at"] is None
    assert route["completed_at"] is None
    assert fixtures.read_night(night["id"])["assigned_unit_coverage_count"] == 4


def test_a_scans_identity_and_timestamps_come_from_the_server_not_the_body():
    """The client's id, scanned_at and service_night_id are all discarded.

    PRD 2.7: "The clock is the source of `accepted_at`, `completed_at`,
    `scanned_at`, `reported_at`, `acknowledged_at`, `escalated_at` and
    `resolved_at`, the basis of `ack_deadline_at`, the reference point of the
    ninety-day offense lookback and the seven-day observed-hours window, and the
    definition of "the current billing period" for the monthly fine cap."

    Design: Corner/entities/service_scan_system_stamped_fields_input_ignored
    """
    world = fixtures.build_scan_ready_night(
        name="Cedar Ridge",
        unit_count=4,
        resident_units=(101,),
        resident_kwargs={101: {"move_in_date": "2026-08-01"}},
        service_date="2026-09-01",
    )
    fixtures.set_clock("2026-09-01T19:30:00Z")

    scan = validate_success(
        api_client.record_scan(
            world["route"]["id"],
            factories.scan_payload(
                world["residents"][101]["id"],
                "SERVICED",
                "TRASH_BIN",
                id="11111111-1111-4111-8111-111111111111",
                scanned_at="2020-01-01T00:00:00.000Z",
                service_night_id=NON_EXISTENT_UUID,
            ),
            make_valet_headers(world["contractor"]["id"]),
        ),
        expected_status=201,
    )

    assert is_valid_uuid(scan["id"])
    assert scan["id"] != "11111111-1111-4111-8111-111111111111"
    assert_instants_equal(scan["scanned_at"], "2026-09-01T19:30:00.000Z", "scanned_at")
    assert scan["service_night_id"] == world["night"]["id"]
    assert scan["tag_status"] == "NONE"
    assert scan["offense_ordinal"] == 0


# --------------------------------------------------------------------------
# Required fields, enum members and integer ranges
# --------------------------------------------------------------------------
def test_a_contract_draft_without_the_per_unit_fee_is_a_shape_violation():
    """A required input with no declared default cannot be omitted.

    PRD 2.5: "**Body shape.** Every required field present and non-null; every
    enum value a declared member; every integer inside its declared range; every
    date a well-formed `YYYY-MM-DD`; every instant a well-formed ISO 8601 UTC
    value; `unit_from` no greater than `unit_to`; `limit` between 1 and 100
    inclusive and `offset` at least 0 — otherwise `ERR_INVALID_REQUEST` (422)."

    Design: Corner/entities/contract_create_missing_required_fee_returns_invalid_request
    """
    fixtures.set_clock("2026-09-01T00:00:00Z")
    prop = fixtures.create_property(name="Cedar Ridge", unit_count=4)

    response = api_client.create_contract(
        prop["id"],
        {
            "property_revenue_share_bps": 1500,
            "service_night_days": ["SUN", "MON", "TUE", "WED", "THU"],
            "effective_from": "2026-09-01",
            "effective_to": "2027-08-31",
            "sla_missed_threshold_bps": 1000,
        },
        ANALYST_DRAFTER,
    )

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 422)
    assert fixtures.list_contracts({"property_id": prop["id"]}) == []
    unchanged = fixtures.read_property(prop["id"])
    assert unchanged["status"] == "ONBOARDING"
    assert unchanged["active_contract_id"] is None


def test_an_undeclared_weekday_and_an_out_of_range_share_are_both_refused():
    """FUNDAY is not a weekday and 12000 basis points is outside the declared range.

    PRD 3.1: "`service_night_days`, a non-empty array of between one and seven
    distinct weekday names drawn from `SUN`, `MON`, `TUE`, `WED`, `THU`, `FRI`
    and `SAT`"

    Design: Corner/entities/contract_create_with_illegal_weekday_enum_returns_invalid_request
    """
    fixtures.set_clock("2026-09-01T00:00:00Z")
    prop = fixtures.create_property(name="Cedar Ridge", unit_count=4)

    bad_weekday = api_client.create_contract(
        prop["id"],
        factories.contract_payload(service_night_days=["SUN", "FUNDAY"]),
        ANALYST_DRAFTER,
    )
    bad_share = api_client.create_contract(
        prop["id"],
        factories.contract_payload(
            property_revenue_share_bps=12000, service_night_days=["SUN", "MON"]
        ),
        ANALYST_DRAFTER,
    )

    validate_error(bad_weekday, ApiErrorId.ERR_INVALID_REQUEST.value, 422)
    validate_error(bad_share, ApiErrorId.ERR_INVALID_REQUEST.value, 422)
    assert fixtures.list_contracts({"property_id": prop["id"]}) == []


# --------------------------------------------------------------------------
# Path identifiers and body foreign keys
# --------------------------------------------------------------------------
def test_reading_an_unknown_contractor_is_a_typed_404_not_an_empty_success():
    """The error envelope names the entity that failed to resolve.

    PRD 2.5: "**Path existence.** Every identifier in the path resolves, left to
    right — otherwise the corresponding 404 code above. Applies to every endpoint
    that has a path identifier."

    Design: Corner/entities/contractor_get_with_unknown_id_returns_contractor_not_found
    """
    fixtures.set_clock("2026-09-01T00:00:00Z")

    response = api_client.get_contractor(NON_EXISTENT_UUID, VALET_OPS_MANAGER)

    body = validate_error(response, ApiErrorId.ERR_CONTRACTOR_NOT_FOUND.value, 404)
    assert isinstance(body["message"], str) and body["message"].strip()
    assert fixtures.list_contractors() == []


def test_creating_a_resident_under_an_unknown_community_resolves_the_path_first():
    """The path identifier is checked before the body is even considered.

    PRD 2.5: "The practical consequence of this ordering is worth spelling out. A
    `Valet` who sends a malformed scan body for a resident belonging to another
    property receives the shape error, not the cross-property error, because rung
    5 precedes rung 7."

    Design: Corner/entities/resident_create_under_unknown_property_returns_property_not_found
    """
    fixtures.set_clock("2026-09-01T00:00:00Z")

    response = api_client.create_resident(
        NON_EXISTENT_UUID,
        factories.resident_payload(101, full_name="Rosa One", move_in_date="2026-08-01"),
        PLATFORM_ADMIN,
    )

    validate_error(response, ApiErrorId.ERR_PROPERTY_NOT_FOUND.value, 404)
    assert fixtures.list_residents() == []


def test_scanning_another_communitys_resident_is_a_cross_property_reference():
    """Both rows exist, but they belong to different communities.

    PRD 2.5: "**Aggregate scope of a body foreign key.** The scanned resident's
    property must be the same property as the one behind the night's contract —
    otherwise `ERR_CROSS_PROPERTY_REFERENCE` (409). Applies to scan recording
    only."

    Design: Corner/entities/scan_of_resident_from_another_property_rejected_cross_property
    """
    fixtures.set_clock("2026-09-01T00:00:00Z")
    other = fixtures.create_property(name="Cedar Ridge", unit_count=4)
    outsider = fixtures.create_resident(
        other["id"], 101, full_name="Rosa One", move_in_date="2026-08-01"
    )
    world = fixtures.build_scan_ready_night(
        name="Birch Row",
        unit_count=4,
        resident_units=(),
        service_date="2026-09-01",
    )

    response = api_client.record_scan(
        world["route"]["id"],
        factories.scan_payload(outsider["id"], "SERVICED", "TRASH_BIN"),
        make_valet_headers(world["contractor"]["id"]),
    )

    validate_error(response, ApiErrorId.ERR_CROSS_PROPERTY_REFERENCE.value, 409)
    assert fixtures.list_scans({"route_assignment_id": world["route"]["id"]}) == []
    route = fixtures.read_route(world["route"]["id"])
    assert route["status"] == "ACCEPTED"
    assert route["scan_count"] == 0
    assert fixtures.read_night(world["night"]["id"])["verification_status"] == "SCHEDULED"
