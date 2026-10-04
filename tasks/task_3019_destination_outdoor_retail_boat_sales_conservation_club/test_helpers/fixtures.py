"""Composite setup helpers and design-recipe executor.

Every test starts against a fresh server (the harness restarts it before each
test), so every fixture builds its world from scratch through the public API.

The recipe executor translates the structured call chains the design indices
use: each step is a dict with ``call`` (``METHOD /path``), ``payload`` (JSON
body for writes, query parameters for reads), ``as`` (acting role), optional
``as_user_id`` (X-User-ID override for the entity-backed Member role), and
optional ``captures`` mapping names to ``$.``-rooted response paths.
``${name}`` placeholders inside payload values and the path resolve against
previously captured values; ``${a} + N`` / ``${a} - N`` express small integer
arithmetic on captured versions.
"""
import json
import re

from prd_bench_local_runner.testing import get_success_data

from .test_users import (
    AGENCY_OPERATOR,
    ANONYMOUS,
    ATTRACTION_HOST,
    CLUB_CARD_SPECIALIST,
    CREDIT_OFFICER,
    CREDIT_UNDERWRITER,
    DEAL_DESK_CLERK,
    EVENTS_COORDINATOR,
    FINANCE_ADMIN,
    PERMIT_CLERK,
    PLATFORM_ADMIN,
    RECEIVING_MANAGER,
    REMIT_ADMIN,
    SERVICE_TECHNICIAN,
    SERVICE_WRITER,
    STORE_MANAGER,
    TITLE_CLERK,
    make_member_headers,
)

_REF_RE = re.compile(r"\$\{([^}]+)\}")
_ARITH_RE = re.compile(r"^\$\{([^}]+)\}\s*([+-])\s*(\d+)$")

_OPAQUE_ROLE_HEADERS = {
    "PlatformAdmin": PLATFORM_ADMIN,
    "StoreManager": STORE_MANAGER,
    "AttractionHost": ATTRACTION_HOST,
    "EventsCoordinator": EVENTS_COORDINATOR,
    "DealDeskClerk": DEAL_DESK_CLERK,
    "ServiceWriter": SERVICE_WRITER,
    "ServiceTechnician": SERVICE_TECHNICIAN,
    "ReceivingManager": RECEIVING_MANAGER,
    "PermitClerk": PERMIT_CLERK,
    "RemitAdmin": REMIT_ADMIN,
    "AgencyOperator": AGENCY_OPERATOR,
    "TitleClerk": TITLE_CLERK,
    "CreditUnderwriter": CREDIT_UNDERWRITER,
    "CreditOfficer": CREDIT_OFFICER,
    "ClubCardSpecialist": CLUB_CARD_SPECIALIST,
    "FinanceAdmin": FINANCE_ADMIN,
    "Anonymous": ANONYMOUS,
}


def headers_for(role: str, as_user_id: str | None = None) -> dict:
    """Resolve a design-recipe role name to request headers."""
    if role == "Member":
        if as_user_id is None:
            raise ValueError("Member calls must carry as_user_id (the Member row id)")
        return make_member_headers(as_user_id)
    try:
        return _OPAQUE_ROLE_HEADERS[role]
    except KeyError:  # pragma: no cover - defensive
        raise ValueError(f"Unknown recipe role: {role}") from None


def _resolve(value, ctx: dict):
    """Resolve ``${name}`` references (and ``${name} +/- N``) in a payload."""
    if isinstance(value, dict):
        return {k: _resolve(v, ctx) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve(v, ctx) for v in value]
    if not isinstance(value, str):
        return value

    arith = _ARITH_RE.match(value)
    if arith:
        name, op, amount = arith.group(1), arith.group(2), int(arith.group(3))
        base = int(ctx[name])
        return base + amount if op == "+" else base - amount

    full = _REF_RE.fullmatch(value)
    if full:
        return ctx[full.group(1)]

    return _REF_RE.sub(lambda m: str(ctx[m.group(1)]), value)


def _resolve_path(path: str, ctx: dict) -> str:
    return _REF_RE.sub(lambda m: str(ctx[m.group(1)]), path)


