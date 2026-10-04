"""Eligibility verifications: lifecycle, renewal loop, segregation of duties,
decision validation, and the program-grant cascade."""
from test_helpers import (
    ApiErrorId,
    get_grant,
    get_success_data,
    list_extension_grants,
    make_compliance_officer_headers,
    make_named_user_headers,
    setup_base_chain,
    setup_with_user,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.fixtures import (
    accept_user,
    activate_grant,
    approve_ev,
    invite_user,
    list_evs,
    review_ev,
    set_clock,
    setup_education_org,
    setup_education_org_with_approved_ev,
    setup_grant,
    setup_product,
    submit_ev,
)
from test_helpers.test_users import TEST_USERS

CO_HEADERS = TEST_USERS["compliance_officer_headers"]
LA_HEADERS = TEST_USERS["license_admin_headers"]


def _get_ev(ev_id):
    resp = api_client.get_eligibility_verification(ev_id, CO_HEADERS)
    return get_success_data(resp)


def test_ev_decide_from_submitted_rejected(api):
    """PRD section 3.8: "Deciding the review — moving it to `APPROVED` or
    `REJECTED` — is likewise a `ComplianceOfficer` action, requiring the
    record to be `UNDER_REVIEW` (else `ERR_EV_NOT_UNDER_REVIEW`)".

    Design: Corner/state_machines/ev_decide_from_submitted_rejected
    """
    base = setup_with_user()
    ev = submit_ev(base["org"]["id"], base["user"]["id"], program_kind="NONPROFIT_PROGRAM",
                   evidence="doc-1")
    resp = api_client.transition_eligibility_verification(
        ev["id"],
        {"target_status": "APPROVED", "decision_rationale": "Skipping review entirely"},
        make_compliance_officer_headers("co-9"))
    validate_error(resp, ApiErrorId.ERR_EV_NOT_UNDER_REVIEW)
    assert _get_ev(ev["id"])["status"] == "SUBMITTED"


def test_ev_begin_review_then_decide_happy_path(api):
    """PRD section 3.8: "A `ComplianceOfficer` begins review by moving the
    record from `SUBMITTED` to `UNDER_REVIEW`" and "Deciding the review —
    moving it to `APPROVED` or `REJECTED` — is likewise a `ComplianceOfficer`
    action, requiring the record to be `UNDER_REVIEW` (else
    `ERR_EV_NOT_UNDER_REVIEW`) and a `decision_rationale` to be present (else
    `ERR_INVALID_EV_DECISION`, HTTP 400)."

    Design: Corner/state_machines/ev_decide_from_submitted_rejected
    """
    base = setup_with_user()
    ev = submit_ev(base["org"]["id"], base["user"]["id"], program_kind="NONPROFIT_PROGRAM",
                   evidence="doc-1")
    review_ev(ev["id"], officer_id="co-7")
    data = get_success_data(api_client.transition_eligibility_verification(
        ev["id"],
        {"target_status": "APPROVED", "decision_rationale": "Documents verified"},
        make_compliance_officer_headers("co-7")))
    assert data["status"] == "APPROVED"


def test_ev_decide_without_rationale_rejected(api):
    """PRD section 3.8: "Deciding the review — moving it to `APPROVED` or
    `REJECTED` — is likewise a `ComplianceOfficer` action, requiring the
    record to be `UNDER_REVIEW` (else `ERR_EV_NOT_UNDER_REVIEW`) and a
    `decision_rationale` to be present (else `ERR_INVALID_EV_DECISION`, HTTP
    400)."

    Design: Corner/errors/every_error_triggerable_spot_check
    """
    base = setup_with_user()
    ev = submit_ev(base["org"]["id"], base["user"]["id"], program_kind="NONPROFIT_PROGRAM",
                   evidence="doc-1")
    review_ev(ev["id"], officer_id="co-3")
    resp = api_client.transition_eligibility_verification(
        ev["id"], {"target_status": "APPROVED"}, make_compliance_officer_headers("co-3"))
    validate_error(resp, ApiErrorId.ERR_INVALID_EV_DECISION)
    assert _get_ev(ev["id"])["status"] == "UNDER_REVIEW"


def test_ev_resubmit_from_submitted_rejected(api):
    """PRD section 3.8: "Resubmission moves a `RENEWAL_REQUIRED` record back
    to `UNDER_REVIEW`, performed by a `NamedUser` supplying a fresh
    `evidence_document_ref`. The record must be `RENEWAL_REQUIRED` (else
    `ERR_EV_NOT_RENEWAL_REQUIRED`)".

    Design: Corner/errors/every_error_triggerable_spot_check
    """
    base = setup_with_user()
    ev = submit_ev(base["org"]["id"], base["user"]["id"], program_kind="NONPROFIT_PROGRAM",
                   evidence="doc-1")
    resp = api_client.transition_eligibility_verification(
        ev["id"],
        {"target_status": "UNDER_REVIEW", "evidence_document_ref": "doc-1"},
        make_named_user_headers(base["user"]["id"]))
    # PRD does not pin role-vs-state precedence for a NamedUser targeting
    # UNDER_REVIEW on a SUBMITTED record: the resubmit reading yields
    # ERR_EV_NOT_RENEWAL_REQUIRED; the begin-review role-gate reading yields
    # ERR_INSUFFICIENT_PERMISSIONS. Both are PRD-defensible.
    validate_error_is_one_of(resp, [
        ApiErrorId.ERR_EV_NOT_RENEWAL_REQUIRED,
        ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS,
    ])
    assert _get_ev(ev["id"])["status"] == "SUBMITTED"


def test_ev_resubmit_with_identical_evidence_rejected(api):
    """PRD section 3.8: "Resubmission moves a `RENEWAL_REQUIRED` record back
    to `UNDER_REVIEW`, performed by a `NamedUser` supplying a fresh
    `evidence_document_ref`. The record must be `RENEWAL_REQUIRED` (else
    `ERR_EV_NOT_RENEWAL_REQUIRED`), and the new evidence reference must differ
    from the previously recorded value (else `ERR_STALE_EVIDENCE`)."

    Design: Corner/errors/every_error_triggerable_spot_check
    """
    ctx = setup_education_org_with_approved_ev()
    ev = ctx["ev"]
    assert ev["status"] == "APPROVED"
    assert ev["valid_through_period"] == 12
    # Advance past the validity window (period 0 -> period 12).
    set_clock("2026-09-13T00:00:00Z")
    assert _get_ev(ev["id"])["status"] == "RENEWAL_REQUIRED"
    resp = api_client.transition_eligibility_verification(
        ev["id"],
        {"target_status": "UNDER_REVIEW", "evidence_document_ref": "doc-v1"},
        make_named_user_headers(ctx["user"]["id"]))
    validate_error(resp, ApiErrorId.ERR_STALE_EVIDENCE)


def test_ev_segregation_of_duties_blocks_self_decision(api):
    """PRD section 3.8: "Segregation of duties is enforced on both outcomes:
    the decider's `X-User-ID` must differ from the recorded
    `submitted_by_named_user_id` (else `ERR_SEGREGATION_OF_DUTIES_VIOLATION`,
    HTTP 403)."

    Design: Corner/validations/segregation_of_duties_blocks_self_decision
    """
    base = setup_with_user()
    ev = submit_ev(base["org"]["id"], base["user"]["id"], program_kind="NONPROFIT_PROGRAM",
                   evidence="doc-1")
    review_ev(ev["id"], officer_id="co-2")
    resp = api_client.transition_eligibility_verification(
        ev["id"],
        {"target_status": "APPROVED", "decision_rationale": "Self-approval attempt"},
        make_compliance_officer_headers(base["user"]["id"]))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION)
    assert _get_ev(ev["id"])["status"] == "UNDER_REVIEW"


