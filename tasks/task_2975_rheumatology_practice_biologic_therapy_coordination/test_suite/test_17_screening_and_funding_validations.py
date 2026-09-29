"""Screening-posture, funding-routing and payload-validation corners.

These tests pin the conditional validations that guard activation and
submission — the four-case hepatitis B walk of §3.3 as it is consumed by
§3.4's and §3.5's gates, the benefit-channel routing that can leave an
episode with nowhere to bill, the attestation that a formulary exception
needs before it may excuse step therapy, the five natural keys of §3.1,
the authorization coverage window of §3.7 and the instrument-specific
component requirements of §3.2.
"""
import pytest

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import ApiErrorId, assertions, constants, factories, fixtures


def test_incomplete_hepatitis_b_panel_blocks_activation_until_both_markers(api):
    """A negative surface antigen on its own leaves `hbv_screen_status`
    `INCOMPLETE` and activation is refused; filing the core antibody turns the
    posture `CLEARED` and exposes the monitoring gate underneath, and only the
    panel finishes the activation.

    PRD: "If the drug has `hbv_screen_required` set, the patient's
    `hbv_screen_status` must not be `ACTIVE_INFECTION`, or the request is
    refused with `ERR_HBV_ACTIVE_INFECTION_CONTRAINDICATED` (HTTP 422); and it
    must not be `INCOMPLETE` either, or the request is refused with
    `ERR_HBV_SCREEN_INCOMPLETE` (HTTP 422)."

    Design: Corner/validations/incomplete_hepatitis_b_panel_blocks_activation_until_both_markers_are_on_file
    """
    fixtures.set_clock(constants.CLOCK_DEFAULT)
    scenario = fixtures.bootstrap_reference()
    fixtures.register_patient(scenario)
    fixtures.file_screen(scenario, "TB_IGRA", "NEGATIVE")
    fixtures.file_screen(scenario, "HBV_SURFACE_AG", "NEGATIVE")

    half_screened = scenario.refresh_patient()
    assert half_screened["tb_screen_status"] == "CLEARED"
    assert half_screened["hbv_screen_status"] == "INCOMPLETE"

    fixtures.open_planned_episode(scenario)
    fixtures.approved_authorization(scenario, 6)
    assert scenario.refresh_episode()["funding_state"] == "AUTHORIZED"

    validate_error(
        api.activate_therapy_episode(scenario.episode_id, scenario.rheum_headers),
        ApiErrorId.ERR_HBV_SCREEN_INCOMPLETE.value,
    )
    assert scenario.refresh_patient()["hbv_screen_status"] == "INCOMPLETE"

    fixtures.file_screen(scenario, "HBV_CORE_AB", "NEGATIVE")
    assert scenario.refresh_patient()["hbv_screen_status"] == "CLEARED"

    validate_error(
        api.activate_therapy_episode(scenario.episode_id, scenario.rheum_headers),
        ApiErrorId.ERR_MONITORING_LAB_OVERDUE.value,
    )

    fixtures.file_monitoring_lab(
        scenario,
        panel_type="CMP",
        collected_at=constants.instant(2026, 7, 25),
        alt_u_l=30.0,
        neutrophil_k_ul=3.20,
    )
    activated = get_success_data(
        api.activate_therapy_episode(scenario.episode_id, scenario.rheum_headers)
    )
    assert activated["therapy_state"] == "ACTIVE"
    assert scenario.refresh_patient()["active_episode_count"] == 1


def test_both_negative_markers_are_what_clears_the_hepatitis_b_posture(api):
    """The `CLEARED` posture needs *both* a current negative surface antigen and
    a current negative core antibody; with only one of the two on file the
    posture is `INCOMPLETE`.

    PRD: "It is `CLEARED` when both a current `HBV_SURFACE_AG` record and a
    current `HBV_CORE_AB` record report `NEGATIVE`."

    Design: Corner/validations/incomplete_hepatitis_b_panel_blocks_activation_until_both_markers_are_on_file
    """
    fixtures.set_clock(constants.CLOCK_DEFAULT)
    scenario = fixtures.bootstrap_reference()
    fixtures.register_patient(scenario)

    assert scenario.refresh_patient()["hbv_screen_status"] == "INCOMPLETE"

    fixtures.file_screen(scenario, "HBV_SURFACE_AG", "NEGATIVE")
    assert scenario.refresh_patient()["hbv_screen_status"] == "INCOMPLETE"

    fixtures.file_screen(scenario, "HBV_CORE_AB", "NEGATIVE")
    assert scenario.refresh_patient()["hbv_screen_status"] == "CLEARED"


