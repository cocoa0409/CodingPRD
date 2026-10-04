"""Core fixture plumbing: clock, time arithmetic, primitive creators, and
single-step action helpers.

Every helper performs real API calls through the shared client and validates
setup success with the lenient validator, so a broken precondition raises a
clear "Setup step failed" error instead of a confusing assertion later.

Identity threading rule: any judge-scoped call is made with
``make_judge_headers(<existing Judge id>)``; when the caller passes a case or
hearing dict the helper resolves the owning judge id from a fresh read.
"""

from datetime import datetime, timedelta, timezone

from prd_bench_local_runner.testing import get_success_data

from . import constants as _C
from . import factories as _factory
from .api_client import api_client as _api
from .test_users import make_admin_headers, make_board_headers, make_judge_headers

_ADMIN = make_admin_headers()
_BOARD = make_board_headers()


class Bundle(dict):
    """A dict with attribute access, returned by composite fixtures."""

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name)

    def __setattr__(self, name, value):
        self[name] = value


# ─── ISO-8601 / logical-clock time helpers ────────────────────────────────


def parse_instant(value) -> datetime:
    """Parse an ISO 8601 UTC instant ('Z' or offset, optional fractions)."""
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def to_iso_z(dt: datetime) -> str:
    """Render a datetime as ``YYYY-MM-DDTHH:MM:SSZ``."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def add_days(iso: str, days: float) -> str:
    return to_iso_z(parse_instant(iso) + timedelta(days=days))


def add_seconds(iso: str, seconds: float) -> str:
    return to_iso_z(parse_instant(iso) + timedelta(seconds=seconds))


# ─── Logical clock ────────────────────────────────────────────────────────


def set_clock(to_iso8601: str = _C.CLOCK_DEFAULT_ISO) -> dict:
    """Advance the server's logical clock (CourtAdministrator-only, 200)."""
    return get_success_data(_api.set_clock(to_iso8601, headers=_ADMIN))


def reset_clock() -> dict:
    """Pin the logical clock to its documented default instant."""
    return set_clock(_C.CLOCK_DEFAULT_ISO)


# ─── Primitive creators (201s) ────────────────────────────────────────────


def create_court(**overrides) -> dict:
    return get_success_data(_api.create_court(_factory.make_court_payload(**overrides),
                                              headers=_ADMIN))


def create_judge(court_id, **overrides) -> dict:
    return get_success_data(_api.create_judge(
        _factory.make_judge_payload(court_id, **overrides), headers=_ADMIN))


def create_interpreter(court_id, **overrides) -> dict:
    return get_success_data(_api.create_interpreter(
        _factory.make_interpreter_payload(court_id, **overrides), headers=_ADMIN))


def create_orientation_program(court_id, **overrides) -> dict:
    return get_success_data(_api.create_orientation_program(
        _factory.make_orientation_program_payload(court_id, **overrides), headers=_ADMIN))


def set_program_coverage(program_id, **fields) -> dict:
    """Update coverage_pct and/or active; returns the updated program (200)."""
    return get_success_data(_api.set_program_coverage(
        program_id, _factory.make_set_coverage_payload(**fields), headers=_ADMIN))


def create_case(court_id, **overrides) -> dict:
    """File a case; defaults are NON_DETAINED English PRO_SE, no interpreter."""
    return get_success_data(_api.create_case(
        _factory.make_case_payload(court_id, **overrides), headers=_ADMIN))


# ─── Reads ────────────────────────────────────────────────────────────────


def read_case(case_id) -> dict:
    return get_success_data(_api.get_case(case_id, headers=_ADMIN))


def read_court(court_id) -> dict:
    return get_success_data(_api.get_court(court_id, headers=_ADMIN))


def read_hearing(hearing_id) -> dict:
    return get_success_data(_api.get_hearing(hearing_id, headers=_ADMIN))


def read_judge(judge_id) -> dict:
    return get_success_data(_api.get_judge(judge_id, headers=_ADMIN))


def read_decision(decision_id) -> dict:
    return get_success_data(_api.get_decision(decision_id, headers=_ADMIN))


def case_version(case_id) -> int:
    """Freshly read Case.version — the value OCC-guarded writes must carry."""
    return read_case(case_id)["version"]


def list_case_hearings(case_id, status=None) -> list:
    params = {"case_id": case_id, "limit": 100}
    if status:
        params["status"] = status
    return get_success_data(_api.list_hearings(headers=_ADMIN, params=params))


def list_case_decisions(case_id, status=None) -> list:
    params = {"case_id": case_id, "limit": 100}
    if status:
        params["status"] = status
    return get_success_data(_api.list_decisions(headers=_ADMIN, params=params))


def scheduled_hearing_of(case_id) -> dict:
    """The case's single live SCHEDULED hearing, or None."""
    hearings = list_case_hearings(case_id, status="SCHEDULED")
    return hearings[0] if hearings else None


