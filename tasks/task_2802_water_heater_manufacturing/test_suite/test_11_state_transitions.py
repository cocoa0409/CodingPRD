"""Declared entry states, refused replays and the ordering of recovery steps.

Every transition here is checked twice over: once for the state the service
reports afterwards, and once for the fields and counters a refused call must
have left exactly where it found them.
"""

from test_helpers import (
    adhesion_inspection_payload,
    approx2,
    approx4,
    assert_tank_lot_ledger,
    assert_version_unchanged,
    compliance_engineer_headers,
    component_lot_payload,
    data_of,
    ERR_BLOCKED_LOTS_REMAIN,
    ERR_COMPONENT_SUPPLIER_NOT_QUALIFIED,
    ERR_FIRING_WINDOW_NOT_ELAPSED,
    ERR_INVALID_BATCH_STATE,
    ERR_INVALID_TANK_LOT_STATE,
    foam_payload,
    furnace_payload,
    holiday_inspection_payload,
    lining_batch_payload,
    lot_inspections,
    make_fired_batch,
    make_model,
    make_qualified_supplier,
    plant_admin_headers,
    plant_operator_headers,
    private_label_payload,
    product_model_payload,
    qualify_payload,
    quality_inspector_headers,
    reason_payload,
    recall_campaign_payload,
    supplier_payload,
    supplier_quality_headers,
    tank_lot_payload,
    tank_lot_version,
    USER_WELD_OPERATOR,
    validate_error,
    validate_success,
    warranty_analyst_headers,
    weld_operator_headers,
    fixtures as x,
)


def _one_of_every_freshly_created_entity(api):
    """A model, a supplier, a lot, a furnace, a batch, a tank lot and a campaign.

    Nothing here is advanced past creation: the firing window has not elapsed, the
    incoming lot has not been inspected, and the campaign has not been scoped.
    """
    model = data_of(
        api.create_product_model(product_model_payload(), compliance_engineer_headers())
    )
    supplier = data_of(
        api.create_supplier(supplier_payload(), supplier_quality_headers())
    )
    component_lot = data_of(
        api.create_component_lot(
            component_lot_payload(supplier["id"]), supplier_quality_headers()
        )
    )
    furnace = data_of(api.create_furnace(furnace_payload(), plant_admin_headers()))
    batch = data_of(
        api.create_lining_batch(
            lining_batch_payload(furnace["id"]), plant_operator_headers()
        )
    )
    tank_lot = data_of(
        api.create_tank_lot(tank_lot_payload(model["id"]), plant_operator_headers())
    )
    campaign = data_of(
        api.create_recall_campaign(
            recall_campaign_payload(model["id"]), warranty_analyst_headers()
        )
    )
    return model, supplier, component_lot, batch, tank_lot, campaign


