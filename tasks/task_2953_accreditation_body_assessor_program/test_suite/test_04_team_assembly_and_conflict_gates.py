"""Assembling a conflict-free team: confirmation gates and the unwind cascade.

Every test in this module translates exactly one design instance; the
``Design:`` line closing each docstring names it.
"""

from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers.assertions import assert_capacity_ledger, assert_total_count
from test_helpers.api_errors import (
    ERR_INVALID_STATE_TRANSITION,
    ERR_QUALIFICATION_NOT_GRANTED,
)
from test_helpers.constants import (
    APP_SUBMITTED,
    APP_TEAM_ASSIGNED,
    EMPLOYMENT_CONTRACT,
    IMPARTIALITY_RESTRICTED,
    IMPARTIALITY_SCREENED,
    ORG_APPLIED,
    ORG_UNDER_ASSESSMENT,
    QUALIFICATION_STATUS_QUALIFIED,
    QUALIFICATION_STATUS_SUSPENDED,
    QUAL_EXPIRED,
    QUAL_GRANTED,
    RECUSAL_REASON_ASSESSOR_SUSPENDED,
    RELATIONSHIP_EMPLOYMENT,
    ROLE_TYPE_LEAD_ASSESSOR,
    TA_CONFIRMED,
    TA_PROPOSED,
    TA_RECUSED,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import ASSESSMENT_MANAGER, SCHEME_MANAGER

SUSPENSION_REASON = "Impartiality investigation opened by the governance committee."


def test_team_assignment_junction_links_one_assessor_to_two_cycles(client):
    """One assessor may hold a confirmed assignment on two cycles at once.

    PRD section 3.4: "Team-assignment lists may be filtered by
    `application_id`, `assessor_id`, `role_type` and `status`."

    Design: Corner/entities/team_assignment_junction_links_one_assessor_to_two_cycles
    """
    fx.set_clock(client, fx.CLOCK_BUILD_INSTANT)
    scheme = fx.create_published_scheme(
        client, "ISO17025-CAL", witness_min_count=2, qualification_points_required=60.0
    )
    assessor = fx.register_assessor(
        client, "Bruno Katz", "bruno.katz@ab.test", EMPLOYMENT_CONTRACT, 20
    )
    qualification = fx.register_qualification(
        client, assessor["id"], scheme["id"], ROLE_TYPE_LEAD_ASSESSOR, 6, 4, 1, "2026-05-10"
    )
    fx.verify_qualification(client, qualification["id"], 6, 4, 1)
    fx.screen_assessor(client, assessor["id"])
    org_1 = fx.register_organization(
        client, "Northlight Testing AB", "SE", "qa@northlight.test"
    )
    org_2 = fx.register_organization(
        client, "Meridian Calibration Oy", "FI", "qa@meridian.test"
    )
    app_1 = fx.open_initial_cycle(
        client, org_1["id"], scheme["id"], ["mass calibration 1 mg - 20 kg"], 30
    )
    app_2 = fx.open_initial_cycle(
        client, org_2["id"], scheme["id"], ["temperature calibration -40 C - 250 C"], 30
    )
    ta_1 = fx.propose_team_member(
        client, app_1["id"], assessor["id"], ROLE_TYPE_LEAD_ASSESSOR
    )
    fx.confirm_team_member(client, ta_1["id"])
    ta_2 = fx.propose_team_member(
        client, app_2["id"], assessor["id"], ROLE_TYPE_LEAD_ASSESSOR
    )

    response = client.confirm_team_assignment(ta_2["id"], ASSESSMENT_MANAGER)

    confirmed = validate_success(response, 200)
    assert confirmed["status"] == TA_CONFIRMED
    stored_first = validate_success(
        client.get_team_assignment(ta_1["id"], ASSESSMENT_MANAGER), 200
    )
    assert stored_first["status"] == TA_CONFIRMED
    assert_total_count(
        client.list_team_assignments(
            ASSESSMENT_MANAGER, {"assessor_id": assessor["id"]}
        ),
        2,
    )
    assert_total_count(
        client.list_team_assignments(ASSESSMENT_MANAGER, {"application_id": app_1["id"]}),
        1,
    )
    assert_total_count(
        client.list_team_assignments(ASSESSMENT_MANAGER, {"application_id": app_2["id"]}),
        1,
    )
    assert fx.read_application(client, app_1["id"])["status"] == APP_TEAM_ASSIGNED
    assert fx.read_application(client, app_2["id"])["status"] == APP_TEAM_ASSIGNED
    for organization in (org_1, org_2):
        stored = validate_success(
            client.get_organization(organization["id"], ASSESSMENT_MANAGER), 200
        )
        assert stored["status"] == ORG_UNDER_ASSESSMENT


def test_team_confirmation_cascade_is_visible_in_the_same_response(client):
    """The cycle and the organization have already moved by the time the
    confirmation response is read back.

    PRD section 2.8: "First, **every resource a cascade touches is genuinely
    mutated** — its `version` increases by 1 and its `updated_at` is
    refreshed — even when the cascade only changed a derived counter."

    Design: Corner/consistency_model/team_confirmation_cascade_is_visible_in_the_same_response
    """
    ctx = fx.new_context(client, "ISO17025-CAL")
    fx.with_lead(ctx, declared=(8, 5, 2), verified=(8, 5, 2))
    fx.with_organization(ctx, legal_name="Northlight Testing AB", country_code="SE",
                         contact_email="qa@northlight.test")
    fx.with_initial_cycle(
        ctx,
        requested_scope_lines=[
            "mass calibration 1 mg - 20 kg",
            "temperature calibration -40 C - 250 C",
            "pressure calibration 0 - 700 bar",
        ],
    )
    assignment = fx.propose_team_member(
        client, ctx["app_id"], ctx["lead_id"], ROLE_TYPE_LEAD_ASSESSOR
    )
    version_before = fx.read_application_version(client, ctx["app_id"])

    response = client.confirm_team_assignment(assignment["id"], ASSESSMENT_MANAGER)

    confirmed = validate_success(response, 200)
    assert confirmed["status"] == TA_CONFIRMED
    application = fx.read_application(client, ctx["app_id"])
    assert application["status"] == APP_TEAM_ASSIGNED
    assert application["version"] == version_before + 1
    organization = validate_success(
        client.get_organization(ctx["org_id"], ASSESSMENT_MANAGER), 200
    )
    assert organization["status"] == ORG_UNDER_ASSESSMENT
    assert_total_count(
        client.list_team_assignments(
            ASSESSMENT_MANAGER,
            {"application_id": ctx["app_id"], "status": TA_CONFIRMED},
        ),
        1,
    )
    again = fx.read_application(client, ctx["app_id"])
    assert again == application, "A second identical read must observe nothing further"
    organization_again = validate_success(
        client.get_organization(ctx["org_id"], ASSESSMENT_MANAGER), 200
    )
    assert organization_again == organization


def test_team_confirm_requires_an_unexpired_granted_qualification(client):
    """Expiry is observed by the confirmation that trips over it, and the
    state change survives the rejection.

    PRD section 3.2: "Expiry is observed lazily at the moment someone tries to
    confirm a team assignment that relies on it: if the current logical-clock
    date is strictly later than the qualification's `expires_on`, the
    qualification is moved `GRANTED → EXPIRED`, the assessor's
    `granted_qualification_count` is decremented by 1, and the confirmation
    request that observed the expiry is itself rejected with
    `ERR_QUALIFICATION_NOT_GRANTED`."

    Design: Difficulty/cross_entity_state_dependency/team_confirm_requires_an_unexpired_granted_qualification
    """
    ctx = fx.new_context(client, "ISO17025-EXP")
    fx.with_lead(ctx)
    fx.with_organization(ctx)
    fx.with_initial_cycle(ctx)
    assignment = fx.propose_team_member(
        client, ctx["app_id"], ctx["lead_id"], ROLE_TYPE_LEAD_ASSESSOR
    )
    fx.set_clock(client, "2030-08-10T00:00:00Z")

    response = client.confirm_team_assignment(assignment["id"], ASSESSMENT_MANAGER)

    validate_error(response, ERR_QUALIFICATION_NOT_GRANTED, 422)
    qualification = validate_success(
        client.get_qualification(ctx["lead_qualification_id"], SCHEME_MANAGER), 200
    )
    assert qualification["status"] == QUAL_EXPIRED
    assert qualification["expires_on"] == "2030-08-09"
    assert qualification["granted_on"] == "2026-08-10"
    assessor = fx.read_assessor(client, ctx["lead_id"])
    assert assessor["granted_qualification_count"] == 0
    assert assessor["qualification_status"] == QUALIFICATION_STATUS_QUALIFIED, (
        "A lapsed qualification does not itself move the assessor dimension"
    )
    stored = validate_success(
        client.get_team_assignment(assignment["id"], ASSESSMENT_MANAGER), 200
    )
    assert stored["status"] == TA_PROPOSED
    assert stored["conflict_verdict"] is None
    assert stored["conflict_checked_at"] is None
    assert fx.read_application(client, ctx["app_id"])["status"] == APP_SUBMITTED
    organization = validate_success(
        client.get_organization(ctx["org_id"], ASSESSMENT_MANAGER), 200
    )
    assert organization["status"] == ORG_APPLIED


def test_assignment_state_check_precedes_the_impartiality_restriction(client):
    """An already-confirmed assignment fails on its own status before the
    independence gates are ever consulted.

    PRD section 2.9: "The complete precedence order the server applies to any
    request is the following, and it is normative — an earlier rule always
    masks a later one, so a request that violates several rules reports only
    the earliest:"

    Design: Difficulty/priority_pair_validation_conflict/assignment_state_check_precedes_impartiality_restriction_on_confirm
    """
    ctx = fx.new_context(client, "ISO17025-PRI")
    fx.with_lead(ctx)
    fx.with_organization(ctx)
    fx.with_initial_cycle(ctx)
    fx.with_confirmed_team(ctx, ("lead",))
    assignment_id = ctx["ta_lead_id"]
    assignment_before = validate_success(
        client.get_team_assignment(assignment_id, ASSESSMENT_MANAGER), 200
    )
    application_before = fx.read_application(client, ctx["app_id"])
    get_success_data(
        client.create_declaration(
            ctx["lead_id"],
            f.declaration_payload(
                ctx["org_id"],
                RELATIONSHIP_EMPLOYMENT,
                "2019-03-01",
                detail="Quality manager, still on the payroll.",
            ),
            ASSESSMENT_MANAGER,
        )
    )

    response = client.confirm_team_assignment(assignment_id, ASSESSMENT_MANAGER)

    validate_error(response, ERR_INVALID_STATE_TRANSITION, 409)
    stored = validate_success(
        client.get_team_assignment(assignment_id, ASSESSMENT_MANAGER), 200
    )
    assert stored["status"] == TA_CONFIRMED
    assert stored["version"] == assignment_before["version"]
    application = fx.read_application(client, ctx["app_id"])
    assert application["status"] == APP_TEAM_ASSIGNED
    assert application["version"] == application_before["version"]
    assessor = fx.read_assessor(client, ctx["lead_id"])
    assert assessor["impartiality_status"] == IMPARTIALITY_RESTRICTED, (
        "The lower-priority rule really was violated at trigger time"
    )


def test_assessor_suspension_recuses_the_team_and_returns_the_cycle(client):
    """Suspending the sole lead assessor cascades to the assignment and then
    pushes the cycle back to ``SUBMITTED``.

    PRD section 3.2: "Moving a `QUALIFIED` assessor to `SUSPENDED` requires a
    `reason`, which is written to `suspension_reason` (1 to 300 characters),
    and triggers a two-hop cascade: every team assignment of that assessor in
    `PROPOSED` becomes `REJECTED` and every one in `CONFIRMED` becomes
    `RECUSED`, each carrying the `recusal_reason` `assessor suspended`; then,
    for each assignment that just became `RECUSED` while holding `role_type`
    `LEAD_ASSESSOR` on a cycle in `TEAM_ASSIGNED` with no other `CONFIRMED`
    lead assessor remaining, that cycle is pushed back from `TEAM_ASSIGNED`
    to `SUBMITTED`."

    Design: Difficulty/transitive_cascade/assessor_suspension_recuses_team_then_returns_application_to_submitted
    """
    ctx = fx.new_context(client, "ISO17025-SUS")
    fx.with_lead(ctx)
    fx.with_organization(ctx)
    fx.with_initial_cycle(ctx)
    fx.with_confirmed_team(ctx, ("lead",))

    response = client.set_assessor_status(
        ctx["lead_id"],
        f.assessor_status_payload(QUALIFICATION_STATUS_SUSPENDED, SUSPENSION_REASON),
        SCHEME_MANAGER,
    )

    assessor = validate_success(response, 200)
    assert assessor["qualification_status"] == QUALIFICATION_STATUS_SUSPENDED
    assert assessor["suspension_reason"] == SUSPENSION_REASON
    assert assessor["impartiality_status"] == IMPARTIALITY_SCREENED, (
        "The two dimensions are independent"
    )
    assignment = validate_success(
        client.get_team_assignment(ctx["ta_lead_id"], ASSESSMENT_MANAGER), 200
    )
    assert assignment["status"] == TA_RECUSED
    assert assignment["recusal_reason"] == RECUSAL_REASON_ASSESSOR_SUSPENDED
    assert fx.read_application(client, ctx["app_id"])["status"] == APP_SUBMITTED
    organization = validate_success(
        client.get_organization(ctx["org_id"], ASSESSMENT_MANAGER), 200
    )
    assert organization["status"] == ORG_UNDER_ASSESSMENT, (
        "Losing a lead assessor is a team-assembly setback, not a withdrawal"
    )
    assert assessor["granted_qualification_count"] == 1
    qualification = validate_success(
        client.get_qualification(ctx["lead_qualification_id"], SCHEME_MANAGER), 200
    )
    assert qualification["status"] == QUAL_GRANTED
    assert_capacity_ledger(assessor, committed=0, available=20)
