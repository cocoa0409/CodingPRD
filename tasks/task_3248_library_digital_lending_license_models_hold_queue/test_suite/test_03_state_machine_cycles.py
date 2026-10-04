"""Cyclic state machines: hold suspend/resume and invoice dispute/re-issue."""
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
    make_patron_headers,
    place_hold,
    set_clock,
    setup_base,
    setup_base_with_title,
    setup_ocou_library,
    validate_success,
)


def test_suspended_hold_is_skipped_by_promotion(api):
    """PRD §3.4: "Suspended holds are invisible to promotion — a freed copy
    skips over them."

    Design: Difficulty/non_linear_state_machine/hold_suspend_resume_cycle_preserves_queue_rank
    """
    ctx = setup_ocou_library(copies=1)
    lib = ctx["library"]
    p0 = create_patron(lib["id"], external_card_number="P-0", full_name="Patron Zero")
    p1 = create_patron(lib["id"], external_card_number="P-1", full_name="Patron One")
    p2 = create_patron(lib["id"], external_card_number="P-2", full_name="Patron Two")
    loan0 = checkout(p0["id"], ctx["title"]["id"])
    h1 = place_hold(p1["id"], ctx["title"]["id"])
    h2 = place_hold(p2["id"], ctx["title"]["id"])
    resp = api.suspend_hold(h1["id"], make_patron_headers(p1["id"]))
    assert resp.status_code == 200, resp.text
    api.return_loan(loan0["id"], make_patron_headers(p0["id"]))
    hold1 = validate_success(api.get_hold(h1["id"], make_patron_headers(p1["id"])))
    hold2 = validate_success(api.get_hold(h2["id"], make_patron_headers(p2["id"])))
    assert hold2["status"] == "READY", (
        f"the freed copy must skip the SUSPENDED hold and promote H2, got {hold2['status']}"
    )
    assert hold1["status"] == "SUSPENDED"
    assert hold1["suspension_count"] == 1


def test_resume_preserves_original_placed_at_rank_key(api):
    """PRD §3.4: "resuming moves it `SUSPENDED` → `PLACED` with the original
    `placed_at` preserved, so queue rank is unchanged."

    Design: Difficulty/non_linear_state_machine/hold_suspend_resume_cycle_preserves_queue_rank
    """
    ctx = setup_ocou_library(copies=1)
    lib = ctx["library"]
    p0 = create_patron(lib["id"], external_card_number="P-0", full_name="Patron Zero")
    p1 = create_patron(lib["id"], external_card_number="P-1", full_name="Patron One")
    p2 = create_patron(lib["id"], external_card_number="P-2", full_name="Patron Two")
    checkout(p0["id"], ctx["title"]["id"])
    h1 = place_hold(p1["id"], ctx["title"]["id"])
    original_placed_at = h1["placed_at"]
    place_hold(p2["id"], ctx["title"]["id"])
    api.suspend_hold(h1["id"], make_patron_headers(p1["id"]))
    resp = api.resume_hold(h1["id"], make_patron_headers(p1["id"]))
    data = validate_success(resp)
    assert data["status"] == "PLACED"
    assert data["placed_at"] == original_placed_at, (
        f"placed_at {data['placed_at']} != original {original_placed_at}"
    )


def _setup_dispute_cycle():
    """Libraries H and A; shared CONSORTIUM title; H fulfills an OCOU order
    invoiced 10000 with zero checkouts; invoice generated and issued."""
    set_clock()
    consortium = create_consortium()
    lib_h = create_library(consortium["id"], name="Library H")
    lib_a = create_library(consortium["id"], name="Library A")
    fund_h = create_fund(lib_h["id"])
    pat_a = create_patron(lib_a["id"], external_card_number="PA-1",
                          full_name="Patron A")
    title = create_title(consortium["id"], price_ocou_cents=10000,
                         sharing_scope="CONSORTIUM")
    create_license_via_order(
        lib_h["id"], fund_h["id"], title["id"],
        model="OCOU", copies=1, invoiced_cost_cents=10000,
    )
    from test_helpers import api_client
    resp = api_client.generate_invoice(
        consortium["id"],
        {"period_start": "2026-09-01T00:00:00Z",
         "period_end": "2026-10-01T00:00:00Z"},
        ADMIN,
    )
    invoice = get_success_data(resp)
    issue = api_client.issue_invoice(invoice["id"], ADMIN)
    issued = get_success_data(issue)
    return {"consortium": consortium, "lib_h": lib_h, "lib_a": lib_a,
            "pat_a": pat_a, "title": title, "invoice": issued}


def test_invoice_first_issue_with_no_checkouts_host_absorbs_all(api):
    """PRD §3.12: "If no non-host library had any checkouts, the host absorbs
    the full T."

    Design: Difficulty/non_linear_state_machine/invoice_dispute_reissue_cycle_recomputes_lines
    """
    ctx = _setup_dispute_cycle()
    invoice = ctx["invoice"]
    assert invoice["status"] == "ISSUED"
    assert invoice["total_cents"] == 10000
    assert len(invoice["lines"]) == 1
    assert invoice["lines"][0]["library_id"] == ctx["lib_h"]["id"]
    assert invoice["lines"][0]["share_cents"] == 10000


def test_invoice_dispute_then_reissue_recomputes_lines(api):
    """PRD §3.12: "the dispute loop closes when the `ConsortiumAdmin`
    re-issues, which recomputes the lines from current event data before the
    invoice returns to `ISSUED`."

    Design: Difficulty/non_linear_state_machine/invoice_dispute_reissue_cycle_recomputes_lines
    """
    ctx = _setup_dispute_cycle()
    invoice = ctx["invoice"]
    resp = api.dispute_invoice(
        invoice["id"], make_library_admin_headers(ctx["lib_a"]["id"]),
        payload={"reason": "usage data incomplete"},
    )
    disputed = validate_success(resp)
    assert disputed["status"] == "DISPUTED"
    checkout(ctx["pat_a"]["id"], ctx["title"]["id"])
    resp = api.issue_invoice(invoice["id"], ADMIN)
    reissued = validate_success(resp)
    assert reissued["status"] == "ISSUED"
    shares = {line["library_id"]: line["share_cents"]
              for line in reissued["lines"]}
    # PRD §3.12 pins: (a) re-issue recomputes lines from current event data,
    # (b) the host's share is max(proportional, floor) — here the host has 0
    # of 1 checkouts, so its share is exactly the floor 0.25 * 10000 == 2500,
    # (c) the remainder goes to non-host libraries with usage. The design
    # doc's 5000/5000 split contradicts the pinned waterfall (it would double
    # as a proportional split of the whole T), so it is not asserted.
    assert shares[ctx["lib_h"]["id"]] == 2500, (
        "host with zero usage carries exactly the floor share"
    )
    assert shares[ctx["lib_a"]["id"]] == 7500, (
        "the sole non-host user absorbs the remainder"
    )
    assert reissued["total_cents"] == 10000
