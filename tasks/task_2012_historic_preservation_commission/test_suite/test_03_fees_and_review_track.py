"""Application fee schedule (provisional vs final variants, pinned per-item
rounding) and the review-track determination branches (PRD §2.6, §3.2, §3.3)."""
from test_helpers import (
    TEST_USERS,
    accept_application,
    begin_review,
    create_adopted_guideline_set,
    create_district,
    create_owner,
    create_property,
    submit_application,
    verified_item,
    work_item,
)

STAFF = TEST_USERS["staff_headers"]


class TestFeeProvisionalVsFinalAssessment:
    def test_provisional_fee_from_declared_items(self, api):
        """PRD §3.2: "At submission the system computes two money fields from
        the declared work items. `declared_cost_cents` is the plain sum of
        every item's `estimated_cost_cents`. `provisional_fee_cents` is the
        provisional variant of the application fee: it uses the
        applicant-declared costs and never includes a hearing surcharge."
        PRD §3.2: "an `EXTERIOR_ALTERATION` item carries a base of 15,000 cents
        and a rate of 0.4 percent of the item's cost; an `ADDITION` item a base
        of 30,000 cents at 0.5 percent; a `NEW_CONSTRUCTION` item a base of
        50,000 cents at 0.6 percent; a `DEMOLITION` item a base of 25,000 cents
        at 0.3 percent; a `RELOCATION` item a base of 40,000 cents at 0.5
        percent; and a `SITE_WORK` item a base of 10,000 cents at 0.2 percent."

        Design: Difficulty/dual_variant_calc/fee_provisional_vs_final_assessment
        """
        district = create_district(name="Old Town", significance_tier="LOCAL")
        create_adopted_guideline_set(district["id"], title="DG-1")
        owner = create_owner()
        prop = create_property(owner["id"], district_id=district["id"])

        submitted = submit_application(
            prop["id"],
            owner["id"],
            work_items=[
                work_item("EXTERIOR_ALTERATION", "repaint", 500000),
                work_item("SITE_WORK", "fence", 300000),
            ],
        )
        # 500000 + 300000 declared; per item: (15000 + 2000) + (10000 + 600).
        assert submitted["declared_cost_cents"] == 800000
        assert submitted["provisional_fee_cents"] == 27600

    def test_final_assessment_adds_hearing_surcharge(self, api):
        """PRD §3.3: "Otherwise, if `verified_cost_cents` is at least 1,000,000
        cents — ten thousand dollars — the application is `COMMISSION` track;
        the comparison is inclusive, so a verified total of exactly 1,000,000
        cents routes to the commission."
        PRD §3.3: "The final fee, stored as `assessed_fee_cents`, is the final
        variant of the §3.2 schedule applied to the verified work items — the
        same per-item base-plus-rate computation with the same pinned per-item
        rounding — plus, when the computed track is `COMMISSION`, a flat
        hearing surcharge of 20,000 cents added after the per-item sum."
        PRD §3.3: "At acceptance the `fee_balance_cents` is set equal to
        `assessed_fee_cents`; `paid_fee_cents` accumulates against it later
        (§3.5)."

        Design: Difficulty/dual_variant_calc/fee_provisional_vs_final_assessment
        """
        district = create_district(name="Old Town", significance_tier="LOCAL")
        create_adopted_guideline_set(district["id"], title="DG-1")
        owner = create_owner()
        prop = create_property(owner["id"], district_id=district["id"])
        submitted = submit_application(
            prop["id"],
            owner["id"],
            work_items=[
                work_item("EXTERIOR_ALTERATION", "repaint", 500000),
                work_item("SITE_WORK", "fence", 300000),
            ],
        )
        provisional = submitted["provisional_fee_cents"]
        begin_review(submitted["id"])

        accepted = accept_application(
            submitted["id"],
            [
                verified_item("EXTERIOR_ALTERATION", 900000),
                verified_item("SITE_WORK", 350000),
            ],
        )
        # 900000 + 350000 = 1250000 verified >= 1000000 -> COMMISSION.
        assert accepted["verified_cost_cents"] == 1250000
        assert accepted["review_track"] == "COMMISSION"
        # (15000 + 3600) + (10000 + 700) = 29300, then + 20000 surcharge.
        assert accepted["assessed_fee_cents"] == 49300
        assert accepted["fee_balance_cents"] == 49300
        assert provisional == 27600
        assert accepted["assessed_fee_cents"] != provisional, (
            "the provisional and final variants price the same application differently"
        )


