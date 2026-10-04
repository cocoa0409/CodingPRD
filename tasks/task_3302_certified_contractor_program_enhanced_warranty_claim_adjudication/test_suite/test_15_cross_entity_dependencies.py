"""Difficulty queue A: cross-entity state dependencies."""
from test_helpers import (
    ApiErrorId,
    get_success_data,
    make_certified_contractor,
    make_contractor_headers,
    set_clock,
    setup_active_registration,
    suspend_contractor_via_complaints,
    validate_error,
)


def test_registration_activate_requires_active_certification(api, program_admin_headers, claimant_headers):
    """PRD §3.3: "The activation re-confirms that the backing certification is still
    `ACTIVE` and that the `install_date` remains on or before the certification's
    `valid_until` (else `ERR_CERTIFICATION_NOT_ACTIVE`)..."

    Design: Difficulty/cross_entity_state_dependency/registration_activate_requires_active_certification
    """
    from test_helpers import (
        add_catalog_items,
        add_required_components,
        create_registration_payload,
    )

    set_clock("2026-09-01T00:00:00Z")
    ctx = make_certified_contractor(tier="BRONZE")
    contractor, cert = ctx["contractor"], ctx["certification"]
    ch = make_contractor_headers(contractor["id"])
    skus = add_catalog_items()
    set_clock("2026-09-10T00:00:00Z")
    reg = get_success_data(api.create_warranty_registration(
        create_registration_payload(certification_id=cert["id"], install_date="2026-09-10"), ch))
    add_required_components(reg["id"], contractor["id"], skus, line_cents=25000)
    # drive the contractor (and thus the certification) to SUSPENDED
    suspend_contractor_via_complaints(contractor["id"])
    cert_now = get_success_data(api.get_certification(cert["id"], program_admin_headers))
    assert cert_now["status"] == "SUSPENDED"
    resp = api.activate_warranty_registration(reg["id"], program_admin_headers)
    validate_error(resp, ApiErrorId.ERR_CERTIFICATION_NOT_ACTIVE)
    reg_now = get_success_data(api.get_warranty_registration(reg["id"], program_admin_headers))
    assert reg_now["status"] == "DRAFT"


def test_registration_create_rejected_when_certification_suspended(api, program_admin_headers, claimant_headers):
    """PRD §3.3: "The referenced certification must be `ACTIVE` and the `install_date`
    must fall within its validity — that is, on or before the certification's
    `valid_until` — or the creation is refused with `ERR_CERTIFICATION_NOT_ACTIVE`
    (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/registration_activate_requires_active_certification
    """
    from test_helpers import create_registration_payload

    set_clock("2026-09-01T00:00:00Z")
    ctx = make_certified_contractor(tier="BRONZE")
    contractor, cert = ctx["contractor"], ctx["certification"]
    ch = make_contractor_headers(contractor["id"])
    suspend_contractor_via_complaints(contractor["id"])
    resp = api.create_warranty_registration(
        create_registration_payload(certification_id=cert["id"], install_date="2026-09-10"), ch)
    validate_error(resp, ApiErrorId.ERR_CERTIFICATION_NOT_ACTIVE)


def test_claim_intake_requires_active_registration(api, program_admin_headers, claimant_headers):
    """PRD §3.4: "Filing against a registration in any other state is refused with
    `ERR_REGISTRATION_NOT_ACTIVE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/claim_intake_requires_active_registration
    """
    from test_helpers import create_registration_payload

    set_clock("2026-09-01T00:00:00Z")
    ctx = make_certified_contractor(tier="BRONZE")
    contractor, cert = ctx["contractor"], ctx["certification"]
    ch = make_contractor_headers(contractor["id"])
    set_clock("2026-09-10T00:00:00Z")
    reg = get_success_data(api.create_warranty_registration(
        create_registration_payload(certification_id=cert["id"], install_date="2026-09-10"), ch))
    # registration left in DRAFT
    resp = api.create_warranty_claim(
        {"registration_id": reg["id"], "description": "premature claim", "claim_labor_cost_cents": 1000},
        claimant_headers)
    validate_error(resp, ApiErrorId.ERR_REGISTRATION_NOT_ACTIVE)
    claims = get_success_data(api.list_registration_claims(reg["id"], program_admin_headers))
    assert claims == []


def test_claim_intake_rejected_on_void_registration(api, program_admin_headers, claimant_headers):
    """PRD §3.4: "Filing against a registration in any other state is refused with
    `ERR_REGISTRATION_NOT_ACTIVE` (HTTP 409)." PRD §3.3: "A registration's only other
    transition is to `VOID`, terminal, which happens exclusively through the
    contractor revocation cascade of §3.7."

    Design: Difficulty/cross_entity_state_dependency/claim_intake_requires_active_registration
    """
    from test_helpers import create_complaint_payload

    ctx = setup_active_registration(tier="BRONZE")
    contractor, reg = ctx["contractor"], ctx["registration"]
    set_clock("2026-09-01T00:00:00Z")
    ids = []
    for _ in range(8):
        c = get_success_data(api.create_complaint(
            create_complaint_payload(contractor_id=contractor["id"], category="WORKMANSHIP"), claimant_headers))
        ids.append(c["id"])
    for cid in ids:
        get_success_data(api.substantiate_complaint(cid, program_admin_headers))
    reg_now = get_success_data(api.get_warranty_registration(reg["id"], program_admin_headers))
    assert reg_now["status"] == "VOID"
    resp = api.create_warranty_claim(
        {"registration_id": reg["id"], "description": "too late", "claim_labor_cost_cents": 1000},
        claimant_headers)
    validate_error(resp, ApiErrorId.ERR_REGISTRATION_NOT_ACTIVE)
