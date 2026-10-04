"""Composite setup helpers.

Every fixture builds its preconditions from scratch via PRD-declared
endpoints (the harness restarts the server before every test, so each test
starts against an empty database). Setup calls use get_success_data() so
failures surface as clear setup errors rather than assertion noise.
"""
from typing import Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS, make_recruiter_user_headers
from .factories import (
    create_contract_payload,
    create_recruiter_payload,
    create_candidate_payload,
    create_project_payload,
    send_message_payload,
    create_job_posting_payload,
    create_promoted_slot_payload,
    create_ats_integration_payload,
    create_ats_sync_record_payload,
    create_talent_insight_payload,
)


def contract_admin_headers():
    return TEST_USERS["contract_admin_headers"]


def seat_admin_headers():
    return TEST_USERS["seat_admin_headers"]


def auditor_headers():
    return TEST_USERS["auditor_headers"]


def ats_service_headers():
    return TEST_USERS["ats_service_headers"]


def recruiter_headers(recruiter_id: str):
    return make_recruiter_user_headers(recruiter_id)


# ---------------------------------------------------------------------------
# Tier 1: contracts
# ---------------------------------------------------------------------------

def create_contract(contract_number=None, product_tier="RECRUITER_PRO",
                    seat_cap=5, true_up_allowed=None) -> dict:
    payload = create_contract_payload(product_tier=product_tier, seat_cap=seat_cap)
    if contract_number is not None:
        payload["contract_number"] = contract_number
    if true_up_allowed is not None:
        payload["true_up_allowed"] = true_up_allowed
    resp = api_client.create_contract(payload, contract_admin_headers())
    return get_success_data(resp)


def activate_contract(contract_id, seats_purchased_initial=1) -> dict:
    resp = api_client.activate_contract(
        contract_id, {"seats_purchased_initial": seats_purchased_initial},
        contract_admin_headers(),
    )
    return get_success_data(resp)


def create_and_activate_contract(seats=1, product_tier="RECRUITER_PRO", seat_cap=None,
                                 contract_number=None, true_up_allowed=None) -> dict:
    cap = seat_cap if seat_cap is not None else max(5, seats)
    contract = create_contract(
        contract_number=contract_number,
        product_tier=product_tier,
        seat_cap=cap,
        true_up_allowed=true_up_allowed,
    )
    return activate_contract(contract["id"], seats)


def get_contract(contract_id) -> dict:
    return get_success_data(api_client.get_contract(contract_id, contract_admin_headers()))


def current_contract_version(contract_id) -> int:
    return get_contract(contract_id)["version"]


def set_clock(to_iso8601: str) -> dict:
    return get_success_data(api_client.set_clock(to_iso8601, contract_admin_headers()))


# ---------------------------------------------------------------------------
# Tier 1: recruiters and seats
# ---------------------------------------------------------------------------

def create_recruiter(contract_id, email=None, full_name=None, manager_recruiter_id=None) -> dict:
    payload = create_recruiter_payload(contract_id)
    if email is not None:
        payload["email"] = email
    if full_name is not None:
        payload["full_name"] = full_name
    if manager_recruiter_id is not None:
        payload["manager_recruiter_id"] = manager_recruiter_id
    resp = api_client.create_recruiter(payload, contract_admin_headers())
    return get_success_data(resp)


def list_seats(contract_id, params=None) -> list:
    resp = api_client.list_seats(contract_id, contract_admin_headers(), params=params)
    return get_success_data(resp)


def get_seat(seat_id) -> dict:
    return get_success_data(api_client.get_seat(seat_id, auditor_headers()))


def assign_seat(contract_id, seat_id, recruiter_id) -> dict:
    seat = get_seat(seat_id)
    resp = api_client.assign_seat(
        contract_id, seat_id,
        {"recruiter_id": recruiter_id, "expected_seat_version": seat["version"]},
        seat_admin_headers(),
    )
    return get_success_data(resp)


