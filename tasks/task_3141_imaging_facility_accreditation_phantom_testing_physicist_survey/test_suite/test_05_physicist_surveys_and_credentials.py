"""Physicist survey lifecycle, credential cascades and conserved quantities."""
from test_helpers import (
    TEST_USERS,
    api_client,
    read_facility,
    read_qualification,
    read_survey,
    read_unit,
    setup_imaging_facility,
    validate_success,
)

REVIEWER = TEST_USERS["accreditation_body_headers"]
READER = TEST_USERS["any_headers"]


def _schedule(scenario, survey_type, scheduled_at):
    return validate_success(
        api_client.create_physicist_survey(
            {
                "facility_id": scenario.facility_id,
                "physicist_qualification_id": scenario.physicist_qualification_id,
                "survey_type": survey_type,
                "scheduled_at": scheduled_at,
                "reference_entrance_dose_mgy": 2.0,
                "unit_id": scenario.unit_id,
            },
            scenario.physicist,
        ),
        201,
    )


def _submit(scenario, survey_id, measured, performed_at, shielding="PASS"):
    return validate_success(
        api_client.submit_physicist_survey(
            survey_id,
            {
                "performed_at": performed_at,
                "measured_entrance_dose_mgy": measured,
                "shielding_verdict": shielding,
            },
            scenario.physicist,
        ),
        200,
    )


# ══════════════════════════════════════════════════════════════════════════
# The corrective-required recovery loop
# ══════════════════════════════════════════════════════════════════════════

def test_a_corrective_required_survey_resubmits_into_the_accepted_target(api):
    """PRD §3.5: "Correcting the problem means resubmitting. The physicist
    supplies a fresh `measured_entrance_dose_mgy` and `shielding_verdict`; the
    survey must currently be `CORRECTIVE_REQUIRED`; `shielding_verdict` must
    now be `PASS`; the recomputed absolute deviation must be at most `10.0`
    percent"
    PRD §3.5: "A successful resubmission debits `100000` from the facility's
    `registry_credit_cents`, recomputes `dose_deviation_pct` by the dose
    deviation rule, resets `rejection_code` to `NONE`, and moves the survey to
    `RESUBMITTED`. A resubmitted survey can then be accepted under the same
    shielding, deviation and qualification conditions as a first submission"

    Design: Difficulty/non_linear_state_machine/physicist_survey_corrective_required_recovery_loop
    """
    scenario = setup_imaging_facility()
    survey = _schedule(scenario, "POST_REPAIR", "2026-09-20T00:00:00Z")
    # measured 2.4 against reference 2.0 gives +20.0 %, which exceeds the limit.
    _submit(scenario, survey["id"], 2.4, "2026-09-20T00:00:00Z")
    corrective = validate_success(
        api_client.accept_physicist_survey(survey["id"], {}, REVIEWER), 200
    )
    assert corrective["survey_status"] == "CORRECTIVE_REQUIRED"
    assert corrective["rejection_code"] == "DOSE_OUT_OF_RANGE"

    resubmitted = validate_success(
        api_client.resubmit_physicist_survey(
            survey["id"],
            {"measured_entrance_dose_mgy": 2.1, "shielding_verdict": "PASS"},
            scenario.physicist,
        ),
        200,
    )
    assert resubmitted["survey_status"] == "RESUBMITTED"
    assert resubmitted["dose_deviation_pct"] == 5.0
    assert resubmitted["rejection_code"] == "NONE"

    accepted = validate_success(
        api_client.accept_physicist_survey(survey["id"], {}, REVIEWER), 200
    )
    assert accepted["survey_status"] == "ACCEPTED"


def test_the_recovery_resubmission_debits_the_resubmission_fee_once(api):
    """PRD §3.5: "the facility's `registry_credit_cents` must hold at least
    `100000`, failing which the request is refused with
    `ERR_INSUFFICIENT_REGISTRY_CREDIT`. A successful resubmission debits
    `100000` from the facility's `registry_credit_cents`"
    PRD §2.7: "resubmitting a corrective-required physicist survey debits
    `100000`"

    Design: Difficulty/non_linear_state_machine/physicist_survey_corrective_required_recovery_loop
    """
    scenario = setup_imaging_facility()
    survey = _schedule(scenario, "POST_REPAIR", "2026-09-20T00:00:00Z")
    _submit(scenario, survey["id"], 2.4, "2026-09-20T00:00:00Z")
    validate_success(api_client.accept_physicist_survey(survey["id"], {}, REVIEWER), 200)

    validate_success(
        api_client.resubmit_physicist_survey(
            survey["id"],
            {"measured_entrance_dose_mgy": 2.1, "shielding_verdict": "PASS"},
            scenario.physicist,
        ),
        200,
    )
    assert read_facility(scenario.facility_id)["registry_credit_cents"] == 500000 - 100000


