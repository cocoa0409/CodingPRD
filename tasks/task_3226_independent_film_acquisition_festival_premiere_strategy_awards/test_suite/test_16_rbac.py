"""Corner — RBAC: role-exclusive operations reject other roles.

Design: Corner/rbac
"""
from test_helpers import (
    TEST_USERS, acquire_film_with_premiere, create_offer_payload,
    get_success_data, setup_active_campaign, setup_film, validate_error,
)
from test_helpers.api_errors import ApiErrorId

PROG = TEST_USERS["festival_prog_headers"]
COORD = TEST_USERS["talent_coord_headers"]


class TestRoleExclusiveOperations:
    def test_festival_programmer_cannot_create_offers(self, api):
        """PRD §2.1: "A request whose role is authenticated but not permitted
        for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: `POST /films/{film_id}/offers` — "Open a new acquisition
        offer on a film" is authorized for AcquisitionExec only.

        Design: Corner/rbac/festival_programmer_cannot_create_offers
        """
        film = setup_film()
        resp = api.create_offer(film["id"], create_offer_payload(), PROG)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_talent_coordinator_cannot_submit_campaign(self, api):
        """PRD §2.1: "A request whose role is authenticated but not permitted
        for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: `POST /films/{film_id}/awards-campaigns/{campaign_id}/submit`
        — "Submit a campaign to the awards body" is authorized for
        AwardsStrategist only.

        Design: Corner/rbac/talent_coordinator_cannot_submit_campaign
        """
        film, offer, deal, festival, slot = acquire_film_with_premiere()
        campaign = setup_active_campaign(film, deal)

        resp = api.submit_awards_campaign(film["id"], campaign["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
