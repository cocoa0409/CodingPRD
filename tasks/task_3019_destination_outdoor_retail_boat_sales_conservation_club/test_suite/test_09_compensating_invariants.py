"""Depth tests: compensating-action invariants across different conserved quantities."""
from test_helpers import (
    ATTRACTION_HOST,
    STORE_MANAGER,
    create_member,
    create_open_attraction,
    create_point_event,
    create_store,
    get_success_data,
    request_session,
    set_clock,
)


# ===========================================================================
# points_redemption_reversal_conserves_the_ledger  (queue A / compensating_invariant)
# ===========================================================================

def _gold_member_at_26500(api):
    """A member reading GOLD at 26500 lifetime and 25000 redeemable."""
    set_clock(api, "2026-09-01T00:00:00Z")
    store = create_store(api)
    member = create_member(api, store["id"], email="m_ci@x.com",
                           full_name="Iris Cove")
    for delta in (25_000, 1_000, 500):
        create_point_event(api, store["id"], member["id"], event_kind="AWARD",
                           points_delta=delta)
    refreshed = get_success_data(api.get_member(member["id"], STORE_MANAGER), 200)
    return store, refreshed


def test_the_redemption_moves_exactly_the_delta_it_carries(api):
    """PRD §2.8.1: "For `REDEEM` events the absolute value of the event's
    `points_delta` is subtracted from the balance and the lifetime total is
    untouched."
    PRD §2.8.1: "`redeemable_points` is then computed as the member's
    `points_balance` minus a tier retention floor, clamped at zero."

    Design: Difficulty/compensating_invariant/points_redemption_reversal_conserves_the_ledger
    """
    store, member = _gold_member_at_26500(api)
    assert member["points_balance"] == 26_500
    assert member["points_lifetime_earned"] == 26_500
    assert member["club_tier"] == "GOLD"
    assert member["redeemable_points"] == 25_000, (
        "26500 balance minus the GOLD retention floor of 1500; got "
        f"{member['redeemable_points']}"
    )

    create_point_event(api, store["id"], member["id"], event_kind="REDEEM",
                       points_delta=-300)
    after_redeem = get_success_data(api.get_member(member["id"], STORE_MANAGER), 200)
    assert after_redeem["points_balance"] == 26_200, (
        f"exactly 300 points moved; got {after_redeem['points_balance']}"
    )
    assert after_redeem["points_lifetime_earned"] == 26_500, (
        "a redemption does not reduce lifetime earnings; got "
        f"{after_redeem['points_lifetime_earned']}"
    )


def test_a_reversal_of_the_same_magnitude_restores_the_conserved_quantity(api):
    """PRD §2.8.1: "For `REVERSAL` events the event's signed delta is added to
    the balance and the absolute value of that delta is subtracted from the
    lifetime total, because a reversal of an award is recorded as a negative
    movement."
    PRD §2.8.1: "After each event both running totals are clamped at zero by
    taking the greater of the running total and zero."
    PRD §2.8.1: "`redeemable_points` is then computed as the member's
    `points_balance` minus a tier retention floor, clamped at zero."

    Design: Difficulty/compensating_invariant/points_redemption_reversal_conserves_the_ledger
    """
    store, member = _gold_member_at_26500(api)
    balance_before = member["points_balance"]
    lifetime_before = member["points_lifetime_earned"]

    create_point_event(api, store["id"], member["id"], event_kind="REDEEM",
                       points_delta=-300)
    after_redeem = get_success_data(api.get_member(member["id"], STORE_MANAGER), 200)
    assert after_redeem["points_balance"] == balance_before - 300, (
        f"the redemption moves the balance alone; got {after_redeem['points_balance']}"
    )
    assert after_redeem["points_lifetime_earned"] == lifetime_before

    # A reversal carries a signed delta: it adds that delta to the balance and
    # subtracts its magnitude from the lifetime total.
    create_point_event(api, store["id"], member["id"], event_kind="REVERSAL",
                       points_delta=-300, boat_deal_id=None)
    after = get_success_data(api.get_member(member["id"], STORE_MANAGER), 200)

    assert after["points_balance"] == balance_before - 600, (
        "the reversal's signed delta is added to the balance; expected "
        f"{balance_before - 600}, got {after['points_balance']}"
    )
    assert after["points_lifetime_earned"] == lifetime_before - 300, (
        "the reversal subtracts its magnitude from the lifetime total; expected "
        f"{lifetime_before - 300}, got {after['points_lifetime_earned']}"
    )
    assert after["club_tier"] == "GOLD", (
        "26200 lifetime points still clear the 25000-point GOLD threshold; got "
        f"{after['club_tier']}"
    )
    assert after["redeemable_points"] == 24_400, (
        "25900 balance minus the GOLD retention floor of 1500; got "
        f"{after['redeemable_points']}"
    )


# ===========================================================================
# cancel_restore_conserves_the_exact_committed_dwell  (queue A / compensating_invariant)
# ===========================================================================

