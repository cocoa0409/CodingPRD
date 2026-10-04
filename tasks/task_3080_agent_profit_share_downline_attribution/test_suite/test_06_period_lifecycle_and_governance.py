"""Profit-share period lifecycle: preliminary close, the final-close cascade,
the distribution waterfall, clawback/regeneration, and mark-paid."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_pool_conservation,
    create_center,
    enroll_agent,
    file_dispute,
    find_distribution,
    get_agent,
    get_success_data,
    open_period,
    add_ledger_entry,
    post_commission,
    prelim_close,
    draft_resolution,
    propose_resolution,
    ratify_resolution,
    setup_center_with_mca,
    setup_final_closed_single_sponsor_period,
    setup_prelim_closed_divergence_period,
    validate_error,
    validate_success,
)
from test_helpers import (
    TEST_USERS,
    make_alc_chair_headers,
    make_market_center_admin_headers,
)

PA = TEST_USERS["platform_admin_headers"]
RD = TEST_USERS["regional_director_headers"]


def _list_period_distributions(api, period_id, **params):
    params.setdefault("period_id", period_id)
    return api.list_distributions(PA, params=params).json()["data"]


class TestRatifyCascade:
    def test_ratify_closes_period_and_flips_distributions(self, api):
        """PRD §3.9: "The cascade then fans out. Every PROJECTION distribution of
        the period moves to PAYABLE, its amount recomputed under the FINAL basis
        against the profit_share_pool and its level_breakdown rewritten; each
        recipient agent's pending_payable_profit_share — the sum of that agent's
        PAYABLE distribution amounts — is recomputed and each touched agent's
        version incremented; and the vesting schedules of DEPARTED recipients are
        re-evaluated for continuation eligibility."
        PRD §3.9: "The period lands in FINAL_CLOSED, terminal."

        Design: Difficulty/transitive_cascade/ratify_final_close_cascade_depth4
        """
        ctx = setup_prelim_closed_divergence_period()
        ratify_resolution(ctx["resolution"]["id"], ctx["alc"]["id"])
        period = get_success_data(api.get_period(ctx["period"]["id"], PA))
        assert period["status"] == "FINAL_CLOSED"
        mca_dist = find_distribution(period["id"], ctx["mca"]["id"])
        s1_dist = find_distribution(period["id"], ctx["s1"]["id"])
        assert mca_dist["status"] == "PAYABLE" and s1_dist["status"] == "PAYABLE"
        assert mca_dist["basis"] == "FINAL" and s1_dist["basis"] == "FINAL"

    def test_ratify_recomputes_amounts_and_pending_payable(self, api):
        """PRD §3.9: "The cascade then fans out. Every PROJECTION distribution of
        the period moves to PAYABLE, its amount recomputed under the FINAL basis
        against the profit_share_pool and its level_breakdown rewritten; each
        recipient agent's pending_payable_profit_share — the sum of that agent's
        PAYABLE distribution amounts — is recomputed and each touched agent's
        version incremented; and the vesting schedules of DEPARTED recipients are
        re-evaluated for continuation eligibility."

        Design: Difficulty/transitive_cascade/ratify_final_close_cascade_depth4
        """
        ctx = setup_prelim_closed_divergence_period()
        ratify_resolution(ctx["resolution"]["id"], ctx["alc"]["id"])
        period = get_success_data(api.get_period(ctx["period"]["id"], PA))
        mca_dist = find_distribution(period["id"], ctx["mca"]["id"])
        s1_dist = find_distribution(period["id"], ctx["s1"]["id"])
        assert mca_dist["amount"] == pytest.approx(476.67, abs=0.01), (
            f"mca FINAL amount: round2(0.10 * 6000.00) scaled 2860/3600, got {mca_dist['amount']}"
        )
        assert s1_dist["amount"] == pytest.approx(2383.33, abs=0.01), (
            f"s1 FINAL amount: round2(0.50 * 6000.00) scaled 2860/3600, got {s1_dist['amount']}"
        )
        mca = get_agent(ctx["mca"]["id"])
        s1 = get_agent(ctx["s1"]["id"])
        assert mca["pending_payable_profit_share"] == pytest.approx(476.67, abs=0.01)
        assert s1["pending_payable_profit_share"] == pytest.approx(2383.33, abs=0.01)
        # Hop 4: linked vesting schedules re-evaluated without error.
        schedules = get_success_data(api.get_vesting_schedule(ctx["mca"]["id"], PA))
        assert len(schedules) == 1
        assert schedules[0]["status"] == "ACCRUING"


class TestWaterfallUnderSubscription:
    def test_under_subscribed_pool_leaves_remainder_with_center(self, api):
        """PRD §3.8: "If the gross total fits within the pool, no scaling occurs
        and the unallocated remainder stays with the center."
        PRD §3.8: "Conservation holds at all times: the sum of distribution
        amounts plus center_retained_amount equals the current pool, where
        distributed_total sums the period's distributions in status PROJECTION or
        PAYABLE and is recomputed on every distribution creation or transition."

        Design: Corner/calculations/pool_covers_entitlements_center_retains_difference
        """
        center = create_center()
        mca = enroll_agent(center["id"], full_name="MCA One", email="mca1@x.com")
        d1 = enroll_agent(center["id"], sponsor_id=mca["id"], full_name="D One",
                          email="d1@x.com")
        post_commission(d1["id"], 5000.00, "2026-09-10T00:00:00Z", mca["id"],
                        settle=True, external_ref="ref-d1")
        period = open_period(center["id"], "2026-09", mca["id"])
        period = prelim_close(period["id"], mca["id"])
        assert period["provisional_profit"] == pytest.approx(1500.00, abs=0.01)
        assert period["provisional_pool"] == pytest.approx(780.00, abs=0.01)
        dist = find_distribution(period["id"], mca["id"])
        assert dist["status"] == "PROJECTION"
        assert dist["amount"] == pytest.approx(750.00, abs=0.01), (
            f"0.50 * 1500.00 unscaled, got {dist['amount']}"
        )
        assert period["distributed_total"] == pytest.approx(750.00, abs=0.01)
        assert period["center_retained_amount"] == pytest.approx(30.00, abs=0.01)
        assert_pool_conservation(period)


class TestOverturnClawbackCascade:
    def _setup_under_review_overturn(self, api):
        center = create_center()
        mca = enroll_agent(center["id"], full_name="MCA One", email="mca1@x.com")
        s1 = enroll_agent(center["id"], sponsor_id=mca["id"], full_name="S One",
                          email="s1@x.com")
        # d1's recorded sponsor is s1 but the paperwork names r1.
        d1 = enroll_agent(center["id"], sponsor_id=s1["id"], full_name="D One",
                          email="d1@x.com", docs=False)
        r1 = enroll_agent(center["id"], sponsor_id=mca["id"], full_name="R One",
                          email="r1@x.com")
        att = get_success_data(api.create_onboarding_document(
            d1["id"],
            {"document_type": "SPONSOR_ATTESTATION", "document_ref": "doc-d1-att",
             "attested_sponsor_agent_id": r1["id"]},
            PA,
        ))
        get_success_data(api.create_onboarding_document(
            d1["id"], {"document_type": "ICA_SIGNED", "document_ref": "doc-d1-ica"}, PA))
        get_success_data(api.create_onboarding_document(
            d1["id"], {"document_type": "W9", "document_ref": "doc-d1-w9"}, PA))
        post_commission(d1["id"], 5000.00, "2026-09-10T00:00:00Z", mca["id"],
                        settle=True, external_ref="ref-d1-1")
        period = open_period(center["id"], "2026-09", mca["id"])
        period = prelim_close(period["id"], mca["id"])
        dsp = file_dispute(r1["id"], d1["id"], att["id"], reason="Attestation names me")
        validate_success(api.open_dispute_review(dsp["id"], RD), 200)
        return {"center": center, "mca": mca, "s1": s1, "d1": d1, "r1": r1,
                "period": period, "dispute": dsp}

    def test_overturn_supersedes_old_edges_and_rebuilds(self, api):
        """PRD §3.4: "RESOLVED_OVERTURNED is not terminal — see the appeal path
        below — but it fires a large cascade immediately: the sponsored agent's
        sponsor_agent_id is re-pointed to the filer and that agent's version
        incremented; every ACTIVE edge whose child is the sponsored agent or any
        descendant of it via active edges becomes SUPERSEDED; and a fresh closure
        (depths one through seven) is rebuilt along the new sponsor chain, with
        descendants' edges whose paths crossed the re-pointed root re-derived."

        Design: Difficulty/transitive_cascade/dispute_overturn_sponsor_repoint_cascade
        """
        ctx = self._setup_under_review_overturn(api)
        validate_success(api.resolve_dispute(ctx["dispute"]["id"], {"outcome": "OVERTURNED"}, RD), 200)
        d1 = get_agent(ctx["d1"]["id"])
        assert d1["sponsor_agent_id"] == ctx["r1"]["id"], (
            f"re-pointed to the filer, got {d1['sponsor_agent_id']}"
        )
        superseded = api.list_sponsorship_edges(
            PA, params={"child_agent_id": ctx["d1"]["id"], "status": "SUPERSEDED"}).json()["data"]
        active = api.list_sponsorship_edges(
            PA, params={"child_agent_id": ctx["d1"]["id"], "status": "ACTIVE"}).json()["data"]
        assert len(superseded) == 2, (
            f"old edges (s1->d1 L1, mca->d1 L2) superseded, got {len(superseded)}"
        )
        assert {(e["parent_agent_id"], e["depth_level"]) for e in active} == {
            (ctx["r1"]["id"], 1), (ctx["mca"]["id"], 2)
        }, f"new closure along the new sponsor chain, got {active}"

    def test_overturn_clawback_regenerates_projections(self, api):
        """PRD §3.4: "Any ProfitShareDistribution with basis PROVISIONAL still in
        status PROJECTION whose level_breakdown references a superseded edge moves
        to CLAWED_BACK, a replacement PROJECTION distribution is regenerated from
        the new closure, and the owning period's distributed_total and
        center_retained_amount are recomputed."

        Design: Difficulty/transitive_cascade/dispute_overturn_sponsor_repoint_cascade
        """
        ctx = self._setup_under_review_overturn(api)
        validate_success(api.resolve_dispute(ctx["dispute"]["id"], {"outcome": "OVERTURNED"}, RD), 200)
        clawed = _list_period_distributions(api, ctx["period"]["id"], status="CLAWED_BACK")
        assert len(clawed) == 2, (
            f"the s1 and mca projections are clawed back, got {len(clawed)}"
        )
        assert {d["agent_id"] for d in clawed} == {ctx["s1"]["id"], ctx["mca"]["id"]}
        r1_dist = find_distribution(ctx["period"]["id"], ctx["r1"]["id"],
                                    status="PROJECTION")
        mca_dist = find_distribution(ctx["period"]["id"], ctx["mca"]["id"],
                                     status="PROJECTION")
        # Entitlements 750.00 (r1 L1) + 150.00 (mca L2) scaled by 780/900.
        assert r1_dist["amount"] == pytest.approx(650.00, abs=0.01)
        assert mca_dist["amount"] == pytest.approx(130.00, abs=0.01)
        s1_rows = _list_period_distributions(api, ctx["period"]["id"],
                                             agent_id=ctx["s1"]["id"], status="PROJECTION")
        assert len(s1_rows) == 0, "s1 has no PROJECTION distribution under the new closure"


class TestClawbackConservation:
    def _setup_under_review_overturn(self, api):
        helper = TestOverturnClawbackCascade()
        return helper._setup_under_review_overturn(api)

    def test_pool_totals_before_overturn(self, api):
        """PRD §3.8: "If the gross total of all lines across all recipients
        exceeds the pool, every line is scaled by the ratio of pool to gross total
        (the factor carried at full precision), each scaled line is rounded two
        decimals half-up, and the residual delta — pool minus the sum of scaled
        lines, rounded — is applied to the single line with the largest
        pre-rounding fractional part; ties break to the lower depth_level first,
        then the recipient agent's earlier created_at, then the source child
        agent's earlier created_at."
        PRD §3.8: "Conservation holds at all times: the sum of distribution
        amounts plus center_retained_amount equals the current pool, where
        distributed_total sums the period's distributions in status PROJECTION or
        PAYABLE and is recomputed on every distribution creation or transition."

        Design: Difficulty/compensating_invariant/pool_distributed_plus_retained_conserved_through_clawback
        """
        ctx = self._setup_under_review_overturn(api)
        period = get_success_data(api.get_period(ctx["period"]["id"], PA))
        assert period["provisional_pool"] == pytest.approx(780.00, abs=0.01)
        assert period["distributed_total"] == pytest.approx(780.00, abs=0.01)
        assert period["center_retained_amount"] == pytest.approx(0.00, abs=0.01)
        s1_dist = find_distribution(period["id"], ctx["s1"]["id"])
        mca_dist = find_distribution(period["id"], ctx["mca"]["id"])
        # Entitlements 750.00 (s1 L1) + 150.00 (mca L2) scaled by 780/900.
        assert s1_dist["amount"] == pytest.approx(650.00, abs=0.01)
        assert mca_dist["amount"] == pytest.approx(130.00, abs=0.01), (
            f"scaled lines land exactly on the pool, got {mca_dist['amount']}"
        )
        assert_pool_conservation(period)

    def test_pool_conserved_through_clawback_regeneration(self, api):
        """PRD §3.4: "Any ProfitShareDistribution with basis PROVISIONAL still in
        status PROJECTION whose level_breakdown references a superseded edge moves
        to CLAWED_BACK, a replacement PROJECTION distribution is regenerated from
        the new closure, and the owning period's distributed_total and
        center_retained_amount are recomputed."
        PRD §3.8: "Conservation holds at all times: the sum of distribution
        amounts plus center_retained_amount equals the current pool, where
        distributed_total sums the period's distributions in status PROJECTION or
        PAYABLE and is recomputed on every distribution creation or transition."

        Design: Difficulty/compensating_invariant/pool_distributed_plus_retained_conserved_through_clawback
        """
        ctx = self._setup_under_review_overturn(api)
        validate_success(api.resolve_dispute(ctx["dispute"]["id"], {"outcome": "OVERTURNED"}, RD), 200)
        period = get_success_data(api.get_period(ctx["period"]["id"], PA))
        assert period["provisional_pool"] == pytest.approx(780.00, abs=0.01), (
            "the pool is unchanged by the clawback/regeneration pair"
        )
        r1_dist = find_distribution(period["id"], ctx["r1"]["id"], status="PROJECTION")
        mca_dist = find_distribution(period["id"], ctx["mca"]["id"], status="PROJECTION")
        assert round(r1_dist["amount"] + mca_dist["amount"], 2) == pytest.approx(780.00, abs=0.01)
        assert period["distributed_total"] == pytest.approx(780.00, abs=0.01)
        assert period["center_retained_amount"] == pytest.approx(0.00, abs=0.01)
        assert_pool_conservation(period)


class TestPreliminaryCloseValidations:
    def test_preliminary_close_requires_positive_profit(self, api):
        """PRD §3.6: "Two further guards apply: the period must be OPEN, and the
        computed provisional_profit must be greater than zero, else
        ERR_PROFIT_NOT_POSITIVE (HTTP 422)."

        Design: Corner/validations/preliminary_close_requires_positive_profit
        """
        ctx = setup_center_with_mca()
        mca = ctx["mca"]
        post_commission(mca["id"], 1000.00, "2026-09-10T00:00:00Z", mca["id"],
                        settle=True, external_ref="ref-1")
        period = open_period(ctx["center"]["id"], "2026-09", mca["id"])
        add_ledger_entry(period["id"], "EXPENSE", 500.00, mca["id"])
        resp = api.preliminary_close_period(
            period["id"], make_market_center_admin_headers(mca["id"]))
        validate_error(resp, ApiErrorId.ERR_PROFIT_NOT_POSITIVE)
        after = get_success_data(api.get_period(period["id"], PA))
        assert after["status"] == "OPEN", "the failed close leaves the period OPEN"

    def test_preliminary_close_by_non_center_agent_rejected(self, api):
        """PRD §3.6: "Preliminary close is the first of two closing stages and
        belongs to the MarketCenterAdmin — with a twist: the acting X-User-ID must
        be an Agent with membership_status ACTIVE enrolled in this period's
        market center, else the close is rejected with ERR_MCA_NOT_CENTER_AGENT
        (HTTP 422)."

        Design: Corner/validations/preliminary_close_by_non_center_agent_rejected
        """
        mc1 = create_center(name="MC One")
        mc2 = create_center(name="MC Two")
        mca = enroll_agent(mc1["id"], full_name="MCA One", email="mca1@x.com")
        out = enroll_agent(mc2["id"], full_name="Out Sider", email="out@x.com")
        post_commission(mca["id"], 10000.00, "2026-09-10T00:00:00Z", mca["id"],
                        settle=True, external_ref="ref-1")
        period = open_period(mc1["id"], "2026-09", mca["id"])
        resp = api.preliminary_close_period(
            period["id"], make_market_center_admin_headers(out["id"]))
        validate_error(resp, ApiErrorId.ERR_MCA_NOT_CENTER_AGENT)
        after = get_success_data(api.get_period(period["id"], PA))
        assert after["status"] == "OPEN"


class TestSegregationOfDuties:
    def _setup_proposed_period(self, api):
        ctx = setup_center_with_mca()
        mca = ctx["mca"]
        alc = enroll_agent(ctx["center"]["id"], full_name="ALC Chair", email="alc@x.com")
        post_commission(mca["id"], 20000.00, "2026-09-10T00:00:00Z", mca["id"],
                        settle=True, external_ref="ref-1")
        period = open_period(ctx["center"]["id"], "2026-09", mca["id"])
        prelim_close(period["id"], mca["id"])
        res = draft_resolution(period["id"], mca["id"])
        propose_resolution(res["id"], mca["id"])
        return {"center": ctx["center"], "mca": mca, "alc": alc,
                "period": period, "res": res}

    def test_preliminary_closer_cannot_ratify(self, api):
        """PRD §3.7: "Ratification requires the resolution to be PROPOSED and
        enforces segregation of duties: the ratifying X-User-ID — the chair's own
        agent id — must differ from the period's preliminary_closed_by, else
        ERR_SEGREGATION_OF_DUTIES (HTTP 403)."

        Design: Corner/validations/segregation_of_duties_on_ratify
        """
        ctx = self._setup_proposed_period(api)
        resp = api.ratify_resolution(
            ctx["res"]["id"], make_alc_chair_headers(ctx["mca"]["id"]))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        resolution = get_success_data(api.get_resolution(ctx["res"]["id"], PA))
        assert resolution["status"] == "PROPOSED"

    def test_different_chair_ratifies(self, api):
        """PRD §3.7: "Ratification requires the resolution to be PROPOSED and
        enforces segregation of duties: the ratifying X-User-ID — the chair's own
        agent id — must differ from the period's preliminary_closed_by, else
        ERR_SEGREGATION_OF_DUTIES (HTTP 403)."
        PRD §3.9: "The period lands in FINAL_CLOSED, terminal."

        Design: Corner/validations/segregation_of_duties_on_ratify
        """
        ctx = self._setup_proposed_period(api)
        validate_error(
            api.ratify_resolution(ctx["res"]["id"], make_alc_chair_headers(ctx["mca"]["id"])),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
        )
        ratified = validate_success(api.ratify_resolution(
            ctx["res"]["id"], make_alc_chair_headers(ctx["alc"]["id"])), 200)
        assert ratified["status"] == "RATIFIED"
        period = get_success_data(api.get_period(ctx["period"]["id"], PA))
        assert period["status"] == "FINAL_CLOSED"


class TestMarkPaidReconciliation:
    def test_payable_before_markpaid(self, api):
        """PRD §3.9: "The cascade then fans out. Every PROJECTION distribution of
        the period moves to PAYABLE, its amount recomputed under the FINAL basis
        against the profit_share_pool and its level_breakdown rewritten; each
        recipient agent's pending_payable_profit_share — the sum of that agent's
        PAYABLE distribution amounts — is recomputed and each touched agent's
        version incremented; and the vesting schedules of DEPARTED recipients are
        re-evaluated for continuation eligibility."

        Design: Corner/cross_cutting_layers/mark_paid_reconciles_derived_agent_totals
        """
        ctx = setup_final_closed_single_sponsor_period()
        dist = find_distribution(ctx["period"]["id"], ctx["mca"]["id"])
        assert dist["status"] == "PAYABLE"
        assert dist["amount"] == pytest.approx(750.00, abs=0.01)
        mca = get_agent(ctx["mca"]["id"])
        assert mca["pending_payable_profit_share"] == pytest.approx(750.00, abs=0.01)
        assert mca["lifetime_profit_share"] == pytest.approx(0.00, abs=0.01)

    def test_markpaid_moves_amount_between_buckets(self, api):
        """PRD §3.9: "Payment is a separate, deliberate act: a MarketCenterAdmin
        marks a PAYABLE distribution paid, moving it to PAID, adding the amount
        to the recipient's lifetime_profit_share (the sum of that agent's PAID
        distributions), subtracting it from pending_payable_profit_share, and
        incrementing the agent's version."

        Design: Corner/cross_cutting_layers/mark_paid_reconciles_derived_agent_totals
        """
        ctx = setup_final_closed_single_sponsor_period()
        dist = find_distribution(ctx["period"]["id"], ctx["mca"]["id"])
        paid = validate_success(api.mark_distribution_paid(
            dist["id"], make_market_center_admin_headers(ctx["mca"]["id"])), 200)
        assert paid["status"] == "PAID"
        mca = get_agent(ctx["mca"]["id"])
        assert mca["pending_payable_profit_share"] == pytest.approx(0.00, abs=0.01)
        assert mca["lifetime_profit_share"] == pytest.approx(750.00, abs=0.01)
