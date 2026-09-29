"""Fixtures and setup helpers.

Every helper below builds state exclusively through the endpoints the PRD
declares, so a test can be run against a freshly started server with no
pre-existing rows.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

import pytest
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from . import factories as f
from .api_client import ApiClient, api_client
from .constants import (
    CLOCK_ORIGIN,
    DECISION_ISSUE,
    HAZARD_HIGH,
    HAZARD_LOW,
    HAZARD_SIGNIFICANT,
    REVIEW_APPROVE,
    SAFETY_SATISFACTORY,
)
from .test_users import (
    admin_headers,
    coordinator_headers,
    make_engineer_headers,
    make_owner_headers,
)


@dataclass
class Bootstrap:
    """The shared entity chain: owner, two engineers, one reach, one dam."""

    owner: dict
    engineer_a: dict
    engineer_b: dict
    reach: dict
    dam: dict

    @property
    def owner_id(self) -> str:
        return self.owner["id"]

    @property
    def engineer_a_id(self) -> str:
        return self.engineer_a["id"]

    @property
    def engineer_b_id(self) -> str:
        return self.engineer_b["id"]

    @property
    def reach_id(self) -> str:
        return self.reach["id"]

    @property
    def dam_id(self) -> str:
        return self.dam["id"]

    @property
    def owner_headers(self) -> dict:
        return make_owner_headers(self.owner_id)

    @property
    def engineer_a_headers(self) -> dict:
        return make_engineer_headers(self.engineer_a_id)

    @property
    def engineer_b_headers(self) -> dict:
        return make_engineer_headers(self.engineer_b_id)


class Program:
    """Setup facade: one method per lifecycle step, all through declared endpoints."""

    def __init__(self, api: ApiClient) -> None:
        self.api = api
        self.admin = admin_headers()
        self.coordinator = coordinator_headers()

    # ------------------------------------------------------------------
    # Clock
    # ------------------------------------------------------------------
    def set_clock(self, current_utc: str) -> dict:
        return get_success_data(
            self.api.set_clock(f.clock_payload(current_utc), self.admin)
        )

    # ------------------------------------------------------------------
    # Entities
    # ------------------------------------------------------------------
    def create_owner(self, **kwargs: Any) -> dict:
        return get_success_data(
            self.api.create_owner(f.owner_payload(**kwargs), self.admin)
        )

    def create_engineer(self, **kwargs: Any) -> dict:
        return get_success_data(
            self.api.create_engineer(f.engineer_payload(**kwargs), self.admin)
        )

    def create_reach(self, **kwargs: Any) -> dict:
        return get_success_data(
            self.api.create_river_reach(f.river_reach_payload(**kwargs), self.admin)
        )

    def create_dam(self, owner_id: str, reach_id: str, **kwargs: Any) -> dict:
        return get_success_data(
            self.api.create_dam(f.dam_payload(owner_id, reach_id, **kwargs), self.admin)
        )

    def get_dam(self, dam_id: str, headers: Optional[dict] = None) -> dict:
        return get_success_data(self.api.get_dam(dam_id, headers or self.admin))

    def get_owner(self, owner_id: str, headers: Optional[dict] = None) -> dict:
        return get_success_data(self.api.get_owner(owner_id, headers or self.admin))

    def get_reach(self, reach_id: str, headers: Optional[dict] = None) -> dict:
        return get_success_data(
            self.api.get_river_reach(reach_id, headers or self.admin)
        )

    def get_engineer(self, engineer_id: str, headers: Optional[dict] = None) -> dict:
        return get_success_data(
            self.api.get_engineer(engineer_id, headers or self.admin)
        )

    def summary(self, dam_id: str, headers: Optional[dict] = None) -> dict:
        return get_success_data(
            self.api.get_compliance_summary(dam_id, headers or self.admin)
        )

    def dam_version(self, dam_id: str) -> int:
        return int(self.get_dam(dam_id)["version"])

    def reach_version(self, reach_id: str) -> int:
        return int(self.get_reach(reach_id)["version"])

    def bootstrap(
        self,
        clock: Optional[str] = CLOCK_ORIGIN,
        owner: Optional[dict] = None,
        dam: Optional[dict] = None,
        reach: Optional[dict] = None,
        engineer_a: Optional[dict] = None,
        engineer_b: Optional[dict] = None,
    ) -> Bootstrap:
        """Owner, two engineers, one reach and one UNCLASSIFIED dam."""
        if clock is not None:
            self.set_clock(clock)
        owner_row = self.create_owner(**(owner or {}))
        eng_a = self.create_engineer(**(engineer_a or {}))
        eng_b_defaults = {
            "full_name": "Priya Nair",
            "license_number": "PE-55210",
            "certified_hazard_classes": [HAZARD_SIGNIFICANT, HAZARD_HIGH],
        }
        eng_b_defaults.update(engineer_b or {})
        eng_b = self.create_engineer(**eng_b_defaults)
        reach_row = self.create_reach(**(reach or {}))
        dam_row = self.create_dam(owner_row["id"], reach_row["id"], **(dam or {}))
        return Bootstrap(owner_row, eng_a, eng_b, reach_row, dam_row)

    # ------------------------------------------------------------------
    # Consequence assessments
    # ------------------------------------------------------------------
    def create_assessment(self, payload: dict, engineer_id: str) -> dict:
        return get_success_data(
            self.api.create_assessment(payload, make_engineer_headers(engineer_id))
        )

    def certify_assessment(self, assessment_id: str, engineer_id: str) -> dict:
        return get_success_data(
            self.api.certify_assessment(
                assessment_id, None, make_engineer_headers(engineer_id)
            )
        )

    def classify(
        self,
        dam_id: str,
        engineer_id: str,
        builder: Callable[..., dict] = f.assessment_a1,
        **overrides: Any,
    ) -> dict:
        """Create and certify one assessment, publishing the dam's hazard class."""
        assessment = self.create_assessment(builder(dam_id, **overrides), engineer_id)
        return self.certify_assessment(assessment["id"], engineer_id)

    def classify_significant(self, dam_id: str, engineer_id: str, **kw: Any) -> dict:
        """Certified score 6.60 -> SIGNIFICANT."""
        return self.classify(dam_id, engineer_id, f.assessment_a1, **kw)

    def classify_high(self, dam_id: str, engineer_id: str, **kw: Any) -> dict:
        """Certified score 45.00 -> HIGH."""
        return self.classify(dam_id, engineer_id, f.assessment_a2, **kw)

    def classify_low(self, dam_id: str, engineer_id: str, **kw: Any) -> dict:
        """Certified score 0.00 with no population at risk -> LOW."""
        return self.classify(dam_id, engineer_id, f.assessment_a3, **kw)

    def assessments_for(self, dam_id: str) -> list[dict]:
        rows, _meta = validate_paginated(
            self.api.list_assessments(self.admin, {"dam_id": dam_id})
        )
        return rows

    # ------------------------------------------------------------------
    # Inspections
    # ------------------------------------------------------------------
    def schedule_inspection(self, dam_id: str, engineer_id: str, **kwargs: Any) -> dict:
        return get_success_data(
            self.api.create_inspection(
                f.inspection_payload(dam_id, engineer_id, **kwargs), self.admin
            )
        )

    def submit_inspection(
        self, inspection_id: str, engineer_id: str, **kwargs: Any
    ) -> dict:
        return get_success_data(
            self.api.submit_inspection(
                inspection_id,
                f.inspection_submission_payload(**kwargs),
                make_engineer_headers(engineer_id),
            )
        )

    def accept_inspection(self, inspection_id: str, headers: dict) -> dict:
        return get_success_data(
            self.api.accept_inspection(inspection_id, None, headers)
        )

    def return_inspection(self, inspection_id: str, **kwargs: Any) -> dict:
        return get_success_data(
            self.api.return_inspection(
                inspection_id, f.inspection_return_payload(**kwargs), self.admin
            )
        )

    def accepted_inspection(
        self,
        dam_id: str,
        engineer_id: str,
        accepter_headers: Optional[dict] = None,
        condition_rating: str = SAFETY_SATISFACTORY,
        deficiencies: Optional[list[dict]] = None,
        schedule: Optional[dict] = None,
        submission: Optional[dict] = None,
    ) -> dict:
        """Schedule, submit and accept one inspection, landing the rating on the dam."""
        inspection = self.schedule_inspection(dam_id, engineer_id, **(schedule or {}))
        submit_kwargs: dict[str, Any] = {"condition_rating": condition_rating}
        if deficiencies is not None:
            submit_kwargs["deficiencies"] = deficiencies
        submit_kwargs.update(submission or {})
        self.submit_inspection(inspection["id"], engineer_id, **submit_kwargs)
        return self.accept_inspection(inspection["id"], accepter_headers or self.admin)

    def inspections_for(self, dam_id: str) -> list[dict]:
        rows, _meta = validate_paginated(
            self.api.list_inspections(self.admin, {"dam_id": dam_id})
        )
        return rows

    # ------------------------------------------------------------------
    # Deficiencies and remediation orders
    # ------------------------------------------------------------------
    def deficiencies_for(self, dam_id: str, **params: Any) -> list[dict]:
        query = {"dam_id": dam_id}
        query.update(params)
        rows, _meta = validate_paginated(
            self.api.list_deficiencies(self.admin, query)
        )
        return rows

    def issue_order(self, deficiency_id: str, **kwargs: Any) -> dict:
        return get_success_data(
            self.api.create_remediation_order(
                deficiency_id, f.remediation_order_payload(**kwargs), self.admin
            )
        )

    def file_order_response(self, order_id: str, owner_id: str, **kwargs: Any) -> dict:
        return get_success_data(
            self.api.file_order_response(
                order_id, f.order_response_payload(**kwargs), make_owner_headers(owner_id)
            )
        )

    def verify_order(self, order_id: str, engineer_id: str, **kwargs: Any) -> dict:
        return get_success_data(
            self.api.verify_order(
                order_id, f.order_verify_payload(**kwargs), make_engineer_headers(engineer_id)
            )
        )

    def penalty_preview(self, order_id: str, headers: Optional[dict] = None) -> dict:
        return get_success_data(
            self.api.get_penalty_preview(order_id, headers or self.admin)
        )

    def get_order(self, order_id: str, headers: Optional[dict] = None) -> dict:
        return get_success_data(
            self.api.get_remediation_order(order_id, headers or self.admin)
        )

    def sweep(self) -> dict:
        return get_success_data(self.api.compliance_sweep(self.admin))

    # ------------------------------------------------------------------
    # Emergency action plans
    # ------------------------------------------------------------------
    def draft_plan(
        self,
        dam_id: str,
        owner_id: str,
        expected_dam_version: Optional[int] = None,
        **kwargs: Any,
    ) -> dict:
        version = (
            expected_dam_version
            if expected_dam_version is not None
            else self.dam_version(dam_id)
        )
        return get_success_data(
            self.api.create_eap(
                f.eap_payload(dam_id, version, **kwargs), make_owner_headers(owner_id)
            )
        )

    def submit_plan(
        self, plan_id: str, owner_id: str, payload: Optional[dict] = None
    ) -> dict:
        return get_success_data(
            self.api.submit_eap(plan_id, payload, make_owner_headers(owner_id))
        )

    def review_plan(self, plan_id: str, engineer_id: str, **kwargs: Any) -> dict:
        return get_success_data(
            self.api.review_eap(
                plan_id, f.eap_review_payload(**kwargs), make_engineer_headers(engineer_id)
            )
        )

    def approved_plan(
        self,
        dam_id: str,
        owner_id: str,
        engineer_id: str,
        submit_payload: Optional[dict] = None,
        **draft_kwargs: Any,
    ) -> dict:
        """Draft, submit and approve one plan."""
        plan = self.draft_plan(dam_id, owner_id, **draft_kwargs)
        self.submit_plan(plan["id"], owner_id, submit_payload)
        return self.review_plan(plan["id"], engineer_id, decision=REVIEW_APPROVE)

    def get_plan(self, plan_id: str, headers: Optional[dict] = None) -> dict:
        return get_success_data(self.api.get_eap(plan_id, headers or self.admin))

    def log_exercise(self, plan_id: str, headers: dict, **kwargs: Any) -> dict:
        return get_success_data(
            self.api.create_exercise(plan_id, f.exercise_payload(**kwargs), headers)
        )

    def plans_for(self, dam_id: str, **params: Any) -> list[dict]:
        query = {"dam_id": dam_id}
        query.update(params)
        rows, _meta = validate_paginated(self.api.list_eaps(self.admin, query))
        return rows

    # ------------------------------------------------------------------
    # Permits
    # ------------------------------------------------------------------
    def apply_permit(self, dam_id: str, owner_id: str, **kwargs: Any) -> dict:
        return get_success_data(
            self.api.create_permit(
                f.permit_payload(dam_id, **kwargs), make_owner_headers(owner_id)
            )
        )

    def assign_permit_review(self, permit_id: str, engineer_id: str) -> dict:
        return get_success_data(
            self.api.assign_permit_review(
                permit_id, f.assign_review_payload(engineer_id), self.admin
            )
        )

    def decide_permit(self, permit_id: str, engineer_id: str, **kwargs: Any) -> dict:
        return get_success_data(
            self.api.decide_permit(
                permit_id,
                f.permit_decision_payload(**kwargs),
                make_engineer_headers(engineer_id),
            )
        )

    def issued_permit(
        self, dam_id: str, owner_id: str, engineer_id: str, **kwargs: Any
    ) -> dict:
        permit = self.apply_permit(dam_id, owner_id, **kwargs)
        self.assign_permit_review(permit["id"], engineer_id)
        return self.decide_permit(permit["id"], engineer_id, decision=DECISION_ISSUE)

    def get_permit(self, permit_id: str, headers: Optional[dict] = None) -> dict:
        return get_success_data(self.api.get_permit(permit_id, headers or self.admin))

    # ------------------------------------------------------------------
    # High-water events and readings
    # ------------------------------------------------------------------
    def declare_event(self, dam_id: str, **kwargs: Any) -> dict:
        return get_success_data(
            self.api.create_event(f.event_payload(dam_id, **kwargs), self.coordinator)
        )

    def add_reading(
        self,
        event_id: str,
        reading_at: str,
        pool_elevation_ft: float,
        headers: Optional[dict] = None,
        **kwargs: Any,
    ) -> dict:
        return get_success_data(
            self.api.create_reading(
                event_id,
                f.reading_payload(reading_at, pool_elevation_ft, **kwargs),
                headers or self.coordinator,
            )
        )

    def escalate_event(
        self,
        event_id: str,
        crest_elevation_ft: float,
        first_at: str = "2026-08-01T02:00:00Z",
        second_at: str = "2026-08-01T04:00:00Z",
    ) -> dict:
        """Two readings: a CRITICAL non-rising one, then a rising one that escalates."""
        self.add_reading(event_id, first_at, crest_elevation_ft - 1.0)
        self.add_reading(event_id, second_at, crest_elevation_ft - 0.9)
        return self.get_event(event_id)

    def get_event(self, event_id: str, headers: Optional[dict] = None) -> dict:
        return get_success_data(self.api.get_event(event_id, headers or self.admin))

    def stand_down(self, event_id: str, **kwargs: Any) -> dict:
        return get_success_data(
            self.api.stand_down_event(
                event_id, f.stand_down_payload(**kwargs), self.coordinator
            )
        )

    # ------------------------------------------------------------------
    # Drawdown orders
    # ------------------------------------------------------------------
    def request_drawdown(self, dam_id: str, event_id: str, **kwargs: Any) -> dict:
        return get_success_data(
            self.api.create_drawdown_order(
                f.drawdown_payload(dam_id, event_id, **kwargs), self.admin
            )
        )

    def coordinate_drawdown(
        self,
        drawdown_id: str,
        reach_id: Optional[str] = None,
        expected_reach_version: Optional[int] = None,
    ) -> dict:
        if expected_reach_version is None:
            assert reach_id is not None, "reach_id or expected_reach_version required"
            expected_reach_version = self.reach_version(reach_id)
        return get_success_data(
            self.api.coordinate_drawdown(
                drawdown_id, f.coordinate_payload(expected_reach_version), self.admin
            )
        )

    def activate_drawdown(self, drawdown_id: str) -> dict:
        return get_success_data(
            self.api.activate_drawdown(drawdown_id, None, self.coordinator)
        )

    def complete_drawdown(self, drawdown_id: str, actual_release_acre_ft: float) -> dict:
        return get_success_data(
            self.api.complete_drawdown(
                drawdown_id,
                f.complete_drawdown_payload(actual_release_acre_ft),
                self.coordinator,
            )
        )

    def cancel_drawdown(
        self, drawdown_id: str, headers: Optional[dict] = None, **kwargs: Any
    ) -> dict:
        return get_success_data(
            self.api.cancel_drawdown(
                drawdown_id, f.cancel_drawdown_payload(**kwargs), headers or self.admin
            )
        )

    def get_drawdown(self, drawdown_id: str, headers: Optional[dict] = None) -> dict:
        return get_success_data(
            self.api.get_drawdown_order(drawdown_id, headers or self.admin)
        )

    # ------------------------------------------------------------------
    # Fee ledger
    # ------------------------------------------------------------------
    def post_ledger_entry(self, owner_id: str, **kwargs: Any) -> dict:
        return get_success_data(
            self.api.create_fee_adjustment(
                owner_id, f.fee_adjustment_payload(**kwargs), self.admin
            )
        )

    def ledger(self, owner_id: str, headers: Optional[dict] = None, **params: Any):
        return validate_paginated(
            self.api.list_fee_ledger_entries(
                owner_id, headers or self.admin, params or None
            )
        )

    def make_delinquent(self, owner_id: str, amount_cents: int = 30_000) -> dict:
        """Post a civil penalty large enough to cross the delinquency threshold."""
        return self.post_ledger_entry(owner_id, amount_cents=amount_cents)


