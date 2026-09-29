"""When the owner has to sign, and what a frozen order says when it also busts the budget.

Three stories run through this file. The first is the five-hundred-dollar line in the
sand: an owner's share of 49,999 cents leaves the shop free to keep working, a share of
exactly 50,000 cents demands a signature, and a signature taken at 50,000 survives a
later 50,000 but not a later 50,001. The second is what an adjuster's approval sets in
motion — the supplemented labor operation joins the estimate, the money picture is
rewritten around it, the order freezes on the owner's new share, and the signature the
owner gave against the old share is torn up. The third is the order of the refusals: a
part that cannot be bought both because the order is frozen and because the owner's
exposure has run past the deductible is refused for the freeze, and only once the freeze
is lifted does the shop hear about the budget.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import assertions as A
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import PARTS_MANAGER_HEADERS, TECHNICIAN_HEADERS

# The single BODY 4.5 h plus FRAME 3.0 h estimate the requirements use for their own
# boundary illustration: labor 51,000, supplies 2,040, pre-tax 53,040, no parts at all.
_BOUNDARY_LINES = [
    {"labor_type": "BODY", "guide_hours": 4.5},
    {"labor_type": "FRAME", "guide_hours": 3.0},
]


def _try_advance_to_parts_staged(api, order_id):
    """The stage hop that every posture freeze is visible through, un-validated."""
    return api.advance_stage(
        order_id, f.stage_advance_payload("PARTS_STAGED"), TECHNICIAN_HEADERS
    )


class TestConsentThresholdBoundaryAtEstimateLock:
    """The owner's share against the 50,000-cent consent line, one cent either side."""

    def test_an_owner_share_of_49999_at_lock_leaves_the_shop_free_to_work(self, api):
        """A share one cent under the threshold locks the estimate at posture OPEN.

        PRD: "The comparison is inclusive: a share of exactly 50,000 cents already requires consent, and 49,999 does not."
        PRD: "With a `deductible_cents` of 49,999 the insurer is authorised 3,041 and the owner pays 49,999, which leaves the posture `OPEN`."
        Design: Difficulty/boundary_precision_check/consent_threshold_is_inclusive_at_exactly_50000_on_estimate_lock
        """
        world = fx.locked_world(
            api,
            lines=_BOUNDARY_LINES,
            order_overrides={"deductible_cents": 49999, "initial_authorized_cents": 400000},
        )
        order = fx.read_order(api, world["order_id"])

        A.assert_totals(
            order,
            labor_subtotal_cents=51000,
            supplies_fee_cents=2040,
            pre_tax_total_cents=53040,
            insurer_authorized_cents=3041,
            customer_pay_cents=49999,
        )
        A.assert_posture(order, "OPEN")
        assert order["consent_state"] == "NONE"

        # Observed from the outside: nothing is frozen, so the car moves on.
        validate_success(_try_advance_to_parts_staged(api, world["order_id"]))
        A.assert_stage(fx.read_order(api, world["order_id"]), "PARTS_STAGED")

    def test_an_owner_share_of_exactly_50000_at_lock_already_demands_a_signature(self, api):
        """A share sitting exactly on the threshold freezes the order for consent.

        PRD: "The comparison is inclusive: a share of exactly 50,000 cents already requires consent, and 49,999 does not."
        PRD: "With a `deductible_cents` of 50,000 the insurer is authorised 3,040 and the owner pays 50,000, which makes the posture `CONSENT_REQUIRED` — the threshold is inclusive, so exactly 50,000 cents already requires a signature."
        Design: Difficulty/boundary_precision_check/consent_threshold_is_inclusive_at_exactly_50000_on_estimate_lock
        """
        world = fx.locked_world(
            api,
            lines=_BOUNDARY_LINES,
            order_overrides={"deductible_cents": 50000, "initial_authorized_cents": 400000},
        )
        order = fx.read_order(api, world["order_id"])

        A.assert_totals(
            order,
            labor_subtotal_cents=51000,
            supplies_fee_cents=2040,
            pre_tax_total_cents=53040,
            insurer_authorized_cents=3040,
            customer_pay_cents=50000,
        )
        A.assert_posture(order, "CONSENT_REQUIRED")
        assert order["consent_state"] == "NONE"
        A.assert_null(order["consent_basis_cents"], "consent_basis_cents")

        # The identical hop that the 49,999 order takes freely is refused here.
        validate_error(
            _try_advance_to_parts_staged(api, world["order_id"]),
            ApiErrorId.AUTHORIZATION_POSTURE_BLOCKED.value,
        )

    def test_a_signature_taken_at_50000_survives_50000_but_dies_at_50001(self, api):
        """A consent basis of exactly 50,000 releases the order and then one cent kills it.

        PRD: "A consent recorded at a `consent_basis_cents` of 50,000 survives a later `customer_pay_cents` of 50,000 but is invalidated by 50,001."
        PRD: "Before the posture is chosen, one compensation is applied: if `consent_state` is `CONSENTED` and `consent_basis_cents` is strictly below the current `customer_pay_cents`, that consent is stale and is thrown away — `consent_state` becomes `NONE`, `consent_basis_cents` becomes null, and `consent_alternate_parts` becomes false."
        Design: Difficulty/boundary_precision_check/consent_threshold_is_inclusive_at_exactly_50000_on_estimate_lock
        """
        # A tight insurer authorisation of 3,040 makes the owner's share exactly 50,000
        # over the same 53,040 pre-tax picture, with the deductible well clear of it.
        world = fx.locked_world(
            api,
            lines=_BOUNDARY_LINES,
            order_overrides={"deductible_cents": 25000, "initial_authorized_cents": 3040},
        )
        locked = fx.read_order(api, world["order_id"])
        A.assert_cents(locked["customer_pay_cents"], 50000, "customer_pay_cents")
        A.assert_posture(locked, "CONSENT_REQUIRED")

        fx.record_consent(api, world["order_id"], world["customer_id"], "CONSENT", True)
        consented = fx.read_order(api, world["order_id"])
        assert consented["consent_state"] == "CONSENTED"
        A.assert_cents(consented["consent_basis_cents"], 50000, "consent_basis_cents")
        A.assert_cents(consented["customer_pay_cents"], 50000, "customer_pay_cents")
        # The basis is not strictly below the share, so the signature stands and the
        # order is released.
        A.assert_posture(consented, "OPEN")

        # A single cent of parts pushes the pre-tax total to 53,041 while the insurer
        # stays pinned at its 3,040 authorisation, so the owner's share becomes 50,001.
        vendor = fx.create_vendor(api)
        part = fx.add_parts_line(
            api, world["line_ids"][0], list_price_cents=100, qty=1
        )
        fx.quote_part(api, part["id"], vendor["id"], 1)
        fx.accept_price(api, part["id"])

        order = fx.read_order(api, world["order_id"])
        A.assert_totals(
            order,
            parts_gross_cents=1,
            parts_subtotal_cents=1,
            pre_tax_total_cents=53041,
            insurer_authorized_cents=3040,
            customer_pay_cents=50001,
        )
        assert order["consent_state"] == "NONE"
        A.assert_null(order["consent_basis_cents"], "consent_basis_cents")
        assert order["consent_alternate_parts"] is False
        A.assert_posture(order, "CONSENT_REQUIRED")


