"""Print-job scheduling gating tests (PRD §3.7)."""
from test_helpers import (
    ApiErrorId,
    PERMIT_COORD,
    PRINT_OP,
    assert_print_job,
    create_permit_application_payload,
    create_print_job_payload,
    current_site_version,
    get_success_data,
    schedule_print_job,
    set_clock,
    setup_site_ready_for_print,
    validate_error,
    validate_success,
)


def test_print_job_ready_gated_on_permit_approved(api):
    """PRD §3.7: "The site's permit application covering `plan_revision_id`
    must be `APPROVED`; otherwise the transition is rejected with
    `ERR_PERMIT_NOT_APPROVED`."

    The site is fully prepared but its permit application is left in `DRAFT`;
    the ready transition is rejected.

    Design: Difficulty/cross_entity_state_dependency/print_job_ready_gated_on_permit_approved
    """
    from test_helpers import (
        create_approved_plan_revision,
        create_jurisdiction,
        create_site,
        create_qualified_batch,
        create_and_qualify_printer,
        post_clear_weather,
        pour_and_cure_foundation,
    )

    set_clock("2026-09-01T00:00:00Z")
    jurisdiction = create_jurisdiction(code="JR")
    _plan, revision = create_approved_plan_revision(plan_area_m2=80)
    site = create_site(jurisdiction["id"], address="401 P St")
    pour_and_cure_foundation(site["id"], "2026-09-01T00:00:00Z", "2026-09-04T00:00:00Z")
    setup = create_and_qualify_printer(site["id"])
    create_qualified_batch(site["id"])
    post_clear_weather(site["id"], "2026-09-04T07:30:00Z")
    # Permit application created but never submitted — stays DRAFT.
    app = get_success_data(
        api.create_permit_application(
            site["id"], create_permit_application_payload(revision["id"]), PERMIT_COORD
        )
    )
    version = current_site_version(site["id"])
    job = get_success_data(
        api.create_print_job(
            site["id"],
            create_print_job_payload(
                revision["id"],
                setup["id"],
                version,
                scheduled_start_at="2026-09-05T08:00:00Z",
                scheduled_end_at="2026-09-05T16:00:00Z",
            ),
            PRINT_OP,
        )
    )
    assert app["status"] == "DRAFT"
    resp = api.transition_print_job(site["id"], job["id"], {"to_state": "READY_TO_PRINT"}, PRINT_OP)
    validate_error(resp, ApiErrorId.ERR_PERMIT_NOT_APPROVED)


def test_print_job_ready_succeeds_with_approved_permit(api):
    """PRD §3.7: "Moving the job from `SCHEDULED` to `READY_TO_PRINT` is the
    system's main gating checkpoint" whose permit check requires the covering
    application to be `APPROVED` (§3.7 first bullet).

    Design: Difficulty/cross_entity_state_dependency/print_job_ready_gated_on_permit_approved
    """
    ctx = setup_site_ready_for_print(jurisdiction_code="JR2")
    job = schedule_print_job(ctx)
    data = validate_success(
        api.transition_print_job(
            ctx["site"]["id"], job["id"], {"to_state": "READY_TO_PRINT"}, PRINT_OP
        )
    )
    assert data["status"] == "READY_TO_PRINT"


def test_schedule_overlap_half_open_interval(api):
    """PRD §3.7: "Two intervals overlap when each one's start is strictly before
    the other's end; an incoming start equal to an existing job's end is
    adjacent, not overlapping, and is permitted. Violations are rejected with
    `ERR_PRINT_SCHEDULE_OVERLAP`."

    Design: Difficulty/boundary_precision_check/schedule_overlap_half_open_interval
    """
    ctx = setup_site_ready_for_print(jurisdiction_code="JO")
    site_id = ctx["site"]["id"]
    job1 = schedule_print_job(
        ctx, scheduled_start_at="2026-09-05T08:00:00Z", scheduled_end_at="2026-09-05T16:00:00Z"
    )
    # Adjacent: start == existing end is permitted.
    version = current_site_version(site_id)
    adjacent = validate_success(
        api.create_print_job(
            site_id,
            create_print_job_payload(
                ctx["revision"]["id"],
                ctx["printer_setup"]["id"],
                version,
                scheduled_start_at="2026-09-05T16:00:00Z",
                scheduled_end_at="2026-09-05T20:00:00Z",
            ),
            PRINT_OP,
        ),
        201,
    )
    assert adjacent["scheduled_start_at"].startswith("2026-09-05T16:00")
    # Overlapping by one minute is rejected.
    version = current_site_version(site_id)
    resp = api.create_print_job(
        site_id,
        create_print_job_payload(
            ctx["revision"]["id"],
            ctx["printer_setup"]["id"],
            version,
            scheduled_start_at="2026-09-05T15:59:00Z",
            scheduled_end_at="2026-09-05T20:00:00Z",
        ),
        PRINT_OP,
    )
    validate_error(resp, ApiErrorId.ERR_PRINT_SCHEDULE_OVERLAP)
    assert job1["status"] == "SCHEDULED"


