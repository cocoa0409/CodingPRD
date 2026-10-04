"""Dual-variant calculations: wait estimates and fund availability."""
from test_helpers import (
    ADMIN,
    create_fund,
    create_license_via_order,
    create_patron,
    create_title,
    get_success_data,
    make_library_admin_headers,
    make_patron_headers,
    place_hold,
    checkout,
    set_clock,
    setup_base,
    setup_base_with_title,
    validate_success,
)


def _setup_wait_queue():
    """Library L (21d loans, 2x21d renewals), one OCOU copy on loan to P0,
    and three PLACED holds P1..P3 on the same title."""
    ctx = setup_base_with_title()
    lib = ctx["library"]
    lib_admin = make_library_admin_headers(lib["id"])
    create_license_via_order(lib["id"], ctx["fund"]["id"], ctx["title"]["id"],
                             model="OCOU", copies=1)
    p0 = create_patron(lib["id"], external_card_number="P-0", full_name="Patron Zero")
    checkout(p0["id"], ctx["title"]["id"])
    holds = []
    patrons = []
    for i in (1, 2, 3):
        p = create_patron(lib["id"], external_card_number=f"P-{i}",
                          full_name=f"Patron {i}")
        patrons.append(p)
        holds.append(place_hold(p["id"], ctx["title"]["id"]))
    ctx.update({"p0": p0, "patrons": patrons, "holds": holds,
                "lib_admin": lib_admin})
    return ctx


def test_wait_estimate_optimistic_vs_pessimistic_hold_fields(api):
    """PRD §3.9: "The optimistic variant multiplies those cycles by the
    library's `loan_period_days` — it assumes every current loan comes back at
    its first due date with no renewals. The pessimistic variant multiplies the
    same cycles by the full possible loan tenure: `loan_period_days` plus
    `max_renewals` times `renewal_period_days`."

    Design: Difficulty/dual_variant_calc/wait_estimate_optimistic_vs_pessimistic_queue_cycles
    """
    ctx = _setup_wait_queue()
    hold3 = ctx["holds"][2]
    p3 = ctx["patrons"][2]
    resp = api.get_hold(hold3["id"], make_patron_headers(p3["id"]))
    data = validate_success(resp)
    assert data["optimistic_wait_days"] == 63, (
        f"expected ceil(3/1) * 21 == 63, got {data['optimistic_wait_days']}"
    )
    assert data["pessimistic_wait_days"] == 189, (
        f"expected ceil(3/1) * (21 + 2*21) == 189, got {data['pessimistic_wait_days']}"
    )


def test_wait_estimate_availability_read_shows_same_dual_variant(api):
    """PRD §3.6: "The title-level availability view reports, from the
    perspective of a chosen library (the `library_id` query parameter,
    defaulting to the requesting patron's home library), four numbers:
    `copies_available`, the `active_holds` queue depth, and the
    `optimistic_wait_days` and `pessimistic_wait_days` a new arrival should
    expect."
    PRD §3.9: "The pessimistic estimate is always at least the optimistic one,
    and strictly greater whenever the library allows any renewals and there is
    at least one hold ahead."

    Design: Difficulty/dual_variant_calc/wait_estimate_optimistic_vs_pessimistic_queue_cycles
    """
    ctx = _setup_wait_queue()
    resp = api.get_title_availability(
        ctx["title"]["id"], ctx["lib_admin"],
        params={"library_id": ctx["library"]["id"]},
    )
    avail = validate_success(resp)
    assert avail["copies_available"] == 0
    assert avail["active_holds"] == 3
    assert avail["pessimistic_wait_days"] - avail["optimistic_wait_days"] == 126, (
        "the renewal-assumption delta is 2 * 21 * 3 == 126"
    )


def _setup_approved_unfulfilled_order():
    """Fund budget 1000000; one OCOU order (estimate 5000) proposed and
    approved but NOT fulfilled."""
    ctx = setup_base_with_title()
    lib = ctx["library"]
    from test_helpers import create_order, propose_order, approve_order
    order = create_order(lib["id"], ctx["fund"]["id"], ctx["title"]["id"],
                         model="OCOU", copies=1)
    propose_order(lib["id"], order["id"])
    approve_order(lib["id"], order["id"])
    ctx["order"] = order
    ctx["lib_admin"] = make_library_admin_headers(lib["id"])
    return ctx


def test_fund_availability_committed_vs_actual_variants(api):
    """PRD §3.10: "The forward-looking `available_committed_cents` is
    `budget_cents` minus `committed_cents` minus `spent_cents` minus
    `cpc_accrued_cents`; the actuals-only `available_actual_cents` is
    `budget_cents` minus `spent_cents` minus `cpc_accrued_cents`."

    Design: Difficulty/dual_variant_calc/fund_availability_committed_vs_actual_gap
    """
    ctx = _setup_approved_unfulfilled_order()
    resp = api.get_fund(ctx["fund"]["id"], ctx["lib_admin"])
    fund = validate_success(resp)
    assert fund["committed_cents"] == 5000
    assert fund["spent_cents"] == 0
    assert fund["available_committed_cents"] == 995000
    assert fund["available_actual_cents"] == 1000000


def test_fund_availability_variants_diverge_by_exactly_the_commitment(api):
    """PRD §3.10: "identical inputs always yield `available_actual_cents` at
    least `available_committed_cents`, strictly greater whenever any
    approved-but-unfulfilled order exists."

    Design: Difficulty/dual_variant_calc/fund_availability_committed_vs_actual_gap
    """
    ctx = _setup_approved_unfulfilled_order()
    resp = api.get_fund(ctx["fund"]["id"], ctx["lib_admin"])
    fund = validate_success(resp)
    gap = fund["available_actual_cents"] - fund["available_committed_cents"]
    assert gap == 5000, (
        f"the two variants must diverge by exactly the 5000-cent commitment, got {gap}"
    )
