"""Registration component and catalog corner tests."""
from test_helpers import (
    ApiErrorId,
    create_registration_component_payload,
    make_contractor_headers,
    setup_active_registration,
    validate_error,
    validate_success,
)
from test_helpers import api_client as _unused  # noqa: F401  (ensure helpers import path)


def _setup_draft_registration(api, program_admin_headers, claimant_headers):
    """BRONZE certified contractor with a DRAFT registration (no components yet)."""
    from test_helpers import (
        add_catalog_items,
        create_registration_payload,
        get_success_data,
        make_certified_contractor,
        set_clock,
    )

    set_clock("2026-09-01T00:00:00Z")
    ctx = make_certified_contractor(tier="BRONZE")
    contractor, cert = ctx["contractor"], ctx["certification"]
    ch = make_contractor_headers(contractor["id"])
    set_clock("2026-09-10T00:00:00Z")
    reg = get_success_data(
        api.create_warranty_registration(
            create_registration_payload(certification_id=cert["id"], install_date="2026-09-10"), ch
        )
    )
    return contractor, cert, reg, ch


def test_registration_component_duplicate_type_rejected(api, program_admin_headers, claimant_headers):
    """PRD §3.3: "A registration may hold at most one line of any given `component_type`;
    a second line duplicating a type already present is refused with
    `ERR_DUPLICATE_COMPONENT_TYPE` (HTTP 409)."

    Design: Corner/entities/registration_component_duplicate_type_rejected
    """
    from test_helpers import get_success_data, set_clock
    from test_helpers.factories import create_catalog_item_payload

    contractor, cert, reg, ch = _setup_draft_registration(api, program_admin_headers, claimant_headers)
    get_success_data(api.create_component_catalog_item(
        create_catalog_item_payload(sku="SH-G", component_type="SHINGLE", manufacturer="GAF"), program_admin_headers))
    get_success_data(api.create_component_catalog_item(
        create_catalog_item_payload(sku="SH-G2", component_type="SHINGLE", manufacturer="GAF"), program_admin_headers))
    get_success_data(api.create_registration_component(
        create_registration_component_payload(registration_id=reg["id"], catalog_sku="SH-G", material_cost_cents=25000), ch))

    resp = api.create_registration_component(
        create_registration_component_payload(registration_id=reg["id"], catalog_sku="SH-G2", material_cost_cents=25000), ch)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_COMPONENT_TYPE)


def test_component_unknown_catalog_sku_returns_not_found(api, program_admin_headers, claimant_headers):
    """PRD §3.3: "The `catalog_sku` must match an existing catalog item or the line is
    refused with `ERR_CATALOG_ITEM_NOT_FOUND` (HTTP 404)."

    Design: Corner/errors/component_unknown_catalog_sku_returns_not_found
    """
    contractor, cert, reg, ch = _setup_draft_registration(api, program_admin_headers, claimant_headers)
    resp = api.create_registration_component(
        create_registration_component_payload(registration_id=reg["id"], catalog_sku="NOPE", material_cost_cents=100), ch)
    validate_error(resp, ApiErrorId.ERR_CATALOG_ITEM_NOT_FOUND)


def test_claim_evidence_invalid_enum_rejected(api, program_admin_headers, claimant_headers):
    """PRD §3.4: "Each evidence submission — by the `Claimant` or a `ProgramAdmin` —
    appends one entry carrying an `evidence_type` of `PHOTO`, `CORE_SAMPLE`, or
    `DOCUMENT` plus a free-text `note` to the claim's `evidence` list."
    PRD §2.8: "Request-shape validation follows (`ERR_INVALID_REQUEST`)..."

    Design: Corner/entities/claim_evidence_invalid_enum_rejected
    """
    from test_helpers import file_claim_with_photos

    ctx = setup_active_registration(tier="BRONZE")
    claim = ctx_claim = None
    claim_info = file_claim_with_photos(ctx["registration"]["id"], claim_labor_cost_cents=1000,
                                        file_at="2026-09-20", description="c")
    claim = claim_info["claim"]
    resp = api.add_claim_evidence(claim["id"], {"evidence_type": "VIDEO", "note": "clip"}, claimant_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_activate_registration_missing_required_component_rejected(api, program_admin_headers, claimant_headers):
    """PRD §3.3: "The bill of materials must then contain each of the four required
    component types — `SHINGLE`, `UNDERLAYMENT`, `STARTER`, and `RIDGE_CAP` — present
    exactly once each; a missing or duplicated required type is refused with
    `ERR_MISSING_REQUIRED_COMPONENT` (HTTP 422)."

    Design: Corner/validations/activate_registration_missing_required_component_rejected
    """
    from test_helpers import add_required_components, get_success_data, set_clock
    from test_helpers.factories import create_catalog_item_payload

    contractor, cert, reg, ch = _setup_draft_registration(api, program_admin_headers, claimant_headers)
    skus = {}
    for ctype, sku in (("SHINGLE", "SH-G"), ("UNDERLAYMENT", "UN-G"), ("STARTER", "ST-G"), ("RIDGE_CAP", "RC-G")):
        get_success_data(api.create_component_catalog_item(
            create_catalog_item_payload(sku=sku, component_type=ctype, manufacturer="GAF"), program_admin_headers))
        skus[ctype] = sku
    # add only 3 of the 4 required types (RIDGE_CAP missing)
    for ctype in ("SHINGLE", "UNDERLAYMENT", "STARTER"):
        get_success_data(api.create_registration_component(
            create_registration_component_payload(registration_id=reg["id"], catalog_sku=skus[ctype],
                                                  material_cost_cents=25000), ch))
    resp = api.activate_warranty_registration(reg["id"], program_admin_headers)
    validate_error(resp, ApiErrorId.ERR_MISSING_REQUIRED_COMPONENT)
    # add the missing RIDGE_CAP and activate succeeds
    get_success_data(api.create_registration_component(
        create_registration_component_payload(registration_id=reg["id"], catalog_sku=skus["RIDGE_CAP"],
                                              material_cost_cents=25000), ch))
    ok = api.activate_warranty_registration(reg["id"], program_admin_headers)
    data = validate_success(ok)
    assert data["status"] == "ACTIVE"
