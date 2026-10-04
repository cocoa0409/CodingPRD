"""Permit counter, state remittance, club points, tiers and credit cards."""
from core import DB, err, get, find, find_one, create_row, touch, iso, norm_now
import calc
from calc import _parse_iso
import services as S
from services import (Shape, require_store, require_row, ensure_belongs, page,
                      pagination_args, softly)
from app import route, ok, ok_list, created


# ---------------------------------------------------------------------------
# PermitSale
# ---------------------------------------------------------------------------
@route("POST", "/stores/{store_id}/permit-sales", ["PermitClerk"])
def permit_sale_create(ctx):
    store = require_store(ctx.p("store_id"))
    body = ctx.body
    shape = Shape()
    member_id = shape.str(body, "member_id", required=True)
    permit_type = shape.enum(body, "permit_type",
                             ("FISHING", "HUNTING", "ARCHERY_RANGE", "BOAT_REGISTRATION"))
    residency_class = shape.enum(body, "residency_class",
                                 ("RESIDENT", "NON_RESIDENT", "SENIOR", "YOUTH"))
    term_days = shape.int(body, "term_days", required=True)
    land_access_units = shape.int(body, "land_access_units", minimum=0)
    agent_user_id = shape.str(body, "agent_user_id", required=True)
    batch_id = shape.str(body, "permit_remit_batch_id")
    expected_version = shape.int(body, "expected_remit_batch_version")
    shape.raise_now()

    member = require_row("members", member_id)
    batch = None
    if batch_id is not None:
        batch = get("remit_batches", batch_id)
        if batch is None:
            err("ERR_RESOURCE_NOT_FOUND")
        ensure_belongs("remit_batches", batch, store["id"])

    # p22 term / land-access boundaries
    if term_days < 1 or (land_access_units is not None and land_access_units < 0):
        err("ERR_INVALID_TERM_DAYS")

    # p25 stale parent version
    if batch is not None and expected_version is not None \
            and expected_version != int(batch.get("version", 0)):
        err("ERR_STALE_VERSION")

    units = 0 if land_access_units is None else land_access_units
    row = create_row("permit_sales", {
        "store_id": store["id"],
        "member_id": member["id"],
        "permit_type": permit_type,
        "residency_class": residency_class,
        "term_days": term_days,
        "land_access_units": units,
        "agent_user_id": agent_user_id,
        "issuer_admin_user_id": ctx.user_id,
        "remitter_admin_user_id": None,
        "permit_remit_batch_id": batch["id"] if batch is not None else None,
        "fee_cents": 0,
        "status": "ISSUED",
    })
    row["fee_cents"] = calc.permit_fee(permit_type, residency_class, term_days, units)
    if batch is not None:
        calc.permit_remit_snapshot(batch)
        touch(batch)
    return created(row)


@route("GET", "/stores/permit-sales/{sale_id}",
       ["PermitClerk", "RemitAdmin", "StoreManager", "PlatformAdmin", "Member"])
def permit_sale_read(ctx):
    return ok(require_row("permit_sales", ctx.p("sale_id")))


@route("GET", "/stores/permit-sales",
       ["PermitClerk", "RemitAdmin", "StoreManager", "PlatformAdmin"])
def permit_sale_list(ctx):
    rows = list(DB.tables["permit_sales"].values())
    for key in ("permit_remit_batch_id", "store_id", "member_id", "status"):
        value = ctx.args.get(key)
        if value:
            rows = [r for r in rows if r.get(key) == value]
    limit, offset = pagination_args(ctx.args)
    window, meta = page(rows, limit, offset)
    return ok_list(window, meta)


