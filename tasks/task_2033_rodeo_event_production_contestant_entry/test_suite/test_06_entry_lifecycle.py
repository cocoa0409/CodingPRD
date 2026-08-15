"""Entry lifecycle: turn-out, re-entry, draw-out, and performance
cancellation gating (PRD §2.1, §3.2, §3.6)."""
from test_helpers import (
    ApiErrorId,
    assignment_for_entry,
    compute_payout,
    execute_draw,
    file_vet_report,
    get_assignment,
    get_entry,
    get_performance,
    make_contestant_headers,
    setup_drawn,
    setup_entries_open,
    enter,
    register_contestant,
    TEST_USERS,
    transition_entry,
    transition_rodeo,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["committee_admin_headers"]
OFFICE = TEST_USERS["entry_office_headers"]


def test_voluntary_turnout_forfeits_fee_and_reentry_charges_again(api):
    """PRD §3.2: "A voluntary turn-out forfeits the entire fee to the purse —
    nothing is refunded."
    PRD §3.2: "The split is recomputed from the event's current
    `entry_fee_cents`, the new fee adds onto `fee_charges_cents`, the new
    contribution onto `contribution_charges_cents`, both `turn_out_reason` and
    `vet_report_id` are cleared, and the purse grows by the new contribution."

    Design: Difficulty/non_linear_state_machine/entry_turn_out_re_entry_cycle
    """
    sc = setup_drawn(
        event_code="BULL_RIDING", num_contestants=1, animal_tags=("A100",),
        event_overrides={"per_performance_slots": 5},
        card_prefix="PRCA-601",
    )
    entry = sc["entries"][0]
    assert get_entry(entry["id"])["status"] == "DRAWN"

    turned_out = transition_entry(
        entry["id"], {"action": "TURN_OUT", "reason": "VOLUNTARY"}, OFFICE
    )
    assert turned_out["status"] == "TURNED_OUT"
    assert turned_out["turn_out_reason"] == "VOLUNTARY"
    assert turned_out["refunded_cents"] == 0, (
        "a voluntary turn-out forfeits the entire fee; nothing is refunded"
    )

    # Re-entry is gated on ENTRIES_OPEN; unlock the draw to reopen the window.
    transition_rodeo(sc["rodeo"]["id"], "UNLOCK_DRAW")
    reentered = transition_entry(entry["id"], {"action": "RE_ENTER"}, OFFICE)
    assert reentered["status"] == "ENTERED"
    assert reentered["fee_charges_cents"] == 4000, (
        f"two charges of 2000 accumulate: {reentered['fee_charges_cents']}"
    )
    assert reentered["contribution_charges_cents"] == 2320, (
        f"two contributions of 1160 accumulate: "
        f"{reentered['contribution_charges_cents']}"
    )
    assert reentered["turn_out_reason"] is None
    assert reentered["vet_report_id"] is None
    assert reentered["refunded_cents"] == 0


def test_reentry_redraws_and_purse_reflects_double_contribution(api):
    """PRD §3.2: "Because a voluntary turn-out forfeited the first fee, a
    contestant who turns out and re-enters legitimately contributes to the
    purse twice — this is intended behavior, not an accounting error."
    PRD §3.7: "Its purse — `purse_cents` — is the event's `added_money_cents`
    plus, summed over all of the event's entries regardless of their status,
    each entry's `contribution_charges_cents` minus its
    `refunded_contribution_cents`."

    Design: Difficulty/non_linear_state_machine/entry_turn_out_re_entry_cycle
    """
    sc = setup_drawn(
        event_code="BULL_RIDING", num_contestants=1, animal_tags=("A100",),
        event_overrides={"per_performance_slots": 5},
        card_prefix="PRCA-602",
    )
    entry = sc["entries"][0]
    transition_entry(entry["id"], {"action": "TURN_OUT", "reason": "VOLUNTARY"},
                     OFFICE)
    transition_rodeo(sc["rodeo"]["id"], "UNLOCK_DRAW")
    transition_entry(entry["id"], {"action": "RE_ENTER"}, OFFICE)

    # Re-lock and re-draw: the entry closes the cycle DRAWN again.
    transition_rodeo(sc["rodeo"]["id"], "LOCK_DRAW")
    execute_draw(sc["event"]["id"], go_round_number=1)
    assert get_entry(entry["id"])["status"] == "DRAWN"

    payout = compute_payout(sc["event"]["id"], "PROVISIONAL")
    assert payout["purse_cents"] == 2320, (
        f"purse = added 0 + cumulative contributions 2320 - refunded 0, "
        f"got {payout['purse_cents']}"
    )


def test_turnout_from_entered_rejected(api):
    """PRD §3.2: "A drawn contestant may turn out — `TURN_OUT` from `DRAWN`,
    carrying a `reason` of `VOLUNTARY` or `MEDICAL` — only while the rodeo is
    `DRAW_LOCKED` or `IN_PROGRESS` (`ERR_RODEO_NOT_OPEN` otherwise)."
    PRD §2.8: "6. State-machine legality — the requested transition action is
    valid from the resource's current state, including the lockdown of
    terminal states (`ERR_INVALID_STATE`)."

    Design: Corner/state_machines/turnout_from_entered_rejected
    """
    sc = setup_entries_open(
        event_overrides={"event_code": "BAREBACK", "entry_fee_cents": 2000}
    )
    contestant = register_contestant("PRCA-220", "Rider X")
    entry = enter(contestant["id"], sc["event"]["id"])
    assert entry["status"] == "ENTERED"

    resp = api.entry_transition(
        entry["id"], {"action": "TURN_OUT", "reason": "VOLUNTARY"}, OFFICE
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    after = get_entry(entry["id"])
    assert after["status"] == "ENTERED"
    assert after["refunded_cents"] == 0


def test_medical_turnout_requires_vet_report(api):
    """PRD §3.2: "A medical turn-out must name a `vet_report_id` referencing a
    vet report whose `disposition` is `INJURED_TURNOUT`; without that linkage
    the request fails with `ERR_MEDICAL_RELEASE_REQUIRED`." and "A medical
    turn-out refunds the purse contribution: `refunded_cents` and
    `refunded_contribution_cents` each grow by the contribution, and the purse
    shrinks accordingly."

    Design: Corner/validations/medical_turnout_requires_vet_report
    """
    sc = setup_drawn(
        event_code="BULL_RIDING", num_contestants=1, animal_tags=("A100",),
        event_overrides={"per_performance_slots": 5},
        card_prefix="PRCA-440",
    )
    entry = sc["entries"][0]

    missing_report = api.entry_transition(
        entry["id"], {"action": "TURN_OUT", "reason": "MEDICAL"}, OFFICE
    )
    validate_error(missing_report, ApiErrorId.ERR_MEDICAL_RELEASE_REQUIRED)
    assert get_entry(entry["id"])["status"] == "DRAWN"

    report = file_vet_report(
        subject_type="CONTESTANT",
        contestant_id=sc["contestants"][0]["id"],
        findings="Broken collarbone",
        disposition="INJURED_TURNOUT",
        veterinarian_name="Dr. Ellis",
    )
    turned_out = transition_entry(
        entry["id"],
        {"action": "TURN_OUT", "reason": "MEDICAL", "vet_report_id": report["id"]},
        OFFICE,
    )
    assert turned_out["status"] == "TURNED_OUT"
    assert turned_out["turn_out_reason"] == "MEDICAL"
    assert turned_out["vet_report_id"] == report["id"]
    assert turned_out["refunded_cents"] == 1160
    assert turned_out["refunded_contribution_cents"] == 1160


def test_performance_cancel_with_assignments_rejected(api):
    """PRD §3.6: "Cancelling it (`CANCEL_PERFORMANCE`: `SCHEDULED` →
    `CANCELLED`) is blocked while any draw assignment in `PENDING` or
    `COMPLETED` status references the performance (`ERR_PERF_HAS_ASSIGNMENTS`);
    when the cancel does succeed, every `PAID` ticket order for that
    performance is refunded and `sold_tickets` is recomputed."

    Design: Corner/state_machines/performance_cancel_with_assignments_rejected
    """
    sc = setup_drawn(
        event_code="BULL_RIDING", num_contestants=1, animal_tags=("A100",),
        event_overrides={"per_performance_slots": 5},
        card_prefix="PRCA-260",
    )
    performance = sc["performance"]
    entry = sc["entries"][0]

    blocked = api.performance_transition(
        performance["id"], {"action": "CANCEL_PERFORMANCE"}, ADMIN
    )
    validate_error(blocked, ApiErrorId.ERR_PERF_HAS_ASSIGNMENTS)
    assert get_performance(performance["id"])["status"] == "SCHEDULED"

    # Turning the entry out releases its assignment, unblocking the cancel.
    transition_entry(entry["id"], {"action": "TURN_OUT", "reason": "VOLUNTARY"},
                     OFFICE)
    da = assignment_for_entry(entry["id"])
    assert get_assignment(da["id"])["status"] == "RELEASED"

    cancelled = validate_success(
        api.performance_transition(
            performance["id"], {"action": "CANCEL_PERFORMANCE"}, ADMIN
        ),
        200,
    )
    assert cancelled["status"] == "CANCELLED"


def test_entry_draw_out_is_committee_only(api):
    """PRD §3.2: "`DRAW_OUT`, restricted to a `CommitteeAdmin` and valid from
    `DRAWN`, is the full-refund removal: `refunded_cents` grows by the entire
    fee including the sanction, `refunded_contribution_cents` grows by the
    contribution, pending assignments are released with their animals freed,
    and the purse is recomputed."

    Design: Corner/rbac/entry_draw_out_is_committee_only
    """
    sc = setup_drawn(
        event_code="BARREL_RACING", num_contestants=1, animal_tags=(),
        event_overrides={"per_performance_slots": 5},
        card_prefix="PRCA-496",
    )
    entry = sc["entries"][0]

    forbidden = api.entry_transition(entry["id"], {"action": "DRAW_OUT"}, OFFICE)
    validate_error(forbidden, ApiErrorId.ERR_FORBIDDEN)
    assert get_entry(entry["id"])["status"] == "DRAWN"

    drawn_out = validate_success(
        api.entry_transition(entry["id"], {"action": "DRAW_OUT"}, ADMIN), 200
    )
    assert drawn_out["status"] == "DRAWN_OUT"
    assert drawn_out["refunded_cents"] == 2000, (
        "full refund including the sanction fee"
    )
    assert drawn_out["refunded_contribution_cents"] == 1160


def test_contestant_cannot_turn_out_anothers_entry(api):
    """PRD §2.1: "A request whose role is not permitted for the endpoint or
    action is rejected with `ERR_FORBIDDEN` (HTTP 403); the same rejection
    applies when a `Contestant` attempts to act on an entry belonging to
    someone else."
    PRD §2.1: "When `X-User-Role` is `Contestant`, `X-User-ID` is the `id` of
    the acting Contestant, and ownership checks on any entry compare the
    entry's `contestant_id` field to `X-User-ID`."

    Design: Corner/validations/contestant_cannot_turn_out_anothers_entry
    """
    sc = setup_drawn(
        event_code="BARREL_RACING", num_contestants=1, animal_tags=(),
        event_overrides={"per_performance_slots": 5},
        card_prefix="PRCA-482",
    )
    entry = sc["entries"][0]
    other_contestant = register_contestant("PRCA-481", "Rider X")

    resp = api.entry_transition(
        entry["id"],
        {"action": "TURN_OUT", "reason": "VOLUNTARY"},
        make_contestant_headers(other_contestant["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    assert get_entry(entry["id"])["status"] == "DRAWN"
