"""Jurisdictional screening and employer size-band classification.

Implements calculations.timeliness_deadline_resolution and
calculations.employer_size_band_classification from SCAFFOLD section 1.3
(PRD sections 3.1 and 3.2). The evaluation order is pinned: the size screen
runs FIRST, timeliness SECOND.
"""

from datetime import timedelta

import constants
from store import db


def size_band_for_count(count):
    """Inclusive lower bounds: 14 -> UNDER_15, 15 -> FROM_15_TO_19,
    20 -> FROM_20_TO_100, 100 -> FROM_20_TO_100, 101 -> FROM_101_TO_200."""
    if count < constants.BAND_EDGE_TITLE_VII:
        return constants.BAND_UNDER_15
    if count < constants.BAND_EDGE_ADEA:
        return constants.BAND_15_19
    if count <= constants.BAND_EDGE_CAP_T1_MAX:
        return constants.BAND_20_100
    if count <= constants.BAND_EDGE_CAP_T2_MAX:
        return constants.BAND_101_200
    if count <= constants.BAND_EDGE_CAP_T3_MAX:
        return constants.BAND_201_500
    return constants.BAND_OVER_500


def match_agency(state_code):
    """Auto-match a DeferralAgency by the employer's state_code (or None)."""
    for agency in db.deferral_agencies.values():
        if agency["state_code"] == state_code:
            return agency
    return None


def basis_is_covered(basis, employee_count_at_incident, agency):
    """The size/coverage screen for one asserted basis.

    AGE requires the snapshot headcount >= ADEA_MIN_EMPLOYEES AND (no matched
    agency OR the agency covers age). Every other basis requires the snapshot
    >= TITLE_VII_MIN_EMPLOYEES. The employer's current headcount is never
    consulted.
    """
    if basis == constants.BASIS_AGE:
        return employee_count_at_incident >= constants.ADEA_MIN_EMPLOYEES and (
            agency is None or agency["covers_age"]
        )
    return employee_count_at_incident >= constants.TITLE_VII_MIN_EMPLOYEES


def run_screening(basis_codes, incident_date, received_date, employee_count_at_incident, agency):
    """Full intake screening. Returns a dict with the computed fields.

    filing_deadline_date = incident_date + deadline_days, where deadline_days
    is the matched agency's filing_deadline_days or the 180-day federal
    default. Timeliness is INCLUSIVE: received_date <= filing_deadline_date.
    """
    deadline_days = (
        agency["filing_deadline_days"]
        if agency is not None
        else constants.FEDERAL_DEFAULT_DEADLINE_DAYS
    )
    filing_deadline_date = incident_date + timedelta(days=deadline_days)
    timely = received_date <= filing_deadline_date

    covered_bases = [
        b
        for b in basis_codes
        if basis_is_covered(b, employee_count_at_incident, agency)
    ]

    # Pinned order: size screen first, timeliness second.
    if not covered_bases:
        outcome = constants.JURISDICTION_DISMISSED_NO_JURISDICTION
    elif not timely:
        outcome = constants.JURISDICTION_DISMISSED_UNTIMELY
    else:
        outcome = constants.JURISDICTION_TIMELY_CONFIRMED

    if outcome == constants.JURISDICTION_TIMELY_CONFIRMED:
        if agency is not None and agency["work_sharing_policy"] == constants.POLICY_FEPA_EXCLUSIVE:
            owner = constants.OWNER_FEPA
            case_status = constants.CHARGE_DELEGATED_TO_FEPA
        else:
            owner = constants.OWNER_EEOC
            case_status = constants.CHARGE_DOCKETED
    else:
        owner = constants.OWNER_NONE
        case_status = outcome

    dual_filed = agency is not None and agency["work_sharing_policy"] in (
        constants.POLICY_DUAL_FILE_DEFAULT,
        constants.POLICY_FEPA_EXCLUSIVE,
    )

    return {
        "deferral_agency_id": agency["id"] if agency is not None else None,
        "covered_bases": covered_bases,
        "jurisdiction_outcome": outcome,
        "filing_deadline_date": filing_deadline_date,
        "investigation_owner": owner,
        "dual_filed": dual_filed,
        "case_status": case_status,
    }
