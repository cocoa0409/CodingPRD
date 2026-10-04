"""Inspection cycles: window overlap, team screening, conflict checks."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    cite_finding,
    create_assignment,
    create_cycle,
    create_inspector,
    create_laboratory,
    get_success_data,
    make_inspector_headers,
    setup_conducted_cycle,
    setup_findings_issued,
    setup_lab_with_active_enrollment,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)

OFFICER = TEST_USERS["officer_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


def test_inspection_cycle_window_half_open_overlap(api):
    """PRD §3.4: "if the half-open window from `scheduled_start` to
    `scheduled_end` intersects the window of any existing cycle of the same
    laboratory whose status is `TEAM_ASSEMBLY`, `SCREENED`, `CONDUCTED`, or
    `FINDINGS_ISSUED`, the creation is rejected with `ERR_CYCLE_WINDOW_OVERLAP`;
    windows that merely touch — the existing cycle's `scheduled_end` equal to
    the new `scheduled_start` — do not overlap."

    Design: Difficulty/resource_temporal_overlap/inspection_cycle_window_half_open_overlap
    """
    lab = create_laboratory(name="Overlap Lab", clia_number="45D1000070")
    create_cycle(lab["id"], "2026-10-01T00:00:00Z", "2026-10-10T00:00:00Z")

    touching = api.create_inspection_cycle(
        {"laboratory_id": lab["id"], "scheduled_start": "2026-10-10T00:00:00Z",
         "scheduled_end": "2026-10-20T00:00:00Z"}, OFFICER)
    validate_success(touching, expected_status=201)

    resp_overlap = api.create_inspection_cycle(
        {"laboratory_id": lab["id"], "scheduled_start": "2026-10-09T23:59:59Z",
         "scheduled_end": "2026-10-15T00:00:00Z"}, OFFICER)
    validate_error(resp_overlap, ApiErrorId.ERR_CYCLE_WINDOW_OVERLAP.value, 409)


def test_inspection_cycle_window_overlap_against_first_cycle(api):
    """PRD §3.4: "if the half-open window from `scheduled_start` to
    `scheduled_end` intersects the window of any existing cycle of the same
    laboratory whose status is `TEAM_ASSEMBLY`, `SCREENED`, `CONDUCTED`, or
    `FINDINGS_ISSUED`, the creation is rejected with `ERR_CYCLE_WINDOW_OVERLAP`"

    Design: Difficulty/resource_temporal_overlap/inspection_cycle_window_half_open_overlap
    """
    lab = create_laboratory(name="Overlap Lab B", clia_number="45D1000099")
    create_cycle(lab["id"], "2026-10-01T00:00:00Z", "2026-10-10T00:00:00Z")

    # One second before the existing cycle's end: genuine intersection.
    resp = api.create_inspection_cycle(
        {"laboratory_id": lab["id"], "scheduled_start": "2026-10-05T00:00:00Z",
         "scheduled_end": "2026-10-15T00:00:00Z"}, OFFICER)
    validate_error(resp, ApiErrorId.ERR_CYCLE_WINDOW_OVERLAP.value, 409)

    # Fully outside any open cycle window: admitted.
    ok = api.create_inspection_cycle(
        {"laboratory_id": lab["id"], "scheduled_start": "2026-11-01T00:00:00Z",
         "scheduled_end": "2026-11-05T00:00:00Z"}, OFFICER)
    validate_success(ok, expected_status=201)


def test_screen_team_blocked_by_conflicted_assignment(api):
    """PRD §3.4: "it requires that no assignment on the cycle remain
    `CONFLICTED` (conflicted inspectors must be replaced first), otherwise
    `ERR_CONFLICTED_INSPECTOR`."
    PRD §3.4: "the replacement creates a fresh `PENDING` assignment on the same
    cycle with the same `role_in_team`, leaving the original assignment in its
    terminal `REPLACED` state."

    Design: Corner/state_machines/screen_team_blocked_by_conflicted_assignment
    """
    setup_lab_with_active_enrollment()
    # rebuild with explicit ids (edition CHM/2026 already registered above)
    ctx_lab = create_laboratory(name="Screen Lab", clia_number="45D1000017")
    from test_helpers import create_enrollment_for_lab, create_section_for_enrollment, register_checklist_edition, assign_checklist_to_section
    enr = create_enrollment_for_lab(ctx_lab["id"], "CHEMISTRY")
    sec = create_section_for_enrollment(enr["id"], ctx_lab["id"], section_name="Chem")
    assign_checklist_to_section(sec["id"], "CHM", "2026")

    peer = create_laboratory(name="Screen Peer", clia_number="45D1000018")
    insp1 = create_inspector(peer["id"], specialties=["CHEMISTRY"],
                             full_name="Conf Inspector")
    insp2 = create_inspector(peer["id"], specialties=["CHEMISTRY"],
                             full_name="Clean Inspector")
    cycle = create_cycle(ctx_lab["id"])
    asg1 = create_assignment(cycle["id"], insp1["id"], "LEAD")
    get_success_data(api.flag_conflict(asg1["id"], OFFICER))

    resp_blocked = api.screen_team(cycle["id"], OFFICER)
    # With the only assignment CONFLICTED, two §3.4 rules fail at once: no
    # CLEARED LEAD exists (ERR_TEAM_INCOMPLETE) and a CONFLICTED assignment
    # remains (ERR_CONFLICTED_INSPECTOR). PRD names no precedence between
    # them, so accept either — the replacement flow below pins the
    # conflicted-inspector rule.
    assert resp_blocked.status_code == 409
    validate_error_is_one_of(
        resp_blocked,
        [ApiErrorId.ERR_CONFLICTED_INSPECTOR.value,
         ApiErrorId.ERR_TEAM_INCOMPLETE.value])

    replaced = get_success_data(api.replace_assignment(asg1["id"], insp2["id"], OFFICER))
    assert replaced["status"] == "REPLACED"

    assignments = get_success_data(api.list_team_assignments(
        OFFICER, params={"inspection_cycle_id": cycle["id"]}))
    assert len(assignments) == 2
    new_asg = [a for a in assignments if a["id"] != asg1["id"]][0]
    assert new_asg["status"] == "PENDING"
    assert new_asg["inspector_id"] == insp2["id"]
    assert new_asg["role_in_team"] == "LEAD"

    get_success_data(api.clear_assignment(new_asg["id"], OFFICER))
    screened = get_success_data(api.screen_team(cycle["id"], OFFICER))
    assert screened["status"] == "SCREENED"


def test_team_clear_rejects_self_inspection(api):
    """PRD §3.4: "the inspector's `affiliated_laboratory_id` must differ from
    the cycle's laboratory (`ERR_SELF_INSPECTION`)"

    Design: Corner/state_machines/team_clear_rejects_self_inspection
    """
    lab = create_laboratory(name="Self Lab", clia_number="45D1000019")
    from test_helpers import create_enrollment_for_lab, create_section_for_enrollment, register_checklist_edition, assign_checklist_to_section
    enr = create_enrollment_for_lab(lab["id"], "CHEMISTRY")
    sec = create_section_for_enrollment(enr["id"], lab["id"], section_name="Chem")
    register_checklist_edition("CHM", "2026")
    assign_checklist_to_section(sec["id"], "CHM", "2026")

    insp = create_inspector(lab["id"], specialties=["CHEMISTRY"],
                            full_name="Self Inspector")
    cycle = create_cycle(lab["id"])
    asg = create_assignment(cycle["id"], insp["id"], "LEAD")
    resp = api.clear_assignment(asg["id"], OFFICER)
    validate_error(resp, ApiErrorId.ERR_SELF_INSPECTION.value, 409)
    asg_after = get_success_data(api.get_team_assignment(asg["id"], OFFICER))
    assert asg_after["status"] == "PENDING"


def test_team_clear_rejects_reciprocal_conflict_within_365_days(api):
    """PRD §3.4: "the inspector's affiliated laboratory must not have
    participated in inspecting this laboratory recently — specifically, there
    must be no other cycle of this laboratory, in any status from `CONDUCTED`
    onward through `RE_DECIDED`, whose `scheduled_start` falls within the 365
    days before this cycle's `scheduled_start` and which carries any team
    assignment (in `CLEARED`, `PENDING`, or `REPLACED` status) whose inspector
    shares this inspector's affiliated laboratory — (`ERR_RECIPROCAL_CONFLICT`)."

    Design: Corner/state_machines/team_clear_rejects_reciprocal_conflict_within_365_days
    """
    lab = create_laboratory(name="Recip Lab", clia_number="45D1000020")
    lab_b = create_laboratory(name="Recip Peer B", clia_number="45D1000021")
    lab_c = create_laboratory(name="Recip Peer C", clia_number="45D1000022")
    from test_helpers import create_enrollment_for_lab, create_section_for_enrollment, register_checklist_edition, assign_checklist_to_section
    enr = create_enrollment_for_lab(lab["id"], "CHEMISTRY")
    sec = create_section_for_enrollment(enr["id"], lab["id"], section_name="Chem")
    register_checklist_edition("CHM", "2026")
    assign_checklist_to_section(sec["id"], "CHM", "2026")

    # Cycle 1 conducted with a lab-B inspector on the team.
    insp_b1 = create_inspector(lab_b["id"], specialties=["CHEMISTRY"],
                               full_name="B One")
    cyc1 = create_cycle(lab["id"], "2026-09-10T00:00:00Z", "2026-09-20T00:00:00Z")
    asg1 = create_assignment(cyc1["id"], insp_b1["id"], "LEAD")
    get_success_data(api.clear_assignment(asg1["id"], OFFICER))
    get_success_data(api.screen_team(cyc1["id"], OFFICER))
    from test_helpers import create_qualified_personnel, create_approved_method_validation
    create_qualified_personnel(enr["id"], lab["id"])
    create_approved_method_validation(enr["id"], lab["id"])
    get_success_data(api.set_clock("2026-09-12T00:00:00Z", ADMIN))
    get_success_data(api.conduct_cycle(cyc1["id"], OFFICER))

    # Cycle 2 scheduled within 365 days of cycle 1's start.
    insp_b2 = create_inspector(lab_b["id"], specialties=["CHEMISTRY"],
                               full_name="B Two")
    insp_c1 = create_inspector(lab_c["id"], specialties=["CHEMISTRY"],
                               full_name="C One")
    cyc2 = create_cycle(lab["id"], "2026-12-01T00:00:00Z", "2026-12-10T00:00:00Z")
    asg_b2 = create_assignment(cyc2["id"], insp_b2["id"], "LEAD")
    asg_c1 = create_assignment(cyc2["id"], insp_c1["id"], "MEMBER")

    resp_conflict = api.clear_assignment(asg_b2["id"], OFFICER)
    validate_error(resp_conflict, ApiErrorId.ERR_RECIPROCAL_CONFLICT.value, 409)

    cleared = get_success_data(api.clear_assignment(asg_c1["id"], OFFICER))
    assert cleared["status"] == "CLEARED"


def test_finding_cite_on_section_of_another_laboratory_rejected(api):
    """PRD §3.6: "The cited section must belong to an enrollment of the cycle's
    laboratory; citing a section from another laboratory's enrollment fails
    with `ERR_SECTION_NOT_IN_LABORATORY`."

    Design: Corner/state_machines/finding_cite_on_section_of_another_laboratory_rejected
    """
    ctx = setup_conducted_cycle()
    other = setup_lab_with_active_enrollment(checklist_code="MIC",
                                             checklist_version="2026")
    other_section = other["sections"][0]

    resp = api.create_finding(
        {"inspection_cycle_id": ctx["cycle"]["id"],
         "section_id": other_section["id"],
         "checklist_item_code": "CHM.10099",
         "deficiency_level": "LEVEL_1"},
        make_inspector_headers(ctx["inspectors"][0]["id"]))
    validate_error(resp, ApiErrorId.ERR_SECTION_NOT_IN_LABORATORY.value, 409)


def test_business_safety_priority_beats_business_fiscal_on_unready_conduct(api):
    """PRD §2.8: "(7) temporal windows such as deadlines and appeal periods;
    (8) gate checks such as cycle posture, deficiency burden, validation-study
    adequacy, and the no-findings floor"
    PRD §3.6: "Two gates apply: the cycle's `posture_ready` must be true
    (`ERR_CYCLE_NOT_READY`), and the current logical time must fall within the
    inspection window — at or after `scheduled_start` and strictly before
    `scheduled_end` — otherwise `ERR_INSPECTION_WINDOW_NOT_OPEN`."

    Design: Difficulty/priority_pair_validation_conflict/business_safety_priority_beats_business_fiscal_on_unready_conduct
    """
    # Laboratory whose only enrollment has an UNASSIGNED section: posture fails.
    lab = create_laboratory(name="Gate Lab", clia_number="45D1000041")
    from test_helpers import create_enrollment_for_lab, create_section_for_enrollment, register_checklist_edition
    enr = create_enrollment_for_lab(lab["id"], "CHEMISTRY")
    create_section_for_enrollment(enr["id"], lab["id"], section_name="Unassigned Bench")
    register_checklist_edition("CHM", "2026")

    peer = create_laboratory(name="Gate Peer", clia_number="45D1000042")
    insp = create_inspector(peer["id"], specialties=["CHEMISTRY"],
                            full_name="Gate Inspector")
    cycle = create_cycle(lab["id"], "2026-09-10T00:00:00Z", "2026-09-20T00:00:00Z")
    asg = create_assignment(cycle["id"], insp["id"], "LEAD")
    get_success_data(api.clear_assignment(asg["id"], OFFICER))
    get_success_data(api.screen_team(cycle["id"], OFFICER))

    # Clock at 2026-09-05: outside the window AND posture not ready.
    resp_outside = api.conduct_cycle(cycle["id"], OFFICER)
    validate_error(resp_outside, ApiErrorId.ERR_INSPECTION_WINDOW_NOT_OPEN.value, 409)

    # Inside the window, posture still false.
    get_success_data(api.set_clock("2026-09-12T00:00:00Z", ADMIN))
    resp_inside = api.conduct_cycle(cycle["id"], OFFICER)
    validate_error(resp_inside, ApiErrorId.ERR_CYCLE_NOT_READY.value, 409)

    cycle_after = get_success_data(api.get_inspection_cycle(cycle["id"], OFFICER))
    assert cycle_after["status"] == "SCREENED"


def test_conduct_outside_window_rejected_window_not_open(api):
    """PRD §3.6: "the current logical time must fall within the inspection
    window — at or after `scheduled_start` and strictly before `scheduled_end`
    — otherwise `ERR_INSPECTION_WINDOW_NOT_OPEN`."

    Design: Difficulty/priority_pair_validation_conflict/business_safety_priority_beats_business_fiscal_on_unready_conduct
    """
    # Build a fully posture-ready lab but never advance the clock into the window.
    from test_helpers import setup_posture_ready_lab
    lab_setup = setup_posture_ready_lab()
    lab = lab_setup["lab"]
    peer = create_laboratory()
    insp = create_inspector(peer["id"], specialties=["CHEMISTRY"])
    cycle = create_cycle(lab["id"], "2026-09-10T00:00:00Z", "2026-09-20T00:00:00Z")
    asg = create_assignment(cycle["id"], insp["id"], "LEAD")
    get_success_data(api.clear_assignment(asg["id"], OFFICER))
    get_success_data(api.screen_team(cycle["id"], OFFICER))

    # Clock is at 2026-09-01 (before the window), posture is ready.
    resp = api.conduct_cycle(cycle["id"], OFFICER)
    validate_error(resp, ApiErrorId.ERR_INSPECTION_WINDOW_NOT_OPEN.value, 409)
    cycle_after = get_success_data(api.get_inspection_cycle(cycle["id"], OFFICER))
    assert cycle_after["status"] == "SCREENED"
