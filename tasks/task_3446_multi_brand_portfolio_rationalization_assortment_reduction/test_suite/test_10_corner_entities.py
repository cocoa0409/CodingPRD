"""Corner queue: entity-surface claims — required fields, defaults, system
fields, enum membership, retrieval round-trip, 404, and the append-only
QualificationRun shape.
"""
from test_helpers import (
    ABSENT_UUID,
    CLOCK_START_ISO_MILLIS,
    TEST_USERS,
    ApiErrorId,
    api_client,
    assert_item,
    assert_qualification_run,
    create_brand,
    create_brand_payload,
    create_item_payload,
    create_retailer_payload,
    is_valid_uuid,
    record_pass_run,
    setup_brand_and_plant,
    setup_listed_item,
    setup_transfer_planned,
    validate_created,
    validate_error,
    validate_ok,
    validate_paginated,
)

PM = TEST_USERS["portfolio_manager_headers"]
FC = TEST_USERS["finance_controller_headers"]


def test_create_item_missing_required_field_returns_invalid_request():
    """PRD §2.8: "4. The request body is well-formed: required fields present,
    types correct, enum members valid, integer ranges honored — for example
    `private_label_share_pct` between 0 and 100 inclusive,
    `strategic_fit_score` between 0 and 100 inclusive, `units_produced` at
    least 1 — and unknown enum values rejected (`ERR_INVALID_REQUEST`)."
    PRD §3.1: "Creating an **item** requires its `brand_id` and
    `primary_plant_id` (the plant currently producing it), a globally unique
    `sku_code` ...".

    Design: Corner/entities/create_item_missing_required_field_returns_invalid_request
    """
    brand, plant = setup_brand_and_plant()
    payload = create_item_payload(brand["id"], plant["id"])
    del payload["sku_code"]
    resp = api_client.create_item(payload, PM)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    items, _ = validate_paginated(
        api_client.list_items(PM, params={"brand_id": brand["id"]})
    )
    assert items == [], "A rejected create must persist nothing"


def test_item_salvageable_defaults_false_when_omitted():
    """PRD §3.1: "An optional `salvageable` flag, defaulting to false, records
    whether residual inventory has salvage value; it selects which obsolescence
    variant applies when the item is eventually discontinued (§3.2)."
    PRD §3.1: "A new item starts `LISTED`."

    Design: Corner/entities/item_salvageable_defaults_false_when_omitted
    """
    brand, plant = setup_brand_and_plant()
    # The factory omits `salvageable` unless asked, exercising the server default.
    resp = api_client.create_item(
        create_item_payload(brand["id"], plant["id"]), PM
    )
    item = validate_created(resp)
    assert_item(item)
    assert item["salvageable"] is False, (
        f"omitted salvageable must default to false, got {item['salvageable']}"
    )
    assert item["item_status"] == "LISTED"


def test_brand_create_system_fields_input_ignored():
    """PRD §2.5: "Every entity in this API carries an `id` that is a
    server-minted UUID with no type prefix, assigned at creation."
    PRD §2.5: "`version` (an integer that starts at 1 and increments by exactly
    1 on every mutation of that resource, including mutations performed as side
    effects of operations on other resources)".
    PRD §2.4: "At startup, before any clock-setting call has been made, the
    logical clock reads exactly 2026-09-01T00:00:00Z".

    Design: Corner/entities/brand_create_system_fields_input_ignored
    """
    resp = api_client.create_brand(
        create_brand_payload(
            name="B-EN3", id="client-supplied-id", version=99,
        ),
        PM,
    )
    brand = validate_created(resp)
    assert brand["id"] != "client-supplied-id", (
        "The server must mint its own id, not accept the client-supplied one"
    )
    assert is_valid_uuid(brand["id"])
    assert brand["version"] == 1, (
        f"version is system-initialized to 1, got {brand['version']}"
    )
    assert brand["created_at"] == CLOCK_START_ISO_MILLIS, (
        f"created_at must be stamped from the logical clock default "
        f"2026-09-01T00:00:00.000Z, got {brand['created_at']}"
    )


def test_invalid_enum_risk_rating_returns_invalid_request():
    """PRD §3.1: "A **retailer** is registered with a unique `name` and a
    `risk_rating` of `LOW`, `MEDIUM`, or `HIGH`, capturing the relationship
    risk the company assigns to that account."
    PRD §2.8: "4. The request body is well-formed: ... unknown enum values
    rejected (`ERR_INVALID_REQUEST`)."

    Design: Corner/entities/invalid_enum_risk_rating_returns_invalid_request
    """
    resp = api_client.create_retailer(
        create_retailer_payload(name="R-EN4", risk_rating="EXTREME"), PM
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_get_item_returns_stored_fields():
    """PRD §3.1: "Two lifecycle counters accompany it from birth, both starting
    at zero: `units_sold_cumulative` and `units_written_off_cumulative`, plus
    an `obsolescence_charge_cents` accumulator that also starts at zero."
    PRD §3.2: "the `sell_through_deadline` field is null at all other times in
    an item's life."

    Design: Corner/entities/get_item_returns_stored_fields
    """
    _, _, item = setup_listed_item({"units_on_hand": 42})
    resp = api_client.get_item(item["id"], FC)
    data = validate_ok(resp)
    assert_item(data)
    assert data["id"] == item["id"]
    assert data["sku_code"] == item["sku_code"]
    assert data["units_on_hand"] == 42, "input fields must round-trip"
    assert data["units_sold_cumulative"] == 0
    assert data["units_written_off_cumulative"] == 0
    assert data["obsolescence_charge_cents"] == 0
    assert data["sell_through_deadline"] is None, (
        "no approved case -> sell_through_deadline must be null"
    )


def test_get_nonexistent_item_returns_not_found():
    """PRD §2.5: "On nested reads and parameterized paths, path identifiers are
    resolved strictly left to right — the parent segment's existence is
    confirmed before any sub-resource segment is considered — and any
    unresolved path or body foreign-key identifier is rejected with
    `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/get_nonexistent_item_returns_not_found
    """
    resp = api_client.get_item(ABSENT_UUID, PM)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_qualification_run_immutable_common_fields_false():
    """PRD §2.5: "`QualificationRun` is the sole exception: it is an immutable
    event record carrying only `id` and `created_at`, and both `updated_at` and
    `version` are absent from it."
    PRD §3.4: "the recorded run's `certifier_plant_id` is set to that
    `X-User-ID`."

    Design: Corner/entities/qualification_run_immutable_common_fields_false
    """
    _, _, target_plant, _, transfer = setup_transfer_planned()
    run = record_pass_run(transfer["id"], target_plant["id"],
                          run_date="2026-09-02T00:00:00Z")
    assert_qualification_run(run)  # enforces absence of updated_at and version
    assert "version" not in run
    assert "updated_at" not in run
    assert run["result"] == "PASS"
    assert run["certifier_plant_id"] == target_plant["id"], (
        "certifier_plant_id must be stamped from the caller's X-User-ID"
    )
    runs, _ = validate_paginated(
        api_client.list_qualification_runs(transfer["id"], PM)
    )
    assert len(runs) == 1
    assert runs[0]["id"] == run["id"]
