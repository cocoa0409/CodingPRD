"""Corner — state machines: invalid transitions, lockdown, preconditions,
idempotency.

Design: Corner/state_machines
"""
from test_helpers import (
    TEST_USERS, acquire_film_with_premiere, create_offer_payload,
    get_success_data, setup_active_campaign, setup_film,
    setup_film_with_offer, validate_error, validate_success,
)
from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import create_talent_obligation_payload

ACQ = TEST_USERS["acq_exec_headers"]
STRAT = TEST_USERS["awards_strat_headers"]
STRAT2 = TEST_USERS["awards_strat_2_headers"]
COORD = TEST_USERS["talent_coord_headers"]


class TestOfferInvalidTransition:
    def test_offer_accept_from_rejected_state_returns_invalid_state(self, api):
        """PRD §3.2: "It is rejected with `ERR_OFFER_ALREADY_TERMINAL`
        (HTTP 409) if the offer is not `OPEN`" — an offer in `REJECTED` is not
        `OPEN`, so an accept attempt on it is rejected with
        `ERR_OFFER_ALREADY_TERMINAL`.

        Design: Corner/state_machines/offer_accept_from_rejected_state_returns_invalid_state
        """
        film, offer = setup_film_with_offer()
        validate_success(api.reject_offer(film["id"], offer["id"], ACQ))

        film_now = get_success_data(api.get_film(film["id"], ACQ))
        resp = api.accept_offer(
            film["id"], offer["id"],
            {"expected_film_version": film_now["version"]}, ACQ,
        )
        validate_error(resp, ApiErrorId.ERR_OFFER_ALREADY_TERMINAL)


class TestTerminalStateLockdown:
    def test_terminal_state_lockdown_passed_film_rejects_new_offer(self, api):
        """PRD §3.1: "A successful pass moves the film to `PASSED`, terminal"
        — `PASSED` is a terminal acquisition status, so opening a new
        negotiation offer on a passed film is rejected with
        `ERR_INVALID_STATE` (HTTP 409).

        Design: Corner/state_machines/terminal_state_lockdown_passed_film_rejects_new_offer
        """
        film = setup_film()
        validate_success(api.pass_film(film["id"], ACQ))

        film_now = get_success_data(api.get_film(film["id"], ACQ))
        assert film_now["acquisition_status"] == "PASSED"

        resp = api.create_offer(
            film["id"], create_offer_payload(), ACQ,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestFulfillTooEarly:
    def test_fulfill_before_window_end_returns_fulfill_too_early(self, api):
        """PRD §3.8: "Fulfilling an obligation transitions it `CONFIRMED →
        FULFILLED`, but only once the logical clock has reached the
        obligation's `window_ends_at`. An attempt to fulfill earlier is
        rejected with `ERR_FULFILL_TOO_EARLY` (HTTP 409)."

        Design: Corner/state_machines/fulfill_before_window_end_returns_fulfill_too_early
        """
        film = setup_film()
        ob = get_success_data(api.create_talent_obligation(
            film["id"], create_talent_obligation_payload(), COORD,
        ))
        validate_success(api.confirm_talent_obligation(film["id"], ob["id"], COORD))

        # Logical clock is still at the 2026-09-01 default; window ends Dec 1.
        resp = api.fulfill_talent_obligation(film["id"], ob["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_FULFILL_TOO_EARLY)

        ob_after = get_success_data(api.get_talent_obligation(ob["id"], COORD))
        assert ob_after["status"] == "CONFIRMED"


class TestCampaignSubmitIdempotency:
    def test_campaign_submit_idempotent_when_already_submitted(self, api):
        """PRD §3.6: "Submitting a campaign transitions it `ACTIVE →
        SUBMITTED`" — a second submit on an already-SUBMITTED campaign is not
        a legal transition and is rejected with `ERR_INVALID_STATE` (HTTP 409).

        Design: Corner/state_machines/campaign_submit_idempotent_when_already_submitted
        """
        film, offer, deal, festival, slot = acquire_film_with_premiere()
        campaign = setup_active_campaign(film, deal)

        validate_success(
            api.submit_awards_campaign(film["id"], campaign["id"], STRAT2)
        )
        resp = api.submit_awards_campaign(film["id"], campaign["id"], STRAT)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        campaign_after = get_success_data(
            api.get_awards_campaign(campaign["id"], STRAT)
        )
        assert campaign_after["status"] == "SUBMITTED"
