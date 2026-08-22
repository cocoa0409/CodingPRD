"""Composite setup helpers.

Every test starts against an empty database, so each fixture builds its whole
world from scratch using only PRD-declared endpoints. All setup calls go through
`get_success_data()` so a broken precondition surfaces as a clear "Setup step
failed" message rather than a confusing assertion further down.

Identity threading: whenever a fixture creates a Patron, a Musician or a
GuestArtistContract and then makes an ownership-gated call on its behalf, it
uses `make_patron_headers(...)` / `make_musician_headers(...)` /
`make_guest_artist_headers(...)` with that entity's real id.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    balcony_section_payload,
    create_ad_booking_payload,
    create_concert_payload,
    create_engagement_payload,
    create_guest_contract_payload,
    create_musician_payload,
    create_patron_payload,
    create_rehearsal_payload,
    create_season_payload,
    create_section_payload,
    create_subscription_payload,
    create_ticket_order_payload,
    create_union_agreement_payload,
    create_venue_payload,
    renew_subscription_payload,
    unique_email,
)
from .test_users import (
    ADVERTISING_SALES,
    ARTISTIC_ADMIN,
    BOX_OFFICE,
    ORCHESTRA_MANAGER,
    make_guest_artist_headers,
    make_musician_headers,
    make_patron_headers,
)

DEFAULT_CLOCK = "2026-09-01T00:00:00Z"

# Concert slots for the 2027 season (season A) and the 2028 season (season B).
CONCERT_SLOTS_A = [
    ("2026-11-05T19:30:00Z", "2026-11-05T21:30:00Z"),
    ("2026-12-05T19:30:00Z", "2026-12-05T21:30:00Z"),
    ("2027-01-05T19:30:00Z", "2027-01-05T21:30:00Z"),
    ("2027-02-05T19:30:00Z", "2027-02-05T21:30:00Z"),
    ("2027-03-05T19:30:00Z", "2027-03-05T21:30:00Z"),
    ("2027-04-05T19:30:00Z", "2027-04-05T21:30:00Z"),
    ("2027-05-05T19:30:00Z", "2027-05-05T21:30:00Z"),
    ("2027-06-05T19:30:00Z", "2027-06-05T21:30:00Z"),
]
CONCERT_SLOTS_B = [
    ("2027-11-05T19:30:00Z", "2027-11-05T21:30:00Z"),
    ("2027-12-05T19:30:00Z", "2027-12-05T21:30:00Z"),
    ("2028-01-05T19:30:00Z", "2028-01-05T21:30:00Z"),
]

SEASON_B_DEFAULTS = {
    "name": "2028 Season",
    "fiscal_year": 2028,
    "renewal_deadline_utc": "2027-10-01T00:00:00Z",
    "base_ticket_price_cents": 6000,
}


class World:
    """Container for a built-up scenario; attributes are set by the builders."""

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

    def __repr__(self):  # pragma: no cover - debugging aid only
        return f"World({sorted(self.__dict__)})"


# --------------------------------------------------------------------------
# Primitive setup steps
# --------------------------------------------------------------------------
def set_clock(to_iso8601=DEFAULT_CLOCK, headers=None):
    return get_success_data(
        api_client.set_clock(to_iso8601, headers or ARTISTIC_ADMIN)
    )


def create_season(**overrides):
    return get_success_data(
        api_client.create_season(create_season_payload(**overrides), ARTISTIC_ADMIN)
    )


def create_union_agreement(season_id, **overrides):
    return get_success_data(
        api_client.create_union_agreement(
            create_union_agreement_payload(season_id, **overrides), ORCHESTRA_MANAGER
        )
    )


def create_venue(**overrides):
    return get_success_data(
        api_client.create_venue(create_venue_payload(**overrides), ARTISTIC_ADMIN)
    )


def create_section(venue_id, **overrides):
    return get_success_data(
        api_client.create_section(
            create_section_payload(venue_id, **overrides), ARTISTIC_ADMIN
        )
    )


def create_balcony_section(venue_id, **overrides):
    return get_success_data(
        api_client.create_section(
            balcony_section_payload(venue_id, **overrides), ARTISTIC_ADMIN
        )
    )


def create_concert(season_id, venue_id, **overrides):
    return get_success_data(
        api_client.create_concert(
            create_concert_payload(season_id, venue_id, **overrides), ARTISTIC_ADMIN
        )
    )


def program_concert(concert_id):
    return get_success_data(api_client.program_concert(concert_id, ARTISTIC_ADMIN))


def advance_season(season_id, target_status):
    return get_success_data(
        api_client.advance_season(season_id, target_status, ARTISTIC_ADMIN)
    )


def open_renewal_window(season_id):
    return advance_season(season_id, "RENEWAL_WINDOW")


def open_public_onsale(season):
    """Move the clock to the season's renewal deadline, then advance to on-sale."""
    set_clock(season["renewal_deadline_utc"])
    return advance_season(season["id"], "SINGLE_ON_SALE")


