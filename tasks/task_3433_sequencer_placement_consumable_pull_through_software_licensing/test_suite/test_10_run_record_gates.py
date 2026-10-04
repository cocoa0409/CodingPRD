"""Run-record gate battery: license state, instrument state, lot usability,
depletion, expiry, run-type/chemistry/generation compatibility, clinical
clearance, cloud-credit sufficiency, and the FAILED-run asymmetry
(PRD sections 2.6, 3.7).
"""
from datetime import datetime, timezone

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_account,
    create_active_license,
    create_instrument,
    create_kit,
    create_model,
    create_passed_lot,
    create_run_record_payload,
    drive_instrument_to,
    license_status_payload,
    make_lab_operator_headers,
    record_run,
    setup_run_ready,
    validate_error,
    validate_success,
)
from test_helpers import api_client

SP = TEST_USERS["supply_planner_headers"]
FA = TEST_USERS["finance_admin_headers"]


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
        timezone.utc
    )


def _run_request(bag: dict, **overrides):
    """Fire a run against a setup_run_ready() bag, returning the raw resp."""
    payload = create_run_record_payload(
        bag["instrument"]["id"], bag["lot"]["id"], bag["license"]["id"],
        **overrides,
    )
    return api_client.create_run_record(
        payload, make_lab_operator_headers(bag["account"]["id"])
    )


def _lot(bag: dict) -> dict:
    return validate_success(api_client.get_reagent_lot(bag["lot"]["id"], SP))


def _license(bag: dict) -> dict:
    return validate_success(
        api_client.get_software_license(bag["license"]["id"], FA)
    )


