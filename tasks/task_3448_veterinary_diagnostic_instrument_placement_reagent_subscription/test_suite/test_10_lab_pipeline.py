"""Diagnostic pipelines: branches, result record, proficiency, delivery gates (PRD §2.5, §3.8, §3.9)."""

from test_helpers import (
    ApiErrorId,
    CLOCK_2026_10_01,
    CLOCK_2026_10_01_1S,
    TEST_USERS,
    advance_clock,
    api_client,
    assert_lab_result,
    create_clinic,
    deliver_test_order,
    get_analyzer,
    get_test_order,
    get_test_order_results,
    list_service_cases,
    make_clinic_manager_headers,
    patch_lab_test_order_payload,
    place_patient_order,
    place_proficiency_order,
    place_send_out_patient_order,
    record_in_clinic_result,
    set_connectivity,
    setup_in_service_analyzer,
    setup_online_analyzer,
    setup_patient_order_ready,
    setup_recorded_patient_result,
    validate_error,
)

_LABTECH = TEST_USERS["laboratory_technician_headers"]


def test_lab_result_immutable_single_record(api):
    """PRD §2.5: "The result record is the one exception: as an immutable
    record created once per test order, it carries only `id` and
    `created_at`, and both `updated_at` and `version` are absent from it."
    PRD §3.8: "Recording a result creates the order's single result record —
    exactly one per test order". PRD §3.8: "any recording attempted from the
    wrong state or the wrong branch is `ERR_TEST_ORDER_INVALID_STATE`".

    Design: Corner/entities/lab_result_immutable_single_record
    """
    scenario = setup_recorded_patient_result(result_value=7.7)
    order = scenario["patient_order"]
    clinic = scenario["clinic"]

    results = get_test_order_results(order["id"])
    assert len(results) == 1
    record = results[0]
    assert_lab_result(record)  # id + created_at present; updated_at/version absent
    assert record["test_order_id"] == order["id"]
    assert record["source"] == "IN_CLINIC"
    assert record["result_value"] == 7.7
    assert record["verdict"] is None  # PATIENT results carry no verdict
    assert record["resulted_at"]

    resp = api_client.update_lab_test_order(
        order["id"],
        patch_lab_test_order_payload("RECORD_RESULT", result_value=8.8),
        make_clinic_manager_headers(clinic["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_TEST_ORDER_INVALID_STATE)

    after = get_test_order_results(order["id"])
    assert len(after) == 1
    assert after[0]["result_value"] == 7.7  # no overwrite channel exists


def test_lab_test_order_receive_rejected_for_in_clinic(api):
    """PRD §3.8: "attempting receipt on an `IN_CLINIC` order, or on an order
    no longer `ORDERED`, is rejected with `ERR_TEST_ORDER_INVALID_STATE`".

    Design: Corner/state_machines/lab_test_order_receive_rejected_for_in_clinic
    """
    scenario = setup_in_service_analyzer()
    order = place_patient_order(scenario["clinic"]["id"], scenario["analyzer"]["id"])

    resp = api_client.update_lab_test_order(
        order["id"], patch_lab_test_order_payload("RECEIVE"), _LABTECH
    )
    # The origin gate, not a role failure: LaboratoryTechnician IS the RECEIVE role.
    validate_error(resp, ApiErrorId.ERR_TEST_ORDER_INVALID_STATE)
    assert get_test_order(order["id"])["status"] == "ORDERED"


def test_lab_test_order_send_out_result_before_receive_rejected(api):
    """PRD §3.8: "The send-out branch inserts a laboratory intake stage".
    PRD §3.8: "On the send-out branch, the `LaboratoryTechnician` records the
    reference-lab result from `RECEIVED`." — from ORDERED the recording is
    rejected with `ERR_TEST_ORDER_INVALID_STATE` per "any recording attempted
    from the wrong state or the wrong branch".

    Design: Corner/state_machines/lab_test_order_send_out_result_before_receive_rejected
    """
    clinic = create_clinic()
    order = place_send_out_patient_order(clinic["id"])

    resp = api_client.update_lab_test_order(
        order["id"],
        patch_lab_test_order_payload("RECORD_RESULT", result_value=42.0),
        _LABTECH,
    )
    validate_error(resp, ApiErrorId.ERR_TEST_ORDER_INVALID_STATE)
    assert get_test_order_results(order["id"]) == []


def test_lab_test_order_cancel_after_result_rejected(api):
    """PRD §3.8: "Cancellation by the owning manager is available from
    `ORDERED` or `RECEIVED` and lands in `CANCELLED`." PRD §3.8: "`DELIVERED`
    and `CANCELLED` are terminal, and any drive from a state the transition
    does not allow is `ERR_TEST_ORDER_INVALID_STATE`".

    Design: Corner/state_machines/lab_test_order_cancel_after_result_rejected
    """
    scenario = setup_recorded_patient_result()
    order = scenario["patient_order"]
    clinic = scenario["clinic"]

    resp = api_client.update_lab_test_order(
        order["id"],
        patch_lab_test_order_payload("CANCEL"),
        make_clinic_manager_headers(clinic["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_TEST_ORDER_INVALID_STATE)
    assert get_test_order(order["id"])["status"] == "RESULT_RECORDED"
    assert len(get_test_order_results(order["id"])) == 1


def test_deliver_requires_result_recorded_first(api):
    """PRD §3.8: "Delivery into the practice-management record is the owning
    `ClinicManager`'s final step, moving the order `RESULT_RECORDED` →
    `DELIVERED`" — from ORDERED the drive is rejected with
    `ERR_TEST_ORDER_INVALID_STATE` ("any drive from a state the transition
    does not allow"). PRD §3.8: "A new order starts `ORDERED` with
    `delivery_status` `NOT_READY`."

    Design: Corner/endpoints/deliver_requires_result_recorded_first
    """
    scenario = setup_patient_order_ready()
    order = scenario["patient_order"]
    clinic = scenario["clinic"]

    resp = api_client.update_lab_test_order(
        order["id"],
        patch_lab_test_order_payload("DELIVER"),
        make_clinic_manager_headers(clinic["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_TEST_ORDER_INVALID_STATE)
    after = get_test_order(order["id"])
    assert after["status"] == "ORDERED"
    assert after["delivery_status"] == "NOT_READY"


def test_deliver_blocked_when_connectivity_degraded(api):
    """PRD §3.8: "In-clinic delivery requires the analyzer's connectivity
    `ACTIVE` at push time (`ERR_CONNECTIVITY_NOT_ACTIVE`); send-out delivery
    has no connectivity gate." PRD §3.8: the successful push moves the order
    "`RESULT_RECORDED` → `DELIVERED` with `delivery_status` moving `PENDING`
    → `DELIVERED`".

    Design: Corner/endpoints/deliver_blocked_when_connectivity_degraded
    """
    scenario = setup_recorded_patient_result()
    order = scenario["patient_order"]
    clinic = scenario["clinic"]
    analyzer = scenario["analyzer"]

    set_connectivity(analyzer["id"], "DEGRADED")
    resp = api_client.update_lab_test_order(
        order["id"],
        patch_lab_test_order_payload("DELIVER"),
        make_clinic_manager_headers(clinic["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_CONNECTIVITY_NOT_ACTIVE)
    held = get_test_order(order["id"])
    assert held["status"] == "RESULT_RECORDED"
    assert held["delivery_status"] == "PENDING"

    set_connectivity(analyzer["id"], "ACTIVE")
    delivered = deliver_test_order(order["id"], clinic["id"])
    assert delivered["status"] == "DELIVERED"
    assert delivered["delivery_status"] == "DELIVERED"


def test_record_result_blocked_by_lapsed_proficiency(api):
    """PRD §3.8: "the analyzer must be `IN_SERVICE`
    (`ERR_ANALYZER_INVALID_STATE`); then, for `PATIENT` orders only,
    connectivity must be `ACTIVE` (`ERR_CONNECTIVITY_NOT_ACTIVE`); and
    finally, again for `PATIENT` orders only, proficiency standing must be
    `CURRENT` (`ERR_PROFICIENCY_LAPSED`)." — with the analyzer IN_SERVICE and
    connectivity ACTIVE but proficiency never passed, the proficiency gate
    fires.

    Design: Difficulty/cross_entity_state_dependency/record_result_requires_analyzer_readiness
    """
    scenario = setup_in_service_analyzer()
    clinic = scenario["clinic"]
    analyzer = scenario["analyzer"]
    set_connectivity(analyzer["id"], "ACTIVE")
    order = place_patient_order(clinic["id"], analyzer["id"])

    resp = api_client.update_lab_test_order(
        order["id"],
        patch_lab_test_order_payload("RECORD_RESULT", result_value=7.7),
        make_clinic_manager_headers(clinic["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_PROFICIENCY_LAPSED)
    assert get_test_order(order["id"])["status"] == "ORDERED"
    assert get_test_order_results(order["id"]) == []


def test_record_result_connectivity_gate_fires_before_proficiency(api):
    """PRD §3.8: the safety gates are "evaluated in a fixed order: the
    analyzer must be `IN_SERVICE` ... then ... connectivity must be `ACTIVE`
    (`ERR_CONNECTIVITY_NOT_ACTIVE`); and finally ... proficiency standing
    must be `CURRENT`" — with connectivity DEGRADED (and proficiency still
    LAPSED), the earlier connectivity gate reports.

    Design: Difficulty/cross_entity_state_dependency/record_result_requires_analyzer_readiness
    """
    scenario = setup_in_service_analyzer()
    clinic = scenario["clinic"]
    analyzer = scenario["analyzer"]
    set_connectivity(analyzer["id"], "ACTIVE")
    order = place_patient_order(clinic["id"], analyzer["id"])
    set_connectivity(analyzer["id"], "DEGRADED")

    resp = api_client.update_lab_test_order(
        order["id"],
        patch_lab_test_order_payload("RECORD_RESULT", result_value=7.7),
        make_clinic_manager_headers(clinic["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_CONNECTIVITY_NOT_ACTIVE)
    assert get_test_order(order["id"])["status"] == "ORDERED"
    assert get_test_order_results(order["id"]) == []


def test_proficiency_fail_lapses_standing_and_spawns_remediation(api):
    """PRD §3.9: "A `FAIL` lapses the analyzer to `LAPSED`, leaves
    `qc_valid_until` unchanged, and — as a system cascade — opens a
    `PROFICIENCY_REMEDIATION` service case for that analyzer in `OPEN`
    status." PRD §3.9: "the absolute deviation between them must be at most
    0.05 of the expected value" — |230.0 - 200.0| = 30.0 > 10.0.

    Design: Difficulty/transitive_cascade/proficiency_fail_cascade
    """
    scenario = setup_online_analyzer()
    clinic = scenario["clinic"]
    analyzer = scenario["analyzer"]
    assert analyzer["proficiency_standing"] == "CURRENT"

    prof = place_proficiency_order(clinic["id"], analyzer["id"], expected_result=200.0)
    record_in_clinic_result(prof["id"], clinic["id"], 230.0)

    results = get_test_order_results(prof["id"])
    assert results[0]["verdict"] == "FAIL"
    assert get_analyzer(analyzer["id"])["proficiency_standing"] == "LAPSED"

    cases = list_service_cases(analyzer["id"])
    assert len(cases) == 1
    assert cases[0]["case_type"] == "PROFICIENCY_REMEDIATION"
    assert cases[0]["status"] == "OPEN"


def test_proficiency_fail_blocks_patient_testing(api):
    """PRD §3.9: "A `FAIL` lapses the analyzer to `LAPSED`". PRD §3.8:
    "finally, again for `PATIENT` orders only, proficiency standing must be
    `CURRENT` (`ERR_PROFICIENCY_LAPSED`)" — the cascade's downstream effect
    is that in-clinic patient testing stops until proficiency is restored.

    Design: Difficulty/transitive_cascade/proficiency_fail_cascade
    """
    scenario = setup_online_analyzer()
    clinic = scenario["clinic"]
    analyzer = scenario["analyzer"]

    prof = place_proficiency_order(clinic["id"], analyzer["id"], expected_result=200.0)
    record_in_clinic_result(prof["id"], clinic["id"], 230.0)  # FAIL → LAPSED

    patient = place_patient_order(clinic["id"], analyzer["id"])
    resp = api_client.update_lab_test_order(
        patient["id"],
        patch_lab_test_order_payload("RECORD_RESULT", result_value=7.7),
        make_clinic_manager_headers(clinic["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_PROFICIENCY_LAPSED)
    assert get_test_order(patient["id"])["status"] == "ORDERED"


def test_proficiency_tolerance_boundary_inclusive(api):
    """PRD §3.9: "the absolute deviation between them must be at most 0.05 of
    the expected value (`PROFICIENCY_TOLERANCE_PCT`)." PRD §3.9: "The
    boundary is inclusive — a deviation of exactly five percent passes". PRD
    §3.9: "A `PASS` sets `proficiency_standing` to `CURRENT` and extends
    `qc_valid_until` to thirty days (`QC_VALIDITY_DAYS`, 30 days) after
    `resulted_at`." — 210.0 vs 200.0 is exactly 5% (PASS); 210.01 exceeds it
    (FAIL).

    Design: Corner/calculations/proficiency_tolerance_boundary_inclusive
    """
    scenario = setup_in_service_analyzer()
    clinic = scenario["clinic"]
    analyzer = scenario["analyzer"]

    prof_pass = place_proficiency_order(clinic["id"], analyzer["id"], expected_result=200.0)
    prof_fail = place_proficiency_order(clinic["id"], analyzer["id"], expected_result=200.0)

    record_in_clinic_result(prof_pass["id"], clinic["id"], 210.0)
    assert get_test_order_results(prof_pass["id"])[0]["verdict"] == "PASS"
    after_pass = get_analyzer(analyzer["id"])
    assert after_pass["proficiency_standing"] == "CURRENT"
    # recorded at the startup clock 2026-09-01T00:00:00Z, +30 days
    assert after_pass["qc_valid_until"] == "2026-10-01T00:00:00Z"

    record_in_clinic_result(prof_fail["id"], clinic["id"], 210.01)
    assert get_test_order_results(prof_fail["id"])[0]["verdict"] == "FAIL"
    assert get_analyzer(analyzer["id"])["proficiency_standing"] == "LAPSED"


def test_qc_validity_lapses_only_after_boundary(api):
    """PRD §3.9: "Time lapses standing too: the clock sweep flips a `CURRENT`
    analyzer to `LAPSED` once the clock passes `qc_valid_until` strictly." —
    at exactly `qc_valid_until` the standing holds; one second later it
    lapses, with `qc_valid_until` itself unchanged.

    Design: Corner/cross_cutting_layers/qc_validity_lapses_only_after_boundary
    """
    scenario = setup_online_analyzer()
    analyzer = scenario["analyzer"]
    assert analyzer["proficiency_standing"] == "CURRENT"
    assert analyzer["qc_valid_until"] == "2026-10-01T00:00:00Z"

    advance_clock(CLOCK_2026_10_01)
    at_boundary = get_analyzer(analyzer["id"])
    assert at_boundary["proficiency_standing"] == "CURRENT"  # lapse requires strictly past

    advance_clock(CLOCK_2026_10_01_1S)
    past_boundary = get_analyzer(analyzer["id"])
    assert past_boundary["proficiency_standing"] == "LAPSED"
    assert past_boundary["qc_valid_until"] == "2026-10-01T00:00:00Z"