def _order_with_a_consent_and_a_pending_supplement_line(api):
    """A signed-off 4.5-hour estimate with a further 4.0-hour operation awaiting the adjuster.

    The locked estimate leaves the owner paying 28,080 cents, comfortably under the
    consent line, and the owner signs at exactly that figure. A supplement for 24,000
    cents is then raised against the order's current version and one more BODY operation
    of 4.0 hours is written underneath it, so the new operation is invisible to every
    total until the adjuster answers.
    """
    world = fx.locked_world(
        api,
        order_overrides={"deductible_cents": 50000, "initial_authorized_cents": 400000},
        insurer_overrides={"supplement_round_limit": 2},
    )
    locked = fx.read_order(api, world["order_id"])
    A.assert_cents(locked["customer_pay_cents"], 28080, "customer_pay_cents")
    A.assert_posture(locked, "OPEN")

    fx.record_consent(api, world["order_id"], world["customer_id"], "CONSENT", False)
    consented = fx.read_order(api, world["order_id"])
    assert consented["consent_state"] == "CONSENTED"
    A.assert_cents(consented["consent_basis_cents"], 28080, "consent_basis_cents")

    world["supplement"] = fx.raise_supplement(
        api, world["order_id"], requested_amount_cents=24000
    )
    world["supplement_line"] = fx.add_estimate_line(
        api,
        world["order_id"],
        labor_type="BODY",
        guide_hours=4.0,
        supplement_id=world["supplement"]["id"],
    )
    assert world["supplement_line"]["line_status"] == "PENDING_SUPPLEMENT"
    A.assert_posture(fx.read_order(api, world["order_id"]), "SUPPLEMENT_PENDING")
    return world


