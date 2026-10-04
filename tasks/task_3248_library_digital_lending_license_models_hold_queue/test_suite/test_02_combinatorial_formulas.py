"""Combinatorial formulas: per-event CPC rounding and consortium allocation."""
from test_helpers import (
    ADMIN,
    checkout,
    create_consortium,
    create_fund,
    create_library,
    create_license_via_order,
    create_patron,
    create_title,
    get_success_data,
    make_library_admin_headers,
    set_clock,
    setup_base,
    setup_base_with_title,
    validate_success,
)


def _setup_cpc_license(discount=0.25, cpc_price=299, prepaid=5000):
    """Consortium with the given CPC discount; one fulfilled CPC license."""
    set_clock()
    consortium = create_consortium(cpc_discount_pct=discount)
    library = create_library(consortium["id"])
    fund = create_fund(library["id"])
    title = create_title(consortium["id"], cpc_price_per_circ_cents=cpc_price)
    license_ = create_license_via_order(
        library["id"], fund["id"], title["id"],
        model="COST_PER_CIRC", prepaid_balance_cents=prepaid,
    )
    return {"consortium": consortium, "library": library, "fund": fund,
            "title": title, "license": license_}


def test_cpc_per_event_rounding_charge_on_loan(api):
    """PRD §2.7: "each checkout's discounted charge is computed by multiplying
    the title's `cpc_price_per_circ_cents` by the complement of the
    consortium's `cpc_discount_pct` (that is, one minus the discount fraction)
    and rounding the result half-up to whole cents immediately, per checkout
    event."

    Design: Difficulty/combinatorial_formula/cpc_per_event_rounding_beats_sum_then_round
    """
    ctx = _setup_cpc_license()
    p0 = create_patron(ctx["library"]["id"], external_card_number="P-0",
                       full_name="Patron Zero")
    loan = checkout(p0["id"], ctx["title"]["id"])
    assert loan["circ_price_charged_cents"] == 224, (
        f"round_half_up(299 * 0.75) == 224, got {loan['circ_price_charged_cents']}"
    )


def test_cpc_per_event_rounding_accumulates_rounded_charges(api):
    """PRD §2.7: "Only after that per-event rounding does the system
    accumulate: the license's balance is decremented by the already-rounded
    charge, the loan's `circ_price_charged_cents` records the already-rounded
    charge, and the patron's home-library fund accrues the already-rounded
    charge. The fractional product is never carried across events."

    Design: Difficulty/combinatorial_formula/cpc_per_event_rounding_beats_sum_then_round
    """
    ctx = _setup_cpc_license()
    lib_admin = make_library_admin_headers(ctx["library"]["id"])
    for i in range(3):
        p = create_patron(ctx["library"]["id"], external_card_number=f"P-{i}",
                          full_name=f"Patron {i}")
        checkout(p["id"], ctx["title"]["id"])
    lic = validate_success(
        api.get_license(ctx["license"]["id"], lib_admin)
    )
    assert lic["balance_cents"] == 5000 - 3 * 224 == 4328
    fund = validate_success(api.get_fund(ctx["fund"]["id"], lib_admin))
    assert fund["cpc_accrued_cents"] == 672, (
        "per-event rounding yields 3 * 224 == 672, not the 673 of sum-then-round"
    )