@route("POST", "/stores/permit-sales/{sale_id}/void", ["PermitClerk", "PlatformAdmin"])
def permit_sale_void(ctx):
    sale = require_row("permit_sales", ctx.p("sale_id"))
    if sale.get("status") in ("REMITTED", "VOIDED"):
        err("ERR_ALREADY_TERMINAL")
    if sale.get("status") not in ("ISSUED", "CORRECTED"):
        err("ERR_INVALID_STATE")
    batch = get("remit_batches", sale.get("permit_remit_batch_id")) \
        if sale.get("permit_remit_batch_id") else None
    if batch is not None and batch.get("status") in ("SEALED", "TRANSMITTED", "ACCEPTED"):
        err("ERR_INVALID_STATE", "The sale belongs to a batch that is no longer open.")
    was_corrected = sale.get("status") == "CORRECTED"
    sale["status"] = "VOIDED"
    if was_corrected:
        sale["fee_cents"] = calc.permit_fee(
            sale["permit_type"], sale["residency_class"], sale["term_days"],
            int(sale.get("land_access_units", 0) or 0), "per_unit_rounded")
        if batch is not None:
            calc.permit_remit_snapshot(batch)
            touch(batch)
    touch(sale)
    return ok(sale)


# ---------------------------------------------------------------------------
# PermitRemitBatch
# ---------------------------------------------------------------------------
@route("POST", "/stores/{store_id}/permit-remit-batches", ["RemitAdmin"])
def batch_create(ctx):
    store = require_store(ctx.p("store_id"))
    body = ctx.body
    shape = Shape()
    window_start = shape.dt(body, "window_start_utc", required=True)
    window_end = shape.dt(body, "window_end_utc", required=True)
    shape.raise_now()
    if window_end is None or window_start is None or window_end <= window_start:
        err("ERR_INVALID_SLOT_WINDOW")
    row = create_row("remit_batches", {
        "store_id": store["id"],
        "window_start_utc": iso(window_start),
        "window_end_utc": iso(window_end),
        "gross_fee_cents": 0,
        "interpretative_gross_cents": 0,
        "remit_variance_cents": 0,
        "agency_ack_no": None,
        "status": "OPEN",
    })
    return created(row)


@route("GET", "/stores/permit-remit-batches/{batch_id}",
       ["RemitAdmin", "PlatformAdmin", "StoreManager"])
def batch_read(ctx):
    batch = require_row("remit_batches", ctx.p("batch_id"))
    frozen = int(batch.get("gross_fee_cents", 0) or 0)
    if batch.get("status") in ("SEALED", "TRANSMITTED", "ACCEPTED", "CORRECTED"):
        calc.permit_remit_snapshot(batch, frozen=frozen)
    return ok(batch)


@route("GET", "/stores/permit-remit-batches", ["RemitAdmin", "PlatformAdmin", "StoreManager"])
def batch_list(ctx):
    rows = list(DB.tables["remit_batches"].values())
    for key in ("store_id", "status"):
        value = ctx.args.get(key)
        if value:
            rows = [r for r in rows if r.get(key) == value]
    limit, offset = pagination_args(ctx.args)
    window, meta = page(rows, limit, offset)
    return ok_list(window, meta)


@route("POST", "/stores/permit-remit-batches/{batch_id}/seal", ["RemitAdmin"])
def batch_seal(ctx):
    batch = require_row("remit_batches", ctx.p("batch_id"))
    if batch.get("status") in ("ACCEPTED", "CORRECTED"):
        err("ERR_ALREADY_TERMINAL")
    if batch.get("status") != "OPEN":
        err("ERR_INVALID_STATE")

    body = ctx.body
    remitter = body.get("remitter_admin_user_id")
    if remitter is None or remitter == "":
        remitter = ctx.user_id
    if not isinstance(remitter, str):
        err("ERR_INVALID_REQUEST", "remitter_admin_user_id must be a string.")

    eligible = [s for s in DB.tables["permit_sales"].values()
                if s.get("store_id") == batch.get("store_id")
                and s.get("status") == "ISSUED"
                and _in_window(s, batch)]
    if not eligible:
        err("ERR_EMPTY_REMIT_WINDOW")

    seal_id = ctx.user_id
    for s in eligible:
        if s.get("issuer_admin_user_id") is not None and s.get("issuer_admin_user_id") == seal_id:
            err("ERR_SEGREGATION_OF_DUTIES")

    frozen = 0
    for s in eligible:
        s["remitter_admin_user_id"] = remitter
        frozen += int(s.get("fee_cents", 0) or 0)
    calc.permit_remit_snapshot(batch, frozen=frozen)
    batch["remitter_admin_user_id"] = remitter
    batch["status"] = "SEALED"
    touch(batch)
    store = get("stores", batch.get("store_id"))
    if store is not None:
        store["remit_ledger_cents"] = int(store.get("remit_ledger_cents", 0) or 0) + frozen
        touch(store)
    return ok(batch)


