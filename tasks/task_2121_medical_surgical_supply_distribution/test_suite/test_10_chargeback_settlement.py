"""Manufacturer chargeback claims: the four settlement steps, the two order
axes, the contract ledger and the two-person reconciliation rule."""

from test_helpers import (
    ApiErrorId,
    assert_chargeback_claim,
    assert_contract_ledger_matches_claims,
    claim_response_payload,
    claim_settle_payload,
    create_chargeback_claim_payload,
    list_claims_of_contract,
    make_contract_admin_headers,
    make_manufacturer_rep_headers,
    read_claim,
    read_contract,
    read_order,
    read_order_line,
    respond_to_claim,
    settle_claim,
    setup_glove_order,
    validate_error,
    validate_paginated,
    CONTRACT_ADMIN_USER_ID,
    MANUFACTURER_REP_USER_ID,
    TEST_USERS,
)

ADMIN = TEST_USERS["contract_admin_headers"]


def _glove_claim_world(claim_user_id=CONTRACT_ADMIN_USER_ID, **overrides):
    """The TIER_2 glove order delivered and claimed: gross 24600, fee 492,
    net 24108."""
    params = {
        "stage": "claimed",
        "room_overrides": {"facility_code": "FAC-CB", "room_code": "OR-CORE-CB"},
        "lot_overrides": {"lot_code": "LOT-CB", "received_quantity": 100},
        "route_overrides": {"route_code": "RT-CB", "service_date": "2026-08-01",
                            "vehicle_class": "AMBIENT_VAN"},
        "claim_user_id": claim_user_id,
    }
    params.update(overrides)
    return setup_glove_order(**params)


def test_gross_of_exactly_250000_selects_the_lowest_administrative_rate(api):
    """PRD §3.9: "**Step two:** `admin_fee_pct` is selected from a bracket keyed
    on the gross amount — a gross below 50000 cents takes 0.020, a gross from
    50000 cents up to but not including 250000 cents takes 0.015, and a gross of
    250000 cents or more takes 0.010. Bracket edges are inclusive on the lower
    bound, so a gross of exactly 50000 cents takes the middle rate of 0.015."
    PRD §3.9: "**Step three:** `admin_fee_cents` is the gross multiplied by the
    selected rate, rounded half up to a whole cent — this is the only rounding
    step in the whole settlement. **Step four:** `net_chargeback_cents` is the
    gross minus the administrative fee."

    Design: Corner/calculations/chargeback_admin_bracket_third_tier_at_exactly_250000
    """
    world = setup_glove_order(
        stage="claimed",
        room_overrides={"facility_code": "FAC-303", "room_code": "OR-CORE-303"},
        item_overrides={
            "sku": "SKU-B3-EA", "description": "High value implant, each",
            "manufacturer_code": "MFR-ORTHO", "uom": "EA", "wac_cents": 300000,
            "handling_class": "AMBIENT", "units_per_parent": 1,
        },
        contract_overrides={
            "manufacturer_code": "MFR-ORTHO", "contract_code": "CTR-B3",
            "tier": "TIER_1", "member_class_scope": "ACUTE",
        },
        formulary_overrides={"facility_item_code": "FAC-B3", "par_qty": 10,
                             "reorder_point": 2},
        tier_price_cents=50000,
        floor_price_cents=40000,
        requested_qty=1,
        lot_overrides={"lot_code": "LOT-B3", "expiry_date": "2028-01-01T00:00:00Z",
                       "received_quantity": 5},
        route_overrides={"route_code": "RT-B3", "service_date": "2026-08-01",
                         "vehicle_class": "AMBIENT_VAN"},
        arrival_min=600,
        service_minutes=20,
    )
    claim = world["claim"]
    assert_chargeback_claim(claim)

    assert read_order_line(world["order_line"]["id"])["settled_unit_price_cents"] == 50000
    assert claim["gross_chargeback_cents"] == 250000
    assert claim["admin_fee_pct"] == 0.010
    assert claim["admin_fee_cents"] == 2500
    assert claim["net_chargeback_cents"] == 247500
    assert read_order(world["order"]["id"])["order_total_cents"] == 51375


