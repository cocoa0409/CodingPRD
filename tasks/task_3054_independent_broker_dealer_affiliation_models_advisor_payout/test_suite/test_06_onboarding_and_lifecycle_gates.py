"""Onboarding gates, declared defaults and the departure settlement cascade."""
from test_helpers import (
    api_client, get_success_data, validate_error, validate_paginated, ApiErrorId,
    refresh_advisor, create_branch, create_advisor, create_loan, enroll_advisor,
    setup_active_advisor, setup_funded_period,
    open_account, open_period, contest_account, settle_retention,
    advance_period, retire_loan,
    setup_retention_scenario,
    make_advisor_ops_headers,
    PLATFORM_ADMIN, COMPLIANCE_OFFICER,
)


# ─── corner: entities ─────────────────────────────────

def test_a_new_branch_starts_unsupervised_and_draft():
    """PRD §2.4: "It also carries an `osj_enabled` flag that begins `false` and stays false
    until the first supervisory enrollment completes."
    PRD §2.4: "`current_payout_period_id` points at the payout period currently tagged to
    the branch, remaining null until the first period is opened for it."

    Design: Corner/entities/branch_create_returns_every_declared_default_field
    """
    branch = create_branch(branch_code="SUP-1")
    assert branch["state"] == "UNSUPERVISED"
    assert branch["status"] == "DRAFT"
    assert branch["osj_enabled"] is False
    assert branch["supervising_advisor_count"] == 0
    assert branch["current_payout_period_id"] is None
    assert branch["version"] == 1

    reread = get_success_data(api_client.get_branch(branch["id"], PLATFORM_ADMIN))
    assert reread["branch_code"] == "SUP-1"
    assert reread["transmittal_account"] == "TA-4471"

    listing, meta = validate_paginated(api_client.list_branches(PLATFORM_ADMIN))
    assert meta["total_count"] == 1
    assert listing[0]["id"] == branch["id"]


def test_branch_creation_without_the_osj_name_is_a_malformed_request():
    """PRD §2.4: "Every branch is created from four inputs — a `branch_code` that is
    unique and immutable after creation, a display `name`, a `transmittal_account` the
    branch clears through that is likewise unique, and an `osj_name`".
    PRD §2.10: "1. Authentication: `X-User-Role` must be present and must
    name a declared role, otherwise `ERR_UNAUTHENTICATED` (401)."

    Design: Corner/entities/branch_create_missing_required_osj_name_returns_invalid_request
    """
    response = api_client.create_branch(
        {"branch_code": "SUP-1", "name": "Superset Wealth",
         "transmittal_account": "TA-4471"},
        PLATFORM_ADMIN)
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)

    rows = get_success_data(api_client.list_branches(PLATFORM_ADMIN))
    assert rows == [], "no branch is created for a malformed payload"


# ─── corner: state machines ───────────────────────────

def test_repeating_enrollment_on_an_onboarding_advisor_is_refused():
    """PRD §3.1: "Moving an advisor from `PROSPECT` to `ONBOARDING` requires that the
    advisor has a non-empty `crd_number`".
    PRD §2.10: "From-state: the resource must be in the state the requested transition
    requires, otherwise `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/advisor_enrollment_from_active_returns_invalid_state
    """
    create_branch()
    advisor = create_advisor("A-8001", "1234567", "Iris Calloway")
    create_loan(advisor)
    enrolled = enroll_advisor(advisor)
    assert enrolled["status"] == "ONBOARDING"

    response = api_client.enroll_advisor(
        advisor["id"],
        {"expected_advisor_version": refresh_advisor(advisor["id"])["version"]},
        make_advisor_ops_headers(advisor["id"]))
    validate_error(response, ApiErrorId.ERR_INVALID_STATE)

    unchanged = refresh_advisor(advisor["id"])
    assert unchanged["status"] == "ONBOARDING"
    assert unchanged["version"] == enrolled["version"]