def _extract(body, spec: str, ctx: dict):
    """Extract a value from a JSON body via a ``$.``-rooted path."""
    spec = _resolve(spec, ctx)
    if not spec.startswith("$."):
        raise ValueError(f"capture path must start with $.: {spec}")
    node = body
    for segment in spec[2:].split("."):
        if isinstance(node, list):
            node = node[int(segment)]
        else:
            node = node[segment]
    return node


def execute_recipe(api, calls: list) -> dict:
    """Execute a design-recipe call chain and return the captured context.

    Setup calls must succeed — a failing setup call fails the test loudly.
    A step may set ``expect_error: True`` to mark a call whose error envelope
    is the point of the step; capture paths then simply do not resolve.
    """
    ctx: dict = {}
    for step in calls:
        method, path = step["call"].split(" ", 1)
        path = _resolve_path(path, ctx)
        payload = _resolve(step.get("payload") or {}, ctx)
        as_user_id = step.get("as_user_id")
        if isinstance(as_user_id, str):
            as_user_id = _resolve(as_user_id, ctx)
        headers = headers_for(step["as"], as_user_id)
        response = api._request(method, path, payload, headers)
        if response.status_code >= 400 and not step.get("expect_error"):
            raise AssertionError(
                f"setup step {method} {path} failed unexpectedly: "
                f"status={response.status_code} body={response.text}"
            )
        captures = step.get("captures") or {}
        if captures:
            try:
                body = response.json()
            except (ValueError, json.JSONDecodeError):
                body = {}
            for name, spec in captures.items():
                if response.status_code >= 400:
                    # An error envelope has no entity fields; leave unset.
                    continue
                try:
                    ctx[name] = _extract(body, spec, ctx)
                except (KeyError, IndexError, TypeError, ValueError) as exc:
                    raise AssertionError(
                        f"capture {name} ({spec}) failed on {method} {path}: {exc}; "
                        f"status={response.status_code} body={body}"
                    ) from exc
    return ctx


# ---------------------------------------------------------------------------
# Tier 1: state progression primitives
# ---------------------------------------------------------------------------

def set_clock(api, to_iso8601: str):
    """Move the logical store clock; the only way the clock ever advances."""
    return get_success_data(api.set_clock(to_iso8601, PLATFORM_ADMIN), 200)


def create_store(api, **overrides):
    from .factories import create_store_payload

    return get_success_data(
        api.create_store(create_store_payload(**overrides), PLATFORM_ADMIN), 201
    )


def create_member(api, store_id: str, **overrides):
    from .factories import create_member_payload

    return get_success_data(
        api.create_member(store_id, create_member_payload(**overrides), ANONYMOUS), 201
    )


def create_attraction(api, store_id: str, **overrides):
    from .factories import create_attraction_payload

    return get_success_data(
        api.create_attraction(
            store_id, create_attraction_payload(**overrides), STORE_MANAGER
        ),
        201,
    )


def open_attraction(api, attraction_id: str):
    return get_success_data(api.open_attraction(attraction_id, STORE_MANAGER), 200)


def create_open_attraction(api, store_id: str, **overrides):
    """Create a venue and open it for sessions."""
    attraction = create_attraction(api, store_id, **overrides)
    return get_success_data(api.open_attraction(attraction["id"], STORE_MANAGER), 200)


def create_waiver(api, store_id: str, member_id: str, **overrides):
    from .factories import create_waiver_payload

    return get_success_data(
        api.create_waiver(
            store_id, create_waiver_payload(member_id, **overrides), ATTRACTION_HOST
        ),
        201,
    )


def request_session(api, store_id: str, attraction_id: str, member_id: str, **overrides):
    """Request a venue session; the server auto-confirms, parks or rejects."""
    from .factories import create_session_payload

    return api.create_session(
        store_id,
        create_session_payload(attraction_id, member_id, **overrides),
        ATTRACTION_HOST,
    )


def create_boat_unit(api, store_id: str, **overrides):
    from .factories import create_boat_unit_payload

    return get_success_data(
        api.create_boat_unit(store_id, create_boat_unit_payload(**overrides),
                             DEAL_DESK_CLERK),
        201,
    )


