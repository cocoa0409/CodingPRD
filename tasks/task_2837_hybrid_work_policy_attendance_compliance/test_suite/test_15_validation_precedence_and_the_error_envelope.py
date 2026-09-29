"""Which rule answers when several are broken at once, and what a refusal looks like."""
from test_helpers import (
    ApiErrorId,
    HRBP_USER_ID,
    MANAGER_USER_ID,
    UNKNOWN_TEAM_ID,
    add_signal,
    api_client,
    attendance_week_payload,
    classification_payload,
    create_cycle,
    create_neighborhood,
    create_team,
    desk_assignment_payload,
    draft_review,
    employee_payload,
    exception_request_payload,
    finalize,
    first_case_for,
    get_success_data,
    list_all,
    neighborhood_payload,
    open_and_finalize_week,
    open_week,
    pin_clock,
    policy_cycle_payload,
    read_cycle,
    read_employee,
    read_neighborhood,
    read_team,
    read_week,
    recalibration_review_payload,
    register_employee,
    reserve_allocation,
    seat_allocation_payload,
    signal_payload,
    team_payload,
    validate_error,
)
from test_helpers.fixtures import HRBP, SYSTEM, WPO

STANDARD_DIALS = {
    "effective_from": "2026-09-01",
    "effective_to": "2026-12-31",
    "days_in_office_floor": 2,
    "badge_weight": 0.60,
    "network_weight": 0.40,
    "collaboration_target_score": 70.00,
    "equity_variance_threshold_pct": 20.00,
}

THREE_DAY_TEAM = {
    "expected_days_in_office_per_week": 3,
    "core_collaboration_days": ["TUE", "WED", "THU"],
    "headcount_planned": 12,
    "signal_corroboration_required": False,
}

BADGED_DATES = ["2026-09-08", "2026-09-09", "2026-09-10"]

NO_IDENTITY_SYSTEM = {**SYSTEM, "X-User-ID": ""}


def _a_week_already_carrying_one_badge_signal():
    """An open 2026-W37 week whose Tuesday badge swipe used the key 'B-0908'."""
    pin_clock()
    cycle = create_cycle(cycle_label="FY27-PP2", **STANDARD_DIALS)
    team = create_team(cycle["id"], team_code="T1-CORE", **THREE_DAY_TEAM)
    employee = register_employee(
        team["id"], employee_number="E-1001", work_email="e1001@corp.example"
    )
    week = open_week(employee["id"], "2026-W37")
    first_signal = add_signal(
        week["id"], "2026-09-08", minutes_present=480, dedupe_key="B-0908"
    )
    return {
        "cycle": cycle,
        "team": team,
        "employee": employee,
        "week": week,
        "first_signal": first_signal,
    }


def _two_cycles_with_one_of_everything_in_the_first():
    """Every uniqueness-bearing row exists once under the first cycle; the second is bare."""
    pin_clock()
    first = create_cycle(cycle_label="FY27-CRN46", **STANDARD_DIALS)
    second_dials = dict(STANDARD_DIALS)
    second_dials["effective_from"] = "2027-01-01"
    second_dials["effective_to"] = "2027-06-30"
    second = create_cycle(cycle_label="FY27-CRN47", **second_dials)
    team = create_team(first["id"], team_code="T-A", **THREE_DAY_TEAM)
    zone = create_neighborhood(
        first["id"], team["id"], neighborhood_code="N-1", site_code="NYC-01",
        seat_count=13, buffer_seats=4, desk_index_from=1, desk_index_to=13,
    )
    employee = register_employee(
        team["id"], employee_number="E-1001", work_email="e1001@corp.example"
    )
    week = open_week(employee["id"], "2026-W37")
    review = draft_review(first["id"], 0, review_label="R-1")
    return {
        "first": first,
        "second": second,
        "team": team,
        "zone": zone,
        "employee": employee,
        "week": week,
        "review": review,
    }


def _a_zone_whose_version_has_already_moved():
    """One reservation has already advanced the zone, so the captured version is stale."""
    pin_clock()
    cycle = create_cycle(cycle_label="FY27-CRN48", **STANDARD_DIALS)
    team = create_team(cycle["id"], team_code="T-A", **THREE_DAY_TEAM)
    employee = register_employee(
        team["id"], employee_number="E-1001", work_email="e1001@corp.example"
    )
    zone = create_neighborhood(
        cycle["id"], team["id"], neighborhood_code="N-1", site_code="NYC-01",
        seat_count=13, buffer_seats=4, desk_index_from=1, desk_index_to=13,
    )
    allocation = reserve_allocation(
        zone["id"], team["id"], 2, "2026-W37", "2026-W40", zone["version"]
    )
    return {
        "cycle": cycle,
        "team": team,
        "employee": employee,
        "zone": zone,
        "stale_version": zone["version"],
        "current_version": read_neighborhood(zone["id"])["version"],
        "allocation": allocation,
    }


def _a_cycle_team_employee_and_an_open_week(cycle_label):
    """The smallest world that can carry a shape violation on every entity."""
    pin_clock()
    cycle = create_cycle(cycle_label=cycle_label, **STANDARD_DIALS)
    team = create_team(cycle["id"], team_code="T-A", **THREE_DAY_TEAM)
    employee = register_employee(
        team["id"], employee_number="E-1001", work_email="e1001@corp.example"
    )
    week = open_week(employee["id"], "2026-W37")
    return {"cycle": cycle, "team": team, "employee": employee, "week": week}


def _a_settled_breach_with_every_rollup_raised():
    """One finalized short week, so every counter from week to cycle is off its floor."""
    pin_clock()
    cycle = create_cycle(cycle_label="FY27-CRN58", **STANDARD_DIALS)
    team = create_team(cycle["id"], team_code="T-A", **THREE_DAY_TEAM)
    employee = register_employee(
        team["id"], employee_number="E-1001", work_email="e1001@corp.example"
    )
    zone = create_neighborhood(
        cycle["id"], team["id"], neighborhood_code="N-1", site_code="NYC-01",
        seat_count=13, buffer_seats=4, desk_index_from=1, desk_index_to=13,
    )
    week = open_and_finalize_week(employee["id"], "2026-W37", BADGED_DATES)
    return {
        "cycle": cycle,
        "team": team,
        "employee": employee,
        "zone": zone,
        "week": week,
    }