def test_enrollment_without_a_transition_loan_is_refused():
    """PRD §3.1: "Enrollment is the only door into the payout grid. Moving an advisor from
    `PROSPECT` to `ONBOARDING` requires that the advisor has a non-empty `crd_number`, that
    the branch named by `primary_branch_code` exists, and — mirroring the real
    transition-assistance contract — that a transition assistance loan for the advisor
    already exists in `REQUESTED` or `ACTIVE` status."
    PRD §3.1: "Enrollment without such a loan is refused with `ERR_NO_TRANSITION_LOAN` at
    HTTP 409."

    Design: Corner/state_machines/enrollment_without_a_transition_loan_returns_no_transition_loan
    """
    create_branch()
    advisor = create_advisor("A-8002", "1234568", "Noor Beaumont")

    response = api_client.enroll_advisor(
        advisor["id"],
        {"expected_advisor_version": advisor["version"]},
        make_advisor_ops_headers(advisor["id"]))
    validate_error(response, ApiErrorId.ERR_NO_TRANSITION_LOAN)
    assert refresh_advisor(advisor["id"])["status"] == "PROSPECT"

    create_loan(advisor)
    enrolled = get_success_data(api_client.enroll_advisor(
        advisor["id"],
        {"expected_advisor_version": refresh_advisor(advisor["id"])["version"]},
        make_advisor_ops_headers(advisor["id"])))
    assert enrolled["status"] == "ONBOARDING"


def test_affiliation_below_the_portability_minimum_is_refused():
    """PRD §3.1: "A book that transferred 5,000 basis points or more of its ingested value
    clears the affiliation minimum; below that the affiliation is refused with
    `ERR_BOOK_PORTABILITY_BELOW_MINIMUM` at HTTP 422."

    Design: Corner/state_machines/affiliation_with_untransferable_book_returns_portability_error
    """
    create_branch()
    from test_helpers import enroll_supervisor, create_advisor_link
    supervisor = create_advisor("A-8003-SUP", "1234570", "Supervisor",
                               primary_branch_code="SUP-1",
                               ingested_book_total_cents=500_000_000,
                               book_transferred_cents=400_000_000)
    enroll_supervisor("SUP-1", "A-8003-SUP")
    create_advisor_link(supervisor, "SUP-1", is_supervisor=True)

    advisor = create_advisor("A-8003", "1234569", "Pere Whitlock",
                             ingested_book_total_cents=500_000_000,
                             book_transferred_cents=200_000_000,
                             protocol_eligible=True)
    create_loan(advisor)
    enroll_advisor(advisor)
    assert refresh_advisor(advisor["id"])["book_portability_pct"] == 4000

    response = api_client.affiliate_advisor(
        advisor["id"],
        {"affiliation_model": "IC",
         "expected_advisor_version": refresh_advisor(advisor["id"])["version"]},
        make_advisor_ops_headers(advisor["id"]))
    validate_error(response, ApiErrorId.ERR_BOOK_PORTABILITY_BELOW_MINIMUM)
    assert refresh_advisor(advisor["id"])["status"] == "ONBOARDING"


def test_affiliation_without_protocol_eligibility_at_six_thousand_is_refused():
    """PRD §3.1: "unless the advisor's prior firm was a protocol signatory, the ratio must
    reach 7,000 basis points, and an advisor who is neither a signatory nor above that
    ratio is refused with `ERR_PORTABILITY_PROTOCOL_FAILURE` at HTTP 403."

    Design: Corner/state_machines/affiliation_with_untransferable_book_returns_portability_error
    """
    create_branch()
    from test_helpers import enroll_supervisor, create_advisor_link
    supervisor = create_advisor("A-8004-SUP", "1234572", "Supervisor",
                               primary_branch_code="SUP-1",
                               ingested_book_total_cents=500_000_000,
                               book_transferred_cents=400_000_000)
    enroll_supervisor("SUP-1", "A-8004-SUP")
    create_advisor_link(supervisor, "SUP-1", is_supervisor=True)

    advisor = create_advisor("A-8004", "1234571", "Dara Osei",
                             ingested_book_total_cents=500_000_000,
                             book_transferred_cents=300_000_000,
                             protocol_eligible=False)
    create_loan(advisor)
    enroll_advisor(advisor)
    assert refresh_advisor(advisor["id"])["book_portability_pct"] == 6000

    response = api_client.affiliate_advisor(
        advisor["id"],
        {"affiliation_model": "IC",
         "expected_advisor_version": refresh_advisor(advisor["id"])["version"]},
        make_advisor_ops_headers(advisor["id"]))
    validate_error(response, ApiErrorId.ERR_PORTABILITY_PROTOCOL_FAILURE)
    assert refresh_advisor(advisor["id"])["status"] == "ONBOARDING"


