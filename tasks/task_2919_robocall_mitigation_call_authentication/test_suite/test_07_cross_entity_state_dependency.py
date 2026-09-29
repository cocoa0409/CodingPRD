"""Refusals whose whole cause lives on a different row than the request body."""

from test_helpers import (
    ComplianceWorld,
    OFFICER_1,
    OFFICER_2,
    assert_decimal_4,
    assert_equals,
    assert_fields,
    assert_provider_counters,
    build_signing_ready_provider,
    expect_created,
    expect_error,
    expect_list_total,
    expect_ok,
)
from test_helpers.api_errors import ERR_PLAN_STATE_INVALID, ERR_SIGNING_SUSPENDED
from test_helpers.constants import NUMBER_1, NUMBER_3, NUMBER_CALLED
from test_helpers.factories import (
    call_attestation_payload,
    effectiveness_report_payload,
)


def _build_points_suspended_provider(world: ComplianceWorld):
    """A provider whose own rows are all in order, but whose two ignored notices
    have taken its penalty points to the suspension threshold."""
    setup = build_signing_ready_provider(world)
    world.set_clock("2026-08-10T00:00:00Z")
    first = world.serve_notice(setup.provider_id, calling_number=NUMBER_1)
    second = world.serve_notice(setup.provider_id, calling_number=NUMBER_3)
    world.set_clock("2026-08-12T00:00:01Z")
    world.run_sweep(setup.provider_id)
    return setup, first, second


class TestAttestationRefusedByProviderPosture:
    """Signing blocked by the parent provider's accumulated penalty points."""

    def test_two_expired_notices_take_the_posture_to_signing_suspended(self, world):
        """Ten points fire step one even though the certificate is still ACTIVE.

        PRD: "**Step one:** if `rmd_filing_status` is `UNFILED`, or `penalty_points` is at least 10, or the provider's `active_certificate_id` is null, then `auth_posture` becomes `SIGNING_SUSPENDED`."

        Design: Difficulty/cross_entity_state_dependency/attestation_refused_by_provider_posture_not_by_its_own_fields
        """
        setup, first, second = _build_points_suspended_provider(world)

        assert_equals(world.read_notice(first["id"]), "state", "EXPIRED_UNMITIGATED")
        assert_equals(world.read_notice(second["id"]), "state", "EXPIRED_UNMITIGATED")

        provider = world.read_provider(setup.provider_id)
        assert_provider_counters(
            provider,
            penalty_points=10,
            auth_posture="SIGNING_SUSPENDED",
            rmd_filing_status="COMPLETE",
            active_certificate_id=setup.certificate_id,
        )
        assert_equals(world.read_certificate(setup.certificate_id), "status", "ACTIVE")

    def test_signing_is_refused_though_every_field_of_the_request_is_valid(self, world):
        """A verified, enabled customer on an owned number is still refused, 409.

        PRD: "The provider's `auth_posture` must not be `SIGNING_SUSPENDED`, or the refusal is `ERR_SIGNING_SUSPENDED` (409); that code guards signing and nothing else."

        Design: Difficulty/cross_entity_state_dependency/attestation_refused_by_provider_posture_not_by_its_own_fields
        """
        setup, _first, _second = _build_points_suspended_provider(world)
        assert_fields(
            world.read_customer(setup.customer_id),
            kyc_state="VERIFIED",
            origination_state="ENABLED",
        )

        expect_error(
            world.client.create_call_attestation(
                call_attestation_payload(
                    setup.provider_id,
                    setup.customer_id,
                    NUMBER_1,
                    NUMBER_CALLED,
                    "2026-08-12T00:00:01Z",
                ),
                world.provider_admin(setup.provider_id),
            ),
            ERR_SIGNING_SUSPENDED,
        )

        _items, _meta = expect_list_total(
            world.client.list_call_attestations(
                world.regulator, provider_id=setup.provider_id
            ),
            0,
        )


