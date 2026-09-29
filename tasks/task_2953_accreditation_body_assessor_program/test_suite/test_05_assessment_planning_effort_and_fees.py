"""The assessment plan: the derived day budget, the four fee lines and the
DRAFT/APPROVED loop.

Every test in this module translates exactly one design instance; the
``Design:`` line closing each docstring names it.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.assertions import (
    assert_cents,
    assert_effort_breakdown,
    assert_fee_lines,
    assert_total_count,
    assert_travel_line_is_unmultiplied,
    rounded_fee_line,
)
from test_helpers.api_errors import (
    ERR_INVALID_STATE_TRANSITION,
    ERR_STALE_APPLICATION_VERSION,
)
from test_helpers.constants import (
    APP_PLANNED,
    APP_TEAM_ASSIGNED,
    PLAN_APPROVED,
    PLAN_CANCELLED,
    PLAN_DRAFT,
    PLAN_MODE_HYBRID,
    RATE_ON_SITE_DAY_CENTS,
    RATE_REMOTE_DAY_CENTS,
    RATE_TRAVEL_DAY_CENTS,
    RATE_WITNESS_DAY_CENTS,
    SESSION_ABORTED,
    EVIDENCE_NOTE_PLAN_RETURNED,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import ASSESSMENT_MANAGER

SEVEN_SCOPE_LINES = [
    "Mass 1kg-20kg",
    "Temperature -20C-200C",
    "Pressure 0-10MPa",
    "Length 0-1m",
    "Torque 0-100Nm",
    "Volume 0-10L",
    "Electrical DC 0-1000V",
]

SIX_SCOPE_LINES = [
    "mass calibration 1 mg - 20 kg",
    "temperature calibration -40 C - 250 C",
    "pressure calibration 0 - 700 bar",
    "humidity calibration 10 - 95 pct RH",
    "electrical DC voltage 0 - 1000 V",
    "torque calibration 1 - 500 Nm",
]

THREE_SCOPE_LINES = [
    "mass calibration 1 mg - 20 kg",
    "temperature calibration -40 C - 250 C",
    "pressure calibration 0 - 700 bar",
]

MULTIPLIER = "1.0725"


def test_assessment_fee_rounds_each_line_before_summing(client):
    """Four lines each rounded half up, then summed; one cent separates that
    from summing the exact products.

    PRD section 3.5: "The plan's price is assembled from four separate fee
    lines, each rounded half up to whole cents *before* any addition takes
    place." and "The travel line `fee_line_travel_cents` is a flat
    pass-through of `87500` cents per travel day — **the complexity
    multiplier does not apply to travel**, because travel is reimbursed at
    cost rather than priced for effort."

    Design: Difficulty/combinatorial_formula/assessment_fee_rounds_each_line_before_summing
    """
    ctx = fx.new_context(client, "ISO17025-FEE")
    fx.with_lead(ctx)
    fx.with_organization(ctx)
    fx.with_initial_cycle(ctx, requested_scope_lines=SEVEN_SCOPE_LINES)
    fx.with_confirmed_team(ctx, ("lead",))
    application_version = fx.read_application_version(client, ctx["app_id"])

    response = client.create_plan(
        ctx["app_id"],
        f.plan_payload(application_version, 3, 2, PLAN_MODE_HYBRID, "2026-09-07", "2026-09-18"),
        ASSESSMENT_MANAGER,
    )

    plan = validate_success(response, 201)
    assert_effort_breakdown(
        plan, witness_days_planned=3, core_days=8, travel_days=1, total_effort_days=9
    )
    assert_fee_lines(
        plan,
        on_site_cents=466538,
        remote_cents=206993,
        witness_cents=426319,
        travel_cents=87500,
        total_cents=1187350,
    )
    assert int(plan["assessment_fee_cents"]) != 1187349, (
        "Summing the four exact products and rounding once would give 1187349"
    )
    assert_travel_line_is_unmultiplied(plan)
    assert_cents(
        plan["fee_line_on_site_cents"], rounded_fee_line(3, RATE_ON_SITE_DAY_CENTS, MULTIPLIER)
    )
    assert_cents(
        plan["fee_line_remote_cents"], rounded_fee_line(2, RATE_REMOTE_DAY_CENTS, MULTIPLIER)
    )
    assert_cents(
        plan["fee_line_witness_cents"], rounded_fee_line(3, RATE_WITNESS_DAY_CENTS, MULTIPLIER)
    )
    assert_cents(plan["fee_line_travel_cents"], 1 * RATE_TRAVEL_DAY_CENTS)
    assert plan["status"] == PLAN_DRAFT


def test_assessment_effort_travel_tier_is_keyed_on_core_days_not_total(client):
    """Ten core days sit in the middle travel tier even though the total
    lands at eleven, which the top tier would claim.

    PRD section 3.5: "**Travel days** is selected from a tier keyed on
    `core_days` — and on `core_days` alone, never on the total." and
    "When the cycle is in `TEAM_ASSIGNED`, the approval also advances it
    `TEAM_ASSIGNED → PLANNED`, writes the plan's `total_effort_days` into the
    cycle's `planned_effort_days`, and bumps the cycle's `version`."

    Design: Difficulty/combinatorial_formula/assessment_effort_travel_tier_keyed_on_core_days_not_total
    """
    ctx = fx.new_context(client, "ISO17025-TIER")
    fx.with_lead(ctx)
    fx.with_organization(
        ctx,
        legal_name="Borealis Test House",
        country_code="SE",
        contact_email="qa@borealis.test",
    )
    fx.with_initial_cycle(ctx, requested_scope_lines=SEVEN_SCOPE_LINES)
    fx.with_confirmed_team(ctx, ("lead",))
    application_version = fx.read_application_version(client, ctx["app_id"])

    response = client.create_plan(
        ctx["app_id"],
        f.plan_payload(application_version, 4, 3, PLAN_MODE_HYBRID, "2026-09-07", "2026-09-25"),
        ASSESSMENT_MANAGER,
    )

    plan = validate_success(response, 201)
    assert_effort_breakdown(
        plan, witness_days_planned=3, core_days=10, travel_days=1, total_effort_days=11
    )
    assert plan["travel_days"] != 2, (
        "A total_effort_days of 11 must not pull the plan into the top travel tier"
    )
    assert_fee_lines(
        plan,
        on_site_cents=622050,
        remote_cents=310489,
        witness_cents=426319,
        travel_cents=87500,
        total_cents=1446358,
    )
    approved = fx.approve_plan(client, plan["id"])
    assert approved["status"] == PLAN_APPROVED
    assert approved["total_effort_days"] == 11
    application = fx.read_application(client, ctx["app_id"])
    assert application["status"] == APP_PLANNED
    assert application["planned_effort_days"] == 11


def test_travel_tier_is_keyed_on_core_days_across_all_three_tiers(client):
    """Three successive drafts land in the three tiers, and each supersedes
    the one before it.

    PRD section 3.5: "A `core_days` of 5 or fewer yields `travel_days` of 0; a
    `core_days` of 6 through 10 inclusive yields 1; a `core_days` above 10
    yields 2." and "Creating a plan when the cycle already has a plan in
    `DRAFT` is legitimate and is how a planner iterates: the earlier `DRAFT`
    plan moves to `CANCELLED`, records the new plan's identifier in its own
    `superseded_by_plan_id`, and has its `version` bumped."

    Design: Corner/calculations/travel_tier_is_keyed_on_core_days_across_all_three_tiers
    """
    ctx = fx.new_context(client, "ISO17025-CAL", complexity_multiplier=1.0)
    fx.with_lead(ctx)
    fx.with_organization(
        ctx,
        legal_name="Northlight Testing AB",
        country_code="SE",
        contact_email="qa@northlight.test",
    )
    fx.with_initial_cycle(ctx, requested_scope_lines=SIX_SCOPE_LINES)
    fx.with_confirmed_team(ctx, ("lead",))
    plan_1 = fx.create_plan(
        client, ctx["app_id"], 2, 1, PLAN_MODE_HYBRID, "2026-09-07", "2026-09-11"
    )
    plan_2 = fx.create_plan(
        client, ctx["app_id"], 3, 1, PLAN_MODE_HYBRID, "2026-09-07", "2026-09-15"
    )
    application_version = fx.read_application_version(client, ctx["app_id"])

    response = client.create_plan(
        ctx["app_id"],
        f.plan_payload(application_version, 6, 3, PLAN_MODE_HYBRID, "2026-09-07", "2026-09-25"),
        ASSESSMENT_MANAGER,
    )

    plan_3 = validate_success(response, 201)
    assert_effort_breakdown(
        plan_1, witness_days_planned=2, core_days=5, travel_days=0, total_effort_days=5
    )
    assert_effort_breakdown(
        plan_2, witness_days_planned=2, core_days=6, travel_days=1, total_effort_days=7
    )
    assert_effort_breakdown(
        plan_3, witness_days_planned=2, core_days=11, travel_days=2, total_effort_days=13
    )
    stored_1 = validate_success(client.get_plan(plan_1["id"], ASSESSMENT_MANAGER), 200)
    assert stored_1["status"] == PLAN_CANCELLED
    assert stored_1["superseded_by_plan_id"] == plan_2["id"]
    stored_2 = validate_success(client.get_plan(plan_2["id"], ASSESSMENT_MANAGER), 200)
    assert stored_2["status"] == PLAN_CANCELLED
    assert stored_2["superseded_by_plan_id"] == plan_3["id"]
    assert plan_3["status"] == PLAN_DRAFT
    assert plan_3["superseded_by_plan_id"] is None
    application = fx.read_application(client, ctx["app_id"])
    assert application["status"] == APP_TEAM_ASSIGNED
    assert application["planned_effort_days"] is None


def test_stale_application_version_on_plan_creation_is_rejected(client):
    """The cycle version read before the team was confirmed no longer proves
    anything about the state being planned against.

    PRD section 2.6: "That request must carry `expected_application_version`,
    a non-optional integer field whose value is the
    `AccreditationApplication` `version` the client last read. If it does not
    equal the cycle's current `version`, the creation is rejected with
    `ERR_STALE_APPLICATION_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/stale_application_version_on_plan_creation_rejected
    """
    ctx = fx.new_context(client, "ISO17025-CAL")
    fx.with_lead(ctx, declared=(8, 5, 2))
    fx.with_organization(
        ctx,
        legal_name="Northlight Testing AB",
        country_code="SE",
        contact_email="qa@northlight.test",
    )
    fx.with_initial_cycle(ctx, requested_scope_lines=THREE_SCOPE_LINES)
    version_before_team = fx.read_application_version(client, ctx["app_id"])
    fx.with_confirmed_team(ctx, ("lead",))

    response = client.create_plan(
        ctx["app_id"],
        f.plan_payload(
            version_before_team, 3, 2, PLAN_MODE_HYBRID, "2026-09-07", "2026-09-18"
        ),
        ASSESSMENT_MANAGER,
    )

    validate_error(response, ERR_STALE_APPLICATION_VERSION, 412)
    assert_total_count(
        client.list_plans(ASSESSMENT_MANAGER, {"application_id": ctx["app_id"]}), 0
    )
    current_version = fx.read_application_version(client, ctx["app_id"])
    assert current_version == version_before_team + 1, (
        "Only the confirmed assignment bumped the cycle; the rejected call did not"
    )
    plan = validate_success(
        client.create_plan(
            ctx["app_id"],
            f.plan_payload(
                current_version, 3, 2, PLAN_MODE_HYBRID, "2026-09-07", "2026-09-18"
            ),
            ASSESSMENT_MANAGER,
        ),
        201,
    )
    assert plan["status"] == PLAN_DRAFT
    assert_effort_breakdown(
        plan, witness_days_planned=2, core_days=7, travel_days=1, total_effort_days=8
    )
    assert fx.read_application(client, ctx["app_id"])["status"] == APP_TEAM_ASSIGNED


def test_approving_an_already_approved_plan_returns_invalid_state(client):
    """Approval is not idempotent: the second attempt fails on the plan's own
    status and changes nothing.

    PRD section 3.5: "The plan must be `DRAFT`; the cycle must be in
    `SUBMITTED` or `TEAM_ASSIGNED` and must not be frozen; the programme must
    be in `status` `PUBLISHED` (`ERR_SCHEME_NOT_PUBLISHED`); the programme's
    current `rule_revision` must still equal the cycle's
    `pinned_scheme_rule_revision` (`ERR_SCHEME_VERSION_SUPERSEDED`)"

    Design: Corner/state_machines/approving_an_already_approved_plan_returns_invalid_state
    """
    ctx = fx.new_context(client, "ISO17025-CAL")
    fx.with_lead(ctx)
    fx.with_organization(
        ctx,
        legal_name="Northlight Testing AB",
        country_code="SE",
        contact_email="qa@northlight.test",
    )
    fx.with_initial_cycle(ctx, requested_scope_lines=THREE_SCOPE_LINES)
    fx.with_confirmed_team(ctx, ("lead",))
    fx.with_approved_plan(ctx, 3, 2, PLAN_MODE_HYBRID)
    approved_version = ctx["plan"]["version"]

    response = client.approve_plan(ctx["plan_id"], ASSESSMENT_MANAGER)

    validate_error(response, ERR_INVALID_STATE_TRANSITION, 409)
    stored = validate_success(client.get_plan(ctx["plan_id"], ASSESSMENT_MANAGER), 200)
    assert stored["status"] == PLAN_APPROVED
    assert stored["version"] == approved_version
    assert_effort_breakdown(
        stored, witness_days_planned=2, core_days=7, travel_days=1, total_effort_days=8
    )
    assert_cents(stored["assessment_fee_cents"], 1045244)
    application = fx.read_application(client, ctx["app_id"])
    assert application["status"] == APP_PLANNED
    assert application["planned_effort_days"] == 8


def test_plan_return_to_draft_aborts_sessions_and_restores_the_ledger(client):
    """The return unwinds the scheduled witnessing and hands the assessor's
    days back.

    PRD section 3.5: "Every witnessing session under the plan still in
    `SCHEDULED` becomes `ABORTED` with the `evidence_note` `plan returned to
    draft`, and each such abort returns that session's `day_count` to its
    assessor's ledger — `committed_witness_days` down,
    `available_witness_days` up by the same amount, so that the capacity
    identity of §2.8 still holds."

    Design: Corner/state_machines/plan_return_to_draft_aborts_scheduled_sessions_and_restores_the_ledger
    """
    revision_note = "witnessing window moved at the applicant's request"
    ctx = fx.new_context(client, "ISO17025-CAL")
    fx.with_lead(ctx)
    fx.with_organization(
        ctx,
        legal_name="Northlight Testing AB",
        country_code="SE",
        contact_email="qa@northlight.test",
    )
    fx.with_initial_cycle(ctx, requested_scope_lines=THREE_SCOPE_LINES)
    fx.with_confirmed_team(ctx, ("lead",))
    fx.with_approved_plan(ctx, 3, 2, PLAN_MODE_HYBRID)
    fx.with_booked_session(
        ctx,
        "lead",
        "2026-09-07T08:00:00Z",
        "2026-09-08T16:00:00Z",
        site_ref="NORTHLIGHT-LAB-1",
    )
    session = ctx["sessions"][-1]
    assert session["day_count"] == 4
    booked_owner = fx.read_assessor(client, ctx["lead_id"])
    assert booked_owner["committed_witness_days"] == 4
    assert booked_owner["available_witness_days"] == 16

    response = client.return_plan_to_draft(
        ctx["plan_id"], f.return_to_draft_payload(revision_note), ASSESSMENT_MANAGER
    )

    plan = validate_success(response, 200)
    assert plan["status"] == PLAN_DRAFT
    assert plan["approved_at"] is None
    assert plan["revision_note"] == revision_note
    stored_session = validate_success(
        client.get_witness_session(session["id"], ASSESSMENT_MANAGER), 200
    )
    assert stored_session["status"] == SESSION_ABORTED
    assert stored_session["evidence_note"] == EVIDENCE_NOTE_PLAN_RETURNED
    assert stored_session["day_count"] == 4, "The abort does not rewrite the booked cost"
    assert stored_session["outcome"] is None
    owner = fx.read_assessor(client, ctx["lead_id"])
    assert owner["committed_witness_days"] == 0
    assert owner["available_witness_days"] == 20
    assert (
        owner["committed_witness_days"] + owner["available_witness_days"]
        == owner["annual_witness_capacity_days"]
    )
    application = fx.read_application(client, ctx["app_id"])
    assert application["status"] == APP_TEAM_ASSIGNED
    assert application["planned_effort_days"] is None