class TestReviewTrackMultiBranchOverride:
    def test_track_commission_via_contributing_landmark_branch(self, api):
        """PRD §3.3: "Otherwise, if the property is `CONTRIBUTING`, the work
        `is_visible_from_public_way`, and the district's `significance_tier` is
        `LANDMARK` or `ICONIC`, the application is `COMMISSION` track; for a
        property outside any district this third branch is false by
        construction."

        Design: Difficulty/combinatorial_formula/review_track_multi_branch_override
        """
        district = create_district(name="Landmark Heights", significance_tier="LANDMARK")
        owner = create_owner()
        prop = create_property(
            owner["id"], district_id=district["id"], contributing_status="CONTRIBUTING"
        )
        submitted = submit_application(
            prop["id"],
            owner["id"],
            is_visible_from_public_way=True,
            work_items=[work_item("EXTERIOR_ALTERATION", "window replacement", 400000)],
        )
        begin_review(submitted["id"])

        accepted = accept_application(
            submitted["id"], [verified_item("EXTERIOR_ALTERATION", 500000)]
        )
        # 500000 is below the 1000000 threshold, yet the third branch forces
        # COMMISSION for CONTRIBUTING + visible + LANDMARK.
        assert accepted["verified_cost_cents"] == 500000
        assert accepted["review_track"] == "COMMISSION"

    def test_multi_branch_track_assesses_hearing_surcharge(self, api):
        """PRD §3.3: "The final fee, stored as `assessed_fee_cents`, is the
        final variant of the §3.2 schedule applied to the verified work items —
        the same per-item base-plus-rate computation with the same pinned
        per-item rounding — plus, when the computed track is `COMMISSION`, a
        flat hearing surcharge of 20,000 cents added after the per-item sum."

        Design: Difficulty/combinatorial_formula/review_track_multi_branch_override
        """
        district = create_district(name="Landmark Heights", significance_tier="LANDMARK")
        owner = create_owner()
        prop = create_property(
            owner["id"], district_id=district["id"], contributing_status="CONTRIBUTING"
        )
        submitted = submit_application(
            prop["id"],
            owner["id"],
            is_visible_from_public_way=True,
            work_items=[work_item("EXTERIOR_ALTERATION", "window replacement", 400000)],
        )
        begin_review(submitted["id"])

        accepted = accept_application(
            submitted["id"], [verified_item("EXTERIOR_ALTERATION", 500000)]
        )
        assert accepted["review_track"] == "COMMISSION"
        # 15000 + round_half_up(0.004 * 500000) = 17000, then + 20000.
        assert accepted["assessed_fee_cents"] == 37000


class TestFeePerItemRoundingOrder:
    def test_provisional_fee_rounds_per_item(self, api):
        """PRD §3.2: "Each work item's fee is its category's base amount plus
        the category's rate multiplied by the item's cost in cents, with that
        variable component rounded half-up to a whole cent; the application fee
        is then the sum of the per-item fees."

        Design: Difficulty/combinatorial_formula/fee_per_item_rounding_order
        """
        district = create_district(name="Mill District", significance_tier="LOCAL")
        owner = create_owner()
        prop = create_property(owner["id"], district_id=district["id"])
        submitted = submit_application(
            prop["id"],
            owner["id"],
            work_items=[
                work_item("EXTERIOR_ALTERATION", "siding north", 100000),
                work_item("EXTERIOR_ALTERATION", "siding south", 100000),
            ],
        )
        # 2 x (15000 + round_half_up(400.0)) = 30800.
        assert submitted["provisional_fee_cents"] == 30800

    def test_final_fee_rounds_per_item_then_sums(self, api):
        """PRD §3.2: "Rounding each item before summing is normative — summing
        unrounded products and rounding once at the end yields a different
        total and is not compliant."
        PRD §3.3: "Every remaining application is `STAFF` track."

        Design: Difficulty/combinatorial_formula/fee_per_item_rounding_order
        """
        district = create_district(name="Mill District", significance_tier="LOCAL")
        owner = create_owner()
        prop = create_property(owner["id"], district_id=district["id"])
        submitted = submit_application(
            prop["id"],
            owner["id"],
            work_items=[
                work_item("EXTERIOR_ALTERATION", "siding north", 100000),
                work_item("EXTERIOR_ALTERATION", "siding south", 100000),
            ],
        )
        begin_review(submitted["id"])

        accepted = accept_application(
            submitted["id"],
            [
                verified_item("EXTERIOR_ALTERATION", 33333),
                verified_item("EXTERIOR_ALTERATION", 33333),
            ],
        )
        # Per item: 15000 + round_half_up(133.332) = 15133; twice -> 30266.
        # The sum-then-round order would yield 30267 and is non-compliant.
        assert accepted["assessed_fee_cents"] == 30266
        assert accepted["assessed_fee_cents"] != 30267
        assert accepted["review_track"] == "STAFF"


