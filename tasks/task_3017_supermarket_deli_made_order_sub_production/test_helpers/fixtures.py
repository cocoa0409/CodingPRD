"""Composite setup helpers.

Every helper here builds its preconditions from scratch through declared
endpoints only — the harness restarts the server (and therefore empties the
database) before each individual test, so nothing may be assumed to pre-exist.
"""

from types import SimpleNamespace

from prd_bench_local_runner.testing import get_success_data


def dt_add_hours_iso(iso, hours):
    """Shift an ISO instant by whole hours, in tests, without importing the
    implementation's helpers (the test artifact must stay independent of it)."""
    from datetime import datetime, timedelta, timezone

    s = iso[:-1] + "+00:00" if iso.endswith("Z") else iso
    dt = datetime.fromisoformat(s).astimezone(timezone.utc) + timedelta(hours=hours)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

from .api_client import api_client
from .factories import (
    create_associate_payload,
    create_batch_payload,
    create_bread_item_payload,
    create_bread_order_payload,
    create_catering_order_payload,
    create_certification_payload,
    create_cold_cut_item_payload,
    create_item_payload,
    create_label_payload,
    create_platter_item_payload,
    create_price_file_payload,
    create_promotion_payload,
    create_sanitation_cycle_payload,
    create_slicer_payload,
    create_store_payload,
    create_sub_ticket_payload,
    create_waste_record_payload,
)
from .test_users import (
    make_bakery_coordinator_headers,
    make_platform_admin_headers,
    make_deli_clerk_headers,
    make_deli_manager_headers,
    make_scale_operator_headers,
)

DEFAULT_CLOCK = "2026-09-02T06:00:00Z"
CERT_ISSUED = "2026-09-01T00:00:00Z"
CERT_EXPIRES = "2026-12-31T00:00:00Z"


# --------------------------------------------------------------------------
# Role headers (identity-threading helpers)
# --------------------------------------------------------------------------

def platform_admin_headers():
    return make_platform_admin_headers("test-platform-admin-1")


def scale_operator_headers():
    return make_scale_operator_headers("test-scale-operator-1")


def clerk_headers(associate_id):
    """DeliClerk acting as the named Associate — required for every
    certification-, allergy- or segregation-gated call."""
    return make_deli_clerk_headers(associate_id)


def manager_headers(associate_id):
    """DeliManager acting as the named Associate."""
    return make_deli_manager_headers(associate_id)


def coordinator_headers(associate_id):
    """BakeryCoordinator acting as the named Associate."""
    return make_bakery_coordinator_headers(associate_id)


# --------------------------------------------------------------------------
# Clock
# --------------------------------------------------------------------------

def set_clock(current_utc=DEFAULT_CLOCK):
    return get_success_data(api_client.set_clock(current_utc, platform_admin_headers()))


def advance_clock(current_utc):
    return set_clock(current_utc)


def open_markdown_window(batch, item, margin_minutes=5):
    """Move the logical clock inside a one-minute-wide slice of the batch's
    half-open markdown window, `margin_minutes` after it opens.

    PRD §3.1 defines the window as [hold_expires_at - item.markdown_window_minutes,
    hold_expires_at); a batch whose `markdown_window_minutes` is zero has no such
    window at all, and one whose window has already closed cannot be marked down.
    """
    from datetime import datetime, timedelta, timezone

    def parse(s):
        return datetime.fromisoformat(s[:-1] + "+00:00" if s.endswith("Z") else s)

    expiry = parse(batch["hold_expires_at"])
    window = int(item["markdown_window_minutes"])
    assert window > 0, "a zero-markdown item has no markdown window to open"
    at = expiry - timedelta(minutes=window - margin_minutes)
    return set_clock(at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))