def test_second_claim_and_premature_reconcile_are_both_refused(api):
    """PRD §3.9: "The order must have `fulfillment_status` `DELIVERED` and
    `settlement_status` `UNBILLED`; an order may carry at most one claim whose
    `status` is anything other than `DISPUTED`, and a second is
    `ERR_CLAIM_ALREADY_OPEN` (HTTP 409)."
    PRD §3.9: "`RECONCILE` is permitted only while the claim is `ACCEPTED`; it is
    subject to the two-person rule of §2.8, so the acting `X-User-ID` must
    differ from `submitted_by_user_id`, and a violation is
    `ERR_SEGREGATION_OF_DUTIES`."
    PRD §3.9: "Any response or settle action requested from a claim status that
    does not permit it is `ERR_CLAIM_STATE_INVALID` (HTTP 409)."
    PRD §2.9: "When a request violates several rules at once, the response is
    determined by the **first** rule to fail in the fixed order below; rules
    later in the order are not evaluated at all, and their error codes cannot
    appear."

    Design: Corner/errors/second_claim_on_a_claimed_order_and_premature_reconcile_are_rejected
    """
    world = _glove_claim_world(room_overrides={"facility_code": "FAC-602",
                                               "room_code": "OR-CORE-602"})
    claim = world["claim"]

    duplicate = api.create_chargeback_claim(
        create_chargeback_claim_payload(world["order"]["id"], world["contract"]["id"]),
        make_contract_admin_headers("ca-3"),
    )
    validate_error(duplicate, ApiErrorId.ERR_CLAIM_ALREADY_OPEN.value, 409)

    premature = api.settle_chargeback_claim(
        claim["id"],
        claim_settle_payload("RECONCILE"),
        make_contract_admin_headers(CONTRACT_ADMIN_USER_ID),
    )
    validate_error(premature, ApiErrorId.ERR_CLAIM_STATE_INVALID.value, 409)
    assert (
        premature.json()["data"]["error_id"]
        != ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value
    ), "the state check precedes the two-person rule"

    _rows, meta = validate_paginated(
        api.list_chargeback_claims(
            ADMIN, params={"order_id": world["order"]["id"], "limit": 10, "offset": 0}
        )
    )
    assert meta["total_count"] == 1

    after = read_claim(claim["id"])
    assert after["status"] == "SUBMITTED"
    assert after["net_chargeback_cents"] == 24108
    assert after.get("reconciled_by_user_id") is None
    assert read_contract(world["contract"]["id"])["chargeback_payable_cents"] == 24108


