"""Composite scenario builders.

The service under test is restarted with an empty database before every test,
so nothing here may assume a pre-existing row: each builder provisions the
whole chain it needs, from the logical clock through the plan, the technicians,
the style, its physical depth, the member, and as far along the rental circuit
as the caller asks for.

Every step validates its own response, so a broken fixture fails with the step
that broke rather than with a puzzling assertion later on.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from test_helpers import constants as K
from test_helpers import factories as F
from test_helpers.api_client import ApparelRentalClient
from test_helpers.assertions import assert_created, assert_list, assert_ok
from test_helpers.test_users import (
    make_claims_adjuster_headers,
    make_inventory_planner_headers,
    make_member_headers,
    make_platform_admin_headers,
    make_warehouse_tech_headers,
)

JsonDict = Dict[str, Any]


class Scenario:
    """A fluent builder over the rental circuit for one test.

    Instances are cheap: each one only remembers the actor headers and the rows
    it has created, so a test can hold several of them if it needs two
    independent members or two independent styles.
    """

    def __init__(self, client: ApparelRentalClient) -> None:
        self.client = client
        self.admin = make_platform_admin_headers()
        self.planner = make_inventory_planner_headers()
        self.adjuster = make_claims_adjuster_headers()
        self.clock: str = "2026-08-01T00:00:00Z"

    # -- actors ------------------------------------------------------------

    @staticmethod
    def member_headers(member: JsonDict) -> Dict[str, str]:
        return make_member_headers(member["id"])

    @staticmethod
    def tech_headers(technician: JsonDict) -> Dict[str, str]:
        return make_warehouse_tech_headers(technician["id"])

    # -- logical clock -----------------------------------------------------

    def set_clock(self, instant: str) -> JsonDict:
        data = assert_ok(self.client.set_clock(instant, self.admin))
        self.clock = instant
        return data

    # -- catalog -----------------------------------------------------------

    def create_plan(self, payload: Optional[JsonDict] = None) -> JsonDict:
        body = payload if payload is not None else F.sig4_plan_payload()
        return assert_created(self.client.create_membership_plan(body, self.admin))

    def create_technician(self, payload: JsonDict) -> JsonDict:
        return assert_created(self.client.create_technician(payload, self.admin))

    def create_inspector(self) -> JsonDict:
        return self.create_technician(F.inspector_technician_payload())

    def create_repairer(self) -> JsonDict:
        return self.create_technician(F.repairer_technician_payload())

    def create_uncertified_technician(self) -> JsonDict:
        return self.create_technician(F.uncertified_technician_payload())

    def create_style(self, payload: Optional[JsonDict] = None) -> JsonDict:
        body = payload if payload is not None else F.gown_style_payload()
        return assert_created(self.client.create_style(body, self.planner))

    def add_unit(
        self,
        style_id: str,
        unit_code: str,
        size: str = K.SIZE_M,
        acquisition_cost_cents: Optional[int] = None,
        condition_grade: Optional[str] = None,
    ) -> JsonDict:
        body = F.rental_unit_payload(
            unit_code, size, acquisition_cost_cents, condition_grade
        )
        return assert_created(self.client.create_rental_unit(style_id, body, self.planner))

    def add_units(
        self, style_id: str, unit_codes: Sequence[str], size: str = K.SIZE_M
    ) -> List[JsonDict]:
        return [self.add_unit(style_id, code, size) for code in unit_codes]

    # -- membership --------------------------------------------------------

    def enrol_member(
        self,
        plan_id: str,
        full_name: str = K.MEMBER_NORA_NAME,
        email: str = K.MEMBER_NORA_EMAIL,
        waiver_active: Optional[bool] = None,
        preferred_categories: Optional[Sequence[str]] = None,
        size_profile: Optional[str] = None,
    ) -> JsonDict:
        body = F.member_payload(
            plan_id,
            full_name,
            email,
            waiver_active=waiver_active,
            preferred_categories=preferred_categories,
            size_profile=size_profile,
        )
        return assert_created(self.client.create_member(body, self.admin))

    # -- reservations ------------------------------------------------------

    def create_reservation(
        self,
        member: JsonDict,
        style_id: str,
        window: Sequence[str],
        requested_size: str = K.SIZE_M,
        preferred_unit_id: Optional[str] = None,
    ) -> JsonDict:
        body = F.reservation_payload(
            style_id, requested_size, window[0], window[1], preferred_unit_id
        )
        return assert_created(
            self.client.create_reservation(body, self.member_headers(member))
        )

    # -- outbound leg ------------------------------------------------------

    def create_outbound_leg(
        self,
        reservation_id: str,
        planned_ship_date: str,
        carrier_reference: Optional[str] = None,
    ) -> JsonDict:
        body = F.outbound_shipment_payload(
            reservation_id, planned_ship_date, carrier_reference
        )
        return assert_created(self.client.create_shipment(body, self.admin))

    def dispatch(
        self,
        technician: JsonDict,
        shipment_id: str,
        carrier_reference: Optional[str] = None,
    ) -> JsonDict:
        return assert_ok(
            self.client.dispatch_shipment(
                shipment_id,
                self.tech_headers(technician),
                F.dispatch_payload(carrier_reference),
            )
        )

    def deliver(self, technician: JsonDict, shipment_id: str) -> JsonDict:
        return assert_ok(
            self.client.deliver_shipment(shipment_id, self.tech_headers(technician))
        )

    def record_exception(
        self, technician: JsonDict, shipment_id: str, reason: str
    ) -> JsonDict:
        return assert_ok(
            self.client.record_shipment_exception(
                shipment_id, F.shipment_exception_payload(reason), self.tech_headers(technician)
            )
        )

    # -- inbound leg -------------------------------------------------------

    def initiate_return(
        self,
        member: JsonDict,
        reservation_id: str,
        planned_ship_date: Optional[str] = None,
        carrier_reference: Optional[str] = None,
    ) -> JsonDict:
        body = F.return_initiation_payload(planned_ship_date, carrier_reference)
        return assert_created(
            self.client.initiate_return(reservation_id, body, self.member_headers(member))
        )

    def receive(self, technician: JsonDict, shipment_id: str) -> JsonDict:
        return assert_ok(
            self.client.receive_shipment(shipment_id, self.tech_headers(technician))
        )

    # -- lookups -----------------------------------------------------------

    def job_for_reservation(self, technician: JsonDict, reservation_id: str) -> JsonDict:
        rows, _ = assert_list(
            self.client.list_jobs(
                self.tech_headers(technician), {"reservation_id": reservation_id}
            ),
            total_count=1,
        )
        return rows[0]

    def claim_for_reservation(self, reservation_id: str) -> JsonDict:
        rows, _ = assert_list(
            self.client.list_damage_claims(self.adjuster, {"reservation_id": reservation_id}),
            total_count=1,
        )
        return rows[0]

    def ledger_rows(self, member: JsonDict) -> List[JsonDict]:
        rows, _ = assert_list(
            self.client.list_fee_ledger_entries(self.admin, {"member_id": member["id"]})
        )
        return rows

    def read_member(self, member: JsonDict) -> JsonDict:
        return assert_ok(self.client.get_member(member["id"], self.admin))

    def read_unit(self, unit_id: str) -> JsonDict:
        return assert_ok(self.client.get_rental_unit(unit_id, self.planner))

    def read_style(self, style_id: str) -> JsonDict:
        return assert_ok(self.client.get_style(style_id, self.planner))

    def read_reservation(self, reservation_id: str) -> JsonDict:
        return assert_ok(self.client.get_reservation(reservation_id, self.admin))

    def read_shipment(self, shipment_id: str) -> JsonDict:
        return assert_ok(self.client.get_shipment(shipment_id, self.admin))

    def read_job(self, technician: JsonDict, job_id: str) -> JsonDict:
        return assert_ok(self.client.get_job(job_id, self.tech_headers(technician)))

    def read_claim(self, claim_id: str) -> JsonDict:
        return assert_ok(self.client.get_damage_claim(claim_id, self.adjuster))

    def read_listing(self, listing_id: str) -> JsonDict:
        return assert_ok(self.client.get_resale_listing(listing_id, self.planner))

    # -- reconditioning ----------------------------------------------------

    def file_inspection(
        self,
        technician: JsonDict,
        job_id: str,
        soil_level: str = K.SOIL_NONE,
        damage_severity: str = K.DAMAGE_NONE,
        condition_grade_after: str = K.GRADE_A,
        biohazard_flag: Optional[bool] = None,
        notes: Optional[str] = None,
    ) -> JsonDict:
        body = F.inspection_payload(
            soil_level, damage_severity, condition_grade_after, biohazard_flag, notes
        )
        return assert_created(
            self.client.file_inspection(job_id, body, self.tech_headers(technician))
        )

    def complete_repair(
        self, technician: JsonDict, job_id: str, outcome: str = K.REPAIR_ACCEPTED
    ) -> JsonDict:
        return assert_ok(
            self.client.complete_repair(
                job_id, F.repair_completion_payload(outcome), self.tech_headers(technician)
            )
        )

    def complete_cleaning(self, technician: JsonDict, job_id: str) -> JsonDict:
        return assert_ok(
            self.client.complete_cleaning(job_id, self.tech_headers(technician))
        )

    def clear_quarantine(self, technician: JsonDict, job_id: str) -> JsonDict:
        return assert_ok(
            self.client.clear_quarantine(job_id, self.tech_headers(technician))
        )

    def photograph(self, technician: JsonDict, job_id: str) -> JsonDict:
        return assert_ok(self.client.photograph(job_id, self.tech_headers(technician)))

    def restock(self, technician: JsonDict, job_id: str) -> JsonDict:
        return assert_ok(self.client.restock(job_id, self.tech_headers(technician)))

    # -- money -------------------------------------------------------------

    def assess(self, claim_id: str) -> JsonDict:
        return assert_ok(self.client.assess_claim(claim_id, self.adjuster))

    def charge(self, claim_id: str) -> JsonDict:
        return assert_ok(self.client.charge_claim(claim_id, self.adjuster))

    def waive(self, claim_id: str) -> JsonDict:
        return assert_ok(self.client.waive_claim(claim_id, self.adjuster))

    def settle(
        self, member: JsonDict, amount_cents: int, memo: Optional[str] = None
    ) -> JsonDict:
        return assert_created(
            self.client.settle_fees(
                member["id"],
                F.settlement_payload(amount_cents, memo),
                self.member_headers(member),
            )
        )

    # -- resale ------------------------------------------------------------

    def retire_unit(self, unit_id: str, reason: str) -> JsonDict:
        return assert_ok(
            self.client.retire_rental_unit(
                unit_id, F.retirement_payload(reason), self.planner
            )
        )

    def create_listing(
        self,
        unit_id: str,
        expected_version: int,
        channel: str = K.CHANNEL_OUTLET,
        supersedes_listing_id: Optional[str] = None,
    ) -> JsonDict:
        body = F.resale_listing_payload(
            unit_id, expected_version, channel, supersedes_listing_id
        )
        return assert_created(self.client.create_resale_listing(body, self.planner))


class Catalog:
    """The provisioned world a rental turn needs before it can start."""

    def __init__(
        self,
        plan: JsonDict,
        inspector: JsonDict,
        repairer: JsonDict,
        style: JsonDict,
        units: List[JsonDict],
        member: JsonDict,
    ) -> None:
        self.plan = plan
        self.inspector = inspector
        self.repairer = repairer
        self.style = style
        self.units = units
        self.member = member

    @property
    def unit(self) -> JsonDict:
        return self.units[0]

    @property
    def style_id(self) -> str:
        return self.style["id"]

    @property
    def member_id(self) -> str:
        return self.member["id"]


class Turn:
    """One garment-turn's worth of rows, accumulated as the circuit advances."""

    def __init__(self, reservation: JsonDict) -> None:
        self.reservation = reservation
        self.outbound_leg: Optional[JsonDict] = None
        self.inbound_leg: Optional[JsonDict] = None
        self.job: Optional[JsonDict] = None
        self.inspection: Optional[JsonDict] = None
        self.claim: Optional[JsonDict] = None

    @property
    def reservation_id(self) -> str:
        return self.reservation["id"]

    @property
    def unit_id(self) -> str:
        unit_id = self.reservation["allocated_unit_id"]
        assert unit_id is not None, "this turn's reservation holds no allocated unit"
        return unit_id

    @property
    def job_id(self) -> str:
        assert self.job is not None, "this turn has no reverse-logistics job yet"
        return self.job["id"]

    @property
    def claim_id(self) -> str:
        assert self.claim is not None, "this turn has no damage claim"
        return self.claim["id"]


