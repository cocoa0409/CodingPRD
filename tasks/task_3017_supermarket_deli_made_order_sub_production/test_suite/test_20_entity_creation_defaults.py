"""Creation-time defaults and derived fields on the catalog and store rows."""

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    api_client,
    clerk_headers,
    create_batch_payload,
    create_catering_order_payload,
    create_item_payload,
    create_label_payload,
    create_store_payload,
    create_sub_ticket_payload,
    get_success_data,
    platform_admin_headers,
    scale_operator_headers,
    set_clock,
    setup_deli_master_data,
    setup_price_file,
    validate_error,
    validate_success,
)


def test_store_create_returns_derived_posture_and_zero_counters():
    """PRD §3.1: "A new store is provisioned at `posture` `OPEN` and
    `posture_reason` `OK`, with `case_on_hand_lbs` at 0, its `ops_run_index`
    production-day counter at 0, and its `version` at 1."
    PRD §2.6: posture "is not set directly by clients; it is computed from the
    store's own counters and flags ... If the store's
    `certified_slicer_operator_count` is zero ... the posture is `HALT` with
    reason `CERTIFICATION_TRIGGERED`", so only the counters PRD §3.1 pins are
    checked here — a later read of a store with no staff derives HALT, which is
    the predicate PRD §2.6 declares.
    PRD §2.4: "The `id` field is a server-minted UUID string with no type prefix;
    the identifier `store_id` is never a component of it."

    Design: Corner/entities/store_create_returns_derived_posture_and_zero_counters
    """
    set_clock("2026-09-02T06:00:00Z")
    created = validate_success(
        api_client.create_store(
            create_store_payload(store_number="101", name="Store One", deli_case_capacity_lbs=300,
                                 hot_bar_capacity_lbs=60, sub_station_count=2),
            platform_admin_headers(),
        ),
        expected_status=201,
    )
    assert not str(created["id"]).startswith("store_")
    assert created["case_on_hand_lbs"] == 0 and created["ops_run_index"] == 0
    assert created["certified_slicer_operator_count"] == 0
    assert created["version"] == 1

    report = validate_success(api_client.get_posture_report(created["id"], platform_admin_headers()))
    assert report["protection_index"] == 100 and report["diffusion_index"] == 0

def test_deli_item_applies_the_platter_default_and_keeps_the_bread_link_null_for_non_subs():
    """PRD §3.1: "A platter item contributes `servings_per_platter` servings per
    unit, defaulting to 12."
    PRD §3.1: "A sub item names the `bread_deli_item_id` it is served on, and that
    referenced row must itself carry `category` `BREAD`; non-sub items leave the
    field null."

    Design: Corner/entities/deli_item_defaults_and_bread_link
    """
    set_clock("2026-09-02T06:00:00Z")
    bread = get_success_data(
        api_client.create_item(
            create_item_payload(sku="BREAD-ITA", name="Italian Roll", category="BREAD",
                                unit_cost_cents=120, retail_price_per_lb_cents=250,
                                case_life_minutes=720, markdown_window_minutes=60,
                                allergen_flags=["WHEAT"], slicer_required=False),
            platform_admin_headers(),
        )
    )
    platter = get_success_data(
        api_client.create_item(
            {k: v for k, v in create_item_payload(
                sku="PLAT-CLASSIC", name="Classic Platter", category="CATERING_PLATTER",
                unit_cost_cents=900, retail_price_per_lb_cents=1800, case_life_minutes=480,
                markdown_window_minutes=60, allergen_flags=["MILK", "WHEAT"], slicer_required=False,
            ).items() if k != "bread_deli_item_id"},
            platform_admin_headers(),
        )
    )
    cold_cut = get_success_data(
        api_client.create_item(
            {k: v for k, v in create_item_payload(
                sku="CC-TURK-01", name="Turkey Breast", category="COLD_CUT", unit_cost_cents=520,
                retail_price_per_lb_cents=899, case_life_minutes=180, markdown_window_minutes=30,
                allergen_flags=["MILK"], slicer_required=True,
            ).items() if k != "bread_deli_item_id"},
            platform_admin_headers(),
        )
    )
    sub = get_success_data(
        api_client.create_item(
            create_item_payload(sku="SUBS-001", name="Classic Sub", category="SUB",
                                unit_cost_cents=480, retail_price_per_lb_cents=799,
                                case_life_minutes=240, markdown_window_minutes=30,
                                allergen_flags=["WHEAT"], slicer_required=False,
                                bread_deli_item_id=bread["id"]),
            platform_admin_headers(),
        )
    )

    platter_now = validate_success(api_client.get_item(platter["id"], platform_admin_headers()))
    assert platter_now["servings_per_platter"] == 12, "the platter default was applied"
    cold_cut_now = validate_success(api_client.get_item(cold_cut["id"], platform_admin_headers()))
    assert cold_cut_now["bread_deli_item_id"] is None
    sub_now = validate_success(api_client.get_item(sub["id"], platform_admin_headers()))
    assert sub_now["bread_deli_item_id"] == bread["id"]

    listing = api_client.list_items(platform_admin_headers(), {"bread_deli_item_id": bread["id"]})
    rows = listing.json()["data"]
    assert [row["id"] for row in rows] == [sub["id"]], (
        "the bread-parent filter returns exactly the one sub built on that roll"
    )