def assign_first_seat(contract_id, recruiter_id) -> dict:
    """Assign the first (oldest-created) seat of the contract to the recruiter."""
    seats = list_seats(contract_id)
    assert seats, "setup failed: contract has no seats"
    return assign_seat(contract_id, seats[0]["id"], recruiter_id)


def setup_assigned_seat(seats=1, product_tier="RECRUITER_PRO", seat_cap=None,
                        contract_number=None) -> dict:
    """ACTIVE contract + one recruiter + seat[0] assigned to that recruiter.

    Returns {"contract", "recruiter", "seat"}.
    """
    contract = create_and_activate_contract(
        seats=seats, product_tier=product_tier, seat_cap=seat_cap,
        contract_number=contract_number,
    )
    recruiter = create_recruiter(contract["id"])
    seat = assign_first_seat(contract["id"], recruiter["id"])
    return {"contract": contract, "recruiter": recruiter, "seat": seat}


# ---------------------------------------------------------------------------
# Tier 2: projects and candidates
# ---------------------------------------------------------------------------

def create_open_project(contract_id, owner_seat_id, name=None) -> dict:
    payload = create_project_payload(owner_seat_id)
    if name is not None:
        payload["name"] = name
    resp = api_client.create_project(contract_id, payload, seat_admin_headers())
    project = get_success_data(resp)
    resp = api_client.open_project(project["id"], seat_admin_headers())
    return get_success_data(resp)


def create_candidate(**overrides) -> dict:
    resp = api_client.create_candidate_profile(
        create_candidate_payload(**overrides), contract_admin_headers(),
    )
    return get_success_data(resp)


def create_public_candidates(count, title, member_prefix=None) -> list:
    """Create `count` PUBLIC candidates with current_title=title (visible to all)."""
    out = []
    for i in range(count):
        overrides = {"current_title": title}
        if member_prefix is not None:
            overrides["member_id"] = f"{member_prefix}-{i:03d}"
        out.append(create_candidate(**overrides))
    return out


def setup_messaging(seats=1, product_tier="RECRUITER_PRO", seat_cap=None,
                    contract_number=None, **candidate_overrides) -> dict:
    """setup_assigned_seat + one OPEN project + one visible candidate.

    Returns {"contract", "recruiter", "seat", "project", "candidate"}.
    """
    ctx = setup_assigned_seat(
        seats=seats, product_tier=product_tier, seat_cap=seat_cap,
        contract_number=contract_number,
    )
    ctx["project"] = create_open_project(ctx["contract"]["id"], ctx["seat"]["id"])
    ctx["candidate"] = create_candidate(**candidate_overrides)
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: messages and responses
# ---------------------------------------------------------------------------

def send_message(seat_id, recruiter_id, candidate_id, project_id, body=None) -> dict:
    payload = send_message_payload(candidate_id, project_id)
    if body is not None:
        payload["body"] = body
    resp = api_client.send_message(seat_id, payload, recruiter_headers(recruiter_id))
    return get_success_data(resp)


def record_response(message_id, response_kind) -> dict:
    resp = api_client.record_response(
        message_id, {"response_kind": response_kind}, ats_service_headers(),
    )
    return get_success_data(resp)


def get_message(message_id) -> dict:
    return get_success_data(api_client.get_message(message_id, auditor_headers()))


def get_credit_pool(seat_id, period_index=None) -> dict:
    params = {"period_index": period_index} if period_index is not None else None
    resp = api_client.list_credit_pools(seat_id, auditor_headers(), params=params)
    pools = get_success_data(resp)
    assert pools, "setup failed: no credit pool for seat"
    return pools[0]


def list_credit_pools(seat_id) -> list:
    resp = api_client.list_credit_pools(seat_id, auditor_headers())
    return get_success_data(resp)


def get_quota_ledger(seat_id, period_index=None) -> dict:
    params = {"period_index": period_index} if period_index is not None else None
    resp = api_client.list_quota_ledgers(seat_id, auditor_headers(), params=params)
    ledgers = get_success_data(resp)
    assert ledgers, "setup failed: no quota ledger for seat"
    return ledgers[0]


