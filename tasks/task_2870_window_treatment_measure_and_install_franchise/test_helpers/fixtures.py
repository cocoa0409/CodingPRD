"""Composite setup builders and pytest fixtures.

Two layers live here.

The *builders* are plain functions taking the client and returning the created
resource. They thread identity for you: a franchisee call is made with the acting
territory's id in `X-User-ID`, a designer call with the acting designer's id, and a
manufacturer's ship call with the acting vendor's id. Setup steps use the lenient
success reader so a broken setup fails loudly and early.

The *fixtures* wrap the recurring chains — charter, staff, onboard, intake, book,
measure, configure, quote, present, accept, place, ship, receive, schedule — so a
test that needs a received order does not restate fourteen calls.
"""

from typing import Any, Dict, List, Optional, Sequence

import pytest

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import BlindsApiClient
from .test_users import (
    designer_headers,
    franchisee_headers,
    franchisor_headers,
    vendor_rep_headers,
)
from .types import Json

# ─── Reference instants used by the recurring chains ──────────────────────────

CLOCK_START = "2026-08-01T00:00:00.000Z"
CONSULT_START = "2026-08-03T14:00:00.000Z"
CONSULT_END = "2026-08-03T15:00:00.000Z"
INSTALL_START = "2026-08-20T09:00:00.000Z"
INSTALL_END = "2026-08-20T12:00:00.000Z"

# A square 24.000 x 48.000 inside-mount opening on a 3.000 inch pocket. Its
# ordered dimensions are 23.500 x 47.750, its billable area 8.000 square feet,
# and priced LT-SHEER / CORDED it lists at 4960 cents.
BASELINE_LIST_PRICE_CENTS = 4960


# ─── Builders ─────────────────────────────────────────────────────────────────


def set_clock(api: BlindsApiClient, current_utc: str) -> None:
    """Move the logical clock. Headquarters drives it; it advances no state machine."""
    get_success_data(api.set_clock(current_utc, franchisor_headers()))


def charter_territory(api: BlindsApiClient, **kwargs: Any) -> Json:
    """Charter a territory as headquarters."""
    return get_success_data(
        api.create_territory(f.territory_payload(**kwargs), franchisor_headers())
    )


def hire_designer(api: BlindsApiClient, territory: Json, **kwargs: Any) -> Json:
    """Hire a designer into a territory, acting as that territory's owner."""
    return get_success_data(
        api.create_designer(f.designer_payload(territory["id"], **kwargs),
                            franchisee_headers(territory["id"]))
    )


def onboard_vendor(api: BlindsApiClient, **kwargs: Any) -> Json:
    """Onboard a manufacturer as headquarters."""
    return get_success_data(
        api.create_vendor(f.vendor_payload(**kwargs), franchisor_headers())
    )


def add_sample_kit(api: BlindsApiClient, territory: Json, **kwargs: Any) -> Json:
    """Add a sample kit to a territory's library."""
    return get_success_data(
        api.create_sample_kit(f.sample_kit_payload(territory["id"], **kwargs),
                              franchisee_headers(territory["id"]))
    )


def intake_lead(api: BlindsApiClient, territory: Json, **kwargs: Any) -> Json:
    """Intake a homeowner inquiry through the local office."""
    return get_success_data(
        api.create_lead(f.lead_payload(**kwargs),
                        franchisee_headers(territory["id"]))
    )


def intake_lead_at_hq(api: BlindsApiClient, **kwargs: Any) -> Json:
    """Intake a homeowner inquiry through the national call centre."""
    return get_success_data(
        api.create_lead(f.lead_payload(**kwargs), franchisor_headers())
    )


def book_consultation(api: BlindsApiClient, designer: Json, lead: Json,
                      **kwargs: Any) -> Json:
    """Book an in-home appointment on the designer's own calendar."""
    payload = f.consultation_payload(lead["id"], designer["id"], **kwargs)
    return get_success_data(
        api.create_consultation(payload, designer_headers(designer["id"]))
    )


def record_opening(api: BlindsApiClient, designer: Json, consultation: Json,
                   **kwargs: Any) -> Json:
    """Record one measured opening against the appointment."""
    payload = f.opening_payload(consultation["id"], **kwargs)
    return get_success_data(
        api.create_opening(payload, designer_headers(designer["id"]))
    )


