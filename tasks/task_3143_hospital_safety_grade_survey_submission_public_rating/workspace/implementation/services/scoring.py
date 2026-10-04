"""Score runs, the computed preview and the scorecard."""

from decimal import Decimal

from calculations import (
    DOMAINS,
    composite_score as compute_composite,
    domain_measure_rollup,
    grade_assignment,
    to_decimal,
)
from db import BaseRecord, store
from errors import (
    ApiError,
    ERR_CHAR_EXEMPTION_UNSUPPORTED,
    ERR_CYCLE_ALREADY_PUBLISHED,
    ERR_HOSPITAL_NOT_ACTIVE,
    ERR_INVALID_REQUEST,
    ERR_MEASURE_SET_NOT_FOUND,
    ERR_MEASURE_SET_NOT_READY,
    ERR_MEASURE_SET_OMITTED,
    ERR_METHODOLOGY_INCOMPLETE,
    ERR_METHODOLOGY_VERSION_REQUIRED,
    ERR_RELEASE_CYCLE_NOT_FOUND,
    ERR_SCORE_RUN_NOT_FOUND,
)

from services.hospitals import (
    available_measure_values,
    ensure_hospital_set,
    find_hospital_set,
    materialise_measures,
)


class ScoreRun(BaseRecord):
    entity_name = "ScoreRun"


class Grade(BaseRecord):
    entity_name = "Grade"


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def get_score_run(run_id):
    run = store.score_runs.get(run_id)
    if run is None:
        raise ApiError(ERR_SCORE_RUN_NOT_FOUND)
    return run


def get_grade(grade_id):
    from errors import ERR_GRADE_NOT_FOUND
    grade = store.grades.get(grade_id)
    if grade is None:
        raise ApiError(ERR_GRADE_NOT_FOUND)
    return grade


def get_measure_set(measure_set_id):
    measure_set = store.hospital_measure_sets.get(measure_set_id)
    if measure_set is None:
        raise ApiError(ERR_MEASURE_SET_NOT_FOUND)
    return measure_set


def latest_verified_survey(hospital_id):
    candidates = [
        survey for survey in store.surveys.values()
        if survey["hospital_id"] == hospital_id and survey.get("af_status") == "VERIFIED"
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item["updated_at"], item["id"]))
    return candidates[-1]


def hospital_grade_in_cycle(hospital_id, release_cycle_id):
    for grade in store.grades.values():
        if grade["hospital_id"] == hospital_id and grade["release_cycle_id"] == release_cycle_id:
            return grade
    return None


def hospital_grades(hospital_id):
    rows = [grade for grade in store.grades.values() if grade["hospital_id"] == hospital_id]
    rows.sort(key=lambda item: (item["created_at"], item["id"]))
    return rows


def reviewable_grades(hospital_id):
    """Grades usable for the computed reads: the newest scored one first."""
    rows = [
        grade for grade in store.grades.values()
        if grade["hospital_id"] == hospital_id and grade.get("letter_grade") is not None
    ]
    rows.sort(key=lambda item: (item["created_at"], item["id"]))
    return rows


def latest_grade(hospital_id):
    rows = hospital_grades(hospital_id)
    return rows[-1] if rows else None


# ---------------------------------------------------------------------------
# Methodology completeness
# ---------------------------------------------------------------------------

def methodology_complete(methodology_version):
    """All five domains must carry a positive weight."""
    weights = {}
    for definition in methodology_version.get("measure_definitions") or []:
        domain = definition.get("domain")
        if domain not in DOMAINS:
            continue
        weight = to_decimal(definition.get("weight", 0) or 0)
        weights[domain] = weights.get(domain, Decimal("0")) + weight
    if set(weights.keys()) != set(DOMAINS):
        return False
    return all(weight > 0 for weight in weights.values())


# ---------------------------------------------------------------------------
# Score run creation
# ---------------------------------------------------------------------------

