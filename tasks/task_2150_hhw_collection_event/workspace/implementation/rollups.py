"""Derived-field recomputation, program posture and the cost report.

Every computed field in §1.1 is a pure aggregation over the store, so each
recompute below is idempotent; `apply_if_changed` guarantees that a row's
version only moves when the row genuinely mutates (PRD §2.4).
"""

from decimal import Decimal

import calc
from calc import ZERO, cents, dec, floor_int, q2, q3
from store import apply_if_changed, clock_dt, ordered, store
from validation import parse_iso

RESERVING_STATUSES = ("CONFIRMED", "CHECKED_IN", "UNLOADING")
REJECTED_DISPOSITIONS = (
    "REJECTED_PROHIBITED",
    "REJECTED_OVER_ANNUAL_LIMIT",
    "REJECTED_OVER_EVENT_LIMIT",
    "REFERRED_BUSINESS",
)


# ------------------------------------------------------------------ queries --

def events_of_program(program_id):
    return ordered([e for e in store.events.values() if e["program_id"] == program_id])


def sites_of_program(program_id):
    return ordered([s for s in store.sites.values() if s["program_id"] == program_id])


def events_of_site(site_id):
    return ordered([e for e in store.events.values() if e["site_id"] == site_id])


def appointments_of_event(event_id):
    return ordered([a for a in store.appointments.values() if a["event_id"] == event_id])


def appointments_of_resident(resident_id):
    return ordered(
        [a for a in store.appointments.values() if a["resident_id"] == resident_id])


def lines_of_appointment(appointment_id):
    return ordered(
        [l for l in store.dropoff_lines.values() if l["appointment_id"] == appointment_id])


def lines_of_container(container_id):
    return ordered(
        [l for l in store.dropoff_lines.values() if l.get("container_id") == container_id])


def lines_of_event(event_id):
    appt_ids = set(a["id"] for a in store.appointments.values()
                   if a["event_id"] == event_id)
    return ordered(
        [l for l in store.dropoff_lines.values() if l["appointment_id"] in appt_ids])


def lines_of_resident(resident_id):
    appt_ids = set(a["id"] for a in store.appointments.values()
                   if a["resident_id"] == resident_id)
    return ordered(
        [l for l in store.dropoff_lines.values() if l["appointment_id"] in appt_ids])


def containers_of_event(event_id):
    return ordered([c for c in store.containers.values() if c["event_id"] == event_id])


def containers_of_manifest(manifest_id):
    return ordered(
        [c for c in store.containers.values() if c.get("manifest_id") == manifest_id])


def manifests_of_event(event_id):
    return ordered([m for m in store.manifests.values() if m["event_id"] == event_id])


def assignments_of_event(event_id):
    return ordered(
        [la for la in store.lane_assignments.values() if la["event_id"] == event_id])


def assignments_of_staffer(staffer_id):
    return ordered(
        [la for la in store.lane_assignments.values() if la["staffer_id"] == staffer_id])


def containers_of_program(program_id):
    event_ids = set(e["id"] for e in store.events.values()
                    if e["program_id"] == program_id)
    return ordered([c for c in store.containers.values() if c["event_id"] in event_ids])


def manifests_of_program(program_id):
    event_ids = set(e["id"] for e in store.events.values()
                    if e["program_id"] == program_id)
    return ordered([m for m in store.manifests.values() if m["event_id"] in event_ids])


def appointments_of_program(program_id):
    event_ids = set(e["id"] for e in store.events.values()
                    if e["program_id"] == program_id)
    return ordered([a for a in store.appointments.values()
                    if a["event_id"] in event_ids])


def program_of_event(event):
    return store.programs.get(event["program_id"])


def program_of_appointment(appointment):
    event = store.events.get(appointment["event_id"])
    return program_of_event(event) if event else None


def event_of_appointment(appointment):
    return store.events.get(appointment["event_id"])


def resident_of_appointment(appointment):
    return store.residents.get(appointment["resident_id"])


# ---------------------------------------------------------- live aggregates --

def live_reserved_slot_count(event):
    return len([a for a in appointments_of_event(event["id"])
                if a["status"] in RESERVING_STATUSES])


