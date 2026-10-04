"""Composite setup fixtures: multi-step lifecycle chains built from the core
primitives (re-exported here so tests import one module).

The chains mirror the standard docket lifecycle — filing, docketing, master
and merits hearings, decision, appeal, board ruling — plus the in-absentia
track (served notice, no-show, motion to reopen) and the backlog-reassignment
track.  Every chain pins the logical clock explicitly and re-reads entities
after each mutating step so OCC versions and computed fields are fresh.

Common anchors (defaults, all overridable):
- master hearing 2026-09-03T10:00Z, completed at clock 2026-09-03T10:30Z
- merits hearing 2026-09-04T10:00Z, completed at clock 2026-09-04T12:00Z
- no-show hearing 2026-09-05T10:00Z with a notice served 2026-08-20, no-show
  recorded at clock 2026-09-05T11:00Z
"""

from ._fixture_core import *  # noqa: F401,F403  (primitives are part of the surface)
from ._fixture_core import (
    Bundle,
    assign_case_to_judge,
    case_version,
    create_case,
    create_court,
    create_judge,
    decide_appeal,
    decide_continuance,
    decide_motion_to_reopen,
    decision_of_case,
    file_appeal,
    file_continuance,
    file_motion_to_reopen,
    file_venue_motion,
    issue_decision,
    mark_notice_defective,
    read_case,
    read_court,
    read_decision,
    record_no_show,
    reset_clock,
    scheduled_hearing_of,
    schedule_hearing,
    serve_notice,
    set_clock,
    complete_hearing,
)
from .constants import (
    MASTER_HEARING_CLOCK_ISO,
    MASTER_HEARING_START_ISO,
    MERITS_HEARING_CLOCK_ISO,
    MERITS_HEARING_START_ISO,
    NOSHOW_CLOCK_ISO,
    NOSHOW_HEARING_START_ISO,
    NOTICE_SERVED_AT_ISO,
)


# ─── Tier 1/2: docketed case world ────────────────────────────────────────


def setup_docketed_case(*, custody_status="NON_DETAINED", primary_language_code="eng",
                        representation_status="PRO_SE", interpreter_required=False,
                        court=None, judge=None, case_overrides=None,
                        court_overrides=None, judge_overrides=None,
                        initial_clock=True) -> Bundle:
    """Court + judge + case docketed to that judge (case CALENDAR).

    Returns Bundle(court, judge, case); ``case`` is the post-docket read with
    assigned_judge_id set.  Pass an existing ``court``/``judge`` to stack
    several cases onto the same bench.
    """
    if initial_clock:
        reset_clock()
    court = court or create_court(**(court_overrides or {}))
    judge = judge or create_judge(court["id"], **(judge_overrides or {}))
    payload_overrides = {
        "custody_status": custody_status,
        "primary_language_code": primary_language_code,
        "representation_status": representation_status,
        "interpreter_required": interpreter_required,
    }
    payload_overrides.update(case_overrides or {})
    case = create_case(court["id"], **payload_overrides)
    case = assign_case_to_judge(case["id"], judge["id"])
    return Bundle(court=court, judge=judge, case=case, case_version=case["version"])


# ─── Tier 3: lifecycle progressions ───────────────────────────────────────


def advance_case_to_merits(case, *, judge_id=None,
                           master_start=MASTER_HEARING_START_ISO,
                           master_clock=MASTER_HEARING_CLOCK_ISO) -> Bundle:
    """Schedule + complete a master hearing; case CALENDAR -> MERITS.

    The clock is moved to ``master_clock`` (at/after the start) before the
    completion.  Returns Bundle(case, master_hearing); the case is refreshed.
    """
    hearing = schedule_hearing(case, "MASTER_CALENDAR", master_start)
    set_clock(master_clock)
    hearing = complete_hearing(hearing, judge_id=judge_id)
    case_id = case["id"] if isinstance(case, dict) else case
    return Bundle(case=read_case(case_id), master_hearing=hearing)


