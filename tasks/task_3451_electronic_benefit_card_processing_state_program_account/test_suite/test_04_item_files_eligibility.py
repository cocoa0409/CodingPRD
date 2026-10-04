"""Retailer item files: atomic upload validation, half-open eligibility
windows, and point-of-sale item eligibility under STRICT and LENIENT modes."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    make_retailer_system_headers,
    validate_error,
    validate_success,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx

ADMIN = TEST_USERS["state_admin_headers"]


class TestItemFileUpload:
    def test_upc_format_violation_rejects_whole_file(self, api):
        """PRD §3.2: "Every entry is validated, and any failure rejects the
        whole file: a `upc` failing the twelve-digit format rejects the file
        with `ERR_UPC_INVALID`, and an entry whose half-open window — running
        from `effective_from` inclusive up to but not including `effective_to` —
        overlaps an existing record for the same `retailer_id` and `upc` pair is
        rejected with `ERR_ITEM_WINDOW_OVERLAP`, where pure adjacency is
        allowed."

        Design: Corner/validations/upc_format_violation_rejects_whole_file
        """
        ctx = fx.setup_active_contract(api)
        fx.add_retailer(api, ctx, with_item_file=False)
        retailer_id = ctx.retailer["id"]
        resp = api.upload_item_file(
            retailer_id,
            f.item_file_payload([f.item_entry(upc="123")]),
            make_retailer_system_headers(retailer_id),
        )
        validate_error(resp, ApiErrorId.ERR_UPC_INVALID)
        # Atomic rejection: no RetailerItem rows exist afterwards.
        assert fx.list_retailer_items(api, retailer_id) == [], (
            "a rejected file must create no item records"
        )

    def test_item_window_overlap_rejected_adjacency_allowed(self, api):
        """PRD §3.2: "an entry whose half-open window — running from
        `effective_from` inclusive up to but not including `effective_to` —
        overlaps an existing record for the same `retailer_id` and `upc` pair is
        rejected with `ERR_ITEM_WINDOW_OVERLAP`, where pure adjacency is
        allowed."

        Design: Difficulty/resource_temporal_overlap/item_window_half_open_overlap_rejected_adjacency_allowed
        """
        ctx = fx.setup_active_contract(api)
        fx.add_retailer(api, ctx, item_entries=[
            f.item_entry(upc="333333333333", effective_from="2026-09-01",
                         effective_to="2026-10-01"),
        ])
        retailer_id = ctx.retailer["id"]
        headers = make_retailer_system_headers(retailer_id)
        # Overlap: [2026-09-15, 2026-11-01) intersects [2026-09-01, 2026-10-01).
        resp = api.upload_item_file(
            retailer_id,
            f.item_file_payload([f.item_entry(
                upc="333333333333", food_eligible=False,
                effective_from="2026-09-15", effective_to="2026-11-01")]),
            headers,
        )
        validate_error(resp, ApiErrorId.ERR_ITEM_WINDOW_OVERLAP)
        # Adjacency (from == previous effective_to) is not a conflict.
        resp2 = api.upload_item_file(
            retailer_id,
            f.item_file_payload([f.item_entry(
                upc="333333333333", food_eligible=False,
                effective_from="2026-10-01", effective_to="2026-12-01")]),
            headers,
        )
        created = validate_success(resp2, 201)
        assert created["created_count"] == 1

    def test_item_window_leading_adjacency_allowed_containment_rejected(self, api):
        """PRD §3.2: "an entry whose half-open window — running from
        `effective_from` inclusive up to but not including `effective_to` —
        overlaps an existing record for the same `retailer_id` and `upc` pair is
        rejected with `ERR_ITEM_WINDOW_OVERLAP`, where pure adjacency is
        allowed."

        Design: Difficulty/resource_temporal_overlap/item_window_half_open_overlap_rejected_adjacency_allowed
        """
        ctx = fx.setup_active_contract(api)
        fx.add_retailer(api, ctx, item_entries=[
            f.item_entry(upc="333333333333", effective_from="2026-09-01",
                         effective_to="2026-10-01"),
        ])
        retailer_id = ctx.retailer["id"]
        headers = make_retailer_system_headers(retailer_id)
        # Adjacent before: [2026-08-01, 2026-09-01) ends exactly where the
        # existing record begins — half-open adjacency is allowed.
        resp = api.upload_item_file(
            retailer_id,
            f.item_file_payload([f.item_entry(
                upc="333333333333", food_eligible=False,
                effective_from="2026-08-01", effective_to="2026-09-01")]),
            headers,
        )
        created = validate_success(resp, 201)
        assert created["created_count"] == 1
        # [2026-08-15, 2026-09-15) overlaps both stored windows.
        resp2 = api.upload_item_file(
            retailer_id,
            f.item_file_payload([f.item_entry(
                upc="333333333333", food_eligible=False,
                effective_from="2026-08-15", effective_to="2026-09-15")]),
            headers,
        )
        validate_error(resp2, ApiErrorId.ERR_ITEM_WINDOW_OVERLAP)


class TestPointOfSaleEligibility:
    def test_unknown_upc_strict_mode_rejected(self, api):
        """PRD §3.7: "Under `STRICT`, a line whose UPC has no covering `ACTIVE`
        item record — unknown or expired — is rejected with
        `ERR_ITEM_NOT_ELIGIBLE`."

        Design: Corner/validations/unknown_upc_strict_mode_rejected
        """
        ctx = fx.setup_pos_ready(api)  # FOOD program, STRICT by default
        retailer_id = ctx.retailer["id"]
        resp = api.create_authorization(
            retailer_id,
            f.purchase_payload(ctx.card["id"], items=[
                f.purchase_item(upc="999999999999", unit_price_cents=100)]),
            make_retailer_system_headers(retailer_id),
        )
        validate_error(resp, ApiErrorId.ERR_ITEM_NOT_ELIGIBLE)

    def test_unknown_upc_lenient_mode_allowed_with_exception_flag(self, api):
        """PRD §3.7: "Under `LENIENT`, a line with an unknown UPC is treated as
        food-eligible and counted in the transaction's `exception_flag_count`."

        Design: Corner/validations/unknown_upc_lenient_mode_allowed_with_exception_flag
        """
        ctx = fx.setup_pos_ready(
            api, program_overrides={"FOOD": {"item_restriction_mode": "LENIENT"}})
        txn = fx.place_purchase(
            api, ctx.retailer["id"], ctx.card["id"],
            items=[f.purchase_item(upc="999999999999", unit_price_cents=100)],
        )
        assert txn["exception_flag_count"] == 1, (
            f"unknown UPC under LENIENT must flag one exception, got {txn['exception_flag_count']}"
        )
        assert txn["food_charge_cents"] == 100
        assert txn["total_cents"] == 100

    def test_non_food_cart_without_cash_purse_rejected(self, api):
        """PRD §3.7: "If the cash total is positive and the case has no cash
        purse that is not `CLOSED`, the authorization is rejected with
        `ERR_NO_CASH_PURSE` — a non-food charge with no cash purse to absorb it
        reports this error rather than an eligibility error."

        Design: Corner/validations/non_food_cart_without_cash_purse_rejected
        """
        ctx = fx.setup_pos_ready(api, item_entries=[
            f.item_entry(upc="222222222222", food_eligible=False),
        ])  # FOOD-only contract; the case holds no CASH purse
        retailer_id = ctx.retailer["id"]
        resp = api.create_authorization(
            retailer_id,
            f.purchase_payload(ctx.card["id"], items=[
                f.purchase_item(upc="222222222222", unit_price_cents=300)]),
            make_retailer_system_headers(retailer_id),
        )
        validate_error(resp, ApiErrorId.ERR_NO_CASH_PURSE)
