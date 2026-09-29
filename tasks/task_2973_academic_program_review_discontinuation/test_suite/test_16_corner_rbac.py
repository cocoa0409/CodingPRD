"""Corner cases of the §2.1 identity/role surface and the §2.10 refusal order."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prd_bench_local_runner.testing import (
    build_user_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions, constants, factories, fixtures
from test_helpers.api_client import allow_blank_header_values
from test_helpers.api_errors import *  # noqa: F401,F403
from test_helpers.test_users import (
    PROVOST_PROPOSER_USER_ID,
    PROVOST_RATIFIER_USER_ID,
    make_external_reviewer_headers,
    make_headers_with_blank_role,
    make_headers_with_blank_user_id,
    make_headers_with_whitespace_role,
    make_headers_with_whitespace_user_id,
    make_hr_partner_headers,
    make_program_chair_headers,
    make_provost_headers,
    make_provost_proposer_headers,
    make_provost_ratifier_headers,
    make_registrar_headers,
    make_review_coordinator_headers,
)


def test_blank_and_unknown_identity_headers_are_rejected_before_anything_else(api):
    """Whitespace is not a credential, and neither check ever reaches the path.

    §2.1 and §2.10 checks 1-2: an absent, empty or whitespace-only ``X-User-ID``
    or ``X-User-Role`` is ``ERR_MISSING_AUTH_HEADER`` (401) — a whitespace-only
    role is treated as absent rather than as a value that then fails the
    role-membership test — while a role name outside the six declared ones is
    ``ERR_INVALID_ROLE`` (401). Both rank above path resolution (check 7), so
    every probe aims at an id that resolves to nothing and still answers 401
    rather than 404, and above the endpoint's role list (check 3), so an unknown
    role never earns a 403.

    Design: Corner/rbac/blank_and_unknown_identity_headers_are_rejected_before_anything_else
    """
    coordinator = make_review_coordinator_headers()
    validate_success(api.set_clock(constants.CLOCK_STARTUP_DEFAULT, coordinator))

    missing_id = constants.UNKNOWN_UUID

    # check 1 — the role header is present but carries no value.
    validate_error(
        api.get_program(missing_id, make_headers_with_blank_role("coordinator-1")),
        ERR_MISSING_AUTH_HEADER,
        401,
    )
    # check 1 outranks check 2 — three spaces is an absent role, not an unknown one.
    with allow_blank_header_values():
        whitespace_role = api.get_program(
            missing_id, make_headers_with_whitespace_role("coordinator-1")
        )
    validate_error(whitespace_role, ERR_MISSING_AUTH_HEADER, 401)
    # check 1 on the identity half of the pair, with a valid and permitted role.
    validate_error(
        api.get_program(missing_id, make_headers_with_blank_user_id("ReviewCoordinator")),
        ERR_MISSING_AUTH_HEADER,
        401,
    )
    with allow_blank_header_values():
        whitespace_user_id = api.get_program(
            missing_id, make_headers_with_whitespace_user_id("ReviewCoordinator")
        )
    validate_error(whitespace_user_id, ERR_MISSING_AUTH_HEADER, 401)

    # check 2 — a syntactically fine role that is not one of the six.
    validate_error(
        api.get_program(missing_id, build_user_headers("dean-1", "Dean")),
        ERR_INVALID_ROLE,
        401,
    )
    # check 2 — the six role names are matched exactly as §2.1 spells them.
    validate_error(
        api.get_program(missing_id, build_user_headers("registrar-1", "registrar")),
        ERR_INVALID_ROLE,
        401,
    )

    # A write refused at check 1 leaves nothing behind.
    validate_error(
        api.create_program(
            factories.program_payload(
                code="HIST-BA", name="History BA", department_code="HIST"
            ),
            make_headers_with_blank_role(""),
        ),
        ERR_MISSING_AUTH_HEADER,
        401,
    )
    _rows, meta = validate_paginated(api.list_programs(coordinator))
    assert meta["total_count"] == 0, "a request refused at check 1 must create nothing"


def test_no_role_may_perform_another_roles_exclusive_write(api):
    """Six roles, six exclusive surfaces, and no seniority between them.

    §2.10 check 3: a role that is not on the endpoint's authorised list is
    refused with ``ERR_ROLE_NOT_PERMITTED`` (403) whatever the payload says. The
    decision probe carries an otherwise flawless body — a real cycle, an outcome
    the band supports and an ``expected_cycle_version`` echoed straight from the
    cycle — so the caller's role is the only possible reason for the refusal.
    §2.4 then supplies the negative: a refused write is not a mutation, so the
    program's ``version`` is exactly where the last accepted write left it.

    Design: Corner/rbac/no_role_may_perform_another_roles_exclusive_write
    """
    coordinator = make_review_coordinator_headers()
    fixtures.set_clock(api, constants.CLOCK_STARTUP_DEFAULT)
    program = fixtures.create_program(
        api, code="HIST-BA", name="History BA", department_code="HIST"
    )
    program_id = program["id"]
    cycle = fixtures.open_cycle(api, program_id)

    # §3.3 already bumped the program once by opening the cycle; the counter the
    # refusals must not move is the one standing after that accepted write.
    before = fixtures.read_program(api, program_id)
    cycle_version = fixtures.read_cycle(api, cycle["id"])["version"]

    # POST /provost/academic-programs belongs to ReviewCoordinator alone.
    validate_error(
        api.create_program(
            factories.program_payload(
                code="PHIL-BA", name="Philosophy BA", department_code="PHIL"
            ),
            make_provost_headers("provost-1"),
        ),
        ERR_ROLE_NOT_PERMITTED,
        403,
    )
    # Metric snapshots belong to ReviewCoordinator.
    validate_error(
        api.create_metric_snapshot(
            program_id,
            factories.metric_snapshot_payload(term_code="2024FA", term_index=1),
            make_hr_partner_headers(),
        ),
        ERR_ROLE_NOT_PERMITTED,
        403,
    )
    # Proposing a decision is the Provost's exclusive act (§3.6).
    validate_error(
        api.create_decision_record(
            cycle["id"],
            factories.decision_payload(
                outcome="CONTINUE",
                expected_cycle_version=cycle_version,
                rationale="Looks fine to me.",
            ),
            make_registrar_headers(),
        ),
        ERR_ROLE_NOT_PERMITTED,
        403,
    )
    # The catalog axis belongs to the Registrar (§2.6).
    validate_error(
        api.set_catalog_status(
            program_id,
            factories.catalog_status_payload(
                "MARKETING_SUPPRESSED", "Coordinators do not run the catalog."
            ),
            coordinator,
        ),
        ERR_ROLE_NOT_PERMITTED,
        403,
    )
    # Faculty appointments belong to the HRPartner (§3.11).
    validate_error(
        api.create_faculty_appointment(
            program_id,
            factories.faculty_appointment_payload(
                faculty_number="F-HIST-1", fte=1.00, annual_salary_cents=12000000
            ),
            make_registrar_headers(),
        ),
        ERR_ROLE_NOT_PERMITTED,
        403,
    )
    # The self-study is the ProgramChair's document (§3.3).
    validate_error(
        api.create_self_study(
            cycle["id"],
            factories.self_study_payload(narrative="Not my job."),
            coordinator,
        ),
        ERR_ROLE_NOT_PERMITTED,
        403,
    )
    # The portfolio list is not on the ExternalReviewer's surface (§4).
    validate_error(
        api.list_programs(make_external_reviewer_headers("reviewer-1")),
        ERR_ROLE_NOT_PERMITTED,
        403,
    )
    # The compliance sweep belongs to ReviewCoordinator (§3.7).
    validate_error(
        api.run_compliance_sweep(make_hr_partner_headers()),
        ERR_ROLE_NOT_PERMITTED,
        403,
    )

    after = fixtures.read_program(api, program_id)
    assert after["version"] == before["version"], (
        "not one of the eight refused writes may bump AcademicProgram.version"
    )
    assertions.assert_axes(after, "UNDER_REVIEW", "LISTED")
    assert after["snapshot_count"] == 0
    assertions.assert_decimal_equals(
        after["faculty_fte_baseline"], 0.00, "program.faculty_fte_baseline"
    )
    _rows, meta = validate_paginated(api.list_programs(coordinator))
    assert meta["total_count"] == 1, "no PHIL-BA program was created"


def test_action_scoped_grants_split_one_transitions_endpoint_between_roles(api):
    """One URL, two owners: the ``action`` in the body decides who may call it.

    §2.1's action-scoped clause and §2.10 check 3 read together: a role that is
    on the endpoint's list but does not own the requested ``action`` is refused
    with ``ERR_ROLE_NOT_PERMITTED`` (403) exactly like a role that is not on the
    list at all. Self-study transitions split SUBMIT (chair) from RETURN/ACCEPT
    (coordinator), decision transitions split RATIFY/RESCIND (provost) from
    EFFECTUATE/EVALUATE_IMPROVEMENT (coordinator), and plan transitions split
    SUBMIT (chair) from APPROVE/RETURN (provost) from ACTIVATE (coordinator).
    Because check 3 outranks every state precondition (checks 11-13), the
    EFFECTUATE probe aimed at a merely PROPOSED decision answers 403 on the role
    rather than 409 on the state.

    Design: Corner/rbac/action_scoped_grants_split_one_transitions_endpoint_between_roles
    """
    coordinator = make_review_coordinator_headers()
    ratifier = make_provost_ratifier_headers()
    fixtures.set_clock(api, constants.CLOCK_STARTUP_DEFAULT)
    program = fixtures.create_nonviable_program(
        api, code="HIST-BA", name="History BA", department_code="HIST"
    )
    program_id = program["id"]
    chair = make_program_chair_headers(program_id)
    cycle = fixtures.open_cycle(api, program_id)
    self_study = fixtures.create_self_study(api, cycle["id"], program_id)

    # SUBMIT is the chair's action even though the coordinator owns the endpoint's
    # other two actions.
    validate_error(
        api.transition_self_study(
            self_study["id"], factories.self_study_submit_payload(), coordinator
        ),
        ERR_ROLE_NOT_PERMITTED,
        403,
    )
    validate_success(
        api.transition_self_study(
            self_study["id"], factories.self_study_submit_payload(), chair
        )
    )
    # ...and ACCEPT is not the chair's, even on his own program's document.
    validate_error(
        api.transition_self_study(
            self_study["id"], factories.self_study_accept_payload(), chair
        ),
        ERR_ROLE_NOT_PERMITTED,
        403,
    )
    validate_success(
        api.transition_self_study(
            self_study["id"], factories.self_study_accept_payload(), coordinator
        )
    )

    reviewer = fixtures.register_reviewer(api)
    visit = fixtures.schedule_visit(api, cycle["id"], reviewer["id"])
    fixtures.set_clock(api, fixtures.CLOCK_AFTER_VISIT)
    fixtures.complete_visit(api, visit["id"])
    fixtures.file_report(api, visit["id"], reviewer["id"])
    fixtures.file_program_response(api, cycle["id"], program_id)
    fixtures.set_clock(api, fixtures.CLOCK_AT_RATIFICATION)

    ctx = fixtures.ReviewContext(
        program=fixtures.read_program(api, program_id),
        cycle=fixtures.read_cycle(api, cycle["id"]),
    )
    decision = fixtures.propose_decision(api, ctx, "DISCONTINUATION")

    # RATIFY belongs to the Provost, not to the coordinator who owns EFFECTUATE.
    validate_error(
        api.transition_decision_record(
            decision["id"], factories.ratify_payload(), coordinator
        ),
        ERR_ROLE_NOT_PERMITTED,
        403,
    )
    # EFFECTUATE belongs to the coordinator; check 3 answers before the state
    # check that would have complained the decision is only PROPOSED.
    validate_error(
        api.transition_decision_record(
            decision["id"], factories.effectuate_payload(), ratifier
        ),
        ERR_ROLE_NOT_PERMITTED,
        403,
    )
    fixtures.ratify_decision(api, ctx)

    plan = fixtures.file_plan(
        api,
        ctx,
        last_admit_term_index=3,
        first_teach_out_term_index=4,
        final_award_term_index=5,
    )

    # The plan endpoint is split three ways: SUBMIT chair, APPROVE provost,
    # ACTIVATE coordinator.
    validate_error(
        api.transition_teach_out_plan(
            plan["id"], factories.plan_transition_payload("SUBMIT"), ratifier
        ),
        ERR_ROLE_NOT_PERMITTED,
        403,
    )
    fixtures.submit_plan(api, ctx)
    validate_error(
        api.transition_teach_out_plan(
            plan["id"], factories.plan_transition_payload("APPROVE"), chair
        ),
        ERR_ROLE_NOT_PERMITTED,
        403,
    )
    validate_error(
        api.transition_teach_out_plan(
            plan["id"], factories.plan_transition_payload("ACTIVATE"), ratifier
        ),
        ERR_ROLE_NOT_PERMITTED,
        403,
    )

    plan_now = fixtures.read_plan(api, plan["id"])
    assert plan_now["state"] == "SUBMITTED", "no refused transition may move the plan"
    assert plan_now["approved_at"] is None
    assert plan_now["activated_at"] is None

    decision_now = fixtures.read_decision(api, decision["id"])
    assert decision_now["state"] == "RATIFIED"
    assert decision_now["effectuated_at"] is None
    assert decision_now["proposed_by_user_id"] == PROVOST_PROPOSER_USER_ID
    assert decision_now["ratified_by_user_id"] == PROVOST_RATIFIER_USER_ID


def test_the_same_provost_cannot_propose_and_ratify(api):
    """Segregation of duties outranks the state machine in both directions.

    §2.10 check 6: ``RATIFY`` requested by the same ``X-User-ID`` that proposed
    the decision is ``ERR_SEGREGATION_OF_DUTIES`` (403), and the PRD places that
    check above every state precondition. The test reads the ordering twice — the
    proposer is refused on duties while the decision is still PROPOSED and
    ratifiable, and refused on duties again once the decision is RATIFIED and no
    longer ratifiable, where a *third* provost identity gets the state answer
    ``ERR_DECISION_STATE_INVALID`` (409) instead.

    Design: Corner/rbac/the_same_provost_cannot_propose_and_ratify
    """
    proposer = make_provost_proposer_headers()
    ctx = fixtures.carry_cycle_to_response_submitted(
        api, code="HIST-BA", name="History BA", department_code="HIST"
    )
    fixtures.set_clock(api, fixtures.CLOCK_AT_RATIFICATION)
    decision = fixtures.propose_decision(api, ctx, "DISCONTINUATION")
    assert decision["state"] == "PROPOSED"
    assert decision["proposed_by_user_id"] == PROVOST_PROPOSER_USER_ID

    # The proposer is the one identity that may not ratify.
    validate_error(
        api.transition_decision_record(
            decision["id"], factories.ratify_payload("I approve my own work."), proposer
        ),
        ERR_SEGREGATION_OF_DUTIES,
        403,
    )

    ratified = validate_success(
        api.transition_decision_record(
            decision["id"],
            factories.ratify_payload("The second provost ratifies."),
            make_provost_ratifier_headers(),
        )
    )
    assert ratified["state"] == "RATIFIED"
    assert ratified["ratified_by_user_id"] == PROVOST_RATIFIER_USER_ID
    assert ratified["ratification_note"] == "The second provost ratifies."
    assertions.assert_instant_equals(
        ratified["ratified_at"], fixtures.CLOCK_AT_RATIFICATION, "decision.ratified_at"
    )
    minted = fixtures.list_notifications(api, decision["id"])
    assert len(minted) == 2, "§3.6 hop 3 mints exactly two notices"
    assert sorted(n["agency_type"] for n in minted) == ["ACCREDITOR", "STATE_AGENCY"]

    # Now the decision is un-ratifiable AND the caller is the proposer: check 6
    # still answers before check 12.
    validate_error(
        api.transition_decision_record(
            decision["id"], factories.ratify_payload("Once more."), proposer
        ),
        ERR_SEGREGATION_OF_DUTIES,
        403,
    )
    # A third provost, with clean hands, gets the state answer instead.
    validate_error(
        api.transition_decision_record(
            decision["id"],
            factories.ratify_payload("A third provost tries."),
            make_provost_headers("provost-third"),
        ),
        ERR_DECISION_STATE_INVALID,
        409,
    )

    final = fixtures.read_decision(api, decision["id"])
    assert final["state"] == "RATIFIED"
    assert final["ratified_by_user_id"] == PROVOST_RATIFIER_USER_ID
    assert final["ratification_note"] == "The second provost ratifies."


def test_a_chair_and_a_reviewer_are_confined_to_their_own_records(api):
    """The two entity-backed roles carry a scope, not just a permission.

    §2.1 binds a ``ProgramChair``'s ``X-User-ID`` to a program id and an
    ``ExternalReviewer``'s to a reviewer id, and §2.10 checks 4-5 turn that
    binding into ``ERR_NOT_PROGRAM_OWNER`` (403) and
    ``ERR_NOT_ASSIGNED_REVIEWER`` (403). Both rank above existence (checks 7-8),
    schema (check 9) and state (checks 11-13), so the neighbouring chair's PATCH
    of an already-accepted self-study answers on ownership rather than on the
    document's state, and his POST to a cycle that already holds a self-study
    answers on ownership rather than on the duplicate. The same probes issued by
    the rightful owner are accepted, which is what proves the refusals were about
    scope and nothing else.

    Design: Corner/rbac/a_chair_and_a_reviewer_are_confined_to_their_own_records
    """
    fixtures.set_clock(api, constants.CLOCK_STARTUP_DEFAULT)
    program_a = fixtures.create_program(
        api, code="HIST-BA", name="History BA", department_code="HIST"
    )
    program_b = fixtures.create_program(
        api, code="PHIL-BA", name="Philosophy BA", department_code="PHIL"
    )
    chair_a = make_program_chair_headers(program_a["id"])
    chair_b = make_program_chair_headers(program_b["id"])

    cycle_a = fixtures.open_cycle(api, program_a["id"])
    study_a = fixtures.create_self_study(
        api, cycle_a["id"], program_a["id"], narrative="History self-study"
    )
    fixtures.create_appointment(
        api,
        program_a["id"],
        faculty_number="F-HIST-1",
        tenure_status="ADJUNCT",
        fte=0.25,
        annual_salary_cents=4000000,
    )
    fixtures.accept_self_study(api, study_a["id"], program_a["id"])

    reviewer_a = fixtures.register_reviewer(
        api,
        full_name="Dr Nala Osei",
        institution="Westmoor University",
        specialty_code="HIST",
    )
    reviewer_b = fixtures.register_reviewer(
        api,
        full_name="Dr Ivo Marek",
        institution="Northgate College",
        specialty_code="PHIL",
    )
    visit_a = fixtures.schedule_visit(api, cycle_a["id"], reviewer_a["id"])
    fixtures.set_clock(api, fixtures.CLOCK_AFTER_VISIT)
    fixtures.complete_visit(api, visit_a["id"])

    # check 4 outranks the duplicate-self-study check.
    validate_error(
        api.create_self_study(
            cycle_a["id"],
            factories.self_study_payload(narrative="Written by the wrong chair."),
            chair_b,
        ),
        ERR_NOT_PROGRAM_OWNER,
        403,
    )
    # check 4 outranks the state check that would say the study is no longer DRAFT.
    validate_error(
        api.patch_self_study(
            study_a["id"],
            factories.self_study_patch_payload(narrative="Edited by the wrong chair."),
            chair_b,
        ),
        ERR_NOT_PROGRAM_OWNER,
        403,
    )
    # A chair is on the roster for both of these reads, but only for his own rows.
    validate_error(
        api.list_faculty_appointments(program_a["id"], chair_b),
        ERR_NOT_PROGRAM_OWNER,
        403,
    )
    validate_error(
        api.get_review_cycle(cycle_a["id"], chair_b),
        ERR_NOT_PROGRAM_OWNER,
        403,
    )

    # check 5 — the reviewer who was never scheduled for this visit.
    validate_error(
        api.create_reviewer_report(
            visit_a["id"],
            factories.reviewer_report_payload(
                recommendation="CONTINUE",
                finding_codes=["F-NONE"],
                narrative="I was never on this visit.",
            ),
            make_external_reviewer_headers(reviewer_b["id"]),
        ),
        ERR_NOT_ASSIGNED_REVIEWER,
        403,
    )
    report = validate_success(
        api.create_reviewer_report(
            visit_a["id"],
            factories.reviewer_report_payload(
                recommendation="DISCONTINUE",
                finding_codes=["F-ENROLL"],
                narrative="Enrollment has collapsed.",
            ),
            make_external_reviewer_headers(reviewer_a["id"]),
        ),
        201,
    )
    assert report["sequence_number"] == 1
    validate_error(
        api.list_reviewer_reports(
            visit_a["id"], make_external_reviewer_headers(reviewer_b["id"])
        ),
        ERR_NOT_ASSIGNED_REVIEWER,
        403,
    )

    rows, meta = validate_paginated(
        api.list_reviewer_reports(
            visit_a["id"], make_external_reviewer_headers(reviewer_a["id"])
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["recommendation"] == "DISCONTINUE"
    assert rows[0]["sequence_number"] == 1

    studies, study_meta = validate_paginated(
        api.list_self_studies(cycle_a["id"], chair_a)
    )
    assert study_meta["total_count"] == 1
    assert studies[0]["narrative"] == "History self-study", (
        "the refused PATCH must not have edited the rightful chair's narrative"
    )


def test_the_shared_read_surface_answers_every_role_that_declares_it(api):
    """Every role on the roster sees the same bytes; nobody else sees any.

    §4's role column is the whole authority here: ``GET`` on a single program is
    shared by ReviewCoordinator, Provost, Registrar, HRPartner and the owning
    ProgramChair, so all five must get HTTP 200 carrying an identical ``data``
    object — reads are not mutations under §2.4, so nothing about the row may
    drift between them. The same table withholds the review-cycle read from
    Registrar and HRPartner, who therefore get ``ERR_ROLE_NOT_PERMITTED`` (403)
    on it, and it grants the clock endpoint to all six roles, so even an
    ``ExternalReviewer`` may move the clock.

    Design: Corner/rbac/the_shared_read_surface_answers_every_role_that_declares_it
    """
    coordinator = make_review_coordinator_headers()
    registrar = make_registrar_headers()
    hr_partner = make_hr_partner_headers()
    provost = make_provost_proposer_headers()

    # §4 lists all six roles on the clock endpoint.
    validate_success(api.set_clock(constants.CLOCK_STARTUP_DEFAULT, hr_partner))

    program_a = fixtures.create_program(
        api, code="HIST-BA", name="History BA", department_code="HIST"
    )
    program_b = fixtures.create_program(
        api, code="PHIL-BA", name="Philosophy BA", department_code="PHIL"
    )
    chair_a = make_program_chair_headers(program_a["id"])
    chair_b = make_program_chair_headers(program_b["id"])
    cycle = fixtures.open_cycle(api, program_a["id"])

    baseline = validate_success(api.get_program(program_a["id"], coordinator))
    for headers in (provost, registrar, hr_partner, chair_a):
        assert validate_success(api.get_program(program_a["id"], headers)) == baseline, (
            "every role on the shared read roster must see one identical object"
        )

    assert baseline["code"] == "HIST-BA"
    assertions.assert_axes(baseline, "UNDER_REVIEW", "LISTED")
    assert baseline["viability_band"] == "INSUFFICIENT_DATA"
    assert baseline["composite_score"] is None
    assert baseline["snapshot_count"] == 0

    # The sharing stops at the chair's own program.
    validate_error(
        api.get_program(program_a["id"], chair_b),
        ERR_NOT_PROGRAM_OWNER,
        403,
    )

    for headers in (registrar, hr_partner):
        # The teach-out-plan list is shared with both of them...
        rows, meta = validate_paginated(
            api.list_teach_out_plans(headers, params={"program_id": program_a["id"]})
        )
        assert rows == []
        assertions.assert_pagination_meta(
            meta, constants.DEFAULT_LIMIT, constants.DEFAULT_OFFSET, 0, False
        )
        # ...but the review-cycle read is not.
        validate_error(
            api.get_review_cycle(cycle["id"], headers),
            ERR_ROLE_NOT_PERMITTED,
            403,
        )

    validate_success(
        api.set_clock("2026-08-02T00:00:00Z", make_external_reviewer_headers("reviewer-1"))
    )
    assert (
        validate_success(api.get_program(program_a["id"], coordinator))["version"]
        == baseline["version"]
    ), "reads and clock moves are not mutations of the program row"
