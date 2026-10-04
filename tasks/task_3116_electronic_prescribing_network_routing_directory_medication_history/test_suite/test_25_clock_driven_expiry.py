"""Corner coverage: the logical clock moving a consent past the exclusive upper bound of its
validity window.
"""
from test_helpers import (
    validate_error,
    set_clock,
    advance_logical_clock,
    setup_certified_pharmacy,
    create_patient,
    grant_consent,
    add_history_record,
    open_history_batch,
    reload_batch,
    reload_history_record,
    reload_endpoint,
    reload_participant,
    TEST_USERS,
    api_client,
)

HUB = TEST_USERS["hub_operator_headers"]
OPERATOR = TEST_USERS["network_operator_headers"]


def test_advancing_the_clock_past_the_window_closes_the_consent(api):
    """PRD §3.8: "The new consent's `status` is written `ACTIVE` when `expires_at` is later
    than the current logical clock and `EXPIRED` otherwise"
    PRD §2.10: "Because every temporal rule reads this one clock, a test that advances the
    clock can deliberately move an endpoint out of its service window or a consent past its
    expiry without touching stored records."

    Design: Corner/cross_cutting_layers/consent_window_elapse_blocks_aggregation_after_clock_advance
    """
    set_clock()
    pharmacy, _ = setup_certified_pharmacy(
        endpoint_specs=[{"service_set": "MED_HISTORY", "endpoint_role": "RECEIVER",
                         "service_level": "ELIGIBLE_A", "sla_response_minutes": 60,
                         "message_standard": "NCPDP_SCRIPT_2022011"}]
    )
    patient = create_patient()
    consent = grant_consent(patient["id"], scope="MEDICATION_HISTORY", duration_days=30)
    assert consent["status"] == "ACTIVE"
    record = add_history_record(
        patient["id"], pharmacy["id"], drug_ndc="00093314905",
        fill_date="2026-06-01T00:00:00Z", days_supply=30, quantity=60,
    )

    # 30 days after 2026-09-01T00:00:00Z is exactly the window's exclusive upper bound.
    clock = advance_logical_clock(43200)
    assert clock["current_utc"] == "2026-10-01T00:00:00Z"
    assert consent["expires_at"] == "2026-10-01T00:00:00Z"

    batch = open_history_batch(patient["id"], pharmacy["id"])
    response = api_client.aggregate_history_batch(batch["id"], HUB)
    validate_error(response, "ERR_CONSENT_REQUIRED", expected_status=422)

    assert reload_batch(batch["id"])["status"] == "PENDING"
    assert reload_history_record(record["id"])["aggregation_batch_id"] is None


def test_the_advanced_clock_leaves_untouched_records_and_other_windows_alone(api):
    """PRD §2.10: "Neither capability changes any business state; they move the clock and
    nothing else, and neither is part of the public business surface."
    PRD §2.4: "The count of reachable endpoints is the number of that participant's endpoints
    whose `status` is `ACTIVE` or `DEGRADED` and whose half-open service interval
    `[effective_from, effective_to)` contains the current logical clock"

    Design: Corner/cross_cutting_layers/consent_window_elapse_blocks_aggregation_after_clock_advance
    """
    set_clock()
    pharmacy, endpoints = setup_certified_pharmacy(
        endpoint_specs=[{"service_set": "MED_HISTORY", "endpoint_role": "RECEIVER",
                         "service_level": "ELIGIBLE_A", "sla_response_minutes": 60,
                         "message_standard": "NCPDP_SCRIPT_2022011"}]
    )
    patient = create_patient()
    grant_consent(patient["id"], scope="MEDICATION_HISTORY", duration_days=30)
    record = add_history_record(
        patient["id"], pharmacy["id"], drug_ndc="00093314905",
        fill_date="2026-06-01T00:00:00Z", days_supply=30, quantity=60,
    )
    batch = open_history_batch(patient["id"], pharmacy["id"])

    advance_logical_clock(43200)

    # The endpoint's own service interval still contains the advanced instant, so its derived
    # reachability is unaffected by the clock move.
    assert reload_endpoint(endpoints[0]["id"])["status"] == "ACTIVE"
    assert reload_participant(pharmacy["id"])["delivery_reachability"] == "FULL"

    # Nothing stamped the record.
    stamped = reload_history_record(record["id"])
    assert stamped["is_superseded"] is False
    assert stamped["aggregation_batch_id"] is None
    assert reload_batch(batch["id"])["batch_cost_cents"] == 0