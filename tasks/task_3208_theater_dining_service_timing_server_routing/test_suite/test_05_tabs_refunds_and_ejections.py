"""The tab: automatic compensation, the compensating ejection refund, and scoring."""
import pytest

from test_helpers import (
    api_client, LEAD,
    validate_success, validate_error, get_success_data,
    assert_check_tab, assert_check_tab_zero_balance_invariant,
    assert_section_assignment, assert_server,
    server_headers,
    read_check, read_server,
    setup_compensated_check_for_ejection, setup_delivered_entree_with_ejection,
)


def test_ejection_refund_fills_the_remainder_not_a_second_thirty_percent(api):
    """PRD §3.8: "When the kitchen lead approves the ejection of a guest seated on
    a slip (§3.10), the refund booked against that slip's tab is not a percentage
    but the entire remaining remainder: the refunded amount is raised directly to
    the original total, the tab moves to `REFUNDED`, and the reason is recorded as
    `EJECTION_NO_TALKING` when the underlying disturbance was a talking offence
    and `EJECTION_NO_TEXTING` when it was a texting offence."
    PRD §3.8: "a tab that has already absorbed an automatic thirty-percent
    compensation and is then hit by an ejection refund settles at exactly zero,
    not at thirty percent of the original."

    Design: Difficulty/compensating_invariant/compensating_refund_leaves_the_settled_tab_at_zero
    """
    scenario = setup_compensated_check_for_ejection(price_cents=1000)
    slip, server, check = scenario["slip"], scenario["server"], scenario["check"]
    assert check["refunded_cents"] == 300, "the automatic compensation has already landed"
    assert check["status"] == "PARTIALLY_REFUNDED"

    disturbance = get_success_data(api_client.create_disturbance_event(
        {"order_slip_id": slip["id"], "kind": "NO_TALKING"}, server_headers(server)
    ))
    validate_success(api_client.approve_ejection(disturbance["id"], LEAD), 200)

    settled = read_check(check["id"], LEAD)
    assert_check_tab(settled)
    assert settled["refunded_cents"] == 1000, "the remainder was filled, not a second thirty percent"
    assert settled["status"] == "REFUNDED"
    assert settled["reason_code"] == "EJECTION_NO_TALKING"
    assert settled["original_cents"] - settled["refunded_cents"] == 0, (
        "the compensating action left the conserved tab quantity at exactly zero"
    )
    assert_check_tab_zero_balance_invariant(settled)


def test_a_further_refund_on_a_refunded_tab_is_refused(api):
    """PRD §3.8: "a refund whose amount would push the refunded total above the
    original is rejected with `ERR_REFUND_EXCEEDS_ORIGINAL` (HTTP 422), and a tab
    already at `REFUNDED` cannot be refunded again — the same error answers any
    further attempt."

    Design: Difficulty/compensating_invariant/compensating_refund_leaves_the_settled_tab_at_zero
    """
    scenario = setup_compensated_check_for_ejection(price_cents=1000)
    slip, server, check = scenario["slip"], scenario["server"], scenario["check"]
    disturbance = get_success_data(api_client.create_disturbance_event(
        {"order_slip_id": slip["id"], "kind": "NO_TALKING"}, server_headers(server)
    ))
    validate_success(api_client.approve_ejection(disturbance["id"], LEAD), 200)

    for amount in (1000, 300):
        refused = api_client.refund_check(check["id"], amount, LEAD)
        validate_error(refused, "ERR_REFUND_EXCEEDS_ORIGINAL")
        assert refused.status_code == 422

    final = read_check(check["id"], LEAD)
    assert final["refunded_cents"] == 1000, "no second refund was bookable at any amount"


def test_the_ejection_refund_leaves_the_tab_at_exactly_zero(api):
    """PRD §3.8: "Refunds arrive on three paths, and they all converge on a single
    invariant: when a refund completes, the tab's original amount minus its
    refunded amount must be exactly zero."

    Design: Difficulty/compensating_invariant/compensating_refund_leaves_the_settled_tab_at_zero
    """
    scenario = setup_compensated_check_for_ejection(price_cents=1000)
    slip, server, check = scenario["slip"], scenario["server"], scenario["check"]
    disturbance = get_success_data(api_client.create_disturbance_event(
        {"order_slip_id": slip["id"], "kind": "NO_TEXTING"}, server_headers(server)
    ))
    validate_success(api_client.approve_ejection(disturbance["id"], LEAD), 200)

    settled = read_check(check["id"], LEAD)
    assert settled["original_cents"] == 1000
    assert settled["refunded_cents"] == 1000
    assert settled["reason_code"] == "EJECTION_NO_TEXTING", (
        "a texting ejection carries its own reason code even though the money is identical"
    )
    assert settled["original_cents"] - settled["refunded_cents"] == 0


