"""Business logic: ETA prediction, confidence, quality scoring, replay,
delay-risk assessment, cascades."""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import db
from db import get_clock
from helpers import new_id, rhu, minutes_between

# --- constants (pinned from scaffold) ----------------------------------------

CADENCE_MINUTES = {"TELEMATICS": 15, "TMS": 240, "MANUAL": 1440}

MODES = ("OCEAN", "RAIL", "PARCEL", "TRUCKLOAD")

BASE_CI_HALFWIDTH = {"OCEAN": 720, "RAIL": 360, "PARCEL": 60, "TRUCKLOAD": 120}

TOLERANCE_MINUTES = {"OCEAN": 720, "RAIL": 360, "PARCEL": 30, "TRUCKLOAD": 60}

FREE_TIME_MINUTES = {"OCEAN": 240, "RAIL": 360, "PARCEL": 0, "TRUCKLOAD": 120}
GRACE_MINUTES = 15

ESCALATION_SLA_MINUTES = 240

UNSET_QUALITY_NEUTRAL = Decimal(50)


# --- entity mutation helper ---------------------------------------------------

def touch(entity):
    """Refresh updated_at + bump version. Call on any mutation of a common-fields entity."""
    entity["updated_at"] = get_clock()
    entity["version"] = entity.get("version", 0) + 1


# --- ETA prediction ------------------------------------------------------------

def _non_voided_events(shipment_id):
    """Replay order: event_time ASC, tie-break created_at ASC (never id)."""
    evts = [
        e for e in db.tracking_events.values()
        if e["shipment_id"] == shipment_id and not e["voided"]
    ]
    evts.sort(key=lambda e: (e["event_time"], e["created_at"]))
    return evts


def recompute_eta(shipment):
    """Run eta_prediction + eta_confidence_halfwidth per scaffold §1.3.
    Mutates the shipment in place; caller bumps version / timestamps if needed."""
    events = _non_voided_events(shipment["id"])
    R = minutes_between(shipment["planned_arrival_at"], shipment["planned_departure_at"])

    if not events:
        # SCHEDULED_BASELINE
        shipment["eta_at"] = shipment["planned_arrival_at"]
        shipment["eta_variant"] = "SCHEDULED_BASELINE"
    else:
        # TELEMETRY_BLENDED
        E = max(e["event_time"] for e in events)
        p = (minutes_between(E, shipment["planned_departure_at"]) / R)
        if p < 0:
            p = Decimal(0)
        elif p > 1:
            p = Decimal(1)
        open_delay = Decimal(0)
        for e in events:
            if e["event_type"] == "DELAY_REPORTED":
                open_delay += Decimal(e["delay_minutes"] or 0)
            elif e["event_type"] == "RECOVERED":
                open_delay -= Decimal(e["delay_minutes"] or 0)
        if open_delay < 0:
            open_delay = Decimal(0)
        remaining_minutes = R * (Decimal(1) - p)
        total_delta_minutes = remaining_minutes + open_delay
        # Whole-minute round-half-up on the total delta; fractional seconds discarded.
        whole_minutes = rhu(total_delta_minutes)
        eta_dt = E + timedelta(minutes=whole_minutes)
        shipment["eta_at"] = eta_dt
        shipment["eta_variant"] = "TELEMETRY_BLENDED"

    # Confidence halfwidth — final step only rounding. The quality input is the
    # score as of the last COMPLETED checkpoint (never this run's fresh score);
    # an unscored connection contributes a neutral 50 (PRD §3.5).
    conn = db.connections.get(shipment["connection_id"])
    q = Decimal(UNSET_QUALITY_NEUTRAL)
    if conn is not None and conn.get("ci_quality_input") is not None:
        q = Decimal(conn["ci_quality_input"])
    base = Decimal(BASE_CI_HALFWIDTH[shipment["mode"]])
    half = base * (Decimal(1) + (Decimal(100) - q) / Decimal(100))
    if shipment["data_freshness"] == "STALE":
        half = half * Decimal("1.5")
    shipment["eta_confidence_halfwidth_minutes"] = rhu(half)


# --- Replay: derive tracking_status -------------------------------------------

def derive_tracking_status(shipment):
    """Replay non-voided events in pinned order to derive tracking_status.
    Returns the derived status. Does NOT mutate; caller assigns."""
    events = _non_voided_events(shipment["id"])
    if not events:
        return "BOOKED"
    eff = events[-1]  # latest event in replay order
    t = eff["event_type"]
    if t == "DELIVERED":
        return "DELIVERED"
    if t == "OUT_FOR_DELIVERY":
        return "OUT_FOR_DELIVERY"
    if t == "DELAY_REPORTED":
        return "EXCEPTION"
    if t in ("DEPARTED", "ARRIVED_WAYPOINT", "POSITION_UPDATE", "RECOVERED"):
        # DEPARTED moves BOOKED -> IN_TRANSIT; RECOVERED moves EXCEPTION -> IN_TRANSIT.
        # Waypoints and position updates keep an in-transit state.
        return "IN_TRANSIT"
    return "BOOKED"


