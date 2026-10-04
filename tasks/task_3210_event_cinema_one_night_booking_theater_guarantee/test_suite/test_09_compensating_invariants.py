"""Compensating-action invariants: each compensation returns its conserved quantity to its prior value."""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data, TEST_USERS, ApiErrorId,
    set_clock, create_distributor, create_circuit, create_theater, create_title,
    create_booking, add_line, submit_booking, approve_booking, get_booking,
    get_circuit, get_theater, get_line, run_on_sale_sweep, confirm_booking,
    report_screening, first_screening, make_distributor_headers,
    make_exhibitor_headers, create_settlement_payload, get_title,
)
from test_helpers.api_client import api_client

OPS = TEST_USERS["platform_ops_headers"]
PROG = TEST_USERS["programming_manager_headers"]
FIN = TEST_USERS["finance_ops_headers"]


def _approved_booking(screens=40, pool_total=400):
    set_clock("2026-09-15T00:00:00Z")
    distributor = create_distributor(guarantee_floor_cents=10000,
                                     ticket_price_default_cents=1500)
    circuit = create_circuit(credit_rating="A", settlement_terms="NET_30",
                             screen_pool_total=pool_total)
    theater = create_theater(circuit["id"], seats_total=200)
    title = create_title(distributor["id"], duration_minutes=120,
                         max_screen_commitment=120,
                         rights_end_utc="2027-06-01T00:00:00Z")
    booking = create_booking(title["id"], circuit["id"], guarantee_cents=1000000,
                             revenue_share_pct=0.40)
    line = add_line(booking["id"], circuit["id"], theater["id"],
                    booking["version"], committed_screens=screens,
                    expected_attendance=100)
    booking = submit_booking(booking["id"], circuit["id"], line["version"])
    booking = approve_booking(booking["id"], distributor["id"],
                              booking["version"], line["id"])
    line = get_line(line["id"])
    booking = get_booking(booking["id"])
    return {"distributor": distributor, "circuit": circuit, "theater": theater,
            "title": title, "booking": booking, "line": line,
            "screening": first_screening(booking["id"])}


def test_approval_commits_the_screens_against_the_circuit_pool():
    """PRD §3.2: "On success the booking moves to `APPROVED`, the nominated line's
    `exhibit_state` moves from `PROPOSED` to `COMMITTED`, the circuit's screen balance
    is recomputed, the booking's guarantee allocation is recomputed by the waterfall of
    §3.2, the committed screen total is recomputed".

    Design: Difficulty/compensating_invariant/screen_commitment_conserved_across_release
    """
    scene = _approved_booking(screens=40)
    assert scene["booking"]["status"] == "APPROVED"
    assert scene["line"]["exhibit_state"] == "COMMITTED"
    assert get_circuit(scene["circuit"]["id"])["committed_screens_balance"] == 40


def test_releasing_committed_screens_returns_the_circuit_balance_to_zero():
    """PRD §3.2: "Releasing a line's screens is the compensating action for approval:
    the distributor names a `line_id` and the line moves from `COMMITTED` back to
    `RELEASED`".
    PRD §2.10: "A circuit's `committed_screens_balance` is the number of screens
    currently committed by that circuit's non-terminal bookings, recomputed from
    scratch on every event that could change it."

    Design: Difficulty/compensating_invariant/screen_commitment_conserved_across_release
    """
    scene = _approved_booking(screens=40)
    released = get_success_data(api_client.release_screens(
        scene["booking"]["id"], scene["line"]["id"], scene["booking"]["version"],
        make_distributor_headers(scene["distributor"]["id"])))
    assert released["exhibit_state"] == "RELEASED"
    assert get_circuit(scene["circuit"]["id"])["committed_screens_balance"] == 0, (
        "the conserved quantity returns exactly to its pre-commitment value"
    )


def test_release_cancels_the_lines_screenings_and_revokes_their_keys():
    """PRD §3.2: "with every one of that line's screenings still in `SCHEDULED`
    moving to `SKIPPED_CANCELLED` and driving its keys to `REVOKED` and bumping the
    venue's `pending_rekey_count`, after which the guarantee allocation and the circuit
    balance are recomputed."

    Design: Difficulty/compensating_invariant/screen_commitment_conserved_across_release
    """
    scene = _approved_booking(screens=40)
    issue_scene_key(scene)
    get_success_data(api_client.release_screens(
        scene["booking"]["id"], scene["line"]["id"], scene["booking"]["version"],
        make_distributor_headers(scene["distributor"]["id"])))
    assert get_theater(scene["theater"]["id"])["pending_rekey_count"] == 1, (
        "the line's screening was cancelled and its key revoked in the same request"
    )
    assert get_line(scene["line"]["id"])["exhibit_state"] == "RELEASED"


def test_release_leaves_the_bookings_own_status_untouched():
    """PRD §3.2: "The booking's status is untouched by a release; only the line's
    commitment is undone."

    Design: Difficulty/compensating_invariant/screen_commitment_conserved_across_release
    """
    scene = _approved_booking(screens=40)
    get_success_data(api_client.release_screens(
        scene["booking"]["id"], scene["line"]["id"], scene["booking"]["version"],
        make_distributor_headers(scene["distributor"]["id"])))
    booking = get_booking(scene["booking"]["id"])
    assert booking["status"] == "APPROVED"
    assert booking["committed_screens_total"] == 0


