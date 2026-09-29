"""Accident reporting, the investigation cycle and the settlement waterfall.

Two money variants are computed over the same accident: the provisional reserve held
at filing and the itemised settlement produced at closure. The tests below exercise
that pair, the remediation cycle the hold survives, the exactness of the coverage
ledger under file-then-withdraw, the one-live-report-per-flight rule and the
segregation that keeps the approving airspace authority away from the closure.
"""

from test_helpers import (
    AIRSPACE_AUTHORITY_ID,
    COMPLIANCE_OFFICER,
    HTTP_STATUS_CODES,
    INVESTIGATION_OFFICER,
    INVESTIGATION_OFFICER_ID,
    ApiErrorId,
    CoverageStatus,
    FlightStatus,
    InjuryLevel,
    InvestigationStatus,
    OperationCategory,
    OperatorCategory,
    PreflightResult,
    ReportStatus,
    Role,
    SystemCancellationReason,
    ZoneClassCode,
    assert_coverage_ledger_conservation,
    get_success_data,
    make_headers,
    make_pilot_headers,
    set_clock,
    validate_error,
    validate_paginated,
)
from test_helpers.factories import (
    accident_report_payload,
    close_report_payload,
    completion_payload,
    damage_line,
    remediation_payload,
    withdraw_report_payload,
)
from test_helpers.fixtures import (
    clear_flight_for_launch,
    create_active_policy,
    create_approved_authorization,
    create_certified_pilot,
    create_controlled_zone,
    create_filed_report,
    create_planned_flight,
    create_registered_aircraft,
    create_zone,
    read_policy,
)

SETUP_DAY = "2026-08-05T00:00:00Z"
FLIGHT_START = "2026-08-10T09:00:00Z"
FLIGHT_END = "2026-08-10T10:00:00Z"
FILING_DAY = "2026-08-11T00:00:00Z"
OCCURRED_AT = "2026-08-10T09:45:00Z"
LATER_FLIGHT_START = "2026-08-20T09:00:00Z"
LATER_FLIGHT_END = "2026-08-20T10:00:00Z"


def _flown_commercial_incident(
    api, coverage_limit_cents, deductible_cents, with_later_flight=False
):
    """A commercial operator whose covered mission has landed with an incident aboard.

    The logical clock only ever walks forward: it is parked on the day after the
    flight so that a report can be filed against an instant inside the flown window.
    A second, still-planned mission on the same cover is optional, because only the
    coverage-erosion scenarios need a victim ten days out.
    """
    set_clock(api, SETUP_DAY, headers=COMPLIANCE_OFFICER)
    pilot = create_certified_pilot(
        api, OperatorCategory.COMMERCIAL.value, scheduled_at=SETUP_DAY
    )
    aircraft = create_registered_aircraft(
        api, pilot["id"], takeoff_weight_g=249, max_altitude_ft=1500
    )
    zone = create_zone(
        api,
        class_code=ZoneClassCode.G.value,
        class_ceiling_ft=400,
        requires_authorization=False,
        max_concurrent_authorizations=3,
    )
    policy = create_active_policy(
        api,
        pilot["id"],
        coverage_limit_cents=coverage_limit_cents,
        deductible_cents=deductible_cents,
    )
    pilot_headers = make_pilot_headers(pilot["id"])
    flight = create_planned_flight(
        api,
        pilot["id"],
        aircraft["id"],
        zone["id"],
        FLIGHT_START,
        FLIGHT_END,
        operation_category=OperationCategory.COMMERCIAL.value,
        planned_max_altitude_ft=380,
    )
    later_flight = None
    if with_later_flight:
        later_flight = create_planned_flight(
            api,
            pilot["id"],
            aircraft["id"],
            zone["id"],
            LATER_FLIGHT_START,
            LATER_FLIGHT_END,
            operation_category=OperationCategory.COMMERCIAL.value,
            planned_max_altitude_ft=390,
        )
    check = clear_flight_for_launch(api, flight)
    assert check["result"] == PreflightResult.PASSED.value, (
        f"setup expected a PASSED pre-flight sweep, got {check['result']} "
        f"with findings {check['blocking_findings']}"
    )
    set_clock(api, FLIGHT_START, headers=COMPLIANCE_OFFICER)
    get_success_data(api.launch_flight(flight["id"], headers=pilot_headers))
    flown = get_success_data(
        api.complete_flight(
            flight["id"],
            completion_payload(
                FLIGHT_END,
                max_altitude_reached_ft=370,
                incident_occurred=True,
                incident_summary="Rotor arm cracked on a hard landing in gusting wind.",
            ),
            headers=pilot_headers,
        )
    )
    set_clock(api, FILING_DAY, headers=COMPLIANCE_OFFICER)
    return {
        "pilot": pilot,
        "aircraft": aircraft,
        "zone": zone,
        "policy": policy,
        "flight": flown,
        "later_flight": later_flight,
        "pilot_headers": pilot_headers,
    }


