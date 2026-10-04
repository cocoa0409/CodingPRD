"""Difficulty queue: homogeneity boundary precision and the retest cycle."""
from test_helpers import (
    make_lot, make_metrologist_headers, make_program, validate_success,
)

FAIL_PAYLOAD = {"to": "HOMOGENEITY_TESTING", "bottle_means": [7.0, 7.0, 13.0, 13.0],
                "within_bottle_std": 1.0, "replicates_per_bottle": 2}
PASS_PAYLOAD = {"to": "HOMOGENEITY_TESTING", "bottle_means": [10.0, 10.0, 10.0, 10.0],
                "within_bottle_std": 0.5, "replicates_per_bottle": 2}


def _run(api, lot_id, payload):
    return validate_success(
        api.transition_material_lot(lot_id, payload, make_metrologist_headers("met-op"))
    )


def test_f_ratio_exactly_critical_passes(api):
    """PRD §3.2: "The lot's `homogeneity_verdict` is `PASS` when the ratio is at
    most the critical value `F_CRITICAL` of 3.0, and `FAIL` otherwise".
    PRD §3.2: "When the verdict is `PASS`, the same request auto-advances the
    lot to `VALUE_ASSIGNMENT`".

    Design: Difficulty/boundary_precision_check/homogeneity_f_ratio_exactly_critical
    """
    program = make_program(program_code="NIST-RM-11")
    lot = make_lot(program["id"], material_code="SRM-J1", total_units_produced=20)
    data = _run(api, lot["id"], {"to": "HOMOGENEITY_TESTING",
                                 "bottle_means": [7.0, 7.0, 13.0, 13.0],
                                 "within_bottle_std": 2.0, "replicates_per_bottle": 2})
    assert data["homogeneity_f_ratio"] == 3.0
    assert data["homogeneity_verdict"] == "PASS"
    assert data["status"] == "VALUE_ASSIGNMENT"
    assert data["homogeneity_u_hom"] == 3.162278


def test_f_ratio_above_critical_fails(api):
    """PRD §3.2: "The lot's `homogeneity_verdict` is `PASS` when the ratio is at
    most the critical value `F_CRITICAL` of 3.0, and `FAIL` otherwise".
    PRD §3.2: "on `FAIL` the lot remains in `HOMOGENEITY_TESTING`".

    Design: Difficulty/boundary_precision_check/homogeneity_f_ratio_exactly_critical
    """
    program = make_program(program_code="NIST-RM-11B")
    lot = make_lot(program["id"], material_code="SRM-J2", total_units_produced=20)
    data = _run(api, lot["id"], {"to": "HOMOGENEITY_TESTING",
                                 "bottle_means": [7.0, 7.0, 13.0, 14.0],
                                 "within_bottle_std": 2.0, "replicates_per_bottle": 2})
    assert data["homogeneity_f_ratio"] == 3.5625
    assert data["homogeneity_verdict"] == "FAIL"
    assert data["status"] == "HOMOGENEITY_TESTING"


def test_retest_cycle_statuses(api):
    """PRD §3.2: "on `FAIL` the lot remains in `HOMOGENEITY_TESTING`, where the
    `Metrologist` may retest it through the same self-loop transition with fresh
    payload — the new statistics overwrite the old".
    PRD §3.2: "A lot already in `VALUE_ASSIGNMENT` may likewise be cycled back
    through homogeneity testing; a passing verdict returns it to
    `VALUE_ASSIGNMENT`, while a failing one strands it in `HOMOGENEITY_TESTING`
    until a retest passes."

    Design: Difficulty/non_linear_state_machine/lot_value_assignment_retest_cycle
    """
    program = make_program(program_code="NIST-RM-05")
    lot = make_lot(program["id"], material_code="SRM-F", total_units_produced=20)
    r1 = _run(api, lot["id"], FAIL_PAYLOAD)
    assert r1["status"] == "HOMOGENEITY_TESTING"
    assert r1["homogeneity_verdict"] == "FAIL"
    assert r1["homogeneity_f_ratio"] == 12.0
    r2 = _run(api, lot["id"], PASS_PAYLOAD)
    assert r2["status"] == "VALUE_ASSIGNMENT"
    r3 = _run(api, lot["id"], FAIL_PAYLOAD)
    assert r3["status"] == "HOMOGENEITY_TESTING"
    r4 = _run(api, lot["id"], PASS_PAYLOAD)
    assert r4["status"] == "VALUE_ASSIGNMENT"


def test_retest_cycle_accumulates_qc_and_overwrites_stats(api):
    """PRD §3.2: "each tested bottle is added to `qc_units_consumed`" and "the
    new statistics overwrite the old, bottles keep accumulating in
    `qc_units_consumed`".
    PRD §3.2: "its `units_available` always derives as the produced total minus
    those three counters."

    Design: Difficulty/non_linear_state_machine/lot_value_assignment_retest_cycle
    """
    program = make_program(program_code="NIST-RM-05B")
    lot = make_lot(program["id"], material_code="SRM-F2", total_units_produced=20)
    _run(api, lot["id"], FAIL_PAYLOAD)
    _run(api, lot["id"], PASS_PAYLOAD)
    _run(api, lot["id"], FAIL_PAYLOAD)
    r4 = _run(api, lot["id"], PASS_PAYLOAD)
    assert r4["status"] == "VALUE_ASSIGNMENT"
    assert r4["homogeneity_f_ratio"] == 0.0
    assert r4["qc_units_consumed"] == 16
    assert r4["units_available"] == 4