def _setup_consortium_allocation():
    """Libraries H/A/B; shared CONSORTIUM title; H fulfills an OCOU order
    invoiced 10000; checkout counts H=10, A=50, B=40 in the invoice window."""
    set_clock()
    consortium = create_consortium()  # floor 0.25
    lib_h = create_library(consortium["id"], name="Library H")
    lib_a = create_library(consortium["id"], name="Library A")
    lib_b = create_library(consortium["id"], name="Library B")
    fund_h = create_fund(lib_h["id"])
    pat_h = create_patron(lib_h["id"], external_card_number="PH-1",
                          full_name="Patron H")
    pat_a = create_patron(lib_a["id"], external_card_number="PA-1",
                          full_name="Patron A")
    pat_b = create_patron(lib_b["id"], external_card_number="PB-1",
                          full_name="Patron B")
    title = create_title(consortium["id"], price_ocou_cents=10000,
                         sharing_scope="CONSORTIUM")
    create_license_via_order(
        lib_h["id"], fund_h["id"], title["id"],
        model="OCOU", copies=1, invoiced_cost_cents=10000,
    )
    set_clock("2026-09-02T00:00:00Z")
    loan = checkout(pat_h["id"], title["id"])
    from test_helpers import make_patron_headers, api_client
    api_client.return_loan(loan["id"], make_patron_headers(pat_h["id"]))
    api_client.run_epoch(ADMIN)
    resp = api_client.drive_circulation(
        {
            "title_id": title["id"],
            "by_library": [
                {"library_id": lib_h["id"], "patron_id": pat_h["id"],
                 "checkouts": 9},
                {"library_id": lib_a["id"], "patron_id": pat_a["id"],
                 "checkouts": 50},
                {"library_id": lib_b["id"], "patron_id": pat_b["id"],
                 "checkouts": 40},
            ],
        },
        ADMIN,
    )
    assert resp.status_code == 200, f"drive_circulation failed: {resp.text}"
    return {"consortium": consortium, "lib_h": lib_h, "lib_a": lib_a,
            "lib_b": lib_b, "title": title}


def _line_for(invoice: dict, library_id: str) -> int:
    for line in invoice["lines"]:
        if line["library_id"] == library_id:
            return line["share_cents"]
    raise AssertionError(f"no invoice line for library {library_id}")


def test_consortium_allocation_host_floor_binds_and_remainder_prorates(api):
    """PRD §3.12: "The host's share is the larger of two quantities: its
    proportional usage share (T times the host's checkout count over the total
    checkout count, with a zero total treated as 1, rounded half-up to whole
    cents) and the host floor (`host_share_floor_pct` times T, rounded half-up
    to whole cents). When the floor binds, the remainder pool is computed on T
    minus the floor, not on T."

    Design: Difficulty/combinatorial_formula/consortium_allocation_host_floor_prorata_remainder
    """
    ctx = _setup_consortium_allocation()
    resp = api.generate_invoice(
        ctx["consortium"]["id"],
        {"period_start": "2026-09-01T00:00:00Z",
         "period_end": "2026-10-01T00:00:00Z"},
        ADMIN,
    )
    invoice = validate_success(resp, expected_status=201)
    assert _line_for(invoice, ctx["lib_h"]["id"]) == 2500, (
        "max(round_half_up(10000*10/100), round_half_up(10000*0.25)) == 2500"
    )
    assert _line_for(invoice, ctx["lib_a"]["id"]) == 4167, (
        "round_half_up(7500*50/90) == 4167"
    )
    assert _line_for(invoice, ctx["lib_b"]["id"]) == 3333, (
        "round_half_up(7500*40/90) == 3333"
    )


def test_consortium_allocation_lines_sum_to_total(api):
    """PRD §3.12: "The invoice's `lines` array carries one `{ library_id,
    share_cents }` entry per library with a nonzero share, and `total_cents` is
    their sum."

    Design: Difficulty/combinatorial_formula/consortium_allocation_host_floor_prorata_remainder
    """
    ctx = _setup_consortium_allocation()
    resp = api.generate_invoice(
        ctx["consortium"]["id"],
        {"period_start": "2026-09-01T00:00:00Z",
         "period_end": "2026-10-01T00:00:00Z"},
        ADMIN,
    )
    invoice = validate_success(resp, expected_status=201)
    assert invoice["total_cents"] == 10000
    assert sum(line["share_cents"] for line in invoice["lines"]) == 10000, (
        "residual cents must land on the largest non-host sharer so lines sum exactly"
    )