def test_ev_segregation_allows_distinct_decider(api):
    """PRD section 3.8: "Segregation of duties is enforced on both outcomes:
    the decider's `X-User-ID` must differ from the recorded
    `submitted_by_named_user_id` (else `ERR_SEGREGATION_OF_DUTIES_VIOLATION`,
    HTTP 403). On either decision, `decided_by_named_user_id` is set to the
    decider's `X-User-ID` and the rationale is recorded."

    Design: Corner/validations/segregation_of_duties_blocks_self_decision
    """
    base = setup_with_user()
    ev = submit_ev(base["org"]["id"], base["user"]["id"], program_kind="NONPROFIT_PROGRAM",
                   evidence="doc-1")
    review_ev(ev["id"], officer_id="co-4")
    data = get_success_data(api_client.transition_eligibility_verification(
        ev["id"],
        {"target_status": "APPROVED", "decision_rationale": "Independent review passed"},
        make_compliance_officer_headers("co-4")))
    assert data["status"] == "APPROVED"
    assert data["decided_by_named_user_id"] == "co-4"


def test_ev_renewal_loop_flips_at_boundary_and_resubmits(api):
    """PRD section 3.8: "Approval additionally sets `valid_through_period` to
    the current period index plus 12 — an approval at period 3 stays
    `APPROVED` through period 14 and flips at period 15."
    PRD section 3.8: "When a clock advance pushes the organization's
    `current_period_index` to or past `valid_through_period` — the comparison
    is inclusive at the boundary — an `APPROVED` record flips to
    `RENEWAL_REQUIRED`."
    PRD section 3.8: "Resubmission moves a `RENEWAL_REQUIRED` record back to
    `UNDER_REVIEW`, performed by a `NamedUser` supplying a fresh
    `evidence_document_ref`."

    Design: Difficulty/non_linear_state_machine/eligibility_verification_renewal_loop
    """
    ctx = setup_education_org_with_approved_ev()
    ev = ctx["ev"]
    assert ev["valid_through_period"] == 12

    # Period 11 (2026-09-12): still APPROVED
    set_clock("2026-09-12T00:00:00Z")
    assert _get_ev(ev["id"])["status"] == "APPROVED"

    # Period 12 (2026-09-13): flips to RENEWAL_REQUIRED (inclusive boundary)
    set_clock("2026-09-13T00:00:00Z")
    assert _get_ev(ev["id"])["status"] == "RENEWAL_REQUIRED"

    # Resubmit with fresh evidence closes the loop.
    data = get_success_data(api_client.transition_eligibility_verification(
        ev["id"],
        {"target_status": "UNDER_REVIEW", "evidence_document_ref": "doc-v2"},
        make_named_user_headers(ctx["user"]["id"])))
    assert data["status"] == "UNDER_REVIEW"


