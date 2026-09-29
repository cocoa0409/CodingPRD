"""Cross-entity state dependencies: a write blocked by a *different* row's state.

In both scenarios the rejected request and the accepted request are byte
identical; only the state of a neighbouring entity - the authorization, the
patient - changes between them.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_AUTHORIZATION_NOT_ACTIVE,
    ERR_INVALID_STATE,
    ERR_PATIENT_HOSPITALIZED,
    ERR_SEGREGATION_OF_DUTIES,
)
from test_helpers.assertions import assert_hours, validate_unpaginated
from test_helpers.test_users import (
    CASE_MANAGER,
    CLINICAL_SUPERVISOR,
    CLINICAL_SUPERVISOR_2,
    CLINICAL_SUPERVISOR_3,
    SUPERVISOR_USER_ID,
)
from test_helpers.types import (
    AuthorizationStatus,
    CaseStatus,
    IncidentCategory,
    IncidentSeverity,
    IncidentStatus,
    PatientStatus,
)


def _pending_authorization_and_a_case_body(api):
    """Everything a case needs except an ACTIVE authorization."""
    base = fx.setup_baseline(api, activate_authorization_after_create=False, with_case=False)
    payload = f.case_payload(
        base.patient_id,
        base.authorization_id,
        SUPERVISOR_USER_ID,
        continuity_nurse_id=base.nurse_id,
        concurrent_nurse_limit=1,
        excluded_nurse_ids=[],
    )
    return base, payload


def test_a_case_cannot_open_against_a_pending_authorization(api):
    """The Case write reads the Authorization's state, not its own: while the grant
    is still PENDING the request answers ERR_AUTHORIZATION_NOT_ACTIVE and no case
    row is created.

    Design: Difficulty/cross_entity_state_dependency/case_creation_requires_the_authorization_out_of_pending
    """
    base, payload = _pending_authorization_and_a_case_body(api)

    response = api.create_case(payload, CASE_MANAGER)
    validate_error(response, ERR_AUTHORIZATION_NOT_ACTIVE, 409)

    authorization = fx.refresh_authorization(api, base)
    assert authorization["status"] == AuthorizationStatus.PENDING.value, authorization

    _rows, meta = validate_paginated(
        api.list_cases(CASE_MANAGER, {"authorization_id": base.authorization_id})
    )
    assert meta["total_count"] == 0, meta


def test_activating_the_authorization_lets_the_identical_body_through(api):
    """Nothing about the request changes - only the neighbour's state does. Once the
    authorization is ACTIVE with 0.00 committed hours the same body answers 201 with
    a PENDING_STAFFING case carrying the continuity nurse.

    Design: Difficulty/cross_entity_state_dependency/case_creation_requires_the_authorization_out_of_pending
    """
    base, payload = _pending_authorization_and_a_case_body(api)
    api.create_case(payload, CASE_MANAGER)

    fx.activate_authorization(api, base.authorization_id, base.payer_id)
    authorization = fx.refresh_authorization(api, base)
    assert authorization["status"] == AuthorizationStatus.ACTIVE.value, authorization
    assert_hours(authorization, "hours_committed_this_week", 0.00)

    case = validate_success(api.create_case(payload, CASE_MANAGER), 201)
    assert case["status"] == CaseStatus.PENDING_STAFFING.value, case
    assert case["continuity_nurse_id"] == base.nurse_id, case


def test_only_the_accepted_attempt_is_visible_in_the_case_list(api):
    """After the rejection and the retry the authorization owns exactly one case:
    the refused attempt left nothing behind.

    Design: Difficulty/cross_entity_state_dependency/case_creation_requires_the_authorization_out_of_pending
    """
    base, payload = _pending_authorization_and_a_case_body(api)
    api.create_case(payload, CASE_MANAGER)
    fx.activate_authorization(api, base.authorization_id, base.payer_id)
    validate_success(api.create_case(payload, CASE_MANAGER), 201)

    _rows, meta = validate_paginated(
        api.list_cases(CASE_MANAGER, {"authorization_id": base.authorization_id})
    )
    assert meta["total_count"] == 1, meta


def _case_on_hold_with_the_child_still_an_inpatient(api):
    """A HOSPITALIZATION incident closed on paperwork only: the incident is CLOSED
    but the child has not come home, so the patient is still HOSPITALIZED."""
    base = fx.setup_baseline(api)
    incident = fx.file_incident(
        api,
        base.case_id,
        "2026-08-03T05:00:00Z",
        CLINICAL_SUPERVISOR,
        category=IncidentCategory.HOSPITALIZATION.value,
        severity=IncidentSeverity.HIGH.value,
        narrative="admitted for vent-associated pneumonia",
    )
    fx.close_incident(
        api,
        incident["id"],
        False,
        CLINICAL_SUPERVISOR,
        resolution="paperwork closed while the child is still an inpatient",
    )
    return base, incident


def test_resume_is_blocked_by_the_patients_state_not_the_incidents(api):
    """The incident is already CLOSED, so nothing on the case's own paperwork bars
    the resume - the block comes from the neighbouring Patient row still reading
    HOSPITALIZED, and the error names exactly that.

    Design: Difficulty/cross_entity_state_dependency/case_resume_blocked_until_the_patient_is_out_of_hospital
    """
    base, incident = _case_on_hold_with_the_child_still_an_inpatient(api)

    response = api.resume_case(base.case_id, CLINICAL_SUPERVISOR_2)
    error = validate_error(response, ERR_PATIENT_HOSPITALIZED, 409)
    assert error["error_id"] not in (ERR_INVALID_STATE, ERR_SEGREGATION_OF_DUTIES)

    reread = validate_success(api.get_incident_report(incident["id"], CLINICAL_SUPERVISOR))
    assert reread["status"] == IncidentStatus.CLOSED.value, reread
    assert reread["patient_returned_home"] is False, reread

    patient = validate_success(api.get_patient(base.patient_id, CASE_MANAGER))
    assert patient["status"] == PatientStatus.HOSPITALIZED.value, patient


def test_bringing_the_child_home_frees_the_patient_but_never_resumes_the_case(api):
    """Closing a later incident with `patient_returned_home` true returns the patient
    to ACTIVE, yet the case stays ON_HOLD: the discharge clears the precondition, it
    does not perform the transition.

    Design: Difficulty/cross_entity_state_dependency/case_resume_blocked_until_the_patient_is_out_of_hospital
    """
    base, _incident = _case_on_hold_with_the_child_still_an_inpatient(api)
    api.resume_case(base.case_id, CLINICAL_SUPERVISOR_2)

    second = fx.file_incident(
        api,
        base.case_id,
        "2026-08-03T05:30:00Z",
        CLINICAL_SUPERVISOR_3,
        category=IncidentCategory.HOSPITALIZATION.value,
        severity=IncidentSeverity.MODERATE.value,
        narrative="discharge planning note for the same admission",
    )
    closed = fx.close_incident(
        api,
        second["id"],
        True,
        CLINICAL_SUPERVISOR_3,
        resolution="child discharged home on home vent",
    )
    assert closed["status"] == IncidentStatus.CLOSED.value, closed

    patient = validate_success(api.get_patient(base.patient_id, CASE_MANAGER))
    assert patient["status"] == PatientStatus.ACTIVE.value, patient

    case = fx.refresh_case(api, base.case_id)
    assert case["status"] == CaseStatus.ON_HOLD.value, case


def test_the_identical_resume_succeeds_once_the_patient_is_home(api):
    """The same call from the same supervisor now answers 200 with the case ACTIVE
    and both hold fields cleared, and the case owns both incident reports.

    Design: Difficulty/cross_entity_state_dependency/case_resume_blocked_until_the_patient_is_out_of_hospital
    """
    base, _incident = _case_on_hold_with_the_child_still_an_inpatient(api)
    api.resume_case(base.case_id, CLINICAL_SUPERVISOR_2)

    second = fx.file_incident(
        api,
        base.case_id,
        "2026-08-03T05:30:00Z",
        CLINICAL_SUPERVISOR_3,
        category=IncidentCategory.HOSPITALIZATION.value,
        severity=IncidentSeverity.MODERATE.value,
        narrative="discharge planning note for the same admission",
    )
    fx.close_incident(
        api,
        second["id"],
        True,
        CLINICAL_SUPERVISOR_3,
        resolution="child discharged home on home vent",
    )

    resumed = validate_success(api.resume_case(base.case_id, CLINICAL_SUPERVISOR_2))
    assert resumed["status"] == CaseStatus.ACTIVE.value, resumed
    assert resumed["hold_reason"] is None, resumed
    assert resumed["hold_incident_report_id"] is None, resumed

    _rows, meta = validate_unpaginated(
        api.list_case_incident_reports(base.case_id, CLINICAL_SUPERVISOR)
    )
    assert meta["total_count"] == 2, meta
