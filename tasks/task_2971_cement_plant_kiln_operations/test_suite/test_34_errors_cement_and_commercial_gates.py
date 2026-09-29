"""Breadth coverage of the refusals on the commercial side of the plant: the two substantive
gates on issuing a mill certificate, the five distinct certificate defects a reservation can
carry, the eligibility rule that can leave a distribution plan with nobody to serve, and the
sulphate ceiling a legal gypsum share can still overshoot.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_amount, assert_int
from test_helpers.test_users import (
    ADMIN_HEADERS,
    ENGINEER_HEADERS,
    LAB_HEADERS,
    LOGISTICS_HEADERS,
    QUALITY_HEADERS,
)


def _ground_cement(api):
    """A released run ground into a `GROUND` TYPE_IL batch of 574.72 tonnes with both laboratory
    branches still `PENDING`, so its cement is present but not yet sellable."""
    fx.reset_clock(api)
    env = fx.released_clinker_environment(api)
    env["batch"] = fx.create_ground_batch(
        api, env["plant_id"], env["clinker_silo"]["id"], env["cement_silo"]["id"]
    )
    assert env["batch"]["status"] == "GROUND"
    assert_amount(env["batch"]["cement_tonnes"], 574.72, "cement_tonnes")
    assert_amount(env["batch"]["so3_pct"], 2.85, "so3_pct")
    env["customer"] = fx.create_customer(api)
    return env


def _qualified_cement(api):
    """The same batch carried through both in-specification laboratory branches, so it is
    `QUALIFIED` and its 574.72 tonnes are available in the cement silo."""
    fx.reset_clock(api)
    env = fx.qualified_cement_environment(api)
    assert env["batch"]["status"] == "QUALIFIED"
    assert env["batch"]["cement_type"] == "TYPE_IL"
    assert_amount(env["batch"]["so3_pct"], 2.85, "so3_pct")
    silo = validate_success(api.get_silo(env["cement_silo"]["id"], LOGISTICS_HEADERS))
    assert_amount(silo["available_tonnes"], 574.72, "available_tonnes")
    return env


# ---------------------------------------------------------------------------
# errors: issuing needs a qualified batch and a customer whose spec is met
# ---------------------------------------------------------------------------
def test_a_certificate_cannot_be_issued_against_a_merely_ground_batch(api):
    """Drafting is unguarded — the document may be prepared while the laboratory is still
    working — but issuing it is not, and a `GROUND` batch is refused with a conflict rather than
    an unprocessable-entity, because the obstacle is the subject's state and not the request. The
    two in-specification readings then qualify the batch and the next document issues cleanly.

    PRD: "The batch's `status` must be `QUALIFIED` or already `CERTIFIED`, else
    `ERR_BATCH_NOT_QUALIFIED`; a `GROUND`, `REJECTED` or `DECERTIFIED` batch cannot be certified."

    Design: Corner/errors/certificate_creation_rejects_an_unqualified_batch_and_an_unmet_customer_spec
    """
    env = _ground_cement(api)
    premature = fx.create_draft_certificate(
        api, env["batch"]["id"], env["customer"]["id"], 100.00
    )
    assert premature["status"] == "DRAFT"

    validate_error(
        api.issue_mill_certificate(premature["id"], QUALITY_HEADERS),
        ApiErrorId.ERR_BATCH_NOT_QUALIFIED.value,
        409,
    )

    still_draft = validate_success(
        api.get_mill_certificate(premature["id"], QUALITY_HEADERS)
    )
    assert still_draft["status"] == "DRAFT"
    assert still_draft["issued_at"] is None
    assert still_draft["issued_by_user_id"] is None
    assert still_draft["certified_so3_pct"] is None
    assert_amount(still_draft["allocated_tonnes"], 0.00, "allocated_tonnes")

    unmoved = validate_success(api.get_cement_batch(env["batch"]["id"], ENGINEER_HEADERS))
    assert unmoved["status"] == "GROUND"
    # The refused issue left the batch's status untouched, but the document itself is still
    # DRAFT and PRD 3.7 counts it: "certified_tonnes_allocated is the sum of
    # certified_tonnes across the certificates for that batch whose status is DRAFT or
    # ISSUED". The 100.00 tonnes of the prepared document are therefore already allocated.
    assert_amount(
        unmoved["certified_tonnes_allocated"], 100.00, "certified_tonnes_allocated"
    )

    fx.record_blaine(api, env["batch"]["id"], 400, LAB_HEADERS)
    fx.record_strength(api, env["batch"]["id"], 45.00, LAB_HEADERS)
    qualified = validate_success(
        api.get_cement_batch(env["batch"]["id"], ENGINEER_HEADERS)
    )
    assert qualified["status"] == "QUALIFIED"

    issued = fx.create_issued_certificate(
        api, env["batch"]["id"], env["customer"]["id"], 100.00
    )
    assert issued["status"] == "ISSUED"
    assert_amount(issued["certified_so3_pct"], 2.85, "certified_so3_pct")
    assert_int(
        issued["certified_blaine_m2_per_kg"], 400, "certified_blaine_m2_per_kg"
    )
    assert_amount(issued["certified_strength_mpa"], 45.00, "certified_strength_mpa")

    certified = validate_success(
        api.get_cement_batch(env["batch"]["id"], ENGINEER_HEADERS)
    )
    assert certified["status"] == "CERTIFIED"
    # The lingering DRAFT of 100.00 and the freshly ISSUED 100.00 are both live documents.
    assert_amount(
        certified["certified_tonnes_allocated"], 200.00, "certified_tonnes_allocated"
    )


def test_the_customer_specification_is_two_conditions_and_not_one(api):
    """The batch is TYPE_IL at 2.85 percent sulphate. A customer that only accepts TYPE_I fails
    the type leg, and a customer that accepts TYPE_IL but caps sulphate at 2.50 fails the
    sulphate leg — the second is the one a type-only implementation certifies by mistake, since
    everything about the cement type matches. Only the customer that satisfies both is served.

    PRD: "The customer's specification must be met: the batch's `cement_type` must equal the
    customer's `required_cement_type` **and** the batch's `so3_pct` must be no greater than the
    customer's `max_so3_pct`, else `ERR_CUSTOMER_SPEC_NOT_MET`."

    Design: Corner/errors/certificate_creation_rejects_an_unqualified_batch_and_an_unmet_customer_spec
    """
    env = _qualified_cement(api)
    batch_id = env["batch"]["id"]

    wrong_type = fx.create_customer(
        api,
        name="Type One Only",
        contract_priority=20,
        contract_monthly_tonnes=1000.00,
        required_cement_type="TYPE_I",
        max_so3_pct=3.00,
    )
    low_sulphate = fx.create_customer(
        api,
        name="Low Sulfate Spec",
        contract_priority=30,
        contract_monthly_tonnes=1000.00,
        required_cement_type="TYPE_IL",
        max_so3_pct=2.50,
    )
    satisfied = fx.create_customer(api)
    assert wrong_type["required_cement_type"] == "TYPE_I"
    assert_amount(low_sulphate["max_so3_pct"], 2.50, "max_so3_pct")
    assert satisfied["required_cement_type"] == "TYPE_IL"
    assert_amount(satisfied["max_so3_pct"], 3.00, "max_so3_pct")

    for customer in (wrong_type, low_sulphate):
        draft = fx.create_draft_certificate(api, batch_id, customer["id"], 100.00)
        validate_error(
            api.issue_mill_certificate(draft["id"], QUALITY_HEADERS),
            ApiErrorId.ERR_CUSTOMER_SPEC_NOT_MET.value,
            422,
        )
        refused = validate_success(api.get_mill_certificate(draft["id"], QUALITY_HEADERS))
        assert refused["status"] == "DRAFT"
        assert refused["certified_so3_pct"] is None

    unmoved = validate_success(api.get_cement_batch(batch_id, ENGINEER_HEADERS))
    assert unmoved["status"] == "QUALIFIED"
    # Neither refused document was issued, so the batch never left QUALIFIED; both remain
    # DRAFT though, and PRD 3.7 counts DRAFT alongside ISSUED, so 2 x 100.00 is allocated.
    assert_amount(
        unmoved["certified_tonnes_allocated"], 200.00, "certified_tonnes_allocated"
    )

    accepted = fx.create_issued_certificate(api, batch_id, satisfied["id"], 100.00)
    assert accepted["status"] == "ISSUED"
    assert_amount(accepted["certified_so3_pct"], 2.85, "certified_so3_pct")

    _rows, meta = validate_paginated(
        api.list_mill_certificates(
            QUALITY_HEADERS, params={"cement_batch_id": batch_id, "status": "ISSUED"}
        )
    )
    assert meta["total_count"] == 1


# ---------------------------------------------------------------------------
# errors: five reservation defects that differ only in which field is wrong
# ---------------------------------------------------------------------------
def _certificates_for_reservation(api):
    """A qualified 574.72 tonne batch with two documents against it: one `ISSUED` certificate
    covering 100.00 tonnes for the buyer, and one that is still `DRAFT`."""
    env = _qualified_cement(api)
    env["customer"] = fx.create_customer(api)
    env["issued"] = fx.create_issued_certificate(
        api, env["batch"]["id"], env["customer"]["id"], 100.00
    )
    env["draft"] = fx.create_draft_certificate(
        api, env["batch"]["id"], env["customer"]["id"], 100.00
    )
    assert env["issued"]["status"] == "ISSUED"
    assert env["draft"]["status"] == "DRAFT"
    assert_amount(env["issued"]["allocated_tonnes"], 0.00, "allocated_tonnes")
    return env


def _order(api, env, certificate, tonnes, customer_id=None, silo_id=None):
    return api.create_loadout_order(
        f.loadout_order_payload(
            customer_id or env["customer"]["id"],
            silo_id or env["cement_silo"]["id"],
            certificate["id"],
            certificate["version"],
            tonnes=tonnes,
        ),
        LOGISTICS_HEADERS,
    )


def test_each_certificate_defect_on_a_reservation_has_its_own_code(api):
    """Three refusals whose only difference is which field of the request is wrong: one hundredth
    of a tonne past what the document covers, the right document offered to the wrong buyer, and a
    document that was never issued. The honest hundred tonnes then reserves and takes the
    certificate's allocation to exactly its certified figure, where equality is allowed.

    PRD: "The certificate must be `ISSUED`, else `ERR_CERTIFICATE_NOT_ISSUED`; its `customer_id`
    must equal the order's `customer_id`, else `ERR_CERTIFICATE_CUSTOMER_MISMATCH`; and its
    `allocated_tonnes` plus the new `tonnes` must be no greater than its `certified_tonnes`, with
    equality allowed, else `ERR_CERTIFICATE_ALLOCATION_EXCEEDED`."

    Design: Corner/errors/loadout_order_creation_rejects_every_certificate_defect
    """
    env = _certificates_for_reservation(api)
    other_buyer = fx.create_customer(
        api,
        name="Other Buyer",
        contract_priority=40,
        contract_monthly_tonnes=1000.00,
    )

    validate_error(
        _order(api, env, env["issued"], 100.01),
        ApiErrorId.ERR_CERTIFICATE_ALLOCATION_EXCEEDED.value,
        422,
    )
    validate_error(
        _order(api, env, env["issued"], 50.00, customer_id=other_buyer["id"]),
        ApiErrorId.ERR_CERTIFICATE_CUSTOMER_MISMATCH.value,
        422,
    )
    validate_error(
        _order(api, env, env["draft"], 50.00),
        ApiErrorId.ERR_CERTIFICATE_NOT_ISSUED.value,
        422,
    )

    _rows, meta = validate_paginated(
        api.list_loadout_orders(
            LOGISTICS_HEADERS, params={"cement_silo_id": env["cement_silo"]["id"]}
        )
    )
    assert meta["total_count"] == 0, "no refusal may leave an order behind"
    intact = validate_success(
        api.get_mill_certificate(env["issued"]["id"], LOGISTICS_HEADERS)
    )
    assert_amount(intact["allocated_tonnes"], 0.00, "allocated_tonnes")
    assert intact["version"] == env["issued"]["version"]

    reserved = validate_success(_order(api, env, env["issued"], 100.00), 201)
    assert reserved["status"] == "RESERVED"
    assert_amount(reserved["tonnes"], 100.00, "tonnes")
    assert_amount(reserved["loaded_tonnes"], 0.00, "loaded_tonnes")
    assert_amount(reserved["scheduled_hours"], 2.00, "scheduled_hours")

    allocated = validate_success(
        api.get_mill_certificate(env["issued"]["id"], LOGISTICS_HEADERS)
    )
    assert_amount(allocated["allocated_tonnes"], 100.00, "allocated_tonnes")
    assert allocated["version"] == env["issued"]["version"] + 1

    silo = validate_success(api.get_silo(env["cement_silo"]["id"], LOGISTICS_HEADERS))
    assert_amount(silo["reserved_tonnes"], 100.00, "reserved_tonnes")
    assert_amount(silo["available_tonnes"], 474.72, "available_tonnes")

    buyer = validate_success(api.get_customer(env["customer"]["id"], LOGISTICS_HEADERS))
    assert_amount(buyer["open_reserved_tonnes"], 100.00, "open_reserved_tonnes")


def test_the_silo_is_judged_before_the_certificate_is_ever_read(api):
    """Six hundred tonnes breaches three separate limits at once — the 574.72 tonnes standing in
    the silo, the 100.00 tonnes the certificate covers, and the 500.00 tonnes a two-hour
    appointment on a 250-tonne-per-hour spout could draw — and the answer must be the stock one,
    because availability is read before either of the others. Pointing the same order at the
    clinker silo is refused earlier still, on the kind of material it holds.

    PRD: "The silo must be `OPEN`, else `ERR_SILO_BLOCKED`, and `cement_silo_id` must name a
    `CEMENT` silo of the operation's plant, else `ERR_SILO_KIND_MISMATCH`. The silo's
    `available_tonnes` must cover the reservation, with equality allowed, else
    `ERR_INSUFFICIENT_CEMENT`."

    Design: Corner/errors/loadout_order_creation_rejects_every_certificate_defect
    """
    env = _certificates_for_reservation(api)
    assert_amount(
        env["cement_silo"]["draw_rate_tonnes_per_hour"],
        250.00,
        "draw_rate_tonnes_per_hour",
    )

    validate_error(
        _order(api, env, env["issued"], 600.00),
        ApiErrorId.ERR_INSUFFICIENT_CEMENT.value,
        422,
    )
    validate_error(
        _order(
            api,
            env,
            env["issued"],
            50.00,
            silo_id=env["clinker_silo"]["id"],
        ),
        ApiErrorId.ERR_SILO_KIND_MISMATCH.value,
        422,
    )

    cement_silo = validate_success(
        api.get_silo(env["cement_silo"]["id"], LOGISTICS_HEADERS)
    )
    assert_amount(cement_silo["reserved_tonnes"], 0.00, "reserved_tonnes")
    assert_amount(cement_silo["available_tonnes"], 574.72, "available_tonnes")
    clinker_silo = validate_success(
        api.get_silo(env["clinker_silo"]["id"], LOGISTICS_HEADERS)
    )
    assert clinker_silo["material_kind"] == "CLINKER"
    # The batch has long since been ground, and PRD 3.8 says starting grinding "converts the
    # reservation into a physical draw: the clinker silo's tonnes_on_hand shrinks by
    # clinker_tonnes_drawn and its reserved_tonnes shrinks by the same amount". The 500.00
    # tonne reservation is therefore already gone, and the misdirected order added none.
    assert_amount(clinker_silo["reserved_tonnes"], 0.00, "reserved_tonnes")

    untouched = validate_success(
        api.get_mill_certificate(env["issued"]["id"], LOGISTICS_HEADERS)
    )
    assert_amount(untouched["allocated_tonnes"], 0.00, "allocated_tonnes")
    _rows, meta = validate_paginated(
        api.list_loadout_orders(
            LOGISTICS_HEADERS, params={"mill_certificate_id": env["issued"]["id"]}
        )
    )
    assert meta["total_count"] == 0


# ---------------------------------------------------------------------------
# errors: a plan with nothing to give is fine, one with nobody to serve is not
# ---------------------------------------------------------------------------
def _plant_with_one_buyer(api):
    """A plant whose cement silo is empty and whose only customer is in the plant's own region,
    active and off credit hold: the pool is 0.00 but the eligible set is not."""
    fx.reset_clock(api)
    env = fx.plant_environment(api)
    env["customer"] = fx.create_customer(api)
    assert env["customer"]["region_code"] == env["plant"]["region_code"]
    assert env["customer"]["contract_state"] == "ACTIVE"
    assert env["customer"]["credit_hold"] is False
    return env


def test_a_plan_with_an_empty_pool_is_still_a_plan(api):
    """Nothing has been ground yet, so there is not one tonne to distribute — and the answer is
    still a plan, with the eligible customer named and its entire seasonal demand recorded as
    shortfall. An implementation that treated an empty pool as an error, or that dropped the
    zero-allocation customer from the array, would hide exactly the customer the planner most
    needs to see.

    PRD: "Every eligible customer appears in the `allocations` array — each entry carrying its
    `customer_id`, its `contract_priority`, its `demand_tonnes`, its `allocated_tonnes` and its
    `shortfall_tonnes` — including those that receive 0.00 because the pool ran dry above them."

    Design: Corner/errors/a_distribution_plan_with_no_eligible_customer_is_rejected
    """
    env = _plant_with_one_buyer(api)

    plan = validate_success(
        api.get_distribution_plan(
            env["plant_id"], LOGISTICS_HEADERS, params={"as_of_month": 8}
        )
    )
    assert_amount(plan["available_pool_tonnes"], 0.00, "available_pool_tonnes")
    assert_amount(plan["seasonal_factor"], 1.25, "seasonal_factor")
    assert_amount(plan["total_allocated_tonnes"], 0.00, "total_allocated_tonnes")
    assert_amount(plan["total_shortfall_tonnes"], 5000.00, "total_shortfall_tonnes")

    assert len(plan["allocations"]) == 1
    only = plan["allocations"][0]
    assert only["customer_id"] == env["customer"]["id"]
    assert_int(only["contract_priority"], 10, "contract_priority")
    assert_amount(only["demand_tonnes"], 5000.00, "demand_tonnes")
    assert_amount(only["allocated_tonnes"], 0.00, "allocated_tonnes")
    assert_amount(only["shortfall_tonnes"], 5000.00, "shortfall_tonnes")


def test_each_of_the_three_eligibility_legs_can_empty_the_candidate_set(api):
    """The credit hold and the suspension are refused one at a time, and each is lifted before the
    next is applied, so neither refusal can be explained by the other. The region leg is shown from
    the other side: an out-of-region buyer never enters the array while the local one is active,
    and cannot save the plan once the local one is suspended.

    PRD: "Eligibility is strict: only customers whose `contract_state` is `ACTIVE`, whose
    `credit_hold` is false, and whose `region_code` equals the plant's `region_code` are
    considered. If no customer satisfies all three conditions, the request is refused with
    `ERR_NO_ELIGIBLE_CUSTOMERS` rather than returning an empty plan."

    Design: Corner/errors/a_distribution_plan_with_no_eligible_customer_is_rejected
    """
    env = _plant_with_one_buyer(api)
    customer_id = env["customer"]["id"]

    def plan_response():
        return api.get_distribution_plan(
            env["plant_id"], LOGISTICS_HEADERS, params={"as_of_month": 8}
        )

    validate_success(plan_response())

    validate_success(
        api.patch_customer(customer_id, {"credit_hold": True}, LOGISTICS_HEADERS)
    )
    validate_error(
        plan_response(), ApiErrorId.ERR_NO_ELIGIBLE_CUSTOMERS.value, 422
    )

    validate_success(
        api.patch_customer(
            customer_id,
            {"credit_hold": False, "contract_state": "SUSPENDED"},
            LOGISTICS_HEADERS,
        )
    )
    validate_error(
        plan_response(), ApiErrorId.ERR_NO_ELIGIBLE_CUSTOMERS.value, 422
    )

    validate_success(
        api.patch_customer(customer_id, {"contract_state": "ACTIVE"}, ADMIN_HEADERS)
    )
    restored = validate_success(plan_response())
    assert [row["customer_id"] for row in restored["allocations"]] == [customer_id]

    elsewhere = fx.create_customer(
        api, name="Southwest Ready-Mix", region_code="US-SW", contract_priority=90
    )
    assert elsewhere["region_code"] != env["plant"]["region_code"]
    ignored = validate_success(plan_response())
    assert [row["customer_id"] for row in ignored["allocations"]] == [customer_id], (
        "the higher-priority out-of-region buyer is not a candidate at all"
    )

    validate_success(
        api.patch_customer(
            customer_id, {"contract_state": "SUSPENDED"}, LOGISTICS_HEADERS
        )
    )
    validate_error(
        plan_response(), ApiErrorId.ERR_NO_ELIGIBLE_CUSTOMERS.value, 422
    )

    final = validate_success(api.get_customer(customer_id, LOGISTICS_HEADERS))
    assert final["contract_state"] == "SUSPENDED"
    assert final["credit_hold"] is False
    assert_int(final["version"], 5, "version")


# ---------------------------------------------------------------------------
# errors: the sulphate ceiling is per cement type and read off the computation
# ---------------------------------------------------------------------------
def _released_clinker(api):
    """583.78 released tonnes standing in the clinker silo, ready to be drawn on."""
    fx.reset_clock(api)
    env = fx.released_clinker_environment(api)
    silo = validate_success(api.get_silo(env["clinker_silo"]["id"], ENGINEER_HEADERS))
    assert_amount(silo["available_tonnes"], 583.78, "available_tonnes")
    env["clinker_silo"] = silo
    return env


def _batch_attempt(api, env, **overrides):
    """Plan a batch, echoing the clinker silo's version as it stands at this moment."""
    silo = validate_success(api.get_silo(env["clinker_silo"]["id"], ENGINEER_HEADERS))
    return api.create_cement_batch(
        f.cement_batch_payload(
            env["plant_id"],
            env["clinker_silo"]["id"],
            env["cement_silo"]["id"],
            silo["version"],
            **overrides,
        ),
        ENGINEER_HEADERS,
    )


