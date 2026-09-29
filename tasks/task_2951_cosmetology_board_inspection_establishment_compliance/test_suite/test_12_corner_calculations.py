"""Corner coverage for the derived-calculation layer (SCAFFOLD_CORNER_DESIGN §calculations).

Every test in this module translates exactly one non-stub `instance` of the
`calculations` section of the corner design index, and asserts only values the
PRD derives uniquely.
"""
from test_helpers import (
    BOARD_ADMIN_HEADERS,
    INSPECTOR_HEADERS,
    NOTIFICATION_WINDOW_HOURS_MULTI_CASE,
    NOTIFICATION_WINDOW_HOURS_SINGLE_CASE,
    POSTURE_WATCH_DEMERITS,
    REPEAT_FACTOR_NONE,
    REPEAT_FACTOR_ONE,
    advance_clock,
    assert_cents,
    assert_fine_breakdown,
    assert_instants_equal,
    assert_points,
    citation_payload,
    create_candidate,
    create_establishment,
    create_licensed_practitioner,
    create_school,
    create_violation_code,
    infection_incident_payload,
    issue_citation,
    license_action_payload,
    refresh_booth_rental,
    refresh_establishment,
    refresh_inspection,
    refresh_practitioner,
    refresh_workstation,
    sanitation_log_payload,
    setup_establishment_with_posted_practitioner,
    setup_finalized_inspection,
    setup_substantiated_incident,
    training_record_payload,
    validate_paginated,
    validate_success,
)


def test_repeat_factor_rises_to_one_point_five_after_one_prior_finalized_inspection(api):
    """A second identical finding scores 6.00 where the first scored 4.00.

    PRD 3.5: the repeat count is "the number of findings on *other* inspections
    that cite the very same `violation_code_id` ... whose inspection's `status`
    is `FINALIZED`, and whose inspection's `finalized_at` falls at or after the
    cutoff instant pulled back by 730 days ... and strictly before the cutoff
    instant itself", and the factor is "1.0 when the count is zero, 1.5 when the
    count is exactly one".
    Design: Corner/calculations/calculation_repeat_factor_rises_to_one_point_five_after_one_prior_finalized_inspection
    """
    code = create_violation_code(
        api, severity="MINOR", base_points=4.00, fine_cents_base=4000, code="SAN-970"
    )
    est = create_establishment(api, county_code="ABS", station_capacity=4)
    spec = {"violation_code_id": code["id"], "observed_count": 1, "corrected_on_site": False}

    first = setup_finalized_inspection(api, est["id"], findings=[spec], window_index=0)
    # The upper bound of the lookback is strict, so the prior inspection must be
    # finalized strictly before the second inspection's cutoff instant.
    advance_clock(api, "2026-08-05T00:00:00.000Z")
    second = setup_finalized_inspection(api, est["id"], findings=[spec], window_index=3)

    early = validate_success(
        api.get_violation_finding(first["findings"][0]["id"], BOARD_ADMIN_HEADERS)
    )
    assert_points(early["repeat_factor_final"], REPEAT_FACTOR_NONE, "repeat_factor_final")
    assert_points(early["final_points"], 4.00, "final_points")

    repeat = validate_success(
        api.get_violation_finding(second["findings"][0]["id"], BOARD_ADMIN_HEADERS)
    )
    assert_points(
        repeat["repeat_factor_provisional"], REPEAT_FACTOR_ONE, "repeat_factor_provisional"
    )
    assert_points(repeat["repeat_factor_final"], REPEAT_FACTOR_ONE, "repeat_factor_final")
    assert_points(repeat["final_points"], 6.00, "final_points")

    insp_one = refresh_inspection(api, first["inspection"]["id"])
    assert_points(insp_one["final_adjusted_score"], 4.00, "final_adjusted_score")
    assert insp_one["final_outcome"] == "PASS"

    insp_two = refresh_inspection(api, second["inspection"]["id"])
    assert_points(insp_two["final_adjusted_score"], 6.00, "final_adjusted_score")
    assert insp_two["final_outcome"] == "PASS"
    assert_points(
        insp_two["demerit_balance_before_finalize"], 4.00, "demerit_balance_before_finalize"
    )

    facility = refresh_establishment(api, est["id"])
    assert_points(facility["demerit_balance"], 10.00, "demerit_balance")
    assert facility["compliance_posture"] == "CLEAR"
    assert_instants_equal(
        facility["last_finalized_inspection_at"],
        "2026-08-05T00:00:00.000Z",
        "last_finalized_inspection_at",
    )


