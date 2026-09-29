"""Guard clauses that fire before any state is written.

Each family below drives one endpoint through the whole run of refusals it can
produce and then through the one call it accepts, so the guard order is visible
from the error identifiers alone and the accepted call proves nothing was
quietly written by the refused ones.
"""

from test_helpers import (
    approx2,
    assert_hardness_band,
    assert_notice_ledger,
    assert_reserve_ledger,
    assert_serial_number,
    assert_tank_lot_ledger,
    compliance_engineer_headers,
    component_lot_payload,
    data_of,
    ERR_BASE_MODEL_NOT_RELEASED,
    ERR_COMPLETION_BELOW_THRESHOLD,
    ERR_COMPONENT_SUPPLIER_NOT_QUALIFIED,
    ERR_FOAM_THICKNESS_BELOW_MINIMUM,
    ERR_HELD_UNITS_REMAIN,
    ERR_INSULATION_R_VALUE_SHORTFALL,
    ERR_INVALID_REQUEST,
    ERR_MODEL_NOT_RELEASED,
    ERR_PRIVATE_LABEL_BASE_INVALID,
    ERR_QUALIFICATION_EXPIRED,
    ERR_RECALL_BUDGET_EXCEEDED,
    ERR_RECALL_SCOPE_EMPTY,
    ERR_SERIAL_RANGE_INVALID,
    ERR_UNIT_NOT_IN_SERVICE,
    ERR_WARRANTY_RESERVE_INSUFFICIENT,
    foam_payload,
    heater_unit_payload,
    plant_operator_headers,
    private_label_payload,
    product_model_payload,
    qualify_payload,
    quality_inspector_headers,
    reason_payload,
    recall_campaign_payload,
    safety_valve_lot_payload,
    safety_valve_supplier_payload,
    scope_payload,
    ship_payload,
    supplier_payload,
    supplier_quality_headers,
    validate_error,
    validate_paginated,
    validate_success,
    warranty_analyst_headers,
    warranty_claim_payload,
    fixtures as x,
)

#: Every serial the August cohort of the default model can mint, in order.
AUGUST_SERIALS = (
    "GX50-T-202608-00001",
    "GX50-T-202608-00002",
    "GX50-T-202608-00003",
    "GX50-T-202608-00004",
    "GX50-T-202608-00005",
)


def _a_verified_lot_awaiting_insulation(api):
    """A 120-tank lot in LINING_VERIFIED under a model declaring R-20."""
    model = x.make_model(api)
    batch = x.make_fired_batch(api)
    lot_id = x.make_verified_tank_lot(api, model["id"], batch.batch_id)
    return model["id"], lot_id


def _foam(api, lot_id, thickness_mm):
    """Attempt one foaming pass at the given wall thickness."""
    return api.foam_tank_lot(
        lot_id, foam_payload(foam_thickness_mm=thickness_mm), plant_operator_headers()
    )


class TestFoamThicknessFloorPrecedesTheRValueFloor:
    """Two floors on one call, and the cheaper one is deliberately first."""

    def test_01_a_thirty_nine_millimetre_wall_reports_the_thickness_floor(self, api):
        """39 mm is both under the floor and short on R-value; the floor wins.

        PRD: "Because the thickness floor is evaluated ahead of this comparison, a lot
        foamed at, say, 30 mm reports the thickness error even though it would also have
        failed the R-value comparison."

        Design: Corner/validations/foam_thickness_floor_beats_r_value_shortfall_rejected
        """
        _model_id, lot_id = _a_verified_lot_awaiting_insulation(api)

        response = _foam(api, lot_id, 39)

        validate_error(response, ERR_FOAM_THICKNESS_BELOW_MINIMUM, expected_status=422)

    def test_02_a_legal_wall_that_misses_r_twenty_reports_the_shortfall(self, api):
        """40 mm buys R-16.0 and 49 mm buys R-19.6, both under the declared R-20.

        PRD: "The service then derives `achieved_r_value` as the `foam_thickness_mm`
        multiplied by 0.4 R-value units per millimetre, rounded half up to one decimal
        place, and compares it against the model's declared `insulation_r_value`; an
        achieved value below the declared value is refused with
        `ERR_INSULATION_R_VALUE_SHORTFALL`, while an achieved value exactly equal to it
        passes."

        Design: Corner/validations/foam_thickness_floor_beats_r_value_shortfall_rejected
        """
        _model_id, lot_id = _a_verified_lot_awaiting_insulation(api)

        at_the_floor = _foam(api, lot_id, 40)
        one_short = _foam(api, lot_id, 49)

        validate_error(at_the_floor, ERR_INSULATION_R_VALUE_SHORTFALL, expected_status=409)
        validate_error(one_short, ERR_INSULATION_R_VALUE_SHORTFALL, expected_status=409)

    def test_03_only_the_accepted_pass_writes_the_insulation_fields(self, api):
        """Three refusals leave the lot untouched; 50 mm lands exactly on R-20.

        PRD: "On acceptance the lot moves `LINING_VERIFIED → FOAMED` with
        `foam_density_kg_m3`, `foam_thickness_mm` and the computed `achieved_r_value` all
        stored."

        Design: Corner/validations/foam_thickness_floor_beats_r_value_shortfall_rejected
        """
        _model_id, lot_id = _a_verified_lot_awaiting_insulation(api)

        _foam(api, lot_id, 39)
        _foam(api, lot_id, 40)
        _foam(api, lot_id, 49)
        refused = validate_success(api.get_tank_lot(lot_id, plant_operator_headers()))

        assert refused["status"] == "LINING_VERIFIED"
        assert refused["foam_thickness_mm"] is None
        assert refused["achieved_r_value"] is None
        assert refused["wip_quantity"] == 120

        foamed = validate_success(_foam(api, lot_id, 50))

        assert foamed["status"] == "FOAMED"
        assert foamed["foam_thickness_mm"] == 50
        assert foamed["achieved_r_value"] == approx2(20.0)
        assert foamed["foam_density_kg_m3"] == approx2(32.0)
        assert foamed["wip_quantity"] == 120
        assert_tank_lot_ledger(foamed)


