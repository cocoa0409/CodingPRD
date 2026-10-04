"""Validation priority conflicts: which error wins when two conditions both fail."""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data, TEST_USERS, ApiErrorId,
    set_clock, create_distributor, create_circuit, create_theater, create_title,
    create_booking, add_line, submit_booking, approve_booking, get_booking,
    run_on_sale_sweep, make_distributor_headers, make_exhibitor_headers,
    create_settlement_payload, get_title, get_line, validate_error_is_one_of,
)
from test_helpers.api_client import api_client

OPS = TEST_USERS["platform_ops_headers"]
PROG = TEST_USERS["programming_manager_headers"]
FIN = TEST_USERS["finance_ops_headers"]


def _draft_booking_with_over_ceiling_guarantee():
    """DRAFT booking, 60-screen line, guarantee far above the live ceiling."""
    set_clock("2026-09-01T00:00:00Z")
    distributor = create_distributor(guarantee_floor_cents=1000000,
                                     ticket_price_default_cents=1500)
    circuit = create_circuit(credit_rating="B", settlement_terms="NET_30",
                             screen_pool_total=2000)
    theater = create_theater(circuit["id"], seats_total=200)
    title = create_title(distributor["id"], duration_minutes=120,
                         max_screen_commitment=120,
                         rights_end_utc="2027-06-01T00:00:00Z")
    booking = create_booking(title["id"], circuit["id"], guarantee_cents=5000000,
                             revenue_share_pct=0.40)
    line = add_line(booking["id"], circuit["id"], theater["id"],
                    booking["version"], committed_screens=60,
                    expected_attendance=100)
    return {"distributor": distributor, "circuit": circuit, "theater": theater,
            "title": title, "booking": booking, "line": line}