def close_markdown_window(batch, item, margin_minutes=1):
    """Move the logical clock past a batch's half-open hold window.

    PRD §3.3 permits a direct discard from `DRAFT` only when the markdown window
    has closed (or the item declares none), so a scenario that goes straight from
    `DRAFT` to discard must first step past `hold_expires_at`.
    """
    from datetime import datetime, timedelta, timezone

    s = batch["hold_expires_at"]
    expiry = datetime.fromisoformat(s[:-1] + "+00:00" if s.endswith("Z") else s)
    at = expiry + timedelta(minutes=margin_minutes)
    return set_clock(at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))


# --------------------------------------------------------------------------
# Tier 1: single-entity creation and state progression
# --------------------------------------------------------------------------

def create_store(**overrides):
    return get_success_data(api_client.create_store(create_store_payload(**overrides), platform_admin_headers()))


def get_store(store_id):
    return get_success_data(api_client.get_store(store_id, platform_admin_headers()))


def store_version(store_id):
    """Read the store's current version (needed as an OCC token)."""
    return get_store(store_id)["version"]


def create_item(**overrides):
    return get_success_data(api_client.create_item(create_item_payload(**overrides), platform_admin_headers()))


def create_sub_item(bread_item_id=None, **overrides):
    payload = create_item_payload(**overrides)
    payload["bread_deli_item_id"] = bread_item_id
    return get_success_data(api_client.create_item(payload, platform_admin_headers()))


def create_cold_cut_item(**overrides):
    return get_success_data(
        api_client.create_item(create_cold_cut_item_payload(**overrides), platform_admin_headers())
    )


def create_bread_item(**overrides):
    return get_success_data(
        api_client.create_item(create_bread_item_payload(**overrides), platform_admin_headers())
    )


def create_platter_item(**overrides):
    return get_success_data(
        api_client.create_item(create_platter_item_payload(**overrides), platform_admin_headers())
    )


def create_associate(store_id, **overrides):
    payload = create_associate_payload(store_id=store_id, **overrides)
    return get_success_data(api_client.create_associate(payload, platform_admin_headers()))


def create_certification(store_id, associate_id, cert_type, issued_at=CERT_ISSUED, expires_at=CERT_EXPIRES, **overrides):
    payload = create_certification_payload(
        store_id=store_id,
        associate_id=associate_id,
        cert_type=cert_type,
        issued_at=issued_at,
        expires_at=expires_at,
        **overrides,
    )
    return get_success_data(api_client.create_certification(payload, platform_admin_headers()))


def create_slicer(store_id, asset_tag, assigned_operator_id=None, sanitation_cycle_limit=25, **overrides):
    payload = create_slicer_payload(
        store_id=store_id,
        asset_tag=asset_tag,
        sanitation_cycle_limit=sanitation_cycle_limit,
        **overrides,
    )
    if assigned_operator_id is not None:
        payload["assigned_operator_id"] = assigned_operator_id
    return get_success_data(api_client.create_slicer(payload, platform_admin_headers()))


def create_batch(store_id, item_id, associate_id, batch_code, planned_lbs, slicer_id=None, **overrides):
    payload = create_batch_payload(
        store_id=store_id,
        deli_item_id=item_id,
        produced_by_associate_id=associate_id,
        batch_code=batch_code,
        planned_lbs=planned_lbs,
    )
    if slicer_id is not None:
        payload["slicer_id"] = slicer_id
    payload.update(overrides)
    return get_success_data(api_client.create_batch(payload, clerk_headers(associate_id)))


def start_batch(batch_id, associate_id, expected_store_version=None, store_id=None):
    if expected_store_version is None:
        expected_store_version = store_version(store_id)
    return get_success_data(
        api_client.start_batch(batch_id, expected_store_version, clerk_headers(associate_id))
    )


def complete_batch(batch_id, associate_id, produced_lbs):
    return get_success_data(
        api_client.complete_batch(batch_id, produced_lbs, clerk_headers(associate_id))
    )


