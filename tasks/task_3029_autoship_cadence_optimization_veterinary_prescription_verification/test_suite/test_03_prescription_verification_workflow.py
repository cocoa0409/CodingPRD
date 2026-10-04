"""The clinic callback cycle, the attempt cap and the verification-failure cascade."""
from test_helpers import TEST_USERS, api_client, get_success_data
from test_helpers.fixtures import (
    plan_version,
    read_plan,
    read_prescription,
    read_item,
    run_callback_attempt,
    setup_prescription_item,
    setup_prescription_with_callback_attempts,
)


def test_callback_workflow_cycles_in_progress_until_the_cap(api):
    """PRD §3.3: "The first attempt moves the prescription from `PENDING_VERIFICATION`
    to `VERIFICATION_IN_PROGRESS`; a subsequent attempt while the count is still
    below the cap leaves it in `VERIFICATION_IN_PROGRESS` and re-pulls the owning
    item's `autoship_item_next_due_date` to the prescription's verification lead time."

    Design: Difficulty/non_linear_state_machine/callback_workflow_cycles_within_the_attempt_cap
    """
    bundle = setup_prescription_item()
    rx = bundle["rx"]

    assert rx["rx_status"] == "PENDING_VERIFICATION"
    assert rx["callback_attempt_count"] == 0

    after_first = run_callback_attempt(rx)
    assert after_first["callback_attempt_count"] == 1
    assert after_first["rx_status"] == "VERIFICATION_IN_PROGRESS"

    after_second = run_callback_attempt(rx)
    assert after_second["callback_attempt_count"] == 2
    assert after_second["rx_status"] == "VERIFICATION_IN_PROGRESS", (
        "a repeat call below the cap re-enters the same state rather than failing"
    )


def test_third_callback_attempt_fails_the_prescription(api):
    """PRD §3.3: "The third attempt is different in kind: it moves the prescription
    to the terminal `VERIFICATION_FAILED` and fixes `callback_attempt_count` at 3"
    PRD §3.3: "each recorded attempt advances `callback_attempt_count` by one and
    bumps the owning item's `version` by one"

    Design: Difficulty/non_linear_state_machine/callback_workflow_cycles_within_the_attempt_cap
    """
    bundle = setup_prescription_with_callback_attempts(attempts=2)
    rx = bundle["rx"]
    item = bundle["item"]
    version_before = read_item(bundle["plan"], bundle["pet"], item)["version"]

    after_third = run_callback_attempt(rx)

    assert after_third["callback_attempt_count"] == 3
    assert after_third["rx_status"] == "VERIFICATION_FAILED", (
        "the third attempt is the cycle exit into the terminal failure state"
    )
    item_after = read_item(bundle["plan"], bundle["pet"], item)
    assert item_after["version"] == version_before + 1, (
        "the parent item's version tracks its prescription's verification activity"
    )


def test_failed_verification_blocks_the_item_and_suspends_the_plan(api):
    """PRD §3.3: "it fires the three-hop cascade described in §2.8 — the owning item's
    `verification_state` goes from `UNVERIFIED` to `BLOCKED`, the plan's `plan_status`
    goes from `ACTIVE` to `SUSPENDED` because a live item on it is blocked, and the
    plan's `autoship_discount_eligibility` goes from `ELIGIBLE` to `INELIGIBLE`."
    PRD §2.8: "When a prescription fails verification outright, the first hop marks
    the owning item's verification `BLOCKED`; the second hop suspends the plan
    because it now carries a live blocked item; the third hop revokes the plan's
    autoship discount eligibility because a plan carrying a blocked item is no
    longer eligible."

    Design: Difficulty/transitive_cascade/third_callback_failure_suspends_the_plan_and_revokes_discounts
    """
    bundle = setup_prescription_with_callback_attempts(attempts=2)
    plan = bundle["plan"]
    pet = bundle["pet"]
    item = bundle["item"]

    assert read_item(plan, pet, item)["verification_state"] == "UNVERIFIED"
    assert read_plan(plan, pet)["plan_status"] == "ACTIVE"
    assert read_plan(plan, pet)["autoship_discount_eligibility"] == "ELIGIBLE"

    run_callback_attempt(bundle["rx"])

    assert read_item(plan, pet, item)["verification_state"] == "BLOCKED"
    plan_after = read_plan(plan, pet)
    assert plan_after["plan_status"] == "SUSPENDED"
    assert plan_after["autoship_discount_eligibility"] == "INELIGIBLE"


def test_reopen_clears_the_block_and_resets_the_callback_window(api):
    """PRD §3.3: "A pharmacy manager can unwind that state with the reopen capability,
    which returns the prescription from `VERIFICATION_FAILED` to
    `PENDING_VERIFICATION`, resets `callback_attempt_count` to zero, and clears the
    item's verification from `BLOCKED` back to `UNVERIFIED`."
    PRD §2.8: "A verification block is only ever cleared by the pharmacy manager's
    reopen capability, which returns the prescription to the beginning of the
    callback workflow and resets the item's verification to unverified."

    Design: Difficulty/transitive_cascade/third_callback_failure_suspends_the_plan_and_revokes_discounts
    """
    bundle = setup_prescription_with_callback_attempts(attempts=2)
    plan = bundle["plan"]
    pet = bundle["pet"]
    item = bundle["item"]
    rx = bundle["rx"]
    run_callback_attempt(rx)
    assert read_item(plan, pet, item)["verification_state"] == "BLOCKED"

    reopened = get_success_data(api_client.reopen_prescription(
        rx["id"], TEST_USERS["pharmacy_manager_headers"]))

    assert reopened["rx_status"] == "PENDING_VERIFICATION"
    assert reopened["callback_attempt_count"] == 0
    assert read_item(plan, pet, item)["verification_state"] == "UNVERIFIED"