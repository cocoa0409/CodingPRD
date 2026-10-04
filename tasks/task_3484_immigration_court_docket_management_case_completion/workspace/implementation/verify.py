#!/usr/bin/env python3
# verify.py — deeper self-verification of lifecycle, cascades, calculations,
# and validation-tier precedence. Boots start.sh on a dynamic port, kills only
# the PID it started. Exits nonzero on any failure.
import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

IMPL_DIR = os.path.dirname(os.path.abspath(__file__))
ADMIN = {"X-User-ID": "admin-1", "X-User-Role": "CourtAdministrator"}
BOARD = {"X-User-ID": "board-1", "X-User-Role": "BoardMember"}
FAILURES = []
BASE = None


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def call(method, path, headers=None, body=None):
    hdrs = {"Content-Type": "application/json"}
    if headers:
        hdrs.update(headers)
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, headers=hdrs,
                                 method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, {"_raw": raw}
    except urllib.error.URLError as e:
        return None, {"_error": str(e)}


def check(label, cond, detail=""):
    print("[%s] %s %s" % ("ok" if cond else "FAIL", label, detail))
    if not cond:
        FAILURES.append(label)


def jcreate(body, headers=ADMIN):
    return call("POST", "/eoir/" + body[0], headers=headers, body=body[1])


def set_clock(ts):
    code, _ = call("POST", "/eoir/_clock/set_current_utc", headers=ADMIN,
                   body={"to_iso8601": ts})
    assert code == 200, ("clock set failed", code)


def mk_court(code, goal=100, cap=5):
    c, b = jcreate(("courts", {"court_code": code, "name": code, "city": "X",
                               "annual_completion_goal": goal,
                               "detained_daily_hearing_capacity": cap}))
    assert c == 201, (c, b)
    return b["data"]["id"]


def mk_judge(court_id, name="J", maxp=10):
    c, b = jcreate(("judges", {"court_id": court_id, "full_name": name,
                               "max_pending_cases": maxp}))
    assert c == 201, (c, b)
    return b["data"]["id"]


def jhdr(jid):
    return {"X-User-ID": jid, "X-User-Role": "ImmigrationJudge"}


def mk_interp(court_id, langs=("spa",), cap=4, name="I"):
    c, b = jcreate(("interpreters", {"court_id": court_id, "full_name": name,
                                     "language_codes": list(langs),
                                     "daily_hearing_cap": cap}))
    assert c == 201, (c, b)
    return b["data"]["id"]


def mk_case(court_id, number, custody="NON_DETAINED", lang="spa",
            rep="PRO_SE", interp_required=True):
    c, b = jcreate(("cases", {"court_id": court_id, "case_number": number,
                              "respondent_full_name": "R " + number,
                              "custody_status": custody,
                              "primary_language_code": lang,
                              "representation_status": rep,
                              "interpreter_required": interp_required}))
    assert c == 201, (c, b)
    return b["data"]


def assign(case_id, jid):
    c, b = call("POST", "/eoir/cases/%s/assign-judge" % case_id,
                headers=ADMIN, body={"judge_id": jid})
    assert c == 200, (c, b)
    return b["data"]


def schedule(case_id, htype, start, version, remote=None):
    body = {"case_id": case_id, "hearing_type": htype,
            "scheduled_start": start, "expected_case_version": version}
    if remote is not None:
        body["is_remote"] = remote
    return call("POST", "/eoir/hearings", headers=ADMIN, body=body)