def test_score_input_set_excludes_findings_of_other_inspections(api):
    """The second visit scores 5.00, not the establishment-wide 11.00.

    PRD 3.5: "the pass walks the inspection's findings in `created_at` ascending
    order", and PRD 2.5 makes `demerit_balance` the ledger sum over the whole
    establishment, so the two aggregates deliberately disagree.
    Design: Corner/calculations/calculation_score_input_set_excludes_findings_of_other_inspections
    """
    code_a = create_violation_code(
        api, severity="MINOR", base_points=3.00, fine_cents_base=3000, code="SAN-971"
    )
    code_b = create_violation_code(
        api,
        severity="MAJOR",
        base_points=2.00,
        fine_cents_base=7000,
        category="FACILITY",
        code="FAC-972",
    )
    est = create_establishment(api, county_code="ABT", station_capacity=4)

    first = setup_finalized_inspection(
        api,
        est["id"],
        findings=[
            {"violation_code_id": code_a["id"], "observed_count": 1},
            {"violation_code_id": code_a["id"], "observed_count": 1},
        ],
        window_index=0,
    )
    advance_clock(api, "2026-08-05T00:00:00.000Z")
    second = setup_finalized_inspection(
        api,
        est["id"],
        findings=[{"violation_code_id": code_b["id"], "observed_count": 1}],
        window_index=3,
    )

    insp_one = refresh_inspection(api, first["inspection"]["id"])
    assert insp_one["finding_count"] == 2
    assert_points(insp_one["final_adjusted_score"], 6.00, "final_adjusted_score")

    insp_two = refresh_inspection(api, second["inspection"]["id"])
    assert insp_two["finding_count"] == 1
    assert_points(insp_two["final_adjusted_score"], 5.00, "final_adjusted_score")
    assert insp_two["final_outcome"] == "PASS"

    facility = refresh_establishment(api, est["id"])
    assert_points(facility["demerit_balance"], 11.00, "demerit_balance")

    own_rows, own_meta = validate_paginated(
        api.list_violation_findings(
            BOARD_ADMIN_HEADERS, {"inspection_id": insp_two["id"]}
        )
    )
    assert own_meta["total_count"] == 1
    assert len(own_rows) == 1

    _, code_meta = validate_paginated(
        api.list_violation_findings(
            BOARD_ADMIN_HEADERS, {"violation_code_id": code_a["id"]}
        )
    )
    assert code_meta["total_count"] == 2


def test_admin_fee_tier_one_boundary_is_inclusive_at_twenty_five_thousand_cents(api):
    """25000 cents pays 5 percent; 25001 cents pays 8 percent.

    PRD 3.7: "the fee percentage is keyed on `assessed_fine_cents` **alone**:
    5 percent when the assessed fine is at most 25000 cents, 8 percent when it is
    above 25000 and at most 100000 cents".
    Design: Corner/calculations/calculation_admin_fee_tier_one_boundary_is_inclusive_at_twenty_five_thousand_cents
    """
    code_a = create_violation_code(
        api,
        severity="MINOR",
        base_points=1.00,
        fine_cents_base=25000,
        category="RECORDKEEPING",
        code="CB-981",
    )
    code_b = create_violation_code(
        api,
        severity="MINOR",
        base_points=1.00,
        fine_cents_base=25001,
        category="RECORDKEEPING",
        code="CB-982",
    )
    est = create_establishment(api, county_code="ABU", station_capacity=4)

    first = setup_finalized_inspection(
        api,
        est["id"],
        findings=[{"violation_code_id": code_a["id"], "observed_count": 1}],
        window_index=0,
    )
    citation_a = issue_citation(api, first["inspection"]["id"])

    advance_clock(api, "2026-08-05T00:00:00.000Z")
    second = setup_finalized_inspection(
        api,
        est["id"],
        findings=[{"violation_code_id": code_b["id"], "observed_count": 1}],
        window_index=3,
    )
    # The tier multiplier reads the snapshot, which is 1.00 point here, so both
    # citations stay on tier 1.00 and only the fee band differs.
    insp_two = refresh_inspection(api, second["inspection"]["id"])
    assert_points(
        insp_two["demerit_balance_before_finalize"], 1.00, "demerit_balance_before_finalize"
    )
    citation_b = validate_success(
        api.create_citation(
            citation_payload(
                inspection_id=insp_two["id"],
                expected_inspection_version=insp_two["version"],
                subject_type="ESTABLISHMENT",
            ),
            BOARD_ADMIN_HEADERS,
        ),
        201,
    )

    assert_fine_breakdown(citation_a, 25000, 1250, 26250)
    assert_fine_breakdown(citation_b, 25001, 2000, 27001, outstanding_fine_cents=27001)
    assert_points(citation_a["demerit_tier_multiplier"], 1.00, "demerit_tier_multiplier")
    assert_points(citation_b["demerit_tier_multiplier"], 1.00, "demerit_tier_multiplier")
    assert citation_a["max_finding_severity"] == "MINOR"
    assert citation_b["max_finding_severity"] == "MINOR"

    facility = refresh_establishment(api, est["id"])
    assert_cents(
        facility["outstanding_fine_total_cents"], 53251, "outstanding_fine_total_cents"
    )
    assert facility["open_critical_citation_count"] == 0


