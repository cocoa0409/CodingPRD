"""Cascades and cross-aggregate side effects.

- remove_assignment: the shared release/bubble-up cascade (manual remove,
  delay cascade, license-revoke cascade, scrub cascade)
- scrub_mission / delay_mission / revoke_cascade / expiry_sweep
- execute_separation: deployment + contract/mission bubble-up

Version discipline (PRD §2.5): a version increments only where a transition
or documented side effect says so; derived-field recomputation only touches
updated_at. Cascade RangeSlot transitions (RELEASED/CONSUMED) and
SeparationEvent status changes carry NO version bump per the scaffold's
empty side_effects lists.
"""
from calc import LIVE_ASSIGNMENT_STATUSES, recompute_commitment
from store import bump, db, new_append_only, now, touch


def contract_live_assignments(contract_id):
    out = []
    for a in db["assignments"].values():
        if a["status"] not in LIVE_ASSIGNMENT_STATUSES:
            continue
        if db["payloads"][a["payload_id"]]["contract_id"] == contract_id:
            out.append(a)
    return out


def remove_assignment(a):
    """Full release/bubble-up side effects of a REMOVED transition:
    assignment +1, mission +1, payload -> REGISTERED (+1), and the contract
    falls MANIFESTED -> SIGNED (+1) when its last live assignment leaves.
    Returns the contract if it made that MANIFESTED -> SIGNED hop, else None.
    """
    a["status"] = "REMOVED"
    bump(a)

    mission = db["missions"][a["mission_id"]]
    recompute_commitment(mission)
    bump(mission)

    payload = db["payloads"][a["payload_id"]]
    if payload["status"] == "MANIFESTED":
        payload["status"] = "REGISTERED"
        bump(payload)

    contract = db["contracts"][payload["contract_id"]]
    transitioned = None
    if contract["status"] == "MANIFESTED" and not contract_live_assignments(
        contract["id"]
    ):
        contract["status"] = "SIGNED"
        bump(contract)
        transitioned = contract
    return transitioned


def scrub_mission(mission):
    """MANIFEST_LOCKED/RANGE_SCHEDULED -> SCRUBBED cascade (PRD §3.7)."""
    if mission["status"] == "RANGE_SCHEDULED":
        for s in db["range_slots"].values():
            if s["mission_id"] == mission["id"] and s["status"] in (
                "RESERVED",
                "CONFIRMED",
            ):
                s["status"] = "RELEASED"
                touch(s)
    stripped = []
    live = [
        a
        for a in db["assignments"].values()
        if a["mission_id"] == mission["id"]
        and a["status"] in LIVE_ASSIGNMENT_STATUSES
    ]
    live.sort(key=lambda a: (a["created_at"], a["_seq"]))
    for a in live:
        c = remove_assignment(a)
        if c is not None and c["id"] not in {x["id"] for x in stripped}:
            stripped.append(c)
    for c in stripped:
        c["rebook_eligible"] = True
        touch(c)
    recompute_commitment(mission)
    mission["status"] = "SCRUBBED"
    bump(mission)