def produce_batch(store_id, item_id, associate_id, batch_code, planned_lbs, produced_lbs=None, slicer_id=None):
    """Create -> start -> complete. Returns the ON_LINE batch."""
    batch = create_batch(store_id, item_id, associate_id, batch_code, planned_lbs, slicer_id=slicer_id)
    start_batch(batch["id"], associate_id, store_id=store_id)
    if produced_lbs is None:
        produced_lbs = planned_lbs
    return complete_batch(batch["id"], associate_id, produced_lbs)


def create_waste_record(store_id, batch_id, markdown_by_associate_id, reason="QUALITY", acting_associate_id=None):
    payload = create_waste_record_payload(
        store_id=store_id,
        production_batch_id=batch_id,
        markdown_by_associate_id=markdown_by_associate_id,
        reason=reason,
    )
    headers = clerk_headers(acting_associate_id or markdown_by_associate_id)
    return get_success_data(api_client.create_waste_record(payload, headers))


def discard_waste_record(waste_id, discard_lbs, acting_associate_id):
    return get_success_data(
        api_client.discard_waste_record(waste_id, discard_lbs, clerk_headers(acting_associate_id))
    )


def verify_waste_record(waste_id, verifier_associate_id, certification_id, batch_id, acting_manager_id):
    batch = get_success_data(api_client.get_batch(batch_id, platform_admin_headers()))
    return get_success_data(
        api_client.verify_waste_record(
            waste_id,
            verifier_associate_id,
            certification_id,
            batch["version"],
            manager_headers(acting_manager_id),
        )
    )


# --------------------------------------------------------------------------
# Tier 2: entity hierarchy — the standard deli master data
# --------------------------------------------------------------------------

def setup_deli_master_data(
    capacity=420,
    hot_bar_capacity=90,
    sub_station_count=2,
    store_number="101",
    store_name="Store One",
    slicer_count=7,
    clerk_allergy_set=("MILK", "WHEAT", "SOY"),
    with_price_file=True,
):
    """Store + catalog + staffing + slicers, the preamble almost every claim needs.

    Sub-ticket completion and batch completion both print a weight label, and PRD
    §3.6 says a label-generating call resolves the store's ACTIVE scale price file
    or fails with `ERR_PRICE_FILE_STALE`. PRD §2.6 additionally makes a null
    `active_price_file_id` drive the store to `RESTRICTED`, which blocks batch
    creation entirely — so a store with no price file cannot host any production
    or ticketing claim. The default therefore provisions one ACTIVE price file;
    the few scenarios that manage their own price-file rotation pass
    `with_price_file=False`.

    Catalog `sku`, `employee_number`, `asset_tag` and `file_label` are chain- or
    store-unique, so the identifiers are suffixed with the store number; that way
    a single test may stand up more than one store with this helper without the
    second receipt colliding with the first.

    Returns a namespace with: store, j1 (SUB on b1), j2 (COLD_CUT, MILK),
    j3 (COLD_CUT, MILK+WHEAT), j4 (COLD_CUT, cost 1000), b1 (BREAD),
    p1 (CATERING_PLATTER), a1 (DELI_CLERK), a2 (DELI_MANAGER),
    a3 (BAKERY_COORDINATOR), c_a1_sl, c_a1_fh, c_a3_fh, slicers (list).
    """
    store = create_store(
        store_number=store_number,
        name=store_name,
        deli_case_capacity_lbs=capacity,
        hot_bar_capacity_lbs=hot_bar_capacity,
        sub_station_count=sub_station_count,
    )
    sid = store["id"]
    tag = store_number

    b1 = create_bread_item(sku=f"BREAD-ITA-{tag}", name=f"Italian Roll {tag}")
    p1 = create_platter_item(sku=f"PLAT-CLASSIC-{tag}", name=f"Classic Platter {tag}")
    j1 = create_sub_item(bread_item_id=b1["id"], sku=f"SUBS-001-{tag}", name=f"Classic Sub {tag}")
    j2 = create_cold_cut_item(sku=f"CC-TURK-01-{tag}", name="Turkey Breast",
                              allergen_flags=["MILK"])
    j3 = create_cold_cut_item(
        sku=f"CC-TURK-02-{tag}", name="Turkey Wheat", allergen_flags=["MILK", "WHEAT"]
    )
    j4 = create_cold_cut_item(
        sku=f"CC-PROSC-01-{tag}",
        name="Prosciutto",
        unit_cost_cents=1000,
        retail_price_per_lb_cents=1499,
        case_life_minutes=120,
        allergen_flags=["MILK"],
    )

    a1 = create_associate(sid, employee_number=f"E-1001-{tag}", full_name="Ana One",
                          primary_role="DELI_CLERK", allergy_set=list(clerk_allergy_set))
    a2 = create_associate(sid, employee_number=f"E-1002-{tag}", full_name="Bea Two",
                          primary_role="DELI_MANAGER")
    a3 = create_associate(sid, employee_number=f"E-1003-{tag}", full_name="Cal Three",
                          primary_role="BAKERY_COORDINATOR")

    c_a1_sl = create_certification(sid, a1["id"], "SLICER_OPERATION")
    c_a1_fh = create_certification(sid, a1["id"], "FOOD_HANDLING")
    c_a3_fh = create_certification(sid, a3["id"], "FOOD_HANDLING")

    slicers = [
        create_slicer(sid, f"SL-{tag}-{i}", assigned_operator_id=a1["id"])
        for i in range(1, slicer_count + 1)
    ]

    price_file = setup_price_file(sid, file_label=f"PF-{tag}-0901") if with_price_file else None
    # Re-read the store so the namespace's `store` (and its `version`, which
    # callers hand back as an OCC token) reflects the post-setup state.
    store = get_store(sid)

    return SimpleNamespace(
        price_file=price_file,
        store=store,
        s=sid,
        j1=j1,
        j2=j2,
        j3=j3,
        j4=j4,
        b1=b1,
        p1=p1,
        a1=a1,
        a2=a2,
        a3=a3,
        c_a1_sl=c_a1_sl,
        c_a1_fh=c_a1_fh,
        c_a3_fh=c_a3_fh,
        slicers=slicers,
    )


