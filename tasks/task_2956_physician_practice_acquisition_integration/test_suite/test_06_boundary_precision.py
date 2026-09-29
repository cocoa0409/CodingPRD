"""Boundaries where one unit either side of the line changes the outcome.

The reconciliation floor is compared against a truncated basis-point ratio, so
one record short of the floor cannot round its way over it. The readiness posture
is derived from a collection that may be empty, and an empty collection is not
vacuously satisfied.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import (
    BATCH_ACTION_REQUEUE,
    BATCH_STATUS_FAILED,
    BATCH_STATUS_LOADED,
    BATCH_STATUS_RECONCILED,
    DOMAIN_BY_TASK_CODE,
    POSTURE_AT_RISK,
    POSTURE_BLOCKED,
    POSTURE_READY,
    TASK_COMPLIANCE_TRAINING,
    TASK_REVENUE_CYCLE_GO_LIVE,
    TASK_STATUS_COMPLETE,
    TASK_STATUS_IN_PROGRESS,
    TASK_STATUS_OPEN,
)
from test_helpers.fixtures import (
    INTEGRATION_MANAGER,
    create_acquisition,
    create_task,
    loaded_batch,
    read_acquisition,
    reconcile_batch,
    reset_clock,
    set_task_status,
)

RECORD_COUNT = 20_000
# 19,900 of 20,000 is exactly the floor; 19,899 truncates to one basis point under.
ON_FLOOR_VALIDATED = 19_900
ON_FLOOR_DEFECTS = 100
FLOOR_BPS = 9_950
UNDER_FLOOR_VALIDATED = 19_899
UNDER_FLOOR_DEFECTS = 101
UNDER_FLOOR_BPS = 9_949


def test_a_rate_exactly_on_the_floor_reconciles(api: ApiClient):
    """The floor comparison is inclusive, so landing exactly on it succeeds.

    PRD: "When the computed rate is at or above 9950 basis points, the batch
    takes `LOADED → RECONCILED`."

    Design: Difficulty/boundary_precision_check/ehr_match_rate_exactly_9950_bps_reconciles
    """
    reset_clock(api)
    acquisition = create_acquisition(api)
    batch = loaded_batch(api, acquisition["id"], batch_label="CHARTS-HI", record_count=RECORD_COUNT)
    a.assert_status(batch, BATCH_STATUS_LOADED)

    reconciled = reconcile_batch(api, batch["id"], ON_FLOOR_VALIDATED, ON_FLOOR_DEFECTS)

    assert reconciled["match_rate_bps"] == FLOOR_BPS
    a.assert_status(reconciled, BATCH_STATUS_RECONCILED)
    assert reconciled["retry_count"] == 0
    assert reconciled["unprocessed_count"] == 0
    assert (
        reconciled["validated_count"] + reconciled["defect_count"] + reconciled["unprocessed_count"]
        == RECORD_COUNT
    )


def test_one_record_short_truncates_below_the_floor_and_fails(api: ApiClient):
    """The rate is truncated, never rounded, so 9949.5 reads 9949 and fails.

    PRD: "The match rate is then computed as `validated_count` multiplied by
    10000, divided by `record_count`, and **truncated** toward zero to a whole
    number of basis points; it is never rounded up, so a batch cannot round its
    way to the reconciliation floor."

    Design: Difficulty/boundary_precision_check/ehr_match_rate_exactly_9950_bps_reconciles
    """
    reset_clock(api)
    acquisition = create_acquisition(api)
    batch = loaded_batch(api, acquisition["id"], batch_label="CHARTS-LO", record_count=RECORD_COUNT)

    failed = reconcile_batch(api, batch["id"], UNDER_FLOOR_VALIDATED, UNDER_FLOOR_DEFECTS)

    assert failed["match_rate_bps"] == UNDER_FLOOR_BPS
    assert failed["match_rate_bps"] != FLOOR_BPS
    a.assert_status(failed, BATCH_STATUS_FAILED)
    assert failed["retry_count"] == 1


def test_a_reconciled_batch_refuses_a_requeue(api: ApiClient):
    """Crossing the floor is final: the reconciled batch has no exit.

    PRD: "`RECONCILED` and `ABORTED` are the batch's terminal states."

    Design: Difficulty/boundary_precision_check/ehr_match_rate_exactly_9950_bps_reconciles
    """
    reset_clock(api)
    acquisition = create_acquisition(api)
    batch = loaded_batch(api, acquisition["id"], batch_label="CHARTS-HI", record_count=RECORD_COUNT)
    reconcile_batch(api, batch["id"], ON_FLOOR_VALIDATED, ON_FLOOR_DEFECTS)

    rejected = api.progress_ehr_migration_batch(
        batch["id"], f.batch_progress_payload(BATCH_ACTION_REQUEUE), INTEGRATION_MANAGER
    )

    validate_error(rejected, ApiErrorId.INVALID_STATE_TRANSITION, 409)


def test_the_conservation_bound_is_enforced_only_above_the_record_count(api: ApiClient):
    """Counts summing exactly to the record count are accepted; a larger sum is not.

    PRD: "In every branch the sum of `validated_count` and `defect_count` must
    not exceed `record_count`, or the request fails with
    `ERR_MIGRATION_COUNT_INVALID` — conservation is enforced on input so that
    `unprocessed_count` can never go negative."

    Design: Difficulty/boundary_precision_check/ehr_match_rate_exactly_9950_bps_reconciles
    """
    reset_clock(api)
    acquisition = create_acquisition(api)
    on_bound = loaded_batch(
        api, acquisition["id"], batch_label="CHARTS-BOUND", record_count=RECORD_COUNT
    )
    over_bound = loaded_batch(
        api, acquisition["id"], batch_label="CHARTS-OVER", record_count=RECORD_COUNT
    )

    accepted = reconcile_batch(api, on_bound["id"], ON_FLOOR_VALIDATED, ON_FLOOR_DEFECTS)
    a.assert_status(accepted, BATCH_STATUS_RECONCILED)

    rejected = api.progress_ehr_migration_batch(
        over_bound["id"],
        f.reconcile_payload(19_950, 100),
        INTEGRATION_MANAGER,
    )
    validate_error(rejected, ApiErrorId.MIGRATION_COUNT_INVALID, 422)


# ---------------------------------------------------------------------------
# The empty blocking-checklist boundary
# ---------------------------------------------------------------------------


def test_an_acquisition_with_no_blocking_lines_reads_blocked(api: ApiClient):
    """A non-blocking line does not populate the set the posture is derived from.

    PRD: "If the acquisition has no blocking lines at all, `readiness_posture` is
    `BLOCKED` — an empty checklist is treated as an unbuilt checklist rather than
    as a vacuously satisfied one, which is why a brand-new acquisition starts
    `BLOCKED`."

    Design: Difficulty/boundary_precision_check/zero_blocking_readiness_tasks_yields_blocked_not_ready
    """
    reset_clock(api)
    acquisition = create_acquisition(api)
    assert acquisition["readiness_posture"] == POSTURE_BLOCKED

    task = create_task(
        api,
        acquisition["id"],
        task_code=TASK_REVENUE_CYCLE_GO_LIVE,
        is_blocking=False,
        due_on="2026-10-20",
    )

    assert task["is_blocking"] is False
    a.assert_status(task, TASK_STATUS_OPEN)
    assert task["domain"] == DOMAIN_BY_TASK_CODE[TASK_REVENUE_CYCLE_GO_LIVE]

    refreshed = read_acquisition(api, acquisition["id"])
    assert refreshed["readiness_posture"] == POSTURE_BLOCKED


def test_completing_a_non_blocking_line_never_reaches_ready(api: ApiClient):
    """Driving the irrelevant line to completion leaves the posture where it was.

    PRD: "Only lines with `is_blocking` true participate; non-blocking lines
    never affect the posture, in any status."

    Design: Difficulty/boundary_precision_check/zero_blocking_readiness_tasks_yields_blocked_not_ready
    """
    reset_clock(api)
    acquisition = create_acquisition(api)
    task = create_task(
        api,
        acquisition["id"],
        task_code=TASK_REVENUE_CYCLE_GO_LIVE,
        is_blocking=False,
        due_on="2026-10-20",
    )

    set_task_status(api, task["id"], TASK_STATUS_IN_PROGRESS)
    completed = set_task_status(api, task["id"], TASK_STATUS_COMPLETE)
    a.assert_status(completed, TASK_STATUS_COMPLETE)

    refreshed = read_acquisition(api, acquisition["id"])
    assert refreshed["readiness_posture"] == POSTURE_BLOCKED
    assert refreshed["readiness_posture"] != POSTURE_READY


def test_the_first_blocking_line_moves_the_posture_to_at_risk_then_ready(api: ApiClient):
    """One blocking line makes the set non-empty and drives the whole derivation.

    PRD: "Otherwise, if any blocking line is in `OPEN` or in `IN_PROGRESS`, the
    posture is `AT_RISK`."

    Design: Difficulty/boundary_precision_check/zero_blocking_readiness_tasks_yields_blocked_not_ready
    """
    reset_clock(api)
    acquisition = create_acquisition(api)
    non_blocking = create_task(
        api,
        acquisition["id"],
        task_code=TASK_REVENUE_CYCLE_GO_LIVE,
        is_blocking=False,
        due_on="2026-10-20",
    )
    set_task_status(api, non_blocking["id"], TASK_STATUS_IN_PROGRESS)
    set_task_status(api, non_blocking["id"], TASK_STATUS_COMPLETE)

    blocking = create_task(
        api, acquisition["id"], task_code=TASK_COMPLIANCE_TRAINING, is_blocking=True
    )
    assert blocking["is_blocking"] is True
    at_risk = read_acquisition(api, acquisition["id"])
    assert at_risk["readiness_posture"] == POSTURE_AT_RISK

    set_task_status(api, blocking["id"], TASK_STATUS_IN_PROGRESS)
    set_task_status(api, blocking["id"], TASK_STATUS_COMPLETE)

    ready = read_acquisition(api, acquisition["id"])
    assert ready["readiness_posture"] == POSTURE_READY


def test_a_second_line_with_the_same_code_is_rejected(api: ApiClient):
    """The checklist admits at most one line per code, blocking or not.

    PRD: "`task_code` is one of `HR_STAFFING_PLAN`, `PAYER_CREDENTIALING`,
    `IT_DATA_MIGRATION`, `REVENUE_CYCLE_GO_LIVE`, `COMPLIANCE_TRAINING`, or
    `PATIENT_NOTIFICATION`, and at most one line per code may exist on a given
    acquisition — a second attempt at the same code is `ERR_DUPLICATE_TASK_CODE`."

    Design: Difficulty/boundary_precision_check/zero_blocking_readiness_tasks_yields_blocked_not_ready
    """
    reset_clock(api)
    acquisition = create_acquisition(api)
    create_task(
        api,
        acquisition["id"],
        task_code=TASK_REVENUE_CYCLE_GO_LIVE,
        is_blocking=False,
        due_on="2026-10-20",
    )

    duplicate = api.create_readiness_task(
        f.readiness_task_payload(
            acquisition["id"],
            task_code=TASK_REVENUE_CYCLE_GO_LIVE,
            is_blocking=True,
            due_on="2026-10-21",
        ),
        INTEGRATION_MANAGER,
    )

    validate_error(duplicate, ApiErrorId.DUPLICATE_TASK_CODE, 409)
    still_blocked = validate_success(api.get_acquisition(acquisition["id"], INTEGRATION_MANAGER))
    assert still_blocked["readiness_posture"] == POSTURE_BLOCKED
