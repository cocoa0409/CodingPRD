"""Payload factories — one per writable entity, input fields only."""
import itertools

from .constants import DEFAULT_MEETING_DAY_OF_WEEK

_counter = itertools.count(1)


def _seq() -> int:
    return next(_counter)


def create_branch_payload(**overrides) -> dict:
    defaults = {"name": f"Test Branch {_seq()}"}
    defaults.update(overrides)
    return defaults


def create_center_manager_payload(branch_id, **overrides) -> dict:
    defaults = {
        "branch_id": branch_id,
        "full_name": f"Manager {_seq()}",
        "hired_on": "2026-08-01",
    }
    defaults.update(overrides)
    return defaults


def create_center_payload(branch_id, center_manager_id, **overrides) -> dict:
    defaults = {
        "branch_id": branch_id,
        "center_manager_id": center_manager_id,
        "name": f"Center {_seq()}",
        "meeting_day_of_week": DEFAULT_MEETING_DAY_OF_WEEK,
    }
    defaults.update(overrides)
    return defaults


def create_peer_group_payload(center_id, **overrides) -> dict:
    defaults = {"center_id": center_id, "name": f"Group {_seq()}"}
    defaults.update(overrides)
    return defaults


def create_member_payload(branch_id, **overrides) -> dict:
    n = _seq()
    defaults = {
        "branch_id": branch_id,
        "full_name": f"Member {n}",
        "national_id": f"NID-{n:06d}",
    }
    defaults.update(overrides)
    return defaults


def create_training_session_payload(
    peer_group_id,
    center_manager_id,
    start_time="2026-09-02T09:00:00Z",
    end_time="2026-09-02T10:00:00Z",
    **overrides,
) -> dict:
    defaults = {
        "peer_group_id": peer_group_id,
        "center_manager_id": center_manager_id,
        "start_time": start_time,
        "end_time": end_time,
    }
    defaults.update(overrides)
    return defaults


def create_loan_application_payload(member_id, requested_amount_cents=100_000, **overrides) -> dict:
    defaults = {"member_id": member_id, "requested_amount_cents": requested_amount_cents}
    defaults.update(overrides)
    return defaults


def create_vote_payload(decision="APPROVE", **overrides) -> dict:
    defaults = {"decision": decision}
    defaults.update(overrides)
    return defaults


def create_center_meeting_payload(
    center_id,
    scheduled_start="2026-09-08T10:00:00Z",
    scheduled_end="2026-09-08T11:00:00Z",
    **overrides,
) -> dict:
    defaults = {
        "center_id": center_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
    }
    defaults.update(overrides)
    return defaults


def create_attendance_payload(member_id, present=True, **overrides) -> dict:
    defaults = {"member_id": member_id, "present": present}
    defaults.update(overrides)
    return defaults


def create_collection_payload(member_id, loan_id, amount_cents, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "loan_id": loan_id,
        "amount_cents": amount_cents,
    }
    defaults.update(overrides)
    return defaults


def create_restructure_payload(new_term_weeks, expected_loan_version, **overrides) -> dict:
    defaults = {
        "new_term_weeks": new_term_weeks,
        "expected_loan_version": expected_loan_version,
    }
    defaults.update(overrides)
    return defaults


def create_expansion_plan_payload(
    new_centers=1, new_managers_hired=0, target_new_members=0, **overrides
) -> dict:
    defaults = {
        "new_centers": new_centers,
        "new_managers_hired": new_managers_hired,
        "target_new_members": target_new_members,
    }
    defaults.update(overrides)
    return defaults


def create_withdrawal_payload(amount_cents, **overrides) -> dict:
    defaults = {"amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


def create_reconcile_payload(declared_cash_cents, **overrides) -> dict:
    defaults = {"declared_cash_cents": declared_cash_cents}
    defaults.update(overrides)
    return defaults
