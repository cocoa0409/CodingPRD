"""Software update application gates: active contract, release state, clinical
validation, model generation; and the run-mode unlock side effect
(PRD sections 2.6, 2.9, 3.2, 3.7).
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_account,
    create_active_license,
    create_contract,
    create_kit,
    create_model,
    create_operational_instrument,
    create_passed_lot,
    create_run_record_payload,
    create_software_update,
    make_field_service_engineer_headers,
    make_lab_operator_headers,
    record_run,
    setup_update_gate_scenario,
    validate_error,
    validate_success,
)
from test_helpers import api_client


def _apply(instrument_id: str, update_id: str):
    return api_client.apply_software_update(
        instrument_id,
        {"update_id": update_id},
        make_field_service_engineer_headers("fse-1"),
    )


def _operational_instrument_without_active_contract(with_draft_contract: bool):
    """RUO account + OPERATIONAL gen-2 instrument + RELEASED VALIDATED update
    (min generation 2). Optionally a contract that stays DRAFT; never an
    ACTIVE contract — so only the contract gate can fail."""
    account = create_account()
    model = create_model(generation=2, supported_chemistry_versions=["V1", "V2"])
    instrument = create_operational_instrument(
        account_id=account["id"], model_id=model["id"]
    )
    if with_draft_contract:
        create_contract(account_id=account["id"], instrument_id=instrument["id"])
    update = create_software_update(
        update_version="2.1.0",
        min_model_generation=2,
        unlocks_run_modes=["STD_LONG"],
        clinical_validation_status="VALIDATED",
    )
    return {"account": account, "instrument": instrument, "update": update}


class TestUpdateRequiresActiveContract:
    def test_draft_contract_does_not_satisfy_gate(self, api):
        """A DRAFT contract on the instrument fails the active-contract gate
        even when the update is RELEASED, VALIDATED, and generation-compatible.

        PRD §3.2: "Applying a software update to an instrument is also `FieldServiceEngineer` work, and it is gated on four conditions: an `ACTIVE` service contract must cover the instrument, else `ERR_CONTRACT_NOT_ACTIVE` (HTTP 409); the update's `release_state` must be `RELEASED`, else `ERR_UPDATE_WITHDRAWN`; the clinical-validation gate of §2.6 applies to `CLINICAL` instruments; and the update's `min_model_generation` must not exceed the instrument model's `generation`, else `ERR_UPDATE_MODEL_INCOMPATIBLE` (HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/update_apply_requires_active_contract
        """
        bag = _operational_instrument_without_active_contract(
            with_draft_contract=True
        )
        resp = _apply(bag["instrument"]["id"], bag["update"]["id"])
        validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE)
        instrument = validate_success(
            api.get_instrument(
                bag["instrument"]["id"], TEST_USERS["account_manager_headers"]
            )
        )
        assert instrument["software_version"] == "1.0.0"

    def test_no_contract_at_all_fails_gate(self, api):
        """With no contract on the instrument at all, the same gate fires.

        PRD §3.2: "Applying a software update to an instrument is also `FieldServiceEngineer` work, and it is gated on four conditions: an `ACTIVE` service contract must cover the instrument, else `ERR_CONTRACT_NOT_ACTIVE` (HTTP 409); the update's `release_state` must be `RELEASED`, else `ERR_UPDATE_WITHDRAWN`; the clinical-validation gate of §2.6 applies to `CLINICAL` instruments; and the update's `min_model_generation` must not exceed the instrument model's `generation`, else `ERR_UPDATE_MODEL_INCOMPATIBLE` (HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/update_apply_requires_active_contract
        """
        bag = _operational_instrument_without_active_contract(
            with_draft_contract=False
        )
        resp = _apply(bag["instrument"]["id"], bag["update"]["id"])
        validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE)
        instrument = validate_success(
            api.get_instrument(
                bag["instrument"]["id"], TEST_USERS["account_manager_headers"]
            )
        )
        assert instrument["software_version"] == "1.0.0"
        assert instrument["applied_update_ids"] == []


class TestSafetyBeatsConstraintOnUpdateApply:
    def _clinical_scenario_with_doubly_bad_update(self):
        """CLINICAL account + CLINICAL OPERATIONAL instrument (model
        generation 2) under an ACTIVE contract; the update is BOTH
        NOT_VALIDATED (safety violation) and min generation 4 (constraint
        violation)."""
        return setup_update_gate_scenario(
            regulatory_class="CLINICAL",
            model_overrides={"generation": 2, "supported_chemistry_versions": ["V2"]},
            update_overrides={
                "update_version": "4.0.0",
                "min_model_generation": 4,
                "unlocks_run_modes": ["HIGH_OUTPUT"],
                "clinical_validation_status": "NOT_VALIDATED",
            },
        )

    def test_safety_error_wins_over_constraint_error(self, api):
        """One request violates the clinical-validation safety gate and the
        model-generation compatibility constraint; the safety error wins.

        PRD §2.9: "Only after all eight tiers pass do the domain rules of §3 evaluate: state-specific gates first, then regulatory and safety gates, then uniqueness and compatibility constraints including segregation of duties and optimistic concurrency, then temporal window rules, and finally fiscal gates."
        PRD §2.6: "Applying a software update whose `clinical_validation_status` is `NOT_VALIDATED` to a `CLINICAL` instrument is rejected with `ERR_UPDATE_NOT_VALIDATED_CLINICAL` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_constraint_on_update_apply
        """
        bag = self._clinical_scenario_with_doubly_bad_update()
        resp = _apply(bag["instrument"]["id"], bag["update"]["id"])
        validate_error(resp, ApiErrorId.ERR_UPDATE_NOT_VALIDATED_CLINICAL)

    def test_rejected_dual_violation_leaves_instrument_untouched(self, api):
        """The rejected dual-violation application mutates nothing: factory
        software version and an empty applied-update list survive.

        PRD §3.2: "On success the instrument's `software_version` becomes the update's `update_version`, the update's id is appended to `applied_update_ids` in application order, `unlocked_run_modes` is recomputed as the model's `base_run_modes` unioned with the `unlocks_run_modes` of every applied update still in `RELEASED` state, and the instrument's `version` increments."
        PRD §2.6: "Applying a software update whose `clinical_validation_status` is `NOT_VALIDATED` to a `CLINICAL` instrument is rejected with `ERR_UPDATE_NOT_VALIDATED_CLINICAL` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_constraint_on_update_apply
        """
        bag = self._clinical_scenario_with_doubly_bad_update()
        resp = _apply(bag["instrument"]["id"], bag["update"]["id"])
        validate_error(resp, ApiErrorId.ERR_UPDATE_NOT_VALIDATED_CLINICAL)
        instrument = validate_success(
            api.get_instrument(
                bag["instrument"]["id"], TEST_USERS["account_manager_headers"]
            )
        )
        assert instrument["software_version"] == "1.0.0"
        assert instrument["applied_update_ids"] == []


class TestUpdateReleaseAndGenerationGates:
    def test_withdrawn_update_cannot_be_applied(self, api):
        """A WITHDRAWN update is inapplicable even with every other gate
        (contract, generation, validation) passing.

        PRD §3.1: "Withdrawing an update moves its `release_state` to `WITHDRAWN` and bumps its `version`; instruments that already applied the update keep the run modes it unlocked — there is no retroactive lock — but a withdrawn update can no longer be applied to any instrument and the attempt is rejected with `ERR_UPDATE_WITHDRAWN` (HTTP 409)."

        Design: Corner/errors/update_withdrawn_cannot_be_applied
        """
        bag = setup_update_gate_scenario(
            update_overrides={
                "update_version": "1.2.0",
                "min_model_generation": 1,
                "unlocks_run_modes": ["STD_LONG"],
                "clinical_validation_status": "VALIDATED",
            }
        )
        withdrawn = validate_success(
            api_client.withdraw_software_update(
                bag["update"]["id"], TEST_USERS["platform_admin_headers"]
            )
        )
        assert withdrawn["release_state"] == "WITHDRAWN"
        resp = _apply(bag["instrument"]["id"], bag["update"]["id"])
        validate_error(resp, ApiErrorId.ERR_UPDATE_WITHDRAWN)
        instrument = validate_success(
            api.get_instrument(
                bag["instrument"]["id"], TEST_USERS["account_manager_headers"]
            )
        )
        assert instrument["software_version"] == "1.0.0"

    def test_update_model_incompatible_rejected(self, api):
        """A VALIDATED, RELEASED update whose min_model_generation (3) exceeds
        the instrument model's generation (2) fails only the compatibility
        gate.

        PRD §3.2: "Applying a software update to an instrument is also `FieldServiceEngineer` work, and it is gated on four conditions: an `ACTIVE` service contract must cover the instrument, else `ERR_CONTRACT_NOT_ACTIVE` (HTTP 409); the update's `release_state` must be `RELEASED`, else `ERR_UPDATE_WITHDRAWN`; the clinical-validation gate of §2.6 applies to `CLINICAL` instruments; and the update's `min_model_generation` must not exceed the instrument model's `generation`, else `ERR_UPDATE_MODEL_INCOMPATIBLE` (HTTP 422)."

        Design: Corner/validations/update_model_incompatible_rejected
        """
        bag = setup_update_gate_scenario(
            model_overrides={"generation": 2},
            update_overrides={
                "update_version": "3.0.0",
                "min_model_generation": 3,
                "unlocks_run_modes": ["STD_LONG"],
                "clinical_validation_status": "VALIDATED",
            },
        )
        resp = _apply(bag["instrument"]["id"], bag["update"]["id"])
        validate_error(resp, ApiErrorId.ERR_UPDATE_MODEL_INCOMPATIBLE)
        instrument = validate_success(
            api.get_instrument(
                bag["instrument"]["id"], TEST_USERS["account_manager_headers"]
            )
        )
        assert instrument["software_version"] == "1.0.0"

    def test_run_mode_locked_until_update_unlocks(self, api):
        """A STD_LONG run is rejected while the mode is locked; applying a
        RELEASED VALIDATED update that unlocks STD_LONG recomputes the
        instrument's mode set, and the identical run then succeeds.

        PRD §3.7: "The gates evaluate in this relative order after the §2.9 tiers: the instrument's `install_state` must be `OPERATIONAL`, else `ERR_INSTRUMENT_NOT_OPERATIONAL`; the license must be `ACTIVE`, else `ERR_LICENSE_NOT_ACTIVE`; the lot's `qc_status` must be `QC_PASSED`, else `ERR_LOT_NOT_USABLE` (HTTP 409); the lot's `available_units` must be at least 1, else `ERR_LOT_DEPLETED` (HTTP 409); a lot whose cold chain is `BREACHED` is rejected with `ERR_COLD_CHAIN_BREACHED`; the lot's `expiry_date` must be strictly after the current logical clock, else `ERR_LOT_EXPIRED`; the clinical-clearance gate of §2.6 applies on `CLINICAL` instruments; the `run_mode` must be among the instrument's `unlocked_run_modes`, else `ERR_RUN_MODE_LOCKED` (HTTP 422); the lot's kit `run_type` must equal the `run_mode`, else `ERR_KIT_RUN_TYPE_MISMATCH` (HTTP 422); the kit's `chemistry_version` must appear in the instrument model's `supported_chemistry_versions`, else `ERR_CHEMISTRY_UNSUPPORTED` (HTTP 422); the kit's `min_model_generation` must not exceed the instrument model's `generation`, else `ERR_KIT_MODEL_INCOMPATIBLE` (HTTP 422); and a non-`FAILED` run in a cloud analysis mode requires a `credits_balance` of at least the run's cost, else `ERR_INSUFFICIENT_CREDITS` (HTTP 402)."
        PRD §3.2: "On success the instrument's `software_version` becomes the update's `update_version`, the update's id is appended to `applied_update_ids` in application order, `unlocked_run_modes` is recomputed as the model's `base_run_modes` unioned with the `unlocks_run_modes` of every applied update still in `RELEASED` state, and the instrument's `version` increments."

        Design: Corner/validations/run_mode_locked_until_update_unlocks
        """
        bag = setup_update_gate_scenario(
            model_overrides={"base_run_modes": ["STD_SHORT"]},
            update_overrides={
                "update_version": "1.1.0",
                "min_model_generation": 1,
                "unlocks_run_modes": ["STD_LONG"],
                "clinical_validation_status": "VALIDATED",
            },
        )
        account = bag["account"]
        instrument = bag["instrument"]
        kit = create_kit(
            run_type="STD_LONG", flow_cell_version="FC_MID", samples_per_kit=24
        )
        lot = create_passed_lot(kit_id=kit["id"], quantity_units=5)
        license_data = create_active_license(account_id=account["id"])
        run_kwargs = dict(
            run_mode="STD_LONG", analysis_mode="LOCAL", samples_count=10,
            output_gb=1.0, outcome="SUCCESS",
        )
        resp = api_client.create_run_record(
            create_run_record_payload(
                instrument["id"], lot["id"], license_data["id"], **run_kwargs
            ),
            make_lab_operator_headers(account["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_RUN_MODE_LOCKED)

        updated = validate_success(_apply(instrument["id"], bag["update"]["id"]))
        assert set(updated["unlocked_run_modes"]) == {"STD_SHORT", "STD_LONG"}
        assert updated["software_version"] == "1.1.0"

        run = record_run(
            instrument["id"], lot["id"], license_data["id"], account["id"],
            **run_kwargs,
        )
        assert run["id"], "post-update STD_LONG run must succeed"
