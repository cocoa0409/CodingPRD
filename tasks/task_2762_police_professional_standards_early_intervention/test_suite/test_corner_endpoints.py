"""Reference CRUD, the employment action, the sweep, a join listing and a pure report read."""

from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers import (
    RECORDS_CUSTODIAN_HEADERS,
    SYSTEM_ADMIN_HEADERS,
    assert_eis_run_counters,
    assert_envelope_meta,
    assert_instant,
    assert_list_page,
    assert_officer_ledgers,
    assert_officer_risk,
    assert_one_dp,
    assert_report_group,
    assert_two_dp,
    make_ia_commander_headers,
    make_supervisor_headers,
)
from test_helpers import factories, fixtures

BASE_CLOCK = "2026-08-01T00:00:00Z"
STANDING_COMMANDER_ID = "00000000-0000-0000-0000-00000000000a"
READER_HEADERS = make_ia_commander_headers(STANDING_COMMANDER_ID)


def test_reference_data_round_trips_through_create_read_and_filtered_list(api):
    """Two units and two rooms come back from their reads with the declared filters honoured.

    PRD: Registering a command unit supplies its display `name`, its `unit_role`, its bureau `command_code` — which is unique across units — its `peer_group_code`, and its `sworn_headcount`, which must be at least 1.
    PRD: A sixth field, `intake_enabled`, defaults to true when omitted and is the switch that takes a unit out of the routing pool: a unit whose `intake_enabled` is false is never an eligible routing target, even for a complaint that names it.
    PRD: Units are immutable once registered, and they are listed with optional `unit_role` and `peer_group_code` filters.
    PRD: Hearing rooms are also immutable, and are listed with an optional `facility_code` filter.
    Design: Corner/endpoints/reference_data_round_trips_through_create_read_and_filtered_list
    """
    fixtures.set_clock(api, BASE_CLOCK)

    ia_response = api.create_unit(factories.internal_affairs_unit_payload(), SYSTEM_ADMIN_HEADERS)
    patrol_response = api.create_unit(factories.patrol_unit_payload(), SYSTEM_ADMIN_HEADERS)

    internal_affairs = validate_success(ia_response, 201)
    patrol = validate_success(patrol_response, 201)
    # PRD: for a `Unit`, a `HearingRoom` and an `OfficerActivityEvent` both
    # `updated_at` and `version` are absent from the resource entirely.
    for unit_row in (internal_affairs, patrol):
        assert "version" not in unit_row
        assert "updated_at" not in unit_row
        assert unit_row["created_at"] is not None
    assert patrol["intake_enabled"] is True

    single = validate_success(api.get_unit(patrol["id"], READER_HEADERS))

    assert single["name"] == "Patrol North"
    assert single["unit_role"] == "PATROL_DIVISION"
    assert single["command_code"] == "PN"
    assert single["peer_group_code"] == "PG_NORTH"
    assert single["sworn_headcount"] == 60

    by_role_response = api.list_units(READER_HEADERS, {"unit_role": "PATROL_DIVISION", "limit": 10, "offset": 0})
    by_role, role_meta = fixtures.rows(by_role_response)
    by_group, group_meta = fixtures.rows(
        api.list_units(READER_HEADERS, {"peer_group_code": "PG_IA", "limit": 10, "offset": 0})
    )

    assert [row["id"] for row in by_role] == [patrol["id"]]
    assert_list_page(role_meta, 10, 0, 1, False)
    assert_envelope_meta(by_role_response.json())
    assert [row["id"] for row in by_group] == [internal_affairs["id"]]
    assert_list_page(group_meta, 10, 0, 1, False)

    hq_response = api.create_hearing_room(
        factories.hearing_room_payload(
            facility_code="HQ",
            room_name="Interview 1",
            concurrent_capacity=2,
            recording_enabled=True,
        ),
        SYSTEM_ADMIN_HEADERS,
    )
    west_response = api.create_hearing_room(
        factories.hearing_room_payload(
            facility_code="WEST", room_name="Interview 2", concurrent_capacity=1
        ),
        SYSTEM_ADMIN_HEADERS,
    )

    headquarters = validate_success(hq_response, 201)
    west = validate_success(west_response, 201)
    # A `HearingRoom` is append-only history in the same way a `Unit` is.
    for room_row in (headquarters, west):
        assert "version" not in room_row
        assert "updated_at" not in room_row
        assert room_row["created_at"] is not None

    west_read = validate_success(api.get_hearing_room(west["id"], READER_HEADERS))

    assert west_read["room_name"] == "Interview 2"
    assert west_read["concurrent_capacity"] == 1
    assert west_read["facility_code"] == "WEST"

    hq_rooms, room_meta = fixtures.rows(
        api.list_hearing_rooms(READER_HEADERS, {"facility_code": "HQ", "limit": 10, "offset": 0})
    )

    assert [row["id"] for row in hq_rooms] == [headquarters["id"]]
    assert hq_rooms[0]["recording_enabled"] is True
    assert_list_page(room_meta, 10, 0, 1, False)