def issue_scene_key(scene):
    """Give the approved booking a verified package and one unissued key.

    PRD §3.4 revokes a key automatically only while it is `PENDING`, so the key
    must not be issued for the release cascade to have anything to revoke.
    """
    from test_helpers import setup_verified_delivery, setup_issued_key
    setup_verified_delivery(scene)
    setup_issued_key(scene, issue=False)
    return scene


def _reported_settlement_scene(settlement_terms="NET_30"):
    set_clock("2026-09-01T00:00:00Z")
    distributor = create_distributor(guarantee_floor_cents=10000,
                                     ticket_price_default_cents=1500)
    circuit = create_circuit(credit_rating="A", settlement_terms=settlement_terms,
                             screen_pool_total=300)
    theater = create_theater(circuit["id"], seats_total=200)
    title = create_title(distributor["id"], duration_minutes=120,
                         max_screen_commitment=120,
                         rights_end_utc="2027-06-01T00:00:00Z")
    booking = create_booking(title["id"], circuit["id"], guarantee_cents=1000000,
                             revenue_share_pct=0.40)
    line = add_line(booking["id"], circuit["id"], theater["id"],
                    booking["version"], committed_screens=30,
                    expected_attendance=100)
    booking = submit_booking(booking["id"], circuit["id"], line["version"])
    booking = approve_booking(booking["id"], distributor["id"],
                              booking["version"], line["id"])
    line = get_line(line["id"])
    booking = get_booking(booking["id"])
    set_clock(booking["on_sale_at"])
    run_on_sale_sweep()
    booking = get_booking(booking["id"])
    booking = confirm_booking(booking["id"], booking["version"])
    screening = first_screening(booking["id"])
    report_screening(screening["id"], theater["id"], 175, "SCREENED",
                     at_instant="2026-12-01T21:30:00Z")
    settlement = get_success_data(api_client.create_settlement(
        create_settlement_payload(booking["id"], gross_box_office_cents=3000000),
        FIN))
    return {"distributor": distributor, "circuit": circuit, "theater": theater,
            "title": title, "booking": get_booking(booking["id"]), "line": line,
            "screening": screening, "settlement": settlement}


def test_settlement_split_conserves_cents_on_creation():
    """PRD §3.6: "Money must be conserved. Every settlement records a drift figure
    defined as the sum of gross, top-up, and adjustment, less the distributor's
    position, less the exhibitor's position; when the calculation is internally
    consistent that figure is zero".

    Design: Difficulty/compensating_invariant/settlement_net_conserved_across_close_and_reopen
    """
    scene = _reported_settlement_scene()
    settlement = scene["settlement"]
    assert settlement["distributor_net_cents"] == 1800000
    assert settlement["exhibitor_net_cents"] == 1200000
    assert (settlement["distributor_net_cents"] + settlement["exhibitor_net_cents"]
            == settlement["gross_box_office_cents"] + settlement["topup_paid_cents"]
            + settlement["adjustment_cents"])
    assert settlement["invariant_drift_cents"] == 0


def test_reopening_the_settlement_does_not_move_the_distributor_net():
    """PRD §3.6: "Reopening returns a closed settlement to `REOPENED` and clears its
    `closed_at_utc`, and the corresponding booking moves back from `SETTLED` to
    `CONFIRMED` with its `settled_at` cleared — the pair moves together."

    Design: Difficulty/compensating_invariant/settlement_net_conserved_across_close_and_reopen
    """
    scene = _reported_settlement_scene()
    settlement = scene["settlement"]
    assert settlement["status"] == "CLOSED"
    reopened = get_success_data(
        api_client.reopen_settlement(settlement["id"], FIN))
    assert reopened["status"] == "REOPENED"
    assert reopened["distributor_net_cents"] == 1800000
    assert get_booking(scene["booking"]["id"])["status"] == "CONFIRMED"


def test_closing_again_restores_the_same_split_with_no_accumulated_drift():
    """PRD §3.6: "Once open, a settlement may be closed explicitly, which stamps its
    `closed_at_utc` and moves the booking to `SETTLED` with the booking's `settled_at`
    set to the same instant".

    Design: Difficulty/compensating_invariant/settlement_net_conserved_across_close_and_reopen
    """
    scene = _reported_settlement_scene()
    settlement = scene["settlement"]
    get_success_data(api_client.reopen_settlement(settlement["id"], FIN))
    closed = get_success_data(api_client.close_settlement(settlement["id"], FIN))
    assert closed["status"] == "CLOSED"
    assert closed["distributor_net_cents"] == 1800000
    assert closed["exhibitor_net_cents"] == 1200000
    assert closed["invariant_drift_cents"] == 0
    assert closed["closed_at_utc"] is not None
    assert get_booking(scene["booking"]["id"])["status"] == "SETTLED"