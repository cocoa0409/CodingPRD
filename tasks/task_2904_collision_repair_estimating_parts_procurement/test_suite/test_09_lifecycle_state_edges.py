"""The edges of the lifecycles: where a repair order, a parts line, a supplement and a
procedure record are allowed to move, and where the shop is told no.

Every case here walks a car (or a calibration, or an insurer negotiation) up to one
particular doorway and then pushes on it: an order still at intake asked to jump straight
to teardown, a blueprint published before anybody has torn the car down, a total loss
declared after the estimate was already committed, a stage skipped, a stage re-entered, a
delivered car asked to accept one more finding, an approved supplement answered twice, and
a calibration result filed on a record that was never booked into a bay. The refusals and
the side effects that must NOT fire are the point of each one.
"""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    ESTIMATOR_HEADERS,
    SHOP_ADMIN_HEADERS,
    TECHNICIAN_HEADERS,
    make_estimator_headers,
    make_insurer_adjuster_headers,
)

BLUEPRINTING_ESTIMATOR = make_estimator_headers("est-100")


class TestIntakeAndBlueprintDoorways:
    """The two ways an order can be pushed too early."""

    def test_newly_created_rows_open_in_their_declared_initial_states(self, api):
        """A fresh order rests at intake, and a fresh procedure record's calibration state follows its own flag.

        PRD: "On creation the order's `checkin_at` is stamped from the logical clock, opening the cycle-time window; `stage` is `INTAKE`, `authorization_posture` is `OPEN`, `consent_state` is `NONE`, and `version` is 1."
        PRD: "At creation, a record whose `requires_calibration` is false is born at `calibration_status` `NOT_REQUIRED` and stays there permanently; a record whose `requires_calibration` is true is born at `REQUIRED`."
        Design: Corner/state_machines/newly_created_rows_start_in_their_declared_initial_states
        """
        customer = fx.create_customer(
            api, full_name="Nia Ash", phone="555-1013", email="nia@example.com"
        )
        insurer = fx.create_insurer(
            api,
            insurer_code="CRNR-13",
            name="Cornerstone Mutual",
            rate_ceiling_cents=C.CEILINGS_BELOW_POSTED,
        )
        order = fx.create_repair_order(
            api,
            customer["id"],
            insurer["id"],
            claim_number="CLM-90017",
            vehicle_vin="1HGCV1F30LA090017",
            vehicle_model_year=2019,
            vehicle_make_model="Honda Accord",
            initial_authorized_cents=400000,
            deductible_cents=25000,
        )
        A.assert_stage(order, C.STAGE_INTAKE)
        A.assert_posture(order, C.POSTURE_OPEN)
        assert order["consent_state"] == "NONE", (
            f"consent_state must open at NONE, got {order['consent_state']!r}"
        )
        A.assert_version(order, 1, "repair order")

        plain = fx.add_procedure_record(
            api,
            order["id"],
            procedure_code="SEAM-SEAL",
            source="ALLDATA",
            operation_scope="STRUCTURAL",
        )
        calibrated = fx.add_procedure_record(
            api,
            order["id"],
            procedure_code="ADAS-CAL-Z",
            source="OEM_PORTAL",
            operation_scope="ADAS",
            requires_calibration=True,
            calibration_type="STATIC",
        )

        assert calibrated["calibration_status"] == "REQUIRED", (
            "a record demanding calibration is born at REQUIRED, got "
            f"{calibrated['calibration_status']!r}"
        )
        for field in ("bay_id", "window_start", "window_end", "post_scan_dtc_count"):
            A.assert_null(calibrated[field], f"unbooked procedure record {field}")
        assert plain["calibration_status"] == "NOT_REQUIRED", (
            "a record with the flag defaulted lands directly in the terminal "
            f"NOT_REQUIRED, got {plain['calibration_status']!r}"
        )

        # Intake is left by recording a finding, not by asking for the next stage.
        refused = api.advance_stage(
            order["id"], f.stage_advance_payload(C.STAGE_TEARDOWN), TECHNICIAN_HEADERS
        )
        validate_error(refused, ApiErrorId.STAGE_SEQUENCE_INVALID.value, 409)
        A.assert_stage(fx.read_order(api, order["id"]), C.STAGE_INTAKE)

    def test_a_blueprint_before_any_finding_is_refused_for_missing_findings(self, api):
        """An untorn-down car cannot be blueprinted, and the refusal leaves no blueprint behind.

        PRD: "The order must have at least one teardown finding, and an order with a `teardown_finding_count` of zero is refused with `ERR_NO_TEARDOWN_FINDINGS` — the only refusal an `INTAKE` order can receive here."
        PRD: "It stamps `blueprint_by_user_id` with the acting `X-User-ID`, which is the segregation-of-duties key consumed much later at quality control."
        Design: Corner/state_machines/blueprint_before_any_teardown_finding_is_refused_for_missing_findings
        """
        world = fx.open_order_world(
            api,
            customer_overrides={
                "full_name": "Oli Bex",
                "phone": "555-1014",
                "email": "oli@example.com",
            },
            insurer_overrides={
                "insurer_code": "CRNR-14",
                "name": "Cornerstone Mutual",
                "rate_ceiling_cents": C.CEILINGS_BELOW_POSTED,
            },
            order_overrides={
                "claim_number": "CLM-90018",
                "vehicle_vin": "1HGCV1F30LA090018",
                "vehicle_make_model": "Honda Accord",
                "initial_authorized_cents": 400000,
                "deductible_cents": 25000,
            },
        )
        order_id = world["order_id"]
        version_before = fx.order_version(api, order_id)
        A.assert_count(world["order"]["teardown_finding_count"], 0, "teardown_finding_count")

        refused = api.publish_blueprint(order_id, None, BLUEPRINTING_ESTIMATOR)
        validate_error(refused, ApiErrorId.NO_TEARDOWN_FINDINGS.value, 422)

        untouched = fx.read_order(api, order_id)
        A.assert_stage(untouched, C.STAGE_INTAKE)
        A.assert_null(untouched["blueprint_by_user_id"], "blueprint_by_user_id")
        A.assert_hours(
            untouched["refinish_hours_provisional"], 0.0, "refinish_hours_provisional"
        )
        A.assert_version(untouched, version_before, "repair order")

        # One finding is all it takes; the identical call then lands.
        fx.add_finding(api, order_id, panel_code="LT-DOOR", severity="MODERATE")
        published = get_success_data(
            api.publish_blueprint(order_id, None, BLUEPRINTING_ESTIMATOR)
        )
        A.assert_stage(published, C.STAGE_BLUEPRINTED)
        assert published["blueprint_by_user_id"] == "est-100", (
            "the publishing estimator's identifier must be recorded verbatim, got "
            f"{published['blueprint_by_user_id']!r}"
        )