def _one_unit_in_the_field_and_one_still_on_the_line(api):
    """A shipped unit installed in hard water, plus a sibling only labelled."""
    plant = x.make_full_plant(api)
    in_service = x.ship_unit(api, plant, hardness_gpg=12.0)
    on_the_line = x.label_unit(api, plant)
    return plant, in_service, on_the_line


#: One year of service to the day for a unit shipped on 2026-08-05T06:00:00Z.
TWELVE_MONTHS_IN = "2027-07-31T06:00:00Z"
#: Exactly 2,160 days later, the last instant the long warranty still pays in full.
SEVENTY_TWO_MONTHS_IN = "2032-07-04T06:00:00Z"


def _file_and_validate(api, unit_id, failure_mode):
    """Open a claim for one failure mode and take it straight to VALIDATED."""
    claim = data_of(
        api.create_warranty_claim(
            warranty_claim_payload(
                unit_id,
                failure_mode=failure_mode,
                reported_water_hardness_gpg=12.0,
            ),
            warranty_analyst_headers(),
        )
    )
    return data_of(api.validate_claim(claim["id"], warranty_analyst_headers()))


class TestWarrantyFilingAndReserveGuards:
    """A claim needs a unit in service, and a payment needs money behind it."""

    def test_04_a_claim_against_a_unit_never_shipped_is_refused(self, api):
        """A labelled unit is still in the plant, so nobody can claim on it.

        PRD: "The unit must be in service, meaning its `build_status` is `SHIPPED` and
        its `shipped_at` is not null; a claim against a staged, assembled, labelled, held
        or scrapped unit is refused with `ERR_UNIT_NOT_IN_SERVICE`."

        Design: Corner/validations/warranty_filing_and_reserve_guards_rejected
        """
        _plant, _in_service, on_the_line = _one_unit_in_the_field_and_one_still_on_the_line(api)

        response = api.create_warranty_claim(
            warranty_claim_payload(on_the_line, reported_water_hardness_gpg=12.0),
            warranty_analyst_headers(),
        )

        validate_error(response, ERR_UNIT_NOT_IN_SERVICE, expected_status=409)

    def test_05_a_component_claim_at_twelve_months_still_pays_in_full(self, api):
        """4,200 parts plus 12,525 labour plus 3,325 freight at the full share.

        PRD: "The three component modes carry a short warranty: for `THERMOSTAT`,
        `GAS_VALVE` and `COMPRESSOR`, coverage is 1.00 when the frozen service months are
        12 or fewer and 0.00 otherwise."

        Design: Corner/validations/warranty_filing_and_reserve_guards_rejected
        """
        _plant, in_service, _on_the_line = _one_unit_in_the_field_and_one_still_on_the_line(api)
        x.set_clock(api, TWELVE_MONTHS_IN)

        claim = _file_and_validate(api, in_service, "THERMOSTAT")

        assert claim["months_in_service_at_report"] == 12
        assert claim["coverage_pct"] == approx2(1.00)
        assert claim["approved_payout_cents"] == 20050
        assert claim["status"] == "VALIDATED"

    def test_06_a_tank_claim_at_seventy_two_months_still_pays_in_full(self, api):
        """41,500 parts plus the two flat lines, all at the undiminished share.

        PRD: "The two tank-related modes carry the long warranty: for `TANK_LEAK` and
        `ANODE_DEPLETION`, coverage is the full 1.00 when the frozen service months are 72
        or fewer, drops to a half share of 0.50 when they are more than 72 but 96 or
        fewer, and falls to 0.00 beyond 96."

        Design: Corner/validations/warranty_filing_and_reserve_guards_rejected
        """
        _plant, in_service, _on_the_line = _one_unit_in_the_field_and_one_still_on_the_line(api)
        x.set_clock(api, SEVENTY_TWO_MONTHS_IN)

        claim = _file_and_validate(api, in_service, "TANK_LEAK")

        assert claim["months_in_service_at_report"] == 72
        assert claim["coverage_pct"] == approx2(1.00)
        assert claim["approved_payout_cents"] == 57350
        assert claim["status"] == "VALIDATED"

    def test_07_the_second_payment_exceeds_what_one_shipment_accrued(self, api):
        """One gas shipment funds 42,000 cents; the two claims together want 77,400.

        PRD: "A `WarrantyAnalyst` pays a claim in `status` `VALIDATED`, moving it
        `VALIDATED → PAID`, and the claim's `approved_payout_cents` must be less than or
        equal to the `warranty_reserve_balance_cents` of the product model of the claim's
        unit; a payout exactly equal to the balance is allowed and drains the reserve to
        zero, while one cent more is refused with `ERR_WARRANTY_RESERVE_INSUFFICIENT` and
        the claim stays `VALIDATED`."

        Design: Corner/validations/warranty_filing_and_reserve_guards_rejected
        """
        plant, in_service, _on_the_line = _one_unit_in_the_field_and_one_still_on_the_line(api)
        x.set_clock(api, TWELVE_MONTHS_IN)
        component_claim = _file_and_validate(api, in_service, "THERMOSTAT")
        x.set_clock(api, SEVENTY_TWO_MONTHS_IN)
        tank_claim = _file_and_validate(api, in_service, "TANK_LEAK")

        paid = validate_success(
            api.pay_claim(component_claim["id"], warranty_analyst_headers())
        )
        after_payment = validate_success(
            api.get_product_model(plant.model_id, compliance_engineer_headers())
        )
        refused = api.pay_claim(tank_claim["id"], warranty_analyst_headers())
        unpaid = validate_success(
            api.get_warranty_claim(tank_claim["id"], warranty_analyst_headers())
        )
        after_refusal = validate_success(
            api.get_product_model(plant.model_id, compliance_engineer_headers())
        )

        assert paid["status"] == "PAID"
        assert paid["paid_at"].startswith("2032-07-04T06:00:00")
        assert after_payment["warranty_reserve_accrued_cents"] == 42000
        assert after_payment["warranty_paid_cents"] == 20050
        assert after_payment["warranty_reserve_balance_cents"] == 21950
        assert_reserve_ledger(after_payment)

        validate_error(refused, ERR_WARRANTY_RESERVE_INSUFFICIENT, expected_status=402)
        assert unpaid["status"] == "VALIDATED"
        assert unpaid["paid_at"] is None
        assert after_refusal["warranty_reserve_accrued_cents"] == 42000
        assert after_refusal["warranty_paid_cents"] == 20050
        assert after_refusal["warranty_reserve_balance_cents"] == 21950
        assert_reserve_ledger(after_refusal)


