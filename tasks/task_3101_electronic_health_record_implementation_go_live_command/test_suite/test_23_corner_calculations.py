"""Aggregate calculations: revenue-cycle recovery and epoch-scoped test cycles."""

import pytest

from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    get_facility,
    create_patient_order_payload,
    setup_program_and_facility,
    setup_epoch_scoped_build_item,
    DIRECTOR,
    CONVERSION,
    RECONCILER,
    REVENUE,
    TEST_LEAD,
    ANALYST,
)


# ===========================================================================
# c_revenue_cycle_index_tracks_denial_and_recovery
# ===========================================================================

def test_a_denied_claim_pins_the_stabilization_index_at_sixty(api, conversion_headers, revenue_headers, reconciler_headers, analyst_headers):
    """PRD §3.8: "The `revenue_cycle_stabilization_index` is a weighted blend of
    two factors, computed over the facility's orders whose clinical state is
    `CONVERTED` or `RECONCILED`."
    PRD §3.8: "The second factor is a blunt denial penalty: it is 0 if any order
    of the facility is in `CLAIM_DENIED` and 100 otherwise."
    PRD §3.8: "A facility holding a single denied claim therefore cannot exceed
    60.00 however fresh its other receivables are".

    The encounter is three days behind the clock, so the receivables factor is
    100 and the blend is 0.60 * 100 + 0.40 * 0 = 60.00.

    Design: Corner/calculations/c_revenue_cycle_index_tracks_denial_and_recovery
    """
    prog, fac = setup_program_and_facility()
    order = get_success_data(api_client.create_patient_order(
        fac["id"],
        create_patient_order_payload(
            patient_mrn="MRN-8100", order_type="LAB",
            encounter_utc="2026-08-29T00:00:00Z", legacy_charge_cents=10000,
        ),
        conversion_headers,
    ))
    get_success_data(api_client.reconcile_order(order["id"], reconciler_headers))
    get_success_data(api_client.post_charge(order["id"], revenue_headers))
    get_success_data(api_client.submit_claim(order["id"], revenue_headers))

    denied = validate_success(
        api_client.record_claim_response(order["id"], {"claim_response": "DENIED"}, revenue_headers), 200
    )
    assert denied["billing_state"] == "CLAIM_DENIED"

    facility = get_facility(fac["id"], analyst_headers)
    assert facility["revenue_cycle_stabilization_index"] == pytest.approx(60.00, abs=0.01), (
        f"0.60 * 100 (fresh receivable) + 0.40 * 0 (denial present) = 60.00; "
        f"got {facility['revenue_cycle_stabilization_index']}"
    )


def test_reopening_the_claim_restores_the_stabilization_index(api, conversion_headers, revenue_headers, reconciler_headers, analyst_headers):
    """PRD §3.8: "A denied claim is not a dead end: it may be reopened for
    correction, which returns the order to `CHARGE_POSTED` so the charge can be
    corrected and resubmitted."
    PRD §3.8: "The facility returns to `LIVE` on its own as soon as no order of it
    remains in `CLAIM_DENIED`."

    Design: Corner/calculations/c_revenue_cycle_index_tracks_denial_and_recovery
    """
    prog, fac = setup_program_and_facility()
    order = get_success_data(api_client.create_patient_order(
        fac["id"],
        create_patient_order_payload(
            patient_mrn="MRN-8100", order_type="LAB",
            encounter_utc="2026-08-29T00:00:00Z", legacy_charge_cents=10000,
        ),
        conversion_headers,
    ))
    get_success_data(api_client.reconcile_order(order["id"], reconciler_headers))
    get_success_data(api_client.post_charge(order["id"], revenue_headers))
    get_success_data(api_client.submit_claim(order["id"], revenue_headers))
    get_success_data(api_client.record_claim_response(
        order["id"], {"claim_response": "DENIED"}, revenue_headers
    ))

    reopened = validate_success(api_client.reopen_claim(order["id"], revenue_headers), 200)
    assert reopened["billing_state"] == "CHARGE_POSTED"

    facility = get_facility(fac["id"], analyst_headers)
    assert facility["revenue_cycle_stabilization_index"] == pytest.approx(100.00, abs=0.01), (
        "with the denial cleared both factors are 100, so the index returns to 100.00"
    )


# ===========================================================================
# c_test_cycle_count_filters_to_current_epoch
# ===========================================================================

def test_a_pass_recorded_in_epoch_zero_counts_while_the_program_is_at_epoch_zero(api, director_headers, test_lead_headers):
    """PRD §3.3: "Testing is measured through `test_cycles_passed`, the count of
    scenarios in the item's current epoch that have reached `PASSED`".
    PRD §3.5: "A passing outcome moves the scenario to `PASSED`, records the epoch
    and refreshes the build item's `test_cycles_passed`".

    Design: Corner/calculations/c_test_cycle_count_filters_to_current_epoch
    """
    ctx = setup_epoch_scoped_build_item()
    get_success_data(api_client.execute_scenario(
        ctx["scenario"]["id"], {"outcome": "PASS", "executed_epoch": 0}, test_lead_headers
    ))

    item = validate_success(api_client.get_build_item(ctx["item"]["id"], test_lead_headers), 200)
    assert item["test_cycles_passed"] == 1


def test_advancing_the_epoch_drops_the_ephemeral_pass_from_the_count(api, director_headers, test_lead_headers):
    """PRD §2.6: "a test scenario records the `executed_epoch` in which it last
    ran"; PRD §2.6: "Advancing the epoch triggers a program-wide sweep:
    `test_cycles_passed` is recomputed for every system build item of the
    program".
    PRD §3.3: "Testing is measured through `test_cycles_passed`, the count of
    scenarios in the item's current epoch that have reached `PASSED`".

    The scenario stays PASSED and keeps its recorded epoch, but it no longer
    belongs to the current epoch, so the count drops to zero.

    Design: Corner/calculations/c_test_cycle_count_filters_to_current_epoch
    """
    ctx = setup_epoch_scoped_build_item()
    get_success_data(api_client.execute_scenario(
        ctx["scenario"]["id"], {"outcome": "PASS", "executed_epoch": 0}, test_lead_headers
    ))

    advanced = validate_success(api_client.advance_epoch(ctx["prog"]["id"], director_headers), 200)
    assert advanced["current_epoch_index"] == 1

    item = validate_success(api_client.get_build_item(ctx["item"]["id"], test_lead_headers), 200)
    assert item["test_cycles_passed"] == 0, "the epoch-0 pass no longer counts"

    scenario = validate_success(api_client.get_test_scenario(ctx["scenario"]["id"], test_lead_headers), 200)
    assert scenario["status"] == "PASSED"
    assert scenario["executed_epoch"] == 0