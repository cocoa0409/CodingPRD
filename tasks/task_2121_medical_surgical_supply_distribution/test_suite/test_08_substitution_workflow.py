"""Backorders, the clinician information loop, and substitution approval."""

from test_helpers import (
    ApiErrorId,
    add_order_line,
    assert_substitution_request,
    clinician_action_payload,
    clinician_decide_substitution,
    create_chargeback_claim,
    create_lot,
    create_order,
    create_substitution_request,
    create_substitution_request_payload,
    make_clinician_headers,
    make_materials_manager_headers,
    read_claim,
    read_contract,
    read_order,
    read_order_line,
    read_substitution_request,
    requester_respond_substitution,
    setup_backordered_line,
    setup_priced_catalogue,
    substitution_respond_payload,
    validate_error,
    walk_order_to_delivered,
    CLINICIAN_USER_ID,
    TEST_USERS,
)

ADMIN = TEST_USERS["contract_admin_headers"]


def _draft_order_with_open_line_and_request(room_code, sku, alt_sku, contract_code,
                                            facility_code):
    """A DRAFT order carrying one OPEN line worth 3083 cents, with a PENDING
    substitution request raised against that still-open line."""
    world = setup_priced_catalogue(
        [
            {
                "item": {
                    "sku": sku, "description": "Substitution probe, case",
                    "manufacturer_code": "MFR-ACME", "uom": "CS", "wac_cents": 8000,
                    "handling_class": "AMBIENT", "units_per_parent": 10,
                },
                "tier_price_cents": 3000, "floor_price_cents": 2000,
                "formulary": {"facility_item_code": "FAC-SUB", "par_qty": 50,
                              "reorder_point": 10},
            },
            {
                "item": {
                    "sku": alt_sku,
                    "description": "Substitution probe alternate, case",
                    "manufacturer_code": "MFR-ACME", "uom": "CS", "wac_cents": 8000,
                    "handling_class": "AMBIENT", "units_per_parent": 10,
                },
                "priced": False,
                "formulary": None,
            },
        ],
        room_overrides={
            "facility_code": facility_code, "room_code": room_code,
            "gpo_member_class": "ACUTE", "room_type": "GENERAL_STORE",
        },
        contract_overrides={
            "manufacturer_code": "MFR-ACME", "contract_code": contract_code,
            "tier": "TIER_1", "member_class_scope": "ACUTE",
        },
    )
    room_id = world["room"]["id"]
    world["order"] = create_order(room_id)
    world["order_line"] = add_order_line(
        world["order"]["id"], room_id, world["items"][0]["id"], 1,
        world["order"]["version"],
    )
    world["request"] = create_substitution_request(
        world["order_line"]["id"], room_id, world["items"][1]["id"],
        justification="Checking whether the alternate is stocked",
    )
    return world


def test_withdrawal_cancels_a_still_open_line_and_the_draft_order(api):
    """PRD §3.6: "Withdrawal belongs to the requester and is permitted as
    `PENDING → WITHDRAWN` and as `INFO_REQUESTED → WITHDRAWN`. If the target
    line is still `OPEN` at that moment, the line moves `OPEN → CANCELLED` with
    its extended price and line fee zeroed. And if that cancellation leaves a
    `DRAFT` order with every one of its lines in `CANCELLED`, the order itself
    moves `DRAFT → CANCELLED` with `order_total_cents` set to zero — the only
    path to a cancelled order in this system, reached by cascade rather than by
    any direct request."
    PRD §3.6: "The new request records `requested_by_user_id` from the acting
    user, starts in `status` `PENDING` with `rounds_used` at zero, and leaves
    `clinician_user_id`, `info_request_note`, `response_note` and
    `price_delta_cents` null."

    Design: Corner/state_machines/substitution_withdraw_cancels_the_still_open_target_line
    """
    world = _draft_order_with_open_line_and_request(
        "GEN-209", "SKU-SM9-CS", "SKU-SM9-ALT-CS", "CTR-SM9", "FAC-209"
    )
    assert read_order(world["order"]["id"])["order_total_cents"] == 3083

    withdrawn = requester_respond_substitution(
        world["request"]["id"], world["room"]["id"], "WITHDRAW",
        response_note="No longer needed",
    )
    assert_substitution_request(withdrawn)
    assert withdrawn["status"] == "WITHDRAWN"
    assert withdrawn["rounds_used"] == 0

    line = read_order_line(world["order_line"]["id"])
    assert line["line_status"] == "CANCELLED"
    assert line["extended_price_cents"] == 0
    assert line["line_fee_cents"] == 0

    order = read_order(world["order"]["id"])
    assert order["order_total_cents"] == 0
    assert order["fulfillment_status"] == "CANCELLED"


