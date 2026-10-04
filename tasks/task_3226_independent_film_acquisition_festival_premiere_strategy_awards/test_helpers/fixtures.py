"""Composite setup helpers.

Every helper builds preconditions from scratch against an empty database
(the harness restarts the server before every test). All helpers use
get_success_data() so setup failures surface as clear "Setup failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_film_payload,
    create_territory_payload,
    create_festival_payload,
    create_premiere_slot_payload,
    create_offer_payload,
    create_release_plan_payload,
    create_awards_campaign_payload,
    create_talent_obligation_payload,
)
from .test_users import TEST_USERS

ADMIN = TEST_USERS["admin_headers"]
ACQ = TEST_USERS["acq_exec_headers"]
ACQ2 = TEST_USERS["acq_exec_2_headers"]
PROG = TEST_USERS["festival_prog_headers"]
DIST = TEST_USERS["dist_exec_headers"]
STRAT = TEST_USERS["awards_strat_headers"]
STRAT2 = TEST_USERS["awards_strat_2_headers"]
COORD = TEST_USERS["talent_coord_headers"]
ACCT = TEST_USERS["part_acct_headers"]


# ─── Tier 1: reference data ───────────────────────────────────────────────

def setup_territory(code="US", name=None, is_home_ent_eligible=True):
    """Register a territory. Returns the territory dict."""
    resp = api_client.create_territory(
        create_territory_payload(
            code=code, name=name or f"{code} Territory",
            is_home_ent_eligible=is_home_ent_eligible,
        ),
        ADMIN,
    )
    return get_success_data(resp)


def setup_festival(code="SUNDANCE", prestige_tier="A_LIST", **overrides):
    """Register a festival. Returns the festival dict."""
    payload = create_festival_payload(code=code, prestige_tier=prestige_tier)
    payload.update(overrides)
    resp = api_client.create_festival(payload, ADMIN)
    return get_success_data(resp)


# ─── Tier 2: films and acquisition ────────────────────────────────────────

def setup_film(**overrides):
    """Register a film. Returns the film dict."""
    resp = api_client.create_film(create_film_payload(**overrides), ADMIN)
    return get_success_data(resp)


def setup_film_with_offer(film_overrides=None, offer_overrides=None,
                          territory_code="US", offer_headers=None):
    """Film + territory + one OPEN offer. Returns (film, offer).

    The offer is created by the shared ACQ identity unless ``offer_headers``
    is supplied; tests that exercise segregation-of-duties pass explicit
    user headers so the creator identity matches the actor under test.
    """
    setup_territory(code=territory_code)
    film = setup_film(**(film_overrides or {}))
    offer = api_client.create_offer(
        film["id"], create_offer_payload(**(offer_overrides or {})),
        offer_headers or ACQ,
    )
    return film, get_success_data(offer)


def acquire_film(film_overrides=None, offer_overrides=None,
                 territory_code="US"):
    """Film acquired via accepted offer.

    The offer is created by ACQ2 and accepted by ACQ (different user ids,
    satisfying the segregation-of-duties rule). Returns (film, offer, deal).
    """
    setup_territory(code=territory_code)
    film = setup_film(**(film_overrides or {}))
    offer_resp = api_client.create_offer(
        film["id"], create_offer_payload(**(offer_overrides or {})), ACQ2,
    )
    offer = get_success_data(offer_resp)
    film_now = get_success_data(api_client.get_film(film["id"], ACQ))
    deal_resp = api_client.accept_offer(
        film["id"], offer["id"],
        {"expected_film_version": film_now["version"]}, ACQ,
    )
    deal = get_success_data(deal_resp)
    film = get_success_data(api_client.get_film(film["id"], ACQ))
    return film, offer, deal


# ─── Tier 3: premiere locking ─────────────────────────────────────────────

def setup_premiere_slot(festival_id, **overrides):
    """Declare an OPEN premiere slot. Returns the slot dict."""
    resp = api_client.create_premiere_slot(
        festival_id, create_premiere_slot_payload(**overrides), PROG,
    )
    return get_success_data(resp)


def acquire_film_with_premiere(film_overrides=None, offer_overrides=None,
                               festival_overrides=None, slot_overrides=None,
                               territory_code="US"):
    """Acquired film + booked premiere slot (release_posture == PREMIERE_LOCKED).

    Returns (film, offer, deal, festival, slot).
    """
    film, offer, deal = acquire_film(
        film_overrides=film_overrides, offer_overrides=offer_overrides,
        territory_code=territory_code,
    )
    festival = setup_festival(**(festival_overrides or {}))
    slot = setup_premiere_slot(festival["id"], **(slot_overrides or {}))
    slot = get_success_data(
        api_client.hold_premiere_slot(
            festival["id"], slot["id"], {"film_id": film["id"]}, PROG,
        )
    )
    film_now = get_success_data(api_client.get_film(film["id"], PROG))
    slot = get_success_data(
        api_client.book_premiere_slot(
            festival["id"], slot["id"],
            {"expected_film_version": film_now["version"]}, PROG,
        )
    )
    film = get_success_data(api_client.get_film(film["id"], ACQ))
    return film, offer, deal, festival, slot


# ─── Tier 4: release plans ────────────────────────────────────────────────

def setup_open_release_plan(film, deal, target_market_codes=("NY",),
                            plan_overrides=None):
    """Create + open a release plan on an acquired, premiere-locked film.

    Returns (plan, initial_screenings_by_market).
    """
    overrides = dict(plan_overrides or {})
    overrides.setdefault("target_market_codes", list(target_market_codes))
    plan = get_success_data(
        api_client.create_release_plan(
            film["id"], create_release_plan_payload(
                deal_id=deal["id"], **overrides,
            ),
            DIST,
        )
    )
    plan = get_success_data(
        api_client.open_release_plan(film["id"], plan["id"], DIST)
    )
    screenings = {}
    for market in target_market_codes:
        data, _meta = _paginated(
            api_client.list_market_screenings(
                plan["id"], DIST, params={"market_code": market},
            )
        )
        assert len(data) == 1, f"Setup failed: expected 1 screening for {market}"
        screenings[market] = data[0]
    return plan, screenings


def _paginated(resp):
    """Return (data_list, meta) from a list response."""
    body = resp.json()
    assert 200 <= resp.status_code < 300, f"Setup failed: {resp.status_code} {body}"
    return body["data"], body.get("meta", {})


# ─── Tier 5: awards campaigns ─────────────────────────────────────────────

def setup_active_campaign(film, deal, campaign_overrides=None,
                          creator_headers=None, activator_headers=None):
    """Create + activate an awards campaign on a premiere-locked film.

    Returns the ACTIVE campaign dict.
    """
    overrides = dict(campaign_overrides or {})
    overrides.setdefault("deal_id", deal["id"])
    campaign = get_success_data(
        api_client.create_awards_campaign(
            film["id"],
            create_awards_campaign_payload(**overrides),
            creator_headers or STRAT,
        )
    )
    campaign = get_success_data(
        api_client.activate_awards_campaign(
            film["id"], campaign["id"], activator_headers or STRAT,
        )
    )
    return campaign


def setup_premiered_film_with_active_campaign(campaign_overrides=None,
                                              **acquire_kwargs):
    """Full chain: territory -> film -> offer -> accept -> festival -> slot ->
    hold -> book -> campaign -> activate.

    Returns (film, deal, festival, slot, campaign).
    """
    film, offer, deal, festival, slot = acquire_film_with_premiere(
        **acquire_kwargs,
    )
    campaign = setup_active_campaign(film, deal, campaign_overrides)
    return film, deal, festival, slot, campaign


# ─── Tier 6: talent obligations ───────────────────────────────────────────

def setup_confirmed_obligation(film_id, obligation_overrides=None):
    """Create + confirm a talent obligation. Returns the CONFIRMED obligation."""
    ob = get_success_data(
        api_client.create_talent_obligation(
            film_id,
            create_talent_obligation_payload(**(obligation_overrides or {})),
            COORD,
        )
    )
    ob = get_success_data(
        api_client.confirm_talent_obligation(film_id, ob["id"], COORD)
    )
    return ob