class TestDeclaredInitialStates:
    """Seven entity types, each read back at the state its creation declares."""

    def test_01_production_rows_enter_with_empty_counters(self, api):
        """A batch enters MIXED with nothing assigned, a lot FAB_QUEUED all in process.

        PRD: "Every new batch starts at `status` `MIXED`, with `rejected_lot_count` at
        0, no `quarantine_reason_code`, and an `assigned_lot_count` derived as the number
        of tank lots whose `glass_lining_batch_id` names this batch."

        Design: Corner/state_machines/newly_created_entities_start_in_declared_initial_state
        """
        _model, _supplier, _lot, batch, tank_lot, _campaign = _one_of_every_freshly_created_entity(api)

        stored_batch = validate_success(
            api.get_lining_batch(batch["id"], plant_operator_headers())
        )
        stored_lot = validate_success(
            api.get_tank_lot(tank_lot["id"], plant_operator_headers())
        )

        assert stored_batch["status"] == "MIXED"
        assert stored_batch["rejected_lot_count"] == 0
        assert stored_batch["assigned_lot_count"] == 0
        assert stored_batch["quarantine_reason_code"] is None
        assert stored_lot["status"] == "FAB_QUEUED"
        assert stored_lot["wip_quantity"] == 120
        assert stored_lot["good_quantity"] == 0
        assert stored_lot["scrapped_quantity"] == 0
        assert stored_lot["glass_lining_batch_id"] is None
        assert stored_lot["rework_count"] == 0
        assert stored_lot["cascade_rejected"] is False

    def test_02_the_supply_catalogue_and_recall_rows_enter_at_their_own_floors(self, api):
        """A model starts on both dimensions at once, and a campaign at zero cost.

        PRD: "The campaign opens in `status` `DRAFT` with `serial_range_start`,
        `serial_range_end`, `affected_unit_count`, `per_unit_remedy_cost_cents`,
        `estimated_remedy_cost_cents` and `reason_code` all unset, and with `notice_count`,
        `remedied_count`, `completion_pct_notice_based` and `completion_pct_population_based`
        at their empty-campaign values of zero."

        Design: Corner/state_machines/newly_created_entities_start_in_declared_initial_state
        """
        model, supplier, lot, _batch, _tank_lot, campaign = _one_of_every_freshly_created_entity(api)

        stored_campaign = validate_success(
            api.get_recall_campaign(campaign["id"], warranty_analyst_headers())
        )

        assert stored_campaign["status"] == "DRAFT"
        assert stored_campaign["affected_unit_count"] is None
        assert stored_campaign["per_unit_remedy_cost_cents"] is None
        assert stored_campaign["serial_range_start"] is None
        assert stored_campaign["notice_count"] == 0
        assert stored_campaign["remedied_count"] == 0
        assert model["certification_status"] == "UNCERTIFIED"
        assert model["release_status"] == "DRAFT"
        assert supplier["qualification_status"] == "PENDING"
        assert lot["status"] == "QUARANTINED"


def _a_booked_batch_whose_window_has_not_elapsed(api):
    """A batch occupying 06:00-10:00 on 2 August, read at the initial clock."""
    furnace = data_of(api.create_furnace(furnace_payload(), plant_admin_headers()))
    batch = data_of(
        api.create_lining_batch(
            lining_batch_payload(furnace["id"]), plant_operator_headers()
        )
    )
    return furnace["id"], batch["id"]


class TestBatchFiringWindowElapse:
    """Firing is a clock-gated transition, and the gate is inclusive."""

    def test_03_firing_is_refused_until_the_clock_reaches_the_window_end(self, api):
        """One minute early is early; the instant of the end is enough.

        PRD: "Marking the firing cycle complete is a `PlantOperator` action that moves
        the batch `MIXED → FIRED`, and it is refused before the logical clock reaches the
        batch's own `firing_end` with `ERR_FIRING_WINDOW_NOT_ELAPSED`; the clock exactly at
        `firing_end` is sufficient."

        Design: Corner/state_machines/batch_fire_before_firing_end_rejected
        """
        _furnace_id, batch_id = _a_booked_batch_whose_window_has_not_elapsed(api)

        at_the_initial_clock = api.fire_lining_batch(batch_id, plant_operator_headers())
        x.set_clock(api, "2026-08-02T09:59:00Z")
        one_minute_early = api.fire_lining_batch(batch_id, plant_operator_headers())
        x.set_clock(api, "2026-08-02T10:00:00Z")
        exactly_at_the_end = validate_success(
            api.fire_lining_batch(batch_id, plant_operator_headers())
        )

        validate_error(
            at_the_initial_clock, ERR_FIRING_WINDOW_NOT_ELAPSED, expected_status=409
        )
        validate_error(
            one_minute_early, ERR_FIRING_WINDOW_NOT_ELAPSED, expected_status=409
        )
        assert exactly_at_the_end["status"] == "FIRED"

    def test_04_the_two_early_attempts_left_no_trace_on_the_batch(self, api):
        """Only the accepted fire wrote, so the version advanced exactly once.

        PRD: "Marking the firing cycle complete is a `PlantOperator` action that moves
        the batch `MIXED → FIRED`, and it is refused before the logical clock reaches the
        batch's own `firing_end` with `ERR_FIRING_WINDOW_NOT_ELAPSED`; the clock exactly at
        `firing_end` is sufficient."

        Design: Corner/state_machines/batch_fire_before_firing_end_rejected
        """
        _furnace_id, batch_id = _a_booked_batch_whose_window_has_not_elapsed(api)

        api.fire_lining_batch(batch_id, plant_operator_headers())
        x.set_clock(api, "2026-08-02T09:59:00Z")
        api.fire_lining_batch(batch_id, plant_operator_headers())
        x.set_clock(api, "2026-08-02T10:00:00Z")
        fired = validate_success(api.fire_lining_batch(batch_id, plant_operator_headers()))

        assert fired["version"] == 2

    def test_05_firing_an_already_fired_batch_is_an_invalid_state_not_a_no_op(self, api):
        """The replay is refused and the batch is left untouched, version included.

        PRD: "Firing a batch that is not `MIXED` — an already-`FIRED` batch, for
        instance — reports `ERR_INVALID_BATCH_STATE`."

        Design: Corner/state_machines/batch_fire_twice_returns_invalid_batch_state
        """
        batch = make_fired_batch(api)
        first_read = validate_success(
            api.get_lining_batch(batch.batch_id, plant_operator_headers())
        )

        replay = api.fire_lining_batch(batch.batch_id, plant_operator_headers())

        validate_error(replay, ERR_INVALID_BATCH_STATE, expected_status=409)
        after = validate_success(
            api.get_lining_batch(batch.batch_id, plant_operator_headers())
        )
        assert after["status"] == "FIRED"
        assert after["quarantine_reason_code"] is None
        assert after["version"] == 2
        assert_version_unchanged(first_read, after)

    def test_06_the_furnace_still_counts_the_fired_window_once(self, api):
        """A FIRED batch is still an occupation, and the replay did not double it.

        PRD: "A furnace read reports `occupied_window_count`, derived as the number of
        glass-lining batches booked on that furnace whose `status` is `MIXED` or `FIRED`."

        Design: Corner/state_machines/batch_fire_twice_returns_invalid_batch_state
        """
        batch = make_fired_batch(api)

        api.fire_lining_batch(batch.batch_id, plant_operator_headers())
        furnace = validate_success(
            api.get_furnace(batch.furnace_id, plant_admin_headers())
        )

        assert furnace["occupied_window_count"] == 1


