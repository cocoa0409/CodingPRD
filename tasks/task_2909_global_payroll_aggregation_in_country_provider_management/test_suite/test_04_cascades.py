"""Transitive cascades that cross three entity levels in one request.

Confirming an incident and sweeping a missed obligation are both single acts that
must land on the provider, on its live engagements and on their draft cycles
before the response is returned.
"""

from test_helpers import assertions as a
from test_helpers import fixtures as fx
from test_helpers.constants import (
    CYCLE_ON_HOLD,
    CYCLE_RESULTS_APPROVED,
    ENGAGEMENT_REMEDIATION_REQUIRED,
    FILING_TYPE_INCOME_TAX_WITHHOLDING,
    HOLD_REASON_PROVIDER_PROBATION,
    PENALTY_OWNER_PROVIDER,
    PROVIDER_PROBATION,
    SCORE_VARIANT_ENGAGEMENT_TO_DATE,
    SEV1,
)

# 60 000 minor units a day over three late days on top of the 25 000 statutory
# base carries the accrual past the second ceiling and into the 20.00 percent tier.
_EXPENSIVE_COUNTRY = {
    "country_code": "PL",
    "required_filing_types": [FILING_TYPE_INCOME_TAX_WITHHOLDING],
    "penalty_daily_rate_minor": 60000,
}
_PROVIDER = {"legal_name": "VistulaPay Sp z oo"}


def _second_confirmation(api):
    """An estate with one confirmed SEV1 already scored and a second one open."""
    ctx = fx.setup_draft_cycle(api)
    fx.confirmed_incident(api, ctx["engagement_id"], SEV1)
    second = fx.raise_incident(api, ctx["engagement_id"], SEV1)
    return ctx, second


def _swept_expensive_filing(api):
    """A held-open September draft, plus an August obligation swept three days late."""
    ctx = fx.setup_active_engagement(
        api, country_overrides=_EXPENSIVE_COUNTRY, provider_overrides=_PROVIDER
    )
    september = fx.create_cycle(
        api,
        ctx["engagement_id"],
        period_label="2026-09",
        period_start_date="2026-09-01",
        period_end_date="2026-10-01",
        pay_date="2026-09-30",
    )
    ctx = fx.setup_draft_cycle(api, ctx)
    ctx = fx.setup_validated_extract(api, ctx)
    ctx = fx.setup_locked_cycle(api, ctx)
    ctx = fx.setup_scored_run(api, ctx)
    ctx = fx.setup_results_approved_cycle(api, ctx)

    fx.set_clock(api, "2026-09-13T12:00:00Z")
    swept = fx.sweep_filings(api, ctx["cycle_id"])
    filing = a.find_by(swept, "filing_type", FILING_TYPE_INCOME_TAX_WITHHOLDING)
    ctx = dict(ctx)
    ctx["september_cycle_id"] = september["id"]
    return ctx, filing


def test_second_incident_confirmation_drops_the_provider_to_probation(api):
    """Confirming the second SEV1 finding takes the score to 50.00, which is inside
    the probation band, and the standing is re-derived in that same request.

    PRD 3.8: "A score at least 40.00 but below 55.00 makes it `PROBATION`."

    Design: Difficulty/transitive_cascade/incident_confirmation_cascades_score_to_provider_engagement_and_cycle
    """
    ctx, second = _second_confirmation(api)

    confirmed = fx.confirm_incident(api, second["id"])
    a.assert_pct(confirmed["weight_points"], 25.00, "weight_points")

    provider = fx.read_provider(api, ctx["provider_id"])
    a.assert_provider_standing(
        provider,
        status=PROVIDER_PROBATION,
        service_score=50.00,
        open_penalty_minor=0,
        score_variant_applied=SCORE_VARIANT_ENGAGEMENT_TO_DATE,
    )