def test_respond_on_a_pending_request_and_a_request_on_a_cancelled_line_are_refused(api):
    """PRD §3.6: "A `RESPOND` attempted while the request is already `PENDING`,
    and any clinician action or requester response against a request already in
    `APPROVED`, `REJECTED` or `WITHDRAWN`, is `ERR_SUBSTITUTION_STATE_INVALID`
    (HTTP 409)."
    PRD §3.6: "A substitution request names the `proposed_item_id` and carries a
    free-text `justification`, and it is permitted while the target line is
    either `OPEN` or `BACKORDERED` — a request opened against a line in any
    other state is `ERR_ORDER_LINE_STATE_INVALID` (HTTP 409)."

    Design: Corner/errors/substitution_respond_on_a_pending_request_is_rejected
    """
    world = _draft_order_with_open_line_and_request(
        "GEN-600", "SKU-SR-CS", "SKU-SR-ALT-CS", "CTR-SR", "FAC-600"
    )
    mm_headers = make_materials_manager_headers(world["room"]["id"])

    premature = api.respond_substitution_request(
        world["request"]["id"],
        substitution_respond_payload("RESPOND", "Premature answer"),
        mm_headers,
    )
    validate_error(premature, ApiErrorId.ERR_SUBSTITUTION_STATE_INVALID.value, 409)
    assert read_substitution_request(world["request"]["id"])["rounds_used"] == 0

    withdrawn = requester_respond_substitution(
        world["request"]["id"], world["room"]["id"], "WITHDRAW",
        response_note="Closing the request",
    )
    assert withdrawn["status"] == "WITHDRAWN"
    assert read_order_line(world["order_line"]["id"])["line_status"] == "CANCELLED"

    on_cancelled_line = api.create_substitution_request(
        world["order_line"]["id"],
        create_substitution_request_payload(
            world["items"][1]["id"],
            justification="Second attempt on a cancelled line",
        ),
        mm_headers,
    )
    validate_error(
        on_cancelled_line, ApiErrorId.ERR_ORDER_LINE_STATE_INVALID.value, 409
    )


