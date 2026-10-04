"""Corner tests: RBAC denials and segregation of duties."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_agency,
    create_component,
    create_draft_contract,
    create_production_slot_payload,
    get_success_data,
    make_compliance_officer_headers,
    make_supplier_rep_headers,
    validate_error,
    validate_success,
)

CO = TEST_USERS["compliance_officer_headers"]
INSP = TEST_USERS["agency_inspector_headers"]


def test_supplier_rep_cannot_verify_docs(api):
    """PRD section 2.1: "A request whose role is not permitted for the target
    endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD section 3.4: "A `ComplianceOfficer` then either verifies the
    documentation, moving `SUBMITTED` → `VERIFIED`, or rejects it, moving
    `SUBMITTED` → `REJECTED` — and in both cases the acting officer's user id
    must differ from the submitter's, with a same-user attempt rejected as
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/supplier_rep_cannot_verify_docs
    """
    component = create_component(name="Axle", category="AXLE",
                                 unit_cost_cents=300000)
    get_success_data(
        api.submit_supplier_docs(component["id"],
                                 make_supplier_rep_headers("sup-1")),
    )
    resp = api.verify_docs(component["id"], make_supplier_rep_headers("sup-9"))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_agency_inspector_cannot_create_production_slots(api):
    """PRD section 2.1: "A request whose role is not permitted for the target
    endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/agency_inspector_cannot_manage_slots
    """
    resp = api.create_production_slot(create_production_slot_payload(), INSP)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_compliance_officer_cannot_award_contract(api):
    """PRD section 2.1: "A request whose role is not permitted for the target
    endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD section 3.2: "The `ProcurementOfficer` may award only while the agency
    is `ACTIVE`, the `base_quantity` is at least 1, and at least one bus
    configuration engineered under the contract has reached `FROZEN` status."

    Design: Corner/rbac/compliance_officer_cannot_award_contract
    """
    agency = create_agency()
    contract = create_draft_contract(agency["id"], base_quantity=1)
    resp = api.award_contract(contract["id"], CO)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_same_user_submit_and_verify_segregated(api):
    """PRD section 2.6: "First, supplier documentation: the
    `ComplianceOfficer` who verifies or rejects a component's documentation
    must be a different user than the `SupplierRep` who submitted it."
    PRD section 2.6: "Any violation of these rules is rejected with
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 422)."

    Design: Corner/rbac/same_user_submit_and_verify_segregated
    """
    component = create_component(name="Axle", category="AXLE",
                                 unit_cost_cents=300000)
    get_success_data(
        api.submit_supplier_docs(component["id"],
                                 make_supplier_rep_headers("sup-1")),
    )
    # Same user id on the verify side: segregated.
    resp = api.verify_docs(component["id"],
                           make_compliance_officer_headers("sup-1"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    # A different officer verifies successfully.
    resp = api.verify_docs(component["id"],
                           make_compliance_officer_headers("co-1"))
    verified = validate_success(resp)
    assert verified["supplier_doc_status"] == "VERIFIED"
