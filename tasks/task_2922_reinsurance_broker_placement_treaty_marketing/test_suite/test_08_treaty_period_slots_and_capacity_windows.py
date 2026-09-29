"""Treaty-period slots and the buffered capacity aggregation window (PRD §3.1, §3.5).

Queue A — rule ``resource_temporal_overlap``: two different resources are guarded
by two different interval semantics. The ``(cedent_id, line_of_business)`` treaty
slot is HALF-OPEN and unbuffered, so an adjacent renewal is legal while a
mid-term program is refused; a market's ``capacity_limit_minor`` is guarded by an
aggregation window that is CLOSED at both ends and widened thirty days each way,
so a line from a program incepting exactly on the lower edge still consumes it.
"""
from test_helpers import (
    ApiErrorId,
    CLOCK,
    TEST_USERS,
    api_client,
    assert_capacity_invariants,
    assert_instant_equals,
    assert_money_equals,
    assert_pct_equals,
    assert_status,
    create_cedent,
    create_exposure_submission,
    create_program,
    create_program_payload,
    create_reinsurer,
    create_xol_layer,
    firm_order,
    go_to_market,
    list_rows,
    quote_on,
    read_layer,
    read_program,
    read_reinsurer,
    read_signing_line,
    set_clock,
    sign_off_exposure,
    submit_to_market,
    validate_error,
    validate_success,
)

LEAD_HEADERS = TEST_USERS["placement_lead_headers"]

# ==========================================================================
# Instance 1 — the (cedent_id, line_of_business) treaty slot, HALF-OPEN and
# unbuffered. The incumbent PROPERTY treaty covers
# [2026-01-01T00:00:00.000Z, 2027-01-01T00:00:00.000Z).
# ==========================================================================
INCUMBENT_PROGRAM = {
    "program_name": "Northwind Property 2026",
    "line_of_business": "PROPERTY",
    "underwriting_year": 2026,
    "inception_date": "2026-01-01T00:00:00.000Z",
    "expiry_date": "2027-01-01T00:00:00.000Z",
    "estimated_premium_income_minor": 2_000_000_000,
    "brokerage_pct": 2.5000,
}
# Same period, different line of business — a different slot entirely.
OTHER_LOB_PROGRAM = {
    "program_name": "Northwind Marine 2026",
    "line_of_business": "MARINE",
    "underwriting_year": 2026,
    "inception_date": "2026-01-01T00:00:00.000Z",
    "expiry_date": "2027-01-01T00:00:00.000Z",
    "estimated_premium_income_minor": 500_000_000,
    "brokerage_pct": 2.5000,
}
# Incepts at exactly the instant the incumbent expires — the excluded end.
ADJACENT_PROGRAM = {
    "program_name": "Northwind Property 2027",
    "line_of_business": "PROPERTY",
    "underwriting_year": 2027,
    "inception_date": "2027-01-01T00:00:00.000Z",
    "expiry_date": "2028-01-01T00:00:00.000Z",
    "estimated_premium_income_minor": 2_100_000_000,
    "brokerage_pct": 2.5000,
}
# Incepts five months inside the incumbent period — a genuine overlap.
MID_TERM_PROGRAM = {
    "program_name": "Northwind Property 2026 Mid-Term",
    "line_of_business": "PROPERTY",
    "underwriting_year": 2026,
    "inception_date": "2026-06-01T00:00:00.000Z",
    "expiry_date": "2027-06-01T00:00:00.000Z",
    "estimated_premium_income_minor": 900_000_000,
    "brokerage_pct": 2.5000,
}


def _occupied_treaty_slot():
    """One cedent holding an incumbent PROPERTY treaty and a twin MARINE treaty.

    Both are left in ``DRAFT`` — placement status is irrelevant to the overlap
    check as long as it is not ``WITHDRAWN``.
    """
    set_clock(CLOCK["PLACEMENT_START"])
    cedent = create_cedent()
    incumbent = create_program(cedent["id"], **INCUMBENT_PROGRAM)
    other_lob = create_program(cedent["id"], **OTHER_LOB_PROGRAM)
    return {"cedent": cedent, "incumbent": incumbent, "other_lob": other_lob}


def _create_program_response(cedent_id: str, overrides):
    """Raw POST /programs so the HTTP status and the error id are both assertable."""
    return api_client.create_program(
        create_program_payload(cedent_id, **overrides), LEAD_HEADERS
    )


