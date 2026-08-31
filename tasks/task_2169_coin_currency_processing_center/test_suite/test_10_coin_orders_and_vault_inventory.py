"""Coin orders: dock capacity, waterfall allocation, release, return and inventory."""

from test_helpers import (
    ApiErrorId,
    MANAGER_1,
    TELLER_1,
    adjust_inventory,
    approve_coin_order_payload,
    assert_coin_order,
    assert_coin_order_line,
    assert_vault_inventory,
    coin_order_line,
    create_coin_order_payload,
    find_coin_order_line,
    inventory_adjustment_payload,
    make_customer_account_holder_headers,
    make_manager_headers,
    make_teller_headers,
    place_coin_order,
    read_account,
    read_coin_order,
    read_coin_order_lines,
    read_inventory_position,
    read_vault,
    read_vault_version,
    release_coin_order,
    release_coin_order_payload,
    return_coin_order,
    set_posture,
    setup_approved_coin_order,
    setup_vault_with_inventory,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestVaultInventoryAdjustments:
    def test_an_adjustment_that_would_go_negative_is_refused_outright(self, api):
        """PRD §3.1: "An adjustment that would drive `on_hand_boxes` below zero is refused
        outright with `ERR_INVENTORY_NEGATIVE`; the row is left untouched."
        PRD §3.1: "Every adjustment also recomputes the vault's
        `coin_face_value_on_hand_cents` and increments the vault's `version` by 1."
        PRD §3.1: "A standard box is worth 2,500 cents of pennies (twenty-five dollars),
        10,000 cents of nickels (one hundred dollars), 25,000 cents of dimes (two hundred and
        fifty dollars), or 50,000 cents of quarters (five hundred dollars)."

        Design: Corner/validations/inventory_adjustment_below_zero_rejected
        """
        scenario = setup_vault_with_inventory({"QUARTER": 2})
        vault_id = scenario["vault"]["id"]
        position = read_inventory_position(vault_id, "QUARTER")
        assert_vault_inventory(position)
        assert position["on_hand_boxes"] == 2
        version_before = read_vault_version(vault_id)

        response = api.adjust_vault_inventory(
            vault_id,
            inventory_adjustment_payload("QUARTER", -3),
            make_manager_headers(MANAGER_1),
        )
        validate_error(response, ApiErrorId.ERR_INVENTORY_NEGATIVE.value)
        assert response.status_code == 422

        after = read_inventory_position(vault_id, "QUARTER")
        assert after["on_hand_boxes"] == 2, (
            f"The refused adjustment leaves the row untouched, got {after['on_hand_boxes']}"
        )
        vault = read_vault(vault_id)
        assert vault["version"] == version_before, (
            f"A refused adjustment is not an adjustment and bumps no version: "
            f"{version_before} -> {vault['version']}"
        )
        assert vault["coin_face_value_on_hand_cents"] == 100_000, (
            f"Two quarter boxes are worth 2 * 50000 = 100000, got "
            f"{vault['coin_face_value_on_hand_cents']}"
        )


class TestCoinOrderPlacement:
    def test_two_lines_of_the_same_denomination_are_refused(self, api):
        """PRD §3.9: "At most one line per denomination is permitted within a single order;
        naming the same denomination twice is `ERR_DUPLICATE_DENOMINATION`."
        PRD §3.9: "Orders can be read singly, listed with optional `customer_account_id`,
        `vault_id` and `status` filters, and their lines read back as a list; all of these
        accept `limit` and `offset`."

        Design: Corner/validations/duplicate_denomination_line_rejected_on_coin_order_create
        """
        scenario = setup_vault_with_inventory({})
        account_id = scenario["account"]["id"]

        response = api.create_coin_order(
            create_coin_order_payload(
                account_id,
                scenario["vault"]["id"],
                [coin_order_line("QUARTER", 1), coin_order_line("QUARTER", 2)],
            ),
            make_customer_account_holder_headers(account_id),
        )
        validate_error(response, ApiErrorId.ERR_DUPLICATE_DENOMINATION.value)
        assert response.status_code == 422

        _, meta = validate_paginated(
            api.list_coin_orders(
                make_manager_headers(MANAGER_1), params={"vault_id": scenario["vault"]["id"]}
            )
        )
        assert meta["total_count"] == 0, (
            f"No CoinOrder may survive a rejected placement, got {meta['total_count']}"
        )

    def test_a_third_window_sharing_a_closed_endpoint_exceeds_the_dock_capacity(self, api):
        """PRD §3.9: "A vault's `pickup_concurrency_limit` is the number of live pickup
        windows that may cover any single instant. The requested window is treated as a
        **closed** interval, including both its start and its end instants, and if any instant
        inside it is already covered by that many or more of the vault's coin orders whose
        `status` is `REQUESTED`, `APPROVED_FULL` or `APPROVED_PARTIAL`, the order is refused
        with `ERR_PICKUP_CAPACITY_EXCEEDED`. Because the interval is closed at both ends, two
        windows that merely touch at a single instant do overlap for this purpose."

        Design: Difficulty/resource_temporal_overlap/vault_pickup_window_closed_interval_aggregate_capacity
        """
        scenario = setup_vault_with_inventory({}, pickup_concurrency_limit=2)
        account_id = scenario["account"]["id"]
        vault_id = scenario["vault"]["id"]

        place_coin_order(
            account_id,
            vault_id,
            [coin_order_line("QUARTER", 1)],
            "2026-08-05T10:00:00Z",
            "2026-08-05T12:00:00Z",
        )
        place_coin_order(
            account_id,
            vault_id,
            [coin_order_line("DIME", 1)],
            "2026-08-05T11:00:00Z",
            "2026-08-05T13:00:00Z",
        )

        response = api.create_coin_order(
            create_coin_order_payload(
                account_id,
                vault_id,
                [coin_order_line("NICKEL", 1)],
                "2026-08-05T12:00:00Z",
                "2026-08-05T14:00:00Z",
            ),
            make_customer_account_holder_headers(account_id),
        )
        validate_error(response, ApiErrorId.ERR_PICKUP_CAPACITY_EXCEEDED.value)
        assert response.status_code == 409, (
            f"ERR_PICKUP_CAPACITY_EXCEEDED must be HTTP 409, got {response.status_code}"
        )

    def test_a_window_starting_one_second_later_clears_the_dock(self, api):
        """PRD §3.9: "Because the interval is closed at both ends, two windows that merely
        touch at a single instant do overlap for this purpose."
        PRD §3.9: "A placed order is created in `REQUESTED` with one **order line** per entry
        in `lines`, each recording its `coin_order_id`, `denomination` and `boxes_requested`,
        with `boxes_allocated`, `boxes_returned` and `line_face_value_cents` all at 0."

        Design: Difficulty/resource_temporal_overlap/vault_pickup_window_closed_interval_aggregate_capacity
        """
        scenario = setup_vault_with_inventory({}, pickup_concurrency_limit=2)
        account_id = scenario["account"]["id"]
        vault_id = scenario["vault"]["id"]

        first = place_coin_order(
            account_id,
            vault_id,
            [coin_order_line("QUARTER", 1)],
            "2026-08-05T10:00:00Z",
            "2026-08-05T12:00:00Z",
        )
        second = place_coin_order(
            account_id,
            vault_id,
            [coin_order_line("DIME", 1)],
            "2026-08-05T11:00:00Z",
            "2026-08-05T13:00:00Z",
        )

        response = api.create_coin_order(
            create_coin_order_payload(
                account_id,
                vault_id,
                [coin_order_line("NICKEL", 1)],
                "2026-08-05T12:00:01Z",
                "2026-08-05T14:00:00Z",
            ),
            make_customer_account_holder_headers(account_id),
        )
        third = validate_success(response, 201)
        assert_coin_order(third)
        assert third["status"] == "REQUESTED", (
            f"The 12:00:01 window clears the first order's closed end, got {third['status']}"
        )
        assert read_coin_order(first["id"])["status"] == "REQUESTED"
        assert read_coin_order(second["id"])["status"] == "REQUESTED"

        _, meta = validate_paginated(
            api.list_coin_orders(make_manager_headers(MANAGER_1), params={"vault_id": vault_id})
        )
        assert meta["total_count"] == 3, (
            f"Three orders must now sit on this vault, got {meta['total_count']}"
        )


class TestAllocation:
    def test_a_zero_allocation_is_a_rejected_order_not_an_error(self, api):
        """PRD §3.9: "If `total_boxes_allocated` is 0, nothing could be filled at all: the
        order moves `REQUESTED → REJECTED`, `fill_ratio_pct` is 0 and `charge_cents` is 0, and
        no inventory position is touched. A zero allocation is a business outcome, not an
        error, and this holds regardless of what `allow_partial` said."
        PRD §3.9: "If no position row exists for that pair, the available figure is 0 and the
        line simply allocates nothing — this is not an error."

        Design: Corner/calculations/coin_order_with_zero_allocation_is_rejected_status_not_an_error
        """
        scenario = setup_vault_with_inventory({})
        order = place_coin_order(
            scenario["account"]["id"], scenario["vault"]["id"], [coin_order_line("NICKEL", 2)]
        )
        assert order["total_boxes_requested"] == 2

        response = api.approve_coin_order(
            order["id"], approve_coin_order_payload(False), make_manager_headers(MANAGER_1)
        )
        approved = validate_success(response, 200)
        assert approved["status"] == "REJECTED", (
            f"An empty allocation is a REJECTED order, got {approved['status']}"
        )
        assert approved["fill_ratio_pct"] == 0
        assert approved["charge_cents"] == 0
        assert approved["total_boxes_allocated"] == 0
        assert approved["approved_by_user_id"] == MANAGER_1

        positions, meta = validate_paginated(
            api.list_vault_inventory(scenario["vault"]["id"], make_manager_headers(MANAGER_1))
        )
        assert meta["total_count"] == 0, (
            f"No inventory position may be created by the allocation, got {meta['total_count']}"
        )
        assert positions == []

    def test_a_partial_fill_with_allow_partial_false_is_refused(self, api):
        """PRD §3.9: "If the fill is somewhere strictly between 0 and 100 percent, the order
        moves `REQUESTED → APPROVED_PARTIAL` when `allow_partial` was true; when
        `allow_partial` was false the partial fill is refused with
        `ERR_INSUFFICIENT_COIN_INVENTORY` and nothing is reserved."

        Design: Corner/validations/full_only_approval_with_short_inventory_returns_insufficient_coin_inventory
        """
        scenario = setup_vault_with_inventory({"QUARTER": 1})
        order = place_coin_order(
            scenario["account"]["id"], scenario["vault"]["id"], [coin_order_line("QUARTER", 3)]
        )

        response = api.approve_coin_order(
            order["id"], approve_coin_order_payload(False), make_manager_headers(MANAGER_1)
        )
        validate_error(response, ApiErrorId.ERR_INSUFFICIENT_COIN_INVENTORY.value)
        assert response.status_code == 409

        refreshed = read_coin_order(order["id"])
        assert refreshed["status"] == "REQUESTED", (
            f"The refused approval leaves the order REQUESTED, got {refreshed['status']}"
        )
        assert refreshed["total_boxes_allocated"] == 0
        position = read_inventory_position(scenario["vault"]["id"], "QUARTER")
        assert position["reserved_boxes"] == 0, "Nothing is reserved by a refused approval"
        assert position["on_hand_boxes"] == 1

    def test_the_lines_subresource_exposes_the_per_denomination_allocation(self, api):
        """PRD §3.9: "The line's `boxes_allocated` is the smaller of its `boxes_requested` and
        that available figure, and its `line_face_value_cents` is `boxes_allocated` multiplied
        by the face value of a standard box of that denomination — 2,500 cents for pennies,
        10,000 cents for nickels, 25,000 cents for dimes and 50,000 cents for quarters."
        PRD §3.9: "A placed order is created in `REQUESTED` with one **order line** per entry
        in `lines`, each recording its `coin_order_id`, `denomination` and `boxes_requested`,
        with `boxes_allocated`, `boxes_returned` and `line_face_value_cents` all at 0."

        Design: Corner/endpoints/coin_order_lines_subresource_exposes_per_denomination_allocations
        """
        scenario = setup_approved_coin_order(
            {"PENNY": 6, "DIME": 4, "QUARTER": 10},
            {"PENNY": 2, "DIME": 6, "QUARTER": 3},
            allow_partial=True,
        )

        lines, meta = validate_paginated(
            api.list_coin_order_lines(
                scenario["order"]["id"], make_teller_headers(TELLER_1), params={"limit": 10, "offset": 0}
            )
        )
        assert meta["total_count"] == 3, f"Expected three lines, got {meta['total_count']}"

        penny = find_coin_order_line(lines, "PENNY")
        dime = find_coin_order_line(lines, "DIME")
        quarter = find_coin_order_line(lines, "QUARTER")
        for line in (penny, dime, quarter):
            assert_coin_order_line(line)
            assert line["coin_order_id"] == scenario["order"]["id"]
            assert line["boxes_returned"] == 0

        assert (penny["boxes_requested"], penny["boxes_allocated"], penny["line_face_value_cents"]) == (
            2,
            2,
            5_000,
        ), f"PENNY line unexpected: {penny}"
        assert (dime["boxes_requested"], dime["boxes_allocated"], dime["line_face_value_cents"]) == (
            6,
            4,
            100_000,
        ), f"DIME line unexpected: {dime}"
        assert (
            quarter["boxes_requested"],
            quarter["boxes_allocated"],
            quarter["line_face_value_cents"],
        ) == (3, 3, 150_000), f"QUARTER line unexpected: {quarter}"


class TestReleaseGuards:
    def test_dual_control_is_reported_ahead_of_the_inventory_shortfall(self, api):
        """PRD §2.9: "When a coin order is released, the acting `X-User-ID` must differ from
        the `approved_by_user_id` recorded at approval. The manager who authorised the
        allocation may not also be the person who hands the boxes to the carrier; a violation
        is again `ERR_DUAL_CONTROL_VIOLATION`."
        PRD §2.6: "Checks are evaluated in the following sequence, and the first failure is
        the one reported; later checks are never reached."
        PRD §2.6: "16. **Dual control** — `ERR_DUAL_CONTROL_VIOLATION` (409)."
        PRD §2.6: "36. **Coin inventory sufficient** — `ERR_INSUFFICIENT_COIN_INVENTORY` (409)."

        Design: Difficulty/priority_pair_validation_conflict/dual_control_beats_inventory_shortfall_on_coin_release
        """
        scenario = setup_approved_coin_order(
            {"QUARTER": 10}, {"QUARTER": 3}, allow_partial=False, approver_user_id=MANAGER_1
        )
        assert scenario["order"]["status"] == "APPROVED_FULL"
        assert scenario["order"]["charge_cents"] == 150_000

        shrunk = adjust_inventory(scenario["vault"]["id"], "QUARTER", -8)
        assert shrunk["on_hand_boxes"] == 2, (
            f"The write-down leaves only 2 boxes against the 3 allocated, got "
            f"{shrunk['on_hand_boxes']}"
        )

        response = api.release_coin_order(
            scenario["order"]["id"],
            release_coin_order_payload(read_vault_version(scenario["vault"]["id"])),
            make_teller_headers(MANAGER_1),
        )
        validate_error(response, ApiErrorId.ERR_DUAL_CONTROL_VIOLATION.value)
        assert response.status_code == 409, (
            f"ERR_DUAL_CONTROL_VIOLATION must be HTTP 409, got {response.status_code}"
        )

    def test_the_blocked_release_moves_no_box_and_records_no_releaser(self, api):
        """PRD §3.9: "A successful release moves the order `APPROVED_FULL → RELEASED` or
        `APPROVED_PARTIAL → RELEASED`, depending on which approved state it was in, and does
        five things. Per denomination, the position's `on_hand_boxes` and `reserved_boxes` are
        each decreased by that line's `boxes_allocated`, with `available_boxes` recomputed as
        `on_hand_boxes` minus `reserved_boxes` floored at 0."
        PRD §3.9: "The releasing teller's `X-User-ID` must differ from the order's
        `approved_by_user_id`, or the release is `ERR_DUAL_CONTROL_VIOLATION`."
        PRD §3.1: "`reserved_boxes` is never moved by an adjustment — it tracks boxes
        committed to approved-but-unreleased coin orders, it only ever moves through the
        coin-order lifecycle, and after a shrinkage write-down it may legitimately exceed
        `on_hand_boxes`."

        Design: Difficulty/priority_pair_validation_conflict/dual_control_beats_inventory_shortfall_on_coin_release
        """
        scenario = setup_approved_coin_order(
            {"QUARTER": 10}, {"QUARTER": 3}, allow_partial=False, approver_user_id=MANAGER_1
        )
        adjust_inventory(scenario["vault"]["id"], "QUARTER", -8)

        response = api.release_coin_order(
            scenario["order"]["id"],
            release_coin_order_payload(read_vault_version(scenario["vault"]["id"])),
            make_teller_headers(MANAGER_1),
        )
        validate_error(response, ApiErrorId.ERR_DUAL_CONTROL_VIOLATION.value)

        order = read_coin_order(scenario["order"]["id"])
        assert order["status"] == "APPROVED_FULL", (
            f"The refused release leaves the order APPROVED_FULL, got {order['status']}"
        )
        assert order["released_by_user_id"] is None, (
            f"No releaser may be recorded, got {order['released_by_user_id']!r}"
        )
        position = read_inventory_position(scenario["vault"]["id"], "QUARTER")
        assert position["on_hand_boxes"] == 2, (
            f"The physical position is untouched by the refused release, got "
            f"{position['on_hand_boxes']}"
        )
        assert position["reserved_boxes"] == 3, (
            f"The approval's reservation still stands, got {position['reserved_boxes']}"
        )

    def test_a_restricted_vault_refuses_the_physical_release(self, api):
        """PRD §2.10: "`RESTRICTED` continues to permit counting but blocks the physical
        release of coin."
        PRD §2.10: "Attempting to release coin from a `RESTRICTED` vault is rejected with
        `ERR_VAULT_RESTRICTED` — a distinct code, because the remedy differs."
        PRD §3.9: "The vault's `posture` must be `OPEN`: a `RESTRICTED` posture yields
        `ERR_VAULT_RESTRICTED` and a `FROZEN` posture yields `ERR_VAULT_FROZEN`."

        Design: Corner/validations/restricted_vault_posture_blocks_coin_release
        """
        scenario = setup_approved_coin_order(
            {"QUARTER": 5}, {"QUARTER": 2}, allow_partial=False, approver_user_id=MANAGER_1
        )
        assert scenario["order"]["status"] == "APPROVED_FULL"

        restricted = set_posture(scenario["vault"]["id"], "RESTRICTED")
        assert restricted["posture"] == "RESTRICTED"

        response = api.release_coin_order(
            scenario["order"]["id"],
            release_coin_order_payload(read_vault_version(scenario["vault"]["id"])),
            make_teller_headers(TELLER_1),
        )
        validate_error(response, ApiErrorId.ERR_VAULT_RESTRICTED.value)
        assert response.status_code == 409

        assert read_coin_order(scenario["order"]["id"])["status"] == "APPROVED_FULL"
        position = read_inventory_position(scenario["vault"]["id"], "QUARTER")
        assert position["on_hand_boxes"] == 5, "No box leaves a RESTRICTED vault"
        assert position["reserved_boxes"] == 2
        assert read_account(scenario["account"]["id"])["ledger_balance_cents"] == 0


class TestReleaseAndReturnConservation:
    def test_release_then_return_restores_the_vaults_coin_face_value(self, api):
        """PRD §3.1: "It is the sum, over every one of the vault's inventory positions, of
        `on_hand_boxes` multiplied by the face value of a standard box of that denomination."
        PRD §3.9: "The vault's `coin_face_value_on_hand_cents` is recomputed from the new
        positions."
        PRD §3.9: "Taken together, a release followed by a return leaves the vault's coin face
        value and the customer's ledger balance exactly where they stood before the release."

        Design: Difficulty/compensating_invariant/coin_release_then_return_conserves_vault_coin_face_value
        """
        scenario = setup_approved_coin_order(
            {"PENNY": 6, "DIME": 4, "QUARTER": 10},
            {"PENNY": 2, "DIME": 6, "QUARTER": 3},
            allow_partial=True,
            approver_user_id=MANAGER_1,
        )
        vault_id = scenario["vault"]["id"]
        assert scenario["order"]["status"] == "APPROVED_PARTIAL", (
            f"9 of 11 boxes fill, so the order is APPROVED_PARTIAL, got {scenario['order']['status']}"
        )
        assert scenario["order"]["fill_ratio_pct"] == 81.82, (
            f"100 * 9 / 11 rounds half up to 81.82, got {scenario['order']['fill_ratio_pct']}"
        )
        assert scenario["order"]["charge_cents"] == 255_000, (
            f"5000 + 100000 + 150000 = 255000, got {scenario['order']['charge_cents']}"
        )
        assert scenario["vault"]["coin_face_value_on_hand_cents"] == 615_000, (
            "6 * 2500 + 4 * 25000 + 10 * 50000 = 615000, got "
            f"{scenario['vault']['coin_face_value_on_hand_cents']}"
        )

        release_coin_order(scenario["order"]["id"], vault_id, teller_user_id=TELLER_1)
        assert read_vault(vault_id)["coin_face_value_on_hand_cents"] == 360_000, (
            "After the release 4 penny, 0 dime and 7 quarter boxes remain: 10000 + 350000"
        )

        returned = return_coin_order(scenario["order"]["id"], teller_user_id=TELLER_1)
        assert returned["status"] == "RETURNED", f"Expected RETURNED, got {returned['status']}"
        assert read_vault(vault_id)["coin_face_value_on_hand_cents"] == 615_000, (
            "The compensating return restores the vault's coin face value exactly"
        )

    def test_release_then_return_restores_every_position_and_the_ledger(self, api):
        """PRD §3.9: "Every line's `boxes_returned` is set equal to its `boxes_allocated` —
        returns are all-or-nothing, never partial. Per denomination the position's
        `on_hand_boxes` is increased by that line's `boxes_allocated` while `reserved_boxes` is
        deliberately left untouched, since the reservation was already consumed at release;
        `available_boxes` is recomputed and the vault's `coin_face_value_on_hand_cents` is
        recomputed."
        PRD §3.9: "The depositor's `ledger_balance_cents` is increased by the order's
        `charge_cents` and `available_balance_cents` is recomputed."
        PRD §3.9: "The depositor's `ledger_balance_cents` is decreased by the order's
        `charge_cents` and `available_balance_cents` is recomputed as `ledger_balance_cents`
        plus `provisional_credit_cents`."

        Design: Difficulty/compensating_invariant/coin_release_then_return_conserves_vault_coin_face_value
        """
        scenario = setup_approved_coin_order(
            {"PENNY": 6, "DIME": 4, "QUARTER": 10},
            {"PENNY": 2, "DIME": 6, "QUARTER": 3},
            allow_partial=True,
            approver_user_id=MANAGER_1,
        )
        vault_id = scenario["vault"]["id"]
        account_id = scenario["account"]["id"]

        release_coin_order(scenario["order"]["id"], vault_id, teller_user_id=TELLER_1)
        assert read_account(account_id)["ledger_balance_cents"] == -255_000, (
            "The release debits the order's charge from the depositor's ledger"
        )

        return_coin_order(scenario["order"]["id"], teller_user_id=TELLER_1)

        for denomination, expected_on_hand in (("PENNY", 6), ("DIME", 4), ("QUARTER", 10)):
            position = read_inventory_position(vault_id, denomination)
            assert position["on_hand_boxes"] == expected_on_hand, (
                f"{denomination} on_hand_boxes must return to {expected_on_hand}, got "
                f"{position['on_hand_boxes']}"
            )
            assert position["reserved_boxes"] == 0, (
                f"{denomination} reserved_boxes must be back at 0, got {position['reserved_boxes']}"
            )
            assert_vault_inventory(position)

        lines = read_coin_order_lines(scenario["order"]["id"])
        for denomination, allocated in (("PENNY", 2), ("DIME", 4), ("QUARTER", 3)):
            line = find_coin_order_line(lines, denomination)
            assert line["boxes_returned"] == allocated, (
                f"{denomination} boxes_returned must equal boxes_allocated {allocated}, got "
                f"{line['boxes_returned']}"
            )

        account = read_account(account_id)
        assert account["ledger_balance_cents"] == 0, (
            f"The return restores the ledger balance to 0, got {account['ledger_balance_cents']}"
        )
        assert account["available_balance_cents"] == 0
