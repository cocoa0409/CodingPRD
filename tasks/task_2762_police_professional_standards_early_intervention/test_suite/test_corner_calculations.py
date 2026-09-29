"""Selector ordering, window constants, band boundaries and the two discipline variants."""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import (
    assert_discipline_days,
    assert_eis_profile,
    assert_instant,
    assert_investigation_window,
    assert_officer_ledgers,
    assert_officer_risk,
    assert_two_dp,
)
from test_helpers import factories, fixtures

BASE_CLOCK = "2026-08-01T00:00:00Z"


def four_files_and_a_bench_of_three_investigators(api):
    """Ahn, Briggs and Calder sit idle in internal affairs behind four unassigned Class II files."""
    world = fixtures.seed_reference_data(api)
    briggs = fixtures.create_investigator(
        api,
        world["ia_unit_id"],
        badge_number="IA-102",
        full_name="Investigator Briggs",
        certification_level=3,
        max_case_load=3,
    )
    calder = fixtures.create_investigator(
        api,
        world["ia_unit_id"],
        badge_number="IA-050",
        full_name="Investigator Calder",
        certification_level=2,
        max_case_load=3,
    )
    files = {}
    for key, incident, subject in (
        ("a", "2026-07-11T20:00:00Z", None),
        ("b", "2026-07-12T20:00:00Z", None),
        ("c", "2026-07-13T20:00:00Z", None),
        ("d", "2026-07-14T20:00:00Z", calder["id"]),
    ):
        complaint = fixtures.file_supervisor_complaint(
            api,
            world,
            narrative=f"Reports not filed on shift {key}.",
            incident_datetime=incident,
        )
        fixtures.attach_allegation(
            api,
            world,
            complaint["id"],
            subject_officer_id=subject,
            allegation_type="NEGLECT_OF_DUTY",
            offense_class="B",
        )
        investigation = fixtures.open_investigation(api, world, complaint["id"])
        files[key] = {
            "c_id": complaint["id"],
            "i_id": investigation["id"],
            "version": investigation["version"],
            "status": investigation["status"],
            "required_certification_level": investigation["required_certification_level"],
        }
    world.update({"briggs_id": briggs["id"], "calder_id": calder["id"], "files": files})
    return world


def test_the_selector_walks_its_four_ranking_keys_and_rejects_an_empty_pool(api):
    """Caseload decides, then certification, then badge order — and a pool of none is refused.

    PRD: The eligible pool is then sorted on four keys applied in this exact order: `open_case_load` ascending, then `certification_level` descending, then `badge_number` ascending in lexicographic byte order, then `created_at` ascending.
    PRD: If the eligible pool is empty — for instance because every officer flagged `is_investigator` already sits at their `max_case_load` — the request is refused with `ERR_NO_ELIGIBLE_INVESTIGATOR`, the investigation stays exactly where it was, and no caseload counter moves.
    Design: Corner/calculations/the_selector_walks_its_four_ranking_keys_and_rejects_an_empty_pool
    """
    world = four_files_and_a_bench_of_three_investigators(api)
    files = world["files"]
    assert [row["status"] for row in files.values()] == ["UNASSIGNED"] * 4
    assert [row["required_certification_level"] for row in files.values()] == [2, 2, 2, 2]

    first = fixtures.assign_investigation(api, world, files["a"]["i_id"], files["a"]["version"])
    second = fixtures.assign_investigation(api, world, files["b"]["i_id"], files["b"]["version"])
    third = fixtures.assign_investigation(api, world, files["c"]["i_id"], files["c"]["version"])

    assert first["assigned_investigator_officer_id"] == world["inv_a_id"]
    assert second["assigned_investigator_officer_id"] == world["briggs_id"]
    assert third["assigned_investigator_officer_id"] == world["calder_id"]
    for picked, opened in ((first, files["a"]), (second, files["b"]), (third, files["c"])):
        assert picked["status"] == "ASSIGNED"
        assert picked["assignment_count"] == 1
        assert picked["version"] == opened["version"] + 1

    refused = api.assign_investigation(
        files["d"]["i_id"],
        factories.assignment_payload(files["d"]["version"]),
        world["cmdr_headers"],
    )

    validate_error(refused, "ERR_NO_ELIGIBLE_INVESTIGATOR", 422)
    stalled = fixtures.read_investigation(api, files["d"]["i_id"], world["cmdr_headers"])
    assert stalled["status"] == "UNASSIGNED"
    assert stalled["assigned_investigator_officer_id"] is None
    assert stalled["assignment_count"] == 0
    assert stalled["version"] == files["d"]["version"]
    for officer_id in (world["inv_a_id"], world["briggs_id"], world["calder_id"]):
        assert_officer_ledgers(
            fixtures.read_officer(api, officer_id, world["cmdr_headers"]), open_case_load=1
        )
    assert_officer_ledgers(
        fixtures.read_officer(api, world["cmdr_id"], world["cmdr_headers"]), open_case_load=0
    )


