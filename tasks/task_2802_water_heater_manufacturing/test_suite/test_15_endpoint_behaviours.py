"""Reads and compensating writes exercised through their own endpoints.

The logical clock, the two computed reports, the immutable inspection listing and
the three recovery actions are driven here in the sequences that make their
contracts observable: what a report says about a cohort that does not exist, what
a returned component piece does and does not restore, and which of two identical
looking calls the service is willing to accept second.
"""

from types import SimpleNamespace

from test_helpers import (
    adhesion_inspection_payload,
    approve_payload,
    approx2,
    approx4,
    assert_component_lot_ledger,
    assert_envelope_meta,
    certification_approver_headers,
    compliance_engineer_headers,
    component_lot_payload,
    data_of,
    ERR_COMPLETION_BELOW_THRESHOLD,
    ERR_COMPONENT_SUPPLIER_NOT_QUALIFIED,
    ERR_HELD_UNITS_REMAIN,
    ERR_INVALID_CERTIFICATION_STATE,
    ERR_INVALID_MODEL_STATE,
    ERR_INVALID_NOTICE_STATE,
    ERR_INVALID_REQUEST,
    ERR_INVALID_UNIT_STATE,
    ERR_PRODUCT_MODEL_NOT_FOUND,
    ERR_SOD_APPROVER_IS_SUBMITTER,
    ERR_TANK_LOT_NOT_FOUND,
    holiday_inspection_payload,
    NON_EXISTENT_UUID,
    plant_admin_headers,
    plant_operator_headers,
    qualify_payload,
    quality_inspector_headers,
    reason_payload,
    safety_valve_lot_payload,
    safety_valve_supplier_payload,
    supplier_payload,
    supplier_quality_headers,
    USER_APPROVER,
    USER_ENGINEER_ALT,
    USER_INSPECTOR,
    USER_INSPECTOR_ALT,
    validate_error,
    validate_paginated,
    validate_success,
    warranty_analyst_headers,
    fixtures as x,
)

#: Ninety days after every shipment, so each unit reads exactly three whole months.
NINETY_DAYS_ON = "2026-11-03T06:00:00Z"
#: Two clock positions used to prove the roundtrip drives stored timestamps.
FIRST_MOVE = "2026-09-15T13:45:00Z"
SECOND_MOVE = "2026-09-16T00:00:00Z"
#: The August cohort key every unit in this file inherits from its tank lot.
AUGUST = "2026-08"
#: The serial the first labelled unit of the August cohort receives.
FIRST_SERIAL = "GX50-T-202608-00001"


def _three_shipped_units_in_three_hardness_bands(api):
    """One soft, one moderate and one very-hard installation, all ninety days old.

    The three hardnesses are chosen so the cohort's exposure measure and its band
    profile disagree in shape: the band counts are 1/1/0/1 while the exposure sum
    weights the same three units 0.80, 1.00 and 1.80.
    """
    plant = x.make_full_plant(api)
    soft = x.ship_unit(api, plant, hardness_gpg=2.0)
    moderate = x.ship_unit(api, plant, hardness_gpg=7.0)
    very_hard = x.ship_unit(api, plant, hardness_gpg=12.0)
    x.set_clock(api, NINETY_DAYS_ON)
    return plant, SimpleNamespace(soft=soft, moderate=moderate, very_hard=very_hard)


def _analysis(api, model_id, headers=None, **params):
    """One field-failure read, returning the raw response."""
    query = {"production_period": AUGUST}
    query.update(params)
    return api.get_warranty_analysis(model_id, headers or warranty_analyst_headers(), query)


class TestLogicalClockRoundtrip:
    """The clock the service admits to holding is the clock it stamps rows with."""

    def test_01_the_clock_opens_at_the_declared_instant_and_echoes_every_move(self, api):
        """A service that has never been moved reports the pinned startup instant.

        PRD: "On startup the logical clock reads exactly `2026-08-01T00:00:00Z`, and
        until an administrator moves it, that is the instant every rule sees; the service
        never falls back to host wall-clock time under any circumstance."

        Design: Corner/endpoints/clock_set_and_read_roundtrip_drives_every_timestamp
        """
        before = validate_success(api.read_clock(warranty_analyst_headers()))

        validate_success(api.set_clock(FIRST_MOVE, plant_admin_headers()))
        after = validate_success(api.read_clock(plant_operator_headers()))

        assert before["current_utc"].startswith("2026-08-01T00:00:00")
        assert after["current_utc"].startswith("2026-09-15T13:45:00")

    def test_02_a_row_is_stamped_from_the_clock_at_the_instant_it_is_written(self, api):
        """Creation freezes `created_at`; the later mutation moves only `updated_at`.

        PRD: "Thirteen of the fourteen resource types are mutable and additionally carry
        `updated_at` — an ISO 8601 UTC timestamp with three fractional digits, refreshed on
        every accepted mutation of that row — and `version`, an integer that starts at 1 when
        the row is created and increments by exactly 1 on every accepted mutation."

        Design: Corner/endpoints/clock_set_and_read_roundtrip_drives_every_timestamp
        """
        x.set_clock(api, FIRST_MOVE)
        created = x.make_pending_supplier(api)

        x.set_clock(api, SECOND_MOVE)
        qualified = data_of(
            api.qualify_supplier(created["id"], qualify_payload(), supplier_quality_headers())
        )

        assert created["created_at"].startswith("2026-09-15T13:45:00")
        assert created["updated_at"].startswith("2026-09-15T13:45:00")
        assert created["version"] == 1
        assert qualified["created_at"].startswith("2026-09-15T13:45:00")
        assert qualified["updated_at"].startswith("2026-09-16T00:00:00")
        assert qualified["version"] == 2
        assert qualified["qualification_status"] == "QUALIFIED"

    def test_03_every_read_carries_the_two_request_meta_fields(self, api):
        """Both the clock read and the supplier read answer inside the same envelope.

        PRD: "The `api_request_id` is a server-generated unique identifier for the
        request that starts with `req_`."

        Design: Corner/endpoints/clock_set_and_read_roundtrip_drives_every_timestamp
        """
        supplier = x.make_pending_supplier(api)

        clock_read = api.read_clock(plant_admin_headers())
        supplier_read = api.get_supplier(supplier["id"], plant_admin_headers())

        for response in (clock_read, supplier_read):
            validate_success(response)
            assert_envelope_meta(response)
            assert response.json()["response_type"] == "object"


