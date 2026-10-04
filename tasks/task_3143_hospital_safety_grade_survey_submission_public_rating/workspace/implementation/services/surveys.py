"""Survey lifecycle: opening, measuring, submission, verification, resolution."""

from calculations import sample_rate_of, survey_certification_reliability
from db import BaseRecord, clock, format_instant, store, to_decimal
from errors import (
    ApiError,
    ERR_METHODOLOGY_VERSION_REQUIRED,
    ERR_SELF_VERIFICATION_FORBIDDEN,
    ERR_SOURCE_DOCUMENTATION_REQUIRED,
    ERR_SURVEY_ALREADY_SUBMITTED,
    ERR_SURVEY_HAS_NO_MEASURES,
    ERR_SURVEY_NOT_IN_DISCREPANCY,
    ERR_SURVEY_NOT_FOUND,
    ERR_SURVEY_OWNER_MISMATCH,
    ERR_SURVEY_RESPONSE_COUNT_INCONSISTENT,
    ERR_SURVEY_SAMPLE_DENOMINATOR_INVALID,
    ERR_SURVEY_VERIFICATION_ALREADY_OPEN,
    ERR_INVALID_REQUEST,
    ERR_HOSPITAL_NOT_ACTIVE,
)

from services.hospitals import (
    derive_measure_row,
    ensure_hospital_set,
    get_hospital,
    mark_disclosure_submitted,
    mark_disclosure_unverified,
    materialise_measures,
    measure_rows_for_hospital,
    recompute_source_document_count,
)

VALIDATION_METHODS = ("ATTESTATION", "SOURCE_DOCUMENT")
VERIFICATION_RESPONSES = ("ACCEPT", "DISCREPANCY_REQUEST")


class Survey(BaseRecord):
    entity_name = "Survey"


class SurveyMeasure(BaseRecord):
    entity_name = "SurveyMeasure"


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def get_survey(survey_id):
    survey = store.surveys.get(survey_id)
    if survey is None:
        raise ApiError(ERR_SURVEY_NOT_FOUND)
    return survey


def get_survey_measure(row_id):
    from errors import ERR_SURVEY_MEASURE_NOT_FOUND
    row = store.survey_measures.get(row_id)
    if row is None:
        raise ApiError(ERR_SURVEY_MEASURE_NOT_FOUND)
    return row


def measures_for_survey(survey_id):
    rows = [row for row in store.survey_measures.values() if row["survey_id"] == survey_id]
    rows.sort(key=lambda item: (item["created_at"], item["id"]))
    return rows


def measures_for_hospital(hospital_id):
    return measure_rows_for_hospital(hospital_id)


def find_measure_row(hospital_id, measure_code):
    rows = [
        row for row in store.survey_measures.values()
        if row["hospital_id"] == hospital_id and row["measure_code"] == measure_code
    ]
    if not rows:
        return None
    rows.sort(key=lambda item: (item["created_at"], item["id"]))
    return rows[0]


def adopt_supporting_documents(hospital):
    """Adopted supporting documents across the hospital's reanalysis requests."""
    documents = []
    for request in store.reanalysis_requests.values():
        if request["hospital_id"] != hospital["id"]:
            continue
        if request.get("status") not in ("GRANTED", "UNDER_REVIEW", "PENDING"):
            continue
        for entry in request.get("supporting_documents") or []:
            if isinstance(entry, dict):
                documents.append(entry)
    return documents


# ---------------------------------------------------------------------------
# Opening and correcting
# ---------------------------------------------------------------------------

def create_survey(hospital, payload, submitting_user_id):
    if hospital.get("status") != "ACTIVE":
        raise ApiError(ERR_HOSPITAL_NOT_ACTIVE)

    methodology_version_id = hospital.get("active_methodology_version_id")
    if methodology_version_id is None:
        raise ApiError(ERR_METHODOLOGY_VERSION_REQUIRED)

    started = _optional_count(payload, "started_survey_count", 0)
    completed = _optional_count(payload, "completed_survey_count", 0)
    discharges = _optional_count(payload, "entity_annual_discharges", 0)
    validation_method = payload.get("validation_method")
    if validation_method is not None and validation_method not in VALIDATION_METHODS:
        raise ApiError(ERR_INVALID_REQUEST)

    rate = sample_rate_of(completed, discharges) if discharges else None
    survey = Survey(
        hospital_id=hospital["id"],
        methodology_version_id=methodology_version_id,
        submitted_by_user_id=submitting_user_id,
        started_survey_count=started,
        completed_survey_count=completed,
        entity_annual_discharges=discharges,
        validation_method=validation_method,
        verification_response=None,
        verification_cycle=0,
        reanalysis_request_count=0,
        reliability_weight=None,
        sample_rate=rate,
        af_status="AWAITING_SUBMISSION",
        af_certification_level="UNCERTIFIED",
    )
    store.surveys[survey["id"]] = survey
    hospital.touch()
    return survey


