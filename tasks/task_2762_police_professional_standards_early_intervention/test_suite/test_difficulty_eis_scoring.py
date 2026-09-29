"""The early-intervention composite score: its two variants, its five factors and its edges."""

from test_helpers import SYSTEM_ADMIN_HEADERS, assert_eis_profile, assert_officer_ledgers
from test_helpers import assert_eis_run_counters, assert_officer_risk, assert_two_dp
from test_helpers import fixtures


FIVE_EVENTS = fixtures.FIVE_EVENT_ALERT_PATTERN


def south_peer_group(api, world):
    """Three patrol officers in one peer group: the subject, a busy peer and an idle peer."""
    unit = fixtures.create_unit(
        api,
        name="Patrol South",
        command_code="PS",
        peer_group_code="PG_SOUTH",
        sworn_headcount=3,
        intake_enabled=True,
    )
    subject = fixtures.create_officer(
        api, unit["id"], badge_number="PS-201", full_name="Officer Kerr"
    )
    busy_peer = fixtures.create_officer(
        api, unit["id"], badge_number="PS-202", full_name="Officer Lund", demographic_code="DG_A"
    )
    idle_peer = fixtures.create_officer(
        api, unit["id"], badge_number="PS-203", full_name="Officer Moss", demographic_code="DG_D"
    )
    fixtures.ingest_event_pattern(api, subject["id"], FIVE_EVENTS)
    fixtures.ingest_event_pattern(
        api,
        busy_peer["id"],
        (
            ("USE_OF_FORCE", "LEVEL_3", "2026-06-01T00:00:00Z", "L-1"),
            ("USE_OF_FORCE", "LEVEL_3", "2026-06-05T00:00:00Z", "L-2"),
            ("USE_OF_FORCE", "LEVEL_3", "2026-06-10T00:00:00Z", "L-3"),
            ("USE_OF_FORCE", "LEVEL_3", "2026-06-15T00:00:00Z", "L-4"),
            ("USE_OF_FORCE", "LEVEL_3", "2026-06-20T00:00:00Z", "L-5"),
        ),
    )
    return {"unit_id": unit["id"], "subject_id": subject["id"], "peer_ids": [busy_peer["id"], idle_peer["id"]]}


def test_the_rolling_variant_applies_the_multiplier_and_the_indicator_bonus(api, world):
    """The default variant carries a weighted total of 17.50 to a score of 63.75.

    PRD: A patrol officer with a weighted total of 17.5 and two breached indicators scores 63.75, which lands in the `ALERT` band.
    Design: Difficulty/dual_variant_calc/eis_rolling_window_versus_peer_relative_score
    """
    group = south_peer_group(api, world)

    profile = fixtures.read_eis_profile(
        api, group["subject_id"], world["admin_headers"], {"variant": "ROLLING_12M"}
    )

    assert_eis_profile(
        profile,
        event_count=5,
        weighted_total=17.50,
        composite_score=63.75,
        alert_level="ALERT",
        breached_indicators=["FORCE_COUNT", "PURSUIT_COUNT"],
    )
    officer = fixtures.read_officer(api, group["subject_id"], world["admin_headers"])
    assert_officer_risk(officer, eis_score=63.75, eis_alert_level="ALERT")


def test_the_peer_relative_variant_drops_the_multiplier_and_the_bonus(api, world):
    """The same history scores 46.67 at WATCH against a peer mean of 15.00.

    PRD: The score is the subject's weighted total divided by `peer_mean`, multiplied by a peer scale of 40, capped at 100 and rounded half up to two decimal places.
    Design: Difficulty/dual_variant_calc/eis_rolling_window_versus_peer_relative_score
    """
    group = south_peer_group(api, world)

    profile = fixtures.read_eis_profile(
        api, group["subject_id"], world["admin_headers"], {"variant": "PEER_RELATIVE"}
    )

    assert profile["peer_pool_size"] == 2
    assert_two_dp(profile["peer_mean"], 15.00, label="peer_mean")
    assert_eis_profile(
        profile, weighted_total=17.50, composite_score=46.67, alert_level="WATCH"
    )

    officer = fixtures.read_officer(api, group["subject_id"], world["admin_headers"])
    assert_officer_risk(officer, eis_score=63.75, eis_alert_level="ALERT")


def west_pair(api, world):
    """Two officers with byte-identical event histories and different assignment types."""
    unit = fixtures.create_unit(
        api,
        name="Patrol West",
        command_code="PW",
        peer_group_code="PG_WEST",
        sworn_headcount=40,
        intake_enabled=True,
    )
    patrol = fixtures.create_officer(
        api,
        unit["id"],
        badge_number="PW-301",
        full_name="Officer Ruiz",
        assignment_type="PATROL",
        demographic_code="DG_A",
    )
    investigative = fixtures.create_officer(
        api,
        unit["id"],
        badge_number="PW-302",
        full_name="Officer Sato",
        assignment_type="INVESTIGATIVE",
        demographic_code="DG_B",
    )
    fixtures.ingest_event_pattern(api, patrol["id"], FIVE_EVENTS)
    fixtures.ingest_event_pattern(api, investigative["id"], FIVE_EVENTS)
    return {"patrol_id": patrol["id"], "investigative_id": investigative["id"]}