def test_a_legal_gypsum_share_can_still_overshoot_the_sulphate_ceiling(api):
    """Seven percent gypsum is the top of the permitted band, so nothing about the request is
    malformed — but on 500.00 drawn tonnes it puts 39.77 tonnes of a 46.50 percent sulphate
    material into 568.18 tonnes of cement, which is 3.79 percent against the 3.00 percent a
    `TYPE_I` cement may carry. The identical recipe declared as the rapid-hardening type, whose
    ceiling is 4.50, is accepted with that same 3.79 figure on its face.

    PRD: "The computed `so3_pct` must be no greater than the cement type's sulphate ceiling, with
    equality allowed, else `ERR_SO3_LIMIT_EXCEEDED`; that ceiling is 3.00 percent for `TYPE_I`,
    `TYPE_IL` and `TYPE_II`, and 4.50 percent for the rapid-hardening `TYPE_III`."

    Design: Corner/errors/batch_create_rejects_a_gypsum_share_that_overshoots_the_so3_ceiling
    """
    env = _released_clinker(api)
    version_before = env["clinker_silo"]["version"]

    validate_error(
        _batch_attempt(
            api,
            env,
            cement_type="TYPE_I",
            gypsum_pct=7.00,
            limestone_pct=5.00,
            blaine_target_m2_per_kg=380,
        ),
        ApiErrorId.ERR_SO3_LIMIT_EXCEEDED.value,
        422,
    )

    accepted = validate_success(
        _batch_attempt(
            api,
            env,
            cement_type="TYPE_III",
            gypsum_pct=7.00,
            limestone_pct=5.00,
            blaine_target_m2_per_kg=550,
        ),
        201,
    )
    assert accepted["status"] == "PLANNED"
    assert accepted["cement_type"] == "TYPE_III"
    assert_amount(accepted["total_batch_tonnes"], 568.18, "total_batch_tonnes")
    assert_amount(accepted["gypsum_tonnes"], 39.77, "gypsum_tonnes")
    assert_amount(accepted["limestone_tonnes"], 28.41, "limestone_tonnes")
    assert_amount(accepted["cement_tonnes"], 568.18, "cement_tonnes")
    assert_amount(accepted["so3_pct"], 3.79, "so3_pct")

    _rows, meta = validate_paginated(
        api.list_cement_batches(ENGINEER_HEADERS, params={"plant_id": env["plant_id"]})
    )
    assert meta["total_count"] == 1

    silo = validate_success(api.get_silo(env["clinker_silo"]["id"], ENGINEER_HEADERS))
    assert_amount(silo["reserved_tonnes"], 500.00, "reserved_tonnes")
    assert_amount(silo["available_tonnes"], 83.78, "available_tonnes")
    assert silo["version"] == version_before + 1, (
        "only the accepted batch may touch the silo"
    )


