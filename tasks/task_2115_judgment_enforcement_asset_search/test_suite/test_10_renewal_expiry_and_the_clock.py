"""Renewal, capitalization, expiry and the docket sweep."""

from test_helpers import (
    ApiErrorId,
    advance_clock,
    assert_logical_instant_equals,
    assert_sweep_summary_shape,
    make_case_manager_headers,
    make_compliance_officer_headers,
    make_enforcement_officer_headers,
    read_action,
    read_filing,
    read_judgment,
    record_county_filing,
    setup_judgment,
    setup_drafted_wage_garnishment,
    validate_error,
    validate_paginated,
    validate_success,
)

CM = make_case_manager_headers()
CO = make_compliance_officer_headers("co-1")
EO = make_enforcement_officer_headers("eo-1")


# ==========================================================================
# The renewal window opens exactly 180 days before expiry
# ==========================================================================
def test_renewing_one_day_before_the_window_opens_is_refused(api):
    """PRD §3.9: "It is permitted only inside a window that opens 180 days before
    `expires_on` and closes the day `expires_on` itself arrives: the current clock
    date must be on or after the date 180 days before `expires_on` — the lower
    bound is inclusive, so exactly 180 days before expiry is the first legal day —
    and strictly before `expires_on`."
    PRD §3.9: "An attempt made earlier than that window is
    `ERR_RENEWAL_WINDOW_NOT_OPEN`."

    Design: Difficulty/boundary_precision_check/renewal_window_opens_exactly_one_hundred_eighty_days_before_expiry
    """
    ctx = setup_judgment(court_case_number="CV-2026-0605")
    assert ctx["judgment"]["expires_on"] == "2036-01-01"

    advance_clock("2035-07-04T00:00:00Z", CO)

    validate_error(
        api.renew_judgment(ctx["judgment"]["id"], CO),
        ApiErrorId.ERR_RENEWAL_WINDOW_NOT_OPEN.value,
        422,
    )
    assert read_judgment(ctx["judgment"]["id"])["renewal_count"] == 0


def test_renewing_on_the_first_legal_day_capitalizes_the_interest(api):
    """PRD §3.9: "Renewal begins by replaying the balances to the renewal date,
    which is the current clock date, so that `accrued_interest_cents` is current.
    It then **capitalizes**: the entire `accrued_interest_cents` figure is added to
    `principal_balance_cents` and `accrued_interest_cents` is set to zero."
    PRD §3.9: "A renewal fee of 5,000 cents is added to `costs_balance_cents`."
    PRD §3.9: "`expires_on` is pushed out a further ten calendar years,
    `renewal_count` is incremented by one, `accrued_through_on` is set to the
    renewal date, and the judgment's `version` is incremented by one."

    Design: Difficulty/boundary_precision_check/renewal_window_opens_exactly_one_hundred_eighty_days_before_expiry
    """
    ctx = setup_judgment(court_case_number="CV-2026-0608")

    advance_clock("2035-07-05T00:00:00Z", CO)
    renewed = validate_success(api.renew_judgment(ctx["judgment"]["id"], CO))

    assert renewed["principal_balance_cents"] == 9_756_164
    assert renewed["accrued_interest_cents"] == 0
    assert renewed["costs_balance_cents"] == 50_000
    assert renewed["total_payoff_cents"] == 9_806_164
    assert renewed["expires_on"] == "2046-01-01"
    assert renewed["renewal_count"] == 1
    assert read_judgment(ctx["judgment"]["id"])["accrued_through_on"] == "2035-07-05"


# ==========================================================================
# Screening order: an expired judgment beats the garnishment floor
# ==========================================================================
def test_the_sweep_expires_a_judgment_on_its_expiry_date(api):
    """PRD §2.5: "**Step 1 — expiry.** Every `ACTIVE` judgment whose `expires_on`
    is on or before the new clock date becomes `EXPIRED`, cascading as described
    in Section 3.9."
    PRD §3.9: "When renewal does not happen in time, the sweep's first step ends
    the judgment. Every `ACTIVE` judgment whose `expires_on` is on or before the
    new clock date moves `ACTIVE → EXPIRED`."

    Design: Difficulty/priority_pair_validation_conflict/expired_judgment_beats_garnishment_floor
    """
    ctx = setup_drafted_wage_garnishment(
        21_750,
        debtor_overrides={"head_of_household": False},
        filing_overrides={"fee_cents": 0},
        court_case_number="CV-2018-0501",
        entered_on="2018-01-01",
        filing_costs_cents=0,
    )
    assert ctx["judgment"]["expires_on"] == "2028-01-01"

    summary = advance_clock("2028-01-01T00:00:00Z")
    assert_sweep_summary_shape(summary)
    assert summary["expired_judgment_count"] == 1
    assert read_judgment(ctx["judgment"]["id"])["status"] == "EXPIRED"


