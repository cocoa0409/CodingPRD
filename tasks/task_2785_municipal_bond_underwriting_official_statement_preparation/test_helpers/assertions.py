"""Domain assertions and the PRD's arithmetic, restated once.

Two kinds of helper live here. The ``assert_*`` functions check invariants that
PRD.md states as invariants (the money identity, the par identity, the common
field set, sort order). The ``expected_*`` functions restate a PRD formula so a
test can pin a derived figure for a schedule the PRD does not itself work out.

All monetary comparisons go through ``Decimal`` at the PRD's own scale, and every
timestamp comparison is canonicalised to millisecond precision first, so neither
float representation nor sub-second width can produce a spurious failure.
"""

from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    ARBITRAGE_ALLOWANCE_PCT,
    ARBITRAGE_DAY_BASIS,
    BOND_PAR_USD,
    ENTITY_TYPE_SURCHARGE,
    LATE_ANNUAL_FILING_POINTS,
    LATE_EVENT_NOTICE_POINTS,
    MATERIAL_EVENT_POINTS,
    MIN_DENOMINATION_USD,
    RISK_SCORE_MAX,
    RISK_SCORE_MIN,
    SEMIANNUAL_PERIODS_PER_YEAR,
    parse_iso,
)

MONEY = Decimal("0.01")
PRICE = Decimal("0.001")
YIELD = Decimal("0.0001")


# ---------------------------------------------------------------------------
# Numeric plumbing
# ---------------------------------------------------------------------------
def to_decimal(value):
    """Coerce an API numeric to ``Decimal`` without float drift."""
    assert value is not None, "expected a numeric value, got None"
    return Decimal(str(value))


def round_half_up(value, scale):
    """Round half up at ``scale``, which is PRD section 2.6's only rounding mode."""
    return to_decimal(value).quantize(scale, rounding=ROUND_HALF_UP)


def assert_money(actual, expected, label="amount"):
    """Compare two dollar amounts at PRD section 2.6's two decimal places."""
    got = round_half_up(actual, MONEY)
    want = round_half_up(expected, MONEY)
    assert got == want, f"{label}: expected {want}, got {got} (raw {actual!r})"


def assert_price(actual, expected, label="price"):
    """Compare two prices at PRD section 2.6's three decimal places."""
    got = round_half_up(actual, PRICE)
    want = round_half_up(expected, PRICE)
    assert got == want, f"{label}: expected {want}, got {got} (raw {actual!r})"


def assert_yield_value(actual, expected, label="yield"):
    """Compare two arbitrage yields at PRD section 2.6's four decimal places."""
    got = round_half_up(actual, YIELD)
    want = round_half_up(expected, YIELD)
    assert got == want, f"{label}: expected {want}, got {got} (raw {actual!r})"


def assert_decimal_places(value, places, label="value"):
    """Assert a numeric carries no more than ``places`` decimal places."""
    text = format(to_decimal(value).normalize(), "f")
    fraction = text.split(".")[1] if "." in text else ""
    assert len(fraction) <= places, (
        f"{label}: expected at most {places} decimal places, got {value!r}"
    )


def assert_is_number(value, label="value"):
    """Assert a monetary or price field arrived as a JSON number, not a string."""
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{label}: expected a JSON number, got {type(value).__name__} {value!r}"
    )


def assert_whole_denomination(value, label="amount"):
    """PRD section 2.6: par figures are whole multiples of the minimum denomination."""
    amount = to_decimal(value)
    assert amount % MIN_DENOMINATION_USD == 0, (
        f"{label}: expected a whole multiple of {MIN_DENOMINATION_USD}, got {value!r}"
    )


def floor_to_denomination(value):
    """Floor down to a whole multiple of five thousand dollars (PRD section 3.7)."""
    amount = to_decimal(value)
    increments = (amount / MIN_DENOMINATION_USD).to_integral_value(rounding=ROUND_DOWN)
    return increments * MIN_DENOMINATION_USD


