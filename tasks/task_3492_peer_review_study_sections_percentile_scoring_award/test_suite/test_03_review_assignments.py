"""Review-side mechanics: assignment gates (section recruiting, COI,
capacity, meeting proximity), the quorum-driven REFERRED<->UNDER_REVIEW
cycle, the withdraw cascade, and terminal-state lockdowns."""
import pytest

from test_helpers import (
    api_client,
    fixtures,
    factories,
    TEST_USERS,
    make_applicant_headers,
    make_reviewer_headers,
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
)

_SRO = TEST_USERS["sro_headers"]


def test_application_quorum_cycle_referred_under_review():
    """PRD §3.4: "Creating an assignment while the application is `REFERRED` flips it automatically from `REFERRED` to `UNDER_REVIEW` and increments the application's `version` — the first assignment is what puts an application under review."
    PRD §3.4: "an application must hold at least two live assignments to remain under review, so when a decline drops an `UNDER_REVIEW` application below two live assignments, the application automatically falls back from `UNDER_REVIEW` to `REFERRED`, increments its `version`, and must attract new assignments before it can be scored."

    Design: Difficulty/non_linear_state_machine/application_quorum_cycle_referred_under_review
    """
    ctx = fixtures.make_review_context()
    section = fixtures.make_study_section(name="Section C")
    pi_a = fixtures.make_applicant()
    app = fixtures.create_referred_application(
        ctx["foa"]["id"], ctx["institution"]["id"], pi_a["id"],
        section["id"], ctx["institute"]["id"], title="Cycle app")
    r1 = fixtures.make_active_reviewer(ctx["reviewer_institution"]["id"])
    r2 = fixtures.make_active_reviewer(ctx["reviewer_institution"]["id"])
    r3 = fixtures.make_active_reviewer(ctx["reviewer_institution"]["id"])
    a_1 = fixtures.assign_reviewer(app["id"], r1["id"], "PRIMARY")
    a_2 = fixtures.assign_reviewer(app["id"], r2["id"], "SECONDARY")
    fixtures.respond_to_assignment(a_1["id"], r1["id"], "ACCEPT")
    fixtures.respond_to_assignment(a_2["id"], r2["id"], "ACCEPT")

    mid0 = fixtures.refresh_application(app["id"])
    assert mid0["status"] == "UNDER_REVIEW"
    assert mid0["live_assignment_count"] == 2

    declined = fixtures.respond_to_assignment(a_1["id"], r1["id"], "DECLINE")
    assert declined["status"] == "DECLINED"
    assert fixtures.refresh_reviewer(r1["id"])["active_assignment_count"] == 0
    mid1 = fixtures.refresh_application(app["id"])
    assert mid1["status"] == "REFERRED", (
        "dropping below two live assignments must fall back to REFERRED"
    )
    assert mid1["live_assignment_count"] == 1

    fixtures.assign_reviewer(app["id"], r3["id"], "PRIMARY")
    end = fixtures.refresh_application(app["id"])
    assert end["status"] == "UNDER_REVIEW", (
        "a fresh assignment on the REFERRED application puts it back UNDER_REVIEW"
    )
    assert end["live_assignment_count"] == 2