class TestBoundedInformationRequestLoop:
    """The PENDING to INFO_REQUESTED cycle is bounded by rounds_used."""

    @staticmethod
    def _pending_request_on_a_backordered_line():
        world = setup_backordered_line(
            primary_spec={
                "item": {
                    "sku": "SKU-CATH-CS", "description": "Catheter kit, case",
                    "manufacturer_code": "MFR-ACME", "uom": "CS", "wac_cents": 8000,
                    "handling_class": "AMBIENT", "units_per_parent": 10,
                },
                "tier_price_cents": 6000, "floor_price_cents": 5000,
                "formulary": {"facility_item_code": "FAC-CATH", "par_qty": 40,
                              "reorder_point": 8},
            },
            alternate_spec={
                "item": {
                    "sku": "SKU-CATH-ALT-CS",
                    "description": "Catheter kit alternate, case",
                    "manufacturer_code": "MFR-ACME", "uom": "CS", "wac_cents": 8500,
                    "handling_class": "AMBIENT", "units_per_parent": 10,
                },
                "tier_price_cents": 6000, "floor_price_cents": 5000,
                "formulary": {"facility_item_code": "FAC-CATH-ALT", "par_qty": 40,
                              "reorder_point": 8},
            },
            room_overrides={
                "facility_code": "FAC-007", "room_code": "ICU-7",
                "gpo_member_class": "ACUTE", "room_type": "ICU",
            },
            contract_overrides={
                "manufacturer_code": "MFR-ACME", "contract_code": "CTR-C7",
                "tier": "TIER_1", "member_class_scope": "ACUTE",
            },
            requested_qty=4,
        )
        world["request"] = create_substitution_request(
            world["order_line"]["id"], world["room"]["id"], world["alt_item"]["id"],
            justification="Primary catheter kit on national backorder",
        )
        return world

    def test_each_response_closes_a_round_and_increments_the_counter(self, api):
        """PRD §3.6: "`REQUEST_INFO` is permitted only from `PENDING`, moves the
        request to `INFO_REQUESTED`, stores the supplied note as
        `info_request_note` and stamps `clinician_user_id`."
        PRD §3.6: "The requester answers with an `action` of `RESPOND` and a
        `response_note`, which is permitted only from `INFO_REQUESTED`, stores
        the note, increments `rounds_used` by one, and returns the request to
        `PENDING` — closing the `PENDING → INFO_REQUESTED → PENDING` cycle under
        a bounded counter."
        PRD §3.5: "If **no** line finds a lot at all, the order moves `SUBMITTED
        → HELD` instead, every `OPEN` line becomes `BACKORDERED`, and the
        recomputed `order_total_cents` is therefore zero."

        Design: Difficulty/non_linear_state_machine/substitution_request_cycles_pending_to_info_requested_twice_then_exhausts
        """
        world = self._pending_request_on_a_backordered_line()
        assert world["order_line"]["line_status"] == "BACKORDERED"
        assert read_order(world["order"]["id"])["fulfillment_status"] == "HELD"

        first_query = clinician_decide_substitution(
            world["request"]["id"], "REQUEST_INFO",
            note="Confirm the alternate connector gauge",
        )
        assert first_query["status"] == "INFO_REQUESTED"
        assert first_query["rounds_used"] == 0

        first_answer = requester_respond_substitution(
            world["request"]["id"], world["room"]["id"], "RESPOND",
            response_note="Gauge is identical",
        )
        assert first_answer["status"] == "PENDING"
        assert first_answer["rounds_used"] == 1

        clinician_decide_substitution(
            world["request"]["id"], "REQUEST_INFO",
            note="Confirm sterilisation method",
        )
        second_answer = requester_respond_substitution(
            world["request"]["id"], world["room"]["id"], "RESPOND",
            response_note="Ethylene oxide, same as primary",
        )
        assert second_answer["status"] == "PENDING"
        assert second_answer["rounds_used"] == 2

    def test_a_third_information_request_is_refused(self, api):
        """PRD §3.6: "It is budgeted: a clinician may open a round only while
        `rounds_used` is strictly less than 2, and an attempt once that ceiling
        has been reached is `ERR_SUBSTITUTION_ROUNDS_EXHAUSTED` (HTTP 409)."

        Design: Difficulty/non_linear_state_machine/substitution_request_cycles_pending_to_info_requested_twice_then_exhausts
        """
        world = self._pending_request_on_a_backordered_line()
        request_id = world["request"]["id"]
        room_id = world["room"]["id"]

        for note, answer in (
            ("Confirm the alternate connector gauge", "Gauge is identical"),
            ("Confirm sterilisation method", "Ethylene oxide, same as primary"),
        ):
            clinician_decide_substitution(request_id, "REQUEST_INFO", note=note)
            requester_respond_substitution(
                request_id, room_id, "RESPOND", response_note=answer
            )
        assert read_substitution_request(request_id)["rounds_used"] == 2

        exhausted = api.clinician_action(
            request_id,
            clinician_action_payload("REQUEST_INFO", "Third query"),
            make_clinician_headers(CLINICIAN_USER_ID),
        )
        validate_error(
            exhausted, ApiErrorId.ERR_SUBSTITUTION_ROUNDS_EXHAUSTED.value, 409
        )
        assert read_substitution_request(request_id)["status"] == "PENDING"