def standard_catalog(
    scenario: Scenario,
    unit_codes: Sequence[str] = (K.UNIT_GOWN_001,),
    size: str = K.SIZE_M,
    clock: str = K.CLOCK_AUG_03,
    plan_payload: Optional[JsonDict] = None,
    style_payload: Optional[JsonDict] = None,
    member_name: str = K.MEMBER_NORA_NAME,
    member_email: str = K.MEMBER_NORA_EMAIL,
    waiver_active: Optional[bool] = None,
    preferred_categories: Optional[Sequence[str]] = None,
    size_profile: Optional[str] = None,
) -> Catalog:
    """Clock, plan, two certified technicians, one style, its depth, one member."""
    scenario.set_clock(clock)
    plan = scenario.create_plan(plan_payload)
    inspector = scenario.create_inspector()
    repairer = scenario.create_repairer()
    style = scenario.create_style(style_payload)
    units = scenario.add_units(style["id"], unit_codes, size)
    member = scenario.enrol_member(
        plan["id"],
        full_name=member_name,
        email=member_email,
        waiver_active=waiver_active,
        preferred_categories=preferred_categories,
        size_profile=size_profile,
    )
    return Catalog(plan, inspector, repairer, style, units, member)


def turn_to_delivery(
    scenario: Scenario,
    catalog: Catalog,
    window: Sequence[str] = K.WINDOW_AUG_05_09,
    requested_size: str = K.SIZE_M,
    preferred_unit_id: Optional[str] = None,
    planned_ship_date: str = "2026-08-05",
    carrier_reference: Optional[str] = K.CARRIER_OUT_AUG_05,
    dispatch_clock: str = K.CLOCK_AUG_05_0800,
    member: Optional[JsonDict] = None,
) -> Turn:
    """Reserve, create the outbound leg, dispatch it and record delivery."""
    holder = member if member is not None else catalog.member
    reservation = scenario.create_reservation(
        holder, catalog.style_id, window, requested_size, preferred_unit_id
    )
    turn = Turn(reservation)
    turn.outbound_leg = scenario.create_outbound_leg(
        reservation["id"], planned_ship_date, carrier_reference
    )
    scenario.set_clock(dispatch_clock)
    turn.outbound_leg = scenario.dispatch(catalog.inspector, turn.outbound_leg["id"])
    turn.outbound_leg = scenario.deliver(catalog.inspector, turn.outbound_leg["id"])
    return turn


