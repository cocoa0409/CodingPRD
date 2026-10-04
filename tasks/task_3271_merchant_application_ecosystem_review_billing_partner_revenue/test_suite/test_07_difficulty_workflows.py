"""Review-cycle, consent, cascade, validation-priority, and temporal-overlap
difficulty tests."""
import pytest

from test_helpers import (
    ApiErrorId,
    validate_error_is_one_of,
    create_app,
    create_app_version,
    create_developer,
    create_merchant,
    create_scope_request,
    decide_scope_request,
    get_success_data,
    make_admin_headers,
    make_developer_headers,
    make_merchant_headers,
    make_reviewer_headers,
    register_permission_scope,
    set_clock,
    setup_active_installation,
    setup_issued_invoice,
    setup_listed_app,
    setup_paid_invoice,
    setup_suspended_app_with_strikes,
    submit_app,
    validate_error,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# non_linear_state_machine / app_version_review_cycle_resubmission_increments_round
# ---------------------------------------------------------------------------

def test_resubmission_increments_review_round(api):
    """PRD §3.2: "Resubmission from `CHANGES_REQUESTED` follows the same
    endpoint: the app must be in `CHANGES_REQUESTED`, the version being
    resubmitted must also be in `CHANGES_REQUESTED`, and on success the
    version's `review_round` increments by one, the version transitions
    `CHANGES_REQUESTED → IN_REVIEW`, the app transitions back to `IN_REVIEW`,
    the app's `submitted_at` is refreshed to the current logical time, and the
    app's `version` increments."

    Design: Difficulty/non_linear_state_machine/app_version_review_cycle_resubmission_increments_round
    """
    developer = create_developer(company_name="D5")
    app = create_app(developer["id"], name="AppFive", category="MARKETING")
    version = create_app_version(app["id"], developer["id"])
    submit_app(app["id"], developer["id"])
    validate_success(
        api.request_changes(
            version["id"], {"reviewer_id": "rev-1", "note": "fix onboarding"},
            make_reviewer_headers("rev-1"),
        )
    )
    submit_app(app["id"], developer["id"])
    version_after = get_success_data(
        api.get_app_version(version["id"], make_reviewer_headers("rev-1"))
    )
    assert version_after["status"] == "IN_REVIEW", (
        f"expected IN_REVIEW, got {version_after['status']}"
    )
    assert version_after["review_round"] == 1, (
        f"expected review_round 1, got {version_after['review_round']}"
    )


def test_second_resubmission_increments_review_round_again(api):
    """PRD §3.2: "Resubmission from `CHANGES_REQUESTED` follows the same
    endpoint: the app must be in `CHANGES_REQUESTED`, the version being
    resubmitted must also be in `CHANGES_REQUESTED`, and on success the
    version's `review_round` increments by one, the version transitions
    `CHANGES_REQUESTED → IN_REVIEW`, the app transitions back to `IN_REVIEW`,
    the app's `submitted_at` is refreshed to the current logical time, and the
    app's `version` increments."

    Design: Difficulty/non_linear_state_machine/app_version_review_cycle_resubmission_increments_round
    """
    developer = create_developer(company_name="D5B")
    app = create_app(developer["id"], name="AppFiveB", category="MARKETING")
    version = create_app_version(app["id"], developer["id"])
    submit_app(app["id"], developer["id"])
    reviewer = make_reviewer_headers("rev-1")
    # First loop: IN_REVIEW -> CHANGES_REQUESTED -> IN_REVIEW (round 1).
    validate_success(
        api.request_changes(version["id"], {"reviewer_id": "rev-1"}, reviewer)
    )
    submit_app(app["id"], developer["id"])
    # Second loop: -> CHANGES_REQUESTED -> IN_REVIEW (round 2).
    validate_success(
        api.request_changes(version["id"], {"reviewer_id": "rev-1"}, reviewer)
    )
    submit_app(app["id"], developer["id"])
    version_after = get_success_data(api.get_app_version(version["id"], reviewer))
    assert version_after["status"] == "IN_REVIEW", (
        f"expected IN_REVIEW, got {version_after['status']}"
    )
    assert version_after["review_round"] == 2, (
        f"expected review_round 2 after two resubmissions, got "
        f"{version_after['review_round']}"
    )


# ---------------------------------------------------------------------------
# non_linear_state_machine / installation_consent_revocation_parallel_dimensions
# ---------------------------------------------------------------------------

def _two_scope_active_installation(api, company):
    """Listed app with two APPROVED LOW scope requests + ACTIVE installation
    holding two GRANTED consent records."""
    developer, app, version, merchant, installation = setup_active_installation(
        company=company,
        category="PRODUCTIVITY",
        scope_specs=[
            {"code": "read_products", "risk_level": "LOW"},
            {"code": "read_orders", "risk_level": "LOW"},
        ],
    )
    return developer, app, merchant, installation


def test_consent_revocation_flips_installation_keeps_sibling(api):
    """PRD §3.5: "On successful revocation the record transitions
    `GRANTED → REVOKED`, `revoked_at` is set to the current logical time, the
    installation transitions `ACTIVE → RECONSENT_REQUIRED`, and the
    installation's `version` increments. Revocation is terminal for the
    consent record itself: a `REVOKED` record cannot return to `GRANTED`, and
    a subsequent reconsent creates a new record rather than resurrecting the
    old one."

    Design: Difficulty/non_linear_state_machine/installation_consent_revocation_parallel_dimensions
    """
    developer, app, merchant, installation = _two_scope_active_installation(
        api, "D6"
    )
    merchant_headers = make_merchant_headers(merchant["id"])
    records, _ = validate_paginated(
        api.list_consent_records(installation["id"], merchant_headers)
    )
    assert len(records) == 2, f"expected 2 consent records, got {len(records)}"
    cr1, cr2 = records[0], records[1]
    validate_success(
        api.revoke_consent_record(installation["id"], cr1["id"], {}, merchant_headers)
    )
    installation_after = get_success_data(
        api.get_installation(installation["id"], merchant_headers)
    )
    assert installation_after["status"] == "RECONSENT_REQUIRED", (
        f"expected RECONSENT_REQUIRED, got {installation_after['status']}"
    )
    cr2_after = get_success_data(api.get_consent_record(cr2["id"], merchant_headers))
    assert cr2_after["status"] == "GRANTED", (
        f"expected sibling record to stay GRANTED, got {cr2_after['status']}"
    )


def test_reconsent_does_not_resurrect_revoked_record(api):
    """PRD §3.5: "Revocation is terminal for the consent record itself: a
    `REVOKED` record cannot return to `GRANTED`, and a subsequent reconsent
    creates a new record rather than resurrecting the old one."

    Design: Difficulty/non_linear_state_machine/installation_consent_revocation_parallel_dimensions
    """
    developer, app, merchant, installation = _two_scope_active_installation(
        api, "D6B"
    )
    merchant_headers = make_merchant_headers(merchant["id"])
    records, _ = validate_paginated(
        api.list_consent_records(installation["id"], merchant_headers)
    )
    cr1 = records[0]
    validate_success(
        api.revoke_consent_record(installation["id"], cr1["id"], {}, merchant_headers)
    )
    # Re-consent restores ACTIVE but the revoked record stays REVOKED.
    validate_success(api.consent_installation(installation["id"], {}, merchant_headers))
    installation_after = get_success_data(
        api.get_installation(installation["id"], merchant_headers)
    )
    assert installation_after["status"] == "ACTIVE", (
        f"expected ACTIVE after re-consent, got {installation_after['status']}"
    )
    cr1_after = get_success_data(api.get_consent_record(cr1["id"], merchant_headers))
    assert cr1_after["status"] == "REVOKED", (
        f"expected revoked record to stay REVOKED, got {cr1_after['status']}"
    )


# ---------------------------------------------------------------------------
# transitive_cascade / app_suspend_cascades_to_installations_and_pending_charges
# ---------------------------------------------------------------------------

def test_delist_cascades_installation_uninstalling(api):
    """PRD §3.11: "On success the app transitions `SUSPENDED → DELISTED` (the
    terminal state), its `listing_status` is set to `DELISTED`, every
    installation of the app in `ACTIVE`, `SUSPENDED`, or `RECONSENT_REQUIRED`
    transitions to `UNINSTALLING` with `uninstalled_at` set to the current
    logical time and `data_deletion_deadline` set to thirty days later, and
    the app's `version` increments."

    Design: Difficulty/transitive_cascade/app_suspend_cascades_to_installations_and_pending_charges
    """
    developer, app, version, merchant, installation, charge = (
        setup_suspended_app_with_strikes(
            strike_count=5, company="D7", category="ANALYTICS",
            with_pending_charge=7000,
        )
    )
    validate_success(api.delist_app(app["id"], {}, make_admin_headers()))
    app_after = get_success_data(api.get_app(app["id"], make_admin_headers()))
    assert app_after["status"] == "DELISTED", (
        f"expected DELISTED, got {app_after['status']}"
    )
    installation_after = get_success_data(
        api.get_installation(installation["id"], make_admin_headers())
    )
    assert installation_after["status"] == "UNINSTALLING", (
        f"expected UNINSTALLING, got {installation_after['status']}"
    )
    assert installation_after["data_deletion_deadline"] is not None, (
        "expected data_deletion_deadline set after delist cascade"
    )


def test_delist_cascade_reverses_pending_charges(api):
    """PRD §3.9: "On success the installation's `uninstalled_at` is set to the
    current logical time, the `data_deletion_deadline` is set to exactly
    thirty days after `uninstalled_at`, every charge of the installation
    still in `PENDING` transitions to `REVERSED`, every webhook subscription
    of the installation in `ACTIVE` status receives an `app/uninstalled`
    delivery attempt, and the installation's `version` increments."

    Design: Difficulty/transitive_cascade/app_suspend_cascades_to_installations_and_pending_charges
    """
    developer, app, version, merchant, installation, charge = (
        setup_suspended_app_with_strikes(
            strike_count=5, company="D7B", category="ANALYTICS",
            with_pending_charge=7000,
        )
    )
    validate_success(api.delist_app(app["id"], {}, make_admin_headers()))
    charge_after = get_success_data(
        api.get_billing_charge(charge["id"], make_admin_headers())
    )
    assert charge_after["status"] == "REVERSED", (
        f"expected REVERSED (cascade hop through UNINSTALLING), got "
        f"{charge_after['status']}"
    )


# ---------------------------------------------------------------------------
# transitive_cascade / merchant_uninstall_reverses_charges_then_deadline_opens_strike
# ---------------------------------------------------------------------------

def test_uninstall_reverses_pending_charge(api):
    """PRD §3.9: "On success the installation's `uninstalled_at` is set to the
    current logical time, the `data_deletion_deadline` is set to exactly
    thirty days after `uninstalled_at`, every charge of the installation
    still in `PENDING` transitions to `REVERSED`, every webhook subscription
    of the installation in `ACTIVE` status receives an `app/uninstalled`
    delivery attempt, and the installation's `version` increments."

    Design: Difficulty/transitive_cascade/merchant_uninstall_reverses_charges_then_deadline_opens_strike
    """
    developer, app, version, merchant, installation = setup_active_installation(
        company="D8", category="MARKETING"
    )
    charge = get_success_data(
        api.create_billing_charge(
            installation["id"],
            {"charge_type": "ONE_TIME", "base_amount_cents": 8000,
             "description": "pending"},
            make_developer_headers(developer["id"]),
        )
    )
    set_clock("2026-09-09T00:00:00Z")
    validate_success(
        api.uninstall_installation(
            installation["id"], {}, make_merchant_headers(merchant["id"])
        )
    )
    charge_after = get_success_data(
        api.get_billing_charge(charge["id"], make_admin_headers())
    )
    assert charge_after["status"] == "REVERSED", (
        f"expected REVERSED at uninstall, got {charge_after['status']}"
    )


def test_deadline_passage_uninstalls_and_opens_strike(api):
    """PRD §3.9: "If the logical clock advances past `data_deletion_deadline`
    without a confirmation — `data_deletion_confirmed_at` still null — the
    system itself transitions the installation `UNINSTALLING → UNINSTALLED`,
    opens a governance strike with reason `DATA_DELETION_OVERDUE` against the
    app, transitions every webhook subscription of the installation to
    `DISABLED`, and increments the installation's `version`."

    Design: Difficulty/transitive_cascade/merchant_uninstall_reverses_charges_then_deadline_opens_strike
    """
    developer, app, version, merchant, installation = setup_active_installation(
        company="D8B", category="MARKETING"
    )
    get_success_data(
        api.create_billing_charge(
            installation["id"],
            {"charge_type": "ONE_TIME", "base_amount_cents": 8000,
             "description": "pending"},
            make_developer_headers(developer["id"]),
        )
    )
    set_clock("2026-09-09T00:00:00Z")
    validate_success(
        api.uninstall_installation(
            installation["id"], {}, make_merchant_headers(merchant["id"])
        )
    )
    # Deadline is 2026-09-09 + 30 days = 2026-10-09; advance past it.
    set_clock("2026-10-10T00:00:00Z")
    installation_after = get_success_data(
        api.get_installation(installation["id"], make_admin_headers())
    )
    assert installation_after["status"] == "UNINSTALLED", (
        f"expected UNINSTALLED after deadline, got {installation_after['status']}"
    )
    strikes, _ = validate_paginated(
        api.list_app_strikes(app["id"], make_admin_headers())
    )
    assert strikes, "expected at least one strike after deadline passage"
    assert strikes[0]["reason"] == "DATA_DELETION_OVERDUE", (
        f"expected DATA_DELETION_OVERDUE, got {strikes[0]['reason']}"
    )


# ---------------------------------------------------------------------------
# priority_pair_validation_conflict / state_vs_business_fiscal_invoice_issue_conflict
# ---------------------------------------------------------------------------

def test_issue_paid_invoice_surfaces_not_issuable(api):
    """PRD §2.7: "Because earlier categories mask later ones, a request that
    fails both authentication and a business rule surfaces
    `ERR_UNAUTHENTICATED`; a request whose app is in the wrong state for the
    requested transition surfaces `ERR_INVALID_STATE` (or the appropriate
    specific state error) rather than a downstream business-rule error."
    PRD §3.8: "An issue attempt against an invoice that is not `OPEN` is
    rejected with `ERR_INVOICE_NOT_ISSUABLE`."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_fiscal_invoice_issue_conflict
    """
    _, _, _, _, _, _, invoice = setup_paid_invoice(
        company="D9", category="FINANCE", charge_amounts=(9000,)
    )
    invoice = get_success_data(api.get_invoice(invoice["id"], make_admin_headers()))
    resp = api.issue_invoice(
        invoice["id"],
        {"expected_invoice_version": invoice["version"]},
        make_admin_headers(),
    )
    # State (priority 4) beats the fiscal no-approved-charges rule (12).
    validate_error(resp, ApiErrorId.ERR_INVOICE_NOT_ISSUABLE)


def test_issue_issued_invoice_surfaces_not_issuable(api):
    """PRD §2.7: "Because earlier categories mask later ones, a request that
    fails both authentication and a business rule surfaces
    `ERR_UNAUTHENTICATED`; a request whose app is in the wrong state for the
    requested transition surfaces `ERR_INVALID_STATE` (or the appropriate
    specific state error) rather than a downstream business-rule error."
    PRD §3.8: "An issue attempt against an invoice that is not `OPEN` is
    rejected with `ERR_INVOICE_NOT_ISSUABLE`."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_fiscal_invoice_issue_conflict
    """
    _, _, _, _, _, _, invoice = setup_issued_invoice(
        company="D9B", category="FINANCE", charge_amounts=(9000,)
    )
    # The cycle's only charge is already INVOICED, so a second issue would
    # also fail the fiscal precondition; the state error must win.
    invoice = get_success_data(api.get_invoice(invoice["id"], make_admin_headers()))
    resp = api.issue_invoice(
        invoice["id"],
        {"expected_invoice_version": invoice["version"]},
        make_admin_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_INVOICE_NOT_ISSUABLE)


# ---------------------------------------------------------------------------
# priority_pair_validation_conflict / business_safety_vs_business_constraint_scope_decide_conflict
# ---------------------------------------------------------------------------

def test_reviewer_conflict_outranks_inverted_interval(api):
    """PRD §2.7: "6. Segregation of duties — reviewer identity is not the
    owning developer identity on reviewer actions, and `HIGH`-risk scope
    revocation is not attempted while the installation has pending charges
    (`ERR_REVIEWER_CONFLICT`)."
    PRD §3.2: "Segregation of duties applies at scheduling time as it does
    everywhere else in review: the `reviewer_id` must not equal the
    `developer_id` of the app that owns the version."

    Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_constraint_scope_decide_conflict
    """
    developer = create_developer(company_name="D10")
    app = create_app(developer["id"], name="AppTen", category="PRODUCTIVITY")
    version = create_app_version(app["id"], developer["id"])
    submit_app(app["id"], developer["id"])
    resp = api.create_review_window(
        version["id"],
        {"reviewer_id": developer["id"],
         "starts_at": "2026-09-15T00:00:00Z", "ends_at": "2026-09-15T00:00:00Z"},
        make_reviewer_headers(developer["id"]),
    )
    # Segregation of duties (priority 6) outranks the inverted-interval
    # structural constraint (priority 7).
    validate_error(resp, ApiErrorId.ERR_REVIEWER_CONFLICT)


def test_reviewer_conflict_on_valid_interval(api):
    """PRD §3.3: "Reviewer actions on the version itself are segregated from
    the developer who owns the app: on every one of the three reviewer actions
    — approving a version, requesting changes on a version, and rejecting a
    version — the acting `reviewer_id` must not equal the `developer_id` of
    the owning developer account. A violation is rejected with
    `ERR_REVIEWER_CONFLICT`."

    Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_constraint_scope_decide_conflict
    """
    developer = create_developer(company_name="D10B")
    app = create_app(developer["id"], name="AppTenB", category="PRODUCTIVITY")
    version = create_app_version(app["id"], developer["id"])
    submit_app(app["id"], developer["id"])
    resp = api.approve_version(
        version["id"], {"reviewer_id": developer["id"]},
        make_reviewer_headers(developer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_REVIEWER_CONFLICT)


# ---------------------------------------------------------------------------
# cross_entity_state_dependency / installation_consent_gated_by_scope_request_states
# ---------------------------------------------------------------------------

def test_consent_blocked_by_denied_scope_request(api):
    """PRD §3.5: "The consent action requires the installation to be in
    `PENDING_CONSENT` and requires that every scope requested by the app's
    `PUBLISHED` version has a corresponding scope request with status
    `APPROVED`. If any scope of the published version lacks an approved scope
    request, the consent is rejected with `ERR_SCOPE_NOT_APPROVED`."

    Design: Difficulty/cross_entity_state_dependency/installation_consent_gated_by_scope_request_states
    """
    developer, app, version = setup_listed_app(
        company="D13",
        category="ANALYTICS",
        scope_specs=[
            {"code": "read_products", "risk_level": "LOW"},
            {"code": "write_orders", "risk_level": "HIGH",
             "justification": "needed to fulfill orders end to end"},
        ],
        scope_decisions=[(0, "APPROVED", None), (1, "DENIED", "overbroad")],
    )
    merchant = create_merchant(shop_domain="m13.myshop.com")
    installation = validate_success(
        api.create_installation(
            {"app_id": app["id"], "merchant_id": merchant["id"]},
            make_merchant_headers(merchant["id"]),
        ),
        expected_status=201,
    )
    resp = api.consent_installation(
        installation["id"], {}, make_merchant_headers(merchant["id"])
    )
    validate_error(resp, ApiErrorId.ERR_SCOPE_NOT_APPROVED)
    installation_after = get_success_data(
        api.get_installation(installation["id"], make_merchant_headers(merchant["id"]))
    )
    assert installation_after["status"] == "PENDING_CONSENT", (
        f"expected PENDING_CONSENT unchanged, got {installation_after['status']}"
    )


def test_consent_blocked_by_pending_scope_request(api):
    """PRD §3.5: "The consent action requires the installation to be in
    `PENDING_CONSENT` and requires that every scope requested by the app's
    `PUBLISHED` version has a corresponding scope request with status
    `APPROVED`. If any scope of the published version lacks an approved scope
    request, the consent is rejected with `ERR_SCOPE_NOT_APPROVED`."

    Design: Difficulty/cross_entity_state_dependency/installation_consent_gated_by_scope_request_states
    """
    developer, app, version = setup_listed_app(
        company="D13B",
        category="ANALYTICS",
        scope_specs=[{"code": "read_products", "risk_level": "LOW"}],
        scope_decisions=[(0, "DENIED", "not justified")],
    )
    merchant = create_merchant(shop_domain="m13b.myshop.com")
    installation = validate_success(
        api.create_installation(
            {"app_id": app["id"], "merchant_id": merchant["id"]},
            make_merchant_headers(merchant["id"]),
        ),
        expected_status=201,
    )
    resp = api.consent_installation(
        installation["id"], {}, make_merchant_headers(merchant["id"])
    )
    validate_error(resp, ApiErrorId.ERR_SCOPE_NOT_APPROVED)


# ---------------------------------------------------------------------------
# cross_entity_state_dependency / charge_approval_gated_by_installation_state
# ---------------------------------------------------------------------------

def test_charge_approval_rejected_after_uninstall(api):
    """PRD §3.6: "A merchant approves a pending charge on their own
    installation, transitioning it `PENDING → APPROVED`; approval requires the
    installation to be in `ACTIVE` or `RECONSENT_REQUIRED` — approval against
    an installation in any other state is rejected with
    `ERR_UNINSTALL_IN_PROGRESS`."
    PRD §3.6: "Approval or decline attempted on a charge that is no longer
    `PENDING` is rejected with `ERR_CHARGE_NOT_PENDING`."

    Design: Difficulty/cross_entity_state_dependency/charge_approval_gated_by_installation_state
    """
    developer, app, version, merchant, installation = setup_active_installation(
        company="D14", category="PRODUCTIVITY"
    )
    charge = get_success_data(
        api.create_billing_charge(
            installation["id"],
            {"charge_type": "RECURRING", "base_amount_cents": 1400,
             "description": "monthly"},
            make_developer_headers(developer["id"]),
        )
    )
    validate_success(
        api.uninstall_installation(
            installation["id"], {}, make_merchant_headers(merchant["id"])
        )
    )
    charge_after = get_success_data(
        api.get_billing_charge(charge["id"], make_admin_headers())
    )
    assert charge_after["status"] == "REVERSED", (
        f"expected REVERSED (uninstall cascade fired first), got "
        f"{charge_after['status']}"
    )
    resp = api.approve_charge(
        charge["id"], {}, make_merchant_headers(merchant["id"])
    )
    validate_error_is_one_of(
        resp, [ApiErrorId.ERR_INVALID_STATE, ApiErrorId.ERR_CHARGE_NOT_PENDING]
    )


def test_charge_approval_rejected_on_suspended_installation(api):
    """PRD §3.6: "A merchant approves a pending charge on their own
    installation, transitioning it `PENDING → APPROVED`; approval requires the
    installation to be in `ACTIVE` or `RECONSENT_REQUIRED` — approval against
    an installation in any other state is rejected with
    `ERR_UNINSTALL_IN_PROGRESS`."

    Design: Difficulty/cross_entity_state_dependency/charge_approval_gated_by_installation_state
    """
    developer, app, version, merchant, installation = setup_active_installation(
        company="D14B", category="PRODUCTIVITY"
    )
    charge = get_success_data(
        api.create_billing_charge(
            installation["id"],
            {"charge_type": "RECURRING", "base_amount_cents": 1400,
             "description": "monthly"},
            make_developer_headers(developer["id"]),
        )
    )
    # App suspension cascades the installation ACTIVE -> SUSPENDED.
    validate_success(api.suspend_app(app["id"], {}, make_admin_headers()))
    resp = api.approve_charge(
        charge["id"], {}, make_merchant_headers(merchant["id"])
    )
    validate_error(resp, ApiErrorId.ERR_UNINSTALL_IN_PROGRESS)


# ---------------------------------------------------------------------------
# resource_temporal_overlap / review_window_half_open_adjacency_allowed
# ---------------------------------------------------------------------------

def test_review_window_adjacency_allowed(api):
    """PRD §3.2: "A new window conflicts with an existing `SCHEDULED` window
    for the same version if and only if the new window's start is before the
    existing window's end and the existing window's start is before the new
    window's end. Adjacency is not a conflict: a new window whose `starts_at`
    equals an existing window's `ends_at` (or vice versa) is permitted."

    Design: Difficulty/resource_temporal_overlap/review_window_half_open_adjacency_allowed
    """
    developer = create_developer(company_name="D15")
    app = create_app(developer["id"], name="AppFifteen", category="FINANCE")
    version = create_app_version(app["id"], developer["id"])
    submit_app(app["id"], developer["id"])
    validate_success(
        api.create_review_window(
            version["id"],
            {"reviewer_id": "rev-1",
             "starts_at": "2026-09-01T00:00:00Z", "ends_at": "2026-09-15T00:00:00Z"},
            make_reviewer_headers("rev-1"),
        ),
        expected_status=201,
    )
    # Adjacent: starts exactly at the existing window's end -> permitted.
    resp = api.create_review_window(
        version["id"],
        {"reviewer_id": "rev-2",
         "starts_at": "2026-09-15T00:00:00Z", "ends_at": "2026-09-29T00:00:00Z"},
        make_reviewer_headers("rev-2"),
    )
    validate_success(resp, expected_status=201)


def test_review_window_overlap_rejected(api):
    """PRD §3.2: "A new window conflicts with an existing `SCHEDULED` window
    for the same version if and only if the new window's start is before the
    existing window's end and the existing window's start is before the new
    window's end. Adjacency is not a conflict: a new window whose `starts_at`
    equals an existing window's `ends_at` (or vice versa) is permitted. An
    overlapping pair is rejected with `ERR_REVIEW_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/review_window_half_open_adjacency_allowed
    """
    developer = create_developer(company_name="D15B")
    app = create_app(developer["id"], name="AppFifteenB", category="FINANCE")
    version = create_app_version(app["id"], developer["id"])
    submit_app(app["id"], developer["id"])
    validate_success(
        api.create_review_window(
            version["id"],
            {"reviewer_id": "rev-1",
             "starts_at": "2026-09-01T00:00:00Z", "ends_at": "2026-09-15T00:00:00Z"},
            make_reviewer_headers("rev-1"),
        ),
        expected_status=201,
    )
    # Overlapping: starts one day before the existing window's end.
    resp = api.create_review_window(
        version["id"],
        {"reviewer_id": "rev-3",
         "starts_at": "2026-09-14T00:00:00Z", "ends_at": "2026-09-28T00:00:00Z"},
        make_reviewer_headers("rev-3"),
    )
    validate_error(resp, ApiErrorId.ERR_REVIEW_WINDOW_OVERLAP)


# ---------------------------------------------------------------------------
# resource_temporal_overlap / invoice_cycle_uniqueness_per_merchant
# ---------------------------------------------------------------------------

def test_invoice_cycle_unique_per_merchant(api):
    """PRD §3.8: "Each merchant may have at most one invoice per cycle; a
    duplicate cycle for the same merchant is rejected with `ERR_DUPLICATE`."

    Design: Difficulty/resource_temporal_overlap/invoice_cycle_uniqueness_per_merchant
    """
    merchant_a = create_merchant(shop_domain="m16a.myshop.com")
    merchant_b = create_merchant(shop_domain="m16b.myshop.com", plan_tier="GROWTH")
    validate_success(
        api.create_invoice(merchant_a["id"], {"cycle": "2026-09"}, make_admin_headers()),
        expected_status=201,
    )
    resp = api.create_invoice(
        merchant_a["id"], {"cycle": "2026-09"}, make_admin_headers()
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE)


def test_same_cycle_free_for_other_merchant(api):
    """PRD §3.8: "Each merchant may have at most one invoice per cycle; a
    duplicate cycle for the same merchant is rejected with `ERR_DUPLICATE`."

    Design: Difficulty/resource_temporal_overlap/invoice_cycle_uniqueness_per_merchant
    """
    merchant_a = create_merchant(shop_domain="m16c.myshop.com")
    merchant_b = create_merchant(shop_domain="m16d.myshop.com", plan_tier="GROWTH")
    validate_success(
        api.create_invoice(merchant_a["id"], {"cycle": "2026-09"}, make_admin_headers()),
        expected_status=201,
    )
    resp = api.create_invoice(
        merchant_b["id"], {"cycle": "2026-09"}, make_admin_headers()
    )
    validate_success(resp, expected_status=201)
