"""Payload factories - one per client-supplied body, input fields only.

Money is always a whole number of cents and share counts are always whole
integers, so every numeric field below is emitted as a JSON number, never as a
string. Where the PRD declares an ISO 8601 UTC instant, the factory emits a full
instant; where it declares a calendar date, the factory emits ``YYYY-MM-DD``.
"""

import itertools

_employee_seq = itertools.count(1)
_metric_seq = itertools.count(1)
_quarter_seq = itertools.count(1)


def unique_employee_number(prefix: str = "E") -> str:
    return f"{prefix}-{next(_employee_seq):05d}"


def unique_metric_code(prefix: str = "METRIC") -> str:
    return f"{prefix}_{next(_metric_seq):05d}"


def unique_quarter_label(prefix: str = "Q") -> str:
    return f"{prefix}{next(_quarter_seq):05d}-FY2026"


# ------------------------------------------------------------------ plan
def create_equity_plan_payload(**overrides) -> dict:
    payload = {
        "name": "2026 Omnibus Incentive Plan",
        "total_authorized_shares": 1_000_000,
        "common_shares_outstanding": 1_000_000,
        "fiscal_year_start_date": "2026-01-01",
    }
    payload.update(overrides)
    return payload


def plan_status_payload(action: str, **overrides) -> dict:
    payload = {"action": action}
    payload.update(overrides)
    return payload


def share_reserve_adjustment_payload(delta_shares: int, expected_plan_version: int,
                                    **overrides) -> dict:
    payload = {
        "delta_shares": delta_shares,
        "expected_plan_version": expected_plan_version,
    }
    payload.update(overrides)
    return payload


def annual_rollover_payload(fiscal_year_label: str = "FY2027", **overrides) -> dict:
    payload = {"fiscal_year_label": fiscal_year_label}
    payload.update(overrides)
    return payload


# ------------------------------------------------------------- delegation
def create_approval_authority_payload(plan_id: str, delegate_user_id: str = "officer-1",
                                     **overrides) -> dict:
    payload = {
        "plan_id": plan_id,
        "authority_type": "DELEGATED_OFFICER",
        "delegate_user_id": delegate_user_id,
        "per_grant_share_cap": 10_000,
        "aggregate_share_cap": 50_000,
        "effective_from": "2026-01-01",
        "effective_to": "2026-12-31",
    }
    payload.update(overrides)
    return payload


# ------------------------------------------------------------ participant
def create_participant_payload(**overrides) -> dict:
    payload = {
        "full_name": "Test Recipient",
        "employee_number": unique_employee_number(),
        "home_country_code": "US",
        "home_state_code": "CA",
        "hire_date": "2020-01-06",
        "birth_date": "1985-01-01",
    }
    payload.update(overrides)
    return payload


def insider_status_payload(insider_status: str) -> dict:
    return {"insider_status": insider_status}


def terminate_participant_payload(termination_date: str, termination_reason: str,
                                 **overrides) -> dict:
    payload = {
        "termination_date": termination_date,
        "termination_reason": termination_reason,
    }
    payload.update(overrides)
    return payload


# ----------------------------------------------------- mobility assignment
def create_mobility_assignment_payload(participant_id: str, **overrides) -> dict:
    payload = {
        "participant_id": participant_id,
        "jurisdiction_code": "US-CA",
        "tax_rate_bps": 4000,
        "start_date": "2026-01-01",
        "end_date": "2026-06-30",
        "workdays": 100,
    }
    payload.update(overrides)
    return payload


# ------------------------------------------------------------------ grant
def create_grant_payload(plan_id: str, participant_id: str, **overrides) -> dict:
    payload = {
        "plan_id": plan_id,
        "participant_id": participant_id,
        "award_type": "RSU",
        "target_shares": 1000,
    }
    payload.update(overrides)
    return payload


def create_vesting_tranche_payload(tranche_index: int = 1, **overrides) -> dict:
    payload = {
        "tranche_index": tranche_index,
        "vest_type": "TIME",
        "scheduled_vest_date": "2027-01-05",
        "target_shares": 1000,
    }
    payload.update(overrides)
    return payload


def request_changes_payload(change_note: str = "Resize the second tranche.") -> dict:
    return {"change_note": change_note}


def revise_grant_payload(target_shares: int, **overrides) -> dict:
    payload = {"target_shares": target_shares}
    payload.update(overrides)
    return payload


def approve_grant_payload(approval_path: str = "BOARD", **overrides) -> dict:
    payload = {"approval_path": approval_path}
    payload.update(overrides)
    return payload


def cancel_grant_payload(cancel_reason: str = "Superseded by a new award.") -> dict:
    return {"cancel_reason": cancel_reason}


# ------------------------------------------------------- performance cycle
def create_performance_cycle_payload(plan_id: str, **overrides) -> dict:
    payload = {
        "plan_id": plan_id,
        "metric_code": unique_metric_code(),
        "target_value": 100,
        "certification_due_date": "2027-02-15",
    }
    payload.update(overrides)
    return payload


def certify_payload(actual_value, **overrides) -> dict:
    payload = {"actual_value": actual_value}
    payload.update(overrides)
    return payload


# ---------------------------------------------------- vesting / settlement
def vest_tranche_payload(fmv_per_share_cents: int = 5000, **overrides) -> dict:
    payload = {"fmv_per_share_cents": fmv_per_share_cents}
    payload.update(overrides)
    return payload


def reverse_payload(reversal_reason: str = "Administrative correction.") -> dict:
    return {"reversal_reason": reversal_reason}


# ---------------------------------------------------------- trading window
def create_trading_window_payload(plan_id: str, **overrides) -> dict:
    payload = {
        "plan_id": plan_id,
        "quarter_label": unique_quarter_label(),
        "open_at": "2026-01-05T00:00:00Z",
        "close_at": "2026-03-31T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def window_status_payload(action: str, **overrides) -> dict:
    payload = {"action": action}
    payload.update(overrides)
    return payload


# ----------------------------------------------------- preclearance request
def create_preclearance_request_payload(participant_id: str, window_id: str,
                                       **overrides) -> dict:
    payload = {
        "participant_id": participant_id,
        "window_id": window_id,
        "transaction_type": "SELL",
        "requested_shares": 500,
        "intended_trade_date": "2026-01-09",
    }
    payload.update(overrides)
    return payload


def decide_payload(decision: str, **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def resubmit_payload(requested_shares: int, intended_trade_date: str) -> dict:
    return {
        "requested_shares": requested_shares,
        "intended_trade_date": intended_trade_date,
    }


def execute_payload(executed_shares: int, price_per_share_cents: int) -> dict:
    return {
        "executed_shares": executed_shares,
        "price_per_share_cents": price_per_share_cents,
    }


# ------------------------------------------------------------ trading plan
def create_trading_plan_payload(participant_id: str, expected_participant_version: int,
                               **overrides) -> dict:
    payload = {
        "participant_id": participant_id,
        "plan_document_ref": "10b5-1/2026/001",
        "first_scheduled_trade_date": "2026-06-01",
        "total_shares": 1200,
        "expected_participant_version": expected_participant_version,
    }
    payload.update(overrides)
    return payload


def modify_trading_plan_payload(first_scheduled_trade_date: str, total_shares: int) -> dict:
    return {
        "first_scheduled_trade_date": first_scheduled_trade_date,
        "total_shares": total_shares,
    }


def terminate_trading_plan_payload(termination_reason: str = "PARTICIPANT_REQUEST") -> dict:
    return {"termination_reason": termination_reason}
