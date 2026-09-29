"""Single writes whose consequences propagate three or more hops away from the
entity that was touched.
"""

from test_helpers import fixtures as fx


class TestApplyCascadeCommitsAndOpensExitWindow:
    """One apply walks item, rungs, reservations, stores and the season."""

    def test_the_waterfall_fills_the_largest_free_bay_first_and_skips_remodel(
        self, api
    ):
        """PRD 3.7: "Those candidates are ordered by `available_clearance_units`
        descending, then by `store_number` ascending, then by `created_at`
        ascending, so the largest free bay is filled first and ties resolve
        deterministically." PRD 3.4: "Only `OPEN` stores are candidates for
        clearance allocation — a store in `REMODEL` or `CLOSING` is skipped even
        when its bays are empty — and a duplicate `store_number`, like a duplicate
        `zone_code`, is refused with `ERR_DUPLICATE_RESOURCE`".

        Design: Difficulty/transitive_cascade/apply_cascade_commits_reservations_and_opens_exit_window
        """
        sc = fx.allocated_scenario(api, total_units=600)

        res1, res2 = sc.reservations[0], sc.reservations[1]

        assert res1["reserved_units"] == 500
        assert res1["allocation_rank"] == 1
        assert res1["store_id"] == sc.store_0202["id"]

        assert res2["reserved_units"] == 100
        assert res2["allocation_rank"] == 2
        assert res2["store_id"] == sc.store_0101["id"]

        assert sc.store_0303["id"] not in [r["store_id"] for r in sc.reservations]

    def test_applying_marks_the_item_and_commits_every_reservation(self, api):
        """PRD 3.6: "Hop three re-runs lifecycle classification, which for a
        permanently marked item carries the lifecycle dimension into `CLEARANCE`.
        Hop four follows from that reclassification: every clearance reservation of
        this plan still in `RESERVED` moves to `COMMITTED`, so the season's
        `reserved_clearance_units` falls and its `committed_clearance_units` rises
        by the same units."

        Design: Difficulty/transitive_cascade/apply_cascade_commits_reservations_and_opens_exit_window
        """
        sc = fx.exit_window_scenario(api, total_units=600)

        assert sc.execution["status"] == "APPLIED"
        assert sc.item["markdown_state"] == "PERM_MARKED"
        assert sc.item["lifecycle_stage"] == "CLEARANCE"
        assert sc.item["current_retail_cents"] == 3871

        for reservation in sc.reservations:
            assert fx.read_reservation(api, reservation["id"])["status"] == "COMMITTED"

    def test_the_committed_units_pull_the_season_into_its_exit_window(self, api):
        """PRD 3.7: "Whenever a reservation entering `COMMITTED` lifts the season's
        `committed_clearance_units` to at least 60 percent of the season's
        `exit_units_target` — that is, to at least the `exit_units_target`
        multiplied by 60.00, divided by 100 and rounded half up to a whole unit — a
        season still in `ACTIVE` moves `ACTIVE → EXIT_WINDOW` on the spot."

        Design: Difficulty/transitive_cascade/apply_cascade_commits_reservations_and_opens_exit_window
        """
        sc = fx.exit_window_scenario(api, total_units=600)

        season = fx.read_season(api, sc.season["id"])

        assert season["reserved_clearance_units"] == 0
        assert season["committed_clearance_units"] == 600
        assert season["status"] == "EXIT_WINDOW"

    def test_each_store_counter_reflects_the_units_it_absorbed(self, api):
        """PRD 3.4: "Thereafter `committed_clearance_units` is maintained as the sum
        of `reserved_units` across the store's reservations that are `RESERVED` or
        `COMMITTED`, and `available_clearance_units` is always the bay capacity less
        that committed sum."

        Design: Difficulty/transitive_cascade/apply_cascade_commits_reservations_and_opens_exit_window
        """
        sc = fx.exit_window_scenario(api, total_units=600)

        store_0202 = fx.read_store(api, sc.store_0202["id"])
        store_0101 = fx.read_store(api, sc.store_0101["id"])

        assert store_0202["committed_clearance_units"] == 500
        assert store_0202["available_clearance_units"] == 0
        assert store_0101["committed_clearance_units"] == 100
        assert store_0101["available_clearance_units"] == 200

    def test_the_plan_and_the_rung_move_with_the_cascade(self, api):
        """PRD 3.6: "Alongside the cascade, the plan's `gross_markdown_cents` grows
        by `line_markdown_cents`, its `net_markdown_cents` is recomputed, and the
        plan moves `APPROVED → EXECUTING` on its first applied execution."

        Design: Difficulty/transitive_cascade/apply_cascade_commits_reservations_and_opens_exit_window
        """
        sc = fx.exit_window_scenario(api, total_units=600)

        plan = fx.read_plan(api, sc.plan["id"])

        assert plan["status"] == "COMPLETED"
        assert plan["gross_markdown_cents"] == 225600
        assert fx.read_step(api, sc.step1["id"])["status"] == "EXECUTED"


