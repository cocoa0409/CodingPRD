"""Difficulty rule: priority_pair_validation_conflict — the state gate beats
the lead-time rule on a re-submit (PRD §2.9, §3.5)."""

from test_helpers import (
    ApiErrorId,
    create_order,
    get_order,
    make_dealer_headers,
    make_submit_payload,
    set_logical_clock,
    setup_acknowledged_order,
    setup_locked_world,
    validate_error,
)


def test_state_error_beats_temporal_error_on_resubmit(api):
    """PRD §3.5: "The gate then evaluates its checks in this order, returning
    the first failure: the order must be `DRAFT` (else `ERR_INVALID_STATE`)"
    and, later in the same ordered gate, "the `requested_install_date` must
    be at least the clock date plus the spec's `max_lead_time_days` (else
    `ERR_LEAD_TIME_VIOLATION`)". A re-submit of an ACKNOWLEDGED order whose
    install date has fallen behind the advanced clock violates both; the
    state gate fires first.

    Design: Difficulty/priority_pair_validation_conflict/state_error_beats_temporal_error_on_resubmit
    """
    ctx = setup_acknowledged_order(api)  # requested_install_date 2026-12-15
    set_logical_clock(api, "2026-12-20T00:00:00Z")
    live = get_order(
        api, ctx["order"]["id"], make_dealer_headers(ctx["dealer"]["id"])
    )
    assert live["status"] == "ACKNOWLEDGED"

    resp = api.submit_project_order(
        live["id"], make_submit_payload(live["version"]),
        make_dealer_headers(ctx["dealer"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_temporal_violation_is_genuinely_present(api):
    """Control leg of the same design instance: at the advanced clock
    2026-12-20, a genuinely DRAFT order with requested_install_date
    2026-12-15 fails with `ERR_LEAD_TIME_VIOLATION` (PRD §3.5: "the
    `requested_install_date` must be at least the clock date plus the spec's
    `max_lead_time_days`") — proving the ACKNOWLEDGED resubmit's
    ERR_INVALID_STATE reflected check ordering, not absence of the temporal
    failure.

    Design: Difficulty/priority_pair_validation_conflict/state_error_beats_temporal_error_on_resubmit
    """
    ctx = setup_locked_world(api)
    set_logical_clock(api, "2026-12-20T00:00:00Z")
    order = create_order(
        api, ctx["agreement"]["id"], ctx["configuration"]["id"],
        ctx["dealer"]["id"], requested_install_date="2026-12-15",
    )
    resp = api.submit_project_order(
        order["id"], make_submit_payload(order["version"]),
        make_dealer_headers(ctx["dealer"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_LEAD_TIME_VIOLATION)
