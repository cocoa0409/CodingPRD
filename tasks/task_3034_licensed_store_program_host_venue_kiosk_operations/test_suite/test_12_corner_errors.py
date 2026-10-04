"""Corner design — section: errors."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    api_client,
    generate_statement,
    set_clock,
    setup_failed_inspection,
    setup_operating_store,
    validate_error,
    validate_success,
)
from test_helpers.factories import (
    create_certification_payload,
    create_employee_payload,
    create_loyalty_member_payload,
)
from test_helpers.fixtures import (
    activate_agreement,
    create_draft_agreement,
    create_licensee,
    create_venue,
)
from test_helpers.test_users import (
    make_inspector_headers,
    make_licensee_manager_headers,
)


def test_duplicate_member_email_conflict():
    """PRD §3.9: "**LoyaltyMembers** register with a unique `email` (duplicates
    are `ERR_UNIQUENESS_CONFLICT`) and carry a `points_balance` flanked by
    `lifetime_earned` and `lifetime_redeemed`; the invariant `points_balance`
    equals `lifetime_earned` minus `lifetime_redeemed` holds after every event,
    with `ADJUST` credits feeding the earned side and `ADJUST` debits the
    redeemed side."

    Design: Corner/errors/duplicate_member_email_conflict
    """
    validate_success(api_client.create_loyalty_member(
        create_loyalty_member_payload(email="dup@x.com"), ADMIN), expected_status=201)
    resp = api_client.create_loyalty_member(
        create_loyalty_member_payload(email="dup@x.com"), ADMIN)
    validate_error(resp, ApiErrorId.ERR_UNIQUENESS_CONFLICT.value)


def test_stale_agreement_version_on_amend():
    """PRD §2.10: "Amending an agreement's royalty terms requires a
    non-optional `expected_agreement_version` field carrying the client's last
    observed `version` of the agreement; if the agreement's current `version`
    no longer matches — because another successful write (an amendment, an
    accept, a suspend, a reinstate, or a statement generation) has advanced it
    since the client's view was taken — the request is rejected with
    `ERR_STALE_AGREEMENT_VERSION` (HTTP 412)."

    Design: Corner/errors/stale_agreement_version_on_amend
    """
    set_clock()
    licensee = create_licensee()
    venue = create_venue()
    draft = create_draft_agreement(licensee["id"], venue["id"])
    stale_version = draft["version"]  # 1
    agreement = activate_agreement(draft)
    assert agreement["version"] == stale_version + 2
    resp = api_client.amend_license_agreement(
        agreement["id"],
        {"royalty_basis": "CASH", "expected_agreement_version": stale_version},
        ADMIN)
    validate_error(resp, ApiErrorId.ERR_STALE_AGREEMENT_VERSION.value)
    fresh = validate_success(api_client.get_license_agreement(agreement["id"], ADMIN))
    amended = validate_success(api_client.amend_license_agreement(
        agreement["id"],
        {"royalty_basis": "CASH", "expected_agreement_version": fresh["version"]},
        ADMIN))
    assert amended["royalty_basis"] == "CASH"
    assert amended["version"] == fresh["version"] + 1


def test_stale_version_on_statement_generation_supersede():
    """PRD §2.10: "Generating a royalty statement under an agreement is guarded
    identically: the request must carry `expected_agreement_version` matching
    the agreement's current `version`, and a mismatch is rejected with
    `ERR_STALE_AGREEMENT_VERSION` (HTTP 412), because generation supersedes any
    existing draft statement for an overlapping period and that supersede
    decision must be based on terms the client has actually observed."

    Design: Corner/errors/stale_version_on_statement_generation_supersede
    """
    set_clock()
    licensee = create_licensee()
    venue = create_venue()
    agreement = activate_agreement(create_draft_agreement(licensee["id"], venue["id"]))
    version_v0 = agreement["version"]
    stmt1 = generate_statement(
        agreement["id"], period_start_date="2026-09-01", period_end_date="2026-09-30")
    assert stmt1["status"] == "DRAFT"
    # retry with the stale pre-first-generation version
    resp = api_client.create_royalty_statement(
        agreement["id"],
        {"period_start_date": "2026-09-01", "period_end_date": "2026-09-30",
         "expected_agreement_version": version_v0},
        ADMIN)
    validate_error(resp, ApiErrorId.ERR_STALE_AGREEMENT_VERSION.value)
    # with the fresh version the regeneration succeeds and supersedes the first DRAFT
    stmt2 = generate_statement(
        agreement["id"], period_start_date="2026-09-01", period_end_date="2026-09-30")
    assert stmt2["status"] == "DRAFT"
    stmt1 = validate_success(api_client.get_royalty_statement(stmt1["id"], ADMIN))
    assert stmt1["status"] == "SUPERSEDED"


def test_segregated_audit_verify_by_proctor_rejected():
    """PRD §3.6: "Audit verification, again by a `BrandInspector`, moves
    `EXAM_PASSED → CERTIFIED` — but the verifying inspector must not be the
    proctor: identical identities are rejected with `ERR_SEGREGATION_OF_DUTIES`,
    and audit rejection carries the same segregation rule."

    Design: Corner/errors/segregated_audit_verify_by_proctor_rejected
    """
    set_clock()
    licensee = create_licensee()
    venue = create_venue()
    activate_agreement(create_draft_agreement(licensee["id"], venue["id"]))
    lic_headers = make_licensee_manager_headers(licensee["id"])
    employee = validate_success(api_client.create_employee(
        licensee["id"], create_employee_payload(), lic_headers), expected_status=201)
    cert = validate_success(api_client.create_certification(
        employee["id"], create_certification_payload(), lic_headers), expected_status=201)
    validate_success(api_client.record_certification_exam(
        cert["id"], {"exam_score": 90, "proctor_anomaly": False},
        make_inspector_headers("insp-P")))
    resp = api_client.audit_verify_certification(
        cert["id"], make_inspector_headers("insp-P"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
    verified = validate_success(api_client.audit_verify_certification(
        cert["id"], make_inspector_headers("insp-Q")))
    assert verified["status"] == "CERTIFIED"


def test_max_reopens_enforced():
    """PRD §3.8: "Alternatively the inspector reopens a submitted action with a
    `reason`: `reopen_count` climbs by 1, the store's posture is recomputed,
    and the action returns to `REOPENED` — but an action may be reopened at
    most twice, and a third attempt is `ERR_MAX_REOPENS_EXCEEDED`."

    Design: Corner/errors/max_reopens_enforced
    """
    set_clock()
    bundle, inspection, actions = setup_failed_inspection(
        failing_categories=("BEVERAGE_QUALITY",))
    assert len(actions) == 1
    ca = actions[0]
    lic_headers = make_licensee_manager_headers(bundle["licensee_id"])
    inspector = make_inspector_headers("insp-A")
    validate_success(api_client.submit_corrective_action_evidence(
        ca["id"], {"evidence_note": "v1"}, lic_headers))
    validate_success(api_client.reopen_corrective_action(ca["id"], {"reason": "no"}, inspector))
    validate_success(api_client.submit_corrective_action_evidence(
        ca["id"], {"evidence_note": "v2"}, lic_headers))
    validate_success(api_client.reopen_corrective_action(
        ca["id"], {"reason": "still no"}, inspector))
    validate_success(api_client.submit_corrective_action_evidence(
        ca["id"], {"evidence_note": "v3"}, lic_headers))
    resp = api_client.reopen_corrective_action(ca["id"], {"reason": "third"}, inspector)
    validate_error(resp, ApiErrorId.ERR_MAX_REOPENS_EXCEEDED.value)
    refreshed = validate_success(api_client.get_corrective_action(ca["id"], ADMIN))
    assert refreshed["status"] == "SUBMITTED"
    assert refreshed["reopen_count"] == 2