class TestRunRequiresActiveLicense:
    def test_suspended_license_rejects_then_reinstate_succeeds(self, api):
        """A run recorded while its license is SUSPENDED is rejected; after
        REINSTATE the identical run succeeds — the gate is the license's
        state, not the payload.

        PRD §3.7: "The gates evaluate in this relative order after the §2.9 tiers: the instrument's `install_state` must be `OPERATIONAL`, else `ERR_INSTRUMENT_NOT_OPERATIONAL`; the license must be `ACTIVE`, else `ERR_LICENSE_NOT_ACTIVE`; the lot's `qc_status` must be `QC_PASSED`, else `ERR_LOT_NOT_USABLE` (HTTP 409); the lot's `available_units` must be at least 1, else `ERR_LOT_DEPLETED` (HTTP 409); a lot whose cold chain is `BREACHED` is rejected with `ERR_COLD_CHAIN_BREACHED`; the lot's `expiry_date` must be strictly after the current logical clock, else `ERR_LOT_EXPIRED`; the clinical-clearance gate of §2.6 applies on `CLINICAL` instruments; the `run_mode` must be among the instrument's `unlocked_run_modes`, else `ERR_RUN_MODE_LOCKED` (HTTP 422); the lot's kit `run_type` must equal the `run_mode`, else `ERR_KIT_RUN_TYPE_MISMATCH` (HTTP 422); the kit's `chemistry_version` must appear in the instrument model's `supported_chemistry_versions`, else `ERR_CHEMISTRY_UNSUPPORTED` (HTTP 422); the kit's `min_model_generation` must not exceed the instrument model's `generation`, else `ERR_KIT_MODEL_INCOMPATIBLE` (HTTP 422); and a non-`FAILED` run in a cloud analysis mode requires a `credits_balance` of at least the run's cost, else `ERR_INSUFFICIENT_CREDITS` (HTTP 402)."

        Design: Difficulty/cross_entity_state_dependency/run_requires_active_license
        """
        bag = setup_run_ready()
        validate_success(
            api_client.set_license_status(
                bag["license"]["id"], license_status_payload("SUSPEND"), FA
            )
        )
        resp = _run_request(bag, samples_count=100)
        validate_error(resp, ApiErrorId.ERR_LICENSE_NOT_ACTIVE)
        validate_success(
            api_client.set_license_status(
                bag["license"]["id"], license_status_payload("REINSTATE"), FA
            )
        )
        run = record_run(
            bag["instrument"]["id"], bag["lot"]["id"], bag["license"]["id"],
            bag["account"]["id"], samples_count=100,
            run_at="2026-09-10T01:00:00Z",
        )
        assert run["id"], "after REINSTATE the identical run must succeed"
        assert _lot(bag)["consumed_units"] == 1

    def test_draft_license_rejects_run(self, api):
        """A license never activated sits in DRAFT and fails the same gate.

        PRD §3.7: "The gates evaluate in this relative order after the §2.9 tiers: the instrument's `install_state` must be `OPERATIONAL`, else `ERR_INSTRUMENT_NOT_OPERATIONAL`; the license must be `ACTIVE`, else `ERR_LICENSE_NOT_ACTIVE`; the lot's `qc_status` must be `QC_PASSED`, else `ERR_LOT_NOT_USABLE` (HTTP 409); the lot's `available_units` must be at least 1, else `ERR_LOT_DEPLETED` (HTTP 409); a lot whose cold chain is `BREACHED` is rejected with `ERR_COLD_CHAIN_BREACHED`; the lot's `expiry_date` must be strictly after the current logical clock, else `ERR_LOT_EXPIRED`; the clinical-clearance gate of §2.6 applies on `CLINICAL` instruments; the `run_mode` must be among the instrument's `unlocked_run_modes`, else `ERR_RUN_MODE_LOCKED` (HTTP 422); the lot's kit `run_type` must equal the `run_mode`, else `ERR_KIT_RUN_TYPE_MISMATCH` (HTTP 422); the kit's `chemistry_version` must appear in the instrument model's `supported_chemistry_versions`, else `ERR_CHEMISTRY_UNSUPPORTED` (HTTP 422); the kit's `min_model_generation` must not exceed the instrument model's `generation`, else `ERR_KIT_MODEL_INCOMPATIBLE` (HTTP 422); and a non-`FAILED` run in a cloud analysis mode requires a `credits_balance` of at least the run's cost, else `ERR_INSUFFICIENT_CREDITS` (HTTP 402)."

        Design: Difficulty/cross_entity_state_dependency/run_requires_active_license
        """
        bag = setup_run_ready(activate=False)
        assert bag["license"]["license_state"] == "DRAFT"
        resp = _run_request(bag, samples_count=100)
        validate_error(resp, ApiErrorId.ERR_LICENSE_NOT_ACTIVE)


class TestFailedRunAsymmetry:
    def test_failed_run_consumes_unit_but_bills_nothing(self, api):
        """A FAILED run consumes the physical kit unit yet bills zero samples
        and zero credits even in CLOUD_DEEP.

        PRD §3.7: "Every recorded run consumes exactly one kit unit from its lot — the lot's `consumed_units` increments even for a `FAILED` run, which consumes the unit but bills zero samples and zero credits."

        Design: Corner/calculations/failed_run_consumes_unit_but_bills_nothing
        """
        bag = setup_run_ready(grant_credits_amount=50, granted_on="2026-08-15")
        run = record_run(
            bag["instrument"]["id"], bag["lot"]["id"], bag["license"]["id"],
            bag["account"]["id"], analysis_mode="CLOUD_DEEP",
            samples_count=100, outcome="FAILED",
        )
        assert run["credits_consumed"] == 0
        assert _lot(bag)["consumed_units"] == 1, (
            "the failed run still consumed the physical kit unit"
        )
        license_after = _license(bag)
        assert license_after["samples_this_period"] == 0
        assert license_after["credits_balance"] == 50