def test_fine_ceiling_clamp_is_inclusive_at_two_hundred_fifty_thousand_cents(api):
    """A raw 250000 passes through; a raw 250001 is clamped to 250000.

    PRD 3.7: "The ceiling clamp is inclusive at the boundary, so a raw amount of
    exactly 250000 cents passes through untouched while 250001 cents is clamped
    to 250000."
    Design: Corner/calculations/calculation_fine_ceiling_clamp_is_inclusive_at_two_hundred_fifty_thousand_cents
    """
    code_a = create_violation_code(
        api,
        severity="MINOR",
        base_points=1.00,
        fine_cents_base=250000,
        category="FACILITY",
        code="CC-983",
    )
    code_b = create_violation_code(
        api,
        severity="MINOR",
        base_points=1.00,
        fine_cents_base=250001,
        category="FACILITY",
        code="CC-984",
    )
    est = create_establishment(api, county_code="ABV", station_capacity=4)

    first = setup_finalized_inspection(
        api,
        est["id"],
        findings=[{"violation_code_id": code_a["id"], "observed_count": 1}],
        window_index=0,
    )
    citation_a = issue_citation(api, first["inspection"]["id"])

    advance_clock(api, "2026-08-05T00:00:00.000Z")
    second = setup_finalized_inspection(
        api,
        est["id"],
        findings=[{"violation_code_id": code_b["id"], "observed_count": 1}],
        window_index=3,
    )
    insp_two = refresh_inspection(api, second["inspection"]["id"])
    citation_b = validate_success(
        api.create_citation(
            citation_payload(
                inspection_id=insp_two["id"],
                expected_inspection_version=insp_two["version"],
                subject_type="ESTABLISHMENT",
            ),
            BOARD_ADMIN_HEADERS,
        ),
        201,
    )

    assert_fine_breakdown(citation_a, 250000, 30000, 280000)
    assert_fine_breakdown(citation_b, 250000, 30000, 280000)

    facility = refresh_establishment(api, est["id"])
    assert_cents(
        facility["outstanding_fine_total_cents"], 560000, "outstanding_fine_total_cents"
    )
    assert_cents(
        facility["delinquent_fine_total_cents"], 0, "delinquent_fine_total_cents"
    )
    assert_points(facility["demerit_balance"], 2.00, "demerit_balance")
    assert facility["compliance_posture"] == "CLEAR"