def _a_base_model_and_its_private_label_variant(api):
    """A trade base model and one retailer-branded variant of it, both still DRAFT."""
    base = x.make_model(api)
    variant = data_of(
        api.create_product_model(
            private_label_payload(
                base["id"], model_code="HD50-PL", brand_label="HomeValue"
            ),
            compliance_engineer_headers(),
        )
    )
    return base["id"], variant["id"]


def _create_model(api, payload):
    """Attempt one catalogue create, returning the raw response."""
    return api.create_product_model(payload, compliance_engineer_headers())


class TestPrivateLabelShapeAndReleaseOrder:
    """The re-branding shape is checked on creation; the base's posture on release."""

    def test_08_every_broken_base_relationship_reports_the_same_shape_error(self, api):
        """No base at all, a base that is itself re-branded, and a capacity mismatch.

        PRD: "Any violation of that shape — a private-label variant without a base, a base
        that is itself a private label, a base whose fuel type or capacity differs, or a
        base supplied on a non-private-label model — is rejected with
        `ERR_PRIVATE_LABEL_BASE_INVALID`."

        Design: Corner/validations/private_label_base_and_release_rules_rejected
        """
        base_id, variant_id = _a_base_model_and_its_private_label_variant(api)
        orphan = private_label_payload(base_id, model_code="NB50-PL")
        orphan.pop("base_model_id")

        no_base = _create_model(api, orphan)
        base_is_a_variant = _create_model(
            api, private_label_payload(variant_id, model_code="ST50-PL")
        )
        capacity_differs = _create_model(
            api,
            private_label_payload(
                base_id, model_code="HD75-PL", nominal_capacity_gallons=75
            ),
        )

        validate_error(no_base, ERR_PRIVATE_LABEL_BASE_INVALID, expected_status=422)
        validate_error(base_is_a_variant, ERR_PRIVATE_LABEL_BASE_INVALID, expected_status=422)
        validate_error(capacity_differs, ERR_PRIVATE_LABEL_BASE_INVALID, expected_status=422)

    def test_09_the_brand_label_field_is_settled_by_schema_validation(self, api):
        """A variant owes a brand; a plain catalogue model may not carry one.

        PRD: "When it is `true`, the payload must also carry `base_model_id` naming the
        model being re-branded and `brand_label`, the retailer brand printed on the jacket
        (at most 40 characters); the named base model must itself have `is_private_label`
        false and must match the variant's `fuel_type` and `nominal_capacity_gallons`
        exactly."

        Design: Corner/validations/private_label_base_and_release_rules_rejected
        """
        base_id, _variant_id = _a_base_model_and_its_private_label_variant(api)
        unbranded = private_label_payload(base_id, model_code="NL50-PL")
        unbranded.pop("brand_label")

        variant_without_a_brand = _create_model(api, unbranded)
        plain_model_with_a_brand = _create_model(
            api, product_model_payload(model_code="PB50-T", brand_label="HomeValue")
        )

        validate_error(variant_without_a_brand, ERR_INVALID_REQUEST, expected_status=400)
        validate_error(plain_model_with_a_brand, ERR_INVALID_REQUEST, expected_status=400)

    def test_10_a_variant_cannot_reach_the_channel_before_its_base(self, api):
        """The base is still DRAFT, so the retailer edition has nothing to ride on.

        PRD: "A variant whose base is still `DRAFT`, or already `WITHDRAWN`, is refused
        with `ERR_BASE_MODEL_NOT_RELEASED`."

        Design: Corner/validations/private_label_base_and_release_rules_rejected
        """
        _base_id, variant_id = _a_base_model_and_its_private_label_variant(api)

        response = api.release_model_to_channel(
            variant_id, compliance_engineer_headers()
        )
        variant = validate_success(
            api.get_product_model(variant_id, compliance_engineer_headers())
        )

        validate_error(response, ERR_BASE_MODEL_NOT_RELEASED, expected_status=409)
        assert variant["release_status"] == "DRAFT"

    def test_11_releasing_the_base_first_opens_the_variant_s_own_release(self, api):
        """Two rows, released in dependency order, neither of them rated yet.

        PRD: "Channel release is a `ComplianceEngineer` action that moves a model
        `DRAFT → RELEASED`; a model whose `release_status` is anything other than `DRAFT`
        reports `ERR_INVALID_MODEL_STATE`."

        Design: Corner/validations/private_label_base_and_release_rules_rejected
        """
        base_id, variant_id = _a_base_model_and_its_private_label_variant(api)
        api.release_model_to_channel(variant_id, compliance_engineer_headers())

        base = validate_success(
            api.release_model_to_channel(base_id, compliance_engineer_headers())
        )
        variant = validate_success(
            api.release_model_to_channel(variant_id, compliance_engineer_headers())
        )
        rows, meta = validate_paginated(
            api.list_product_models(
                compliance_engineer_headers(), {"limit": 100, "offset": 0}
            )
        )

        assert base["release_status"] == "RELEASED"
        assert variant["release_status"] == "RELEASED"
        assert variant["base_model_id"] == base_id
        assert variant["brand_label"] == "HomeValue"
        assert meta["total_count"] == 2
        assert len(rows) == 2
        for row in rows:
            assert row["certification_status"] == "UNCERTIFIED"


