"""
Composite setup helpers for the Renewable Land Origination API test suite.

Every helper builds its preconditions from scratch through declared endpoints —
each test runs against a freshly booted server whose logical clock reads the
startup instant and whose store is empty. Setup calls use the lenient success
reader so a broken precondition surfaces as a setup failure rather than as a
confusing assertion inside the test body.

Two habits are deliberate. First, every helper is a single hop wherever the API
offers one, and the multi-hop composites re-read their parents between hops, so a
composite can never invalidate its own earlier step by advancing a version it
captured. Second, the two writes that carry a parent version always read that
version immediately before the guarded write, never from a value captured
earlier, because versions move under cascade.
"""

from typing import Any, Dict, List, Optional

import pytest
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import LandOriginationApiClient
from .constants import CLOCK_START
from .factories import (
    booking_payload,
    cancel_booking_payload,
    caprock_occupied_dwelling_rule,
    caprock_property_line_rule,
    caprock_public_road_rule,
    clear_curative_payload,
    corridor_payload,
    counter_payload,
    crossing_payload,
    curative_item_payload,
    exercise_payload,
    invoice_payload,
    landowner_payload,
    neighbor_consent_payload,
    option_payload,
    parcel_payload,
    pay_invoice_payload,
    post_security_payload,
    projection_params,
    record_memo_payload,
    rescreen_payload,
    revise_payload,
    royalty_hybrid_option_payload,
    setback_rule_payload,
    void_invoice_payload,
    waive_curative_payload,
    withdraw_payload,
)
from .test_users import (
    LAND_AGENT,
    PAYMENT_ADMIN,
    PORTFOLIO_MANAGER,
    PORTFOLIO_MANAGER_2,
    TITLE_COUNSEL,
    TITLE_COUNSEL_2,
    make_landowner_headers,
)

Payload = Dict[str, Any]
Headers = Dict[str, str]

_CLIENT: Optional[LandOriginationApiClient] = None


def client() -> LandOriginationApiClient:
    """The process-wide endpoint client, built on first use."""
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = LandOriginationApiClient()
    return _CLIENT


def _ok(response, what: str) -> Payload:
    """Read a setup response leniently and label it if it failed."""
    try:
        return get_success_data(response)
    except AssertionError as exc:  # pragma: no cover - setup diagnostics
        raise AssertionError(f"Setup failed while {what}: {exc}") from exc


# ─── Logical clock ────────────────────────────────────

def set_clock(current_utc: str, headers: Headers = LAND_AGENT) -> Payload:
    """Advance the logical clock and return the four sweep counts."""
    return _ok(
        client().set_clock(current_utc, headers), f"setting the clock to {current_utc}"
    )


# ─── Landowners ───────────────────────────────────────

def register_landowner(**overrides: Any) -> Payload:
    """Register one landowner of record."""
    return _ok(
        client().create_landowner(landowner_payload(**overrides), LAND_AGENT),
        "registering a landowner",
    )


def read_landowner(landowner_id: str, headers: Headers = LAND_AGENT) -> Payload:
    """Re-read a landowner, picking up any cascade that moved its posture."""
    return _ok(
        client().get_landowner(landowner_id, headers),
        f"reading landowner {landowner_id}",
    )


def amend_landowner(landowner_id: str, **fields: Any) -> Payload:
    """Amend the payable attributes of a landowner."""
    return _ok(
        client().patch_landowner(landowner_id, dict(fields), PAYMENT_ADMIN),
        f"amending landowner {landowner_id}",
    )


# ─── Setback ordinances ───────────────────────────────

def publish_setback_rule(**overrides: Any) -> Payload:
    """Publish one jurisdictional setback rule."""
    return _ok(
        client().create_setback_rule(setback_rule_payload(**overrides), TITLE_COUNSEL),
        "publishing a setback rule",
    )


