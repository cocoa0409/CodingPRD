"""HostBusiness and HostParkingSite services: CRUD, rulings and the cascades."""

from datetime import datetime, timezone

import calculations as calc
import errors
import recompute
import serializers
import store
import validation as v
from envelope import created_object, ok_array, ok_object, parse_iso
from recompute import recompute_host, recompute_window

HOST_CATEGORIES = ("WINERY", "FARM", "BREWERY", "ATTRACTION")
SITE_CLASSES = ("PULL_THROUGH", "BACK_IN")
ELECTRIC_CODES = ("NONE", "ELECTRIC_30A", "ELECTRIC_50A")
HOST_ACTIONS = ("APPROVE", "REJECT", "SUSPEND", "REINSTATE")


def load_host(host_id):
    host = store.get(store.HOSTS, host_id)
    if host is None:
        errors.fail("ERR_RESOURCE_NOT_FOUND", "No host business with that id.")
    return host


# --------------------------------------------------------------------------
# POST /api/hosts
# --------------------------------------------------------------------------

def create_host(actor, body):
    v.authorize(actor, ("HostOperator", "PlatformAdmin"))
    legal_name = v.text_field(body, "legal_name", required=True)
    category = v.enum_field(body, "category", HOST_CATEGORIES, required=True)
    address_line1 = v.text_field(body, "address_line1", required=True)
    state_code = v.text_field(body, "state_code", required=True)
    start_hour = v.int_field(body, "arrival_window_start_hour", default=14)
    end_hour = v.int_field(body, "arrival_window_end_hour", default=11)
    self_contained = v.bool_field(body, "self_contained_required", default=True)
    if not 0 <= start_hour <= 23 or not 0 <= end_hour <= 23:
        errors.fail("ERR_INVALID_REQUEST", "Arrival window hours must be between 0 and 23.")

    host = {
        "id": store.new_id(),
        "legal_name": legal_name,
        "category": category,
        "address_line1": address_line1,
        "state_code": state_code,
        "arrival_window_start_hour": start_hour,
        "arrival_window_end_hour": end_hour,
        "self_contained_required": self_contained,
        "onboarding_status": "PENDING_REVIEW",
        # A freshly declared host: posture UNAVAILABLE, capacity arithmetic at 0.
        "posture": "UNAVAILABLE",
        "effective_capacity": 0,
        "committed_sites": 0,
        "free_sites": 0,
        "latest_checkout_at": None,
        "seasonal_windows_reserved_sites": 0,
        "electric_site_count": 0,
        "total_amenity_count": 0,
        "patronization_credit_cents": 0,
        "host_rating_average": 0.00,
    }
    host.update(store.create_common())
    store.add(store.HOSTS, host)
    return created_object(serializers.host_row(host))


# --------------------------------------------------------------------------
# GET /api/hosts, GET /api/hosts/{hostId}
# --------------------------------------------------------------------------

def list_hosts(actor):
    v.authorize(actor, ("Member", "HostOperator", "PlatformAdmin"))
    limit, offset = v.pagination()
    rows = store.all_of(store.HOSTS)
    state_code = v.query("state_code")
    category = v.query("category")
    onboarding = v.query("onboarding_status")
    posture = v.query("posture")
    filtered = []
    for host in rows:
        if state_code is not None and host.get("state_code") != state_code:
            continue
        if category is not None and host.get("category") != category:
            continue
        if onboarding is not None and host.get("onboarding_status") != onboarding:
            continue
        if posture is not None and host.get("posture") != posture:
            continue
        filtered.append(serializers.host_row(host))
    window, total = v.page(filtered, limit, offset)
    return ok_array(window, limit, offset, total)


def get_host(actor, host_id):
    v.authorize(actor, ("Member", "HostOperator", "PlatformAdmin"))
    host = load_host(host_id)
    return ok_object(serializers.host_row(host))


def capacity_summary(actor, host_id):
    v.authorize(actor, ("Member", "HostOperator", "PlatformAdmin"))
    host = load_host(host_id)
    return ok_object(serializers.capacity_summary(host))


# --------------------------------------------------------------------------
# PATCH /api/hosts/{hostId}
# --------------------------------------------------------------------------

