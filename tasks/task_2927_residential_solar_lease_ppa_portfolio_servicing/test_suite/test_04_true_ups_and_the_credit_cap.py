"""Annual guarantee true-ups: the two methods, the credit cap and the void.

A true-up prices a whole contract year, so it is guarded by optimistic
concurrency against the agreement, gated on twelve complete months, capped at a
quarter of the annual contract value and reversible only by a second person.
"""

import pytest

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_errors as E
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import test_users as U
from test_helpers.assertions import assert_credit_counters, assert_identity_fields
from test_helpers.fixtures import (
    activate,
    book_ppa,
    create_true_up,
    make_homeowner,
    make_tariff,
    post_true_up,
    read_agreement,
    record_period,
    set_clock,
)

# The twelve monthly meter readings of the shared contract year 1 (2025).
METERED_YEAR = [400, 580, 780, 900, 900, 950, 1000, 980, 800, 690, 450, 380]
# Their per-month floors and rounded credit figures, month by month.
MONTHLY_FLOORS = [474, 565, 757, 894, 994, 1021, 1031, 967, 848, 694, 484, 392]
MONTHLY_CREDITS = [1092, 0, 0, 0, 1387, 1047, 457, 0, 708, 59, 502, 177]


def _active_a1_agreement(api, clock="2026-08-01T00:00:00Z"):
    """An ACTIVE PPA whose contract year 1 is the twelve calendar months of 2025."""
    set_clock(api, clock)
    owner = make_homeowner(api)
    schedule = make_tariff(api)
    agreement = book_ppa(
        api,
        owner["id"],
        schedule["id"],
        contract_start_date="2025-01-01",
        escalator_pct=0.029,
        base_ppa_rate_per_kwh_millicents=14750,
        guaranteed_annual_kwh=9600,
        guarantee_band_pct=0.05,
    )
    activate(api, agreement["id"])
    return agreement


def _record_year(api, agreement_id, metered_by_month, issue_credit=False):
    """Record and settle the twelve months of 2025 from an explicit meter list."""
    months = []
    for index, metered in enumerate(metered_by_month, start=1):
        months.append(
            record_period(
                api,
                agreement_id,
                2025,
                index,
                metered,
                auto_reconcile=True,
                auto_issue_credit=issue_credit,
            )
        )
    return months


def _current_version(api, agreement_id):
    return read_agreement(api, agreement_id)["version"]


def test_a_true_up_needs_all_twelve_months_before_it_may_be_computed(api):
    """Two recorded months are not a contract year, and the refusal writes nothing.

    §3.4: "The computation is refused with `ERR_PERIODS_INCOMPLETE` unless twelve
    metered months exist for that agreement and that `contract_year`". §2.4:
    "`version`, an integer that begins at 1 and increases by exactly one on every
    mutation of that resource", and §3.4: "A successful computation lands in
    `status` `DRAFT`, moves no money, and advances the parent agreement's `version`
    by one."

    Design: Corner/validations/true_up_for_a_year_with_only_two_recorded_months_is_rejected
    """
    agreement = _active_a1_agreement(api)
    _record_year(api, agreement["id"], METERED_YEAR[:2])
    before = _current_version(api, agreement["id"])

    validate_error(
        api.create_true_up(
            F.true_up_payload(
                agreement["id"], 1, C.METHOD_ANNUAL_TRUE_UP, before
            ),
            U.agent_headers(),
        ),
        E.ERR_PERIODS_INCOMPLETE,
        422,
    )

    rows, meta = validate_paginated(
        api.list_true_ups(U.agent_headers(), {"agreement_id": agreement["id"]})
    )
    assert rows == []
    assert meta["total_count"] == 0
    assert _current_version(api, agreement["id"]) == before


