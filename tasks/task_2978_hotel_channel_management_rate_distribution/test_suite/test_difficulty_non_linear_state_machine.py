"""Non-linear state machines of the Hotel Channel Distribution contract.

Three surfaces in this contract refuse to advance in a straight line: a channel
connection cycles between health and degradation and can be suspended more than
once, a promotion carries two state axes that neither read nor gate each other,
and a distribution batch forks into child jobs whose mixed outcomes decide the
parent's settled state and can re-open it after it has already settled.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_success,
)

from test_helpers import (
    APPROVER_USER_ID,
    CHANNEL_OPS_ENGINEER_HEADERS,
    MAX_JOB_ATTEMPTS,
    REVENUE_MANAGER_HEADERS,
    SUBMITTER_USER_ID,
    ApiErrorId,
    assert_batch_counters,
    assert_fields,
    assert_instant_equals,
    assert_job,
    assert_sequence_indices_one_based,
    find_by,
    make_revenue_director_headers,
    make_revenue_manager_headers,
)
from test_helpers import factories, fixtures


# ── Module-local composition helpers ───────────────────────────────────────


def _error_heartbeat(api, connection_id, failure_code):
    """One failure event reported by the partner, with its failure code."""
    payload = factories.heartbeat_payload(status="ERROR", failure_code=failure_code)
    return validate_success(api.record_heartbeat(connection_id, payload, CHANNEL_OPS_ENGINEER_HEADERS))


def _ok_heartbeat(api, connection_id):
    """A healthy heartbeat, which clears the failure streak."""
    payload = factories.heartbeat_payload(status="OK")
    return validate_success(api.record_heartbeat(connection_id, payload, CHANNEL_OPS_ENGINEER_HEADERS))


def _record_version(seen, entity, label):
    """Track a version across hops: every accepted write increments it by 1."""
    if seen:
        assert entity["version"] > seen[-1], (
            f"{label}.version should grow on every accepted write, "
            f"went from {seen[-1]} to {entity['version']}"
        )
    seen.append(entity["version"])


def _pending_connection(api):
    """A property with one channel whose connection is still PENDING."""
    fixtures.set_clock(api)
    property_row = fixtures.create_canonical_property(api)
    channel = fixtures.create_channel(
        api,
        property_row["id"],
        code=fixtures.OTA_CODE,
        channel_kind="OTA_PUBLIC",
        commission_bp=fixtures.OTA_COMMISSION_BP,
    )
    connection = fixtures.create_connection(
        api,
        channel["id"],
        url=factories.endpoint_url(fixtures.OTA_CODE),
        heartbeat_interval_minutes=15,
    )
    return property_row, channel, connection


# ── The connection health cycle ────────────────────────────────────────────


def test_connection_walks_healthy_degraded_healthy_suspended_degraded_suspended(api):
    """A connection with no mappings and no allotments traverses HEALTHY, DEGRADED,
    HEALTHY, DEGRADED, DEGRADED, SUSPENDED, DEGRADED and SUSPENDED again, and the
    contract pins its state, its failure streak and its recorded failure code at
    every one of those hops.

    Design: Difficulty/non_linear_state_machine/connection_cycles_healthy_degraded_healthy_then_suspends_and_resuspends
    """
    _property_row, _channel, connection = _pending_connection(api)
    connection_id = connection["id"]
    seen_versions = []
    _record_version(seen_versions, connection, "connection")
    assert_fields(
        connection,
        {
            "connection_state": "PENDING",
            "consecutive_failures": 0,
            "last_heartbeat_at": None,
            "last_failure_code": None,
            "suspended_at": None,
        },
        "connection",
    )

    # Activation: PENDING -> HEALTHY, streak cleared, nothing suspended yet.
    activated = validate_success(api.activate_connection(connection_id, CHANNEL_OPS_ENGINEER_HEADERS))
    assert_fields(
        activated,
        {"connection_state": "HEALTHY", "consecutive_failures": 0, "suspended_at": None},
        "connection after activation",
    )
    _record_version(seen_versions, activated, "connection")

    # Failure 1: HEALTHY -> DEGRADED at a streak of 1.
    first_failure = _error_heartbeat(api, connection_id, "TIMEOUT")
    assert_fields(
        first_failure,
        {"connection_state": "DEGRADED", "consecutive_failures": 1, "last_failure_code": "TIMEOUT"},
        "connection after failure 1",
    )
    _record_version(seen_versions, first_failure, "connection")

    # An OK heartbeat closes the cycle back to HEALTHY, not back to PENDING.
    recovered = _ok_heartbeat(api, connection_id)
    assert_fields(
        recovered,
        {"connection_state": "HEALTHY", "consecutive_failures": 0, "last_failure_code": None},
        "connection after recovery",
    )
    _record_version(seen_versions, recovered, "connection")

    # Failure 2 starts a fresh streak from the recovered HEALTHY state.
    second_failure = _error_heartbeat(api, connection_id, "TIMEOUT")
    assert_fields(
        second_failure,
        {"connection_state": "DEGRADED", "consecutive_failures": 1, "last_failure_code": "TIMEOUT"},
        "connection after failure 2",
    )
    _record_version(seen_versions, second_failure, "connection")

    # Failure 3 is the self-loop: still DEGRADED, streak 2, new failure code.
    third_failure = _error_heartbeat(api, connection_id, "SCHEMA_ERROR")
    assert_fields(
        third_failure,
        {
            "connection_state": "DEGRADED",
            "consecutive_failures": 2,
            "last_failure_code": "SCHEMA_ERROR",
        },
        "connection after failure 3",
    )
    _record_version(seen_versions, third_failure, "connection")

    # Failure 4 reaches the suspension threshold of three.
    fourth_failure = _error_heartbeat(api, connection_id, "AUTH_REJECTED")
    assert_fields(
        fourth_failure,
        {
            "connection_state": "SUSPENDED",
            "consecutive_failures": 3,
            "last_failure_code": "AUTH_REJECTED",
        },
        "connection after failure 4",
    )
    assert_instant_equals(
        fourth_failure["suspended_at"], fixtures.FIXTURE_CLOCK, "connection.suspended_at"
    )
    _record_version(seen_versions, fourth_failure, "connection")

    # Revalidation puts the connection back on probation at a streak of two.
    revalidated = validate_success(
        api.revalidate_connection(connection_id, CHANNEL_OPS_ENGINEER_HEADERS)
    )
    assert_fields(
        revalidated,
        {"connection_state": "DEGRADED", "consecutive_failures": 2},
        "connection after revalidation",
    )
    assert revalidated["suspended_at"] is not None, (
        "revalidation should leave the recorded suspended_at in place, "
        f"got {revalidated['suspended_at']!r}"
    )
    _record_version(seen_versions, revalidated, "connection")

    # Failure 5: one single failure re-suspends a revalidated connection.
    fifth_failure = _error_heartbeat(api, connection_id, "TIMEOUT")
    assert_fields(
        fifth_failure,
        {
            "connection_state": "SUSPENDED",
            "consecutive_failures": 3,
            "last_failure_code": "TIMEOUT",
        },
        "connection after failure 5",
    )
    assert_instant_equals(
        fifth_failure["suspended_at"], fixtures.FIXTURE_CLOCK, "connection.suspended_at"
    )
    _record_version(seen_versions, fifth_failure, "connection")

    # Eight accepted writes followed the creation, each one bumping the version.
    assert len(seen_versions) == 9, f"expected nine observations, got {len(seen_versions)}"


def test_degraded_self_loop_and_streak_reset_decide_the_second_suspension(api):
    """The same trigger from the same state lands in two different places: an ERROR
    heartbeat leaves a DEGRADED connection DEGRADED at a streak of two and suspends
    it at three, an OK heartbeat discards the streak without leaving SUSPENDED, and
    revalidation reinstates a streak of two so one further failure suspends again.

    Design: Difficulty/non_linear_state_machine/connection_cycles_healthy_degraded_healthy_then_suspends_and_resuspends
    """
    _property_row, _channel, connection = _pending_connection(api)
    connection_id = connection["id"]
    validate_success(api.activate_connection(connection_id, CHANNEL_OPS_ENGINEER_HEADERS))

    # Two failures: the second is the intermediate self-loop, not a suspension.
    _error_heartbeat(api, connection_id, "TIMEOUT")
    at_two = _error_heartbeat(api, connection_id, "SCHEMA_ERROR")
    assert_fields(
        at_two,
        {
            "connection_state": "DEGRADED",
            "consecutive_failures": 2,
            "last_failure_code": "SCHEMA_ERROR",
        },
        "connection at a streak of two",
    )

    # An OK heartbeat resets the streak, so the next failure starts again at one
    # rather than being the third of a run.
    _ok_heartbeat(api, connection_id)
    after_reset = _error_heartbeat(api, connection_id, "TIMEOUT")
    assert_fields(
        after_reset,
        {"connection_state": "DEGRADED", "consecutive_failures": 1},
        "connection after the streak reset",
    )

    # Two more failures reach three and suspend.
    _error_heartbeat(api, connection_id, "TIMEOUT")
    suspended = _error_heartbeat(api, connection_id, "MAPPING_REJECTED")
    assert_fields(
        suspended,
        {
            "connection_state": "SUSPENDED",
            "consecutive_failures": 3,
            "last_failure_code": "MAPPING_REJECTED",
        },
        "suspended connection",
    )

    # An OK heartbeat on a SUSPENDED connection clears the streak fields but does
    # not move the state: only revalidation leaves SUSPENDED.
    cleared = _ok_heartbeat(api, connection_id)
    assert_fields(
        cleared,
        {
            "connection_state": "SUSPENDED",
            "consecutive_failures": 0,
            "last_failure_code": None,
        },
        "suspended connection after an OK heartbeat",
    )

    # Revalidation pins the streak at two regardless of what it had been cleared to.
    revalidated = validate_success(
        api.revalidate_connection(connection_id, CHANNEL_OPS_ENGINEER_HEADERS)
    )
    assert_fields(
        revalidated,
        {"connection_state": "DEGRADED", "consecutive_failures": 2},
        "revalidated connection",
    )

    # One failure is therefore enough for the second suspension.
    resuspended = _error_heartbeat(api, connection_id, "TIMEOUT")
    assert_fields(
        resuspended,
        {"connection_state": "SUSPENDED", "consecutive_failures": 3},
        "re-suspended connection",
    )
    assert_instant_equals(
        resuspended["suspended_at"], fixtures.FIXTURE_CLOCK, "connection.suspended_at"
    )


# ── The promotion's two independent axes ───────────────────────────────────


def test_promotion_loads_and_applies_while_its_approval_axis_lags_behind(api, world):
    """A promotion carries an approval axis and a distribution axis that advance
    independently: the offer is loaded to channels and its batch applies while the
    offer is still awaiting sign-off, so the pair of statuses walks (DRAFT, LOADING),
    (SUBMITTED, LOADING), (SUBMITTED, LOADED) and only then (APPROVED, LOADED).

    Design: Difficulty/non_linear_state_machine/promotion_approval_and_distribution_axes_advance_independently
    """
    mapping = fixtures.create_verified_mapping(
        api, world["rate_plan_id"], world["channel_id"], world["room_type_id"]
    )
    promotion = fixtures.create_promotion(
        api,
        world["rate_plan_id"],
        start_date="2026-09-01",
        end_date="2026-09-30",
        promo_kind="MEMBER_RATE",
        discount_kind="PERCENT",
        discount_bp=1000,
    )
    assert_fields(
        promotion,
        {
            "approval_status": "DRAFT",
            "distribution_status": "NOT_LOADED",
            "revision_count": 0,
            "submitted_by_user_id": None,
            "approved_by_user_id": None,
            "reject_reason": None,
        },
        "new promotion",
    )
    observed = []

    # Loading a DRAFT promotion is admitted: the load never consults the approval axis.
    loaded = validate_success(api.load_promotion(promotion["id"], CHANNEL_OPS_ENGINEER_HEADERS))
    observed.append((loaded["approval_status"], loaded["distribution_status"]))
    batch = fixtures.only_batch(api, property_id=world["property_id"], payload_kind="PROMOTION")
    assert_fields(
        batch,
        {
            "payload_kind": "PROMOTION",
            "source_ref_kind": "PROMOTION",
            "source_ref_id": promotion["id"],
            "dispatched_at": None,
        },
        "promotion batch",
    )
    assert_batch_counters(
        batch, batch_state="QUEUED", total_jobs=1, applied_jobs=0, rejected_jobs=0, abandoned_jobs=0
    )

    # The approval axis moves on its own, leaving the distribution axis where it was.
    submitted = validate_success(
        api.submit_promotion(promotion["id"], make_revenue_manager_headers(SUBMITTER_USER_ID))
    )
    assert_fields(
        submitted,
        {"submitted_by_user_id": SUBMITTER_USER_ID, "approved_by_user_id": None},
        "submitted promotion",
    )
    observed.append((submitted["approval_status"], submitted["distribution_status"]))

    # The distribution axis then settles while the offer is still only SUBMITTED.
    dispatched = validate_success(api.dispatch_batch(batch["id"], CHANNEL_OPS_ENGINEER_HEADERS))
    assert_batch_counters(
        dispatched,
        batch_state="APPLIED",
        total_jobs=1,
        applied_jobs=1,
        rejected_jobs=0,
        abandoned_jobs=0,
    )
    after_dispatch = fixtures.read_promotion(api, promotion["id"])
    observed.append((after_dispatch["approval_status"], after_dispatch["distribution_status"]))
    # The applied job pushes the promotion-free rate card, not the discounted offer.
    pushed = fixtures.read_mapping(api, mapping["id"])
    assert_fields(
        pushed,
        {"last_pushed_rate_cents": fixtures.BAR_BASE_CENTS},
        "mapping after the promotion push",
    )

    # Sign-off arrives last, and does not disturb what was already delivered.
    approved = validate_success(
        api.approve_promotion(promotion["id"], make_revenue_director_headers(APPROVER_USER_ID))
    )
    assert_fields(approved, {"approved_by_user_id": APPROVER_USER_ID}, "approved promotion")
    observed.append((approved["approval_status"], approved["distribution_status"]))

    assert observed == [
        ("DRAFT", "LOADING"),
        ("SUBMITTED", "LOADING"),
        ("SUBMITTED", "LOADED"),
        ("APPROVED", "LOADED"),
    ], f"the two axes should advance independently, observed {observed}"


def test_approval_axis_transitions_leave_distribution_status_untouched(api, world):
    """Submission, rejection, revision, resubmission and approval move only the
    approval axis: `distribution_status` stays wherever the loading axis left it, the
    loading axis keeps its own state gate, and an APPROVED promotion that was never
    loaded sits at NOT_LOADED.

    Design: Difficulty/non_linear_state_machine/promotion_approval_and_distribution_axes_advance_independently
    """
    fixtures.create_verified_mapping(
        api, world["rate_plan_id"], world["channel_id"], world["room_type_id"]
    )
    promotion = fixtures.create_promotion(
        api,
        world["rate_plan_id"],
        start_date="2026-09-01",
        end_date="2026-09-30",
        discount_bp=1000,
    )
    promotion_id = promotion["id"]

    # Park the distribution axis at LOADING and never touch it again.
    validate_success(api.load_promotion(promotion_id, CHANNEL_OPS_ENGINEER_HEADERS))
    batch = fixtures.only_batch(api, property_id=world["property_id"], payload_kind="PROMOTION")

    submitted = validate_success(
        api.submit_promotion(promotion_id, make_revenue_manager_headers(SUBMITTER_USER_ID))
    )
    assert_fields(
        submitted,
        {"approval_status": "SUBMITTED", "distribution_status": "LOADING"},
        "submitted promotion",
    )

    rejected = validate_success(
        api.reject_promotion(
            promotion_id,
            make_revenue_director_headers(APPROVER_USER_ID),
            factories.reject_payload("the discount needs a second look"),
        )
    )
    assert_fields(
        rejected,
        {
            "approval_status": "REJECTED",
            "distribution_status": "LOADING",
            "reject_reason": "the discount needs a second look",
            "revision_count": 0,
        },
        "rejected promotion",
    )

    # Revision returns the approval axis to DRAFT and clears the submitter, which is
    # what lets the same director approve the revised offer later on.
    revised = validate_success(api.revise_promotion(promotion_id, REVENUE_MANAGER_HEADERS))
    assert_fields(
        revised,
        {
            "approval_status": "DRAFT",
            "distribution_status": "LOADING",
            "submitted_by_user_id": None,
            "reject_reason": None,
            "revision_count": 1,
        },
        "revised promotion",
    )

    # The loading axis is gated by its own state alone: a promotion already LOADING
    # is refused a second load even though its approval axis has moved twice since.
    validate_error(
        api.load_promotion(promotion_id, CHANNEL_OPS_ENGINEER_HEADERS),
        ApiErrorId.PROMOTION_STATE_INVALID.value,
        409,
    )

    # The distribution axis settles on its own schedule.
    validate_success(api.dispatch_batch(batch["id"], CHANNEL_OPS_ENGINEER_HEADERS))
    after_dispatch = fixtures.read_promotion(api, promotion_id)
    assert_fields(
        after_dispatch,
        {"approval_status": "DRAFT", "distribution_status": "LOADED"},
        "promotion after its batch applied",
    )

    # Resubmission and approval then run to completion without moving the delivery axis.
    validate_success(api.submit_promotion(promotion_id, make_revenue_manager_headers(SUBMITTER_USER_ID)))
    approved = validate_success(
        api.approve_promotion(promotion_id, make_revenue_director_headers(APPROVER_USER_ID))
    )
    assert_fields(
        approved,
        {
            "approval_status": "APPROVED",
            "distribution_status": "LOADED",
            "revision_count": 1,
            "approved_by_user_id": APPROVER_USER_ID,
        },
        "approved promotion",
    )

    # And the converse: a fully approved offer that was never loaded stays NOT_LOADED.
    never_loaded = fixtures.create_approved_promotion(
        api,
        world["rate_plan_id"],
        start_date="2026-09-01",
        end_date="2026-09-30",
        discount_bp=500,
    )
    assert_fields(
        never_loaded,
        {"approval_status": "APPROVED", "distribution_status": "NOT_LOADED"},
        "approved but undelivered promotion",
    )


# ── Batch fork, partial settlement and re-join ─────────────────────────────


def _promotion_forked_over_two_channels(api, world):
    """One promotion of the canonical plan, loaded over two verified mappings.

    The OTA mapping keeps its parity; the direct-brand mapping is knocked out of
    parity *after* the load, which the load itself would have refused.
    """
    ota_mapping = fixtures.create_verified_mapping(
        api, world["rate_plan_id"], world["channel_id"], world["room_type_id"]
    )
    brand = fixtures.create_brand_channel(api, world["property_id"])
    brand_mapping = fixtures.create_verified_mapping(
        api, world["rate_plan_id"], brand["channel"]["id"], world["room_type_id"]
    )
    promotion = fixtures.create_promotion(
        api,
        world["rate_plan_id"],
        start_date="2026-09-01",
        end_date="2026-09-30",
        discount_bp=1000,
    )
    validate_success(api.load_promotion(promotion["id"], CHANNEL_OPS_ENGINEER_HEADERS))
    batch = fixtures.only_batch(api, property_id=world["property_id"], payload_kind="PROMOTION")
    # One image short of the property's floor of 5 leaves the mapping VERIFIED but
    # OUT_OF_PARITY, which is what the parity check rejects at dispatch.
    fixtures.patch_mapping_content(api, brand_mapping["id"], content_image_count=4)
    broken = fixtures.read_mapping(api, brand_mapping["id"])
    assert_fields(
        broken,
        {"mapping_state": "VERIFIED", "parity_state": "OUT_OF_PARITY"},
        "brand mapping after the content change",
    )
    return {
        "batch_id": batch["id"],
        "promotion_id": promotion["id"],
        "ota_mapping_id": ota_mapping["id"],
        "brand_mapping_id": brand_mapping["id"],
        "brand_connection_id": brand["connection"]["id"],
    }


def test_batch_forks_settles_partially_applied_then_rejoins_applied(api, world):
    """A batch fans out two jobs, one applies and one is rejected, so the parent
    settles to PARTIALLY_APPLIED and the promotion behind it fails to load. Repairing
    the mapping and retrying re-opens the settled batch without creating a second one,
    and the following dispatch joins it back to APPLIED and the promotion to LOADED.

    Design: Difficulty/non_linear_state_machine/batch_forks_two_jobs_settles_partially_applied_then_joins_to_applied
    """
    scenario = _promotion_forked_over_two_channels(api, world)
    batch_id = scenario["batch_id"]

    forked = fixtures.jobs_of(api, batch_id)
    assert len(forked) == 2, f"the load should fan out two jobs, got {len(forked)}"
    # Fan-out numbers the children from 1 upward, and dispatch walks them in that order.
    assert_sequence_indices_one_based(forked)

    settled = validate_success(api.dispatch_batch(batch_id, CHANNEL_OPS_ENGINEER_HEADERS))
    assert_batch_counters(
        settled,
        batch_state="PARTIALLY_APPLIED",
        total_jobs=2,
        applied_jobs=1,
        rejected_jobs=1,
        abandoned_jobs=0,
    )
    assert_instant_equals(settled["dispatched_at"], fixtures.FIXTURE_CLOCK, "batch.dispatched_at")

    jobs = fixtures.jobs_of(api, batch_id)
    ota_job = find_by(jobs, channel_mapping_id=scenario["ota_mapping_id"])
    brand_job = find_by(jobs, channel_mapping_id=scenario["brand_mapping_id"])
    assert_job(ota_job, job_state="APPLIED", attempt_count=1, failure_reason=None)
    assert_instant_equals(ota_job["applied_at"], fixtures.FIXTURE_CLOCK, "applied job.applied_at")
    assert_job(brand_job, job_state="REJECTED", attempt_count=1, failure_reason="PARITY_BLOCKED")
    assert brand_job["applied_at"] is None, (
        f"a rejected job leaves applied_at null, got {brand_job['applied_at']!r}"
    )

    # The rejection's side effects are confined to the channel that rejected.
    assert_fields(
        fixtures.read_mapping(api, scenario["brand_mapping_id"]),
        {"mapping_state": "ERRORED"},
        "rejected mapping",
    )
    assert_fields(
        fixtures.read_connection(api, scenario["brand_connection_id"]),
        {
            "connection_state": "DEGRADED",
            "consecutive_failures": 1,
            "last_failure_code": "MAPPING_REJECTED",
        },
        "connection behind the rejected job",
    )
    assert_fields(
        fixtures.read_connection(api, world["connection_id"]),
        {"connection_state": "HEALTHY", "consecutive_failures": 0},
        "connection behind the applied job",
    )
    # A partial success on the distribution axis is a failure for the promotion.
    assert_fields(
        fixtures.read_promotion(api, scenario["promotion_id"]),
        {"distribution_status": "LOAD_FAILED", "approval_status": "DRAFT"},
        "promotion after the partial settlement",
    )

    # Repair the content, close the VERIFIED -> ERRORED -> VERIFIED cycle, and retry.
    fixtures.patch_mapping_content(api, scenario["brand_mapping_id"], content_image_count=5)
    revived = fixtures.verify_mapping(api, scenario["brand_mapping_id"])
    assert_fields(
        revived,
        {"mapping_state": "VERIFIED", "parity_state": "IN_PARITY"},
        "re-verified mapping",
    )
    retried = validate_success(api.retry_job(brand_job["id"], CHANNEL_OPS_ENGINEER_HEADERS))
    assert_job(retried, job_state="QUEUED", attempt_count=1, failure_reason=None)
    assert retried["applied_at"] is None, (
        f"a retried job clears applied_at back to null, got {retried['applied_at']!r}"
    )

    # A retry is the one child change that does not move the parent's settled state.
    reopened = fixtures.read_batch(api, batch_id)
    assert_batch_counters(
        reopened,
        batch_state="PARTIALLY_APPLIED",
        total_jobs=2,
        applied_jobs=1,
        rejected_jobs=0,
        abandoned_jobs=0,
    )
    assert_fields(
        fixtures.read_promotion(api, scenario["promotion_id"]),
        {"distribution_status": "LOADING"},
        "promotion pulled back by the retry",
    )
    # The retry reuses the batch it belongs to; nothing new is queued.
    assert fixtures.only_batch(api, property_id=world["property_id"], payload_kind="PROMOTION")[
        "id"
    ] == batch_id, "a retry must not create a second promotion batch"

    joined = validate_success(api.dispatch_batch(batch_id, CHANNEL_OPS_ENGINEER_HEADERS))
    assert_batch_counters(
        joined,
        batch_state="APPLIED",
        total_jobs=2,
        applied_jobs=2,
        rejected_jobs=0,
        abandoned_jobs=0,
    )
    final_brand_job = fixtures.read_job(api, brand_job["id"])
    assert_job(final_brand_job, job_state="APPLIED", attempt_count=2, failure_reason=None)
    assert_fields(
        fixtures.read_promotion(api, scenario["promotion_id"]),
        {"distribution_status": "LOADED", "approval_status": "DRAFT"},
        "promotion after the re-join",
    )


def test_retry_preserves_attempt_count_and_the_cap_ends_the_reject_retry_loop(api, world):
    """Without a repair the rejected child cycles PARTIALLY_APPLIED -> DISPATCHING ->
    PARTIALLY_APPLIED: each retry preserves `attempt_count` rather than resetting it,
    each rejection drives the same connection one step further toward suspension, and
    the third attempt exhausts the cap so the next retry is refused.

    Design: Difficulty/non_linear_state_machine/batch_forks_two_jobs_settles_partially_applied_then_joins_to_applied
    """
    scenario = _promotion_forked_over_two_channels(api, world)
    batch_id = scenario["batch_id"]

    # Attempt 1: the parity verdict is the reason, and it errors the mapping.
    validate_success(api.dispatch_batch(batch_id, CHANNEL_OPS_ENGINEER_HEADERS))
    jobs = fixtures.jobs_of(api, batch_id)
    brand_job_id = find_by(jobs, channel_mapping_id=scenario["brand_mapping_id"])["id"]
    assert_job(
        fixtures.read_job(api, brand_job_id),
        job_state="REJECTED",
        attempt_count=1,
        failure_reason="PARITY_BLOCKED",
    )
    assert_fields(
        fixtures.read_connection(api, scenario["brand_connection_id"]),
        {"connection_state": "DEGRADED", "consecutive_failures": 1},
        "connection after attempt 1",
    )

    # Attempt 2: the mapping is ERRORED now, so the earlier check in the fixed order
    # claims the rejection, and the preserved attempt_count climbs to 2.
    retried = validate_success(api.retry_job(brand_job_id, CHANNEL_OPS_ENGINEER_HEADERS))
    assert_job(retried, job_state="QUEUED", attempt_count=1, failure_reason=None)
    validate_success(api.dispatch_batch(batch_id, CHANNEL_OPS_ENGINEER_HEADERS))
    assert_job(
        fixtures.read_job(api, brand_job_id),
        job_state="REJECTED",
        attempt_count=2,
        failure_reason="MAPPING_NOT_VERIFIED",
    )
    assert_fields(
        fixtures.read_connection(api, scenario["brand_connection_id"]),
        {"connection_state": "DEGRADED", "consecutive_failures": 2},
        "connection after attempt 2",
    )
    assert_batch_counters(
        fixtures.read_batch(api, batch_id),
        batch_state="PARTIALLY_APPLIED",
        total_jobs=2,
        applied_jobs=1,
        rejected_jobs=1,
        abandoned_jobs=0,
    )

    # Attempt 3: the same rejection now carries the connection to the threshold of 3.
    retried_again = validate_success(api.retry_job(brand_job_id, CHANNEL_OPS_ENGINEER_HEADERS))
    assert_job(retried_again, job_state="QUEUED", attempt_count=2, failure_reason=None)
    validate_success(api.dispatch_batch(batch_id, CHANNEL_OPS_ENGINEER_HEADERS))
    exhausted = fixtures.read_job(api, brand_job_id)
    assert_job(
        exhausted,
        job_state="REJECTED",
        attempt_count=MAX_JOB_ATTEMPTS,
        failure_reason="MAPPING_NOT_VERIFIED",
    )
    assert_fields(
        fixtures.read_connection(api, scenario["brand_connection_id"]),
        {"connection_state": "SUSPENDED", "consecutive_failures": 3},
        "connection after attempt 3",
    )

    # The cap is what terminates the loop: a fourth attempt is refused.
    validate_error(
        api.retry_job(brand_job_id, CHANNEL_OPS_ENGINEER_HEADERS),
        ApiErrorId.JOB_NOT_RETRYABLE.value,
        409,
    )
    refused = fixtures.read_job(api, brand_job_id)
    assert_job(
        refused,
        job_state="REJECTED",
        attempt_count=MAX_JOB_ATTEMPTS,
        failure_reason="MAPPING_NOT_VERIFIED",
    )
    assert refused["version"] == exhausted["version"], (
        "a refused retry has no side effects, so the job's version should stay at "
        f"{exhausted['version']}, got {refused['version']}"
    )

    # Three dispatches and three rejections, all inside the one batch the load made.
    assert_batch_counters(
        fixtures.read_batch(api, batch_id),
        batch_state="PARTIALLY_APPLIED",
        total_jobs=2,
        applied_jobs=1,
        rejected_jobs=1,
        abandoned_jobs=0,
    )
    assert fixtures.only_batch(api, property_id=world["property_id"], payload_kind="PROMOTION")[
        "id"
    ] == batch_id, "the reject and retry cycle must not create further batches"
    assert_fields(
        fixtures.read_promotion(api, scenario["promotion_id"]),
        {"distribution_status": "LOAD_FAILED"},
        "promotion after the exhausted cycle",
    )
    # The channel that applied on the first pass was never touched again.
    assert_job(
        find_by(fixtures.jobs_of(api, batch_id), channel_mapping_id=scenario["ota_mapping_id"]),
        job_state="APPLIED",
        attempt_count=1,
        failure_reason=None,
    )
