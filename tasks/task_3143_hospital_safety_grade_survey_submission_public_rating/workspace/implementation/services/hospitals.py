"""Hospital registration, mutation, measure-set materialisation and disclosure."""

from calculations import derived_measure_value
from db import BaseRecord, clock, format_instant, store, to_decimal
from errors import (
    ApiError,
    ERR_DUPLICATE_CCN,
    ERR_HOSPITAL_NOT_FOUND,
    ERR_INVALID_TEACHING_STATUS,
    ERR_INVALID_REQUEST,
    ERR_MEASURE_CODE_NOT_IN_METHODOLOGY,
    ERR_METHODOLOGY_VERSION_REQUIRED,
    ERR_SNAPSHOT_ALREADY_CURRENT,
)
from middleware import require_int, require_string

TEACHING_VALUES = ("TEACHING", "NON_TEACHING")

CCN_PATTERN_LENGTH = 6


class Hospital(BaseRecord):
    entity_name = "Hospital"


class HospitalMeasureSet(BaseRecord):
    entity_name = "HospitalMeasureSet"


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def get_hospital(hospital_id):
    hospital = store.hospitals.get(hospital_id)
    if hospital is None:
        raise ApiError(ERR_HOSPITAL_NOT_FOUND)
    return hospital


def find_hospital_set(hospital_id, methodology_version_id=None):
    """The materialised set for a hospital, optionally scoped to a version."""
    candidates = [
        measure_set for measure_set in store.hospital_measure_sets.values()
        if measure_set["hospital_id"] == hospital_id
        and (methodology_version_id is None
             or measure_set["methodology_version_id"] == methodology_version_id)
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item["created_at"], item["id"]))
    return candidates[-1]


def ensure_hospital_set(hospital):
    """Fetch, or lazily create, the hospital's materialised measure set."""
    version_id = hospital.get("active_methodology_version_id")
    existing = find_hospital_set(hospital["id"], version_id)
    if existing is not None:
        return existing
    measure_set = HospitalMeasureSet(
        hospital_id=hospital["id"],
        methodology_version_id=version_id,
        # PRD §3.4: the set "records ... the logical-clock instant
        # `source_snapshot_at` at which it was last materialised", so the set
        # created here is stamped at its creation instant and a refresh at that
        # same instant is refused as `ERR_SNAPSHOT_ALREADY_CURRENT`.
        source_snapshot_at=format_instant(clock.now()),
        measures=[],
        substituted_measure_count=0,
        readiness_state="INCOMPLETE",
    )
    store.hospital_measure_sets[measure_set["id"]] = measure_set
    return measure_set


# ---------------------------------------------------------------------------
# Registration and update
# ---------------------------------------------------------------------------

def create_hospital(payload):
    name = require_string(payload, "name")
    ccn = require_string(payload, "ccn")
    state_code = require_string(payload, "state_code")
    bed_count = require_int(payload, "bed_count", minimum=1)
    teaching_status = require_string(payload, "teaching_status")
    annual_discharges = require_int(payload, "annual_discharges", minimum=1)
    contact_email = require_string(payload, "survey_contact_email")

    if teaching_status not in TEACHING_VALUES:
        raise ApiError(ERR_INVALID_TEACHING_STATUS)

    for existing in store.hospitals.values():
        if existing.get("ccn") == ccn:
            raise ApiError(ERR_DUPLICATE_CCN)

    hospital = Hospital(
        name=name,
        ccn=ccn,
        state_code=state_code,
        bed_count=bed_count,
        teaching_status=teaching_status,
        annual_discharges=annual_discharges,
        survey_contact_email=contact_email,
        active_methodology_version_id=None,
        worst_grade_ever=None,
        disclosure_status="NEVER_SUBMITTED",
        submitted_source_document_count=0,
        status="ACTIVE",
    )
    store.hospitals[hospital["id"]] = hospital
    return hospital