def start_season(season_id):
    return advance_season(season_id, "IN_PROGRESS")


def close_season(season_id):
    return advance_season(season_id, "CLOSED")


def run_ops(season_id, headers=None):
    return get_success_data(api_client.run_ops(season_id, headers or BOX_OFFICE))


def create_patron(**overrides):
    payload = create_patron_payload(**overrides)
    return get_success_data(api_client.create_patron(payload, BOX_OFFICE))


def donate(patron_id, amount_cents):
    return get_success_data(
        api_client.record_donation(patron_id, amount_cents, BOX_OFFICE)
    )


def create_patron_at_level(donor_level, **overrides):
    """Register a patron and gift exactly enough to land on `donor_level`."""
    thresholds = {
        "NONE": 0,
        "FRIEND": 250_000,
        "SUSTAINER": 1_000_000,
        "BENEFACTOR": 2_500_000,
        "LAUREATE": 5_000_000,
    }
    patron = create_patron(**overrides)
    amount = thresholds[donor_level]
    if amount:
        patron = donate(patron["id"], amount)
    return patron


def create_musician(**overrides):
    return get_success_data(
        api_client.create_musician(create_musician_payload(**overrides), ORCHESTRA_MANAGER)
    )


def create_service(concert_id, venue_id, **overrides):
    return get_success_data(
        api_client.create_rehearsal(
            create_rehearsal_payload(concert_id, venue_id, **overrides), ORCHESTRA_MANAGER
        )
    )


def add_engagement(service_id, musician_id, **overrides):
    return get_success_data(
        api_client.create_engagement(
            service_id, create_engagement_payload(musician_id, **overrides),
            ORCHESTRA_MANAGER,
        )
    )


def publish_service(service_id):
    return get_success_data(api_client.publish_rehearsal(service_id, ORCHESTRA_MANAGER))


def clock_service(service_id, actual_start_utc, actual_end_utc):
    return get_success_data(
        api_client.clock_rehearsal(
            service_id, actual_start_utc, actual_end_utc, ORCHESTRA_MANAGER
        )
    )


def decline_engagement(engagement_id, musician_id):
    return get_success_data(
        api_client.decline_engagement(engagement_id, make_musician_headers(musician_id))
    )


def create_contract(concert_id, **overrides):
    return get_success_data(
        api_client.create_guest_contract(
            create_guest_contract_payload(concert_id, **overrides), ARTISTIC_ADMIN
        )
    )


def counter_contract(contract_id, countered_fee_cents):
    """The artist counters: X-User-ID is the contract's own id."""
    return get_success_data(
        api_client.counter_guest_contract(
            contract_id, countered_fee_cents, make_guest_artist_headers(contract_id)
        )
    )


def revise_offer(contract_id, offered_fee_cents):
    return get_success_data(
        api_client.revise_guest_contract_offer(
            contract_id, offered_fee_cents, ARTISTIC_ADMIN
        )
    )


def sign_contract_as_artist(contract_id):
    """Signing from OFFERED is the artist accepting the standing offer."""
    return get_success_data(
        api_client.sign_guest_contract(contract_id, make_guest_artist_headers(contract_id))
    )


def sign_contract_as_orchestra(contract_id):
    """Signing from COUNTERED is the orchestra accepting the artist's demand."""
    return get_success_data(api_client.sign_guest_contract(contract_id, ARTISTIC_ADMIN))


def create_ad_booking(season_id, **overrides):
    return get_success_data(
        api_client.create_ad_booking(
            create_ad_booking_payload(season_id, **overrides), ADVERTISING_SALES
        )
    )


def decide_ad_booking(booking_id, decision):
    return get_success_data(
        api_client.decide_ad_booking(booking_id, decision, ADVERTISING_SALES)
    )


# --------------------------------------------------------------------------
# Fresh reads
# --------------------------------------------------------------------------
def read_season(season_id, headers=None):
    return get_success_data(api_client.get_season(season_id, headers or ARTISTIC_ADMIN))