def _locked_body_order(api, claim_number: str, vin: str, customer: dict, insurer_code: str):
    """A committed estimate carrying the one 4.5-hour body operation the contract works through."""
    return fx.locked_world(
        api,
        customer_overrides=customer,
        insurer_overrides={
            "insurer_code": insurer_code,
            "name": "Cornerstone Mutual",
            "rate_ceiling_cents": C.CEILINGS_BELOW_POSTED,
        },
        order_overrides={
            "claim_number": claim_number,
            "vehicle_vin": vin,
            "vehicle_make_model": "Honda Accord",
            "initial_authorized_cents": 400000,
            "deductible_cents": 25000,
        },
        findings=[{"panel_code": "LT-DOOR", "severity": "MODERATE"}],
        lines=[{"operation_code": "BDY-1", "labor_type": "BODY", "guide_hours": 4.5}],
    )


class TestTheTwoWaysOutOfABlueprint:
    """Once the estimate is committed the shop is committed with it."""

    def test_a_total_loss_after_the_estimate_is_locked_is_refused_on_the_stage_precondition(
        self, api
    ):
        """A car cannot be written off once its estimate has been committed, and no line is voided.

        PRD: "The order must be at `BLUEPRINTED`, or the declaration is refused with `ERR_STAGE_PRECONDITION`."
        PRD: "Hop one, requested directly: every labor line whose `line_status` is `DRAFT` or `PENDING_SUPPLEMENT` becomes `VOID`, and every parts line whose `procurement_status` is `PLANNED`, `QUOTED`, `COUNTERED` or `PRICE_LOCKED` becomes `VOID`."
        Design: Corner/state_machines/total_loss_from_estimate_locked_is_refused_on_stage_precondition
        """
        world = _locked_body_order(
            api,
            "CLM-90019",
            "1HGCV1F30LA090019",
            {"full_name": "Pat Cyr", "phone": "555-1015", "email": "pat@example.com"},
            "CRNR-15",
        )
        order_id = world["order_id"]
        line_id = world["line_ids"][0]
        A.assert_stage(world["order"], C.STAGE_ESTIMATE_LOCKED)

        refused = api.declare_total_loss(
            order_id,
            f.total_loss_payload(total_loss_note="frame rail beyond repair"),
            ESTIMATOR_HEADERS,
        )
        validate_error(refused, ApiErrorId.STAGE_PRECONDITION.value, 409)

        untouched = fx.read_order(api, order_id)
        A.assert_stage(untouched, C.STAGE_ESTIMATE_LOCKED)
        A.assert_null(untouched["total_loss_note"], "total_loss_note")

        line = fx.read_estimate_line(api, line_id)
        assert line["line_status"] == "APPROVED", (
            f"the approved body line must survive the refusal, got {line['line_status']!r}"
        )
        A.assert_hours(line["allocated_hours"], 4.5, "allocated_hours")
        A.assert_cents(line["line_amount_cents"], 27000, "line_amount_cents")

        # The void cascade never ran, so the locked money picture is exactly as committed.
        A.assert_totals(
            untouched,
            labor_subtotal_cents=27000,
            supplies_fee_cents=1080,
            pre_tax_total_cents=28080,
            insurer_authorized_cents=3080,
            customer_pay_cents=25000,
        )
        A.assert_posture(untouched, C.POSTURE_OPEN)


