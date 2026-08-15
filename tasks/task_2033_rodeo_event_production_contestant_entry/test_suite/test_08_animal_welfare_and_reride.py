"""Animal welfare cycle, the three-out threshold, and re-ride stock gates
(PRD §2.8, §3.3, §3.5)."""
from test_helpers import (
    ApiErrorId,
    add_animal,
    assignment_for_entry,
    assignments_for_entry,
    create_contract,
    drive_go_round,
    execute_draw,
    file_vet_report,
    get_animal,
    get_assignment,
    get_entry,
    record_rough_result,
    register_and_enter,
    setup_active_stock,
    setup_entries_open,
    setup_in_progress,
    TEST_USERS,
    transition_contract,
    transition_rodeo,
    validate_error,
    verify_result,
)

ADMIN = TEST_USERS["committee_admin_headers"]
OFFICE = TEST_USERS["entry_office_headers"]


def _two_go_round_scenario():
    """BULL_RIDING event with two go-rounds, one rider, one animal; go-round 1
    drawn and the rodeo started. Returns the scenario dict."""
    return setup_in_progress(
        event_code="BULL_RIDING", num_contestants=1, animal_tags=("A100",),
        event_overrides={"go_rounds": 2, "per_performance_slots": 5,
                         "payout_places": 1},
        judge_card="J-5", card_prefix="PRCA-501",
    )


def test_animal_cycles_drawn_competed_available_across_go_rounds(api):
    """PRD §3.3: "The welfare threshold is three outs. Each verified result
    naming the animal moves it `DRAWN` → `COMPETED` and increments
    `welfare_out_count`; if the count has reached three — the boundary is
    inclusive, so exactly three retires — the animal immediately auto-retires
    (`COMPETED` → `RETIRED`), otherwise it auto-releases back to the pen
    (`COMPETED` → `AVAILABLE`)."

    Design: Difficulty/non_linear_state_machine/stock_animal_compete_release_cycle_across_go_rounds
    """
    sc = _two_go_round_scenario()
    entry = sc["entries"][0]
    animal = sc["animals"][0]

    da1 = assignment_for_entry(entry["id"], status="PENDING")
    verify_result(
        record_rough_result(da1["id"], sc["judge"]["id"], 41, 41)["id"]
    )
    after_g1 = get_animal(animal["id"])
    assert after_g1["status"] == "AVAILABLE", (
        f"count 1 < 3: auto-release to the pen, got {after_g1['status']}"
    )
    assert after_g1["welfare_out_count"] == 1
    assert get_entry(entry["id"])["status"] == "DRAWN"

    # The same animal is eligible again and loops AVAILABLE -> DRAWN in G2.
    execute_draw(sc["event"]["id"], go_round_number=2)
    assert get_animal(animal["id"])["status"] == "DRAWN"

    da2 = assignment_for_entry(entry["id"], status="PENDING")
    verify_result(
        record_rough_result(da2["id"], sc["judge"]["id"], 40, 39)["id"]
    )
    after_g2 = get_animal(animal["id"])
    assert after_g2["status"] == "AVAILABLE"
    assert after_g2["welfare_out_count"] == 2


def test_entry_bubbles_to_competed_when_all_rounds_complete(api):
    """PRD §3.2: "One last entry motion is driven entirely by results: when
    every go-round assignment of a `DRAWN` entry reaches `COMPLETED`, the
    entry bubbles up to `COMPETED`".

    Design: Difficulty/non_linear_state_machine/stock_animal_compete_release_cycle_across_go_rounds
    """
    sc = _two_go_round_scenario()
    entry = sc["entries"][0]

    da1 = assignment_for_entry(entry["id"], status="PENDING")
    verify_result(
        record_rough_result(da1["id"], sc["judge"]["id"], 41, 41)["id"]
    )
    # One of two go-round assignments completed: the entry is still DRAWN.
    assert get_entry(entry["id"])["status"] == "DRAWN"

    drive_go_round(sc, 2, rough_scores=[(40, 39, True)])

    assert get_entry(entry["id"])["status"] == "COMPETED"
    completed = assignments_for_entry(entry["id"], status="COMPLETED")
    assert len(completed) == 2, (
        f"both go-round assignments must be COMPLETED, got {len(completed)}"
    )