def test_withdraw_cascade_releases_assignments_and_reviewer_capacity():
    """PRD §3.2: "withdrawing from `UNDER_REVIEW` first cancels every live assignment — each assignment in `ASSIGNED`, `ACCEPTED`, or `CRITIQUE_SUBMITTED` status moves to `CANCELLED` — then decrements each cancelled assignment's reviewer `active_assignment_count` (only for assignments that were `ASSIGNED` or `ACCEPTED`, since a submitted critique has already freed the reviewer's active slot), and finally decrements the section's `assigned_application_count`."

    Design: Difficulty/transitive_cascade/withdraw_cascade_releases_assignments_and_reviewer_capacity
    """
    ctx = fixtures.make_review_context()
    section = fixtures.make_study_section(name="Section WD")
    pi_a = fixtures.make_applicant()
    app = fixtures.create_referred_application(
        ctx["foa"]["id"], ctx["institution"]["id"], pi_a["id"],
        section["id"], ctx["institute"]["id"], title="Withdraw app")
    panel = fixtures.assign_panel(app["id"], ctx["reviewer_institution"]["id"])
    a_1, a_2 = panel["assignments"]
    r1, r2 = panel["reviewers"]
    assert fixtures.refresh_application(app["id"])["status"] == "UNDER_REVIEW"
    assert fixtures.refresh_study_section(section["id"])["assigned_application_count"] == 1

    resp = api_client.withdraw_application(app["id"], make_applicant_headers(pi_a["id"]))
    assert validate_success(resp, 200)["status"] == "WITHDRAWN"

    assert fixtures.refresh_assignment(a_1["id"])["status"] == "CANCELLED"
    assert fixtures.refresh_assignment(a_2["id"])["status"] == "CANCELLED"
    assert fixtures.refresh_reviewer(r1["id"])["active_assignment_count"] == 0
    assert fixtures.refresh_reviewer(r2["id"])["active_assignment_count"] == 0
    assert fixtures.refresh_study_section(section["id"])["assigned_application_count"] == 0


def test_assignment_requires_section_recruiting():
    """PRD §3.4: "The reviewer must be `ACTIVE` (`ERR_REVIEWER_NOT_ACTIVE`), and the application's study section must still be `RECRUITING` (`ERR_SECTION_NOT_RECRUITING`)."

    Design: Difficulty/cross_entity_state_dependency/assignment_requires_section_recruiting
    """
    ctx = fixtures.make_review_context()
    section = fixtures.make_study_section(name="Section SG")
    pi_a = fixtures.make_applicant()
    app = fixtures.create_referred_application(
        ctx["foa"]["id"], ctx["institution"]["id"], pi_a["id"],
        section["id"], ctx["institute"]["id"], title="Section gate app")
    r1 = fixtures.make_active_reviewer(ctx["reviewer_institution"]["id"])
    fixtures.assign_reviewer(app["id"], r1["id"], "PRIMARY")
    fixtures.convene_section(section["id"])  # section now MEETING_HELD

    r2 = fixtures.make_active_reviewer(ctx["reviewer_institution"]["id"])
    resp = api_client.create_assignment(
        factories.create_assignment_payload(app["id"], r2["id"], "SECONDARY"), _SRO)
    validate_error(resp, ApiErrorId.ERR_SECTION_NOT_RECRUITING)

    data, meta = validate_paginated(
        api_client.list_assignments(_SRO, params={"application_id": app["id"]}))
    assert meta["total_count"] == 1 and len(data) == 1, (
        "a rejected assignment must not create anything (no partial creation)"
    )


def test_reviewer_meeting_proximity_inclusive_buffer():
    """PRD §3.4: "for each of the reviewer's live assignments to an application of a *different* study section, if the absolute difference between the two sections' `meeting_date` values is within seven days — inclusive, so exactly seven days apart is a conflict while seven days and one second is not — creation is rejected with `ERR_MEETING_PROXIMITY_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/reviewer_meeting_proximity_inclusive_buffer
    """
    ctx = fixtures.make_review_context()
    sec_a = fixtures.make_study_section(name="Section A", meeting_date="2027-03-01T00:00:00Z")
    sec_b = fixtures.make_study_section(name="Section B", meeting_date="2027-03-08T00:00:00Z")
    sec_c = fixtures.make_study_section(name="Section C", meeting_date="2027-03-09T00:00:00Z")
    apps = []
    for i, sec in enumerate((sec_a, sec_b, sec_c), start=1):
        pi = fixtures.make_applicant()
        apps.append(fixtures.create_referred_application(
            ctx["foa"]["id"], ctx["institution"]["id"], pi["id"],
            sec["id"], ctx["institute"]["id"], title=f"P{i}"))
    app_a, app_b, app_c = apps
    rx = fixtures.make_active_reviewer(ctx["reviewer_institution"]["id"])
    fixtures.assign_reviewer(app_a["id"], rx["id"], "PRIMARY")

    # Section B meets exactly 7 days after section A: inclusive buffer -> conflict.
    conflict = api_client.create_assignment(
        factories.create_assignment_payload(app_b["id"], rx["id"], "PRIMARY"), _SRO)
    validate_error(conflict, ApiErrorId.ERR_MEETING_PROXIMITY_CONFLICT)

    # Section C meets 8 days after section A: outside the buffer -> allowed.
    ok = api_client.create_assignment(
        factories.create_assignment_payload(app_c["id"], rx["id"], "PRIMARY"), _SRO)
    assert validate_success(ok, 201)["status"] == "ASSIGNED"
    assert fixtures.refresh_reviewer(rx["id"])["active_assignment_count"] == 2