def _a_recall_in_remedy_with_one_unit_still_held(api):
    """Four notified owners in the field and one in-plant unit held by the fan-out."""
    plant = x.make_full_plant(api)
    for _ in range(4):
        x.ship_unit(api, plant, hardness_gpg=12.0)
    held = x.label_unit(api, plant)
    campaign = data_of(
        api.create_recall_campaign(
            recall_campaign_payload(plant.model_id, budget_cents=150000),
            warranty_analyst_headers(),
        )
    )
    data_of(
        api.scope_campaign(
            campaign["id"],
            scope_payload(AUGUST_SERIALS[0], AUGUST_SERIALS[4]),
            warranty_analyst_headers(),
        )
    )
    data_of(api.announce_campaign(campaign["id"], warranty_analyst_headers()))
    notices = x.campaign_notices(api, campaign["id"])
    for notice in notices:
        data_of(api.notify_notice(notice["id"], warranty_analyst_headers()))
    return plant, campaign["id"], notices, held


def _remedy(api, notices):
    """Record the remedy on each of the given notices in turn."""
    for notice in notices:
        data_of(api.remedy_notice(notice["id"], warranty_analyst_headers()))


class TestRecallClosureLadder:
    """Closure needs the population measure met and every hold cleared, in that order."""

    def test_12_the_population_measure_is_the_one_that_gates_closure(self, api):
        """Two of four remedies is 50.00 by notice but only 40.00 by population.

        PRD: "First, `completion_pct_population_based` must be at least 80.00 — exactly
        80.00 passes, and anything below is refused with `ERR_COMPLETION_BELOW_THRESHOLD` —
        which means the notice-based figure being at or above the threshold is not
        sufficient on its own."

        Design: Corner/validations/recall_close_completion_then_held_units_ladder
        """
        _plant, campaign_id, notices, _held = _a_recall_in_remedy_with_one_unit_still_held(api)
        _remedy(api, notices[:2])

        response = api.close_campaign(campaign_id, warranty_analyst_headers())
        completion = validate_success(
            api.get_campaign_completion(campaign_id, warranty_analyst_headers())
        )

        validate_error(response, ERR_COMPLETION_BELOW_THRESHOLD, expected_status=409)
        assert completion["completion_pct_population_based"] == approx2(40.00)
        assert completion["completion_pct_notice_based"] == approx2(50.00)

    def test_13_a_perfect_notice_programme_still_leaves_the_hold_in_the_way(self, api):
        """All four owners remedied is 100.00 by notice and 80.00 by population.

        PRD: "Second, no unit in the affected population may still be in `build_status`
        `HELD`, and a remaining hold is refused with `ERR_HELD_UNITS_REMAIN`; the in-plant
        units must have been either released back into production or disassembled and
        scrapped before the recall can be declared finished."

        Design: Corner/validations/recall_close_completion_then_held_units_ladder
        """
        _plant, campaign_id, notices, _held = _a_recall_in_remedy_with_one_unit_still_held(api)
        _remedy(api, notices)

        completion = validate_success(
            api.get_campaign_completion(campaign_id, warranty_analyst_headers())
        )
        response = api.close_campaign(campaign_id, warranty_analyst_headers())
        campaign = validate_success(
            api.get_recall_campaign(campaign_id, warranty_analyst_headers())
        )

        assert completion["completion_pct_notice_based"] == approx2(100.00)
        assert completion["completion_pct_population_based"] == approx2(80.00)
        validate_error(response, ERR_HELD_UNITS_REMAIN, expected_status=409)
        assert campaign["status"] == "IN_REMEDY"

    def test_14_releasing_the_hold_restores_the_label_but_not_the_channel(self, api):
        """The unit goes back to LABELED while the model keeps its restriction.

        PRD: "All three branches clear `hold_reason_code`, clear `held_from_status`, have
        the owning product model recompute `held_unit_count`, and increment `version` on
        both the unit and the model."

        Design: Corner/validations/recall_close_completion_then_held_units_ladder
        """
        plant, campaign_id, notices, held = _a_recall_in_remedy_with_one_unit_still_held(api)
        _remedy(api, notices)
        api.close_campaign(campaign_id, warranty_analyst_headers())

        released = validate_success(
            api.release_unit_hold(held, plant_operator_headers())
        )
        model = validate_success(
            api.get_product_model(plant.model_id, compliance_engineer_headers())
        )

        assert released["build_status"] == "LABELED"
        assert released["held_from_status"] is None
        assert released["hold_reason_code"] is None
        assert model["held_unit_count"] == 0
        assert model["release_status"] == "RESTRICTED"

    def test_15_with_the_plant_clear_the_third_close_finally_lands(self, api):
        """Same campaign, same percentages, and now nothing is held against it.

        PRD: "On acceptance the campaign moves `IN_REMEDY → CLOSED`."

        Design: Corner/validations/recall_close_completion_then_held_units_ladder
        """
        _plant, campaign_id, notices, held = _a_recall_in_remedy_with_one_unit_still_held(api)
        _remedy(api, notices)
        api.close_campaign(campaign_id, warranty_analyst_headers())
        data_of(api.release_unit_hold(held, plant_operator_headers()))

        closed = validate_success(
            api.close_campaign(campaign_id, warranty_analyst_headers())
        )

        assert closed["status"] == "CLOSED"
        assert closed["remedied_count"] == 4
        assert closed["notice_count"] == 4
        assert closed["affected_unit_count"] == 5
        assert_notice_ledger(closed, x.campaign_notices(api, campaign_id))


