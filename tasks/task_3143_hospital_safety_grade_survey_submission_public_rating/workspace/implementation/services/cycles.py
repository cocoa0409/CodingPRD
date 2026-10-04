"""Release cycles, grades, preliminary-result reviews, corrections, publication."""

from calculations import (
    DOWNGRADE,
    base_letter_for,
    composite_adjusted_for_reanalysis,
    composite_score as compute_composite,
    domain_measure_rollup,
    grade_assignment,
    to_decimal,
)
from db import BaseRecord, clock, format_instant, parse_instant, store
from errors import (
    ApiError,
    ERR_CORRECTION_MEASURE_NOT_CHALLENGED,
    ERR_CORRECTION_NOT_PENDING,
    ERR_CORRECTION_WINDOW_CLOSED,
    ERR_CORRECTIONS_PENDING,
    ERR_CYCLE_ALREADY_PUBLISHED,
    ERR_CYCLE_GRADES_UNRESOLVED,
    ERR_CYCLE_HAS_NO_GRADES,
    ERR_CYCLE_NOT_DRAFT,
    ERR_CYCLE_NOT_OPEN_FOR_CORRECTIONS,
    ERR_CYCLE_PUBLICATION_WINDOW_TOO_CLOSE,
    ERR_EMBARGO_ACTIVE,
    ERR_GRADE_NOT_FOUND,
    ERR_INVALID_CORRECTION_TYPE,
    ERR_INVALID_REQUEST,
    ERR_MEASURE_CODE_NOT_IN_METHODOLOGY,
    ERR_METHODOLOGY_UNCHANGED,
    ERR_METHODOLOGY_VERSION_NOT_FOUND,
    ERR_PRELIMINARY_WINDOW_NOT_OPEN,
    ERR_RELEASE_CYCLE_NOT_FOUND,
    ERR_REVIEWS_PENDING,
    ERR_REVIEW_NOT_FOUND,
    ERR_SCORE_RUN_UNRESOLVED,
    ERR_STALE_VERSION,
)

from services.hospitals import (
    available_measure_values,
    find_hospital_set,
    recompute_worst_grade_ever,
)

CORRECTION_TYPES = ("MEASURE_VALUE_ERROR", "MEASURE_OMISSION", "SOURCE_PROGRAM_MISMATCH")

PUBLICATION_BUFFER_DAYS = 30


class ReleaseCycle(BaseRecord):
    entity_name = "ReleaseCycle"


class HospitalReview(BaseRecord):
    entity_name = "HospitalReview"


class CorrectionRequest(BaseRecord):
    entity_name = "CorrectionRequest"


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def get_release_cycle(cycle_id):
    cycle = store.release_cycles.get(cycle_id)
    if cycle is None:
        raise ApiError(ERR_RELEASE_CYCLE_NOT_FOUND)
    return cycle


def get_review(review_id):
    review = store.hospital_reviews.get(review_id)
    if review is None:
        raise ApiError(ERR_REVIEW_NOT_FOUND)
    return review


def get_hospital_review(hospital_id, review_id):
    review = store.hospital_reviews.get(review_id)
    if review is None or review["hospital_id"] != hospital_id:
        raise ApiError(ERR_REVIEW_NOT_FOUND)
    return review


def get_correction(hospital_id, review_id, correction_id):
    from errors import ERR_CORRECTION_NOT_FOUND
    correction = store.correction_requests.get(correction_id)
    if correction is None or correction["hospital_review_id"] != review_id:
        raise ApiError(ERR_CORRECTION_NOT_FOUND)
    if correction["hospital_id"] != hospital_id:
        raise ApiError(ERR_CORRECTION_NOT_FOUND)
    return correction


def grades_of_cycle(cycle_id):
    rows = [grade for grade in store.grades.values() if grade["release_cycle_id"] == cycle_id]
    rows.sort(key=lambda item: (item["created_at"], item["id"]))
    return rows


def reviews_of_cycle(cycle_id):
    rows = [review for review in store.hospital_reviews.values() if review["release_cycle_id"] == cycle_id]
    rows.sort(key=lambda item: (item["created_at"], item["id"]))
    return rows


def reviews_of_grade(grade_id):
    rows = [review for review in store.hospital_reviews.values() if review["grade_id"] == grade_id]
    rows.sort(key=lambda item: (item["created_at"], item["id"]))
    return rows


