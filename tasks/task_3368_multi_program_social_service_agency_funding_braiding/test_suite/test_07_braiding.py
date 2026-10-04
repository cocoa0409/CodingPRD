"""Braiding the cost of one delivery across the grants that can bear it."""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data, set_clock,
    create_client, create_funder, create_program, create_grant, open_assessment,
    open_screen, verify_screen, submit_assessment, route_assessment, determine_screen,
    walk_screen_to_eligible, activate_enrollment, authorize_units, record_delivery,
    document_delivery, delivery_lines, setup_landscape, setup_two_grant_braiding,
    ApiErrorId, PROGRAM, FINANCE,
)


def test_braided_lines_carry_contiguous_ranks_and_the_pinned_basis():
    """PRD §3.7: "under the `RANKED_PRIORITY` basis, grants are drawn in
    ascending `allocation_rank` with ties broken by ascending creation time".
    PRD §3.7: "The resulting line records the take as `allocated_amount_cents`,
    an administrative share as `admin_amount_cents` computed by multiplying the
    take by that grant's administrative rate and rounding half up to whole
    cents, its position as `allocation_rank`, the basis that produced it as
    `allocation_basis`".

    Design: Corner/endpoints/braided_lines_carry_contiguous_ranks_and_the_pinned_basis
    """
    set_clock("2026-09-02T00:00:00Z")
    ctx = setup_two_grant_braiding(
        grant_a_overrides={"grant_code": "G-1", "total_award_cents": 40000,
                           "admin_rate_pct": 0.10, "allocation_rank": 1},
        grant_b_overrides={"grant_code": "G-2", "total_award_cents": 200000,
                           "admin_rate_pct": 0.20, "allocation_rank": 2},
        units_delivered=12, unit_rate_cents=5000, document=True,
    )
    lines = delivery_lines(ctx["delivery"]["id"])
    assert len(lines) == 2
    assert lines[0]["allocation_rank"] == 1 and lines[1]["allocation_rank"] == 2
    assert lines[0]["grant_id"] == ctx["grant_a"]["id"]
    assert lines[0]["allocated_amount_cents"] == 40000
    assert lines[0]["admin_amount_cents"] == 4000
    assert lines[1]["grant_id"] == ctx["grant_b"]["id"]
    assert lines[1]["allocated_amount_cents"] == 20000
    assert lines[1]["admin_amount_cents"] == 4000
    assert all(line["allocation_basis"] == "RANKED_PRIORITY" for line in lines)
    assert all(line["status"] == "PROVISIONAL" for line in lines)
    assert ctx["delivery"]["allocated_total_cents"] == 60000
    assert ctx["delivery"]["admin_total_cents"] == 8000


def test_equal_rank_braiding_order_falls_back_to_created_at():
    """PRD §3.7: "under the `RANKED_PRIORITY` basis, grants are drawn in
    ascending `allocation_rank` with ties broken by ascending creation time".
    PRD §3.7: "That set is ordered once, before any line is written, and the
    order is never recomputed between lines".

    Design: Corner/cross_cutting_complexity_layers/equal_rank_braiding_order_falls_back_to_created_at
    """
    set_clock("2026-09-01T00:00:00Z")
    funder = create_funder()
    program = create_program()
    early = create_grant(funder["id"], program["id"], grant_code="G-EARLY",
                         total_award_cents=40000, admin_rate_pct=0.10, allocation_rank=1)
    set_clock("2026-09-02T00:00:00Z")
    late = create_grant(funder["id"], program["id"], grant_code="G-LATE",
                        total_award_cents=200000, admin_rate_pct=0.10, allocation_rank=1)

    client = create_client()
    assessment = open_assessment(client["id"], assessment_date="2026-09-02T00:00:00Z")
    screen = open_screen(assessment["id"], program["id"], early["id"])
    verify_screen(screen["id"])
    submit_assessment(assessment["id"])
    route_assessment(assessment["id"])
    determine_screen(screen["id"], "ELIGIBLE")
    enrollments = get_success_data(api_client.list_enrollments(
        PROGRAM, {"client_id": client["id"], "program_id": program["id"]}))
    enrollment = activate_enrollment(enrollments[0]["id"])
    authorization = authorize_units(enrollment["id"], late["id"], enrollment["version"],
                                    authorized_units=20, unit_rate_cents=5000)
    delivery = record_delivery(authorization["id"], late["id"], client["id"],
                               authorization["version"], units_delivered=12,
                               unit_rate_cents=5000,
                               service_date="2026-09-02T01:00:00Z")
    document_delivery(delivery["id"])

    lines = delivery_lines(delivery["id"])
    assert lines[0]["allocation_rank"] == 1
    assert lines[0]["grant_id"] == early["id"], "the tie falls to the earlier created grant"
    assert lines[0]["allocated_amount_cents"] == 40000
    assert lines[1]["allocation_rank"] == 2
    assert lines[1]["grant_id"] == late["id"]
    assert lines[1]["allocated_amount_cents"] == 20000


