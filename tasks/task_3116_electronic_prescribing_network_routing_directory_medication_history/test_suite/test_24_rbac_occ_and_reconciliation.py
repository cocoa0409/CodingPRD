"""Corner coverage: role-based access control, optimistic concurrency on the route call, the
derived fee field's reconciliation across repeated post-and-reverse cycles, and the immediate
visibility of a reversal.
"""
from test_helpers import (
    validate_success,
    validate_error,
    set_clock,
    create_clinic,
    create_pharmacy,
    add_endpoint,
    certify_participant,
    create_patient,
    create_ready_session,
    create_prescription,
    post_fee_entry,
    reload_fee_entry,
    reverse_fee_entry,
    reload_prescription,
    make_prescriber_headers,
    make_pharmacy_headers,
    TEST_USERS,
    api_client,
)

OPERATOR = TEST_USERS["network_operator_headers"]


def _certified_pair():
    set_clock()
    clinic = create_clinic()
    add_endpoint(
        clinic["id"], service_set="NEW_RX", endpoint_role="SENDER", service_level="ELIGIBLE_A",
        sla_response_minutes=15, message_standard="NCPDP_SCRIPT_2022011",
    )
    clinic = certify_participant(clinic["id"])

    pharmacy = create_pharmacy()
    add_endpoint(
        pharmacy["id"], service_set="NEW_RX", endpoint_role="BOTH", service_level="ELIGIBLE_A",
        sla_response_minutes=15, message_standard="NCPDP_SCRIPT_2022011",
    )
    pharmacy = certify_participant(pharmacy["id"])
    return clinic, pharmacy


def test_a_role_without_the_operation_is_refused_before_any_guard_is_consulted(api):
    """PRD §2.1: "A request that names a valid role the operation does not authorize — or that
    supplies an `X-User-ID` which fails to resolve for a role whose identity is entity-backed —
    is refused with `ERR_FORBIDDEN_ROLE` and an HTTP 403."

    Design: Corner/rbac/pharmacy_cannot_complete_a_benefit_check_it_does_not_own_the_role_for_the_sign_step
    """
    clinic, pharmacy = _certified_pair()
    patient = create_patient()
    prescription = create_prescription(clinic["id"], pharmacy["id"], patient["id"])
    session = create_ready_session(prescription["id"], clinic["id"])
    assert session["two_factor_status"] == "PASSED"

    response = api_client.sign_prescription(
        prescription["id"], session["id"], make_pharmacy_headers(pharmacy["id"])
    )
    validate_error(response, "ERR_FORBIDDEN_ROLE", expected_status=403)

    after = reload_prescription(prescription["id"])
    assert after["clinical_status"] == "DRAFT"


def test_the_same_call_succeeds_for_the_authorized_role(api):
    """PRD §2.1: "Only a `Prescriber` may author a prescription, sign it, route it, push it to
    the fallback channel, cancel it, open and drive a signing session through identity proofing
    and two-factor verification, abandon a signing session, and register a patient."

    Design: Corner/rbac/pharmacy_cannot_complete_a_benefit_check_it_does_not_own_the_role_for_the_sign_step
    """
    clinic, pharmacy = _certified_pair()
    patient = create_patient()
    prescription = create_prescription(clinic["id"], pharmacy["id"], patient["id"])
    session = create_ready_session(prescription["id"], clinic["id"])

    signed = validate_success(
        api_client.sign_prescription(
            prescription["id"], session["id"], make_prescriber_headers(clinic["id"])
        ),
        200,
    )
    assert signed["clinical_status"] == "SIGNED"
    assert signed["signature_audit_id"] == session["id"]


