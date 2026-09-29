"""Derived values: calendar walks, thresholds, weights and tiered penalties.

Each test pins one arithmetic rule at the exact point where a naive
implementation diverges — the weekend inside a backwards working-day walk, the
holiday inside the same walk, calendar days against working days, the ordering
of two validation stages, a drift landing exactly on its ceiling, a baseline
that must be ignored because it was never approved, a score landing exactly on
the probation floor, the rounded escalation multiplier, and a penalty base
landing exactly on a tier ceiling.
"""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.constants import (
    CTRL_INPUT_INTEGRITY,
    CYCLE_DRAFT,
    CYCLE_INPUTS_LOCKED,
    CYCLE_ON_HOLD,
    ENGAGEMENT_ACTIVE,
    ENGAGEMENT_REMEDIATION_REQUIRED,
    FILING_LATE,
    FILING_PENDING,
    FILING_TYPE_INCOME_TAX_WITHHOLDING,
    GTN_CLEARED,
    HOLD_REASON_PROVIDER_PROBATION,
    INCIDENT_CONFIRMED,
    INCIDENT_ESCALATED,
    INPUT_FILE_REJECTED,
    INPUT_FILE_VALIDATED,
    PENALTY_ASSESSED,
    PENALTY_OWNER_PROVIDER,
    PROVIDER_ACTIVE,
    PROVIDER_PROBATION,
    REGION_EU,
    REJECTION_MISSING_ELEMENTS,
    REJECTION_RECORD_COUNT_DRIFT,
    SEV1,
    SEV2,
    SEV3,
    VARIANCE_BASIS_NO_PRIOR_BASELINE,
)
from test_helpers.factories import OMIT
from test_helpers.test_users import CONTROLLER_HEADERS, OPS_HEADERS

_AUGUST_CUTOFF = "2026-08-26T17:00:00.000Z"
_SEPTEMBER_CUTOFF = "2026-09-24T17:00:00.000Z"
_SEPTEMBER_DUE_AT = "2026-10-10T23:59:59.999Z"
_SEPTEMBER_OVERRIDES = {
    "period_label": "2026-09",
    "period_start_date": "2026-09-01",
    "period_end_date": "2026-10-01",
    "pay_date": "2026-09-30",
}
_SINGLE_FILING_COUNTRY = {"required_filing_types": [FILING_TYPE_INCOME_TAX_WITHHOLDING]}
_PENALTY_SWEEP_CLOCK = "2026-09-13T12:00:00Z"


def _extract_status(api, cycle_id, extract_id):
    """Re-read one extract of a cycle through the nested sub-resource list."""
    extracts, _ = validate_paginated(api.list_cycle_input_files(cycle_id, OPS_HEADERS))
    return a.find_by(extracts, "id", extract_id)


def test_cutoff_walks_back_over_the_weekend(api):
    """A Monday pay date with a three-working-day lead lands on the Wednesday
    before, because Saturday and Sunday are stepped over without being counted.

    PRD 3.3: "Begin at the cycle's `pay_date` and set a counter of counted working
    days to zero. Repeatedly step back one calendar day at a time; each time you land
    on a day whose ISO weekday is Monday through Friday **and** which is not one of
    the country's `local_holidays`, increase the counter by one."

    PRD 3.3: "The resolved instant always carries millisecond precision and its
    time-of-day component is always exactly 17:00:00.000Z."

    Design: Corner/calculations/cutoff_resolution_walks_back_three_working_days_over_the_weekend
    """
    ctx = fx.setup_active_engagement(api)

    response = api.create_cycle(f.cycle_payload(ctx["engagement_id"]), OPS_HEADERS)

    cycle = validate_success(response, 201)
    assert cycle["pay_date"] == "2026-08-31", (
        f"the period pays on the Monday, got {cycle['pay_date']!r}"
    )
    assert cycle["cutoff_lead_working_days"] == 3, (
        f"the lead is three working days, got {cycle['cutoff_lead_working_days']}"
    )
    a.assert_instant_equals(cycle["input_cutoff_at"], _AUGUST_CUTOFF, "input_cutoff_at")
    a.assert_instant_format(cycle["input_cutoff_at"], "input_cutoff_at")
    assert cycle["input_cutoff_at"].endswith("T17:00:00.000Z"), (
        f"the time of day is exactly 17:00:00.000Z, got {cycle['input_cutoff_at']!r}"
    )