class TestSupplementApprovalCascade:
    """One adjuster decision, four caused hops down the order."""

    def test_approving_a_supplement_promotes_its_operation_and_rewrites_the_money(self, api):
        """The supplemented labor line joins the estimate and drags the totals with it.

        PRD: "Then four caused hops: hop one, every labor line whose `supplement_id` is this supplement and whose `line_status` is `PENDING_SUPPLEMENT` becomes `APPROVED`; hop two, caused by hop one, the `FINAL` refinish allocation, the approved-hours roll-up and the eight-step totals all rerun, so `approved_labor_hours`, `labor_subtotal_cents`, `insurer_authorized_cents`, `pre_tax_total_cents` and `customer_pay_cents` all move; hop three, caused by hop two, the posture derivation reruns on the new `customer_pay_cents` and may set `authorization_posture` to `CONSENT_REQUIRED`; hop four, caused by hop three, a consent recorded earlier whose `consent_basis_cents` now sits below the new `customer_pay_cents` is invalidated, so `consent_state` returns to `NONE`, `consent_basis_cents` returns to null, and `consent_alternate_parts` returns to false."
        PRD: "The **approved-hours roll-up** is simple but load-bearing: `approved_labor_hours` is the sum of `allocated_hours` over the order's labor lines whose `line_status` is `APPROVED` — every labor type, refinish and non-refinish alike — rounded half up to one decimal place."
        Design: Difficulty/transitive_cascade/supplement_approval_cascades_lines_totals_posture_and_stale_consent
        """
        world = _order_with_a_consent_and_a_pending_supplement_line(api)

        fx.decide_supplement(
            api,
            world["supplement"]["id"],
            world["insurer_id"],
            "APPROVE",
            note="hidden damage confirmed",
        )

        supplement = fx.read_supplement(api, world["supplement"]["id"])
        assert supplement["status"] == "APPROVED"
        A.assert_cents(supplement["approved_amount_cents"], 24000, "approved_amount_cents")

        # Hop one: the line the supplement carried is now part of the estimate.
        line = fx.read_estimate_line(api, world["supplement_line"]["id"])
        assert line["line_status"] == "APPROVED"

        # Hop two: 4.5 plus 4.0 approved hours at an effective 6,000 cents.
        order = fx.read_order(api, world["order_id"])
        A.assert_hours(order["approved_labor_hours"], 8.5, "approved_labor_hours")
        A.assert_totals(
            order,
            labor_subtotal_cents=51000,
            supplies_fee_cents=2040,
            pre_tax_total_cents=53040,
            insurer_authorized_cents=3040,
            customer_pay_cents=50000,
        )
        A.assert_customer_pay_split(order)

    def test_approving_a_supplement_freezes_the_order_and_tears_up_the_stale_consent(self, api):
        """The owner's new share crosses the line, so the old signature is worthless.

        PRD: "A **consent gap** exists when `customer_pay_cents` is at or above 50,000 cents *and* either `consent_state` is not `CONSENTED`, or `consent_basis_cents` is null, or `consent_basis_cents` is strictly below the current `customer_pay_cents`."
        PRD: "Before the posture is chosen, one compensation is applied: if `consent_state` is `CONSENTED` and `consent_basis_cents` is strictly below the current `customer_pay_cents`, that consent is stale and is thrown away — `consent_state` becomes `NONE`, `consent_basis_cents` becomes null, and `consent_alternate_parts` becomes false."
        Design: Difficulty/transitive_cascade/supplement_approval_cascades_lines_totals_posture_and_stale_consent
        """
        world = _order_with_a_consent_and_a_pending_supplement_line(api)

        fx.decide_supplement(
            api,
            world["supplement"]["id"],
            world["insurer_id"],
            "APPROVE",
            note="hidden damage confirmed",
        )

        order = fx.read_order(api, world["order_id"])
        # Hop three: the recomputed share of 50,000 sits on the consent line.
        A.assert_cents(order["customer_pay_cents"], 50000, "customer_pay_cents")
        A.assert_posture(order, "CONSENT_REQUIRED")
        # Hop four: the signature taken against 28,080 is thrown away.
        assert order["consent_state"] == "NONE"
        A.assert_null(order["consent_basis_cents"], "consent_basis_cents")
        assert order["consent_alternate_parts"] is False

        # The freeze seen from the outside: the car cannot move on.
        validate_error(
            _try_advance_to_parts_staged(api, world["order_id"]),
            ApiErrorId.AUTHORIZATION_POSTURE_BLOCKED.value,
        )


