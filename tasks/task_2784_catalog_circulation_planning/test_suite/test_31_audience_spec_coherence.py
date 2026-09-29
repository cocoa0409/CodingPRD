"""A line names exactly one audience, and the ladder decides who says so.

Six creates hit the same endpoint. Three are well-formed but incoherent about
which audience they name, one carries an out-of-enum type, one names a segment that
does not exist, and only the last is accepted. The two rejections that are NOT
audience-shape failures are the point: the enum check and the body foreign-key check
both sit above the audience check in §2.10, so a handler that validates the audience
shape first reports the wrong code and the wrong status for each of them.
"""
from test_helpers import (
    BROKER,
    CLOCK_START,
    NON_EXISTENT_UUID,
    PLANNER,
    create_rental_payload,
    fetch_drop,
    fetch_line,
    iso_utc,
    new_drop,
    new_plan,
    new_season,
    new_segment,
    validate_error,
    validate_paginated,
    validate_success,
    set_clock,
)

SCORING = {
    "recency_days": 45,
    "orders_12mo": 7,
    "ltv_cents": 62000,
    "housefile_count": 30000,
    "avg_order_value_cents": 18500,
    "historical_response_rate_bps": 620,
}


def _a_drop_ready_for_lines(api) -> dict:
    """One resolvable segment and one resolvable rental, on a drop of a DRAFT plan,
    so every rejection below is about the audience specification rather than about
    an unresolvable reference or an uneditable parent."""
    set_clock(CLOCK_START)
    season = new_season(season_code="FW26", fiscal_year=2026)
    segment = new_segment(season["id"], segment_code="S_A", **SCORING)
    rental = validate_success(
        api.create_rental(
            create_rental_payload(
                season["id"],
                list_source_name="COOP-A",
                requested_gross_names=10000,
                cost_per_thousand_cents=8500,
                housefile_overlap_bps=1000,
                inter_list_overlap_bps=0,
            ),
            BROKER,
        ),
        201,
    )
    plan = new_plan(season["id"], plan_code="P1", budget_cents=20000000)
    drop = new_drop(
        plan["id"], drop_number=1, in_home_date=iso_utc("2026-09-15"), page_count=64
    )
    return {"season": season, "segment": segment, "rental": rental, "plan": plan,
            "drop": drop}


def _the_one_accepted_line(api, world) -> dict:
    """The five malformed creates, then the single well-formed one."""
    drop_id = world["drop"]["id"]
    segment_id = world["segment"]["id"]
    for payload in (
        {"audience_type": "HOUSEFILE", "requested_quantity": 5000,
         "housefile_segment_id": segment_id,
         "prospect_list_rental_id": world["rental"]["id"]},
        {"audience_type": "HOUSEFILE", "requested_quantity": 5000},
        {"audience_type": "RENTAL", "requested_quantity": 5000,
         "housefile_segment_id": segment_id},
        {"audience_type": "PROSPECT", "requested_quantity": 5000,
         "housefile_segment_id": segment_id},
        {"audience_type": "HOUSEFILE", "requested_quantity": 5000,
         "housefile_segment_id": NON_EXISTENT_UUID},
    ):
        api.create_line(drop_id, payload, PLANNER)

    return validate_success(
        api.create_line(
            drop_id,
            {"audience_type": "HOUSEFILE", "requested_quantity": 5000,
             "housefile_segment_id": segment_id},
            PLANNER,
        ),
        201,
    )


class TestIncoherentAudienceSpecifications:
    def test_both_neither_and_a_disagreeing_type_are_all_refused(self, api):
        """PRD §3.5: "The planner supplies an `audience_type` of either `HOUSEFILE`
        or `RENTAL`, a `requested_quantity` greater than zero, and precisely one of two
        audience references: `housefile_segment_id` for a housefile line, or
        `prospect_list_rental_id` for a rental line. The unused reference is null.
        Supplying both references, supplying neither, or supplying an `audience_type`
        that disagrees with the reference actually provided is rejected with
        `ERR_AUDIENCE_SPEC_INVALID`."

        Design: Corner/validations/a_line_must_name_exactly_one_audience_or_it_is_rejected
        """
        world = _a_drop_ready_for_lines(api)
        drop_id = world["drop"]["id"]
        segment_id = world["segment"]["id"]

        both = api.create_line(
            drop_id,
            {"audience_type": "HOUSEFILE", "requested_quantity": 5000,
             "housefile_segment_id": segment_id,
             "prospect_list_rental_id": world["rental"]["id"]},
            PLANNER,
        )
        validate_error(both, "ERR_AUDIENCE_SPEC_INVALID", 422)

        neither = api.create_line(
            drop_id,
            {"audience_type": "HOUSEFILE", "requested_quantity": 5000},
            PLANNER,
        )
        validate_error(neither, "ERR_AUDIENCE_SPEC_INVALID", 422)

        disagreeing = api.create_line(
            drop_id,
            {"audience_type": "RENTAL", "requested_quantity": 5000,
             "housefile_segment_id": segment_id},
            PLANNER,
        )
        validate_error(disagreeing, "ERR_AUDIENCE_SPEC_INVALID", 422)


