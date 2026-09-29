"""Optimistic concurrency on both pinned parents, threshold edges and immediate visibility."""

from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers import (
    RECORDS_CUSTODIAN_HEADERS,
    assert_eis_profile,
    assert_instant,
    assert_officer_ledgers,
    assert_officer_risk,
    assert_two_dp,
)
from test_helpers import factories, fixtures

BASE_CLOCK = "2026-08-01T00:00:00Z"


def test_assignment_create_rejects_a_stale_investigation_version(api):
    """A replayed version looks like a valid reassignment and is refused without moving the ledger.

    PRD: Assigning an investigator requires `expected_investigation_version` as a non-optional field of the request body, carrying the client's last observed `version` of the target `Investigation`. If that value does not equal the investigation's current `version`, the write is rejected with `ERR_STALE_INVESTIGATION_VERSION` (HTTP 412) and nothing is mutated — no assignee is written, no caseload counter moves, and the investigation's own `version` does not advance.
    PRD: Both accepted writes advance the parent's `version` by exactly 1, so a client that wishes to write twice in a row must re-read the parent — or read the returned resource — between the two writes.
    PRD: An accepted assignment writes `assigned_investigator_officer_id`, raises `assignment_count` by 1 — the counter includes reassignments, so it is a count of accepted assignment writes rather than of distinct people — credits the new assignee's `open_case_load` by 1, and advances the investigation's `version` by 1.
    PRD: On the reassignment self-loop the outgoing assignee's `open_case_load` is debited by 1 in the same request, so the department-wide caseload total is conserved.
    Design: Corner/cross_cutting_layers/assignment_create_rejects_a_stale_investigation_version
    """
    world = fixtures.world_with_investigation(api)
    briggs = fixtures.create_investigator(
        api,
        world["ia_unit_id"],
        badge_number="IA-102",
        full_name="Investigator Briggs",
        certification_level=3,
        max_case_load=8,
    )
    assert world["investigation"]["status"] == "UNASSIGNED"

    first = get_success_data(
        api.assign_investigation(
            world["i1_id"],
            factories.assignment_payload(
                world["i1_v0"],
                world["inv_a_id"],
                assignment_note="First assignment, at the observed version.",
            ),
            world["cmdr_headers"],
        )
    )

    assert first["status"] == "ASSIGNED"
    assert first["assigned_investigator_officer_id"] == world["inv_a_id"]
    assert first["assignment_count"] == 1
    i1_v1 = first["version"]
    assert i1_v1 == world["i1_v0"] + 1
    assert_officer_ledgers(
        fixtures.read_officer(api, world["inv_a_id"], world["cmdr_headers"]), open_case_load=1
    )

    stale = api.assign_investigation(
        world["i1_id"],
        factories.assignment_payload(
            world["i1_v0"],
            briggs["id"],
            assignment_note="Replay of the version observed before the first assignment.",
        ),
        world["cmdr_headers"],
    )

    validate_error(stale, "ERR_STALE_INVESTIGATION_VERSION", 412)
    unmoved = fixtures.read_investigation(api, world["i1_id"], world["cmdr_headers"])
    assert unmoved["assigned_investigator_officer_id"] == world["inv_a_id"]
    assert unmoved["assignment_count"] == 1
    assert_officer_ledgers(
        fixtures.read_officer(api, briggs["id"], world["cmdr_headers"]), open_case_load=0
    )
    assert_officer_ledgers(
        fixtures.read_officer(api, world["inv_a_id"], world["cmdr_headers"]), open_case_load=1
    )

    # The refused write consumed no version, so the re-read matches the accepted write's own.
    i1_v2 = unmoved["version"]
    assert i1_v2 == i1_v1

    reassigned = get_success_data(
        api.assign_investigation(
            world["i1_id"],
            factories.assignment_payload(
                i1_v2,
                briggs["id"],
                assignment_note="Reassignment after re-reading the current version.",
            ),
            world["cmdr_headers"],
        )
    )

    assert reassigned["status"] == "ASSIGNED"
    assert reassigned["assigned_investigator_officer_id"] == briggs["id"]
    assert reassigned["assignment_count"] == 2
    assert reassigned["version"] == i1_v2 + 1
    assert_officer_ledgers(
        fixtures.read_officer(api, world["inv_a_id"], world["cmdr_headers"]), open_case_load=0
    )
    assert_officer_ledgers(
        fixtures.read_officer(api, briggs["id"], world["cmdr_headers"]), open_case_load=1
    )