def test_reviewer_declined_terminal_lockdown():
    """PRD §3.4: "The invited reviewer then answers for themselves — the roster respond action is owner-scoped — with a `decision` of `ACCEPT` moving them to `ACTIVE`, or `DECLINE` moving them to the terminal `DECLINED` state; responding from any status other than `INVITED` is rejected with `ERR_REVIEWER_INVALID_STATE`."

    Design: Corner/state_machines/reviewer_declined_terminal_lockdown
    """
    inst = fixtures.make_institution(name="Other College")
    rx = fixtures.make_reviewer(inst["id"], full_name="Rev X")
    fixtures.respond_to_invitation(rx["id"], "DECLINE")
    resp = api_client.reviewer_respond(
        rx["id"], factories.reviewer_respond_payload("ACCEPT"),
        make_reviewer_headers(rx["id"]))
    validate_error(resp, ApiErrorId.ERR_REVIEWER_INVALID_STATE)
    assert fixtures.refresh_reviewer(rx["id"])["status"] == "DECLINED"


def test_critique_before_convene_rejected():
    """PRD §3.5: "With the meeting held, each assigned reviewer submits a critique on their own `ACCEPTED` assignment — submitting from any other assignment state is rejected with `ERR_ASSIGNMENT_INVALID_STATE`, and submitting while the application's section is not `MEETING_HELD` is rejected with `ERR_SECTION_NOT_IN_MEETING`."

    Design: Corner/state_machines/critique_before_convene_rejected
    """
    ctx = fixtures.make_review_context()
    section = fixtures.make_study_section(name="Section CR")
    pi_a = fixtures.make_applicant()
    app = fixtures.create_referred_application(
        ctx["foa"]["id"], ctx["institution"]["id"], pi_a["id"],
        section["id"], ctx["institute"]["id"], title="Critique app")
    panel = fixtures.assign_panel(app["id"], ctx["reviewer_institution"]["id"])
    a_1 = panel["assignments"][0]
    r1 = panel["reviewers"][0]
    # Section deliberately never convened.
    resp = api_client.submit_critique(
        a_1["id"], factories.critique_payload(overall_impact_score=3),
        make_reviewer_headers(r1["id"]))
    validate_error(resp, ApiErrorId.ERR_SECTION_NOT_IN_MEETING)
    assert fixtures.refresh_assignment(a_1["id"])["status"] == "ACCEPTED"


def test_convene_without_under_review_applications_rejected():
    """PRD §3.5: "When at least one application assigned to a `RECRUITING` section has reached `UNDER_REVIEW`, the SRO convenes the review meeting, moving the section from `RECRUITING` to `MEETING_HELD`; convening a section without an under-review application is rejected with `ERR_SECTION_NOT_CONVENABLE`."

    Design: Corner/state_machines/convene_without_under_review_applications_rejected
    """
    section = fixtures.make_study_section(name="Empty Section")
    resp = api_client.convene_study_section(section["id"], _SRO)
    validate_error(resp, ApiErrorId.ERR_SECTION_NOT_CONVENABLE)
    assert fixtures.refresh_study_section(section["id"])["status"] == "RECRUITING"