class TestFieldFailureAnalysisRead:
    """One cohort, two denominators, and one period that holds nothing at all."""

    def test_04_the_default_read_is_the_naive_cohort_view(self, api):
        """Three shipped units, no tank-leak claims, and a rate of exactly zero.

        PRD: "The report echoes `production_period` and `variant` and returns
        `shipped_unit_count` as the size of the cohort."

        Design: Corner/endpoints/warranty_analysis_read_hardness_mix_and_empty_cohort
        """
        plant, _units = _three_shipped_units_in_three_hardness_bands(api)

        report = validate_success(_analysis(api, plant.model_id))

        assert report["production_period"] == AUGUST
        assert report["variant"] == "COHORT_NAIVE"
        assert report["shipped_unit_count"] == 3
        assert report["tank_leak_claim_count"] == 0
        assert report["failure_rate_ppm"] == 0.0

    def test_05_the_band_profile_and_the_exposure_sum_describe_the_same_cohort(self, api):
        """Band counts sum to the cohort while the exposure sum weights it by hardness.

        PRD: "The report closes with the cohort's water-chemistry profile:
        `soft_unit_count`, `moderate_unit_count`, `hard_unit_count` and
        `very_hard_unit_count`, which are the counts of cohort units in each
        `water_hardness_band` and which always sum to `shipped_unit_count`."

        Design: Corner/endpoints/warranty_analysis_read_hardness_mix_and_empty_cohort
        """
        plant, _units = _three_shipped_units_in_three_hardness_bands(api)

        report = validate_success(_analysis(api, plant.model_id))

        assert report["soft_unit_count"] == 1
        assert report["moderate_unit_count"] == 1
        assert report["hard_unit_count"] == 0
        assert report["very_hard_unit_count"] == 1
        assert (
            report["soft_unit_count"]
            + report["moderate_unit_count"]
            + report["hard_unit_count"]
            + report["very_hard_unit_count"]
            == report["shipped_unit_count"]
        )
        assert report["weighted_exposure_unit_months"] == approx2(10.80)

    def test_06_the_weighted_variant_changes_the_denominator_and_nothing_else(self, api):
        """A zero numerator is still zero once the denominator becomes unit-months.

        PRD: "The `EXPOSURE_WEIGHTED` variant — the reliability-engineering view —
        divides the same `tank_leak_claim_count` by `weighted_exposure_unit_months` and
        multiplies by 1,000,000, expressing the rate per million weighted unit-months
        instead."

        Design: Corner/endpoints/warranty_analysis_read_hardness_mix_and_empty_cohort
        """
        plant, _units = _three_shipped_units_in_three_hardness_bands(api)

        weighted = validate_success(
            _analysis(
                api,
                plant.model_id,
                headers=compliance_engineer_headers(),
                variant="EXPOSURE_WEIGHTED",
            )
        )

        assert weighted["variant"] == "EXPOSURE_WEIGHTED"
        assert weighted["shipped_unit_count"] == 3
        assert weighted["tank_leak_claim_count"] == 0
        assert weighted["weighted_exposure_unit_months"] == approx2(10.80)
        assert weighted["failure_rate_ppm"] == 0.0

    def test_07_a_period_that_produced_nothing_reports_zeroes_not_an_error(self, api):
        """July holds no units, so every figure in the report collapses to zero.

        PRD: "Whenever the selected variant's denominator is zero — an empty cohort in
        the naive case, or a cohort in which every unit has zero elapsed months in the
        weighted case — the rate is reported as exactly 0.0 rather than as an error or an
        infinity."

        Design: Corner/endpoints/warranty_analysis_read_hardness_mix_and_empty_cohort
        """
        plant, _units = _three_shipped_units_in_three_hardness_bands(api)

        empty = validate_success(_analysis(api, plant.model_id, production_period="2026-07"))

        assert empty["production_period"] == "2026-07"
        assert empty["shipped_unit_count"] == 0
        assert empty["weighted_exposure_unit_months"] == approx2(0.00)
        assert empty["failure_rate_ppm"] == 0.0
        assert empty["soft_unit_count"] == 0
        assert empty["moderate_unit_count"] == 0
        assert empty["hard_unit_count"] == 0
        assert empty["very_hard_unit_count"] == 0

    def test_08_the_period_parameter_is_mandatory_on_the_report(self, api):
        """Omitting the cohort key is malformed rather than defaulted.

        PRD: "It takes a mandatory `production_period` query parameter — omitting it is
        a malformed request reported as `ERR_INVALID_REQUEST` — and an optional `variant`
        selecting between the two denominators, which takes the value `COHORT_NAIVE` or
        `EXPOSURE_WEIGHTED` and defaults to the naive cohort view when it is omitted."

        Design: Corner/endpoints/warranty_analysis_read_hardness_mix_and_empty_cohort
        """
        plant, _units = _three_shipped_units_in_three_hardness_bands(api)

        response = api.get_warranty_analysis(plant.model_id, warranty_analyst_headers())

        validate_error(response, ERR_INVALID_REQUEST, expected_status=400)

    def test_09_a_model_that_does_not_exist_is_resolved_before_the_report_runs(self, api):
        """The path id is checked first, so no cohort is ever computed.

        PRD: "A missing row yields that entity's own not-found code:
        `ERR_SUPPLIER_NOT_FOUND`, `ERR_COMPONENT_LOT_NOT_FOUND`, `ERR_FURNACE_NOT_FOUND`,
        `ERR_GLASS_LINING_BATCH_NOT_FOUND`, `ERR_TANK_LOT_NOT_FOUND`,
        `ERR_LINING_INSPECTION_NOT_FOUND`, `ERR_PRODUCT_MODEL_NOT_FOUND`,
        `ERR_TEST_CELL_NOT_FOUND`, `ERR_EFFICIENCY_TEST_NOT_FOUND`,
        `ERR_RATING_CERTIFICATION_NOT_FOUND`, `ERR_HEATER_UNIT_NOT_FOUND`,
        `ERR_WARRANTY_CLAIM_NOT_FOUND`, `ERR_RECALL_CAMPAIGN_NOT_FOUND` or
        `ERR_RECALL_NOTICE_NOT_FOUND`, each HTTP 404."

        Design: Corner/endpoints/warranty_analysis_read_hardness_mix_and_empty_cohort
        """
        _three_shipped_units_in_three_hardness_bands(api)

        response = _analysis(api, NON_EXISTENT_UUID)

        validate_error(response, ERR_PRODUCT_MODEL_NOT_FOUND, expected_status=404)

    def test_10_the_reports_leave_the_units_they_read_untouched(self, api):
        """Elapsed service months are recomputed on the read, not written by it.

        PRD: "From shipment onward a unit read reports `months_in_service`, recomputed
        on every read as the whole number of 30-day months that have elapsed between
        `shipped_at` and the current logical clock, truncated downward and never rounded up;
        it stays null while `shipped_at` is null."

        Design: Corner/endpoints/warranty_analysis_read_hardness_mix_and_empty_cohort
        """
        plant, units = _three_shipped_units_in_three_hardness_bands(api)
        before = validate_success(api.get_heater_unit(units.soft, warranty_analyst_headers()))

        validate_success(_analysis(api, plant.model_id))
        validate_success(_analysis(api, plant.model_id, variant="EXPOSURE_WEIGHTED"))
        after = validate_success(api.get_heater_unit(units.soft, warranty_analyst_headers()))

        assert after["version"] == before["version"]
        assert after["months_in_service"] == 3
        assert after["water_hardness_band"] == "SOFT"
        assert after["hardness_factor"] == approx2(0.80)
        assert after["shipped_at"].startswith("2026-08-05T06:00:00")


