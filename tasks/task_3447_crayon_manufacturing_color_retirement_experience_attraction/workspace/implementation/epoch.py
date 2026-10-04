"""The operations epoch checkpoint (PRD section 3.8): six pinned phases."""
from datetime import timedelta

from calculations import (
    recompute_spec, rerun_waterfall, session_bounds, tally_outcome,
)
from constants import ARCHIVE_AFTER_DAYS, ROLE_PLATFORM_ADMIN
from envelope import ok
from store import STORE, fmt_like, parse_dt
from validation import auth, require_role, touch


def _apply_retirement_cascade(color):
    """Retirement: specs containing the color deprecate; their PLANNED runs cancel."""
    for spec in STORE.specs.values():
        if not any(e["color_id"] == color["id"] for e in spec["entries"]):
            continue
        was_active = spec["status"] == "ACTIVE"
        recompute_spec(spec)  # flips to DEPRECATED and bumps version on change
        if was_active and spec["status"] == "DEPRECATED":
            for run in STORE.runs.values():
                if run["assortment_spec_id"] == spec["id"] and run["stage"] == "PLANNED":
                    run["stage"] = "CANCELLED"
                    touch(run)
            rerun_waterfall(spec)


def _tally_campaign(campaign):
    """Compute the outcome and apply it to the subject Color (PRD 3.1)."""
    outcome = tally_outcome(campaign)
    campaign["outcome"] = outcome
    campaign["tallied_at"] = STORE.clock_raw
    campaign["status"] = "TALLYED"
    touch(campaign)
    color = STORE.colors.get(campaign["color_id"])
    if color is None:
        return
    closes_dt = parse_dt(campaign["closes_on"])
    if campaign["kind"] == "INTRODUCTION":
        if color["status"] == "IN_VOTE":
            if outcome == "PASSED":
                color["status"] = "ACTIVE"
                color["introduced_on"] = campaign["closes_on"]
            else:
                color["status"] = "PROPOSED"
            touch(color)
    else:  # RETIREMENT
        if color["status"] == "RETIRE_VOTE":
            if outcome == "PASSED":
                color["status"] = "RETIRED"
                color["retired_on"] = campaign["closes_on"]
                color["archive_after_date"] = fmt_like(
                    closes_dt + timedelta(days=ARCHIVE_AFTER_DAYS),
                    campaign["closes_on"])
                touch(color)
                _apply_retirement_cascade(color)
            else:
                color["status"] = "ACTIVE"
                touch(color)


def _close_session(session):
    """Session closing: CONFIRMED -> NO_SHOW, WAITLISTED -> CANCELLED."""
    for ticket in STORE.tickets.values():
        if ticket["session_id"] != session["id"]:
            continue
        if ticket["status"] == "CONFIRMED":
            ticket["status"] = "NO_SHOW"
            touch(ticket)
        elif ticket["status"] == "WAITLISTED":
            ticket["status"] = "CANCELLED"
            touch(ticket)
    session["status"] = "CLOSED"
    session["booked_units"] = 0
    touch(session)


def run_epoch():
    _, role = auth()
    require_role(role, {ROLE_PLATFORM_ADMIN})
    STORE.epoch_index += 1
    clock = STORE.clock_dt
    campaigns_opened = 0
    campaigns_tallied = 0
    sessions_closed = 0
    allocations_expired = 0
    recalls_contained = 0
    recalls_closed = 0
    colors_archived = 0

    # Phase 1: campaign openings (created_at ASC).
    scheduled = sorted(
        (c for c in STORE.campaigns.values() if c["status"] == "SCHEDULED"),
        key=lambda c: c["_seq"])
    for campaign in scheduled:
        if parse_dt(campaign["opens_on"]) <= clock < parse_dt(campaign["closes_on"]):
            campaign["status"] = "OPEN"
            touch(campaign)
            campaigns_opened += 1

    # Phase 2: campaign tallies, oldest closes_on first (jumped windows included).
    due = [c for c in STORE.campaigns.values()
           if c["status"] in ("SCHEDULED", "OPEN") and parse_dt(c["closes_on"]) <= clock]
    due.sort(key=lambda c: (parse_dt(c["closes_on"]), c["_seq"]))
    for campaign in due:
        _tally_campaign(campaign)
        campaigns_tallied += 1

    # Phase 3: session closings.
    for session in sorted(STORE.sessions.values(), key=lambda s: s["_seq"]):
        if session["status"] != "SCHEDULED":
            continue
        _, end = session_bounds(session)
        if clock >= end:
            _close_session(session)
            sessions_closed += 1

    # Phase 4: allocation expirations (requested_ship_date strictly before clock).
    affected_spec_ids = set()
    for alloc in sorted(STORE.allocations.values(), key=lambda a: a["_seq"]):
        if alloc["status"] == "REQUESTED" and parse_dt(alloc["requested_ship_date"]) < clock:
            alloc["status"] = "EXPIRED"
            touch(alloc)
            affected_spec_ids.add(alloc["assortment_spec_id"])
            allocations_expired += 1
    for spec_id in affected_spec_ids:
        spec = STORE.specs.get(spec_id)
        if spec is not None:
            recompute_spec(spec)
            rerun_waterfall(spec)

    # Phase 5: recall progressions.
    for case in sorted(STORE.recall_cases.values(), key=lambda c: c["_seq"]):
        if case["status"] == "OPEN":
            # The cascade is applied synchronously at case creation.
            case["status"] = "CONTAINED"
            touch(case)
            recalls_contained += 1
    for case in sorted(STORE.recall_cases.values(), key=lambda c: c["_seq"]):
        if case["status"] == "CONTAINED" and parse_dt(case["cooling_until"]) <= clock:
            case["status"] = "CLOSED"
            touch(case)
            recalls_closed += 1

    # Phase 6: color archivals.
    for color in sorted(STORE.colors.values(), key=lambda c: c["_seq"]):
        if color["status"] == "RETIRED" and color["archive_after_date"] is not None \
                and parse_dt(color["archive_after_date"]) <= clock:
            color["status"] = "ARCHIVED"
            touch(color)
            colors_archived += 1

    return ok({
        "epoch_index": STORE.epoch_index,
        "campaigns_opened": campaigns_opened,
        "campaigns_tallied": campaigns_tallied,
        "sessions_closed": sessions_closed,
        "allocations_expired": allocations_expired,
        "recalls_contained": recalls_contained,
        "recalls_closed": recalls_closed,
        "colors_archived": colors_archived,
    })


def register(app):
    app.add_url_rule("/crayon-works/ops/run-epoch", view_func=run_epoch, methods=["POST"])