def test_ev_approval_window_is_twelve_periods(api):
    """PRD section 3.8: "Approval additionally sets `valid_through_period` to
    the current period index plus 12 — an approval at period 3 stays
    `APPROVED` through period 14 and flips at period 15."

    Design: Difficulty/non_linear_state_machine/eligibility_verification_renewal_loop
    """
    ctx = setup_education_org()
    ev = submit_ev(ctx["org"]["id"], ctx["user"]["id"])
    review_ev(ev["id"])
    ev = approve_ev(ev["id"])
    assert ev["valid_through_period"] == 12
    # Still approved one period before the boundary.
    set_clock("2026-09-12T00:00:00Z")
    assert _get_ev(ev["id"])["status"] == "APPROVED"


def test_ev_renewal_lapse_suspends_program_grants(api):
    """PRD section 3.8: "That flip cascades: every LicenseGrant of the
    organization whose `grant_kind` matches the record's `program_kind` and
    which is currently `ACTIVE` is moved to `SUSPENDED`, revoking those
    grants' extension grants in the depth-3 chain of §3.4."

    Design: Difficulty/transitive_cascade/ev_renewal_lapse_suspends_program_grants
    """
    set_clock()
    ctx = setup_education_org()
    org = ctx["org"]
    # Give the EDU product an extension module and attach an extension grant.
    product = setup_product(
        product_code="EDU-DESKTOP-11",
        extension_modules=[{
            "extension_code": "GEOSTAT",
            "additional_credit_rate_per_op": 2,
            "required_min_edition": "STANDARD",
        }],
    )
    grant = setup_grant(org["id"], product["id"], grant_kind="EDUCATION_PROGRAM")
    ev = submit_ev(org["id"], ctx["user"]["id"], program_kind="EDUCATION_PROGRAM")
    review_ev(ev["id"])
    approve_ev(ev["id"])
    activate_grant(grant["id"], org["id"])
    ext = get_success_data(api_client.create_extension_grant(
        {"license_grant_id": grant["id"], "extension_code": "GEOSTAT", "seats_allocated": 10},
        LA_HEADERS))

    # Period 11: still APPROVED, grant still ACTIVE.
    set_clock("2026-09-12T00:00:00Z")
    assert _get_ev(ev["id"])["status"] == "APPROVED"
    assert get_grant(grant["id"])["status"] == "ACTIVE"

    # Period 12: EV flips and the program grant cascade fires.
    set_clock("2026-09-13T00:00:00Z")
    assert _get_ev(ev["id"])["status"] == "RENEWAL_REQUIRED"
    assert get_grant(grant["id"])["status"] == "SUSPENDED"
    exts = list_extension_grants(grant["id"])
    assert all(e["status"] == "REVOKED" for e in exts)
    # The EV cascade touches grants only, not users.
    from test_helpers.fixtures import get_user
    assert get_user(ctx["user"]["id"])["status"] == "ACTIVE"