def setup_two_stores(capacity_a=420, capacity_b=240, slicer_count=7):
    """Two stores' worth of catalog + staffing; returns namespaces keyed by store."""
    first = setup_deli_master_data(capacity=capacity_a, store_number="101", store_name="Store One",
                                   slicer_count=slicer_count)
    second = setup_deli_master_data(capacity=capacity_b, store_number="102", store_name="Store Two",
                                    slicer_count=0)
    return first, second


# --------------------------------------------------------------------------
# Tier 3: full lifecycle shortcuts
# --------------------------------------------------------------------------

def setup_price_file(store_id, file_label="PF-0901", effective_from="2026-09-01T00:00:00Z",
                     effective_to="2026-10-01T00:00:00Z", item_price_count=6, activate=True):
    payload = create_price_file_payload(
        store_id=store_id,
        file_label=file_label,
        effective_from=effective_from,
        effective_to=effective_to,
        item_price_count=item_price_count,
    )
    price_file = get_success_data(api_client.create_price_file(payload, scale_operator_headers()))
    if activate:
        price_file = get_success_data(
            api_client.activate_price_file(price_file["id"], scale_operator_headers())
        )
    return price_file


def setup_promo_bread_chain(
    store_id,
    bread_item_id,
    promo_item_id,
    promo_code="FEAT-0914",
    week_start="2026-09-07T00:00:00Z",
    week_end="2026-09-14T00:00:00Z",
    forecast_uplift_pct=0.1,
    trailing_baseline_units=600,
    committed_units=720,
    delivered_units=720,
    activate_promotion=True,
    submit=True,
    confirm=True,
    deliver=True,
    coordinator_id=None,
):
    """Promotion -> bread order -> submit -> confirm -> deliver.

    Returns (promotion, bread_order). The clock is sequenced through the chain's
    two disjoint PRD windows rather than parked in one of them:

      * PRD §3.5 requires submission to happen strictly before the promotion's
        `week_start_date` minus 48 hours, so the order is raised and submitted at
        `week_start - 72h`.
      * PRD §3.5 requires activation to happen inside the half-open week, so the
        clock then moves to `week_start` for the activate/confirm/deliver steps.

    Parking the clock at `week_start` for the whole chain would make `submit` a
    legal `ERR_LEAD_TIME_VIOLATED`, and parking it before the week would make
    `activate` a legal `ERR_INVALID_STATE`.
    """
    if submit:
        set_clock(dt_add_hours_iso(week_start, -72))
    promotion = get_success_data(
        api_client.create_promotion(
            create_promotion_payload(
                promo_code=promo_code,
                deli_item_id=promo_item_id,
                week_start_date=week_start,
                week_end_date=week_end,
                forecast_uplift_pct=forecast_uplift_pct,
                trailing_baseline_units=trailing_baseline_units,
            ),
            platform_admin_headers(),
        )
    )
    manager_id = coordinator_id or _fallback_manager_id(store_id)
    bread_headers = coordinator_headers(
        coordinator_id or _fallback_coordinator_id(store_id)
    )
    # The order is raised and submitted while the clock still sits behind the
    # 48-hour lead-time wall (PRD §3.5 makes `submit_by_at` a hard wall).
    order = get_success_data(
        api_client.create_bread_order(
            create_bread_order_payload(
                store_id=store_id,
                bread_deli_item_id=bread_item_id,
                promotion_id=promotion["id"],
                committed_units=committed_units,
            ),
            bread_headers,
        )
    )
    if submit:
        order = get_success_data(api_client.submit_bread_order(order["id"], bread_headers))

    if activate_promotion:
        # Activation is legal only inside the half-open week (PRD §3.5), which is
        # entirely after the submit wall.
        set_clock(week_start)
        promotion = get_success_data(
            api_client.activate_promotion(promotion["id"], manager_headers(manager_id))
        )
    if confirm:
        promotion_now = get_success_data(api_client.get_promotion(promotion["id"], platform_admin_headers()))
        order = get_success_data(
            api_client.confirm_bread_order(order["id"], promotion_now["version"], bread_headers)
        )
    if deliver:
        order = get_success_data(
            api_client.deliver_bread_order(order["id"], delivered_units, bread_headers)
        )
    return promotion, order


