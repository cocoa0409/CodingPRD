"""Rejection-precedence corners: which of two simultaneous violations wins.

Every test in this module stages *both* offending conditions at once and pins
the single error the PRD's ordering rules say must surface, then repairs the
winner and shows the loser emerging underneath it. The orderings exercised
here come from §2.10's global ladder and its two clarifications, from §3.4's
seven ordered activation gates, from §3.7's scheduling sequence and from
§3.9's consent-before-emptiness rule for the quality report.
"""
import pytest

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    validate_error,
)

from test_helpers import ApiErrorId, assertions, constants, factories, fixtures


def test_invalid_request_shape_outranks_the_body_reference_lookup(api):
    """A malformed `therapy_start_at` and an unknown `patient_id` in the same
    body answer with the shape error, not the reference error; repairing only
    the timestamp exposes the 404 underneath.

    PRD: "First, path-segment existence (rules 5 through 11) is settled before
    the payload is validated at all, so a malformed body against a
    non-existent parent reports the 404 rather than the 422; body-borne
    references (rules 13 through 15) are resolved after the payload has been
    shape-checked, because a reference cannot be resolved until it is known to
    be a string."

    Design: Corner/validations/invalid_request_shape_outranks_the_body_reference_lookup_on_episode_create
    """
    fixtures.set_clock(constants.CLOCK_DEFAULT)
    scenario = fixtures.visit_ready_practice()
    patient_version = scenario.patient["version"]

    both_broken = factories.create_therapy_episode_payload(
        NON_EXISTENT_UUID,
        scenario.drug_id,
        scenario.plan_id,
        patient_version,
        therapy_start_at="not-a-timestamp",
    )
    validate_error(
        api.create_therapy_episode(both_broken, scenario.rheum_headers),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )

    shape_repaired = factories.create_therapy_episode_payload(
        NON_EXISTENT_UUID,
        scenario.drug_id,
        scenario.plan_id,
        patient_version,
        therapy_start_at=constants.CLOCK_DEFAULT,
    )
    validate_error(
        api.create_therapy_episode(shape_repaired, scenario.rheum_headers),
        ApiErrorId.ERR_REFERENCE_NOT_FOUND.value,
    )

    rows, meta = assertions.validate_list(
        api.list_therapy_episodes(
            scenario.admin_headers, {"patient_id": scenario.patient_id}
        )
    )
    assert rows == [], "neither rejected create may leave an episode behind"
    assert meta["total_count"] == 0
    assert scenario.refresh_patient()["version"] == patient_version, (
        "a rejected create must not spend the patient's revision"
    )


def test_body_reference_lookup_outranks_the_stale_patient_version_check(api):
    """An unknown `drug_id` carried alongside a stale `expected_patient_version`
    answers with the reference 404; repairing the reference exposes the 412,
    and only a live token creates the episode.

    PRD: "The server evaluates in the following order and stops at the first
    failure."

    Design: Corner/validations/body_reference_lookup_outranks_the_stale_patient_version_check
    """
    fixtures.set_clock(constants.CLOCK_DEFAULT)
    scenario = fixtures.visit_ready_practice()
    live_version = scenario.patient_version
    stale_version = live_version - 1

    unknown_drug_and_stale_token = factories.create_therapy_episode_payload(
        scenario.patient_id,
        NON_EXISTENT_UUID,
        scenario.plan_id,
        stale_version,
    )
    validate_error(
        api.create_therapy_episode(unknown_drug_and_stale_token, scenario.rheum_headers),
        ApiErrorId.ERR_REFERENCE_NOT_FOUND.value,
    )

    stale_token_only = factories.create_therapy_episode_payload(
        scenario.patient_id,
        scenario.drug_id,
        scenario.plan_id,
        stale_version,
    )
    validate_error(
        api.create_therapy_episode(stale_token_only, scenario.rheum_headers),
        ApiErrorId.ERR_STALE_PATIENT_VERSION.value,
    )

    clean = factories.create_therapy_episode_payload(
        scenario.patient_id,
        scenario.drug_id,
        scenario.plan_id,
        live_version,
    )
    episode = get_success_data(
        api.create_therapy_episode(clean, scenario.rheum_headers), 201
    )
    assertions.assert_therapy_episode(episode)
    assert episode["therapy_state"] == "PLANNED"
    assert episode["funding_state"] == "UNFUNDED"

    patient = scenario.refresh_patient()
    assert patient["version"] == live_version + 1, (
        "only the accepted create may spend the patient's revision"
    )
    assert patient["active_episode_count"] == 0