def test_the_investigation_window_constants_are_selected_by_classification(api, world):
    """One received_at and three classifications give three windows: 180, 121 and 90 days.

    PRD: `statutory_days` — the investigation window the state grants — is 180 days for `CLASS_I`, 121 days for `CLASS_II` and 90 days for `CLASS_III`.
    PRD: `required_certification_level` — the internal-affairs certification an assignee must hold — is 3 for `CLASS_I`, 2 for `CLASS_II` and 1 for `CLASS_III`.
    PRD: From those, `due_at` is the complaint's `received_at` advanced by `statutory_days` plus `tolled_days` whole days; at opening `tolled_days` is 0, so a Class I complaint received at the start of September 2026 is due at the end of February 2027.
    Design: Corner/calculations/the_investigation_window_constants_are_selected_by_classification
    """
    class_one = fixtures.file_public_complaint(
        api,
        world,
        narrative="Force used during an arrest, injury alleged.",
        reported_allegation_types=["EXCESSIVE_FORCE"],
        alleged_injury=True,
    )
    class_two = fixtures.file_supervisor_complaint(
        api, world, narrative="Reports not filed for four shifts."
    )
    class_three = fixtures.file_public_complaint(
        api, world, narrative="Officer was rude during a traffic stop."
    )

    assert class_one["classification"] == "CLASS_I"
    assert class_one["assigned_unit_id"] == world["ia_unit_id"]
    assert class_two["classification"] == "CLASS_II"
    assert class_two["assigned_unit_id"] == world["patrol_unit_id"]
    assert class_three["classification"] == "CLASS_III"
    assert class_three["screening_required"] is False
    assert class_three["assigned_unit_id"] == world["patrol_unit_id"]
    for complaint in (class_one, class_two, class_three):
        assert_instant(complaint["received_at"], BASE_CLOCK)

    windows = {}
    for key, complaint, allegation_type, offense_class in (
        ("one", class_one, "EXCESSIVE_FORCE", "A"),
        ("two", class_two, "NEGLECT_OF_DUTY", "B"),
        ("three", class_three, "DISCOURTESY", "D"),
    ):
        fixtures.attach_allegation(
            api,
            world,
            complaint["id"],
            allegation_type=allegation_type,
            offense_class=offense_class,
        )
        windows[key] = fixtures.open_investigation(api, world, complaint["id"])

    assert_investigation_window(windows["one"], 180, 3, "2027-01-28T00:00:00Z")
    assert_investigation_window(windows["two"], 121, 2, "2026-11-30T00:00:00Z")
    assert_investigation_window(windows["three"], 90, 1, "2026-10-30T00:00:00Z")
    for investigation in windows.values():
        assert investigation["status"] == "UNASSIGNED"
        assert investigation["tolled_days"] == 0
        assert investigation["overdue"] is False


