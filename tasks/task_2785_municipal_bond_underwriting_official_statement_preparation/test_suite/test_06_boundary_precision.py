"""Boundary precision on the two gates whose comparison direction is load-bearing.

Two metrics are pinned one smallest-representable step either side of their
threshold, so an implementation that swaps an inclusive comparison for a strict
one (or the reverse) cannot pass:

* the issuer's integer `disclosure_risk_score` against the inclusive gate at
  forty, on posting the preliminary official statement;
* the four-decimal `projected_investment_yield_pct` against the strictly
  greater-than yield-restriction test.
"""

from decimal import Decimal

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_DISCLOSURE_RISK_SECTION_REQUIRED
from test_helpers.assertions import (
    assert_money,
    assert_timestamps_equal,
    assert_yield_value,
    expected_excess_earnings,
    expected_permitted_investment_yield,
    expected_risk_score,
    to_decimal,
)
from test_helpers.constants import (
    CANONICAL_ARBITRAGE_YIELD_PCT,
    CANONICAL_PERMITTED_INVESTMENT_YIELD_PCT,
    CLOCK_EPOCH,
    DISCLOSURE_RISK_GATE,
    YIELD_DECIMALS,
)
from test_helpers.test_users import make_issuer_official_headers
from test_helpers.types import (
    DisclosureClearance,
    EntityType,
    OfficialStatementStatus,
    ReviewStatus,
    SectionType,
)

# One unit in the last place of a yield, which PRD section 2.6 carries to four
# decimal places: the smallest move that can straddle the permitted yield.
YIELD_ULP = Decimal(1).scaleb(-YIELD_DECIMALS)
PERMITTED_YIELD = to_decimal(CANONICAL_PERMITTED_INVESTMENT_YIELD_PCT)
PROJECTED_ONE_STEP_BELOW_PERMITTED = float(PERMITTED_YIELD - YIELD_ULP)
PROJECTED_EQUAL_TO_PERMITTED = float(PERMITTED_YIELD)
PROJECTED_ONE_STEP_ABOVE_PERMITTED = float(PERMITTED_YIELD + YIELD_ULP)


def _competitive_deal_for(client, issuer):
    """A PRICING_COMPETITIVE deal opened against ``issuer``.

    ``fx.participants`` registers its own issuer, so the namespace is repointed
    at the issuer whose risk score is under test before the deal is opened; the
    ``IssuerOfficial`` headers must follow it, because PRD section 2.1 resolves
    that role against the deal's ``issuer_id``.
    """
    ctx = fx.participants(client)
    ctx.issuer = issuer
    ctx.issuer_id = issuer["id"]
    ctx.issuer_headers = make_issuer_official_headers(issuer["id"])
    return fx.competitive_pricing_deal(client, ctx)


def _approve_sections_without_material_continuing_disclosure(ctx):
    """Approve all four mandatory categories, the CONTINUING_DISCLOSURE one immaterial.

    ``fx.approve_mandatory_sections`` flags its CONTINUING_DISCLOSURE section as
    a material risk, which would satisfy the high-risk gate outright; this
    variant clears `mandatory_sections_approved` while leaving the gate unmet.
    """
    sections = {
        SectionType.RISK_FACTOR: fx.add_section(
            ctx.client, ctx.statement_id, f.material_risk_section_payload()
        ),
        SectionType.TAX_MATTERS: fx.add_section(
            ctx.client, ctx.statement_id, f.section_payload(SectionType.TAX_MATTERS)
        ),
        SectionType.CONTINUING_DISCLOSURE: fx.add_section(
            ctx.client,
            ctx.statement_id,
            f.continuing_disclosure_risk_section_payload(is_material_risk=False),
        ),
        SectionType.UNDERWRITING: fx.add_section(
            ctx.client, ctx.statement_id, f.section_payload(SectionType.UNDERWRITING)
        ),
    }
    for section in sections.values():
        fx.approve_section(ctx.client, section["id"])
    ctx.sections = sections
    ctx.section_ids = {key: row["id"] for key, row in sections.items()}
    return ctx


def _statement_in_review_missing_the_risk_section(client, issuer):
    """A statement in IN_REVIEW that meets every posting gate except the high-risk one."""
    ctx = _competitive_deal_for(client, issuer)
    fx.with_active_undertaking(ctx)
    fx.with_drafting_statement(ctx)
    _approve_sections_without_material_continuing_disclosure(ctx)
    ctx.statement = fx.submit_for_review(client, ctx.statement_id)
    return ctx


