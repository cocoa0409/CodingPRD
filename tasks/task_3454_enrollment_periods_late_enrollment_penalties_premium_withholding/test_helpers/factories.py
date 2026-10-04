"""Request-payload builders.

Each builder returns a dict that satisfies every declared input constraint of
the operation it names, and accepts ``**overrides`` so a test can perturb one
field without restating the rest.  Overrides are applied by ``update`` after
the defaults are assembled, so no field is ever passed twice.

Conventions applied everywhere:

* money travels as JSON integers (cents), never as strings or floats;
* ``*_month`` fields are ``YYYY-MM`` strings and ``*_date``/``date_of_birth``
  fields are ``YYYY-MM-DD`` strings, per PRD section 2.4;
* optional inputs (``coverage_end_month``, ``employment_end_month``,
  ``is_drug_coverage_creditable``, ``requested_effective_month``) are omitted
  from the payload unless the caller supplies them, so the server-side
  defaults the PRD names are the thing under test.
"""

import itertools

from .constants import (
    FILING_SINGLE,
    IRMAA_JOINT_FLOORS_CENTS,
    IRMAA_SINGLE_FLOORS_CENTS,
    LIFE_EVENT_WORK_STOPPAGE,
    MISINFORM_FEDERAL_AGENCY,
    PART_B,
    RELIEF_RETROACTIVE_ENROLLMENT,
    RS2026_PART_B_STANDARD_CENTS,
    RS2026_PART_B_SURCHARGES_CENTS,
    RS2026_PART_D_NATIONAL_BASE_CENTS,
    RS2026_PART_D_SURCHARGES_CENTS,
    RS2027_PART_B_STANDARD_CENTS,
    RS2027_PART_B_SURCHARGES_CENTS,
    RS2027_PART_D_NATIONAL_BASE_CENTS,
    RS2027_PART_D_SURCHARGES_CENTS,
    TARGET_METHOD_WITHHOLDING,
    VERIFICATION_VERIFIED,
)

_SEQUENCE = itertools.count(1)


def next_sequence():
    """A monotonically increasing integer for unique-per-test literals."""
    return next(_SEQUENCE)


# --- Beneficiaries (PRD section 3.1) -----------------------------------------


def beneficiary_payload(**overrides):
    serial = next_sequence()
    payload = {
        "full_name": "Test Beneficiary {0:04d}".format(serial),
        "date_of_birth": "1961-12-14",
    }
    payload.update(overrides)
    return payload


# --- Rate schedules (PRD section 3.5) -----------------------------------------


def irmaa_brackets(part_b_surcharges, part_d_surcharges,
                   single_floors=None, joint_floors=None):
    """Assemble the six-bracket IRMAA array in ascending floor order.

    ``part_b_surcharges`` and ``part_d_surcharges`` are 6-tuples indexed by
    tier 0..5.  Floors default to the canonical schedule floors.
    """
    single_floors = (
        IRMAA_SINGLE_FLOORS_CENTS if single_floors is None else single_floors
    )
    joint_floors = IRMAA_JOINT_FLOORS_CENTS if joint_floors is None else joint_floors
    return [
        {
            "tier": tier,
            "single_floor_cents": single_floors[tier],
            "joint_floor_cents": joint_floors[tier],
            "part_b_surcharge_cents": part_b_surcharges[tier],
            "part_d_surcharge_cents": part_d_surcharges[tier],
        }
        for tier in range(6)
    ]


def rate_schedule_payload(**overrides):
    """The canonical 2026 schedule: B standard 18500, D national base 3450."""
    payload = {
        "coverage_year": 2026,
        "part_b_standard_cents": RS2026_PART_B_STANDARD_CENTS,
        "part_d_national_base_cents": RS2026_PART_D_NATIONAL_BASE_CENTS,
        "irmaa_brackets": irmaa_brackets(
            RS2026_PART_B_SURCHARGES_CENTS, RS2026_PART_D_SURCHARGES_CENTS
        ),
    }
    payload.update(overrides)
    return payload


def rate_schedule_2026_payload(**overrides):
    return rate_schedule_payload(**overrides)


def rate_schedule_2027_payload(**overrides):
    """The canonical 2027 schedule: B standard 19000, D national base 3600."""
    payload = {
        "coverage_year": 2027,
        "part_b_standard_cents": RS2027_PART_B_STANDARD_CENTS,
        "part_d_national_base_cents": RS2027_PART_D_NATIONAL_BASE_CENTS,
        "irmaa_brackets": irmaa_brackets(
            RS2027_PART_B_SURCHARGES_CENTS, RS2027_PART_D_SURCHARGES_CENTS
        ),
    }
    payload.update(overrides)
    return payload