# ---------------------------------------------------------------------------
# Timestamps
# ---------------------------------------------------------------------------
def canonical_timestamp(value):
    """Normalise an ISO 8601 UTC instant to millisecond precision.

    PRD section 2.2 renders timestamps with three fractional digits, but a
    payload echoed back with a different fractional width still denotes the same
    instant. Canonicalising both sides keeps precision out of the assertion.
    """
    if value is None:
        return None
    moment = parse_iso(value)
    return moment.replace(microsecond=(moment.microsecond // 1000) * 1000)


def assert_timestamps_equal(actual, expected, label="timestamp"):
    """Compare two ISO 8601 instants at millisecond precision."""
    got = canonical_timestamp(actual)
    want = canonical_timestamp(expected)
    assert got == want, f"{label}: expected {expected!r}, got {actual!r}"


def assert_timestamp_shape(value, label="timestamp"):
    """PRD section 2.2: ISO 8601 UTC, optionally with three fractional digits."""
    assert is_iso8601_timestamp(value), f"{label}: not an ISO 8601 UTC instant: {value!r}"


# ---------------------------------------------------------------------------
# Common field set (PRD section 2.4)
# ---------------------------------------------------------------------------
def assert_common_fields(entity, label="entity"):
    """Every row carries id, created_at, updated_at and version.

    PRD section 2.4: "No entity in this system omits ``updated_at`` or
    ``version``."
    """
    assert is_valid_uuid(entity.get("id")), (
        f"{label}: id is not a bare UUID: {entity.get('id')!r}"
    )
    assert_timestamp_shape(entity.get("created_at"), f"{label}.created_at")
    assert_timestamp_shape(entity.get("updated_at"), f"{label}.updated_at")
    version = entity.get("version")
    assert isinstance(version, int) and not isinstance(version, bool), (
        f"{label}: version is not an integer: {version!r}"
    )
    assert version >= 1, f"{label}: version must start at 1, got {version}"


def assert_version(entity, expected, label="entity"):
    """Pin an entity's ``version`` exactly."""
    assert entity.get("version") == expected, (
        f"{label}.version: expected {expected}, got {entity.get('version')!r}"
    )


def assert_version_advanced(new_entity, old_entity, by=1, label="entity"):
    """PRD section 2.4: a mutation adds exactly ``by`` to ``version``."""
    old = old_entity.get("version")
    new = new_entity.get("version")
    assert new == old + by, (
        f"{label}.version: expected {old} + {by} = {old + by}, got {new!r}"
    )


# ---------------------------------------------------------------------------
# Cross-entity identities (PRD section 2.9)
# ---------------------------------------------------------------------------
def assert_money_identity(deal, label="deal"):
    """``issue_price_total_usd == net_proceeds + gross_spread + premium``."""
    issue_price = to_decimal(deal["issue_price_total_usd"])
    net = to_decimal(deal["net_proceeds_to_issuer_usd"])
    spread = to_decimal(deal["gross_spread_total_usd"])
    premium = to_decimal(deal["credit_enhancement_premium_usd"])
    total = (net + spread + premium).quantize(MONEY, rounding=ROUND_HALF_UP)
    assert issue_price.quantize(MONEY, rounding=ROUND_HALF_UP) == total, (
        f"{label}: money identity broken -- issue_price {issue_price} != "
        f"net {net} + spread {spread} + premium {premium}"
    )


def assert_par_identity(tranche, label="tranche"):
    """``par_allotted_usd + par_unsold_usd == principal_amount_usd``."""
    allotted = to_decimal(tranche["par_allotted_usd"])
    unsold = to_decimal(tranche["par_unsold_usd"])
    principal = to_decimal(tranche["principal_amount_usd"])
    assert allotted + unsold == principal, (
        f"{label}: par identity broken -- allotted {allotted} + unsold {unsold} "
        f"!= principal {principal}"
    )


def assert_deal_par_total(deal, tranches, label="deal"):
    """``Deal.par_allotted_total_usd`` is the sum over the deal's tranches."""
    expected = sum(to_decimal(t["par_allotted_usd"]) for t in tranches)
    assert_money(deal["par_allotted_total_usd"], expected, f"{label}.par_allotted_total_usd")


# ---------------------------------------------------------------------------
# Collection order and pagination (PRD section 2.3)
# ---------------------------------------------------------------------------
def assert_sorted_by(rows, key, descending=False, label="collection"):
    """Assert a listing is ordered by ``key``."""
    values = [row[key] for row in rows]
    expected = sorted(values, reverse=descending)
    assert values == expected, (
        f"{label}: not sorted by {key} "
        f"{'descending' if descending else 'ascending'}: {values}"
    )


def assert_timestamps_sorted(rows, key, descending=False, label="collection"):
    """Assert a listing is ordered by a timestamp field, precision-insensitively."""
    values = [canonical_timestamp(row[key]) for row in rows]
    expected = sorted(values, reverse=descending)
    assert values == expected, (
        f"{label}: not sorted by {key} "
        f"{'descending' if descending else 'ascending'}: {[row[key] for row in rows]}"
    )


def assert_pagination(meta, total_count=None, has_more=None, limit=None, offset=None):
    """Pin whichever pagination fields the caller cares about."""
    if total_count is not None:
        assert meta["total_count"] == total_count, (
            f"meta.total_count: expected {total_count}, got {meta['total_count']!r}"
        )
    if has_more is not None:
        assert meta["has_more"] is has_more, (
            f"meta.has_more: expected {has_more}, got {meta['has_more']!r}"
        )
    if limit is not None:
        assert meta["limit"] == limit, (
            f"meta.limit: expected {limit}, got {meta['limit']!r}"
        )
    if offset is not None:
        assert meta["offset"] == offset, (
            f"meta.offset: expected {offset}, got {meta['offset']!r}"
        )


def ids_of(rows):
    """Extract the ``id`` of every row in a listing, in listing order."""
    return [row["id"] for row in rows]


# ---------------------------------------------------------------------------
# The PRD's arithmetic, restated (PRD sections 3.1, 3.2, 3.3, 3.8)
# ---------------------------------------------------------------------------
def expected_risk_score(
    entity_type,
    prior_late_annual_filings=0,
    prior_late_event_notices=0,
    has_prior_material_event=False,
):
    """PRD section 3.1's continuing-disclosure risk score, clamped to 0..100."""
    raw = (
        prior_late_annual_filings * LATE_ANNUAL_FILING_POINTS
        + prior_late_event_notices * LATE_EVENT_NOTICE_POINTS
        + (MATERIAL_EVENT_POINTS if has_prior_material_event else 0)
        + ENTITY_TYPE_SURCHARGE[entity_type]
    )
    return max(RISK_SCORE_MIN, min(RISK_SCORE_MAX, raw))


def expected_price_pct(coupon_rate_pct, yield_pct, periods, redemption_pct=100.000):
    """PRD section 3.2's semiannual actuarial price per one hundred of principal."""
    semiannual_yield = to_decimal(yield_pct) / Decimal(200)
    semiannual_coupon = to_decimal(coupon_rate_pct) / Decimal(2)
    discount_factor = (Decimal(1) + semiannual_yield) ** (-int(periods))
    annuity_factor = (Decimal(1) - discount_factor) / semiannual_yield
    raw = semiannual_coupon * annuity_factor + to_decimal(redemption_pct) * discount_factor
    return raw.quantize(PRICE, rounding=ROUND_HALF_UP)


def expected_tranche_proceeds(principal_amount_usd, reoffering_price_pct):
    """PRD section 3.8: principal / 100 * reoffering price, rounded to two places."""
    raw = to_decimal(principal_amount_usd) / Decimal(100) * to_decimal(
        reoffering_price_pct
    )
    return raw.quantize(MONEY, rounding=ROUND_HALF_UP)


def expected_issue_price_total(tranches):
    """PRD section 3.8: round each tranche and then sum, never sum then round."""
    return sum(
        expected_tranche_proceeds(t["principal_amount_usd"], t["reoffering_price_pct"])
        for t in tranches
    )


def expected_negotiated_gross_spread(tranches, component_total_per_bond):
    """PRD section 3.8's negotiated spread: round per tranche, then sum."""
    total = Decimal(0)
    for tranche in tranches:
        bond_count = to_decimal(tranche["principal_amount_usd"]) / Decimal(BOND_PAR_USD)
        total += (bond_count * to_decimal(component_total_per_bond)).quantize(
            MONEY, rounding=ROUND_HALF_UP
        )
    return total


def expected_competitive_gross_spread(
    par_amount_usd, winning_bid_price_pct, issue_price_total_usd
):
    """PRD section 3.8's competitive spread: reoffering scale less bid proceeds."""
    bid_proceeds = (
        to_decimal(par_amount_usd) * to_decimal(winning_bid_price_pct) / Decimal(100)
    ).quantize(MONEY, rounding=ROUND_HALF_UP)
    return (to_decimal(issue_price_total_usd) - bid_proceeds).quantize(
        MONEY, rounding=ROUND_HALF_UP
    )


def expected_gross_spread_per_bond(gross_spread_total_usd, par_amount_usd):
    """PRD section 3.8: derived from the already-rounded total, at three places."""
    bond_count = to_decimal(par_amount_usd) / Decimal(BOND_PAR_USD)
    return (to_decimal(gross_spread_total_usd) / bond_count).quantize(
        PRICE, rounding=ROUND_HALF_UP
    )


def expected_tranche_debt_service(principal_amount_usd, coupon_rate_pct, periods):
    """PRD section 3.3: principal plus semiannual interest over the whole life."""
    principal = to_decimal(principal_amount_usd)
    interest = (
        principal
        * to_decimal(coupon_rate_pct)
        / Decimal(100)
        / Decimal(SEMIANNUAL_PERIODS_PER_YEAR)
        * Decimal(int(periods))
    )
    return (principal + interest).quantize(MONEY, rounding=ROUND_HALF_UP)


def expected_insured_debt_service(insured_tranches):
    """PRD section 3.3: round each insured maturity, then sum the rounded figures."""
    return sum(
        expected_tranche_debt_service(
            t["principal_amount_usd"], t["coupon_rate_pct"], t["periods_to_maturity"]
        )
        for t in insured_tranches
    )


def expected_premium(insured_debt_service_usd, premium_bps):
    """PRD section 3.3: debt service * bps / 10,000, rounded to two places."""
    raw = to_decimal(insured_debt_service_usd) * to_decimal(premium_bps) / Decimal(10000)
    return raw.quantize(MONEY, rounding=ROUND_HALF_UP)


def expected_net_proceeds(issue_price_total_usd, gross_spread_total_usd, premium_usd):
    """PRD section 2.9's money identity, solved for net proceeds."""
    raw = (
        to_decimal(issue_price_total_usd)
        - to_decimal(gross_spread_total_usd)
        - to_decimal(premium_usd)
    )
    return raw.quantize(MONEY, rounding=ROUND_HALF_UP)


def expected_bond_years(principal_amount_usd, periods_to_maturity):
    """PRD section 3.8: principal / 1,000 * periods / 2."""
    return (
        to_decimal(principal_amount_usd)
        / Decimal(BOND_PAR_USD)
        * Decimal(int(periods_to_maturity))
        / Decimal(SEMIANNUAL_PERIODS_PER_YEAR)
    )


def expected_arbitrage_yield(tranches):
    """PRD section 3.8's bond-year-weighted average yield, at four places."""
    weighted = Decimal(0)
    total_bond_years = Decimal(0)
    for tranche in tranches:
        bond_years = expected_bond_years(
            tranche["principal_amount_usd"], tranche["periods_to_maturity"]
        )
        weighted += to_decimal(tranche["yield_pct"]) * bond_years
        total_bond_years += bond_years
    return (weighted / total_bond_years).quantize(YIELD, rounding=ROUND_HALF_UP)


def expected_permitted_investment_yield(arbitrage_yield_pct):
    """PRD section 3.8: arbitrage yield plus the one-eighth allowance."""
    raw = to_decimal(arbitrage_yield_pct) + to_decimal(ARBITRAGE_ALLOWANCE_PCT)
    return raw.quantize(YIELD, rounding=ROUND_HALF_UP)


def expected_excess_earnings(
    unspent_proceeds_usd,
    projected_investment_yield_pct,
    permitted_investment_yield_pct,
    investment_days,
):
    """PRD section 3.8's excess earnings, zero unless the restriction applies."""
    projected = to_decimal(projected_investment_yield_pct)
    permitted = to_decimal(permitted_investment_yield_pct)
    if projected <= permitted:
        return Decimal("0.00")
    raw = (
        to_decimal(unspent_proceeds_usd)
        * (projected - permitted)
        / Decimal(100)
        * Decimal(int(investment_days))
        / Decimal(ARBITRAGE_DAY_BASIS)
    )
    return raw.quantize(MONEY, rounding=ROUND_HALF_UP)


def expected_takedown_credit(par_allotted_amounts, takedown_per_bond_usd):
    """PRD section 3.8: round each order's credit, then sum the rounded credits."""
    total = Decimal(0)
    for amount in par_allotted_amounts:
        credit = (
            to_decimal(amount) / Decimal(BOND_PAR_USD) * to_decimal(takedown_per_bond_usd)
        ).quantize(MONEY, rounding=ROUND_HALF_UP)
        total += credit
    return total


def expected_liability_par(liability_pct, par_amount_usd):
    """PRD sections 3.2, 3.8: liability_pct / 100 * par, rounded to two places."""
    raw = to_decimal(liability_pct) / Decimal(100) * to_decimal(par_amount_usd)
    return raw.quantize(MONEY, rounding=ROUND_HALF_UP)


def word_count(text):
    """PRD section 3.4: whitespace-delimited token count of the section prose."""
    return len(text.split())
