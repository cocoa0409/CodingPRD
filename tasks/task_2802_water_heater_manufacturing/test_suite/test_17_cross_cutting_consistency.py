"""Two version pins, one derived counter, and a promise about write responses.

Every rule in this file is about what a single request settles. A create that
supersedes a sibling does both inside one call; a create whose pin has gone stale
leaves neither a row nor a version bump behind; a derived counter that falls to
zero still waits for an administrator; and the response to a write already carries
every field a later read would repeat.
"""

from types import SimpleNamespace

from test_helpers import (
    adhesion_inspection_payload,
    approx2,
    assert_created_at_ascending,
    assert_serial_number,
    certification_payload,
    compliance_engineer_headers,
    data_of,
    ERR_COMPONENT_SUPPLIER_NOT_QUALIFIED,
    ERR_HELD_UNITS_REMAIN,
    ERR_STALE_PARENT_VERSION,
    holiday_inspection_payload,
    plant_admin_headers,
    plant_operator_headers,
    quality_inspector_headers,
    qualify_payload,
    reason_payload,
    ship_payload,
    supplier_payload,
    supplier_quality_headers,
    validate_error,
    validate_paginated,
    validate_success,
    warranty_analyst_headers,
    fixtures as x,
)

#: The serial the first unit of the GX50-T August cohort must be given.
FIRST_SERIAL = "GX50-T-202608-00001"
#: The instant every fixture leaves the logical clock at.
SHIP_INSTANT = "2026-08-05T06:00:00"


def _a_model_with_one_open_draft_certification(api):
    """A fully tested model, one DRAFT certificate, and the pin that opened it.

    The pin returned is the version the model carried *before* the draft existed,
    which is precisely the token a second engineer would still be holding.
    """
    model_id = x.make_model(api)["id"]
    cell_id = x.make_test_cell(api)["id"]
    x.make_passing_test_suite(api, model_id, cell_id)
    stale_pin = x.model_version(api, model_id)
    draft = data_of(
        api.create_certification(
            certification_payload(model_id, stale_pin), compliance_engineer_headers()
        )
    )
    return SimpleNamespace(model_id=model_id, draft_id=draft["id"], stale_pin=stale_pin)


def _certifications_of(api, model_id):
    """Every certificate ever opened against one model."""
    rows, _meta = validate_paginated(
        api.list_certifications(
            compliance_engineer_headers(),
            {"product_model_id": model_id, "limit": 100, "offset": 0},
        )
    )
    return rows


class TestStaleModelPinOnCertificationCreate:
    """The create that bumps the model is the create that staled your token."""

    def test_01_a_create_carrying_the_pre_bump_model_version_is_refused(self, api):
        """The second engineer's pin is stale by exactly the first create's bump.

        PRD: "If that value does not equal the model's current `version` at the
        moment the request is processed, the creation is rejected with
        `ERR_STALE_PARENT_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/stale_product_model_version_on_certification_create_is_rejected
        """
        ground = _a_model_with_one_open_draft_certification(api)

        response = api.create_certification(
            certification_payload(ground.model_id, ground.stale_pin),
            compliance_engineer_headers(),
        )

        validate_error(response, ERR_STALE_PARENT_VERSION, expected_status=412)

    def test_02_the_refused_create_leaves_no_row_and_no_further_bump(self, api):
        """Exactly one certificate, and the version the accepted create left.

        PRD: "On acceptance, the model's `version` is itself incremented, so a
        client that creates two certifications back to back must re-read the model
        between them."

        Design: Corner/cross_cutting_complexity_layers/stale_product_model_version_on_certification_create_is_rejected
        """
        ground = _a_model_with_one_open_draft_certification(api)

        api.create_certification(
            certification_payload(ground.model_id, ground.stale_pin),
            compliance_engineer_headers(),
        )

        rows = _certifications_of(api, ground.model_id)
        assert len(rows) == 1
        assert rows[0]["id"] == ground.draft_id
        assert x.model_version(api, ground.model_id) == ground.stale_pin + 1

    def test_03_a_retry_with_the_freshly_read_version_is_accepted(self, api):
        """Re-reading the model is the whole remedy the pin asks for.

        PRD: "A `ComplianceEngineer` opens one against a model by naming
        `product_model_id` together with the `expected_product_model_version` pin of
        §2.7; the new certificate enters at `status` `DRAFT` with `certified_uef`,
        `certified_fhr`, `certified_recovery`, `uef_test_count`,
        `submitted_by_user_id`, `approved_by_user_id`, `effective_date`,
        `label_serial_prefix` and `reason_code` all null."

        Design: Corner/cross_cutting_complexity_layers/stale_product_model_version_on_certification_create_is_rejected
        """
        ground = _a_model_with_one_open_draft_certification(api)
        api.create_certification(
            certification_payload(ground.model_id, ground.stale_pin),
            compliance_engineer_headers(),
        )

        retried = validate_success(
            api.create_certification(
                certification_payload(
                    ground.model_id, x.model_version(api, ground.model_id)
                ),
                compliance_engineer_headers(),
            ),
            expected_status=201,
        )

        assert retried["status"] == "DRAFT"
        assert retried["submitted_by_user_id"] is None
        assert retried["certified_uef"] is None

    def test_04_the_accepted_create_supersedes_the_draft_it_never_saw(self, api):
        """The supersede side effect is exactly what the pin exists to guard.

        PRD: "Opening a certificate advances the model's own `version`, and it
        supersedes the model's earlier paperwork: any certification of the same model
        still sitting at `DRAFT` or at `REJECTED` moves to the terminal `SUPERSEDED`,
        with its `version` incremented."

        Design: Corner/cross_cutting_complexity_layers/stale_product_model_version_on_certification_create_is_rejected
        """
        ground = _a_model_with_one_open_draft_certification(api)
        data_of(
            api.create_certification(
                certification_payload(
                    ground.model_id, x.model_version(api, ground.model_id)
                ),
                compliance_engineer_headers(),
            )
        )

        superseded = validate_success(
            api.get_certification(ground.draft_id, compliance_engineer_headers())
        )
        rows = _certifications_of(api, ground.model_id)

        assert superseded["status"] == "SUPERSEDED"
        assert len(rows) == 2