def test_the_expired_judgment_is_reported_before_the_garnishment_floor(api):
    """PRD §2.8: "When several checks would fail on the same request, the response
    is determined by the **first** failing check in the following fixed order.
    This ordering is normative: a request that violates both a
    segregation-of-duties rule and a fiscal floor reports the segregation failure,
    never the floor."
    PRD §2.8: "The governing judgment's `status` is not `EXPIRED` — otherwise
    `ERR_JUDGMENT_EXPIRED` and HTTP 409. This applies to every write endpoint that
    touches a judgment or any of its children."
    PRD §2.8: "A wage garnishment yields a strictly positive weekly withholding —
    otherwise `ERR_GARNISHMENT_BELOW_FLOOR` and HTTP 422, on writ request when the
    instrument is a wage garnishment."

    Design: Difficulty/priority_pair_validation_conflict/expired_judgment_beats_garnishment_floor
    """
    ctx = setup_drafted_wage_garnishment(
        21_750,
        debtor_overrides={"head_of_household": False},
        filing_overrides={"fee_cents": 0},
        court_case_number="CV-2018-0502",
        entered_on="2018-01-01",
        filing_costs_cents=0,
    )
    advance_clock("2028-01-01T00:00:00Z")

    resp = api.request_writ(ctx["action"]["id"], EO)
    validate_error(resp, ApiErrorId.ERR_JUDGMENT_EXPIRED.value, 409)
    assert read_action(ctx["action"]["id"])["status"] == "DRAFT"


# ==========================================================================
# Corner coverage
# ==========================================================================
def test_a_third_renewal_hits_the_renewal_ceiling(api):
    """PRD §3.9: "A judgment may be renewed at most twice — `renewal_count` must
    be strictly less than 2 — and a third attempt is `ERR_RENEWAL_LIMIT_REACHED`."
    PRD §3.9: "A renewal fee of 5,000 cents is added to `costs_balance_cents`."

    Design: Corner/validations/third_renewal_returns_renewal_limit_reached
    """
    ctx = setup_judgment(
        court_case_number="CV-2026-4017",
        original_principal_cents=5_000_000,
        interest_rate_bps=0,
        filing_costs_cents=0,
    )

    advance_clock("2035-07-05T00:00:00Z", CO)
    first = validate_success(api.renew_judgment(ctx["judgment"]["id"], CO))
    assert first["renewal_count"] == 1
    assert first["expires_on"] == "2046-01-01"

    advance_clock("2045-07-05T00:00:00Z", CO)
    second = validate_success(api.renew_judgment(ctx["judgment"]["id"], CO))
    assert second["renewal_count"] == 2
    assert second["expires_on"] == "2056-01-01"
    assert second["costs_balance_cents"] == 10_000

    advance_clock("2055-07-05T00:00:00Z", CO)
    validate_error(
        api.renew_judgment(ctx["judgment"]["id"], CO),
        ApiErrorId.ERR_RENEWAL_LIMIT_REACHED.value,
        409,
    )

    judgment = read_judgment(ctx["judgment"]["id"])
    assert judgment["renewal_count"] == 2
    assert judgment["status"] == "ACTIVE"


def test_expiry_lapses_the_recorded_filing_and_drops_the_posture(api):
    """PRD §3.9: "Its `enforcement_posture` is driven to `NONE` from wherever it
    stood — `LIEN_PERFECTED → NONE`, `ENFORCING → NONE` or `STAYED → NONE`."
    PRD §3.9: "Every county filing on it in status `RECORDED` moves `RECORDED →
    LAPSED`, in `created_at` ascending order, driving `perfected_county_count` to
    0."

    Design: Corner/state_machines/clock_sweep_expires_judgment_and_lapses_recorded_filings
    """
    ctx = setup_judgment(
        court_case_number="CV-2018-2008",
        entered_on="2018-01-01",
        interest_rate_bps=0,
        filing_costs_cents=0,
    )
    assert ctx["judgment"]["expires_on"] == "2028-01-01"
    filing = record_county_filing(ctx["judgment"]["id"], fee_cents=0)
    assert read_judgment(ctx["judgment"]["id"])["enforcement_posture"] == "LIEN_PERFECTED"

    summary = advance_clock("2028-01-01T00:00:00Z")
    assert summary["expired_judgment_count"] == 1

    judgment = read_judgment(ctx["judgment"]["id"])
    assert judgment["status"] == "EXPIRED"
    assert judgment["enforcement_posture"] == "NONE"
    assert judgment["perfected_county_count"] == 0
    assert read_filing(filing["id"])["status"] == "LAPSED"