def create_score_run(hospital, payload):
    if hospital.get("status") != "ACTIVE":
        raise ApiError(ERR_HOSPITAL_NOT_ACTIVE)

    release_cycle_id = payload.get("release_cycle_id")
    if not isinstance(release_cycle_id, str) or release_cycle_id.strip() == "":
        raise ApiError(ERR_INVALID_REQUEST)
    cycle = store.release_cycles.get(release_cycle_id)
    if cycle is None:
        raise ApiError(ERR_RELEASE_CYCLE_NOT_FOUND)

    methodology_version_id = payload.get("methodology_version_id")
    if methodology_version_id is None:
        methodology_version_id = hospital.get("active_methodology_version_id")
    if not isinstance(methodology_version_id, str) or methodology_version_id.strip() == "":
        raise ApiError(ERR_METHODOLOGY_VERSION_REQUIRED)
    methodology_version = store.methodology_versions.get(methodology_version_id)
    if methodology_version is None:
        from errors import ERR_METHODOLOGY_VERSION_NOT_FOUND
        raise ApiError(ERR_METHODOLOGY_VERSION_NOT_FOUND)

    if cycle.get("methodology_version_id") != methodology_version_id:
        raise ApiError(ERR_INVALID_REQUEST)
    if cycle.get("state") == "PUBLISHED":
        raise ApiError(ERR_CYCLE_ALREADY_PUBLISHED)

    expected = payload.get("expected_hospital_version")
    if expected is not None:
        if isinstance(expected, bool) or not isinstance(expected, int):
            raise ApiError(ERR_INVALID_REQUEST)
        if expected != int(hospital.get("version", 0)):
            from errors import ERR_STALE_VERSION
            raise ApiError(ERR_STALE_VERSION)

    # Rematerialise against the run's methodology version, then decide the branch.
    measure_set = ensure_hospital_set(hospital)
    if measure_set.get("methodology_version_id") != methodology_version_id:
        measure_set["methodology_version_id"] = methodology_version_id
    materialise_measures(hospital, measure_set, advance_readiness=False)
    measure_set.touch()

    readiness = measure_set.get("readiness_state")
    run = ScoreRun(
        hospital_id=hospital["id"],
        methodology_version_id=methodology_version_id,
        measure_set_id=measure_set["id"],
        reliability_weight=None,
        domain_scores=[],
        composite_score=None,
        base_grade_letter=None,
        letter_grade=None,
        score_state="RUNNING",
    )

    if readiness == "OMITTED_FROM_CYCLE":
        raise ApiError(ERR_MEASURE_SET_OMITTED)
    if readiness != "READY":
        # PRD §3.5 orders the two guards as a conditional: a run "may [land in
        # SCORED] only when the hospital's measure set `readiness_state` is
        # `READY`, or the attempt is refused with `ERR_MEASURE_SET_NOT_READY`,
        # and only when the pinned version's definitions cover all five domains
        # with positive weights, or the attempt is refused with
        # `ERR_METHODOLOGY_INCOMPLETE`". The readiness verdict decides the fate
        # of a set that never got materialised; the methodology-completeness
        # requirement is a precondition of the scoring branch itself.
        state = _incomplete_branch(hospital, methodology_version)
    else:
        if not methodology_complete(methodology_version):
            raise ApiError(ERR_METHODOLOGY_INCOMPLETE)
        state = "SCORED"

    if state == "CHAR_EXEMPT":
        run["score_state"] = "CHAR_EXEMPT"
        run["letter_grade"] = None
        run["domain_scores"] = _available_domain_scores(measure_set, methodology_version)
        run["composite_score"] = None
        run["base_grade_letter"] = None
        run["reliability_weight"] = None
        store.score_runs[run["id"]] = run
        _cut_grade(hospital, cycle, run, "CHAR_EXEMPT")
        hospital.touch()
        return run

    _complete_scored_run(run, hospital, measure_set, methodology_version)
    store.score_runs[run["id"]] = run
    _cut_grade(hospital, cycle, run, "SCORED")
    hospital.touch()
    return run


def _incomplete_branch(hospital, methodology_version):
    """Decide between CHAR_EXEMPT and a refusal for an INCOMPLETE measure set.

    PRD §3.5: "A run moves from `RUNNING` to `CHAR_EXEMPT` only when the
    hospital has neither a `VERIFIED` survey nor any `PUBLIC_SOURCE_SUBSTITUTED`
    measure, and at least one measure in the pinned version is
    `UNREPORTED_EXCLUDED`." A run that does not meet that conjunction but whose
    set is not `READY` is refused with `ERR_MEASURE_SET_NOT_READY`.
    """
    definitions = methodology_version.get("measure_definitions") or []
    rows = [
        row for row in store.survey_measures.values()
        if row["hospital_id"] == hospital["id"]
    ]
    has_substituted = any(
        row.get("measure_status") == "PUBLIC_SOURCE_SUBSTITUTED" for row in rows
    )
    verified = latest_verified_survey(hospital["id"]) is not None

    codes_present = {row["measure_code"] for row in rows}
    any_excluded = any(
        definition["measure_code"] not in codes_present for definition in definitions
    )

    if not verified and not has_substituted and any_excluded:
        return "CHAR_EXEMPT"
    raise ApiError(ERR_MEASURE_SET_NOT_READY)