def test_filing_holds_the_provisional_reserve_computed_from_the_reported_damage(api):
    """PRD §3.8: "Select the injury reserve from the `injury_level` — 0 cents for `NONE`, 250000 cents for `MINOR`, 1500000 cents for `SERIOUS`."
    PRD §3.8: "Multiply the `reported_property_damage_cents` by 1.25 and round half-up to whole cents, then add the injury reserve; that sum is the raw reserve."
    PRD §3.8: "The report is created in `FILED` with `remediation_round` 0, and with `remediation_findings`, `damage_line_items`, `settlement_cents`, `probable_cause` and `closed_by_user_id` all null."
    PRD §3.8: "The policy's ledger is then recomputed, which raises `open_reserved_cents_total` and lowers `remaining_coverage_cents` by the reserve, and may push the policy into `INSUFFICIENT` with the flight cancellations that entails (§3.6, §2.8)."

    Design: Difficulty/dual_variant_calc/accident_provisional_reserve_versus_final_settlement
    """
    scene = _flown_commercial_incident(api, 5000000, 50000)
    report = create_filed_report(
        api,
        scene["flight"],
        OCCURRED_AT,
        injury_level=InjuryLevel.MINOR.value,
        reported_property_damage_cents=1237035,
    )

    assert report["reserved_cents"] == 1796294, (
        "the provisional hold on 1237035 cents of reported damage at MINOR injury is "
        f"1546294 plus 250000, expected 1796294, got {report['reserved_cents']}"
    )
    assert isinstance(report["reserved_cents"], int), (
        f"reserved_cents must be a whole-cent integer, got {report['reserved_cents']!r}"
    )
    assert report["status"] == ReportStatus.FILED.value, (
        f"a new report starts in FILED, got {report['status']}"
    )
    assert report["remediation_round"] == 0, (
        f"a new report starts with remediation_round 0, got {report['remediation_round']}"
    )
    assert report["settlement_cents"] is None, (
        "filing is a hold and not a payment, so settlement_cents must be null, got "
        f"{report['settlement_cents']!r}"
    )

    policy = read_policy(api, scene["policy"]["id"])
    assert policy["open_reserved_cents_total"] == 1796294, (
        "the open reserve total must carry the whole hold, expected 1796294, got "
        f"{policy['open_reserved_cents_total']}"
    )
    assert policy["remaining_coverage_cents"] == 3203706, (
        "remaining cover falls by exactly the reserve, expected 3203706, got "
        f"{policy['remaining_coverage_cents']}"
    )
    assert policy["settled_cents_total"] == 0, (
        f"no payment has been made yet, expected 0, got {policy['settled_cents_total']}"
    )
    assert policy["coverage_status"] == CoverageStatus.ACTIVE.value, (
        "3203706 cents of remaining cover is far above the commercial minimum, so the "
        f"policy stays ACTIVE, got {policy['coverage_status']}"
    )
    assert_coverage_ledger_conservation(api, policy["id"], COMPLIANCE_OFFICER)


def test_closing_replaces_the_reserve_with_the_itemised_settlement(api):
    """PRD §3.8: "First, apply coinsurance **per line**: for each entry of `damage_line_items` in the order supplied, multiply its `amount_cents` by 0.85 and round half-up to whole cents."
    PRD §3.8: "Closure then writes `settlement_cents`, zeroes `reserved_cents`, and sets `closed_by_user_id` to the closing operator's `X-User-ID`."
    PRD §3.8: "Because the two variants work off different inputs, the same accident yields a different figure at close than it reserved at filing: the reserve inflates a single reported figure by 25 percent and adds a flat injury reserve, while the settlement itemises the damage at 85 percent with per-line rounding, deducts the deductible, adds a tier surcharge and caps against unused limit."

    Design: Difficulty/dual_variant_calc/accident_provisional_reserve_versus_final_settlement
    """
    scene = _flown_commercial_incident(api, 5000000, 50000)
    report = create_filed_report(
        api,
        scene["flight"],
        OCCURRED_AT,
        injury_level=InjuryLevel.MINOR.value,
        reported_property_damage_cents=1237035,
    )
    provisional = report["reserved_cents"]
    get_success_data(
        api.open_investigation(report["id"], headers=INVESTIGATION_OFFICER)
    )
    closed = get_success_data(
        api.close_accident_report(
            report["id"],
            close_report_payload(
                [
                    damage_line("Airframe", 412345),
                    damage_line("Payload", 412345),
                    damage_line("Third-party property", 412345),
                ],
                probable_cause="Late flare on approach in gusting crosswind.",
            ),
            headers=INVESTIGATION_OFFICER,
        )
    )

    assert closed["settlement_cents"] == 1021509, (
        "three lines of 412345 cents cover to 350493 each, summing to 1051479, less the "
        "50000 deductible is 1001479, plus a 20030 tier surcharge, expected 1021509, got "
        f"{closed['settlement_cents']}"
    )
    assert closed["status"] == ReportStatus.CLOSED.value, (
        f"closure is terminal in CLOSED, got {closed['status']}"
    )
    assert closed["reserved_cents"] == 0, (
        f"closure zeroes the hold, expected 0, got {closed['reserved_cents']}"
    )
    assert closed["closed_by_user_id"] == INVESTIGATION_OFFICER_ID, (
        "closed_by_user_id records the closing operator, expected "
        f"{INVESTIGATION_OFFICER_ID}, got {closed['closed_by_user_id']!r}"
    )
    assert provisional != closed["settlement_cents"], (
        "the two variants read different inputs, so the same accident must not reserve "
        f"and settle the same cent figure; both were {provisional}"
    )

    policy = read_policy(api, scene["policy"]["id"])
    assert policy["settled_cents_total"] == 1021509, (
        f"the settlement moves into the settled bucket, got {policy['settled_cents_total']}"
    )
    assert policy["open_reserved_cents_total"] == 0, (
        f"the hold is released on closure, got {policy['open_reserved_cents_total']}"
    )
    assert policy["remaining_coverage_cents"] == 3978491, (
        "remaining cover is the limit less the settlement, expected 3978491, got "
        f"{policy['remaining_coverage_cents']}"
    )
    assert_coverage_ledger_conservation(api, policy["id"], COMPLIANCE_OFFICER)


def _half_cent_damage_lines():
    """Two covered lines that each land on an exact half cent at the coinsurance rate."""
    return [
        damage_line("Airframe and battery", 1100010),
        damage_line("Third-party vehicle", 1265630),
    ]


def _investigating_report_on_an_eight_million_policy(api):
    scene = _flown_commercial_incident(api, 8000000, 50000)
    report = create_filed_report(
        api,
        scene["flight"],
        OCCURRED_AT,
        injury_level=InjuryLevel.NONE.value,
        reported_property_damage_cents=2365640,
    )
    opened = get_success_data(
        api.open_investigation(report["id"], headers=INVESTIGATION_OFFICER)
    )
    assert opened["status"] == ReportStatus.INVESTIGATING.value, (
        f"setup expected an INVESTIGATING report, got {opened['status']}"
    )
    return scene, opened


