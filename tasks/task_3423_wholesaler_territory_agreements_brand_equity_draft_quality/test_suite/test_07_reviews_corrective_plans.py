"""Quarterly performance reviews, composite scoring, corrective plans."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    get_success_data,
    list_plans,
    make_account,
    make_review,
    make_wholesaler_headers,
    post_audit,
    setup_awarded_territory,
    setup_review_with_plan,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]


@pytest.fixture
def dual_profile_reviews(api):
    """Identical metrics 80/100.00/40 reviewed under STANDARD and SHARE_TILTED
    agreements; no audits, so freshness_index is 100.00 for both."""
    _, wa, _ = setup_awarded_territory(territory_name="Territory A")
    _, wb, _ = setup_awarded_territory(
        territory_name="Territory B",
        agreement_overrides={"weighting_profile": "SHARE_TILTED"})
    reva = make_review(wa["id"], period_year=2026, period_quarter="Q3",
                       distribution_pct=80, share_pct=40)
    revb = make_review(wb["id"], period_year=2026, period_quarter="Q3",
                       distribution_pct=80, share_pct=40)
    return {"wa": wa, "wb": wb, "reva": reva, "revb": revb}


class TestCompositeDualVariant:
    def test_standard_profile_composite_spawns_no_plan(
        self, api, dual_profile_reviews
    ):
        """PRD §3.8: "under `STANDARD`, the weights are 0.40 for distribution,
        0.30 for freshness, and 0.30 for share"
        PRD §3.8: "When the `composite_score` lands below the corrective floor
        of 70.00, the review automatically spawns a `CorrectivePlan`"

        Design: Difficulty/dual_variant_calc/composite_score_standard_vs_share_tilted
        """
        env = dual_profile_reviews
        reva = env["reva"]
        assert reva["weighting_profile_snapshot"] == "STANDARD"
        assert reva["freshness_index"] == pytest.approx(100.00, abs=1e-9)
        assert reva["composite_score"] == pytest.approx(74.00, abs=1e-9), (
            "0.4*80 + 0.3*100 + 0.3*40 = 74.00"
        )
        plans = list_plans(reva["id"])
        assert plans == [], "74.00 is not below the 70.00 floor"

    def test_share_tilted_profile_composite_spawns_plan(
        self, api, dual_profile_reviews
    ):
        """PRD §3.8: "under `SHARE_TILTED`, they are 0.25 for distribution,
        0.25 for freshness, and 0.50 for share — the same inputs yield a
        different composite under the two profiles."
        PRD §3.8: "the plan's `review_id` references the spawning review, its
        status is `PROPOSED`, its `revision_count` is zero, and its
        `target_snapshot` copies the agreement targets in force when the plan
        was created."

        Design: Difficulty/dual_variant_calc/composite_score_standard_vs_share_tilted
        """
        env = dual_profile_reviews
        revb = env["revb"]
        assert revb["weighting_profile_snapshot"] == "SHARE_TILTED"
        assert revb["composite_score"] == pytest.approx(65.00, abs=1e-9), (
            "0.25*80 + 0.25*100 + 0.5*40 = 65.00"
        )
        plans = list_plans(revb["id"])
        assert len(plans) == 1
        assert plans[0]["status"] == "PROPOSED"
        assert plans[0]["revision_count"] == 0
        assert plans[0]["review_id"] == revb["id"]


@pytest.fixture
def rounding_order_review(api):
    """STANDARD wholesaler; one audit (168.3 fresh bbl + 31.7 bbl exactly
    90 days stale) giving pooled freshness 84.15; review inputs 90.06/33.35."""
    _, wholesaler, _ = setup_awarded_territory(
        territory_name="Round Territory",
        agreement_overrides={"weighting_profile": "STANDARD",
                             "distribution_target_pct": 90,
                             "freshness_target_index": 85,
                             "share_target_pct": 35,
                             "declared_distribution_pct": 90,
                             "declared_freshness_index": 85,
                             "declared_share_pct": 35})
    account = make_account(wholesaler["id"], name="Round Bar")
    audit_resp = post_audit(
        account["id"], conducted_at="2026-09-01T00:00:00Z",
        line_cleaning_last_at="2026-08-28T00:00:00Z",
        kegs=[{"brand_code": "BUD", "filled_at": "2026-08-20T00:00:00Z",
               "volume_bbl": 168.3},
              {"brand_code": "BUD", "filled_at": "2026-06-03T00:00:00Z",
               "volume_bbl": 31.7}])
    if audit_resp.status_code != 201:
        raise AssertionError(f"Setup failed at audit: {audit_resp.text[:300]}")
    review = make_review(wholesaler["id"], period_year=2026, period_quarter="Q3",
                         distribution_pct=90.06, share_pct=33.35)
    return {"wholesaler": wholesaler, "audit": get_success_data(audit_resp),
            "review": review}


class TestPinnedRoundingOrder:
    def test_freshness_index_pooled_volume_weighted(self, api, rounding_order_review):
        """PRD §3.8: "sum the `volume_bbl` of every keg into a total volume,
        and sum the `volume_bbl` of every keg that was stale at its audit (aged
        at least 90 days, per §3.6) into a stale volume. When there are no
        audits in the window, or the pooled total volume is zero, the index is
        100.00; otherwise it is one hundred minus one hundred times the stale
        volume divided by the total volume, rounded half-up to two decimal
        places."

        Design: Difficulty/combinatorial_formula/composite_component_first_rounding_order
        """
        env = rounding_order_review
        assert env["audit"]["stale_keg_count"] == 1, (
            "the 90-day keg counts as stale; >= 90 is inclusive"
        )
        assert env["review"]["freshness_index"] == pytest.approx(84.15, abs=1e-9), (
            "100 - 100*31.7/200 = 84.15"
        )

    def test_component_first_rounding_produces_71_32(self, api, rounding_order_review):
        """PRD §3.8: "Step one: round each of the three inputs —
        `distribution_pct`, `freshness_index`, and `share_pct` — to one decimal
        place, half-up. Step two: combine the three rounded values at full
        intermediate precision using the profile weights. Step three: round the
        weighted sum half-up to two decimal places to produce the
        `composite_score`. Rounding each metric before weighting is required;
        rounding only the final sum produces different values and is
        non-conformant."

        Design: Difficulty/combinatorial_formula/composite_component_first_rounding_order
        """
        review = rounding_order_review["review"]
        assert review["composite_score"] == pytest.approx(71.32, abs=1e-9), (
            "round1: 90.1/84.2/33.4 -> 0.4*90.1 + 0.3*84.2 + 0.3*33.4 = 71.32"
        )
        assert review["composite_score"] != pytest.approx(71.27, abs=1e-9), (
            "the forbidden weight-first order would produce 71.274"
        )
        plans = list_plans(review["id"])
        assert plans == [], "71.32 >= 70.00: no corrective plan spawned"


class TestFreshnessPoolingAcrossWindows:
    def test_freshness_index_pools_volume_across_audits_and_windows(self, api):
        """PRD §3.8: "across all audits of accounts served by the wholesaler
        whose `conducted_at` falls inside the calendar quarter identified by
        `period_year` and `period_quarter` — inclusive of both window endpoints"
        PRD §3.8: "When there are no audits in the window, or the pooled total
        volume is zero, the index is 100.00"

        Design: Corner/calculations/freshness_index_pools_volume_across_audits_and_windows
        """
        _, wholesaler, _ = setup_awarded_territory(territory_name="Fresh Territory")
        af1 = make_account(wholesaler["id"], name="Fresh Bar 1")
        af2 = make_account(wholesaler["id"], name="Fresh Bar 2")
        r1 = post_audit(af1["id"], conducted_at="2026-09-01T00:00:00Z",
                        line_cleaning_last_at="2026-08-28T00:00:00Z",
                        kegs=[{"brand_code": "BUD",
                               "filled_at": "2026-08-25T00:00:00Z",
                               "volume_bbl": 50}])
        r2 = post_audit(af2["id"], conducted_at="2026-09-02T00:00:00Z",
                        line_cleaning_last_at="2026-08-30T00:00:00Z",
                        kegs=[{"brand_code": "BUD",
                               "filled_at": "2026-06-04T00:00:00Z",
                               "volume_bbl": 50}])
        for r in (r1, r2):
            if r.status_code != 201:
                raise AssertionError(f"Setup failed at audit: {r.text[:300]}")

        q3 = make_review(wholesaler["id"], period_year=2026, period_quarter="Q3",
                         distribution_pct=80, share_pct=40)
        assert q3["freshness_index"] == pytest.approx(50.00, abs=1e-9), (
            "pooled 100 bbl, 50 stale"
        )
        assert q3["composite_score"] == pytest.approx(59.00, abs=1e-9), (
            "0.4*80 + 0.3*50.0 + 0.3*40 = 59.00"
        )
        assert len(list_plans(q3["id"])) == 1, "59.00 < 70.00 spawns one plan"

        q2 = make_review(wholesaler["id"], period_year=2026, period_quarter="Q2",
                         distribution_pct=80, share_pct=40)
        assert q2["freshness_index"] == pytest.approx(100.00, abs=1e-9), (
            "no audits inside the Q2 window"
        )
        assert q2["composite_score"] == pytest.approx(74.00, abs=1e-9)
        assert list_plans(q2["id"]) == [], "74.00 >= 70.00 spawns no plan"


class TestReviewValidations:
    def test_duplicate_review_same_quarter_rejected(self, api):
        """PRD §3.8: "One review per wholesaler per period: a second review for
        the same `wholesaler_id`, `period_year`, and `period_quarter` is
        rejected with `ERR_DUPLICATE_REVIEW`."

        Design: Corner/validations/duplicate_review_same_quarter_rejected
        """
        _, wholesaler, _ = setup_awarded_territory(territory_name="Dup Territory")
        first = make_review(wholesaler["id"], period_year=2026,
                            period_quarter="Q3", distribution_pct=90,
                            share_pct=50)
        assert first["status"] == "PUBLISHED"

        resp = api.create_review(
            {"wholesaler_id": wholesaler["id"], "period_year": 2026,
             "period_quarter": "Q3", "distribution_pct": 85, "share_pct": 45},
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_REVIEW)

        q2 = api.create_review(
            {"wholesaler_id": wholesaler["id"], "period_year": 2026,
             "period_quarter": "Q2", "distribution_pct": 85, "share_pct": 45},
            ADMIN)
        validate_success(q2, 201)

    def test_review_dispute_branch_and_terminal_lockdown(self, api):
        """PRD §3.8: "responding with `action` `DISPUTE` moves it to `DISPUTED`
        and requires a `dispute_reason` to be present — a dispute without one
        is rejected with `ERR_INVALID_REQUEST`. Both outcomes are terminal for
        the review."

        Design: Corner/state_machines/review_dispute_branch_and_terminal_lockdown
        """
        _, wholesaler, _ = setup_awarded_territory(
            territory_name="Dispute Territory")
        review = make_review(wholesaler["id"], period_year=2026,
                             period_quarter="Q3", distribution_pct=90,
                             share_pct=50)
        assert review["composite_score"] == pytest.approx(81.00, abs=1e-9)
        assert list_plans(review["id"]) == [], "81.00 >= 70.00 spawns no plan"

        headers = make_wholesaler_headers(wholesaler["id"])
        disputed = validate_success(
            api.review_response(review["id"],
                                {"action": "DISPUTE",
                                 "dispute_reason": "share undercounted in chain accounts"},
                                headers)
        )
        assert disputed["status"] == "DISPUTED"
        assert disputed["dispute_reason"] == "share undercounted in chain accounts"

        second = api.review_response(review["id"], {"action": "ACKNOWLEDGE"},
                                     headers)
        validate_error(second, ApiErrorId.ERR_INVALID_STATE_TRANSITION)


@pytest.fixture
def failed_cycle(api):
    """Review at composite 59.00 with a PROPOSED plan; review ACKNOWLEDGED;
    plan activated then resolved FAILED (round one complete)."""
    wholesaler, _, review, plan = setup_review_with_plan(
        territory_name="Cycle Territory", distribution_pct=50, share_pct=30)
    headers = make_wholesaler_headers(wholesaler["id"])
    ack = api.review_response(review["id"], {"action": "ACKNOWLEDGE"}, headers)
    if ack.status_code != 200:
        raise AssertionError(f"Setup failed at ACKNOWLEDGE: {ack.text[:300]}")
    act = api.activate_plan(plan["id"], COMPLIANCE)
    if act.status_code != 200:
        raise AssertionError(f"Setup failed at activate: {act.text[:300]}")
    failed = api.resolve_plan(plan["id"],
                              {"outcome": "FAILED",
                               "resolution_notes": "first round missed freshness target"},
                              COMPLIANCE)
    if failed.status_code != 200:
        raise AssertionError(f"Setup failed at resolve FAILED: {failed.text[:300]}")
    return {"wholesaler": wholesaler, "review": review, "plan": plan,
            "headers": headers}


class TestCorrectivePlanRevisionCycle:
    def test_failed_plan_revises_to_proposed_with_count_one(
        self, api, failed_cycle
    ):
        """PRD §3.8: "The exception is revision: the reviewed wholesaler itself
        — ownership-checked against the review's wholesaler — may resubmit a
        `FAILED` plan, moving it `FAILED` → `PROPOSED` for another round while
        its `revision_count` increments by one."

        Design: Difficulty/non_linear_state_machine/corrective_plan_failed_revision_cycle
        """
        env = failed_cycle
        assert env["review"]["composite_score"] == pytest.approx(59.00, abs=1e-9), (
            "0.4*50 + 0.3*100 + 0.3*30 = 59.00"
        )

        revised = validate_success(api.revise_plan(env["plan"]["id"],
                                                   env["headers"]))
        assert revised["status"] == "PROPOSED"
        assert revised["revision_count"] == 1, "the loop ran exactly once"

        reactivated = validate_success(api.activate_plan(env["plan"]["id"],
                                                         COMPLIANCE))
        assert reactivated["status"] == "ACTIVE"
        assert reactivated["revision_count"] == 1, (
            "activate does not touch revision_count"
        )

    def test_second_round_resolves_verified_with_count_unchanged(
        self, api, failed_cycle
    ):
        """PRD §3.8: "Resolution moves an `ACTIVE` plan to its outcome,
        supplied as `outcome` with optional `resolution_notes`, which are
        recorded either way: `VERIFIED` is terminal"
        PRD §3.8: "The cycle may repeat: propose, activate, resolve, revise."

        Design: Difficulty/non_linear_state_machine/corrective_plan_failed_revision_cycle
        """
        env = failed_cycle
        validate_success(api.revise_plan(env["plan"]["id"], env["headers"]))
        validate_success(api.activate_plan(env["plan"]["id"], COMPLIANCE))
        verified = validate_success(
            api.resolve_plan(env["plan"]["id"],
                             {"outcome": "VERIFIED",
                              "resolution_notes": "second round verified"},
                             COMPLIANCE)
        )
        assert verified["status"] == "VERIFIED"
        assert verified["revision_count"] == 1, (
            "resolve does not touch revision_count"
        )


@pytest.fixture
def ack_gated_plan(api):
    """A PROPOSED plan whose parent review is still PUBLISHED."""
    wholesaler, _, review, plan = setup_review_with_plan(
        territory_name="Ack Territory", distribution_pct=50, share_pct=30)
    return {"wholesaler": wholesaler, "review": review, "plan": plan}


class TestPlanActivateGatedOnReviewAck:
    def test_activate_rejected_while_review_published(self, api, ack_gated_plan):
        """PRD §3.8: "Activation moves a `PROPOSED` plan to `ACTIVE`, but only
        once the plan's parent review — reached through its `review_id` — is
        `ACKNOWLEDGED`; while the review is still `PUBLISHED` or has been
        `DISPUTED`, activation is rejected with `ERR_REVIEW_NOT_ACKNOWLEDGED`."

        Design: Difficulty/cross_entity_state_dependency/plan_activate_gated_on_review_acknowledgement
        """
        env = ack_gated_plan
        resp = api.activate_plan(env["plan"]["id"], COMPLIANCE)
        validate_error(resp, ApiErrorId.ERR_REVIEW_NOT_ACKNOWLEDGED)

    def test_activate_succeeds_after_acknowledgement(self, api, ack_gated_plan):
        """PRD §3.8: "Responding to a `PUBLISHED` review with `action`
        `ACKNOWLEDGE` moves it to `ACKNOWLEDGED`"
        PRD §3.8: "Activation moves a `PROPOSED` plan to `ACTIVE`, but only
        once the plan's parent review — reached through its `review_id` — is
        `ACKNOWLEDGED`"

        Design: Difficulty/cross_entity_state_dependency/plan_activate_gated_on_review_acknowledgement
        """
        env = ack_gated_plan
        resp = api.activate_plan(env["plan"]["id"], COMPLIANCE)
        validate_error(resp, ApiErrorId.ERR_REVIEW_NOT_ACKNOWLEDGED)

        headers = make_wholesaler_headers(env["wholesaler"]["id"])
        acked = validate_success(
            api.review_response(env["review"]["id"], {"action": "ACKNOWLEDGE"},
                                headers)
        )
        assert acked["status"] == "ACKNOWLEDGED"

        activated = validate_success(api.activate_plan(env["plan"]["id"],
                                                       COMPLIANCE))
        assert activated["status"] == "ACTIVE"
        assert activated["revision_count"] == 0