def decision_of_case(case_id, status=None) -> dict:
    decisions = list_case_decisions(case_id, status=status)
    return decisions[0] if decisions else None


# ─── Case actions ─────────────────────────────────────────────────────────


def assign_case_to_judge(case_id, judge_id) -> dict:
    """Docket a FILED case (FILED -> CALENDAR); returns the updated case."""
    return get_success_data(_api.assign_judge(
        case_id, _factory.make_assign_judge_payload(judge_id), headers=_ADMIN))


def close_case_administratively(case, closure_reason="PENDING_APPLICATION",
                                judge_id=None) -> dict:
    """Judge-side administrative closure; returns the ADMIN_CLOSED case."""
    case_id = case["id"] if isinstance(case, dict) else case
    if judge_id is None:
        judge_id = read_case(case_id)["assigned_judge_id"]
    return get_success_data(_api.administrative_closure(
        case_id, _factory.make_closure_payload(closure_reason),
        headers=make_judge_headers(judge_id)))


def recalendar_case(case, judge_id=None) -> dict:
    """ADMIN_CLOSED -> MERITS; returns the updated case."""
    case_id = case["id"] if isinstance(case, dict) else case
    if judge_id is None:
        judge_id = read_case(case_id)["assigned_judge_id"]
    return get_success_data(_api.recalendar_case(
        case_id, headers=make_judge_headers(judge_id)))


# ─── Hearings ─────────────────────────────────────────────────────────────


def schedule_hearing(case, hearing_type, scheduled_start, *,
                     is_remote=None, expected_case_version=None) -> dict:
    """Create a hearing (201).  Re-reads the case for the OCC version unless
    one is supplied; ``is_remote`` defaults to True for DETAINED cases (the
    remote-technology mandate) and is omitted otherwise."""
    case_id = case["id"] if isinstance(case, dict) else case
    if expected_case_version is None or is_remote is None:
        fresh = read_case(case_id)
        if expected_case_version is None:
            expected_case_version = fresh["version"]
        if is_remote is None and fresh["custody_status"] == "DETAINED":
            is_remote = True
    payload = _factory.make_hearing_payload(
        case_id, hearing_type, scheduled_start, expected_case_version,
        is_remote=is_remote)
    return get_success_data(_api.create_hearing(payload, headers=_ADMIN))


def complete_hearing(hearing, judge_id=None) -> dict:
    """Judge-side completion; judge defaults to the hearing's own judge."""
    hearing_id = hearing["id"] if isinstance(hearing, dict) else hearing
    if judge_id is None:
        judge_id = read_hearing(hearing_id)["judge_id"]
    return get_success_data(_api.complete_hearing(
        hearing_id, headers=make_judge_headers(judge_id)))


def record_no_show(hearing, judge_id=None) -> dict:
    """Judge-side no-show recording; returns the NO_SHOW hearing."""
    hearing_id = hearing["id"] if isinstance(hearing, dict) else hearing
    if judge_id is None:
        judge_id = read_hearing(hearing_id)["judge_id"]
    return get_success_data(_api.record_no_show(
        hearing_id, headers=make_judge_headers(judge_id)))


# ─── Notices ──────────────────────────────────────────────────────────────


def serve_notice(hearing_id, **overrides) -> dict:
    """Record service of notice (201); defaults MAIL, served 2026-08-20."""
    return get_success_data(_api.create_notice(
        _factory.make_notice_payload(hearing_id, **overrides), headers=_ADMIN))


def mark_notice_defective(notice_id) -> dict:
    return get_success_data(_api.mark_notice_defective(notice_id, headers=_ADMIN))


# ─── Continuances ─────────────────────────────────────────────────────────


def file_continuance(case_id, hearing_id, reason_code="EVIDENCE_GATHERING") -> dict:
    return get_success_data(_api.create_continuance_request(
        _factory.make_continuance_payload(case_id, hearing_id, reason_code),
        headers=_ADMIN))


def _resolve_judge_for_case(case_id, judge_id):
    if judge_id is not None:
        return judge_id
    return read_case(case_id)["assigned_judge_id"]


def decide_continuance(request, decision="GRANTED", judge_id=None) -> dict:
    """Judge ruling on a continuance; judge defaults to the case's assignee."""
    if isinstance(request, dict):
        request_id = request["id"]
        case_id = request.get("case_id")
    else:
        request_id = request
        case_id = None
    if judge_id is None:
        if case_id is None:
            case_id = get_success_data(
                _api.get_continuance_request(request_id, headers=_ADMIN))["case_id"]
        judge_id = _resolve_judge_for_case(case_id, None)
    return get_success_data(_api.decide_continuance_request(
        request_id, _factory.make_ruling_payload(decision),
        headers=make_judge_headers(judge_id)))