#: A well-ordered range over a production month that minted no serials at all.
DECEMBER_RANGE = ("GX50-T-202612-00001", "GX50-T-202612-00009")


def _three_labelled_units_and_two_campaigns(api):
    """Three serialised in-plant units, a well-funded campaign and a starved one."""
    plant = x.make_full_plant(api)
    units = [x.label_unit(api, plant) for _ in range(3)]
    generous = data_of(
        api.create_recall_campaign(
            recall_campaign_payload(
                plant.model_id, campaign_code="RC-A", budget_cents=150000
            ),
            warranty_analyst_headers(),
        )
    )
    starved = data_of(
        api.create_recall_campaign(
            recall_campaign_payload(
                plant.model_id, campaign_code="RC-B", budget_cents=20000
            ),
            warranty_analyst_headers(),
        )
    )
    return plant, units, generous["id"], starved["id"]


def _scope(api, campaign_id, start, end):
    """Attempt one scoping call over the given inclusive serial range."""
    return api.scope_campaign(
        campaign_id, scope_payload(start, end), warranty_analyst_headers()
    )


class TestRecallScopeRangeAndBudgetGuards:
    """Range well-formedness is settled before the population is ever resolved."""

    def test_16_an_inverted_range_never_reports_an_empty_population(self, api):
        """Backwards is a range error; forwards over an empty month is a scope error.

        PRD: "The range is validated before anything else is attempted:
        `serial_range_end` must not be lexicographically less than `serial_range_start`,
        and an inverted range is refused with `ERR_SERIAL_RANGE_INVALID` before the
        population is resolved, so an inverted range is never reported as an empty scope."

        Design: Corner/validations/recall_scope_range_and_budget_guards_rejected
        """
        _plant, _units, generous, _starved = _three_labelled_units_and_two_campaigns(api)

        inverted = _scope(api, generous, AUGUST_SERIALS[2], AUGUST_SERIALS[0])
        empty_month = _scope(api, generous, *DECEMBER_RANGE)
        campaign = validate_success(
            api.get_recall_campaign(generous, warranty_analyst_headers())
        )

        validate_error(inverted, ERR_SERIAL_RANGE_INVALID, expected_status=422)
        validate_error(empty_month, ERR_RECALL_SCOPE_EMPTY, expected_status=422)
        assert campaign["status"] == "DRAFT"
        assert campaign["serial_range_start"] is None
        assert campaign["serial_range_end"] is None

    def test_17_the_budget_bites_at_announcement_not_at_scoping(self, api):
        """Scoping three units at 20,700 each is fine; announcing 62,100 is not.

        PRD: "A `WarrantyAnalyst` announces a campaign in `status` `SCOPED`, and the
        campaign's `estimated_remedy_cost_cents` must be less than or equal to its
        `budget_cents`; an estimate exactly equal to the budget is allowed, and one cent
        over is refused with `ERR_RECALL_BUDGET_EXCEEDED`, leaving the campaign `SCOPED` so
        it can be re-scoped to a narrower range or reopened with more budget."

        Design: Corner/validations/recall_scope_range_and_budget_guards_rejected
        """
        _plant, _units, _generous, starved = _three_labelled_units_and_two_campaigns(api)

        scoped = validate_success(
            _scope(api, starved, AUGUST_SERIALS[0], AUGUST_SERIALS[2])
        )
        response = api.announce_campaign(starved, warranty_analyst_headers())
        _rows, meta = validate_paginated(
            api.list_recall_notices(
                warranty_analyst_headers(), {"limit": 100, "offset": 0}
            )
        )

        assert scoped["status"] == "SCOPED"
        assert scoped["affected_unit_count"] == 3
        assert scoped["per_unit_remedy_cost_cents"] == 20700
        assert scoped["estimated_remedy_cost_cents"] == 62100
        validate_error(response, ERR_RECALL_BUDGET_EXCEEDED, expected_status=402)
        assert meta["total_count"] == 0

    def test_18_a_cancelled_campaign_keeps_the_scope_it_never_announced(self, api):
        """The audit record retains the count and the cost that priced it out.

        PRD: "Both branches retain whatever scope snapshot the campaign had accumulated —
        `serial_range_start`, `serial_range_end`, `affected_unit_count`,
        `per_unit_remedy_cost_cents` and `estimated_remedy_cost_cents` are preserved for
        the audit record rather than cleared — and neither branch touches any unit, since
        no unit was ever held or notified."

        Design: Corner/validations/recall_scope_range_and_budget_guards_rejected
        """
        _plant, units, generous, starved = _three_labelled_units_and_two_campaigns(api)
        data_of(_scope(api, starved, AUGUST_SERIALS[0], AUGUST_SERIALS[2]))
        api.announce_campaign(starved, warranty_analyst_headers())

        cancelled = validate_success(
            api.cancel_campaign(
                starved,
                warranty_analyst_headers(),
                reason_payload(reason_code="BUDGET_NOT_APPROVED"),
            )
        )
        narrower = validate_success(
            _scope(api, generous, AUGUST_SERIALS[0], AUGUST_SERIALS[1])
        )

        assert cancelled["status"] == "CANCELLED"
        assert cancelled["affected_unit_count"] == 3
        assert cancelled["estimated_remedy_cost_cents"] == 62100
        assert narrower["affected_unit_count"] == 2
        assert narrower["estimated_remedy_cost_cents"] == 41400
        for unit_id in units:
            unit = validate_success(
                api.get_heater_unit(unit_id, plant_operator_headers())
            )
            assert unit["build_status"] == "LABELED"


