"""Employers: registration, network listings and grade utilisation."""

from calculations import employer_utilization_index, round_half_up
from db import BaseRecord, format_instant, parse_instant, store
from errors import (
    ApiError,
    ERR_BENEFIT_WINDOW_CONTAINMENT_CONFLICT,
    ERR_BENEFIT_WINDOW_INVALID,
    ERR_EMPLOYER_NOT_FOUND,
    ERR_HOSPITAL_NOT_FOUND,
    ERR_INVALID_MINIMUM_LETTER,
    ERR_INVALID_REQUEST,
)

PURCHASER_TYPES = ("SELF_INSURED_EMPLOYER", "COALITION", "HEALTH_PLAN")
MINIMUM_LETTERS = ("A", "B", "C", "D")


class Employer(BaseRecord):
    entity_name = "Employer"


def get_employer(employer_id):
    employer = store.employers.get(employer_id)
    if employer is None:
        raise ApiError(ERR_EMPLOYER_NOT_FOUND)
    return employer


# ---------------------------------------------------------------------------
# Shared validation
# ---------------------------------------------------------------------------

def _validate_common(name=None, purchaser_type=None, minimum_letter=None,
                     window_from=None, window_to=None, network_ids=None):
    if purchaser_type is not None and purchaser_type not in PURCHASER_TYPES:
        raise ApiError(ERR_INVALID_REQUEST)
    if minimum_letter is not None and minimum_letter not in MINIMUM_LETTERS:
        raise ApiError(ERR_INVALID_MINIMUM_LETTER)

    parsed_from = None
    parsed_to = None
    if window_from is not None:
        if not isinstance(window_from, str):
            raise ApiError(ERR_INVALID_REQUEST)
        try:
            parsed_from = parse_instant(window_from)
        except ValueError:
            raise ApiError(ERR_INVALID_REQUEST)
    if window_to is not None:
        if not isinstance(window_to, str):
            raise ApiError(ERR_INVALID_REQUEST)
        try:
            parsed_to = parse_instant(window_to)
        except ValueError:
            raise ApiError(ERR_INVALID_REQUEST)
    if parsed_from is not None and parsed_to is not None and not (parsed_to > parsed_from):
        raise ApiError(ERR_BENEFIT_WINDOW_INVALID)

    if network_ids is not None:
        if not isinstance(network_ids, list):
            raise ApiError(ERR_INVALID_REQUEST)
        for hospital_id in network_ids:
            if not isinstance(hospital_id, str) or hospital_id not in store.hospitals:
                raise ApiError(ERR_HOSPITAL_NOT_FOUND)

    return parsed_from, parsed_to


def _collapse(network_ids):
    """Duplicate entries collapse to the first occurrence."""
    collapsed = []
    for hospital_id in network_ids or []:
        if hospital_id not in collapsed:
            collapsed.append(hospital_id)
    return collapsed


def _check_containment(scope_type, scope_letter, window_from, window_to, exclude_id=None):
    """Two windows in the same scope may not stand in a containment relation.

    PRD §3.8: "Two purchasers may not overlap in a way that hides a hospital's
    standing." The overlap that hides standing is a containment either way — an
    incoming window swallowing an existing one, or fitting wholly inside it —
    and PRD §3.8's specific rule refuses a window that contains another's.
    Windows that merely touch (one's `benefit_window_to` equals the other's
    `benefit_window_from`) are accepted, so the comparison is over the half-open
    [from, to) intervals declared in §3.8.
    """
    if window_from is None or window_to is None:
        return
    for employer in store.employers.values():
        if exclude_id is not None and employer["id"] == exclude_id:
            continue
        if employer.get("purchaser_type") != scope_type:
            continue
        if employer.get("minimum_acceptable_letter") != scope_letter:
            continue
        try:
            other_from = parse_instant(employer.get("benefit_window_from"))
            other_to = parse_instant(employer.get("benefit_window_to"))
        except (ValueError, TypeError):
            continue
        if other_from is None or other_to is None:
            continue
        keeps_other = window_from <= other_from and window_to >= other_to
        fits_inside = other_from <= window_from and other_to >= window_to
        # PRD §3.8: "windows that merely touch — one's `benefit_window_to`
        # equalling the other's `benefit_window_from` — are accepted", so the
        # endpoint-equality case is not a containment.
        touches = window_from == other_to or window_to == other_from
        if (keeps_other or fits_inside) and not touches:
            raise ApiError(ERR_BENEFIT_WINDOW_CONTAINMENT_CONFLICT)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def create_employer(payload):
    name = payload.get("name")
    if not isinstance(name, str) or name.strip() == "":
        raise ApiError(ERR_INVALID_REQUEST)
    purchaser_type = payload.get("purchaser_type")
    minimum_letter = payload.get("minimum_acceptable_letter")
    window_from = payload.get("benefit_window_from")
    window_to = payload.get("benefit_window_to")
    network_ids = payload.get("network_hospital_ids", [])

    parsed_from, parsed_to = _validate_common(
        purchaser_type=purchaser_type,
        minimum_letter=minimum_letter,
        window_from=window_from,
        window_to=window_to,
        network_ids=network_ids,
    )
    if parsed_from is None or parsed_to is None:
        raise ApiError(ERR_INVALID_REQUEST)

    _check_containment(purchaser_type, minimum_letter, parsed_from, parsed_to)

    collapsed = _collapse(network_ids)
    employer = Employer(
        name=name,
        purchaser_type=purchaser_type,
        status="ACTIVE",
        network_hospital_ids=collapsed,
        benefit_window_from=format_instant(parsed_from),
        benefit_window_to=format_instant(parsed_to),
        network_hospital_count=len(collapsed),
        minimum_acceptable_letter=minimum_letter,
        eligible_hospital_count=0,
        utilization_index=None,
    )
    store.employers[employer["id"]] = employer
    recompute_employer_counters(employer)
    return employer


