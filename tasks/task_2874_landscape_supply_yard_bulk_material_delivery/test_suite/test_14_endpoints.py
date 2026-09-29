"""Surfaces exercised end to end: the round trip, the bodyless action and the derived reads."""

from __future__ import annotations

import pytest
from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    CENTS,
    assert_charge_assembly,
    assert_claim_case,
    assert_credit_position,
    assert_delivery_truck,
    assert_effective_density,
    assert_job_purchase_order,
    normalize_instant,
)
from test_helpers.factories import create_claim_case_payload
from test_helpers.fixtures import (
    read_account,
    read_order,
    read_purchase_order,
    read_truck,
    seed_account,
    seed_catalogue,
    seed_delivered_load,
    seed_delivery_order,
    seed_purchase_order,
    seed_truck,
    seed_will_call_order,
)
from test_helpers.test_users import (
    make_claims_adjuster_headers,
    make_contractor_headers,
    make_credit_manager_headers,
    make_dispatch_planner_headers,
    make_yard_admin_headers,
    make_yard_loader_headers,
)

FLAT_PRICE = {
    "effective_from": "2026-07-01T00:00:00.000Z",
    "bulk_price_per_cubic_yard_cents": 2000,
    "bagged_price_per_bag_cents": 899,
    "seasonal_surcharge_pct": 0.0,
}
STANDARD_LOT = {"gross_cubic_yards": 100.0, "moisture_pct_at_intake": 15.0}
BIG_LOT = {"gross_cubic_yards": 200.0, "moisture_pct_at_intake": 15.0}


def _stone(sku: str, name: str, **overrides):
    """One aggregate profile at reference moisture, cloned per test."""
    profile = {
        "sku": sku,
        "name": name,
        "offered_forms": ["BULK"],
        "seasonal_category": "AGGREGATE",
        "density_lb_per_cubic_yard": 1000,
        "shrinkage_factor": 0.10,
        "moisture_pct": 15.0,
        "unit_bag_cubic_yards": 0.037,
        "prebuy_eligible": False,
    }
    profile.update(overrides)
    return profile


def _truck_ids(trucks):
    return [truck["id"] for truck in trucks]


def _fleet_of_two(api):
    """One tandem restricted to CLASS_B driveways and one tri-axle restricted to CLASS_A."""
    tandem = seed_truck(
        api,
        truck_code="TND-E1",
        axle_class="TANDEM",
        max_payload_lb=40000,
        bed_capacity_cubic_yards=12.0,
        min_driveway_access_class="CLASS_B",
    )
    tri_axle = seed_truck(
        api,
        truck_code="TRI-E1",
        axle_class="TRI_AXLE",
        max_payload_lb=60000,
        bed_capacity_cubic_yards=20.0,
        min_driveway_access_class="CLASS_A",
    )
    return {"tandem": tandem, "tri_axle": tri_axle}


