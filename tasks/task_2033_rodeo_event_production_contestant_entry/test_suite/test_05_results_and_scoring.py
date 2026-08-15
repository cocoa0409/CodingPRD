"""Result recording, verification, amendment, and voiding (PRD §3.4)."""
from test_helpers import (
    ApiErrorId,
    assert_run_result,
    assignment_for_entry,
    create_run_result_payload,
    get_animal,
    get_assignment,
    get_entry,
    get_success_data,
    make_judge_headers,
    record_rough_result,
    record_timed_result,
    register_judge,
    setup_in_progress,
    TEST_USERS,
    transition_result,
    validate_error,
    validate_success,
    verify_result,
)

ADMIN = TEST_USERS["committee_admin_headers"]


def test_unassigned_judge_rejected_assigned_judge_records_rough(api):
    """PRD §3.4: "Only a `Judge` records results, and only for outs in
    performances they are assigned to. ... an acting judge who holds no
    assignment for the result's performance is rejected with
    `ERR_JUDGE_NOT_ASSIGNED`." and "the server stamps the result's `judge_id`
    from the caller's `X-User-ID`".

    Design: Difficulty/cross_entity_state_dependency/run_result_requires_assigned_judge
    """
    sc = setup_in_progress(
        event_code="BULL_RIDING", num_contestants=1, animal_tags=("A100",),
        event_overrides={"per_performance_slots": 5},
        judge_card="J-13B", card_prefix="PRCA-131",
    )
    assigned = sc["judge"]
    unassigned = register_judge("J-13A", "Judge Un", "PRCA_CARD")
    da = assignment_for_entry(sc["entries"][0]["id"])

    blocked = api.create_run_result(
        create_run_result_payload(da["id"], judge_1_score=41, judge_2_score=40),
        make_judge_headers(unassigned["id"]),
    )
    validate_error(blocked, ApiErrorId.ERR_JUDGE_NOT_ASSIGNED)

    recorded = validate_success(
        api.create_run_result(
            create_run_result_payload(da["id"], judge_1_score=41, judge_2_score=40),
            make_judge_headers(assigned["id"]),
        ),
        201,
    )
    assert_run_result(recorded)
    assert recorded["status"] == "RECORDED"
    assert recorded["judge_id"] == assigned["id"]
    assert recorded["total_score"] == 81
    assert recorded["outcome"] == "QUALIFIED"


def test_unassigned_judge_rejected_assigned_judge_records_timed(api):
    """PRD §3.4: "an acting judge who holds no assignment for the result's
    performance is rejected with `ERR_JUDGE_NOT_ASSIGNED`."
    PRD §3.4: "For timed events, `total_time_ms` is the raw time plus the
    penalty."

    Design: Difficulty/cross_entity_state_dependency/run_result_requires_assigned_judge
    """
    sc = setup_in_progress(
        event_code="BARREL_RACING", num_contestants=1, animal_tags=(),
        event_overrides={"per_performance_slots": 5},
        judge_position="TIMER", judge_card="J-13D", card_prefix="PRCA-132",
    )
    assigned = sc["judge"]
    unassigned = register_judge("J-13C", "Judge Un", "PRCA_CARD")
    da = assignment_for_entry(sc["entries"][0]["id"])

    blocked = api.create_run_result(
        create_run_result_payload(da["id"], raw_time_ms=14250),
        make_judge_headers(unassigned["id"]),
    )
    validate_error(blocked, ApiErrorId.ERR_JUDGE_NOT_ASSIGNED)

    recorded = validate_success(
        api.create_run_result(
            create_run_result_payload(da["id"], raw_time_ms=14250),
            make_judge_headers(assigned["id"]),
        ),
        201,
    )
    assert recorded["status"] == "RECORDED"
    assert recorded["judge_id"] == assigned["id"]
    assert recorded["total_time_ms"] == 14250
    assert recorded["outcome"] == "QUALIFIED"


def test_score_payload_on_timed_event_rejected(api):
    """PRD §3.4: "The scoring payload is discipline-specific. A rough-stock
    out takes `judge_1_score` and `judge_2_score`, each an integer from 0 to
    50 inclusive, and must not carry `raw_time_ms`. A timed out takes
    `raw_time_ms` of zero or more milliseconds and must not carry judge
    scores. Sending scores on a timed event, time on a rough-stock event, or
    a score outside its range is rejected with `ERR_SCORE_OUT_OF_RANGE`."

    Design: Corner/validations/score_payload_on_timed_event_rejected
    """
    sc = setup_in_progress(
        event_code="BARREL_RACING", num_contestants=1, animal_tags=(),
        event_overrides={"per_performance_slots": 5},
        judge_position="TIMER", judge_card="J-45", card_prefix="PRCA-450",
    )
    da = assignment_for_entry(sc["entries"][0]["id"])

    wrong_discipline = api.create_run_result(
        create_run_result_payload(da["id"], judge_1_score=40, judge_2_score=40),
        make_judge_headers(sc["judge"]["id"]),
    )
    validate_error(wrong_discipline, ApiErrorId.ERR_SCORE_OUT_OF_RANGE)

    recorded = validate_success(
        api.create_run_result(
            create_run_result_payload(da["id"], raw_time_ms=14250),
            make_judge_headers(sc["judge"]["id"]),
        ),
        201,
    )
    assert recorded["total_time_ms"] == 14250
    assert recorded["outcome"] == "QUALIFIED"
    assert recorded["status"] == "RECORDED"


