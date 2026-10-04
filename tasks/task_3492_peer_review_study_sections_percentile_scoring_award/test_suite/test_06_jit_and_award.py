"""Just-in-time information flow (submit/return/resubmit/accept cycle, state
gates, ownership) and award issuance (per-year rounding-then-sum budget
build, immediate consistency of the issuance response)."""
from decimal import Decimal, ROUND_HALF_UP

import pytest

from test_helpers import (
    api_client,
    fixtures,
    factories,
    TEST_USERS,
    make_applicant_headers,
    validate_success,
    validate_error,
    ApiErrorId,
    JIT_BASE_ITEMS,
    TERM_STANDARD,
    add_days_iso,
)

_GO = TEST_USERS["grants_officer_headers"]


def _rhup_int(value) -> int:
    """Round half up to a whole cent (PRD money precision rule)."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _award_period_totals(directs, max_direct_cents_per_year, budget_cut_pct, indirect_cost_rate):
    """PRD §3.8 award budget build: per year, capped direct x (1 - cut)
    rounded half up, then indirect = direct x rate rounded half up; the
    per-year total is the sum of the two rounded components (per-year-then-
    sum; sum-then-round is the rejected order)."""
    totals = []
    for direct in directs:
        capped = min(direct, max_direct_cents_per_year)
        direct_y = _rhup_int(Decimal(capped) * (1 - Decimal(str(budget_cut_pct))))
        indirect_y = _rhup_int(Decimal(direct_y) * Decimal(str(indirect_cost_rate)))
        totals.append(direct_y + indirect_y)
    return totals


def test_jit_return_resubmit_cycle_to_acceptance():
    """PRD §3.8: "The owning `Applicant` answers the request from `ISSUED` or `RETURNED` status — any other state rejects with `ERR_JIT_INVALID_STATE` — by supplying `items_submitted`, which must cover every element of `required_items`; an incomplete package is rejected with `ERR_JIT_ITEM_MISSING`."
    PRD §3.8: "`RETURN` moves the request to `RETURNED` — optionally carrying a `return_reason` — so the applicant can revise and resubmit the full item set, while `ACCEPT` moves it to the terminal `ACCEPTED` state, records the supplied `budget_cut_pct` (defaulting to zero, and never above 0.30 — a value outside that range is rejected with `ERR_VALIDATION`) as a uniform direct-cost cut, and advances the application from `JIT_PENDING` to `JIT_COMPLETE`, incrementing the application's `version`."
    PRD §3.8: "Its `required_items` are derived from the application's flags: `OTHER_SUPPORT` and `BUDGET_JUSTIFICATION` always, plus `IRB_APPROVAL` exactly when `human_subjects_involved` is set, plus `IACUC_APPROVAL` exactly when `vertebrate_animals_involved` is set."

    Design: Difficulty/non_linear_state_machine/jit_return_resubmit_cycle_to_acceptance
    """
    scenario = fixtures.setup_jit_pending_application()
    jit = scenario["jit_request"]
    pi_id = scenario["applicant"]["id"]
    assert set(jit["required_items"]) == set(JIT_BASE_ITEMS)

    first = api_client.submit_jit_items(
        jit["id"], factories.jit_submit_items_payload(), make_applicant_headers(pi_id))
    assert validate_success(first, 200)["status"] == "SUBMITTED"

    returned = api_client.adjudicate_jit_request(
        jit["id"],
        factories.jit_adjudicate_payload("RETURN", return_reason="other support page incomplete"),
        _GO)
    assert validate_success(returned, 200)["status"] == "RETURNED"

    resubmitted = api_client.submit_jit_items(
        jit["id"], factories.jit_submit_items_payload(), make_applicant_headers(pi_id))
    assert validate_success(resubmitted, 200)["status"] == "SUBMITTED", (
        "the RETURNED -> SUBMITTED leg closes the cycle"
    )

    accepted = api_client.adjudicate_jit_request(
        jit["id"], factories.jit_adjudicate_payload("ACCEPT", budget_cut_pct=0.10), _GO)
    accepted_data = validate_success(accepted, 200)
    assert accepted_data["status"] == "ACCEPTED"
    assert accepted_data["budget_cut_pct"] == 0.10
    assert fixtures.refresh_application(scenario["application"]["id"])["status"] == "JIT_COMPLETE"


def test_award_budget_per_year_rounding_then_sum():
    """PRD §3.8: "For each requested year: the funded direct cost starts from the lesser of that year's `direct_cents_per_year` entry and the announcement's `max_direct_cents_per_year`; that capped amount is multiplied by one minus the `budget_cut_pct` and rounded half up to a whole cent; the year's indirect cost is that reduced direct amount multiplied by the institute's `indirect_cost_rate`, rounded half up to a whole cent; and the year's entry in `period_total_cents` is the sum of the two rounded components."
    PRD §3.8: "The evaluation order is pinned: each component is rounded per year *before* any summation — summing first and rounding once is a different, rejected order."
    PRD §3.8: "The award's `total_awarded_cents` is the sum of the per-year totals, and its `end_date` falls exactly `requested_years` times 365 days after the `start_date`."
    PRD §3.8: "Its `terms_and_conditions` always contain `STANDARD_TERMS_V1`, and gain `RESTRICTED_DRAW_DOWN` exactly when the accepted `budget_cut_pct` is greater than zero."
    Derivation for directs [19,999,997, 19,999,997, 20,000,006] at rate 0.55
    with no cut: indirects are rhup(19,999,997 x 0.55) = 10,999,998 twice and
    rhup(20,000,006 x 0.55) = 11,000,003, so period totals are
    [30,999,995, 30,999,995, 31,000,009] and the total is 92,999,999.

    Design: Difficulty/combinatorial_formula/award_budget_per_year_rounding_then_sum
    """
    scenario = fixtures.setup_jit_complete_application(
        budget_cut_pct=0,
        context_kwargs={"indirect_cost_rate": 0.55},
        direct_cents_per_year=[19_999_997, 19_999_997, 20_000_006],
        requested_years=3,
    )
    start = "2027-01-01T00:00:00Z"
    resp = api_client.issue_award(
        scenario["application"]["id"], factories.award_payload(start), _GO)
    award = validate_success(resp, 201)

    expected_periods = _award_period_totals(
        [19_999_997, 19_999_997, 20_000_006], 25_000_000, 0, 0.55)
    assert expected_periods == [30_999_995, 30_999_995, 31_000_009]
    assert award["period_total_cents"] == expected_periods
    assert award["total_awarded_cents"] == sum(expected_periods) == 92_999_999
    assert award["terms_and_conditions"] == [TERM_STANDARD]
    # 3 x 365 days after 2027-01-01 lands on 2029-12-31.
    assert award["end_date"] == add_days_iso(start, 3 * 365) == "2029-12-31T00:00:00Z"


def test_jit_adjudicate_before_submit_rejected():
    """PRD §3.8: "A `GrantsOfficer` then adjudicates a `SUBMITTED` package (otherwise `ERR_JIT_INVALID_STATE`) with a `decision`"

    Design: Corner/state_machines/jit_adjudicate_before_submit_rejected
    """
    scenario = fixtures.setup_jit_pending_application()
    jit = scenario["jit_request"]
    assert jit["status"] == "ISSUED"
    resp = api_client.adjudicate_jit_request(
        jit["id"], factories.jit_adjudicate_payload("ACCEPT", budget_cut_pct=0), _GO)
    validate_error(resp, ApiErrorId.ERR_JIT_INVALID_STATE)
    assert fixtures.refresh_jit_request(jit["id"])["status"] == "ISSUED"


def test_jit_submit_by_non_owner_forbidden():
    """PRD §2.7: "5. **Entity-backed ownership.** For owner-scoped operations — submission, withdrawal, JIT item submission, progress-report creation, modification creation, transfer proposal, reviewer respond, conflict declaration, assignment respond, and critique submission — the caller's `X-User-ID` must match the owning entity as described in §2.1 (`ERR_NOT_RESOURCE_OWNER`, HTTP 403)."
    PRD §2.1: "When `X-User-Role` is `Applicant`, `X-User-ID` is the `id` of the acting Applicant; ownership checks on any resource that references an Applicant compare the resource's foreign-key field to `X-User-ID` — an application's `applicant_id` directly, and, for award-scoped operations, the `applicant_id` of the application that the award funds."

    Design: Corner/rbac/jit_submit_by_non_owner_forbidden
    """
    scenario = fixtures.setup_jit_pending_application()
    jit = scenario["jit_request"]
    pi_b = fixtures.make_applicant()
    resp = api_client.submit_jit_items(
        jit["id"], factories.jit_submit_items_payload(),
        make_applicant_headers(pi_b["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)
    assert fixtures.refresh_jit_request(jit["id"])["status"] == "ISSUED"


def test_award_issuance_response_immediate():
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."
    PRD §4: "Operations that create a new resource — announcements, institutes, institutions, applicants, applications, study sections, reviewers, assignments, council reviews, awards, progress reports, modifications, and transfer requests — return a `201 Created` status code."
    PRD §3.8: "Issuance adds the `total_awarded_cents` to the institute's `committed_cents` and moves the application from `JIT_COMPLETE` to the terminal `AWARDED` state, incrementing its `version`."
    Derivation: direct 20,000,000 at rate 0.5 with no cut gives
    20,000,000 + rhup(20,000,000 x 0.5) = 30,000,000 in the single period, and
    the end date falls 365 days after 2027-01-01, i.e. 2028-01-01.

    Design: Corner/consistency_model/award_issuance_response_immediate
    """
    scenario = fixtures.setup_jit_complete_application(budget_cut_pct=0)
    start = "2027-01-01T00:00:00Z"
    resp = api_client.issue_award(
        scenario["application"]["id"], factories.award_payload(start), _GO)
    award = validate_success(resp, 201)

    # The 201 response itself already carries the computed budget.
    expected_periods = _award_period_totals([20_000_000], 25_000_000, 0, 0.5)
    assert expected_periods == [30_000_000]
    assert award["total_awarded_cents"] == 30_000_000
    assert award["period_total_cents"] == expected_periods
    assert award["end_date"] == add_days_iso(start, 365) == "2028-01-01T00:00:00Z"
    assert award["status"] == "ACTIVE"
    assert award["current_period"] == 1

    institute = fixtures.refresh_institute(scenario["context"]["institute"]["id"])
    assert institute["committed_cents"] == 30_000_000, (
        "the commitment is visible immediately after issuance"
    )
    assert fixtures.refresh_application(scenario["application"]["id"])["status"] == "AWARDED"
