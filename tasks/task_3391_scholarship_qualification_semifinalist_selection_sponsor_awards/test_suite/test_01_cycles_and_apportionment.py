"""Cycle creation, StateAllocation children, and the two apportionment
variants (provisional at close-entries vs final at selection) — PRD §3.1-3.2.
"""
import pytest

from test_helpers import (
    close_entries,
    create_cycle,
    list_state_allocations,
    open_entries,
    run_semifinalist_selection,
    validate_success,
    api_client,
    TEST_USERS,
)

PA = TEST_USERS["program_admin_headers"]

_CYC3_POPS = [
    {"state_code": "AA", "graduating_population": 4500},
    {"state_code": "BB", "graduating_population": 2500},
    {"state_code": "CC", "graduating_population": 3000},
]
_CYC4_POPS = [
    {"state_code": "AA", "graduating_population": 4600},
    {"state_code": "BB", "graduating_population": 4400},
    {"state_code": "CC", "graduating_population": 600},
    {"state_code": "DD", "graduating_population": 400},
]


def _by_state(rows):
    return {row["state_code"]: row for row in rows}


def test_cycle_creation_makes_state_allocation_children(api):
    """PRD §3.1: "one `StateAllocation` child is created per entry in it —
    recording the state's `state_code`, its projected `graduating_population`
    (zero or more), and its owning `cycle_id`, starting in `PENDING` status",
    and "A new cycle starts in `SETUP` posture with `matching_run` false and
    `version` 1". PRD §2.3: "a cycle's state allocations are returned sorted
    by `state_code` ascending".
    
    Design: Corner/entities/program_cycle_creation_makes_state_allocation_children
    """
    resp = api.create_program_cycle(
        {
            "name": "CYC-C1",
            "target_graduation_year": 2028,
            "total_semifinalist_slots": 10,
            "national_award_slots": 0,
            "national_award_amount_cents": 250000,
            "confirming_floor": 200,
            "application_deadline": "2027-12-15T00:00:00Z",
            "semifinalist_embargo_until": "2027-09-10T00:00:00Z",
            "finalist_embargo_until": "2028-02-10T00:00:00Z",
            "award_embargo_until": "2028-03-01T00:00:00Z",
            "public_embargo_until": "2028-03-01T00:00:00Z",
            "state_populations": [
                {"state_code": "AA", "graduating_population": 4500},
                {"state_code": "BB", "graduating_population": 2500},
            ],
        },
        PA,
    )
    cycle = validate_success(resp, 201)
    assert cycle["status"] == "SETUP"
    assert cycle["version"] == 1
    assert cycle["matching_run"] is False

    rows = list_state_allocations(cycle["id"])
    assert [r["state_code"] for r in rows] == ["AA", "BB"], (
        "state allocations must be sorted state_code ascending"
    )
    aa, bb = rows
    assert aa["graduating_population"] == 4500
    assert bb["graduating_population"] == 2500
    for row in rows:
        assert row["cycle_id"] == cycle["id"]
        assert row["status"] == "PENDING"
        # Computed at close-entries / selection (PRD §3.2) — no value yet.
        assert row["quota_raw"] is None
        assert row["slots_provisional"] is None
        assert row["slots_final"] is None
        assert row["threshold_selection_index"] is None
        assert row["selected_count"] == 0


def test_provisional_apportionment_at_close_entries(api):
    """PRD §3.2: "The provisional variant of the allocation then sets each
    state's `slots_provisional` to its `quota_raw` rounded half up to a whole
    slot and flips the allocation `PENDING` → `PROVISIONAL`", and "The
    provisional sum across states may exceed or fall short of
    `total_semifinalist_slots`".
    
    Design: Difficulty/dual_variant_calc/state_slot_provisional_vs_final_apportionment
    """
    cycle = create_cycle(
        name="CYC3", total_semifinalist_slots=10, state_populations=_CYC3_POPS
    )
    open_entries(cycle["id"])
    close_entries(cycle["id"])

    rows = _by_state(list_state_allocations(cycle["id"]))
    assert rows["AA"]["quota_raw"] == pytest.approx(4.5, abs=1e-9)
    assert rows["BB"]["quota_raw"] == pytest.approx(2.5, abs=1e-9)
    assert rows["CC"]["quota_raw"] == pytest.approx(3.0, abs=1e-9)
    # round_half_up per state: 5 / 3 / 3; the sum overshoots the total.
    assert rows["AA"]["slots_provisional"] == 5
    assert rows["BB"]["slots_provisional"] == 3
    assert rows["CC"]["slots_provisional"] == 3
    assert sum(r["slots_provisional"] for r in rows.values()) == 11
    assert 11 > cycle["total_semifinalist_slots"] == 10
    for row in rows.values():
        assert row["status"] == "PROVISIONAL"
        assert row["slots_final"] is None


