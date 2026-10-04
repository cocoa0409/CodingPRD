"""Routing selectors (queue_selector + agent_selector)."""

import db
from calculations import cert_standing_at
from clock import now, parse_iso
from errors import ApiError

MAX_ROUTE_DEPTH = 2


def _agent_busy(agent_id):
    for c in db.calls.values():
        if c.get("agent_id") == agent_id and c["status"] in ("ASSIGNED", "ANSWERED"):
            return True
    return False


def _agent_completed_today_count(agent_id, program_code, contract):
    """Count of COMPLETED calls by this agent for program P, today in contract.measurement_tz."""
    n = now()
    # Logical date in contract measurement_tz: naive local wall time. We interpret
    # measurement windows as naive wall time; "today" is the logical clock's UTC date
    # truncated against the same naive wall time convention.
    today_start = n.replace(hour=0, minute=0, second=0, microsecond=0)
    cnt = 0
    for c in db.calls.values():
        if c.get("handled_by_agent_id") != agent_id:
            continue
        if c["program_code"] != program_code:
            continue
        if c["status"] != "COMPLETED":
            continue
        ended = parse_iso(c["ended_at"]) if c.get("ended_at") else None
        if ended is not None and ended >= today_start:
            cnt += 1
    return cnt


def agent_selector(queue, call, contract):
    """Return best agent for queue+call, or None."""
    program = call["program_code"]
    language = call["language_code"]
    n = now()
    candidates = []
    for agent in db.agents.values():
        if agent["employment_status"] != "ACTIVE":
            continue
        if language not in agent.get("languages", []):
            continue
        # Standing certification for program
        standing = False
        for cert in db.certifications.values():
            if cert["agent_id"] != agent["id"]:
                continue
            if cert["program_code"] != program:
                continue
            if cert_standing_at(cert, n):
                standing = True
                break
        if not standing:
            continue
        if _agent_busy(agent["id"]):
            continue
        candidates.append(agent)
    if not candidates:
        return None
    # Deterministic: created_at ASC tie-break; id never consulted.
    candidates.sort(key=lambda a: (_agent_completed_today_count(a["id"], program, contract),
                                   a["created_at"]))
    return candidates[0]


def _queue_candidates(call):
    contract_id = call["contract_id"]
    program = call["program_code"]
    s = call.get("required_specialty")
    out = []
    for q in db.queues.values():
        if q["contract_id"] != contract_id:
            continue
        if q["program_code"] != program:
            continue
        if q["status"] != "OPEN":
            continue
        if s is None:
            if q["queue_type"] != "GENERAL":
                continue
        else:
            if q["queue_type"] != "SPECIALTY" or q.get("specialty_tag") != s:
                continue
        out.append(q)
    return out


def queue_selector(call):
    """Return (queue, agent, assigned_via, route_depth) or raise.

    Raises ERR_NO_ELIGIBLE_QUEUE when no candidate works (including overflow).
    """
    contract = db.contracts.get(call["contract_id"])
    language = call["language_code"]
    candidates = _queue_candidates(call)
    # Filter A: language match
    lang_filtered = [q for q in candidates if q["language_code"] == language]
    lang_filtered.sort(key=lambda q: q["created_at"])
    for q in lang_filtered:
        agent = agent_selector(q, call, contract)
        if agent is not None:
            return q, agent, "PRIMARY", 1
    # Overflow fallback: ignore language filter, but still require OPEN status.
    if call.get("route_depth", 0) + 1 > MAX_ROUTE_DEPTH:
        raise ApiError("ERR_CALL_OVERFLOW_FORBIDDEN", "Routing would exceed MAX_ROUTE_DEPTH", 409)
    candidates_sorted = sorted(candidates, key=lambda q: q["created_at"])
    for parent in candidates_sorted:
        target_id = parent.get("overflow_queue_id")
        if not target_id:
            continue
        target = db.queues.get(target_id)
        if target is None or target["status"] != "OPEN":
            continue
        agent = agent_selector(target, call, contract)
        if agent is not None:
            return target, agent, "OVERFLOW", call.get("route_depth", 0) + 1
    raise ApiError("ERR_NO_ELIGIBLE_QUEUE", "No eligible queue available", 409)