def test_posture_watch_threshold_is_inclusive_at_exactly_twenty_demerits(api):
    """20.00 demerits opens WATCH; 15.00 stays CLEAR under the same outcome band.

    PRD 2.6: "Otherwise it is `WATCH` when `demerit_balance` has reached 20.00
    points or more", and "the boundaries are inclusive at the threshold".
    Design: Corner/calculations/calculation_posture_watch_threshold_is_inclusive_at_exactly_twenty_demerits
    """
    code = create_violation_code(
        api,
        severity="MAJOR",
        base_points=2.00,
        fine_cents_base=6000,
        category="FACILITY",
        code="MAJ-985",
    )
    watch_est = create_establishment(api, county_code="ABW", station_capacity=4)
    below_est = create_establishment(api, county_code="ABX", station_capacity=4)

    # 2.00 base x 2.5 MAJOR weight x observed_count, repeat factor 1.0.
    watch = setup_finalized_inspection(
        api,
        watch_est["id"],
        findings=[{"violation_code_id": code["id"], "observed_count": 4}],
        window_index=0,
    )
    below = setup_finalized_inspection(
        api,
        below_est["id"],
        findings=[{"violation_code_id": code["id"], "observed_count": 3}],
        window_index=0,
    )

    assert_points(
        watch["inspection"]["final_adjusted_score"],
        POSTURE_WATCH_DEMERITS,
        "final_adjusted_score",
    )
    assert watch["inspection"]["final_outcome"] == "CONDITIONAL_PASS"
    assert_points(below["inspection"]["final_adjusted_score"], 15.00, "final_adjusted_score")
    assert below["inspection"]["final_outcome"] == "CONDITIONAL_PASS"

    watch_facility = refresh_establishment(api, watch_est["id"])
    assert_points(watch_facility["demerit_balance"], 20.00, "demerit_balance")
    assert watch_facility["compliance_posture"] == "WATCH"
    below_facility = refresh_establishment(api, below_est["id"])
    assert_points(below_facility["demerit_balance"], 15.00, "demerit_balance")
    assert below_facility["compliance_posture"] == "CLEAR"
    # PRD 3.7 hop four promotes both facilities on a CONDITIONAL_PASS, so the
    # posture difference cannot be explained by the licence status.
    assert watch_facility["license_status"] == "ACTIVE"
    assert below_facility["license_status"] == "ACTIVE"

    _, posture_meta = validate_paginated(
        api.list_establishments(BOARD_ADMIN_HEADERS, {"compliance_posture": "WATCH"})
    )
    assert posture_meta["total_count"] == 1

    rows, ledger_meta = validate_paginated(
        api.list_ledger_entries(
            BOARD_ADMIN_HEADERS,
            {"establishment_id": watch_est["id"], "ledger_type": "DEMERIT_POINTS"},
        )
    )
    assert ledger_meta["total_count"] == 1
    assert_points(rows[0]["delta_points"], 20.00, "delta_points")


def test_notification_window_shrinks_to_twenty_four_hours_at_two_cases(api):
    """One case gets 72 hours; two cases get 24.

    PRD 3.9: "A cluster of two or more cases must be reported within 24 hours of
    `reported_at`; a single-case cluster has 72 hours ... The threshold is
    inclusive, so a `case_count` of 1 gets the 72-hour window and a `case_count`
    of 2 gets the 24-hour one."
    Design: Corner/calculations/calculation_notification_window_shrinks_to_twenty_four_hours_at_two_cases
    """
    est = create_establishment(
        api, establishment_type="ESTHETICS_SPA", county_code="ABY", station_capacity=4
    )

    single = validate_success(
        api.create_infection_incident(
            infection_incident_payload(
                establishment_id=est["id"],
                case_count=1,
                onset_date="2026-07-28",
                narrative="Single client reported a post-facial rash.",
            ),
            INSPECTOR_HEADERS,
        ),
        201,
    )
    multi = validate_success(
        api.create_infection_incident(
            infection_incident_payload(
                establishment_id=est["id"],
                case_count=2,
                onset_date="2026-07-29",
                narrative="Two clients reported post-facial folliculitis.",
            ),
            INSPECTOR_HEADERS,
        ),
        201,
    )

    assert NOTIFICATION_WINDOW_HOURS_SINGLE_CASE == 72
    assert NOTIFICATION_WINDOW_HOURS_MULTI_CASE == 24
    assert_instants_equal(single["reported_at"], "2026-08-01T00:00:00.000Z", "reported_at")
    assert_instants_equal(
        single["notification_deadline_at"],
        "2026-08-04T00:00:00.000Z",
        "notification_deadline_at",
    )
    assert_instants_equal(multi["reported_at"], "2026-08-01T00:00:00.000Z", "reported_at")
    assert_instants_equal(
        multi["notification_deadline_at"],
        "2026-08-02T00:00:00.000Z",
        "notification_deadline_at",
    )
    for incident in (single, multi):
        assert incident["status"] == "REPORTED"
        assert incident["suspected_practitioner_id"] is None

    facility = refresh_establishment(api, est["id"])
    assert facility["compliance_posture"] == "CLEAR"

    _, meta = validate_paginated(
        api.list_infection_incidents(BOARD_ADMIN_HEADERS, {"establishment_id": est["id"]})
    )
    assert meta["total_count"] == 2


