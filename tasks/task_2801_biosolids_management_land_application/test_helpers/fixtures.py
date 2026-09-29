"""Composite state builders.

Every fixture drives the declared API only - the service is started with an
empty store before each test, so nothing may be assumed to pre-exist.
"""

from typing import Any, Dict, List, Optional

import pytest

from prd_bench_local_runner.testing import get_success_data

from . import constants as C
from . import factories as F
from .api_client import BiosolidsApiClient
from .test_users import (
    AGRONOMIST_HEADERS,
    CERTIFYING_OFFICER_HEADERS,
    CERTIFYING_OFFICER_ID,
    DEFAULT_FARMER_ID,
    LAB_ANALYST_HEADERS,
    OFFICER_HEADERS,
    make_farmer_headers,
    make_officer_headers,
    make_operator_headers,
)


class StateBuilder:
    """Thin, role-correct wrapper that builds domain state over the API."""

    def __init__(self, api: BiosolidsApiClient):
        self.api = api

    # ------------------------------------------------------------ clock
    def set_clock(self, now: str = C.SEED_CLOCK) -> Dict[str, Any]:
        return get_success_data(
            self.api.set_clock(F.clock_payload(now), OFFICER_HEADERS)
        )

    # ------------------------------------------------------------ facility
    def facility(self, **overrides: Any) -> Dict[str, Any]:
        payload = F.facility_payload(**overrides)
        return get_success_data(
            self.api.create_facility(payload, make_operator_headers()), 201
        )

    def read_facility(self, facility_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_facility(facility_id, OFFICER_HEADERS))

    def storage_projection(self, facility_id: str) -> Dict[str, Any]:
        return get_success_data(
            self.api.get_storage_projection(facility_id, OFFICER_HEADERS)
        )

    # ------------------------------------------------------------ limits
    def limit(self, **overrides: Any) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_pollutant_limit(
                F.pollutant_limit_payload(**overrides), OFFICER_HEADERS
            ),
            201,
        )

    # ------------------------------------------------------------ batch
    def batch(self, facility_id: str, **overrides: Any) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_batch(
                F.batch_payload(facility_id, **overrides), make_operator_headers(facility_id)
            ),
            201,
        )

    def digest(self, batch_id: str, **overrides: Any) -> Dict[str, Any]:
        return get_success_data(
            self.api.advance_process(
                batch_id, F.digest_payload(**overrides), make_operator_headers()
            )
        )

    def dewater(self, batch_id: str, **overrides: Any) -> Dict[str, Any]:
        return get_success_data(
            self.api.advance_process(
                batch_id, F.dewater_payload(**overrides), make_operator_headers()
            )
        )

    def advance(self, batch_id: str, to_status: str, **overrides: Any) -> Dict[str, Any]:
        return get_success_data(
            self.api.advance_process(
                batch_id, F.advance_payload(to_status, **overrides), make_operator_headers()
            )
        )

    def lab_result(self, batch_id: str, **overrides: Any) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_lab_result(
                batch_id, F.lab_result_payload(**overrides), LAB_ANALYST_HEADERS
            ),
            201,
        )

    def certify(self, batch_id: str, officer_id: str = CERTIFYING_OFFICER_ID) -> Dict[str, Any]:
        return get_success_data(
            self.api.certify_batch(batch_id, make_officer_headers(officer_id))
        )

    def retest(self, batch_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.request_retest(batch_id, OFFICER_HEADERS))

    def read_batch(self, batch_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_batch(batch_id, OFFICER_HEADERS))

    def dewatered_batch(self, facility_id: str, **overrides: Any) -> Dict[str, Any]:
        """Batch carried to DEWATERED / PENDING_RESULTS."""
        batch = self.batch(facility_id, **overrides)
        self.digest(batch["id"])
        return self.dewater(batch["id"])

    def qualified_batch(self, facility_id: str, **overrides: Any) -> Dict[str, Any]:
        """Batch carried to DEWATERED with a clean CADMIUM result and certified."""
        batch = self.dewatered_batch(facility_id, **overrides)
        self.lab_result(batch["id"])
        return self.certify(batch["id"])

    # ------------------------------------------------------------ site
    def site(self, facility_id: str, **overrides: Any) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_site(
                F.site_payload(facility_id, **overrides), AGRONOMIST_HEADERS
            ),
            201,
        )

    def submit_permit(self, site_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.submit_permit(site_id, AGRONOMIST_HEADERS))

    def approve_permit(self, site_id: str, **overrides: Any) -> Dict[str, Any]:
        return get_success_data(
            self.api.permit_decision(
                site_id, F.permit_approval_payload(**overrides), OFFICER_HEADERS
            )
        )

    def permitted_site(self, facility_id: str, **overrides: Any) -> Dict[str, Any]:
        site = self.site(facility_id, **overrides)
        self.submit_permit(site["id"])
        return self.approve_permit(site["id"])

    def read_site(self, site_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_site(site_id, OFFICER_HEADERS))

    def loading_summary(self, site_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_loading_summary(site_id, OFFICER_HEADERS))

    def weather(self, site_id: str, **overrides: Any) -> Dict[str, Any]:
        return get_success_data(
            self.api.post_weather_observation(
                F.weather_payload(site_id, **overrides), make_operator_headers()
            )
        )

    # ------------------------------------------------------------ agreement
    def agreement(self, site_id: str, site_version: int, **overrides: Any) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_agreement(
                F.agreement_payload(site_id, site_version, **overrides), AGRONOMIST_HEADERS
            ),
            201,
        )

    def propose(self, agreement_id: str) -> Dict[str, Any]:
        return get_success_data(
            self.api.propose_agreement(agreement_id, AGRONOMIST_HEADERS)
        )

    def counter(self, agreement_id: str, farmer_id: str = DEFAULT_FARMER_ID, **overrides: Any):
        return get_success_data(
            self.api.counter_agreement(
                agreement_id, F.counter_payload(**overrides), make_farmer_headers(farmer_id)
            )
        )

    def sign(self, agreement_id: str, farmer_id: str = DEFAULT_FARMER_ID) -> Dict[str, Any]:
        return get_success_data(
            self.api.sign_agreement(agreement_id, make_farmer_headers(farmer_id))
        )

    def activate(self, agreement_id: str) -> Dict[str, Any]:
        return get_success_data(
            self.api.activate_agreement(agreement_id, AGRONOMIST_HEADERS)
        )

    def active_agreement(self, site_id: str, site_version: int, **overrides: Any):
        agreement = self.agreement(site_id, site_version, **overrides)
        self.propose(agreement["id"])
        self.sign(agreement["id"], overrides.get("farmer_user_id", DEFAULT_FARMER_ID))
        return self.activate(agreement["id"])

    def read_agreement(self, agreement_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_agreement(agreement_id, OFFICER_HEADERS))

    # ------------------------------------------------------------ events
    def event(
        self, site_id: str, batch_id: str, agreement_id: str, **overrides: Any
    ) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_event(
                F.event_payload(site_id, batch_id, agreement_id, **overrides),
                AGRONOMIST_HEADERS,
            ),
            201,
        )

    def start(self, event_id: str, facility_id: Optional[str] = None) -> Dict[str, Any]:
        return get_success_data(
            self.api.start_event(event_id, make_operator_headers(facility_id or "op"))
        )

    def haul_ticket(self, event_id: str, **overrides: Any) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_haul_ticket(
                event_id, F.haul_ticket_payload(**overrides), make_operator_headers()
            ),
            201,
        )

    def complete(self, event_id: str, officer_id: str = "officer-close-2", **overrides: Any):
        return get_success_data(
            self.api.complete_event(
                event_id, make_officer_headers(officer_id), F.complete_payload(**overrides)
            )
        )

    def cancel(self, event_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.cancel_event(event_id, AGRONOMIST_HEADERS))

    def void(self, event_id: str, officer_id: str = "officer-close-2") -> Dict[str, Any]:
        return get_success_data(
            self.api.void_event(event_id, make_officer_headers(officer_id))
        )

    def read_event(self, event_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_event(event_id, OFFICER_HEADERS))

    def completed_event(
        self,
        site_id: str,
        batch_id: str,
        agreement_id: str,
        clock_at: str = "2026-08-20T00:00:00Z",
        ticket_wet_tons: float = 400.00,
        complete_kwargs: Optional[Dict[str, Any]] = None,
        **event_overrides: Any,
    ) -> Dict[str, Any]:
        """Schedule, start inside the window, haul, and close out one event."""
        event = self.event(site_id, batch_id, agreement_id, **event_overrides)
        self.set_clock(clock_at)
        self.weather(site_id)
        self.start(event["id"])
        self.haul_ticket(event["id"], wet_tons=ticket_wet_tons)
        return self.complete(event["id"], **(complete_kwargs or {}))

    # ------------------------------------------------------------ outlets
    def outlet(self, **overrides: Any) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_outlet(F.outlet_payload(**overrides), make_operator_headers()),
            201,
        )

    def set_outlet_status(self, outlet_id: str, status: str) -> Dict[str, Any]:
        return get_success_data(
            self.api.set_outlet_status(
                outlet_id, F.outlet_status_payload(status), OFFICER_HEADERS
            )
        )

    def read_outlet(self, outlet_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_outlet(outlet_id, OFFICER_HEADERS))

    def order(
        self, batch_id: str, outlet_id: str, batch_version: int, **overrides: Any
    ) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_diversion_order(
                F.diversion_order_payload(batch_id, outlet_id, batch_version, **overrides),
                make_operator_headers(),
            ),
            201,
        )

    def commit_order(self, order_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.commit_order(order_id, OFFICER_HEADERS))

    def settle_order(self, order_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.settle_order(order_id, make_operator_headers()))

    def read_order(self, order_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_diversion_order(order_id, OFFICER_HEADERS))

    # ------------------------------------------------------------ complaints
    def complaint(self, facility_id: str, **overrides: Any) -> Dict[str, Any]:
        from .test_users import LIAISON_HEADERS

        return get_success_data(
            self.api.create_complaint(
                F.complaint_payload(facility_id, **overrides), LIAISON_HEADERS
            ),
            201,
        )

    def investigate(self, complaint_id: str) -> Dict[str, Any]:
        return get_success_data(
            self.api.investigate_complaint(complaint_id, OFFICER_HEADERS)
        )

    def resolve(self, complaint_id: str, **overrides: Any) -> Dict[str, Any]:
        return get_success_data(
            self.api.resolve_complaint(
                complaint_id, F.resolve_payload(**overrides), OFFICER_HEADERS
            )
        )

    def substantiated_complaint(self, facility_id: str, **overrides: Any) -> Dict[str, Any]:
        complaint = self.complaint(facility_id, **overrides)
        self.investigate(complaint["id"])
        return self.resolve(complaint["id"], outcome=C.COMPLAINT_SUBSTANTIATED)

    # ------------------------------------------------------------ reports
    def annual_report(self, facility_id: str, report_year: int = 2026, **overrides: Any):
        return get_success_data(
            self.api.create_annual_report(
                F.annual_report_payload(facility_id, report_year, **overrides),
                OFFICER_HEADERS,
            ),
            201,
        )

    def submit_report(self, report_id: str) -> Dict[str, Any]:
        return get_success_data(
            self.api.submit_annual_report(report_id, OFFICER_HEADERS)
        )

    # ------------------------------------------------------------ ledger
    def ledger_entries(self, **params: Any) -> List[Dict[str, Any]]:
        response = self.api.list_ledger_entries(OFFICER_HEADERS, params or None)
        return get_success_data(response)


