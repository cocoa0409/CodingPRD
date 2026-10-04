"""Follow-up inspections and the factory conformity score.

Covers scheduling-date and minimum-gap rules, overdue marking and late
completion, the derived inspection interval tiers, the 70-point regime
boundary, the divergent STANDARD/PROBATION scoring windows under clock aging,
finding-to-certification scoping, and the CRITICAL-finding suspension cascade.
"""

from test_helpers import (
    ApiErrorId,
    BASE_CLOCK_ISO,
    SECOND_ENGINEER_ID,
    canonical_instant,
    complete_inspection,
    complete_inspection_payload,
    create_factory,
    create_manufacturer,
    finding_entry,
    inspection_payload,
    label_batch_payload,
    make_manufacturer_rep_headers,
    parse_instant,
    refresh_certification,
    refresh_factory,
    refresh_mark_license,
    schedule_and_complete_inspection,
    schedule_inspection,
    set_clock,
    setup_certified,
    setup_certified_with_license,
    setup_world,
    validate_error,
    validate_paginated,
    validate_success,
)


def _build_window_divergence(api):
    """Two factories, each with one CRITICAL-finding inspection completed at
    2024-06-01 (both drop to PROBATION, score 60). Factory G then records a
    zero-finding completion at 2024-07-01, returning it to STANDARD while the
    June finding is still inside its trailing 24-month window. Returns the two
    factory dicts with the clock standing at 2024-07-01.
    """
    ctx = setup_world(
        api,
        clock_iso="2024-06-01T00:00:00Z",
        factory_overrides={
            "site_code": "A",
            "country_code": "US",
            "jurisdiction_code": "US-OSHA",
        },
    )
    fac_f = ctx["factory"]
    fac_g = create_factory(
        api,
        ctx["manufacturer"]["id"],
        site_code="B",
        country_code="US",
        jurisdiction_code="US-OSHA",
    )
    schedule_and_complete_inspection(
        api,
        fac_f["id"],
        findings=[
            finding_entry("FD-F1", "CRITICAL", "Unlisted capacitor in primary circuit")
        ],
        scheduled_for="2024-06-01T00:00:00Z",
    )
    schedule_and_complete_inspection(
        api,
        fac_g["id"],
        findings=[
            finding_entry("FD-G1", "CRITICAL", "Unlisted capacitor in primary circuit")
        ],
        scheduled_for="2024-06-01T00:00:00Z",
    )
    set_clock(api, "2024-07-01T00:00:00Z")
    schedule_and_complete_inspection(
        api, fac_g["id"], findings=[], scheduled_for="2024-07-01T00:00:00Z"
    )
    return fac_f, fac_g


def test_inspection_scheduled_in_past_returns_422(api, inspector_headers):
    """PRD §3.6: "The instant must not be before the current logical time
    (`ERR_INSPECTION_DATE_PAST`, HTTP 422), and it must leave a buffer of at
    least 25 days against every other non-`VOIDED` inspection of the same
    factory — whether `SCHEDULED`, `OVERDUE`, or `COMPLETED`."

    Design: Corner/validations/inspection_scheduled_in_past_returns_422
    """
    ctx = setup_world(api)
    factory_id = ctx["factory"]["id"]
    past = api.schedule_inspection(
        factory_id, inspection_payload("2026-08-31T23:59:59Z"), inspector_headers
    )
    validate_error(past, ApiErrorId.ERR_INSPECTION_DATE_PAST)
    # Exactly the current logical instant is admissible (not before now).
    now = api.schedule_inspection(
        factory_id, inspection_payload(BASE_CLOCK_ISO), inspector_headers
    )
    data = validate_success(now, 201)
    assert data["status"] == "SCHEDULED"


