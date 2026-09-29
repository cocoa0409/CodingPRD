"""Breadth coverage for the graded, windowed and denormalized calculations.

Every test in this module translates exactly one instance of the
`calculations` section of the corner design index: visit slot arithmetic, the
denormalized patient projection, the ALT and ANC grade ladders, monitoring
currency, screening validity and the quality report's `URGENT` exclusion.

Each of these rules is read off the logical clock or off an inclusive
threshold, so every test parks the clock explicitly with `fixtures.set_clock`
before the hop whose outcome it governs.
"""
import pytest

from prd_bench_local_runner.testing import validate_success

from test_helpers import api_client, assertions, factories, fixtures
from test_helpers.constants import CLOCK_DEFAULT, instant


# ---------------------------------------------------------------------------
# visit_slot_interval_uses_the_per_visit_type_duration_constant
# ---------------------------------------------------------------------------
def test_visit_end_datetime_uses_the_per_visit_type_slot_length():
    """One clinician books all three visit types on the same day.

    "A `NEW` visit occupies a full hour, a `FOLLOW_UP` visit occupies half an
    hour, and an `URGENT` visit occupies three quarters of an hour; the server
    writes `visit_end_datetime` as the visit's start advanced by that many
    minutes."

    Design: Corner/calculations/visit_slot_interval_uses_the_per_visit_type_duration_constant
    """
    fixtures.set_clock(CLOCK_DEFAULT)
    scenario = fixtures.visit_ready_practice()

    new_visit = fixtures.book_visit(scenario, instant(2026, 8, 3, 8, 0, 0), "NEW")
    follow_up = fixtures.book_visit(scenario, instant(2026, 8, 3, 10, 0, 0), "FOLLOW_UP")
    urgent = fixtures.book_visit(scenario, instant(2026, 8, 3, 11, 0, 0), "URGENT")

    for booked in (new_visit, follow_up, urgent):
        assertions.assert_visit(booked)

    assertions.assert_instant_equals(
        new_visit["visit_end_datetime"], instant(2026, 8, 3, 9, 0, 0), "NEW visit_end_datetime"
    )
    assertions.assert_instant_equals(
        follow_up["visit_end_datetime"],
        instant(2026, 8, 3, 10, 30, 0),
        "FOLLOW_UP visit_end_datetime",
    )
    assertions.assert_instant_equals(
        urgent["visit_end_datetime"],
        instant(2026, 8, 3, 11, 45, 0),
        "URGENT visit_end_datetime",
    )


# ---------------------------------------------------------------------------
# patient_projection_winner_is_the_latest_visit_datetime_not_the_latest_scoring
# ---------------------------------------------------------------------------
def test_patient_projection_prefers_the_latest_visit_datetime_over_scoring_order():
    """Score the newer visit first, then back-fill the older one.

    "Because the winner is chosen by `visit_datetime` and not by the order in
    which visits were scored, back-filling an older visit after a newer one
    has already been scored leaves the patient's denormalized figures exactly
    as they were — the older visit simply loses the comparison."

    Design: Corner/calculations/patient_projection_winner_is_the_latest_visit_datetime_not_the_latest_scoring
    """
    fixtures.set_clock(instant(2026, 8, 3, 15, 0, 0))
    scenario = fixtures.visit_ready_practice()

    late = fixtures.book_visit(scenario, instant(2026, 8, 3, 14, 0, 0), "FOLLOW_UP")
    early = fixtures.book_visit(scenario, instant(2026, 8, 1, 14, 0, 0), "FOLLOW_UP")
    fixtures.check_in_visit(scenario, late["id"])
    fixtures.check_in_visit(scenario, early["id"])

    scored_late = fixtures.score_visit(
        scenario,
        factories.score_visit_cdai_payload(
            tender_joint_count=6,
            swollen_joint_count=5,
            patient_global_assessment=3.0,
            physician_global_assessment=3.0,
        ),
        late["id"],
    )
    assert scored_late["activity_score"] == pytest.approx(17.00, abs=0.01)
    assert scored_late["activity_category"] == "MODERATE"

    after_late = scenario.refresh_patient()
    assert after_late["latest_activity_score"] == pytest.approx(17.00, abs=0.01)
    assert after_late["latest_activity_category"] == "MODERATE"
    assert after_late["target_status"] == "NOT_AT_TARGET"
    version_after_late = after_late["version"]

    scored_early = fixtures.score_visit(
        scenario,
        factories.score_visit_cdai_payload(
            tender_joint_count=1,
            swollen_joint_count=1,
            patient_global_assessment=2.0,
            physician_global_assessment=2.0,
        ),
        early["id"],
    )
    assert scored_early["activity_score"] == pytest.approx(6.00, abs=0.01)
    assert scored_early["activity_category"] == "LOW"

    after_early = scenario.refresh_patient()
    assert after_early["latest_activity_score"] == pytest.approx(17.00, abs=0.01), (
        "the back-filled older visit must not overwrite the newer winner"
    )
    assert after_early["latest_activity_category"] == "MODERATE"
    assert after_early["target_status"] == "NOT_AT_TARGET"
    assert after_early["version"] == version_after_late + 1, (
        "every successful scoring increments the patient's version by one"
    )