class BaseWorld:
    """The shared starting position: one facility, one limit, one qualified batch,
    one permitted site with a clear weather observation, and one active agreement."""

    def __init__(self, build: StateBuilder, facility, limit, batch, batch_version_dewatered,
                 site, agreement):
        self.build = build
        self.facility = facility
        self.limit = limit
        self.batch = batch
        self.batch_version_dewatered = batch_version_dewatered
        self.site = site
        self.agreement = agreement

    @property
    def facility_id(self) -> str:
        return self.facility["id"]

    @property
    def batch_id(self) -> str:
        return self.batch["id"]

    @property
    def site_id(self) -> str:
        return self.site["id"]

    @property
    def agreement_id(self) -> str:
        return self.agreement["id"]

    @property
    def site_version(self) -> int:
        return self.site["version"]


# ==================================================================
# pytest fixtures
# ==================================================================

@pytest.fixture
def api() -> BiosolidsApiClient:
    """Endpoint client pointed at the service under test."""
    return BiosolidsApiClient()


@pytest.fixture
def build(api: BiosolidsApiClient) -> StateBuilder:
    """State builder with the logical clock parked at the seed instant."""
    builder = StateBuilder(api)
    builder.set_clock(C.SEED_CLOCK)
    return builder


@pytest.fixture
def facility(build: StateBuilder) -> Dict[str, Any]:
    """One registered treatment facility."""
    return build.facility()


