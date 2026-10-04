"""Difficulty queue A: temporal overlap — one-active-binding rule and the
prescription validity closed interval against the logical clock."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_approved_verification,
    create_order,
    create_payer,
    create_prescription,
    make_patient_headers,
    set_clock,
    setup_delivered_unit,
    setup_supply_pipeline,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
FULFILL = TEST_USERS["fulfillment_agent_headers"]


def test_second_binding_on_same_channel_while_first_active_rejected(api):
    """PRD §3.7: "First, the one-active-sensor rule: at most one `ACTIVE`
    device binding may exist per patient per channel. The new binding's
    half-open interval — beginning at `activated_at` and ending at
    `expires_at` — must not overlap any existing `ACTIVE` binding's interval
    on the same channel for the same patient; an overlap is rejected with
    `ERR_ACTIVE_BINDING_EXISTS`."

    Design: Difficulty/resource_temporal_overlap/one_active_binding_per_channel_half_open_interval
    """
    ctx = setup_delivered_unit(num_units=2, quantity_per_fill=2)
    patient = ctx["patient"]
    first, second = ctx["units"][0], ctx["units"][1]
    resp1 = api.create_device_binding(
        patient["id"],
        {"sensor_unit_id": first["id"], "channel": "READER"},
        make_patient_headers(patient["id"]),
    )
    validate_success(resp1, expected_status=201)
    resp2 = api.create_device_binding(
        patient["id"],
        {"sensor_unit_id": second["id"], "channel": "READER"},
        make_patient_headers(patient["id"]),
    )
    validate_error(resp2, ApiErrorId.ERR_ACTIVE_BINDING_EXISTS, expected_status=409)


def test_second_binding_on_different_channel_while_first_active_allowed(api):
    """PRD §3.7: "First, the one-active-sensor rule: at most one `ACTIVE`
    device binding may exist per patient per channel."

    The rule scopes to the channel: a second ACTIVE binding on the *other*
    channel does not overlap the first binding's channel scope.

    Design: Difficulty/resource_temporal_overlap/one_active_binding_per_channel_half_open_interval
    """
    ctx = setup_delivered_unit(
        num_units=2, quantity_per_fill=2, product_overrides={"reader_channel": "HYBRID"}
    )
    patient = ctx["patient"]
    first, second = ctx["units"][0], ctx["units"][1]
    resp1 = api.create_device_binding(
        patient["id"],
        {"sensor_unit_id": first["id"], "channel": "READER"},
        make_patient_headers(patient["id"]),
    )
    validate_success(resp1, expected_status=201)
    resp2 = api.create_device_binding(
        patient["id"],
        {"sensor_unit_id": second["id"], "channel": "APP"},
        make_patient_headers(patient["id"]),
    )
    binding2 = validate_success(resp2, expected_status=201)
    assert binding2["channel"] == "APP"
    assert binding2["status"] == "ACTIVE"


def test_order_on_expires_on_date_permitted(api):
    """PRD §3.3: "The server sets `fills_consumed` to zero, computes
    `expires_on` as exactly 365 days after `written_on`"
    PRD §3.5: "The prescription must be `ACTIVE` and not past its
    `expires_on`, failing which the create yields
    `ERR_PRESCRIPTION_NOT_ACTIVE`."

    written_on 2025-09-01 -> expires_on 2026-09-01; an order placed on
    2026-09-01 (not past expires_on) is permitted.

    Design: Difficulty/resource_temporal_overlap/prescription_expiry_closed_interval_vs_logical_date
    """
    ctx = setup_supply_pipeline()
    patient = ctx["patient"]
    patient = validate_success(api.get_patient(patient["id"], ADMIN))
    rx = create_prescription(
        patient, ctx["prescriber"], ctx["product"],
        quantity_per_fill=1, written_on="2025-09-01",
    )
    assert rx["expires_on"] == "2026-09-01"
    cv = create_approved_verification(rx, ctx["payer"])
    order = create_order(patient, rx, cv, ctx["lot"])
    assert order["fulfillment_status"] == "PENDING_PICK"


def test_order_one_day_past_expires_on_rejected(api):
    """PRD §3.5: "The prescription must be `ACTIVE` and not past its
    `expires_on`, failing which the create yields
    `ERR_PRESCRIPTION_NOT_ACTIVE`."
    PRD §3.3: "When the logical clock passes `expires_on`, the prescription
    auto-transitions to `EXPIRED`."

    written_on 2025-09-01 -> expires_on 2026-09-01; at logical date
    2026-09-02 the prescription is past its validity and the order is
    rejected.

    Design: Difficulty/resource_temporal_overlap/prescription_expiry_closed_interval_vs_logical_date
    """
    ctx = setup_supply_pipeline()
    patient = validate_success(api.get_patient(ctx["patient"]["id"], ADMIN))
    rx = create_prescription(
        patient, ctx["prescriber"], ctx["product"],
        quantity_per_fill=1, written_on="2025-09-01",
    )
    cv = create_approved_verification(rx, ctx["payer"])
    set_clock("2026-09-02T00:00:00Z")
    resp = api.create_sensor_order(
        patient["id"],
        {
            "prescription_id": rx["id"],
            "coverage_verification_id": cv["id"],
            "lot_id": ctx["lot"]["id"],
            "quantity": 1,
        },
        FULFILL,
    )
    validate_error(resp, ApiErrorId.ERR_PRESCRIPTION_NOT_ACTIVE, expected_status=409)
