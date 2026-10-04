"""Accident reporting and investigation (PRD §3.7, §2.10): the late-report
threshold, the auto-issued fixed-factor citation, the publication gate, and
the public projection.

Clock note: all readings are >= the startup reading 2026-09-01T00:00:00Z
(PRD §2.4). A FATAL accident occurring at 2026-09-10T08:00:00Z is timely when
reported at 08:15:00Z exactly (900 seconds) and late at 08:16:00Z (960 > 900,
strict greater-than).
"""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_accident,
    get_assessment_for_citation,
    get_success_data,
    in_progress_inspection,
    make_inspector_headers,
    publish_report_flow,
    publish_report_payload,
    refresh_accident,
    report_accident_flow,
    set_clock,
    setup_citation,
    setup_registry,
    validate_error,
    validate_paginated,
    validate_success,
)

_ADMIN = TEST_USERS["admin_headers"]
_DM = TEST_USERS["district_manager_headers"]
_PUBLIC = TEST_USERS["public_reader_headers"]


def test_accident_publish_requires_completed_investigation(api):
    """PRD §3.3: "When an `ACCIDENT_INVESTIGATION` inspection starts, the
    linked accident simultaneously moves from `REPORTED` to
    `UNDER_INVESTIGATION` (§3.7)."
    PRD §3.7: "Once the investigation inspection has reached `COMPLETED`, an
    `MSHAAdmin` publishes the public report by supplying the `root_cause` and
    the `report_text` — both required, their absence `ERR_INVALID_REQUEST` —
    which moves the accident to `REPORT_PUBLISHED` and stamps `published_at`;
    publishing without a completed investigation is rejected with
    `ERR_ACCIDENT_INVESTIGATION_INCOMPLETE`."
    PRD §3.7: "Only then does the public projection become readable —
    including by `PublicReader`; before publication it answers `ERR_NOT_FOUND`
    as if absent (§2.10)."

    Design: Difficulty/cross_entity_state_dependency/accident_publish_requires_completed_investigation
    """
    set_clock("2026-09-10T08:50:00Z")
    operator, mine, i1 = setup_registry(mine_type="SURFACE")
    accident = report_accident_flow(
        mine, operator,
        occurred_at="2026-09-10T08:00:00Z",
        severity="LOST_TIME",
        description="haul truck rollover at the pit ramp",
    )
    assert accident["late_report"] is False  # 3000s gap, within the 7200s limit
    assert accident["status"] == "REPORTED"

    i1h = make_inspector_headers(i1["id"])
    set_clock("2026-09-11T09:00:00Z")
    inspection = in_progress_inspection(
        mine, i1, kind="ACCIDENT_INVESTIGATION", accident_id=accident["id"],
        planned_start_at="2026-09-11T08:00:00Z",
        planned_end_at="2026-09-11T17:00:00Z",
    )
    assert refresh_accident(accident["id"])["status"] == "UNDER_INVESTIGATION", (
        "the inspection start auto-derives the accident's investigation state"
    )

    # Publication while the investigation is still IN_PROGRESS is refused.
    set_clock("2026-09-12T09:00:00Z")
    resp = api.publish_accident_report(accident["id"], publish_report_payload(), _ADMIN)
    validate_error(resp, ApiErrorId.ERR_ACCIDENT_INVESTIGATION_INCOMPLETE)

    # Completing the (plan-gate-free) investigation unblocks publication.
    completed = get_success_data(api.complete_inspection(inspection["id"], i1h))
    assert completed["status"] == "COMPLETED"
    published = publish_report_flow(refresh_accident(accident["id"]))
    assert published["status"] == "REPORT_PUBLISHED"
    assert published["published_at"] == "2026-09-12T09:00:00Z"

    public = validate_success(api.get_public_accident_report(accident["id"], _PUBLIC))
    assert public["id"] == accident["id"]