def test_braided_allocation_rank_order_vs_period_order_admin_divergence():
    """PRD §3.7: "under the `RANKED_PRIORITY` basis, grants are drawn in
    ascending `allocation_rank` with ties broken by ascending creation time;
    under the `CHRONOLOGICAL_PERIOD` basis, grants are drawn in ascending
    `period_start` with ties broken by ascending creation time."
    PRD §3.7: "`DIRECT_ONLY` and `HEADCOUNT` produce the `RANKED_PRIORITY`
    order, while `TIME_AND_EFFORT` and `SQUARE_FOOTAGE` produce the
    `CHRONOLOGICAL_PERIOD` order."

    Design: Difficulty/dual_variant_calc/braided_allocation_rank_order_vs_period_order_admin_divergence
    """
    set_clock("2026-10-02T00:00:00Z")
    funder = create_funder(name="FED", funder_type="FEDERAL",
                           allow_faith_based_activity=False,
                           requires_time_and_effort_documentation=True,
                           max_admin_rate_pct=0.25, fiscal_year_start_month=10)
    program = create_program(name="HOUSING_PGM", capacity_slots=10)
    common = {"total_award_cents": 40000, "admin_rate_pct": 0.10, "allocation_rank": 1,
              "period_start": "2026-10-01T00:00:00Z", "period_end": "2027-09-30T00:00:00Z"}
    rank_first = dict(common, cost_allocation_basis="DIRECT_ONLY", grant_code="G-A1")
    rank_second = {"grant_code": "G-B1", "total_award_cents": 20000, "admin_rate_pct": 0.20,
                   "allocation_rank": 2, "cost_allocation_basis": "DIRECT_ONLY",
                   "period_start": "2026-09-15T00:00:00Z",
                   "period_end": "2027-09-30T00:00:00Z"}
    period_first = dict(common, cost_allocation_basis="TIME_AND_EFFORT", grant_code="G-A2")
    period_second = {"grant_code": "G-B2", "total_award_cents": 20000, "admin_rate_pct": 0.20,
                     "allocation_rank": 2, "cost_allocation_basis": "TIME_AND_EFFORT",
                     "period_start": "2026-09-15T00:00:00Z",
                     "period_end": "2027-09-30T00:00:00Z"}
    a1 = create_grant(funder["id"], program["id"], **rank_first)
    b1 = create_grant(funder["id"], program["id"], **rank_second)
    a2 = create_grant(funder["id"], program["id"], **period_first)
    b2 = create_grant(funder["id"], program["id"], **period_second)

    def build_delivery(client_name, screen_grant, bearer_grant, service_date):
        client = create_client(full_name=client_name)
        assessment = open_assessment(client["id"], assessment_date="2026-09-01T00:00:00Z")
        screen = open_screen(assessment["id"], program["id"], screen_grant["id"])
        verify_screen(screen["id"])
        submit_assessment(assessment["id"])
        route_assessment(assessment["id"])
        determine_screen(screen["id"], "ELIGIBLE")
        rows = get_success_data(api_client.list_enrollments(
            PROGRAM, {"client_id": client["id"], "program_id": program["id"]}))
        enrollment = activate_enrollment(rows[0]["id"])
        authorization = authorize_units(enrollment["id"], bearer_grant["id"],
                                        enrollment["version"], authorized_units=40,
                                        unit_rate_cents=4500,
                                        period_start="2026-09-01T00:00:00Z",
                                        period_end="2027-09-01T00:00:00Z")
        delivery = record_delivery(authorization["id"], screen_grant["id"], client["id"],
                                   authorization["version"], units_delivered=12,
                                   unit_rate_cents=4500, service_date=service_date)
        return document_delivery(delivery["id"])

    del_1 = build_delivery("Client One", a1, b1, "2026-10-02T00:00:00Z")
    del_2 = build_delivery("Client Two", a2, b2, "2026-10-03T00:00:00Z")

    assert del_1["allocated_total_cents"] == 54000
    assert del_1["admin_total_cents"] == 6800, "ranked order: 40000*0.10 + 14000*0.20"
    lines_1 = delivery_lines(del_1["id"])
    assert lines_1[0]["grant_id"] == a1["id"]
    assert lines_1[0]["allocated_amount_cents"] == 40000
    assert lines_1[0]["admin_amount_cents"] == 4000
    assert lines_1[0]["allocation_basis"] == "RANKED_PRIORITY"
    assert lines_1[1]["grant_id"] == b1["id"]
    assert lines_1[1]["allocated_amount_cents"] == 14000
    assert lines_1[1]["admin_amount_cents"] == 2800
    assert lines_1[1]["allocation_basis"] == "RANKED_PRIORITY"

    assert del_2["allocated_total_cents"] == 54000
    assert del_2["admin_total_cents"] == 7400, "period order: 20000*0.20 + 34000*0.10"
    lines_2 = delivery_lines(del_2["id"])
    assert lines_2[0]["grant_id"] == b2["id"]
    assert lines_2[0]["allocated_amount_cents"] == 20000
    assert lines_2[0]["admin_amount_cents"] == 4000
    assert lines_2[0]["allocation_basis"] == "CHRONOLOGICAL_PERIOD"
    assert lines_2[1]["grant_id"] == a2["id"]
    assert lines_2[1]["allocated_amount_cents"] == 34000
    assert lines_2[1]["admin_amount_cents"] == 3400
    assert lines_2[1]["allocation_basis"] == "CHRONOLOGICAL_PERIOD"