def test_a_renewal_incepting_at_the_incumbents_expiry_instant_opens_a_new_file():
    """2027-01-01T00:00:00.000Z is the excluded end of the incumbent period, so it is free.

    PRD: "Because the period is half-open, a program incepting at exactly the
    instant another expires does not overlap it — but if the new period does
    overlap the period of any other program of the same `cedent_id` and the same
    `line_of_business` whose `placement_status` is anything other than
    `WITHDRAWN`, the creation is refused with `ERR_OVERLAPPING_TREATY_PERIOD`."

    Design: Difficulty/resource_temporal_overlap/adjacent_treaty_periods_coexist_but_an_overlapping_one_is_refused
    """
    ctx = _occupied_treaty_slot()

    response = _create_program_response(ctx["cedent"]["id"], ADJACENT_PROGRAM)

    adjacent = validate_success(response, 201)
    assert_instant_equals(
        adjacent["inception_date"], "2027-01-01T00:00:00.000Z", "adjacent inception_date"
    )
    assert_instant_equals(
        adjacent["expiry_date"], "2028-01-01T00:00:00.000Z", "adjacent expiry_date"
    )
    assert_status(adjacent, "placement_status", "DRAFT")
    assert_status(adjacent, "line_of_business", "PROPERTY")

    incumbent = read_program(ctx["incumbent"]["id"])
    assert_instant_equals(
        incumbent["expiry_date"], "2027-01-01T00:00:00.000Z", "incumbent expiry_date"
    )
    assert_status(read_program(adjacent["id"]), "placement_status", "DRAFT")


def test_a_mid_term_program_inside_the_incumbent_period_is_refused():
    """A PROPERTY treaty incepting 2026-06-01 collides with the incumbent slot.

    PRD: "Because the period is half-open, a program incepting at exactly the
    instant another expires does not overlap it — but if the new period does
    overlap the period of any other program of the same `cedent_id` and the same
    `line_of_business` whose `placement_status` is anything other than
    `WITHDRAWN`, the creation is refused with `ERR_OVERLAPPING_TREATY_PERIOD`."

    Design: Difficulty/resource_temporal_overlap/adjacent_treaty_periods_coexist_but_an_overlapping_one_is_refused
    """
    ctx = _occupied_treaty_slot()
    validate_success(_create_program_response(ctx["cedent"]["id"], ADJACENT_PROGRAM), 201)

    response = _create_program_response(ctx["cedent"]["id"], MID_TERM_PROGRAM)

    validate_error(response, ApiErrorId.ERR_OVERLAPPING_TREATY_PERIOD.value)


def test_the_treaty_slot_is_keyed_on_line_of_business_as_well_as_cedent():
    """A MARINE treaty over the identical period never conflicts with the PROPERTY one.

    PRD: "Because the period is half-open, a program incepting at exactly the
    instant another expires does not overlap it — but if the new period does
    overlap the period of any other program of the same `cedent_id` and the same
    `line_of_business` whose `placement_status` is anything other than
    `WITHDRAWN`, the creation is refused with `ERR_OVERLAPPING_TREATY_PERIOD`."

    Design: Difficulty/resource_temporal_overlap/adjacent_treaty_periods_coexist_but_an_overlapping_one_is_refused
    """
    ctx = _occupied_treaty_slot()
    adjacent = validate_success(
        _create_program_response(ctx["cedent"]["id"], ADJACENT_PROGRAM), 201
    )
    validate_error(
        _create_program_response(ctx["cedent"]["id"], MID_TERM_PROGRAM),
        ApiErrorId.ERR_OVERLAPPING_TREATY_PERIOD.value,
    )

    rows = list_rows(api_client.list_cedent_programs(ctx["cedent"]["id"], LEAD_HEADERS))

    property_rows = [row for row in rows if row["line_of_business"] == "PROPERTY"]
    assert len(property_rows) == 2, (
        "the PROPERTY slot holds exactly the incumbent and the adjacent renewal, "
        f"got {[row['program_name'] for row in property_rows]}"
    )
    assert {row["id"] for row in property_rows} == {
        ctx["incumbent"]["id"],
        adjacent["id"],
    }, "the refused mid-term program must not have been persisted"

    other_lob = read_program(ctx["other_lob"]["id"])
    assert_status(other_lob, "line_of_business", "MARINE")
    assert_instant_equals(
        other_lob["inception_date"], "2026-01-01T00:00:00.000Z", "MARINE inception_date"
    )
    assert_instant_equals(
        other_lob["expiry_date"], "2027-01-01T00:00:00.000Z", "MARINE expiry_date"
    )
    assert_status(other_lob, "placement_status", "DRAFT")


# ==========================================================================
# Instance 2 — India Re's capacity_limit_minor, guarded by an aggregation
# window CLOSED at both ends and widened by thirty days each way.
#
# Program P covers [2026-02-01T00:00:00.000Z, 2027-02-01T00:00:00.000Z), so
# window(P) is [2026-01-02T00:00:00.000Z, 2027-03-03T00:00:00.000Z]. Program Q
# incepts on 2026-01-02T00:00:00.000Z — exactly the inclusive lower edge — so
# its 200,000,000 line still consumes capacity, and P's 300,000,000 line lands
# the windowed total on exactly the 500,000,000 limit.
# ==========================================================================
INDIA_RE_SPEC = {
    "name": "India Re",
    "security_rating": "A",
    "capacity_limit_minor": 500_000_000,
    "max_line_pct": 100.0000,
    "lead_authorised": True,
}

