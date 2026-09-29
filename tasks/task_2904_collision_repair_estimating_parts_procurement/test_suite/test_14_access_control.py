"""Who may act on a repair order, and who is turned away at the door.

Every call into the shop's system carries an acting identity and the capacity it
claims. Four gates stand in front of the work itself: an identity must actually
be presented, the capacity must be one the endpoint recognises, an outside party
must be the program funding the car or the owner of the car, and the person who
wrote the blueprint may never be the person who signs the repair off. Those four
gates answer before any stage, content or money rule underneath them, and this
file walks each of them on orders sitting in the exact state where the rightful
caller would have succeeded.
"""

import pytest

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    ESTIMATOR_HEADERS,
    ESTIMATOR_USER_ID,
    PARTS_MANAGER_HEADERS,
    QC_INSPECTOR_HEADERS,
    QC_INSPECTOR_USER_ID,
    SHOP_ADMIN_HEADERS,
    SHOP_ADMIN_USER_ID,
    TECHNICIAN_HEADERS,
    BLANK_HEADERS,
    headers_with_empty_role,
    headers_with_empty_user_id,
    headers_with_undeclared_role,
    make_customer_headers,
    make_estimator_headers,
    make_insurer_adjuster_headers,
    make_qc_inspector_headers,
)

_OWNER_DEDUCTIBLE_CENTS = 25000


def _assert_declared_supplier_defaults(vendor):
    """Every value the contract declares for a freshly registered supplier."""
    assert vendor["status"] == C.DEFAULT_VENDOR_STATUS, (
        f"status: expected {C.DEFAULT_VENDOR_STATUS}, got {vendor['status']}"
    )
    assert vendor["discount_pct"] == pytest.approx(C.DEFAULT_DISCOUNT_PCT, abs=0.01)
    A.assert_cents(
        vendor["core_charge_cents"], C.DEFAULT_CORE_CHARGE_CENTS, "core_charge_cents"
    )
    assert vendor["restocking_fee_pct"] == pytest.approx(
        C.DEFAULT_RESTOCKING_FEE_PCT, abs=0.01
    )
    A.assert_count(
        vendor["max_qty_per_line"], C.DEFAULT_MAX_QTY_PER_LINE, "max_qty_per_line"
    )
    A.assert_count(
        vendor["order_seq_counter"], C.DEFAULT_ORDER_SEQ_COUNTER, "order_seq_counter"
    )
    A.assert_scores(vendor, C.VENDOR_SCORE_DEFAULT, C.VENDOR_SCORE_DEFAULT)