def live_open_lane_count(event):
    lanes = set()
    for la in assignments_of_event(event["id"]):
        if la["status"] == "ACTIVE":
            lanes.add(la["lane_number"])
    return len(lanes)


def live_certified_staff_hours(event):
    total = ZERO
    for la in assignments_of_event(event["id"]):
        if la["status"] != "ACTIVE":
            continue
        staffer = store.staffers.get(la["staffer_id"])
        if staffer is None or staffer["status"] != "ACTIVE":
            continue
        if staffer["hazwoper_expires_on"] < event["event_date"]:
            continue
        total += dec(la["duration_hours"])
    return q2(total)


def live_slot_capacity(event):
    site = store.sites.get(event["site_id"])
    liters = site["secondary_containment_liters"] if site else 0
    return calc.slot_capacity(
        live_open_lane_count(event),
        live_certified_staff_hours(event),
        event["window_duration_hours"],
        liters,
        event["containment_status"],
    )


def live_staffing_cost_cents(event):
    program = program_of_event(event)
    rate = program["staff_hourly_rate_cents"] if program else 0
    return cents(live_certified_staff_hours(event) * dec(rate))


def live_projected_cost_per_participant(event):
    reserved = live_reserved_slot_count(event)
    denominator = reserved if reserved > 0 else 1
    return floor_int(dec(live_staffing_cost_cents(event)) / dec(denominator))


def live_line_count(container):
    return len(lines_of_container(container["id"]))


def accepted_lines_of_container(container_id):
    return [l for l in lines_of_container(container_id) if l["disposition"] == "ACCEPTED"]


def live_container_net_weight(container):
    total = ZERO
    for line in accepted_lines_of_container(container["id"]):
        total += dec(line["net_weight_kg"])
    return q3(total)


def live_container_estimate(container):
    """container_estimate variant — round per line, then sum."""
    total = 0
    for line in accepted_lines_of_container(container["id"]):
        category = store.material_categories.get(line["material_category_id"])
        rate = category["disposal_rate_cents_per_kg"] if category else 0
        total += cents(dec(line["net_weight_kg"]) * dec(rate))
    return total


# ------------------------------------------------------------- recomputation --

def recompute_appointment(appointment):
    if appointment["status"] in RESERVING_STATUSES:
        reserved = dec(appointment["declared_total_kg"])
    else:
        reserved = ZERO
    settled = ZERO
    for line in lines_of_appointment(appointment["id"]):
        if line["disposition"] == "ACCEPTED":
            settled += dec(line["net_weight_kg"])
    apply_if_changed(appointment, reserved_kg=reserved, settled_kg=q3(settled))


def recompute_resident(resident):
    reserved = ZERO
    no_shows = 0
    completed = 0
    for appointment in appointments_of_resident(resident["id"]):
        if appointment["status"] in RESERVING_STATUSES:
            reserved += dec(appointment["declared_total_kg"])
        if appointment["status"] == "NO_SHOW":
            no_shows += 1
        if appointment["status"] == "COMPLETED":
            completed += 1
    settled = ZERO
    for line in lines_of_resident(resident["id"]):
        if line["disposition"] == "ACCEPTED":
            settled += dec(line["net_weight_kg"])
    apply_if_changed(
        resident,
        annual_quantity_reserved_kg=q3(reserved),
        annual_quantity_settled_kg=q3(settled),
        no_show_strike_count=no_shows,
        completed_visit_count=completed,
    )


def recompute_staffer(staffer):
    total = ZERO
    for la in assignments_of_staffer(staffer["id"]):
        if la["status"] == "ACTIVE":
            total += dec(la["duration_hours"])
    apply_if_changed(staffer, assigned_hours=q2(total))


def recompute_container(container):
    apply_if_changed(
        container,
        line_count=live_line_count(container),
        net_weight_kg=live_container_net_weight(container),
        estimated_disposal_cost_cents=live_container_estimate(container),
    )


def recompute_manifest(manifest):
    containers = containers_of_manifest(manifest["id"])
    net = ZERO
    estimate = 0
    for container in containers:
        net += dec(container["net_weight_kg"])
        estimate += container["estimated_disposal_cost_cents"]
    apply_if_changed(
        manifest,
        container_ids=[c["id"] for c in containers],
        net_weight_kg=q3(net),
        estimated_disposal_cost_cents=estimate,
    )


