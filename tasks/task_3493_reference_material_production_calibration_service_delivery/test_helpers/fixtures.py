"""Composite setup helpers (PRD §3 workflows).

Every fixture builds preconditions from scratch using only PRD-declared
endpoints, and uses the lenient get_success_data validator so setup failures
surface as clear errors instead of assertion noise.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    ANALYST_ONE, ANALYST_TWO, OFFICER_ONE, OFFICER_TWO,
    FLAT_HOMOGENEITY, METHOD_ONE, METHOD_TWO, WINDOW_START, WINDOW_END,
)
from .factories import (
    create_program_payload, create_material_lot_payload, create_customer_payload,
    create_method_payload, create_certificate_payload, create_sales_order_payload,
    create_service_payload, create_calibration_order_payload,
    create_traceability_link_payload, create_pt_round_payload,
    create_participant_result_payload,
)
from .test_users import (
    TEST_USERS, make_metrologist_headers, make_certification_officer_headers,
    make_customer_headers,
)

_ADMIN = TEST_USERS["program_admin_headers"]
_INV = TEST_USERS["inventory_manager_headers"]
_AO = TEST_USERS["accreditation_officer_headers"]
_COORD = TEST_USERS["calibration_coordinator_headers"]


# --- Programs, customers, lots -------------------------------------------

def make_program(**overrides):
    return get_success_data(api_client.create_program(create_program_payload(**overrides), _ADMIN))


def make_customer(**overrides):
    return get_success_data(api_client.create_customer(create_customer_payload(**overrides), _ADMIN))


def make_lot(program_id, **overrides):
    return get_success_data(
        api_client.create_material_lot(create_material_lot_payload(program_id, **overrides), _ADMIN)
    )


def get_lot(lot_id):
    return get_success_data(api_client.get_material_lot(lot_id, _ADMIN))


def run_homogeneity(lot_id, homogeneity=None):
    """Drive lot into HOMOGENEITY_TESTING with the given payload (default flat PASS)."""
    payload = {"to": "HOMOGENEITY_TESTING"}
    payload.update(homogeneity or FLAT_HOMOGENEITY)
    return get_success_data(
        api_client.transition_material_lot(lot_id, payload, make_metrologist_headers("met-op"))
    )


# --- Methods & certificates -------------------------------------------------

def submit_method(lot_id, method_fields=None, analyst_id=ANALYST_ONE):
    payload = create_method_payload(lot_id, **(method_fields or {}))
    return get_success_data(
        api_client.create_value_assignment_method(payload, make_metrologist_headers(analyst_id))
    )


def accept_method(method_id, officer_id=OFFICER_ONE):
    return get_success_data(
        api_client.transition_value_assignment_method(
            method_id, {"to": "ACCEPTED"}, make_certification_officer_headers(officer_id)
        )
    )


def setup_value_assignment_lot(program=None, total=10, program_overrides=None,
                               **lot_overrides):
    """Lot in VALUE_ASSIGNMENT carrying two ACCEPTED methods (met-1, met-2)."""
    program = program or make_program(**(program_overrides or {}))
    lot = make_lot(program["id"], total_units_produced=total, **lot_overrides)
    lot = run_homogeneity(lot["id"])
    assert lot["status"] == "VALUE_ASSIGNMENT", f"fixture lot not VALUE_ASSIGNMENT: {lot}"
    m1 = submit_method(lot["id"], dict(METHOD_ONE), ANALYST_ONE)
    m2 = submit_method(lot["id"], dict(METHOD_TWO), ANALYST_TWO)
    accept_method(m1["id"], OFFICER_ONE)
    accept_method(m2["id"], OFFICER_ONE)
    return {"program": program, "lot": lot, "methods": [m1, m2]}


def create_draft_certificate(lot_id, officer_id=OFFICER_ONE, **overrides):
    lot = get_lot(lot_id)
    payload = create_certificate_payload(lot_id, lot["version"], **overrides)
    return get_success_data(
        api_client.create_certificate(payload, make_certification_officer_headers(officer_id))
    )


def publish_certificate(cert_id, officer_id=OFFICER_TWO):
    return get_success_data(
        api_client.transition_certificate(
            cert_id, {"to": "PUBLISHED"}, make_certification_officer_headers(officer_id)
        )
    )


def withdraw_certificate(cert_id, officer_id=OFFICER_TWO):
    return get_success_data(
        api_client.transition_certificate(
            cert_id, {"to": "WITHDRAWN"}, make_certification_officer_headers(officer_id)
        )
    )


def setup_lot_in_distribution(program=None, total=10, validity_days=365,
                              variant="WEIGHTED_MEAN", certificate_code="CERT-1",
                              program_overrides=None, **lot_overrides):
    """Full pipeline: lot IN_DISTRIBUTION behind a PUBLISHED certificate."""
    ctx = setup_value_assignment_lot(program=program, total=total,
                                     program_overrides=program_overrides, **lot_overrides)
    cert = create_draft_certificate(
        ctx["lot"]["id"], value_assignment_variant=variant,
        validity_days=validity_days, certificate_code=certificate_code,
    )
    cert = publish_certificate(cert["id"])
    lot = get_success_data(
        api_client.transition_material_lot(ctx["lot"]["id"], {"to": "IN_DISTRIBUTION"}, _INV)
    )
    ctx.update({"lot": lot, "certificate": cert})
    return ctx


# --- Sales orders -----------------------------------------------------------

def place_order(lot_id, customer_id, quantity):
    return get_success_data(
        api_client.create_sales_order(
            create_sales_order_payload(lot_id, quantity=quantity),
            make_customer_headers(customer_id),
        )
    )


def get_order(order_id):
    return get_success_data(api_client.get_sales_order(order_id, _INV))


# --- Calibration ------------------------------------------------------------

def make_service(**overrides):
    return get_success_data(api_client.create_calibration_service(create_service_payload(**overrides), _ADMIN))


def make_traceability_link(service_id, **overrides):
    return get_success_data(
        api_client.create_traceability_link(
            create_traceability_link_payload(service_id, **overrides),
            make_metrologist_headers("met-op"),
        )
    )


def make_calibration_order(service_id, customer_id, **overrides):
    return get_success_data(
        api_client.create_calibration_order(
            create_calibration_order_payload(service_id, **overrides),
            make_customer_headers(customer_id),
        )
    )


def schedule_calibration_order(order_id, start=WINDOW_START, end=WINDOW_END):
    return get_success_data(
        api_client.transition_calibration_order(
            order_id, {"to": "SCHEDULED", "scheduled_start": start, "scheduled_end": end},
            _COORD,
        )
    )


def setup_calibration_scenario(program=None, expedite=False, measurement_points=4,
                               service_overrides=None):
    """Program + ACTIVE service + valid traceability link + customer + RECEIVED order."""
    program = program or make_program()
    service = make_service(**(service_overrides or {}))
    link = make_traceability_link(service["id"])
    customer = make_customer()
    order = make_calibration_order(
        service["id"], customer["id"],
        measurement_points=measurement_points, expedite_requested=expedite,
    )
    return {"program": program, "service": service, "link": link,
            "customer": customer, "order": order}


# --- PT rounds ---------------------------------------------------------------

def make_pt_round(lot_id, **overrides):
    """Create a round (born in PLANNING)."""
    return get_success_data(
        api_client.create_pt_round(create_pt_round_payload(lot_id, **overrides), _AO)
    )


def setup_pt_round_open(lot_id, round_code="PT-1", round_type="PROFICIENCY_TEST",
                        sample_units_reserved=1):
    """Round driven PLANNING -> SAMPLE_DISTRIBUTION -> ANALYSIS_OPEN."""
    rnd = make_pt_round(lot_id, round_code=round_code, round_type=round_type,
                        sample_units_reserved=sample_units_reserved)
    get_success_data(api_client.transition_pt_round(rnd["id"], {"to": "SAMPLE_DISTRIBUTION"}, _AO))
    return get_success_data(api_client.transition_pt_round(rnd["id"], {"to": "ANALYSIS_OPEN"}, _AO))


def submit_result(round_id, customer_id, measured_value, uncertainty=1.0, lab_code="LAB-1"):
    return get_success_data(
        api_client.create_participant_result(
            round_id,
            create_participant_result_payload(lab_code=lab_code, measured_value=measured_value,
                                              measurement_uncertainty=uncertainty),
            make_customer_headers(customer_id),
        )
    )


def transition_round(round_id, to):
    return get_success_data(api_client.transition_pt_round(round_id, {"to": to}, _AO))


def run_failing_pt_round(lot_id, round_code, customer_id, measured_value=114.0, close=True):
    """Full PT cycle with one FAIL result; ends CLOSED (or EVALUATION if close=False)."""
    rnd = setup_pt_round_open(lot_id, round_code=round_code)
    submit_result(rnd["id"], customer_id, measured_value)
    rnd = transition_round(rnd["id"], "EVALUATION")
    if close:
        rnd = transition_round(rnd["id"], "CLOSED")
    return rnd


# --- Clock -------------------------------------------------------------------

def set_clock(to_iso8601):
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, _ADMIN))