class TestIdentityAndRoleGates:
    """The first two rungs: an identity must be present, and it must be usable."""

    def test_an_empty_identity_is_refused_before_the_body_or_the_lookup(self, api):
        """Blank acting headers answer 401 even when a better-known reason waits behind them.

        PRD: "If either header is absent, empty, or blank, the request is refused with `ERR_UNAUTHENTICATED`."
        PRD: "Every endpoint is subject to the validation ladder of §2.5 in that exact order, so an unauthenticated caller is refused before a role check, a role check before a resource lookup, and a lookup before any state or business rule."
        Design: Corner/rbac/calls_with_blank_headers_are_unauthenticated
        """
        world = fx.open_order_world(
            api, order_overrides={"deductible_cents": _OWNER_DEDUCTIBLE_CENTS}
        )
        order_id = world["order_id"]

        # Both headers empty strings, on a request that would otherwise succeed.
        validate_error(
            api.get_repair_order(order_id, BLANK_HEADERS),
            ApiErrorId.UNAUTHENTICATED.value,
            401,
        )
        # Either header empty on its own is equally unauthenticated.
        validate_error(
            api.get_repair_order(order_id, headers_with_empty_role(SHOP_ADMIN_USER_ID)),
            ApiErrorId.UNAUTHENTICATED.value,
            401,
        )
        validate_error(
            api.get_repair_order(order_id, headers_with_empty_user_id(C.ROLE_SHOP_ADMIN)),
            ApiErrorId.UNAUTHENTICATED.value,
            401,
        )

        # An order identifier that resolves to nothing is still 401, not 404.
        validate_error(
            api.get_repair_order(C.ABSENT_UUID, BLANK_HEADERS),
            ApiErrorId.UNAUTHENTICATED.value,
            401,
        )

        # A body missing a required field is still 401, not 400.
        intake_without_claim_number = {
            "customer_id": world["customer_id"],
            "insurer_id": world["insurer_id"],
            "vehicle_vin": f.next_vin(),
            "vehicle_model_year": 2019,
            "vehicle_make_model": "Honda Accord",
            "initial_authorized_cents": 400000,
            "deductible_cents": _OWNER_DEDUCTIBLE_CENTS,
        }
        validate_error(
            api.create_repair_order(intake_without_claim_number, BLANK_HEADERS),
            ApiErrorId.UNAUTHENTICATED.value,
            401,
        )

        # An identity that is present but unusable is a different answer entirely.
        validate_error(
            api.get_repair_order(order_id, headers_with_undeclared_role()),
            ApiErrorId.ROLE_NOT_PERMITTED.value,
            403,
        )

        # Nothing was written by any of the refusals.
        untouched = fx.read_order(api, order_id)
        A.assert_stage(untouched, C.STAGE_INTAKE)
        A.assert_version(untouched, 1, "repair order")

    def test_each_stage_of_the_repair_is_written_by_its_own_role_alone(self, api):
        """A caller holding the wrong capacity is refused even where the rightful one would succeed.

        PRD: "A request whose `X-User-Role` is not one of those seven, or is one of those seven but is not on the acting endpoint's authorized list, is refused with `ERR_ROLE_NOT_PERMITTED`."
        PRD: "Every endpoint is subject to the validation ladder of §2.5 in that exact order, so an unauthenticated caller is refused before a role check, a role check before a resource lookup, and a lookup before any state or business rule."
        Design: Corner/rbac/each_roles_exclusive_writes_are_refused_to_the_other_roles
        """
        world = fx.locked_world(
            api, order_overrides={"deductible_cents": _OWNER_DEDUCTIBLE_CENTS}
        )
        order_id = world["order_id"]
        labor_line_id = world["line_ids"][0]
        locked = fx.read_order(api, order_id)
        locked_version = locked["version"]
        A.assert_stage(locked, C.STAGE_ESTIMATE_LOCKED)
        A.assert_posture(locked, C.POSTURE_OPEN)

        part_choice = f.parts_line_payload(
            part_number="OEM-9062",
            part_description="Door shell",
            part_type="OEM",
            list_price_cents=30000,
            qty=1,
        )

        # Parts selection belongs to the parts manager alone.
        validate_error(
            api.create_parts_line(labor_line_id, part_choice, ESTIMATOR_HEADERS),
            ApiErrorId.ROLE_NOT_PERMITTED.value,
            403,
        )
        # Teardown is the estimator's, stage advancement the technician's, release the admin's.
        validate_error(
            api.create_teardown_finding(
                order_id, f.teardown_finding_payload(), PARTS_MANAGER_HEADERS
            ),
            ApiErrorId.ROLE_NOT_PERMITTED.value,
            403,
        )
        validate_error(
            api.advance_stage(
                order_id, f.stage_advance_payload(C.STAGE_PARTS_STAGED), SHOP_ADMIN_HEADERS
            ),
            ApiErrorId.ROLE_NOT_PERMITTED.value,
            403,
        )
        validate_error(
            api.deliver_repair_order(order_id, None, TECHNICIAN_HEADERS),
            ApiErrorId.ROLE_NOT_PERMITTED.value,
            403,
        )

        # The role gate answers before the stage gate that would also have refused these two.
        validate_error(
            api.create_qc_inspection(
                order_id,
                f.qc_inspection_payload(True, 0, scan_report_ref="SCAN-9062"),
                ESTIMATOR_HEADERS,
            ),
            ApiErrorId.ROLE_NOT_PERMITTED.value,
            403,
        )
        validate_error(
            api.create_consent_decision(
                order_id,
                f.consent_decision_payload("CONSENT", False, locked_version),
                SHOP_ADMIN_HEADERS,
            ),
            ApiErrorId.ROLE_NOT_PERMITTED.value,
            403,
        )

        # No refusal left a row behind, and the order never moved.
        _, meta = fx.page(
            api.list_parts_lines(PARTS_MANAGER_HEADERS, {"estimate_line_id": labor_line_id})
        )
        A.assert_page(meta, total_count=0)
        after_refusals = fx.read_order(api, order_id)
        A.assert_stage(after_refusals, C.STAGE_ESTIMATE_LOCKED)
        A.assert_version(after_refusals, locked_version, "repair order")

        # The identical request from the rightful role is accepted.
        accepted = validate_success(
            api.create_parts_line(labor_line_id, part_choice, PARTS_MANAGER_HEADERS), 201
        )
        A.assert_parts_line_state(accepted, procurement_status="PLANNED")

    def test_either_the_admin_or_the_parts_manager_may_register_a_supplier(self, api):
        """Both authorized roles write the same supplier row, and everyone else is refused.

        PRD: "Parts suppliers are registered by either a `ShopAdmin` or a `PartsManager`."
        PRD: "Commercial terms follow: `discount_pct` is the fractional discount off the quoted unit price, at least zero and strictly below one, defaulting to zero; `core_charge_cents` is a per-unit core charge of zero or more, defaulting to zero, that exists for reconditioned cores; `restocking_fee_pct` is the fractional fee the supplier levies on returned units, between zero and one inclusive, defaulting to 0.2; and `max_qty_per_line` is the largest quantity the supplier will accept on a single line order, at least 1, defaulting to 4."
        Design: Corner/rbac/vendor_registration_is_shared_by_shop_admin_and_parts_manager
        """
        owner = fx.create_customer(api)
        program = fx.create_insurer(api)

        admin_registration = f.parts_vendor_payload(
            name="Harbour Honda", vendor_type="OEM_DEALER", part_types_offered=["OEM"]
        )
        by_admin = validate_success(
            api.create_parts_vendor(admin_registration, SHOP_ADMIN_HEADERS), 201
        )

        manager_registration = f.parts_vendor_payload(
            name="Alt Supply Co",
            vendor_type="AFTERMARKET_DISTRIBUTOR",
            part_types_offered=["AFTERMARKET", "RECYCLED"],
        )
        by_manager = validate_success(
            api.create_parts_vendor(manager_registration, PARTS_MANAGER_HEADERS), 201
        )

        # Neither caller gets a privileged row: the declared default block is identical.
        _assert_declared_supplier_defaults(
            fx.read_vendor(api, by_manager["id"], PARTS_MANAGER_HEADERS)
        )
        _assert_declared_supplier_defaults(
            fx.read_vendor(api, by_admin["id"], SHOP_ADMIN_HEADERS)
        )

        # Every other capacity is refused the same registration.
        for headers in (
            ESTIMATOR_HEADERS,
            TECHNICIAN_HEADERS,
            QC_INSPECTOR_HEADERS,
            make_insurer_adjuster_headers(program["id"]),
            make_customer_headers(owner["id"]),
        ):
            validate_error(
                api.create_parts_vendor(
                    f.parts_vendor_payload(name="Interloper Parts"), headers
                ),
                ApiErrorId.ROLE_NOT_PERMITTED.value,
                403,
            )

        # The read side is shared by the same two roles and closed to the rest.
        validate_success(api.get_parts_vendor(by_admin["id"], SHOP_ADMIN_HEADERS))
        validate_success(api.get_parts_vendor(by_admin["id"], PARTS_MANAGER_HEADERS))
        validate_error(
            api.get_parts_vendor(by_admin["id"], TECHNICIAN_HEADERS),
            ApiErrorId.ROLE_NOT_PERMITTED.value,
            403,
        )