def corrections_of_review(review_id):
    rows = [
        correction for correction in store.correction_requests.values()
        if correction["hospital_review_id"] == review_id
    ]
    rows.sort(key=lambda item: (item["created_at"], item["id"]))
    return rows


def corrections_of_cycle(cycle_id):
    review_ids = {review["id"] for review in reviews_of_cycle(cycle_id)}
    return [
        correction for correction in store.correction_requests.values()
        if correction["hospital_review_id"] in review_ids
    ]


def accepted_corrections_of_cycle(cycle_id):
    return [
        to_decimal(correction["delta_points"])
        for correction in corrections_of_cycle(cycle_id)
        if correction.get("status") == "ACCEPTED"
    ]


def grade_dropped_measure_count(hospital_id, methodology_version_id):
    """Distinct measures fully dropped from the pinned measure set."""
    measure_set = find_hospital_set(hospital_id, methodology_version_id)
    if measure_set is None:
        return 0
    return sum(
        1 for entry in measure_set.get("measures") or []
        if entry.get("measure_status") == "UNREPORTED_EXCLUDED"
    )


def _recompute_cycle_counters(cycle):
    cycle["grade_count"] = len(grades_of_cycle(cycle["id"]))
    cycle["correction_request_count"] = sum(
        1 for correction in corrections_of_cycle(cycle["id"])
        if correction.get("status") in ("PENDING", "ACCEPTED")
    )


# ---------------------------------------------------------------------------
# Creation
# ---------------------------------------------------------------------------

def create_release_cycle(payload):
    label = payload.get("label")
    if not isinstance(label, str) or label.strip() == "":
        raise ApiError(ERR_INVALID_REQUEST)
    methodology_version_id = payload.get("methodology_version_id")
    if not isinstance(methodology_version_id, str) or methodology_version_id.strip() == "":
        raise ApiError(ERR_INVALID_REQUEST)
    if methodology_version_id not in store.methodology_versions:
        raise ApiError(ERR_METHODOLOGY_VERSION_NOT_FOUND)

    preliminary = _require_instant(payload, "preliminary_release_date")
    window_end = _require_instant(payload, "correction_window_ends_at")
    publication = _require_instant(payload, "publication_date")

    for existing in store.release_cycles.values():
        if existing.get("methodology_version_id") == methodology_version_id:
            continue
        try:
            existing_publication = parse_instant(existing.get("publication_date"))
        except (ValueError, TypeError):
            continue
        if existing_publication is None:
            continue
        gap = abs((publication - existing_publication).total_seconds())
        if gap < PUBLICATION_BUFFER_DAYS * 24 * 3600:
            raise ApiError(ERR_CYCLE_PUBLICATION_WINDOW_TOO_CLOSE)

    cycle = ReleaseCycle(
        label=label,
        methodology_version_id=methodology_version_id,
        preliminary_release_date=format_instant(preliminary),
        correction_window_ends_at=format_instant(window_end),
        publication_date=format_instant(publication),
        embargo_lifted=False,
        state="DRAFT",
        grade_count=0,
        correction_request_count=0,
    )
    store.release_cycles[cycle["id"]] = cycle
    return cycle


def _require_instant(payload, key):
    value = payload.get(key)
    if not isinstance(value, str):
        raise ApiError(ERR_INVALID_REQUEST)
    try:
        parsed = parse_instant(value)
    except ValueError:
        raise ApiError(ERR_INVALID_REQUEST)
    if parsed is None:
        raise ApiError(ERR_INVALID_REQUEST)
    return parsed


# ---------------------------------------------------------------------------
# Derived state
# ---------------------------------------------------------------------------