def patch_host(actor, host_id, body):
    v.authorize(actor, ("HostOperator", "PlatformAdmin"))
    host = load_host(host_id)
    legal_name = v.text_field(body, "legal_name")
    category = v.enum_field(body, "category", HOST_CATEGORIES)
    address_line1 = v.text_field(body, "address_line1")
    state_code = v.text_field(body, "state_code")
    self_contained = v.bool_field(body, "self_contained_required")
    v.require_fields(body, ["expected_host_version"])
    expected = v.int_field(body, "expected_host_version")

    candidate = dict(host)
    if legal_name is not None:
        candidate["legal_name"] = legal_name
    if category is not None:
        candidate["category"] = category
    if address_line1 is not None:
        candidate["address_line1"] = address_line1
    if state_code is not None:
        candidate["state_code"] = state_code
    if self_contained is not None:
        candidate["self_contained_required"] = self_contained

    # The ordinance profile is re-evaluated on the update itself.
    if calc.ordinance_violation(candidate, recompute.base_capacity(host_id)):
        errors.fail("ERR_ORDINANCE_CONSTRAINT")
    if expected != host["version"]:
        errors.fail("ERR_STALE_HOST_VERSION")

    host.update(
        {
            "legal_name": candidate["legal_name"],
            "category": candidate["category"],
            "address_line1": candidate["address_line1"],
            "state_code": candidate["state_code"],
            "self_contained_required": candidate["self_contained_required"],
        }
    )
    recompute_host(host)
    return ok_object(serializers.host_row(host))


# --------------------------------------------------------------------------
# POST /api/hosts/{hostId}/decisions
# --------------------------------------------------------------------------

def host_decision(actor, host_id, body):
    v.authorize(actor, ("PlatformAdmin",))
    host = load_host(host_id)
    action = v.enum_field(body, "action", HOST_ACTIONS, required=True)
    v.text_field(body, "reason")
    v.require_fields(body, ["expected_host_version"])
    expected = v.int_field(body, "expected_host_version")

    status = host.get("onboarding_status")

    if action == "APPROVE":
        # priority 6: the ordinance profile bites on the approval decision.
        if calc.ordinance_violation(host, recompute.base_capacity(host_id)):
            errors.fail("ERR_ORDINANCE_CONSTRAINT")
        if status != "PENDING_REVIEW":
            errors.fail("ERR_INVALID_STATE")
        if recompute.live_basis(host_id) < 1:
            errors.fail("ERR_INVALID_STATE", "The host has no active parking sites.")
        if expected != host["version"]:
            errors.fail("ERR_STALE_HOST_VERSION")
        _activate_due_windows(host)
        if recompute.electric_site_count(host_id) < 1:
            errors.fail("ERR_INVALID_STATE", "The host declares no electric parking site.")
        return _approve(host)

    if action == "REINSTATE":
        if status != "SUSPENDED":
            errors.fail("ERR_INVALID_STATE")
        if recompute.base_capacity(host_id) < 1:
            errors.fail("ERR_INVALID_STATE", "The host has no active parking site.")
        if expected != host["version"]:
            errors.fail("ERR_STALE_HOST_VERSION")
        host["onboarding_status"] = "APPROVED"
        recompute_host(host)
        return ok_object(serializers.host_row(host))

    if action == "SUSPEND":
        if status != "APPROVED":
            errors.fail("ERR_INVALID_STATE")
        if host.get("posture") not in calc.WINDOW_ACTIVE_BASES:
            errors.fail("ERR_INVALID_STATE")
        if expected != host["version"]:
            errors.fail("ERR_STALE_HOST_VERSION")
        host["onboarding_status"] = "SUSPENDED"
        host["posture"] = "SUSPENDED"
        _strand_stays(host, ("REQUESTED", "CONFIRMED"), "STAFF_FILING")
        recompute_host(host)
        return ok_object(serializers.host_row(host))

    # action == REJECT
    if status not in ("PENDING_REVIEW", "APPROVED", "SUSPENDED"):
        errors.fail("ERR_INVALID_STATE")
    if expected != host["version"]:
        errors.fail("ERR_STALE_HOST_VERSION")
    host["onboarding_status"] = "REJECTED"
    if status == "PENDING_REVIEW":
        _strand_stays(host, ("REQUESTED",), "REVIEW_REPORT")
    elif status == "APPROVED":
        _strand_stays(host, ("REQUESTED", "CONFIRMED"), "REVIEW_REPORT")
    recompute_host(host)
    return ok_object(serializers.host_row(host))