class TestOwnershipAndSegregation:
    """The two rungs that read the acting identifier rather than the capacity."""

    def test_an_adjuster_funding_another_program_may_neither_read_nor_answer(self, api):
        """A foreign insurer program is refused the supplement decision and the reads behind it.

        PRD: "The adjuster answers, and only the `InsurerAdjuster` whose `X-User-ID` equals the order's `insurer_id` may do so; anyone else is refused with `ERR_NOT_RESOURCE_OWNER`."
        PRD: "A request that breaks several rules at once returns the error belonging to the earliest rung, which is why the ladder below is normative rather than descriptive:"
        Design: Corner/rbac/an_adjuster_from_another_program_is_not_the_resource_owner
        """
        owner = fx.create_customer(api, full_name="Hal Vex")
        funding_program = fx.create_insurer(api, name="Cornerstone Mutual")
        rival_program = fx.create_insurer(api, name="Rampart Casualty")
        order = fx.create_repair_order(
            api,
            owner["id"],
            funding_program["id"],
            deductible_cents=_OWNER_DEDUCTIBLE_CENTS,
        )
        order_id = order["id"]
        fx.add_finding(api, order_id, panel_code="LT-DOOR", severity="MODERATE")
        fx.add_estimate_line(api, order_id, labor_type="BODY", guide_hours=4.5)
        fx.publish_blueprint(api, order_id)
        fx.lock_estimate(api, order_id)
        supplement = fx.raise_supplement(
            api, order_id, reason_code="HIDDEN_DAMAGE", requested_amount_cents=50000
        )
        supplement_id = supplement["id"]

        funding_adjuster = make_insurer_adjuster_headers(funding_program["id"])
        rival_adjuster = make_insurer_adjuster_headers(rival_program["id"])
        version_before = fx.order_version(api, order_id)

        # The rival holds the role and aims at a genuinely open supplement.
        validate_error(
            api.decide_supplement(
                supplement_id, f.supplement_decision_payload("APPROVE"), rival_adjuster
            ),
            ApiErrorId.NOT_RESOURCE_OWNER.value,
            403,
        )
        still_open = fx.read_supplement(api, supplement_id)
        assert still_open["status"] == "SUBMITTED", (
            f"supplement status: expected SUBMITTED, got {still_open['status']}"
        )
        A.assert_null(still_open["approved_amount_cents"], "approved_amount_cents")
        A.assert_null(still_open["decided_at"], "decided_at")
        A.assert_version(fx.read_order(api, order_id), version_before, "repair order")

        # The same check closes the read side, or a competitor reads an estimate it is not funding.
        validate_error(
            api.get_repair_order(order_id, rival_adjuster),
            ApiErrorId.NOT_RESOURCE_OWNER.value,
            403,
        )
        validate_error(
            api.get_supplement(supplement_id, rival_adjuster),
            ApiErrorId.NOT_RESOURCE_OWNER.value,
            403,
        )
        validate_success(api.get_repair_order(order_id, funding_adjuster))
        validate_success(api.get_supplement(supplement_id, funding_adjuster))

        # The rightful adjuster's identical answer lands.
        decided = validate_success(
            api.decide_supplement(
                supplement_id, f.supplement_decision_payload("APPROVE"), funding_adjuster
            )
        )
        assert decided["status"] == "APPROVED", (
            f"supplement status: expected APPROVED, got {decided['status']}"
        )
        A.assert_cents(decided["approved_amount_cents"], 50000, "approved_amount_cents")

        # Ownership still outranks the fact that the supplement is no longer open.
        validate_error(
            api.decide_supplement(
                supplement_id, f.supplement_decision_payload("APPROVE"), rival_adjuster
            ),
            ApiErrorId.NOT_RESOURCE_OWNER.value,
            403,
        )

    def test_only_the_vehicles_own_owner_may_record_the_consent(self, api):
        """A foreign owner is refused for ownership whether their version is current or stale.

        PRD: "When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks compare the order's `customer_id` to `X-User-ID`, and a mismatch is likewise refused with `ERR_NOT_RESOURCE_OWNER`."
        PRD: "A request that breaks several rules at once returns the error belonging to the earliest rung, which is why the ladder below is normative rather than descriptive:"
        PRD: "A `CONSENT` decision sets `consent_state` to `CONSENTED`, freezes `consent_basis_cents` at the order's *current* `customer_pay_cents` — the figure the owner was actually shown — and sets `consent_alternate_parts` from the supplied `alternate_parts_ok`."
        Design: Corner/rbac/a_customer_may_only_consent_on_their_own_order
        """
        vehicle_owner = fx.create_customer(api, full_name="Ivy Nash")
        stranger = fx.create_customer(api, full_name="Jax Poe")
        program = fx.create_insurer(api, name="Cornerstone Mutual")
        order = fx.create_repair_order(
            api,
            vehicle_owner["id"],
            program["id"],
            deductible_cents=_OWNER_DEDUCTIBLE_CENTS,
        )
        order_id = order["id"]
        fx.add_finding(api, order_id, panel_code="LT-DOOR", severity="MODERATE")
        fx.add_estimate_line(api, order_id, labor_type="BODY", guide_hours=4.5)
        fx.publish_blueprint(api, order_id)
        fx.lock_estimate(api, order_id)

        owner_headers = make_customer_headers(vehicle_owner["id"])
        stranger_headers = make_customer_headers(stranger["id"])
        current_version = fx.order_version(api, order_id)
        decision = f.consent_decision_payload("CONSENT", False, current_version)

        # A perfectly current version does not make the stranger the owner.
        validate_error(
            api.create_consent_decision(order_id, decision, stranger_headers),
            ApiErrorId.NOT_RESOURCE_OWNER.value,
            403,
        )
        untouched = fx.read_order(api, order_id)
        assert untouched["consent_state"] == "NONE", (
            f"consent_state: expected NONE, got {untouched['consent_state']}"
        )
        A.assert_null(untouched["consent_basis_cents"], "consent_basis_cents")
        A.assert_version(untouched, current_version, "repair order")

        # The owner's own share is readable by the owner and by nobody else.
        validate_error(
            api.get_repair_order(order_id, stranger_headers),
            ApiErrorId.NOT_RESOURCE_OWNER.value,
            403,
        )
        owner_view = validate_success(api.get_repair_order(order_id, owner_headers))
        A.assert_cents(
            owner_view["customer_pay_cents"], _OWNER_DEDUCTIBLE_CENTS, "customer_pay_cents"
        )

        # A deliberately superseded version is still an ownership refusal, not a staleness one.
        validate_error(
            api.create_consent_decision(
                order_id,
                f.consent_decision_payload("CONSENT", False, current_version - 1),
                stranger_headers,
            ),
            ApiErrorId.NOT_RESOURCE_OWNER.value,
            403,
        )

        # The identical call from the vehicle's own owner is accepted.
        consented = validate_success(
            api.create_consent_decision(order_id, decision, owner_headers)
        )
        assert consented["consent_state"] == "CONSENTED", (
            f"consent_state: expected CONSENTED, got {consented['consent_state']}"
        )
        A.assert_cents(
            consented["consent_basis_cents"],
            _OWNER_DEDUCTIBLE_CENTS,
            "consent_basis_cents",
        )

    def test_the_estimator_who_blueprinted_the_car_may_not_sign_it_off(self, api):
        """The inspection refusal keys on the acting identifier, not on the capacity claimed.

        PRD: "The acting `X-User-ID` must differ from the order's `blueprint_by_user_id`, or `ERR_SEGREGATION_OF_DUTIES` — the person who wrote the plan may not be the person who signs off on its execution, which is the segregation-of-duties rule of §2.1 in its only enforcement site."
        PRD: "Holding the `QcInspector` role does not rescue the person who blueprinted the order; the check is on the identifier, not on the role."
        Design: Corner/rbac/the_blueprinting_user_cannot_file_the_qc_inspection
        """
        fx.set_clock(api, fx.T0000)
        world = fx.locked_world_at(
            api,
            C.STAGE_READY_FOR_QC,
            order_overrides={"deductible_cents": _OWNER_DEDUCTIBLE_CENTS},
            repair_window=(fx.T0800, fx.T1200),
            refinish_window=(fx.T1300, fx.T1500),
        )
        order_id = world["order_id"]
        waiting = fx.read_order(api, order_id)
        A.assert_stage(waiting, C.STAGE_READY_FOR_QC)
        assert waiting["blueprint_by_user_id"] == ESTIMATOR_USER_ID, (
            "blueprint_by_user_id: expected "
            f"{ESTIMATOR_USER_ID}, got {waiting['blueprint_by_user_id']}"
        )

        blueprinter_as_inspector = make_qc_inspector_headers(ESTIMATOR_USER_ID)
        inspection_request = f.qc_inspection_payload(True, 0, scan_report_ref="SCAN-9065")

        # Byte-identical but for the acting identifier: this one is refused.
        validate_error(
            api.create_qc_inspection(order_id, inspection_request, blueprinter_as_inspector),
            ApiErrorId.SEGREGATION_OF_DUTIES.value,
            403,
        )
        _, meta = fx.page(api.list_qc_inspections(order_id, QC_INSPECTOR_HEADERS))
        A.assert_page(meta, total_count=0)
        A.assert_stage(fx.read_order(api, order_id), C.STAGE_READY_FOR_QC)

        # The refusal sits above the stage gate: a second car, blueprinted by a
        # different estimator and still in repair, answers the same way when that
        # estimator's own identifier files the inspection.
        second = fx.open_order_world(
            api, order_overrides={"deductible_cents": _OWNER_DEDUCTIBLE_CENTS}
        )
        second_id = second["order_id"]
        other_estimator_id = "est-100"
        other_estimator = make_estimator_headers(other_estimator_id)
        fx.add_finding(api, second_id, panel_code="LT-DOOR", severity="MODERATE")
        fx.add_estimate_line(api, second_id, labor_type="BODY", guide_hours=4.5)
        fx.publish_blueprint(api, second_id, other_estimator)
        fx.lock_estimate(api, second_id, other_estimator)
        fx.advance_stage(api, second_id, C.STAGE_PARTS_STAGED)
        body_stall = fx.create_stall(api, name="Body R", stall_type="BODY")
        fx.book_stall(
            api, second_id, body_stall["id"], C.STAGE_REPAIR, fx.T0800, fx.T1200
        )
        fx.advance_stage(api, second_id, C.STAGE_REPAIR)
        mid_repair = fx.read_order(api, second_id)
        A.assert_stage(mid_repair, C.STAGE_REPAIR)
        assert mid_repair["blueprint_by_user_id"] == other_estimator_id, (
            "blueprint_by_user_id: expected "
            f"{other_estimator_id}, got {mid_repair['blueprint_by_user_id']}"
        )
        validate_error(
            api.create_qc_inspection(
                second_id,
                inspection_request,
                make_qc_inspector_headers(other_estimator_id),
            ),
            ApiErrorId.SEGREGATION_OF_DUTIES.value,
            403,
        )

        # Any other inspector files the very same inspection successfully.
        filed = validate_success(
            api.create_qc_inspection(order_id, inspection_request, QC_INSPECTOR_HEADERS), 201
        )
        assert filed["result"] == "PASS", f"result: expected PASS, got {filed['result']}"
        A.assert_count(filed["sequence_number"], 1, "sequence_number")
        assert filed["inspector_user_id"] == QC_INSPECTOR_USER_ID, (
            "inspector_user_id: expected "
            f"{QC_INSPECTOR_USER_ID}, got {filed['inspector_user_id']}"
        )