def test_settlement_rounds_each_damage_line_before_summing(api):
    """PRD §3.8: "First, apply coinsurance **per line**: for each entry of `damage_line_items` in the order supplied, multiply its `amount_cents` by 0.85 and round half-up to whole cents."
    PRD §3.8: "Then sum those rounded line figures to get the subtotal."
    PRD §3.8: "Rounding each line before summing is required; summing the raw amounts and rounding once at the end is wrong and produces a different cent figure."

    Design: Difficulty/combinatorial_formula/accident_final_settlement_per_line_rounding_then_pre_surcharge_tier
    """
    scene, report = _investigating_report_on_an_eight_million_policy(api)

    closed = get_success_data(
        api.close_accident_report(
            report["id"],
            close_report_payload(
                _half_cent_damage_lines(),
                probable_cause="Cell puncture from a prior hard landing, undetected at pre-flight.",
            ),
            headers=INVESTIGATION_OFFICER,
        )
    )

    assert closed["settlement_cents"] == 2000011, (
        "the covered lines are 935009 and 1075786, a subtotal of 2010795, less the 50000 "
        "deductible is 1960795, plus a 39216 surcharge, expected 2000011, got "
        f"{closed['settlement_cents']}"
    )
    assert closed["settlement_cents"] != 2000010, (
        "summing the raw amounts and rounding once yields a subtotal of 2010794 and a "
        "settlement of 2000010; the per-line rounding must happen before the sum"
    )
    assert isinstance(closed["settlement_cents"], int), (
        f"settlement_cents must be a whole-cent integer, got {closed['settlement_cents']!r}"
    )
    assert_coverage_ledger_conservation(api, scene["policy"]["id"], COMPLIANCE_OFFICER)


def test_surcharge_tier_is_selected_from_the_pre_surcharge_net(api):
    """PRD §3.8: "Second, subtract the policy's `deductible_cents` from the subtotal and floor the result at 0 — this is the net figure."
    PRD §3.8: "Third, select the surcharge tier **from the net figure**, before any surcharge is added, and never from the post-surcharge total even though the surcharge becomes part of it: a net at or below 500000 cents attracts no surcharge; a net above 500000 cents and at or below 2000000 cents attracts the net multiplied by 0.02, rounded half-up; a net above 2000000 cents attracts the net multiplied by 0.05, rounded half-up."
    PRD §3.8: "Fourth, add the surcharge to the net to get the uncapped total."

    Design: Difficulty/combinatorial_formula/accident_final_settlement_per_line_rounding_then_pre_surcharge_tier
    """
    scene, report = _investigating_report_on_an_eight_million_policy(api)

    closed = get_success_data(
        api.close_accident_report(
            report["id"],
            close_report_payload(
                _half_cent_damage_lines(),
                probable_cause="Cell puncture from a prior hard landing, undetected at pre-flight.",
            ),
            headers=INVESTIGATION_OFFICER,
        )
    )

    assert closed["settlement_cents"] == 2000011, (
        "the net of 1960795 sits at or below 2000000, so the surcharge is 2 percent of "
        f"the net, expected 2000011, got {closed['settlement_cents']}"
    )
    assert closed["settlement_cents"] != 2058835, (
        "re-deriving the tier from the finished total of 2000011 pushes it past 2000000 "
        "and applies 5 percent, yielding 2058835; the tier is fixed by the net alone"
    )

    policy = read_policy(api, scene["policy"]["id"])
    assert policy["settled_cents_total"] == 2000011, (
        f"the settled bucket takes the whole payment, got {policy['settled_cents_total']}"
    )
    assert policy["open_reserved_cents_total"] == 0, (
        f"the provisional hold is gone after closure, got {policy['open_reserved_cents_total']}"
    )
    assert policy["remaining_coverage_cents"] == 5999989, (
        "remaining cover is 8000000 less the settlement, expected 5999989, got "
        f"{policy['remaining_coverage_cents']}"
    )
    assert_coverage_ledger_conservation(api, policy["id"], COMPLIANCE_OFFICER)


def _bird_strike_damage_lines():
    return [damage_line("Rotor arms", 400000), damage_line("Gimbal", 400000)]


def test_remediation_round_advances_and_the_reserve_survives_the_cycle(api):
    """PRD §3.8: "From `INVESTIGATING` the officer may send the report back for operator remediation, supplying `remediation_findings`: the report moves to `REMEDIATION_REQUIRED` and `remediation_round` is incremented."
    PRD §3.8: "The officer returns a `REMEDIATION_REQUIRED` report to `INVESTIGATING` once the operator has responded, closing the `INVESTIGATING → REMEDIATION_REQUIRED → INVESTIGATING` cycle."
    PRD §3.8: "The reserve is held untouched throughout the loop, which is why a policy driven into `INSUFFICIENT` by a filing stays there for the whole remediation cycle no matter how many rounds it takes."

    Design: Difficulty/non_linear_state_machine/accident_investigation_remediation_cycle_with_parallel_flight_dimension
    """
    scene = _flown_commercial_incident(api, 5000000, 50000)
    report = create_filed_report(
        api,
        scene["flight"],
        OCCURRED_AT,
        injury_level=InjuryLevel.NONE.value,
        reported_property_damage_cents=800000,
    )
    assert report["reserved_cents"] == 1000000, (
        "800000 cents inflated by a quarter with no injury reserve is 1000000, got "
        f"{report['reserved_cents']}"
    )
    get_success_data(
        api.open_investigation(report["id"], headers=INVESTIGATION_OFFICER)
    )

    sent_back = get_success_data(
        api.require_remediation(
            report["id"],
            remediation_payload(
                remediation_findings=(
                    "Wildlife survey for the launch site is missing; supply it before closure."
                )
            ),
            headers=INVESTIGATION_OFFICER,
        )
    )
    assert sent_back["status"] == ReportStatus.REMEDIATION_REQUIRED.value, (
        f"the report must sit in REMEDIATION_REQUIRED, got {sent_back['status']}"
    )
    assert sent_back["remediation_round"] == 1, (
        f"the first send-back increments the round to 1, got {sent_back['remediation_round']}"
    )
    assert sent_back["reserved_cents"] == 1000000, (
        "the hold is untouched by the send-back, expected 1000000, got "
        f"{sent_back['reserved_cents']}"
    )

    mid_loop_policy = read_policy(api, scene["policy"]["id"])
    assert mid_loop_policy["open_reserved_cents_total"] == 1000000, (
        "the policy still carries the whole hold during the loop, got "
        f"{mid_loop_policy['open_reserved_cents_total']}"
    )
    assert mid_loop_policy["remaining_coverage_cents"] == 4000000, (
        f"remaining cover stays at 4000000 during the loop, got "
        f"{mid_loop_policy['remaining_coverage_cents']}"
    )

    resumed = get_success_data(
        api.resume_investigation(report["id"], headers=INVESTIGATION_OFFICER)
    )
    assert resumed["status"] == ReportStatus.INVESTIGATING.value, (
        f"the cycle returns the report to INVESTIGATING, got {resumed['status']}"
    )
    assert resumed["remediation_round"] == 1, (
        "returning to INVESTIGATING does not advance the round, expected 1, got "
        f"{resumed['remediation_round']}"
    )
    assert resumed["reserved_cents"] == 1000000, (
        f"the hold survives the whole cycle, expected 1000000, got {resumed['reserved_cents']}"
    )


