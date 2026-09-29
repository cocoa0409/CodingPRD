"""Two variants of the same computation over byte-identical stored data."""

from test_helpers import (
    ComplianceWorld,
    OFFICER_2,
    assert_cents,
    assert_decimal_4,
    assert_equals,
    assert_fields,
    assert_provider_counters,
    build_signing_ready_provider,
    expect_created,
    expect_ok,
)
from test_helpers.constants import NUMBER_1, NUMBER_2, NUMBER_3, NUMBER_CALLED
from test_helpers.factories import (
    effectiveness_report_payload,
    enforcement_action_payload,
)


def _build_reporting_domain(world: ComplianceWorld):
    """One provider whose August holds two signed calls, two tracebacks and two
    notices, exactly one of each pair being finished work."""
    setup = build_signing_ready_provider(world)
    provider_id = setup.provider_id
    customer_id = setup.customer_id

    # Two signed calls inside the period: the first from an owned number, the
    # second from a number the customer holds no assignment for.
    owned_call = world.sign_call(
        provider_id, customer_id, NUMBER_1, NUMBER_CALLED, "2026-08-02T00:00:00Z"
    )
    world.sign_call(
        provider_id, customer_id, NUMBER_2, NUMBER_CALLED, "2026-08-03T00:00:00Z"
    )

    # One traceback answered inside its window.
    world.set_clock("2026-08-05T00:00:00Z")
    answered = world.open_traceback(
        provider_id,
        calling_number=NUMBER_1,
        called_number=NUMBER_CALLED,
        origination_time="2026-08-02T00:00:00Z",
    )
    world.respond_traceback(answered["id"], customer_id, owned_call["id"])

    # One notice discharged by blocking all of the attributed traffic.
    world.set_clock("2026-08-10T00:00:00Z")
    discharged = world.serve_notice(provider_id, calling_number=NUMBER_1)
    world.investigate_notice(discharged["id"], customer_id)
    world.mitigate_notice(discharged["id"], "TRAFFIC_BLOCKED")

    # One traceback still answerable and one notice still inside its deadline.
    world.set_clock("2026-08-31T12:00:00Z")
    world.open_traceback(
        provider_id,
        calling_number=NUMBER_1,
        called_number=NUMBER_CALLED,
        origination_time="2026-08-02T00:00:00Z",
    )
    world.serve_notice(provider_id, calling_number=NUMBER_3)

    world.set_clock("2026-09-01T00:00:00Z")
    return setup


def _generate(world: ComplianceWorld, provider_id: str, variant: str):
    payload = effectiveness_report_payload(
        provider_id, world.provider_version(provider_id), variant=variant
    )
    return expect_created(
        world.client.create_effectiveness_report(payload, world.officer(OFFICER_2))
    )


class TestEffectivenessVariantsOnOnePeriod:
    """The provisional and certified readings of one elapsed period."""

    def test_provisional_variant_keeps_pending_work_in_the_numerator(self, world):
        """Pending traceback and open notice both count, so the score is 0.8000.

        PRD: "`PROVISIONAL` presumes that a traceback still inside its response window and a notice still inside its mitigation deadline will land compliant, so both count toward the numerator."

        Design: Difficulty/dual_variant_calc/effectiveness_provisional_vs_certified_on_same_period
        """
        setup = _build_reporting_domain(world)

        report = _generate(world, setup.provider_id, "PROVISIONAL")

        assert_fields(
            report,
            signed_call_count=2,
            attestation_a_count=1,
            traceback_total_count=2,
            traceback_on_time_count=1,
            data_sufficiency="SUFFICIENT",
            variant="PROVISIONAL",
            state="GENERATED",
            score_band="HIGH",
        )
        assert_decimal_4(report, "attestation_component", 0.5000)
        assert_decimal_4(report, "traceback_component", 1.0000)
        assert_decimal_4(report, "notice_component", 1.0000)
        assert_decimal_4(report, "effectiveness_score", 0.8000)

    def test_certified_variant_drops_pending_work_and_supersedes_the_provisional(
        self, world
    ):
        """The identical period certified scores 0.5000 and supersedes the earlier row.

        PRD: "`CERTIFIED` counts only finished work: pending tracebacks and open notices are excluded from the numerator while remaining in the denominator, so certifying a period can only lower the score or leave it unchanged."

        Design: Difficulty/dual_variant_calc/effectiveness_provisional_vs_certified_on_same_period
        """
        setup = _build_reporting_domain(world)
        provisional = _generate(world, setup.provider_id, "PROVISIONAL")

        certified = _generate(world, setup.provider_id, "CERTIFIED")

        assert_fields(
            certified,
            signed_call_count=2,
            attestation_a_count=1,
            traceback_total_count=2,
            traceback_on_time_count=1,
            state="GENERATED",
            score_band="LOW",
        )
        assert_decimal_4(certified, "attestation_component", 0.5000)
        assert_decimal_4(certified, "traceback_component", 0.5000)
        assert_decimal_4(certified, "notice_component", 0.5000)
        assert_decimal_4(certified, "effectiveness_score", 0.5000)

        stale = expect_ok(
            world.client.get_effectiveness_report(provisional["id"], world.regulator)
        )
        assert_equals(stale, "state", "SUPERSEDED")