def _a_plant_whose_gas_lot_holds_exactly_two_pieces(api):
    """A released plant whose gas-valve lot is exhausted by two units.

    Sizing the gas lot at two pieces and the valve lot at five means the second
    assembly drives the gas lot to `CONSUMED` while the valve lot stays `RELEASED`,
    so one disassembly afterwards touches two lots in two different states.
    """
    gas_supplier = x.make_qualified_supplier(api, supplier_payload())
    valve_supplier = data_of(
        api.create_supplier(safety_valve_supplier_payload(), supplier_quality_headers())
    )
    data_of(
        api.qualify_supplier(
            valve_supplier["id"],
            qualify_payload(audit_score=92, defect_ppm=1500, open_capa_count=1),
            supplier_quality_headers(),
        )
    )
    gas_lot = data_of(
        api.create_component_lot(
            component_lot_payload(gas_supplier["id"], quantity=2), supplier_quality_headers()
        )
    )
    data_of(api.release_component_lot(gas_lot["id"], quality_inspector_headers()))
    valve_lot = data_of(
        api.create_component_lot(
            safety_valve_lot_payload(valve_supplier["id"], quantity=5),
            supplier_quality_headers(),
        )
    )
    data_of(api.release_component_lot(valve_lot["id"], quality_inspector_headers()))
    model = x.make_released_model(api)
    batch = x.make_fired_batch(api)
    tank_lot_id = x.make_released_tank_lot(api, model.model_id, batch.batch_id)
    return SimpleNamespace(
        model_id=model.model_id,
        cert_id=model.cert_id,
        tank_lot_id=tank_lot_id,
        gas_lot_id=gas_lot["id"],
        valve_lot_id=valve_lot["id"],
    )


def _one_shipped_and_one_assembled_unit_from_the_same_two_lots(api):
    """Draw both gas pieces: the first unit ships, the second stops at assembly."""
    plant = _a_plant_whose_gas_lot_holds_exactly_two_pieces(api)
    shipped = x.ship_unit(api, plant, hardness_gpg=12.0)
    assembled = x.assemble_unit(api, plant)
    return plant, shipped, assembled


