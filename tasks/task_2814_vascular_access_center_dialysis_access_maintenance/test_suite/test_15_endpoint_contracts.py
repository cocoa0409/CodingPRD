"""Endpoint surface: declared ordering, a junction reachable from both sides, a pure read.

The three scenarios here read rather than write, so each one is judged on the shape of the
envelope it returns as much as on the rows inside it.
"""

from test_helpers import assertions
from test_helpers import fixtures as fx
from test_helpers import validate_error, validate_paginated, validate_success

LATE_START = "2026-08-01T17:00:00Z"
LATE_END = "2026-08-01T18:00:00Z"
EARLY_START = "2026-08-01T13:00:00Z"
EARLY_END = "2026-08-01T14:00:00Z"
MID_START = "2026-08-01T15:00:00Z"
MID_END = "2026-08-01T16:00:00Z"
UNKNOWN_LOT_ID = "00000000-0000-4000-8000-000000000000"
READING_AT = "2026-07-25T08:00:00Z"


def _three_cases_booked_out_of_order(api):
    """Three cases in one room, inserted 17:00 first and 13:00 second.

    Each booking occupies its hour plus the room's thirty-minute turnover, giving the
    half-open spans [13:00, 14:30), [15:00, 16:30) and [17:00, 18:30), which do not
    intersect, and three cases sit under the room's default daily cap of six.
    """
    center = fx.seed_center(api)
    booked = {}
    for label, start, end in (
        ("late", LATE_START, LATE_END),
        ("early", EARLY_START, EARLY_END),
        ("mid", MID_START, MID_END),
    ):
        triaged = fx.seed_triaged_referral(api, center)
        assert triaged["referral"]["urgency"] == "ROUTINE"
        procedure = fx.book_case(
            api,
            triaged["referral_id"],
            center["room_id"],
            center["operator_id"],
            triaged["referral"]["version"],
            start,
            end,
        )
        assert procedure["clinical_status"] == "SCHEDULED"
        booked[label] = procedure
        booked[label + "_access_id"] = triaged["access_id"]
    assert center["room"]["turnover_buffer_min"] == 30
    assert center["room"]["daily_case_cap"] == 6
    return center, booked


def test_01_the_procedure_list_reads_in_schedule_order_across_two_pages(api):
    """Insertion order is 17:00, 13:00, 15:00; the list reads 13:00, 15:00, 17:00.

    The PRD states: "procedure lists are ordered by `scheduled_start` ascending then
    `created_at` ascending".

    Pagination is a window over that ordering rather than over the matching set, and the
    PRD pins the counting: "Both are echoed in the response `meta` alongside `total_count`
    (the number of items matching the filter before the window is applied) and `has_more`
    (true when items remain beyond the current window)."

    Design: Corner/endpoints/procedure_listing_is_ordered_by_scheduled_start_not_by_creation_order
    """
    center, booked = _three_cases_booked_out_of_order(api)

    first_page, first_meta = validate_paginated(
        api.list_procedures(fx.ADMIN, {"room_id": center["room_id"], "limit": 2, "offset": 0})
    )
    assert [procedure["id"] for procedure in first_page] == [
        booked["early"]["id"],
        booked["mid"]["id"],
    ]
    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True

    second_page, second_meta = validate_paginated(
        api.list_procedures(fx.ADMIN, {"room_id": center["room_id"], "limit": 2, "offset": 2})
    )
    assert [procedure["id"] for procedure in second_page] == [booked["late"]["id"]]
    assert second_meta["limit"] == 2
    assert second_meta["offset"] == 2
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False


def test_02_each_filter_narrows_the_count_and_an_empty_match_is_still_an_array(api):
    """A filter that matches nothing is an empty list, not a not-found.

    The PRD states: "the procedure list filters on `referral_id`, `access_id`, `room_id`,
    `primary_operator_id`, `sedation_rn_id`, `attested_by_id`, `supporting_reading_id`,
    `clinical_status` and `coding_status`".

    The `access_id` filter works only because the value was denormalised onto the
    procedure: the PRD states "The new procedure's `access_id` is copied verbatim from the
    referral's `access_id` at the moment of creation".

    Design: Corner/endpoints/procedure_listing_is_ordered_by_scheduled_start_not_by_creation_order
    """
    _center, booked = _three_cases_booked_out_of_order(api)

    matched, matched_meta = validate_paginated(
        api.list_procedures(fx.ADMIN, {"access_id": booked["mid_access_id"]})
    )
    assert [procedure["id"] for procedure in matched] == [booked["mid"]["id"]]
    assert matched_meta["total_count"] == 1
    assert matched[0]["access_id"] == booked["mid_access_id"]

    response = api.list_procedures(fx.ADMIN, {"clinical_status": "DISCHARGED"})
    empty, empty_meta = validate_paginated(response)
    assert empty == []
    assert empty_meta["total_count"] == 0
    assert empty_meta["has_more"] is False
    assert response.json()["response_type"] == "array"