def test_inspection_overdue_via_sweep_then_late_completion(api, officer_headers):
    """PRD §2.5: "Third, overdue marking: every `SCHEDULED` inspection whose
    `scheduled_for` is before the current time becomes `OVERDUE`."
    PRD §3.6: "Completion — admitted from either `SCHEDULED` or `OVERDUE`, with
    lateness observable as a `completed_on` later than `scheduled_for`"
    PRD §3.6: "the result is `CONFORMING` when no findings were recorded."

    Design: Corner/state_machines/inspection_overdue_via_sweep_then_late_completion
    """
    ctx = setup_world(api)
    factory_id = ctx["factory"]["id"]
    inspection = schedule_inspection(api, factory_id, "2026-09-10T00:00:00Z")
    set_clock(api, "2026-09-11T00:00:00Z")

    inspections, _meta = validate_paginated(
        api.list_inspections(factory_id, officer_headers)
    )
    view = next(i for i in inspections if i["id"] == inspection["id"])
    assert view["status"] == "OVERDUE"

    completed = complete_inspection(api, inspection["id"], findings=[])
    assert completed["status"] == "COMPLETED"
    assert completed["result"] == "CONFORMING"
    assert canonical_instant(completed["completed_on"]) == canonical_instant(
        "2026-09-11T00:00:00Z"
    )
    assert parse_instant(completed["completed_on"]) > parse_instant(
        completed["scheduled_for"]
    ), "lateness is observable as completed_on later than scheduled_for"


def test_inspection_interval_twelve_month_tier_for_clean_factory(api):
    """PRD §3.6: "A `PROBATION` factory, or any factory whose `conformity_score`
    is below 70, is due every 3 months; a factory scoring at least 70 but below
    90 is due every 6 months; a factory scoring 90 or above is due every 12
    months. `next_inspection_due_on` is `last_inspection_completed_on` plus that
    interval, added in calendar months onto the completion date, and is null
    before the first inspection."

    Design: Corner/calculations/inspection_interval_twelve_month_tier_for_clean_factory
    """
    ctx = setup_world(api)
    factory_id = ctx["factory"]["id"]
    schedule_and_complete_inspection(
        api, factory_id, findings=[], scheduled_for=BASE_CLOCK_ISO
    )
    factory = refresh_factory(api, factory_id)
    assert factory["conformity_score"] == 100
    assert factory["conformity_regime"] == "STANDARD"
    assert canonical_instant(
        factory["last_inspection_completed_on"]
    ) == canonical_instant(BASE_CLOCK_ISO)
    assert canonical_instant(factory["next_inspection_due_on"]) == canonical_instant(
        "2027-09-01T00:00:00Z"
    )


def test_conformity_score_exactly_70_stays_standard(api):
    """PRD §3.6: "Each finding is worth a penalty by `severity`: 40 points for
    `CRITICAL`, 15 for `MAJOR`, and 5 for `MINOR`. The factory's
    `conformity_score` is 100 minus the sum of penalties over the included
    findings, never below zero, kept to two decimal places rounded half-up."
    PRD §3.6: "A `STANDARD` factory drops to `PROBATION` when a new `CRITICAL`
    finding is recorded against it or when its windowed score falls below 70."

    Design: Difficulty/boundary_precision_check/conformity_score_exactly_70_stays_standard_regime
    """
    ctx = setup_world(api)
    factory_id = ctx["factory"]["id"]
    schedule_and_complete_inspection(
        api,
        factory_id,
        findings=[
            finding_entry("FD-1", "MAJOR", "Missing torque records"),
            finding_entry("FD-2", "MAJOR", "Uncalibrated hipot tester"),
        ],
        scheduled_for=BASE_CLOCK_ISO,
    )
    factory = refresh_factory(api, factory_id)
    # 100 - 15 - 15 = 70 exactly: the threshold is strict-below, so the regime
    # holds at STANDARD and the interval tier is the 6-month band.
    assert factory["conformity_score"] == 70
    assert factory["conformity_regime"] == "STANDARD"
    assert canonical_instant(factory["next_inspection_due_on"]) == canonical_instant(
        "2027-03-01T00:00:00Z"
    )