def configure_opening(api: BlindsApiClient, designer: Json, opening: Json,
                      **kwargs: Any) -> Json:
    """Set fabric, lift and motor package on one opening and re-price it."""
    payload = f.configuration_payload(**kwargs)
    return get_success_data(
        api.configure_opening(opening["id"], payload,
                              designer_headers(designer["id"]))
    )


def read_consultation(api: BlindsApiClient, designer: Json,
                      consultation_id: str) -> Json:
    """Read an appointment back — the version must be read immediately before a create."""
    return get_success_data(
        api.get_consultation(consultation_id, designer_headers(designer["id"]))
    )


def build_quote(api: BlindsApiClient, designer: Json, consultation: Json) -> Json:
    """Assemble a quote, reading the appointment's current version first."""
    current = read_consultation(api, designer, consultation["id"])
    payload = f.quote_payload(consultation["id"], current["version"])
    return get_success_data(
        api.create_quote(payload, designer_headers(designer["id"]))
    )


def present_quote(api: BlindsApiClient, designer: Json, quote: Json) -> Json:
    """Price and present a quote to the homeowner."""
    return get_success_data(
        api.present_quote(quote["id"], designer_headers(designer["id"]))
    )


def accept_quote(api: BlindsApiClient, designer: Json, quote: Json) -> Json:
    """Accept a presented quote, recognizing provisional royalty."""
    return get_success_data(
        api.accept_quote(quote["id"], designer_headers(designer["id"]))
    )


def read_quote(api: BlindsApiClient, territory: Json, quote_id: str) -> Json:
    """Read a quote back so the caller holds its current version."""
    return get_success_data(
        api.get_quote(quote_id, franchisee_headers(territory["id"]))
    )


def place_order(api: BlindsApiClient, territory: Json, quote: Json,
                opening_ids: Sequence[str],
                vendor: Optional[Json] = None,
                expected_quote_version: Optional[int] = None) -> Json:
    """Place a manufacturing order, reading the quote's current version first."""
    if expected_quote_version is None:
        expected_quote_version = read_quote(api, territory, quote["id"])["version"]
    payload = f.vendor_order_payload(
        quote["id"], opening_ids, expected_quote_version,
        preferred_vendor_id=vendor["id"] if vendor else None,
    )
    return get_success_data(
        api.create_vendor_order(payload, franchisee_headers(territory["id"]))
    )


def ship_order(api: BlindsApiClient, vendor: Json, order: Json) -> Json:
    """The manufacturer's own dispatcher reports the goods shipped."""
    return get_success_data(
        api.ship_vendor_order(order["id"], vendor_rep_headers(vendor["id"]))
    )


def receive_order(api: BlindsApiClient, territory: Json, order: Json) -> Json:
    """The franchise owner records the goods arriving."""
    return get_success_data(
        api.receive_vendor_order(order["id"], franchisee_headers(territory["id"]))
    )


def request_remake(api: BlindsApiClient, territory: Json, order: Json,
                   credit_scope: str = "REPLACEMENT") -> Json:
    """Request a replacement remake or a full credit on a received order."""
    return get_success_data(
        api.remake_vendor_order(order["id"], f.remake_payload(credit_scope),
                                franchisee_headers(territory["id"]))
    )


def schedule_install(api: BlindsApiClient, territory: Json, order: Json,
                     designer: Json, **kwargs: Any) -> Json:
    """Schedule the installation of a received order, booked by the franchise owner."""
    payload = f.install_job_payload(order["id"], designer["id"], **kwargs)
    return get_success_data(
        api.create_install_job(payload, franchisee_headers(territory["id"]))
    )


def checkout_kit(api: BlindsApiClient, designer: Json, kit: Json,
                 consultation: Json, hold_start_at: str,
                 hold_end_at: str) -> Json:
    """Take a kit out of the library on a closed hold interval."""
    payload = f.sample_checkout_payload(kit["id"], consultation["id"],
                                        hold_start_at, hold_end_at)
    return get_success_data(
        api.create_sample_checkout(payload, designer_headers(designer["id"]))
    )


def return_kit(api: BlindsApiClient, designer: Json, checkout: Json) -> Json:
    """Return a checked-out kit; lateness is priced at this instant."""
    return get_success_data(
        api.return_sample_checkout(checkout["id"],
                                   designer_headers(designer["id"]))
    )