def _fallback_manager_id(store_id):
    """Pick any DELI_MANAGER associate of the store when the caller did not name one."""
    listing = _list_all(api_client.list_associates, {"store_id": store_id, "primary_role": "DELI_MANAGER"})
    assert listing, f"no DELI_MANAGER associate exists for store {store_id}"
    return listing[-1]["id"]


def _fallback_coordinator_id(store_id):
    """Pick any BAKERY_COORDINATOR associate of the store."""
    listing = _list_all(
        api_client.list_associates, {"store_id": store_id, "primary_role": "BAKERY_COORDINATOR"}
    )
    assert listing, f"no BAKERY_COORDINATOR associate exists for store {store_id}"
    return listing[-1]["id"]


def _list_all(list_fn, params):
    """Read a filtered collection, following pagination until it is exhausted."""
    headers = platform_admin_headers()
    collected = []
    offset = 0
    while True:
        params_with_offset = dict(params or {})
        params_with_offset["offset"] = offset
        params_with_offset["limit"] = 100
        body = list_fn(headers, params_with_offset).json()
        collected.extend(body["data"])
        meta = body.get("meta", {})
        if not meta.get("has_more"):
            return collected
        offset += len(body["data"]) or 1


def setup_ticket_ticketed(master, half_lb_units=4, channel="DIGITAL", request_index=1, on_item=None):
    """Create a sub ticket and ticket it. Returns the TICKETED ticket."""
    item = on_item or master.j2
    ticket = get_success_data(
        api_client.create_sub_ticket(
            create_sub_ticket_payload(
                store_id=master.s,
                deli_item_id=master.j1["id"],
                bread_deli_item_id=master.b1["id"],
                order_channel=channel,
                lines=[{"deli_item_id": item["id"], "half_lb_units": half_lb_units, "line_sequence_number": 1}],
            ),
            clerk_headers(master.a1["id"]),
        )
    )
    return get_success_data(
        api_client.ticket_sub_ticket(ticket["id"], clerk_headers(master.a1["id"]))
    )