#: The instant one supplier's qualification is written to run to.
EXPIRES_AT = "2026-08-02T00:00:00Z"
#: One second past that instant, the first moment the qualification is stale.
ONE_SECOND_STALE = "2026-08-02T00:00:01Z"


def _a_qualification_expiring_now_and_a_supplier_never_scored(api):
    """One QUALIFIED supplier standing exactly on its expiry, one still PENDING."""
    expiring = data_of(
        api.create_supplier(supplier_payload(), supplier_quality_headers())
    )
    data_of(
        api.qualify_supplier(
            expiring["id"],
            qualify_payload(qualified_until=EXPIRES_AT),
            supplier_quality_headers(),
        )
    )
    never_scored = data_of(
        api.create_supplier(safety_valve_supplier_payload(), supplier_quality_headers())
    )
    on_time = data_of(
        api.create_component_lot(
            component_lot_payload(expiring["id"]), supplier_quality_headers()
        )
    )
    one_second_late = data_of(
        api.create_component_lot(
            component_lot_payload(expiring["id"], part_number="GV-881"),
            supplier_quality_headers(),
        )
    )
    unscored_lot = data_of(
        api.create_component_lot(
            safety_valve_lot_payload(never_scored["id"]), supplier_quality_headers()
        )
    )
    x.set_clock(api, EXPIRES_AT)
    return (
        expiring["id"],
        never_scored["id"],
        on_time["id"],
        one_second_late["id"],
        unscored_lot["id"],
    )