def _approve(host):
    host["onboarding_status"] = "APPROVED"
    _reconcile_windows_on_approval(host)
    recompute_host(host)
    return ok_object(serializers.host_row(host))


def _activate_due_windows(host):
    """The approval effect: a window that the clock has already reached and that
    yields a member site goes ACTIVE -- capacity is assessed after that."""
    host_id = host["id"]
    instant = store.now()
    due = [
        window
        for window in recompute.host_window_rows(host_id)
        if window.get("window_status") in ("SCHEDULED", "ACTIVE")
        and window.get("start_date") <= instant < window.get("end_date")
        and (window.get("member_capacity_ceiling") or 0) >= 1
    ]
    if not due:
        return
    due.sort(key=lambda w: (w.get("start_date"), w.get("created_at")))
    due[-1]["window_status"] = "ACTIVE"


def _reconcile_windows_on_approval(host):
    """Bring the host's availability windows into line with the logical clock."""
    host_id = host["id"]
    instant = store.now()
    windows = recompute.host_window_rows(host_id)
    live = [
        w
        for w in windows
        if w.get("window_status") == "ACTIVE"
        and w.get("start_date") <= instant < w.get("end_date")
    ]
    if not live:
        # Nothing is live: activate the in-range scheduled window that is due
        # (greatest start_date first), and retire zero-capacity scheduled ones.
        due = sorted(
            [
                w
                for w in windows
                if w.get("window_status") == "SCHEDULED"
                and w.get("start_date") <= instant < w.get("end_date")
            ],
            key=lambda w: (w.get("start_date"), w.get("created_at")),
            reverse=True,
        )
        for index, window in enumerate(due):
            if index == 0 and (window.get("capacity_override") or 0) > 0:
                window["window_status"] = "ACTIVE"
                recompute_window(window)
            elif (window.get("capacity_override") or 0) <= 0:
                window["window_status"] = "CANCELLED"
                recompute_window(window)
        live = [
            w
            for w in windows
            if w.get("window_status") == "ACTIVE"
            and w.get("start_date") <= instant < w.get("end_date")
        ]
    if not live:
        for window in windows:
            if window.get("window_status") == "SCHEDULED" and (
                window.get("capacity_override") or 0
            ) <= 0:
                window["window_status"] = "CANCELLED"
                recompute_window(window)
    else:
        # Any other active window of this host whose end_date has passed retires.
        for window in windows:
            if (
                window.get("window_status") == "ACTIVE"
                and window.get("end_date") <= instant
            ):
                window["window_status"] = "CANCELLED"
                recompute_window(window)


def _strand_stays(host, statuses, incident_origin):
    """The four-hop cascade: decline stranded stays and file MAJOR incidents."""
    host_id = host["id"]
    stranded = [
        s
        for s in store.all_of(store.STAYS)
        if s.get("host_id") == host_id and s.get("request_status") in statuses
    ]
    for stay in stranded:
        stay["request_status"] = "DECLINED"
        store.stamp(stay)
        member = store.get(store.MEMBERS, stay.get("member_id"))
        if member is None:
            continue
        incident = {
            "id": store.new_id(),
            "member_id": member["id"],
            "host_id": host_id,
            "severity": "MAJOR",
            "origin": incident_origin,
            "incident_status": "OPEN",
            "narrative": "Stay stranded by a host ruling.",
            "waived_days_remaining": 0,
        }
        incident.update(store.create_common())
        store.add(store.INCIDENTS, incident)
        # Hops 3 and 4: ledger recompute, the removal edge, and the release of
        # the removed member's in-flight reservations past the first round.
        recompute.recompute_member(member)


# --------------------------------------------------------------------------
# HostParkingSite
# --------------------------------------------------------------------------

def load_site(host_id, site_id):
    host = store.get(store.HOSTS, host_id)
    if host is None:
        errors.fail("ERR_RESOURCE_NOT_FOUND", "No host business with that id.")
    site = store.get(store.SITES, site_id)
    if site is None or site.get("host_id") != host_id:
        errors.fail("ERR_RESOURCE_NOT_FOUND", "No parking site with that id on this host.")
    return host, site


