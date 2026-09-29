"""Transitions, guards, terminal states and the cascades hanging off them.

Every lifecycle in this contract is a small state machine with a fixed entry
state, a set of legal edges and a set of preconditions that are checked in a
published order. These tests walk the legal edges, then push at the illegal ones
to confirm which guard answers first.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_INVALIDATION_NOT_REVERSIBLE,
    ERR_PILOT_WINDOW_NOT_STARTED,
    ERR_RESULT_STATE_INVALID,
    ERR_SAMPLE_STATE_INVALID,
)
from test_helpers.assertions import (
    assert_decimal,
    assert_entry_point_posture,
    assert_equals,
    assert_instant_equals,
    assert_is_null,
    assert_status,
    assert_total_count,
)
from test_helpers.constants import DEFAULT_CLOCK
from test_helpers.fixtures import (
    build_registry,
    collect_sample,
    issued_violation,
    open_evaluation,
    read_entry_point,
    read_evaluation,
    read_lab_result,
    read_notification,
    read_pilot,
    read_sample,
    receive_sample,
    received_sample,
    register_entry_point,
    register_pilot,
    reject_result,
    set_clock,
    ship_sample,
    submit_result,
)
from test_helpers.test_users import (
    COMPLIANCE_OFFICER_2_HEADERS,
    COMPLIANCE_OFFICER_HEADERS,
    OFFICER_2_USER_ID,
    OFFICER_USER_ID,
    SAMPLING_TECHNICIAN_HEADERS,
    STATE_REGULATOR_HEADERS,
    TREATMENT_ENGINEER_HEADERS,
    UTILITY_ADMIN_HEADERS,
)

_COLLECTED_AT = "2026-05-15T08:00:00.000Z"


def _collected_sample(api):
    """One COLLECTED 2026Q2 sample and the registry it belongs to."""
    registry = build_registry(api)
    sample = collect_sample(
        api,
        registry["entry_point_id"],
        [registry["contaminant_id"]],
        monitoring_period="2026Q2",
        collected_at=_COLLECTED_AT,
        preservative_lot="LOT-SHIP",
    )
    return registry, sample


def test_shipping_a_collected_sample_stamps_the_clock_not_the_collection_instant(api):
    """Two instants live on the row at once and they are not the same instant.

    The shipment names the receiving laboratory and the sample advances to
    IN_TRANSIT, where shipped_at is the logical clock's default reading of
    2026-08-01T00:00:00.000Z while collected_at keeps the field instant of
    2026-05-15T08:00:00.000Z and received_at is still null.

    PRD: "The shipment payload names the receiving `laboratory_id`, and on
    success the sample advances `COLLECTED → IN_TRANSIT` with
    `assigned_laboratory_id` set to the named laboratory and `shipped_at` set to
    the logical clock."

    Design: Corner/state_machines/shipping_a_collected_sample_records_the_assignment_and_the_clock
    """
    registry, sample = _collected_sample(api)

    shipped = validate_success(
        api.ship_sample(
            sample["id"],
            f.ship_sample_payload(registry["laboratory_id"]),
            SAMPLING_TECHNICIAN_HEADERS,
        )
    )

    assert_status(shipped, "IN_TRANSIT")
    assert_equals(shipped, "assigned_laboratory_id", registry["laboratory_id"])
    assert_instant_equals(shipped["shipped_at"], DEFAULT_CLOCK, label="shipped_at")
    assert_instant_equals(shipped["collected_at"], _COLLECTED_AT, label="collected_at")
    assert_is_null(shipped, "received_at")
    assert_equals(shipped, "version", 2)


def test_a_second_shipment_cannot_reassign_the_sample_to_another_laboratory(api):
    """The ship trigger is not idempotent, and the refusal is not a no-op either.

    A sample already IN_TRANSIT is outside the only status the transition
    accepts, so naming a second laboratory is refused on the state guard and the
    first assignment stands untouched at version 2 — nothing is re-stamped.

    PRD: "A sample in any status other than `COLLECTED` is refused with
    `ERR_SAMPLE_STATE_INVALID`; a laboratory reference that does not resolve is
    refused with `ERR_LABORATORY_NOT_FOUND`; and because the logical clock can be
    moved backwards, a shipment attempted while the clock reads earlier than the
    sample's collection instant is refused with `ERR_SHIP_BEFORE_COLLECTION`."

    Design: Corner/state_machines/a_sample_cannot_be_shipped_twice
    """
    registry, sample = _collected_sample(api)
    second_laboratory = validate_success(
        api.create_laboratory(
            f.laboratory_payload(name="Southbay Labs", certification_id="CERT-002"),
            UTILITY_ADMIN_HEADERS,
        ),
        201,
    )
    ship_sample(api, sample["id"], registry["laboratory_id"])

    validate_error(
        api.ship_sample(
            sample["id"],
            f.ship_sample_payload(second_laboratory["id"]),
            SAMPLING_TECHNICIAN_HEADERS,
        ),
        ERR_SAMPLE_STATE_INVALID,
        422,
    )

    stored = read_sample(api, sample["id"])
    assert_status(stored, "IN_TRANSIT")
    assert_equals(stored, "assigned_laboratory_id", registry["laboratory_id"])
    assert_equals(stored, "version", 2)


def test_reinstating_a_received_sample_answers_on_the_state_guard(api):
    """Two guards could fire here and the published order decides which one does.

    The sample is RECEIVED, which reinstatement has no edge out of at all, so the
    state guard answers first and the reversibility guard is never consulted —
    the code is the state refusal, not the not-reversible refusal, and the sample
    still carries no invalidation reason.

    PRD: "Reinstatement is the exact inverse, and it is deliberately narrow. Only
    a sample in `INVALIDATED` status may be reinstated, else
    `ERR_SAMPLE_STATE_INVALID`."

    Design: Corner/state_machines/a_received_sample_cannot_be_reinstated
    """
    registry = build_registry(api)
    sample = received_sample(
        api,
        registry["entry_point_id"],
        [registry["contaminant_id"]],
        registry["laboratory_id"],
        preservative_lot="LOT-REINS",
    )

    response = api.reinstate_sample(sample["id"], {}, COMPLIANCE_OFFICER_HEADERS)

    validate_error(response, ERR_SAMPLE_STATE_INVALID, 422)
    assert response.json()["data"]["error_id"] != ERR_INVALIDATION_NOT_REVERSIBLE, (
        "A sample that was never invalidated must answer on the state guard"
    )
    stored = read_sample(api, sample["id"])
    assert_status(stored, "RECEIVED")
    assert_is_null(stored, "invalidation_reason")


def test_a_new_pilot_is_born_planned_with_no_measurements_at_all(api):
    """Unmeasured is null, not zero — only the media ledger starts at 0.00.

    A freshly registered GAC skid is PLANNED and unselected with an
    unmanifested media ledger of 0.00 kg, but every measurement and score the
    completion will later write is null rather than seeded to zero, and the row
    is at version 1.

    PRD: "The pilot is created in `PLANNED` status with `unmanifested_media_kg` of
    0.00 and `selected` false."

    Design: Corner/state_machines/a_new_pilot_test_starts_in_planned_with_empty_measurements
    """
    entry_point = register_entry_point(api)
    evaluation = open_evaluation(api, entry_point["id"], residuals_budget_cents=500000)

    pilot = validate_success(
        api.create_pilot_test(
            f.gac_pilot_payload(evaluation["id"]), TREATMENT_ENGINEER_HEADERS
        ),
        201,
    )

    assert_status(pilot, "PLANNED")
    assert_equals(pilot, "selected", False)
    assert_decimal(pilot["unmanifested_media_kg"], 0.00, label="unmanifested_media_kg")
    assert_is_null(
        pilot,
        "influent_ng_per_l",
        "effluent_ng_per_l",
        "spent_media_kg",
        "removal_pct",
        "technology_score",
    )
    assert_equals(pilot, "version", 1)


def test_only_the_first_pilot_forks_the_evaluation_and_the_entry_point(api):
    """The cascade fires once per evaluation, not once per pilot.

    Registering the GAC skid moves its voluntary evaluation from screening into
    piloting and marks the entry point as being on a pilot; the IX skid that
    follows leaves both of those alone and simply becomes the second PLANNED
    pilot of the same evaluation.

    PRD: "The first pilot registered against an evaluation moves it
    `SCREENING → PILOTING` and sets the parent entry point's `treatment_status`
    to `PILOT`; subsequent pilots leave both alone."

    Design: Corner/state_machines/the_first_pilot_forks_its_evaluation_from_screening_to_piloting
    """
    entry_point = register_entry_point(api)
    evaluation = open_evaluation(api, entry_point["id"], residuals_budget_cents=500000)

    first = register_pilot(api, f.gac_pilot_payload(evaluation["id"]))
    after_first = read_evaluation(api, evaluation["id"])
    assert_status(after_first, "PILOTING")
    second = register_pilot(api, f.ix_pilot_payload(evaluation["id"]))

    stored_evaluation = read_evaluation(api, evaluation["id"])
    assert_status(stored_evaluation, "PILOTING")
    assert_equals(stored_evaluation, "mandated", False)
    assert_entry_point_posture(read_entry_point(api, entry_point["id"]), treatment_status="PILOT")
    assert_status(read_pilot(api, first["id"]), "PLANNED")
    assert_status(read_pilot(api, second["id"]), "PLANNED")
    assert_total_count(
        api.list_pilot_tests(
            TREATMENT_ENGINEER_HEADERS, params={"treatment_evaluation_id": evaluation["id"]}
        ),
        2,
    )


def test_a_rejected_result_cannot_be_accepted_by_a_second_review(api):
    """REJECTED is terminal in both directions, and the entry point never moved.

    The officer's rejection is final: a second review attempting to accept the
    same result is refused, the reason code stays on the row, the parent sample
    is still merely RECEIVED, and because nothing was ever accepted the entry
    point's counter is zero and monitoring never left INITIAL.

    PRD: "Only a result in `SUBMITTED` status may be reviewed; a second review of
    the same result is refused with `ERR_RESULT_STATE_INVALID`. Rejection drives
    the result `SUBMITTED → REJECTED`, stores the reason code and the note, and
    changes nothing at all on the entry point — `REJECTED` is terminal."

    Design: Corner/state_machines/a_rejected_lab_result_cannot_be_reviewed_again
    """
    registry = build_registry(api)
    sample = received_sample(
        api,
        registry["entry_point_id"],
        [registry["contaminant_id"]],
        registry["laboratory_id"],
        preservative_lot="LOT-TERM",
    )
    result = submit_result(
        api, registry["laboratory_id"], sample["id"], registry["contaminant_id"]
    )
    reject_result(
        api,
        result["id"],
        reject_reason_code="QC_FAILURE",
        review_note="Duplicate precision out of range",
    )

    validate_error(
        api.review_lab_result(
            result["id"], f.accept_review_payload(), COMPLIANCE_OFFICER_HEADERS
        ),
        ERR_RESULT_STATE_INVALID,
        422,
    )

    stored = read_lab_result(api, result["id"])
    assert_status(stored, "REJECTED")
    assert_equals(stored, "reject_reason_code", "QC_FAILURE")
    assert_status(read_sample(api, sample["id"]), "RECEIVED")
    assert_entry_point_posture(
        read_entry_point(api, registry["entry_point_id"]),
        accepted_result_count=0,
        monitoring_status="INITIAL",
    )


def test_a_pilot_whose_window_has_not_opened_cannot_be_started(api):
    """The blocked precondition is the clock, not a state and not a role.

    The skid is in the one status the start accepts and the engineer is the one
    role permitted to start it, but the window opens on 2026-09-01 while the
    logical clock still reads its default 2026-08-01, so the start is refused on
    the temporal precondition and the pilot is left untouched at version 1.

    PRD: "A pilot moves `PLANNED → RUNNING` when the engineer starts it, which
    requires `PLANNED` status — else `ERR_PILOT_STATE_INVALID` — and requires the
    logical clock to have reached the pilot's `window_start_at`; starting exactly
    at the window start instant is permitted, and starting before it is refused
    with `ERR_PILOT_WINDOW_NOT_STARTED`."

    Design: Corner/state_machines/a_pilot_cannot_start_before_its_window_opens
    """
    entry_point = register_entry_point(api)
    evaluation = open_evaluation(api, entry_point["id"], residuals_budget_cents=500000)
    pilot = register_pilot(
        api,
        f.gac_pilot_payload(
            evaluation["id"],
            window_start_at="2026-09-01T00:00:00.000Z",
            window_end_at="2026-09-15T00:00:00.000Z",
        ),
    )

    validate_error(
        api.start_pilot_test(pilot["id"], {}, TREATMENT_ENGINEER_HEADERS),
        ERR_PILOT_WINDOW_NOT_STARTED,
        422,
    )

    stored = read_pilot(api, pilot["id"])
    assert_status(stored, "PLANNED")
    assert_equals(stored, "version", 1)


def test_a_quality_control_invalidation_can_never_be_walked_back(api):
    """Here the state is right and a non-state field of the same row blocks it.

    The sample really is INVALIDATED, so the state guard passes; what refuses the
    reinstatement is the recorded reason, because only an operator error is
    reversible and a quality-control failure is substantive. The row keeps its
    reason and its remembered prior status, and the entry point's invalidation
    streak stands at one.

    PRD: "Beyond that, the invalidation must have been recorded as
    `OPERATOR_ERROR` and `status_before_invalidation` must not be null; a sample
    invalidated for any substantive reason — broken custody, a contaminated field
    blank, an exceeded holding time or a quality-control failure — can never be
    reinstated, and the attempt is refused with
    `ERR_INVALIDATION_NOT_REVERSIBLE`."

    Design: Corner/state_machines/a_sample_invalidated_for_qc_failure_cannot_be_reinstated
    """
    registry = build_registry(api)
    sample = received_sample(
        api,
        registry["entry_point_id"],
        [registry["contaminant_id"]],
        registry["laboratory_id"],
        preservative_lot="LOT-QCF",
    )
    invalidated = validate_success(
        api.invalidate_sample(
            sample["id"],
            f.invalidate_sample_payload(invalidation_reason="QC_FAILURE"),
            COMPLIANCE_OFFICER_HEADERS,
        )
    )
    assert_status(invalidated, "INVALIDATED")

    validate_error(
        api.reinstate_sample(sample["id"], {}, COMPLIANCE_OFFICER_HEADERS),
        ERR_INVALIDATION_NOT_REVERSIBLE,
        422,
    )

    stored = read_sample(api, sample["id"])
    assert_status(stored, "INVALIDATED")
    assert_equals(stored, "status_before_invalidation", "RECEIVED")
    assert_equals(stored, "invalidation_reason", "QC_FAILURE")
    assert_entry_point_posture(
        read_entry_point(api, registry["entry_point_id"]), consecutive_invalidated_samples=1
    )


_RESCIND_REASON = "Laboratory recalculated the calibration curve"
_TIER_2_DEADLINE = "2026-08-31T00:00:00.000Z"
_ONE_HOUR_LATE = "2026-08-31T01:00:00.000Z"


def _issued_mcl_violation(api):
    """An issued non-acute MCL violation at 4.50 ng/L with its DRAFT TIER_2 notice."""
    registry = build_registry(api)
    issued = issued_violation(api, registry, reported_ng_per_l=4.50)
    return registry, issued


def test_rescinding_a_determination_voids_the_notice_it_never_sent(api):
    """One trigger writes three rows: the verdict, the counter and the notice.

    The rescission moves the determination out of ISSUED while leaving its
    verdict and violation type on the record, drops the entry point's open
    violation count back to zero, and voids the draft notice the issuance
    cascade had opened — yet the posture stays VIOLATION_PENDING, because
    withdrawing the paperwork does not change the measured ratio.

    PRD: "Rescission requires `ISSUED` status, else
    `ERR_DETERMINATION_STATE_INVALID`, and moves the determination
    `ISSUED → RESCINDED`. When the rescinded determination was an
    `MCL_VIOLATION`, the entry point's `open_violation_count` falls by one with a
    floor of zero. Any linked public notification still in `DRAFT`, `SUBMITTED`
    or `APPROVED` status is driven to `VOIDED`, because a notice that has not yet
    reached the public need not go out."

    Design: Corner/state_machines/rescinding_a_determination_voids_the_undistributed_notification
    """
    registry, issued = _issued_mcl_violation(api)

    rescinded = validate_success(
        api.rescind_determination(
            issued["determination_id"],
            f.rescind_payload(rescind_reason=_RESCIND_REASON),
            STATE_REGULATOR_HEADERS,
        )
    )

    assert_equals(rescinded, "determination", "MCL_VIOLATION")
    assert_equals(rescinded, "violation_type", "NON_ACUTE")
    assert_status(rescinded, "RESCINDED")
    assert_equals(rescinded, "rescind_reason", _RESCIND_REASON)

    notification = read_notification(api, issued["notification"]["id"])
    assert_status(notification, "VOIDED")
    assert_equals(notification, "tier", "TIER_2")
    assert_instant_equals(
        notification["required_by_at"], _TIER_2_DEADLINE, label="required_by_at"
    )
    assert_entry_point_posture(
        read_entry_point(api, registry["entry_point_id"]),
        posture="VIOLATION_PENDING",
        open_violation_count=0,
    )


def test_certifying_one_hour_past_the_deadline_takes_the_late_branch(api):
    """One trigger, two destinations, and the clock alone picks between them.

    The TIER_2 notice was due 720 hours after issuance, at
    2026-08-31T00:00:00.000Z; certifying at 2026-08-31T01:00:00.000Z is strictly
    after that, so the notice lands in LATE_DISTRIBUTED with one hour of overrun
    rather than DISTRIBUTED with none. Two distinct officers appear on the row —
    the drafter and the certifier — and no revision was ever demanded.

    PRD: "When the clock instant is strictly after `required_by_at`, the
    notification moves `APPROVED → LATE_DISTRIBUTED` and `late_by_hours` is the
    overrun in hours rounded up to the next whole hour, with a minimum of 1, so
    that even a one-minute overrun records a full hour late."

    Design: Corner/state_machines/certifying_one_hour_past_the_deadline_takes_the_late_branch
    """
    _, issued = _issued_mcl_violation(api)
    notification_id = issued["notification"]["id"]
    validate_success(
        api.submit_notification(
            notification_id, f.notification_submit_payload(), COMPLIANCE_OFFICER_HEADERS
        )
    )
    validate_success(
        api.review_notification(
            notification_id,
            f.notification_review_payload(approve=True, review_note="Content acceptable"),
            STATE_REGULATOR_HEADERS,
        )
    )
    set_clock(api, _ONE_HOUR_LATE, COMPLIANCE_OFFICER_2_HEADERS)

    certified = validate_success(
        api.certify_notification_distribution(
            notification_id,
            f.certify_distribution_payload(delivery_evidence_ref="MAILING-RECEIPT-7781"),
            COMPLIANCE_OFFICER_2_HEADERS,
        )
    )

    assert_status(certified, "LATE_DISTRIBUTED")
    assert_equals(certified, "late_by_hours", 1)
    assert_instant_equals(certified["distributed_at"], _ONE_HOUR_LATE, label="distributed_at")
    assert_instant_equals(certified["required_by_at"], _TIER_2_DEADLINE, label="required_by_at")
    assert_equals(certified, "drafted_by_user_id", OFFICER_USER_ID)
    assert_equals(certified, "certified_by_user_id", OFFICER_2_USER_ID)
    assert_equals(certified, "revision_count", 0)


def test_the_third_contaminated_field_blank_suspends_the_entry_point(api):
    """A counter side effect that only fires on its third execution.

    A field blank reading of exactly 2.00 ng/L is at the limit rather than below
    it, so each of three receipts invalidates its sample for blank contamination
    and lifts the streak by one; the entry point sits out the first two at
    INITIAL and only the third flips it to SUSPENDED, clearing any pending
    frequency request as it goes.

    PRD: "When `consecutive_invalidated_samples` reaches 3 at an entry point, the
    entry point's `monitoring_status` becomes `SUSPENDED` as a cascade of the
    third invalidation, its `requested_monitoring_status` is cleared, and no
    further collection is accepted there until an administrator resumes
    monitoring."

    Design: Corner/state_machines/the_third_contaminated_field_blank_suspends_the_entry_point
    """
    registry = build_registry(api)
    samples = []
    for period, collected_at, lot in (
        ("2025Q4", "2025-11-14T08:00:00.000Z", "LOT-B1"),
        ("2026Q1", "2026-02-13T08:00:00.000Z", "LOT-B2"),
        ("2026Q2", "2026-05-15T08:00:00.000Z", "LOT-B3"),
    ):
        sample = collect_sample(
            api,
            registry["entry_point_id"],
            [registry["contaminant_id"]],
            monitoring_period=period,
            collected_at=collected_at,
            preservative_lot=lot,
        )
        ship_sample(api, sample["id"], registry["laboratory_id"])
        samples.append(sample)

    expected_statuses = ["INITIAL", "INITIAL", "SUSPENDED"]
    for index, sample in enumerate(samples):
        invalidated = receive_sample(
            api,
            sample["id"],
            registry["laboratory_id"],
            field_blank_result_ng_per_l=2.00,
        )
        assert_status(invalidated, "INVALIDATED")
        assert_equals(invalidated, "invalidation_reason", "FIELD_BLANK_CONTAMINATED")
        assert_entry_point_posture(
            read_entry_point(api, registry["entry_point_id"]),
            monitoring_status=expected_statuses[index],
            consecutive_invalidated_samples=index + 1,
        )

    last = read_sample(api, samples[-1]["id"])
    assert_is_null(last, "status_before_invalidation")
    assert_is_null(read_entry_point(api, registry["entry_point_id"]), "requested_monitoring_status")


def test_resuming_a_suspended_entry_point_lands_on_quarterly_and_clears_the_streak(api):
    """The destination is a fixed state, not the state the entry point came from.

    The entry point was suspended while still on INITIAL monitoring, yet the
    resume returns it to QUARTERLY rather than restoring INITIAL, and the same
    write zeroes the invalidation streak that prompted the suspension. The
    broken-custody invalidation itself is untouched.

    PRD: "Resumption is permitted only from `SUSPENDED` and returns the entry
    point to `QUARTERLY` — never to whatever reduced frequency it held before —
    while resetting `consecutive_invalidated_samples` to zero, which clears the
    invalidation streak that may have prompted the suspension in the first
    place."

    Design: Corner/state_machines/resuming_a_suspended_entry_point_lands_on_quarterly_and_zeroes_the_streak
    """
    registry = build_registry(api)
    sample = collect_sample(
        api,
        registry["entry_point_id"],
        [registry["contaminant_id"]],
        monitoring_period="2026Q2",
        preservative_lot="LOT-RES",
    )
    ship_sample(api, sample["id"], registry["laboratory_id"])
    receive_sample(
        api, sample["id"], registry["laboratory_id"], chain_of_custody_intact=False
    )
    validate_success(
        api.set_monitoring_status(
            registry["entry_point_id"],
            f.monitoring_status_payload("SUSPEND", reason="Sampling crew retraining"),
            UTILITY_ADMIN_HEADERS,
        )
    )

    resumed = validate_success(
        api.set_monitoring_status(
            registry["entry_point_id"],
            f.monitoring_status_payload("RESUME"),
            UTILITY_ADMIN_HEADERS,
        )
    )

    assert_entry_point_posture(
        resumed,
        posture="COMPLIANT",
        monitoring_status="QUARTERLY",
        consecutive_invalidated_samples=0,
        accepted_result_count=0,
    )
    stored = read_sample(api, sample["id"])
    assert_status(stored, "INVALIDATED")
    assert_equals(stored, "invalidation_reason", "CHAIN_OF_CUSTODY_BROKEN")