def _build_report_over_deficient_plan(world: ComplianceWorld):
    """A generated report whose provider's operative plan sits in DEFICIENT."""
    provider = world.register_provider(provider_type="NON_FACILITIES_RESELLER")
    plan = world.submitted_plan(
        provider["id"],
        officer_id=OFFICER_1,
        practices=["KYC_ONBOARDING", "TRACEBACK_COOPERATION", "CONTRACT_TERMS_PROHIBITION"],
    )
    world.decide_plan(
        plan["id"],
        "DEFICIENT",
        deficiency_reasons=["Traceback contact point not staffed"],
    )
    world.set_clock("2026-09-01T00:00:00Z")
    report = expect_created(
        world.client.create_effectiveness_report(
            effectiveness_report_payload(
                provider["id"], world.provider_version(provider["id"]),
                variant="PROVISIONAL",
            ),
            world.officer(OFFICER_2),
        )
    )
    return provider["id"], plan["id"], report["id"]


class TestReportCertificationBlockedByPlanState:
    """Sign-off gated on a row the report does not reference."""

    def test_a_deficient_operative_plan_refuses_certification(self, world):
        """The report is in the only state certify accepts, and is still refused 409.

        PRD: "A `ComplianceOfficer` other than the one who filed the operative mitigation plan — per the third gate of §2.12 — signs off a `GENERATED` report, which requires that the provider's operative plan (the plan whose `filing_state` is neither `WITHDRAWN` nor `SUPERSEDED`) be `ACCEPTED`; if it is not, the refusal is `ERR_PLAN_STATE_INVALID` (409)."

        Design: Difficulty/cross_entity_state_dependency/report_certification_blocked_by_operative_plan_state
        """
        provider_id, plan_id, report_id = _build_report_over_deficient_plan(world)

        expect_error(
            world.client.certify_effectiveness_report(
                report_id, world.officer(OFFICER_2)
            ),
            ERR_PLAN_STATE_INVALID,
        )

        report = expect_ok(
            world.client.get_effectiveness_report(report_id, world.regulator)
        )
        assert_equals(report, "state", "GENERATED")
        assert_fields(
            world.read_plan(plan_id), filing_state="DEFICIENT", deficiency_count=1
        )
        assert_provider_counters(world.read_provider(provider_id), penalty_points=2)

    def test_accepting_the_plan_lets_the_identical_certify_call_through(self, world):
        """Repairing the plan alone flips the report to SIGNED_OFF and CERTIFIED.

        PRD: "Sign-off advances `GENERATED → SIGNED_OFF`, records the signing officer's `X-User-ID` as `signed_off_by_user_id`, stamps `signed_off_at`, **overwrites `variant` with `CERTIFIED`**, and recomputes every count, every component, the `effectiveness_score`, the `score_band` and `data_sufficiency` in place under that variant."

        Design: Difficulty/cross_entity_state_dependency/report_certification_blocked_by_operative_plan_state
        """
        provider_id, plan_id, report_id = _build_report_over_deficient_plan(world)
        expect_error(
            world.client.certify_effectiveness_report(
                report_id, world.officer(OFFICER_2)
            ),
            ERR_PLAN_STATE_INVALID,
        )

        resubmitted = world.submit_plan(plan_id, OFFICER_1)
        assert_fields(resubmitted, filing_state="SUBMITTED", revision_count=1)
        accepted = world.decide_plan(plan_id, "ACCEPT")
        assert_fields(accepted, filing_state="ACCEPTED", deficiency_count=1)

        signed_off = expect_ok(
            world.client.certify_effectiveness_report(
                report_id, world.officer(OFFICER_2)
            )
        )

        assert_fields(
            signed_off,
            state="SIGNED_OFF",
            variant="CERTIFIED",
            signed_off_by_user_id=OFFICER_2,
        )
        assert_decimal_4(signed_off, "effectiveness_score", 0.6000)
        assert_provider_counters(world.read_provider(provider_id), penalty_points=2)