def test_occult_hepatitis_b_risk_requires_documented_prophylaxis(api):
    """A negative surface antigen with a positive core antibody is
    `OCCULT_RISK`, and submission then demands `hbv_prophylaxis_documented`:
    the unflagged authorization is refused and a flagged replacement submits.

    PRD: "If the patient's `hbv_screen_status` is `OCCULT_RISK`, the
    authorization must carry `hbv_prophylaxis_documented` set to true, else
    `ERR_HBV_SCREEN_INCOMPLETE` (HTTP 422); this is the one place where the
    occult-risk posture bites, and prophylaxis is what clears it."

    Design: Corner/validations/occult_hepatitis_b_risk_requires_documented_prophylaxis_before_submission
    """
    fixtures.set_clock(constants.CLOCK_DEFAULT)
    scenario = fixtures.bootstrap_reference()
    fixtures.register_patient(scenario)
    fixtures.file_screen(scenario, "TB_IGRA", "NEGATIVE")
    fixtures.file_screen(scenario, "HBV_SURFACE_AG", "NEGATIVE")
    fixtures.file_screen(scenario, "HBV_CORE_AB", "POSITIVE")

    assert scenario.refresh_patient()["hbv_screen_status"] == "OCCULT_RISK"

    fixtures.open_planned_episode(scenario)
    without_prophylaxis = fixtures.open_authorization(
        scenario, 6, hbv_prophylaxis_documented=False
    )

    validate_error(
        api.submit_authorization(without_prophylaxis["id"], scenario.coordinator_headers),
        ApiErrorId.ERR_HBV_SCREEN_INCOMPLETE.value,
    )

    with_prophylaxis = fixtures.open_authorization(
        scenario, 6, hbv_prophylaxis_documented=True
    )
    submitted = get_success_data(
        api.submit_authorization(with_prophylaxis["id"], scenario.coordinator_headers)
    )
    assert submitted["status"] == "SUBMITTED"
    assert submitted["hbv_prophylaxis_documented"] is True
    assertions.assert_instant_equals(
        submitted["submitted_at"], constants.CLOCK_DEFAULT, "submitted_at"
    )

    superseded = scenario.refresh_authorization(without_prophylaxis["id"])
    assert superseded["status"] == "EXPIRED"
    assert superseded["submitted_at"] is None
    assert scenario.refresh_episode()["funding_state"] == "PENDING_AUTH"


