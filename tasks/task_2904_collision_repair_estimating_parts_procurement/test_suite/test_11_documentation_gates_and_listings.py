"""Paperwork gates on the estimate and the repair, and the read surfaces that prove them.

Four of the shop's refusals are documentation refusals: an operation the labor guide
does not include may not be committed without a written justification, a car whose
sensors were disturbed may not be blueprinted without the manufacturer's calibration
procedure on file, a labor line written after the estimate is committed must name an
open supplement, and the frame technician may not leave the body stall until the
structural procedures have been signed off. Alongside them sit the fiscal boundary on
a supplier's quote, the ordering of the ladder's early rungs against a repair order
that does not exist at all, and the three listings the shop uses to reverse a lookup
from a supplier, a stall or an order back to the work hanging off it.
"""

from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    BLANK_HEADERS,
    ESTIMATOR_HEADERS,
    PARTS_MANAGER_HEADERS,
    SHOP_ADMIN_HEADERS,
    TECHNICIAN_HEADERS,
)

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)


def _ids(rows):
    """The identifiers of a listing's rows, as a set, since one logical instant
    stamps every row with the same `created_at` and leaves ties unordered."""
    return {row["id"] for row in rows}


class TestDocumentationAndFiscalGates:
    """The compliance paperwork the shop must hold before money or metal moves."""

    def test_an_unjustified_not_included_operation_blocks_the_estimate_lock(self, api):
        """A not-included operation without a written justification cannot be committed.

        PRD: "`not_included_operation`, defaulting to false, marks work the guide does not include in its published time; such a line **must** carry a non-empty `justification_note` in writing, and if it does not, the estimate cannot be committed."
        PRD: "And every `DRAFT` line whose `not_included_operation` is true must carry a non-null `justification_note`, or the lock is refused with `ERR_NOT_INCLUDED_JUSTIFICATION_MISSING`."
        PRD: "No side effect of any kind is applied when a check fails."
        Design: Corner/validations/not_included_operation_without_a_justification_blocks_the_lock
        """
        bare = fx.blueprinted_world(api)
        bare_line = fx.add_estimate_line(
            api,
            bare["order_id"],
            operation_code="BDY-1",
            labor_type="BODY",
            guide_hours=4.5,
            not_included_operation=True,
        )

        justified = fx.blueprinted_world(api)
        justified_line = fx.add_estimate_line(
            api,
            justified["order_id"],
            operation_code="BDY-1",
            labor_type="BODY",
            guide_hours=4.5,
            not_included_operation=True,
            justification_note="OEM procedure demands seam sealer after panel replacement",
        )
        locked = validate_success(
            api.lock_estimate(justified["order_id"], None, ESTIMATOR_HEADERS)
        )

        validate_error(
            api.lock_estimate(bare["order_id"], None, ESTIMATOR_HEADERS),
            ApiErrorId.NOT_INCLUDED_JUSTIFICATION_MISSING.value,
            422,
        )

        refused = fx.read_order(api, bare["order_id"])
        A.assert_stage(refused, C.STAGE_BLUEPRINTED)
        A.assert_cents(refused["labor_subtotal_cents"], 0, "labor_subtotal_cents")
        assert fx.read_estimate_line(api, bare_line["id"])["line_status"] == "DRAFT"

        A.assert_stage(locked, C.STAGE_ESTIMATE_LOCKED)
        A.assert_cents(locked["labor_subtotal_cents"], 27000, "labor_subtotal_cents")
        assert (
            fx.read_estimate_line(api, justified_line["id"])["line_status"] == "APPROVED"
        )

        rows, meta = validate_paginated(
            api.list_estimate_lines(
                ESTIMATOR_HEADERS,
                {"repair_order_id": bare["order_id"], "line_status": "DRAFT"},
            )
        )
        A.assert_page(meta, total_count=1)
        A.assert_ids(rows, [bare_line["id"]])

    def test_adas_damage_without_a_calibration_procedure_blocks_the_blueprint(self, api):
        """A disturbed sensor must be researched before the diagnosis is published.

        PRD: "Third, if **any** finding on the order has `adas_component_touched` set to true, then at least one procedure record on the order must have `operation_scope` equal to `ADAS` *and* `requires_calibration` equal to true; otherwise the blueprint is refused with `ERR_ADAS_PROCEDURE_RESEARCH_MISSING`."
        PRD: "At creation, a record whose `requires_calibration` is false is born at `calibration_status` `NOT_REQUIRED` and stays there permanently; a record whose `requires_calibration` is true is born at `REQUIRED`."
        PRD: "No side effect of any kind is applied when a check fails."
        Design: Corner/validations/adas_damage_without_a_calibration_procedure_blocks_blueprint
        """
        world = fx.open_order_world(api)
        order_id = world["order_id"]
        fx.add_finding(
            api,
            order_id,
            panel_code="FRONT_BUMPER",
            severity="MODERATE",
            adas_component_touched=True,
        )
        structural = fx.add_procedure_record(
            api,
            order_id,
            procedure_code="SEAM-SEAL",
            source="ALLDATA",
            operation_scope="STRUCTURAL",
        )
        assert fx.read_procedure_record(api, structural["id"])[
            "calibration_status"
        ] == "NOT_REQUIRED"

        validate_error(
            api.publish_blueprint(order_id, None, ESTIMATOR_HEADERS),
            ApiErrorId.ADAS_PROCEDURE_RESEARCH_MISSING.value,
            422,
        )

        refused = fx.read_order(api, order_id)
        A.assert_stage(refused, C.STAGE_TEARDOWN)
        A.assert_null(refused["blueprint_by_user_id"], "blueprint_by_user_id")
        A.assert_hours(
            refused["refinish_hours_provisional"], 0.0, "refinish_hours_provisional"
        )

        researched = fx.add_procedure_record(
            api,
            order_id,
            procedure_code="ADAS-FRONT-RADAR",
            source="OEM_PORTAL",
            operation_scope="ADAS",
            requires_calibration=True,
            calibration_type="STATIC",
        )
        published = validate_success(
            api.publish_blueprint(order_id, None, ESTIMATOR_HEADERS)
        )
        A.assert_stage(published, C.STAGE_BLUEPRINTED)

        rows, meta = validate_paginated(
            api.list_procedure_records(
                TECHNICIAN_HEADERS,
                {"repair_order_id": order_id, "calibration_status": "REQUIRED"},
            )
        )
        A.assert_page(meta, total_count=1)
        A.assert_ids(rows, [researched["id"]])

    def test_a_labor_line_written_after_the_lock_must_name_an_open_supplement(self, api):
        """Past the blueprint the estimate is closed to unsupplemented work.

        PRD: "Once the order's `stage` is **past** `BLUEPRINTED`, an unsupplemented line is no longer acceptable: the line must carry a `supplement_id` naming a supplement of the *same* order whose `status` is `SUBMITTED` or `INFO_REQUESTED`, and a line offered without one is refused with `ERR_SUPPLEMENT_REQUIRED`."
        PRD: "A line created under a supplement is born `PENDING_SUPPLEMENT` and is invisible to every total until the adjuster decides its fate."
        PRD: "While the posture is anything other than `OPEN` the order is frozen: no stage may advance, no part may be ordered, and the vehicle may not be released."
        Design: Corner/validations/a_new_line_after_the_lock_must_name_an_open_supplement
        """
        world = fx.locked_world(api)
        order_id = world["order_id"]
        supplement = fx.raise_supplement(
            api, order_id, reason_code="HIDDEN_DAMAGE", requested_amount_cents=12000
        )
        assert supplement["status"] == "SUBMITTED"

        payload = f.estimate_line_payload(
            operation_code="BDY-3", labor_type="BODY", guide_hours=1.5
        )
        validate_error(
            api.create_estimate_line(order_id, payload, ESTIMATOR_HEADERS),
            ApiErrorId.SUPPLEMENT_REQUIRED.value,
            422,
        )

        untouched = fx.read_order(api, order_id)
        A.assert_hours(untouched["approved_labor_hours"], 4.5, "approved_labor_hours")
        A.assert_cents(untouched["labor_subtotal_cents"], 27000, "labor_subtotal_cents")

        rows, meta = validate_paginated(
            api.list_estimate_lines(ESTIMATOR_HEADERS, {"repair_order_id": order_id})
        )
        A.assert_page(meta, total_count=1)
        A.assert_ids(rows, [world["line_ids"][0]])

        supplemented = dict(payload)
        supplemented["supplement_id"] = supplement["id"]
        accepted = validate_success(
            api.create_estimate_line(order_id, supplemented, ESTIMATOR_HEADERS), 201
        )
        assert accepted["line_status"] == "PENDING_SUPPLEMENT"
        A.assert_null(accepted["allocated_hours"], "allocated_hours")

    def test_structural_adherence_must_be_documented_before_leaving_repair(self, api):
        """The frame paperwork gates the hop out of the body stall, and the patch clears it.

        PRD: "Into `REFINISH_CALIBRATION` from `REPAIR`: no parts line may still be at `ORDERED` or `RECEIVED` — everything bought is on the car or has been sent back — or the hop is refused with `ERR_PARTS_NOT_INSTALLED`; and every procedure record on the order whose `operation_scope` is `STRUCTURAL` must have `adherence_documented` true, or the hop is refused with `ERR_PROCEDURE_ADHERENCE_MISSING`; and at least one booking with `stage` `REFINISH_CALIBRATION` and `status` `SCHEDULED` must exist, or the hop is refused with `ERR_NO_STAGE_ASSIGNMENT`."
        PRD: "Two later gates depend on it, and they differ in scope: leaving `REPAIR` requires only the `STRUCTURAL`-scoped records on the order to be documented, whereas filing a post-repair inspection requires **every** record on the order to be documented."
        PRD: "On success, every `ACTIVE` `REPAIR` booking on the order becomes `COMPLETED` and releases its `occupied_minutes` from its stall, every `SCHEDULED` `REFINISH_CALIBRATION` booking becomes `ACTIVE`, and the order's `version` increments."
        Design: Corner/validations/structural_adherence_must_be_documented_before_leaving_repair
        """
        world = fx.locked_world_at(
            api,
            C.STAGE_REPAIR,
            lines=[{"operation_code": "FRM-1", "labor_type": "FRAME", "guide_hours": 4.5}],
            findings=[{"panel_code": "L_RAIL", "severity": "SEVERE", "structural": True}],
            procedures=[
                {
                    "procedure_code": "RAIL-SECTION",
                    "source": "OEM_PORTAL",
                    "operation_scope": "STRUCTURAL",
                }
            ],
        )
        order_id = world["order_id"]
        record_id = world["procedure_records"][0]["id"]
        assert fx.read_procedure_record(api, record_id)["adherence_documented"] is False

        paint_stall = fx.create_stall(api, name="Paint J", stall_type="PAINT")
        paint_booking = fx.book_stall(
            api, order_id, paint_stall["id"], "REFINISH_CALIBRATION", fx.T1300, fx.T1500
        )

        validate_error(
            api.advance_stage(
                order_id,
                f.stage_advance_payload(C.STAGE_REFINISH_CALIBRATION),
                TECHNICIAN_HEADERS,
            ),
            ApiErrorId.PROCEDURE_ADHERENCE_MISSING.value,
            422,
        )
        A.assert_stage(fx.read_order(api, order_id), C.STAGE_REPAIR)
        assert fx.read_assignment(api, paint_booking["id"])["status"] == "SCHEDULED"

        documented = validate_success(
            api.document_adherence(
                record_id,
                f.adherence_payload(True, adherence_doc_ref="DOC-9039"),
                TECHNICIAN_HEADERS,
            )
        )
        assert documented["adherence_documented"] is True
        assert documented["adherence_doc_ref"] == "DOC-9039"

        advanced = validate_success(
            api.advance_stage(
                order_id,
                f.stage_advance_payload(C.STAGE_REFINISH_CALIBRATION),
                TECHNICIAN_HEADERS,
            )
        )
        A.assert_stage(advanced, C.STAGE_REFINISH_CALIBRATION)
        assert fx.read_assignment(api, paint_booking["id"])["status"] == "ACTIVE"

    def test_a_quote_at_exactly_the_insurer_price_ceiling_is_accepted(self, api):
        """A quote landing exactly on the per-unit ceiling prices the line; one cent over is refused.

        PRD: "One fiscal gate stands in front of it: the `quoted_unit_price_cents` must not exceed the `list_price_cents` multiplied by the insurer program's `parts_price_ceiling_pct`, that product rounded half up to a whole cent."
        PRD: "A quote above that ceiling is refused with `ERR_PARTS_PRICE_CEILING_EXCEEDED`."
        PRD: "`extended_price_cents` is then `unit_extended_cents` multiplied by `qty` less `returned_qty`."
        PRD: "*Pre-tax total.* `pre_tax_total_cents` is `labor_subtotal_cents` plus `supplies_fee_cents` plus `parts_subtotal_cents`."
        PRD: "*The customer's share.* `customer_pay_cents` is `pre_tax_total_cents` less `insurer_authorized_cents`."
        Design: Corner/validations/a_quote_at_exactly_the_insurer_price_ceiling_is_accepted
        """
        world = fx.locked_world(api, order_overrides={"deductible_cents": 25000})
        order_id = world["order_id"]
        labor_line_id = world["line_ids"][0]
        vendor = fx.create_vendor(api, name="Cityline Honda")

        at_ceiling = fx.add_parts_line(
            api,
            labor_line_id,
            part_number="OEM-9040A",
            part_description="Mirror assembly",
            part_type="OEM",
            list_price_cents=10000,
            qty=1,
            vendor_id=vendor["id"],
        )
        over_ceiling = fx.add_parts_line(
            api,
            labor_line_id,
            part_number="OEM-9040B",
            part_description="Mirror glass",
            part_type="OEM",
            list_price_cents=10000,
            qty=1,
            vendor_id=vendor["id"],
        )
        fx.quote_part(api, at_ceiling["id"], vendor["id"], 11000)
        fx.quote_part(api, over_ceiling["id"], vendor["id"], 11001)

        priced = validate_success(
            api.accept_parts_price(at_ceiling["id"], None, PARTS_MANAGER_HEADERS)
        )
        A.assert_parts_line_state(priced, procurement_status="PRICE_LOCKED")
        A.assert_cents(priced["unit_price_cents"], 11000, "unit_price_cents")
        A.assert_extension(priced, 11000, 11000)

        order = fx.read_order(api, order_id)
        A.assert_totals(
            order,
            parts_gross_cents=11000,
            parts_discount_cents=0,
            pre_tax_total_cents=39080,
            insurer_authorized_cents=14080,
            customer_pay_cents=25000,
        )

        validate_error(
            api.accept_parts_price(over_ceiling["id"], None, PARTS_MANAGER_HEADERS),
            ApiErrorId.PARTS_PRICE_CEILING_EXCEEDED.value,
            422,
        )
        refused = fx.read_parts_line(api, over_ceiling["id"])
        A.assert_parts_line_state(refused, procurement_status="QUOTED")
        A.assert_null(refused["unit_price_cents"], "unit_price_cents")
        A.assert_cents(
            fx.read_order(api, order_id)["parts_gross_cents"], 11000, "parts_gross_cents"
        )


