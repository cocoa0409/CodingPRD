"""Corner — validations: auth, authorization, rights-window scope.

Design: Corner/validations
"""
from test_helpers import (
    NON_EXISTENT_UUID, TEST_USERS, acquire_film, create_offer_payload,
    create_territory_payload, get_success_data, setup_film, setup_territory,
    validate_error, validate_paginated,
)
from test_helpers.api_errors import ApiErrorId

ACQ = TEST_USERS["acq_exec_headers"]
ACQ2 = TEST_USERS["acq_exec_2_headers"]


class TestAuthentication:
    def test_missing_x_user_role_returns_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, or carrying a role
        outside the declared set, is rejected with `ERR_UNAUTHENTICATED`
        (HTTP 401)."

        Design: Corner/validations/missing_x_user_role_returns_unauthenticated
        """
        resp = api.get_film(NON_EXISTENT_UUID, headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestAuthorization:
    def test_acquisition_exec_cannot_create_territory(self, api):
        """PRD §2.1: "A request whose role is authenticated but not permitted
        for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: `POST /territories` — "Create a distribution territory" is
        authorized for PlatformAdmin only.

        Design: Corner/validations/acquisition_exec_cannot_create_territory
        """
        resp = api.create_territory(create_territory_payload(), ACQ)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestHomeEntWindowScope:
    def test_home_ent_window_on_ineligible_territory_rejected(self, api):
        """PRD §3.3: "A `HOME_ENT` grant may only be created on a territory
        whose `is_home_ent_eligible` is true; asking for `HOME_ENT` on an
        ineligible territory rejects the entire accept with
        `ERR_WINDOW_NOT_AVAILABLE` (HTTP 422)."

        Design: Corner/validations/home_ent_window_on_ineligible_territory_rejected
        """
        setup_territory(code="JP", name="Japan", is_home_ent_eligible=False)
        film = setup_film()
        offer = get_success_data(api.create_offer(
            film["id"],
            create_offer_payload(
                requested_territory_codes=["JP"],
                requested_windows=["HOME_ENT"],
            ),
            ACQ2,
        ))
        film_now = get_success_data(api.get_film(film["id"], ACQ))
        resp = api.accept_offer(
            film["id"], offer["id"],
            {"expected_film_version": film_now["version"]}, ACQ,
        )
        validate_error(resp, ApiErrorId.ERR_WINDOW_NOT_AVAILABLE)

        # The entire accept is rejected — no deal was created
        deals, meta = validate_paginated(api.list_film_deals(film["id"], ACQ))
        assert len(deals) == 0
        assert meta["total_count"] == 0