def test_routing_with_a_stale_prescription_version_is_refused(api):
    """PRD §2.8: "A route request must carry `expected_prescription_version`, and that value
    must equal the prescription's current `version`."
    PRD §2.8: "Such a request is refused with `ERR_STALE_VERSION` at HTTP 412, and no
    `RoutingAttempt` is created."

    Design: Corner/cross_cutting_layers/stale_prescription_version_on_route_returns_precondition_failed
    """
    clinic, pharmacy = _certified_pair()
    patient = create_patient()
    prescription = create_prescription(clinic["id"], pharmacy["id"], patient["id"])
    created_version = prescription["version"]

    session = create_ready_session(prescription["id"], clinic["id"])
    signed = validate_success(
        api_client.sign_prescription(
            prescription["id"], session["id"], make_prescriber_headers(clinic["id"])
        ),
        200,
    )
    assert signed["version"] > created_version

    stale = api_client.route_prescription(
        prescription["id"], created_version, make_prescriber_headers(clinic["id"])
    )
    validate_error(stale, "ERR_STALE_VERSION", expected_status=412)

    after = reload_prescription(prescription["id"])
    assert after["routing_status"] == "NOT_ROUTED"
    assert after["routing_attempt_count"] == 0

    fresh = validate_success(
        api_client.route_prescription(
            prescription["id"], after["version"], make_prescriber_headers(clinic["id"])
        ),
        200,
    )
    assert fresh["routing_status"] == "ROUTED"


def test_repeated_post_and_reverse_cycles_return_the_derived_total_to_its_value(api):
    """PRD §2.7: "This quantity is identical on every such row, and because it ignores `status`
    entirely, a charge followed by its compensating row leaves the quantity exactly where it
    began"
    PRD §2.7: "The first is `period_net_total_cents`, the sum of `fee_cents` over every
    `TransactionFeeEntry` row sharing the same participant and `month_key`."

    Design: Corner/cross_cutting_layers/repeated_stop_and_repost_in_the_same_month_leaves_the_net_fee_unchanged
    """
    set_clock()
    clinic = create_clinic()

    first = post_fee_entry(
        clinic["id"], transaction_type="NEW_RX", direction="SENT", transaction_count=500
    )
    assert first["period_net_total_cents"] == 3600
    first_comp = reverse_fee_entry(first["id"], clinic["id"])

    second = post_fee_entry(
        clinic["id"], transaction_type="NEW_RX", direction="SENT", transaction_count=500
    )
    assert second["period_net_total_cents"] == 3600
    second_comp = reverse_fee_entry(second["id"], clinic["id"])

    third = post_fee_entry(
        clinic["id"], transaction_type="NEW_RX", direction="SENT", transaction_count=500
    )
    assert third["period_net_total_cents"] == 3600
    assert third["reversal_entry_id"] is None

    assert first_comp["fee_cents"] == -3600
    assert second_comp["fee_cents"] == -3600
    assert reload_fee_entry(first["id"])["period_net_total_cents"] == 3600


def test_a_reversal_is_visible_in_its_own_response_and_on_the_next_read(api):
    """PRD §2.7: "For the same reason a row marked `REVERSED` keeps its own `fee_cents` and
    remains inside the total; the marker records that a compensating row exists, not that the
    original was erased."

    Design: Corner/consistency_model/reversal_is_visible_in_its_own_response_and_on_the_next_read
    """
    set_clock()
    clinic = create_clinic()
    small = post_fee_entry(
        clinic["id"], transaction_type="NEW_RX", direction="SENT", transaction_count=500
    )
    big = post_fee_entry(
        clinic["id"], transaction_type="NEW_RX", direction="SENT", transaction_count=2000
    )

    response = reverse_fee_entry(big["id"], clinic["id"])
    assert response["status"] == "REVERSED"
    compensating_id = response["reversal_entry_id"]
    assert compensating_id is not None
    assert compensating_id == response["id"]

    sibling = reload_fee_entry(small["id"])
    assert sibling["period_net_total_cents"] == 3600
    assert sibling["reversal_entry_id"] is None

    reread = reload_fee_entry(big["id"])
    assert reread["status"] == "REVERSED"
    assert reread["reversal_entry_id"] == compensating_id
    assert reread["period_net_total_cents"] == sibling["period_net_total_cents"]