def test_welfare_threshold_retires_at_third_out(api):
    """PRD §3.3: "The welfare threshold is three outs. Each verified result
    naming the animal moves it `DRAWN` → `COMPETED` and increments
    `welfare_out_count`; if the count has reached three — the boundary is
    inclusive, so exactly three retires — the animal immediately auto-retires
    (`COMPETED` → `RETIRED`), otherwise it auto-releases back to the pen
    (`COMPETED` → `AVAILABLE`)."

    Design: Corner/calculations/welfare_threshold_retires_at_third_out
    """
    sc = setup_in_progress(
        event_code="BULL_RIDING", num_contestants=1, animal_tags=("A100",),
        event_overrides={"go_rounds": 3, "per_performance_slots": 5,
                         "payout_places": 1},
        judge_card="J-32", card_prefix="PRCA-320",
    )
    entry = sc["entries"][0]
    animal = sc["animals"][0]

    da1 = assignment_for_entry(entry["id"], status="PENDING")
    verify_result(
        record_rough_result(da1["id"], sc["judge"]["id"], 40, 40)["id"]
    )
    assert get_animal(animal["id"])["welfare_out_count"] == 1

    drive_go_round(sc, 2, rough_scores=[(40, 40, True)])
    assert get_animal(animal["id"])["welfare_out_count"] == 2
    assert get_animal(animal["id"])["status"] == "AVAILABLE"

    drive_go_round(sc, 3, rough_scores=[(40, 40, True)])
    after_third = get_animal(animal["id"])
    assert after_third["welfare_out_count"] == 3
    assert after_third["status"] == "RETIRED", (
        f"the third out retires the animal (inclusive boundary), got "
        f"{after_third['status']}"
    )


def _reride_dual_violation_scenario(activate_second_contract):
    """One DRAWN entry holding animal A100 under an ACTIVE contract, plus a
    second contract whose animal A900 is made welfare-ineligible; the second
    contract is terminated or left PROPOSED per the flag. Returns
    (assignment, original_animal, spare_animal)."""
    sc = setup_entries_open(
        event_overrides={"event_code": "BULL_RIDING", "per_performance_slots": 10}
    )
    contestants, entries = register_and_enter(sc["event"]["id"], 1,
                                              card_prefix="PRCA-902")
    k1, animals1 = setup_active_stock(sc["rodeo"]["id"], "BULL_RIDING", ["A100"])
    if activate_second_contract:
        k2, animals2 = setup_active_stock(
            sc["rodeo"]["id"], "BULL_RIDING", ["A900"],
            contractor_name="Diamond G",
        )
    else:
        k2 = create_contract(sc["rodeo"]["id"], contractor_name="Diamond G")
        animals2 = [add_animal(k2["id"], "A900", "BULL_RIDING")]
    transition_rodeo(sc["rodeo"]["id"], "LOCK_DRAW")
    execute_draw(sc["event"]["id"], go_round_number=1)
    da = assignment_for_entry(entries[0]["id"])

    spare = animals2[0]
    file_vet_report(
        subject_type="ANIMAL",
        animal_id=spare["id"],
        findings="Shoulder inflammation",
        disposition="INJURED_TURNOUT",
        veterinarian_name="Dr. Ellis",
    )
    if activate_second_contract:
        # Terminating retires the injured animal: it ends RETIRED under a
        # TERMINATED contract — ineligible on both safety and referential
        # grounds.
        transition_contract(k2["id"], "TERMINATE")
    return da, animals1[0], spare


