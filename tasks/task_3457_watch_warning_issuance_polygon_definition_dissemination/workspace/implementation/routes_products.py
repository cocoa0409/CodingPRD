"""Product endpoints: draft creation, listing, submit-coordination, issue,
cancel, and the WEA render preview (PRD §3.4-§3.7)."""
from datetime import timedelta

from flask import Blueprint, request

from auth import authenticate, check_office_scope, require_mic_for_override, require_role
from calculations import (
    compute_impact,
    compute_required_offices,
    covering_agreement,
    criteria_met,
    duration_in_range,
    eligible_channels,
    find_overlap_conflict,
    render_wea,
    resolve_polygon_geometry,
    unsatisfiable_required,
)
from constants import (
    HAZARD_TYPES,
    POLYGON_MAX_VERTICES,
    POLYGON_MIN_VERTICES,
    PRODUCT_LEVELS,
    SUPERSEDE_REASONS,
)
from db import STORE, now
from errors import api_error
from geometry import is_simple_convex_nondegenerate
from serialize import serialize_product
from util import as_int, as_number, base_entity, envelope, get_body, list_response, parse_dt, touch

bp = Blueprint("products", __name__, url_prefix="/alerts")

FORECASTING = ["Forecaster", "MeteorologistInCharge"]
ANY_ROLE = ["PlatformAdmin", "Forecaster", "MeteorologistInCharge", "VerificationAnalyst", "EmergencyManager"]


def _get_product_or_404(product_id):
    product = STORE["products"].get(product_id)
    if product is None:
        raise api_error("ERR_PRODUCT_NOT_FOUND", "Product %s does not exist." % product_id)
    return product


def _validate_polygon_shape(polygon):
    """Tier 4 schema: object with a vertices list of {lat, lon} numerics,
    3..12 vertices."""
    if not isinstance(polygon, dict):
        raise api_error("ERR_INVALID_REQUEST", "polygon must be an object with a vertices list.")
    vertices = polygon.get("vertices")
    if not isinstance(vertices, list):
        raise api_error("ERR_INVALID_REQUEST", "polygon.vertices must be a list.")
    if not (POLYGON_MIN_VERTICES <= len(vertices) <= POLYGON_MAX_VERTICES):
        raise api_error("ERR_INVALID_REQUEST", "polygon must carry between 3 and 12 vertices.")
    normalized = []
    for vertex in vertices:
        if not isinstance(vertex, dict):
            raise api_error("ERR_INVALID_REQUEST", "each polygon vertex must be an object.")
        lat = as_number(vertex.get("lat"))
        lon = as_number(vertex.get("lon"))
        if lat is None or lon is None:
            raise api_error("ERR_INVALID_REQUEST", "each polygon vertex needs numeric lat and lon.")
        normalized.append({"lat": lat, "lon": lon})
    return {"vertices": normalized}


