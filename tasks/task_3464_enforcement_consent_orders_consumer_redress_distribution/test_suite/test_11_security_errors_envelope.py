"""Security and error-surface contracts: auth precedence, the fixed error
envelope, entity-specific 404s, and role-based denials."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    UNKNOWN_UUID,
    advance_clock,
    api_client,
    build_user_headers,
    consent_order_transition_payload,
    create_claim_payload,
    create_company,
    create_investigation,
    file_claim,
    get_claim,
    get_investigation,
    get_latest_comment_period,
    get_order,
    make_claimant_headers,
    make_claimant_specs,
    make_company_representative_headers,
    reset_clock_to_epoch,
    setup_open_fund,
    setup_proposed_order,
    validate_error,
)

_ADMIN_READ = TEST_USERS["platform_admin_headers"]
_ATTORNEY = TEST_USERS["staff_attorney_headers"]
_COMMISSIONER = TEST_USERS["commissioner_headers"]
_ADMIN = TEST_USERS["fund_administrator_headers"]  # fa-1
_MONITOR_1 = TEST_USERS["compliance_monitor_headers"]  # cm-1
_OFFICER = TEST_USERS["disbursement_officer_headers"]  # do-1


def _uid(suffix: int) -> str:
    """A syntactically valid but never-allocated UUID per probe."""
    return f"00000000-0000-4000-8000-{suffix:012d}"


def test_missing_auth_header_on_unknown_id_returns_unauthenticated():
    """PRD section 2.8: "1. **Authentication context** — `X-User-ID` and
    `X-User-Role` present and non-empty, else
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. Applies to all endpoints."
    PRD section 2.8: "When several checks could fail, the one at the lowest
    priority number fires first and determines the error the client sees;
    later checks are not evaluated."

    Design: Corner/validations/missing_auth_header_on_unknown_id_returns_unauthenticated
    """
    reset_clock_to_epoch()
    resp = api_client.get_consent_order(UNKNOWN_UUID, headers={})
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
    assert resp.status_code == 400, "authentication outranks existence: never a 404 here"


def test_error_response_envelope_shape_is_fixed():
    """PRD section 2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."
    PRD section 2.2: "The `error_id` is a unique, machine-readable string
    that identifies the specific error."
    PRD section 2.2: "The `message` provides a human-readable explanation of
    what went wrong."

    Design: Corner/errors/error_response_envelope_shape_is_fixed
    """
    reset_clock_to_epoch()
    resp = api_client.transition_cid(UNKNOWN_UUID, {"target_state": "ISSUED"}, _ATTORNEY)
    error_data = validate_error(resp, ApiErrorId.ERR_CID_NOT_FOUND)
    assert isinstance(error_data["message"], str) and error_data["message"].strip()
    body = resp.json()
    assert body["response_type"] == "error"
    assert set(body["meta"].keys()) == {"api_request_id", "api_request_timestamp"}, (
        f"error meta must carry exactly the two request fields, got {sorted(body['meta'])}"
    )


def test_single_resource_gets_with_unknown_ids_return_entity_specific_not_found():
    """PRD section 2.9: "the request is rejected with the entity-specific
    not-found error for the *first* identifier that does not resolve."

    Design: Corner/errors/single_resource_gets_with_unknown_ids_return_entity_specific_not_found
    """
    reset_clock_to_epoch()
    validate_error(
        api_client.get_subject_company(_uid(1), _ADMIN_READ),
        ApiErrorId.ERR_SUBJECT_COMPANY_NOT_FOUND,
    )
    validate_error(
        api_client.get_investigation(_uid(2), _ATTORNEY),
        ApiErrorId.ERR_INVESTIGATION_NOT_FOUND,
    )
    validate_error(
        api_client.get_judgment(_uid(3), _COMMISSIONER),
        ApiErrorId.ERR_JUDGMENT_NOT_FOUND,
    )
    validate_error(
        api_client.get_redress_fund(_uid(4), _ADMIN),
        ApiErrorId.ERR_REDRESS_FUND_NOT_FOUND,
    )
    validate_error(
        api_client.get_claim(_uid(5), _ADMIN),
        ApiErrorId.ERR_CLAIM_NOT_FOUND,
    )

    # Claimant body-FK probe: filed against a REAL open fund with a caller
    # identity matching the unknown claimant_id, so the claimant lookup is
    # the only check that can fail — every evaluation order converges on
    # ERR_CLAIMANT_NOT_FOUND.
    bundle = setup_open_fund(
        judgment_amount_cents=1_500_000,
        monetary_relief_cents=1_500_000,
        claimant_specs=None,
    )
    unknown_claimant = _uid(6)
    resp = api_client.create_claim(
        create_claim_payload(unknown_claimant, bundle["fund"]["id"], documented_loss_cents=1_000),
        build_user_headers(unknown_claimant, "Claimant"),
    )
    validate_error(resp, ApiErrorId.ERR_CLAIMANT_NOT_FOUND)


def test_nested_paths_and_transition_targets_with_unknown_ids_return_entity_specific_not_found():
    """PRD section 2.9: "When an endpoint path contains resource identifiers,
    the system validates them in strict left-to-right order, and the request
    is rejected with the entity-specific not-found error for the *first*
    identifier that does not resolve. A request addressing a CID under a
    nonexistent investigation therefore fails with
    `ERR_INVESTIGATION_NOT_FOUND` before the CID itself is ever consulted."

    Design: Corner/errors/nested_paths_and_transition_targets_with_unknown_ids_return_entity_specific_not_found
    """
    reset_clock_to_epoch()
    # Unknown parent ids on nested collections report the parent's 404.
    validate_error(
        api_client.list_cids(_uid(10), _ATTORNEY),
        ApiErrorId.ERR_INVESTIGATION_NOT_FOUND,
    )
    validate_error(
        api_client.list_comment_periods(_uid(11), _COMMISSIONER),
        ApiErrorId.ERR_CONSENT_ORDER_NOT_FOUND,
    )
    validate_error(
        api_client.list_claimants(_uid(12), _ADMIN),
        ApiErrorId.ERR_REDRESS_FUND_NOT_FOUND,
    )
    # Unknown transition/action targets report the target's own 404.
    validate_error(
        api_client.transition_cid(_uid(13), {"target_state": "ISSUED"}, _ATTORNEY),
        ApiErrorId.ERR_CID_NOT_FOUND,
    )
    validate_error(
        api_client.post_comment(_uid(14), {"author_email": "a@b.org", "body": "x"}, _ADMIN_READ),
        ApiErrorId.ERR_COMMENT_PERIOD_NOT_FOUND,
    )
    validate_error(
        api_client.transition_compliance_report(_uid(15), {"target_state": "ACCEPTED"}, _MONITOR_1),
        ApiErrorId.ERR_COMPLIANCE_REPORT_NOT_FOUND,
    )
    validate_error(
        api_client.transition_violation_penalty(_uid(16), {"target_state": "WAIVED"}, _MONITOR_1),
        ApiErrorId.ERR_VIOLATION_PENALTY_NOT_FOUND,
    )
    validate_error(
        api_client.transition_refund_check(_uid(17), {"target_state": "CASHED"}, _OFFICER),
        ApiErrorId.ERR_REFUND_CHECK_NOT_FOUND,
    )


def test_claimant_cannot_transition_claims():
    """PRD section 2.1: "A `FundAdministrator` identifies claimants,
    adjudicates claims, and advances the redress fund lifecycle."
    PRD section 2.1: "A request whose role is not permitted for the endpoint
    — or, on a transition endpoint, not permitted for the requested
    `target_state` — is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP
    403)."

    Design: Corner/rbac/claimant_cannot_transition_claims
    """
    bundle = setup_open_fund(
        judgment_amount_cents=1_500_000,
        monetary_relief_cents=1_500_000,
        claimant_specs=make_claimant_specs(1),
    )
    claim = file_claim(bundle["claimants"][0], 100_000)

    resp = api_client.transition_claim(
        claim["id"],
        {"target_state": "UNDER_REVIEW"},
        make_claimant_headers(bundle["claimants"][0]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    after = get_claim(claim["id"])
    assert after["status"] == "FILED"
    assert after["version"] == 1


def test_staff_attorney_cannot_finalize_order():
    """PRD section 3.3: "Finalization is reserved for a `Commissioner` and
    carries the regulatory cooling-off gate".
    PRD section 2.1: "A request whose role is not permitted for the endpoint
    — or, on a transition endpoint, not permitted for the requested
    `target_state` — is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP
    403)."

    Design: Corner/rbac/staff_attorney_cannot_finalize_order
    """
    bundle = setup_proposed_order()
    order_id = bundle["order"]["id"]
    order_v2 = bundle["order"]["version"]

    # Close the comment period so ONLY the role check can fail.
    advance_clock(get_latest_comment_period(order_id)["closes_at"])
    resp = api_client.transition_consent_order(
        order_id,
        consent_order_transition_payload("FINAL", order_v2),
        _ATTORNEY,
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    order = get_order(order_id)
    assert order["status"] == "IN_PUBLIC_COMMENT"
    assert order["version"] == order_v2


def test_company_representative_cannot_transition_investigation():
    """PRD section 2.1: "A `StaffAttorney` opens and advances investigations,
    issues civil investigative demands, drafts and proposes consent orders,
    and records asset traces."
    PRD section 2.1: "A `CompanyRepresentative` speaks for a subject company:
    responding to demands, submitting compliance reports, and paying
    judgments and penalties."
    PRD section 2.1: "A request whose role is not permitted for the endpoint
    — or, on a transition endpoint, not permitted for the requested
    `target_state` — is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP
    403)."

    Design: Corner/rbac/company_representative_cannot_transition_investigation
    """
    reset_clock_to_epoch()
    company = create_company()
    investigation = create_investigation(company["id"])

    resp = api_client.transition_investigation(
        investigation["id"],
        {"target_state": "PRELIMINARY_REVIEW"},
        make_company_representative_headers(company["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    assert get_investigation(investigation["id"])["status"] == "INTAKE"
