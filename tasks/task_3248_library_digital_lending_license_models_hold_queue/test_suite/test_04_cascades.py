"""Transitive cascades: return-driven promotion and epoch auto-purchase."""
from test_helpers import (
    ADMIN,
    ANALYST,
    checkout,
    create_patron,
    get_success_data,
    make_library_admin_headers,
    make_patron_headers,
    place_hold,
    set_clock,
    setup_base_with_title,
    setup_ocou_library,
    create_license_via_order,
    validate_success,
)


def _setup_two_holds_behind_active_loan():
    ctx = setup_ocou_library(copies=1)
    lib = ctx["library"]
    p0 = create_patron(lib["id"], external_card_number="P-0", full_name="Patron Zero")
    p1 = create_patron(lib["id"], external_card_number="P-1", full_name="Patron One")
    p2 = create_patron(lib["id"], external_card_number="P-2", full_name="Patron Two")
    loan0 = checkout(p0["id"], ctx["title"]["id"])
    h1 = place_hold(p1["id"], ctx["title"]["id"])
    h2 = place_hold(p2["id"], ctx["title"]["id"])
    ctx.update({"p0": p0, "p1": p1, "p2": p2, "loan0": loan0, "h1": h1, "h2": h2})
    return ctx


def test_return_frees_copy_and_promotes_oldest_hold(api):
    """PRD §3.7: "the freed copy immediately triggers hold promotion for the
    title, which stamps `ready_since`/`ready_until` on the promoted hold and
    recomputes the remaining queue's wait estimates."
    PRD §3.4: "its `ready_since` is stamped with the current logical time, its
    `ready_until` is computed as `ready_since` plus the home library's
    `pickup_window_hours`."

    Design: Difficulty/transitive_cascade/early_return_copy_hold_ready_wait_cascade
    """
    ctx = _setup_two_holds_behind_active_loan()
    resp = api.return_loan(ctx["loan0"]["id"], make_patron_headers(ctx["p0"]["id"]))
    loan = validate_success(resp)
    assert loan["status"] == "RETURNED"
    assert loan["returned_at"] == "2026-09-01T00:00:00Z"
    lic = validate_success(
        api.get_license(ctx["license"]["id"],
                        make_library_admin_headers(ctx["library"]["id"]))
    )
    assert lic["copies_on_loan"] == 0
    hold1 = validate_success(
        api.get_hold(ctx["h1"]["id"], make_patron_headers(ctx["p1"]["id"]))
    )
    assert hold1["status"] == "READY"
    assert hold1["ready_since"] == "2026-09-01T00:00:00Z"
    assert hold1["ready_until"] == "2026-09-04T00:00:00Z"


def test_return_recomputes_remaining_queue_wait_estimates(api):
    """PRD §3.7: "the freed copy immediately triggers hold promotion for the
    title, which stamps `ready_since`/`ready_until` on the promoted hold and
    recomputes the remaining queue's wait estimates."
    PRD §2.8: "The `event_type` enumeration is exactly: `CHECKOUT`, `RENEW`,
    `RETURN`, `LOAN_EXPIRED`, `HOLD_PLACED`, `HOLD_READY`, `HOLD_FULFILLED`,
    `HOLD_EXPIRED`, `HOLD_CANCELLED`, `PURCHASE`."

    Design: Difficulty/transitive_cascade/early_return_copy_hold_ready_wait_cascade
    """
    ctx = _setup_two_holds_behind_active_loan()
    api.return_loan(ctx["loan0"]["id"], make_patron_headers(ctx["p0"]["id"]))
    hold2 = validate_success(
        api.get_hold(ctx["h2"]["id"], make_patron_headers(ctx["p2"]["id"]))
    )
    assert hold2["status"] == "PLACED"
    assert hold2["optimistic_wait_days"] == 21, (
        f"one hold ahead, one copy: ceil(1/1) * 21 == 21, got {hold2['optimistic_wait_days']}"
    )
    events, meta = None, None
    from test_helpers import validate_paginated
    events, meta = validate_paginated(
        api.list_title_events(ctx["title"]["id"], ANALYST)
    )
    return_events = [e for e in events if e["event_type"] == "RETURN"
                     and e["loan_id"] == ctx["loan0"]["id"]]
    ready_events = [e for e in events if e["event_type"] == "HOLD_READY"
                    and e["hold_id"] == ctx["h1"]["id"]]
    assert len(return_events) == 1 and len(ready_events) == 1
    assert return_events[0]["occurred_at"] == ready_events[0]["occurred_at"], (
        "RETURN then HOLD_READY share the same logical instant"
    )


