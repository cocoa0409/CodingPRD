"""Search quota ledgers: exhaustion boundary, seat-state gating, and
period rollover keeping adjacent periods disjoint."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, TIER_LIMITS, PERIOD_DAYS,
    auditor_headers, contract_admin_headers, seat_admin_headers,
    recruiter_headers,
    create_and_activate_contract, create_recruiter, create_candidate,
    assign_first_seat, setup_assigned_seat, consume_searches, set_clock,
    list_quota_ledgers, propose_and_approve, apply_event, current_contract_version,
)


# ---------------------------------------------------------------------------
# Corner/errors/quota_exhausted_error_triggerable
# ---------------------------------------------------------------------------

def test_quota_exhausted_on_search_past_quota():
    """PRD section 3.4: "the seat's current `OPEN` `QuotaLedger` must have
    `searches_remaining` of at least 1 — a search against an exhausted quota
    is rejected with `ERR_QUOTA_EXHAUSTED`."
    PRD section 3.3: "When `searches_used` reaches `search_quota_total`, the
    system moves the ledger from `OPEN` to `EXHAUSTED`, after which further
    candidate searches on this seat are rejected."

    Design: Corner/errors/quota_exhausted_error_triggerable
    """
    ctx = setup_assigned_seat(product_tier="RECRUITER_LITE", contract_number="C-ERR-1")
    create_candidate()
    quota = TIER_LIMITS["RECRUITER_LITE"]["monthly_search_quota_per_seat"]
    consume_searches(ctx["seat"]["id"], ctx["recruiter"]["id"], quota)

    ledgers = list_quota_ledgers(ctx["seat"]["id"])
    assert ledgers[0]["searches_used"] == quota
    assert ledgers[0]["ledger_status"] == "EXHAUSTED"

    resp = api_client.candidate_search(
        ctx["seat"]["id"], {"filter_spec": {"current_title": "t"}},
        recruiter_headers(ctx["recruiter"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_QUOTA_EXHAUSTED)


def test_quota_exhausted_ledger_count_matches_usage():
    """PRD section 3.3: "`searches_remaining`, which is always
    `search_quota_total` minus `searches_used` and can never go negative."
    PRD section 3.4: "a search against an exhausted quota is rejected with
    `ERR_QUOTA_EXHAUSTED`."

    Design: Corner/errors/quota_exhausted_error_triggerable
    """
    ctx = setup_assigned_seat(product_tier="RECRUITER_LITE", contract_number="C-ERR-1B")
    create_candidate()
    quota = TIER_LIMITS["RECRUITER_LITE"]["monthly_search_quota_per_seat"]
    consume_searches(ctx["seat"]["id"], ctx["recruiter"]["id"], quota - 1)

    ledger = list_quota_ledgers(ctx["seat"]["id"])[0]
    assert ledger["searches_used"] == quota - 1
    assert ledger["searches_remaining"] == 1
    assert ledger["ledger_status"] == "OPEN"

    resp = api_client.candidate_search(
        ctx["seat"]["id"], {"filter_spec": {"current_title": "t"}},
        recruiter_headers(ctx["recruiter"]["id"]),
    )
    validate_success(resp)
    ledger = list_quota_ledgers(ctx["seat"]["id"])[0]
    assert ledger["searches_used"] == quota
    assert ledger["searches_remaining"] == 0
    assert ledger["ledger_status"] == "EXHAUSTED"


# ---------------------------------------------------------------------------
# Corner/state_machines/candidate_search_on_unassigned_seat_rejected
# ---------------------------------------------------------------------------

def test_candidate_search_on_unassigned_seat_rejected():
    """PRD section 3.4: "Before the search runs, three gates apply: the seat
    must be `ASSIGNED` (otherwise `ERR_INVALID_STATE`)"

    Design: Corner/state_machines/candidate_search_on_unassigned_seat_rejected
    """
    contract = create_and_activate_contract(seats=1, contract_number="C-SM-5")
    seat = get_success_data(
        api_client.list_seats(contract["id"], contract_admin_headers())
    )[0]
    resp = api_client.candidate_search(
        seat["id"], {"filter_spec": {"current_title": "t"}},
        seat_admin_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_candidate_search_consumes_quota_on_assigned_seat():
    """PRD section 3.4: "The search increments `searches_used` on the seat's
    current ledger by 1; if that brings `searches_used` to
    `search_quota_total`, the ledger transitions from `OPEN` to `EXHAUSTED`
    as a side effect."

    Design: Corner/state_machines/candidate_search_on_unassigned_seat_rejected
    """
    ctx = setup_assigned_seat(contract_number="C-SM-5B")
    create_candidate()
    resp = api_client.candidate_search(
        ctx["seat"]["id"], {"filter_spec": {"current_title": "t"}},
        recruiter_headers(ctx["recruiter"]["id"]),
    )
    validate_success(resp)
    ledger = list_quota_ledgers(ctx["seat"]["id"])[0]
    assert ledger["searches_used"] == 1
    assert ledger["searches_remaining"] == ledger["search_quota_total"] - 1
    assert ledger["ledger_status"] == "OPEN"


# ---------------------------------------------------------------------------
# Difficulty/resource_temporal_overlap/quota_ledger_periods_disjoint_no_overlap
# ---------------------------------------------------------------------------

def _setup_contract_with_five_searches(contract_number):
    ctx = setup_assigned_seat(contract_number=contract_number)
    create_candidate(current_title="t", years_experience=2)
    consume_searches(ctx["seat"]["id"], ctx["recruiter"]["id"], 5, title="t")
    return ctx


def test_quota_ledger_periods_disjoint_no_overlap():
    """PRD section 3.9: "Applying a `RENEWAL` event moves the contract from
    `RENEWAL_PENDING` back to `ACTIVE`, increments `period_index` by 1, sets
    `current_period_start` to the previous `current_period_end`, sets
    `current_period_end` to 30 days after that, closes every `OPEN`
    `QuotaLedger` for the contract's seats (each moves to `CLOSED`) and
    creates a fresh `QuotaLedger` for the new period per seat"

    Design: Difficulty/resource_temporal_overlap/quota_ledger_periods_disjoint_no_overlap
    """
    ctx = _setup_contract_with_five_searches("C-OVL-2")
    cid = ctx["contract"]["id"]
    seat_id = ctx["seat"]["id"]

    set_clock("2026-10-02T00:00:00Z")
    event = propose_and_approve(cid, "RENEWAL")
    apply_event(event["id"])

    resp = api_client.candidate_search(
        seat_id, {"filter_spec": {"current_title": "t"}},
        recruiter_headers(ctx["recruiter"]["id"]),
    )
    validate_success(resp)

    ledgers = list_quota_ledgers(seat_id)
    assert len(ledgers) == 2
    by_period = {l["period_index"]: l for l in ledgers}
    assert by_period[1]["ledger_status"] == "CLOSED"
    assert by_period[1]["searches_used"] == 5
    assert by_period[2]["ledger_status"] == "OPEN"
    assert by_period[2]["searches_used"] == 1


def test_quota_ledger_period1_usage_frozen_after_renewal():
    """PRD section 3.9: "Applying a `RENEWAL` event moves the contract from
    `RENEWAL_PENDING` back to `ACTIVE`, increments `period_index` by 1, sets
    `current_period_start` to the previous `current_period_end`, sets
    `current_period_end` to 30 days after that, closes every `OPEN`
    `QuotaLedger` for the contract's seats (each moves to `CLOSED`) and
    creates a fresh `QuotaLedger` for the new period per seat"
    PRD section 3.1: "`period_index` is a monotone counter beginning at 1 at
    activation and incrementing by 1 on each renewal apply."

    Design: Difficulty/resource_temporal_overlap/quota_ledger_periods_disjoint_no_overlap
    """
    ctx = _setup_contract_with_five_searches("C-OVL-2B")
    cid = ctx["contract"]["id"]

    set_clock("2026-10-02T00:00:00Z")
    event = propose_and_approve(cid, "RENEWAL")
    apply_event(event["id"])

    contract_after = get_success_data(
        api_client.get_contract(cid, contract_admin_headers())
    )
    assert contract_after["period_index"] == 2
    assert contract_after["contract_status"] == "ACTIVE"

    ledgers = list_quota_ledgers(ctx["seat"]["id"])
    by_period = {l["period_index"]: l for l in ledgers}
    assert by_period[1]["searches_used"] == 5
    assert by_period[2]["searches_used"] == 0
    assert by_period[2]["search_quota_total"] == (
        TIER_LIMITS[ctx["contract"]["product_tier"]]["monthly_search_quota_per_seat"]
    )