def publish_caprock_setback_rules() -> Dict[str, Payload]:
    """
    Publish the three ordinances of the canonical jurisdiction, in the order the
    derivation will read them.
    """
    return {
        "property_line": _ok(
            client().create_setback_rule(caprock_property_line_rule(), TITLE_COUNSEL),
            "publishing the property-line ordinance",
        ),
        "occupied_dwelling": _ok(
            client().create_setback_rule(
                caprock_occupied_dwelling_rule(), TITLE_COUNSEL
            ),
            "publishing the occupied-dwelling ordinance",
        ),
        "public_road": _ok(
            client().create_setback_rule(caprock_public_road_rule(), TITLE_COUNSEL),
            "publishing the public-road ordinance",
        ),
    }


# ─── Parcels ──────────────────────────────────────────

def register_parcel(landowner_id: str, **overrides: Any) -> Payload:
    """Register one candidate parcel, which is screened as it lands."""
    return _ok(
        client().create_parcel(parcel_payload(landowner_id, **overrides), LAND_AGENT),
        "registering a parcel",
    )


def read_parcel(parcel_id: str, headers: Headers = LAND_AGENT) -> Payload:
    """Re-read a parcel with its full derived picture."""
    return _ok(client().get_parcel(parcel_id, headers), f"reading parcel {parcel_id}")


def parcels_page(headers: Headers = LAND_AGENT, **params: Any) -> tuple:
    """One page of the parcel collection, returned as (rows, meta)."""
    response = client().list_parcels(headers, dict(params))
    return validate_paginated(response)


def parcel_version(parcel_id: str) -> int:
    """Read a parcel's current version, for use as a concurrency input."""
    return int(read_parcel(parcel_id)["version"])


def rescreen(parcel_id: str, screen_mode: str = "FIELD_VERIFIED", **overrides: Any) -> Payload:
    """Re-screen a parcel under a named variant, persisting that variant."""
    return _ok(
        client().rescreen_parcel(
            parcel_id, rescreen_payload(screen_mode, **overrides), LAND_AGENT
        ),
        f"re-screening parcel {parcel_id} as {screen_mode}",
    )


# ─── Neighbor consents ────────────────────────────────

def request_consent(parcel_id: str, setback_rule_id: str, **overrides: Any) -> Payload:
    """Record a request for a neighbour's written consent."""
    return _ok(
        client().create_neighbor_consent(
            neighbor_consent_payload(parcel_id, setback_rule_id, **overrides),
            LAND_AGENT,
        ),
        "requesting a neighbor consent",
    )


def read_consent(consent_id: str, headers: Headers = LAND_AGENT) -> Payload:
    """Re-read a consent with its release contribution."""
    return _ok(
        client().get_neighbor_consent(consent_id, headers),
        f"reading consent {consent_id}",
    )


def grant_consent(consent_id: str) -> Payload:
    """Record the neighbour's signature and cascade the acreage release."""
    return _ok(
        client().grant_neighbor_consent(consent_id, {}, LAND_AGENT),
        f"granting consent {consent_id}",
    )


def revoke_consent(consent_id: str) -> Payload:
    """Record the neighbour's withdrawal and restore the encumbrance."""
    return _ok(
        client().revoke_neighbor_consent(consent_id, {}, LAND_AGENT),
        f"revoking consent {consent_id}",
    )


# ─── Title curative work ──────────────────────────────

def raise_curative(parcel_id: str, headers: Headers = TITLE_COUNSEL, **overrides: Any) -> Payload:
    """Raise one title defect against a parcel."""
    return _ok(
        client().create_curative_item(
            curative_item_payload(parcel_id, **overrides), headers
        ),
        "raising a title curative item",
    )


def read_curative(item_id: str, headers: Headers = TITLE_COUNSEL) -> Payload:
    """Re-read a curative item."""
    return _ok(
        client().get_curative_item(item_id, headers), f"reading curative item {item_id}"
    )


def clear_curative(item_id: str, headers: Headers = TITLE_COUNSEL_2, **overrides: Any) -> Payload:
    """Record that the curative work is complete, capitalising its cost."""
    return _ok(
        client().clear_curative_item(item_id, clear_curative_payload(**overrides), headers),
        f"clearing curative item {item_id}",
    )


def waive_curative(item_id: str, headers: Headers = TITLE_COUNSEL_2, **overrides: Any) -> Payload:
    """Accept the defect on the record instead of curing it."""
    return _ok(
        client().waive_curative_item(item_id, waive_curative_payload(**overrides), headers),
        f"waiving curative item {item_id}",
    )