def test_plan_create_rejects_a_stale_alert_version(api):
    """Plan creation bumps the alert itself, so the same version twice is a stale write.

    PRD: Creating an intervention plan against an alert requires `expected_alert_version` as a non-optional field of the request body, carrying the client's last observed `version` of the target `EarlyInterventionAlert`. If that value does not equal the alert's current `version`, the create is rejected with `ERR_STALE_ALERT_VERSION` (HTTP 412) and no plan row is written.
    PRD: Both accepted writes advance the parent's `version` by exactly 1, so a client that wishes to write twice in a row must re-read the parent — or read the returned resource — between the two writes.
    PRD: A `Supervisor` or an `IACommander` attaches a plan to an alert, pinning `expected_alert_version` as Section 2.6 requires and supplying the `supervisor_officer_id` who will do the monitoring, the `required_checkin_count` between 2 and 6, the `duration_days` of 30, 60 or 90, and the `interventions` to be applied, drawn from `RETRAINING`, `COUNSELING`, `PEER_REVIEW`, `REASSIGNMENT` and `EAP_REFERRAL`.
    PRD: The alert must be in `PLAN_REQUIRED` or `ESCALATED`, otherwise `ERR_ALERT_STATE_INVALID`.
    PRD: The plan is created in `DRAFT` with `completed_checkin_count`, `on_time_checkin_count` and `concern_count` all 0, the alert's `plan_count` rises by 1 and its `version` rises by 1.
    Design: Corner/cross_cutting_layers/plan_create_rejects_a_stale_alert_version
    """
    world = fixtures.world_with_promoted_alert(api)
    al_v0 = world["al_v"]
    assert world["alert"]["status"] == "PLAN_REQUIRED"
    assert world["alert"]["plan_count"] == 0

    first = validate_success(
        api.create_intervention_plan(
            world["al_id"],
            factories.intervention_plan_payload(
                al_v0,
                world["sup_id"],
                required_checkin_count=2,
                duration_days=30,
                interventions=["RETRAINING"],
            ),
            world["sup_headers"],
        ),
        201,
    )

    assert first["status"] == "DRAFT"
    assert first["required_checkin_count"] == 2
    assert first["duration_days"] == 30
    after_first = fixtures.read_alert(api, world["al_id"], world["cmdr_headers"])
    assert after_first["plan_count"] == 1
    assert after_first["version"] == al_v0 + 1

    # PLAN_REQUIRED is still a legal from-state, so only the version pin can refuse this.
    stale = api.create_intervention_plan(
        world["al_id"],
        factories.intervention_plan_payload(
            al_v0,
            world["sup_id"],
            required_checkin_count=3,
            duration_days=60,
            interventions=["RETRAINING", "COUNSELING"],
        ),
        world["sup_headers"],
    )

    validate_error(stale, "ERR_STALE_ALERT_VERSION", 412)
    unmoved = fixtures.read_alert(api, world["al_id"], world["cmdr_headers"])
    assert unmoved["status"] == "PLAN_REQUIRED"
    assert unmoved["plan_count"] == 1
    assert unmoved["version"] == al_v0 + 1
    only_one, plan_meta = fixtures.rows(
        api.list_intervention_plans(world["sup_headers"], {"alert_id": world["al_id"]})
    )
    assert plan_meta["total_count"] == 1
    assert [row["id"] for row in only_one] == [first["id"]]

    al_v1 = unmoved["version"]
    assert al_v1 == al_v0 + 1

    second = validate_success(
        api.create_intervention_plan(
            world["al_id"],
            factories.intervention_plan_payload(
                al_v1,
                world["sup_id"],
                required_checkin_count=3,
                duration_days=60,
                interventions=["RETRAINING", "COUNSELING"],
            ),
            world["sup_headers"],
        ),
        201,
    )

    assert second["status"] == "DRAFT"
    assert second["id"] != first["id"]
    assert second["required_checkin_count"] == 3
    assert second["duration_days"] == 60
    after_second = fixtures.read_alert(api, world["al_id"], world["cmdr_headers"])
    assert after_second["plan_count"] == 2
    assert after_second["version"] == al_v1 + 1
    _, both = fixtures.rows(
        api.list_intervention_plans(world["sup_headers"], {"alert_id": world["al_id"]})
    )
    assert both["total_count"] == 2


