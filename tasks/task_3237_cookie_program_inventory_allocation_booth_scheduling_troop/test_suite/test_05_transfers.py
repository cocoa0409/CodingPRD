"""Inventory transfer lifecycle: double-acknowledgement, SoD, holds, cycles,
OCC at completion, swap symmetry."""
from test_helpers import (
    ApiErrorId,
    add_product,
    assert_inventory_transfer,
    create_active_recall,
    create_and_confirm_order,
    create_and_place_po,
    create_season,
    create_transfer,
    create_troop_with_account,
    deliver_po,
    get_site,
    get_transfer,
    make_council_admin_headers,
    make_troop_leader_headers,
    open_season,
    set_clock,
    setup_open_season_with_supply,
    setup_selling_season,
    validate_error,
    validate_success,
)


def _setup_selling_season_case12(admin, purchase_qty=600, confirm_qty=480):
    """SELLING season with case-pack-12 product and one confirmed order."""
    ctx = setup_selling_season(
        purchase_qty=purchase_qty, confirm_qty=confirm_qty, admin=admin,
        packages_per_case=12,
    )
    return ctx


class TestTransferSegregation:
    def test_transfer_sod_requester_cannot_ship_sign_own_request(self, api):
        """PRD §3.4: "when the request was created by a troop, the signing
        troop must differ from the requesting troop; the same troop signing its
        own request fails with `ERR_SOD_SAME_TROOP`."

        Design: Corner/state_machines/transfer_sod_requester_cannot_ship_sign_own_request
        """
        admin = make_council_admin_headers()
        ctx = _setup_selling_season_case12(admin)
        season, product, troop = ctx["season"], ctx["product"], ctx["troop"]
        leader = ctx["leader"]
        troop2, account2, leader2 = create_troop_with_account(season["id"], admin=admin)
        transfer = create_transfer(
            season["id"], product["id"], 12, leader,
            source_troop_id=troop["id"], dest_troop_id=troop2["id"],
        )
        resp = api.sign_ship(transfer["id"], {"signing_troop_id": troop["id"]}, leader)
        validate_error(resp, ApiErrorId.ERR_SOD_SAME_TROOP, 422)


class TestTransferCycle:
    def test_transfer_ship_signature_retraction_cycle(self, api):
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
        held = get_site(site["id"], admin=admin)
        assert held["hold_units"] == 24
        assert held["available_units"] == 600 - 24
        retracted = validate_success(
            api.retract_ship_signature(transfer["id"], make_troop_leader_headers(troop["id"]))
        )
        assert_inventory_transfer(retracted)
        assert retracted["status"] == "REQUESTED"
        assert retracted["shipper_signed_by_troop_id"] is None
        restored = get_site(site["id"], admin=admin)
        assert restored["hold_units"] == 0
        assert restored["available_units"] == 600


class TestTransferCompletePriority:
    def test_transfer_complete_occ_state_vs_recall_safety(self, api):
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
        unchanged = get_transfer(transfer["id"], admin=admin)
        assert unchanged["status"] == "REQUESTED"


class TestTransferSwapSymmetry:
    def test_transfer_complete_two_hop_swap_symmetry_cascade(self, api):
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
        tr_x_current = get_transfer(tr_x["id"], admin=admin)
        completed = validate_success(
            api.complete_transfer(
                tr_x["id"], {"expected_transfer_version": tr_x_current["version"]}, admin
            )
        )
        assert completed["status"] == "COMPLETED"
        tr_y_after = get_transfer(tr_y["id"], admin=admin)
        assert tr_y_after["status"] == "COMPLETED"