def create_appraisal(api, store_id: str, member_id: str, boat_unit_id: str, **overrides):
    from .factories import create_appraisal_payload

    return get_success_data(
        api.create_appraisal(
            store_id,
            create_appraisal_payload(member_id, boat_unit_id, **overrides),
            DEAL_DESK_CLERK,
        ),
        201,
    )


def accept_appraisal(api, appraisal_id: str):
    return get_success_data(api.accept_appraisal(appraisal_id, DEAL_DESK_CLERK), 200)


def create_deal(api, store_id: str, member_id: str, boat_unit_id: str, **overrides):
    from .factories import create_deal_payload

    return get_success_data(
        api.create_deal(
            store_id, create_deal_payload(member_id, boat_unit_id, **overrides),
            DEAL_DESK_CLERK,
        ),
        201,
    )


def contract_deal(api, deal_id: str, expected_deal_version: int):
    return get_success_data(
        api.contract_deal(deal_id, {"expected_deal_version": expected_deal_version},
                          DEAL_DESK_CLERK),
        200,
    )


def fund_deal(api, deal_id: str, amount_cents: int, expected_deal_version: int):
    return get_success_data(
        api.fund_deal(
            deal_id,
            {"amount_cents": amount_cents,
             "expected_deal_version": expected_deal_version},
            FINANCE_ADMIN,
        ),
        200,
    )


def settle_deal(api, deal_id: str, expected_deal_version: int):
    return get_success_data(
        api.settle_deal(deal_id, {"expected_deal_version": expected_deal_version},
                        FINANCE_ADMIN),
        200,
    )


def create_service_order(api, store_id: str, boat_unit_id: str, **overrides):
    from .factories import create_service_order_payload

    return get_success_data(
        api.create_service_order(
            store_id, create_service_order_payload(boat_unit_id, **overrides),
            SERVICE_WRITER,
        ),
        201,
    )


def create_service_intake(api, store_id: str, member_id: str, service_order_id: str,
                          **overrides):
    from .factories import create_service_intake_payload

    return get_success_data(
        api.create_service_intake(
            store_id,
            create_service_intake_payload(member_id, service_order_id, **overrides),
            SERVICE_WRITER,
        ),
        201,
    )


def create_remit_batch(api, store_id: str, **overrides):
    from .factories import create_remit_batch_payload

    return get_success_data(
        api.create_remit_batch(store_id, create_remit_batch_payload(**overrides),
                               REMIT_ADMIN),
        201,
    )


def create_permit_sale(api, store_id: str, member_id: str, batch_id: str,
                       batch_version: int, **overrides):
    from .factories import create_permit_sale_payload

    return get_success_data(
        api.create_permit_sale(
            store_id,
            create_permit_sale_payload(member_id, batch_id, batch_version, **overrides),
            PERMIT_CLERK,
        ),
        201,
    )


def create_point_event(api, store_id: str, member_id: str, **overrides):
    from .factories import create_point_event_payload

    return get_success_data(
        api.create_point_event(
            store_id, create_point_event_payload(member_id, **overrides),
            CLUB_CARD_SPECIALIST,
        ),
        201,
    )


def create_event_offering(api, store_id: str, **overrides):
    from .factories import create_event_offering_payload

    return get_success_data(
        api.create_event_offering(
            store_id, create_event_offering_payload(**overrides), EVENTS_COORDINATOR
        ),
        201,
    )


def publish_event_offering(api, offering_id: str):
    return get_success_data(
        api.publish_event_offering(offering_id, EVENTS_COORDINATOR), 200
    )


def create_club_card_application(api, store_id: str, member_id: str, **overrides):
    from .factories import create_club_card_application_payload

    return get_success_data(
        api.create_club_card_application(
            store_id,
            create_club_card_application_payload(member_id, **overrides),
            CLUB_CARD_SPECIALIST,
        ),
        201,
    )


def create_bay_booking(api, store_id: str, member_id: str, service_order_id: str,
                       **overrides):
    from .factories import create_bay_booking_payload

    return get_success_data(
        api.create_bay_booking(
            store_id,
            create_bay_booking_payload(member_id, service_order_id, **overrides),
            RECEIVING_MANAGER,
        ),
        201,
    )


