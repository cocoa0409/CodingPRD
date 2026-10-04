"""Corner queue B: validations, endpoint CRUD/listing, error envelope, OCC,
RBAC segregation-of-duties, cross-cutting layers, and read-after-write
consistency."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_lot,
    create_order,
    create_patient,
    create_payer,
    create_payer_payload,
    create_prescriber,
    create_prescription,
    create_product,
    create_units,
    make_patient_headers,
    make_prescriber_headers,
    pick_order,
    run_verification,
    setup_failed_unit,
    setup_supply_pipeline,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
REVIEWER = TEST_USERS["coverage_reviewer_headers"]
FULFILL = TEST_USERS["fulfillment_agent_headers"]
BILLING = TEST_USERS["billing_agent_headers"]
WARRANTY = TEST_USERS["warranty_reviewer_headers"]
SUPPORT = TEST_USERS["patient_support_agent_headers"]
PATIENT_FALLBACK = TEST_USERS["patient_headers"]


# ---------------------------------------------------------------------------
# validations
# ---------------------------------------------------------------------------

def test_quantity_mismatch_on_order_create(api):
    """PRD §3.5: "The order's `quantity` must equal the prescription's
    `quantity_per_fill` exactly, failing which the create yields
    `ERR_QUANTITY_MISMATCH`."

    Design: Corner/validations/quantity_mismatch_on_order_create
    """
    ctx = setup_supply_pipeline(quantity_per_fill=2)
    resp = api.create_sensor_order(
        ctx["patient"]["id"],
        {
            "prescription_id": ctx["prescription"]["id"],
            "coverage_verification_id": ctx["verification"]["id"],
            "lot_id": ctx["lot"]["id"],
            "quantity": 3,
        },
        FULFILL,
    )
    validate_error(resp, ApiErrorId.ERR_QUANTITY_MISMATCH, expected_status=422)


def test_product_mismatch_on_order_create(api):
    """PRD §3.5: "The product associated with the chosen `lot_id` must equal
    the prescription's `product_id` — no cross-product substitution is
    permitted — or the create fails with `ERR_PRODUCT_MISMATCH`."

    Design: Corner/validations/product_mismatch_on_order_create
    """
    ctx = setup_supply_pipeline()
    other_product = create_product()
    other_lot = create_lot(other_product)
    resp = api.create_sensor_order(
        ctx["patient"]["id"],
        {
            "prescription_id": ctx["prescription"]["id"],
            "coverage_verification_id": ctx["verification"]["id"],
            "lot_id": other_lot["id"],
            "quantity": 1,
        },
        FULFILL,
    )
    validate_error(resp, ApiErrorId.ERR_PRODUCT_MISMATCH, expected_status=422)


def test_savings_card_state_exclusion(api):
    """PRD §3.10: "First, the patient's `state_code` must not be `MA`, `CA`,
    or `WA` and the named payer's `benefit_route` must be `PHARMACY`;
    violating either constraint rejects the enrollment with
    `ERR_SAVINGS_CARD_NOT_PERMITTED`."

    Design: Corner/validations/savings_card_state_exclusion
    """
    patient = create_patient(state_code="MA")
    payer = create_payer(benefit_route="PHARMACY")
    resp = api.create_support_enrollment(
        patient["id"], {"payer_id": payer["id"], "card_max_per_fill_cents": 5000}, SUPPORT
    )
    validate_error(resp, ApiErrorId.ERR_SAVINGS_CARD_NOT_PERMITTED, expected_status=422)


def test_savings_card_dme_route_excluded(api):
    """PRD §3.10: "First, the patient's `state_code` must not be `MA`, `CA`,
    or `WA` and the named payer's `benefit_route` must be `PHARMACY`;
    violating either constraint rejects the enrollment with
    `ERR_SAVINGS_CARD_NOT_PERMITTED`."

    Design: Corner/validations/savings_card_dme_route_excluded
    """
    patient = create_patient(state_code="TX")
    payer = create_payer(benefit_route="DME", pharmacy_copay_pct=0.0, dme_coinsurance_pct=0.20)
    resp = api.create_support_enrollment(
        patient["id"], {"payer_id": payer["id"], "card_max_per_fill_cents": 5000}, SUPPORT
    )
    validate_error(resp, ApiErrorId.ERR_SAVINGS_CARD_NOT_PERMITTED, expected_status=422)


def test_reader_channel_reader_only_rejects_app(api):
    """PRD §3.7: "The chosen channel must be permitted by the product's
    `reader_channel`: a `READER`-only product accepts only `READER`, an
    `APP`-only product accepts only `APP`, and a `HYBRID` product accepts
    either; an impermissible channel is rejected with
    `ERR_CHANNEL_NOT_SUPPORTED`."

    Design: Corner/validations/reader_channel_reader_only_rejects_app
    """
    from test_helpers import setup_delivered_unit

    ctx = setup_delivered_unit(product_overrides={"reader_channel": "READER"})
    patient = ctx["patient"]
    unit = ctx["units"][0]
    resp = api.create_device_binding(
        patient["id"],
        {"sensor_unit_id": unit["id"], "channel": "APP"},
        make_patient_headers(patient["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_CHANNEL_NOT_SUPPORTED, expected_status=422)


def test_strict_payer_requires_intensive_insulin(api):
    """PRD §3.4: "Under `STRICT`, all three of the following must hold: the
    prescription's `diagnosis_code` is in the covered-diagnosis set, the
    `insulin_use` is `INTENSIVE`, and `documentation_attached` is true."
    PRD §3.4: "Failing the applicable policy rejects the approval with
    `ERR_COVERAGE_CRITERIA_NOT_MET`."

    Design: Corner/validations/strict_payer_requires_intensive_insulin
    """
    patient = create_patient()
    prescriber = create_prescriber()
    product = create_product()
    payer = create_payer(cgm_coverage_policy="STRICT")
    rx = create_prescription(patient, prescriber, product, insulin_use="BASAL_ONLY")
    cv = run_verification(rx, payer)
    resp = api.decide_coverage_verification(cv["id"], {"decision": "APPROVED"}, REVIEWER)
    validate_error(resp, ApiErrorId.ERR_COVERAGE_CRITERIA_NOT_MET, expected_status=422)


# ---------------------------------------------------------------------------
# endpoints
# ---------------------------------------------------------------------------

def test_get_patient_returns_full_payload(api):
    """PRD §2.4: "Every primary resource in the system carries a standard set
    of system-managed fields."
    PRD §2.4: "The `id` is a server-minted UUID with no type prefix."
    PRD §2.4: "The `version` field is an integer starting at 1 that increments
    on every mutation and serves as the optimistic-concurrency token for
    endpoints that accept one."
    PRD §3.1: "A patient record captures the patient's `full_name`,
    `date_of_birth` as an ISO calendar date, and the `state_code` used for
    savings-card eligibility gating; patients are created in `ACTIVE` status
    and may later be marked `DECEASED` or `TRANSFERRED_OUT` through
    administrative action."

    Design: Corner/endpoints/get_patient_returns_full_payload
    """
    created = create_patient(full_name="E1", state_code="TX")
    fetched = validate_success(api.get_patient(created["id"], ADMIN))
    assert fetched["full_name"] == "E1"
    assert fetched["state_code"] == "TX"
    assert fetched["status"] == "ACTIVE"
    assert fetched["version"] == 1


def test_prescription_list_returns_paginated(api):
    """PRD §2.3: "Paginated list responses include `limit`, `offset`,
    `total_count`, and `has_more` in the `meta` block of the envelope."
    PRD §3.3: "A prescription begins in `ACTIVE`."

    Design: Corner/endpoints/prescription_list_returns_paginated
    """
    patient = create_patient()
    prescriber = create_prescriber()
    product = create_product()
    create_prescription(patient, prescriber, product)
    patient = validate_success(api.get_patient(patient["id"], ADMIN))
    create_prescription(patient, prescriber, product)
    items, meta = validate_paginated(api.list_patient_prescriptions(patient["id"], ADMIN))
    assert len(items) == 2
    assert meta["total_count"] == 2
    assert all(item["status"] == "ACTIVE" for item in items)


# ---------------------------------------------------------------------------
# errors / envelope / OCC
# ---------------------------------------------------------------------------

def test_error_envelope_shape(api):
    """PRD §2.2: "All error API responses (4xx status codes) follow this
    standard envelope format"
    PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that
    identifies the specific error."
    PRD §2.2: "The `message` provides a human-readable explanation of what
    went wrong."

    Design: Corner/errors/error_envelope_shape
    """
    resp = api.get_patient(NON_EXISTENT_UUID, ADMIN)
    assert resp.status_code == 404
    body = resp.json()
    assert body["response_type"] == "error"
    assert isinstance(body["meta"]["api_request_id"], str)
    assert isinstance(body["meta"]["api_request_timestamp"], str)
    assert body["data"]["error_id"] == "ERR_NOT_FOUND"
    assert isinstance(body["data"]["message"], str) and len(body["data"]["message"]) > 0


def test_error_stale_patient_version_via_occ(api):
    """PRD §2.9: "A request that creates a new prescription against a patient
    must include `expected_patient_version`, carrying the client's
    last-observed `version` of the patient record. If the patient's current
    `version` no longer matches — for example because another writer has just
    changed the patient's `state_code` (which would alter savings-card
    eligibility) or flipped `status` to `DECEASED` — the create is rejected
    with `ERR_STALE_PATIENT_VERSION` (HTTP 412)."

    Design: Corner/errors/error_stale_patient_version_via_occ
    """
    patient = create_patient()
    stale_version = patient["version"]
    prescriber = create_prescriber()
    product = create_product()
    # first create succeeds and bumps the patient's version
    create_prescription(patient, prescriber, product)
    from test_helpers import create_prescription_payload

    payload = create_prescription_payload(
        prescriber["id"], product["id"], stale_version
    )
    resp = api.create_prescription(
        patient["id"], payload, make_prescriber_headers(prescriber["id"])
    )
    validate_error(resp, ApiErrorId.ERR_STALE_PATIENT_VERSION, expected_status=412)


def test_error_stale_order_version_via_occ(api):
    """PRD §2.9: "A request that adjudicates a sensor order must include
    `expected_order_version`, carrying the billing agent's last-observed
    `version` of the order. If the order's `version` has advanced since that
    read — for example because a fulfillment agent picked the order and
    thereby bumped its `version` — the adjudication is rejected with
    `ERR_STALE_ORDER_VERSION` (HTTP 412)."

    Design: Corner/errors/error_stale_order_version_via_occ
    """
    ctx = setup_supply_pipeline()
    order = create_order(ctx["patient"], ctx["prescription"], ctx["verification"], ctx["lot"])
    stale_version = order["version"]
    # pick advances the order's version before the adjudication attempt
    pick_order(order)
    resp = api.adjudicate_sensor_order(
        order["id"], {"expected_order_version": stale_version}, BILLING
    )
    validate_error(resp, ApiErrorId.ERR_STALE_ORDER_VERSION, expected_status=412)


# ---------------------------------------------------------------------------
# rbac
# ---------------------------------------------------------------------------

def test_patient_cannot_create_payer(api):
    """PRD §2.1: "If the named role is not permitted to invoke the endpoint,
    the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS`."
    PRD §4: POST `/cgm/payers` is authorized for PlatformAdmin only.

    Design: Corner/rbac/patient_cannot_create_payer
    """
    resp = api.create_payer(create_payer_payload(), PATIENT_FALLBACK)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, expected_status=403)


def test_fulfillment_agent_cannot_adjudicate(api):
    """PRD §2.1: "If the named role is not permitted to invoke the endpoint,
    the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS`."
    PRD §4: POST `/cgm/sensor-orders/{id}/adjudicate` is authorized for
    BillingAgent only.

    Design: Corner/rbac/fulfillment_agent_cannot_adjudicate
    """
    ctx = setup_supply_pipeline()
    order = create_order(ctx["patient"], ctx["prescription"], ctx["verification"], ctx["lot"])
    resp = api.adjudicate_sensor_order(
        order["id"], {"expected_order_version": order["version"]}, FULFILL
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, expected_status=403)


def test_patient_cannot_review_own_warranty_claim(api):
    """PRD §2.1: "If the named role is not permitted to invoke the endpoint,
    the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS`."
    PRD §4: POST `/cgm/warranty-claims/{id}/begin-review` is authorized for
    WarrantyReviewer only.

    Design: Corner/rbac/patient_cannot_review_own_warranty_claim
    """
    ctx = setup_failed_unit(failure_day_index=3, device_data_attached=True)
    resp = api.begin_review_warranty_claim(
        ctx["claim"]["id"], make_patient_headers(ctx["patient"]["id"])
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, expected_status=403)


def test_prescriber_cannot_cancel_other_prescribers_prescription(api):
    """PRD §3.3: "A prescriber may also cancel an active prescription directly;
    the cancellation is rejected with `ERR_PRESCRIPTION_NOT_ACTIVE` if the
    prescription is not `ACTIVE`, and with `ERR_PRESCRIPTION_OWNER_MISMATCH` if
    the acting prescriber's `id` does not match the prescription's
    `prescriber_id`."

    Design: Corner/rbac/prescriber_cannot_cancel_other_prescribers_prescription
    """
    patient = create_patient()
    prescriber_a = create_prescriber()
    prescriber_b = create_prescriber(specialty="PRIMARY_CARE")
    product = create_product()
    rx = create_prescription(patient, prescriber_a, product)
    resp = api.cancel_prescription(rx["id"], make_prescriber_headers(prescriber_b["id"]))
    validate_error(resp, ApiErrorId.ERR_PRESCRIPTION_OWNER_MISMATCH, expected_status=403)


def test_patient_cannot_report_failure_for_another_patients_unit(api):
    """PRD §3.8: "The report requires the unit to be `ACTIVE` (otherwise
    `ERR_UNIT_NOT_ACTIVE`) and the acting patient's `X-User-ID` to equal the
    unit's `patient_id` (otherwise `ERR_UNIT_OWNER_MISMATCH`)."

    Design: Corner/rbac/patient_cannot_report_failure_for_another_patients_unit
    """
    from test_helpers import activate_unit, setup_delivered_unit

    ctx = setup_delivered_unit()
    owner = ctx["patient"]
    unit = ctx["units"][0]
    activate_unit(owner, unit)
    intruder = create_patient()
    resp = api.report_early_failure(unit["id"], make_patient_headers(intruder["id"]))
    validate_error(resp, ApiErrorId.ERR_UNIT_OWNER_MISMATCH, expected_status=403)


# ---------------------------------------------------------------------------
# cross-cutting layers / consistency
# ---------------------------------------------------------------------------

def test_patient_version_increments_on_prescription_create(api):
    """PRD §3.3: "The server sets `fills_consumed` to zero, computes
    `expires_on` as exactly 365 days after `written_on`, and increments the
    patient's `version` by one as part of the same write"
    PRD §2.4: "The `version` field is an integer starting at 1 that increments
    on every mutation and serves as the optimistic-concurrency token for
    endpoints that accept one."

    Design: Corner/cross_cutting_complexity_layers/optimistic_concurrency_patient_version_increments_on_mutation
    """
    patient = create_patient()
    assert patient["version"] == 1
    prescriber = create_prescriber()
    product = create_product()
    create_prescription(patient, prescriber, product)
    after = validate_success(api.get_patient(patient["id"], ADMIN))
    assert after["version"] == 2


def test_lot_posture_recomputed_on_aer_close(api):
    """PRD §3.11: "A substantiated closure moves the report to
    `CLOSED_SUBSTANTIATED` and increments the parent lot's `complaint_count` by
    one, then recomputes the lot's `complaint_posture` per the threshold rule"
    PRD §3.2: "below three, the posture is `NORMAL`."

    Design: Corner/cross_cutting_complexity_layers/derived_field_reconciliation_lot_posture_recomputed_on_aer_close
    """
    from test_helpers import file_and_close_aer

    patient = create_patient()
    product = create_product()
    lot = create_lot(product)
    units = create_units(lot, 1)
    before = validate_success(api.get_sensor_lot(lot["id"], ADMIN))
    assert before["complaint_count"] == 0
    assert before["complaint_posture"] == "NORMAL"
    file_and_close_aer(lot, units[0], patient["id"], outcome="SUBSTANTIATED",
                       severity="MEDIUM", event_type="OTHER")
    after = validate_success(api.get_sensor_lot(lot["id"], ADMIN))
    assert after["complaint_count"] == 1
    assert after["complaint_posture"] == "NORMAL"


def test_prescription_cancel_cascades_to_pending_orders(api):
    """PRD §3.3: "Cancelling a prescription cascades: any `PENDING_PICK`
    sensor order against it auto-transitions to `CANCELLED`."

    Design: Corner/cross_cutting_complexity_layers/cascading_side_effects_prescription_cancel_cascade_to_pending_orders
    """
    ctx = setup_supply_pipeline()
    order = create_order(ctx["patient"], ctx["prescription"], ctx["verification"], ctx["lot"])
    cancelled_rx = validate_success(
        api.cancel_prescription(
            ctx["prescription"]["id"], make_prescriber_headers(ctx["prescriber"]["id"])
        )
    )
    assert cancelled_rx["status"] == "CANCELLED"
    order_after = validate_success(api.get_sensor_order(order["id"], ADMIN))
    assert order_after["fulfillment_status"] == "CANCELLED"


def test_immediate_consistency_post_then_get_reflects_change(api):
    """PRD §2.4: "Every primary resource in the system carries a standard set
    of system-managed fields."
    PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."

    A write is visible in the immediately-following GET under the same logical
    clock.

    Design: Corner/consistency_model/immediate_consistency_post_then_get_reflects_change
    """
    created = create_patient(full_name="CM1")
    fetched = validate_success(api.get_patient(created["id"], ADMIN))
    assert fetched["id"] == created["id"]
    assert fetched["full_name"] == "CM1"
