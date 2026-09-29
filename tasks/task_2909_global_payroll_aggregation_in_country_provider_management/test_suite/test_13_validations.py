"""Guards that turn a rule violation into its declared error — and the boundary
cases where the same rule must let the request through.

Uniqueness, subset, tolerance, cross-entity state, a strict temporal comparison,
an aggregate cap, a conditional actor rule, and a check that only runs once an
earlier one has passed.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_DUPLICATE_COUNTRY_CODE,
    ERR_DUPLICATE_PERIOD_LABEL,
    ERR_ENGAGEMENT_NOT_ACTIVE,
    ERR_FILING_RESPONSIBILITY_MISMATCH,
    ERR_FUNDING_CAP_EXCEEDED,
    ERR_INPUT_CUTOFF_PASSED,
    ERR_SERVICE_SCOPE_NOT_COVERED,
    ERR_VARIANCE_JUSTIFICATION_REQUIRED,
)
from test_helpers.constants import (
    CTRL_FUNDING_DUAL_AUTH,
    CYCLE_DRAFT,
    CYCLE_INPUTS_LOCKED,
    CYCLE_RESULTS_APPROVED,
    ENGAGEMENT_REJECTED,
    FILING_FILED,
    FILING_PENDING,
    FILING_RESPONSIBILITY_CLIENT,
    FILING_TYPE_INCOME_TAX_WITHHOLDING,
    FILING_TYPE_SOCIAL_INSURANCE,
    FUNDING_APPROVED,
    GTN_APPROVED,
    GTN_CLEARED,
    GTN_ESCALATED,
    INPUT_FILE_VALIDATED,
    SERVICE_GROSS_TO_NET,
    SERVICE_PAYMENT_DISBURSEMENT,
    SERVICE_STATUTORY_FILING,
    VARIANCE_BASIS_ABSOLUTE_TOTAL,
    VARIANCE_BASIS_NO_PRIOR_BASELINE,
)
from test_helpers.test_users import (
    AUDITOR_HEADERS,
    CONTROLLER_HEADERS,
    OPS_HEADERS,
    PLATFORM_ADMIN_HEADERS,
    TREASURY_RELEASER_HEADERS,
)

_SINGLE_FILING_COUNTRY = {"required_filing_types": [FILING_TYPE_INCOME_TAX_WITHHOLDING]}
_SEPTEMBER_OVERRIDES = {
    "period_label": "2026-09",
    "period_start_date": "2026-09-01",
    "period_end_date": "2026-10-01",
    "pay_date": "2026-09-30",
}
_AUGUST_CUTOFF = "2026-08-26T17:00:00.000Z"
_ONE_MS_PAST_CUTOFF = "2026-08-26T17:00:00.001Z"
_BEFORE_DUE_CLOCK = "2026-09-05T10:00:00Z"
_JUSTIFICATION = "structural headcount increase after the plant acquisition"


def test_second_profile_for_the_same_country_code_is_rejected(api):
    """Every other term differs, but the code is taken, so the registration is
    refused and the stored profile keeps its own values.

    PRD 3.1: "A country registration carries the `country_code`, which is exactly two
    uppercase letters following ISO 3166-1 alpha-2 and must be unique across all
    registered countries — reusing a code that already exists is rejected with
    `ERR_DUPLICATE_COUNTRY_CODE` (HTTP 409)."

    Design: Corner/validations/duplicate_country_code_is_rejected
    """
    first = fx.create_country(api, **_SINGLE_FILING_COUNTRY)

    response = api.create_country_profile(
        f.country_profile_payload(
            statutory_filing_deadline_days=20,
            materiality_pct=9.0,
            materiality_floor_minor=500000,
            penalty_daily_rate_minor=30000,
            required_filing_types=[FILING_TYPE_SOCIAL_INSURANCE],
        ),
        PLATFORM_ADMIN_HEADERS,
    )
    validate_error(response, ERR_DUPLICATE_COUNTRY_CODE, 409)

    stored = fx.read_country(api, first["id"])
    assert stored["statutory_filing_deadline_days"] == 10, (
        "the registered deadline is untouched, got "
        f"{stored['statutory_filing_deadline_days']}"
    )
    a.assert_pct(stored["materiality_pct"], 5.00, "materiality_pct")
    a.assert_common_fields(stored, expected_version=1)


def test_engagement_claiming_a_service_outside_the_provider_scope_is_rejected(api):
    """The engagement asks for a service the provider does not sell, which fails the
    subset check and persists nothing.

    PRD 3.2: "every member of the engagement's `service_scope` must also be a member
    of the provider's `service_scope`, otherwise `ERR_SERVICE_SCOPE_NOT_COVERED`
    (HTTP 422)."

    Design: Corner/validations/engagement_claiming_a_service_the_provider_does_not_sell_is_rejected
    """
    country = fx.create_country(api, **_SINGLE_FILING_COUNTRY)
    provider = fx.create_provider(
        api, service_scope=[SERVICE_GROSS_TO_NET, SERVICE_STATUTORY_FILING]
    )

    response = api.create_engagement(
        f.engagement_payload(
            country["id"],
            provider["id"],
            service_scope=[SERVICE_GROSS_TO_NET, SERVICE_PAYMENT_DISBURSEMENT],
            filing_responsibility=FILING_RESPONSIBILITY_CLIENT,
        ),
        PLATFORM_ADMIN_HEADERS,
    )
    validate_error(response, ERR_SERVICE_SCOPE_NOT_COVERED, 422)

    engagements, meta = validate_paginated(api.list_engagements(OPS_HEADERS))
    a.assert_pagination_meta(meta, expected_total=0, expected_has_more=False)
    assert engagements == [], f"no engagement was formed, got {engagements}"


def test_run_at_exactly_ten_percent_gross_deviation_is_accepted(api):
    """A gross of 11 000 000 against a declared 10 000 000 is exactly one tenth away,
    which does not exceed the tolerance, so the run is accepted.

    PRD 3.5: "Then the fiscal tolerance check: the absolute difference between the
    run's `gross_minor` and the backing extract's `gross_declared_minor` must not
    exceed one tenth of that declared gross, and a wider gap is rejected with
    `ERR_GROSS_TOTAL_OUT_OF_TOLERANCE` (HTTP 422)."

    Design: Corner/validations/gtn_run_at_exactly_ten_percent_gross_deviation_is_accepted
    """
    ctx = fx.setup_locked_cycle(api, country_overrides=_SINGLE_FILING_COUNTRY)
    assert ctx["input_file"]["gross_declared_minor"] == 10000000, (
        "the extract declares ten million, got "
        f"{ctx['input_file']['gross_declared_minor']}"
    )

    response = api.create_gtn_run(
        f.gtn_run_payload(
            ctx["cycle_id"],
            ctx["input_file_id"],
            ctx["cycle_version"],
            gross_minor=11000000,
            net_minor=7000000,
            employer_cost_minor=2200000,
            provider_fee_minor=165000,
        ),
        ctx["provider_headers"],
    )

    run = validate_success(response, 201)
    assert run["status"] == GTN_CLEARED, (
        f"without a baseline the run clears, got {run['status']}"
    )
    assert run["variance_basis"] == VARIANCE_BASIS_NO_PRIOR_BASELINE, (
        f"there is no prior period to compare, got {run['variance_basis']}"
    )
    a.assert_minor_amount(run["gross_minor"], 11000000, "gross_minor")

    cycle = fx.read_cycle(api, ctx["cycle_id"])
    a.assert_cycle_state(cycle, CYCLE_INPUTS_LOCKED)
    a.assert_minor_amount(cycle["gross_total_minor"], 0, "gross_total_minor")


def test_cycle_creation_on_a_rejected_engagement_is_refused(api):
    """The engagement exists but its residency decision was a rejection, so it is not
    a live state and no period may open on it.

    PRD 3.3: "The engagement must be in a live state — one of `ACTIVE`,
    `REMEDIATION_REQUIRED`, `TRANSITION_PLANNED` or `TRANSITION_IN_PROGRESS` — and
    anything else, including a `DRAFT` or `REJECTED` engagement, yields
    `ERR_ENGAGEMENT_NOT_ACTIVE` (HTTP 409)."

    Design: Corner/validations/cycle_creation_on_a_rejected_engagement_is_rejected
    """
    country = fx.create_country(api, **_SINGLE_FILING_COUNTRY)
    provider = fx.create_provider(api)
    engagement = fx.create_engagement(api, country["id"], provider["id"])
    rejected = validate_success(
        api.residency_decision(
            engagement["id"], f.residency_reject_payload(), AUDITOR_HEADERS
        )
    )
    assert rejected["status"] == ENGAGEMENT_REJECTED, (
        f"a REJECT decision rests in REJECTED, got {rejected['status']}"
    )
    a.assert_null_fields(rejected, ["activated_at"])

    response = api.create_cycle(f.cycle_payload(engagement["id"]), OPS_HEADERS)
    validate_error(response, ERR_ENGAGEMENT_NOT_ACTIVE, 409)

    cycles, meta = validate_paginated(api.list_cycles(OPS_HEADERS))
    a.assert_pagination_meta(meta, expected_total=0, expected_has_more=False)
    assert cycles == [], f"no period was opened, got {cycles}"


def test_extract_submitted_one_millisecond_past_the_cutoff_is_refused(api):
    """Submission at exactly the cutoff would be accepted; one millisecond later the
    door is shut and the cycle records no extract and no submitter.

    PRD 3.4: "The current logical clock must not be strictly after the cycle's
    resolved `input_cutoff_at`; submitting at exactly the cutoff instant is accepted,
    and submitting even one millisecond later is rejected with
    `ERR_INPUT_CUTOFF_PASSED` (HTTP 409)."

    Design: Corner/validations/extract_submitted_after_the_cutoff_instant_is_rejected
    """
    ctx = fx.setup_draft_cycle(api, country_overrides=_SINGLE_FILING_COUNTRY)
    a.assert_instant_equals(
        ctx["cycle"]["input_cutoff_at"], _AUGUST_CUTOFF, "input_cutoff_at"
    )
    fx.set_clock(api, _ONE_MS_PAST_CUTOFF)

    response = api.create_input_file(f.input_file_payload(ctx["cycle_id"]), OPS_HEADERS)
    validate_error(response, ERR_INPUT_CUTOFF_PASSED, 409)

    extracts, meta = validate_paginated(
        api.list_cycle_input_files(ctx["cycle_id"], OPS_HEADERS)
    )
    a.assert_pagination_meta(meta, expected_total=0, expected_has_more=False)
    assert extracts == [], f"nothing was stored, got {extracts}"

    cycle = fx.read_cycle(api, ctx["cycle_id"])
    a.assert_cycle_state(cycle, CYCLE_DRAFT)
    a.assert_null_fields(cycle, ["input_submitter_user_id"])


def test_single_release_above_the_accounts_daily_cap_is_refused(api):
    """No instruction has ever been released on this account, but the cap is evaluated
    on the aggregate *including* this instruction, so the release is refused.

    PRD 3.6: "Finally the fiscal cap: sum the `requested_local_minor` of every
    already-`RELEASED` instruction on the same `bank_account_id` bearing the same
    `value_date`, add this instruction's own `requested_local_minor`, and if that total
    exceeds the account's `daily_cap_minor`, the release is rejected with
    `ERR_FUNDING_CAP_EXCEEDED` (HTTP 409)."

    Design: Corner/validations/single_release_above_the_accounts_daily_cap_is_rejected
    """
    ctx = fx.setup_approved_funding(
        api,
        account_overrides={"daily_cap_minor": 1000000},
        country_overrides=_SINGLE_FILING_COUNTRY,
    )

    response = api.release_funding_instruction(
        ctx["funding_id"], TREASURY_RELEASER_HEADERS
    )
    validate_error(response, ERR_FUNDING_CAP_EXCEEDED, 409)

    funding = fx.read_funding(api, ctx["funding_id"])
    assert funding["status"] == FUNDING_APPROVED, (
        f"the refused instruction stays approved, got {funding['status']}"
    )
    a.assert_null_fields(funding, ["releaser_user_id"])
    a.assert_minor_amount(
        funding["requested_local_minor"], 8650000, "requested_local_minor"
    )
    a.assert_minor_amount(funding["funded_source_minor"], 9543206, "funded_source_minor")

    cycle = fx.read_cycle(api, ctx["cycle_id"])
    a.assert_cycle_state(cycle, CYCLE_RESULTS_APPROVED)
    a.assert_minor_amount(cycle["funded_total_minor"], 0, "funded_total_minor")

    engagement = fx.read_engagement(api, ctx["engagement_id"])
    a.assert_minor_amount(
        engagement["treasury_committed_minor"], 0, "treasury_committed_minor"
    )

    evidence = fx.evidence_of_cycle(
        api, ctx["cycle_id"], control_ref=CTRL_FUNDING_DUAL_AUTH
    )
    assert evidence == [], f"no dual-authorization control was exercised, got {evidence}"


def test_provider_user_may_not_lodge_a_client_responsibility_filing(api):
    """`ProviderUser` is a declared role of the lodgement endpoint, but this obligation
    belongs to the client, so the provider is refused and operations lodges it instead.

    PRD 3.7: "The actor rule is checked before any state rule: when `responsibility`
    is `PROVIDER`, the actor must be the `ProviderUser` of the engaged provider, and
    when `responsibility` is `CLIENT`, the actor must not be a `ProviderUser` — it is
    `GlobalPayrollOps` that lodges client obligations. A mismatch in either direction
    is rejected with `ERR_FILING_RESPONSIBILITY_MISMATCH` (HTTP 403)."

    Design: Corner/validations/provider_user_cannot_lodge_a_client_responsibility_filing
    """
    ctx = fx.setup_results_approved_cycle(
        api,
        country_overrides=_SINGLE_FILING_COUNTRY,
        engagement_overrides={"filing_responsibility": FILING_RESPONSIBILITY_CLIENT},
    )
    fx.set_clock(api, _BEFORE_DUE_CLOCK)
    filings = fx.filings_of_cycle(api, ctx["cycle_id"])
    assert len(filings) == 1, f"the country mints one obligation, got {len(filings)}"
    filing_id = filings[0]["id"]
    assert filings[0]["responsibility"] == FILING_RESPONSIBILITY_CLIENT, (
        f"the obligation belongs to the client, got {filings[0]['responsibility']}"
    )

    response = api.file_filing(
        filing_id,
        f.file_filing_payload(submission_ref="DE-SUB-PROV"),
        ctx["provider_headers"],
    )
    validate_error(response, ERR_FILING_RESPONSIBILITY_MISMATCH, 403)

    untouched = fx.read_filing(api, filing_id)
    assert untouched["status"] == FILING_PENDING, (
        f"the obligation is still pending, got {untouched['status']}"
    )
    a.assert_null_fields(untouched, ["filed_at"])
    country = fx.read_country(api, ctx["country_id"])
    assert country["open_filing_obligation_count"] == 1, (
        "the obligation is still live, got "
        f"{country['open_filing_obligation_count']}"
    )

    lodged = validate_success(
        api.file_filing(
            filing_id,
            f.file_filing_payload(submission_ref="DE-SUB-CLIENT"),
            OPS_HEADERS,
        )
    )
    assert lodged["status"] == FILING_FILED, (
        f"operations lodges the client obligation, got {lodged['status']}"
    )
    assert lodged["submission_ref"] == "DE-SUB-CLIENT", (
        f"the authority reference is persisted, got {lodged['submission_ref']!r}"
    )


def test_escalated_run_approved_without_a_justification_is_refused(api):
    """The run passed the state check and is escalated, so the justification check
    fires; supplying the justification on a retry approves the very same run.

    PRD 3.5: "Third, approving a run whose status is `ESCALATED` requires a
    `variance_justification` of at least 10 characters; approving an escalated run
    without one, or with a shorter one, is rejected with
    `ERR_VARIANCE_JUSTIFICATION_REQUIRED` (HTTP 422)."

    Design: Corner/validations/escalated_run_approved_without_a_justification_is_rejected
    """
    ctx = fx.setup_results_approved_cycle(api, country_overrides=_SINGLE_FILING_COUNTRY)
    second = fx.create_cycle(
        api,
        ctx["engagement_id"],
        prior_cycle_id=ctx["cycle_id"],
        **_SEPTEMBER_OVERRIDES,
    )
    extract = fx.submit_extract(
        api, second["id"], record_count=230, gross_declared_minor=10500000
    )
    extract = fx.validate_extract(api, extract["id"])
    assert extract["status"] == INPUT_FILE_VALIDATED, (
        f"a drift of 15.00 is within the ceiling, got {extract['status']}"
    )
    locked = fx.lock_inputs(api, second["id"])
    run = fx.submit_run(
        api,
        second["id"],
        extract["id"],
        ctx["provider_id"],
        locked["version"],
        gross_minor=10500000,
        net_minor=6800000,
        employer_cost_minor=2100000,
        provider_fee_minor=157500,
        employee_count=230,
    )
    assert run["status"] == GTN_ESCALATED, (
        f"a material variance escalates the run, got {run['status']}"
    )
    a.assert_variance_analysis(
        run,
        variance_basis=VARIANCE_BASIS_ABSOLUTE_TOTAL,
        variance_pct=5.00,
        headcount_drift_pct=15.00,
        variance_material=True,
    )

    response = api.review_gtn_run(
        run["id"], f.review_approve_payload(), CONTROLLER_HEADERS
    )
    validate_error(response, ERR_VARIANCE_JUSTIFICATION_REQUIRED, 422)

    unreviewed = fx.read_run(api, run["id"])
    assert unreviewed["status"] == GTN_ESCALATED, (
        f"the run is still escalated, got {unreviewed['status']}"
    )
    a.assert_null_fields(unreviewed, ["variance_justification"])
    cycle = fx.read_cycle(api, second["id"])
    a.assert_cycle_state(cycle, CYCLE_INPUTS_LOCKED)
    a.assert_minor_amount(cycle["gross_total_minor"], 0, "gross_total_minor")

    approved = validate_success(
        api.review_gtn_run(
            run["id"], f.review_approve_payload(_JUSTIFICATION), CONTROLLER_HEADERS
        )
    )
    assert approved["status"] == GTN_APPROVED, (
        f"the justified approval carries, got {approved['status']}"
    )
    assert approved["variance_justification"] == _JUSTIFICATION, (
        f"the justification is persisted, got {approved['variance_justification']!r}"
    )


def test_duplicate_period_label_on_a_non_overlapping_period_is_refused(api):
    """The second period does not overlap the first, so the overlap check passes and
    the label-uniqueness check is the one that reports.

    PRD 3.3: "Finally two constraint checks: the period's length must match the
    engagement's contracted `pay_frequency`, and the `period_label` must be unique
    within the engagement, otherwise `ERR_DUPLICATE_PERIOD_LABEL` (HTTP 409)."

    Design: Corner/validations/duplicate_period_label_on_a_non_overlapping_period_is_rejected
    """
    ctx = fx.setup_draft_cycle(api, country_overrides=_SINGLE_FILING_COUNTRY)

    response = api.create_cycle(
        f.cycle_payload(
            ctx["engagement_id"],
            period_start_date="2026-09-01",
            period_end_date="2026-10-01",
            pay_date="2026-09-30",
        ),
        OPS_HEADERS,
    )
    validate_error(response, ERR_DUPLICATE_PERIOD_LABEL, 409)

    cycles, meta = validate_paginated(
        api.list_cycles(OPS_HEADERS, {"engagement_id": ctx["engagement_id"]})
    )
    a.assert_pagination_meta(meta, expected_total=1, expected_has_more=False)
    assert cycles[0]["period_label"] == "2026-08", (
        f"only the original period exists, got {cycles[0]['period_label']!r}"
    )
