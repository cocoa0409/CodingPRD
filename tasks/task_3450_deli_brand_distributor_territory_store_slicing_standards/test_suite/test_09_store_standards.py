"""In-store slicer standards: allergen separation at product opening (PRD §3.5)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_opened_log,
    create_opened_log_payload,
    create_product,
    create_slicer,
    create_visit,
    make_retail_manager_headers,
    set_clock,
    setup_approved_account,
    submit_visit,
    validate_error,
)

ADMIN = TEST_USERS["brand_admin_headers"]


def _setup_cleaned_slicer(product_overrides):
    """Approved account, product, a NON-dedicated slicer S1 freshly cleaned by a
    visit submission (cleaning_verified_at stamped at the 2026-09-01T00:00:00Z clock
    default), and the clock advanced so later openings are backdated."""
    ctx = setup_approved_account()
    product = create_product(code="P1", **product_overrides)
    slicer = create_slicer(ctx["account"], label="S1", dedicated_allergen="NONE")
    visit = create_visit(ctx["account"], ctx["distributor"],
                         "2026-09-02T09:00:00Z", "2026-09-02T10:00:00Z")
    submit_visit(visit, ctx["distributor"], score=90, cleaned_slicer_ids=[slicer["id"]])
    set_clock("2026-09-03T00:00:00Z")  # opened_at values below are backdates (§3.5)
    return ctx, product, slicer


def test_dedicated_slicer_required_overrides_cleaning_window(api):
    """PRD §3.5: "Allergen separation is enforced at opening, and a violation is
    refused with `ERR_ALLERGEN_CROSS_CONTACT`: the slicer must be `ACTIVE` and belong
    to the same account as the caller; if the product's `requires_dedicated_slicer`
    is true, the slicer's `dedicated_allergen` must be one of the product's
    `allergen_tags`; otherwise, whenever `allergen_tags` is non-empty, the slicer
    must either be dedicated to one of those allergens or have a
    `cleaning_verified_at` no earlier than 24 hours before the `opened_at`."

    For a flagged product the dedication rule overrides the cleaning-window
    fallback: the freshly cleaned non-dedicated slicer still fails, while the
    MILK-dedicated slicer accepts the opening.

    Design: Corner/validations/dedicated_slicer_required_for_flagged_allergen_product
    """
    ctx, product, slicer = _setup_cleaned_slicer({
        "name": "Cheese", "base_price_cents": 800, "shelf_life_opened_hours": 24,
        "shelf_life_unopened_days": 60, "allergen_tags": ["MILK"],
        "requires_dedicated_slicer": True,
    })
    dedicated = create_slicer(ctx["account"], label="S2", dedicated_allergen="MILK")

    resp = api.create_opened_product_log(
        create_opened_log_payload(product["id"], slicer["id"],
                                  opened_at="2026-09-02T11:00:00Z"),
        make_retail_manager_headers(ctx["account"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_ALLERGEN_CROSS_CONTACT)

    log = create_opened_log(ctx["account"], product, dedicated,
                            opened_at="2026-09-02T11:00:00Z")
    assert log["status"] == "OPEN", "a MILK-dedicated slicer satisfies the rule"


def test_allergen_cleaning_window_twenty_four_hour_boundary(api):
    """PRD §3.5: "otherwise, whenever `allergen_tags` is non-empty, the slicer must
    either be dedicated to one of those allergens or have a `cleaning_verified_at` no
    earlier than 24 hours before the `opened_at`." and "a violation is refused with
    `ERR_ALLERGEN_CROSS_CONTACT`".

    The slicer was cleaned at 2026-09-01T00:00:00Z: an opening 25 hours later
    (2026-09-02T01:00:00Z) falls outside the window and is refused, while one 23
    hours later (2026-09-01T23:00:00Z) is inside it and opens.

    Design: Corner/validations/allergen_cleaning_window_24_hour_boundary
    """
    ctx, product, slicer = _setup_cleaned_slicer({
        "name": "Turkey", "base_price_cents": 800, "shelf_life_opened_hours": 48,
        "shelf_life_unopened_days": 21, "allergen_tags": ["MILK"],
    })

    resp = api.create_opened_product_log(
        create_opened_log_payload(product["id"], slicer["id"],
                                  opened_at="2026-09-02T01:00:00Z"),
        make_retail_manager_headers(ctx["account"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_ALLERGEN_CROSS_CONTACT)  # 25h after cleaning

    log = create_opened_log(ctx["account"], product, slicer,
                            opened_at="2026-09-01T23:00:00Z")  # 23h after cleaning
    assert log["status"] == "OPEN", "cleaning within 24 hours of opened_at passes"