def delay_mission(mission, new_open, new_close, reason_code):
    """calculations.delay_cascade_assessment (PRD §3.7). Returns the DelayEvent."""
    prev_open = mission["window_open_utc"]
    prev_close = mission["window_close_utc"]

    mission["window_open_utc"] = new_open
    mission["window_close_utc"] = new_close
    bump(mission)  # the window replacement itself

    slot_released = False
    if mission["status"] == "RANGE_SCHEDULED":
        slot = next(
            (
                s
                for s in db["range_slots"].values()
                if s["mission_id"] == mission["id"] and s["status"] == "CONFIRMED"
            ),
            None,
        )
        if slot is not None and not (
            slot["window_open_utc"] <= new_open
            and slot["window_close_utc"] >= new_close
        ):
            slot["status"] = "RELEASED"
            touch(slot)
            slot_released = True
            mission["status"] = "MANIFEST_LOCKED"
            bump(mission)  # the RANGE_SCHEDULED -> MANIFEST_LOCKED hop

    removed = 0
    # Sweep contracts in created_at ASC order.
    candidates = []
    for c in db["contracts"].values():
        if c["target_mission_id"] == mission["id"]:
            candidates.append(c)
            continue
        for a in db["assignments"].values():
            if (
                a["mission_id"] == mission["id"]
                and a["status"] in LIVE_ASSIGNMENT_STATUSES
                and db["payloads"][a["payload_id"]]["contract_id"] == c["id"]
            ):
                candidates.append(c)
                break
    candidates.sort(key=lambda c: (c["created_at"], c["_seq"]))

    for c in candidates:
        if c["window_close_utc"] < new_close:
            # impacted: strip this contract's live assignments on THIS mission
            mine = [
                a
                for a in db["assignments"].values()
                if a["mission_id"] == mission["id"]
                and a["status"] in LIVE_ASSIGNMENT_STATUSES
                and db["payloads"][a["payload_id"]]["contract_id"] == c["id"]
            ]
            mine.sort(key=lambda a: (a["created_at"], a["_seq"]))
            for a in mine:
                remove_assignment(a)
                removed += 1
            c["rebook_eligible"] = True
            touch(c)

    recompute_commitment(mission)

    event = new_append_only()
    event.update(
        {
            "mission_id": mission["id"],
            "previous_window_open_utc": prev_open,
            "previous_window_close_utc": prev_close,
            "new_window_open_utc": new_open,
            "new_window_close_utc": new_close,
            "reason_code": reason_code,
            "slot_released": slot_released,
            "assignments_removed_count": removed,
        }
    )
    db["delay_events"][event["id"]] = event
    return event


def revoke_cascade(license_):
    """GRANTED -> REVOKED: only CUSTOMER/PAYLOAD_OPERATOR licenses cascade,
    stripping that customer's live assignments on unlaunched missions."""
    if not (
        license_["subject_type"] == "CUSTOMER"
        and license_["kind"] == "PAYLOAD_OPERATOR"
    ):
        return
    customer_id = license_["customer_id"]
    targets = []
    for a in db["assignments"].values():
        if a["status"] not in LIVE_ASSIGNMENT_STATUSES:
            continue
        payload = db["payloads"][a["payload_id"]]
        if db["contracts"][payload["contract_id"]]["customer_id"] != customer_id:
            continue
        mission = db["missions"][a["mission_id"]]
        if mission["status"] not in (
            "MANIFEST_OPEN",
            "MANIFEST_LOCKED",
            "RANGE_SCHEDULED",
        ):
            continue
        targets.append(a)
    targets.sort(key=lambda a: (a["created_at"], a["_seq"]))
    for a in targets:
        remove_assignment(a)


def expiry_sweep():
    """calculations.expiry_sweep — runs synchronously on every clock move."""
    t = now()
    for c in db["contracts"].values():
        if c["status"] == "SIGNED" and c["window_close_utc"] < t:
            c["status"] = "EXPIRED"
            c["rebook_eligible"] = False
            bump(c)
    for lic in db["licenses"].values():
        if lic["status"] == "GRANTED" and lic["valid_until"] < t:
            lic["status"] = "EXPIRED"
            bump(lic)  # no assignment cascade on expiry


def execute_separation(event):
    """EXECUTED side effects: assignment -> DEPLOYED, payload -> DEPLOYED,
    contract -> FULFILLED when all its payloads deployed, mission -> COMPLETED
    when all its separation events executed."""
    event["status"] = "EXECUTED"
    touch(event)  # SeparationEvent transitions carry no version bump

    assignment = db["assignments"][event["assignment_id"]]
    if assignment["status"] == "INTEGRATED":
        assignment["status"] = "DEPLOYED"
        bump(assignment)

    payload = db["payloads"][assignment["payload_id"]]
    if payload["status"] == "MANIFESTED":
        payload["status"] = "DEPLOYED"
        bump(payload)

    contract = db["contracts"][payload["contract_id"]]
    if contract["status"] == "MANIFESTED":
        all_deployed = all(
            p["status"] == "DEPLOYED"
            for p in db["payloads"].values()
            if p["contract_id"] == contract["id"]
        )
        if all_deployed:
            contract["status"] = "FULFILLED"
            bump(contract)

    mission = db["missions"][event["mission_id"]]
    if mission["status"] == "LAUNCHED":
        all_exec = all(
            e["status"] == "EXECUTED"
            for e in db["separation_events"].values()
            if e["mission_id"] == mission["id"]
        )
        if all_exec:
            mission["status"] = "COMPLETED"
            bump(mission)