def test_admin_share_line_level_rounding_beats_sum_then_round():
    """PRD §2.6: "that line's share is rounded to whole cents first, and the
    rounded line values are then added together to produce the delivery's
    administrative total. Summing the unrounded products and rounding once at
    the end is explicitly not the behaviour: two lines of 1005 cents each at an
    administrative rate of one tenth contribute 101 cents each, for a total of
    202 cents, not 201."

    Design: Difficulty/combinatorial_formula/admin_share_line_level_rounding_beats_sum_then_round
    """
    set_clock("2026-10-02T00:00:00Z")
    ctx = setup_two_grant_braiding(
        grant_a_overrides={"grant_code": "G-A", "total_award_cents": 1005,
                           "admin_rate_pct": 0.10, "allocation_rank": 1},
        grant_b_overrides={"grant_code": "G-B", "total_award_cents": 1005,
                           "admin_rate_pct": 0.10, "allocation_rank": 2,
                           "period_start": "2026-09-15T00:00:00Z"},
        units_delivered=3, unit_rate_cents=670, document=True,
    )
    assert ctx["delivery"]["allocated_total_cents"] == 2010
    assert ctx["delivery"]["admin_total_cents"] == 202, (
        "round per line then sum gives 202; sum then round would give 201"
    )
    lines = delivery_lines(ctx["delivery"]["id"])
    assert len(lines) == 2
    for line in lines:
        assert line["allocated_amount_cents"] == 1005
        assert line["admin_amount_cents"] == 101


