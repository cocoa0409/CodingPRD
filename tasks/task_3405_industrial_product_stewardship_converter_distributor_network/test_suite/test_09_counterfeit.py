"""Counterfeit reports and their confirmation cascades (PRD §3.9, §3.3, §3.6)."""
from test_helpers import (
    ApiErrorId,
    advance_order,
    cancel_order,
    create_agreement,
    create_authorized_converter,
    create_counterfeit_report,
    create_distributor,
    disposition_payload,
    disposition_report,
    get_agreement,
    get_converter,
    get_order,
    grant_authorization,
    make_converter_headers,
    make_distributor_headers,
    order_payload,
    place_order,
    setup_active_formulation,
    TEST_USERS,
    validate_error,
    validate_success,
)

CM = TEST_USERS["channel_manager_headers"]
QA = TEST_USERS["quality_auditor_headers"]


def test_second_confirmed_report_revokes_suspended_converter(api):
    """PRD §3.9: "an `AUTHORIZED` converter moves to `SUSPENDED`; a converter
    already `SUSPENDED` — implicated by a second, distinct confirmed report —
    moves to `REVOKED`; a converter in `APPLIED`, `AUDIT_RECORDED`, or `REVOKED`
    does not transition." PRD §3.3: "The terminal state `REVOKED` is reached
    only by the system".

    Design: Corner/state_machines/second_confirmed_report_revokes_suspended_converter
    """
    ctx = setup_active_formulation()
    conv = create_authorized_converter()
    rep_a = create_counterfeit_report(
        ctx["formulation"]["id"], "L-A", channel_description="broker lot A",
        implicated_converter_id=conv["id"], reporter_role="QualityAuditor", reporter_id="qa-1")
    rep_b = create_counterfeit_report(
        ctx["formulation"]["id"], "L-B", channel_description="broker lot B",
        implicated_converter_id=conv["id"], reporter_role="QualityAuditor", reporter_id="qa-1")
    disposition_report(rep_a["id"], "CONFIRMED_COUNTERFEIT")
    assert get_converter(conv["id"])["status"] == "SUSPENDED"
    disposition_report(rep_b["id"], "CONFIRMED_COUNTERFEIT")
    assert get_converter(conv["id"])["status"] == "REVOKED"
    resp = api.reinstate_converter(conv["id"], CM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def _setup_converter_with_allocated_order(api):
    """AUTHORIZED converter with SLITTING/DE grant; CONVERTER_AUTHORIZED
    agreement; order qty 4 lot L-9 advanced to ALLOCATED; a distributor exists
    to act as the counterfeit reporter."""
    ctx = setup_active_formulation()
    conv = create_authorized_converter()
    grant_authorization(conv["id"], capability="SLITTING", territory_code="DE",
                        valid_from="2026-10-01T00:00:00Z", valid_to="2027-04-01T00:00:00Z")
    ag = create_agreement(ctx["formulation"]["id"], ctx["jurisdiction"]["id"],
                          converter_id=conv["id"], tier="CONVERTER_AUTHORIZED",
                          base_price_cents=10000)
    order = place_order(ag["id"], 4, converter_id=conv["id"],
                        requested_ship_date="2026-11-01T00:00:00Z",
                        intended_capability="SLITTING", lot_code="L-9")
    advance_order(order["id"], converter_id=conv["id"])
    dist = create_distributor()
    return ctx, conv, ag, order, dist


def test_counterfeit_confirmation_suspends_converter_and_flags_orders(api):
    """PRD §3.9: "If `implicated_converter_id` is set, the implicated
    converter's standing degrades one rung: an `AUTHORIZED` converter moves to
    `SUSPENDED`" and "Link one matches by lot: every order whose
    `formulation_id` and `lot_code` equal the report's, whose fulfillment is
    anything but `CANCELLED` — including already-`SHIPPED` orders — and whose
    compliance stands `CLEAR` is flagged with `flagged_by_report_id` set to this
    report."

    Design: Difficulty/transitive_cascade/counterfeit_confirm_cascades_converter_suspension_and_order_flags
    """
    ctx, conv, ag, order, dist = _setup_converter_with_allocated_order(api)
    rep = create_counterfeit_report(
        ctx["formulation"]["id"], "L-9", channel_description="auction-site die-cut reels",
        implicated_converter_id=conv["id"], reporter_role="Distributor",
        reporter_id=dist["id"])
    disposition = disposition_report(rep["id"], "CONFIRMED_COUNTERFEIT")
    assert disposition["status"] == "CONFIRMED_COUNTERFEIT"
    assert get_converter(conv["id"])["status"] == "SUSPENDED"
    after = get_order(order["id"])
    assert after["compliance_status"] == "FLAGGED"
    assert after["flagged_by_report_id"] == rep["id"]
    assert after["fulfillment_status"] == "ALLOCATED", "the compliance axis moves alone"


def test_follow_on_converter_order_rejected_after_suspension(api):
    """PRD §3.6: "A converter buyer must currently stand `AUTHORIZED`, else
    `ERR_CONVERTER_NOT_AUTHORIZED` (409)."

    Design: Difficulty/transitive_cascade/counterfeit_confirm_cascades_converter_suspension_and_order_flags
    """
    ctx, conv, ag, order, dist = _setup_converter_with_allocated_order(api)
    rep = create_counterfeit_report(
        ctx["formulation"]["id"], "L-9", channel_description="auction-site die-cut reels",
        implicated_converter_id=conv["id"], reporter_role="Distributor",
        reporter_id=dist["id"])
    disposition_report(rep["id"], "CONFIRMED_COUNTERFEIT")
    assert get_converter(conv["id"])["status"] == "SUSPENDED"
    current = get_agreement(ag["id"])
    follow = api.create_order(
        order_payload(ag["id"], quantity=1, requested_ship_date="2026-11-03T00:00:00Z",
                      expected_price_agreement_version=current["version"],
                      converter_id=conv["id"], intended_capability="SLITTING"),
        make_converter_headers(conv["id"]),
    )
    validate_error(follow, ApiErrorId.ERR_CONVERTER_NOT_AUTHORIZED)


def _setup_flagged_allocated_order(api):
    """Distributor STANDARD agreement; order qty 10 lot L-P ALLOCATED, then
    FLAGGED by a confirmed counterfeit report on (formulation, L-P)."""
    ctx = setup_active_formulation()
    dist = create_distributor()
    ag = create_agreement(ctx["formulation"]["id"], ctx["jurisdiction"]["id"],
                          distributor_id=dist["id"], tier="STANDARD", base_price_cents=10000)
    order = place_order(ag["id"], 10, distributor_id=dist["id"],
                        requested_ship_date="2026-11-01T00:00:00Z", lot_code="L-P")
    advance_order(order["id"], distributor_id=dist["id"])
    rep = create_counterfeit_report(
        ctx["formulation"]["id"], "L-P", channel_description="online marketplace reel",
        reporter_role="Distributor", reporter_id=dist["id"])
    disposition_report(rep["id"], "CONFIRMED_COUNTERFEIT")
    return ctx, dist, order, rep


def test_flagged_order_advance_blocked_fulfillment_unchanged(api):
    """PRD §3.6: "From `ALLOCATED`, an advance ships: compliance must again be
    `CLEAR` under the same error" — "the order's compliance must be `CLEAR`,
    else `ERR_ORDER_COMPLIANCE_BLOCKED` (409)". "Compliance runs on a **parallel
    dimension** and never mixes with fulfillment."

    Design: Difficulty/non_linear_state_machine/order_fulfillment_and_compliance_axes_move_independently
    """
    ctx, dist, order, rep = _setup_flagged_allocated_order(api)
    flagged = get_order(order["id"])
    assert flagged["fulfillment_status"] == "ALLOCATED"
    assert flagged["compliance_status"] == "FLAGGED"
    assert flagged["flagged_by_report_id"] == rep["id"]
    resp = api.advance_order(order["id"], make_distributor_headers(dist["id"]))
    validate_error(resp, ApiErrorId.ERR_ORDER_COMPLIANCE_BLOCKED)
    assert get_order(order["id"])["fulfillment_status"] == "ALLOCATED"


def test_flagged_order_cancel_moves_only_fulfillment_axis(api):
    """PRD §3.6: "Cancellation is open from either non-terminal fulfillment
    state, again only to the owning partner." and "Compliance runs on a
    **parallel dimension** and never mixes with fulfillment."

    Design: Difficulty/non_linear_state_machine/order_fulfillment_and_compliance_axes_move_independently
    """
    ctx, dist, order, rep = _setup_flagged_allocated_order(api)
    cancelled = cancel_order(order["id"], distributor_id=dist["id"])
    assert cancelled["fulfillment_status"] == "CANCELLED"
    after = get_order(order["id"])
    assert after["compliance_status"] == "FLAGGED", "cancel does not touch the compliance axis"
