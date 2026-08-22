"""Record identity, server-set defaults, foreign keys, code uniqueness and the
list envelope across the plant record's reference entities."""

import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_load_position,
    api_client,
    assert_customer,
    assert_dose_audit,
    create_chamber_payload,
    create_customer,
    create_customer_payload,
    create_cycle,
    create_cycle_payload,
    create_lot,
    create_permit,
    create_product,
    create_product_payload,
    create_qualified_qualification,
    disposition_adverse_event,
    get_cycle,
    get_lot,
    is_valid_uuid,
    make_customer_rep_headers,
    officer,
    operator,
    report_adverse_event,
    set_clock,
    setup_reference_data,
    setup_released_lot,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["regulatory_admin_headers"]
UNKNOWN_UUID = "00000000-0000-4000-8000-000000000000"


def test_create_customer_returns_201_with_server_defaults():
    """PRD 4: "Operations that mint a new resource — registering a customer, a
    product, a permit, a chamber, a recipe, a qualification, a dose audit, a
    lot, a cycle, a load-map slot, an indicator or an aeration record — return
    `201 Created`."
    PRD 3.1: "A customer also carries a `status`, supplied optionally at
    registration and defaulting to `ACTIVE`, whose only other value is
    `SUSPENDED`."
    PRD 3.1: "Each customer record also exposes `open_lot_count`, a
    server-maintained integer that starts at 0 and reflects how many of that
    customer's lots are still live in the facility"
    PRD 2.4: "Every resource the API mints carries an `id`: a server-generated
    UUID with no type prefix and no client control over its value."
    PRD 2.4: "All resources except one also carry `updated_at`, an ISO 8601 UTC
    timestamp refreshed on every persisted change to the row, and `version`, an
    integer that begins at 1 when the row is created and increases by exactly
    one on every persisted mutation of that row."
    PRD 2.2: "The `api_request_id` is a server-generated unique identifier for
    the request that starts with `req_`."

    Design: Corner/entities/corner_create_customer_returns_201_with_server_defaults
    """
    response = api_client.create_customer(create_customer_payload(), ADMIN)

    data = validate_success(response, 201)
    assert response.json()["response_type"] == "object"
    assert data["status"] == "ACTIVE"
    assert data["open_lot_count"] == 0
    assert data["version"] == 1
    assert is_valid_uuid(data["id"]), "the id is a bare UUID with no type prefix"
    assert_customer(data)
    meta = response.json()["meta"]
    assert meta["api_request_id"].startswith("req_")
    assert isinstance(meta["api_request_timestamp"], str)


def test_get_customer_returns_the_stored_row():
    """PRD 3.1: "A `RegulatoryAdmin` registers one with a legal `name`, a short
    `account_code` of between 1 and 32 characters that must be unique across
    all customers as an exact, case-sensitive string, and a
    `contracted_modalities` list."
    PRD 2.2: "The `data` field contains the resource object or an array of
    resource objects."

    Design: Corner/entities/corner_get_customer_returns_stored_row
    """
    set_clock("2026-08-10T00:00:00Z")
    customer = create_customer(
        name="Acme Medical", account_code="ACME-01", contracted_modalities=["ETO", "GAMMA"]
    )

    data = validate_success(api_client.get_customer(customer["id"], ADMIN))

    assert data["account_code"] == "ACME-01"
    assert data["name"] == "Acme Medical"
    assert data["contracted_modalities"] == ["ETO", "GAMMA"]
    assert data["version"] == 1


