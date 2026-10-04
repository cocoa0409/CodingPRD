"""Composite setup helpers: turnaround negotiation ladder and settlement runs.
Re-exported through fixtures.py.

Turnaround OCC threading (PRD section 2.7): every respond carries
expected_turnaround_version matching the turnaround's current version, so the
helpers read the version off each fresh response rather than assuming it.
CustomerOps identity threading (PRD section 2.1): respond calls always use
make_customer_ops_headers(customer_id) with the customer that owns the plant's
contract.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    DEFAULTS,
    create_respond_payload,
    create_settlement_payload,
    create_turnaround_payload,
)
from .fixtures_contracts import set_logical_clock
from .test_users import TEST_USERS, make_customer_ops_headers


# ---------------------------------------------------------------------------
# Turnaround ladder: PROPOSED -> (AGREE|COUNTER) -> AGREED -> SCHEDULED ->
# IN_PROGRESS (completion is clock-driven, PRD section 3.7)
# ---------------------------------------------------------------------------

def create_turnaround(plant_id: str, window_start: str = DEFAULTS["TURNAROUND_WINDOW_START"],
                      window_end: str = DEFAULTS["TURNAROUND_WINDOW_END"],
                      scope: str = DEFAULTS["TURNAROUND_SCOPE"]) -> dict:
    """Propose a turnaround on an OPERATING plant. Born PROPOSED with
    proposal_round 1."""
    return get_success_data(
        api_client.create_turnaround(
            plant_id,
            create_turnaround_payload(
                window_start=window_start, window_end=window_end, scope=scope
            ),
            TEST_USERS["plant_operator_headers"],
        )
    )


def agree_turnaround(turnaround_id: str, turnaround_version: int, customer_id: str) -> dict:
    """CustomerOps AGREEs the proposed window (OCC-guarded)."""
    return get_success_data(
        api_client.respond_to_turnaround(
            turnaround_id,
            create_respond_payload("AGREE", turnaround_version),
            make_customer_ops_headers(customer_id),
        )
    )


def counter_turnaround(turnaround_id: str, turnaround_version: int, customer_id: str,
                       counter_window_start: str, counter_window_end: str) -> dict:
    """CustomerOps COUNTERs: window replaced, proposal_round +1, version +1,
    status stays PROPOSED."""
    return get_success_data(
        api_client.respond_to_turnaround(
            turnaround_id,
            create_respond_payload(
                "COUNTER", turnaround_version,
                counter_window_start=counter_window_start,
                counter_window_end=counter_window_end,
            ),
            make_customer_ops_headers(customer_id),
        )
    )


def create_agreed_turnaround(plant_id: str, customer_id: str,
                             window_start: str = DEFAULTS["TURNAROUND_WINDOW_START"],
                             window_end: str = DEFAULTS["TURNAROUND_WINDOW_END"],
                             scope: str = DEFAULTS["TURNAROUND_SCOPE"]) -> dict:
    """Propose + AGREE. Returns the AGREED turnaround."""
    turnaround = create_turnaround(plant_id, window_start, window_end, scope)
    return agree_turnaround(turnaround["id"], turnaround["version"], customer_id)


def schedule_turnaround(turnaround_id: str) -> dict:
    """Schedule an AGREED turnaround as PlantOperator."""
    return get_success_data(
        api_client.schedule_turnaround(
            turnaround_id, TEST_USERS["plant_operator_headers"]
        )
    )


def create_scheduled_turnaround(plant_id: str, customer_id: str,
                                window_start: str = DEFAULTS["TURNAROUND_WINDOW_START"],
                                window_end: str = DEFAULTS["TURNAROUND_WINDOW_END"],
                                scope: str = DEFAULTS["TURNAROUND_SCOPE"]) -> dict:
    """Propose + AGREE + schedule. Returns the SCHEDULED turnaround."""
    turnaround = create_agreed_turnaround(plant_id, customer_id, window_start, window_end, scope)
    return schedule_turnaround(turnaround["id"])


def start_turnaround(turnaround_id: str) -> dict:
    """Start a SCHEDULED turnaround (fires the failover cascade)."""
    return get_success_data(
        api_client.start_turnaround(
            turnaround_id, TEST_USERS["plant_operator_headers"]
        )
    )


def create_in_progress_turnaround(plant_id: str, customer_id: str,
                                  window_start: str = DEFAULTS["TURNAROUND_WINDOW_START"],
                                  window_end: str = DEFAULTS["TURNAROUND_WINDOW_END"],
                                  scope: str = DEFAULTS["TURNAROUND_SCOPE"]) -> dict:
    """Full ladder to IN_PROGRESS: propose, agree, schedule, advance the
    logical clock to exactly window_start (due-gate requires current_utc >=
    window_start), then start. Returns the IN_PROGRESS turnaround."""
    turnaround = create_scheduled_turnaround(plant_id, customer_id, window_start, window_end, scope)
    set_logical_clock(window_start)
    return start_turnaround(turnaround["id"])


# ---------------------------------------------------------------------------
# Settlement runs (setup-side; always expect success here — tests that probe
# settlement failures call the API client directly)
# ---------------------------------------------------------------------------

def run_settlement(contract_id: str, **payload_overrides) -> dict:
    """Run one settlement statement as BillingSpecialist and return it.
    Pass period_month / variant / metered_volume_nm3 / projected_volume_nm3 /
    power_index_actual / apply_makeup_cents as overrides."""
    payload = create_settlement_payload(**payload_overrides)
    return get_success_data(
        api_client.create_settlement(
            contract_id, payload, TEST_USERS["billing_specialist_headers"]
        )
    )


def run_final_settlement(contract_id: str, period_month: str,
                         metered_volume_nm3: int, power_index_actual: float,
                         apply_makeup_cents: int = None) -> dict:
    """Convenience wrapper for a FINAL period close."""
    overrides = {
        "period_month": period_month,
        "variant": "FINAL",
        "metered_volume_nm3": metered_volume_nm3,
        "power_index_actual": power_index_actual,
    }
    if apply_makeup_cents is not None:
        overrides["apply_makeup_cents"] = apply_makeup_cents
    return run_settlement(contract_id, **overrides)


def list_settlements(contract_id: str) -> list:
    """All settlement statements for a contract (data list)."""
    return get_success_data(
        api_client.list_settlements(
            contract_id, TEST_USERS["billing_specialist_headers"]
        )
    )


__all__ = [
    "create_turnaround",
    "agree_turnaround",
    "counter_turnaround",
    "create_agreed_turnaround",
    "schedule_turnaround",
    "create_scheduled_turnaround",
    "start_turnaround",
    "create_in_progress_turnaround",
    "run_settlement",
    "run_final_settlement",
    "list_settlements",
]