def _in_window(sale, batch):
    created = _parse_iso(sale.get("created_at"))
    start = _parse_iso(batch.get("window_start_utc"))
    end = _parse_iso(batch.get("window_end_utc"))
    if created is None:
        return False
    if start is not None and created < start:
        return False
    if end is not None and created >= end:
        return False
    return True


@route("POST", "/stores/permit-remit-batches/{batch_id}/transmit", ["RemitAdmin"])
def batch_transmit(ctx):
    batch = require_row("remit_batches", ctx.p("batch_id"))
    if batch.get("status") in ("ACCEPTED", "CORRECTED"):
        err("ERR_ALREADY_TERMINAL")
    if batch.get("status") != "SEALED":
        err("ERR_INVALID_STATE")
    batch["status"] = "TRANSMITTED"
    touch(batch)
    return ok(batch)


@route("POST", "/stores/permit-remit-batches/{batch_id}/acknowledge", ["AgencyOperator"])
def batch_acknowledge(ctx):
    batch = require_row("remit_batches", ctx.p("batch_id"))
    if batch.get("status") == "ACCEPTED":
        err("ERR_ALREADY_TERMINAL")
    if batch.get("status") not in ("TRANSMITTED", "CORRECTED"):
        err("ERR_INVALID_STATE")
    ack_no = ctx.body.get("agency_ack_no")
    if not isinstance(ack_no, str) or ack_no == "":
        err("ERR_INVALID_REQUEST", "agency_ack_no must be a non-empty string.")
    batch["agency_ack_no"] = ack_no
    batch["status"] = "ACCEPTED"
    for s in DB.tables["permit_sales"].values():
        if s.get("store_id") != batch.get("store_id") or not _in_window(s, batch):
            continue
        if s.get("status") in ("ISSUED", "CORRECTED"):
            s["status"] = "REMITTED"
            touch(s)
    calc.permit_remit_snapshot(batch, frozen=int(batch.get("gross_fee_cents", 0) or 0))
    touch(batch)
    store = get("stores", batch.get("store_id"))
    if store is not None:
        store["permit_remit_epoch"] = int(store.get("permit_remit_epoch", 0) or 0) + 1
        touch(store)
    return ok(batch)


@route("POST", "/stores/permit-remit-batches/{batch_id}/reject-correction", ["AgencyOperator"])
def batch_reject_correction(ctx):
    batch = require_row("remit_batches", ctx.p("batch_id"))
    if batch.get("status") == "ACCEPTED":
        err("ERR_ALREADY_TERMINAL")
    if batch.get("status") not in ("TRANSMITTED", "CORRECTED"):
        err("ERR_INVALID_STATE")

    body = ctx.body
    shape = Shape()
    sale_id = shape.str(body, "sale_id", required=True)
    revised = shape.int(body, "revised_fee_cents", required=True, minimum=0)
    shape.raise_now()
    sale = get("permit_sales", sale_id)
    if sale is None:
        err("ERR_RESOURCE_NOT_FOUND")
    if sale.get("permit_remit_batch_id") != batch["id"]:
        err("ERR_PARENT_MISMATCH")

    frozen = int(batch.get("gross_fee_cents", 0) or 0)
    if batch.get("status") == "TRANSMITTED":
        batch["status"] = "CORRECTED"
        for s in DB.tables["permit_sales"].values():
            if s.get("store_id") != batch.get("store_id") or not _in_window(s, batch):
                continue
            if s.get("status") == "REMITTED":
                s["status"] = "CORRECTED"
                touch(s)
    sale["fee_cents"] = revised
    if sale.get("status") == "ISSUED":
        sale["status"] = "CORRECTED"
    touch(sale)
    calc.permit_remit_snapshot(batch, frozen=frozen)
    touch(batch)
    return ok(batch)