def test_the_employment_action_moves_one_dimension_and_locks_at_separated(api):
    """Relief of duty touches nothing but the employment field, and separation is a one-way door.

    PRD: An officer who is `ACTIVE` or `SUSPENDED` may be moved to `RELIEVED_OF_DUTY`, and that officer remains fully interviewable and remains an eligible subject of discipline — relief from duty is a precaution, not an exit.
    PRD: Any officer who is not already `SEPARATED` may be moved to `SEPARATED`, at which point the officer stops being an eligible investigator candidate and stops being interviewable, while every open investigation already assigned to that officer is left exactly as it was and the caseload ledger is not adjusted.
    PRD: `SEPARATED` is terminal: every further employment-status write on that officer is refused with `ERR_OFFICER_SEPARATED`, including a write that merely repeats `SEPARATED`.
    Design: Corner/endpoints/the_employment_action_moves_one_dimension_and_locks_at_separated
    """
    fixtures.set_clock(api, BASE_CLOCK)
    unit = fixtures.create_unit(api, intake_enabled=True)
    vance = fixtures.create_officer(api, unit["id"])

    relieved = get_success_data(
        api.set_employment_status(
            vance["id"],
            factories.employment_status_payload(
                "RELIEVED_OF_DUTY", reason="Pending review of a use-of-force report."
            ),
            SYSTEM_ADMIN_HEADERS,
        )
    )

    assert relieved["employment_status"] == "RELIEVED_OF_DUTY"

    unchanged = fixtures.read_officer(api, vance["id"], SYSTEM_ADMIN_HEADERS)

    assert unchanged["badge_number"] == vance["badge_number"]
    assert unchanged["unit_id"] == unit["id"]
    assert unchanged["annual_salary_cents"] == vance["annual_salary_cents"]
    assert unchanged["certification_level"] == vance["certification_level"]
    assert_instant(unchanged["hire_date"], vance["hire_date"])
    assert_officer_risk(unchanged, eis_score=0.00, eis_alert_level="NONE")
    assert_officer_ledgers(unchanged, open_case_load=0, imposed_suspension_days_total=0)
    assert unchanged["suspension_end_date"] is None

    separated = get_success_data(
        api.set_employment_status(
            vance["id"],
            factories.employment_status_payload("SEPARATED", reason="Resignation accepted."),
            SYSTEM_ADMIN_HEADERS,
        )
    )

    assert separated["employment_status"] == "SEPARATED"

    refused = api.set_employment_status(
        vance["id"],
        factories.employment_status_payload(
            "ACTIVE", reason="Attempted reinstatement outside the appeal process."
        ),
        SYSTEM_ADMIN_HEADERS,
    )

    validate_error(refused, "ERR_OFFICER_SEPARATED", 409)
    still_there = fixtures.read_officer(api, vance["id"], SYSTEM_ADMIN_HEADERS)
    assert still_there["employment_status"] == "SEPARATED"
    assert still_there["id"] == vance["id"]


