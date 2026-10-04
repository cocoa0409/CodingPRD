"""Entity assertions and domain invariant checkers.

Structural checks only: identity fields, timestamp shapes, version counters
and state-enum membership — the properties the PRD pins for every resource.
Value-level expectations (a specific posture, a specific cent total) live in
the tests that assert them, next to the PRD sentence they cite.
"""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_mutable_common_fields(data: dict, label: str) -> None:
    """id + created_at + updated_at + version, as the PRD's common-fields rule."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be an ISO 8601 UTC timestamp, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be an ISO 8601 UTC timestamp, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be an integer starting at 1, got {data.get('version')!r}"
    )


def assert_site(data: dict) -> None:
    _assert_mutable_common_fields(data, "Site")
    assert data.get("status") in ("SETUP", "ACTIVE", "CLOSED"), (
        f"Site.status out of range: {data.get('status')!r}"
    )
    assert data.get("funding_posture") in ("FUNDED", "TIGHT", "DEFICIT"), (
        f"Site.funding_posture out of range: {data.get('funding_posture')!r}"
    )


def assert_school(data: dict) -> None:
    _assert_mutable_common_fields(data, "School")
    assert data.get("agreement_status") in (
        "DRAFT", "SIGNED", "ACTIVE", "AMENDMENT_REVIEW", "SUSPENDED", "COMPLETED", "TERMINATED",
    ), f"School.agreement_status out of range: {data.get('agreement_status')!r}"
    assert data.get("data_sharing_status") in ("DRAFT", "SIGNED", "EXPIRED"), (
        f"School.data_sharing_status out of range: {data.get('data_sharing_status')!r}"
    )


def assert_application(data: dict) -> None:
    _assert_mutable_common_fields(data, "CorpsMemberApplication")
    assert data.get("status") in (
        "SUBMITTED", "SCREENED_ELIGIBLE", "INTERVIEWED", "OFFERED", "ACCEPTED",
        "ENROLLED", "REJECTED", "WITHDRAWN", "DECLINED",
    ), f"CorpsMemberApplication.status out of range: {data.get('status')!r}"


def assert_corps_member(data: dict) -> None:
    _assert_mutable_common_fields(data, "CorpsMember")
    assert data.get("service_status") in (
        "ENROLLED", "ACTIVE", "SUSPENDED", "EXITED_EARLY", "COMPLETED",
    ), f"CorpsMember.service_status out of range: {data.get('service_status')!r}"
    assert data.get("stipend_status") in ("NOT_STARTED", "ACTIVE", "SUSPENDED", "ENDED"), (
        f"CorpsMember.stipend_status out of range: {data.get('stipend_status')!r}"
    )
    assert data.get("award_status") in (
        "NOT_EARNED", "EARNED_FULL", "EARNED_PARTIAL", "FORFEITED", "DISBURSED",
    ), f"CorpsMember.award_status out of range: {data.get('award_status')!r}"


def assert_team(data: dict) -> None:
    _assert_mutable_common_fields(data, "Team")
    assert data.get("status") in ("FORMING", "DEPLOYED", "UNDERSTAFFED", "COMPLETED", "DISSOLVED"), (
        f"Team.status out of range: {data.get('status')!r}"
    )


def assert_team_assignment(data: dict) -> None:
    _assert_mutable_common_fields(data, "TeamAssignment")
    assert data.get("status") in ("ACTIVE", "ENDED"), (
        f"TeamAssignment.status out of range: {data.get('status')!r}"
    )


def assert_student(data: dict) -> None:
    _assert_mutable_common_fields(data, "Student")
    assert data.get("enrollment_status") in ("ACTIVE", "EXITED"), (
        f"Student.enrollment_status out of range: {data.get('enrollment_status')!r}"
    )
    assert data.get("caseload_status") in ("UNASSIGNED", "ASSIGNED"), (
        f"Student.caseload_status out of range: {data.get('caseload_status')!r}"
    )


def assert_hour_entry(data: dict) -> None:
    """The one append-and-review record: id + created_at, no updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), f"ServiceHourEntry.id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"ServiceHourEntry.created_at must be an ISO 8601 UTC timestamp, got {data.get('created_at')!r}"
    )
    assert "version" not in data, "ServiceHourEntry must not carry a version field"
    assert "updated_at" not in data, "ServiceHourEntry must not carry an updated_at field"
    assert data.get("status") in ("PENDING", "VERIFIED", "REJECTED", "VOIDED"), (
        f"ServiceHourEntry.status out of range: {data.get('status')!r}"
    )


def assert_stipend_payment(data: dict) -> None:
    _assert_mutable_common_fields(data, "StipendPayment")
    assert data.get("status") in ("SCHEDULED", "APPROVED", "PAID", "FORFEITED", "CLAWED_BACK"), (
        f"StipendPayment.status out of range: {data.get('status')!r}"
    )


def assert_evaluation_report(data: dict) -> None:
    _assert_mutable_common_fields(data, "EvaluationReport")
    assert data.get("status") in ("DRAFT", "SUBMITTED", "RETURNED", "ACCEPTED"), (
        f"EvaluationReport.status out of range: {data.get('status')!r}"
    )


def assert_cash_conserved(site: dict, members: list) -> None:
    """The pay/clawback conserved quantity: site outlay equals the members' net."""
    member_net_total = sum(m.get("net_stipend_received_cents", 0) for m in members)
    assert site.get("stipend_outlay_cents") == member_net_total, (
        f"I-CASH violated: site outlay {site.get('stipend_outlay_cents')} "
        f"!= sum of member net {member_net_total}"
    )


def assert_posture_matches_headroom(site: dict) -> None:
    """The posture band boundaries: DEFICIT below 0, TIGHT below 500000, else FUNDED."""
    headroom = site.get("funding_headroom_cents")
    posture = site.get("funding_posture")
    if headroom < 0:
        expected = "DEFICIT"
    elif headroom < 500_000:
        expected = "TIGHT"
    else:
        expected = "FUNDED"
    assert posture == expected, (
        f"funding_posture {posture!r} inconsistent with headroom {headroom} (expected {expected})"
    )
