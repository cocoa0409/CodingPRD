"""Supplier audits: composite scoring, SoD, verify cascades (PRD §3.2, §2.9, §2.5)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, TEST_USERS, api_client,
    create_audit_payload,
    make_supplier, create_approved_supplier, run_audit,
    make_commitment, make_verified_certification, make_certification,
    verify_certification,
    make_limited_run_flavor, make_published_claim_flavor,
    make_sustainability_auditor_headers, make_audit_verifier_headers,
)

SM = TEST_USERS["sourcing_manager_headers"]
FM = TEST_USERS["flavor_manager_headers"]
POC = TEST_USERS["parent_ops_controller_headers"]




def test_audit_composite_weighted_and_findings_gate(api):
    """PRD §3.2: "The system then computes the audit's `composite_score` as the weighted sum of labor at 40 percent, environment at 30 percent, and community at 30 percent, rounded half-up to an integer, and derives the `outcome`: `PASS` when the composite is at least 70 and the findings count is at most 2 — both boundaries inclusive — and `FAIL` otherwise."

    Design: Corner/calculations/audit_composite_weighted_and_findings_gate
    """
    supplier = make_supplier(name="Gate Supplier", category="NUTS")

    audit1 = get_success_data(api.create_audit(
        supplier["id"], create_audit_payload(scheduled_for="2026-09-05T00:00:00Z"), SM))
    get_success_data(api.start_audit(
        audit1["id"], make_sustainability_auditor_headers("aud-1")))
    done1 = validate_success(api.complete_audit(
        audit1["id"],
        {"labor_score": 80, "environment_score": 70, "community_score": 60,
         "findings_count": 0},
        make_sustainability_auditor_headers("aud-1")))
    assert done1["composite_score"] == 71
    assert done1["outcome"] == "PASS"

    audit2 = get_success_data(api.create_audit(
        supplier["id"], create_audit_payload(scheduled_for="2026-09-06T00:00:00Z"), SM))
    get_success_data(api.start_audit(
        audit2["id"], make_sustainability_auditor_headers("aud-2")))
    done2 = validate_success(api.complete_audit(
        audit2["id"],
        {"labor_score": 90, "environment_score": 90, "community_score": 90,
         "findings_count": 3},
        make_sustainability_auditor_headers("aud-2")))
    assert done2["composite_score"] == 90
    assert done2["outcome"] == "FAIL", "findings_count 3 > 2 gate overrides composite"


def test_auditor_cannot_verify_own_audit_sod(api):
    """PRD §2.9: "The `AuditVerifier` who verifies a completed audit must not be
    the auditor who performed it. If the verifier's `X-User-ID` equals the
    audit's `auditor_user_id`, the verification is rejected with
    `ERR_SOD_AUDITOR_VERIFY` (HTTP 403)."

    Design: Corner/validations/auditor_cannot_verify_own_audit_sod
    """
    supplier = make_supplier(name="SoD Supplier")
    audit = get_success_data(api.create_audit(supplier["id"], create_audit_payload(), SM))
    get_success_data(api.start_audit(
        audit["id"], make_sustainability_auditor_headers("aud-1")))
    get_success_data(api.complete_audit(
        audit["id"],
        {"labor_score": 80, "environment_score": 70, "community_score": 60,
         "findings_count": 0},
        make_sustainability_auditor_headers("aud-1")))
    resp = api.verify_audit(audit["id"], make_audit_verifier_headers("aud-1"))
    validate_error(resp, ApiErrorId.ERR_SOD_AUDITOR_VERIFY)


def test_audit_fail_depth3_cascade(api):
    """PRD §3.2: "On a `FAIL`, a `PROSPECT` or `APPROVED` supplier cascades to `SUSPENDED` in a depth-3 cascade: every certification of the supplier in `PENDING` or `VERIFIED` is revoked to `REVOKED`; every flavor claim in `SUBSTANTIATED` or `PUBLISHED` citing any of those certifications is challenged to `CHALLENGED`; every `ACTIVE` sourcing commitment of the supplier lapses to `LAPSED`; and the supplier's `version` bumps."

    Design: Difficulty/transitive_cascade/audit_fail_depth3_cascade
    """
    supplier = create_approved_supplier(name="Cascade Dairy")
    commitment = make_commitment(supplier["id"], category="DAIRY")
    cert = make_verified_certification(supplier["id"], declared=95, verified=95)
    flavor = make_published_claim_flavor([cert["id"]], name="Cascade Crunch")
    assert flavor["claim_status"] == "PUBLISHED"

    # Second audit on the same supplier, completed with failing scores.
    fail_supplier_verify = run_audit(
        supplier["id"], labor=50, environment=50, community=50, findings=5,
        auditor_id="aud-2", verifier_id="ver-9",
        scheduled_for="2026-09-06T00:00:00Z")
    assert fail_supplier_verify["outcome"] == "FAIL"

    supplier_after = get_success_data(api.get_supplier(supplier["id"], SM))
    assert supplier_after["status"] == "SUSPENDED"          # link 1
    assert supplier_after["social_criteria_score"] == 50    # composite written even on FAIL

    certs, _ = validate_paginated(api.list_certifications(supplier["id"], SM))
    cert_by_id = {c["id"]: c for c in certs}
    assert cert_by_id[cert["id"]]["status"] == "REVOKED"    # link 2

    flavor_after = get_success_data(api.get_flavor(flavor["id"], FM))
    assert flavor_after["claim_status"] == "CHALLENGED"     # link 3

    active, _ = validate_paginated(
        api.list_commitments(supplier["id"], SM, params={"status": "ACTIVE"}))
    assert active == [], "the ACTIVE commitment must lapse in the cascade"
    commitments, _ = validate_paginated(api.list_commitments(supplier["id"], SM))
    by_id = {c["id"]: c for c in commitments}
    assert by_id[commitment["id"]]["status"] == "LAPSED"


def test_audit_fail_on_prospect_suspends_and_revokes(api):
    """PRD §3.2: "On a `FAIL`, a `PROSPECT` or `APPROVED` supplier cascades to `SUSPENDED` in a depth-3 cascade: every certification of the supplier in `PENDING` or `VERIFIED` is revoked to `REVOKED`; every flavor claim in `SUBSTANTIATED` or `PUBLISHED` citing any of those certifications is challenged to `CHALLENGED`; every `ACTIVE` sourcing commitment of the supplier lapses to `LAPSED`; and the supplier's `version` bumps."
    PRD §3.2: "Verification moves the audit from `COMPLETED` to its terminal
    `VERIFIED` state and always writes the audit's `composite_score` onto the
    supplier as `social_criteria_score`."

    Design: Difficulty/transitive_cascade/audit_fail_depth3_cascade
    """
    supplier = make_supplier(name="Prospect Fail Dairy")
    cert = make_certification(supplier["id"], declared=90)  # PENDING

    audit = run_audit(supplier["id"], labor=50, environment=50, community=50,
                      findings=5)
    assert audit["outcome"] == "FAIL"

    after = get_success_data(api.get_supplier(supplier["id"], SM))
    assert after["status"] == "SUSPENDED", "a PROSPECT supplier cascades to SUSPENDED"
    assert after["social_criteria_score"] == 50

    certs, _ = validate_paginated(api.list_certifications(supplier["id"], SM))
    by_id = {c["id"]: c for c in certs}
    assert by_id[cert["id"]]["status"] == "REVOKED", \
        "PENDING certifications are revoked by the cascade as well"


def test_clock_expiry_depth2_cascade(api):
    """PRD §2.5: "A certification in `PENDING` or `VERIFIED` whose `valid_until`
    is strictly earlier than the current logical time transitions to `EXPIRED`.
    Every flavor claim in `PUBLISHED` status that cites that certification is
    retracted to `RETRACTED` — a depth-2 cascade from clock advance to
    certification expiry to claim retraction."

    Design: Difficulty/transitive_cascade/clock_expiry_depth2_cascade
    """
    supplier = create_approved_supplier(name="Clock Dairy")
    cert = make_verified_certification(
        supplier["id"], declared=95, verified=95,
        valid_until="2026-10-01T00:00:00Z")
    flavor = make_published_claim_flavor([cert["id"]], name="Clockwork Orange")
    assert flavor["claim_status"] == "PUBLISHED"

    validate_success(api.set_clock({"to_iso8601": "2026-10-02T00:00:00Z"}, POC))

    certs, _ = validate_paginated(api.list_certifications(supplier["id"], SM))
    by_id = {c["id"]: c for c in certs}
    assert by_id[cert["id"]]["status"] == "EXPIRED"          # link 1

    after = get_success_data(api.get_flavor(flavor["id"], FM))
    assert after["claim_status"] == "RETRACTED"              # link 2 (not CHALLENGED)
    assert after["status"] == "LIMITED_RUN", "claim cascade must not touch lifecycle"


def test_clock_expiry_boundary_exclusive(api):
    """PRD §2.5: "A certification in `PENDING` or `VERIFIED` whose `valid_until`
    is strictly earlier than the current logical time transitions to `EXPIRED`."

    Design: Difficulty/transitive_cascade/clock_expiry_depth2_cascade
    """
    supplier = create_approved_supplier(name="Boundary Dairy")
    cert = make_verified_certification(
        supplier["id"], declared=95, verified=95,
        valid_until="2026-10-01T00:00:00Z")
    flavor = make_published_claim_flavor([cert["id"]], name="Boundary Batch")

    # At exactly valid_until the window end is exclusive: not yet EXPIRED.
    validate_success(api.set_clock({"to_iso8601": "2026-10-01T00:00:00Z"}, POC))
    certs, _ = validate_paginated(api.list_certifications(supplier["id"], SM))
    by_id = {c["id"]: c for c in certs}
    assert by_id[cert["id"]]["status"] == "VERIFIED"
    assert get_success_data(api.get_flavor(flavor["id"], FM))["claim_status"] == "PUBLISHED"

    # One second past: expiry fires and retracts the citing PUBLISHED claim.
    validate_success(api.set_clock({"to_iso8601": "2026-10-01T00:00:01Z"}, POC))
    certs, _ = validate_paginated(api.list_certifications(supplier["id"], SM))
    by_id = {c["id"]: c for c in certs}
    assert by_id[cert["id"]]["status"] == "EXPIRED"
    assert get_success_data(api.get_flavor(flavor["id"], FM))["claim_status"] == "RETRACTED"