def recompute_event(event):
    accepted = ZERO
    rejected = ZERO
    for line in lines_of_event(event["id"]):
        if line["disposition"] == "ACCEPTED":
            accepted += dec(line["net_weight_kg"])
        elif line["disposition"] in REJECTED_DISPOSITIONS:
            rejected += dec(line["net_weight_kg"])
    reported = ZERO
    for manifest in manifests_of_event(event["id"]):
        if manifest["status"] == "RECEIVED":
            reported += dec(manifest["net_weight_kg"])
    participants = len([a for a in appointments_of_event(event["id"])
                        if a["status"] == "COMPLETED"])
    discrepancies = len([c for c in containers_of_event(event["id"])
                         if c["discrepancy_flag"]])
    apply_if_changed(
        event,
        open_lane_count=live_open_lane_count(event),
        certified_staff_hours=live_certified_staff_hours(event),
        staffing_cost_cents=live_staffing_cost_cents(event),
        slot_capacity=live_slot_capacity(event),
        reserved_slot_count=live_reserved_slot_count(event),
        participant_count=participants,
        accepted_tonnage_kg=q3(accepted),
        rejected_tonnage_kg=q3(rejected),
        tonnage_reported_kg=q3(reported),
        projected_cost_per_participant_cents=live_projected_cost_per_participant(event),
        discrepancy_container_count=discrepancies,
    )


# ------------------------------------------------------------------ posture --

def program_counters(program):
    encumbered = 0
    in_transit = 0
    for container in containers_of_program(program["id"]):
        if container["status"] in ("SEALED", "MANIFESTED"):
            encumbered += container["estimated_disposal_cost_cents"]
        elif container["status"] == "SHIPPED":
            in_transit += container["estimated_disposal_cost_cents"]
    spent = 0
    tonnage = ZERO
    for manifest in manifests_of_program(program["id"]):
        if manifest["status"] == "RECEIVED":
            spent += manifest["invoiced_disposal_cost_cents"]
            tonnage += dec(manifest["net_weight_kg"])
    deficiencies = len([e for e in events_of_program(program["id"])
                        if e["containment_status"] == "DEFICIENT"])
    participants = len([a for a in appointments_of_program(program["id"])
                        if a["status"] == "COMPLETED"])
    return {
        "budget_encumbered_cents": encumbered,
        "budget_in_transit_cents": in_transit,
        "budget_spent_cents": spent,
        "open_containment_deficiency_count": deficiencies,
        "participant_count_ytd": participants,
        "tonnage_ytd_kg": q3(tonnage),
    }


def raw_posture(program, counters=None):
    counters = counters or program_counters(program)
    committed = (counters["budget_encumbered_cents"]
                 + counters["budget_in_transit_cents"]
                 + counters["budget_spent_cents"])
    if committed >= program["budget_cents"]:
        return "FROZEN"
    if counters["open_containment_deficiency_count"] >= calc.DEFICIENCY_FREEZE_COUNT:
        return "FROZEN"
    if committed * 100 >= program["budget_cents"] * calc.RESTRICT_UTILIZATION_PCT:
        return "RESTRICTED"
    ceiling = program["cost_per_participant_ceiling_cents"]
    for event in events_of_program(program["id"]):
        if event["lifecycle_status"] != "OPEN_FOR_REGISTRATION":
            continue
        if live_projected_cost_per_participant(event) > ceiling:
            return "RESTRICTED"
    return "OPEN"


def effective_posture(program, counters=None):
    """The posture the gates read (PRD §2.8), computed live."""
    posture = raw_posture(program, counters)
    if program.get("posture_override") == "OPEN" and posture != "FROZEN":
        expires = program.get("posture_override_expires_utc")
        if expires:
            try:
                expires_dt = parse_iso(expires, "posture_override_expires_utc")
            except Exception:
                expires_dt = None
            if expires_dt is not None and clock_dt() < expires_dt:
                return "OPEN"
    return posture


_ALERT_TRANSITIONS = {
    ("OPEN", "RESTRICTED"),
    ("OPEN", "FROZEN"),
    ("RESTRICTED", "FROZEN"),
}