def read_venue(venue_id, headers=None):
    return get_success_data(api_client.get_venue(venue_id, headers or ARTISTIC_ADMIN))


def read_section(section_id, headers=None):
    return get_success_data(api_client.get_section(section_id, headers or ARTISTIC_ADMIN))


def read_concert(concert_id, headers=None):
    return get_success_data(api_client.get_concert(concert_id, headers or ARTISTIC_ADMIN))


def read_contract(contract_id, headers=None):
    return get_success_data(
        api_client.get_guest_contract(contract_id, headers or ARTISTIC_ADMIN)
    )


def read_musician(musician_id, headers=None):
    return get_success_data(
        api_client.get_musician(musician_id, headers or ORCHESTRA_MANAGER)
    )


def read_service(service_id, headers=None):
    return get_success_data(
        api_client.get_rehearsal(service_id, headers or ORCHESTRA_MANAGER)
    )


def read_engagement(engagement_id, headers=None):
    return get_success_data(
        api_client.get_engagement(engagement_id, headers or ORCHESTRA_MANAGER)
    )


def read_patron(patron_id, headers=None):
    return get_success_data(api_client.get_patron(patron_id, headers or BOX_OFFICE))


def read_subscription(subscription_id, headers=None):
    return get_success_data(
        api_client.get_subscription(subscription_id, headers or BOX_OFFICE)
    )


def read_ticket_order(order_id, headers=None):
    return get_success_data(api_client.get_ticket_order(order_id, headers or BOX_OFFICE))


def read_ad_booking(booking_id, headers=None):
    return get_success_data(
        api_client.get_ad_booking(booking_id, headers or ADVERTISING_SALES)
    )


def read_union_agreement(agreement_id, headers=None):
    return get_success_data(
        api_client.get_union_agreement(agreement_id, headers or ORCHESTRA_MANAGER)
    )


def current_concert_version(concert_id, headers=None):
    return read_concert(concert_id, headers)["version"]


def current_package_version(subscription_id, headers=None):
    return read_subscription(subscription_id, headers)["version"]


# --------------------------------------------------------------------------
# Tier 1/2: world builders
# --------------------------------------------------------------------------
def build_world(
    *,
    clock=DEFAULT_CLOCK,
    season_overrides=None,
    with_union=True,
    union_overrides=None,
    venue_overrides=None,
    section_specs=None,
    concert_count=1,
    concert_slots=None,
    concert_overrides=None,
    program_indexes="all",
    advance_to=None,
    titles=None,
):
    """Build a season with a hall, its sections and its concerts.

    Sections are always created before the concerts, so every concert snapshots
    the full inventory. `advance_to` walks the season lifecycle; reaching
    SINGLE_ON_SALE moves the logical clock to the renewal deadline first.
    """
    if clock:
        set_clock(clock)
    season = create_season(**(season_overrides or {}))
    agreement = None
    if with_union:
        agreement = create_union_agreement(season["id"], **(union_overrides or {}))

    venue = create_venue(**(venue_overrides or {}))
    specs = section_specs if section_specs is not None else [{}]
    sections = []
    for spec in specs:
        spec = dict(spec)
        if spec.pop("_balcony", False):
            sections.append(create_balcony_section(venue["id"], **spec))
        else:
            sections.append(create_section(venue["id"], **spec))

    slots = concert_slots or CONCERT_SLOTS_A
    concerts = []
    for index in range(concert_count):
        start, end = slots[index]
        overrides = {
            "title": (titles[index] if titles else f"C{index + 1}"),
            "performance_start_utc": start,
            "performance_end_utc": end,
        }
        overrides.update(concert_overrides or {})
        concerts.append(create_concert(season["id"], venue["id"], **overrides))

    if program_indexes == "all":
        program_indexes = list(range(concert_count))
    for index in program_indexes or []:
        program_concert(concerts[index]["id"])

    if advance_to in ("RENEWAL_WINDOW", "SINGLE_ON_SALE", "IN_PROGRESS", "CLOSED"):
        open_renewal_window(season["id"])
    if advance_to in ("SINGLE_ON_SALE", "IN_PROGRESS", "CLOSED"):
        open_public_onsale(season)
    if advance_to in ("IN_PROGRESS", "CLOSED"):
        start_season(season["id"])
    if advance_to == "CLOSED":
        close_season(season["id"])

    concerts = [read_concert(c["id"]) for c in concerts]
    world = World(
        season=read_season(season["id"]),
        union_agreement=agreement,
        venue=read_venue(venue["id"]),
        sections=sections,
        section=sections[0] if sections else None,
        section_ids=[s["id"] for s in sections],
        concerts=concerts,
        concert=concerts[0] if concerts else None,
        concert_ids=[c["id"] for c in concerts],
    )
    return world


