"""Corner coverage of entity defaults, required fields, and the immutable log."""

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_waste_log,
    fixtures,
    factories,
    make_manager_headers,
    make_shift_lead_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_store_day_create_missing_business_date_returns_400(client):
    """The create payload without business_date is rejected 400 and no row exists.

    "creating a store day identified by its `business_date`, a `YYYY-MM-DD` UTC
    calendar date that must be unique across all store days"

    Design: Corner/entities/store_day_create_missing_business_date_returns_400
    """
    resp = client.create_store_day({}, make_manager_headers())
    validate_error(resp, ApiErrorId.ERR_VALIDATION)

    rows, meta = validate_paginated(client.list_store_days(make_manager_headers()))
    assert meta["total_count"] == 0


def test_product_defaults_applied_when_optional_fields_omitted(client):
    """customization_allowed defaults false, promo_locked starts false.

    "an optional `promo_price_cents`, and a `customization_allowed` flag that
    defaults to false"
    "The derived `promo_locked` flag is true while any `OPEN` store day has a
    daypart carrying a production run that references this product and has not
    yet reached `CLOSED`."

    Design: Corner/entities/product_defaults_applied_when_optional_fields_omitted
    """
    product = validate_success(
        client.create_product(
            factories.product_payload(), make_manager_headers()
        ),
        201,
    )
    assert product["customization_allowed"] is False
    assert product["promo_locked"] is False
    assert product.get("promo_price_cents") is None


def test_store_day_create_ignores_computed_produced_units_input(client):
    """A client-supplied produced_units does not survive creation: the day is
    born with zero production.

    "The new day starts in `PLANNING` status with its counters
    (`produced_units`, `sold_units`, `discarded_units`, `donated_units`) all at
    zero and both waste percentages at 0.0."

    Design: Corner/entities/store_day_create_extra_computed_field_ignored_input
    """
    created = validate_success(
        client.create_store_day(
            {"business_date": "2026-10-01", "produced_units": 99},
            make_manager_headers(),
        ),
        201,
    )
    assert created["produced_units"] == 0
    assert created["status"] == "PLANNING"


def test_store_day_get_nonexistent_returns_not_found(client):
    """A well-formed but unknown id resolves to the store-day 404.

    "the request is rejected with the 404 error corresponding to the first
    identifier that does not resolve — `ERR_STORE_DAY_NOT_FOUND`"

    Design: Corner/entities/store_day_get_nonexistent_returns_not_found
    """
    resp = client.get_store_day(NON_EXISTENT_UUID, make_manager_headers())
    validate_error(resp, ApiErrorId.ERR_STORE_DAY_NOT_FOUND)


def test_waste_log_rows_are_immutable_audit_appends(client):
    """A manual discard appends exactly one WasteLog row (quantity 1, donated
    from input) and the row carries no updated_at or version.

    "appends exactly one `WasteLog` row per unit — the row's `quantity` is
    always 1 — capturing the `store_day_id`, the `daypart_id` of the discarded
    unit's run, the `hold_unit_id`, the `reason`, the `donated` flag (taken from
    the operator's input on a manual discard; always false for sweeps and
    automatic discards), and a `logged_at` clock stamp."
    "A `WasteLog` row is an immutable audit append: it carries `id` and
    `created_at`, but `updated_at` and `version` are absent entirely."

    Design: Corner/entities/waste_log_immutable_entity_has_no_mutation_surface
    """
    bundle = fixtures.open_day_with_stock(
        client, "2026-10-02", active_at="10:35:00Z", run_quantity=2, batch_size=5
    )
    units = fixtures.holding_units(client, bundle.run["id"])
    fixtures.get_success_data(
        client.discard_hold_unit(
            units[0]["id"], {"reason": "DAMAGED", "donated": True},
            make_shift_lead_headers(),
        )
    )

    logs, meta = validate_paginated(
        client.list_waste_logs_of(bundle.store_day["id"], make_manager_headers())
    )
    assert meta["total_count"] == 1
    row = logs[0]
    assert_waste_log(row)
    assert row["reason"] == "DAMAGED"
    assert row["donated"] is True
    assert row["hold_unit_id"] == units[0]["id"]
    assert row["store_day_id"] == bundle.store_day["id"]
    assert row["daypart_id"] == bundle.daypart["id"]