def test_conformity_score_65_drops_to_probation_three_month_interval(api):
    """PRD §3.6: "A `STANDARD` factory drops to `PROBATION` when a new
    `CRITICAL` finding is recorded against it or when its windowed score falls
    below 70."
    PRD §3.6: "A `PROBATION` factory, or any factory whose `conformity_score` is
    below 70, is due every 3 months"

    Design: Difficulty/boundary_precision_check/conformity_score_exactly_70_stays_standard_regime
    """
    ctx = setup_world(api)
    factory_id = ctx["factory"]["id"]
    schedule_and_complete_inspection(
        api,
        factory_id,
        findings=[
            finding_entry("FD-1", "MAJOR", "Missing torque records"),
            finding_entry("FD-2", "MAJOR", "Uncalibrated hipot tester"),
        ],
        scheduled_for=BASE_CLOCK_ISO,
    )
    assert refresh_factory(api, factory_id)["conformity_score"] == 70

    follow_up = schedule_inspection(api, factory_id, "2026-09-26T00:00:00Z")
    set_clock(api, "2026-09-26T00:00:00Z")
    complete_inspection(
        api,
        follow_up["id"],
        findings=[finding_entry("FD-3", "MINOR", "Label log missing a page")],
    )
    factory = refresh_factory(api, factory_id)
    # 70 - 5 = 65 < 70: the regime flips and the interval shortens to 3 months
    # counted from the latest completion (2026-09-26).
    assert factory["conformity_score"] == 65
    assert factory["conformity_regime"] == "PROBATION"
    assert canonical_instant(factory["next_inspection_due_on"]) == canonical_instant(
        "2026-12-26T00:00:00Z"
    )


def test_standard_regime_window_ages_out_old_findings(api):
    """PRD §3.6: "For a `STANDARD` factory, the window is the trailing 24
    months: findings on non-`VOIDED` `COMPLETED` inspections whose
    `completed_on` is at or after the instant 24 months before now count — the
    lower bound is inclusive — and older findings stop counting, which is why a
    clock sweep recomputes `STANDARD`-regime scores."
    PRD §3.6: "A `PROBATION` factory returns to `STANDARD` when a completed
    inspection records zero findings, or when a void leaves it with no open
    `CRITICAL` findings and a windowed score of at least 70."
    PRD §3.6: "`open_critical_findings` counts the `CRITICAL` findings on the
    factory's non-`VOIDED` `COMPLETED` inspections"

    Design: Difficulty/dual_variant_calc/factory_conformity_window_vs_open_findings_diverge
    """
    _fac_f, fac_g = _build_window_divergence(api)
    # At 2024-07-01 the zero-finding completion returned G to STANDARD while the
    # June CRITICAL finding is still inside the trailing window.
    g_mid = refresh_factory(api, fac_g["id"])
    assert g_mid["conformity_regime"] == "STANDARD"
    assert g_mid["conformity_score"] == 60

    set_clock(api, "2026-09-01T00:00:00Z")
    g = refresh_factory(api, fac_g["id"])
    assert g["conformity_score"] == 100, (
        "the 27-month-old finding has aged out of the STANDARD window"
    )
    assert g["conformity_regime"] == "STANDARD"
    assert g["open_critical_findings"] == 1, (
        "the open-findings count is not windowed: the finding still counts"
    )


def test_probation_regime_score_is_time_invariant(api):
    """PRD §3.6: "For a `PROBATION` factory, every finding on a non-`VOIDED`
    `COMPLETED` inspection counts regardless of age, so the score is
    time-invariant and sweeps never touch it."
    PRD §2.5: "Fifth, conformity aging: the `conformity_score` of every
    `STANDARD`-regime factory is recomputed, so findings that have aged out of
    the trailing 24-month window stop counting; `PROBATION`-regime scores are
    time-invariant and are never recomputed on the sweep."

    Design: Difficulty/dual_variant_calc/factory_conformity_window_vs_open_findings_diverge
    """
    fac_f, fac_g = _build_window_divergence(api)
    f_mid = refresh_factory(api, fac_f["id"])
    assert f_mid["conformity_score"] == 60
    assert f_mid["conformity_regime"] == "PROBATION"
    assert f_mid["open_critical_findings"] == 1

    set_clock(api, "2026-09-01T00:00:00Z")
    f = refresh_factory(api, fac_f["id"])
    assert f["conformity_score"] == 60, "PROBATION scores never age"
    assert f["conformity_regime"] == "PROBATION"
    assert f["open_critical_findings"] == 1
    # Contrast: the same finding history aged out for the STANDARD factory.
    g = refresh_factory(api, fac_g["id"])
    assert g["conformity_score"] == 100
    assert g["conformity_regime"] == "STANDARD"


