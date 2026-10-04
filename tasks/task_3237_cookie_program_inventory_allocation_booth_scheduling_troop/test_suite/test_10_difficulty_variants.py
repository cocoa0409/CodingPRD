"""Second (orthogonal) test per difficulty-design instance."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    add_product,
    add_site,
    create_active_recall,
    create_agreement,
    create_and_confirm_order,
    create_and_place_po,
    create_and_submit_order,
    create_booth_location_payload,
    create_booth_slot_payload,
    create_digital_order,
    create_season,
    create_transfer,
    create_troop_with_account,
    deliver_po,
    get_account,
    get_agreement,
    get_digital_order,
    get_order,
    get_season,
    get_site,
    get_transfer,
    make_council_admin_headers,
    open_season,
    set_clock,
    setup_booth_arena,
    setup_open_season_with_supply,
    setup_reconciliation_season,
    setup_selling_season,
    validate_error,
    validate_success,
)


class TestDualVariantCalcSecond:
    def test_attainment_provisional_vs_final_gate_uses_confirmed_only(self, api):
        """PRD §3.3: "Season summary reads additionally expose a provisional
        attainment that counts both confirmed and pending commitments in the
        numerator — useful while orders are still `SUBMITTED` — but this
        provisional figure is never used for the selling gate; the gate and all
        post-selling reporting use the confirmed-only final attainment, which
        for identical data is always the lower of the two whenever pending
        orders exist."

        Design: Difficulty/dual_variant_calc/attainment_provisional_vs_final_season_domain
        """
        admin = make_council_admin_headers()
        # purchased 200, confirm 120 (60.00) then submit 60 -> provisional 90.00
        # but the gate reads final-only, so the season stays OPEN.
        ctx = setup_open_season_with_supply(200, admin=admin)
        season, product = ctx["season"], ctx["product"]
        troop, account, leader = create_troop_with_account(season["id"], admin=admin)
        set_clock("2027-01-10T00:00:00Z", admin=admin)
        create_and_confirm_order(season["id"], troop, [(product["id"], 120)],
                                 leader=leader, admin=admin)
        create_and_submit_order(season["id"], troop, [(product["id"], 60)], leader=leader)
        read = get_season(season["id"], admin=admin)
        assert read["forecast_attainment_pct"] == 60.00
        assert read["pending_commit_units"] == 60
        assert read["initial_commit_units"] == 120
        assert read["status"] == "OPEN"

    def test_proceeds_settlement_offset_subtracts_from_balance(self, api):
        """PRD §3.9: "for each troop account, the offset is the lesser of the
        account's `proceeds_accrued_cents` and the positive part of its
        `balance_cents`; the offset is subtracted from `balance_cents`, and
        whatever proceeds remain beyond the offset become the
        `proceeds_payable_cents` owed back to the troop."

        Design: Difficulty/dual_variant_calc/proceeds_settlement_offset_vs_payable_troop_domain
        """
        admin = make_council_admin_headers()
        ctx = setup_reconciliation_season(purchase_qty=150, confirm_qty=120, admin=admin)
        season, account = ctx["season"], ctx["account"]
        close_out = validate_success(api.close_out_season(season["id"], admin))
        assert close_out["total_proceeds_offset_cents"] == 12000
        acct = get_account(account["id"], admin=admin)
        assert acct["balance_cents"] == 60000
        assert get_season(season["id"], admin=admin)["status"] == "CLOSED"


class TestCombinatorialFormulaSecond:
    def test_digital_order_total_donation_avg_pins_at_creation(self, api):
        """PRD §3.6: "The donation portion prices each donated package at the
        season's average unit price: the sum of `unit_price_cents` over all of
        the season's products, divided by the product count, rounded half-up to
        a whole cent, and only then multiplied by `donation_units`."

        Design: Difficulty/combinatorial_formula/digital_order_total_mode_a_nonlinear_donation_blend
        """
        admin = make_council_admin_headers()
        ctx = setup_selling_season(
            purchase_qty=1000, confirm_qty=800, admin=admin, unit_price_cents=600,
        )
        season, product_tm = ctx["season"], ctx["product"]
        add_product(
            season["id"], admin=admin, variety_code="SD", name="Samoas",
            unit_price_cents=700, troop_proceeds_cents=110, packages_per_case=1,
        )
        order = create_digital_order(
            season["id"], ctx["troop"],
            [{"product_id": product_tm["id"], "package_qty": 12}],
            leader=ctx["leader"], donation_units=3,
        )
        # 12*600 + 3 * round_half_up((600+700)/2) = 7200 + 1950.
        assert order["total_amount_cents"] == 9150

    def test_closeout_waterfall_forfeits_then_offsets(self, api):
        """PRD §3.9: "First, the forfeiture sweep: every agreement still
        `PENDING` or `DISPUTED` is moved to `FORFEITED` and its
        `outstanding_cents` posted as a charge against its troop's account.
        Second — only after those charges have landed — the proceeds waterfall".
        PRD §3.9: "Swapping this order would change balances whenever proceeds
        fall short of charges, which is why forfeiture always posts first."

        Design: Difficulty/combinatorial_formula/closeout_waterfall_mode_c_order_pinned_forfeit_then_offset
        """
        admin = make_council_admin_headers()
        ctx = setup_reconciliation_season(purchase_qty=150, confirm_qty=120, admin=admin)
        season, account = ctx["season"], ctx["account"]
        agreement = create_agreement(
            season["id"], ctx["troop"], leader=ctx["leader"],
            assigned_packages=10, paid_amount_cents=0,
        )
        # PRD §3.9 guard blocks close-out while uncollected is non-zero AND any
        # PENDING agreement is un-forfeited; a DISPUTED agreement (no PENDING
        # left) passes the guard and is forfeited by the sweep.
        validate_success(
            api.dispute_agreement(agreement["id"], {"reason": "contested"}, ctx["leader"])
        )
        close_out = validate_success(api.close_out_season(season["id"], admin))
        assert close_out["forfeited_agreements"] == 1
        assert close_out["total_proceeds_offset_cents"] == 12000
        acct = get_account(account["id"], admin=admin)
        assert acct["balance_cents"] == 66000
        assert get_agreement(agreement["id"], admin=admin)["status"] == "FORFEITED"


class TestNonLinearStateMachineSecond:
    def test_transfer_ship_signature_retraction_releases_hold(self, api):
        """PRD §3.4: "a ship signature can be retracted by the same troop that
        gave it, returning the transfer from `SHIPPER_SIGNED` to `REQUESTED`,
        clearing `shipper_signed_by_troop_id` to null, releasing any site hold,
        and advancing the transfer's `version`"."

        Design: Difficulty/non_linear_state_machine/transfer_ship_signature_retraction_cycle
        """
        admin = make_council_admin_headers()
        ctx = setup_open_season_with_supply(
            600, admin=admin, packages_per_case=12, deliver=True,
        )
        season, product, site = ctx["season"], ctx["product"], ctx["site"]
        troop, account, leader = create_troop_with_account(season["id"], admin=admin)
        set_clock("2027-01-10T00:00:00Z", admin=admin)
        create_and_confirm_order(
            season["id"], troop, [(product["id"], 480)], leader=leader, admin=admin
        )
        transfer = create_transfer(
            season["id"], product["id"], 24, admin,
            dest_troop_id=troop["id"], site_id=site["id"],
        )
        # CouncilAdmin signs the cupboard-source ship side, recording the
        # represented troop via signing_troop_id (PRD §3.4); that same troop
        # then retracts its own signature.
        validate_success(
            api.sign_ship(transfer["id"], {"signing_troop_id": troop["id"]}, admin)
        )
        retracted = validate_success(api.retract_ship_signature(transfer["id"], leader))
        assert retracted["status"] == "REQUESTED"
        assert retracted["shipper_signed_by_troop_id"] is None
        site_after = get_site(site["id"], admin=admin)
        assert site_after["hold_units"] == 0
        assert site_after["available_units"] == 600

    def test_digital_order_refund_after_delivery_blocked_both_dims_intact(self, api):
        """PRD §3.6: "The order's two status dimensions then evolve
        independently: `payment_status` walks `PENDING`, `PAID`, `UNCOLLECTED`,
        and `REFUNDED`, while `fulfillment_status` walks `OPEN`, `DELIVERED`,
        and `CANCELLED`". PRD §3.6: "refunding after delivery is refused with
        `ERR_ALREADY_DELIVERED`."

        Design: Difficulty/non_linear_state_machine/digital_order_parallel_payment_and_fulfillment_dims
        """
        admin = make_council_admin_headers()
        ctx = setup_selling_season(purchase_qty=1000, confirm_qty=800, admin=admin)
        season, product = ctx["season"], ctx["product"]
        order = create_digital_order(
            season["id"], ctx["troop"],
            [{"product_id": product["id"], "package_qty": 12}],
            leader=ctx["leader"],
        )
        validate_success(api.record_payment(order["id"], ctx["leader"]))
        validate_success(api.mark_delivered(order["id"], ctx["leader"]))
        resp = api.refund_digital_order(order["id"], admin)
        validate_error(resp, ApiErrorId.ERR_ALREADY_DELIVERED, 422)
        after = get_digital_order(order["id"], admin=admin)
        assert after["payment_status"] == "PAID"
        assert after["fulfillment_status"] == "DELIVERED"


class TestTransitiveCascadeSecond:
    def test_order_confirm_cascade_attainment_and_season_flip(self, api):
        """PRD §3.2: "Confirmation swaps the order's units out of
        `pending_commit_units` and into `initial_commit_units`, pins the
        order's `total_amount_cents` from the products' current prices at that
        moment, posts that amount as a charge against the troop account's
        `balance_cents`, and accrues per-package proceeds into the account's
        `proceeds_accrued_cents`". PRD §3.3: "the system performs it
        automatically when two conditions coincide: the logical clock has
        reached `ordering_opens_at`, and `forecast_attainment_pct` has reached
        the selling gate."

        Design: Difficulty/transitive_cascade/order_confirm_three_hop_cascade
        """
        admin = make_council_admin_headers()
        ctx = setup_open_season_with_supply(100, admin=admin)
        season, product = ctx["season"], ctx["product"]
        troop, account, leader = create_troop_with_account(season["id"], admin=admin)
        set_clock("2027-01-10T00:00:00Z", admin=admin)
        order = create_and_confirm_order(
            season["id"], troop, [(product["id"], 80)], leader=leader, admin=admin
        )
        assert order["status"] == "CONFIRMED"
        assert order["total_amount_cents"] == 48000
        acct = get_account(account["id"], admin=admin)
        assert acct["balance_cents"] == 48000
        assert acct["proceeds_accrued_cents"] == 8000
        read = get_season(season["id"], admin=admin)
        assert read["initial_commit_units"] == 80
        assert read["pending_commit_units"] == 0
        assert read["remaining_units"] == 20
        assert read["forecast_attainment_pct"] == 80.00
        assert read["status"] == "SELLING"

    def test_transfer_complete_swap_symmetry_auto_completes_counter(self, api):
        """PRD §3.4: "When a completed transfer has a `counter_transfer_id`
        whose counter-transfer is itself sitting at `RECEIVER_SIGNED`, the
        counter-transfer auto-completes in the same breath, preserving swap
        symmetry."

        Design: Difficulty/transitive_cascade/transfer_complete_two_hop_swap_symmetry_cascade
        """
        admin = make_council_admin_headers()
        ctx = setup_open_season_with_supply(600, admin=admin, packages_per_case=12)
        season, site = ctx["season"], ctx["site"]
        product_tm = ctx["product"]
        product_sd = add_product(
            season["id"], admin=admin, variety_code="SD", name="Samoas",
            unit_price_cents=700, troop_proceeds_cents=110, packages_per_case=12,
        )
        create_and_place_po(season, product_sd["id"], 600, site["id"], admin=admin)
        troop1, account1, leader1 = create_troop_with_account(season["id"], admin=admin)
        troop2, account2, leader2 = create_troop_with_account(season["id"], admin=admin)
        set_clock("2027-01-10T00:00:00Z", admin=admin)
        create_and_confirm_order(
            season["id"], troop1, [(product_tm["id"], 480)], leader=leader1, admin=admin
        )
        # PRD §3.4 SOD: a troop-created request may not be ship-signed by the
        # requesting troop, so admin creates both legs (transfer creation is a
        # shared capability) and each source troop signs its own ship side.
        tr_y = create_transfer(
            season["id"], product_sd["id"], 12, admin,
            source_troop_id=troop2["id"], dest_troop_id=troop1["id"],
        )
        tr_x = create_transfer(
            season["id"], product_tm["id"], 12, admin,
            source_troop_id=troop1["id"], dest_troop_id=troop2["id"],
            counter_transfer_id=tr_y["id"],
        )
        validate_success(api.sign_ship(tr_x["id"], {"signing_troop_id": troop1["id"]}, leader1))
        validate_success(api.sign_receive(tr_x["id"], {"signing_troop_id": troop2["id"]}, leader2))
        validate_success(api.sign_ship(tr_y["id"], {"signing_troop_id": troop2["id"]}, leader2))
        validate_success(api.sign_receive(tr_y["id"], {"signing_troop_id": troop1["id"]}, leader1))
        current = get_transfer(tr_x["id"], admin=admin)
        completed = validate_success(
            api.complete_transfer(tr_x["id"], {"expected_transfer_version": current["version"]}, admin)
        )
        assert completed["status"] == "COMPLETED"
        assert get_transfer(tr_y["id"], admin=admin)["status"] == "COMPLETED"


class TestPriorityPairSecond:
    def test_confirm_recall_beats_supply_insufficient_variant(self, api):
        """PRD §2.10: "Only after those four come the business rules, in this
        relative order: recall safety (`ERR_RECALLED_PRODUCT`) before
        referential ownership (`ERR_FORBIDDEN_OWNERSHIP`), before segregation
        of duties (`ERR_SOD_SAME_TROOP`), before booth conflicts
        (`ERR_BOOTH_CONFLICT`), before season and clock acceptance gates
        (`ERR_SEASON_NOT_ACCEPTING`), before the case-pack constraint
        (`ERR_CASE_PACK_VIOLATION`), before supply and capacity checks
        (`ERR_SUPPLY_INSUFFICIENT`), before fiscal guards
        (`ERR_FISCAL_VIOLATION`), and finally optimistic-concurrency staleness
        (`ERR_STALE_VERSION`) last.""

        Design: Difficulty/priority_pair_validation_conflict/confirm_recall_safety_beats_allocation_constraint
        """
        admin = make_council_admin_headers()
        ctx = setup_open_season_with_supply(50, admin=admin)
        season, product = ctx["season"], ctx["product"]
        troop, account, leader = create_troop_with_account(season["id"], admin=admin)
        set_clock("2027-01-10T00:00:00Z", admin=admin)
        submitted = create_and_submit_order(
            season["id"], troop, [(product["id"], 60)], leader=leader
        )
        create_active_recall(
            season["id"], product["id"], admin=admin,
            effective_at="2027-01-05T00:00:00Z",
        )
        resp = api.confirm_order(season["id"], submitted["id"], admin)
        validate_error(resp, ApiErrorId.ERR_RECALLED_PRODUCT, 422)
        assert get_order(submitted["id"], admin=admin)["status"] == "SUBMITTED"

    def test_transfer_complete_wrong_state_rejected_despite_stale_and_recall(self, api):
        """PRD §2.4: "A state transition attempted on a resource that is not in
        a state from which that transition exists is rejected with the
        domain-specific state error where one exists
        (`ERR_SEASON_INVALID_STATE`, `ERR_ORDER_INVALID_STATE`,
        `ERR_TRANSFER_INVALID_STATE`, `ERR_REQUEST_INVALID_STATE`,
        `ERR_PAYMENT_INVALID_STATE`, `ERR_FULFILLMENT_INVALID_STATE`,
        `ERR_PO_INVALID_STATE`, `ERR_RECALL_INVALID_STATE`,
        `ERR_AGREEMENT_INVALID_STATE`), or with the generic
        `ERR_INVALID_STATE` (HTTP 409) where none applies."

        Design: Difficulty/priority_pair_validation_conflict/transfer_complete_occ_state_vs_recall_safety
        """
        admin = make_council_admin_headers()
        ctx = setup_open_season_with_supply(
            600, admin=admin, packages_per_case=12, deliver=True,
        )
        season, product, site = ctx["season"], ctx["product"], ctx["site"]
        troop, account, leader = create_troop_with_account(season["id"], admin=admin)
        set_clock("2027-01-10T00:00:00Z", admin=admin)
        create_and_confirm_order(
            season["id"], troop, [(product["id"], 480)], leader=leader, admin=admin
        )
        transfer = create_transfer(
            season["id"], product["id"], 12, admin,
            dest_troop_id=troop["id"], site_id=site["id"],
        )
        create_active_recall(
            season["id"], product["id"], admin=admin,
            effective_at="2027-01-05T00:00:00Z",
        )
        resp = api.complete_transfer(
            transfer["id"], {"expected_transfer_version": transfer["version"] - 1}, admin
        )
        validate_error(resp, ApiErrorId.ERR_TRANSFER_INVALID_STATE, 409)
        assert get_transfer(transfer["id"], admin=admin)["status"] == "REQUESTED"


class TestBoundaryPrecisionSecond:
    def test_attainment_gate_inclusive_boundary_flips_selling(self, api):
        """PRD §3.3: "The gate itself is inclusive: an attainment of at least
        80.00 percent opens selling."

        Design: Difficulty/boundary_precision_check/attainment_gate_exactly_80_vs_just_below
        """
        admin = make_council_admin_headers()
        ctx = setup_open_season_with_supply(100, admin=admin)
        season, product = ctx["season"], ctx["product"]
        troop, account, leader = create_troop_with_account(season["id"], admin=admin)
        set_clock("2027-01-10T00:00:00Z", admin=admin)
        submitted = create_and_submit_order(
            season["id"], troop, [(product["id"], 80)], leader=leader
        )
        validate_success(api.confirm_order(season["id"], submitted["id"], admin))
        read = get_season(season["id"], admin=admin)
        assert read["forecast_attainment_pct"] == 80.00
        assert read["status"] == "SELLING"

    def test_order_submit_with_zero_lines_stays_draft(self, api):
        """PRD §3.2: "it must hold at least one line, or `ERR_ORDER_EMPTY`
        results"."

        Design: Difficulty/boundary_precision_check/order_submit_empty_lines_zero_count_edge
        """
        admin = make_council_admin_headers()
        season = create_season(admin=admin)
        add_product(season["id"], admin=admin)
        open_season(season["id"], admin=admin)
        troop, account, leader = create_troop_with_account(season["id"], admin=admin)
        set_clock("2027-01-10T00:00:00Z", admin=admin)
        order = validate_success(
            api.create_order(season["id"], {"troop_id": troop["id"], "kind": "INITIAL"}, leader),
            expected_status=201,
        )
        resp = api.submit_order(season["id"], order["id"], leader)
        validate_error(resp, ApiErrorId.ERR_ORDER_EMPTY, 422)
        assert get_order(order["id"], admin=admin)["status"] == "DRAFT"


class TestCrossEntityDependencySecond:
    def test_booth_slot_creation_blocked_without_host_permission(self, api):
        """PRD §3.5: "Slot creation is refused with `ERR_BOOTH_CONFLICT` when
        host permission is missing, when the slot's date appears in the
        location's blackout dates, or when the new interval overlaps an
        existing slot at the same location — touching boundaries, where one
        slot's `end_at` equals another's `start_at`, are explicitly allowed."

        Design: Difficulty/cross_entity_state_dependency/booth_approve_gated_by_location_permission
        """
        admin = make_council_admin_headers()
        ctx = setup_selling_season(admin=admin)
        season = ctx["season"]
        location = validate_success(
            api.create_booth_location(
                season["id"],
                create_booth_location_payload(host_permission_granted=False),
                admin,
            ),
            expected_status=201,
        )
        resp = api.create_booth_slot(create_booth_slot_payload(location["id"]), admin)
        validate_error(resp, ApiErrorId.ERR_BOOTH_CONFLICT, 409)

    def test_begin_reconciliation_rejected_while_transfer_requested(self, api):
        """PRD §3.9: "The move is refused with `ERR_TRANSFER_IN_FLIGHT` while
        any transfer of the season sits in `REQUESTED`, `SHIPPER_SIGNED`, or
        `RECEIVER_SIGNED` — inventory in motion must land first — and with
        `ERR_BOOTH_REQUEST_PENDING` while any booth request remains `PENDING`."

        Design: Difficulty/cross_entity_state_dependency/reconciliation_gated_by_transfer_and_booth_states
        """
        admin = make_council_admin_headers()
        ctx = setup_selling_season(purchase_qty=600, confirm_qty=480,
                                   packages_per_case=12, admin=admin)
        season, product = ctx["season"], ctx["product"]
        troop2, account2, leader2 = create_troop_with_account(season["id"], admin=admin)
        create_transfer(
            season["id"], product["id"], 12, ctx["leader"],
            source_troop_id=ctx["troop"]["id"], dest_troop_id=troop2["id"],
        )
        resp = api.begin_reconciliation(season["id"], admin)
        validate_error(resp, ApiErrorId.ERR_TRANSFER_IN_FLIGHT, 409)
        assert get_season(season["id"], admin=admin)["status"] == "SELLING"


class TestResourceTemporalOverlapSecond:
    def test_booth_slot_touching_boundary_allowed_overlap_rejected(self, api):
        """PRD §3.5: "Slot creation is refused with `ERR_BOOTH_CONFLICT` when
        host permission is missing, when the slot's date appears in the
        location's blackout dates, or when the new interval overlaps an
        existing slot at the same location — touching boundaries, where one
        slot's `end_at` equals another's `start_at`, are explicitly allowed."

        Design: Difficulty/resource_temporal_overlap/booth_slot_half_open_interval_overlap
        """
        admin = make_council_admin_headers()
        ctx = setup_selling_season(admin=admin)
        arena = setup_booth_arena(ctx["season"]["id"], admin=admin)
        touching = validate_success(
            api.create_booth_slot(
                create_booth_slot_payload(
                    arena["location"]["id"],
                    start_at="2027-02-10T16:00:00Z",
                    end_at="2027-02-10T18:00:00Z",
                ),
                admin,
            ),
            expected_status=201,
        )
        assert touching["location_id"] == arena["location"]["id"]
        resp = api.create_booth_slot(
            create_booth_slot_payload(
                arena["location"]["id"],
                start_at="2027-02-10T15:00:00Z",
                end_at="2027-02-10T17:00:00Z",
            ),
            admin,
        )
        validate_error(resp, ApiErrorId.ERR_BOOTH_CONFLICT, 409)

    def test_site_capacity_boundary_inclusive_then_exceeded(self, api):
        """PRD §3.1: "Recording is permitted only from `ORDERED` or
        `PARTIALLY_DELIVERED`, and only while the receiving site's posture is
        `RECEIVING` with enough headroom — pushing `received_units` past
        `capacity_units` fails with `ERR_SITE_CAPACITY_EXCEEDED`." PRD §2.8:
        "`FULL` once `received_units` reaches or exceeds `capacity_units`".

        Design: Difficulty/resource_temporal_overlap/site_capacity_aggregate_overlap_semantics
        """
        admin = make_council_admin_headers()
        season = create_season(admin=admin)
        product = add_product(season["id"], admin=admin)
        site = add_site(season, admin=admin, capacity_units=100)
        po_a = create_and_place_po(season, product["id"], 90, site["id"], admin=admin)
        po_b = create_and_place_po(season, product["id"], 20, site["id"], admin=admin)
        # Deliveries require site posture RECEIVING (PRD §3.1), i.e. season OPEN.
        open_season(season["id"], admin=admin)
        deliver_po(season["id"], po_a["id"], 90, admin=admin)
        deliver_po(season["id"], po_b["id"], 10, admin=admin)
        site_read = get_site(site["id"], admin=admin)
        assert site_read["received_units"] == 100
        assert site_read["posture"] == "FULL"
        resp = api.record_delivery(season["id"], po_b["id"], {"delivered_now": 10}, admin)
        validate_error(resp, ApiErrorId.ERR_SITE_CAPACITY_EXCEEDED, 422)


class TestCompensatingInvariantSecond:
    def test_season_commitment_ledger_restored_after_reject(self, api):
        """PRD §3.2: "A successful submission moves the order to `SUBMITTED`,
        adds its `total_units` to the season's `pending_commit_units`,
        recomputes `remaining_units`, and advances the season's `version`."
        PRD §3.2: "Rejection instead moves the order to `REJECTED`, releases
        the pending commitment back into `remaining_units`, and records the
        supplied `reason` into the order's `rejection_reason`."

        Design: Difficulty/compensating_invariant/season_commitment_conservation_submit_reject
        """
        admin = make_council_admin_headers()
        ctx = setup_open_season_with_supply(200, admin=admin)
        season, product = ctx["season"], ctx["product"]
        before = get_season(season["id"], admin=admin)
        troop, account, leader = create_troop_with_account(season["id"], admin=admin)
        set_clock("2027-01-10T00:00:00Z", admin=admin)
        submitted = create_and_submit_order(
            season["id"], troop, [(product["id"], 50)], leader=leader
        )
        rejected = validate_success(
            api.reject_order(season["id"], submitted["id"], {"reason": "duplicate"}, admin)
        )
        assert rejected["status"] == "REJECTED"
        after = get_season(season["id"], admin=admin)
        assert after["pending_commit_units"] == 0
        assert after["initial_commit_units"] == 0
        assert after["remaining_units"] == before["remaining_units"] == 200

    def test_troop_account_balance_restored_after_refund(self, api):
        """PRD §3.6: "The refund credits `total_amount_cents` back off the
        troop account's `balance_cents` and claws the accrued proceeds back out
        of `proceeds_accrued_cents`."

        Design: Difficulty/compensating_invariant/troop_account_money_conservation_payment_refund
        """
        admin = make_council_admin_headers()
        ctx = setup_selling_season(purchase_qty=100, confirm_qty=80, admin=admin)
        season, product, account = ctx["season"], ctx["product"], ctx["account"]
        before = get_account(account["id"], admin=admin)
        order = create_digital_order(
            season["id"], ctx["troop"],
            [{"product_id": product["id"], "package_qty": 12}],
            leader=ctx["leader"],
        )
        validate_success(api.record_payment(order["id"], ctx["leader"]))
        refunded = validate_success(api.refund_digital_order(order["id"], admin))
        assert refunded["payment_status"] == "REFUNDED"
        assert refunded["fulfillment_status"] == "OPEN"
        after = get_account(account["id"], admin=admin)
        assert after["balance_cents"] == before["balance_cents"] == 48000
        assert after["proceeds_accrued_cents"] == before["proceeds_accrued_cents"] == 8000
