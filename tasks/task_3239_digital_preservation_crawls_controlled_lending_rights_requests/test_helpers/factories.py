"""Payload factories — one per entity, input fields only."""
import itertools

_counter = itertools.count(1)


def _n() -> int:
    return next(_counter)


def create_patron_payload(**overrides) -> dict:
    n = _n()
    defaults = {"email": f"patron{n}@example.org", "full_name": f"Patron {n}"}
    defaults.update(overrides)
    return defaults


def create_accessibility_credential_payload(patron_id, **overrides) -> dict:
    defaults = {"patron_id": patron_id, "certifier_reference": f"NLS-{_n()}"}
    defaults.update(overrides)
    return defaults


def create_partner_library_payload(**overrides) -> dict:
    n = _n()
    defaults = {
        "library_code": f"LIB-{n:04d}",
        "display_name": f"Library {n}",
        "storage_commitment_years": 5,
    }
    defaults.update(overrides)
    return defaults


def create_work_payload(**overrides) -> dict:
    n = _n()
    defaults = {
        "title": f"Work {n}",
        "author": f"Author {n}",
        "publication_year": 2000,
    }
    defaults.update(overrides)
    return defaults


def create_scan_batch_payload(**overrides) -> dict:
    defaults = {"operator_code": f"op-{_n()}"}
    defaults.update(overrides)
    return defaults


def create_item_payload(batch_id, work_id, owning_library_id, **overrides) -> dict:
    defaults = {
        "batch_id": batch_id,
        "work_id": work_id,
        "owning_library_id": owning_library_id,
        "page_count": 10,
        "condition_grade": "GOOD",
    }
    defaults.update(overrides)
    return defaults


def create_loan_payload(item_id, patron_id, **overrides) -> dict:
    defaults = {"item_id": item_id, "patron_id": patron_id, "loan_kind": "STANDARD"}
    defaults.update(overrides)
    return defaults


def create_waitlist_entry_payload(work_id, patron_id, **overrides) -> dict:
    defaults = {"work_id": work_id, "patron_id": patron_id}
    defaults.update(overrides)
    return defaults


def create_crawl_job_payload(**overrides) -> dict:
    n = _n()
    defaults = {
        "seed_url": f"https://site{n}.example/",
        "scheduled_at": "2026-09-02T00:00:00Z",
        "requests_per_minute": 10,
    }
    defaults.update(overrides)
    return defaults


def create_capture_payload(crawl_job_id, **overrides) -> dict:
    n = _n()
    defaults = {
        "crawl_job_id": crawl_job_id,
        "url": f"https://cap.example/p{n}",
        "content_hash": f"hash{n}",
        "has_dynamic_content": False,
    }
    defaults.update(overrides)
    return defaults


def create_exclusion_directive_payload(**overrides) -> dict:
    defaults = {
        "url_prefix": f"https://excl-{_n()}.example/",
        "scope": "CRAWL_ONLY",
        "reason": "audit",
    }
    defaults.update(overrides)
    return defaults


def create_rights_request_payload(**overrides) -> dict:
    defaults = {"claimant_name": f"Claimant {_n()}"}
    defaults.update(overrides)
    return defaults


def create_funding_grant_payload(**overrides) -> dict:
    defaults = {"donor_name": f"Donor {_n()}", "amount_cents": 100000}
    defaults.update(overrides)
    return defaults


def create_budget_line_payload(grant_id, **overrides) -> dict:
    defaults = {
        "grant_id": grant_id,
        "category": "STORAGE",
        "budget_reservation_cents": 1000,
    }
    defaults.update(overrides)
    return defaults
