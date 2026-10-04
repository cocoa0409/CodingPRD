"""Reanalysis requests: raising, reviewing, granting and refuting."""

from decimal import Decimal

from calculations import (
    DOMAINS,
    composite_adjusted_for_reanalysis,
    derived_measure_value,
    documents_sufficient,
    grade_assignment,
    round_half_up,
    safe_practice_credit,
    to_decimal,
    verification_completeness,
)
from db import BaseRecord, store
from errors import (
    ApiError,
    ERR_HOSPITAL_OWNER_MISMATCH,
    ERR_INSUFFICIENT_PERMISSIONS,
    ERR_INVALID_REQUEST,
    ERR_REANALYSIS_DOCUMENTS_INSUFFICIENT,
    ERR_REANALYSIS_NOT_UNDER_REVIEW,
    ERR_REANALYSIS_REFERENCE_STALE,
    ERR_REANALYSIS_REGRESSION_FORBIDDEN,
    ERR_REANALYSIS_REQUEST_NOT_FOUND,
    ERR_REANALYSIS_SELECTOR_ARITY,
    ERR_REANALYSIS_SELECTOR_UNRESOLVED,
    ERR_REANALYSIS_SURVEY_MISMATCH,
)

from services.hospitals import (
    all_surveys_unverified,
    ensure_hospital_set,
    mark_disclosure_unverified,
    materialise_measures,
    measure_rows_for_hospital,
    recompute_source_document_count,
)
from services.scoring import hospital_grades
from services.surveys import get_survey, recompute_reliability

DECISIONS = ("START_REVIEW", "GRANT", "REFUTE", "WITHDRAW")

SELECTOR_KINDS = ("measure_code", "domain", "source_program_id")


class ReanalysisRequest(BaseRecord):
    entity_name = "ReanalysisRequest"


# ---------------------------------------------------------------------------
# Lookups and selector resolution
# ---------------------------------------------------------------------------

def _refresh_reference_stale(request):
    """Recompute `reference_stale` from the live survey and hospital pins.

    PRD §3.6: "On entering review the system recomputes the request's
    `reference_stale` flag, which is true exactly when the survey's pinned
    `methodology_version_id` differs from the hospital's currently pinned
    `active_methodology_version_id`." The flag is a pure predicate over two
    live pins, so it is refreshed on every read and every forward decision
    rather than frozen at `START_REVIEW`.
    """
    survey = store.surveys.get(request.get("survey_id"))
    hospital = store.hospitals.get(request.get("hospital_id"))
    if survey is None or hospital is None:
        return request
    request["reference_stale"] = (
        survey.get("methodology_version_id")
        != hospital.get("active_methodology_version_id")
    )
    return request


def get_reanalysis_request(request_id):
    request = store.reanalysis_requests.get(request_id)
    if request is None:
        raise ApiError(ERR_REANALYSIS_REQUEST_NOT_FOUND)
    return _refresh_reference_stale(request)


def get_hospital_request(hospital_id, request_id):
    request = store.reanalysis_requests.get(request_id)
    if request is None or request["hospital_id"] != hospital_id:
        raise ApiError(ERR_REANALYSIS_REQUEST_NOT_FOUND)
    return _refresh_reference_stale(request)


def _validate_selectors(selectors):
    if not isinstance(selectors, list):
        raise ApiError(ERR_REANALYSIS_SELECTOR_ARITY)
    if len(selectors) < 1 or len(selectors) > 20:
        raise ApiError(ERR_REANALYSIS_SELECTOR_ARITY)
    normalised = []
    for entry in selectors:
        if not isinstance(entry, dict):
            raise ApiError(ERR_REANALYSIS_SELECTOR_ARITY)
        kinds = [key for key in SELECTOR_KINDS if entry.get(key) is not None]
        if len(kinds) != 1:
            raise ApiError(ERR_REANALYSIS_SELECTOR_ARITY)
        kind = kinds[0]
        value = entry.get(kind)
        if not isinstance(value, str) or value.strip() == "":
            raise ApiError(ERR_REANALYSIS_SELECTOR_ARITY)
        normalised.append({kind: value})
    return normalised


def _resolve_selectors(methodology_version, selectors):
    """Every selector must resolve inside the survey's pinned version."""
    definitions = methodology_version.get("measure_definitions") or []
    codes = {definition["measure_code"] for definition in definitions}
    domains = {definition["domain"] for definition in definitions}
    for selector in selectors:
        if "measure_code" in selector:
            if selector["measure_code"] not in codes:
                raise ApiError(ERR_REANALYSIS_SELECTOR_UNRESOLVED)
        elif "domain" in selector:
            if selector["domain"] not in domains or selector["domain"] not in DOMAINS:
                raise ApiError(ERR_REANALYSIS_SELECTOR_UNRESOLVED)