def test_ev_renewal_cascade_only_hits_matching_program_kind(api):
    """PRD section 3.8: "That flip cascades: every LicenseGrant of the
    organization whose `grant_kind` matches the record's `program_kind` and
    which is currently `ACTIVE` is moved to `SUSPENDED`".

    Design: Difficulty/transitive_cascade/ev_renewal_lapse_suspends_program_grants
    """
    set_clock()
    ctx = setup_education_org()
    org = ctx["org"]
    edu_grant = setup_grant(org["id"], ctx["product"]["id"], grant_kind="EDUCATION_PROGRAM")
    std_grant = setup_grant(org["id"], ctx["product"]["id"], grant_kind="STANDARD")
    ev = submit_ev(org["id"], ctx["user"]["id"], program_kind="EDUCATION_PROGRAM")
    review_ev(ev["id"])
    approve_ev(ev["id"])
    activate_grant(edu_grant["id"], org["id"])
    activate_grant(std_grant["id"], org["id"])

    set_clock("2026-09-13T00:00:00Z")
    assert _get_ev(ev["id"])["status"] == "RENEWAL_REQUIRED"
    assert get_grant(edu_grant["id"])["status"] == "SUSPENDED"
    assert get_grant(std_grant["id"])["status"] == "ACTIVE"


def test_eligibility_window_closes_at_exact_period(api):
    """PRD section 3.4: "For program-kind grants — `EDUCATION_PROGRAM` or
    `NONPROFIT_PROGRAM` — there must additionally exist an
    EligibilityVerification for the same organization with a matching
    `program_kind`, in `APPROVED` status, whose `valid_through_period` is
    strictly greater than the current period index; without one the activation
    fails with `ERR_ELIGIBILITY_NOT_APPROVED` (HTTP 403)."
    PRD section 3.8: "When a clock advance pushes the organization's
    `current_period_index` to or past `valid_through_period` — the comparison
    is inclusive at the boundary — an `APPROVED` record flips to
    `RENEWAL_REQUIRED`."

    Design: Difficulty/resource_temporal_overlap/eligibility_window_closes_at_exact_period
    """
    ctx = setup_education_org_with_approved_ev()
    org = ctx["org"]
    grant = ctx["grant"]

    # Period 11: valid_through 12 > 11 -> activation passes the gate.
    set_clock("2026-09-12T00:00:00Z")
    resp = api_client.transition_license_grant(
        grant["id"],
        {"target_status": "ACTIVE",
         "expected_organization_version": _org_version(org["id"])},
        LA_HEADERS)
    data = validate_success(resp)
    assert data["status"] == "ACTIVE"

    # Suspend, advance past the window, and re-activation must fail the gate.
    resp = api_client.transition_license_grant(
        grant["id"],
        {"target_status": "SUSPENDED",
         "expected_organization_version": _org_version(org["id"])},
        LA_HEADERS)
    validate_success(resp)
    set_clock("2026-09-13T00:00:00Z")
    resp = api_client.transition_license_grant(
        grant["id"],
        {"target_status": "ACTIVE",
         "expected_organization_version": _org_version(org["id"])},
        LA_HEADERS)
    validate_error(resp, ApiErrorId.ERR_ELIGIBILITY_NOT_APPROVED)