@pytest.mark.parametrize("operation", ["submit", "determination"])
def test_approved_authorization_refuses_submit_and_determination(api, operation):
    """From `APPROVED`, submit (which wants `DRAFT` or `DENIED`) and
    determination (which wants `SUBMITTED`) both answer
    `ERR_AUTHORIZATION_STATE_INVALID`, and the approved fields survive intact.

    PRD: "`ERR_AUTHORIZATION_STATE_INVALID` — submission or exception signing
    attempted on an authorization that is neither `DRAFT` nor `DENIED`, or
    determination attempted on an authorization that is not `SUBMITTED`."

    Design: Corner/validations/submit_and_determination_against_an_approved_authorization_return_state_invalid
    """
    fixtures.set_clock(constants.CLOCK_DEFAULT)
    scenario = fixtures.planned_episode()
    fixtures.approved_authorization(scenario, 6)

    approved = scenario.refresh_authorization()
    assert approved["status"] == "APPROVED"
    approved_version = approved["version"]

    if operation == "submit":
        response = api.submit_authorization(
            scenario.authorization_id, scenario.coordinator_headers
        )
    else:
        response = api.determine_authorization(
            scenario.authorization_id,
            factories.deny_determination_payload(decision_reason="second look"),
            scenario.reviewer_headers,
        )
    validate_error(response, ApiErrorId.ERR_AUTHORIZATION_STATE_INVALID.value)

    after = scenario.refresh_authorization()
    assert after["status"] == "APPROVED"
    assert after["approved_units"] == 6
    assert after["units_remaining"] == 6
    assert after["appeal_round"] == 0
    assert after["version"] == approved_version, (
        "a rejected transition must not bump the authorization's revision"
    )
    assertions.assert_unit_ledger(after, 0, 0, 6)
    assert scenario.refresh_episode()["funding_state"] == "AUTHORIZED"


def test_funding_check_outranks_the_tuberculosis_screening_check(api):
    """An unscreened, unfunded `PLANNED` episode violates the funding gate and
    the TB gate at once: activation answers `ERR_FUNDING_NOT_AUTHORIZED`, and
    only once the payer approves does the same call reach the TB posture.

    PRD: "Seven conditions must hold, and they are checked in this order."

    Design: Corner/validations/funding_check_outranks_the_tuberculosis_screening_check_on_activate
    """
    fixtures.set_clock(constants.CLOCK_DEFAULT)
    scenario = fixtures.visit_ready_practice()
    fixtures.open_planned_episode(scenario)

    unscreened = scenario.refresh_patient()
    assert unscreened["tb_screen_status"] == "MISSING"
    assert unscreened["hbv_screen_status"] == "INCOMPLETE"
    assert scenario.refresh_episode()["funding_state"] == "UNFUNDED"

    validate_error(
        api.activate_therapy_episode(scenario.episode_id, scenario.rheum_headers),
        ApiErrorId.ERR_FUNDING_NOT_AUTHORIZED.value,
    )

    fixtures.approved_authorization(scenario, 6)
    assert scenario.refresh_episode()["funding_state"] == "AUTHORIZED"

    validate_error(
        api.activate_therapy_episode(scenario.episode_id, scenario.rheum_headers),
        ApiErrorId.ERR_TB_SCREEN_NOT_CLEARED.value,
    )

    patient = scenario.refresh_patient()
    assert patient["tb_screen_status"] == "MISSING"
    assert patient["hbv_screen_status"] == "INCOMPLETE"
    assert patient["active_episode_count"] == 0
    episode = scenario.refresh_episode()
    assert episode["therapy_state"] == "PLANNED"
    assert episode["funding_state"] == "AUTHORIZED"


