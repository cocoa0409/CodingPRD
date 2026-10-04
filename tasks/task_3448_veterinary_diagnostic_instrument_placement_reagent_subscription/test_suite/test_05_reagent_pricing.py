"""Reagent ordering: layered price resolution, commitment inputs, pagination (PRD §2.3, §3.4, §3.5)."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_pricing_line,
    cancel_reagent_order,
    create_group_pricing_agreement,
    create_reagent_order_payload,
    extract_pricing_lines,
    fulfill_reagent_order,
    get_reagent_order,
    list_commitment_periods,
    make_clinic_manager_headers,
    patch_reagent_order_payload,
    place_reagent_order,
    reagent_line,
    setup_clinic_with_active_reagent_commitment,
    setup_clinic_with_rc_and_purchase_agreements,
    sku_override,
    validate_error,
    validate_paginated,
    validate_success,
)

_FINANCE = TEST_USERS["finance_reviewer_headers"]


def _dual_group_scenario() -> dict:
    """Clinic in BOTH a corporate (10%, VH500_CBC_CART override 800c) and a
    buying (20%) group, with an ACTIVE reagent-commitment agreement."""
    create_group_pricing_agreement(
        group_type="CORPORATE", group_code="CORP-1", discount_pct=0.10,
        sku_overrides=[sku_override("VH500_CBC_CART", 800)],
    )
    create_group_pricing_agreement(
        group_type="BUYING", group_code="BUY-1", discount_pct=0.20,
    )
    return setup_clinic_with_active_reagent_commitment(
        clinic_kwargs={"corporate_group_code": "CORP-1", "buying_group_code": "BUY-1"}
    )


def _layered_order(scenario: dict) -> dict:
    return place_reagent_order(
        scenario["clinic"]["id"], scenario["agreement"]["id"],
        order_month="2026-09",
        lines=[
            reagent_line("VH500_CBC_CART", 10),
            reagent_line("VC300_CHEM_SLIDE", 100),
            reagent_line("QC_LEVEL_1", 2),
        ],
    )


def test_layered_pricing_corporate_precedence_excludes_buying(api):
    """PRD §3.1: "When a clinic carries a `corporate_group_code`, only
    corporate group pricing agreements with that code ever apply to the
    clinic's orders — buying-group agreements are never consulted for that
    clinic". PRD §3.4: "the unit price is the catalog `list_price_cents`
    reduced by `discount_pct` — computed as the list price multiplied by one
    minus the discount fraction, rounded half up to a whole cent — with
    `price_source` `CORPORATE_DISCOUNT` or `BUYING_DISCOUNT` as the group
    type dictates." The slide line resolves at round_half_up(420 * 0.9) =
    378c; the buying-group 20% tier (336c) is never consulted.

    Design: Difficulty/combinatorial_formula/layered_pricing_override_membership_program
    """
    scenario = _dual_group_scenario()
    order = _layered_order(scenario)
    lines = extract_pricing_lines(order["pricing_detail"])
    assert_pricing_line(lines[1], "VC300_CHEM_SLIDE", 378, "CORPORATE_DISCOUNT", 37800)
    assert order["final_total_cents"] == 45800  # 8000 + 37800 + 0


def test_layered_pricing_override_and_program_included_branches(api):
    """PRD §3.4: "when the applying agreement's `sku_overrides` covers the
    `sku`, that entry's `unit_price_cents` wins, with `price_source`
    `OVERRIDE`." PRD §3.4: "Quality-control material — any `sku` of the
    `QC_MATERIAL` family — ordered under a `REAGENT_COMMITMENT` agreement is
    bundled into the program: the line prices at zero cents with
    `price_source` `PROGRAM_INCLUDED`." PRD §3.4: "For comparison reporting,
    `list_total_cents` sums the undiscounted list price times quantity over
    all lines."

    Design: Difficulty/combinatorial_formula/layered_pricing_override_membership_program
    """
    scenario = _dual_group_scenario()
    order = _layered_order(scenario)
    lines = extract_pricing_lines(order["pricing_detail"])
    assert_pricing_line(lines[0], "VH500_CBC_CART", 800, "OVERRIDE", 8000)
    assert_pricing_line(lines[2], "QC_LEVEL_1", 0, "PROGRAM_INCLUDED", 0)
    assert order["list_total_cents"] == 56900  # 8900 + 42000 + 6000
    assert order["final_total_cents"] == 45800


def test_qc_material_zero_priced_only_on_reagent_commitment(api):
    """PRD §3.4: "Quality-control material — any `sku` of the `QC_MATERIAL`
    family — ordered under a `REAGENT_COMMITMENT` agreement is bundled into
    the program: the line prices at zero cents with `price_source`
    `PROGRAM_INCLUDED`." PRD §3.4: "Otherwise the line prices at the catalog
    list price with `price_source` `LIST`."

    Design: Corner/calculations/qc_material_zero_priced_only_on_reagent_commitment
    """
    scenario = setup_clinic_with_rc_and_purchase_agreements()
    clinic = scenario["clinic"]

    on_rc = place_reagent_order(
        clinic["id"], scenario["rc_agreement"]["id"],
        order_month="2026-09", lines=[reagent_line("QC_LEVEL_1", 2)],
    )
    assert on_rc["final_total_cents"] == 0
    assert_pricing_line(
        extract_pricing_lines(on_rc["pricing_detail"])[0],
        "QC_LEVEL_1", 0, "PROGRAM_INCLUDED", 0,
    )

    on_purchase = place_reagent_order(
        clinic["id"], scenario["purchase_agreement"]["id"],
        order_month="2026-09", lines=[reagent_line("QC_LEVEL_1", 2)],
    )
    assert on_purchase["final_total_cents"] == 6000  # 2 x 3000 LIST
    assert_pricing_line(
        extract_pricing_lines(on_purchase["pricing_detail"])[0],
        "QC_LEVEL_1", 3000, "LIST", 6000,
    )


def test_order_month_outside_agreement_term_rejected(api):
    """PRD §3.4: "The order declares its `order_month` in YYYY-MM form, which
    must fall within the agreement's term months (`ERR_INVALID_REQUEST`)".

    Design: Corner/calculations/order_month_outside_agreement_term_rejected
    """
    scenario = setup_clinic_with_active_reagent_commitment()
    clinic = scenario["clinic"]
    agreement = scenario["agreement"]  # term months 2026-09 .. 2028-08
    cm = make_clinic_manager_headers(clinic["id"])

    for bad_month in ("2026-08", "2030-01"):
        resp = api_client.create_reagent_order(
            create_reagent_order_payload(
                clinic["id"], agreement["id"],
                order_month=bad_month, lines=[reagent_line("VC300_CHEM_SLIDE", 1)],
            ),
            cm,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    data, _meta = validate_paginated(api_client.list_reagent_orders(
        _FINANCE, params={"agreement_id": agreement["id"]}
    ))
    assert data == []


def test_create_response_carries_locked_pricing_immediately(api):
    """PRD §2.5: "Consistency is immediate: every mutation a request triggers
    — including cascades onto other resources and recomputed derived fields —
    is visible in that same request's response." PRD §3.4: "The whole
    computation is frozen at creation into the immutable `pricing_detail`
    snapshot — per-line `unit_price_cents`, `price_source`, and
    `line_total_cents` — and `final_total_cents` never changes afterwards."

    Design: Corner/consistency_model/create_response_carries_locked_pricing_immediately
    """
    scenario = setup_clinic_with_active_reagent_commitment()
    clinic = scenario["clinic"]
    agreement = scenario["agreement"]

    created = validate_success(api_client.create_reagent_order(
        create_reagent_order_payload(
            clinic["id"], agreement["id"],
            order_month="2026-09",
            lines=[reagent_line("VC300_CHEM_SLIDE", 10), reagent_line("QC_LEVEL_1", 1)],
        ),
        make_clinic_manager_headers(clinic["id"]),
    ), 201)
    assert created["final_total_cents"] == 4200  # 10 x 420 + 1 x 0

    fetched = get_reagent_order(created["id"])
    assert fetched["final_total_cents"] == 4200
    assert fetched["pricing_detail"] == created["pricing_detail"]
    lines = extract_pricing_lines(fetched["pricing_detail"])
    assert_pricing_line(lines[0], "VC300_CHEM_SLIDE", 420, "LIST", 4200)
    assert_pricing_line(lines[1], "QC_LEVEL_1", 0, "PROGRAM_INCLUDED", 0)


def test_reagent_orders_list_paginates_and_filters(api):
    """PRD §2.3: "`limit` sets the maximum number of items returned: it
    defaults to 10, with a minimum of 1 and a maximum of 100. `offset` sets
    the number of items skipped and defaults to 0." PRD §2.3: "The `meta`
    object of every list response carries the pagination fields `limit`,
    `offset`, `total_count`, and `has_more`." PRD §3.4: "Orders list with
    `clinic_id`, `agreement_id`, and `status` filters."

    Design: Corner/entities/reagent_orders_list_paginates_and_filters
    """
    scenario = setup_clinic_with_active_reagent_commitment()
    clinic = scenario["clinic"]
    agreement = scenario["agreement"]
    place_reagent_order(clinic["id"], agreement["id"],
                        order_month="2026-09", lines=[reagent_line("VC300_CHEM_SLIDE", 10)])
    place_reagent_order(clinic["id"], agreement["id"],
                        order_month="2026-09", lines=[reagent_line("VC300_LYTE_CART", 10)])
    third = place_reagent_order(clinic["id"], agreement["id"],
                                order_month="2026-10", lines=[reagent_line("VU200_URINE_STRIP", 10)])
    fulfill_reagent_order(third["id"], clinic["id"])

    page1, meta1 = validate_paginated(api_client.list_reagent_orders(
        _FINANCE, params={"agreement_id": agreement["id"], "limit": 2, "offset": 0}
    ))
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True

    page2, meta2 = validate_paginated(api_client.list_reagent_orders(
        _FINANCE, params={"agreement_id": agreement["id"], "limit": 2, "offset": 2}
    ))
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False

    fulfilled, _meta3 = validate_paginated(api_client.list_reagent_orders(
        _FINANCE, params={"agreement_id": agreement["id"], "status": "FULFILLED"}
    ))
    assert [row["id"] for row in fulfilled] == [third["id"]]

    default_page, meta4 = validate_paginated(api_client.list_reagent_orders(
        _FINANCE, params={"agreement_id": agreement["id"]}
    ))
    assert len(default_page) == 3
    assert meta4["limit"] == 10
    assert meta4["offset"] == 0


def test_reagent_order_terminal_lockdown_after_cancel(api):
    """PRD §3.4: "an order no longer `SUBMITTED` rejects either drive with
    `ERR_ORDER_INVALID_STATE`". PRD §3.4: "the order becomes `CANCELLED`,
    `fulfilled_at` stays null". PRD §3.5: "`SUBMITTED` and `CANCELLED` orders
    never count toward either variant".

    Design: Corner/state_machines/reagent_order_terminal_lockdown_after_cancel
    """
    scenario = setup_clinic_with_active_reagent_commitment()
    clinic = scenario["clinic"]
    agreement = scenario["agreement"]
    order = place_reagent_order(
        clinic["id"], agreement["id"],
        order_month="2026-09", lines=[reagent_line("VC300_CHEM_SLIDE", 5)],
    )
    cancel_reagent_order(order["id"], clinic["id"])

    resp = api_client.update_reagent_order(
        order["id"], patch_reagent_order_payload("FULFILLED"),
        make_clinic_manager_headers(clinic["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_ORDER_INVALID_STATE)

    after = get_reagent_order(order["id"])
    assert after["status"] == "CANCELLED"
    assert after["fulfilled_at"] is None
    periods = list_commitment_periods(agreement["id"])
    assert periods[0]["provisional_fulfilled_cents"] == 0


def test_order_cancel_conserves_provisional_commitment_total(api):
    """PRD §3.4: "a compensating invariant holds — a cancelled order was
    never fulfilled, so every commitment total is unchanged by it." PRD §3.5:
    "`SUBMITTED` and `CANCELLED` orders never count toward either variant".

    Design: Difficulty/compensating_invariant/order_cancel_conserves_commitment_fulfillment
    """
    scenario = setup_clinic_with_active_reagent_commitment()
    clinic = scenario["clinic"]
    agreement = scenario["agreement"]
    fulfilled_order = place_reagent_order(
        clinic["id"], agreement["id"], order_month="2026-09",
        lines=[reagent_line("VC300_CHEM_SLIDE", 100)],
    )
    fulfill_reagent_order(fulfilled_order["id"], clinic["id"])
    before = list_commitment_periods(agreement["id"])[0]["provisional_fulfilled_cents"]
    assert before == 42000

    cancelled = place_reagent_order(
        clinic["id"], agreement["id"], order_month="2026-09",
        lines=[reagent_line("VH500_CBC_CART", 10)],
    )
    cancel_reagent_order(cancelled["id"], clinic["id"])

    after = list_commitment_periods(agreement["id"])[0]["provisional_fulfilled_cents"]
    assert after == 42000  # the 8900c cancelled order never entered attribution


def test_order_cancel_leaves_fulfilled_set_unchanged(api):
    """PRD §3.4: "Cancellation, also by the owning manager and also only from
    `SUBMITTED`, carries no clinic- or agreement-state gates: the order
    becomes `CANCELLED`, `fulfilled_at` stays null". PRD §3.5: the
    attribution input set is "the agreement's `FULFILLED` orders" only.

    Design: Difficulty/compensating_invariant/order_cancel_conserves_commitment_fulfillment
    """
    scenario = setup_clinic_with_active_reagent_commitment()
    clinic = scenario["clinic"]
    agreement = scenario["agreement"]
    fulfilled_order = place_reagent_order(
        clinic["id"], agreement["id"], order_month="2026-09",
        lines=[reagent_line("VC300_CHEM_SLIDE", 100)],
    )
    fulfill_reagent_order(fulfilled_order["id"], clinic["id"])
    cancelled = place_reagent_order(
        clinic["id"], agreement["id"], order_month="2026-09",
        lines=[reagent_line("VH500_CBC_CART", 10)],
    )
    cancel_reagent_order(cancelled["id"], clinic["id"])

    after = get_reagent_order(cancelled["id"])
    assert after["status"] == "CANCELLED"
    assert after["fulfilled_at"] is None

    rows, meta = validate_paginated(api_client.list_reagent_orders(
        _FINANCE, params={"agreement_id": agreement["id"], "status": "FULFILLED"}
    ))
    assert meta["total_count"] == 1
    assert rows[0]["id"] == fulfilled_order["id"]
    assert rows[0]["final_total_cents"] == 42000