def _a_fab_queued_lot_and_a_fired_batch(api):
    """A brand-new tank lot alongside a batch that is ready to be applied."""
    model_id = make_model(api)["id"]
    batch = make_fired_batch(api)
    lot = data_of(
        api.create_tank_lot(tank_lot_payload(model_id), plant_operator_headers())
    )
    return lot["id"], batch.batch_id


class TestTankLotStageOrdering:
    """A fabrication stage can only be reached from the stage before it."""

    def test_07_only_welding_is_reachable_from_the_fabrication_queue(self, api):
        """Lining, foaming and jacketing are all refused; welding is accepted.

        PRD: "Welding takes the lot `FAB_QUEUED → WELDED` and pins accountability:
        the caller's `X-User-ID` is stored as `weld_operator_user_id`, which the later
        inspection separation rule reads."

        Design: Corner/state_machines/apply_lining_from_fab_queued_rejected
        """
        lot_id, batch_id = _a_fab_queued_lot_and_a_fired_batch(api)

        lining = api.apply_lining(
            lot_id, {"glass_lining_batch_id": batch_id}, plant_operator_headers()
        )
        foam = api.foam_tank_lot(lot_id, foam_payload(), plant_operator_headers())
        jacket = api.jacket_tank_lot(lot_id, plant_operator_headers())
        welded = validate_success(api.weld_tank_lot(lot_id, weld_operator_headers()))

        validate_error(lining, ERR_INVALID_TANK_LOT_STATE, expected_status=409)
        validate_error(foam, ERR_INVALID_TANK_LOT_STATE, expected_status=409)
        validate_error(jacket, ERR_INVALID_TANK_LOT_STATE, expected_status=409)
        assert welded["status"] == "WELDED"
        assert welded["weld_operator_user_id"] == USER_WELD_OPERATOR

    def test_08_the_three_refused_stages_wrote_none_of_their_fields(self, api):
        """No batch was attached and no insulation figures were derived.

        PRD: "A new lot begins at `status` `FAB_QUEUED` with `rework_count` 0,
        `cascade_rejected` false, and `glass_lining_batch_id`, `weld_operator_user_id`,
        `last_scrap_quantity`, `foam_density_kg_m3`, `foam_thickness_mm` and
        `achieved_r_value` all null."

        Design: Corner/state_machines/apply_lining_from_fab_queued_rejected
        """
        lot_id, batch_id = _a_fab_queued_lot_and_a_fired_batch(api)

        api.apply_lining(
            lot_id, {"glass_lining_batch_id": batch_id}, plant_operator_headers()
        )
        api.foam_tank_lot(lot_id, foam_payload(), plant_operator_headers())
        api.jacket_tank_lot(lot_id, plant_operator_headers())
        data_of(api.weld_tank_lot(lot_id, weld_operator_headers()))

        lot = validate_success(api.get_tank_lot(lot_id, plant_operator_headers()))
        batch = validate_success(api.get_lining_batch(batch_id, plant_operator_headers()))

        assert lot["glass_lining_batch_id"] is None
        assert lot["foam_density_kg_m3"] is None
        assert lot["foam_thickness_mm"] is None
        assert lot["achieved_r_value"] is None
        assert batch["assigned_lot_count"] == 0