def selected_measure_codes(hospital, survey, selectors):
    """The pinned version's measure codes the selector list names."""
    methodology_version = store.methodology_versions.get(survey.get("methodology_version_id"))
    if methodology_version is None:
        return []
    definitions = methodology_version.get("measure_definitions") or []
    codes = []
    for definition in definitions:
        code = definition["measure_code"]
        domain = definition["domain"]
        for selector in selectors:
            if "measure_code" in selector and selector["measure_code"] == code:
                codes.append(code)
                break
            if "domain" in selector and selector["domain"] == domain:
                codes.append(code)
                break
            if "source_program_id" in selector:
                row = _row_for_code(hospital["id"], code)
                if row is not None and row.get("source_program_id") == selector["source_program_id"]:
                    codes.append(code)
                    break
    seen = []
    for code in codes:
        if code not in seen:
            seen.append(code)
    return seen


def _row_for_code(hospital_id, measure_code):
    rows = [
        row for row in store.survey_measures.values()
        if row["hospital_id"] == hospital_id and row["measure_code"] == measure_code
    ]
    if not rows:
        return None
    rows.sort(key=lambda item: (item["created_at"], item["id"]))
    return rows[0]


def _validate_documents(documents):
    if documents is None:
        return []
    if not isinstance(documents, list):
        raise ApiError(ERR_INVALID_REQUEST)
    normalised = []
    for entry in documents:
        if not isinstance(entry, dict):
            raise ApiError(ERR_INVALID_REQUEST)
        code = entry.get("document_code")
        if not isinstance(code, str) or code.strip() == "":
            raise ApiError(ERR_INVALID_REQUEST)
        normalised.append({
            "document_code": code,
            "issued_on": entry.get("issued_on"),
        })
    return normalised


# ---------------------------------------------------------------------------
# Raising
# ---------------------------------------------------------------------------

def create_reanalysis_request(hospital, payload):
    survey_id = payload.get("survey_id")
    if not isinstance(survey_id, str) or survey_id.strip() == "":
        raise ApiError(ERR_INVALID_REQUEST)
    survey = get_survey(survey_id)
    if survey["hospital_id"] != hospital["id"]:
        raise ApiError(ERR_REANALYSIS_SURVEY_MISMATCH)

    selectors = _validate_selectors(payload.get("subset_selector"))
    documents = _validate_documents(payload.get("supporting_documents"))
    requested_delta = payload.get("requested_delta")
    if requested_delta is not None:
        if isinstance(requested_delta, bool) or not isinstance(requested_delta, (int, float, str)):
            raise ApiError(ERR_INVALID_REQUEST)
        requested_delta = to_decimal(requested_delta)

    request = ReanalysisRequest(
        hospital_id=hospital["id"],
        survey_id=survey_id,
        subset_selector=selectors,
        supporting_documents=documents,
        requested_delta=requested_delta,
        adjusted_delta=Decimal("0"),
        non_regression_confirmed=False,
        reference_stale=False,
        documents_sufficient=documents_sufficient(
            [entry["document_code"] for entry in documents]
        ),
        status="PENDING",
        safe_practice_credit=safe_practice_credit(
            [entry["document_code"] for entry in documents]
        ),
        verification_completeness=verification_completeness(
            [entry["document_code"] for entry in documents]
        ),
    )
    store.reanalysis_requests[request["id"]] = request
    survey["reanalysis_request_count"] = sum(
        1 for item in store.reanalysis_requests.values() if item["survey_id"] == survey_id
    )
    survey.touch()
    hospital.touch()
    return request


# ---------------------------------------------------------------------------
# Decisions
# ---------------------------------------------------------------------------

