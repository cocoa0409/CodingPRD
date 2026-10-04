"""The slicer's cyclic sanitation life and the reopen revert edge."""

from test_helpers import (
    api_client,
    clerk_headers,
    get_success_data,
    manager_headers,
    open_sanitation_cycle,
    platform_admin_headers,
    produce_batch,
    set_clock,
    setup_deli_master_data,
    validate_success,
)


def _setup_sanitized_then_reopened():
    """Produce 60 lbs on one slicer so the cut counter reaches 12 and the ROUTINE
    threshold is unmet, open and complete a cycle, then reopen it."""
    set_clock("2026-09-02T06:00:00Z")
    master = setup_deli_master_data(capacity=300, store_number="103", store_name="Store Three",
                                    slicer_count=0)
    slicer = get_success_data(
        api_client.create_slicer(
            {"store_id": master.s, "asset_tag": "SL-3", "sanitation_cycle_limit": 12,
             "assigned_operator_id": master.a3["id"]},
            platform_admin_headers(),
        )
    )
    create_routine = get_success_data(
        api_client.create_certification(
            {"store_id": master.s, "associate_id": master.a3["id"], "cert_type": "SLICER_OPERATION",
             "issued_at": "2026-09-01T00:00:00Z", "expires_at": "2026-12-31T00:00:00Z"},
            platform_admin_headers(),
        )
    )
    assert create_routine["status"] == "ACTIVE"

    batch = produce_batch(master.s, master.j2["id"], master.a3["id"], "B-030", 60, produced_lbs=60,
                          slicer_id=slicer["id"])
    cycle = open_sanitation_cycle(master.s, slicer["id"], master.a3["id"])

    set_clock("2026-09-02T06:11:00Z")
    completed = get_success_data(
        api_client.complete_sanitation_cycle(cycle["id"], master.a3["id"], clerk_headers(master.a3["id"]))
    )
    assert completed["status"] == "COMPLETE"

    reopened = get_success_data(
        api_client.reopen_sanitation_cycle(
            cycle["id"], "cycle evidence invalidated by manager review", manager_headers(master.a3["id"])
        )
    )
    return master, slicer, batch, cycle, reopened


def test_reopen_reverts_the_cycle_and_returns_the_slicer_to_needs_sanitation():
    """PRD §3.2: "A completed cycle may be reopened, which is a manager-level
    reversal of a sanitation claim: the manager asserts the cycle's evidence is
    invalid, the cycle's status moves to `ABORTED` with its reopen count
    incremented, the slicer returns to `NEEDS_SANITATION`."

    Design: Difficulty/non_linear_state_machine/slicer_sanitation_cycle_loop
    """
    master, slicer, _, cycle, _ = _setup_sanitized_then_reopened()
    cycle_now = validate_success(api_client.get_sanitation_cycle(cycle["id"], platform_admin_headers()))
    assert cycle_now["status"] == "ABORTED", (
        "the completed cycle takes the revert edge rather than terminating"
    )
    slicer_now = validate_success(api_client.get_slicer(slicer["id"], platform_admin_headers()))
    assert slicer_now["sanitation_status"] == "NEEDS_SANITATION", (
        "the asset returns to the state that admits the next sanitizing entry"
    )


def test_reopen_leaves_the_cut_counter_uncredited():
    """PRD §3.2: "the cycle's status moves to `ABORTED` with its reopen count
    incremented, the slicer returns to `NEEDS_SANITATION`, and critically
    `cuts_since_sanitation` is not reset."

    The aborted cycle earns no credit of its own: the reopen edge does not push
    the counter back up, and it does not re-apply the completion's reset.

    Design: Difficulty/non_linear_state_machine/slicer_sanitation_cycle_loop
    """
    master, slicer, _, _, _ = _setup_sanitized_then_reopened()
    slicer_now = validate_success(api_client.get_slicer(slicer["id"], platform_admin_headers()))
    assert slicer_now["cuts_since_sanitation"] == 0, (
        "an invalidated cycle grants no credit, and the completion's reset stands"
    )
    assert slicer_now["last_sliced_deli_item_id"] == master.j2["id"]
    assert slicer_now["sanitation_status"] == "NEEDS_SANITATION"