def _available_domain_scores(measure_set, methodology_version):
    available = available_measure_values(measure_set)
    return domain_measure_rollup(available, methodology_version.get("measure_definitions") or [])


def _complete_scored_run(run, hospital, measure_set, methodology_version):
    definitions = methodology_version.get("measure_definitions") or []
    available = available_measure_values(measure_set)

    domain_scores = domain_measure_rollup(available, definitions)
    composite, _terms = compute_composite(definitions, domain_scores)

    survey = latest_verified_survey(hospital["id"])
    reliability = to_decimal(survey["reliability_weight"]) if (
        survey is not None and survey.get("reliability_weight") is not None
    ) else None

    base_letter, letter, capped = grade_assignment(composite, reliability)

    run["score_state"] = "SCORED"
    run["domain_scores"] = domain_scores
    run["composite_score"] = composite
    run["base_grade_letter"] = base_letter
    run["letter_grade"] = letter
    run["reliability_weight"] = reliability
    run["grade_cap_applied"] = capped
    return run


def _cut_grade(hospital, cycle, run, status):
    grade = hospital_grade_in_cycle(hospital["id"], cycle["id"])
    if grade is None:
        grade = Grade(
            hospital_id=hospital["id"],
            release_cycle_id=cycle["id"],
            score_run_id=run["id"],
            composite_score=run.get("composite_score"),
            letter_grade=run.get("letter_grade"),
            grade_cap_applied=bool(run.get("grade_cap_applied", False)),
            status=status,
        )
        store.grades[grade["id"]] = grade
    else:
        grade["score_run_id"] = run["id"]
        grade["composite_score"] = run.get("composite_score")
        grade["letter_grade"] = run.get("letter_grade")
        grade["grade_cap_applied"] = bool(run.get("grade_cap_applied", False))
        grade["status"] = status
        grade.touch()
    cycle["grade_count"] = sum(
        1 for item in store.grades.values() if item["release_cycle_id"] == cycle["id"]
    )
    return grade


# ---------------------------------------------------------------------------
# Computed reads
# ---------------------------------------------------------------------------

def composite_preview(hospital, methodology_version_id=None):
    from errors import ERR_METHODOLOGY_VERSION_NOT_FOUND
    version_id = methodology_version_id or hospital.get("active_methodology_version_id")
    if version_id is None:
        raise ApiError(ERR_METHODOLOGY_VERSION_REQUIRED)
    methodology_version = store.methodology_versions.get(version_id)
    if methodology_version is None:
        raise ApiError(ERR_METHODOLOGY_VERSION_NOT_FOUND)

    measure_set = find_hospital_set(hospital["id"], version_id)
    if measure_set is not None:
        available = available_measure_values(measure_set)
        substituted_count = int(measure_set.get("substituted_measure_count") or 0)
    else:
        available = {}
        substituted_count = 0

    definitions = methodology_version.get("measure_definitions") or []
    domain_scores = domain_measure_rollup(available, definitions)
    composite, _terms = compute_composite(definitions, domain_scores)

    submitted_available = {
        code: (value, status)
        for code, (value, status) in available.items()
        if status != "PUBLIC_SOURCE_SUBSTITUTED"
    }
    submitted_domain_scores = domain_measure_rollup(submitted_available, definitions)
    submitted_composite, _ = compute_composite(definitions, submitted_domain_scores)

    survey = latest_verified_survey(hospital["id"])
    reliability = to_decimal(survey["reliability_weight"]) if (
        survey is not None and survey.get("reliability_weight") is not None
    ) else None
    base_letter, letter, capped = grade_assignment(composite, reliability)

    return {
        "hospital_id": hospital["id"],
        "methodology_version_id": version_id,
        "domain_scores": domain_scores,
        "composite_score": composite,
        "submitted_raw_composite_score": submitted_composite,
        "base_grade_letter": base_letter,
        "letter_grade": letter,
        "reliability_weight": reliability,
        "grade_cap_applied": capped,
        "substituted_measure_count": substituted_count,
    }