def update_hospital(hospital, payload):
    if "teaching_status" in payload and payload.get("teaching_status") is not None:
        if payload.get("teaching_status") not in TEACHING_VALUES:
            raise ApiError(ERR_INVALID_TEACHING_STATUS)

    numeric_keys = {
        "bed_count": 1,
        "annual_discharges": 1,
    }
    derived_inputs_changed = False
    for key in ("name", "state_code", "status"):
        if key in payload and payload.get(key) is not None:
            if not isinstance(payload[key], str) or payload[key].strip() == "":
                raise ApiError(ERR_INVALID_REQUEST)
            hospital[key] = payload[key]
    for key, minimum in numeric_keys.items():
        if key in payload and payload.get(key) is not None:
            value = payload[key]
            if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
                raise ApiError(ERR_INVALID_REQUEST)
            if hospital.get(key) != value:
                derived_inputs_changed = True
            hospital[key] = value
    for key in ("teaching_status", "survey_contact_email"):
        if key in payload and payload.get(key) is not None:
            if not isinstance(payload[key], str) or payload[key].strip() == "":
                raise ApiError(ERR_INVALID_REQUEST)
            hospital[key] = payload[key]

    if derived_inputs_changed:
        _recompute_set_readiness(hospital)

    hospital.touch()
    return hospital


def _recompute_set_readiness(hospital):
    """A changed denominator or bed count invalidates the materialised set."""
    measure_set = find_hospital_set(hospital["id"], hospital.get("active_methodology_version_id"))
    if measure_set is not None and measure_set.get("readiness_state") == "READY":
        measure_set["readiness_state"] = "INCOMPLETE"


# ---------------------------------------------------------------------------
# Measure-set materialisation
# ---------------------------------------------------------------------------

def _definition_index(methodology_version):
    index = {}
    for definition in methodology_version.get("measure_definitions") or []:
        index[definition["measure_code"]] = definition
    return index


def _version_scope(hospital):
    """The methodology version whose definitions are in scope for this hospital."""
    version_id = hospital.get("active_methodology_version_id")
    if version_id is None:
        return None
    return store.methodology_versions.get(version_id)


def measure_rows_for_hospital(hospital_id):
    rows = [row for row in store.survey_measures.values() if row["hospital_id"] == hospital_id]
    rows.sort(key=lambda item: (item["created_at"], item["id"]))
    return rows


def _row_state(row):
    """(raw_value, derived_value, status, source_program_id) for a row."""
    return (
        to_decimal(row["raw_value"]) if row.get("raw_value") is not None else None,
        to_decimal(row["derived_value"]) if row.get("derived_value") is not None else None,
        row.get("measure_status"),
        row.get("source_program_id"),
    )


def materialise_measures(hospital, measure_set, advance_readiness=True):
    """Rebuild the ordered measures array, count substitutions, derive readiness.

    Substitution rule: a row that carries a source_program_id and whose stored
    measure_status is PUBLIC_SOURCE_SUBSTITUTED is a substituted entry and the
    source programme's number wins. Any other row uses the hospital's submitted
    raw value.
    """
    methodology_version = _version_scope(hospital)
    if methodology_version is None:
        raise ApiError(ERR_METHODOLOGY_VERSION_REQUIRED)

    definitions = methodology_version.get("measure_definitions") or []
    rows_by_code = {}
    for row in measure_rows_for_hospital(hospital["id"]):
        rows_by_code[row["measure_code"]] = row

    measures = []
    substituted = 0
    for definition in definitions:
        code = definition["measure_code"]
        rule = definition.get("derivation_rule", "NONE")
        row = rows_by_code.get(code)
        if row is None:
            measures.append({
                "measure_code": code,
                "domain": definition["domain"],
                "derived_value": None,
                "measure_status": "UNREPORTED_EXCLUDED",
            })
            continue

        raw_value = row.get("raw_value")
        sourced = (
            row.get("source_program_id") is not None
            and row.get("measure_status") == "PUBLIC_SOURCE_SUBSTITUTED"
        )
        if sourced:
            value_source = row.get("raw_value")
            status = "PUBLIC_SOURCE_SUBSTITUTED"
            substituted += 1
        else:
            value_source = raw_value
            status = "REPORTED"

        derived = derived_measure_value(value_source, rule)
        row["derived_value"] = derived
        measures.append({
            "measure_code": code,
            "domain": definition["domain"],
            "derived_value": derived,
            "measure_status": status,
        })

    measure_set["measures"] = measures
    measure_set["substituted_measure_count"] = substituted
    if advance_readiness:
        # PRD §3.4: the READY / OMITTED_FROM_CYCLE doors open on *rematerialisation*
        # ("Rematerialisation is performed by the `RatingEngine` ... when the count
        # is three or fewer the set becomes `READY`"). A plain recompute — the
        # measure list a submission or a raw write refreshes — rebuilds the
        # `measures` array without opening either door.
        if substituted >= 4:
            measure_set["readiness_state"] = "OMITTED_FROM_CYCLE"
        elif all(entry["measure_status"] == "UNREPORTED_EXCLUDED" for entry in measures):
            measure_set["readiness_state"] = "INCOMPLETE"
        else:
            measure_set["readiness_state"] = "READY"
    return measure_set


