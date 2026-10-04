"""Donation intake, receipts, the sort, and the item catalog listing."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    assert_donated_item,
    create_donation,
    create_org,
    create_site,
    create_sorted_items,
    list_items,
    make_donation_attendant_headers,
    sort_item_descriptor,
    validate_error,
    validate_paginated,
    validate_success,
)

ASSOCIATE = TEST_USERS["store_associate_headers"]


class TestDonationIntake:
    def test_donation_at_store_drop_issues_no_receipt(self, api):
        """PRD 3.2: "When the site's `site_type` is `ADC`, the new donation is
        born with `receipt_issued` true and a server-minted `receipt_token`; at
        a `STORE_DROP` site both remain false and null respectively."
        PRD 3.2: "Either way the donation's `status` begins at `RECEIVED`."

        Design: Corner/entities/donation_at_store_drop_issues_no_receipt
        """
        org = create_org("Org SD")
        site = create_site(org["id"], name="Drop Site", site_type="STORE_DROP")
        donation = create_donation(site["id"], donor_name="Walk-in", item_count=3)
        assert donation["status"] == "RECEIVED"
        assert donation["receipt_issued"] is False
        assert donation.get("receipt_token") is None
        assert donation.get("receipt_fmv_total_cents") is None

    def test_sort_materializes_items_with_grade_driven_initial_states(self, api):
        """PRD 3.2: "Each descriptor becomes a DonatedItem linked back to its
        source through `donation_id`: an item graded `UNSALABLE` is born
        directly into `SALVAGED` status, while every other grade is born
        `SORTED`."
        PRD 3.2: "The sort completes by stamping `sorted_at` with the logical
        clock, and it is only permitted while the donation is still `RECEIVED`
        and the organization is `ACTIVE`."

        Design: Corner/entities/sort_materializes_items_with_grade_driven_initial_states
        """
        org = create_org("Org Init")
        site = create_site(org["id"], name="Site I")
        donation, items = create_sorted_items(
            site["id"],
            [sort_item_descriptor(category="TEXTILES", condition_grade="B",
                                  estimated_value_cents=200, weight_lbs=3),
             sort_item_descriptor(category="EWASTE", condition_grade="UNSALABLE",
                                  estimated_value_cents=0, weight_lbs=8)])
        assert len(items) == 2
        sorted_rows = list_items({"donation_id": donation["id"], "status": "SORTED"})
        salvaged_rows = list_items({"donation_id": donation["id"], "status": "SALVAGED"})
        assert len(sorted_rows) == 1 and sorted_rows[0]["condition_grade"] == "B"
        assert len(salvaged_rows) == 1
        assert salvaged_rows[0]["condition_grade"] == "UNSALABLE"
        assert salvaged_rows[0].get("price_cents") is None
        for item in items:
            assert_donated_item(item)
            assert item["donation_id"] == donation["id"]
        assert donation["status"] == "SORTED"
        assert donation.get("sorted_at")

    def test_donated_items_list_paginates_with_filters(self, api):
        """PRD 2.3: "The `limit` parameter caps the number of items returned; it
        defaults to 10, with a minimum of 1 and a maximum of 100. The `offset`
        parameter skips a number of items from the start of the result set and
        defaults to 0."
        PRD 2.3: "The `meta` object of a list response carries the pagination
        fields `limit`, `offset`, `total_count`, and `has_more`."
        PRD 3.3: "The item catalog can be browsed with filters on
        `donation_id`, `salvage_lot_id`, `status`, `color_tag`, and
        `priced_standard_id`."

        Design: Corner/entities/donated_items_list_paginates_with_filters
        """
        org = create_org("Org Page")
        site = create_site(org["id"], name="Site P")
        donation, _items = create_sorted_items(
            site["id"],
            [sort_item_descriptor(category="TEXTILES", condition_grade="A",
                                  estimated_value_cents=100, weight_lbs=1),
             sort_item_descriptor(category="TEXTILES", condition_grade="A",
                                  estimated_value_cents=100, weight_lbs=1),
             sort_item_descriptor(category="MEDIA", condition_grade="UNSALABLE",
                                  estimated_value_cents=0, weight_lbs=2)])
        page1, meta1 = validate_paginated(api_client.list_donated_items(
            ASSOCIATE,
            params={"donation_id": donation["id"], "limit": 2, "offset": 0}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(api_client.list_donated_items(
            ASSOCIATE,
            params={"donation_id": donation["id"], "limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

        salvaged, meta3 = validate_paginated(api_client.list_donated_items(
            ASSOCIATE,
            params={"donation_id": donation["id"], "status": "SALVAGED"}))
        assert len(salvaged) == 1
        assert meta3["total_count"] == 1

    def test_sort_a_sorted_donation_returns_invalid_state(self, api):
        """PRD 3.2: "Sorting is the attendant's second act and moves the
        donation from `RECEIVED` to `SORTED`, its terminal state."
        PRD 3.2: "The sort completes by stamping `sorted_at` with the logical
        clock, and it is only permitted while the donation is still `RECEIVED`
        and the organization is `ACTIVE`."

        Design: Corner/state_machines/sort_a_sorted_donation_returns_invalid_state
        """
        org = create_org("Org S2")
        site = create_site(org["id"], name="Site S2")
        donation, items = create_sorted_items(
            site["id"],
            [sort_item_descriptor(category="MEDIA", condition_grade="C",
                                  estimated_value_cents=50, weight_lbs=1)])
        assert len(items) == 1
        resp = api_client.sort_donation(
            donation["id"],
            {"items": [sort_item_descriptor(category="MEDIA", condition_grade="C",
                                            estimated_value_cents=50, weight_lbs=1)]},
            make_donation_attendant_headers(site["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        remaining = list_items({"donation_id": donation["id"]})
        assert len(remaining) == 1, "rejected re-sort must not duplicate items"

    def test_sort_with_wrong_item_count_rejected(self, api):
        """PRD 3.2: "The number of descriptors must equal the donation's
        `item_count_declared` exactly; a mismatch is rejected with
        `ERR_ITEM_COUNT_MISMATCH`."

        Design: Corner/validations/sort_with_wrong_item_count_rejected
        """
        org = create_org("Org IC")
        site = create_site(org["id"], name="Site IC")
        donation = create_donation(site["id"], donor_name="DIC", item_count=2)
        resp = api_client.sort_donation(
            donation["id"],
            {"items": [sort_item_descriptor(category="MEDIA", condition_grade="B",
                                            estimated_value_cents=60, weight_lbs=1)]},
            make_donation_attendant_headers(site["id"]))
        validate_error(resp, ApiErrorId.ERR_ITEM_COUNT_MISMATCH)
        after = validate_success(api_client.get_donation(
            donation["id"], make_donation_attendant_headers(site["id"])))
        assert after["status"] == "RECEIVED"
        assert list_items({"donation_id": donation["id"]}) == []