def test_cutoff_skips_a_local_holiday_inside_the_walk(api):
    """The Friday inside the walk is a registered local holiday, so it is skipped
    uncounted and the cutoff is pushed one further working day into the past.

    PRD 3.3: "`local_holidays` is consulted on every candidate day, so a public
    holiday sitting inside the walk is skipped without being counted and pushes the
    cutoff one further working day into the past."

    Design: Corner/calculations/cutoff_resolution_skips_a_local_holiday_inside_the_walk
    """
    ctx = fx.setup_active_engagement(api)
    country = fx.read_country(api, ctx["country_id"])
    assert country["local_holidays"] == ["2026-09-25"], (
        f"the walk must cross the registered holiday, got {country['local_holidays']}"
    )

    response = api.create_cycle(
        f.september_cycle_payload(ctx["engagement_id"]), OPS_HEADERS
    )

    cycle = validate_success(response, 201)
    a.assert_instant_equals(
        cycle["input_cutoff_at"], _SEPTEMBER_CUTOFF, "input_cutoff_at"
    )
    a.assert_null_fields(cycle, ["prior_cycle_id"])
    a.assert_cycle_state(cycle, CYCLE_DRAFT)


def test_statutory_due_date_uses_calendar_days(api):
    """Ten calendar days after a Wednesday pay date is a Saturday, and the deadline
    stays there rather than rolling forward to a working day.

    PRD 3.4: "Each minted filing's `due_at` is resolved from calendar days, not
    working days: take the cycle's `pay_date`, add the country profile's
    `statutory_filing_deadline_days` as whole calendar days, and set the time of day
    to 23:59:59.999Z."

    PRD 3.4: "Statutory deadlines never roll forward off a weekend or a local
    holiday, so `local_holidays` plays no part here — it matters only for the input
    cutoff."

    Design: Corner/calculations/statutory_due_date_uses_calendar_days_not_working_days
    """
    ctx = fx.setup_active_engagement(api, country_overrides=_SINGLE_FILING_COUNTRY)
    ctx = fx.setup_draft_cycle(api, ctx, cycle_overrides=dict(_SEPTEMBER_OVERRIDES))
    ctx = fx.setup_validated_extract(api, ctx)
    ctx = fx.setup_locked_cycle(api, ctx)

    a.assert_cycle_state(ctx["cycle"], CYCLE_INPUTS_LOCKED)
    filings = fx.filings_of_cycle(api, ctx["cycle_id"])
    assert len(filings) == 1, f"the country mints one obligation, got {len(filings)}"
    filing = filings[0]
    a.assert_instant_equals(filing["due_at"], _SEPTEMBER_DUE_AT, "due_at")
    assert filing["status"] == FILING_PENDING, (
        f"a freshly minted obligation is PENDING, got {filing['status']}"
    )
    assert filing["late_days"] == 0, (
        f"nothing is late before the deadline, got {filing['late_days']}"
    )

    country = fx.read_country(api, ctx["country_id"])
    assert country["open_filing_obligation_count"] == 1, (
        "one live obligation was minted, got "
        f"{country['open_filing_obligation_count']}"
    )


def test_missing_element_is_reported_before_the_drift_check(api):
    """The extract fails both stages, and the first-stage element failure is the one
    reported, because the drift check never runs after it.

    PRD 3.4: "The outcome is computed in two strictly ordered stages, and the second
    stage never runs if the first one fails."

    PRD 3.4: "If any required key is absent from `country_elements`, or is present
    but maps to an empty string, validation fails immediately: the extract moves
    `RECEIVED → REJECTED` with `rejection_code` set to `MISSING_ELEMENTS`,
    `validated_record_count` stays at 0, and no audit evidence is minted."

    Design: Corner/calculations/input_validation_rejects_a_missing_element_before_the_drift_check
    """
    ctx = fx.setup_results_approved_cycle(api, country_overrides=_SINGLE_FILING_COUNTRY)
    second = fx.create_cycle(
        api,
        ctx["engagement_id"],
        prior_cycle_id=ctx["cycle_id"],
        **_SEPTEMBER_OVERRIDES,
    )
    extract = fx.submit_extract(
        api,
        second["id"],
        record_count=400,
        country_elements=f.elements_for_region(REGION_EU, iban=OMIT),
    )

    validated = fx.validate_extract(api, extract["id"])

    assert validated["status"] == INPUT_FILE_REJECTED, (
        f"a missing element rejects the extract, got {validated['status']}"
    )
    assert validated["rejection_code"] == REJECTION_MISSING_ELEMENTS, (
        "the first stage names the failure, got "
        f"{validated['rejection_code']}"
    )
    assert validated["validated_record_count"] == 0, (
        f"nothing is frozen on a rejection, got {validated['validated_record_count']}"
    )

    evidence = fx.evidence_of_cycle(
        api, second["id"], control_ref=CTRL_INPUT_INTEGRITY
    )
    assert evidence == [], f"a failed validation mints no evidence, got {evidence}"