# ---------------------------------------------------------------------------
# alt_grade_ladder_uses_inclusive_upper_bounds
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "alt_u_l, expected_grade",
    [
        (40.0, 0),
        (40.1, 1),
        (120.0, 1),
        (120.1, 2),
        (200.0, 2),
        (200.1, 3),
        (400.0, 3),
        (400.1, 4),
    ],
)
def test_alt_grade_ladder_upper_bounds_are_inclusive(alt_u_l, expected_grade):
    """Walk every rung of the ALT ladder from one side of the bound to the other.

    "`alt_grade` is 0 when `alt_u_l` is absent or is at most 40, 1 when it is
    greater than 40 and at most 120, 2 when it is greater than 120 and at most
    200, 3 when it is greater than 200 and at most 400, and 4 when it exceeds
    400 — the upper bounds are inclusive, so a value of exactly 200.0 grades 2
    while 200.1 grades 3."

    Design: Corner/calculations/alt_grade_ladder_uses_inclusive_upper_bounds
    """
    fixtures.set_clock(CLOCK_DEFAULT)
    scenario = fixtures.planned_episode()

    payload = factories.create_monitoring_lab_payload(
        scenario.episode_id,
        panel_type="CMP",
        collected_at=instant(2026, 7, 30),
        alt_u_l=alt_u_l,
    )
    payload.pop("neutrophil_k_ul", None)
    lab = validate_success(
        api_client.create_monitoring_lab(payload, scenario.nurse_headers), 201
    )

    assertions.assert_monitoring_lab(lab)
    assert lab["alt_grade"] == expected_grade, (
        f"alt_u_l {alt_u_l} must grade {expected_grade}"
    )
    assert lab["anc_grade"] == 0, "an absent neutrophil component grades 0"
    assert lab["abnormal_grade"] == expected_grade
    assert lab["triggers_hold"] is (expected_grade >= 3)


def test_alt_two_hundred_grades_two_while_two_hundred_point_one_grades_three():
    """Two panels one tenth of a unit apart on a `PLANNED` episode.

    "`alt_grade` is 0 when `alt_u_l` is absent or is at most 40, 1 when it is
    greater than 40 and at most 120, 2 when it is greater than 120 and at most
    200, 3 when it is greater than 200 and at most 400, and 4 when it exceeds
    400 — the upper bounds are inclusive, so a value of exactly 200.0 grades 2
    while 200.1 grades 3."

    Design: Corner/calculations/alt_grade_ladder_uses_inclusive_upper_bounds
    """
    fixtures.set_clock(CLOCK_DEFAULT)
    scenario = fixtures.planned_episode()

    at_bound = fixtures.file_monitoring_lab(
        scenario,
        panel_type="CMP",
        collected_at=instant(2026, 7, 30),
        alt_u_l=200.0,
        neutrophil_k_ul=3.20,
    )
    assert at_bound["alt_grade"] == 2
    assert at_bound["abnormal_grade"] == 2
    assert at_bound["triggers_hold"] is False

    over_bound = fixtures.file_monitoring_lab(
        scenario,
        panel_type="CMP",
        collected_at=instant(2026, 7, 31),
        alt_u_l=200.1,
        neutrophil_k_ul=3.20,
    )
    assert over_bound["alt_grade"] == 3
    assert over_bound["abnormal_grade"] == 3
    assert over_bound["triggers_hold"] is True

    episode = scenario.refresh_episode()
    assert episode["therapy_state"] == "PLANNED", (
        "a grade-3 panel on a PLANNED episode is graded but drives no hold"
    )
    assert episode["hold_count"] == 0


