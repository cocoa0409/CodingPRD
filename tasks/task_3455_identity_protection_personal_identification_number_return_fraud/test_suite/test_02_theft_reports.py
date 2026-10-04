"""Identity-theft report lifecycle tests: the reject/reopen cycle, the
confirm cascade (victim flag + enrollment + pin issuance + supersession), the
closed 60-day review window, and segregation of duties on confirm.

PRD section 3.3.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_identity_theft_report,
    assert_single_active_pin,
    confirm_report,
    confirm_report_payload,
    create_identity_theft_report_payload,
    create_taxpayer,
    create_theft_report,
    get_active_pin,
    get_taxpayer,
    list_pins,
    make_fraud_analyst_headers,
    make_taxpayer_headers,
    opt_in_taxpayer,
    reject_report,
    reopen_report,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["system_admin_headers"]


def _attempt_report(api, taxpayer_id):
    """File a TAXPAYER_REPORT as the taxpayer themselves."""
    return api.create_identity_theft_report(
        taxpayer_id,
        create_identity_theft_report_payload(),
        make_taxpayer_headers(taxpayer_id),
    )


# ─── Reject / reopen cycle ───────────────────────────

def test_theft_report_reject_then_reopen_returns_to_submitted(api):
    """PRD section 3.3: "Rejection is the quiet sibling: a `FraudAnalyst`
    moves a `SUBMITTED` report to `REJECTED` with no side effects."
    PRD section 3.3: "The report lifecycle is cyclic in one place only: a
    `REJECTED` report may be reopened to `SUBMITTED` by the taxpayer
    themselves or by a `TaxpayerAdvocate`, re-entering review."

    Design: Difficulty/non_linear_state_machine/theft_report_reject_reopen_cycle
    """
    set_clock("2027-01-20T00:00:00Z")
    taxpayer = create_taxpayer()
    report = create_theft_report(taxpayer["id"])
    assert report["status"] == "SUBMITTED"

    rejected = reject_report(report["id"])
    assert rejected["status"] == "REJECTED"

    reopened = reopen_report(report["id"], taxpayer_id=taxpayer["id"])
    assert reopened["status"] == "SUBMITTED"


def test_theft_report_confirm_after_reopen_fires_victim_cascade(api):
    """PRD section 3.3: "Confirmation fires a three-link cascade plus a
    stamp: first, the subject taxpayer's `status` becomes `VICTIM_FLAGGED`
    and their `ip_pin_enrollment` becomes `ENROLLED`, incrementing the
    taxpayer's `version`; second, because the taxpayer is now enrolled, a
    `ProtectionPin` is created for the payload tax year in `ACTIVE`; third,
    that minting supersedes any previously `ACTIVE` pin for the same taxpayer
    and tax year; and the report's `confirmed_tax_year` is set to the payload
    `tax_year`."

    Design: Difficulty/non_linear_state_machine/theft_report_reject_reopen_cycle
    """
    set_clock("2027-01-20T00:00:00Z")
    taxpayer = create_taxpayer()
    report = create_theft_report(taxpayer["id"])
    reject_report(report["id"])
    reopen_report(report["id"], taxpayer_id=taxpayer["id"])

    confirmed = confirm_report(report["id"], tax_year=2026)
    assert confirmed["status"] == "CONFIRMED"
    assert confirmed["confirmed_tax_year"] == 2026

    after = get_taxpayer(taxpayer["id"])
    assert after["status"] == "VICTIM_FLAGGED"
    assert after["ip_pin_enrollment"] == "ENROLLED"

    pin = get_active_pin(taxpayer["id"], 2026)
    assert pin["status"] == "ACTIVE"
    assert pin["tax_year"] == 2026


# ─── Confirm cascade: enrollment + pin supersession ──

def _setup_opted_in_taxpayer_with_report():
    """Taxpayer (ONLINE_ACCOUNT preference) opted in for 2026 with pin P1
    ACTIVE, plus a self-filed SUBMITTED theft report."""
    set_clock("2027-01-25T00:00:00Z")
    taxpayer = create_taxpayer(pin_delivery_channel="ONLINE_ACCOUNT")
    opt_in_taxpayer(taxpayer["id"], tax_year=2026)
    pin1 = get_active_pin(taxpayer["id"], 2026)
    report = create_theft_report(
        taxpayer["id"], description="noticed duplicate filing"
    )
    return taxpayer, pin1, report


def test_report_confirm_flags_victim_and_enrolls(api):
    """PRD section 3.3: "Confirmation fires a three-link cascade plus a
    stamp: first, the subject taxpayer's `status` becomes `VICTIM_FLAGGED`
    and their `ip_pin_enrollment` becomes `ENROLLED`, incrementing the
    taxpayer's `version`; second, because the taxpayer is now enrolled, a
    `ProtectionPin` is created for the payload tax year in `ACTIVE`; third,
    that minting supersedes any previously `ACTIVE` pin for the same taxpayer
    and tax year; and the report's `confirmed_tax_year` is set to the payload
    `tax_year`."

    Design: Difficulty/transitive_cascade/report_confirm_enrollment_pin_supersede_cascade
    """
    taxpayer, _pin1, report = _setup_opted_in_taxpayer_with_report()

    confirmed = confirm_report(report["id"], tax_year=2026)
    assert confirmed["status"] == "CONFIRMED"
    assert confirmed["confirmed_tax_year"] == 2026

    after = get_taxpayer(taxpayer["id"])
    assert after["status"] == "VICTIM_FLAGGED"
    assert after["ip_pin_enrollment"] == "ENROLLED"


def test_report_confirm_supersedes_prior_active_pin(api):
    """PRD section 3.3: "third, that minting supersedes any previously
    `ACTIVE` pin for the same taxpayer and tax year".
    PRD section 3.2: "At most one pin may be `ACTIVE` for a given taxpayer
    and tax year, so minting the new pin flips any previously `ACTIVE` pin
    for that same pair to `SUPERSEDED`."

    Design: Difficulty/transitive_cascade/report_confirm_enrollment_pin_supersede_cascade
    """
    taxpayer, pin1, report = _setup_opted_in_taxpayer_with_report()
    confirm_report(report["id"], tax_year=2026)

    pins = list_pins(taxpayer["id"])
    by_id = {p["id"]: p for p in pins}
    assert by_id[pin1["id"]]["status"] == "SUPERSEDED"

    active = assert_single_active_pin(pins, 2026)
    assert active["id"] != pin1["id"]
    assert active["pin_value"] != pin1["pin_value"]


# ─── Review-window exclusivity ───────────────────────

def test_second_report_inside_review_window_rejected(api):
    """PRD section 3.3: "While a taxpayer has a report in `SUBMITTED`, a
    further report for that taxpayer is rejected with
    `ERR_ACTIVE_REPORT_WINDOW` (HTTP 409) whenever the new submission time
    falls inside the closed review window that runs from the earlier report's
    `created_at` through 60 days later, both endpoints inclusive."

    Design: Difficulty/resource_temporal_overlap/report_window_closed_interval_exclusion
    """
    set_clock("2027-01-15T00:00:00Z")
    taxpayer = create_taxpayer()
    create_theft_report(taxpayer["id"])

    # Day 31 of the window (2027-01-15 + 31 days).
    set_clock("2027-02-15T00:00:00Z")
    validate_error(
        _attempt_report(api, taxpayer["id"]), ApiErrorId.ERR_ACTIVE_REPORT_WINDOW
    )

    # Exactly day 60 — the closed window's inclusive end.
    set_clock("2027-03-16T00:00:00Z")
    validate_error(
        _attempt_report(api, taxpayer["id"]), ApiErrorId.ERR_ACTIVE_REPORT_WINDOW
    )


def test_report_after_review_window_accepted(api):
    """PRD section 3.3: "Once the earlier report leaves `SUBMITTED`, or the
    window has fully passed, a new report is accepted."

    Design: Difficulty/resource_temporal_overlap/report_window_closed_interval_exclusion
    """
    set_clock("2027-01-15T00:00:00Z")
    taxpayer = create_taxpayer()
    create_theft_report(taxpayer["id"])
    set_clock("2027-02-15T00:00:00Z")
    validate_error(
        _attempt_report(api, taxpayer["id"]), ApiErrorId.ERR_ACTIVE_REPORT_WINDOW
    )
    set_clock("2027-03-16T00:00:00Z")
    validate_error(
        _attempt_report(api, taxpayer["id"]), ApiErrorId.ERR_ACTIVE_REPORT_WINDOW
    )

    # Day 61 — the first instant outside the closed window.
    set_clock("2027-03-17T00:00:00Z")
    created = validate_success(_attempt_report(api, taxpayer["id"]), 201)
    assert_identity_theft_report(created)
    assert created["status"] == "SUBMITTED"

    rows, meta = validate_paginated(
        api.list_identity_theft_reports(
            taxpayer["id"], make_taxpayer_headers(taxpayer["id"])
        )
    )
    assert meta["total_count"] == 2
    assert len(rows) == 2


# ─── Segregation of duties on confirm ────────────────

def test_sod_report_confirm_by_creator_rejected(api):
    """PRD section 2.1: "Segregation of duties overlays role checks on two
    workflows: confirming an identity-theft report is forbidden to the user
    who created that report, and resolving an advocate case is forbidden to
    the user who opened it. Both violations are rejected with
    `ERR_DUTY_SEGREGATION_VIOLATION` (HTTP 403)."

    Design: Corner/rbac/sod_report_confirm_by_creator_rejected
    """
    set_clock("2027-01-20T00:00:00Z")
    taxpayer = create_taxpayer()
    report = create_theft_report(
        taxpayer["id"],
        creator="analyst",
        creator_user_id="analyst-1",
        description="filed via phone with analyst",
    )
    assert report["created_by_user_id"] == "analyst-1"

    own_confirm = api.confirm_identity_theft_report(
        report["id"], confirm_report_payload(2026),
        make_fraud_analyst_headers("analyst-1"),
    )
    validate_error(own_confirm, ApiErrorId.ERR_DUTY_SEGREGATION_VIOLATION)

    peer_confirm = api.confirm_identity_theft_report(
        report["id"], confirm_report_payload(2026),
        make_fraud_analyst_headers("analyst-2"),
    )
    confirmed = validate_success(peer_confirm, 200)
    assert confirmed["status"] == "CONFIRMED"
    assert confirmed["confirmed_tax_year"] == 2026