def _assert_error_envelope(response, expected_status, expected_error_id):
    """A refusal carries exactly the two declared data fields and the two meta fields."""
    error_data = validate_error(response, expected_error_id, expected_status)
    body = response.json()
    assert body["response_type"] == "error"
    assert set(body["meta"]) == {"api_request_id", "api_request_timestamp"}, (
        "an error envelope's meta carries only the request id and timestamp"
    )
    assert body["meta"]["api_request_id"].startswith("req_")
    assert set(error_data) == {"error_id", "message"}, (
        "no entity field may leak through an error envelope"
    )
    assert isinstance(error_data["message"], str)
    assert error_data["message"].strip() != ""
    return error_data


def test_01_a_replayed_key_on_an_out_of_week_date_answers_the_uniqueness_rule():
    """The duplicate wins over the containment gate; a fresh key exposes the gate again.

    PRD 2.10: "When a single request violates several rules at once, exactly one error is
    returned, and which one is fully determined."
    PRD 2.10: "A replayed signal whose `dedupe_key` already exists on the week *and* whose
    `observed_date` falls outside the week reports `ERR_DUPLICATE_SIGNAL` (409), since
    uniqueness outranks the containment gate — though both sit below the editability check,
    so a replay onto an already-`FINALIZED` week reports `ERR_WEEK_NOT_OPEN` (409)."
    PRD 3.4: "A `dedupe_key` already present on that week is `ERR_DUPLICATE_SIGNAL` (409),
    and an `observed_date` falling outside the week's seven dates is
    `ERR_SIGNAL_OUTSIDE_WEEK` (422)."
    PRD 3.4: "Appending a signal moves no derived field whatsoever: signals are pure
    evidence, and nothing is credited until the week is settled."

    Design: Difficulty/priority_pair_validation_conflict/duplicate_signal_outranks_signal_outside_week
    """
    scenario = _a_week_already_carrying_one_badge_signal()
    week_id = scenario["week"]["id"]

    _assert_error_envelope(
        api_client.append_signal(
            week_id,
            signal_payload(
                "2026-09-20", site_code="NYC-01", minutes_present=480,
                dedupe_key="B-0908",
            ),
            SYSTEM,
        ),
        409,
        ApiErrorId.ERR_DUPLICATE_SIGNAL.value,
    )

    _assert_error_envelope(
        api_client.append_signal(
            week_id,
            signal_payload(
                "2026-09-20", site_code="NYC-01", minutes_present=480,
                dedupe_key="B-0920",
            ),
            SYSTEM,
        ),
        422,
        ApiErrorId.ERR_SIGNAL_OUTSIDE_WEEK.value,
    )

    rows, meta = list_all(
        api_client.list_compliance_signals, SYSTEM, {"attendance_week_id": week_id}
    )
    assert meta["total_count"] == 1, "neither refusal stored a row"
    assert rows[0]["id"] == scenario["first_signal"]["id"]
    week = read_week(week_id)
    assert week["status"] == "OPEN"
    assert week["credited_days"] == 0, "evidence alone credits nothing"
    assert week["required_days"] == 0
    assert week["shortfall_days"] == 0


def test_02_the_last_date_of_the_week_is_inside_it_and_a_settled_week_refuses_first():
    """Sunday is one of the seven dates; once the week is settled the state rule answers.

    PRD 3.4: "**Credited days** are counted date by date across the week's seven dates,
    against a minute floor of four hours — a badge or network observation must record at
    least 240 minutes present to count, while a manual attestation counts on the strength
    of its existence alone and its `minutes_present` is ignored entirely."
    PRD 3.4: "Under the `SIGNAL_UNION` standard, used when the team does not require
    corroboration, a date counts when **any** of badge, network or attestation evidence is
    satisfied, so a badge-only day counts."
    PRD 3.4: "Signals may only be appended while the week is still editable — that is,
    while its `status` is `OPEN` or `AMENDED`; an append onto a `FINALIZED` or `LOCKED`
    week is refused with `ERR_WEEK_NOT_OPEN` (409)."
    PRD 2.10: "A replayed signal whose `dedupe_key` already exists on the week *and* whose
    `observed_date` falls outside the week reports `ERR_DUPLICATE_SIGNAL` (409), since
    uniqueness outranks the containment gate — though both sit below the editability check,
    so a replay onto an already-`FINALIZED` week reports `ERR_WEEK_NOT_OPEN` (409)."
    PRD 3.3: "Every role in the company is eventually classified as one of three
    eligibility classes — `FULLY_REMOTE`, `HYBRID` or `ONSITE_REQUIRED` — and until a
    classification has been approved the employee is treated as `ONSITE_REQUIRED`."
    PRD 3.4: "An `ONSITE_REQUIRED` employee is required for all five working days."
    PRD 2.3: "Several collections override that default because their business ordering
    matters more than their insertion ordering: policy cycles are returned newest first,
    by `created_at` descending; teams are ordered by `team_code` ascending; employees by
    `employee_number` ascending; eligibility classifications by `effective_from`
    descending and then `created_at` descending, which is the same ranking the
    current-class selector uses; attendance weeks by `week_start_date` ascending;
    compliance signals by `observed_date` ascending and then `created_at` ascending;
    neighborhoods by `neighborhood_code` ascending; and desk assignments by `start_date`
    ascending and then `desk_index` ascending."

    Design: Difficulty/priority_pair_validation_conflict/duplicate_signal_outranks_signal_outside_week
    """
    scenario = _a_week_already_carrying_one_badge_signal()
    week_id = scenario["week"]["id"]

    sunday = get_success_data(
        api_client.append_signal(
            week_id,
            signal_payload(
                "2026-09-13", site_code="NYC-01", minutes_present=480,
                dedupe_key="B-0913",
            ),
            SYSTEM,
        ),
        201,
    )
    assert sunday["observed_date"] == "2026-09-13", (
        "the inclusive last date of the week is inside the week"
    )
    assert sunday["signal_source"] == "BADGE"
    assert sunday["dedupe_key"] == "B-0913"

    rows, meta = list_all(
        api_client.list_compliance_signals, SYSTEM, {"attendance_week_id": week_id}
    )
    assert meta["total_count"] == 2
    assert [row["observed_date"] for row in rows] == ["2026-09-08", "2026-09-13"]

    settled = finalize(week_id, SYSTEM)
    assert settled["status"] == "FINALIZED"
    assert settled["variant_applied"] == "SIGNAL_UNION"
    assert settled["required_days"] == 5, "the employee is unclassified, so onsite"
    assert settled["credited_days"] == 2, "both full-day badge dates counted"
    assert settled["shortfall_days"] == 3

    _assert_error_envelope(
        api_client.append_signal(
            week_id,
            signal_payload(
                "2026-09-20", site_code="NYC-01", minutes_present=480,
                dedupe_key="B-0908",
            ),
            SYSTEM,
        ),
        409,
        ApiErrorId.ERR_WEEK_NOT_OPEN.value,
    )
    assert read_week(week_id)["credited_days"] == 2, (
        "the editability rule sits above both the duplicate and the containment gate"
    )


