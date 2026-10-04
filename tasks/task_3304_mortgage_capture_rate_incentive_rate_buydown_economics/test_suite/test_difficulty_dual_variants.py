"""Dual-variant economics: buydown recognition and lock cost.

Each rule has two readings whose numbers diverge, and the PRD pins one of them.
"""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import constants as c
from test_helpers import factories as f
from test_helpers import fixtures
from test_helpers import (
    ADMIN_HEADERS,
    BANKER_HEADERS,
    CLOSING_HEADERS,
    COMPLIANCE_HEADERS,
    SALES_HEADERS,
    make_buyer_headers,
)


def recaptured_buydown_world(api):
    """A deal whose buydown record is held 366 days before the contract closes.

    The record is created on the startup clock, the contract then survives a
    lock expiry and a relock, and the sale closes on 2027-09-02 - one day past
    the one-year recapture window.
    """
    world = fixtures.seed_reference_data(api)
    # Re-seed the community under the premium caps this instance works with.
    community = get_success_data(
        api.create_community(
            f.community_payload(
                name="C1", state_code="TX", incentive_policy_code="PREMIUM",
                **c.PREMIUM_CAPS,
            ),
            ADMIN_HEADERS,
        )
    )
    world["community"] = community
    world["cm1"] = community["id"]

    site = fixtures.create_home_site(
        api, world["cm1"], base_price_cents=50_000_000,
        construction_stage="DRYWALL",
        estimated_completion_iso="2026-12-01T00:00:00Z",
    )
    world["home_site"] = site
    world["hs1"] = site["id"]

    commitment = fixtures.create_commitment(
        api, world["cm1"], commitment_code="FC1", committed_units=10,
        commitment_start_iso="2026-09-01T00:00:00Z",
        commitment_end_iso="2030-01-01T00:00:00Z",
    )
    world["commitment"] = commitment
    world["fc1"] = commitment["id"]

    contract = fixtures.create_contract(api, world["hs1"], world["b1"], earnest_money_cents=2_000_000)
    world.update({"contract": contract, "ct1": contract["id"], "ct1_v": contract["version"]})

    application = fixtures.create_application(api, world["ct1"])
    application = get_success_data(
        api.qualify_loan_application(application["id"], BANKER_HEADERS)
    )
    world["la1"] = application["id"]
    world["la1_v"] = application["version"]

    lock = get_success_data(
        api.create_rate_lock(
            world["la1"],
            f.rate_lock_payload(world["fc1"], lock_days=360,
                                expected_application_version=application["version"]),
            BANKER_HEADERS,
        )
    )
    world["lk1"] = lock["id"]
    fixtures.drive_lock(api, world)

    disclosure = fixtures.deliver_disclosure(api, world["ct1"])
    world["d1"] = disclosure["id"]
    fixtures.acknowledge(api, world["d1"], world["b1"])

    world["allocation"] = fixtures.allocate(api, world["ct1"], "RATE_BUYDOWN", 8_000_000)
    world["al1"] = world["allocation"]["id"]

    record = fixtures.add_buydown_record(api, world["ct1"], world["al1"], 520_000)
    world["buydown_record"] = record
    world["bd1"] = record["id"]

    # The lock and the application both lapse once the clock runs past them. The
    # contract is still LOCKED at that instant - approval is taken after the revival,
    # because PRD sections 3.3 and 3.5 revert only a LOCKED contract when a lock or an
    # application expires, so an already-approved deal would keep that posture.
    fixtures.set_clock(api, "2027-09-02T00:00:00Z")
    get_success_data(api.relock_loan_application(world["la1"], BANKER_HEADERS))
    get_success_data(api.relock_rate_lock(world["lk1"], BANKER_HEADERS))
    fixtures.drive_approve(api, world)
    fixtures.drive_close(api, world)
    return world


def test_buydown_held_past_the_recapture_window_recognises_no_incentive(api):
    """A record held 366 days earns the whole recapture credit, so nothing is recognised.

    PRD §3.7: "if the contract closed at least 365 days after the record was
    created, the full gross buydown is credited back and `recapture_credit_cents`
    equals `gross_buydown_cents`".
    PRD §3.7: "The recognized incentive is `allowed_buydown_cost_cents`, which is
    the gross buydown minus the recapture credit, never permitted to fall below
    zero."
    Design: Difficulty/dual_variant_calc/buydown_incentive_spend_us_recognition_vs_full_points
    """
    world = recaptured_buydown_world(api)

    record = fixtures.read_buydown_record(api, world["bd1"])
    assert record["gross_buydown_cents"] == 520_000, record
    assert record["recapture_credit_cents"] == 520_000, (
        f"expected the whole gross buydown credited back, got {record['recapture_credit_cents']}"
    )
    assert record["allowed_buydown_cost_cents"] == 0, (
        f"net-of-recapture recognition must be zero, got {record['allowed_buydown_cost_cents']}"
    )
    assert record["record_status"] == "BOOKED", record["record_status"]