class TestDisassemblyReturnsPieces:
    """Returning a piece rebuilds the ledger without reviving a terminal lot."""

    def test_11_a_unit_that_has_already_shipped_cannot_be_disassembled(self, api):
        """The field is out of reach of the compensating action.

        PRD: "Shipping a `HELD` unit, or disassembling one that has already shipped,
        both report `ERR_INVALID_UNIT_STATE`."

        Design: Corner/endpoints/disassemble_returns_pieces_without_resurrecting_consumed_lot
        """
        _plant, shipped, _assembled = _one_shipped_and_one_assembled_unit_from_the_same_two_lots(api)

        response = api.disassemble_unit(
            shipped, reason_payload("SCRAP_DEFECT"), plant_operator_headers()
        )

        validate_error(response, ERR_INVALID_UNIT_STATE, expected_status=409)
        still_out = validate_success(api.get_heater_unit(shipped, plant_operator_headers()))
        assert still_out["build_status"] == "SHIPPED"
        assert still_out["shipped_at"].startswith("2026-08-05T06:00:00")

    def test_12_the_returned_piece_restores_the_ledger_but_not_the_lot_status(self, api):
        """The exhausted gas lot counts its piece back and stays `CONSUMED`.

        PRD: "One asymmetry is deliberate: a lot that had already reached the terminal
        `CONSUMED` is **not** resurrected by the return and stays `CONSUMED` even though its
        `remaining_quantity` is now at least 1."

        Design: Corner/endpoints/disassemble_returns_pieces_without_resurrecting_consumed_lot
        """
        plant, _shipped, assembled = _one_shipped_and_one_assembled_unit_from_the_same_two_lots(api)

        scrapped = validate_success(
            api.disassemble_unit(
                assembled, reason_payload("SCRAP_DEFECT"), plant_operator_headers()
            )
        )

        gas = validate_success(api.get_component_lot(plant.gas_lot_id, plant_operator_headers()))
        valve = validate_success(
            api.get_component_lot(plant.valve_lot_id, plant_operator_headers())
        )
        assert scrapped["build_status"] == "SCRAPPED"
        assert scrapped["hold_reason_code"] == "SCRAP_DEFECT"
        assert gas["quantity"] == 2
        assert gas["consumed_quantity"] == 1
        assert gas["remaining_quantity"] == 1
        assert gas["status"] == "CONSUMED"
        assert_component_lot_ledger(gas)
        assert valve["status"] == "RELEASED"
        assert valve["consumed_quantity"] == 1
        assert valve["remaining_quantity"] == 4
        assert_component_lot_ledger(valve)

    def test_13_a_scrapped_unit_stops_occupying_its_tank_lot(self, api):
        """Only the shipped unit still counts against the lot's output.

        PRD: "Its `unit_count` is derived at read time as the number of heater units
        drawn from this lot whose `build_status` is anything other than `SCRAPPED`."

        Design: Corner/endpoints/disassemble_returns_pieces_without_resurrecting_consumed_lot
        """
        plant, _shipped, assembled = _one_shipped_and_one_assembled_unit_from_the_same_two_lots(api)

        data_of(
            api.disassemble_unit(
                assembled, reason_payload("SCRAP_DEFECT"), plant_operator_headers()
            )
        )

        lot = validate_success(api.get_tank_lot(plant.tank_lot_id, quality_inspector_headers()))
        assert lot["unit_count"] == 1

    def test_14_a_replacement_unit_stages_but_cannot_draw_from_the_consumed_lot(self, api):
        """Staging never inspects lot status; assembly always does.

        PRD: "A lot that is not `RELEASED` — including one that has already reached
        `CONSUMED` because its last piece was drawn — or a supplier that is `PENDING` or
        `DISQUALIFIED`, is refused with `ERR_COMPONENT_SUPPLIER_NOT_QUALIFIED`; a supplier
        whose `qualified_until` is strictly before the current logical clock is refused with
        `ERR_QUALIFICATION_EXPIRED`, while a `qualified_until` exactly at the current instant
        is accepted."

        Design: Corner/endpoints/disassemble_returns_pieces_without_resurrecting_consumed_lot
        """
        plant, _shipped, assembled = _one_shipped_and_one_assembled_unit_from_the_same_two_lots(api)
        data_of(
            api.disassemble_unit(
                assembled, reason_payload("SCRAP_DEFECT"), plant_operator_headers()
            )
        )

        replacement = x.stage_unit(api, plant)
        response = api.assemble_unit(replacement, plant_operator_headers())

        validate_error(response, ERR_COMPONENT_SUPPLIER_NOT_QUALIFIED, expected_status=409)
        model = validate_success(
            api.get_product_model(plant.model_id, compliance_engineer_headers())
        )
        assert model["warranty_reserve_accrued_cents"] == 42000
        assert model["held_unit_count"] == 0


def _a_certification_rejected_by_the_approver(api):
    """A model with a full passing programme whose first submission was refused.

    The submitter of record is the engineer who filed it, and the approver who
    refused it is the one who becomes eligible again once somebody else resubmits.
    """
    model = x.make_model(api)
    cell = x.make_test_cell(api)
    x.make_passing_test_suite(api, model["id"], cell["id"])
    cert = x.make_submitted_certification(api, model["id"])
    return model["id"], cert["id"]