# ─── Venue motions ────────────────────────────────────────────────────────


def file_venue_motion(case_id, destination_court_id, reason="respondent moved") -> dict:
    return get_success_data(_api.create_venue_motion(
        _factory.make_venue_motion_payload(case_id, destination_court_id, reason),
        headers=_ADMIN))


def decide_venue_motion(motion, decision="GRANTED", judge_id=None) -> dict:
    if isinstance(motion, dict):
        motion_id = motion["id"]
        case_id = motion.get("case_id")
    else:
        motion_id = motion
        case_id = None
    if judge_id is None:
        if case_id is None:
            case_id = get_success_data(
                _api.get_venue_motion(motion_id, headers=_ADMIN))["case_id"]
        judge_id = _resolve_judge_for_case(case_id, None)
    return get_success_data(_api.decide_venue_motion(
        motion_id, _factory.make_ruling_payload(decision),
        headers=make_judge_headers(judge_id)))


# ─── Decisions / appeals / motions to reopen ──────────────────────────────


def issue_decision(case, outcome="REMOVAL", *,
                   judge_id=None, expected_case_version=None) -> dict:
    """Judge issues a decision on a MERITS case (201)."""
    case_id = case["id"] if isinstance(case, dict) else case
    fresh = read_case(case_id)
    if judge_id is None:
        judge_id = fresh["assigned_judge_id"]
    if expected_case_version is None:
        expected_case_version = fresh["version"]
    payload = _factory.make_decision_payload(
        case_id, outcome, expected_case_version)
    return get_success_data(_api.create_decision(
        payload, headers=make_judge_headers(judge_id)))


def file_appeal(decision_id, grounds=None) -> dict:
    return get_success_data(_api.create_appeal(
        _factory.make_appeal_payload(decision_id, grounds), headers=_ADMIN))


def decide_appeal(appeal_id, ruling, remand_instructions=None,
                  board_member_id=None) -> dict:
    """Board ruling; remand_instructions required iff ruling is REMANDED."""
    headers = (_BOARD if board_member_id is None
               else make_board_headers(board_member_id))
    return get_success_data(_api.decide_appeal(
        appeal_id, _factory.make_appeal_ruling_payload(ruling, remand_instructions),
        headers=headers))


def file_motion_to_reopen(case_id, decision_id,
                          basis="EXCEPTIONAL_CIRCUMSTANCES") -> dict:
    return get_success_data(_api.create_motion_to_reopen(
        _factory.make_motion_to_reopen_payload(case_id, decision_id, basis),
        headers=_ADMIN))


def decide_motion_to_reopen(motion, decision="GRANTED", judge_id=None) -> dict:
    if isinstance(motion, dict):
        motion_id = motion["id"]
        case_id = motion.get("case_id")
    else:
        motion_id = motion
        case_id = None
    if judge_id is None:
        if case_id is None:
            case_id = get_success_data(
                _api.get_motion_to_reopen(motion_id, headers=_ADMIN))["case_id"]
        judge_id = _resolve_judge_for_case(case_id, None)
    return get_success_data(_api.decide_motion_to_reopen(
        motion_id, _factory.make_ruling_payload(decision),
        headers=make_judge_headers(judge_id)))


# ─── Reassignment / docket review ─────────────────────────────────────────


def reassign_case(case, *, expected_case_version=None) -> dict:
    """Execute a backlog reassignment (201); version re-read unless given."""
    case_id = case["id"] if isinstance(case, dict) else case
    if expected_case_version is None:
        expected_case_version = case_version(case_id)
    payload = _factory.make_reassignment_payload(case_id, expected_case_version)
    return get_success_data(_api.create_case_reassignment(payload, headers=_ADMIN))


def run_docket_review(court_id) -> dict:
    """Run the court's docket checkpoint (201); returns the DocketReview."""
    return get_success_data(_api.create_docket_review(court_id, headers=_ADMIN))


__all__ = [
    "Bundle",
    "parse_instant", "to_iso_z", "add_days", "add_seconds",
    "set_clock", "reset_clock",
    "create_court", "create_judge", "create_interpreter",
    "create_orientation_program", "set_program_coverage", "create_case",
    "read_case", "read_court", "read_hearing", "read_judge", "read_decision",
    "case_version", "list_case_hearings", "list_case_decisions",
    "scheduled_hearing_of", "decision_of_case",
    "assign_case_to_judge", "close_case_administratively", "recalendar_case",
    "schedule_hearing", "complete_hearing", "record_no_show",
    "serve_notice", "mark_notice_defective",
    "file_continuance", "decide_continuance",
    "file_venue_motion", "decide_venue_motion",
    "issue_decision", "file_appeal", "decide_appeal",
    "file_motion_to_reopen", "decide_motion_to_reopen",
    "reassign_case", "run_docket_review",
]
