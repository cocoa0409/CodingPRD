"""Conserved quantities that a compensating action restores exactly.

The retention pool conserves money: committed plus available always equals the
authorised total, and a rescission releases precisely what the extension
committed. The migration batch conserves record counts: validated plus defect
plus unprocessed always equals the original record count, and a requeue returns
the whole batch to its post-staging counters while the retry tally advances.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import (
    BATCH_ACTION_EXTRACT,
    BATCH_ACTION_LOAD,
    BATCH_ACTION_REQUEUE,
    BATCH_STATUS_ABORTED,
    BATCH_STATUS_FAILED,
    BATCH_STATUS_STAGED,
    OFFER_STATUS_DRAFT,
    OFFER_STATUS_EXTENDED,
    OFFER_STATUS_RESCINDED,
    ROLE_CODE_BILLER,
    ROLE_CODE_PRACTICE_MANAGER,
)
from test_helpers.fixtures import (
    INTEGRATION_MANAGER,
    create_acquisition,
    create_offer,
    diligence_deal,
    loaded_batch,
    progress_batch,
    read_acquisition,
    reconcile_batch,
    reset_clock,
    set_offer_status,
)

POOL_TOTAL_CENTS = 3_000_000

# A biller on 5,282,350 cents: a 300 basis point uplift rounds to 158,471 and a
# half-rate buy-out of 104 hours rounds to 132,059, so the harmonised sum of
# 5,572,880 clears the 4,400,000 floor on its own.
BILLER_LEGACY_WAGE_CENTS = 5_282_350
BILLER_PTO_HOURS = 104
BILLER_SERVICE_MONTHS = 84
BILLER_OFFERED_WAGE_CENTS = 5_572_880
# 800 basis points of that wage rounds to 445,830, and the biller's 12,500 basis
# point criticality premium rounds 557,287.5 up to 557,288.
BILLER_BONUS_CENTS = 557_288
POOL_AVAILABLE_AFTER_BILLER_CENTS = 2_442_712

# A practice manager's raw award exceeds the cap, so it is clamped.
MANAGER_LEGACY_WAGE_CENTS = 12_000_000
MANAGER_PTO_HOURS = 160
MANAGER_SERVICE_MONTHS = 200
MANAGER_BONUS_CENTS = 1_500_000
POOL_AVAILABLE_AFTER_MANAGER_CENTS = 1_500_000

OFFER_EXPIRES_ON = "2026-09-15"


def _diligence_deal_with_a_drafted_biller_offer(api: ApiClient):
    reset_clock(api)
    deal = diligence_deal(api, retention_pool_total_cents=POOL_TOTAL_CENTS)
    deal["offer"] = create_offer(
        api,
        deal["acquisition"]["id"],
        staff_member_name="Dana Whitfield",
        role_code=ROLE_CODE_BILLER,
        legacy_annual_wage_cents=BILLER_LEGACY_WAGE_CENTS,
        legacy_pto_hours=BILLER_PTO_HOURS,
        credited_service_months=BILLER_SERVICE_MONTHS,
        offer_expires_on=OFFER_EXPIRES_ON,
    )
    return deal


def test_a_rescission_restores_the_pool_to_its_pre_extension_reading(api: ApiClient):
    """Committed plus available equals the total at every one of the three readings.

    PRD: "After every offer transition the invariant holds that the total equals
    the committed amount plus the available amount, and because every
    non-acceptance exit releases exactly the amount that was committed, the pool
    balance after a rescission is identical to the balance before the offer was
    extended, with no residue."

    Design: Difficulty/compensating_invariant/retention_pool_restored_exactly_after_offer_rescind
    """
    deal = _diligence_deal_with_a_drafted_biller_offer(api)
    acquisition_id = deal["acquisition"]["id"]

    a.assert_status(deal["offer"], OFFER_STATUS_DRAFT)
    a.assert_money_equals(
        deal["offer"]["offered_annual_wage_cents"],
        BILLER_OFFERED_WAGE_CENTS,
        "offered_annual_wage_cents",
    )
    assert deal["offer"]["wage_floor_applied"] is False
    a.assert_money_equals(
        deal["offer"]["retention_bonus_cents"], BILLER_BONUS_CENTS, "retention_bonus_cents"
    )
    at_draft = read_acquisition(api, acquisition_id)
    a.assert_retention_pool(at_draft, POOL_TOTAL_CENTS, 0, POOL_TOTAL_CENTS)

    set_offer_status(api, deal["offer"]["id"], OFFER_STATUS_EXTENDED)
    at_extended = read_acquisition(api, acquisition_id)
    a.assert_retention_pool(
        at_extended, POOL_TOTAL_CENTS, BILLER_BONUS_CENTS, POOL_AVAILABLE_AFTER_BILLER_CENTS
    )

    set_offer_status(
        api,
        deal["offer"]["id"],
        OFFER_STATUS_RESCINDED,
        note="Position eliminated in the day-one org chart.",
    )
    at_rescinded = read_acquisition(api, acquisition_id)
    a.assert_retention_pool(at_rescinded, POOL_TOTAL_CENTS, 0, POOL_TOTAL_CENTS)
    assert (
        at_rescinded["retention_pool_committed_cents"] == at_draft["retention_pool_committed_cents"]
    )
    assert (
        at_rescinded["retention_pool_available_cents"] == at_draft["retention_pool_available_cents"]
    )


def test_the_rescinded_offer_keeps_its_award_and_cannot_release_it_twice(api: ApiClient):
    """The release is idempotent by refusal, not by repetition.

    PRD: "`ACCEPTED`, `DECLINED`, `RESCINDED`, and `EXPIRED` are all terminal."

    Design: Difficulty/compensating_invariant/retention_pool_restored_exactly_after_offer_rescind
    """
    deal = _diligence_deal_with_a_drafted_biller_offer(api)
    offer_id = deal["offer"]["id"]
    set_offer_status(api, offer_id, OFFER_STATUS_EXTENDED)
    rescinded = set_offer_status(api, offer_id, OFFER_STATUS_RESCINDED)

    a.assert_status(rescinded, OFFER_STATUS_RESCINDED)
    a.assert_money_equals(
        rescinded["retention_bonus_cents"], BILLER_BONUS_CENTS, "retention_bonus_cents"
    )

    again = api.set_staff_transition_offer_status(
        offer_id, f.offer_status_payload(OFFER_STATUS_RESCINDED), INTEGRATION_MANAGER
    )
    validate_error(again, ApiErrorId.INVALID_STATE_TRANSITION, 409)

    re_extend = api.set_staff_transition_offer_status(
        offer_id, f.offer_status_payload(OFFER_STATUS_EXTENDED), INTEGRATION_MANAGER
    )
    validate_error(re_extend, ApiErrorId.INVALID_STATE_TRANSITION, 409)

    ledger = read_acquisition(api, deal["acquisition"]["id"])
    a.assert_retention_pool(ledger, POOL_TOTAL_CENTS, 0, POOL_TOTAL_CENTS)


def test_the_released_capacity_is_genuinely_reusable_by_another_offer(api: ApiClient):
    """The restored balance is spendable, not merely reported.

    PRD: "On success the offer's `retention_bonus_cents` is added to
    `retention_pool_committed_cents` and subtracted from
    `retention_pool_available_cents`, `extended_on` is stamped with the current
    logical date, and the acquisition's `hr_staffing_coverage_pct` is recomputed."

    Design: Difficulty/compensating_invariant/retention_pool_restored_exactly_after_offer_rescind
    """
    deal = _diligence_deal_with_a_drafted_biller_offer(api)
    acquisition_id = deal["acquisition"]["id"]
    set_offer_status(api, deal["offer"]["id"], OFFER_STATUS_EXTENDED)
    set_offer_status(api, deal["offer"]["id"], OFFER_STATUS_RESCINDED)

    manager = create_offer(
        api,
        acquisition_id,
        staff_member_name="Grace Okonkwo",
        role_code=ROLE_CODE_PRACTICE_MANAGER,
        legacy_annual_wage_cents=MANAGER_LEGACY_WAGE_CENTS,
        legacy_pto_hours=MANAGER_PTO_HOURS,
        credited_service_months=MANAGER_SERVICE_MONTHS,
        offer_expires_on=OFFER_EXPIRES_ON,
    )
    a.assert_money_equals(
        manager["retention_bonus_cents"], MANAGER_BONUS_CENTS, "retention_bonus_cents"
    )

    extended = set_offer_status(api, manager["id"], OFFER_STATUS_EXTENDED)
    a.assert_status(extended, OFFER_STATUS_EXTENDED)
    assert extended["extended_on"] == "2026-08-01"

    ledger = read_acquisition(api, acquisition_id)
    a.assert_retention_pool(
        ledger, POOL_TOTAL_CENTS, MANAGER_BONUS_CENTS, POOL_AVAILABLE_AFTER_MANAGER_CENTS
    )


# ---------------------------------------------------------------------------
# Record counts conserved across a failed reconcile and its requeue
# ---------------------------------------------------------------------------

RECORD_COUNT = 20_000
FAILING_VALIDATED = 19_899
FAILING_DEFECTS = 101
FAILING_RATE_BPS = 9_949
OVER_BOUND_VALIDATED = 19_900
OVER_BOUND_DEFECTS = 200


def _assert_counts_conserved(batch, validated: int, defects: int, unprocessed: int) -> None:
    assert batch["record_count"] == RECORD_COUNT
    assert batch["validated_count"] == validated
    assert batch["defect_count"] == defects
    assert batch["unprocessed_count"] == unprocessed
    assert validated + defects + unprocessed == RECORD_COUNT
    assert (
        batch["validated_count"] + batch["defect_count"] + batch["unprocessed_count"]
        == batch["record_count"]
    )


def _loaded_batch(api: ApiClient):
    reset_clock(api)
    acquisition = create_acquisition(api)
    return loaded_batch(
        api, acquisition["id"], batch_label="CHARTS-A", record_count=RECORD_COUNT
    )


def test_a_failed_reconcile_conserves_the_record_count(api: ApiClient):
    """The two processed buckets absorb the whole batch and nothing goes missing.

    PRD: "`unprocessed_count` is always `record_count` minus `validated_count`
    minus `defect_count` — it is the conserved remainder, and the invariant that
    validated plus defect plus unprocessed equals the original record count holds
    after every action on the batch."

    Design: Difficulty/compensating_invariant/ehr_record_count_conserved_across_fail_and_requeue
    """
    batch = _loaded_batch(api)
    _assert_counts_conserved(batch, 0, 0, RECORD_COUNT)

    failed = reconcile_batch(api, batch["id"], FAILING_VALIDATED, FAILING_DEFECTS)

    _assert_counts_conserved(failed, FAILING_VALIDATED, FAILING_DEFECTS, 0)
    assert failed["match_rate_bps"] == FAILING_RATE_BPS
    a.assert_status(failed, BATCH_STATUS_FAILED)
    assert failed["retry_count"] == 1


def test_requeue_compensates_the_counters_but_not_the_retry_tally(api: ApiClient):
    """The batch returns to its post-staging counters while the tally advances.

    PRD: "`REQUEUE` moves `FAILED → STAGED`, resetting `validated_count` and
    `defect_count` to 0 — which restores `unprocessed_count` to exactly
    `record_count` — and resetting `match_rate_bps` to 0."

    Design: Difficulty/compensating_invariant/ehr_record_count_conserved_across_fail_and_requeue
    """
    batch = _loaded_batch(api)
    reconcile_batch(api, batch["id"], FAILING_VALIDATED, FAILING_DEFECTS)

    requeued = progress_batch(
        api,
        batch["id"],
        BATCH_ACTION_REQUEUE,
        note="Remapping the allergy dictionary before the second pass.",
    )

    _assert_counts_conserved(requeued, 0, 0, RECORD_COUNT)
    assert requeued["match_rate_bps"] == 0
    a.assert_status(requeued, BATCH_STATUS_STAGED)
    assert requeued["retry_count"] == 1


def test_a_reconcile_that_would_break_the_invariant_is_refused(api: ApiClient):
    """Conservation is enforced on input, so the counters never take the bad write.

    PRD: "In every branch the sum of `validated_count` and `defect_count` must not
    exceed `record_count`, or the request fails with `ERR_MIGRATION_COUNT_INVALID`
    — conservation is enforced on input so that `unprocessed_count` can never go
    negative."

    Design: Difficulty/compensating_invariant/ehr_record_count_conserved_across_fail_and_requeue
    """
    batch = _loaded_batch(api)
    reconcile_batch(api, batch["id"], FAILING_VALIDATED, FAILING_DEFECTS)
    progress_batch(api, batch["id"], BATCH_ACTION_REQUEUE)
    progress_batch(api, batch["id"], BATCH_ACTION_EXTRACT)
    reloaded = progress_batch(api, batch["id"], BATCH_ACTION_LOAD)
    _assert_counts_conserved(reloaded, 0, 0, RECORD_COUNT)

    rejected = api.progress_ehr_migration_batch(
        batch["id"],
        f.reconcile_payload(OVER_BOUND_VALIDATED, OVER_BOUND_DEFECTS),
        INTEGRATION_MANAGER,
    )

    validate_error(rejected, ApiErrorId.MIGRATION_COUNT_INVALID, 422)
    assert OVER_BOUND_VALIDATED + OVER_BOUND_DEFECTS > RECORD_COUNT
    unchanged = validate_success(api.get_ehr_migration_batch(batch["id"], INTEGRATION_MANAGER))
    _assert_counts_conserved(unchanged, 0, 0, RECORD_COUNT)
    assert unchanged["match_rate_bps"] == 0
    assert unchanged["retry_count"] == 1


def test_the_third_failing_cycle_aborts_with_the_invariant_still_holding(api: ApiClient):
    """The retry tally is the one figure the compensation deliberately does not restore.

    PRD: "The retry allowance is therefore two failures, with the third failing
    reconcile abandoning the batch outright."

    Design: Difficulty/compensating_invariant/ehr_record_count_conserved_across_fail_and_requeue
    """
    batch = _loaded_batch(api)
    batch_id = batch["id"]

    for expected_retries in (1, 2):
        failed = reconcile_batch(api, batch_id, FAILING_VALIDATED, FAILING_DEFECTS)
        a.assert_status(failed, BATCH_STATUS_FAILED)
        assert failed["retry_count"] == expected_retries
        _assert_counts_conserved(failed, FAILING_VALIDATED, FAILING_DEFECTS, 0)
        progress_batch(api, batch_id, BATCH_ACTION_REQUEUE)
        progress_batch(api, batch_id, BATCH_ACTION_EXTRACT)
        progress_batch(api, batch_id, BATCH_ACTION_LOAD)

    aborted = reconcile_batch(api, batch_id, FAILING_VALIDATED, FAILING_DEFECTS)

    a.assert_status(aborted, BATCH_STATUS_ABORTED)
    assert aborted["retry_count"] == 3
    _assert_counts_conserved(aborted, FAILING_VALIDATED, FAILING_DEFECTS, 0)