# ---------------------------------------------------------------------------
# create (draft)
# ---------------------------------------------------------------------------
@bp.post("/products")
def create_product():
    role, _uid, forecaster = authenticate()
    require_role(role, FORECASTING)
    body = get_body()
    # tier 3 (scope) on the raw body value, before deeper schema work
    issuing_office_id = body.get("issuing_office_id")
    if isinstance(issuing_office_id, str) and issuing_office_id:
        check_office_scope(forecaster, issuing_office_id)
    # ---- tier 4: schema ----
    product_level = body.get("product_level")
    hazard_type = body.get("hazard_type")
    if product_level not in PRODUCT_LEVELS:
        raise api_error("ERR_INVALID_REQUEST", "product_level must be one of %s" % PRODUCT_LEVELS)
    if hazard_type not in HAZARD_TYPES:
        raise api_error("ERR_INVALID_REQUEST", "hazard_type must be one of %s" % HAZARD_TYPES)
    if not isinstance(issuing_office_id, str) or not issuing_office_id:
        raise api_error("ERR_INVALID_REQUEST", "issuing_office_id is required.")
    expires_at = parse_dt(body.get("expires_at"))
    if expires_at is None:
        raise api_error("ERR_INVALID_REQUEST", "expires_at is required and must be ISO 8601.")
    effective_from = None
    if "effective_from" in body and body.get("effective_from") is not None:
        effective_from = parse_dt(body.get("effective_from"))
        if effective_from is None:
            raise api_error("ERR_INVALID_REQUEST", "effective_from must be ISO 8601.")
    zone_ids = body.get("zone_ids")
    if zone_ids is not None:
        if not isinstance(zone_ids, list) or any(not isinstance(z, str) for z in zone_ids):
            raise api_error("ERR_INVALID_REQUEST", "zone_ids must be a list of zone id strings.")
        if not zone_ids:
            zone_ids = None
    polygon = body.get("polygon")
    if polygon is not None:
        polygon = _validate_polygon_shape(polygon)
    storm_event_id = body.get("storm_event_id")
    if storm_event_id is not None and not isinstance(storm_event_id, str):
        raise api_error("ERR_INVALID_REQUEST", "storm_event_id must be a string.")
    supersedes_product_id = body.get("supersedes_product_id")
    supersede_reason = body.get("supersede_reason")
    if supersedes_product_id is not None and not isinstance(supersedes_product_id, str):
        raise api_error("ERR_INVALID_REQUEST", "supersedes_product_id must be a string.")
    # geometry combinations per level (PRD §3.4)
    if product_level in ("OUTLOOK", "WATCH"):
        if polygon is not None:
            raise api_error("ERR_INVALID_REQUEST", "polygon is forbidden for OUTLOOK/WATCH.")
        if zone_ids is None:
            raise api_error("ERR_INVALID_REQUEST", "OUTLOOK/WATCH require a non-empty zone_ids list.")
        storm_event_id = None  # linked storm is null for outlooks and zone-based watches
    elif product_level == "WARNING":
        if polygon is None:
            raise api_error("ERR_INVALID_REQUEST", "WARNING requires a polygon.")
        if zone_ids is not None:
            raise api_error("ERR_INVALID_REQUEST", "zone_ids are forbidden when a polygon is supplied.")
        if not storm_event_id:
            raise api_error("ERR_INVALID_REQUEST", "WARNING requires a linked storm_event_id.")
    else:  # ADVISORY takes exactly one of the two shapes
        if polygon is not None and zone_ids is not None:
            raise api_error("ERR_INVALID_REQUEST", "ADVISORY takes exactly one of polygon/zone_ids.")
        if polygon is None and zone_ids is None:
            raise api_error("ERR_INVALID_REQUEST", "ADVISORY takes exactly one of polygon/zone_ids.")
        if polygon is not None and not storm_event_id:
            raise api_error("ERR_INVALID_REQUEST", "A polygon-based ADVISORY requires storm_event_id.")
    # supersede pairing
    if (supersedes_product_id is None) != (supersede_reason is None):
        raise api_error(
            "ERR_INVALID_REQUEST",
            "supersedes_product_id and supersede_reason must be supplied together.",
        )
    if supersede_reason is not None and supersede_reason not in SUPERSEDE_REASONS:
        raise api_error("ERR_INVALID_REQUEST", "supersede_reason must be one of %s" % SUPERSEDE_REASONS)
    # ---- tier 5: body FK existence (office, zone, storm, product order) ----
    office = STORE["offices"].get(issuing_office_id)
    if office is None:
        raise api_error("ERR_OFFICE_NOT_FOUND", "ForecastOffice %s does not exist." % issuing_office_id)
    for zid in (zone_ids or []):
        if STORE["zones"].get(zid) is None:
            raise api_error("ERR_ZONE_NOT_FOUND", "CountyZone %s does not exist." % zid)
    storm = None
    if storm_event_id:
        storm = STORE["storms"].get(storm_event_id)
        if storm is None:
            raise api_error("ERR_STORM_EVENT_NOT_FOUND", "StormEvent %s does not exist." % storm_event_id)
    if supersedes_product_id is not None and STORE["products"].get(supersedes_product_id) is None:
        raise api_error("ERR_PRODUCT_NOT_FOUND", "Product %s does not exist." % supersedes_product_id)
    # ---- tier 8: polygon geometry ----
    if polygon is not None and not is_simple_convex_nondegenerate(polygon["vertices"]):
        raise api_error("ERR_POLYGON_INVALID", "Polygon is concave, self-intersecting, or degenerate.")
    # ---- tier 9: temporal window ----
    effective = effective_from if effective_from is not None else now()
    if not expires_at > effective:
        raise api_error("ERR_WINDOW_INVALID", "expires_at must be strictly later than effective_from.")
    if product_level in ("OUTLOOK", "WATCH") and effective < now():
        raise api_error("ERR_EFFECTIVE_IN_PAST", "OUTLOOK/WATCH effective_from is earlier than the logical clock.")
    # ---- computed block, frozen at creation ----
    if polygon is not None:
        area, resolved_zone_ids, overlaps = resolve_polygon_geometry(polygon["vertices"], office)
    else:
        area, resolved_zone_ids, overlaps = None, list(zone_ids), {}
    damage_threat, wea_360 = compute_impact(storm, resolved_zone_ids)
    required_offices = compute_required_offices(
        zone_ids if polygon is None else None, overlaps, issuing_office_id, hazard_type
    )
    product = base_entity()
    product.update({
        "product_level": product_level,
        "hazard_type": hazard_type,
        "issuing_office_id": issuing_office_id,
        "storm_event_id": storm_event_id,
        "zone_ids": list(zone_ids) if zone_ids is not None else None,
        "polygon": polygon,
        "resolved_zone_ids": resolved_zone_ids,
        "polygon_area_sq_km": area,
        "damage_threat": damage_threat,
        "wea_360": wea_360,
        "effective_from": effective,
        "expires_at": expires_at,
        "issued_at": None,
        "cancelled_at": None,
        "superseded_at": None,
        "expired_at": None,
        "supersedes_product_id": supersedes_product_id,
        "supersede_reason": supersede_reason,
        "coordination_required": bool(required_offices),
        "verified_event_count": 0,
        "verification_status": "UNVERIFIED",
        "status": "DRAFT",
        "_overlap_pct": overlaps,
        "_required_offices": required_offices,
        "_coord_round": 0,
    })
    STORE["products"][product["id"]] = product
    return envelope(serialize_product(product), "object", 201)