def test_batch_creation_ignores_client_supplied_computed_dimensions():
    """PRD §3.1: "A fresh batch starts at `PLANNED` on the first dimension and
    `HOLDING` on the second, with `produced_lbs` at 0."
    PRD §2.4: "the only read-only quantities are derived ones, which clients may
    read but never supply."

    Design: Corner/entities/production_batch_ignores_client_supplied_computed_fields
    """
    set_clock("2026-09-02T06:00:00Z")
    master = setup_deli_master_data(slicer_count=1)
    created = validate_success(
        api_client.create_batch(
            create_batch_payload(
                store_id=master.s, deli_item_id=master.j1["id"],
                produced_by_associate_id=master.a1["id"], batch_code="B-001", planned_lbs=9,
            ),
            clerk_headers(master.a1["id"]),
        ),
        expected_status=201,
    )
    assert created["produced_lbs"] == 0
    assert created["production_status"] == "PLANNED"
    assert created["hold_status"] == "HOLDING"
    assert created["produced_at"] is None and created["hold_expires_at"] is None


def test_label_rejects_an_over_the_limit_weight_and_prices_a_valid_one():
    """PRD §3.6: "A standalone label request supplies the weight and the unit price
    directly and is refused with `ERR_LABEL_WEIGHT_EXCEEDED` when the weight is
    zero, negative, or above 10 pounds; that bound is the scale-lock limit."
    PRD §3.6: "a derived `total_price_cents` equal to the net weight multiplied by
    the unit price, rounded half up to a whole cent."

    Design: Corner/entities/label_rejects_client_supplied_total_and_zero_weight
    """
    set_clock("2026-09-02T06:00:00Z")
    master = setup_deli_master_data(slicer_count=1)

    over = api_client.create_label(
        create_label_payload(store_id=master.s, subject_type="PRODUCTION_BATCH",
                             subject_ref_id=master.b1["id"], net_weight_lbs=10.01,
                             unit_price_cents=899),
        scale_operator_headers(),
    )
    validate_error(over, ApiErrorId.ERR_LABEL_WEIGHT_EXCEEDED)

    zero = api_client.create_label(
        create_label_payload(store_id=master.s, subject_type="PRODUCTION_BATCH",
                             subject_ref_id=master.b1["id"], net_weight_lbs=0,
                             unit_price_cents=899),
        scale_operator_headers(),
    )
    validate_error(zero, ApiErrorId.ERR_LABEL_WEIGHT_EXCEEDED)

    ok = validate_success(
        api_client.create_label(
            create_label_payload(store_id=master.s, subject_type="PRODUCTION_BATCH",
                                 subject_ref_id=master.b1["id"], net_weight_lbs=1.234,
                                 unit_price_cents=899),
            scale_operator_headers(),
        ),
        expected_status=201,
    )
    assert ok["total_price_cents"] == 1109, "1.234 lbs at 899 cents rounds half up to 1109"


