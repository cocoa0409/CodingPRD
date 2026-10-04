"""Attrition sweeps and the monitoring-account suspension they cascade."""
import pytest

from test_helpers import (
    api_client,
    find_monitoring_account,
    setup_delinquent_contract,
    validate_success,
)


# ─── Difficulty: transitive_cascade / attrition_sweep_flag_suspends_monitoring_account ───

def test_sweep_flags_the_contract_and_moves_it_to_delinquent(api):
    """PRD §3.6: "Each contract that survives both filters has its `id` appended to the sweep's `flagged_contract_ids` array in that same ascending order, the sweep's `delinquent_count` advances, the contract's `contract_status` moves to `DELINQUENT` and its `monitoring_hold_until` is set to the sweep instant."

    Design: Difficulty/transitive_cascade/attrition_sweep_flag_suspends_monitoring_account
    """
    customer, contract, sweep = setup_delinquent_contract(sweep_month="2026-09")

    assert contract["id"] in sweep["flagged_contract_ids"]
    assert sweep["delinquent_count"] == 1
    assert contract["contract_status"] == "DELINQUENT"


def test_sweep_flag_append_suspends_the_contract_monitoring_account(api):
    """PRD §3.6: "The append itself is not inert: each id appended is the trigger for a `SUSPEND` cascade on that contract's monitoring account, which moves the account from `PROVISIONED` to `SUSPENDED`."

    Design: Difficulty/transitive_cascade/attrition_sweep_flag_suspends_monitoring_account
    """
    customer, contract, sweep = setup_delinquent_contract(sweep_month="2026-09")

    account = find_monitoring_account(contract["id"])
    assert account["provision_state"] == "SUSPENDED"