"""Optimistic concurrency on parent rows and the immediate-consistency guarantee."""
import pytest

from test_helpers import (
    validate_error, validate_success, validate_paginated, ApiErrorId, TEST_USERS,
    create_warehouse, create_account, create_battery_model, receive_lot, create_order,
    add_line, submit_order, allocate_order, create_service_contract,
    size_service_contract, create_disposal_manifest, scrap_lot, certify_shipment,
    read_order, read_account, read_shipment, read_manifest, read_core_return,
    read_service_contract, setup_base_env, setup_packed_shipment,
    setup_credited_core_return,
)

REP = TEST_USERS["sales_rep_headers"]
OPERATOR = TEST_USERS["warehouse_operator_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


def _allocated_two_unit_order():
    env = setup_base_env(
        "IB-AGM-95",
        account_overrides={"name": "Delta Fleet", "storm_priority_rank": 5},
        lot_overrides={"manufactured_on": "2026-06-01", "quantity_on_hand": 30},
    )
    order = create_order(env["account"]["id"], env["warehouse"]["id"],
                         requested_ship_date="2026-08-05")
    add_line(order["id"], env["model"]["id"], 2, core_expected_count=0)
    env["order_at_submit"] = submit_order(order["id"])
    env["order"] = allocate_order(order["id"])
    return env


def _shipment_payload(env, expected_order_version):
    return {
        "order_id": env["order"]["id"], "carrier_id": env["carrier"]["id"],
        "pickup_window_start": "2026-08-05T08:00:00Z",
        "pickup_window_end": "2026-08-05T18:00:00Z",
        "expected_order_version": expected_order_version,
    }


def test_packing_against_a_stale_order_version_is_refused(api):
    """PRD §2.5: "Packing a shipment — a `POST /distribution/shipments` request
    — must carry `expected_order_version` as a required, non-optional body field
    holding the client's last observed `version` of the target `Order`. If it
    does not equal the order's current `version`, the request is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/stale_order_version_on_shipment_create_returns_precondition_failed
    """
    env = _allocated_two_unit_order()
    current = env["order"]["version"]

    resp = api.create_shipment(_shipment_payload(env, current - 1), OPERATOR)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)

    rows, meta = validate_paginated(api.list_shipments(
        OPERATOR, params={"order_id": env["order"]["id"], "limit": 10, "offset": 0}))
    assert rows == [] and meta["total_count"] == 0
    stored = read_order(env["order"]["id"])
    assert stored["fulfillment_status"] == "ALLOCATED"
    assert stored["version"] == current, "A refused pack does not advance the version"


def test_packing_against_the_current_order_version_bumps_it_by_one(api):
    """PRD §2.5: "A successful pack increments the order's `version` by 1."
    PRD §2.4: "Every resource also carries `created_at` and `updated_at`, both
    ISO 8601 UTC timestamps rendered with three fractional digits, and a
    `version`, an integer that starts at 1 on creation and increments by exactly
    1 on every mutation of that row."

    Design: Corner/cross_cutting_complexity_layers/current_order_version_on_shipment_create_succeeds_and_bumps_the_version
    """
    env = _allocated_two_unit_order()
    current = env["order"]["version"]

    shipment = validate_success(api.create_shipment(_shipment_payload(env, current),
                                                    OPERATOR), 201)
    assert shipment["status"] == "PACKED"
    assert shipment["packed_by_user_id"] == "op-1"
    assert shipment["hazmat_class_code"] == "UN2800_EXCEPTED"
    assert shipment["total_weight_kg"] == pytest.approx(56.0, abs=0.001)
    assert read_order(env["order"]["id"])["version"] == current + 1


def test_attaching_a_contract_against_a_stale_order_version_is_refused(api):
    """PRD §2.5: "Attaching a service contract to an order — a `POST
    /distribution/service-contracts/{serviceContractId}/attach` request — must
    likewise carry `expected_order_version` as a required body field matching
    the target `Order`'s current `version`, and a mismatch is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/stale_order_version_on_contract_attach_returns_precondition_failed
    """
    warehouse = create_warehouse(code="TX-DAL", state_code="TX", hazmat_endorsement=True,
                                 storm_reserve_pct=0.0, dock_capacity_kg_per_window=100000.0)
    account = create_account(name="Delta Fleet", account_tier="STANDARD", state_code="TX",
                             credit_limit_cents=100000000, storm_priority_rank=5)
    agm = create_battery_model("IB-AGM-95")
    create_battery_model("IB-LFP-100")
    order = create_order(account["id"], warehouse["id"], requested_ship_date="2026-08-11")
    add_line(order["id"], agm["id"], 4, core_expected_count=0)
    order = submit_order(order["id"])
    assert order["total_cents"] == 118080

    contract = create_service_contract(account["id"], coverage_tier="GOLD")
    contract = size_service_contract(contract["id"])
    assert contract["prepay_total_cents"] == 118800

    resp = api.attach_service_contract(contract["id"], {
        "order_id": order["id"], "expected_order_version": order["version"] - 1,
    }, REP)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)

    stored_contract = read_service_contract(contract["id"])
    assert stored_contract["status"] == "SIZED"
    assert stored_contract["order_id"] is None
    stored_order = read_order(order["id"])
    assert stored_order["service_contract_fee_cents"] == 0
    assert stored_order["total_cents"] == 118080
    assert stored_order["version"] == order["version"]