def test_the_same_history_scores_lower_for_an_investigative_officer(api, world):
    """Identical events score 63.75 for patrol duty and 55.00 for investigative duty.

    PRD: Its score is the weighted total multiplied by the officer's assignment multiplier — 1.0 for `PATROL`, 0.8 for `INVESTIGATIVE` and 0.6 for `ADMIN`, discounting officers whose duties expose them to fewer incidents — multiplied by a scale factor of 2.5, plus a flat additive bonus of 10 for each breached indicator.
    Design: Difficulty/combinatorial_formula/eis_five_factor_score_assignment_multiplier_and_indicator_bonus
    """
    pair = west_pair(api, world)

    patrol_profile = fixtures.read_eis_profile(api, pair["patrol_id"], world["admin_headers"])
    investigative_profile = fixtures.read_eis_profile(
        api, pair["investigative_id"], world["admin_headers"]
    )

    assert_eis_profile(
        patrol_profile,
        event_count=5,
        weighted_total=17.50,
        composite_score=63.75,
        alert_level="ALERT",
        window_start="2025-08-01T00:00:00Z",
    )
    assert_eis_profile(
        investigative_profile,
        event_count=5,
        weighted_total=17.50,
        composite_score=55.00,
        alert_level="ALERT",
    )


def test_the_assignment_multiplier_is_applied_before_the_additive_bonus(api, world):
    """The 8.75 gap between the two officers is 17.50 times 0.2 times 2.5.

    PRD: The `ROLLING_12M` variant is the default and the only one written to the officer record.
    Design: Difficulty/combinatorial_formula/eis_five_factor_score_assignment_multiplier_and_indicator_bonus
    """
    pair = west_pair(api, world)

    patrol_officer = fixtures.read_officer(api, pair["patrol_id"], world["admin_headers"])
    investigative_officer = fixtures.read_officer(
        api, pair["investigative_id"], world["admin_headers"]
    )

    assert_officer_risk(patrol_officer, eis_score=63.75, eis_alert_level="ALERT")
    assert_officer_risk(investigative_officer, eis_score=55.00, eis_alert_level="ALERT")
    gap = float(patrol_officer["eis_score"]) - float(investigative_officer["eis_score"])
    assert_two_dp(gap, 17.50 * (1.0 - 0.8) * 2.5, label="score gap")


def east_pair(api):
    """A bare roster of exactly two active officers, one of them carrying six events."""
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    unit = fixtures.create_unit(
        api,
        name="Patrol East",
        command_code="PE",
        peer_group_code="PG_EAST",
        sworn_headcount=25,
        intake_enabled=True,
    )
    subject = fixtures.create_officer(
        api, unit["id"], badge_number="PE-401", full_name="Officer Kerr"
    )
    other = fixtures.create_officer(
        api, unit["id"], badge_number="PE-402", full_name="Officer Nash", demographic_code="DG_A"
    )
    fixtures.ingest_event_pattern(
        api,
        subject["id"],
        FIVE_EVENTS + (("USE_OF_FORCE", "LEVEL_3", "2026-07-25T00:00:00Z", "K-6"),),
    )
    return {"subject_id": subject["id"], "other_id": other["id"]}


def test_relief_from_duty_leaves_the_risk_dimension_untouched(api):
    """An officer relieved of duty keeps the score of 78.75 and the CRITICAL band.

    PRD: Neither constrains the other: a `SEPARATED` officer keeps accumulating EIS history for reporting purposes, and an officer at `CRITICAL` risk remains `ACTIVE` unless discipline or an administrative decision moves the employment dimension.
    Design: Difficulty/non_linear_state_machine/officer_employment_and_risk_dimensions_advance_independently
    """
    roster = east_pair(api)

    before = fixtures.read_officer(api, roster["subject_id"], SYSTEM_ADMIN_HEADERS)
    assert_officer_risk(before, eis_score=78.75, eis_alert_level="CRITICAL")
    assert before["employment_status"] == "ACTIVE"

    relieved = fixtures.separate_officer(api, roster["subject_id"], status="RELIEVED_OF_DUTY")

    assert relieved["employment_status"] == "RELIEVED_OF_DUTY"
    assert_officer_risk(relieved, eis_score=78.75, eis_alert_level="CRITICAL")
    assert relieved["suspension_end_date"] is None
    assert_officer_ledgers(relieved, imposed_suspension_days_total=0)


