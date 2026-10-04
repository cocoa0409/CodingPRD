"""Derived-field reconciliation (PRD sections 2.4, 2.5, 2.7, 2.14, 3.x).

Recomputation counts as a mutation: every write performed here refreshes the
resource's updated_at and increments its version (PRD section 2.5).
"""

from datetime import timedelta

import calculations as calc
import store


# --------------------------------------------------------------------------
# Host capacity basis
# --------------------------------------------------------------------------

def site_rows(host_id):
    return [s for s in store.all_of(store.SITES) if s.get("host_id") == host_id]


def active_site_rows(host_id):
    return [s for s in site_rows(host_id) if s.get("is_active")]


def base_capacity(host_id):
    """Count of active HostParkingSite rows -- the physical basis."""
    return len(active_site_rows(host_id))


def host_window_rows(host_id):
    return [w for w in store.all_of(store.WINDOWS) if w.get("host_id") == host_id]


def active_window(host_id):
    """The single live window: greatest start_date, ties by created_at ASC."""
    instant = store.now()
    candidates = [
        w
        for w in host_window_rows(host_id)
        if w.get("window_status") == "ACTIVE"
        and w.get("start_date") <= instant < w.get("end_date")
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda w: (w.get("start_date"), w.get("created_at")))
    return candidates[-1]


def live_basis(host_id):
    window = active_window(host_id)
    if window is not None:
        return max(0, (window.get("capacity_override") or 0) - (window.get("reserved_sites") or 0))
    return base_capacity(host_id)


def effective_capacity(host):
    if host.get("posture") in ("UNAVAILABLE", "SUSPENDED"):
        return 0
    return live_basis(host["id"])


def stay_count_toward_capacity(stay):
    if stay.get("request_status") == "CONFIRMED":
        return True
    if stay.get("request_status") == "REQUESTED" and (stay.get("request_depth") or 0) <= 1:
        return True
    return False


def host_stay_rows(host_id):
    return [s for s in store.all_of(store.STAYS) if s.get("host_id") == host_id]


def committed_sites_reserved(host_id):
    """Reserved basis: CONFIRMED stays plus first-round REQUESTED requests."""
    return sum(1 for s in host_stay_rows(host_id) if stay_count_toward_capacity(s))


def committed_sites_occupied(host_id):
    """Occupied basis for the public card: CONFIRMED plus CHECKED_IN."""
    return sum(
        1
        for s in host_stay_rows(host_id)
        if s.get("request_status") in calc.ACTIVE_STAY_STATUSES
    )


def latest_checkout_at(host_id):
    instants = [
        s.get("occupancy_end")
        for s in host_stay_rows(host_id)
        if s.get("request_status") in calc.ACTIVE_STAY_STATUSES
    ]
    instants = [i for i in instants if i is not None]
    return max(instants) if instants else None


def seasonal_windows_reserved_sites(host_id):
    return sum(
        (w.get("reserved_sites") or 0)
        for w in host_window_rows(host_id)
        if w.get("window_status") == "ACTIVE"
    )


def electric_site_count(host_id):
    return sum(
        1
        for s in site_rows(host_id)
        if s.get("is_active") and s.get("has_electric")
    )


def patronization_credit_cents(host_id):
    return sum(
        (r.get("host_credit_cents") or 0)
        for r in store.all_of(store.RECORDS)
        if r.get("host_id") == host_id and r.get("verification_status") == "VERIFIED"
    )


def host_rating_average(host_id):
    ratings = [
        r.get("rating")
        for r in store.all_of(store.REVIEWS)
        if r.get("author_kind") == "HOST"
        and r.get("host_id") == host_id
        and r.get("review_status") == "PUBLISHED"
    ]
    return calc.rating_average(ratings)


def derive_posture(host, effective, free):
    if host.get("onboarding_status") in ("SUSPENDED", "REJECTED"):
        return "SUSPENDED"
    if effective < 1:
        return "UNAVAILABLE"
    if free < 1:
        return "LIMITED"
    if free <= calc.limited_band(effective):
        return "LIMITED"
    return "OPEN"