def complete_consultation(api: BlindsApiClient, designer: Json,
                          consultation: Json) -> Json:
    """Close out an appointment as completed."""
    return get_success_data(
        api.complete_consultation(consultation["id"],
                                  designer_headers(designer["id"]))
    )


def ledger_rows(api: BlindsApiClient, territory: Json, **filters: Any) -> List[Json]:
    """Every accrual row on a territory, in the listing's declared order."""
    response = api.list_ledger_entries(territory["id"],
                                       franchisee_headers(territory["id"]),
                                       **filters)
    return get_success_data(response)


def ledger_page(api: BlindsApiClient, territory: Json, **filters: Any):
    """The ledger listing's rows together with its pagination block."""
    response = api.list_ledger_entries(territory["id"],
                                       franchisee_headers(territory["id"]),
                                       **filters)
    body = response.json()
    assert response.status_code == 200, response.text
    return body["data"], body["meta"]


def read_territory(api: BlindsApiClient, territory: Json) -> Json:
    """Read a territory and its nine derived counters."""
    return get_success_data(
        api.get_territory(territory["id"], franchisee_headers(territory["id"]))
    )


def read_designer(api: BlindsApiClient, territory: Json, designer_id: str) -> Json:
    """Read a designer and their liability figures."""
    return get_success_data(
        api.get_designer(designer_id, franchisee_headers(territory["id"]))
    )


def read_opening(api: BlindsApiClient, designer: Json, opening_id: str) -> Json:
    """Read one opening back."""
    return get_success_data(
        api.get_opening(opening_id, designer_headers(designer["id"]))
    )


def read_order(api: BlindsApiClient, territory: Json, order_id: str) -> Json:
    """Read one manufacturing order back."""
    return get_success_data(
        api.get_vendor_order(order_id, franchisee_headers(territory["id"]))
    )


def read_install_job(api: BlindsApiClient, designer: Json, job_id: str) -> Json:
    """Read one install job back."""
    return get_success_data(
        api.get_install_job(job_id, designer_headers(designer["id"]))
    )


# ─── Full-lifecycle shortcut ──────────────────────────────────────────────────


def single_opening_job(api: BlindsApiClient,
                       fabric_code: str = "LT-SHEER",
                       lift_system: str = "CORDED",
                       motorization_option: Optional[str] = None,
                       room_type: str = "OFFICE",
                       vendor_kwargs: Optional[Dict[str, Any]] = None,
                       territory_kwargs: Optional[Dict[str, Any]] = None,
                       designer_kwargs: Optional[Dict[str, Any]] = None,
                       stop_after: str = "received") -> Dict[str, Json]:
    """Charter through receipt for one opening, stopping where the caller asks.

    ``stop_after`` is one of ``consultation``, ``measured``, ``configured``,
    ``quoted``, ``presented``, ``accepted``, ``placed``, ``shipped``,
    ``received`` or ``scheduled``.
    """
    stages = ["consultation", "measured", "configured", "quoted", "presented",
              "accepted", "placed", "shipped", "received", "scheduled"]
    assert stop_after in stages, f"unknown stage {stop_after!r}"
    limit = stages.index(stop_after)

    territory = charter_territory(api, **(territory_kwargs or {}))
    designer = hire_designer(api, territory, **(designer_kwargs or {}))
    vendor_args = {"supported_lift_systems": [lift_system]}
    vendor_args.update(vendor_kwargs or {})
    vendor = onboard_vendor(api, **vendor_args)
    lead = intake_lead(api, territory)
    consultation = book_consultation(api, designer, lead)
    bundle: Dict[str, Json] = {
        "territory": territory, "designer": designer, "vendor": vendor,
        "lead": lead, "consultation": consultation,
    }
    if limit < stages.index("measured"):
        return bundle

    opening = record_opening(api, designer, consultation, room_type=room_type)
    bundle["opening"] = opening
    if limit < stages.index("configured"):
        return bundle

    bundle["opening"] = configure_opening(
        api, designer, opening, fabric_code=fabric_code,
        lift_system=lift_system, motorization_option=motorization_option,
    )
    if limit < stages.index("quoted"):
        return bundle

    quote = build_quote(api, designer, consultation)
    bundle["quote"] = quote
    if limit < stages.index("presented"):
        return bundle

    bundle["quote"] = present_quote(api, designer, quote)
    if limit < stages.index("accepted"):
        return bundle

    bundle["quote"] = accept_quote(api, designer, quote)
    if limit < stages.index("placed"):
        return bundle

    order = place_order(api, territory, quote, [bundle["opening"]["id"]], vendor)
    bundle["order"] = order
    if limit < stages.index("shipped"):
        return bundle

    bundle["order"] = ship_order(api, vendor, order)
    if limit < stages.index("received"):
        return bundle

    bundle["order"] = receive_order(api, territory, order)
    if limit < stages.index("scheduled"):
        return bundle

    bundle["install_job"] = schedule_install(api, territory, order, designer)
    return bundle


