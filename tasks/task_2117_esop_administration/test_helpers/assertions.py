"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

PLAN_STATUSES = ["OPEN", "VALUATION_PENDING", "ALLOCATION_LOCKED", "FROZEN"]
PARTICIPANT_STATUSES = ["ACTIVE", "TERMINATED", "RETIRED", "DECEASED", "DISTRIBUTED"]
VALUATION_STATUSES = ["SUBMITTED", "CHALLENGED", "APPROVED", "REJECTED", "SUPERSEDED"]
LOAN_STATUSES = ["AMORTIZING", "REPAID"]
RUN_STATUSES = ["DRAFT", "FINALIZED", "VOID"]
FORFEITURE_STATUSES = ["PENDING_REALLOCATION", "REALLOCATED"]
APPROVAL_STATUSES = ["REQUESTED", "APPROVED", "DENIED"]
PAYMENT_STATUSES = ["NOT_STARTED", "IN_PROGRESS", "COMPLETED"]
INSTALLMENT_STATUSES = ["SCHEDULED", "PAID", "CANCELLED"]
EXERCISE_STATUSES = ["PENDING", "FUNDED", "DEFERRED", "SETTLED", "CANCELLED"]
PRIORITY_CLASSES = ["DEATH", "RETIREMENT_DISABILITY", "TERMINATION", "DIVERSIFICATION"]
DELIVERY_STATUSES = ["GENERATED", "DELIVERED"]
DELIVERY_CHANNELS = ["EMAIL", "POSTAL", "PORTAL"]

_DATE_LEN = len("YYYY-MM-DD")


def _assert_identity(data: dict, versioned: bool = True):
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    if versioned:
        assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601 UTC"
        assert isinstance(data.get("version"), int) and data["version"] >= 1, (
            "version must be an integer starting at 1"
        )


def assert_calendar_date(value, field_name="date"):
    assert isinstance(value, str) and len(value) == _DATE_LEN, (
        f"{field_name} must be a plain YYYY-MM-DD calendar date, got {value!r}"
    )
    year, month, day = value.split("-")
    assert len(year) == 4 and len(month) == 2 and len(day) == 2, (
        f"{field_name} must be a plain YYYY-MM-DD calendar date, got {value!r}"
    )


def assert_esop_plan(data: dict):
    _assert_identity(data)
    assert data["plan_status"] in PLAN_STATUSES, f"unexpected plan_status {data['plan_status']!r}"
    assert data["repurchase_posture"] in ["FUNDED", "UNDERFUNDED"]
    assert data["forfeiture_posture"] in ["CLEAR", "SWEEP_REQUIRED"]
    assert isinstance(data["plan_year"], int)
    assert isinstance(data["total_shares_outstanding"], int) and data["total_shares_outstanding"] >= 1
    for counter in (
        "total_plan_shares", "suspense_shares", "unallocated_released_shares",
        "unallocated_forfeiture_shares", "reacquired_shares", "allocated_shares_total",
        "current_share_price_cents", "open_valuation_count", "draft_run_count",
        "repurchase_reserve_cents", "committed_repurchase_cents",
        "cumulative_repurchase_funding_cents", "cumulative_repurchase_settled_cents",
    ):
        assert isinstance(data[counter], int), f"{counter} must be an integer"
        assert data[counter] >= 0, f"{counter} must never go negative, got {data[counter]}"


def assert_participant(data: dict):
    _assert_identity(data)
    assert data["status"] in PARTICIPANT_STATUSES
    assert isinstance(data["employee_number"], str) and data["employee_number"]
    assert_calendar_date(data["date_of_birth"], "date_of_birth")
    assert_calendar_date(data["hire_date"], "hire_date")
    assert 0 <= data["vested_percentage"] <= 100
    for counter in (
        "years_of_service", "allocated_shares", "vested_shares",
        "distributed_shares_cumulative", "tendered_shares_cumulative",
        "diversified_shares_cumulative", "eligible_compensation_cents", "annual_hours",
    ):
        assert isinstance(data[counter], int) and data[counter] >= 0, (
            f"{counter} must be a non-negative integer"
        )
    assert isinstance(data["diversification_eligible"], bool)
    if data["termination_reason"] is not None:
        assert data["termination_reason"] in ["TERMINATION", "RETIREMENT", "DEATH", "DISABILITY"]