# ---------------------------------------------------------------------------
# anc_grade_ladder_uses_inclusive_lower_bounds_and_absent_components_grade_zero
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "neutrophil_k_ul, expected_grade",
    [
        (1.5, 0),
        (1.49, 1),
        (1.0, 1),
        (0.99, 2),
        (0.5, 2),
        (0.49, 3),
        (0.2, 3),
        (0.19, 4),
    ],
)
def test_anc_grade_ladder_lower_bounds_are_inclusive(neutrophil_k_ul, expected_grade):
    """Walk every rung of the ANC ladder from one side of the bound to the other.

    "`anc_grade` runs the other way, on inclusive lower bounds: it is 0 when
    `neutrophil_k_ul` is absent or is at least 1.5, 1 when the count is at
    least 1.0 but below 1.5, 2 when it is at least 0.5 but below 1.0, 3 when it
    is at least 0.2 but below 0.5, and 4 when it is below 0.2 — so a count of
    exactly 0.50 grades 2 while 0.49 grades 3."

    Design: Corner/calculations/anc_grade_ladder_uses_inclusive_lower_bounds_and_absent_components_grade_zero
    """
    fixtures.set_clock(CLOCK_DEFAULT)
    scenario = fixtures.planned_episode(drug_payload=factories.adalimumab_payload())

    payload = factories.create_monitoring_lab_payload(
        scenario.episode_id,
        panel_type="CBC",
        collected_at=instant(2026, 7, 30),
        neutrophil_k_ul=neutrophil_k_ul,
    )
    payload.pop("alt_u_l", None)
    lab = validate_success(
        api_client.create_monitoring_lab(payload, scenario.nurse_headers), 201
    )

    assertions.assert_monitoring_lab(lab)
    assert lab["anc_grade"] == expected_grade, (
        f"neutrophil_k_ul {neutrophil_k_ul} must grade {expected_grade}"
    )
    assert lab["alt_grade"] == 0, "an absent ALT component grades 0"
    assert lab["abnormal_grade"] == expected_grade
    assert lab["triggers_hold"] is (expected_grade >= 3)


def test_anc_absent_component_grades_zero_and_blocks_nothing():
    """A `CBC` panel carrying only a white cell count.

    "An absent component grades as 0 and therefore never blocks therapy on its
    own."

    Design: Corner/calculations/anc_grade_ladder_uses_inclusive_lower_bounds_and_absent_components_grade_zero
    """
    fixtures.set_clock(CLOCK_DEFAULT)
    scenario = fixtures.planned_episode(drug_payload=factories.adalimumab_payload())

    payload = factories.create_monitoring_lab_payload(
        scenario.episode_id,
        panel_type="CBC",
        collected_at=instant(2026, 7, 30),
        wbc_k_ul=5.40,
    )
    payload.pop("alt_u_l", None)
    payload.pop("neutrophil_k_ul", None)
    lab = validate_success(
        api_client.create_monitoring_lab(payload, scenario.nurse_headers), 201
    )

    assertions.assert_monitoring_lab(lab)
    assert lab["alt_grade"] == 0
    assert lab["anc_grade"] == 0
    assert lab["abnormal_grade"] == 0
    assert lab["triggers_hold"] is False

    episode = scenario.refresh_episode()
    assert episode["monitoring_status"] == "CURRENT"
    assert episode["therapy_state"] == "PLANNED"
    assert episode["hold_count"] == 0


