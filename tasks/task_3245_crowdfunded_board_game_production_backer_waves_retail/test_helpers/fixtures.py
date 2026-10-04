"""Composite setup helpers — multi-step API preambles shared by many tests.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints (the server is restarted between tests, so state never carries over).
Fixtures use get_success_data() so setup failures surface as clear errors.

Common chain encoded below (used by wave/freight/replacement tests):

  clock(09-01) -> campaign -> launch -> pledge -> charge -> confirm-address
  -> clock(09-06) -> quote -> submit -> finalize -> run -> lock
  -> start-production -> freight booked -> clock(departs) -> depart
  -> clock(arrives) -> arrive -> assess-duty -> pay-duty
  -> deliver-to-warehouse   [shipment now DELIVERED; region cleared]
  -> wave -> open           [campaign now FULFILLING]
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_campaign_payload,
    create_distributor_allocation_payload,
    create_freight_shipment_payload,
    create_localization_agreement_payload,
    create_manufacturing_quote_payload,
    create_pledge_payload,
    create_production_run_payload,
    create_replacement_request_payload,
    create_wave_payload,
)
from .test_users import TEST_USERS, make_backer_headers

OWNER = TEST_USERS["campaign_owner_headers"]
BACKERS = TEST_USERS["backer_headers"]
FACTORY = TEST_USERS["factory_coordinator_headers"]
FREIGHT = TEST_USERS["freight_broker_headers"]
CUSTOMS = TEST_USERS["customs_agent_headers"]
FULFILL = TEST_USERS["fulfillment_operator_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]
LOCAL = TEST_USERS["localization_partner_headers"]


def set_clock(current_utc: str) -> dict:
    resp = api_client.set_clock(current_utc, ADMIN)
    return get_success_data(resp)


def create_campaign(**overrides) -> dict:
    """Create a DRAFT campaign. Returns the campaign body."""
    resp = api_client.create_campaign(create_campaign_payload(**overrides), OWNER)
    return get_success_data(resp)


def launch_campaign(campaign_id: str) -> dict:
    resp = api_client.transition_campaign(campaign_id, {"action": "launch"}, OWNER)
    return get_success_data(resp)


def get_campaign(campaign_id: str) -> dict:
    return get_success_data(api_client.get_campaign(campaign_id, ADMIN))


def get_campaign_version(campaign_id: str) -> int:
    return get_campaign(campaign_id)["version"]


def create_pledge(campaign_id: str, **overrides) -> dict:
    """Create a PENDING pledge; reads current campaign version for OCC."""
    version = get_campaign_version(campaign_id)
    payload = create_pledge_payload(
        campaign_id, expected_campaign_version=version, **overrides
    )
    resp = api_client.create_pledge(payload, ADMIN)
    return get_success_data(resp)


def charge_pledge(pledge_id: str, payment_outcome=None) -> dict:
    payload = {"action": "charge"}
    if payment_outcome is not None:
        payload["payment_outcome"] = payment_outcome
    resp = api_client.transition_pledge(pledge_id, payload, OWNER)
    return get_success_data(resp)


def refund_pledge(pledge_id: str) -> dict:
    return get_success_data(
        api_client.transition_pledge(pledge_id, {"action": "refund"}, OWNER)
    )


def confirm_address(pledge_id: str, backer_user_id: str) -> dict:
    resp = api_client.transition_pledge(
        pledge_id,
        {"action": "confirm-address"},
        make_backer_headers(backer_user_id),
    )
    return get_success_data(resp)


def create_charged_pledge(campaign_id: str, **overrides) -> dict:
    """Create + charge a pledge. Returns the pledge body (CHARGED)."""
    pledge = create_pledge(campaign_id, **overrides)
    return charge_pledge(pledge["id"])


def close_campaign_via_clock(campaign_id: str, close_utc: str = "2026-10-02T00:00:00Z") -> dict:
    """Advance the clock past closes_at so the system closes the campaign.

    Default close_utc suits campaigns created with the default closes_at
    (2026-10-01). For campaigns with closes_at 2026-09-05 pass
    close_utc="2026-09-06T00:00:00Z".
    """
    set_clock(close_utc)
    return get_campaign(campaign_id)


def create_quote(campaign_id: str, **overrides) -> dict:
    resp = api_client.create_manufacturing_quote(
        create_manufacturing_quote_payload(campaign_id, **overrides), FACTORY
    )
    return get_success_data(resp)


def submit_quote(quote_id: str) -> dict:
    return get_success_data(
        api_client.transition_manufacturing_quote(quote_id, {"action": "submit"}, FACTORY)
    )


def finalize_quote(quote_id: str) -> dict:
    return get_success_data(
        api_client.transition_manufacturing_quote(
            quote_id, {"action": "finalize"}, FACTORY
        )
    )


def create_final_quote(campaign_id: str, **overrides) -> dict:
    """Create -> submit -> finalize a quote. Campaign must be CLOSED_SUCCESS."""
    quote = create_quote(campaign_id, **overrides)
    submit_quote(quote["id"])
    return finalize_quote(quote["id"])


def create_run(campaign_id: str, quote_id: str, **overrides) -> dict:
    resp = api_client.create_production_run(
        create_production_run_payload(campaign_id, quote_id, **overrides), FACTORY
    )
    return get_success_data(resp)


def lock_run(run_id: str) -> dict:
    return get_success_data(
        api_client.transition_production_run(run_id, {"action": "lock"}, FACTORY)
    )


def create_locked_run(campaign_id: str, quote_id: str, **overrides) -> dict:
    run = create_run(campaign_id, quote_id, **overrides)
    return lock_run(run["id"])


def start_production(campaign_id: str) -> dict:
    return get_success_data(
        api_client.transition_campaign(
            campaign_id, {"action": "start-production"}, OWNER
        )
    )


def book_freight(run_id: str, **overrides) -> dict:
    resp = api_client.create_freight_shipment(
        create_freight_shipment_payload(run_id, **overrides), FREIGHT
    )
    return get_success_data(resp)


def transition_freight(shipment_id: str, action: str, headers=None, **extra) -> dict:
    payload = {"action": action}
    payload.update(extra)
    resp = api_client.transition_freight_shipment(
        shipment_id, payload, headers or FREIGHT
    )
    return get_success_data(resp)


def deliver_freight_to_warehouse(shipment_id: str) -> dict:
    return transition_freight(
        shipment_id, "deliver-to-warehouse", headers=FULFILL
    )


def ship_freight_fully(shipment) -> dict:
    """BOOKED -> ... -> DELIVERED. Uses the shipment's own window."""
    departs = shipment["departs_at"]
    arrives = shipment["arrives_at"]
    sid = shipment["id"]
    set_clock(departs)
    transition_freight(sid, "depart")
    set_clock(arrives)
    transition_freight(sid, "arrive")
    transition_freight(sid, "assess-duty", headers=CUSTOMS)
    transition_freight(sid, "pay-duty", headers=CUSTOMS)
    return deliver_freight_to_warehouse(sid)