def test_a_stale_agreement_version_is_answered_before_the_completeness_rule(api):
    """The same body earns 412 one version behind and 422 once it is fresh.

    §2.10 rung 9: "**Parent version freshness.** `ERR_STALE_AGREEMENT_VERSION` or
    `ERR_STALE_OUTAGE_EVENT_VERSION`, HTTP 412, on true-up creation and truck-roll
    creation respectively". §2.10 rung 12 places `ERR_PERIODS_INCOMPLETE` lower, and
    §2.7: "If `expected_agreement_version` does not equal the agreement's current
    `version`, the create is refused with `ERR_STALE_AGREEMENT_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_agreement_version_on_a_true_up_returns_412
    """
    agreement = _active_a1_agreement(api)
    current = _current_version(api, agreement["id"])

    validate_error(
        api.create_true_up(
            F.true_up_payload(
                agreement["id"], 1, C.METHOD_MONTHLY_ROLLING, current - 1
            ),
            U.agent_headers(),
        ),
        E.ERR_STALE_AGREEMENT_VERSION,
        412,
    )
    validate_error(
        api.create_true_up(
            F.true_up_payload(agreement["id"], 1, C.METHOD_MONTHLY_ROLLING, current),
            U.agent_headers(),
        ),
        E.ERR_PERIODS_INCOMPLETE,
        422,
    )

    _, meta = validate_paginated(
        api.list_true_ups(U.agent_headers(), {"agreement_id": agreement["id"]})
    )
    assert meta["total_count"] == 0
    assert _current_version(api, agreement["id"]) == current


def test_the_expected_agreement_version_field_is_mandatory(api):
    """Omitting the concurrency token is a malformed request, not a stale one.

    §2.7: "neither of these two fields is optional on its endpoint: a create that
    omits it is a malformed request." §2.10 rung 3: "**Payload shape and domain.**
    `ERR_INVALID_REQUEST`, HTTP 400 ... This rung covers a required input field
    that is missing or null".

    Design: Corner/cross_cutting_complexity_layers/stale_expected_agreement_version_on_a_true_up_returns_412
    """
    agreement = _active_a1_agreement(api)
    current = _current_version(api, agreement["id"])

    validate_error(
        api.create_true_up(
            {
                "agreement_id": agreement["id"],
                "contract_year": 1,
                "method": C.METHOD_MONTHLY_ROLLING,
            },
            U.agent_headers(),
        ),
        E.ERR_INVALID_REQUEST,
        400,
    )
    assert _current_version(api, agreement["id"]) == current


def test_monthly_rolling_sums_twelve_independently_rounded_monthly_credits(api):
    """Every monthly dip is paid, so the annual total carries twelve roundings.

    §3.4: "Under `MONTHLY_ROLLING`, every monthly dip is paid:
    `annual_guarantee_floor_kwh` is 0, `credit_rate_millicents` is 0,
    `annual_shortfall_kwh` is the sum of the twelve months' `shortfall_kwh`, and
    `gross_credit_cents` is the sum of the twelve months' `credit_cents` — a total
    that therefore carries twelve independent roundings." §3.4: "`covered_period_ids`
    records the twelve month ids in that same ascending order".

    Design: Difficulty/dual_variant_calc/true_up_monthly_rolling_vs_annual_diverge_on_same_twelve_months
    """
    agreement = _active_a1_agreement(api)
    months = _record_year(api, agreement["id"], METERED_YEAR)

    assert [month["guarantee_floor_kwh"] for month in months] == MONTHLY_FLOORS
    assert [month["credit_cents"] for month in months] == MONTHLY_CREDITS
    assert all(month["status"] == C.PERIOD_RECONCILED for month in months)

    rolling = create_true_up(
        api,
        agreement["id"],
        1,
        C.METHOD_MONTHLY_ROLLING,
        _current_version(api, agreement["id"]),
    )

    assert_identity_fields(rolling)
    assert rolling["method"] == C.METHOD_MONTHLY_ROLLING
    assert rolling["total_metered_kwh"] == 8810
    assert rolling["total_adjusted_expected_kwh"] == 9601
    assert rolling["annual_guarantee_floor_kwh"] == 0
    assert rolling["annual_shortfall_kwh"] == 368
    assert rolling["credit_rate_millicents"] == 0
    assert rolling["gross_credit_cents"] == 5429
    assert rolling["already_issued_credit_cents"] == 0
    assert rolling["net_credit_cents"] == 5429
    assert rolling["status"] == C.TRUE_UP_DRAFT
    assert rolling["posted_by_user_id"] is None
    assert rolling["voided_by_user_id"] is None
    assert rolling["covered_period_ids"] == [month["id"] for month in months]

    assert_credit_counters(
        read_agreement(api, agreement["id"]), earned=0, applied=0, balance=0
    )


