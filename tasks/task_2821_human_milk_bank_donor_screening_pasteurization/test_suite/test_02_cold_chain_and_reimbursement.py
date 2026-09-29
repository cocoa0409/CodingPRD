"""Cooler dispatch, receipt, courier reimbursement and container logging.

Covers the two reimbursement passes over one shared arithmetic skeleton, the
normative per-container rounding order, the three-way receipt fork with its
three crediting rules, the quarantine disposition top-up and reversal, the
state gates around receiving and container logging, the cooler's automatic
close, and the shipment concurrency token.
"""

from test_helpers import (
    ApiErrorId,
    api_client,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import INTAKE_HEADERS, INTAKE_ID, MEDICAL_DIRECTOR_HEADERS

CLOCK = C.CLOCK_INTAKE


class TestTwoReimbursementPasses:
    """One skeleton, two passes, and a rounding order that is normative."""

    def test_the_dispatch_estimate_and_the_receipt_final_diverge_on_one_cooler(self):
        """A three-container dry-ice cooler out of zone Z2 is estimated at 2952
        cents with the penalty rate pinned to 0, and finalised at 2538 cents once
        a seven-minute excursion charges fourteen percent; the estimate is
        retained alongside the final figure rather than overwritten.

        PRD: "At receipt the logger has been downloaded, so the excursion penalty rate becomes the **lesser** of 0.60 and 0.02 multiplied by `excursion_minutes` — meaning each excursion minute costs two percent of the pre-penalty amount, and the penalty stops growing once it has consumed sixty percent of it."
        Design: Difficulty/dual_variant_calc/shipment_reimbursement_provisional_vs_final_divergence
        """
        fx.set_clock(CLOCK)
        donor = fx.qualified_donor(donor_code="DNR-1004", full_name="Dia Vega", zone_code="Z2")
        dispatched = fx.register_shipment(
            donor["id"],
            tracking_code="TRK-1004",
            container_count=3,
            uses_dry_ice=True,
            declared_volume_ml=1200,
            shipped_on="2026-08-02",
        )
        assert dispatched["status"] == "IN_TRANSIT"
        assert dispatched["zone_code"] == "Z2", "the cooler carries a copy of the donor's zone"
        assert dispatched["estimated_reimbursement_cents"] == 2952
        assert dispatched["estimated_reimbursement_cents"] == A.expected_reimbursement_cents("Z2", 3, True, 0)
        assert dispatched["final_reimbursement_cents"] is None
        assert dispatched["credited_reimbursement_cents"] is None

        received = fx.receive_shipment(
            dispatched["id"], excursion_minutes=7, arrival_max_temp_celsius=-18.0, verified_volume_ml=1200
        )
        assert float(A.excursion_penalty_rate(7)) == 0.14, "0.02 for each of the seven minutes"
        assert received["status"] == "ACCEPTED"
        assert received["estimated_reimbursement_cents"] == 2952, "the provisional figure is not overwritten"
        assert received["final_reimbursement_cents"] == 2538
        assert received["final_reimbursement_cents"] == A.expected_reimbursement_cents("Z2", 3, True, 7)
        assert received["estimated_reimbursement_cents"] != received["final_reimbursement_cents"]
        assert isinstance(received["final_reimbursement_cents"], int)

    def test_only_the_receipt_pass_figure_is_credited_to_the_donor_ledger(self):
        """Registration credits nothing; the receipt fork then credits an
        ACCEPTED cooler in full, so the donor ledger holds the 2538-cent final
        figure and never the 2952-cent dispatch estimate.

        PRD: "Whatever that figure is, it is added to the donor's `reimbursement_balance_cents` — which is by definition the sum of `credited_reimbursement_cents` across her coolers in `ACCEPTED`, `QUARANTINED` or `CLOSED` — and her `version` increases by 1 alongside the cooler's."
        Design: Difficulty/dual_variant_calc/shipment_reimbursement_provisional_vs_final_divergence
        """
        fx.set_clock(CLOCK)
        donor = fx.qualified_donor(donor_code="DNR-1004", full_name="Dia Vega", zone_code="Z2")
        dispatched = fx.register_shipment(
            donor["id"],
            tracking_code="TRK-1004",
            container_count=3,
            uses_dry_ice=True,
            declared_volume_ml=1200,
            shipped_on="2026-08-02",
        )
        assert fx.donor_balance(donor["id"]) == 0, "nothing is credited at dispatch"

        received = fx.receive_shipment(
            dispatched["id"], excursion_minutes=7, arrival_max_temp_celsius=-18.0, verified_volume_ml=1200
        )
        assert received["credited_reimbursement_cents"] == 2538
        assert received["credited_reimbursement_cents"] == A.expected_credited_cents("ACCEPTED", 2538)
        assert fx.donor_balance(donor["id"]) == 2538
        assert fx.donor_balance(donor["id"]) != 2952

    def test_rounding_each_container_before_multiplying_is_the_normative_order(self):
        """Zone Z2's base of 1850 does not divide evenly by three containers, so
        the two orders disagree by a cent: rounding each container's 984.1666…
        down to 984 and multiplying gives 2952, while summing the unrounded
        shares and rounding once would give 2953.

        PRD: "The order of those last two operations is normative: summing the unrounded per-container amounts and rounding the total once at the end yields a different figure whenever the zone base does not divide evenly by the container count, and the ledgers are reconciled against the per-container rounding."
        Design: Difficulty/combinatorial_formula/reimbursement_per_container_rounding_order
        """
        fx.set_clock(CLOCK)
        donor = fx.qualified_donor(donor_code="DNR-1006", full_name="Fay Ibarra", zone_code="Z2")
        dispatched = fx.register_shipment(
            donor["id"],
            tracking_code="TRK-1006",
            container_count=3,
            uses_dry_ice=True,
            declared_volume_ml=1200,
            shipped_on="2026-08-02",
        )

        assert dispatched["estimated_reimbursement_cents"] == 2952
        assert A.expected_reimbursement_cents("Z2", 3, True, 0) == 2952
        assert A.expected_unrounded_total_cents("Z2", 3, True, 0) == 2953
        assert dispatched["estimated_reimbursement_cents"] != 2953, (
            "rounding the total once at the end is the wrong order"
        )

    def test_the_receipt_pass_applies_the_same_rounding_order_with_no_excursion(self):
        """With a zero excursion the penalty term vanishes and the receipt pass
        must reproduce the dispatch figure exactly — 2952 again, not 2953 — and
        that is the amount credited to the donor.

        PRD: "**Then round that per-container amount half up to a whole cent, and only afterwards multiply by `container_count`.**"
        Design: Difficulty/combinatorial_formula/reimbursement_per_container_rounding_order
        """
        fx.set_clock(CLOCK)
        donor = fx.qualified_donor(donor_code="DNR-1006", full_name="Fay Ibarra", zone_code="Z2")
        dispatched = fx.register_shipment(
            donor["id"],
            tracking_code="TRK-1006",
            container_count=3,
            uses_dry_ice=True,
            declared_volume_ml=1200,
            shipped_on="2026-08-02",
        )
        received = fx.receive_shipment(
            dispatched["id"], excursion_minutes=0, arrival_max_temp_celsius=-18.0, verified_volume_ml=1200
        )

        assert received["status"] == "ACCEPTED"
        assert received["estimated_reimbursement_cents"] == 2952
        assert received["final_reimbursement_cents"] == 2952
        assert received["final_reimbursement_cents"] != 2953
        assert received["credited_reimbursement_cents"] == 2952
        assert fx.donor_balance(donor["id"]) == 2952


class TestShipmentRowSurface:
    """What registration stores and what the shape and range steps refuse."""

    def test_a_single_read_returns_the_cooler_exactly_as_registration_stored_it(self):
        """A cooler read back before receipt carries the zone copied from its
        donor, the provisional estimate, and nulls in every field the receipt
        pass is responsible for.

        PRD: "The new cooler begins `IN_TRANSIT` at `version` 1, with `final_reimbursement_cents`, `credited_reimbursement_cents`, `excursion_minutes`, `arrival_max_temp_celsius`, `verified_volume_ml`, `received_at` and `received_by_user_id` all null."
        Design: Corner/entities/shipment_retrieval_returns_stored_provisional_reimbursement
        """
        fx.set_clock(CLOCK)
        donor = fx.qualified_donor(donor_code="DNR-0001", zone_code="Z2")
        registered = fx.register_shipment(
            donor["id"],
            tracking_code="TRK-0001",
            container_count=1,
            uses_dry_ice=False,
            declared_volume_ml=800,
            shipped_on="2026-08-02",
        )

        stored = fx.get_shipment(registered["id"])
        assert stored["tracking_code"] == "TRK-0001"
        assert stored["zone_code"] == "Z2"
        assert stored["status"] == "IN_TRANSIT"
        assert stored["estimated_reimbursement_cents"] == 2125, "1850 for zone Z2 over one container, plus 275"
        assert stored["estimated_reimbursement_cents"] == A.expected_reimbursement_cents("Z2", 1, False, 0)
        assert stored["final_reimbursement_cents"] is None
        assert stored["credited_reimbursement_cents"] is None
        assert stored["excursion_minutes"] is None
        assert stored["arrival_max_temp_celsius"] is None
        assert stored["verified_volume_ml"] is None
        assert stored["received_at"] is None
        assert stored["received_by_user_id"] is None
        assert stored["version"] == 1

    def test_registering_a_cooler_without_a_shipped_on_date_is_an_invalid_request(self):
        """The registration omits a required input field, so the shape step
        refuses it and no cooler row is written, even though the owning donor is
        QUALIFIED and every other field is well formed.

        PRD: "Shape validation in step 6 rejects a missing required field, a field of the wrong JSON type, a string that violates its declared pattern, or an enum value outside its declared set, all with `ERR_INVALID_REQUEST` (HTTP 422)."
        Design: Corner/entities/shipment_create_missing_shipped_on_returns_invalid_request
        """
        fx.set_clock(CLOCK)
        donor = fx.qualified_donor(donor_code="DNR-0001", zone_code="Z2")

        response = api_client.create_shipment(
            f.shipment(
                donor["id"],
                tracking_code="TRK-0001",
                container_count=1,
                uses_dry_ice=False,
                declared_volume_ml=800,
                _omit=("shipped_on",),
            ),
            INTAKE_HEADERS,
        )
        validate_error(response, ApiErrorId.INVALID_REQUEST.value, 422)

        rows, meta = validate_paginated(
            api_client.list_shipments(INTAKE_HEADERS, params={"donor_id": donor["id"]})
        )
        assert meta["total_count"] == 0
        assert rows == []

    def test_a_logged_container_computes_its_own_remaining_volume_and_owner(self):
        """The container log initialises remaining_ml from volume_ml and copies
        the donor from the cooler; a body that also sends a remaining_ml and a
        status is accepted with those unwritable fields ignored.

        PRD: "The new `Donation` starts `ELIGIBLE` with its `remaining_ml` equal to its `volume_ml` and with its own `donor_id` copied from the cooler's, never to be changed."
        Design: Corner/entities/donation_remaining_ml_is_computed_and_body_value_ignored
        """
        fx.set_clock(CLOCK)
        donor = fx.qualified_donor(donor_code="DNR-0001", zone_code="Z2")
        cooler = fx.accepted_cooler(donor["id"], tracking_code="TRK-0001", declared_volume_ml=800)

        donation = validate_success(
            api_client.log_donation(
                cooler["id"],
                f.donation(
                    fx.shipment_version(cooler["id"]),
                    container_label="C1",
                    expressed_on="2026-07-10",
                    volume_ml=700,
                    kcal_per_oz=20.0,
                    milk_class="TERM",
                    remaining_ml=1,
                    status="ALLOCATED",
                ),
                INTAKE_HEADERS,
            ),
            201,
        )
        assert donation["volume_ml"] == 700
        assert donation["remaining_ml"] == 700, "the body's remaining_ml of 1 was ignored, not honoured"
        assert donation["status"] == "ELIGIBLE", "the body's status was ignored, not rejected"
        assert donation["donor_id"] == donor["id"]
        assert donation["shipment_id"] == cooler["id"]
        assert donation["version"] == 1
        A.assert_donation(donation, volume_ml=700, remaining_ml=700, status="ELIGIBLE")

    def test_an_out_of_enum_milk_class_and_an_out_of_range_volume_are_different_refusals(self):
        """MIXED is not a container milk class, so the shape step answers first;
        1201 millilitres is an integer of the right type but beyond the declared
        ceiling, so the range step answers instead — and neither call writes a
        container.

        PRD: "Step 7 then checks declared numeric and date ranges and reports `ERR_FIELD_OUT_OF_RANGE` (HTTP 422); it applies to write requests only."
        Design: Corner/entities/donation_enum_and_range_constraints_are_enforced_separately
        """
        fx.set_clock(CLOCK)
        donor = fx.qualified_donor(donor_code="DNR-0001", zone_code="Z2")
        cooler = fx.accepted_cooler(donor["id"], tracking_code="TRK-0001", declared_volume_ml=800)
        version = fx.shipment_version(cooler["id"])

        bad_enum = api_client.log_donation(
            cooler["id"],
            f.donation(version, container_label="C1", expressed_on="2026-07-10", volume_ml=800, milk_class="MIXED"),
            INTAKE_HEADERS,
        )
        validate_error(bad_enum, ApiErrorId.INVALID_REQUEST.value, 422)

        bad_range = api_client.log_donation(
            cooler["id"],
            f.donation(version, container_label="C1", expressed_on="2026-07-10", volume_ml=1201, milk_class="TERM"),
            INTAKE_HEADERS,
        )
        validate_error(bad_range, ApiErrorId.FIELD_OUT_OF_RANGE.value, 422)

        _, meta = validate_paginated(
            api_client.list_donations(INTAKE_HEADERS, params={"shipment_id": cooler["id"]})
        )
        assert meta["total_count"] == 0

    def test_logging_a_container_against_an_unknown_cooler_is_a_resource_not_found(self):
        """A well-formed container body addressed to an identifier that matches
        no cooler is refused by the existence step, even though a real ACCEPTED
        cooler exists in the same bank.

        PRD: "Existence resolution in step 5 runs **left to right**: path parameters first, in the order they appear in the path, and then body foreign keys in the order the endpoint declares its input fields."
        Design: Corner/entities/donation_log_against_unknown_shipment_returns_not_found
        """
        fx.set_clock(CLOCK)
        donor = fx.qualified_donor(donor_code="DNR-0001", zone_code="Z2")
        cooler = fx.accepted_cooler(donor["id"], tracking_code="TRK-0001", declared_volume_ml=800)

        response = api_client.log_donation(
            "11111111-1111-4111-8111-111111111111",
            f.donation(
                fx.shipment_version(cooler["id"]),
                container_label="C1",
                expressed_on="2026-07-10",
                volume_ml=800,
                milk_class="TERM",
            ),
            INTAKE_HEADERS,
        )
        validate_error(response, ApiErrorId.RESOURCE_NOT_FOUND.value, 404)

        _, meta = validate_paginated(
            api_client.list_donations(INTAKE_HEADERS, params={"shipment_id": cooler["id"]})
        )
        assert meta["total_count"] == 0


class TestReceiptForkAndDisposition:
    """The three-way fork, the two crediting rules and the two dispositions."""

    def test_a_long_excursion_quarantines_the_cooler_and_credits_only_half(self):
        """A cooler that arrived cold enough but spent forty minutes warm takes
        the quarantine fork rather than the accepted one: the final figure is
        computed in full at 1416 cents, but only half of it — 708 — is credited
        and reaches the donor ledger.

        PRD: "`credited_reimbursement_cents` equals the full `final_reimbursement_cents` for an `ACCEPTED` cooler; equals `final_reimbursement_cents` multiplied by one half and rounded half up to a whole cent for a `QUARANTINED` cooler; and equals 0 for a `REJECTED` one."
        Design: Corner/state_machines/shipment_receive_quarantine_branch_credits_half_the_final_amount
        """
        fx.set_clock(CLOCK)
        donor = fx.qualified_donor(donor_code="DNR-0001", zone_code="Z3")
        cooler = fx.register_shipment(
            donor["id"],
            tracking_code="TRK-0001",
            container_count=2,
            uses_dry_ice=True,
            declared_volume_ml=1600,
            shipped_on="2026-08-02",
        )
        assert cooler["estimated_reimbursement_cents"] == 3540

        received = fx.receive_shipment(
            cooler["id"], excursion_minutes=40, arrival_max_temp_celsius=-18.0, verified_volume_ml=1600
        )
        assert received["status"] == "QUARANTINED"
        assert A.expected_receive_status(40, -18.0) == "QUARANTINED"
        assert received["estimated_reimbursement_cents"] == 3540
        assert received["final_reimbursement_cents"] == 1416, "the penalty rate is capped at 0.60"
        assert received["final_reimbursement_cents"] == A.expected_reimbursement_cents("Z3", 2, True, 40)
        assert received["credited_reimbursement_cents"] == 708
        assert received["credited_reimbursement_cents"] == A.expected_credited_cents("QUARANTINED", 1416)
        assert received["excursion_minutes"] == 40
        assert received["arrival_max_temp_celsius"] == -18.0
        assert received["received_by_user_id"] == INTAKE_ID
        assert fx.donor_balance(donor["id"]) == 708

    def test_accepting_a_quarantined_cooler_tops_the_ledger_up_by_the_difference(self):
        """The director's ACCEPT raises the credited figure from the half amount
        to the full 1416 cents and moves the ledger by the 708-cent difference
        only, so the ledger reconciles to 1416 rather than doubling to 2124.

        PRD: "`ACCEPT` rejoins the accepted path — `QUARANTINED → ACCEPTED` — by raising `credited_reimbursement_cents` to the full `final_reimbursement_cents` and crediting the donor's ledger with **only the difference** between the full amount and what was already credited; the ledger is topped up, never double-credited."
        Design: Corner/state_machines/quarantine_accept_disposition_tops_up_ledger_by_the_difference
        """
        fx.set_clock(CLOCK)
        donor = fx.qualified_donor(donor_code="DNR-0001", zone_code="Z3")
        cooler = fx.register_shipment(
            donor["id"],
            tracking_code="TRK-0001",
            container_count=2,
            uses_dry_ice=True,
            declared_volume_ml=1600,
            shipped_on="2026-08-02",
        )
        fx.receive_shipment(
            cooler["id"], excursion_minutes=40, arrival_max_temp_celsius=-18.0, verified_volume_ml=1600
        )
        assert fx.donor_balance(donor["id"]) == 708

        released = fx.disposition_shipment(cooler["id"], "ACCEPT")
        assert released["status"] == "ACCEPTED"
        assert released["final_reimbursement_cents"] == 1416
        assert released["credited_reimbursement_cents"] == 1416
        assert fx.donor_balance(donor["id"]) == 1416
        assert fx.donor_balance(donor["id"]) != 2124, "the half credit was topped up, not re-added in full"

    def test_rejecting_a_quarantined_cooler_reverses_the_half_credit_exactly(self):
        """The director's REJECT debits the 708 cents already credited and zeroes
        the credited figure, leaving the ledger at 0 while the full final amount
        stays on the row as the audit record.

        PRD: "`REJECT` moves the cooler `QUARANTINED → REJECTED`, debits the donor's `reimbursement_balance_cents` by the partial amount previously credited, and sets `credited_reimbursement_cents` to 0."
        Design: Corner/state_machines/quarantine_reject_disposition_reverses_the_half_credit
        """
        fx.set_clock(CLOCK)
        donor = fx.qualified_donor(donor_code="DNR-0001", zone_code="Z3")
        cooler = fx.register_shipment(
            donor["id"],
            tracking_code="TRK-0001",
            container_count=2,
            uses_dry_ice=True,
            declared_volume_ml=1600,
            shipped_on="2026-08-02",
        )
        fx.receive_shipment(
            cooler["id"], excursion_minutes=40, arrival_max_temp_celsius=-18.0, verified_volume_ml=1600
        )
        assert fx.donor_balance(donor["id"]) == 708

        refused = fx.disposition_shipment(cooler["id"], "REJECT")
        assert refused["status"] == "REJECTED"
        assert refused["final_reimbursement_cents"] == 1416, "the computed amount is retained for audit"
        assert refused["credited_reimbursement_cents"] == 0
        assert fx.donor_balance(donor["id"]) == 0

        _, meta = validate_paginated(
            api_client.list_donations(INTAKE_HEADERS, params={"shipment_id": cooler["id"]})
        )
        assert meta["total_count"] == 0, "container logging is admitted only against an accepted cooler"

    def test_the_receive_response_already_carries_the_final_figure_and_the_credit(self):
        """No derived value lags its request: the receive response itself reports
        the recomputed final and credited amounts, the stamped clock instant and
        the new status, the very next donor read already shows the ledger credit
        and a version bump, and re-reading both rows changes nothing.

        PRD: "All three are stamped onto the cooler along with `received_at`, the clock instant of the call, and `received_by_user_id`."
        Design: Corner/consistency_model/receipt_response_already_carries_the_final_reimbursement_and_the_donor_ledger_credit
        """
        fx.set_clock(CLOCK)
        donor = fx.qualified_donor(donor_code="DNR-0001", zone_code="Z2")
        cooler = fx.register_shipment(
            donor["id"],
            tracking_code="TRK-0001",
            container_count=1,
            uses_dry_ice=False,
            declared_volume_ml=1200,
            shipped_on="2026-08-02",
        )
        assert cooler["estimated_reimbursement_cents"] == 2125
        before = fx.get_donor(donor["id"])
        assert before["reimbursement_balance_cents"] == 0

        received = fx.receive_shipment(
            cooler["id"], excursion_minutes=5, arrival_max_temp_celsius=-18.0, verified_volume_ml=1200
        )
        assert received["status"] == "ACCEPTED"
        assert received["final_reimbursement_cents"] == 1913, "2125 less a ten percent penalty is 1912.5, rounded up"
        assert received["credited_reimbursement_cents"] == 1913
        A.assert_instant_equals(received["received_at"], CLOCK, "received_at")

        after_first_read = fx.get_donor(donor["id"])
        assert after_first_read["reimbursement_balance_cents"] == 1913
        assert after_first_read["version"] == before["version"] + 1

        reread_cooler = fx.get_shipment(cooler["id"])
        assert reread_cooler["final_reimbursement_cents"] == received["final_reimbursement_cents"]
        assert reread_cooler["credited_reimbursement_cents"] == received["credited_reimbursement_cents"]
        assert reread_cooler["status"] == received["status"]
        A.assert_instant_equals(reread_cooler["received_at"], received["received_at"], "received_at")
        assert reread_cooler["estimated_reimbursement_cents"] == 2125, "the estimate survives beside the final"
        assert reread_cooler["excursion_minutes"] == 5
        assert reread_cooler["arrival_max_temp_celsius"] == -18.0
        assert reread_cooler["verified_volume_ml"] == 1200
        assert reread_cooler["received_by_user_id"] == INTAKE_ID

        reread_donor = fx.get_donor(donor["id"])
        assert reread_donor["reimbursement_balance_cents"] == after_first_read["reimbursement_balance_cents"]
        assert reread_donor["version"] == after_first_read["version"], "nothing settled between the two reads"


class TestCoolerStateGatesAndClosure:
    """The state gate at step 10 runs before the concurrency token at step 11."""

    def test_receiving_the_same_cooler_twice_is_refused_and_credits_nothing_further(self):
        """Only the IN_TRANSIT to received transitions are declared, so a second
        receive on an ACCEPTED cooler is refused by the state gate and the donor
        is not credited twice.

        PRD: "The global sequence is: (1) both auth headers present and non-empty; (2) the role is one of the eight declared roles; (3) the role is authorized for this endpoint; (4) a `Donor` acts only within her own scope; (5) every referenced id exists; (6) the request body is shape-valid; (7) numeric and date inputs are inside their declared ranges; (8) business codes declared unique are not already taken; (9) the logical clock does not move backwards; (10) the addressed entity is in a state from which the requested transition is declared; (11) the optimistic-concurrency token matches the parent's current `version`; (12) clinical-safety and compliance rules; (13) temporal rules; (14) capacity and quantity constraints; (15) fiscal rules about subsidy capacity."
        Design: Corner/state_machines/second_receive_on_the_same_shipment_returns_state_invalid
        """
        fx.set_clock(CLOCK)
        donor = fx.qualified_donor(donor_code="DNR-0001", zone_code="Z2")
        cooler = fx.accepted_cooler(donor["id"], tracking_code="TRK-0001", declared_volume_ml=800)
        assert cooler["status"] == "ACCEPTED"
        assert cooler["credited_reimbursement_cents"] == 2125
        assert fx.donor_balance(donor["id"]) == 2125

        response = api_client.receive_shipment(
            cooler["id"], f.receipt(excursion_minutes=0, arrival_max_temp_celsius=-18.0, verified_volume_ml=800), INTAKE_HEADERS
        )
        validate_error(response, ApiErrorId.SHIPMENT_STATE_INVALID.value, 409)

        after = fx.get_shipment(cooler["id"])
        assert after["status"] == "ACCEPTED"
        assert after["credited_reimbursement_cents"] == 2125
        assert fx.donor_balance(donor["id"]) == 2125

    def test_a_correct_concurrency_token_does_not_rescue_a_log_against_a_cooler_in_transit(self):
        """Containers are inventoried only after receipt, and the cooler's state
        gate is evaluated before the concurrency token, so a container log with a
        perfectly fresh expected_shipment_version is still refused for the state.

        PRD: "Because the state gate at step 10 precedes the concurrency token at step 11, a request that is both stale and aimed at a wrongly-stated parent reports the state error, not the stale-version error."
        Design: Corner/state_machines/donation_log_against_in_transit_shipment_returns_state_invalid
        """
        fx.set_clock(CLOCK)
        donor = fx.qualified_donor(donor_code="DNR-0001", zone_code="Z2")
        cooler = fx.register_shipment(
            donor["id"],
            tracking_code="TRK-0001",
            container_count=1,
            uses_dry_ice=False,
            declared_volume_ml=800,
            shipped_on="2026-08-02",
        )
        assert cooler["status"] == "IN_TRANSIT"

        response = api_client.log_donation(
            cooler["id"],
            f.donation(
                fx.shipment_version(cooler["id"]),
                container_label="C1",
                expressed_on="2026-07-10",
                volume_ml=800,
                milk_class="TERM",
            ),
            INTAKE_HEADERS,
        )
        validate_error(response, ApiErrorId.SHIPMENT_STATE_INVALID.value, 409)

        after = fx.get_shipment(cooler["id"])
        assert after["status"] == "IN_TRANSIT"
        assert after["version"] == 1
        _, meta = validate_paginated(
            api_client.list_donations(INTAKE_HEADERS, params={"shipment_id": cooler["id"]})
        )
        assert meta["total_count"] == 0

    def test_a_cooler_closes_itself_once_its_only_container_becomes_terminal(self):
        """A deferral whose closed lookback window covers the expression date
        recalls the cooler's only container, and because every container of the
        cooler is then terminal the cooler closes inside the same request; the
        recall marks the container without zeroing its volume.

        PRD: "A `Shipment` in `ACCEPTED` that has at least one `Donation` and whose every `Donation` has reached `PASTEURIZED`, `RECALLED` or `DISCARDED` moves to `CLOSED`, taking a `version` increment."
        Design: Corner/state_machines/shipment_closes_when_its_last_donation_becomes_terminal
        """
        fx.set_clock(CLOCK)
        donor = fx.qualified_donor(donor_code="DNR-0001", zone_code="Z2")
        cooler = fx.accepted_cooler(donor["id"], tracking_code="TRK-0001", declared_volume_ml=700)
        donation = fx.log_container(
            cooler["id"], container_label="C1", expressed_on="2026-07-10", volume_ml=700
        )
        assert fx.get_shipment(cooler["id"])["status"] == "ACCEPTED"

        fx.record_deferral(
            donor["id"],
            reason_code="ILLNESS",
            deferral_type="TEMPORARY",
            effective_from="2026-07-10",
            deferral_days=30,
            lookback_days=0,
            recall_scope="DONATIONS_ONLY",
        )

        recalled = fx.get_donation(donation["id"])
        assert recalled["status"] == "RECALLED"
        assert recalled["remaining_ml"] == 700, "only the discarded path zeroes the volume"
        assert fx.get_shipment(cooler["id"])["status"] == "CLOSED"

        after_donor = fx.get_donor(donor["id"])
        assert after_donor["status"] == "TEMPORARILY_DEFERRED"
        assert after_donor["temporary_deferral_count"] == 1
        assert after_donor["active_deferral_until_date"] == A.add_days("2026-07-10", 30) == "2026-08-09"

        events, meta = validate_paginated(api_client.list_deferrals(donor["id"], MEDICAL_DIRECTOR_HEADERS))
        assert meta["total_count"] == 1
        A.assert_recall_counters(events[0], recalled_donation_count=1)

    def test_a_replayed_shipment_version_is_refused_then_the_refreshed_one_lands(self):
        """The container log is guarded by the cooler's version: replaying the
        token read before the first container was logged is refused with the
        stale-version error and writes nothing, while the token read after that
        log admits the identical body — proving the cooler's version advances by
        exactly one per accepted write.

        PRD: "Logging a container against a cooler requires `expected_shipment_version` to equal the parent `Shipment`'s current `version`. If it does not — because another container was logged against the same cooler, or because a `MedicalDirector` re-dispositioned it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), which is how the intake clerk learns that the cooler's manifest has changed since the screen was loaded."
        Design: Corner/cross_cutting_complexity_layers/occ_stale_shipment_version_refuses_the_second_container_log_then_the_fresh_version_lands_it
        """
        fx.set_clock(CLOCK)
        donor = fx.qualified_donor(donor_code="DNR-0001", zone_code="Z2")
        cooler = fx.accepted_cooler(
            donor["id"], tracking_code="TRK-0001", container_count=2, declared_volume_ml=2400
        )
        assert cooler["status"] == "ACCEPTED"
        assert cooler["estimated_reimbursement_cents"] == 2400, "925 per container plus 275, rounded, doubled"
        assert cooler["final_reimbursement_cents"] == 2400

        stale_token = fx.shipment_version(cooler["id"])
        body = dict(container_label="C1", expressed_on="2026-07-10", volume_ml=1200, kcal_per_oz=20.0, milk_class="TERM")
        first = validate_success(
            api_client.log_donation(cooler["id"], f.donation(stale_token, **body), INTAKE_HEADERS), 201
        )
        assert first["container_label"] == "C1"
        assert first["remaining_ml"] == 1200

        replayed = api_client.log_donation(
            cooler["id"], f.donation(stale_token, **dict(body, container_label="C2")), INTAKE_HEADERS
        )
        validate_error(replayed, ApiErrorId.STALE_VERSION.value, 412)

        fresh_token = fx.shipment_version(cooler["id"])
        assert fresh_token == stale_token + 1, "only the accepted log advanced the cooler"
        _, mid_meta = validate_paginated(
            api_client.list_donations(INTAKE_HEADERS, params={"shipment_id": cooler["id"]})
        )
        assert mid_meta["total_count"] == 1, "the refused call stored no container"

        second = validate_success(
            api_client.log_donation(
                cooler["id"], f.donation(fresh_token, **dict(body, container_label="C2")), INTAKE_HEADERS
            ),
            201,
        )
        assert second["container_label"] == "C2"
        assert second["shipment_id"] == cooler["id"]
        assert second["remaining_ml"] == 1200
        assert fx.shipment_version(cooler["id"]) == stale_token + 2

        rows, final_meta = validate_paginated(
            api_client.list_donations(INTAKE_HEADERS, params={"shipment_id": cooler["id"]})
        )
        assert final_meta["total_count"] == 2
        assert {row["id"] for row in rows} == {first["id"], second["id"]}
        assert fx.get_shipment(cooler["id"])["status"] == "ACCEPTED"
