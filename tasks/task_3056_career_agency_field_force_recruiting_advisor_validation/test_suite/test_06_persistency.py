"""Persistency measurement: the tier chain, the renewal base it multiplies and
the demotion an INELIGIBLE tier triggers."""
import pytest

from test_helpers import (
    api_client,
    fetch_advisor,
    new_office,
    md_headers,
    set_clock,
    setup_persistency_book,
    validate_success,
)


def test_an_ineligible_measurement_pays_nothing_and_accrues_nothing():
    """PRD §3.7: "otherwise the tier is `INELIGIBLE`" ... "`INELIGIBLE` selects
    0.000".
    PRD §3.7: "Provisional and disputed records accrue nothing — only
    finalization pays."

    Design: Difficulty/combinatorial_formula/persistency_tier_selection_chain_with_renewal_base
    """
    set_clock()
    office = new_office()
    ctx = setup_persistency_book(office["id"], premium=1200000,
                                 required_production_cents=480000,
                                 policies_issued=25, policies_persisted=20)

    finalized = validate_success(api_client.finalize_persistency_record(ctx["record"]["id"], md_headers))
    assert finalized["persistency_pct"] == pytest.approx(80.00, abs=0.005)
    assert finalized["persistency_tier"] == "INELIGIBLE"
    assert finalized["renewal_rate_pct"] == pytest.approx(0.000, abs=0.0005)
    assert finalized["renewal_commission_cents"] == 0
    assert finalized["renewal_commission_cents"] != 42000


def test_an_ineligible_tier_demotes_the_validated_advisor():
    """PRD §3.7: "When the finalized record's `persistency_tier` is
    `INELIGIBLE`, the advisor's contract is demoted: an advisor whose contract is
    `VALIDATED` moves to `AT_RISK`, its `validation_posture` moves to `AT_RISK`,
    and `orphan_pool_access` returns to false."

    Design: Difficulty/combinatorial_formula/persistency_tier_selection_chain_with_renewal_base
    """
    set_clock()
    office = new_office()
    ctx = setup_persistency_book(office["id"], premium=1200000,
                                 required_production_cents=480000,
                                 policies_issued=25, policies_persisted=20)

    assert fetch_advisor(ctx["advisor"]["id"])["contract_status"] == "VALIDATED"
    validate_success(api_client.finalize_persistency_record(ctx["record"]["id"], md_headers))

    advisor = fetch_advisor(ctx["advisor"]["id"])
    assert advisor["contract_status"] == "AT_RISK"
    assert advisor["validation_posture"] == "AT_RISK"
    assert advisor["orphan_pool_access"] is False
    assert advisor["renewal_commission_cents"] == 0


def test_a_95_percent_reading_selects_tier_1_at_the_inclusive_boundary():
    """PRD §3.7: "the tier is selected against inclusive lower bounds, evaluated
    top down: a `persistency_pct` of at least 95.00 selects `TIER_1`."

    Design: Corner/calculations/persistency_tier_boundaries_at_95_and_90
    """
    set_clock()
    office = new_office()
    ctx = setup_persistency_book(office["id"], premium=1200000,
                                 required_production_cents=480000,
                                 policies_issued=20, policies_persisted=19)
    # A single 1200000-cent book stands; the boundary is on the counters only.

    finalized = validate_success(api_client.finalize_persistency_record(ctx["record"]["id"], md_headers))
    assert finalized["persistency_pct"] == pytest.approx(95.00, abs=0.005)
    assert finalized["persistency_tier"] == "TIER_1"
    assert finalized["renewal_rate_pct"] == pytest.approx(0.050, abs=0.0005)
    assert finalized["renewal_commission_cents"] == 60000


def test_the_renewal_base_is_summed_over_active_policies_and_multiplied_by_the_rate():
    """PRD §3.7: "the renewal base is the sum of `annual_premium_cents` over the
    advisor's policies whose status is `ACTIVE` at the instant of the window's
    `measurement_end` within the closed window, and `renewal_commission_cents`
    is that base multiplied by the selected `renewal_rate_pct`, rounded half up
    to the nearest cent."

    Design: Corner/calculations/persistency_tier_boundaries_at_95_and_90
    """
    set_clock()
    office = new_office()
    ctx = setup_persistency_book(office["id"], premium=1200000,
                                 required_production_cents=480000,
                                 policies_issued=20, policies_persisted=19)

    finalized = validate_success(api_client.finalize_persistency_record(ctx["record"]["id"], md_headers))

    # 95.00 -> TIER_1 -> 0.050; the book is one ACTIVE policy of 1200000 cents.
    assert finalized["renewal_commission_cents"] == 60000
    assert finalized["renewal_commission_cents"] != 42000, "42000 is the TIER_2 figure"

    advisor = fetch_advisor(ctx["advisor"]["id"])
    assert advisor["renewal_commission_cents"] == 60000
    assert advisor["contract_status"] == "VALIDATED"