def _frozen_order_whose_owner_is_already_over_the_deductible(api):
    """A price-locked part on an order that breaks the freeze rule and the budget rule at once.

    The insurer authorised only 1,000 cents against a 25,000-cent deductible, so the
    28,080-cent labour picture already leaves the owner 27,080 out of pocket. A 10,000-cent
    original-equipment part lifts the pre-tax total to 38,080 and the owner's share to
    37,080 — far past the deductible, yet still short of the consent line, so the posture
    is still `OPEN`. A supplement for 5,000 cents is then raised, and that is what freezes
    the order.
    """
    world = fx.locked_world(
        api,
        order_overrides={"deductible_cents": 25000, "initial_authorized_cents": 1000},
        insurer_overrides={"parts_price_ceiling_pct": 1.1, "supplement_round_limit": 2},
    )
    locked = fx.read_order(api, world["order_id"])
    A.assert_cents(locked["customer_pay_cents"], 27080, "customer_pay_cents")
    A.assert_posture(locked, "OPEN")

    world["vendor"] = fx.create_vendor(api)
    world["part"] = fx.add_parts_line(
        api, world["line_ids"][0], part_type="OEM", list_price_cents=10000, qty=1
    )
    fx.quote_part(api, world["part"]["id"], world["vendor"]["id"], 10000)
    fx.accept_price(api, world["part"]["id"])

    priced = fx.read_order(api, world["order_id"])
    A.assert_totals(
        priced,
        parts_gross_cents=10000,
        pre_tax_total_cents=38080,
        insurer_authorized_cents=1000,
        customer_pay_cents=37080,
        deductible_cents=25000,
        betterment_cents=0,
    )
    A.assert_posture(priced, "OPEN")

    world["supplement"] = fx.raise_supplement(
        api, world["order_id"], requested_amount_cents=5000
    )
    A.assert_posture(fx.read_order(api, world["order_id"]), "SUPPLEMENT_PENDING")
    return world


def _try_to_place_the_parts_order(api, parts_line_id):
    """Ask the supplier for the part, un-validated, with a promise a week out."""
    return api.order_parts_line(
        parts_line_id, f.order_payload("2026-08-10T00:00:00Z"), PARTS_MANAGER_HEADERS
    )