def test_drift_exactly_at_the_ceiling_passes_and_one_record_above_it_fails(api):
    """Against a 200-employee baseline, 240 records is a drift of exactly 20.00 and
    passes, while 241 records is 20.50 and fails.

    PRD 3.4: "Otherwise, take the absolute difference between the extract's
    `record_count` and the baseline run's `employee_count`, divide by the baseline
    `employee_count`, multiply by 100, and round the result half up to two decimal
    places."

    PRD 3.4: "If that rounded drift percentage is strictly greater than 20.00,
    validation fails: the extract moves `RECEIVED → REJECTED` with `rejection_code`
    set to `RECORD_COUNT_DRIFT`. Drift landing exactly on 20.00 is not greater than
    20.00 and therefore passes."

    Design: Corner/calculations/record_drift_at_exactly_the_max_threshold_passes_and_just_above_it_fails
    """
    ctx = fx.setup_results_approved_cycle(api, country_overrides=_SINGLE_FILING_COUNTRY)
    assert ctx["run"]["employee_count"] == 200, (
        f"the baseline pays 200 employees, got {ctx['run']['employee_count']}"
    )
    second = fx.create_cycle(
        api,
        ctx["engagement_id"],
        prior_cycle_id=ctx["cycle_id"],
        **_SEPTEMBER_OVERRIDES,
    )

    on_threshold = fx.submit_extract(api, second["id"], record_count=240)
    on_threshold = fx.validate_extract(api, on_threshold["id"])
    above_threshold = fx.submit_extract(api, second["id"], record_count=241)
    above_threshold = fx.validate_extract(api, above_threshold["id"])

    assert on_threshold["status"] == INPUT_FILE_VALIDATED, (
        f"a drift of exactly 20.00 passes, got {on_threshold['status']}"
    )
    assert on_threshold["validated_record_count"] == 240, (
        "the record count is frozen on validation, got "
        f"{on_threshold['validated_record_count']}"
    )
    a.assert_null_fields(on_threshold, ["rejection_code"])

    assert above_threshold["status"] == INPUT_FILE_REJECTED, (
        f"a drift of 20.50 fails, got {above_threshold['status']}"
    )
    assert above_threshold["rejection_code"] == REJECTION_RECORD_COUNT_DRIFT, (
        f"the drift stage names the failure, got {above_threshold['rejection_code']}"
    )
    assert above_threshold["validated_record_count"] == 0, (
        "a rejected extract freezes nothing, got "
        f"{above_threshold['validated_record_count']}"
    )

    survivor = _extract_status(api, second["id"], on_threshold["id"])
    assert survivor["status"] == INPUT_FILE_VALIDATED, (
        f"a failed validation supersedes nothing, got {survivor['status']}"
    )
    a.assert_cycle_state(fx.read_cycle(api, second["id"]), CYCLE_DRAFT)


