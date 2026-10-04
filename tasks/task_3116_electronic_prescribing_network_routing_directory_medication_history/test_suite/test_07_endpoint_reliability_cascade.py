"""The chain from a reported outcome through the endpoint's reliability recompute to the
owning participant's directory rollup.

Each hop is caused by the hop before it: the report terminalises the attempt, the attempt
history drives the recomputed ratio, the ratio can move the endpoint's status, and the
status move re-derives the participant's `directory_listed`.
"""
from test_helpers import (
    set_clock,
    create_clinic,
    create_pharmacy,
    add_endpoint,
    certify_participant,
    create_patient,
    setup_signed_prescription,
    route_prescription,
    latest_attempt,
    report_undeliverable,
    report_acknowledged,
    reload_endpoint,
    reload_participant,
)


def _pharmacy_with_one_prior_failure():
    """A CERTIFIED pharmacy holding two in-window NEW_RX endpoints (ELIGIBLE_A at 15 minutes
    and ELIGIBLE_B at 30), both ACTIVE, one of which already carries a single UNDELIVERABLE
    attempt out of one reported."""
    set_clock()
    clinic = create_clinic()
    add_endpoint(
        clinic["id"], service_set="NEW_RX", endpoint_role="SENDER", service_level="ELIGIBLE_A",
        sla_response_minutes=15, message_standard="NCPDP_SCRIPT_2022011",
    )
    clinic = certify_participant(clinic["id"])

    pharmacy = create_pharmacy()
    ep_a = add_endpoint(
        pharmacy["id"], service_set="NEW_RX", endpoint_role="BOTH", service_level="ELIGIBLE_A",
        sla_response_minutes=15, message_standard="NCPDP_SCRIPT_2022011",
    )
    ep_b = add_endpoint(
        pharmacy["id"], service_set="NEW_RX", endpoint_role="BOTH", service_level="ELIGIBLE_B",
        sla_response_minutes=30, message_standard="NCPDP_SCRIPT_2022011",
    )
    pharmacy = certify_participant(pharmacy["id"])

    # One earlier order fails on the first-ranked endpoint, giving it a ratio of 0.0000.
    patient_one = create_patient(full_name="Hugo Lindqvist")
    rx_one, _ = setup_signed_prescription(clinic["id"], pharmacy["id"], patient_one["id"])
    rx_one = route_prescription(rx_one["id"], clinic["id"])
    assert rx_one["routed_endpoint_id"] == ep_a["id"]
    report_undeliverable(latest_attempt(rx_one["id"])["id"], "CF_0000")

    return clinic, pharmacy, ep_a, ep_b


def test_sign_and_acknowledged_report_recompute_the_endpoint_history(api):
    """PRD §2.11: "Stamping an attempt terminal is the first hop, and it forces the second:
    the target endpoint's `reported_attempt_count`, `acknowledged_count`, and both
    `reliability_ratio` columns are recomputed from its reported history."

    Design: Difficulty/transitive_cascade/acknowledged_attempt_cascade_reaches_endpoint_degradation
    """
    clinic, pharmacy, ep_a, ep_b = _pharmacy_with_one_prior_failure()

    after_failure = reload_endpoint(ep_a["id"])
    assert after_failure["reported_attempt_count"] == 1
    assert after_failure["acknowledged_count"] == 0
    assert after_failure["reliability_ratio"] == 0.0

    patient_two = create_patient(full_name="Sena Okafor")
    rx_two, _ = setup_signed_prescription(clinic["id"], pharmacy["id"], patient_two["id"])
    rx_two = route_prescription(rx_two["id"], clinic["id"])
    assert rx_two["routing_attempt_count"] == 1

    attempt_two = latest_attempt(rx_two["id"])
    report_acknowledged(attempt_two["id"])

    # The second-ranked endpoint took this order, so its own history advanced to one
    # reported attempt, all acknowledged.
    endpoint_b = reload_endpoint(ep_b["id"])
    assert endpoint_b["reported_attempt_count"] == 1
    assert endpoint_b["acknowledged_count"] == 1
    assert endpoint_b["reliability_ratio"] == 1.0

    # The first endpoint's history was untouched by this order.
    endpoint_a = reload_endpoint(ep_a["id"])
    assert endpoint_a["reported_attempt_count"] == 1
    assert endpoint_a["reliability_ratio"] == 0.0


def test_recomputed_ratio_moves_the_endpoint_and_rolls_up_to_the_participant(api):
    """PRD §2.11: "That recompute can itself move the endpoint's status, either upward from
    `DEGRADED` or downward from `ACTIVE` subject to the coverage invariant."
    PRD §2.11: "The status move is the third hop, and it forces the fourth: the owning
    participant's `directory_listed` is recomputed."
    PRD §2.4: "A participant is `directory_listed` when, and only when, its
    `certification_status` is `CERTIFIED` and it holds at least one `DirectoryEndpoint` whose
    `status` is either `ACTIVE` or `DEGRADED`."

    Design: Difficulty/transitive_cascade/acknowledged_attempt_cascade_reaches_endpoint_degradation
    """
    clinic, pharmacy, ep_a, ep_b = _pharmacy_with_one_prior_failure()

    # The single failed attempt recomputed a chronological ratio of 0.0000, below the 0.90
    # degrade gate; the degrade is permitted because one of the two endpoints stays ACTIVE.
    assert reload_endpoint(ep_a["id"])["status"] == "DEGRADED"
    assert reload_endpoint(ep_b["id"])["status"] == "ACTIVE"

    patient_two = create_patient(full_name="Sena Okafor")
    rx_two, _ = setup_signed_prescription(clinic["id"], pharmacy["id"], patient_two["id"])
    rx_two = route_prescription(rx_two["id"], clinic["id"])
    # ACTIVE ranks before DEGRADED, so the healthy endpoint takes the order.
    assert rx_two["routed_endpoint_id"] == ep_b["id"]

    report_acknowledged(latest_attempt(rx_two["id"])["id"])

    assert reload_endpoint(ep_b["id"])["status"] == "ACTIVE"
    assert reload_endpoint(ep_a["id"])["status"] == "DEGRADED"

    participant = reload_participant(pharmacy["id"])
    assert participant["certification_status"] == "CERTIFIED"
    assert participant["directory_listed"] is True
    assert participant["delivery_reachability"] == "FULL"