def turn_to_receipt(
    scenario: Scenario,
    catalog: Catalog,
    turn: Turn,
    return_clock: str = K.CLOCK_AUG_09_1700,
    receipt_clock: str = K.CLOCK_AUG_10_0900,
    planned_ship_date: Optional[str] = None,
    carrier_reference: Optional[str] = K.CARRIER_IN_AUG_09,
    member: Optional[JsonDict] = None,
) -> Turn:
    """Initiate the return, dispatch the inbound leg and receive it at the warehouse."""
    holder = member if member is not None else catalog.member
    scenario.set_clock(return_clock)
    turn.inbound_leg = scenario.initiate_return(
        holder, turn.reservation_id, planned_ship_date, carrier_reference
    )
    turn.inbound_leg = scenario.dispatch(catalog.inspector, turn.inbound_leg["id"])
    scenario.set_clock(receipt_clock)
    turn.inbound_leg = scenario.receive(catalog.inspector, turn.inbound_leg["id"])
    turn.job = scenario.job_for_reservation(catalog.inspector, turn.reservation_id)
    return turn


def turn_to_inspection(
    scenario: Scenario,
    catalog: Catalog,
    turn: Turn,
    soil_level: str = K.SOIL_NONE,
    damage_severity: str = K.DAMAGE_NONE,
    condition_grade_after: str = K.GRADE_A,
    biohazard_flag: Optional[bool] = None,
    notes: Optional[str] = None,
) -> Turn:
    """File the opening inspection and pick up the job and any claim it opened."""
    turn.inspection = scenario.file_inspection(
        catalog.inspector,
        turn.job_id,
        soil_level,
        damage_severity,
        condition_grade_after,
        biohazard_flag,
        notes,
    )
    turn.job = scenario.read_job(catalog.inspector, turn.job_id)
    if damage_severity != K.DAMAGE_NONE:
        turn.claim = scenario.claim_for_reservation(turn.reservation_id)
    return turn


