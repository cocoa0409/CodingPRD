"""Call sessions — live intervals, disclaimers, recordings and amendments
(PRD 2.6, 3.3)."""

import core
import db
import middleware
import response
import serializers
from decorators import requires
from errors import ApiError

READ_ROLES = ("PlatformAdmin", "ComplianceOfficer", "Coach", "LicensedAgent", "Any")


def _live_interval_conflict(agent_id, started_at, scheduled_end_at, exclude_id=None):
    """The agent's live-call interval must not overlap another live-call interval
    of the same agent; touching endpoints do not overlap."""
    for session in core.agent_sessions(agent_id):
        if session["id"] == exclude_id:
            continue
        if session["status"] != "IN_PROGRESS":
            continue
        if started_at < session["scheduled_end_at"] and session["started_at"] < scheduled_end_at:
            return True
    return False


def _live_interval_contains_clock(agent_id, exclude_id=None):
    """Connect precondition: no other IN_PROGRESS call of this agent whose
    [started_at, scheduled_end_at) contains the logical clock."""
    clock = db.now()
    for session in core.agent_sessions(agent_id):
        if session["id"] == exclude_id or session["status"] != "IN_PROGRESS":
            continue
        if session["started_at"] <= clock < session["scheduled_end_at"]:
            return True
    return False


def _live_call_limit(agent_id, agency):
    live = [row for row in core.agent_sessions(agent_id) if row["status"] == "IN_PROGRESS"]
    return len(live) >= agency["max_live_calls_per_agent"]


def _disclaimer_obligations(session, scope):
    """Waived only when the attached scope's capture_channel is WRITTEN."""
    if scope is not None and scope.get("capture_channel") == "WRITTEN":
        return
    has_recording = session.get("recording_id") not in (None, "")
    if session.get("disclaimer_delivered") is not True or not has_recording:
        raise ApiError("ERR_DISCLAIMER_NOT_DELIVERED",
                       "The recording and CMS disclaimer obligations must both be satisfied.")


def _recording_obligation(session, scope):
    if scope is not None and scope.get("capture_channel") == "WRITTEN":
        return
    if session.get("recording_id") in (None, ""):
        raise ApiError("ERR_RECORDING_MISSING",
                       "A recording is required unless the scope was captured in writing.")