class TestDrivingTheStages:
    """The successor map admits exactly one next stage, and it admits it exactly once."""

    def test_skipping_the_parts_staged_hop_is_refused_as_out_of_sequence(self, api):
        """From a committed estimate the only legal next stage is parts staged; jumping ahead is refused.

        PRD: "Any other pair, including an attempt to re-enter the current stage and any attempt to skip a stage, is refused with `ERR_STAGE_SEQUENCE_INVALID`."
        PRD: "`PARTS_STAGED` follows `ESTIMATE_LOCKED`."
        Design: Corner/state_machines/stage_advance_skipping_parts_staged_is_refused_as_out_of_sequence
        """
        world = _locked_body_order(
            api,
            "CLM-90020",
            "1HGCV1F30LA090020",
            {"full_name": "Quin Dae", "phone": "555-1016", "email": "quin@example.com"},
            "CRNR-16",
        )
        order_id = world["order_id"]
        version_before = fx.order_version(api, order_id)

        for skipped in (C.STAGE_REPAIR, C.STAGE_READY_FOR_QC):
            refused = api.advance_stage(
                order_id, f.stage_advance_payload(skipped), TECHNICIAN_HEADERS
            )
            validate_error(refused, ApiErrorId.STAGE_SEQUENCE_INVALID.value, 409)
            still_locked = fx.read_order(api, order_id)
            A.assert_stage(still_locked, C.STAGE_ESTIMATE_LOCKED)
            A.assert_version(still_locked, version_before, "repair order")

        advanced = fx.advance_stage(api, order_id, C.STAGE_PARTS_STAGED)
        A.assert_stage(advanced, C.STAGE_PARTS_STAGED)

    def test_repeating_an_accepted_advance_is_refused_the_second_time(self, api):
        """Re-entering the stage the order already occupies is an out-of-sequence request.

        PRD: "Any other pair, including an attempt to re-enter the current stage and any attempt to skip a stage, is refused with `ERR_STAGE_SEQUENCE_INVALID`."
        PRD: "No side effect of any kind is applied when a check fails."
        Design: Corner/state_machines/repeating_an_accepted_stage_advance_is_refused_the_second_time
        """
        world = _locked_body_order(
            api,
            "CLM-90021",
            "1HGCV1F30LA090021",
            {"full_name": "Rex Eno", "phone": "555-1017", "email": "rex@example.com"},
            "CRNR-17",
        )
        order_id = world["order_id"]

        staged = fx.advance_stage(api, order_id, C.STAGE_PARTS_STAGED)
        A.assert_stage(staged, C.STAGE_PARTS_STAGED)
        version_after_first = staged["version"]

        replayed = api.advance_stage(
            order_id, f.stage_advance_payload(C.STAGE_PARTS_STAGED), TECHNICIAN_HEADERS
        )
        validate_error(replayed, ApiErrorId.STAGE_SEQUENCE_INVALID.value, 409)

        unmoved = fx.read_order(api, order_id)
        A.assert_stage(unmoved, C.STAGE_PARTS_STAGED)
        A.assert_version(unmoved, version_after_first, "repair order")