def received_turn(
    scenario: Scenario,
    catalog: Catalog,
    window: Sequence[str] = K.WINDOW_AUG_05_09,
    **kwargs: Any,
) -> Turn:
    """The whole circuit as far as the warehouse receipt, with the job in RECEIVED."""
    delivery_keys = (
        "requested_size",
        "preferred_unit_id",
        "planned_ship_date",
        "carrier_reference",
        "dispatch_clock",
        "member",
    )
    receipt_keys = ("return_clock", "receipt_clock", "member")
    delivery_kwargs = {k: v for k, v in kwargs.items() if k in delivery_keys}
    receipt_kwargs = {k: v for k, v in kwargs.items() if k in receipt_keys}
    unexpected = set(kwargs) - set(delivery_keys) - set(receipt_keys)
    assert not unexpected, f"unexpected keyword arguments: {sorted(unexpected)}"
    turn = turn_to_delivery(scenario, catalog, window, **delivery_kwargs)
    return turn_to_receipt(scenario, catalog, turn, **receipt_kwargs)


def inspected_turn(
    scenario: Scenario,
    catalog: Catalog,
    window: Sequence[str] = K.WINDOW_AUG_05_09,
    soil_level: str = K.SOIL_NONE,
    damage_severity: str = K.DAMAGE_NONE,
    condition_grade_after: str = K.GRADE_A,
    biohazard_flag: Optional[bool] = None,
    notes: Optional[str] = None,
    **kwargs: Any,
) -> Turn:
    """The circuit as far as the opening inspection on the reverse-logistics job."""
    turn = received_turn(scenario, catalog, window, **kwargs)
    return turn_to_inspection(
        scenario,
        catalog,
        turn,
        soil_level,
        damage_severity,
        condition_grade_after,
        biohazard_flag,
        notes,
    )