def list_quota_ledgers(seat_id) -> list:
    resp = api_client.list_quota_ledgers(seat_id, auditor_headers())
    return get_success_data(resp)


def consume_searches(seat_id, recruiter_id, count, title="t") -> None:
    """Run `count` successful candidate searches on the seat."""
    for _ in range(count):
        resp = api_client.candidate_search(
            seat_id, {"filter_spec": {"current_title": title}},
            recruiter_headers(recruiter_id),
        )
        get_success_data(resp)


def drain_credits(ctx, count, body_prefix="m") -> list:
    """Send `count` credit-consuming messages; returns the message dicts."""
    messages = []
    for i in range(count):
        messages.append(send_message(
            ctx["seat"]["id"], ctx["recruiter"]["id"],
            ctx["candidate"]["id"], ctx["project"]["id"],
            body=f"{body_prefix}{i:02d}",
        ))
    return messages


# ---------------------------------------------------------------------------
# Tier 3: job postings
# ---------------------------------------------------------------------------

def create_posting(contract_id, seat_id, budget_cents=10000, daily_cap_cents=5000,
                   pacing_mode="EVEN", start_at="2026-09-01T00:00:00Z",
                   end_at="2026-09-11T00:00:00Z", title=None) -> dict:
    payload = create_job_posting_payload(
        seat_id, budget_cents=budget_cents, daily_cap_cents=daily_cap_cents,
        pacing_mode=pacing_mode, start_at=start_at, end_at=end_at,
    )
    if title is not None:
        payload["title"] = title
    resp = api_client.create_job_posting(contract_id, payload, seat_admin_headers())
    return get_success_data(resp)


def add_slot(contract_id, posting_id, slot_date="2026-09-01", reserved_cents=100) -> dict:
    resp = api_client.create_promoted_slot(
        contract_id, posting_id,
        create_promoted_slot_payload(slot_date=slot_date, reserved_cents=reserved_cents),
        seat_admin_headers(),
    )
    return get_success_data(resp)


def activate_posting(contract_id, posting_id) -> dict:
    resp = api_client.activate_job_posting(contract_id, posting_id, seat_admin_headers())
    return get_success_data(resp)


def get_posting(contract_id, posting_id) -> dict:
    resp = api_client.get_job_posting_in_contract(contract_id, posting_id, auditor_headers())
    return get_success_data(resp)


def setup_active_posting(budget_cents=10000, daily_cap_cents=5000, pacing_mode="EVEN",
                         start_at="2026-09-01T00:00:00Z", end_at="2026-09-11T00:00:00Z",
                         slot_date="2026-09-01", slot_reserved_cents=None,
                         product_tier="RECRUITER_PRO", contract_number=None) -> dict:
    """ACTIVE contract + assigned seat + ACTIVE posting with one RESERVED slot.

    Returns {"contract", "recruiter", "seat", "posting", "slot"}.
    """
    ctx = setup_assigned_seat(product_tier=product_tier, contract_number=contract_number)
    posting = create_posting(
        ctx["contract"]["id"], ctx["seat"]["id"],
        budget_cents=budget_cents, daily_cap_cents=daily_cap_cents,
        pacing_mode=pacing_mode, start_at=start_at, end_at=end_at,
    )
    slot = add_slot(
        ctx["contract"]["id"], posting["id"], slot_date=slot_date,
        reserved_cents=slot_reserved_cents or daily_cap_cents,
    )
    posting = activate_posting(ctx["contract"]["id"], posting["id"])
    ctx.update({"posting": posting, "slot": slot})
    return ctx


def record_spend(contract_id, posting_id, amount_cents):
    return api_client.record_spend(
        contract_id, posting_id, {"amount_cents": amount_cents}, seat_admin_headers(),
    )


# ---------------------------------------------------------------------------
# Tier 3: ATS integrations and sync records
# ---------------------------------------------------------------------------

