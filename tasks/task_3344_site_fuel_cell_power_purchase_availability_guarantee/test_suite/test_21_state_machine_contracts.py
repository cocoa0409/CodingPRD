"""Refused edges, terminal lockdown and initial states across the contract, site
and custody machines."""
from test_helpers import api_client, validate_error, validate_success
from test_helpers.api_errors import ApiErrorId
from test_helpers.fixtures import (
    ANALYST,
    APPROVER,
    FUEL_COORDINATOR,
    OPERATOR,
    cancel_delivery,
    create_customer,
    create_ppa,
    create_settlement_line,
    create_site,
    get_delivery,
    get_ppa,
    get_service_plan,
    get_site,
    issue_allowance,
    list_deliveries,
    list_transitions,
    post_accrual,
    schedule_delivery,
    set_clock,
    setup_active_ppa,
    setup_validated_line,
    validate_settlement_line,
)


def test_terminating_a_live_contract_without_an_exit_request_is_refused():
    """PRD §3.8: "A `SiteOperator` terminates a contract in `PPA_EXIT_PENDING` only while the logical
    clock is strictly past the contract's `state_entered_at` plus
    `customer_cure_deadline_days`; a termination attempted before that instant is rejected."

    Design: Corner/state_machines/terminate_from_active_without_exit_returns_invalid_state
    """
    ctx = setup_active_ppa()
    plan_id = ctx["plan_id"]
    assert ctx["ppa"]["state"] == "PPA_ACTIVE"

    response = api_client.terminate_ppa(ctx["ppa_id"], OPERATOR)

    validate_error(response, ApiErrorId.ERR_INVALID_STATE)
    assert get_ppa(ctx["ppa_id"])["state"] == "PPA_ACTIVE", (
        "a refused terminate leaves the contract on the edge it started from"
    )
    assert get_service_plan(ctx["ppa_id"], plan_id)["lifecycle_state"] == "SERVICE_ACTIVE"


def test_the_refused_terminate_appends_no_transition_record():
    """PRD §3.2: "a transition record is appended
    carrying `from_state` `PPA_DRAFT`, `to_state` `PPA_ACTIVE`, trigger code `PPA_ACTIVATED`".

    Design: Corner/state_machines/terminate_from_active_without_exit_returns_invalid_state
    """
    ctx = setup_active_ppa()

    api_client.terminate_ppa(ctx["ppa_id"], OPERATOR)

    transitions = list_transitions(ctx["ppa_id"])
    assert len(transitions) == 1, (
        f"only the activation transition may exist; found {len(transitions)} records"
    )
    assert transitions[0]["to_state"] == "PPA_ACTIVE"


def test_requesting_an_exit_from_a_draft_contract_is_refused():
    """PRD §3.8: "A `SiteOperator`
    records an exit request on a contract that is either `PPA_ACTIVE` or `PPA_SUSPENDED`."

    Design: Corner/state_machines/exit_requested_from_draft_ppa_returns_invalid_state
    """
    set_clock()
    site = create_site()
    customer = create_customer()
    ppa = create_ppa(site["id"], customer["id"])
    assert ppa["state"] == "PPA_DRAFT"

    response = api_client.request_exit(ppa["id"], OPERATOR)

    validate_error(response, ApiErrorId.ERR_INVALID_STATE)
    after = get_ppa(ppa["id"])
    assert after["state"] == "PPA_DRAFT"


def test_a_draft_contract_carries_no_exit_transition_after_a_refused_request():
    """PRD §3.8: "a transition record is appended with trigger code `EXIT_REQUESTED` — or
    `EXIT_REQUESTED_FROM_SUSPENDED` when the request came from the suspended state".

    Design: Corner/state_machines/exit_requested_from_draft_ppa_returns_invalid_state
    """
    set_clock()
    site = create_site()
    customer = create_customer()
    ppa = create_ppa(site["id"], customer["id"])

    api_client.request_exit(ppa["id"], OPERATOR)

    assert list_transitions(ppa["id"]) == [], (
        "the draft machine has no PPA_DRAFT -> PPA_EXIT_PENDING edge, so nothing is recorded"
    )


def test_confirming_a_delivery_that_was_never_dispatched_is_refused():
    """PRD §2.6: "the delivery may not be confirmed before
    its `confirm_after_iso8601` instant has passed, and an early confirmation is refused with
    `ERR_CONFIRM_TOO_EARLY` (HTTP 422)."

    Design: Corner/state_machines/confirm_from_scheduled_delivery_returns_invalid_state
    """
    ctx = setup_active_ppa()
    delivery = schedule_delivery(
        ctx["site_id"],
        volume_therms=8000,
        delivered_at="2026-03-05T00:00:00Z",
        confirm_after_iso8601="2026-03-06T00:00:00Z",
    )
    assert get_delivery(ctx["site_id"], delivery["id"])["lifecycle_state"] == (
        "DELIVERY_SCHEDULED"
    )

    response = api_client.confirm_fuel_delivery(
        ctx["site_id"], delivery["id"], FUEL_COORDINATOR
    )

    assert response.status_code in (409, 422), (
        "a scheduled load has no shortcut into custody; got "
        f"{response.status_code} {response.text}"
    )
    assert get_delivery(ctx["site_id"], delivery["id"])["lifecycle_state"] == (
        "DELIVERY_SCHEDULED"
    ), "the refused confirm must leave the custody state untouched"


