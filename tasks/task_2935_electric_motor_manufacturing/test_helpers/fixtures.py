"""Composite setup helpers that drive real state through the public endpoints.

The database is empty before every test, so each helper rebuilds the plant it
needs from scratch: reference data, a released design, a confirmed order, a
costed work order, the two subassemblies, the assembly, the dynamometer test,
the nameplate and finally the warranty claim.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as F
from . import test_users as U
from .api_client import ApiClient

STAGE_ORDER: List[str] = [
    "reference",
    "design",
    "released_design",
    "order",
    "confirmed_order",
    "work_order",
    "subassemblies_opened",
    "stator_impregnated",
    "stator_surge_tested",
    "stator_accepted",
    "rotor_caged",
    "rotor_machined",
    "subassemblies_done",
    "assembled",
    "test_scheduled",
    "tested",
    "certified",
    "shipped",
    "claim_filed",
]


class Plant:
    """A live plant built through the API, one endpoint call at a time."""

    def __init__(self, api: ApiClient):
        self.api = api
        self.distributor: Optional[Dict[str, Any]] = None
        self.distributor_headers: Optional[Dict[str, str]] = None
        self.oven: Optional[Dict[str, Any]] = None
        self.cell: Optional[Dict[str, Any]] = None
        self.standard: Optional[Dict[str, Any]] = None
        self.design: Optional[Dict[str, Any]] = None
        self.design_payload: Optional[Dict[str, Any]] = None
        self.order: Optional[Dict[str, Any]] = None
        self.order_payload: Optional[Dict[str, Any]] = None
        self.work_order: Optional[Dict[str, Any]] = None
        self.work_order_payload: Optional[Dict[str, Any]] = None
        self.stator: Optional[Dict[str, Any]] = None
        self.rotor: Optional[Dict[str, Any]] = None
        self.assembly: Optional[Dict[str, Any]] = None
        self.test: Optional[Dict[str, Any]] = None
        self.test_payload: Optional[Dict[str, Any]] = None
        self.nameplate: Optional[Dict[str, Any]] = None
        self.claim: Optional[Dict[str, Any]] = None
        self.claim_payload: Optional[Dict[str, Any]] = None

    # ── Logical clock ─────────────────────────────────────────────────────────

    def set_clock(self, current_utc: str) -> Dict[str, Any]:
        return get_success_data(
            self.api.set_clock(F.clock_payload(current_utc=current_utc), U.PLANT_ADMIN)
        )

    # ── Reference data ────────────────────────────────────────────────────────

    def add_distributor(self, **overrides) -> Dict[str, Any]:
        row = get_success_data(
            self.api.create_distributor(
                F.distributor_payload(**overrides), U.PLANT_ADMIN
            )
        )
        self.distributor = row
        self.distributor_headers = U.make_distributor_headers(row["id"])
        return row

    def add_extra_distributor(self, **overrides) -> Dict[str, Any]:
        """A second distributor, used where two owners must stay distinct."""
        return get_success_data(
            self.api.create_distributor(
                F.distributor_payload(**overrides), U.PLANT_ADMIN
            )
        )

    def add_oven(self, **overrides) -> Dict[str, Any]:
        row = get_success_data(
            self.api.create_curing_oven(F.curing_oven_payload(**overrides), U.PLANT_ADMIN)
        )
        if self.oven is None:
            self.oven = row
        return row

    def add_cell(self, **overrides) -> Dict[str, Any]:
        row = get_success_data(
            self.api.create_test_cell(F.test_cell_payload(**overrides), U.PLANT_ADMIN)
        )
        if self.cell is None:
            self.cell = row
        return row

    def add_standard(self, **overrides) -> Dict[str, Any]:
        row = get_success_data(
            self.api.create_regulatory_standard(
                F.regulatory_standard_payload(**overrides), U.PLANT_ADMIN
            )
        )
        if self.standard is None:
            self.standard = row
        return row

    def add_reference_data(self, **overrides) -> "Plant":
        self.add_distributor(**overrides.get("distributor", {}))
        self.add_oven(**overrides.get("oven", {}))
        self.add_cell(**overrides.get("cell", {}))
        self.add_standard(**overrides.get("standard", {}))
        return self

    # ── Motor designs ─────────────────────────────────────────────────────────

    def add_design(
        self, payload: Optional[Dict[str, Any]] = None, headers=None, **overrides
    ) -> Dict[str, Any]:
        payload = dict(payload) if payload else F.motor_design_payload()
        payload.update(overrides)
        row = get_success_data(
            self.api.create_motor_design(payload, headers or U.DESIGN_ENGINEER)
        )
        if self.design is None:
            self.design = row
            self.design_payload = payload
        return row

    def submit_design(self, design: Optional[Dict[str, Any]] = None, headers=None):
        target = design or self.design
        row = get_success_data(
            self.api.submit_design_review(
                target["id"], F.submit_review_payload(), headers or U.DESIGN_ENGINEER
            )
        )
        if design is None or target is self.design:
            self.design = row
        return row

    def decide_design(
        self,
        decision: str = "APPROVE",
        design: Optional[Dict[str, Any]] = None,
        headers=None,
        **overrides
    ):
        target = design or self.design
        row = get_success_data(
            self.api.record_review_decision(
                target["id"],
                F.review_decision_payload(decision=decision, **overrides),
                headers or U.DESIGN_REVIEWER,
            )
        )
        if design is None or target is self.design:
            self.design = row
        return row

    def release_design(self, design: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        self.submit_design(design)
        return self.decide_design("APPROVE", design)

    def open_revision(self, design: Optional[Dict[str, Any]] = None, headers=None):
        target = design or self.design
        row = get_success_data(
            self.api.open_design_revision(
                target["id"], F.open_revision_payload(), headers or U.DESIGN_ENGINEER
            )
        )
        if design is None or target is self.design:
            self.design = row
        return row

    def released_design(self, payload: Optional[Dict[str, Any]] = None, **overrides):
        self.add_design(payload, **overrides)
        return self.release_design()

    # ── Customer orders ───────────────────────────────────────────────────────

    def add_order(
        self, headers=None, distributor=None, design=None, **overrides
    ) -> Dict[str, Any]:
        payload = F.customer_order_payload(
            (distributor or self.distributor)["id"],
            (design or self.design)["id"],
            **overrides
        )
        row = get_success_data(
            self.api.create_customer_order(payload, headers or U.PRODUCTION_PLANNER)
        )
        if self.order is None:
            self.order = row
            self.order_payload = payload
        return row

    def confirm_order(self, order: Optional[Dict[str, Any]] = None, headers=None):
        target = order or self.order
        row = get_success_data(
            self.api.confirm_customer_order(
                target["id"], F.confirm_order_payload(), headers or U.PRODUCTION_PLANNER
            )
        )
        if order is None or target is self.order:
            self.order = row
        return row

    def cancel_order(self, order: Optional[Dict[str, Any]] = None, headers=None):
        target = order or self.order
        row = get_success_data(
            self.api.cancel_customer_order(
                target["id"], F.cancel_order_payload(), headers or U.PRODUCTION_PLANNER
            )
        )
        if order is None or target is self.order:
            self.order = row
        return row

    # ── Work orders ───────────────────────────────────────────────────────────

    def add_work_order(
        self, headers=None, order=None, design=None, **overrides
    ) -> Dict[str, Any]:
        design_row = design or self.design
        live = self.get_design(design_row)
        payload = F.work_order_payload(
            (order or self.order)["id"],
            design_row["id"],
            live["version"],
            **overrides
        )
        row = get_success_data(
            self.api.create_work_order(payload, headers or U.PRODUCTION_PLANNER)
        )
        if self.work_order is None:
            self.work_order = row
            self.work_order_payload = payload
        return row

    def ship_work_order(self, work_order: Optional[Dict[str, Any]] = None, headers=None):
        target = work_order or self.work_order
        row = get_success_data(
            self.api.ship_work_order(
                target["id"], F.ship_payload(), headers or U.PRODUCTION_PLANNER
            )
        )
        if work_order is None or target is self.work_order:
            self.work_order = row
        return row

    # ── Stator builds ─────────────────────────────────────────────────────────

    def add_stator(self, work_order=None, headers=None, **overrides) -> Dict[str, Any]:
        target = work_order or self.work_order
        row = get_success_data(
            self.api.create_stator_build(
                F.stator_build_payload(target["id"], **overrides),
                headers or U.BUILD_TECHNICIAN,
            )
        )
        if self.stator is None:
            self.stator = row
        return row

    def impregnate_stator(
        self, stator=None, oven=None, headers=None, **overrides
    ) -> Dict[str, Any]:
        target = stator or self.stator
        oven_row = oven or self.oven
        row = get_success_data(
            self.api.impregnate_stator_build(
                target["id"],
                F.impregnation_payload(oven_row["id"], **overrides),
                headers or U.BUILD_TECHNICIAN,
            )
        )
        if stator is None or target is self.stator:
            self.stator = row
        return row

    def surge_test_stator(self, stator=None, headers=None, **overrides):
        target = stator or self.stator
        row = get_success_data(
            self.api.surge_test_stator_build(
                target["id"],
                F.surge_test_payload(**overrides),
                headers or U.TEST_ENGINEER,
            )
        )
        if stator is None or target is self.stator:
            self.stator = row
        return row

    def disposition_stator(
        self, disposition: str = "ACCEPTED", stator=None, headers=None, **overrides
    ):
        target = stator or self.stator
        row = get_success_data(
            self.api.disposition_stator_build(
                target["id"],
                F.disposition_payload(disposition=disposition, **overrides),
                headers or U.TEST_ENGINEER,
            )
        )
        if stator is None or target is self.stator:
            self.stator = row
        return row

    def accepted_stator(self, **overrides) -> Dict[str, Any]:
        self.add_stator(**overrides.get("create", {}))
        self.impregnate_stator(**overrides.get("impregnate", {}))
        self.surge_test_stator(**overrides.get("surge", {}))
        return self.disposition_stator("ACCEPTED")

    # ── Rotor builds ──────────────────────────────────────────────────────────

    def add_rotor(self, work_order=None, headers=None, **overrides) -> Dict[str, Any]:
        target = work_order or self.work_order
        row = get_success_data(
            self.api.create_rotor_build(
                F.rotor_build_payload(target["id"], **overrides),
                headers or U.BUILD_TECHNICIAN,
            )
        )
        if self.rotor is None:
            self.rotor = row
        return row

    def form_cage(self, rotor=None, headers=None, payload=None, **overrides):
        target = rotor or self.rotor
        body = payload or F.cage_payload_for_design(self.design_payload, **overrides)
        row = get_success_data(
            self.api.form_rotor_cage(
                target["id"], body, headers or U.BUILD_TECHNICIAN
            )
        )
        if rotor is None or target is self.rotor:
            self.rotor = row
        return row

    def machine_rotor(self, rotor=None, headers=None, **overrides):
        target = rotor or self.rotor
        row = get_success_data(
            self.api.machine_rotor_build(
                target["id"],
                F.machine_payload(**overrides),
                headers or U.BUILD_TECHNICIAN,
            )
        )
        if rotor is None or target is self.rotor:
            self.rotor = row
        return row

    def balance_rotor(
        self, disposition: str = "ACCEPTED", rotor=None, headers=None, **overrides
    ):
        target = rotor or self.rotor
        row = get_success_data(
            self.api.balance_disposition_rotor_build(
                target["id"],
                F.balance_disposition_payload(disposition=disposition, **overrides),
                headers or U.TEST_ENGINEER,
            )
        )
        if rotor is None or target is self.rotor:
            self.rotor = row
        return row

    def accepted_rotor(self, **overrides) -> Dict[str, Any]:
        self.add_rotor(**overrides.get("create", {}))
        self.form_cage(**overrides.get("cage", {}))
        self.machine_rotor(**overrides.get("machine", {}))
        return self.balance_rotor("ACCEPTED", **overrides.get("balance", {}))

    # ── Assembly ──────────────────────────────────────────────────────────────

    def add_assembly(
        self, headers=None, work_order=None, stator=None, rotor=None, **overrides
    ) -> Dict[str, Any]:
        row = get_success_data(
            self.api.create_assembly_record(
                F.assembly_record_payload(
                    (work_order or self.work_order)["id"],
                    (stator or self.stator)["id"],
                    (rotor or self.rotor)["id"],
                    **overrides
                ),
                headers or U.BUILD_TECHNICIAN,
            )
        )
        if self.assembly is None:
            self.assembly = row
        return row

    # ── Performance tests ─────────────────────────────────────────────────────

    def schedule_test(
        self, headers=None, cell=None, work_order=None, **overrides
    ) -> Dict[str, Any]:
        cell_row = cell or self.cell
        wo_row = work_order or self.work_order
        live = self.get_work_order(wo_row)
        payload = F.performance_test_payload(
            wo_row["id"], cell_row["id"], live["version"], **overrides
        )
        row = get_success_data(
            self.api.create_performance_test(payload, headers or U.TEST_ENGINEER)
        )
        if self.test is None:
            self.test = row
            self.test_payload = payload
        return row

    def record_test(
        self,
        test=None,
        headers=None,
        advance_clock: bool = True,
        clock: Optional[str] = None,
        **overrides
    ) -> Dict[str, Any]:
        target = test or self.test
        if advance_clock:
            self.set_clock(clock or max(F.RECORD_CLOCK, target["window_start"]))
        row = get_success_data(
            self.api.record_performance_test(
                target["id"],
                F.record_results_payload(**overrides),
                headers or U.TEST_ENGINEER,
            )
        )
        if test is None or target is self.test:
            self.test = row
        return row

    # ── Nameplates ────────────────────────────────────────────────────────────

    def issue_nameplate(
        self, headers=None, test=None, work_order=None, **overrides
    ) -> Dict[str, Any]:
        target = test or self.test
        row = get_success_data(
            self.api.create_nameplate(
                F.nameplate_payload(
                    (work_order or self.work_order)["id"], target["id"], **overrides
                ),
                headers or U.QUALITY_CERTIFIER,
            )
        )
        if self.nameplate is None:
            self.nameplate = row
        return row

    def revoke_nameplate(self, nameplate=None, headers=None, **overrides):
        target = nameplate or self.nameplate
        row = get_success_data(
            self.api.revoke_nameplate(
                target["id"],
                F.revoke_nameplate_payload(**overrides),
                headers or U.QUALITY_CERTIFIER,
            )
        )
        if nameplate is None or target is self.nameplate:
            self.nameplate = row
        return row

    # ── Warranty claims ───────────────────────────────────────────────────────

    def file_claim(
        self, headers=None, work_order=None, distributor=None, **overrides
    ) -> Dict[str, Any]:
        payload = F.warranty_claim_payload(
            (work_order or self.work_order)["id"],
            (distributor or self.distributor)["id"],
            **overrides
        )
        row = get_success_data(
            self.api.create_warranty_claim(payload, headers or U.COMPLIANCE_OFFICER)
        )
        if self.claim is None:
            self.claim = row
            self.claim_payload = payload
        return row

    def analyze_claim(self, payload: Dict[str, Any], claim=None, headers=None):
        target = claim or self.claim
        row = get_success_data(
            self.api.analyze_warranty_claim(
                target["id"], payload, headers or U.COMPLIANCE_OFFICER
            )
        )
        if claim is None or target is self.claim:
            self.claim = row
        return row

    def dispute_claim(self, claim=None, headers=None, **overrides):
        target = claim or self.claim
        row = get_success_data(
            self.api.dispute_warranty_claim(
                target["id"],
                F.dispute_payload(**overrides),
                headers or self.distributor_headers,
            )
        )
        if claim is None or target is self.claim:
            self.claim = row
        return row

    def close_claim(self, claim=None, headers=None, **overrides):
        target = claim or self.claim
        row = get_success_data(
            self.api.close_warranty_claim(
                target["id"],
                F.close_claim_payload(**overrides),
                headers or U.COMPLIANCE_OFFICER,
            )
        )
        if claim is None or target is self.claim:
            self.claim = row
        return row

    # ── Reads (the plant admin is authorised on every read path) ──────────────

    def get_design(self, design=None) -> Dict[str, Any]:
        row_id = (design or self.design)["id"]
        return get_success_data(self.api.get_motor_design(row_id, U.PLANT_ADMIN))

    def get_order(self, order=None) -> Dict[str, Any]:
        row_id = (order or self.order)["id"]
        return get_success_data(self.api.get_customer_order(row_id, U.PLANT_ADMIN))

    def get_work_order(self, work_order=None) -> Dict[str, Any]:
        row_id = (work_order or self.work_order)["id"]
        return get_success_data(self.api.get_work_order(row_id, U.PLANT_ADMIN))

    def get_cost_summary(self, work_order=None) -> Dict[str, Any]:
        row_id = (work_order or self.work_order)["id"]
        return get_success_data(
            self.api.get_work_order_cost_summary(row_id, U.PLANT_ADMIN)
        )

    def get_distributor(self, distributor=None) -> Dict[str, Any]:
        row_id = (distributor or self.distributor)["id"]
        return get_success_data(self.api.get_distributor(row_id, U.PLANT_ADMIN))

    def get_oven(self, oven=None) -> Dict[str, Any]:
        row_id = (oven or self.oven)["id"]
        return get_success_data(self.api.get_curing_oven(row_id, U.PLANT_ADMIN))

    def get_cell(self, cell=None) -> Dict[str, Any]:
        row_id = (cell or self.cell)["id"]
        return get_success_data(self.api.get_test_cell(row_id, U.PLANT_ADMIN))

    def get_standard(self, standard=None) -> Dict[str, Any]:
        row_id = (standard or self.standard)["id"]
        return get_success_data(self.api.get_regulatory_standard(row_id, U.PLANT_ADMIN))

    def get_stator(self, stator=None) -> Dict[str, Any]:
        row_id = (stator or self.stator)["id"]
        return get_success_data(self.api.get_stator_build(row_id, U.PLANT_ADMIN))

    def get_rotor(self, rotor=None) -> Dict[str, Any]:
        row_id = (rotor or self.rotor)["id"]
        return get_success_data(self.api.get_rotor_build(row_id, U.PLANT_ADMIN))

    def get_assembly(self, assembly=None) -> Dict[str, Any]:
        row_id = (assembly or self.assembly)["id"]
        return get_success_data(self.api.get_assembly_record(row_id, U.PLANT_ADMIN))

    def get_test(self, test=None) -> Dict[str, Any]:
        row_id = (test or self.test)["id"]
        return get_success_data(self.api.get_performance_test(row_id, U.PLANT_ADMIN))

    def get_nameplate(self, nameplate=None) -> Dict[str, Any]:
        row_id = (nameplate or self.nameplate)["id"]
        return get_success_data(self.api.get_nameplate(row_id, U.PLANT_ADMIN))

    def get_claim(self, claim=None) -> Dict[str, Any]:
        row_id = (claim or self.claim)["id"]
        return get_success_data(self.api.get_warranty_claim(row_id, U.PLANT_ADMIN))


def build_plant(api: ApiClient, stage: str = "shipped", **opts) -> Plant:
    """Drive the plant through the lifecycle up to and including ``stage``.

    Per-step payload overrides are passed as keyword dictionaries, for example
    ``build_plant(api, "work_order", work_order={"unit_count": 11})``.
    """
    assert stage in STAGE_ORDER, "unknown stage %r" % stage
    limit = STAGE_ORDER.index(stage)
    plant = Plant(api)

    def wanted(name: str) -> bool:
        return STAGE_ORDER.index(name) <= limit

    if wanted("reference"):
        plant.add_reference_data(
            distributor=opts.get("distributor", {}),
            oven=opts.get("oven", {}),
            cell=opts.get("cell", {}),
            standard=opts.get("standard", {}),
        )
    if wanted("design"):
        plant.add_design(opts.get("design_payload"), **opts.get("design", {}))
    if wanted("released_design"):
        plant.release_design()
    if wanted("order"):
        plant.add_order(**opts.get("order", {}))
    if wanted("confirmed_order"):
        plant.confirm_order()
    if wanted("work_order"):
        plant.add_work_order(**opts.get("work_order", {}))
    if wanted("subassemblies_opened"):
        plant.add_stator(**opts.get("stator", {}))
        plant.add_rotor(**opts.get("rotor", {}))
    if wanted("stator_impregnated"):
        plant.impregnate_stator(**opts.get("impregnate", {}))
    if wanted("stator_surge_tested"):
        plant.surge_test_stator(**opts.get("surge", {}))
    if wanted("stator_accepted"):
        plant.disposition_stator("ACCEPTED")
    if wanted("rotor_caged"):
        plant.form_cage(**opts.get("cage", {}))
    if wanted("rotor_machined"):
        plant.machine_rotor(**opts.get("machine", {}))
    if wanted("subassemblies_done"):
        plant.balance_rotor("ACCEPTED", **opts.get("balance", {}))
    if wanted("assembled"):
        plant.add_assembly(**opts.get("assembly", {}))
    if wanted("test_scheduled"):
        plant.schedule_test(**opts.get("test", {}))
    if wanted("tested"):
        plant.record_test(**opts.get("record", {}))
    if wanted("certified"):
        plant.issue_nameplate(**opts.get("nameplate", {}))
    if wanted("shipped"):
        plant.ship_work_order()
    if wanted("claim_filed"):
        plant.file_claim(**opts.get("claim", {}))
    return plant