def test_03_every_declared_unique_key_refuses_a_replay_inside_its_own_scope():
    """Three keys are global, three are cycle-scoped, one is a pair, and both keys tie-break.

    PRD 3.1: "A `WorkplaceProgramOffice` operator opens one by supplying a `cycle_label` of
    1 to 40 characters that no other cycle already uses (a collision is
    `ERR_DUPLICATE_CYCLE_LABEL`), the inclusive calendar dates `effective_from` and
    `effective_to` where the end date must fall strictly after the start date, and the four
    policy dials described below."
    PRD 3.1: "A team is enrolled by naming its `policy_cycle_id` and a `team_code` of 1 to
    24 characters drawn from uppercase alphanumerics and hyphens, unique among the teams of
    that cycle (a collision is `ERR_DUPLICATE_TEAM_CODE`)."
    PRD 3.8: "A `WorkplaceProgramOffice` operator creates a neighborhood under a
    `policy_cycle_id`, designed around an `anchor_team_id`, with a `neighborhood_code` of 1
    to 24 characters unique within the cycle (a collision is
    `ERR_DUPLICATE_NEIGHBORHOOD_CODE`) and a `site_code` of 1 to 16 characters."
    PRD 3.2: "An `HRBusinessPartner` registers an employee against a `team_id`, supplying
    an `employee_number` of 1 to 24 characters that is globally unique (a collision is
    `ERR_DUPLICATE_EMPLOYEE_NUMBER`), a `work_email` that must contain an at-sign and is
    likewise globally unique (`ERR_DUPLICATE_WORK_EMAIL`), the IANA `home_timezone`
    recorded for policy communication and used in no calculation, the `tenure_start_date`
    on which employment began, and a `demographic_band` of `BAND_A`, `BAND_B`, `BAND_C` or
    `BAND_D` used solely by the equity monitoring of §3.9."
    PRD 2.10: "An employee payload duplicating both `employee_number` and `work_email`
    reports `ERR_DUPLICATE_EMPLOYEE_NUMBER`."
    PRD 3.4: "At most one week may exist per employee and `iso_week` pair; a second attempt
    is `ERR_DUPLICATE_ATTENDANCE_WEEK` (409)."
    PRD 3.9: "A review is drafted against a `policy_cycle_id` with a `review_label` of 1 to
    40 characters unique within that cycle — a collision is `ERR_DUPLICATE_REVIEW_LABEL`
    (409) — and a `proposed_days_in_office_delta`, a signed integer from -2 through 2
    naming the change that would be applied to every team on adoption."

    Design: Corner/validations/uniqueness_sweep_over_every_declared_unique_key_rejects_replays
    """
    world = _two_cycles_with_one_of_everything_in_the_first()
    first_id = world["first"]["id"]
    second_id = world["second"]["id"]
    team_id = world["team"]["id"]

    validate_error(
        api_client.create_policy_cycle(
            policy_cycle_payload(
                cycle_label="FY27-CRN46", effective_from="2028-01-01",
                effective_to="2028-06-30", days_in_office_floor=3,
                badge_weight=0.50, network_weight=0.50,
                collaboration_target_score=60.00,
                equity_variance_threshold_pct=15.00,
            ),
            WPO,
        ),
        ApiErrorId.ERR_DUPLICATE_CYCLE_LABEL.value,
        409,
    )

    replayed_team = team_payload(
        first_id, team_code="T-A", expected_days_in_office_per_week=4,
        core_collaboration_days=["MON", "TUE", "WED", "THU"], headcount_planned=8,
    )
    validate_error(
        api_client.create_team(replayed_team, WPO),
        ApiErrorId.ERR_DUPLICATE_TEAM_CODE.value,
        409,
    )
    elsewhere = get_success_data(
        api_client.create_team(dict(replayed_team, policy_cycle_id=second_id), WPO), 201
    )
    assert elsewhere["team_code"] == "T-A", (
        "the code is scoped to its cycle, so a second cycle may reuse it"
    )

    validate_error(
        api_client.create_neighborhood(
            neighborhood_payload(
                first_id, team_id, neighborhood_code="N-1", site_code="NYC-02",
                seat_count=4, buffer_seats=1, desk_index_from=40, desk_index_to=43,
            ),
            WPO,
        ),
        ApiErrorId.ERR_DUPLICATE_NEIGHBORHOOD_CODE.value,
        409,
    )

    validate_error(
        api_client.create_employee(
            employee_payload(
                team_id, MANAGER_USER_ID, HRBP_USER_ID, employee_number="E-1001",
                work_email="e1001@corp.example", home_timezone="America/Chicago",
                tenure_start_date="2025-01-06", demographic_band="BAND_B",
            ),
            HRBP,
        ),
        ApiErrorId.ERR_DUPLICATE_EMPLOYEE_NUMBER.value,
        409,
    )
    validate_error(
        api_client.create_employee(
            employee_payload(
                team_id, MANAGER_USER_ID, HRBP_USER_ID, employee_number="E-9999",
                work_email="e1001@corp.example", home_timezone="America/Chicago",
                tenure_start_date="2025-01-06", demographic_band="BAND_B",
            ),
            HRBP,
        ),
        ApiErrorId.ERR_DUPLICATE_WORK_EMAIL.value,
        409,
    )

    validate_error(
        api_client.create_attendance_week(
            attendance_week_payload(world["employee"]["id"], "2026-W37"), SYSTEM
        ),
        ApiErrorId.ERR_DUPLICATE_ATTENDANCE_WEEK.value,
        409,
    )

    validate_error(
        api_client.create_recalibration_review(
            recalibration_review_payload(
                first_id, review_label="R-1", proposed_days_in_office_delta=1
            ),
            WPO,
        ),
        ApiErrorId.ERR_DUPLICATE_REVIEW_LABEL.value,
        409,
    )
    reused = get_success_data(
        api_client.create_recalibration_review(
            recalibration_review_payload(
                second_id, review_label="R-1", proposed_days_in_office_delta=1
            ),
            WPO,
        ),
        201,
    )
    assert reused["review_label"] == "R-1", "the label is scoped to its cycle too"

    cycles, cycle_meta = list_all(api_client.list_policy_cycles, WPO)
    assert cycle_meta["total_count"] == 2
    assert {row["cycle_label"] for row in cycles} == {"FY27-CRN46", "FY27-CRN47"}
    _, team_meta = list_all(
        api_client.list_teams, WPO, {"policy_cycle_id": first_id}
    )
    assert team_meta["total_count"] == 1
    _, employee_meta = list_all(
        api_client.list_employees, HRBP, {"team_id": team_id}
    )
    assert employee_meta["total_count"] == 1
    _, review_meta = list_all(
        api_client.list_recalibration_reviews, WPO, {"policy_cycle_id": first_id}
    )
    assert review_meta["total_count"] == 1, "every refusal was a true no-op"


