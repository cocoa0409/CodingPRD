"""Depth tests: cross-entity state dependencies (audit gate, certificate gate)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    award_contract,
    build_bus_to_built,
    complete_pre_award_audit,
    create_agency,
    create_audit_record_payload,
    create_component,
    create_draft_contract,
    create_frozen_configuration,
    get_success_data,
    setup_active_contract,
    validate_error,
    validate_success,
)

PO = TEST_USERS["procurement_officer_headers"]
AUD = TEST_USERS["auditor_headers"]
PP = TEST_USERS["production_planner_headers"]


def _setup_awarded_contract_with_open_audit(api):
    """DRAFT contract + FROZEN config + award + OPEN pre-award audit whose
    propulsion component docs are not yet verified."""
    agency = create_agency()
    contract = create_draft_contract(agency["id"], base_quantity=1)
    component = create_component(name="Engine", category="PROPULSION")
    config = create_frozen_configuration(
        contract["id"], [component["id"]], contract["version"]
    )
    award_contract(contract["id"])
    resp = api.create_audit_record(
        create_audit_record_payload(contract["id"]), AUD
    )
    audit = get_success_data(resp)
    return agency, contract, component, config, audit


def test_activate_rejected_while_pre_award_audit_incomplete(api):
    """PRD section 3.2: "Moving an `AWARDED` contract to `ACTIVE` is permitted
    only after a `PRE_AWARD` audit of the contract has been completed with a
    `PASS` result; attempting activation without one is rejected with
    `ERR_AUDIT_INCOMPLETE`."

    Design: Difficulty/cross_entity_state_dependency/contract_activation_gated_on_pre_award_audit
    """
    _agency, contract, _component, _config, _audit = (
        _setup_awarded_contract_with_open_audit(api)
    )
    resp = api.activate_contract(contract["id"], PO)
    validate_error(resp, ApiErrorId.ERR_AUDIT_INCOMPLETE)


def test_activate_succeeds_after_passing_pre_award_audit(api):
    """PRD section 3.7: "A completed `PASS` on a pre-award audit is exactly
    what unlocks the contract's `AWARDED` → `ACTIVE` transition."
    PRD section 3.7: "Completing the audit records the number of in-scope
    buses as `scope_bus_count` and computes the `result`: `PASS` when
    `findings_count` is 0, otherwise `FAIL`."

    Design: Difficulty/cross_entity_state_dependency/contract_activation_gated_on_pre_award_audit
    """
    _agency, contract, component, _config, audit = (
        _setup_awarded_contract_with_open_audit(api)
    )
    from test_helpers import submit_and_verify_component
    submit_and_verify_component(component["id"])
    resp = api.complete_audit(audit["id"], AUD)
    audit = validate_success(resp)
    assert audit["result"] == "PASS", (
        f"findings_count 0 must compute PASS, got {audit['result']}"
    )

    resp = api.activate_contract(contract["id"], PO)
    activated = validate_success(resp)
    assert activated["status"] == "ACTIVE"


def test_plant_inspection_rejected_without_certificate(api):
    """PRD section 3.6: "a bus cannot advance from `BUILT` to
    `PLANT_INSPECTION` while it lacks an `ISSUED` certificate — the submission
    is rejected with `ERR_CERTIFICATE_MISSING` — and for a federally funded
    agency the certificate must additionally show a `domestic_content_pct` of
    at least its `threshold_pct`, with a shortfall rejected as
    `ERR_DOMESTIC_CONTENT_BELOW_THRESHOLD`."

    Design: Difficulty/cross_entity_state_dependency/plant_inspection_gated_on_issued_certificate
    """
    setup = setup_active_contract(contract_overrides={"base_quantity": 1})
    bus = build_bus_to_built(setup)
    assert bus["status"] == "BUILT"

    resp = api.submit_plant_inspection(bus["id"], PP)
    validate_error(resp, ApiErrorId.ERR_CERTIFICATE_MISSING)


def test_plant_inspection_succeeds_once_certificate_issued(api):
    """PRD section 3.8: "This submission carries the domestic content gate in
    full: the bus must hold an `ISSUED` certificate, failing as
    `ERR_CERTIFICATE_MISSING`, and if the agency is federally funded that
    certificate's `domestic_content_pct` must be at least the certificate's
    `threshold_pct`, failing as `ERR_DOMESTIC_CONTENT_BELOW_THRESHOLD`."

    Design: Difficulty/cross_entity_state_dependency/plant_inspection_gated_on_issued_certificate
    """
    from test_helpers import issue_certificate
    setup = setup_active_contract(contract_overrides={"base_quantity": 1})
    bus = build_bus_to_built(setup)
    issue_certificate(bus["id"], variant="COST_BASED")

    resp = api.submit_plant_inspection(bus["id"], PP)
    submitted = validate_success(resp)
    assert submitted["status"] == "PLANT_INSPECTION"
