"""Corner coverage: cross-cutting layers (fund accrual reconciliation, epoch
idempotence, sharing-scope tenancy) and immediate consistency."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    checkout,
    create_consortium,
    create_library,
    create_license_via_order,
    create_patron,
    create_title,
    make_library_admin_headers,
    make_patron_headers,
    place_hold,
    setup_base_with_title,
    setup_ocou_library,
    validate_error,
    validate_success,
)


def test_cpc_accrual_reconciles_fund_after_checkouts(api):
    """PRD §3.10: "`cpc_accrued_cents` is the sum of `charge_cents` over
    cost-per-circulation `CHECKOUT` events by this library's patrons whose
    `occurred_at` falls inside the fund's period. The forward-looking
    `available_committed_cents` is `budget_cents` minus `committed_cents` minus
    `spent_cents` minus `cpc_accrued_cents`."

    Design: Corner/cross_cutting_layers/cpc_accrual_reconciles_fund_after_checkout_and_snapshot
    """
    ctx = setup_base_with_title()
    lib = ctx["library"]
    lib_admin = make_library_admin_headers(lib["id"])
    create_license_via_order(lib["id"], ctx["fund"]["id"], ctx["title"]["id"],
                             model="COST_PER_CIRC", prepaid_balance_cents=5000)
    p0 = create_patron(lib["id"], external_card_number="P-0", full_name="Patron Zero")
    p1 = create_patron(lib["id"], external_card_number="P-1", full_name="Patron One")
    loan0 = checkout(p0["id"], ctx["title"]["id"])
    charge = loan0["circ_price_charged_cents"]
    # PRD §2.7 pins per-event half-up rounding of price * (1 - discount) but
    # not the arithmetic representation; 199 * 0.85 rounds to 169 (exact
    # decimal) or 170 (design's reference computation). Reconcile the fund
    # against whatever the already-rounded per-event charge was.
    fund = validate_success(api.get_fund(ctx["fund"]["id"], lib_admin))
    assert fund["cpc_accrued_cents"] == charge
    checkout(p1["id"], ctx["title"]["id"])
    fund = validate_success(api.get_fund(ctx["fund"]["id"], lib_admin))
    assert fund["cpc_accrued_cents"] == 2 * charge
    assert fund["available_committed_cents"] == 1000000 - 5000 - 2 * charge


def test_epoch_run_is_idempotent_when_nothing_is_due(api):
    """PRD §2.5: "Running an epoch performs, in this exact order: (1) expiring
    due loans, (2) expiring READY holds whose pickup window has closed, (3)
    expiring metered licenses past their term, (4) expiring patron cards past
    their validity date, (5) marking depleted licenses `EXHAUSTED`, (6) the
    auto-purchase sweep, and (7) the hold-promotion sweep. The epoch response
    reports how many items each stage touched: `expired_loans`,
    `expired_holds`, `expired_licenses`, `exhausted_licenses`,
    `expired_patrons`, `auto_orders_created`, and `holds_promoted`."

    Design: Corner/cross_cutting_layers/epoch_run_is_idempotent_when_nothing_is_due
    """
    ctx = setup_ocou_library(copies=1)
    p0 = create_patron(ctx["library"]["id"], external_card_number="P-0",
                       full_name="Patron Zero")
    loan0 = checkout(p0["id"], ctx["title"]["id"])
    before = validate_success(
        api.get_loan(loan0["id"], make_patron_headers(p0["id"]))
    )
    epoch = validate_success(api.run_epoch(ADMIN))
    assert epoch["expired_loans"] == 0
    assert epoch["expired_holds"] == 0
    assert epoch["expired_licenses"] == 0
    assert epoch["expired_patrons"] == 0
    assert epoch["auto_orders_created"] == 0
    assert epoch["holds_promoted"] == 0
    after = validate_success(
        api.get_loan(loan0["id"], make_patron_headers(p0["id"]))
    )
    assert after["version"] == before["version"]
    assert after["status"] == "ACTIVE"


def test_consortium_visibility_gate_blocks_local_only_title(api):
    """PRD §3.2: "When it is `LOCAL_ONLY`, only the purchasing library's
    patrons ever touch it."
    PRD §3.5: "If no eligible license exists, the checkout fails with
    `ERR_NO_LICENSE_AVAILABLE`."

    Design: Corner/cross_cutting_layers/consortium_visibility_gate_blocks_local_only_title
    """
    ctx = setup_base_with_title(title_overrides={"sharing_scope": "LOCAL_ONLY"})
    lib_a = ctx["library"]
    create_license_via_order(lib_a["id"], ctx["fund"]["id"], ctx["title"]["id"],
                             model="OCOU", copies=1)
    lib_b = create_library(ctx["consortium"]["id"], name="Library B")
    pat_b = create_patron(lib_b["id"], external_card_number="B-1",
                          full_name="Patron B")
    resp = api.checkout(
        {"patron_id": pat_b["id"], "title_id": ctx["title"]["id"]},
        make_patron_headers(pat_b["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NO_LICENSE_AVAILABLE)
    loans, _ = None, None
    from test_helpers import validate_paginated
    loans, _ = validate_paginated(
        api.list_patron_loans(pat_b["id"], make_patron_headers(pat_b["id"]))
    )
    assert len(loans) == 0, "no loan row may be created for the blocked patron"


def test_return_response_reflects_full_cascade_immediately(api):
    """PRD §3.7: "the freed copy immediately triggers hold promotion for the
    title, which stamps `ready_since`/`ready_until` on the promoted hold and
    recomputes the remaining queue's wait estimates."

    Design: Corner/consistency_model/return_response_reflects_full_cascade_immediately
    """
    ctx = setup_ocou_library(copies=1)
    lib = ctx["library"]
    p0 = create_patron(lib["id"], external_card_number="P-0", full_name="Patron Zero")
    p1 = create_patron(lib["id"], external_card_number="P-1", full_name="Patron One")
    loan0 = checkout(p0["id"], ctx["title"]["id"])
    hold1 = place_hold(p1["id"], ctx["title"]["id"])
    resp = api.return_loan(loan0["id"], make_patron_headers(p0["id"]))
    loan = validate_success(resp)
    assert loan["status"] == "RETURNED"
    assert loan["returned_at"] is not None
    hold = validate_success(api.get_hold(hold1["id"], make_patron_headers(p1["id"])))
    assert hold["status"] == "READY"
    assert hold["ready_since"] == "2026-09-01T00:00:00Z", (
        "the cascade is applied in the same request, no delayed reconciliation"
    )
    patron = validate_success(api.get_patron(p0["id"], make_patron_headers(p0["id"])))
    assert patron["active_loan_count"] == 0
