"""Payload factories — one per entity, input fields only."""

_counter = {"n": 0}


def _seq() -> int:
    _counter["n"] += 1
    return _counter["n"]


def create_contract_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "contract_number": f"C-{n:05d}",
        "product_tier": "RECRUITER_PRO",
        "seat_cap": 5,
    }
    defaults.update(overrides)
    return defaults


def activate_contract_payload(**overrides) -> dict:
    defaults = {"seats_purchased_initial": 1}
    defaults.update(overrides)
    return defaults


def create_recruiter_payload(home_contract_id, **overrides) -> dict:
    n = _seq()
    defaults = {
        "email": f"recruiter-{n}@example.com",
        "full_name": f"Recruiter {n}",
        "home_contract_id": home_contract_id,
    }
    defaults.update(overrides)
    return defaults


def create_candidate_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "member_id": f"member-{n:05d}",
        "full_name": f"Candidate {n}",
        "headline": "Seasoned professional",
        "privacy_setting": "PUBLIC",
        "open_to_work": False,
        "open_to_work_visibility": "NONE",
        "years_experience": 3,
        "current_title": "Engineer",
    }
    defaults.update(overrides)
    return defaults


def create_project_payload(owner_seat_id, **overrides) -> dict:
    n = _seq()
    defaults = {
        "name": f"Project-{n:05d}",
        "owner_seat_id": owner_seat_id,
    }
    defaults.update(overrides)
    return defaults


def send_message_payload(candidate_id, project_id, **overrides) -> dict:
    n = _seq()
    defaults = {
        "candidate_id": candidate_id,
        "project_id": project_id,
        "body": f"Hello candidate, message {n}",
    }
    defaults.update(overrides)
    return defaults


def record_response_payload(**overrides) -> dict:
    defaults = {"response_kind": "RESPONDED"}
    defaults.update(overrides)
    return defaults


def create_job_posting_payload(created_by_seat_id, **overrides) -> dict:
    n = _seq()
    defaults = {
        "title": f"Job {n:05d}",
        "budget_cents": 10000,
        "daily_cap_cents": 5000,
        "pacing_mode": "EVEN",
        "start_at": "2026-09-01T00:00:00Z",
        "end_at": "2026-09-11T00:00:00Z",
        "created_by_seat_id": created_by_seat_id,
    }
    defaults.update(overrides)
    return defaults


def create_promoted_slot_payload(**overrides) -> dict:
    defaults = {
        "slot_date": "2026-09-01",
        "reserved_cents": 100,
    }
    defaults.update(overrides)
    return defaults


def record_spend_payload(**overrides) -> dict:
    defaults = {"amount_cents": 100}
    defaults.update(overrides)
    return defaults


def create_ats_integration_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "vendor": "GREENHOUSE",
        "external_tenant_id": f"tenant-{n:05d}",
    }
    defaults.update(overrides)
    return defaults


def create_ats_sync_record_payload(ats_integration_id, candidate_id, **overrides) -> dict:
    n = _seq()
    defaults = {
        "ats_integration_id": ats_integration_id,
        "candidate_id": candidate_id,
        "external_candidate_ref": f"ext-cand-{n:05d}",
        "event_type": "APPLICATION_FORWARDED",
        "payload": {"stage": "applied"},
    }
    defaults.update(overrides)
    return defaults


def create_talent_insight_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "report_name": f"Report-{n:05d}",
        "filter_spec": {"current_title": "Engineer"},
    }
    defaults.update(overrides)
    return defaults


def create_renewal_event_payload(event_kind, expected_contract_version, **overrides) -> dict:
    defaults = {
        "event_kind": event_kind,
        "expected_contract_version": expected_contract_version,
    }
    defaults.update(overrides)
    return defaults


def assign_seat_payload(recruiter_id, expected_seat_version, **overrides) -> dict:
    defaults = {
        "recruiter_id": recruiter_id,
        "expected_seat_version": expected_seat_version,
    }
    defaults.update(overrides)
    return defaults