WINDOW_EDGE_PROGRAM_Q = {
    "program_name": "Northwind Marine 2026",
    "line_of_business": "MARINE",
    "underwriting_year": 2026,
    "inception_date": "2026-01-02T00:00:00.000Z",
    "expiry_date": "2027-01-02T00:00:00.000Z",
    "estimated_premium_income_minor": 400_000_000,
    "brokerage_pct": 2.5000,
}
WINDOW_EDGE_LAYER_Q = {
    "layer_label": "MAR XOL 200M xs 300M",
    "attachment_minor": 300_000_000,
    "limit_minor": 200_000_000,
    "base_rate_pct": 6.0000,
    "subject_premium_base_minor": 200_000_000,
    "expected_loss_cost_minor": 8_000_000,
    "reinstatements_total": 0,
    "sublimit_minor": 0,
}

TARGET_PROGRAM_P = {
    "program_name": "Northwind Property 2026",
    "line_of_business": "PROPERTY",
    "underwriting_year": 2026,
    "inception_date": "2026-02-01T00:00:00.000Z",
    "expiry_date": "2027-02-01T00:00:00.000Z",
    "estimated_premium_income_minor": 900_000_000,
    "brokerage_pct": 2.5000,
}
TARGET_LAYER_P = {
    "layer_label": "PROP XOL 300M xs 700M",
    "attachment_minor": 700_000_000,
    "limit_minor": 300_000_000,
    "base_rate_pct": 6.0000,
    "subject_premium_base_minor": 300_000_000,
    "expected_loss_cost_minor": 12_000_000,
    "reinstatements_total": 0,
    "sublimit_minor": 0,
}


def _market_one_layer_to_india(
    cedent_id: str,
    india_id: str,
    program_overrides,
    layer_overrides,
    package_label: str,
    response_deadline: str,
    quote_expires_at: str,
):
    """program -> package -> XOL layer -> sign-off -> market -> submission -> quote."""
    program = create_program(cedent_id, **program_overrides)
    submission = create_exposure_submission(
        program["id"], cedent_id, package_label=package_label
    )
    layer = create_xol_layer(program["id"], **layer_overrides)
    sign_off_exposure(submission["id"])
    go_to_market(program["id"])
    market_submission = submit_to_market(
        layer["id"], india_id, response_deadline=response_deadline
    )
    quote = quote_on(
        market_submission["id"],
        india_id,
        offered_line_pct=100.0000,
        quoted_rate_pct=6.0000,
        ceding_commission_pct=0.0000,
        reinstatements_offered=0,
        sublimit_minor=0,
        expires_at=quote_expires_at,
        is_lead=True,
    )
    return {"program": program, "layer": layer, "quote": quote}


def _india_re_on_the_window_edge():
    """India Re holds a 200,000,000 line on window-edge program Q; program P is quoted.

    Q incepts on 2026-01-02, exactly thirty days before P's 2026-02-01 inception,
    and P's own 300,000,000 line has been quoted but not yet firm-ordered.
    """
    set_clock(CLOCK["PLACEMENT_START"])
    cedent = create_cedent()
    india = create_reinsurer(**INDIA_RE_SPEC)

    edge = _market_one_layer_to_india(
        cedent["id"],
        india["id"],
        WINDOW_EDGE_PROGRAM_Q,
        WINDOW_EDGE_LAYER_Q,
        "NW-MAR-2026-EDP",
        "2026-02-01T00:00:00.000Z",
        "2026-02-15T00:00:00.000Z",
    )
    edge_line = firm_order(edge["quote"]["id"], 100.0000, layer_id=edge["layer"]["id"])

    target = _market_one_layer_to_india(
        cedent["id"],
        india["id"],
        TARGET_PROGRAM_P,
        TARGET_LAYER_P,
        "NW-PROP-2026-EDP",
        "2026-02-05T00:00:00.000Z",
        "2026-02-20T00:00:00.000Z",
    )
    return {
        "cedent": cedent,
        "india": india,
        "edge_program": edge["program"],
        "edge_layer": edge["layer"],
        "edge_line": edge_line,
        "target_program": target["program"],
        "target_layer": target["layer"],
        "target_quote": target["quote"],
        "india_before": read_reinsurer(india["id"]),
    }