class TestRunGateBattery:
    def test_insufficient_credits_for_cloud_run(self, api):
        """A CLOUD_DEEP run (25 credits) against a balance of 10 is refused
        outright: no record, no lot consumption, balance untouched.

        PRD §3.7: "The gates evaluate in this relative order after the §2.9 tiers: the instrument's `install_state` must be `OPERATIONAL`, else `ERR_INSTRUMENT_NOT_OPERATIONAL`; the license must be `ACTIVE`, else `ERR_LICENSE_NOT_ACTIVE`; the lot's `qc_status` must be `QC_PASSED`, else `ERR_LOT_NOT_USABLE` (HTTP 409); the lot's `available_units` must be at least 1, else `ERR_LOT_DEPLETED` (HTTP 409); a lot whose cold chain is `BREACHED` is rejected with `ERR_COLD_CHAIN_BREACHED`; the lot's `expiry_date` must be strictly after the current logical clock, else `ERR_LOT_EXPIRED`; the clinical-clearance gate of §2.6 applies on `CLINICAL` instruments; the `run_mode` must be among the instrument's `unlocked_run_modes`, else `ERR_RUN_MODE_LOCKED` (HTTP 422); the lot's kit `run_type` must equal the `run_mode`, else `ERR_KIT_RUN_TYPE_MISMATCH` (HTTP 422); the kit's `chemistry_version` must appear in the instrument model's `supported_chemistry_versions`, else `ERR_CHEMISTRY_UNSUPPORTED` (HTTP 422); the kit's `min_model_generation` must not exceed the instrument model's `generation`, else `ERR_KIT_MODEL_INCOMPATIBLE` (HTTP 422); and a non-`FAILED` run in a cloud analysis mode requires a `credits_balance` of at least the run's cost, else `ERR_INSUFFICIENT_CREDITS` (HTTP 402)."
        PRD §3.7: "The `credits_balance` is always the sum of all ledger entries' `credits` and may never go negative — a run whose cloud cost would exceed the balance is refused outright."

        Design: Corner/validations/insufficient_credits_for_cloud_run
        """
        bag = setup_run_ready(grant_credits_amount=10, granted_on="2026-08-15")
        resp = _run_request(bag, analysis_mode="CLOUD_DEEP")
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_CREDITS)
        assert _lot(bag)["consumed_units"] == 0
        assert _license(bag)["credits_balance"] == 10

    def test_run_on_non_operational_instrument_rejected(self, api):
        """A run against an INSTALLED (never commissioned) instrument fails
        the operational gate; the lot and license are otherwise valid.

        PRD §3.7: "The gates evaluate in this relative order after the §2.9 tiers: the instrument's `install_state` must be `OPERATIONAL`, else `ERR_INSTRUMENT_NOT_OPERATIONAL`; the license must be `ACTIVE`, else `ERR_LICENSE_NOT_ACTIVE`; the lot's `qc_status` must be `QC_PASSED`, else `ERR_LOT_NOT_USABLE` (HTTP 409); the lot's `available_units` must be at least 1, else `ERR_LOT_DEPLETED` (HTTP 409); a lot whose cold chain is `BREACHED` is rejected with `ERR_COLD_CHAIN_BREACHED`; the lot's `expiry_date` must be strictly after the current logical clock, else `ERR_LOT_EXPIRED`; the clinical-clearance gate of §2.6 applies on `CLINICAL` instruments; the `run_mode` must be among the instrument's `unlocked_run_modes`, else `ERR_RUN_MODE_LOCKED` (HTTP 422); the lot's kit `run_type` must equal the `run_mode`, else `ERR_KIT_RUN_TYPE_MISMATCH` (HTTP 422); the kit's `chemistry_version` must appear in the instrument model's `supported_chemistry_versions`, else `ERR_CHEMISTRY_UNSUPPORTED` (HTTP 422); the kit's `min_model_generation` must not exceed the instrument model's `generation`, else `ERR_KIT_MODEL_INCOMPATIBLE` (HTTP 422); and a non-`FAILED` run in a cloud analysis mode requires a `credits_balance` of at least the run's cost, else `ERR_INSUFFICIENT_CREDITS` (HTTP 402)."

        Design: Corner/errors/run_on_non_operational_instrument_rejected
        """
        account = create_account()
        model = create_model()
        kit = create_kit()
        instrument = create_instrument(
            account_id=account["id"], model_id=model["id"]
        )
        instrument = drive_instrument_to(instrument["id"], "INSTALLED")
        assert instrument["install_state"] == "INSTALLED"
        lot = create_passed_lot(kit_id=kit["id"])
        license_data = create_active_license(account_id=account["id"])
        resp = api_client.create_run_record(
            create_run_record_payload(
                instrument["id"], lot["id"], license_data["id"]
            ),
            make_lab_operator_headers(account["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INSTRUMENT_NOT_OPERATIONAL)
        lot_after = validate_success(api_client.get_reagent_lot(lot["id"], SP))
        assert lot_after["consumed_units"] == 0

    def test_lot_not_usable_pending_qc_rejected(self, api):
        """A run against a PENDING_QC lot (never verdicted) fails the
        usability state gate.

        PRD §3.7: "The gates evaluate in this relative order after the §2.9 tiers: the instrument's `install_state` must be `OPERATIONAL`, else `ERR_INSTRUMENT_NOT_OPERATIONAL`; the license must be `ACTIVE`, else `ERR_LICENSE_NOT_ACTIVE`; the lot's `qc_status` must be `QC_PASSED`, else `ERR_LOT_NOT_USABLE` (HTTP 409); the lot's `available_units` must be at least 1, else `ERR_LOT_DEPLETED` (HTTP 409); a lot whose cold chain is `BREACHED` is rejected with `ERR_COLD_CHAIN_BREACHED`; the lot's `expiry_date` must be strictly after the current logical clock, else `ERR_LOT_EXPIRED`; the clinical-clearance gate of §2.6 applies on `CLINICAL` instruments; the `run_mode` must be among the instrument's `unlocked_run_modes`, else `ERR_RUN_MODE_LOCKED` (HTTP 422); the lot's kit `run_type` must equal the `run_mode`, else `ERR_KIT_RUN_TYPE_MISMATCH` (HTTP 422); the kit's `chemistry_version` must appear in the instrument model's `supported_chemistry_versions`, else `ERR_CHEMISTRY_UNSUPPORTED` (HTTP 422); the kit's `min_model_generation` must not exceed the instrument model's `generation`, else `ERR_KIT_MODEL_INCOMPATIBLE` (HTTP 422); and a non-`FAILED` run in a cloud analysis mode requires a `credits_balance` of at least the run's cost, else `ERR_INSUFFICIENT_CREDITS` (HTTP 402)."

        Design: Corner/validations/lot_not_usable_pending_qc_rejected
        """
        bag = setup_run_ready(pass_qc=False)
        assert bag["lot"]["qc_status"] == "PENDING_QC"
        resp = _run_request(bag)
        validate_error(resp, ApiErrorId.ERR_LOT_NOT_USABLE)
        assert _lot(bag)["qc_status"] == "PENDING_QC"

    def test_lot_depleted_rejected(self, api):
        """After one SUCCESS run consumes the lot's single unit, a second run
        against the same lot fails with available_units < 1.

        PRD §3.7: "The gates evaluate in this relative order after the §2.9 tiers: the instrument's `install_state` must be `OPERATIONAL`, else `ERR_INSTRUMENT_NOT_OPERATIONAL`; the license must be `ACTIVE`, else `ERR_LICENSE_NOT_ACTIVE`; the lot's `qc_status` must be `QC_PASSED`, else `ERR_LOT_NOT_USABLE` (HTTP 409); the lot's `available_units` must be at least 1, else `ERR_LOT_DEPLETED` (HTTP 409); a lot whose cold chain is `BREACHED` is rejected with `ERR_COLD_CHAIN_BREACHED`; the lot's `expiry_date` must be strictly after the current logical clock, else `ERR_LOT_EXPIRED`; the clinical-clearance gate of §2.6 applies on `CLINICAL` instruments; the `run_mode` must be among the instrument's `unlocked_run_modes`, else `ERR_RUN_MODE_LOCKED` (HTTP 422); the lot's kit `run_type` must equal the `run_mode`, else `ERR_KIT_RUN_TYPE_MISMATCH` (HTTP 422); the kit's `chemistry_version` must appear in the instrument model's `supported_chemistry_versions`, else `ERR_CHEMISTRY_UNSUPPORTED` (HTTP 422); the kit's `min_model_generation` must not exceed the instrument model's `generation`, else `ERR_KIT_MODEL_INCOMPATIBLE` (HTTP 422); and a non-`FAILED` run in a cloud analysis mode requires a `credits_balance` of at least the run's cost, else `ERR_INSUFFICIENT_CREDITS` (HTTP 402)."

        Design: Corner/validations/lot_depleted_rejected
        """
        bag = setup_run_ready(lot_overrides={"quantity_units": 1})
        record_run(
            bag["instrument"]["id"], bag["lot"]["id"], bag["license"]["id"],
            bag["account"]["id"],
        )
        resp = _run_request(bag, run_at="2026-09-10T01:00:00Z")
        validate_error(resp, ApiErrorId.ERR_LOT_DEPLETED)
        assert _lot(bag)["consumed_units"] == 1

    def test_expired_lot_rejected_at_run(self, api):
        """The run-time expiry gate compares expiry_date against the logical
        clock directly: a QC_PASSED lot whose expiry (2026-08-14, from
        manufacture 2026-07-15 + 30 days) precedes the default clock is
        rejected even though no sweep has run.

        PRD §3.7: "The gates evaluate in this relative order after the §2.9 tiers: the instrument's `install_state` must be `OPERATIONAL`, else `ERR_INSTRUMENT_NOT_OPERATIONAL`; the license must be `ACTIVE`, else `ERR_LICENSE_NOT_ACTIVE`; the lot's `qc_status` must be `QC_PASSED`, else `ERR_LOT_NOT_USABLE` (HTTP 409); the lot's `available_units` must be at least 1, else `ERR_LOT_DEPLETED` (HTTP 409); a lot whose cold chain is `BREACHED` is rejected with `ERR_COLD_CHAIN_BREACHED`; the lot's `expiry_date` must be strictly after the current logical clock, else `ERR_LOT_EXPIRED`; the clinical-clearance gate of §2.6 applies on `CLINICAL` instruments; the `run_mode` must be among the instrument's `unlocked_run_modes`, else `ERR_RUN_MODE_LOCKED` (HTTP 422); the lot's kit `run_type` must equal the `run_mode`, else `ERR_KIT_RUN_TYPE_MISMATCH` (HTTP 422); the kit's `chemistry_version` must appear in the instrument model's `supported_chemistry_versions`, else `ERR_CHEMISTRY_UNSUPPORTED` (HTTP 422); the kit's `min_model_generation` must not exceed the instrument model's `generation`, else `ERR_KIT_MODEL_INCOMPATIBLE` (HTTP 422); and a non-`FAILED` run in a cloud analysis mode requires a `credits_balance` of at least the run's cost, else `ERR_INSUFFICIENT_CREDITS` (HTTP 402)."
        PRD §3.4: "The server computes the lot's `expiry_date` as the `manufacture_date` plus the referenced kit's `shelf_life_days`."

        Design: Corner/validations/expired_lot_rejected_at_run
        """
        bag = setup_run_ready(
            kit_overrides={"shelf_life_days": 30},
            lot_overrides={"manufacture_date": "2026-07-15T00:00:00Z"},
        )
        assert _parse_iso(bag["lot"]["expiry_date"]) == datetime(
            2026, 8, 14, tzinfo=timezone.utc
        )
        resp = _run_request(bag, run_at="2026-09-02T00:00:00Z")
        validate_error(resp, ApiErrorId.ERR_LOT_EXPIRED)
        assert _lot(bag)["consumed_units"] == 0

    def test_kit_run_type_mismatch_rejected(self, api):
        """The run_mode STD_LONG is unlocked on the instrument, but the
        lot's kit is typed STD_SHORT: the kit/run-type equality gate fires.

        PRD §3.7: "The gates evaluate in this relative order after the §2.9 tiers: the instrument's `install_state` must be `OPERATIONAL`, else `ERR_INSTRUMENT_NOT_OPERATIONAL`; the license must be `ACTIVE`, else `ERR_LICENSE_NOT_ACTIVE`; the lot's `qc_status` must be `QC_PASSED`, else `ERR_LOT_NOT_USABLE` (HTTP 409); the lot's `available_units` must be at least 1, else `ERR_LOT_DEPLETED` (HTTP 409); a lot whose cold chain is `BREACHED` is rejected with `ERR_COLD_CHAIN_BREACHED`; the lot's `expiry_date` must be strictly after the current logical clock, else `ERR_LOT_EXPIRED`; the clinical-clearance gate of §2.6 applies on `CLINICAL` instruments; the `run_mode` must be among the instrument's `unlocked_run_modes`, else `ERR_RUN_MODE_LOCKED` (HTTP 422); the lot's kit `run_type` must equal the `run_mode`, else `ERR_KIT_RUN_TYPE_MISMATCH` (HTTP 422); the kit's `chemistry_version` must appear in the instrument model's `supported_chemistry_versions`, else `ERR_CHEMISTRY_UNSUPPORTED` (HTTP 422); the kit's `min_model_generation` must not exceed the instrument model's `generation`, else `ERR_KIT_MODEL_INCOMPATIBLE` (HTTP 422); and a non-`FAILED` run in a cloud analysis mode requires a `credits_balance` of at least the run's cost, else `ERR_INSUFFICIENT_CREDITS` (HTTP 402)."

        Design: Corner/validations/kit_run_type_mismatch_rejected
        """
        bag = setup_run_ready(
            model_overrides={"base_run_modes": ["STD_SHORT", "STD_LONG"]}
        )
        # kit defaults to run_type STD_SHORT; run_mode STD_LONG is unlocked.
        resp = _run_request(bag, run_mode="STD_LONG")
        validate_error(resp, ApiErrorId.ERR_KIT_RUN_TYPE_MISMATCH)

    def test_chemistry_unsupported_by_model_rejected(self, api):
        """The lot's kit runs V3 chemistry while the instrument model
        supports only V1/V2.

        PRD §3.7: "The gates evaluate in this relative order after the §2.9 tiers: the instrument's `install_state` must be `OPERATIONAL`, else `ERR_INSTRUMENT_NOT_OPERATIONAL`; the license must be `ACTIVE`, else `ERR_LICENSE_NOT_ACTIVE`; the lot's `qc_status` must be `QC_PASSED`, else `ERR_LOT_NOT_USABLE` (HTTP 409); the lot's `available_units` must be at least 1, else `ERR_LOT_DEPLETED` (HTTP 409); a lot whose cold chain is `BREACHED` is rejected with `ERR_COLD_CHAIN_BREACHED`; the lot's `expiry_date` must be strictly after the current logical clock, else `ERR_LOT_EXPIRED`; the clinical-clearance gate of §2.6 applies on `CLINICAL` instruments; the `run_mode` must be among the instrument's `unlocked_run_modes`, else `ERR_RUN_MODE_LOCKED` (HTTP 422); the lot's kit `run_type` must equal the `run_mode`, else `ERR_KIT_RUN_TYPE_MISMATCH` (HTTP 422); the kit's `chemistry_version` must appear in the instrument model's `supported_chemistry_versions`, else `ERR_CHEMISTRY_UNSUPPORTED` (HTTP 422); the kit's `min_model_generation` must not exceed the instrument model's `generation`, else `ERR_KIT_MODEL_INCOMPATIBLE` (HTTP 422); and a non-`FAILED` run in a cloud analysis mode requires a `credits_balance` of at least the run's cost, else `ERR_INSUFFICIENT_CREDITS` (HTTP 402)."

        Design: Corner/validations/chemistry_unsupported_by_model_rejected
        """
        bag = setup_run_ready(
            model_overrides={"supported_chemistry_versions": ["V1", "V2"]},
            kit_overrides={"chemistry_version": "V3",
                           "flow_cell_version": "FC_HIGH"},
        )
        resp = _run_request(bag)
        validate_error(resp, ApiErrorId.ERR_CHEMISTRY_UNSUPPORTED)

    def test_kit_min_generation_rejected(self, api):
        """The lot's kit demands generation >= 3 while the instrument model
        is generation 2, with run type, chemistry, and mode otherwise valid.

        PRD §3.7: "The gates evaluate in this relative order after the §2.9 tiers: the instrument's `install_state` must be `OPERATIONAL`, else `ERR_INSTRUMENT_NOT_OPERATIONAL`; the license must be `ACTIVE`, else `ERR_LICENSE_NOT_ACTIVE`; the lot's `qc_status` must be `QC_PASSED`, else `ERR_LOT_NOT_USABLE` (HTTP 409); the lot's `available_units` must be at least 1, else `ERR_LOT_DEPLETED` (HTTP 409); a lot whose cold chain is `BREACHED` is rejected with `ERR_COLD_CHAIN_BREACHED`; the lot's `expiry_date` must be strictly after the current logical clock, else `ERR_LOT_EXPIRED`; the clinical-clearance gate of §2.6 applies on `CLINICAL` instruments; the `run_mode` must be among the instrument's `unlocked_run_modes`, else `ERR_RUN_MODE_LOCKED` (HTTP 422); the lot's kit `run_type` must equal the `run_mode`, else `ERR_KIT_RUN_TYPE_MISMATCH` (HTTP 422); the kit's `chemistry_version` must appear in the instrument model's `supported_chemistry_versions`, else `ERR_CHEMISTRY_UNSUPPORTED` (HTTP 422); the kit's `min_model_generation` must not exceed the instrument model's `generation`, else `ERR_KIT_MODEL_INCOMPATIBLE` (HTTP 422); and a non-`FAILED` run in a cloud analysis mode requires a `credits_balance` of at least the run's cost, else `ERR_INSUFFICIENT_CREDITS` (HTTP 402)."

        Design: Corner/errors/kit_min_generation_rejected
        """
        bag = setup_run_ready(
            model_overrides={
                "generation": 2,
                "supported_chemistry_versions": ["V1", "V2", "V3"],
            },
            kit_overrides={
                "chemistry_version": "V3",
                "min_model_generation": 3,
                "flow_cell_version": "FC_HIGH",
            },
        )
        resp = _run_request(bag)
        validate_error(resp, ApiErrorId.ERR_KIT_MODEL_INCOMPATIBLE)

    def test_clinical_instrument_rejects_ruo_kit(self, api):
        """A CLINICAL instrument cannot consume a RUO_ONLY kit even when
        every other run precondition passes.

        PRD §2.6: "Recording a sequencing run on a `CLINICAL` instrument consumes only kits cleared `IVD`; a `RUO_ONLY` kit on such an instrument is rejected with `ERR_CHEMISTRY_NOT_CLEARED_FOR_CLINICAL` (HTTP 422)."

        Design: Corner/validations/clinical_instrument_rejects_ruo_kit
        """
        bag = setup_run_ready(
            regulatory_class="CLINICAL",
            model_overrides={"generation": 2,
                             "supported_chemistry_versions": ["V2"]},
            kit_overrides={"chemistry_version": "V2"},
        )
        assert bag["instrument"]["regulatory_mode"] == "CLINICAL"
        assert bag["kit"]["regulatory_clearance"] == "RUO_ONLY"
        resp = _run_request(bag)
        validate_error(resp, ApiErrorId.ERR_CHEMISTRY_NOT_CLEARED_FOR_CLINICAL)
        assert _lot(bag)["consumed_units"] == 0