def a_roster_of_four_with_two_stale_alerts(api):
    """Doyle carries nothing, Pratt three uses of force, Quinn two and Reeve none."""
    fixtures.set_clock(api, BASE_CLOCK)
    unit = fixtures.create_unit(api, intake_enabled=True)
    doyle = fixtures.create_supervisor(api, unit["id"])
    people = {}
    for key, badge, name, demographic in (
        ("pratt", "PN-801", "Officer Pratt", "DG_A"),
        ("quinn", "PN-802", "Officer Quinn", "DG_B"),
        ("reeve", "PN-803", "Officer Reeve", "DG_C"),
    ):
        people[key] = fixtures.create_officer(
            api,
            unit["id"],
            badge_number=badge,
            full_name=name,
            annual_salary_cents=9000000,
            demographic_code=demographic,
        )
    supervisor_headers = make_supervisor_headers(doyle["id"])
    for occurred_at, reference in (
        ("2026-07-01T12:00:00Z", "P-1"),
        ("2026-07-10T12:00:00Z", "P-2"),
        ("2026-07-20T12:00:00Z", "P-3"),
    ):
        fixtures.record_activity_event(
            api,
            people["pratt"]["id"],
            "USE_OF_FORCE",
            occurred_at,
            severity_code="LEVEL_3",
            source_reference=reference,
            headers=supervisor_headers,
        )
    for occurred_at, reference in (
        ("2026-07-01T12:00:00Z", "Q-1"),
        ("2026-07-20T12:00:00Z", "Q-2"),
    ):
        fixtures.record_activity_event(
            api,
            people["quinn"]["id"],
            "USE_OF_FORCE",
            occurred_at,
            severity_code="LEVEL_3",
            source_reference=reference,
            headers=supervisor_headers,
        )
    return {
        "unit_id": unit["id"],
        "sup_id": doyle["id"],
        "pratt_id": people["pratt"]["id"],
        "quinn_id": people["quinn"]["id"],
        "reeve_id": people["reeve"]["id"],
    }