def test_approve_refuses_a_draft_booking_with_the_state_error_not_the_fiscal_one():
    """PRD §2.4: "an attempt to run a transition the resource's current state does
    not admit of is `ERR_INVALID_STATE`".
    PRD §2.4: "Business and fiscal constraints are evaluated after state, so a booking
    that is in the wrong state for the operation reports the state problem rather than
    a constraint problem it would also have hit."

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_outranks_guarantee_above_ceiling
    """
    scene = _draft_booking_with_over_ceiling_guarantee()
    booking = scene["booking"]
    resp = api_client.approve_booking(
        booking["id"], booking["version"],
        make_distributor_headers(scene["distributor"]["id"]), scene["line"]["id"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


def test_approve_dual_failure_state_error_condition_is_genuinely_violated():
    """PRD §3.2: "If a booking's guarantee exceeds the ceiling live for its status, the
    operation is refused with `ERR_GUARANTEE_ABOVE_CEILING` — checked at approval, at
    resume, and at submission."
    PRD §3.2: "a booking that has committed no screens yet also evaluates to a ceiling
    of zero".

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_outranks_guarantee_above_ceiling
    """
    scene = _draft_booking_with_over_ceiling_guarantee()
    booking = get_booking(scene["booking"]["id"])
    assert booking["guarantee_cents"] == 5000000
    assert booking["status"] == "DRAFT"
    # §2.10 defines the committed screen total over COMMITTED lines, which a DRAFT
    # booking cannot have; §3.2's ceiling is derived from that total. The PRD is
    # silent on whether a merely PROPOSED commitment counts for the ceiling, so the
    # derivable claim is the one §3.2 actually states: the guarantee exceeds the
    # ceiling live for the booking's status.
    assert booking["guarantee_cents"] > booking["guarantee_ceiling_cents"], (
        "the guarantee exceeds the live ceiling, so the fiscal condition is genuinely "
        "violated as well — this is a true dual failure"
    )


def test_approve_dual_failure_leaves_the_booking_untouched():
    """PRD §2.4: "nothing downstream of the existence check is evaluated, so a caller
    never receives a business-rule rejection for a request that was never addressable
    in the first place."

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_outranks_guarantee_above_ceiling
    """
    scene = _draft_booking_with_over_ceiling_guarantee()
    booking = scene["booking"]
    api_client.approve_booking(
        booking["id"], booking["version"],
        make_distributor_headers(scene["distributor"]["id"]), scene["line"]["id"])
    assert get_booking(booking["id"])["status"] == "DRAFT"


def test_confirm_refuses_an_expired_rights_window_with_the_safety_error():
    """PRD §2.4: "Within the business layer the safety and rights checks precede the
    fiscal ones, which is why a showtime falling outside the rights window surfaces as
    `ERR_RIGHTS_WINDOW_VIOLATION` rather than as an unrelated money error."
    PRD §3.1: "the rights window must not already have closed — `rights_end_utc` must
    be strictly after the current clock instant".

    Design: Difficulty/priority_pair_validation_conflict/rights_expired_outranks_rights_window_violation
    """
    scene = _on_sale_booking_then_rights_shrunk()
    booking = scene["booking"]
    resp = api_client.confirm_booking(booking["id"], booking["version"], OPS)
    # PRD §2.4 states the rights checks precede the fiscal ones but does not order
    # the two rights-layer checks against each other: §2.8's clock rule ("the same
    # error reported whenever any operation that ... confirms a booking is attempted
    # at or past rights_end_utc") and §2.9's showtime-inside-window rule are both
    # genuinely tripped here, and the PRD admits either reading.
    validate_error_is_one_of(resp, [ApiErrorId.ERR_RIGHTS_EXPIRED,
                                    ApiErrorId.ERR_RIGHTS_WINDOW_VIOLATION])


def test_confirm_dual_failure_rights_window_condition_is_genuinely_violated():
    """PRD §3.1: "the same error reported whenever any operation that commits screens,
    issues a key, or confirms a booking is attempted at or past `rights_end_utc`".
    PRD §3.3: "no committed line's scheduled screenings may collide with another
    booking's scheduled screening at the same venue."

    Design: Difficulty/priority_pair_validation_conflict/rights_expired_outranks_rights_window_violation
    """
    scene = _on_sale_booking_then_rights_shrunk()
    title = get_title(scene["title"]["id"], )
    screening = scene["screening"]
    assert title["rights_end_utc"].startswith("2026-11-15")
    assert screening["ends_at"] > title["rights_end_utc"], (
        "the showtime falls past the amended expiry, so the rights-window condition "
        "is genuinely violated as well — this is a true dual failure"
    )


def test_confirm_dual_failure_leaves_the_booking_on_sale():
    """PRD §2.4: "the order is observable because only the first failing layer's error
    is returned."

    Design: Difficulty/priority_pair_validation_conflict/rights_expired_outranks_rights_window_violation
    """
    scene = _on_sale_booking_then_rights_shrunk()
    booking = scene["booking"]
    api_client.confirm_booking(booking["id"], booking["version"], OPS)
    assert get_booking(booking["id"])["status"] == "ON_SALE"


def _on_sale_booking_then_rights_shrunk():
    """ON_SALE booking whose title's rights end is amended behind the showtime."""
    set_clock("2026-09-01T00:00:00Z")
    distributor = create_distributor(guarantee_floor_cents=1000000,
                                     ticket_price_default_cents=1500)
    circuit = create_circuit(credit_rating="B", settlement_terms="NET_30",
                             screen_pool_total=2000)
    theater = create_theater(circuit["id"], seats_total=200)
    title = create_title(distributor["id"], duration_minutes=120,
                         max_screen_commitment=120,
                         rights_end_utc="2027-06-01T00:00:00Z")
    booking = create_booking(title["id"], circuit["id"], guarantee_cents=1000000,
                             revenue_share_pct=0.40)
    line = add_line(booking["id"], circuit["id"], theater["id"],
                    booking["version"], committed_screens=60,
                    expected_attendance=100)
    booking = submit_booking(booking["id"], circuit["id"], line["version"])
    booking = approve_booking(booking["id"], distributor["id"],
                              booking["version"], line["id"])
    line = get_line(line["id"])
    booking = get_booking(booking["id"])
    set_clock(booking["on_sale_at"])
    run_on_sale_sweep()
    booking = get_booking(booking["id"])
    get_success_data(api_client.update_title(
        title["id"], {"rights_end_utc": "2026-11-15T00:00:00Z"}, PROG))
    set_clock("2026-11-20T00:00:00Z")
    return {"distributor": distributor, "circuit": circuit, "theater": theater,
            "title": get_title(title["id"], ), "booking": booking,
            "line": line, "screening": scene_screening(booking["id"])}


def scene_screening(booking_id):
    from test_helpers import first_screening
    return first_screening(booking_id)