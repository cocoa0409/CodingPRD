"""Clock-driven expiration, OCC on pricing, recertification recovery, listing."""
from test_helpers import (
    ApiErrorId, create_draft_certificate, get_lot, get_order, make_customer,
    make_customer_headers, make_inventory_manager_headers, make_lot,
    make_program, make_program_admin_headers, place_order, publish_certificate,
    run_homogeneity, set_clock, setup_lot_in_distribution, validate_error,
    validate_paginated, validate_success,
)

_INV = make_inventory_manager_headers()
_ADMIN = make_program_admin_headers()


def test_occ_stale_program_version_pricing_update_rejected(api):
    """PRD §2.7: "when the supplied value no longer matches the program's
    current `version` — because another writer has advanced it since — the
    request is rejected with `ERR_STALE_VERSION` (HTTP 412), and no pricing
    field changes."

    Design: Corner/complexity_layers/occ_stale_program_version_pricing_update_rejected
    """
    program = make_program(program_code="NIST-RM-C48")
    updated = validate_success(
        api.pricing_update(program["id"],
                           {"expected_program_version": program["version"],
                            "material_unit_price_cents": 1200}, _ADMIN))
    assert updated["version"] == 2
    assert updated["material_unit_price_cents"] == 1200
    resp = api.pricing_update(program["id"],
                              {"expected_program_version": program["version"],
                               "material_unit_price_cents": 1500}, _ADMIN)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


def test_clock_sweep_expires_certificate_and_holds_lot(api):
    """PRD §2.4: "Setting the clock fires the certificate-expiration sweep:
    every certificate in `PUBLISHED` status whose `expiration_date` falls at or
    before the new clock value becomes `EXPIRED`."
    PRD §2.4: "When such an expiring certificate's lot is currently
    `IN_DISTRIBUTION`, the lot is automatically placed on `DISTRIBUTION_HOLD`
    with `hold_reason` set to `CERTIFICATE_EXPIRED`."

    Design: Corner/complexity_layers/clock_sweep_expires_certificate_and_holds_lot
    """
    ctx = setup_lot_in_distribution(total=10, material_code="SRM-C50", validity_days=30,
                                    program_overrides={"program_code": "NIST-RM-C50"})
    customer = make_customer(name="C50")
    pre = set_clock("2026-09-30T23:59:59Z")
    assert pre["expired_certificate_count"] == 0
    assert pre["transitioned_lot_count"] == 0
    post = set_clock("2026-10-01T00:00:00Z")
    assert post["expired_certificate_count"] == 1
    assert post["transitioned_lot_count"] == 1
    lot = get_lot(ctx["lot"]["id"])
    assert lot["status"] == "DISTRIBUTION_HOLD"
    assert lot["hold_reason"] == "CERTIFICATE_EXPIRED"
    resp = api.create_sales_order({"lot_id": ctx["lot"]["id"], "quantity": 1},
                                  make_customer_headers(customer["id"]))
    validate_error(resp, ApiErrorId.ERR_LOT_NOT_DISTRIBUTABLE)


def _setup_recert(api):
    """Lot (12 produced, 4 qc -> 8 usable) IN_DISTRIBUTION behind a validity-30
    certificate; O1 qty 4 ALLOCATED, O2 qty 6 partially allocated BACKORDERED;
    clock advanced to expiration; O1 cancelled during the hold."""
    ctx = setup_lot_in_distribution(total=12, material_code="SRM-H", validity_days=30,
                                    program_overrides={"program_code": "NIST-RM-08"})
    lot_id = ctx["lot"]["id"]
    customer_x = make_customer(name="CX")
    customer_y = make_customer(name="CY")
    o1 = place_order(lot_id, customer_x["id"], 4)
    o2 = place_order(lot_id, customer_y["id"], 6)
    assert o1["status"] == "ALLOCATED"
    assert o2["status"] == "BACKORDERED" and o2["allocated_quantity"] == 4
    set_clock("2026-10-01T00:00:00Z")
    validate_success(api.transition_sales_order(o1["id"], {"to": "CANCELLED"},
                                                make_customer_headers(customer_x["id"])))
    lot_hold = get_lot(lot_id)
    return ctx, o2, lot_hold


def test_recertification_returns_lot_to_distribution(api):
    """PRD §3.4: "from `DISTRIBUTION_HOLD` it returns to `IN_DISTRIBUTION` with
    `hold_reason` cleared to null and the shortage-allocation sweep of §3.5
    re-run over its backordered orders".

    Design: Difficulty/transitive_cascade/certificate_recertification_recovers_distribution
    """
    ctx, _o2, lot_hold = _setup_recert(api)
    assert lot_hold["status"] == "DISTRIBUTION_HOLD"
    cert2 = create_draft_certificate(ctx["lot"]["id"], certificate_code="CERT-H2",
                                     value_assignment_variant="UNWEIGHTED_MEAN",
                                     validity_days=60)
    publish_certificate(cert2["id"])
    lot = get_lot(ctx["lot"]["id"])
    assert lot["status"] == "IN_DISTRIBUTION"
    assert lot["hold_reason"] is None


def test_recertification_promotes_backordered_order(api):
    """PRD §3.4: "from `DISTRIBUTION_HOLD` it returns to `IN_DISTRIBUTION` with
    `hold_reason` cleared to null and the shortage-allocation sweep of §3.5
    re-run over its backordered orders".
    PRD §3.5: "any candidate whose `allocated_quantity` reaches its full
    `quantity` is promoted from `BACKORDERED` to `ALLOCATED`."

    Design: Difficulty/transitive_cascade/certificate_recertification_recovers_distribution
    """
    ctx, o2, lot_hold = _setup_recert(api)
    assert lot_hold["status"] == "DISTRIBUTION_HOLD"
    cert2 = create_draft_certificate(ctx["lot"]["id"], certificate_code="CERT-H2",
                                     value_assignment_variant="UNWEIGHTED_MEAN",
                                     validity_days=60)
    publish_certificate(cert2["id"])
    o2_after = get_order(o2["id"])
    assert o2_after["status"] == "ALLOCATED"
    assert o2_after["allocated_quantity"] == 6
    lot = get_lot(ctx["lot"]["id"])
    assert lot["units_reserved"] == 6
    assert lot["units_available"] == 2
    certs, _meta = validate_paginated(api.list_lot_certificates(lot["id"], _ADMIN))
    by_code = {c["certificate_code"]: c["status"] for c in certs}
    assert by_code["CERT-1"] == "EXPIRED"
    assert by_code["CERT-H2"] == "PUBLISHED"


def test_list_pagination_and_status_filter(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned; it
    defaults to 10, with a minimum of 1 and a maximum of 100. The `offset`
    parameter skips a number of items from the front of the result set and
    defaults to 0."
    PRD §3.2: "Lots can be browsed directly or filtered by `program_id` and
    `status`".

    Design: Corner/endpoints/list_pagination_and_status_filter
    """
    program = make_program(program_code="NIST-RM-C38")
    lot_a = make_lot(program["id"], material_code="SRM-C38A")
    lot_b = make_lot(program["id"], material_code="SRM-C38B")
    lot_c = make_lot(program["id"], material_code="SRM-C38C")
    run_homogeneity(lot_c["id"])  # -> VALUE_ASSIGNMENT
    rows, meta = validate_paginated(
        api.list_material_lots(_INV, params={"program_id": program["id"],
                                             "status": "SOURCING"}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert {r["id"] for r in rows} == {lot_a["id"], lot_b["id"]}
    assert all(r["status"] == "SOURCING" and r["program_id"] == program["id"]
               for r in rows)