def test_departure_with_an_outstanding_loan_balance_is_refused():
    """PRD §3.7: "Moving an advisor from `ACTIVE` to `DEPARTING` requires that the
    advisor's `outstanding_loan_balance_cents` is exactly zero — otherwise
    `ERR_LOAN_BALANCE_OUTSTANDING` at HTTP 409".

    Design: Corner/state_machines/departure_with_outstanding_loan_returns_loan_balance_outstanding
    """
    ctx = setup_active_advisor(advisor_code="A-8005", principal_cents=1_000_000,
                               forgiveness_milestone_pct=99)
    advisor = ctx["advisor"]
    assert advisor["outstanding_loan_balance_cents"] == 1_000_000

    response = api_client.start_departure(
        advisor["id"], {"expected_advisor_version": advisor["version"]},
        make_advisor_ops_headers(advisor["id"]))
    validate_error(response, ApiErrorId.ERR_LOAN_BALANCE_OUTSTANDING)
    assert refresh_advisor(advisor["id"])["status"] == "ACTIVE"


def test_departure_is_blocked_by_an_open_period_once_the_loan_is_repaid():
    """PRD §3.7: "and that no payout period tagged to the advisor's primary branch is
    `OPEN` or `REOPENED`, otherwise `ERR_PERIOD_NOT_CLOSED` at HTTP 409."

    Design: Corner/state_machines/departure_with_outstanding_loan_returns_loan_balance_outstanding
    """
    ctx = setup_active_advisor(advisor_code="A-8006", principal_cents=500_000,
                               forgiveness_milestone_pct=100)
    advisor = ctx["advisor"]
    account = open_account(advisor, "A-8006-1", balance_cents=1_000_000)
    # The retirement opens and closes its own July month; the September period is
    # then left OPEN, which is what blocks the departure.
    retire_loan(advisor, account)
    open_period(period_index=2)

    response = api_client.start_departure(
        advisor["id"],
        {"expected_advisor_version": refresh_advisor(advisor["id"])["version"]},
        make_advisor_ops_headers(advisor["id"]))
    validate_error(response, ApiErrorId.ERR_PERIOD_NOT_CLOSED)


def test_a_new_advisor_starts_in_prospect_regardless_of_its_affiliation_model():
    """PRD §3.1: "A newly created advisor sits at `status` `PROSPECT` with
    `retention_status` `NOT_AT_RISK`, and its `book_portability_pct` is derived immediately
    from the transferred and ingested values."

    Design: Corner/state_machines/new_advisor_starts_in_prospect_before_any_enrollment
    """
    create_branch()
    advisor = create_advisor("A-8007", "1234573", "Yara Boateng",
                             affiliation_model="INSTITUTIONAL",
                             eo_coverage_level="PREMIUM",
                             ingested_book_total_cents=900_000_000,
                             book_transferred_cents=720_000_000)
    assert advisor["status"] == "PROSPECT"
    assert advisor["affiliation_model"] == "INSTITUTIONAL"
    assert advisor["eo_coverage_level"] == "PREMIUM"
    assert advisor["book_portability_pct"] == 8000

    loans = get_success_data(api_client.list_payout_loans(
        PLATFORM_ADMIN, {"advisor_code": "A-8007"}))
    assert loans == [], "creation opened no loan"
    accounts = get_success_data(api_client.list_accounts(
        PLATFORM_ADMIN, {"advisor_code": "A-8007"}))
    assert accounts == [], "creation opened no account"


def test_voiding_a_closed_period_voids_its_draft_lines():
    """PRD §3.3: "A period may be voided only from `CLOSED` and only while no line of the
    period has been released or true-upped; otherwise `ERR_PERIOD_ALREADY_POSTED` at HTTP
    409, and voiding moves every draft line of the period to `VOID`."

    Design: Corner/state_machines/payout_line_terminal_void_has_no_outgoing_transition
    """
    ctx = setup_funded_period(advisor_code="A-8008", release=True,
                              entries=((1_000_000, "2026-09-03", "EQUITY"),))
    branch_code = ctx["branch"]["branch_code"]
    advance_period(ctx["period"]["id"], "CLOSED", branch_code)
    advance_period(ctx["period"]["id"], "VOID", branch_code,
                   role_headers=COMPLIANCE_OFFICER)

    period = get_success_data(api_client.get_payout_period(ctx["period"]["id"],
                                                          PLATFORM_ADMIN))
    assert period["state"] == "VOID"

    line = get_success_data(api_client.get_payout_line(ctx["line"]["id"],
                                                      PLATFORM_ADMIN))
    assert line["status"] == "VOID"
    assert line["release_amount_cents"] == 0