def test_the_refused_confirm_opens_no_accrual_against_the_contract():
    """PRD §3.3: "a `PpaAccrual` of type `CHARGE_ACCRUAL` is opened in `ACCRUAL_OPEN` against the
    contract that won the allocation".

    Design: Corner/state_machines/confirm_from_scheduled_delivery_returns_invalid_state
    """
    ctx = setup_active_ppa()
    delivery = schedule_delivery(
        ctx["site_id"],
        volume_therms=8000,
        delivered_at="2026-03-05T00:00:00Z",
        confirm_after_iso8601="2026-03-06T00:00:00Z",
    )

    api_client.confirm_fuel_delivery(ctx["site_id"], delivery["id"], FUEL_COORDINATOR)

    body = validate_success(
        api_client.list_accruals(OPERATOR, {"ppa_id": ctx["ppa_id"]})
    )
    accruals = body["data"] if isinstance(body, dict) and "data" in body else body
    assert accruals == [], (
        "custody never became accounting, so no accrual may be opened; found "
        f"{[a['accrual_type'] for a in accruals]}"
    )


def test_settling_a_line_that_was_never_approved_is_refused():
    """PRD §3.4: "Approval belongs to the `SettlementApprover` and is narrower than validation. The line must
    already be `SETTLEMENT_VALIDATED`".

    Design: Corner/state_machines/settle_before_approve_returns_invalid_state
    """
    ctx = setup_validated_line()
    assert ctx["line"]["status"] == "SETTLEMENT_VALIDATED"

    response = api_client.settle_settlement_line(ctx["ppa_id"], ctx["line_id"], OPERATOR)

    assert response.status_code in (403, 409), (
        "the id-checked settle of an unapproved line is refused; got "
        f"{response.status_code} {response.text}"
    )
    assert api_client.get_settlement_line(
        ctx["ppa_id"], ctx["line_id"], ANALYST
    ).json()["data"]["status"] == "SETTLEMENT_VALIDATED"


def test_the_refused_settle_leaves_the_issued_allowance_unconsumed():
    """PRD §3.4: "one settlement allowance is consumed, its `lifecycle_state` becoming
    `ALLOWANCE_APPLIED` with its `applied_direction` recorded as `ALLOWANCE_APPLIED_AS_TIME`."

    Design: Corner/state_machines/settle_before_approve_returns_invalid_state
    """
    ctx = setup_validated_line()

    api_client.settle_settlement_line(ctx["ppa_id"], ctx["line_id"], OPERATOR)

    rows = validate_success(api_client.list_allowances(ctx["ppa_id"], ANALYST))
    allowances = rows["data"] if isinstance(rows, dict) and "data" in rows else rows
    assert [a["lifecycle_state"] for a in allowances] == ["ALLOWANCE_ISSUED"], (
        "a settle that never ran cannot have consumed an allowance"
    )


def test_reversing_a_line_that_was_never_settled_is_refused():
    """PRD §3.4: "A `SettlementApprover` may reverse an applied line only while the logical clock has not passed
    the line's applied instant plus `SETTLEMENT_REVERSAL_WINDOW_DAYS`".

    Design: Corner/state_machines/reverse_before_settle_returns_invalid_state
    """
    set_clock()
    site = create_site()
    customer = create_customer()
    ppa = create_ppa(site["id"], customer["id"])
    activated = validate_success(api_client.activate_ppa(ppa["id"], OPERATOR))
    post_accrual(ppa["id"], site["id"], accrual_type="CHARGE_ACCRUAL", amount_cents=100000)
    issue_allowance(ppa["id"], amount_cents=185000)
    line = create_settlement_line(ppa["id"])
    validated = validate_settlement_line(ppa["id"], line["id"])
    validate_success(api_client.approve_settlement_line(ppa["id"], line["id"], APPROVER))

    assert validated["status"] == "SETTLEMENT_VALIDATED"
    assert activated["state"] == "PPA_ACTIVE"

    response = api_client.reverse_settlement_line(ppa["id"], line["id"], APPROVER)

    assert response.status_code in (403, 409), (
        "the reversal edge is only reachable from SETTLEMENT_APPLIED; got "
        f"{response.status_code} {response.text}"
    )
    after = api_client.get_settlement_line(ppa["id"], line["id"], ANALYST).json()["data"]
    assert after["status"] == "SETTLEMENT_APPROVED"
    assert after["allocation_basis"] == "ALLOCATION_ORDER"


