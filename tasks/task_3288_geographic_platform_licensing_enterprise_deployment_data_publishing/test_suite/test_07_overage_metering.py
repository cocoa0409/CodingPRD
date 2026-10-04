"""Concurrent-use overage metering: marginal fee at checkout vs the
average-form re-charge at each logical-clock advance."""
from test_helpers import (
    get_grant,
    get_org,
    get_success_data,
    make_named_user_headers,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.fixtures import (
    add_user_on_grant,
    invite_user,
    set_clock,
    setup_concurrent_use_org,
)


def test_overage_checkout_accrues_marginal_fee(api):
    """PRD section 2.8: "`CONCURRENT_USE` grants are metered instead: a
    checkout that pushes a grant's in-use seats beyond its allocation
    succeeds, and the platform accrues a marginal overage fee onto the
    organization's `seat_overage_fee_accrued_cents`, priced by which overage
    seat this checkout occupies".
    PRD section 2.8: "overage seats 1 through 5 cost 250 cents each".

    Design: Difficulty/combinatorial_formula/overage_marginal_at_checkout_vs_sustained_at_period
    """
    ctx = setup_concurrent_use_org(seats_allocated=1)
    grant = ctx["grant"]
    add_user_on_grant(ctx["org"]["id"], grant["id"], "u1", "u1@meridian.example")
    assert get_grant(grant["id"])["seats_in_use"] == 1
    assert get_org(ctx["org"]["id"])["seat_overage_fee_accrued_cents"] == 0

    add_user_on_grant(ctx["org"]["id"], grant["id"], "u2", "u2@meridian.example")
    # overage seat 1 -> marginal 250 cents
    assert get_grant(grant["id"])["seats_in_use"] == 2
    org = get_org(ctx["org"]["id"])
    assert org["seat_overage_fee_accrued_cents"] == 250


def test_overage_period_advance_recharges_all_sustained_seats(api):
    """PRD section 2.8: "A second, distinct accrual runs at each logical-clock
    advance while overage seats remain checked out. Rather than pricing only
    the marginal seat, the sustained-overage variant re-charges *all*
    currently sustained overage seats — the in-use count minus the allocation,
    floored at zero — using the average-rate form of the same table: the count
    of sustained seats falling in the first tier times 250 cents, plus the
    count in the second tier times 400 cents, plus the count in the third tier
    times 700 cents."

    Design: Difficulty/combinatorial_formula/overage_marginal_at_checkout_vs_sustained_at_period
    """
    ctx = setup_concurrent_use_org(seats_allocated=1)
    grant = ctx["grant"]
    add_user_on_grant(ctx["org"]["id"], grant["id"], "u1", "u1@meridian.example")
    add_user_on_grant(ctx["org"]["id"], grant["id"], "u2", "u2@meridian.example")
    assert get_org(ctx["org"]["id"])["seat_overage_fee_accrued_cents"] == 250

    set_clock("2026-09-02T00:00:00Z")
    # sustained re-charge: 1 sustained overage seat in tier 1 -> +250
    org = get_org(ctx["org"]["id"])
    assert org["seat_overage_fee_accrued_cents"] == 500
