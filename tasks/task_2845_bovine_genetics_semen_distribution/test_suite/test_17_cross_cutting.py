"""Where two subsystems meet: the version pins, the value cascade and the aggregates."""

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_buckets,
    assert_instant_equals,
    assert_row_unchanged,
    assert_settlement,
    expected_market_unit_value_cents,
    expected_settlement,
    expected_standard_unit_value_cents,
    factories,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)

STALE_SIRE = ApiErrorId.ERR_STALE_SIRE_VERSION.value
STALE_LOT = ApiErrorId.ERR_STALE_STRAW_LOT_VERSION.value
NOT_FOUND = ApiErrorId.ERR_RESOURCE_NOT_FOUND.value


class TestSireVersionPin:
    """PRD 2.7's first pin: expected_sire_version on an evaluation filing."""

    PROOF_SEASON = "2026-09-01T00:00:00Z"
    LATER_EFFECTIVE_AT = "2026-08-20T00:00:00Z"

    def test_a_pin_either_side_of_current_is_refused_and_the_fresh_one_lands(self, api):
        """A parentage correction moves the bull under the client's feet.

        PRD 2.7: "Its value must equal the target `Sire` row's current
        `version`; if any other writer has advanced that `version` since the
        client last read the bull, the creation is rejected with
        `ERR_STALE_SIRE_VERSION` (HTTP 412)."
        PRD 3.1: "`pedigree_depth` is re-derived and `version` increments by 1".

        Design: Corner/cross-cutting complexity layers/stale_sire_version_refuses_the_evaluation_and_the_fresh_one_lands
        """
        fx.advance_clock(api, self.PROOF_SEASON)
        subject = fx.register_sire(api, registration_code="REG-OC1")
        maternal_grandsire = fx.register_sire(api, registration_code="REG-OC2")
        version_before_the_correction = subject["version"]

        amended = validate_success(
            api.amend_sire_pedigree(
                subject["id"],
                factories.pedigree_payload(dam_sire_id=maternal_grandsire["id"]),
                fx.DIRECTOR,
            ),
            200,
        )
        assert amended["version"] == version_before_the_correction + 1

        a_version_below_current = api.file_genomic_evaluation(
            subject["id"],
            factories.genomic_evaluation_payload(version_before_the_correction),
            fx.DIRECTOR,
        )
        validate_error(a_version_below_current, STALE_SIRE, 412)

        a_version_above_current = api.file_genomic_evaluation(
            subject["id"],
            factories.genomic_evaluation_payload(amended["version"] + 5),
            fx.DIRECTOR,
        )
        validate_error(a_version_above_current, STALE_SIRE, 412)

        _rows, filed_so_far = validate_paginated(
            api.list_genomic_evaluations(fx.DIRECTOR, {"sire_id": subject["id"]})
        )
        assert filed_so_far["total_count"] == 0
        assert_row_unchanged(
            amended,
            fx.read_sire(api, subject["id"]),
            "pedigree_depth",
            "dam_sire_id",
            "published_composite_index",
        )

        with_the_fresh_pin = validate_success(
            api.file_genomic_evaluation(
                subject["id"],
                factories.genomic_evaluation_payload(amended["version"]),
                fx.DIRECTOR,
            ),
            201,
        )
        assert with_the_fresh_pin["status"] == "DRAFT"
        assert with_the_fresh_pin["sire_id"] == subject["id"]

    def test_the_pin_yields_to_the_existence_check_and_publication_carries_none(self, api):
        """The 412 sits at priority 12, behind the 404s at 8 and 9.

        PRD 2.10: "`expected_sire_version` and `expected_straw_lot_version`
        are compared after existence and uniqueness but **before any state
        precondition**".
        PRD 3.6: hop 1 "increments the bull's `version` by 1", so the pin a
        client held before the proof run is stale afterwards.

        Design: Corner/cross-cutting complexity layers/stale_sire_version_refuses_the_evaluation_and_the_fresh_one_lands
        """
        fx.advance_clock(api, self.PROOF_SEASON)
        subject = fx.register_sire(api, registration_code="REG-OC4")

        fabricated_target = api.file_genomic_evaluation(
            NON_EXISTENT_UUID,
            factories.genomic_evaluation_payload(subject["version"] + 7),
            fx.DIRECTOR,
        )
        validate_error(fabricated_target, NOT_FOUND, 404)

        first_proof = fx.file_evaluation(api, subject["id"])
        version_before_publication = fx.read_sire(api, subject["id"])["version"]
        published = fx.publish_evaluation(api, first_proof["id"])
        assert published["status"] == "PUBLISHED"
        version_after_hop_one = fx.read_sire(api, subject["id"])["version"]
        assert version_after_hop_one == version_before_publication + 1

        pinned_to_the_pre_publication_row = api.file_genomic_evaluation(
            subject["id"],
            factories.genomic_evaluation_payload(version_before_publication),
            fx.DIRECTOR,
        )
        validate_error(pinned_to_the_pre_publication_row, STALE_SIRE, 412)

        second_proof = validate_success(
            api.file_genomic_evaluation(
                subject["id"],
                factories.genomic_evaluation_payload(
                    version_after_hop_one, effective_at=self.LATER_EFFECTIVE_AT
                ),
                fx.DIRECTOR,
            ),
            201,
        )
        promoted = validate_success(
            api.publish_genomic_evaluation(
                second_proof["id"], factories.publish_payload(), fx.DIRECTOR
            ),
            200,
        )
        assert promoted["status"] == "PUBLISHED"
        assert promoted["supersedes_evaluation_id"] == first_proof["id"]
        superseded = validate_success(
            api.get_genomic_evaluation(first_proof["id"], fx.DIRECTOR), 200
        )
        assert superseded["status"] == "SUPERSEDED"


