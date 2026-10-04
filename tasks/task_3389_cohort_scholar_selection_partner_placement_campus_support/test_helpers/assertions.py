"""Entity assertions and domain invariant checkers.

Each assert_* checks the fields PRD prose names for that resource: identity
and timestamp shape (PRD §2.5) plus the entity's own fields (PRD §3). The
Evaluation record is the stated exception to versioning (PRD §2.5), so its
asserter also pins the ABSENCE of updated_at and version.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be ISO 8601"
    )
    # PRD §2.5 pins version as an integer that increments on every mutation;
    # the initial value is not pinned, so only presence and type are checked.
    assert isinstance(data.get("version"), int), f"{entity}.version must be an integer"


def assert_city_program(data: dict):
    _assert_common(data, "CityProgram")
    for f in ("code", "name", "admissions_cycle"):
        assert isinstance(data.get(f), str) and data[f], f"CityProgram.{f} must be set"
    for f in ("nomination_window_opens_at", "nomination_window_closes_at"):
        assert is_iso8601_timestamp(data.get(f, "")), f"CityProgram.{f} must be ISO 8601"


def assert_nominating_partner(data: dict):
    _assert_common(data, "NominatingPartner")
    assert isinstance(data.get("city_program_id"), str)
    assert isinstance(data.get("name"), str) and data["name"]
    assert data.get("kind") in ("HIGH_SCHOOL", "COMMUNITY_ORG")
    assert isinstance(data.get("nomination_quota"), int)
    assert 1 <= data["nomination_quota"] <= 20, "quota must satisfy 1 <= quota <= 20"
    assert isinstance(data.get("nominations_used"), int) and data["nominations_used"] >= 0


def assert_nominee(data: dict):
    _assert_common(data, "Nominee")
    assert isinstance(data.get("city_program_id"), str)
    assert isinstance(data.get("nominator_id"), str)
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    assert isinstance(data.get("first_generation"), bool)
    assert data.get("status") in (
        "NOMINATED", "ROUND_1", "ROUND_2", "ROUND_3", "SELECTED",
        "WAITLISTED", "PLACED", "DROPPED", "WITHDRAWN",
    )
    assert isinstance(data.get("current_round"), int)
    for f in ("round_1_score", "round_2_score", "round_3_score"):
        assert f in data, f"Nominee.{f} must be present (null until 2 evaluations)"
        assert data[f] is None or isinstance(data[f], int)


def assert_evaluation(data: dict):
    assert is_valid_uuid(data.get("id", "")), "Evaluation.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "Evaluation.created_at must be ISO 8601"
    )
    assert "version" not in data, "Evaluation is append-only: no version field"
    assert "updated_at" not in data, "Evaluation is append-only: no updated_at field"
    assert isinstance(data.get("nominee_id"), str)
    assert data.get("round_number") in (1, 2, 3)
    assert isinstance(data.get("assessor_ref"), str) and data["assessor_ref"]
    for f in ("leadership", "teamwork", "group_presence"):
        assert isinstance(data.get(f), int) and 0 <= data[f] <= 100
    assert isinstance(data.get("weighted_score"), int)


def assert_partner_college(data: dict):
    _assert_common(data, "PartnerCollege")
    assert isinstance(data.get("name"), str) and data["name"]
    assert data.get("status") in ("ACTIVE", "PROBATION", "LAPSED")
    assert isinstance(data.get("renewed_cycles_count"), int)
    assert data["renewed_cycles_count"] >= 0


def assert_mentor(data: dict):
    _assert_common(data, "Mentor")
    assert isinstance(data.get("partner_college_id"), str)
    assert isinstance(data.get("full_name"), str) and data["full_name"]


def assert_partner_agreement(data: dict):
    _assert_common(data, "PartnerAgreement")
    assert isinstance(data.get("partner_college_id"), str)
    assert isinstance(data.get("admissions_cycle"), str) and data["admissions_cycle"]
    assert isinstance(data.get("cohort_size"), int)
    assert 3 <= data["cohort_size"] <= 6, "cohort_size must lie within 3 to 6"
    assert isinstance(data.get("tuition_annual_cents"), int)
    assert data["tuition_annual_cents"] > 0
    assert data.get("status") in ("DRAFT", "ACTIVE", "SUPERSEDED", "FULFILLED", "EXPIRED")


def assert_cohort(data: dict):
    _assert_common(data, "Cohort")
    for f in ("agreement_id", "city_program_id", "partner_college_id", "mentor_id"):
        assert isinstance(data.get(f), str), f"Cohort.{f} must be set"
    assert isinstance(data.get("cohort_size"), int) and 3 <= data["cohort_size"] <= 6
    assert isinstance(data.get("tuition_annual_cents"), int)
    assert data.get("status") in ("FORMING", "LOCKED", "MATRICULATED", "COMPLETED")
    for f in ("seats_committed", "offers_outstanding", "seats_remaining",
              "projected_fill_provisional", "projected_fill_final", "meetings_held_count"):
        assert isinstance(data.get(f), int), f"Cohort.{f} must be an integer"
    assert "invoice_total_cents" in data, "Cohort.invoice_total_cents present (null pre-matriculation)"
    assert data["invoice_total_cents"] is None or isinstance(data["invoice_total_cents"], int)
    assert_seat_ledger_invariants(data)


def assert_seat_ledger_invariants(data: dict):
    """PRD §3.4: seats_remaining == cohort_size - committed - outstanding."""
    assert data["seats_remaining"] == (
        data["cohort_size"] - data["seats_committed"] - data["offers_outstanding"]
    ), "seat ledger identity violated"
    assert data["seats_committed"] >= 0
    assert data["offers_outstanding"] >= 0
    assert data["seats_remaining"] >= 0, "the ledger never goes negative"
    assert data["projected_fill_final"] == data["seats_committed"], (
        "final projection always equals committed seats"
    )


def assert_offer(data: dict):
    _assert_common(data, "Offer")
    assert isinstance(data.get("nominee_id"), str)
    assert isinstance(data.get("cohort_id"), str)
    assert data.get("status") in (
        "OFFERED", "ACCEPTED", "DECLINED", "EXPIRED", "REVOKED", "FULFILLED",
    )
    assert is_iso8601_timestamp(data.get("expires_at", "")), "Offer.expires_at ISO 8601"


def assert_scholar(data: dict):
    _assert_common(data, "Scholar")
    assert isinstance(data.get("cohort_id"), str)
    assert isinstance(data.get("nominee_id"), str)
    assert data.get("enrollment_status") in (
        "PRE_COLLEGIATE", "MATRICULATED", "RETAINED", "GRADUATED", "WITHDRAWN", "DISMISSED",
    )
    assert data.get("standing") in ("GOOD_STANDING", "PROBATION")
    assert isinstance(data.get("ever_matriculated"), bool)
    assert isinstance(data.get("training_completed_count"), int)
    assert 0 <= data["training_completed_count"] <= 8
    assert isinstance(data.get("alumni_network_access"), bool)


def assert_training_record(data: dict):
    _assert_common(data, "TrainingRecord")
    assert isinstance(data.get("scholar_id"), str)
    assert data.get("module_code") in tuple(f"T{i}" for i in range(1, 9))
    assert data.get("category") in ("ACADEMIC", "LEADERSHIP", "TEAM_BUILDING")
    assert data.get("status") in ("NOT_STARTED", "COMPLETED")
    assert "completed_at" in data, "TrainingRecord.completed_at present (null until COMPLETED)"
    assert data["completed_at"] is None or is_iso8601_timestamp(data["completed_at"])


def assert_cohort_meeting(data: dict):
    _assert_common(data, "CohortMeeting")
    assert isinstance(data.get("cohort_id"), str)
    assert data.get("kind") in ("COHORT", "INDIVIDUAL")
    for f in ("starts_at", "ends_at"):
        assert is_iso8601_timestamp(data.get(f, "")), f"CohortMeeting.{f} ISO 8601"


def assert_internship(data: dict):
    _assert_common(data, "Internship")
    assert isinstance(data.get("scholar_id"), str)
    assert isinstance(data.get("employer_name"), str) and data["employer_name"]
    assert isinstance(data.get("starts_on"), str) and len(data["starts_on"]) == 10
    assert isinstance(data.get("ends_on"), str) and len(data["ends_on"]) == 10
    assert data.get("status") in ("PROPOSED", "CONFIRMED", "COMPLETED", "TERMINATED")


def assert_outcomes(data: dict):
    """PRD §3.9: the readout returns five fields; rates are integer bps or null."""
    for f in ("retention_bps_census", "graduation_bps_census",
              "retention_bps_rolling", "graduation_bps_rolling"):
        assert f in data, f"outcomes.{f} must be present"
        assert data[f] is None or (isinstance(data[f], int) and 0 <= data[f] <= 10000)
    assert data.get("college_status") in ("ACTIVE", "PROBATION", "LAPSED")