def _a_released_lot(api):
    """A lot carried through the whole route to the terminal RELEASED state."""
    model_id = make_model(api)["id"]
    batch = make_fired_batch(api)
    lot_id = x.make_released_tank_lot(api, model_id, batch.batch_id)
    return lot_id, batch.batch_id


class TestReleasedTankLotIsTerminal:
    """Nothing is reachable from RELEASED, in either direction."""

    def test_09_every_further_transition_on_a_released_lot_is_refused(self, api):
        """Re-release, scrap, re-lining and reline authorisation all fail the same way.

        PRD: "Release requires at least one tank still in process, and both actions
        report `ERR_INVALID_TANK_LOT_STATE` when the lot is not in the state they expect —
        releasing an unjacketed lot, for instance."

        Design: Corner/state_machines/released_tank_lot_is_terminal_and_locked
        """
        lot_id, batch_id = _a_released_lot(api)

        again = api.release_tank_lot(lot_id, plant_operator_headers())
        scrapped = api.scrap_tank_lot(
            lot_id, quality_inspector_headers(), reason_payload(reason_code="LATE_DEFECT")
        )
        relined = api.apply_lining(
            lot_id, {"glass_lining_batch_id": batch_id}, plant_operator_headers()
        )
        authorised = api.authorize_reline(lot_id, plant_operator_headers())

        for response in (again, scrapped, relined, authorised):
            validate_error(response, ERR_INVALID_TANK_LOT_STATE, expected_status=409)
        lot = validate_success(api.get_tank_lot(lot_id, plant_operator_headers()))
        assert lot["status"] == "RELEASED"

    def test_10_the_settled_ledger_survives_the_four_refusals(self, api):
        """Every planned tank is still a good tank, and the batch still owns the lot.

        PRD: "Jacket assembly then moves the lot `FOAMED → JACKETED`, and lot release
        moves it `JACKETED → RELEASED`, which is where the quantity ledger settles:
        `good_quantity` takes the value of `wip_quantity` and `wip_quantity` becomes 0,
        leaving the planned total still exactly split across the three counters."

        Design: Corner/state_machines/released_tank_lot_is_terminal_and_locked
        """
        lot_id, batch_id = _a_released_lot(api)

        api.release_tank_lot(lot_id, plant_operator_headers())
        api.scrap_tank_lot(
            lot_id, quality_inspector_headers(), reason_payload(reason_code="LATE_DEFECT")
        )
        api.authorize_reline(lot_id, plant_operator_headers())

        lot = validate_success(api.get_tank_lot(lot_id, plant_operator_headers()))
        batch = validate_success(api.get_lining_batch(batch_id, plant_operator_headers()))

        assert lot["good_quantity"] == 120
        assert lot["wip_quantity"] == 0
        assert lot["scrapped_quantity"] == 0
        assert lot["rework_count"] == 0
        assert_tank_lot_ledger(lot)
        assert batch["assigned_lot_count"] == 1
        assert batch["rejected_lot_count"] == 0