def test_empty_ticket_is_refused_while_a_one_line_ticket_gets_the_first_sequence():
    """PRD §3.4: "A ticket must carry at least one line and every line's
    `half_lb_units` must be at least 1; an empty ticket is rejected with
    `ERR_EMPTY_CART`."
    PRD §3.4: "Creation places the ticket at `QUEUED` on both, and assigns a
    per-store `creation_sequence` and a customer-facing `ticket_number` equal to
    it, monotonically increasing within the store."

    Design: Corner/entities/sub_ticket_requires_lines_and_defaults_channel_sequence
    """
    set_clock("2026-09-02T06:00:00Z")
    master = setup_deli_master_data(slicer_count=1)
    price_file = master.price_file

    empty = api_client.create_sub_ticket(
        create_sub_ticket_payload(
            store_id=master.s, deli_item_id=master.j1["id"], bread_deli_item_id=master.b1["id"],
            order_channel="DIGITAL", lines=[],
        ),
        clerk_headers(master.a1["id"]),
    )
    validate_error(empty, ApiErrorId.ERR_EMPTY_CART)

    created = validate_success(
        api_client.create_sub_ticket(
            create_sub_ticket_payload(
                store_id=master.s, deli_item_id=master.j1["id"], bread_deli_item_id=master.b1["id"],
                order_channel="PHONE",
                lines=[{"deli_item_id": master.j2["id"], "half_lb_units": 3,
                        "line_sequence_number": 1}],
            ),
            clerk_headers(master.a1["id"]),
        ),
        expected_status=201,
    )
    assert created["creation_sequence"] == 1 and created["ticket_number"] == 1
    assert created["status"] == "QUEUED"
    assert created["weight_lbs"] == 1.5
    assert created["order_channel"] == "PHONE"
    assert created.get("placed_by_customer_ref") is None


def test_catering_order_is_invisible_from_another_stores_scope():
    """PRD §2.12: "a resource that exists but sits under a different store is
    reported not as a permission problem but as `ERR_NOT_FOUND`, because scope
    disagreement is treated as non-existence."
    PRD §2.11: "Existence of the addressed resource under that store follows, with
    `ERR_NOT_FOUND` for `id`-addressed resources."

    Design: Corner/entities/catering_order_not_found_on_wrong_store_scope
    """
    set_clock("2026-09-02T06:00:00Z")
    first = setup_deli_master_data(capacity=420, store_number="101", store_name="Store One",
                                   slicer_count=1)
    second = setup_deli_master_data(capacity=240, store_number="102", store_name="Store Two",
                                    slicer_count=0)

    order = get_success_data(
        api_client.create_catering_order(
            create_catering_order_payload(
                store_id=first.s, platter_deli_item_id=first.p1["id"],
                certified_planner_associate_id=first.a1["id"], request_id="REQ-K1",
            ),
            clerk_headers(first.a1["id"]),
        )
    )

    wrong = api_client.list_catering_orders(
        clerk_headers(first.a1["id"]), {"store_id": second.s, "status": "INQUIRY"}
    )
    assert wrong.json()["data"] == [], "the order belongs to its owning store, not this one"

    right = api_client.list_catering_orders(
        clerk_headers(first.a1["id"]), {"store_id": first.s, "status": "INQUIRY"}
    )
    assert [row["id"] for row in right.json()["data"]] == [order["id"]]

    missing = api_client.get_catering_order(NON_EXISTENT_UUID, clerk_headers(first.a1["id"]))
    validate_error(missing, ApiErrorId.ERR_NOT_FOUND)