def test_a_second_termination_of_a_terminated_contract_is_refused():
    """PRD §3.8: "A
    second termination of the same contract is refused outright with `ERR_ALREADY_TERMINAL`
    (HTTP 409)".

    Design: Corner/state_machines/second_terminate_on_terminated_ppa_returns_already_terminal
    """
    set_clock()
    site = create_site()
    customer = create_customer()
    ppa = create_ppa(site["id"], customer["id"])
    validate_success(api_client.activate_ppa(ppa["id"], OPERATOR))
    validate_success(api_client.request_exit(ppa["id"], OPERATOR))
    set_clock("2026-04-20T00:00:00Z")
    terminated = validate_success(api_client.terminate_ppa(ppa["id"], OPERATOR))
    assert terminated["state"] == "PPA_TERMINATED"

    response = api_client.terminate_ppa(ppa["id"], OPERATOR)

    validate_error(response, ApiErrorId.ERR_ALREADY_TERMINAL)
    assert get_ppa(ppa["id"])["state"] == "PPA_TERMINATED"


def test_a_terminated_contract_decrements_the_site_only_once():
    """PRD §3.8: "decrements the site's
    `active_ppa_count`, returns the site's `lifecycle_state` to `RESOURCE_AVAILABLE` when the
    active count has reached zero and the site still holds a positive `draw_position_therms`".

    Design: Corner/state_machines/second_terminate_on_terminated_ppa_returns_already_terminal
    """
    set_clock()
    site = create_site()
    customer = create_customer()
    ppa = create_ppa(site["id"], customer["id"])
    validate_success(api_client.activate_ppa(ppa["id"], OPERATOR))
    validate_success(api_client.request_exit(ppa["id"], OPERATOR))
    set_clock("2026-04-20T00:00:00Z")
    validate_success(api_client.terminate_ppa(ppa["id"], OPERATOR))

    api_client.terminate_ppa(ppa["id"], OPERATOR)

    after = get_site(site["id"])
    assert after["active_ppa_count"] == 0, (
        f"the count is decremented once by the accepted terminal edge; got {after['active_ppa_count']}"
    )
    assert after["lifecycle_state"] == "RESOURCE_AVAILABLE"
    assert after["draw_position_therms"] > 0


def test_a_second_cancel_of_a_cancelled_delivery_is_refused():
    """PRD §3.3: "`DELIVERY_CANCELLED` is terminal, and a cancellation aimed at a load that is
    already cancelled or already settled is refused with `ERR_ALREADY_TERMINAL` (HTTP 409) rather
    than silently succeeding".

    Design: Corner/state_machines/second_cancel_on_cancelled_delivery_returns_already_terminal
    """
    set_clock()
    site = create_site()
    delivery = schedule_delivery(
        site["id"],
        volume_therms=8000,
        delivered_at="2026-03-12T00:00:00Z",
        confirm_after_iso8601="2026-03-13T00:00:00Z",
    )
    cancelled = cancel_delivery(site["id"], delivery["id"])
    assert cancelled["lifecycle_state"] == "DELIVERY_CANCELLED"

    response = api_client.cancel_fuel_delivery(site["id"], delivery["id"], FUEL_COORDINATOR)

    validate_error(response, ApiErrorId.ERR_ALREADY_TERMINAL)
    assert get_delivery(site["id"], delivery["id"])["lifecycle_state"] == "DELIVERY_CANCELLED"


def test_the_refused_second_cancel_does_not_credit_the_pool_twice():
    """PRD §3.3: "cancellation returns the canceled
    `volume_therms` to the site's `draw_position_therms`".

    Design: Corner/state_machines/second_cancel_on_cancelled_delivery_returns_already_terminal
    """
    set_clock()
    site = create_site()
    delivery = schedule_delivery(
        site["id"],
        volume_therms=8000,
        delivered_at="2026-03-12T00:00:00Z",
        confirm_after_iso8601="2026-03-13T00:00:00Z",
    )
    cancel_delivery(site["id"], delivery["id"])
    after_cancel = get_site(site["id"])
    restored = after_cancel["draw_position_therms"]
    assert restored == after_cancel["initial_fuel_inventory_therms"], (
        "the cancellation restores the pool to the registration's opening inventory"
    )

    api_client.cancel_fuel_delivery(site["id"], delivery["id"], FUEL_COORDINATOR)

    assert get_site(site["id"])["draw_position_therms"] == restored, (
        "the terminal guard is what stops the pool being credited a second time"
    )


