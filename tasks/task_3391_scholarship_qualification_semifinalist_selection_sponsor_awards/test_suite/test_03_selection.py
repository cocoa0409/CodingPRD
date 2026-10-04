"""Semifinalist selection: thresholds, the inclusive boundary, and the
selection-gated application create — PRD §3.4, §3.5, §3.9.
"""
from test_helpers import (
    ApiErrorId,
    TEST_DEFAULTS,
    TEST_USERS,
    close_entries,
    create_application,
    create_finalist_application_payload,
    get_entry,
    list_notifications,
    list_state_allocations,
    make_student_headers,
    run_semifinalist_selection,
    score_entry,
    setup_entry_closed,
    setup_semifinalists_selected,
    validate_error,
    validate_success,
)

PA = TEST_USERS["program_admin_headers"]

_BND1_SCORES = [
    {"full_name": "B One", "scores": (37, 37, 36)},   # SI 220
    {"full_name": "B Two", "scores": (36, 36, 37)},   # SI 218 (math 37)
    {"full_name": "B Three", "scores": (37, 37, 35)},  # SI 218 (math 35)
    {"full_name": "B Four", "scores": (35, 35, 35)},  # SI 210
]


def test_notification_created_embargoed_initial_state(api):
    """PRD §3.4: "each newly selected student's entry spawns a
    `SEMIFINALIST_NOTICE` notification (sequence 1, embargoed until the
    cycle's `semifinalist_embargo_until`)". PRD §3.9: "Every notification
    starts `EMBARGOED`, with `released_logical_at` null until release."
    
    Design: Corner/state_machines/notification_created_embargoed_initial_state
    """
    ctx = setup_semifinalists_selected()  # one student, SI 224, slots 5
    notes = list_notifications(ctx["student"]["id"])
    assert len(notes) == 1
    note = notes[0]
    assert note["notice_type"] == "SEMIFINALIST_NOTICE"
    assert note["sequence_number"] == 1
    assert note["status"] == "EMBARGOED"
    assert note["embargo_until"] == TEST_DEFAULTS["SEMIFINALIST_EMBARGO_UNTIL"]
    assert note["released_logical_at"] is None


def test_unscored_entries_block_selection_rejected(api):
    """PRD §3.4: "The selection run refuses to fire while any entry of the cycle
    is still `SUBMITTED` — the rejection is `ERR_UNSCORED_ENTRIES_REMAIN`
    (HTTP 409)."
    
    Design: Corner/errors/unscored_entries_block_selection_rejected
    """
    ctx = setup_entry_closed(score=False)  # one SUBMITTED entry blocks the run
    cycle_id = ctx["cycle"]["id"]
    resp = api.run_semifinalist_selection(cycle_id, PA)
    validate_error(resp, ApiErrorId.ERR_UNSCORED_ENTRIES_REMAIN)
    score_entry(ctx["entry"]["id"], 37, 37, 38)
    result = run_semifinalist_selection(cycle_id)
    assert result["selected_total"] == 1


def test_threshold_tie_inflates_selected_count(api):
    """PRD §3.4: "Every candidate whose `selection_index` is at least the
    threshold flips `SCORED` → `SELECTED_SEMIFINALIST` — the boundary is
    inclusive, so a tie at the threshold selects more than `slots_final`
    candidates and a state's `selected_count` may exceed its `slots_final`".
    
    Design: Difficulty/boundary_precision_check/threshold_inclusion_is_gte_with_tie_inflation
    """
    ctx = setup_entry_closed(
        student_specs=_BND1_SCORES, cycle_overrides={"total_semifinalist_slots": 2}
    )
    result = run_semifinalist_selection(ctx["cycle"]["id"])
    assert result["selected_total"] == 3, (
        "the inclusive >= threshold must admit both 218-scorers, not just 2"
    )
    alloc = list_state_allocations(ctx["cycle"]["id"])[0]
    assert alloc["state_code"] == "ZZ"
    assert alloc["slots_final"] == 2
    assert alloc["threshold_selection_index"] == 218
    assert alloc["selected_count"] == 3 > alloc["slots_final"]