@pytest.fixture
def cadmium_limit(build: StateBuilder) -> Dict[str, Any]:
    """The regulatory limit row every lab result and loading check consults."""
    return build.limit()


@pytest.fixture
def dewatered_batch(build: StateBuilder, facility, cadmium_limit) -> Dict[str, Any]:
    """A batch carried to DEWATERED / PENDING_RESULTS."""
    return build.dewatered_batch(facility["id"])


@pytest.fixture
def qualified_batch(build: StateBuilder, facility, cadmium_limit) -> Dict[str, Any]:
    """A batch carried to DEWATERED with a clean result and certified."""
    return build.qualified_batch(facility["id"])


@pytest.fixture
def draft_site(build: StateBuilder, facility) -> Dict[str, Any]:
    """A candidate site still in DRAFT."""
    return build.site(facility["id"])


@pytest.fixture
def permitted_site(build: StateBuilder, facility) -> Dict[str, Any]:
    """A site approved through the permit decision."""
    return build.permitted_site(facility["id"])


@pytest.fixture
def base_world(build: StateBuilder) -> BaseWorld:
    """The shared starting position used by most behavioural tests.

    One facility with 5000.00 wet tons of storage and two loadout bays, one
    CADMIUM limit row, one 800.00 wet ton batch dewatered to 160.000 dry tons
    and certified QUALIFIED, one PERMITTED 100 acre corn site with a clear
    weather observation, and one ACTIVE agreement naming ``farmer-jones``.
    """
    facility = build.facility()
    limit = build.limit()
    batch = build.batch(facility["id"])
    build.digest(batch["id"])
    dewatered = build.dewater(batch["id"])
    batch_version_dewatered = dewatered["version"]
    build.lab_result(batch["id"])
    certified = build.certify(batch["id"])
    site = build.permitted_site(facility["id"])
    agreement = build.active_agreement(site["id"], site["version"])
    build.weather(site["id"])
    return BaseWorld(
        build=build,
        facility=facility,
        limit=limit,
        batch=certified,
        batch_version_dewatered=batch_version_dewatered,
        site=site,
        agreement=agreement,
    )