BOUNDARY_EVENT_PATTERN = (
    ("USE_OF_FORCE", "LEVEL_3", "2026-07-01T00:00:00Z", "UOF-A"),
    ("USE_OF_FORCE", "LEVEL_3", "2026-07-05T00:00:00Z", "UOF-B"),
    ("PURSUIT", "NA", "2026-07-10T00:00:00Z", "PUR-A"),
    ("SICK_LEAVE_DAY", "NA", "2026-07-15T00:00:00Z", "SL-1"),
    ("SICK_LEAVE_DAY", "NA", "2026-07-16T00:00:00Z", "SL-2"),
    ("SICK_LEAVE_DAY", "NA", "2026-07-17T00:00:00Z", "SL-3"),
    ("SICK_LEAVE_DAY", "NA", "2026-07-18T00:00:00Z", "SL-4"),
    ("SICK_LEAVE_DAY", "NA", "2026-07-19T00:00:00Z", "SL-5"),
    ("SICK_LEAVE_DAY", "NA", "2026-07-20T00:00:00Z", "SL-6"),
)


def test_eis_thresholds_fire_at_their_exact_boundaries_and_reset_when_the_window_moves(api):
    """Exactly 50.00 promotes, the third use of force adds 17.50, and a year later the score is 0.00.

    PRD: The scoring window is the 365 days ending at the logical clock, and it is **half-open on the left**: an event is in the window when its `occurred_at` is strictly after the clock less 365 whole days and at or before the clock. An event exactly 365 days old is therefore excluded and contributes nothing.
    PRD: Each in-window event contributes the product of three factors. The first is the base weight of its `event_type`: 3 for `USE_OF_FORCE`, 2 for `PURSUIT`, 1 for `SICK_LEAVE_DAY`, 1 for `COMPLAINT_INTAKE` and 4 for `COMPLAINT_SUSTAINED` — a sustained complaint weighs more than any single incident.
    PRD: The second is the multiplier of its `severity_code`: 1.0 for `LEVEL_1`, 1.5 for `LEVEL_2`, 2.0 for `LEVEL_3`, and 1.0 for `NA`, so an unclassified event is scored as though it were level one.
    PRD: The weighted total is the exact decimal sum of every contribution, accumulated in `occurred_at` ascending order with `created_at` ascending as the tie-break and with no intermediate rounding anywhere in the sum.
    PRD: Four indicators are then evaluated over the same window, each with a non-strict at-least comparison: `FORCE_COUNT` is breached when there are at least 3 `USE_OF_FORCE` events; `PURSUIT_COUNT` when there are at least 2 `PURSUIT` events; `COMPLAINT_COUNT` when the `COMPLAINT_INTAKE` and `COMPLAINT_SUSTAINED` events together number at least 3; and `SICK_LEAVE_DAYS` when there are at least 12 `SICK_LEAVE_DAY` events.
    PRD: `breached_indicators` lists the breached names in the fixed order `FORCE_COUNT`, `PURSUIT_COUNT`, `COMPLAINT_COUNT`, `SICK_LEAVE_DAYS` regardless of the order in which the events arrived, and the breached count is the length of that list.
    PRD: The `ROLLING_12M` variant is the default and the only one written to the officer record. Its score is the weighted total multiplied by the officer's assignment multiplier — 1.0 for `PATROL`, 0.8 for `INVESTIGATIVE` and 0.6 for `ADMIN`, discounting officers whose duties expose them to fewer incidents — multiplied by a scale factor of 2.5, plus a flat additive bonus of 10 for each breached indicator. The result is clamped into the range 0 to 100 and rounded half up to two decimal places.
    PRD: The band is read off the final score: `CRITICAL` at 75 or above, otherwise `ALERT` at 50 or above, otherwise `WATCH` at 30 or above, otherwise `NONE`. No alert row is ever created at `NONE`.
    PRD: Recording an event also rescores the officer under the rolling variant, and when the resulting band is above `NONE` and the officer has no alert already open, an `EarlyInterventionAlert` is created with `trigger_source` `EVENT_INGEST` and the officer's `open_alert_count` rises by 1.
    PRD: For each officer who does already have an open alert, it refreshes that alert's `composite_score`, `score_variant`, `alert_level` and `breached_indicators` to the newly computed values and stamps the alert's `run_sequence`.
    PRD: It promotes an alert `OPEN → PLAN_REQUIRED` when the recomputed band reaches `ALERT` or `CRITICAL`, setting `review_due_at` to the promotion instant plus 30 whole days — the same 30-day rule that sets `review_due_at` at creation.
    PRD: The computed profile read returns the `officer_id`, the `variant` applied, the `window_start` and `window_end` bounding the scoring window, the `event_count` of in-window events, the `weighted_total`, the `composite_score`, the `alert_level`, the `breached_indicators`, and the `peer_pool_size` and `peer_mean` belonging to the peer comparison. A read never overwrites the stored `eis_score`.
    Design: Corner/cross_cutting_layers/eis_thresholds_fire_at_their_exact_boundaries_and_reset_when_the_window_moves
    """
    world = fixtures.seed_reference_data(api)
    fixtures.ingest_event_pattern(api, world["subj_id"], BOUNDARY_EVENT_PATTERN)

    at_the_band = fixtures.read_eis_profile(api, world["subj_id"], world["cmdr_headers"])

    assert at_the_band["variant"] == "ROLLING_12M"
    assert_eis_profile(
        at_the_band,
        event_count=9,
        weighted_total=20.0,
        composite_score=50.00,
        alert_level="ALERT",
        breached_indicators=[],
        window_start="2025-08-01T00:00:00Z",
        window_end=BASE_CLOCK,
    )
    assert_officer_risk(
        fixtures.read_officer(api, world["subj_id"], world["cmdr_headers"]),
        eis_score=50.00,
        eis_alert_level="ALERT",
    )

    # The ingest opened the alert at the WATCH crossing and never refreshed it afterwards.
    opened = fixtures.alert_for_officer(api, world, world["subj_id"])
    assert opened["status"] == "OPEN"
    assert opened["trigger_source"] == "EVENT_INGEST"
    assert_two_dp(opened["composite_score"], 30.00, label="alert.composite_score")
    assert opened["alert_level"] == "WATCH"
    assert opened["run_sequence"] is None

    fixtures.run_sweep(api, world)

    promoted = fixtures.alert_for_officer(api, world, world["subj_id"])
    assert promoted["id"] == opened["id"]
    assert promoted["status"] == "PLAN_REQUIRED"
    assert_two_dp(promoted["composite_score"], 50.00, label="alert.composite_score")
    assert promoted["alert_level"] == "ALERT"
    assert promoted["breached_indicators"] == []
    assert promoted["run_sequence"] == 1
    assert_instant(promoted["review_due_at"], "2026-08-31T00:00:00Z")

    fixtures.record_activity_event(
        api,
        world["subj_id"],
        "USE_OF_FORCE",
        "2026-07-25T00:00:00Z",
        severity_code="LEVEL_1",
        source_reference="UOF-C",
    )

    # Three points of weight are worth 7.50 scaled, and FORCE_COUNT adds a flat 10.00 on top.
    breached = fixtures.read_eis_profile(api, world["subj_id"], world["cmdr_headers"])

    assert_eis_profile(
        breached,
        event_count=10,
        weighted_total=23.0,
        composite_score=67.50,
        alert_level="ALERT",
        breached_indicators=["FORCE_COUNT"],
    )
    assert_officer_risk(
        fixtures.read_officer(api, world["subj_id"], world["cmdr_headers"]),
        eis_score=67.50,
        eis_alert_level="ALERT",
    )
    alerts, alert_meta = fixtures.rows(
        api.list_eis_alerts(world["cmdr_headers"], {"officer_id": world["subj_id"]})
    )
    assert alert_meta["total_count"] == 1
    assert_two_dp(alerts[0]["composite_score"], 50.00, label="alert.composite_score")
    assert alerts[0]["status"] == "PLAN_REQUIRED"

    fixtures.set_clock(api, "2027-08-01T00:00:00Z")

    aged_out = fixtures.read_eis_profile(api, world["subj_id"], world["cmdr_headers"])

    assert_eis_profile(
        aged_out,
        event_count=0,
        weighted_total=0.0,
        composite_score=0.00,
        alert_level="NONE",
        breached_indicators=[],
        window_start="2026-08-01T00:00:00Z",
        window_end="2027-08-01T00:00:00Z",
    )
    survivor, survivor_meta = fixtures.rows(
        api.list_eis_alerts(world["cmdr_headers"], {"officer_id": world["subj_id"]})
    )
    assert survivor_meta["total_count"] == 1
    assert survivor[0]["status"] == "PLAN_REQUIRED"
    assert_two_dp(survivor[0]["composite_score"], 50.00, label="alert.composite_score")