def test_list_customers_returns_the_pagination_envelope():
    """PRD 2.3: "`limit` sets the maximum number of rows returned; it defaults
    to 10, may not be smaller than 1, and may not be larger than 100."
    PRD 2.3: "The `meta` object of every list response carries `limit`,
    `offset`, `total_count` and `has_more`."

    Design: Corner/entities/corner_list_customers_returns_pagination_envelope
    """
    set_clock("2026-08-10T00:00:00Z")
    create_customer(account_code="ACME-01")
    create_customer(account_code="BETA-02")

    response = api_client.list_customers(ADMIN, params={"limit": 1, "offset": 0})

    rows, meta = validate_paginated(response)
    assert response.json()["response_type"] == "array"
    assert meta["total_count"] == 2
    assert meta["limit"] == 1
    assert meta["offset"] == 0
    assert meta["has_more"] is True
    assert len(rows) == 1


def test_get_customer_with_an_unknown_id_returns_customer_not_found():
    """PRD 2.7: "Every identifier in the URL is resolved left to right, and
    each resource type raises its own 404: `ERR_CUSTOMER_NOT_FOUND` for a
    customer segment"

    Design: Corner/entities/corner_get_customer_unknown_id_returns_not_found
    """
    response = api_client.get_customer(UNKNOWN_UUID, ADMIN)

    validate_error(response, ApiErrorId.ERR_CUSTOMER_NOT_FOUND)
    assert response.json()["response_type"] == "error"


def test_create_product_without_pallet_mass_is_rejected():
    """PRD 2.7: "**Payload schema.** On every write, required fields are
    present, types are correct, enum members are recognised and numeric ranges
    hold"
    PRD 3.1: "`pallet_mass_kg` is the mass of one shipping pallet of the
    product in kilograms and must be greater than zero"

    Design: Corner/entities/corner_create_product_missing_required_pallet_mass_rejected
    """
    set_clock("2026-08-10T00:00:00Z")
    customer = create_customer()
    payload = create_product_payload(customer["id"])
    payload.pop("pallet_mass_kg")

    response = api_client.create_product(payload, ADMIN)

    validate_error(response, ApiErrorId.ERR_VALIDATION)
    _, meta = validate_paginated(
        api_client.list_customer_products(customer["id"], ADMIN)
    )
    assert meta["total_count"] == 0, "nothing was persisted"


def test_product_created_without_requires_aeration_defaults_to_true():
    """PRD 3.1: "`requires_aeration` is a boolean defaulting to true; when it
    is true and the goods are processed in an ethylene-oxide chamber, lots of
    that product acquire a degassing obligation the moment their cycle
    completes."
    PRD 3.1: "Finally a product carries a `status`, optional at creation and
    defaulting to `ACTIVE`, whose only other value is `DISCONTINUED`."

    Design: Corner/entities/corner_create_product_omitting_requires_aeration_applies_default_true
    """
    set_clock("2026-08-10T00:00:00Z")
    customer = create_customer()
    payload = create_product_payload(customer["id"])
    payload.pop("requires_aeration")

    data = validate_success(api_client.create_product(payload, ADMIN), 201)

    assert data["requires_aeration"] is True
    assert data["status"] == "ACTIVE"
    assert data["customer_id"] == customer["id"]


def test_create_chamber_with_an_unrecognised_modality_is_rejected():
    """PRD 2.7: "**Payload schema.** On every write, required fields are
    present, types are correct, enum members are recognised and numeric ranges
    hold"
    PRD 3.2: "A **Chamber** is commissioned under exactly one permit,
    identified by `permit_id`, and carries a `chamber_code` of 1 to 32
    characters unique across the facility, a `modality` of `ETO`, `GAMMA` or
    `EBEAM`, a `pallet_capacity` of at least one pallet, a `turnaround_minutes`
    value of zero or more expressing the purge and cooldown buffer that must
    follow every dwell, and an `abatement_efficiency_pct` between 0 and 100
    inclusive describing how much of the raw ethylene-oxide charge the
    chamber's abatement train destroys."

    Design: Corner/entities/corner_create_chamber_invalid_modality_enum_rejected
    """
    set_clock("2026-08-10T00:00:00Z")
    permit = create_permit()

    response = api_client.create_chamber(
        create_chamber_payload(permit["id"], "XRAY", chamber_code="CH-1"),
        ADMIN,
    )

    validate_error(response, ApiErrorId.ERR_VALIDATION)


