"""Composite setup helpers for multi-step test prerequisites.

Every helper drives a freshly-started, empty database into the state its
tests need, using only public endpoints. Setup steps use
`get_success_data()` so a broken precondition surfaces as a clear
"Setup failed" message rather than a confusing assertion failure.

The canonical accreditation scenario is:

    facility (ENROLLED, credit 500000)
      └── modality unit CT-1 (ENROLLED)
            └── equipment item SN-CT-0001 (ACTIVE, verdict PASS)
      └── TECHNOLOGIST qualification (VERIFIED)
      └── MEDICAL_PHYSICIST qualification (VERIFIED)
      └── accreditation cycle #1 (ACTIVE)
      └── physicist survey (ACCEPTED, deviation 7.5%)

`setup_imaging_facility()` builds exactly that and returns a `Scenario`
namespace holding the identifiers, headers and the entities themselves.

Header threading: the PRD states that "`FacilityAdmin` is the identity of an
accredited facility itself" and that "The API additionally tolerates an
operator principal whose `X-User-ID` is not equal to any facility's `id` for
cross-facility administrative plumbing", so the setup calls made before an
entity exists use the shared facility-admin constant. Once a facility is
created, `Scenario.admin` carries headers built from that facility's own `id`,
and every `MedicalPhysicist` call uses headers built from the acting
qualification's `id`, because a survey is judged against the qualification
that signs it.
"""
from dataclasses import dataclass, field
from typing import Any, Dict

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (DEFAULT_CLOCK, MODALITY_COMPARISON,
                        REGISTRY_FEE_CENTS, RENEWAL_FEE_CENTS,
                        SCENARIO_CLOCK, SURVEY_RESUBMISSION_FEE_CENTS,
                        TEST_DEFAULTS, days_after, iso)
from .factories import (create_accreditation_cycle_payload,
                        create_clinical_image_submission_payload,
                        create_clinical_resubmission_payload,
                        create_clock_payload, create_dose_registry_record_payload,
                        create_equipment_payload, create_facility_payload,
                        create_modality_unit_payload,
                        create_phantom_score_payload, create_phantom_test_payload,
                        create_physicist_qualification_payload,
                        create_physicist_survey_payload,
                        create_qualification_payload,
                        create_registry_credit_payload,
                        create_review_payload, create_survey_submission_payload,
                        create_verify_payload,
                        create_version_payload, create_versionless_payload)
from .test_users import (TEST_USERS, make_facility_admin_headers,
                         make_medical_physicist_headers)

D = TEST_DEFAULTS
ANY = TEST_USERS["any_headers"]


# ══════════════════════════════════════════════════════════════════════════
# Scenario namespace
# ══════════════════════════════════════════════════════════════════════════

@dataclass
class Scenario:
    """Identifiers, headers and entities of the canonical setup."""

    facility: Dict[str, Any]
    unit: Dict[str, Any]
    equipment: Dict[str, Any]
    cycle: Dict[str, Any]
    tech_qualification: Dict[str, Any]
    physicist_qualification: Dict[str, Any]
    survey: Dict[str, Any]
    admin: Dict[str, str]
    physicist: Dict[str, str]
    extras: Dict[str, Any] = field(default_factory=dict)

    # Convenience identifiers
    @property
    def facility_id(self) -> str:
        return self.facility["id"]

    @property
    def unit_id(self) -> str:
        return self.unit["id"]

    @property
    def equipment_id(self) -> str:
        return self.equipment["id"]

    @property
    def cycle_id(self) -> str:
        return self.cycle["id"]

    @property
    def tech_qualification_id(self) -> str:
        return self.tech_qualification["id"]

    @property
    def physicist_qualification_id(self) -> str:
        return self.physicist_qualification["id"]

    @property
    def survey_id(self) -> str:
        return self.survey["id"]


# ══════════════════════════════════════════════════════════════════════════
# Low-level helpers
# ══════════════════════════════════════════════════════════════════════════

def _ok(response, label="setup step"):
    """Run a setup call and return its data payload, with a clear failure label."""
    try:
        return get_success_data(response)
    except AssertionError as exc:  # pragma: no cover - only on broken setup
        raise AssertionError(f"Setup failed during {label}: {exc}") from exc


