"""Composite setup helpers for the seasonal slate programming tests.

Every fixture builds its preconditions from scratch via PRD-declared endpoints.
Fixtures use get_success_data() (lenient) so setup failures surface as clear
"Setup failed" errors rather than confusing assertion failures.

Naming convention: make_* create one entity; setup_* build composite state.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_studio_payload,
    create_season_payload,
    create_title_payload,
    create_talent_payload,
    create_deal_payload,
    create_casting_payload,
    create_location_payload,
    create_production_slot_payload,
    create_program_block_payload,
    create_air_slot_payload,
    create_sponsorship_payload,
    create_streaming_window_payload,
    create_license_payload,
)
from .test_users import TEST_USERS, make_talent_agent_headers

ADMIN = TEST_USERS["platform_admin_headers"]
PLANNER = TEST_USERS["slate_planner_headers"]
PROD = TEST_USERS["production_manager_headers"]
EXEC = TEST_USERS["programming_exec_headers"]
ADS = TEST_USERS["ad_sales_rep_headers"]
STREAM = TEST_USERS["streaming_curator_headers"]
LIC = TEST_USERS["licensing_manager_headers"]

SPIKED_SEASON = {
    "air_window_start": "2027-11-01T00:00:00Z",
    "air_window_end": "2027-12-31T00:00:00Z",
    "delivery_deadline": "2027-10-01T00:00:00Z",
}


# ---------------------------------------------------------------------------
# Base makers
# ---------------------------------------------------------------------------

def set_clock(current_utc):
    """Advance the server-side logical clock (PlatformAdmin)."""
    return get_success_data(api_client.set_clock(current_utc, ADMIN))


def make_studio(**overrides):
    """Create a Studio. Returns the studio dict."""
    return get_success_data(api_client.create_studio(create_studio_payload(**overrides), ADMIN))


def make_season(studio_id, **overrides):
    """Create a Season (state DRAFT). Defaults to the December-spiked 2027 window."""
    payload = create_season_payload(studio_id=studio_id, **{**SPIKED_SEASON, **overrides})
    return get_success_data(api_client.create_season(payload, ADMIN))


def make_locked_season(studio_id, **overrides):
    """Create a Season and lock it. Returns (season_after_lock, locked_version)."""
    season = make_season(studio_id, **overrides)
    locked = get_success_data(api_client.lock_season(season["id"], EXEC))
    return locked, locked["version"]


def make_title(season_id, **overrides):
    """Create a PITCHED title."""
    return get_success_data(api_client.create_title(create_title_payload(season_id=season_id, **overrides), PLANNER))


def approve_title(title_id, expected_season_version):
    """Approve a PITCHED title (OCC on the season version). Returns title dict."""
    return get_success_data(
        api_client.approve_title(title_id, {"expected_season_version": expected_season_version}, PLANNER)
    )


def make_approved_title(season_id, season_version, **overrides):
    """Create + approve a title. Returns (title_dict, new_season_version)."""
    title = make_title(season_id, **overrides)
    approved = approve_title(title["id"], season_version)
    season = get_success_data(api_client.get_season(season_id, ADMIN))
    return approved, season["version"]


def make_location(studio_id, **overrides):
    return get_success_data(api_client.create_location(create_location_payload(studio_id=studio_id, **overrides), PROD))


def book_slot(title_id, location_id, shoot_start="2027-03-10T00:00:00Z",
              shoot_end="2027-03-20T00:00:00Z", shoot_days=10):
    """Book a production slot. Returns the BOOKED slot dict."""
    payload = create_production_slot_payload(
        title_id=title_id, location_id=location_id,
        shoot_start=shoot_start, shoot_end=shoot_end, shoot_days=shoot_days,
    )
    return get_success_data(api_client.create_production_slot(payload, PROD))


def make_talent(studio_id, availability_windows=None, **overrides):
    """Create a Talent. Returns (talent_dict, ownership_headers)."""
    payload = create_talent_payload(
        studio_id=studio_id,
        availability_windows=availability_windows if availability_windows is not None else [],
        **overrides,
    )
    talent = get_success_data(api_client.create_talent(payload, TEST_USERS["talent_agent_headers"]))
    return talent, make_talent_agent_headers(talent["id"])


def make_deal(talent_id, season_id, agent_headers, picture_commitment=1):
    """Create an ACTIVE deal (ownership-gated on the talent)."""
    return get_success_data(
        api_client.create_deal(
            create_deal_payload(talent_id=talent_id, season_id=season_id,
                                picture_commitment=picture_commitment),
            agent_headers,
        )
    )


def make_casting(title_id, talent_id, agent_headers):
    """Attach talent to a title (ATTACHED)."""
    return get_success_data(
        api_client.create_casting(create_casting_payload(title_id=title_id, talent_id=talent_id), agent_headers)
    )


def confirm_casting(casting_id, agent_headers):
    return get_success_data(api_client.confirm_casting(casting_id, agent_headers))


def make_program_block(season_id, **overrides):
    """Create a DRAFT program block."""
    return get_success_data(api_client.create_program_block(create_program_block_payload(season_id=season_id, **overrides), EXEC))


def make_published_block(season_id, **overrides):
    """Create + publish a program block. Returns (block, published_version)."""
    block = make_program_block(season_id, **overrides)
    published = get_success_data(api_client.publish_program_block(block["id"], EXEC))
    return published, published["version"]


def make_air_slot(block_id, title_id, air_start, kind, expected_block_version):
    return get_success_data(
        api_client.create_air_slot(
            create_air_slot_payload(block_id=block_id, title_id=title_id, air_start=air_start,
                                    kind=kind, expected_block_version=expected_block_version),
            EXEC,
        )
    )


def make_sponsorship(season_id, **overrides):
    return get_success_data(api_client.create_sponsorship(create_sponsorship_payload(season_id=season_id, **overrides), ADS))


def make_streaming_window(season_id, title_id, **overrides):
    return get_success_data(
        api_client.create_streaming_window(
            create_streaming_window_payload(season_id=season_id, title_id=title_id, **overrides), STREAM
        )
    )


def make_license(season_id, title_id, **overrides):
    return get_success_data(api_client.create_license(create_license_payload(season_id=season_id, title_id=title_id, **overrides), LIC))


# ---------------------------------------------------------------------------
# Composite fixtures
# ---------------------------------------------------------------------------

def setup_studio_with_season(required_title_count=1, ad_budget_cents=1000000,
                             max_shoot_days=100, locked=False, **season_overrides):
    """Studio + season. If locked=True the season is LOCKED.

    Returns dict with keys: studio, season, season_version (current).
    """
    studio = make_studio(ad_budget_cents=ad_budget_cents)
    if locked:
        season, version = make_locked_season(studio["id"], required_title_count=required_title_count,
                                             max_shoot_days=max_shoot_days, **season_overrides)
    else:
        season = make_season(studio["id"], required_title_count=required_title_count,
                             max_shoot_days=max_shoot_days, **season_overrides)
        version = season["version"]
    return {"studio": studio, "season": season, "season_version": version}


def setup_locked_season_with_approved_title(required_title_count=1, max_shoot_days=100,
                                            ad_budget_cents=1000000, **title_overrides):
    """Studio + LOCKED season + one APPROVED title.

    Returns dict: studio, season, season_version, title.
    """
    ctx = setup_studio_with_season(required_title_count=required_title_count,
                                   ad_budget_cents=ad_budget_cents,
                                   max_shoot_days=max_shoot_days, locked=True)
    title = make_title(ctx["season"]["id"], **title_overrides)
    approved = approve_title(title["id"], ctx["season_version"])
    season = get_success_data(api_client.get_season(ctx["season"]["id"], ADMIN))
    ctx.update({"title": approved, "season": season, "season_version": season["version"]})
    return ctx


def setup_delivered_title(required_title_count=1, ad_budget_cents=1000000,
                          clock="2027-03-01T00:00:00Z", **title_overrides):
    """Studio + LOCKED season + one title that is shot (WRAPPED) and DELIVERED.

    Returns dict: studio, season, season_version, title, location, slot.
    """
    set_clock(clock)
    ctx = setup_locked_season_with_approved_title(required_title_count=required_title_count,
                                                  ad_budget_cents=ad_budget_cents, **title_overrides)
    location = make_location(ctx["studio"]["id"])
    slot = book_slot(ctx["title"]["id"], location["id"])
    get_success_data(api_client.wrap_production_slot(slot["id"], PROD))
    delivered = get_success_data(api_client.deliver_title(ctx["title"]["id"], PROD))
    season = get_success_data(api_client.get_season(ctx["season"]["id"], ADMIN))
    ctx.update({"title": delivered, "location": location, "slot": slot,
                "season": season, "season_version": season["version"]})
    return ctx


def setup_archived_season_with_premieres(num_premieres, required_title_count=1,
                                         ad_budget_cents=10000000,
                                         clock="2027-03-01T00:00:00Z"):
    """Full chain: studio -> spiked LOCKED season -> one delivered title ->
    published block -> num_premieres PREMIERE slots marked AIRED -> season ARCHIVED.

    Premieres air weekly starting 2027-11-05 (cadence 7, block_start 2027-11-05).
    Returns dict: studio, season (ARCHIVED), title, block, air_slots, premiered_title_count.
    """
    ctx = setup_delivered_title(required_title_count=required_title_count,
                                ad_budget_cents=ad_budget_cents, clock=clock)
    season_id = ctx["season"]["id"]
    block, block_v = make_published_block(season_id)
    air_slots = []
    bv = block_v
    for i in range(num_premieres):
        day = 5 + 7 * i
        air_start = f"2027-11-{day:02d}T00:00:00Z"
        slot = make_air_slot(block["id"], ctx["title"]["id"], air_start, "PREMIERE", bv)
        air_slots.append(slot)
        # each creation bumps the block's version; re-read for the next OCC token
        block = get_success_data(api_client.get_program_block(block["id"], EXEC))
        bv = block["version"]
    if num_premieres > 0:
        last_day = 5 + 7 * (num_premieres - 1)
        set_clock(f"2027-11-{last_day:02d}T00:00:01Z")
        for slot in air_slots:
            get_success_data(api_client.mark_air_slot_aired(slot["id"], EXEC))
    archived = get_success_data(api_client.archive_season(season_id, EXEC))
    ctx.update({"season": archived, "season_version": archived["version"],
                "block": block, "air_slots": air_slots,
                "premiered_title_count": num_premieres})
    return ctx


def setup_talent_with_deal(season_id, studio_id, picture_commitment=1,
                           availability_windows=None):
    """Talent + ACTIVE deal. Returns (talent, agent_headers, deal)."""
    if availability_windows is None:
        availability_windows = [{"start": "2027-01-01T00:00:00Z", "end": "2027-12-01T00:00:00Z"}]
    talent, agent_headers = make_talent(studio_id, availability_windows=availability_windows)
    deal = make_deal(talent["id"], season_id, agent_headers, picture_commitment=picture_commitment)
    return talent, agent_headers, deal