def _a_lined_lot_awaiting_both_verdicts(api):
    """A LINED lot with no inspection records against it yet."""
    model_id = make_model(api)["id"]
    batch = make_fired_batch(api)
    return x.make_lined_tank_lot(api, model_id, batch.batch_id)


class TestLiningVerificationNeedsBothCurrentPasses:
    """One passing record is never enough, because the two types are independent."""

    def test_11_a_passing_adhesion_record_alone_leaves_the_lot_lined(self, api):
        """Class 2 is the worst passing class, and it carries no holiday density.

        PRD: "For an `ADHESION` record `holidays_per_tank` is null and `result` is
        `FAIL` when `adhesion_class` is greater than 2, `PASS` otherwise."

        Design: Corner/state_machines/lining_verified_requires_both_current_pass_records
        """
        lot_id = _a_lined_lot_awaiting_both_verdicts(api)

        record = validate_success(
            api.create_lining_inspection(
                adhesion_inspection_payload(
                    lot_id, tank_lot_version(api, lot_id), adhesion_class=2
                ),
                quality_inspector_headers(),
            ),
            expected_status=201,
        )
        lot = validate_success(api.get_tank_lot(lot_id, quality_inspector_headers()))

        assert record["result"] == "PASS"
        assert record["holidays_per_tank"] is None
        assert lot["status"] == "LINED"

    def test_12_the_second_passing_record_of_the_other_type_verifies_the_lot(self, api):
        """Neither record supersedes the other, so both are current and the lot moves.

        PRD: "When the lot holds exactly one `CURRENT` `ADHESION` record with `result`
        `PASS` **and** exactly one `CURRENT` `HOLIDAY` record with `result` `PASS`, it moves
        `LINED → LINING_VERIFIED`."

        Design: Corner/state_machines/lining_verified_requires_both_current_pass_records
        """
        lot_id = _a_lined_lot_awaiting_both_verdicts(api)

        data_of(
            api.create_lining_inspection(
                adhesion_inspection_payload(
                    lot_id, tank_lot_version(api, lot_id), adhesion_class=2
                ),
                quality_inspector_headers(),
            )
        )
        holiday = data_of(
            api.create_lining_inspection(
                holiday_inspection_payload(lot_id, tank_lot_version(api, lot_id)),
                quality_inspector_headers(),
            )
        )
        lot = validate_success(api.get_tank_lot(lot_id, quality_inspector_headers()))
        rows = lot_inspections(api, lot_id)

        assert holiday["holidays_per_tank"] == approx4(0.5000)
        assert holiday["result"] == "PASS"
        assert lot["status"] == "LINING_VERIFIED"
        assert [row["record_status"] for row in rows] == ["CURRENT", "CURRENT"]
        assert lot["wip_quantity"] == 120
        assert lot["scrapped_quantity"] == 0
        assert lot["rework_count"] == 0


def _a_base_model_with_one_released_and_one_draft_variant(api):
    """Two private-label variants of one released base, only one of them in a channel."""
    base = make_model(api)
    released_variant = data_of(
        api.create_product_model(
            private_label_payload(
                base["id"],
                model_code="HD50-PL",
                channel="RETAIL",
                brand_label="HomeValue",
            ),
            compliance_engineer_headers(),
        )
    )
    draft_variant = data_of(
        api.create_product_model(
            private_label_payload(
                base["id"],
                model_code="BC50-PL",
                channel="BUILDER",
                brand_label="BuilderChoice",
            ),
            compliance_engineer_headers(),
        )
    )
    data_of(api.release_model_to_channel(base["id"], compliance_engineer_headers()))
    data_of(
        api.release_model_to_channel(
            released_variant["id"], compliance_engineer_headers()
        )
    )
    return base["id"], released_variant["id"], draft_variant