def test_monitoring_currency_outranks_self_injection_training(api):
    """A screened, funded subcutaneous episode with no panel on file violates
    the monitoring gate and the training gate together: activation answers
    `ERR_MONITORING_LAB_OVERDUE`, then `ERR_SELF_INJECTION_TRAINING_INCOMPLETE`
    once the CBC is filed, and only `PASSED` training lets it activate.

    PRD: "Seven conditions must hold, and they are checked in this order."

    Design: Corner/validations/monitoring_currency_outranks_self_injection_training_on_a_subcutaneous_activation
    """
    fixtures.set_clock(constants.CLOCK_DEFAULT)
    scenario = fixtures.planned_episode(drug_payload=factories.adalimumab_payload())

    routed = scenario.refresh_episode()
    assert routed["benefit_channel"] == "PHARMACY"
    assert routed["site_of_care"] == "SELF_ADMIN"
    assert routed["self_injection_training_status"] == "PENDING"
    assert routed["monitoring_status"] == "OVERDUE"

    fixtures.approved_authorization(scenario, 6)
    assert scenario.refresh_episode()["funding_state"] == "AUTHORIZED"

    validate_error(
        api.activate_therapy_episode(scenario.episode_id, scenario.rheum_headers),
        ApiErrorId.ERR_MONITORING_LAB_OVERDUE.value,
    )

    fixtures.file_monitoring_lab(
        scenario,
        panel_type="CBC",
        collected_at=constants.instant(2026, 7, 25),
        wbc_k_ul=6.0,
        neutrophil_k_ul=3.20,
    )
    assert scenario.refresh_episode()["monitoring_status"] == "CURRENT"

    validate_error(
        api.activate_therapy_episode(scenario.episode_id, scenario.rheum_headers),
        ApiErrorId.ERR_SELF_INJECTION_TRAINING_INCOMPLETE.value,
    )

    get_success_data(
        api.record_training(
            scenario.episode_id,
            factories.record_training_payload("PASSED"),
            scenario.nurse_headers,
        )
    )
    trained = scenario.refresh_episode()
    assert trained["self_injection_training_status"] == "PASSED"
    assert trained["self_injection_training_attempts"] == 1

    activated = get_success_data(
        api.activate_therapy_episode(scenario.episode_id, scenario.rheum_headers)
    )
    assert activated["therapy_state"] == "ACTIVE"
    assert scenario.refresh_patient()["active_episode_count"] == 1


def test_active_hepatitis_b_infection_outranks_the_overdue_monitoring_panel(api):
    """A current `POSITIVE` surface antigen makes `hbv_screen_status`
    `ACTIVE_INFECTION`, and that contraindication answers before the episode's
    `OVERDUE` monitoring status — filing the panel repairs the later gate but
    the same rejection stands.

    PRD: "Seven conditions must hold, and they are checked in this order."

    Design: Corner/validations/active_hepatitis_b_infection_outranks_the_overdue_monitoring_panel_on_activate
    """
    fixtures.set_clock(constants.CLOCK_DEFAULT)
    scenario = fixtures.bootstrap_reference()
    fixtures.register_patient(scenario)
    fixtures.file_screen(scenario, "TB_IGRA", "NEGATIVE")
    fixtures.file_screen(scenario, "HBV_SURFACE_AG", "POSITIVE")

    patient = scenario.refresh_patient()
    assert patient["tb_screen_status"] == "CLEARED"
    assert patient["hbv_screen_status"] == "ACTIVE_INFECTION"

    fixtures.open_planned_episode(scenario)
    fixtures.approved_authorization(scenario, 6)
    staged = scenario.refresh_episode()
    assert staged["funding_state"] == "AUTHORIZED"
    assert staged["monitoring_status"] == "OVERDUE"

    validate_error(
        api.activate_therapy_episode(scenario.episode_id, scenario.rheum_headers),
        ApiErrorId.ERR_HBV_ACTIVE_INFECTION_CONTRAINDICATED.value,
    )

    fixtures.file_monitoring_lab(
        scenario,
        panel_type="CMP",
        collected_at=constants.instant(2026, 7, 25),
        alt_u_l=30.0,
        neutrophil_k_ul=3.20,
    )
    assert scenario.refresh_episode()["monitoring_status"] == "CURRENT"

    validate_error(
        api.activate_therapy_episode(scenario.episode_id, scenario.rheum_headers),
        ApiErrorId.ERR_HBV_ACTIVE_INFECTION_CONTRAINDICATED.value,
    )

    episode = scenario.refresh_episode()
    assert episode["monitoring_status"] == "CURRENT"
    assert episode["therapy_state"] == "PLANNED"
    assert scenario.refresh_patient()["active_episode_count"] == 0


