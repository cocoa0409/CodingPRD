"""Composite setup helpers.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints, because the server is restarted (empty database) before each test.
Setup calls use the lenient get_success_data() so failures surface as clear
"Setup failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_agency_payload,
    create_audit_record_payload,
    create_bus_configuration_payload,
    create_bus_unit_payload,
    create_component_payload,
    create_contract_payload,
    create_production_slot_payload,
)
from .test_users import TEST_USERS

ADMIN = TEST_USERS["platform_admin_headers"]
PO = TEST_USERS["procurement_officer_headers"]
CE = TEST_USERS["config_engineer_headers"]
CO = TEST_USERS["compliance_officer_headers"]
INSP = TEST_USERS["agency_inspector_headers"]
PP = TEST_USERS["production_planner_headers"]
AUD = TEST_USERS["auditor_headers"]
WA = TEST_USERS["warranty_admin_headers"]


def create_agency(**overrides) -> dict:
    """Create an agency. Returns the agency dict."""
    resp = api_client.create_agency(create_agency_payload(**overrides), ADMIN)
    return get_success_data(resp)


def create_component(**overrides) -> dict:
    """Register a component (starts with supplier_doc_status MISSING)."""
    resp = api_client.create_component(create_component_payload(**overrides), CO)
    return get_success_data(resp)


def submit_and_verify_component(component_id, submitter="sup-1", verifier="co-1"):
    """Drive one component MISSING -> SUBMITTED -> VERIFIED with segregated ids."""
    resp = api_client.submit_supplier_docs(
        component_id, _supplier_headers(submitter)
    )
    get_success_data(resp)
    resp = api_client.verify_docs(component_id, _officer_headers(verifier))
    return get_success_data(resp)


def _supplier_headers(user_id):
    from prd_bench_local_runner.testing import build_user_headers

    return build_user_headers(user_id, "SupplierRep")


def _officer_headers(user_id):
    from prd_bench_local_runner.testing import build_user_headers

    return build_user_headers(user_id, "ComplianceOfficer")


def create_draft_contract(agency_id, **overrides) -> dict:
    """Create a contract in DRAFT."""
    resp = api_client.create_contract(create_contract_payload(agency_id, **overrides), PO)
    return get_success_data(resp)


def create_frozen_configuration(contract_id, component_ids, expected_contract_version,
                                **overrides) -> dict:
    """Create a configuration and drive it DRAFT -> ENGINEERING_REVIEW -> FROZEN."""
    resp = api_client.create_bus_configuration(
        create_bus_configuration_payload(contract_id, component_ids, **overrides), CE
    )
    cfg = get_success_data(resp)
    resp = api_client.submit_review_configuration(cfg["id"], CE)
    get_success_data(resp)
    resp = api_client.freeze_configuration(
        cfg["id"], {"expected_contract_version": expected_contract_version}, CE
    )
    return get_success_data(resp)


def award_contract(contract_id) -> dict:
    resp = api_client.award_contract(contract_id, PO)
    return get_success_data(resp)


def complete_pre_award_audit(contract_id, component_ids, auditor_id="aud-1",
                             submitter="sup-1", verifier="co-1",
                             verify_components=True) -> dict:
    """Open a PRE_AWARD audit, verify the given components' docs, complete it.

    Returns the COMPLETED audit record. With ``verify_components=False`` the
    components are left untouched (useful when the frozen configuration's
    PROPULSION components are already verified through another path and the
    remaining kit components must stay undocumented).
    """
    resp = api_client.create_audit_record(
        create_audit_record_payload(contract_id, auditor_id=auditor_id), AUD
    )
    audit = get_success_data(resp)
    if verify_components:
        for cid in component_ids:
            submit_and_verify_component(cid, submitter=submitter, verifier=verifier)
    resp = api_client.complete_audit(audit["id"], AUD)
    return get_success_data(resp)


def setup_active_contract(agency_id=None, agency_overrides=None, contract_overrides=None,
                          component_overrides=None, propulsion_type="DIESEL",
                          seating_layout=None, accessibility_features=None,
                          auditor_id="aud-1"):
    """Agency + contract + one verified component + FROZEN configuration +
    award + passing PRE_AWARD audit + activate.

    Returns a dict with keys: agency, contract, components (list),
    configuration, contract_version (current Contract.version after activation).
    """
    agency_overrides = agency_overrides or {}
    contract_overrides = contract_overrides or {}
    component_overrides = component_overrides or {}

    agency = create_agency(**agency_overrides) if agency_id is None else None
    ag_id = agency["id"] if agency is not None else agency_id

    contract = create_draft_contract(ag_id, **contract_overrides)
    component = create_component(**component_overrides)

    cfg_kwargs = {}
    if seating_layout is not None:
        cfg_kwargs["seating_layout"] = seating_layout
    if accessibility_features is not None:
        cfg_kwargs["accessibility_features"] = accessibility_features
    config = create_frozen_configuration(
        contract["id"], [component["id"]], contract["version"],
        propulsion_type=propulsion_type, **cfg_kwargs,
    )

    award_contract(contract["id"])
    audit = complete_pre_award_audit(
        contract["id"], [component["id"]], auditor_id=auditor_id
    )
    resp = api_client.activate_contract(contract["id"], PO)
    activated = get_success_data(resp)

    return {
        "agency": agency if agency is not None else get_success_data(
            api_client.get_agency(ag_id, ADMIN)
        ),
        "contract": activated,
        "audit": audit,
        "components": [component],
        "configuration": config,
        "contract_version": activated["version"],
    }


def setup_active_contract_with_config(agency_id=None, agency_overrides=None,
                                      contract_overrides=None,
                                      config_components=None,
                                      propulsion_type="DIESEL",
                                      seating_layout=None,
                                      accessibility_features=None,
                                      auditor_id="aud-1",
                                      verify_components=True):
    """Like setup_active_contract but freezes a configuration carrying an
    explicit component list *before* award/activation.

    PRD section 3.3 allows submit-review only while the parent contract is in
    DRAFT or AWARDED status, so a configuration carrying a custom kit must be
    created and frozen before the contract reaches ACTIVE. `config_components`
    is a list of already-created component dicts (or None for the default
    single verified component). With ``verify_components=False`` the listed
    components are left in their current documentation status; the caller
    must then have arranged the pre-award audit's PROPULSION-verified
    precondition some other way.
    """
    agency_overrides = agency_overrides or {}
    contract_overrides = contract_overrides or {}

    agency = create_agency(**agency_overrides) if agency_id is None else None
    ag_id = agency["id"] if agency is not None else agency_id

    contract = create_draft_contract(ag_id, **contract_overrides)
    if config_components is None:
        components = [create_component()]
    else:
        components = list(config_components)

    cfg_kwargs = {}
    if seating_layout is not None:
        cfg_kwargs["seating_layout"] = seating_layout
    if accessibility_features is not None:
        cfg_kwargs["accessibility_features"] = accessibility_features
    config = create_frozen_configuration(
        contract["id"], [c["id"] for c in components], contract["version"],
        propulsion_type=propulsion_type, **cfg_kwargs,
    )

    award_contract(contract["id"])
    audit = complete_pre_award_audit(
        contract["id"], [c["id"] for c in components], auditor_id=auditor_id,
        verify_components=verify_components,
    )
    resp = api_client.activate_contract(contract["id"], PO)
    activated = get_success_data(resp)

    return {
        "agency": agency if agency is not None else get_success_data(
            api_client.get_agency(ag_id, ADMIN)
        ),
        "contract": activated,
        "audit": audit,
        "components": components,
        "configuration": config,
        "contract_version": activated["version"],
    }


def create_engineered_bus(contract_id, configuration_id, **overrides) -> dict:
    """Create a bus under an ACTIVE contract and engineer it (ORDERED -> ENGINEERED).

    Engineering also creates the bus's parts kit in STAGING.
    """
    resp = api_client.create_bus_unit(
        create_bus_unit_payload(contract_id, configuration_id, **overrides), PP
    )
    bus = get_success_data(resp)
    resp = api_client.engineer_bus(bus["id"], CE)
    return get_success_data(resp)


def create_and_assign_slot(bus_id, **slot_overrides) -> dict:
    """Create an OPEN slot and assign an ENGINEERED bus to it."""
    resp = api_client.create_production_slot(
        create_production_slot_payload(**slot_overrides), PP
    )
    slot = get_success_data(resp)
    resp = api_client.assign_slot(slot["id"], {"bus_unit_id": bus_id}, PP)
    return get_success_data(resp)


def build_bus_to_built(setup, slot_overrides=None, **bus_overrides) -> dict:
    """From a setup_active_contract() result, drive a bus to BUILT:
    create + engineer + slot assign + start production + complete production.

    Requires every kit component to be VERIFIED before engineering so the kit
    auto-completes and the slot becomes KITTED.
    """
    slot_overrides = slot_overrides or {}
    bus = create_engineered_bus(
        setup["contract"]["id"], setup["configuration"]["id"], **bus_overrides
    )
    slot = create_and_assign_slot(bus["id"], **slot_overrides)
    resp = api_client.start_production(slot["id"], PP)
    get_success_data(resp)
    resp = api_client.complete_production(slot["id"], PP)
    get_success_data(resp)
    bus = get_success_data(api_client.get_bus_unit(bus["id"], PP))
    return bus


def issue_certificate(bus_id, **overrides) -> dict:
    from .factories import create_certificate_payload

    resp = api_client.issue_certificate(
        bus_id, create_certificate_payload(**overrides), CO
    )
    return get_success_data(resp)


def build_bus_to_plant_inspection(setup, slot_overrides=None,
                                  certificate_overrides=None, **bus_overrides) -> dict:
    """Drive a bus to PLANT_INSPECTION (BUILT + certificate + submit)."""
    certificate_overrides = certificate_overrides or {}
    bus = build_bus_to_built(setup, slot_overrides=slot_overrides, **bus_overrides)
    issue_certificate(bus["id"], **certificate_overrides)
    resp = api_client.submit_plant_inspection(bus["id"], PP)
    return get_success_data(resp)


def build_bus_to_delivered(setup, slot_overrides=None,
                           certificate_overrides=None, **bus_overrides) -> dict:
    """Drive a bus to DELIVERED: plant inspection + PLANT PASS + deliver."""
    bus = build_bus_to_plant_inspection(
        setup, slot_overrides=slot_overrides,
        certificate_overrides=certificate_overrides, **bus_overrides,
    )
    resp = api_client.create_inspection_record(
        {
            "bus_unit_id": bus["id"],
            "inspection_type": "PLANT",
            "inspector_id": "insp-1",
            "result": "PASS",
        },
        INSP,
    )
    get_success_data(resp)
    resp = api_client.deliver_bus(bus["id"], PP)
    return get_success_data(resp)


def build_bus_to_accepted(setup, slot_overrides=None, certificate_overrides=None,
                          **bus_overrides) -> dict:
    """Drive a bus to ACCEPTED (delivered + agency accept)."""
    bus = build_bus_to_delivered(
        setup, slot_overrides=slot_overrides,
        certificate_overrides=certificate_overrides, **bus_overrides,
    )
    resp = api_client.accept_bus(bus["id"], INSP)
    return get_success_data(resp)


def setup_accepted_bus(agency_overrides=None, contract_overrides=None,
                       component_overrides=None, propulsion_type="DIESEL",
                       slot_overrides=None, certificate_overrides=None):
    """Full stack: ACTIVE contract + one ACCEPTED bus. Returns the setup dict
    augmented with the accepted bus under key 'bus'."""
    setup = setup_active_contract(
        agency_overrides=agency_overrides,
        contract_overrides=contract_overrides,
        component_overrides=component_overrides,
        propulsion_type=propulsion_type,
    )
    bus = build_bus_to_accepted(
        setup, slot_overrides=slot_overrides,
        certificate_overrides=certificate_overrides,
    )
    setup["bus"] = bus
    return setup