def advance_case_to_decided(case, *, outcome="REMOVAL", judge_id=None,
                            merits_start=MERITS_HEARING_START_ISO,
                            merits_clock=MERITS_HEARING_CLOCK_ISO) -> Bundle:
    """Schedule + complete a merits hearing, then issue a decision; the case
    lands in DECIDED with an ISSUED decision whose appeal window is open."""
    hearing = schedule_hearing(case, "INDIVIDUAL_MERITS", merits_start)
    set_clock(merits_clock)
    hearing = complete_hearing(hearing, judge_id=judge_id)
    case_id = case["id"] if isinstance(case, dict) else case
    decision = issue_decision(case_id, outcome, judge_id=judge_id)
    return Bundle(case=read_case(case_id), merits_hearing=hearing, decision=decision)


def setup_decided_case(*, outcome="REMOVAL", **case_kw) -> Bundle:
    """Full merits path: court/judge/docketed case -> MERITS -> DECIDED.
    Clock ends at the merits-completion instant (inside the appeal window)."""
    ctx = setup_docketed_case(**case_kw)
    m = advance_case_to_merits(ctx["case"], judge_id=ctx["judge"]["id"])
    d = advance_case_to_decided(m["case"], outcome=outcome,
                                judge_id=ctx["judge"]["id"])
    return Bundle(court=ctx["court"], judge=ctx["judge"], case=d["case"],
                  master_hearing=m["master_hearing"],
                  merits_hearing=d["merits_hearing"], decision=d["decision"])


def setup_appealed_case(*, grounds=None, **case_kw) -> Bundle:
    """Decided case plus a filed appeal: case APPEALED, decision APPEAL_PENDING."""
    ctx = setup_decided_case(**case_kw)
    appeal = file_appeal(ctx["decision"]["id"], grounds=grounds)
    ctx.update(case=read_case(ctx["case"]["id"]), appeal=appeal)
    return ctx


def setup_completed_case(*, ruling="AFFIRMED", **case_kw) -> Bundle:
    """Appealed case ruled AFFIRMED or DISMISSED: decision FINAL, case
    COMPLETED with completed_at stamped at the ruling clock."""
    ctx = setup_appealed_case(**case_kw)
    appeal = decide_appeal(ctx["appeal"]["id"], ruling)
    ctx.update(case=read_case(ctx["case"]["id"]), appeal=appeal,
               decision=read_decision(ctx["decision"]["id"]))
    return ctx


def setup_remanded_case(*, remand_instructions="Reassess the record", **case_kw) -> Bundle:
    """Appealed case ruled REMANDED: decision REMANDED, case back in MERITS,
    and a system-created merits hearing scheduled at clock + 42 days."""
    ctx = setup_appealed_case(**case_kw)
    appeal = decide_appeal(ctx["appeal"]["id"], "REMANDED",
                           remand_instructions=remand_instructions)
    case = read_case(ctx["case"]["id"])
    ctx.update(case=case, appeal=appeal, decision=read_decision(ctx["decision"]["id"]),
               remand_hearing=scheduled_hearing_of(case["id"]))
    return ctx


# ─── In-absentia track ────────────────────────────────────────────────────


def setup_case_in_absentia(*, service_method="MAIL",
                           notice_served_at=NOTICE_SERVED_AT_ISO,
                           hearing_start=NOSHOW_HEARING_START_ISO,
                           noshow_clock=NOSHOW_CLOCK_ISO, **case_kw) -> Bundle:
    """Docketed case whose master hearing's respondent did not appear:
    hearing NO_SHOW, case IN_ABSENTIA, and a system-created
    IN_ABSENTIA_REMOVAL decision (ISSUED) whose 30/180-day windows run from
    the no-show clock.  Returns Bundle(court, judge, case, hearing, notice,
    decision)."""
    ctx = setup_docketed_case(**case_kw)
    hearing = schedule_hearing(ctx["case"], "MASTER_CALENDAR", hearing_start)
    notice = serve_notice(hearing["id"], service_method=service_method,
                          served_at=notice_served_at)
    set_clock(noshow_clock)
    hearing = record_no_show(hearing, judge_id=ctx["judge"]["id"])
    case = read_case(ctx["case"]["id"])
    decision = decision_of_case(case["id"])
    ctx.update(case=case, hearing=hearing, notice=notice, decision=decision)
    return ctx


def setup_in_absentia_with_defective_notice(**kw) -> Bundle:
    """In-absentia case whose no-show hearing's notice is then marked
    DEFECTIVE — the precondition for a NOTICE_DEFECTIVE motion to reopen."""
    ctx = setup_case_in_absentia(**kw)
    ctx["notice"] = mark_notice_defective(ctx["notice"]["id"])
    return ctx


