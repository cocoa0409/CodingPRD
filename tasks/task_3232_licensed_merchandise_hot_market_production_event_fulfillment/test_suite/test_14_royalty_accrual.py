"""Royalty accruals: per-row rounding and the delivered-order cascade."""
from test_helpers import validate_success
from test_helpers.fixtures import (
    FULFILLMENT,
    committed_run,
    create_order,
    deliver_flow,
    get_licensor,
    make_licensing_ops_headers,
    pick_order,
    set_clock,
    ship_order,
)


def test_two_rows_are_rounded_to_the_cent_before_they_are_summed(api):
    """PRD §3.8: "Two delivered orders of 1250 cents each on a cap design, at a
    0.06 rate and a 0.125 premium, give per-row values of 75 cents of royalty and
    9.38 cents of premium — 75 plus 9.375 rounded half up — for a row total of
    84.38 cents, and a two-row ledger of 168.76 cents."
    PRD §3.8: "The rounding sequence is the substance of the rule and it is
    pinned: each row is rounded to the cent before the rows are summed, and the
    sum is then taken as it stands."

    Design: Difficulty/dual_variant_calc/royalty_accrual_per_row_then_sum
    """
    set_clock(api)
    setup = committed_run(api, base_qty=2000, licensor_overrides={
        "name": "NBL Properties", "royalty_rate_pct": 0.125,
        "minimum_guarantee_cents": 200000,
    }, design_overrides={"team_code": "BOS", "garment_sku": "CAP",
                        "design_name": "BOS Champs Cap"})

    first = create_order(api, setup["run"], channel="ECOM",
                         destination_code="ECOM-BOS-1", quantity=250)
    deliver_flow(api, setup["run"]["id"], first, 250, "pick-a")

    second = create_order(api, setup["run"], channel="ECOM",
                          destination_code="ECOM-BOS-2", quantity=250)
    deliver_flow(api, setup["run"]["id"], second, 250, "pick-b")

    licensor = validate_success(
        api.get_licensor(
            setup["licensor"]["id"],
            make_licensing_ops_headers(setup["licensor"]["id"]),
        ),
        expected_status=200,
    )
    assert licensor["accrued_royalty_cents"] == 168.76


def test_the_two_row_ledger_is_not_the_single_rounded_sum(api):
    """PRD §3.8: "Rounding the combined unrounded figure once instead gives 168.75
    cents. The per-row sequence is the specification"

    Design: Difficulty/dual_variant_calc/royalty_accrual_per_row_then_sum
    """
    set_clock(api)
    setup = committed_run(api, base_qty=2000, licensor_overrides={
        "name": "NBL Properties 2", "royalty_rate_pct": 0.125,
        "minimum_guarantee_cents": 200000,
    }, design_overrides={"team_code": "BOS", "garment_sku": "CAP"})

    for index, remark in enumerate(("pick-x", "pick-y"), start=1):
        order = create_order(api, setup["run"], channel="ECOM",
                             destination_code=f"ECOM-BOS-{index}", quantity=250)
        deliver_flow(api, setup["run"]["id"], order, 250, remark)

    licensor = get_licensor(
        api, setup["licensor"]["id"],
        make_licensing_ops_headers(setup["licensor"]["id"]),
    )
    assert licensor["accrued_royalty_cents"] != 168.75
    assert licensor["accrued_royalty_cents"] == 168.76


def test_a_single_cap_row_accrues_the_per_row_figure(api):
    """PRD §3.8: "The row's royalty is the gross multiplied by that rate, rounded
    half up to the cent. A designer premium of 0.125 is then applied to the row's
    royalty, rounded half up to the cent, and the row's total is the royalty plus
    the premium."

    Design: Corner/cross_cutting_complexity_layers/designer_premium_rate_delta_across_accrual_variants
    """
    set_clock(api)
    setup = committed_run(api, base_qty=2000, design_overrides={
        "team_code": "PHI", "garment_sku": "CAP", "design_name": "AM Cap",
    }, licensor_overrides={"name": "Licensor AM", "royalty_rate_pct": 0.1})

    order = create_order(api, setup["run"], channel="ECOM",
                         destination_code="ECOM-PHI-9", quantity=250)
    deliver_flow(api, setup["run"]["id"], order, 250, "pick-am")

    licensor = get_licensor(
        api, setup["licensor"]["id"],
        make_licensing_ops_headers(setup["licensor"]["id"]),
    )
    assert licensor["accrued_royalty_cents"] == 84.38


