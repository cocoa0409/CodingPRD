"""Store and partner lifecycle: invalid transitions, terminal lockdowns."""
from test_helpers import (
    ADMIN,
    FINANCE,
    ApiErrorId,
    create_active_store,
    create_partner,
    create_store,
    get_success_data,
    set_clock,
    validate_error,
    validate_success,
)


def test_store_activate_from_active_is_invalid(api):
    """PRD §3.2: "The store status dimension runs `PENDING_ONBOARDING` →
    `ACTIVE` → `SUSPENDED` → `ACTIVE` → `DEACTIVATED`."
    PRD §2.11: "Only then are state-machine preconditions checked
    (`ERR_INVALID_STATE`, HTTP 409)"

    Design: Corner/state_machines/store_activate_from_active_is_invalid
    """
    set_clock("2026-09-01T00:00:00Z")
    store = create_store(
        shop_name="State Books",
        slug="state-books",
        commission_pct=0.30,
        payout_threshold_cents=20000,
    )
    get_success_data(api.store_action(store["id"], {"action": "activate"}, ADMIN))

    resp = api.store_action(store["id"], {"action": "activate"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    store_now = get_success_data(api.get_store(store["id"], ADMIN))
    assert store_now["status"] == "ACTIVE"
    assert store_now["version"] == 2  # create (1) + first activate (2)


def test_deactivated_store_is_terminal(api):
    """PRD §3.2: "Deactivation is the terminal act, permitted from either
    `ACTIVE` or `SUSPENDED`, but only when the store's `accrued_balance_cents`
    is exactly zero and no payout for the store sits in `PENDING` or
    `PROCESSING`"
    PRD §2.11: "Only then are state-machine preconditions checked
    (`ERR_INVALID_STATE`, HTTP 409)"

    Design: Corner/state_machines/deactivated_store_is_terminal
    """
    set_clock("2026-09-01T00:00:00Z")
    store = create_active_store(
        shop_name="State Books",
        slug="state-books",
        commission_pct=0.30,
        payout_threshold_cents=20000,
    )
    get_success_data(api.store_action(store["id"], {"action": "deactivate"}, ADMIN))

    for action in ("reactivate", "suspend"):
        resp = api.store_action(store["id"], {"action": action}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    store_now = get_success_data(api.get_store(store["id"], ADMIN))
    assert store_now["status"] == "DEACTIVATED"


def test_partner_reject_is_terminal_and_approve_after_reject_fails(api):
    """PRD §3.2: "An application may instead be rejected outright from
    `APPLIED`, moving it to `REJECTED`, which is terminal."
    PRD §2.11: "Only then are state-machine preconditions checked
    (`ERR_INVALID_STATE`, HTTP 409)"

    Design: Corner/state_machines/partner_reject_is_terminal_and_approve_after_reject_fails
    """
    set_clock("2026-09-01T00:00:00Z")
    partner = create_partner(
        display_name="Terminal Author", partner_kind="AUTHOR", commission_pct=0.10
    )
    get_success_data(api.partner_action(partner["id"], {"action": "reject"}, ADMIN))

    for action in ("approve", "activate"):
        resp = api.partner_action(partner["id"], {"action": action}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    partner_now = get_success_data(api.get_partner(partner["id"], ADMIN))
    assert partner_now["status"] == "REJECTED"


def test_commercial_terms_band_enforcement(api):
    """PRD §3.2: "a `commission_pct` between 0.10 and 0.30 inclusive, an optional
    `pool_opt_in` flag defaulting to true that governs participation in the
    monthly profit pool, and an optional `payout_threshold_cents` defaulting to
    2500 and never accepted below that floor. Terms outside these bands are
    rejected with `ERR_COMMERCIAL_TERMS_INVALID`."
    PRD §3.2: "a `commission_pct` between 0.05 and 0.15 inclusive — a
    deliberately narrower band than stores — and an optional
    `payout_threshold_cents` defaulting to 1000 with that value as its floor."
    PRD §3.6: "the `pool_cents` committed to the pool — which must be greater
    than zero, else `ERR_COMMERCIAL_TERMS_INVALID`"

    Design: Corner/validations/commercial_terms_band_enforcement
    """
    set_clock("2026-09-01T00:00:00Z")
    resp = api.create_store(
        {"shop_name": "Greedy Books", "slug": "greedy-books", "commission_pct": 0.31},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_COMMERCIAL_TERMS_INVALID, expected_status=422)

    resp = api.create_partner(
        {"display_name": "Cheap Author", "partner_kind": "AUTHOR", "commission_pct": 0.04},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_COMMERCIAL_TERMS_INVALID, expected_status=422)

    resp = api.create_partner(
        {
            "display_name": "Low Floor",
            "partner_kind": "AUTHOR",
            "commission_pct": 0.10,
            "payout_threshold_cents": 999,
        },
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_COMMERCIAL_TERMS_INVALID, expected_status=422)

    resp = api.create_pool_distribution(
        {
            "period_start": "2026-09-01T00:00:00Z",
            "period_end": "2026-10-01T00:00:00Z",
            "pool_cents": 0,
            "share_mode": "EQUAL_SPLIT",
        },
        FINANCE,
    )
    validate_error(resp, ApiErrorId.ERR_COMMERCIAL_TERMS_INVALID, expected_status=422)