class TestDeliveryTruckRoundTrip:
    """The one entity with a create, read, list and update surface, walked all four ways."""

    def test_the_status_patch_is_visible_to_the_very_next_filtered_list(self, api):
        """A commissioned truck reads back exactly as commissioned, and one PATCH moves it
        out of the AVAILABLE page and into the OUT_OF_SERVICE page with no lag at all.

        PRD 3.5: "A commissioned truck starts `AVAILABLE`; the planner may later take it out
        of service or return it, moving `status` among `AVAILABLE`, `IN_SERVICE` and
        `OUT_OF_SERVICE` and advancing the truck's `version`."

        PRD 3.5: "Trucks may be listed filtered by `axle_class`, by `status` and by
        `min_driveway_access_class`, and read individually by the planner, the yard admin and
        the loader."

        PRD 2.4: "Filter parameters described alongside individual endpoints combine
        conjunctively: a query naming both a material and a status returns only rows matching
        both."

        PRD 2.4: "The `meta` object of a list response carries `limit` and `offset` echoing
        the effective values used, `total_count` giving the number of rows matching the
        filters before pagination was applied, and `has_more` set to true exactly when rows
        remain beyond the current page."

        PRD 2.6: "There is no background job and no eventual consistency: by the time a 2xx
        response is emitted, every figure the write disturbed has already been recomputed and
        every automatic state transition the new figures imply has already fired."

        Design: Corner/endpoints/truck_create_read_list_and_status_patch_round_trip
        """
        fleet = _fleet_of_two(api)
        tandem_id = fleet["tandem"]["id"]
        tri_axle_id = fleet["tri_axle"]["id"]

        read_back = validate_success(
            api.get_delivery_truck(tandem_id, headers=make_dispatch_planner_headers()), 200
        )
        assert_delivery_truck(read_back)
        assert read_back["truck_code"] == "TND-E1"
        assert read_back["axle_class"] == "TANDEM"
        assert read_back["max_payload_lb"] == 40000
        assert read_back["bed_capacity_cubic_yards"] == pytest.approx(12.00, abs=CENTS)
        assert read_back["min_driveway_access_class"] == "CLASS_B"
        assert read_back["status"] == "AVAILABLE"

        available_tandems, meta = validate_paginated(
            api.list_delivery_trucks(
                headers=make_yard_admin_headers(),
                params={"axle_class": "TANDEM", "status": "AVAILABLE", "limit": 10, "offset": 0},
            )
        )
        # the tri-axle matches the status filter but not the axle filter, so it is excluded
        assert meta["total_count"] == 1
        assert meta["has_more"] is False
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert _truck_ids(available_tandems) == [tandem_id]

        patched = validate_success(
            api.patch_delivery_truck(
                tandem_id, {"status": "OUT_OF_SERVICE"}, headers=make_dispatch_planner_headers()
            ),
            200,
        )
        assert patched["status"] == "OUT_OF_SERVICE"
        assert patched["version"] == fleet["tandem"]["version"] + 1
        assert normalize_instant(patched["updated_at"]) >= normalize_instant(patched["created_at"])

        emptied, emptied_meta = validate_paginated(
            api.list_delivery_trucks(
                headers=make_yard_admin_headers(),
                params={"axle_class": "TANDEM", "status": "AVAILABLE", "limit": 10, "offset": 0},
            )
        )
        # the write is already visible to the very next read
        assert emptied_meta["total_count"] == 0
        assert emptied == []

        parked, parked_meta = validate_paginated(
            api.list_delivery_trucks(
                headers=make_yard_loader_headers(),
                params={"status": "OUT_OF_SERVICE", "limit": 10, "offset": 0},
            )
        )
        assert parked_meta["total_count"] == 1
        assert _truck_ids(parked) == [tandem_id]

        # nothing about the other vehicle moved
        assert read_truck(api, tri_axle_id)["status"] == "AVAILABLE"
        assert read_truck(api, tri_axle_id)["version"] == fleet["tri_axle"]["version"]


def _action_landscapes(api):
    """One account whose single purchase order carries no committed orders at all."""
    account = seed_account(
        api,
        business_name="Action Landscapes",
        credit_limit_cents=500000,
        po_required=False,
        driveway_protection_required=False,
    )
    purchase_order = seed_purchase_order(
        api, account, 100000, po_number="PO-E2-3001", job_code="JOB-E2"
    )
    return {"account": account, "purchase_order": purchase_order}