def test_approving_an_ejection_refunds_the_seat_and_advances_the_stage(api):
    """PRD §3.10: "Approving an ejection moves the disturbance record's stage to
    `EJECTION` and advances its `stage_version` by one".
    PRD §3.10: "The compensating refund described in §3.8 is issued against the
    seat's tab, raising the refunded amount to the original total and recording
    the reason that matches the offence".

    Design: Difficulty/transitive_cascade/ejection_cascade_event_to_slip_to_server_rotation
    """
    scenario = setup_delivered_entree_with_ejection(rating_grade="B", kind="NO_TEXTING",
                                                    price_cents=1200)
    server = scenario["server"]

    before = read_server(server["id"], LEAD)
    assert before["in_rotation"] is True, "the server was not penalised before the ejection"

    validate_success(api_client.approve_ejection(scenario["disturbance"]["id"], LEAD), 200)

    event = get_success_data(
        api_client.get_disturbance_event(scenario["disturbance"]["id"], LEAD)
    )
    assert event["stage"] == "EJECTION"

    check = _fetch_check(scenario["slip"]["id"])
    assert check["status"] == "REFUNDED"
    assert check["refunded_cents"] == 1200
    assert check["original_cents"] == 1200
    assert check["original_cents"] - check["refunded_cents"] == 0


def test_closing_the_ejection_assignment_penalises_the_server(api):
    """PRD §3.9: "it is multiplied again by a compensation factor of
    one-and-a-half whenever the assignment caused an approved ejection or a
    service compensation, and by one when it did not."
    PRD §3.9: "That base is then multiplied by an ejection factor of two whenever
    the assignment's showtime booked an ejection-linked refund".
    PRD §3.9: "Server.lifetime_points incremented" on close-out.

    Design: Difficulty/transitive_cascade/ejection_cascade_event_to_slip_to_server_rotation
    """
    scenario = setup_delivered_entree_with_ejection(rating_grade="B", kind="NO_TEXTING",
                                                    price_cents=1200)
    server, section = scenario["server"], scenario["section"]

    validate_success(api_client.approve_ejection(scenario["disturbance"]["id"], LEAD), 200)
    closed = validate_success(api_client.close_section_assignment(section["id"], LEAD), 200)
    assert_section_assignment(closed)
    assert closed["status"] == "COMPLETED"
    assert closed["assignment_points"] == 9, (
        "round_half_up(base 3 for a B grade times ejection 2.0 times refund 1.5)"
    )

    # PRD §3.9 computes the quality index "from the day's final state" only when
    # the shift is ended, and §3.7 escalates the roster on the cancellation path.
    # The close-out itself records the points; the shift end is what re-derives
    # the rolling figures the roster decision rides on.
    after = read_server(server["id"], LEAD)
    assert_server(after)
    assert after["lifetime_points"] == 9, (
        "the close-out incremented the owning server's lifetime total by the "
        "assignment's points"
    )
    assert after["shift_load_final"] == 1, "the closed assignment is the day's covered section"


def test_a_c_grade_ejection_night_scores_eighteen_points(api):
    """PRD §3.9: "an A scores one point, a B scores three, and a C scores six — a
    worse grade therefore costs more, which is the intended reading".
    PRD §3.9: "The product is rounded half up to a whole number of points, reported
    as the assignment's `assignment_points`."

    Design: Corner/calculations/section_assignment_points_multiply_grade_ejection_and_refund
    """
    scenario = setup_delivered_entree_with_ejection(rating_grade="C", kind="NO_TALKING",
                                                    price_cents=1000)
    server, section = scenario["server"], scenario["section"]

    validate_success(api_client.approve_ejection(scenario["disturbance"]["id"], LEAD), 200)
    closed = validate_success(api_client.close_section_assignment(section["id"], LEAD), 200)
    assert closed["assignment_points"] == 18, (
        "round_half_up(6 for a C grade times ejection 2.0 times refund 1.5)"
    )
    assert closed["status"] == "COMPLETED"
    assert read_server(server["id"], LEAD)["lifetime_points"] == 18


def _fetch_check(slip_id: str) -> dict:
    checks, _ = _list_checks(slip_id)
    assert checks, "the slip must have a check"
    return checks[0]


def _list_checks(slip_id: str):
    body = api_client.list_checks(LEAD, params={"id": slip_id}).json()
    return body["data"], body.get("meta", {})