class TestApprovalCascadesIntoTheOpenClaim:
    """Approving a substitution re-prices the line, re-totals the order and
    unwinds the manufacturer ledger behind the open claim."""

    @staticmethod
    def _claimed_order_with_a_pending_substitution():
        world = setup_priced_catalogue(
            [
                {
                    "item": {
                        "sku": "SKU-GLOVE-CS",
                        "description": "Sterile surgical glove, case of 24",
                        "manufacturer_code": "MFR-ACME", "uom": "CS",
                        "wac_cents": 12000, "handling_class": "AMBIENT",
                        "units_per_parent": 24,
                    },
                    "tier_price_cents": 9000, "floor_price_cents": 8000,
                    "chargeback_eligible": True,
                    "formulary": {"facility_item_code": "FAC-GLOVE", "par_qty": 400,
                                  "reorder_point": 100},
                },
                {
                    "item": {
                        "sku": "SKU-GAUZE-CS",
                        "description": "Gauze sponge, case of 24",
                        "manufacturer_code": "MFR-ACME", "uom": "CS",
                        "wac_cents": 7000, "handling_class": "AMBIENT",
                        "units_per_parent": 24,
                    },
                    "tier_price_cents": 3400, "floor_price_cents": 2000,
                    "chargeback_eligible": True,
                    "formulary": {"facility_item_code": "FAC-GAUZE", "par_qty": 200,
                                  "reorder_point": 40},
                },
                {
                    "item": {
                        "sku": "SKU-GAUZE-ALT-CS",
                        "description": "Gauze sponge alternate, case of 24",
                        "manufacturer_code": "MFR-ACME", "uom": "CS",
                        "wac_cents": 6000, "handling_class": "AMBIENT",
                        "units_per_parent": 24,
                    },
                    "tier_price_cents": 3000, "floor_price_cents": 2000,
                    "chargeback_eligible": True,
                    "formulary": {"facility_item_code": "FAC-GAUZE-ALT",
                                  "par_qty": 200, "reorder_point": 40},
                },
            ],
            room_overrides={
                "facility_code": "FAC-009", "room_code": "OR-CORE-9",
                "gpo_member_class": "ACUTE", "room_type": "OR_CORE",
                "credit_limit_cents": 5000000,
            },
            contract_overrides={
                "manufacturer_code": "MFR-ACME", "contract_code": "CTR-A",
                "tier": "TIER_2", "member_class_scope": "ACUTE",
            },
        )
        room_id = world["room"]["id"]
        glove, gauze, alt = world["items"]
        create_lot(
            glove["id"], lot_code="LOT-G9", expiry_date="2027-06-30T00:00:00Z",
            received_quantity=100,
        )

        world["order"] = create_order(room_id)
        world["line_glove"] = add_order_line(
            world["order"]["id"], room_id, glove["id"], 10, world["order"]["version"]
        )
        world["line_gauze"] = add_order_line(
            world["order"]["id"], room_id, gauze["id"], 5
        )
        walk_order_to_delivered(
            world,
            route_overrides={"route_code": "RT-9", "service_date": "2026-08-01",
                             "vehicle_class": "AMBIENT_VAN"},
        )
        world["claim"] = create_chargeback_claim(
            world["order"]["id"], world["contract"]["id"]
        )
        world["request"] = create_substitution_request(
            world["line_gauze"]["id"], room_id, alt["id"],
            justification="Primary gauze on allocation hold",
        )
        return world

    def test_approval_repins_the_line_and_records_the_price_delta(self, api):
        """PRD §3.6: "On success the request moves `PENDING → APPROVED`, stamps
        `clinician_user_id`, and rewrites the target line in place: the line's
        `item_id` becomes the proposed item, and `pinned_contract_line_id`,
        `pinned_unit_price_cents` and `chargeback_eligible` are re-pinned by the
        pinning role of the price formula at the current instant."
        PRD §3.6: "The request records `price_delta_cents` as the new pinned unit
        price minus the previously pinned unit price — a negative figure when
        the substitute is cheaper."

        Design: Difficulty/transitive_cascade/substitution_approval_line_to_order_to_claim_three_hops
        """
        world = self._claimed_order_with_a_pending_substitution()
        alt = world["items"][2]

        approved = clinician_decide_substitution(
            world["request"]["id"], "APPROVE",
            note="Alternate is clinically equivalent",
        )
        assert approved["status"] == "APPROVED"
        assert approved["price_delta_cents"] == -424, "3180 re-pinned minus 3604 pinned"

        line = read_order_line(world["line_gauze"]["id"])
        assert line["item_id"] == alt["id"]
        assert line["line_status"] == "SUBSTITUTED"
        assert line["pinned_unit_price_cents"] == 3180

    def test_approval_retotals_the_order_on_the_substituted_line(self, api):
        """PRD §3.6: "The line moves `BACKORDERED → SUBSTITUTED`, and because a
        substituted line participates in the total on its `requested_qty` basis,
        `extended_price_cents`, `line_fee_cents` and the order's
        `order_total_cents` are all recomputed."
        PRD §3.4: "Each participating line contributes on a quantity basis that
        depends on its state: `allocated_qty` when the line is `ALLOCATED` or
        `DELIVERED`, and `requested_qty` when it is `OPEN` or `SUBSTITUTED`."

        Design: Difficulty/transitive_cascade/substitution_approval_line_to_order_to_claim_three_hops
        """
        world = self._claimed_order_with_a_pending_substitution()
        assert read_order(world["order"]["id"])["order_total_cents"] == 98024

        clinician_decide_substitution(
            world["request"]["id"], "APPROVE",
            note="Alternate is clinically equivalent",
        )

        line = read_order_line(world["line_gauze"]["id"])
        assert line["extended_price_cents"] == 15900, "3180 times 5 requested cases"
        assert line["line_fee_cents"] == 437
        assert read_order(world["order"]["id"])["order_total_cents"] == 114361

    def test_approval_knocks_the_open_claim_into_rebill_required(self, api):
        """PRD §3.6: "That recomputation has a settlement consequence: if the
        order was sitting at `settlement_status` `CLAIMED` when its total
        changed, the order moves `CLAIMED → REBILL_REQUIRED`, its open claim
        moves `SUBMITTED → REBILL_REQUIRED`, and the claim's
        `net_chargeback_cents` is subtracted from the contract's
        `chargeback_payable_cents`."

        Design: Difficulty/transitive_cascade/substitution_approval_line_to_order_to_claim_three_hops
        """
        world = self._claimed_order_with_a_pending_substitution()
        assert read_order(world["order"]["id"])["settlement_status"] == "CLAIMED"
        assert (
            read_contract(world["contract"]["id"])["chargeback_payable_cents"] == 24108
        )

        clinician_decide_substitution(
            world["request"]["id"], "APPROVE",
            note="Alternate is clinically equivalent",
        )

        order = read_order(world["order"]["id"])
        claim = read_claim(world["claim"]["id"])
        assert order["settlement_status"] == "REBILL_REQUIRED"
        assert order["fulfillment_status"] == "DELIVERED", (
            "the fulfilment axis is untouched by the settlement cascade"
        )
        assert claim["status"] == "REBILL_REQUIRED"
        assert claim["net_chargeback_cents"] == 24108
        assert read_contract(world["contract"]["id"])["chargeback_payable_cents"] == 0