def test_04_interval_shape_is_judged_before_concurrency_on_all_three_carriers():
    """A half-open window needs a strictly later end; closed windows accept equal endpoints.

    PRD 2.10: "Checks are grouped into precedence bands and evaluated from the top of this
    list downwards; the first band that produces a violation supplies the response, and
    later bands are never reached."
    PRD 2.10: "7. **Interval well-formedness** — `ERR_INVALID_INTERVAL` for an empty or
    inverted declared interval."
    PRD 2.10: "8. **Optimistic concurrency** — the three stale-version codes of §2.8."
    PRD 2.8: "`POST /seat-allocations` must carry `expected_neighborhood_version`, equal to
    the current `version` of the `Neighborhood` named by `neighborhood_id`."
    PRD 3.8: "The window must be non-empty in ISO-week ordinal terms — `window_end_week`
    strictly later than `window_start_week` — and both labels well formed, or the request is
    refused with `ERR_INVALID_INTERVAL` (422)."
    PRD 3.8: "A successful reservation lands in `RESERVED` status with `release_reason`
    null, `line_chargeback_cents` at 0, and `weeks_in_window` set to the number of ISO weeks
    in the half-open interval — the ordinal of `window_end_week` minus the ordinal of
    `window_start_week`."
    PRD 3.8: "It also advances the parent neighborhood's `version` by one."
    PRD 3.8: "An end date earlier than the start date is `ERR_INVALID_INTERVAL` (422)."
    PRD 3.6: "The payload names the `employee_id`, a `category` of `MEDICAL`, `CAREGIVING`
    or `DISABILITY_ACCOMMODATION`, the `requested_relief_days` as an integer from 1 through
    5 representing days-in-office relief per affected week, the inclusive `start_date` and
    `end_date` of the relief window, and a `rationale` of 1 to 1000 characters."
    PRD 3.6: "An end date earlier than the start date is refused with
    `ERR_INVALID_INTERVAL` (422)."

    Design: Corner/validations/interval_shape_is_checked_on_all_three_carriers_and_outranks_concurrency
    """
    scenario = _a_zone_whose_version_has_already_moved()
    zone_id = scenario["zone"]["id"]
    team_id = scenario["team"]["id"]
    employee_id = scenario["employee"]["id"]
    stale = scenario["stale_version"]
    current = scenario["current_version"]
    assert current == stale + 1, "the first reservation already moved the zone"

    validate_error(
        api_client.create_seat_allocation(
            seat_allocation_payload(
                zone_id, team_id, stale, allocated_seats=1,
                window_start_week="2026-W38", window_end_week="2026-W38",
            ),
            WPO,
        ),
        ApiErrorId.ERR_INVALID_INTERVAL.value,
        422,
    )
    validate_error(
        api_client.create_seat_allocation(
            seat_allocation_payload(
                zone_id, team_id, current, allocated_seats=1,
                window_start_week="2026-W40", window_end_week="2026-W38",
            ),
            WPO,
        ),
        ApiErrorId.ERR_INVALID_INTERVAL.value,
        422,
    )
    validate_error(
        api_client.create_desk_assignment(
            desk_assignment_payload(
                scenario["allocation"]["id"], employee_id, desk_index=1,
                start_date="2026-09-11", end_date="2026-09-07",
            ),
            WPO,
        ),
        ApiErrorId.ERR_INVALID_INTERVAL.value,
        422,
    )
    validate_error(
        api_client.create_exception_request(
            exception_request_payload(
                employee_id, category="CAREGIVING", requested_relief_days=2,
                start_date="2026-09-11", end_date="2026-09-07",
                rationale="inverted window typed by mistake",
            ),
            HRBP,
        ),
        ApiErrorId.ERR_INVALID_INTERVAL.value,
        422,
    )

    narrowest = get_success_data(
        api_client.create_seat_allocation(
            seat_allocation_payload(
                zone_id, team_id, current, allocated_seats=1,
                window_start_week="2026-W38", window_end_week="2026-W39",
            ),
            WPO,
        ),
        201,
    )
    assert narrowest["status"] == "RESERVED"
    assert narrowest["weeks_in_window"] == 1, "one week is the narrowest legal window"

    single_day = get_success_data(
        api_client.create_exception_request(
            exception_request_payload(
                employee_id, category="CAREGIVING", requested_relief_days=1,
                start_date="2026-09-09", end_date="2026-09-09",
                rationale="single-day caregiving absence",
            ),
            HRBP,
        ),
        201,
    )
    assert single_day["status"] == "SUBMITTED"
    assert single_day["start_date"] == single_day["end_date"], (
        "a closed interval of one day is well formed, unlike the half-open case"
    )
    assert single_day["requested_relief_days"] == 1

    assert read_neighborhood(zone_id)["version"] == current + 1, (
        "only the accepted reservation advanced the zone"
    )
    _, meta = list_all(
        api_client.list_seat_allocations, WPO, {"neighborhood_id": zone_id}
    )
    assert meta["total_count"] == 2, "the four refusals created nothing"


