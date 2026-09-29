"""The shape of a refusal: entity-specific 404s, minimal bodies, page bounds.

Every retrieval endpoint answers with its own not-found identifier rather than a
single shared code, every error body publishes exactly two fields, and the page
window is an inclusive range whose upper edge is admissible.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
)

from test_helpers.api_errors import (
    ERR_AWARD_NOT_FOUND,
    ERR_CHALLENGE_NOT_FOUND,
    ERR_CONTRACT_NOT_FOUND,
    ERR_INVALID_PAGINATION,
    ERR_LOG_ENTRY_NOT_FOUND,
    ERR_LOT_NOT_FOUND,
    ERR_PARTICIPANT_NOT_FOUND,
    ERR_PRESENTER_NOT_FOUND,
    ERR_PROGRAM_NOT_FOUND,
    ERR_RESERVATION_NOT_FOUND,
    ERR_ROOM_NOT_FOUND,
    ERROR_HTTP_STATUS,
)
from test_helpers.assertions import assert_error_payload_is_minimal
from test_helpers.factories import log_correction_payload, reservation_payload
from test_helpers.fixtures import LibraryWorld


class TestEntitySpecificNotFound:
    """Ten retrieval endpoints, ten distinct identifiers, one envelope shape."""

    def test_each_retrieval_endpoint_names_its_own_missing_entity(
        self, world: LibraryWorld
    ) -> None:
        """No shared generic code stands in for the entity that was asked for.

        "Identifiers named in the request **path** are resolved first, strictly
        left to right, and the response reports the leftmost segment that names
        nothing." and "The path identifiers in play across the API resolve to these
        HTTP 404 codes".

        Design: Corner/errors/unknown_path_ids_return_the_entity_specific_not_found_error
        """
        headers = world.coordinator
        expectations = [
            (world.api.get_room(NON_EXISTENT_UUID, headers), ERR_ROOM_NOT_FOUND),
            (
                world.api.get_program(NON_EXISTENT_UUID, headers),
                ERR_PROGRAM_NOT_FOUND,
            ),
            (
                world.api.get_reservation(NON_EXISTENT_UUID, headers),
                ERR_RESERVATION_NOT_FOUND,
            ),
            (
                world.api.get_presenter(NON_EXISTENT_UUID, headers),
                ERR_PRESENTER_NOT_FOUND,
            ),
            (
                world.api.get_contract(NON_EXISTENT_UUID, headers),
                ERR_CONTRACT_NOT_FOUND,
            ),
            (
                world.api.get_challenge(NON_EXISTENT_UUID, headers),
                ERR_CHALLENGE_NOT_FOUND,
            ),
            (
                world.api.get_participant(NON_EXISTENT_UUID, headers),
                ERR_PARTICIPANT_NOT_FOUND,
            ),
            (
                world.api.get_log_entry(NON_EXISTENT_UUID, headers),
                ERR_LOG_ENTRY_NOT_FOUND,
            ),
            (
                world.api.get_inventory_lot(NON_EXISTENT_UUID, headers),
                ERR_LOT_NOT_FOUND,
            ),
            (
                world.api.get_tier_award(NON_EXISTENT_UUID, headers),
                ERR_AWARD_NOT_FOUND,
            ),
        ]

        for response, expected_error_id in expectations:
            assert response.status_code == 404, (
                f"expected 404 for {expected_error_id}, got {response.status_code}"
            )
            validate_error(response, expected_error_id, 404)
            assert_error_payload_is_minimal(response)


class TestPaginationBounds:
    """A limit of one hundred is admissible; zero, one hundred one and minus one are not."""

    def test_the_page_window_is_an_inclusive_one_to_one_hundred(
        self, world: LibraryWorld
    ) -> None:
        """Three bad windows are refused and the upper edge still succeeds.

        "A `limit` outside the permitted range, a negative `offset`, or a
        non-integer value for either is rejected with `ERR_INVALID_PAGINATION` and
        HTTP 400."

        Design: Corner/errors/pagination_outside_the_declared_bounds_returns_400
        """
        branch = world.branch()
        room = world.room(branch["id"])

        for limit, offset in ((0, None), (101, None), (None, -1)):
            response = world.api.list_rooms(
                world.coordinator, limit=limit, offset=offset
            )
            validate_error(
                response,
                ERR_INVALID_PAGINATION,
                ERROR_HTTP_STATUS[ERR_INVALID_PAGINATION],
            )
            assert_error_payload_is_minimal(response)

        rows, meta = validate_paginated(
            world.api.list_rooms(world.coordinator, limit=100, offset=0)
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == room["id"]


class TestBodyForeignKeyResolution:
    """A body reference is resolved once the path id has resolved, and answers 404."""

    def test_a_fabricated_body_reference_answers_not_found_rather_than_unprocessable(
        self, world: LibraryWorld
    ) -> None:
        """Neither rejected call spends the entity's version.

        "Only once every path identifier has resolved does the server resolve
        foreign keys supplied in the request **body**, and it resolves them in the
        order the fields are declared on the owning resource." and "`room_id` to
        `ERR_ROOM_NOT_FOUND`" and "`corrected_entry_id` to
        `ERR_LOG_ENTRY_NOT_FOUND`".

        Design: Corner/errors/unknown_body_foreign_keys_return_404_after_the_path_id_resolves
        """
        branch = world.branch()
        program = world.program(branch["id"])
        opened = world.opened_challenge()
        participant = world.participant(
            opened["challenge"]["id"],
            branch["id"],
            display_name="Ada L.",
            age_band="AGE_5_11",
        )
        program_version = world.program_version(program["id"])
        participant_version = world.participant_version(participant["id"])

        room_response = world.api.create_reservation(
            program["id"],
            reservation_payload(NON_EXISTENT_UUID, program_version),
            world.coordinator,
        )
        validate_error(room_response, ERR_ROOM_NOT_FOUND, 404)
        assert_error_payload_is_minimal(room_response)

        entry_response = world.api.create_log_correction(
            participant["id"],
            log_correction_payload(NON_EXISTENT_UUID, -5, participant_version),
            world.coordinator,
        )
        validate_error(entry_response, ERR_LOG_ENTRY_NOT_FOUND, 404)
        assert_error_payload_is_minimal(entry_response)

        assert world.program_version(program["id"]) == program_version
        assert world.participant_version(participant["id"]) == participant_version