def read_facility(facility_id, headers=None):
    return _ok(api_client.get_facility(facility_id, headers or ANY), "GET facility")


def read_unit(unit_id, headers=None):
    return _ok(api_client.get_modality_unit(unit_id, headers or ANY), "GET unit")


def read_submission(submission_id, headers=None):
    return _ok(
        api_client.get_clinical_image_submission(submission_id, headers or ANY),
        "GET clinical image submission",
    )


def read_survey(survey_id, headers=None):
    return _ok(api_client.get_physicist_survey(survey_id, headers or ANY), "GET survey")


def read_plan(plan_id, headers=None):
    return _ok(
        api_client.get_corrective_action_plan(plan_id, headers or ANY), "GET plan"
    )


def read_qualification(qualification_id, headers=None):
    return _ok(
        api_client.get_personnel_qualification(qualification_id, headers or ANY),
        "GET qualification",
    )


def read_record(record_id, headers=None):
    return _ok(
        api_client.get_dose_registry_record(record_id, headers or ANY),
        "GET dose registry record",
    )


def set_clock(current_utc: str):
    """Advance the server's logical clock and return the clock payload."""
    return _ok(
        api_client.set_current_utc(
            create_clock_payload(current_utc),
            TEST_USERS["accreditation_body_headers"],
        ),
        "POST /_clock/set_current_utc",
    )


# ══════════════════════════════════════════════════════════════════════════
# Tier 1 — State progression
# ══════════════════════════════════════════════════════════════════════════

def create_facility_record(name=None, state_code=None, facility_type=None):
    """Create a PENDING facility. Returns the created facility."""
    payload = create_facility_payload()
    if name is not None:
        payload["name"] = name
    if state_code is not None:
        payload["state_code"] = state_code
    if facility_type is not None:
        payload["facility_type"] = facility_type
    return _ok(api_client.create_facility(payload, ANY), "POST /accreditation/facilities")


def create_verified_qualification(facility_id, **overrides):
    """Record a qualification and verify it. Returns (qualification, owner_headers)."""
    qual = _ok(
        api_client.create_personnel_qualification(
            create_qualification_payload(facility_id, **overrides),
            TEST_USERS["accreditation_body_headers"],
        ),
        "POST /accreditation/qualifications",
    )
    verified = _ok(
        api_client.verify_personnel_qualification(
            qual["id"], create_verify_payload(), TEST_USERS["accreditation_body_headers"]
        ),
        "POST /accreditation/qualifications/{id}/verify",
    )
    headers = make_medical_physicist_headers(verified["id"])
    return verified, headers


def create_physicist_credential(facility_id, **overrides):
    """Record + verify a MEDICAL_PHYSICIST credential. Returns (qualification, headers)."""
    qual = _ok(
        api_client.create_personnel_qualification(
            create_physicist_qualification_payload(facility_id, **overrides),
            TEST_USERS["accreditation_body_headers"],
        ),
        "POST /accreditation/qualifications (physicist)",
    )
    verified = _ok(
        api_client.verify_personnel_qualification(
            qual["id"], create_verify_payload(), TEST_USERS["accreditation_body_headers"]
        ),
        "POST /accreditation/qualifications/{id}/verify",
    )
    return verified, make_medical_physicist_headers(verified["id"])


def enroll_unit(facility_id, expected_facility_version, **overrides):
    """Enroll a modality unit against its facility."""
    return _ok(
        api_client.create_modality_unit(
            create_modality_unit_payload(facility_id, expected_facility_version, **overrides),
            TEST_USERS["facility_admin_headers"],
        ),
        "POST /accreditation/modality-units",
    )


def commission_equipment(unit_id, **overrides):
    """Commission an equipment item onto a unit."""
    return _ok(
        api_client.create_equipment(
            create_equipment_payload(unit_id, **overrides),
            TEST_USERS["facility_admin_headers"],
        ),
        "POST /accreditation/equipment",
    )


