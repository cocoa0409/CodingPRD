"""Payload factories — one per entity, input fields only.

Field names and required/optional splits follow the PRD endpoint contracts
exactly. Optional fields are omitted unless supplied (never sent as null),
so the server-side defaults the PRD declares are what tests observe.
"""
import itertools

from .constants import (
    PPM_BASELINE,
    SEASONAL_FACTOR_COUNT,
)

_ein_counter = itertools.count(1)
_outlet_code_counter = itertools.count(1)


def next_ein() -> str:
    """Unique employer identification number per call."""
    return f"11-{next(_ein_counter):07d}"


def next_outlet_code() -> str:
    """Unique media outlet code per call."""
    return f"OUTLET-{next(_outlet_code_counter):04d}"


# ---------------------------------------------------------------------------
# Create payloads (source: input fields only)
# ---------------------------------------------------------------------------
def create_program_payload(code="CES", name="Current Employment Statistics",
                           sample_budget=3, **overrides):
    """POST /survey/programs. embargo_window_minutes and
    annual_burden_budget_minutes are optional (defaults 30 / 120); pass them
    via overrides only when a test needs a non-default value."""
    payload = {"code": code, "name": name, "sample_budget": sample_budget}
    payload.update(overrides)
    return payload


def create_stratum(industry_code, size_class, frame_unit_count):
    """One strata entry. allocated_sample_size is never supplied on input."""
    return {
        "industry_code": industry_code,
        "size_class": size_class,
        "frame_unit_count": frame_unit_count,
    }


def create_sample_frame_payload(program_code, reference_quarter, strata,
                                expected_program_version, **overrides):
    """POST /survey/sample-frames. OCC field expected_program_version is
    required by the concurrency rule; replaces_frame_id is optional."""
    payload = {
        "program_code": program_code,
        "reference_quarter": reference_quarter,
        "strata": strata,
        "expected_program_version": expected_program_version,
    }
    payload.update(overrides)
    return payload


def create_establishment_payload(ein=None, name="Test Establishment",
                                 industry_code="MANUFACTURING",
                                 size_class="SMALL", **overrides):
    """POST /survey/establishments."""
    payload = {
        "ein": ein if ein is not None else next_ein(),
        "name": name,
        "industry_code": industry_code,
        "size_class": size_class,
    }
    payload.update(overrides)
    return payload


def create_enrollment_payload(establishment_id, program_code, **overrides):
    """POST /survey/panel-enrollments."""
    payload = {"establishment_id": establishment_id, "program_code": program_code}
    payload.update(overrides)
    return payload


def create_cycle_payload(program_code, reference_month, **overrides):
    """POST /survey/survey-cycles. The collection window is derived."""
    payload = {"program_code": program_code, "reference_month": reference_month}
    payload.update(overrides)
    return payload


def create_report_payload(enrollment_id, cycle_id, employment, **overrides):
    """POST /survey/response-reports. employment must be >= 0."""
    payload = {
        "enrollment_id": enrollment_id,
        "cycle_id": cycle_id,
        "employment": employment,
    }
    payload.update(overrides)
    return payload


def make_factor_list(month_overrides=None):
    """Exactly 12 factors, Jan..Dec, all 1.0 except the 1-indexed month
    overrides (e.g., {9: 1.05} sets September). The all-1.0 baseline has
    mean exactly 1.0, inside the declared tolerance."""
    factors = [1.0] * SEASONAL_FACTOR_COUNT
    for month_index, value in (month_overrides or {}).items():
        factors[month_index - 1] = value
    return factors


def create_factor_set_payload(program_code, industry_code, size_class, year,
                              factors=None, **overrides):
    """POST /survey/seasonal-factor-sets."""
    payload = {
        "program_code": program_code,
        "industry_code": industry_code,
        "size_class": size_class,
        "year": year,
        "factors": factors if factors is not None else make_factor_list(),
    }
    payload.update(overrides)
    return payload


def create_admin_cell_count(industry_code, size_class, admin_employment):
    """One admin_cell_counts entry. admin_employment must be >= 0."""
    return {
        "industry_code": industry_code,
        "size_class": size_class,
        "admin_employment": admin_employment,
    }