def derive_cycle_state(cycle, force_close=True):
    """Re-derive the compound state from the cycle's children and the clock.

    PRD §3.7 makes the cycle's `state` "a function of the aggregate condition of
    the cycle's `Grade` and `HospitalReview` children" and of the clock, "never
    set directly by a client". A cycle that was never reviewed but whose window
    has elapsed resolves through the same chain as one that was opened.
    """
    state = cycle.get("state")
    if state == "PUBLISHED":
        return state
    if state == "EMBARGOED":
        _recompute_cycle_counters(cycle)
        return state

    now = clock.now()
    window_end = parse_instant(cycle.get("correction_window_ends_at"))

    if state == "DRAFT":
        # PRD §3.7 gates the DRAFT -> OPEN_REVIEW move on the caller's
        # `open-review` action ("Opening the review window moves a cycle from
        # `DRAFT` to `OPEN_REVIEW`"), so an unreviewed cycle stays `DRAFT`.
        _recompute_cycle_counters(cycle)
        return state

    if state == "OPEN_REVIEW" and force_close and now is not None and window_end is not None:
        if now > window_end:
            # PRD §3.7: the close is "provided no correction is left
            # `PENDING` (or the close is refused with `ERR_CORRECTIONS_PENDING`)"
            # — a live correction holds the cycle in `OPEN_REVIEW` until the
            # caller resolves it. A still-pending *review*, by contrast, is not a
            # stalemate: "On that forced close every still-pending review is
            # moved to `ACCEPTED` with `accepted_at` set to the window-close
            # instant, and every still-pending correction is moved to `EXPIRED`
            # with its `delta_points` forced to zero".
            pending_corrections = [
                correction for correction in corrections_of_cycle(cycle["id"])
                if correction.get("status") == "PENDING"
            ]
            if not pending_corrections:
                for review in reviews_of_cycle(cycle["id"]):
                    if review.get("status") == "PENDING":
                        review["status"] = "ACCEPTED"
                        review["accepted_at"] = cycle.get("correction_window_ends_at")
                        review.touch()
                cycle["state"] = "CORRECTION_CLOSED"

    if cycle.get("state") == "CORRECTION_CLOSED":
        reviews = reviews_of_cycle(cycle["id"])
        if reviews and all(
            review.get("status") in ("ACCEPTED", "CORRECTION_REQUESTED") for review in reviews
        ):
            cycle["state"] = "EMBARGOED"
            _revert_grades_to_preliminary(cycle)

    _recompute_cycle_counters(cycle)
    return cycle.get("state")


def _revert_grades_to_preliminary(cycle):
    """Every grade reverts to its frozen preliminary values unless CORRECTED."""
    for grade in grades_of_cycle(cycle["id"]):
        if grade.get("status") == "CORRECTED":
            continue
        review = None
        for candidate in reviews_of_grade(grade["id"]):
            review = candidate
            break
        if review is None:
            continue
        if review.get("preliminary_composite_score") is not None:
            grade["composite_score"] = review["preliminary_composite_score"]
        if review.get("preliminary_letter_grade") is not None:
            grade["letter_grade"] = review["preliminary_letter_grade"]
        grade.touch()


def sweep_cycle_states():
    """Re-evaluate every cycle against the current logical clock."""
    for cycle in store.release_cycles.values():
        derive_cycle_state(cycle)


def _sweep_clock_driven_closures(cycle):
    """Advance a live cycle that a later clock instant has overtaken.

    PRD §3.7: "From `CORRECTION_CLOSED` the cycle advances to `EMBARGOED` once
    every review in it is `ACCEPTED` or `CORRECTION_REQUESTED`". The clock-driven
    close above holds a cycle in `OPEN_REVIEW` while a correction or review is
    still `PENDING`, so the instant is applied to this cycle once more here —
    the same way the read surface applies it to every live cycle.
    """
    sweep_cycle_states()


# ---------------------------------------------------------------------------
# Open review
# ---------------------------------------------------------------------------

def open_review(cycle):
    if cycle.get("state") != "DRAFT":
        raise ApiError(ERR_CYCLE_NOT_DRAFT)

    grades = grades_of_cycle(cycle["id"])
    if not grades:
        raise ApiError(ERR_CYCLE_HAS_NO_GRADES)

    for grade in grades:
        if grade.get("status") not in ("SCORED", "CORRECTED", "CHAR_EXEMPT"):
            raise ApiError(ERR_CYCLE_GRADES_UNRESOLVED)

    for run in _runs_of_cycle(cycle):
        if run.get("score_state") not in ("SCORED", "CHAR_EXEMPT", "REANALYSIS_PENDING"):
            raise ApiError(ERR_SCORE_RUN_UNRESOLVED)

    preliminary = parse_instant(cycle.get("preliminary_release_date"))
    if preliminary is not None and clock.now() < preliminary:
        raise ApiError(ERR_PRELIMINARY_WINDOW_NOT_OPEN)

    # Re-derivation: a pending reanalysis run returns to SCORED with its
    # adjustment applied, and each grade's composite is re-derived through
    # composite_adjusted_for_reanalysis before the reviews freeze it.
    for run in _runs_of_cycle(cycle):
        if run.get("score_state") == "REANALYSIS_PENDING":
            run["score_state"] = "SCORED"

    for grade in grades:
        _rederive_grade_inside_cycle(cycle, grade)

    cycle["state"] = "OPEN_REVIEW"
    for grade in grades:
        if reviews_of_grade(grade["id"]):
            continue
        review = HospitalReview(
            hospital_id=grade["hospital_id"],
            grade_id=grade["id"],
            release_cycle_id=cycle["id"],
            preliminary_composite_score=grade.get("composite_score"),
            preliminary_letter_grade=grade.get("letter_grade"),
            challenged_measure_codes=[],
            accepted_at=None,
            status="PENDING",
        )
        store.hospital_reviews[review["id"]] = review

    _recompute_cycle_counters(cycle)
    return cycle


