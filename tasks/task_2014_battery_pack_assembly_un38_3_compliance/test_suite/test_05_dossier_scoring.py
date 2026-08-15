"""UN38.3 dossier lifecycle, dual-variant composite scoring, and open gating."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_dossier,
    certify_weld,
    create_battery_pack,
    drive_pack_to_test_queued,
    get_battery_pack,
    get_program,
    record_test_matrix,
    record_weld,
    setup_program_with_bom,
    submit_dossier,
    validate_error,
)


class TestDualVariantScoring:
    def test_provisional_score_counts_false_boolean_as_zero_not_fail_fast(self, api):
        """PRD §3.6: "The two scoring variants differ only in how a missing boolean is
        treated: the provisional variant, computed when the matrix is recorded, counts a
        null boolean as an optimistic 0.5 while a false boolean still counts 0".
        PRD §3.6: "The composite score weights the eight tests so their contributions sum
        to 100: T1 carries 10, T2 carries 15, T3 carries 12, T4 carries 13, T5 carries 15,
        T6 carries 15, T7 carries 10, and T8 carries 10."
        With every numeric at its reference ceiling and only forced_discharge_ok false,
        the provisional score is 10+15+12+13+15+15+10+0 = 90.0.

        Design: Difficulty/dual_variant_calc/dossier_un_score_provisional_vs_final_diverge_on_null_boolean
        """
        bundle = setup_program_with_bom()
        program_id = bundle["program"]["id"]
        driven = drive_pack_to_test_queued(program_id, bundle["bom"])
        pack = driven["pack"]
        dossier = driven["dossier"]
        recorded = record_test_matrix(
            program_id, pack["id"], dossier["id"], forced_discharge_ok=False
        )
        assert recorded["status"] == "TESTS_RECORDED"
        assert recorded["provisional_un_score"] == pytest.approx(90.0)
        assert recorded["final_un_score"] is None

    def test_final_score_fail_fast_zeroes_on_false_boolean(self, api):
        """PRD §3.6: "the final variant, computed at submission, counts a null boolean as
        0 and applies a strict fail-fast — any false boolean forces the entire final score
        to 0.0."
        PRD §3.6: "A final score below 85.0 marks the dossier `FAIL`: instead of settling
        in `SUBMITTED` the dossier lands in `FAILED`, the program's
        `compliance_risk_index` drops by 5, and the pack stays in `TEST_QUEUED`."

        Design: Difficulty/dual_variant_calc/dossier_un_score_provisional_vs_final_diverge_on_null_boolean
        """
        bundle = setup_program_with_bom()
        program_id = bundle["program"]["id"]
        driven = drive_pack_to_test_queued(program_id, bundle["bom"])
        pack = driven["pack"]
        dossier = driven["dossier"]
        record_test_matrix(program_id, pack["id"], dossier["id"], forced_discharge_ok=False)
        submitted = submit_dossier(program_id, pack["id"], dossier["id"])
        assert submitted["final_un_score"] == pytest.approx(0.0)
        assert submitted["outcome"] == "FAIL"
        assert submitted["status"] == "FAILED"
        assert get_battery_pack(program_id, pack["id"])["assembly_status"] == "TEST_QUEUED"
        assert get_program(program_id)["compliance_risk_index"] == 95


class TestScoreThresholds:
    def test_all_reference_values_yield_perfect_score(self, api):
        """PRD §3.6: "The composite score weights the eight tests so their contributions
        sum to 100" and "a value at or above its reference yields a full sub-score of 1.
        Each boolean test contributes 1 when true and 0 when false."
        PRD §3.6: "A final score of at least 85.0 marks the dossier `PASS`".

        Design: Corner/calculations/un_score_all_pass_yields_100
        """
        bundle = setup_program_with_bom()
        program_id = bundle["program"]["id"]
        driven = drive_pack_to_test_queued(program_id, bundle["bom"])
        pack = driven["pack"]
        dossier = driven["dossier"]
        record_test_matrix(program_id, pack["id"], dossier["id"])  # all references, all true
        submitted = submit_dossier(program_id, pack["id"], dossier["id"])
        assert submitted["final_un_score"] == pytest.approx(100.0)
        assert submitted["outcome"] == "PASS"
        assert submitted["status"] == "SUBMITTED"

    def test_score_exactly_at_threshold_passes(self, api):
        """PRD §3.6: "A final score of at least 85.0 marks the dossier `PASS`".
        Matrix built to total exactly 85.0: altitude at reference (10), zero thermal
        cycles (0), vibration at reference (12), shock at reference (13) gives 35 from
        numerics; all four booleans true add 50.

        Design: Corner/calculations/pass_threshold_boundary_at_85
        """
        bundle = setup_program_with_bom()
        program_id = bundle["program"]["id"]
        driven = drive_pack_to_test_queued(program_id, bundle["bom"])
        pack = driven["pack"]
        dossier = driven["dossier"]
        record_test_matrix(program_id, pack["id"], dossier["id"], thermal_cycles=0)
        submitted = submit_dossier(program_id, pack["id"], dossier["id"])
        assert submitted["final_un_score"] == pytest.approx(85.0)
        assert submitted["outcome"] == "PASS"
        assert submitted["status"] == "SUBMITTED"
        # A PASS dossier can be approved, driving the pack to READY_TO_STORE.
        approved = approve_dossier(program_id, pack["id"], dossier["id"])
        assert approved["status"] == "APPROVED"
        assert get_battery_pack(program_id, pack["id"])["assembly_status"] == "READY_TO_STORE"


class TestDossierOpenGating:
    def test_open_rejected_when_pack_only_weld_certified(self, api):
        """PRD §3.6: "A `QualityEngineer` opens a `SafetyTestDossier` against a pack that
        is `BMS_FLASHED` (otherwise `ERR_PACK_NOT_BMS_FLASHED`)".

        Design: Difficulty/cross_entity_state_dependency/dossier_open_gated_on_pack_bms_flashed
        """
        bundle = setup_program_with_bom()
        program_id = bundle["program"]["id"]
        pack = create_battery_pack(program_id, bundle["bom"]["id"])
        record = record_weld(program_id, pack["id"])
        certify_weld(program_id, pack["id"], record["id"])
        assert get_battery_pack(program_id, pack["id"])["assembly_status"] == "WELD_CERTIFIED"
        resp = api.create_safety_test_dossier(
            program_id, pack["id"], TEST_USERS["quality_engineer_headers"]
        )
        validate_error(resp, ApiErrorId.ERR_PACK_NOT_BMS_FLASHED)
        assert get_battery_pack(program_id, pack["id"])["assembly_status"] == "WELD_CERTIFIED"

    def test_open_rejected_when_pack_only_built(self, api):
        """PRD §3.6: "A `QualityEngineer` opens a `SafetyTestDossier` against a pack that
        is `BMS_FLASHED` (otherwise `ERR_PACK_NOT_BMS_FLASHED`)". A freshly assembled pack
        in `BUILT` is even further from the gate and is rejected identically.

        Design: Difficulty/cross_entity_state_dependency/dossier_open_gated_on_pack_bms_flashed
        """
        bundle = setup_program_with_bom()
        program_id = bundle["program"]["id"]
        pack = create_battery_pack(program_id, bundle["bom"]["id"])
        assert pack["assembly_status"] == "BUILT"
        resp = api.create_safety_test_dossier(
            program_id, pack["id"], TEST_USERS["quality_engineer_headers"]
        )
        validate_error(resp, ApiErrorId.ERR_PACK_NOT_BMS_FLASHED)
        assert get_battery_pack(program_id, pack["id"])["assembly_status"] == "BUILT"