def scorecard(hospital, release_cycle_id=None):
    from errors import ERR_GRADE_NOT_FOUND
    if release_cycle_id is None:
        grade = latest_grade(hospital["id"])
        if grade is None:
            raise ApiError(ERR_GRADE_NOT_FOUND)
        cycle = store.release_cycles.get(grade["release_cycle_id"])
    else:
        cycle = store.release_cycles.get(release_cycle_id)
        if cycle is None:
            raise ApiError(ERR_RELEASE_CYCLE_NOT_FOUND)
        grade = hospital_grade_in_cycle(hospital["id"], cycle["id"])
        if grade is None:
            from errors import ERR_GRADE_NOT_FOUND
            raise ApiError(ERR_GRADE_NOT_FOUND)

    run = store.score_runs.get(grade.get("score_run_id")) if grade else None
    domain_scores = run.get("domain_scores") if run else []

    measure_set = find_hospital_set(
        hospital["id"], cycle.get("methodology_version_id")
    ) if cycle else None
    substituted = int(measure_set.get("substituted_measure_count") or 0) if measure_set else 0
    if substituted > 0:
        method_source = "PUBLIC_SOURCE_SUBSTITUTED"
    elif domain_scores:
        method_source = "SURVEY_SUBMISSION"
    else:
        method_source = "NO_MEASURES"

    employer_eligible = _employer_eligible(hospital["id"], grade.get("letter_grade"))

    return {
        "hospital_id": hospital["id"],
        "release_cycle_id": cycle["id"] if cycle else release_cycle_id,
        "domain_scores": domain_scores,
        "composite_score": grade.get("composite_score") if grade else None,
        "letter_grade": grade.get("letter_grade") if grade else None,
        "grade_cap_applied": bool(grade.get("grade_cap_applied", False)) if grade else False,
        "method_source": method_source,
        "employer_eligible": employer_eligible,
    }


def _employer_eligible(hospital_id, letter):
    from calculations import LETTER_RANKS
    if letter is None:
        return False
    rank = LETTER_RANKS.get(letter, 0)
    for employer in store.employers.values():
        if hospital_id not in (employer.get("network_hospital_ids") or []):
            continue
        floor = LETTER_RANKS.get(employer.get("minimum_acceptable_letter"), 0)
        if rank >= floor:
            return True
    return False


# ---------------------------------------------------------------------------
# Re-derivation helpers used by the cycle and reanalysis tracks
# ---------------------------------------------------------------------------

def published_grade_components(hospital_id, release_cycle_id):
    """Pre-renormalisation components for the composite_adjusted_for_reanalysis rule."""
    grade = hospital_grade_in_cycle(hospital_id, release_cycle_id)
    if grade is None:
        return None, None
    return grade.get("composite_score"), grade.get("letter_grade")


def refresh_hospital_measures(hospital, expected_hospital_version):
    """Version-guarded rematerialisation, plus the withheld-grade consequence.

    Both doors stamp source_snapshot_at and increment the hospital's version;
    the omitted door additionally withholds the hospital's grades in every
    cycle that has not yet published.
    """
    from services.hospitals import refresh_measures

    measure_set = refresh_measures(hospital, expected_hospital_version)

    if measure_set.get("readiness_state") == "OMITTED_FROM_CYCLE":
        _withhold_grades(hospital)
    else:
        # A rematerialised set clears any reanalysis adjustment, so a hospital
        # returning to READY is no longer omitted and its grades are reinstated.
        _reinstate_grades(hospital, measure_set)
    return measure_set


def _withhold_grades(hospital):
    from services.cycles import derive_cycle_state
    for grade in hospital_grades(hospital["id"]):
        cycle = store.release_cycles.get(grade.get("release_cycle_id"))
        if cycle is None or cycle.get("state") == "PUBLISHED":
            continue
        if grade.get("status") == "WITHHELD":
            continue
        grade["status"] = "WITHHELD"
        grade["letter_grade"] = None
        grade.touch()
        cycle["grade_count"] = sum(
            1 for item in store.grades.values() if item["release_cycle_id"] == cycle["id"]
        )
        derive_cycle_state(cycle)


def _reinstate_grades(hospital, measure_set):
    """Re-materialising a no-longer-omitted set returns withheld grades to SCORED."""
    from services.cycles import derive_cycle_state
    for grade in hospital_grades(hospital["id"]):
        if grade.get("status") != "WITHHELD":
            continue
        cycle = store.release_cycles.get(grade.get("release_cycle_id"))
        if cycle is None or cycle.get("state") == "PUBLISHED":
            continue
        run = store.score_runs.get(grade.get("score_run_id"))
        grade["status"] = "SCORED"
        if run is not None:
            grade["composite_score"] = run.get("composite_score")
            grade["letter_grade"] = run.get("letter_grade")
            grade["grade_cap_applied"] = bool(run.get("grade_cap_applied", False))
        grade.touch()
        cycle["grade_count"] = sum(
            1 for item in store.grades.values() if item["release_cycle_id"] == cycle["id"]
        )
        derive_cycle_state(cycle)