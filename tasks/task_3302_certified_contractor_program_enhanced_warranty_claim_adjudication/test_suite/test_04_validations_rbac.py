"""Validation and error-path corner tests (existence, RBAC, temporal gates)."""
from test_helpers import (
    ApiErrorId,
    create_certification_payload,
    create_distributor_payload,
    create_lead_assignment_payload,
    get_success_data,
    make_certified_contractor,
    make_contractor_headers,
    make_distributor_headers,
    set_clock,
    setup_active_registration,
    validate_error,
    validate_success,
)


def test_existence_check_beats_state_check_on_adjudicate(api, program_admin_headers):
    """PRD §2.10: "Existence is established before any state or business rule of a
    deeper resource is evaluated, so a request against a nonexistent certification
    never surfaces a rule about the registration beneath it."

    Design: Corner/validations/existence_check_beats_state_check_on_adjudicate
    """
    # source a well-formed version value from a real create
    contractor = get_success_data(api.create_contractor(
        {"legal_name": "Ex Co", "license_number": "LIC-E1", "license_expiry": "2035-01-01",
         "insurance_expiry": "2035-01-01", "territory_codes": ["T1"]}, program_admin_headers))
    resp = api.adjudicate_claim(
        "11111111-2222-3333-4444-555555555555",
        {"determination": "MANUFACTURER_DEFECT", "expected_claim_version": contractor["version"]},
        program_admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_RESOURCE_NOT_FOUND)


def test_adjudicate_without_two_photos_returns_photo_error(api, program_admin_headers, claimant_headers):
    """PRD §3.6: "Second, no linked inspection order may remain in `REQUESTED` or
    `SCHEDULED` — adjudicating with inspection work outstanding is refused with
    `ERR_INSPECTION_INCOMPLETE` (HTTP 422)."

    Design: Corner/validations/adjudicate_without_two_photos_returns_photo_error
    """
    from test_helpers import file_claim_with_photos

    ctx = setup_active_registration(tier="BRONZE")
    reg = ctx["registration"]
    info = file_claim_with_photos(reg["id"], claim_labor_cost_cents=1000, file_at="2026-09-20", description="c")
    claim = info["claim"]
    get_success_data(api.request_inspection(claim["id"], program_admin_headers))
    fresh = get_success_data(api.get_warranty_claim(claim["id"], program_admin_headers))
    resp = api.adjudicate_claim(
        claim["id"], {"determination": "MANUFACTURER_DEFECT", "expected_claim_version": fresh["version"]},
        program_admin_headers)
    validate_error(resp, ApiErrorId.ERR_INSPECTION_INCOMPLETE)

    # completing the order unblocks adjudication
    from test_helpers import make_inspector_headers
    order = get_success_data(api.list_claim_inspection_orders(claim["id"], program_admin_headers))[0]
    get_success_data(api.schedule_inspection_order(order["id"], {"inspector_id": "INSP-1", "service_date": "2026-10-05"}, program_admin_headers))
    get_success_data(api.complete_inspection_order(order["id"], {"findings": "f", "confirms_defect": True}, make_inspector_headers("INSP-1")))
    fresh2 = get_success_data(api.get_warranty_claim(claim["id"], program_admin_headers))
    ok = api.adjudicate_claim(
        claim["id"], {"determination": "MANUFACTURER_DEFECT", "expected_claim_version": fresh2["version"]},
        program_admin_headers)
    data = validate_success(ok)
    assert data["status"] == "RESOLVED"