def setup_in_absentia_with_motion(*, basis="EXCEPTIONAL_CIRCUMSTANCES",
                                  motion_clock="2026-09-06T00:00:00Z", **kw) -> Bundle:
    """In-absentia case with a FILED motion to reopen (motion filed at
    ``motion_clock``, inside the 180-day window for either basis)."""
    ctx = setup_case_in_absentia(**kw)
    set_clock(motion_clock)
    motion = file_motion_to_reopen(ctx["case"]["id"], ctx["decision"]["id"], basis)
    ctx.update(motion=motion)
    return ctx


def grant_reopen_motion(ctx, decision="GRANTED") -> Bundle:
    """Rule on the in-absentia world's motion; on GRANTED the decision is
    RESCINDED, the case returns to CALENDAR, and a reopen master hearing is
    auto-created at clock + 21 days.  Returns Bundle(motion, case,
    reopen_hearing)."""
    motion = decide_motion_to_reopen(ctx["motion"], decision,
                                     judge_id=ctx["judge"]["id"])
    case = read_case(ctx["case"]["id"])
    return Bundle(motion=motion, case=case,
                  reopen_hearing=scheduled_hearing_of(case["id"]))


# ─── Tier 4: accumulation / threshold targeting ───────────────────────────


def grant_continuances(case_id, judge_id, count, *,
                       reason_code="EVIDENCE_GATHERING") -> Bundle:
    """File + grant ``count`` continuances in sequence against the case's live
    SCHEDULED hearing; each grant supersedes the hearing (start += 7/28 days
    by custody).  Returns Bundle(requests, superseded_hearings,
    scheduled_hearing, case) with the case refreshed (continuance_count ==
    count)."""
    requests, superseded = [], []
    for _ in range(count):
        hearing = scheduled_hearing_of(case_id)
        assert hearing is not None, "expected a live SCHEDULED hearing to continue"
        req = file_continuance(case_id, hearing["id"], reason_code)
        req = decide_continuance(req, "GRANTED", judge_id=judge_id)
        requests.append(req)
        superseded.append(hearing)
    case = read_case(case_id)
    return Bundle(requests=requests, superseded_hearings=superseded,
                  scheduled_hearing=scheduled_hearing_of(case_id), case=case)


# ─── Backlog / reassignment track ─────────────────────────────────────────


def setup_backlog_critical_source(*, source_goal=4, dest_goal=100,
                                  custody_status="NON_DETAINED",
                                  initial_clock=True) -> Bundle:
    """Source court made backlog-critical by construction (``source_goal`` 4 ->
    threshold ceil(0.25*4) = 1 pending case) holding one case, plus an
    eligible empty destination court.  Courts are returned re-read so their
    computed backlog fields are live.  Bundle(source_court, dest_court, case).
    """
    if initial_clock:
        reset_clock()
    source = create_court(annual_completion_goal=source_goal)
    dest = create_court(annual_completion_goal=dest_goal)
    case = create_case(source["id"], custody_status=custody_status)
    return Bundle(source_court=read_court(source["id"]),
                  dest_court=read_court(dest["id"]),
                  case=read_case(case["id"]))


# ─── Venue-motion track ───────────────────────────────────────────────────


def setup_venue_motion_pending(*, reason="respondent moved", **case_kw) -> Bundle:
    """Docketed case plus a second court and a PENDING change-of-venue motion
    to it.  Bundle(court, judge, case, dest_court, motion)."""
    ctx = setup_docketed_case(**case_kw)
    dest = create_court()
    motion = file_venue_motion(ctx["case"]["id"], dest["id"], reason)
    ctx.update(dest_court=dest, motion=motion)
    return ctx


__all__ = [
    # re-exported core primitives
    "Bundle", "parse_instant", "to_iso_z", "add_days", "add_seconds",
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
    # composite chains
    "setup_docketed_case", "advance_case_to_merits", "advance_case_to_decided",
    "setup_decided_case", "setup_appealed_case", "setup_completed_case",
    "setup_remanded_case", "setup_case_in_absentia",
    "setup_in_absentia_with_defective_notice", "setup_in_absentia_with_motion",
    "grant_reopen_motion", "grant_continuances",
    "setup_backlog_critical_source", "setup_venue_motion_pending",
]
