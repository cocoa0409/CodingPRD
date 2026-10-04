"""Resource temporal-overlap rules.

Directory endpoints and patient consents both carry validity intervals, but the two rules
differ: endpoint service intervals are half-open and compared against the logical clock, while
consent windows are duration-closed and compared against their stored expiry.
"""
from test_helpers import (
    validate_success,
    validate_error,
    set_clock,
    create_pharmacy,
    add_endpoint,
    create_patient,
    grant_consent,
    reload_patient,
    make_participant_admin_headers,
    TEST_USERS,
    api_client,
)

PATIENT_SERVICE = TEST_USERS["patient_service_headers"]


def test_adjacent_endpoint_intervals_are_accepted_and_overlapping_ones_are_refused(api):
    """PRD §2.6: "Two endpoints of the same participant that share a `service_set`, an
    `endpoint_role`, and a `message_standard` may not hold overlapping intervals; a
    registration that would overlap is refused with `ERR_ENDPOINT_INTERVAL_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/directory_endpoint_service_interval_overlap_half_open
    """
    set_clock()
    pharmacy = create_pharmacy()
    headers = make_participant_admin_headers(pharmacy["id"])
    add_endpoint(
        pharmacy["id"], service_set="NEW_RX", endpoint_role="BOTH", service_level="ELIGIBLE_A",
        sla_response_minutes=15, message_standard="NCPDP_SCRIPT_2022011",
        effective_from="2026-01-01T00:00:00Z", effective_to="2026-07-01T00:00:00Z",
    )

    overlapping = api_client.create_endpoint(
        pharmacy["id"],
        {"service_set": "NEW_RX", "endpoint_role": "BOTH", "service_level": "ELIGIBLE_A",
         "sla_response_minutes": 20, "message_standard": "NCPDP_SCRIPT_2022011",
         "effective_from": "2026-06-30T23:59:00Z",
         "effective_to": "2027-01-01T00:00:00Z"},
        headers,
    )
    validate_error(overlapping, "ERR_ENDPOINT_INTERVAL_OVERLAP", expected_status=422)

    adjacent = api_client.create_endpoint(
        pharmacy["id"],
        {"service_set": "NEW_RX", "endpoint_role": "BOTH", "service_level": "ELIGIBLE_A",
         "sla_response_minutes": 20, "message_standard": "NCPDP_SCRIPT_2022011",
         "effective_from": "2026-07-01T00:00:00Z",
         "effective_to": "2026-12-31T00:00:00Z"},
        headers,
    )
    created = validate_success(adjacent, 201)
    assert created["effective_from"] == "2026-07-01T00:00:00Z"


def test_intervals_differing_in_service_set_do_not_collide(api):
    """PRD §2.6: "Two endpoints of the same participant that share a `service_set`, an
    `endpoint_role`, and a `message_standard` may not hold overlapping intervals"
    PRD §3.1: "the `service_set` it supports — `NEW_RX`, `REFILL_RX`, `CHANGE_CANCEL`,
    `MED_HISTORY`, `BENEFIT_COST`, or `ELIGIBILITY_FORMULARY`"

    Design: Difficulty/resource_temporal_overlap/directory_endpoint_service_interval_overlap_half_open
    """
    set_clock()
    pharmacy = create_pharmacy()
    headers = make_participant_admin_headers(pharmacy["id"])
    first = add_endpoint(
        pharmacy["id"], service_set="NEW_RX", endpoint_role="BOTH", service_level="ELIGIBLE_A",
        sla_response_minutes=15, message_standard="NCPDP_SCRIPT_2022011",
        effective_from="2026-01-01T00:00:00Z", effective_to="2026-07-01T00:00:00Z",
    )
    second = add_endpoint(
        pharmacy["id"], service_set="BENEFIT_COST", endpoint_role="BOTH",
        service_level="ELIGIBLE_A", sla_response_minutes=15,
        message_standard="NCPDP_SCRIPT_2022011",
        effective_from="2026-01-01T00:00:00Z", effective_to="2026-07-01T00:00:00Z",
    )
    assert first["service_set"] == "NEW_RX"
    assert second["service_set"] == "BENEFIT_COST"

    listed = validate_success(
        api_client.list_participant_endpoints(pharmacy["id"], headers), 200
    )
    assert {row["id"] for row in listed} == {first["id"], second["id"]}


def test_a_second_consent_for_the_same_scope_inside_a_live_window_is_refused(api):
    """PRD §3.8: "Only one `ACTIVE` window may exist at a time for a given patient and scope,
    so a grant whose window intersects an existing `ACTIVE` window for the same patient and
    scope is refused with `ERR_CONSENT_INTERVAL_OVERLAP` at HTTP 422."

    Design: Difficulty/resource_temporal_overlap/patient_consent_validity_window_overlap_closed_grant
    """
    set_clock()
    patient = create_patient()
    live = grant_consent(patient["id"], scope="MEDICATION_HISTORY", duration_days=365)
    grant_consent(patient["id"], scope="BENEFIT_CHECK", duration_days=365)

    clash = api_client.grant_consent(
        patient["id"], {"scope": "MEDICATION_HISTORY", "duration_days": 30},
        PATIENT_SERVICE,
    )
    validate_error(clash, "ERR_CONSENT_INTERVAL_OVERLAP", expected_status=422)

    # The rejected grant neither moved nor truncated the live window.
    reread = validate_success(api_client.get_consent(live["id"], PATIENT_SERVICE), 200)
    assert reread["expires_at"] == live["expires_at"]
    assert reread["status"] == "ACTIVE"


def test_rejected_grants_do_not_advance_the_patients_consent_version(api):
    """PRD §3.8: "A successful grant sets the patient's `consent_status` to `GRANTED` and
    increments the patient's `consent_version`."
    PRD §3.8: "a grant whose window intersects an existing `ACTIVE` window for the same patient
    and scope is refused with `ERR_CONSENT_INTERVAL_OVERLAP` at HTTP 422."

    Design: Difficulty/resource_temporal_overlap/patient_consent_validity_window_overlap_closed_grant
    """
    set_clock()
    patient = create_patient()
    grant_consent(patient["id"], scope="MEDICATION_HISTORY", duration_days=365)
    grant_consent(patient["id"], scope="BENEFIT_CHECK", duration_days=365)

    assert reload_patient(patient["id"])["consent_version"] == 2

    for scope, duration in (("MEDICATION_HISTORY", 30), ("BOTH", 30)):
        refused = api_client.grant_consent(
            patient["id"], {"scope": scope, "duration_days": duration},
            PATIENT_SERVICE,
        )
        assert refused.status_code == 422

    after = reload_patient(patient["id"])
    assert after["consent_version"] == 2, "only the two accepted grants incremented the version"
    assert after["consent_status"] == "GRANTED"