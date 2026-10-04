"""Wood intake: creation defaults, drying-gate boundaries, terminal lockdown."""
from test_helpers import (
    ApiErrorId,
    CLOCK_START_ISO,
    MIN_DRYING_DAYS,
    TEST_USERS,
    assert_wood_batch,
    create_wood_batch,
    create_wood_batch_payload,
    moisture_reading_payload,
    record_moisture,
    set_clock_days_after,
    validate_error,
    validate_success,
)

WM = TEST_USERS["workshop_manager_headers"]


def test_create_wood_batch_applies_system_defaults(api):
    """PRD section 3.1: "The batch enters `DRYING` at the current logical clock, and
    that moment is recorded as `drying_started_at`."
    PRD section 2.4: "a server-owned logical clock whose value at startup is exactly
    2026-09-01T00:00:00Z".
    PRD section 3.1: "its `conditioned_at` is set to the current logical clock (it is
    null until then)".

    Design: Corner/entities/create_wood_batch_applies_system_defaults
    """
    resp = api.create_wood_batch(create_wood_batch_payload("MAPLE", 14.2), WM)
    data = validate_success(resp, 201)
    assert_wood_batch(data)
    assert data["status"] == "DRYING"
    assert data["drying_started_at"] == CLOCK_START_ISO
    assert data["conditioned_at"] is None
    body = resp.json()
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"].startswith("req_")


def test_rejected_batch_terminal_lockdown(api):
    """PRD section 3.1: "`CONSUMED` and `REJECTED` are terminal — a batch in either
    state accepts no further transitions of any kind."
    PRD section 3.1: "against a `CONSUMED` or `REJECTED` batch the attempt is rejected
    with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/rejected_batch_terminal_lockdown
    """
    wb = create_wood_batch("BIRCH", 13.0)
    rejected = validate_success(api.reject_wood_batch(wb["id"], {}, WM), 200)
    assert rejected["status"] == "REJECTED"
    reading = api.record_moisture_reading(wb["id"], moisture_reading_payload(7.0), WM)
    validate_error(reading, ApiErrorId.ERR_INVALID_STATE)
    re_reject = api.reject_wood_batch(wb["id"], {}, WM)
    validate_error(re_reject, ApiErrorId.ERR_INVALID_STATE)


def test_drying_gate_day_239_insufficient(api):
    """PRD section 3.1: "at least 240 whole days have elapsed since `drying_started_at`
    — exactly 240 passes — the batch auto-transitions from `DRYING` to `CONDITIONED`".

    Design: Corner/calculations/drying_gate_day_239_insufficient
    """
    wb = create_wood_batch("MAPLE", 12.0)
    set_clock_days_after(wb["drying_started_at"], MIN_DRYING_DAYS - 1)
    data = record_moisture(wb["id"], 8.0)
    assert data["status"] == "DRYING", "day 239 must not condition even at 8.0 percent"
    assert data["conditioned_at"] is None
    assert data["moisture_content_pct"] == 8.0


def test_moisture_exactly_eight_pct_conditions_at_day_240(api):
    """PRD section 3.1: "when the new reading is at most 8.0 percent — exactly 8.0
    passes — and at least 240 whole days have elapsed since `drying_started_at` —
    exactly 240 passes — the batch auto-transitions from `DRYING` to `CONDITIONED`,
    its `conditioned_at` is set to the current logical clock".

    Design: Difficulty/boundary_precision_check/moisture_exactly_eight_pct_conditions
    """
    wb = create_wood_batch("MAPLE", 12.0)
    target = set_clock_days_after(wb["drying_started_at"], MIN_DRYING_DAYS)
    data = record_moisture(wb["id"], 8.0)
    assert data["status"] == "CONDITIONED"
    assert data["conditioned_at"] == target
    assert data["moisture_content_pct"] == 8.0


def test_moisture_above_eight_pct_stays_drying_at_day_240(api):
    """PRD section 3.1: "Each accepted reading overwrites `moisture_content_pct` and
    increments the batch's `version`."
    PRD section 3.1: the gate opens only "when the new reading is at most 8.0 percent
    — exactly 8.0 passes".

    Design: Difficulty/boundary_precision_check/moisture_exactly_eight_pct_conditions
    """
    wb = create_wood_batch("MAPLE", 11.0)
    set_clock_days_after(wb["drying_started_at"], MIN_DRYING_DAYS)
    data = record_moisture(wb["id"], 8.01)
    assert data["status"] == "DRYING", "8.01 exceeds the 8.0 gate even at day 240"
    assert data["conditioned_at"] is None
    assert data["moisture_content_pct"] == 8.01
