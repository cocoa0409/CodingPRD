"""Recomputations, the posture cascade, deferred clock actions and lookups."""

import db
import db as db_helpers
import domain
import shapes
from errors import ApiError

# ---------------------------------------------------------------------------
# scoped collections
# ---------------------------------------------------------------------------

def store_bays(store_id):
    return [b for b in db.rows("bays") if b["store_id"] == store_id]


def store_clinics(store_id):
    return [c for c in db.rows("clinics") if c["store_id"] == store_id]


def store_orders(store_id):
    return [o for o in db.rows("pharmacy_orders") if o["store_id"] == store_id]


def encounter_authorizations(encounter_id):
    return [a for a in db.rows("authorizations") if a["encounter_id"] == encounter_id]


def authorization_orders(authorization_id):
    return [o for o in db.rows("pharmacy_orders")
            if o["authorization_id"] == authorization_id]


def pet_incidents(pet_id):
    return [i for i in db.rows("incidents") if i["pet_id"] == pet_id]


def booking_incidents(booking_id):
    return [i for i in db.rows("incidents") if i["booking_id"] == booking_id]


def package_enrollments(package_id):
    return [e for e in db.rows("enrollments") if e["package_id"] == package_id]


def member_packages(member_id):
    return [p for p in db.rows("packages") if p["member_id"] == member_id]


def package_cycles(package_id):
    return [c for c in db.rows("cycles") if c["package_id"] == package_id]


# ---------------------------------------------------------------------------
# derived counters
# ---------------------------------------------------------------------------

def store_occupancy(store):
    rows = [e for e in db.rows("encounters") if e["store_id"] == store["id"]]
    occupancy = len([e for e in rows if e["status"] in domain.ENCOUNTER_OCCUPANCY_STATES])
    occupied = len([e for e in rows if e["status"] in domain.ENCOUNTER_OCCUPIED_STATES])
    return occupancy, occupied


def recompute_training_slots(store, touch_row=False):
    store["restricted_training_slots_pending"] = len(
        [e for e in db.rows("enrollments")
         if e["store_id"] == store["id"] and e["status"] in ("PENDING_ACK", "RESTRICTED")])
    if touch_row:
        db.touch(store)


def recompute_frozen_clinics(store):
    store["frozen_vaccination_clinics"] = len(
        [c for c in store_clinics(store["id"]) if c["clinic_status"] == "FROZEN"])


def recompute_stores_held(store):
    store["stores_held_total"] = len(
        [o for o in store_orders(store["id"]) if o["on_hold"] == "HOLDING"])


def recompute_cross_sell_balance(store):
    granted = sum(c["credit_granted_cents"] for c in db.rows("cross_sells")
                  if c["store_id"] == store["id"] and c["status"] in ("PENDING", "REDEEMED"))
    redeemed = sum(c["credit_redeemed_cents"] for c in db.rows("cross_sells")
                   if c["store_id"] == store["id"] and c["status"] == "REDEEMED")
    store["cross_sell_credit_balance_cents"] = granted - redeemed


def recompute_incident_risk_index(store):
    store["incident_risk_index"] = sum(
        i["claim_amount_cents"] for i in db.rows("incidents")
        if i["store_id"] == store["id"]
        and i["claim_status"] in ("UNREVIEWED", "UNDER_REVIEW"))


def recompute_pet_risk(pet, touch_row=True):
    pet["risk_score"] = sum(i["risk_points"] for i in pet_incidents(pet["id"])
                            if i["claim_status"] != "DENIED")
    pet["rabies_vaccination_expires_at"] = shapes.live_rabies_expiry(pet)
    if touch_row:
        db.touch(pet)


def recompute_member_balance(member, touch_row=True):
    total = 0
    for pkg in member_packages(member["id"]):
        if pkg["status"] == "CANCELLED":
            continue
        total += pkg["total_price_cents"]
        total -= sum(c["cycle_total_cents"] for c in package_cycles(pkg["id"])
                     if c["status"] == "BILLED")
    member["outstanding_balance_cents"] = domain.json_number(total)
    if touch_row:
        db.touch(member)


# ---------------------------------------------------------------------------
# the posture cascade (PRD §3.3)
# ---------------------------------------------------------------------------

