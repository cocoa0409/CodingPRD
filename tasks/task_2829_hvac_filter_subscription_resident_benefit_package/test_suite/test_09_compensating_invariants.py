"""
The two compensating pairs: claim payment against its reversal, restoring the
property balance to the cent, and property suspension against reactivation,
restoring the ACTIVE entitlement census exactly.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import ADJUSTER_A, ADJUSTER_B, OPERATOR


def _approved_claim_env(api):
    """Fixture A with a DAMAGE_WAIVER claim APPROVED for 30000 and unpaid."""
    env = fx.build_base_env(api)
    claim = fx.file_claim(
        api,
        env.subscription_id,
        claim_type="DAMAGE_WAIVER",
        incident_date="2026-08-05",
        requested_amount_cents=40000,
        description="Return grille torn during filter change",
    )
    fx.triage_claim(api, claim["id"], ADJUSTER_A)
    approved = validate_success(
        api.decide_claim(
            claim["id"],
            f.decide_payload("APPROVE", "Waiver applies, no non-install suspicion on file"),
            ADJUSTER_B,
        )
    )
    assert approved["status"] == "APPROVED"
    a.assert_cents(approved["approved_amount_cents"], 30000, "approved_amount_cents")
    assert fx.read_subscription(api, env.subscription_id)["installation_posture"] == (
        "UNVERIFIED"
    )
    return env, claim


class TestClaimPayoutAndReversal:
    """The payout leg and the reversal leg must sum to exactly zero."""

    def test_the_payout_leg_genuinely_moves_the_balance_negative(self, api):
        """
        Disbursing the approved claim posts a CLAIM_PAYOUT of -30000 against the
        property manager and drags the balance from 5588 to -24412, so the
        intermediate state the reversal has to undo is a real change.

        PRD §3.7: "The claim moves `APPROVED → PAID`, `paid_at` is stamped from the logical clock, and a `CLAIM_PAYOUT` ledger row is posted whose `amount_cents` is the **negative** of `approved_amount_cents` — money leaving the program is a credit to the billed party — with `billed_party` snapshotting the subscription's `billing_party` and `source_ref_id` naming the claim."

        Design: Difficulty/compensating_invariant/claim_payout_and_reversal_restore_property_ledger_net_exactly
        """
        env, claim = _approved_claim_env(api)
        before = fx.read_ledger(api, env.subscription_id)
        assert len(before) == 2
        assert a.property_balance(api, env.property_id, OPERATOR) == 5588

        paid = validate_success(api.pay_claim(claim["id"], OPERATOR))
        assert paid["status"] == "PAID"
        a.assert_system_timestamp(paid["paid_at"])

        rows = fx.read_ledger(api, env.subscription_id)
        assert len(rows) == 3
        payouts = a.find_ledger_rows(rows, "CLAIM_PAYOUT")
        assert len(payouts) == 1
        a.assert_ledger_row(payouts[0], "CLAIM_PAYOUT", -30000, "PROPERTY_MANAGER", claim["id"])

        assert a.property_balance(api, env.property_id, OPERATOR) == -24412

    def test_the_reversal_leg_restores_the_balance_to_the_cent(self, api):
        """
        Reversing the payment posts a mirror-image CLAIM_PAYOUT_REVERSAL of +30000
        carrying the same billed_party and source_ref_id, leaves
        approved_amount_cents at 30000, and puts the balance back on 5588 exactly —
        four append-only rows, none of them mutated away.

        PRD §3.7: "`approved_amount_cents` is deliberately left unchanged so the two ledger legs sum to exactly zero and the property's balance returns to its exact pre-payout value with no drift."

        Design: Difficulty/compensating_invariant/claim_payout_and_reversal_restore_property_ledger_net_exactly
        """
        env, claim = _approved_claim_env(api)
        fx.pay_claim(api, claim["id"])
        payout = a.find_ledger_rows(fx.read_ledger(api, env.subscription_id), "CLAIM_PAYOUT")[0]

        reversed_claim = validate_success(
            api.reverse_claim_payment(
                claim["id"],
                f.reverse_payment_payload("Vendor invoice withdrawn by the property manager"),
                OPERATOR,
            )
        )
        assert reversed_claim["status"] == "PAYMENT_REVERSED"
        a.assert_cents(reversed_claim["approved_amount_cents"], 30000, "approved_amount_cents")

        rows = fx.read_ledger(api, env.subscription_id)
        assert len(rows) == 4
        a.assert_ledger_ordering(rows)
        assert a.find_ledger_rows(rows, "CLAIM_PAYOUT") == [payout]
        reversals = a.find_ledger_rows(rows, "CLAIM_PAYOUT_REVERSAL")
        assert len(reversals) == 1
        a.assert_ledger_row(
            reversals[0],
            "CLAIM_PAYOUT_REVERSAL",
            30000,
            payout["billed_party"],
            payout["source_ref_id"],
        )
        assert payout["amount_cents"] + reversals[0]["amount_cents"] == 0

        assert a.property_balance(api, env.property_id, OPERATOR) == 5588


def _forfeited_env(api):
    """
    Fixture A carried through cascade A, so DAMAGE_WAIVER and
    AIR_QUALITY_GUARANTEE are FORFEITED and only two rows are still ACTIVE.
    """
    env = fx.build_base_env(api)
    fx.deliver_first_shipment(api, env.subscription_id, "2026-08-06T00:00:00Z")
    fx.add_runtime_reading(
        api, env.unit_id, "2026-08-07T00:00:00Z", "2026-08-08T00:00:00Z",
        168, 100, "PRESSURE_SENSOR",
    )
    fx.add_runtime_reading(
        api, env.unit_id, "2026-08-08T00:00:00Z", "2026-08-09T00:00:00Z",
        168, 120, "PRESSURE_SENSOR",
    )
    fx.set_clock(api, "2026-08-09T00:00:00Z")
    case = fx.open_case(api, env.subscription_id, "RUNTIME_ANALYTICS", "2026-08-09")
    fx.send_notice(api, case["id"])
    fx.set_clock(api, "2026-09-11T00:00:00Z")
    fx.confirm_case(api, case["id"])

    rows = fx.read_entitlements(api, env.subscription_id)
    assert len(rows) == 4
    assert a.active_benefit_codes(rows) == ["CREDIT_REPORTING", "RENTERS_INSURANCE"]
    return env


def _census(rows: list) -> dict:
    census = {}
    for row in rows:
        census[row["state"]] = census.get(row["state"], 0) + 1
    return census


class TestSuspendReactivateEntitlementCensus:
    """The suspend leg must disturb the census, the reactivate leg restore it."""

    def test_the_suspend_leg_drops_the_active_census_to_one_survivor(self, api):
        """
        Suspension takes only the renters-insurance rider, so the ACTIVE census
        falls from two to one and the already-forfeited air-quality row is left
        alone — terminal, and never marked as suspended by the property event.

        PRD §3.6: "A property suspension suspends only the two operationally-suspendable riders — a row moves `ACTIVE → SUSPENDED` with `suspended_by_property_event` set true when its `benefit_code` is `RENTERS_INSURANCE` or `AIR_QUALITY_GUARANTEE`, while `CREDIT_REPORTING` and `DAMAGE_WAIVER` rows stay `ACTIVE` — and a property reactivation moves `SUSPENDED → ACTIVE` with the marker cleared to false for exactly the rows carrying it."

        Design: Difficulty/compensating_invariant/property_suspend_reactivate_pair_restores_active_entitlement_set
        """
        env = _forfeited_env(api)
        before = fx.read_entitlements(api, env.subscription_id)
        a.assert_entitlement(
            a.entitlement_by_code(before, "DAMAGE_WAIVER"),
            "FORFEITED",
            forfeit_reason="NON_INSTALL_CONFIRMED",
        )
        a.assert_entitlement(
            a.entitlement_by_code(before, "AIR_QUALITY_GUARANTEE"),
            "FORFEITED",
            forfeit_reason="NON_INSTALL_CONFIRMED",
        )

        validate_success(
            api.suspend_property(env.property_id, f.suspend_payload(), OPERATOR)
        )

        rows = fx.read_entitlements(api, env.subscription_id)
        assert len(rows) == 4
        assert a.active_benefit_codes(rows) == ["CREDIT_REPORTING"]
        assert _census(rows) == {"ACTIVE": 1, "SUSPENDED": 1, "FORFEITED": 2}
        a.assert_entitlement(
            a.entitlement_by_code(rows, "RENTERS_INSURANCE"),
            "SUSPENDED",
            suspended_by_property_event=True,
        )
        a.assert_entitlement(
            a.entitlement_by_code(rows, "AIR_QUALITY_GUARANTEE"),
            "FORFEITED",
            suspended_by_property_event=False,
            forfeit_reason="NON_INSTALL_CONFIRMED",
        )

    def test_the_reactivate_leg_restores_the_same_active_set_and_nothing_more(self, api):
        """
        Reactivation puts the renters-insurance row back with the marker cleared,
        so the ACTIVE set is byte-identical to the pre-suspend one, while the two
        forfeited rows stay forfeited, the row count never leaves four and the
        subscription is neither re-priced nor made compliant again.

        PRD §2.9: "Reactivating a suspended property must leave each affected subscription's count of `ACTIVE` entitlements, and the exact set of `benefit_code` values among them, identical to their pre-suspend values; this works because the suspend cascade marks exactly the rows it suspended with `suspended_by_property_event` set to true and the reactivate cascade restores exactly those rows, clearing the flag back to false."

        Design: Difficulty/compensating_invariant/property_suspend_reactivate_pair_restores_active_entitlement_set
        """
        env = _forfeited_env(api)
        before = fx.read_entitlements(api, env.subscription_id)
        active_before = a.active_benefit_codes(before)
        fee_before = fx.read_subscription(api, env.subscription_id)["monthly_fee_cents"]
        a.assert_cents(fee_before, 2546, "monthly_fee_cents")

        validate_success(
            api.suspend_property(env.property_id, f.suspend_payload(), OPERATOR)
        )
        validate_success(api.reactivate_property(env.property_id, OPERATOR))

        after = fx.read_entitlements(api, env.subscription_id)
        assert len(after) == len(before) == 4
        assert a.active_benefit_codes(after) == active_before
        assert _census(after) == {"ACTIVE": 2, "FORFEITED": 2}
        a.assert_entitlement(
            a.entitlement_by_code(after, "RENTERS_INSURANCE"),
            "ACTIVE",
            suspended_by_property_event=False,
            forfeit_reason=None,
        )
        a.assert_entitlement(
            a.entitlement_by_code(after, "DAMAGE_WAIVER"),
            "FORFEITED",
            forfeit_reason="NON_INSTALL_CONFIRMED",
        )
        a.assert_entitlement(
            a.entitlement_by_code(after, "AIR_QUALITY_GUARANTEE"),
            "FORFEITED",
            forfeit_reason="NON_INSTALL_CONFIRMED",
        )

        subscription = fx.read_subscription(api, env.subscription_id)
        assert subscription["status"] == "ACTIVE"
        assert subscription["installation_posture"] == "NON_INSTALL_CONFIRMED"
        a.assert_cents(subscription["monthly_fee_cents"], 2546, "monthly_fee_cents")
        assert fx.read_property(api, env.property_id)["suspend_reason"] is None