def register_facility(facility_id, expected_facility_version):
    """Register the facility, moving it PENDING -> ENROLLED."""
    return _ok(
        api_client.register_facility(
            facility_id,
            create_version_payload(expected_facility_version),
            TEST_USERS["facility_admin_headers"],
        ),
        "POST /accreditation/facilities/{id}/register",
    )


def open_and_activate_cycle(facility_id, cycle_index=1, cycle_started_at=None, **overrides):
    """Open an accreditation cycle and activate it."""
    cycle = _ok(
        api_client.create_accreditation_cycle(
            create_accreditation_cycle_payload(
                facility_id,
                cycle_index=cycle_index,
                cycle_started_at=cycle_started_at or D["CYCLE_STARTED_AT"],
                **overrides,
            ),
            TEST_USERS["accreditation_body_headers"],
        ),
        "POST /accreditation/cycles",
    )
    return activate_cycle(cycle["id"])


def activate_cycle(cycle_id):
    return _ok(
        api_client.activate_accreditation_cycle(
            cycle_id, create_versionless_payload(), TEST_USERS["accreditation_body_headers"]
        ),
        "POST /accreditation/cycles/{id}/activate",
    )


def purchase_registry_credit(facility_id, expected_facility_version, amount_cents=None):
    """Top up the facility's prepaid registry balance."""
    return _ok(
        api_client.purchase_registry_credit(
            facility_id,
            create_registry_credit_payload(
                expected_facility_version,
                amount_cents=amount_cents if amount_cents is not None else D["REGISTRY_CREDIT_TOPUP"],
            ),
            TEST_USERS["facility_admin_headers"],
        ),
        "POST /accreditation/facilities/{id}/registry-credit",
    )


# ══════════════════════════════════════════════════════════════════════════
# Tier 3 — Full lifecycle shortcuts (surveys)
# ══════════════════════════════════════════════════════════════════════════

def schedule_survey(scenario, survey_type="ANNUAL", scheduled_at=None, **overrides):
    """Schedule a survey naming the scenario's physicist credential."""
    payload = create_physicist_survey_payload(
        scenario.facility_id,
        scenario.physicist_qualification_id,
        survey_type=survey_type,
        scheduled_at=scheduled_at or D["SURVEY_SCHEDULED_AT"],
        unit_id=scenario.unit_id,
        **overrides,
    )
    return _ok(
        api_client.create_physicist_survey(payload, scenario.physicist),
        "POST /accreditation/physicist-surveys",
    )


def submit_survey(scenario, survey_id, **overrides):
    """Submit the physicist's findings for review."""
    return _ok(
        api_client.submit_physicist_survey(
            survey_id, create_survey_submission_payload(**overrides), scenario.physicist
        ),
        "POST /accreditation/physicist-surveys/{id}/submit",
    )


def accept_survey(survey_id):
    return _ok(
        api_client.accept_physicist_survey(
            survey_id, create_versionless_payload(), TEST_USERS["accreditation_body_headers"]
        ),
        "POST /accreditation/physicist-surveys/{id}/accept",
    )


def reject_survey(survey_id):
    return _ok(
        api_client.reject_physicist_survey(
            survey_id, create_versionless_payload(), TEST_USERS["accreditation_body_headers"]
        ),
        "POST /accreditation/physicist-surveys/{id}/reject",
    )


def resubmit_survey(scenario, survey_id, **overrides):
    return api_client.resubmit_physicist_survey(
        survey_id,
        {
            "measured_entrance_dose_mgy": overrides.pop("measured_entrance_dose_mgy", D["MEASURED_DOSE_MGY"]),
            "shielding_verdict": overrides.pop("shielding_verdict", "PASS"),
            **overrides,
        },
        scenario.physicist,
    )


def create_accepted_survey(scenario, survey_type="ANNUAL", scheduled_at=None,
                           performed_at=None, measured_entrance_dose_mgy=None):
    """Schedule -> submit -> accept a survey. Returns the ACCEPTED survey."""
    survey = schedule_survey(scenario, survey_type=survey_type, scheduled_at=scheduled_at)
    submit_survey(
        scenario, survey["id"],
        performed_at=performed_at or D["SURVEY_PERFORMED_AT"],
        measured_entrance_dose_mgy=(
            measured_entrance_dose_mgy
            if measured_entrance_dose_mgy is not None
            else D["MEASURED_DOSE_MGY"]
        ),
    )
    return accept_survey(survey["id"])


