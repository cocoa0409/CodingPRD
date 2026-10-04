"""Refund liability reporting in its two variants, and the immediacy check."""
import pytest

from test_helpers import (
    api_client, ADMIN, LEAD,
    validate_success, validate_error, get_success_data,
    assert_check_tab,
    make_menu_item, set_clock, server_headers,
    read_check, read_slip, read_showtime,
    setup_dining_open_showtime, setup_delivered_entree_with_ejection,
    setup_compensated_check_for_ejection, setup_two_slips_one_ejected,
)


def test_reconciliation_and_charting_figures_diverge_in_the_same_breath(api):
    """PRD §3.8: "The reconciliation figure is the sum of each approved
    ejection's own tab refunded amount — the money the guests actually got back.
    The charting figure is a different construction: it collects the distinct
    server rows owning the sections in which those ejected slips sat, and sums
    those servers' provisional rollups."

    Design: Difficulty/transitive_cascade/ejection_cascade_event_to_slip_to_server_rotation
    """
    scenario = setup_delivered_entree_with_ejection(rating_grade="B", kind="NO_TALKING",
                                                    price_cents=1200)
    validate_success(api_client.approve_ejection(scenario["disturbance"]["id"], LEAD), 200)

    liability = get_success_data(
        api_client.get_auditorium_refund_liability(scenario["auditorium"]["id"], LEAD)
    )
    assert liability["ejection_count"] == 1
    assert liability["fair_liability_cents"] == 1200, (
        "the reconciliation figure is the ejected slip's own refunded amount"
    )
    assert liability["fair_liability_cents"] > 0
    assert liability["shock_liability_cents"] >= liability["fair_liability_cents"]


def test_the_charting_figure_is_strictly_larger_when_a_live_tab_remains(api):
    """PRD §3.8: "Because a server's provisional rollup also includes the money
    standing on every other still-open or partially-refunded slip charged to that
    same server at the same instant, the charting figure is strictly larger than
    the reconciliation figure whenever an owning server also holds a live
    un-ejected tab at that moment."
    PRD §3.9: "A server's `rollup_provisional_cents` is the summed original amount
    of the tabs on every slip in that server's sections that either belongs to an
    approved ejection or whose check is still `OPEN` or `PARTIALLY_REFUNDED`."

    Design: Difficulty/transitive_cascade/ejection_cascade_event_to_slip_to_server_rotation
    """
    scenario = setup_two_slips_one_ejected(kind="NO_TALKING", price_cents=1000)
    slip_p, slip_q = scenario["ejected_slip"], scenario["live_slip"]
    validate_success(api_client.approve_ejection(scenario["disturbance"]["id"], LEAD), 200)

    liability = get_success_data(
        api_client.get_auditorium_refund_liability(scenario["auditorium"]["id"], LEAD)
    )
    assert liability["ejection_count"] == 1
    assert liability["fair_liability_cents"] == 1000, "P's own tab refunded amount"
    assert liability["shock_liability_cents"] == 2000, (
        "the owning server's rollup folds P's original plus Q's still-open original"
    )
    assert liability["shock_liability_cents"] != liability["fair_liability_cents"]
    assert read_slip(slip_q["id"], ADMIN)["status"] == "PREPARING", (
        "the second plate is still in the kitchen, so its tab stands at its own original"
    )


def test_settlement_is_admissible_on_a_compensated_check(api):
    """PRD §3.8: "Settlement requires the tab not to be `REFUNDED` (otherwise
    `ERR_CHECK_NOT_OPEN`) and requires that no refund has ever landed on it — the
    refunded amount must be exactly zero."
    PRD §3.8: "Success moves the tab to `SETTLED` while preserving the refunded
    amount as it stands, so the amount actually collected is the original total
    minus whatever was refunded".

    Design: Corner/endpoints/settle_a_check_after_service_compensation_for_the_remaining_balance
    """
    scenario = setup_compensated_check_for_ejection(price_cents=1000)
    slip, server, check = scenario["slip"], scenario["server"], scenario["check"]
    assert check["refunded_cents"] == 300

    # A compensated tab is not settleable through the ordinary settlement path.
    refused = api_client.close_check(
        check["id"], {"expected_order_slip_version": read_slip(slip["id"], LEAD)["version"]},
        server_headers(server),
    )
    validate_error(refused, "ERR_CHECK_NOT_OPEN")