def test_the_claim_submitter_cannot_reconcile_their_own_claim(api):
    """PRD §2.8: "A `ContractAdmin` reconciling a chargeback claim must not be
    the same `X-User-ID` recorded in that claim's `submitted_by_user_id`. A
    `DistributionOperator` releasing a cold-chain excursion must not be the same
    `X-User-ID` recorded in that lot's `excursion_flagged_by_user_id`. Either
    violation is reported as `ERR_SEGREGATION_OF_DUTIES` (HTTP 403), and the
    rule is enforced on exactly two endpoints:
    `POST /chargeback-claims/{chargeback_claim_id}/settle` and
    `POST /lots/{lot_id}/excursion`."
    PRD §3.9: "It moves the claim `ACCEPTED → RECONCILED`, records
    `reconciled_by_user_id`, leaves the ledger untouched because a reconciled
    claim also remains inside the payable set, and moves the order `CLAIMED →
    RECONCILED`."

    Design: Corner/rbac/claim_submitter_cannot_reconcile_their_own_claim
    """
    world = _glove_claim_world(
        room_overrides={"facility_code": "FAC-702", "room_code": "OR-CORE-702"},
        contract_overrides={"contract_code": "CTR-SOD2"},
    )
    claim = world["claim"]
    respond_to_claim(claim["id"], "ACCEPT")

    self_settle = api.settle_chargeback_claim(
        claim["id"],
        claim_settle_payload("RECONCILE"),
        make_contract_admin_headers(CONTRACT_ADMIN_USER_ID),
    )
    validate_error(self_settle, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

    refused = read_claim(claim["id"])
    assert refused["status"] == "ACCEPTED"
    assert refused.get("reconciled_by_user_id") is None

    reconciled = settle_claim(claim["id"], "RECONCILE", "ca-9")
    assert reconciled["status"] == "RECONCILED"
    assert reconciled["reconciled_by_user_id"] == "ca-9"
    assert reconciled["submitted_by_user_id"] == CONTRACT_ADMIN_USER_ID
    assert read_order(world["order"]["id"])["settlement_status"] == "RECONCILED"
    assert read_contract(world["contract"]["id"])["chargeback_payable_cents"] == 24108


def test_settlement_and_response_actions_belong_to_opposite_sides(api):
    """PRD §2.1: "If both headers are well formed but the named role is not among
    the roles authorised for the endpoint (see the catalogue in §4), the
    rejection is `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD §3.9: "The manufacturer responds through a `ManufacturerRep` supplying an
    `outcome` of `ACCEPT` or `DISPUTE`, and either is permitted only while the
    claim is `SUBMITTED`."
    PRD §3.9: "The distributor settles through a `ContractAdmin` supplying an
    `action` of `RECONCILE` or `RESUBMIT`."

    Design: Corner/rbac/manufacturer_rep_cannot_run_the_distributor_settle_action
    """
    world = _glove_claim_world(
        room_overrides={"facility_code": "FAC-703", "room_code": "OR-CORE-703"},
        contract_overrides={"contract_code": "CTR-RB4"},
    )
    claim = world["claim"]

    rep_settle = api.settle_chargeback_claim(
        claim["id"],
        claim_settle_payload("RECONCILE"),
        make_manufacturer_rep_headers(MANUFACTURER_REP_USER_ID),
    )
    validate_error(rep_settle, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)

    admin_respond = api.respond_chargeback_claim(
        claim["id"],
        claim_response_payload("ACCEPT"),
        make_contract_admin_headers(CONTRACT_ADMIN_USER_ID),
    )
    validate_error(admin_respond, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)

    assert read_claim(claim["id"])["status"] == "SUBMITTED"
    assert read_contract(world["contract"]["id"])["chargeback_payable_cents"] == 24108


class TestAdminFeeBracketKeyedOnGross:
    """The administrative bracket is chosen from the gross figure, before the
    fee is subtracted."""

    @staticmethod
    def _implant_claim_world():
        return setup_glove_order(
            stage="claimed",
            room_overrides={"facility_code": "FAC-005", "room_code": "OR-CORE-5"},
            item_overrides={
                "sku": "SKU-IMPLANT-EA", "description": "Orthopaedic implant, each",
                "manufacturer_code": "MFR-ORTHO", "uom": "EA", "wac_cents": 60000,
                "handling_class": "AMBIENT", "units_per_parent": 1,
            },
            contract_overrides={
                "manufacturer_code": "MFR-ORTHO", "contract_code": "CTR-CB",
                "tier": "TIER_1", "member_class_scope": "ACUTE",
            },
            formulary_overrides={"facility_item_code": "FAC-IMPLANT", "par_qty": 10,
                                 "reorder_point": 2},
            tier_price_cents=10000,
            floor_price_cents=9000,
            requested_qty=1,
            lot_overrides={"lot_code": "LOT-IMP-1",
                           "expiry_date": "2028-01-01T00:00:00Z",
                           "received_quantity": 5},
            route_overrides={"route_code": "RT-CB", "service_date": "2026-08-01",
                             "vehicle_class": "AMBIENT_VAN"},
        )

    def test_gross_at_the_lower_bracket_edge_takes_the_middle_rate(self, api):
        """PRD §3.9: "**Step one:** `gross_chargeback_cents` is the sum, over the
        eligible lines, of the item's `wac_cents` minus that line's
        `settled_unit_price_cents`, floored at zero for each line individually,
        multiplied by that line's `allocated_qty` — a line settled above the
        wholesale acquisition cost contributes nothing rather than a negative
        amount, and the *settled* price is used, never the pinned one."
        PRD §3.9: "**Step two:** `admin_fee_pct` is selected from a bracket keyed
        on the gross amount — a gross below 50000 cents takes 0.020, a gross from
        50000 cents up to but not including 250000 cents takes 0.015, and a gross
        of 250000 cents or more takes 0.010. Bracket edges are inclusive on the
        lower bound, so a gross of exactly 50000 cents takes the middle rate of
        0.015."

        Design: Difficulty/combinatorial_formula/chargeback_admin_bracket_keyed_on_gross_not_on_net
        """
        world = self._implant_claim_world()
        claim = world["claim"]

        assert (
            read_order_line(world["order_line"]["id"])["settled_unit_price_cents"]
            == 10000
        )
        assert claim["gross_chargeback_cents"] == 50000
        assert claim["admin_fee_pct"] == 0.015
        assert claim["admin_fee_cents"] == 750

    def test_net_is_gross_minus_fee_and_is_never_re_bracketed(self, api):
        """PRD §3.9: "The bracket is keyed on the gross figure and is never
        re-derived from the net figure; re-keying after step four changes the
        answer whenever the net amount falls into a different bracket than the
        gross did."
        PRD §3.9: "Creating the claim stores all five computed figures, records
        `submitted_by_user_id` from the acting administrator, starts the claim in
        `SUBMITTED` with `reconciled_by_user_id` and `dispute_reason` null, adds
        its `net_chargeback_cents` to the contract's `chargeback_payable_cents`,
        and moves the order `UNBILLED → CLAIMED` on its settlement axis."

        Design: Difficulty/combinatorial_formula/chargeback_admin_bracket_keyed_on_gross_not_on_net
        """
        world = self._implant_claim_world()
        claim = world["claim"]

        assert claim["net_chargeback_cents"] == 49250
        assert claim["net_chargeback_cents"] != 49000, (
            "49000 is what re-keying the bracket on the net figure would produce"
        )
        assert claim["eligible_line_count"] == 1
        assert claim["status"] == "SUBMITTED"
        assert claim["submitted_by_user_id"] == CONTRACT_ADMIN_USER_ID
        assert read_contract(world["contract"]["id"])["chargeback_payable_cents"] == 49250
        assert read_order(world["order"]["id"])["settlement_status"] == "CLAIMED"


class TestParallelOrderAxes:
    """The settlement axis cycles while the fulfilment axis sits in its terminal
    delivered state."""

    def test_settlement_axis_walks_claimed_unbilled_and_claimed_again(self, api):
        """PRD §3.9: "`DISPUTE` moves the claim `SUBMITTED → DISPUTED`, records
        the supplied `dispute_reason`, subtracts the claim's
        `net_chargeback_cents` from the contract's `chargeback_payable_cents`,
        and returns the order's settlement axis `CLAIMED → UNBILLED`."
        PRD §3.9: "Resubmitting a disputed claim moves it `DISPUTED → SUBMITTED`
        and the order `UNBILLED → CLAIMED`, closing the dispute cycle;
        resubmitting a rebill-required claim moves it `REBILL_REQUIRED →
        SUBMITTED` and the order `REBILL_REQUIRED → CLAIMED`."

        Design: Difficulty/non_linear_state_machine/order_settlement_axis_cycles_while_fulfillment_axis_is_terminal
        """
        world = _glove_claim_world(
            room_overrides={"facility_code": "FAC-006", "room_code": "OR-CORE-6"},
        )
        claim_id = world["claim"]["id"]

        assert read_order(world["order"]["id"])["settlement_status"] == "CLAIMED"
        assert read_claim(claim_id)["status"] == "SUBMITTED"

        respond_to_claim(
            claim_id, "DISPUTE", dispute_reason="Tier eligibility under review"
        )
        assert read_order(world["order"]["id"])["settlement_status"] == "UNBILLED"
        assert read_claim(claim_id)["status"] == "DISPUTED"

        settle_claim(claim_id, "RESUBMIT", CONTRACT_ADMIN_USER_ID)
        assert read_order(world["order"]["id"])["settlement_status"] == "CLAIMED"
        assert read_claim(claim_id)["status"] == "SUBMITTED"

    def test_fulfilment_axis_stays_delivered_throughout_the_settlement_cycle(self, api):
        """PRD §2.10: "Neither axis constrains the other's transition set: an
        order can sit at `DELIVERED` and `UNBILLED` indefinitely, and an order at
        `CLAIMED` can still be re-picked and re-totalled on the fulfilment axis,
        which is precisely what forces a rebill."
        PRD §3.9: "`RESUBMIT` is permitted from `DISPUTED` and from
        `REBILL_REQUIRED`; in both cases the four settlement steps are re-run at
        the current logical clock, rewriting `gross_chargeback_cents`,
        `admin_fee_pct`, `admin_fee_cents`, `net_chargeback_cents` and
        `eligible_line_count`, and the recomputed net amount is added back to the
        contract's `chargeback_payable_cents`."

        Design: Difficulty/non_linear_state_machine/order_settlement_axis_cycles_while_fulfillment_axis_is_terminal
        """
        world = _glove_claim_world(
            room_overrides={"facility_code": "FAC-006", "room_code": "OR-CORE-6"},
        )
        claim_id = world["claim"]["id"]
        contract_id = world["contract"]["id"]

        assert read_order(world["order"]["id"])["fulfillment_status"] == "DELIVERED"
        assert read_claim(claim_id)["net_chargeback_cents"] == 24108
        assert read_contract(contract_id)["chargeback_payable_cents"] == 24108

        respond_to_claim(
            claim_id, "DISPUTE", dispute_reason="Tier eligibility under review"
        )
        assert read_order(world["order"]["id"])["fulfillment_status"] == "DELIVERED"
        assert read_contract(contract_id)["chargeback_payable_cents"] == 0

        settle_claim(claim_id, "RESUBMIT", CONTRACT_ADMIN_USER_ID)
        assert read_order(world["order"]["id"])["fulfillment_status"] == "DELIVERED"
        assert read_claim(claim_id)["net_chargeback_cents"] == 24108
        assert read_contract(contract_id)["chargeback_payable_cents"] == 24108


class TestEmptyEligibleLineSet:
    """A delivered order with nothing chargeback-eligible is refused outright."""

    @staticmethod
    def _ineligible_delivered_world():
        return setup_glove_order(
            stage="delivered",
            room_overrides={"facility_code": "FAC-013", "room_code": "OR-CORE-13"},
            item_overrides={
                "sku": "SKU-NE-CS", "description": "Non-eligible commodity, case",
                "manufacturer_code": "MFR-ACME", "uom": "CS", "wac_cents": 12000,
                "handling_class": "AMBIENT", "units_per_parent": 24,
            },
            contract_overrides={"contract_code": "CTR-NE", "tier": "TIER_1"},
            tier_price_cents=9000,
            floor_price_cents=8000,
            chargeback_eligible=False,
            formulary_overrides={"facility_item_code": "FAC-NE", "par_qty": 400,
                                 "reorder_point": 100},
            lot_overrides={"lot_code": "LOT-NE-1", "received_quantity": 100},
            route_overrides={"route_code": "RT-13", "service_date": "2026-08-01",
                             "vehicle_class": "AMBIENT_VAN"},
        )

    def test_claim_is_refused_when_no_delivered_line_is_eligible(self, api):
        """PRD §3.9: "The claim's arithmetic runs over a strictly defined set:
        those lines of the claimed order whose `line_status` is `DELIVERED`
        **and** whose `chargeback_eligible` flag is true."
        PRD §3.9: "`eligible_line_count` records the size of that set, and an
        empty set is a hard rejection rather than a zero-value claim:
        `ERR_NO_CHARGEBACK_ELIGIBLE_LINES` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/chargeback_rejected_when_eligible_delivered_line_set_is_empty
        """
        world = self._ineligible_delivered_world()
        line = read_order_line(world["order_line"]["id"])
        assert line["line_status"] == "DELIVERED"
        assert line["chargeback_eligible"] is False

        response = api.create_chargeback_claim(
            create_chargeback_claim_payload(
                world["order"]["id"], world["contract"]["id"]
            ),
            make_contract_admin_headers(CONTRACT_ADMIN_USER_ID),
        )
        validate_error(
            response, ApiErrorId.ERR_NO_CHARGEBACK_ELIGIBLE_LINES.value, 422
        )

    def test_the_refused_claim_leaves_the_order_unbilled_and_the_ledger_empty(self, api):
        """PRD §3.9: "`eligible_line_count` records the size of that set, and an
        empty set is a hard rejection rather than a zero-value claim:
        `ERR_NO_CHARGEBACK_ELIGIBLE_LINES` (HTTP 422)."
        PRD §2.10: "`GpoContract.chargeback_payable_cents` is the sum of
        `net_chargeback_cents` over that contract's claims whose `status` is
        `SUBMITTED`, `ACCEPTED` or `RECONCILED`; it is credited when a claim
        enters that set and debited when a claim leaves it."

        Design: Difficulty/boundary_precision_check/chargeback_rejected_when_eligible_delivered_line_set_is_empty
        """
        world = self._ineligible_delivered_world()

        api.create_chargeback_claim(
            create_chargeback_claim_payload(
                world["order"]["id"], world["contract"]["id"]
            ),
            make_contract_admin_headers(CONTRACT_ADMIN_USER_ID),
        )

        _rows, meta = validate_paginated(
            api.list_chargeback_claims(
                ADMIN,
                params={"order_id": world["order"]["id"], "limit": 10, "offset": 0},
            )
        )
        assert meta["total_count"] == 0, "no claim row may be written"
        assert read_order(world["order"]["id"])["settlement_status"] == "UNBILLED"
        assert read_contract(world["contract"]["id"])["chargeback_payable_cents"] == 0


class TestContractLedgerConservation:
    """chargeback_payable_cents equals the sum of the net amounts on claims
    inside the payable set at every step."""

    def test_ledger_is_credited_on_claim_and_debited_on_dispute(self, api):
        """PRD §2.10: "`GpoContract.chargeback_payable_cents` is the sum of
        `net_chargeback_cents` over that contract's claims whose `status` is
        `SUBMITTED`, `ACCEPTED` or `RECONCILED`; it is credited when a claim
        enters that set and debited when a claim leaves it."
        PRD §3.9: "`DISPUTE` moves the claim `SUBMITTED → DISPUTED`, records the
        supplied `dispute_reason`, subtracts the claim's `net_chargeback_cents`
        from the contract's `chargeback_payable_cents`, and returns the order's
        settlement axis `CLAIMED → UNBILLED`."

        Design: Difficulty/compensating_invariant/contract_chargeback_ledger_conservation_across_claim_and_dispute
        """
        world = _glove_claim_world(
            room_overrides={"facility_code": "FAC-018", "room_code": "OR-CORE-18"},
        )
        contract_id = world["contract"]["id"]
        claim_id = world["claim"]["id"]

        claim = read_claim(claim_id)
        assert claim["gross_chargeback_cents"] == 24600
        assert claim["admin_fee_cents"] == 492
        assert claim["net_chargeback_cents"] == 24108
        assert read_contract(contract_id)["chargeback_payable_cents"] == 24108
        assert_contract_ledger_matches_claims(
            read_contract(contract_id), list_claims_of_contract(contract_id)
        )

        respond_to_claim(
            claim_id, "DISPUTE", dispute_reason="Tier eligibility under review"
        )
        assert read_claim(claim_id)["status"] == "DISPUTED"
        assert read_contract(contract_id)["chargeback_payable_cents"] == 0
        assert_contract_ledger_matches_claims(
            read_contract(contract_id), list_claims_of_contract(contract_id)
        )

    def test_ledger_holds_through_resubmit_accept_and_reconcile(self, api):
        """PRD §3.9: "`ACCEPT` moves the claim `SUBMITTED → ACCEPTED` and leaves
        the contract ledger untouched, because an accepted claim remains inside
        the payable set."
        PRD §3.9: "It moves the claim `ACCEPTED → RECONCILED`, records
        `reconciled_by_user_id`, leaves the ledger untouched because a reconciled
        claim also remains inside the payable set, and moves the order `CLAIMED →
        RECONCILED`."
        PRD §2.10: "`GpoContract.chargeback_payable_cents` is the sum of
        `net_chargeback_cents` over that contract's claims whose `status` is
        `SUBMITTED`, `ACCEPTED` or `RECONCILED`; it is credited when a claim
        enters that set and debited when a claim leaves it."

        Design: Difficulty/compensating_invariant/contract_chargeback_ledger_conservation_across_claim_and_dispute
        """
        world = _glove_claim_world(
            room_overrides={"facility_code": "FAC-018", "room_code": "OR-CORE-18"},
        )
        contract_id = world["contract"]["id"]
        claim_id = world["claim"]["id"]

        respond_to_claim(
            claim_id, "DISPUTE", dispute_reason="Tier eligibility under review"
        )
        settle_claim(claim_id, "RESUBMIT", CONTRACT_ADMIN_USER_ID)
        assert read_claim(claim_id)["status"] == "SUBMITTED"
        assert read_contract(contract_id)["chargeback_payable_cents"] == 24108

        respond_to_claim(claim_id, "ACCEPT")
        assert read_claim(claim_id)["status"] == "ACCEPTED"
        assert read_contract(contract_id)["chargeback_payable_cents"] == 24108

        reconciled = settle_claim(claim_id, "RECONCILE", "ca-2")
        assert reconciled["status"] == "RECONCILED"
        assert reconciled["reconciled_by_user_id"] == "ca-2"
        assert read_order(world["order"]["id"])["settlement_status"] == "RECONCILED"
        assert read_contract(contract_id)["chargeback_payable_cents"] == 24108
        assert_contract_ledger_matches_claims(
            read_contract(contract_id), list_claims_of_contract(contract_id)
        )