def test_03_an_unknown_lot_in_the_body_is_a_404_and_the_real_one_makes_a_two_sided_link(api):
    """The junction row is created once and is then reachable from either foreign key.

    The PRD states: "Foreign keys supplied in a request *body* are resolved by the same
    catalogue of errors, but they are checked after body-shape validation, and among
    themselves they are checked in the order the operation declares its input fields."

    The unknown lot therefore never reaches the stock arithmetic, and the accepted request
    writes the row the PRD describes: "On success a device usage is created with `state` of
    `RESERVED`, `wasted_quantity` 0, `consumed_at` and `released_at` null".

    Both directions of the link are then walked, which the PRD provides for: "the
    device-usage list filters on `procedure_id`, `device_lot_id` and `state`".

    Design: Corner/endpoints/device_usage_links_a_procedure_and_a_lot_and_both_sides_are_reverse_reachable
    """
    bundle = fx.seed_scheduled_case(api)
    lot = fx.seed_lot(api, "BALLOON", received_quantity=6)

    missing = api.create_device_usage(
        bundle["procedure_id"],
        {
            "device_lot_id": UNKNOWN_LOT_ID,
            "quantity": 2,
            "expected_device_lot_version": lot["version"],
        },
        fx.COORDINATOR,
    )
    validate_error(missing, "ERR_DEVICE_LOT_NOT_FOUND", 404)

    untouched = fx.read_lot(api, lot["id"])
    assert untouched["quantity_reserved"] == 0
    assert untouched["version"] == lot["version"]

    usage = validate_success(
        api.create_device_usage(
            bundle["procedure_id"],
            {
                "device_lot_id": lot["id"],
                "quantity": 2,
                "expected_device_lot_version": lot["version"],
            },
            fx.COORDINATOR,
        ),
        201,
    )
    assertions.assert_device_usage(usage)
    assert usage["procedure_id"] == bundle["procedure_id"]
    assert usage["device_lot_id"] == lot["id"]
    assert usage["quantity"] == 2
    assert usage["state"] == "RESERVED"
    assert usage["wasted_quantity"] == 0
    assert usage["consumed_at"] is None
    assert usage["released_at"] is None

    promised = fx.read_lot(api, lot["id"])
    assert promised["quantity_reserved"] == 2
    assert promised["quantity_on_hand"] == 6
    assert promised["version"] == lot["version"] + 1

    by_operator = validate_success(
        api.get_device_usage(usage["id"], bundle["operator_headers"])
    )
    assert by_operator["id"] == usage["id"]
    assert by_operator["device_lot_id"] == lot["id"]
    assert by_operator["procedure_id"] == bundle["procedure_id"]

    from_the_lot, lot_meta = validate_paginated(
        api.list_device_usages(fx.ADMIN, {"device_lot_id": lot["id"]})
    )
    assert lot_meta["total_count"] == 1
    assert [row["id"] for row in from_the_lot] == [usage["id"]]

    from_the_case, case_meta = validate_paginated(
        api.list_device_usages(
            fx.ADMIN, {"procedure_id": bundle["procedure_id"], "state": "RESERVED"}
        )
    )
    assert case_meta["total_count"] == 1
    assert [row["id"] for row in from_the_case] == [usage["id"]]


def test_04_the_metrics_view_scales_the_rates_and_leaves_the_facility_alone(api):
    """One referral carrying five missed treatments, read twice, changing nothing.

    The PRD states: "`missed_treatments_per_referral_x100` is the raw in-window missed
    count multiplied by 100 and divided by the in-window referral volume, rounded half up
    to a whole number; it is reported as 0 when the referral volume is 0 rather than
    dividing by zero."

    It also states of `same_day_honor_rate_pct` that "the rate is likewise reported as 0
    when that denominator is 0", which is the branch taken here because the only referral
    banded to `ROUTINE`.

    The read is made by the facility's own coordinator, which the PRD permits: "A read-only
    partnership-metrics view exposes the whole picture to a `CenterAdmin`, an
    `AccessCoordinator` or the facility's own coordinator. It recomputes nothing and
    persists nothing, so two consecutive calls against an unchanged clock return
    byte-identical bodies."

    Design: Corner/endpoints/partnership_metrics_read_reports_scaled_rates_without_rescoring
    """
    center = fx.seed_center(api)
    access = fx.seed_access_in_use(api, center["patient_id"], access_type="AVG")
    fx.seed_reading(
        api,
        access["id"],
        center["facility_id"],
        reading_at=READING_AT,
        access_flow_ml_min=900,
        venous_pressure_mmhg=100,
        recirculation_pct=2.0,
        kind="ROUTINE",
    )
    referral = fx.triage(
        api,
        fx.seed_referral(
            api,
            access["id"],
            center["facility_id"],
            suspected_problem="STENOSIS",
            clinical_narrative="five treatments already missed waiting for this case",
            missed_treatment_count=5,
        )["id"],
    )
    assert referral["triage_score"] == 18
    assert referral["urgency"] == "ROUTINE"

    scored = fx.read_facility(api, center["facility_id"])
    assert scored["referral_volume_window"] == 1
    assert scored["raw_missed_count_window"] == 5
    assert scored["grace_credit_window"] == 0
    assert scored["adjusted_missed_count_window"] == 5
    assert scored["same_day_honored_window"] == 0
    assert scored["partnership_score"] == 80
    assert scored["partnership_tier"] == "SILVER"
    assert scored["contract_status"] == "ACTIVE"

    metrics = validate_success(
        api.get_facility_partnership_metrics(
            center["facility_id"], center["facility_headers"]
        )
    )
    assertions.assert_partnership_metrics(metrics)
    assert metrics["facility_id"] == center["facility_id"]
    assert metrics["missed_treatments_per_referral_x100"] == 500
    assert metrics["same_day_honor_rate_pct"] == 0
    assert metrics["partnership_score"] == 80
    assert metrics["referral_volume_window"] == 1
    assert metrics["raw_missed_count_window"] == 5
    assert metrics["adjusted_missed_count_window"] == 5

    again = validate_success(
        api.get_facility_partnership_metrics(center["facility_id"], fx.ADMIN)
    )
    assert again == metrics

    afterwards = fx.read_facility(api, center["facility_id"])
    assert afterwards["version"] == scored["version"]
    assert afterwards["last_scored_at"] == scored["last_scored_at"]