# ---------------------------------------------------------------------------
# pytest fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def api() -> ApiClient:
    """The shared HTTP client."""
    return api_client


@pytest.fixture()
def program(api: ApiClient) -> Program:
    """Setup facade bound to the client, with the logical clock at its origin."""
    prog = Program(api)
    prog.set_clock(CLOCK_ORIGIN)
    return prog


@pytest.fixture()
def base(program: Program) -> Bootstrap:
    """Owner, two engineers, one reach and one UNCLASSIFIED dam."""
    return program.bootstrap(clock=None)


@pytest.fixture()
def significant(program: Program, base: Bootstrap) -> Bootstrap:
    """The bootstrap chain with the dam classified SIGNIFICANT."""
    program.classify_significant(base.dam_id, base.engineer_a_id)
    base.dam = program.get_dam(base.dam_id)
    return base


@pytest.fixture()
def high(program: Program, base: Bootstrap) -> Bootstrap:
    """The bootstrap chain with the dam classified HIGH."""
    program.classify_high(base.dam_id, base.engineer_a_id)
    base.dam = program.get_dam(base.dam_id)
    return base


@pytest.fixture()
def low(program: Program, base: Bootstrap) -> Bootstrap:
    """The bootstrap chain with the dam classified LOW."""
    program.classify_low(base.dam_id, base.engineer_a_id)
    base.dam = program.get_dam(base.dam_id)
    return base