class TestLotVersionPin:
    """PRD 2.7's second pin guards a dose ledger, so a refusal must move nothing."""

    LOT_STRAWS = 150
    LOT_COST_CENTS = 75000
    COMMITTED_DOSES = 10
    REQUESTED_DOSES = 20

    def test_another_actors_acceptance_invalidates_the_pin_and_no_dose_moves(self, api):
        """The version that breaks the pin is bumped by the customer's own answer.

        PRD 2.7: "Its value must equal the target `StrawLot` row's current
        `version`; a mismatch is rejected with `ERR_STALE_STRAW_LOT_VERSION`
        (HTTP 412)."
        PRD 3.9: acceptance "moves `doses_requested` out of the lot's
        `doses_available` and into its `doses_reserved`, and increments the
        lot's `version` by 1."

        Design: Corner/cross-cutting complexity layers/lot_version_pins_the_consignment_request_and_advances_on_every_write
        """
        context = fx.released_lot(
            api,
            registration_code="REG-OC3",
            straw_count=self.LOT_STRAWS,
            processing_cost_cents=self.LOT_COST_CENTS,
        )
        lot_id = context["lot"]["id"]
        fx.published_proof(api, context["sire"]["id"])
        partner = fx.distributor_with_tank(
            api,
            distributor_overrides={"name": "D-OC"},
            tank_overrides={"serial": "TK-OC"},
        )
        herd = fx.register_customer_herd(
            api, partner["distributor"]["id"], herd_name="H-OC"
        )
        recommendation = fx.request_recommendation(
            api, herd["id"], doses_requested=self.COMMITTED_DOSES
        )
        assert recommendation["straw_lot_id"] == lot_id

        before_the_answer = fx.read_lot(api, lot_id)
        fx.decide_recommendation(api, recommendation["id"], "ACCEPTED")
        after_the_answer = fx.read_lot(api, lot_id)
        assert after_the_answer["version"] == before_the_answer["version"] + 1
        assert_buckets(
            after_the_answer,
            self.LOT_STRAWS - self.COMMITTED_DOSES,
            self.COMMITTED_DOSES,
            0,
            0,
            0,
        )

        pinned_to_the_pre_acceptance_lot = api.request_consignment_transfer(
            lot_id,
            factories.consignment_request_payload(
                partner["distributor"]["id"],
                partner["tank"]["id"],
                before_the_answer["version"],
                self.REQUESTED_DOSES,
            ),
            fx.DIRECTOR,
        )
        validate_error(pinned_to_the_pre_acceptance_lot, STALE_LOT, 412)

        untouched = fx.read_lot(api, lot_id)
        assert_buckets(
            untouched,
            self.LOT_STRAWS - self.COMMITTED_DOSES,
            self.COMMITTED_DOSES,
            0,
            0,
            0,
        )
        assert_row_unchanged(
            after_the_answer, untouched, "unit_book_value_cents", "distribution_status"
        )
        _rows, raised_so_far = validate_paginated(
            api.list_consignment_transfers(fx.DIRECTOR, {"straw_lot_id": lot_id})
        )
        assert raised_so_far["total_count"] == 0

        with_the_fresh_pin = validate_success(
            api.request_consignment_transfer(
                lot_id,
                factories.consignment_request_payload(
                    partner["distributor"]["id"],
                    partner["tank"]["id"],
                    after_the_answer["version"],
                    self.REQUESTED_DOSES,
                ),
                fx.DIRECTOR,
            ),
            201,
        )
        assert with_the_fresh_pin["status"] == "REQUESTED"
        after_the_request = fx.read_lot(api, lot_id)
        assert_buckets(
            after_the_request,
            self.LOT_STRAWS - self.COMMITTED_DOSES,
            self.COMMITTED_DOSES,
            0,
            0,
            0,
        )

    def test_every_accepted_write_adds_one_and_reads_never_do(self, api):
        """The counter walks the lot's whole commercial life, one step per write.

        PRD 2.4: "`version` is an integer that starts at 1 on creation and
        increments by exactly 1 on every mutation of that row."
        PRD 2.4: "the `version` of a row a client is holding can advance
        without that client issuing any request".

        Design: Corner/cross-cutting complexity layers/lot_version_pins_the_consignment_request_and_advances_on_every_write
        """
        context = fx.quarantine_lot(
            api,
            registration_code="REG-LV",
            straw_count=self.LOT_STRAWS,
            processing_cost_cents=self.LOT_COST_CENTS,
        )
        lot_id = context["lot"]["id"]
        assert context["lot"]["version"] == 1

        released = fx.release_lot(api, lot_id)
        assert released["version"] == context["lot"]["version"] + 1

        fx.published_proof(api, context["sire"]["id"])
        revalued = fx.read_lot(api, lot_id)
        assert revalued["version"] == released["version"] + 1
        assert revalued["valuation_basis"] == "MARKET_REVALUED"

        partner = fx.distributor_with_tank(
            api,
            distributor_overrides={"name": "D-LV"},
            tank_overrides={"serial": "TK-LV"},
        )
        herd = fx.register_customer_herd(
            api, partner["distributor"]["id"], herd_name="H-LV"
        )
        recommendation = fx.request_recommendation(
            api, herd["id"], doses_requested=self.COMMITTED_DOSES
        )
        fx.decide_recommendation(api, recommendation["id"], "ACCEPTED")
        after_acceptance = fx.read_lot(api, lot_id)
        assert after_acceptance["version"] == revalued["version"] + 1

        transfer = fx.request_consignment(
            api,
            lot_id,
            partner["distributor"]["id"],
            partner["tank"]["id"],
            doses=40,
        )
        fx.approve_transfer(api, transfer["id"])
        after_approval = fx.read_lot(api, lot_id)
        assert after_approval["version"] == after_acceptance["version"] + 1
        assert_buckets(after_approval, 100, 50, 0, 0, 0)

        fx.dispatch_transfer(api, transfer["id"])
        fx.receive_transfer(api, transfer["id"], partner["distributor"]["id"])
        after_receipt = fx.read_lot(api, lot_id)
        assert after_receipt["version"] == after_approval["version"] + 1
        assert_buckets(after_receipt, 100, 10, 40, 0, 0)

        fx.report_usage(api, transfer["id"], partner["distributor"]["id"], 30, doses_returned=10)
        after_reconciliation = fx.read_lot(api, lot_id)
        assert after_reconciliation["version"] == after_receipt["version"] + 1
        assert_buckets(after_reconciliation, 110, 10, 0, 30, 0)

        for _read in range(3):
            assert fx.read_lot(api, lot_id)["version"] == after_reconciliation["version"]
        rows, _meta = validate_paginated(
            api.list_straw_lots(fx.DIRECTOR, {"sire_id": context["sire"]["id"]})
        )
        assert [row["version"] for row in rows] == [after_reconciliation["version"]]


