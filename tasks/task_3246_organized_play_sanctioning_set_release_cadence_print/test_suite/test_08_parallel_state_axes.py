"""The event application's two independent state axes, and the code card's
independent lifecycle and grant axes."""
from test_helpers import (
    get_allocation,
    get_application,
    get_code,
    setup_application,
    setup_pool_with_physical_grants,
    transition_application,
)


def test_the_prizing_axis_cycles_while_the_reporting_axis_never_moves(api):
    """PRD §3.4: "The store may also opt into and out of its reporting window
    independently of where the application sits in its sanctioning lifecycle.
    Opting in moves `prizing_report_status` to `DUE` and is allowed from
    `SUBMITTED`, `APPROVED` or `COMPLETED`; opting out moves it back to `NOT_DUE`
    from the same three states. Neither option touches any allocation."

    Design: Difficulty/non_linear_state_machine/event_application_parallel_status_and_prizing_dimensions_revert
    """
    store, _set_release, _fmt, application, allocation = setup_application(tier="LOCAL")

    transition_application(application["id"], "OPTION_IN").raise_for_status()
    assert get_application(application["id"])["prizing_report_status"] == "DUE"

    transition_application(application["id"], "OPTION_OUT").raise_for_status()
    assert get_application(application["id"])["prizing_report_status"] == "NOT_DUE"

    transition_application(application["id"], "OPTION_IN").raise_for_status()
    after = get_application(application["id"])
    assert after["prizing_report_status"] == "DUE", (
        "the prizing axis has cycled twice"
    )
    assert after["status"] == "APPROVED", "the reporting axis never moved"


def test_the_reporting_window_options_leave_the_pool_untouched(api):
    """PRD §3.4: "Opting in moves `prizing_report_status` to `DUE` and is allowed
    from `SUBMITTED`, `APPROVED` or `COMPLETED`; opting out moves it back to
    `NOT_DUE` from the same three states. Neither option touches any allocation."
    PRD §3.4: "One thing approval deliberately does not do is move
    `prizing_report_status`. That dimension is driven only by the set release
    reaching `RELEASED` and by the store choosing to opt in or out, described
    next."

    Design: Difficulty/non_linear_state_machine/event_application_parallel_status_and_prizing_dimensions_revert
    """
    store, _set_release, _fmt, application, allocation = setup_application(tier="LOCAL")
    before = get_allocation(allocation["id"])
    assert before["remaining_tp"] == 16

    transition_application(application["id"], "OPTION_IN").raise_for_status()
    transition_application(application["id"], "OPTION_OUT").raise_for_status()
    transition_application(application["id"], "OPTION_IN").raise_for_status()

    after = get_allocation(allocation["id"])
    assert after["remaining_tp"] == 16
    assert after["base_tp"] == before["base_tp"]
    assert after["total_drawn_tp"] == 0
    assert after["total_restored_tp"] == 0


def test_a_physical_card_is_redeemed_while_its_grant_is_still_reserved(api):
    """PRD §3.11: "Its redemption sets `physical_grant_status` to `RESERVED`,
    which opens a second dimension that does not exist for digital cards."
    PRD §3.11: "A successful redemption assigns the card a `redemption_seq` from
    the global monotonic sequence and moves it to `REDEEMED`, and from that point
    the two paths diverge."

    Design: Difficulty/non_linear_state_machine/code_redemption_parallel_lifecycle_and_grant_dimensions
    """
    store, _set_release, _fmt, application, allocation, cards = (
        setup_pool_with_physical_grants(grant_count=1, extra_tp=150, tier="LOCAL")
    )

    card = get_code(cards[0]["id"])
    assert card["status"] == "REDEEMED"
    assert card["physical_grant_status"] == "RESERVED", (
        "the lifecycle axis and the grant axis disagree at this point"
    )
    assert card["redemption_seq"] == 1
    assert card["code_kind"] == "PHYSICAL"


def test_disbursement_advances_the_grant_axis_alone(api):
    """PRD §3.11: "That dimension advances later, when an operator disburses the
    grant, moving `physical_grant_status` from `RESERVED` to `DISBURSED`, and
    disbursement is available only when the card has actually been redeemed and
    the event application it was redeemed against has reached `COMPLETED`."
    PRD §3.11: "Disbursement is terminal for the grant dimension."

    Design: Difficulty/non_linear_state_machine/code_redemption_parallel_lifecycle_and_grant_dimensions
    """
    store, _set_release, _fmt, application, allocation, cards = (
        setup_pool_with_physical_grants(grant_count=1, extra_tp=150, tier="LOCAL")
    )

    from test_helpers import disburse_code

    disburse_code(cards[0]["id"]).raise_for_status()

    card = get_code(cards[0]["id"])
    assert card["physical_grant_status"] == "DISBURSED"
    assert card["status"] == "REDEEMED", (
        "the lifecycle axis is undisturbed by the grant movement"
    )
    assert card["prize_allocation_id"] == allocation["id"]

    pool = get_allocation(allocation["id"])
    assert pool["total_drawn_tp"] == 40
    assert pool["total_restored_tp"] == 40
    assert pool["remaining_tp"] == 166

def test_a_grant_never_leaves_the_pool_short_however_large_the_pool(api):
    """PRD §3.11: "The floored figure is computed once for the grant and used for
    both sides — the grant's two counter movements are bit-for-bit identical, so
    the conserved invariant over the pool is exactly what it was before the
    disbursement."
    PRD §3.11: "That is what makes a physical grant a value transfer rather than a
    net draw on the pool."

    Design: Difficulty/compensating_invariant/physical_grant_points_conserved_within_draw_and_restore
    """
    from test_helpers import disburse_code

    store, _set_release, _fmt, application, allocation, cards = (
        setup_pool_with_physical_grants(grant_count=2, extra_tp=150, tier="LOCAL")
    )
    before = get_allocation(allocation["id"])

    for card in cards:
        disburse_code(card["id"]).raise_for_status()

    after = get_allocation(allocation["id"])
    assert after["total_drawn_tp"] == 80
    assert after["total_restored_tp"] == 80, (
        "the same floored figure lands on both counters, so the net movement is zero"
    )
    assert after["remaining_tp"] == before["remaining_tp"] == 166
    assert after["status"] == "OPEN"