def finalize_program(program):
    counters = program_counters(program)
    posture = effective_posture(program, counters)
    previous = program.get("posture", "OPEN")
    alert_count = program.get("budget_alert_count", 0)
    if (previous, posture) in _ALERT_TRANSITIONS:
        alert_count += 1
    fields = dict(counters)
    fields["posture"] = posture
    fields["budget_alert_count"] = alert_count
    apply_if_changed(program, **fields)


def refresh_world():
    """Settle every rollup before the response is rendered (PRD §2.10)."""
    for appointment in list(store.appointments.values()):
        recompute_appointment(appointment)
    for container in list(store.containers.values()):
        recompute_container(container)
    for manifest in list(store.manifests.values()):
        recompute_manifest(manifest)
    for event in list(store.events.values()):
        recompute_event(event)
    for resident in list(store.residents.values()):
        recompute_resident(resident)
    for staffer in list(store.staffers.values()):
        recompute_staffer(staffer)
    for program in list(store.programs.values()):
        finalize_program(program)


# -------------------------------------------- calculations.program_cost_rollup

def cost_summary(program):
    received = [m for m in manifests_of_program(program["id"])
                if m["status"] == "RECEIVED"]
    disposal_subtotal_cents = sum(m["invoiced_disposal_cost_cents"] for m in received)
    received_tonnage = ZERO
    for manifest in received:
        received_tonnage += dec(manifest["net_weight_kg"])
    received_tonnage = q3(received_tonnage)

    mobilization, rebate_pct = calc.volume_tier(received_tonnage)
    mobilization_fee_cents = mobilization if received else 0
    volume_rebate_cents = floor_int(dec(disposal_subtotal_cents) * rebate_pct)

    staffing_cost_cents = 0
    accepted = ZERO
    rejected = ZERO
    events = events_of_program(program["id"])
    for event in events:
        if event["lifecycle_status"] != "CANCELLED":
            staffing_cost_cents += event["staffing_cost_cents"]
        accepted += dec(event["accepted_tonnage_kg"])
        rejected += dec(event["rejected_tonnage_kg"])

    pre_contingency_cents = (disposal_subtotal_cents + mobilization_fee_cents
                             + staffing_cost_cents - volume_rebate_cents)
    contingency_cents = cents(dec(pre_contingency_cents) * calc.CONTINGENCY_PCT)
    total_program_cost_cents = pre_contingency_cents + contingency_cents

    participant_count = len([a for a in appointments_of_program(program["id"])
                             if a["status"] == "COMPLETED"])
    if participant_count > 0:
        cost_per_participant_cents = floor_int(
            dec(total_program_cost_cents) / dec(participant_count))
    else:
        cost_per_participant_cents = 0

    return {
        "event_count": len(events),
        "participant_count": participant_count,
        "accepted_tonnage_kg": calc.num(q3(accepted)),
        "rejected_tonnage_kg": calc.num(q3(rejected)),
        "received_tonnage_kg": calc.num(received_tonnage),
        "disposal_subtotal_cents": disposal_subtotal_cents,
        "mobilization_fee_cents": mobilization_fee_cents,
        "volume_rebate_cents": volume_rebate_cents,
        "staffing_cost_cents": staffing_cost_cents,
        "pre_contingency_cents": pre_contingency_cents,
        "contingency_cents": contingency_cents,
        "total_program_cost_cents": total_program_cost_cents,
        "cost_per_participant_cents": cost_per_participant_cents,
    }


# -------------------------------------- calculations.disposal_cost_valuation --

def manifest_invoice(manifest):
    """manifest_invoice variant — sum exactly, blend, then round once."""
    containers = containers_of_manifest(manifest["id"])
    net = ZERO
    for container in containers:
        net += dec(container["net_weight_kg"])
    net = q3(net)
    weighted = ZERO
    for container in containers:
        for line in accepted_lines_of_container(container["id"]):
            category = store.material_categories.get(line["material_category_id"])
            rate = category["disposal_rate_cents_per_kg"] if category else 0
            weighted += dec(line["net_weight_kg"]) * dec(rate)
    if net > ZERO:
        blended = calc.q4(weighted / net)
    else:
        blended = Decimal("0")
    invoiced = cents(net * blended)
    return net, blended, invoiced