# ─── Option agreements ────────────────────────────────

def draft_option(parcel_id: str, landowner_id: str, **overrides: Any) -> Payload:
    """
    Draft one option over a parcel.

    The parcel's version is read immediately before the guarded write, because a
    draft is one of only two writes that carry a parent version and any cascade
    since an earlier read would have moved it.
    """
    payload = option_payload(
        parcel_id, landowner_id, parcel_version(parcel_id), **overrides
    )
    return _ok(
        client().create_option_agreement(payload, LAND_AGENT),
        "drafting an option agreement",
    )


def draft_royalty_option(parcel_id: str, landowner_id: str, **overrides: Any) -> Payload:
    """Draft one option on the royalty-hybrid structure."""
    payload = royalty_hybrid_option_payload(
        parcel_id, landowner_id, parcel_version(parcel_id), **overrides
    )
    return _ok(
        client().create_option_agreement(payload, LAND_AGENT),
        "drafting a royalty-hybrid option agreement",
    )


def read_option(option_id: str, headers: Headers = LAND_AGENT) -> Payload:
    """Re-read an option with its negotiated terms and payment total."""
    return _ok(
        client().get_option_agreement(option_id, headers), f"reading option {option_id}"
    )


def send_option(option_id: str) -> Payload:
    """Send the terms on the table to the landowner."""
    return _ok(client().send_option(option_id, {}, LAND_AGENT), f"sending option {option_id}")


def counter_option(option_id: str, landowner_id: str, **overrides: Any) -> Payload:
    """Counter the sent terms as the landowner."""
    return _ok(
        client().counter_option(
            option_id, counter_payload(**overrides), make_landowner_headers(landowner_id)
        ),
        f"countering option {option_id}",
    )


def revise_option(option_id: str, **overrides: Any) -> Payload:
    """Answer a counter with revised terms."""
    return _ok(
        client().revise_option(option_id, revise_payload(**overrides), LAND_AGENT),
        f"revising option {option_id}",
    )


def accept_option(option_id: str, landowner_id: str) -> Payload:
    """Accept the terms on the table as the landowner."""
    return _ok(
        client().accept_option(option_id, {}, make_landowner_headers(landowner_id)),
        f"accepting option {option_id}",
    )


def execute_option(option_id: str, headers: Headers = PORTFOLIO_MANAGER) -> Payload:
    """Execute the option and mint the initial option fee."""
    return _ok(
        client().execute_option(option_id, {}, headers), f"executing option {option_id}"
    )


def extend_option(option_id: str, headers: Headers = PORTFOLIO_MANAGER) -> Payload:
    """Buy one extension of the option term."""
    return _ok(
        client().extend_option(option_id, {}, headers), f"extending option {option_id}"
    )


def exercise_option(
    option_id: str,
    exercise_notice_reference: str = "NOL-2982-0001",
    headers: Headers = PORTFOLIO_MANAGER_2,
) -> Payload:
    """
    Exercise the option and originate the lease.

    The default acting principal is the second portfolio manager, because the
    principal who executed the instrument may not be the one who converts it.
    """
    return _ok(
        client().exercise_option(
            option_id, exercise_payload(exercise_notice_reference), headers
        ),
        f"exercising option {option_id}",
    )


def withdraw_option(option_id: str, headers: Headers = LAND_AGENT, **overrides: Any) -> Payload:
    """Withdraw from the option."""
    return _ok(
        client().withdraw_option(option_id, withdraw_payload(**overrides), headers),
        f"withdrawing option {option_id}",
    )


def ledger_rows(option_agreement_id: str, headers: Headers = PORTFOLIO_MANAGER) -> List[Payload]:
    """Read the ledger rows of one agreement in their declared order."""
    return _ok(
        client().list_option_payments(
            headers, {"option_agreement_id": option_agreement_id}
        ),
        f"listing ledger rows of {option_agreement_id}",
    )


# ─── Corridors and crossings ──────────────────────────

def plan_corridor(**overrides: Any) -> Payload:
    """Plan one collection or interconnection corridor."""
    return _ok(
        client().create_corridor(corridor_payload(**overrides), LAND_AGENT),
        "planning a corridor",
    )