def test_the_two_methods_disagree_by_exactly_842_cents_on_one_year(api):
    """A strong summer offsets a weak winter only under the annual instrument.

    §3.4: "Under `ANNUAL_TRUE_UP`, a strong summer is allowed to offset a weak
    winter before anything is owed: `annual_guarantee_floor_kwh` is
    `total_adjusted_expected_kwh` multiplied by one minus the agreement's
    `guarantee_band_pct`, rounded to a whole kilowatt-hour ... and
    `gross_credit_cents` is `annual_shortfall_kwh` multiplied by that rate, divided
    by 1000 and rounded once, at the end, to a whole cent." §3.4: "The two methods
    are expected to disagree on the same twelve months, and that disagreement is the
    contractual point rather than a defect."

    Design: Difficulty/dual_variant_calc/true_up_monthly_rolling_vs_annual_diverge_on_same_twelve_months
    """
    agreement = _active_a1_agreement(api)
    _record_year(api, agreement["id"], METERED_YEAR)

    rolling = create_true_up(
        api,
        agreement["id"],
        1,
        C.METHOD_MONTHLY_ROLLING,
        _current_version(api, agreement["id"]),
    )
    annual = create_true_up(
        api,
        agreement["id"],
        1,
        C.METHOD_ANNUAL_TRUE_UP,
        _current_version(api, agreement["id"]),
    )

    assert annual["method"] == C.METHOD_ANNUAL_TRUE_UP
    assert annual["total_metered_kwh"] == 8810
    assert annual["total_adjusted_expected_kwh"] == 9601
    assert annual["annual_guarantee_floor_kwh"] == 9121
    assert annual["annual_shortfall_kwh"] == 311
    assert annual["credit_rate_millicents"] == 14750
    assert annual["gross_credit_cents"] == 4587
    assert annual["already_issued_credit_cents"] == 0
    assert annual["net_credit_cents"] == 4587
    assert annual["status"] == C.TRUE_UP_DRAFT

    assert rolling["net_credit_cents"] - annual["net_credit_cents"] == 842
    assert_credit_counters(
        read_agreement(api, agreement["id"]), earned=0, applied=0, balance=0
    )


def test_a_true_up_above_the_annual_cap_computes_but_can_never_be_posted(api):
    """A zero-production year prices 134535 cents against a 35400-cent cap.

    §3.4: "the sum of `net_credit_cents` across every `POSTED` true-up for that
    agreement and contract year, with this true-up's own `net_credit_cents` included
    in the sum whether or not it is already posted, may not exceed twenty-five
    percent of that contract year's annual contract value, computed as 0.25
    multiplied by the annual contract value for the year and rounded to a whole
    cent. A breach is reported as `ERR_CREDIT_CAP_EXCEEDED`." §3.2: "the annual
    contract value for a contract year is twelve times that contract year's notional
    monthly payment".

    Design: Corner/validations/posting_a_true_up_worth_more_than_a_quarter_of_the_annual_value_is_rejected
    """
    agreement = _active_a1_agreement(api)
    _record_year(api, agreement["id"], [0] * 12)

    draft = create_true_up(
        api,
        agreement["id"],
        1,
        C.METHOD_ANNUAL_TRUE_UP,
        _current_version(api, agreement["id"]),
    )
    assert draft["total_metered_kwh"] == 0
    assert draft["total_adjusted_expected_kwh"] == 9601
    assert draft["annual_guarantee_floor_kwh"] == 9121
    assert draft["annual_shortfall_kwh"] == 9121
    assert draft["credit_rate_millicents"] == 14750
    assert draft["gross_credit_cents"] == 134535
    assert draft["already_issued_credit_cents"] == 0
    assert draft["net_credit_cents"] == 134535

    validate_error(
        api.post_true_up(draft["id"], U.agent_headers()),
        E.ERR_CREDIT_CAP_EXCEEDED,
        422,
    )

    unchanged = validate_success(api.get_true_up(draft["id"], U.agent_headers()), 200)
    assert unchanged["status"] == C.TRUE_UP_DRAFT
    assert unchanged["posted_by_user_id"] is None
    assert_credit_counters(
        read_agreement(api, agreement["id"]), earned=0, applied=0, balance=0
    )