def register(app):
    @app.post("/call-sessions")
    @requires("LicensedAgent")
    def open_session():
        payload = middleware.body()
        agent = middleware.resolve("Agent", middleware.require_field(payload, "agent_id"))
        member = middleware.resolve("Member", middleware.require_field(payload, "member_id"))
        scope = middleware.resolve("ScopeOfAppointment",
                                   middleware.require_field(payload, "scope_of_appointment_id"))
        agency = db.agencies.get(member["agency_id"])
        middleware.gate_posture(agency)
        middleware.owner_check("LicensedAgent", middleware.current_user_id(), agent["id"])

        started_at = middleware.as_instant(middleware.require_field(payload, "started_at"), "started_at")
        scheduled_end_at = middleware.as_instant(
            middleware.require_field(payload, "scheduled_end_at"), "scheduled_end_at")

        if _live_interval_conflict(agent["id"], started_at, scheduled_end_at):
            raise ApiError("ERR_AGENT_HAS_ACTIVE_CALL",
                           "The requested interval overlaps another live call of this agent.")
        # The max_live_calls_per_agent cap counts *live* intervals, so it is
        # enforced where a call becomes live (connect), not when a RINGING call
        # is merely opened.
        core.require_scope_usable(scope, agent["id"])

        row = {
            "id": db.new_id(),
            "_seq": db.next_seq(),
            "created_at": db.now(),
            "updated_at": db.now(),
            "version": 1,
            "agent_id": agent["id"],
            "member_id": member["id"],
            "agency_id": member["agency_id"],
            "scope_of_appointment_id": scope["id"],
            "started_at": started_at,
            "scheduled_end_at": scheduled_end_at,
            "actual_end_at": None,
            "recording_id": middleware.optional(payload, "recording_id"),
            "disclaimer_script_code": middleware.optional(payload, "disclaimer_script_code"),
            "disclaimer_delivered": middleware.optional(payload, "disclaimer_delivered", False),
            "marketing_rule_set_version": middleware.optional(payload, "marketing_rule_set_version"),
            "status": "RINGING",
        }
        db.call_sessions[row["id"]] = row
        core.recompute_agent_counts(agent)
        return response.ok(serializers.serialize("CallSession", row), status=201)

    @app.get("/call-sessions")
    @requires(*READ_ROLES)
    def list_sessions():
        rows = list(db.call_sessions.values())
        for arg, field in (("agent_id", "agent_id"), ("member_id", "member_id"),
                           ("scope_of_appointment_id", "scope_of_appointment_id"),
                           ("status", "status")):
            value = middleware.text_arg(arg)
            if value is not None:
                rows = [row for row in rows if row[field] == value]
        recording_status = middleware.text_arg("recording_status")
        if recording_status is not None:
            rows = [row for row in rows if core.recording_status(row) == recording_status]
        page, limit, offset, total = middleware.paginate(rows, middleware.by_creation)
        return response.ok_list(serializers.listing("CallSession", page), limit, offset, total)

    @app.get("/call-sessions/<session_id>")
    @requires(*READ_ROLES)
    def get_session(session_id):
        session = middleware.resolve("CallSession", session_id)
        return response.ok(serializers.serialize("CallSession", session))

    @app.post("/call-sessions/<session_id>/connect")
    @requires("LicensedAgent")
    def connect_session(session_id):
        session = middleware.resolve("CallSession", session_id)
        payload = middleware.body()
        agent = middleware.resolve("Agent", session["agent_id"])
        scope = db.scopes.get(session["scope_of_appointment_id"])
        agency = db.agencies.get(session["agency_id"])

        # PRD §2.13 fixes the order: the agency posture gate is evaluated first
        # among business-safety checks (a FROZEN agency is reported before the
        # more specific reason a request is also invalid), then the scope gate,
        # then the temporal disclaimer obligation, then the live-call overlap
        # rule, and only last the state-machine legality of the agent (a
        # ERR_*_NOT_* code at priority 16).
        middleware.gate_posture(agency)
        core.require_scope_usable(scope, agent["id"], payload.get("plan_type_discussed"))

        if payload.get("recording_id") is not None:
            session["recording_id"] = payload["recording_id"]
        if payload.get("disclaimer_script_code") is not None:
            session["disclaimer_script_code"] = payload["disclaimer_script_code"]
        if payload.get("marketing_rule_set_version") is not None:
            session["marketing_rule_set_version"] = payload["marketing_rule_set_version"]
        session["disclaimer_delivered"] = middleware.optional(payload, "disclaimer_delivered", False)
        _disclaimer_obligations(session, scope)

        if _live_interval_contains_clock(agent["id"], exclude_id=session["id"]):
            raise ApiError("ERR_AGENT_HAS_ACTIVE_CALL",
                           "The logical clock falls inside another live call of this agent.")
        if _live_call_limit(agent["id"], agency):
            raise ApiError("ERR_LIVE_CALL_LIMIT_EXCEEDED",
                           "The agent already holds the maximum number of live calls.")
        if agent["status"] != "ACTIVE":
            raise ApiError("ERR_AGENT_NOT_ACTIVE", "The agent is not ACTIVE.")

        session["status"] = "IN_PROGRESS"
        core.touch(session)
        core.recompute_agent_counts(agent)
        return response.ok(serializers.serialize("CallSession", session))

    @app.post("/call-sessions/<session_id>/complete")
    @requires("LicensedAgent")
    def complete_session(session_id):
        session = middleware.resolve("CallSession", session_id)
        payload = middleware.body()
        agent = middleware.resolve("Agent", session["agent_id"])
        scope = db.scopes.get(session["scope_of_appointment_id"])
        member = db.members.get(session["member_id"])

        if session["status"] != "IN_PROGRESS":
            raise ApiError("ERR_CALL_NOT_IN_PROGRESS", "The call is not IN_PROGRESS.")
        if payload.get("recording_id") is not None:
            session["recording_id"] = payload["recording_id"]
        if payload.get("disclaimer_delivered") is not None:
            session["disclaimer_delivered"] = middleware.as_bool(
                payload["disclaimer_delivered"], "disclaimer_delivered")
        _disclaimer_obligations(session, scope)
        _recording_obligation(session, scope)
        if member is None or member["agency_id"] != agent["agency_id"]:
            raise ApiError("ERR_MEMBER_NOT_IN_AGENCY",
                           "The member does not belong to the agent's agency.")

        session["status"] = "COMPLETED"
        session["actual_end_at"] = db.now()
        core.touch(session)
        core.recompute_agent_counts(agent)
        core.recompute_substantiated_rate(db.agencies.get(agent["agency_id"]))
        core.recompute_posture(db.agencies.get(agent["agency_id"]))
        core.recompute_risk_score(agent)
        return response.ok(serializers.serialize("CallSession", session))

    @app.post("/call-sessions/<session_id>/drop")
    @requires("LicensedAgent", "PlatformAdmin")
    def drop_session(session_id):
        session = middleware.resolve("CallSession", session_id)
        if session["status"] not in ("RINGING", "IN_PROGRESS"):
            raise ApiError("ERR_CALL_NOT_DROPPABLE", "The call cannot be dropped from this status.")
        was_live = session["status"] == "IN_PROGRESS"
        session["status"] = "DROPPED"
        session["actual_end_at"] = db.now()
        core.touch(session)
        agent = db.agents.get(session["agent_id"])
        agency = db.agencies.get(session["agency_id"])
        core.recompute_agent_counts(agent)
        # PRD §3.10: the score is recomputed on call completion and call drop.
        core.recompute_risk_score(agent)
        if was_live:
            core.recompute_substantiated_rate(agency)
            core.recompute_posture(agency)
        return response.ok(serializers.serialize("CallSession", session))

    @app.post("/call-sessions/<session_id>/amend")
    @requires("ComplianceOfficer")
    def amend_session(session_id):
        session = middleware.resolve("CallSession", session_id)
        payload = middleware.body()
        reason = payload.get("amendment_reason")
        if not isinstance(reason, str) or not reason.strip():
            raise ApiError("ERR_INVALID_REQUEST", "amendment_reason must be a non-empty string.")
        if session["status"] != "COMPLETED":
            raise ApiError("ERR_CALL_NOT_COMPLETED", "Amendment requires a COMPLETED call.")
        agency = db.agencies.get(session["agency_id"])
        middleware.gate_posture(agency)
        session["status"] = "AMENDED"
        core.touch(session)
        return response.ok(serializers.serialize("CallSession", session))

    @app.post("/call-sessions/<session_id>/finalize-amendment")
    @requires("LicensedAgent")
    def finalize_amendment(session_id):
        session = middleware.resolve("CallSession", session_id)
        payload = middleware.body()
        if session["status"] != "AMENDED":
            raise ApiError("ERR_CALL_NOT_AMENDED", "The call is not AMENDED.")
        if payload.get("recording_id") is not None:
            session["recording_id"] = payload["recording_id"]
        if payload.get("disclaimer_delivered") is not None:
            session["disclaimer_delivered"] = middleware.as_bool(
                payload["disclaimer_delivered"], "disclaimer_delivered")
        if session.get("disclaimer_delivered") is not True:
            raise ApiError("ERR_DISCLAIMER_NOT_DELIVERED", "The disclaimer must have been delivered.")
        if session.get("recording_id") in (None, ""):
            raise ApiError("ERR_RECORDING_MISSING", "A recording is required.")
        session["status"] = "COMPLETED"
        session["actual_end_at"] = db.now()
        core.touch(session)
        agent = db.agents.get(session["agent_id"])
        core.recompute_risk_score(agent)
        return response.ok(serializers.serialize("CallSession", session))

    @app.post("/call-sessions/<session_id>/recordings")
    @requires("LicensedAgent", "PlatformAdmin")
    def attach_recording(session_id):
        session = middleware.resolve("CallSession", session_id)
        payload = middleware.body()
        session["recording_id"] = middleware.require_field(payload, "recording_id", str)
        core.touch(session)
        return response.ok(serializers.serialize("CallSession", session))