def _optional_count(payload, key, default):
    if key not in payload or payload.get(key) is None:
        return default
    value = payload[key]
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ApiError(ERR_INVALID_REQUEST)
    return value


def update_survey(survey, payload):
    if "started_survey_count" in payload and payload.get("started_survey_count") is not None:
        survey["started_survey_count"] = _optional_count(payload, "started_survey_count", 0)
    if "completed_survey_count" in payload and payload.get("completed_survey_count") is not None:
        survey["completed_survey_count"] = _optional_count(payload, "completed_survey_count", 0)
    if "entity_annual_discharges" in payload and payload.get("entity_annual_discharges") is not None:
        survey["entity_annual_discharges"] = _optional_count(payload, "entity_annual_discharges", 0)
    if "validation_method" in payload:
        value = payload.get("validation_method")
        if value is not None and value not in VALIDATION_METHODS:
            raise ApiError(ERR_INVALID_REQUEST)
        survey["validation_method"] = value

    survey["sample_rate"] = sample_rate_of(
        survey["completed_survey_count"], survey["entity_annual_discharges"]
    )
    if survey["entity_annual_discharges"] == 0:
        survey["sample_rate"] = None

    survey.touch()
    hospital = get_hospital(survey["hospital_id"])
    hospital.touch()
    return survey


# ---------------------------------------------------------------------------
# Measures
# ---------------------------------------------------------------------------

def record_measure(hospital, payload):
    survey_id = payload.get("survey_id")
    if not isinstance(survey_id, str) or survey_id.strip() == "":
        raise ApiError(ERR_INVALID_REQUEST)
    survey = get_survey(survey_id)
    if survey["hospital_id"] != hospital["id"]:
        raise ApiError(ERR_INVALID_REQUEST)

    measure_code = payload.get("measure_code")
    if not isinstance(measure_code, str) or measure_code.strip() == "":
        raise ApiError(ERR_INVALID_REQUEST)
    raw_value = payload.get("raw_value")
    if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float, str)):
        raise ApiError(ERR_INVALID_REQUEST)
    raw_value_dec = to_decimal(raw_value)
    if raw_value_dec < 0:
        raise ApiError(ERR_INVALID_REQUEST)

    source_program_id = payload.get("source_program_id")
    if source_program_id is not None:
        if not isinstance(source_program_id, str) or not (1 <= len(source_program_id) <= 64):
            raise ApiError(ERR_INVALID_REQUEST)

    derived = derive_measure_row(hospital, measure_code, raw_value_dec, source_program_id)

    row = find_measure_row(hospital["id"], measure_code)
    if row is None:
        row = SurveyMeasure(
            hospital_id=hospital["id"],
            survey_id=survey_id,
            measure_code=measure_code,
            raw_value=raw_value_dec,
            source_program_id=source_program_id,
            derived_value=derived,
            measure_status="REPORTED",
            flag_hold=_flag_hold(hospital, measure_code, raw_value_dec, source_program_id),
        )
        store.survey_measures[row["id"]] = row
    else:
        row["survey_id"] = survey_id
        row["raw_value"] = raw_value_dec
        row["source_program_id"] = source_program_id
        row["derived_value"] = derived
        row["measure_status"] = "REPORTED"
        row["flag_hold"] = _flag_hold(hospital, measure_code, raw_value_dec, source_program_id)
        row.touch()

    _invalidate_set(hospital)
    hospital.touch()
    return row