# ---------------------------------------------------------------------------
# reads
# ---------------------------------------------------------------------------
@bp.get("/products/<product_id>")
def get_product(product_id):
    role, _uid, _fc = authenticate()
    require_role(role, ANY_ROLE)
    return envelope(serialize_product(_get_product_or_404(product_id)), "object", 200)


@bp.get("/products")
def list_products():
    role, _uid, _fc = authenticate()
    require_role(role, ANY_ROLE)
    rows = list(STORE["products"].values())
    for field in ("issuing_office_id", "storm_event_id", "supersedes_product_id", "status", "hazard_type"):
        value = request.args.get(field)
        if value is not None:
            rows = [p for p in rows if p.get(field) == value]
    return list_response(rows, serialize_product)


# ---------------------------------------------------------------------------
# submit-coordination: DRAFT -> PENDING_COORDINATION
# ---------------------------------------------------------------------------
@bp.post("/products/<product_id>/submit-coordination")
def submit_coordination(product_id):
    role, _uid, forecaster = authenticate()
    require_role(role, FORECASTING)
    product = _get_product_or_404(product_id)
    check_office_scope(forecaster, product["issuing_office_id"])
    # tier 7: state machine preconditions
    if product["status"] != "DRAFT":
        raise api_error("ERR_INVALID_PRODUCT_STATE", "Only a DRAFT product can be submitted for coordination.")
    if not product["coordination_required"]:
        raise api_error("ERR_INVALID_PRODUCT_STATE", "coordination is not required for this product.")
    # tier 11: every required office must have a covering agreement
    _raise_unsatisfiable(product)
    # mutate: product + one REQUESTED CoordinationRequest per required office
    product["status"] = "PENDING_COORDINATION"
    product["_coord_round"] += 1
    touch(product)
    stamp = now()
    required = product["_required_offices"]
    for office_id in sorted(required, key=lambda oid: STORE["offices"][oid]["_seq"]):
        agreement = covering_agreement(product["issuing_office_id"], office_id, product["hazard_type"])
        req = base_entity()
        req["created_at"] = stamp
        req["updated_at"] = stamp
        req.update({
            "product_id": product["id"],
            "from_office_id": product["issuing_office_id"],
            "to_office_id": office_id,
            "hazard_type": product["hazard_type"],
            "status": "REQUESTED",
            "requested_at": stamp,
            "deadline_at": stamp + timedelta(minutes=agreement["coordination_timeout_minutes"]),
            "responded_at": None,
            "_round": product["_coord_round"],
        })
        STORE["coordinations"][req["id"]] = req
    return envelope(serialize_product(product), "object", 200)