def test_05_out_of_range_numbers_a_mismatched_band_and_an_unknown_enum_all_refuse():
    """Six declared ranges, a band that is not the seat count, and a bad source all answer 422.

    PRD 2.10: "6. **Request shape** — missing required fields, undeclared enum members and
    out-of-range numbers, all `ERR_INVALID_REQUEST`."
    PRD 3.1: "The team declares `expected_days_in_office_per_week`, an integer from 0
    through 5 which must be at least the cycle's `days_in_office_floor`; a lower value is
    refused with `ERR_INVALID_REQUEST`."
    PRD 3.8: "The band must be well formed and exactly the right width: `desk_index_from`
    at least 1, `desk_index_to` at least `desk_index_from`, and the count of indices from
    one to the other inclusive equal to `seat_count`."
    PRD 3.8: "An inverted band, a band narrower or wider than the seat count, or a buffer
    at least as large as the seat count is refused with `ERR_INVALID_REQUEST` (422)."
    PRD 3.4: "each append names a `signal_source` of `BADGE`, `NETWORK` or
    `MANUAL_ATTEST`, the `site_code` of the building or campus where presence was observed
    (1 to 16 characters), the `observed_date`, the `minutes_present` observed on site as an
    integer from 0 through 1440, and a `dedupe_key` of 1 to 64 characters that the upstream
    feed uses as its idempotency handle."
    PRD 3.6: "The payload names the `employee_id`, a `category` of `MEDICAL`, `CAREGIVING`
    or `DISABILITY_ACCOMMODATION`, the `requested_relief_days` as an integer from 1 through
    5 representing days-in-office relief per affected week, the inclusive `start_date` and
    `end_date` of the relief window, and a `rationale` of 1 to 1000 characters."
    PRD 3.9: "A review is drafted against a `policy_cycle_id` with a `review_label` of 1 to
    40 characters unique within that cycle — a collision is `ERR_DUPLICATE_REVIEW_LABEL`
    (409) — and a `proposed_days_in_office_delta`, a signed integer from -2 through 2 naming
    the change that would be applied to every team on adoption."
    PRD 2.3: "`limit` defaults to 10, must be at least 1 and at most 100; `offset` defaults
    to 0 and must be at least 0."

    Design: Corner/validations/numeric_range_band_width_and_enum_shape_rejections
    """
    world = _a_cycle_team_employee_and_an_open_week("FY27-CRN49")
    cycle_id = world["cycle"]["id"]
    team_id = world["team"]["id"]
    invalid = ApiErrorId.ERR_INVALID_REQUEST.value

    validate_error(
        api_client.create_team(
            team_payload(
                cycle_id, team_code="T-SIX", expected_days_in_office_per_week=6,
                core_collaboration_days=["MON", "TUE", "WED", "THU", "FRI"],
                headcount_planned=12,
            ),
            WPO,
        ),
        invalid,
        422,
    )
    validate_error(
        api_client.create_neighborhood(
            neighborhood_payload(
                cycle_id, team_id, neighborhood_code="N-NARROW",
                site_code="NYC-01", seat_count=13, buffer_seats=4,
                desk_index_from=1, desk_index_to=12,
            ),
            WPO,
        ),
        invalid,
        422,
    )
    validate_error(
        api_client.create_neighborhood(
            neighborhood_payload(
                cycle_id, team_id, neighborhood_code="N-NOCAP",
                site_code="NYC-01", seat_count=13, buffer_seats=13,
                desk_index_from=1, desk_index_to=13,
            ),
            WPO,
        ),
        invalid,
        422,
    )
    validate_error(
        api_client.append_signal(
            world["week"]["id"],
            signal_payload(
                "2026-09-08", signal_source="VPN_TUNNEL", dedupe_key="S-ENUM"
            ),
            SYSTEM,
        ),
        invalid,
        422,
    )
    validate_error(
        api_client.append_signal(
            world["week"]["id"],
            signal_payload(
                "2026-09-08", minutes_present=1441, dedupe_key="S-MINUTES"
            ),
            SYSTEM,
        ),
        invalid,
        422,
    )
    validate_error(
        api_client.create_exception_request(
            exception_request_payload(
                world["employee"]["id"], requested_relief_days=0,
                start_date="2026-09-07", end_date="2026-09-11",
            ),
            HRBP,
        ),
        invalid,
        422,
    )
    validate_error(
        api_client.create_recalibration_review(
            recalibration_review_payload(
                cycle_id, review_label="R-BIG", proposed_days_in_office_delta=3
            ),
            WPO,
        ),
        invalid,
        422,
    )
    validate_error(
        api_client.list_employees(HRBP, {"team_id": team_id, "limit": 101}),
        invalid,
        422,
    )

    _, team_meta = list_all(api_client.list_teams, WPO, {"policy_cycle_id": cycle_id})
    assert team_meta["total_count"] == 1, "only the fixture team survived"
    _, zone_meta = list_all(
        api_client.list_neighborhoods, WPO, {"policy_cycle_id": cycle_id}
    )
    assert zone_meta["total_count"] == 0, "neither malformed zone was stored"
    _, signal_meta = list_all(
        api_client.list_compliance_signals, WPO,
        {"attendance_week_id": world["week"]["id"]},
    )
    assert signal_meta["total_count"] == 0, "a rejected append leaves no evidence"
    assert read_week(world["week"]["id"])["status"] == "OPEN"