def _a_lined_lot_with_one_adhesion_record(api):
    """A lined lot already carrying one CURRENT passing adhesion verdict.

    The pin returned is the lot version the adhesion filing consumed, so it is one
    behind the version any further filing must now carry.
    """
    model = x.make_certified_model(api)
    batch = x.make_fired_batch(api)
    lot_id = x.make_lined_tank_lot(api, model.model_id, batch.batch_id)
    stale_pin = x.tank_lot_version(api, lot_id)
    adhesion = data_of(
        api.create_lining_inspection(
            adhesion_inspection_payload(lot_id, stale_pin), quality_inspector_headers()
        )
    )
    return SimpleNamespace(lot_id=lot_id, adhesion_id=adhesion["id"], stale_pin=stale_pin)


class TestStaleTankLotPinOnLiningInspection:
    """An immutable record cannot be rolled back, so the pin has to stop it first."""

    def test_05_a_holiday_filing_carrying_the_pre_adhesion_version_is_refused(self, api):
        """The adhesion record moved the lot on, and the inspector never re-read it.

        PRD: "If that value does not equal the lot's current `version`, the filing is
        rejected with `ERR_STALE_PARENT_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/stale_tank_lot_version_on_lining_inspection_is_rejected
        """
        ground = _a_lined_lot_with_one_adhesion_record(api)

        response = api.create_lining_inspection(
            holiday_inspection_payload(ground.lot_id, ground.stale_pin),
            quality_inspector_headers(),
        )

        validate_error(response, ERR_STALE_PARENT_VERSION, expected_status=412)

    def test_06_the_refused_filing_writes_no_record_and_leaves_the_lot_lined(self, api):
        """One record on the lot, and no progress toward verification.

        PRD: "Accepting the inspection increments the lot's `version`, which means the
        second of two inspections filed against the same lot must carry the version the
        first one produced."

        Design: Corner/cross_cutting_complexity_layers/stale_tank_lot_version_on_lining_inspection_is_rejected
        """
        ground = _a_lined_lot_with_one_adhesion_record(api)

        api.create_lining_inspection(
            holiday_inspection_payload(ground.lot_id, ground.stale_pin),
            quality_inspector_headers(),
        )

        records = x.lot_inspections(api, ground.lot_id)
        lot = validate_success(api.get_tank_lot(ground.lot_id, quality_inspector_headers()))

        assert len(records) == 1
        assert records[0]["inspection_type"] == "ADHESION"
        assert lot["status"] == "LINED"

    def test_07_the_retry_with_the_freshly_read_version_is_accepted(self, api):
        """A holiday density of exactly 0.5000 over six tanks passes, and is current.

        PRD: "Every accepted record stores the caller's `X-User-ID` as
        `inspector_user_id` and enters at `record_status` `CURRENT`; any earlier record
        of the **same** `inspection_type` on the same lot moves to `record_status`
        `SUPERSEDED`."

        Design: Corner/cross_cutting_complexity_layers/stale_tank_lot_version_on_lining_inspection_is_rejected
        """
        ground = _a_lined_lot_with_one_adhesion_record(api)
        api.create_lining_inspection(
            holiday_inspection_payload(ground.lot_id, ground.stale_pin),
            quality_inspector_headers(),
        )

        retried = validate_success(
            api.create_lining_inspection(
                holiday_inspection_payload(
                    ground.lot_id, x.tank_lot_version(api, ground.lot_id)
                ),
                quality_inspector_headers(),
            ),
            expected_status=201,
        )

        assert retried["result"] == "PASS"
        assert retried["record_status"] == "CURRENT"

    def test_08_the_lot_verifies_only_once_both_types_hold_a_current_pass(self, api):
        """The second accepted verdict is what carries LINED to LINING_VERIFIED.

        PRD: "When the lot holds exactly one `CURRENT` `ADHESION` record with `result`
        `PASS` **and** exactly one `CURRENT` `HOLIDAY` record with `result` `PASS`, it
        moves `LINED → LINING_VERIFIED`."

        Design: Corner/cross_cutting_complexity_layers/stale_tank_lot_version_on_lining_inspection_is_rejected
        """
        ground = _a_lined_lot_with_one_adhesion_record(api)
        api.create_lining_inspection(
            holiday_inspection_payload(ground.lot_id, ground.stale_pin),
            quality_inspector_headers(),
        )
        data_of(
            api.create_lining_inspection(
                holiday_inspection_payload(
                    ground.lot_id, x.tank_lot_version(api, ground.lot_id)
                ),
                quality_inspector_headers(),
            )
        )

        lot = validate_success(api.get_tank_lot(ground.lot_id, quality_inspector_headers()))

        assert lot["status"] == "LINING_VERIFIED"

    def test_09_the_lot_history_ends_with_two_untouched_records(self, api):
        """Adhesion first, holiday second, and the adhesion row exactly as written.

        PRD: "A `LiningInspection` is an immutable measurement: once written it is
        never mutated, only superseded by a newer record of the same inspection type."

        Design: Corner/cross_cutting_complexity_layers/stale_tank_lot_version_on_lining_inspection_is_rejected
        """
        ground = _a_lined_lot_with_one_adhesion_record(api)
        api.create_lining_inspection(
            holiday_inspection_payload(ground.lot_id, ground.stale_pin),
            quality_inspector_headers(),
        )
        data_of(
            api.create_lining_inspection(
                holiday_inspection_payload(
                    ground.lot_id, x.tank_lot_version(api, ground.lot_id)
                ),
                quality_inspector_headers(),
            )
        )

        records = x.lot_inspections(api, ground.lot_id)

        assert len(records) == 2
        assert_created_at_ascending(records)
        assert [record["inspection_type"] for record in records] == ["ADHESION", "HOLIDAY"]
        assert records[0]["id"] == ground.adhesion_id
        assert records[0]["record_status"] == "CURRENT"