class TestClaimRecognitionCascade:
    """Recognising one claim funds the agreement and kills its siblings."""

    def test_the_first_claim_is_recognised_up_to_the_agreement_cap(self, api):
        """PRD 3.8: "Fourth, the amount actually recognised is the smallest of three
        quantities in that order: the claim's `claimed_cents`, the plan headroom,
        and the agreement's `remaining_cap_cents`."

        Design: Difficulty/transitive_cascade/claim_recognition_cascade_funds_agreement_and_rejects_sibling
        """
        sc = fx.executing_plan_with_agreement(api, share_pct=25.00, cap_cents=56400)
        claim1 = fx.create_claim(api, sc.agreement["id"], sc.plan["id"], 56400)
        fx.create_claim(api, sc.agreement["id"], sc.plan["id"], 10000)

        recognized = fx.recognize_claim(api, claim1["id"])

        assert recognized["status"] == "RECOGNIZED"
        assert recognized["recognized_cents"] == 56400

    def test_exhausting_the_cap_funds_the_agreement(self, api):
        """PRD 3.8: "Hop three fires when that remaining cap has reached exactly 0:
        the agreement moves `AGREED → FUNDED`."

        Design: Difficulty/transitive_cascade/claim_recognition_cascade_funds_agreement_and_rejects_sibling
        """
        sc = fx.executing_plan_with_agreement(api, share_pct=25.00, cap_cents=56400)
        claim1 = fx.create_claim(api, sc.agreement["id"], sc.plan["id"], 56400)
        fx.create_claim(api, sc.agreement["id"], sc.plan["id"], 10000)

        fx.recognize_claim(api, claim1["id"])
        agreement = fx.read_agreement(api, sc.agreement["id"])

        assert agreement["recognized_total_cents"] == 56400
        assert agreement["remaining_cap_cents"] == 0
        assert agreement["status"] == "FUNDED"

    def test_funding_the_agreement_rejects_the_still_submitted_sibling(self, api):
        """PRD 3.8: "Hop four follows from the agreement being funded — every other
        claim of that agreement still in `SUBMITTED` moves to `REJECTED` with its
        `rejection_reason` set to `CAP_EXHAUSTED` and its `recognized_cents` left
        at 0."

        Design: Difficulty/transitive_cascade/claim_recognition_cascade_funds_agreement_and_rejects_sibling
        """
        sc = fx.executing_plan_with_agreement(api, share_pct=25.00, cap_cents=56400)
        claim1 = fx.create_claim(api, sc.agreement["id"], sc.plan["id"], 56400)
        claim2 = fx.create_claim(api, sc.agreement["id"], sc.plan["id"], 10000)

        fx.recognize_claim(api, claim1["id"])
        sibling = fx.read_claim(api, claim2["id"])

        assert sibling["status"] == "REJECTED"
        assert sibling["rejection_reason"] == "CAP_EXHAUSTED"
        assert sibling["recognized_cents"] == 0

    def test_the_rejected_sibling_restates_the_plan_net_markdown(self, api):
        """PRD 3.8: "Hop five follows from those rejections: each rejected sibling's
        plan recomputes its `vendor_funded_cents` and restates `net_markdown_cents`
        as gross less vendor-funded."

        Design: Difficulty/transitive_cascade/claim_recognition_cascade_funds_agreement_and_rejects_sibling
        """
        sc = fx.executing_plan_with_agreement(api, share_pct=25.00, cap_cents=56400)
        claim1 = fx.create_claim(api, sc.agreement["id"], sc.plan["id"], 56400)
        fx.create_claim(api, sc.agreement["id"], sc.plan["id"], 10000)

        fx.recognize_claim(api, claim1["id"])
        plan = fx.read_plan(api, sc.plan["id"])

        assert plan["gross_markdown_cents"] == 225600
        assert plan["vendor_funded_cents"] == 56400
        assert plan["net_markdown_cents"] == 169200

    def test_the_agreement_cap_conservation_invariant_survives_the_cascade(self, api):
        """PRD 2.9: "Second, an agreement's `funding_cap_cents` always equals its
        `remaining_cap_cents` plus the sum of `recognized_cents` across its
        `RECOGNIZED` claims; recognising a claim and then reversing it must restore
        both sides."

        Design: Difficulty/transitive_cascade/claim_recognition_cascade_funds_agreement_and_rejects_sibling
        """
        sc = fx.executing_plan_with_agreement(api, share_pct=25.00, cap_cents=56400)
        claim1 = fx.create_claim(api, sc.agreement["id"], sc.plan["id"], 56400)
        fx.create_claim(api, sc.agreement["id"], sc.plan["id"], 10000)
        fx.recognize_claim(api, claim1["id"])

        agreement = fx.read_agreement(api, sc.agreement["id"])
        claims = fx.list_claims_of_agreement(api, sc.agreement["id"])
        recognized_sum = sum(
            c["recognized_cents"] for c in claims if c["status"] == "RECOGNIZED"
        )

        assert agreement["funding_cap_cents"] == (
            agreement["remaining_cap_cents"] + recognized_sum
        )
        assert recognized_sum == 56400