def test_the_department_wide_sweep_visits_only_active_officers(api):
    """A relieved officer still rescores on ingest but is skipped by the sweep.

    PRD: It rescores every `ACTIVE` officer under the rolling variant, or the single named officer.
    Design: Difficulty/non_linear_state_machine/officer_employment_and_risk_dimensions_advance_independently
    """
    roster = east_pair(api)
    fixtures.separate_officer(api, roster["subject_id"], status="RELIEVED_OF_DUTY")

    fixtures.record_activity_event(
        api, roster["subject_id"], "PURSUIT", "2026-07-28T00:00:00Z", severity_code="NA"
    )
    rescored = fixtures.read_officer(api, roster["subject_id"], SYSTEM_ADMIN_HEADERS)
    assert_officer_risk(rescored, eis_score=83.75, eis_alert_level="CRITICAL")

    run = fixtures.run_sweep(api, {})

    assert_eis_run_counters(run, evaluated_officer_count=1)
    after = fixtures.read_officer(api, roster["subject_id"], SYSTEM_ADMIN_HEADERS)
    assert after["employment_status"] == "RELIEVED_OF_DUTY"
    idle = fixtures.read_officer(api, roster["other_id"], SYSTEM_ADMIN_HEADERS)
    assert_officer_risk(idle, eis_score=0.00, eis_alert_level="NONE")


def decay_pair(api, world):
    """Two patrol officers with no history at all, ready for a single dated event each."""
    pike = fixtures.create_officer(
        api, world["patrol_unit_id"], badge_number="PN-601", full_name="Officer Pike",
        demographic_code="DG_B",
    )
    quill = fixtures.create_officer(
        api, world["patrol_unit_id"], badge_number="PN-602", full_name="Officer Quill",
        demographic_code="DG_B",
    )
    return {"pike_id": pike["id"], "quill_id": quill["id"]}


def test_decay_halves_one_day_past_the_one_hundred_eighty_day_edge(api, world):
    """An event aged 180 days weighs 3.00; one aged 181 days weighs 1.50.

    PRD: The boundary matters — an event aged exactly 180 days still contributes in full, and one aged 181 days contributes half.
    Design: Difficulty/boundary_precision_check/eis_decay_and_window_edges_at_one_hundred_eighty_and_three_hundred_sixty_five_days
    """
    pair = decay_pair(api, world)

    fresh_event = fixtures.record_activity_event(
        api, pair["pike_id"], "USE_OF_FORCE", "2026-02-02T00:00:00Z", severity_code="LEVEL_1",
        source_reference="UOF-180",
    )
    fixtures.record_activity_event(
        api, pair["quill_id"], "USE_OF_FORCE", "2026-02-01T00:00:00Z", severity_code="LEVEL_1",
        source_reference="UOF-181",
    )

    assert_two_dp(fresh_event["base_weight"], 3, label="base_weight")

    fresh_profile = fixtures.read_eis_profile(api, pair["pike_id"], world["admin_headers"])
    stale_profile = fixtures.read_eis_profile(api, pair["quill_id"], world["admin_headers"])

    assert_eis_profile(
        fresh_profile,
        event_count=1,
        weighted_total=3.00,
        composite_score=7.50,
        alert_level="NONE",
        window_start="2025-08-01T00:00:00Z",
    )
    assert_eis_profile(
        stale_profile,
        event_count=1,
        weighted_total=1.50,
        composite_score=3.75,
        alert_level="NONE",
    )


def test_an_event_aged_exactly_three_hundred_sixty_five_days_is_excluded(api, world):
    """The left edge of the window is open: 365 days out scores nothing, 364 scores half.

    PRD: An event exactly 365 days old is therefore excluded and contributes nothing.
    Design: Difficulty/boundary_precision_check/eis_decay_and_window_edges_at_one_hundred_eighty_and_three_hundred_sixty_five_days
    """
    pair = decay_pair(api, world)
    fixtures.record_activity_event(
        api, pair["pike_id"], "USE_OF_FORCE", "2026-02-02T00:00:00Z", severity_code="LEVEL_1",
        source_reference="UOF-180",
    )

    fixtures.record_activity_event(
        api, pair["pike_id"], "USE_OF_FORCE", "2025-08-01T00:00:00Z", severity_code="LEVEL_1",
        source_reference="UOF-365",
    )
    excluded = fixtures.read_eis_profile(api, pair["pike_id"], world["admin_headers"])
    assert_eis_profile(excluded, event_count=1, weighted_total=3.00)

    fixtures.record_activity_event(
        api, pair["pike_id"], "USE_OF_FORCE", "2025-08-02T00:00:00Z", severity_code="LEVEL_1",
        source_reference="UOF-364",
    )
    included = fixtures.read_eis_profile(api, pair["pike_id"], world["admin_headers"])
    assert_eis_profile(
        included,
        event_count=2,
        weighted_total=4.50,
        composite_score=11.25,
        alert_level="NONE",
    )

    officer = fixtures.read_officer(api, pair["pike_id"], world["admin_headers"])
    assert_officer_risk(officer, eis_score=11.25, eis_alert_level="NONE")
    assert_officer_ledgers(officer, open_alert_count=0)

    stored, _ = fixtures.rows(api.list_activity_events(pair["pike_id"], world["admin_headers"]))
    assert len(stored) == 3
