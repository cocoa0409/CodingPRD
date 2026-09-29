"""Where two layers meet: the version token, the pool ledger, and the cascade.

Three mechanisms in this API are cross-cutting rather than local. The
`Acquisition` version token is spent by writes that arrive from unrelated
directions, so a caller who read once and writes twice is refused the second
time. The retention pool is a cumulative ledger checked at commitment time, so
an offer may be drafted for more than the deal can bear and only fail when
somebody tries to extend it. And a clearance move reaches down into the child
rows it is allowed to touch and leaves the rest exactly as they were.

Every figure asserted here is re-derived from the rounding points the PRD pins:
components are rounded independently before they are summed, and the retention
award is clamped floor-first, cap-second.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_success,
)

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import PRECEDENCE_RANK, ApiErrorId
from test_helpers.constants import (
    BENCHMARK_BASIS_COMP_PER_WRVU,
    CLEARANCE_CLEARED,
    CLEARANCE_FLAGGED,
    CLEARANCE_PENDING,
    CLEARANCE_SUSPENDED,
    DEAL_STATUS_DILIGENCE,
    DEFAULT_CLOCK_DATE,
    EMPLOYMENT_PROSPECTIVE,
    HR_COVERAGE_COMPLETE_PCT,
    MODEL_WRVU_PRODUCTIVITY,
    OFFER_STATUS_ACCEPTED,
    OFFER_STATUS_DRAFT,
    OFFER_STATUS_EXTENDED,
    OFFER_STATUS_RESCINDED,
    OPINION_TYPE_COMMERCIAL_REASONABLENESS,
    PLAN_STATUS_DRAFT,
    POSTURE_AT_RISK,
    POSTURE_READY,
    ROLE_CODE_BILLER,
    ROLE_CODE_FRONT_DESK,
    ROLE_CODE_MA,
    ROLE_CODE_PRACTICE_MANAGER,
    ROLE_CODE_RN,
    STARK_BONA_FIDE_EMPLOYMENT,
    TASK_COMPLIANCE_TRAINING,
    TASK_HR_STAFFING_PLAN,
    TASK_STATUS_COMPLETE,
    TASK_STATUS_IN_PROGRESS,
    TASK_STATUS_OPEN,
)
from test_helpers.fixtures import (
    COMPENSATION_DESIGNER,
    COMPLIANCE_OFFICER,
    DEAL_LEAD,
    INTEGRATION_MANAGER,
    VALUATION_ANALYST,
    create_acquisition,
    create_offer,
    create_physician,
    create_task,
    diligence_deal,
    in_progress_task,
    read_acquisition,
    read_task,
    reset_clock,
    second_physician,
    set_clearance,
    set_offer_status,
    set_task_status,
)

# --- Staff transition offer inputs, one per role code ------------------------

OFFER_EXPIRES_ON = "2026-10-15"

PM_OFFER = {
    "staff_member_name": "Dorothy Achebe",
    "role_code": ROLE_CODE_PRACTICE_MANAGER,
    "legacy_annual_wage_cents": 12_000_000,
    "legacy_pto_hours": 160,
    "credited_service_months": 200,
    "offer_expires_on": OFFER_EXPIRES_ON,
}
RN_OFFER = {
    "staff_member_name": "Nadia Brackenbury",
    "role_code": ROLE_CODE_RN,
    "legacy_annual_wage_cents": 8_000_000,
    "legacy_pto_hours": 80,
    "credited_service_months": 130,
    "offer_expires_on": OFFER_EXPIRES_ON,
}
MA_OFFER = {
    "staff_member_name": "Teo Marchetti",
    "role_code": ROLE_CODE_MA,
    "legacy_annual_wage_cents": 3_600_000,
    "legacy_pto_hours": 40,
    "credited_service_months": 30,
    "offer_expires_on": OFFER_EXPIRES_ON,
}
FRONT_DESK_OFFER = {
    "staff_member_name": "Imani Rutledge",
    "role_code": ROLE_CODE_FRONT_DESK,
    "legacy_annual_wage_cents": 3_400_000,
    "legacy_pto_hours": 0,
    "credited_service_months": 6,
    "offer_expires_on": OFFER_EXPIRES_ON,
}
BILLER_OFFER = {
    "staff_member_name": "Perla Otieno",
    "role_code": ROLE_CODE_BILLER,
    "legacy_annual_wage_cents": 5_282_350,
    "legacy_pto_hours": 104,
    "credited_service_months": 84,
    "offer_expires_on": OFFER_EXPIRES_ON,
}

# --- Harmonised wages and retention awards, re-derived ----------------------
#
# PRACTICE_MANAGER: 12000000 + round(12000000 * 800 / 10000) = 12000000 + 960000,
# plus round(160 * (12000000 / 2080) * 5000 / 10000) = 461538 -> 13421538, above
# the 9500000 floor.  Award: round(13421538 * 1100 / 10000) = 1476369, then
# round(1476369 * 12500 / 10000) = 1845461, clamped down by the 1500000 cap.
PM_WAGE_CENTS = 13_421_538
PM_AWARD_BEFORE_CAP_CENTS = 1_845_461
PM_BONUS_CENTS = 1_500_000

# RN: 8000000 + 480000 + round(80 * (8000000 / 2080) * 0.5) = 8633846, above the
# 7600000 floor.  Award: round(8633846 * 1100 / 10000) = 949723, then
# round(949723 * 12500 / 10000) = 1187154, inside both clamps.
RN_WAGE_CENTS = 8_633_846
RN_BONUS_CENTS = 1_187_154

# MA: 3600000 + 144000 + 34615 = 3778615, strictly below the 4200000 floor, so
# the floor displaces it.  Award: round(4200000 * 500 / 10000) = 210000 with a
# criticality multiplier of 10000 bps, inside both clamps.
MA_WAGE_CENTS = 4_200_000
MA_BONUS_CENTS = 210_000

# FRONT_DESK: 3400000 + 85000 + 0 = 3485000, below the 3600000 floor.  Award:
# round(3600000 * 200 / 10000) = 72000, raised to the 100000 floor.
FRONT_DESK_WAGE_CENTS = 3_600_000
FRONT_DESK_AWARD_BEFORE_FLOOR_CENTS = 72_000
FRONT_DESK_BONUS_CENTS = 100_000

# BILLER: 5282350 + round(5282350 * 300 / 10000) = 5282350 + 158471, plus
# round(104 * (5282350 / 2080) * 0.5) = 132059 -> 5572880, above the 4400000
# floor.  Award: round(5572880 * 800 / 10000) = 445830, then
# round(445830 * 12500 / 10000) = 557288, inside both clamps.
BILLER_WAGE_CENTS = 5_572_880
BILLER_BONUS_CENTS = 557_288

# Ledger totals used by the boundary fixtures.
POOL_TOTAL_EXACT_CENTS = PM_BONUS_CENTS + RN_BONUS_CENTS + MA_BONUS_CENTS  # 2897154
POOL_AFTER_MA_RELEASE_CENTS = PM_BONUS_CENTS + RN_BONUS_CENTS  # 2687154
FOUR_SEAT_COMMITMENT_CENTS = POOL_TOTAL_EXACT_CENTS + FRONT_DESK_BONUS_CENTS  # 2997154
STANDARD_POOL_TOTAL_CENTS = 3_000_000

# --- Coverage and posture ---------------------------------------------------

COVERAGE_THREE_OF_FIVE_PCT = 60.00
COVERAGE_FOUR_OF_FIVE_PCT = 80.00

# --- The second plan in the optimistic-concurrency pair --------------------

PLAN_B_CF_CENTS_PER_WRVU = 8_500
PLAN_B_PROJECTED_WRVU = 4_000
PLAN_B_TOTAL_CASH_CENTS = 34_000_000
PLAN_B_PER_WRVU_CENTS = 8_500
# 8500 is above the PRIMARY_CARE ninetieth point of 7600:
# 90 + 9 * (8500 - 7600) / 7600 = 91.0657... -> 91.07, under the cap of 99.
PLAN_B_PERCENTILE = 91.07

CLEARANCE_NOTE_FLAGGED = "Referral-source review opened"
CLEARANCE_NOTE_SUSPENDED = "Integration suspended pending the self-disclosure decision"
CLEARANCE_NOTE_LIFTED = "Self-disclosure decided, integration resumed"


def _wrvu_plan_payload(acquisition_id: str, version: int, physician_id: str) -> dict:
    """The productivity plan whose economics land at the 91.07th percentile."""
    return f.compensation_plan_payload(
        acquisition_id,
        version,
        physician_id,
        model_type=MODEL_WRVU_PRODUCTIVITY,
        base_salary_cents=0,
        conversion_factor_cents_per_wrvu=PLAN_B_CF_CENTS_PER_WRVU,
        threshold_wrvu=0,
        projected_annual_wrvu=PLAN_B_PROJECTED_WRVU,
        includes_referral_credit=False,
        stark_exception=STARK_BONA_FIDE_EMPLOYMENT,
        fmv_justification_on_file=True,
    )


# ---------------------------------------------------------------------------
# The analyst spends its own token on the first filing
# ---------------------------------------------------------------------------


def test_a_second_opinion_filed_from_one_read_is_refused_as_stale(api: ApiClient):
    """One read, two filings: the second is built on a superseded picture.

    PRD: "A `POST /valuation-opinions` request must carry
    `expected_acquisition_version` equal to the target acquisition's current
    stored `version`."

    PRD: "If the value does not match — because some other writer has advanced
    the acquisition since the client read it — the create is rejected with
    `ERR_STALE_ACQUISITION_VERSION` and HTTP 412."

    PRD: "On success the server increments the acquisition's `version` by 1."

    Design: Corner/cross_cutting_complexity_layers/stale_acquisition_version_on_opinion_create_returns_412
    """
    reset_clock(api)
    deal = diligence_deal(api)
    acquisition_id = deal["acquisition"]["id"]

    read_once = read_acquisition(api, acquisition_id, VALUATION_ANALYST)
    stale_version = read_once["version"]

    validate_success(
        api.create_valuation_opinion(
            f.market_fmv_payload(acquisition_id, stale_version), VALUATION_ANALYST
        ),
        201,
    )

    cr_body = f.cr_opinion_payload(acquisition_id, stale_version)
    validate_error(
        api.create_valuation_opinion(cr_body, VALUATION_ANALYST),
        ApiErrorId.STALE_ACQUISITION_VERSION,
        412,
    )

    a.assert_total_count(
        api.list_valuation_opinions({"acquisition_id": acquisition_id}, VALUATION_ANALYST),
        1,
    )

    after_fmv = read_acquisition(api, acquisition_id, VALUATION_ANALYST)
    assert after_fmv["version"] == stale_version + 1, (
        "the fair market value filing should have spent exactly one version"
    )

    accepted = validate_success(
        api.create_valuation_opinion(
            f.cr_opinion_payload(acquisition_id, after_fmv["version"]), VALUATION_ANALYST
        ),
        201,
    )
    assert accepted["opinion_type"] == OPINION_TYPE_COMMERCIAL_REASONABLENESS

    after_cr = read_acquisition(api, acquisition_id, VALUATION_ANALYST)
    a.assert_version_bumped_by(after_fmv, after_cr)
    a.assert_total_count(
        api.list_valuation_opinions({"acquisition_id": acquisition_id}, VALUATION_ANALYST),
        2,
    )


def test_reading_the_deal_never_spends_the_token_and_omitting_it_is_a_schema_error(
    api: ApiClient,
):
    """The token moves on writes only, and its absence is caught far above rank 13.

    PRD: "Two create operations are optimistically concurrent on the
    `Acquisition` aggregate, and both of them require a non-optional
    `expected_acquisition_version` field in the request body carrying the
    `version` the client last read from that acquisition."

    PRD: "Checked after existence and scope but before any state or business
    rule, so a stale reader is told to re-read rather than being handed a
    business error derived from a version it never observed."

    Design: Corner/cross_cutting_complexity_layers/stale_acquisition_version_on_opinion_create_returns_412
    """
    reset_clock(api)
    deal = diligence_deal(api)
    acquisition_id = deal["acquisition"]["id"]

    first = read_acquisition(api, acquisition_id, VALUATION_ANALYST)
    second = read_acquisition(api, acquisition_id, VALUATION_ANALYST)
    a.assert_version_unchanged(first, second)

    assert (
        PRECEDENCE_RANK[ApiErrorId.INVALID_REQUEST]
        < PRECEDENCE_RANK[ApiErrorId.STALE_ACQUISITION_VERSION]
    )
    versionless = f.without(
        f.market_fmv_payload(acquisition_id, first["version"]),
        "expected_acquisition_version",
    )
    validate_error(
        api.create_valuation_opinion(versionless, VALUATION_ANALYST),
        ApiErrorId.INVALID_REQUEST,
        400,
    )

    a.assert_total_count(
        api.list_valuation_opinions({"acquisition_id": acquisition_id}, VALUATION_ANALYST),
        0,
    )
    third = read_acquisition(api, acquisition_id, VALUATION_ANALYST)
    a.assert_version_unchanged(first, third)


# ---------------------------------------------------------------------------
# The designer papering two physicians must re-read between them
# ---------------------------------------------------------------------------


def test_the_designer_papering_two_physicians_must_re_read_between_them(api: ApiClient):
    """The first plan spends the token the second plan was built on.

    PRD: "A `POST /compensation-plans` request must likewise carry
    `expected_acquisition_version` equal to the target acquisition's current
    stored `version`, is rejected with `ERR_STALE_ACQUISITION_VERSION` and HTTP
    412 on any mismatch, and increments the acquisition's `version` by 1 on
    success."

    PRD: "Under `COMP_PER_WRVU` the compared value is `comp_per_wrvu_cents` and
    the quartiles are the specialty's dollars-per-work-RVU figures, so two plans
    with identical total cash compensation land at different percentiles
    whenever their work-RVU volumes differ."

    Design: Corner/cross_cutting_complexity_layers/stale_acquisition_version_on_plan_create_returns_412
    """
    reset_clock(api)
    acquisition = create_acquisition(api)
    acquisition_id = acquisition["id"]
    physician_a = create_physician(api, acquisition_id)
    physician_b = second_physician(api, acquisition_id)

    read_once = read_acquisition(api, acquisition_id, COMPENSATION_DESIGNER)
    stale_version = read_once["version"]

    plan_a = validate_success(
        api.create_compensation_plan(
            f.compensation_plan_payload(acquisition_id, stale_version, physician_a["id"]),
            COMPENSATION_DESIGNER,
        ),
        201,
    )

    plan_b_body = _wrvu_plan_payload(acquisition_id, stale_version, physician_b["id"])
    validate_error(
        api.create_compensation_plan(plan_b_body, COMPENSATION_DESIGNER),
        ApiErrorId.STALE_ACQUISITION_VERSION,
        412,
    )

    a.assert_total_count(
        api.list_compensation_plans({"acquisition_id": acquisition_id}, COMPENSATION_DESIGNER),
        1,
    )

    untouched_physician = get_success_data(
        api.get_physician(physician_b["id"], COMPENSATION_DESIGNER)
    )
    a.assert_status(untouched_physician, EMPLOYMENT_PROSPECTIVE, "employment_status")

    untouched_plan = get_success_data(
        api.get_compensation_plan(plan_a["id"], COMPENSATION_DESIGNER)
    )
    a.assert_common_fields(untouched_plan, 1)
    a.assert_status(untouched_plan, PLAN_STATUS_DRAFT)

    re_read = read_acquisition(api, acquisition_id, COMPENSATION_DESIGNER)
    plan_b = validate_success(
        api.create_compensation_plan(
            _wrvu_plan_payload(acquisition_id, re_read["version"], physician_b["id"]),
            COMPENSATION_DESIGNER,
        ),
        201,
    )
    a.assert_money_equals(
        plan_b["projected_total_cash_comp_cents"],
        PLAN_B_TOTAL_CASH_CENTS,
        "projected_total_cash_comp_cents",
    )
    a.assert_money_equals(
        plan_b["comp_per_wrvu_cents"], PLAN_B_PER_WRVU_CENTS, "comp_per_wrvu_cents"
    )
    assert plan_b["benchmark_basis"] == BENCHMARK_BASIS_COMP_PER_WRVU
    a.assert_percentage_equals(
        plan_b["benchmark_percentile"], PLAN_B_PERCENTILE, "benchmark_percentile"
    )

    after = read_acquisition(api, acquisition_id, COMPENSATION_DESIGNER)
    a.assert_version_bumped_by(re_read, after)


def test_a_version_one_greater_than_the_stored_value_is_equally_stale(api: ApiClient):
    """The comparison is equality, not a lower bound.

    PRD: "**Optimistic concurrency** — `expected_acquisition_version` equals the
    stored acquisition `version`, on `POST /valuation-opinions` and `POST
    /compensation-plans`."

    Design: Corner/cross_cutting_complexity_layers/stale_acquisition_version_on_plan_create_returns_412
    """
    reset_clock(api)
    acquisition = create_acquisition(api)
    acquisition_id = acquisition["id"]
    physician = create_physician(api, acquisition_id)

    stored = read_acquisition(api, acquisition_id, COMPENSATION_DESIGNER)
    ahead_of_the_server = f.compensation_plan_payload(
        acquisition_id, stored["version"] + 1, physician["id"]
    )
    validate_error(
        api.create_compensation_plan(ahead_of_the_server, COMPENSATION_DESIGNER),
        ApiErrorId.STALE_ACQUISITION_VERSION,
        412,
    )
    a.assert_total_count(
        api.list_compensation_plans({"acquisition_id": acquisition_id}, COMPENSATION_DESIGNER),
        0,
    )

    validate_success(
        api.create_compensation_plan(
            f.compensation_plan_payload(acquisition_id, stored["version"], physician["id"]),
            COMPENSATION_DESIGNER,
        ),
        201,
    )
    a.assert_total_count(
        api.list_compensation_plans({"acquisition_id": acquisition_id}, COMPENSATION_DESIGNER),
        1,
    )


# ---------------------------------------------------------------------------
# The token counts writes to the deal row from unrelated directions
# ---------------------------------------------------------------------------


def test_every_write_to_the_deal_row_moves_the_token_and_no_read_does(api: ApiClient):
    """Two status dimensions and one guarded child create each spend one version.

    PRD: "Each carries an `id` that is a server-minted UUID with no type prefix
    and no client-supplied component; a `created_at` and an `updated_at`, both
    ISO 8601 UTC instants with exactly three fractional digits; and a `version`,
    a plain integer that starts at 1 when the row is inserted and increases by
    exactly 1 on every mutation of that row."

    PRD: "`updated_at` is refreshed to the current logical instant on every
    mutation, and `version` is bumped, whether the mutation was requested
    directly or arrived as a cascade from another entity's transition."

    Design: Corner/cross_cutting_complexity_layers/acquisition_version_increments_on_every_write
    """
    reset_clock(api)
    fresh = create_acquisition(api)
    a.assert_common_fields(fresh, 1)
    acquisition_id = fresh["id"]
    create_physician(api, acquisition_id)

    before_status = read_acquisition(api, acquisition_id)
    advanced = validate_success(
        api.set_acquisition_status(
            acquisition_id,
            f.acquisition_status_payload(DEAL_STATUS_DILIGENCE),
            DEAL_LEAD,
        )
    )
    a.assert_status(advanced, DEAL_STATUS_DILIGENCE, "deal_status")
    a.assert_version_bumped_by(before_status, advanced)

    cleared = validate_success(
        api.set_compliance_clearance(
            acquisition_id,
            f.compliance_clearance_payload(CLEARANCE_CLEARED),
            COMPLIANCE_OFFICER,
        )
    )
    a.assert_status(cleared, CLEARANCE_CLEARED, "compliance_clearance")
    a.assert_version_bumped_by(advanced, cleared)

    validate_success(
        api.create_valuation_opinion(
            f.market_fmv_payload(acquisition_id, cleared["version"]), VALUATION_ANALYST
        ),
        201,
    )
    after_opinion = read_acquisition(api, acquisition_id)
    a.assert_version_bumped_by(cleared, after_opinion)

    for _ in range(3):
        a.assert_version_unchanged(after_opinion, read_acquisition(api, acquisition_id))

    rows = a.assert_total_count(api.list_acquisitions({}, DEAL_LEAD), 1)
    assert rows[0]["version"] == after_opinion["version"], (
        "the list projection must report the same token as the detail read"
    )


def test_a_clearance_officer_can_invalidate_a_designers_token(api: ApiClient):
    """The officer never touched a plan, yet the designer must re-read.

    PRD: "The effect is that a plan designer must re-read the acquisition after
    any preceding write, so no plan can be built on a superseded valuation, a
    stale retention pool balance, or a stale regulatory clearance value."

    Design: Corner/cross_cutting_complexity_layers/acquisition_version_increments_on_every_write
    """
    reset_clock(api)
    acquisition = create_acquisition(api)
    acquisition_id = acquisition["id"]
    physician = create_physician(api, acquisition_id)

    designers_read = read_acquisition(api, acquisition_id, COMPENSATION_DESIGNER)
    officers_write = set_clearance(api, acquisition_id, CLEARANCE_CLEARED)
    a.assert_version_bumped_by(designers_read, officers_write)

    validate_error(
        api.create_compensation_plan(
            f.compensation_plan_payload(
                acquisition_id, designers_read["version"], physician["id"]
            ),
            COMPENSATION_DESIGNER,
        ),
        ApiErrorId.STALE_ACQUISITION_VERSION,
        412,
    )
    a.assert_total_count(
        api.list_compensation_plans({"acquisition_id": acquisition_id}, COMPENSATION_DESIGNER),
        0,
    )

    re_read = read_acquisition(api, acquisition_id, COMPENSATION_DESIGNER)
    plan = validate_success(
        api.create_compensation_plan(
            f.compensation_plan_payload(acquisition_id, re_read["version"], physician["id"]),
            COMPENSATION_DESIGNER,
        ),
        201,
    )
    a.assert_common_fields(plan, 1)
    a.assert_version_bumped_by(re_read, read_acquisition(api, acquisition_id, COMPENSATION_DESIGNER))


# ---------------------------------------------------------------------------
# The retention pool as a cumulative ledger, exhausted to the cent
# ---------------------------------------------------------------------------


def _pool_committed_to_the_last_cent(api: ApiClient) -> dict:
    """A DILIGENCE deal whose 2,897,154-cent pool is committed in full.

    Three offers are drafted and extended in descending size, and a fourth is
    drafted afterwards — while the available balance already reads zero — so the
    fixture itself shows that drafting reserves nothing.
    """
    reset_clock(api)
    deal = diligence_deal(api, retention_pool_total_cents=POOL_TOTAL_EXACT_CENTS)
    acquisition_id = deal["acquisition"]["id"]

    drafted = {
        "pm": create_offer(api, acquisition_id, **PM_OFFER),
        "rn": create_offer(api, acquisition_id, **RN_OFFER),
        "ma": create_offer(api, acquisition_id, **MA_OFFER),
    }
    ledger = []
    for key in ("pm", "rn", "ma"):
        set_offer_status(api, drafted[key]["id"], OFFER_STATUS_EXTENDED)
        ledger.append(read_acquisition(api, acquisition_id))

    drafted["front_desk"] = create_offer(api, acquisition_id, **FRONT_DESK_OFFER)
    return {
        "acquisition_id": acquisition_id,
        "drafted": drafted,
        "ledger": ledger,
    }


def test_the_third_offer_commits_the_last_cent_and_the_fourth_is_refused(api: ApiClient):
    """The boundary is inclusive going in and exclusive coming out.

    PRD: "And the offer's `retention_bonus_cents` must not exceed the
    acquisition's `retention_pool_available_cents`, or the request is rejected
    with `ERR_RETENTION_POOL_EXCEEDED`."

    PRD: "Because the pool is checked at commitment time rather than at drafting
    time, an offer may quite legitimately be drafted for more than the pool can
    bear and only fail when someone tries to extend it."

    PRD: "Finally the result is clamped in a fixed order: the floor of 100000
    cents is applied first, raising any smaller award up to it, and the cap of
    1500000 cents is applied second, bringing any larger award down to it."

    Design: Corner/cross_cutting_complexity_layers/retention_pool_exactly_exhausted_then_one_more_offer_rejected
    """
    fixture = _pool_committed_to_the_last_cent(api)
    acquisition_id = fixture["acquisition_id"]
    drafted = fixture["drafted"]

    a.assert_money_equals(
        drafted["pm"]["offered_annual_wage_cents"], PM_WAGE_CENTS, "PRACTICE_MANAGER wage"
    )
    assert drafted["pm"]["wage_floor_applied"] is False
    a.assert_money_equals(
        drafted["pm"]["retention_bonus_cents"], PM_BONUS_CENTS, "PRACTICE_MANAGER award"
    )
    assert PM_AWARD_BEFORE_CAP_CENTS > PM_BONUS_CENTS, (
        "the practice manager's award is only interesting because the cap bites"
    )

    a.assert_money_equals(drafted["rn"]["offered_annual_wage_cents"], RN_WAGE_CENTS, "RN wage")
    assert drafted["rn"]["wage_floor_applied"] is False
    a.assert_money_equals(drafted["rn"]["retention_bonus_cents"], RN_BONUS_CENTS, "RN award")

    a.assert_money_equals(drafted["ma"]["offered_annual_wage_cents"], MA_WAGE_CENTS, "MA wage")
    assert drafted["ma"]["wage_floor_applied"] is True
    a.assert_money_equals(drafted["ma"]["retention_bonus_cents"], MA_BONUS_CENTS, "MA award")

    after_pm, after_rn, after_ma = fixture["ledger"]
    a.assert_retention_pool(
        after_pm,
        POOL_TOTAL_EXACT_CENTS,
        PM_BONUS_CENTS,
        POOL_TOTAL_EXACT_CENTS - PM_BONUS_CENTS,
    )
    a.assert_retention_pool(
        after_rn,
        POOL_TOTAL_EXACT_CENTS,
        PM_BONUS_CENTS + RN_BONUS_CENTS,
        MA_BONUS_CENTS,
    )
    a.assert_retention_pool(after_ma, POOL_TOTAL_EXACT_CENTS, POOL_TOTAL_EXACT_CENTS, 0)

    front_desk = drafted["front_desk"]
    a.assert_status(front_desk, OFFER_STATUS_DRAFT)
    a.assert_money_equals(
        front_desk["offered_annual_wage_cents"], FRONT_DESK_WAGE_CENTS, "FRONT_DESK wage"
    )
    assert front_desk["wage_floor_applied"] is True
    a.assert_money_equals(
        front_desk["retention_bonus_cents"], FRONT_DESK_BONUS_CENTS, "FRONT_DESK award"
    )
    assert FRONT_DESK_AWARD_BEFORE_FLOOR_CENTS < FRONT_DESK_BONUS_CENTS, (
        "the front desk award is only interesting because the floor lifts it"
    )
    a.assert_fields_null(front_desk, "extended_on", "accepted_on")

    validate_error(
        api.set_staff_transition_offer_status(
            front_desk["id"],
            f.offer_status_payload(OFFER_STATUS_EXTENDED),
            INTEGRATION_MANAGER,
        ),
        ApiErrorId.RETENTION_POOL_EXCEEDED,
        422,
    )

    unmoved = read_acquisition(api, acquisition_id)
    a.assert_retention_pool(unmoved, POOL_TOTAL_EXACT_CENTS, POOL_TOTAL_EXACT_CENTS, 0)
    still_drafted = get_success_data(
        api.get_staff_transition_offer(front_desk["id"], INTEGRATION_MANAGER)
    )
    a.assert_status(still_drafted, OFFER_STATUS_DRAFT)
    a.assert_fields_null(still_drafted, "extended_on")


def test_rescinding_the_third_offer_frees_exactly_what_it_committed(api: ApiClient):
    """Release the smallest commitment and the refused offer fits precisely.

    PRD: "All three subtract the offer's `retention_bonus_cents` from
    `retention_pool_committed_cents`, add the same amount back to
    `retention_pool_available_cents`, and recompute `hr_staffing_coverage_pct`."

    PRD: "Because the released amount is exactly the amount committed, the pool
    balance after a rescission is identical to the balance before the offer was
    ever extended."

    Design: Corner/cross_cutting_complexity_layers/retention_pool_exactly_exhausted_then_one_more_offer_rejected
    """
    fixture = _pool_committed_to_the_last_cent(api)
    acquisition_id = fixture["acquisition_id"]
    front_desk = fixture["drafted"]["front_desk"]
    ma_offer = fixture["drafted"]["ma"]

    validate_error(
        api.set_staff_transition_offer_status(
            front_desk["id"],
            f.offer_status_payload(OFFER_STATUS_EXTENDED),
            INTEGRATION_MANAGER,
        ),
        ApiErrorId.RETENTION_POOL_EXCEEDED,
        422,
    )

    rescinded = set_offer_status(api, ma_offer["id"], OFFER_STATUS_RESCINDED)
    a.assert_status(rescinded, OFFER_STATUS_RESCINDED)
    freed = read_acquisition(api, acquisition_id)
    a.assert_retention_pool(
        freed, POOL_TOTAL_EXACT_CENTS, POOL_AFTER_MA_RELEASE_CENTS, MA_BONUS_CENTS
    )

    extended = validate_success(
        api.set_staff_transition_offer_status(
            front_desk["id"],
            f.offer_status_payload(OFFER_STATUS_EXTENDED),
            INTEGRATION_MANAGER,
        )
    )
    a.assert_status(extended, OFFER_STATUS_EXTENDED)
    a.assert_date_only(extended["extended_on"], "extended_on")
    assert extended["extended_on"] == DEFAULT_CLOCK_DATE

    final = read_acquisition(api, acquisition_id)
    a.assert_retention_pool(
        final,
        POOL_TOTAL_EXACT_CENTS,
        POOL_AFTER_MA_RELEASE_CENTS + FRONT_DESK_BONUS_CENTS,
        MA_BONUS_CENTS - FRONT_DESK_BONUS_CENTS,
    )


# ---------------------------------------------------------------------------
# Coverage crossing exactly eighty completes a line nobody asked to complete
# ---------------------------------------------------------------------------


def test_the_fourth_acceptance_lands_on_exactly_eighty_and_completes_the_line(
    api: ApiClient,
):
    """A write to an offer finishes a checklist line and flips the posture.

    PRD: "`hr_staffing_coverage_pct` counts the offers that hold a seat — those
    in `EXTENDED` or in `ACCEPTED`, since an extended offer holds a seat as
    surely as it holds pool money — multiplies that count by 100, divides by
    `required_staff_headcount`, and rounds half up to exactly two decimal
    places."

    PRD: "It stamps `accepted_on` with the current logical date, recomputes
    `hr_staffing_coverage_pct`, sets the acquisition's readiness checklist line
    with `task_code` `HR_STAFFING_PLAN` to `COMPLETE` when the recomputed
    coverage is at least 80.00 percent and that line is currently in
    `IN_PROGRESS`, and recomputes the acquisition's `readiness_posture`."

    PRD: "Only when every blocking line is in `COMPLETE` or in `WAIVED` does the
    posture read `READY`."

    Design: Corner/cross_cutting_complexity_layers/hr_coverage_hitting_exactly_eighty_completes_the_staffing_task
    """
    reset_clock(api)
    deal = diligence_deal(api)
    acquisition_id = deal["acquisition"]["id"]

    task = in_progress_task(
        api, acquisition_id, task_code=TASK_HR_STAFFING_PLAN, due_on="2026-10-20"
    )
    a.assert_status(task, TASK_STATUS_IN_PROGRESS)

    for spec in (PM_OFFER, RN_OFFER, MA_OFFER):
        seated = create_offer(api, acquisition_id, **spec)
        set_offer_status(api, seated["id"], OFFER_STATUS_EXTENDED)
        set_offer_status(api, seated["id"], OFFER_STATUS_ACCEPTED)

    three_of_five = read_acquisition(api, acquisition_id)
    a.assert_percentage_equals(
        three_of_five["hr_staffing_coverage_pct"],
        COVERAGE_THREE_OF_FIVE_PCT,
        "hr_staffing_coverage_pct",
    )
    a.assert_status(read_task(api, task["id"]), TASK_STATUS_IN_PROGRESS)
    a.assert_status(three_of_five, POSTURE_AT_RISK, "readiness_posture")

    front_desk = create_offer(api, acquisition_id, **FRONT_DESK_OFFER)
    set_offer_status(api, front_desk["id"], OFFER_STATUS_EXTENDED)

    at_the_boundary = read_acquisition(api, acquisition_id)
    a.assert_percentage_equals(
        at_the_boundary["hr_staffing_coverage_pct"],
        COVERAGE_FOUR_OF_FIVE_PCT,
        "hr_staffing_coverage_pct",
    )
    a.assert_status(read_task(api, task["id"]), TASK_STATUS_IN_PROGRESS)
    a.assert_status(at_the_boundary, POSTURE_AT_RISK, "readiness_posture")

    accepted = validate_success(
        api.set_staff_transition_offer_status(
            front_desk["id"],
            f.offer_status_payload(OFFER_STATUS_ACCEPTED),
            INTEGRATION_MANAGER,
        )
    )
    a.assert_status(accepted, OFFER_STATUS_ACCEPTED)
    a.assert_date_only(accepted["accepted_on"], "accepted_on")
    assert accepted["accepted_on"] == DEFAULT_CLOCK_DATE

    a.assert_status(read_task(api, task["id"]), TASK_STATUS_COMPLETE)

    ready = read_acquisition(api, acquisition_id)
    a.assert_percentage_equals(
        ready["hr_staffing_coverage_pct"],
        HR_COVERAGE_COMPLETE_PCT,
        "hr_staffing_coverage_pct",
    )
    a.assert_status(ready, POSTURE_READY, "readiness_posture")
    a.assert_retention_pool(
        ready,
        STANDARD_POOL_TOTAL_CENTS,
        FOUR_SEAT_COMMITMENT_CENTS,
        STANDARD_POOL_TOTAL_CENTS - FOUR_SEAT_COMMITMENT_CENTS,
    )


def test_the_same_acceptance_leaves_a_line_that_was_never_started_open(api: ApiClient):
    """The cascade fires only from `IN_PROGRESS`, so an `OPEN` line stays open.

    PRD: "Otherwise, if any blocking line is in `OPEN` or in `IN_PROGRESS`, the
    posture is `AT_RISK`."

    PRD: "The `HR_STAFFING_PLAN` checklist line may only be completed while
    coverage is at least 80.00 percent, and exactly 80.00 is sufficient."

    Design: Corner/cross_cutting_complexity_layers/hr_coverage_hitting_exactly_eighty_completes_the_staffing_task
    """
    reset_clock(api)
    deal = diligence_deal(api)
    acquisition_id = deal["acquisition"]["id"]

    task = create_task(
        api, acquisition_id, task_code=TASK_HR_STAFFING_PLAN, due_on="2026-10-20"
    )
    a.assert_status(task, TASK_STATUS_OPEN)

    for spec in (PM_OFFER, RN_OFFER, MA_OFFER, FRONT_DESK_OFFER):
        seated = create_offer(api, acquisition_id, **spec)
        set_offer_status(api, seated["id"], OFFER_STATUS_EXTENDED)
        set_offer_status(api, seated["id"], OFFER_STATUS_ACCEPTED)

    at_the_boundary = read_acquisition(api, acquisition_id)
    a.assert_percentage_equals(
        at_the_boundary["hr_staffing_coverage_pct"],
        COVERAGE_FOUR_OF_FIVE_PCT,
        "hr_staffing_coverage_pct",
    )
    a.assert_status(read_task(api, task["id"]), TASK_STATUS_OPEN)
    a.assert_status(at_the_boundary, POSTURE_AT_RISK, "readiness_posture")

    started = set_task_status(api, task["id"], TASK_STATUS_IN_PROGRESS)
    a.assert_status(started, TASK_STATUS_IN_PROGRESS)
    completed = set_task_status(api, task["id"], TASK_STATUS_COMPLETE)
    a.assert_status(completed, TASK_STATUS_COMPLETE)
    a.assert_status(read_acquisition(api, acquisition_id), POSTURE_READY, "readiness_posture")


# ---------------------------------------------------------------------------
# Suspension reaches the drafts and stops there
# ---------------------------------------------------------------------------


def _suspended_deal(api: ApiClient) -> dict:
    """A DILIGENCE deal, one offer extended and one still drafted, then suspended."""
    reset_clock(api)
    deal = diligence_deal(api)
    acquisition_id = deal["acquisition"]["id"]
    assert deal["acquisition"]["compliance_clearance"] == CLEARANCE_PENDING

    live = create_offer(api, acquisition_id, **BILLER_OFFER)
    extended = set_offer_status(api, live["id"], OFFER_STATUS_EXTENDED)
    draft = create_offer(api, acquisition_id, **FRONT_DESK_OFFER)

    set_clearance(
        api, acquisition_id, CLEARANCE_FLAGGED, clearance_note=CLEARANCE_NOTE_FLAGGED
    )
    suspended = validate_success(
        api.set_compliance_clearance(
            acquisition_id,
            f.compliance_clearance_payload(
                CLEARANCE_SUSPENDED, clearance_note=CLEARANCE_NOTE_SUSPENDED
            ),
            COMPLIANCE_OFFICER,
        )
    )
    return {
        "acquisition_id": acquisition_id,
        "live": live,
        "extended": extended,
        "draft": draft,
        "suspended": suspended,
    }


def test_suspending_the_deal_rescinds_only_the_drafts_and_moves_no_money(api: ApiClient):
    """The cascade is status-selective, and the ledger does not notice it.

    PRD: "`FLAGGED → SUSPENDED` has no precondition and sets every staff
    transition offer still in `DRAFT` to `RESCINDED` — a draft offer reserves no
    pool money, so nothing is released."

    PRD: "A drafted offer lands in `DRAFT`, with `extended_on` and `accepted_on`
    both null, and the retention pool is untouched — a draft reserves nothing."

    Design: Corner/cross_cutting_complexity_layers/suspension_cascade_rescinds_the_draft_offers_only
    """
    fixture = _suspended_deal(api)
    acquisition_id = fixture["acquisition_id"]

    a.assert_money_equals(
        fixture["live"]["offered_annual_wage_cents"], BILLER_WAGE_CENTS, "BILLER wage"
    )
    assert fixture["live"]["wage_floor_applied"] is False
    a.assert_money_equals(
        fixture["live"]["retention_bonus_cents"], BILLER_BONUS_CENTS, "BILLER award"
    )

    a.assert_status(fixture["suspended"], CLEARANCE_SUSPENDED, "compliance_clearance")

    cascaded = get_success_data(
        api.get_staff_transition_offer(fixture["draft"]["id"], INTEGRATION_MANAGER)
    )
    a.assert_status(cascaded, OFFER_STATUS_RESCINDED)
    a.assert_fields_null(cascaded, "extended_on", "accepted_on")

    untouched = get_success_data(
        api.get_staff_transition_offer(fixture["live"]["id"], INTEGRATION_MANAGER)
    )
    a.assert_status(untouched, OFFER_STATUS_EXTENDED)
    a.assert_money_equals(
        untouched["retention_bonus_cents"], BILLER_BONUS_CENTS, "BILLER award"
    )

    a.assert_retention_pool(
        read_acquisition(api, acquisition_id),
        STANDARD_POOL_TOTAL_CENTS,
        BILLER_BONUS_CENTS,
        STANDARD_POOL_TOTAL_CENTS - BILLER_BONUS_CENTS,
    )


def test_the_freeze_spares_the_checklist_and_lifting_it_revives_nothing(api: ApiClient):
    """The suspension blocks the offer desk, not the remediation work.

    PRD: "Whenever an acquisition's `compliance_clearance` is `FLAGGED` or
    `SUSPENDED`, the deal is frozen for new work."

    PRD: "And `POST /compensation-plans/{planId}/status`, `POST
    /readiness-tasks`, and `POST /readiness-tasks/{taskId}/status` are exempt
    because remediating the compensation defect and the day-one checklist is
    precisely the work that a flagged deal needs to do."

    PRD: "`SUSPENDED → FLAGGED` has no precondition and no side effect, and is
    the only way out of suspension."

    Design: Corner/cross_cutting_complexity_layers/suspension_cascade_rescinds_the_draft_offers_only
    """
    fixture = _suspended_deal(api)
    acquisition_id = fixture["acquisition_id"]

    validate_error(
        api.create_staff_transition_offer(
            f.staff_offer_payload(acquisition_id, **MA_OFFER), INTEGRATION_MANAGER
        ),
        ApiErrorId.COMPLIANCE_CLEARANCE_BLOCKED,
        403,
    )
    validate_error(
        api.set_staff_transition_offer_status(
            fixture["live"]["id"],
            f.offer_status_payload(OFFER_STATUS_ACCEPTED),
            INTEGRATION_MANAGER,
        ),
        ApiErrorId.COMPLIANCE_CLEARANCE_BLOCKED,
        403,
    )

    assert (
        PRECEDENCE_RANK[ApiErrorId.STALE_ACQUISITION_VERSION]
        < PRECEDENCE_RANK[ApiErrorId.COMPLIANCE_CLEARANCE_BLOCKED]
    )
    current = read_acquisition(api, acquisition_id, VALUATION_ANALYST)
    validate_error(
        api.create_valuation_opinion(
            f.market_fmv_payload(acquisition_id, current["version"]), VALUATION_ANALYST
        ),
        ApiErrorId.COMPLIANCE_CLEARANCE_BLOCKED,
        403,
    )

    validate_success(api.get_acquisition(acquisition_id, INTEGRATION_MANAGER))
    validate_success(
        api.create_readiness_task(
            f.readiness_task_payload(acquisition_id, task_code=TASK_COMPLIANCE_TRAINING),
            INTEGRATION_MANAGER,
        ),
        201,
    )

    back_to_flagged = set_clearance(
        api, acquisition_id, CLEARANCE_FLAGGED, clearance_note=CLEARANCE_NOTE_FLAGGED
    )
    a.assert_status(back_to_flagged, CLEARANCE_FLAGGED, "compliance_clearance")
    a.assert_status(
        get_success_data(
            api.get_staff_transition_offer(fixture["draft"]["id"], INTEGRATION_MANAGER)
        ),
        OFFER_STATUS_RESCINDED,
    )
    validate_error(
        api.create_staff_transition_offer(
            f.staff_offer_payload(acquisition_id, **MA_OFFER), INTEGRATION_MANAGER
        ),
        ApiErrorId.COMPLIANCE_CLEARANCE_BLOCKED,
        403,
    )

    lifted = set_clearance(
        api, acquisition_id, CLEARANCE_CLEARED, clearance_note=CLEARANCE_NOTE_LIFTED
    )
    a.assert_status(lifted, CLEARANCE_CLEARED, "compliance_clearance")
    validate_success(
        api.create_staff_transition_offer(
            f.staff_offer_payload(acquisition_id, **MA_OFFER), INTEGRATION_MANAGER
        ),
        201,
    )
    a.assert_status(
        get_success_data(
            api.get_staff_transition_offer(fixture["draft"]["id"], INTEGRATION_MANAGER)
        ),
        OFFER_STATUS_RESCINDED,
    )