# ---------------------------------------------------------------------------
# Network listings
# ---------------------------------------------------------------------------

def set_network_listing(employer, payload):
    network_ids = payload.get("network_hospital_ids")
    minimum_letter = payload.get("minimum_acceptable_letter")
    window_from = payload.get("benefit_window_from")
    window_to = payload.get("benefit_window_to")

    if network_ids is None:
        raise ApiError(ERR_INVALID_REQUEST)
    if minimum_letter is None:
        raise ApiError(ERR_INVALID_REQUEST)
    if window_from is None or window_to is None:
        raise ApiError(ERR_INVALID_REQUEST)

    parsed_from, parsed_to = _validate_common(
        purchaser_type=employer.get("purchaser_type"),
        minimum_letter=minimum_letter,
        window_from=window_from,
        window_to=window_to,
        network_ids=network_ids,
    )
    _check_containment(
        employer.get("purchaser_type"),
        minimum_letter,
        parsed_from,
        parsed_to,
        exclude_id=employer["id"],
    )

    collapsed = _collapse(network_ids)
    employer["network_hospital_ids"] = collapsed
    employer["network_hospital_count"] = len(collapsed)
    employer["minimum_acceptable_letter"] = minimum_letter
    employer["benefit_window_from"] = format_instant(parsed_from)
    employer["benefit_window_to"] = format_instant(parsed_to)
    employer["status"] = "ACTIVE"
    recompute_employer_counters(employer)
    employer.touch()
    return employer


# ---------------------------------------------------------------------------
# Derived counters
# ---------------------------------------------------------------------------

def recompute_employer_counters(employer):
    """Eligibility and utilisation against the currently published grades."""
    network = list(employer.get("network_hospital_ids") or [])
    graded_letters = []
    graded_composites = []

    for hospital_id in network:
        grade = _best_grade(hospital_id)
        if grade is None:
            continue
        graded_letters.append(grade.get("letter_grade"))
        graded_composites.append(grade.get("composite_score"))

    eligible, index, propensity = employer_utilization_index(
        employer.get("minimum_acceptable_letter"), graded_letters, graded_composites
    )
    # The propensity-adjusted indicator is a points figure, carried at the
    # two-decimal precision of the composite it is derived from.
    if propensity is not None:
        propensity = round_half_up(propensity, 2)
    employer["eligible_hospital_count"] = eligible
    employer["utilization_index"] = index
    employer["propensity_adjusted_indicator"] = propensity
    return employer


def _best_grade(hospital_id):
    """The hospital's grade row used for utilisation.

    Rows with status SCORED, CORRECTED or CHAR_EXEMPT and a non-null composite,
    de-duplicated by hospital keeping the lowest created_at.
    """
    candidates = [
        grade for grade in store.grades.values()
        if grade["hospital_id"] == hospital_id
        and grade.get("status") in ("SCORED", "CORRECTED", "CHAR_EXEMPT")
        and grade.get("composite_score") is not None
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item["created_at"], item["id"]))
    return candidates[0]


def employers_listing_hospital(hospital_id, minimum_letter=None):
    rows = []
    for employer in store.employers.values():
        if hospital_id not in (employer.get("network_hospital_ids") or []):
            continue
        if minimum_letter is not None and employer.get("minimum_acceptable_letter") != minimum_letter:
            continue
        rows.append(employer)
    rows.sort(key=lambda item: (item["created_at"], item["id"]))
    return rows