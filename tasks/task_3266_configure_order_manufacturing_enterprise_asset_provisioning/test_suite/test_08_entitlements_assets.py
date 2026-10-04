"""Support entitlements and the asset report: parts-stocking gate, closed
interval overlap, reservation invariants, and the serial-to-PO feed."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_account,
    create_chassis,
    create_component,
    add_allowed_rule,
    create_entitlement_payload,
    create_program,
    create_template,
    create_validated_configuration,
    create_order_with_lines,
    create_wave_payload,
    get_order_build_jobs,
    setup_built_order,
    submit_order,
    make_customer_user_headers,
    get_success_data,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
MANAGER = TEST_USERS["account_manager_headers"]
OPS = TEST_USERS["factory_ops_headers"]


def _server_order_with_line(api, tier="STANDARD"):
    """SERVER-chassis submitted order. Returns dict of account/chassis/part/order/line."""
    account = create_account(account_tier=tier)
    chassis = create_chassis(category="SERVER", base_price_cents=200_000)
    part = create_component(kind="PSU", price_cents=9_000, stock_on_hand=10)
    add_allowed_rule(chassis["id"], part["id"])
    config = create_validated_configuration(account, chassis["id"],
                                            [{"component_id": part["id"], "qty": 1}])
    order, lines = create_order_with_lines(
        account, [{"configuration_id": config["id"], "qty": 1, "ship_to_mode": "SINGLE_ADDRESS"}],
    )
    submit_order(account, order, config["version"])
    return {"account": account, "chassis": chassis, "part": part,
            "order": order, "line": lines[0]}


def test_onsite_4h_server_requires_parts_stocking(api):
    """PRD §3.8: "First, an `ONSITE_4H` entitlement covering a line whose
    chassis category is `SERVER` must carry `parts_stocking_required` set to
    true with a reservable part in stock; creation without the stocking
    commitment, or without available part stock, is rejected with
    `ERR_PARTS_STOCKING_REQUIRED` (HTTP 422)."

    Design: Corner/validations/onsite_4h_server_requires_parts_stocking
    """
    env = _server_order_with_line(api)
    resp = api.create_support_entitlement(
        env["line"]["id"],
        create_entitlement_payload(tier="ONSITE_4H"),
        MANAGER,
    )
    validate_error(resp, ApiErrorId.ERR_PARTS_STOCKING_REQUIRED.value, 422)
    ents = get_success_data(api.list_line_entitlements(env["line"]["id"], MANAGER))
    assert len(ents) == 0


def test_onsite_4h_laptop_succeeds_without_parts_stocking(api):
    """PRD §3.8: "First, an `ONSITE_4H` entitlement covering a line whose
    chassis category is `SERVER` must carry `parts_stocking_required` set to
    true with a reservable part in stock; creation without the stocking
    commitment, or without available part stock, is rejected with
    `ERR_PARTS_STOCKING_REQUIRED` (HTTP 422)."

    Design: Corner/validations/onsite_4h_server_requires_parts_stocking
    """
    # Same tier on a LAPTOP line succeeds — the rule is conditional on SERVER.
    env = setup_built_order()
    resp = api.create_support_entitlement(
        env["line"]["id"],
        create_entitlement_payload(tier="ONSITE_4H"),
        MANAGER,
    )
    data = validate_success(resp, 201)
    assert data["tier"] == "ONSITE_4H"
    assert data["status"] == "ACTIVE"


def test_entitlement_closed_interval_duplicate_rejected(api):
    """PRD §3.8: "The entitlement names a `tier` of `BASIC`, `NBD`, or
    `ONSITE_4H`; a coverage window from `coverage_start` through `coverage_end`
    as a closed interval, inclusive of both endpoints; an optional
    `parts_stocking_required` flag defaulting to false; and, when parts
    stocking is required, the `reserved_part_component_id` identifying which
    component is stocked for this entitlement."
    PRD §3.8: "Second, the closed coverage window must not duplicate an
    `ACTIVE` entitlement already covering the same order line at the same tier;
    such duplication is rejected with `ERR_ENTITLEMENT_OVERLAP` (HTTP 422)."

    Design: Difficulty/resource_temporal_overlap/entitlement_closed_interval_duplicate_rejected
    """
    env = setup_built_order()
    line_id = env["line"]["id"]
    resp = api.create_support_entitlement(
        line_id,
        create_entitlement_payload(
            tier="NBD",
            coverage_start="2026-09-01T00:00:00Z",
            coverage_end="2027-09-01T00:00:00Z",
        ),
        MANAGER,
    )
    validate_success(resp, 201)
    # Second entitlement touching at the endpoint: closed interval -> overlap.
    resp = api.create_support_entitlement(
        line_id,
        create_entitlement_payload(
            tier="NBD",
            coverage_start="2027-09-01T00:00:00Z",
            coverage_end="2028-09-01T00:00:00Z",
        ),
        MANAGER,
    )
    validate_error(resp, ApiErrorId.ERR_ENTITLEMENT_OVERLAP.value, 422)
    ents = get_success_data(api.list_line_entitlements(line_id, MANAGER))
    active = [e for e in ents if e["status"] == "ACTIVE"]
    assert len(active) == 1


def test_entitlement_overlap_interior_duplicate_rejected(api):
    """PRD §3.8: "Second, the closed coverage window must not duplicate an
    `ACTIVE` entitlement already covering the same order line at the same tier;
    such duplication is rejected with `ERR_ENTITLEMENT_OVERLAP` (HTTP 422)."

    Design: Difficulty/resource_temporal_overlap/entitlement_closed_interval_duplicate_rejected
    """
    env = setup_built_order()
    line_id = env["line"]["id"]
    api.create_support_entitlement(
        line_id,
        create_entitlement_payload(
            tier="BASIC",
            coverage_start="2026-09-01T00:00:00Z",
            coverage_end="2027-09-01T00:00:00Z",
        ),
        MANAGER,
    )
    resp = api.create_support_entitlement(
        line_id,
        create_entitlement_payload(
            tier="BASIC",
            coverage_start="2027-01-01T00:00:00Z",
            coverage_end="2028-01-01T00:00:00Z",
        ),
        MANAGER,
    )
    validate_error(resp, ApiErrorId.ERR_ENTITLEMENT_OVERLAP.value, 422)


def test_parts_stocking_reservation_cancel_invariant(api):
    """PRD §3.8: "When an entitlement is created with parts stocking, the
    reserved part component's `reserved_units` increases by 1, reducing its
    `available_units` per the pool invariant."
    PRD §3.8: "On either path, an entitlement that required parts stocking
    releases its reservation: the reserved part component's `reserved_units`
    decreases by 1."

    Design: Difficulty/compensating_invariant/parts_stocking_reservation_cancel_invariant
    """
    env = _server_order_with_line(api)
    part_id = env["part"]["id"]
    resp = api.create_support_entitlement(
        env["line"]["id"],
        create_entitlement_payload(
            tier="ONSITE_4H",
            parts_stocking_required=True,
            reserved_part_component_id=part_id,
        ),
        MANAGER,
    )
    ent = validate_success(resp, 201)
    part_after = get_success_data(api.get_component(part_id, ADMIN))
    assert part_after["reserved_units"] == 1
    assert part_after["available_units"] == 9
    resp = api.cancel_entitlement(ent["id"], MANAGER)
    ent_after = validate_success(resp, 200)
    assert ent_after["status"] == "CANCELLED"
    part_after = get_success_data(api.get_component(part_id, ADMIN))
    assert part_after["reserved_units"] == 0
    assert part_after["available_units"] == 10


def test_parts_stocking_cancel_restores_exactly_one_unit(api):
    """PRD §3.8: "On either path, an entitlement that required parts stocking
    releases its reservation: the reserved part component's `reserved_units`
    decreases by 1."

    Design: Difficulty/compensating_invariant/parts_stocking_reservation_cancel_invariant
    """
    env = _server_order_with_line(api)
    part_id = env["part"]["id"]
    before = get_success_data(api.get_component(part_id, ADMIN))
    ent = get_success_data(api.create_support_entitlement(
        env["line"]["id"],
        create_entitlement_payload(
            tier="ONSITE_4H",
            parts_stocking_required=True,
            reserved_part_component_id=part_id,
        ),
        MANAGER,
    ))
    mid = get_success_data(api.get_component(part_id, ADMIN))
    assert mid["reserved_units"] == before["reserved_units"] + 1
    api.cancel_entitlement(ent["id"], MANAGER)
    after = get_success_data(api.get_component(part_id, ADMIN))
    assert after["reserved_units"] == before["reserved_units"]
    assert after["available_units"] == before["available_units"]


def test_asset_report_maps_serials_to_po(api):
    """PRD §3.7: "For asset managers, the order exposes a serial-to-PO report:
    keyed by the order's `po_number`, it lists one row per asset with the
    asset's `serial_number`, `asset_tag`, `order_line_id`,
    `destination_employee_ref` (null for single-address lines), and the asset's
    current status as `asset_status`."
    PRD §3.7: "Shipping moves every asset covered by the wave's destinations
    from `STAGED` to `IN_TRANSIT` and stamps each with its
    `destination_employee_ref`."

    Design: Corner/endpoints/asset_report_maps_serials_to_po
    """
    account = create_account(company_name="EE1")
    program = create_program(account["id"], name="P1", asset_tag_prefix="FE",
                             custom_image_ref="img-std")
    chassis = create_chassis(model_code="EEL1")
    cpu = create_component(sku="EEC1")
    add_allowed_rule(chassis["id"], cpu["id"])
    template = create_template(program["id"], chassis["id"],
                               [{"component_id": cpu["id"], "revision": "A01", "qty": 1}],
                               name="T1")
    api.publish_template(template["id"], MANAGER)
    api.lock_program(program["id"], MANAGER)
    config = create_validated_configuration(
        account, chassis["id"], [{"component_id": cpu["id"], "qty": 1}],
        template_id=template["id"],
    )
    resp = api.lock_configuration(config["id"], MANAGER)
    locked = validate_success(resp, 200)
    order, lines = create_order_with_lines(
        account,
        [{"configuration_id": config["id"], "qty": 2, "ship_to_mode": "DROP_SHIP_EMPLOYEES"}],
        po_number="PO-EE1",
    )
    submit_order(account, order, locked["version"])
    job = get_order_build_jobs(order["id"])[0]
    for fn in (api.allocate_build_job, api.start_build_job, api.complete_build_job):
        resp = fn(job["id"], OPS)
        assert resp.status_code == 200
    api.set_clock("2026-09-02T00:00:00Z", ADMIN)
    wave = get_success_data(api.create_deployment_wave(
        order["id"],
        create_wave_payload(
            wave_label="W1",
            ship_window_start="2026-09-02T00:00:00Z",
            ship_window_end="2026-09-20T00:00:00Z",
            destinations=[
                {"employee_ref": "EMP-A", "address": "1 A St", "units": 1},
                {"employee_ref": "EMP-B", "address": "2 B St", "units": 1},
            ],
        ),
        MANAGER,
    ))
    api.release_wave(wave["id"], MANAGER)
    api.ship_wave(wave["id"], OPS)
    resp = api.get_asset_report(order["id"], MANAGER)
    report = validate_success(resp, 200)
    assert report["po_number"] == "PO-EE1"
    rows = report["rows"]
    assert len(rows) == 2
    serials = [r["serial_number"] for r in rows]
    assert all(s for s in serials)
    assert len(set(serials)) == 2
    assert all(r["asset_tag"].startswith("FE-") for r in rows)
    assert sorted(r["destination_employee_ref"] for r in rows) == ["EMP-A", "EMP-B"]
    assert all(r["asset_status"] == "IN_TRANSIT" for r in rows)