def test_apprentice_hours_below_the_daily_cap_are_credited_in_full(api):
    """3.0 + 4.0 hours on one day pool to 7.00 credited hours, not 8.00.

    PRD 3.2: for a candidate "whose `license_type` is anything other than
    `APPRENTICE` ... the identical set of apprentice-hour records is instead
    pooled by `performed_on` UTC date, each date's total capped at the same
    eight-hour daily cap, credited at a ratio of 1.00".
    Design: Corner/calculations/calculation_apprentice_hours_below_the_daily_cap_are_credited_in_full
    """
    sponsor_school = create_school(
        api,
        required_clock_hours=16.00,
        accreditation_status="ACCREDITED",
        apprenticeship_program_approved=True,
        county_code="ABZ",
    )
    pupil_school = create_school(
        api,
        required_clock_hours=100.00,
        accreditation_status="ACCREDITED",
        county_code="ACA",
    )
    # PRD 3.2 sponsor eligibility: a different practitioner, not an APPRENTICE,
    # whose licence is ACTIVE.
    sponsor = create_licensed_practitioner(
        api,
        school_id=sponsor_school["id"],
        license_type="INSTRUCTOR",
        full_name="Rhea Cole",
    )
    subject = create_candidate(
        api,
        school_id=pupil_school["id"],
        license_type="ESTHETICIAN",
        full_name="Tomas Ib",
    )

    for hours, discipline in ((3.00, "PRACTICAL"), (4.00, "SANITATION")):
        validate_success(
            api.create_training_record(
                training_record_payload(
                    practitioner_id=subject["id"],
                    credit_type="APPRENTICE_HOUR",
                    hours=hours,
                    performed_on="2026-07-20",
                    discipline=discipline,
                    sponsor_practitioner_id=sponsor["id"],
                ),
                BOARD_ADMIN_HEADERS,
            ),
            201,
        )

    pupil = refresh_practitioner(api, subject["id"])
    assert_points(pupil["credited_hours_apprentice"], 7.00, "credited_hours_apprentice")
    assert_points(pupil["credited_hours_school"], 0.00, "credited_hours_school")
    assert_points(pupil["credited_hours_total"], 7.00, "credited_hours_total")
    assert_points(
        pupil["required_clock_hours_effective"], 100.00, "required_clock_hours_effective"
    )
    assert pupil["exam_eligible"] is False
    assert pupil["license_status"] == "STUDENT"
    assert refresh_practitioner(api, sponsor["id"])["license_status"] == "ACTIVE"

    _, meta = validate_paginated(
        api.list_training_records(
            BOARD_ADMIN_HEADERS, {"sponsor_practitioner_id": sponsor["id"]}
        )
    )
    assert meta["total_count"] == 2


def test_posting_projection_degrades_to_stale_when_the_posted_licence_goes_on_probation(api):
    """Probation invalidates the posting without clearing it.

    PRD 3.3: a posting is `COMPLIANT` only when "the posted practitioner's
    `license_status` is `ACTIVE`" alongside the expiry and rental conditions, and
    "If any of the three fails, the verdict is `STALE_POSTING`."
    Design: Corner/calculations/calculation_posting_projection_degrades_to_stale_when_the_posted_licence_goes_on_probation
    """
    salon = setup_establishment_with_posted_practitioner(api)
    station = salon["workstation"]
    practitioner_id = salon["practitioner"]["id"]
    assert station["posting_status"] == "COMPLIANT"

    moved = validate_success(
        api.apply_license_action(
            practitioner_id,
            license_action_payload(
                "PLACE_ON_PROBATION",
                reason="Sanitation deficiencies attributed at a prior inspection.",
            ),
            BOARD_ADMIN_HEADERS,
        )
    )
    assert moved["license_status"] == "PROBATION"
    assert moved["suspension_cause_points"] is None

    # PRD 3.2: PLACE_ON_PROBATION "does nothing else", so the ACTIVE rental and
    # the posting row both survive.
    assert refresh_booth_rental(api, salon["booth_rental"]["id"])["status"] == "ACTIVE"
    refreshed = refresh_workstation(api, station["id"])
    assert refreshed["posted_practitioner_id"] == practitioner_id
    assert refreshed["posting_status"] == "STALE_POSTING"

    _, meta = validate_paginated(
        api.list_workstations(BOARD_ADMIN_HEADERS, {"posting_status": "COMPLIANT"})
    )
    assert meta["total_count"] == 0