def test_create_cycle_with_equal_start_and_end_is_rejected():
    """PRD 2.7: "**Payload schema.** On every write, required fields are
    present, types are correct, enum members are recognised and numeric ranges
    hold — `pallet_count` at least 1, `positives` between 0 and
    `samples_tested` inclusive, `samples_tested` exactly 100,
    `abatement_efficiency_pct` between 0 and 100 inclusive, `scheduled_end_at`
    strictly later than `scheduled_start_at`"
    PRD 3.4: "Chamber time is booked as a **Cycle** by a `CycleOperator`, who
    supplies the `chamber_id` of the chamber to occupy, the `recipe_id` of the
    approved recipe to run, a `cycle_code` of 1 to 32 characters unique across
    the facility, and the dwell window as `scheduled_start_at` and
    `scheduled_end_at`, the latter strictly later than the former."

    Design: Corner/entities/corner_create_cycle_end_not_after_start_rejected
    """
    env = setup_reference_data(qualify=False)

    response = api_client.create_cycle(
        create_cycle_payload(
            env["chamber"]["id"],
            env["recipe"]["id"],
            scheduled_start_at="2026-08-11T06:00:00Z",
            scheduled_end_at="2026-08-11T06:00:00Z",
        ),
        operator(),
    )

    validate_error(response, ApiErrorId.ERR_VALIDATION)
    _, meta = validate_paginated(
        api_client.list_cycles(operator(), params={"chamber_id": env["chamber"]["id"]})
    )
    assert meta["total_count"] == 0


def test_dose_audit_is_an_immutable_record_without_version():
    """PRD 2.4: "The single exception is the `DoseAudit`: a dose audit is an
    immutable laboratory record, so it carries only `id` and `created_at` — it
    has no `updated_at` field and no `version` field at all."

    Design: Corner/entities/corner_dose_audit_is_append_only_without_version_field
    """
    env = setup_reference_data(qualify=False)

    response = api_client.create_dose_audit(
        env["qualification"]["id"],
        {
            "performed_at": "2026-08-05T00:00:00Z",
            "samples_tested": 100,
            "positives": 0,
            "verification_dose_kgy_applied": 12.5,
        },
        ADMIN,
    )

    data = validate_success(response, 201)
    assert data["outcome"] == "PASS"
    assert_dose_audit(data)
    assert "version" not in data
    assert "updated_at" not in data

    audits, meta = validate_paginated(
        api_client.list_dose_audits(env["qualification"]["id"], ADMIN)
    )
    assert meta["total_count"] == 1
    assert audits[0]["id"] == data["id"]


def test_create_product_with_an_unknown_customer_returns_customer_not_found():
    """PRD 2.7: "**Body foreign keys.** Every foreign key supplied in a request
    body must resolve, each raising its own 404: `customer_id` raises
    `ERR_CUSTOMER_NOT_FOUND`, `product_id` raises `ERR_PRODUCT_NOT_FOUND`,
    `permit_id` raises `ERR_PERMIT_NOT_FOUND`, `recipe_id` raises
    `ERR_RECIPE_NOT_FOUND`, `chamber_id` raises `ERR_CHAMBER_NOT_FOUND` and
    `lot_id` raises `ERR_LOT_NOT_FOUND`."

    Design: Corner/entities/corner_create_product_with_unknown_customer_returns_customer_not_found
    """
    set_clock("2026-08-10T00:00:00Z")

    response = api_client.create_product(create_product_payload(UNKNOWN_UUID), ADMIN)

    validate_error(response, ApiErrorId.ERR_CUSTOMER_NOT_FOUND)