class TestReviewTrackThresholdBoundary:
    def test_track_threshold_exact_dollar_commission(self, api):
        """PRD §3.3: "Otherwise, if `verified_cost_cents` is at least 1,000,000
        cents — ten thousand dollars — the application is `COMMISSION` track;
        the comparison is inclusive, so a verified total of exactly 1,000,000
        cents routes to the commission."

        Design: Difficulty/boundary_precision_check/review_track_threshold_exact_dollar
        """
        district = create_district(name="Old Town", significance_tier="LOCAL")
        owner = create_owner()
        prop = create_property(owner["id"], district_id=district["id"])
        submitted = submit_application(
            prop["id"],
            owner["id"],
            application_type="ADDITION",
            work_items=[work_item("ADDITION", "mudroom", 900000)],
        )
        begin_review(submitted["id"])

        accepted = accept_application(
            submitted["id"], [verified_item("ADDITION", 1000000)]
        )
        assert accepted["verified_cost_cents"] == 1000000
        assert accepted["review_track"] == "COMMISSION"

    def test_threshold_exact_dollar_assessed_with_surcharge(self, api):
        """PRD §3.3: "The final fee, stored as `assessed_fee_cents`, is the
        final variant of the §3.2 schedule applied to the verified work items —
        the same per-item base-plus-rate computation with the same pinned
        per-item rounding — plus, when the computed track is `COMMISSION`, a
        flat hearing surcharge of 20,000 cents added after the per-item sum."

        Design: Difficulty/boundary_precision_check/review_track_threshold_exact_dollar
        """
        district = create_district(name="Old Town", significance_tier="LOCAL")
        owner = create_owner()
        prop = create_property(owner["id"], district_id=district["id"])
        submitted = submit_application(
            prop["id"],
            owner["id"],
            application_type="ADDITION",
            work_items=[work_item("ADDITION", "mudroom", 900000)],
        )
        begin_review(submitted["id"])

        accepted = accept_application(
            submitted["id"], [verified_item("ADDITION", 1000000)]
        )
        # 30000 + round_half_up(0.005 * 1000000) = 35000, then + 20000.
        assert accepted["assessed_fee_cents"] == 55000


def test_track_one_dollar_below_threshold_staff(api):
    """PRD §3.3: "Otherwise, if `verified_cost_cents` is at least 1,000,000
    cents — ten thousand dollars — the application is `COMMISSION` track; the
    comparison is inclusive, so a verified total of exactly 1,000,000 cents
    routes to the commission."
    PRD §3.3: "Every remaining application is `STAFF` track."
    PRD §3.3: "The final fee, stored as `assessed_fee_cents`, is the final
    variant of the §3.2 schedule applied to the verified work items — the same
    per-item base-plus-rate computation with the same pinned per-item rounding
    — plus, when the computed track is `COMMISSION`, a flat hearing surcharge
    of 20,000 cents added after the per-item sum."

    Design: Corner/calculations/track_one_dollar_below_threshold_staff
    """
    district = create_district(name="Old Town", significance_tier="LOCAL")
    owner = create_owner()
    prop = create_property(owner["id"], district_id=district["id"])
    submitted = submit_application(
        prop["id"],
        owner["id"],
        work_items=[work_item("EXTERIOR_ALTERATION", "windows", 999999)],
    )
    begin_review(submitted["id"])

    accepted = accept_application(
        submitted["id"], [verified_item("EXTERIOR_ALTERATION", 999999)]
    )
    assert accepted["review_track"] == "STAFF"
    # 15000 + round_half_up(3999.996) = 19000; no surcharge on STAFF track.
    assert accepted["assessed_fee_cents"] == 19000