def create_integration(contract_id, vendor="GREENHOUSE", external_tenant_id=None,
                       write_back_enabled=None) -> dict:
    payload = create_ats_integration_payload(vendor=vendor)
    if external_tenant_id is not None:
        payload["external_tenant_id"] = external_tenant_id
    if write_back_enabled is not None:
        payload["write_back_enabled"] = write_back_enabled
    resp = api_client.create_ats_integration(contract_id, payload, contract_admin_headers())
    return get_success_data(resp)


def connect_integration(contract_id, integration_id) -> dict:
    resp = api_client.connect_ats_integration(contract_id, integration_id, contract_admin_headers())
    return get_success_data(resp)


def create_sync_record(integration_id, candidate_id, event_type="APPLICATION_FORWARDED",
                       external_candidate_ref=None, payload=None) -> dict:
    body = create_ats_sync_record_payload(integration_id, candidate_id, event_type=event_type)
    if external_candidate_ref is not None:
        body["external_candidate_ref"] = external_candidate_ref
    if payload is not None:
        body["payload"] = payload
    resp = api_client.create_ats_sync_record(body, ats_service_headers())
    return get_success_data(resp)


def setup_connected_integration(product_tier="RECRUITER_PRO", contract_number=None,
                                write_back_enabled=True) -> dict:
    """ACTIVE contract + CONNECTED ATS integration + one candidate.

    Returns {"contract", "integration", "candidate"}.
    """
    contract = create_and_activate_contract(product_tier=product_tier,
                                            contract_number=contract_number)
    integration = create_integration(contract["id"], write_back_enabled=write_back_enabled)
    integration = connect_integration(contract["id"], integration["id"])
    candidate = create_candidate()
    return {"contract": contract, "integration": integration, "candidate": candidate}


# ---------------------------------------------------------------------------
# Tier 3: talent insights
# ---------------------------------------------------------------------------

def create_report(contract_id, report_name=None, filter_spec=None) -> dict:
    payload = create_talent_insight_payload()
    if report_name is not None:
        payload["report_name"] = report_name
    if filter_spec is not None:
        payload["filter_spec"] = filter_spec
    resp = api_client.create_talent_insight(contract_id, payload, contract_admin_headers())
    return get_success_data(resp)


def generate_report(contract_id, report_id) -> dict:
    resp = api_client.generate_talent_insight(contract_id, report_id, contract_admin_headers())
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 3/4: renewal events (OCC-guarded; propose / approve / apply)
# ---------------------------------------------------------------------------

def propose_event(contract_id, event_kind, seats_delta=None) -> dict:
    version = current_contract_version(contract_id)
    payload = {"event_kind": event_kind, "expected_contract_version": version}
    if seats_delta is not None:
        payload["seats_delta"] = seats_delta
    resp = api_client.create_renewal_event(contract_id, payload, auditor_headers())
    return get_success_data(resp)


def approve_event(event_id) -> dict:
    resp = api_client.approve_renewal_event(event_id, auditor_headers())
    return get_success_data(resp)


def apply_event(event_id) -> dict:
    resp = api_client.apply_renewal_event(event_id, auditor_headers())
    return get_success_data(resp)


def propose_and_approve(contract_id, event_kind, seats_delta=None) -> dict:
    event = propose_event(contract_id, event_kind, seats_delta=seats_delta)
    return approve_event(event["id"])


def suspend_contract_via_event(contract_id) -> dict:
    """Full machinery: propose SUSPENSION, approve, then suspend the contract."""
    event = propose_and_approve(contract_id, "SUSPENSION")
    resp = api_client.suspend_contract(contract_id, auditor_headers())
    get_success_data(resp)
    return event


def apply_true_up(contract_id, seats_delta) -> dict:
    """Propose + approve + apply a TRUE_UP event. Returns the applied event."""
    event = propose_and_approve(contract_id, "TRUE_UP", seats_delta=seats_delta)
    return apply_event(event["id"])