def test_duplicate_result_on_same_assignment_rejected(api):
    """PRD §3.4: "An assignment may hold at most one live result — a second
    submission while a non-voided result exists for the same
    `draw_assignment_id` is rejected with `ERR_DUPLICATE_RESULT`." and
    "Voiding (`VOID`, a `CommitteeAdmin` action) sends a `RECORDED` or
    `AMENDED` result to `VOIDED`. The assignment stays `PENDING` in both
    cases, so a fresh result may be recorded for the out afterward."

    Design: Corner/validations/duplicate_result_on_same_assignment_rejected
    """
    sc = setup_in_progress(
        event_code="BARREL_RACING", num_contestants=1, animal_tags=(),
        event_overrides={"per_performance_slots": 5},
        judge_position="TIMER", judge_card="J-492", card_prefix="PRCA-492",
    )
    da = assignment_for_entry(sc["entries"][0]["id"])
    first = record_timed_result(da["id"], sc["judge"]["id"], 14250)
    assert first["status"] == "RECORDED"

    dup = api.create_run_result(
        create_run_result_payload(da["id"], raw_time_ms=14100),
        make_judge_headers(sc["judge"]["id"]),
    )
    validate_error(dup, ApiErrorId.ERR_DUPLICATE_RESULT)

    voided = transition_result(first["id"], {"action": "VOID"}, ADMIN)
    assert voided["status"] == "VOIDED"

    replacement = validate_success(
        api.create_run_result(
            create_run_result_payload(da["id"], raw_time_ms=14100),
            make_judge_headers(sc["judge"]["id"]),
        ),
        201,
    )
    assert replacement["total_time_ms"] == 14100
    assert replacement["id"] != first["id"]


def test_voided_result_cannot_be_verified(api):
    """PRD §3.4: "A fresh result is `RECORDED`; its other states are
    `VERIFIED`, `AMENDED`, and `VOIDED`, the last being terminal."
    PRD §2.8: "6. State-machine legality — the requested transition action is
    valid from the resource's current state, including the lockdown of
    terminal states (`ERR_INVALID_STATE`)."

    Design: Corner/state_machines/voided_result_cannot_be_verified
    """
    sc = setup_in_progress(
        event_code="BULL_RIDING", num_contestants=1, animal_tags=("A100",),
        event_overrides={"per_performance_slots": 5},
        judge_card="J-25", card_prefix="PRCA-250",
    )
    da = assignment_for_entry(sc["entries"][0]["id"])
    result = record_rough_result(da["id"], sc["judge"]["id"], 30, 30)
    voided = transition_result(result["id"], {"action": "VOID"}, ADMIN)
    assert voided["status"] == "VOIDED"

    resp = api.run_result_transition(result["id"], {"action": "VERIFY"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    after = get_success_data(api.get_run_result(result["id"], ADMIN), 200)
    assert after["status"] == "VOIDED"
    assert get_assignment(da["id"])["status"] == "PENDING"


def test_result_amend_reverses_out_effects(api):
    """PRD §3.4: "The amendment unwinds the verification: the assignment drops
    back `COMPLETED` → `PENDING`, the animal's welfare counter decrements and
    the animal returns to `DRAWN` from `COMPETED` or `RETIRED`, a completed
    entry reopens to `DRAWN`, and the corrected fields and reason are stored
    with the result now in `AMENDED`."
    PRD §3.4: "Verifying an `AMENDED` result runs the identical cascade, and
    `verified_at` always reflects the latest verification."

    Design: Corner/state_machines/result_amend_reverses_out_effects
    """
    sc = setup_in_progress(
        event_code="BULL_RIDING", num_contestants=1, animal_tags=("A100",),
        event_overrides={"per_performance_slots": 5},
        judge_card="J-51", card_prefix="PRCA-510",
    )
    entry = sc["entries"][0]
    animal = sc["animals"][0]
    da = assignment_for_entry(entry["id"])
    result = record_rough_result(da["id"], sc["judge"]["id"], 40, 40)
    verify_result(result["id"])
    # Forward cascade landed: assignment COMPLETED, animal released (count 1),
    # entry COMPETED.
    assert get_assignment(da["id"])["status"] == "COMPLETED"
    assert get_animal(animal["id"])["welfare_out_count"] == 1
    assert get_entry(entry["id"])["status"] == "COMPETED"

    amended = validate_success(
        api.run_result_transition(
            result["id"],
            {"action": "AMEND", "amendment_reason": "Misread score sheet",
             "judge_1_score": 38, "judge_2_score": 39, "qualified_flag": True},
            make_judge_headers(sc["judge"]["id"]),
        ),
        200,
    )
    assert amended["status"] == "AMENDED"
    assert amended["judge_1_score"] == 38
    assert amended["judge_2_score"] == 39
    assert amended["total_score"] == 77
    assert amended["amendment_reason"] == "Misread score sheet"

    # Compensation across the assignment, the animal, and the entry.
    assert get_assignment(da["id"])["status"] == "PENDING"
    animal_after = get_animal(animal["id"])
    assert animal_after["welfare_out_count"] == 0
    assert animal_after["status"] == "DRAWN"
    assert get_entry(entry["id"])["status"] == "DRAWN"

    # Re-verification re-applies the whole cascade with the corrected fields.
    reverified = verify_result(result["id"])
    assert reverified["status"] == "VERIFIED"
    assert reverified["total_score"] == 77
    animal_final = get_animal(animal["id"])
    assert animal_final["welfare_out_count"] == 1
    assert animal_final["status"] == "AVAILABLE"
    assert get_entry(entry["id"])["status"] == "COMPETED"