def _block_clinic_visits(clinic):
    """Freezing a clinic blocks its live visits and invalidates their certificates."""
    affected_pets = set()
    for visit in db.rows("visits"):
        if visit["clinic_id"] != clinic["id"]:
            continue
        if visit["status"] in ("REGISTERED", "CERTIFICATE_ISSUED", "REPORT_REQUIRED"):
            if visit["status"] == "REGISTERED" and visit["state_report_status"] == "NOT_REQUIRED":
                pass
            visit["status"] = "BLOCKED"
            if visit["state_report_status"] == "PENDING":
                visit["state_report_status"] = "NOT_REQUIRED"
            db.touch(visit)
            for cert in db.rows("certificates"):
                if cert["visit_id"] == visit["id"]:
                    cert["is_effective"] = False
                    affected_pets.add(cert["pet_id"])
    for pet_id in affected_pets:
        pet = db.get("pets", pet_id)
        if pet:
            recompute_pet_risk(pet)


def apply_bay_freeze(bay):
    """M2 ACTIVE -> FROZEN consequences: cancel what has not begun, close out the rest."""
    for booking in db.rows("bookings"):
        if booking["bay_id"] != bay["id"]:
            continue
        if booking["status"] in ("REQUESTED", "SCREENED", "BAY_CONFIRMED"):
            booking["status"] = "CANCELLED"
            db.touch(booking)
        elif booking["status"] == "IN_SERVICE":
            booking["status"] = "COMPLETED"
            db.touch(booking)
            for enc in db.rows("encounters"):
                if enc["booking_id"] == booking["id"] and enc["status"] in ("SCHEDULED", "CHECKED_IN"):
                    enc["status"] = "CANCELLED"
                    db.touch(enc)
                    for auth in encounter_authorizations(enc["id"]):
                        if auth["status"] in ("PENDING_EXAM", "AUTHORIZED"):
                            auth["status"] = "REVOKED"
                            db.touch(auth)


def _freeze_children(store, deep):
    for bay in store_bays(store["id"]):
        if bay["status"] == "ACTIVE":
            bay["status"] = "FROZEN"
            bay["is_frozen"] = True
            db.touch(bay)
            apply_bay_freeze(bay)
        elif bay["status"] == "FROZEN":
            bay["is_frozen"] = True
    for clinic in store_clinics(store["id"]):
        if deep and clinic["clinic_status"] in ("SCHEDULED", "OPEN"):
            clinic["clinic_status"] = "FROZEN"
            db.touch(clinic)
            _block_clinic_visits(clinic)
        elif not deep and clinic["clinic_status"] == "OPEN":
            # §3.3: the RESTRICTED rung reaches the visits through the clinic.
            clinic["clinic_status"] = "FROZEN"
            db.touch(clinic)
            _block_clinic_visits(clinic)
    if deep:
        for order in store_orders(store["id"]):
            if order["status"] not in ("DISPENSED", "REJECTED"):
                order["on_hold"] = "HOLDING"
        store["pharmacy_hold_until"] = db.now() + db_helpers.timedelta(
            hours=domain.PHARMACY_HOLD_HOURS)


def _thaw_children(store, releasing_freeze):
    for bay in store_bays(store["id"]):
        if bay["status"] == "FROZEN":
            bay["status"] = "ACTIVE"
            bay["is_frozen"] = False
            db.touch(bay)
    for clinic in store_clinics(store["id"]):
        if clinic["clinic_status"] == "FROZEN":
            clinic["clinic_status"] = "SCHEDULED"
            db.touch(clinic)
            affected_pets = set()
            for visit in db.rows("visits"):
                if visit["clinic_id"] != clinic["id"] or visit["status"] != "BLOCKED":
                    continue
                visit["status"] = "REGISTERED"
                db.touch(visit)
                for cert in db.rows("certificates"):
                    if cert["visit_id"] == visit["id"] and cert["expires_at"] >= db.now():
                        cert["is_effective"] = True
                        affected_pets.add(cert["pet_id"])
            for pet_id in affected_pets:
                pet = db.get("pets", pet_id)
                if pet:
                    recompute_pet_risk(pet)
    if releasing_freeze:
        for order in store_orders(store["id"]):
            if order["on_hold"] == "HOLDING":
                order["on_hold"] = "NONE"
                if order["status"] == "AUTHORIZED":
                    order["status"] = "REQUESTED"
        store["pharmacy_hold_until"] = None


def apply_posture(store, target):
    current = store["hospital_posture"]
    if target == current:
        return
    if target == "FROZEN":
        _freeze_children(store, deep=True)
    elif target == "RESTRICTED":
        _freeze_children(store, deep=False)
    elif target == "OPEN":
        _thaw_children(store, releasing_freeze=(current == "FROZEN"))
    store["hospital_posture"] = target


