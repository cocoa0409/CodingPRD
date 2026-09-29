"""The good-cause weighting and the hearing cost assessment."""
import pytest

from prd_bench_local_runner.testing import get_success_data
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.test_users import make_manufacturer_headers

PROTESTANT_STUDY = dict(
    total_market_registrations=40000,
    line_make_registrations=3200,
    statewide_line_make_share_pct=12.50,
    permanency_investment_cents=250000000,
    consumer_access_drive_minutes=22,
    market_growth_pct=8.00,
)
MANUFACTURER_STUDY = dict(
    total_market_registrations=40000,
    line_make_registrations=3200,
    comparable_market_shares_pct=[9.00, 10.00, 11.00],
    permanency_investment_cents=0,
    consumer_access_drive_minutes=12,
    market_growth_pct=8.00,
)


def _tender_comparable_manufacturer_study(protest_id, manufacturer_id, **overrides):
    """Tender the franchisor's study on the COMPARABLE_MARKET basis."""
    return get_success_data(api_client.create_market_study(
        protest_id, f.comparable_study_payload("MANUFACTURER", **overrides),
        make_manufacturer_headers(manufacturer_id),
    ))


def _additional_point_protest():
    """A protest against an ADDITIONAL_POINT filing 15.00 km from the incumbent."""
    ctx = fx.setup_licensed_dealer()
    filing = fx.open_additional_point_filing(
        ctx["manufacturer"]["id"], proposed_effective_on="2026-11-15",
        site_x_km=9, site_y_km=12)
    ctx["filing"] = fx.serve_notice(filing["id"], ctx["manufacturer"]["id"])
    fx.set_clock("2026-09-15T00:00:00Z")
    ctx["protest"] = fx.file_protest(
        ctx["filing"]["id"], ctx["dealer"]["id"], ctx["filing"]["version"],
        grounds_code="MARKET_ENCROACHMENT")
    return ctx


class TestExpectedPenetrationBasis:
    def test_statewide_basis_is_verbatim_while_comparable_basis_is_averaged(self, api):
        """PRD 3.7: "expected penetration is that figure verbatim; any
        `comparable_market_shares_pct` supplied alongside it is ignored." PRD
        3.7: "expected penetration is the unweighted mean of those shares —
        their sum divided by how many there are — rounded half up to two
        decimals". On identical registration counts (3200 of 40000, an actual
        8.00) the two bases give 12.50 against 10.00, so the shortfalls diverge.

        Design: Difficulty/dual_variant_calc/good_cause_expected_penetration_statewide_vs_comparable
        """
        ctx = _additional_point_protest()

        protestant_study = fx.tender_protestant_study(
            ctx["protest"]["id"], ctx["dealer"]["id"], **PROTESTANT_STUDY)
        manufacturer_study = _tender_comparable_manufacturer_study(
            ctx["protest"]["id"], ctx["manufacturer"]["id"], **MANUFACTURER_STUDY)

        assert protestant_study["actual_penetration_pct"] == pytest.approx(8.00, abs=0.01)
        assert protestant_study["expected_penetration_pct"] == pytest.approx(12.50, abs=0.01)
        assert protestant_study["shortfall_pts"] == pytest.approx(4.50, abs=0.01)
        assert protestant_study["is_probative"] is True

        assert manufacturer_study["actual_penetration_pct"] == pytest.approx(8.00, abs=0.01)
        assert manufacturer_study["expected_penetration_pct"] == pytest.approx(10.00, abs=0.01)
        assert manufacturer_study["shortfall_pts"] == pytest.approx(2.00, abs=0.01)
        assert manufacturer_study["is_probative"] is True

    def test_net_shortfall_and_weighted_score_follow_the_two_bases(self, api):
        """PRD 3.7: "The net shortfall is the protestant's controlling
        `shortfall_pts` less the franchisor's controlling `shortfall_pts`,
        rounded half up to two decimals and never allowed below 0.00". PRD 3.7:
        "The `good_cause_score` is then four tenths of the inadequacy component,
        plus one quarter of the investment component, plus one fifth of the
        access component, plus fifteen hundredths of the growth component". The
        comparable-market study leaves a net 2.50 points, so the score is
        0.40x20.00 + 0.25x100.00 + 0.20x10.00 + 0.15x40.00 = 41.00, short of the
        60.00 threshold that PRD 3.5 fixes for a filing other than a termination.

        Design: Difficulty/dual_variant_calc/good_cause_expected_penetration_statewide_vs_comparable
        """
        ctx = _additional_point_protest()
        protestant_study = fx.tender_protestant_study(
            ctx["protest"]["id"], ctx["dealer"]["id"], **PROTESTANT_STUDY)
        manufacturer_study = _tender_comparable_manufacturer_study(
            ctx["protest"]["id"], ctx["manufacturer"]["id"], **MANUFACTURER_STUDY)

        analysis = fx.read_good_cause_analysis(ctx["protest"]["id"])

        assert analysis["controlling_protestant_study_id"] == protestant_study["id"]
        assert analysis["controlling_manufacturer_study_id"] == manufacturer_study["id"]
        assert analysis["net_shortfall_pts"] == pytest.approx(2.50, abs=0.01)
        assert analysis["inadequacy_component"] == pytest.approx(20.00, abs=0.01)
        assert analysis["investment_component"] == pytest.approx(100.00, abs=0.01)
        assert analysis["access_component"] == pytest.approx(10.00, abs=0.01)
        assert analysis["growth_component"] == pytest.approx(40.00, abs=0.01)
        assert analysis["good_cause_score"] == pytest.approx(41.00, abs=0.01)
        assert analysis["good_cause_threshold"] == pytest.approx(60.00, abs=0.01)
        assert analysis["good_cause_established"] is False


