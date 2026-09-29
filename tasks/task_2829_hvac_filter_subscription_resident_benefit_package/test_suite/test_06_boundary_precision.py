"""
Two boundaries probed on both sides: the inclusive confirm threshold at exactly
60 against 59, and a settlement whose exposed-shipment set is empty.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_EVIDENCE_BELOW_CONFIRM_THRESHOLD
from test_helpers.test_users import OPERATOR


def _threshold_pair_env(api):
    """
    Two identical subscriptions at one property whose telemetry differs only in
    runtime minutes: 144 per window scores exactly 60, 132 scores 59.
    """
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    fx.create_sku(api)
    prop = fx.create_property(api)
    unit_a = fx.create_unit(api, prop["id"])
    fx.activate_property(api, prop["id"])
    unit_b = fx.create_unit(api, prop["id"], unit_label="A-102")
    resident_a = fx.create_resident(api)
    resident_b = fx.create_resident(
        api, full_name="Ben Ortiz", email="ben.ortiz@example.com"
    )
    fx.set_clock(api, "2026-08-05T00:00:00Z")

    cases = {}
    for label, unit, resident, minutes, tracking in (
        ("a", unit_a, resident_a, 144, "TRK-A-0001"),
        ("b", unit_b, resident_b, 132, "TRK-B-0001"),
    ):
        subscription = fx.create_subscription(api, resident["id"], unit["id"])
        fx.activate_subscription(api, subscription["id"])
        fx.deliver_first_shipment(
            api, subscription["id"], "2026-08-06T00:00:00Z", tracking
        )
        fx.add_runtime_reading(
            api, unit["id"], "2026-08-07T00:00:00Z", "2026-08-08T00:00:00Z",
            minutes, 100, "PRESSURE_SENSOR",
        )
        fx.add_runtime_reading(
            api, unit["id"], "2026-08-08T00:00:00Z", "2026-08-09T00:00:00Z",
            minutes, 120, "PRESSURE_SENSOR",
        )
        cases[label] = {"subscription_id": subscription["id"], "unit_id": unit["id"]}

    fx.set_clock(api, "2026-08-09T00:00:00Z")
    for label in ("a", "b"):
        case = fx.open_case(
            api, cases[label]["subscription_id"], "RUNTIME_ANALYTICS", "2026-08-09"
        )
        validate_success(api.send_case_notice(case["id"], OPERATOR))
        cases[label]["case"] = case
    return cases


class TestConfirmThresholdBoundary:
    """60 is inside the confirmable range; 59 is outside it."""

    def test_a_score_exactly_at_the_frozen_threshold_confirms(self, api):
        """
        The case scoring exactly 60 against a frozen confirm_threshold of 60 is
        confirmable, because the comparison is greater-than-or-equal: it escalates,
        the posture confirms and the monthly fee falls to 2546.

        PRD §3.6: "Confirmation runs only from `NOTICE_SENT` and only when the case's stored `evidence_score` is greater than or equal to its own frozen `confirm_threshold`; a score below the frozen threshold is rejected with `ERR_EVIDENCE_BELOW_CONFIRM_THRESHOLD`."

        Design: Difficulty/boundary_precision_check/evidence_score_exactly_at_confirm_threshold_passes_one_below_rejects
        """
        cases = _threshold_pair_env(api)
        assert cases["a"]["case"]["evidence_score"] == 60
        assert cases["b"]["case"]["evidence_score"] == 59
        for label in ("a", "b"):
            assert cases[label]["case"]["suspect_threshold"] == 40
            assert cases[label]["case"]["confirm_threshold"] == 60

        confirmed = validate_success(api.confirm_case(cases["a"]["case"]["id"], OPERATOR))
        assert confirmed["status"] == "ESCALATED_TO_PM"

        subscription = fx.read_subscription(api, cases["a"]["subscription_id"])
        assert subscription["installation_posture"] == "NON_INSTALL_CONFIRMED"
        a.assert_cents(subscription["monthly_fee_cents"], 2546, "monthly_fee_cents")

    def test_a_score_one_point_below_the_threshold_is_refused_intact(self, api):
        """
        The case scoring 59 against the same threshold of 60 is refused with
        ERR_EVIDENCE_BELOW_CONFIRM_THRESHOLD and the refusal leaves everything
        alone: the case stays NOTICE_SENT at its original version, the posture stays
        merely suspected, all four entitlements stay ACTIVE and the fee stays 3546.

        PRD §2.10: "The case's stored `evidence_score` is greater than or equal to the case's stored `confirm_threshold` — otherwise `ERR_EVIDENCE_BELOW_CONFIRM_THRESHOLD` (422)."

        Design: Difficulty/boundary_precision_check/evidence_score_exactly_at_confirm_threshold_passes_one_below_rejects
        """
        cases = _threshold_pair_env(api)
        before = validate_success(
            api.get_non_install_case(cases["b"]["case"]["id"], OPERATOR)
        )
        assert before["status"] == "NOTICE_SENT"
        assert before["evidence_score"] == 59

        validate_error(
            api.confirm_case(cases["b"]["case"]["id"], OPERATOR),
            ERR_EVIDENCE_BELOW_CONFIRM_THRESHOLD,
            422,
        )

        after = validate_success(
            api.get_non_install_case(cases["b"]["case"]["id"], OPERATOR)
        )
        assert after["status"] == "NOTICE_SENT"
        assert after["version"] == before["version"]

        subscription = fx.read_subscription(api, cases["b"]["subscription_id"])
        assert subscription["installation_posture"] == "NON_INSTALL_SUSPECTED"
        a.assert_cents(subscription["monthly_fee_cents"], 3546, "monthly_fee_cents")
        rows = fx.read_entitlements(api, cases["b"]["subscription_id"])
        assert a.active_benefit_codes(rows) == [
            "AIR_QUALITY_GUARANTEE",
            "CREDIT_REPORTING",
            "DAMAGE_WAIVER",
            "RENTERS_INSURANCE",
        ]


def _unexposed_env(api):
    """Fixture A whose only shipment is still SCHEDULED, clock on 2026-09-01."""
    env = fx.build_base_env(api)
    fx.set_clock(api, "2026-09-01T00:00:00Z")
    return env


class TestSettlementWithEmptyExposedSet:
    """An empty exposed set zeroes the fee but never skips the tier lookup."""

    def test_the_tier_is_still_selected_when_no_shipment_is_exposed(self, api):
        """
        With the only shipment still SCHEDULED the exposed count is 0 and the gross
        fee is 0, yet the tier lookup still runs on the 2364 gross credit and
        reports 0.25; the relieved fee is 0 and the net equals the credit exactly.

        PRD §3.9: "When `gross_prorated_credit_cents` is below one thousand cents the relief `waiver_credit_pct` is zero; from one thousand cents up to but not including five thousand it is twenty-five percent; from five thousand up to but not including ten thousand it is fifty percent; at ten thousand cents or above it is seventy-five percent."

        Design: Difficulty/boundary_precision_check/settlement_with_empty_exposed_shipment_set_still_applies_the_waiver_tier
        """
        env = _unexposed_env(api)
        assert fx.first_shipment(api, env.subscription_id)["status"] == "SCHEDULED"

        preview = validate_success(
            api.get_settlement(
                env.subscription_id, OPERATOR, {"effective_date": "2026-09-11"}
            )
        )
        assert preview["used_days"] == 10
        assert preview["unused_days"] == 20
        a.assert_cents(preview["gross_prorated_credit_cents"], 2364, "gross credit")
        assert preview["exposed_shipment_count"] == 0
        a.assert_cents(preview["unreturned_fee_gross_cents"], 0, "gross fee")
        a.assert_decimal_string(preview["waiver_credit_pct"], "0.25", "waiver_credit_pct")
        a.assert_cents(preview["unreturned_fee_net_cents"], 0, "net fee")
        a.assert_cents(preview["net_settlement_cents"], 2364, "net settlement")

    def test_the_zero_fee_row_is_not_posted_and_the_scheduled_shipment_cancels(self, api):
        """
        Cancelling posts the PRORATION_CREDIT of -2364 and nothing else: the
        conditional UNRETURNED_SHIPMENT_FEE row is skipped because the net fee is
        not greater than zero, the SCHEDULED shipment is cancelled rather than
        recalled, the balance settles at 3224 and every entitlement expires.

        PRD §3.9: "Two ledger rows may be posted, both with `source_ref_id` naming the subscription: a `PRORATION_CREDIT` row whose `amount_cents` is the **negative** of `gross_prorated_credit_cents`, always; and an `UNRETURNED_SHIPMENT_FEE` row of **positive** `unreturned_fee_net_cents` carrying a `memo` reading `cancellation unreturned reconciliation`, posted only when that net figure is greater than zero."

        Design: Difficulty/boundary_precision_check/settlement_with_empty_exposed_shipment_set_still_applies_the_waiver_tier
        """
        env = _unexposed_env(api)
        shipment = fx.first_shipment(api, env.subscription_id)
        before = len(fx.read_ledger(api, env.subscription_id))

        cancelled = validate_success(
            api.cancel_subscription(
                env.subscription_id,
                f.cancel_payload("2026-09-11", "RESIDENT_MOVE_OUT"),
                OPERATOR,
            )
        )
        assert cancelled["status"] == "CANCELLED"
        a.assert_cents(cancelled["net_settlement_cents"], 2364, "net settlement")

        rows = fx.read_ledger(api, env.subscription_id)
        assert len(rows) == before + 1
        credits = a.find_ledger_rows(rows, "PRORATION_CREDIT")
        assert len(credits) == 1
        a.assert_ledger_row(
            credits[0], "PRORATION_CREDIT", -2364, "PROPERTY_MANAGER", env.subscription_id
        )
        assert a.find_ledger_rows(rows, "UNRETURNED_SHIPMENT_FEE") == []

        assert validate_success(api.get_shipment(shipment["id"], OPERATOR))["status"] == (
            "CANCELLED"
        )
        assert a.property_balance(api, env.property_id, OPERATOR) == 3224

        for row in fx.read_entitlements(api, env.subscription_id):
            a.assert_entitlement(row, "EXPIRED", forfeit_reason="SUBSCRIPTION_CANCELLED")
