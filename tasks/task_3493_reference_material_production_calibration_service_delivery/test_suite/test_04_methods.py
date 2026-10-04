"""Value-assignment methods: adjudication, resubmission, uniqueness, SoD."""
from test_helpers import (
    ApiErrorId, accept_method, create_certificate_payload, create_method_payload,
    get_lot, make_certification_officer_headers, make_lot, make_metrologist_headers,
    make_program, run_homogeneity, submit_method, validate_error, validate_success,
)


def test_method_resubmit_cycle_restores_data(api):
    """PRD §3.3: "the original analyst — and only that analyst, with anyone else
    answered by `ERR_FORBIDDEN_OWNERSHIP` — may resubmit the method back into
    `DATA_SUBMITTED`, which overwrites `method_mean` and `method_std_uncertainty`
    with the payload values and clears `rejection_reason` to null."

    Design: Corner/state_machines/method_resubmit_cycle_restores_data
    """
    program = make_program(program_code="NIST-RM-C13")
    lot = make_lot(program["id"], material_code="SRM-C13")
    run_homogeneity(lot["id"])
    method = submit_method(lot["id"], analyst_id="met-1")
    rejected = validate_success(
        api.transition_value_assignment_method(
            method["id"], {"to": "REJECTED", "rejection_reason": "outlier in replicate 3"},
            make_certification_officer_headers("co-1"))
    )
    assert rejected["status"] == "REJECTED"
    resubmitted = validate_success(
        api.transition_value_assignment_method(
            method["id"], {"to": "DATA_SUBMITTED", "method_mean": 101.5,
                           "method_std_uncertainty": 1.5},
            make_metrologist_headers("met-1"))
    )
    assert resubmitted["status"] == "DATA_SUBMITTED"
    assert resubmitted["method_mean"] == 101.5
    assert resubmitted["rejection_reason"] is None


def test_method_double_accept_rejected(api):
    """PRD §3.3: "Accepting a method requires it to be in `DATA_SUBMITTED`
    (`ERR_INVALID_METHOD_STATE`)".

    Design: Corner/state_machines/method_double_accept_rejected
    """
    program = make_program(program_code="NIST-RM-C14")
    lot = make_lot(program["id"], material_code="SRM-C14")
    run_homogeneity(lot["id"])
    method = submit_method(lot["id"], analyst_id="met-1")
    accept_method(method["id"], "co-1")
    resp = api.transition_value_assignment_method(
        method["id"], {"to": "ACCEPTED"}, make_certification_officer_headers("co-1"))
    validate_error(resp, ApiErrorId.ERR_INVALID_METHOD_STATE)


def test_duplicate_analyst_method_rejected(api):
    """PRD §3.3: "One analyst may hold at most one open method per lot — open
    meaning `DATA_SUBMITTED` or `ACCEPTED` — and a second attempt is refused with
    `ERR_DUPLICATE_ANALYST_METHOD`".

    Design: Corner/calculations/duplicate_analyst_method_rejected
    """
    program = make_program(program_code="NIST-RM-C21")
    lot = make_lot(program["id"], material_code="SRM-C21")
    run_homogeneity(lot["id"])
    submit_method(lot["id"], analyst_id="met-1")
    resp = api.create_value_assignment_method(
        create_method_payload(lot["id"], method_code="M2", method_mean=101.0,
                              method_std_uncertainty=1.0),
        make_metrologist_headers("met-1"))
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_ANALYST_METHOD)


def test_insufficient_independent_methods_rejected(api):
    """PRD §3.4: "With at least two methods `ACCEPTED` — fewer draws
    `ERR_INSUFFICIENT_INDEPENDENT_METHODS`".

    Design: Corner/calculations/insufficient_independent_methods_rejected
    """
    program = make_program(program_code="NIST-RM-C20")
    lot = make_lot(program["id"], material_code="SRM-C20")
    run_homogeneity(lot["id"])
    method = submit_method(lot["id"], analyst_id="met-1")
    accept_method(method["id"], "co-1")
    payload = create_certificate_payload(
        lot["id"], get_lot(lot["id"])["version"], certificate_code="CERT-C20",
        validity_days=30)
    resp = api.create_certificate(payload, make_certification_officer_headers("co-1"))
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_INDEPENDENT_METHODS)


def test_method_accept_by_own_analyst_violates_segregation_rejected(api):
    """PRD §2.8: "Publishing a certificate or adjudicating a method must not be
    performed by an analyst of the lot's methods
    (`ERR_SEGREGATION_OF_DUTIES_VIOLATION`, 403)."

    Design: Corner/rbac/method_accept_by_own_analyst_violates_segregation_rejected
    """
    program = make_program(program_code="NIST-RM-C47")
    lot = make_lot(program["id"], material_code="SRM-C47")
    run_homogeneity(lot["id"])
    method = submit_method(lot["id"], analyst_id="met-1")
    resp = api.transition_value_assignment_method(
        method["id"], {"to": "ACCEPTED"}, make_certification_officer_headers("met-1"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION)
