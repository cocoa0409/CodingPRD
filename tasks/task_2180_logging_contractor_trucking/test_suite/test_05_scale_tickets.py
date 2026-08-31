"""The mill scale ticket: legal weight ceilings and the pinned pound-to-ton order."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_delivery_ticket,
    assert_ticket_weight_chain,
    build_network,
    certify_ticket,
    deliver_load,
    load_at_mill,
    read_delivery_ticket,
    read_load,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
    write_ticket,
)


class TestServerCopiedTicketFields:
    def test_the_ticket_takes_its_tare_weight_from_the_truck(self, api):
        """PRD §3.7: "Two fields on a ticket are copied by the server and never taken
        from the client. The ticket's `mill_id` is copied from the `mill_id` of the
        load's mill contract, which is also what the scaler's `X-User-ID` is compared
        against. The ticket's `tare_weight_lbs` is copied from the truck's own
        `tare_weight_lbs`; a client-supplied tare is ignored outright."
        PRD §3.7: "The ticket opens in `DRAFT` status with `certified_at`,
        `certified_by_user_id` and `reject_reason` all null."

        Design: Corner/entities/delivery_ticket_tare_weight_is_copied_from_the_truck
        """
        scn = build_network()
        load = load_at_mill(scn)

        response = api.create_delivery_ticket(
            load["id"],
            {
                "gross_weight_lbs": 90000,
                "defect_deduction_pct": 0.04,
                "scaled_species": "DOUGLAS_FIR",
                "scaled_grade": "SAWLOG_1",
            },
            scn["scaler_headers"],
        )
        ticket = validate_success(response, 201)

        assert_delivery_ticket(ticket)
        assert ticket["tare_weight_lbs"] == 31_000
        assert ticket["net_weight_lbs"] == 59_000
        assert ticket["mill_id"] == scn["mill_a_id"]
        assert ticket["load_id"] == load["id"]
        assert ticket["ticket_status"] == "DRAFT"

    def test_ticket_listing_filters_by_load_and_by_mill(self, api):
        """PRD §3.7: "Tickets may be listed with filters on `load_id`, `mill_id` and
        `ticket_status`."
        PRD §2.3: "Filter parameters are additive: supplying several narrows the
        result set to records matching all of them."

        Design: Corner/endpoints/delivery_tickets_list_filters_by_load_and_by_mill
        """
        scn = build_network()
        first_load, first_ticket = deliver_load(scn)
        second_load = load_at_mill(
            scn,
            estimated_net_tons=20.0,
            scheduled_depart_at="2026-08-04T08:00:00Z",
            scheduled_arrive_at="2026-08-04T10:00:00Z",
        )
        second_ticket = write_ticket(
            scn, second_load["id"], gross_weight_lbs=71060, defect_deduction_pct=0.0
        )

        by_load, load_meta = validate_paginated(
            api.list_delivery_tickets(
                scn["scaler_headers"], params={"load_id": second_load["id"]}
            )
        )
        assert load_meta["total_count"] == 1
        assert [row["id"] for row in by_load] == [second_ticket["id"]]

        by_mill, mill_meta = validate_paginated(
            api.list_delivery_tickets(
                scn["scaler_headers"],
                params={"mill_id": scn["mill_a_id"], "limit": 10, "offset": 0},
            )
        )
        assert mill_meta["total_count"] == 2
        assert {row["id"] for row in by_mill} == {first_ticket["id"], second_ticket["id"]}

        assert read_delivery_ticket(second_ticket["id"])["ticket_status"] == "DRAFT"
        assert read_delivery_ticket(first_ticket["id"])["ticket_status"] == "CERTIFIED"


class TestLegalWeightCeiling:
    def test_a_gross_weight_one_pound_over_the_axle_cap_is_refused(self, api):
        """PRD §3.7: "The ceiling is then the smaller of the effective legal weight
        plus that uplift, and the axle cap for the truck's configuration — 80,000
        pounds for `FIVE_AXLE`, 91,000 for `SIX_AXLE` and 105,500 for `SEVEN_AXLE`."
        PRD §3.7: "Rejection is strict but admits equality: a `gross_weight_lbs`
        strictly greater than the ceiling is refused with `ERR_OVERWEIGHT_LOAD`, while
        a gross weight exactly equal to the ceiling passes."

        Design: Difficulty/boundary_precision_check/gross_weight_exactly_at_axle_cap_admits_the_scale_ticket
        """
        scn = build_network()
        load = load_at_mill(scn)

        response = api.create_delivery_ticket(
            load["id"],
            {
                "gross_weight_lbs": 91001,
                "defect_deduction_pct": 0.0,
                "scaled_species": "DOUGLAS_FIR",
                "scaled_grade": "SAWLOG_1",
            },
            scn["scaler_headers"],
        )
        validate_error(response, ApiErrorId.ERR_OVERWEIGHT_LOAD.value, 422)
        assert read_load(load["id"])["dispatch_status"] == "AT_MILL"

    def test_a_gross_weight_exactly_at_the_axle_cap_is_admitted(self, api):
        """PRD §3.7: "Rejection is strict but admits equality: a `gross_weight_lbs`
        strictly greater than the ceiling is refused with `ERR_OVERWEIGHT_LOAD`, while
        a gross weight exactly equal to the ceiling passes."
        PRD §3.7: "Only that integer pound figure is then divided by 2,000 pounds per
        ton and rounded half-up to two decimal places, giving `net_tons` — the scaled
        tonnage that every downstream money figure uses."

        Design: Difficulty/boundary_precision_check/gross_weight_exactly_at_axle_cap_admits_the_scale_ticket
        """
        scn = build_network()
        load = load_at_mill(scn)

        ticket = validate_success(
            api.create_delivery_ticket(
                load["id"],
                {
                    "gross_weight_lbs": 91000,
                    "defect_deduction_pct": 0.0,
                    "scaled_species": "DOUGLAS_FIR",
                    "scaled_grade": "SAWLOG_1",
                },
                scn["scaler_headers"],
            ),
            201,
        )

        assert ticket["max_allowed_gross_lbs"] == 91_000
        assert ticket["gross_weight_lbs"] == 91_000
        assert ticket["net_weight_lbs"] == 60_000
        assert ticket["defect_deducted_lbs"] == 0
        assert ticket["net_tons"] == pytest.approx(30.00, abs=0.005)
        assert ticket["ticket_status"] == "DRAFT"

    def test_an_active_frost_law_window_cuts_the_posted_weight_by_a_fifth(self, api):
        """PRD §3.7: "The frost-law posting is considered active when the route's
        `status` is `POSTED_RESTRICTED`, or when the route has a non-null
        `frost_law_start_on` and the clock date falls on or after `frost_law_start_on`
        and on or before `frost_law_end_on` — a closed interval on both endpoints. When
        frost law is active, the effective legal weight is the route's
        `legal_gross_weight_lbs` multiplied by 0.80 — a twenty-percent reduction — and
        rounded **down** to whole pounds, never rounded to nearest; when it is not
        active, the effective legal weight is the posted figure unchanged."

        Design: Corner/calculations/frost_law_window_cuts_the_posted_legal_weight_by_twenty_percent
        """
        scn = build_network(
            contract={"period_start": "2026-01-01", "period_end": "2026-12-31"},
            truck={"axle_config": "SEVEN_AXLE"},
            route={
                "frost_law_start_on": "2026-01-01",
                "frost_law_end_on": "2026-03-31",
            },
        )
        set_clock("2026-02-15T09:00:00Z")
        load = load_at_mill(
            scn,
            estimated_net_tons=23.0,
            scheduled_depart_at="2026-02-15T10:00:00Z",
            scheduled_arrive_at="2026-02-15T12:00:00Z",
        )

        over = api.create_delivery_ticket(
            load["id"],
            {
                "gross_weight_lbs": 78401,
                "defect_deduction_pct": 0.0,
                "scaled_species": "DOUGLAS_FIR",
                "scaled_grade": "SAWLOG_1",
            },
            scn["scaler_headers"],
        )
        validate_error(over, ApiErrorId.ERR_OVERWEIGHT_LOAD.value, 422)

        ticket = validate_success(
            api.create_delivery_ticket(
                load["id"],
                {
                    "gross_weight_lbs": 78400,
                    "defect_deduction_pct": 0.0,
                    "scaled_species": "DOUGLAS_FIR",
                    "scaled_grade": "SAWLOG_1",
                },
                scn["scaler_headers"],
            ),
            201,
        )
        assert ticket["max_allowed_gross_lbs"] == 78_400
        assert ticket["net_weight_lbs"] == 47_400
        assert ticket["net_tons"] == pytest.approx(23.70, abs=0.005)
        assert ticket["ticket_status"] == "DRAFT"

    def test_a_posted_restricted_route_is_frost_posted_on_every_date(self, api):
        """PRD §3.1: "A route's `status` is `OPEN`, `POSTED_RESTRICTED` or `CLOSED`,
        defaulting to `OPEN`; a route sitting in `POSTED_RESTRICTED` behaves as though
        the frost-law posting were in force on every date regardless of the window."
        PRD §3.7: "When frost law is active, the effective legal weight is the route's
        `legal_gross_weight_lbs` multiplied by 0.80 — a twenty-percent reduction — and
        rounded **down** to whole pounds, never rounded to nearest; when it is not
        active, the effective legal weight is the posted figure unchanged."

        Design: Corner/calculations/posted_restricted_route_applies_the_frost_reduction_on_every_date
        """
        scn = build_network(
            truck={"axle_config": "SEVEN_AXLE"},
            route={"status": "POSTED_RESTRICTED"},
        )
        load = load_at_mill(scn, estimated_net_tons=23.0)

        ticket = validate_success(
            api.create_delivery_ticket(
                load["id"],
                {
                    "gross_weight_lbs": 78400,
                    "defect_deduction_pct": 0.0,
                    "scaled_species": "DOUGLAS_FIR",
                    "scaled_grade": "SAWLOG_1",
                },
                scn["scaler_headers"],
            ),
            201,
        )

        route = validate_success(
            api.get_haul_route(scn["route_a_id"], scn["scaler_headers"])
        )
        assert route["status"] == "POSTED_RESTRICTED"
        assert ticket["max_allowed_gross_lbs"] == 78_400
        assert ticket["net_tons"] == pytest.approx(23.70, abs=0.005)

    def test_the_permit_uplift_needs_both_sides_to_be_longer_combination(self, api):
        """PRD §3.7: "A permit uplift of 10,000 pounds is granted only when the truck's
        `permit_class` is `LONGER_COMBINATION` **and** the route's
        `permit_class_required` is also `LONGER_COMBINATION`; in every other
        combination the uplift is zero. The ceiling is then the smaller of the
        effective legal weight plus that uplift, and the axle cap for the truck's
        configuration — 80,000 pounds for `FIVE_AXLE`, 91,000 for `SIX_AXLE` and
        105,500 for `SEVEN_AXLE`."

        Design: Corner/calculations/permit_uplift_requires_both_the_truck_and_the_route_to_be_longer_combination
        """
        scn = build_network(
            truck={"axle_config": "SEVEN_AXLE", "permit_class": "LONGER_COMBINATION"},
            route={"permit_class_required": "LONGER_COMBINATION"},
        )
        load = load_at_mill(scn, estimated_net_tons=37.0)

        ticket = validate_success(
            api.create_delivery_ticket(
                load["id"],
                {
                    "gross_weight_lbs": 105500,
                    "defect_deduction_pct": 0.0,
                    "scaled_species": "DOUGLAS_FIR",
                    "scaled_grade": "SAWLOG_1",
                },
                scn["scaler_headers"],
            ),
            201,
        )

        assert ticket["max_allowed_gross_lbs"] == 105_500
        assert ticket["net_weight_lbs"] == 74_500
        assert ticket["net_tons"] == pytest.approx(37.25, abs=0.005)


class TestPayableTonnage:
    def test_the_defect_deduction_rounds_in_pounds_before_the_ton_conversion(self, api):
        """PRD §3.7: "The defect deduction is that net weight multiplied by
        `defect_deduction_pct`, rounded half-up to whole **pounds**, stored as
        `defect_deducted_lbs`. The payable weight is the net weight less the rounded
        deduction, stored as `payable_lbs`. Only that integer pound figure is then
        divided by 2,000 pounds per ton and rounded half-up to two decimal places,
        giving `net_tons` — the scaled tonnage that every downstream money figure uses.
        Converting to tons first and deducting afterwards is a different answer and is
        forbidden."

        Design: Corner/calculations/defect_deduction_rounds_in_pounds_before_the_conversion_to_tons
        """
        scn = build_network()
        load = load_at_mill(scn, estimated_net_tons=29.0)

        ticket = validate_success(
            api.create_delivery_ticket(
                load["id"],
                {
                    "gross_weight_lbs": 90010,
                    "defect_deduction_pct": 0.037,
                    "scaled_species": "DOUGLAS_FIR",
                    "scaled_grade": "SAWLOG_1",
                },
                scn["scaler_headers"],
            ),
            201,
        )

        assert_ticket_weight_chain(ticket)
        assert ticket["net_weight_lbs"] == 59_010
        assert ticket["defect_deducted_lbs"] == 2_183
        assert ticket["payable_lbs"] == 56_827
        assert ticket["net_tons"] == pytest.approx(28.41, abs=0.005)
        assert ticket["net_tons"] != pytest.approx(28.42, abs=0.001)

    def test_a_gross_weight_equal_to_the_tare_yields_zero_payable_tons(self, api):
        """PRD §3.7: "If the resulting `net_tons` is not strictly greater than 0.00,
        the ticket is refused with `ERR_ZERO_NET_TONS`."
        PRD §3.7: "The net weight is the gross weight less the truck's tare weight,
        stored as `net_weight_lbs`."

        Design: Corner/validations/a_ticket_whose_gross_equals_the_tare_is_rejected_for_zero_net_tons
        """
        scn = build_network()
        load = load_at_mill(scn)

        response = api.create_delivery_ticket(
            load["id"],
            {
                "gross_weight_lbs": 31000,
                "defect_deduction_pct": 0.0,
                "scaled_species": "DOUGLAS_FIR",
                "scaled_grade": "SAWLOG_1",
            },
            scn["scaler_headers"],
        )
        validate_error(response, ApiErrorId.ERR_ZERO_NET_TONS.value, 422)

        rows, meta = validate_paginated(
            api.list_delivery_tickets(
                scn["scaler_headers"], params={"load_id": load["id"]}
            )
        )
        assert meta["total_count"] == 0, "the refused ticket must not be persisted"
        assert read_load(load["id"])["dispatch_status"] == "AT_MILL"