def test_a_line_from_a_program_incepting_on_the_windows_lower_edge_consumes_capacity():
    """India Re's 200,000,000 window-edge line lets the next 300,000,000 land on exactly 500,000,000.

    PRD: "The aggregation window around the target program runs from thirty days
    before its `inception_date` to thirty days after its `expiry_date`, and it is
    **closed at both ends**: a live line counts if and only if its own program's
    `inception_date` lies inside that window inclusive of both endpoints, so a
    program incepting exactly thirty days before the target program incepts is
    inside the window and does consume capacity."

    Design: Difficulty/resource_temporal_overlap/buffered_capacity_window_counts_a_line_from_a_program_incepting_exactly_on_the_boundary
    """
    ctx = _india_re_on_the_window_edge()
    assert_money_equals(
        ctx["india_before"]["committed_capacity_minor"],
        200_000_000,
        "committed_capacity_minor before the target firm order",
    )
    assert_money_equals(
        ctx["india_before"]["available_capacity_minor"],
        300_000_000,
        "available_capacity_minor before the target firm order",
    )

    target_line = firm_order(
        ctx["target_quote"]["id"], 100.0000, layer_id=ctx["target_layer"]["id"]
    )

    assert_money_equals(
        target_line["committed_capacity_minor"],
        300_000_000,
        "target signing line committed_capacity_minor",
    )
    assert_pct_equals(target_line["written_line_pct"], 100.0000, "written_line_pct")
    assert_status(target_line, "status", "PROVISIONAL")
    assert target_line["signed_line_pct"] is None, (
        "a PROVISIONAL line has no signed_line_pct until sign-down or binding"
    )
    assert_money_equals(
        read_reinsurer(ctx["india"]["id"])["committed_capacity_minor"],
        500_000_000,
        "committed_capacity_minor after the target firm order",
    )


def test_the_market_register_reports_the_full_five_hundred_million_as_committed():
    """Both lines together exhaust India Re: committed 500,000,000 and available 0.

    PRD: "A market's `committed_capacity_minor` is that sum and its
    `available_capacity_minor` is its `capacity_limit_minor` less that sum; both
    are refreshed whenever any of its lines is created, signed down or released."

    Design: Difficulty/resource_temporal_overlap/buffered_capacity_window_counts_a_line_from_a_program_incepting_exactly_on_the_boundary
    """
    ctx = _india_re_on_the_window_edge()

    firm_order(ctx["target_quote"]["id"], 100.0000, layer_id=ctx["target_layer"]["id"])

    india = read_reinsurer(ctx["india"]["id"])
    assert_money_equals(
        india["capacity_limit_minor"], 500_000_000, "capacity_limit_minor"
    )
    assert_money_equals(
        india["committed_capacity_minor"], 500_000_000, "committed_capacity_minor"
    )
    assert_money_equals(
        india["available_capacity_minor"], 0, "available_capacity_minor"
    )
    assert_capacity_invariants(india)

    edge_line = read_signing_line(ctx["edge_line"]["id"])
    assert_status(edge_line, "status", "PROVISIONAL")
    assert_money_equals(
        edge_line["committed_capacity_minor"],
        200_000_000,
        "window-edge line committed_capacity_minor",
    )
    assert_pct_equals(
        edge_line["effective_line_pct"], 100.0000, "window-edge line effective_line_pct"
    )


def test_filling_the_target_layer_promotes_it_and_its_program():
    """The 100.0000 line takes P's layer to FULLY_PLACED and P itself to FIRM_ORDER.

    PRD: "The third hop looks up at the program: when every layer of the program
    whose status is not `LAPSED` is either `FULLY_PLACED` or `OVERSUBSCRIBED`,
    the program's `placement_status` advances from `IN_MARKET` to `FIRM_ORDER`
    and its `version` increments."

    Design: Difficulty/resource_temporal_overlap/buffered_capacity_window_counts_a_line_from_a_program_incepting_exactly_on_the_boundary
    """
    ctx = _india_re_on_the_window_edge()
    assert_status(read_program(ctx["target_program"]["id"]), "placement_status", "IN_MARKET")

    firm_order(ctx["target_quote"]["id"], 100.0000, layer_id=ctx["target_layer"]["id"])

    target_layer = read_layer(ctx["target_layer"]["id"])
    assert_pct_equals(
        target_layer["written_line_total_pct"], 100.0000, "target written_line_total_pct"
    )
    assert_status(target_layer, "status", "FULLY_PLACED")
    assert_money_equals(target_layer["limit_minor"], 300_000_000, "target limit_minor")
    assert_status(
        read_program(ctx["target_program"]["id"]), "placement_status", "FIRM_ORDER"
    )

    edge_layer = read_layer(ctx["edge_layer"]["id"])
    assert_status(edge_layer, "status", "FULLY_PLACED")
    assert_money_equals(edge_layer["limit_minor"], 200_000_000, "window-edge limit_minor")
    assert_status(
        read_program(ctx["edge_program"]["id"]), "placement_status", "FIRM_ORDER"
    )
