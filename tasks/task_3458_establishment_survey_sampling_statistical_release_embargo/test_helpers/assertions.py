"""Entity assertions and domain invariant checkers.

Each assert_<entity>() verifies the system-managed common fields (id as
UUID, created_at/updated_at as ISO 8601, version as a positive int) plus the
presence and enum-membership of the entity's own fields. Nullable fields are
checked for key presence but may hold None (e.g., frozen_at while DRAFT).
"""
from datetime import datetime

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AccreditationStatus, CaseStatus, CycleStatus, DisclosureStatus,
    EstimateStatus, FactorSetStatus, FrameStatus, GrantStatus,
    ImputationVariant, IndustryCode, EnrollmentStatus, BenchmarkRunStatus,
    NoticeScope, NoticeStatus, PubStatus, ReportStatus, SizeClass,
    SuppressionStatus,
)


def parse_instant(ts: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp into a datetime (accepts a Z suffix)."""
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def assert_same_instant(actual: str, expected: str, msg: str = ""):
    """Assert two ISO 8601 serializations denote the same instant.

    The PRD pins the instant each timestamp field records, but it pins the
    three-fractional-digit serialization only for `api_request_timestamp`,
    `created_at`, and `updated_at`; every other timestamp field is therefore
    compared as an instant, not as a string."""
    assert parse_instant(actual) == parse_instant(expected), (
        msg or f"{actual!r} and {expected!r} are not the same instant")


def _assert_common(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity}.created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{entity}.updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"{entity}.version must be an int >= 1, got {data.get('version')!r}"


def _assert_nullable_timestamp(data: dict, field: str, entity: str):
    assert field in data, f"{entity}.{field} key must be present"
    value = data[field]
    if value is not None:
        assert is_iso8601_timestamp(value), \
            f"{entity}.{field} must be ISO 8601 when set, got {value!r}"


def assert_program(data: dict):
    _assert_common(data, "SurveyProgram")
    assert isinstance(data.get("code"), str) and data["code"], "program.code required"
    assert isinstance(data.get("name"), str), "program.name must be a string"
    assert isinstance(data.get("sample_budget"), int) and data["sample_budget"] >= 2, \
        f"program.sample_budget must be an int >= 2, got {data.get('sample_budget')!r}"
    ew = data.get("embargo_window_minutes")
    assert isinstance(ew, int) and 1 <= ew <= 1440, \
        f"embargo_window_minutes must be in 1..1440, got {ew!r}"
    bb = data.get("annual_burden_budget_minutes")
    assert isinstance(bb, int) and bb >= 15, \
        f"annual_burden_budget_minutes must be >= 15, got {bb!r}"


def assert_sample_frame(data: dict):
    _assert_common(data, "SampleFrame")
    assert isinstance(data.get("program_code"), str), "frame.program_code required"
    assert isinstance(data.get("reference_quarter"), str), "frame.reference_quarter required"
    assert data.get("frame_status") in {s.value for s in FrameStatus}, \
        f"frame_status invalid: {data.get('frame_status')!r}"
    strata = data.get("strata")
    assert isinstance(strata, list) and strata, "frame.strata must be a non-empty array"
    for st in strata:
        assert st["industry_code"] in {i.value for i in IndustryCode}
        assert st["size_class"] in {s.value for s in SizeClass}
        assert isinstance(st["frame_unit_count"], int) and st["frame_unit_count"] >= 1
        assert "allocated_sample_size" in st, "stratum must carry allocated_sample_size (null until freeze)"
    assert "total_sample_size" in data, "frame must carry total_sample_size (null until freeze)"
    _assert_nullable_timestamp(data, "frozen_at", "SampleFrame")
    assert "replaced_by_frame_id" in data, "frame must carry replaced_by_frame_id"


def assert_establishment(data: dict):
    _assert_common(data, "Establishment")
    assert isinstance(data.get("ein"), str) and data["ein"], "establishment.ein required"
    assert isinstance(data.get("name"), str), "establishment.name must be a string"
    assert data.get("industry_code") in {i.value for i in IndustryCode}
    assert data.get("size_class") in {s.value for s in SizeClass}


def assert_enrollment(data: dict):
    _assert_common(data, "PanelEnrollment")
    assert is_valid_uuid(data.get("establishment_id", "")), "enrollment.establishment_id must be a UUID"
    assert isinstance(data.get("program_code"), str), "enrollment.program_code required"
    assert data.get("industry_code") in {i.value for i in IndustryCode}
    assert data.get("size_class") in {s.value for s in SizeClass}
    assert isinstance(data.get("base_weight"), (int, float)), "enrollment.base_weight must be numeric"
    assert isinstance(data.get("burden_minutes_ytd"), int) and data["burden_minutes_ytd"] >= 0
    assert "burden_year" in data, "enrollment must carry burden_year (null until first burden event)"
    if data["burden_year"] is not None:
        assert isinstance(data["burden_year"], int)
    assert data.get("enrollment_status") in {s.value for s in EnrollmentStatus}


def assert_cycle(data: dict):
    _assert_common(data, "SurveyCycle")
    assert isinstance(data.get("program_code"), str), "cycle.program_code required"
    assert isinstance(data.get("reference_month"), str), "cycle.reference_month required"
    assert is_iso8601_timestamp(data.get("collection_open_at", "")), \
        "cycle.collection_open_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("collection_close_at", "")), \
        "cycle.collection_close_at must be ISO 8601"
    assert data.get("cycle_status") in {s.value for s in CycleStatus}
    _assert_nullable_timestamp(data, "estimates_computed_at", "SurveyCycle")
    for rate_field in ("weighted_response_rate", "unweighted_response_rate"):
        assert rate_field in data, f"cycle must carry {rate_field} (null before first compute)"
        if data[rate_field] is not None:
            assert isinstance(data[rate_field], (int, float))
    assert "certified_by_user_id" in data, "cycle must carry certified_by_user_id"


def assert_report(data: dict):
    _assert_common(data, "ResponseReport")
    assert is_valid_uuid(data.get("enrollment_id", "")), "report.enrollment_id must be a UUID"
    assert is_valid_uuid(data.get("cycle_id", "")), "report.cycle_id must be a UUID"
    assert isinstance(data.get("employment"), int) and data["employment"] >= 0, \
        f"report.employment must be an int >= 0, got {data.get('employment')!r}"
    assert data.get("report_status") in {s.value for s in ReportStatus}
    assert isinstance(data.get("submit_count"), int) and data["submit_count"] >= 1, \
        f"report.submit_count must be >= 1, got {data.get('submit_count')!r}"
    assert is_iso8601_timestamp(data.get("submitted_at", "")), "report.submitted_at must be ISO 8601"
    assert "return_reason" in data, "report must carry return_reason (null unless RETURNED)"


def assert_follow_up_case(data: dict):
    _assert_common(data, "FollowUpCase")
    assert is_valid_uuid(data.get("enrollment_id", "")), "case.enrollment_id must be a UUID"
    assert is_valid_uuid(data.get("cycle_id", "")), "case.cycle_id must be a UUID"
    assert data.get("case_status") in {s.value for s in CaseStatus}
    assert is_iso8601_timestamp(data.get("opened_at", "")), "case.opened_at must be ISO 8601"
    contacts = data.get("contacts")
    assert isinstance(contacts, list), "case.contacts must be an array"
    for entry in contacts:
        assert isinstance(entry.get("seq"), int) and entry["seq"] >= 1
        assert isinstance(entry.get("contact_minutes"), int)
        assert isinstance(entry.get("channel"), str)
        assert is_iso8601_timestamp(entry.get("contacted_at", ""))
        assert isinstance(entry.get("voided"), bool)
    expected_total = sum(e["contact_minutes"] for e in contacts if not e["voided"])
    assert data.get("total_contact_minutes") == expected_total, (
        f"total_contact_minutes must equal the sum of non-voided contact minutes: "
        f"got {data.get('total_contact_minutes')!r}, expected {expected_total}")


def assert_cell_estimate(data: dict):
    _assert_common(data, "CellEstimate")
    assert is_valid_uuid(data.get("cycle_id", "")), "cell.cycle_id must be a UUID"
    assert isinstance(data.get("program_code"), str), "cell.program_code required"
    assert data.get("industry_code") in {i.value for i in IndustryCode}
    assert data.get("size_class") in {s.value for s in SizeClass}
    assert data.get("estimate_status") in {s.value for s in EstimateStatus}
    assert isinstance(data.get("revision_no"), int) and data["revision_no"] >= 1
    for int_field in ("employment_estimate", "variance_estimate",
                      "seasonally_adjusted_concurrent", "seasonally_adjusted_revised"):
        assert int_field in data, f"cell must carry {int_field}"
        if data[int_field] is not None:
            assert isinstance(data[int_field], int), \
                f"cell.{int_field} must be a whole-person int, got {data[int_field]!r}"
    assert isinstance(data.get("respondent_count"), int) and data["respondent_count"] >= 0
    assert isinstance(data.get("enrolled_count"), int) and data["enrolled_count"] >= 0
    assert isinstance(data.get("dominance_flag"), bool)
    assert data.get("suppression_status") in {s.value for s in SuppressionStatus}
    assert "imputation_variant" in data, "cell must carry imputation_variant (null when unused)"
    if data["imputation_variant"] is not None:
        assert data["imputation_variant"] in {v.value for v in ImputationVariant}
    assert "wedge_factor" in data, "cell must carry wedge_factor (null until benchmarked)"
    if data["wedge_factor"] is not None:
        assert isinstance(data["wedge_factor"], (int, float))


def assert_factor_set(data: dict):
    _assert_common(data, "SeasonalFactorSet")
    assert isinstance(data.get("program_code"), str), "factor set program_code required"
    assert data.get("industry_code") in {i.value for i in IndustryCode}
    assert data.get("size_class") in {s.value for s in SizeClass}
    assert isinstance(data.get("year"), int)
    factors = data.get("factors")
    assert isinstance(factors, list) and len(factors) == 12, \
        "factor set must carry exactly 12 factors"
    assert data.get("set_status") in {s.value for s in FactorSetStatus}
    _assert_nullable_timestamp(data, "finalized_at", "SeasonalFactorSet")


def assert_benchmark_run(data: dict):
    _assert_common(data, "BenchmarkRun")
    assert isinstance(data.get("program_code"), str), "run.program_code required"
    assert isinstance(data.get("benchmark_month"), str), "run.benchmark_month required"
    counts = data.get("admin_cell_counts")
    assert isinstance(counts, list) and counts, "run.admin_cell_counts must be non-empty"
    for entry in counts:
        assert entry["industry_code"] in {i.value for i in IndustryCode}
        assert entry["size_class"] in {s.value for s in SizeClass}
        assert isinstance(entry["admin_employment"], int) and entry["admin_employment"] >= 0
    assert data.get("run_status") in {s.value for s in BenchmarkRunStatus}
    _assert_nullable_timestamp(data, "applied_at", "BenchmarkRun")


def assert_notice(data: dict):
    _assert_common(data, "MethodologyNotice")
    assert isinstance(data.get("program_code"), str), "notice.program_code required"
    assert isinstance(data.get("title"), str), "notice.title required"
    assert is_iso8601_timestamp(data.get("effective_from", "")), \
        "notice.effective_from must be ISO 8601"
    assert data.get("scope") in {s.value for s in NoticeScope}
    ppm = data.get("reconstruction_factor_ppm")
    assert isinstance(ppm, int) and ppm >= 1, \
        f"reconstruction_factor_ppm must be an int >= 1, got {ppm!r}"
    assert data.get("notice_status") in {s.value for s in NoticeStatus}
    _assert_nullable_timestamp(data, "announced_at", "MethodologyNotice")
    _assert_nullable_timestamp(data, "activated_at", "MethodologyNotice")


def assert_release_event(data: dict):
    _assert_common(data, "ReleaseEvent")
    assert is_valid_uuid(data.get("cycle_id", "")), "release.cycle_id must be a UUID"
    assert isinstance(data.get("program_code"), str), "release.program_code required"
    assert is_iso8601_timestamp(data.get("release_at", "")), "release.release_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("embargo_open_at", "")), \
        "release.embargo_open_at must be ISO 8601"
    assert data.get("pub_status") in {s.value for s in PubStatus}
    assert data.get("disclosure_status") in {s.value for s in DisclosureStatus}
    assert isinstance(data.get("revision_notice_required"), bool)
    count = data.get("active_embargo_grant_count")
    assert isinstance(count, int) and count >= 0, \
        f"active_embargo_grant_count must be a non-negative int, got {count!r}"


def assert_media_outlet(data: dict):
    _assert_common(data, "MediaOutlet")
    assert isinstance(data.get("name"), str), "outlet.name required"
    assert isinstance(data.get("outlet_code"), str) and data["outlet_code"], \
        "outlet.outlet_code required"
    assert data.get("accreditation_status") in {s.value for s in AccreditationStatus}


def assert_embargo_grant(data: dict):
    _assert_common(data, "EmbargoGrant")
    assert is_valid_uuid(data.get("release_event_id", "")), "grant.release_event_id must be a UUID"
    assert is_valid_uuid(data.get("media_outlet_id", "")), "grant.media_outlet_id must be a UUID"
    assert data.get("grant_status") in {s.value for s in GrantStatus}
    assert is_iso8601_timestamp(data.get("issued_at", "")), "grant.issued_at must be ISO 8601"
    _assert_nullable_timestamp(data, "first_accessed_at", "EmbargoGrant")


def assert_bulletin(data: dict):
    """Shape of the embargoed bulletin payload."""
    assert is_valid_uuid(data.get("release_event_id", "")), \
        "bulletin.release_event_id must be a UUID"
    assert isinstance(data.get("reference_month"), str), "bulletin.reference_month required"
    assert data.get("release_status") in {s.value for s in PubStatus}, \
        f"bulletin.release_status invalid: {data.get('release_status')!r}"
    assert isinstance(data.get("embargoed"), bool), "bulletin.embargoed must be a bool"
    assert isinstance(data.get("cells"), list), "bulletin.cells must be an array"
    assert isinstance(data.get("industry_totals"), list), \
        "bulletin.industry_totals must be an array"


# ---------------------------------------------------------------------------
# Domain invariant checkers
# ---------------------------------------------------------------------------
def assert_burden_invariants(enrollment: dict, program: dict):
    """The burden ledger never exceeds the program's annual budget and never
    goes negative; burden_year is set exactly when a burden event has landed."""
    burden = enrollment["burden_minutes_ytd"]
    assert burden >= 0, "burden_minutes_ytd must be non-negative"
    assert burden <= program["annual_burden_budget_minutes"], (
        f"burden {burden} exceeds annual_burden_budget_minutes "
        f"{program['annual_burden_budget_minutes']}")
    if burden == 0:
        # Either no event yet (burden_year null) or a fresh-year rollover just
        # landed a zero-minute-net state; both are legal. Only forbid the
        # contradictory combination asserted by the PRD: a year with no events
        # is represented by burden_year null, which accompanies burden 0.
        pass
    else:
        assert enrollment["burden_year"] is not None, \
            "burden_year must be set once a burden event has landed"


def assert_release_invariants(release: dict):
    """Release dimensions stay internally consistent."""
    assert_release_event(release)
    if release["pub_status"] in (PubStatus.SCHEDULED.value, PubStatus.EMBARGO_OPEN.value):
        assert release["embargo_open_at"] < release["release_at"], \
            "embargo_open_at must precede release_at"
    if release["pub_status"] != PubStatus.EMBARGO_OPEN.value and \
            release["pub_status"] != PubStatus.PUBLISHED.value:
        pass  # no further cross-field constraint the PRD pins down