def test_attaching_a_core_return_against_a_stale_manifest_version_is_refused(api):
    """PRD §2.5: "Attaching a credited core return to a disposal manifest — a
    `POST /distribution/disposal-manifests/{disposalManifestId}/attach-core-return`
    request — must carry `expected_disposal_manifest_version` as a required body
    field matching that manifest's current `version`, and a mismatch is rejected
    with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §3.2: "A successful scrap writes `scrap_manifest_id` onto the lot, which
    forces its `condition_state` to `SCRAPPED`, increments that manifest's
    `scrapped_lot_count` by 1, and re-derives the manifest's `lot_lead_kg` and
    `total_lead_kg`."

    Design: Corner/cross_cutting_complexity_layers/stale_manifest_version_on_attach_core_return_returns_precondition_failed
    """
    env = setup_credited_core_return(
        quantity=10, core_expected_count=10, declared_core_count=10,
        accepted_core_count=10, lot_overrides={"quantity_on_hand": 60},
        account_overrides={"name": "Delta Fleet", "storm_priority_rank": 5},
        order_overrides={"requested_ship_date": "2026-08-05"},
    )
    assert env["core_return"]["status"] == "CREDITED"
    assert env["core_return"]["lead_recovered_kg"] == pytest.approx(120.625, abs=0.0005)

    expired = receive_lot(env["model"]["id"], env["warehouse"]["id"],
                          manufactured_on="2024-01-01", quantity_on_hand=4)
    manifest = create_disposal_manifest(env["warehouse"]["id"])
    stale_version = manifest["version"]
    scrap_lot(expired["id"], manifest["id"])

    resp = api.attach_core_return_to_manifest(manifest["id"], {
        "core_return_id": env["core_return"]["id"],
        "expected_disposal_manifest_version": stale_version,
    }, COMPLIANCE)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)

    assert read_core_return(env["core_return"]["id"])["disposal_manifest_id"] is None
    stored = read_manifest(manifest["id"])
    assert stored["attached_core_return_count"] == 0
    assert stored["scrapped_lot_count"] == 1
    assert stored["total_lead_kg"] == pytest.approx(50.000, abs=0.0005)


def test_the_certification_cascade_is_visible_on_the_very_next_read():
    """PRD §2.9: "What is universal is the discipline: a cascade runs to
    completion within the triggering request, synchronously, and the response
    reflects the finished state. There is no deferred or eventual settlement
    anywhere in this system."
    PRD §3.5: "It then cascades: unless the order's `hazmat_fee_waived` is true,
    the order's `hazmat_fee_cents` is replaced by the shipment's surcharge and
    `total_cents` is re-derived; and because the order total changed, the buying
    account's `open_receivable_cents` is adjusted by the difference between the
    new order total and the previous one."

    Design: Corner/consistency_model/certification_cascade_is_visible_in_the_very_next_read
    """
    env = setup_packed_shipment(
        quantity=2, core_expected_count=0, model_preset="IB-AGM-95",
        lot_overrides={"manufactured_on": "2026-06-01", "quantity_on_hand": 30},
        order_overrides={"requested_ship_date": "2026-08-05"},
    )
    assert read_order(env["order"]["id"])["total_cents"] == 59678

    certified = certify_shipment(env["shipment"]["id"], "APPROVE")
    assert certified["hazmat_surcharge_cents"] == 3953

    order = read_order(env["order"]["id"])
    assert order["total_cents"] == 60953
    assert order["hazmat_fee_cents"] == 3953
    assert read_account(env["account"]["id"])["open_receivable_cents"] == 60953
    assert read_shipment(env["shipment"]["id"])["status"] == "CERTIFIED"