class TestTerminalLockdown:
    """A released car and a written-off car are both closed books."""

    def test_a_delivered_order_rejects_every_further_mutation(self, api):
        """Releasing the vehicle issues the warranty, empties both stalls and locks the whole aggregate.

        PRD: "The order is neither `DELIVERED` nor `TOTAL_LOSS` — otherwise `ERR_ORDER_TERMINAL`."
        PRD: "The `warranty_expires_at` is the logical clock at the moment of the pass plus exactly 365 days, treating a day as 86,400 seconds with no calendar or leap adjustment."
        Design: Corner/state_machines/delivered_order_rejects_every_further_mutation
        """
        fx.set_clock(api, C.CLOCK_DEFAULT)
        world = fx.locked_world_at(
            api,
            C.STAGE_READY_FOR_QC,
            customer_overrides={
                "full_name": "Sam Fry",
                "phone": "555-1018",
                "email": "sam@example.com",
            },
            insurer_overrides={
                "insurer_code": "CRNR-18",
                "name": "Cornerstone Mutual",
                "rate_ceiling_cents": C.CEILINGS_BELOW_POSTED,
            },
            order_overrides={
                "claim_number": "CLM-90022",
                "vehicle_vin": "1HGCV1F30LA090022",
                "vehicle_make_model": "Honda Accord",
                "initial_authorized_cents": 400000,
                "deductible_cents": 25000,
            },
            findings=[{"panel_code": "LT-DOOR", "severity": "MODERATE"}],
            lines=[{"operation_code": "BDY-1", "labor_type": "BODY", "guide_hours": 4.5}],
            repair_window=(fx.T0800, fx.T1200),
            refinish_window=(fx.T1300, fx.T1500),
        )
        order_id = world["order_id"]
        fx.delivered_world(api, world)

        delivered = fx.read_order(api, order_id)
        A.assert_stage(delivered, C.STAGE_DELIVERED)
        A.assert_instant(delivered["delivered_at"], C.CLOCK_DEFAULT, "delivered_at")

        inspection = world["qc_inspection"]
        assert inspection["result"] == "PASS", (
            f"a clean checklist with no codes is a PASS, got {inspection['result']!r}"
        )
        A.assert_count(inspection["sequence_number"], 1, "sequence_number")
        A.assert_null(inspection["failure_reason"], "failure_reason")
        assert inspection["warranty_certificate_number"] == "WC-CLM-90022-1", (
            "the certificate composes the claim number and the sequence number, got "
            f"{inspection['warranty_certificate_number']!r}"
        )
        A.assert_instant(
            inspection["warranty_expires_at"],
            "2027-08-01T00:00:00Z",
            "warranty_expires_at",
        )
        A.assert_warranty(inspection, "CLM-90022", C.CLOCK_DEFAULT)

        # Both occupancies are retired and neither stall is holding minutes for this car.
        for key in ("repair_assignment", "refinish_assignment"):
            booking = fx.read_assignment(api, world[key]["id"])
            assert booking["status"] == "COMPLETED", (
                f"{key} must be COMPLETED after release, got {booking['status']!r}"
            )
        for stall_key in ("body_stall", "paint_stall"):
            stall = fx.read_stall(api, world[stall_key]["id"])
            A.assert_count(stall["booked_minutes"], 0, f"{stall_key} booked_minutes")

        # A new finding, a second release and a further hop are all refused alike.
        refused_finding = api.create_teardown_finding(
            order_id,
            f.teardown_finding_payload(panel_code="RT-DOOR", severity="LIGHT"),
            ESTIMATOR_HEADERS,
        )
        validate_error(refused_finding, ApiErrorId.ORDER_TERMINAL.value, 409)
        A.assert_count(
            fx.read_order(api, order_id)["teardown_finding_count"],
            1,
            "teardown_finding_count",
        )

        refused_delivery = api.deliver_repair_order(order_id, None, SHOP_ADMIN_HEADERS)
        validate_error(refused_delivery, ApiErrorId.ORDER_TERMINAL.value, 409)

        refused_hop = api.advance_stage(
            order_id, f.stage_advance_payload(C.STAGE_REPAIR), TECHNICIAN_HEADERS
        )
        validate_error(refused_hop, ApiErrorId.ORDER_TERMINAL.value, 409)

    def test_a_total_loss_voids_unordered_parts_and_releases_the_stall(self, api):
        """Writing the car off voids the open lines, hands the stall's minutes back and reopens the posture.

        PRD: "Hop one, requested directly: every labor line whose `line_status` is `DRAFT` or `PENDING_SUPPLEMENT` becomes `VOID`, and every parts line whose `procurement_status` is `PLANNED`, `QUOTED`, `COUNTERED` or `PRICE_LOCKED` becomes `VOID`."
        PRD: "Alongside the cascade, every stall booking on the order whose `status` is `SCHEDULED` or `ACTIVE` becomes `CANCELLED`, and each cancellation lowers that stall's `booked_minutes` by that booking's `occupied_minutes`."
        Design: Corner/state_machines/total_loss_voids_unordered_parts_and_releases_the_stall
        """
        world = fx.blueprinted_world(
            api,
            customer_overrides={
                "full_name": "Tia Gil",
                "phone": "555-1019",
                "email": "tia@example.com",
            },
            insurer_overrides={
                "insurer_code": "CRNR-19",
                "name": "Cornerstone Mutual",
                "rate_ceiling_cents": C.CEILINGS_BELOW_POSTED,
            },
            order_overrides={
                "claim_number": "CLM-90023",
                "vehicle_vin": "1HGCV1F30LA090023",
                "vehicle_make_model": "Honda Accord",
                "initial_authorized_cents": 400000,
                "deductible_cents": 25000,
            },
            findings=[
                {"panel_code": "LT-QTR", "severity": "SEVERE", "structural": True}
            ],
        )
        order_id = world["order_id"]
        finding_id = world["findings"][0]["id"]

        body_line = fx.add_estimate_line(
            api,
            order_id,
            damage_line_id=finding_id,
            operation_code="BDY-1",
            labor_type="BODY",
            guide_hours=4.5,
        )
        refinish_line = fx.add_estimate_line(
            api,
            order_id,
            damage_line_id=finding_id,
            operation_code="RFN-1",
            labor_type="REFINISH",
            guide_hours=2.0,
        )
        part = fx.add_parts_line(
            api,
            body_line["id"],
            part_number="OEM-9002",
            part_description="Quarter panel",
            part_type="OEM",
            list_price_cents=50000,
            qty=1,
        )
        stall = fx.create_stall(api, name="Body G", stall_type="BODY")
        booking = fx.book_stall(
            api, order_id, stall["id"], C.STAGE_REPAIR, fx.T0800, fx.T1200
        )
        A.assert_count(booking["occupied_minutes"], 240, "occupied_minutes")
        A.assert_count(
            fx.read_stall(api, stall["id"])["booked_minutes"], 240, "booked_minutes"
        )

        note = "unibody deformation beyond published tolerances"
        totalled = fx.declare_total_loss(api, order_id, total_loss_note=note)
        A.assert_stage(totalled, C.STAGE_TOTAL_LOSS)
        assert totalled["total_loss_note"] == note, (
            f"total_loss_note must be recorded verbatim, got {totalled['total_loss_note']!r}"
        )

        for line_id, label in ((body_line["id"], "body line"), (refinish_line["id"], "refinish line")):
            line = fx.read_estimate_line(api, line_id)
            assert line["line_status"] == "VOID", (
                f"the draft {label} must be VOID, got {line['line_status']!r}"
            )

        voided_part = fx.read_parts_line(api, part["id"])
        A.assert_parts_line_state(voided_part, procurement_status="VOID")
        A.assert_cents(voided_part["extended_price_cents"], 0, "extended_price_cents")

        released = fx.read_assignment(api, booking["id"])
        assert released["status"] == "CANCELLED", (
            f"the scheduled booking must be CANCELLED, got {released['status']!r}"
        )
        A.assert_count(
            fx.read_stall(api, stall["id"])["booked_minutes"], 0, "booked_minutes"
        )

        A.assert_hours(totalled["approved_labor_hours"], 0.0, "approved_labor_hours")
        A.assert_totals(
            totalled,
            labor_subtotal_cents=0,
            parts_gross_cents=0,
            pre_tax_total_cents=0,
            insurer_authorized_cents=0,
            customer_pay_cents=0,
        )
        A.assert_posture(totalled, C.POSTURE_OPEN)

        refused = api.create_teardown_finding(
            order_id,
            f.teardown_finding_payload(panel_code="RT-DOOR", severity="LIGHT"),
            ESTIMATOR_HEADERS,
        )
        validate_error(refused, ApiErrorId.ORDER_TERMINAL.value, 409)


