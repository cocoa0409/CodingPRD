"""
Formulas whose result depends on where the arithmetic is capped and rounded.

Three of them are pinned here: the match score with an inner component cap and an
outer total cap, the per-line rounding of a support-request award, and the
administrative-fee tier that is read from the request and never from the total.
"""

from test_helpers.assertions import (
    assert_int_field,
    assert_match_breakdown,
    assert_money_cents,
    assert_one_decimal_place,
    validate_unpaginated,
)
from test_helpers.constants import (
    BARRIER_TIER_LOW,
    CATEGORY_TOOLS,
    CATEGORY_TRANSIT_PASS,
    ENROLLMENT_ATTENDED,
    INDUSTRY_MANUFACTURING,
    MATCH_BREAKDOWN_KEYS,
    RECORD_DRUG_OFFENSE,
    REQUEST_SUBMITTED,
    SESSION_TYPE_DISCLOSURE_COACHING,
    SESSION_TYPE_INTERVIEW_PRACTICE,
    TRANSPORT_OWN_VEHICLE,
)
from test_helpers import factories as f
from test_helpers.test_users import CASE_MANAGER, FUNDER_ANALYST


def _saturating_preview_inputs(api, build, clock):
    """A participant and opening whose six match components sum past 100."""
    participant = build.participant_assessed(
        0, 0, 0, 0, 0, full_name="Rosalind Frey", record_categories=[RECORD_DRUG_OFFENSE]
    )
    build.release_plan_draft(
        participant["id"], transportation_plan_type=TRANSPORT_OWN_VEHICLE
    )

    coaching = build.readiness_session(
        session_type=SESSION_TYPE_DISCLOSURE_COACHING,
        starts_at="2026-08-01T13:00:00.000Z",
        ends_at="2026-08-01T15:00:00.000Z",
    )
    practice = build.readiness_session(
        session_type=SESSION_TYPE_INTERVIEW_PRACTICE,
        starts_at="2026-08-01T15:30:00.000Z",
        ends_at="2026-08-01T17:00:00.000Z",
    )
    reviewed = build.enrollment(
        coaching["id"], participant["id"], disclosure_script_reviewed=True
    )
    plain = build.enrollment(
        practice["id"], participant["id"], disclosure_script_reviewed=False
    )

    clock.set("2026-08-01T17:30:00.000Z")
    for enrollment in (reviewed, plain):
        attended = validate_unpaginated(
            api.set_enrollment_status(
                enrollment["id"],
                f.enrollment_status_payload(ENROLLMENT_ATTENDED),
                CASE_MANAGER,
            )
        )
        assert attended["status"] == ENROLLMENT_ATTENDED

    partnership = build.partnership_active(
        employer_name="Calder Fabrication", industry=INDUSTRY_MANUFACTURING
    )
    opening = build.job_opening(
        partnership["id"],
        title="CNC Operator",
        occupation_code="51-4011",
        hourly_wage_cents=2400,
        weekly_hours=40,
        openings_count=1,
    )
    return participant, opening


def test_match_score_saturates_at_one_hundred_when_the_components_sum_to_more(
    api, build, clock
):
    """
    The outer cap on the total is genuinely reachable.

    PRD section 3.6: "A wage of 2,400 cents, 40 hours a week, a `barrier_score` of
    0.0, an `OWN_VEHICLE` plan, three attended sessions including a reviewed
    disclosure script, and a certified employer produces 30, 20, 20, 15, 15, and 5
    — 105 before the outer cap and a stored `match_score` of exactly 100."

    Design: Difficulty/combinatorial_formula/job_match_score_double_cap_saturation_at_100
    """
    participant, opening = _saturating_preview_inputs(api, build, clock)

    preview = validate_unpaginated(
        api.get_match_preview(
            opening["id"], CASE_MANAGER, {"participant_id": participant["id"]}
        )
    )
    assert preview["participant_id"] == participant["id"]
    assert preview["job_opening_id"] == opening["id"]
    assert_int_field(preview, "match_score", 100)
    assert preview["eligible"] is True
    assert preview["blocking_error_id"] is None

    components = preview["match_breakdown"]
    assert_match_breakdown(components, 30, 20, 20, 15, 15, 5)
    assert sum(components[key] for key in MATCH_BREAKDOWN_KEYS) == 105


def test_match_breakdown_reports_the_uncapped_inner_components(api, build, clock):
    """
    The inner caps bite before the outer one: a 2,400-cent wage would score 36 on
    the wage component and two attended sessions with a reviewed script would score
    20 on readiness, yet each is held at its own ceiling.

    PRD section 3.6: "The `wage_component` rewards pay against a programme target
    wage of 2,000 cents an hour — twenty dollars. It is thirty multiplied by the
    opening's `hourly_wage_cents`, divided by 2,000, rounded half up to a whole
    number, and then capped at 30."

    Design: Difficulty/combinatorial_formula/job_match_score_double_cap_saturation_at_100
    """
    participant, opening = _saturating_preview_inputs(api, build, clock)

    scored = validate_unpaginated(api.get_participant(participant["id"], CASE_MANAGER))
    assert_one_decimal_place(scored, "barrier_score", 0.0)
    assert scored["barrier_tier"] == BARRIER_TIER_LOW

    preview = validate_unpaginated(
        api.get_match_preview(
            opening["id"], CASE_MANAGER, {"participant_id": participant["id"]}
        )
    )
    components = preview["match_breakdown"]
    assert components["wage_component"] == 30
    assert components["readiness_component"] == 15
    assert components["barrier_fit_component"] == 20
    assert components["access_component"] == 15