# ─── Pytest fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def hq_headers() -> Json:
    """Headers for brand headquarters."""
    return franchisor_headers()


@pytest.fixture
def territory(api: BlindsApiClient) -> Json:
    """One ACTIVE territory chartered on all four defaults."""
    return charter_territory(api)


@pytest.fixture
def owner_headers(territory: Json) -> Json:
    """Headers for the franchise owner of `territory`."""
    return franchisee_headers(territory["id"])


@pytest.fixture
def designer(api: BlindsApiClient, territory: Json) -> Json:
    """One ACTIVE designer with no certifications."""
    return hire_designer(api, territory)


@pytest.fixture
def dsg_headers(designer: Json) -> Json:
    """Headers for the acting designer."""
    return designer_headers(designer["id"])


@pytest.fixture
def certified_designer(api: BlindsApiClient, territory: Json) -> Json:
    """One ACTIVE designer holding the MOTORIZATION certification."""
    return hire_designer(api, territory, full_name="Marco Silva",
                         certifications=["MOTORIZATION"])


@pytest.fixture
def vendor(api: BlindsApiClient) -> Json:
    """One ACTIVE manufacturer supporting corded and cordless lifts."""
    return onboard_vendor(api, supported_lift_systems=["CORDED", "CORDLESS"],
                          concurrent_capacity=5)


@pytest.fixture
def lead(api: BlindsApiClient, territory: Json) -> Json:
    """One routed lead in the territory's only postal code."""
    return intake_lead(api, territory)


@pytest.fixture
def consultation(api: BlindsApiClient, designer: Json, lead: Json) -> Json:
    """One SCHEDULED appointment on the designer's calendar."""
    return book_consultation(api, designer, lead)


@pytest.fixture
def measured_opening(api: BlindsApiClient, designer: Json,
                     consultation: Json) -> Json:
    """One MEASURED 24.000 x 48.000 inside-mount opening on a 3.000 inch pocket."""
    return record_opening(api, designer, consultation)


@pytest.fixture
def configured_opening(api: BlindsApiClient, designer: Json,
                       measured_opening: Json) -> Json:
    """The same opening configured LT-SHEER / CORDED, listing at 4960 cents."""
    return configure_opening(api, designer, measured_opening)


@pytest.fixture
def draft_quote(api: BlindsApiClient, designer: Json, consultation: Json,
                configured_opening: Json) -> Json:
    """A DRAFT quote sweeping in the one configured opening."""
    return build_quote(api, designer, consultation)


@pytest.fixture
def presented_quote(api: BlindsApiClient, designer: Json,
                    draft_quote: Json) -> Json:
    """The same quote priced and PRESENTED at the clock's startup instant."""
    return present_quote(api, designer, draft_quote)


@pytest.fixture
def accepted_quote(api: BlindsApiClient, designer: Json,
                   presented_quote: Json) -> Json:
    """The same quote ACCEPTED, with provisional royalty recognized."""
    return accept_quote(api, designer, presented_quote)


@pytest.fixture
def placed_order(api: BlindsApiClient, territory: Json, vendor: Json,
                 accepted_quote: Json, configured_opening: Json) -> Json:
    """One PLACED manufacturing order carrying the single opening."""
    return place_order(api, territory, accepted_quote,
                       [configured_opening["id"]], vendor)


@pytest.fixture
def received_order(api: BlindsApiClient, territory: Json, vendor: Json,
                   placed_order: Json) -> Json:
    """The same order shipped by its manufacturer and RECEIVED by the franchise."""
    ship_order(api, vendor, placed_order)
    return receive_order(api, territory, placed_order)


@pytest.fixture
def install_job(api: BlindsApiClient, territory: Json, designer: Json,
                received_order: Json) -> Json:
    """One SCHEDULED install job against the received order."""
    return schedule_install(api, territory, received_order, designer)
