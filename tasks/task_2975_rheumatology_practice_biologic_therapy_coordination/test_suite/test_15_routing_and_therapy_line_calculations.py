"""Breadth coverage for the routing, selector and therapy-line calculations.

Every test in this module translates exactly one instance of the
`calculations` section of the corner design index: the one-hop line-of-therapy
walk, the authorization selector's window-before-units ordering, the
`SITE_NEUTRAL` chair-time bound, the exclusive assistance tier bound, the
inclusive ninety-day escalation dwell and the two step-therapy trial rules.

The dwell and exposure rules are read off the logical clock, so those tests
park it explicitly with `fixtures.set_clock` before the hop whose outcome it
governs — and the twelve-week exposure test activates each trial episode
before advancing the clock, because `therapy_exposure_weeks` is frozen at
discontinuation and is 0 for an episode that never activated.
"""
import pytest

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_client, assertions, factories, fixtures
from test_helpers.constants import CLOCK_DEFAULT, instant


def _tocilizumab_payload(**overrides) -> dict:
    """An IV `IL6` product, so the plan's `TNFI` step requirement is not
    self-satisfied by the drug's own molecule class."""
    payload = factories.create_drug_payload(
        name="Tocilizumab",
        molecule_class="IL6",
        route="IV",
        formulary_tier=4,
        acquisition_cost_cents=500_000,
        admin_time_minutes=150,
        monitoring_panel_type="CMP",
        monitoring_panel_interval_days=90,
    )
    payload.update(overrides)
    return payload


def _sibling_scenario(scenario: fixtures.Scenario, drug_id: str = "") -> fixtures.Scenario:
    """A second patient sharing the first scenario's reference data.

    Opening an episode supersedes the patient's other `PLANNED` episodes, so a
    recipe that needs two independent episodes needs two patients.
    """
    return fixtures.Scenario(
        rheumatologist_id=scenario.rheumatologist_id,
        nurse_id=scenario.nurse_id,
        drug_id=drug_id or scenario.drug_id,
        plan_id=scenario.plan_id,
        chair_id=scenario.chair_id,
    )