def assert_valuation(data: dict):
    _assert_identity(data)
    assert data["status"] in VALUATION_STATUSES
    assert isinstance(data["plan_year"], int)
    assert_calendar_date(data["effective_from_date"], "effective_from_date")
    assert_calendar_date(data["effective_to_date"], "effective_to_date")
    assert data["effective_to_date"] > data["effective_from_date"], (
        "effective_to_date must fall strictly after effective_from_date"
    )
    assert 0 <= data["control_premium_bps"] <= 10000
    assert 0 <= data["marketability_discount_bps"] <= 9999
    assert data["equity_value_cents"] >= 0
    assert data["control_premium_applied_cents"] >= 0
    assert data["ownership_bps_at_valuation"] >= 0
    assert isinstance(data["challenge_round"], int) and data["challenge_round"] >= 0


def assert_esop_loan(data: dict):
    _assert_identity(data)
    assert data["status"] in LOAN_STATUSES
    assert data["release_method"] in ["PRINCIPAL_ONLY", "PRINCIPAL_AND_INTEREST"]
    assert data["principal_balance_cents"] >= 0
    assert data["remaining_interest_cents"] >= 0
    assert data["suspense_shares"] >= 0
    assert data["released_shares_cumulative"] >= 0
    assert data["suspense_shares"] + data["released_shares_cumulative"] == data["shares_pledged"], (
        "every pledged share is either still in suspense or already released"
    )


def assert_loan_payment(data: dict):
    """Loan payments are immutable servicing records: id and created_at only."""
    _assert_identity(data, versioned=False)
    assert "version" not in data, "a loan payment carries no version field"
    assert "updated_at" not in data, "a loan payment carries no updated_at field"
    assert data["release_method_applied"] in ["PRINCIPAL_ONLY", "PRINCIPAL_AND_INTEREST"]
    assert_calendar_date(data["payment_date"], "payment_date")
    assert data["released_shares"] >= 0
    assert data["suspense_shares_after"] == data["suspense_shares_before"] - data["released_shares"], (
        "suspense_shares_after is the before-balance less the released count"
    )


def assert_allocation_run(data: dict):
    _assert_identity(data)
    assert data["status"] in RUN_STATUSES
    assert isinstance(data["contributed_shares"], int) and data["contributed_shares"] >= 0
    for counter in (
        "released_shares_snapshot", "forfeiture_shares_snapshot", "pool_shares",
        "share_price_cents", "eligible_participant_count", "total_capped_compensation_cents",
        "capped_participant_count", "passes_executed", "residual_shares",
    ):
        assert isinstance(data[counter], int) and data[counter] >= 0, (
            f"{counter} must be a non-negative integer"
        )


def assert_share_allocation(data: dict):
    """Allocation lines are immutable audit rows: id and created_at only."""
    _assert_identity(data, versioned=False)
    assert "version" not in data, "a share allocation line carries no version field"
    assert "updated_at" not in data, "a share allocation line carries no updated_at field"
    assert isinstance(data["capped"], bool)
    assert data["excess_shares_removed"] == data["gross_shares_before_cap"] - data["allocated_shares"], (
        "excess_shares_removed is gross_shares_before_cap less allocated_shares"
    )


def assert_forfeiture_event(data: dict):
    _assert_identity(data)
    assert data["status"] in FORFEITURE_STATUSES
    assert data["measurement_method_applied"] in [
        "TERMINATION_DATE_MEASURE", "PLAN_YEAR_END_MEASURE"
    ]
    assert data["forfeited_shares"] >= 0
    assert 0 <= data["vested_percentage_at_forfeiture"] <= 100


def assert_distribution_election(data: dict):
    _assert_identity(data)
    assert data["approval_status"] in APPROVAL_STATUSES
    assert data["payment_status"] in PAYMENT_STATUSES
    assert data["election_type"] in [
        "TERMINATION", "RETIREMENT", "DEATH", "DISABILITY", "DIVERSIFICATION"
    ]
    assert data["requested_shares"] >= 1
    assert data["approved_shares"] >= 0
    assert data["installment_count"] >= 0


