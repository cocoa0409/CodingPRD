"""Payroll batch ingestion: terminality, layout status, feed monotonicity."""
from test_helpers import (
    onboard_employer,
    register_worker,
    create_layout,
    create_verified_layout,
    create_batch,
    attach_record,
    validate_batch,
    reject_batch,
    get_batch,
    get_employer,
    get_layout,
    set_clock,
    make_employer_headers,
    api,
    validate_error,
    validate_success,
    ApiErrorId,
    DEFAULTS,
)


def test_validated_batch_rejects_a_second_validate(api):
    """PRD §3.3: "On success the batch becomes `VALIDATED` — terminal".
    PRD §2.8: "An action addressed at a resource that is not in any state from which
    that action is defined fails with `ERR_INVALID_STATE` (HTTP 409)".

    Design: Corner/state_machines/payroll_batch_validated_is_terminal_for_validate_and_reject
    """
    employer = onboard_employer()
    headers = make_employer_headers(employer["id"])
    layout = create_verified_layout(employer["id"])
    batch = create_batch(employer["id"], layout["id"])
    validate_batch(employer["id"], batch["id"])

    response = api.validate_batch(batch["id"], headers)
    validate_error(response, ApiErrorId.ERR_ALREADY_TERMINAL)
    assert get_batch(batch["id"], employer["id"])["validation_state"] == "VALIDATED"


def test_validated_batch_cannot_be_rejected_afterwards(api):
    """PRD §3.3: "A second declaration path rejects the batch outright, moving it to
    `REJECTED` and freezing every attached record's `currency_state`; `REJECTED` is
    terminal for the batch."
    PRD §2.8: "a `PayrollFeedBatch` that is `VALIDATED` or `REJECTED` may not be driven
    further by an action that assumes they are live".

    Design: Corner/state_machines/payroll_batch_validated_is_terminal_for_validate_and_reject
    """
    employer = onboard_employer()
    headers = make_employer_headers(employer["id"])
    layout = create_verified_layout(employer["id"])
    batch = create_batch(employer["id"], layout["id"])
    validate_batch(employer["id"], batch["id"])

    response = api.reject_batch(batch["id"], headers)
    validate_error(response, ApiErrorId.ERR_ALREADY_TERMINAL)
    assert get_batch(batch["id"], employer["id"])["validation_state"] == "VALIDATED"


def test_batch_on_unverified_layout_is_refused_with_the_state_error(api):
    """PRD §3.3: "a batch validated while its `record_layout_id` points at a layout
    that is not `VERIFIED` fails with `ERR_BATCH_LAYOUT_NOT_VERIFIED` (HTTP 422)."
    PRD §3.3: "Because a batch's own layout must be settled before its payload can be
    trusted".

    Design: Corner/errors/error_batch_layout_not_verified_triggered_by_validate
    """
    employer = onboard_employer()
    headers = make_employer_headers(employer["id"])
    layout_1 = create_verified_layout(employer["id"], layout_version=1)
    batch_1 = create_batch(
        employer["id"], layout_1["id"], batch_sequence=1, pay_period_end_date="2026-05-31T00:00:00Z"
    )
    layout_2 = create_layout(employer["id"], layout_version=2)
    batch_2 = create_batch(
        employer["id"], layout_2["id"], batch_sequence=2, pay_period_end_date="2026-06-30T00:00:00Z"
    )

    response = api.validate_batch(batch_2["id"], headers)
    validate_error(response, ApiErrorId.ERR_BATCH_LAYOUT_NOT_VERIFIED)
    assert get_layout(layout_2["id"], headers)["status"] == "DRAFT"
    assert get_batch(batch_2["id"], employer["id"])["validation_state"] == "RECEIVED"


def test_backdated_batch_is_refused_and_leaves_the_feed_date_alone(api):
    """PRD §3.3: "a batch whose pay period is not strictly later fails with
    `ERR_FEED_NOT_MONOTONIC` (HTTP 422)."
    PRD §3.3: "Validation is the sole transition that advances feed currency."

    Design: Corner/errors/error_feed_not_monotonic_triggered_by_backdated_batch
    """
    employer = onboard_employer()
    headers = make_employer_headers(employer["id"])
    layout = create_verified_layout(employer["id"])
    batch_1 = create_batch(
        employer["id"], layout["id"], batch_sequence=1, pay_period_end_date="2026-05-31T00:00:00Z"
    )
    validate_batch(employer["id"], batch_1["id"])
    batch_2 = create_batch(
        employer["id"], layout["id"], batch_sequence=2, pay_period_end_date="2026-05-31T00:00:00Z"
    )

    response = api.validate_batch(batch_2["id"], headers)
    validate_error(response, ApiErrorId.ERR_FEED_NOT_MONOTONIC)
    assert get_employer(employer["id"])["last_feed_received_date"] == "2026-05-31T00:00:00.000Z"


