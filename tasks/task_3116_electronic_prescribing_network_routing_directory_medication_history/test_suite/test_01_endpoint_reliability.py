"""Directory endpoint reliability: the chronological ratio and the EWMA column.

Both columns share an input set — the endpoint's RoutingAttempt rows whose outcome is
ACKNOWLEDGED, REJECTED or UNDELIVERABLE — but differ in method, so the identical delivered
attempt history can read below and above the degradation gate at the same time.
"""
import pytest

from test_helpers import (
    set_clock,
    create_clinic,
    add_endpoint,
    certify_participant,
    setup_two_new_rx_endpoint_pharmacy,
    create_patient,
    setup_signed_prescription,
    build_attempt_history,
    reload_endpoint,
)


def _endpoint_with_two_acks_and_one_undeliverable():
    """A CERTIFIED pharmacy with two in-window NEW_RX endpoints, plus a three-attempt
    history on the first endpoint: ACKNOWLEDGED, ACKNOWLEDGED, UNDELIVERABLE."""
    set_clock()
    clinic = create_clinic()
    add_endpoint(
        clinic["id"], service_set="NEW_RX", endpoint_role="SENDER", service_level="ELIGIBLE_A",
        sla_response_minutes=15, message_standard="NCPDP_SCRIPT_2022011",
    )
    clinic = certify_participant(clinic["id"])
    pharmacy, ep_first, ep_other = setup_two_new_rx_endpoint_pharmacy()
    patient = create_patient()
    prescription, _ = setup_signed_prescription(clinic["id"], pharmacy["id"], patient["id"])
    build_attempt_history(
        prescription["id"], clinic["id"],
        ["ACKNOWLEDGED", "ACKNOWLEDGED", ("UNDELIVERABLE", "TRANSMISSION_TIMEOUT")],
    )
    return ep_first, ep_other


def test_reliability_columns_disagree_over_the_same_attempt_history(api):
    """PRD §2.6: "Its inputs are ordered by `reported_at` ascending, then `attempt_no`
    ascending, then `created_at` ascending; the window is the last 20 rows of that ordering,
    that is, the 20 rows with the greatest sort key."
    PRD §2.6: "The ratio is the number of `ACKNOWLEDGED` rows within that window divided by
    the window's length, rounded half up to four decimal places."
    PRD §2.6: "Because the seed is 1.0 and the weight is small, a short or mostly-failed
    history reads far higher here than chronologically: a single `UNDELIVERABLE` attempt
    alone yields a chronological ratio of 0.0000 against an EWMA of 0.9330."

    Design: Difficulty/dual_variant_calc/reliability_ratio_dual_variant_on_directory_endpoint
    """
    ep_first, ep_other = _endpoint_with_two_acks_and_one_undeliverable()

    endpoint = reload_endpoint(ep_first["id"])
    assert endpoint["reported_attempt_count"] == 3
    assert endpoint["acknowledged_count"] == 2
    assert endpoint["reliability_ratio"] == pytest.approx(0.6667, abs=1e-4)
    assert endpoint["reliability_ratio_ewma"] == pytest.approx(0.9330, abs=1e-4)
    assert endpoint["reliability_ratio"] != endpoint["reliability_ratio_ewma"]

    # The second endpoint carries no delivered history at all, so both columns read the
    # value they take on an empty input set.
    untouched = reload_endpoint(ep_other["id"])
    assert untouched["reported_attempt_count"] == 0
    assert untouched["reliability_ratio"] == 1.0
    assert untouched["reliability_ratio_ewma"] == 1.0


def test_chronological_ratio_below_the_degrade_gate_moves_the_endpoint_to_degraded(api):
    """PRD §2.6: "An endpoint whose chronological ratio has fallen below 0.90 is degraded by
    the reporting path, subject to the coverage invariant below."
    PRD §2.6: "The `reliability_ratio_ewma` column is the exponentially weighted variant and
    no gate reads it."

    Design: Difficulty/dual_variant_calc/reliability_ratio_dual_variant_on_directory_endpoint
    """
    ep_first, ep_other = _endpoint_with_two_acks_and_one_undeliverable()

    endpoint = reload_endpoint(ep_first["id"])
    assert endpoint["reliability_ratio"] < 0.90, (
        "the chronological variant is the one the degradation gate measures"
    )
    assert endpoint["reliability_ratio_ewma"] > 0.90, (
        "the EWMA variant stays above the gate, and no gate consumes it"
    )
    assert endpoint["status"] == "DEGRADED"

    assert reload_endpoint(ep_other["id"])["status"] == "ACTIVE"