def build_programmed_concert_world(**kwargs):
    """A PLANNING season with a union agreement and one PROGRAMMED concert."""
    return build_world(**kwargs)


def build_on_sale_world(**kwargs):
    """A season advanced all the way to SINGLE_ON_SALE (concert PUBLIC_ONSALE)."""
    kwargs.setdefault("advance_to", "SINGLE_ON_SALE")
    return build_world(**kwargs)


def build_renewal_window_world(**kwargs):
    """A season sitting in RENEWAL_WINDOW with its concerts on RENEWAL_ONLY."""
    kwargs.setdefault("advance_to", "RENEWAL_WINDOW")
    return build_world(**kwargs)


# --------------------------------------------------------------------------
# Tier 3: ticketing and subscription shortcuts
# --------------------------------------------------------------------------
def hold_tickets(concert_id, patron_id, seat_section_id, seat_count=1, headers=None,
                 expected_concert_version=None):
    """Read the concert's current version, then hold `seat_count` seats."""
    if expected_concert_version is None:
        expected_concert_version = current_concert_version(concert_id)
    payload = create_ticket_order_payload(
        concert_id, patron_id, seat_section_id, expected_concert_version,
        seat_count=seat_count,
    )
    return get_success_data(
        api_client.create_ticket_order(payload, headers or BOX_OFFICE)
    )


def pay_tickets(order_id, use_credit=False, headers=None):
    return get_success_data(
        api_client.pay_ticket_order(order_id, headers or BOX_OFFICE, use_credit=use_credit)
    )


def hold_and_pay_tickets(concert_id, patron_id, seat_section_id, seat_count=1,
                         use_credit=False):
    order = hold_tickets(concert_id, patron_id, seat_section_id, seat_count)
    return pay_tickets(order["id"], use_credit=use_credit)


def create_package(patron_id, season_id, seat_section_id, concert_ids, seat_count=1,
                   headers=None):
    payload = create_subscription_payload(
        patron_id, season_id, seat_section_id, concert_ids, seat_count=seat_count
    )
    return get_success_data(
        api_client.create_subscription(payload, headers or BOX_OFFICE)
    )


def pay_package(subscription_id, headers=None):
    return get_success_data(
        api_client.pay_subscription(subscription_id, headers or BOX_OFFICE)
    )


def create_and_pay_package(patron_id, season_id, seat_section_id, concert_ids,
                           seat_count=1):
    package = create_package(
        patron_id, season_id, seat_section_id, concert_ids, seat_count=seat_count
    )
    return pay_package(package["id"])


def renew_package(subscription_id, season_id, concert_ids, seat_count=None,
                  expected_package_version=None, headers=None):
    if expected_package_version is None:
        expected_package_version = current_package_version(subscription_id)
    payload = renew_subscription_payload(
        season_id, concert_ids, expected_package_version
    )
    if seat_count is not None:
        payload["seat_count"] = seat_count
    return get_success_data(
        api_client.renew_subscription(subscription_id, payload, headers or BOX_OFFICE)
    )


# --------------------------------------------------------------------------
# Tier 3: labour-side shortcuts
# --------------------------------------------------------------------------
def setup_published_service(
    *,
    world=None,
    world_kwargs=None,
    service_overrides=None,
    musician_specs=({},),
    doubling_counts=None,
):
    """A PROGRAMMED concert carrying one PUBLISHED service with N engagements.

    Returns a World with `.service`, `.musicians` and `.engagements` added.
    """
    world = world or build_world(**(world_kwargs or {}))
    service = create_service(
        world.concert["id"], world.venue["id"], **(service_overrides or {})
    )
    musicians = []
    engagements = []
    for index, spec in enumerate(musician_specs):
        spec = dict(spec)
        spec.setdefault("full_name", f"Player {index + 1}")
        musician = create_musician(**spec)
        musicians.append(musician)
        extra = {}
        if doubling_counts:
            extra["doubling_count"] = doubling_counts[index]
        engagements.append(add_engagement(service["id"], musician["id"], **extra))
    publish_service(service["id"])

    world.service = read_service(service["id"])
    world.musicians = musicians
    world.musician = musicians[0] if musicians else None
    world.engagements = [read_engagement(e["id"]) for e in engagements]
    world.engagement = world.engagements[0] if engagements else None
    world.concert = read_concert(world.concert["id"])
    return world


