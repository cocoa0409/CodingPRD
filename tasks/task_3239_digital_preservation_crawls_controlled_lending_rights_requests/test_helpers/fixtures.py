"""Composite setup helpers built from the PRD-declared endpoints.

Every helper builds its preconditions from scratch (the server restarts before
each test) and uses get_success_data() so setup failures surface clearly.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_patron_payload,
    create_accessibility_credential_payload,
    create_partner_library_payload,
    create_work_payload,
    create_scan_batch_payload,
    create_item_payload,
    create_loan_payload,
    create_waitlist_entry_payload,
    create_crawl_job_payload,
    create_capture_payload,
    create_funding_grant_payload,
    create_budget_line_payload,
    create_rights_request_payload,
)
from .test_users import (
    TEST_USERS,
    make_patron_headers,
    make_legal_reviewer_headers,
)

ADMIN = TEST_USERS["admin_headers"]
ANON = TEST_USERS["anonymous_headers"]
LIBADMIN = TEST_USERS["library_admin_headers"]
SCANOP = TEST_USERS["scan_operator_headers"]
CRAWLOP = TEST_USERS["crawl_operator_headers"]
FINANCE = TEST_USERS["finance_admin_headers"]


# --- clock / sweep ---

def set_clock(iso: str) -> dict:
    return get_success_data(api_client.set_clock(iso, ADMIN))


def run_sweep() -> dict:
    return get_success_data(api_client.run_sweep(ADMIN))


# --- simple creates ---

def make_patron(email=None, full_name=None) -> dict:
    payload = create_patron_payload()
    if email is not None:
        payload["email"] = email
    if full_name is not None:
        payload["full_name"] = full_name
    return get_success_data(api_client.create_patron(payload, ANON))


def make_library(**overrides) -> dict:
    return get_success_data(
        api_client.create_partner_library(create_partner_library_payload(**overrides), LIBADMIN)
    )


def make_work(**overrides) -> dict:
    return get_success_data(api_client.create_work(create_work_payload(**overrides), ADMIN))


def make_grant(amount_cents=100000, **overrides) -> dict:
    return get_success_data(
        api_client.create_funding_grant(
            create_funding_grant_payload(amount_cents=amount_cents, **overrides), FINANCE
        )
    )


def make_budget_line(grant_id, reservation_cents=1000, category="STORAGE") -> dict:
    return get_success_data(
        api_client.create_budget_line(
            create_budget_line_payload(
                grant_id, budget_reservation_cents=reservation_cents, category=category
            ),
            FINANCE,
        )
    )


def get_grant(grant_id) -> dict:
    return get_success_data(api_client.get_funding_grant(grant_id, FINANCE))


def get_patron(patron_id) -> dict:
    return get_success_data(api_client.get_patron(patron_id, ADMIN))


def get_item(item_id) -> dict:
    return get_success_data(api_client.get_item(item_id, ADMIN))


def get_work(work_id) -> dict:
    return get_success_data(api_client.get_work(work_id, ADMIN))


def get_entry(entry_id) -> dict:
    return get_success_data(api_client.get_waitlist_entry(entry_id, ADMIN))


def get_loan(loan_id) -> dict:
    return get_success_data(api_client.get_loan(loan_id, ADMIN))


def get_job(job_id) -> dict:
    return get_success_data(api_client.get_crawl_job(job_id, ADMIN))


def get_capture(capture_id) -> dict:
    return get_success_data(api_client.get_capture(capture_id, ADMIN))


# --- composite: library + work + batch + items ---

def make_batch_with_items(work_id, library_id, item_specs=None, seal=True):
    """Create a batch, deposit items (each a dict of item overrides), optionally seal.
    Returns (batch, [item, ...])."""
    batch = get_success_data(
        api_client.create_scan_batch(create_scan_batch_payload(), SCANOP)
    )
    specs = item_specs if item_specs is not None else [{}]
    items = []
    for spec in specs:
        payload = create_item_payload(batch["id"], work_id, library_id, **spec)
        items.append(get_success_data(api_client.create_item(payload, SCANOP)))
    if seal:
        get_success_data(api_client.seal_scan_batch(batch["id"], SCANOP))
        batch = get_success_data(api_client.get_scan_batch(batch["id"], ADMIN))
    return batch, items


def setup_work_with_lendable_items(num_items=1, work_overrides=None, library=None):
    """Library + work + sealed batch + num_items LENDABLE items.
    Returns (library, work, batch, items)."""
    library = library or make_library()
    work = make_work(**(work_overrides or {}))
    batch, items = make_batch_with_items(
        work["id"], library["id"], item_specs=[{} for _ in range(num_items)], seal=True
    )
    return library, work, batch, items


# --- lending operations ---

def checkout(item_id, patron_id, loan_kind="STANDARD") -> dict:
    payload = create_loan_payload(item_id, patron_id, loan_kind=loan_kind)
    return get_success_data(api_client.create_loan(payload, make_patron_headers(patron_id)))


def join_waitlist(work_id, patron_id) -> dict:
    payload = create_waitlist_entry_payload(work_id, patron_id)
    return get_success_data(
        api_client.create_waitlist_entry(payload, make_patron_headers(patron_id))
    )


def expire_and_sweep(clock_iso: str) -> dict:
    """Advance the logical clock and run the sweep. Returns sweep response data."""
    set_clock(clock_iso)
    return run_sweep()


def make_suspended_patron(item_id, email=None, base_clock="2026-09-01T00:00:00Z"):
    """Create a patron and drive it to strike_count == 3 / SUSPENDED via three
    expire+sweep cycles on the given item. Returns (patron, final_clock_iso)."""
    patron = make_patron(email=email)
    set_clock(base_clock)
    day = 1
    month = 9
    year = 2026
    for _ in range(3):
        checkout(item_id, patron["id"])
        day += 15
        if day > 28:
            day -= 28
            month += 1
        clock = f"{year:04d}-{month:02d}-{day:02d}T00:00:00Z"
        expire_and_sweep(clock)
    return patron, f"{year:04d}-{month:02d}-{day:02d}T00:00:00Z"


# --- accessibility ---

def make_verified_patron(email=None, officer_id="officer-1"):
    """Create a patron, submit a credential, VERIFY it. Returns (patron, credential)."""
    patron = make_patron(email=email)
    cred = get_success_data(
        api_client.create_accessibility_credential(
            create_accessibility_credential_payload(patron["id"]),
            make_patron_headers(patron["id"]),
        )
    )
    from .test_users import make_accessibility_officer_headers
    get_success_data(
        api_client.decide_accessibility_credential(
            cred["id"], {"decision": "VERIFY"}, make_accessibility_officer_headers(officer_id)
        )
    )
    return patron, cred


# --- crawl jobs ---

def make_running_crawl_job(seed_url="https://crawl.example/", scheduled_at="2026-09-01T00:05:00Z",
                           start_clock="2026-09-01T00:05:00Z", rpm=10, **overrides) -> dict:
    """Create a crawl job and start it. Caller must have already set the clock to a
    time strictly before scheduled_at."""
    payload = create_crawl_job_payload(
        seed_url=seed_url, scheduled_at=scheduled_at, requests_per_minute=rpm, **overrides
    )
    job = get_success_data(api_client.create_crawl_job(payload, CRAWLOP))
    if start_clock is not None:
        set_clock(start_clock)
    get_success_data(api_client.start_crawl_job(job["id"], CRAWLOP))
    return get_job(job["id"])


def record_capture(job_id, url, content_hash, has_dynamic_content=False):
    payload = create_capture_payload(
        job_id, url=url, content_hash=content_hash, has_dynamic_content=has_dynamic_content
    )
    return get_success_data(api_client.create_capture(payload, CRAWLOP))


# --- rights requests ---

def file_work_rights_request(work_id, claimant_name="Claimant", filer="legal-a") -> dict:
    payload = create_rights_request_payload(
        subject_kind="WORK", work_id=work_id, claimant_name=claimant_name
    )
    return get_success_data(
        api_client.create_rights_request(payload, make_legal_reviewer_headers(filer))
    )


def begin_review(request_id, reviewer="legal-b") -> dict:
    return get_success_data(
        api_client.begin_review_rights_request(
            request_id, make_legal_reviewer_headers(reviewer)
        )
    )


def escalate_hold(request_id, reviewer="legal-b") -> dict:
    return get_success_data(
        api_client.escalate_hold_rights_request(
            request_id, make_legal_reviewer_headers(reviewer)
        )
    )


def decide_request(request_id, decision, decider="legal-c") -> dict:
    return get_success_data(
        api_client.decide_rights_request(
            request_id, {"decision": decision}, make_legal_reviewer_headers(decider)
        )
    )