def test_lead_assignment_end_before_start_rejected(api, program_admin_headers):
    """PRD §3.8: "...a half-open service window from `start_date` (inclusive) to
    `end_date` (exclusive, and strictly later than `start_date`, or the request is
    malformed with `ERR_INVALID_REQUEST`)."

    Design: Corner/entities/lead_assignment_end_before_start_rejected
    """
    dist = get_success_data(api.create_distributor(
        create_distributor_payload(name="Dist V", territory_codes=["T1"], lead_pool_total=1), program_admin_headers))
    resp = api.create_lead_assignment(
        create_lead_assignment_payload(
            distributor_id=dist["id"],
            contractor_id="11111111-2222-3333-4444-555555555555",
            start_date="2026-11-01",
            end_date="2026-10-01",
        ),
        make_distributor_headers(dist["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_missing_role_header_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or presenting a role string outside
    this set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/errors/missing_role_header_unauthenticated
    """
    resp = api._request("GET", "/program/contractors/11111111-2222-3333-4444-555555555555", headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_claimant_cannot_adjudicate_claim(api, program_admin_headers, claimant_headers):
    """PRD §2.1: "A request whose role is not permitted for the target endpoint is
    rejected with `ERR_FORBIDDEN` (HTTP 403); the permitted roles for every endpoint
    appear in §4." (§4: adjudicate is ProgramAdmin-only.)

    Design: Corner/rbac/claimant_cannot_adjudicate_claim
    """
    contractor = get_success_data(api.create_contractor(
        {"legal_name": "Any Co", "license_number": "LIC-AN", "license_expiry": "2035-01-01",
         "insurance_expiry": "2035-01-01", "territory_codes": ["T1"]}, program_admin_headers))
    resp = api.adjudicate_claim(
        "11111111-2222-3333-4444-555555555555",
        {"determination": "MANUFACTURER_DEFECT", "expected_claim_version": contractor["version"]},
        claimant_headers,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_contractor_cannot_substantiate_complaint(api, program_admin_headers):
    """PRD §2.1: "A request whose role is not permitted for the target endpoint is
    rejected with `ERR_FORBIDDEN` (HTTP 403)..." (§4: substantiate is ProgramAdmin-only.)

    Design: Corner/rbac/contractor_cannot_substantiate_complaint
    """
    contractor = get_success_data(api.create_contractor(
        {"legal_name": "RBAC Co", "license_number": "LIC-RB", "license_expiry": "2035-01-01",
         "insurance_expiry": "2035-01-01", "territory_codes": ["T1"]}, program_admin_headers))
    resp = api.substantiate_complaint("11111111-2222-3333-4444-555555555555",
                                      make_contractor_headers(contractor["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_distributor_cannot_assign_for_other_distributor(api, program_admin_headers):
    """PRD §2.1: "When `X-User-Role` is `Distributor`, `X-User-ID` is the `id` of the
    acting `Distributor` record; lead-assignment creation and return compare the
    resource's `distributor_id` to `X-User-ID` under the same `ERR_OWNERSHIP_MISMATCH`
    rule."

    Design: Corner/rbac/distributor_cannot_assign_for_other_distributor
    """
    da = get_success_data(api.create_distributor(
        create_distributor_payload(name="Dist A", territory_codes=["T1"], lead_pool_total=1), program_admin_headers))
    db = get_success_data(api.create_distributor(
        create_distributor_payload(name="Dist B", territory_codes=["T1"], lead_pool_total=1), program_admin_headers))
    resp = api.create_lead_assignment(
        create_lead_assignment_payload(
            distributor_id=db["id"],
            contractor_id="11111111-2222-3333-4444-555555555555",
        ),
        make_distributor_headers(da["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_OWNERSHIP_MISMATCH)


def test_inspector_cannot_complete_unassigned_order(api, program_admin_headers, claimant_headers):
    """PRD §3.5: "Completion belongs to the assigned inspector and no one else: the
    completing call must present an `X-User-ID` equal to the order's `inspector_id`,
    or it is refused with `ERR_OWNERSHIP_MISMATCH`."

    Design: Corner/rbac/inspector_cannot_complete_unassigned_order
    """
    from test_helpers import file_claim_with_photos, make_inspector_headers

    ctx = setup_active_registration(tier="BRONZE")
    reg = ctx["registration"]
    info = file_claim_with_photos(reg["id"], claim_labor_cost_cents=1000, file_at="2026-09-20", description="c")
    claim = info["claim"]
    order = get_success_data(api.request_inspection(claim["id"], program_admin_headers))
    get_success_data(api.schedule_inspection_order(
        order["id"], {"inspector_id": "INSP-1", "service_date": "2026-10-05"}, program_admin_headers))
    resp = api.complete_inspection_order(
        order["id"], {"findings": "f", "confirms_defect": True}, make_inspector_headers("INSP-2"))
    validate_error(resp, ApiErrorId.ERR_OWNERSHIP_MISMATCH)


def test_verify_with_expired_insurance_returns_insurance_expired(api, program_admin_headers):
    """PRD §3.2: "Approving moves the certification from `PENDING_VERIFICATION` to
    `ACTIVE` and is gated by four checks evaluated at the current clock date, in the
    order stated: ... the contractor's `insurance_expiry` must be strictly later than
    the current clock date (else `ERR_INSURANCE_EXPIRED`, HTTP 422)..."

    Design: Corner/errors/verify_with_expired_insurance_returns_insurance_expired
    """
    from test_helpers import add_training_credits, create_contractor_payload, create_training_course_payload

    set_clock("2026-09-01T00:00:00Z")
    contractor = get_success_data(api.create_contractor(
        create_contractor_payload(legal_name="Unins Co", license_number="LIC-UN", insurance_expiry="2026-08-01"),
        program_admin_headers))
    add_training_credits(contractor["id"], 4, validity_months=36)
    ch = make_contractor_headers(contractor["id"])
    cert = get_success_data(api.create_certification(
        create_certification_payload(contractor_id=contractor["id"], tier="BRONZE"), ch))
    resp = api.verify_certification(cert["id"], {"decision": "APPROVE"}, program_admin_headers)
    validate_error(resp, ApiErrorId.ERR_INSURANCE_EXPIRED)