def assert_installment_payment(data: dict):
    _assert_identity(data)
    assert data["status"] in INSTALLMENT_STATUSES
    assert data["sequence_number"] >= 1
    assert_calendar_date(data["scheduled_date"], "scheduled_date")
    assert data["shares_scheduled"] >= 0
    assert data["shares_delivered"] >= 0


def assert_put_option_exercise(data: dict):
    _assert_identity(data)
    assert data["status"] in EXERCISE_STATUSES
    assert data["priority_class"] in PRIORITY_CLASSES
    assert data["shares_tendered"] >= 1
    assert_calendar_date(data["window_open_date"], "window_open_date")
    assert_calendar_date(data["window_close_date"], "window_close_date")
    assert_calendar_date(data["exercise_date"], "exercise_date")
    assert data["exercise_amount_cents"] == data["shares_tendered"] * data["share_price_cents"], (
        "exercise_amount_cents is the share price multiplied by the tendered count"
    )


def assert_participant_statement(data: dict):
    _assert_identity(data)
    assert data["delivery_status"] in DELIVERY_STATUSES
    if data["delivery_channel"] is not None:
        assert data["delivery_channel"] in DELIVERY_CHANNELS
    assert data["closing_shares"] == data["opening_shares"] + data["shares_allocated"], (
        "closing_shares is the opening balance plus the allocated figure"
    )
    assert data["total_value_cents"] == data["closing_shares"] * data["share_price_cents"], (
        "total_value_cents is the closing share balance multiplied by the frozen price"
    )


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------
def assert_share_conservation(plan: dict):
    """Every share that entered the trust sits in exactly one of the five buckets."""
    components = (
        plan["suspense_shares"]
        + plan["allocated_shares_total"]
        + plan["unallocated_released_shares"]
        + plan["unallocated_forfeiture_shares"]
        + plan["reacquired_shares"]
    )
    assert plan["total_plan_shares"] == components, (
        f"total_plan_shares {plan['total_plan_shares']} must equal suspense "
        f"{plan['suspense_shares']} + allocated {plan['allocated_shares_total']} + released "
        f"{plan['unallocated_released_shares']} + forfeited {plan['unallocated_forfeiture_shares']} "
        f"+ reacquired {plan['reacquired_shares']} = {components}"
    )


def assert_cash_conservation(plan: dict):
    """Every cent ever deposited is either uncommitted, committed or settled."""
    components = (
        plan["repurchase_reserve_cents"]
        + plan["committed_repurchase_cents"]
        + plan["cumulative_repurchase_settled_cents"]
    )
    assert plan["cumulative_repurchase_funding_cents"] == components, (
        f"cumulative_repurchase_funding_cents {plan['cumulative_repurchase_funding_cents']} must "
        f"equal reserve {plan['repurchase_reserve_cents']} + committed "
        f"{plan['committed_repurchase_cents']} + settled "
        f"{plan['cumulative_repurchase_settled_cents']} = {components}"
    )


def assert_postures_consistent(plan: dict):
    """Both derived postures are recomputed after any movement of their counter."""
    expected_repurchase = (
        "FUNDED"
        if plan["repurchase_reserve_cents"] >= plan["repurchase_reserve_floor_cents"]
        else "UNDERFUNDED"
    )
    assert plan["repurchase_posture"] == expected_repurchase, (
        f"repurchase_posture should be {expected_repurchase} at reserve "
        f"{plan['repurchase_reserve_cents']} against floor {plan['repurchase_reserve_floor_cents']}"
    )
    expected_forfeiture = (
        "CLEAR"
        if plan["unallocated_forfeiture_shares"] <= plan["forfeiture_sweep_threshold_shares"]
        else "SWEEP_REQUIRED"
    )
    assert plan["forfeiture_posture"] == expected_forfeiture, (
        f"forfeiture_posture should be {expected_forfeiture} at "
        f"{plan['unallocated_forfeiture_shares']} forfeited shares against threshold "
        f"{plan['forfeiture_sweep_threshold_shares']}"
    )