#: A supplier with no lots at all, so no cascade can contribute a stray increment.
NORTHLINE = dict(name="Northline Valves", audit_score=94, defect_ppm=1200, open_capa_count=0)
#: 0.40x94 + 0.35x(100-1200/50) + 0.25x100 = 37.60 + 26.60 + 25.00.
NORTHLINE_SCORE = 89.20


def _a_registered_supplier_with_no_lots(api):
    """Register Northline Valves and hand back the whole creation response."""
    return validate_success(
        api.create_supplier(supplier_payload(**NORTHLINE), supplier_quality_headers()),
        expected_status=201,
    )


def _supplier_version(api, supplier_id):
    """One single-row read, reporting only the version."""
    return validate_success(api.get_supplier(supplier_id, supplier_quality_headers()))[
        "version"
    ]


def _score(api, supplier_id):
    """One accepted scoring call at Northline's standing audit reading."""
    return validate_success(
        api.qualify_supplier(
            supplier_id,
            qualify_payload(audit_score=94, defect_ppm=1200, open_capa_count=0),
            supplier_quality_headers(),
        )
    )


class TestSupplierVersionCountsWritesAndOnlyWrites:
    """Five accepted writes, five increments, and four reads that change nothing."""

    def test_10_a_freshly_registered_supplier_starts_at_version_one(self, api):
        """Two reads later - single row and collection - it is still version 1.

        PRD: "Thirteen of the fourteen resource types are mutable and additionally
        carry `updated_at` — an ISO 8601 UTC timestamp with three fractional digits,
        refreshed on every accepted mutation of that row — and `version`, an integer
        that starts at 1 when the row is created and increments by exactly 1 on every
        accepted mutation."

        Design: Corner/cross_cutting_complexity_layers/version_increments_on_every_write_and_never_on_a_read
        """
        created = _a_registered_supplier_with_no_lots(api)

        single = validate_success(
            api.get_supplier(created["id"], supplier_quality_headers())
        )
        rows, _meta = validate_paginated(
            api.list_suppliers(supplier_quality_headers(), {"limit": 100, "offset": 0})
        )

        assert created["version"] == 1
        assert created["qualification_status"] == "PENDING"
        assert created["qualification_score"] is None
        assert single["version"] == 1
        assert [row["version"] for row in rows] == [1]

    def test_11_the_first_scoring_call_advances_the_version_by_exactly_one(self, api):
        """Version 2, and the read that follows it is still version 2.

        PRD: "Whichever branch is taken, the accepted call writes
        `qualification_score` and `qualified_until`, clears
        `disqualification_reason_code`, and increments the supplier's `version` by 1."

        Design: Corner/cross_cutting_complexity_layers/version_increments_on_every_write_and_never_on_a_read
        """
        supplier_id = _a_registered_supplier_with_no_lots(api)["id"]

        qualified = _score(api, supplier_id)

        assert qualified["version"] == 2
        assert qualified["qualification_status"] == "QUALIFIED"
        assert _supplier_version(api, supplier_id) == 2

    def test_12_the_disqualification_advances_it_again_and_clears_the_expiry(self, api):
        """Version 3, with nothing left to expire and no lot to contain.

        PRD: "A `SupplierQualityManager` disqualifies a supplier that is currently
        `QUALIFIED` or `CONDITIONAL`, supplying a `reason_code`; the supplier moves to
        `DISQUALIFIED`, that `reason_code` is stored as `disqualification_reason_code`,
        and `qualified_until` is cleared."

        Design: Corner/cross_cutting_complexity_layers/version_increments_on_every_write_and_never_on_a_read
        """
        supplier_id = _a_registered_supplier_with_no_lots(api)["id"]
        _score(api, supplier_id)

        disqualified = validate_success(
            api.disqualify_supplier(
                supplier_id,
                reason_payload("AUDIT_FAILURE"),
                supplier_quality_headers(),
            )
        )

        assert disqualified["version"] == 3
        assert disqualified["qualification_status"] == "DISQUALIFIED"
        assert disqualified["qualified_until"] is None
        assert disqualified["blocked_lot_count"] == 0

    def test_13_the_requalification_advances_it_and_drops_the_score(self, api):
        """Version 4, back at PENDING with no score to its name.

        PRD: "Requalifying a `DISQUALIFIED` supplier — a `SupplierQualityManager`
        action carrying a `reason_code` — moves it `DISQUALIFIED → PENDING`, clears both
        `disqualification_reason_code` and `qualification_score`, and increments
        `version`; it unblocks nothing by itself."

        Design: Corner/cross_cutting_complexity_layers/version_increments_on_every_write_and_never_on_a_read
        """
        supplier_id = _a_registered_supplier_with_no_lots(api)["id"]
        _score(api, supplier_id)
        data_of(
            api.disqualify_supplier(
                supplier_id, reason_payload("AUDIT_FAILURE"), supplier_quality_headers()
            )
        )

        requalified = validate_success(
            api.requalify_supplier(
                supplier_id, supplier_quality_headers(), reason_payload("CAPA_CLOSED")
            )
        )

        assert requalified["version"] == 4
        assert requalified["qualification_status"] == "PENDING"
        assert requalified["qualification_score"] is None
        assert requalified["disqualification_reason_code"] is None

    def test_14_the_second_scoring_call_lands_on_version_five_with_a_fresh_score(self, api):
        """The same three inputs score the same way, and the reads added nothing.

        PRD: "The three components are then combined with weights of 0.40 for the
        audit component, 0.35 for the parts-per-million component and 0.25 for the
        corrective-action component, and the weighted sum is rounded half up to two
        decimal places to become `qualification_score`."

        Design: Corner/cross_cutting_complexity_layers/version_increments_on_every_write_and_never_on_a_read
        """
        supplier_id = _a_registered_supplier_with_no_lots(api)["id"]
        _score(api, supplier_id)
        _supplier_version(api, supplier_id)
        data_of(
            api.disqualify_supplier(
                supplier_id, reason_payload("AUDIT_FAILURE"), supplier_quality_headers()
            )
        )
        data_of(
            api.requalify_supplier(
                supplier_id, supplier_quality_headers(), reason_payload("CAPA_CLOSED")
            )
        )

        rescored = _score(api, supplier_id)

        assert rescored["version"] == 5
        assert rescored["qualification_status"] == "QUALIFIED"
        assert rescored["qualification_score"] == approx2(NORTHLINE_SCORE)
        assert _supplier_version(api, supplier_id) == 5