def test_the_watch_band_admits_a_score_of_exactly_thirty_and_refuses_twenty_six(api, world):
    """Two level-three uses of force score exactly 30.00; a level two instead scores 26.25.

    PRD: The second is the multiplier of its `severity_code`: 1.0 for `LEVEL_1`, 1.5 for `LEVEL_2`, 2.0 for `LEVEL_3`, and 1.0 for `NA`, so an unclassified event is scored as though it were level one.
    PRD: `CRITICAL` at 75 or above, otherwise `ALERT` at 50 or above, otherwise `WATCH` at 30 or above, otherwise `NONE`.
    PRD: No alert row is ever created at `NONE`.
    Design: Corner/calculations/the_watch_band_admits_a_score_of_exactly_thirty_and_refuses_twenty_six
    """
    nagy = fixtures.create_officer(
        api, world["patrol_unit_id"], badge_number="PN-601", full_name="Officer Nagy"
    )
    ortiz = fixtures.create_officer(
        api, world["patrol_unit_id"], badge_number="PN-602", full_name="Officer Ortiz"
    )
    for officer_id, severity in ((nagy["id"], "LEVEL_3"), (ortiz["id"], "LEVEL_3")):
        fixtures.record_activity_event(
            api, officer_id, "USE_OF_FORCE", "2026-07-01T12:00:00Z", severity_code=severity
        )
    fixtures.record_activity_event(
        api, nagy["id"], "USE_OF_FORCE", "2026-07-20T12:00:00Z", severity_code="LEVEL_3"
    )
    fixtures.record_activity_event(
        api, ortiz["id"], "USE_OF_FORCE", "2026-07-20T12:00:00Z", severity_code="LEVEL_2"
    )

    at_the_band = fixtures.read_eis_profile(api, nagy["id"], world["cmdr_headers"])
    below_the_band = fixtures.read_eis_profile(api, ortiz["id"], world["cmdr_headers"])

    assert at_the_band["variant"] == "ROLLING_12M"
    assert_eis_profile(
        at_the_band,
        event_count=2,
        weighted_total=12.0,
        composite_score=30.00,
        alert_level="WATCH",
        breached_indicators=[],
        window_start="2025-08-01T00:00:00Z",
        window_end=BASE_CLOCK,
    )
    assert_eis_profile(
        below_the_band,
        event_count=2,
        weighted_total=10.5,
        composite_score=26.25,
        alert_level="NONE",
        breached_indicators=[],
        window_start="2025-08-01T00:00:00Z",
        window_end=BASE_CLOCK,
    )

    scored = fixtures.read_officer(api, nagy["id"], world["cmdr_headers"])
    assert_officer_risk(scored, eis_score=30.00, eis_alert_level="WATCH")
    assert_officer_ledgers(scored, open_alert_count=1)
    unscored = fixtures.read_officer(api, ortiz["id"], world["cmdr_headers"])
    assert_officer_risk(unscored, eis_score=26.25, eis_alert_level="NONE")
    assert_officer_ledgers(unscored, open_alert_count=0)

    raised = fixtures.alert_for_officer(api, world, nagy["id"])
    assert raised["trigger_source"] == "EVENT_INGEST"
    assert raised["score_variant"] == "ROLLING_12M"
    assert_two_dp(raised["composite_score"], 30.00, label="alert.composite_score")
    assert raised["alert_level"] == "WATCH"
    assert raised["status"] == "OPEN"
    assert raised["run_sequence"] is None
    assert raised["plan_count"] == 0
    assert_instant(raised["review_due_at"], "2026-08-31T00:00:00Z")

    quiet, meta = fixtures.rows(
        api.list_eis_alerts(world["cmdr_headers"], {"officer_id": ortiz["id"]})
    )
    assert quiet == []
    assert meta["total_count"] == 0


def test_events_ingested_out_of_order_score_identically_and_list_chronologically(api, world):
    """Four uses of force written newest first still read oldest first and total 24.0.

    PRD: An officer's events are listed in `occurred_at` ascending order with an optional `event_type` filter.
    PRD: The weighted total is the exact decimal sum of every contribution, accumulated in `occurred_at` ascending order with `created_at` ascending as the tie-break and with no intermediate rounding anywhere in the sum.
    PRD: On acceptance the system derives `base_weight` from the event type's base weight in the scoring table below, and derives `weekday_index` from `occurred_at`: an integer from 0 to 6 where 0 is Monday, computed in UTC.
    Design: Corner/calculations/events_ingested_out_of_order_score_identically_and_list_chronologically
    """
    pike = fixtures.create_officer(
        api, world["patrol_unit_id"], badge_number="PN-701", full_name="Officer Pike"
    )
    written = {}
    for reference, occurred_at in (
        ("REF-D", "2026-07-20T12:00:00Z"),
        ("REF-A", "2026-07-01T12:00:00Z"),
        ("REF-C", "2026-07-10T12:00:00Z"),
        ("REF-B", "2026-07-10T12:00:00Z"),
    ):
        written[reference] = fixtures.record_activity_event(
            api,
            pike["id"],
            "USE_OF_FORCE",
            occurred_at,
            severity_code="LEVEL_3",
            source_reference=reference,
        )

    listed, meta = fixtures.rows(api.list_activity_events(pike["id"], world["cmdr_headers"]))

    assert meta["total_count"] == 4
    assert [row["source_reference"] for row in listed] == ["REF-A", "REF-C", "REF-B", "REF-D"]
    assert [row["id"] for row in listed] == [
        written["REF-A"]["id"],
        written["REF-C"]["id"],
        written["REF-B"]["id"],
        written["REF-D"]["id"],
    ]
    assert [row["weekday_index"] for row in listed] == [2, 4, 4, 0]
    assert [row["severity_code"] for row in listed] == ["LEVEL_3"] * 4
    assert [row["system_generated"] for row in listed] == [False] * 4
    assert_instant(listed[0]["occurred_at"], "2026-07-01T12:00:00Z")
    assert_instant(listed[3]["occurred_at"], "2026-07-20T12:00:00Z")

    profile = fixtures.read_eis_profile(api, pike["id"], world["cmdr_headers"])

    assert_eis_profile(
        profile,
        event_count=4,
        weighted_total=24.0,
        composite_score=70.00,
        alert_level="ALERT",
        breached_indicators=["FORCE_COUNT"],
    )
    assert_officer_risk(
        fixtures.read_officer(api, pike["id"], world["cmdr_headers"]),
        eis_score=70.00,
        eis_alert_level="ALERT",
    )

    alerts, alert_meta = fixtures.rows(
        api.list_eis_alerts(world["cmdr_headers"], {"officer_id": pike["id"]})
    )
    assert alert_meta["total_count"] == 1
    assert alerts[0]["trigger_source"] == "EVENT_INGEST"
    assert_two_dp(alerts[0]["composite_score"], 30.00, label="alert.composite_score")
    assert alerts[0]["alert_level"] == "WATCH"
    assert alerts[0]["status"] == "OPEN"