def _heard_termination_protest_with_late_exhibit():
    """A termination protest heard on 152 accepted pages, one of them late.

    The hearing runs 2026-11-02T10:00:00Z to 13:00:00Z as a single session, so
    the evidence cut-off is 2026-10-26T10:00:00Z: the 2026-10-20 tenders are
    timely and the 2026-10-30 tender needs the presiding officer's leave.
    """
    ctx = fx.setup_scheduled_protest()
    protest_id = ctx["protest"]["id"]
    fx.tender_protestant_study(protest_id, ctx["dealer"]["id"], **PROTESTANT_STUDY)
    _tender_comparable_manufacturer_study(
        protest_id, ctx["manufacturer"]["id"], **MANUFACTURER_STUDY)

    fx.set_clock("2026-10-20T00:00:00Z")
    fx.tender_protestant_exhibit(
        protest_id, ctx["dealer"]["id"], exhibit_label="P-1", page_count=100)
    fx.tender_manufacturer_exhibit(
        protest_id, ctx["manufacturer"]["id"], exhibit_label="M-1", page_count=40)

    fx.set_clock("2026-10-30T00:00:00Z")
    fx.tender_protestant_exhibit(
        protest_id, ctx["dealer"]["id"], exhibit_label="P-2", page_count=12,
        leave_granted=True)

    fx.set_clock("2026-11-02T10:00:00Z")
    ctx["protest"] = fx.convene_hearing(protest_id)
    return ctx


class TestHearingCostAssessment:
    def test_surcharge_rate_is_banded_on_the_subtotal(self, api):
        """PRD 3.7: "its rate is chosen from the **subtotal** — never from the
        post-surcharge total — by taking the first matching band in ascending
        order: a subtotal of 100,000 cents or less attracts five percent, a
        subtotal above that but no more than 250,000 cents attracts eight
        percent". One session at 45,000 plus 152 pages at 350 makes a subtotal of
        98,200, which sits in the five percent band: 4,910 of surcharge and a
        total of 103,110, not the 106,056 that banding on the total would give.

        Design: Difficulty/combinatorial_formula/hearing_assessment_surcharge_tier_keyed_on_subtotal
        """
        ctx = _heard_termination_protest_with_late_exhibit()
        heard = ctx["protest"]

        assert heard["status"] == "HEARD"
        assert heard["accepted_evidence_pages"] == 152
        assert heard["late_evidence_count"] == 1
        assert heard["good_cause_score"] == pytest.approx(41.00, abs=0.01)
        assert heard["good_cause_threshold"] == pytest.approx(40.00, abs=0.01)

        decided = fx.decide_protest(
            heard["id"], "SUSTAINED",
            findings_note="Franchisor failed to establish good cause.")

        assert decided["assessment_total_cents"] == 103110
        assert decided["assessment_total_cents"] != 106056

    def test_prevailing_share_is_thirty_percent_and_the_loser_absorbs_the_rest(self, api):
        """PRD 3.7: "The **prevailing** party's share is 30 percent of
        `assessment_total_cents`, rounded half up to a whole cent; the losing
        party absorbs the remainder, computed as `assessment_total_cents` less
        the prevailing share, so that `protestant_share_cents` and
        `manufacturer_share_cents` always re-sum to `assessment_total_cents`
        exactly with no rounding drift." PRD 3.7: "Where the barred filing was a
        `TERMINATION`, the affected dealership's franchise dimension is restored
        `TERMINATION_PENDING → FRANCHISED`".

        Design: Difficulty/combinatorial_formula/hearing_assessment_surcharge_tier_keyed_on_subtotal
        """
        ctx = _heard_termination_protest_with_late_exhibit()

        decided = fx.decide_protest(ctx["protest"]["id"], "SUSTAINED")

        assert decided["status"] == "SUSTAINED"
        assert decided["decided_on"] == "2026-11-02"
        assert decided["protestant_share_cents"] == 30933
        assert decided["manufacturer_share_cents"] == 72177
        assert (decided["protestant_share_cents"] + decided["manufacturer_share_cents"]
                == decided["assessment_total_cents"])

        assert fx.read_filing(ctx["filing"]["id"])["status"] == "BARRED"
        assert fx.read_dealer(ctx["dealer"]["id"])["franchise_status"] == "FRANCHISED"