def decide_reanalysis_request(hospital, request, decision, acting_user_id):
    if not isinstance(decision, str) or decision.strip() == "":
        raise ApiError(ERR_INVALID_REQUEST)
    decision = decision.strip().upper()
    if decision not in DECISIONS:
        raise ApiError(ERR_INVALID_REQUEST)

    if decision == "WITHDRAW":
        if acting_user_id != hospital["id"]:
            raise ApiError(ERR_HOSPITAL_OWNER_MISMATCH)
        if request.get("status") != "PENDING":
            raise ApiError(ERR_REANALYSIS_NOT_UNDER_REVIEW)
        request["status"] = "WITHDRAWN"
        request["adjusted_delta"] = Decimal("0")
        request.touch()
        hospital.touch()
        return request

    # PRD §3.6: the forward decisions — `START_REVIEW`, `GRANT` and `REFUTE` —
    # are "a `VerificationAnalyst` moves the request forward by posting a
    # `decision`". The role gate therefore covers the whole forward surface, and
    # only `WITHDRAW` is the hospital's own compensating move. The route admits
    # both roles so that the withdrawal path stays reachable; without this check
    # a respondent could advance (or grant) its own request.
    if acting_user_id == hospital["id"]:
        raise ApiError(ERR_INSUFFICIENT_PERMISSIONS)

    survey = store.surveys.get(request.get("survey_id"))
    if survey is None or survey["hospital_id"] != hospital["id"]:
        raise ApiError(ERR_REANALYSIS_SURVEY_MISMATCH)

    if decision == "START_REVIEW":
        if request.get("status") != "PENDING":
            raise ApiError(ERR_REANALYSIS_NOT_UNDER_REVIEW)
        methodology_version = store.methodology_versions.get(survey.get("methodology_version_id"))
        if methodology_version is None:
            raise ApiError(ERR_REANALYSIS_SELECTOR_UNRESOLVED)
        selectors = request.get("subset_selector") or []
        if len(selectors) < 1 or len(selectors) > 20:
            raise ApiError(ERR_REANALYSIS_SELECTOR_ARITY)
        _resolve_selectors(methodology_version, selectors)
        request["status"] = "UNDER_REVIEW"
        _refresh_reference_stale(request)
        request.touch()
        _invalidate_ready_set(hospital)
        hospital.touch()
        return request

    if decision in ("GRANT", "REFUTE"):
        if request.get("status") != "UNDER_REVIEW":
            raise ApiError(ERR_REANALYSIS_NOT_UNDER_REVIEW)
        if request.get("survey_id") != survey["id"]:
            raise ApiError(ERR_REANALYSIS_SURVEY_MISMATCH)

    if decision == "GRANT":
        # The reference-stale guard is a precondition of the GRANT itself, so
        # it is evaluated before the evidentiary and non-regression checks.
        _refresh_reference_stale(request)
        if request.get("reference_stale"):
            raise ApiError(ERR_REANALYSIS_REFERENCE_STALE)
        if not request.get("documents_sufficient"):
            raise ApiError(ERR_REANALYSIS_DOCUMENTS_INSUFFICIENT)
        requested = request.get("requested_delta")
        candidate = to_decimal(requested) if requested is not None else _recomputed_delta(
            hospital, survey, request
        )
        if candidate < to_decimal("-0.01"):
            raise ApiError(ERR_REANALYSIS_REGRESSION_FORBIDDEN)
        request["adjusted_delta"] = (
            to_decimal(requested) if requested is not None else round_half_up(candidate, 2)
        )
        request["non_regression_confirmed"] = True
        request["status"] = "GRANTED"
        request.touch()
        _apply_grant_cascade(hospital, survey, request)
        hospital.touch()
        return request

    # REFUTE
    request["adjusted_delta"] = Decimal("0")
    request["status"] = "REFUTED"
    request.touch()
    _apply_refute_cascade(hospital, request)
    hospital.touch()
    return request


def _recomputed_delta(hospital, survey, request):
    """Recompute the adjustment from the selected measures when no delta was given."""
    methodology_version = store.methodology_versions.get(survey.get("methodology_version_id"))
    if methodology_version is None:
        return Decimal("0")
    definitions = {entry["measure_code"]: entry for entry in methodology_version.get("measure_definitions") or []}
    codes = selected_measure_codes(hospital, survey, request.get("subset_selector") or [])
    total = Decimal("0")
    for code in codes:
        definition = definitions.get(code)
        row = _row_for_code(hospital["id"], code)
        if definition is None or row is None:
            continue
        scale = to_decimal(definition.get("scale_factor", 1))
        current = to_decimal(row.get("derived_value") or 0)
        source_derived = derived_measure_value(row.get("raw_value"), definition.get("derivation_rule", "NONE"))
        if source_derived is None:
            continue
        total += scale * (to_decimal(source_derived) - current)
    return total


def _invalidate_ready_set(hospital):
    """A reanalysis under review invalidates a materialised set."""
    measure_set = ensure_hospital_set(hospital)
    if measure_set.get("readiness_state") == "READY":
        measure_set["readiness_state"] = "INCOMPLETE"
        measure_set.touch()