def test_release_before_convene_rejected():
    """PRD §3.5: "Releasing scores moves the section from `MEETING_HELD` to the terminal `SCORES_RELEASED` state; releasing from any other state is rejected with `ERR_SECTION_NOT_RELEASABLE`."

    Design: Corner/state_machines/release_before_convene_rejected
    """
    section = fixtures.make_study_section(name="Early Section")
    resp = api_client.release_section_scores(section["id"], _SRO)
    validate_error(resp, ApiErrorId.ERR_SECTION_NOT_RELEASABLE)
    assert fixtures.refresh_study_section(section["id"])["status"] == "RECRUITING"


def test_decline_after_decline_rejected():
    """PRD §3.4: "from `ASSIGNED`, `ACCEPT` moves the assignment to `ACCEPTED`, while `DECLINE` from either `ASSIGNED` or `ACCEPTED` moves it to the terminal `DECLINED` state; any other respond attempt is rejected with `ERR_ASSIGNMENT_INVALID_STATE`."

    Design: Corner/state_machines/decline_after_decline_rejected
    """
    ctx = fixtures.make_review_context()
    section = fixtures.make_study_section(name="Section D")
    pi_a = fixtures.make_applicant()
    app = fixtures.create_referred_application(
        ctx["foa"]["id"], ctx["institution"]["id"], pi_a["id"],
        section["id"], ctx["institute"]["id"], title="Decline app")
    r1 = fixtures.make_active_reviewer(ctx["reviewer_institution"]["id"])
    a_1 = fixtures.assign_reviewer(app["id"], r1["id"], "PRIMARY")
    fixtures.respond_to_assignment(a_1["id"], r1["id"], "DECLINE")
    assert fixtures.refresh_reviewer(r1["id"])["active_assignment_count"] == 0

    resp = api_client.assignment_respond(
        a_1["id"], factories.assignment_respond_payload("DECLINE"),
        make_reviewer_headers(r1["id"]))
    validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_INVALID_STATE)
    assert fixtures.refresh_reviewer(r1["id"])["active_assignment_count"] == 0, (
        "reviewer capacity must be released exactly once"
    )


def test_coi_three_arms_rejected():
    """PRD §3.4: "Conflict-of-interest screening then rejects three pairings: the reviewer's `institution_id` matching the application's `institution_id` (`ERR_COI_INSTITUTION_MATCH`); the reviewer appearing in the application's `excluded_reviewer_ids` (`ERR_REVIEWER_EXCLUDED`); and the application appearing in the reviewer's `declared_conflicts` (`ERR_REVIEWER_SELF_DECLARED_CONFLICT`)."

    Design: Corner/validations/coi_three_arms_rejected
    """
    ctx = fixtures.make_review_context()
    section = fixtures.make_study_section(name="Section COI")
    pi_a = fixtures.make_applicant()
    # Arm 1: reviewer affiliated with the applicant's own institution.
    r1 = fixtures.make_active_reviewer(ctx["institution"]["id"], full_name="Rev Same")
    # Arm 2: reviewer named in the application's excluded_reviewer_ids.
    r2 = fixtures.make_active_reviewer(ctx["reviewer_institution"]["id"], full_name="Rev Excluded")
    # Arm 3: reviewer who self-declared a conflict with this application.
    r3 = fixtures.make_active_reviewer(ctx["reviewer_institution"]["id"], full_name="Rev Declared")
    app = fixtures.create_referred_application(
        ctx["foa"]["id"], ctx["institution"]["id"], pi_a["id"],
        section["id"], ctx["institute"]["id"], title="COI app",
        excluded_reviewer_ids=[r2["id"]])
    fixtures.declare_conflict(r3["id"], app["id"])

    resp1 = api_client.create_assignment(
        factories.create_assignment_payload(app["id"], r1["id"], "PRIMARY"), _SRO)
    validate_error(resp1, ApiErrorId.ERR_COI_INSTITUTION_MATCH)
    resp2 = api_client.create_assignment(
        factories.create_assignment_payload(app["id"], r2["id"], "PRIMARY"), _SRO)
    validate_error(resp2, ApiErrorId.ERR_REVIEWER_EXCLUDED)
    resp3 = api_client.create_assignment(
        factories.create_assignment_payload(app["id"], r3["id"], "PRIMARY"), _SRO)
    validate_error(resp3, ApiErrorId.ERR_REVIEWER_SELF_DECLARED_CONFLICT)

    data, meta = validate_paginated(
        api_client.list_assignments(_SRO, params={"application_id": app["id"]}))
    assert meta["total_count"] == 0 and data == [], "no assignment may be created"


