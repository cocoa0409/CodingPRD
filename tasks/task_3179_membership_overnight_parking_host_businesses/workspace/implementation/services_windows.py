"""HostAvailabilityWindow services and the logical-clock capability."""

import calculations as calc
import errors
import recompute
import serializers
import store
import validation as v
from envelope import created_object, ok_array, ok_object, parse_iso
from recompute import recompute_host, recompute_window
from services_hosts import load_host

WINDOW_KINDS = ("SEASONAL", "EVENT")


def _confirmed_inside(window, start_date, end_date):
    """CONFIRMED stays whose occupancy_start falls inside [start_date, end_date)."""
    return [
        s
        for s in store.all_of(store.STAYS)
        if s.get("host_id") == window.get("host_id")
        and s.get("request_status") == "CONFIRMED"
        and start_date <= s.get("occupancy_start") < end_date
    ]


def load_window(window_id):
    window = store.get(store.WINDOWS, window_id)
    if window is None:
        errors.fail("ERR_RESOURCE_NOT_FOUND", "No availability window with that id.")
    return window


def _integrity(capacity_override, reserved_sites, start_date, end_date):
    """priority 21: capacity_override >= reserved_sites and end_date > start_date."""
    if reserved_sites < 0 or capacity_override < reserved_sites:
        errors.fail("ERR_WINDOW_CAPACITY_BELOW_RESERVED")
    if end_date <= start_date:
        errors.fail("ERR_WINDOW_CAPACITY_BELOW_RESERVED")


def create_window(actor, body):
    v.authorize(actor, ("HostOperator", "PlatformAdmin"))
    host_id = v.text_field(body, "host_id", required=True)
    kind = v.enum_field(body, "kind", WINDOW_KINDS, required=True)
    label = v.text_field(body, "label", required=True)
    start_raw = v.require(body, "start_date")
    end_raw = v.require(body, "end_date")
    start_date = parse_iso(start_raw)
    end_date = parse_iso(end_raw)
    capacity_override = v.int_field(body, "capacity_override", required=True)
    reserved_sites = v.int_field(body, "reserved_sites", default=0)
    host = load_host(host_id)
    v.require_host_scope(actor, host_id)
    _integrity(capacity_override, reserved_sites, start_date, end_date)

    instant = store.now()
    window = {
        "id": store.new_id(),
        "host_id": host_id,
        "kind": kind,
        "label": label,
        "start_date": start_date,
        "end_date": end_date,
        "window_status": "SCHEDULED",
        "capacity_override": capacity_override,
        "reserved_sites": reserved_sites,
        "member_capacity_ceiling": max(0, capacity_override - reserved_sites),
    }
    window.update(store.create_common())
    # ACTIVE straight away when the clock already falls inside the window and
    # the host is APPROVED; otherwise parked at SCHEDULED.
    if host.get("onboarding_status") == "APPROVED" and start_date <= instant < end_date:
        window["window_status"] = "ACTIVE"
    store.add(store.WINDOWS, window)
    recompute_window(window, bump=False)
    recompute_host(host)
    return created_object(serializers.window_row(window))


def list_host_windows(actor, host_id):
    v.authorize(actor, ("Member", "HostOperator", "PlatformAdmin"))
    load_host(host_id)
    limit, offset = v.pagination()
    status = v.query("window_status")
    kind = v.query("kind")
    overlaps_raw = v.query("overlaps_date")
    overlaps = v.date_param(overlaps_raw, "overlaps_date") if overlaps_raw is not None else None
    rows = []
    for window in store.all_of(store.WINDOWS):
        if window.get("host_id") != host_id:
            continue
        if status is not None and window.get("window_status") != status:
            continue
        if kind is not None and window.get("kind") != kind:
            continue
        if overlaps is not None and not (
            window.get("start_date") <= overlaps < window.get("end_date")
        ):
            continue
        rows.append(serializers.window_row(window))
    window_page, total = v.page(rows, limit, offset)
    return ok_array(window_page, limit, offset, total)


def get_window(actor, window_id):
    v.authorize(actor, ("Member", "HostOperator", "PlatformAdmin"))
    window = load_window(window_id)
    return ok_object(serializers.window_row(window))