def read_corridor(corridor_id: str, headers: Headers = LAND_AGENT) -> Payload:
    """Re-read a corridor with its granted-crossing count."""
    return _ok(
        client().get_corridor(corridor_id, headers), f"reading corridor {corridor_id}"
    )


def permit_corridor(corridor_id: str) -> Payload:
    """Record the corridor's route permit."""
    return _ok(
        client().permit_corridor(corridor_id, {}, PORTFOLIO_MANAGER),
        f"permitting corridor {corridor_id}",
    )


def propose_crossing(corridor_id: str, parcel_id: str, **overrides: Any) -> Payload:
    """Propose one crossing over a station range and an occupancy window."""
    return _ok(
        client().create_crossing_agreement(
            crossing_payload(corridor_id, parcel_id, **overrides), LAND_AGENT
        ),
        "proposing a crossing agreement",
    )


def read_crossing(crossing_id: str, headers: Headers = LAND_AGENT) -> Payload:
    """Re-read a crossing with its computed compensation."""
    return _ok(
        client().get_crossing_agreement(crossing_id, headers),
        f"reading crossing {crossing_id}",
    )


def crossings_on_corridor(
    corridor_id: str, headers: Headers = LAND_AGENT
) -> List[Payload]:
    """Every crossing recorded against one corridor."""
    return _ok(
        client().list_crossing_agreements(headers, {"corridor_id": corridor_id}),
        f"listing crossings on corridor {corridor_id}",
    )


def grant_crossing(crossing_id: str) -> Payload:
    """Grant a proposed crossing."""
    return _ok(
        client().grant_crossing_agreement(crossing_id, {}, PORTFOLIO_MANAGER),
        f"granting crossing {crossing_id}",
    )


# ─── Site-access bookings ─────────────────────────────

def book_site_access(parcel_id: str, headers: Headers = LAND_AGENT, **overrides: Any) -> Payload:
    """Book a crew onto a parcel for one half-open window."""
    return _ok(
        client().create_site_access_booking(
            booking_payload(parcel_id, **overrides), headers
        ),
        "booking site access",
    )


def read_booking(booking_id: str, headers: Headers = LAND_AGENT) -> Payload:
    """Re-read a site-access booking."""
    return _ok(
        client().get_site_access_booking(booking_id, headers),
        f"reading booking {booking_id}",
    )


def cancel_booking(booking_id: str, headers: Headers = LAND_AGENT, **overrides: Any) -> Payload:
    """Cancel a booking, freeing its crew allocation."""
    return _ok(
        client().cancel_site_access_booking(
            booking_id, cancel_booking_payload(**overrides), headers
        ),
        f"cancelling booking {booking_id}",
    )


# ─── Leases ───────────────────────────────────────────

def read_lease(lease_id: str, headers: Headers = PORTFOLIO_MANAGER) -> Payload:
    """Re-read a lease with its security, recording and rent dimensions."""
    return _ok(client().get_lease(lease_id, headers), f"reading lease {lease_id}")


def leases_for_option(
    option_agreement_id: str, headers: Headers = PORTFOLIO_MANAGER
) -> List[Payload]:
    """Every lease originated by one option agreement."""
    return _ok(
        client().list_leases(headers, {"option_agreement_id": option_agreement_id}),
        f"listing leases for option {option_agreement_id}",
    )


def lease_version(lease_id: str) -> int:
    """Read a lease's current version, for use as a concurrency input."""
    return int(read_lease(lease_id)["version"])


def post_security(lease_id: str, amount_cents: int) -> Payload:
    """Post one instalment of decommissioning security."""
    return _ok(
        client().post_security(lease_id, post_security_payload(amount_cents), PAYMENT_ADMIN),
        f"posting {amount_cents} cents of security on lease {lease_id}",
    )


def post_full_security(lease_id: str) -> Payload:
    """
    Post the whole requirement in one instalment.

    The requirement is re-read first rather than recomputed, so a composite never
    depends on the sizing arithmetic it is only setting up for.
    """
    required = int(read_lease(lease_id)["total_security_required_cents"])
    return post_security(lease_id, required)