def _build_high_band_provider(world: ComplianceWorld):
    """A provider whose one signed call gives it a certified HIGH band."""
    setup = build_signing_ready_provider(world)
    world.sign_call(
        setup.provider_id,
        setup.customer_id,
        NUMBER_1,
        NUMBER_CALLED,
        "2026-08-02T00:00:00Z",
    )
    world.set_clock("2026-09-01T00:00:00Z")
    report = world.generate_report(
        setup.provider_id, variant="PROVISIONAL", officer_id=OFFICER_2
    )
    signed_off = world.certify_report(report["id"], OFFICER_2)
    assert_equals(signed_off, "state", "SIGNED_OFF")
    assert_decimal_4(signed_off, "effectiveness_score", 1.0000)
    return setup


class TestForfeitureAssessmentBasesOnOneBody:
    """The same violation body assessed per violation and per continuing day."""

    def test_per_violation_election_charges_the_violation_count(self, world):
        """Three violations bill 3,000,000 cents, TIER_2, 25 percent credit, 2,250,000 due.

        PRD: "With `violation_count` 3, `violation_days` 10 and band `HIGH`, an election of `PER_VIOLATION` gives a base of 3,000,000 cents, which is `TIER_2`, a credit of 25 percent or 750,000 cents, and a total of 2,250,000 cents — while `CONTINUING_DAILY` on the very same body gives a base of 2,500,000 cents, still `TIER_2`, a credit of 625,000 cents, and a total of 1,875,000 cents."

        Design: Difficulty/dual_variant_calc/forfeiture_per_violation_vs_continuing_daily_on_same_body
        """
        setup = _build_high_band_provider(world)

        action = expect_created(
            world.client.create_enforcement_action(
                enforcement_action_payload(
                    setup.provider_id,
                    basis="FALSE_ATTESTATION",
                    violation_count=3,
                    violation_days=10,
                    assessment_basis="PER_VIOLATION",
                ),
                world.regulator,
            )
        )

        assert_fields(action, assessment_tier="TIER_2", score_band="HIGH")
        assert_cents(action, "base_assessment_cents", 3000000)
        assert_cents(action, "base_capped_cents", 3000000)
        assert_cents(action, "mitigation_credit_cents", 750000)
        assert_cents(action, "total_forfeiture_cents", 2250000)

    def test_continuing_daily_election_charges_the_violation_days(self, world):
        """The identical body billed by day totals 1,875,000, and both rows stay outstanding.

        PRD: "`outstanding_forfeiture_cents` is the sum of `total_forfeiture_cents` over the provider's enforcement actions whose `status` is `PROPOSED`, `CONTESTED` or `SUSTAINED`."

        Design: Difficulty/dual_variant_calc/forfeiture_per_violation_vs_continuing_daily_on_same_body
        """
        setup = _build_high_band_provider(world)
        body = dict(
            basis="FALSE_ATTESTATION",
            violation_count=3,
            violation_days=10,
        )

        per_violation = expect_created(
            world.client.create_enforcement_action(
                enforcement_action_payload(
                    setup.provider_id, assessment_basis="PER_VIOLATION", **body
                ),
                world.regulator,
            )
        )
        continuing = expect_created(
            world.client.create_enforcement_action(
                enforcement_action_payload(
                    setup.provider_id, assessment_basis="CONTINUING_DAILY", **body
                ),
                world.regulator,
            )
        )

        assert_fields(continuing, assessment_tier="TIER_2", score_band="HIGH")
        assert_cents(continuing, "base_assessment_cents", 2500000)
        assert_cents(continuing, "mitigation_credit_cents", 625000)
        assert_cents(continuing, "total_forfeiture_cents", 1875000)
        assert_cents(per_violation, "total_forfeiture_cents", 2250000)

        provider = world.read_provider(setup.provider_id)
        assert_provider_counters(provider, outstanding_forfeiture_cents=4125000)
