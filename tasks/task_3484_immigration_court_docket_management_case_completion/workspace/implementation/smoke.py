#!/usr/bin/env python3
# smoke.py — boot the server via start.sh on a DYNAMIC free port, exercise a
# thin slice of the lifecycle, then kill exactly the process it started.
# Exits nonzero on any failure. Uses only the stdlib (no requests).
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
FAILURES = []


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def call(base, method, path, headers=None, body=None):
    url = base + path
    data = None
    hdrs = {"Content-Type": "application/json"}
    if headers:
        hdrs.update(headers)
    if body is not None:
        data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
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
    status = "ok" if cond else "FAIL"
    print("[%s] %s %s" % (status, label, detail))
    if not cond:
        FAILURES.append(label)


def main():
    port = free_port()
    base = "http://127.0.0.1:%d" % port
    log = open(os.path.join(IMPL_DIR, "smoke_server.log"), "w")
    env = dict(os.environ, PORT=str(port))
    proc = subprocess.Popen(["bash", "start.sh"], cwd=IMPL_DIR, env=env,
                            stdout=log, stderr=subprocess.STDOUT,
                            start_new_session=True)
    try:
        # readiness: any HTTP response means the server is up
        ready = False
        deadline = time.time() + 45
        while time.time() < deadline:
            code, _ = call(base, "GET", "/eoir/courts/nope", headers=ADMIN)
            if code is not None:
                ready = True
                break
            time.sleep(0.25)
        if not ready:
            print("[FAIL] server did not respond within 45s")
            return 1

        # 1. clock: default must be exactly 2026-09-01T00:00:00Z; set is 200
        code, body = call(base, "POST", "/eoir/_clock/set_current_utc",
                          headers=ADMIN,
                          body={"to_iso8601": "2026-09-01T00:00:00Z"})
        check("clock.set", code == 200 and body.get("response_type") == "object",
              "-> %s" % code)

        # 2. create court
        code, body = call(base, "POST", "/eoir/courts", headers=ADMIN, body={
            "court_code": "EOIR-TEST-1", "name": "Test Court",
            "city": "Testville", "annual_completion_goal": 100,
            "detained_daily_hearing_capacity": 5})
        court = body.get("data", {})
        check("court.create", code == 201 and court.get("court_code") == "EOIR-TEST-1"
              and court.get("pending_case_count") == 0
              and court.get("is_backlog_critical") is False
              and court.get("version") == 1, "-> %s" % code)
        court_id = court.get("id")

        # 3. create judge
        code, body = call(base, "POST", "/eoir/judges", headers=ADMIN, body={
            "court_id": court_id, "full_name": "Judge Ada",
            "max_pending_cases": 10})
        judge = body.get("data", {})
        check("judge.create", code == 201
              and judge.get("pending_case_load") == 0, "-> %s" % code)
        judge_id = judge.get("id")
        judge_hdrs = {"X-User-ID": judge_id or "", "X-User-Role": "ImmigrationJudge"}

        # 4. create interpreter
        code, body = call(base, "POST", "/eoir/interpreters", headers=ADMIN,
                          body={"court_id": court_id, "full_name": "Interp Ingrid",
                                "language_codes": ["spa", "eng"],
                                "daily_hearing_cap": 4})
        interpreter = body.get("data", {})
        check("interpreter.create", code == 201, "-> %s" % code)

        # 5. file case (default clock 2026-09-01T00:00:00Z)
        code, body = call(base, "POST", "/eoir/cases", headers=ADMIN, body={
            "court_id": court_id, "case_number": "A-001",
            "respondent_full_name": "Respondent Ruiz",
            "custody_status": "NON_DETAINED",
            "primary_language_code": "spa",
            "representation_status": "PRO_SE"})
        case = body.get("data", {})
        check("case.create", code == 201 and case.get("status") == "FILED"
              and case.get("filed_at") == "2026-09-01T00:00:00.000Z"
              and case.get("target_completion_date") == "2027-09-01T00:00:00.000Z"
              and case.get("version") == 1
              and case.get("priority_score") == 0,
              "-> %s %s" % (code, json.dumps(case)[:200]))
        case_id = case.get("id")

        # 6. assign judge (FILED -> CALENDAR, version 2)
        code, body = call(base, "POST",
                          "/eoir/cases/%s/assign-judge" % case_id,
                          headers=ADMIN, body={"judge_id": judge_id})
        case = body.get("data", {})
        check("case.assign_judge", code == 200 and case.get("status") == "CALENDAR"
              and case.get("assigned_judge_id") == judge_id
              and case.get("version") == 2, "-> %s" % code)

        # 7. schedule a master-calendar hearing (OCC version 2 -> version 3)
        code, body = call(base, "POST", "/eoir/hearings", headers=ADMIN, body={
            "case_id": case_id, "hearing_type": "MASTER_CALENDAR",
            "scheduled_start": "2026-09-05T14:00:00Z",
            "expected_case_version": 2})
        hearing = body.get("data", {})
        check("hearing.create", code == 201
              and hearing.get("status") == "SCHEDULED"
              and hearing.get("duration_minutes") == 30
              and hearing.get("scheduled_end") == "2026-09-05T14:30:00.000Z"
              and hearing.get("judge_id") == judge_id
              and hearing.get("interpreter_id") is not None
              and hearing.get("auto_created") is False,
              "-> %s %s" % (code, json.dumps(hearing)[:200]))
        hearing_id = hearing.get("id")

        # 7b. a second hearing while one stands is rejected (tier 9) — use a
        # free slot so judge-conflict/minutes pass and the single-scheduled
        # rule is the one that fires
        code, body = call(base, "POST", "/eoir/hearings", headers=ADMIN, body={
            "case_id": case_id, "hearing_type": "MASTER_CALENDAR",
            "scheduled_start": "2026-09-08T14:00:00Z",
            "expected_case_version": 3})
        err = body.get("data", {})
        check("hearing.one_scheduled", code == 409
              and err.get("error_id") == "ERR_CASE_HAS_SCHEDULED_HEARING",
              "-> %s %s" % (code, err.get("error_id")))

        # 8. set clock to hearing day
        code, _ = call(base, "POST", "/eoir/_clock/set_current_utc",
                       headers=ADMIN,
                       body={"to_iso8601": "2026-09-05T14:00:00Z"})
        check("clock.advance", code == 200, "-> %s" % code)

        # 9. complete the hearing as the hearing judge (case -> MERITS)
        code, body = call(base, "POST",
                          "/eoir/hearings/%s/complete" % hearing_id,
                          headers=judge_hdrs)
        hearing = body.get("data", {})
        check("hearing.complete", code == 200
              and hearing.get("status") == "COMPLETED", "-> %s" % code)

        # 9b. stale OCC is rejected with 412 (all business rules pass: case is
        # MERITS, type matches, slot free, interpreter available, no SCHEDULED
        # hearing standing; only the version is stale)
        code, body = call(base, "POST", "/eoir/hearings", headers=ADMIN, body={
            "case_id": case_id, "hearing_type": "INDIVIDUAL_MERITS",
            "scheduled_start": "2026-09-06T15:00:00Z",
            "expected_case_version": 3})
        err = body.get("data", {})
        check("hearing.stale_occ", code == 412
              and err.get("error_id") == "ERR_STALE_CASE_VERSION",
              "-> %s %s" % (code, err.get("error_id")))

        # 10. read the case back: MERITS, version 4, computed age fields
        code, body = call(base, "GET", "/eoir/cases/%s" % case_id,
                          headers=ADMIN)
        case = body.get("data", {})
        check("case.read_after", code == 200
              and case.get("status") == "MERITS"
              and case.get("version") == 4
              and case.get("days_pending_calendar") == 4
              and case.get("days_pending_court") == 3
              and case.get("is_past_goal") is False,
              "-> %s %s" % (code, json.dumps(case)[:240]))

        # 11. negative auth: ImmigrationJudge with unknown id -> 400
        code, body = call(base, "GET", "/eoir/cases/%s" % case_id,
                          headers={"X-User-ID": "not-a-judge",
                                   "X-User-Role": "ImmigrationJudge"})
        check("auth.unknown_judge", code == 400
              and body.get("data", {}).get("error_id")
              == "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
              "-> %s" % code)

        # 12. negative permission: judge may not create courts -> 403
        code, body = call(base, "POST", "/eoir/courts", headers=judge_hdrs,
                          body={"court_code": "X", "name": "x", "city": "x",
                                "annual_completion_goal": 1,
                                "detained_daily_hearing_capacity": 0})
        check("auth.forbidden", code == 403
              and body.get("data", {}).get("error_id")
              == "ERR_INSUFFICIENT_PERMISSIONS", "-> %s" % code)

        # 13. list pagination envelope
        code, body = call(base, "GET", "/eoir/cases?limit=10&offset=0",
                          headers=ADMIN)
        meta = body.get("meta", {})
        check("list.pagination", code == 200
              and body.get("response_type") == "array"
              and meta.get("limit") == 10 and meta.get("offset") == 0
              and meta.get("total_count") == 1
              and meta.get("has_more") is False, "-> %s" % code)

        if FAILURES:
            print("SMOKE FAILED: %d check(s): %s"
                  % (len(FAILURES), ", ".join(FAILURES)))
            return 1
        print("SMOKE PASSED")
        return 0
    finally:
        # kill exactly the process (group) we started
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