class TestWithdrawalFansOutToDistributedVariantsOnly:
    """The private-label tree is walked, but only where a channel posture exists."""

    def test_13_withdrawing_the_base_withdraws_only_its_released_variant(self, api):
        """The draft variant is left where it is, because it was never distributed.

        PRD: "Withdrawal fans out down the private-label tree: every private-label
        variant whose `base_model_id` is this model and whose own `release_status` is
        `RELEASED` or `RESTRICTED` is withdrawn as well, in `created_at` ascending order,
        and `version` is incremented on the withdrawn base and on each withdrawn variant."

        Design: Corner/state_machines/model_withdraw_cascades_to_released_private_label_variants_only
        """
        base_id, released_variant_id, draft_variant = _a_base_model_with_one_released_and_one_draft_variant(api)

        withdrawn = validate_success(
            api.withdraw_model(
                base_id,
                compliance_engineer_headers(),
                reason_payload(reason_code="LINE_DISCONTINUED"),
            )
        )

        assert withdrawn["release_status"] == "WITHDRAWN"
        variant = validate_success(
            api.get_product_model(released_variant_id, compliance_engineer_headers())
        )
        untouched = validate_success(
            api.get_product_model(draft_variant["id"], compliance_engineer_headers())
        )
        assert variant["release_status"] == "WITHDRAWN"
        assert untouched["release_status"] == "DRAFT"

    def test_14_the_untouched_variant_keeps_its_version_and_no_model_is_recertified(
        self, api
    ):
        """The channel dimension moved on its own, three times over.

        PRD: "Neither dimension gates the other's transitions: a model may be
        `RELEASED` while still `UNCERTIFIED`, and `CERTIFIED` while still `DRAFT`."

        Design: Corner/state_machines/model_withdraw_cascades_to_released_private_label_variants_only
        """
        base_id, released_variant_id, draft_variant = _a_base_model_with_one_released_and_one_draft_variant(api)

        data_of(
            api.withdraw_model(
                base_id,
                compliance_engineer_headers(),
                reason_payload(reason_code="LINE_DISCONTINUED"),
            )
        )

        after = validate_success(
            api.get_product_model(draft_variant["id"], compliance_engineer_headers())
        )
        assert_version_unchanged(draft_variant, after)
        for model_id in (base_id, released_variant_id, draft_variant["id"]):
            model = validate_success(
                api.get_product_model(model_id, compliance_engineer_headers())
            )
            assert model["certification_status"] == "UNCERTIFIED"


def _a_disqualified_supplier_with_two_blocked_lots(api):
    """A supplier disqualified after two of its lots had reached the line."""
    supplier = make_qualified_supplier(api)
    first = data_of(
        api.create_component_lot(
            component_lot_payload(supplier["id"]), supplier_quality_headers()
        )
    )
    data_of(api.release_component_lot(first["id"], quality_inspector_headers()))
    second = data_of(
        api.create_component_lot(
            component_lot_payload(supplier["id"], part_number="GV-881", quantity=40),
            supplier_quality_headers(),
        )
    )
    data_of(api.release_component_lot(second["id"], quality_inspector_headers()))
    data_of(
        api.disqualify_supplier(
            supplier["id"],
            reason_payload(reason_code="AUDIT_FAILURE"),
            supplier_quality_headers(),
        )
    )
    return supplier["id"], first["id"], second["id"]


