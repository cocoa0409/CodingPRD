"""The markdown window's inclusive lower bound and exclusive upper bound."""

from test_helpers import (
    ApiErrorId,
    api_client,
    clerk_headers,
    get_success_data,
    platform_admin_headers,
    produce_batch,
    set_clock,
    setup_deli_master_data,
    validate_error,
    validate_success,
)


def _setup_batch_with_a_thirty_minute_window():
    """case_life 120 with a 30-minute markdown window puts the window at
    [hold_expires_at - 30min, hold_expires_at)."""
    set_clock("2026-09-02T07:00:00Z")
    master = setup_deli_master_data(capacity=300, store_number="103", store_name="Store Three",
                                    slicer_count=0)
    slicer = get_success_data(
        api_client.create_slicer(
            {"store_id": master.s, "asset_tag": "SL-8", "sanitation_cycle_limit": 25,
             "assigned_operator_id": master.a1["id"]},
            platform_admin_headers(),
        )
    )
    batch = produce_batch(master.s, master.j2["id"], master.a1["id"], "B-M", 8, produced_lbs=8,
                          slicer_id=slicer["id"])
    return master, batch


def test_markdown_is_accepted_at_the_windows_inclusive_lower_bound():
    """PRD §3.1: "That window is half-open and runs from the hold expiry minus the
    item's `markdown_window_minutes` up to, but not including, the hold expiry; a
    markdown requested before the window opens or at or after the hold expiry
    fails with `ERR_MARKDOWN_WINDOW_CLOSED`."

    The batch went on line at 07:00Z with a 180-minute case life, so the window
    opens at exactly 09:30Z.

    Design: Difficulty/boundary_precision_check/markdown_window_boundary_exclusive_on_a_batch
    """
    master, batch = _setup_batch_with_a_thirty_minute_window()
    assert batch["hold_expires_at"].startswith("2026-09-02T10:00:00"), (
        "the hold window runs 180 minutes from the produced instant"
    )

    set_clock("2026-09-02T09:30:00Z")
    marked = validate_success(
        api_client.mark_down_batch(batch["id"], clerk_headers(master.a1["id"]))
    )
    assert marked["hold_status"] == "MARKED_DOWN", (
        "the lower bound is inclusive, so the exact opening instant is legal"
    )


def test_markdown_is_refused_one_minute_before_the_window_opens():
    """PRD §3.1: "a markdown requested before the window opens or at or after the
    hold expiry fails with `ERR_MARKDOWN_WINDOW_CLOSED`."

    Design: Difficulty/boundary_precision_check/markdown_window_boundary_exclusive_on_a_batch
    """
    master, batch = _setup_batch_with_a_thirty_minute_window()
    set_clock("2026-09-02T09:29:00Z")
    response = api_client.mark_down_batch(batch["id"], clerk_headers(master.a1["id"]))
    validate_error(response, ApiErrorId.ERR_MARKDOWN_WINDOW_CLOSED)

    unchanged = validate_success(api_client.get_batch(batch["id"], platform_admin_headers()))
    assert unchanged["hold_status"] == "HOLDING", "the rejected markdown wrote nothing"
    assert unchanged["production_status"] == "ON_LINE", (
        "only the hold dimension is ever moved by a markdown"
    )


def test_markdown_is_refused_at_the_exclusive_hold_expiry_instant():
    """PRD §2.5: "A hold window is the half-open span running from the instant a
    batch went on line up to, but not including, the instant its hold expires;
    the expiry instant itself is already outside the window."
    PRD §3.1: "a markdown requested before the window opens or at or after the
    hold expiry fails with `ERR_MARKDOWN_WINDOW_CLOSED`."

    Design: Difficulty/boundary_precision_check/markdown_window_boundary_exclusive_on_a_batch
    """
    master, batch = _setup_batch_with_a_thirty_minute_window()
    set_clock("2026-09-02T10:00:00Z")
    response = api_client.mark_down_batch(batch["id"], clerk_headers(master.a1["id"]))
    validate_error(response, ApiErrorId.ERR_MARKDOWN_WINDOW_CLOSED)

    unchanged = validate_success(api_client.get_batch(batch["id"], platform_admin_headers()))
    assert unchanged["hold_status"] == "HOLDING"