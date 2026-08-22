"""Lot receipt, cold-chain excursions and first-expiry-first-out picking."""

from test_helpers import (
    ApiErrorId,
    add_order_line,
    allocate_order,
    assert_lot,
    assert_lot_units_conserved,
    cascade_recall_notice,
    create_item,
    create_lot,
    create_order,
    create_recall_notice,
    flag_lot_excursion,
    list_lines_drawn_from_lot,
    lot_excursion_payload,
    make_distribution_operator_headers,
    read_lot,
    read_order,
    read_order_line,
    setup_glove_order,
    setup_priced_item,
    submit_order,
    validate_error,
    validate_success,
    DISTRIBUTION_OPERATOR_USER_ID,
    SECOND_DISTRIBUTION_OPERATOR_USER_ID,
    TEST_USERS,
)

ADMIN = TEST_USERS["contract_admin_headers"]


def test_release_against_an_available_lot_is_refused(api):
    """PRD §3.5: "Releasing moves an `EXCURSION_HOLD` lot back to `AVAILABLE` and
    clears `excursion_flagged_by_user_id` — and this is where the two-person
    rule of §2.8 bites: an operator may not release the excursion they
    themselves flagged, and an attempt is `ERR_SEGREGATION_OF_DUTIES`."
    PRD §3.5: "Any of the three actions requested from a lot status that does not
    permit it is `ERR_LOT_STATE_INVALID` (HTTP 409)."

    Design: Corner/state_machines/lot_release_from_available_state_is_rejected
    """
    item = create_item(
        sku="SKU-SM6-CS", description="Lot state probe", manufacturer_code="MFR-ACME",
        uom="CS", wac_cents=2000, handling_class="AMBIENT", units_per_parent=10,
    )
    lot = create_lot(
        item["id"], lot_code="LOT-SM6", expiry_date="2027-12-31T00:00:00Z",
        received_quantity=50,
    )
    assert_lot(lot)

    response = api.lot_excursion(
        lot["id"],
        lot_excursion_payload("RELEASE"),
        make_distribution_operator_headers(SECOND_DISTRIBUTION_OPERATOR_USER_ID),
    )
    validate_error(response, ApiErrorId.ERR_LOT_STATE_INVALID.value, 409)

    after = read_lot(lot["id"])
    assert after["status"] == "AVAILABLE"
    assert after.get("excursion_flagged_by_user_id") is None
    assert after["quantity_on_hand"] == 50


def test_allocation_picks_the_earliest_expiring_lot(api):
    """PRD §3.5: "For a given line, a lot is a candidate when it holds the line's
    item, its `status` is `AVAILABLE`, its `expiry_date` is strictly later than
    the current logical clock, and its `quantity_on_hand` is at least the
    quantity the line needs; among candidates the lot with the earliest
    `expiry_date` wins, and if two lots expire at the same instant the one
    created earlier wins."
    PRD §3.5: "From `SUBMITTED`, picking moves the order `SUBMITTED → ALLOCATED`
    when at least one of its lines finds a lot. Each `OPEN` or `SUBSTITUTED`
    line that finds a lot moves `OPEN → ALLOCATED` or `SUBSTITUTED → ALLOCATED`
    respectively, records `lot_id` and `allocated_qty`, decrements that lot's
    `quantity_on_hand` by the allocated quantity, and has its
    `extended_price_cents` and `line_fee_cents` recomputed."

    Design: Corner/calculations/allocation_selects_the_earliest_expiring_lot_under_fefo
    """
    world = setup_priced_item(
        room_overrides={
            "facility_code": "FAC-304", "room_code": "GEN-304",
            "gpo_member_class": "ACUTE", "room_type": "GENERAL_STORE",
        },
        item_overrides={
            "sku": "SKU-FEFO-CS", "description": "FEFO probe",
            "manufacturer_code": "MFR-ACME", "uom": "CS", "wac_cents": 8000,
            "handling_class": "AMBIENT", "units_per_parent": 10,
        },
        contract_overrides={
            "manufacturer_code": "MFR-ACME", "contract_code": "CTR-FEFO",
            "tier": "TIER_1", "member_class_scope": "ACUTE",
        },
        tier_price_cents=3000,
        floor_price_cents=2000,
        formulary_overrides={"facility_item_code": "FAC-FEFO", "par_qty": 200,
                             "reorder_point": 40},
    )
    late = create_lot(
        world["item"]["id"], lot_code="LOT-LATE",
        expiry_date="2027-01-01T00:00:00Z", received_quantity=50,
    )
    early = create_lot(
        world["item"]["id"], lot_code="LOT-EARLY",
        expiry_date="2026-12-01T00:00:00Z", received_quantity=50,
    )

    order = create_order(world["room"]["id"])
    line = add_order_line(
        order["id"], world["room"]["id"], world["item"]["id"], 5, order["version"]
    )
    submit_order(order["id"], world["room"]["id"])
    allocated = allocate_order(order["id"])

    picked = read_order_line(line["id"])
    assert picked["lot_id"] == early["id"], "FEFO takes the earliest expiry"
    assert picked["lot_id"] != late["id"]
    assert picked["allocated_qty"] == 5
    assert picked["line_status"] == "ALLOCATED"
    assert read_lot(early["id"])["quantity_on_hand"] == 45
    assert read_lot(late["id"])["quantity_on_hand"] == 50
    assert allocated["fulfillment_status"] == "ALLOCATED"
    assert read_order(order["id"])["order_total_cents"] == 15413