def freeze_eta_on_delivered(shipment):
    """On every DELIVERED transition, eta_at is frozen at the delivery event_time."""
    events = _non_voided_events(shipment["id"])
    for e in reversed(events):
        if e["event_type"] == "DELIVERED":
            shipment["eta_at"] = e["event_time"]
            return


# --- Delay-risk assessment -----------------------------------------------------

def delay_risk_assessment(shipment, alerts_created_counter=None):
    """After every ETA recompute. Returns the created ExceptionAlert or None."""
    if shipment["eta_at"] is None:
        return None
    if shipment["tracking_status"] not in ("BOOKED", "IN_TRANSIT", "EXCEPTION", "OUT_FOR_DELIVERY"):
        return None
    delay = minutes_between(shipment["eta_at"], shipment["planned_arrival_at"])
    T = Decimal(TOLERANCE_MINUTES[shipment["mode"]])
    if delay <= T:
        return None
    # No OPEN/ESCALATED/ACKNOWLEDGED DELAY_RISK already on this shipment
    for a in db.alerts.values():
        if (
            a["shipment_id"] == shipment["id"]
            and a["alert_type"] == "DELAY_RISK"
            and a["status"] in ("OPEN", "ESCALATED", "ACKNOWLEDGED")
        ):
            return None
    severity = "HIGH" if delay > 2 * T else "MEDIUM"
    queue = "CS_TIER2" if severity == "HIGH" else "CS_TIER1"
    now = get_clock()
    alert = {
        "id": new_id(),
        "shipment_id": shipment["id"],
        "alert_type": "DELAY_RISK",
        "severity": severity,
        "assigned_queue": queue,
        "status": "OPEN",
        "opened_at": now,
        "resolution": None,
        "resolved_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.alerts[alert["id"]] = alert
    if alerts_created_counter is not None:
        alerts_created_counter[0] += 1
    return alert


# --- Data quality scoring --------------------------------------------------------

def score_connection_epoch(conn, prev_run_at, now):
    """Authoritative epoch-windowed quality score. Mutates conn in place.
    Window W = (max(conn.created_at, prev_run_at), now] over recorded_at."""
    window_start = conn["created_at"]
    if prev_run_at is not None and prev_run_at > window_start:
        window_start = prev_run_at
    heartbeats = [
        h for h in db.heartbeat_records.values()
        if h["connection_id"] == conn["id"]
        and window_start < h["recorded_at"] <= now
    ]
    total = len(heartbeats)
    if total > 0:
        on_time_count = sum(1 for h in heartbeats if h["on_time"])
        timeliness_raw = Decimal(100) * Decimal(on_time_count) / Decimal(total)
        completeness_raw = (
            sum(Decimal(h["payload_completeness_pct"]) for h in heartbeats) / Decimal(total)
        )
    else:
        timeliness_raw = Decimal(0)
        completeness_raw = Decimal(0)
    w_minutes = minutes_between(now, window_start)
    expected_count = int(w_minutes // Decimal(conn["cadence_minutes"])) if w_minutes > 0 else 0
    if expected_count > 0:
        ratio = Decimal(total) / Decimal(expected_count)
        if ratio > 1:
            ratio = Decimal(1)
        cadence_raw = Decimal(100) * ratio
    else:
        cadence_raw = Decimal(0)

    t = rhu(timeliness_raw)
    c = rhu(completeness_raw)
    d = rhu(cadence_raw)
    score = rhu(Decimal("0.40") * Decimal(t) + Decimal("0.35") * Decimal(c) + Decimal("0.25") * Decimal(d))

    conn["data_quality_score"] = score
    conn["health_status"] = (
        "HEALTHY" if score >= 70 else ("DEGRADED" if score >= 40 else "CRITICAL")
    )
    if total == 0:
        conn["missed_heartbeat_streak"] = conn.get("missed_heartbeat_streak", 0) + 1
    else:
        conn["missed_heartbeat_streak"] = 0


def score_connection_instantaneous(conn):
    """Instantaneous score from the LATEST heartbeat only (recorded_at desc,
    tie-break created_at ASC)."""
    heartbeats = [
        h for h in db.heartbeat_records.values() if h["connection_id"] == conn["id"]
    ]
    if not heartbeats:
        return
    # latest by recorded_at, tie-break created_at ASC (i.e., earliest created wins ties)
    heartbeats.sort(key=lambda h: (h["recorded_at"], h["created_at"]))
    # we want the latest recorded_at; on ties, the earliest created_at
    latest_recorded = max(h["recorded_at"] for h in heartbeats)
    candidates = [h for h in heartbeats if h["recorded_at"] == latest_recorded]
    candidates.sort(key=lambda h: h["created_at"])
    latest = candidates[0]
    timeliness_component = 100 if latest["on_time"] else 0
    score = rhu(
        Decimal("0.60") * Decimal(timeliness_component)
        + Decimal("0.40") * Decimal(latest["payload_completeness_pct"])
    )
    conn["instantaneous_quality_score"] = score


# --- Identity match score --------------------------------------------------------

def compute_match_score(shipment, po):
    """Returns a Decimal with two decimal places in [0,1]."""
    score = Decimal(0)
    claim = shipment.get("po_reference_claim") or ""
    if claim != "" and claim == po["po_number"]:
        score += Decimal("0.5")
    if shipment["tracking_reference"] == po["booking_reference"]:
        score += Decimal("0.4")
    if shipment["destination_code"] == po["destination_code"]:
        score += Decimal("0.1")
    return score.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# --- Identity state re-derivation -------------------------------------------------

def rederive_identity_state(shipment):
    """Re-derive shipment.identity_state from its identity links.
    Returns the new state; bumps the shipment version + updated_at if changed."""
    links = [l for l in db.identity_links.values() if l["shipment_id"] == shipment["id"]]
    non_rejected = [l for l in links if l["status"] != "REJECTED"]
    confirmed = [l for l in non_rejected if l["status"] == "CONFIRMED"]
    if confirmed:
        new_state = "MATCHED_CONFIRMED"
    elif non_rejected:
        new_state = "MATCHED_PROVISIONAL"
    else:
        new_state = "UNRESOLVED"
    if shipment["identity_state"] != new_state:
        shipment["identity_state"] = new_state
    return new_state


# --- Facility adherence -------------------------------------------------------------

def recompute_facility_adherence(facility):
    """Recompute appointment_adherence_pct; mutates facility in place."""
    appts = [a for a in db.appointments.values() if a["facility_id"] == facility["id"]]
    completed = [a for a in appts if a["status"] == "COMPLETED"]
    missed = [a for a in appts if a["status"] == "MISSED"]
    denom = len(completed) + len(missed)
    if denom == 0:
        facility["appointment_adherence_pct"] = None
    else:
        adherent_count = sum(1 for a in completed if a["adherent"])
        facility["appointment_adherence_pct"] = rhu(
            Decimal(100) * Decimal(adherent_count) / Decimal(denom)
        )


# --- Suspension / resume cascades ---------------------------------------------------

def suspend_connection(conn, now):
    """ACTIVE -> SUSPENDED, recording suspended_at and running the 3-link cascade."""
    conn["status"] = "SUSPENDED"
    conn["suspended_at"] = now
    for s in db.shipments.values():
        if s["connection_id"] != conn["id"]:
            continue
        if s["tracking_status"] in ("IN_TRANSIT", "EXCEPTION"):
            s["data_freshness"] = "STALE"
            recompute_eta(s)
            delay_risk_assessment(s)
            touch(s)


def resume_connection(conn):
    """SUSPENDED -> ACTIVE; clears suspended_at; restores FRESH on stale shipments."""
    conn["status"] = "ACTIVE"
    conn["suspended_at"] = None
    for s in db.shipments.values():
        if s["connection_id"] != conn["id"]:
            continue
        if s["data_freshness"] == "STALE":
            s["data_freshness"] = "FRESH"
            recompute_eta(s)
            delay_risk_assessment(s)
            touch(s)


# --- Data-share visibility --------------------------------------------------------------

def has_active_grant(shipper_id, grantee_id, scope_needed, now):
    """True iff an ACTIVE grant from shipper_id covers grantee_id at time `now`
    with a sufficient scope. scope_needed: 'ETA_ONLY' or 'FULL_TRACE'.
    ETA_ONLY grant suffices for ETA_ONLY reads; FULL_TRACE needed for events."""
    for g in db.data_share_grants.values():
        if g["shipper_id"] != shipper_id:
            continue
        if g["status"] != "ACTIVE":
            continue
        if g["grantee_id"] != grantee_id:
            continue
        if not (g["effective_from"] <= now <= g["expires_at"]):
            continue
        if scope_needed == "FULL_TRACE" and g["scope"] == "ETA_ONLY":
            continue
        return True
    return False