class TestQualificationExpiryIsInclusive:
    """Two different refusals on the same endpoint: never scored, and scored too long ago."""

    def test_19_a_supplier_that_was_never_scored_cannot_supply_the_line(self, api):
        """PENDING is not a qualification, so its lot stays in quarantine.

        PRD: "The owning supplier's `qualification_status` must be `QUALIFIED` or
        `CONDITIONAL`; a `PENDING` or `DISQUALIFIED` supplier yields
        `ERR_COMPONENT_SUPPLIER_NOT_QUALIFIED`."

        Design: Corner/validations/supplier_qualification_expiry_is_inclusive_rejected
        """
        (
            _expiring,
            never_scored,
            _on_time,
            _one_second_late,
            unscored_lot,
        ) = _a_qualification_expiring_now_and_a_supplier_never_scored(api)

        response = api.release_component_lot(unscored_lot, quality_inspector_headers())
        lot = validate_success(
            api.get_component_lot(unscored_lot, supplier_quality_headers())
        )
        supplier = validate_success(
            api.get_supplier(never_scored, supplier_quality_headers())
        )

        validate_error(response, ERR_COMPONENT_SUPPLIER_NOT_QUALIFIED, expected_status=409)
        assert lot["status"] == "QUARANTINED"
        assert supplier["qualification_status"] == "PENDING"
        assert supplier["qualified_until"] is None
        assert supplier["qualification_score"] is None

    def test_20_the_expiry_instant_itself_still_passes_and_one_second_later_does_not(self, api):
        """Midnight exactly is inside the qualification; 00:00:01 is outside it.

        PRD: "And the supplier's `qualified_until` must be at or after the current logical
        clock — a `qualified_until` strictly before it yields `ERR_QUALIFICATION_EXPIRED`,
        while a `qualified_until` exactly equal to the current instant passes."

        Design: Corner/validations/supplier_qualification_expiry_is_inclusive_rejected
        """
        (
            expiring,
            _never_scored,
            on_time,
            one_second_late,
            _unscored_lot,
        ) = _a_qualification_expiring_now_and_a_supplier_never_scored(api)

        accepted = validate_success(
            api.release_component_lot(on_time, quality_inspector_headers())
        )
        x.set_clock(api, ONE_SECOND_STALE)
        refused = api.release_component_lot(one_second_late, quality_inspector_headers())
        stale_lot = validate_success(
            api.get_component_lot(one_second_late, supplier_quality_headers())
        )
        supplier = validate_success(
            api.get_supplier(expiring, supplier_quality_headers())
        )

        assert accepted["status"] == "RELEASED"
        validate_error(refused, ERR_QUALIFICATION_EXPIRED, expected_status=409)
        assert stale_lot["status"] == "QUARANTINED"
        assert supplier["qualification_status"] == "QUALIFIED"
        assert supplier["qualification_score"] == approx2(91.40)


def _a_certified_model_still_out_of_channel_with_one_assembled_unit(api):
    """A CERTIFIED but DRAFT-release model carrying one unit ready to be labelled."""
    supply = x.make_supply_base(api)
    model = x.make_certified_model(api)
    batch = x.make_fired_batch(api)
    lot_id = x.make_released_tank_lot(api, model.model_id, batch.batch_id)
    unit_id = data_of(
        api.create_heater_unit(
            heater_unit_payload(lot_id, supply.valve_lot_id, supply.gas_lot_id),
            plant_operator_headers(),
        )
    )["id"]
    data_of(api.assemble_unit(unit_id, plant_operator_headers()))
    return model.model_id, unit_id