def test_one_eis_run_evaluates_every_officer_and_reports_its_counters(api):
    """Four officers, one promotion, one plain refresh and two quiet evaluations in a single run.

    PRD: The run reports six counters: the `run_sequence` of this run, the `evaluated_officer_count`, the number of `alerts_created`, the number of `alerts_promoted`, the number of `checkins_missed`, and the number of `disclosures_expired`.
    PRD: For each officer who does already have an open alert, it refreshes that alert's `composite_score`, `score_variant`, `alert_level` and `breached_indicators` to the newly computed values and stamps the alert's `run_sequence`.
    PRD: It promotes an alert `OPEN → PLAN_REQUIRED` when the recomputed band reaches `ALERT` or `CRITICAL`, setting `review_due_at` to the promotion instant plus 30 whole days — the same 30-day rule that sets `review_due_at` at creation.
    Design: Corner/endpoints/one_eis_run_evaluates_every_officer_and_reports_its_counters
    """
    roster = a_roster_of_four_with_two_stale_alerts(api)

    run = get_success_data(api.run_eis_sweep(factories.eis_run_payload(), SYSTEM_ADMIN_HEADERS))

    assert_eis_run_counters(
        run,
        run_sequence=1,
        evaluated_officer_count=4,
        alerts_created=0,
        alerts_promoted=1,
        checkins_missed=0,
        disclosures_expired=0,
    )

    promoted, _ = fixtures.rows(
        api.list_eis_alerts(SYSTEM_ADMIN_HEADERS, {"officer_id": roster["pratt_id"]})
    )
    assert len(promoted) == 1
    assert_two_dp(promoted[0]["composite_score"], 55.00, label="alert.composite_score")
    assert promoted[0]["alert_level"] == "ALERT"
    assert promoted[0]["status"] == "PLAN_REQUIRED"
    assert promoted[0]["run_sequence"] == 1
    assert_instant(promoted[0]["review_due_at"], "2026-08-31T00:00:00Z")

    refreshed, _ = fixtures.rows(
        api.list_eis_alerts(SYSTEM_ADMIN_HEADERS, {"officer_id": roster["quinn_id"]})
    )
    assert len(refreshed) == 1
    assert_two_dp(refreshed[0]["composite_score"], 30.00, label="alert.composite_score")
    assert refreshed[0]["alert_level"] == "WATCH"
    assert refreshed[0]["status"] == "OPEN"
    assert refreshed[0]["run_sequence"] == 1

    quiet, quiet_meta = fixtures.rows(
        api.list_eis_alerts(SYSTEM_ADMIN_HEADERS, {"officer_id": roster["reeve_id"]})
    )
    assert quiet == []
    assert quiet_meta["total_count"] == 0

    assert_officer_risk(
        fixtures.read_officer(api, roster["pratt_id"], SYSTEM_ADMIN_HEADERS),
        eis_score=55.00,
        eis_alert_level="ALERT",
    )
    assert_officer_risk(
        fixtures.read_officer(api, roster["quinn_id"], SYSTEM_ADMIN_HEADERS),
        eis_score=30.00,
        eis_alert_level="WATCH",
    )
    assert_officer_risk(
        fixtures.read_officer(api, roster["reeve_id"], SYSTEM_ADMIN_HEADERS),
        eis_score=0.00,
        eis_alert_level="NONE",
    )
    assert_officer_risk(
        fixtures.read_officer(api, roster["sup_id"], SYSTEM_ADMIN_HEADERS),
        eis_score=0.00,
        eis_alert_level="NONE",
    )
    assert_officer_ledgers(
        fixtures.read_officer(api, roster["pratt_id"], SYSTEM_ADMIN_HEADERS), open_alert_count=1
    )
    assert_officer_ledgers(
        fixtures.read_officer(api, roster["quinn_id"], SYSTEM_ADMIN_HEADERS), open_alert_count=1
    )


def two_complaints_and_three_allegations(api):
    """Vance is named on both files; Winters only on the first."""
    world = fixtures.seed_reference_data(api)
    winters = fixtures.create_officer(
        api,
        world["patrol_unit_id"],
        badge_number="PN-502",
        full_name="Officer Winters",
        annual_salary_cents=9000000,
        demographic_code="DG_A",
    )
    first = fixtures.file_supervisor_complaint(
        api,
        world,
        narrative="Two officers failed to file reports for the same shift.",
        incident_datetime="2026-07-15T20:00:00Z",
    )
    against_vance = fixtures.attach_allegation(
        api,
        world,
        first["id"],
        allegation_type="NEGLECT_OF_DUTY",
        narrative="Vance filed nothing.",
        offense_class="C",
    )
    against_winters = fixtures.attach_allegation(
        api,
        world,
        first["id"],
        subject_officer_id=winters["id"],
        allegation_type="NEGLECT_OF_DUTY",
        narrative="Winters filed nothing either.",
        offense_class="C",
    )
    second = fixtures.file_supervisor_complaint(
        api,
        world,
        narrative="Discourtesy at a later traffic stop.",
        incident_datetime="2026-07-22T18:00:00Z",
        reported_allegation_types=["DISCOURTESY"],
    )
    later_against_vance = fixtures.attach_allegation(
        api,
        world,
        second["id"],
        allegation_type="DISCOURTESY",
        narrative="Vance was hostile at the stop.",
        offense_class="D",
    )
    world.update(
        {
            "winters_id": winters["id"],
            "c1_id": first["id"],
            "c2_id": second["id"],
            "a1_id": against_vance["id"],
            "a2_id": against_winters["id"],
            "a3_id": later_against_vance["id"],
        }
    )
    return world