def test_late_fatal_accident_report_auto_issues_citation(api):
    """PRD §3.7: "the report is late when the gap between `reported_at` and
    `occurred_at` exceeds 900 seconds (15 minutes) for a `FATAL` accident or
    exceeds 7,200 seconds (120 minutes) for any other severity; a gap exactly
    at the limit is timely."
    PRD §3.7: "A late report triggers the system's own enforcement: an
    automatic citation is issued with `system_issued` true, no `inspection_id`
    and no `issued_by_inspector_id`, kind `CITATION`, negligence `MODERATE`,
    likelihood `UNLIKELY`, severity `NO_INJURY`, exactly one person affected,
    neither S&S nor repeat, and `standard_code` reading `50.10 LATE REPORT`,
    together with its own proposed assessment computed by the standard pipeline
    from those fixed factors."

    Design: Corner/state_machines/late_fatal_accident_report_auto_issues_citation
    """
    set_clock("2026-09-10T08:16:00Z")
    operator, mine, _i1 = setup_registry()
    accident = report_accident_flow(
        mine, operator,
        occurred_at="2026-09-10T08:00:00Z",
        severity="FATAL",
        description="powered haulage fatality at the face",
    )
    assert_accident(accident)
    assert accident["late_report"] is True, "960 seconds > 900-second FATAL limit"
    assert accident["status"] == "REPORTED"

    rows, meta = validate_paginated(
        api.list_citations(_DM, params={"mine_id": mine["id"]})
    )
    assert len(rows) == 1 and meta["total_count"] == 1
    auto = rows[0]
    assert auto["system_issued"] is True
    assert auto["inspection_id"] is None
    assert auto["issued_by_inspector_id"] is None
    assert auto["kind"] == "CITATION"
    assert auto["negligence"] == "MODERATE"
    assert auto["gravity_likelihood"] == "UNLIKELY"
    assert auto["gravity_severity"] == "NO_INJURY"
    assert auto["persons_affected"] == 1
    assert auto["significant_and_substantial"] is False
    assert auto["repeat_violation"] is False
    assert auto["standard_code"] == "50.10 LATE REPORT"

    # Fixed factors: 25 + 5 + 0 + 0 + 0 + 0(history) + 0(size 1000t) = 30
    # points; gross 20*11250 + 10*22500 = 450000c; the 60000c floor is below.
    assessment = get_assessment_for_citation(auto["id"])
    assert assessment["points_total"] == 30
    assert assessment["proposed_penalty_cents"] == 450000
    assert assessment["statutory_floor_applied"] is False


def test_timely_fatal_report_at_exactly_fifteen_minutes(api):
    """PRD §3.7: "the report is late when the gap between `reported_at` and
    `occurred_at` exceeds 900 seconds (15 minutes) for a `FATAL` accident or
    exceeds 7,200 seconds (120 minutes) for any other severity; a gap exactly
    at the limit is timely."

    Design: Corner/calculations/timely_fatal_report_at_exactly_fifteen_minutes
    """
    set_clock("2026-09-10T08:15:00Z")
    operator, mine, _i1 = setup_registry()
    accident = report_accident_flow(
        mine, operator,
        occurred_at="2026-09-10T08:00:00Z",
        severity="FATAL",
        description="roof fall fatality",
    )
    assert accident["late_report"] is False, (
        "exactly 900 seconds is the inclusive-timely boundary (strict greater-than)"
    )
    rows, meta = validate_paginated(
        api.list_citations(_DM, params={"mine_id": mine["id"]})
    )
    assert rows == [] and meta["total_count"] == 0, (
        "a timely report synthesizes no citation"
    )


def test_publicreader_limited_to_published_reports(api):
    """PRD §2.1: "This applies to `PublicReader` as well: the public role is
    authorized only for the published-accident-report read, and every other
    endpoint answers a `PublicReader` request with `ERR_UNAUTHORIZED`."
    PRD §2.10: "an accident whose report has not yet been published answers the
    public read with `ERR_NOT_FOUND`, exactly as if the accident did not exist,
    so that no draft investigation is observable through the public surface."

    Design: Corner/rbac/publicreader_limited_to_published_reports
    """
    set_clock("2026-09-10T08:00:00Z")
    bundle = setup_citation()
    accident = report_accident_flow(
        bundle["mine"], bundle["operator"],
        occurred_at="2026-09-10T08:00:00Z",
        severity="NO_LOST_TIME",
        description="minor equipment contact",
    )
    assert accident["status"] == "REPORTED"  # never investigated or published

    resp = api.get_citation(bundle["citation"]["id"], _PUBLIC)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

    resp = api.get_public_accident_report(accident["id"], _PUBLIC)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
