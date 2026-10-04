"""PT round gates: state, duplicate participation, units, reference cert."""
from test_helpers import (
    ApiErrorId, create_participant_result_payload, create_pt_round_payload,
    make_accreditation_officer_headers, make_customer, make_customer_headers,
    make_lot, make_program, set_clock, setup_lot_in_distribution,
    setup_pt_round_open, submit_result, validate_error, validate_success,
)

_AO = make_accreditation_officer_headers()


def test_pt_result_before_analysis_open_rejected(api):
    """PRD §3.7: "filing while the round is not `ANALYSIS_OPEN` is refused with
    `ERR_INVALID_ROUND_STATE`."

    Design: Corner/state_machines/pt_result_before_analysis_open_rejected
    """
    program = make_program(program_code="NIST-RM-C18")
    lot = make_lot(program["id"], material_code="SRM-C18", total_units_produced=10)
    customer = make_customer(name="C18")
    rnd = validate_success(
        api.create_pt_round(create_pt_round_payload(lot["id"], round_code="PT-C18"), _AO),
        201)
    resp = api.create_participant_result(
        rnd["id"], create_participant_result_payload(),
        make_customer_headers(customer["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_ROUND_STATE)


def test_duplicate_participation_rejected(api):
    """PRD §3.7: "One customer files at most one result per round
    (`ERR_DUPLICATE_PARTICIPATION`)".

    Design: Corner/validations/duplicate_participation_rejected
    """
    ctx = setup_lot_in_distribution(total=10, material_code="SRM-C32",
                                    program_overrides={"program_code": "NIST-RM-C32"})
    customer = make_customer(name="C32")
    rnd = setup_pt_round_open(ctx["lot"]["id"], round_code="PT-C32")
    submit_result(rnd["id"], customer["id"], 100.0)
    resp = api.create_participant_result(
        rnd["id"],
        create_participant_result_payload(measured_value=101.0),
        make_customer_headers(customer["id"]))
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_PARTICIPATION)


def test_pt_evaluation_without_reference_certificate_rejected(api):
    """PRD §3.7: "a proficiency test additionally requires a `PUBLISHED`
    certificate for the lot (`ERR_NO_REFERENCE_CERTIFICATE`)".

    Design: Corner/validations/pt_evaluation_without_reference_certificate_rejected
    """
    ctx = setup_lot_in_distribution(total=10, material_code="SRM-C33", validity_days=30,
                                    program_overrides={"program_code": "NIST-RM-C33"})
    customer = make_customer(name="C33")
    rnd = setup_pt_round_open(ctx["lot"]["id"], round_code="PT-C33")
    submit_result(rnd["id"], customer["id"], 100.0)
    set_clock("2026-10-02T00:00:00Z")  # certificate (expiry 2026-10-01) is EXPIRED
    resp = api.transition_pt_round(rnd["id"], {"to": "EVALUATION"}, _AO)
    validate_error(resp, ApiErrorId.ERR_NO_REFERENCE_CERTIFICATE)


def test_pt_evaluation_insufficient_results_rejected(api):
    """PRD §3.7: "a proficiency test needs at least one `SUBMITTED` result, a
    key comparison at least two (the `MIN_KC_RESULTS` floor), with shortfalls
    answered by `ERR_INSUFFICIENT_RESULTS`".

    Design: Corner/validations/pt_evaluation_insufficient_results_rejected
    """
    ctx = setup_lot_in_distribution(total=10, material_code="SRM-C35",
                                    program_overrides={"program_code": "NIST-RM-C35"})
    customer = make_customer(name="C35")
    rnd = setup_pt_round_open(ctx["lot"]["id"], round_code="KC-C35",
                              round_type="KEY_COMPARISON")
    submit_result(rnd["id"], customer["id"], 100.0)
    resp = api.transition_pt_round(rnd["id"], {"to": "EVALUATION"}, _AO)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_RESULTS)


def test_pt_distribution_insufficient_units_rejected(api):
    """PRD §3.7: "Moving it to `SAMPLE_DISTRIBUTION` requires the lot to be
    `IN_DISTRIBUTION` (`ERR_LOT_NOT_DISTRIBUTABLE`) and its `units_available` to
    cover `sample_units_reserved` (`ERR_INSUFFICIENT_UNITS`)".

    Design: Corner/validations/pt_distribution_insufficient_units_rejected
    """
    ctx = setup_lot_in_distribution(total=8, material_code="SRM-C36",
                                    program_overrides={"program_code": "NIST-RM-C36"})
    rnd = validate_success(
        api.create_pt_round(
            create_pt_round_payload(ctx["lot"]["id"], round_code="PT-C36",
                                    sample_units_reserved=5), _AO), 201)
    resp = api.transition_pt_round(rnd["id"], {"to": "SAMPLE_DISTRIBUTION"}, _AO)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_UNITS)