def setup_locked_concert(*, world=None, world_kwargs=None, contract_overrides=None,
                         service_overrides=None):
    """A concert whose only contract is SIGNED and whose service is PUBLISHED.

    Both conditions together drive programming_status to LOCKED.
    """
    world = world or build_world(**(world_kwargs or {}))
    contract = create_contract(world.concert["id"], **(contract_overrides or {}))
    sign_contract_as_artist(contract["id"])
    overrides = {"minimum_complement": 0, "break_minutes": 0}
    overrides.update(service_overrides or {})
    service = create_service(world.concert["id"], world.venue["id"], **overrides)
    publish_service(service["id"])

    world.contract = read_contract(contract["id"])
    world.service = read_service(service["id"])
    world.concert = read_concert(world.concert["id"])
    return world


# --------------------------------------------------------------------------
# Tier 4/5: two-season renewal chains
# --------------------------------------------------------------------------
def setup_renewal_chain(
    *,
    clock=DEFAULT_CLOCK,
    season_a_overrides=None,
    season_b_overrides=None,
    section_spec=None,
    balcony=True,
    concerts_a=1,
    concerts_b=1,
    patron_overrides=None,
    donation_cents=0,
    seat_count=1,
    pay=True,
    advance_b=True,
):
    """Two seasons plus a patron holding a package in the first one.

    Season A is advanced to RENEWAL_WINDOW and the patron's package is created
    (and by default paid, making it ACTIVE with consecutive_renewal_years 1).
    Season B shares the same hall and section, gets its own union agreement and
    programmed concerts, and is advanced to RENEWAL_WINDOW unless `advance_b`
    is False.
    """
    spec = dict(section_spec or {})
    if balcony:
        spec["_balcony"] = True

    world_a = build_world(
        clock=clock,
        season_overrides=season_a_overrides,
        section_specs=[spec],
        concert_count=concerts_a,
        titles=[f"A{i + 1}" for i in range(concerts_a)],
        advance_to="RENEWAL_WINDOW",
    )

    patron = create_patron(**(patron_overrides or {"full_name": "Iris Lund",
                                                   "email": unique_email("iris"),
                                                   "subscriber_since_year": 2018}))
    if donation_cents:
        patron = donate(patron["id"], donation_cents)

    package = create_package(
        patron["id"],
        world_a.season["id"],
        world_a.section["id"],
        world_a.concert_ids,
        seat_count=seat_count,
    )
    if pay:
        package = pay_package_and_read(package["id"])

    season_b_payload = dict(SEASON_B_DEFAULTS)
    season_b_payload.update(season_b_overrides or {})
    season_b = create_season(**season_b_payload)
    create_union_agreement(season_b["id"], scale_service_fee_cents=21000)
    concerts_b_list = []
    for index in range(concerts_b):
        start, end = CONCERT_SLOTS_B[index]
        concerts_b_list.append(
            create_concert(
                season_b["id"],
                world_a.venue["id"],
                title=f"B{index + 1}",
                performance_start_utc=start,
                performance_end_utc=end,
            )
        )
    for concert in concerts_b_list:
        program_concert(concert["id"])
    if advance_b:
        open_renewal_window(season_b["id"])

    return World(
        season_a=read_season(world_a.season["id"]),
        season_b=read_season(season_b["id"]),
        venue=world_a.venue,
        section=world_a.section,
        concerts_a=[read_concert(c["id"]) for c in world_a.concerts],
        concerts_b=[read_concert(c["id"]) for c in concerts_b_list],
        concert_ids_a=world_a.concert_ids,
        concert_ids_b=[c["id"] for c in concerts_b_list],
        patron=read_patron(patron["id"]),
        package=read_subscription(package["id"]),
    )


def pay_package_and_read(subscription_id):
    pay_package(subscription_id)
    return read_subscription(subscription_id)


def setup_in_progress_season(**kwargs):
    """A season advanced to IN_PROGRESS — the state in which concerts settle."""
    kwargs.setdefault("advance_to", "IN_PROGRESS")
    return build_world(**kwargs)