def _raise_unsatisfiable(product):
    bad = unsatisfiable_required(product)
    if not bad:
        return
    _office_id, kind = bad[0]
    if kind == "zone":
        raise api_error(
            "ERR_ZONE_OUTSIDE_CWA",
            "A listed zone belongs to another office's CWA and no covering NeighborAgreement exists.",
        )
    if kind == "polygon":
        raise api_error(
            "ERR_POLYGON_OUTSIDE_CWA",
            "Polygon overlaps another office's CWA and no covering NeighborAgreement exists.",
        )
    # hurricane-pulled partner without hazard coverage: map by product geometry
    if product.get("polygon") is not None:
        raise api_error(
            "ERR_POLYGON_OUTSIDE_CWA",
            "Polygon overlaps another office's CWA and no covering NeighborAgreement exists.",
        )
    raise api_error(
        "ERR_ZONE_OUTSIDE_CWA",
        "A listed zone belongs to another office's CWA and no covering NeighborAgreement exists.",
    )


# ---------------------------------------------------------------------------
# issue
# ---------------------------------------------------------------------------
@bp.post("/products/<product_id>/issue")
def issue_product(product_id):
    role, _uid, forecaster = authenticate()
    require_role(role, FORECASTING)
    body = get_body()
    # tier 3: MIC-only coordination override
    coordination_override = body.get("coordination_override", False)
    if not isinstance(coordination_override, bool):
        raise api_error("ERR_INVALID_REQUEST", "coordination_override must be a boolean.")
    require_mic_for_override(role, forecaster, coordination_override)
    # tier 4: schema — expected_product_version is a required OCC field
    expected = as_int(body.get("expected_product_version"))
    if expected is None:
        raise api_error(
            "ERR_INVALID_REQUEST", "expected_product_version is required and must be an integer."
        )
    # tier 5: path existence, then scope against the loaded entity
    product = _get_product_or_404(product_id)
    check_office_scope(forecaster, product["issuing_office_id"])
    # tier 6: OCC
    if expected != product["version"]:
        raise api_error("ERR_STALE_VERSION", "expected_product_version does not match the stored version.")
    # tier 7: state machine preconditions
    if product["status"] not in ("DRAFT", "PENDING_COORDINATION"):
        raise api_error(
            "ERR_INVALID_PRODUCT_STATE", "Product is not in a from-state for issue (DRAFT/PENDING_COORDINATION)."
        )
    target = None
    if product.get("supersedes_product_id"):
        target = STORE["products"].get(product["supersedes_product_id"])
        if target is None or target["status"] != "ISSUED":
            raise api_error(
                "ERR_INVALID_PRODUCT_STATE", "The supersede target is no longer ISSUED."
            )
    defer_referential = False
    if product["status"] == "PENDING_COORDINATION":
        current = [
            c for c in STORE["coordinations"].values()
            if c["product_id"] == product["id"] and c.get("_round") == product["_coord_round"]
        ]
        if not coordination_override and any(c["status"] == "REQUESTED" for c in current):
            raise api_error(
                "ERR_COORDINATION_NOT_ACKED", "Not all linked CoordinationRequests are ACKNOWLEDGED."
            )
    else:  # DRAFT path
        if product["coordination_required"]:
            if unsatisfiable_required(product):
                defer_referential = True  # unsatisfiable coverage is the final referential tier
            else:
                raise api_error(
                    "ERR_COORDINATION_NOT_ACKED",
                    "coordination is required but was never submitted/completed.",
                )
    storm = None
    if product.get("storm_event_id"):
        storm = STORE["storms"].get(product["storm_event_id"])
        if storm is None or storm["status"] == "DISSIPATED":
            raise api_error(
                "ERR_INVALID_STORM_STATE",
                "A DISSIPATED (or missing) storm cannot anchor a warning or advisory.",
            )
    # tier 8: issuance criteria against the storm's current readings
    if not criteria_met(product["product_level"], product["hazard_type"], storm):
        raise api_error(
            "ERR_ISSUANCE_CRITERIA_NOT_MET",
            "Current storm readings do not meet the requested product level's thresholds.",
        )
    # tier 9: temporal window
    stamp = now()
    if product["product_level"] in ("WARNING", "ADVISORY"):
        new_effective = stamp  # server overwrites effective_from with issued_at
        if not product["expires_at"] > stamp:
            raise api_error("ERR_WINDOW_INVALID", "expires_at must be strictly later than now at issue.")
        if not duration_in_range(product["hazard_type"], new_effective, product["expires_at"]):
            raise api_error(
                "ERR_DURATION_OUT_OF_RANGE",
                "WARNING/ADVISORY duration is outside the hazard criterion's min..max range.",
            )
    else:
        new_effective = product["effective_from"]
        if not product["expires_at"] > new_effective:
            raise api_error("ERR_WINDOW_INVALID", "expires_at must be strictly later than effective_from.")
        if new_effective < stamp:
            raise api_error(
                "ERR_EFFECTIVE_IN_PAST", "OUTLOOK/WATCH effective_from is earlier than the logical clock."
            )
    # tier 10: supersede chain shape
    if target is not None:
        reason = product["supersede_reason"]
        chain_ok = True
        if reason == "UPGRADE":
            chain_ok = (
                target["product_level"] == "WATCH"
                and product["product_level"] == "WARNING"
                and target["hazard_type"] == product["hazard_type"]
            )
        else:  # CONTINUATION / CORRECTION
            chain_ok = (
                target["product_level"] == product["product_level"]
                and target["hazard_type"] == product["hazard_type"]
            )
        if stamp >= target["expires_at"]:
            chain_ok = False
        if not chain_ok:
            raise api_error("ERR_INVALID_SUPERSEDE_CHAIN", "The supersede chain shape is invalid.")
    # tier 10: product window overlap
    if find_overlap_conflict(product, new_effective) is not None:
        raise api_error(
            "ERR_PRODUCT_OVERLAP_CONFLICT",
            "Another ISSUED product of the same office, hazard and level overlaps window and zones.",
        )
    # recompute impact from the storm's current readings (needed before WEA render)
    new_threat, new_wea_360 = compute_impact(storm, product["resolved_zone_ids"])
    # tier 10: WEA message must fit each eligible channel's budget
    channels = eligible_channels(product)
    render_plan = {}
    probe = dict(product)
    probe["damage_threat"] = new_threat
    for channel in channels:
        if channel["channel_type"] != "WEA":
            continue
        message, included, dropped, _count, overflow = render_wea(probe, channel)
        if overflow:
            raise api_error(
                "ERR_MESSAGE_FORMAT_OVERFLOW",
                "WEA message exceeds the channel budget even after truncating to a single zone.",
            )
        render_plan[channel["id"]] = (message, included, dropped)
    # tier 11: cross-boundary referential coverage (deferred from the DRAFT path)
    if defer_referential:
        _raise_unsatisfiable(product)
    # ---- side effects, all atomic in this request ----
    product["issued_at"] = stamp
    product["effective_from"] = new_effective
    product["damage_threat"] = new_threat
    product["wea_360"] = new_wea_360
    if target is not None:
        target["status"] = "SUPERSEDED"
        target["superseded_at"] = stamp
        touch(target)
        for record in STORE["records"].values():
            if record["product_id"] == target["id"] and record["status"] == "QUEUED":
                record["status"] = "WITHDRAWN"
                touch(record)
        for coord in STORE["coordinations"].values():
            if coord["product_id"] == target["id"] and coord["status"] == "REQUESTED":
                coord["status"] = "CANCELLED"
                touch(coord)
    if product["status"] == "PENDING_COORDINATION" and coordination_override:
        for coord in STORE["coordinations"].values():
            if (
                coord["product_id"] == product["id"]
                and coord.get("_round") == product["_coord_round"]
                and coord["status"] == "REQUESTED"
            ):
                coord["status"] = "OVERRIDDEN"
                touch(coord)
    for channel in channels:
        record = base_entity()
        record["created_at"] = stamp
        record["updated_at"] = stamp
        if channel["channel_type"] == "WEA":
            message, included, dropped = render_plan[channel["id"]]
        else:
            # non-WEA channels carry the full render with no truncation
            message, included, dropped, _count, _over = render_wea(
                probe, {"max_message_chars": 10 ** 9}
            )
        record.update({
            "product_id": product["id"],
            "channel_id": channel["id"],
            "channel_type": channel["channel_type"],
            "status": "QUEUED",
            "rendered_message": message,
            "included_zone_ids": included,
            "dropped_zone_ids": dropped,
            "retry_count": 0,
            "queued_at": stamp,
            "sent_at": None,
            "confirmed_at": None,
        })
        STORE["records"][record["id"]] = record
    product["status"] = "ISSUED"
    touch(product)
    return envelope(serialize_product(product), "object", 200)


