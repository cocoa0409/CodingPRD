"""Claim and inspection state machine corner tests."""
from test_helpers import (
    ApiErrorId,
    file_claim_with_photos,
    get_success_data,
    make_contractor_headers,
    make_inspector_headers,
    setup_active_registration,
    validate_error,
    validate_success,
)


def test_claim_evidence_auto_transition_at_second_photo(api, program_admin_headers, claimant_headers):
    """PRD §3.4: "When a submission raises `photo_count` to at least 2 while the claim
    is `SUBMITTED`, the claim automatically advances from `SUBMITTED` to
    `EVIDENCE_REVIEW`; claims already past `SUBMITTED` simply continue to accumulate
    evidence."

    Design: Corner/state_machines/claim_evidence_auto_transition_at_second_photo
    """
    ctx = setup_active_registration(tier="BRONZE")
    reg = ctx["registration"]
    claim = get_success_data(api.create_warranty_claim(
        {"registration_id": reg["id"], "description": "c", "claim_labor_cost_cents": 1000}, claimant_headers))
    r1 = api.add_claim_evidence(claim["id"], {"evidence_type": "PHOTO", "note": "one"}, claimant_headers)
    d1 = validate_success(r1, expected_status=201)
    assert d1["status"] == "SUBMITTED"
    assert d1["photo_count"] == 1
    r2 = api.add_claim_evidence(claim["id"], {"evidence_type": "PHOTO", "note": "two"}, claimant_headers)
    d2 = validate_success(r2, expected_status=201)
    assert d2["status"] == "EVIDENCE_REVIEW"
    assert d2["photo_count"] == 2


def test_claim_denied_terminal_lockdown_rejected(api, program_admin_headers, claimant_headers):
    """PRD §3.6: "A `NO_DEFECT` determination denies the claim: it moves to `DENIED`,
    terminal, no remedy allocation is created, and the claim's `version` increments."
    PRD §3.4: "Evidence may be appended while the claim is in any non-terminal state."

    Design: Corner/state_machines/claim_denied_terminal_lockdown_rejected
    """
    ctx = setup_active_registration(tier="BRONZE")
    reg = ctx["registration"]
    info = file_claim_with_photos(reg["id"], claim_labor_cost_cents=1000, file_at="2026-09-20", description="c")
    claim, cv = info["claim"], info["version"]
    resp = api.adjudicate_claim(claim["id"], {"determination": "NO_DEFECT", "expected_claim_version": cv}, program_admin_headers)
    data = validate_success(resp)
    assert data["status"] == "DENIED"
    remedies = get_success_data(api.list_remedy_allocations(claim["id"], program_admin_headers))
    assert remedies == []
    late = api.add_claim_evidence(claim["id"], {"evidence_type": "PHOTO", "note": "late"}, claimant_headers)
    validate_error(late, ApiErrorId.ERR_INVALID_STATE)


def test_inspection_order_complete_before_schedule_returns_invalid_state(api, program_admin_headers, claimant_headers):
    """PRD §3.5: "Completion moves the order from `SCHEDULED` to `COMPLETED` — its
    terminal state — and increments the order's `version`."
    PRD §2.8: "State-eligibility checks come next — that the requested transition
    exists from the entity's current state (`ERR_INVALID_STATE`)..."

    Design: Corner/state_machines/inspection_order_complete_before_schedule_returns_invalid_state
    """
    ctx = setup_active_registration(tier="BRONZE")
    reg = ctx["registration"]
    info = file_claim_with_photos(reg["id"], claim_labor_cost_cents=1000, file_at="2026-09-20", description="c")
    claim = info["claim"]
    order = get_success_data(api.request_inspection(claim["id"], program_admin_headers))
    resp = api.complete_inspection_order(order["id"], {"findings": "f", "confirms_defect": True},
                                         make_inspector_headers("INSP-1"))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_reinstate_active_certification_returns_invalid_state(api, program_admin_headers):
    """PRD §3.2: "A `SUSPENDED` certification returns to `ACTIVE` only through an
    individual reinstatement by a `ProgramAdmin`..." PRD §2.8: "State-eligibility
    checks come next — that the requested transition exists from the entity's current
    state (`ERR_INVALID_STATE`)..."

    Design: Corner/state_machines/reinstate_active_certification_returns_invalid_state
    """
    from test_helpers import make_certified_contractor, set_clock

    set_clock("2026-09-01T00:00:00Z")
    ctx = make_certified_contractor(tier="BRONZE")
    cert = ctx["certification"]
    assert cert["status"] == "ACTIVE"
    resp = api.reinstate_certification(cert["id"], program_admin_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_registration_voided_on_contractor_revocation_cascade(api, program_admin_headers, claimant_headers):
    """PRD §3.7: "The revocation cascade is wider: every certification of the
    contractor in `ACTIVE` or `SUSPENDED` moves to `REVOKED`, every warranty
    registration reached through those certifications that is currently `ACTIVE`
    moves to `VOID`, and every `ASSIGNED` lead assignment returns to `RETURNED` with
    the distributor pool recomputed..."

    Design: Corner/state_machines/registration_voided_on_contractor_revocation_cascade
    """
    from test_helpers import create_complaint_payload, set_clock

    ctx = setup_active_registration(tier="BRONZE")
    contractor, cert, reg = ctx["contractor"], ctx["certification"], ctx["registration"]
    set_clock("2026-09-01T00:00:00Z")
    ids = []
    for _ in range(8):
        c = get_success_data(api.create_complaint(
            create_complaint_payload(contractor_id=contractor["id"], category="WORKMANSHIP"), claimant_headers))
        ids.append(c["id"])
    for cid in ids[:7]:
        get_success_data(api.substantiate_complaint(cid, program_admin_headers))
    get_success_data(api.substantiate_complaint(ids[7], program_admin_headers))

    cnow = get_success_data(api.get_contractor(contractor["id"], program_admin_headers))
    assert cnow["status"] == "REVOKED"
    cert_now = get_success_data(api.get_certification(cert["id"], program_admin_headers))
    assert cert_now["status"] == "REVOKED"
    reg_now = get_success_data(api.get_warranty_registration(reg["id"], program_admin_headers))
    assert reg_now["status"] == "VOID"