def create_corrective_required_survey(scenario):
    """A POST_REPAIR survey whose acceptance lands on CORRECTIVE_REQUIRED.

    The measured dose 2.4 against the 2.0 reference gives a +20.0% deviation,
    which exceeds the 10.0% absolute limit, so the accept call drives the
    survey to CORRECTIVE_REQUIRED with rejection_code DOSE_OUT_OF_RANGE.
    """
    survey = schedule_survey(
        scenario, survey_type="POST_REPAIR", scheduled_at="2026-09-20T00:00:00Z"
    )
    submit_survey(
        scenario, survey["id"],
        performed_at="2026-09-20T00:00:00Z", measured_entrance_dose_mgy=2.4,
    )
    return accept_survey(survey["id"])


# ══════════════════════════════════════════════════════════════════════════
# Tier 3 — Clinical image submissions
# ══════════════════════════════════════════════════════════════════════════

def file_submission(scenario, required_view_count=10, accepted_view_count=10, **overrides):
    """File a clinical image set against the scenario's unit."""
    unit = read_unit(scenario.unit_id)
    canary = overrides.pop("expected_unit_version", None)
    payload = create_clinical_image_submission_payload(
        scenario.unit_id,
        canary if canary is not None else unit["version"],
        required_view_count=required_view_count,
        accepted_view_count=accepted_view_count,
        **overrides,
    )
    return api_client.create_clinical_image_submission(payload, scenario.admin)


def file_submission_ok(scenario, required_view_count=10, accepted_view_count=10, **overrides):
    return _ok(
        file_submission(
            scenario,
            required_view_count=required_view_count,
            accepted_view_count=accepted_view_count,
            **overrides,
        ),
        "POST /accreditation/clinical-image-submissions",
    )


def review_submission(submission_id, review_outcome, **overrides):
    return api_client.review_clinical_image_submission(
        submission_id, create_review_payload(review_outcome, **overrides),
        TEST_USERS["accreditation_body_headers"],
    )


def review_submission_ok(submission_id, review_outcome, **overrides):
    return _ok(
        review_submission(submission_id, review_outcome, **overrides),
        "POST /accreditation/clinical-image-submissions/{id}/review",
    )


def resubmit_submission(scenario, submission_id, canary_version=None, **overrides):
    unit = read_unit(scenario.unit_id)
    payload = create_clinical_resubmission_payload(
        canary_version if canary_version is not None else unit["version"], **overrides
    )
    return api_client.resubmit_clinical_image_submission(
        submission_id, payload, scenario.admin
    )


def create_deficient_submission(scenario, reviewer_deficiency_category="POSITIONING"):
    """File a submission that reviews as DEFICIENCY. Returns (submission, plan)."""
    submission = file_submission_ok(scenario, required_view_count=10, accepted_view_count=8)
    reviewed = review_submission_ok(
        submission["id"], "ACCEPT_WITH_DEFICIENCY",
        reviewer_deficiency_category=reviewer_deficiency_category,
    )
    plan = read_plan(reviewed["corrective_action_plan_id"])
    return reviewed, plan


def create_failed_submission(scenario):
    """File a submission the reviewer explicitly fails. Returns (submission, plan)."""
    submission = file_submission_ok(scenario, required_view_count=10, accepted_view_count=8)
    reviewed = review_submission_ok(submission["id"], "FAIL")
    plan = read_plan(reviewed["corrective_action_plan_id"])
    return reviewed, plan


# ══════════════════════════════════════════════════════════════════════════
# Tier 3 — Phantom tests
# ══════════════════════════════════════════════════════════════════════════

def record_phantom(scenario, **overrides):
    return api_client.create_phantom_test(
        create_phantom_test_payload(scenario.unit_id, **overrides), scenario.admin
    )


def record_phantom_ok(scenario, **overrides):
    return _ok(record_phantom(scenario, **overrides), "POST /accreditation/phantom-tests")