class TestSupplierRecoveryOrdering:
    """Requalify, then disposition every contained lot, then score - in that order."""

    def test_15_a_blocked_lot_cannot_be_dispositioned_while_the_supplier_is_out(
        self, api
    ):
        """Unblocking is the step that must wait, not requalification.

        PRD: "The containment gate is not on requalification but on the subsequent
        scoring step, precisely because requalification is what makes the blocked lots
        dispositionable at all: unblocking a lot is refused while its supplier is still
        `DISQUALIFIED`."

        Design: Corner/state_machines/supplier_qualify_blocked_until_containment_dispositioned
        """
        _supplier_id, first_lot_id, _second_lot_id = _a_disqualified_supplier_with_two_blocked_lots(api)

        response = api.unblock_component_lot(first_lot_id, supplier_quality_headers())

        validate_error(response, ERR_COMPONENT_SUPPLIER_NOT_QUALIFIED, expected_status=409)
        lot = validate_success(
            api.get_component_lot(first_lot_id, quality_inspector_headers())
        )
        assert lot["status"] == "BLOCKED"

    def test_16_requalification_clears_the_verdict_without_clearing_containment(
        self, api
    ):
        """The supplier returns to PENDING with both lots still contained.

        PRD: "Requalifying a `DISQUALIFIED` supplier — a `SupplierQualityManager`
        action carrying a `reason_code` — moves it `DISQUALIFIED → PENDING`, clears both
        `disqualification_reason_code` and `qualification_score`, and increments `version`;
        it unblocks nothing by itself."

        Design: Corner/state_machines/supplier_qualify_blocked_until_containment_dispositioned
        """
        supplier_id, _first_lot_id, _second_lot_id = _a_disqualified_supplier_with_two_blocked_lots(api)

        requalified = validate_success(
            api.requalify_supplier(
                supplier_id,
                supplier_quality_headers(),
                reason_payload(reason_code="CAPA_CLOSED"),
            )
        )

        assert requalified["qualification_status"] == "PENDING"
        assert requalified["qualification_score"] is None
        assert requalified["disqualification_reason_code"] is None
        assert requalified["blocked_lot_count"] == 2

    def test_17_scoring_is_refused_while_even_one_lot_remains_contained(self, api):
        """Two blocked lots refuse, and so does the one left after the first unblock.

        PRD: "One further gate applies only on the way out of `PENDING`: the
        supplier's `blocked_lot_count` must be 0, and a `PENDING` supplier scored into
        either band while lots of its remain blocked is refused with
        `ERR_BLOCKED_LOTS_REMAIN`."

        Design: Corner/state_machines/supplier_qualify_blocked_until_containment_dispositioned
        """
        supplier_id, first_lot_id, _second_lot_id = _a_disqualified_supplier_with_two_blocked_lots(api)

        data_of(
            api.requalify_supplier(
                supplier_id,
                supplier_quality_headers(),
                reason_payload(reason_code="CAPA_CLOSED"),
            )
        )
        with_two_blocked = api.qualify_supplier(
            supplier_id, qualify_payload(), supplier_quality_headers()
        )
        unblocked = validate_success(
            api.unblock_component_lot(first_lot_id, supplier_quality_headers())
        )
        with_one_blocked = api.qualify_supplier(
            supplier_id, qualify_payload(), supplier_quality_headers()
        )

        validate_error(with_two_blocked, ERR_BLOCKED_LOTS_REMAIN, expected_status=409)
        validate_error(with_one_blocked, ERR_BLOCKED_LOTS_REMAIN, expected_status=409)
        assert unblocked["status"] == "RELEASED"
        assert unblocked["reject_reason_code"] is None
        supplier = validate_success(
            api.get_supplier(supplier_id, supplier_quality_headers())
        )
        assert supplier["qualification_status"] == "PENDING"
        assert supplier["blocked_lot_count"] == 1

    def test_18_rejecting_the_last_contained_lot_reopens_the_scoring_step(self, api):
        """Rejection overwrites the containment reason and empties the count.

        PRD: "Rejecting a `BLOCKED` lot is one of the two ways containment is
        cleared: a rejected lot is no longer contained, so the supplier's
        `blocked_lot_count` is recomputed and both the lot's and the supplier's `version`
        are incremented."

        Design: Corner/state_machines/supplier_qualify_blocked_until_containment_dispositioned
        """
        supplier_id, first_lot_id, second_lot_id = _a_disqualified_supplier_with_two_blocked_lots(api)

        data_of(
            api.requalify_supplier(
                supplier_id,
                supplier_quality_headers(),
                reason_payload(reason_code="CAPA_CLOSED"),
            )
        )
        data_of(api.unblock_component_lot(first_lot_id, supplier_quality_headers()))
        rejected = validate_success(
            api.reject_component_lot(
                second_lot_id,
                quality_inspector_headers(),
                reason_payload(reason_code="CONTAINMENT_SCRAP"),
            )
        )
        scored = validate_success(
            api.qualify_supplier(supplier_id, qualify_payload(), supplier_quality_headers())
        )

        assert rejected["status"] == "REJECTED"
        assert rejected["reject_reason_code"] == "CONTAINMENT_SCRAP"
        assert scored["blocked_lot_count"] == 0
        assert scored["qualification_score"] == approx2(91.40)
        assert scored["qualification_status"] == "QUALIFIED"