def create_wave(campaign_id: str, **overrides) -> dict:
    resp = api_client.create_wave(create_wave_payload(campaign_id, **overrides), FULFILL)
    return get_success_data(resp)


def open_wave(wave_id: str) -> dict:
    return get_success_data(
        api_client.transition_wave(wave_id, {"action": "open"}, FULFILL)
    )


def assign_pledge(wave_id: str, pledge_id: str, campaign_id: str) -> dict:
    version = get_campaign_version(campaign_id)
    resp = api_client.transition_wave(
        wave_id,
        {
            "action": "assign",
            "pledge_id": pledge_id,
            "expected_campaign_version": version,
        },
        FULFILL,
    )
    return get_success_data(resp)


def create_distributor_allocation(campaign_id: str, run_id: str, **overrides) -> dict:
    resp = api_client.create_distributor_allocation(
        create_distributor_allocation_payload(campaign_id, run_id, **overrides), ADMIN
    )
    return get_success_data(resp)


def create_localization_agreement(campaign_id: str, **overrides) -> dict:
    resp = api_client.create_localization_agreement(
        create_localization_agreement_payload(campaign_id, **overrides), LOCAL
    )
    return get_success_data(resp)


def create_replacement_request(campaign_id: str, pledge_id: str, backer_user_id: str, **overrides) -> dict:
    resp = api_client.create_replacement_request(
        create_replacement_request_payload(campaign_id, pledge_id, **overrides),
        make_backer_headers(backer_user_id),
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2/3 composites
# ---------------------------------------------------------------------------


def setup_live_campaign(**campaign_overrides) -> dict:
    """Clock at 2026-09-01 + DRAFT campaign -> LIVE. Returns campaign."""
    set_clock("2026-09-01T00:00:00Z")
    campaign = create_campaign(**campaign_overrides)
    return launch_campaign(campaign["id"])


def setup_closed_success_campaign(clock_to="2026-09-06T00:00:00Z", _charge_backer=("b1", "b1@x"), **campaign_overrides) -> dict:
    """LIVE campaign whose closes_at (2026-09-05 default in this helper) has
    passed with goal met (default goal 1000c is met by one charged 5000c
    pledge). Returns the CLOSED_SUCCESS campaign.

    ``_charge_backer`` is the (user_id, email) identity used for the
    pre-close charged pledge; composites that add pledges of their own pass
    a distinct identity so the per-campaign email uniqueness rule (PRD
    §3.3) is not tripped."""
    overrides = {"closes_at": "2026-09-05T00:00:00Z"}
    overrides.update(campaign_overrides)
    campaign = setup_live_campaign(**overrides)
    pledge = create_charged_pledge(
        campaign["id"], backer_user_id=_charge_backer[0], backer_email=_charge_backer[1]
    )
    campaign = close_campaign_via_clock(campaign["id"], close_utc=clock_to)
    campaign["_charged_pledge"] = pledge
    return campaign


def setup_campaign_in_production(**campaign_overrides) -> dict:
    """Full pipeline to IN_PRODUCTION: CLOSED_SUCCESS campaign, FINAL quote,
    LOCKED run, start-production. Returns dict with campaign, quote, run.
    Quote-scoped keys (factory_name, tier_breaks) are peeled off and applied
    to the quote; everything else goes to the campaign.

    ``_signed_commitments`` (int, optional): before the quote is finalized,
    sign a localization agreement with this many print_commitment_units so
    the run's planned_units (and hence its spare pool) is large enough for
    replacement scenarios (PRD §3.4: SIGNED commitments count into the
    final variant; PRD §3.10: sign is free of overlap gates when no freight
    exists yet)."""
    quote_keys = {"factory_name", "tier_breaks"}
    quote_overrides = {k: campaign_overrides.pop(k) for k in list(campaign_overrides) if k in quote_keys}
    commitments = campaign_overrides.pop("_signed_commitments", 0)
    campaign = setup_closed_success_campaign(
        _charge_backer=("b0", "b0@x"), **campaign_overrides
    )
    charged_pledge = campaign.pop("_charged_pledge")
    if commitments:
        agreement = create_localization_agreement(
            campaign["id"], print_commitment_units=commitments
        )
        get_success_data(
            api_client.transition_localization_agreement(
                agreement["id"], {"action": "sign"}, LOCAL
            )
        )
    quote = create_final_quote(campaign["id"], **quote_overrides)
    run = create_locked_run(campaign["id"], quote["id"])
    start_production(campaign["id"])
    campaign = get_campaign(campaign["id"])
    return {"campaign": campaign, "quote": quote, "run": run,
            "charged_pledge": charged_pledge}


def setup_campaign_with_cleared_freight(**campaign_overrides) -> dict:
    """IN_PRODUCTION plus one DELIVERED NA freight shipment on the run.
    Returns dict with campaign, quote, run, shipment."""
    bundle = setup_campaign_in_production(**campaign_overrides)
    shipment = book_freight(bundle["run"]["id"])
    ship_freight_fully(shipment)
    bundle["shipment"] = get_success_data(
        api_client.get_freight_shipment(shipment["id"], ADMIN)
    )
    bundle["campaign"] = get_campaign(bundle["campaign"]["id"])
    return bundle


def setup_open_wave_with_assigned_pledge(**campaign_overrides) -> dict:
    """FULFILLING campaign with an OPEN wave (seq 1, region NA) and one
    CHARGED+CONFIRMED pledge ASSIGNED to it. Returns dict with campaign, run,
    shipment, wave, pledge."""
    bundle = setup_campaign_with_cleared_freight(**campaign_overrides)
    campaign = bundle["campaign"]
    # Second backer identity: the setup chain already charged a pledge for
    # b1/b1@x, and backer_email is unique within the campaign (PRD §3.3).
    pledge = create_charged_pledge(
        campaign["id"], backer_user_id="b2", backer_email="b2@x"
    )
    confirm_address(pledge["id"], "b2")
    wave = create_wave(campaign["id"])
    open_wave(wave["id"])
    assign_pledge(wave["id"], pledge["id"], campaign["id"])
    bundle["wave"] = get_success_data(api_client.get_wave(wave["id"], ADMIN))
    bundle["pledge"] = get_success_data(api_client.get_pledge(pledge["id"], ADMIN))
    bundle["campaign"] = get_campaign(campaign["id"])
    return bundle


def setup_delivered_pledge(**campaign_overrides) -> dict:
    """One pledge fully DELIVERED via the wave pipeline. Returns dict with
    campaign, run, shipment, wave, pledge (pledge in DELIVERED state)."""
    bundle = setup_open_wave_with_assigned_pledge(**campaign_overrides)
    campaign = bundle["campaign"]
    wave = bundle["wave"]
    pledge = bundle["pledge"]
    # Move clock into dispatch window, then pick -> ship -> deliver.
    set_clock(wave["dispatch_window_start"])
    api_client.transition_wave(
        wave["id"], {"action": "pick", "pledge_id": pledge["id"]}, FULFILL
    )
    api_client.transition_wave(
        wave["id"], {"action": "ship", "pledge_id": pledge["id"]}, FULFILL
    )
    resp = api_client.transition_wave(
        wave["id"], {"action": "deliver", "pledge_id": pledge["id"]}, FULFILL
    )
    get_success_data(resp)
    bundle["pledge"] = get_success_data(api_client.get_pledge(pledge["id"], ADMIN))
    bundle["wave"] = get_success_data(api_client.get_wave(wave["id"], ADMIN))
    bundle["campaign"] = get_campaign(campaign["id"])
    return bundle