def score_phantom(scenario, phantom_test_id, **overrides):
    return api_client.score_phantom_test(
        phantom_test_id, create_phantom_score_payload(**overrides), scenario.admin
    )


def score_phantom_ok(scenario, phantom_test_id, **overrides):
    return _ok(
        score_phantom(scenario, phantom_test_id, **overrides),
        "POST /accreditation/phantom-tests/{id}/score",
    )


def schedule_scored_phantom(scenario, spatial=9, contrast=9, artifact=9,
                            acquired_at=None, serial_code=None, scored_at=None):
    """Record and score a phantom test. Returns the scored test."""
    phantom = record_phantom_ok(
        scenario,
        acquired_at=acquired_at or D["PHANTOM_ACQUIRED_AT"],
        phantom_serial_code=serial_code or D["PHANTOM_SERIAL_CODE"],
    )
    return score_phantom_ok(
        scenario, phantom["id"],
        spatial_resolution_score=spatial,
        contrast_score=contrast,
        artifact_score=artifact,
        scored_at=scored_at or "2026-09-13T01:00:00Z",
    )


# ══════════════════════════════════════════════════════════════════════════
# Tier 3 — Dose registry records
# ══════════════════════════════════════════════════════════════════════════

def stage_record(scenario, dose_index_value=2.3, exam_month="2026-07-01T00:00:00Z", **overrides):
    return _ok(
        api_client.create_dose_registry_record(
            create_dose_registry_record_payload(
                scenario.unit_id,
                dose_index_value=dose_index_value,
                exam_month=exam_month,
                **overrides,
            ),
            scenario.admin,
        ),
        "POST /accreditation/dose-registry-records",
    )


def submit_record(scenario, record_id):
    return api_client.submit_dose_registry_record(
        record_id, create_versionless_payload(), scenario.admin
    )


def submit_record_ok(scenario, record_id):
    return _ok(submit_record(scenario, record_id), "POST /accreditation/dose-registry-records/{id}/submit")


def reject_record(record_id):
    return api_client.reject_dose_registry_record(
        record_id, create_versionless_payload(), TEST_USERS["accreditation_body_headers"]
    )


def setup_submitted_record(scenario, dose_index_value=2.3, exam_month="2026-07-01T00:00:00Z"):
    """Stage and submit one record. Returns the SUBMITTED record."""
    record = stage_record(scenario, dose_index_value=dose_index_value, exam_month=exam_month)
    return submit_record_ok(scenario, record["id"])


# ══════════════════════════════════════════════════════════════════════════
# Tier 2 — The canonical scenario
# ══════════════════════════════════════════════════════════════════════════

def setup_imaging_facility(credit_cents=None, with_survey=True, cycle_index=1,
                           cycle_started_at=None, third_qualification=False,
                           tech_expires_on=None, modality_code=None,
                           unit_label=None, serial_number=None):
    """Build the canonical accreditation scenario from an empty database.

    Returns a `Scenario` whose survey has been ACCEPTED (deviation 7.5%).

    Arguments let a test move a single needle: the credit top-up, the clock
    anchor of the cycle, the technician's expiry date, or the addition of a
    third (INTERPRETING_PHYSICIAN) roster row.
    """
    facility = create_facility_record()
    admin = make_facility_admin_headers(facility["id"])

    tech, _ = create_verified_qualification(
        facility["id"], **({"credential_expires_on": tech_expires_on} if tech_expires_on else {})
    )

    unit = enroll_unit(
        facility["id"], read_facility(facility["id"])["version"],
        **({"modality_code": modality_code, "unit_label": unit_label} if modality_code else {}),
    )
    equipment = commission_equipment(
        unit["id"], **({"serial_number": serial_number} if serial_number else {})
    )

    register_facility(facility["id"], read_facility(facility["id"])["version"])

    cycle = open_and_activate_cycle(
        facility["id"], cycle_index=cycle_index, cycle_started_at=cycle_started_at
    )

    physicist, physicist_headers = create_physicist_credential(facility["id"])

    purchase_registry_credit(
        facility["id"], read_facility(facility["id"])["version"],
        amount_cents=credit_cents if credit_cents is not None else D["REGISTRY_CREDIT_TOPUP"],
    )

    scenario = Scenario(
        facility=read_facility(facility["id"]),
        unit=read_unit(unit["id"]),
        equipment=equipment,
        cycle=cycle,
        tech_qualification=tech,
        physicist_qualification=physicist,
        survey={},
        admin=admin,
        physicist=physicist_headers,
    )

    if with_survey:
        scenario.survey = create_accepted_survey(scenario)

    if third_qualification:
        scenario.extras["third_qualification"] = _ok(
            api_client.create_personnel_qualification(
                create_qualification_payload(
                    facility["id"], person_name="Ravi Menon",
                    personnel_role="INTERPRETING_PHYSICIAN",
                    credential_number="RAD-3001",
                    ce_credit_hours=40.0, required_ce_hours=40.0,
                    credential_expires_on="2027-12-31T00:00:00Z",
                ),
                TEST_USERS["accreditation_body_headers"],
            ),
            "POST /accreditation/qualifications (third)",
        )

    # Refresh entities whose derived fields moved during setup.
    scenario.facility = read_facility(facility["id"])
    scenario.unit = read_unit(unit["id"])
    scenario.physicist_qualification = read_qualification(physicist["id"])
    return scenario