def compute_host_derived(host):
    """The posture ladder (PRD 2.4) and everything that rides along with it.

    effective_capacity is forced to 0 exactly when the derived posture is
    UNAVAILABLE or SUSPENDED, so the ladder is evaluated against the live basis
    and the two values are settled together rather than circularly.
    """
    host_id = host["id"]
    committed = committed_sites_reserved(host_id)
    basis = live_basis(host_id)
    if host.get("onboarding_status") in ("SUSPENDED", "REJECTED"):
        posture = "SUSPENDED"
    elif basis < 1:
        posture = "UNAVAILABLE"
    else:
        free_on_basis = max(0, basis - committed)
        if free_on_basis < 1 or free_on_basis <= calc.limited_band(basis):
            posture = "LIMITED"
        else:
            posture = "OPEN"
    effective = 0 if posture in ("UNAVAILABLE", "SUSPENDED") else basis
    free = max(0, effective - committed)
    return {
        "committed_sites": committed,
        "effective_capacity": effective,
        "free_sites": free,
        "posture": posture,
        "latest_checkout_at": latest_checkout_at(host_id),
        "seasonal_windows_reserved_sites": seasonal_windows_reserved_sites(host_id),
        "electric_site_count": electric_site_count(host_id),
        "total_amenity_count": electric_site_count(host_id),
        "patronization_credit_cents": patronization_credit_cents(host_id),
        "host_rating_average": host_rating_average(host_id),
    }


def recompute_host(host, bump=True):
    host.update(compute_host_derived(host))
    if bump:
        store.stamp(host)
    return host


def recompute_window(window, bump=True):
    window["member_capacity_ceiling"] = max(
        0, (window.get("capacity_override") or 0) - (window.get("reserved_sites") or 0)
    )
    if bump:
        store.stamp(window)
    return window


# --------------------------------------------------------------------------
# Member ledger
# --------------------------------------------------------------------------

def member_incidents(member_id):
    return [i for i in store.all_of(store.INCIDENTS) if i.get("member_id") == member_id]


def member_stay_rows(member_id):
    return [s for s in store.all_of(store.STAYS) if s.get("member_id") == member_id]


def total_stays_completed(member_id):
    return sum(
        1
        for s in member_stay_rows(member_id)
        if s.get("request_status") == "CHECKED_OUT"
    )


def member_has_in_flight(member_id):
    return any(
        s.get("request_status") in calc.IN_FLIGHT_STAY_STATUSES
        for s in member_stay_rows(member_id)
    )


def guests_used_this_year(member_id):
    year = store.now().year
    used = 0
    for stay in member_stay_rows(member_id):
        if stay.get("request_status") != "CHECKED_OUT":
            continue
        departure = stay.get("departure_date")
        if departure is None or departure.year != year:
            continue
        used += max(0, (stay.get("party_size") or 1) - 1)
    return used


def member_rating_average(member_id):
    ratings = [
        r.get("rating")
        for r in store.all_of(store.REVIEWS)
        if r.get("author_kind") == "MEMBER"
        and r.get("author_member_id") == member_id
        and r.get("review_status") == "PUBLISHED"
    ]
    return calc.rating_average(ratings)


def recompute_member(member, bump=True):
    """Recompute the conduct ledger, completion count and guest-pass pool."""
    member_id = member["id"]
    incidents = member_incidents(member_id)
    member["standing_score"] = calc.standing_score(incidents)
    strikes = calc.strike_count(incidents)
    member["strike_count"] = strikes
    member["total_stays_completed"] = total_stays_completed(member_id)
    member["member_rating_average"] = member_rating_average(member_id)
    # Guest-pass pool: frozen while any stay is in flight, else recalculated.
    if not member_has_in_flight(member_id):
        allotment = calc.guest_pass_allotment(member.get("plan_tier"))
        member["guest_passes_remaining"] = max(0, allotment - guests_used_this_year(member_id))
    # Removal edge: automatic, terminal, evaluated on every ledger recompute.
    if (
        strikes >= calc.STRIKE_REMOVAL_THRESHOLD
        and member.get("removal_status") != "REMOVED"
    ):
        member["removal_status"] = "REMOVED"
        member["subscription_status"] = "CANCELLED"
        release_in_flight_reservations(member_id)
        # The ledger row itself is itself recomputed; refresh fresh values.
        member["standing_score"] = calc.standing_score(incidents)
        member["total_stays_completed"] = total_stays_completed(member_id)
    if bump:
        store.stamp(member)
    return member


def release_in_flight_reservations(member_id):
    """Cascade hop 4: decline every countable stay beyond request_depth 1."""
    touched_hosts = set()
    for stay in member_stay_rows(member_id):
        if stay.get("request_status") != "CONFIRMED":
            continue
        if (stay.get("request_depth") or 0) <= 1:
            continue
        stay["request_status"] = "DECLINED"
        store.stamp(stay)
        touched_hosts.add(stay.get("host_id"))
    for host_id in touched_hosts:
        host = store.get(store.HOSTS, host_id)
        if host is not None:
            recompute_host(host)