def test_schedule_overlap_one_hour_overlap_rejected(api):
    """PRD §3.7: "The job's half-open scheduled interval must not overlap any
    other print job on the same site in `SCHEDULED`, `READY_TO_PRINT`,
    `PRINTING`, or `PAUSED` ... Violations are rejected with
    `ERR_PRINT_SCHEDULE_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/print_job_schedule_half_open_overlap
    """
    ctx = setup_site_ready_for_print(jurisdiction_code="JU")
    site_id = ctx["site"]["id"]
    schedule_print_job(
        ctx, scheduled_start_at="2026-09-05T08:00:00Z", scheduled_end_at="2026-09-05T16:00:00Z"
    )
    version = current_site_version(site_id)
    resp = api.create_print_job(
        site_id,
        create_print_job_payload(
            ctx["revision"]["id"],
            ctx["printer_setup"]["id"],
            version,
            scheduled_start_at="2026-09-05T15:00:00Z",
            scheduled_end_at="2026-09-05T20:00:00Z",
        ),
        PRINT_OP,
    )
    validate_error(resp, ApiErrorId.ERR_PRINT_SCHEDULE_OVERLAP)


def test_schedule_overlap_contained_interval_rejected(api):
    """PRD §3.7: "The job's half-open scheduled interval must not overlap any
    other print job on the same site in `SCHEDULED`, `READY_TO_PRINT`,
    `PRINTING`, or `PAUSED`. Two intervals overlap when each one's start is
    strictly before the other's end ... Violations are rejected with
    `ERR_PRINT_SCHEDULE_OVERLAP`."

    Design: Difficulty/boundary_precision_check/schedule_overlap_half_open_interval
    """
    ctx = setup_site_ready_for_print(jurisdiction_code="JO2")
    site_id = ctx["site"]["id"]
    schedule_print_job(
        ctx, scheduled_start_at="2026-09-05T08:00:00Z", scheduled_end_at="2026-09-05T16:00:00Z"
    )
    version = current_site_version(site_id)
    resp = api.create_print_job(
        site_id,
        create_print_job_payload(
            ctx["revision"]["id"],
            ctx["printer_setup"]["id"],
            version,
            scheduled_start_at="2026-09-05T10:00:00Z",
            scheduled_end_at="2026-09-05T12:00:00Z",
        ),
        PRINT_OP,
    )
    validate_error(resp, ApiErrorId.ERR_PRINT_SCHEDULE_OVERLAP)


def test_schedule_overlap_back_to_back_predecessor_permitted(api):
    """PRD §3.7: "an incoming start equal to an existing job's end is adjacent,
    not overlapping, and is permitted."

    Design: Difficulty/resource_temporal_overlap/print_job_schedule_half_open_overlap
    """
    ctx = setup_site_ready_for_print(jurisdiction_code="JU2")
    site_id = ctx["site"]["id"]
    # First job ends at 08:00 next day; the second starts exactly then.
    schedule_print_job(
        ctx, scheduled_start_at="2026-09-05T00:00:00Z", scheduled_end_at="2026-09-06T08:00:00Z"
    )
    version = current_site_version(site_id)
    adjacent = validate_success(
        api.create_print_job(
            site_id,
            create_print_job_payload(
                ctx["revision"]["id"],
                ctx["printer_setup"]["id"],
                version,
                scheduled_start_at="2026-09-06T08:00:00Z",
                scheduled_end_at="2026-09-06T16:00:00Z",
            ),
            PRINT_OP,
        ),
        201,
    )
    assert adjacent["status"] == "SCHEDULED"


def test_weather_observation_lookback_window_stale_rejected(api):
    """PRD §3.7: "must have `is_print_permissible` true and must have been
    observed within the last 30 minutes of the current logical clock; otherwise
    `ERR_WEATHER_NOT_PERMISSIBLE`."

    Design: Difficulty/resource_temporal_overlap/weather_observation_lookback_window
    """
    # Setup posts clear weather at 07:30; we re-post at 07:29 (31 minutes stale
    # relative to the 08:00 clock) so the latest observation is outside the
    # 30-minute lookback.
    ctx = setup_site_ready_for_print(
        jurisdiction_code="JW", weather_observed_at="2026-09-04T07:29:00Z"
    )
    site_id = ctx["site"]["id"]
    job = schedule_print_job(ctx)
    set_clock("2026-09-04T08:00:00Z")
    resp = api.transition_print_job(site_id, job["id"], {"to_state": "READY_TO_PRINT"}, PRINT_OP)
    validate_error(resp, ApiErrorId.ERR_WEATHER_NOT_PERMISSIBLE)


def test_weather_observation_lookback_window_fresh_accepted(api):
    """PRD §3.6: "An observation remains valid for gating for 30 minutes after
    its `observed_at`, inclusive."

    Design: Difficulty/resource_temporal_overlap/weather_observation_lookback_window
    """
    # Latest observation at 07:30, clock at 08:00 — exactly 30 minutes old,
    # within the inclusive lookback, so the ready transition passes the weather
    # check.
    ctx = setup_site_ready_for_print(jurisdiction_code="JW2")
    job = schedule_print_job(ctx)
    set_clock("2026-09-04T08:00:00Z")
    data = validate_success(
        api.transition_print_job(
            ctx["site"]["id"], job["id"], {"to_state": "READY_TO_PRINT"}, PRINT_OP
        )
    )
    assert data["status"] == "READY_TO_PRINT"