def test_flight_investigation_dimension_moves_independently_of_its_operational_status(api):
    """PRD §3.8: "The flight's `investigation_status` is a genuinely parallel dimension: filing moves it from `NONE` to `OPEN` and closure or withdrawal moves it from `OPEN` to `CLOSED`, and **neither ever touches the flight's operational `status`**."
    PRD §3.8: "A `COMPLETED` flight can be `OPEN`, and an `IN_PROGRESS` flight can be `OPEN` — the aircraft may still be in the air while the paperwork is running."
    PRD §3.8: "The flight's `investigation_status` moves from `OPEN` to `CLOSED`, and the pilot's `risk_score` is recomputed — the open-accident term drops out, so closing a report normally lowers the score."

    Design: Difficulty/non_linear_state_machine/accident_investigation_remediation_cycle_with_parallel_flight_dimension
    """
    scene = _flown_commercial_incident(api, 5000000, 50000)
    flight_id = scene["flight"]["id"]
    assert scene["flight"]["investigation_status"] == InvestigationStatus.NONE.value, (
        "a flown mission with no report has nothing under investigation, got "
        f"{scene['flight']['investigation_status']}"
    )

    report = create_filed_report(
        api,
        scene["flight"],
        OCCURRED_AT,
        injury_level=InjuryLevel.NONE.value,
        reported_property_damage_cents=800000,
    )
    get_success_data(
        api.open_investigation(report["id"], headers=INVESTIGATION_OFFICER)
    )
    get_success_data(
        api.require_remediation(
            report["id"],
            remediation_payload(
                remediation_findings=(
                    "Wildlife survey for the launch site is missing; supply it before closure."
                )
            ),
            headers=INVESTIGATION_OFFICER,
        )
    )

    mid_loop = get_success_data(
        api.get_flight(flight_id, headers=scene["pilot_headers"])
    )
    assert mid_loop["status"] == FlightStatus.COMPLETED.value, (
        "no accident transition moves the operational dimension, expected COMPLETED, got "
        f"{mid_loop['status']}"
    )
    assert mid_loop["investigation_status"] == InvestigationStatus.OPEN.value, (
        "the investigation dimension stays OPEN for the whole remediation cycle, got "
        f"{mid_loop['investigation_status']}"
    )

    get_success_data(
        api.resume_investigation(report["id"], headers=INVESTIGATION_OFFICER)
    )
    closed = get_success_data(
        api.close_accident_report(
            report["id"],
            close_report_payload(
                _bird_strike_damage_lines(),
                probable_cause="Bird strike during a permitted operation; no operator error.",
            ),
            headers=INVESTIGATION_OFFICER,
        )
    )
    assert closed["settlement_cents"] == 642600, (
        "two lines of 400000 cover to 340000 each, a subtotal of 680000, less the 50000 "
        f"deductible is 630000, plus a 12600 surcharge, expected 642600, got "
        f"{closed['settlement_cents']}"
    )

    after = get_success_data(api.get_flight(flight_id, headers=scene["pilot_headers"]))
    assert after["investigation_status"] == InvestigationStatus.CLOSED.value, (
        f"closure closes the investigation dimension, got {after['investigation_status']}"
    )
    assert after["status"] == FlightStatus.COMPLETED.value, (
        f"the operational dimension is still COMPLETED, got {after['status']}"
    )

    policy = read_policy(api, scene["policy"]["id"])
    assert policy["remaining_coverage_cents"] == 4357400, (
        "remaining cover is 5000000 less the settlement, expected 4357400, got "
        f"{policy['remaining_coverage_cents']}"
    )
    assert policy["settled_cents_total"] == 642600, (
        f"the settled bucket takes 642600, got {policy['settled_cents_total']}"
    )
    assert_coverage_ledger_conservation(api, policy["id"], COMPLIANCE_OFFICER)


def test_withdrawing_a_report_restores_the_policy_ledger_exactly(api):
    """PRD §3.8: "Withdrawal is the compensating action for filing and is admissible from `FILED` or `INVESTIGATING`, optionally recording a `probable_cause`."
    PRD §3.8: "It moves the report to `WITHDRAWN`, zeroes `reserved_cents`, and leaves `settlement_cents` null — no payment is ever made."
    PRD §2.10: "The three terms add up to the limit with zero drift: filing a report that reserves an amount and then withdrawing that report returns `remaining_coverage_cents` to precisely its pre-filing value and leaves `settled_cents_total` untouched."
    PRD §3.6: "When a closure or a withdrawal restores the recomputed `remaining_coverage_cents` to 1000000 cents or above, an `INSUFFICIENT` policy moves back to `ACTIVE` — the `ACTIVE → INSUFFICIENT → ACTIVE` cycle — but the flights that were cancelled while cover was short are not restored."

    Design: Difficulty/compensating_invariant/coverage_ledger_conservation_under_file_then_withdraw
    """
    scene = _flown_commercial_incident(api, 2000000, 50000, with_later_flight=True)
    policy_id = scene["policy"]["id"]

    report = create_filed_report(
        api,
        scene["flight"],
        OCCURRED_AT,
        injury_level=InjuryLevel.MINOR.value,
        reported_property_damage_cents=800000,
    )
    assert report["reserved_cents"] == 1250000, (
        "800000 cents inflated by a quarter is 1000000, plus the MINOR reserve 250000, "
        f"expected 1250000, got {report['reserved_cents']}"
    )

    held = read_policy(api, policy_id)
    assert held["remaining_coverage_cents"] == 750000, (
        f"the hold leaves 750000 cents of cover, got {held['remaining_coverage_cents']}"
    )
    assert held["open_reserved_cents_total"] == 1250000, (
        f"the whole hold is open, got {held['open_reserved_cents_total']}"
    )
    assert held["settled_cents_total"] == 0, (
        f"nothing has been paid, got {held['settled_cents_total']}"
    )
    assert held["coverage_status"] == CoverageStatus.INSUFFICIENT.value, (
        "750000 cents of remaining cover is below the commercial minimum, so the policy "
        f"is INSUFFICIENT, got {held['coverage_status']}"
    )
    assert_coverage_ledger_conservation(api, policy_id, COMPLIANCE_OFFICER)

    withdrawn = get_success_data(
        api.withdraw_accident_report(
            report["id"],
            withdraw_report_payload(
                probable_cause=(
                    "Filed against the wrong flight; the damage belongs to a ground "
                    "handling incident."
                )
            ),
            headers=INVESTIGATION_OFFICER,
        )
    )
    assert withdrawn["status"] == ReportStatus.WITHDRAWN.value, (
        f"withdrawal lands in WITHDRAWN, got {withdrawn['status']}"
    )
    assert withdrawn["reserved_cents"] == 0, (
        f"withdrawal zeroes the hold, expected 0, got {withdrawn['reserved_cents']}"
    )
    assert withdrawn["settlement_cents"] is None, (
        "no payment is ever made on a withdrawal, so settlement_cents stays null, got "
        f"{withdrawn['settlement_cents']!r}"
    )

    released = read_policy(api, policy_id)
    assert released["remaining_coverage_cents"] == 2000000, (
        "the release is exact, so remaining cover returns to its pre-filing 2000000, got "
        f"{released['remaining_coverage_cents']}"
    )
    assert released["open_reserved_cents_total"] == 0, (
        f"no hold survives the withdrawal, got {released['open_reserved_cents_total']}"
    )
    assert released["settled_cents_total"] == 0, (
        "nothing may be shifted into the settled bucket by a withdrawal, got "
        f"{released['settled_cents_total']}"
    )
    assert released["coverage_status"] == CoverageStatus.ACTIVE.value, (
        "the ledger is whole again, so the policy climbs back to ACTIVE, got "
        f"{released['coverage_status']}"
    )
    assert_coverage_ledger_conservation(api, policy_id, COMPLIANCE_OFFICER)