def test_load_position_list_resolves_both_the_cycle_and_the_lot_direction():
    """PRD 2.3: "The load-position list accepts `cycle_id` and `lot_id`."
    PRD 3.5: "The `CycleOperator` builds the map one **LoadPosition** at a
    time, each request naming the `lot_id` of the lot to place, a
    `position_index` identifying the physical slot, which must be at least 1
    and no greater than the chamber's `pallet_capacity` and must not already be
    used by another position on the same cycle, a `zone` describing the slot's
    geometric dose exposure — one of `MIN_DOSE`, `MAX_DOSE`, `INTERIOR` or
    `EDGE` — a `pallet_count` of at least one pallet, and the
    `expected_cycle_version` handle described in §2.6."

    Design: Corner/entities/corner_load_position_junction_links_one_cycle_to_two_lots
    """
    env = setup_reference_data()
    product_b = create_product(
        env["customer"]["id"], product_code="P2", pallet_mass_kg=90.0, pallet_volume_m3=0.8
    )
    create_qualified_qualification(product_b["id"], env["recipe"]["id"])
    lot_a = create_lot(env["customer"]["id"], env["product"]["id"], lot_code="L-P1")
    lot_b = create_lot(env["customer"]["id"], product_b["id"], lot_code="L-P2")
    cycle = create_cycle(env["chamber"]["id"], env["recipe"]["id"])
    position_a = add_load_position(
        cycle["id"], lot_a["id"], position_index=1, zone="MIN_DOSE", pallet_count=1
    )
    position_b = add_load_position(
        cycle["id"], lot_b["id"], expected_cycle_version=position_a["cycle_version_after"],
        position_index=2, zone="INTERIOR", pallet_count=1,
    )

    by_cycle, cycle_meta = validate_paginated(
        api_client.list_load_positions(operator(), params={"cycle_id": cycle["id"]})
    )
    by_lot, lot_meta = validate_paginated(
        api_client.list_load_positions(operator(), params={"lot_id": lot_b["id"]})
    )

    assert cycle_meta["total_count"] == 2
    assert {row["id"] for row in by_cycle} == {position_a["id"], position_b["id"]}
    assert lot_meta["total_count"] == 1
    assert by_lot[0]["id"] == position_b["id"]

    stored_cycle = get_cycle(cycle["id"])
    assert stored_cycle["loaded_pallet_count"] == 2
    assert stored_cycle["load_density_g_per_cm3"] == pytest.approx(0.1050, abs=1e-9)


def test_scrap_disposition_mints_no_successor_lot():
    """PRD 3.9: "`SCRAP` is available when the subject lot is `RELEASED` or in
    `QUARANTINE`. The event moves `REPORTED → SCRAP_APPROVED`, the lot moves
    `QUARANTINE → SCRAPPED` or `RELEASED → SCRAPPED` as the case may be, and
    its `schedulable` flag is cleared to false so the physical goods can never
    re-enter a load map."
    PRD 3.4: "`parent_lot_id` is populated only on a successor minted by the
    re-sterilization pathway of §3.9."
    PRD 2.3: "The lot list accepts `customer_id`, `product_id`,
    `parent_lot_id`, `status` and `residual_status`, the last of which filters
    on the lot's second, independent state dimension."

    Design: Corner/entities/corner_lot_parent_lot_id_self_reference_filter_returns_successor
    """
    env = setup_released_lot()
    event = report_adverse_event(
        env["lot"]["id"],
        reporter_headers=make_customer_rep_headers(env["customer"]["id"]),
        event_type="PACKAGING_BREACH",
        severity="LOW",
        description="Outer carton seal breached in transit",
    )

    dispositioned = disposition_adverse_event(event["id"], "SCRAP")

    assert dispositioned["status"] == "SCRAP_APPROVED"
    assert dispositioned["disposition"] == "SCRAP"
    lot = get_lot(env["lot"]["id"])
    assert lot["status"] == "SCRAPPED"
    assert lot["schedulable"] is False
    assert lot["parent_lot_id"] is None

    _, meta = validate_paginated(
        api_client.list_lots(officer(), params={"parent_lot_id": env["lot"]["id"]})
    )
    assert meta["total_count"] == 0