def submit_memo(lease_id: str) -> Payload:
    """Submit the memorandum of lease to the county."""
    return _ok(
        client().submit_memo(lease_id, {}, PORTFOLIO_MANAGER),
        f"submitting the memorandum of lease {lease_id}",
    )


def record_memo(lease_id: str, recording_instrument_no: str = "2026-0044821") -> Payload:
    """Record the memorandum with the county recorder."""
    return _ok(
        client().record_memo(
            lease_id, record_memo_payload(recording_instrument_no=recording_instrument_no),
            PORTFOLIO_MANAGER,
        ),
        f"recording the memorandum of lease {lease_id}",
    )


def rent_projection(lease_id: str, period_year: int = 1, production_mwh: float = 90000) -> Payload:
    """Read the non-persisting side-by-side projection for one period."""
    return _ok(
        client().get_rent_projection(
            lease_id, projection_params(period_year, production_mwh), PORTFOLIO_MANAGER
        ),
        f"projecting rent for lease {lease_id}",
    )


# ─── Rent invoices ────────────────────────────────────

def raise_invoice(lease_id: str, period_year: int = 1, production_mwh: float = 90000, **overrides: Any) -> Payload:
    """
    Raise one rent invoice.

    The lease's version is read immediately before the guarded write, because
    posting security, submitting and recording the memorandum all move it.
    """
    payload = invoice_payload(
        lease_version(lease_id), period_year, production_mwh, **overrides
    )
    return _ok(
        client().create_rent_invoice(lease_id, payload, PAYMENT_ADMIN),
        f"raising a rent invoice on lease {lease_id}",
    )


def read_invoice(invoice_id: str, headers: Headers = PAYMENT_ADMIN) -> Payload:
    """Re-read a rent invoice with its variant, components and gross amount."""
    return _ok(
        client().get_rent_invoice(invoice_id, headers), f"reading invoice {invoice_id}"
    )


def issue_invoice(invoice_id: str) -> Payload:
    """Issue an invoice and set its due date."""
    return _ok(
        client().issue_rent_invoice(invoice_id, {}, PAYMENT_ADMIN),
        f"issuing invoice {invoice_id}",
    )


def pay_invoice(invoice_id: str, paid_amount_cents: Optional[int] = None) -> Payload:
    """
    Record payment of an invoice in full.

    When no amount is supplied the invoice's own gross is read back and paid, so
    a composite never restates a figure the test is about to assert.
    """
    if paid_amount_cents is None:
        paid_amount_cents = int(read_invoice(invoice_id)["gross_rent_cents"])
    return _ok(
        client().pay_rent_invoice(
            invoice_id, pay_invoice_payload(paid_amount_cents), PAYMENT_ADMIN
        ),
        f"paying invoice {invoice_id}",
    )


def void_invoice(invoice_id: str, **overrides: Any) -> Payload:
    """Void a draft or issued invoice, freeing its period."""
    return _ok(
        client().void_rent_invoice(invoice_id, void_invoice_payload(**overrides), PAYMENT_ADMIN),
        f"voiding invoice {invoice_id}",
    )


# ─── Multi-hop composites ─────────────────────────────

def advance_option_to_accepted(option_id: str, landowner_id: str) -> Payload:
    """Walk a drafted option to the point where it can be executed."""
    send_option(option_id)
    return accept_option(option_id, landowner_id)


def advance_option_to_executed(
    option_id: str, landowner_id: str, headers: Headers = PORTFOLIO_MANAGER
) -> Payload:
    """Walk a drafted option all the way to a binding instrument."""
    advance_option_to_accepted(option_id, landowner_id)
    return execute_option(option_id, headers)


def caprock_qualified_parcel(**parcel_overrides: Any) -> Dict[str, Any]:
    """
    The canonical starting position: an owner of record, the three ordinances of
    their county, and one registered parcel that clears the qualification floor.

    Returned rows are the freshest reads available, because publishing the
    ordinances and registering the parcel each cascade.
    """
    landowner = register_landowner()
    rules = publish_caprock_setback_rules()
    parcel = register_parcel(landowner["id"], **parcel_overrides)
    return {
        "landowner": read_landowner(landowner["id"]),
        "rules": rules,
        "parcel": read_parcel(parcel["id"]),
    }