def create_benchmark_run_payload(program_code, benchmark_month,
                                 admin_cell_counts, **overrides):
    """POST /survey/benchmark-runs."""
    payload = {
        "program_code": program_code,
        "benchmark_month": benchmark_month,
        "admin_cell_counts": admin_cell_counts,
    }
    payload.update(overrides)
    return payload


def create_series_ref(industry_code, size_class):
    """One methodology-notice series entry."""
    return {"industry_code": industry_code, "size_class": size_class}


def create_notice_payload(program_code, title, effective_from,
                          scope="ALL_SERIES",
                          reconstruction_factor_ppm=PPM_BASELINE,
                          series=None, **overrides):
    """POST /survey/methodology-notices. series is required and non-empty
    when scope is LISTED_SERIES and ignored otherwise."""
    payload = {
        "program_code": program_code,
        "title": title,
        "effective_from": effective_from,
        "scope": scope,
        "reconstruction_factor_ppm": reconstruction_factor_ppm,
    }
    if series is not None:
        payload["series"] = series
    payload.update(overrides)
    return payload


def create_release_payload(cycle_id, release_at, **overrides):
    """POST /survey/release-events."""
    payload = {"cycle_id": cycle_id, "release_at": release_at}
    payload.update(overrides)
    return payload


def create_outlet_payload(name="Wire Service", outlet_code=None, **overrides):
    """POST /survey/media-outlets."""
    payload = {
        "name": name,
        "outlet_code": outlet_code if outlet_code is not None else next_outlet_code(),
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Action payloads (action-style endpoints)
# ---------------------------------------------------------------------------
def cycle_advance_payload(action, **overrides):
    """POST /survey/survey-cycles/{id}/advance."""
    payload = {"action": action}
    payload.update(overrides)
    return payload


def report_advance_payload(action, return_reason=None, **overrides):
    """POST /survey/response-reports/{id}/advance. return_reason is required
    on RETURN and null otherwise — pass it only for RETURN."""
    payload = {"action": action}
    if return_reason is not None:
        payload["return_reason"] = return_reason
    payload.update(overrides)
    return payload


def lifecycle_payload(action, **overrides):
    """POST /survey/panel-enrollments/{id}/lifecycle."""
    payload = {"action": action}
    payload.update(overrides)
    return payload


def case_advance_payload(action, contact_minutes=None, channel=None,
                         contact_seq=None, outcome=None, **overrides):
    """POST /survey/follow-up-cases/{id}/advance. Fields apply per action:
    RECORD_CONTACT takes contact_minutes+channel; VOID_CONTACT takes
    contact_seq; CLOSE takes outcome; ESCALATE takes none."""
    payload = {"action": action}
    if contact_minutes is not None:
        payload["contact_minutes"] = contact_minutes
    if channel is not None:
        payload["channel"] = channel
    if contact_seq is not None:
        payload["contact_seq"] = contact_seq
    if outcome is not None:
        payload["outcome"] = outcome
    payload.update(overrides)
    return payload


def release_advance_payload(action, expected_release_version,
                            new_release_at=None, **overrides):
    """POST /survey/release-events/{id}/advance. Every release advance is
    OCC-guarded by expected_release_version; RESCHEDULE also takes
    new_release_at."""
    payload = {
        "action": action,
        "expected_release_version": expected_release_version,
    }
    if new_release_at is not None:
        payload["new_release_at"] = new_release_at
    payload.update(overrides)
    return payload


def accreditation_payload(action, **overrides):
    """POST /survey/media-outlets/{id}/accreditation."""
    payload = {"action": action}
    payload.update(overrides)
    return payload


def notice_advance_payload(action, **overrides):
    """POST /survey/methodology-notices/{id}/advance."""
    payload = {"action": action}
    payload.update(overrides)
    return payload


def clock_payload(to_iso8601):
    """POST /_clock/set_current_utc (unprefixed endpoint)."""
    return {"to_iso8601": to_iso8601}