class TestLadderOrderAgainstAnAbsentRepairOrder:
    """The early rungs settle the answer before the path identifier is ever resolved."""

    def test_the_role_check_on_a_missing_order_answers_403_not_404(self, api):
        """A technician reaching for the estimator's blueprint is refused on the role alone.

        PRD: "`X-User-Role` is one of the seven declared roles and appears on the endpoint's authorized list — otherwise `ERR_ROLE_NOT_PERMITTED`."
        PRD: "Every endpoint is subject to the validation ladder of §2.5 in that exact order, so an unauthenticated caller is refused before a role check, a role check before a resource lookup, and a lookup before any state or business rule."
        PRD: "Both `X-User-ID` and `X-User-Role` present and non-empty — otherwise `ERR_UNAUTHENTICATED`."
        Design: Corner/validations/role_check_on_a_missing_order_returns_403
        """
        absent = C.ABSENT_UUID

        validate_error(
            api.publish_blueprint(absent, None, TECHNICIAN_HEADERS),
            ApiErrorId.ROLE_NOT_PERMITTED.value,
            403,
        )
        validate_error(
            api.publish_blueprint(absent, None, ESTIMATOR_HEADERS),
            ApiErrorId.REPAIR_ORDER_NOT_FOUND.value,
            404,
        )
        validate_error(
            api.publish_blueprint(absent, None, BLANK_HEADERS),
            ApiErrorId.UNAUTHENTICATED.value,
            401,
        )

    def test_pagination_bounds_on_a_missing_order_answer_400_not_404(self, api):
        """A malformed page request on an absent order is a page error, never a lookup error.

        PRD: "A `limit` below 1, a `limit` above 100, a negative `offset`, or a non-integer value for either is refused with `ERR_INVALID_PAGINATION`."
        PRD: "More generally, every request is evaluated against an ordered ladder of checks, and **the first violated rule decides the response**."
        PRD: "Every endpoint is subject to the validation ladder of §2.5 in that exact order, so an unauthenticated caller is refused before a role check, a role check before a resource lookup, and a lookup before any state or business rule."
        Design: Corner/validations/pagination_bounds_on_a_missing_order_returns_400
        """
        absent = C.ABSENT_UUID

        for params in ({"limit": 0}, {"limit": 101}, {"offset": -1}):
            validate_error(
                api.list_supplements(absent, SHOP_ADMIN_HEADERS, params),
                ApiErrorId.INVALID_PAGINATION.value,
                400,
            )

        validate_error(
            api.list_supplements(absent, SHOP_ADMIN_HEADERS, {"limit": 10}),
            ApiErrorId.REPAIR_ORDER_NOT_FOUND.value,
            404,
        )


