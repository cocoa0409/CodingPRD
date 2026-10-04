"""Spousal computation: the pinned dual-entitlement evaluation order and the
family maximum's per-line dime reconciliation."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_claim,
    create_relationship,
    create_worker,
    create_worker_with_awi_record,
    file_auxiliary_claim,
    file_claim,
    get_claim,
    post_wage_report,
    set_clock,
    validate_success,
)

CS = TEST_USERS["claims_specialist_headers"]

# Spouse S2's record: one fifth of the average wage index per year, 2019-2023;
# each year indexes to 390,000 (AWI(2024)/5), giving AIME 4,600 and PIA 4,140.
S2_WAGES = {2019: 365_000, 2020: 370_000, 2021: 375_000, 2022: 380_000, 2023: 385_000}


def _setup_dual_entitlement(api):
    """h2 (PIA 20,880, RETIREMENT ENTITLED at 2026-06) married to s2 since
    2000-01-01; s2 holds an own RETIREMENT claim (ENTITLED) and files SPOUSAL."""
    h2 = create_worker_with_awi_record(2019, 2023, full_name="Worker H2")
    h2_claim = file_claim(h2["id"], "RETIREMENT", "2026-06")
    approve_claim(h2_claim["id"])

    s2 = create_worker(full_name="Spouse S2")
    for year, amount in S2_WAGES.items():
        post_wage_report(s2["id"], year, amount)
    rel = create_relationship(h2["id"], s2["id"], "CURRENT_SPOUSE", "2000-01-01",
                              verify=True)
    own_claim = file_claim(s2["id"], "RETIREMENT", "2026-06")
    own_entitled = approve_claim(own_claim["id"])
    spousal_claim = file_auxiliary_claim(s2["id"], "SPOUSAL", "2026-06", rel["id"])
    return h2, s2, rel, own_entitled, spousal_claim


class TestDualEntitlementEvaluationOrder:
    def test_own_retirement_pia_and_reduced_benefit(self, api):
        """PRD §3.5: "The evaluation order is pinned and must be followed exactly:
        first compute the reduced spousal amount; second, apply the
        dual-entitlement offset — the claimant's own `pia_cents` from their own
        `ENTITLED` or `SUSPENDED` `RETIREMENT` claim, zero if they have none, is
        subtracted, and only the positive excess survives; third, the family
        maximum below may lower that excess; fourth, the government pension
        offset — two-thirds of the claimant's own
        `noncovered_pension_monthly_cents`, dime-floored — is subtracted, and the
        claim's `monthly_benefit_cents` is the remainder, floored at zero."

        s2's own record: AIME 4,600, PIA 4,140, own benefit at 744 months =
        dime_floor(4,140 * 0.70) = 2,890.

        Design: Difficulty/combinatorial_formula/dual_entitlement_excess_evaluation_order
        """
        _, _, _, own_entitled, _ = _setup_dual_entitlement(api)

        assert own_entitled["aime_cents"] == 4_600
        assert own_entitled["pia_cents"] == 4_140
        assert own_entitled["monthly_benefit_cents"] == 2_890

    def test_spousal_excess_nets_against_unreduced_own_pia(self, api):
        """PRD §3.5: "second, apply the dual-entitlement offset — the claimant's
        own `pia_cents` from their own `ENTITLED` or `SUSPENDED` `RETIREMENT`
        claim, zero if they have none, is subtracted, and only the positive
        excess survives".
        PRD §3.5: "The spouse's total income is the sum of their own retirement
        benefit and this claim's benefit, and the two claims remain separate
        entities throughout."

        Reduced spousal dime_floor(10,440 * 0.65) = 6,780 minus own PIA 4,140 =
        excess 2,640 (family max not binding: 14,610 + 2,640 <= 31,320; no
        pension). Netting against the reduced own benefit instead would give
        3,890 — observably different and non-conformant. Combined income 2,890 +
        2,640 = 5,530.

        Design: Difficulty/combinatorial_formula/dual_entitlement_excess_evaluation_order
        """
        _, _, _, own_entitled, spousal_claim = _setup_dual_entitlement(api)

        spousal = approve_claim(spousal_claim["id"])
        assert spousal["status"] == "ENTITLED"
        assert spousal["monthly_benefit_cents"] == 2_640
        assert spousal["monthly_benefit_cents"] != 3_890, (
            "the offset runs against the UNREDUCED own PIA, not the reduced benefit"
        )
        assert own_entitled["monthly_benefit_cents"] + spousal["monthly_benefit_cents"] == 5_530


def _setup_family_max(api):
    """Worker q (PIA 20,880); ex-spouse DIVORCED_SPOUSAL approved at 2026-06
    (reduced spousal 6,780 pre-family-max); then at 2031-06 q's own RETIREMENT
    (20,880 at FRA) and current spouse's SPOUSAL (10,440 pre-family-max)."""
    q = create_worker_with_awi_record(2019, 2023, full_name="Worker Q")

    ex = create_worker(full_name="Ex Spouse")
    rel_ex = create_relationship(q["id"], ex["id"], "DIVORCED_SPOUSE", "1990-01-01",
                                 divorce_date="2010-01-01", verify=True)
    ex_claim = file_auxiliary_claim(ex["id"], "DIVORCED_SPOUSAL", "2026-06", rel_ex["id"])
    approve_claim(ex_claim["id"])

    set_clock("2031-06-15T00:00:00Z")
    q_claim = file_claim(q["id"], "RETIREMENT", "2031-06")
    q_entitled = approve_claim(q_claim["id"])

    cur = create_worker(full_name="Current Spouse")
    rel_cur = create_relationship(q["id"], cur["id"], "CURRENT_SPOUSE", "2020-01-01",
                                  verify=True)
    cur_claim = file_auxiliary_claim(cur["id"], "SPOUSAL", "2031-06", rel_cur["id"])
    return q, ex_claim, q_entitled, cur_claim