def test_06_each_input_sitting_exactly_on_its_legal_extreme_is_accepted():
    """A zero-day team, a one-seat usable zone, 1440 minutes, five relief days and a -2 delta.

    PRD 3.1: "The first dial is `days_in_office_floor`, an integer from 0 through 5 that no
    team in the cycle may declare an expectation below."
    PRD 3.1: "It also declares `core_collaboration_days`, an array of between zero and five
    distinct weekday codes drawn from `MON`, `TUE`, `WED`, `THU` and `FRI` on which the team
    is expected to co-locate — published in the policy communication and not consumed by any
    calculation — and `headcount_planned`, an integer from 1 through 5000."
    PRD 3.1: "Step one: `expected_daily_attendance` is the planned headcount multiplied by
    the expected days in office, divided by the five working days of a week, then rounded
    **up** to a whole number."
    PRD 3.1: "Step five: `entitled_seats` is `base_entitlement` plus
    `buffer_seats_entitled`, and it is the per-week ceiling on how many seats the team may
    hold."
    PRD 3.8: "It declares `seat_count` as an integer from 1 through 500, `buffer_seats` as
    an integer of at least 0 that must be strictly smaller than `seat_count` so that usable
    capacity is positive, and the contiguous desk index band `desk_index_from` and
    `desk_index_to`."
    PRD 3.8: "A new zone starts with `committed_seats` and `peak_committed_seats` at 0,
    `utilization_pct` at 0.00, and `allocation_state` at `OPEN` — or already `FROZEN`, when
    the parent cycle is `LOCKED`."
    PRD 3.4: "the `minutes_present` observed on site as an integer from 0 through 1440"
    PRD 3.6: "the `requested_relief_days` as an integer from 1 through 5 representing
    days-in-office relief per affected week"
    PRD 3.9: "and a `proposed_days_in_office_delta`, a signed integer from -2 through 2
    naming the change that would be applied to every team on adoption."
    PRD 2.3: "`limit` defaults to 10, must be at least 1 and at most 100; `offset` defaults
    to 0 and must be at least 0."

    Design: Corner/validations/every_legal_boundary_value_is_accepted
    """
    pin_clock()
    edge_dials = dict(STANDARD_DIALS)
    edge_dials["days_in_office_floor"] = 0
    cycle = create_cycle(cycle_label="FY27-CRN50", **edge_dials)
    cycle_id = cycle["id"]

    zero_day_team = get_success_data(
        api_client.create_team(
            team_payload(
                cycle_id, team_code="T-ZERO", expected_days_in_office_per_week=0,
                core_collaboration_days=[], headcount_planned=12,
                signal_corroboration_required=False,
            ),
            WPO,
        ),
        201,
    )
    assert zero_day_team["expected_days_in_office_per_week"] == 0, (
        "zero meets a floor of zero"
    )
    assert zero_day_team["core_collaboration_days"] == [], "an empty array is legal"
    assert zero_day_team["expected_daily_attendance"] == 0
    assert zero_day_team["base_entitlement"] == 0
    assert zero_day_team["buffer_seats_entitled"] == 0, (
        "the smallest tier still applies but adds nothing to a zero base"
    )
    assert zero_day_team["entitled_seats"] == 0
    team_id = zero_day_team["id"]

    edge_zone = get_success_data(
        api_client.create_neighborhood(
            neighborhood_payload(
                cycle_id, team_id, neighborhood_code="N-EDGE", site_code="NYC-01",
                seat_count=6, buffer_seats=5, desk_index_from=4, desk_index_to=9,
            ),
            WPO,
        ),
        201,
    )
    assert edge_zone["buffer_seats"] == 5, "one below the seat count leaves capacity of one"
    assert edge_zone["desk_index_from"] == 4
    assert edge_zone["desk_index_to"] == 9, "a band of exactly six indices for six seats"
    assert edge_zone["utilization_pct"] == 0.00
    assert edge_zone["allocation_state"] == "OPEN"

    employee = register_employee(
        team_id, employee_number="E-2001", work_email="e2001@corp.example"
    )
    week = open_week(employee["id"], "2026-W37")
    max_signal = get_success_data(
        api_client.append_signal(
            week["id"],
            signal_payload("2026-09-13", minutes_present=1440, dedupe_key="S-MAX"),
            SYSTEM,
        ),
        201,
    )
    assert max_signal["minutes_present"] == 1440, "the exact ceiling of the range"
    assert max_signal["observed_date"] == "2026-09-13", "the last of the week's seven dates"

    full_relief = get_success_data(
        api_client.create_exception_request(
            exception_request_payload(
                employee["id"], requested_relief_days=5,
                start_date="2026-09-07", end_date="2026-09-11",
                rationale="full week of caregiving relief requested",
            ),
            HRBP,
        ),
        201,
    )
    assert full_relief["requested_relief_days"] == 5
    assert full_relief["status"] == "SUBMITTED"

    lowest_delta = get_success_data(
        api_client.create_recalibration_review(
            recalibration_review_payload(
                cycle_id, review_label="R-MIN", proposed_days_in_office_delta=-2
            ),
            WPO,
        ),
        201,
    )
    assert lowest_delta["proposed_days_in_office_delta"] == -2, "the exact range floor"
    assert lowest_delta["state"] == "DRAFT", (
        "the days-floor consequence is deferred to the decision"
    )

    rows, meta = list_all(
        api_client.list_employees, HRBP,
        {"team_id": team_id, "limit": 100, "offset": 0},
    )
    assert meta["limit"] == 100, "the exact ceiling of the window parameter"
    assert meta["offset"] == 0
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert [row["employee_number"] for row in rows] == ["E-2001"]