def test_an_entry_released_before_the_voiding_keeps_its_released_status():
    """PRD §3.3: "Release recomputes the advisor's trailing-twelve-month production and the
    period's gross."
    PRD §3.3: "voiding moves every draft line of the period to `VOID`."

    Design: Corner/state_machines/payout_line_terminal_void_has_no_outgoing_transition
    """
    ctx = setup_funded_period(advisor_code="A-8009", release=True,
                              entries=((1_000_000, "2026-09-03", "EQUITY"),))
    branch_code = ctx["branch"]["branch_code"]
    entry = ctx["entries"][0]
    advance_period(ctx["period"]["id"], "CLOSED", branch_code)
    advance_period(ctx["period"]["id"], "VOID", branch_code,
                   role_headers=COMPLIANCE_OFFICER)

    reread = get_success_data(api_client.get_revenue_entry(entry["id"], PLATFORM_ADMIN))
    assert reread["status"] == "RELEASED"

    repeat = api_client.release_revenue_entry(
        entry["id"], make_advisor_ops_headers(ctx["advisor"]["id"]))
    validate_error(repeat, ApiErrorId.ERR_INVALID_STATE)


# ─── corner: cross_cutting_complexity_layers ──────────

def _settle_discharge_fixture(advisor_code):
    """A DEPARTING advisor whose loan is settled and whose contest has closed.

    The advisor's transition-assistance loan is driven to a zero balance before
    the departure — the departure gate of PRD 3.7 reads the advisor's
    outstanding loan balance and refuses a departure while any is left — and the
    retention contest is then closed, which is the precondition the departure
    settlement requires.
    """
    ctx = setup_retention_scenario(
        advisor_code=advisor_code,
        account_numbers=(f"{advisor_code}-P1", f"{advisor_code}-P2"),
        account_balances=(10_000_000, 10_000_000))
    accounts = ctx["accounts"]
    advisor = ctx["advisor"]
    transition = ctx["transition"]
    assert advisor["outstanding_loan_balance_cents"] == 0

    # Every account the transition counts sits in the transfer window, and each
    # of them is contested before the contest closes on them all.
    for account in accounts:
        contest_account(transition["id"], account["id"], 500)
    get_success_data(settle_retention(
        transition["id"], [account["id"] for account in accounts],
        refresh_advisor(advisor["id"])))

    loan = get_success_data(api_client.get_payout_loan(ctx["loan"]["id"],
                                                      PLATFORM_ADMIN))
    return {"ctx": ctx, "accounts": accounts[:2],
            "milestone_account": ctx["milestone_account"],
            "advisor": refresh_advisor(advisor["id"]),
            "transition": transition, "loan": loan}


def test_settling_a_departure_discharges_the_transition_loan_to_zero():
    """PRD §3.7: "discharges every loan still at `ACTIVE` or `AMORTIZING` as described in
    §3.2, driving `outstanding_loan_balance_cents` to zero".
    PRD §3.2: "A loan is discharged when the advisor's departure is settled."

    Design: Corner/cross_cutting_complexity_layers/departure_settlement_discharges_the_transition_loan_to_zero
    """
    fx = _settle_discharge_fixture("A-8010")
    assert fx["loan"]["remaining_balance_cents"] == 0

    settled = get_success_data(api_client.settle_departure(
        fx["advisor"]["id"],
        {"expected_advisor_version": fx["advisor"]["version"]},
        COMPLIANCE_OFFICER))
    assert settled["status"] == "DEPARTED"
    assert settled["retention_status"] == "DEPARTED_CONFIRMED"
    assert settled["outstanding_loan_balance_cents"] == 0

    loan = get_success_data(api_client.get_payout_loan(fx["loan"]["id"], PLATFORM_ADMIN))
    assert loan["remaining_balance_cents"] == 0, (
        "the settled departure leaves no residual loan balance")


# ─── corner: endpoints (bulk import, crd change) ──────

def test_a_bulk_import_reports_the_created_and_skipped_rows():
    """PRD §3.1: "Recruiting lists arrive through a bulk capability whose payload is an
    array of `advisors`; each parsed row is created at `PROSPECT`, while a row whose branch
    or advisor code does not resolve is skipped without rolling back the rows that were
    accepted, and the response reports `created_count`, `skipped_count`,
    `created_advisor_codes`, and `skipped_advisor_codes`."

    Design: Corner/endpoints/bulk_import_reports_created_and_skipped_rows
    """
    create_branch()
    payload = {"advisors": [
        {"advisor_code": "A-9001", "crd_number": "7000001", "full_name": "Ada Reyes",
         "affiliation_model": "IC", "primary_branch_code": "SUP-1",
         "ingested_book_total_cents": 500_000_000,
         "book_transferred_cents": 400_000_000, "protocol_eligible": True},
        {"advisor_code": "A-9002", "crd_number": "7000002", "full_name": "Ben Ortiz",
         "affiliation_model": "HYBRID", "primary_branch_code": "GHOST-9",
         "ingested_book_total_cents": 100_000_000,
         "book_transferred_cents": 80_000_000, "protocol_eligible": False},
        {"advisor_code": "A-9003", "crd_number": "7000003", "full_name": "Cara Lund",
         "affiliation_model": "EMPLOYEE", "primary_branch_code": "SUP-1",
         "ingested_book_total_cents": 200_000_000,
         "book_transferred_cents": 160_000_000, "protocol_eligible": True},
    ]}
    result = get_success_data(api_client.bulk_import_advisors(payload, PLATFORM_ADMIN))
    assert result["created_count"] == 2
    assert result["skipped_count"] == 1
    assert sorted(result["created_advisor_codes"]) == ["A-9001", "A-9003"]
    assert result["skipped_advisor_codes"] == ["A-9002"]