def _aquarium_with_two_members(api, capacity_units=40, dwell_cost_minutes=30,
                               dwell_capacity_minutes=60_000):
    set_clock(api, "2026-09-01T00:00:00Z")
    store = create_store(api, dwell_capacity_minutes=dwell_capacity_minutes)
    attraction = create_open_attraction(api, store["id"], attraction_type="AQUARIUM",
                                        capacity_units=capacity_units,
                                        dwell_cost_minutes=dwell_cost_minutes)
    member_one = create_member(api, store["id"], email="m_ci1@x.com",
                               full_name="Ivo Carr")
    member_two = create_member(api, store["id"], email="m_ci2@x.com",
                               full_name="Ines Carr")
    return store, attraction, member_one, member_two


def test_a_ten_guest_party_commits_the_triple_band_charge_and_the_cancel_restores_it(api):
    """PRD §2.7: "Consumed minutes are tracked as `dwell_committed_minutes`,
    defined as the sum of `dwell_charge_minutes` across the store's attraction
    sessions whose `status` is `CONFIRMED` or `IN_PROGRESS`."
    PRD §2.8.1: "The base is the per-guest rate multiplied by that band
    multiplier."
    PRD §3.1: "cancelling a `CONFIRMED` session subtracts its `party_size` from
    the venue's `in_use_units`, recomputes the committed and free minute totals,
    and re-evaluates the posture."

    Design: Difficulty/compensating_invariant/cancel_restore_conserves_the_exact_committed_dwell
    """
    store, attraction, member_one, member_two = _aquarium_with_two_members(api)

    baseline = get_success_data(api.get_dwell_summary(store["id"], STORE_MANAGER), 200)
    assert baseline["dwell_committed_minutes"] == 0, (
        "a fresh store commits nothing; got "
        f"{baseline['dwell_committed_minutes']}"
    )
    assert baseline["dwell_free_minutes"] == 60_000

    session = get_success_data(
        request_session(api, store["id"], attraction["id"], member_one["id"],
                        party_size=10, slot_start_utc="2026-11-01T10:00:00Z",
                        slot_end_utc="2026-11-01T11:00:00Z"),
        201,
    )
    assert session["status"] == "CONFIRMED"
    assert session["dwell_charge_minutes"] > 30, (
        "a party of ten pays the triple band rate of the per-guest dwell cost, so "
        f"the venue's purchase multiplies the cost; got {session['dwell_charge_minutes']}"
    )

    live = get_success_data(api.get_dwell_summary(store["id"], STORE_MANAGER), 200)
    assert live["dwell_committed_minutes"] == session["dwell_charge_minutes"], (
        "the committed total is the sum of dwell_charge_minutes over the store's "
        f"live sessions; got {live['dwell_committed_minutes']}"
    )
    assert live["dwell_free_minutes"] == 60_000 - live["dwell_committed_minutes"]

    get_success_data(api.cancel_session(session["id"], ATTRACTION_HOST), 200)
    after_cancel = get_success_data(api.get_dwell_summary(store["id"], STORE_MANAGER), 200)
    assert after_cancel["dwell_committed_minutes"] == 0, (
        "committed_after_cancel == committed_before_confirm; got "
        f"{after_cancel['dwell_committed_minutes']}"
    )


def test_reconfirming_the_identical_party_brings_the_store_back_to_the_same_total(api):
    """PRD §2.7: "Sessions in `REQUESTED`, `WAITLIST_FALLBACK`, `COMPLETED`,
    `NO_SHOW` or `CANCELLED` consume nothing."
    PRD §3.1: "Releasing capacity runs the same machinery in reverse: cancelling
    a `CONFIRMED` session subtracts its `party_size` from the venue's
    `in_use_units`, recomputes the committed and free minute totals, and
    re-evaluates the posture, so a store that had gone `RESTRICTED` returns to
    `OPEN` once enough sessions release."

    Design: Difficulty/compensating_invariant/cancel_restore_conserves_the_exact_committed_dwell
    """
    store, attraction, member_one, member_two = _aquarium_with_two_members(api)

    first = get_success_data(
        request_session(api, store["id"], attraction["id"], member_one["id"],
                        party_size=10, slot_start_utc="2026-11-01T10:00:00Z",
                        slot_end_utc="2026-11-01T11:00:00Z"),
        201,
    )
    first_charge = first["dwell_charge_minutes"]
    get_success_data(api.cancel_session(first["id"], ATTRACTION_HOST), 200)

    second = get_success_data(
        request_session(api, store["id"], attraction["id"], member_two["id"],
                        party_size=10, slot_start_utc="2026-11-02T10:00:00Z",
                        slot_end_utc="2026-11-02T11:00:00Z"),
        201,
    )
    assert second["dwell_charge_minutes"] == first_charge, (
        "the identical party recomputes to the identical charge; got "
        f"{second['dwell_charge_minutes']} against {first_charge}"
    )
    summary = get_success_data(api.get_dwell_summary(store["id"], STORE_MANAGER), 200)
    assert summary["dwell_committed_minutes"] == first_charge, (
        "the replacement party brings the store back to exactly the charge the "
        f"cancel released; got {summary['dwell_committed_minutes']}"
    )
    assert summary["dwell_free_minutes"] == 60_000 - first_charge