def test_07_six_bands_of_the_ladder_all_answer_with_the_same_two_field_envelope():
    """401, 403, 404, 409, 412 and 422 differ only in code and status, never in shape.

    PRD 2.2: "The `meta` object for error responses contains only `api_request_id` and
    `api_request_timestamp`."
    PRD 2.2: "The `api_request_id` is a server-generated unique identifier for the request
    that starts with `req_`."
    PRD 2.2: "The `error_id` is a unique, machine-readable string that identifies the
    specific error."
    PRD 2.2: "The `message` provides a human-readable explanation of what went wrong."
    PRD 2.1: "On every other endpoint, a missing or empty `X-User-ID` is refused with
    `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD 2.1: "Each endpoint in §4 lists the roles authorized to call it; a caller whose
    `X-User-Role` is not on that list is refused with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD 2.5: "Each entity has its own not-found code, all at HTTP 404:
    `ERR_POLICY_CYCLE_NOT_FOUND`, `ERR_TEAM_NOT_FOUND`, `ERR_EMPLOYEE_NOT_FOUND`,
    `ERR_CLASSIFICATION_NOT_FOUND`, `ERR_ATTENDANCE_WEEK_NOT_FOUND`,
    `ERR_COMPLIANCE_SIGNAL_NOT_FOUND`, `ERR_EXCEPTION_REQUEST_NOT_FOUND`,
    `ERR_RELOCATION_REQUEST_NOT_FOUND`, `ERR_NEIGHBORHOOD_NOT_FOUND`,
    `ERR_SEAT_ALLOCATION_NOT_FOUND`, `ERR_DESK_ASSIGNMENT_NOT_FOUND`,
    `ERR_ESCALATION_CASE_NOT_FOUND` and `ERR_RECALIBRATION_REVIEW_NOT_FOUND`."
    PRD 3.4: "At most one week may exist per employee and `iso_week` pair; a second attempt
    is `ERR_DUPLICATE_ATTENDANCE_WEEK` (409)."
    PRD 3.3: "A successful draft also advances the parent employee's `version` by one, which
    is precisely why the next writer's `expected_employee_version` will no longer match."
    PRD 2.8: "When another writer has already created a classification that legitimately
    supersedes the employee's current `APPROVED` class, the employee's `version` has advanced
    and the current writer's picture of the employee is stale; the create is then rejected
    with `ERR_STALE_EMPLOYEE_VERSION` (412)."

    Design: Corner/errors/every_status_class_returns_the_same_two_field_error_envelope
    """
    world = _a_cycle_team_employee_and_an_open_week("FY27-CRN56")
    employee_id = world["employee"]["id"]
    first_version = world["employee"]["version"]
    drafted = get_success_data(
        api_client.create_classification(
            classification_payload(employee_id, first_version), HRBP
        ),
        201,
    )
    assert drafted["state"] == "DRAFT"
    assert read_employee(employee_id)["version"] == first_version + 1, (
        "the draft advanced the employee, so the captured version is now stale"
    )

    unauthenticated = _assert_error_envelope(
        api_client.create_attendance_week(
            attendance_week_payload(employee_id, "2026-W38"), NO_IDENTITY_SYSTEM
        ),
        401,
        ApiErrorId.ERR_UNAUTHENTICATED.value,
    )
    unauthorized = _assert_error_envelope(
        api_client.create_policy_cycle(
            policy_cycle_payload(cycle_label="FY27-CRN57", **STANDARD_DIALS), SYSTEM
        ),
        403,
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )
    not_found = _assert_error_envelope(
        api_client.get_team(UNKNOWN_TEAM_ID, HRBP),
        404,
        ApiErrorId.ERR_TEAM_NOT_FOUND.value,
    )
    duplicate = _assert_error_envelope(
        api_client.create_attendance_week(
            attendance_week_payload(employee_id, "2026-W37"), SYSTEM
        ),
        409,
        ApiErrorId.ERR_DUPLICATE_ATTENDANCE_WEEK.value,
    )
    stale = _assert_error_envelope(
        api_client.create_classification(
            classification_payload(
                employee_id, first_version, requested_class="FULLY_REMOTE",
                justification_code="TALENT_RETENTION",
            ),
            HRBP,
        ),
        412,
        ApiErrorId.ERR_STALE_EMPLOYEE_VERSION.value,
    )
    malformed = _assert_error_envelope(
        api_client.create_team(
            team_payload(
                world["cycle"]["id"], team_code="T-SEVEN",
                expected_days_in_office_per_week=7,
                core_collaboration_days=["TUE"], headcount_planned=4,
                signal_corroboration_required=False,
            ),
            WPO,
        ),
        422,
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )

    refusals = [unauthenticated, unauthorized, not_found, duplicate, stale, malformed]
    assert [row["error_id"] for row in refusals] == [
        "ERR_UNAUTHENTICATED",
        "ERR_UNAUTHORIZED",
        "ERR_TEAM_NOT_FOUND",
        "ERR_DUPLICATE_ATTENDANCE_WEEK",
        "ERR_STALE_EMPLOYEE_VERSION",
        "ERR_INVALID_REQUEST",
    ]
    for refusal in refusals:
        assert set(refusal) == {"error_id", "message"}, (
            "no id, version or created_at may ride along inside an error"
        )