def _setup_autopurchase_epoch():
    """Library L2 with auto-purchase enabled; METERED_TIME license
    (metered_time_days 30) on loan to Q0; holds by Q1..Q4; clock past expiry."""
    ctx = setup_base_with_title(
        title_overrides={"metered_time_days": 30},
        library_overrides={
            "loan_period_days": 21, "renewal_period_days": 21, "max_renewals": 2,
            "auto_purchase_enabled": True, "holds_per_copy_ratio": 4,
            "wait_target_days": 28, "auto_purchase_max_cents": 100000,
        },
    )
    lib = ctx["library"]
    create_license_via_order(lib["id"], ctx["fund"]["id"], ctx["title"]["id"],
                             model="METERED_TIME")
    patrons = []
    for i in range(5):
        patrons.append(create_patron(lib["id"], external_card_number=f"Q-{i}",
                                     full_name=f"Patron Q{i}"))
    checkout(patrons[0]["id"], ctx["title"]["id"])
    holds = [place_hold(p["id"], ctx["title"]["id"]) for p in patrons[1:]]
    set_clock("2026-10-02T00:00:00Z")
    ctx.update({"patrons": patrons, "holds": holds})
    return ctx


def test_epoch_expiry_triggers_auto_purchase_order_fulfilled(api):
    """PRD §3.8: "when a metered license expires, the title's availability
    drops, wait estimates are recomputed, and if some library's auto-purchase
    rule now fires (both the ratio and the wait target, per §3.11), the same
    epoch creates an `AUTO_RATIO` order, approves it, fulfills it into a
    replacement license, and runs hold promotion off the new copy."

    Design: Difficulty/transitive_cascade/epoch_license_expiry_autopurchase_fulfill_promotion_cascade
    """
    ctx = _setup_autopurchase_epoch()
    lib = ctx["library"]
    resp = api.run_epoch(ADMIN)
    epoch = validate_success(resp)
    assert epoch["expired_licenses"] >= 1
    assert epoch["auto_orders_created"] == 1, (
        f"4 holds / max(0,1) == 4 >= 4 with pessimistic wait > 28 must fire exactly once, got {epoch}"
    )
    from test_helpers import validate_paginated
    orders, _ = validate_paginated(
        api.list_orders(ANALYST, params={"library_id": lib["id"], "status": "FULFILLED"})
    )
    auto_orders = [o for o in orders if o["origin"] == "AUTO_RATIO"]
    assert len(auto_orders) == 1
    auto = auto_orders[0]
    assert auto["model"] == "OCOU"
    assert auto["copies"] == 1, "needed = ceil(4/4) - 0 == 1"
    assert auto["invoiced_cost_cents"] == 5000


def test_epoch_auto_purchase_creates_license_and_promotes_hold(api):
    """PRD §3.11: "Otherwise the sweep creates an acquisition order with
    `origin` `AUTO_RATIO`, model `OCOU`, the candidate copy count, and `status`
    already `APPROVED`, and fulfills it in the same epoch at an
    `invoiced_cost_cents` equal to the estimate — creating the license and
    triggering hold promotion, all within the epoch's cascade."

    Design: Difficulty/transitive_cascade/epoch_license_expiry_autopurchase_fulfill_promotion_cascade
    """
    ctx = _setup_autopurchase_epoch()
    lib = ctx["library"]
    epoch = validate_success(api.run_epoch(ADMIN))
    assert epoch["holds_promoted"] >= 1
    from test_helpers import validate_paginated
    licenses, _ = validate_paginated(
        api.list_licenses(ANALYST, params={"title_id": ctx["title"]["id"],
                                           "model": "OCOU"})
    )
    assert len(licenses) == 1
    assert licenses[0]["status"] == "ACTIVE"
    assert licenses[0]["copies_total"] == 1
    hold1 = validate_success(
        api.get_hold(ctx["holds"][0]["id"],
                     make_patron_headers(ctx["patrons"][1]["id"]))
    )
    assert hold1["status"] == "READY"
    fund = validate_success(
        api.get_fund(ctx["fund"]["id"], make_library_admin_headers(lib["id"]))
    )
    assert fund["spent_cents"] == 4000 + 5000 == 9000