def test_allegation_lists_resolve_both_of_their_foreign_keys(api):
    """The same rows are reachable from the complaint side, the officer side and both at once.

    PRD: Allegations are listed with optional `complaint_id`, `subject_officer_id`, `disposition` and `allegation_type` filters, and a single allegation read returns its evidence weights and disposition.
    PRD: Each accepted allegation raises the complaint's `allegation_count` by 1 and starts life with `disposition` `PENDING`, `evidence_weight_for` and `evidence_weight_against` both 0, `support_pct` 0.00, `redacted` false, and `policy_compliant`, `disposed_at` and `prior_sustained_count_at_disposition` all unset.
    Design: Corner/endpoints/allegation_lists_resolve_both_of_their_foreign_keys
    """
    world = two_complaints_and_three_allegations(api)
    reader = world["cmdr_headers"]

    by_complaint, complaint_meta = fixtures.rows(
        api.list_allegations(reader, {"complaint_id": world["c1_id"], "limit": 10, "offset": 0})
    )

    assert complaint_meta["total_count"] == 2
    assert {row["id"] for row in by_complaint} == {world["a1_id"], world["a2_id"]}

    by_officer, officer_meta = fixtures.rows(
        api.list_allegations(reader, {"subject_officer_id": world["subj_id"], "limit": 10, "offset": 0})
    )

    assert officer_meta["total_count"] == 2
    assert {row["id"] for row in by_officer} == {world["a1_id"], world["a3_id"]}

    intersection, intersection_meta = fixtures.rows(
        api.list_allegations(
            reader,
            {
                "complaint_id": world["c1_id"],
                "subject_officer_id": world["winters_id"],
                "limit": 10,
                "offset": 0,
            },
        )
    )

    assert intersection_meta["total_count"] == 1
    assert [row["id"] for row in intersection] == [world["a2_id"]]

    by_kind, kind_meta = fixtures.rows(
        api.list_allegations(
            reader,
            {
                "disposition": "PENDING",
                "allegation_type": "DISCOURTESY",
                "limit": 10,
                "offset": 0,
            },
        )
    )

    assert kind_meta["total_count"] == 1
    assert [row["id"] for row in by_kind] == [world["a3_id"]]

    single = fixtures.read_allegation(api, world["a3_id"], reader)

    assert single["complaint_id"] == world["c2_id"]
    assert single["subject_officer_id"] == world["subj_id"]
    assert single["allegation_type"] == "DISCOURTESY"
    assert single["disposition"] == "PENDING"
    assert single["evidence_weight_for"] == 0
    assert single["evidence_weight_against"] == 0
    assert_two_dp(single["support_pct"], 0.00, label="support_pct")
    assert single["redacted"] is False
    assert single["disposed_at"] is None

    assert fixtures.read_complaint(api, world["c1_id"], reader)["allegation_count"] == 2
    assert fixtures.read_complaint(api, world["c2_id"], reader)["allegation_count"] == 1


def three_withdrawn_complaints(api):
    """Three supervisor files opened on the first and all withdrawn on the fifth."""
    world = fixtures.seed_reference_data(api)
    filed = []
    for ordinal, incident in (
        ("First", "2026-07-15T20:00:00Z"),
        ("Second", "2026-07-16T20:00:00Z"),
        ("Third", "2026-07-17T20:00:00Z"),
    ):
        filed.append(
            fixtures.file_supervisor_complaint(
                api,
                world,
                narrative=f"{ordinal} report of missing paperwork.",
                incident_datetime=incident,
                complainant_demographic_code="DG_A",
            )
        )

    fixtures.set_clock(api, "2026-08-05T00:00:00Z")
    withdrawn = []
    for complaint in filed:
        withdrawn.append(
            fixtures.withdraw_complaint(
                api,
                world,
                complaint["id"],
                intake_reference_code=complaint["intake_reference_code"],
                withdrawal_reason="Complainant no longer wishes to proceed.",
            )
        )
    world["withdrawn"] = withdrawn
    return world


