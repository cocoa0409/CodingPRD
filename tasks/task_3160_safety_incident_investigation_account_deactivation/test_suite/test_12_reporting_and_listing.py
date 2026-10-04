"""Regional rollup reporting, resource creation stamps and collection listing."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    get_account,
    get_success_data,
    make_incident,
    set_clock,
    setup_account,
    setup_policy,
    validate_error,
    validate_paginated,
)

ADMIN = TEST_USERS["admin_headers"]
INVESTIGATOR = TEST_USERS["investigator_headers"]
LIAISON = TEST_USERS["liaison_headers"]
BACKGROUND_REVIEWER = TEST_USERS["background_reviewer_headers"]

S3_SPEC = {"incident_category": "SAFETY_VIOLATION", "aggravator_codes": ["S3_INJURY"]}


def _file_s3(account_id, when):
    """Step the clock to `when` and file one S3 SAFETY_VIOLATION incident."""
    set_clock(when)
    return make_incident(account_id, **S3_SPEC)


def test_rollup_window_counts_the_closed_start_and_excludes_the_open_end(api):
    """PRD §3.5: "The lower boundary is inclusive and the upper boundary is exclusive: an
    incident created at exactly the window start is counted, and one created at exactly the
    window end — the same instant as the triggering incident — is not"
    PRD §3.5: "The window length defaults to 30 days — so with the default policy the lower edge
    of the window sits exactly 30 days before the triggering incident's `created_at` — and the
    count is compared against a threshold that defaults to 3 serious incidents."

    Design: Difficulty/boundary_precision_check/boundary_rollup_window_closed_open_at_the_exact_day
    """
    set_clock("2026-09-01T00:00:00Z")
    setup_policy(rollup_window_days=30, rollup_threshold=3)
    account_x = setup_account(account_type="DRIVER", handle="rafa.cordero")
    account_y = setup_account(account_type="DRIVER", handle="ines.duarte")

    for when in ("2026-09-01T00:00:00Z", "2026-09-15T00:00:00Z", "2026-09-20T00:00:00Z"):
        _file_s3(account_x["id"], when)
        _file_s3(account_y["id"], when)

    inc_x = _file_s3(account_x["id"], "2026-10-01T00:00:00Z")
    inc_y = _file_s3(account_y["id"], "2026-10-01T00:00:00Z")
    get_success_data(api_client.hold_incident(inc_x["id"], INVESTIGATOR))
    get_success_data(api_client.hold_incident(inc_y["id"], INVESTIGATOR))

    filed = get_success_data(api_client.rollup_sweep(inc_x["id"], LIAISON))
    assert len(filed) == 1, (
        "the leading account's window holds 3 qualifying incidents, meeting the threshold"
    )
    assert filed[0]["report_status"] == "FILED", (
        "a rollup report moves straight to FILED rather than resting in the backlog"
    )
    assert filed[0]["region_code"] == "R1"


def test_raised_rollup_threshold_stops_the_next_sweep_from_filing(api):
    """PRD §3.9: "A revision may carry any of `sd_floor_severity`, `sd_floor_enabled`,
    `rollup_window_days`, `rollup_threshold`, `cluster_watchlist_threshold`,
    `cluster_purge_threshold`, `escalation_enabled`, `expedite_appeal_baseline_count`,
    `expedite_review_days`, `standard_review_days`, `appeal_window_days`,
    `rescreen_refresh_days` or `continuous_monitor_ack_deadline_days`"
    PRD §3.5: "The window length defaults to 30 days — so with the default policy the lower edge
    of the window sits exactly 30 days before the triggering incident's `created_at` — and the
    count is compared against a threshold that defaults to 3 serious incidents."

    Design: Difficulty/boundary_precision_check/boundary_rollup_window_closed_open_at_the_exact_day
    """
    set_clock("2026-09-01T00:00:00Z")
    policy = setup_policy(rollup_window_days=30, rollup_threshold=3)
    account_x = setup_account(account_type="DRIVER", handle="rafa.cordero.b")
    account_y = setup_account(account_type="DRIVER", handle="ines.duarte.b")

    for when in ("2026-09-01T00:00:00Z", "2026-09-15T00:00:00Z", "2026-09-20T00:00:00Z"):
        _file_s3(account_x["id"], when)
        _file_s3(account_y["id"], when)

    inc_x = _file_s3(account_x["id"], "2026-10-01T00:00:00Z")
    inc_y = _file_s3(account_y["id"], "2026-10-01T00:00:00Z")
    get_success_data(api_client.hold_incident(inc_x["id"], INVESTIGATOR))
    get_success_data(api_client.hold_incident(inc_y["id"], INVESTIGATOR))

    first = get_success_data(api_client.rollup_sweep(inc_x["id"], LIAISON))
    assert len(first) == 1, (
        "the qualifying count is 3 for this window: the incident at exactly the window start "
        "is counted and the triggering incident itself sits outside the window"
    )

    revised = get_success_data(
        api_client.patch_platform_policy(
            policy["id"],
            {"expected_policy_version": policy["version"], "rollup_threshold": 4},
            ADMIN,
        )
    )
    assert revised["rollup_threshold"] == 4

    second = get_success_data(api_client.rollup_sweep(inc_y["id"], LIAISON))
    assert second == [], (
        "the same 3 qualifying incidents fall below the raised threshold of 4, so the "
        "sweep files nothing"
    )


def test_rollup_sweep_below_the_threshold_is_empty_and_role_gated(api):
    """PRD §4: "the authorized roles column below is exhaustive: a role that is not listed for
    an operation is refused with `ERR_UNAUTHORIZED`."
    PRD §3.5: "When that count has reached the region's rollup threshold, exactly one report is
    produced for the pair of subject account and region and moves straight to `FILED`"

    Design: Corner/endpoints/rollup_sweep_creates_no_report_below_the_threshold
    """
    set_clock("2026-09-01T00:00:00Z")
    setup_policy(rollup_window_days=30, rollup_threshold=3)
    account = setup_account(account_type="DRIVER", handle="zane.mercer")

    _file_s3(account["id"], "2026-09-10T00:00:00Z")
    _file_s3(account["id"], "2026-09-20T00:00:00Z")
    triggering = _file_s3(account["id"], "2026-10-01T00:00:00Z")
    get_success_data(api_client.hold_incident(triggering["id"], INVESTIGATOR))

    result = get_success_data(api_client.rollup_sweep(triggering["id"], LIAISON))
    assert result == [], (
        "only two incidents were created strictly before the triggering incident inside the "
        "window, which is below the threshold of 3"
    )

    denied = api_client.rollup_sweep(triggering["id"], BACKGROUND_REVIEWER)
    validate_error(denied, ApiErrorId.ERR_UNAUTHORIZED)
    assert denied.status_code == 403

    reports = get_success_data(
        api_client.list_regulator_reports(LIAISON, params={"incident_id": triggering["id"]})
    )
    assert reports == [], (
        "the conditional action produces an empty success result rather than an error when "
        "the threshold is not met"
    )


def test_account_create_stamps_the_posture_and_the_policy_generation(api):
    """PRD §3.9: "A new account starts at `status` `ACTIVE` with `safety_posture` `OPEN`,
    `risk_score` 0, `risk_tier` `TIER_LOW`, `standing_enforcement_count` 0, `deactivation_count`
    0 and `prior_reinstatement_count` 0; its `policy_generation_index` is stamped from the
    region's policy and `three_year_drift_last_run_index` is initialised to that same value."

    Design: Corner/entities/account_create_stamps_posture_and_policy_generation
    """
    set_clock("2026-10-01T00:00:00Z")
    setup_policy(sd_floor_severity="S3", knob_generation_index=3)

    account = get_success_data(
        api_client.create_account(
            {"account_type": "RIDER", "home_region_code": "R1",
             "legal_name": "Ana Ruiz", "contact_email": "ana.ruiz@example.com"},
            ADMIN,
        )
    )

    assert account["status"] == "ACTIVE"
    assert account["safety_posture"] == "OPEN"
    assert account["risk_score"] == 0
    assert account["risk_tier"] == "TIER_LOW"
    assert account["standing_enforcement_count"] == 0
    assert account["deactivation_count"] == 0
    assert account["prior_reinstatement_count"] == 0
    assert account["policy_generation_index"] == 3, (
        "the generation is stamped from the region's published policy rather than "
        f"defaulting to zero, got {account['policy_generation_index']}"
    )
    assert account["three_year_drift_last_run_index"] == account["policy_generation_index"], (
        "the drift-run index is initialised to the newly stamped generation"
    )

    reread = get_account(account["id"])
    assert reread["policy_generation_index"] == 3


def test_only_a_driver_account_gets_the_synthesized_screening_review(api):
    """PRD §3.9: "Driver accounts additionally receive a synthesised `CONTINUOUS_MONITOR`
    background check with `trigger_source` `CONTINUOUS`, `check_status` `SCHEDULED` and
    `adjudication` `PENDING`."

    Design: Corner/entities/driver_account_create_synthesizes_continuous_monitor_check
    """
    set_clock("2026-10-01T00:00:00Z")
    setup_policy(sd_floor_severity="S3")
    driver = setup_account(account_type="DRIVER", handle="bill.osei")
    rider = setup_account(account_type="RIDER", handle="cara.vega")

    driver_checks = get_success_data(
        api_client.list_account_background_checks(
            driver["id"], BACKGROUND_REVIEWER, params={"check_kind": "CONTINUOUS_MONITOR"}
        )
    )
    assert len(driver_checks) == 1, (
        "a driver account receives exactly one synthesised continuous-monitor review"
    )
    assert driver_checks[0]["check_kind"] == "CONTINUOUS_MONITOR"
    assert driver_checks[0]["trigger_source"] == "CONTINUOUS", (
        "the account-creation synthesis writes the CONTINUOUS trigger source"
    )
    assert driver_checks[0]["check_status"] == "SCHEDULED"
    assert driver_checks[0]["adjudication"] == "PENDING"
    assert driver_checks[0]["monitor_generation"] == 1, (
        "the synthesis stamps the region's first policy generation, not a zero placeholder"
    )
    assert driver_checks[0]["scheduled_due_at"] is not None

    rider_checks = get_success_data(
        api_client.list_account_background_checks(rider["id"], BACKGROUND_REVIEWER)
    )
    assert rider_checks == [], (
        "the synthesis is DRIVER-only, so a rider account carries no screening review"
    )

    # The synthesized row is discoverable through the flat collection as well.
    flat = get_success_data(
        api_client.list_background_checks(
            BACKGROUND_REVIEWER, params={"account_id": driver["id"]}
        )
    )
    assert len(flat) == 1 and flat[0]["id"] == driver_checks[0]["id"]


def test_incident_listing_paginates_filters_and_reports_total_count(api):
    """PRD §2.3: "List endpoints accept a `limit` query parameter that caps the number of items
    returned, defaulting to 10 when omitted, with a minimum of 1 and a maximum of 100."
    PRD §2.3: "Every list response carries `limit`, `offset`, `total_count` and `has_more`
    inside the `meta` object of the envelope described in §2.2."

    Design: Corner/entities/incidents_list_paginates_filtered_and_reports_total_count
    """
    set_clock("2026-10-01T00:00:00Z")
    setup_policy(sd_floor_severity="S3")
    account = setup_account(handle="elias.nord")

    for category in ("PHYSICAL_ASSAULT", "SEXUAL_MISCONDUCT",
                     "PROPERTY_DAMAGE", "PROPERTY_DAMAGE"):
        make_incident(account["id"], incident_category=category)

    all_rows, all_meta = validate_paginated(
        api_client.list_incidents(INVESTIGATOR, params={"account_id": account["id"]})
    )
    assert len(all_rows) == 4, (
        "the request with no limit returns all four rows because four is below the "
        "default page size of ten"
    )
    assert all_meta["total_count"] == 4
    assert all_meta["has_more"] is False
    assert all_meta["offset"] == 0
    assert all(row["incident_status"] == "OPEN" for row in all_rows)
    assert all(row["account_id"] == account["id"] for row in all_rows)

    page, page_meta = validate_paginated(
        api_client.list_incidents(
            INVESTIGATOR, params={"account_id": account["id"], "limit": 2, "offset": 0}
        )
    )
    assert len(page) == 2
    assert page_meta["total_count"] == 4
    assert page_meta["limit"] == 2
    assert page_meta["has_more"] is True

    severe, severe_meta = validate_paginated(
        api_client.list_incidents(
            INVESTIGATOR, params={"account_id": account["id"], "severity": "S4"}
        )
    )
    assert len(severe) == 2, "the two S4 categories are the only ones at that band"
    assert severe_meta["total_count"] == 2, (
        "the filter narrows the reported total rather than leaving it at the whole table count"
    )
    assert all(row["severity"] == "S4" for row in severe)