class TestOrderFreezeOutranksTheOwnersExposureCeiling:
    """Two rules broken by one purchase order, and which of them answers."""

    def test_a_frozen_order_over_its_exposure_ceiling_reports_the_freeze(self, api):
        """The unsettled supplement answers first, and the budget is never mentioned.

        PRD: "The order's `authorization_posture` must be `OPEN`, or it is refused with `ERR_AUTHORIZATION_POSTURE_BLOCKED`."
        PRD: "The exposure ceiling is deliberately the very last rung: a request that is both frozen by an unsettled money picture and over budget reports the freeze, and a request that is both from a suspended supplier and over budget reports the suspension."
        Design: Difficulty/priority_pair_validation_conflict/order_posture_freeze_outranks_customer_exposure_ceiling
        """
        world = _frozen_order_whose_owner_is_already_over_the_deductible(api)

        validate_error(
            _try_to_place_the_parts_order(api, world["part"]["id"]),
            ApiErrorId.AUTHORIZATION_POSTURE_BLOCKED.value,
        )

        # Both rules were broken, and the money one was the one not reported.
        order = fx.read_order(api, world["order_id"])
        A.assert_cents(order["customer_pay_cents"], 37080, "customer_pay_cents")
        A.assert_cents(order["deductible_cents"], 25000, "deductible_cents")
        # A refused request leaks nothing: the part is still on the shelf.
        A.assert_parts_line_state(
            fx.read_parts_line(api, world["part"]["id"]),
            procurement_status="PRICE_LOCKED",
        )
        A.assert_cents(
            order["parts_ordered_gross_cents"], 0, "parts_ordered_gross_cents"
        )

    def test_the_owners_exposure_ceiling_answers_once_the_freeze_is_lifted(self, api):
        """With the supplement denied the order is open again, and the budget refuses the buy.

        PRD: "And last of all, the order's `customer_pay_cents` must not exceed the sum of its `deductible_cents` and its `betterment_cents`, or the request is refused with `ERR_AUTHORIZED_AMOUNT_EXCEEDED` — the owner's exposure has to stay inside what the insurer authorised and the owner agreed."
        PRD: "State preconditions in this order: the order's `stage` lies in the operation's declared from-state set (`ERR_STAGE_PRECONDITION`); then, for a stage advance, the requested `to_stage` is the declared successor (`ERR_STAGE_SEQUENCE_INVALID`); then the parts line's `procurement_status` lies in the operation's declared from-state set (`ERR_PARTS_LINE_STATE`); then the order's `authorization_posture` is `OPEN` (`ERR_AUTHORIZATION_POSTURE_BLOCKED`); then the supplement is open for the requested action (`ERR_SUPPLEMENT_NOT_OPEN`); then the procedure record's `calibration_status` permits the requested action (`ERR_CALIBRATION_STATE`); then the stall booking is still `SCHEDULED` (`ERR_ASSIGNMENT_NOT_SCHEDULED`)."
        Design: Difficulty/priority_pair_validation_conflict/order_posture_freeze_outranks_customer_exposure_ceiling
        """
        world = _frozen_order_whose_owner_is_already_over_the_deductible(api)

        fx.decide_supplement(
            api, world["supplement"]["id"], world["insurer_id"], "DENY"
        )
        assert fx.read_supplement(api, world["supplement"]["id"])["status"] == "DENIED"

        # The freeze is gone and the money picture is untouched by the denial.
        order = fx.read_order(api, world["order_id"])
        A.assert_posture(order, "OPEN")
        A.assert_cents(order["customer_pay_cents"], 37080, "customer_pay_cents")
        A.assert_cents(order["deductible_cents"], 25000, "deductible_cents")

        validate_error(
            _try_to_place_the_parts_order(api, world["part"]["id"]),
            ApiErrorId.AUTHORIZED_AMOUNT_EXCEEDED.value,
        )
        A.assert_parts_line_state(
            fx.read_parts_line(api, world["part"]["id"]),
            procurement_status="PRICE_LOCKED",
        )