def _a_restricted_model_with_two_held_units(api):
    """One assembled unit and one still-staged unit, both caught by one disqualification.

    Both units draw the same gas-control lot, so disqualifying that lot's supplier
    blocks the lot, holds both units and restricts the model in a single request.
    """
    plant = x.make_full_plant(api)
    assembled = x.assemble_unit(api, plant)
    staged = x.stage_unit(api, plant)
    data_of(
        api.disqualify_supplier(
            plant.gas_supplier_id,
            reason_payload("AUDIT_FAILURE"),
            supplier_quality_headers(),
        )
    )
    return SimpleNamespace(plant=plant, assembled=assembled, staged=staged)


def _the_model(api, ground):
    """One catalogue read of the model the two units belong to."""
    return validate_success(
        api.get_product_model(ground.plant.model_id, compliance_engineer_headers())
    )


def _the_supplier_is_recovered_and_the_lot_unblocked(api, ground):
    """Run the declared recovery order: requalify first, then disposition the lot."""
    requalified = validate_success(
        api.requalify_supplier(
            ground.plant.gas_supplier_id,
            supplier_quality_headers(),
            reason_payload("CAPA_CLOSED"),
        )
    )
    unblocked = validate_success(
        api.unblock_component_lot(ground.plant.gas_lot_id, supplier_quality_headers())
    )
    return requalified, unblocked