@pytest.fixture
def diversion_world(build: StateBuilder):
    """A facility, a dewatered batch and one ACCEPTING compost outlet."""
    facility = build.facility()
    build.limit()
    batch = build.dewatered_batch(facility["id"])
    outlet = build.outlet()
    return {
        "build": build,
        "facility": facility,
        "batch": batch,
        "batch_version": batch["version"],
        "outlet": outlet,
    }


@pytest.fixture
def tight_cplr_world(build: StateBuilder):
    """A site whose cumulative cadmium limit is nearly exhausted (CPLR 0.19 kg/ha),
    carrying two scheduled applications of 80.000 dry tons on 20.0 acres each, with
    the first one started and one 400.00 wet ton haul ticket recorded.
    """
    facility = build.facility()
    build.limit(cplr_kg_per_hectare=0.19)
    batch = build.qualified_batch(facility["id"])
    site = build.permitted_site(facility["id"])
    agreement = build.active_agreement(site["id"], site["version"])
    build.weather(site["id"])

    event_a = build.event(
        site["id"], batch["id"], agreement["id"],
        window_start="2026-08-20T00:00:00Z",
        window_end="2026-08-21T00:00:00Z",
        acres_treated=20.0,
        planned_dry_tons=80.000,
    )
    event_b = build.event(
        site["id"], batch["id"], agreement["id"],
        window_start="2026-09-10T00:00:00Z",
        window_end="2026-09-11T00:00:00Z",
        acres_treated=20.0,
        planned_dry_tons=80.000,
    )
    build.set_clock("2026-08-20T06:00:00Z")
    build.start(event_a["id"])
    build.haul_ticket(
        event_a["id"],
        truck_id="T-1",
        wet_tons=400.00,
        depart_at="2026-08-20T08:00:00Z",
        return_at="2026-08-20T10:00:00Z",
        odometer_miles=30.0,
    )
    return {
        "build": build,
        "facility": facility,
        "batch": batch,
        "site": site,
        "agreement": agreement,
        "event_a": event_a,
        "event_b": event_b,
    }