def test_finding_certification_mismatch_returns_422(api, inspector_headers, officer_headers):
    """PRD §3.6: "Each finding carries a `finding_ref`, a `severity` of
    `CRITICAL`, `MAJOR`, or `MINOR`, and a `description`, and may optionally
    name a `certification_id`, which when present must belong to the inspected
    factory (`ERR_FINDING_CERTIFICATION_MISMATCH`)."

    Design: Corner/validations/finding_certification_mismatch_returns_422
    """
    ctx_a = setup_certified(api)
    mfr_b = create_manufacturer(
        api, legal_name="Beacon Power Co", annual_revenue_tier="STANDARD"
    )
    fac_b = create_factory(
        api, mfr_b["id"], site_code="GZ-1", country_code="CN", jurisdiction_code="CN-GZ"
    )
    ctx_b = setup_certified(
        api,
        {"standard": ctx_a["standard"], "manufacturer": mfr_b, "factory": fac_b},
        project_overrides={"product_model": "BP-9"},
        engineer_id=SECOND_ENGINEER_ID,
    )
    inspection = schedule_inspection(api, ctx_a["factory"]["id"], BASE_CLOCK_ISO)
    response = api.complete_inspection(
        inspection["id"],
        complete_inspection_payload(
            [
                finding_entry(
                    "FD-X",
                    "MAJOR",
                    "Names factory B's certification while inspecting factory A",
                    certification_id=ctx_b["certification"]["id"],
                )
            ]
        ),
        inspector_headers,
    )
    validate_error(response, ApiErrorId.ERR_FINDING_CERTIFICATION_MISMATCH)

    inspections, _meta = validate_paginated(
        api.list_inspections(ctx_a["factory"]["id"], officer_headers)
    )
    view = next(i for i in inspections if i["id"] == inspection["id"])
    assert view["status"] == "SCHEDULED", "a rejected completion leaves it untouched"
    factory_b = refresh_factory(api, fac_b["id"])
    assert factory_b["conformity_score"] == 100, (
        "no finding may leak to the other factory"
    )


def test_critical_finding_suspends_certification_and_license(api, officer_headers):
    """PRD §3.6: "Every `CRITICAL` finding that names a certification also
    suspends that certification, if it is `ACTIVE`, adding a cause string of
    'CRITICAL_FINDING:' followed by the `finding_ref` to its
    `suspension_causes` and cascading the suspension to its mark licenses as
    §3.9 describes."
    PRD §3.7: "Issuance requires the license to be `ACTIVE` — a batch against an
    `EXHAUSTED`, `SUSPENDED`, or `REVOKED` license is rejected with
    `ERR_LICENSE_NOT_ACTIVE`"

    Design: Difficulty/transitive_cascade/critical_finding_cascades_cert_suspend_to_license_block
    """
    ctx = setup_certified_with_license(api)
    cert_id = ctx["certification"]["id"]
    lic_id = ctx["mark_license"]["id"]
    mfr_id = ctx["manufacturer"]["id"]

    inspection = schedule_inspection(api, ctx["factory"]["id"], BASE_CLOCK_ISO)
    complete_inspection(
        api,
        inspection["id"],
        findings=[
            finding_entry(
                "FD-9",
                "CRITICAL",
                "Production unit uses unlisted relay",
                certification_id=cert_id,
            )
        ],
    )

    certification = refresh_certification(api, cert_id)
    assert certification["status"] == "SUSPENDED"
    assert "CRITICAL_FINDING:FD-9" in certification["suspension_causes"]
    license_view = refresh_mark_license(api, lic_id)
    assert license_view["status"] == "SUSPENDED"

    blocked = api.issue_label_batch(
        lic_id, label_batch_payload(100), make_manufacturer_rep_headers(mfr_id)
    )
    validate_error(blocked, ApiErrorId.ERR_LICENSE_NOT_ACTIVE)