# ---------------------------------------------------------------------------
# monitoring_currency_is_inclusive_at_the_interval_and_panel_type_scoped
# ---------------------------------------------------------------------------
def test_monitoring_currency_is_inclusive_at_the_panel_interval():
    """A `CMP` collected 2026-07-25 read at ninety and at ninety-one days.

    "The comparison is inclusive, so an episode whose newest matching panel was
    collected exactly `monitoring_panel_interval_days` ago is still current."

    Design: Corner/calculations/monitoring_currency_is_inclusive_at_the_interval_and_panel_type_scoped
    """
    fixtures.set_clock(CLOCK_DEFAULT)
    scenario = fixtures.planned_episode()
    fixtures.file_monitoring_lab(
        scenario, panel_type="CMP", collected_at=instant(2026, 7, 25)
    )

    fixtures.set_clock(instant(2026, 10, 23))
    at_interval = validate_success(
        api_client.get_therapy_episode(scenario.episode_id, fixtures.ADMIN)
    )
    assertions.assert_therapy_episode(at_interval)
    assert at_interval["monitoring_status"] == "CURRENT", (
        "exactly ninety whole days after collection the panel is still current"
    )

    fixtures.set_clock(instant(2026, 10, 24))
    past_interval = validate_success(
        api_client.get_therapy_episode(scenario.episode_id, fixtures.ADMIN)
    )
    assert past_interval["monitoring_status"] == "OVERDUE", (
        "ninety-one whole days after collection the panel has lapsed"
    )


def test_monitoring_currency_only_counts_the_drugs_own_panel_type():
    """A fresh `CBC` cannot rescue an episode whose drug demands a `CMP`.

    "The server considers only the episode's panels whose `panel_type` equals
    the episode drug's `monitoring_panel_type`; a `CBC` filed against an
    episode whose drug demands `LFT` is stored and graded and can still trigger
    a hold, but it can never establish currency."

    Design: Corner/calculations/monitoring_currency_is_inclusive_at_the_interval_and_panel_type_scoped
    """
    fixtures.set_clock(CLOCK_DEFAULT)
    scenario = fixtures.planned_episode()
    fixtures.file_monitoring_lab(
        scenario, panel_type="CMP", collected_at=instant(2026, 7, 25)
    )

    fixtures.set_clock(instant(2026, 10, 24))
    assert scenario.refresh_episode()["monitoring_status"] == "OVERDUE"

    wrong_panel = fixtures.file_monitoring_lab(
        scenario, panel_type="CBC", collected_at=instant(2026, 10, 24)
    )
    assertions.assert_monitoring_lab(wrong_panel)
    assert wrong_panel["panel_type"] == "CBC"
    assert scenario.refresh_episode()["monitoring_status"] == "OVERDUE", (
        "a CBC never establishes currency for a CMP drug"
    )

    right_panel = fixtures.file_monitoring_lab(
        scenario, panel_type="CMP", collected_at=instant(2026, 10, 24)
    )
    assert right_panel["panel_type"] == "CMP"
    assert scenario.refresh_episode()["monitoring_status"] == "CURRENT", (
        "the matching panel type does establish currency"
    )

    rows, meta = assertions.validate_list(
        api_client.list_episode_monitoring_labs(
            scenario.episode_id, fixtures.ADMIN, params={"panel_type": "CMP"}
        )
    )
    assert meta["total_count"] == 2, "only the two CMP panels match the filter"
    assert all(row["panel_type"] == "CMP" for row in rows)


# ---------------------------------------------------------------------------
# screening_validity_window_is_inclusive_at_365_days_then_expires
# ---------------------------------------------------------------------------
def test_screening_validity_is_inclusive_at_365_days_then_expires():
    """One negative TB IGRA resulted 2026-07-21, read at three clocks.

    "Currency is the pivot: a screening record is **current** when the elapsed
    whole days from its `resulted_at` to the logical clock is at most 365, and
    the boundary is inclusive, so a record resulted exactly 365 days ago is
    still current while one resulted 366 days ago is not."

    Design: Corner/calculations/screening_validity_window_is_inclusive_at_365_days_then_expires
    """
    fixtures.set_clock(CLOCK_DEFAULT)
    scenario = fixtures.bootstrap_reference()
    fixtures.register_patient(scenario)
    screen = fixtures.file_screen(
        scenario,
        "TB_IGRA",
        "NEGATIVE",
        collected_at=instant(2026, 7, 20),
        resulted_at=instant(2026, 7, 21),
    )
    assertions.assert_screening_record(screen)

    fresh = scenario.refresh_patient()
    assert fresh["tb_screen_status"] == "CLEARED"
    assert fresh["hbv_screen_status"] == "INCOMPLETE"

    fixtures.set_clock(instant(2027, 7, 21))
    at_bound = scenario.refresh_patient()
    assert at_bound["tb_screen_status"] == "CLEARED", (
        "exactly 365 whole days after resulted_at the record is still current"
    )
    assert at_bound["hbv_screen_status"] == "INCOMPLETE"

    fixtures.set_clock(instant(2027, 7, 22))
    past_bound = scenario.refresh_patient()
    assert past_bound["tb_screen_status"] == "EXPIRED", (
        "366 whole days after resulted_at no TB record is current any more"
    )
    assert past_bound["hbv_screen_status"] == "INCOMPLETE"