def create_order_fulfillment(api, store_id: str, member_id: str,
                             pre_service_order_id: str, booking_id: str,
                             booking_version: int, **overrides):
    from .factories import create_order_fulfillment_payload

    return get_success_data(
        api.create_order_fulfillment(
            store_id,
            create_order_fulfillment_payload(
                member_id, pre_service_order_id, booking_id, booking_version,
                **overrides,
            ),
            RECEIVING_MANAGER,
        ),
        201,
    )


# ---------------------------------------------------------------------------
# Tier 2: entity hierarchies
# ---------------------------------------------------------------------------

def setup_store_with_member(api, store_overrides=None, member_overrides=None,
                            clock="2026-09-01T00:00:00Z"):
    """Store at a known clock instant plus one club member."""
    if clock:
        set_clock(api, clock)
    store = create_store(api, **(store_overrides or {}))
    member = create_member(api, store["id"], **(member_overrides or {}))
    return store, member


def setup_open_venue(api, **store_overrides):
    """Store + open venue + one member. Returns (store, attraction, member)."""
    store = create_store(api, **store_overrides)
    member = create_member(api, store["id"], email="venue_member@example.com")
    attraction = create_open_attraction(api, store["id"])
    return store, attraction, member


def setup_waiver_venue(api, *, attraction_type="ARCHERY_RANGE", capacity_units=12,
                       dwell_cost_minutes=45, waiver_scope="ARCHERY_RANGE",
                       signed_at_utc="2026-08-01T00:00:00Z", waiver_term_days=365,
                       clock="2026-09-01T00:00:00Z"):
    """Store + waiver-requiring open venue + member holding a live waiver."""
    set_clock(api, clock)
    store = create_store(api)
    member = create_member(api, store["id"], email="waiver_member@example.com")
    attraction = create_open_attraction(
        api, store["id"], attraction_type=attraction_type,
        capacity_units=capacity_units, dwell_cost_minutes=dwell_cost_minutes,
    )
    waiver = create_waiver(
        api, store["id"], member["id"], activity_scope=waiver_scope,
        signed_at_utc=signed_at_utc, waiver_term_days=waiver_term_days,
    )
    return store, attraction, member, waiver


# ---------------------------------------------------------------------------
# Tier 3: lifecycle shortcuts
# ---------------------------------------------------------------------------

OZARK_NEW_UNIT = {
    "stock_no": "BU-9001",
    "model_name": "Angler 190",
    "unit_price_cents": 9_000_000,
    "motor_price_cents": 1_800_000,
    "trailer_price_cents": 350_000,
    "unit_condition": "NEW",
    "hull_id_no": "HIN9001AA000",
}

OZARK_BALANCE_DUE_CENTS = 12_102_193


def setup_contracted_deal(api, *, fund=False, issue_filing=False, clock="2026-09-01T00:00:00Z",
                          unit_overrides=None, member_overrides=None,
                          deposit_cents=None):
    """Store + member + NEW unit + deal walked to CONTRACTED.

    Returns a dict with store, member, unit, deal, filing and version keys.
    """
    set_clock(api, clock)
    store = create_store(api)
    member = create_member(api, store["id"], email="deal_member@example.com",
                           **(member_overrides or {}))
    unit_payload = dict(OZARK_NEW_UNIT)
    unit_payload.update(unit_overrides or {})
    unit = create_boat_unit(api, store["id"], **unit_payload)
    deal_overrides = {}
    if deposit_cents is not None:
        deal_overrides["deposit_cents"] = deposit_cents
    deal = create_deal(api, store["id"], member["id"], unit["id"], **deal_overrides)
    contracted = contract_deal(api, deal["id"], deal["version"])
    ctx = {
        "store": store,
        "member": member,
        "unit": unit,
        "deal": contracted,
        "contract_version": contracted["version"],
        "filing_id": contracted.get("title_filing_id"),
    }
    if issue_filing:
        get_success_data(api.submit_title_filing(ctx["filing_id"], TITLE_CLERK), 200)
        issued = get_success_data(
            api.issue_title_filing(ctx["filing_id"],
                                   {"agency_reference": "MO-TTL-55201"}, TITLE_CLERK),
            200,
        )
        ctx["filing"] = issued
        # Issuing the BOAT_TITLE filing advances the deal's title_status, which
        # is a mutation of the deal row: PRD §2.4 says a cascade from a parent
        # refreshes updated_at and increments version, and §2.10 then makes the
        # pre-issuance version stale for funding. Re-read before funding.
        refreshed_deal = get_success_data(
            api.get_deal(ctx["deal"]["id"], DEAL_DESK_CLERK), 200
        )
        ctx["deal"] = refreshed_deal
        ctx["contract_version"] = refreshed_deal["version"]
    if fund:
        funded = fund_deal(api, ctx["deal"]["id"], OZARK_BALANCE_DUE_CENTS,
                           ctx["contract_version"])
        ctx["funded_deal"] = funded
        ctx["fund_version"] = funded["version"]
    return ctx


