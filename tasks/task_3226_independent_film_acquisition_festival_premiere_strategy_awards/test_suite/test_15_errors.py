"""Corner — errors: stale-version OCC and segregation of duties.

Design: Corner/errors
"""
from test_helpers import (
    TEST_USERS, build_user_headers, create_offer_payload, get_success_data,
    setup_film_with_offer, validate_error, validate_success,
)
from test_helpers.api_errors import ApiErrorId

ACQ = TEST_USERS["acq_exec_headers"]
ACQ2 = TEST_USERS["acq_exec_2_headers"]


class TestStaleFilmVersionOnAccept:
    def test_stale_film_version_on_offer_accept_returns_412(self, api):
        """PRD §2.8: "Accepting an acquisition offer requires the request body
        to carry `expected_film_version` equal to the Film's current
        `version`; a mismatch rejects the request with `ERR_STALE_VERSION`
        (HTTP 412)."

        Design: Corner/errors/stale_film_version_on_offer_accept_returns_412
        """
        film, o1 = setup_film_with_offer()
        film_id = film["id"]
        film_v1 = film["version"]  # 1 at creation

        # Counter bumps Film.version, so the creation-time version is stale
        o2 = validate_success(api.counter_offer(
            film_id, o1["id"], create_offer_payload(), ACQ2,
        ), expected_status=201)

        resp = api.accept_offer(
            film_id, o2["id"], {"expected_film_version": film_v1}, ACQ,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        o2_after = get_success_data(api.get_offer(film_id, o2["id"], ACQ))
        assert o2_after["status"] == "OPEN"


class TestDutySeparationOnAccept:
    def test_duty_separation_offer_creator_cannot_accept(self, api):
        """PRD §2.10: "An `AcquisitionExec` cannot accept an offer that they
        themselves created — the `X-User-ID` that opened the offer must differ
        from the `X-User-ID` that accepts it... Either violation is rejected
        with `ERR_DUTY_SEPARATION_VIOLATION` (HTTP 403)."

        Design: Corner/errors/duty_separation_offer_creator_cannot_accept
        """
        exec_1 = build_user_headers("exec-1", "AcquisitionExec")
        film, o1 = setup_film_with_offer(offer_headers=exec_1)
        film_id = film["id"]

        film_now = get_success_data(api.get_film(film_id, exec_1))
        resp = api.accept_offer(
            film_id, o1["id"],
            {"expected_film_version": film_now["version"]}, exec_1,
        )
        validate_error(resp, ApiErrorId.ERR_DUTY_SEPARATION_VIOLATION)

        o1_after = get_success_data(api.get_offer(film_id, o1["id"], ACQ))
        assert o1_after["status"] == "OPEN"