def test_a_cancelled_flight_is_not_resurrected_by_the_withdrawal(api):
    """PRD §3.8: "Flights cancelled while cover was short are not resurrected."
    PRD §2.8: "Cascades are one-way. Reinstating a suspended pilot does not return their grounded airframes to service — each airframe must be individually returned."
    PRD §3.8: "A report's `status` moves through `FILED`, `INVESTIGATING`, `REMEDIATION_REQUIRED`, `CLOSED` and `WITHDRAWN`, with `CLOSED` and `WITHDRAWN` terminal."
    PRD §2.11: "**Declared source state**, on every state-changing endpoint: the addressed resource sits in a state from which the requested transition is declared, with the code naming the entity whose state blocks it — `ERR_PILOT_INVALID_STATE`, `ERR_TEST_ALREADY_GRADED`, `ERR_MODULE_INVALID_STATE`, `ERR_AIRCRAFT_INVALID_STATE`, `ERR_AUTHORIZATION_INVALID_STATE`, `ERR_WAIVER_INVALID_STATE`, `ERR_FLIGHT_INVALID_STATE`, `ERR_REPORT_INVALID_STATE`, `ERR_POLICY_INVALID_STATE` or `ERR_TFR_INVALID_STATE`, each HTTP 409."

    Design: Difficulty/compensating_invariant/coverage_ledger_conservation_under_file_then_withdraw
    """
    scene = _flown_commercial_incident(api, 2000000, 50000, with_later_flight=True)
    policy_id = scene["policy"]["id"]
    later_id = scene["later_flight"]["id"]

    report = create_filed_report(
        api,
        scene["flight"],
        OCCURRED_AT,
        injury_level=InjuryLevel.MINOR.value,
        reported_property_damage_cents=800000,
    )
    cancelled = get_success_data(
        api.get_flight(later_id, headers=scene["pilot_headers"])
    )
    assert cancelled["status"] == FlightStatus.CANCELLED.value, (
        "the still-planned commercial mission is cancelled when the reserve leaves the "
        f"policy under-covered, got {cancelled['status']}"
    )
    assert cancelled["cancellation_reason"] == (
        SystemCancellationReason.COVERAGE_INSUFFICIENT.value
    ), (
        "the cancellation is recorded against short cover, got "
        f"{cancelled['cancellation_reason']!r}"
    )

    get_success_data(
        api.withdraw_accident_report(
            report["id"],
            withdraw_report_payload(
                probable_cause="Filed against the wrong flight; no damage substantiated."
            ),
            headers=INVESTIGATION_OFFICER,
        )
    )

    still_cancelled = get_success_data(
        api.get_flight(later_id, headers=scene["pilot_headers"])
    )
    assert still_cancelled["status"] == FlightStatus.CANCELLED.value, (
        "money is conserved but a cancelled mission is never resurrected, got "
        f"{still_cancelled['status']}"
    )
    assert still_cancelled["cancellation_reason"] == (
        SystemCancellationReason.COVERAGE_INSUFFICIENT.value
    ), (
        "the recorded reason survives the withdrawal, got "
        f"{still_cancelled['cancellation_reason']!r}"
    )

    flown = get_success_data(
        api.get_flight(scene["flight"]["id"], headers=scene["pilot_headers"])
    )
    assert flown["investigation_status"] == InvestigationStatus.CLOSED.value, (
        "withdrawal closes the investigation dimension of the flown mission, got "
        f"{flown['investigation_status']}"
    )
    assert flown["status"] == FlightStatus.COMPLETED.value, (
        f"the operational dimension is untouched, got {flown['status']}"
    )

    second = api.withdraw_accident_report(
        report["id"],
        withdraw_report_payload(probable_cause="Second attempt at the same withdrawal."),
        headers=INVESTIGATION_OFFICER,
    )
    validate_error(
        second,
        ApiErrorId.REPORT_INVALID_STATE.value,
        HTTP_STATUS_CODES[ApiErrorId.REPORT_INVALID_STATE.value],
    )
    unchanged = read_policy(api, policy_id)
    assert unchanged["remaining_coverage_cents"] == 2000000, (
        "the rejected second withdrawal must not credit the policy twice, expected "
        f"2000000, got {unchanged['remaining_coverage_cents']}"
    )
    assert_coverage_ledger_conservation(api, policy_id, COMPLIANCE_OFFICER)


RECREATIONAL_LAUNCH = "2026-08-01T09:00:00Z"
RECREATIONAL_PLANNED_END = "2026-08-01T10:00:00Z"
RECREATIONAL_TOUCHDOWN = "2026-08-01T09:55:00Z"
RECREATIONAL_OCCURRED_AT = "2026-08-01T09:30:00Z"