def test_incomplete_layout_cannot_be_verified_even_after_the_batch_error(api):
    """PRD §3.1: "A layout with any absent canonical field cannot be promoted: the
    verify step requires `validation_error_count` of zero and a complete map, and
    otherwise fails with `ERR_LAYOUT_MAPPING_INCOMPLETE` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/layout_mapping_incomplete_beats_batch_layout_not_verified
    """
    employer = onboard_employer()
    headers = make_employer_headers(employer["id"])
    layout_1 = create_verified_layout(employer["id"], layout_version=1)
    incomplete = dict(DEFAULTS["COMPLETE_COLUMN_MAP"])
    incomplete.pop("BASIS")
    layout_2 = create_layout(employer["id"], layout_version=2, column_map=incomplete)

    response = api.verify_layout(layout_2["id"], headers)
    validate_error(response, ApiErrorId.ERR_LAYOUT_MAPPING_INCOMPLETE)
    detail = get_layout(layout_2["id"], headers)
    assert detail["validation_error_count"] == 1
    assert detail["missing_canonical_fields"] == ["pay_rate_basis"]


def test_batch_pinned_to_an_incomplete_draft_layout_stays_received(api):
    """PRD §3.3: "Validation is the sole transition that advances feed currency. It
    requires that the batch belongs to the acting employer, that its layout is
    `VERIFIED`, that `rejected_record_count` is 0".
    PRD §3.1: "A layout with any absent canonical field cannot be promoted: the verify
    step requires `validation_error_count` of zero and a complete map".

    Design: Difficulty/priority_pair_validation_conflict/layout_mapping_incomplete_beats_batch_layout_not_verified
    """
    employer = onboard_employer()
    headers = make_employer_headers(employer["id"])
    incomplete = dict(DEFAULTS["COMPLETE_COLUMN_MAP"])
    incomplete.pop("BASIS")
    layout = create_layout(employer["id"], layout_version=1, column_map=incomplete)
    batch = create_batch(
        employer["id"], layout["id"], batch_sequence=1, pay_period_end_date="2026-06-30T00:00:00Z"
    )

    response = api.validate_batch(batch["id"], headers)
    assert response.status_code != 200, "a batch on an unverified layout cannot validate"
    assert get_layout(layout["id"], headers)["status"] == "DRAFT"
    assert get_batch(batch["id"], employer["id"])["validation_state"] == "RECEIVED"


def test_validated_batch_advances_the_employer_feed_date(api):
    """PRD §3.3: "`last_feed_received_date` advances to the later of its current value
    and the batch's `pay_period_end_date`".
    PRD §3.3: "the employer's `feed_status` is derived to `CURRENT`".

    Design: Corner/errors/error_feed_not_monotonic_triggered_by_backdated_batch
    """
    set_clock("2026-06-15T00:00:00Z")
    employer = onboard_employer()
    layout = create_verified_layout(employer["id"])
    batch = create_batch(
        employer["id"], layout["id"], batch_sequence=1, pay_period_end_date="2026-05-31T00:00:00Z"
    )
    validate_batch(employer["id"], batch["id"])
    detail = get_employer(employer["id"])
    assert detail["last_feed_received_date"] == "2026-05-31T00:00:00.000Z"
    assert detail["feed_status"] == "CURRENT"


def test_accepted_and_rejected_counts_reconcile_with_the_declared_count(api):
    """PRD §3.3: "A record-entry declaration sets `rejected_record_count` to the
    submitted `rejected_entries` and recomputes `accepted_record_count` as
    `record_count` minus `rejected_record_count`".

    Design: Corner/state_machines/payroll_batch_validated_is_terminal_for_validate_and_reject
    """
    employer = onboard_employer()
    headers = make_employer_headers(employer["id"])
    layout = create_verified_layout(employer["id"])
    batch = create_batch(employer["id"], layout["id"], record_count=900)

    response = api.patch_batch_records(batch["id"], 3, headers)
    data = validate_success(response, 200)
    assert data["rejected_record_count"] == 3
    assert data["accepted_record_count"] == 897
    assert data["accepted_record_count"] + data["rejected_record_count"] == data["record_count"]