class TestVersionIsSystemOwned:
    """The counter is proved system-owned from both sides: creation and refusal."""

    def test_a_client_supplied_counter_is_ignored_and_writes_drive_it_one_at_a_time(self, api):
        """Version 1 on creation, then one step per accepted write.

        PRD 2.10: "unknown body keys are ignored rather than rejected".
        PRD 2.4: "`version` is an integer that starts at 1 on creation and
        increments by exactly 1 on every mutation of that row."

        Design: Corner/cross-cutting complexity layers/version_is_system_owned_and_never_moves_on_a_refusal
        """
        facility = fx.register_facility(api)
        registered = validate_success(
            api.create_sire(
                factories.sire_payload(registration_code="REG-VS", version=99),
                fx.DIRECTOR,
            ),
            201,
        )
        assert registered["version"] == 1

        contracted = fx.contract_sire(api, registered["id"])
        assert contracted["version"] == 2
        housed = fx.house_sire(api, registered["id"], facility["id"])
        assert housed["version"] == 3

        fx.grant_base_health_currency(api, registered["id"], facility["id"])
        still_in_isolation = fx.read_sire(api, registered["id"])
        assert still_in_isolation["version"] == 3

        fx.advance_clock(api, fx.CLOCK_ISOLATION_SERVED)
        cleared = validate_success(
            api.clear_sire_for_collection(
                registered["id"], factories.clearance_payload(), fx.VET
            ),
            200,
        )
        assert cleared["version"] == 4
        assert cleared["collection_status"] == "ELIGIBLE"
        assert_instant_equals(cleared["created_at"], registered["created_at"])
        assert cleared["updated_at"] != registered["updated_at"]

    def test_no_refusal_of_any_status_family_advances_the_counter(self, api):
        """400, 403, 404, 409, 412 and 422 all leave the row exactly as it stood.

        PRD 2.10 orders the bands, so each refusal below is answered by a
        different gate and none of them is a mutation.
        PRD 2.4: "`version` is an integer that starts at 1 on creation and
        increments by exactly 1 on every mutation of that row."

        Design: Corner/cross-cutting complexity layers/version_is_system_owned_and_never_moves_on_a_refusal
        """
        context = fx.eligible_sire(api, registration_code="REG-VR")
        resident = fx.read_sire(api, context["sire"]["id"])

        an_enum_outside_the_closed_set = api.set_sire_collection_status(
            resident["id"],
            factories.collection_status_payload("HIBERNATING"),
            fx.DIRECTOR,
        )
        validate_error(an_enum_outside_the_closed_set, ApiErrorId.ERR_VALIDATION.value, 400)

        the_wrong_role = api.retire_sire(
            resident["id"], factories.retire_payload(), fx.ADVISOR
        )
        validate_error(the_wrong_role, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

        a_fabricated_target = api.retire_sire(
            NON_EXISTENT_UUID, factories.retire_payload(), fx.DIRECTOR
        )
        validate_error(a_fabricated_target, NOT_FOUND, 404)

        a_second_contract = api.contract_sire(
            resident["id"], factories.contract_payload(), fx.DIRECTOR
        )
        validate_error(
            a_second_contract, ApiErrorId.ERR_SIRE_ACQUISITION_STATE.value, 409
        )

        a_stale_pin = api.file_genomic_evaluation(
            resident["id"],
            factories.genomic_evaluation_payload(resident["version"] - 1),
            fx.DIRECTOR,
        )
        validate_error(a_stale_pin, STALE_SIRE, 412)

        assert_row_unchanged(
            resident,
            fx.read_sire(api, resident["id"]),
            "acquisition_status",
            "collection_status",
            "created_at",
        )

        newcomer = fx.register_sire(api, registration_code="REG-VR2")
        fx.contract_sire(api, newcomer["id"])
        quarantined = fx.house_sire(api, newcomer["id"], context["facility"]["id"])
        fx.grant_base_health_currency(api, newcomer["id"], context["facility"]["id"])
        an_early_clearance = api.clear_sire_for_collection(
            newcomer["id"], factories.clearance_payload(), fx.VET
        )
        validate_error(
            an_early_clearance, ApiErrorId.ERR_ISOLATION_INCOMPLETE.value, 422
        )
        assert_row_unchanged(
            quarantined,
            fx.read_sire(api, newcomer["id"]),
            "collection_status",
            "isolation_ends_at",
        )


class TestRevaluationCascadeOrder:
    """The four-hop cascade of PRD 3.6, read for order sensitivity and atomicity."""

    LOT_STRAWS = 100
    LOT_COST_CENTS = 50000
    SECOND_WINDOW_START = "2026-09-20T08:00:00Z"
    SECOND_WINDOW_END = "2026-09-20T10:00:00Z"

    def test_a_condemnation_before_the_proof_freezes_the_value_and_after_it_does_not(self, api):
        """The same two operations in the other order store a different unit value.

        PRD 3.6: "Lots already in `REJECTED` or `DEPLETED` are never revalued
        and keep whatever unit value they carried when they left the set."
        PRD 3.6: the evaluation's "`revaluation_delta_cents` records the plant
        inventory value immediately after hop 2 minus the plant inventory value
        immediately before it".

        Design: Corner/cross-cutting complexity layers/revaluation_cascade_is_order_sensitive_and_a_refusal_writes_nothing
        """
        context = fx.quarantine_lot(
            api,
            registration_code="REG-CS",
            straw_count=self.LOT_STRAWS,
            processing_cost_cents=self.LOT_COST_CENTS,
        )
        standard_unit = expected_standard_unit_value_cents(
            self.LOT_COST_CENTS, self.LOT_STRAWS
        )
        surviving_lot = context["lot"]
        assert surviving_lot["unit_book_value_cents"] == standard_unit
        assert surviving_lot["valuation_basis"] == "STANDARD_COST"

        condemned_first = fx.cut_lot(
            api,
            context["ejaculate"]["id"],
            "CONVENTIONAL",
            self.LOT_STRAWS,
            self.LOT_COST_CENTS,
        )
        fx.reject_lot(api, condemned_first["id"])
        value_before_the_proof = fx.plant_value(api)
        assert value_before_the_proof == standard_unit * self.LOT_STRAWS

        published = fx.publish_evaluation(
            api, fx.file_evaluation(api, context["sire"]["id"])["id"]
        )
        market_unit = expected_market_unit_value_cents(
            published["composite_index"], "CONVENTIONAL"
        )

        revalued = fx.read_lot(api, surviving_lot["id"])
        assert revalued["unit_book_value_cents"] == market_unit
        assert revalued["valuation_basis"] == "MARKET_REVALUED"
        assert revalued["pre_revaluation_unit_value_cents"] == standard_unit

        left_the_set_first = fx.read_lot(api, condemned_first["id"])
        assert left_the_set_first["unit_book_value_cents"] == standard_unit
        assert left_the_set_first["valuation_basis"] == "STANDARD_COST"
        assert left_the_set_first["pre_revaluation_unit_value_cents"] is None

        assert published["revaluation_delta_cents"] == (
            market_unit * self.LOT_STRAWS - value_before_the_proof
        )
        assert fx.plant_value(api) == market_unit * self.LOT_STRAWS

        mirrored = fx.quarantine_lot(
            api,
            facility=context["facility"],
            registration_code="REG-CS2",
            straw_count=self.LOT_STRAWS,
            processing_cost_cents=self.LOT_COST_CENTS,
            isolation_days=0,
            clearance_clock=None,
            start_at=self.SECOND_WINDOW_START,
            end_at=self.SECOND_WINDOW_END,
            collection_clock=self.SECOND_WINDOW_START,
        )
        mirrored_proof = fx.publish_evaluation(
            api, fx.file_evaluation(api, mirrored["sire"]["id"])["id"]
        )
        mirrored_market_unit = expected_market_unit_value_cents(
            mirrored_proof["composite_index"], "CONVENTIONAL"
        )
        fx.reject_lot(api, mirrored["lot"]["id"])
        left_the_set_second = fx.read_lot(api, mirrored["lot"]["id"])
        assert left_the_set_second["unit_book_value_cents"] == mirrored_market_unit
        assert left_the_set_second["valuation_basis"] == "MARKET_REVALUED"
        assert (
            left_the_set_second["unit_book_value_cents"]
            != left_the_set_first["unit_book_value_cents"]
        )

    def test_a_publication_refused_at_the_state_gate_leaves_all_four_hops_alone(self, api):
        """A second publication of the same row must not half-apply the cascade.

        PRD 3.6: "an evaluation that is neither `DRAFT` nor `SUPERSEDED`
        reports `ERR_EVALUATION_STATE`."
        PRD 2.11: "**Valuation cascades** run from a published proof through
        straw lots to consignments and then to distributor exposure — four
        hops, each of which is described where publication is described."

        Design: Corner/cross-cutting complexity layers/revaluation_cascade_is_order_sensitive_and_a_refusal_writes_nothing
        """
        context = fx.received_consignment(
            api,
            registration_code="REG-CR",
            straw_count=self.LOT_STRAWS,
            processing_cost_cents=self.LOT_COST_CENTS,
            doses=40,
            distributor_overrides={"name": "D-CR"},
            tank_overrides={"serial": "TK-CR"},
        )
        accepted = fx.published_proof(api, context["sire"]["id"])
        market_unit = expected_market_unit_value_cents(
            accepted["composite_index"], "CONVENTIONAL"
        )

        lot_after_hop_two = fx.read_lot(api, context["lot"]["id"])
        transfer_after_hop_three = fx.read_transfer(api, context["transfer"]["id"])
        partner_after_hop_four = fx.read_distributor(api, context["distributor"]["id"])
        sire_after_hop_one = fx.read_sire(api, context["sire"]["id"])
        valuation_after = fx.read_valuation(api)
        assert lot_after_hop_two["unit_book_value_cents"] == market_unit
        assert transfer_after_hop_three["carried_value_cents"] == 40 * market_unit
        assert partner_after_hop_four["consignment_value_cents"] == 40 * market_unit

        a_second_publication = api.publish_genomic_evaluation(
            accepted["id"], factories.publish_payload(), fx.DIRECTOR
        )
        validate_error(
            a_second_publication, ApiErrorId.ERR_EVALUATION_STATE.value, 409
        )

        assert_row_unchanged(
            lot_after_hop_two,
            fx.read_lot(api, context["lot"]["id"]),
            "unit_book_value_cents",
            "valuation_basis",
            "pre_revaluation_unit_value_cents",
        )
        assert_row_unchanged(
            transfer_after_hop_three,
            fx.read_transfer(api, context["transfer"]["id"]),
            "carried_value_cents",
            "status",
        )
        assert_row_unchanged(
            partner_after_hop_four,
            fx.read_distributor(api, context["distributor"]["id"]),
            "consignment_value_cents",
            "outstanding_balance_cents",
            "credit_limit_cents",
        )
        assert_row_unchanged(
            sire_after_hop_one,
            fx.read_sire(api, context["sire"]["id"]),
            "published_composite_index",
            "published_evaluation_effective_at",
            "progeny_daughter_count",
        )
        valuation_now = fx.read_valuation(api)
        for figure in (
            "plant_inventory_value_cents",
            "quarantine_value_cents",
            "released_value_cents",
            "lot_count",
        ):
            assert valuation_now[figure] == valuation_after[figure]

        rows, filed = validate_paginated(
            api.list_genomic_evaluations(fx.DIRECTOR, {"sire_id": context["sire"]["id"]})
        )
        assert filed["total_count"] == 1
        assert [row["status"] for row in rows] == ["PUBLISHED"]
        assert_row_unchanged(
            accepted,
            fx.read_evaluation(api, accepted["id"]),
            "revaluation_delta_cents",
            "published_at",
            "supersedes_evaluation_id",
        )


class TestValueVariantReachesTheDistributor:
    """Hops 3 and 4 carry the basis switch past the row that owns the variant."""

    LOT_STRAWS = 100
    LOT_COST_CENTS = 50000
    CONSIGNED_DOSES = 40
    UNIT_PRICE_CENTS = 4000

    def test_the_switch_travels_two_hops_past_the_lot_and_reverses_in_one_call(self, api):
        """Book value, never the sale price, and the delta reaches the partner.

        PRD 3.8: receipt "sets `carried_value_cents` to the transfer's
        `doses_on_hand` multiplied by the lot's `unit_book_value_cents`".
        PRD 3.6: "**Hop 4**, caused by hop 3, re-derives
        `consignment_value_cents` on every distributor referenced by those
        transfers."

        Design: Corner/cross-cutting complexity layers/lot_value_variant_switch_delta_reaches_the_distributor
        """
        context = fx.received_consignment(
            api,
            registration_code="REG-VD",
            straw_count=self.LOT_STRAWS,
            processing_cost_cents=self.LOT_COST_CENTS,
            doses=self.CONSIGNED_DOSES,
            unit_price_cents=self.UNIT_PRICE_CENTS,
            distributor_overrides={"name": "D-VD"},
            tank_overrides={"serial": "TK-VD"},
        )
        standard_unit = expected_standard_unit_value_cents(
            self.LOT_COST_CENTS, self.LOT_STRAWS
        )
        at_receipt = context["transfer"]
        assert at_receipt["status"] == "RECEIVED"
        assert at_receipt["carried_value_cents"] == self.CONSIGNED_DOSES * standard_unit
        assert (
            at_receipt["carried_value_cents"]
            != self.CONSIGNED_DOSES * self.UNIT_PRICE_CENTS
        )

        partner_before = fx.read_distributor(api, context["distributor"]["id"])
        assert (
            partner_before["consignment_value_cents"]
            == self.CONSIGNED_DOSES * standard_unit
        )
        assert partner_before["outstanding_balance_cents"] == 0
        value_before = fx.plant_value(api)
        assert value_before == standard_unit * self.LOT_STRAWS

        published = fx.publish_evaluation(
            api, fx.file_evaluation(api, context["sire"]["id"])["id"]
        )
        market_unit = expected_market_unit_value_cents(
            published["composite_index"], "CONVENTIONAL"
        )
        assert published["revaluation_delta_cents"] == (
            market_unit * self.LOT_STRAWS - value_before
        )
        assert fx.plant_value(api) == market_unit * self.LOT_STRAWS

        revalued_lot = fx.read_lot(api, context["lot"]["id"])
        assert revalued_lot["unit_book_value_cents"] == market_unit
        assert revalued_lot["valuation_basis"] == "MARKET_REVALUED"
        assert revalued_lot["pre_revaluation_unit_value_cents"] == standard_unit

        after_hop_three = fx.read_transfer(api, context["transfer"]["id"])
        assert after_hop_three["carried_value_cents"] == self.CONSIGNED_DOSES * market_unit
        partner_after = fx.read_distributor(api, context["distributor"]["id"])
        assert (
            partner_after["consignment_value_cents"] == self.CONSIGNED_DOSES * market_unit
        )
        assert (
            partner_after["consignment_value_cents"]
            - partner_before["consignment_value_cents"]
            == self.CONSIGNED_DOSES * (market_unit - standard_unit)
        )
        assert partner_after["credit_limit_cents"] == partner_before["credit_limit_cents"]
        assert partner_after["outstanding_balance_cents"] == 0

        for basis_independent in (
            "doses",
            "unit_price_cents",
            "gross_cents",
            "service_fee_cents",
            "rebate_cents",
            "settlement_total_cents",
        ):
            assert after_hop_three[basis_independent] == at_receipt[basis_independent]

        withdrawn = fx.rollback_evaluation(api, published["id"])
        assert withdrawn["status"] == "ROLLED_BACK"
        restored_lot = fx.read_lot(api, context["lot"]["id"])
        assert restored_lot["unit_book_value_cents"] == standard_unit
        assert restored_lot["valuation_basis"] == "STANDARD_COST"
        assert restored_lot["pre_revaluation_unit_value_cents"] is None
        assert (
            fx.read_transfer(api, context["transfer"]["id"])["carried_value_cents"]
            == self.CONSIGNED_DOSES * standard_unit
        )
        assert (
            fx.read_distributor(api, context["distributor"]["id"])[
                "consignment_value_cents"
            ]
            == self.CONSIGNED_DOSES * standard_unit
        )
        assert fx.plant_value(api) == value_before


class TestPlantValuationReconciles:
    """The derived report of PRD 3.5, read against four kinds of source change."""

    LOT_STRAWS = 100
    LOT_COST_CENTS = 50000
    FIRST_CONSIGNMENT = 40

    def test_a_new_row_a_bucket_move_and_a_revaluation_each_land_in_the_report(self, api):
        """Cutting adds, release moves buckets, publication re-prices, use reduces.

        PRD 3.5: "It reports `plant_inventory_value_cents`, the sum over every
        lot whose `distribution_status` is `QUARANTINE` or `RELEASED` of that
        lot's `unit_book_value_cents` multiplied by the sum of its
        `doses_available`, `doses_reserved` and `doses_consigned`."
        PRD 3.5: "`quarantine_value_cents` is that same sum restricted to lots
        in `QUARANTINE`, `released_value_cents` the same sum restricted to lots
        in `RELEASED`, and `lot_count` the number of rows in the source set."

        Design: Corner/cross-cutting complexity layers/plant_valuation_reconciles_after_create_release_revalue_and_removal
        """
        context = fx.accepted_ejaculate(api, registration_code="REG-RV")
        standard_unit = expected_standard_unit_value_cents(
            self.LOT_COST_CENTS, self.LOT_STRAWS
        )

        empty_plant = fx.read_valuation(api)
        assert empty_plant["plant_inventory_value_cents"] == 0
        assert empty_plant["quarantine_value_cents"] == 0
        assert empty_plant["released_value_cents"] == 0
        assert empty_plant["lot_count"] == 0

        lot = fx.cut_lot(
            api,
            context["ejaculate"]["id"],
            "CONVENTIONAL",
            self.LOT_STRAWS,
            self.LOT_COST_CENTS,
        )
        after_cutting = fx.read_valuation(api)
        assert after_cutting["lot_count"] == 1
        assert after_cutting["quarantine_value_cents"] == standard_unit * self.LOT_STRAWS
        assert after_cutting["released_value_cents"] == 0
        assert (
            after_cutting["plant_inventory_value_cents"]
            == standard_unit * self.LOT_STRAWS
        )

        fx.release_lot(api, lot["id"])
        after_release = fx.read_valuation(api)
        assert after_release["quarantine_value_cents"] == 0
        assert after_release["released_value_cents"] == standard_unit * self.LOT_STRAWS
        assert (
            after_release["plant_inventory_value_cents"]
            == after_cutting["plant_inventory_value_cents"]
        )
        assert after_release["lot_count"] == 1

        published = fx.publish_evaluation(
            api, fx.file_evaluation(api, context["sire"]["id"])["id"]
        )
        market_unit = expected_market_unit_value_cents(
            published["composite_index"], "CONVENTIONAL"
        )
        after_the_proof = fx.read_valuation(api)
        assert after_the_proof["released_value_cents"] == market_unit * self.LOT_STRAWS
        assert (
            after_the_proof["plant_inventory_value_cents"]
            == market_unit * self.LOT_STRAWS
        )
        assert after_the_proof["lot_count"] == 1

        partner = fx.distributor_with_tank(
            api,
            distributor_overrides={"name": "D-RV"},
            tank_overrides={"serial": "TK-RV"},
        )
        transfer = fx.request_consignment(
            api,
            lot["id"],
            partner["distributor"]["id"],
            partner["tank"]["id"],
            doses=self.FIRST_CONSIGNMENT,
        )
        fx.approve_transfer(api, transfer["id"])
        while_reserved = fx.read_valuation(api)
        assert (
            while_reserved["plant_inventory_value_cents"]
            == market_unit * self.LOT_STRAWS
        )
        fx.dispatch_transfer(api, transfer["id"])
        fx.receive_transfer(api, transfer["id"], partner["distributor"]["id"])
        while_consigned = fx.read_valuation(api)
        assert (
            while_consigned["plant_inventory_value_cents"]
            == market_unit * self.LOT_STRAWS
        )

        fx.report_usage(
            api, transfer["id"], partner["distributor"]["id"], self.FIRST_CONSIGNMENT
        )
        remaining = self.LOT_STRAWS - self.FIRST_CONSIGNMENT
        after_consumption = fx.read_valuation(api)
        assert after_consumption["released_value_cents"] == market_unit * remaining
        assert (
            after_consumption["plant_inventory_value_cents"] == market_unit * remaining
        )
        assert after_consumption["lot_count"] == 1
        assert fx.read_lot(api, lot["id"])["distribution_status"] == "RELEASED"

    def test_a_condemned_lot_and_a_depleted_lot_both_leave_the_source_set(self, api):
        """Removal is the fourth kind of change, and the stored unit value survives it.

        PRD 3.5: "lots in `REJECTED` or `DEPLETED` are excluded from the source
        set altogether even though their stored unit value survives."
        PRD 3.8: reconciliation leaves "a lot whose `doses_available`,
        `doses_reserved` and `doses_consigned` have all reached 0" moving
        "`RELEASED → DEPLETED`".

        Design: Corner/cross-cutting complexity layers/plant_valuation_reconciles_after_create_release_revalue_and_removal
        """
        context = fx.accepted_ejaculate(api, registration_code="REG-RM")
        standard_unit = expected_standard_unit_value_cents(
            self.LOT_COST_CENTS, self.LOT_STRAWS
        )
        keeper = fx.cut_lot(
            api,
            context["ejaculate"]["id"],
            "CONVENTIONAL",
            self.LOT_STRAWS,
            self.LOT_COST_CENTS,
        )
        condemned = fx.cut_lot(
            api,
            context["ejaculate"]["id"],
            "CONVENTIONAL",
            self.LOT_STRAWS,
            self.LOT_COST_CENTS,
        )
        both_in_quarantine = fx.read_valuation(api)
        assert both_in_quarantine["lot_count"] == 2
        assert (
            both_in_quarantine["quarantine_value_cents"]
            == 2 * standard_unit * self.LOT_STRAWS
        )

        fx.reject_lot(api, condemned["id"])
        after_condemnation = fx.read_valuation(api)
        assert after_condemnation["lot_count"] == 1
        assert (
            after_condemnation["quarantine_value_cents"]
            == standard_unit * self.LOT_STRAWS
        )
        rejected_row = fx.read_lot(api, condemned["id"])
        assert rejected_row["distribution_status"] == "REJECTED"
        assert rejected_row["unit_book_value_cents"] == standard_unit
        assert_buckets(rejected_row, 0, 0, 0, 0, self.LOT_STRAWS)

        fx.release_lot(api, keeper["id"])
        partner = fx.distributor_with_tank(
            api,
            distributor_overrides={"name": "D-RM"},
            tank_overrides={"serial": "TK-RM"},
        )
        transfer = fx.request_consignment(
            api,
            keeper["id"],
            partner["distributor"]["id"],
            partner["tank"]["id"],
            doses=self.LOT_STRAWS,
        )
        fx.approve_transfer(api, transfer["id"])
        fx.dispatch_transfer(api, transfer["id"])
        fx.receive_transfer(api, transfer["id"], partner["distributor"]["id"])
        fx.report_usage(
            api, transfer["id"], partner["distributor"]["id"], self.LOT_STRAWS
        )

        depleted_row = fx.read_lot(api, keeper["id"])
        assert depleted_row["distribution_status"] == "DEPLETED"
        assert depleted_row["unit_book_value_cents"] == standard_unit
        emptied_plant = fx.read_valuation(api)
        assert emptied_plant["lot_count"] == 0
        assert emptied_plant["plant_inventory_value_cents"] == 0
        assert emptied_plant["quarantine_value_cents"] == 0
        assert emptied_plant["released_value_cents"] == 0


class TestDistributorExposureReconciles:
    """The two exposure aggregates of PRD 3.8 hand over at exactly one transition."""

    LOT_STRAWS = 150
    LOT_COST_CENTS = 75000
    CONSIGNED_DOSES = 40
    UNIT_PRICE_CENTS = 4000
    DOSES_USED = 25
    DOSES_RETURNED = 15
    REFILL_PCT = 96.0

    def test_the_two_halves_hand_over_at_reconciliation_without_double_counting(self, api):
        """Only RECEIVED feeds the consignment half; only RECONCILED feeds the balance.

        PRD 3.8: "`consignment_value_cents` is the sum, over the partner's
        consignments whose `status` is `RECEIVED`, of each transfer's
        `doses_on_hand` multiplied by its lot's `unit_book_value_cents`."
        PRD 3.8: "Consignments in `REQUESTED`, `APPROVED`, `IN_TRANSIT`,
        `REJECTED` or `RETURNED` contribute nothing to any of the three."

        Design: Corner/cross-cutting complexity layers/distributor_exposure_reconciles_across_the_transfer_lifecycle
        """
        context = fx.received_consignment(
            api,
            stop_after="REQUESTED",
            registration_code="REG-EX",
            straw_count=self.LOT_STRAWS,
            processing_cost_cents=self.LOT_COST_CENTS,
            doses=self.CONSIGNED_DOSES,
            unit_price_cents=self.UNIT_PRICE_CENTS,
            distributor_overrides={"name": "D-EX"},
            tank_overrides={"serial": "TK-EX"},
        )
        unit = expected_standard_unit_value_cents(self.LOT_COST_CENTS, self.LOT_STRAWS)
        partner_id = context["distributor"]["id"]
        transfer_id = context["transfer"]["id"]

        def exposure_now():
            return fx.read_distributor(api, partner_id)

        while_requested = exposure_now()
        assert while_requested["consignment_value_cents"] == 0
        assert while_requested["outstanding_balance_cents"] == 0
        assert while_requested["cumulative_doses_used"] == 0

        fx.approve_transfer(api, transfer_id)
        assert exposure_now()["consignment_value_cents"] == 0
        fx.dispatch_transfer(api, transfer_id)
        assert exposure_now()["consignment_value_cents"] == 0

        received = fx.receive_transfer(api, transfer_id, partner_id)
        assert received["doses_on_hand"] == self.CONSIGNED_DOSES
        assert received["carried_value_cents"] == self.CONSIGNED_DOSES * unit
        at_receipt = exposure_now()
        assert at_receipt["consignment_value_cents"] == self.CONSIGNED_DOSES * unit
        assert at_receipt["outstanding_balance_cents"] == 0
        assert at_receipt["cumulative_doses_used"] == 0

        fx.service_tank(api, context["tank"]["id"], self.REFILL_PCT)
        assert fx.read_tank(api, context["tank"]["id"])["service_count"] == 1

        reconciled = fx.report_usage(
            api,
            transfer_id,
            partner_id,
            self.DOSES_USED,
            doses_returned=self.DOSES_RETURNED,
        )
        expected = expected_settlement(self.DOSES_USED, self.UNIT_PRICE_CENTS, 1)
        assert reconciled["status"] == "RECONCILED"
        assert_settlement(reconciled, expected)
        assert reconciled["doses_on_hand"] == 0
        assert reconciled["carried_value_cents"] == 0

        after_the_handover = exposure_now()
        assert after_the_handover["consignment_value_cents"] == 0
        assert (
            after_the_handover["outstanding_balance_cents"]
            == expected["settlement_total_cents"]
        )
        assert after_the_handover["cumulative_doses_used"] == self.DOSES_USED
        assert (
            after_the_handover["consignment_value_cents"]
            + after_the_handover["outstanding_balance_cents"]
            == expected["settlement_total_cents"]
        )
        assert_buckets(
            fx.read_lot(api, context["lot"]["id"]),
            self.LOT_STRAWS - self.CONSIGNED_DOSES + self.DOSES_RETURNED,
            0,
            0,
            self.DOSES_USED,
            0,
        )

    def test_a_returned_or_rejected_consignment_feeds_neither_half(self, api):
        """The compensating ending bills nothing and leaves both figures at 0.

        PRD 3.8: a return "moves those doses out of the lot's `doses_consigned`
        and back into `doses_available`, zeroes `carried_value_cents`,
        re-derives the partner's `consignment_value_cents`".
        PRD 3.8: "`settlement_total_cents` stays null: nothing is billed."

        Design: Corner/cross-cutting complexity layers/distributor_exposure_reconciles_across_the_transfer_lifecycle
        """
        context = fx.received_consignment(
            api,
            registration_code="REG-EXR",
            straw_count=self.LOT_STRAWS,
            processing_cost_cents=self.LOT_COST_CENTS,
            doses=self.CONSIGNED_DOSES,
            unit_price_cents=self.UNIT_PRICE_CENTS,
            distributor_overrides={"name": "D-EXR"},
            tank_overrides={"serial": "TK-EXR"},
        )
        unit = expected_standard_unit_value_cents(self.LOT_COST_CENTS, self.LOT_STRAWS)
        partner_id = context["distributor"]["id"]
        assert (
            fx.read_distributor(api, partner_id)["consignment_value_cents"]
            == self.CONSIGNED_DOSES * unit
        )

        returned = fx.return_transfer(api, context["transfer"]["id"], partner_id)
        assert returned["status"] == "RETURNED"
        assert returned["doses_returned"] == self.CONSIGNED_DOSES
        assert returned["carried_value_cents"] == 0
        assert returned["settlement_total_cents"] is None
        after_the_return = fx.read_distributor(api, partner_id)
        assert after_the_return["consignment_value_cents"] == 0
        assert after_the_return["outstanding_balance_cents"] == 0
        assert after_the_return["cumulative_doses_used"] == 0
        assert_buckets(
            fx.read_lot(api, context["lot"]["id"]), self.LOT_STRAWS, 0, 0, 0, 0
        )

        second_attempt = fx.request_consignment(
            api,
            context["lot"]["id"],
            partner_id,
            context["tank"]["id"],
            doses=self.DOSES_USED,
        )
        refused_by_the_plant = validate_success(
            api.reject_consignment_transfer(
                second_attempt["id"], factories.transfer_reject_payload(), fx.DIRECTOR
            ),
            200,
        )
        assert refused_by_the_plant["status"] == "REJECTED"
        after_the_rejection = fx.read_distributor(api, partner_id)
        assert after_the_rejection["consignment_value_cents"] == 0
        assert after_the_rejection["outstanding_balance_cents"] == 0
        assert after_the_rejection["cumulative_doses_used"] == 0
        assert_buckets(
            fx.read_lot(api, context["lot"]["id"]), self.LOT_STRAWS, 0, 0, 0, 0
        )
