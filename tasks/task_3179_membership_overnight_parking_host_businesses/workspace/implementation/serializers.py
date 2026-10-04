"""JSON serializers for every resource.

Every serialized field is pinned explicitly so that absent optional values come
back as null, pagination fields never leak into a resource body, and the lighter
entities (MemberVehicle, HostReview, ConductDisposition) carry only `id`,
`created_at` and their declared fields.
"""

import calculations as calc
import recompute
from envelope import iso


def host_row(h):
    return {
        "id": h["id"],
        "legal_name": h["legal_name"],
        "category": h["category"],
        "address_line1": h["address_line1"],
        "state_code": h["state_code"],
        "arrival_window_start_hour": h["arrival_window_start_hour"],
        "arrival_window_end_hour": h["arrival_window_end_hour"],
        "self_contained_required": h["self_contained_required"],
        "onboarding_status": h["onboarding_status"],
        "posture": h["posture"],
        "effective_capacity": h["effective_capacity"],
        "committed_sites": h["committed_sites"],
        "free_sites": h["free_sites"],
        "latest_checkout_at": iso(h.get("latest_checkout_at")),
        "seasonal_windows_reserved_sites": h.get("seasonal_windows_reserved_sites", 0),
        "electric_site_count": h.get("electric_site_count", 0),
        "total_amenity_count": h.get("total_amenity_count", 0),
        "patronization_credit_cents": h.get("patronization_credit_cents", 0),
        "host_rating_average": h.get("host_rating_average", 0.00),
        "created_at": iso(h["created_at"]),
        "updated_at": iso(h["updated_at"]),
        "version": h["version"],
    }


def site_row(s):
    return {
        "id": s["id"],
        "host_id": s["host_id"],
        "site_label": s["site_label"],
        "site_class": s["site_class"],
        "max_vehicle_length_feet": s["max_vehicle_length_feet"],
        "has_electric": s["has_electric"],
        "electric_service_code": s["electric_service_code"],
        "blocks_sites": s["blocks_sites"],
        "is_active": s["is_active"],
        "created_at": iso(s["created_at"]),
        "updated_at": iso(s["updated_at"]),
        "version": s["version"],
    }


def member_row(m):
    return {
        "id": m["id"],
        "email": m["email"],
        "full_name": m["full_name"],
        "plan_tier": m["plan_tier"],
        "subscription_status": m["subscription_status"],
        "standing_score": m["standing_score"],
        "strike_count": m["strike_count"],
        "removal_status": m["removal_status"],
        "guest_passes_remaining": m["guest_passes_remaining"],
        "home_state_code": m["home_state_code"],
        "total_stays_completed": m["total_stays_completed"],
        "member_rating_average": m.get("member_rating_average", 0.00),
        "created_at": iso(m["created_at"]),
        "updated_at": iso(m["updated_at"]),
        "version": m["version"],
    }


def vehicle_row(v):
    # MemberVehicle carries only `id` and `created_at` from the common set.
    return {
        "id": v["id"],
        "member_id": v["member_id"],
        "vehicle_class": v["vehicle_class"],
        "length_feet": v["length_feet"],
        "self_contained": v["self_contained"],
        "inspection_state_code": v["inspection_state_code"],
        "inspection_expires_on": iso(v.get("inspection_expires_on")),
        "is_primary": v["is_primary"],
        "created_at": iso(v["created_at"]),
    }


def window_row(w):
    return {
        "id": w["id"],
        "host_id": w["host_id"],
        "kind": w["kind"],
        "label": w["label"],
        "start_date": iso(w["start_date"]),
        "end_date": iso(w["end_date"]),
        "window_status": w["window_status"],
        "capacity_override": w["capacity_override"],
        "reserved_sites": w["reserved_sites"],
        "member_capacity_ceiling": w["member_capacity_ceiling"],
        "created_at": iso(w["created_at"]),
        "updated_at": iso(w["updated_at"]),
        "version": w["version"],
    }


def stay_row(s):
    return {
        "id": s["id"],
        "host_id": s["host_id"],
        "member_id": s["member_id"],
        "vehicle_id": s["vehicle_id"],
        "arrival_date": iso(s["arrival_date"]),
        "nights": s["nights"],
        "departure_date": iso(s["departure_date"]),
        "occupancy_start": iso(s["occupancy_start"]),
        "occupancy_end": iso(s["occupancy_end"]),
        "party_size": s["party_size"],
        "electric_request_code": s["electric_request_code"],
        "request_depth": s["request_depth"],
        "request_status": s["request_status"],
        "count_toward_capacity": recompute.stay_count_toward_capacity(s),
        "same_day_hold": s["same_day_hold"],
        "confirmed_site_id": s.get("confirmed_site_id"),
        "ancillary_charge_cents": s.get("ancillary_charge_cents", 0),
        "cancellation_fee_cents": s.get("cancellation_fee_cents", 0),
        "checked_in_at": iso(s.get("checked_in_at")),
        "checked_out_at": iso(s.get("checked_out_at")),
        "no_show_recorded_at": iso(s.get("no_show_recorded_at")),
        "request_origin": s["request_origin"],
        "created_at": iso(s["created_at"]),
        "updated_at": iso(s["updated_at"]),
        "version": s["version"],
    }