def test_incident_confirmation_reaches_the_engagement_and_its_draft_cycle(api):
    """The degradation travels down three levels: provider, then engagement, then
    the cycle still sitting in draft.

    PRD 3.8: "When a provider becomes `PROBATION` or `SUSPENDED`, every engagement
    of that provider whose `status` is `ACTIVE` moves `ACTIVE → REMEDIATION_REQUIRED`
    and has its `transition_required` set to true, and every cycle of those
    engagements sitting in `DRAFT` moves `DRAFT → ON_HOLD` with `hold_reason` set to
    `PROVIDER_PROBATION` when the provider is on probation or `PROVIDER_SUSPENSION`
    when the provider is suspended."

    Design: Difficulty/transitive_cascade/incident_confirmation_cascades_score_to_provider_engagement_and_cycle
    """
    ctx, second = _second_confirmation(api)

    fx.confirm_incident(api, second["id"])

    engagement = fx.read_engagement(api, ctx["engagement_id"])
    assert engagement["status"] == ENGAGEMENT_REMEDIATION_REQUIRED, (
        f"the engagement enters remediation, got {engagement['status']}"
    )
    assert engagement["transition_required"] is True, (
        f"transition_required is set, got {engagement['transition_required']}"
    )

    cycle = fx.read_cycle(api, ctx["cycle_id"])
    a.assert_cycle_state(
        cycle, CYCLE_ON_HOLD, hold_reason=HOLD_REASON_PROVIDER_PROBATION
    )


def test_filing_sweep_exposure_puts_the_provider_on_probation(api):
    """The swept penalty pushes the provider's unresolved exposure past 100 000, and
    that alone is enough for probation even though the service score is perfect.

    PRD 3.7: "`penalty_status` moves `NONE → ASSESSED`, the provider's
    `open_penalty_minor` increases by the new `provider_share_minor`, and if that
    running exposure now exceeds 100000 local minor units the provider drops
    `ACTIVE → PROBATION`, which cascades to its live engagements and their draft
    cycles as described in the next subsection."

    PRD 3.7: "That probation path leaves `service_score` untouched: penalty exposure
    and service quality are independent grounds for probation."

    Design: Difficulty/transitive_cascade/filing_sweep_cascades_penalty_exposure_to_provider_probation_and_hold
    """
    ctx, filing = _swept_expensive_filing(api)

    a.assert_penalty_assessment(
        filing,
        late_days=3,
        base_penalty_minor=205000,
        surcharge_minor=41000,
        total_penalty_minor=246000,
        provider_share_minor=246000,
        client_share_minor=0,
        penalty_owner=PENALTY_OWNER_PROVIDER,
    )

    provider = fx.read_provider(api, ctx["provider_id"])
    a.assert_provider_standing(
        provider,
        status=PROVIDER_PROBATION,
        service_score=100.00,
        open_penalty_minor=246000,
    )


def test_filing_sweep_holds_only_the_draft_cycle_of_the_engagement(api):
    """The hold reaches the September draft while the August period that produced
    the penalty, being past draft, keeps its approved state.

    PRD 3.3: "When the engaged provider's standing degrades, every cycle of the
    affected engagements that is still in `DRAFT` is moved `DRAFT → ON_HOLD` by the
    system, and `hold_reason` is set to `PROVIDER_PROBATION` when the provider went
    on probation or `PROVIDER_SUSPENSION` when the provider was suspended."

    Design: Difficulty/transitive_cascade/filing_sweep_cascades_penalty_exposure_to_provider_probation_and_hold
    """
    ctx, _ = _swept_expensive_filing(api)

    engagement = fx.read_engagement(api, ctx["engagement_id"])
    assert engagement["status"] == ENGAGEMENT_REMEDIATION_REQUIRED, (
        f"the engagement enters remediation, got {engagement['status']}"
    )
    assert engagement["transition_required"] is True, (
        f"transition_required is set, got {engagement['transition_required']}"
    )

    september = fx.read_cycle(api, ctx["september_cycle_id"])
    a.assert_cycle_state(
        september, CYCLE_ON_HOLD, hold_reason=HOLD_REASON_PROVIDER_PROBATION
    )

    august = fx.read_cycle(api, ctx["cycle_id"])
    a.assert_cycle_state(august, CYCLE_RESULTS_APPROVED)