def test_the_gypsum_band_and_the_blaine_band_are_read_before_any_arithmetic(api):
    """One hundredth of a percent past the band turns a 422 into a 400: the envelope check on
    `gypsum_pct` runs before the sulphate ceiling is ever computed, and the same is true at the
    bottom of the band. The Blaine target is the sharper demonstration — 380 m²/kg is refused as
    malformed for a `TYPE_III` batch whose sulphate would have been perfectly legal, because the
    band belongs to the cement type. The batch that respects both bands then computes cleanly.

    PRD: "`gypsum_pct` must lie between 2.00 and 7.00 inclusive and `blaine_target_m2_per_kg` must
    sit inside the cement type's Blaine band from §2.11 — either violation is a shape error and
    yields `ERR_INVALID_REQUEST`."

    Design: Corner/errors/batch_create_rejects_a_gypsum_share_that_overshoots_the_so3_ceiling
    """
    env = _released_clinker(api)
    version_before = env["clinker_silo"]["version"]

    for gypsum_pct in (7.01, 1.99):
        validate_error(
            _batch_attempt(
                api,
                env,
                cement_type="TYPE_I",
                gypsum_pct=gypsum_pct,
                limestone_pct=5.00,
                blaine_target_m2_per_kg=380,
            ),
            ApiErrorId.ERR_INVALID_REQUEST.value,
            400,
        )

    validate_error(
        _batch_attempt(
            api,
            env,
            cement_type="TYPE_III",
            gypsum_pct=7.00,
            limestone_pct=5.00,
            blaine_target_m2_per_kg=380,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )

    _rows, meta = validate_paginated(
        api.list_cement_batches(ENGINEER_HEADERS, params={"plant_id": env["plant_id"]})
    )
    assert meta["total_count"] == 0

    accepted = validate_success(
        _batch_attempt(
            api,
            env,
            cement_type="TYPE_I",
            gypsum_pct=5.00,
            limestone_pct=5.00,
            blaine_target_m2_per_kg=380,
        ),
        201,
    )
    assert accepted["cement_type"] == "TYPE_I"
    assert_amount(accepted["total_batch_tonnes"], 555.56, "total_batch_tonnes")
    assert_amount(accepted["gypsum_tonnes"], 27.78, "gypsum_tonnes")
    assert_amount(accepted["limestone_tonnes"], 27.78, "limestone_tonnes")
    assert_amount(accepted["cement_tonnes"], 555.56, "cement_tonnes")
    assert_amount(accepted["so3_pct"], 2.87, "so3_pct")
    assert_int(accepted["blaine_target_m2_per_kg"], 380, "blaine_target_m2_per_kg")

    silo = validate_success(api.get_silo(env["clinker_silo"]["id"], ENGINEER_HEADERS))
    assert silo["version"] == version_before + 1
    assert_amount(silo["reserved_tonnes"], 500.00, "reserved_tonnes")