def _flown_uninsured_hobby_flight(api):
    """A recreational sortie flown to completion with an incident and no cover at all.

    The flight is planned while the clock still stands at the service's startup
    instant, so the whole timeline runs forward through a single morning.
    """
    pilot = create_certified_pilot(api, OperatorCategory.RECREATIONAL.value)
    aircraft = create_registered_aircraft(
        api, pilot["id"], takeoff_weight_g=249, max_altitude_ft=900
    )
    zone = create_zone(
        api,
        class_code=ZoneClassCode.G.value,
        class_ceiling_ft=1200,
        requires_authorization=False,
        max_concurrent_authorizations=3,
    )
    pilot_headers = make_pilot_headers(pilot["id"])
    flight = create_planned_flight(
        api,
        pilot["id"],
        aircraft["id"],
        zone["id"],
        RECREATIONAL_LAUNCH,
        RECREATIONAL_PLANNED_END,
        operation_category=OperationCategory.RECREATIONAL.value,
        planned_max_altitude_ft=350,
    )
    set_clock(api, RECREATIONAL_LAUNCH, headers=COMPLIANCE_OFFICER)
    check = clear_flight_for_launch(api, flight)
    assert check["result"] == PreflightResult.PASSED.value, (
        f"setup expected a PASSED pre-flight sweep, got {check['result']} "
        f"with findings {check['blocking_findings']}"
    )
    get_success_data(api.launch_flight(flight["id"], headers=pilot_headers))
    set_clock(api, RECREATIONAL_TOUCHDOWN, headers=COMPLIANCE_OFFICER)
    flown = get_success_data(
        api.complete_flight(
            flight["id"],
            completion_payload(
                RECREATIONAL_TOUCHDOWN,
                max_altitude_reached_ft=340,
                incident_occurred=True,
                incident_summary="Propeller strike against a fence post on recovery.",
            ),
            headers=pilot_headers,
        )
    )
    return {"pilot": pilot, "flight": flown, "pilot_headers": pilot_headers}


def test_a_second_filing_against_a_flight_with_a_live_report_is_refused(api):
    """PRD §3.8: "Filing is admissible only when the flight's operational `status` is `IN_PROGRESS`, `COMPLETED` or `CANCELLED` and its `investigation_status` is `NONE`; a flight still in `PLANNED` or `PREFLIGHT_CLEARED` has nothing to investigate, and at most one non-withdrawn report may exist per flight — a second is refused with `ERR_ACCIDENT_REPORT_DUPLICATE`."
    PRD §2.11: "**One live report per flight**, on `POST /drone-ops/accident-reports` only: no report already exists against that `flight_id` in `FILED`, `INVESTIGATING`, `REMEDIATION_REQUIRED` or `CLOSED` — otherwise `ERR_ACCIDENT_REPORT_DUPLICATE` (409). Only a `WITHDRAWN` report leaves the flight free for a new filing."
    PRD §3.8: "When `policy_id` is null there is nothing to hold against and `reserved_cents` is 0."

    Design: Corner/errors/duplicate_accident_filing_is_triggerable_until_the_prior_report_is_withdrawn
    """
    scene = _flown_uninsured_hobby_flight(api)
    flight = scene["flight"]

    first = create_filed_report(
        api,
        flight,
        RECREATIONAL_OCCURRED_AT,
        injury_level=InjuryLevel.NONE.value,
        reported_property_damage_cents=40000,
    )
    assert first["status"] == ReportStatus.FILED.value, (
        f"a new report opens in FILED, got {first['status']}"
    )
    assert first["policy_id"] is None, (
        "a hobby flight has no covering policy to copy, so policy_id is null, got "
        f"{first['policy_id']!r}"
    )
    assert first["reserved_cents"] == 0, (
        f"there is nothing to hold against, expected a reserve of 0, got {first['reserved_cents']}"
    )

    duplicate = api.create_accident_report(
        accident_report_payload(
            flight["id"],
            RECREATIONAL_OCCURRED_AT,
            injury_level=InjuryLevel.MINOR.value,
            reported_property_damage_cents=90000,
        ),
        headers=scene["pilot_headers"],
    )
    validate_error(
        duplicate,
        ApiErrorId.ACCIDENT_REPORT_DUPLICATE.value,
        HTTP_STATUS_CODES[ApiErrorId.ACCIDENT_REPORT_DUPLICATE.value],
    )

    survivor = get_success_data(
        api.get_accident_report(first["id"], headers=INVESTIGATION_OFFICER)
    )
    assert survivor["status"] == ReportStatus.FILED.value, (
        f"the refused duplicate leaves the live report untouched, got {survivor['status']}"
    )
    assert survivor["reported_property_damage_cents"] == 40000, (
        "the refused duplicate must not overwrite the live report's figures, expected "
        f"40000, got {survivor['reported_property_damage_cents']}"
    )
    records, meta = validate_paginated(
        api.list_accident_reports(
            params={"flight_id": flight["id"]}, headers=INVESTIGATION_OFFICER
        )
    )
    assert meta["total_count"] == 1, (
        f"the rejected filing wrote no second row, expected 1 report, got {meta['total_count']}"
    )
    assert [record["id"] for record in records] == [first["id"]], (
        f"only the first report exists against the flight, got {[r['id'] for r in records]}"
    )