def test_the_ledger_takes_the_final_variant_days_not_the_presumptive_days(api):
    """Ten presumptive days sit untouched beside fifteen final days, and fifteen reach the officer.

    PRD: The `PRESUMPTIVE` variant is computed inside the sustained disposition and written to `presumptive_prior_tier` and `presumptive_days`.
    PRD: The `FINAL` variant is computed inside imposition and written to `final_prior_tier` and `final_days`.
    PRD: Class `B` offers 10, 20 and 45.
    PRD: `final_prior_tier` and `final_days` are computed under the final variant, `effective_days` is set to `final_days`, `imposed_at` is stamped from the logical clock, `appeal_deadline_at` is set to `imposed_at` plus 15 whole days, `final_days` is added to the officer's `imposed_suspension_days_total`, and — when `final_days` is at least 1 — an `ACTIVE` officer moves `ACTIVE → SUSPENDED` with `suspension_end_date` set to `effective_date` plus `final_days` days.
    Design: Corner/calculations/the_ledger_takes_the_final_variant_days_not_the_presumptive_days
    """
    world = fixtures.world_at_findings(api, offense_class="B")

    disposed = fixtures.dispose_allegation(api, world, world["a1_id"], "SUSTAINED")

    assert disposed["disposition"] == "SUSTAINED"
    assert_two_dp(disposed["support_pct"], 60.00, label="support_pct")
    assert disposed["preponderance_met"] is True
    assert_instant(disposed["disposed_at"], "2026-08-05T09:00:00Z")
    assert disposed["prior_sustained_count_at_disposition"] == 0

    proposed = fixtures.discipline_for_allegation(api, world, world["a1_id"])

    assert proposed["status"] == "PROPOSED"
    assert proposed["offense_class"] == "B"
    assert proposed["officer_id"] == world["subj_id"]
    assert_discipline_days(
        proposed,
        presumptive_prior_tier=0,
        presumptive_days=10,
        final_prior_tier=None,
        final_days=None,
        effective_days=0,
    )
    assert proposed["imposed_at"] is None
    assert proposed["appeal_deadline_at"] is None
    before = fixtures.read_officer(api, world["subj_id"], world["cmdr_headers"])
    assert_officer_ledgers(before, imposed_suspension_days_total=0)
    assert before["employment_status"] == "ACTIVE"

    imposed = get_success_data(
        api.impose_discipline(
            proposed["id"],
            factories.imposition_payload(
                effective_date="2026-08-10T00:00:00Z", aggravator_count=1
            ),
            world["cmdr_headers"],
        )
    )

    assert imposed["status"] == "IMPOSED"
    assert_discipline_days(
        imposed,
        presumptive_prior_tier=0,
        presumptive_days=10,
        final_prior_tier=0,
        final_days=15,
        effective_days=15,
    )
    assert_instant(imposed["imposed_at"], "2026-08-05T09:00:00Z")
    assert_instant(imposed["appeal_deadline_at"], "2026-08-20T09:00:00Z")

    charged = fixtures.read_officer(api, world["subj_id"], world["cmdr_headers"])
    assert_officer_ledgers(charged, imposed_suspension_days_total=15)
    assert charged["employment_status"] == "SUSPENDED"
    assert_instant(charged["suspension_end_date"], "2026-08-25T00:00:00Z")