def refresh_store(store, recompute_posture=True):
    """Recompute every derived counter; optionally re-derive the posture ladder."""
    if recompute_posture:
        _, occupied = store_occupancy(store)
        apply_posture(store, domain.posture_next(
            store["hospital_posture"], occupied, store["hospital_capacity"]))
    occupancy, _ = store_occupancy(store)
    store["hospital_occupancy"] = occupancy
    recompute_frozen_clinics(store)
    recompute_stores_held(store)
    recompute_cross_sell_balance(store)
    recompute_incident_risk_index(store)
    recompute_training_slots(store)
    db.touch(store)


# ---------------------------------------------------------------------------
# deferred (scheduled) actions — resolved lazily as the logical clock advances
# ---------------------------------------------------------------------------

def schedule(kind, payload, due=None):
    """Queue a deferred action; `due` defaults to the current logical clock."""
    db.SCHEDULED.append((due if due is not None else db.now(), kind, payload))


def _enrollments_for_booking(booking_id):
    return [e for e in db.rows("enrollments") if e["booking_id"] == booking_id]


def _lapse_screening(booking):
    booking["re_screen_required"] = True
    if booking["status"] == "SCREENED":
        booking["status"] = "REQUESTED"
    elif booking["status"] == "BAY_CONFIRMED":
        # grooming re-enters the screening gate, everything else goes back to the queue
        booking["status"] = "SCREENED" if booking["service_type"] == "GROOMING" else "REQUESTED"
    db.touch(booking)


def _mark_visit_overdue(visit):
    if visit["status"] == "REPORT_REQUIRED" \
            and visit["state_report_status"] in ("PENDING", "OVERDUE"):
        visit["state_report_status"] = "OVERDUE"
        db.touch(visit)


def _revisit_earlier(base):
    """Return the current backlog instant when it precedes `base` (history integrity)."""
    stamps = [v["created_at"] for v in db.rows("visits")]
    stamps += [b["created_at"] for b in db.rows("bookings")]
    if not stamps:
        return base
    return min(base, min(stamps))


def _expire_authorization(auth):
    if auth["status"] == "AUTHORIZED" and auth["expires_at"] and auth["expires_at"] < db.now():
        auth["status"] = "EXPIRED"
        db.touch(auth)


def consume_scheduled(upto):
    pending = sorted(db.SCHEDULED, key=lambda item: item[0])
    db.SCHEDULED.clear()
    for due, kind, payload in pending:
        if due > upto:
            db.SCHEDULED.append((due, kind, payload))
            continue
        if kind == "SCREENING_LAPSE":
            booking = db.get("bookings", payload["booking_id"])
            if booking and booking["status"] in ("SCREENED", "BAY_CONFIRMED") \
                    and booking["screening_valid_until"] and booking["screening_valid_until"] <= upto:
                _lapse_screening(booking)
        elif kind == "REPORT_OVERDUE":
            visit = db.get("visits", payload["visit_id"])
            if visit:
                _mark_visit_overdue(visit)
        elif kind == "AUTH_EXPIRY":
            auth = db.get("authorizations", payload["authorization_id"])
            if auth:
                _expire_authorization(auth)


def sweep_due_actions():
    """Re-evaluate every deadline that the current clock has already crossed.

    The deadline is always the authoritative field on the row, so this sweep is
    idempotent and self-healing whether the clock advanced, was rewound, or the
    queue was cleared.
    """
    db.SCHEDULED.clear()
    for booking in db.rows("bookings"):
        if booking["status"] in domain.TERMINAL_BOOKING_STATES:
            continue
        horizon = booking["screening_valid_until"]
        if horizon is None:
            continue
        if db.now() > horizon:
            if not booking["re_screen_required"]:
                _lapse_screening(booking)
        elif booking["re_screen_required"]:
            booking["re_screen_required"] = False
            db.touch(booking)
    for visit in db.rows("visits"):
        if visit["status"] != "REPORT_REQUIRED" or visit["state_report_due_at"] is None:
            continue
        if db.now() > visit["state_report_due_at"]:
            _mark_visit_overdue(visit)
        elif visit["state_report_status"] == "OVERDUE":
            visit["state_report_status"] = "PENDING"
            db.touch(visit)
    for auth in db.rows("authorizations"):
        if auth["status"] == "EXPIRED":
            if auth["expires_at"] is None or db.now() <= auth["expires_at"]:
                auth["status"] = "AUTHORIZED"
                db.touch(auth)
        elif auth["status"] in ("AUTHORIZED", "PARTIALLY_DISPENSED") \
                and auth["expires_at"] is not None and db.now() > auth["expires_at"]:
            _expire_authorization(auth)
    # M8 REQUESTED -> AUTHORIZED: the authorization-clone release, fired whenever
    # the linked prescription is live and the store is not held.
    for order in db.rows("pharmacy_orders"):
        if order["status"] != "REQUESTED":
            continue
        auth = db.get("authorizations", order["authorization_id"])
        store = db.get("stores", order["store_id"])
        if auth is None or store is None:
            continue
        if auth["status"] not in ("AUTHORIZED", "PARTIALLY_DISPENSED"):
            continue
        hold = store["pharmacy_hold_until"]
        if hold is not None and db.now() <= hold:
            continue
        order["status"] = "AUTHORIZED"
        if store["hospital_posture"] != "FROZEN":
            order["on_hold"] = "NONE"
        db.touch(order)
        recompute_stores_held(store)