# A twelve-month year whose annual true-up is worth more than half the 35400 cap.
METERED_HALF_CAP = [400, 480, 640, 760, 840, 860, 870, 820, 720, 590, 410, 355]


def _posted_true_up_over_half_the_cap(api):
    """A POSTED 20296-cent annual true-up, posted by the first servicing agent."""
    agreement = _active_a1_agreement(api)
    _record_year(api, agreement["id"], METERED_HALF_CAP)
    draft = create_true_up(
        api,
        agreement["id"],
        1,
        C.METHOD_ANNUAL_TRUE_UP,
        _current_version(api, agreement["id"]),
    )
    posted = post_true_up(api, draft["id"])
    return agreement, posted


def test_reposting_a_posted_true_up_reports_the_state_code_not_the_fiscal_one(api):
    """Both rungs are violated at once and the ladder awards the 409.

    §3.4: "A `DRAFT` true-up moves `DRAFT → POSTED` ... a violation — including an
    attempt to post a true-up that is itself already `POSTED` — is reported as
    `ERR_TRUE_UP_ALREADY_POSTED`." §3.4: "Because the target's own figure is always
    inside the sum, re-posting a `POSTED` true-up that consumed more than half of the
    cap breaches the cap as well as the state ladder — and the ladder decides which
    the client hears."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_reposting_a_capped_true_up
    """
    _, posted = _posted_true_up_over_half_the_cap(api)

    assert posted["total_metered_kwh"] == 7745
    assert posted["annual_guarantee_floor_kwh"] == 9121
    assert posted["annual_shortfall_kwh"] == 1376
    assert posted["credit_rate_millicents"] == 14750
    assert posted["gross_credit_cents"] == 20296
    assert posted["already_issued_credit_cents"] == 0
    assert posted["net_credit_cents"] == 20296
    assert posted["status"] == C.TRUE_UP_POSTED
    assert 20296 + 20296 > 35400

    response = api.post_true_up(posted["id"], U.agent_headers())

    validate_error(response, E.ERR_TRUE_UP_ALREADY_POSTED, 409)
    assert response.status_code != 422


@pytest.mark.parametrize("role", ["agent", "admin"])
def test_the_refused_repost_credits_nothing_twice(api, role):
    """The rejected second post leaves the stamp and all three counters alone.

    §3.4: "On success the agreement's `credit_earned_cents` and
    `credit_balance_cents` each increase by `net_credit_cents`, `posted_by_user_id`
    is stamped with the acting `X-User-ID`". §2.9: "`credit_earned_cents` equals the
    sum of `credit_cents` over the agreement's metered months whose `status` is
    `CREDIT_ISSUED`, plus the sum of `net_credit_cents` over the agreement's
    guarantee true-ups whose `status` is `POSTED`."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_reposting_a_capped_true_up
    """
    agreement, posted = _posted_true_up_over_half_the_cap(api)
    headers = U.agent_headers(U.AGENT_2) if role == "agent" else U.admin_headers()

    validate_error(
        api.post_true_up(posted["id"], headers), E.ERR_TRUE_UP_ALREADY_POSTED, 409
    )

    again = validate_success(api.get_true_up(posted["id"], U.agent_headers()), 200)
    assert again["status"] == C.TRUE_UP_POSTED
    assert again["posted_by_user_id"] == U.AGENT_1
    assert again["net_credit_cents"] == 20296
    assert_credit_counters(
        read_agreement(api, agreement["id"]), earned=20296, applied=0, balance=20296
    )