def test_withdrawing_leaves_the_report_row_in_place(api):
    """PRD §3.8: "It moves the report to `WITHDRAWN`, zeroes `reserved_cents`, and leaves `settlement_cents` null — no payment is ever made."
    PRD §3.8: "The flight's `investigation_status` is a genuinely parallel dimension: filing moves it from `NONE` to `OPEN` and closure or withdrawal moves it from `OPEN` to `CLOSED`, and **neither ever touches the flight's operational `status`**."
    PRD §2.2: "Every list response reports `limit`, `offset`, `total_count` and `has_more` inside the `meta` object of the envelope, where `total_count` is the size of the full filtered result set before the page window is applied and `has_more` is true exactly when records remain beyond the current window."

    Design: Corner/errors/duplicate_accident_filing_is_triggerable_until_the_prior_report_is_withdrawn
    """
    scene = _flown_uninsured_hobby_flight(api)
    flight = scene["flight"]

    report = create_filed_report(
        api,
        flight,
        RECREATIONAL_OCCURRED_AT,
        injury_level=InjuryLevel.NONE.value,
        reported_property_damage_cents=40000,
    )
    withdrawn = get_success_data(
        api.withdraw_accident_report(
            report["id"],
            withdraw_report_payload(probable_cause="Damage was pre-existing wear."),
            headers=INVESTIGATION_OFFICER,
        )
    )
    assert withdrawn["status"] == ReportStatus.WITHDRAWN.value, (
        f"withdrawal is a terminal state of its own, got {withdrawn['status']}"
    )
    assert withdrawn["reserved_cents"] == 0, (
        f"withdrawal zeroes the hold, expected 0, got {withdrawn['reserved_cents']}"
    )
    assert withdrawn["settlement_cents"] is None, (
        f"no payment follows a withdrawal, got {withdrawn['settlement_cents']!r}"
    )

    flown = get_success_data(
        api.get_flight(flight["id"], headers=scene["pilot_headers"])
    )
    assert flown["investigation_status"] == InvestigationStatus.CLOSED.value, (
        "withdrawal closes the flight's investigation dimension, got "
        f"{flown['investigation_status']}"
    )
    assert flown["status"] == FlightStatus.COMPLETED.value, (
        f"the operational status is never touched by the paperwork, got {flown['status']}"
    )

    records, meta = validate_paginated(
        api.list_accident_reports(
            params={"flight_id": flight["id"]}, headers=INVESTIGATION_OFFICER
        )
    )
    assert meta["total_count"] == 1, (
        "the withdrawn report is retained as a row rather than deleted, expected 1, got "
        f"{meta['total_count']}"
    )
    assert [record["id"] for record in records] == [report["id"]], (
        f"the withdrawn row is still the flight's report, got {[r['id'] for r in records]}"
    )
    assert records[0]["status"] == ReportStatus.WITHDRAWN.value, (
        f"the retained row carries its terminal status, got {records[0]['status']}"
    )


AUTHORISED_SETUP_DAY = "2026-10-01T00:00:00Z"
AUTHORISED_WINDOW_START = "2026-10-05T08:00:00Z"
AUTHORISED_WINDOW_END = "2026-10-05T12:00:00Z"
AUTHORISED_FLIGHT_START = "2026-10-05T09:00:00Z"
AUTHORISED_FLIGHT_END = "2026-10-05T10:00:00Z"
AUTHORISED_TOUCHDOWN = "2026-10-05T09:45:00Z"
AUTHORISED_OCCURRED_AT = "2026-10-05T09:30:00Z"
AUTHORISED_FILING_DAY = "2026-10-06T00:00:00Z"
OPEN_AIRSPACE_FLIGHT_START = "2026-10-07T09:00:00Z"
OPEN_AIRSPACE_FLIGHT_END = "2026-10-07T10:00:00Z"
OPEN_AIRSPACE_TOUCHDOWN = "2026-10-07T09:40:00Z"
OPEN_AIRSPACE_OCCURRED_AT = "2026-10-07T09:20:00Z"
OPEN_AIRSPACE_FILING_DAY = "2026-10-08T00:00:00Z"


def _insured_commercial_operator(api):
    """A commercial operator with cover carrying no deductible at all.

    A zero deductible keeps the closure waterfall's own arithmetic out of the way, so
    the only thing under test is who is allowed to sign the closure off.
    """
    set_clock(api, AUTHORISED_SETUP_DAY, headers=COMPLIANCE_OFFICER)
    pilot = create_certified_pilot(
        api, OperatorCategory.COMMERCIAL.value, scheduled_at=AUTHORISED_SETUP_DAY
    )
    aircraft = create_registered_aircraft(
        api, pilot["id"], takeoff_weight_g=249, max_altitude_ft=900
    )
    policy = create_active_policy(
        api, pilot["id"], coverage_limit_cents=2000000, deductible_cents=0
    )
    return {
        "pilot": pilot,
        "aircraft": aircraft,
        "policy": policy,
        "pilot_headers": make_pilot_headers(pilot["id"]),
    }


def _fly_and_file(api, scene, zone_id, start, end, touchdown, occurred_at, filing_day,
                  authorization_id=None, damage_cents=100000):
    """Fly one mission in the given zone and leave its report in INVESTIGATING."""
    flight = create_planned_flight(
        api,
        scene["pilot"]["id"],
        scene["aircraft"]["id"],
        zone_id,
        start,
        end,
        operation_category=OperationCategory.COMMERCIAL.value,
        planned_max_altitude_ft=380,
        authorization_id=authorization_id,
    )
    check = clear_flight_for_launch(api, flight)
    assert check["result"] == PreflightResult.PASSED.value, (
        f"setup expected a PASSED pre-flight sweep, got {check['result']} "
        f"with findings {check['blocking_findings']}"
    )
    set_clock(api, start, headers=COMPLIANCE_OFFICER)
    get_success_data(api.launch_flight(flight["id"], headers=scene["pilot_headers"]))
    flown = get_success_data(
        api.complete_flight(
            flight["id"],
            completion_payload(
                touchdown,
                max_altitude_reached_ft=360,
                incident_occurred=True,
                incident_summary="Battery bay deformed by a heavy touchdown.",
            ),
            headers=scene["pilot_headers"],
        )
    )
    set_clock(api, filing_day, headers=COMPLIANCE_OFFICER)
    report = create_filed_report(
        api,
        flown,
        occurred_at,
        injury_level=InjuryLevel.NONE.value,
        reported_property_damage_cents=damage_cents,
    )
    report = get_success_data(
        api.open_investigation(report["id"], headers=INVESTIGATION_OFFICER)
    )
    return flown, report