def setup_ticket_completed(master, net_weight_lbs=2, half_lb_units=4, channel="IN_STORE"):
    """Create -> ticket -> complete. Returns the COMPLETED ticket."""
    ticket = setup_ticket_ticketed(master, half_lb_units=half_lb_units, channel=channel)
    return get_success_data(
        api_client.complete_sub_ticket(
            ticket["id"], net_weight_lbs, clerk_headers(master.a1["id"])
        )
    )


def setup_waste_discarded(master, batch, discard_lbs, reason="QUALITY", markdown_by=None):
    """Open a waste record against a batch whose markdown window is closed, then discard it."""
    markdown_by = markdown_by or master.a2["id"]
    record = create_waste_record(
        master.s, batch["id"], markdown_by, reason=reason, acting_associate_id=master.a1["id"]
    )
    return discard_waste_record(record["id"], discard_lbs, master.a1["id"])


def setup_waste_verified(master, batch, discard_lbs, verifier=None, certification_id=None,
                         reason="QUALITY", markdown_by=None, acting_manager_id=None):
    """Discard then verify. Returns the VERIFIED waste record."""
    record = setup_waste_discarded(master, batch, discard_lbs, reason=reason, markdown_by=markdown_by)
    verifier = verifier or master.a3["id"]
    certification_id = certification_id or master.c_a3_fh["id"]
    acting_manager_id = acting_manager_id or master.a2["id"]
    return verify_waste_record(
        record["id"], verifier, certification_id, batch["id"], acting_manager_id
    )


def setup_catering_confirmed(master, platter_count=3, headcount=8, lead_time_hours=30,
                             pickup_window_start="2026-09-03T15:00:00Z",
                             pickup_window_end="2026-09-03T15:45:00Z",
                             request_id="REQ-K1", confirm=True, planner_id=None, customer_name="Northside PTA"):
    """Create a catering inquiry (optionally confirming it)."""
    payload = create_catering_order_payload(
        store_id=master.s,
        platter_deli_item_id=master.p1["id"],
        customer_name=customer_name,
        platter_count=platter_count,
        headcount=headcount,
        lead_time_hours=lead_time_hours,
        pickup_window_start=pickup_window_start,
        pickup_window_end=pickup_window_end,
        certified_planner_associate_id=planner_id or master.a1["id"],
        request_id=request_id,
    )
    order = get_success_data(api_client.create_catering_order(payload, clerk_headers(master.a1["id"])))
    if confirm:
        order = get_success_data(
            api_client.confirm_catering_order(order["id"], clerk_headers(master.a1["id"]))
        )
    return order


def setup_catering_ready(master, **overrides):
    """Inquiry -> confirm -> start production -> mark ready."""
    order = setup_catering_confirmed(master, **overrides)
    order = get_success_data(
        api_client.start_catering_production(order["id"], clerk_headers(master.a1["id"]))
    )
    return get_success_data(
        api_client.mark_catering_ready(order["id"], clerk_headers(master.a1["id"]))
    )


# --------------------------------------------------------------------------
# Tier 4: accumulation / threshold targeting
# --------------------------------------------------------------------------

def produce_case_stock(master, item, pounds_list, associate_id=None, code_prefix="B-",
                       slicer_id=None, start_index=1):
    """Produce one batch per weight so the store accumulates the exact case weight."""
    associate_id = associate_id or master.a1["id"]
    batches = []
    for offset, pounds in enumerate(pounds_list):
        batch = produce_batch(
            master.s,
            item["id"],
            associate_id,
            f"{code_prefix}{start_index + offset:03d}",
            pounds,
            produced_lbs=pounds,
            slicer_id=slicer_id,
        )
        batches.append(batch)
    return batches