class TestPurchaseOrderCloseAction:
    """The bodyless action whose whole outcome is decided by the status it finds."""

    def test_the_first_close_lands_and_the_second_is_refused_by_the_same_precondition(self, api):
        """Closing takes no body, so the precondition that admitted the first call is exactly
        the one that turns the second away.

        PRD 3.3: "`committed_cents` is the sum, over the orders tagged to this purchase order
        whose `fulfillment_status` is `CONFIRMED`, `ALLOCATED` or `FULFILLED`, of each order's
        final total where one exists and its quoted total otherwise, minus that order's
        `credit_memo_cents`."

        PRD 3.3: "A `Contractor` or a `YardAdmin` may take the `OPEN -> CLOSED` step on a
        purchase order that is currently `OPEN`, which sets `status` to `CLOSED` and freezes
        `committed_cents` at its then-current value; an `EXHAUSTED` purchase order must first
        fall back to `OPEN` before it can be closed, and any attempt to close one that is not
        `OPEN` is refused with `ERR_PO_NOT_OPEN`."

        Design: Corner/endpoints/purchase_order_close_action_transitions_then_guards_itself
        """
        context = _action_landscapes(api)
        account_id = context["account"]["id"]
        po_id = context["purchase_order"]["id"]

        opened = read_purchase_order(api, po_id)
        assert_job_purchase_order(opened)
        assert opened["status"] == "OPEN"
        # no order is tagged to it, so the sum over tagged orders is empty
        assert opened["committed_cents"] == 0

        closed = validate_success(
            api.close_job_purchase_order(po_id, headers=make_contractor_headers(account_id)), 200
        )
        assert closed["status"] == "CLOSED"
        assert closed["version"] == opened["version"] + 1
        assert closed["committed_cents"] == 0

        validate_error(
            api.close_job_purchase_order(po_id, headers=make_yard_admin_headers()),
            ApiErrorId.PO_NOT_OPEN.value,
            409,
        )

        unchanged = read_purchase_order(api, po_id)
        assert unchanged["status"] == "CLOSED"
        assert unchanged["version"] == closed["version"]
        assert unchanged["committed_cents"] == 0


def _computed_landscapes(api):
    """One confirmed 10.0 cubic-yard will-call order against a single 100 cubic-yard pile."""
    catalogue = seed_catalogue(
        api,
        material=_stone("AGG-E3", "Computed Stone"),
        price=FLAT_PRICE,
        lot=STANDARD_LOT,
    )
    account = seed_account(
        api,
        business_name="Computed Landscapes",
        credit_limit_cents=100000,
        po_required=False,
        driveway_protection_required=False,
    )
    seeded = seed_will_call_order(
        api, account, catalogue["material"]["id"], lines=(("BULK", 10.0),), confirm=True
    )
    return {
        "material": catalogue["material"],
        "lot": catalogue["lot"],
        "account": account,
        "order": seeded["order"],
    }


class TestComputedReads:
    """Three reads that no client ever supplies, all of which must agree after one confirm."""

    def test_the_credit_position_the_material_rollup_and_the_lot_all_agree(self, api):
        """One confirm books 20000 of credit and pins 10.00 cubic yards, and every derived
        read reports its own view of exactly that.

        PRD 3.3: "`credit_used_cents` is the sum, over the account's orders whose
        `fulfillment_status` is `CONFIRMED`, `ALLOCATED` or `FULFILLED` **and** whose
        `settlement_status` is `UNBILLED`, `INVOICED` or `CREDIT_MEMO_ISSUED`, of that order's
        final total where one exists and its quoted total otherwise, minus that order's
        `credit_memo_cents`."

        PRD 3.3: "`credit_available_cents` is then the `credit_limit_cents` minus
        `credit_used_cents`, and it is permitted to go negative -- a delivery that comes in
        heavier than the quote can legitimately push an account past its line."

        PRD 3.3: "`pallet_deposit_balance_cents` is the sum, over every container-return
        record belonging to this account's orders, of that record's `issued_count` multiplied
        by its `deposit_per_unit_cents`, minus its `refund_cents`, minus its
        `forfeited_cents`."

        PRD 3.2: "`available_net_cubic_yards` on a `Material` is the sum, over that material's
        lots whose `status` is `AVAILABLE`, of each lot's `net_sellable_cubic_yards` minus its
        `reserved_cubic_yards`, rounded half up to two decimal places."

        PRD 3.2: "While `basis` is `INTAKE` -- meaning no moisture reading has been filed
        since the lot was scaled in -- `net_sellable_cubic_yards` is the `gross_cubic_yards`
        multiplied by one minus the full `shrinkage_factor` of the material, multiplied by the
        moisture multiplier taken from `moisture_pct_at_intake`, with the product rounded half
        up to two decimal places."

        PRD 3.5: "The material's `effective_density_lb_per_cubic_yard` is its
        `density_lb_per_cubic_yard` multiplied by one plus the quantity obtained by
        subtracting the yard's reference moisture of 15.0 percent from the material's
        `moisture_pct` and dividing by one hundred, with the result rounded half up to two
        decimal places -- wetter material is heavier per cubic yard, and this is the figure
        the scale house actually cares about."

        Design: Corner/endpoints/credit_position_and_available_net_are_computed_reads
        """
        context = _computed_landscapes(api)

        order = read_order(api, context["order"]["id"])
        # 10.00 cubic yards at 2000, no discount tier reached and no delivery leg to charge
        assert order["quoted_total_cents"] == 20000
        assert_charge_assembly(order, 20000)
        assert order["fulfillment_status"] == "CONFIRMED"

        account = validate_success(
            api.get_contractor_account(
                context["account"]["id"], headers=make_credit_manager_headers()
            ),
            200,
        )
        assert_credit_position(account, 20000, 80000)
        # nothing bagged ever left the yard, so no container liability exists
        assert account["pallet_deposit_balance_cents"] == 0
        assert account["account_status"] == "ACTIVE"

        material = validate_success(
            api.get_material(context["material"]["id"], headers=make_dispatch_planner_headers()),
            200,
        )
        # 90.00 sellable on the single AVAILABLE lot less the 10.00 the confirm reserved
        assert material["available_net_cubic_yards"] == pytest.approx(80.00, abs=CENTS)
        # at reference moisture the multiplier is exactly one, so density is unshifted
        assert material["effective_density_lb_per_cubic_yard"] == pytest.approx(1000.00, abs=CENTS)
        assert_effective_density(material)

        lot = validate_success(
            api.get_inventory_lot(context["lot"]["id"], headers=make_yard_admin_headers()), 200
        )
        assert lot["basis"] == "INTAKE"
        # 100.0 gross * (1 - 0.10) * 1.00
        assert lot["net_sellable_cubic_yards"] == pytest.approx(90.00, abs=CENTS)
        assert lot["reserved_cubic_yards"] == pytest.approx(10.00, abs=CENTS)
        assert lot["withdrawn_gross_cubic_yards"] == pytest.approx(0.00, abs=CENTS)
        assert lot["status"] == "AVAILABLE"