def test_the_approving_authoritys_identity_cannot_close_the_report_for_that_flight(api):
    """PRD §2.1: "An `InvestigationOfficer` closing an accident report whose flight cites an airspace authorization must have an `X-User-ID` that differs from that authorization's `approved_by_user_id`; when the flight cites no authorization, there is nothing to compare and the check passes."
    PRD §3.8: "Closure is admissible only from `INVESTIGATING`, and it is segregated: when the report's flight cites an airspace authorization, the closing operator's `X-User-ID` must differ from that authorization's `approved_by_user_id`."
    PRD §3.4: "Approval also sets `approved_by_user_id` to the deciding operator's `X-User-ID` and `decided_at` to the current instant, increments the zone's `reserved_slot_count` by one and the zone's `version` by one."
    PRD §3.8: "Closure then writes `settlement_cents`, zeroes `reserved_cents`, and sets `closed_by_user_id` to the closing operator's `X-User-ID`."

    Design: Corner/rbac/the_authority_who_approved_the_authorization_cannot_close_that_flights_report
    """
    scene = _insured_commercial_operator(api)
    zone = create_controlled_zone(
        api, class_ceiling_ft=700, max_concurrent_authorizations=3
    )
    authorization = create_approved_authorization(
        api,
        scene["pilot"]["id"],
        scene["aircraft"]["id"],
        zone["id"],
        AUTHORISED_WINDOW_START,
        AUTHORISED_WINDOW_END,
        requested_ceiling_ft=400,
    )
    assert authorization["approved_by_user_id"] == AIRSPACE_AUTHORITY_ID, (
        "the deciding operator's identity is retained on the approval, expected "
        f"{AIRSPACE_AUTHORITY_ID}, got {authorization['approved_by_user_id']!r}"
    )

    _flight, report = _fly_and_file(
        api,
        scene,
        zone["id"],
        AUTHORISED_FLIGHT_START,
        AUTHORISED_FLIGHT_END,
        AUTHORISED_TOUCHDOWN,
        AUTHORISED_OCCURRED_AT,
        AUTHORISED_FILING_DAY,
        authorization_id=authorization["id"],
    )
    assert report["reserved_cents"] == 125000, (
        "100000 cents of reported damage inflated by a quarter with no injury reserve is "
        f"125000, got {report['reserved_cents']}"
    )

    damage_lines = [damage_line("Airframe shell", 100000)]
    refused = api.close_accident_report(
        report["id"],
        close_report_payload(
            damage_lines, probable_cause="Descent rate exceeded the airframe's limit."
        ),
        headers=make_headers(AIRSPACE_AUTHORITY_ID, Role.INVESTIGATION_OFFICER.value),
    )
    validate_error(
        refused,
        ApiErrorId.SEGREGATION_OF_DUTIES.value,
        HTTP_STATUS_CODES[ApiErrorId.SEGREGATION_OF_DUTIES.value],
    )

    untouched = get_success_data(
        api.get_accident_report(report["id"], headers=INVESTIGATION_OFFICER)
    )
    assert untouched["status"] == ReportStatus.INVESTIGATING.value, (
        f"the refused closure changes nothing, expected INVESTIGATING, got {untouched['status']}"
    )
    assert untouched["settlement_cents"] is None, (
        f"the refused closure pays nothing, got {untouched['settlement_cents']!r}"
    )
    assert untouched["reserved_cents"] == 125000, (
        f"the reserve is still held, expected 125000, got {untouched['reserved_cents']}"
    )

    closed = get_success_data(
        api.close_accident_report(
            report["id"],
            close_report_payload(
                damage_lines, probable_cause="Descent rate exceeded the airframe's limit."
            ),
            headers=INVESTIGATION_OFFICER,
        )
    )
    assert closed["status"] == ReportStatus.CLOSED.value, (
        f"a different officer may close the same report, got {closed['status']}"
    )
    assert closed["settlement_cents"] == 85000, (
        "a single 100000 cent line at 85 percent against a zero deductible settles at "
        f"85000, got {closed['settlement_cents']}"
    )
    assert closed["reserved_cents"] == 0, (
        f"closure zeroes the hold, expected 0, got {closed['reserved_cents']}"
    )
    assert closed["closed_by_user_id"] == INVESTIGATION_OFFICER_ID, (
        "the closing operator's identity is recorded, expected "
        f"{INVESTIGATION_OFFICER_ID}, got {closed['closed_by_user_id']!r}"
    )


def test_the_same_identity_may_close_a_report_whose_flight_cites_no_authorization(api):
    """PRD §2.1: "An `InvestigationOfficer` closing an accident report whose flight cites an airspace authorization must have an `X-User-ID` that differs from that authorization's `approved_by_user_id`; when the flight cites no authorization, there is nothing to compare and the check passes."
    PRD §2.11: "**Accident-close segregation**, on `POST /drone-ops/accident-reports/{id}/close` only: when the report's flight cites an authorization, `X-User-ID` differs from that authorization's `approved_by_user_id` — otherwise `ERR_SEGREGATION_OF_DUTIES` (403)."
    PRD §3.8: "Closure then writes `settlement_cents`, zeroes `reserved_cents`, and sets `closed_by_user_id` to the closing operator's `X-User-ID`."

    Design: Corner/rbac/the_authority_who_approved_the_authorization_cannot_close_that_flights_report
    """
    scene = _insured_commercial_operator(api)
    open_zone = create_zone(
        api,
        class_code=ZoneClassCode.G.value,
        class_ceiling_ft=1200,
        requires_authorization=False,
        max_concurrent_authorizations=3,
    )
    flight, report = _fly_and_file(
        api,
        scene,
        open_zone["id"],
        OPEN_AIRSPACE_FLIGHT_START,
        OPEN_AIRSPACE_FLIGHT_END,
        OPEN_AIRSPACE_TOUCHDOWN,
        OPEN_AIRSPACE_OCCURRED_AT,
        OPEN_AIRSPACE_FILING_DAY,
        damage_cents=20000,
    )
    assert flight["authorization_id"] is None, (
        "a mission in uncontrolled airspace cites no authorization, got "
        f"{flight['authorization_id']!r}"
    )

    closed = get_success_data(
        api.close_accident_report(
            report["id"],
            close_report_payload(
                [damage_line("Landing gear", 20000)],
                probable_cause="Gear leg fractured on an uneven surface.",
            ),
            headers=make_headers(AIRSPACE_AUTHORITY_ID, Role.INVESTIGATION_OFFICER.value),
        )
    )
    assert closed["status"] == ReportStatus.CLOSED.value, (
        "with no authorization to compare against there is nothing to segregate, so the "
        f"closure stands, got {closed['status']}"
    )
    assert closed["settlement_cents"] == 17000, (
        "a single 20000 cent line at 85 percent against a zero deductible settles at "
        f"17000, got {closed['settlement_cents']}"
    )
    assert closed["closed_by_user_id"] == AIRSPACE_AUTHORITY_ID, (
        "the closing identity is recorded as supplied, expected "
        f"{AIRSPACE_AUTHORITY_ID}, got {closed['closed_by_user_id']!r}"
    )
    assert closed["reserved_cents"] == 0, (
        f"closure zeroes the hold, expected 0, got {closed['reserved_cents']}"
    )