def _site_label_taken(host_id, label, exclude_id=None):
    for site in store.all_of(store.SITES):
        if site.get("host_id") != host_id:
            continue
        if site["id"] == exclude_id:
            continue
        if site.get("site_label") == label:
            return True
    return False


def _validate_blocks(host_id, raw, own_label):
    if not raw:
        return ""
    labels = [part.strip() for part in str(raw).split("|") if part.strip()]
    for label in labels:
        if label == own_label:
            errors.fail("ERR_INVALID_REQUEST", "A site may not block itself.")
    return "|".join(labels)


def create_site(actor, host_id, body):
    v.authorize(actor, ("HostOperator", "PlatformAdmin"))
    host = load_host(host_id)
    v.require_host_scope(actor, host_id)
    site_label = v.text_field(body, "site_label", required=True)
    site_class = v.enum_field(body, "site_class", SITE_CLASSES, required=True)
    max_length = v.int_field(body, "max_vehicle_length_feet", required=True, minimum=0)
    has_electric = v.bool_field(body, "has_electric", default=False)
    electric_code = v.enum_field(body, "electric_service_code", ELECTRIC_CODES, default="NONE")
    blocks = _validate_blocks(host_id, body.get("blocks_sites"), site_label)
    if _site_label_taken(host_id, site_label):
        errors.fail("ERR_DUPLICATE_SITE_LABEL")

    site = {
        "id": store.new_id(),
        "host_id": host_id,
        "site_label": site_label,
        "site_class": site_class,
        "max_vehicle_length_feet": max_length,
        "has_electric": has_electric,
        "electric_service_code": electric_code,
        "blocks_sites": blocks,
        "is_active": True,
    }
    site.update(store.create_common())
    store.add(store.SITES, site)
    recompute_host(host)
    return created_object(serializers.site_row(site))


def list_sites(actor, host_id):
    v.authorize(actor, ("Member", "HostOperator", "PlatformAdmin"))
    load_host(host_id)
    limit, offset = v.pagination()
    active = v.bool_query("is_active")
    site_class = v.query("site_class")
    rows = []
    for site in store.all_of(store.SITES):
        if site.get("host_id") != host_id:
            continue
        if active is not None and bool(site.get("is_active")) != active:
            continue
        if site_class is not None and site.get("site_class") != site_class:
            continue
        rows.append(serializers.site_row(site))
    window, total = v.page(rows, limit, offset)
    return ok_array(window, limit, offset, total)


def patch_site(actor, host_id, site_id, body):
    v.authorize(actor, ("HostOperator", "PlatformAdmin"))
    host, site = load_site(host_id, site_id)
    v.require_host_scope(actor, host_id)
    site_label = v.text_field(body, "site_label")
    site_class = v.enum_field(body, "site_class", SITE_CLASSES)
    max_length = v.int_field(body, "max_vehicle_length_feet", minimum=0)
    has_electric = v.bool_field(body, "has_electric")
    electric_code = v.enum_field(body, "electric_service_code", ELECTRIC_CODES)
    is_active = v.bool_field(body, "is_active")
    blocks = None
    if "blocks_sites" in body and body["blocks_sites"] is not None:
        blocks = _validate_blocks(
            host_id, body["blocks_sites"], site_label or site.get("site_label")
        )
    if site_label is not None and _site_label_taken(host_id, site_label, site["id"]):
        errors.fail("ERR_DUPLICATE_SITE_LABEL")

    if site_label is not None:
        site["site_label"] = site_label
    if site_class is not None:
        site["site_class"] = site_class
    if max_length is not None:
        site["max_vehicle_length_feet"] = max_length
    if has_electric is not None:
        site["has_electric"] = has_electric
    if electric_code is not None:
        site["electric_service_code"] = electric_code
    if blocks is not None:
        site["blocks_sites"] = blocks
    if is_active is not None:
        site["is_active"] = is_active
    store.stamp(site)
    recompute_host(host)
    return ok_object(serializers.site_row(site))


def site_availability(actor, host_id, site_id, from_date, to_date):
    v.authorize(actor, ("HostOperator", "PlatformAdmin"))
    host, site = load_site(host_id, site_id)
    return ok_object(serializers.site_availability(host_id, site, from_date, to_date))