# ---------------------------------------------------------------------------
# cancel: ISSUED -> CANCELLED
# ---------------------------------------------------------------------------
@bp.post("/products/<product_id>/cancel")
def cancel_product(product_id):
    role, _uid, forecaster = authenticate()
    require_role(role, FORECASTING)
    product = _get_product_or_404(product_id)
    check_office_scope(forecaster, product["issuing_office_id"])
    if product["status"] != "ISSUED":
        raise api_error("ERR_INVALID_PRODUCT_STATE", "Only an ISSUED product can be cancelled.")
    stamp = now()
    product["status"] = "CANCELLED"
    product["cancelled_at"] = stamp
    touch(product)
    for record in STORE["records"].values():
        if record["product_id"] == product["id"] and record["status"] == "QUEUED":
            record["status"] = "WITHDRAWN"
            touch(record)
    return envelope(serialize_product(product), "object", 200)


# ---------------------------------------------------------------------------
# WEA render preview (read-only)
# ---------------------------------------------------------------------------
@bp.get("/products/<product_id>/wea-preview")
def wea_preview(product_id):
    role, _uid, _fc = authenticate()
    require_role(role, ANY_ROLE)
    channel_id = request.args.get("channel_id")
    if not channel_id:
        raise api_error("ERR_INVALID_REQUEST", "channel_id query parameter is required.")
    product = _get_product_or_404(product_id)
    channel = STORE["channels"].get(channel_id)
    if channel is None:
        raise api_error("ERR_CHANNEL_NOT_FOUND", "AlertChannel %s does not exist." % channel_id)
    if product.get("polygon") is None:
        raise api_error("ERR_INVALID_REQUEST", "WEA preview requires a polygon-based product.")
    message, included, dropped, count, overflow = render_wea(product, channel)
    return envelope(
        {
            "message": message,
            "included_zone_ids": included,
            "dropped_zone_ids": dropped,
            "char_count": count,
            "would_overflow": overflow,
        },
        "object",
        200,
    )
