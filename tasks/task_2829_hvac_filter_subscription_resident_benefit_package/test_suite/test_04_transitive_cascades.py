"""
Cascade A (case confirmation reaching the property balance five links deep) and
cascade B (property suspension reaching shipments and a conditional subset of
entitlements).
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import OPERATOR


def _notice_sent_env(api):
    """Fixture A carried to a NOTICE_SENT case with the clock on 2026-09-11."""
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
    validate_success(api.send_case_notice(case["id"], OPERATOR))
    fx.set_clock(api, "2026-09-11T00:00:00Z")
    return env, case


class TestCascadeAConfirmation:
    """Confirm -> escalation -> posture -> forfeiture -> ledger -> balance."""

    def test_confirmation_escalates_the_case_and_forfeits_exactly_the_two_riders(self, api):
        """
        One confirm call lands the first three links: the case escalates, the
        posture confirms while the commercial dimension stays ACTIVE, and only the
        damage-waiver and air-quality rows forfeit — with the entitled set and the
        monthly fee re-derived from the two survivors.

        PRD §2.9: "**Cascade A — confirmed non-installation, five links deep.** Confirming an investigable case escalates the case to `ESCALATED_TO_PM`; that escalation drives the subscription's `installation_posture` from `NON_INSTALL_SUSPECTED` to `NON_INSTALL_CONFIRMED`; that confirmation forfeits the subscription's damage-waiver and air-quality-guarantee entitlements; each forfeiture posts a credit ledger row; and each ledger row re-derives the owning property's outstanding balance."

        Design: Difficulty/transitive_cascade/cascade_a_case_confirm_reaches_property_balance_five_links_deep
        """
        env, case = _notice_sent_env(api)

        confirmed_case = validate_success(api.confirm_case(case["id"], OPERATOR))
        assert confirmed_case["status"] == "ESCALATED_TO_PM"

        subscription = fx.read_subscription(api, env.subscription_id)
        assert subscription["installation_posture"] == "NON_INSTALL_CONFIRMED"
        assert subscription["status"] == "ACTIVE"
        assert subscription["entitled_benefit_codes"] == [
            "CREDIT_REPORTING",
            "RENTERS_INSURANCE",
        ]
        a.assert_cents(subscription["monthly_fee_cents"], 2546, "monthly_fee_cents")

        rows = fx.read_entitlements(api, env.subscription_id)
        waiver = a.entitlement_by_code(rows, "DAMAGE_WAIVER")
        a.assert_entitlement(waiver, "FORFEITED", forfeit_reason="NON_INSTALL_CONFIRMED")
        a.assert_instant_equals(waiver["terminated_at"], "2026-09-11T00:00:00Z")
        aqg = a.entitlement_by_code(rows, "AIR_QUALITY_GUARANTEE")
        a.assert_entitlement(aqg, "FORFEITED", forfeit_reason="NON_INSTALL_CONFIRMED")

        a.assert_entitlement(
            a.entitlement_by_code(rows, "CREDIT_REPORTING"), "ACTIVE", forfeit_reason=None
        )
        a.assert_entitlement(
            a.entitlement_by_code(rows, "RENTERS_INSURANCE"), "ACTIVE", forfeit_reason=None
        )

    def test_each_forfeiture_credits_its_own_row_and_the_balance_re_derives(self, api):
        """
        The two forfeitures post two independently rounded WAIVER_REVERSAL credits
        — air quality at -267 and damage waiver at -400 — each pointing at its own
        entitlement row, dragging the property's balance from 5588 down to 4921
        without touching the shipment.

        PRD §3.6: "The resulting figure is posted as a `WAIVER_REVERSAL` ledger row whose `amount_cents` is the **negative** of it (it is a credit), whose `billed_party` snapshots the subscription's `billing_party`, and whose `source_ref_id` names the forfeited entitlement row."

        Design: Difficulty/transitive_cascade/cascade_a_case_confirm_reaches_property_balance_five_links_deep
        """
        env, case = _notice_sent_env(api)
        assert a.property_balance(api, env.property_id, OPERATOR) == 5588
        before = fx.first_shipment(api, env.subscription_id)

        validate_success(api.confirm_case(case["id"], OPERATOR))

        entitlements = fx.read_entitlements(api, env.subscription_id)
        aqg_id = a.entitlement_by_code(entitlements, "AIR_QUALITY_GUARANTEE")["id"]
        waiver_id = a.entitlement_by_code(entitlements, "DAMAGE_WAIVER")["id"]

        rows = fx.read_ledger(api, env.subscription_id)
        a.assert_ledger_ordering(rows)
        reversals = a.find_ledger_rows(rows, "WAIVER_REVERSAL")
        assert len(reversals) == 2
        by_ref = {row["source_ref_id"]: row for row in reversals}
        a.assert_ledger_row(by_ref[aqg_id], "WAIVER_REVERSAL", -267, "PROPERTY_MANAGER", aqg_id)
        a.assert_ledger_row(
            by_ref[waiver_id], "WAIVER_REVERSAL", -400, "PROPERTY_MANAGER", waiver_id
        )

        assert a.property_balance(api, env.property_id, OPERATOR) == 4921

        after = validate_success(api.get_shipment(before["id"], OPERATOR))
        assert after["status"] == before["status"]
        assert after["version"] == before["version"]


class TestCascadeBPropertySuspension:
    """Suspend -> subscriptions -> scheduled shipments + suspendable riders."""

    def test_suspension_reaches_the_subscription_and_its_scheduled_shipment(self, api):
        """
        Suspending the property records the reason, drives the ACTIVE subscription
        to SUSPENDED without touching its compliance dimension, cancels the
        still-SCHEDULED first shipment and drops next_ship_date back to null.

        PRD §2.9: "**Cascade B — property suspension, three links deep.** Suspending a property drives every `ACTIVE` subscription at that property to `SUSPENDED`; each of those suspensions cancels that subscription's still-`SCHEDULED` shipments and suspends its renters-insurance and air-quality-guarantee entitlements."

        Design: Difficulty/transitive_cascade/cascade_b_property_suspend_reaches_shipments_and_entitlements_conditionally
        """
        env = fx.build_base_env(api)
        shipment = fx.first_shipment(api, env.subscription_id)
        assert shipment["status"] == "SCHEDULED"
        before = fx.read_subscription(api, env.subscription_id)
        assert before["next_ship_date"] == "2026-08-05"

        suspended_property = validate_success(
            api.suspend_property(
                env.property_id, f.suspend_payload(suspend_reason="PM_PAYMENT_DELINQUENT"), OPERATOR
            )
        )
        assert suspended_property["status"] == "SUSPENDED"
        assert suspended_property["suspend_reason"] == "PM_PAYMENT_DELINQUENT"

        subscription = fx.read_subscription(api, env.subscription_id)
        assert subscription["status"] == "SUSPENDED"
        assert subscription["installation_posture"] == "UNVERIFIED"
        assert subscription["next_ship_date"] is None

        assert validate_success(api.get_shipment(shipment["id"], OPERATOR))["status"] == (
            "CANCELLED"
        )

    def test_suspension_touches_only_the_two_suspendable_riders_and_no_money(self, api):
        """
        Renters insurance and the air-quality guarantee go SUSPENDED with
        suspended_by_property_event true while credit reporting and the damage
        waiver stay ACTIVE with the marker false — and because suspension is not
        forfeiture no ledger row is posted, the balance holds at 5588 and the
        monthly fee stays 3546.

        PRD §3.6: "A property suspension suspends only the two operationally-suspendable riders — a row moves `ACTIVE → SUSPENDED` with `suspended_by_property_event` set true when its `benefit_code` is `RENTERS_INSURANCE` or `AIR_QUALITY_GUARANTEE`, while `CREDIT_REPORTING` and `DAMAGE_WAIVER` rows stay `ACTIVE` — and a property reactivation moves `SUSPENDED → ACTIVE` with the marker cleared to false for exactly the rows carrying it."

        Design: Difficulty/transitive_cascade/cascade_b_property_suspend_reaches_shipments_and_entitlements_conditionally
        """
        env = fx.build_base_env(api)
        ledger_before = fx.read_ledger(api, env.subscription_id)

        validate_success(
            api.suspend_property(
                env.property_id, f.suspend_payload(suspend_reason="PM_PAYMENT_DELINQUENT"), OPERATOR
            )
        )

        rows = fx.read_entitlements(api, env.subscription_id)
        a.assert_entitlement(
            a.entitlement_by_code(rows, "RENTERS_INSURANCE"),
            "SUSPENDED",
            suspended_by_property_event=True,
            forfeit_reason=None,
        )
        a.assert_entitlement(
            a.entitlement_by_code(rows, "AIR_QUALITY_GUARANTEE"),
            "SUSPENDED",
            suspended_by_property_event=True,
            forfeit_reason=None,
        )
        a.assert_entitlement(
            a.entitlement_by_code(rows, "CREDIT_REPORTING"),
            "ACTIVE",
            suspended_by_property_event=False,
        )
        a.assert_entitlement(
            a.entitlement_by_code(rows, "DAMAGE_WAIVER"),
            "ACTIVE",
            suspended_by_property_event=False,
        )

        ledger_after = fx.read_ledger(api, env.subscription_id)
        assert len(ledger_after) == len(ledger_before)
        assert a.property_balance(api, env.property_id, OPERATOR) == 5588
        a.assert_cents(
            fx.read_subscription(api, env.subscription_id)["monthly_fee_cents"],
            3546,
            "monthly_fee_cents",
        )
        assert validate_success(api.get_unit(env.unit_id, OPERATOR))["status"] == "OCCUPIED"
        assert validate_success(api.get_resident(env.resident_id, OPERATOR))["status"] == (
            "RESIDING"
        )
