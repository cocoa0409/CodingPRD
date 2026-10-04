"""Laboratory processing: accessioning, stabilization window boundaries,
adequacy determinations, and the recollection cycle."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    get_kit,
    get_order,
    get_specimen,
    set_clock,
    setup_in_lab,
    setup_inadequate_round,
    setup_kit_ordered,
    setup_processing,
    setup_replacement_kit,
    setup_round_exhausted_in_lab,
    setup_second_in_lab,
    validate_error,
    validate_paginated,
    validate_success,
)

PA = TEST_USERS["program_admin_headers"]
FA = TEST_USERS["fulfillment_agent_headers"]
LT = TEST_USERS["lab_technician_headers"]


# ---------------------------------------------------------------------------
# Resulting gating on adequacy / state
# ---------------------------------------------------------------------------

def test_result_before_adequacy_rejected(api):
    """PRD §3.6: "The specimen must be in `PROCESSING` (else
    `ERR_SPECIMEN_INVALID_STATE`) and its `adequacy` must be `ADEQUATE` —
    resulting on a specimen whose adequacy is anything else is rejected with
    `ERR_SPECIMEN_NOT_ADEQUATE` (HTTP 422)."

    Design: Corner/validations/result_before_adequacy_rejected
    """
    ctx = setup_processing()  # PROCESSING with adequacy still PENDING
    resp = api.result_specimen(ctx["specimen"]["id"], {"outcome": "NEGATIVE"}, LT)
    validate_error(resp, ApiErrorId.ERR_SPECIMEN_NOT_ADEQUATE)


def test_specimen_invalid_state_on_process_after_inadequate(api):
    """PRD §3.5: "A `LabTechnician` starting processing on a specimen requires
    the specimen to be in `ACCESSIONED` status (else
    `ERR_SPECIMEN_INVALID_STATE`)".

    Design: Corner/errors/specimen_invalid_state_on_process
    """
    ctx = setup_inadequate_round()  # specimen is now terminal INADEQUATE
    resp = api.process_specimen(ctx["specimen"]["id"], LT)
    validate_error(resp, ApiErrorId.ERR_SPECIMEN_INVALID_STATE)


# ---------------------------------------------------------------------------
# Recollection cycle (queue A non_linear_state_machine)
# ---------------------------------------------------------------------------

def test_recollection_cycle_second_pass_through_in_lab(api):
    """PRD §3.5: "the specimen's `adequacy` becomes `INADEQUATE` with
    `adequacy_checked_at` stamped, the specimen moves to `INADEQUATE`, the
    kit is consumed — moving to `CONSUMED`, with the order's `active_kit_id`
    cleared — the order's `recollection_round` increments by one, the order
    transitions `IN_LAB → RECOLLECTION_REQUESTED`, and the order's `version`
    increments."
    PRD §3.5: "the order must be in `RECOLLECTION_REQUESTED` (else
    `ERR_ORDER_INVALID_STATE`), the request carries `expected_order_version`
    per §2.7, and on success a fresh `ScreeningKit` is created in `ORDERED`,
    the order's `active_kit_id` is set to it".

    Design: Difficulty/non_linear_state_machine/order_recollection_cycle
    """
    ctx = setup_second_in_lab()
    order = get_order(ctx["order"]["id"])
    assert order["status"] == "IN_LAB"
    assert order["recollection_round"] == 1
    assert get_kit(ctx["first_kit"]["id"])["status"] == "CONSUMED"
    assert get_kit(ctx["kit"]["id"])["status"] == "RETURNED"
    assert order["active_kit_id"] == ctx["kit"]["id"]


def test_recollection_round_counter_distinguishes_first_loop(api):
    """PRD §3.5: "the order's `recollection_round` increments by one, the
    order transitions `IN_LAB → RECOLLECTION_REQUESTED`, and the order's
    `version` increments."

    Design: Difficulty/non_linear_state_machine/order_recollection_cycle
    """
    ctx = setup_inadequate_round()
    order = get_order(ctx["order"]["id"])
    assert order["status"] == "RECOLLECTION_REQUESTED"
    assert order["recollection_round"] == 1
    assert get_specimen(ctx["specimen"]["id"])["status"] == "INADEQUATE"


def test_recollection_limit_exhausted(api):
    """PRD §3.5: "the order's `recollection_round` must be below the maximum
    of 2 completed recollection cycles — at the limit the request fails with
    `ERR_RECOLLECTION_LIMIT_REACHED` (HTTP 422) and nothing else changes."

    Design: Corner/validations/recollection_limit_exhausted
    """
    ctx = setup_round_exhausted_in_lab()
    assert ctx["order"]["recollection_round"] == 2

    resp = api.record_adequacy(ctx["specimen"]["id"], {"adequacy": "INADEQUATE"}, LT)
    validate_error(resp, ApiErrorId.ERR_RECOLLECTION_LIMIT_REACHED)

    order = get_order(ctx["order"]["id"])
    assert order["recollection_round"] == 2
    assert order["status"] == "IN_LAB"


# ---------------------------------------------------------------------------
# Single-active-kit invariant (queue A compensating_invariant)
# ---------------------------------------------------------------------------

def test_recollection_round_trip_conserves_single_active_kit(api):
    """PRD §3.5: "the kit is consumed — moving to `CONSUMED`, with the
    order's `active_kit_id` cleared".
    PRD §3.5: "on success a fresh `ScreeningKit` is created in `ORDERED`,
    the order's `active_kit_id` is set to it".

    Design: Difficulty/compensating_invariant/recollection_round_trip_conserves_single_active_kit
    """
    ctx = setup_replacement_kit()
    kits, _ = validate_paginated(api.list_order_kits(ctx["order"]["id"], PA))
    non_terminal = [k for k in kits if k["status"] in ("ORDERED", "SHIPPED", "RETURNED", "IN_PROCESSING")]
    assert len(kits) == 2
    assert len(non_terminal) == 1
    assert non_terminal[0]["id"] == ctx["kit"]["id"]
    assert non_terminal[0]["status"] == "ORDERED"
    assert get_kit(ctx["first_kit"]["id"])["status"] == "CONSUMED"


def test_recollection_replacement_kit_becomes_active_kit(api):
    """PRD §3.5: "on success a fresh `ScreeningKit` is created in `ORDERED`,
    the order's `active_kit_id` is set to it, any `abandonment_due_at` left
    over from the prior shipment is cleared (it is recomputed when the
    replacement ships), the order moves `RECOLLECTION_REQUESTED →
    KIT_ORDERED`, and its `version` increments."

    Design: Difficulty/compensating_invariant/recollection_round_trip_conserves_single_active_kit
    """
    ctx = setup_replacement_kit()
    order = get_order(ctx["order"]["id"])
    assert order["status"] == "KIT_ORDERED"
    assert order["active_kit_id"] == ctx["kit"]["id"]
    assert order.get("abandonment_due_at") is None
    assert order["recollection_round"] == 1


# ---------------------------------------------------------------------------
# Stabilization window boundaries (queue A boundary + resource_temporal)
# ---------------------------------------------------------------------------

def test_stabilization_exact_expiry_rejected(api):
    """PRD §3.5: "requires the logical clock's current instant to be strictly
    before the kit's `stabilization_expires_at` — a start exactly at the
    expiry instant is too late and is rejected, along with any later start,
    with `ERR_STABILIZATION_EXPIRED` (HTTP 422)."
    PRD §3.4: "its `stabilization_expires_at` is computed as exactly 72 hours
    after `returned_at`".

    Design: Difficulty/boundary_precision_check/stabilization_strict_less_than_at_exact_expiry
    """
    set_clock()
    ctx = setup_in_lab()  # returned 2026-09-01T00:00:00Z -> expiry 2026-09-04T00:00:00Z
    set_clock("2026-09-04T00:00:00Z")  # exactly at expiry
    resp = api.process_specimen(ctx["specimen"]["id"], LT)
    validate_error(resp, ApiErrorId.ERR_STABILIZATION_EXPIRED)


def test_stabilization_one_second_before_expiry_accepted(api):
    """PRD §3.5: "requires the logical clock's current instant to be strictly
    before the kit's `stabilization_expires_at` — a start exactly at the
    expiry instant is too late and is rejected, along with any later start,
    with `ERR_STABILIZATION_EXPIRED` (HTTP 422). On success the specimen
    moves `ACCESSIONED → PROCESSING` with `processing_started_at` stamped,
    and the kit moves `RETURNED → IN_PROCESSING`."

    Design: Difficulty/boundary_precision_check/stabilization_strict_less_than_at_exact_expiry
    """
    set_clock()
    ctx = setup_in_lab()
    set_clock("2026-09-03T23:59:59Z")  # one second before expiry
    specimen = validate_success(api.process_specimen(ctx["specimen"]["id"], LT))
    assert specimen["status"] == "PROCESSING"
    assert get_kit(ctx["kit"]["id"])["status"] == "IN_PROCESSING"


def test_stabilization_half_open_interval_point_acceptance(api):
    """PRD §3.4: "its `stabilization_expires_at` is computed as exactly 72
    hours after `returned_at`".
    PRD §3.5: "requires the logical clock's current instant to be strictly
    before the kit's `stabilization_expires_at` — a start exactly at the
    expiry instant is too late and is rejected, along with any later start,
    with `ERR_STABILIZATION_EXPIRED` (HTTP 422)."

    Design: Difficulty/resource_temporal_overlap/stabilization_window_point_in_interval
    """
    set_clock()
    ctx = setup_kit_ordered(patient_overrides={"external_ref": "p-ovl-2"})
    set_clock("2026-09-01T12:00:00Z")
    # Return stamped at noon: expiry is 2026-09-04T12:00:00Z.
    validate_success(api.ship_kit(ctx["kit"]["id"], FA))
    returned = validate_success(api.return_kit(ctx["kit"]["id"], FA))
    assert str(returned["stabilization_expires_at"]).replace("+00:00", "Z")[:19] == "2026-09-04T12:00:00"
    specimen = validate_success(api.accession_specimen(ctx["order"]["id"], LT), expected_status=201)

    set_clock("2026-09-04T11:59:59Z")  # one second before the half-open end
    processed = validate_success(api.process_specimen(specimen["id"], LT))
    assert processed["status"] == "PROCESSING"


def test_stabilization_half_open_interval_end_rejected(api):
    """PRD §3.4: "its `stabilization_expires_at` is computed as exactly 72
    hours after `returned_at`".
    PRD §3.5: "a start exactly at the expiry instant is too late and is
    rejected, along with any later start, with `ERR_STABILIZATION_EXPIRED`
    (HTTP 422)."

    Design: Difficulty/resource_temporal_overlap/stabilization_window_point_in_interval
    """
    set_clock()
    ctx = setup_kit_ordered()
    set_clock("2026-09-01T12:00:00Z")
    validate_success(api.ship_kit(ctx["kit"]["id"], FA))
    returned = validate_success(api.return_kit(ctx["kit"]["id"], FA))
    assert str(returned["stabilization_expires_at"]).replace("+00:00", "Z")[:19] == "2026-09-04T12:00:00"
    specimen = validate_success(api.accession_specimen(ctx["order"]["id"], LT), expected_status=201)

    set_clock("2026-09-04T12:00:00Z")  # exactly the half-open end
    resp = api.process_specimen(specimen["id"], LT)
    validate_error(resp, ApiErrorId.ERR_STABILIZATION_EXPIRED)


# ---------------------------------------------------------------------------
# Priority pair: temporal vs constraint (queue A)
# ---------------------------------------------------------------------------

def test_stabilization_expired_reported_on_process(api):
    """PRD §3.5: "requires the logical clock's current instant to be strictly
    before the kit's `stabilization_expires_at` — a start exactly at the
    expiry instant is too late and is rejected, along with any later start,
    with `ERR_STABILIZATION_EXPIRED` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/business_temporal_vs_business_constraint_on_process
    """
    set_clock()
    ctx = setup_second_in_lab()  # second specimen ACCESSIONED, round == 1
    set_clock("2026-09-05T00:01:00Z")  # past returned_at + 72h
    resp = api.process_specimen(ctx["specimen"]["id"], LT)
    validate_error(resp, ApiErrorId.ERR_STABILIZATION_EXPIRED)


def test_stabilization_expired_is_422_and_preserves_specimen(api):
    """PRD §3.5: "a start exactly at the expiry instant is too late and is
    rejected, along with any later start, with `ERR_STABILIZATION_EXPIRED`
    (HTTP 422). On success the specimen moves `ACCESSIONED → PROCESSING` with
    `processing_started_at` stamped, and the kit moves `RETURNED →
    IN_PROCESSING`."

    Design: Difficulty/priority_pair_validation_conflict/business_temporal_vs_business_constraint_on_process
    """
    set_clock()
    ctx = setup_second_in_lab()
    set_clock("2026-09-05T00:01:00Z")
    resp = api.process_specimen(ctx["specimen"]["id"], LT)
    assert resp.status_code == 422
    specimen = get_specimen(ctx["specimen"]["id"])
    assert specimen["status"] == "ACCESSIONED"
    assert get_kit(ctx["kit"]["id"])["status"] == "RETURNED"
