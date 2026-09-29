"""
The two non-linear state machines: a subscription's commercial and compliance
dimensions travelling their own cycles on one row, and the bounded
UNDER_REVIEW -> INFO_REQUESTED -> UNDER_REVIEW claim revision loop.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_INFO_REQUEST_LIMIT
from test_helpers.test_users import ADJUSTER_A, OPERATOR


def _suspect_env(api, runtime_minutes: int = 168):
    """Fixture A with a delivered shipment and two rising-pressure windows."""
    env = fx.build_base_env(api)
    fx.deliver_first_shipment(api, env.subscription_id, "2026-08-06T00:00:00Z")
    fx.add_runtime_reading(
        api, env.unit_id, "2026-08-07T00:00:00Z", "2026-08-08T00:00:00Z",
        runtime_minutes, 100, "PRESSURE_SENSOR",
    )
    fx.add_runtime_reading(
        api, env.unit_id, "2026-08-08T00:00:00Z", "2026-08-09T00:00:00Z",
        runtime_minutes, 120, "PRESSURE_SENSOR",
    )
    fx.set_clock(api, "2026-08-09T00:00:00Z")
    return env


class TestSubscriptionTwoDimensions:
    """status and installation_posture cycle independently on the same row."""

    def test_commercial_cycle_closes_without_disturbing_the_compliance_dimension(self, api):
        """
        The subscription runs ACTIVE -> SUSPENDED -> ACTIVE under a property
        suspend/reactivate pair while its posture climbs UNVERIFIED ->
        NON_INSTALL_SUSPECTED -> NON_INSTALL_CONFIRMED; notice and confirmation are
        accepted while the commercial dimension sits in SUSPENDED, and the
        reactivation restores RENTERS_INSURANCE without resurrecting the two
        forfeited riders.

        PRD §2.8: "A subscription may legitimately be `ACTIVE` and `NON_INSTALL_CONFIRMED` at the same time, or `SUSPENDED` and `COMPLIANT`."

        Design: Difficulty/non_linear_state_machine/subscription_two_dimensions_advance_independently_through_both_cycles
        """
        env = _suspect_env(api)

        case = fx.open_case(api, env.subscription_id, "RUNTIME_ANALYTICS", "2026-08-09")
        assert case["evidence_score"] == 62
        assert case["status"] == "OPEN"
        after_eval = fx.read_subscription(api, env.subscription_id)
        assert after_eval["installation_posture"] == "NON_INSTALL_SUSPECTED"
        assert after_eval["status"] == "ACTIVE"

        validate_success(
            api.suspend_property(env.property_id, f.suspend_payload(), OPERATOR)
        )
        suspended = fx.read_subscription(api, env.subscription_id)
        assert suspended["status"] == "SUSPENDED"
        assert suspended["installation_posture"] == "NON_INSTALL_SUSPECTED"

        # Compliance work proceeds while billing is suspended.
        validate_success(api.send_case_notice(case["id"], OPERATOR))
        fx.set_clock(api, "2026-09-11T00:00:00Z")
        validate_success(api.confirm_case(case["id"], OPERATOR))
        assert validate_success(api.get_non_install_case(case["id"], OPERATOR))["status"] == (
            "ESCALATED_TO_PM"
        )
        confirmed = fx.read_subscription(api, env.subscription_id)
        assert confirmed["status"] == "SUSPENDED"
        assert confirmed["installation_posture"] == "NON_INSTALL_CONFIRMED"
        a.assert_cents(confirmed["monthly_fee_cents"], 2546, "monthly_fee_cents")

        rows = fx.read_entitlements(api, env.subscription_id)
        a.assert_entitlement(a.entitlement_by_code(rows, "DAMAGE_WAIVER"), "FORFEITED")
        a.assert_entitlement(
            a.entitlement_by_code(rows, "AIR_QUALITY_GUARANTEE"), "FORFEITED"
        )

        validate_success(api.reactivate_property(env.property_id, OPERATOR))
        reactivated = fx.read_subscription(api, env.subscription_id)
        assert reactivated["status"] == "ACTIVE"
        assert reactivated["installation_posture"] == "NON_INSTALL_CONFIRMED"

        restored = fx.read_entitlements(api, env.subscription_id)
        assert a.active_benefit_codes(restored) == ["CREDIT_REPORTING", "RENTERS_INSURANCE"]
        a.assert_entitlement(a.entitlement_by_code(restored, "DAMAGE_WAIVER"), "FORFEITED")
        a.assert_entitlement(
            a.entitlement_by_code(restored, "AIR_QUALITY_GUARANTEE"), "FORFEITED"
        )

    def test_compliance_cycle_closes_back_to_compliant_without_restoring_the_riders(self, api):
        """
        Remediation moves the posture to REMEDIATED and a later clean evaluation
        scoring 16 closes the loop at COMPLIANT while the commercial dimension
        never leaves ACTIVE — and the monthly fee stays at the post-forfeiture
        2546, because closing the posture cycle restores nothing.

        PRD §3.6: "Remediation deliberately does **not** un-forfeit anything — forfeiture is permanent for that subscription, and the closest the subscription can get to whole again is a subsequent clean evaluation moving `REMEDIATED → COMPLIANT`."

        Design: Difficulty/non_linear_state_machine/subscription_two_dimensions_advance_independently_through_both_cycles
        """
        env = _suspect_env(api)
        case = fx.open_case(api, env.subscription_id, "RUNTIME_ANALYTICS", "2026-08-09")
        validate_success(api.send_case_notice(case["id"], OPERATOR))
        validate_success(api.confirm_case(case["id"], OPERATOR))

        validate_success(api.remediate_case(case["id"], f.remediate_payload(), OPERATOR))
        assert validate_success(api.get_non_install_case(case["id"], OPERATOR))["status"] == (
            "REMEDIATED"
        )
        remediated = fx.read_subscription(api, env.subscription_id)
        assert remediated["installation_posture"] == "REMEDIATED"
        assert remediated["status"] == "ACTIVE"

        # A second, clean evidence period: flat pressure and idle blower.
        second = validate_success(
            api.create_shipment(
                env.subscription_id, f.shipment_payload("2026-10-19", 2), OPERATOR
            ),
            201,
        )
        validate_success(
            api.ship_shipment(second["id"], f.ship_payload("TRK-A-0002"), OPERATOR)
        )
        validate_success(
            api.deliver_shipment(
                second["id"], f.deliver_payload("2026-10-19T00:00:00Z"), OPERATOR
            )
        )
        fx.add_runtime_reading(
            api, env.unit_id, "2026-10-20T00:00:00Z", "2026-10-21T00:00:00Z",
            48, 100, "PRESSURE_SENSOR",
        )
        fx.add_runtime_reading(
            api, env.unit_id, "2026-10-21T00:00:00Z", "2026-10-22T00:00:00Z",
            48, 105, "PRESSURE_SENSOR",
        )
        fx.set_clock(api, "2026-10-22T00:00:00Z")

        clean = fx.open_case(api, env.subscription_id, "RUNTIME_ANALYTICS", "2026-10-22")
        assert clean["evidence_score"] == 16
        assert clean["status"] == "CLOSED_UNSUBSTANTIATED"

        closed = fx.read_subscription(api, env.subscription_id)
        assert closed["installation_posture"] == "COMPLIANT"
        assert closed["status"] == "ACTIVE"
        a.assert_cents(closed["monthly_fee_cents"], 2546, "monthly_fee_cents")


class TestClaimRevisionLoop:
    """UNDER_REVIEW -> INFO_REQUESTED -> UNDER_REVIEW, bounded at two rounds."""

    def _claim_under_review(self, api):
        env = fx.build_base_env(api)
        claim = validate_success(
            api.create_claim(
                f.claim_payload(
                    env.subscription_id,
                    description="Return grille bent during filter swap",
                ),
                env.pm_headers,
            ),
            201,
        )
        triaged = validate_success(api.triage_claim(claim["id"], ADJUSTER_A))
        assert triaged["status"] == "UNDER_REVIEW"
        assert triaged["info_request_round"] == 0
        a.assert_cents(triaged["provisional_amount_cents"], 30000, "provisional_amount_cents")
        return env, claim

    def test_two_rounds_are_allowed_and_the_triage_freeze_survives_both(self, api):
        """
        Each request-info moves the claim to INFO_REQUESTED and lifts
        info_request_round by one; each resubmit brings it back to UNDER_REVIEW
        leaving the round counter alone and the provisional figure frozen at the
        30000 computed at triage.

        PRD §3.7: "Resubmission explicitly does **not** recompute `provisional_amount_cents`: the triage-time freeze survives every iteration of the loop."

        Design: Difficulty/non_linear_state_machine/claim_info_request_revision_loop_bounded_at_two_rounds
        """
        _env, claim = self._claim_under_review(api)

        first_ask = validate_success(
            api.request_claim_info(
                claim["id"],
                f.request_info_payload("Send the pre-damage photograph of the return grille"),
                ADJUSTER_A,
            )
        )
        assert first_ask["status"] == "INFO_REQUESTED"
        assert first_ask["info_request_round"] == 1

        first_back = validate_success(
            api.resubmit_claim(
                claim["id"],
                OPERATOR,
                f.resubmit_payload("Photograph attached; grille bent at the lower corner"),
            )
        )
        assert first_back["status"] == "UNDER_REVIEW"
        assert first_back["info_request_round"] == 1
        a.assert_cents(first_back["provisional_amount_cents"], 30000, "provisional after round 1")

        second_ask = validate_success(
            api.request_claim_info(
                claim["id"], f.request_info_payload("Send the vendor repair quote"), ADJUSTER_A
            )
        )
        assert second_ask["status"] == "INFO_REQUESTED"
        assert second_ask["info_request_round"] == 2

        second_back = validate_success(
            api.resubmit_claim(
                claim["id"],
                OPERATOR,
                f.resubmit_payload("Vendor quote attached at 40000 cents"),
            )
        )
        assert second_back["status"] == "UNDER_REVIEW"
        assert second_back["info_request_round"] == 2
        a.assert_cents(second_back["provisional_amount_cents"], 30000, "provisional after round 2")

    def test_third_request_info_is_refused_and_changes_nothing(self, api):
        """
        A third request-info on a claim whose info_request_round already reads 2 is
        rejected with ERR_INFO_REQUEST_LIMIT, and the refusal is total: the claim
        stays UNDER_REVIEW at round 2 and its version does not move past the six
        mutations that actually landed.

        PRD §3.7: "The loop is bounded: a request-info attempt on a claim whose `info_request_round` has already reached two is rejected with `ERR_INFO_REQUEST_LIMIT`, so at most two round trips are possible."

        Design: Difficulty/non_linear_state_machine/claim_info_request_revision_loop_bounded_at_two_rounds
        """
        _env, claim = self._claim_under_review(api)

        for question, answer in (
            ("Send the pre-damage photograph of the return grille", "Photograph attached"),
            ("Send the vendor repair quote", "Vendor quote attached at 40000 cents"),
        ):
            validate_success(
                api.request_claim_info(claim["id"], f.request_info_payload(question), ADJUSTER_A)
            )
            validate_success(
                api.resubmit_claim(claim["id"], OPERATOR, f.resubmit_payload(answer))
            )

        validate_error(
            api.request_claim_info(
                claim["id"],
                f.request_info_payload("Send a second competing quote"),
                ADJUSTER_A,
            ),
            ERR_INFO_REQUEST_LIMIT,
            422,
        )

        after = validate_success(api.get_claim(claim["id"], ADJUSTER_A))
        assert after["status"] == "UNDER_REVIEW"
        assert after["info_request_round"] == 2
        assert after["version"] == 6