class TestLabelAndShipChannelGate:
    """The channel dimension is read twice on the way out of the plant."""

    def test_21_a_certified_model_that_never_reached_a_channel_cannot_be_labelled(self, api):
        """The rating exists but the catalogue posture is still DRAFT.

        PRD: "Labelling is the moment the two catalogue dimensions are read together, and
        it is the only such moment in the service. A `PlantOperator` labels a unit that is
        `ASSEMBLED`, and the unit's model must have `certification_status` `CERTIFIED` —
        anything else, including `SUSPENDED` and `DECERTIFIED`, is refused with
        `ERR_MODEL_NOT_CERTIFIED` — and `release_status` `RELEASED`, with anything else
        refused as `ERR_MODEL_NOT_RELEASED`."

        Design: Corner/validations/label_and_ship_channel_gate_rejected
        """
        model_id, unit_id = _a_certified_model_still_out_of_channel_with_one_assembled_unit(api)

        response = api.label_unit(unit_id, plant_operator_headers())
        unit = validate_success(api.get_heater_unit(unit_id, plant_operator_headers()))
        model = validate_success(
            api.get_product_model(model_id, compliance_engineer_headers())
        )

        validate_error(response, ERR_MODEL_NOT_RELEASED, expected_status=409)
        assert unit["build_status"] == "ASSEMBLED"
        assert unit["serial_number"] is None
        assert unit["label_status"] == "NONE"
        assert model["certification_status"] == "CERTIFIED"
        assert model["release_status"] == "DRAFT"

    def test_22_the_release_to_channel_unblocks_the_very_same_call(self, api):
        """Nothing else changes, and the second label mints the August serial.

        PRD: "The unit then moves `ASSEMBLED → LABELED` with `label_status` set to
        `APPLIED` and a freshly minted `serial_number`."

        Design: Corner/validations/label_and_ship_channel_gate_rejected
        """
        model_id, unit_id = _a_certified_model_still_out_of_channel_with_one_assembled_unit(api)
        api.label_unit(unit_id, plant_operator_headers())
        data_of(api.release_model_to_channel(model_id, compliance_engineer_headers()))

        labelled = validate_success(api.label_unit(unit_id, plant_operator_headers()))

        assert labelled["build_status"] == "LABELED"
        assert labelled["label_status"] == "APPLIED"
        assert_serial_number(labelled, "GX50-T", "2026-08", 1)

    def test_23_the_shipment_channel_must_be_the_model_s_own_channel(self, api):
        """A trade model refuses a retail truck and accrues only on the accepted run.

        PRD: "Shipment is also the accrual event for the warranty reserve. On each
        shipment the unit's product model adds a fixed per-unit accrual to both
        `warranty_reserve_accrued_cents` and `warranty_reserve_balance_cents`, keyed on the
        model's `fuel_type`: 42,000 cents — that is, 420 dollars — for a `GAS` model,
        31,000 cents for an `ELECTRIC` model, and 98,000 cents for a `HEAT_PUMP` model."

        Design: Corner/validations/label_and_ship_channel_gate_rejected
        """
        model_id, unit_id = _a_certified_model_still_out_of_channel_with_one_assembled_unit(api)
        data_of(api.release_model_to_channel(model_id, compliance_engineer_headers()))
        data_of(api.label_unit(unit_id, plant_operator_headers()))

        wrong_channel = api.ship_unit(
            unit_id,
            ship_payload(install_water_hardness_gpg=6.0, distribution_channel="RETAIL"),
            plant_operator_headers(),
        )
        still_here = validate_success(
            api.get_heater_unit(unit_id, plant_operator_headers())
        )
        before = validate_success(
            api.get_product_model(model_id, compliance_engineer_headers())
        )
        shipped = validate_success(
            api.ship_unit(
                unit_id,
                ship_payload(
                    install_water_hardness_gpg=6.0, distribution_channel="TRADE"
                ),
                plant_operator_headers(),
            )
        )
        after = validate_success(
            api.get_product_model(model_id, compliance_engineer_headers())
        )

        validate_error(wrong_channel, ERR_MODEL_NOT_RELEASED, expected_status=409)
        assert still_here["build_status"] == "LABELED"
        assert still_here["shipped_at"] is None
        assert before["warranty_reserve_accrued_cents"] == 0
        assert shipped["build_status"] == "SHIPPED"
        assert_hardness_band(shipped, "MODERATE")
        assert after["warranty_reserve_accrued_cents"] == 42000
        assert_reserve_ledger(after)