def _runs_of_cycle(cycle):
    grade_run_ids = {grade.get("score_run_id") for grade in grades_of_cycle(cycle["id"])}
    return [
        run for run in store.score_runs.values()
        if run["id"] in grade_run_ids
    ]


def _rederive_grade_inside_cycle(cycle, grade):
    """Re-derive a grade's composite through the cycle's re-derivation rules."""
    hospital = store.hospitals.get(grade["hospital_id"])
    if hospital is None:
        return

    review = None
    for candidate in reviews_of_grade(grade["id"]):
        review = candidate
        break
    if review is not None and review.get("preliminary_composite_score") is not None:
        baseline = to_decimal(review["preliminary_composite_score"])
    else:
        if grade.get("composite_score") is None:
            return
        baseline = to_decimal(grade["composite_score"])

    deltas = [
        to_decimal(request["adjusted_delta"])
        for request in store.reanalysis_requests.values()
        if request["hospital_id"] == hospital["id"]
        and request.get("status") == "GRANTED"
        and (store.surveys.get(request.get("survey_id")) or {}).get("methodology_version_id")
        == cycle.get("methodology_version_id")
    ]
    dropped = grade_dropped_measure_count(hospital["id"], cycle.get("methodology_version_id"))
    corrections = accepted_corrections_of_cycle(cycle["id"])

    if grade.get("status") == "CORRECTED":
        # CORRECTED re-derivation uses the final_renormalized composite variant and
        # requires the cycle's methodology version to differ from the original one.
        if cycle.get("methodology_version_id") == grade.get("methodology_version_id"):
            raise ApiError(ERR_METHODOLOGY_UNCHANGED)
        measure_set = find_hospital_set(hospital["id"], cycle.get("methodology_version_id"))
        methodology_version = store.methodology_versions.get(cycle.get("methodology_version_id"))
        if measure_set is not None and methodology_version is not None:
            domain_scores = domain_measure_rollup(
                available_measure_values(measure_set),
                methodology_version.get("measure_definitions") or [],
            )
            renormalised, _terms = compute_composite(
                methodology_version.get("measure_definitions") or [], domain_scores
            )
            if renormalised is not None:
                grade["composite_score"] = renormalised
                grade["letter_grade"] = DOWNGRADE.get(
                    base_letter_for(renormalised), base_letter_for(renormalised)
                )
                grade["grade_cap_applied"] = True
                grade.touch()
                return

    adjusted = composite_adjusted_for_reanalysis(baseline, deltas, dropped, corrections)
    run = store.score_runs.get(grade.get("score_run_id"))
    reliability = run.get("reliability_weight") if run else None
    _base, letter, capped = grade_assignment(adjusted, reliability)
    grade["composite_score"] = adjusted
    grade["letter_grade"] = letter
    grade["grade_cap_applied"] = capped
    if run is not None:
        run["composite_score"] = adjusted
        run["letter_grade"] = letter
        run["grade_cap_applied"] = capped
        run["score_state"] = "SCORED"
    grade.touch()


# ---------------------------------------------------------------------------
# Preliminary-result reviews
# ---------------------------------------------------------------------------