def available_measure_values(measure_set):
    """measure_code -> (derived_value, measure_status) from the materialised set."""
    available = {}
    for entry in measure_set.get("measures") or []:
        available[entry["measure_code"]] = (entry.get("derived_value"), entry.get("measure_status"))
    return available


def refresh_measures(hospital, expected_hospital_version, defer_touch=False):
    """The version-guarded rematerialisation shared by refresh-measures and scoring."""
    if expected_hospital_version is not None:
        if int(expected_hospital_version) != int(hospital.get("version", 0)):
            from errors import ERR_STALE_VERSION
            raise ApiError(ERR_STALE_VERSION)

    methodology_version = _version_scope(hospital)
    if methodology_version is None:
        raise ApiError(ERR_METHODOLOGY_VERSION_REQUIRED)

    measure_set = ensure_hospital_set(hospital)
    instant = clock.now()
    snapshot = measure_set.get("source_snapshot_at")
    if snapshot is not None:
        from db import parse_instant
        try:
            snapshot_instant = parse_instant(snapshot)
        except ValueError:
            snapshot_instant = None
        if snapshot_instant is not None and instant == snapshot_instant:
            raise ApiError(ERR_SNAPSHOT_ALREADY_CURRENT)

    materialise_measures(hospital, measure_set)
    measure_set["source_snapshot_at"] = format_instant(instant)
    measure_set.touch()
    if not defer_touch:
        hospital.touch()
    return measure_set


def derive_measure_row(hospital, measure_code, raw_value, source_program_id):
    """Compute derived_value for a row under the pinned version's rule."""
    methodology_version = _version_scope(hospital)
    if methodology_version is None:
        raise ApiError(ERR_METHODOLOGY_VERSION_REQUIRED)
    definition = _definition_index(methodology_version).get(measure_code)
    if definition is None:
        raise ApiError(ERR_MEASURE_CODE_NOT_IN_METHODOLOGY)
    return derived_measure_value(raw_value, definition.get("derivation_rule", "NONE"))


# ---------------------------------------------------------------------------
# Disclosure posture
# ---------------------------------------------------------------------------

def mark_disclosure_submitted(hospital):
    """A survey is submitted, or a discrepancy is resolved."""
    hospital["disclosure_status"] = "SUBMITTED"
    return hospital["disclosure_status"]


def mark_disclosure_unverified(hospital):
    """A verification opened a discrepancy, or a refuted reanalysis landed."""
    hospital["disclosure_status"] = "UNVERIFIED"
    return hospital["disclosure_status"]


def all_surveys_unverified(hospital_id):
    """True when the hospital has surveys and none of them is VERIFIED."""
    surveys = hospital_surveys(hospital_id)
    if not surveys:
        return False
    return all(survey.get("af_status") != "VERIFIED" for survey in surveys)


def hospital_surveys(hospital_id):
    return [survey for survey in store.surveys.values() if survey["hospital_id"] == hospital_id]


def recompute_source_document_count(hospital):
    """Survey measures carrying a source_program_id plus adopted documents."""
    count = 0
    for row in measure_rows_for_hospital(hospital["id"]):
        if row.get("source_program_id") is not None:
            count += 1
    for request in store.reanalysis_requests.values():
        if request["hospital_id"] != hospital["id"]:
            continue
        if request.get("status") == "GRANTED":
            count += len(request.get("supporting_documents") or [])
    hospital["submitted_source_document_count"] = count


def recompute_worst_grade_ever(hospital):
    """Lowest published effective letter ever recorded; null before publication."""
    letters = []
    for grade in store.grades.values():
        if grade["hospital_id"] != hospital["id"]:
            continue
        cycle = store.release_cycles.get(grade.get("release_cycle_id"))
        if cycle is None or cycle.get("state") != "PUBLISHED":
            continue
        letter = grade.get("letter_grade")
        if letter is None:
            continue
        letters.append(letter)
    if not letters:
        return hospital.get("worst_grade_ever")
    worst = max(letters, key=lambda item: LETTER_RANK_INDEX.get(item, 0))
    hospital["worst_grade_ever"] = worst
    return worst


LETTER_RANK_INDEX = {"A": 0, "B": 1, "C": 2, "D": 3, "F": 4}