def test_reride_to_retired_animal_on_terminated_contract_reports_safety(api):
    """PRD §2.8: "When several checks could reject the same request, the
    server evaluates them in a fixed order and surfaces the earliest
    failure." with "10. Animal eligibility for stock selection — the animal
    is `AVAILABLE`, under the welfare-out limit, and slated for the matching
    event (`ERR_ANIMAL_NOT_ELIGIBLE`)" ordered before "11. Contract activity —
    the animal's stock contract is `ACTIVE` (`ERR_CONTRACT_NOT_ACTIVE`)".
    PRD §3.5: "The usual stock gates apply — `ERR_ANIMAL_NOT_ELIGIBLE` for an
    ineligible pick and `ERR_CONTRACT_NOT_ACTIVE` when the new animal's
    contract is not active — and the assignment's `version` increments."

    Design: Difficulty/priority_pair_validation_conflict/reride_animal_safety_beats_contract_state
    """
    da, original, spare = _reride_dual_violation_scenario(
        activate_second_contract=True
    )
    assert get_animal(spare["id"])["status"] == "RETIRED"
    version_before = get_assignment(da["id"])["version"]

    resp = api.reride_assignment(da["id"], {"animal_id": spare["id"]}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_ANIMAL_NOT_ELIGIBLE)

    after = get_assignment(da["id"])
    assert after["animal_id"] == original["id"], "no swap may occur on rejection"
    assert after["version"] == version_before


def test_reride_to_injured_animal_on_proposed_contract_reports_safety(api):
    """PRD §2.8: "When several checks could reject the same request, the
    server evaluates them in a fixed order and surfaces the earliest
    failure." with "10. Animal eligibility for stock selection — the animal
    is `AVAILABLE`, under the welfare-out limit, and slated for the matching
    event (`ERR_ANIMAL_NOT_ELIGIBLE`)" ordered before "11. Contract activity —
    the animal's stock contract is `ACTIVE` (`ERR_CONTRACT_NOT_ACTIVE`)".

    Design: Difficulty/priority_pair_validation_conflict/reride_animal_safety_beats_contract_state
    """
    da, original, spare = _reride_dual_violation_scenario(
        activate_second_contract=False
    )
    assert get_animal(spare["id"])["status"] == "INJURED"

    resp = api.reride_assignment(da["id"], {"animal_id": spare["id"]}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_ANIMAL_NOT_ELIGIBLE)

    assert get_assignment(da["id"])["animal_id"] == original["id"]


def test_reride_rejected_when_contract_not_active(api):
    """PRD §3.5: "The usual stock gates apply — `ERR_ANIMAL_NOT_ELIGIBLE` for
    an ineligible pick and `ERR_CONTRACT_NOT_ACTIVE` when the new animal's
    contract is not active — and the assignment's `version` increments."

    Design: Corner/validations/reride_rejected_when_contract_not_active
    """
    sc = setup_entries_open(
        event_overrides={"event_code": "BULL_RIDING", "per_performance_slots": 5}
    )
    contestants, entries = register_and_enter(sc["event"]["id"], 1,
                                              card_prefix="PRCA-493")
    k1, animals1 = setup_active_stock(sc["rodeo"]["id"], "BULL_RIDING", ["A100"])
    k2 = create_contract(sc["rodeo"]["id"], contractor_name="Proposed Co")
    spare = add_animal(k2["id"], "A200", "BULL_RIDING")
    transition_rodeo(sc["rodeo"]["id"], "LOCK_DRAW")
    execute_draw(sc["event"]["id"], go_round_number=1)
    da = assignment_for_entry(entries[0]["id"])

    # The spare animal is AVAILABLE and welfare-eligible; only its contract
    # state (PROPOSED, never activated) blocks the swap.
    assert get_animal(spare["id"])["status"] == "AVAILABLE"
    resp = api.reride_assignment(da["id"], {"animal_id": spare["id"]}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE)

    after = get_assignment(da["id"])
    assert after["animal_id"] == animals1[0]["id"]
    assert get_animal(spare["id"])["status"] == "AVAILABLE"
