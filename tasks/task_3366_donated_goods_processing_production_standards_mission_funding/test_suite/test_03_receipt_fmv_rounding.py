"""Donor receipt FMV: pinned per-item rounding order (Difficulty queue)."""
from test_helpers import (
    create_donation,
    create_org,
    create_site,
    list_items,
    sort_donation,
    sort_item_descriptor,
)

# The pinned example from the PRD: A@100, B@101, C@99, UNSALABLE@500.
FMV_ITEMS = [
    sort_item_descriptor(category="TEXTILES", condition_grade="A",
                         estimated_value_cents=100, weight_lbs=1),
    sort_item_descriptor(category="HOUSEWARES", condition_grade="B",
                         estimated_value_cents=101, weight_lbs=1),
    sort_item_descriptor(category="MEDIA", condition_grade="C",
                         estimated_value_cents=99, weight_lbs=1),
    sort_item_descriptor(category="FURNITURE", condition_grade="UNSALABLE",
                         estimated_value_cents=500, weight_lbs=1),
]


def _setup_adc_donation():
    org = create_org("Org FMV")
    site = create_site(org["id"], name="Site F")
    donation = create_donation(site["id"], donor_name="Donor F", item_count=4)
    return site, donation


class TestReceiptFmvPerItemRoundingOrder:
    def test_receipt_total_rounds_each_item_before_summing(self, api):
        """PRD 3.2: "Each item's `estimated_value_cents` is multiplied by its
        grade's condition multiplier — full value for grade `A`, three quarters
        for `B`, one half for `C`, and zero for `UNSALABLE` — and each product
        is rounded half-up to whole cents *per item*; the donation's
        `receipt_fmv_total_cents` is then the sum of those per-item rounded
        values."
        PRD 3.2: "Consider items estimated at 100 cents (`A`), 101 cents (`B`),
        99 cents (`C`), and 500 cents (`UNSALABLE`): the per-item rounded
        contributions are 100, 76, 50, and 0, totaling 226 cents — whereas
        summing the raw products first and rounding once would yield 225, a
        plausible-looking but forbidden result."

        Design: Difficulty/combinatorial_formula/receipt_fmv_per_item_rounding_order
        """
        site, donation = _setup_adc_donation()
        sorted_donation = sort_donation(site["id"], donation["id"], FMV_ITEMS)
        assert sorted_donation["receipt_fmv_total_cents"] == 226, (
            "per-item round-then-sum is the only sanctioned variant: "
            "100 + round_half_up(75.75)=76 + round_half_up(49.50)=50 + 0 = 226")
        assert sorted_donation["status"] == "SORTED"
        assert sorted_donation.get("sorted_at")

    def test_adc_sort_issues_receipt_and_materializes_items(self, api):
        """PRD 3.2: "When the site's `site_type` is `ADC`, the new donation is
        born with `receipt_issued` true and a server-minted `receipt_token`; at
        a `STORE_DROP` site both remain false and null respectively."
        PRD 3.2: "Each descriptor becomes a DonatedItem linked back to its
        source through `donation_id`: an item graded `UNSALABLE` is born
        directly into `SALVAGED` status, while every other grade is born
        `SORTED`."

        Design: Difficulty/combinatorial_formula/receipt_fmv_per_item_rounding_order
        """
        site, donation = _setup_adc_donation()
        sorted_donation = sort_donation(site["id"], donation["id"], FMV_ITEMS)
        assert sorted_donation["receipt_issued"] is True
        assert sorted_donation.get("receipt_token")
        items = list_items({"donation_id": donation["id"], "limit": 100})
        assert len(items) == 4
        by_grade = {i["condition_grade"]: i["status"] for i in items}
        assert by_grade["A"] == "SORTED"
        assert by_grade["B"] == "SORTED"
        assert by_grade["C"] == "SORTED"
        assert by_grade["UNSALABLE"] == "SALVAGED"