class TestReadSurfacesOverTheWork:
    """The listings the shop reverses its lookups through."""

    def test_the_parts_line_listing_filters_by_vendor_and_procurement_status(self, api):
        """Supplier and procurement state narrow the parts listing independently and together.

        PRD: "Parts lines are readable individually and listable with filters on `estimate_line_id`, on `vendor_id` and on `procurement_status`."
        PRD: "Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the envelope's `meta` object."
        Design: Corner/endpoints/the_parts_line_listing_filters_by_vendor_and_procurement_status
        """
        world = fx.locked_world(api)
        labor_line_id = world["line_ids"][0]
        first_vendor = fx.create_vendor(api, name="Vendor One")
        second_vendor = fx.create_vendor(api, name="Vendor Two")

        planned_first = fx.add_parts_line(
            api,
            labor_line_id,
            part_number="OEM-9044A",
            part_description="Door shell",
            part_type="OEM",
            list_price_cents=30000,
            qty=1,
            vendor_id=first_vendor["id"],
        )
        quoted_first = fx.add_parts_line(
            api,
            labor_line_id,
            part_number="OEM-9044B",
            part_description="Door trim",
            part_type="OEM",
            list_price_cents=30000,
            qty=1,
            vendor_id=first_vendor["id"],
        )
        planned_second = fx.add_parts_line(
            api,
            labor_line_id,
            part_number="OEM-9044C",
            part_description="Door handle",
            part_type="OEM",
            list_price_cents=30000,
            qty=1,
            vendor_id=second_vendor["id"],
        )
        fx.quote_part(api, quoted_first["id"], first_vendor["id"], 20000)

        rows, meta = validate_paginated(
            api.list_parts_lines(
                PARTS_MANAGER_HEADERS,
                {"vendor_id": first_vendor["id"], "procurement_status": "PLANNED"},
            )
        )
        A.assert_page(meta, total_count=1)
        A.assert_ids(rows, [planned_first["id"]])

        rows, meta = validate_paginated(
            api.list_parts_lines(
                PARTS_MANAGER_HEADERS, {"vendor_id": first_vendor["id"]}
            )
        )
        A.assert_page(meta, total_count=2)
        assert _ids(rows) == {planned_first["id"], quoted_first["id"]}

        rows, meta = validate_paginated(
            api.list_parts_lines(
                PARTS_MANAGER_HEADERS, {"estimate_line_id": labor_line_id}
            )
        )
        A.assert_page(meta, total_count=3)
        assert _ids(rows) == {
            planned_first["id"],
            quoted_first["id"],
            planned_second["id"],
        }

        rows, meta = validate_paginated(
            api.list_parts_lines(
                PARTS_MANAGER_HEADERS, {"vendor_id": first_vendor["id"], "limit": 1}
            )
        )
        A.assert_page(meta, total_count=2, has_more=True, limit=1, offset=0)
        assert len(rows) == 1
        assert _ids(rows) <= {planned_first["id"], quoted_first["id"]}

        rows, meta = validate_paginated(
            api.list_parts_lines(
                PARTS_MANAGER_HEADERS, {"procurement_status": "INSTALLED"}
            )
        )
        A.assert_page(meta, total_count=0, has_more=False)
        assert rows == []

    def test_the_stage_assignment_listing_resolves_a_stall_back_to_its_bookings(self, api):
        """The stall filter is the only path from a stall to the work booked on it.

        PRD: "The booking belongs to its order via the `repair_order_id` from the path, and bookings are readable individually and listable with filters on `repair_order_id`, on `stall_id` and on `status`."
        PRD: "A stall's `booked_minutes` always equals the sum of `occupied_minutes` over the bookings on that stall whose `status` is `SCHEDULED` or `ACTIVE`; bookings that are `COMPLETED` or `CANCELLED` contribute nothing."
        Design: Corner/endpoints/the_stage_assignment_listing_resolves_a_stall_back_to_its_bookings
        """
        world = fx.locked_world(api)
        order_id = world["order_id"]
        fx.advance_stage(api, order_id, C.STAGE_PARTS_STAGED)

        kept_stall = fx.create_stall(api, name="Body K1", stall_type="BODY")
        released_stall = fx.create_stall(api, name="Body K2", stall_type="BODY")
        kept_booking = fx.book_stall(
            api, order_id, kept_stall["id"], C.STAGE_REPAIR, fx.T0800, fx.T1200
        )
        released_booking = fx.book_stall(
            api, order_id, released_stall["id"], C.STAGE_REPAIR, fx.T0800, fx.T1200
        )
        fx.cancel_assignment(api, released_booking["id"])

        rows, meta = validate_paginated(
            api.list_stage_assignments(
                TECHNICIAN_HEADERS,
                {"stall_id": released_stall["id"], "status": "SCHEDULED"},
            )
        )
        A.assert_page(meta, total_count=0, has_more=False)
        assert rows == []

        rows, meta = validate_paginated(
            api.list_stage_assignments(
                TECHNICIAN_HEADERS, {"stall_id": released_stall["id"]}
            )
        )
        A.assert_page(meta, total_count=1)
        A.assert_ids(rows, [released_booking["id"]])
        assert rows[0]["status"] == "CANCELLED"

        rows, meta = validate_paginated(
            api.list_stage_assignments(
                TECHNICIAN_HEADERS,
                {"stall_id": kept_stall["id"], "status": "SCHEDULED"},
            )
        )
        A.assert_page(meta, total_count=1)
        A.assert_ids(rows, [kept_booking["id"]])

        rows, meta = validate_paginated(
            api.list_stage_assignments(TECHNICIAN_HEADERS, {"repair_order_id": order_id})
        )
        A.assert_page(meta, total_count=2)
        assert _ids(rows) == {kept_booking["id"], released_booking["id"]}

        A.assert_count(
            fx.read_stall(api, kept_stall["id"])["booked_minutes"], 240, "booked_minutes"
        )
        A.assert_count(
            fx.read_stall(api, released_stall["id"])["booked_minutes"],
            0,
            "booked_minutes",
        )

    def test_teardown_findings_are_readable_only_through_the_parent_listing(self, api):
        """The order's findings listing is the whole read surface, and it pages correctly.

        PRD: "Each finding also belongs to its order through the `repair_order_id` taken from the path, and the findings of an order can be listed in creation order."
        PRD: "`limit` caps the number of rows returned; it defaults to 10, may not be smaller than 1, and may not be larger than 100."
        PRD: "An `Estimator` records one finding at a time, each carrying a `panel_code` such as `L_FRONT_DOOR`, a `severity` of `LIGHT`, `MODERATE` or `SEVERE`, and three booleans that all default to false: `requires_blend`, meaning an adjacent panel will need a refinish blend; `adas_component_touched`, meaning the finding disturbs a driver-assistance sensor or its bracket; and `structural`, meaning the finding is on a structural member."
        PRD: "Every subsequent finding leaves `stage` where it is and only raises the count — the transition fires once, on the first finding, not on each one."
        Design: Corner/endpoints/teardown_findings_are_readable_only_through_the_parent_listing
        """
        world = fx.open_order_world(api)
        order_id = world["order_id"]

        first = fx.add_finding(api, order_id, panel_code="L_FRONT_DOOR", severity="MODERATE")
        structural = fx.add_finding(
            api, order_id, panel_code="L_QUARTER_PANEL", severity="SEVERE", structural=True
        )
        blended = fx.add_finding(
            api, order_id, panel_code="R_REAR_BUMPER", severity="LIGHT", requires_blend=True
        )

        rows, meta = validate_paginated(api.list_damage_lines(order_id, ESTIMATOR_HEADERS))
        A.assert_page(meta, total_count=3, has_more=False, limit=10, offset=0)
        assert len(rows) == 3
        assert _ids(rows) == {first["id"], structural["id"], blended["id"]}

        by_id = {row["id"]: row for row in rows}
        assert by_id[structural["id"]]["discovered_at_stage"] == C.STAGE_TEARDOWN
        assert by_id[blended["id"]]["discovered_at_stage"] == C.STAGE_TEARDOWN
        assert by_id[structural["id"]]["structural"] is True
        assert by_id[structural["id"]]["requires_blend"] is False
        assert by_id[blended["id"]]["requires_blend"] is True
        assert by_id[blended["id"]]["structural"] is False

        tail, tail_meta = validate_paginated(
            api.list_damage_lines(order_id, ESTIMATOR_HEADERS, {"limit": 2, "offset": 2})
        )
        A.assert_page(tail_meta, total_count=3, has_more=False, limit=2, offset=2)
        assert len(tail) == 1

        A.assert_count(
            fx.read_order(api, order_id)["teardown_finding_count"],
            3,
            "teardown_finding_count",
        )