def setup_fulfilled_rigging_order(api, ctx=None, *, order_kind="OVERSIZE_CARRYOUT",
                                  promised_lead_days=5, deal_linked=False,
                                  deliver_order=False, check_in_bay=False,
                                  release=False, bay_no=1):
    """Build a bay booking + order fulfilment chain on a rigging/oversize order.

    Walks the order INTAKE -> COMPLETED and optionally on to DELIVERED. When
    check_in_bay is set the bay is checked in before the order starts (that
    check-in is what releases an OVERSIZE_LOADING order to IN_PROGRESS); when
    release is set the fulfilment is released after the order reaches DELIVERED
    (the release requires a delivered pre-service order). Returns the extended
    context dict.
    """
    ctx = dict(ctx or {})
    store_id = ctx["store"]["id"]
    unit = ctx.get("unit") or ctx.get("boat_unit")
    member = ctx["member"]

    order_overrides = {
        "order_kind": "RIGGING" if deal_linked else "OVERSIZE_LOADING",
        "promised_lead_days": promised_lead_days,
    }
    if deal_linked:
        order_overrides["deal_id"] = ctx["deal"]["id"]
        order_overrides["boat_deal_id"] = ctx["deal"]["id"]
    order = create_service_order(api, store_id, unit["id"], **order_overrides)
    ctx["service_order"] = order

    booking = create_bay_booking(api, store_id, member["id"], order["id"],
                                 bay_no=bay_no)
    ctx["booking"] = booking

    fulfillment = create_order_fulfillment(
        api, store_id, member["id"], order["id"], booking["id"], booking["version"],
        order_kind=order_kind,
    )
    ctx["fulfillment"] = fulfillment

    # PRD §3.6: the check-in "is what lets the bay's linked OVERSIZE_LOADING
    # work order move from SCHEDULED to IN_PROGRESS", so it must precede the
    # order's own start hop.
    if check_in_bay:
        ctx["booking"] = get_success_data(
            api.check_in_bay_booking(booking["id"], RECEIVING_MANAGER), 200
        )
    get_success_data(api.schedule_service_order(order["id"], SERVICE_TECHNICIAN), 200)
    get_success_data(api.start_service_order(order["id"], SERVICE_TECHNICIAN), 200)
    ctx["service_order"] = get_success_data(
        api.complete_service_order(order["id"], SERVICE_TECHNICIAN), 200
    )
    if deliver_order:
        ctx["service_order"] = get_success_data(
            api.deliver_service_order(order["id"], SERVICE_TECHNICIAN), 200
        )
    # PRD §3.6: the release is gated on the pre-service order already being
    # DELIVERED, so it can only follow the deliver hop.
    if release:
        ctx["fulfillment"] = get_success_data(
            api.release_order_fulfillment(
                fulfillment["id"], {"rm_cross_check_code": "rm_7741"},
                RECEIVING_MANAGER,
            ),
            200,
        )
    return ctx