def test_a_new_delivery_starts_scheduled_and_never_settles_on_its_own():
    """PRD §3.3: "A confirmed load settles when the contract it supplied has at least one
    settlement line in `SETTLEMENT_APPLIED`; at that point the delivery moves to
    `DELIVERY_SETTLED`, its terminal state".

    Design: Corner/state_machines/delivered_delivery_is_not_settled_until_the_ppa_settles
    """
    ctx = setup_active_ppa()
    delivery = schedule_delivery(
        ctx["site_id"],
        volume_therms=8000,
        delivered_at="2026-03-05T00:00:00Z",
        confirm_after_iso8601="2026-03-06T00:00:00Z",
    )
    created = get_delivery(ctx["site_id"], delivery["id"])
    assert created["lifecycle_state"] == "DELIVERY_SCHEDULED", (
        "a delivery created with no lifecycle_state of its own starts scheduled"
    )

    api_client.dispatch_fuel_delivery(ctx["site_id"], delivery["id"], FUEL_COORDINATOR)
    set_clock("2026-03-07T00:00:00Z")
    confirmed = validate_success(
        api_client.confirm_fuel_delivery(ctx["site_id"], delivery["id"], FUEL_COORDINATOR)
    )

    assert confirmed["lifecycle_state"] == "DELIVERY_CONFIRMED", (
        "custody reaches the confirmed state but does not auto-advance to the terminal one"
    )
    reread = get_delivery(ctx["site_id"], delivery["id"])
    assert reread["lifecycle_state"] != "DELIVERY_SETTLED"


def test_confirmed_deliveries_are_listable_under_their_custody_state():
    """PRD §2.4: "The fuel delivery collection filters on `lifecycle_state` and `attesting_customer_id`
    when it is listed site-first".

    Design: Corner/state_machines/delivered_delivery_is_not_settled_until_the_ppa_settles
    """
    ctx = setup_active_ppa()
    delivery = schedule_delivery(
        ctx["site_id"],
        volume_therms=8000,
        delivered_at="2026-03-05T00:00:00Z",
        confirm_after_iso8601="2026-03-06T00:00:00Z",
    )
    api_client.dispatch_fuel_delivery(ctx["site_id"], delivery["id"], FUEL_COORDINATOR)
    set_clock("2026-03-07T00:00:00Z")
    validate_success(
        api_client.confirm_fuel_delivery(ctx["site_id"], delivery["id"], FUEL_COORDINATOR)
    )

    confirmed_rows = list_deliveries(
        ctx["site_id"], lifecycle_state="DELIVERY_CONFIRMED"
    )
    assert len(confirmed_rows) == 1, (
        f"exactly the receipted load carries that custody state; found {len(confirmed_rows)}"
    )
    assert confirmed_rows[0]["id"] == delivery["id"]


def test_a_registered_site_starts_active_and_a_second_freeze_is_refused():
    """PRD §3.1: "A newly registered facility starts with `status` of
    `SITE_ACTIVE`".
    PRD §2.5: "A facility may be suspended only while its posture is currently `SITE_ACTIVE`".

    Design: Corner/state_machines/site_starts_active_and_cannot_be_frozen_twice
    """
    ctx = setup_active_ppa()
    assert get_site(ctx["site_id"])["status"] == "SITE_ACTIVE"

    validate_success(api_client.freeze_site(ctx["site_id"], OPERATOR, "FUEL_SHORTAGE"))
    frozen = get_site(ctx["site_id"])
    assert frozen["status"] == "SITE_SUSPENDED"
    assert get_ppa(ctx["ppa_id"])["state"] == "PPA_SUSPENDED"

    response = api_client.freeze_site(ctx["site_id"], OPERATOR, "FUEL_SHORTAGE")

    assert response.status_code == 409, (
        "the already-SITE_SUSPENDED posture is a state problem; got "
        f"{response.status_code} {response.text}"
    )
    assert get_ppa(ctx["ppa_id"])["state"] == "PPA_SUSPENDED"


def test_a_refused_second_freeze_does_not_replay_the_suspension_cascade():
    """PRD §2.5: "Every contract hosted at that site
    in `PPA_ACTIVE` moves to `PPA_SUSPENDED`".

    Design: Corner/state_machines/site_starts_active_and_cannot_be_frozen_twice
    """
    ctx = setup_active_ppa()
    validate_success(api_client.freeze_site(ctx["site_id"], OPERATOR, "FUEL_SHORTAGE"))

    api_client.freeze_site(ctx["site_id"], OPERATOR, "FUEL_SHORTAGE")

    suspended_records = [
        t for t in list_transitions(ctx["ppa_id"]) if t["to_state"] == "PPA_SUSPENDED"
    ]
    assert len(suspended_records) == 1, (
        "the suspension transition is recorded exactly once; found "
        f"{len(suspended_records)}"
    )