def test_the_operator_who_flagged_the_excursion_cannot_release_it(api):
    """PRD §2.8: "A `ContractAdmin` reconciling a chargeback claim must not be
    the same `X-User-ID` recorded in that claim's `submitted_by_user_id`. A
    `DistributionOperator` releasing a cold-chain excursion must not be the same
    `X-User-ID` recorded in that lot's `excursion_flagged_by_user_id`. Either
    violation is reported as `ERR_SEGREGATION_OF_DUTIES` (HTTP 403), and the
    rule is enforced on exactly two endpoints:
    `POST /chargeback-claims/{chargeback_claim_id}/settle` and
    `POST /lots/{lot_id}/excursion`."
    PRD §3.5: "Flagging moves an `AVAILABLE` lot to `EXCURSION_HOLD`, records the
    acting operator in `excursion_flagged_by_user_id`, and removes the lot from
    consideration for picking."

    Design: Corner/rbac/excursion_flagger_cannot_release_the_hold_they_raised
    """
    item = create_item(
        sku="SKU-SOD1-CS", description="SoD probe", manufacturer_code="MFR-ACME",
        uom="CS", wac_cents=4000, handling_class="AMBIENT", units_per_parent=10,
    )
    lot = create_lot(
        item["id"], lot_code="LOT-SOD1", expiry_date="2027-12-31T00:00:00Z",
        received_quantity=60,
    )
    flagged = flag_lot_excursion(lot["id"], DISTRIBUTION_OPERATOR_USER_ID,
                                 "Door left open")
    assert flagged["status"] == "EXCURSION_HOLD"
    assert flagged["excursion_flagged_by_user_id"] == DISTRIBUTION_OPERATOR_USER_ID

    self_release = api.lot_excursion(
        lot["id"],
        lot_excursion_payload("RELEASE"),
        make_distribution_operator_headers(DISTRIBUTION_OPERATOR_USER_ID),
    )
    validate_error(self_release, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

    still_held = read_lot(lot["id"])
    assert still_held["status"] == "EXCURSION_HOLD"
    assert still_held["excursion_flagged_by_user_id"] == DISTRIBUTION_OPERATOR_USER_ID

    released = validate_success(
        api.lot_excursion(
            lot["id"],
            lot_excursion_payload("RELEASE"),
            make_distribution_operator_headers(SECOND_DISTRIBUTION_OPERATOR_USER_ID),
        ),
        200,
    )
    assert released["status"] == "AVAILABLE"
    assert released.get("excursion_flagged_by_user_id") is None
    assert released["quantity_on_hand"] == 60


class TestLotUnitConservation:
    """The lot's on-hand quantity plus everything allocated out of it always
    equals the quantity received."""

    def test_units_are_conserved_across_allocation(self, api):
        """PRD §3.5: "The received quantity is immutable once written and anchors
        a units-conservation invariant: at every instant, the lot's
        `quantity_on_hand` plus the quantity currently allocated out of it to
        order lines must equal the received quantity, unless the lot has been
        written off."
        PRD §3.5: "Allocation is all-or-nothing per line: a line either takes its
        full quantity from one lot or takes nothing."

        Design: Difficulty/compensating_invariant/lot_unit_conservation_across_allocation_and_recall_release
        """
        world = setup_glove_order(
            stage="allocated",
            room_overrides={"facility_code": "FAC-017", "room_code": "OR-CORE-17"},
            lot_overrides={"lot_code": "LOT-17", "received_quantity": 100},
        )

        lot = read_lot(world["lot"]["id"])
        line = read_order_line(world["order_line"]["id"])

        assert lot["received_quantity"] == 100
        assert lot["quantity_on_hand"] == 90
        assert line["allocated_qty"] == 10
        assert line["line_status"] == "ALLOCATED"
        assert_lot_units_conserved(lot, list_lines_drawn_from_lot(lot["id"]))

    def test_units_are_conserved_after_the_recall_returns_the_allocation(self, api):
        """PRD §3.8: "Because a lot became quarantined, every order line drawn
        from that lot whose `line_status` is `ALLOCATED` is moved `ALLOCATED →
        BACKORDERED`, processing lines in ascending `created_at` order. Each such
        line returns its `allocated_qty` to the lot's `quantity_on_hand`, then
        clears its `lot_id` and sets `allocated_qty` to zero, and has its
        `extended_price_cents` and `line_fee_cents` zeroed because a backordered
        line leaves the total."
        PRD §3.5: "The received quantity is immutable once written and anchors a
        units-conservation invariant: at every instant, the lot's
        `quantity_on_hand` plus the quantity currently allocated out of it to
        order lines must equal the received quantity, unless the lot has been
        written off."

        Design: Difficulty/compensating_invariant/lot_unit_conservation_across_allocation_and_recall_release
        """
        world = setup_glove_order(
            stage="allocated",
            room_overrides={"facility_code": "FAC-017", "room_code": "OR-CORE-17"},
            lot_overrides={"lot_code": "LOT-17", "received_quantity": 100},
        )
        notice = create_recall_notice(
            world["item"]["id"], lot_id=world["lot"]["id"], recall_class="CLASS_II",
            reason="Packaging integrity",
        )

        before_lot = read_lot(world["lot"]["id"])
        before_line = read_order_line(world["order_line"]["id"])
        assert before_lot["quantity_on_hand"] == 90
        assert before_line["allocated_qty"] == 10

        cascade_recall_notice(notice["id"])

        after_lot = read_lot(world["lot"]["id"])
        after_line = read_order_line(world["order_line"]["id"])

        assert after_lot["quantity_on_hand"] == 100, (
            "the released units go back to the lot they came from"
        )
        assert after_line["allocated_qty"] == 0
        assert after_line.get("lot_id") is None
        assert after_lot["status"] == "QUARANTINED"
        assert after_lot["received_quantity"] == 100
        assert_lot_units_conserved(
            after_lot, list_lines_drawn_from_lot(after_lot["id"])
        )
