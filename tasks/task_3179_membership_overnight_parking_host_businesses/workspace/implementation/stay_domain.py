"""Stay-domain helpers: derived instants, collision rules and admission guards."""

from datetime import timedelta

import calculations as calc
import errors
import store

APPROACH_BUFFER = timedelta(hours=2)
LEAD_TIME = timedelta(hours=48)


# --------------------------------------------------------------------------
# Derived instants
# --------------------------------------------------------------------------

def departure_date(arrival, nights):
    """arrival + nights days; the exclusive checkout boundary."""
    return arrival + timedelta(days=nights)


def occupancy_start(arrival, host):
    """arrival_date + host.arrival_window_start_hour."""
    return arrival + timedelta(hours=host.get("arrival_window_start_hour") or 0)


def occupancy_end(departure, host):
    """departure_date + host.arrival_window_end_hour."""
    return departure + timedelta(hours=host.get("arrival_window_end_hour") or 0)


def apply_dates(stay, host, arrival, nights):
    stay["arrival_date"] = arrival
    stay["nights"] = nights
    stay["departure_date"] = departure_date(arrival, nights)
    stay["occupancy_start"] = occupancy_start(arrival, host)
    stay["occupancy_end"] = occupancy_end(stay["departure_date"], host)
    return stay


def days_before_arrival(stay):
    """date_diff('day', clock, occupancy_start): whole days, floored.

    A negative value means the arrival window has already opened.
    """
    delta = stay["occupancy_start"] - store.now()
    return delta.days


def vehicle_date_interval(stay):
    """Half-open [arrival_date, departure_date) -- the vehicle collision interval."""
    return stay.get("arrival_date"), stay.get("departure_date")


def dates_touch_or_overlap(a_start, a_end, b_start, b_end):
    """The vehicle rule's half-open DATE interval.

    PRD 3.4: the upper bound is excluded and the lower bound is included, so a
    same-day turnaround -- one stay departing on the morning another arrives --
    counts as touching and is therefore a conflict.
    """
    return a_start <= b_end and b_start <= a_end


# --------------------------------------------------------------------------
# Collision rules
# --------------------------------------------------------------------------

def vehicle_conflict(vehicle_id, arrival, departure, exclude_id=None):
    """Two stays on one rig may not touch or overlap over the half-open date range."""
    for other in store.all_of(store.STAYS):
        if other["id"] == exclude_id:
            continue
        if other.get("vehicle_id") != vehicle_id:
            continue
        status = other.get("request_status")
        if status in ("CANCELLED", "DECLINED", "NO_SHOW"):
            continue
        other_start, other_end = other.get("arrival_date"), other.get("departure_date")
        if other_start is None or other_end is None:
            continue
        # Compare the DATE boundaries; occupancy instants may be derived from
        # different hosts' arrival-window hours, and the rule is on dates.
        other_start = other_start.replace(hour=0, minute=0, second=0, microsecond=0)
        other_end = other_end.replace(hour=0, minute=0, second=0, microsecond=0)
        if dates_touch_or_overlap(arrival, departure, other_start, other_end):
            return other
    return None


def circulating_site_labels(site):
    """A stay circulates when its assigned site has the PULL_THROUGH class."""
    if site.get("site_class") == "PULL_THROUGH":
        return [label for label in split_blocks(site.get("blocks_sites"))]
    return []


def split_blocks(raw):
    if not raw:
        return []
    return [part.strip() for part in str(raw).split("|") if part.strip()]


def site_blocked(host_id, site, new_start, new_end, exclude_id=None):
    """A site may not be assigned while any site naming it in blocks_sites is
    occupied by a circulating stay over the new interval buffered by 2 hours.

    `blockers` holds the ids of the sites that block `site` (i.e. whose
    blocks_sites names `site.site_label`).
    """
    target_label = site.get("site_label")
    blockers = {
        other["id"]
        for other in store.all_of(store.SITES)
        if other.get("host_id") == host_id
        and target_label in split_blocks(other.get("blocks_sites"))
    }
    if not blockers:
        return None
    buffered_start = new_start - APPROACH_BUFFER
    buffered_end = new_end + APPROACH_BUFFER
    for stay in store.all_of(store.STAYS):
        if stay["id"] == exclude_id:
            continue
        if stay.get("host_id") != host_id:
            continue
        if stay.get("confirmed_site_id") not in blockers:
            continue
        if stay.get("request_status") not in ("CONFIRMED", "CHECKED_IN"):
            continue
        if buffered_start < stay.get("occupancy_end") and stay.get("occupancy_start") < buffered_end:
            return stay
    return None


# --------------------------------------------------------------------------
# Admission guards
# --------------------------------------------------------------------------

def host_accepting(host):
    if host.get("onboarding_status") != "APPROVED":
        return False
    if host.get("posture") == "SUSPENDED":
        return False
    return True


def capacity_admits(host, own_reservation=True):
    """effective_capacity - (committed_sites - 1) >= 1; the request's own site excluded."""
    committed = host.get("committed_sites") or 0
    room = (host.get("effective_capacity") or 0) - (committed - 1 if own_reservation else committed)
    return room >= 1


def lead_time_ok(stay):
    """The clock must be at least 48 hours before occupancy_start."""
    if stay.get("same_day_hold"):
        return True
    return store.now() <= stay["occupancy_start"] - LEAD_TIME


def self_containment_ok(host, vehicle):
    if not host.get("self_contained_required"):
        return True
    if not vehicle.get("self_contained"):
        return False
    return bool(vehicle.get("inspection_state_code"))


def vehicle_fits_site(vehicle, site):
    return (site.get("max_vehicle_length_feet") or 0) >= (vehicle.get("length_feet") or 0)


def electric_compatible(request_code, site):
    if request_code == "NONE" or request_code is None:
        return True
    if not site.get("has_electric"):
        return False
    site_rank = calc.ELECTRIC_RANK.get(site.get("electric_service_code"), 0)
    return site_rank >= calc.ELECTRIC_RANK.get(request_code, 0)


def member_eligible(member):
    return (
        member.get("subscription_status") == "ACTIVE"
        and member.get("removal_status") != "REMOVED"
    )


def require_host_accepting(host):
    if not host_accepting(host):
        errors.fail("ERR_HOST_NOT_ACCEPTING_STAYS")


def require_capacity(host, own_reservation=True):
    if host.get("posture") == "UNAVAILABLE":
        errors.fail("ERR_HOST_CAPACITY_FULL")
    if not capacity_admits(host, own_reservation):
        errors.fail("ERR_HOST_CAPACITY_FULL")


def require_lead_time(stay):
    if not lead_time_ok(stay):
        errors.fail("ERR_REQUEST_LEAD_TIME")


def require_no_vehicle_conflict(vehicle_id, arrival, departure, exclude_id=None):
    if vehicle_conflict(vehicle_id, arrival, departure, exclude_id) is not None:
        errors.fail("ERR_VEHICLE_OCCUPANCY_OVERLAP")