def setup_waste_records_open(master, count=3, item=None, associate_id=None, pounds=5.0,
                             reason="QUALITY", code_prefix="B-9"):
    """Produce `count` batches and open one still-unverified waste record each.

    Every record stays in DRAFT, which is one of the statuses the store counts
    toward its pending-verification backlog.
    """
    item = item or master.j1
    associate_id = associate_id or master.a1["id"]
    batches = []
    for index in range(1, count + 1):
        batch = produce_batch(
            master.s, item["id"], associate_id, f"{code_prefix}{index:02d}", pounds,
            produced_lbs=pounds,
        )
        batches.append(batch)
    records = [
        create_waste_record(master.s, batch["id"], master.a2["id"], reason=reason,
                            acting_associate_id=associate_id)
        for batch in batches
    ]
    return batches, records


def setup_case_stock_at(master, target_lbs, item=None, associate_id=None, slicer_id=None):
    """Accumulate exactly `target_lbs` of HOLDING case stock in one batch."""
    item = item or master.j1
    return produce_batch(
        master.s,
        item["id"],
        associate_id or master.a1["id"],
        "B-STOCK",
        target_lbs,
        produced_lbs=target_lbs,
        slicer_id=slicer_id,
    )


def setup_store_restricted_by_inventory(master, mutating_associate_id=None):
    """Push case_on_hand_lbs past the store's capacity so posture reads RESTRICTED."""
    return produce_case_stock(
        master,
        master.j1,
        [master.store["deli_case_capacity_lbs"] + 1.0],
        associate_id=mutating_associate_id,
        code_prefix="B-OV",
    )


# --------------------------------------------------------------------------
# Tier 5: finalization / terminal states
# --------------------------------------------------------------------------

def halt_store_via_gate(master, manager_id=None):
    """Force posture to HALT with reason POSTURE_GATE_TRIGGERED."""
    manager_id = manager_id or master.a2["id"]
    return get_success_data(
        api_client.set_posture_gate(master.s, True, manager_headers(manager_id))
    )


def cancel_catering_from_ready(master, manager_id=None, **overrides):
    """Ready -> CANCELLED, which synthesizes the excluded unclaimed-platter record."""
    order = setup_catering_ready(master, **overrides)
    return get_success_data(
        api_client.cancel_catering_order(
            order["id"], "customer never collected", manager_headers(manager_id or master.a2["id"])
        )
    )


def supersede_price_file(store_id, first, second_label="PF-0902",
                         effective_from="2026-09-02T06:00:00Z",
                         effective_to="2026-10-01T00:00:00Z", item_price_count=8):
    """Activate a successor price file, superseding the incumbent."""
    successor = setup_price_file(
        store_id,
        file_label=second_label,
        effective_from=effective_from,
        effective_to=effective_to,
        item_price_count=item_price_count,
        activate=False,
    )
    return get_success_data(api_client.activate_price_file(successor["id"], scale_operator_headers()))


def issue_standalone_label(store_id, subject_ref_id, net_weight_lbs=2, unit_price_cents=1800,
                           subject_type="PRODUCTION_BATCH"):
    return get_success_data(
        api_client.create_label(
            create_label_payload(
                store_id=store_id,
                subject_type=subject_type,
                subject_ref_id=subject_ref_id,
                net_weight_lbs=net_weight_lbs,
                unit_price_cents=unit_price_cents,
            ),
            scale_operator_headers(),
        )
    )


def open_sanitation_cycle(store_id, slicer_id, acting_associate_id, cycle_type="ROUTINE",
                          cycle_minutes=10, **overrides):
    payload = create_sanitation_cycle_payload(
        store_id=store_id,
        slicer_id=slicer_id,
        cycle_type=cycle_type,
        cycle_minutes=cycle_minutes,
        **overrides,
    )
    return get_success_data(api_client.create_sanitation_cycle(payload, clerk_headers(acting_associate_id)))