# ---------------------------------------------------------------------------
# quality_report_excludes_urgent_visits_from_both_numerator_and_denominator
# ---------------------------------------------------------------------------
def test_quality_report_excludes_urgent_visits_from_numerator_and_denominator():
    """Three scored visits in the window, one of them `URGENT`.

    "The qualifying denominator is the patient's visits whose `visit_type` is
    `NEW` or `FOLLOW_UP` and whose `visit_datetime` falls inside the half-open
    window; `URGENT` visits are excluded from both numerator and denominator
    everywhere in this report."

    Design: Corner/calculations/quality_report_excludes_urgent_visits_from_both_numerator_and_denominator
    """
    fixtures.set_clock(instant(2026, 8, 20))
    scenario = fixtures.visit_ready_practice()

    new_visit = fixtures.checked_in_visit(scenario, instant(2026, 8, 3, 14, 0, 0), "NEW")
    at_target = fixtures.score_visit(
        scenario,
        factories.score_visit_cdai_payload(
            tender_joint_count=1,
            swollen_joint_count=1,
            patient_global_assessment=2.0,
            physician_global_assessment=2.0,
        ),
        new_visit["id"],
    )
    assert at_target["activity_score"] == pytest.approx(6.00, abs=0.01)
    assert at_target["activity_category"] == "LOW"

    follow_up = fixtures.checked_in_visit(
        scenario, instant(2026, 8, 10, 14, 0, 0), "FOLLOW_UP"
    )
    moderate = fixtures.score_visit(
        scenario,
        factories.score_visit_cdai_payload(
            tender_joint_count=6,
            swollen_joint_count=5,
            patient_global_assessment=3.0,
            physician_global_assessment=3.0,
        ),
        follow_up["id"],
    )
    assert moderate["activity_score"] == pytest.approx(17.00, abs=0.01)
    assert moderate["activity_category"] == "MODERATE"
    assert moderate["escalation_recommendation"] == "OPTIMIZE_CURRENT"

    urgent = fixtures.checked_in_visit(scenario, instant(2026, 8, 17, 14, 0, 0), "URGENT")
    high = fixtures.score_visit(
        scenario,
        factories.score_visit_cdai_payload(
            tender_joint_count=8,
            swollen_joint_count=7,
            patient_global_assessment=4.0,
            physician_global_assessment=4.0,
        ),
        urgent["id"],
    )
    assert high["activity_score"] == pytest.approx(23.00, abs=0.01)
    assert high["activity_category"] == "HIGH"
    assert high["escalation_recommendation"] == "ESCALATE"

    report = validate_success(
        api_client.get_quality_report(
            scenario.patient_id,
            fixtures.ADMIN,
            params={
                "period_start": instant(2026, 8, 1),
                "period_end": instant(2026, 9, 1),
            },
        )
    )

    assert report["qualifying_visit_count"] == 2, "the URGENT visit is not a denominator"
    assert report["scored_visit_count"] == 2
    assert report["at_target_visit_count"] == 1
    assert report["escalation_indicated_count"] == 0, (
        "the only ESCALATE recommendation belongs to the excluded URGENT visit"
    )
    assert report["escalation_acted_count"] == 0
    assert report["administered_dose_count"] == 0

    assert report["completeness_pct"] == pytest.approx(100.0, abs=0.01)
    assert report["treat_to_target_attainment_pct"] == pytest.approx(50.0, abs=0.01)
    assert report["escalation_action_pct"] == pytest.approx(0.0, abs=0.01)
    assert report["biosimilar_uptake_pct"] == pytest.approx(0.0, abs=0.01)
    for key in (
        "completeness_pct",
        "treat_to_target_attainment_pct",
        "escalation_action_pct",
        "biosimilar_uptake_pct",
    ):
        assertions.assert_one_decimal_place(report[key], key)