def setup_delivered_deal(api, *, clock="2026-09-01T00:00:00Z"):
    """Walk a deal all the way to DELIVERED (funded, titled, rigging complete).

    Returns the context dict extended with the delivered deal row.
    """
    ctx = setup_contracted_deal(api, issue_filing=True, clock=clock, fund=True)
    ctx = setup_fulfilled_rigging_order(api, ctx, deal_linked=True, deliver_order=True,
                                        check_in_bay=True, release=True)
    deal = get_success_data(
        api.get_deal(ctx["deal"]["id"], DEAL_DESK_CLERK), 200
    )
    ctx["deal"] = deal
    return ctx


def setup_settled_deal(api, *, clock="2026-09-01T00:00:00Z"):
    """Walk a deal through DELIVERED to SETTLED. Returns the context dict."""
    ctx = setup_delivered_deal(api, clock=clock)
    settled = get_success_data(
        api.settle_deal(ctx["deal"]["id"],
                        {"expected_deal_version": ctx["deal"]["version"]},
                        FINANCE_ADMIN),
        200,
    )
    ctx["deal"] = settled
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: accumulation / threshold targeting
# ---------------------------------------------------------------------------

def setup_member_with_points(api, target_lifetime: int, *, store=None,
                             member_overrides=None, email="points_member@example.com"):
    """Create a member and accumulate ``target_lifetime`` lifetime points.

    Awards are posted as AWARD events, each adding to both the balance and the
    lifetime total.
    """
    if store is None:
        set_clock(api, "2026-09-01T00:00:00Z")
        store = create_store(api)
    member = create_member(api, store["id"], email=email, **(member_overrides or {}))
    if target_lifetime > 0:
        create_point_event(api, store["id"], member["id"], event_kind="AWARD",
                           points_delta=target_lifetime)
    refreshed = get_success_data(api.get_member(member["id"], PLATFORM_ADMIN), 200)
    return store, refreshed


def setup_updated_member(api, member_id: str):
    """Re-read a member after a ledger mutation."""
    return get_success_data(api.get_member(member_id, PLATFORM_ADMIN), 200)


# ---------------------------------------------------------------------------
# Tier 5: finalization / terminal helpers
# ---------------------------------------------------------------------------

def setup_published_offering(api, store_id: str, **overrides):
    """Create and publish an event offering."""
    offering = create_event_offering(api, store_id, **overrides)
    return publish_event_offering(api, offering["id"])


def setup_verified_intake(api, *, intake_kind="OUTFITTING", deposit_cents=5_000,
                          specimen_quantity=1, permit_type=None,
                          quoted_lead_days=20, clock="2026-09-01T00:00:00Z"):
    """Store + member + unit + order + intake walked to PERMIT_VERIFIED.

    For TAXIDERMY the caller must supply ``permit_type`` (HUNTING or
    ARCHERY_RANGE) and a permit sale is created first.
    """
    set_clock(api, clock)
    store = create_store(api)
    member = create_member(api, store["id"], email="intake_member@example.com")
    unit = create_boat_unit(api, store["id"], stock_no="BU-IN", model_name="Bay 170",
                            unit_price_cents=4_000_000, unit_condition="USED",
                            hull_id_no="HININ0000001",
                            motor_price_cents=0, trailer_price_cents=0)
    order = create_service_order(api, store["id"], unit["id"],
                                 order_kind="TAXIDERMY" if intake_kind == "TAXIDERMY"
                                 else "OUTFITTING",
                                 promised_lead_days=60)

    permit_sale = None
    intake_overrides = {
        "intake_kind": intake_kind,
        "specimen_quantity": specimen_quantity,
        "deposit_cents": deposit_cents,
        "quoted_lead_days": quoted_lead_days,
    }
    if permit_type:
        batch = create_remit_batch(api, store["id"])
        permit_sale = create_permit_sale(
            api, store["id"], member["id"], batch["id"], batch["version"],
            permit_type=permit_type, term_days=30,
        )
        intake_overrides["permit_sale_id"] = permit_sale["id"]
        intake_overrides["species_code"] = "WTDEER"

    intake = create_service_intake(api, store["id"], member["id"], order["id"],
                                   **intake_overrides)
    verified = get_success_data(
        api.verify_intake_permit(intake["id"], SERVICE_WRITER), 200
    )
    return {
        "store": store,
        "member": member,
        "unit": unit,
        "service_order": order,
        "permit_sale": permit_sale,
        "intake": verified,
    }