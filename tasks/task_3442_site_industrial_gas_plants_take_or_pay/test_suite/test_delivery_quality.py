"""Quality certification: parallel transport/quality axes, the redelivery
cascade on failure, result-consistency and segregation gates, and certificate
uniqueness/lockdown."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    confirm_delivery,
    create_certified_delivery,
    create_certificate_payload,
    create_certify_payload,
    create_customer,
    create_delivered_delivery,
    create_recorded_certificate,
    create_tank_with_telemetry_delivery,
    decide_certificate,
    list_tank_deliveries,
    make_quality_analyst_headers,
    make_quality_certifier_headers,
    record_certificate,
    set_logical_clock,
    validate_error,
    validate_success,
)


def test_delivery_parallel_transport_quality(api):
    """PRD section 3.6: "Its lifecycle runs on two parallel axes:
    `transport_status` (`SCHEDULED`, `DELIVERED`, `COMPLETED`, `REJECTED`, or
    `CANCELLED`) and `quality_status` (`QC_PENDING`, `CERTIFIED`, or
    `FAILED`), starting as `SCHEDULED` with `QC_PENDING`."
    PRD section 3.6: "Confirming a delivery records the
    `delivered_quantity_liters`, stamps `confirmed_at` with the logical time,
    and moves transport to `DELIVERED` while quality remains `QC_PENDING`."
    PRD section 3.6: "A `CERTIFIED` outcome moves the certificate to
    `CERTIFIED` and the delivery to `COMPLETED` with `CERTIFIED` quality."

    Design: Difficulty/non_linear_state_machine/delivery_parallel_transport_quality
    """
    set_logical_clock()
    customer = create_customer(name="Fabrikam Chips", segment="ELECTRONICS",
                               credit_standing="PRIME")
    tank, delivery = create_tank_with_telemetry_delivery(customer["id"])
    delivered = confirm_delivery(delivery["id"], headroom_liters=30000)
    assert delivered["transport_status"] == "DELIVERED"
    assert delivered["quality_status"] == "QC_PENDING", (
        "confirmation moves transport only; the quality axis evolves independently"
    )
    assert delivered["delivered_quantity_liters"] == 30000

    certificate = record_certificate(delivery["id"], analyst_user_id="qa-1")
    decide_certificate(certificate["id"], "CERTIFIED", certifier_user_id="qc-9")
    after = validate_success(api_client.get_delivery(
        delivery["id"], TEST_USERS["quality_certifier_headers"]
    ))
    assert after["transport_status"] == "COMPLETED"
    assert after["quality_status"] == "CERTIFIED"
    deliveries = list_tank_deliveries(tank["id"])
    assert len(deliveries) == 1, (
        "a successful certification spawns no replacement delivery"
    )


def test_quality_fail_redelivery_cascade(api):
    """PRD section 3.6: "A `FAILED` outcome moves the certificate to `FAILED`,
    the delivery to `REJECTED` with `FAILED` quality, and immediately
    auto-creates a replacement delivery for the same tank — `triggered_by`
    `REDELIVERY`, quantity equal to the tank's current headroom — with stop
    sequences recomputed for the affected route date."

    Design: Difficulty/transitive_cascade/quality_fail_redelivery_cascade
    """
    set_logical_clock()
    customer = create_customer(name="Fabrikam Chips", segment="ELECTRONICS",
                               credit_standing="PRIME")
    tank, delivery = create_tank_with_telemetry_delivery(customer["id"])
    confirm_delivery(delivery["id"], headroom_liters=30000)
    certificate = record_certificate(
        delivery["id"], analyst_user_id="qa-1",
        measured_purity_percent=99.99, measured_impurity_ppm=14,
    )
    failed = decide_certificate(certificate["id"], "FAILED", certifier_user_id="qc-9")
    assert failed["result"] == "FAILED"

    rejected = validate_success(api_client.get_delivery(
        delivery["id"], TEST_USERS["quality_certifier_headers"]
    ))
    assert rejected["transport_status"] == "REJECTED"
    assert rejected["quality_status"] == "FAILED"

    deliveries = list_tank_deliveries(tank["id"])
    assert len(deliveries) == 2
    replacements = [d for d in deliveries if d["triggered_by"] == "REDELIVERY"]
    assert len(replacements) == 1
    assert replacements[0]["quantity_liters"] == 30000, (
        "the tank level never moved, so the replacement matches the original headroom"
    )
    tank_after = validate_success(api_client.get_tank(
        tank["id"], TEST_USERS["quality_certifier_headers"]
    ))
    assert tank_after["current_level_liters"] == 20000
    assert tank_after["status"] == "REORDER_DUE"


def test_certify_inconsistent_result_rejected(api):
    """PRD section 3.6: "A `CERTIFIED` decision additionally requires the
    measurements to satisfy the delivery's snapshotted specification: measured
    purity at least the delivery's `required_purity_percent` and measured
    impurities at most its `max_impurity_ppm`, otherwise the decision is
    rejected with `ERR_RESULT_INCONSISTENT`."

    Design: Corner/validations/certify_inconsistent_result_rejected
    """
    set_logical_clock()
    customer = create_customer(name="Fabrikam Chips", segment="ELECTRONICS",
                               credit_standing="PRIME")
    _, delivery, certificate = create_recorded_certificate(
        customer["id"], cert_overrides={
            "measured_purity_percent": 99.99, "measured_impurity_ppm": 5,
        },
    )
    response = api_client.certify_quality_certificate(
        certificate["id"], create_certify_payload("CERTIFIED"),
        make_quality_certifier_headers("qc-9"),
    )
    validate_error(response, ApiErrorId.ERR_RESULT_INCONSISTENT)
    certificates = validate_success(api_client.list_quality_certificates(
        delivery["id"], TEST_USERS["quality_certifier_headers"]
    ))
    assert certificates[0]["result"] == "RECORDED"
    after = validate_success(api_client.get_delivery(
        delivery["id"], TEST_USERS["quality_certifier_headers"]
    ))
    assert after["transport_status"] == "DELIVERED"


def test_certificate_double_decision_lockdown(api):
    """PRD section 3.6: "A `CERTIFIED` outcome moves the certificate to
    `CERTIFIED` and the delivery to `COMPLETED` with `CERTIFIED` quality."
    PRD section 2.8: "State guards: the stale-version checks of §2.7, the
    evaluation-accepted requirement, from-state legality for the requested
    transition (`ERR_INVALID_STATE_TRANSITION`), the contract-active
    requirement (`ERR_CONTRACT_NOT_ACTIVE`), the plant-operating requirement
    (`ERR_PLANT_NOT_OPERATING`), and the delivery-delivered requirement
    (`ERR_DELIVERY_NOT_DELIVERED`)."

    Design: Corner/state_machines/certificate_double_decision_lockdown
    """
    set_logical_clock()
    customer = create_customer(name="Fabrikam Chips", segment="ELECTRONICS",
                               credit_standing="PRIME")
    _, delivery, certificate = create_certified_delivery(customer["id"])
    response = api_client.certify_quality_certificate(
        certificate["id"], create_certify_payload("FAILED"),
        make_quality_certifier_headers("qc-9"),
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
    certificates = validate_success(api_client.list_quality_certificates(
        delivery["id"], TEST_USERS["quality_certifier_headers"]
    ))
    assert certificates[0]["result"] == "CERTIFIED", (
        "the decided outcome is final"
    )


def test_certificate_exists_second_record_rejected(api):
    """PRD section 3.6: "At most one certificate may ever exist per delivery
    (`ERR_CERTIFICATE_EXISTS`)."

    Design: Corner/endpoints/certificate_exists_second_record_rejected
    """
    set_logical_clock()
    customer = create_customer(name="Fabrikam Chips", segment="ELECTRONICS",
                               credit_standing="PRIME")
    _, delivery, certificate = create_recorded_certificate(customer["id"])
    response = api_client.create_quality_certificate(
        delivery["id"],
        create_certificate_payload(
            sampled_at="2026-10-01T09:00:00Z",
            measured_purity_percent=99.9996, measured_impurity_ppm=4,
        ),
        make_quality_analyst_headers("qa-2"),
    )
    validate_error(response, ApiErrorId.ERR_CERTIFICATE_EXISTS)
    certificates = validate_success(api_client.list_quality_certificates(
        delivery["id"], TEST_USERS["quality_analyst_headers"]
    ))
    assert len(certificates) == 1
    assert certificates[0]["id"] == certificate["id"]


def test_segregation_same_user_certify_rejected(api):
    """PRD section 3.6: "The certifier's `X-User-ID` must differ from the
    certificate's `analyst_user_id` — self-certification is rejected with
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/segregation_same_user_certify_rejected
    """
    set_logical_clock()
    customer = create_customer(name="Fabrikam Chips", segment="ELECTRONICS",
                               credit_standing="PRIME")
    _, delivery, certificate = create_recorded_certificate(
        customer["id"], analyst_user_id="qa-shared"
    )
    response = api_client.certify_quality_certificate(
        certificate["id"], create_certify_payload("CERTIFIED"),
        make_quality_certifier_headers("qa-shared"),
    )
    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    certificates = validate_success(api_client.list_quality_certificates(
        delivery["id"], TEST_USERS["quality_certifier_headers"]
    ))
    assert certificates[0]["result"] == "RECORDED"