def test_a_bulk_import_does_not_roll_back_the_accepted_rows():
    """PRD §3.1: "a row whose branch or advisor code does not resolve is skipped without
    rolling back the rows that were accepted".
    PRD §3.1: "each parsed row is created at `PROSPECT`".

    Design: Corner/endpoints/bulk_import_reports_created_and_skipped_rows
    """
    create_branch()
    payload = {"advisors": [
        {"advisor_code": "A-9004", "crd_number": "7000011", "full_name": "Ada Reyes",
         "affiliation_model": "IC", "primary_branch_code": "SUP-1",
         "ingested_book_total_cents": 500_000_000,
         "book_transferred_cents": 400_000_000, "protocol_eligible": True},
        {"advisor_code": "A-9005", "crd_number": "7000012", "full_name": "Ben Ortiz",
         "affiliation_model": "HYBRID", "primary_branch_code": "GHOST-9",
         "ingested_book_total_cents": 100_000_000,
         "book_transferred_cents": 80_000_000, "protocol_eligible": False},
        {"advisor_code": "A-9006", "crd_number": "7000013", "full_name": "Cara Lund",
         "affiliation_model": "EMPLOYEE", "primary_branch_code": "SUP-1",
         "ingested_book_total_cents": 200_000_000,
         "book_transferred_cents": 160_000_000, "protocol_eligible": True},
    ]}
    result = get_success_data(api_client.bulk_import_advisors(payload, PLATFORM_ADMIN))
    assert result["created_count"] == 2 and result["skipped_count"] == 1

    rows = get_success_data(api_client.list_advisors(PLATFORM_ADMIN))
    assert len(rows) == 2, "the accepted rows were not rolled back"
    assert {row["status"] for row in rows} == {"PROSPECT"}
    assert {row["advisor_code"] for row in rows} == {"A-9004", "A-9006"}


def test_a_stale_registration_correction_is_refused():
    """PRD §2.8: "A mismatch between the supplied value and the parent's current `version`
    is rejected with `ERR_STALE_VERSION` at HTTP 412".

    Design: Corner/endpoints/crd_change_endpoint_requires_the_current_advisor_version
    """
    create_branch()
    advisor = create_advisor("A-9007", "7000010", "Dana Whitfield")
    stale = advisor["version"] - 1

    response = api_client.change_crd(
        advisor["id"], {"crd_number": "7000099",
                        "expected_advisor_version": stale},
        COMPLIANCE_OFFICER)
    validate_error(response, ApiErrorId.ERR_STALE_VERSION)


def test_a_current_registration_correction_succeeds_and_advances_the_version():
    """PRD §2.6: "- `**version` (integer):** A system-managed integer that increments by one on
    every modification to the resource."
    PRD §2.9: "An `advisor_code` that does not resolve to an advisor yields
    `ERR_ADVISOR_NOT_FOUND` at HTTP 404."

    Design: Corner/endpoints/crd_change_endpoint_requires_the_current_advisor_version
    """
    create_branch()
    advisor = create_advisor("A-9008", "7000020", "Dana Whitfield")

    corrected = get_success_data(api_client.change_crd(
        advisor["id"], {"crd_number": "7000099",
                        "expected_advisor_version": advisor["version"]},
        COMPLIANCE_OFFICER))
    assert corrected["crd_number"] == "7000099"
    assert corrected["version"] == advisor["version"] + 1

    replay = api_client.change_crd(
        advisor["id"], {"crd_number": "7000100",
                        "expected_advisor_version": advisor["version"]},
        COMPLIANCE_OFFICER)
    validate_error(replay, ApiErrorId.ERR_STALE_VERSION)