def _read_risk_score(client, issuer_id, headers):
    """The `disclosure_risk_score` frozen on the issuer row at registration."""
    issuer = validate_success(client.get_issuer(issuer_id, headers))
    return issuer["disclosure_risk_score"]


def _assert_gate_unmet(ctx, compliance):
    """No approved CONTINUING_DISCLOSURE section on the statement is material."""
    sections, _meta = validate_paginated(
        ctx.client.list_statement_sections(
            ctx.statement_id, compliance, section_type=SectionType.CONTINUING_DISCLOSURE
        )
    )
    assert sections != []
    assert all(
        section["is_material_risk"] is False
        and section["review_status"] == ReviewStatus.APPROVED
        for section in sections
    )


def _analyse(ctx, projected_investment_yield_pct):
    """Run the read-only yield-restriction projection and return payload and result."""
    payload = f.yield_restriction_payload(projected_investment_yield_pct)
    result = validate_success(
        ctx.client.yield_restriction_analysis(ctx.deal_id, payload, ctx.compliance_headers)
    )
    assert_yield_value(
        result["arbitrage_yield_pct"],
        CANONICAL_ARBITRAGE_YIELD_PCT,
        "arbitrage_yield_pct",
    )
    assert_yield_value(
        result["permitted_investment_yield_pct"],
        expected_permitted_investment_yield(CANONICAL_ARBITRAGE_YIELD_PCT),
        "permitted_investment_yield_pct",
    )
    assert_yield_value(
        result["permitted_investment_yield_pct"],
        CANONICAL_PERMITTED_INVESTMENT_YIELD_PCT,
        "permitted_investment_yield_pct",
    )
    assert_yield_value(
        result["projected_investment_yield_pct"],
        projected_investment_yield_pct,
        "projected_investment_yield_pct",
    )
    return payload, result


def test_risk_score_exactly_at_the_gate_blocks_preliminary_posting(client, compliance):
    """PRD section 3.4: "Third, the high-risk-issuer gate applies: when the deal's issuer has a `disclosure_risk_score` at or above forty, the statement must carry at least one section whose `section_type` is `CONTINUING_DISCLOSURE`, whose `is_material_risk` is true, and whose `review_status` is `APPROVED`; a statement without such a section is refused with `ERR_DISCLOSURE_RISK_SECTION_REQUIRED`."

    Design: Difficulty/boundary_precision_check/disclosure_risk_gate_inclusive_at_forty
    """
    issuer = fx.register_high_risk_issuer(client)
    score = _read_risk_score(client, issuer["id"], compliance)
    assert score == DISCLOSURE_RISK_GATE
    assert score == expected_risk_score(
        EntityType.AUTHORITY, has_prior_material_event=True
    )

    ctx = _statement_in_review_missing_the_risk_section(client, issuer)
    assert ctx.statement["status"] == OfficialStatementStatus.IN_REVIEW
    assert ctx.statement["mandatory_sections_approved"] is True
    _assert_gate_unmet(ctx, compliance)

    response = client.post_preliminary(ctx.statement_id, None, ctx.advisor_headers)
    validate_error(response, ERR_DISCLOSURE_RISK_SECTION_REQUIRED)

    after = validate_success(
        client.get_official_statement(ctx.statement_id, ctx.advisor_headers)
    )
    assert after["status"] == OfficialStatementStatus.IN_REVIEW
    assert after["posted_preliminary_at"] is None


def test_risk_score_one_point_below_the_gate_posts_preliminary(client, compliance):
    """PRD section 3.1: "A score **at or above forty** puts the issuer inside the high-risk gate, and a deal for that issuer cannot post a preliminary official statement until an approved material continuing-disclosure risk factor is in the document; a score of thirty-nine does not."

    Design: Difficulty/boundary_precision_check/disclosure_risk_gate_inclusive_at_forty
    """
    issuer = fx.register_below_gate_issuer(client)
    score = _read_risk_score(client, issuer["id"], compliance)
    assert score == DISCLOSURE_RISK_GATE - 1
    assert score == expected_risk_score(
        EntityType.AUTHORITY, prior_late_event_notices=3
    )

    # The same AUTHORITY surcharge and the same immaterial continuing-disclosure
    # package as the blocked case: only the one-point score difference remains.
    ctx = _statement_in_review_missing_the_risk_section(client, issuer)
    assert ctx.statement["mandatory_sections_approved"] is True
    _assert_gate_unmet(ctx, compliance)

    statement = fx.post_preliminary(client, ctx.statement_id, ctx.advisor_headers)
    assert statement["status"] == OfficialStatementStatus.PRELIMINARY_POSTED
    assert_timestamps_equal(
        statement["posted_preliminary_at"], CLOCK_EPOCH, "posted_preliminary_at"
    )

    deal = fx.read_deal(client, ctx.deal_id, ctx.advisor_headers)
    assert deal["disclosure_clearance"] == DisclosureClearance.CLEARED