# ══════════════════════════════════════════════════════════════════════════
# Accepted-survey consequences on the credential and the unit
# ══════════════════════════════════════════════════════════════════════════

def test_accepting_a_survey_cascades_onto_the_named_qualification_and_unit(api):
    """PRD §3.5: "the named qualification's `survey_count` is recomputed as
    the number of surveys naming it whose status is not `REJECTED`; if the
    survey names a `unit_id`, every equipment item of that unit has its
    `performance_verdict` set to `PASS` and that unit's `last_survey_at` is
    set to the survey's `performed_at`"
    PRD §3.5: "the named qualification is promoted back to `VERIFIED` when
    the absolute deviation is at most `8.0` percent"

    Design: Corner/complexity_layers/survey_acceptance_credential_status_cascade_reaches_the_named_qualification
    """
    scenario = setup_imaging_facility()
    survey = _schedule(scenario, "POST_REPAIR", "2026-09-20T00:00:00Z")
    _submit(scenario, survey["id"], 2.15, "2026-09-20T00:00:00Z")

    accepted = validate_success(
        api_client.accept_physicist_survey(survey["id"], {}, REVIEWER), 200
    )
    assert accepted["survey_status"] == "ACCEPTED"
    assert accepted["dose_deviation_pct"] == 7.5

    # The baseline ANNUAL survey and this POST_REPAIR survey both name the
    # credential and neither is rejected.
    qualification = read_qualification(scenario.physicist_qualification_id)
    assert qualification["survey_count"] == 2
    assert qualification["credential_status"] == "VERIFIED"
    assert qualification["qualification_verified_at"] is not None

    unit = read_unit(scenario.unit_id)
    assert unit["last_survey_at"] == "2026-09-20T00:00:00Z"
    assert read_facility(scenario.facility_id)["accreditation_currency"] == "CURRENT"


# ══════════════════════════════════════════════════════════════════════════
# Conserved quantities
# ══════════════════════════════════════════════════════════════════════════

def test_survey_acceptance_conserves_the_registry_balance(api):
    """PRD §2.7: "It can never be negative."
    PRD §2.7: "Individual registry records also expose a per-record
    `registry_fee_cents` value which is `0` while the record is staged,
    becomes `2500` once it is accepted into the registry, and returns to `0`
    if it is later rejected."

    Design: Difficulty/compensating_invariant/survey_acceptance_and_rejection_conserve_certificates_and_credit_once
    """
    scenario = setup_imaging_facility()
    balance_before = read_facility(scenario.facility_id)["registry_credit_cents"]
    survey = _schedule(scenario, "POST_REPAIR", "2026-09-20T00:00:00Z")
    _submit(scenario, survey["id"], 2.15, "2026-09-20T00:00:00Z")
    accepted = validate_success(
        api_client.accept_physicist_survey(survey["id"], {}, REVIEWER), 200
    )

    assert accepted["survey_status"] == "ACCEPTED"
    assert accepted["dose_deviation_pct"] == 7.5
    assert read_facility(scenario.facility_id)["registry_credit_cents"] == balance_before


def test_the_baseline_survey_is_not_counted_twice(api):
    """PRD §3.5: "the named qualification's `survey_count` is recomputed as
    the number of surveys naming it whose status is not `REJECTED`"

    Design: Difficulty/compensating_invariant/survey_acceptance_and_rejection_conserve_certificates_and_credit_once
    """
    scenario = setup_imaging_facility()
    baseline_count = read_qualification(scenario.physicist_qualification_id)["survey_count"]
    assert baseline_count == 1

    survey = _schedule(scenario, "POST_REPAIR", "2026-09-20T00:00:00Z")
    _submit(scenario, survey["id"], 2.15, "2026-09-20T00:00:00Z")
    validate_success(api_client.accept_physicist_survey(survey["id"], {}, REVIEWER), 200)

    assert read_qualification(scenario.physicist_qualification_id)["survey_count"] == 2
    # The baseline survey row is untouched.
    baseline = read_survey(scenario.survey_id)
    assert baseline["survey_status"] == "ACCEPTED"
    assert read_unit(scenario.unit_id)["last_survey_at"] == "2026-09-20T00:00:00Z"