def _apply_grant_cascade(hospital, survey, request):
    # Hop 1 + 2: each selected measure becomes PUBLIC_SOURCE_SUBSTITUTED and the
    # measure set is rematerialised, recomputing the substituted count.
    codes = selected_measure_codes(hospital, survey, request.get("subset_selector") or [])
    for code in codes:
        row = _row_for_code(hospital["id"], code)
        if row is None:
            continue
        row["measure_status"] = "PUBLIC_SOURCE_SUBSTITUTED"
        row.touch()

    measure_set = ensure_hospital_set(hospital)
    materialise_measures(hospital, measure_set)
    # PRD §3.6, hop 2: "each selected measure's `measure_status` becomes
    # `PUBLIC_SOURCE_SUBSTITUTED`; that measure change flips the hospital's set
    # to `INCOMPLETE` and bumps the substituted count". The set turns stale
    # immediately, so the hop is observable before the next refresh.
    if measure_set.get("readiness_state") == "READY":
        measure_set["readiness_state"] = "INCOMPLETE"
    measure_set.touch()
    measure_set.touch()

    # The survey rewind, including the certification dimension.
    if survey.get("af_status") == "VERIFIED":
        survey["af_status"] = "SUBMITTED"
        survey["af_certification_level"] = "CERTIFICATION_WITHDRAWN"
        # PRD §3.6 leaves the two dimensions "observably out of step until the
        # next acceptance re-earns `CERTIFIED`", and freezes the submission
        # dimension "until the next verification". The recorded decision is
        # therefore cleared, so the survey is once again a plain `SUBMITTED`
        # submission carrying no open verification verdict.
        survey["verification_response"] = None
    survey["reanalysis_request_count"] = sum(
        1 for item in store.reanalysis_requests.values()
        if item["survey_id"] == survey["id"] and item.get("status") == "GRANTED"
    )
    recompute_reliability(survey)
    if int(survey.get("verification_cycle") or 0) >= 2:
        survey["reliability_weight"] = round_half_up(to_decimal("0.5999"), 4)
    survey.touch()
    recompute_source_document_count(hospital)

    # Hop 3: re-derive the grade and its letter through the adjusted composite.
    _rederive_grades_for_grant(hospital, survey["methodology_version_id"], request)

    # Hop 4: the cycle state is re-derived from its children.
    from services.cycles import derive_cycle_state
    for grade in hospital_grades(hospital["id"]):
        cycle = store.release_cycles.get(grade.get("release_cycle_id"))
        if cycle is not None:
            derive_cycle_state(cycle)

    # A completed run is overtaken by the grant.
    for run in store.score_runs.values():
        if run["hospital_id"] == hospital["id"] and run.get("score_state") == "SCORED":
            run["score_state"] = "REANALYSIS_PENDING"
            run.touch()


def _rederive_grades_for_grant(hospital, methodology_version_id, request):
    from services.cycles import grade_dropped_measure_count, accepted_corrections_of_cycle

    for grade in hospital_grades(hospital["id"]):
        if grade.get("status") not in ("SCORED", "CORRECTED", "CHAR_EXEMPT"):
            continue
        cycle = store.release_cycles.get(grade.get("release_cycle_id"))
        if cycle is None or cycle.get("state") == "PUBLISHED":
            continue
        review = _review_for_grade(grade["id"])
        base = (
            to_decimal(review["preliminary_composite_score"])
            if review is not None and review.get("preliminary_composite_score") is not None
            else to_decimal(grade.get("composite_score") or 0)
        )
        deltas = [
            to_decimal(item["adjusted_delta"])
            for item in store.reanalysis_requests.values()
            if item["hospital_id"] == hospital["id"]
            and item.get("status") == "GRANTED"
            and (store.surveys.get(item.get("survey_id")) or {}).get("methodology_version_id")
            == cycle.get("methodology_version_id")
        ]
        dropped = grade_dropped_measure_count(hospital["id"], cycle.get("methodology_version_id"))
        corrections = accepted_corrections_of_cycle(cycle["id"])
        adjusted = composite_adjusted_for_reanalysis(base, deltas, dropped, corrections)

        run = store.score_runs.get(grade.get("score_run_id"))
        reliability = run.get("reliability_weight") if run else None
        _base_letter, letter, capped = grade_assignment(adjusted, reliability)
        grade["composite_score"] = adjusted
        grade["letter_grade"] = letter
        grade["grade_cap_applied"] = capped
        grade.touch()

        if run is not None:
            run["composite_score"] = adjusted
            run["letter_grade"] = letter
            run["grade_cap_applied"] = capped
            run.touch()


def _review_for_grade(grade_id):
    rows = [
        review for review in store.hospital_reviews.values() if review["grade_id"] == grade_id
    ]
    if not rows:
        return None
    rows.sort(key=lambda item: (item["created_at"], item["id"]))
    return rows[0]


def _apply_refute_cascade(hospital, request):
    """Recompute the document count; unverified disclosure fans out to measures."""
    recompute_source_document_count(hospital)
    if not all_surveys_unverified(hospital["id"]):
        return
    mark_disclosure_unverified(hospital)
    for row in measure_rows_for_hospital(hospital["id"]):
        row["measure_status"] = "REPORTED"
        row["derived_value"] = None
        row.touch()
    measure_set = ensure_hospital_set(hospital)
    measure_set["readiness_state"] = "INCOMPLETE"
    measure_set.touch()