def test_duplicate_account_code_is_rejected():
    """PRD 2.7: "**Code uniqueness.** `account_code`, `chamber_code`,
    `recipe_code`, `cycle_code` and `serial_code` are unique across the whole
    facility; `product_code` and `lot_code` are unique within their owning
    `customer_id`. A collision yields `ERR_DUPLICATE_CODE` (HTTP 409) and is
    checked when creating a customer, a product, a chamber, a cycle recipe, a
    lot, a cycle or an indicator."

    Design: Corner/entities/corner_duplicate_account_code_rejected
    """
    set_clock("2026-08-10T00:00:00Z")
    create_customer(account_code="ACME-01")

    response = api_client.create_customer(
        create_customer_payload(
            name="Acme Medical Duplicate",
            account_code="ACME-01",
            contracted_modalities=["GAMMA"],
        ),
        ADMIN,
    )

    validate_error(response, ApiErrorId.ERR_DUPLICATE_CODE)
    _, meta = validate_paginated(api_client.list_customers(ADMIN))
    assert meta["total_count"] == 1


def test_lot_list_filters_by_status_and_paginates_together():
    """PRD 2.3: "The lot list accepts `customer_id`, `product_id`,
    `parent_lot_id`, `status` and `residual_status`, the last of which filters
    on the lot's second, independent state dimension."
    PRD 2.3: "The `meta` object of every list response carries `limit`,
    `offset`, `total_count` and `has_more`."

    Design: Corner/entities/corner_list_lots_filtered_by_status_and_paginated
    """
    env = setup_reference_data()
    create_lot(env["customer"]["id"], env["product"]["id"], lot_code="L-001")
    create_lot(env["customer"]["id"], env["product"]["id"], lot_code="L-002")
    staged = create_lot(env["customer"]["id"], env["product"]["id"], lot_code="L-003")
    cycle = create_cycle(env["chamber"]["id"], env["recipe"]["id"])
    add_load_position(cycle["id"], staged["id"], position_index=1, pallet_count=2)

    rows, meta = validate_paginated(
        api_client.list_lots(ADMIN, params={"status": "RECEIVED", "limit": 1, "offset": 0})
    )

    assert meta["total_count"] == 2
    assert meta["limit"] == 1
    assert meta["offset"] == 0
    assert meta["has_more"] is True
    assert len(rows) == 1
    assert rows[0]["status"] == "RECEIVED"
    assert rows[0]["id"] != staged["id"]
    assert get_lot(staged["id"])["status"] == "STAGED"


def test_biological_indicator_without_spore_population_is_rejected():
    """PRD 2.7: "**Payload schema.** On every write, required fields are
    present, types are correct, enum members are recognised and numeric ranges
    hold"
    PRD 3.5: "and, for a biological indicator only, `spore_population`, the
    declared spore count, which must be present and at least 1 for a
    `BIOLOGICAL` indicator and must be omitted or null for a `DOSIMETER`."

    Design: Corner/entities/corner_create_biological_indicator_missing_spore_population_rejected
    """
    env = setup_reference_data()
    lot = create_lot(env["customer"]["id"], env["product"]["id"])
    cycle = create_cycle(env["chamber"]["id"], env["recipe"]["id"])
    position = add_load_position(cycle["id"], lot["id"], position_index=1, pallet_count=2)

    response = api_client.create_indicator(
        position["id"],
        {"indicator_type": "BIOLOGICAL", "placement_zone": "ROUTINE", "serial_code": "B-001"},
        operator(),
    )

    validate_error(response, ApiErrorId.ERR_VALIDATION)
    _, meta = validate_paginated(api_client.list_indicators(position["id"], operator()))
    assert meta["total_count"] == 0