def test_community_incentive_spend_follows_the_recognition_reading_not_full_points(api):
    """The community's recognised spend is zero, not the 520000 the full-points reading reports.

    PRD §2.6: "The `incentive_spend_cents` value is the sum of
    `allowed_buydown_cost_cents` across buydown cost records that are in `BOOKED`
    status and whose owning contract's home site belongs to the community."
    PRD §3.7: "The alternative books-full-points reading, which ignores the credit
    and recognizes the entire gross buydown, is a different number and is
    expressly not the contract."
    Design: Difficulty/dual_variant_calc/buydown_incentive_spend_us_recognition_vs_full_points
    """
    world = recaptured_buydown_world(api)

    fixtures.read_buydown_record(api, world["bd1"])
    community = fixtures.read_community(api, world["cm1"])
    assert community["incentive_spend_cents"] == 0, (
        "the full-points reading would report 520000, but recognition is net of recapture"
    )
    assert community["funded_units"] == 1, community["funded_units"]


def two_lock_deal(api, *, lock_days=30):
    """One contract holding two active locks on two applications, 30 days each."""
    world = fixtures.seed_reference_data(api)
    site1 = fixtures.create_home_site(api, world["cm1"], lot_number="L1", address="1 Elm")
    site2 = fixtures.create_home_site(api, world["cm1"], lot_number="L2", address="2 Elm")
    world.update({"hs1": site1["id"], "hs2": site2["id"]})

    contract1 = fixtures.create_contract(api, world["hs1"], world["b1"])
    contract2 = fixtures.create_contract(api, world["hs2"], world["b1"])
    world.update({"ct1": contract1["id"], "ct2": contract2["id"]})

    app1 = fixtures.create_application(api, world["ct1"], application_number="APP-1")
    app2 = fixtures.create_application(api, world["ct2"], application_number="APP-2")
    app1 = get_success_data(api.qualify_loan_application(app1["id"], BANKER_HEADERS))
    app2 = get_success_data(api.qualify_loan_application(app2["id"], BANKER_HEADERS))
    world.update({"la1": app1["id"], "la2": app2["id"]})

    lock1 = get_success_data(
        api.create_rate_lock(
            world["la1"],
            f.rate_lock_payload(world["fc1"], lock_days=lock_days,
                                expected_application_version=app1["version"]),
            BANKER_HEADERS,
        )
    )
    lock2 = get_success_data(
        api.create_rate_lock(
            world["la2"],
            f.rate_lock_payload(world["fc1"], lock_days=lock_days,
                                expected_application_version=app2["version"]),
            BANKER_HEADERS,
        )
    )
    world.update({"lk1": lock1["id"], "lk2": lock2["id"]})
    return world


def test_extension_variant_prices_only_the_marginal_tier_charge(api):
    """Thirty extra lock days cost 675 cents on the extension variant, fee-free.

    PRD §3.5: "A plain extension by a `MortgageBanker`, which pushes an `ACTIVE`
    lock's expiry later by supplying a `new_lock_days`, is billed on the extension
    variant: the cost is the marginal tier charge alone, the flat relock fee is not
    applied, and `relock_count` does not move".
    Design: Difficulty/dual_variant_calc/lock_cost_extension_variant_vs_relock_variant
    """
    world = two_lock_deal(api, lock_days=30)
    extended = get_success_data(api.extend_rate_lock(world["lk1"], 60, BANKER_HEADERS))

    assert extended["lock_cost_cents"] == 675, (
        f"15 mid-tier days at 45 cents is 675, got {extended['lock_cost_cents']}"
    )
    assert extended["relock_fee_cents"] == 0, (
        "the extension variant never charges the flat relock fee"
    )
    assert extended["relock_count"] == 0, extended["relock_count"]
    assert extended["lock_days"] == 60, extended["lock_days"]


def test_relock_variant_charges_the_flat_fee_the_extension_variant_withholds(api):
    """The second lock, revived at the same term, pays the flat fee and no marginal charge.

    PRD §3.5: "Extending or voiding a lock that is no longer `ACTIVE`, or whose
    `lock_expires_iso` has already passed, is refused with `ERR_RATE_LOCK_EXPIRED`
    at HTTP 409."
    PRD §3.5: "charges the relock variant of the lock economics: the marginal tier
    charge for the new term plus the flat relock fee of 120000 cents multiplied by
    the incremented `relock_count`, so the second relock costs twice the flat fee
    of the first."
    Design: Difficulty/dual_variant_calc/lock_cost_extension_variant_vs_relock_variant
    """
    world = two_lock_deal(api, lock_days=30)
    extended = get_success_data(api.extend_rate_lock(world["lk1"], 60, BANKER_HEADERS))
    assert extended["lock_cost_cents"] == 675, extended["lock_cost_cents"]
    assert extended["relock_fee_cents"] == 0, extended["relock_fee_cents"]

    fixtures.set_clock(api, "2026-10-05T00:00:00Z")
    lock = fixtures.read_rate_lock(api, world["lk2"])
    assert lock["lock_status"] == "EXPIRED", lock["lock_status"]

    revived = get_success_data(api.relock_rate_lock(world["lk2"], BANKER_HEADERS))
    assert revived["lock_status"] == "ACTIVE", revived["lock_status"]
    assert revived["relock_count"] == 1, revived["relock_count"]
    assert revived["relock_fee_cents"] == 120_000, (
        f"the first relock is the flat fee less the (zero) marginal charge for the "
        f"unchanged term, got {revived['relock_fee_cents']}"
    )
    assert revived["lock_cost_cents"] == revived["relock_fee_cents"], (
        "the relock variant writes the same figure to relock_fee_cents and lock_cost_cents"
    )