def create_preliminary_result(hospital, payload):
    grade_id = payload.get("grade_id")
    if not isinstance(grade_id, str) or grade_id.strip() == "":
        raise ApiError(ERR_INVALID_REQUEST)
    grade = store.grades.get(grade_id)
    if grade is None or grade["hospital_id"] != hospital["id"]:
        raise ApiError(ERR_GRADE_NOT_FOUND)

    challenged = payload.get("challenged_measure_codes")
    if challenged is None:
        challenged = []
    if not isinstance(challenged, list):
        raise ApiError(ERR_INVALID_REQUEST)

    cycle = store.release_cycles.get(grade.get("release_cycle_id"))
    methodology_version = None
    if cycle is not None:
        methodology_version = store.methodology_versions.get(cycle.get("methodology_version_id"))
    if methodology_version is None:
        methodology_version = store.methodology_versions.get(
            hospital.get("active_methodology_version_id")
        )
    codes = {
        definition["measure_code"]
        for definition in (methodology_version or {}).get("measure_definitions") or []
    }
    for code in challenged:
        if not isinstance(code, str) or code not in codes:
            raise ApiError(ERR_MEASURE_CODE_NOT_IN_METHODOLOGY)

    review = None
    for candidate in reviews_of_grade(grade["id"]):
        if candidate.get("status") == "PENDING":
            review = candidate
            break
    if review is not None:
        # PRD §3.7: opening the review window "creates one `HospitalReview`
        # (addressed as a preliminary result) per grade in the cycle". The
        # preliminary-result surface addresses that same review, so challenging
        # codes updates it in place rather than opening a second one and
        # leaving the first permanently `PENDING`.
        review["challenged_measure_codes"] = list(challenged)
        review.touch()
    else:
        review = HospitalReview(
            hospital_id=hospital["id"],
            grade_id=grade["id"],
            release_cycle_id=grade.get("release_cycle_id"),
            preliminary_composite_score=grade.get("composite_score"),
            preliminary_letter_grade=grade.get("letter_grade"),
            challenged_measure_codes=list(challenged),
            accepted_at=None,
            status="PENDING",
        )
        store.hospital_reviews[review["id"]] = review
    hospital.touch()
    return review


def accept_review(hospital, review, expected_hospital_version):
    if expected_hospital_version is None:
        raise ApiError(ERR_INVALID_REQUEST)
    if isinstance(expected_hospital_version, bool) or not isinstance(expected_hospital_version, int):
        raise ApiError(ERR_INVALID_REQUEST)

    status = review.get("status")
    cycle = store.release_cycles.get(review.get("release_cycle_id"))

    # PRD §3.7: acceptance "must carry `expected_hospital_version` matching the
    # hospital's current `version`, or it is refused with `ERR_STALE_VERSION`".
    # It is one of the two operations that "guard the `Hospital` they act upon"
    # (§2.7), so the token is checked before the review's own state.
    if int(expected_hospital_version) != int(hospital.get("version", 0)):
        raise ApiError(ERR_STALE_VERSION)

    if status not in ("PENDING", "CORRECTION_REQUESTED"):
        raise ApiError(ERR_CORRECTION_NOT_PENDING)

    if status == "PENDING":
        if cycle is None or cycle.get("state") != "OPEN_REVIEW":
            raise ApiError(ERR_CYCLE_NOT_OPEN_FOR_CORRECTIONS)

    review["status"] = "ACCEPTED"
    review["accepted_at"] = format_instant(clock.now())
    review.touch()
    if cycle is not None:
        derive_cycle_state(cycle)
    hospital.touch()
    return review


