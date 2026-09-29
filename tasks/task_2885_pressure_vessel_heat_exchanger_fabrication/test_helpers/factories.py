"""Request payload builders.

Every builder returns a payload that satisfies PRD §2.8 step 4 for its endpoint,
so a test only has to name the field it wants to bend. Two conventions matter:

* decimal and money-like fields are emitted as JSON numbers, never as strings,
  because §2.8 step 4 requires "every field carries its declared type";
* fields the PRD declares as instants are emitted as full ISO 8601 UTC instants,
  while fields it declares as calendar dates are emitted as bare dates.
"""

import itertools

from .constants import (
    AUDIT_TYPES,
    BAY_1,
    COMPONENT_SHELL,
    COMPONENT_TYPE_SHELL,
    DEFAULT_CLOCK_UTC,
    DESIGN_CODE_DIV1,
    FORM_PLATE,
    FORM_TYPE_U1A,
    FURNACE_A,
    JOINT_CATEGORY_A,
    JOINT_TYPE_BUTT,
    MTR_MINIMA_BY_SPEC,
    POSITIONS,
    PROCESS_SMAW,
    RT_EXTENT_FULL,
    SEVERITY_MAJOR,
    SEVERITY_MINOR,
    SEVERITY_OBSERVATION,
    SPEC_SA_516_70,
    TEST_SIDE_SHELL,
    TEST_TYPE_HYDROSTATIC,
    VESSEL_TYPE_PRESSURE_VESSEL,
)

_counter = itertools.count(1)
_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def next_sequence():
    """A monotonically increasing integer for building unique business keys."""
    return next(_counter)


def unique_suffix(width=4):
    return str(next_sequence()).zfill(width)


def unique_stamp_initials():
    """2 to 4 uppercase letters, distinct on every call (§3.2)."""
    index = next_sequence()
    letters = ""
    value = index
    for _ in range(3):
        letters = _LETTERS[value % 26] + letters
        value //= 26
    return letters


# --- §3.1 certificate and audits --------------------------------------------
def certificate_payload(
    cert_number=None,
    scope_codes=None,
    issued_on="2026-01-01",
    expires_on="2029-01-01",
    **overrides
):
    payload = {
        "cert_number": cert_number or "CA-U-{0}".format(unique_suffix()),
        "scope_codes": list(scope_codes) if scope_codes is not None else ["U"],
        "issued_on": issued_on,
        "expires_on": expires_on,
    }
    payload.update(overrides)
    return payload


def expired_certificate_payload(**overrides):
    """A certificate whose inclusive last valid day already lies in the past."""
    defaults = {"issued_on": "2024-01-01", "expires_on": "2025-06-30"}
    defaults.update(overrides)
    return certificate_payload(**defaults)


def audit_payload(certificate_id, audit_type=None, scheduled_date="2026-07-01", **overrides):
    payload = {
        "certificate_id": certificate_id,
        "audit_type": audit_type or AUDIT_TYPES[0],
        "scheduled_date": scheduled_date,
    }
    payload.update(overrides)
    return payload


def finding(severity, finding_code=None, clause_reference="QW-100"):
    return {
        "finding_code": finding_code or "F-{0}".format(unique_suffix()),
        "severity": severity,
        "clause_reference": clause_reference,
    }


def findings(major=0, minor=0, observation=0):
    """A findings array carrying exactly the requested severity mix."""
    built = []
    built.extend(finding(SEVERITY_MAJOR) for _ in range(major))
    built.extend(finding(SEVERITY_MINOR) for _ in range(minor))
    built.extend(finding(SEVERITY_OBSERVATION) for _ in range(observation))
    return built


def audit_close_payload(closed_on="2026-07-15", major=0, minor=0, observation=0, **overrides):
    payload = {
        "closed_on": closed_on,
        "findings": findings(major=major, minor=minor, observation=observation),
    }
    payload.update(overrides)
    return payload


def renewal_payload(expected_certificate_version, renewal_audit_id, new_expires_on="2030-01-01"):
    return {
        "expected_certificate_version": expected_certificate_version,
        "renewal_audit_id": renewal_audit_id,
        "new_expires_on": new_expires_on,
    }


# --- §3.2 personnel and jobs -------------------------------------------------
def personnel_payload(role_code, full_name=None, stamp_initials=None, **overrides):
    payload = {
        "full_name": full_name or "Person {0}".format(unique_suffix()),
        "role_code": role_code,
        "stamp_initials": stamp_initials or unique_stamp_initials(),
    }
    if role_code == "AUTHORIZED_INSPECTOR":
        payload["ai_agency"] = "Hartford Steam Boiler"
    payload.update(overrides)
    return payload


