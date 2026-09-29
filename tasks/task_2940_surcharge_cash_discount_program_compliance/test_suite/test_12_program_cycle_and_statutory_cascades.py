"""The program status cycle, the statutory prohibition cascade, and the fact that
only explicit restores put terminals back into enforcement."""
import pytest

from test_helpers import (
    api_client,
    apply_law_change,
    get_success_data,
    program_status_action,
    read_merchant,
    read_program,
    read_terminal,
    setup_enforcing_surcharge_estate,
    terminal_action,
    list_page,
    list_total,
)
from test_helpers.constants import TS_AUG_31
from test_helpers.fixtures import ADMIN, OFFICER_ONE


def test_program_re_enters_active_twice_through_suspension_and_prohibition(api):
    """PRD §3.7: "A program's `status` moves through `DRAFT`, `PENDING_REGISTRATION`, `ACTIVE`, `SUSPENDED`, `REMEDIATION`, `DISABLED`, and the terminal `WITHDRAWN`, and its `disable_reason` always explains why it is not `ACTIVE`: `NONE` while nothing is wrong, `JURISDICTION_PROHIBITION` after a law change, `REGISTRATION_REVOKED` after a network revocation, `REMEDIATION_ORDER` after a substantiated complaint, and `OPERATOR_SUSPENSION` after a deliberate suspension."
    PRD §3.7: "Every transition back into `ACTIVE` resets `disable_reason` to `NONE`."
    PRD §3.1: "Every program of that jurisdiction whose `status` is `DISABLED` and whose `disable_reason` is exactly `JURISDICTION_PROHIBITION` moves to `SUSPENDED` with `disable_reason` reset to `OPERATOR_SUSPENSION`, and its `effective_cap_pct` is recomputed against the jurisdiction's new `surcharge_cap_pct`."

    Design: Difficulty/non_linear_state_machine/program_cycle_active_suspend_resume_disable_reactivate
    """
    ctx = setup_enforcing_surcharge_estate(terminal_count=0)
    program_id = ctx["program"]["id"]
    jurisdiction_id = ctx["jurisdiction"]["id"]
    assert ctx["program"]["status"] == "ACTIVE"

    suspended = program_status_action(program_id, "SUSPEND", reason="internal compliance review")
    assert suspended["status"] == "SUSPENDED"
    assert suspended["disable_reason"] == "OPERATOR_SUSPENSION"

    resumed = program_status_action(program_id, "RESUME", reason="review closed")
    assert resumed["status"] == "ACTIVE"
    assert resumed["disable_reason"] == "NONE"

    apply_law_change(jurisdiction_id, False, surcharge_cap_pct=None)
    disabled = read_program(program_id)
    assert disabled["status"] == "DISABLED"
    assert disabled["disable_reason"] == "JURISDICTION_PROHIBITION"

    apply_law_change(jurisdiction_id, True, surcharge_cap_pct=4.0)
    re_permitted = read_program(program_id)
    assert re_permitted["status"] == "SUSPENDED", (
        "re-permission hands the program back to its operator rather than reactivating it"
    )
    assert re_permitted["disable_reason"] == "OPERATOR_SUSPENSION"

    final = program_status_action(program_id, "RESUME", reason="statute restored")
    assert final["status"] == "ACTIVE"
    assert final["disable_reason"] == "NONE"
    assert final["effective_cap_pct"] == pytest.approx(2.19, abs=0.0001)


def test_each_resume_restamps_activation_from_the_logical_clock(api):
    """PRD §3.7: "On success `disable_reason` is set to `NONE`, `activated_at` and `activated_by_user_id` are re-stamped from the logical clock and the acting `X-User-ID`, `effective_cap_pct` and `disclosure_ready` are recomputed, and the program's `version` is bumped by 1."
    PRD §3.1: "Applying a law change increments `law_change_count` by exactly 1, sets `last_law_change_at` to the current logical clock, and bumps the jurisdiction's `version`."

    Design: Difficulty/non_linear_state_machine/program_cycle_active_suspend_resume_disable_reactivate
    """
    ctx = setup_enforcing_surcharge_estate(terminal_count=0)
    program_id = ctx["program"]["id"]
    jurisdiction_id = ctx["jurisdiction"]["id"]
    assert ctx["program"]["activated_at"] == TS_AUG_31
    assert ctx["program"]["activated_by_user_id"] == "officer-1"

    program_status_action(program_id, "SUSPEND", reason="internal compliance review")
    program_status_action(program_id, "RESUME", reason="review closed")
    apply_law_change(jurisdiction_id, False, surcharge_cap_pct=None)
    apply_law_change(jurisdiction_id, True, surcharge_cap_pct=4.0)
    program_status_action(program_id, "RESUME", reason="statute restored")

    program = read_program(program_id)
    assert program["activated_at"] == TS_AUG_31, (
        "the clock never moved, so every re-entry into ACTIVE stamps the same instant"
    )
    assert program["activated_by_user_id"] == "officer-1"

    jurisdiction = get_success_data(
        api_client.get_jurisdiction(jurisdiction_id, ADMIN)
    )
    assert jurisdiction["law_change_count"] == 2
    assert jurisdiction["last_law_change_at"] == TS_AUG_31