# ---------------------------------------------------------------------------
# ClubCardApplication
# ---------------------------------------------------------------------------
CARD_PRODUCTS = ("CLASSIC", "REWARDS", "PATRON")


@route("POST", "/stores/{store_id}/club-card-applications",
       ["StoreManager", "ClubCardSpecialist"])
def club_app_create(ctx):
    store = require_store(ctx.p("store_id"))
    body = ctx.body
    shape = Shape()
    member_id = shape.str(body, "member_id", required=True)
    card_product = shape.enum(body, "card_product", CARD_PRODUCTS)
    donation_match_bps = shape.int(body, "donation_match_bps", required=True, minimum=0)
    underwriter_user_id = shape.str(body, "underwriter_user_id")
    shape.raise_now()
    member = require_row("members", member_id)
    row = create_row("club_card_applications", {
        "store_id": store["id"],
        "member_id": member["id"],
        "card_product": card_product,
        "donation_match_bps": donation_match_bps,
        "underwriter_user_id": underwriter_user_id,
        "decision_user_id": None,
        "decision_reason": None,
        "credit_limit_cents": 0,
        "status": "PENDING",
    })
    return created(row)


@route("GET", "/stores/club-card-applications/{application_id}",
       ["ClubCardSpecialist", "CreditOfficer", "StoreManager", "PlatformAdmin", "Member"])
def club_app_read(ctx):
    return ok(require_row("club_card_applications", ctx.p("application_id")))


@route("GET", "/stores/club-card-applications",
       ["ClubCardSpecialist", "CreditOfficer", "StoreManager", "PlatformAdmin"])
def club_app_list(ctx):
    rows = list(DB.tables["club_card_applications"].values())
    for key in ("member_id", "store_id", "status"):
        value = ctx.args.get(key)
        if value:
            rows = [r for r in rows if r.get(key) == value]
    limit, offset = pagination_args(ctx.args)
    window, meta = page(rows, limit, offset)
    return ok_list(window, meta)


@route("POST", "/stores/club-card-applications/{application_id}/underwrite",
       ["CreditUnderwriter"])
def club_app_underwrite(ctx):
    app = require_row("club_card_applications", ctx.p("application_id"))
    if app.get("status") in ("DECLINED", "ACTIVATED"):
        err("ERR_ALREADY_TERMINAL")
    if app.get("status") != "PENDING":
        err("ERR_INVALID_STATE")
    shape = Shape()
    underwriter = shape.str(ctx.body, "underwriter_user_id")
    shape.raise_now()
    if underwriter is None or underwriter == "":
        underwriter = ctx.user_id
    if not isinstance(underwriter, str) or underwriter == "":
        err("ERR_SEGREGATION_OF_DUTIES", "An underwriter identity is required.")
    if underwriter == app.get("decision_user_id"):
        err("ERR_SEGREGATION_OF_DUTIES")
    app["underwriter_user_id"] = underwriter
    app["status"] = "UNDERWRITING"
    touch(app)
    return ok(app)


