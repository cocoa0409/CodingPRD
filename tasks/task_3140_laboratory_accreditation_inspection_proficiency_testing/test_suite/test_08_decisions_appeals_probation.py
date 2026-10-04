"""Decisions, appeals, probation cascade, reinstatement, revocation."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    cite_finding,
    create_assignment,
    create_cycle,
    create_inspector,
    create_laboratory,
    get_success_data,
    list_investigations,
    make_director_headers,
    make_inspector_headers,
    respond_and_accept,
    setup_decided_cycle,
    setup_findings_issued,
    setup_pt_active_enrollment,
    setup_single_unsatisfactory_event,
    submit_result_ok,
    create_shipment,
    validate_error,
    validate_success,
)

OFFICER = TEST_USERS["officer_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


def test_decide_with_burden_only_denied_admitted(api):
    """PRD §3.7: "The burden gates the outcome: if the cycle's
    `deficiency_burden_score` is above zero — including any contribution from
    findings still awaiting acceptance in `RESPONSE_SUBMITTED` — the only
    admissible decision is `DENIED`, and any other decision is rejected with
    `ERR_DECISION_BLOCKED_BY_BURDEN`."

    Design: Difficulty/cross_entity_state_dependency/decide_with_burden_only_denied_admitted
    """
    ctx = setup_findings_issued(level="LEVEL_1")
    cycle_id = ctx["cycle"]["id"]
    assert ctx["cycle"]["deficiency_burden_score"] == 2

    resp_blocked = api.decide_cycle(cycle_id, "ACCREDITED", OFFICER)
    validate_error(resp_blocked, ApiErrorId.ERR_DECISION_BLOCKED_BY_BURDEN.value, 409)
    cycle_mid = get_success_data(api.get_inspection_cycle(cycle_id, OFFICER))
    assert cycle_mid["status"] == "FINDINGS_ISSUED"

    get_success_data(api.withdraw_finding(
        ctx["finding"]["id"],
        make_inspector_headers(ctx["inspectors"][0]["id"])))
    cycle_zero = get_success_data(api.get_inspection_cycle(cycle_id, OFFICER))
    assert cycle_zero["deficiency_burden_score"] == 0

    decided = get_success_data(api.decide_cycle(cycle_id, "ACCREDITED", OFFICER))
    assert decided["final_decision"] == "ACCREDITED"
    lab_after = get_success_data(api.get_laboratory(ctx["lab"]["id"], OFFICER))
    assert lab_after["accreditation_status"] == "ACCREDITED"


def test_decide_blocked_by_burden_while_response_pending_acceptance(api):
    """PRD §3.7: "The burden gates the outcome: if the cycle's
    `deficiency_burden_score` is above zero — including any contribution from
    findings still awaiting acceptance in `RESPONSE_SUBMITTED` — the only
    admissible decision is `DENIED`, and any other decision is rejected with
    `ERR_DECISION_BLOCKED_BY_BURDEN`."

    Design: Difficulty/cross_entity_state_dependency/decide_with_burden_only_denied_admitted
    """
    ctx = setup_findings_issued(level="LEVEL_1")
    cycle_id = ctx["cycle"]["id"]
    get_success_data(api.respond_to_finding(
        ctx["finding"]["id"], "Addressed.",
        make_director_headers(ctx["lab"]["id"])))
    # Finding is RESPONSE_SUBMITTED: still counts toward burden at full weight.
    resp = api.decide_cycle(cycle_id, "CONDITIONAL", OFFICER)
    validate_error(resp, ApiErrorId.ERR_DECISION_BLOCKED_BY_BURDEN.value, 409)


def test_decide_denied_cascades_lab_probation_to_enrollments_and_inspectors(api):
    """PRD §3.7: "a `DENIED` decision drives the laboratory into `PROBATION`,
    which cascades every `ACTIVE` enrollment of the laboratory to `SUSPENDED`
    and every `ACTIVE` affiliated inspector profile to `SUSPENDED`, recomputing
    `active_discipline_count` as part of the same atomic write (§2.6)."
    PRD §2.6: "when a laboratory enters `PROBATION`, every one of its
    affiliated inspectors in `ACTIVE` status becomes `SUSPENDED`"

    Design: Difficulty/transitive_cascade/decide_denied_cascades_lab_probation_to_enrollments_and_inspectors
    """
    ctx = setup_findings_issued(level="LEVEL_1")
    lab_id = ctx["lab"]["id"]
    # Second ACTIVE enrollment on the same laboratory.
    enr2 = get_success_data(api.create_enrollment(
        {"laboratory_id": lab_id, "discipline": "MOLECULAR"},
        make_director_headers(lab_id)))
    from test_helpers import create_section_for_enrollment, register_checklist_edition, assign_checklist_to_section
    sec2 = create_section_for_enrollment(enr2["id"], lab_id, section_name="PCR Bench")
    register_checklist_edition("MOL", "2026")
    assign_checklist_to_section(sec2["id"], "MOL", "2026")
    # An inspector affiliated with the laboratory under inspection.
    home_inspector = create_inspector(lab_id, specialties=["CHEMISTRY"],
                                      full_name="Home Inspector")

    lab_before = get_success_data(api.get_laboratory(lab_id, OFFICER))
    assert lab_before["active_discipline_count"] == 2

    decided = get_success_data(api.decide_cycle(ctx["cycle"]["id"], "DENIED", OFFICER))
    assert decided["status"] == "DECIDED"
    assert decided["final_decision"] == "DENIED"

    lab_after = get_success_data(api.get_laboratory(lab_id, OFFICER))
    assert lab_after["accreditation_status"] == "PROBATION"
    assert lab_after["active_discipline_count"] == 0
    enr1_after = get_success_data(api.get_enrollment(ctx["enrollment"]["id"], OFFICER))
    enr2_after = get_success_data(api.get_enrollment(enr2["id"], OFFICER))
    assert enr1_after["status"] == "SUSPENDED"
    assert enr2_after["status"] == "SUSPENDED"
    home_after = get_success_data(
        api.get_inspector_profile(home_inspector["id"], OFFICER))
    assert home_after["status"] == "SUSPENDED"
    peer_after = get_success_data(
        api.get_inspector_profile(ctx["inspectors"][0]["id"], OFFICER))
    assert peer_after["status"] == "ACTIVE"


def test_probation_cascade_from_accredited_laboratory_also_suspends(api):
    """PRD §2.6: "when a laboratory enters `PROBATION`, every one of its
    affiliated inspectors in `ACTIVE` status becomes `SUSPENDED`; when a
    laboratory is reinstated from `PROBATION`, every suspended affiliated
    inspector returns to `ACTIVE`."
    PRD §3.7: "a `DENIED` decision drives the laboratory into `PROBATION`,
    which cascades every `ACTIVE` enrollment of the laboratory to `SUSPENDED`
    and every `ACTIVE` affiliated inspector profile to `SUSPENDED`, recomputing
    `active_discipline_count` as part of the same atomic write (§2.6)."

    Design: Difficulty/transitive_cascade/decide_denied_cascades_lab_probation_to_enrollments_and_inspectors
    """
    ctx = setup_findings_issued(level="LEVEL_1")
    lab_id = ctx["lab"]["id"]
    home_inspector = create_inspector(lab_id, specialties=["CHEMISTRY"])
    decided = get_success_data(api.decide_cycle(ctx["cycle"]["id"], "DENIED", OFFICER))
    assert decided["final_decision"] == "DENIED"
    home_after = get_success_data(
        api.get_inspector_profile(home_inspector["id"], OFFICER))
    assert home_after["status"] == "SUSPENDED"
    enr_after = get_success_data(api.get_enrollment(ctx["enrollment"]["id"], OFFICER))
    assert enr_after["status"] == "SUSPENDED"


def test_inspection_cycle_appeal_self_inspection_redecision_loop(api):
    """PRD §3.7: "The loop is cyclic: from `RE_DECIDED` the laboratory may
    appeal again within thirty days of the re-decision, subject to the same
    two-appeal ceiling, walking `DECIDED` to `APPEALED` to
    `INTERIM_SELF_INSPECTION` to `RE_DECIDED` and back while appeals remain."
    PRD §3.7: "Appealing increments `appeal_count` by one and moves the cycle
    to `APPEALED`."

    Design: Difficulty/non_linear_state_machine/inspection_cycle_appeal_self_inspection_redecision_loop
    """
    ctx = setup_findings_issued(level="LEVEL_1")
    lab_id = ctx["lab"]["id"]
    cycle_id = ctx["cycle"]["id"]
    respond_and_accept(ctx["finding"]["id"], lab_id, ctx["inspectors"][1]["id"],
                       response_text="Fixed.")
    director = make_director_headers(lab_id)

    decided = get_success_data(api.decide_cycle(cycle_id, "DENIED", OFFICER))
    assert decided["appeal_count"] == 0
    lab1 = get_success_data(api.get_laboratory(lab_id, OFFICER))
    assert lab1["accreditation_status"] == "PROBATION"

    appealed = get_success_data(api.appeal_cycle(cycle_id, director))
    assert appealed["appeal_count"] == 1
    assert appealed["status"] == "APPEALED"
    get_success_data(api.self_inspect_cycle(cycle_id, director))
    redecided = get_success_data(api.re_decide_cycle(cycle_id, "ACCREDITED", OFFICER))
    assert redecided["status"] == "RE_DECIDED"
    assert redecided["final_decision"] == "ACCREDITED"
    # NOTE: the laboratory-level outcome of re-deciding ACCREDITED while the
    # laboratory sits in PROBATION is deliberately not asserted. PRD §3.7 says
    # "an ACCREDITED decision moves an ENROLLED laboratory to ACCREDITED (a
    # no-op if it is already accredited)" and that re-deciding applies "the
    # identical laboratory cascade", which two faithful readers resolve
    # differently for a PROBATION laboratory.

    appealed2 = get_success_data(api.appeal_cycle(cycle_id, director))
    assert appealed2["appeal_count"] == 2
    get_success_data(api.self_inspect_cycle(cycle_id, director))
    redecided2 = get_success_data(api.re_decide_cycle(cycle_id, "CONDITIONAL", OFFICER))
    assert redecided2["status"] == "RE_DECIDED"
    assert redecided2["final_decision"] == "CONDITIONAL"


def test_appeal_limit_reached_at_two(api):
    """PRD §3.7: "the cycle's `appeal_count` is below two
    (`ERR_APPEAL_LIMIT_REACHED` at the limit)."

    Design: Difficulty/non_linear_state_machine/inspection_cycle_appeal_self_inspection_redecision_loop
    """
    ctx = setup_findings_issued(level="LEVEL_1")
    lab_id = ctx["lab"]["id"]
    cycle_id = ctx["cycle"]["id"]
    respond_and_accept(ctx["finding"]["id"], lab_id, ctx["inspectors"][1]["id"])
    director = make_director_headers(lab_id)

    get_success_data(api.decide_cycle(cycle_id, "DENIED", OFFICER))
    get_success_data(api.appeal_cycle(cycle_id, director))
    get_success_data(api.self_inspect_cycle(cycle_id, director))
    get_success_data(api.re_decide_cycle(cycle_id, "ACCREDITED", OFFICER))
    get_success_data(api.appeal_cycle(cycle_id, director))
    get_success_data(api.self_inspect_cycle(cycle_id, director))
    get_success_data(api.re_decide_cycle(cycle_id, "CONDITIONAL", OFFICER))

    resp = api.appeal_cycle(cycle_id, director)
    validate_error(resp, ApiErrorId.ERR_APPEAL_LIMIT_REACHED.value, 409)


def test_appeal_window_closes_after_30_days(api):
    """PRD §3.7: "From `DECIDED`, the `LaboratoryDirector` may appeal, provided
    the current logical time is within thirty days of the decision instant —
    the `updated_at` stamp of the transition into `DECIDED` —
    (`ERR_APPEAL_WINDOW_CLOSED` thereafter)"
    PRD §3.7: "from `RE_DECIDED` the laboratory may appeal again within thirty
    days of the re-decision, subject to the same two-appeal ceiling"

    Design: Corner/errors/appeal_window_closes_after_30_days
    """
    ctx = setup_findings_issued(conduct_at="2026-09-12T00:00:00Z", level="LEVEL_1")
    lab_id = ctx["lab"]["id"]
    cycle_id = ctx["cycle"]["id"]
    respond_and_accept(ctx["finding"]["id"], lab_id, ctx["inspectors"][1]["id"])
    director = make_director_headers(lab_id)

    get_success_data(api.decide_cycle(cycle_id, "CONDITIONAL", OFFICER))
    # Day +30 (inclusive): appeal succeeds.
    get_success_data(api.set_clock("2026-10-12T00:00:00Z", ADMIN))
    appealed = get_success_data(api.appeal_cycle(cycle_id, director))
    assert appealed["status"] == "APPEALED"
    get_success_data(api.self_inspect_cycle(cycle_id, director))
    redecided = get_success_data(api.re_decide_cycle(cycle_id, "ACCREDITED", OFFICER))
    assert redecided["final_decision"] == "ACCREDITED"
    lab = get_success_data(api.get_laboratory(lab_id, OFFICER))
    assert lab["accreditation_status"] == "ACCREDITED"

    # Re-decision at 2026-10-12; +31 days is out of window.
    get_success_data(api.set_clock("2026-11-13T00:00:00Z", ADMIN))
    resp = api.appeal_cycle(cycle_id, director)
    validate_error(resp, ApiErrorId.ERR_APPEAL_WINDOW_CLOSED.value, 409)


def test_revoke_too_early_blocked_and_succeeds_after_180_days(api):
    """PRD §3.7: "revocation requires the laboratory to be in `PROBATION`
    (`ERR_INVALID_STATE`) and requires the current logical time to be at least
    180 days after the most recent `DENIED` final decision issued for this
    laboratory (`ERR_REVOKE_TOO_EARLY` otherwise). Revocation lands the
    laboratory in its terminal `ACCREDITATION_REVOKED` state."

    Design: Corner/errors/revoke_too_early_blocked_and_succeeds_after_180_days
    """
    ctx = setup_decided_cycle(decision="DENIED", conduct_at="2026-09-12T00:00:00Z")
    lab_id = ctx["lab"]["id"]
    lab = get_success_data(api.get_laboratory(lab_id, OFFICER))
    assert lab["accreditation_status"] == "PROBATION"

    # +10 days after the DENIED decision: too early.
    get_success_data(api.set_clock("2026-09-22T00:00:00Z", ADMIN))
    resp_early = api.revoke_laboratory(lab_id, OFFICER)
    validate_error(resp_early, ApiErrorId.ERR_REVOKE_TOO_EARLY.value, 409)
    lab_mid = get_success_data(api.get_laboratory(lab_id, OFFICER))
    assert lab_mid["accreditation_status"] == "PROBATION"

    # +181 days: admitted.
    get_success_data(api.set_clock("2027-03-12T00:00:00Z", ADMIN))
    revoked = get_success_data(api.revoke_laboratory(lab_id, OFFICER))
    assert revoked["accreditation_status"] == "ACCREDITATION_REVOKED"


def test_reinstate_blocked_by_open_investigation(api):
    """PRD §3.7: "An `AccreditationOfficer` may reinstate it to `ENROLLED`, but
    only while no investigation of any of the laboratory's enrollments sits in
    a non-terminal status (`OPEN`, `UNDER_REVIEW`, or
    `CORRECTIVE_ACTION_REQUIRED`) — otherwise the request fails with
    `ERR_OPEN_INVESTIGATION_EXISTS`"
    PRD §3.7: "Reinstatement cascades every `SUSPENDED` enrollment of the
    laboratory back to `ACTIVE` and every `SUSPENDED` affiliated inspector back
    to `ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/reinstate_blocked_by_open_investigation
    """
    # Build the PT investigation FIRST (while the enrollment is ACTIVE).
    ctx = setup_single_unsatisfactory_event(
        analytes=[{"name": "glucose", "critical": True}])
    lab_id = ctx["lab"]["id"]
    enr_id = ctx["enrollment"]["id"]
    inv_id = ctx["investigation"]["id"]
    get_success_data(api.begin_review(inv_id, OFFICER))

    # Drive the laboratory into PROBATION through a decided cycle.
    from test_helpers import create_qualified_personnel, create_approved_method_validation
    create_qualified_personnel(enr_id, lab_id)
    create_approved_method_validation(enr_id, lab_id)
    peer_b = create_laboratory(name="Peer B", clia_number="45D1000063")
    insp_b = create_inspector(peer_b["id"], specialties=["CHEMISTRY"])
    cyc = create_cycle(lab_id, "2026-09-10T00:00:00Z", "2026-09-20T00:00:00Z")
    asg = create_assignment(cyc["id"], insp_b["id"], "LEAD")
    get_success_data(api.clear_assignment(asg["id"], OFFICER))
    get_success_data(api.screen_team(cyc["id"], OFFICER))
    get_success_data(api.set_clock("2026-09-12T00:00:00Z", ADMIN))
    get_success_data(api.conduct_cycle(cyc["id"], OFFICER))
    cite_finding(cyc["id"], ctx["sections"][0]["id"], insp_b["id"],
                 level="LEVEL_1", item_code="CHM.10000")
    get_success_data(api.issue_findings(cyc["id"], OFFICER))
    get_success_data(api.decide_cycle(cyc["id"], "DENIED", OFFICER))
    lab = get_success_data(api.get_laboratory(lab_id, OFFICER))
    assert lab["accreditation_status"] == "PROBATION"
    enr_mid = get_success_data(api.get_enrollment(enr_id, OFFICER))
    assert enr_mid["status"] == "SUSPENDED"

    # Reinstate while the investigation is UNDER_REVIEW: blocked.
    resp_blocked = api.reinstate_laboratory(lab_id, OFFICER)
    validate_error(resp_blocked, ApiErrorId.ERR_OPEN_INVESTIGATION_EXISTS.value, 409)
    lab_still = get_success_data(api.get_laboratory(lab_id, OFFICER))
    assert lab_still["accreditation_status"] == "PROBATION"

    # Resolve from UNDER_REVIEW: does not touch the SUSPENDED enrollment.
    get_success_data(api.resolve_investigation(inv_id, OFFICER))
    enr_still = get_success_data(api.get_enrollment(enr_id, OFFICER))
    assert enr_still["status"] == "SUSPENDED"

    # Reinstate now succeeds and cascades the enrollment back to ACTIVE.
    reinstated = get_success_data(api.reinstate_laboratory(lab_id, OFFICER))
    assert reinstated["accreditation_status"] == "ENROLLED"
    enr_after = get_success_data(api.get_enrollment(enr_id, OFFICER))
    assert enr_after["status"] == "ACTIVE"
    lab_after = get_success_data(api.get_laboratory(lab_id, OFFICER))
    assert lab_after["active_discipline_count"] == 1


def test_reinstate_restores_suspended_affiliated_inspector(api):
    """PRD §3.7: "Reinstatement cascades every `SUSPENDED` enrollment of the
    laboratory back to `ACTIVE` and every `SUSPENDED` affiliated inspector back
    to `ACTIVE`."
    PRD §2.6: "when a laboratory is reinstated from `PROBATION`, every
    suspended affiliated inspector returns to `ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/reinstate_blocked_by_open_investigation
    """
    # Build the cycle BEFORE the home inspector is suspended so the decide
    # cascade suspends it, then reinstate restores it.
    ctx = setup_findings_issued(level="LEVEL_1")
    lab_id = ctx["lab"]["id"]
    home_inspector = create_inspector(lab_id, specialties=["CHEMISTRY"])
    get_success_data(api.decide_cycle(ctx["cycle"]["id"], "DENIED", OFFICER))
    insp_mid = get_success_data(
        api.get_inspector_profile(home_inspector["id"], OFFICER))
    assert insp_mid["status"] == "SUSPENDED"

    reinstated = get_success_data(api.reinstate_laboratory(lab_id, OFFICER))
    assert reinstated["accreditation_status"] == "ENROLLED"
    enr_after = get_success_data(api.get_enrollment(ctx["enrollment"]["id"], OFFICER))
    assert enr_after["status"] == "ACTIVE"
    insp_after = get_success_data(
        api.get_inspector_profile(home_inspector["id"], OFFICER))
    assert insp_after["status"] == "ACTIVE"