class TestCertificationRevisionLoop:
    """A rejection reopens the loop and moves the separation-of-duties target with it."""

    def test_15_rejection_clears_the_computed_ratings_and_reopens_the_programme(self, api):
        """The certificate keeps its reason code; the model waits at `TEST_PENDING`.

        PRD: "Rejection takes the certificate `SUBMITTED → REJECTED`, stores the
        supplied `reason_code`, and clears the computed `certified_uef`, `certified_fhr` and
        `certified_recovery` so that a resubmission must recompute them."

        Design: Corner/endpoints/certification_reject_then_resubmit_moves_the_sod_target
        """
        model_id, cert_id = _a_certification_rejected_by_the_approver(api)

        rejected = validate_success(
            api.reject_certification(
                cert_id,
                reason_payload("MISSING_TEST_DATA"),
                certification_approver_headers(),
            )
        )

        assert rejected["status"] == "REJECTED"
        assert rejected["reason_code"] == "MISSING_TEST_DATA"
        assert rejected["certified_uef"] is None
        assert rejected["certified_fhr"] is None
        assert rejected["certified_recovery"] is None
        model = validate_success(api.get_product_model(model_id, compliance_engineer_headers()))
        assert model["certification_status"] == "TEST_PENDING"
        assert model["uef_rated"] is None

    def test_16_a_rejected_certificate_is_resubmitted_not_approved(self, api):
        """Approval only ever reads `SUBMITTED`; the resubmission recomputes the ratings.

        PRD: "Submission also stores the caller's `X-User-ID` as `submitted_by_user_id`;
        on a resubmission it **overwrites** that value with the resubmitting engineer's id and
        clears `reason_code`, which is why the approver eligible in one round may not be
        eligible in the next."

        Design: Corner/endpoints/certification_reject_then_resubmit_moves_the_sod_target
        """
        model_id, cert_id = _a_certification_rejected_by_the_approver(api)
        data_of(
            api.reject_certification(
                cert_id,
                reason_payload("MISSING_TEST_DATA"),
                certification_approver_headers(),
            )
        )

        premature = api.approve_certification(
            cert_id, approve_payload(), certification_approver_headers()
        )
        resubmitted = validate_success(
            api.submit_certification(cert_id, compliance_engineer_headers(USER_ENGINEER_ALT))
        )

        validate_error(premature, ERR_INVALID_CERTIFICATION_STATE, expected_status=409)
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["submitted_by_user_id"] == USER_ENGINEER_ALT
        assert resubmitted["reason_code"] is None
        assert resubmitted["certified_uef"] == approx2(0.59)
        assert resubmitted["certified_fhr"] == 63
        assert resubmitted["certified_recovery"] == approx2(41.3)
        assert resubmitted["uef_test_count"] == 3
        assert model_id == resubmitted["product_model_id"]

    def test_17_the_new_submitter_is_barred_and_the_earlier_rejecter_is_not(self, api):
        """Separation of duties follows the id on the certificate, not the round number.

        PRD: "Adjudication belongs exclusively to a `CertificationApprover`, and both
        outcomes require the caller's `X-User-ID` to differ from `submitted_by_user_id`,
        failing with `ERR_SOD_APPROVER_IS_SUBMITTER`."

        Design: Corner/endpoints/certification_reject_then_resubmit_moves_the_sod_target
        """
        model_id, cert_id = _a_certification_rejected_by_the_approver(api)
        data_of(
            api.reject_certification(
                cert_id,
                reason_payload("MISSING_TEST_DATA"),
                certification_approver_headers(),
            )
        )
        data_of(api.submit_certification(cert_id, compliance_engineer_headers(USER_ENGINEER_ALT)))

        self_approval = api.approve_certification(
            cert_id, approve_payload(), certification_approver_headers(USER_ENGINEER_ALT)
        )
        approved = validate_success(
            api.approve_certification(
                cert_id, approve_payload(), certification_approver_headers(USER_APPROVER)
            )
        )

        validate_error(self_approval, ERR_SOD_APPROVER_IS_SUBMITTER, expected_status=403)
        assert approved["status"] == "APPROVED"
        assert approved["approved_by_user_id"] == USER_APPROVER
        model = validate_success(api.get_product_model(model_id, compliance_engineer_headers()))
        assert model["certification_status"] == "CERTIFIED"
        assert model["uef_rated"] == approx2(0.59)
        assert model["label_serial_prefix"] == "GX50-T"
        assert model["release_status"] == "DRAFT"


def _two_adhesion_records_then_one_holiday_record(api):
    """One lined lot carrying three records, the first of them already superseded.

    The two adhesion records are filed by different inspectors so the stored
    `inspector_user_id` on the superseded row can be told apart from the current one.
    """
    model = x.make_model(api)
    batch = x.make_fired_batch(api)
    lot_id = x.make_lined_tank_lot(api, model["id"], batch.batch_id)
    first = data_of(
        api.create_lining_inspection(
            adhesion_inspection_payload(lot_id, x.tank_lot_version(api, lot_id)),
            quality_inspector_headers(USER_INSPECTOR),
        )
    )
    second = data_of(
        api.create_lining_inspection(
            adhesion_inspection_payload(
                lot_id, x.tank_lot_version(api, lot_id), sample_size=8, adhesion_class=2
            ),
            quality_inspector_headers(USER_INSPECTOR_ALT),
        )
    )
    third = data_of(
        api.create_lining_inspection(
            holiday_inspection_payload(lot_id, x.tank_lot_version(api, lot_id)),
            quality_inspector_headers(USER_INSPECTOR),
        )
    )
    return lot_id, SimpleNamespace(first=first["id"], second=second["id"], third=third["id"])