@route("POST", "/stores/club-card-applications/{application_id}/decide", ["CreditOfficer"])
def club_app_decide(ctx):
    app = require_row("club_card_applications", ctx.p("application_id"))
    if app.get("status") in ("DECLINED", "ACTIVATED"):
        err("ERR_ALREADY_TERMINAL")
    if app.get("status") != "UNDERWRITING":
        err("ERR_INVALID_STATE")
    body = ctx.body
    shape = Shape()
    decision_user_id = shape.str(body, "decision_user_id", required=True)
    decision = shape.enum(body, "decision", ("APPROVED", "DECLINED"))
    decision_reason = shape.str(body, "decision_reason")
    credit_limit_cents = shape.int(body, "credit_limit_cents", minimum=0)
    shape.raise_now()

    # p19 segregation of duties
    if decision_user_id == app.get("underwriter_user_id"):
        err("ERR_SEGREGATION_OF_DUTIES")

    member = require_row("members", app.get("member_id"))
    if decision == "APPROVED":
        # §3.8: "An approval carries a decision, a decision_reason, and a
        # credit_limit_cents" — the required-field rule at p24 precedes the
        # credit-limit floor at p21.
        if not (decision_reason and decision_reason != ""):
            err("ERR_INVALID_REQUEST", "decision_reason is required.")
        # p21 credit-limit floor
        if credit_limit_cents is None or credit_limit_cents < 50000:
            err("ERR_CREDIT_LIMIT_BELOW_FLOOR")
        if member.get("club_tier") not in ("SILVER", "GOLD", "PATRON") \
                and app.get("card_product") != "CLASSIC":
            err("ERR_INVALID_STATE", "The card product is reserved for tiered members.")
        app["credit_limit_cents"] = credit_limit_cents
        app["decision_user_id"] = decision_user_id
        app["decision_reason"] = decision_reason
        app["status"] = "APPROVED"
        member["club_card_status"] = "PENDING"
        touch(member)
    else:
        if not (decision_reason and decision_reason != ""):
            err("ERR_INVALID_REQUEST", "decision_reason is required.")
        app["decision_user_id"] = decision_user_id
        app["decision_reason"] = decision_reason
        app["status"] = "DECLINED"
        calc.tier_threshold_eval(member)
    touch(app)
    return ok(app)


@route("POST", "/stores/club-card-applications/{application_id}/activate", ["StoreManager"])
def club_app_activate(ctx):
    app = require_row("club_card_applications", ctx.p("application_id"))
    if app.get("status") in ("DECLINED", "ACTIVATED"):
        err("ERR_ALREADY_TERMINAL")
    if app.get("status") != "APPROVED":
        err("ERR_INVALID_STATE")
    member = require_row("members", app.get("member_id"))
    if member.get("club_card_status") not in ("NONE", "PENDING"):
        err("ERR_INVALID_STATE")
    app["status"] = "ACTIVATED"
    member["club_card_status"] = "ACTIVE"
    member["strike_epoch_started_at"] = iso(norm_now())
    calc.tier_threshold_eval(member)
    touch(app)
    return ok(app)


# ---------------------------------------------------------------------------
# PointEvent
# ---------------------------------------------------------------------------
@route("POST", "/stores/{store_id}/point-events", ["StoreManager", "ClubCardSpecialist"])
def point_event_create(ctx):
    store = require_store(ctx.p("store_id"))
    body = ctx.body
    shape = Shape()
    member_id = shape.str(body, "member_id", required=True)
    event_kind = shape.enum(body, "event_kind", ("AWARD", "REDEEM", "REVERSAL", "ADJUST"))
    if "points_delta" not in body or body.get("points_delta") is None:
        err("ERR_INVALID_REQUEST", "The required field 'points_delta' is absent.")
    points_delta = body.get("points_delta")
    if isinstance(points_delta, bool) or not isinstance(points_delta, int):
        err("ERR_INVALID_REQUEST", "points_delta must be an integer.")
    boat_deal_id = shape.str(body, "boat_deal_id")
    shape.raise_now()
    member = require_row("members", member_id)
    if boat_deal_id is not None:
        require_row("boat_deals", boat_deal_id)
    event = S.post_point_event(store["id"], member, event_kind, points_delta, boat_deal_id)
    return created(event)


@route("GET", "/stores/point-events/{point_event_id}",
       ["StoreManager", "ClubCardSpecialist", "PlatformAdmin", "Member"])
def point_event_read(ctx):
    return ok(require_row("point_events", ctx.p("point_event_id")))


@route("GET", "/stores/point-events",
       ["StoreManager", "ClubCardSpecialist", "PlatformAdmin", "Member"])
def point_event_list(ctx):
    rows = list(DB.tables["point_events"].values())
    for key in ("member_id", "boat_deal_id", "store_id", "event_kind"):
        value = ctx.args.get(key)
        if value:
            rows = [r for r in rows if r.get(key) == value]
    limit, offset = pagination_args(ctx.args)
    window, meta = page(rows, limit, offset)
    return ok_list(window, meta)