def test_last_biofilm_cycle_at_projects_the_latest_weekly_log(api):
    """The station reports the greatest performed_at, not the last row created.

    PRD 3.4: "the station's `last_biofilm_cycle_at` is refreshed to the
    `performed_at` of the most recent such log at that station — choosing by
    `performed_at` descending and then `created_at` descending", and
    `occupancy_end_at` is "`performed_at` advanced by `contact_minutes` minutes".
    Design: Corner/calculations/calculation_last_biofilm_cycle_at_projects_the_latest_weekly_log
    """
    salon = setup_establishment_with_posted_practitioner(api, station_type="FOOT_SPA")
    station_id = salon["workstation"]["id"]

    # The later cycle is filed FIRST, so "most recent" cannot be read off
    # created_at.  Both cycles clear the five-minute inclusive gap by a day.
    later = validate_success(
        api.create_sanitation_log(
            sanitation_log_payload(
                workstation_id=station_id,
                log_type="FOOT_SPA_WEEKLY_BIOFILM",
                performed_at="2026-07-31T12:00:00.000Z",
                contact_minutes=360.00,
                disinfectant_epa_reg_number="EPA-88494-3",
            ),
            BOARD_ADMIN_HEADERS,
        ),
        201,
    )
    earlier = validate_success(
        api.create_sanitation_log(
            sanitation_log_payload(
                workstation_id=station_id,
                log_type="FOOT_SPA_WEEKLY_BIOFILM",
                performed_at="2026-07-30T00:00:00.000Z",
                contact_minutes=400.00,
                disinfectant_epa_reg_number="EPA-88494-3",
            ),
            BOARD_ADMIN_HEADERS,
        ),
        201,
    )

    assert_instants_equal(
        later["occupancy_end_at"], "2026-07-31T18:00:00.000Z", "occupancy_end_at"
    )
    assert_instants_equal(
        earlier["occupancy_end_at"], "2026-07-30T06:40:00.000Z", "occupancy_end_at"
    )

    refreshed = refresh_workstation(api, station_id)
    assert_instants_equal(
        refreshed["last_biofilm_cycle_at"],
        "2026-07-31T12:00:00.000Z",
        "last_biofilm_cycle_at",
    )
    assert refreshed["posting_status"] == "COMPLIANT"
    assert refresh_establishment(api, salon["establishment"]["id"])[
        "foot_spa_biofilm_current"
    ] is True

    _, meta = validate_paginated(
        api.list_workstation_sanitation_logs(
            station_id, BOARD_ADMIN_HEADERS, {"log_type": "FOOT_SPA_WEEKLY_BIOFILM"}
        )
    )
    assert meta["total_count"] == 2


def test_single_substantiated_incident_stays_below_the_suspension_threshold(api):
    """10.00 sanction points leave the licence ACTIVE.

    PRD 3.9: a substantiated resolution "appends a sanction-ledger entry with
    `entry_reason` of `INFECTION_SANCTION_ASSESSMENT` and `delta_points` of
    positive 10.00", and suspension needs "15.00 points or more"; the workflow
    "posts sanction points only, never demerit points".
    Design: Corner/calculations/calculation_single_substantiated_incident_stays_below_the_suspension_threshold
    """
    school = create_school(
        api, required_clock_hours=16.00, accreditation_status="ACCREDITED", county_code="ACF"
    )
    practitioner = create_licensed_practitioner(
        api, school_id=school["id"], license_type="BARBER", full_name="Wes Iyer"
    )
    est = create_establishment(
        api, establishment_type="BARBERSHOP", county_code="ACG", station_capacity=4
    )

    incident = setup_substantiated_incident(
        api, est["id"], practitioner["id"], case_count=1
    )
    assert incident["status"] == "RESOLVED_SUBSTANTIATED"

    sanctioned = refresh_practitioner(api, practitioner["id"])
    assert_points(sanctioned["sanction_points"], 10.00, "sanction_points")
    assert sanctioned["license_status"] == "ACTIVE"
    assert sanctioned["suspension_cause_points"] is None

    rows, sanction_meta = validate_paginated(
        api.list_ledger_entries(
            BOARD_ADMIN_HEADERS,
            {"practitioner_id": practitioner["id"], "ledger_type": "SANCTION_POINTS"},
        )
    )
    assert sanction_meta["total_count"] == 1
    assert rows[0]["entry_reason"] == "INFECTION_SANCTION_ASSESSMENT"
    assert_points(rows[0]["delta_points"], 10.00, "delta_points")

    facility = refresh_establishment(api, est["id"])
    assert_points(facility["demerit_balance"], 0.00, "demerit_balance")
    assert facility["compliance_posture"] == "CLEAR"
    _, demerit_meta = validate_paginated(
        api.list_ledger_entries(
            BOARD_ADMIN_HEADERS,
            {"establishment_id": est["id"], "ledger_type": "DEMERIT_POINTS"},
        )
    )
    assert demerit_meta["total_count"] == 0