def test_the_clock_may_not_be_wound_backwards(api):
    """PRD §2.5: "The clock may only move forward or stay where it is: a
    `to_iso8601` earlier than the current logical instant is rejected with
    `ERR_CLOCK_REGRESSION` and HTTP 422."

    Design: Corner/validations/setting_the_clock_backwards_returns_clock_regression
    """
    first = advance_clock("2026-09-01T00:00:00Z")
    assert_logical_instant_equals(first["current_utc"], "2026-09-01T00:00:00Z")

    validate_error(
        api.set_clock("2026-08-15T00:00:00Z", CM),
        ApiErrorId.ERR_CLOCK_REGRESSION.value,
        422,
    )

    again = advance_clock("2026-09-01T00:00:00Z")
    assert_logical_instant_equals(again["current_utc"], "2026-09-01T00:00:00Z")


def test_a_quiet_clock_advance_reports_five_zero_counters(api):
    """PRD §2.5: "The response to a clock advance is not a stored object but a
    summary: `current_utc` echoes the new logical instant, and
    `expired_judgment_count`, `defaulted_claim_count`, `expired_offer_count`,
    `expired_subpoena_count` and `terminated_agreement_count` report how many rows
    each step touched, with `terminated_agreement_count` counting the installment
    agreements terminated by the step-1 cascade."
    PRD §2.5: "Firm staff advance it through `POST /_clock/set_current_utc`,
    supplying `to_iso8601`; the four staff roles `CaseManager`,
    `AssetInvestigator`, `EnforcementOfficer` and `ComplianceOfficer` may all call
    it."

    Design: Corner/endpoints/clock_endpoint_reports_zero_sweep_counts_when_nothing_is_due
    """
    from test_helpers import make_asset_investigator_headers

    ctx = setup_judgment(
        court_case_number="CV-2026-5002", interest_rate_bps=0, filing_costs_cents=0
    )

    summary = advance_clock(
        "2026-08-05T00:00:00Z", make_asset_investigator_headers("inv-1")
    )
    assert_sweep_summary_shape(summary)
    assert_logical_instant_equals(summary["current_utc"], "2026-08-05T00:00:00Z")
    assert summary["expired_judgment_count"] == 0
    assert summary["defaulted_claim_count"] == 0
    assert summary["expired_offer_count"] == 0
    assert summary["expired_subpoena_count"] == 0
    assert summary["terminated_agreement_count"] == 0
    assert read_judgment(ctx["judgment"]["id"])["status"] == "ACTIVE"


def test_pagination_arguments_outside_their_range_are_rejected(api):
    """PRD §2.3: "`limit` defaults to 10 when omitted, may not be smaller than 1,
    and may not be larger than 100. `offset` defaults to 0 and may not be
    negative. A `limit` outside the range 1 through 100 inclusive, or a negative
    `offset`, or a non-integer value for either, is rejected with
    `ERR_INVALID_PAGINATION` and HTTP 400."

    Design: Corner/validations/pagination_limit_above_one_hundred_returns_invalid_pagination
    """
    setup_judgment(
        court_case_number="CV-2026-4015", interest_rate_bps=0, filing_costs_cents=0
    )

    validate_error(
        api.list_judgments(CM, {"limit": 101}),
        ApiErrorId.ERR_INVALID_PAGINATION.value,
        400,
    )
    validate_error(
        api.list_judgments(CM, {"offset": -1}),
        ApiErrorId.ERR_INVALID_PAGINATION.value,
        400,
    )

    rows, meta = validate_paginated(api.list_judgments(CM, {"limit": 100}))
    assert meta["total_count"] == 1
    assert len(rows) == 1