class TestFamilyMaximumReconciliation:
    def test_worker_own_benefit_never_reduced_and_pool_exhausted(self, api):
        """PRD §3.5: "Otherwise the auxiliary pool is the maximum minus the
        worker's own benefit — the worker's own benefit is *never* reduced — and
        each auxiliary claim's share is the pool multiplied by that claim's
        pre-reduction amount and divided by the sum of all pre-reduction auxiliary
        amounts, dime-floored per claim first."

        FMAX = dime_floor(1.50 * 20,880) = 31,320; pool = 31,320 - 20,880 =
        10,440; allocated shares 4,120 + 6,320 exhaust the pool exactly.

        Design: Difficulty/combinatorial_formula/family_max_per_line_dime_reconciliation
        """
        q, ex_claim, q_entitled, cur_claim = _setup_family_max(api)
        approve_claim(cur_claim["id"])

        q_fresh = get_claim(q_entitled["id"])
        ex_fresh = get_claim(ex_claim["id"])
        cur_fresh = get_claim(cur_claim["id"])
        assert q_fresh["monthly_benefit_cents"] == 20_880, "own benefit never reduced"
        assert ex_fresh["monthly_benefit_cents"] + cur_fresh["monthly_benefit_cents"] == 10_440, (
            "auxiliary shares exhaust the pool FMAX - own = 31,320 - 20,880"
        )

    def test_per_line_dime_floor_then_residual_to_earliest(self, api):
        """PRD §3.5: "Rounding those per-claim shares first strands dimes, and the
        residual is distributed one dime (10 cents) at a time to auxiliary claims
        in `created_at` ascending order, one dime per claim per pass, until the
        pool is exhausted. Computing the shares by summing first and rounding once
        is a different, non-conformant order."

        Per-line dime floors: ex dime_floor(10,440 * 6,780/17,220) = 4,110; cur
        dime_floor(10,440 * 10,440/17,220) = 6,320; the stranded 10-cent residual
        goes to the earliest-created auxiliary (the ex-spouse) — 4,120 vs 6,320.

        Design: Difficulty/combinatorial_formula/family_max_per_line_dime_reconciliation
        """
        q, ex_claim, q_entitled, cur_claim = _setup_family_max(api)
        approve_claim(cur_claim["id"])

        ex_fresh = get_claim(ex_claim["id"])
        cur_fresh = get_claim(cur_claim["id"])
        assert ex_fresh["monthly_benefit_cents"] == 4_120, (
            "dime-floored share 4,110 plus the 10-cent residual as earliest created_at"
        )
        assert cur_fresh["monthly_benefit_cents"] == 6_320
