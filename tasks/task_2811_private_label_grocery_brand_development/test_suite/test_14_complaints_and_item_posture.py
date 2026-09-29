"""Life on the shelf: weighted complaint points, the inclusive WATCH boundary and
the retailer's denominator walking the posture in both directions."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_append_only,
    assert_instant_equals,
    assert_item_state,
    assert_two_decimal_value,
    assert_version_is,
)
from test_helpers.constants import (
    DEFAULT_CLOCK,
    ITEM_CONCEPT,
    ITEM_SOURCED,
    POSTURE_GREEN,
    POSTURE_PROBATION,
    POSTURE_WATCH,
    SEVERITY_CRITICAL,
    SEVERITY_MAJOR,
)
from test_helpers.fixtures import (
    add_complaint,
    build_chain,
    read_item,
    read_supplier,
)
from test_helpers.test_users import (
    QUALITY_HEADERS,
    REGULATORY_HEADERS,
    SOURCING_HEADERS,
)


def _ppm_and_posture(api, item_id):
    item = read_item(api, item_id)
    return item["complaint_ppm_90d"], item["quality_posture"]


def test_two_weighted_points_over_fifty_thousand_units_stay_green(api):
    """40.00 is below the inclusive 60.00 boundary, so the posture does not move.

    PRD 3.8: "Otherwise `complaint_ppm_90d` is the weighted point total multiplied by
    1,000,000 and divided by `trailing_90d_units`, rounded half up to two decimals.
    From that figure the recomputed posture is `PROBATION` when the parts-per-million
    figure is at least 150.00, otherwise `WATCH` when it is at least 60.00, otherwise
    `GREEN`."

    PRD 3.8: "counting five points for each `CRITICAL` complaint, two for each `MAJOR`
    and one for each `MINOR`"

    Design: Difficulty/boundary_precision_check/complaint_ppm_exactly_sixty_is_watch
    """
    ctx = build_chain(api, upto=10)
    assert read_item(api, ctx["item_id"])["trailing_90d_units"] == 50000

    major = add_complaint(api, ctx["item_id"], factory=f.major_complaint_payload)

    assert major["severity"] == SEVERITY_MAJOR
    ppm, posture = _ppm_and_posture(api, ctx["item_id"])
    assert_two_decimal_value(ppm, 40.00, "complaint_ppm_90d")
    assert posture == POSTURE_GREEN, "two points over 50000 units is not yet WATCH"
    assert_item_state(read_item(api, ctx["item_id"]), ITEM_CONCEPT, POSTURE_GREEN)


def test_three_weighted_points_read_exactly_sixty_and_trip_watch(api):
    """The third point lands the figure exactly on the threshold, which is inclusive.

    PRD 3.8: "From that figure the recomputed posture is `PROBATION` when the
    parts-per-million figure is at least 150.00, otherwise `WATCH` when it is at least
    60.00, otherwise `GREEN`."

    PRD 3.8: "Fifty thousand trailing units carrying one `CRITICAL`, one `MAJOR` and
    one `MINOR` complaint accumulate eight points, read 160.00 and land on `PROBATION`;
    drop the critical complaint and the same units read exactly 60.00 and land on
    `WATCH` at the inclusive boundary."

    PRD 3.8: "The server stamps `received_at` with the logical clock's current
    instant, which is also the row's `created_at`."

    Design: Difficulty/boundary_precision_check/complaint_ppm_exactly_sixty_is_watch
    """
    ctx = build_chain(api, upto=10)
    add_complaint(api, ctx["item_id"], factory=f.major_complaint_payload)

    minor = add_complaint(api, ctx["item_id"], factory=f.minor_complaint_payload)

    ppm, posture = _ppm_and_posture(api, ctx["item_id"])
    assert_two_decimal_value(ppm, 60.00, "complaint_ppm_90d")
    assert posture == POSTURE_WATCH, "exactly 60.00 ppm trips WATCH"
    assert_item_state(read_item(api, ctx["item_id"]), ITEM_CONCEPT, POSTURE_WATCH)
    assert_instant_equals(minor["received_at"], DEFAULT_CLOCK, "received_at")


def test_a_complaint_row_carries_no_version_and_no_updated_at(api):
    """The one append-only entity in the model, read back by another role.

    PRD 3.8: "Complaints are append-only, as §2.4 sets out: there is no update, no
    deletion, no `version` and no status to filter on, so every trending computation
    sees every complaint ever logged inside its window."

    PRD 3.8: "The server stamps `received_at` with the logical clock's current
    instant, which is also the row's `created_at`."

    Design: Corner/entities/complaint_is_append_only_without_version_field
    """
    ctx = build_chain(api, upto=10)

    created = validate_success(
        api.create_complaint(
            f.minor_complaint_payload(
                ctx["item_id"],
                defect_category="PACKAGING",
                lot_code="L-0801",
                narrative="Carton flap unsealed",
            ),
            QUALITY_HEADERS,
        ),
        expected_status=201,
    )

    assert_append_only(created)
    assert_instant_equals(created["received_at"], DEFAULT_CLOCK, "received_at")
    assert_instant_equals(
        created["received_at"], created["created_at"], "received_at"
    )

    read_back = validate_success(
        api.get_complaint(created["id"], REGULATORY_HEADERS)
    )
    assert_append_only(read_back)
    assert_instant_equals(read_back["received_at"], DEFAULT_CLOCK, "received_at")


def test_a_critical_complaint_on_an_item_that_never_shipped_reads_zero_ppm(api):
    """No denominator is not a division error: the figure is defined to 0.00.

    PRD 3.8: "If the item's `trailing_90d_units` is zero, `complaint_ppm_90d` is
    defined to be 0.00 rather than an error or an unbounded figure, so complaints
    logged against an item with no shipment history never move its posture."

    PRD 3.3: "`trailing_90d_units` may optionally be seeded at creation from the
    retailer's shipment feed; when omitted it starts at zero, and it may never be
    negative."

    Design: Corner/calculations/complaint_ppm_is_zero_when_trailing_units_are_zero
    """
    ctx = build_chain(api, upto=9)
    unshipped = validate_success(
        api.create_item(
            f.item_payload(
                ctx["gap_id"],
                item_name="Harvest Lane Buttery Rounds",
                pack_size_desc="12 oz sleeve",
                trailing_90d_units=None,
            ),
            SOURCING_HEADERS,
        ),
        expected_status=201,
    )
    assert unshipped["trailing_90d_units"] == 0, "an omitted feed figure starts at zero"

    complaint = add_complaint(api, unshipped["id"])

    assert complaint["severity"] == SEVERITY_CRITICAL
    assert complaint["item_id"] == unshipped["id"]
    item = read_item(api, unshipped["id"])
    assert item["trailing_90d_units"] == 0
    assert_two_decimal_value(item["complaint_ppm_90d"], 0.00, "complaint_ppm_90d")
    assert_item_state(item, ITEM_CONCEPT, POSTURE_GREEN)


def test_a_larger_shipment_denominator_walks_probation_all_the_way_to_green(api):
    """One feed post crosses two thresholds downward, not one step at a time.

    PRD 3.8: "It overwrites the stored value and then triggers the same recomputation
    a new complaint triggers."

    PRD 3.8: "`GREEN → WATCH` and `WATCH → PROBATION` fire when the recomputed posture
    is worse than the stored one; `PROBATION → WATCH` and `PROBATION → GREEN` fire when
    a growing shipment denominator dilutes the complaint rate."

    PRD 3.8: "The `probation_item_count` is the number of that supplier's items
    currently standing at `PROBATION`"

    Design: Corner/endpoints/shipment_feed_recomputes_ppm_and_walks_posture_back_to_green
    """
    ctx = build_chain(api, upto=12)
    add_complaint(api, ctx["item_id"], lot_code="L26-2201")
    add_complaint(
        api,
        ctx["item_id"],
        factory=f.major_complaint_payload,
        defect_category="SPOILAGE",
        lot_code="L26-2201",
    )
    add_complaint(
        api,
        ctx["item_id"],
        factory=f.minor_complaint_payload,
        defect_category="PACKAGING",
        lot_code="L26-2202",
    )
    ppm, posture = _ppm_and_posture(api, ctx["item_id"])
    assert_two_decimal_value(ppm, 160.00, "complaint_ppm_90d")
    assert posture == POSTURE_PROBATION
    assert read_supplier(api, ctx["supplier_id"])["probation_item_count"] == 1

    fed = validate_success(
        api.post_shipment_feed(
            ctx["item_id"], f.shipment_feed_payload(200000), SOURCING_HEADERS
        )
    )

    assert fed["trailing_90d_units"] == 200000
    assert_two_decimal_value(fed["complaint_ppm_90d"], 40.00, "complaint_ppm_90d")
    assert fed["quality_posture"] == POSTURE_GREEN, (
        "eight points over 200000 units clears both thresholds in one step"
    )
    assert_item_state(read_item(api, ctx["item_id"]), ITEM_SOURCED, POSTURE_GREEN)
    assert read_supplier(api, ctx["supplier_id"])["probation_item_count"] == 0


def test_the_shipment_feed_is_shared_by_sourcing_and_quality_but_closed_to_regulatory(
    api,
):
    """The desk that may log the complaint may not restate the denominator.

    PRD 3.8: "Posting the shipment feed is open to a `SourcingManager` or a
    `QualityAuditor` and supplies a single figure, `trailing_90d_units`, the units
    shipped over the trailing ninety days, which may be zero but never negative."

    PRD 2.1: "A `RegulatoryReviewer` owns label compliance: claim review and artwork
    review, and by design may never review a claim it submitted itself."

    Design: Corner/rbac/shipment_feed_is_shared_by_sourcing_and_quality_and_closed_to_everyone_else
    """
    ctx = build_chain(api, upto=12)
    validate_success(
        api.create_complaint(
            f.major_complaint_payload(
                ctx["item_id"],
                defect_category="SENSORY",
                lot_code="L26-2301",
                narrative="Bitter aftertaste in three cartons.",
            ),
            REGULATORY_HEADERS,
        ),
        expected_status=201,
    )

    by_sourcing = validate_success(
        api.post_shipment_feed(
            ctx["item_id"], f.shipment_feed_payload(20000), SOURCING_HEADERS
        )
    )
    assert_two_decimal_value(
        by_sourcing["complaint_ppm_90d"], 100.00, "complaint_ppm_90d"
    )
    assert by_sourcing["quality_posture"] == POSTURE_WATCH

    by_quality = validate_success(
        api.post_shipment_feed(
            ctx["item_id"], f.shipment_feed_payload(40000), QUALITY_HEADERS
        )
    )
    assert_two_decimal_value(
        by_quality["complaint_ppm_90d"], 50.00, "complaint_ppm_90d"
    )
    assert by_quality["quality_posture"] == POSTURE_GREEN
    settled_version = by_quality["version"]

    response = api.post_shipment_feed(
        ctx["item_id"], f.shipment_feed_payload(80000), REGULATORY_HEADERS
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

    item = read_item(api, ctx["item_id"])
    assert item["trailing_90d_units"] == 40000
    assert_two_decimal_value(item["complaint_ppm_90d"], 50.00, "complaint_ppm_90d")
    assert item["quality_posture"] == POSTURE_GREEN
    assert_version_is(item, settled_version, "item")