def _link_landscapes(api):
    """A fulfilled 6.0 cubic-yard CLASS_A delivery two miles out, run without mats."""
    catalogue = seed_catalogue(
        api, material=_stone("AGG-E4", "Link Stone"), price=FLAT_PRICE, lot=STANDARD_LOT
    )
    account = seed_account(
        api,
        business_name="Link Landscapes",
        credit_limit_cents=5000000,
        po_required=False,
        driveway_protection_required=False,
    )
    seeded = seed_delivery_order(
        api,
        account,
        catalogue["material"]["id"],
        lines=(("BULK", 6.0),),
        driveway_access_class="CLASS_A",
        delivery_distance_miles=2.0,
        delivery_address="4 Link Way",
        confirm=True,
    )
    truck = seed_truck(
        api,
        truck_code="TRI-E4",
        axle_class="TRI_AXLE",
        max_payload_lb=60000,
        bed_capacity_cubic_yards=20.0,
        min_driveway_access_class="CLASS_A",
    )
    load = seed_delivered_load(
        api,
        seeded["order"]["id"],
        truck["id"],
        6.0,
        "2026-08-02T08:00:00.000Z",
        "2026-08-02T09:00:00.000Z",
        driveway_protection_used=False,
        spillage_cubic_yards=0.0,
        dispatcher_user_id="planner-e4",
    )
    return {"account": account, "order": seeded["order"], "load": load}


