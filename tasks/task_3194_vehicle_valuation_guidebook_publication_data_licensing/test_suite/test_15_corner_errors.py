"""Corner-design section: errors."""
from test_helpers import (
    api_client, validate_success, validate_error,
    setup_published_edition, setup_offer_scenario, inspect_offer,
    setup_active_agreement, make_consumer, make_dealer_headers,
    create_cash_offer_payload, get_edition, get_offer,
    NON_EXISTENT_UUID, ApiErrorId,
)
from test_helpers.fixtures import ADMIN, DATAOPS


def test_err_not_found_on_unknown_edition(api):
    """PRD §2.8: "The request is rejected with ERR_NOT_FOUND (HTTP 404) at
    the first path identifier that does not resolve, before any child
    identifier is examined." — an unknown path id on an edition read is a
    404 ERR_NOT_FOUND.

    Design: Corner/errors/err_not_found_on_unknown_edition
    """
    res = api.get_valuation_edition(NON_EXISTENT_UUID, ADMIN)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)


def test_err_edition_has_open_offers_on_withdraw(api):
    """PRD §3.4: "a PUBLISHED -> WITHDRAWN withdrawal is blocked while any
    cash offer built on the edition is still in a non-terminal state (QUOTED
    or INSPECTED); such an attempt is rejected with
    ERR_EDITION_HAS_OPEN_OFFERS (HTTP 422)."

    Design: Corner/errors/err_edition_has_open_offers_on_withdraw
    """
    env = setup_offer_scenario(segment="SEDAN", price_cents=2000000)
    offer = inspect_offer(env["offer"]["id"], env["source"]["id"], "GOOD")
    assert offer["status"] == "INSPECTED"

    res = api.withdraw_valuation_edition(env["edition"]["id"], ADMIN)
    validate_error(res, ApiErrorId.ERR_EDITION_HAS_OPEN_OFFERS.value)
    assert get_edition(env["edition"]["id"])["status"] == "PUBLISHED"
    assert get_offer(offer["id"])["status"] == "INSPECTED"


def test_err_stale_version_on_agreement_amend(api):
    """PRD §2.7: "Amending a license agreement's permitted_uses or
    monthly_event_quota likewise requires expected_version matching the
    agreement's current version; a mismatch is rejected with
    ERR_STALE_VERSION (HTTP 412), capturing the case where a prior amendment
    already advanced the agreement and the current caller's view of the
    license terms is stale."

    Design: Corner/errors/err_stale_version_on_agreement_amend
    """
    lic = setup_active_agreement(permitted_uses=("DISPLAY",),
                                 monthly_event_quota=1500)
    agreement = lic["agreement"]
    current = validate_success(
        api.get_license_agreement(agreement["id"], ADMIN), 200)
    observed_version = current["version"]

    amended = validate_success(api.patch_license_agreement(
        agreement["id"],
        {"monthly_event_quota": 2000, "expected_version": observed_version},
        ADMIN), 200)
    assert amended["monthly_event_quota"] == 2000

    res = api.patch_license_agreement(
        agreement["id"],
        {"monthly_event_quota": 3000, "expected_version": observed_version},
        ADMIN)
    validate_error(res, ApiErrorId.ERR_STALE_VERSION.value)

    final = validate_success(
        api.get_license_agreement(agreement["id"], ADMIN), 200)
    assert final["monthly_event_quota"] == 2000