class TestLiningInspectionSubResource:
    """The only channel that still shows a superseded measurement."""

    def test_18_the_sub_resource_returns_current_and_superseded_alike_in_order(self, api):
        """All three records, oldest first, with the first adhesion row superseded.

        PRD: "Every accepted record stores the caller's `X-User-ID` as
        `inspector_user_id` and enters at `record_status` `CURRENT`; any earlier record of the
        **same** `inspection_type` on the same lot moves to `record_status` `SUPERSEDED`."

        Design: Corner/endpoints/lining_inspections_sub_resource_ordering_and_filters
        """
        lot_id, records = _two_adhesion_records_then_one_holiday_record(api)

        rows, meta = validate_paginated(
            api.list_lot_lining_inspections(
                lot_id, plant_operator_headers(), {"limit": 10, "offset": 0}
            )
        )

        assert meta["total_count"] == 3
        assert [row["id"] for row in rows] == [records.first, records.second, records.third]
        assert rows[0]["record_status"] == "SUPERSEDED"
        assert rows[0]["adhesion_class"] == 1
        assert rows[0]["result"] == "PASS"
        assert rows[0]["holidays_per_tank"] is None
        assert rows[0]["inspector_user_id"] == USER_INSPECTOR
        assert rows[1]["record_status"] == "CURRENT"
        assert rows[1]["adhesion_class"] == 2
        assert rows[1]["result"] == "PASS"
        assert rows[1]["inspector_user_id"] == USER_INSPECTOR_ALT
        assert rows[2]["holidays_per_tank"] == approx4(0.5000)
        assert rows[2]["result"] == "PASS"

    def test_19_no_returned_record_carries_a_version(self, api):
        """The immutable measurement has nothing to version.

        PRD: "Both `updated_at` and `version` are **absent** from every
        lining-inspection response — the single-record read and the per-lot sub-resource
        listing alike."

        Design: Corner/endpoints/lining_inspections_sub_resource_ordering_and_filters
        """
        lot_id, records = _two_adhesion_records_then_one_holiday_record(api)

        rows, _meta = validate_paginated(
            api.list_lot_lining_inspections(
                lot_id, quality_inspector_headers(), {"limit": 10, "offset": 0}
            )
        )
        single = validate_success(api.get_lining_inspection(records.first, plant_admin_headers()))

        for row in rows:
            assert "version" not in row
            assert "updated_at" not in row
        assert "version" not in single
        assert "updated_at" not in single

    def test_20_the_two_filters_and_the_window_narrow_the_same_history(self, api):
        """Type, record status and paging each cut a different slice of the three rows.

        PRD: "Inspection records are readable one at a time by `id`, and the per-lot
        sub-resource listing returns every record ever written against a lot, `CURRENT` and
        `SUPERSEDED` alike, in `created_at` ascending order, optionally narrowed by
        `inspection_type` or `record_status`; it is the only channel through which superseded
        records, and the records belonging to lots swept up by a batch-quarantine cascade, can
        be discovered."

        Design: Corner/endpoints/lining_inspections_sub_resource_ordering_and_filters
        """
        lot_id, records = _two_adhesion_records_then_one_holiday_record(api)

        adhesion, _m1 = validate_paginated(
            api.list_lot_lining_inspections(
                lot_id,
                quality_inspector_headers(),
                {"inspection_type": "ADHESION", "limit": 10, "offset": 0},
            )
        )
        current, _m2 = validate_paginated(
            api.list_lot_lining_inspections(
                lot_id,
                quality_inspector_headers(),
                {"record_status": "CURRENT", "limit": 10, "offset": 0},
            )
        )
        superseded_adhesion, _m3 = validate_paginated(
            api.list_lot_lining_inspections(
                lot_id,
                compliance_engineer_headers(),
                {
                    "inspection_type": "ADHESION",
                    "record_status": "SUPERSEDED",
                    "limit": 1,
                    "offset": 0,
                },
            )
        )
        last_only, _m4 = validate_paginated(
            api.list_lot_lining_inspections(
                lot_id, plant_admin_headers(), {"limit": 1, "offset": 2}
            )
        )

        assert [row["id"] for row in adhesion] == [records.first, records.second]
        assert [row["id"] for row in current] == [records.second, records.third]
        assert [row["id"] for row in superseded_adhesion] == [records.first]
        assert [row["id"] for row in last_only] == [records.third]

    def test_21_the_parent_lot_is_resolved_before_the_listing_is_considered(self, api):
        """An unknown lot id is a tank-lot problem, never an empty page.

        PRD: "For a nested path such as the per-lot inspection listing, the tank lot is
        resolved before anything else about the request is considered."

        Design: Corner/endpoints/lining_inspections_sub_resource_ordering_and_filters
        """
        _two_adhesion_records_then_one_holiday_record(api)

        response = api.list_lot_lining_inspections(
            NON_EXISTENT_UUID, quality_inspector_headers(), {"limit": 10, "offset": 0}
        )

        validate_error(response, ERR_TANK_LOT_NOT_FOUND, expected_status=404)


