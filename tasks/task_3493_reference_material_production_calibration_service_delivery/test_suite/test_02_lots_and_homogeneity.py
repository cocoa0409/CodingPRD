"""Lot creation/defaults, homogeneity assessment, wrong-state and unit gates."""
from test_helpers import (
    ApiErrorId, FAILING_HOMOGENEITY, FLAT_HOMOGENEITY, NON_EXISTENT_UUID,
    assert_lot, assert_lot_unit_conservation, create_material_lot_payload,
    make_lot, make_metrologist_headers, make_program, run_homogeneity,
    validate_error, validate_success,
)


def test_lot_initial_state_sourcing(api):
    """PRD §3.2: "The lot is born in `SOURCING`".

    Design: Corner/state_machines/lot_initial_state_sourcing
    """
    program = make_program(program_code="NIST-RM-C06")
    lot = make_lot(program["id"], material_code="SRM-C6", total_units_produced=5)
    assert_lot(lot)
    assert lot["status"] == "SOURCING"


def test_lot_creation_computed_counters_zero(api):
    """PRD §3.2: "The lot is born in `SOURCING` with its computed counters —
    `qc_units_consumed`, `units_reserved`, and `units_shipped` — all at zero, and
    its `units_available` always derives as the produced total minus those three
    counters. Before any homogeneity test has run, `homogeneity_f_ratio`,
    `homogeneity_u_hom`, and `homogeneity_verdict` are null."

    Design: Corner/entities/lot_creation_computed_counters_zero
    """
    program = make_program(program_code="NIST-RM-C02")
    lot = make_lot(program["id"], material_code="SRM-C2", total_units_produced=15)
    assert lot["status"] == "SOURCING"
    assert lot["units_available"] == 15
    assert lot["units_reserved"] == 0
    assert lot["qc_units_consumed"] == 0
    assert lot["units_shipped"] == 0
    assert lot["homogeneity_f_ratio"] is None
    assert lot["homogeneity_verdict"] is None
    assert_lot_unit_conservation(lot)


def test_missing_required_total_units_rejected(api, program_admin_headers):
    """PRD §2.8: "Required fields must be present, types must be valid, enum
    members must be declared values, and ranges must hold" (`ERR_INVALID_REQUEST`, 400).

    Design: Corner/entities/missing_required_total_units_rejected
    """
    program = make_program(program_code="NIST-RM-C03")
    payload = {"program_id": program["id"], "material_code": "SRM-C3",
               "matrix_description": "m"}
    resp = api.create_material_lot(payload, program_admin_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_invalid_enum_allocation_policy_rejected(api, program_admin_headers):
    """PRD §2.8: "enum members must be declared values" (`ERR_INVALID_REQUEST`, 400).
    PRD §3.2: "An optional `allocation_policy` of `FIFO` or `PRO_RATA` governs
    shortage behavior and defaults to `FIFO`."

    Design: Corner/entities/invalid_enum_allocation_policy_rejected
    """
    program = make_program(program_code="NIST-RM-C04")
    payload = create_material_lot_payload(program["id"], material_code="SRM-C4",
                                          total_units_produced=5, allocation_policy="LIFO")
    resp = api.create_material_lot(payload, program_admin_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_get_nonexistent_lot_returns_not_found(api, program_admin_headers):
    """PRD §2.8: "Resource identifiers in the URL path are validated left to
    right, and the first identifier that does not resolve to an existing resource
    ends the request (`ERR_NOT_FOUND`, 404)."

    Design: Corner/entities/get_nonexistent_lot_returns_not_found
    """
    resp = api.get_material_lot(NON_EXISTENT_UUID, program_admin_headers)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_lot_transition_from_wrong_state_rejected(api, inventory_manager_headers):
    """PRD §3.5: "from any lot state other than `CERTIFIED` with
    `ERR_INVALID_LOT_STATE`" (enter-distribution is declared only from CERTIFIED).

    Design: Corner/state_machines/lot_transition_from_wrong_state_rejected
    """
    program = make_program(program_code="NIST-RM-C07")
    lot = make_lot(program["id"], material_code="SRM-C7", total_units_produced=5)
    resp = api.transition_material_lot(lot["id"], {"to": "IN_DISTRIBUTION"},
                                       inventory_manager_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_LOT_STATE)


def test_homogeneity_fail_blocks_pipeline(api):
    """PRD §3.2: "The lot's `homogeneity_verdict` is `PASS` when the ratio is at
    most the critical value `F_CRITICAL` of 3.0, and `FAIL` otherwise".
    PRD §3.2: "on `FAIL` the lot remains in `HOMOGENEITY_TESTING`".

    Design: Corner/calculations/homogeneity_fail_blocks_pipeline
    """
    program = make_program(program_code="NIST-RM-C19")
    lot = make_lot(program["id"], material_code="SRM-C19", total_units_produced=20)
    lot = run_homogeneity(lot["id"], FAILING_HOMOGENEITY)
    assert lot["homogeneity_f_ratio"] == 12.0
    assert lot["homogeneity_verdict"] == "FAIL"
    assert lot["homogeneity_u_hom"] == 3.391165
    assert lot["status"] == "HOMOGENEITY_TESTING"
    assert lot["qc_units_consumed"] == 4


def test_homogeneity_bottle_count_exceeds_available_rejected(api):
    """PRD §3.2: "the number of bottles must not exceed the lot's current
    `units_available`, on pain of `ERR_INSUFFICIENT_UNITS`".

    Design: Corner/validations/homogeneity_bottle_count_exceeds_available_rejected
    """
    program = make_program(program_code="NIST-RM-C37")
    lot = make_lot(program["id"], material_code="SRM-C37", total_units_produced=5)
    payload = {"to": "HOMOGENEITY_TESTING",
               "bottle_means": [10.0, 10.0, 10.0, 10.0, 10.0, 10.0],
               "within_bottle_std": 0.5, "replicates_per_bottle": 2}
    resp = api.transition_material_lot(
        lot["id"], payload, make_metrologist_headers("met-op"))
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_UNITS)


def test_homogeneity_transition_by_wrong_role_rejected(api, inventory_manager_headers):
    """PRD §2.1: "a request whose role is not among them — or whose role is not
    permitted for the specific transition target named in a transition request —
    is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

    Design: Corner/rbac/homogeneity_transition_by_wrong_role_rejected
    """
    program = make_program(program_code="NIST-RM-C46")
    lot = make_lot(program["id"], material_code="SRM-C46", total_units_produced=10)
    payload = {"to": "HOMOGENEITY_TESTING"}
    payload.update(FLAT_HOMOGENEITY)
    resp = api.transition_material_lot(lot["id"], payload, inventory_manager_headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


def test_immediate_read_after_write_visibility(api, metrologist_headers):
    """PRD §2.5: "The system is immediately consistent: a mutation's full
    effect, including any automatic state moves it triggered on related
    resources, is visible in that same operation's response."

    Design: Corner/consistency_model/immediate_read_after_write_visibility
    """
    program = make_program(program_code="NIST-RM-C51")
    lot = make_lot(program["id"], material_code="SRM-C51", total_units_produced=10)
    written = run_homogeneity(lot["id"])
    assert written["status"] == "VALUE_ASSIGNMENT"
    read = validate_success(api.get_material_lot(lot["id"], metrologist_headers))
    assert read["status"] == written["status"]
    assert read["version"] == written["version"] == 2
    assert read["updated_at"] == written["updated_at"]
    assert read["homogeneity_f_ratio"] == written["homogeneity_f_ratio"] == 0.0