def test_allocation_residual_above_zero_rejects_documentation_atomically():
    """PRD §3.7: "If the walk finishes with a residual still above zero — which
    happens when the combined remaining capacity of every candidate grant falls
    below the delivery's total cost — the documentation is refused with
    `ERR_ALLOCATION_EXCEEDS_AWARD` (HTTP 409), and the rewrite is abandoned."
    PRD §3.7: "Only after the entire pass completes are the receiving grants'
    `obligated_cents` balances increased."

    Design: Corner/errors/allocation_residual_above_zero_rejects_documentation_atomically
    """
    set_clock("2026-09-02T00:00:00Z")
    from test_helpers import setup_draft_delivery
    ctx = setup_draft_delivery(units_delivered=12, unit_rate_cents=5000,
                               grant_overrides={"grant_code": "G-SMALL",
                                                "total_award_cents": 40000,
                                                "admin_rate_pct": 0.10},
                               authorization_overrides={"authorized_units": 20,
                                                        "unit_rate_cents": 5000})
    resp = api_client.document_service_delivery(ctx["delivery"]["id"], PROGRAM)
    validate_error(resp, ApiErrorId.ERR_ALLOCATION_EXCEEDS_AWARD)

    grant = get_success_data(api_client.get_grant(ctx["grant"]["id"], FINANCE))
    assert grant["obligated_cents"] == 0
    assert grant["expended_cents"] == 0
    assert grant["burn_ratio"] == 0.0
    assert grant["status"] == "OPEN"

    delivery = get_success_data(api_client.get_service_delivery(ctx["delivery"]["id"], FINANCE))
    assert delivery["status"] == "DRAFT"
    assert delivery["documentation_status"] == "INCOMPLETE"
    assert delivery["allocated_total_cents"] == 0
    assert delivery_lines(ctx["delivery"]["id"]) == []


def test_document_response_carries_braided_totals_with_no_read_after_write_lag():
    """PRD §3.7: "`allocated_total_cents` is the sum of the lines' allocated
    amounts, and the delivery's combined total is the allocated total plus the
    administrative total."
    PRD §3.7: "Each receiving grant's `obligated_cents` increases by the
    allocated and administrative amounts placed on it, its `burn_ratio` is
    recomputed under the posture rule of §2.12".

    Design: Corner/consistency_model/document_response_carries_braided_totals_with_no_read_after_write_lag
    """
    set_clock("2026-09-02T00:00:00Z")
    from test_helpers import setup_documented_delivery
    ctx = setup_documented_delivery(units_delivered=12, unit_rate_cents=4500,
                                    grant_overrides={"total_award_cents": 200000,
                                                     "admin_rate_pct": 0.10},
                                    authorization_overrides={"authorized_units": 20,
                                                             "unit_rate_cents": 4500})
    delivery = ctx["delivery"]
    assert delivery["status"] == "DOCUMENTED"
    assert delivery["documentation_status"] == "COMPLETE"
    assert delivery["allocated_total_cents"] == 54000
    assert delivery["admin_total_cents"] == 5400

    lines = delivery_lines(delivery["id"])
    assert len(lines) == 1
    assert lines[0]["allocated_amount_cents"] == 54000
    assert lines[0]["admin_amount_cents"] == 5400
    assert lines[0]["status"] == "PROVISIONAL"

    grant = get_success_data(api_client.get_grant(ctx["grant"]["id"], FINANCE))
    assert grant["obligated_cents"] == 59400
    assert grant["burn_ratio"] == 0.297000


def test_grant_get_reports_committed_basis_burn_ratio_after_documentation():
    """PRD §2.12: "Commitment is counted on the committed basis: the grant's
    `expended_cents` plus its `obligated_cents`, divided by
    `total_award_cents`, rounded half up to six decimal places."
    PRD §2.12: "A second, reporting-only projection uses the cash basis —
    `expended_cents` alone — and is surfaced on the grant read; it never gates a
    write".

    Design: Corner/endpoints/grant_get_reports_committed_basis_burn_ratio_after_documentation
    """
    set_clock("2026-09-02T00:00:00Z")
    from test_helpers import setup_documented_delivery
    ctx = setup_documented_delivery(units_delivered=12, unit_rate_cents=4500,
                                    grant_overrides={"total_award_cents": 200000,
                                                     "admin_rate_pct": 0.10},
                                    authorization_overrides={"authorized_units": 20,
                                                             "unit_rate_cents": 4500})
    grant = get_success_data(api_client.get_grant(ctx["grant"]["id"], FINANCE))
    assert grant["burn_ratio"] == 0.297000, "the committed basis counts the obligation"
    assert grant["status"] == "OPEN"
    assert grant["obligated_cents"] == 59400
    assert grant["expended_cents"] == 0, "nothing has been billed yet"