class TestClaimCrossReferenceLinks:
    """The only row carrying two foreign keys into fulfilment, queried from both sides."""

    def test_the_claim_is_reachable_from_the_load_and_a_bogus_load_mints_nothing(self, api):
        """Filing against the load makes the claim findable by load id, and an unresolvable
        load reference is refused before any claim row exists.

        PRD 3.7: "A `Contractor` files a `ClaimCase` against the order it was billed on,
        naming the `material_order_id`, the `claim_type`, the strictly positive
        `claimed_amount_cents` it is asking for, and a free-text `description` of the damage
        or shortage."

        PRD 3.7: "The claim may optionally point at the specific event it concerns through
        `delivery_load_id` or `will_call_ticket_id`; whichever is supplied must belong to the
        claim's own `material_order_id`, else `ERR_CLAIM_TARGET_MISMATCH`."

        PRD 3.7: "A filed claim starts in `SUBMITTED` with `review_round` at 0, with
        `approved_amount_cents` and `payable_cents` null, with `invoice_offset_cents`,
        `deposit_offset_cents` and `goodwill_credit_cents` at 0, and with
        `decided_by_user_id`, `denial_reason` and `info_request_note` null."

        PRD 3.7: "Claims may be listed filtered by `material_order_id`, by
        `delivery_load_id`, by `will_call_ticket_id`, by `claim_type` and by `status`, and
        read individually by the adjuster, the yard admin and the owning contractor."

        PRD 2.3: "The same catalogue of 404 codes covers foreign keys arriving in a request
        body -- `material_id`, `contractor_account_id`, `job_purchase_order_id`,
        `material_order_id`, `delivery_truck_id`, `delivery_load_id`, `will_call_ticket_id`
        -- and those body references are resolved in the order the endpoint declares its
        input fields, so the first unresolvable reference in declaration order is the one
        reported."

        Design: Corner/endpoints/claim_case_links_order_and_load_and_both_must_exist
        """
        context = _link_landscapes(api)
        account_id = context["account"]["id"]
        order_id = context["order"]["id"]
        load_id = context["load"]["id"]
        contractor = make_contractor_headers(account_id)

        # 12000 bulk with no discount, the 7500 minimum-load fee and 13500 + 2.0 * 425 of haul
        assert read_order(api, order_id)["final_total_cents"] == 33850
        assert read_order(api, order_id)["fulfillment_status"] == "FULFILLED"

        claim = validate_success(
            api.create_claim_case(
                create_claim_case_payload(
                    order_id,
                    "DRIVEWAY_DAMAGE",
                    50000,
                    description="Apron cracked at the curb cut.",
                    delivery_load_id=load_id,
                ),
                headers=contractor,
            ),
            201,
        )
        assert_claim_case(claim)
        assert claim["material_order_id"] == order_id
        assert claim["delivery_load_id"] == load_id
        assert claim["will_call_ticket_id"] is None
        assert claim["status"] == "SUBMITTED"
        assert claim["review_round"] == 0
        assert claim["approved_amount_cents"] is None
        assert claim["payable_cents"] is None
        assert claim["invoice_offset_cents"] == 0
        assert claim["deposit_offset_cents"] == 0
        assert claim["goodwill_credit_cents"] == 0
        assert claim["decided_by_user_id"] is None
        assert claim["denial_reason"] is None
        assert claim["info_request_note"] is None

        from_the_load, load_meta = validate_paginated(
            api.list_claim_cases(
                headers=make_claims_adjuster_headers(),
                params={"delivery_load_id": load_id, "limit": 10, "offset": 0},
            )
        )
        # the association is queryable from the load side, not only from the order side
        assert load_meta["total_count"] == 1
        assert [row["id"] for row in from_the_load] == [claim["id"]]

        validate_error(
            api.create_claim_case(
                create_claim_case_payload(
                    order_id,
                    "SPILLAGE",
                    1000,
                    description="Bogus load reference.",
                    delivery_load_id="00000000-0000-0000-0000-0000000000ff",
                ),
                headers=contractor,
            ),
            ApiErrorId.LOAD_NOT_FOUND.value,
            404,
        )

        from_the_order, order_meta = validate_paginated(
            api.list_claim_cases(
                headers=make_claims_adjuster_headers(),
                params={"material_order_id": order_id, "limit": 10, "offset": 0},
            )
        )
        # the refused request minted nothing
        assert order_meta["total_count"] == 1
        assert [row["id"] for row in from_the_order] == [claim["id"]]


