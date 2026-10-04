"""Difficulty rule: non_linear_state_machine — the configuration revision
cycle DRAFT->LOCKED->DRAFT->LOCKED, and the order hold/release loop driven
by dealer suspension (PRD §3.1, §3.4, §3.5)."""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_configuration,
    create_product_family,
    create_dealer,
    get_order,
    lock_configuration,
    make_dealer_headers,
    reinstate_dealer,
    revise_configuration,
    setup_submitted_order,
    suspend_dealer,
    validate_error,
)

ADMIN = TEST_USERS["admin_headers"]


def _spec_locked_once(api):
    create_product_family(api, category="SEATING", base_lead_time_days=28)
    dealer = create_dealer(api)
    spec = create_configuration(api, dealer["id"], name="Rev loop")
    locked = lock_configuration(api, spec, dealer["id"])
    return dealer, spec, locked


def test_revise_returns_locked_spec_to_draft(api):
    """PRD §3.4: "revising moves it `LOCKED → DRAFT`, increments
    `revision_number` by 1, and increments `version` by 1".

    Design: Difficulty/non_linear_state_machine/configuration_spec_revision_cycle_locked_to_draft
    """
    dealer, spec, locked = _spec_locked_once(api)
    assert spec["version"] == 1 and locked["version"] == 2
    assert locked["status"] == "LOCKED"

    revised = revise_configuration(api, locked, dealer["id"])
    assert revised["status"] == "DRAFT"
    assert revised["revision_number"] == 2
    assert revised["version"] == 3


def test_revised_spec_can_relock(api):
    """PRD §3.4: "after which the modules may be edited and the spec locked
    again" — the cycle is re-entrant: a re-lock of the revised spec lands
    LOCKED with revision_number still 2 and version 4.

    Design: Difficulty/non_linear_state_machine/configuration_spec_revision_cycle_locked_to_draft
    """
    dealer, _spec, locked = _spec_locked_once(api)
    revised = revise_configuration(api, locked, dealer["id"])
    relocked = lock_configuration(api, revised, dealer["id"])
    assert relocked["status"] == "LOCKED"
    assert relocked["revision_number"] == 2
    assert relocked["version"] == 4


def _order_on_hold(api):
    """A SUBMITTED 4-chair order whose dealer is then suspended through the
    showroom route."""
    ctx = setup_submitted_order(api)
    dealer = suspend_dealer(api, ctx["dealer"]["id"])
    return ctx, dealer


def test_suspension_cascades_submitted_order_to_on_hold(api):
    """PRD §3.1: "setting `showroom_compliant` from true to false
    auto-suspends the dealer even when the same payload says nothing about
    `status`" and "Suspension cascades immediately: every `ProjectOrder` of
    that dealer whose `status` is `SUBMITTED` moves to `ON_HOLD`, and each
    affected order's `version` increments by 1."

    Design: Difficulty/non_linear_state_machine/order_hold_release_cycle_via_dealer_suspension
    """
    ctx, dealer = _order_on_hold(api)
    assert dealer["status"] == "SUSPENDED"
    assert dealer["suspended_at"] is not None

    order = get_order(
        api, ctx["order"]["id"], make_dealer_headers(ctx["dealer"]["id"])
    )
    assert order["status"] == "ON_HOLD"
    assert order["version"] == ctx["order"]["version"] + 1


def test_acknowledge_rejected_while_on_hold(api):
    """PRD §3.5: "An `ON_HOLD` order arises only from dealer suspension and
    cannot be acknowledged while held" and "an order in any other state
    rejects acknowledgment with `ERR_INVALID_STATE`".

    Design: Difficulty/non_linear_state_machine/order_hold_release_cycle_via_dealer_suspension
    """
    ctx, _dealer = _order_on_hold(api)
    resp = api.acknowledge_project_order(ctx["order"]["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_reinstatement_cascades_order_back_to_submitted(api):
    """PRD §3.1: "On reinstatement `suspended_at` is cleared back to null,
    and the cascade runs backward: every order of the dealer sitting in
    `ON_HOLD` returns to `SUBMITTED`, each with its `version` incremented by
    1."

    Design: Difficulty/non_linear_state_machine/order_hold_release_cycle_via_dealer_suspension
    """
    ctx, _dealer = _order_on_hold(api)
    held = get_order(
        api, ctx["order"]["id"], make_dealer_headers(ctx["dealer"]["id"])
    )
    dealer = reinstate_dealer(api, ctx["dealer"]["id"])
    assert dealer["status"] == "ACTIVE"
    assert dealer["suspended_at"] is None

    order = get_order(
        api, ctx["order"]["id"], make_dealer_headers(ctx["dealer"]["id"])
    )
    assert order["status"] == "SUBMITTED"
    assert order["version"] == held["version"] + 1