class TestHeldUnitCountReconcilesAcrossReleaseAndScrap:
    """A derived counter, two ways down to zero, and no automatic recovery."""

    def test_15_the_disqualification_counts_both_held_units_on_the_model(self, api):
        """Two units held, the model restricted, and its certification untouched.

        PRD: "`held_unit_count` is derived: it is the number of heater units of this
        model whose `build_status` is `HELD`."

        Design: Corner/cross_cutting_complexity_layers/held_unit_count_reconciles_across_hold_release_and_scrap
        """
        ground = _a_restricted_model_with_two_held_units(api)

        model = _the_model(api, ground)

        assert model["held_unit_count"] == 2
        assert model["release_status"] == "RESTRICTED"
        assert model["certification_status"] == "CERTIFIED"

    def test_16_a_hold_release_is_refused_while_the_component_lot_is_blocked(self, api):
        """The assembled branch re-examines every lot the unit drew from.

        PRD: "When `held_from_status` is `ASSEMBLED` the unit returns `HELD →
        ASSEMBLED`, and every referenced component lot must be back in `status`
        `RELEASED`, failing with `ERR_COMPONENT_SUPPLIER_NOT_QUALIFIED`, while the
        model's `certification_status` must not be `DECERTIFIED`, failing with
        `ERR_MODEL_NOT_CERTIFIED`."

        Design: Corner/cross_cutting_complexity_layers/held_unit_count_reconciles_across_hold_release_and_scrap
        """
        ground = _a_restricted_model_with_two_held_units(api)

        response = api.release_unit_hold(ground.assembled, plant_operator_headers())

        validate_error(
            response, ERR_COMPONENT_SUPPLIER_NOT_QUALIFIED, expected_status=409
        )

    def test_17_requalifying_first_is_what_makes_the_lot_dispositionable(self, api):
        """The blocked count falls only when the lot itself is unblocked.

        PRD: "The other disposition is unblocking, which a `SupplierQualityManager`
        performs on a lot whose `status` is `BLOCKED`, returning it `BLOCKED →
        RELEASED`, clearing `reject_reason_code` and triggering the same
        `blocked_lot_count` recomputation."

        Design: Corner/cross_cutting_complexity_layers/held_unit_count_reconciles_across_hold_release_and_scrap
        """
        ground = _a_restricted_model_with_two_held_units(api)

        requalified, unblocked = _the_supplier_is_recovered_and_the_lot_unblocked(
            api, ground
        )

        assert requalified["qualification_status"] == "PENDING"
        assert requalified["blocked_lot_count"] == 1
        assert unblocked["status"] == "RELEASED"
        assert unblocked["reject_reason_code"] is None
        supplier = validate_success(
            api.get_supplier(ground.plant.gas_supplier_id, supplier_quality_headers())
        )
        assert supplier["blocked_lot_count"] == 0

    def test_18_the_hold_release_then_restores_the_status_it_was_held_from(self, api):
        """Back to ASSEMBLED, with both hold fields cleared and the count recomputed.

        PRD: "All three branches clear `hold_reason_code`, clear `held_from_status`,
        have the owning product model recompute `held_unit_count`, and increment
        `version` on both the unit and the model."

        Design: Corner/cross_cutting_complexity_layers/held_unit_count_reconciles_across_hold_release_and_scrap
        """
        ground = _a_restricted_model_with_two_held_units(api)
        _the_supplier_is_recovered_and_the_lot_unblocked(api, ground)

        released = validate_success(
            api.release_unit_hold(ground.assembled, plant_operator_headers())
        )

        assert released["build_status"] == "ASSEMBLED"
        assert released["hold_reason_code"] is None
        assert released["held_from_status"] is None
        assert _the_model(api, ground)["held_unit_count"] == 1

    def test_19_the_restriction_cannot_be_lifted_while_one_unit_is_still_held(self, api):
        """The staged unit is still contained, so the model stays restricted.

        PRD: "A model with units still held reports `ERR_HELD_UNITS_REMAIN`; a model
        that is not `RESTRICTED` at all reports `ERR_INVALID_MODEL_STATE`."

        Design: Corner/cross_cutting_complexity_layers/held_unit_count_reconciles_across_hold_release_and_scrap
        """
        ground = _a_restricted_model_with_two_held_units(api)
        _the_supplier_is_recovered_and_the_lot_unblocked(api, ground)
        data_of(api.release_unit_hold(ground.assembled, plant_operator_headers()))

        response = api.lift_model_restriction(ground.plant.model_id, plant_admin_headers())

        validate_error(response, ERR_HELD_UNITS_REMAIN, expected_status=409)

    def test_20_scrapping_the_last_held_unit_zeroes_the_count_but_not_the_restriction(
        self, api
    ):
        """Zero held units is not itself a return to the catalogue.

        PRD: "When the disassembled unit was `HELD`, the owning model recomputes
        `held_unit_count`, and even when that count falls to 0 the model remains
        `RESTRICTED` until an administrator explicitly lifts the restriction."

        Design: Corner/cross_cutting_complexity_layers/held_unit_count_reconciles_across_hold_release_and_scrap
        """
        ground = _a_restricted_model_with_two_held_units(api)
        _the_supplier_is_recovered_and_the_lot_unblocked(api, ground)
        data_of(api.release_unit_hold(ground.assembled, plant_operator_headers()))

        scrapped = validate_success(
            api.disassemble_unit(
                ground.staged,
                reason_payload("COMPONENT_CONTAINMENT"),
                plant_operator_headers(),
            )
        )

        model = _the_model(api, ground)
        assert scrapped["build_status"] == "SCRAPPED"
        assert model["held_unit_count"] == 0
        assert model["release_status"] == "RESTRICTED"

    def test_21_the_administrative_lift_returns_the_model_to_released(self, api):
        """With the count at zero the deliberate act is finally accepted.

        PRD: "Returning from restriction is a deliberate administrative act rather
        than an automatic recovery: a `PlantAdmin` lifts the restriction, moving the
        model `RESTRICTED → RELEASED`, and the call requires `held_unit_count` to be
        exactly 0."

        Design: Corner/cross_cutting_complexity_layers/held_unit_count_reconciles_across_hold_release_and_scrap
        """
        ground = _a_restricted_model_with_two_held_units(api)
        _the_supplier_is_recovered_and_the_lot_unblocked(api, ground)
        data_of(api.release_unit_hold(ground.assembled, plant_operator_headers()))
        data_of(
            api.disassemble_unit(
                ground.staged,
                reason_payload("COMPONENT_CONTAINMENT"),
                plant_operator_headers(),
            )
        )

        lifted = validate_success(
            api.lift_model_restriction(ground.plant.model_id, plant_admin_headers())
        )

        assert lifted["release_status"] == "RELEASED"
        assert lifted["held_unit_count"] == 0


