"""Boundary crossings: a paired-field omission, a strict temporal gate and a
strict positivity gate on the pool."""
from test_helpers import api_client, validate_error, validate_success
from test_helpers.api_errors import ApiErrorId
from test_helpers.fixtures import (
    ANALYST,
    FUEL_COORDINATOR,
    OPERATOR,
    create_settlement_line,
    get_ppa,
    get_site,
    post_accrual,
    schedule_delivery,
    set_clock,
    setup_active_ppa,
    take_resource_hold,
)


def test_a_resource_hold_without_its_window_pair_is_a_malformed_request():
    """PRD §2.6: "The two window boundaries are supplied together or not at all; supplying one
    without the other is a malformed request under `ERR_INVALID_REQUEST`."

    Design: Difficulty/boundary_precision_check/resource_hold_missing_window_returns_invalid_request
    """
    ctx = setup_active_ppa()
    before = get_site(ctx["site_id"])
    assert before["draw_position_therms"] == before["initial_fuel_inventory_therms"]

    response = api_client.take_resource_hold(
        ctx["site_id"], OPERATOR, {"requested_therms": 30000}
    )

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)
    after = get_site(ctx["site_id"])
    assert after["draw_position_therms"] == before["draw_position_therms"], (
        "the pool must be unchanged"
    )
    assert after["version"] == before["version"], "no row was created, so nothing advanced"


def test_a_resource_hold_with_a_supplied_paired_window_is_admitted():
    """PRD §3.3: "A `SiteOperator` takes one by supplying `requested_therms` and the pair of window boundaries
    `window_start_iso8601` and `window_end_iso8601`; the server creates a delivery in
    `DELIVERY_SCHEDULED`."

    Design: Difficulty/boundary_precision_check/resource_hold_missing_window_returns_invalid_request
    """
    ctx = setup_active_ppa()
    opening = get_site(ctx["site_id"])["draw_position_therms"]
    hold = take_resource_hold(
        ctx["site_id"],
        requested_therms=30000,
        window_start_iso8601="2026-04-01T00:00:00Z",
        window_end_iso8601="2026-04-02T00:00:00Z",
    )
    assert hold["lifecycle_state"] == "DELIVERY_SCHEDULED"
    assert get_site(ctx["site_id"])["draw_position_therms"] == opening - 30000


def test_confirmation_one_second_past_the_gate_instant_succeeds():
    """PRD §2.6: "Confirmation of a
    delivery is also time-gated in one direction only: the delivery may not be confirmed before
    its `confirm_after_iso8601` instant has passed".

    Design: Difficulty/boundary_precision_check/confirm_at_exact_window_open_returns_confirm_too_early
    """
    ctx = setup_active_ppa()
    delivery = schedule_delivery(
        ctx["site_id"],
        volume_therms=30000,
        delivered_at="2026-02-01T00:00:00Z",
        confirm_after_iso8601="2026-03-06T00:00:00Z",
    )
    validate_success(
        api_client.dispatch_fuel_delivery(
            ctx["site_id"], delivery["id"], FUEL_COORDINATOR
        )
    )
    set_clock("2026-03-06T00:00:01Z")

    confirmed = validate_success(
        api_client.confirm_fuel_delivery(
            ctx["site_id"], delivery["id"], FUEL_COORDINATOR
        )
    )
    assert confirmed["lifecycle_state"] == "DELIVERY_CONFIRMED", (
        "one second past the gate the same confirm must be admitted"
    )


def test_a_settlement_line_whose_pool_is_exactly_zero_may_not_be_validated():
    """PRD §3.4: "A `SettlementAnalyst` may
    validate a draft line only while the contract is in `PPA_ACTIVE` or `PPA_SUSPENDED`, only
    while the period ends after it begins, and only while the line's
    `cap_side_pool_cents` is greater than zero — a period whose cap-side pool is empty has nothing
    to reconcile and may not be validated."

    Design: Difficulty/boundary_precision_check/validate_with_exactly_zero_cap_pool_returns_invalid_state
    """
    ctx = setup_active_ppa()
    # A positive charge accrual and an equal-and-opposite output-guarantee accrual
    # net the open pool to exactly zero.
    post_accrual(
        ctx["ppa_id"], ctx["site_id"], accrual_type="CHARGE_ACCRUAL", amount_cents=100000
    )
    post_accrual(
        ctx["ppa_id"],
        ctx["site_id"],
        accrual_type="OUTPUT_GUARANTEE_ACCRUAL",
        amount_cents=100000,
    )
    line = create_settlement_line(ctx["ppa_id"], period_start="2026-03-11T00:00:00Z")
    assert line["cap_side_pool_cents"] == 0, (
        f"the two accruals net to zero, got {line['cap_side_pool_cents']}"
    )

    response = api_client.validate_settlement_line(ctx["ppa_id"], line["id"], ANALYST)

    # PRD §3.4 names the gate but no error identifier for it, so only the
    # refusal itself and its inertness are asserted here.
    assert response.status_code >= 400, (
        f"an empty cap-side pool has nothing to reconcile; got {response.status_code}"
    )
    assert response.json()["response_type"] == "error"
    still = validate_success(
        api_client.get_settlement_line(ctx["ppa_id"], line["id"], ANALYST)
    )
    assert still["status"] == "SETTLEMENT_DRAFT"


def test_a_settlement_line_with_a_positive_pool_validates():
    """PRD §3.4: "Validation moves the line to `SETTLEMENT_VALIDATED` and computes its
    `net_charge_cents` and `expected_net_charge_cents`."

    Design: Difficulty/boundary_precision_check/validate_with_exactly_zero_cap_pool_returns_invalid_state
    """
    ctx = setup_active_ppa()
    post_accrual(
        ctx["ppa_id"], ctx["site_id"], accrual_type="CHARGE_ACCRUAL", amount_cents=100000
    )
    post_accrual(
        ctx["ppa_id"],
        ctx["site_id"],
        accrual_type="OUTPUT_GUARANTEE_ACCRUAL",
        amount_cents=100000,
    )
    # A single additional cent of open charge accrual lifts the pool above zero.
    post_accrual(
        ctx["ppa_id"], ctx["site_id"], accrual_type="CHARGE_ACCRUAL", amount_cents=1
    )
    line = create_settlement_line(ctx["ppa_id"], period_start="2026-03-11T00:00:00Z")
    assert line["cap_side_pool_cents"] == 1

    validated = validate_success(
        api_client.validate_settlement_line(ctx["ppa_id"], line["id"], ANALYST)
    )
    assert validated["status"] == "SETTLEMENT_VALIDATED"