def _four_notices_with_two_remedied_and_one_unreachable(api):
    """A campaign over four shipped units, three of whose owners answered.

    Every affected unit shipped, so the two completion denominators start out equal
    and only the notice outcomes can move them apart.
    """
    plant = x.make_full_plant(api)
    for _ in range(4):
        x.ship_unit(api, plant, hardness_gpg=12.0)
    campaign = x.make_announced_campaign(
        api,
        plant.model_id,
        "GX50-T-202608-00001",
        "GX50-T-202608-00004",
        budget_cents=150000,
    )
    notices = x.campaign_notices(api, campaign["id"])
    for notice in notices:
        data_of(api.notify_notice(notice["id"], warranty_analyst_headers()))
    data_of(api.remedy_notice(notices[0]["id"], warranty_analyst_headers()))
    data_of(api.remedy_notice(notices[1]["id"], warranty_analyst_headers()))
    data_of(
        api.mark_notice_unreachable(
            notices[2]["id"], warranty_analyst_headers(), reason_payload("OWNER_MOVED")
        )
    )
    return campaign["id"], notices


class TestCampaignCompletionRead:
    """An unreachable owner is a failure to reach, never a shrinking denominator."""

    def test_22_the_completion_read_reports_both_denominators_and_both_outcomes(self, api):
        """Two remedies out of four notices and four units in scope: 50.00 either way.

        PRD: "Campaign completion is reported by a computed read available to a
        `WarrantyAnalyst`, a `PlantAdmin` or a `ComplianceEngineer`, which returns
        `affected_unit_count` as snapshotted at scoping, `notice_count` as the number of notices
        actually issued, `remedied_count` as the number in `status` `REMEDIED`,
        `unreachable_count` as the number in `status` `UNREACHABLE`, and two completion
        percentages that are deliberately allowed to disagree."

        Design: Corner/endpoints/completion_read_keeps_unreachable_notices_in_both_denominators
        """
        campaign_id, _notices = _four_notices_with_two_remedied_and_one_unreachable(api)

        completion = validate_success(
            api.get_campaign_completion(campaign_id, warranty_analyst_headers())
        )

        assert completion["affected_unit_count"] == 4
        assert completion["notice_count"] == 4
        assert completion["remedied_count"] == 2
        assert completion["unreachable_count"] == 1
        assert completion["completion_pct_notice_based"] == approx2(50.00)
        assert completion["completion_pct_population_based"] == approx2(50.00)

    def test_23_a_campaign_at_half_completion_cannot_be_closed(self, api):
        """Fifty percent of the population is a long way short of the threshold.

        PRD: "First, `completion_pct_population_based` must be at least 80.00 — exactly
        80.00 passes, and anything below is refused with `ERR_COMPLETION_BELOW_THRESHOLD` —
        which means the notice-based figure being at or above the threshold is not sufficient on
        its own."

        Design: Corner/endpoints/completion_read_keeps_unreachable_notices_in_both_denominators
        """
        campaign_id, _notices = _four_notices_with_two_remedied_and_one_unreachable(api)

        response = api.close_campaign(campaign_id, warranty_analyst_headers())

        validate_error(response, ERR_COMPLETION_BELOW_THRESHOLD, expected_status=409)

    def test_24_neither_terminal_notice_state_admits_a_further_action(self, api):
        """An unreachable notice cannot be remedied, and a remedied one cannot go missing.

        PRD: "`REMEDIED` and `UNREACHABLE` are both terminal, and acting further on
        either reports `ERR_INVALID_NOTICE_STATE`."

        Design: Corner/endpoints/completion_read_keeps_unreachable_notices_in_both_denominators
        """
        _campaign_id, notices = _four_notices_with_two_remedied_and_one_unreachable(api)

        remedy_the_unreachable = api.remedy_notice(
            notices[2]["id"], warranty_analyst_headers()
        )
        lose_the_remedied = api.mark_notice_unreachable(
            notices[0]["id"], warranty_analyst_headers(), reason_payload("OWNER_MOVED")
        )

        validate_error(remedy_the_unreachable, ERR_INVALID_NOTICE_STATE, expected_status=409)
        validate_error(lose_the_remedied, ERR_INVALID_NOTICE_STATE, expected_status=409)

    def test_25_the_last_reachable_remedy_still_leaves_the_campaign_short(self, api):
        """Three of four remedies is 75.00 on both measures, and 75.00 does not close.

        PRD: "An unreachable notice is a failure to reach an owner, not a removal of an
        obligation: it stays in the issued-notice denominator, so making owners unreachable can
        never be used to inflate a completion percentage."

        Design: Corner/endpoints/completion_read_keeps_unreachable_notices_in_both_denominators
        """
        campaign_id, notices = _four_notices_with_two_remedied_and_one_unreachable(api)

        remedied = validate_success(
            api.remedy_notice(notices[3]["id"], warranty_analyst_headers())
        )
        completion = validate_success(
            api.get_campaign_completion(campaign_id, compliance_engineer_headers())
        )
        refused = api.close_campaign(campaign_id, warranty_analyst_headers())

        assert remedied["status"] == "REMEDIED"
        assert remedied["remedied_at"].startswith("2026-08-05T06:00:00")
        assert completion["remedied_count"] == 3
        assert completion["unreachable_count"] == 1
        assert completion["notice_count"] == 4
        assert completion["completion_pct_notice_based"] == approx2(75.00)
        assert completion["completion_pct_population_based"] == approx2(75.00)
        validate_error(refused, ERR_COMPLETION_BELOW_THRESHOLD, expected_status=409)
        campaign = validate_success(
            api.get_recall_campaign(campaign_id, warranty_analyst_headers())
        )
        assert campaign["status"] == "IN_REMEDY"