def test_the_outcome_report_derives_its_totals_without_writing_anything(api):
    """A group of exactly three is disclosed, repeats identically, and leaves the files untouched.

    PRD: `period_start` must be at or before `period_end`, otherwise `ERR_INVALID_REPORT_PERIOD`.
    PRD: The report is derived entirely on read and mutates nothing.
    PRD: The population is every complaint whose `status` is `CLOSED` or `WITHDRAWN` and whose `closed_at` falls at or after `period_start` and at or before `period_end`.
    PRD: Grouping follows the `breakdown`: `DEMOGRAPHIC` groups by `complainant_demographic_code`, with `UNKNOWN` forming a group of its own; `CHANNEL` groups by `intake_channel`; and when `breakdown` is omitted the whole population forms a single group whose `group_key` is the literal `ALL`.
    PRD: `suppression_min_cell` reports the threshold, which is 3.
    PRD: A group of exactly 3 is disclosed in full, since the comparison is strict.
    PRD: An accepted withdrawal always stamps `closed_at` from the logical clock, sets `retention_until` to `closed_at` plus 730 whole days, and sets every allegation still in `PENDING` to `disposition` `WITHDRAWN`.
    Design: Corner/endpoints/the_outcome_report_derives_its_totals_without_writing_anything
    """
    world = three_withdrawn_complaints(api)
    for complaint in world["withdrawn"]:
        assert complaint["status"] == "WITHDRAWN"
        assert_instant(complaint["closed_at"], "2026-08-05T00:00:00Z")

    in_period = factories.outcome_report_params(
        "2026-08-01T00:00:00Z", "2026-08-31T00:00:00Z"
    )
    first_read = get_success_data(
        api.get_complaint_outcome_report(RECORDS_CUSTODIAN_HEADERS, in_period)
    )

    assert_instant(first_read["period_start"], "2026-08-01T00:00:00Z")
    assert_instant(first_read["period_end"], "2026-08-31T00:00:00Z")
    assert first_read["total_complaints"] == 3
    assert first_read["sustained_complaints"] == 0
    assert_one_dp(first_read["sustain_rate_pct"], 0.0, label="sustain_rate_pct")
    assert first_read["suppression_min_cell"] == 3
    assert len(first_read["groups"]) == 1
    assert_report_group(first_read["groups"][0], "ALL", 3, 0, 0.0, False)

    second_read = get_success_data(
        api.get_complaint_outcome_report(RECORDS_CUSTODIAN_HEADERS, in_period)
    )

    assert second_read == first_read

    later = get_success_data(
        api.get_complaint_outcome_report(
            RECORDS_CUSTODIAN_HEADERS,
            factories.outcome_report_params("2026-08-06T00:00:00Z", "2026-08-31T00:00:00Z"),
        )
    )

    assert later["total_complaints"] == 0
    assert later["sustained_complaints"] == 0
    assert_one_dp(later["sustain_rate_pct"], 0.0, label="sustain_rate_pct")

    reversed_period = api.get_complaint_outcome_report(
        RECORDS_CUSTODIAN_HEADERS,
        factories.outcome_report_params("2026-08-31T00:00:00Z", "2026-08-01T00:00:00Z"),
    )

    validate_error(reversed_period, "ERR_INVALID_REPORT_PERIOD", 422)

    for complaint in world["withdrawn"]:
        untouched = fixtures.read_complaint(api, complaint["id"], RECORDS_CUSTODIAN_HEADERS)
        assert untouched["status"] == "WITHDRAWN"
        assert untouched["sustained_allegation_count"] == 0
        assert untouched["purged_at"] is None
        assert untouched["version"] == complaint["version"]
        assert_instant(untouched["closed_at"], "2026-08-05T00:00:00Z")
        assert_instant(untouched["retention_until"], "2028-08-04T00:00:00Z")