def setup_facility_with_submitted_records(first_value=2.3, second_value=None,
                                          first_month="2026-07-01T00:00:00Z",
                                          second_month="2026-08-01T00:00:00Z"):
    """Canonical scenario plus one submitted CT_HEAD record.

    With `second_value` supplied the second record is staged (not yet
    submitted) so a boundary test can drive its own submit call.
    Returns (scenario, first_record, second_record_or_None).
    """
    scenario = setup_imaging_facility()
    first = setup_submitted_record(scenario, dose_index_value=first_value, exam_month=first_month)
    second = None
    if second_value is not None:
        second = stage_record(scenario, dose_index_value=second_value, exam_month=second_month)
    return scenario, first, second


def setup_two_phantom_acquisitions(scenario=None):
    """Canonical scenario plus a first ACQUIRED phantom window [00:00, 00:30).

    Returns (scenario, first_phantom).
    """
    scenario = scenario or setup_imaging_facility()
    first = record_phantom_ok(scenario, acquired_at="2026-09-13T00:00:00Z", duration_minutes=30)
    return scenario, first


def setup_lapsed_unit_facility():
    """Canonical scenario followed by a facility suspension.

    The unit is DEFERRED, its equipment OUT_OF_SERVICE, and the facility's
    accreditation_currency is SUSPENDED. Returns the scenario.
    """
    scenario = setup_imaging_facility()
    _ok(
        api_client.suspend_facility(
            scenario.facility_id,
            create_version_payload(read_facility(scenario.facility_id)["version"]),
            TEST_USERS["accreditation_body_headers"],
        ),
        "POST /accreditation/facilities/{id}/suspend",
    )
    scenario.facility = read_facility(scenario.facility_id)
    scenario.unit = read_unit(scenario.unit_id)
    scenario.equipment = _ok(
        api_client.get_equipment(scenario.equipment_id, ANY), "GET equipment"
    )
    return scenario


def setup_reinstated_facility():
    """Canonical scenario suspended then reinstated — back on the PENDING path."""
    scenario = setup_lapsed_unit_facility()
    _ok(
        api_client.reinstate_facility(
            scenario.facility_id,
            create_version_payload(read_facility(scenario.facility_id)["version"]),
            TEST_USERS["accreditation_body_headers"],
        ),
        "POST /accreditation/facilities/{id}/reinstate",
    )
    scenario.facility = read_facility(scenario.facility_id)
    scenario.unit = read_unit(scenario.unit_id)
    return scenario


