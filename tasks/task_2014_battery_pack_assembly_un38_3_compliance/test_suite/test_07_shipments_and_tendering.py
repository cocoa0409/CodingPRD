"""Transport shipments: tendering, dual-variant carrier charge, carrier decisions,
attachment exclusion, and terminal-state lockdown."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    attach_pack,
    create_attach_pack_payload,
    create_shipment,
    get_battery_pack,
    get_shipment,
    make_carrier_agent_headers,
    setup_delivered_pack,
    setup_picked_pack,
    setup_tendered_shipment,
    tender_shipment,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestTenderBoundary:
    def test_empty_shipment_tender_rejected(self, api):
        """PRD §3.8: "The shipment must be `DRAFT` and must contain at least one pack —
        an empty tender is rejected with `ERR_SHIPMENT_EMPTY`".

        Design: Difficulty/boundary_precision_check/shipment_empty_pack_count_zero_boundary
        """
        bundle = setup_picked_pack()
        program_id = bundle["program"]["id"]
        shipment = create_shipment(program_id, un_class_code="UN3480", declared_weight_kg=1.0)
        resp = api.tender_shipment(
            program_id, shipment["id"], TEST_USERS["logistics_coordinator_headers"]
        )
        validate_error(resp, ApiErrorId.ERR_SHIPMENT_EMPTY)
        shipment_after = get_shipment(program_id, shipment["id"])
        assert shipment_after["status"] == "DRAFT"
        assert shipment_after["total_pack_count"] == 0

    def test_tender_succeeds_with_one_pack(self, api):
        """PRD §3.8: "The shipment must be `DRAFT` and must contain at least one pack —
        an empty tender is rejected with `ERR_SHIPMENT_EMPTY` — and the UN-class agreement
        of every attached pack is re-verified (`ERR_UN_CLASS_MISMATCH`). Tendering moves
        the shipment `DRAFT` → `TENDERED`". A shipment with one attached pack tenders
        successfully.

        Design: Difficulty/boundary_precision_check/shipment_empty_pack_count_zero_boundary
        """
        bundle = setup_picked_pack()
        program_id = bundle["program"]["id"]
        shipment = create_shipment(program_id, un_class_code="UN3480", declared_weight_kg=1.0)
        attach_pack(program_id, shipment["id"], bundle["pack"]["id"])
        tendered = tender_shipment(program_id, shipment["id"])
        assert tendered["status"] == "TENDERED"
        assert tendered["total_pack_count"] == 1


class TestCarrierChargeDualVariant:
    def test_provisional_charge_at_tender(self, api):
        """PRD §3.8: "The charge is tiered on `total_wh`: the first 500 watt-hours price
        at $0.12 per watt-hour, the portion above 500 up to 2000 watt-hours at $0.09, the
        portion above 2000 up to 5000 watt-hours at $0.06, and any portion beyond 5000
        watt-hours at $0.04. A weight surcharge of forty cents per kilogram of
        `declared_weight_kg` is added to the watt-hour component, and the combined dollar
        amount is then multiplied by the dangerous-goods multiplier of the shipment's
        `un_class_code` — 1.25 for `UN3480`, 1.15 for `UN3481`, 1.35 for `UN3090`, and
        1.20 for `UN3091` — before being converted to cents and rounded half-up to a whole
        number of cents."
        43.20 Wh at $0.12 = $5.184; 10.00 kg at $0.40 = $4.00; $9.184 x 1.25 = $11.48
        → 1148 cents.

        Design: Difficulty/dual_variant_calc/carrier_charge_provisional_vs_final_diverge_on_weight_patch
        """
        bundle = setup_tendered_shipment(un_class_code="UN3480", declared_weight_kg=10.00)
        assert bundle["shipment"]["status"] == "TENDERED"
        assert bundle["shipment"]["carrier_charge_cents"] == 1148

    def test_final_charge_recomputed_on_weight_override(self, api):
        """PRD §3.8: "A `CarrierAgent` accepts a `TENDERED` shipment (any other state
        yields `ERR_SHIPMENT_NOT_TENDERED`), optionally supplying a corrected
        `declared_weight_kg` that overrides the tendered figure; acceptance recomputes the
        charge under its final variant — idempotent over the same stored fields, but
        reflecting any weight override — and moves the shipment `TENDERED` →
        `CARRIER_ACCEPTED`."
        With the weight patched to 25.50 kg: $5.184 + $10.20 = $15.384; x 1.25 = $19.23
        → 1923 cents.

        Design: Difficulty/dual_variant_calc/carrier_charge_provisional_vs_final_diverge_on_weight_patch
        """
        bundle = setup_tendered_shipment(un_class_code="UN3480", declared_weight_kg=10.00)
        program_id = bundle["program"]["id"]
        shipment_id = bundle["shipment"]["id"]
        assert bundle["shipment"]["carrier_charge_cents"] == 1148
        resp = api.carrier_accept_shipment(
            program_id, shipment_id, {"declared_weight_kg": 25.50},
            TEST_USERS["carrier_agent_headers"],
        )
        accepted = validate_success(resp, 200)
        assert accepted["status"] == "CARRIER_ACCEPTED"
        assert accepted["declared_weight_kg"] == pytest.approx(25.50)
        assert accepted["carrier_charge_cents"] == 1923
        assert get_shipment(program_id, shipment_id)["carrier_charge_cents"] == 1923


class TestCarrierChargeRoundingOrder:
    def test_rounding_applied_once_after_multiplier(self, api):
        """PRD §3.8: "A weight surcharge of forty cents per kilogram of
        `declared_weight_kg` is added to the watt-hour component, and the combined dollar
        amount is then multiplied by the dangerous-goods multiplier of the shipment's
        `un_class_code` — 1.25 for `UN3480`, 1.15 for `UN3481`, 1.35 for `UN3090`, and
        1.20 for `UN3091` — before being converted to cents and rounded half-up to a whole
        number of cents."
        43.20 Wh at $0.12 = $5.184; 7.76 kg at $0.40 = $3.104; $8.288 x 1.25 (UN3480)
        = $10.36 → 1036 cents (rounding each component first would yield 1035).
        UN3480 is used because it is the only shipping classification a PASS dossier
        can produce through PRD-declared inputs (§3.6 names a pack "chemistry flag"
        that no endpoint or entity field supplies).

        Design: Difficulty/combinatorial_formula/carrier_charge_nested_rounding_order_mode_b
        """
        bundle = setup_tendered_shipment(un_class_code="UN3480", declared_weight_kg=7.76)
        assert bundle["shipment"]["carrier_charge_cents"] == 1036

    def test_tendered_shipment_reports_totals_and_status(self, api):
        """PRD §3.8: "Tendering moves the shipment `DRAFT` → `TENDERED` and computes the
        provisional `carrier_charge_cents`."
        PRD §3.8: "increments the shipment's `total_pack_count` by 1, adds the pack's
        `pack_energy_wh` to `total_wh`".

        Design: Difficulty/combinatorial_formula/carrier_charge_nested_rounding_order_mode_b
        """
        bundle = setup_tendered_shipment(un_class_code="UN3480", declared_weight_kg=7.76)
        program_id = bundle["program"]["id"]
        shipment = get_shipment(program_id, bundle["shipment"]["id"])
        assert shipment["status"] == "TENDERED"
        assert shipment["total_pack_count"] == 1
        assert shipment["total_wh"] == pytest.approx(43.20)
        assert shipment["carrier_charge_cents"] == 1036


class TestCarrierRejectCascade:
    def test_reject_returns_shipment_to_draft(self, api):
        """PRD §3.8: "Rejection, also by the `CarrierAgent` and also requiring
        `TENDERED`, moves the shipment to `CARRIER_REJECTED`, from which it automatically
        returns to `DRAFT` for a re-tender cycle while the attached packs remain
        `PACKED_FOR_SHIP`."

        Design: Difficulty/transitive_cascade/carrier_reject_cascades_shipment_status_and_pack_retention
        """
        bundle = setup_tendered_shipment()
        program_id = bundle["program"]["id"]
        shipment_id = bundle["shipment"]["id"]
        resp = api.carrier_reject_shipment(
            program_id, shipment_id, TEST_USERS["carrier_agent_headers"]
        )
        validate_success(resp, 200)
        assert get_shipment(program_id, shipment_id)["status"] == "DRAFT"

    def test_reject_retains_packs_packed_for_ship(self, api):
        """PRD §3.8: "Rejection, also by the `CarrierAgent` and also requiring
        `TENDERED`, moves the shipment to `CARRIER_REJECTED`, from which it automatically
        returns to `DRAFT` for a re-tender cycle while the attached packs remain
        `PACKED_FOR_SHIP`."

        Design: Difficulty/transitive_cascade/carrier_reject_cascades_shipment_status_and_pack_retention
        """
        bundle = setup_tendered_shipment()
        program_id = bundle["program"]["id"]
        shipment_id = bundle["shipment"]["id"]
        validate_success(
            api.carrier_reject_shipment(program_id, shipment_id, TEST_USERS["carrier_agent_headers"]),
            200,
        )
        pack = get_battery_pack(program_id, bundle["pack"]["id"])
        assert pack["logistics_status"] == "PACKED_FOR_SHIP"
        assert pack["assembly_status"] == "READY_TO_STORE"
        links, _ = validate_paginated(
            api.list_shipment_packs(program_id, shipment_id, TEST_USERS["any_headers"])
        )
        assert len(links) == 1
        assert links[0]["battery_pack_id"] == bundle["pack"]["id"]


class TestAttachmentExclusion:
    def _two_draft_shipments_sharing_a_pack(self, api):
        bundle = setup_picked_pack()
        program_id = bundle["program"]["id"]
        pack_id = bundle["pack"]["id"]
        shipment1 = create_shipment(program_id, carrier_code="DHL-DG", declared_weight_kg=5.00)
        attach_pack(program_id, shipment1["id"], pack_id)
        shipment2 = create_shipment(program_id, carrier_code="FEDEX-DG", declared_weight_kg=3.00)
        return bundle, program_id, pack_id, shipment1, shipment2

    def test_second_attach_rejected_while_packed_for_ship(self, api):
        """PRD §3.8: "Attaching requires the pack's logistics axis to be `PICKED`
        (`ERR_PACK_NOT_PICKED`), the shipment to be `DRAFT` (`ERR_SHIPMENT_NOT_DRAFT`),
        the pack's `shipping_classification` to equal the shipment's `un_class_code`
        (`ERR_UN_CLASS_MISMATCH`), and the pack to be free of any other non-terminal
        shipment (`ERR_PACK_ALREADY_ATTACHED`)." Once the first attach moves the pack to
        `PACKED_FOR_SHIP`, a second attach hits the state precondition first (PRD §2.12
        orders resource-state preconditions at step 5, ahead of the attachment rule at
        step 15).

        Design: Difficulty/resource_temporal_overlap/pack_exclusion_from_double_attachment_via_nonterminal_shipment
        """
        bundle, program_id, pack_id, shipment1, shipment2 = self._two_draft_shipments_sharing_a_pack(api)
        resp = api.attach_shipment_pack(
            program_id, shipment2["id"], create_attach_pack_payload(pack_id),
            TEST_USERS["logistics_coordinator_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_PACK_NOT_PICKED)

    def test_second_shipment_stays_empty_after_failed_attach(self, api):
        """PRD §3.8: "Attaching requires the pack's logistics axis to be `PICKED`
        (`ERR_PACK_NOT_PICKED`) ... and the pack to be free of any other non-terminal
        shipment (`ERR_PACK_ALREADY_ATTACHED`). A successful attach ... moves the pack
        `PICKED` → `PACKED_FOR_SHIP`." The refused second attach leaves the second
        shipment empty and the first attachment intact.

        Design: Difficulty/resource_temporal_overlap/pack_exclusion_from_double_attachment_via_nonterminal_shipment
        """
        bundle, program_id, pack_id, shipment1, shipment2 = self._two_draft_shipments_sharing_a_pack(api)
        resp = api.attach_shipment_pack(
            program_id, shipment2["id"], create_attach_pack_payload(pack_id),
            TEST_USERS["logistics_coordinator_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_PACK_NOT_PICKED)
        links2, _ = validate_paginated(
            api.list_shipment_packs(program_id, shipment2["id"], TEST_USERS["any_headers"])
        )
        assert len(links2) == 0
        assert get_shipment(program_id, shipment2["id"])["total_pack_count"] == 0
        pack = get_battery_pack(program_id, pack_id)
        assert pack["logistics_status"] == "PACKED_FOR_SHIP"
        links1, _ = validate_paginated(
            api.list_shipment_packs(program_id, shipment1["id"], TEST_USERS["any_headers"])
        )
        assert len(links1) == 1


class TestUnClassAgreement:
    def test_attach_rejected_on_un_class_mismatch(self, api):
        """PRD §3.8: "Attaching requires the pack's logistics axis to be `PICKED`
        (`ERR_PACK_NOT_PICKED`), the shipment to be `DRAFT` (`ERR_SHIPMENT_NOT_DRAFT`),
        the pack's `shipping_classification` to equal the shipment's `un_class_code`
        (`ERR_UN_CLASS_MISMATCH`)".

        Design: Corner/validations/un_class_mismatch_on_attach
        """
        bundle = setup_picked_pack()
        program_id = bundle["program"]["id"]
        shipment = create_shipment(program_id, un_class_code="UN3090", declared_weight_kg=5.00)
        resp = api.attach_shipment_pack(
            program_id, shipment["id"], create_attach_pack_payload(bundle["pack"]["id"]),
            TEST_USERS["logistics_coordinator_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_UN_CLASS_MISMATCH)
        assert get_shipment(program_id, shipment["id"])["total_pack_count"] == 0


class TestShipmentTerminalLockdown:
    def test_mark_in_transit_rejected_after_delivered(self, api):
        """PRD §3.8: "Once accepted, the `CarrierAgent` marks the shipment in transit —
        requiring `CARRIER_ACCEPTED` (`ERR_SHIPMENT_NOT_CARRIER_ACCEPTED`)" and final
        delivery "moves the shipment to its terminal `DELIVERED` state".

        Design: Corner/state_machines/shipment_terminal_delivered_no_further_transitions
        """
        bundle = setup_delivered_pack()
        program_id = bundle["program"]["id"]
        shipment_id = bundle["shipment"]["id"]
        assert bundle["shipment"]["status"] == "DELIVERED"
        resp = api.mark_shipment_in_transit(
            program_id, shipment_id, TEST_USERS["carrier_agent_headers"]
        )
        validate_error(resp, ApiErrorId.ERR_SHIPMENT_NOT_CARRIER_ACCEPTED)
        assert get_shipment(program_id, shipment_id)["status"] == "DELIVERED"


class TestTenderRoleGate:
    def test_carrier_agent_cannot_tender(self, api):
        """PRD §2.1: "An authenticated operator who attempts an operation reserved for a
        different role is rejected with `ERR_INSUFFICIENT_PERMISSIONS`."
        PRD §3.8: "Tendering offers the shipment to the carrier." — the tender act itself
        belongs to the `LogisticsCoordinator` (see the endpoint table in §4), not the
        `CarrierAgent`.

        Design: Corner/rbac/carrier_agent_cannot_tender
        """
        bundle = setup_picked_pack()
        program_id = bundle["program"]["id"]
        shipment = create_shipment(program_id, declared_weight_kg=5.00)
        attach_pack(program_id, shipment["id"], bundle["pack"]["id"])
        resp = api.tender_shipment(
            program_id, shipment["id"], make_carrier_agent_headers("ca-1")
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
        assert get_shipment(program_id, shipment["id"])["status"] == "DRAFT"