def _ceiling_landscapes(api):
    """Three identical-priced drafts: one untagged, two tagged to a 30000 envelope."""
    catalogue = seed_catalogue(
        api, material=_stone("AGG-E5", "Ceiling Stone"), price=FLAT_PRICE, lot=BIG_LOT
    )
    material_id = catalogue["material"]["id"]
    account = seed_account(
        api,
        business_name="Ceiling Landscapes",
        credit_limit_cents=5000000,
        po_required=False,
        driveway_protection_required=False,
    )
    purchase_order = seed_purchase_order(
        api, account, 30000, po_number="PO-E5-4001", job_code="JOB-E5"
    )
    untagged = seed_will_call_order(api, account, material_id, lines=(("BULK", 20.0),))
    tagged_big = seed_will_call_order(
        api,
        account,
        material_id,
        lines=(("BULK", 20.0),),
        job_purchase_order_id=purchase_order["id"],
    )
    tagged_small = seed_will_call_order(
        api,
        account,
        material_id,
        lines=(("BULK", 10.0),),
        job_purchase_order_id=purchase_order["id"],
    )
    return {
        "account": account,
        "purchase_order": purchase_order,
        "untagged": untagged["order"],
        "tagged_big": tagged_big["order"],
        "tagged_small": tagged_small["order"],
    }


class TestPurchaseOrderCeilingIsConditional:
    """The same 40000 quote passes untagged and is refused the moment it names an envelope."""

    def test_the_envelope_binds_only_the_tagged_order_and_charges_committed_cents(self, api):
        """A 40000 quote confirms freely without a purchase order, is refused against a 30000
        cap when tagged, and a 20000 quote then fits inside the same cap.

        PRD 2.8: "**Purchase-order ceiling** -- at confirm, the purchase order's
        `committed_cents` plus `quoted_total_cents` is at most `po_limit_cents`, exact equality
        accepted, else `ERR_PO_LIMIT_EXCEEDED` (402)."

        PRD 3.4: "And where the order is tagged, the purchase order's `committed_cents` plus
        `quoted_total_cents` must be at most its `po_limit_cents`, again inclusively, else
        `ERR_PO_LIMIT_EXCEEDED`."

        PRD 3.3: "`committed_cents` is the sum, over the orders tagged to this purchase order
        whose `fulfillment_status` is `CONFIRMED`, `ALLOCATED` or `FULFILLED`, of each order's
        final total where one exists and its quoted total otherwise, minus that order's
        `credit_memo_cents`."

        PRD 3.3: "Orders still in `DRAFT` and orders that were `CANCELLED` never consume
        credit, and an order whose `settlement_status` has reached `SETTLED` releases the
        credit it was consuming."

        Design: Corner/endpoints/purchase_order_ceiling_applies_only_to_the_tagged_order
        """
        context = _ceiling_landscapes(api)
        account_id = context["account"]["id"]
        po_id = context["purchase_order"]["id"]
        contractor = make_contractor_headers(account_id)

        untagged = validate_success(
            api.confirm_material_order(context["untagged"]["id"], headers=contractor), 200
        )
        # 20.00 cubic yards at 2000, and no purchase order to charge it against
        assert untagged["quoted_total_cents"] == 40000
        assert untagged["fulfillment_status"] == "CONFIRMED"
        assert untagged["job_purchase_order_id"] is None
        assert read_purchase_order(api, po_id)["committed_cents"] == 0

        validate_error(
            api.confirm_material_order(context["tagged_big"]["id"], headers=contractor),
            ApiErrorId.PO_LIMIT_EXCEEDED.value,
            402,
        )
        refused = read_order(api, context["tagged_big"]["id"])
        assert refused["fulfillment_status"] == "DRAFT"
        assert refused["job_purchase_order_id"] == po_id
        assert read_purchase_order(api, po_id)["committed_cents"] == 0

        tagged_small = validate_success(
            api.confirm_material_order(context["tagged_small"]["id"], headers=contractor), 200
        )
        assert tagged_small["quoted_total_cents"] == 20000
        assert tagged_small["fulfillment_status"] == "CONFIRMED"

        charged = read_purchase_order(api, po_id)
        assert charged["committed_cents"] == 20000
        # 20000 is below the 30000 cap, so the envelope keeps its headroom
        assert charged["status"] == "OPEN"

        # both confirmed orders count against the line; the refused draft never joined it
        assert_credit_position(read_account(api, account_id), 60000, 4940000)
