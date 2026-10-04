"""Depth tests: transitive cascades.

An egregious humane confirmation cascades three hops (event -> IN_EFFECT
suspension -> establishment suspension -> blocked windows and held labels),
and a pathogen result recording cascades two hops (result -> recomputed
category -> auto-created notice on the CAT_3 transition).
"""

from test_helpers import (
    DISTRICT_MANAGER_HEADERS,
    assert_enforcement_action,
    assert_instant,
    fixtures as fx,
    validate_success,
)


def _granted_beef_with_pair(api, name="D8 Beef Plant"):
    base = fx.create_granted_establishment(api, species_classes=["CATTLE"], name=name)
    pair = fx.create_inspector_pair(api, ["CATTLE"])
    return base, pair


class TestEgregiousHumaneConfirmCascade:
    def test_confirm_suspends_establishment_blocks_window_holds_label(self, api):
        """PRD §3.5: "A confirmed `EGREGIOUS` event exercises the agency's
        immediate suspension authority: in the same request, the system creates
        an enforcement action with `action_type` `SUSPENSION`, `basis`
        `EGREGIOUS_HUMANE`, `status` `IN_EFFECT`, `auto_created` true, and
        `effective_at` stamped from the logical clock — and that action's
        activation cascade fires immediately, exactly as in §3.4: the
        establishment's `inspection_status` moves to `SUSPENDED`, its
        `suspension_count` increments by 1, its planned and gap-flagged shift
        windows move to `BLOCKED`, and its in-review label applications move to
        `HELD`."

        Design: Difficulty/transitive_cascade/egregious_humane_confirm_suspends_and_blocks
        """
        base, pair = _granted_beef_with_pair(api)
        est_id = base["establishment"]["id"]
        window = fx.create_shift_window(api, est_id)  # PLANNED SLAUGHTER window
        label = fx.create_label_in_review(
            api, est_id, product_name="Breed Steak", label_claim="BREED_SPECIFIC",
            documentation_refs=["doc-breed-1"],
        )
        event = fx.report_humane_event(
            api, est_id, pair["issuer"]["id"], species="CATTLE", severity="EGREGIOUS",
            observed_at="2026-08-31T07:00:00Z", description="dragging a non-ambulatory animal",
        )

        confirmed = fx.confirm_humane_event(api, event["id"], pair["reviewer"]["id"])

        assert confirmed["status"] == "CONFIRMED"
        actions = fx.list_enforcement_actions(api, est_id)
        assert len(actions) == 1, f"exactly one auto-created action, got {len(actions)}"
        action = actions[0]
        assert_enforcement_action(action)
        assert action["action_type"] == "SUSPENSION"
        assert action["basis"] == "EGREGIOUS_HUMANE"
        assert action["status"] == "IN_EFFECT"
        assert action["auto_created"] is True
        est = fx.get_establishment(api, est_id)
        assert est["inspection_status"] == "SUSPENDED"
        assert est["suspension_count"] == 1
        assert est["grant_status"] == "GRANTED", "suspension leaves the grant dimension alone"
        blocked = fx.get_shift_window(api, window["id"])
        assert blocked["status"] == "BLOCKED", "hop 3: PLANNED window blocked by the suspension"
        labels = fx.list_label_applications(api, est_id)
        assert len(labels) == 1 and labels[0]["id"] == label["id"]
        assert labels[0]["status"] == "HELD", "hop 3: in-review label held by the suspension"

    def test_auto_action_stamps_effective_at_and_advances_parent_version(self, api):
        """PRD §3.5: "in the same request, the system creates an enforcement
        action with `action_type` `SUSPENSION`, `basis` `EGREGIOUS_HUMANE`,
        `status` `IN_EFFECT`, `auto_created` true, and `effective_at` stamped
        from the logical clock"
        PRD §2.11: "Each cascade mutates every resource it touches, refreshing
        that resource's `updated_at` and incrementing its `version` per §2.6 —
        so the establishment's `version` advances on every grant, suspension,
        withdrawal, and lift that touches it, and a shift window's `version`
        advances on every assignment created against it."

        Design: Difficulty/transitive_cascade/egregious_humane_confirm_suspends_and_blocks
        """
        base, pair = _granted_beef_with_pair(api, name="D8 Version Plant")
        est_id = base["establishment"]["id"]
        before = fx.get_establishment(api, est_id)
        event = fx.report_humane_event(
            api, est_id, pair["issuer"]["id"], species="CATTLE", severity="EGREGIOUS",
            observed_at="2026-08-31T07:00:00Z", description="conscious animal hoisted",
        )

        fx.confirm_humane_event(api, event["id"], pair["reviewer"]["id"])

        actions = fx.list_enforcement_actions(api, est_id)
        assert len(actions) == 1
        action = actions[0]
        assert_instant(action["effective_at"], fx.CLOCK_START_ISO, "effective_at stamped from the logical clock")
        after = fx.get_establishment(api, est_id)
        assert after["version"] > before["version"], (
            f"the suspension cascade advances the establishment version ({before['version']} -> {after['version']})"
        )
        assert after["suspension_count"] == 1