def test_reviewer_capacity_four_then_five_rejected():
    """PRD §3.4: "A reviewer may hold at most four active assignments — assignments in `ASSIGNED` or `ACCEPTED` status; when the reviewer already holds four, creation is rejected with `ERR_REVIEWER_CAPACITY_EXCEEDED`, so the boundary is inclusive at the limit: the fourth active assignment is allowed and the fifth is refused."
    PRD §3.4: "Co-review within the same section is normal panel service and is exempt from this check."

    Design: Corner/validations/reviewer_capacity_four_then_five_rejected
    """
    ctx = fixtures.make_review_context()
    section = fixtures.make_study_section(name="Section CAP")
    apps = []
    for i in range(1, 6):
        pi = fixtures.make_applicant()
        apps.append(fixtures.create_referred_application(
            ctx["foa"]["id"], ctx["institution"]["id"], pi["id"],
            section["id"], ctx["institute"]["id"], title=f"C{i}"))
    rc = fixtures.make_active_reviewer(ctx["reviewer_institution"]["id"], full_name="Rev Cap")
    for app in apps[:4]:
        # Same section for every application: the proximity check is exempt.
        fixtures.assign_reviewer(app["id"], rc["id"], "PRIMARY")
    assert fixtures.refresh_reviewer(rc["id"])["active_assignment_count"] == 4

    resp = api_client.create_assignment(
        factories.create_assignment_payload(apps[4]["id"], rc["id"], "PRIMARY"), _SRO)
    validate_error(resp, ApiErrorId.ERR_REVIEWER_CAPACITY_EXCEEDED)
    assert fixtures.refresh_reviewer(rc["id"])["active_assignment_count"] == 4


def test_score_out_of_range_rejected():
    """PRD §3.5: "The critique supplies six integer scores, each from 1 to 9 (`ERR_VALIDATION` otherwise): `significance_score`, `innovation_score`, `approach_score`, `investigator_score`, `environment_score`, and `overall_impact_score`."

    Design: Corner/errors/score_out_of_range_rejected
    """
    ctx = fixtures.make_review_context()
    section = fixtures.make_study_section(name="Section SC")
    pi_a = fixtures.make_applicant()
    app = fixtures.create_referred_application(
        ctx["foa"]["id"], ctx["institution"]["id"], pi_a["id"],
        section["id"], ctx["institute"]["id"], title="Score app")
    r1 = fixtures.make_active_reviewer(ctx["reviewer_institution"]["id"])
    a_1 = fixtures.assign_reviewer(app["id"], r1["id"], "PRIMARY")
    fixtures.respond_to_assignment(a_1["id"], r1["id"], "ACCEPT")
    fixtures.convene_section(section["id"])

    resp = api_client.submit_critique(
        a_1["id"], factories.critique_payload(overall_impact_score=10),
        make_reviewer_headers(r1["id"]))
    validate_error(resp, ApiErrorId.ERR_VALIDATION)
    assert fixtures.refresh_assignment(a_1["id"])["status"] == "ACCEPTED"