def _a_plant_with_one_assembled_unit(api):
    """A certified, released model whose first unit is assembled and awaiting its label."""
    plant = x.make_full_plant(api)
    return plant, x.assemble_unit(api, plant)


def _the_unit(api, unit_id):
    """One unit read, as any client would make it after the write."""
    return validate_success(api.get_heater_unit(unit_id, plant_operator_headers()))


def _the_august_cohort(api, model_id):
    """The field-failure report for the August production period."""
    return validate_success(
        api.get_warranty_analysis(
            model_id, warranty_analyst_headers(), {"production_period": "2026-08"}
        )
    )


class TestEveryDerivedFieldIsVisibleInTheWritingResponse:
    """Nothing here settles later: the write response is already the whole truth."""

    def test_22_the_label_response_already_carries_its_minted_serial(self, api):
        """No null waiting to be filled in by a re-read.

        PRD: "The unit then moves `ASSEMBLED → LABELED` with `label_status` set to
        `APPLIED` and a freshly minted `serial_number`."

        Design: Corner/consistency_model/every_derived_field_is_visible_in_the_writing_response_itself
        """
        _plant, unit_id = _a_plant_with_one_assembled_unit(api)

        labelled = validate_success(api.label_unit(unit_id, plant_operator_headers()))

        assert labelled["build_status"] == "LABELED"
        assert labelled["label_status"] == "APPLIED"
        assert labelled["serial_number"] == FIRST_SERIAL
        assert _the_unit(api, unit_id)["serial_number"] == FIRST_SERIAL

    def test_23_the_sequence_number_is_computed_before_the_response_is_sent(self, api):
        """First unit of this model and month, so the write already knows it is 00001.

        PRD: "The third is a sequence number, left-padded with zeros to a width of
        five digits, whose value is one more than the count of units that share this
        unit's `product_model_id` **and** its `production_period` **and** already hold a
        non-null `serial_number`."

        Design: Corner/consistency_model/every_derived_field_is_visible_in_the_writing_response_itself
        """
        _plant, unit_id = _a_plant_with_one_assembled_unit(api)

        labelled = validate_success(api.label_unit(unit_id, plant_operator_headers()))

        assert_serial_number(labelled, "GX50-T", "2026-08", 1)
        assert labelled["production_period"] == "2026-08"

    def test_24_the_ship_response_already_carries_the_water_chemistry_pair(self, api):
        """Twelve grains per gallon is banded and weighted inside the same call.

        PRD: "The band is stored as `water_hardness_band` and its exposure multiplier
        as `hardness_factor`: 0.80 for `SOFT`, 1.00 for `MODERATE`, 1.35 for `HARD` and
        1.80 for `VERY_HARD`."

        Design: Corner/consistency_model/every_derived_field_is_visible_in_the_writing_response_itself
        """
        _plant, unit_id = _a_plant_with_one_assembled_unit(api)
        data_of(api.label_unit(unit_id, plant_operator_headers()))

        shipped = validate_success(
            api.ship_unit(
                unit_id,
                ship_payload(install_water_hardness_gpg=12.0),
                plant_operator_headers(),
            )
        )

        assert shipped["water_hardness_band"] == "VERY_HARD"
        assert shipped["hardness_factor"] == approx2(1.80)
        assert shipped["build_status"] == "SHIPPED"

    def test_25_the_read_after_the_ship_repeats_every_derived_field(self, api):
        """The shipment stamp and the pair it derived survive the round trip.

        PRD: "Shipment records `shipped_at` as the logical-clock instant, stores
        `install_water_hardness_gpg`, and derives the water-chemistry pair that all
        later reliability analysis leans on."

        Design: Corner/consistency_model/every_derived_field_is_visible_in_the_writing_response_itself
        """
        _plant, unit_id = _a_plant_with_one_assembled_unit(api)
        data_of(api.label_unit(unit_id, plant_operator_headers()))
        shipped = validate_success(
            api.ship_unit(
                unit_id,
                ship_payload(install_water_hardness_gpg=12.0),
                plant_operator_headers(),
            )
        )

        reread = _the_unit(api, unit_id)

        assert shipped["shipped_at"].startswith(SHIP_INSTANT)
        assert reread["shipped_at"].startswith(SHIP_INSTANT)
        assert reread["build_status"] == "SHIPPED"
        assert reread["water_hardness_band"] == "VERY_HARD"
        assert reread["hardness_factor"] == approx2(1.80)
        assert reread["install_water_hardness_gpg"] == approx2(12.0)

    def test_26_the_reserve_accrual_is_on_the_model_the_moment_the_unit_ships(self, api):
        """A gas model accrues 42,000 cents, and nothing has been paid out yet.

        PRD: "On each shipment the unit's product model adds a fixed per-unit accrual
        to both `warranty_reserve_accrued_cents` and `warranty_reserve_balance_cents`,
        keyed on the model's `fuel_type`: 42,000 cents — that is, 420 dollars — for a
        `GAS` model, 31,000 cents for an `ELECTRIC` model, and 98,000 cents for a
        `HEAT_PUMP` model."

        Design: Corner/consistency_model/every_derived_field_is_visible_in_the_writing_response_itself
        """
        plant, unit_id = _a_plant_with_one_assembled_unit(api)
        data_of(api.label_unit(unit_id, plant_operator_headers()))
        data_of(
            api.ship_unit(
                unit_id,
                ship_payload(install_water_hardness_gpg=12.0),
                plant_operator_headers(),
            )
        )

        model = validate_success(
            api.get_product_model(plant.model_id, compliance_engineer_headers())
        )

        assert model["warranty_reserve_accrued_cents"] == 42000
        assert model["warranty_reserve_balance_cents"] == 42000
        assert model["warranty_paid_cents"] == 0

    def test_27_the_cohort_report_already_counts_the_unit_it_just_shipped(self, api):
        """One shipped unit of this model and month is one unit of cohort.

        PRD: "The cohort is the set of units of that model whose `build_status` is
        `SHIPPED` and whose `production_period` matches, enumerated in `created_at`
        ascending order."

        Design: Corner/consistency_model/every_derived_field_is_visible_in_the_writing_response_itself
        """
        plant, unit_id = _a_plant_with_one_assembled_unit(api)
        data_of(api.label_unit(unit_id, plant_operator_headers()))
        data_of(
            api.ship_unit(
                unit_id,
                ship_payload(install_water_hardness_gpg=12.0),
                plant_operator_headers(),
            )
        )

        report = _the_august_cohort(api, plant.model_id)

        assert report["production_period"] == "2026-08"
        assert report["shipped_unit_count"] == 1
        assert report["tank_leak_claim_count"] == 0

    def test_28_the_exposure_measure_is_zero_while_no_month_has_elapsed(self, api):
        """A very-hard multiplier applied to zero months in service is still zero.

        PRD: "`weighted_exposure_unit_months` is the sum, across the cohort, of each
        unit's `months_in_service` multiplied by its `hardness_factor`, rounded to two
        decimal places half up, and it is the exposure measure that makes a soft-water
        unit count for less than a very-hard-water unit of the same age."

        Design: Corner/consistency_model/every_derived_field_is_visible_in_the_writing_response_itself
        """
        plant, unit_id = _a_plant_with_one_assembled_unit(api)
        data_of(api.label_unit(unit_id, plant_operator_headers()))
        data_of(
            api.ship_unit(
                unit_id,
                ship_payload(install_water_hardness_gpg=12.0),
                plant_operator_headers(),
            )
        )

        report = _the_august_cohort(api, plant.model_id)

        assert report["weighted_exposure_unit_months"] == approx2(0.00)
        assert _the_unit(api, unit_id)["months_in_service"] == 0

    def test_29_the_water_chemistry_profile_sums_to_the_cohort(self, api):
        """The one unit sits in exactly one band, and the four counts add up.

        PRD: "The report closes with the cohort's water-chemistry profile:
        `soft_unit_count`, `moderate_unit_count`, `hard_unit_count` and
        `very_hard_unit_count`, which are the counts of cohort units in each
        `water_hardness_band` and which always sum to `shipped_unit_count`."

        Design: Corner/consistency_model/every_derived_field_is_visible_in_the_writing_response_itself
        """
        plant, unit_id = _a_plant_with_one_assembled_unit(api)
        data_of(api.label_unit(unit_id, plant_operator_headers()))
        data_of(
            api.ship_unit(
                unit_id,
                ship_payload(install_water_hardness_gpg=12.0),
                plant_operator_headers(),
            )
        )

        report = _the_august_cohort(api, plant.model_id)

        assert report["very_hard_unit_count"] == 1
        assert report["soft_unit_count"] == 0
        assert report["moderate_unit_count"] == 0
        assert report["hard_unit_count"] == 0
        bands = (
            report["soft_unit_count"]
            + report["moderate_unit_count"]
            + report["hard_unit_count"]
            + report["very_hard_unit_count"]
        )
        assert bands == report["shipped_unit_count"]