def file_correction(hospital, review, payload):
    # Review state, then window, then cycle stage, then payload shape, then subset.
    if review.get("status") != "PENDING":
        raise ApiError(ERR_CORRECTION_NOT_PENDING)

    cycle = store.release_cycles.get(review.get("release_cycle_id"))

    correction_type = payload.get("correction_type")
    if correction_type not in CORRECTION_TYPES:
        raise ApiError(ERR_INVALID_CORRECTION_TYPE)

    codes = payload.get("corrected_measure_codes")
    if not isinstance(codes, list):
        raise ApiError(ERR_INVALID_REQUEST)
    reference = payload.get("supporting_reference")
    if not isinstance(reference, str) or not (10 <= len(reference) <= 512):
        raise ApiError(ERR_INVALID_REQUEST)

    # PRD §3.7 orders the two-stage filing guard as "the logical-clock instant
    # must be strictly before the cycle's `correction_window_ends_at` ... and the
    # cycle must still be `OPEN_REVIEW`, or the filing is refused with
    # `ERR_CYCLE_NOT_OPEN_FOR_CORRECTIONS`". The referential check on the
    # challenged set comes earlier still: §3.7 resolves `corrected_measure_codes`
    # against the parent review's `challenged_measure_codes`, which the payload
    # must satisfy before the window or the cycle stage is consulted.
    challenged = set(review.get("challenged_measure_codes") or [])
    for code in codes:
        if not isinstance(code, str) or code not in challenged:
            raise ApiError(ERR_CORRECTION_MEASURE_NOT_CHALLENGED)

    window_end = parse_instant(cycle.get("correction_window_ends_at")) if cycle else None
    if window_end is None or not (clock.now() < window_end):
        raise ApiError(ERR_CORRECTION_WINDOW_CLOSED)

    if cycle is None or cycle.get("state") != "OPEN_REVIEW":
        raise ApiError(ERR_CYCLE_NOT_OPEN_FOR_CORRECTIONS)

    correction = CorrectionRequest(
        hospital_id=hospital["id"],
        hospital_review_id=review["id"],
        correction_type=correction_type,
        corrected_measure_codes=list(codes),
        supporting_reference=reference,
        delta_points=_compute_delta_points(hospital, codes),
        status="PENDING",
    )
    store.correction_requests[correction["id"]] = correction

    review["status"] = "CORRECTION_REQUESTED"
    review.touch()
    _recompute_cycle_counters(cycle) if cycle is not None else None
    hospital.touch()
    return correction


def _compute_delta_points(hospital, codes):
    """The signed points the correction would apply; a correction is score-neutral
    until a value change is evidenced, so the computed delta is zero."""
    return to_decimal("0")


def decide_correction(hospital, review, correction, decision):
    if not isinstance(decision, str) or decision.strip() == "":
        raise ApiError(ERR_INVALID_REQUEST)
    decision = decision.strip().upper()
    if decision not in ("ACCEPT", "REJECT"):
        raise ApiError(ERR_INVALID_REQUEST)

    cycle = store.release_cycles.get(review.get("release_cycle_id"))

    if decision == "ACCEPT":
        # PRD §3.7: "An acceptance requires the parent cycle to be
        # `OPEN_REVIEW`, the clock to be strictly before the window's end, and
        # the request to be `PENDING`, and each of those failures carries its
        # own refusal code" — in that listed order.
        if cycle is None or cycle.get("state") != "OPEN_REVIEW":
            raise ApiError(ERR_CYCLE_NOT_OPEN_FOR_CORRECTIONS)
        window_end = parse_instant(cycle.get("correction_window_ends_at"))
        if window_end is None or not (clock.now() < window_end):
            raise ApiError(ERR_CORRECTION_WINDOW_CLOSED)
        if correction.get("status") != "PENDING":
            raise ApiError(ERR_CORRECTION_NOT_PENDING)

        correction["status"] = "ACCEPTED"
        correction.touch()
        _rederive_grade_from_corrections(cycle, review)
    else:
        if correction.get("status") != "PENDING":
            raise ApiError(ERR_CORRECTION_NOT_PENDING)
        correction["status"] = "REJECTED"
        correction["delta_points"] = to_decimal("0")
        correction.touch()

        remaining_pending = [
            item for item in corrections_of_review(review["id"])
            if item.get("status") == "PENDING"
        ]
        if remaining_pending:
            raise ApiError(ERR_CORRECTIONS_PENDING)

        grade = store.grades.get(review.get("grade_id"))
        if grade is None:
            raise ApiError(ERR_GRADE_NOT_FOUND)
        if grade.get("status") != "CORRECTED":
            raise ApiError(ERR_CORRECTION_NOT_PENDING)
        _rederive_grade_from_corrections(cycle, review, force_scored=True)

    if cycle is not None:
        derive_cycle_state(cycle)
    hospital.touch()
    return correction


def _rederive_grade_from_corrections(cycle, review, force_scored=False):
    grade = store.grades.get(review.get("grade_id"))
    if grade is None:
        return
    baseline = review.get("preliminary_composite_score")
    if baseline is None:
        baseline = grade.get("composite_score")
    total = to_decimal(baseline or 0)
    for correction in corrections_of_review(review["id"]):
        if correction.get("status") == "ACCEPTED":
            total += to_decimal(correction.get("delta_points") or 0)
    total = to_decimal(total).quantize(to_decimal("0.01"))

    run = store.score_runs.get(grade.get("score_run_id"))
    reliability = run.get("reliability_weight") if run else None
    _base, letter, capped = grade_assignment(total, reliability)
    grade["composite_score"] = total
    grade["letter_grade"] = letter
    grade["grade_cap_applied"] = capped
    if not force_scored:
        grade["status"] = "CORRECTED"
    else:
        grade["status"] = "SCORED"
    grade.touch()

    review["status"] = "CORRECTION_REQUESTED"
    review.touch()


