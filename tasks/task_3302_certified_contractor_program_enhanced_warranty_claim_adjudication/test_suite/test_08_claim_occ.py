"""OCC corner tests on claim adjudication."""
from test_helpers import (
    ApiErrorId,
    adjudicate,
    file_claim_with_photos,
    get_remedy,
    get_success_data,
    setup_active_registration,
    validate_error,
    validate_success,
)


def test_occ_stale_claim_version_adjudicate_returns_412(api, program_admin_headers, claimant_headers):
    """PRD §2.7: "Adjudicating a claim requires the request to carry
    `expected_claim_version`, equal to the claim's current `version` as last observed
    by the caller; if the claim's version has advanced since that observation — for
    example because an evidence submission or the automatic transition into evidence
    review incremented it — the adjudication is rejected with `ERR_STALE_CLAIM_VERSION`
    (HTTP 412), so a remedy allocation is never computed from a claim the adjudicator
    has not seen."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_claim_version_adjudicate_returns_412
    """
    ctx = setup_active_registration(tier="BRONZE")
    reg = ctx["registration"]
    claim = get_success_data(api.create_warranty_claim(
        {"registration_id": reg["id"], "description": "c", "claim_labor_cost_cents": 1000}, claimant_headers))
    stale_v = claim["version"]
    get_success_data(api.add_claim_evidence(claim["id"], {"evidence_type": "PHOTO", "note": "x"}, claimant_headers))
    get_success_data(api.add_claim_evidence(claim["id"], {"evidence_type": "PHOTO", "note": "y"}, claimant_headers))
    resp = api.adjudicate_claim(
        claim["id"], {"determination": "MANUFACTURER_DEFECT", "expected_claim_version": stale_v},
        program_admin_headers)
    validate_error(resp, ApiErrorId.ERR_STALE_CLAIM_VERSION)
    now = get_success_data(api.get_warranty_claim(claim["id"], program_admin_headers))
    assert now["status"] == "EVIDENCE_REVIEW"
    assert get_remedy(claim["id"]) == []


def test_occ_fresh_claim_version_adjudicate_succeeds(api, program_admin_headers, claimant_headers):
    """PRD §2.7: "Adjudicating a claim requires the request to carry
    `expected_claim_version`, equal to the claim's current `version` as last observed
    by the caller..." PRD §3.6: "Any other determination resolves the claim: it moves
    to `RESOLVED`, and the system computes and persists a remedy allocation in
    `ACTIVE` status..."

    Design: Corner/cross_cutting_complexity_layers/occ_fresh_claim_version_adjudicate_succeeds
    """
    ctx = setup_active_registration(tier="BRONZE")
    reg = ctx["registration"]
    info = file_claim_with_photos(reg["id"], claim_labor_cost_cents=1000, file_at="2026-09-20", description="c")
    claim = info["claim"]
    fresh = get_success_data(api.get_warranty_claim(claim["id"], program_admin_headers))
    resp = api.adjudicate_claim(
        claim["id"], {"determination": "MANUFACTURER_DEFECT", "expected_claim_version": fresh["version"]},
        program_admin_headers)
    data = validate_success(resp)
    assert data["status"] == "RESOLVED"
