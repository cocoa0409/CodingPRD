"""Corner coverage: state guards, terminal lockdown and initial states."""
from test_helpers import (
    canonical_instant,
    TEST_USERS,
    create_and_enact_jurisdiction,
    create_and_start_batch,
    create_appraisal_payload,
    create_center,
    create_order,
    create_published_configuration,
    create_verified_buyer,
    get_order,
    get_success_data,
    set_clock,
    validate_error,
    walk_order_to_at_delivery_center,
    walk_order_to_delivered,
)

ADMIN = TEST_USERS["platform_admin_headers"]
TECH = TEST_USERS["service_technician_headers"]
TRADEIN = TEST_USERS["trade_in_specialist_headers"]


def test_order_placement_without_a_settled_order_fee_returns_fee_unpaid(api):
    """PRD §3.2: "Fourth and last, the order fee must already have been captured to
    the ledger — an `OrderFeeLedgerEntry` of type `ORDER_FEE_PAYMENT` covering the
    order's `order_fee_cents` must exist, and its absence is refused with
    `ERR_ORDER_FEE_UNPAID` (HTTP 402)."

    Design: Corner/state_machines/order_placement_without_a_settled_order_fee_returns_fee_unpaid
    """
    set_clock()
    jur = create_and_enact_jurisdiction()
    center = create_center()
    config, _ = create_published_configuration()
    buyer = create_verified_buyer()
    order = create_order(buyer["id"], config["id"], jur["id"], center["id"])

    refused = api.place_order(order["id"], order["version"],
                              {"X-User-ID": buyer["id"], "X-User-Role": "Buyer",
                               "Content-Type": "application/json"})
    validate_error(refused, "ERR_ORDER_FEE_UNPAID", expected_status=402)

    still = get_order(order["id"])
    assert still["status"] == "DRAFT"
    assert still["configuration_lock_deadline"] is None

    estimates = get_success_data(api.list_order_estimates(order["id"], ADMIN))
    assert estimates == []


def test_allocation_on_a_draft_order_returns_invalid_state(api):
    """PRD §3.4: "The order must be `CONFIG_LOCKED` — otherwise
    `ERR_ORDER_NOT_CONFIG_LOCKED` (HTTP 409)"
    PRD §3.12: "State-precondition errors such as `ERR_ORDER_NOT_AT_CENTER`,
    `ERR_BATCH_NOT_SCHEDULED`, `ERR_APPOINTMENT_NOT_CONFIRMED`, `ERR_INVALID_STATE`,
    and `ERR_ALREADY_TERMINAL` are evaluated alongside the pipeline above at the
    point the specific workflow requires"

    Design: Corner/state_machines/allocation_on_a_draft_order_returns_invalid_state
    """
    set_clock()
    jur = create_and_enact_jurisdiction()
    center = create_center()
    config, _ = create_published_configuration()
    buyer = create_verified_buyer()
    order = create_order(buyer["id"], config["id"], jur["id"], center["id"])
    batch, unit = create_and_start_batch()

    refused = api.allocate_order(order["id"], batch["id"], order["version"], ADMIN)
    assert refused.status_code == 409
    error_id = refused.json()["data"]["error_id"]
    assert error_id in ("ERR_INVALID_STATE", "ERR_ORDER_NOT_CONFIG_LOCKED")

    assert get_order(order["id"])["status"] == "DRAFT"
    assert get_success_data(
        api.get_allocation_unit(unit["id"], ADMIN))["status"] == "UNASSIGNED"


def test_cancellation_of_a_delivered_order_returns_already_terminal(api):
    """PRD §3.7: "Both variants start from the same core"
    PRD §3.8: "A delivered order is terminal and lies outside this path"
    PRD §3.8: "Cancellation does not, by itself, reverse a completed delivery."

    Design: Corner/state_machines/cancellation_of_a_delivered_order_returns_already_terminal
    """
    set_clock()
    ctx = walk_order_to_delivered()
    order_id = ctx["order"]["id"]

    refused = api.cancel_order(order_id, ADMIN)
    assert refused.status_code == 409
    error_id = refused.json()["data"]["error_id"]
    assert error_id == "ERR_ALREADY_TERMINAL"

    assert get_order(order_id)["status"] == "DELIVERED"

    entries = get_success_data(api.list_order_ledger_entries(order_id, ADMIN))
    types = [e["entry_type"] for e in entries]
    assert "ORDER_FEE_REFUND" not in types, (
        "no compensating refund is written against a delivered order"
    )