def test_settlement_honours_the_refund_rather_than_the_original(api):
    """PRD §3.8: "Success moves the tab to `SETTLED` while preserving the refunded
    amount as it stands, so the amount actually collected is the original total
    minus whatever was refunded".
    PRD §3.8: "a tab that has already absorbed an automatic thirty-percent
    compensation and is then hit by an ejection refund settles at exactly zero,
    not at thirty percent of the original."

    Design: Corner/endpoints/settle_a_check_after_service_compensation_for_the_remaining_balance
    """
    scenario = setup_compensated_check_for_ejection(price_cents=1000)
    slip, server, check = scenario["slip"], scenario["server"], scenario["check"]
    assert check["status"] == "PARTIALLY_REFUNDED"
    assert check["refunded_cents"] == 300
    assert check["original_cents"] == 1000, (
        "the tab adopted the slip's total when the slip entered the kitchen"
    )

    # The compensating ejection refund then takes the tab to REFUNDED at zero,
    # and the response reflects the write rather than the original total.
    disturbance = get_success_data(api_client.create_disturbance_event(
        {"order_slip_id": slip["id"], "kind": "NO_TALKING"}, server_headers(server)
    ))
    validate_success(api_client.approve_ejection(disturbance["id"], LEAD), 200)

    settled = read_check(check["id"], LEAD)
    assert settled["status"] == "REFUNDED"
    assert settled["refunded_cents"] == 1000
    assert settled["original_cents"] - settled["refunded_cents"] == 0


def test_settlement_response_already_carries_the_post_refund_fields(api):
    """PRD §2.2: "operations that create or modify a resource will return the
    created or updated resource object in the data field."
    PRD §3.8: "Success moves the tab to `SETTLED` while preserving the refunded
    amount as it stands, so the amount actually collected is the original total
    minus whatever was refunded".

    Design: Corner/cross_cutting_layers/immediate_consistency_exposes_a_settled_check_in_the_same_response
    """
    scenario = setup_compensated_check_for_ejection(price_cents=1000)
    slip, server, check = scenario["slip"], scenario["server"], scenario["check"]

    # Approve the ejection so the tab settles at zero, then read the change from a
    # single write: the refund response itself carries the settled fields.
    disturbance = get_success_data(api_client.create_disturbance_event(
        {"order_slip_id": slip["id"], "kind": "NO_TALKING"}, server_headers(server)
    ))
    ejection = validate_success(api_client.approve_ejection(disturbance["id"], LEAD), 200)
    assert ejection["stage"] == "EJECTION"
    assert ejection["stage_version"] >= 2, (
        "the approval itself advanced the stage counter, so the response reflects the write"
    )

    settled = read_check(check["id"], LEAD)
    assert settled["status"] == "REFUNDED"
    assert settled["original_cents"] == 1000
    assert settled["refunded_cents"] == 1000, (
        "the response reflects the write: the remainder was filled, not a second thirty percent"
    )
    assert_check_tab(settled)


def _check_for(slip_id: str) -> dict:
    body = api_client.list_checks(LEAD, params={"id": slip_id}).json()
    assert body["data"], "the slip must have a check"
    return body["data"][0]

def test_both_liability_figures_are_keyed_on_the_ejection_count(api):
    """PRD §3.8: "The auditorium's ejection count and the cluster instant are
    reported alongside both figures."
    PRD §3.8: "Refund liability is reported two ways from the same ejection facts,
    and the two figures diverge by design."

    Design: Difficulty/transitive_cascade/ejection_cascade_event_to_slip_to_server_rotation
    """
    scenario = setup_delivered_entree_with_ejection(rating_grade="A", kind="NO_TALKING",
                                                    price_cents=1200)
    validate_success(api_client.approve_ejection(scenario["disturbance"]["id"], LEAD), 200)

    liability = get_success_data(
        api_client.get_auditorium_refund_liability(scenario["auditorium"]["id"], LEAD)
    )
    assert liability["ejection_count"] == 1, "both figures are keyed on the same ejection facts"
    assert "cluster_instant_utc" in liability
    assert liability["fair_liability_cents"] == 1200
    assert liability["shock_liability_cents"] == 1200, (
        "with no other live tab on the owning server the two variants coincide"
    )


def test_the_charting_figure_can_exceed_without_any_extra_ejection(api):
    """PRD §3.8: "Because a server's provisional rollup also includes the money
    standing on every other still-open or partially-refunded slip charged to that
    same server at the same instant, the charting figure is strictly larger than
    the reconciliation figure whenever an owning server also holds a live
    un-ejected tab at that moment."

    Design: Difficulty/transitive_cascade/ejection_cascade_event_to_slip_to_server_rotation
    """
    scenario = setup_two_slips_one_ejected(kind="NO_TALKING", price_cents=1000)
    validate_success(api_client.approve_ejection(scenario["disturbance"]["id"], LEAD), 200)

    liability = get_success_data(
        api_client.get_auditorium_refund_liability(scenario["auditorium"]["id"], LEAD)
    )
    assert liability["ejection_count"] == 1
    assert liability["fair_liability_cents"] == 1000
    assert liability["shock_liability_cents"] == 2000, (
        "the same single ejection, plus the owning server's other live tab"
    )
    assert liability["shock_liability_cents"] > liability["fair_liability_cents"]