def test_threshold_tie_per_entry_outcomes(api):
    """PRD §3.4: "Candidates rank by `selection_index` descending, ties broken by
    `math_score` descending, then `reading_score` descending, then
    `created_at` ascending — never by `id` ... otherwise
    `threshold_selection_index` is the `selection_index` of the k-th ranked
    candidate", and "while every candidate below the threshold flips `SCORED`
    → `NOT_SELECTED`".
    
    Design: Difficulty/boundary_precision_check/threshold_inclusion_is_gte_with_tie_inflation
    """
    ctx = setup_entry_closed(
        student_specs=_BND1_SCORES, cycle_overrides={"total_semifinalist_slots": 2}
    )
    run_semifinalist_selection(ctx["cycle"]["id"])
    entries = [get_entry(e["id"]) for e in ctx["entries"]]
    by_name = dict(zip(["B One", "B Two", "B Three", "B Four"], entries))
    assert by_name["B One"]["selection_index"] == 220
    assert by_name["B Two"]["selection_index"] == 218
    assert by_name["B Three"]["selection_index"] == 218
    assert by_name["B Four"]["selection_index"] == 210
    assert by_name["B One"]["status"] == "SELECTED_SEMIFINALIST"
    assert by_name["B Two"]["status"] == "SELECTED_SEMIFINALIST"
    assert by_name["B Three"]["status"] == "SELECTED_SEMIFINALIST"
    assert by_name["B Four"]["status"] == "NOT_SELECTED"


def test_application_for_not_selected_entry_rejected(api):
    """PRD §3.5: "The entry must be `SELECTED_SEMIFINALIST`: creating an
    application for an entry that never made semifinalist is
    `ERR_ENTRY_NOT_SEMIFINALIST` (HTTP 409)".
    
    Design: Difficulty/cross_entity_state_dependency/application_gated_by_entry_selection
    """
    ctx = setup_semifinalists_selected(
        student_specs=[
            {"full_name": "S One", "scores": (37, 37, 36)},  # SI 220
            {"full_name": "S Two", "scores": (35, 35, 35)},  # SI 210
        ],
        cycle_overrides={"total_semifinalist_slots": 1},
    )
    e1, e2 = ctx["entries"]
    assert e1["status"] == "SELECTED_SEMIFINALIST"
    assert e2["status"] == "NOT_SELECTED"
    s2 = ctx["students"][1]
    resp = api.create_finalist_application(
        create_finalist_application_payload(e2["id"], gpa_scaled=3.9),
        make_student_headers(s2["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_ENTRY_NOT_SEMIFINALIST)


def test_application_for_selected_entry_accepted(api):
    """PRD §3.5: "a `Student` creates a `FinalistApplication` for one of their
    own entries" once "the cycle reaches `SEMIFINALISTS_SELECTED`", and "the
    application starts `IN_PROGRESS`".
    
    Design: Difficulty/cross_entity_state_dependency/application_gated_by_entry_selection
    """
    ctx = setup_semifinalists_selected(
        student_specs=[
            {"full_name": "S One", "scores": (37, 37, 36)},
            {"full_name": "S Two", "scores": (35, 35, 35)},
        ],
        cycle_overrides={"total_semifinalist_slots": 1},
    )
    e1, s1 = ctx["entries"][0], ctx["students"][0]
    resp = api.create_finalist_application(
        create_finalist_application_payload(e1["id"], gpa_scaled=3.8,
                                            course_rigor="ADVANCED",
                                            confirming_selection_index=208),
        make_student_headers(s1["id"]),
    )
    app = validate_success(resp, 201)
    assert app["status"] == "IN_PROGRESS"
    assert app["entry_id"] == e1["id"]
    assert app["student_id"] == s1["id"]