class TestSalmonellaCat3AutoNotice:
    def _granted_poultry_with_ten_pending(self, api):
        base = fx.create_granted_establishment(api, species_classes=["POULTRY"], name="D9 Poultry Plant")
        inspector = fx.create_inspector(api, species_qualifications=["POULTRY"])
        samples = fx.collect_pathogen_samples(
            api, base["establishment"]["id"], inspector["id"], "SALMONELLA", 10
        )
        return base["establishment"], inspector, samples

    def test_tenth_result_crossing_standard_creates_in_effect_notice(self, api):
        """PRD §3.6: "The boundaries are pinned: a rate exactly equal to the
        standard rate is `CAT_2`, never `CAT_3`; a rate exactly equal to half
        the standard is `CAT_1`. The standard rates are 0.10 for `SALMONELLA`
        and 0.15 for `CAMPYLOBACTER`."
        PRD §3.6: "Whenever a result recording causes any pathogen's recomputed
        category to transition to `CAT_3` from a different value, the system
        automatically creates an enforcement action against the establishment
        in the same request: `action_type` `NOTICE_OF_INTENDED_ENFORCEMENT`,
        `basis` `CATEGORY_3_PATHOGEN`, `status` `IN_EFFECT`, `auto_created`
        true, and `effective_at` stamped from the logical clock."

        Design: Difficulty/transitive_cascade/salmonella_cat3_auto_notice
        """
        est, inspector, samples = self._granted_poultry_with_ten_pending(api)
        fx.record_sample_result(api, samples[0]["id"], inspector["id"], "POSITIVE")
        for sample in samples[1:9]:
            fx.record_sample_result(api, sample["id"], inspector["id"], "NEGATIVE")
        assert fx.list_enforcement_actions(api, est["id"]) == [], (
            "no enforcement before the 10th result lands"
        )

        fx.record_sample_result(api, samples[9]["id"], inspector["id"], "POSITIVE")

        data = validate_success(api.get_establishment(est["id"], DISTRICT_MANAGER_HEADERS), 200)
        # 2/10 == 0.20 exceeds the 0.10 SALMONELLA standard -> CAT_3.
        assert data["pathogen_category"] == "CAT_3", (
            f"2/10 > 0.10: expected CAT_3, got {data['pathogen_category']!r}"
        )
        actions = fx.list_enforcement_actions(api, est["id"])
        assert len(actions) == 1, f"exactly one auto-created notice, got {len(actions)}"
        notice = actions[0]
        assert_enforcement_action(notice)
        assert notice["action_type"] == "NOTICE_OF_INTENDED_ENFORCEMENT"
        assert notice["basis"] == "CATEGORY_3_PATHOGEN"
        assert notice["status"] == "IN_EFFECT"
        assert notice["auto_created"] is True
        assert_instant(notice["effective_at"], fx.CLOCK_START_ISO, "notice effective_at")

    def test_insufficient_results_leave_category_null_and_no_actions(self, api):
        """PRD §3.6: "Fewer than 10 resulted samples means that pathogen
        contributes no categorization at all."
        PRD §3.6: "If no pathogen has sufficient samples, the category is
        unchanged (null if the establishment has never been categorized)."

        Design: Difficulty/transitive_cascade/salmonella_cat3_auto_notice
        """
        est, inspector, samples = self._granted_poultry_with_ten_pending(api)
        fx.record_sample_result(api, samples[0]["id"], inspector["id"], "POSITIVE")
        for sample in samples[1:9]:
            fx.record_sample_result(api, sample["id"], inspector["id"], "NEGATIVE")

        data = validate_success(api.get_establishment(est["id"], DISTRICT_MANAGER_HEADERS), 200)
        assert data["pathogen_category"] is None, (
            f"9 resulted samples: expected null category, got {data['pathogen_category']!r}"
        )
        assert fx.list_enforcement_actions(api, est["id"]) == []

        # The tenth PENDING sample still has not been resulted.
        pending = validate_success(
            api.get_pathogen_sample(samples[9]["id"], DISTRICT_MANAGER_HEADERS), 200
        )
        assert pending["result"] == "PENDING"
        assert pending["resulted_at"] is None