def test_variance_ignores_a_prior_run_that_was_never_approved(api):
    """The prior period has a run, but it only cleared and was never approved, so the
    second period is judged as having no baseline at all.

    PRD 3.5: "The baseline is the gross-to-net run with status `APPROVED` whose cycle
    is the one named by this cycle's `prior_cycle_id`."

    PRD 3.5: "If the cycle has no `prior_cycle_id`, or that prior cycle has no
    approved run, there is nothing to compare against: `variance_basis` is set to
    `NO_PRIOR_BASELINE`, `variance_pct` and `headcount_drift_pct` are both null, and
    `variance_material` is false."

    Design: Corner/calculations/variance_baseline_ignores_a_prior_run_that_is_not_approved
    """
    ctx = fx.setup_scored_run(api, country_overrides=_SINGLE_FILING_COUNTRY)
    unapproved_run_id = ctx["run_id"]
    second = fx.create_cycle(
        api,
        ctx["engagement_id"],
        prior_cycle_id=ctx["cycle_id"],
        **_SEPTEMBER_OVERRIDES,
    )
    extract = fx.validate_extract(api, fx.submit_extract(api, second["id"])["id"])
    locked = fx.lock_inputs(api, second["id"])

    run = fx.submit_run(
        api, second["id"], extract["id"], ctx["provider_id"], locked["version"]
    )

    a.assert_variance_analysis(
        run,
        variance_basis=VARIANCE_BASIS_NO_PRIOR_BASELINE,
        variance_pct=None,
        headcount_drift_pct=None,
        variance_material=False,
    )
    assert run["status"] == GTN_CLEARED, (
        f"an immaterial run clears, got {run['status']}"
    )

    prior = fx.read_run(api, unapproved_run_id)
    assert prior["status"] == GTN_CLEARED, (
        f"the prior run is still merely cleared, got {prior['status']}"
    )

    incidents, meta = validate_paginated(
        api.list_incidents(CONTROLLER_HEADERS, {"engagement_id": ctx["engagement_id"]})
    )
    a.assert_pagination_meta(meta, expected_total=0, expected_has_more=False)
    assert incidents == [], f"a cleared run raises no incident, got {incidents}"


def test_score_landing_exactly_on_the_probation_floor_stays_active(api):
    """Confirmed SEV1, SEV2 and SEV3 findings deduct 45.00 in total, which lands the
    score on 55.00 — the floor itself, which is still ACTIVE.

    PRD 3.8: "`weight_points` is set from the severity band, 25.00 for `SEV1`, 15.00
    for `SEV2` and 5.00 for `SEV3`."

    PRD 3.8: "A score at least 40.00 but below 55.00 makes it `PROBATION`. A score of
    at least 55.00 makes it `ACTIVE` if and only if its `open_penalty_minor` is at most
    100000"

    Design: Corner/calculations/service_score_at_exactly_the_probation_floor_stays_active
    """
    ctx = fx.setup_draft_cycle(api)
    fx.confirmed_incident(api, ctx["engagement_id"], SEV1)
    fx.confirmed_incident(api, ctx["engagement_id"], SEV2)
    third = fx.raise_incident(api, ctx["engagement_id"], SEV3)

    confirmed = fx.confirm_incident(api, third["id"])

    assert confirmed["status"] == INCIDENT_CONFIRMED, (
        f"confirming makes the report a finding, got {confirmed['status']}"
    )
    a.assert_pct(confirmed["weight_points"], 5.00, "weight_points")

    provider = fx.read_provider(api, ctx["provider_id"])
    a.assert_provider_standing(
        provider,
        status=PROVIDER_ACTIVE,
        service_score=55.00,
        open_penalty_minor=0,
    )

    engagement = fx.read_engagement(api, ctx["engagement_id"])
    assert engagement["status"] == ENGAGEMENT_ACTIVE, (
        f"the floor triggers no remediation, got {engagement['status']}"
    )
    assert engagement["transition_required"] is False, (
        f"transition_required stays false, got {engagement['transition_required']}"
    )
    a.assert_cycle_state(fx.read_cycle(api, ctx["cycle_id"]), CYCLE_DRAFT)


