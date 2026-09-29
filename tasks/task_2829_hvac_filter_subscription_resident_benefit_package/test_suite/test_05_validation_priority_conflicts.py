"""
Two deliberately doubly-invalid requests, each proving which rung of the §2.10
ladder answers when two rungs are violated at once.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_BENEFIT_NOT_ENTITLED,
    ERR_OUTSIDE_COVERAGE_WINDOW,
    ERR_PROPERTY_CREDIT_LIMIT_EXCEEDED,
    ERR_PROPERTY_NOT_ACTIVE,
)
from test_helpers.test_users import OPERATOR


def _thin_margin_env(api):
    """A PENDING_SETUP subscription at a SUSPENDED property with a 100-cent limit."""
    env = fx.build_base_env(
        api,
        activate=False,
        property_overrides={"name": "Thin Margin", "credit_limit_cents": 100},
    )
    validate_success(
        api.suspend_property(
            env.property_id,
            f.suspend_payload(suspend_reason="PM_PAYMENT_DELINQUENT"),
            OPERATOR,
        )
    )
    return env


class TestPropertyStateBeatsCreditLimit:
    """Rule 8 answers before rule 30 on subscription activation."""

    def test_suspended_property_answers_before_the_credit_ceiling(self, api):
        """
        Activation would breach both the property-active guard and a 100-cent credit
        ceiling; the response is ERR_PROPERTY_NOT_ACTIVE at 409 rather than the
        402 the fiscal rule would give, and nothing at all is written.

        PRD §2.10: "Rules are evaluated in the order below, and **the first rule that fails determines the response**; no rule below it is evaluated."

        Design: Difficulty/priority_pair_validation_conflict/property_state_priority_8_beats_credit_limit_priority_30_on_activate
        """
        env = _thin_margin_env(api)

        response = api.activate_subscription(env.subscription_id, OPERATOR)
        validate_error(response, ERR_PROPERTY_NOT_ACTIVE, 409)
        assert response.status_code != 402
        assert response.json()["data"]["error_id"] != ERR_PROPERTY_CREDIT_LIMIT_EXCEEDED

        subscription = fx.read_subscription(api, env.subscription_id)
        assert subscription["status"] == "PENDING_SETUP"
        assert subscription["version"] == 1
        assert fx.read_ledger(api, env.subscription_id) == []
        assert a.property_balance(api, env.property_id, OPERATOR) == 0

    def test_the_credit_ceiling_answers_once_the_property_is_active_again(self, api):
        """
        Reactivating the property clears rule 8 and leaves rule 30 as the only
        violation, so the very same activation now answers
        ERR_PROPERTY_CREDIT_LIMIT_EXCEEDED at 402 — the fiscal breach was real in
        the first attempt too, merely outranked.

        PRD §2.10: "The property's credit ceiling absorbs the charge this request would post — otherwise `ERR_PROPERTY_CREDIT_LIMIT_EXCEEDED` (402)."

        Design: Difficulty/priority_pair_validation_conflict/property_state_priority_8_beats_credit_limit_priority_30_on_activate
        """
        env = _thin_margin_env(api)
        validate_error(
            api.activate_subscription(env.subscription_id, OPERATOR),
            ERR_PROPERTY_NOT_ACTIVE,
            409,
        )

        validate_success(api.reactivate_property(env.property_id, OPERATOR))
        validate_error(
            api.activate_subscription(env.subscription_id, OPERATOR),
            ERR_PROPERTY_CREDIT_LIMIT_EXCEEDED,
            402,
        )

        subscription = fx.read_subscription(api, env.subscription_id)
        assert subscription["status"] == "PENDING_SETUP"
        assert fx.read_ledger(api, env.subscription_id) == []
        assert a.property_balance(api, env.property_id, OPERATOR) == 0


def _basic_ridge_env(api):
    """
    An ACTIVE subscription at a BASIC property with the damage waiver switched
    off, read at a clock 97 days past activation.
    """
    env = fx.build_base_env(
        api,
        property_overrides={
            "name": "Basic Ridge",
            "benefit_tier": "BASIC",
            "damage_waiver_enabled": False,
            "aqg_enabled": True,
        },
    )
    fx.set_clock(api, "2026-11-10T00:00:00Z")
    return env


class TestEntitlementBeatsCoverageWindow:
    """Rule 17 answers before rule 18 on claim filing."""

    def test_missing_entitlement_answers_before_the_stale_incident_date(self, api):
        """
        A DAMAGE_WAIVER claim on a property that never bought the waiver is also 91
        days stale, yet the answer is ERR_BENEFIT_NOT_ENTITLED rather than
        ERR_OUTSIDE_COVERAGE_WINDOW, and no claim row is created.

        PRD §2.10: "The entitlement whose `benefit_code` equals the claim's `claim_type` exists on the claim's subscription and is `ACTIVE` — otherwise `ERR_BENEFIT_NOT_ENTITLED` (422)."

        Design: Difficulty/priority_pair_validation_conflict/entitlement_priority_17_beats_coverage_window_priority_18_on_claim_submit
        """
        env = _basic_ridge_env(api)
        subscription = fx.read_subscription(api, env.subscription_id)
        assert "DAMAGE_WAIVER" not in subscription["entitled_benefit_codes"]

        response = api.create_claim(
            f.claim_payload(
                env.subscription_id,
                claim_type="DAMAGE_WAIVER",
                incident_date="2026-08-11",
                description="Grille damage discovered late",
            ),
            env.pm_headers,
        )
        validate_error(response, ERR_BENEFIT_NOT_ENTITLED, 422)
        assert response.json()["data"]["error_id"] != ERR_OUTSIDE_COVERAGE_WINDOW

        assert validate_success(
            api.list_subscription_claims(env.subscription_id, OPERATOR)
        ) == []

    def test_the_coverage_window_answers_for_an_entitled_benefit(self, api):
        """
        The same stale incident date filed against the air-quality guarantee — a
        benefit this property does own — clears rule 17 and lands on
        ERR_OUTSIDE_COVERAGE_WINDOW, proving the window was genuinely breached in
        the waiver attempt as well.

        PRD §2.10: "The claim's `incident_date` falls inside the coverage window — otherwise `ERR_OUTSIDE_COVERAGE_WINDOW` (422)."

        Design: Difficulty/priority_pair_validation_conflict/entitlement_priority_17_beats_coverage_window_priority_18_on_claim_submit
        """
        env = _basic_ridge_env(api)
        rows = fx.read_entitlements(api, env.subscription_id)
        a.assert_entitlement(a.entitlement_by_code(rows, "AIR_QUALITY_GUARANTEE"), "ACTIVE")

        validate_error(
            api.create_claim(
                f.claim_payload(
                    env.subscription_id,
                    claim_type="AIR_QUALITY_GUARANTEE",
                    incident_date="2026-08-11",
                    description="Air quality complaint discovered late",
                ),
                env.pm_headers,
            ),
            ERR_OUTSIDE_COVERAGE_WINDOW,
            422,
        )

        assert validate_success(
            api.list_subscription_claims(env.subscription_id, OPERATOR)
        ) == []
