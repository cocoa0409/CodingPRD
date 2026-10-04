"""Recycling obligations: recovery requirement math, the exactly-1.0
fulfillment boundary, zero-baseline settlement, and settle gating."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_customer,
    open_obligation,
    validate_error,
    validate_paginated,
    validate_success,
)

RC = TEST_USERS["recycling_coordinator_headers"]


def _get_obligation(api, customer_id, obligation_id):
    """Obligations are read back via the customer's sub-resource listing."""
    resp = api.list_customer_recycling_obligations(customer_id, RC)
    data, _meta = validate_paginated(resp)
    for row in data:
        if row["id"] == obligation_id:
            return row
    raise AssertionError(f"obligation {obligation_id} not found in listing")


class TestRecoveryExactFullFulfillment:
    """required = shipped * 0.90 (4dp); RECOVERED fires at fulfillment >= 1.0,
    and exactly 1.0 qualifies."""

    def test_exact_full_fulfillment_recovers(self, api):
        """PRD §3.9: "The obligation's `required_collected_mw` is computed
        immediately: the shipped volume multiplied by a minimum recovery
        percentage of 0.90, at 4 decimal places rounded half up."
        PRD §3.9: "The first event with a volume greater than zero moves the
        obligation `OPEN → COLLECTING`, and each further event accumulates:
        `collected_volume_mw` grows by the event's volume and `fulfillment_pct`
        is recomputed as the collected volume divided by the required volume (or
        exactly 1.0 when the required volume is zero). When an event brings
        `fulfillment_pct` to at least 1.0 — and exactly 1.0 qualifies — the
        obligation transitions automatically `COLLECTING → RECOVERED`."

        Design: Difficulty/boundary_precision_check/recovery_exact_full_fulfillment
        """
        customer = create_customer()
        obligation = open_obligation(customer, shipped_volume_mw=100.0)
        assert obligation["required_collected_mw"] == pytest.approx(90.0000, abs=1e-6)
        assert obligation["status"] == "OPEN"

        first = validate_success(
            api.record_collection(obligation["id"], {"volume_mw": 45.0}, RC), 201
        )
        assert first["status"] == "COLLECTING"
        assert first["fulfillment_pct"] == pytest.approx(0.5000, abs=1e-6)

        second = validate_success(
            api.record_collection(obligation["id"], {"volume_mw": 45.0}, RC), 201
        )
        assert second["collected_volume_mw"] == pytest.approx(90.0000, abs=1e-6)
        assert second["fulfillment_pct"] == pytest.approx(1.0000, abs=1e-6)
        assert second["status"] == "RECOVERED", (
            "exactly 1.0 qualifies for the automatic RECOVERED transition"
        )

    def test_below_full_fulfillment_stays_collecting(self, api):
        """PRD §3.9: "The first event with a volume greater than zero moves the
        obligation `OPEN → COLLECTING`, and each further event accumulates:
        `collected_volume_mw` grows by the event's volume and `fulfillment_pct`
        is recomputed as the collected volume divided by the required volume (or
        exactly 1.0 when the required volume is zero). When an event brings
        `fulfillment_pct` to at least 1.0 — and exactly 1.0 qualifies — the
        obligation transitions automatically `COLLECTING → RECOVERED`."

        Design: Difficulty/boundary_precision_check/recovery_exact_full_fulfillment
        """
        customer = create_customer()
        obligation = open_obligation(customer, shipped_volume_mw=100.0)

        validate_success(
            api.record_collection(obligation["id"], {"volume_mw": 45.0}, RC), 201
        )
        second = validate_success(
            api.record_collection(obligation["id"], {"volume_mw": 44.0}, RC), 201
        )
        # 89.0 / 90.0000 == 0.988888... -> 0.9889 (4dp) < 1.0: no transition.
        assert second["collected_volume_mw"] == pytest.approx(89.0, abs=1e-6)
        assert second["fulfillment_pct"] == pytest.approx(0.9889, abs=1e-6)
        assert second["status"] == "COLLECTING"


def test_recovery_zero_baseline_settles_from_open(api):
    """PRD §3.9: "Settlement directly from `OPEN` is permitted only for a
    zero-shipment baseline, where `required_collected_mw` is zero and
    `fulfillment_pct` is 1.0 by definition."
    PRD §3.9: "The obligation's `required_collected_mw` is computed immediately:
    the shipped volume multiplied by a minimum recovery percentage of 0.90, at 4
    decimal places rounded half up."

    Design: Corner/calculations/recovery_zero_baseline_settles_from_open
    """
    customer = create_customer()
    obligation = open_obligation(customer, shipped_volume_mw=0.0)
    assert obligation["required_collected_mw"] == pytest.approx(0.0, abs=1e-9)
    assert obligation["fulfillment_pct"] == pytest.approx(1.0, abs=1e-9)
    assert obligation["status"] == "OPEN"

    resp = api.settle_obligation(obligation["id"], RC)
    data = validate_success(resp, 200)
    assert data["status"] == "SETTLED"


def test_settle_open_nonzero_obligation_rejected(api):
    """PRD §3.9: "Any other settle attempt — from `COLLECTING` before recovery,
    or from `OPEN` with a nonzero requirement — is rejected with
    `ERR_OBLIGATION_NOT_MET` (HTTP 422)."

    Design: Corner/validations/settle_open_nonzero_obligation_rejected
    """
    customer = create_customer()
    obligation = open_obligation(customer, shipped_volume_mw=100.0)
    assert obligation["required_collected_mw"] == pytest.approx(90.0000, abs=1e-6)

    resp = api.settle_obligation(obligation["id"], RC)
    validate_error(resp, ApiErrorId.ERR_OBLIGATION_NOT_MET)
    after = _get_obligation(api, customer["id"], obligation["id"])
    assert after["status"] == "OPEN"


def test_fk_reverse_obligations_by_customer(api):
    """PRD §4: "Recycling obligations of a customer"
    PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."

    Design: Corner/endpoints/fk_reverse_obligations_by_customer
    """
    customer = create_customer()
    obligation = open_obligation(customer, shipped_volume_mw=100.0)

    resp = api.list_customer_recycling_obligations(customer["id"], RC)
    data, _meta = validate_paginated(resp)
    assert len(data) == 1, f"expected exactly 1 obligation, got {len(data)}"
    assert data[0]["id"] == obligation["id"]
