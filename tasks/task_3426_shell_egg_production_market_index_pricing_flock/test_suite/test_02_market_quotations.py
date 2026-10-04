"""Market quotation publication: source default, append-only shape, and the
uniqueness quadruple.
"""

from test_helpers import (
    ADMIN,
    api_client,
    assert_instant_equal,
    assert_market_quotation,
    publish_quotation,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import ApiErrorId as ERR


def test_quotation_omitting_source_defaults_to_urner_barry(api):
    """Omitting source stores URNER_BARRY; a USDA_AMS observation at the same
    slot is a different key and is accepted.

    PRD §3.4: "an optional `source` defaulting to `URNER_BARRY` with
    `USDA_AMS` as the alternative. The four-tuple of region, size class,
    effective date, and source is unique; a duplicate is rejected with
    `ERR_DUPLICATE_QUOTATION`."

    Design: Corner/entities/quotation_omitting_source_defaults_to_urner_barry
    """
    set_clock("2026-09-01T00:00:00Z")
    first = validate_success(
        api.create_market_quotation(
            {
                "region_code": "MIDWEST",
                "size_class": "LARGE",
                "price_cents_per_dozen": 150,
                "effective_date": "2026-09-07T00:00:00Z",
            },
            ADMIN,
        ),
        201,
    )
    assert_market_quotation(first)
    assert first["source"] == "URNER_BARRY"

    second = validate_success(
        api.create_market_quotation(
            {
                "region_code": "MIDWEST",
                "size_class": "LARGE",
                "price_cents_per_dozen": 152,
                "effective_date": "2026-09-07T00:00:00Z",
                "source": "USDA_AMS",
            },
            ADMIN,
        ),
        201,
    )
    assert_market_quotation(second)
    assert second["source"] == "USDA_AMS"


def test_market_quotation_has_no_version_or_updated_at(api):
    """The append-only quotation carries only id and created_at among
    system-managed fields.

    PRD §2.5: "The market quotation is the deliberate exception: quotations
    are append-only observations, so a quotation carries only `id` and
    `created_at`; both `updated_at` and `version` are absent from it."
    PRD §2.4: "Every `created_at` and `updated_at` stamp, every validation
    window, and every calculation in this document reads this clock."

    Design: Corner/entities/market_quotation_has_no_version_or_updated_at
    """
    set_clock("2026-09-01T00:00:00Z")
    publish_quotation(
        region_code="WEST", size_class="JUMBO", price_cents_per_dozen=210,
        effective_date="2026-09-01T00:00:00Z",
    )

    rows, meta = validate_paginated(
        api.list_market_quotations(
            ADMIN, params={"region_code": "WEST", "size_class": "JUMBO"}
        )
    )
    assert meta["total_count"] == 1
    row = rows[0]
    assert_market_quotation(row)
    assert row["price_cents_per_dozen"] == 210
    assert_instant_equal(row["created_at"], "2026-09-01T00:00:00Z", "created_at")


def test_duplicate_quotation_slot_returns_409(api):
    """Republishing the same (region, size, effective_date, source) is a 409.

    PRD §3.4: "The four-tuple of region, size class, effective date, and
    source is unique; a duplicate is rejected with `ERR_DUPLICATE_QUOTATION`."

    Design: Corner/validations/duplicate_quotation_slot_returns_409
    """
    set_clock("2026-09-01T00:00:00Z")
    publish_quotation(
        region_code="MIDWEST", size_class="LARGE", price_cents_per_dozen=150,
        effective_date="2026-09-07T00:00:00Z",
    )

    response = api.create_market_quotation(
        {
            "region_code": "MIDWEST",
            "size_class": "LARGE",
            "price_cents_per_dozen": 151,
            "effective_date": "2026-09-07T00:00:00Z",
            "source": "URNER_BARRY",
        },
        ADMIN,
    )
    validate_error(response, ERR.ERR_DUPLICATE_QUOTATION)

    rows, meta = validate_paginated(
        api.list_market_quotations(
            ADMIN, params={"region_code": "MIDWEST", "size_class": "LARGE"}
        )
    )
    assert meta["total_count"] == 1 and len(rows) == 1
