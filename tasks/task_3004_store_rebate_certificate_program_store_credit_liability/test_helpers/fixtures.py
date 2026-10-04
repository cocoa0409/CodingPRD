"""Composite setup helpers.

Most interesting claims require the system to be in a state that takes many
API calls to reach (store + active program + account + receipt + submission +
adjudication + issuance, possibly with clock advances, returns, breakage
runs, and fraud flags). These fixtures encapsulate those chains so tests can
focus on assertions.

Every helper builds its preconditions from scratch using only public
endpoints; the harness restarts the server (empty database) before each
test. All helpers use get_success_data() internally so setup failures
surface as clear "Setup failed" assertion errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_store_payload, create_program_payload, create_program_item_payload,
    create_account_payload, cash_line, create_receipt_payload,
    adjudicate_payload,
)
from .test_users import (
    TEST_USERS, make_customer_headers, make_contractor_headers,
)

ADMIN = TEST_USERS["store_admin_headers"]
GUEST = TEST_USERS["guest_service_headers"]
FRAUD = TEST_USERS["fraud_analyst_headers"]
FINANCE = TEST_USERS["finance_admin_headers"]


# ---------------------------------------------------------------------------
# Tier 1: atomic builders
# ---------------------------------------------------------------------------

def set_clock(to_iso8601):
    """Advance the logical clock; returns the clock response data."""
    return get_success_data(api_client.set_logical_clock(to_iso8601, ADMIN))


def create_store(**overrides):
    payload = create_store_payload(**overrides)
    return get_success_data(api_client.create_store(payload, ADMIN), 201)


def create_program(store_id, **overrides):
    payload = create_program_payload(**overrides)
    return get_success_data(api_client.create_program(store_id, payload, ADMIN), 201)


def create_program_item(store_id, program_id, **overrides):
    payload = create_program_item_payload(**overrides)
    return get_success_data(
        api_client.create_program_item(store_id, program_id, payload, ADMIN), 201
    )


def create_active_program(store_id, items, week_start="2026-09-07",
                          week_end="2026-09-14", activate_clock=None,
                          **program_overrides):
    """DRAFT program + items + ACTIVE. `items` is a list of ProgramItem
    payload overrides dicts. Returns (program, item_rows)."""
    program = create_program(
        store_id, week_start_date=week_start, week_end_date=week_end,
        **program_overrides,
    )
    item_rows = [
        create_program_item(store_id, program["id"], **item) for item in items
    ]
    if activate_clock:
        set_clock(activate_clock)
    program = get_success_data(
        api_client.activate_program(store_id, program["id"], ADMIN)
    )
    return program, item_rows


def create_account(store_id, owner_name="Ann", account_type="RETAIL"):
    payload = create_account_payload(
        owner_name=owner_name, account_type=account_type
    )
    return get_success_data(api_client.create_account(store_id, payload, GUEST), 201)


def create_job(store_id, account_id, job_reference="JOB-1"):
    return get_success_data(
        api_client.create_job_purchase(
            store_id, account_id, {"job_reference": job_reference},
            make_contractor_headers(account_id),
        ),
        201,
    )


def create_receipt(store_id, account_id, lines, purchase_at="2026-09-08T10:00:00Z",
                   job_purchase_id=None, **overrides):
    payload = create_receipt_payload(
        account_id, lines, purchase_at=purchase_at, **overrides
    )
    if job_purchase_id is not None:
        payload["job_purchase_id"] = job_purchase_id
    return get_success_data(api_client.create_receipt(store_id, payload, GUEST), 201)


def list_receipt_lines(store_id, receipt_id):
    return get_success_data(api_client.list_receipt_lines(store_id, receipt_id, GUEST))


# ---------------------------------------------------------------------------
# Tier 2: submission chain
# ---------------------------------------------------------------------------

def _submitter_headers(account, role=None):
    """Ownership-gated submission/resubmit headers: entity-backed roles must
    carry the actual account id as X-User-ID."""
    if role is None:
        role = "Contractor" if account.get("account_type") == "CONTRACTOR" else "Customer"
    if role == "Contractor":
        return make_contractor_headers(account["id"])
    return make_customer_headers(account["id"])


def submit_receipt(store_id, receipt_id, account, role=None):
    return get_success_data(
        api_client.create_submission(
            store_id, {"receipt_id": receipt_id},
            _submitter_headers(account, role),
        ),
        201,
    )


def approve_submission(store_id, submission_id):
    return get_success_data(
        api_client.adjudicate_submission(
            store_id, submission_id, adjudicate_payload("APPROVE"), GUEST
        )
    )


def reject_submission(store_id, submission_id, reason="illegible receipt"):
    return get_success_data(
        api_client.adjudicate_submission(
            store_id, submission_id,
            adjudicate_payload("REJECT", rejection_reason=reason), GUEST,
        )
    )


def resubmit_submission(store_id, submission_id, account, role=None):
    return get_success_data(
        api_client.resubmit_submission(
            store_id, submission_id, _submitter_headers(account, role)
        )
    )


def issue_certificate(store_id, submission_id, issue_clock=None):
    if issue_clock:
        set_clock(issue_clock)
    return get_success_data(
        api_client.issue_certificate(store_id, submission_id, GUEST)
    )


# ---------------------------------------------------------------------------
# Tier 3: composite chains
# ---------------------------------------------------------------------------

def setup_store_with_program(store_overrides=None, items=None,
                             week_start="2026-09-07", week_end="2026-09-14",
                             clock_init="2026-09-07T00:00:00Z"):
    """Store + ACTIVE program with items. Returns dict."""
    if clock_init:
        set_clock(clock_init)
    store = create_store(**(store_overrides or {}))
    program, item_rows = create_active_program(
        store["id"], items if items is not None else [{"sku": "AAA", "rebate_pct": 0.1}],
        week_start=week_start, week_end=week_end,
    )
    return {"store": store, "program": program, "items": item_rows}


def setup_account_with_receipt(store, account_type="RETAIL",
                               owner_name="Ann", lines=None,
                               purchase_at="2026-09-08T10:00:00Z",
                               create_clock="2026-09-08T12:00:00Z",
                               account=None, **receipt_overrides):
    """Account + one receipt. Returns dict with account, receipt. Pass
    `account=` to reuse an existing account instead of creating a new one."""
    if create_clock:
        set_clock(create_clock)
    if account is None:
        account = create_account(store["id"], owner_name=owner_name,
                                 account_type=account_type)
    receipt = create_receipt(
        store["id"], account["id"],
        lines if lines is not None else [
            cash_line(1, "AAA", "TOOLS", 1, 10000)
        ],
        purchase_at=purchase_at,
        **receipt_overrides,
    )
    return {"account": account, "receipt": receipt}


def setup_approved_submission(store, account_type="RETAIL", owner_name="Ann",
                              lines=None, purchase_at="2026-09-08T10:00:00Z",
                              create_clock="2026-09-08T12:00:00Z",
                              account=None, **receipt_overrides):
    """Account + receipt + submission approved (UNDER_REVIEW -> APPROVED).
    Returns dict with account, receipt, submission. Extra keyword arguments
    (e.g. receipt_number) are forwarded to the receipt payload."""
    ctx = setup_account_with_receipt(
        store, account_type=account_type, owner_name=owner_name, lines=lines,
        purchase_at=purchase_at, create_clock=create_clock, account=account,
        **receipt_overrides,
    )
    submission = submit_receipt(store["id"], ctx["receipt"]["id"], ctx["account"])
    submission = approve_submission(store["id"], submission["id"])
    ctx["submission"] = submission
    return ctx


def setup_issued_certificate(store, account_type="RETAIL", owner_name="Ann",
                             lines=None, purchase_at="2026-09-08T10:00:00Z",
                             create_clock="2026-09-08T12:00:00Z",
                             issue_clock="2026-09-10T12:00:00Z",
                             account=None, **receipt_overrides):
    """Full chain: account + receipt + approved submission + issued
    certificate. Returns dict with account, receipt, submission, cert. Extra
    keyword arguments (e.g. receipt_number) are forwarded to the receipt
    payload."""
    ctx = setup_approved_submission(
        store, account_type=account_type, owner_name=owner_name, lines=lines,
        purchase_at=purchase_at, create_clock=create_clock, account=account,
        **receipt_overrides,
    )
    ctx["cert"] = issue_certificate(
        store["id"], ctx["submission"]["id"], issue_clock=issue_clock
    )
    return ctx


def redeem_certificate(store_id, certificate_id, receipt_id, amount_cents):
    return get_success_data(
        api_client.redeem_certificate(
            store_id, certificate_id,
            {"receipt_id": receipt_id, "amount_cents": amount_cents}, GUEST,
        )
    )


def process_return(store_id, receipt_id, lines):
    return get_success_data(
        api_client.create_return(store_id, receipt_id, {"lines": lines}, GUEST)
    )


# ---------------------------------------------------------------------------
# Tier 4: OCC-guarded breakage runs
# ---------------------------------------------------------------------------

def current_store_version(store_id):
    store = get_success_data(api_client.get_store(store_id, FINANCE))
    return store["version"]


def run_breakage(store_id):
    """Breakage run with a freshly-observed store version (OCC)."""
    version = current_store_version(store_id)
    return get_success_data(
        api_client.create_breakage_run(
            store_id, {"expected_store_version": version}, FINANCE
        ),
        201,
    )


# ---------------------------------------------------------------------------
# Tier 5: fraud flags
# ---------------------------------------------------------------------------

def open_duplicate_receipt_flag(store_id, receipt_id, account):
    """Submit once, then submit again to trip the duplicate scan; returns the
    OPEN DUPLICATE_RECEIPT flag row."""
    submit_receipt(store_id, receipt_id, account)
    resp = api_client.create_submission(
        store_id, {"receipt_id": receipt_id}, _submitter_headers(account)
    )
    assert resp.status_code == 409, (
        f"Setup failed: duplicate submission not rejected: {resp.text}"
    )
    flags = get_success_data(
        api_client.list_fraud_flags(
            store_id, FRAUD,
            params={"account_id": account["id"], "flag_type": "DUPLICATE_RECEIPT"},
        )
    )
    assert isinstance(flags, list) and len(flags) == 1, (
        f"Setup failed: expected exactly one DUPLICATE_RECEIPT flag, got {flags!r}"
    )
    return flags[0]