def test_every_derived_value_is_already_correct_on_the_first_read_after_the_write(api):
    """One disposition fans out to six records, and every first read already carries the result.

    PRD: Cascades are always executed inside the originating request — the consistency model is immediate, and there is no deferred or eventual settlement anywhere. When a cascade mutates a record, that record's `updated_at` is refreshed and its `version` advances, exactly as if it had been written directly.
    PRD: Every accepted disposition stamps `disposed_at` from the logical clock and records `prior_sustained_count_at_disposition`, the number of prior sustained allegations against the same subject officer inside the presumptive look-back window.
    PRD: **`PENDING → SUSTAINED`** requires `preponderance_met` to be true; a sustained finding without a preponderance is refused with `ERR_PREPONDERANCE_NOT_MET`.
    PRD: Acceptance raises the complaint's `sustained_allegation_count` by 1 and fires five cascades. First, a `Discipline` row is created in `PROPOSED`, with `offense_class` copied verbatim from the allegation and with `presumptive_prior_tier` and `presumptive_days` computed under the presumptive variant of the matrix. Second, because a sustained finding was recorded, a `system_generated` activity event of type `COMPLAINT_SUSTAINED` is appended for the subject officer, with `occurred_at` equal to the allegation's `disposed_at`. Third, because that event has entered the rolling window, the officer's `eis_score` and `eis_alert_level` are recomputed. Fourth, when that recomputation puts `eis_alert_level` above `NONE`, an `EarlyInterventionAlert` is created with `trigger_source` `DISPOSITION_CASCADE` and the officer's `open_alert_count` rises by 1. Fifth, when the allegation's `allegation_type` is `UNTRUTHFULNESS`, a `CredibilityDisclosure` is created in `ACTIVE` with `permanent_retention` true and the officer's `credibility_disclosure_active` is set to true.
    PRD: Class `A` — the most severe row — offers 30, 60 and 120 days for tiers 0, 1 and 2.
    PRD: `system_generated` is false for supervisor-recorded events and true only for the `COMPLAINT_SUSTAINED` events that the sustained-disposition cascade appends.
    PRD: Each in-window event contributes the product of three factors. The first is the base weight of its `event_type`: 3 for `USE_OF_FORCE`, 2 for `PURSUIT`, 1 for `SICK_LEAVE_DAY`, 1 for `COMPLAINT_INTAKE` and 4 for `COMPLAINT_SUSTAINED` — a sustained complaint weighs more than any single incident.
    PRD: The `ROLLING_12M` variant is the default and the only one written to the officer record. Its score is the weighted total multiplied by the officer's assignment multiplier — 1.0 for `PATROL`, 0.8 for `INVESTIGATIVE` and 0.6 for `ADMIN`, discounting officers whose duties expose them to fewer incidents — multiplied by a scale factor of 2.5, plus a flat additive bonus of 10 for each breached indicator. The result is clamped into the range 0 to 100 and rounded half up to two decimal places.
    PRD: An accepted submission stamps `findings_submitted_at`, writes `evidence_weight_for`, `evidence_weight_against` and `policy_compliant` onto every allegation and recomputes each one's `support_pct` and `preponderance_met`, moves the investigation `IN_PROGRESS → PENDING_REVIEW`, and moves the owning complaint `UNDER_INVESTIGATION → ADJUDICATION`.
    Design: Corner/consistency_model/every_derived_value_is_already_correct_on_the_first_read_after_the_write
    """
    world = fixtures.world_at_findings(
        api,
        evidence_weight_for=80,
        evidence_weight_against=20,
        allegation_type="UNTRUTHFULNESS",
        offense_class="A",
        reported_allegation_types=["UNTRUTHFULNESS"],
        complaint_overrides={
            "narrative": "Officer gave a false account in a written report.",
            "incident_datetime": "2026-07-20T22:00:00Z",
        },
    )
    assert world["investigation"]["status"] == "PENDING_REVIEW"
    # PRD: "the system appends a `system_generated` activity event of type
    # `COMPLAINT_INTAKE` for the named subject officer, timestamped with
    # `occurred_at` equal to the owning complaint's `received_at`". Attaching the
    # allegation therefore already left exactly one event behind.
    intake_events, intake_meta = fixtures.rows(
        api.list_activity_events(world["subj_id"], world["cmdr_headers"])
    )
    assert intake_meta["total_count"] == 1
    assert intake_events[0]["event_type"] == "COMPLAINT_INTAKE"
    assert_two_dp(intake_events[0]["base_weight"], 1.0, label="base_weight")
    assert_instant(intake_events[0]["occurred_at"], BASE_CLOCK)

    # The written entity's own derived fields come back on the write itself.
    disposed = get_success_data(
        api.dispose_allegation(
            world["a1_id"],
            factories.disposition_payload("SUSTAINED", rationale="Sustained untruthfulness."),
            world["cmdr_headers"],
        )
    )

    assert disposed["disposition"] == "SUSTAINED"
    assert_instant(disposed["disposed_at"], "2026-08-05T09:00:00Z")
    assert disposed["prior_sustained_count_at_disposition"] == 0
    assert_two_dp(disposed["support_pct"], 80.00, label="support_pct")
    assert disposed["preponderance_met"] is True

    complaint = fixtures.read_complaint(api, world["c_id"], world["cmdr_headers"])

    assert complaint["sustained_allegation_count"] == 1
    assert complaint["status"] == "ADJUDICATION"

    discipline = fixtures.discipline_for_allegation(api, world, world["a1_id"])

    assert discipline["status"] == "PROPOSED"
    assert discipline["offense_class"] == "A"
    assert discipline["presumptive_prior_tier"] == 0
    assert discipline["presumptive_days"] == 30

    disclosure = fixtures.disclosure_for_allegation(api, world, world["a1_id"])

    assert disclosure["status"] == "ACTIVE"
    assert disclosure["basis"] == "UNTRUTHFULNESS_SUSTAINED"
    assert disclosure["permanent_retention"] is True
    _, disclosure_meta = fixtures.rows(
        api.list_credibility_disclosures(
            RECORDS_CUSTODIAN_HEADERS, {"officer_id": world["subj_id"]}
        )
    )
    assert disclosure_meta["total_count"] == 1

    officer = fixtures.read_officer(api, world["subj_id"], world["cmdr_headers"])

    # The rolling window now holds the COMPLAINT_INTAKE event (base 1, aged four
    # days so undecayed) and the COMPLAINT_SUSTAINED event (base 4, aged zero):
    # a weighted total of 5.0, scaled by the PATROL multiplier 1.0 and the 2.5
    # scale factor, with no indicator breached, gives 12.50 -- still below WATCH.
    assert_officer_risk(officer, eis_score=12.50, eis_alert_level="NONE")
    assert_officer_ledgers(officer, credibility_disclosure_active=True, open_alert_count=0)

    cascade_events, event_meta = fixtures.rows(
        api.list_activity_events(
            world["subj_id"], world["cmdr_headers"], {"event_type": "COMPLAINT_SUSTAINED"}
        )
    )

    assert event_meta["total_count"] == 1
    assert_two_dp(cascade_events[0]["base_weight"], 4.0, label="base_weight")
    assert cascade_events[0]["system_generated"] is True
    assert_instant(cascade_events[0]["occurred_at"], "2026-08-05T09:00:00Z")

    profile = fixtures.read_eis_profile(api, world["subj_id"], world["cmdr_headers"])

    assert_eis_profile(
        profile,
        event_count=2,
        weighted_total=5.0,
        composite_score=12.50,
        alert_level="NONE",
        breached_indicators=[],
    )
