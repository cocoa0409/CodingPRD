"""Entity assertions and domain invariant checkers.

Each assert_<entity>() validates the PRD-declared field surface: common
fields (id, created_at, updated_at, version), declared field presence, enum
membership, and nullability. Domain invariant checkers encode cross-field
rules the PRD states (budget/allocation bounds, roster decline conservation,
deal share conservation).
"""
from prd_bench_local_runner.testing import (
    assert_cost_precision,
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .types import (
    AbuseReportStatus,
    AgreementStatus,
    AppealGrounds,
    AppealStatus,
    ComplaintCategory,
    ComplaintPosture,
    ComplaintSeverity,
    ComplaintStatus,
    DealBasis,
    DealStatus,
    EligibilityStatus,
    EntryStatus,
    EventGrade,
    FundingTier,
    GoverningBodyStatus,
    InsuranceStatus,
    PointsMethod,
    ProcStatus,
    ReporterRole,
    ResultStatus,
    RosterStatus,
    ScreeningStatus,
    SlotStatus,
    SlotType,
    TrialsStatus,
)


def _enum_values(enum_cls):
    return [m.value for m in enum_cls]


def assert_common_fields(data: dict):
    """PRD common resource properties: server-minted UUID id, ISO 8601
    created_at/updated_at, integer version starting at 1."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer >= 1, got {data.get('version')!r}"
    )


def _assert_nullable_timestamp(data: dict, field: str):
    assert field in data, f"missing field {field}"
    if data[field] is not None:
        assert is_iso8601_timestamp(data[field]), (
            f"{field} must be ISO 8601 when set, got {data[field]!r}"
        )


def _assert_points_2dp(value, field):
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{field} must be numeric, got {value!r}"
    )
    assert_cost_precision(float(value), 2)


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------

def assert_governing_body(data: dict):
    assert_common_fields(data)
    assert isinstance(data.get("name"), str) and data["name"].strip()
    assert isinstance(data.get("sport_code"), str) and data["sport_code"].strip()
    assert data.get("status") in _enum_values(GoverningBodyStatus)
    assert data.get("complaint_posture") in _enum_values(ComplaintPosture)
    for f in ("funding_budget_cents", "sport_science_pool_hours",
              "committed_monthly_stipend_cents", "allocated_science_hours",
              "substantiated_complaint_count"):
        assert isinstance(data.get(f), int) and not isinstance(data.get(f), bool), (
            f"{f} must be an integer, got {data.get(f)!r}"
        )
    _assert_nullable_timestamp(data, "certified_at")
    assert "interim_manager_id" in data, "missing interim_manager_id"
    if data["interim_manager_id"] is not None:
        assert isinstance(data["interim_manager_id"], str)


def assert_certification_cycle(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("governing_body_id", ""))
    assert is_iso8601_timestamp(data.get("window_start", ""))
    assert is_iso8601_timestamp(data.get("window_end", ""))
    assert data.get("status") in _enum_values(CertificationCycleStatus)
    for f in ("governance_score", "athlete_rep_score", "financial_score",
              "provisional_score", "final_score"):
        assert f in data, f"missing field {f}"
        if data[f] is not None:
            _assert_points_2dp(data[f], f)
    assert isinstance(data.get("remediation_applied"), bool)
    _assert_nullable_timestamp(data, "opened_at")
    _assert_nullable_timestamp(data, "closed_at")
    for f in ("issued_by_user_id", "closed_by_user_id"):
        assert f in data, f"missing field {f}"
        if data[f] is not None:
            assert isinstance(data[f], str)


def assert_complaint(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("governing_body_id", ""))
    assert data.get("category") in _enum_values(ComplaintCategory)
    assert data.get("severity") in _enum_values(ComplaintSeverity)
    assert isinstance(data.get("description"), str)
    assert data.get("status") in _enum_values(ComplaintStatus)
    _assert_nullable_timestamp(data, "resolved_at")
    for f in ("triaged_by_user_id", "resolved_by_user_id"):
        assert f in data, f"missing field {f}"
        if data[f] is not None:
            assert isinstance(data[f], str)


def assert_athlete(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("governing_body_id", ""))
    assert isinstance(data.get("full_name"), str) and data["full_name"].strip()
    dob = data.get("date_of_birth", "")
    assert isinstance(dob, str) and len(dob) == 10 and dob[4] == "-" and dob[7] == "-", (
        f"date_of_birth must be YYYY-MM-DD, got {dob!r}"
    )
    assert isinstance(data.get("team_sport"), bool)
    assert data.get("eligibility_status") in _enum_values(EligibilityStatus)
    assert data.get("screening_status") in _enum_values(ScreeningStatus)
    _assert_nullable_timestamp(data, "screening_expires_at")
    _assert_nullable_timestamp(data, "training_completed_at")


def assert_performance_result(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("athlete_id", ""))
    assert isinstance(data.get("event_name"), str) and data["event_name"].strip()
    assert data.get("event_grade") in _enum_values(EventGrade)
    placing = data.get("placing")
    assert isinstance(placing, int) and not isinstance(placing, bool) and 1 <= placing <= 8, (
        f"placing must be an integer in 1..8, got {placing!r}"
    )
    assert is_iso8601_timestamp(data.get("event_date", ""))
    assert data.get("status") in _enum_values(ResultStatus)
    assert "base_points" in data, "missing base_points"
    if data["base_points"] is not None:
        _assert_points_2dp(data["base_points"], "base_points")
    assert "verified_by_user_id" in data, "missing verified_by_user_id"
    if data["verified_by_user_id"] is not None:
        assert isinstance(data["verified_by_user_id"], str)


def assert_funding_agreement(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("athlete_id", ""))
    assert is_iso8601_timestamp(data.get("coverage_start", ""))
    assert is_iso8601_timestamp(data.get("coverage_end", ""))
    assert data.get("points_method") in _enum_values(PointsMethod)
    _assert_points_2dp(data.get("trailing_points"), "trailing_points")
    _assert_points_2dp(data.get("season_points"), "season_points")
    assert data.get("tier") in _enum_values(FundingTier)
    stipend = data.get("monthly_stipend_cents")
    assert isinstance(stipend, int) and not isinstance(stipend, bool) and stipend >= 0
    assert data.get("status") in _enum_values(AgreementStatus)
    assert data.get("insurance_status") in _enum_values(InsuranceStatus)
    hours = data.get("science_hours_allocated")
    assert isinstance(hours, int) and not isinstance(hours, bool) and hours >= 0
    _assert_nullable_timestamp(data, "insurance_enrolled_at")
    _assert_nullable_timestamp(data, "activated_at")


def assert_abuse_report(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("athlete_id", ""))
    assert data.get("reporter_role") in _enum_values(ReporterRole)
    assert isinstance(data.get("allegation"), str)
    assert data.get("status") in _enum_values(AbuseReportStatus)
    _assert_nullable_timestamp(data, "forwarded_at")
    _assert_nullable_timestamp(data, "adjudicated_at")


def assert_trials_entry(entry: dict):
    assert is_valid_uuid(entry.get("athlete_id", "")), (
        f"entry athlete_id must be a UUID, got {entry.get('athlete_id')!r}"
    )
    assert entry.get("entry_status") in _enum_values(EntryStatus)
    assert "score" in entry, "entry missing score"
    if entry["score"] is not None:
        assert isinstance(entry["score"], (int, float)) and not isinstance(entry["score"], bool)
    assert "result_recorded_at" in entry, "entry missing result_recorded_at"
    if entry["result_recorded_at"] is not None:
        assert is_iso8601_timestamp(entry["result_recorded_at"])


def assert_selection_procedure(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("governing_body_id", ""))
    assert isinstance(data.get("games_name"), str) and data["games_name"].strip()
    assert is_iso8601_timestamp(data.get("trials_start", ""))
    assert is_iso8601_timestamp(data.get("trials_end", ""))
    assert is_iso8601_timestamp(data.get("registration_deadline", ""))
    assert isinstance(data.get("qualifying_score"), (int, float))
    quota = data.get("quota_slots")
    assert isinstance(quota, int) and not isinstance(quota, bool) and quota >= 1, (
        f"quota_slots must be an integer >= 1, got {quota!r}"
    )
    assert data.get("proc_status") in _enum_values(ProcStatus)
    assert data.get("trials_status") in _enum_values(TrialsStatus)
    _assert_nullable_timestamp(data, "published_at")
    _assert_nullable_timestamp(data, "locked_at")
    entries = data.get("entries")
    assert isinstance(entries, list), "entries must be a list"
    for entry in entries:
        assert_trials_entry(entry)


def assert_roster_slot(slot: dict):
    assert is_valid_uuid(slot.get("athlete_id", "")), (
        f"slot athlete_id must be a UUID, got {slot.get('athlete_id')!r}"
    )
    assert slot.get("slot_type") in _enum_values(SlotType)
    assert slot.get("slot_status") in _enum_values(SlotStatus)
    rank = slot.get("rank")
    assert isinstance(rank, int) and not isinstance(rank, bool) and rank >= 1
    _assert_points_2dp(slot.get("composite_score"), "composite_score")
    assert isinstance(slot.get("trials_score"), (int, float))
    _assert_points_2dp(slot.get("season_points"), "season_points")


def assert_roster(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("selection_procedure_id", ""))
    assert data.get("status") in _enum_values(RosterStatus)
    assert "quota_effective" in data, "missing quota_effective"
    if data["quota_effective"] is not None:
        assert isinstance(data["quota_effective"], int) and data["quota_effective"] >= 1
    assert isinstance(data.get("bonus_slot_applied"), bool)
    assert isinstance(data.get("slots"), list), "slots must be a list"
    for slot in data["slots"]:
        assert_roster_slot(slot)
    declined = data.get("declined_athlete_ids")
    assert isinstance(declined, list), "declined_athlete_ids must be a list"
    for aid in declined:
        assert is_valid_uuid(aid), f"declined id must be a UUID, got {aid!r}"
    _assert_nullable_timestamp(data, "nominated_at")
    assert "submitted_by_user_id" in data, "missing submitted_by_user_id"
    if data["submitted_by_user_id"] is not None:
        assert isinstance(data["submitted_by_user_id"], str)


def assert_appeal(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("roster_id", ""))
    assert is_valid_uuid(data.get("filed_by_athlete_id", ""))
    assert data.get("grounds") in _enum_values(AppealGrounds)
    assert data.get("status") in _enum_values(AppealStatus)
    assert is_iso8601_timestamp(data.get("filed_at", ""))
    assert "decision_rationale" in data, "missing decision_rationale"
    if data["decision_rationale"] is not None:
        assert isinstance(data["decision_rationale"], str)


def assert_commercial_deal(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("athlete_id", ""))
    assert isinstance(data.get("sponsor_name"), str) and data["sponsor_name"].strip()
    gross = data.get("gross_value_cents")
    assert isinstance(gross, int) and not isinstance(gross, bool) and gross >= 0
    assert data.get("basis") in _enum_values(DealBasis)
    assert is_iso8601_timestamp(data.get("exclusivity_start", ""))
    assert is_iso8601_timestamp(data.get("exclusivity_end", ""))
    assert data.get("status") in _enum_values(DealStatus)
    for f in ("committee_share_cents", "ngb_share_cents", "athlete_share_cents"):
        assert f in data, f"missing field {f}"
        if data[f] is not None:
            assert isinstance(data[f], int) and not isinstance(data[f], bool) and data[f] >= 0
    _assert_nullable_timestamp(data, "consented_at")
    _assert_nullable_timestamp(data, "activated_at")


# ---------------------------------------------------------------------------
# Domain invariant checkers
# ---------------------------------------------------------------------------

def assert_body_allocation_invariants(body: dict):
    """The body's committed stipends and allocated science hours never go
    negative, and allocated hours never exceed the pool."""
    assert body["committed_monthly_stipend_cents"] >= 0, (
        "committed_monthly_stipend_cents must never be negative"
    )
    assert 0 <= body["allocated_science_hours"] <= body["sport_science_pool_hours"], (
        "allocated_science_hours must stay within [0, sport_science_pool_hours]"
    )


def primary_slot_count(slots: list) -> int:
    """Count of PRIMARY slots awaiting or holding an athlete commitment
    (NOMINATED, PROMOTED, or ACCEPTED) — the conserved quantity across a
    decline-with-promotion."""
    return sum(
        1
        for s in slots
        if s.get("slot_type") == "PRIMARY"
        and s.get("slot_status") in ("NOMINATED", "PROMOTED", "ACCEPTED")
    )


def assert_decline_conservation(before_slots: list, after_slots: list):
    """PRD roster invariant: a DECLINE with an available alternate leaves the
    count of committed PRIMARY slots unchanged."""
    assert primary_slot_count(before_slots) == primary_slot_count(after_slots), (
        f"primary slot count changed: {primary_slot_count(before_slots)} -> "
        f"{primary_slot_count(after_slots)}"
    )


def assert_deal_shares_conserve(deal: dict):
    """PRD revenue split: the three shares are non-negative integers and the
    athlete absorbs the rounding remainder, so the shares never exceed the
    split base (gross, or gross minus the agency fee)."""
    committee = deal["committee_share_cents"]
    ngb = deal["ngb_share_cents"]
    athlete = deal["athlete_share_cents"]
    assert all(isinstance(v, int) and v >= 0 for v in (committee, ngb, athlete))
    total = committee + ngb + athlete
    assert total <= deal["gross_value_cents"], (
        f"shares {total} exceed gross {deal['gross_value_cents']}"
    )


def assert_pagination_meta(meta: dict, limit: int, offset: int,
                           total_count: int, returned_count: int):
    """PRD pagination fields: limit/offset/total_count/has_more present and
    consistent with the page actually returned."""
    assert meta["limit"] == limit, f"meta.limit {meta['limit']} != requested {limit}"
    assert meta["offset"] == offset, f"meta.offset {meta['offset']} != requested {offset}"
    assert meta["total_count"] == total_count, (
        f"meta.total_count {meta['total_count']} != expected {total_count}"
    )
    assert isinstance(meta["has_more"], bool)
    assert meta["has_more"] == (offset + returned_count < total_count), (
        f"has_more {meta['has_more']} inconsistent with offset {offset} + "
        f"returned {returned_count} of {total_count}"
    )