def test_formulary_exception_must_be_attested_before_it_bypasses_step_therapy(api):
    """Requesting a formulary exception silences the step-therapy rejection but
    immediately raises the attestation one; once a credentialed rheumatologist
    signs it the same submission succeeds and still reports the unmet class.

    PRD: "And finally, when `formulary_exception_requested` is true,
    `exception_attested_by_clinician_id` must be non-null, else
    `ERR_FORMULARY_EXCEPTION_NOT_ATTESTED` (HTTP 422) — asking for a waiver
    nobody has signed fails on the attestation rather than on the step therapy
    it was meant to excuse."

    Design: Corner/validations/formulary_exception_must_be_attested_before_it_can_bypass_step_therapy
    """
    fixtures.set_clock(constants.CLOCK_DEFAULT)
    scenario = fixtures.bootstrap_reference(
        drug_payload=factories.create_drug_payload(
            name="Tocilizumab",
            molecule_class="IL6",
            route="IV",
            formulary_tier=4,
            acquisition_cost_cents=500_000,
            admin_time_minutes=150,
            monitoring_panel_type="CMP",
            monitoring_panel_interval_days=90,
        ),
        plan_payload=factories.meridian_plan_payload(
            step_therapy_classes_required=["TNFI"]
        ),
    )
    fixtures.register_patient(scenario)
    fixtures.open_planned_episode(scenario)
    fixtures.open_authorization(scenario, 6, formulary_exception_requested=True)

    unattested = scenario.refresh_authorization()
    assert unattested["formulary_exception_requested"] is True
    assert unattested["exception_attested_by_clinician_id"] is None

    validate_error(
        api.submit_authorization(scenario.authorization_id, scenario.coordinator_headers),
        ApiErrorId.ERR_FORMULARY_EXCEPTION_NOT_ATTESTED.value,
    )

    attested = get_success_data(
        api.attest_exception(scenario.authorization_id, scenario.rheum_headers)
    )
    assert attested["exception_attested_by_clinician_id"] == scenario.rheumatologist_id

    submitted = get_success_data(
        api.submit_authorization(scenario.authorization_id, scenario.coordinator_headers)
    )
    assert submitted["status"] == "SUBMITTED"
    assert submitted["unmet_step_therapy_classes"] == ["TNFI"], (
        "the waiver does not pretend the step was met"
    )

    rows, meta = assertions.validate_list(
        api.list_authorizations(
            scenario.admin_headers,
            {"exception_attested_by_clinician_id": scenario.rheumatologist_id},
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == scenario.authorization_id
    assert scenario.refresh_episode()["funding_state"] == "PENDING_AUTH"


# The five natural keys of §3.1, each with the row that claims it and a second
# body that reuses the very same literal while differing in every other field.
_NATURAL_KEY_CASES = {
    "patient_mrn": (
        "create_patient",
        {
            "mrn": "RH0001",
            "full_name": "Pat One",
            "date_of_birth": "1975-04-12",
            "diagnosis_code": "RA_SEROPOSITIVE",
            "registry_consent": True,
        },
        {
            "mrn": "RH0001",
            "full_name": "Someone Else",
            "date_of_birth": "1990-01-01",
            "diagnosis_code": "PSA",
            "registry_consent": False,
        },
    ),
    "clinician_npi": (
        "create_clinician",
        {
            "npi": "1234567893",
            "full_name": "Ada Rheum",
            "role_type": "RHEUMATOLOGIST",
            "can_attest_formulary_exception": True,
        },
        {
            "npi": "1234567893",
            "full_name": "Other Doc",
            "role_type": "NURSE",
        },
    ),
    "drug_name": (
        "create_drug",
        {
            "name": "Infliximab",
            "molecule_class": "TNFI",
            "route": "IV",
            "formulary_tier": 3,
            "acquisition_cost_cents": 250050,
            "admin_time_minutes": 150,
            "monitoring_panel_type": "CMP",
            "monitoring_panel_interval_days": 90,
        },
        {
            "name": "Infliximab",
            "molecule_class": "IL6",
            "route": "SC",
            "formulary_tier": 4,
            "acquisition_cost_cents": 1,
            "admin_time_minutes": 0,
            "monitoring_panel_type": "CBC",
            "monitoring_panel_interval_days": 180,
        },
    ),
    "payer_plan_name": (
        "create_payer_plan",
        {
            "name": "Meridian PPO",
            "pharmacy_benefit_enabled": True,
            "medical_benefit_enabled": True,
            "site_of_care_policy": "PREFER_AMBULATORY",
            "coinsurance_pct": 0.175,
            "deductible_remaining_cents": 100000,
            "medical_facility_fee_cents": 12500,
            "hospital_outpatient_multiplier": 1.40,
            "appeal_rounds_allowed": 2,
            "auth_validity_days": 180,
            "step_therapy_classes_required": [],
        },
        {
            "name": "Meridian PPO",
            "pharmacy_benefit_enabled": False,
            "medical_benefit_enabled": True,
            "site_of_care_policy": "SITE_NEUTRAL",
            "coinsurance_pct": 0.200,
            "deductible_remaining_cents": 0,
            "medical_facility_fee_cents": 0,
            "hospital_outpatient_multiplier": 1.00,
            "appeal_rounds_allowed": 0,
            "auth_validity_days": 90,
        },
    ),
    "chair_label": (
        "create_infusion_chair",
        {
            "label": "AIC-1",
            "site_type": "AMBULATORY_INFUSION_CENTER",
            "turnover_buffer_minutes": 30,
        },
        {
            "label": "AIC-1",
            "site_type": "HOSPITAL_OUTPATIENT",
            "turnover_buffer_minutes": 0,
        },
    ),
}


@pytest.mark.parametrize("natural_key", sorted(_NATURAL_KEY_CASES))
def test_every_reference_entity_enforces_its_own_unique_identifier(api, natural_key):
    """Each of the five reference collections rejects a second row that reuses
    its natural key, and no second row is written.

    PRD: "Five natural keys are unique within their own collection: a patient's
    `mrn`, a clinician's `npi`, a drug's `name`, a payer plan's `name` and a
    chair's `label`. A collision on any of the five is rejected with
    `ERR_DUPLICATE_IDENTIFIER` (HTTP 409)."

    Design: Corner/validations/every_reference_entity_enforces_its_own_unique_identifier
    """
    fixtures.set_clock(constants.CLOCK_DEFAULT)
    method_name, original, collision = _NATURAL_KEY_CASES[natural_key]
    create = getattr(api, method_name)

    established = get_success_data(create(original, fixtures.ADMIN), 201)

    validate_error(
        create(collision, fixtures.ADMIN),
        ApiErrorId.ERR_DUPLICATE_IDENTIFIER.value,
    )

    if natural_key == "patient_mrn":
        survivor = get_success_data(
            api.get_patient(established["id"], fixtures.ADMIN)
        )
        assertions.assert_patient(survivor)
        assert survivor["mrn"] == "RH0001"
        assert survivor["full_name"] == "Pat One"
        assert survivor["diagnosis_code"] == "RA_SEROPOSITIVE"
        assert survivor["registry_consent"] is True
        assert survivor["version"] == established["version"], (
            "the rejected body must not have partially overwritten the existing row"
        )


def test_a_differing_natural_key_on_the_same_collection_is_accepted(api):
    """The uniqueness rule is scoped to the key itself: a second chair whose
    `label` differs from the first is created normally.

    PRD: "Five natural keys are unique within their own collection: a patient's
    `mrn`, a clinician's `npi`, a drug's `name`, a payer plan's `name` and a
    chair's `label`. A collision on any of the five is rejected with
    `ERR_DUPLICATE_IDENTIFIER` (HTTP 409)."

    Design: Corner/validations/every_reference_entity_enforces_its_own_unique_identifier
    """
    fixtures.set_clock(constants.CLOCK_DEFAULT)
    get_success_data(
        api.create_infusion_chair(
            factories.create_infusion_chair_payload(
                label="AIC-1",
                site_type="AMBULATORY_INFUSION_CENTER",
                turnover_buffer_minutes=30,
            ),
            fixtures.ADMIN,
        ),
        201,
    )

    second = get_success_data(
        api.create_infusion_chair(
            factories.create_infusion_chair_payload(
                label="AIC-2",
                site_type="AMBULATORY_INFUSION_CENTER",
                turnover_buffer_minutes=30,
            ),
            fixtures.ADMIN,
        ),
        201,
    )
    assertions.assert_infusion_chair(second)
    assert second["label"] == "AIC-2"
    assert second["status"] == "OPEN"


def _pharmacy_only_plan() -> dict:
    return factories.meridian_plan_payload(
        name="Pharmacy Only HMO",
        pharmacy_benefit_enabled=True,
        medical_benefit_enabled=False,
        step_therapy_classes_required=[],
    )


def test_an_intravenous_drug_on_a_pharmacy_only_plan_has_no_benefit_channel(api):
    """An IV product may never bill the pharmacy benefit, so on a plan with the
    medical benefit switched off the episode cannot be opened at all — and the
    rejected create leaves the patient's revision unspent.

    PRD: "For an intravenous product the pharmacy benefit is never an option:
    `benefit_channel` is `MEDICAL` when the plan has the medical benefit
    enabled, and otherwise the same rejection applies."

    Design: Corner/validations/an_intravenous_drug_on_a_pharmacy_only_plan_has_no_benefit_channel
    """
    fixtures.set_clock(constants.CLOCK_DEFAULT)
    scenario = fixtures.bootstrap_reference(
        drug_payload=factories.infliximab_payload(),
        plan_payload=_pharmacy_only_plan(),
    )
    fixtures.register_patient(scenario)
    patient_version = scenario.patient["version"]

    validate_error(
        api.create_therapy_episode(
            factories.create_therapy_episode_payload(
                scenario.patient_id,
                scenario.drug_id,
                scenario.plan_id,
                patient_version,
            ),
            scenario.rheum_headers,
        ),
        ApiErrorId.ERR_NO_BENEFIT_CHANNEL_AVAILABLE.value,
    )
    assert scenario.refresh_patient()["version"] == patient_version


def test_a_subcutaneous_drug_on_the_same_pharmacy_only_plan_routes_pharmacy(api):
    """The switch that blocks the IV product routes the SC product cleanly: the
    same plan, the same patient and the same unspent `expected_patient_version`
    yield a `PHARMACY` / `SELF_ADMIN` episode.

    PRD: "For a subcutaneous product, `benefit_channel` is `PHARMACY` when the
    plan has the pharmacy benefit enabled; failing that it is `MEDICAL` when the
    plan has the medical benefit enabled; and if the plan enables neither, the
    episode cannot be opened at all and the request is refused with
    `ERR_NO_BENEFIT_CHANNEL_AVAILABLE` (HTTP 422)."

    Design: Corner/validations/an_intravenous_drug_on_a_pharmacy_only_plan_has_no_benefit_channel
    """
    fixtures.set_clock(constants.CLOCK_DEFAULT)
    scenario = fixtures.bootstrap_reference(
        drug_payload=factories.infliximab_payload(),
        plan_payload=_pharmacy_only_plan(),
    )
    subcutaneous = fixtures.create_drug(None, factories.adalimumab_payload())
    fixtures.register_patient(scenario)
    patient_version = scenario.patient["version"]

    validate_error(
        api.create_therapy_episode(
            factories.create_therapy_episode_payload(
                scenario.patient_id,
                scenario.drug_id,
                scenario.plan_id,
                patient_version,
            ),
            scenario.rheum_headers,
        ),
        ApiErrorId.ERR_NO_BENEFIT_CHANNEL_AVAILABLE.value,
    )

    episode = get_success_data(
        api.create_therapy_episode(
            factories.create_therapy_episode_payload(
                scenario.patient_id,
                subcutaneous["id"],
                scenario.plan_id,
                patient_version,
            ),
            scenario.rheum_headers,
        ),
        201,
    )
    assertions.assert_therapy_episode(episode)
    assert episode["benefit_channel"] == "PHARMACY"
    assert episode["site_of_care"] == "SELF_ADMIN"
    assert episode["routing_frozen"] is True
    assert episode["self_injection_training_status"] == "PENDING"
    assert episode["line_of_therapy"] == 1


@pytest.mark.parametrize(
    "scheduled_start",
    [
        constants.instant(2026, 7, 31, 9, 0, 0),
        constants.instant(2027, 2, 1, 9, 0, 0),
    ],
    ids=["one_day_before_valid_from", "four_days_after_valid_through"],
)
def test_an_appointment_outside_the_authorization_window_is_refused(api, scheduled_start):
    """A start before `valid_from` and a start after `valid_through` both fall
    outside the only approved authorization's coverage window, and neither
    reserves a unit.

    PRD: "Second, the pool is narrowed to members whose coverage window contains
    the requested `scheduled_start` — that is, whose `valid_from` is at or
    before it and whose `valid_through` is at or after it, the window being
    inclusive at both ends; if nothing survives that narrowing, the request is
    refused with `ERR_APPOINTMENT_OUTSIDE_AUTH_WINDOW` (HTTP 409)."

    Design: Corner/validations/an_appointment_must_fall_inside_the_approved_authorization_window
    """
    fixtures.set_clock(constants.CLOCK_DEFAULT)
    scenario = fixtures.active_episode(requested_units=6)

    window = scenario.refresh_authorization()
    assertions.assert_instant_equals(
        window["valid_from"], constants.instant(2026, 8, 1), "valid_from"
    )
    assertions.assert_instant_equals(
        window["valid_through"], constants.instant(2027, 1, 28), "valid_through"
    )

    validate_error(
        api.create_infusion_appointment(
            factories.create_appointment_payload(
                scenario.episode_id, scenario.chair_id, scheduled_start=scheduled_start
            ),
            scenario.nurse_headers,
        ),
        ApiErrorId.ERR_APPOINTMENT_OUTSIDE_AUTH_WINDOW.value,
    )
    assertions.assert_unit_ledger(scenario.refresh_authorization(), 0, 0, 6)


def test_an_appointment_exactly_on_valid_through_is_inside_the_window(api):
    """The window is inclusive at both ends, so a dose starting at the exact
    `valid_through` instant schedules and reserves against that authorization.

    PRD: "Second, the pool is narrowed to members whose coverage window contains
    the requested `scheduled_start` — that is, whose `valid_from` is at or
    before it and whose `valid_through` is at or after it, the window being
    inclusive at both ends; if nothing survives that narrowing, the request is
    refused with `ERR_APPOINTMENT_OUTSIDE_AUTH_WINDOW` (HTTP 409)."

    Design: Corner/validations/an_appointment_must_fall_inside_the_approved_authorization_window
    """
    fixtures.set_clock(constants.CLOCK_DEFAULT)
    scenario = fixtures.active_episode(requested_units=6)
    boundary_start = constants.instant(2027, 1, 28)

    appointment = get_success_data(
        api.create_infusion_appointment(
            factories.create_appointment_payload(
                scenario.episode_id, scenario.chair_id, scheduled_start=boundary_start
            ),
            scenario.nurse_headers,
        ),
        201,
    )
    assertions.assert_infusion_appointment(appointment)
    assertions.assert_instant_equals(
        appointment["scheduled_start"], boundary_start, "scheduled_start"
    )
    assertions.assert_instant_equals(
        appointment["scheduled_end"],
        constants.instant(2027, 1, 28, 2, 30, 0),
        "scheduled_end",
    )
    assert appointment["reserved_authorization_id"] == scenario.authorization_id
    assert appointment["dose_sequence"] == 1
    assert appointment["dose_cost_share_cents"] == 138759
    assert appointment["assistance_applied_cents"] == 0
    assert appointment["patient_out_of_pocket_cents"] == 138759
    assert appointment["reserved_enrollment_id"] is None
    assertions.assert_unit_ledger(scenario.refresh_authorization(), 1, 0, 5)


def test_das28_scoring_without_an_acute_phase_reactant_is_rejected(api):
    """`DAS28_CRP` cannot be computed without `crp_mg_dl`: the request is
    refused, the visit stays `CHECKED_IN` and unscored, and supplying the
    reactant scores it.

    PRD: "Under `DAS28_CRP`, `crp_mg_dl` is mandatory; a request that selects
    this instrument without it is refused with
    `ERR_ACUTE_PHASE_REACTANT_MISSING` (HTTP 422)."

    Design: Corner/validations/das28_scoring_without_an_acute_phase_reactant_is_rejected
    """
    fixtures.set_clock(constants.CLOCK_DEFAULT)
    scenario = fixtures.visit_ready_practice()
    checked_in = fixtures.checked_in_visit(
        scenario, visit_datetime=constants.instant(2026, 8, 1, 9, 0, 0), visit_type="FOLLOW_UP"
    )
    checked_in_version = checked_in["version"]

    without_reactant = factories.score_visit_das28_payload()
    without_reactant.pop("crp_mg_dl")
    validate_error(
        api.score_visit(scenario.visit_id, without_reactant, scenario.rheum_headers),
        ApiErrorId.ERR_ACUTE_PHASE_REACTANT_MISSING.value,
    )

    untouched = get_success_data(api.get_visit(scenario.visit_id, scenario.admin_headers))
    assert untouched["status"] == "CHECKED_IN"
    assert untouched["activity_score"] is None
    assert untouched["scored_at"] is None
    assert untouched["version"] == checked_in_version

    scored = get_success_data(
        api.score_visit(
            scenario.visit_id,
            factories.score_visit_das28_payload(crp_mg_dl=2.5),
            scenario.rheum_headers,
        )
    )
    assert scored["status"] == "SCORED"
    assert scored["activity_score"] == 3.62
    assert scored["activity_category"] == "MODERATE"
    assert scored["escalation_recommendation"] == "OPTIMIZE_CURRENT"

    patient = scenario.refresh_patient()
    assert patient["target_status"] == "NOT_AT_TARGET"
    assert patient["latest_activity_score"] == 3.62