def vessel_job_payload(
    certificate_id,
    job_number=None,
    customer_name="Acme Refining Company",
    vessel_type=VESSEL_TYPE_PRESSURE_VESSEL,
    design_code=DESIGN_CODE_DIV1,
    mawp_psi=300,
    design_temp_f=650,
    mdmt_f=-20,
    inside_radius_in=30.0,
    **overrides
):
    payload = {
        "certificate_id": certificate_id,
        "job_number": job_number or "JOB-2026-{0}".format(unique_suffix()),
        "customer_name": customer_name,
        "vessel_type": vessel_type,
        "design_code": design_code,
        "mawp_psi": mawp_psi,
        "design_temp_f": design_temp_f,
        "mdmt_f": mdmt_f,
        "inside_radius_in": inside_radius_in,
    }
    payload.update(overrides)
    return payload


def cancel_payload(cancel_reason="Customer withdrew the purchase order"):
    return {"cancel_reason": cancel_reason}


# --- §3.3 design calculations ------------------------------------------------
def design_calculation_payload(
    expected_job_version,
    component=COMPONENT_SHELL,
    allowable_stress_psi=17500,
    corrosion_allowance_in=0.1250,
    thickness_nominal_in=1.0000,
    rt_extent_declared=RT_EXTENT_FULL,
    **overrides
):
    payload = {
        "expected_job_version": expected_job_version,
        "component": component,
        "allowable_stress_psi": allowable_stress_psi,
        "corrosion_allowance_in": corrosion_allowance_in,
        "thickness_nominal_in": thickness_nominal_in,
        "rt_extent_declared": rt_extent_declared,
    }
    payload.update(overrides)
    return payload


def reject_payload(reject_reason="Shell course thickness ignores the nozzle reinforcement"):
    return {"reject_reason": reject_reason}


def revise_payload(
    rt_extent_declared=RT_EXTENT_FULL,
    allowable_stress_psi=17500,
    corrosion_allowance_in=0.1250,
    thickness_nominal_in=1.2500,
    **overrides
):
    payload = {
        "rt_extent_declared": rt_extent_declared,
        "allowable_stress_psi": allowable_stress_psi,
        "corrosion_allowance_in": corrosion_allowance_in,
        "thickness_nominal_in": thickness_nominal_in,
    }
    payload.update(overrides)
    return payload


# --- §3.4 material heats and parts ------------------------------------------
def material_heat_payload(
    heat_number=None,
    spec=SPEC_SA_516_70,
    form=FORM_PLATE,
    mtr_received=True,
    quantity_received_lb=5000.00,
    yield_ksi=None,
    tensile_ksi=None,
    **overrides
):
    minimum_yield, minimum_tensile = MTR_MINIMA_BY_SPEC[spec]
    payload = {
        "heat_number": heat_number or "H{0}".format(unique_suffix(5)),
        "spec": spec,
        "form": form,
        "mtr_received": mtr_received,
        "mtr_certified_yield_ksi": minimum_yield + 5 if yield_ksi is None else yield_ksi,
        "mtr_certified_tensile_ksi": minimum_tensile + 5 if tensile_ksi is None else tensile_ksi,
        "quantity_received_lb": quantity_received_lb,
    }
    payload.update(overrides)
    return payload


def mtr_review_payload(decision="ACCEPT", reason=None):
    payload = {"decision": decision}
    if reason is not None:
        payload["reason"] = reason
    return payload


def part_payload(
    heat_id,
    part_mark=None,
    component_type=COMPONENT_TYPE_SHELL,
    issued_quantity_lb=1000.00,
    **overrides
):
    payload = {
        "heat_id": heat_id,
        "part_mark": part_mark or "PM-{0}".format(unique_suffix()),
        "component_type": component_type,
        "issued_quantity_lb": issued_quantity_lb,
    }
    payload.update(overrides)
    return payload


def scrap_payload(scrap_reason="Laminar tearing found during layout"):
    return {"scrap_reason": scrap_reason}


# --- §3.5 procedures, qualifications and weld map ---------------------------
def wps_payload(
    wps_number=None,
    process=PROCESS_SMAW,
    base_metal_p_number=1,
    filler_f_number=4,
    thickness_min_in=0.1875,
    thickness_max_in=3.0000,
    position=None,
    pwht_required=False,
    preheat_min_f=200,
    supporting_pqr_number=None,
    **overrides
):
    payload = {
        "wps_number": wps_number or "WPS-{0}".format(unique_suffix()),
        "process": process,
        "base_metal_p_number": base_metal_p_number,
        "filler_f_number": filler_f_number,
        "thickness_min_in": thickness_min_in,
        "thickness_max_in": thickness_max_in,
        "position": position or POSITIONS[0],
        "pwht_required": pwht_required,
        "preheat_min_f": preheat_min_f,
        "supporting_pqr_number": supporting_pqr_number or "PQR-{0}".format(unique_suffix()),
    }
    payload.update(overrides)
    return payload


def welder_qualification_payload(
    wps_id,
    welder_stamp=None,
    welder_name=None,
    position_qualified=None,
    thickness_range_max_in=3.0000,
    qualified_on="2026-06-01",
    **overrides
):
    payload = {
        "welder_stamp": welder_stamp or "W{0}".format(unique_suffix(3)),
        "welder_name": welder_name or "Welder {0}".format(unique_suffix()),
        "wps_id": wps_id,
        "position_qualified": position_qualified or POSITIONS[0],
        "thickness_range_max_in": thickness_range_max_in,
        "qualified_on": qualified_on,
    }
    payload.update(overrides)
    return payload


