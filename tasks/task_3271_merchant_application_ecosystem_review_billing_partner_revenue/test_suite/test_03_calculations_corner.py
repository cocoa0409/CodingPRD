"""Calculation-focused corner tests: search ranking, proration, SLA."""
import pytest

from test_helpers import (
    create_installation_payload,
    create_merchant,
    make_admin_headers,
    make_developer_headers,
    make_merchant_headers,
    set_clock,
    setup_active_installation,
    setup_listed_app,
    setup_support_ticket,
    validate_paginated,
    validate_success,
)


def test_search_ranking_weights_and_tiebreak(api):
    """PRD §3.4: "The per-category weights `(w1, w2, w3)` applied to quality,
    velocity, and recency respectively are: `PRODUCTIVITY` uses one, two,
    three; `MARKETING` uses two, two, one; `FULFILLMENT` uses three, one, one;
    `ANALYTICS` uses two, one, two; `FINANCE` uses two, three, zero. The final
    ranking is ordered by score descending, with ties broken by the app's
    `created_at` ascending; the app's `id` is never consulted in ranking."

    Design: Corner/calculations/search_ranking_weights_and_tiebreak
    """
    developer, search_a, _ = setup_listed_app(company="DQ", category="PRODUCTIVITY")
    # Rename for deterministic search matching (both share prefix "Search").
    admin = make_admin_headers()
    dev_headers = make_developer_headers(developer["id"])
    app_a = validate_success(
        api.update_app(
            search_a["id"],
            {"name": "SearchA", "expected_app_version": search_a["version"]},
            dev_headers,
        )
    )
    # The second app must belong to the SAME developer: PRD §3.1 lets a
    # developer update only their own apps, and `setup_listed_app` mints a
    # fresh developer per call unless one is supplied.
    _, search_b, _ = setup_listed_app(
        company="DQ2", category="PRODUCTIVITY", developer=developer
    )
    search_b = validate_success(
        api.update_app(
            search_b["id"],
            {"name": "SearchB", "expected_app_version": search_b["version"]},
            dev_headers,
        )
    )
    # Give SearchB one ACTIVE installation (velocity +1 -> 2*w2 = +4 points).
    merchant = create_merchant(shop_domain="mq-search.myshop.com")
    inst = validate_success(
        api.create_installation(
            create_installation_payload(search_b["id"], merchant["id"]),
            make_merchant_headers(merchant["id"]),
        ),
        expected_status=201,
    )
    validate_success(
        api.consent_installation(inst["id"], {}, make_merchant_headers(merchant["id"]))
    )
    resp = api.list_apps(admin, params={"search": "Search", "category": "PRODUCTIVITY"})
    data, _ = validate_paginated(resp)
    ids = [a["id"] for a in data]
    # PRODUCTIVITY (1,2,3): SearchB quality10 + velocity 1*2 + recency 5*3 = 27;
    # SearchA quality 10 + 0 + 15 = 25. SearchB must rank first.
    assert ids[0] == search_b["id"], (
        f"expected SearchB ({search_b['id']}) first, got order {ids}"
    )
    assert ids[1] == app_a["id"], (
        f"expected SearchA ({app_a['id']}) second, got order {ids}"
    )


def test_usage_proration_full_window_uncapped(api):
    """PRD §3.6: "A usage charge created fewer than thirty days after the
    installation's `installed_at` is capped to a prorated share of the declared
    `base_amount_cents`: the number of whole days elapsed between
    `installed_at` and the current logical time is computed (any partial day
    is discarded), the result is capped at thirty, and the capped amount is
    `base_amount_cents` multiplied by that capped day count and divided by
    thirty, rounded half-up to integer cents."

    Design: Corner/calculations/usage_proration_full_window_uncapped
    """
    developer, app, version, merchant, installation = setup_active_installation(
        company="DU", category="ANALYTICS"
    )
    # installed_at is the default logical clock 2026-09-01; advance 34 days.
    set_clock("2026-10-05T00:00:00Z")
    charge = validate_success(
        api.create_billing_charge(
            installation["id"],
            {"charge_type": "USAGE", "base_amount_cents": 2000,
             "description": "late usage"},
            make_developer_headers(developer["id"]),
        ),
        expected_status=201,
    )
    assert charge["final_amount_cents"] == 2000, (
        f"expected 2000 (34 days >= 30-day window, no proration), "
        f"got {charge['final_amount_cents']}"
    )


def test_sla_breach_exactly_at_boundary_not_breached(api):
    """PRD §3.12: "Escalation evaluates the SLA: `sla_breached` becomes true
    when either the developer has not yet responded and the elapsed time since
    `opened_at` is strictly greater than `sla_hours`, or the developer's first
    response arrived more than `sla_hours` after `opened_at`. The boundary is
    exclusive — a response at exactly `sla_hours` after opening is not a
    breach; strictly greater is required."
    PRD §3.12: "The server derives the ticket's `sla_hours` from severity at
    creation: 72 hours for `LOW`, 48 hours for `MEDIUM`, and 24 hours for
    `HIGH`."

    Design: Corner/calculations/sla_breach_exactly_at_boundary_not_breached
    """
    developer, app, merchant, ticket = setup_support_ticket(
        severity="HIGH", company="DSLA", category="PRODUCTIVITY"
    )
    assert ticket["sla_hours"] == 24, f"expected sla_hours 24, got {ticket['sla_hours']}"
    # opened at the default clock 2026-09-01T00:00:00Z; respond at exactly +24h.
    set_clock("2026-09-02T00:00:00Z")
    dev_headers = make_developer_headers(developer["id"])
    validate_success(api.respond_ticket(ticket["id"], {}, dev_headers))
    resolved = validate_success(api.resolve_ticket(ticket["id"], {}, dev_headers))
    assert resolved["sla_breached"] is False, (
        f"expected sla_breached False at exactly 24h, got {resolved['sla_breached']}"
    )