def test_prohibition_reaches_three_levels_from_statute_to_terminal_census(api):
    """PRD §3.1: "First, every `SurchargeProgram` whose `jurisdiction_id` is the changed jurisdiction, whose `program_type` is `SURCHARGE`, and whose `status` is neither `DISABLED` nor `WITHDRAWN` moves to `DISABLED` with `disable_reason` set to `JURISDICTION_PROHIBITION`"
    PRD §3.1: "Second, for each such program, every `Terminal` whose `program_id` is that program and whose `state` is `CONFIGURED` or `ENFORCING` moves to `QUARANTINED` with `quarantine_reason` set to `PROGRAM_DISABLED`"
    PRD §3.1: "Third, each of those terminal transitions recomputes `enforcing_terminal_count` on the terminal's merchant."

    Design: Difficulty/transitive_cascade/law_change_prohibition_cascade_program_terminals_census
    """
    ctx = setup_enforcing_surcharge_estate(terminal_count=2, serial_prefix="T-AZ-")
    merchant_id = ctx["merchant"]["id"]
    assert read_merchant(merchant_id)["enforcing_terminal_count"] == 2

    apply_law_change(ctx["jurisdiction"]["id"], False, surcharge_cap_pct=None)

    jurisdiction = get_success_data(
        api_client.get_jurisdiction(ctx["jurisdiction"]["id"], ADMIN)
    )
    assert jurisdiction["surcharge_permitted"] is False
    assert jurisdiction["surcharge_cap_pct"] is None
    assert jurisdiction["law_change_count"] == 1
    assert jurisdiction["last_law_change_at"] == TS_AUG_31

    program = read_program(ctx["program"]["id"])
    assert program["status"] == "DISABLED"
    assert program["disable_reason"] == "JURISDICTION_PROHIBITION"

    for terminal in ctx["terminals"]:
        refreshed = read_terminal(terminal["id"])
        assert refreshed["state"] == "QUARANTINED"
        assert refreshed["quarantine_reason"] == "PROGRAM_DISABLED"

    assert read_merchant(merchant_id)["enforcing_terminal_count"] == 0


def test_no_terminal_of_a_prohibited_program_is_still_listed_as_enforcing(api):
    """PRD §3.1: "Every cascaded program's `version` is bumped by 1, as is every cascaded terminal's."
    PRD §3.8: "Terminals may be listed filtered by `merchant_id`, `program_id`, and `state`."

    Design: Difficulty/transitive_cascade/law_change_prohibition_cascade_program_terminals_census
    """
    ctx = setup_enforcing_surcharge_estate(terminal_count=2, serial_prefix="T-AZ-")
    before = {t["id"]: read_terminal(t["id"])["version"] for t in ctx["terminals"]}
    program_version_before = read_program(ctx["program"]["id"])["version"]

    apply_law_change(ctx["jurisdiction"]["id"], False, surcharge_cap_pct=None)

    assert read_program(ctx["program"]["id"])["version"] == program_version_before + 1
    for terminal_id, version in before.items():
        assert read_terminal(terminal_id)["version"] == version + 1

    enforcing, meta = list_page(
        api_client.list_terminals(
            ADMIN, params={"merchant_id": ctx["merchant"]["id"], "state": "ENFORCING"}
        )
    )
    assert meta["total_count"] == 0
    assert enforcing == []


def test_suspension_quarantines_the_whole_estate_at_once(api):
    """PRD §3.7: "Its cascade runs in two steps: first, every `Terminal` of the program in state `ENFORCING` moves to `QUARANTINED` with `quarantine_reason` set to `PROGRAM_SUSPENDED`; second, each such terminal transition recomputes `enforcing_terminal_count` on that terminal's merchant."

    Design: Difficulty/compensating_invariant/suspend_quarantine_cascade_reversed_only_by_explicit_restores
    """
    ctx = setup_enforcing_surcharge_estate(terminal_count=3, serial_prefix="T-AZ-")
    merchant_id = ctx["merchant"]["id"]
    assert read_merchant(merchant_id)["enforcing_terminal_count"] == 3

    suspended = program_status_action(
        ctx["program"]["id"], "SUSPEND", reason="network inquiry pending"
    )
    assert suspended["status"] == "SUSPENDED"
    assert suspended["disable_reason"] == "OPERATOR_SUSPENSION"

    for terminal in ctx["terminals"]:
        refreshed = read_terminal(terminal["id"])
        assert refreshed["state"] == "QUARANTINED"
        assert refreshed["quarantine_reason"] == "PROGRAM_SUSPENDED"

    assert read_merchant(merchant_id)["enforcing_terminal_count"] == 0


def test_resuming_the_program_leaves_the_census_at_zero_until_each_terminal_is_restored(api):
    """PRD §3.7: "Resuming does **not** un-quarantine anything: terminals that were quarantined by the suspension stay quarantined until their operator restores them individually, which is what closes the `ACTIVE → SUSPENDED → ACTIVE` cycle at the program level and leaves the terminal cycle of §3.8 to be closed separately."

    Design: Difficulty/compensating_invariant/suspend_quarantine_cascade_reversed_only_by_explicit_restores
    """
    ctx = setup_enforcing_surcharge_estate(terminal_count=3, serial_prefix="T-AZ-")
    merchant_id = ctx["merchant"]["id"]
    program_id = ctx["program"]["id"]
    program_status_action(program_id, "SUSPEND", reason="network inquiry pending")

    resumed = program_status_action(program_id, "RESUME", reason="inquiry closed")
    assert resumed["status"] == "ACTIVE"
    assert resumed["disable_reason"] == "NONE"
    assert read_merchant(merchant_id)["enforcing_terminal_count"] == 0
    for terminal in ctx["terminals"]:
        assert read_terminal(terminal["id"])["state"] == "QUARANTINED"

    for index, terminal in enumerate(ctx["terminals"], start=1):
        restored = terminal_action(terminal["id"], merchant_id, "RESTORE")
        assert restored["state"] == "ENFORCING"
        assert restored["quarantine_reason"] == "NONE"
        assert read_merchant(merchant_id)["enforcing_terminal_count"] == index

    assert (
        list_total(
            api_client.list_terminals(
                ADMIN, params={"program_id": program_id, "state": "ENFORCING"}
            )
        )
        == 3
    )