def caprock_executed_option(
    parcel_overrides: Optional[Payload] = None,
    royalty_hybrid: bool = False,
    executor: Headers = PORTFOLIO_MANAGER,
    **option_overrides: Any,
) -> Dict[str, Any]:
    """The canonical position with a binding option over the qualified parcel."""
    setup = caprock_qualified_parcel(**(parcel_overrides or {}))
    landowner_id = setup["landowner"]["id"]
    parcel_id = setup["parcel"]["id"]
    draft = (
        draft_royalty_option(parcel_id, landowner_id, **option_overrides)
        if royalty_hybrid
        else draft_option(parcel_id, landowner_id, **option_overrides)
    )
    advance_option_to_executed(draft["id"], landowner_id, executor)
    setup["option"] = read_option(draft["id"])
    setup["parcel"] = read_parcel(parcel_id)
    setup["landowner"] = read_landowner(landowner_id)
    return setup


def caprock_exercised_lease(
    exercise_notice_reference: str = "NOL-2982-0001",
    parcel_overrides: Optional[Payload] = None,
    royalty_hybrid: bool = False,
    **option_overrides: Any,
) -> Dict[str, Any]:
    """The canonical position with a lease originated but nothing yet recorded."""
    setup = caprock_executed_option(
        parcel_overrides=parcel_overrides,
        royalty_hybrid=royalty_hybrid,
        **option_overrides,
    )
    lease = exercise_option(setup["option"]["id"], exercise_notice_reference)
    setup["lease"] = read_lease(lease["id"])
    setup["option"] = read_option(setup["option"]["id"])
    setup["parcel"] = read_parcel(setup["parcel"]["id"])
    setup["landowner"] = read_landowner(setup["landowner"]["id"])
    return setup


def caprock_secured_lease(
    exercise_notice_reference: str = "NOL-2982-0001",
    parcel_overrides: Optional[Payload] = None,
    royalty_hybrid: bool = False,
    **option_overrides: Any,
) -> Dict[str, Any]:
    """The canonical position with the whole security requirement posted."""
    setup = caprock_exercised_lease(
        exercise_notice_reference=exercise_notice_reference,
        parcel_overrides=parcel_overrides,
        royalty_hybrid=royalty_hybrid,
        **option_overrides,
    )
    post_full_security(setup["lease"]["id"])
    setup["lease"] = read_lease(setup["lease"]["id"])
    return setup


def caprock_recorded_lease(
    recording_instrument_no: str = "2026-0044821",
    exercise_notice_reference: str = "NOL-2982-0001",
    parcel_overrides: Optional[Payload] = None,
    royalty_hybrid: bool = False,
    **option_overrides: Any,
) -> Dict[str, Any]:
    """The canonical position with the memorandum recorded with the county."""
    setup = caprock_secured_lease(
        exercise_notice_reference=exercise_notice_reference,
        parcel_overrides=parcel_overrides,
        royalty_hybrid=royalty_hybrid,
        **option_overrides,
    )
    lease_id = setup["lease"]["id"]
    submit_memo(lease_id)
    record_memo(lease_id, recording_instrument_no)
    setup["lease"] = read_lease(lease_id)
    setup["parcel"] = read_parcel(setup["parcel"]["id"])
    setup["landowner"] = read_landowner(setup["landowner"]["id"])
    return setup


def permitted_corridor(**overrides: Any) -> Payload:
    """A corridor that has already cleared its route permit."""
    corridor = plan_corridor(**overrides)
    permit_corridor(corridor["id"])
    return read_corridor(corridor["id"])


# ─── Pytest fixtures ──────────────────────────────────

@pytest.fixture
def api() -> LandOriginationApiClient:
    """The endpoint client for one test."""
    return client()


@pytest.fixture
def clock_start() -> str:
    """The instant the logical clock reads on a freshly booted server."""
    return CLOCK_START


@pytest.fixture
def landowner() -> Payload:
    """One registered owner of record."""
    return register_landowner()


@pytest.fixture
def caprock() -> Dict[str, Any]:
    """An owner, their county's three ordinances, and one qualified parcel."""
    return caprock_qualified_parcel()