class TestTheChecksThatOutrankTheAudienceShape:
    def test_an_out_of_enum_audience_type_is_a_schema_failure(self, api):
        """PRD §2.10: "**Request body satisfies its schema** on every write endpoint:
        required fields present, enum values in range, integers inside their declared
        bounds, no negative money or quantities — otherwise `ERR_INVALID_REQUEST`
        (422).
        6. **Audience specification coherent** on
        `POST /catalog-circulation/drops/{id}/circulation-lines` — otherwise
        `ERR_AUDIENCE_SPEC_INVALID` (422)."

        Design: Corner/validations/a_line_must_name_exactly_one_audience_or_it_is_rejected
        """
        world = _a_drop_ready_for_lines(api)

        response = api.create_line(
            world["drop"]["id"],
            {"audience_type": "PROSPECT", "requested_quantity": 5000,
             "housefile_segment_id": world["segment"]["id"]},
            PLANNER,
        )
        error = validate_error(response, "ERR_INVALID_REQUEST", 422)
        assert error["error_id"] != "ERR_AUDIENCE_SPEC_INVALID"

    def test_an_unresolvable_segment_reference_is_a_not_found(self, api):
        """PRD §2.10: "**Every body foreign key resolves**, on
        `POST /catalog-circulation/housefile-segments`,
        `POST /catalog-circulation/prospect-list-rentals`,
        `POST /catalog-circulation/circulation-plans`,
        `POST /catalog-circulation/circulation-plans/{id}/merge-purge-runs`,
        `POST /catalog-circulation/drops/{id}/circulation-lines` and
        `POST /catalog-circulation/contact-events` — otherwise the matching 404 from
        §2.8."
        PRD §2.8: "A `season_id` that does not resolve yields
        `ERR_SEASON_NOT_FOUND`; an unresolvable `parent_segment_id` or
        `housefile_segment_id` yields `ERR_SEGMENT_NOT_FOUND`; an unresolvable
        `prospect_list_rental_id` or any unresolvable element of `input_rental_ids`
        yields `ERR_RENTAL_NOT_FOUND`; an unresolvable `drop_id` on a contact event
        yields `ERR_DROP_NOT_FOUND`."

        Design: Corner/validations/a_line_must_name_exactly_one_audience_or_it_is_rejected
        """
        world = _a_drop_ready_for_lines(api)

        response = api.create_line(
            world["drop"]["id"],
            {"audience_type": "HOUSEFILE", "requested_quantity": 5000,
             "housefile_segment_id": NON_EXISTENT_UUID},
            PLANNER,
        )
        error = validate_error(response, "ERR_SEGMENT_NOT_FOUND", 404)
        assert error["error_id"] != "ERR_AUDIENCE_SPEC_INVALID"


class TestNoneOfTheRejectionsLeftARowBehind:
    def test_the_accepted_line_is_proposed_with_every_figure_at_zero(self, api):
        """PRD §3.5: "A newly created line lands in status `PROPOSED` with
        `allocation_rank` 0 and every allocated, committed, margin and cost field at
        0."

        Design: Corner/validations/a_line_must_name_exactly_one_audience_or_it_is_rejected
        """
        world = _a_drop_ready_for_lines(api)
        line = _the_one_accepted_line(api, world)

        assert line["status"] == "PROPOSED"
        assert line["allocation_rank"] == 0
        assert line["allocated_quantity"] == 0
        assert line["committed_cost_cents"] == 0
        assert line["gross_margin_cents"] == 0
        assert line["circulation_cost_cents"] == 0

    def test_the_drop_total_counts_the_one_surviving_request(self, api):
        """PRD §3.5: "Creating the line also recomputes the drop's
        `requested_quantity_total` — the sum of `requested_quantity` over the drop's
        lines in status `PROPOSED` or `ALLOCATED` — and a plan sitting in `COSTED`
        falls back to `DRAFT`."

        Design: Corner/validations/a_line_must_name_exactly_one_audience_or_it_is_rejected
        """
        world = _a_drop_ready_for_lines(api)
        line = _the_one_accepted_line(api, world)

        rows, meta = validate_paginated(
            api.list_lines(PLANNER, params={"drop_id": world["drop"]["id"]})
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [line["id"]]
        assert fetch_line(line["id"])["requested_quantity"] == 5000
        assert fetch_drop(world["drop"]["id"])["requested_quantity_total"] == 5000