def record_public_source_measure(hospital, payload):
    measure_code = payload.get("measure_code")
    if not isinstance(measure_code, str) or measure_code.strip() == "":
        raise ApiError(ERR_INVALID_REQUEST)
    source_program_id = payload.get("source_program_id")
    if not isinstance(source_program_id, str) or not (1 <= len(source_program_id) <= 64):
        raise ApiError(ERR_INVALID_REQUEST)
    source_value = payload.get("source_value")
    if isinstance(source_value, bool) or not isinstance(source_value, (int, float, str)):
        raise ApiError(ERR_INVALID_REQUEST)
    source_value_dec = to_decimal(source_value)

    derived = derive_measure_row(hospital, measure_code, source_value_dec, source_program_id)

    row = find_measure_row(hospital["id"], measure_code)
    if row is None:
        row = SurveyMeasure(
            hospital_id=hospital["id"],
            survey_id=None,
            measure_code=measure_code,
            raw_value=source_value_dec,
            source_program_id=source_program_id,
            derived_value=derived,
            measure_status="PUBLIC_SOURCE_SUBSTITUTED",
            flag_hold=_flag_hold(hospital, measure_code, source_value_dec, source_program_id),
        )
        store.survey_measures[row["id"]] = row
    else:
        row["raw_value"] = source_value_dec
        row["source_program_id"] = source_program_id
        row["derived_value"] = derived
        row["measure_status"] = "PUBLIC_SOURCE_SUBSTITUTED"
        row["flag_hold"] = _flag_hold(hospital, measure_code, source_value_dec, source_program_id)
        row.touch()

    _invalidate_set(hospital)
    hospital.touch()
    return row


def _flag_hold(hospital, measure_code, value, source_program_id):
    """True when the source programme disagrees with the submitted raw value
    under the pinned derivation rule. A raw value that is already a direct
    submission is recorded through the same code path, so a row carrying a
    source programme always describes a sourced value rather than a mismatch."""
    if source_program_id is None:
        return False
    row = find_measure_row(hospital["id"], measure_code)
    if row is None:
        return False
    return to_decimal(row.get("raw_value") or 0) != to_decimal(value)


def _invalidate_set(hospital):
    """Recording a measure leaves the materialised set INCOMPLETE."""
    measure_set = ensure_hospital_set(hospital)
    if measure_set.get("readiness_state") != "INCOMPLETE":
        measure_set["readiness_state"] = "INCOMPLETE"
        measure_set.touch()


# ---------------------------------------------------------------------------
# Submission
# ---------------------------------------------------------------------------

def submit_survey(survey):
    if survey.get("af_status") != "AWAITING_SUBMISSION":
        raise ApiError(ERR_SURVEY_ALREADY_SUBMITTED)

    if int(survey.get("started_survey_count") or 0) < 1 or int(
        survey.get("completed_survey_count") or 0
    ) > int(survey.get("started_survey_count") or 0):
        raise ApiError(ERR_SURVEY_RESPONSE_COUNT_INCONSISTENT)

    if int(survey.get("entity_annual_discharges") or 0) < 1:
        raise ApiError(ERR_SURVEY_SAMPLE_DENOMINATOR_INVALID)

    if not measures_for_hospital(survey["hospital_id"]):
        raise ApiError(ERR_SURVEY_HAS_NO_MEASURES)

    survey["af_status"] = "SUBMITTED"
    survey["sample_rate"] = sample_rate_of(
        survey["completed_survey_count"], survey["entity_annual_discharges"]
    )
    survey.touch()

    hospital = get_hospital(survey["hospital_id"])
    mark_disclosure_submitted(hospital)
    recompute_source_document_count(hospital)
    hospital["updated_at"] = format_instant(clock.now())
    hospital["version"] = int(hospital.get("version", 0)) + 1

    measure_set = ensure_hospital_set(hospital)
    materialise_measures(hospital, measure_set, advance_readiness=False)
    measure_set.touch()

    # PRD §3.3: the submission increments the hospital's `version` exactly once
    # and materialises the measures. The response is the survey, whose own
    # `version` is unrelated to the hospital's; the caller reads the hospital's
    # post-submission state through the hospital surface.
    return survey


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