class TestNegotiationAndCalibrationLockdown:
    """A settled supplement and a passed calibration are both done being argued with."""

    def test_a_second_decision_on_an_approved_supplement_is_refused_as_not_open(self, api):
        """Once the adjuster has approved a supplement they cannot change their mind, and the money stands.

        PRD: "The supplement's `status` must be `SUBMITTED`, or the answer is refused with `ERR_SUPPLEMENT_NOT_OPEN`."
        PRD: "The supplement's `status` must be `INFO_REQUESTED`, or the resubmission is refused with `ERR_SUPPLEMENT_NOT_OPEN`."
        Design: Corner/state_machines/second_decision_on_an_approved_supplement_is_refused_as_not_open
        """
        world = _locked_body_order(
            api,
            "CLM-90024",
            "1HGCV1F30LA090024",
            {"full_name": "Uma Hoy", "phone": "555-1020", "email": "uma@example.com"},
            "CRNR-20",
        )
        order_id = world["order_id"]
        insurer_id = world["insurer_id"]

        supplement = fx.raise_supplement(
            api, order_id, reason_code="HIDDEN_DAMAGE", requested_amount_cents=24000
        )
        supplemented_line = fx.add_estimate_line(
            api,
            order_id,
            operation_code="BDY-2",
            labor_type="BODY",
            guide_hours=4.0,
            supplement_id=supplement["id"],
        )
        approved = fx.decide_supplement(api, supplement["id"], insurer_id, "APPROVE")
        assert approved["status"] == "APPROVED", (
            f"the supplement must land at APPROVED, got {approved['status']!r}"
        )
        decided_at = approved["decided_at"]

        contradiction = api.decide_supplement(
            supplement["id"],
            f.supplement_decision_payload("DENY"),
            make_insurer_adjuster_headers(insurer_id),
        )
        validate_error(contradiction, ApiErrorId.SUPPLEMENT_NOT_OPEN.value, 409)

        settled = fx.read_supplement(api, supplement["id"])
        assert settled["status"] == "APPROVED", (
            f"the refused answer must leave the supplement APPROVED, got {settled['status']!r}"
        )
        A.assert_cents(settled["approved_amount_cents"], 24000, "approved_amount_cents")
        A.assert_instant(settled["decided_at"], decided_at, "decided_at")

        line = fx.read_estimate_line(api, supplemented_line["id"])
        assert line["line_status"] == "APPROVED", (
            f"the supplemented labor line stays APPROVED, got {line['line_status']!r}"
        )

        order = fx.read_order(api, order_id)
        A.assert_hours(order["approved_labor_hours"], 8.5, "approved_labor_hours")
        A.assert_totals(
            order,
            labor_subtotal_cents=51000,
            supplies_fee_cents=2040,
            pre_tax_total_cents=53040,
            insurer_authorized_cents=28040,
            customer_pay_cents=25000,
        )
        A.assert_posture(order, C.POSTURE_OPEN)

        # Resubmission is only open from an information request, never from an approval.
        resubmission = api.resubmit_supplement(
            supplement["id"], f.supplement_resubmit_payload(30000), ESTIMATOR_HEADERS
        )
        validate_error(resubmission, ApiErrorId.SUPPLEMENT_NOT_OPEN.value, 409)

    def test_a_calibration_result_on_an_unbooked_record_is_refused(self, api):
        """A calibration outcome can only be filed against a booked window, and a passed record cannot be re-booked.

        PRD: "The record must be `SCHEDULED`, or the write is refused with `ERR_CALIBRATION_STATE`."
        PRD: "The record's `calibration_status` must be `REQUIRED` or `FAILED`, and anything else is refused with `ERR_CALIBRATION_STATE`."
        Design: Corner/state_machines/calibration_result_on_an_unscheduled_record_is_refused
        """
        world = fx.open_order_world(
            api,
            customer_overrides={
                "full_name": "Vic Ide",
                "phone": "555-1021",
                "email": "vic@example.com",
            },
            insurer_overrides={
                "insurer_code": "CRNR-21",
                "name": "Cornerstone Mutual",
                "rate_ceiling_cents": C.CEILINGS_BELOW_POSTED,
            },
            order_overrides={
                "claim_number": "CLM-90025",
                "vehicle_vin": "1HGCV1F30LA090025",
                "vehicle_make_model": "Honda Accord",
                "initial_authorized_cents": 400000,
                "deductible_cents": 25000,
            },
        )
        bay = fx.create_bay(
            api, name="Bay H", supported_types=["STATIC"], concurrent_capacity=2
        )
        record = fx.add_procedure_record(
            api,
            world["order_id"],
            procedure_code="ADAS-CAL-Y",
            source="OEM_PORTAL",
            operation_scope="ADAS",
            requires_calibration=True,
            calibration_type="STATIC",
        )
        result_body = f.calibration_result_payload("PASS", 0, scan_report_ref="SCAN-9025")

        premature = api.record_calibration_result(
            record["id"], result_body, TECHNICIAN_HEADERS
        )
        validate_error(premature, ApiErrorId.CALIBRATION_STATE.value, 409)

        unbooked = fx.read_procedure_record(api, record["id"])
        assert unbooked["calibration_status"] == "REQUIRED", (
            f"the record must still be REQUIRED, got {unbooked['calibration_status']!r}"
        )
        A.assert_null(unbooked["post_scan_dtc_count"], "post_scan_dtc_count")
        A.assert_null(unbooked["scan_report_ref"], "scan_report_ref")
        A.assert_count(
            fx.read_bay(api, bay["id"])["scheduled_window_count"],
            0,
            "scheduled_window_count",
        )

        booked = fx.schedule_calibration(api, record["id"], bay["id"], fx.T0900, fx.T1000)
        assert booked["calibration_status"] == "SCHEDULED", (
            f"a booking moves the record to SCHEDULED, got {booked['calibration_status']!r}"
        )
        A.assert_count(
            fx.read_bay(api, bay["id"])["scheduled_window_count"],
            1,
            "scheduled_window_count",
        )

        passed = get_success_data(
            api.record_calibration_result(record["id"], result_body, TECHNICIAN_HEADERS)
        )
        assert passed["calibration_status"] == "PASSED", (
            "a clean pass with no codes reaches PASSED, got "
            f"{passed['calibration_status']!r}"
        )
        A.assert_count(
            fx.read_bay(api, bay["id"])["scheduled_window_count"],
            0,
            "scheduled_window_count",
        )

        rebooking = api.schedule_calibration(
            record["id"],
            f.calibration_schedule_payload(bay["id"], fx.T1100, fx.T1200),
            TECHNICIAN_HEADERS,
        )
        validate_error(rebooking, ApiErrorId.CALIBRATION_STATE.value, 409)
        A.assert_count(
            fx.read_bay(api, bay["id"])["scheduled_window_count"],
            0,
            "scheduled_window_count",
        )