def test_final_apportionment_sums_to_total_at_selection(api):
    """PRD §3.2: "The resulting `slots_final` per state sums to exactly
    `total_semifinalist_slots`, and an individual state may receive fewer
    slots than its provisional figure suggested. The run flips every
    allocation `PROVISIONAL` → `FINAL`". PRD §3.4: "a state with zero
    candidates takes a null `threshold_selection_index` and selects nobody".
    
    Design: Difficulty/dual_variant_calc/state_slot_provisional_vs_final_apportionment
    """
    cycle = create_cycle(
        name="CYC3", total_semifinalist_slots=10, state_populations=_CYC3_POPS
    )
    open_entries(cycle["id"])
    close_entries(cycle["id"])
    result = run_semifinalist_selection(cycle["id"])

    assert result["selected_total"] == 0
    assert result["states_finalized"] == 3
    rows = _by_state(list_state_allocations(cycle["id"]))
    # Largest remainder with MIN_STATE_SLOTS=1: bases 4/2/3, the single
    # remainder seat breaks the .5/.5 tie toward AA (larger population).
    assert rows["AA"]["slots_final"] == 5
    assert rows["BB"]["slots_final"] == 2  # one fewer than its provisional 3
    assert rows["CC"]["slots_final"] == 3
    assert sum(r["slots_final"] for r in rows.values()) == 10
    for row in rows.values():
        assert row["status"] == "FINAL"
        assert row["threshold_selection_index"] is None
        assert row["selected_count"] == 0


def test_largest_remainder_quotas_and_provisional_rounding(api):
    """PRD §3.2: quota_raw is "an exact rational quotient, stored rounded half up
    to 4 decimal places", and the provisional variant is "its `quota_raw`
    rounded half up to a whole slot".
    
    Design: Difficulty/combinatorial_formula/largest_remainder_min_guarantee_redistribution
    """
    cycle = create_cycle(
        name="CYC4", total_semifinalist_slots=10, state_populations=_CYC4_POPS
    )
    open_entries(cycle["id"])
    close_entries(cycle["id"])

    rows = _by_state(list_state_allocations(cycle["id"]))
    assert rows["AA"]["quota_raw"] == pytest.approx(4.6, abs=1e-9)
    assert rows["BB"]["quota_raw"] == pytest.approx(4.4, abs=1e-9)
    assert rows["CC"]["quota_raw"] == pytest.approx(0.6, abs=1e-9)
    assert rows["DD"]["quota_raw"] == pytest.approx(0.4, abs=1e-9)
    assert rows["AA"]["slots_provisional"] == 5
    assert rows["BB"]["slots_provisional"] == 4
    assert rows["CC"]["slots_provisional"] == 1
    assert rows["DD"]["slots_provisional"] == 0


def test_largest_remainder_min_guarantee_redistribution(api):
    """PRD §3.2: "Each state's base is, when its `graduating_population` is
    greater than zero, the larger of the minimum state guarantee
    `MIN_STATE_SLOTS` (exactly 1) and its `quota_raw` rounded down to a whole
    slot ... The remainder — `total_semifinalist_slots` minus the sum of the
    bases — is then distributed one seat at a time, each seat going to the
    state with the largest fractional remainder".
    
    Design: Difficulty/combinatorial_formula/largest_remainder_min_guarantee_redistribution
    """
    cycle = create_cycle(
        name="CYC4", total_semifinalist_slots=10, state_populations=_CYC4_POPS
    )
    open_entries(cycle["id"])
    close_entries(cycle["id"])
    run_semifinalist_selection(cycle["id"])

    rows = _by_state(list_state_allocations(cycle["id"]))
    # Guarantee forces DD 0 -> 1; with bases 4/4/1/1 summing to 10 there is no
    # remainder seat, so AA drops from its provisional 5 to a final 4.
    assert rows["AA"]["slots_final"] == 4
    assert rows["BB"]["slots_final"] == 4
    assert rows["CC"]["slots_final"] == 1
    assert rows["DD"]["slots_final"] == 1  # MIN_STATE_SLOTS guarantee
    assert sum(r["slots_final"] for r in rows.values()) == 10
    assert all(r["status"] == "FINAL" for r in rows.values())