def test_critical_finding_drives_factory_probation(api):
    """PRD §3.6: "A `STANDARD` factory drops to `PROBATION` when a new
    `CRITICAL` finding is recorded against it or when its windowed score falls
    below 70."
    PRD §3.6: "Each finding is worth a penalty by `severity`: 40 points for
    `CRITICAL`, 15 for `MAJOR`, and 5 for `MINOR`."
    PRD §3.6: "`open_critical_findings` counts the `CRITICAL` findings on the
    factory's non-`VOIDED` `COMPLETED` inspections"

    Design: Difficulty/transitive_cascade/critical_finding_cascades_cert_suspend_to_license_block
    """
    ctx = setup_certified_with_license(api)
    inspection = schedule_inspection(api, ctx["factory"]["id"], BASE_CLOCK_ISO)
    complete_inspection(
        api,
        inspection["id"],
        findings=[
            finding_entry(
                "FD-9",
                "CRITICAL",
                "Production unit uses unlisted relay",
                certification_id=ctx["certification"]["id"],
            )
        ],
    )
    factory = refresh_factory(api, ctx["factory"]["id"])
    assert factory["open_critical_findings"] == 1
    assert factory["conformity_score"] == 60
    assert factory["conformity_regime"] == "PROBATION"


def test_inspection_gap_boundary_25_days(api, inspector_headers):
    """PRD §3.6: "The buffer compares the absolute difference between the two
    scheduled instants in whole days; a gap of exactly 25 days is allowed, and
    anything smaller is rejected with `ERR_INSPECTION_GAP_VIOLATION`."

    Design: Difficulty/resource_temporal_overlap/factory_inspection_minimum_gap_buffer
    """
    ctx = setup_world(api)
    factory_id = ctx["factory"]["id"]
    schedule_inspection(api, factory_id, "2026-10-01T00:00:00Z")

    too_close = api.schedule_inspection(
        factory_id, inspection_payload("2026-10-25T00:00:00Z"), inspector_headers
    )
    validate_error(too_close, ApiErrorId.ERR_INSPECTION_GAP_VIOLATION)

    exactly = api.schedule_inspection(
        factory_id, inspection_payload("2026-10-26T00:00:00Z"), inspector_headers
    )
    data = validate_success(exactly, 201)
    assert data["status"] == "SCHEDULED"


def test_inspection_gap_bidirectional_absolute_difference(api, inspector_headers):
    """PRD §3.6: "The buffer compares the absolute difference between the two
    scheduled instants in whole days; a gap of exactly 25 days is allowed, and
    anything smaller is rejected with `ERR_INSPECTION_GAP_VIOLATION`."

    Design: Difficulty/resource_temporal_overlap/factory_inspection_minimum_gap_buffer
    """
    ctx = setup_world(api)
    factory_id = ctx["factory"]["id"]
    schedule_inspection(api, factory_id, "2026-10-01T00:00:00Z")

    # 24 days before the existing inspection: the absolute difference is < 25.
    too_close = api.schedule_inspection(
        factory_id, inspection_payload("2026-09-07T00:00:00Z"), inspector_headers
    )
    validate_error(too_close, ApiErrorId.ERR_INSPECTION_GAP_VIOLATION)

    # Exactly 25 days before: the boundary passes in both directions.
    exactly = api.schedule_inspection(
        factory_id, inspection_payload("2026-09-06T00:00:00Z"), inspector_headers
    )
    data = validate_success(exactly, 201)
    assert data["status"] == "SCHEDULED"