def _posted_rolling_true_up(api):
    """A POSTED 5429-cent MONTHLY_ROLLING true-up plus the twelve months it covers."""
    agreement = _active_a1_agreement(api)
    months = _record_year(api, agreement["id"], METERED_YEAR)
    draft = create_true_up(
        api,
        agreement["id"],
        1,
        C.METHOD_MONTHLY_ROLLING,
        _current_version(api, agreement["id"]),
    )
    posted = post_true_up(api, draft["id"])
    return agreement, months, posted


def test_the_posting_user_may_not_void_their_own_true_up(api):
    """Two-person control on the void, checked before the state ladder.

    §3.4: "A `POSTED` true-up moves `POSTED → VOID` only when the acting
    `X-User-ID` differs from `posted_by_user_id`, otherwise
    `ERR_SEGREGATION_OF_DUTIES`". §2.10 rung 7: "**Segregation of duties.**
    `ERR_SEGREGATION_OF_DUTIES`, HTTP 403, on the five two-person operations listed
    in §2.1 — voiding a true-up, closing out a truck roll, recording a
    subordination, and approving or denying a warranty claim."

    Design: Difficulty/compensating_invariant/void_posted_true_up_restores_credit_ledger_exactly
    """
    agreement, _, posted = _posted_rolling_true_up(api)

    assert posted["status"] == C.TRUE_UP_POSTED
    assert posted["net_credit_cents"] == 5429
    assert posted["posted_by_user_id"] == U.AGENT_1
    assert_credit_counters(
        read_agreement(api, agreement["id"]), earned=5429, applied=0, balance=5429
    )

    validate_error(
        api.void_true_up(posted["id"], U.agent_headers(U.AGENT_1)),
        E.ERR_SEGREGATION_OF_DUTIES,
        403,
    )

    still_posted = validate_success(
        api.get_true_up(posted["id"], U.agent_headers()), 200
    )
    assert still_posted["status"] == C.TRUE_UP_POSTED
    assert still_posted["voided_by_user_id"] is None
    assert_credit_counters(
        read_agreement(api, agreement["id"]), earned=5429, applied=0, balance=5429
    )


def test_a_second_user_voids_the_true_up_and_the_ledger_returns_to_zero(api):
    """The void removes exactly 5429 cents and leaves the covered months alone.

    §3.4: "the agreement's `credit_earned_cents` and `credit_balance_cents` are each
    reduced by exactly `net_credit_cents`, `voided_by_user_id` is stamped, and the
    agreement's `version` advances." §2.8: "Where an operation is described as
    compensating — reopening a settled month, voiding a posted true-up, cancelling a
    dispatch, withdrawing an election, cancelling a transfer — it removes exactly
    what its counterpart added and leaves no residue in any counter."

    Design: Difficulty/compensating_invariant/void_posted_true_up_restores_credit_ledger_exactly
    """
    agreement, months, posted = _posted_rolling_true_up(api)

    voided = validate_success(
        api.void_true_up(posted["id"], U.agent_headers(U.AGENT_2)), 200
    )

    assert voided["status"] == C.TRUE_UP_VOID
    assert voided["voided_by_user_id"] == U.AGENT_2
    assert voided["posted_by_user_id"] == U.AGENT_1
    assert voided["net_credit_cents"] == 5429

    settled = read_agreement(api, agreement["id"])
    assert_credit_counters(settled, earned=0, applied=0, balance=0)
    assert (
        settled["credit_balance_cents"]
        == settled["credit_earned_cents"] - settled["credit_applied_cents"]
    )

    january = validate_success(api.get_period(months[0]["id"], U.agent_headers()), 200)
    assert january["status"] == C.PERIOD_RECONCILED
    assert january["credit_cents"] == MONTHLY_CREDITS[0]
