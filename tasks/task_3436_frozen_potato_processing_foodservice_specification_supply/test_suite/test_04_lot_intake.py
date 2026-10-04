"""Potato-lot intake: required-field shape, the exactly-one-source rule,
delivery-window and variety gates, and the dual intake modes."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_contracted_lot_payload,
    create_import_lot_payload,
    make_active_agreement,
    make_facility,
    make_grower,
    make_grower_headers,
    make_shortage_event,
    set_clock,
    setup_chain_with_validated_spec,
    setup_procurement,
    validate_error,
    validate_paginated,
    validate_success,
)

GRM = TEST_USERS["grower_relations_manager_headers"]
QA = TEST_USERS["qa_lead_headers"]


def test_lot_create_missing_gross_weight_returns_invalid_request(api):
    """PRD §2.10: "4. **Request shape** — required fields present, enum
    members valid, numeric bounds respected (weights positive, tare below
    gross, window start before end, trailer setpoint at or below freezing,
    exactly one of `contract_id` or `shortage_event_id` on lot creation);
    otherwise `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/lot_create_missing_gross_weight_returns_invalid_request
    """
    world = setup_procurement(api=api)
    payload = create_contracted_lot_payload(world["contract"]["id"], world["facility"]["id"])
    del payload["gross_weight_cwt"]
    resp = api.create_potato_lot(payload, make_grower_headers(world["grower"]["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    assert resp.status_code == 400
    rows, _ = validate_paginated(
        api.list_potato_lots(GRM, params={"contract_id": world["contract"]["id"]})
    )
    assert rows == [], "a shape-rejected intake must not persist a lot"


def test_lot_create_with_both_or_neither_source_id_returns_source_mode_invalid(api):
    """PRD §3.2: "A potato lot is received in exactly one of two modes, and
    the request must carry exactly one of `contract_id` or `shortage_event_id`
    — a request with both or with neither is rejected with
    `ERR_LOT_SOURCE_MODE_INVALID` (HTTP 400)."

    Design: Corner/entities/lot_create_with_both_or_neither_source_id_returns_source_mode_invalid
    """
    world = setup_procurement(api=api)
    event = make_shortage_event(api=api)

    both = create_contracted_lot_payload(world["contract"]["id"], world["facility"]["id"])
    both["shortage_event_id"] = event["id"]
    resp_both = api.create_potato_lot(both, make_grower_headers(world["grower"]["id"]))
    validate_error(resp_both, ApiErrorId.ERR_LOT_SOURCE_MODE_INVALID)
    assert resp_both.status_code == 400

    neither = create_contracted_lot_payload(world["contract"]["id"], world["facility"]["id"])
    del neither["contract_id"]
    resp_neither = api.create_potato_lot(neither, GRM)
    validate_error(resp_neither, ApiErrorId.ERR_LOT_SOURCE_MODE_INVALID)
    assert resp_neither.status_code == 400

    rows, _ = validate_paginated(
        api.list_potato_lots(GRM, params={"facility_id": world["facility"]["id"]})
    )
    assert rows == []


def test_lot_create_outside_delivery_window_returns_422(api):
    """PRD §3.2: "the logical clock must fall inside the contract's delivery
    window — from `delivery_window_start` through `delivery_window_end`,
    inclusive at both ends (`ERR_OUTSIDE_DELIVERY_WINDOW` otherwise)".

    Design: Corner/validations/lot_create_outside_delivery_window_returns_422
    """
    world = setup_procurement(api=api)  # window 2026-09-01 .. 2026-10-15
    set_clock("2026-10-16T00:00:00Z", api=api)  # one day past the window end
    resp = api.create_potato_lot(
        create_contracted_lot_payload(world["contract"]["id"], world["facility"]["id"]),
        make_grower_headers(world["grower"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_OUTSIDE_DELIVERY_WINDOW)
    assert resp.status_code == 422
    rows, _ = validate_paginated(
        api.list_potato_lots(GRM, params={"contract_id": world["contract"]["id"]})
    )
    assert rows == []


def test_lot_create_variety_mismatch_returns_422(api):
    """PRD §3.2: "and the lot's `variety` must equal the contract's variety
    (`ERR_VARIETY_MISMATCH` otherwise)".

    Design: Corner/validations/lot_create_variety_mismatch_returns_422
    """
    world = setup_procurement(api=api)  # contract is RUSSET_BURBANK, clock in-window
    payload = create_contracted_lot_payload(
        world["contract"]["id"], world["facility"]["id"], variety="RANGER_RUSSET"
    )
    resp = api.create_potato_lot(payload, make_grower_headers(world["grower"]["id"]))
    validate_error(resp, ApiErrorId.ERR_VARIETY_MISMATCH)
    assert resp.status_code == 422
    rows, _ = validate_paginated(
        api.list_potato_lots(GRM, params={"contract_id": world["contract"]["id"]})
    )
    assert rows == []


def test_import_lot_mode_requires_open_event_and_manager_role(api):
    """PRD §2.1: "creating an import-sourced potato lot (one referencing a
    shortage event) requires the `GrowerRelationsManager` role, and any other
    role attempting it is rejected with `ERR_OWNERSHIP_MISMATCH`."
    PRD §3.2: "In **import mode**, used for shortage-response sourcing, the
    caller must be a `GrowerRelationsManager` and the referenced shortage
    event must be `OPEN` (`ERR_SHORTAGE_EVENT_NOT_OPEN` otherwise)."
    PRD §3.2: "Import lots carry a null `provisional_payment_cents`".
    PRD §3.1: "`final_payment_cents` is always null for import lots".

    Design: Corner/validations/import_lot_mode_requires_open_event_and_manager_role
    """
    set_clock(api=api)
    grower = make_grower(api=api)
    world_chain = setup_chain_with_validated_spec(api=api)
    agreement = make_active_agreement(
        world_chain["chain"]["id"], world_chain["spec"]["id"], api=api,
        weekly_contracted_cases=600,
    )
    facility = make_facility(api=api)
    event = make_shortage_event(api=api)

    # A Grower caller attempting IMPORT mode is refused at ownership priority.
    resp_role = api.create_potato_lot(
        create_import_lot_payload(event["id"], facility["id"]),
        make_grower_headers(grower["id"]),
    )
    validate_error(resp_role, ApiErrorId.ERR_OWNERSHIP_MISMATCH)
    assert resp_role.status_code == 403

    # The GrowerRelationsManager imports successfully while the event is OPEN.
    resp_import = api.create_potato_lot(
        create_import_lot_payload(event["id"], facility["id"]), GRM
    )
    lot = validate_success(resp_import, 201)
    assert resp_import.status_code == 201
    assert lot["origin"] == "IMPORT"
    assert lot["grade"] == "B", "defect 3.0 / gravity 1.075 / sugar 2.5 are all B-tier"
    assert lot["provisional_payment_cents"] is None
    assert lot["final_payment_cents"] is None
    assert lot["net_weight_cwt"] == 2000.0

    # Once executed the event is closed to further imports.
    validate_success(api.execute_allocation(event["id"], GRM))
    resp_closed = api.create_potato_lot(
        create_import_lot_payload(event["id"], facility["id"]), GRM
    )
    validate_error(resp_closed, ApiErrorId.ERR_SHORTAGE_EVENT_NOT_OPEN)
    assert resp_closed.status_code == 409

    rows, _ = validate_paginated(
        api.list_potato_lots(GRM, params={"shortage_event_id": event["id"]})
    )
    assert len(rows) == 1, "exactly one IMPORT lot persisted for the event"


def test_lot_create_response_immediately_carries_computed_fields(api):
    """PRD §1: "All mutations and their cascades are immediately consistent:
    every effect described for an operation is visible in that operation's
    response."
    PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."
    PRD §3.2: "From the weights the system derives the read-only
    `net_weight_cwt`: gross minus tare, rounded half-up to two decimal
    places."

    Design: Corner/consistency_model/lot_create_response_immediately_carries_computed_fields
    """
    world = setup_procurement(api=api)
    resp = api.create_potato_lot(
        create_contracted_lot_payload(world["contract"]["id"], world["facility"]["id"]),
        make_grower_headers(world["grower"]["id"]),
    )
    lot = validate_success(resp, 201)
    assert lot["net_weight_cwt"] == 1000.0, "1050.0 gross - 50.0 tare"
    assert lot["grade"] == "A"
    assert lot["provisional_payment_cents"] == 2700000, "1000.0 x 2500 x 1.08"
    assert lot["status"] == "IN_STORAGE"
    assert lot["origin"] == "CONTRACTED"

    facility = validate_success(api.get_storage_facility(world["facility"]["id"], GRM))
    assert facility["current_stock_cwt"] == 1000.0, (
        "the intake effect is visible on the facility without any further call"
    )
