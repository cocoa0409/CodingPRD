"""Gate passes: capacity, expiry loop, export gating, ownership."""
from test_helpers import (
    ApiErrorId,
    add_images,
    create_auction,
    create_member,
    create_seller,
    create_vehicle,
    create_yard,
    get_success_data,
    issue_gate_pass,
    list_into_auction,
    make_buyer_headers,
    make_seller_agent_headers,
    mark_ready,
    place_bid,
    prepare_vehicle,
    receive_title,
    set_clock,
    setup_closed_sale,
    setup_live_item,
    setup_paid_sale,
    submit_and_verify_export_document,
    submit_condition,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import TEST_USERS

AU = TEST_USERS["auctioneer_headers"]
YO = TEST_USERS["yard_operator_headers"]
TC = TEST_USERS["title_clerk_headers"]
PA = TEST_USERS["platform_admin_headers"]


def _sell_and_pay(api, seller, yard, member, vin, scheduled_start="2026-09-01T00:00:00Z"):
    """Run one vehicle through to a PAID sale; returns (sale, item)."""
    vehicle = prepare_vehicle(seller, yard, vin=vin)
    auction = create_auction(scheduled_start=scheduled_start)
    item = list_into_auction(auction["id"], vehicle["id"])
    get_success_data(api.start_auction(auction["id"], AU))
    get_success_data(api.open_lot(auction["id"], item["id"], AU))
    place_bid(item["id"], member, 1000000)
    sale = validate_success(api.close_lot(auction["id"], item["id"], AU), 200)
    amount = sale["winning_bid_cents"] + sale["buyer_fee_cents"]
    validate_success(
        api.pay_sale(sale["id"], {"amount_cents": amount}, make_buyer_headers(member["id"])), 201
    )
    return sale, item


class TestSlotCapacity:
    def _five_sales_setup(self, api):
        """Five paid sales at one yard, four gate passes issued for 10:00-11:00."""
        yard = create_yard()
        seller = create_seller()
        members = [
            create_member(email=f"b{i}@x.com", full_name=f"Buyer {i}") for i in range(1, 6)
        ]
        vins = [
            "1HGCM82633A004352",
            "5YJSA1E26HF1B0007",
            "1FTFW1ET5DFC10312",
            "2C4RC1BG7ER114788",
            "JN8AZ2NE6F9012345",
        ]
        sales = []
        for member, vin in zip(members, vins):
            sale, _ = _sell_and_pay(api, seller, yard, member, vin)
            sales.append(sale)
        for sale, member in zip(sales[:4], members[:4]):
            validate_success(
                api.create_gate_pass(
                    sale["id"],
                    {"slot_start": "2026-09-02T10:00:00Z", "slot_end": "2026-09-02T11:00:00Z"},
                    make_buyer_headers(member["id"]),
                ),
                201,
            )
        return sales, members

    def test_gate_pass_aggregate_capacity_five_overlapping_slots(self, api):
        """PRD §3.8: "within the one-hour window containing the new slot's start, at
        the vehicle's yard, there must be fewer than four other passes in `ISSUED` or
        `CHECKED_IN` status whose half-open intervals (start inclusive, end exclusive —
        touching boundaries do not overlap) intersect the new slot; the booking that
        would make five overlapping passes is rejected with
        `ERR_SLOT_CAPACITY_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/gate_pass_aggregate_capacity_five_overlapping_slots
        """
        sales, members = self._five_sales_setup(api)
        resp = api.create_gate_pass(
            sales[4]["id"],
            {"slot_start": "2026-09-02T10:30:00Z", "slot_end": "2026-09-02T11:30:00Z"},
            make_buyer_headers(members[4]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SLOT_CAPACITY_EXCEEDED)
        passes = get_success_data(
            api.list_sale_gate_passes(sales[4]["id"], make_buyer_headers(members[4]["id"]))
        )
        assert passes == [], f"no gate pass may be created, got {passes}"

    def test_four_overlapping_slots_accepted(self, api):
        """PRD §3.8: "within the one-hour window containing the new slot's start, at
        the vehicle's yard, there must be fewer than four other passes in `ISSUED` or
        `CHECKED_IN` status whose half-open intervals (start inclusive, end exclusive —
        touching boundaries do not overlap) intersect the new slot; the booking that
        would make five overlapping passes is rejected with
        `ERR_SLOT_CAPACITY_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/gate_pass_aggregate_capacity_five_overlapping_slots
        """
        # The four-pass occupancy itself must be accepted: capacity allows exactly 4
        # overlapping ISSUED passes in the containing window.
        sales, members = self._five_sales_setup(api)
        for sale in sales[:4]:
            passes = get_success_data(api.list_sale_gate_passes(sale["id"], AU))
            assert len(passes) == 1
            assert passes[0]["status"] == "ISSUED"

    def test_gate_pass_half_open_boundary_adjacent_slots_do_not_overlap(self, api):
        """PRD §3.8: "within the one-hour window containing the new slot's start, at
        the vehicle's yard, there must be fewer than four other passes in `ISSUED` or
        `CHECKED_IN` status whose half-open intervals (start inclusive, end exclusive —
        touching boundaries do not overlap) intersect the new slot"

        Design: Difficulty/resource_temporal_overlap/gate_pass_half_open_boundary_adjacent_slots_do_not_overlap
        """
        sales, members = self._five_sales_setup(api)
        gp = validate_success(
            api.create_gate_pass(
                sales[4]["id"],
                {"slot_start": "2026-09-02T11:00:00Z", "slot_end": "2026-09-02T12:00:00Z"},
                make_buyer_headers(members[4]["id"]),
            ),
            201,
        )
        assert gp["status"] == "ISSUED"
        passes = get_success_data(
            api.list_sale_gate_passes(sales[4]["id"], make_buyer_headers(members[4]["id"]))
        )
        assert len(passes) == 1

    def test_adjacent_then_overlapping_within_new_window(self, api):
        """PRD §3.8: "within the one-hour window containing the new slot's start, at
        the vehicle's yard, there must be fewer than four other passes in `ISSUED` or
        `CHECKED_IN` status whose half-open intervals (start inclusive, end exclusive —
        touching boundaries do not overlap) intersect the new slot; the booking that
        would make five overlapping passes is rejected with
        `ERR_SLOT_CAPACITY_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/gate_pass_half_open_boundary_adjacent_slots_do_not_overlap
        """
        sales, members = self._five_sales_setup(api)
        # Touching boundary accepted.
        gp = validate_success(
            api.create_gate_pass(
                sales[4]["id"],
                {"slot_start": "2026-09-02T11:00:00Z", "slot_end": "2026-09-02T12:00:00Z"},
                make_buyer_headers(members[4]["id"]),
            ),
            201,
        )
        assert gp["status"] == "ISSUED"
        # Control: the same sale cannot hold a second active pass regardless of slots.
        resp = api.create_gate_pass(
            sales[4]["id"],
            {"slot_start": "2026-09-02T13:00:00Z", "slot_end": "2026-09-02T14:00:00Z"},
            make_buyer_headers(members[4]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_GATE_PASS_ALREADY_ACTIVE)


class TestGatePassExpiryLoop:
    def _expired_pass_setup(self, api):
        """Paid sale closed 2026-09-10; GP1 slot after expiry; clock past expiry."""
        yard = create_yard()
        seller = create_seller()
        member = create_member()
        vehicle = prepare_vehicle(seller, yard)
        auction = create_auction(scheduled_start="2026-09-05T00:00:00Z")
        item = list_into_auction(auction["id"], vehicle["id"])
        set_clock("2026-09-10T12:00:00Z")
        get_success_data(api.start_auction(auction["id"], AU))
        get_success_data(api.open_lot(auction["id"], item["id"], AU))
        place_bid(item["id"], member, 1000000)
        sale = validate_success(api.close_lot(auction["id"], item["id"], AU), 200)
        amount = sale["winning_bid_cents"] + sale["buyer_fee_cents"]
        validate_success(
            api.pay_sale(sale["id"], {"amount_cents": amount}, make_buyer_headers(member["id"])), 201
        )
        gp1 = validate_success(
            api.create_gate_pass(
                sale["id"],
                {"slot_start": "2026-09-14T14:00:00Z", "slot_end": "2026-09-14T18:00:00Z"},
                make_buyer_headers(member["id"]),
            ),
            201,
        )
        return {"sale": sale, "member": member, "vehicle": vehicle, "gp1": gp1, "seller": seller}

    def test_expired_check_in_marks_pass_expired(self, api):
        """PRD §3.8: "the logical clock to be no later than the sale's
        `gate_pass_expires_at` — the 72-hour expiry is strict, so once the expiry
        instant has been reached or passed the check-in is rejected with
        `ERR_GATE_PASS_EXPIRED` and the pass is marked `EXPIRED` (a fresh pass may then
        be issued for the sale)"

        Design: Difficulty/non_linear_state_machine/gate_pass_expiry_reissue_loop
        """
        ctx = self._expired_pass_setup(api)
        set_clock("2026-09-14T15:00:00Z")
        resp = api.check_in_gate_pass(ctx["gp1"]["id"], YO)
        validate_error(resp, ApiErrorId.ERR_GATE_PASS_EXPIRED)
        gp1 = get_success_data(api.get_gate_pass(ctx["gp1"]["id"], YO))
        assert gp1["status"] == "EXPIRED"

class TestExportGating:
    def _export_sale_setup(self, api):
        """Sold+paid PURE vehicle won by a DE member; gate pass slot ready."""
        ctx = setup_paid_sale(member_overrides={"country_code": "DE"})
        set_clock("2026-09-02T15:00:00Z")
        gp = issue_gate_pass(ctx)
        return ctx, gp

    def test_checkin_without_verified_document_rejected(self, api):
        """PRD §3.8: "Export compliance is checked here as well: when the winner's
        `country_code` is not `US`, a `VERIFIED` export document must exist for the
        sale, else `ERR_EXPORT_DOCUMENT_REQUIRED`."

        Design: Corner/endpoints/export_flow_requires_verified_document_before_checkin
        """
        ctx, gp = self._export_sale_setup(api)
        resp = api.check_in_gate_pass(gp["id"], YO)
        validate_error(resp, ApiErrorId.ERR_EXPORT_DOCUMENT_REQUIRED)

    def test_mismatched_destination_country_rejected(self, api):
        """PRD §3.8: "the destination must equal the winning member's `country_code`,
        else `ERR_EXPORT_DOC_COUNTRY_MISMATCH` (HTTP 422)."

        Design: Corner/endpoints/export_flow_requires_verified_document_before_checkin
        """
        ctx, gp = self._export_sale_setup(api)
        resp = api.create_export_document(
            ctx["sale"]["id"],
            {"document_type": "BILL_OF_LADING", "destination_country": "FR"},
            make_buyer_headers(ctx["member"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_EXPORT_DOC_COUNTRY_MISMATCH)

    def test_verified_document_allows_checkin(self, api):
        """PRD §3.8: "Only a `VERIFIED` document satisfies the load-out gate."
        PRD §3.8: "The document begins `SUBMITTED`; a `PlatformAdmin` then verifies or
        rejects it, each action permitted only from `SUBMITTED`
        (`ERR_EXPORT_DOC_INVALID_STATE`), moving it to `VERIFIED` or `REJECTED`."

        Design: Corner/endpoints/export_flow_requires_verified_document_before_checkin
        """
        ctx, gp = self._export_sale_setup(api)
        resp = api.check_in_gate_pass(gp["id"], YO)
        validate_error(resp, ApiErrorId.ERR_EXPORT_DOCUMENT_REQUIRED)
        doc = submit_and_verify_export_document(ctx)
        assert doc["status"] == "VERIFIED"
        checked = validate_success(api.check_in_gate_pass(gp["id"], YO), 200)
        assert checked["status"] == "CHECKED_IN"


class TestOneOfEachInvariants:
    def test_title_already_exists_conflict(self, api):
        """PRD §3.2: "Exactly one title record may exist per vehicle; a second attempt
        is rejected with `ERR_TITLE_ALREADY_EXISTS`"

        Design: Corner/errors/error_title_already_exists_and_gate_pass_already_active
        """
        ctx = setup_paid_sale()
        resp = api.create_title(ctx["vehicle"]["id"], {"title_type": "CLEAN"}, TC)
        validate_error(resp, ApiErrorId.ERR_TITLE_ALREADY_EXISTS)

    def test_gate_pass_already_active_conflict(self, api):
        """PRD §3.8: "Issuance requires the sale to be `PAID` (`ERR_SALE_NOT_PAID`) and
        that no other pass for the same sale is currently `ISSUED` or `CHECKED_IN`
        (`ERR_GATE_PASS_ALREADY_ACTIVE`)."

        Design: Corner/errors/error_title_already_exists_and_gate_pass_already_active
        """
        ctx = setup_paid_sale()
        gp = issue_gate_pass(ctx)
        assert gp["status"] == "ISSUED"
        resp = api.create_gate_pass(
            ctx["sale"]["id"],
            {"slot_start": "2026-09-03T10:00:00Z", "slot_end": "2026-09-03T11:00:00Z"},
            make_buyer_headers(ctx["member"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_GATE_PASS_ALREADY_ACTIVE)