# ---------------------------------------------------------------------------
# line_of_therapy_walks_exactly_one_hop_and_requires_a_discontinued_parent
# ---------------------------------------------------------------------------
def test_line_of_therapy_is_one_more_than_the_named_predecessor():
    """A three-link chain, each link naming only its immediate predecessor.

    "Given a valid predecessor, `line_of_therapy` is one more than the
    predecessor's own; with no predecessor it is 1."

    Design: Corner/calculations/line_of_therapy_walks_exactly_one_hop_and_requires_a_discontinued_parent
    """
    fixtures.set_clock(CLOCK_DEFAULT)
    scenario = fixtures.bootstrap_reference()
    fixtures.register_patient(scenario)

    first = fixtures.open_planned_episode(scenario, therapy_start_at=CLOCK_DEFAULT)
    assertions.assert_therapy_episode(first)
    assert first["line_of_therapy"] == 1
    assert first["prior_episode_id"] is None
    validate_success(
        api_client.discontinue_therapy_episode(
            first["id"], {"discontinuation_reason": "INADEQUATE_RESPONSE"}, scenario.rheum_headers
        )
    )

    second = fixtures.open_planned_episode(
        scenario, therapy_start_at=CLOCK_DEFAULT, prior_episode_id=first["id"]
    )
    assert second["line_of_therapy"] == 2
    assert second["prior_episode_id"] == first["id"]
    validate_success(
        api_client.discontinue_therapy_episode(
            second["id"], {"discontinuation_reason": "INTOLERANCE"}, scenario.rheum_headers
        )
    )

    third = fixtures.open_planned_episode(
        scenario, therapy_start_at=CLOCK_DEFAULT, prior_episode_id=second["id"]
    )
    assert third["line_of_therapy"] == 3, (
        "the third line is read off the parent's own depth, not by re-walking the chain"
    )
    assert third["prior_episode_id"] == second["id"]

    rows, meta = assertions.validate_list(
        api_client.list_therapy_episodes(
            fixtures.ADMIN, params={"prior_episode_id": second["id"]}
        )
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [third["id"]]


def test_a_still_planned_predecessor_is_refused():
    """The third episode is still `PLANNED`, so it cannot be a predecessor.

    "A predecessor belonging to another patient, one that is still planned,
    active or held, or one that would push the chain to a seventh line is
    refused with `ERR_PRIOR_EPISODE_INVALID` (HTTP 422)."

    Design: Corner/calculations/line_of_therapy_walks_exactly_one_hop_and_requires_a_discontinued_parent
    """
    fixtures.set_clock(CLOCK_DEFAULT)
    scenario = fixtures.bootstrap_reference()
    fixtures.register_patient(scenario)

    first = fixtures.open_planned_episode(scenario, therapy_start_at=CLOCK_DEFAULT)
    validate_success(
        api_client.discontinue_therapy_episode(
            first["id"], {"discontinuation_reason": "INADEQUATE_RESPONSE"}, scenario.rheum_headers
        )
    )
    second = fixtures.open_planned_episode(
        scenario, therapy_start_at=CLOCK_DEFAULT, prior_episode_id=first["id"]
    )
    validate_success(
        api_client.discontinue_therapy_episode(
            second["id"], {"discontinuation_reason": "INTOLERANCE"}, scenario.rheum_headers
        )
    )
    third = fixtures.open_planned_episode(
        scenario, therapy_start_at=CLOCK_DEFAULT, prior_episode_id=second["id"]
    )
    assert third["therapy_state"] == "PLANNED"

    rejected = api_client.create_therapy_episode(
        factories.create_therapy_episode_payload(
            scenario.patient_id,
            scenario.drug_id,
            scenario.plan_id,
            scenario.patient_version,
            therapy_start_at=CLOCK_DEFAULT,
            prior_episode_id=third["id"],
        ),
        scenario.rheum_headers,
    )
    validate_error(rejected, "ERR_PRIOR_EPISODE_INVALID", 422)

    still_planned = validate_success(
        api_client.get_therapy_episode(third["id"], fixtures.ADMIN)
    )
    assert still_planned["therapy_state"] == "PLANNED", (
        "the rejected create superseded nothing"
    )


# ---------------------------------------------------------------------------
# authorization_selector_checks_the_window_before_the_unit_pool
# ---------------------------------------------------------------------------
def test_authorization_selector_narrows_by_window_before_checking_units():
    """Two approved authorizations with disjoint coverage windows.

    "Because the window narrowing precedes the per-authorization unit check, a
    request that falls outside every window is told about the window rather
    than about the units."

    Design: Corner/calculations/authorization_selector_checks_the_window_before_the_unit_pool
    """
    fixtures.set_clock(CLOCK_DEFAULT)
    scenario = fixtures.bootstrap_reference()
    fixtures.screened_patient(scenario)
    fixtures.open_planned_episode(scenario, therapy_start_at=CLOCK_DEFAULT)
    fixtures.make_monitoring_current(scenario, collected_at=instant(2026, 7, 25))

    auth_a = fixtures.open_authorization(scenario, 1)["id"]
    fixtures.submit_authorization(scenario, auth_a)
    auth_b = fixtures.open_authorization(scenario, 6)["id"]
    fixtures.submit_authorization(scenario, auth_b)

    fixtures.approve_authorization(
        scenario,
        auth_a,
        approved_units=1,
        valid_from=instant(2026, 8, 1),
        valid_through=instant(2026, 8, 31),
    )
    fixtures.approve_authorization(
        scenario,
        auth_b,
        approved_units=6,
        valid_from=instant(2026, 9, 1),
        valid_through=instant(2027, 1, 28),
    )
    fixtures.activate_episode(scenario)

    appt_a = fixtures.schedule_appointment(scenario, instant(2026, 8, 15, 9, 0, 0))
    assertions.assert_infusion_appointment(appt_a)
    assert appt_a["reserved_authorization_id"] == auth_a, (
        "only the August window contains 2026-08-15"
    )
    assert appt_a["dose_sequence"] == 1

    appt_b = fixtures.schedule_appointment(scenario, instant(2026, 9, 15, 9, 0, 0))
    assert appt_b["reserved_authorization_id"] == auth_b, (
        "only the September window contains 2026-09-15"
    )
    assert appt_b["dose_sequence"] == 2

    assertions.assert_unit_ledger(
        scenario.refresh_authorization(auth_a), reserved=1, consumed=0, remaining=0
    )
    assertions.assert_unit_ledger(
        scenario.refresh_authorization(auth_b), reserved=1, consumed=0, remaining=5
    )

    exhausted = api_client.create_infusion_appointment(
        factories.create_appointment_payload(
            scenario.episode_id,
            scenario.chair_id,
            scheduled_start=instant(2026, 8, 20, 9, 0, 0),
        ),
        scenario.nurse_headers,
    )
    validate_error(exhausted, "ERR_AUTHORIZATION_UNITS_EXHAUSTED")

    outside = api_client.create_infusion_appointment(
        factories.create_appointment_payload(
            scenario.episode_id,
            scenario.chair_id,
            scheduled_start=instant(2026, 7, 15, 9, 0, 0),
        ),
        scenario.nurse_headers,
    )
    validate_error(outside, "ERR_APPOINTMENT_OUTSIDE_AUTH_WINDOW")

    rows, meta = assertions.validate_list(
        api_client.list_infusion_appointments(
            fixtures.ADMIN, params={"reserved_authorization_id": auth_a}
        )
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [appt_a["id"]]


# ---------------------------------------------------------------------------
# site_neutral_policy_flips_to_hospital_outpatient_above_180_admin_minutes
# ---------------------------------------------------------------------------
def test_site_neutral_is_inclusive_at_one_hundred_eighty_admin_minutes():
    """A 180-minute product and a 240-minute product on one `SITE_NEUTRAL` plan.

    "That three-hour comparison is inclusive, so a product needing exactly 180
    minutes of chair time routes to the ambulatory centre."

    Design: Corner/calculations/site_neutral_policy_flips_to_hospital_outpatient_above_180_admin_minutes
    """
    fixtures.set_clock(CLOCK_DEFAULT)
    scenario = fixtures.bootstrap_reference(
        drug_payload=factories.infliximab_payload(admin_time_minutes=180),
        plan_payload=factories.meridian_plan_payload(
            name="Northwind Site Neutral",
            site_of_care_policy="SITE_NEUTRAL",
            coinsurance_pct=0.20,
            deductible_remaining_cents=0,
            medical_facility_fee_cents=20_000,
            hospital_outpatient_multiplier=1.50,
            step_therapy_classes_required=[],
        ),
    )
    rituximab = fixtures.create_drug(
        None,
        factories.create_drug_payload(
            name="Rituximab",
            molecule_class="CD20",
            route="IV",
            formulary_tier=4,
            acquisition_cost_cents=900_000,
            admin_time_minutes=240,
            monitoring_panel_type="CBC",
            monitoring_panel_interval_days=180,
        ),
    )

    fixtures.register_patient(scenario)
    ambulatory = fixtures.open_planned_episode(scenario, therapy_start_at=CLOCK_DEFAULT)

    second = _sibling_scenario(scenario, rituximab["id"])
    fixtures.register_patient(second)
    hospital = fixtures.open_planned_episode(second, therapy_start_at=CLOCK_DEFAULT)

    assertions.assert_therapy_episode(ambulatory)
    assert ambulatory["site_of_care"] == "AMBULATORY_INFUSION_CENTER", (
        "exactly 180 minutes of chair time stays ambulatory"
    )
    assert ambulatory["benefit_channel"] == "MEDICAL"

    assertions.assert_therapy_episode(hospital)
    assert hospital["site_of_care"] == "HOSPITAL_OUTPATIENT", (
        "240 minutes of chair time exceeds three hours"
    )
    assert hospital["benefit_channel"] == "MEDICAL"


def test_the_hospital_multiplier_applies_only_at_the_hospital_site():
    """The same plan prices the two sites with different multipliers.

    "On the `MEDICAL` variant, a multiplier applies: it is the plan's
    `hospital_outpatient_multiplier` when the episode's `site_of_care` is
    `HOSPITAL_OUTPATIENT`, and 1.00 for every other site."

    Design: Corner/calculations/site_neutral_policy_flips_to_hospital_outpatient_above_180_admin_minutes
    """
    fixtures.set_clock(CLOCK_DEFAULT)
    scenario = fixtures.bootstrap_reference(
        drug_payload=factories.infliximab_payload(admin_time_minutes=180),
        plan_payload=factories.meridian_plan_payload(
            name="Northwind Site Neutral",
            site_of_care_policy="SITE_NEUTRAL",
            coinsurance_pct=0.20,
            deductible_remaining_cents=0,
            medical_facility_fee_cents=20_000,
            hospital_outpatient_multiplier=1.50,
            step_therapy_classes_required=[],
        ),
    )
    rituximab = fixtures.create_drug(
        None,
        factories.create_drug_payload(
            name="Rituximab",
            molecule_class="CD20",
            route="IV",
            formulary_tier=4,
            acquisition_cost_cents=900_000,
            admin_time_minutes=240,
            monitoring_panel_type="CBC",
            monitoring_panel_interval_days=180,
        ),
    )

    fixtures.register_patient(scenario)
    ambulatory = fixtures.open_planned_episode(scenario, therapy_start_at=CLOCK_DEFAULT)
    second = _sibling_scenario(scenario, rituximab["id"])
    fixtures.register_patient(second)
    hospital = fixtures.open_planned_episode(second, therapy_start_at=CLOCK_DEFAULT)

    ambulatory_estimate = validate_success(
        api_client.get_cost_share_estimate(
            ambulatory["id"], fixtures.COUNSELOR, params={"dose_count": 3}
        )
    )
    assertions.assert_cost_share_estimate(
        ambulatory_estimate,
        allowed_per_dose_cents=250_050,
        facility_per_dose_cents=20_000,
        per_dose_share_cents=[70_010, 70_010, 70_010],
    )
    assert ambulatory_estimate["total_member_share_cents"] == 210_030
    assert ambulatory_estimate["deductible_applied_cents"] == 0
    assert ambulatory_estimate["coinsurance_cents"] == 150_030
    assert ambulatory_estimate["facility_cents"] == 60_000

    hospital_estimate = validate_success(
        api_client.get_cost_share_estimate(
            hospital["id"], fixtures.COUNSELOR, params={"dose_count": 3}
        )
    )
    assertions.assert_cost_share_estimate(
        hospital_estimate,
        allowed_per_dose_cents=1_350_000,
        facility_per_dose_cents=20_000,
        per_dose_share_cents=[290_000, 290_000, 290_000],
    )
    assert hospital_estimate["total_member_share_cents"] == 870_000
    assert hospital_estimate["coinsurance_cents"] == 810_000
    assert hospital_estimate["facility_cents"] == 60_000


# ---------------------------------------------------------------------------
# assistance_tier_bound_is_exclusive_so_a_100000_cent_share_lands_in_tier_three
# ---------------------------------------------------------------------------
def test_a_share_of_exactly_one_hundred_thousand_cents_lands_in_the_eighty_percent_tier():
    """Dose 1 costs 180000 cents and dose 2 costs exactly 100000 cents.

    "Both boundaries are exclusive upper bounds, so a share of exactly 20,000
    cents falls in the 90-percent tier and a share of exactly 100,000 cents
    falls in the 80-percent tier."

    Design: Corner/calculations/assistance_tier_bound_is_exclusive_so_a_100000_cent_share_lands_in_tier_three
    """
    fixtures.set_clock(CLOCK_DEFAULT)
    scenario = fixtures.bootstrap_reference(
        drug_payload=_tocilizumab_payload(),
        plan_payload=factories.meridian_plan_payload(
            name="Copay Bridge PPO",
            site_of_care_policy="PREFER_AMBULATORY",
            coinsurance_pct=0.20,
            deductible_remaining_cents=100_000,
            medical_facility_fee_cents=0,
            hospital_outpatient_multiplier=1.00,
            step_therapy_classes_required=[],
        ),
    )
    fixtures.screened_patient(scenario)
    fixtures.open_planned_episode(scenario, therapy_start_at=CLOCK_DEFAULT)
    fixtures.make_monitoring_current(scenario, collected_at=instant(2026, 7, 25))
    fixtures.approved_authorization(
        scenario,
        6,
        approved_units=6,
        valid_from=instant(2026, 8, 1),
        valid_through=instant(2027, 1, 28),
    )
    fixtures.activate_episode(scenario)
    enrollment = fixtures.active_enrollment(
        scenario, annual_benefit_cents=1_000_000, coverage_start=CLOCK_DEFAULT
    )
    assertions.assert_assistance_enrollment(enrollment)
    assert enrollment["status"] == "ACTIVE"

    estimate = validate_success(
        api_client.get_cost_share_estimate(
            scenario.episode_id, fixtures.COUNSELOR, params={"dose_count": 6}
        )
    )
    assertions.assert_cost_share_estimate(
        estimate,
        allowed_per_dose_cents=500_000,
        facility_per_dose_cents=0,
        per_dose_share_cents=[180_000, 100_000, 100_000, 100_000, 100_000, 100_000],
    )
    assert estimate["total_member_share_cents"] == 680_000
    assert estimate["deductible_applied_cents"] == 100_000
    assert estimate["coinsurance_cents"] == 580_000
    assert estimate["facility_cents"] == 0

    first = fixtures.schedule_appointment(scenario, instant(2026, 8, 3, 9, 0, 0))
    assertions.assert_infusion_appointment(first)
    assert first["dose_sequence"] == 1
    assert first["dose_cost_share_cents"] == 180_000
    assert first["assistance_applied_cents"] == 144_000
    assert first["patient_out_of_pocket_cents"] == 36_000
    assert first["reserved_enrollment_id"] == enrollment["id"]

    second = fixtures.schedule_appointment(scenario, instant(2026, 8, 5, 9, 0, 0))
    assert second["dose_sequence"] == 2
    assert second["dose_cost_share_cents"] == 100_000
    assert second["assistance_applied_cents"] == 80_000, (
        "an inclusive tier-two bound would have covered 90000 of a 100000 cent share"
    )
    assert second["assistance_applied_cents"] != 90_000
    assert second["patient_out_of_pocket_cents"] == 20_000
    assert second["reserved_enrollment_id"] == enrollment["id"]

    final = scenario.refresh_enrollment(enrollment["id"])
    assertions.assert_money_ledger(final, used=0, reserved=224_000, remaining=776_000)
    assert final["status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# escalation_dwell_boundary_is_inclusive_at_ninety_days
# ---------------------------------------------------------------------------
def test_escalation_dwell_is_inclusive_at_ninety_days():
    """One `ACTIVE` episode begun 2026-05-05T14:00Z, two `MODERATE` visits.

    "The server looks for a therapy episode belonging to the visit's patient
    whose `therapy_state` is `ACTIVE` and whose `therapy_start_at` is at least
    90 days before this visit's `visit_datetime` — held, planned and
    discontinued episodes are all excluded from that test, and the dwell
    comparison is inclusive, so an episode begun exactly 90 days before the
    visit does qualify."

    Design: Corner/calculations/escalation_dwell_boundary_is_inclusive_at_ninety_days
    """
    fixtures.set_clock(instant(2026, 5, 5))
    scenario = fixtures.bootstrap_reference()
    fixtures.register_patient(scenario)
    fixtures.file_clearing_screens(
        scenario, collected_at=instant(2026, 4, 20), resulted_at=instant(2026, 4, 21)
    )
    fixtures.open_planned_episode(scenario, therapy_start_at=instant(2026, 5, 5, 14, 0, 0))
    fixtures.make_monitoring_current(scenario, collected_at=instant(2026, 5, 1))
    fixtures.approved_authorization(
        scenario,
        6,
        approved_units=6,
        valid_from=instant(2026, 5, 5),
        valid_through=instant(2026, 11, 1),
    )
    activated = fixtures.activate_episode(scenario)
    assert activated["therapy_state"] == "ACTIVE"

    fixtures.set_clock(instant(2026, 8, 3, 15, 0, 0))
    day_89 = fixtures.checked_in_visit(scenario, instant(2026, 8, 2, 14, 0, 0), "FOLLOW_UP")
    day_90 = fixtures.checked_in_visit(scenario, instant(2026, 8, 3, 14, 0, 0), "FOLLOW_UP")

    moderate = factories.score_visit_cdai_payload(
        tender_joint_count=6,
        swollen_joint_count=5,
        patient_global_assessment=3.0,
        physician_global_assessment=3.0,
    )
    scored_89 = fixtures.score_visit(scenario, dict(moderate), day_89["id"])
    assert scored_89["activity_score"] == pytest.approx(17.00, abs=0.01)
    assert scored_89["activity_category"] == "MODERATE"
    assert scored_89["escalation_recommendation"] == "OPTIMIZE_CURRENT", (
        "89 whole days of dwell is one day short of the inclusive bound"
    )

    scored_90 = fixtures.score_visit(scenario, dict(moderate), day_90["id"])
    assert scored_90["activity_score"] == pytest.approx(17.00, abs=0.01)
    assert scored_90["activity_category"] == "MODERATE"
    assert scored_90["escalation_recommendation"] == "ESCALATE", (
        "exactly 90 days of dwell does qualify because the comparison is inclusive"
    )

    episode = scenario.refresh_episode()
    assert episode["therapy_state"] == "ACTIVE"
    assertions.assert_instant_equals(
        episode["therapy_start_at"], instant(2026, 5, 5, 14, 0, 0), "therapy_start_at"
    )

    patient = scenario.refresh_patient()
    assert patient["latest_activity_category"] == "MODERATE"
    assert patient["target_status"] == "NOT_AT_TARGET"


# ---------------------------------------------------------------------------
# step_therapy_counts_intolerance_at_any_exposure_but_ignores_patient_request
# ---------------------------------------------------------------------------
def _discontinued_trial(
    scenario: fixtures.Scenario, drug_id: str, discontinuation_reason: str
) -> dict:
    """Open a `TNFI` episode for the scenario's patient and stop it at once."""
    payload = factories.create_therapy_episode_payload(
        scenario.patient_id,
        drug_id,
        scenario.plan_id,
        scenario.patient_version,
        therapy_start_at=CLOCK_DEFAULT,
    )
    trial = validate_success(
        api_client.create_therapy_episode(payload, scenario.rheum_headers), 201
    )
    return validate_success(
        api_client.discontinue_therapy_episode(
            trial["id"],
            {"discontinuation_reason": discontinuation_reason},
            scenario.rheum_headers,
        )
    )


def test_intolerance_satisfies_the_step_but_patient_request_does_not():
    """Two patients, identical `TNFI` history, different stop reasons.

    "Episodes discontinued for `REMISSION_TAPER`, `PATIENT_REQUEST`,
    `SAFETY_EVENT` or `SUPERSEDED` never count as a trial, whatever their
    exposure."

    Design: Corner/calculations/step_therapy_counts_intolerance_at_any_exposure_but_ignores_patient_request
    """
    fixtures.set_clock(CLOCK_DEFAULT)
    scenario = fixtures.bootstrap_reference(
        drug_payload=_tocilizumab_payload(),
        plan_payload=factories.meridian_plan_payload(
            step_therapy_classes_required=["TNFI"]
        ),
    )
    infliximab = fixtures.create_drug(None, factories.infliximab_payload())

    fixtures.register_patient(scenario)
    tolerant = _discontinued_trial(scenario, infliximab["id"], "INTOLERANCE")

    second = _sibling_scenario(scenario)
    fixtures.register_patient(second)
    requested = _discontinued_trial(second, infliximab["id"], "PATIENT_REQUEST")

    assert tolerant["therapy_exposure_weeks"] == 0
    assert tolerant["discontinuation_reason"] == "INTOLERANCE"
    assert requested["therapy_exposure_weeks"] == 0
    assert requested["discontinuation_reason"] == "PATIENT_REQUEST"

    fixtures.open_planned_episode(scenario, therapy_start_at=CLOCK_DEFAULT)
    first_auth = fixtures.open_authorization(scenario, 6)
    fixtures.open_planned_episode(second, therapy_start_at=CLOCK_DEFAULT)
    second_auth = fixtures.open_authorization(second, 6)

    submitted = fixtures.submit_authorization(scenario, first_auth["id"])
    assertions.assert_authorization(submitted)
    assert submitted["status"] == "SUBMITTED"
    assert submitted["unmet_step_therapy_classes"] == [], (
        "an INTOLERANCE trial counts at any exposure at all"
    )

    rejected = api_client.submit_authorization(second_auth["id"], fixtures.COORDINATOR)
    validate_error(rejected, "ERR_STEP_THERAPY_NOT_SATISFIED", 422)

    still_draft = validate_success(
        api_client.get_authorization(second_auth["id"], fixtures.ADMIN)
    )
    assert still_draft["status"] == "DRAFT", "a refused submission does not advance the status"
    assert still_draft["submitted_at"] is None


# ---------------------------------------------------------------------------
# step_therapy_inadequate_response_trial_needs_exactly_twelve_weeks_of_exposure
# ---------------------------------------------------------------------------
def test_inadequate_response_needs_twelve_whole_weeks_of_exposure():
    """Eighty-three days of exposure fails; eighty-four days satisfies the step.

    "The **satisfied** set contains every molecule class for which the same
    patient has some other therapy episode, different from this
    authorization's episode, whose `therapy_state` is `DISCONTINUED`, whose
    `discontinuation_reason` is either `INADEQUATE_RESPONSE` or `INTOLERANCE`,
    whose drug's `molecule_class` is that class, and which additionally either
    was stopped for `INTOLERANCE` — in which case any exposure at all counts —
    or accumulated `therapy_exposure_weeks` of at least 12."

    Design: Corner/calculations/step_therapy_inadequate_response_trial_needs_exactly_twelve_weeks_of_exposure
    """
    fixtures.set_clock(instant(2026, 1, 1))
    scenario = fixtures.bootstrap_reference(
        drug_payload=factories.infliximab_payload(),
        plan_payload=factories.meridian_plan_payload(
            step_therapy_classes_required=["TNFI"]
        ),
    )
    tocilizumab = fixtures.create_drug(None, _tocilizumab_payload())

    def _activated_trial(sc: fixtures.Scenario) -> dict:
        fixtures.register_patient(sc)
        fixtures.file_clearing_screens(
            sc, collected_at=instant(2025, 12, 19), resulted_at=instant(2025, 12, 20)
        )
        fixtures.open_planned_episode(sc, therapy_start_at=instant(2026, 1, 1))
        fixtures.make_monitoring_current(sc, collected_at=instant(2025, 12, 28))
        fixtures.approved_authorization(
            sc,
            6,
            approved_units=6,
            valid_from=instant(2026, 1, 1),
            valid_through=instant(2026, 6, 30),
        )
        return fixtures.activate_episode(sc)

    trial_one_id = _activated_trial(scenario)["id"]
    second = _sibling_scenario(scenario)
    trial_two_id = _activated_trial(second)["id"]

    fixtures.set_clock(instant(2026, 3, 25))
    trial_one = validate_success(
        api_client.discontinue_therapy_episode(
            trial_one_id,
            {"discontinuation_reason": "INADEQUATE_RESPONSE"},
            scenario.rheum_headers,
        )
    )
    fixtures.set_clock(instant(2026, 3, 26))
    trial_two = validate_success(
        api_client.discontinue_therapy_episode(
            trial_two_id,
            {"discontinuation_reason": "INADEQUATE_RESPONSE"},
            second.rheum_headers,
        )
    )

    assert trial_one["therapy_exposure_weeks"] == 11, "83 days truncates to 11 whole weeks"
    assertions.assert_instant_equals(
        trial_one["discontinued_at"], instant(2026, 3, 25), "trial one discontinued_at"
    )
    assert trial_two["therapy_exposure_weeks"] == 12, "84 days is exactly 12 whole weeks"
    assertions.assert_instant_equals(
        trial_two["discontinued_at"], instant(2026, 3, 26), "trial two discontinued_at"
    )

    next_one = fixtures.open_planned_episode(
        scenario,
        drug_id=tocilizumab["id"],
        therapy_start_at=instant(2026, 3, 26),
        prior_episode_id=trial_one_id,
    )
    next_two = fixtures.open_planned_episode(
        second,
        drug_id=tocilizumab["id"],
        therapy_start_at=instant(2026, 3, 26),
        prior_episode_id=trial_two_id,
    )
    assert next_one["line_of_therapy"] == 2
    assert next_two["line_of_therapy"] == 2

    short_auth = fixtures.open_authorization(scenario, 6)
    full_auth = fixtures.open_authorization(second, 6)

    rejected = api_client.submit_authorization(short_auth["id"], fixtures.COORDINATOR)
    validate_error(rejected, "ERR_STEP_THERAPY_NOT_SATISFIED", 422)
    still_draft = validate_success(
        api_client.get_authorization(short_auth["id"], fixtures.ADMIN)
    )
    assert still_draft["status"] == "DRAFT"
    assert still_draft["submitted_at"] is None

    submitted = fixtures.submit_authorization(second, full_auth["id"])
    assertions.assert_authorization(submitted)
    assert submitted["status"] == "SUBMITTED"
    assert submitted["unmet_step_therapy_classes"] == []
    assertions.assert_instant_equals(
        submitted["submitted_at"], instant(2026, 3, 26), "submitted_at"
    )