def test_projected_yield_one_step_below_permitted_does_not_restrict(client, draft_deal):
    """PRD section 3.8: "The permitted yield is `arbitrage_yield_pct` plus the one-eighth of one percent allowance — that is, plus 0.125 — rounded to four decimal places."

    Design: Difficulty/boundary_precision_check/arbitrage_allowance_strictly_above_permitted_yield
    """
    ctx = draft_deal
    before = fx.read_deal(client, ctx.deal_id, ctx.advisor_headers)
    assert before["arbitrage_yield_pct"] is None

    payload, result = _analyse(ctx, PROJECTED_ONE_STEP_BELOW_PERMITTED)
    assert to_decimal(result["projected_investment_yield_pct"]) < PERMITTED_YIELD
    assert result["yield_restriction_applies"] is False
    assert_money(
        result["excess_earnings_usd"],
        expected_excess_earnings(
            payload["unspent_proceeds_usd"],
            payload["projected_investment_yield_pct"],
            CANONICAL_PERMITTED_INVESTMENT_YIELD_PCT,
            payload["investment_days"],
        ),
        "excess_earnings_usd",
    )

    # PRD section 3.8: the projection "stores nothing whatsoever".
    after = fx.read_deal(client, ctx.deal_id, ctx.advisor_headers)
    assert after["arbitrage_yield_pct"] is None
    assert after["version"] == before["version"]


def test_projected_yield_equal_to_permitted_does_not_restrict(client, draft_deal):
    """PRD section 3.8: "The restriction test is **strict**: `yield_restriction_applies` is true only when `projected_investment_yield_pct` is strictly greater than `permitted_investment_yield_pct`, so a projected yield exactly equal to the permitted yield does not trigger restriction."

    Design: Difficulty/boundary_precision_check/arbitrage_allowance_strictly_above_permitted_yield
    """
    ctx = draft_deal
    before = fx.read_deal(client, ctx.deal_id, ctx.advisor_headers)
    assert before["arbitrage_yield_pct"] is None

    payload, result = _analyse(ctx, PROJECTED_EQUAL_TO_PERMITTED)
    assert to_decimal(result["projected_investment_yield_pct"]) == to_decimal(
        result["permitted_investment_yield_pct"]
    )
    assert result["yield_restriction_applies"] is False
    assert_money(result["excess_earnings_usd"], Decimal("0.00"), "excess_earnings_usd")
    assert_money(
        result["excess_earnings_usd"],
        expected_excess_earnings(
            payload["unspent_proceeds_usd"],
            payload["projected_investment_yield_pct"],
            CANONICAL_PERMITTED_INVESTMENT_YIELD_PCT,
            payload["investment_days"],
        ),
        "excess_earnings_usd",
    )

    after = fx.read_deal(client, ctx.deal_id, ctx.advisor_headers)
    assert after["arbitrage_yield_pct"] is None
    assert after["version"] == before["version"]


def test_projected_yield_one_step_above_permitted_restricts(client, draft_deal):
    """PRD section 3.8: "When the restriction applies, `excess_earnings_usd` is `unspent_proceeds_usd` multiplied by the difference between the projected and permitted yields, divided by one hundred, multiplied by `investment_days`, divided by three hundred sixty, rounded to two decimal places; when it does not apply, `excess_earnings_usd` is 0.00."

    Design: Difficulty/boundary_precision_check/arbitrage_allowance_strictly_above_permitted_yield
    """
    ctx = draft_deal
    before = fx.read_deal(client, ctx.deal_id, ctx.advisor_headers)
    assert before["arbitrage_yield_pct"] is None

    payload, result = _analyse(ctx, PROJECTED_ONE_STEP_ABOVE_PERMITTED)
    assert to_decimal(result["projected_investment_yield_pct"]) == PERMITTED_YIELD + YIELD_ULP
    assert result["yield_restriction_applies"] is True
    assert_money(
        result["excess_earnings_usd"],
        expected_excess_earnings(
            payload["unspent_proceeds_usd"],
            payload["projected_investment_yield_pct"],
            CANONICAL_PERMITTED_INVESTMENT_YIELD_PCT,
            payload["investment_days"],
        ),
        "excess_earnings_usd",
    )

    after = fx.read_deal(client, ctx.deal_id, ctx.advisor_headers)
    assert after["arbitrage_yield_pct"] is None
    assert after["version"] == before["version"]