def finish_reconditioning(
    scenario: Scenario, catalog: Catalog, turn: Turn, restock: bool = True
) -> Turn:
    """Sign off whichever legs the inspection demanded, photograph and restock.

    The repair leg is signed by the second technician, because the technician who
    filed the inspection may not sign off the repair.
    """
    job = scenario.read_job(catalog.inspector, turn.job_id)
    if job["repair_required"] and job["repair_completed_at"] is None:
        job = scenario.complete_repair(catalog.repairer, turn.job_id, K.REPAIR_ACCEPTED)
    if job["cleaning_required"] and job["cleaning_completed_at"] is None:
        job = scenario.complete_cleaning(catalog.inspector, turn.job_id)
    job = scenario.photograph(catalog.inspector, turn.job_id)
    if restock:
        job = scenario.restock(catalog.inspector, turn.job_id)
    turn.job = job
    return turn


def completed_turn(
    scenario: Scenario,
    catalog: Catalog,
    window: Sequence[str] = K.WINDOW_AUG_05_09,
    **kwargs: Any,
) -> Turn:
    """One clean turn all the way to RESTOCKED, so the unit has a completed turn."""
    turn = inspected_turn(scenario, catalog, window, **kwargs)
    return finish_reconditioning(scenario, catalog, turn)
