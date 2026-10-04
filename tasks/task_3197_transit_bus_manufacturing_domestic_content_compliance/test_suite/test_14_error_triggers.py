"""Corner tests: error-trigger claims (domestic content gate, audit
precondition, stale version on freeze)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    build_bus_to_built,
    create_agency,
    create_audit_record_payload,
    create_bus_configuration_payload,
    create_bus_unit_payload,
    create_certificate_payload,
    create_component,
    create_draft_contract,
    create_frozen_configuration,
    get_success_data,
    setup_active_contract,
    validate_error,
    validate_success,
)

PO = TEST_USERS["procurement_officer_headers"]
CE = TEST_USERS["config_engineer_headers"]
CO = TEST_USERS["compliance_officer_headers"]
PP = TEST_USERS["production_planner_headers"]
AUD = TEST_USERS["auditor_headers"]


def test_plant_inspection_below_threshold_rejected(api):
    """PRD section 3.6: "for a federally funded agency the certificate must
    additionally show a `domestic_content_pct` of at least its
    `threshold_pct`, with a shortfall rejected as
    `ERR_DOMESTIC_CONTENT_BELOW_THRESHOLD`."

    Design: Corner/errors/error_domestic_content_below_threshold_trigger
    """
    # 25% domestic content: domestic 100000 / total 400000. The configuration
    # carrying both components is frozen before activation (PRD section 3.3
    # allows submit-review only while the contract is DRAFT or AWARDED).
    domestic = create_component(name="Engine", category="PROPULSION",
                                unit_cost_cents=100000, is_domestic=True)
    foreign = create_component(name="Motor", category="ELECTRICAL",
                               unit_cost_cents=300000, is_domestic=False)
    from test_helpers import setup_active_contract_with_config
    setup = setup_active_contract_with_config(
        contract_overrides={"base_quantity": 1},
        config_components=[domestic, foreign],
    )
    cfg = setup["configuration"]
    bus = get_success_data(
        api.create_bus_unit(
            create_bus_unit_payload(setup["contract"]["id"], cfg["id"]), PP
        ),
    )
    bus = get_success_data(api.engineer_bus(bus["id"], CE))
    # Both components were verified by the pre-award audit, so the kit
    # completed at engineering time and production can run.
    from test_helpers import create_and_assign_slot
    slot = create_and_assign_slot(bus["id"])
    get_success_data(api.start_production(slot["id"], PP))
    get_success_data(api.complete_production(slot["id"], PP))

    resp = api.issue_certificate(
        bus["id"], create_certificate_payload(variant="COST_BASED"), CO
    )
    cert = validate_success(resp, expected_status=201)
    assert cert["domestic_content_pct"] == 25.0

    resp = api.submit_plant_inspection(bus["id"], PP)
    validate_error(resp, ApiErrorId.ERR_DOMESTIC_CONTENT_BELOW_THRESHOLD)


def test_pre_award_audit_completion_blocked_by_unverified_propulsion_docs(api):
    """PRD section 3.7: "The two audit types carry distinct completion
    preconditions, and completing an audit whose preconditions are unmet is
    rejected with `ERR_AUDIT_PRECONDITION`. A `PRE_AWARD` audit may be
    completed only while the contract is in `AWARDED` status, and only when at
    least one `FROZEN` bus configuration of the contract has every
    `PROPULSION`-category component on its standard component list in
    `VERIFIED` documentation status — this is where supplier documentation
    gates the audit rather than the content percentage."

    Design: Corner/errors/error_audit_precondition_unverified_docs
    """
    agency = create_agency()
    contract = create_draft_contract(agency["id"], base_quantity=1)
    component = create_component(name="Engine", category="PROPULSION")
    create_frozen_configuration(
        contract["id"], [component["id"]], contract["version"]
    )
    get_success_data(api.award_contract(contract["id"], PO))
    resp = api.create_audit_record(
        create_audit_record_payload(contract["id"]), AUD
    )
    audit = get_success_data(resp)

    resp = api.complete_audit(audit["id"], AUD)
    validate_error(resp, ApiErrorId.ERR_AUDIT_PRECONDITION)
    audit = get_success_data(api.get_audit_record(audit["id"], AUD))
    assert audit["status"] == "OPEN"


def test_freeze_with_stale_contract_version_rejected(api):
    """PRD section 2.7: "Exercising an option order and freezing a bus
    configuration each require the request to carry
    `expected_contract_version`, a non-optional field containing the client
    last observed `version` of the parent `Contract`. If the contract's
    current `version` does not match the supplied value — because an
    intervening award, activation, sibling option exercise, or sibling freeze
    advanced it — the write is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD section 3.3: "Both of these writes, when they succeed, themselves
    increment the parent contract's `version` by one" — see section 2.7:
    "Both of these writes, when they succeed, themselves increment the parent
    contract's `version` by one, as do the award and activation transitions."

    Design: Corner/errors/error_stale_version_on_freeze
    """
    agency = create_agency()
    contract = create_draft_contract(agency["id"], base_quantity=1)
    component = create_component(name="Engine", category="PROPULSION")
    # Sibling freeze bumps the contract version.
    create_frozen_configuration(
        contract["id"], [component["id"]], contract["version"]
    )
    # Second configuration, still carrying the pre-sibling version.
    resp = api.create_bus_configuration(
        create_bus_configuration_payload(
            contract["id"], [component["id"]], propulsion_type="CNG",
            seating_layout={"rows": 9},
        ),
        CE,
    )
    cfg = get_success_data(resp)
    get_success_data(api.submit_review_configuration(cfg["id"], CE))
    resp = api.freeze_configuration(
        cfg["id"], {"expected_contract_version": contract["version"]}, CE
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