def setup_unit_with_corrective_plan(scenario=None, reviewer_deficiency_category="POSITIONING"):
    """Canonical scenario followed by the full deficiency hop chain.

    Returns (scenario, submission, plan) where the plan has already been
    submitted by the facility, so plan_status is SUBMITTED.
    """
    scenario = scenario or setup_imaging_facility()
    submission, plan = create_deficient_submission(
        scenario, reviewer_deficiency_category=reviewer_deficiency_category
    )
    schedule_scored_phantom(scenario)
    submitted = _ok(
        api_client.submit_corrective_action_plan(
            plan["id"], create_versionless_payload(), scenario.admin
        ),
        "POST /accreditation/corrective-action-plans/{id}/submit",
    )
    scenario.facility = read_facility(scenario.facility_id)
    scenario.unit = read_unit(scenario.unit_id)
    return scenario, submission, submitted


def setup_finalized_cycle(scenario=None):
    """Canonical scenario driven through start-renewal + renew."""
    scenario = scenario or setup_imaging_facility()
    cid = scenario.cycle["id"]
    _ok(
        api_client.start_cycle_renewal(
            cid, create_versionless_payload(), TEST_USERS["accreditation_body_headers"]
        ),
        "POST /accreditation/cycles/{id}/start-renewal",
    )
    renewed = _ok(
        api_client.renew_accreditation_cycle(
            cid, create_versionless_payload(), TEST_USERS["accreditation_body_headers"]
        ),
        "POST /accreditation/cycles/{id}/renew",
    )
    scenario.facility = read_facility(scenario.facility_id)
    return scenario, renewed


# ══════════════════════════════════════════════════════════════════════════
# Threshold / accumulation helpers
# ══════════════════════════════════════════════════════════════════════════

def setup_credit_at_threshold(amount_cents=REGISTRY_FEE_CENTS):
    """Canonical scenario whose registry balance is exactly `amount_cents`."""
    scenario = setup_imaging_facility(credit_cents=0)
    purchase_registry_credit(
        scenario.facility_id, read_facility(scenario.facility_id)["version"],
        amount_cents=amount_cents,
    )
    scenario.facility = read_facility(scenario.facility_id)
    return scenario


def setup_renewal_credit_boundary(amount_cents=RENEWAL_FEE_CENTS):
    """Canonical scenario holding exactly the renewal fee."""
    return setup_credit_at_threshold(amount_cents)


def setup_resubmission_credit_boundary(amount_cents=SURVEY_RESUBMISSION_FEE_CENTS):
    """Canonical scenario holding exactly the survey-resubmission fee."""
    scenario = setup_imaging_facility(credit_cents=0)
    purchase_registry_credit(
        scenario.facility_id, read_facility(scenario.facility_id)["version"],
        amount_cents=amount_cents,
    )
    scenario.facility = read_facility(scenario.facility_id)
    scenario.extras["survey"] = create_corrective_required_survey(scenario)
    return scenario


def expected_comparison_for(modality_code: str) -> float:
    """The modality constant used when no comparison record exists yet."""
    return MODALITY_COMPARISON[modality_code]


__all__ = [
    "Scenario", "DEFAULT_CLOCK", "SCENARIO_CLOCK", "days_after", "iso",
    "read_facility", "read_unit", "read_submission", "read_survey", "read_plan",
    "read_qualification", "read_record", "set_clock",
    "create_facility_record", "create_verified_qualification",
    "create_physicist_credential", "enroll_unit", "commission_equipment",
    "register_facility", "open_and_activate_cycle", "activate_cycle",
    "purchase_registry_credit",
    "schedule_survey", "submit_survey", "accept_survey", "reject_survey",
    "resubmit_survey", "create_accepted_survey", "create_corrective_required_survey",
    "file_submission", "file_submission_ok", "review_submission",
    "review_submission_ok", "resubmit_submission",
    "create_deficient_submission", "create_failed_submission",
    "record_phantom", "record_phantom_ok", "score_phantom", "score_phantom_ok",
    "schedule_scored_phantom",
    "stage_record", "submit_record", "submit_record_ok", "reject_record",
    "setup_submitted_record",
    "setup_imaging_facility", "setup_facility_with_submitted_records",
    "setup_two_phantom_acquisitions", "setup_lapsed_unit_facility",
    "setup_reinstated_facility", "setup_unit_with_corrective_plan",
    "setup_finalized_cycle", "setup_credit_at_threshold",
    "setup_renewal_credit_boundary", "setup_resubmission_credit_boundary",
    "expected_comparison_for",
]