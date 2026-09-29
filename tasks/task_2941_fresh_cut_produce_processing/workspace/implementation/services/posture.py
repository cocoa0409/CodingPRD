"""Line posture: a pure projection over sanitation events, CAPAs and swabs."""

import db

OPEN_CAPA_STATES = ("OPEN", "IN_PROGRESS", "VERIFICATION_PENDING")


def sanitation_events(line_id):
    return [e for e in db.rows("sanitation_events") if e["line_id"] == line_id]


def corrective_actions(line_id):
    return [a for a in db.rows("corrective_actions") if a["line_id"] == line_id]


def swabs(line_id):
    return [s for s in db.rows("environmental_swabs") if s["line_id"] == line_id]


def latest_sanitation(line_id):
    """Greatest scheduled_for, tie-broken by the greatest sequence_no."""
    best = None
    for event in sanitation_events(line_id):
        key = (db.dt_of(event, "scheduled_for"), event["sequence_no"])
        if best is None or key > (db.dt_of(best, "scheduled_for"), best["sequence_no"]):
            best = event
    return best


def newest_validated(line_id):
    best = None
    for event in sanitation_events(line_id):
        if event["status"] != "VALIDATED":
            continue
        key = (db.dt_of(event, "validated_at"), event["sequence_no"])
        if best is None or key > (db.dt_of(best, "validated_at"), best["sequence_no"]):
            best = event
    return best


def compute_posture(line):
    line_id = line["id"]
    actions = corrective_actions(line_id)
    open_critical = any(
        a["severity"] == "CRITICAL" and a["status"] != "VERIFIED" for a in actions
    )
    open_major = any(
        a["severity"] == "MAJOR" and a["status"] != "VERIFIED" for a in actions
    )
    open_presumptive = any(
        s["result"] == "PRESUMPTIVE_POSITIVE" for s in swabs(line_id)
    )
    if open_critical:
        return "FROZEN"
    if open_major or open_presumptive:
        return "RESTRICTED"
    latest = latest_sanitation(line_id)
    if latest is None:
        return "RESTRICTED"
    if latest["status"] != "VALIDATED":
        return "RESTRICTED"
    return "OPEN"


def open_capa_count(line_id):
    return len(
        [a for a in corrective_actions(line_id) if a["status"] in OPEN_CAPA_STATES]
    )


def recompute(line):
    """Recompute posture and the two derived line counters; touch on any change."""
    posture = compute_posture(line)
    count = open_capa_count(line["id"])
    validated = newest_validated(line["id"])
    last_validated_at = validated["validated_at"] if validated else None
    changed = False
    if line["posture"] != posture:
        line["posture"] = posture
        changed = True
    if line["open_corrective_action_count"] != count:
        line["open_corrective_action_count"] = count
        changed = True
    if line.get("last_validated_sanitation_at") != last_validated_at:
        line["last_validated_sanitation_at"] = last_validated_at
        line["_dt_last_validated_sanitation_at"] = (
            db.dt_of(validated, "validated_at") if validated else None
        )
        changed = True
    if changed:
        db.touch(line)
    return posture