def test_registry_consent_outranks_the_empty_reporting_window(api):
    """Two patients with no visits at all ask for the same window: the
    non-consenting one answers `ERR_REGISTRY_CONSENT_MISSING` because the
    consent check runs before the emptiness test, and the consenting one
    answers `ERR_QUALITY_PERIOD_NO_VISITS`.

    PRD: "If the window contains no qualifying visit the report is refused with
    `ERR_QUALITY_PERIOD_NO_VISITS` (HTTP 422), and the consent check precedes
    it."

    Design: Corner/validations/registry_consent_outranks_the_empty_reporting_window_on_the_quality_report
    """
    fixtures.set_clock(constants.CLOCK_DEFAULT)
    non_consenting = fixtures.register_patient(
        None,
        full_name="Pat One",
        date_of_birth="1975-04-12",
        diagnosis_code="RA_SEROPOSITIVE",
        registry_consent=False,
    )
    consenting = fixtures.register_patient(
        None,
        full_name="Pat Two",
        date_of_birth="1980-09-30",
        diagnosis_code="PSA",
        registry_consent=True,
    )
    window = {
        "period_start": constants.instant(2026, 1, 1),
        "period_end": constants.instant(2026, 9, 1),
    }

    consent_response = api.get_quality_report(
        non_consenting["id"], fixtures.ADMIN, window
    )
    validate_error(consent_response, ApiErrorId.ERR_REGISTRY_CONSENT_MISSING.value)

    empty_response = api.get_quality_report(consenting["id"], fixtures.ADMIN, window)
    validate_error(empty_response, ApiErrorId.ERR_QUALITY_PERIOD_NO_VISITS.value)

    for response in (consent_response, empty_response):
        body = response.json()
        assert body["response_type"] == "error"
        assert isinstance(body["data"]["message"], str) and body["data"]["message"]


def test_episode_state_outranks_the_chair_site_match(api):
    """A `PLANNED` episode aimed at a wrongly-sited chair answers
    `ERR_EPISODE_NOT_ACTIVE`, the `ACTIVE` ambulatory-routed episode answers
    `ERR_SITE_OF_CARE_MISMATCH` for the hospital chair, and the same episode
    schedules cleanly in the ambulatory chair.

    PRD: "Scheduling is the most heavily gated write in the API, and its checks
    run in this sequence."

    Design: Corner/validations/episode_state_outranks_the_chair_site_match_and_the_site_match_outranks_nothing
    """
    fixtures.set_clock(constants.CLOCK_DEFAULT)
    scenario = fixtures.active_episode()
    hospital_chair = fixtures.create_chair(
        None,
        factories.create_infusion_chair_payload(
            label="HOSP-1",
            site_type="HOSPITAL_OUTPATIENT",
            turnover_buffer_minutes=0,
        ),
    )

    routed = scenario.refresh_episode()
    assert routed["site_of_care"] == "AMBULATORY_INFUSION_CENTER"
    assert routed["benefit_channel"] == "MEDICAL"
    assert routed["therapy_state"] == "ACTIVE"

    second = fixtures.Scenario(
        rheumatologist_id=scenario.rheumatologist_id,
        nurse_id=scenario.nurse_id,
        drug_id=scenario.drug_id,
        plan_id=scenario.plan_id,
        chair_id=scenario.chair_id,
    )
    fixtures.register_patient(second)
    fixtures.open_planned_episode(second)

    start = constants.instant(2026, 8, 3, 9, 0, 0)

    validate_error(
        api.create_infusion_appointment(
            factories.create_appointment_payload(
                second.episode_id, hospital_chair["id"], scheduled_start=start
            ),
            scenario.nurse_headers,
        ),
        ApiErrorId.ERR_EPISODE_NOT_ACTIVE.value,
    )

    validate_error(
        api.create_infusion_appointment(
            factories.create_appointment_payload(
                scenario.episode_id, hospital_chair["id"], scheduled_start=start
            ),
            scenario.nurse_headers,
        ),
        ApiErrorId.ERR_SITE_OF_CARE_MISMATCH.value,
    )

    appointment = get_success_data(
        api.create_infusion_appointment(
            factories.create_appointment_payload(
                scenario.episode_id, scenario.chair_id, scheduled_start=start
            ),
            scenario.nurse_headers,
        ),
        201,
    )
    assertions.assert_infusion_appointment(appointment)
    assert appointment["chair_id"] == scenario.chair_id
    assertions.assert_instant_equals(
        appointment["scheduled_end"],
        constants.instant(2026, 8, 3, 11, 30, 0),
        "scheduled_end",
    )
    assert appointment["dose_sequence"] == 1

    rows, meta = assertions.validate_list(
        api.list_infusion_appointments(
            scenario.admin_headers, {"chair_id": hospital_chair["id"]}
        )
    )
    assert rows == [], "neither rejection may write a row against the hospital chair"
    assert meta["total_count"] == 0
    assertions.assert_unit_ledger(scenario.refresh_authorization(), 1, 0, 5)