def on_clock_moved():
    """Re-evaluate every deadline against the clock's new value."""
    sweep_due_actions()


# ---------------------------------------------------------------------------
# lookups
# ---------------------------------------------------------------------------

def require(table, row_id, error_id):
    row = db.get(table, row_id)
    if row is None:
        raise ApiError(error_id)
    return row


def require_store(store_id):
    return require("stores", store_id, "ERR_STORE_NOT_FOUND")


def require_member(member_id):
    return require("members", member_id, "ERR_MEMBER_NOT_FOUND")


def require_pet(pet_id):
    return require("pets", pet_id, "ERR_PET_NOT_FOUND")


def require_bay(bay_id):
    return require("bays", bay_id, "ERR_SERVICE_BAY_NOT_FOUND")


def require_booking(booking_id):
    return require("bookings", booking_id, "ERR_BOOKING_NOT_FOUND")


def require_encounter(encounter_id):
    return require("encounters", encounter_id, "ERR_ENCOUNTER_NOT_FOUND")


def require_clinic(clinic_id):
    return require("clinics", clinic_id, "ERR_CLINIC_NOT_FOUND")


def require_visit(visit_id):
    return require("visits", visit_id, "ERR_VISIT_NOT_FOUND")


def require_authorization(authorization_id):
    return require("authorizations", authorization_id, "ERR_AUTHORIZATION_NOT_FOUND")


def require_order(order_id):
    return require("pharmacy_orders", order_id, "ERR_PHARMACY_ORDER_NOT_FOUND")


def require_incident(incident_id):
    return require("incidents", incident_id, "ERR_INCIDENT_NOT_FOUND")


def require_package(package_id):
    return require("packages", package_id, "ERR_PACKAGE_NOT_FOUND")


def require_cycle(cycle_id):
    return require("cycles", cycle_id, "ERR_CYCLE_NOT_FOUND")


def require_enrollment(enrollment_id):
    return require("enrollments", enrollment_id, "ERR_ENROLLMENT_NOT_FOUND")


def require_cross_sell(cross_sell_id):
    return require("cross_sells", cross_sell_id, "ERR_CROSS_SELL_NOT_FOUND")


def require_rule(rule_id):
    return require("breed_rules", rule_id, "ERR_BREED_RULE_NOT_FOUND")


def require_certificate(certificate_id):
    return require("certificates", certificate_id, "ERR_CERTIFICATE_SERIAL_DUPLICATE")


def require_screening(screening_id):
    row = db.get("screenings", screening_id)
    if row is None:
        raise ApiError("ERR_INVALID_REQUEST", "No grooming risk screening matches the screeningId.")
    return row


def pet_of_member(member_id, pet_id):
    """A pet named against a member-scoped path must belong to that member."""
    pet = require_pet(pet_id)
    if pet["member_id"] != member_id:
        raise ApiError("ERR_PET_MEMBER_MISMATCH")
    return pet


# ---------------------------------------------------------------------------
# filtering / paging helpers
# ---------------------------------------------------------------------------

def sort_rows(items, key="created_at"):
    return sorted(items, key=lambda r: (r[key], r["id"]))


def page(items, limit, offset):
    ordered = sort_rows(items)
    return ordered[offset:offset + limit], len(ordered)


def matches(row, filters):
    for field, value in filters.items():
        if value in (None, ""):
            continue
        if str(row.get(field)) != str(value):
            return False
    return True


def filtered(table, query, fields):
    rows = db.rows(table)
    filters = {f: query.get(f) for f in fields if query.get(f) not in (None, "")}
    if not filters:
        return rows
    return [r for r in rows if matches(r, filters)]