def test_repeat_appraisal_on_an_already_appraised_row_returns_invalid_state(api):
    """PRD §3.3: "Recording the desktop appraisal requires the row to be `DRAFT` —
    otherwise `ERR_APPRAISAL_NOT_DRAFT` (HTTP 409)"
    PRD §3.3: "`net_credit_cents` is computed at creation and recomputed at
    appraisal time and at reappraisal time."

    Design: Corner/state_machines/repeat_appraisal_on_an_already_appraised_row_returns_invalid_state
    """
    set_clock()
    ctx = walk_order_to_at_delivery_center()
    order = ctx["order"]
    appraisal = get_success_data(api.create_appraisal(
        order["id"],
        create_appraisal_payload(trade_vin="5YJ3E1EA7PF000910", mileage=90000,
                                 gross_offer_cents=1200000,
                                 reconditioning_estimate_cents=60000,
                                 offer_valid_until="2026-10-15T00:00:00Z"),
        TRADEIN))
    first = get_success_data(api.appraise(order["id"], appraisal["id"], TRADEIN))
    assert first["net_credit_cents"] == 940000, (
        "1140000 raw less the 200000-cent capped mileage deduction"
    )

    again = api.appraise(order["id"], appraisal["id"], TRADEIN)
    assert again.status_code == 409
    error_id = again.json()["data"]["error_id"]
    assert error_id in ("ERR_INVALID_STATE", "ERR_APPRAISAL_NOT_DRAFT")

    frozen = get_success_data(api.get_appraisal(appraisal["id"], TRADEIN))
    assert frozen["net_credit_cents"] == 940000
    assert frozen["status"] == "APPRAISED"


def test_center_transition_with_the_wrong_selected_value_is_rejected(api):
    """PRD §3.4: "A superseded estimate may be restored as the live window,
    provided its `window_start` is still at or after the current clock instant —
    otherwise the restoration is refused with `ERR_ESTIMATE_WINDOW_EXPIRED`
    (HTTP 409)."

    Design: Corner/state_machines/center_transition_with_the_wrong_selected_value_is_rejected
    """
    set_clock()
    ctx = walk_order_to_at_delivery_center()
    order_id = ctx["order"]["id"]
    estimates = get_success_data(api.list_order_estimates(order_id, ADMIN))
    first = [e for e in estimates if e["prior_estimate_id"] is None][0]

    get_success_data(api.project_delivery_estimate(
        order_id, {"basis_iso8601": "2026-09-21T00:00:00Z", "window_days": 7}, ADMIN))
    assert get_success_data(
        api.get_delivery_estimate(first["id"], ADMIN))["estimate_state"] == "SUPERSEDED"

    # Push the clock past the superseded estimate's own window start.
    get_success_data(api.set_current_utc("2026-09-30T00:00:00Z", ADMIN))

    refused = api.restore_delivery_estimate(first["id"], ADMIN)
    validate_error(refused, "ERR_ESTIMATE_WINDOW_EXPIRED", expected_status=409)
    assert get_success_data(
        api.get_delivery_estimate(first["id"], ADMIN))["estimate_state"] == "SUPERSEDED"


def test_batch_resume_from_a_scheduled_batch_returns_invalid_state(api):
    """PRD §3.4: "resuming requires `DELAYED` or the refusal is
    `ERR_BATCH_NOT_DELAYED`"
    PRD §3.4: "A batch is created `SCHEDULED` with `allocated_unit_count` 0,
    `delay_days` 0"

    Design: Corner/state_machines/batch_resume_from_a_scheduled_batch_returns_invalid_state
    """
    set_clock()
    fresh = get_success_data(api.create_production_batch(
        {"factory_code": "AUSTIN", "model_code": "MODEL_Y_LR_AWD",
         "unit_capacity": 2, "planned_completion_at": "2026-09-10T00:00:00Z"}, ADMIN))
    assert fresh["status"] == "SCHEDULED"

    refused = api.resume_batch(fresh["id"], ADMIN)
    assert refused.status_code == 409
    error_id = refused.json()["data"]["error_id"]
    assert error_id in ("ERR_INVALID_STATE", "ERR_BATCH_NOT_DELAYED")

    after = get_success_data(api.get_production_batch(fresh["id"], ADMIN))
    assert after["status"] == "SCHEDULED"
    assert after["delay_days"] == 0


def test_entitlement_state_axis_reads_active_immediately_after_grant(api):
    """PRD §3.11: "the grants are written as one row per entry in the order
    submitted, all `ACTIVE`, all stamped `effective_at` with the current instant"
    PRD §3.11: "A `TRIAL` row's `expires_at` is `effective_at` plus `trial_days`
    days; every other source has a null `expires_at` because the grant is
    perpetual."

    Design: Corner/state_machines/entitlement_state_axis_reads_active_immediately_after_grant
    """
    set_clock()
    ctx = walk_order_to_delivered()
    vehicle_id = ctx["vehicle"]["id"]

    purchase = get_success_data(api.grant_entitlements(
        vehicle_id,
        {"feature_entries": [{"feature_code": "PREMIUM_CONNECTIVITY",
                              "price_cents": 100000}],
         "entitlement_source": "PURCHASE"}, ADMIN))
    row = purchase[0]
    assert row["status"] == "ACTIVE"
    assert canonical_instant(row["effective_at"]) == "2026-09-01T00:00:00.000Z"
    assert row["expires_at"] is None, "a perpetual grant has no expiry"

    trial = get_success_data(api.grant_entitlements(
        vehicle_id,
        {"feature_entries": [{"feature_code": "FSD_TRIAL", "price_cents": 0}],
         "entitlement_source": "TRIAL", "trial_days": 30}, ADMIN))
    assert canonical_instant(trial[0]["expires_at"]) == "2026-10-01T00:00:00.000Z"

    rows = get_success_data(api.list_entitlements(ADMIN))
    assert len(rows) == 2
    assert {r["feature_code"] for r in rows} == {"PREMIUM_CONNECTIVITY", "FSD_TRIAL"}