def _a_decertified_model_holding_one_labelled_unit(api):
    """One labelled unit, then the certificate behind its label is revoked.

    The revocation drives the model to `DECERTIFIED` and `RESTRICTED` and the unit to
    `HELD` with an invalidated label, which is the only way the restriction is entered.
    """
    plant = x.make_full_plant(api)
    unit_id = x.label_unit(api, plant)
    data_of(
        api.revoke_certification(
            plant.cert_id,
            reason_payload("TEST_DATA_INVALID"),
            certification_approver_headers(),
        )
    )
    return plant, unit_id


class TestLiftingARestriction:
    """Two independent conditions, and neither one implies the other."""

    def test_26_a_restriction_cannot_be_lifted_while_a_unit_is_still_held(self, api):
        """The held unit blocks the lift and the model stays where the cascade left it.

        PRD: "A model with units still held reports `ERR_HELD_UNITS_REMAIN`; a model
        that is not `RESTRICTED` at all reports `ERR_INVALID_MODEL_STATE`."

        Design: Corner/endpoints/lift_restriction_requires_zero_held_units_and_restricted_state
        """
        plant, _unit_id = _a_decertified_model_holding_one_labelled_unit(api)

        response = api.lift_model_restriction(plant.model_id, plant_admin_headers())

        validate_error(response, ERR_HELD_UNITS_REMAIN, expected_status=409)
        model = validate_success(
            api.get_product_model(plant.model_id, compliance_engineer_headers())
        )
        assert model["release_status"] == "RESTRICTED"
        assert model["held_unit_count"] == 1
        assert model["certification_status"] == "DECERTIFIED"

    def test_27_an_invalidated_label_can_never_be_restored(self, api):
        """The unit cannot leave the hold the way it came in.

        PRD: "When `held_from_status` is `LABELED` the unit returns `HELD → LABELED`;
        here the component lots are not re-examined, but `label_status` must still be `APPLIED`
        — a unit whose label was invalidated can never be restored to `LABELED` and reports
        `ERR_INVALID_UNIT_STATE` — and the model's `certification_status` must again not be
        `DECERTIFIED`, failing with `ERR_MODEL_NOT_CERTIFIED`."

        Design: Corner/endpoints/lift_restriction_requires_zero_held_units_and_restricted_state
        """
        _plant, unit_id = _a_decertified_model_holding_one_labelled_unit(api)

        response = api.release_unit_hold(unit_id, plant_operator_headers())

        validate_error(response, ERR_INVALID_UNIT_STATE, expected_status=409)
        unit = validate_success(api.get_heater_unit(unit_id, plant_operator_headers()))
        assert unit["build_status"] == "HELD"
        assert unit["label_status"] == "INVALID"
        assert unit["held_from_status"] == "LABELED"

    def test_28_scrapping_the_held_unit_empties_the_count_without_lifting_anything(self, api):
        """The count falls to zero inside the disassembly, and the model stays restricted.

        PRD: "When the disassembled unit was `HELD`, the owning model recomputes
        `held_unit_count`, and even when that count falls to 0 the model remains `RESTRICTED`
        until an administrator explicitly lifts the restriction."

        Design: Corner/endpoints/lift_restriction_requires_zero_held_units_and_restricted_state
        """
        plant, unit_id = _a_decertified_model_holding_one_labelled_unit(api)

        scrapped = validate_success(
            api.disassemble_unit(
                unit_id, reason_payload("DECERTIFIED_STOCK"), plant_operator_headers()
            )
        )

        assert scrapped["build_status"] == "SCRAPPED"
        assert scrapped["hold_reason_code"] == "DECERTIFIED_STOCK"
        assert scrapped["serial_number"] == FIRST_SERIAL
        model = validate_success(
            api.get_product_model(plant.model_id, compliance_engineer_headers())
        )
        assert model["held_unit_count"] == 0
        assert model["release_status"] == "RESTRICTED"
        assert model["warranty_reserve_accrued_cents"] == 0

    def test_29_the_lift_is_granted_once_and_then_has_nothing_left_to_grant(self, api):
        """Release returns to `RELEASED` alone; the certification dimension is untouched.

        PRD: "Returning from restriction is a deliberate administrative act rather than
        an automatic recovery: a `PlantAdmin` lifts the restriction, moving the model
        `RESTRICTED → RELEASED`, and the call requires `held_unit_count` to be exactly 0."

        Design: Corner/endpoints/lift_restriction_requires_zero_held_units_and_restricted_state
        """
        plant, unit_id = _a_decertified_model_holding_one_labelled_unit(api)
        data_of(
            api.disassemble_unit(
                unit_id, reason_payload("DECERTIFIED_STOCK"), plant_operator_headers()
            )
        )

        lifted = validate_success(
            api.lift_model_restriction(plant.model_id, plant_admin_headers())
        )
        again = api.lift_model_restriction(plant.model_id, plant_admin_headers())

        assert lifted["release_status"] == "RELEASED"
        assert lifted["certification_status"] == "DECERTIFIED"
        assert lifted["uef_rated"] is None
        assert lifted["held_unit_count"] == 0
        validate_error(again, ERR_INVALID_MODEL_STATE, expected_status=409)