def test_eligibility_gate_passes_inside_window(api):
    """PRD section 3.4: "For program-kind grants — `EDUCATION_PROGRAM` or
    `NONPROFIT_PROGRAM` — there must additionally exist an
    EligibilityVerification for the same organization with a matching
    `program_kind`, in `APPROVED` status, whose `valid_through_period` is
    strictly greater than the current period index; without one the activation
    fails with `ERR_ELIGIBILITY_NOT_APPROVED` (HTTP 403)."

    Design: Difficulty/resource_temporal_overlap/eligibility_window_closes_at_exact_period
    """
    ctx = setup_education_org_with_approved_ev()
    resp = api_client.transition_license_grant(
        ctx["grant"]["id"],
        {"target_status": "ACTIVE",
         "expected_organization_version": _org_version(ctx["org"]["id"])},
        LA_HEADERS)
    data = validate_success(resp)
    assert data["status"] == "ACTIVE"


def test_stale_version_beats_eligibility_on_grant_activate(api):
    """PRD section 2.9: "Three write endpoints carry mandatory
    optimistic-concurrency fields, and in each case the check runs before any
    business rule on that endpoint".
    PRD section 2.10: "**Optimistic concurrency (priority 5).**
    `expected_*_version` must match the parent entity's current `version` —
    before any business rule — else `ERR_STALE_VERSION`."

    Design: Difficulty/priority_pair_validation_conflict/stale_version_beats_business_safety_on_grant_activate
    """
    ctx = setup_education_org()  # no EV submitted at all
    org = ctx["org"]
    stale_v = ctx["org_v0"]
    # Activate a STANDARD grant once to move the org version forward.
    std_grant = setup_grant(org["id"], ctx["product"]["id"], grant_kind="STANDARD", seats_allocated=5)
    activate_grant(std_grant["id"], org["id"])
    # Activate the EDUCATION_PROGRAM grant with the stale version; no approved EV exists.
    resp = api_client.transition_license_grant(
        ctx["grant"]["id"],
        {"target_status": "ACTIVE", "expected_organization_version": stale_v},
        LA_HEADERS)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
    assert get_grant(ctx["grant"]["id"])["status"] == "PENDING_ACTIVATION"


def test_stale_version_preempts_business_rule_even_with_valid_ev(api):
    """PRD section 2.9: "in each case the check runs before any business rule
    on that endpoint".
    PRD section 2.10: "**Optimistic concurrency (priority 5).**
    `expected_*_version` must match the parent entity's current `version` —
    before any business rule — else `ERR_STALE_VERSION`."

    Design: Difficulty/priority_pair_validation_conflict/stale_version_beats_business_safety_on_grant_activate
    """
    ctx = setup_education_org_with_approved_ev()  # EV gate would pass; only OCC can fail
    org = ctx["org"]
    resp = api_client.transition_license_grant(
        ctx["grant"]["id"],
        {"target_status": "ACTIVE", "expected_organization_version": ctx["org_v0"] + 999},
        LA_HEADERS)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)


def _org_version(org_id):
    from test_helpers.fixtures import get_org_version
    return get_org_version(org_id)