def review_row(r):
    # HostReview carries only `id` and `created_at` from the common set.
    return {
        "id": r["id"],
        "host_id": r.get("host_id"),
        "author_review_id": r.get("author_review_id"),
        "subject_member_id": r.get("subject_member_id"),
        "subject_host_id": r.get("subject_host_id"),
        "author_kind": r["author_kind"],
        "author_member_id": r.get("author_member_id"),
        "rating": r["rating"],
        "public_note": r["public_note"],
        "private_report": r.get("private_report"),
        "review_status": r["review_status"],
        "advance_notice_hours": r.get("advance_notice_hours"),
        "arriving_under_24h_notice": _under_24h(r.get("advance_notice_hours")),
        "counter_review_count": r.get("counter_review_count", 0),
        "created_at": iso(r["created_at"]),
    }


def _under_24h(hours):
    if hours is None or isinstance(hours, bool) or not isinstance(hours, int):
        return False
    return hours < 24


def incident_row(i):
    return {
        "id": i["id"],
        "member_id": i["member_id"],
        "host_id": i["host_id"],
        "severity": i["severity"],
        "origin": i["origin"],
        "incident_status": i["incident_status"],
        "narrative": i.get("narrative"),
        "waived_days_remaining": i.get("waived_days_remaining", 0),
        "created_at": iso(i["created_at"]),
        "updated_at": iso(i["updated_at"]),
        "version": i["version"],
    }


def disposition_row(d):
    # ConductDisposition carries only `id` and `created_at` from the common set.
    return {
        "id": d["id"],
        "incident_id": d["incident_id"],
        "member_id": d["member_id"],
        "requested_decision": d.get("requested_decision"),
        "decided_by_display_name": d["decided_by_display_name"],
        "decision": d["decision"],
        "decided_at": iso(d["decided_at"]),
        "created_at": iso(d["created_at"]),
    }


def record_row(r):
    return {
        "id": r["id"],
        "host_id": r["host_id"],
        "member_id": r["member_id"],
        "stay_request_id": r["stay_request_id"],
        "receipt_cents": r["receipt_cents"],
        "purchase_kind": r["purchase_kind"],
        "verification_code": r["verification_code"],
        "verification_status": r["verification_status"],
        "host_credit_cents": r.get("host_credit_cents", 0),
        "created_at": iso(r["created_at"]),
        "updated_at": iso(r["updated_at"]),
        "version": r["version"],
    }


def capacity_summary(host):
    host_id = host["id"]
    window = recompute.active_window(host_id)
    return {
        "host_id": host_id,
        "capacity_basis": "live" if window is not None else "base",
        "base_capacity": recompute.base_capacity(host_id),
        "effective_capacity": host.get("effective_capacity", 0),
        "committed_sites_reserved_basis": recompute.committed_sites_reserved(host_id),
        "committed_sites_occupied_basis": recompute.committed_sites_occupied(host_id),
        "free_sites": host.get("free_sites", 0),
        "active_window_id": window["id"] if window is not None else None,
        "active_window_member_ceiling": (
            window.get("member_capacity_ceiling") if window is not None else None
        ),
        "latest_checkout_at": iso(recompute.latest_checkout_at(host_id)),
        "posture": host.get("posture"),
    }


def site_availability(host_id, site, from_date, to_date):
    blocked_labels = [
        other.get("site_label")
        for other in store_sites(host_id)
        if site.get("site_label") in _split(other.get("blocks_sites"))
    ]
    intervals = []
    for stay in store_stays(host_id):
        if stay.get("confirmed_site_id") != site["id"]:
            continue
        if stay.get("request_status") not in calc.ACTIVE_STAY_STATUSES:
            continue
        start, end = stay.get("occupancy_start"), stay.get("occupancy_end")
        if from_date is not None and end <= from_date:
            continue
        if to_date is not None and start >= to_date:
            continue
        intervals.append(
            {
                "stay_request_id": stay["id"],
                "start": iso(start),
                "end": iso(end),
                "occupancy_start": iso(start),
                "occupancy_end": iso(end),
            }
        )
    intervals.sort(key=lambda item: item["start"] or "")
    return {
        "site_id": site["id"],
        "host_id": host_id,
        "site_label": site.get("site_label"),
        "occupied_intervals": intervals,
        "blocked_by_site_labels": blocked_labels,
        "is_assignable": site.get("is_active", True) and _assignable(host_id, site),
    }


def _assignable(host_id, site):
    import stay_domain

    instant = store_now()
    probe_start = instant
    probe_end = instant
    return stay_domain.site_blocked(host_id, site, probe_start, probe_end) is None


def _split(raw):
    if not raw:
        return []
    return [part.strip() for part in str(raw).split("|") if part.strip()]


def store_sites(host_id):
    import store

    return [s for s in store.all_of(store.SITES) if s.get("host_id") == host_id]


def store_stays(host_id):
    import store

    return [s for s in store.all_of(store.STAYS) if s.get("host_id") == host_id]


def store_now():
    import store

    return store.now()