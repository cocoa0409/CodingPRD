"""PT investigations: standing variants, cessation gating, resolution cascades."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    create_shipment,
    get_success_data,
    list_investigations,
    make_director_headers,
    setup_pt_active_enrollment,
    setup_rolling_unsatisfactory_enrollment,
    setup_single_unsatisfactory_event,
    submit_result_ok,
    validate_error,
)

OFFICER = TEST_USERS["officer_headers"]
PTC = TEST_USERS["pt_coordinator_headers"]


def _uus_history(api):
    """Build the U,U,S graded history on one enrollment. Returns ctx."""
    analytes = [
        {"name": "glucose", "critical": True},
        {"name": "sodium", "critical": False},
    ]
    ctx = setup_pt_active_enrollment(analytes=analytes)
    lab_id = ctx["lab"]["id"]
    sub_id = ctx["subscription"]["id"]

    sh1 = create_shipment(sub_id, event_code="C-2026-A")
    submit_result_ok(sh1["id"], lab_id,
                     [{"name": "glucose", "score": 100},
                      {"name": "sodium", "score": 79}])
    inv1 = list_investigations(ctx["enrollment"]["id"])[0]
    get_success_data(api.resolve_investigation(inv1["id"], OFFICER))
    get_success_data(api.close_pt_shipment(sh1["id"], PTC))

    sh2 = create_shipment(sub_id, event_code="C-2026-B")
    submit_result_ok(sh2["id"], lab_id,
                     [{"name": "glucose", "score": 90},
                      {"name": "sodium", "score": 70}],
                     collected_at="2026-09-02T12:00:00Z")
    get_success_data(api.close_pt_shipment(sh2["id"], PTC))

    sh3 = create_shipment(sub_id, event_code="C-2026-C")
    submit_result_ok(sh3["id"], lab_id,
                     [{"name": "glucose", "score": 100},
                      {"name": "sodium", "score": 80}],
                     collected_at="2026-09-03T00:00:00Z")
    return ctx


def test_pt_standing_per_event_vs_rolling_uus_sequence(api):
    """PRD §3.2: "`standing_rolling` is `UNSATISFACTORY` if the history holds
    at least two graded results and at least two of the last three graded
    results (or the last `N` when the history is shorter than three) are
    `UNSATISFACTORY`; this variant is sticky — one new satisfactory grading
    cannot clear it while the window still holds two unsuccessful events — so
    a sequence of unsuccessful, unsuccessful, satisfactory heals per-event
    standing but leaves rolling standing `UNSATISFACTORY`."

    Design: Difficulty/dual_variant_calc/pt_standing_per_event_vs_rolling_uus_sequence
    """
    ctx = _uus_history(api)
    enr = get_success_data(api.get_enrollment(ctx["enrollment"]["id"], OFFICER))
    assert enr["standing_per_event"] == "SATISFACTORY"
    assert enr["standing_rolling"] == "UNSATISFACTORY"
    # PRD §3.2: the streak "counts the consecutive most-recent graded results
    # that were unsuccessful and resets to zero on a satisfactory event" — the
    # trailing S in the U,U,S sequence resets it.
    assert enr["unsuccessful_event_streak"] == 0
    assert len(list_investigations(ctx["enrollment"]["id"])) == 2


def test_pt_standing_per_event_heals_and_streak_resets_on_satisfactory(api):
    """PRD §3.2: "`standing_per_event` is `UNSATISFACTORY` if the most recent
    element of that sequence was `UNSATISFACTORY`, otherwise `SATISFACTORY` (an
    empty history reads `SATISFACTORY`); this variant reacts to every event and
    self-heals on the next satisfactory grading."
    PRD §3.2: "`unsuccessful_event_streak` counts the consecutive most-recent
    graded results that were unsuccessful and resets to zero on a satisfactory
    event."

    Design: Difficulty/dual_variant_calc/pt_standing_per_event_vs_rolling_uus_sequence
    """
    analytes = [{"name": "glucose", "critical": True}]
    ctx = setup_pt_active_enrollment(analytes=analytes)
    lab_id = ctx["lab"]["id"]
    sub_id = ctx["subscription"]["id"]

    sh1 = create_shipment(sub_id, event_code="C-2026-A")
    submit_result_ok(sh1["id"], lab_id, [{"name": "glucose", "score": 50}])
    enr_mid = get_success_data(api.get_enrollment(ctx["enrollment"]["id"], OFFICER))
    assert enr_mid["standing_per_event"] == "UNSATISFACTORY"
    assert enr_mid["unsuccessful_event_streak"] == 1

    # Resolve the auto-investigation, close the shipment, then grade S.
    inv1 = list_investigations(ctx["enrollment"]["id"])[0]
    get_success_data(api.resolve_investigation(inv1["id"], OFFICER))
    get_success_data(api.close_pt_shipment(sh1["id"], PTC))
    sh2 = create_shipment(sub_id, event_code="C-2026-B")
    submit_result_ok(sh2["id"], lab_id, [{"name": "glucose", "score": 95}],
                     collected_at="2026-09-02T12:00:00Z")

    enr = get_success_data(api.get_enrollment(ctx["enrollment"]["id"], OFFICER))
    assert enr["standing_per_event"] == "SATISFACTORY"
    assert enr["unsuccessful_event_streak"] == 0


def test_cease_enrollment_blocks_new_pt_subscription(api):
    """PRD §3.2: "Subscribing a non-active enrollment fails with
    `ERR_ENROLLMENT_INACTIVE`."
    PRD §3.3: "Cessation cascades the parent enrollment to `CEASED` and
    recomputes the laboratory's `active_discipline_count`."

    Design: Corner/state_machines/cease_enrollment_blocks_new_pt_subscription
    """
    ctx = setup_rolling_unsatisfactory_enrollment(
        analytes=[{"name": "glucose", "critical": True}])
    get_success_data(api.cease_testing(ctx["inv2"]["id"], OFFICER))
    enr = get_success_data(api.get_enrollment(ctx["enrollment"]["id"], OFFICER))
    assert enr["status"] == "CEASED"

    resp = api.create_pt_subscription(
        {"enrollment_id": ctx["enrollment"]["id"],
         "analytes": [{"name": "sodium", "critical": True}]},
        make_director_headers(ctx["lab"]["id"]))
    validate_error(resp, ApiErrorId.ERR_ENROLLMENT_INACTIVE.value, 409)


def test_investigation_terminal_lockdown(api):
    """PRD §3.3: "Beginning review moves an investigation from `OPEN` to
    `UNDER_REVIEW`; any other source state is rejected with
    `ERR_INVALID_INVESTIGATION_STATE`."
    PRD §3.3: "An `AccreditationOfficer` drives each one through a small state
    machine whose terminal states are `RESOLVED` and `TESTING_CEASED`."

    Design: Corner/state_machines/investigation_terminal_lockdown
    """
    ctx = setup_single_unsatisfactory_event(
        analytes=[{"name": "glucose", "critical": True}])
    inv = ctx["investigation"]
    get_success_data(api.resolve_investigation(inv["id"], OFFICER))

    for action in (
        lambda: api.begin_review(inv["id"], OFFICER),
        lambda: api.require_corrective_action(
            inv["id"], {"corrective_action_notes": "Plan."}, OFFICER),
        lambda: api.resolve_investigation(inv["id"], OFFICER),
        lambda: api.cease_testing(inv["id"], OFFICER),
    ):
        resp = action()
        validate_error(resp, ApiErrorId.ERR_INVALID_INVESTIGATION_STATE.value, 409)

    after = get_success_data(api.get_pt_investigation(inv["id"], OFFICER))
    assert after["status"] == "RESOLVED"


def test_cease_testing_requires_rolling_unsatisfactory_standing(api):
    """PRD §3.3: "Ceasing testing is the severe remedy, available from `OPEN`
    or `UNDER_REVIEW` only (any other source state fails with
    `ERR_INVALID_INVESTIGATION_STATE`), and only while the enrollment's
    `standing_rolling` is `UNSATISFACTORY` — otherwise the request fails with
    `ERR_CESSATION_REQUIRES_ROLLING_UNSATISFACTORY`."

    Design: Corner/state_machines/cease_testing_requires_rolling_unsatisfactory_standing
    """
    ctx = setup_single_unsatisfactory_event(
        analytes=[{"name": "glucose", "critical": True}])
    enr = get_success_data(api.get_enrollment(ctx["enrollment"]["id"], OFFICER))
    assert enr["standing_per_event"] == "UNSATISFACTORY"
    assert enr["standing_rolling"] == "SATISFACTORY"

    resp = api.cease_testing(ctx["investigation"]["id"], OFFICER)
    validate_error(
        resp, ApiErrorId.ERR_CESSATION_REQUIRES_ROLLING_UNSATISFACTORY.value, 409)
    inv_after = get_success_data(
        api.get_pt_investigation(ctx["investigation"]["id"], OFFICER))
    assert inv_after["status"] == "OPEN"
    enr_after = get_success_data(api.get_enrollment(ctx["enrollment"]["id"], OFFICER))
    assert enr_after["status"] == "ACTIVE"


def test_resolve_from_corrective_action_restores_enrollment_and_streak(api):
    """PRD §3.3: "Resolving from `CORRECTIVE_ACTION_REQUIRED` returns the parent
    enrollment to `ACTIVE`, recomputes the laboratory's
    `active_discipline_count`, and resets the enrollment's
    `unsuccessful_event_streak` to zero."
    PRD §3.3: "In all three cases the standing fields are deliberately left
    alone: `standing_per_event` and `standing_rolling` are functions of graded
    history and are not cleared by resolution."

    Design: Corner/state_machines/resolve_from_corrective_action_restores_enrollment_and_streak
    """
    ctx = setup_single_unsatisfactory_event(
        analytes=[{"name": "glucose", "critical": True}])
    inv = ctx["investigation"]
    get_success_data(api.begin_review(inv["id"], OFFICER))
    get_success_data(api.require_corrective_action(
        inv["id"],
        {"corrective_action_notes": "Root cause: reagent lot swap. Plan: retrain + recalibrate."},
        OFFICER))
    enr_mid = get_success_data(api.get_enrollment(ctx["enrollment"]["id"], OFFICER))
    assert enr_mid["status"] == "SUSPENDED"

    get_success_data(api.resolve_investigation(inv["id"], OFFICER))
    inv_after = get_success_data(api.get_pt_investigation(inv["id"], OFFICER))
    assert inv_after["status"] == "RESOLVED"
    enr_after = get_success_data(api.get_enrollment(ctx["enrollment"]["id"], OFFICER))
    assert enr_after["status"] == "ACTIVE"
    assert enr_after["unsuccessful_event_streak"] == 0
    assert enr_after["standing_per_event"] == "UNSATISFACTORY"


def test_cease_testing_cascades_investigation_to_enrollment_and_lab_count(api):
    """PRD §3.3: "Cessation cascades the parent enrollment to `CEASED` and
    recomputes the laboratory's `active_discipline_count`."
    PRD §2.6: "Whenever any enrollment's `status` changes for any reason, the
    parent laboratory's `active_discipline_count` is recomputed as the number
    of that laboratory's enrollments whose `status` is `ACTIVE`."

    Design: Difficulty/transitive_cascade/cease_testing_cascades_investigation_to_enrollment_and_lab_count
    """
    # Two ACTIVE enrollments on one laboratory: E1 with the PT history, E2 idle.
    ctx = setup_rolling_unsatisfactory_enrollment(
        analytes=[{"name": "glucose", "critical": True}])
    lab_id = ctx["lab"]["id"]
    enr2 = api.create_enrollment(
        {"laboratory_id": lab_id, "discipline": "TRANSFUSION"},
        make_director_headers(lab_id))
    from test_helpers import create_section_for_enrollment, register_checklist_edition, assign_checklist_to_section
    sec2 = create_section_for_enrollment(
        get_success_data(enr2)["id"], lab_id, section_name="Blood Bank",
        critical_testing=True)
    register_checklist_edition("TRF", "2026")
    assign_checklist_to_section(sec2["id"], "TRF", "2026")

    lab_before = get_success_data(api.get_laboratory(lab_id, OFFICER))
    assert lab_before["active_discipline_count"] == 2

    get_success_data(api.begin_review(ctx["inv2"]["id"], OFFICER))
    get_success_data(api.cease_testing(ctx["inv2"]["id"], OFFICER))

    inv_after = get_success_data(api.get_pt_investigation(ctx["inv2"]["id"], OFFICER))
    assert inv_after["status"] == "TESTING_CEASED"
    enr1_after = get_success_data(api.get_enrollment(ctx["enrollment"]["id"], OFFICER))
    assert enr1_after["status"] == "CEASED"
    enr2_after = get_success_data(api.get_enrollment(get_success_data(enr2)["id"], OFFICER))
    assert enr2_after["status"] == "ACTIVE"
    lab_after = get_success_data(api.get_laboratory(lab_id, OFFICER))
    assert lab_after["active_discipline_count"] == 1


def test_cease_testing_from_open_also_ceases_enrollment(api):
    """PRD §3.3: "Ceasing testing is the severe remedy, available from `OPEN`
    or `UNDER_REVIEW` only (any other source state fails with
    `ERR_INVALID_INVESTIGATION_STATE`), and only while the enrollment's
    `standing_rolling` is `UNSATISFACTORY` — otherwise the request fails with
    `ERR_CESSATION_REQUIRES_ROLLING_UNSATISFACTORY`. Cessation cascades the
    parent enrollment to `CEASED` and recomputes the laboratory's
    `active_discipline_count`."

    Design: Difficulty/transitive_cascade/cease_testing_cascades_investigation_to_enrollment_and_lab_count
    """
    ctx = setup_rolling_unsatisfactory_enrollment(
        analytes=[{"name": "glucose", "critical": True}])
    # Cease directly from OPEN (no begin-review).
    get_success_data(api.cease_testing(ctx["inv2"]["id"], OFFICER))
    inv_after = get_success_data(api.get_pt_investigation(ctx["inv2"]["id"], OFFICER))
    assert inv_after["status"] == "TESTING_CEASED"
    enr_after = get_success_data(api.get_enrollment(ctx["enrollment"]["id"], OFFICER))
    assert enr_after["status"] == "CEASED"


def test_active_discipline_count_invariant_under_suspend_restore(api):
    """PRD §2.6: "Whenever any enrollment's `status` changes for any reason, the
    parent laboratory's `active_discipline_count` is recomputed as the number
    of that laboratory's enrollments whose `status` is `ACTIVE`."
    PRD §3.3: "Resolving from `CORRECTIVE_ACTION_REQUIRED` returns the parent
    enrollment to `ACTIVE`, recomputes the laboratory's
    `active_discipline_count`, and resets the enrollment's
    `unsuccessful_event_streak` to zero."

    Design: Difficulty/compensating_invariant/active_discipline_count_invariant_under_suspend_restore
    """
    ctx = setup_single_unsatisfactory_event(
        analytes=[{"name": "glucose", "critical": True}])
    lab_id = ctx["lab"]["id"]
    enr2 = get_success_data(api.create_enrollment(
        {"laboratory_id": lab_id, "discipline": "MOLECULAR"},
        make_director_headers(lab_id)))
    from test_helpers import create_section_for_enrollment, register_checklist_edition, assign_checklist_to_section
    sec2 = create_section_for_enrollment(enr2["id"], lab_id, section_name="PCR")
    register_checklist_edition("MOL", "2026")
    assign_checklist_to_section(sec2["id"], "MOL", "2026")

    lab_before = get_success_data(api.get_laboratory(lab_id, OFFICER))
    assert lab_before["active_discipline_count"] == 2

    inv = ctx["investigation"]
    get_success_data(api.begin_review(inv["id"], OFFICER))
    get_success_data(api.require_corrective_action(
        inv["id"],
        {"corrective_action_notes": "Retrain staff; recalibrate analyzer."},
        OFFICER))
    lab_mid = get_success_data(api.get_laboratory(lab_id, OFFICER))
    assert lab_mid["active_discipline_count"] == 1
    enr1_mid = get_success_data(api.get_enrollment(ctx["enrollment"]["id"], OFFICER))
    assert enr1_mid["status"] == "SUSPENDED"
    enr2_mid = get_success_data(api.get_enrollment(enr2["id"], OFFICER))
    assert enr2_mid["status"] == "ACTIVE"

    get_success_data(api.resolve_investigation(inv["id"], OFFICER))
    lab_end = get_success_data(api.get_laboratory(lab_id, OFFICER))
    assert lab_end["active_discipline_count"] == 2
    enr1_end = get_success_data(api.get_enrollment(ctx["enrollment"]["id"], OFFICER))
    assert enr1_end["status"] == "ACTIVE"
    assert enr1_end["unsuccessful_event_streak"] == 0


def test_require_corrective_action_suspends_only_owning_enrollment(api):
    """PRD §3.3: "This transition carries a hard cross-entity cascade: the
    parent enrollment moves to `SUSPENDED` and the laboratory's
    `active_discipline_count` is recomputed."

    Design: Difficulty/compensating_invariant/active_discipline_count_invariant_under_suspend_restore
    """
    ctx = setup_single_unsatisfactory_event(
        analytes=[{"name": "glucose", "critical": True}])
    lab_id = ctx["lab"]["id"]
    enr2 = get_success_data(api.create_enrollment(
        {"laboratory_id": lab_id, "discipline": "MOLECULAR"},
        make_director_headers(lab_id)))
    from test_helpers import create_section_for_enrollment, register_checklist_edition, assign_checklist_to_section
    sec2 = create_section_for_enrollment(enr2["id"], lab_id, section_name="PCR")
    register_checklist_edition("MOL", "2026")
    assign_checklist_to_section(sec2["id"], "MOL", "2026")

    inv = ctx["investigation"]
    get_success_data(api.begin_review(inv["id"], OFFICER))
    get_success_data(api.require_corrective_action(
        inv["id"], {"corrective_action_notes": "Plan."}, OFFICER))

    enr1 = get_success_data(api.get_enrollment(ctx["enrollment"]["id"], OFFICER))
    assert enr1["status"] == "SUSPENDED"
    enr2_after = get_success_data(api.get_enrollment(enr2["id"], OFFICER))
    assert enr2_after["status"] == "ACTIVE"
    lab = get_success_data(api.get_laboratory(lab_id, OFFICER))
    assert lab["active_discipline_count"] == 1


def test_existence_priority_beats_state_priority(api):
    """PRD §2.7: "Existence checks run before any state, safety, or temporal
    rule is evaluated, so a request to act on a nonexistent section under a
    nonexistent enrollment fails on the enrollment first."
    PRD §2.8: "(3) existence of every referenced identifier (the 404 family);
    (4) state-machine admissibility"

    Design: Corner/validations/existence_priority_beats_state_priority
    """
    resp = api.begin_review(NON_EXISTENT_UUID, OFFICER)
    validate_error(resp, ApiErrorId.ERR_INVESTIGATION_NOT_FOUND.value, 404)