def test_delivery_reaches_the_licensor_aggregate_in_the_same_request(api):
    """PRD §3.6: "it increments the `Licensor`'s `version` by 1 with
    `accrued_royalty_cents` recomputed from the delivered units per §3.8."

    Design: Corner/cross_cutting_complexity_layers/delivery_cascade_reaches_the_licensor_ledger
    """
    set_clock(api)
    setup = committed_run(api, base_qty=2000, design_overrides={
        "team_code": "BOS", "garment_sku": "CAP", "design_name": "AO Cap",
    })
    order = create_order(api, setup["run"], channel="ECOM",
                         destination_code="ECOM-BOS-8", quantity=250)
    pick_order(api, order, setup["run"]["id"], 250, "pick-ao")
    ship_order(api, order, 250)

    headers = make_licensing_ops_headers(setup["licensor"]["id"])
    before = get_licensor(api, setup["licensor"]["id"], headers)
    assert before["accrued_royalty_cents"] == 0

    validate_success(api.deliver(order["id"], {}, FULFILLMENT),
                     expected_status=200)

    after = get_licensor(api, setup["licensor"]["id"], headers)
    assert after["accrued_royalty_cents"] == 84.38
    assert after["accrued_unsettled_cents"] == 84.38
    assert after["version"] > before["version"]


def test_a_distressed_order_never_accrues_a_royalty(api):
    """PRD §3.8: "Orders in `PLANNED`, `PICKED`, `SHIPPED` or `DISTRESSED`
    contribute nothing at all, and a `DISTRESSED` order never accrues a royalty on
    any path: distressed goods are destroyed or donated, and destroyed or donated
    goods do not earn."

    Design: Corner/cross_cutting_complexity_layers/delivery_cascade_reaches_the_licensor_ledger
    """
    set_clock(api)
    setup = committed_run(api, base_qty=2000, design_overrides={
        "team_code": "PHI", "garment_sku": "TRACTOR", "design_name": "AQ Tractor",
    })
    order = create_order(api, setup["run"], channel="VENUE_RETAIL",
                         destination_code="PHI_TEAMSTORE", quantity=100)

    validate_success(
        api.distress(
            order["id"],
            {"distress_reason": "DEMAND_COLLAPSE", "destroy_mode": "DESTROY"},
            FULFILLMENT,
        ),
        expected_status=200,
    )

    licensor = get_licensor(
        api, setup["licensor"]["id"],
        make_licensing_ops_headers(setup["licensor"]["id"]),
    )
    assert licensor["accrued_royalty_cents"] == 0


def test_a_pennant_earns_nothing(api):
    """PRD §3.8: "a `MINI` 0.06 and a `PENNANT` nothing at all — pennants are a
    promotional giveaway as far as royalty is concerned."

    Design: Corner/cross_cutting_complexity_layers/designer_premium_rate_delta_across_accrual_variants
    """
    set_clock(api)
    setup = committed_run(api, base_qty=2000,
                          design_overrides={"garment_sku": "PENNANT"})
    order = create_order(api, setup["run"], channel="ECOM",
                         destination_code="ECOM-PEN-1", quantity=250)
    deliver_flow(api, setup["run"]["id"], order, 250, "pick-pen")

    licensor = get_licensor(
        api, setup["licensor"]["id"],
        make_licensing_ops_headers(setup["licensor"]["id"]),
    )
    assert licensor["accrued_royalty_cents"] == 0


def test_the_accrual_register_is_readable_by_the_read_only_role(api):
    """PRD §4: "GET | `/royalty-accruals` | List royalty accrual rows filtered by
    licensor, production order or basis | LicensingOps, AuditOnly"

    Design: Corner/rbac/audit_role_reads_every_ledger
    """
    from test_helpers import TEST_USERS

    set_clock(api)
    setup = committed_run(api, base_qty=2000, design_overrides={
        "team_code": "ATL", "garment_sku": "CAP", "design_name": "AH Cap",
    })
    order = create_order(api, setup["run"], channel="ECOM",
                         destination_code="ECOM-ATL-7", quantity=250)
    deliver_flow(api, setup["run"]["id"], order, 250, "pick-ah")

    resp = api.list_royalty_accruals(TEST_USERS["audit_only_headers"])
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["response_type"] == "array"
    rows = body["data"]
    assert len(rows) >= 1
    for field in ("limit", "offset", "total_count", "has_more"):
        assert field in body["meta"]