def continuity_log_payload(continuity_date, process=PROCESS_SMAW, **overrides):
    payload = {"continuity_date": continuity_date, "process": process}
    payload.update(overrides)
    return payload


def production_weld_payload(
    wps_id,
    part_a_id,
    weld_number=None,
    joint_category=JOINT_CATEGORY_A,
    joint_type=JOINT_TYPE_BUTT,
    thickness_in=1.0000,
    part_b_id=None,
    **overrides
):
    payload = {
        "weld_number": weld_number or "WLD-{0}".format(unique_suffix(3)),
        "joint_category": joint_category,
        "joint_type": joint_type,
        "thickness_in": thickness_in,
        "wps_id": wps_id,
        "part_a_id": part_a_id,
    }
    if part_b_id is not None:
        payload["part_b_id"] = part_b_id
    payload.update(overrides)
    return payload


def weld_complete_payload(welder_qualification_id, welded_at="2026-08-01T08:00:00.000Z", **overrides):
    payload = {"welder_qualification_id": welder_qualification_id, "welded_at": welded_at}
    payload.update(overrides)
    return payload


# --- §3.6 examinations -------------------------------------------------------
def exam_result_payload(
    result="ACCEPT",
    examined_coverage_pct=100.00,
    indications_count=0,
    exam_date="2026-08-02",
    **overrides
):
    payload = {
        "result": result,
        "examined_coverage_pct": examined_coverage_pct,
        "indications_count": indications_count,
        "exam_date": exam_date,
    }
    payload.update(overrides)
    return payload


def exam_reject_payload(indications_count=2, **overrides):
    return exam_result_payload(result="REJECT", indications_count=indications_count, **overrides)


# --- §3.7 nonconformances ----------------------------------------------------
def disposition_payload(disposition="REPAIR", disposition_notes="Grind out and reweld the joint"):
    return {"disposition": disposition, "disposition_notes": disposition_notes}


def repair_weld_payload(wps_id, weld_number=None, **overrides):
    payload = {
        "weld_number": weld_number or "RPR-{0}".format(unique_suffix(3)),
        "wps_id": wps_id,
    }
    payload.update(overrides)
    return payload


# --- §3.8 furnace charges and pressure tests --------------------------------
def pwht_batch_payload(
    job_id,
    weld_ids,
    furnace_code=FURNACE_A,
    scheduled_start="2026-08-05T06:00:00.000Z",
    scheduled_end="2026-08-05T14:00:00.000Z",
    soak_temp_f=1150,
    **overrides
):
    payload = {
        "job_id": job_id,
        "furnace_code": furnace_code,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "soak_temp_f": soak_temp_f,
        "weld_ids": list(weld_ids),
    }
    payload.update(overrides)
    return payload


def pwht_complete_payload(
    actual_soak_minutes=120, chart_record_number=None, chart_uploaded=True, **overrides
):
    payload = {
        "actual_soak_minutes": actual_soak_minutes,
        "chart_record_number": chart_record_number or "CHART-{0}".format(unique_suffix()),
        "chart_uploaded": chart_uploaded,
    }
    payload.update(overrides)
    return payload


def pressure_test_payload(
    job_id,
    test_side=TEST_SIDE_SHELL,
    test_type=TEST_TYPE_HYDROSTATIC,
    test_bay_code=BAY_1,
    scheduled_start="2026-08-10T08:00:00.000Z",
    scheduled_end="2026-08-10T12:00:00.000Z",
    **overrides
):
    payload = {
        "job_id": job_id,
        "test_side": test_side,
        "test_type": test_type,
        "test_bay_code": test_bay_code,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
    }
    payload.update(overrides)
    return payload


def pressure_test_result_payload(
    result="PASS",
    observed_pressure_psi=500.0,
    observed_hold_minutes=45,
    test_medium_temp_f=70,
    **overrides
):
    payload = {
        "result": result,
        "observed_pressure_psi": observed_pressure_psi,
        "observed_hold_minutes": observed_hold_minutes,
        "test_medium_temp_f": test_medium_temp_f,
    }
    payload.update(overrides)
    return payload


# --- §3.9 data package ------------------------------------------------------
def data_report_payload(expected_job_version, form_type=FORM_TYPE_U1A, **overrides):
    payload = {"expected_job_version": expected_job_version, "form_type": form_type}
    payload.update(overrides)
    return payload


def stamp_payload(nameplate_serial=None):
    return {"nameplate_serial": nameplate_serial or "NP-{0}".format(unique_suffix(5))}


# --- §2.5 clock -------------------------------------------------------------
def clock_payload(current_utc=DEFAULT_CLOCK_UTC):
    return {"current_utc": current_utc}