def main():
    global BASE
    port = free_port()
    BASE = "http://127.0.0.1:%d" % port
    log = open(os.path.join(IMPL_DIR, "verify_server.log"), "w")
    env = dict(os.environ, PORT=str(port))
    proc = subprocess.Popen(["bash", "start.sh"], cwd=IMPL_DIR, env=env,
                            stdout=log, stderr=subprocess.STDOUT,
                            start_new_session=True)
    try:
        deadline = time.time() + 45
        while True:
            code, _ = call("GET", "/eoir/courts/nope", headers=ADMIN)
            if code is not None:
                break
            if time.time() > deadline:
                print("[FAIL] server not ready")
                return 1
            time.sleep(0.25)

        # ================= A. full merits lifecycle + appeal affirm ========
        set_clock("2026-09-01T00:00:00Z")
        court = mk_court("C-A")
        courtA = court
        judge = mk_judge(court, "JA")
        interp = mk_interp(court, ("spa",))
        case = mk_case(court, "A-1")
        cid = case["id"]
        case = assign(cid, judge)
        c, b = schedule(cid, "MASTER_CALENDAR", "2026-09-02T09:00:00Z", 2)
        check("A.master.schedule", c == 201, "-> %s %s" % (c, str(b)[:160]))
        hid = b["data"]["id"]
        # notice served
        c, b = jcreate(("notices", {"hearing_id": hid,
                                    "service_method": "MAIL",
                                    "served_at": "2026-09-01T00:00:00Z"}))
        check("A.notice", c == 201 and b["data"]["status"] == "SERVED",
              "-> %s" % c)
        # duplicate notice -> 409
        c, b = jcreate(("notices", {"hearing_id": hid,
                                    "service_method": "MAIL",
                                    "served_at": "2026-09-01T00:00:00Z"}))
        check("A.notice.dup", c == 409 and b["data"]["error_id"] ==
              "ERR_NOTICE_ALREADY_RECORDED", "-> %s" % c)
        # complete too early -> 409 NOT_YET_DUE (and wrong judge wins tier 4)
        c, b = call("POST", "/eoir/hearings/%s/complete" % hid,
                    headers=jhdr(judge))
        check("A.complete.early", c == 409 and b["data"]["error_id"] ==
              "ERR_HEARING_NOT_YET_DUE", "-> %s" % c)
        set_clock("2026-09-02T09:00:00Z")
        c, b = call("POST", "/eoir/hearings/%s/complete" % hid,
                    headers=jhdr(mk_judge(court, "JX")))
        check("A.complete.wrongjudge", c == 403 and b["data"]["error_id"] ==
              "ERR_NOT_HEARING_JUDGE", "-> %s" % c)
        c, b = call("POST", "/eoir/hearings/%s/complete" % hid,
                    headers=jhdr(judge))
        check("A.complete", c == 200 and b["data"]["status"] == "COMPLETED",
              "-> %s" % c)
        # merits hearing (PRO_SE non-detained merits = 120 min)
        c, b = schedule(cid, "INDIVIDUAL_MERITS", "2026-09-03T09:00:00Z", 4)
        check("A.merits.schedule", c == 201
              and b["data"]["duration_minutes"] == 120, "-> %s" % c)
        mid = b["data"]["id"]
        set_clock("2026-09-03T09:00:00Z")
        c, b = call("POST", "/eoir/hearings/%s/complete" % mid,
                    headers=jhdr(judge))
        check("A.merits.complete", c == 200, "-> %s" % c)
        # in-absentia outcome is system-only: case is MERITS with a completed
        # merits hearing and a fresh version, so tier-10 semantics decide
        c, b = call("POST", "/eoir/decisions", headers=jhdr(judge),
                    body={"case_id": cid, "outcome": "IN_ABSENTIA_REMOVAL",
                          "expected_case_version": 5})
        check("A.decision.in_absentia_422", c == 422 and b["data"]["error_id"]
              == "ERR_IN_ABSENTIA_OUTCOME_NOT_CREATABLE", "-> %s" % c)
        # decision: OCC uses current version (case version: create=1,
        # assign=2, master hearing=3, complete->MERITS=4, merits hearing=5)
        c, b = call("POST", "/eoir/decisions", headers=jhdr(judge),
                    body={"case_id": cid, "outcome": "REMOVAL",
                          "expected_case_version": 5})
        dec = b.get("data", {})
        check("A.decision", c == 201 and dec.get("status") == "ISSUED"
              and dec.get("outcome") == "REMOVAL"
              and dec.get("appeal_deadline") == "2026-10-03T09:00:00.000Z"
              and dec.get("reopen_deadline") is None
              and dec.get("source_hearing_id") is None,
              "-> %s %s" % (c, str(dec)[:200]))
        did = dec.get("id")
        c, b = call("GET", "/eoir/cases/%s" % cid, headers=ADMIN)
        check("A.case.decided", b["data"]["status"] == "DECIDED"
              and b["data"]["version"] == 6, "-> %s" % b["data"]["status"])
        # appeal within window
        c, b = jcreate(("appeals", {"decision_id": did, "grounds": "g"}))
        ap = b.get("data", {})
        check("A.appeal", c == 201 and ap.get("status") == "FILED"
              and ap.get("case_id") == cid, "-> %s" % c)
        aid = ap.get("id")
        c, b = call("GET", "/eoir/decisions/%s" % did, headers=ADMIN)
        check("A.decision.appeal_pending",
              b["data"]["status"] == "APPEAL_PENDING", "-> %s" % c)
        # board affirms -> case COMPLETED
        c, b = call("POST", "/eoir/appeals/%s/decide" % aid, headers=BOARD,
                    body={"ruling": "AFFIRMED"})
        ap = b.get("data", {})
        check("A.appeal.affirm", c == 200 and ap.get("status") == "AFFIRMED"
              and ap.get("decided_by_board_member_id") == "board-1",
              "-> %s" % c)
        c, b = call("GET", "/eoir/cases/%s" % cid, headers=ADMIN)
        check("A.case.completed", b["data"]["status"] == "COMPLETED"
              and b["data"]["completed_at"] is not None, "-> %s" % c)
        # double decide -> 409
        c, b = call("POST", "/eoir/appeals/%s/decide" % aid, headers=BOARD,
                    body={"ruling": "DISMISSED"})
        check("A.appeal.twice", c == 409 and b["data"]["error_id"] ==
              "ERR_APPEAL_ALREADY_DECIDED", "-> %s" % c)

        # ============ B. no-show cascade + reopen on defective notice ======
        courtB = mk_court("C-B")
        judgeB = mk_judge(courtB, "JB")
        mk_interp(courtB, ("spa",))
        caseB = mk_case(courtB, "B-1")
        cidB = caseB["id"]
        assign(cidB, judgeB)
        c, b = schedule(cidB, "MASTER_CALENDAR", "2026-09-04T09:00:00Z", 2)
        hidB = b["data"]["id"]
        # no-show without notice -> ERR_NOTICE_NOT_SERVED
        set_clock("2026-09-04T09:00:00Z")
        c, b = call("POST", "/eoir/hearings/%s/record-no-show" % hidB,
                    headers=jhdr(judgeB))
        check("B.noshow.nonotice", c == 409 and b["data"]["error_id"] ==
              "ERR_NOTICE_NOT_SERVED", "-> %s" % c)
        jcreate(("notices", {"hearing_id": hidB,
                             "service_method": "PERSONAL_SERVICE",
                             "served_at": "2026-09-03T00:00:00Z"}))
        c, b = call("POST", "/eoir/hearings/%s/record-no-show" % hidB,
                    headers=jhdr(judgeB))
        check("B.noshow", c == 200 and b["data"]["status"] == "NO_SHOW",
              "-> %s" % c)
        c, b = call("GET", "/eoir/cases/%s" % cidB, headers=ADMIN)
        check("B.case.in_absentia",
              b["data"]["status"] == "IN_ABSENTIA"
              and b["data"]["assigned_judge_id"] == judgeB, "-> %s" % c)
        c, b = call("GET", "/eoir/decisions?case_id=%s" % cidB, headers=ADMIN)
        decs = b["data"]
        check("B.decision.auto", len(decs) == 1
              and decs[0]["outcome"] == "IN_ABSENTIA_REMOVAL"
              and decs[0]["source_hearing_id"] == hidB
              and decs[0]["reopen_deadline"] == "2027-03-03T09:00:00.000Z"
              and decs[0]["status"] == "ISSUED", "-> %s" % str(decs)[:200])
        didB = decs[0]["id"]
        # motion NOTICE_DEFECTIVE while notice SERVED -> ERR_NOTICE_NOT_DEFECTIVE
        c, b = jcreate(("motions-to-reopen",
                        {"case_id": cidB, "decision_id": didB,
                         "basis": "NOTICE_DEFECTIVE"}))
        check("B.motion.notdefective", c == 409 and b["data"]["error_id"] ==
              "ERR_NOTICE_NOT_DEFECTIVE", "-> %s" % c)
        # mark the notice defective, then file again
        c, b = call("GET", "/eoir/hearings/%s/notices" % hidB, headers=ADMIN)
        nid = b["data"][0]["id"]
        c, b = call("POST", "/eoir/notices/%s/mark-defective" % nid,
                    headers=ADMIN)
        check("B.notice.defective", c == 200
              and b["data"]["status"] == "DEFECTIVE", "-> %s" % c)
        # notice-defective motion is window-exempt: jump past reopen_deadline
        set_clock("2027-04-01T00:00:00Z")
        c, b = jcreate(("motions-to-reopen",
                        {"case_id": cidB, "decision_id": didB,
                         "basis": "NOTICE_DEFECTIVE"}))
        mot = b.get("data", {})
        check("B.motion.filed", c == 201 and mot.get("status") == "FILED",
              "-> %s %s" % (c, str(mot)[:160]))
        midB = mot.get("id")
        # duplicate FILED motion -> 409
        c, b = jcreate(("motions-to-reopen",
                        {"case_id": cidB, "decision_id": didB,
                         "basis": "NOTICE_DEFECTIVE"}))
        check("B.motion.dup", c == 409 and b["data"]["error_id"] ==
              "ERR_MOTION_ALREADY_PENDING", "-> %s" % c)
        # grant -> CALENDAR + auto master hearing at clock + 21d
        c, b = call("POST", "/eoir/motions-to-reopen/%s/decide" % midB,
                    headers=jhdr(judgeB), body={"decision": "GRANTED"})
        check("B.motion.grant", c == 200 and b["data"]["status"] == "GRANTED",
              "-> %s" % c)
        c, b = call("GET", "/eoir/cases/%s" % cidB, headers=ADMIN)
        check("B.case.recalendared", b["data"]["status"] == "CALENDAR",
              "-> %s" % b["data"]["status"])
        c, b = call("GET", "/eoir/decisions/%s" % didB, headers=ADMIN)
        check("B.decision.rescinded", b["data"]["status"] == "RESCINDED",
              "-> %s" % b["data"]["status"])
        c, b = call("GET", "/eoir/hearings?case_id=%s&status=SCHEDULED" % cidB,
                    headers=ADMIN)
        hs = b["data"]
        check("B.reopen.autohearing", len(hs) == 1
              and hs[0]["auto_created"] is True
              and hs[0]["hearing_type"] == "MASTER_CALENDAR"
              and hs[0]["scheduled_start"] == "2027-04-22T00:00:00.000Z",
              "-> %s" % str(hs)[:240])

        # ============ C. continuance grant: +28d bump for NON_DETAINED =====
        set_clock("2026-09-01T00:00:00Z")
        courtC = mk_court("C-C")
        judgeC = mk_judge(courtC, "JC")
        mk_interp(courtC, ("spa",))
        caseC = mk_case(courtC, "C-1")
        cidC = caseC["id"]
        assign(cidC, judgeC)
        c, b = schedule(cidC, "MASTER_CALENDAR", "2026-09-10T09:00:00Z", 2)
        hidC = b["data"]["id"]
        # lead time: file at clock 2026-09-01, start 09-10 -> fine
        c, b = jcreate(("continuance-requests",
                        {"case_id": cidC, "hearing_id": hidC,
                         "reason_code": "EVIDENCE_GATHERING"}))
        rq = b.get("data", {})
        check("C.cont.file", c == 201 and rq.get("status") == "PENDING"
              and rq.get("is_first_for_case") is True, "-> %s" % c)
        ridC = rq.get("id")
        # pending blocks no-show
        set_clock("2026-09-10T09:00:00Z")
        jcreate(("notices", {"hearing_id": hidC, "service_method": "MAIL",
                             "served_at": "2026-09-01T00:00:00Z"}))
        c, b = call("POST", "/eoir/hearings/%s/record-no-show" % hidC,
                    headers=jhdr(judgeC))
        check("C.noshow.blocked", c == 409 and b["data"]["error_id"] ==
              "ERR_CONTINUANCE_PENDING_BLOCKS_NO_SHOW", "-> %s" % c)
        # grant -> CONTINUED + replacement at +28d
        c, b = call("POST", "/eoir/continuance-requests/%s/decide" % ridC,
                    headers=jhdr(judgeC), body={"decision": "GRANTED"})
        check("C.cont.grant", c == 200 and b["data"]["status"] == "GRANTED"
              and b["data"]["decided_by_judge_id"] == judgeC, "-> %s" % c)
        c, b = call("GET", "/eoir/hearings/%s" % hidC, headers=ADMIN)
        check("C.hearing.continued", b["data"]["status"] == "CONTINUED",
              "-> %s" % b["data"]["status"])
        c, b = call("GET",
                    "/eoir/hearings?case_id=%s&status=SCHEDULED" % cidC,
                    headers=ADMIN)
        hs = b["data"]
        check("C.replacement", len(hs) == 1
              and hs[0]["supersedes_hearing_id"] == hidC
              and hs[0]["auto_created"] is True
              and hs[0]["scheduled_start"] == "2026-10-08T09:00:00.000Z",
              "-> %s" % str(hs)[:240])
        # ATTORNEY_REPRESENTATION requires PRO_SE
        c, b = jcreate(("continuance-requests",
                        {"case_id": cidC, "hearing_id": hs[0]["id"],
                         "reason_code": "ATTORNEY_REPRESENTATION"}))
        # caseC is PRO_SE so this passes; use a represented case for the 422
        check("C.cont.atty_prose_ok", c == 201, "-> %s %s" % (c, str(b)[:120]))
        caseC2 = mk_case(courtC, "C-2", rep="COUNSEL_RETAINED")
        assign(caseC2["id"], judgeC)
        c, b = schedule(caseC2["id"], "MASTER_CALENDAR",
                        "2026-09-11T09:00:00Z", 2)
        h2 = b["data"]["id"]
        c, b = jcreate(("continuance-requests",
                        {"case_id": caseC2["id"], "hearing_id": h2,
                         "reason_code": "ATTORNEY_REPRESENTATION"}))
        check("C.cont.atty_422", c == 422 and b["data"]["error_id"] ==
              "ERR_REASON_REQUIRES_PRO_SE", "-> %s" % c)
        # hearing-case mismatch
        c, b = jcreate(("continuance-requests",
                        {"case_id": caseC2["id"], "hearing_id": hs[0]["id"],
                         "reason_code": "OTHER"}))
        check("C.cont.mismatch", c == 409 and b["data"]["error_id"] ==
              "ERR_HEARING_CASE_MISMATCH", "-> %s" % c)

        # ============ D. detained scheduling rules =========================
        set_clock("2026-09-01T00:00:00Z")  # reset so filed_at is the default
        courtD = mk_court("C-D", cap=1)
        judgeD = mk_judge(courtD, "JD")
        mk_interp(courtD, ("spa",))
        caseD = mk_case(courtD, "D-1", custody="DETAINED")
        cidD = caseD["id"]
        assign(cidD, judgeD)
        # is_remote required
        c, b = schedule(cidD, "MASTER_CALENDAR", "2026-09-05T09:00:00Z", 2)
        check("D.remote.required", c == 409 and b["data"]["error_id"] ==
              "ERR_DETAINED_REQUIRES_REMOTE", "-> %s" % c)
        # expedited deadline: master > filed_at + 14d (inclusive boundary)
        c, b = schedule(cidD, "MASTER_CALENDAR", "2026-09-15T00:00:01Z", 2,
                        remote=True)
        check("D.expedited", c == 409 and b["data"]["error_id"] ==
              "ERR_DETAINED_HEARING_PAST_EXPEDITED_DEADLINE", "-> %s" % c)
        # exactly +14d passes
        c, b = schedule(cidD, "MASTER_CALENDAR", "2026-09-15T00:00:00Z", 2,
                        remote=True)
        check("D.expedited.boundary", c == 201, "-> %s %s" % (c, str(b)[:160]))
        hidD = b["data"]["id"]
        # daily capacity cap=1: a second detained hearing same day fails.
        # A second judge avoids the overlap check, and the deadline boundary
        # (filed_at + 14d inclusive, 09-15T00:00) keeps tier 8 quiet.
        caseD2 = mk_case(courtD, "D-2", custody="DETAINED")
        judgeD2 = mk_judge(courtD, "JD2")
        assign(caseD2["id"], judgeD2)
        c, b = schedule(caseD2["id"], "MASTER_CALENDAR",
                        "2026-09-15T00:00:00Z", 2, remote=True)
        check("D.capacity", c == 409 and b["data"]["error_id"] ==
              "ERR_DETAINED_DAILY_CAPACITY_REACHED", "-> %s %s" % (c, str(b)[:160]))
        # detained case: target +60d, priority base 1000 (age 0 at filing)
        c, b = call("GET", "/eoir/cases/%s" % cidD, headers=ADMIN)
        check("D.priority", b["data"]["priority_score"] == 1000
              and b["data"]["target_completion_date"]
              == "2026-10-31T00:00:00.000Z",
              "-> score=%s target=%s" % (b["data"]["priority_score"],
                                         b["data"]["target_completion_date"]))

        # ============ E. venue motion grant resets to FILED ================
        courtE2 = mk_court("C-E2")
        mk_judge(courtE2, "JE2")
        c, b = jcreate(("venue-motions",
                        {"case_id": caseD2["id"],
                         "destination_court_id": courtE2,
                         "reason": "moved"}))
        mot = b.get("data", {})
        check("E.venue.file", c == 201 and mot.get("status") == "PENDING",
              "-> %s" % c)
        midE = mot.get("id")
        c, b = call("POST", "/eoir/venue-motions/%s/decide" % midE,
                    headers=jhdr(judgeD2), body={"decision": "GRANTED"})
        check("E.venue.grant", c == 200, "-> %s" % c)
        c, b = call("GET", "/eoir/cases/%s" % caseD2["id"], headers=ADMIN)
        check("E.case.reset", b["data"]["status"] == "FILED"
              and b["data"]["court_id"] == courtE2
              and b["data"]["assigned_judge_id"] is None, "-> %s" % c)
        # destination == current -> 422
        c, b = jcreate(("venue-motions",
                        {"case_id": caseD2["id"],
                         "destination_court_id": courtE2,
                         "reason": "again"}))
        check("E.venue.same", c == 422 and b["data"]["error_id"] ==
              "ERR_DESTINATION_COURT_IS_CURRENT", "-> %s" % c)

        # ============ F. reassignment selector + backlog flag ==============
        # goal 4 -> critical at ceil(1.0)=1 pending. Fill source, reassign.
        courtF = mk_court("C-F", goal=4)
        courtF2 = mk_court("C-F2", goal=100)
        mk_judge(courtF, "JF")
        caseF = mk_case(courtF, "F-1")
        c, b = call("GET", "/eoir/courts/%s" % courtF, headers=ADMIN)
        check("F.backlog.flag", b["data"]["is_backlog_critical"] is True,
              "-> %s" % b["data"]["is_backlog_critical"])
        c, b = call("GET", "/eoir/cases/%s" % caseF["id"], headers=ADMIN)
        verF = b["data"]["version"]
        c, b = jcreate(("case-reassignments",
                        {"case_id": caseF["id"],
                         "expected_case_version": verF}))
        rec = b.get("data", {})
        # selector: every earlier court with pending < goal is a candidate;
        # C-A (0/100, created first) wins the exact-rational + created_at race
        check("F.reassign", c == 201 and rec.get("from_court_id") == courtF
              and rec.get("to_court_id") == courtA
              and rec.get("reason") == "BACKLOG_REBALANCE"
              and "version" not in rec and "updated_at" not in rec,
              "-> %s %s" % (c, str(rec)[:200]))
        # detained cases cannot be reassigned
        c, b = jcreate(("case-reassignments",
                        {"case_id": cidD, "expected_case_version": 3}))
        check("F.detained", c == 409 and b["data"]["error_id"] ==
              "ERR_DETAINED_NOT_REASSIGNABLE", "-> %s" % c)
        # non-critical source court rejected
        c, b = jcreate(("case-reassignments",
                        {"case_id": caseF["id"],
                         "expected_case_version": 2}))
        check("F.notcritical", c == 409 and b["data"]["error_id"] ==
              "ERR_COURT_NOT_BACKLOG_CRITICAL", "-> %s" % c)

        # ============ G. docket review: pace anchors + lapse ===============
        # Anchor (PRD §3.8): goal 100, 1 completion, clock 2026-10-05 ->
        # 0.0132 under both variants; the same court at 2026-09-10 splits to
        # 0.0145 (calendar) vs 0.0144 (hearing-day).
        set_clock("2026-09-01T00:00:00Z")
        courtG = mk_court("C-G", goal=100)
        judgeG = mk_judge(courtG, "JG")
        mk_interp(courtG, ("spa",))

        def drive_to_decided(number):
            set_clock("2026-09-01T00:00:00Z")
            case = mk_case(courtG, number)
            cid = case["id"]
            assign(cid, judgeG)
            c, b = schedule(cid, "MASTER_CALENDAR", "2026-09-01T09:00:00Z", 2)
            assert c == 201, (number, c, b)
            hid = b["data"]["id"]
            set_clock("2026-09-01T09:00:00Z")
            c, b = call("POST", "/eoir/hearings/%s/complete" % hid,
                        headers=jhdr(judgeG))
            assert c == 200, (number, c, b)
            c, b = schedule(cid, "INDIVIDUAL_MERITS", "2026-09-01T10:00:00Z",
                            4)
            assert c == 201, (number, c, b)
            mid = b["data"]["id"]
            set_clock("2026-09-01T10:00:00Z")
            c, b = call("POST", "/eoir/hearings/%s/complete" % mid,
                        headers=jhdr(judgeG))
            assert c == 200, (number, c, b)
            c, b = call("POST", "/eoir/decisions", headers=jhdr(judgeG),
                        body={"case_id": cid, "outcome": "GRANT_RELIEF",
                              "expected_case_version": 5})
            assert c == 201, (number, c, b)
            return cid, b["data"]["id"]

        set_clock("2026-09-01T00:00:00Z")
        cidG1, didG1 = drive_to_decided("G-1")
        # case G-1 completes NOW via appeal affirm (completed_at 09-01T10:00)
        c, b = jcreate(("appeals", {"decision_id": didG1}))
        aidG1 = b["data"]["id"]
        c, b = call("POST", "/eoir/appeals/%s/decide" % aidG1, headers=BOARD,
                    body={"ruling": "DISMISSED"})
        check("G1.completed", c == 200
              and b["data"]["status"] == "DISMISSED", "-> %s" % c)
        # case G-2 is left DECIDED (issued 09-01T10:00, appeal deadline
        # 2026-10-01T10:00) and must lapse once the clock passes it
        cidG2, didG2 = drive_to_decided("G-2")

        set_clock("2026-10-05T00:00:00Z")
        c, b = call("POST", "/eoir/courts/%s/docket-reviews" % courtG,
                    headers=ADMIN)
        rev = b.get("data", {})
        # snapshot freezes metrics as they stand at run time (pre-lapse):
        # pending = the still-DECIDED case G-2; completions = G-1's = 1
        check("G.review.anchor", c == 201
              and rev.get("run_index") == 1
              and rev.get("cases_finalized_by_lapse") == 1
              and rev.get("pace_ratio_calendar") == 0.0132
              and rev.get("pace_ratio_hearing_day") == 0.0132
              and rev.get("is_on_pace") is False
              and rev.get("pending_case_count") == 1
              and rev.get("completions_ytd") == 1
              and rev.get("representation_rate_pct") == 0.0,
              "-> %s %s" % (c, str(rev)[:300]))
        c, b = call("GET", "/eoir/cases/%s" % cidG2, headers=ADMIN)
        check("G.case.lapsed", b["data"]["status"] == "COMPLETED"
              and b["data"]["completed_at"] == "2026-10-05T00:00:00.000Z",
              "-> %s" % b["data"]["status"])
        c, b = call("GET", "/eoir/decisions/%s" % didG2, headers=ADMIN)
        check("G.decision.final", b["data"]["status"] == "FINAL",
              "-> %s" % b["data"]["status"])
        # second run at the same clock: nothing left to lapse; both
        # completions now count (completed_at <= clock, inclusive)
        c, b = call("POST", "/eoir/courts/%s/docket-reviews" % courtG,
                    headers=ADMIN)
        rev2 = b.get("data", {})
        check("G.review.second", c == 201 and rev2.get("run_index") == 2
              and rev2.get("cases_finalized_by_lapse") == 0
              and rev2.get("completions_ytd") == 2
              and rev2.get("pending_case_count") == 0,
              "-> %s %s" % (c, str(rev2)[:200]))
        # split anchor: 1 completion visible at 2026-09-10 (G-2's completion
        # instant is later), elapsed 252 calendar / 180 hearing days
        set_clock("2026-09-10T00:00:00Z")
        c, b = call("POST", "/eoir/courts/%s/docket-reviews" % courtG,
                    headers=ADMIN)
        rev3 = b.get("data", {})
        check("G.review.split", c == 201
              and rev3.get("pace_ratio_calendar") == 0.0145
              and rev3.get("pace_ratio_hearing_day") == 0.0144,
              "-> %s %s" % (c, str(rev3)[:240]))

        if FAILURES:
            print("VERIFY FAILED: %d check(s): %s"
                  % (len(FAILURES), ", ".join(FAILURES)))
            return 1
        print("VERIFY PASSED")
        return 0
    finally:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        log.close()


if __name__ == "__main__":
    sys.exit(main())