def test_escalated_incident_weight_uses_the_rounded_multiplier(api):
    """Escalating the confirmed SEV2 multiplies its 15.00 by 1.5 to 22.50, which takes
    the score to 52.50 and tips the provider onto probation.

    PRD 3.8: "**Escalating** a confirmed incident moves it `CONFIRMED → ESCALATED`,
    sets `escalation_level` to 1, and multiplies the severity's base points by 1.5,
    rounding half up to two decimal places — so an escalated `SEV1` weighs 37.50, an
    escalated `SEV2` weighs 22.50 and an escalated `SEV3` weighs 7.50."

    PRD 3.8: "every cycle of those engagements sitting in `DRAFT` moves `DRAFT →
    ON_HOLD` with `hold_reason` set to `PROVIDER_PROBATION` when the provider is on
    probation"

    Design: Corner/calculations/escalated_incident_weight_uses_the_rounded_escalation_multiplier
    """
    ctx = fx.setup_draft_cycle(api)
    severe = fx.confirmed_incident(api, ctx["engagement_id"], SEV1)
    moderate = fx.confirmed_incident(api, ctx["engagement_id"], SEV2)

    escalated = fx.escalate_incident(api, moderate["id"])

    assert escalated["status"] == INCIDENT_ESCALATED, (
        f"the finding is escalated, got {escalated['status']}"
    )
    assert escalated["escalation_level"] == 1, (
        f"escalation_level is set to 1, got {escalated['escalation_level']}"
    )
    a.assert_pct(escalated["weight_points"], 22.50, "weight_points")
    a.assert_pct(
        fx.read_incident(api, severe["id"])["weight_points"], 25.00, "weight_points"
    )

    provider = fx.read_provider(api, ctx["provider_id"])
    a.assert_provider_standing(
        provider, status=PROVIDER_PROBATION, service_score=52.50, open_penalty_minor=0
    )

    engagement = fx.read_engagement(api, ctx["engagement_id"])
    assert engagement["status"] == ENGAGEMENT_REMEDIATION_REQUIRED, (
        f"probation cascades into remediation, got {engagement['status']}"
    )
    assert engagement["transition_required"] is True, (
        f"transition_required is raised, got {engagement['transition_required']}"
    )
    a.assert_cycle_state(
        fx.read_cycle(api, ctx["cycle_id"]),
        CYCLE_ON_HOLD,
        HOLD_REASON_PROVIDER_PROBATION,
    )


def test_penalty_base_exactly_on_the_second_ceiling_takes_the_middle_rate(api):
    """Three late days at a 25000 daily rate put the base on exactly 100000, which is
    "at most 100000" and therefore attracts the 10.00 percent rate, not 20.00.

    PRD 3.7: "**Base accrual** second: `base_penalty_minor` is a statutory base of
    25000 local minor units plus `late_days` multiplied by the country profile's
    `penalty_daily_rate_minor`."

    PRD 3.7: "if `base_penalty_minor` is at most 50000 the surcharge rate is 0.00
    percent; otherwise if it is at most 100000 the rate is 10.00 percent; otherwise the
    rate is 20.00 percent."

    Design: Corner/calculations/penalty_tier_boundary_at_exactly_the_second_ceiling_uses_the_middle_rate
    """
    ctx = fx.setup_results_approved_cycle(
        api,
        country_overrides={**_SINGLE_FILING_COUNTRY, "penalty_daily_rate_minor": 25000},
    )
    fx.set_clock(api, _PENALTY_SWEEP_CLOCK)

    fx.sweep_filings(api, ctx["cycle_id"])

    filings = fx.filings_of_cycle(api, ctx["cycle_id"])
    assert len(filings) == 1, f"the cycle carries one obligation, got {len(filings)}"
    filing = filings[0]
    assert filing["status"] == FILING_LATE, (
        f"the missed obligation is swept to LATE, got {filing['status']}"
    )
    assert filing["penalty_status"] == PENALTY_ASSESSED, (
        f"the penalty is assessed, got {filing['penalty_status']}"
    )
    a.assert_penalty_assessment(
        filing,
        late_days=3,
        base_penalty_minor=100000,
        surcharge_minor=10000,
        total_penalty_minor=110000,
        provider_share_minor=110000,
        client_share_minor=0,
        penalty_owner=PENALTY_OWNER_PROVIDER,
    )

    provider = fx.read_provider(api, ctx["provider_id"])
    a.assert_minor_amount(
        provider["open_penalty_minor"], 110000, "open_penalty_minor"
    )

    country = fx.read_country(api, ctx["country_id"])
    assert country["open_filing_obligation_count"] == 1, (
        "PENDING to LATE is obligation-count-neutral, got "
        f"{country['open_filing_obligation_count']}"
    )