# ---------------------------------------------------------------------------
# Publication
# ---------------------------------------------------------------------------

def publish_cycle(cycle):
    # PRD §3.7 `embargo_release_readiness`: a cycle is publishable when every
    # grade's status is `SCORED`, `CORRECTED` or `CHAR_EXEMPT`, no review is
    # `PENDING`, no correction is `PENDING` or `ACCEPTED`, and the clock is at or
    # after `publication_date`. Three of those are conditions on the clock and
    # the children rather than caller obligations, so the derived state is
    # brought up to date before the verdict is read.
    derive_cycle_state(cycle)
    _sweep_clock_driven_closures(cycle)
    state = derive_cycle_state(cycle)
    if state == "PUBLISHED":
        raise ApiError(ERR_CYCLE_ALREADY_PUBLISHED)

    publication = parse_instant(cycle.get("publication_date"))
    if publication is not None and clock.now() < publication:
        raise ApiError(ERR_EMBARGO_ACTIVE)

    for grade in grades_of_cycle(cycle["id"]):
        if grade.get("status") == "WITHHELD" and not grade.get("withheld_reason"):
            raise ApiError(ERR_CYCLE_GRADES_UNRESOLVED)

    for review in reviews_of_cycle(cycle["id"]):
        if review.get("status") == "PENDING":
            raise ApiError(ERR_REVIEWS_PENDING)

    cycle["state"] = "PUBLISHED"
    cycle["embargo_lifted"] = True
    cycle.touch()
    _recompute_cycle_counters(cycle)

    for grade in grades_of_cycle(cycle["id"]):
        hospital = store.hospitals.get(grade["hospital_id"])
        if hospital is not None:
            recompute_worst_grade_ever(hospital)
            hospital.touch()
    return cycle


# ---------------------------------------------------------------------------
# Computed review summary
# ---------------------------------------------------------------------------

def review_summary(hospital, release_cycle_id=None):
    review = None
    cycle = None
    if release_cycle_id is not None:
        cycle = store.release_cycles.get(release_cycle_id)
        if cycle is None:
            raise ApiError(ERR_RELEASE_CYCLE_NOT_FOUND)
        for candidate in reviews_of_cycle(cycle["id"]):
            if candidate["hospital_id"] == hospital["id"]:
                review = candidate
                break
        if review is None:
            raise ApiError(ERR_REVIEW_NOT_FOUND)
    else:
        candidates = [
            item for item in store.hospital_reviews.values()
            if item["hospital_id"] == hospital["id"]
        ]
        if not candidates:
            raise ApiError(ERR_REVIEW_NOT_FOUND)
        # The review of the cycle still in play is the one being reported on;
        # an already published cycle is only consulted when nothing else exists.
        open_cycle = [
            item for item in candidates
            if (store.release_cycles.get(item.get("release_cycle_id")) or {}).get("state") != "PUBLISHED"
        ]
        if open_cycle:
            candidates = open_cycle
        candidates.sort(key=lambda item: (item["created_at"], item["id"]))
        review = candidates[-1]
        cycle = store.release_cycles.get(review.get("release_cycle_id"))

    grade = store.grades.get(review.get("grade_id"))
    challenged = list(review.get("challenged_measure_codes") or [])
    resolved = set()
    for correction in corrections_of_review(review["id"]):
        if correction.get("status") in ("ACCEPTED", "REJECTED"):
            resolved.update(correction.get("corrected_measure_codes") or [])

    return {
        "hospital_id": hospital["id"],
        "release_cycle_id": cycle["id"] if cycle else None,
        "review_status": review.get("status"),
        "challenged_count": len(challenged),
        "unresolved_challenged_count": len([code for code in challenged if code not in resolved]),
        "reported_composite_score": grade.get("composite_score") if grade else None,
        "base_grade_letter": base_letter_for(grade.get("composite_score")) if grade else None,
        "letter_grade": grade.get("letter_grade") if grade else None,
    }