def verify_survey(survey, verification_response, acting_user_id):
    if verification_response not in VERIFICATION_RESPONSES:
        raise ApiError(ERR_INVALID_REQUEST)

    if acting_user_id == survey.get("submitted_by_user_id"):
        raise ApiError(ERR_SELF_VERIFICATION_FORBIDDEN)

    status = survey.get("af_status")
    recorded = survey.get("verification_response")

    accepting = verification_response == "ACCEPT"
    if accepting:
        if status == "SUBMITTED" and recorded is None:
            pass
        elif status == "DISCREPANCY_RESOLVED" and recorded == "DISCREPANCY_REQUEST":
            pass
        else:
            raise ApiError(ERR_SURVEY_VERIFICATION_ALREADY_OPEN)
    else:
        if status != "SUBMITTED" or recorded is not None:
            raise ApiError(ERR_SURVEY_VERIFICATION_ALREADY_OPEN)

    hospital = get_hospital(survey["hospital_id"])
    if accepting:
        if not _source_documentation_complete(hospital, survey):
            raise ApiError(ERR_SOURCE_DOCUMENTATION_REQUIRED)

    if accepting:
        survey["af_status"] = "VERIFIED"
        survey["af_certification_level"] = "CERTIFIED"
        survey["verification_response"] = "ACCEPT"
        weight, _, _ = survey_certification_reliability(
            survey["started_survey_count"],
            survey["completed_survey_count"],
            survey["entity_annual_discharges"],
            survey.get("verification_cycle", 0),
        )
        survey["reliability_weight"] = weight
        survey.touch()
        hospital.touch()
        mark_disclosure_submitted(hospital)
        if to_decimal(weight) < to_decimal("0.60"):
            _cap_open_review_grades(hospital)
    else:
        survey["af_status"] = "DISCREPANCY_OPEN"
        survey["verification_response"] = "DISCREPANCY_REQUEST"
        survey["verification_cycle"] = int(survey.get("verification_cycle", 0)) + 1
        survey["af_certification_level"] = "UNCERTIFIED"
        survey.touch()
        hospital.touch()
        _apply_discrepancy_cascade(hospital, survey)

    return survey


def _source_documentation_complete(hospital, survey):
    rows = measures_for_survey(survey["id"])
    if not rows:
        rows = measures_for_hospital(hospital["id"])
    if rows and all(row.get("source_program_id") is not None for row in rows):
        return True
    return len(adopt_supporting_documents(hospital)) >= 1


def _apply_discrepancy_cascade(hospital, survey):
    """Four hops: demand documents, re-flag each row, stale the set, disclose."""
    for row in measures_for_hospital(hospital["id"]):
        if row.get("source_program_id") is None:
            row["flag_hold"] = True
            definition_derived = derive_measure_row(
                hospital, row["measure_code"], row["raw_value"], row.get("source_program_id")
            )
            row["derived_value"] = definition_derived
            row.touch()

    measure_set = ensure_hospital_set(hospital)
    measure_set["readiness_state"] = "INCOMPLETE"
    measure_set.touch()
    mark_disclosure_unverified(hospital)
    recompute_source_document_count(hospital)


def _cap_open_review_grades(hospital):
    """A freshly accepted survey below the cap downgrades every open-review grade."""
    from calculations import DOWNGRADE
    for grade in store.grades.values():
        if grade["hospital_id"] != hospital["id"]:
            continue
        cycle = store.release_cycles.get(grade.get("release_cycle_id"))
        if cycle is None or cycle.get("state") != "OPEN_REVIEW":
            continue
        grade["grade_cap_applied"] = True
        letter = grade.get("letter_grade")
        if letter is not None:
            grade["letter_grade"] = DOWNGRADE.get(letter, letter)
        grade.touch()


# ---------------------------------------------------------------------------
# Discrepancy resolution
# ---------------------------------------------------------------------------

def resolve_survey(survey, acting_user_id):
    if survey.get("af_status") != "DISCREPANCY_OPEN":
        raise ApiError(ERR_SURVEY_NOT_IN_DISCREPANCY)
    if acting_user_id != survey.get("submitted_by_user_id"):
        raise ApiError(ERR_SURVEY_OWNER_MISMATCH)

    hospital = get_hospital(survey["hospital_id"])
    rows = measures_for_hospital(hospital["id"])
    if not rows or any(row.get("source_program_id") is None for row in rows):
        raise ApiError(ERR_SOURCE_DOCUMENTATION_REQUIRED)

    survey["af_status"] = "DISCREPANCY_RESOLVED"
    survey.touch()
    mark_disclosure_submitted(hospital)
    recompute_source_document_count(hospital)
    hospital.touch()

    measure_set = ensure_hospital_set(hospital)
    materialise_measures(hospital, measure_set, advance_readiness=False)
    measure_set.touch()
    return survey


def recompute_reliability(survey):
    weight, _, _ = survey_certification_reliability(
        survey["started_survey_count"],
        survey["completed_survey_count"],
        survey["entity_annual_discharges"],
        survey.get("verification_cycle", 0),
    )
    survey["reliability_weight"] = weight
    return weight