def amend_window(actor, window_id, body):
    v.authorize(actor, ("HostOperator", "PlatformAdmin"))
    window = load_window(window_id)
    v.require_host_scope(actor, window.get("host_id"))
    # priority 4: well-formedness, including the mandatory version precondition.
    v.require_fields(body, ["expected_window_version"])
    expected = v.int_field(body, "expected_window_version")
    capacity_override = v.int_field(body, "capacity_override")
    reserved_sites = v.int_field(body, "reserved_sites")
    start_raw = body.get("start_date")
    end_raw = body.get("end_date")
    start_date = parse_iso(start_raw) if start_raw is not None else None
    end_date = parse_iso(end_raw) if end_raw is not None else None

    # priority 7: the amendment is admitted only while the window is ACTIVE.
    if window.get("window_status") != "ACTIVE":
        errors.fail("ERR_WINDOW_NOT_ACTIVE")

    new_override = capacity_override if capacity_override is not None else window["capacity_override"]
    new_reserved = reserved_sites if reserved_sites is not None else window["reserved_sites"]
    new_start = start_date if start_date is not None else window["start_date"]
    new_end = end_date if end_date is not None else window["end_date"]
    # priority 21: window integrity.
    _integrity(new_override, new_reserved, new_start, new_end)

    # priority 22: an amendment may not evict a confirmed stay.
    ceiling = max(0, new_override - new_reserved)
    inside = [s for s in _confirmed_inside(window, new_start, new_end)]
    if len(inside) > ceiling:
        errors.fail("ERR_WINDOW_EVICTS_CONFIRMED_STAY")

    # priority 24: the version precondition, matched after every other check.
    if expected != window.get("version"):
        errors.fail("ERR_STALE_WINDOW_VERSION")

    window["capacity_override"] = new_override
    window["reserved_sites"] = new_reserved
    window["start_date"] = new_start
    window["end_date"] = new_end
    window["window_status"] = "ACTIVE"
    recompute_window(window)
    host = store.get(store.HOSTS, window.get("host_id"))
    if host is not None:
        recompute_host(host)
    return ok_object(serializers.window_row(window))


def cancel_window(actor, window_id, body):
    v.authorize(actor, ("HostOperator", "PlatformAdmin"))
    window = load_window(window_id)
    v.require_host_scope(actor, window.get("host_id"))
    if window.get("window_status") not in ("SCHEDULED", "ACTIVE"):
        errors.fail("ERR_INVALID_STATE")
    window["window_status"] = "CANCELLED"
    recompute_window(window)
    host = store.get(store.HOSTS, window.get("host_id"))
    if host is not None:
        recompute_host(host)
    return ok_object(serializers.window_row(window))


# --------------------------------------------------------------------------
# POST /api/_clock/set_current_utc
# --------------------------------------------------------------------------

def set_clock(actor, body):
    v.authorize(actor, ("PlatformAdmin",))
    instant = parse_iso(v.require(body, "to_iso8601"))

    # Snapshot the live basis before the move so we can report only the hosts
    # whose basis actually changed; the window transitions come first.
    before_basis = {
        host["id"]: recompute.live_basis(host["id"]) for host in store.all_of(store.HOSTS)
    }
    store.set_clock(instant)

    activated = []
    deactivated = []
    touched_hosts = set()

    for window in store.all_of(store.WINDOWS):
        status = window.get("window_status")
        host = store.get(store.HOSTS, window.get("host_id"))
        if status == "SCHEDULED" and window["start_date"] <= instant < window["end_date"]:
            if host is not None and host.get("onboarding_status") == "APPROVED":
                window["window_status"] = "ACTIVE"
                activated.append(window["id"])
                touched_hosts.add(window.get("host_id"))
        elif status == "ACTIVE":
            if instant < window["start_date"]:
                window["window_status"] = "SCHEDULED"
                deactivated.append(window["id"])
                touched_hosts.add(window.get("host_id"))
            elif instant >= window["end_date"]:
                window["window_status"] = "CANCELLED"
                deactivated.append(window["id"])
                touched_hosts.add(window.get("host_id"))

    # Same pass: any other ACTIVE window of a touched host whose end_date has
    # already passed is retired to CANCELLED.
    for host_id in list(touched_hosts):
        for window in recompute.host_window_rows(host_id):
            if (
                window.get("window_status") == "ACTIVE"
                and window["end_date"] <= instant
                and window["id"] not in deactivated
            ):
                window["window_status"] = "CANCELLED"
                deactivated.append(window["id"])

    # Capacity, free_sites and posture for every host whose live basis changed.
    for host in store.all_of(store.HOSTS):
        host_id = host["id"]
        if recompute.live_basis(host_id) == before_basis.get(host_id) and (
            host_id not in touched_hosts
        ):
            continue
        before = _host_snapshot(host)
        host.update(recompute.compute_host_derived(host))
        if before != _host_snapshot(host):
            store.stamp(host)

    return ok_object(
        {
            "current_utc": serializers.iso(store.now()),
            "activated_window_ids": activated,
            "deactivated_window_ids": deactivated,
        }
    )


def _host_snapshot(host):
    return (
        host.get("effective_capacity"),
        host.get("committed_sites"),
        host.get("free_sites"),
        host.get("posture"),
        host.get("latest_checkout_at"),
    )