def _tools_request_with_four_lines(api, build):
    """The PRD's four-line TOOLS request, whose rounding point is observable."""
    grant = build.grant(authorized_cents=5000000, per_participant_cap_cents=60000)
    participant = build.participant()
    lines = [
        f.line_item("Steel-toe boots", 4550),
        f.line_item("Insulated jacket", 5550),
        f.line_item("Hand tool set", 3750),
        f.line_item("Safety glasses", 2570),
    ]
    request = build.support_request(
        participant["id"], grant["id"], lines, category=CATEGORY_TOOLS
    )
    return grant, participant, request


def test_support_request_awards_are_rounded_line_by_line_and_never_re_rounded(
    api, build
):
    """
    Per-line rounding and aggregate rounding diverge by two cents, and the
    per-line result is the required one.

    PRD section 3.8: "Rounding per line and rounding the aggregate genuinely
    diverge: for a `TOOLS` request at 0.85 with four lines of `quantity` 1 and unit
    costs 4550, 5550, 3750, and 2570, the per-line awards are 3868, 4718, 3188, and
    2185 for a `requested_cents` of 13,959 — whereas rounding the aggregate of
    16,420 at 0.85 would have produced 13,957, a two-cent divergence that the
    per-line rule forbids."

    Design: Difficulty/combinatorial_formula/support_request_per_line_rounding_beats_aggregate_rounding
    """
    grant, participant, request = _tools_request_with_four_lines(api, build)

    awards = [line["line_award_cents"] for line in request["line_items"]]
    assert awards == [3868, 4718, 3188, 2185]
    assert_money_cents(request, "requested_cents", 13959)
    assert request["requested_cents"] != 13957
    assert request["status"] == REQUEST_SUBMITTED


def test_support_request_fee_and_total_follow_the_per_line_requested_sum(api, build):
    """
    The middle fee tier applies to a 13,959-cent request, and a submitted request
    commits no money.

    PRD section 3.8: "A `requested_cents` of 5,000 selects the lowest tier for a
    fee of 0 and a total of 5,000; 5,001 selects the middle tier for a fee of 150
    and a total of 5,151; 13,959 selects the middle tier for a fee of 419 and a
    total of 14,378; and 57,143 selects the highest tier for a fee of 2,857 and a
    total of exactly 60,000."

    Design: Difficulty/combinatorial_formula/support_request_per_line_rounding_beats_aggregate_rounding
    """
    grant, participant, request = _tools_request_with_four_lines(api, build)

    assert_money_cents(request, "admin_fee_cents", 419)
    assert_money_cents(request, "total_charge_cents", 14378)

    stored = validate_unpaginated(api.get_grant(grant["id"], FUNDER_ANALYST))
    assert_money_cents(stored, "committed_cents", 0)
    assert_int_field(stored, "open_request_count", 1)


def _transit_pass_request_at_the_tier_boundary(api, build):
    """A request whose `requested_cents` lands on exactly 20,000."""
    grant = build.grant(authorized_cents=5000000, per_participant_cap_cents=60000)
    participant = build.participant(full_name="Terrence Boyd")
    request = build.support_request(
        participant["id"],
        grant["id"],
        [f.line_item("Monthly transit pass", 10000, 2)],
        category=CATEGORY_TRANSIT_PASS,
    )
    return grant, participant, request


def test_admin_fee_tier_is_read_from_requested_cents_and_not_from_the_total(
    api, build
):
    """
    Reading the tier from the total would push a 20,000-cent request into the top
    band and overcharge the fee.

    PRD section 3.8: "Selecting the tier from the total instead of from the request
    is observably wrong, because adding the fee can push the total past a boundary
    the request itself never crossed: a `requested_cents` of exactly 20,000 selects
    the middle tier, yielding a fee of 600 and a total of 20,600, whereas reading
    the tier from that 20,600 total would wrongly select 0.05 and produce a fee of
    1,030."

    Design: Difficulty/combinatorial_formula/admin_fee_tier_selected_from_requested_not_total
    """
    grant, participant, request = _transit_pass_request_at_the_tier_boundary(api, build)

    assert_money_cents(request, "requested_cents", 20000)
    assert_money_cents(request, "admin_fee_cents", 600)
    assert request["admin_fee_cents"] != 1030
    assert_money_cents(request, "total_charge_cents", 20600)


def test_transit_pass_lines_are_awarded_at_full_coverage(api, build):
    """
    The whole request is priced from one request-level rate, and the transit-pass
    rate covers the line in full.

    PRD section 3.8: "First the coverage rate is selected from the request-level
    `category` — not from any individual line — at 0.85 for `TOOLS`, 0.90 for
    `UNIFORM`, 1.00 for `TRANSIT_PASS`, 1.00 for `ID_FEE`, and 0.60 for
    `LICENSE_FEE`."

    Design: Difficulty/combinatorial_formula/admin_fee_tier_selected_from_requested_not_total
    """
    grant, participant, request = _transit_pass_request_at_the_tier_boundary(api, build)

    assert request["category"] == CATEGORY_TRANSIT_PASS
    assert len(request["line_items"]) == 1
    assert_money_cents(request["line_items"][0], "line_award_cents", 20000)
    assert_money_cents(request, "requested_cents", 20000)
    assert request["status"] == REQUEST_SUBMITTED