def test_08_three_refusals_move_no_version_and_no_counter_anywhere_in_the_cycle():
    """The zone version waits for a success, and the same guard value is accepted afterwards.

    PRD 3.8: "And the team's entitlement is enforced week by week: for every ISO week in the
    requested window, the sum of `allocated_seats` over that team's non-`RELEASED`
    allocations covering that week, plus the requested seats, must not exceed the team's
    `entitled_seats`; a breach in any single week is refused with
    `ERR_SEAT_ENTITLEMENT_EXCEEDED` (409)."
    PRD 3.8: "It also advances the parent neighborhood's `version` by one."
    PRD 2.8: "`POST /seat-allocations` must carry `expected_neighborhood_version`, equal to
    the current `version` of the `Neighborhood` named by `neighborhood_id`."
    PRD 3.4: "Signals may only be appended while the week is still editable — that is, while
    its `status` is `OPEN` or `AMENDED`; an append onto a `FINALIZED` or `LOCKED` week is
    refused with `ERR_WEEK_NOT_OPEN` (409)."
    PRD 3.2: "An `HRBusinessPartner` registers an employee against a `team_id`, supplying an
    `employee_number` of 1 to 24 characters that is globally unique (a collision is
    `ERR_DUPLICATE_EMPLOYEE_NUMBER`), a `work_email` that must contain an at-sign and is
    likewise globally unique (`ERR_DUPLICATE_WORK_EMAIL`), the IANA `home_timezone` recorded
    for policy communication and used in no calculation, the `tenure_start_date` on which
    employment began, and a `demographic_band` of `BAND_A`, `BAND_B`, `BAND_C` or `BAND_D`
    used solely by the equity monitoring of §3.9."
    PRD 2.4: "Whenever a field on a row changes, that row's `updated_at` is refreshed to the
    current logical instant and its `version` advances — this applies equally to a row the
    caller addressed directly and to a parent or sibling row a cascade touched."
    PRD 3.5: "`escalated_headcount` is the number of that team's employees holding a case
    whose `stage` is `COACHING`, `WRITTEN_WARNING`, `PERFORMANCE_PLAN` or `REFERRED`;
    `formal_action_count` is the number holding a case in the narrower formal-action band of
    `WRITTEN_WARNING`, `PERFORMANCE_PLAN` or `REFERRED`."

    Design: Corner/errors/a_refused_write_advances_no_version_and_no_rollup
    """
    world = _a_settled_breach_with_every_rollup_raised()
    zone_id = world["zone"]["id"]
    team_id = world["team"]["id"]
    employee_id = world["employee"]["id"]
    week_id = world["week"]["id"]
    guard_version = world["zone"]["version"]
    settled_employee = read_employee(employee_id)
    assert world["team"]["entitled_seats"] == 10, "twelve heads over three days"
    assert world["week"]["status"] == "FINALIZED"
    assert world["week"]["credited_days"] == 3
    assert world["week"]["shortfall_days"] == 2
    assert settled_employee["non_compliance_pressure"] == 4.00
    assert settled_employee["compliance_state"] == "BREACH"
    settled_version = settled_employee["version"]

    validate_error(
        api_client.create_seat_allocation(
            seat_allocation_payload(
                zone_id, team_id, guard_version, allocated_seats=11,
                window_start_week="2026-W37", window_end_week="2026-W40",
            ),
            WPO,
        ),
        ApiErrorId.ERR_SEAT_ENTITLEMENT_EXCEEDED.value,
        409,
    )
    assert read_neighborhood(zone_id)["version"] == guard_version, (
        "the version is a side effect of success, not of the attempt"
    )

    validate_error(
        api_client.append_signal(
            week_id,
            signal_payload("2026-09-11", minutes_present=480, dedupe_key="B-0911"),
            SYSTEM,
        ),
        ApiErrorId.ERR_WEEK_NOT_OPEN.value,
        409,
    )
    _, signal_meta = list_all(
        api_client.list_compliance_signals, WPO, {"attendance_week_id": week_id}
    )
    assert signal_meta["total_count"] == 3, "the settled week keeps exactly its evidence"

    validate_error(
        api_client.create_employee(
            employee_payload(
                team_id, MANAGER_USER_ID, HRBP_USER_ID,
                employee_number="E-1001", work_email="dup@corp.example",
                demographic_band="BAND_B",
            ),
            HRBP,
        ),
        ApiErrorId.ERR_DUPLICATE_EMPLOYEE_NUMBER.value,
        409,
    )
    _, employee_meta = list_all(api_client.list_employees, HRBP, {"team_id": team_id})
    assert employee_meta["total_count"] == 1, "the collision registered nobody"

    week = read_week(week_id)
    assert week["credited_days"] == 3
    assert week["shortfall_days"] == 2
    employee = read_employee(employee_id)
    assert employee["non_compliance_pressure"] == 4.00
    assert employee["version"] == settled_version, (
        "no refusal touched the employee row the settlement had left alone"
    )
    case = first_case_for(employee_id)
    assert case["stage"] == "WRITTEN_WARNING"
    team = read_team(team_id)
    assert team["escalated_headcount"] == 1
    assert team["formal_action_count"] == 1
    cycle = read_cycle(world["cycle"]["id"])
    assert cycle["formal_action_total"] == 1
    assert cycle["aggregate_compliance_rate"] == 0.00

    accepted = get_success_data(
        api_client.create_seat_allocation(
            seat_allocation_payload(
                zone_id, team_id, guard_version, allocated_seats=10,
                window_start_week="2026-W37", window_end_week="2026-W40",
            ),
            WPO,
        ),
        201,
    )
    assert accepted["status"] == "RESERVED"
    assert accepted["allocated_seats"] == 10, "exactly on the entitlement is permitted"
    assert read_neighborhood(zone_id)["version"] == guard_version + 1, (
        "only now, on the success, does the zone version move"
    )