# --- Coverage enrollments (PRD section 3.2) -------------------------------------


def enrollment_payload(beneficiary_id, part=PART_B, **overrides):
    payload = {"beneficiary_id": beneficiary_id, "part": part}
    payload.update(overrides)
    return payload


def switch_collection_method_payload(target_method=TARGET_METHOD_WITHHOLDING,
                                     **overrides):
    payload = {"target_method": target_method}
    payload.update(overrides)
    return payload


# --- Employer coverage records (PRD section 3.3) ---------------------------------


def employer_coverage_payload(beneficiary_id, **overrides):
    """Required inputs only; the optional end months and the creditable-drug
    flag stay absent unless a test supplies them."""
    serial = next_sequence()
    payload = {
        "beneficiary_id": beneficiary_id,
        "employer_name": "Employer {0:04d}".format(serial),
        "employer_size": 30,
        "coverage_start_month": "2024-01",
    }
    payload.update(overrides)
    return payload


def verify_decision_payload(decision=VERIFICATION_VERIFIED, **overrides):
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def end_coverage_payload(coverage_end_month, employment_end_month, **overrides):
    payload = {
        "coverage_end_month": coverage_end_month,
        "employment_end_month": employment_end_month,
    }
    payload.update(overrides)
    return payload


# --- Tax records (PRD section 3.5) -------------------------------------------------


def tax_record_payload(beneficiary_id, tax_year, magi_cents,
                       filing_status=FILING_SINGLE, **overrides):
    payload = {
        "beneficiary_id": beneficiary_id,
        "tax_year": tax_year,
        "magi_cents": magi_cents,
        "filing_status": filing_status,
    }
    payload.update(overrides)
    return payload


# --- Premium determinations (PRD section 3.5) ---------------------------------------


def premium_determination_payload(beneficiary_id, coverage_year, part=PART_B,
                                  **overrides):
    payload = {
        "beneficiary_id": beneficiary_id,
        "coverage_year": coverage_year,
        "part": part,
    }
    payload.update(overrides)
    return payload


# --- Appeals (PRD section 3.6) --------------------------------------------------------


def appeal_payload(premium_determination_id, **overrides):
    payload = {
        "premium_determination_id": premium_determination_id,
        "life_event_type": LIFE_EVENT_WORK_STOPPAGE,
        "event_date": "2026-11-02",
        "claimed_magi_cents": 9000000,
    }
    payload.update(overrides)
    return payload


def appeal_decision_payload(decision, **overrides):
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def appeal_response_payload(note="Additional documentation attached.", **overrides):
    payload = {"note": note}
    payload.update(overrides)
    return payload


# --- Withholding arrangements (PRD section 3.7) ---------------------------------------


def withholding_arrangement_payload(beneficiary_id, monthly_benefit_cents=21000,
                                    **overrides):
    payload = {
        "beneficiary_id": beneficiary_id,
        "monthly_benefit_cents": monthly_benefit_cents,
    }
    payload.update(overrides)
    return payload


def adjust_arrangement_payload(monthly_benefit_cents, **overrides):
    payload = {"monthly_benefit_cents": monthly_benefit_cents}
    payload.update(overrides)
    return payload


# --- Invoice payment (PRD section 3.7) --------------------------------------------------


def pay_invoice_payload(amount_cents, **overrides):
    payload = {"amount_cents": amount_cents}
    payload.update(overrides)
    return payload


# --- Plan elections (PRD sections 2.7 and 3.8) -------------------------------------------


def election_payload(beneficiary_id, election_window, target_coverage,
                     expected_beneficiary_version, **overrides):
    payload = {
        "beneficiary_id": beneficiary_id,
        "election_window": election_window,
        "target_coverage": target_coverage,
        "expected_beneficiary_version": expected_beneficiary_version,
    }
    payload.update(overrides)
    return payload


# --- Equitable relief cases (PRD section 3.9) ----------------------------------------------


def relief_case_payload(beneficiary_id, part=PART_B, **overrides):
    """Defaults to a retroactive-enrollment filing, which requires
    ``requested_effective_month``; pure penalty-waiver filings omit it."""
    serial = next_sequence()
    payload = {
        "beneficiary_id": beneficiary_id,
        "relief_type": RELIEF_RETROACTIVE_ENROLLMENT,
        "part": part,
        "claimed_misinform_source": MISINFORM_FEDERAL_AGENCY,
        "description": "Misinformation case {0:04d}".format(serial),
        "requested_effective_month": "2026-01",
    }
    payload.update(overrides)
    return payload


def relief_decision_payload(decision, **overrides):
    payload = {"decision": decision}
    payload.update(overrides)
    return payload
