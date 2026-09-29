"""Ten aggregates, ten not-found identifiers.

The same unknown identifier is offered to every aggregate in the system, and
each one is required to answer with the identifier belonging to its own
resource type rather than a shared generic refusal.
"""

from typing import Any, Callable, Dict, List, Tuple

from prd_bench_local_runner.testing import NON_EXISTENT_UUID, validate_error

from test_helpers.api_client import ApiClient
from test_helpers.api_errors import (
    ERR_BRAND_NOT_FOUND,
    ERR_DISCLOSURE_PACKET_NOT_FOUND,
    ERR_ENFORCEMENT_ACTION_NOT_FOUND,
    ERR_ESTABLISHMENT_NOT_FOUND,
    ERR_JURISDICTION_NOT_FOUND,
    ERR_MENU_BOARD_NOT_FOUND,
    ERR_MENU_ITEM_NOT_FOUND,
    ERR_NUTRITION_ANALYSIS_NOT_FOUND,
    ERR_RECIPE_NOT_FOUND,
    ERR_VARIANCE_REQUEST_NOT_FOUND,
)
from test_helpers.constants import (
    BOARD_PRIMARY_MENU_BOARD,
    STATEMENT_FEDERAL_DEFAULT,
)
from test_helpers.factories import menu_board_payload
from test_helpers.fixtures import set_clock
from test_helpers.test_users import PLATFORM_ADMIN, make_publisher_headers


def _unknown_id_reads(api: ApiClient) -> List[Tuple[str, Callable[[], Any]]]:
    """One single-resource read per aggregate, each naming no row."""
    return [
        (ERR_BRAND_NOT_FOUND, lambda: api.get_brand(NON_EXISTENT_UUID, PLATFORM_ADMIN)),
        (
            ERR_JURISDICTION_NOT_FOUND,
            lambda: api.get_jurisdiction(NON_EXISTENT_UUID, PLATFORM_ADMIN),
        ),
        (
            ERR_ESTABLISHMENT_NOT_FOUND,
            lambda: api.get_establishment(NON_EXISTENT_UUID, PLATFORM_ADMIN),
        ),
        (
            ERR_MENU_ITEM_NOT_FOUND,
            lambda: api.get_menu_item(NON_EXISTENT_UUID, PLATFORM_ADMIN),
        ),
        (
            ERR_RECIPE_NOT_FOUND,
            lambda: api.get_recipe(NON_EXISTENT_UUID, PLATFORM_ADMIN),
        ),
        (
            ERR_NUTRITION_ANALYSIS_NOT_FOUND,
            lambda: api.get_nutrition_analysis(NON_EXISTENT_UUID, PLATFORM_ADMIN),
        ),
        (
            ERR_MENU_BOARD_NOT_FOUND,
            lambda: api.get_menu_board(NON_EXISTENT_UUID, PLATFORM_ADMIN),
        ),
        (
            ERR_DISCLOSURE_PACKET_NOT_FOUND,
            lambda: api.get_disclosure_packet(NON_EXISTENT_UUID, PLATFORM_ADMIN),
        ),
        (
            ERR_VARIANCE_REQUEST_NOT_FOUND,
            lambda: api.get_variance_request(NON_EXISTENT_UUID, PLATFORM_ADMIN),
        ),
        (
            ERR_ENFORCEMENT_ACTION_NOT_FOUND,
            lambda: api.get_enforcement_action(NON_EXISTENT_UUID, PLATFORM_ADMIN),
        ),
    ]


def test_each_aggregate_answers_an_unknown_path_id_with_its_own_not_found(api):
    """Ten reads, ten distinct identifiers, all at HTTP 404.

    PRD 2.5: "Every templated segment must name an existing row, and the
    not-found error reported is the one belonging to the resource type of the
    *leftmost* unresolved segment: `ERR_BRAND_NOT_FOUND`,
    `ERR_JURISDICTION_NOT_FOUND`, `ERR_ESTABLISHMENT_NOT_FOUND`,
    `ERR_MENU_ITEM_NOT_FOUND`, `ERR_RECIPE_NOT_FOUND`,
    `ERR_NUTRITION_ANALYSIS_NOT_FOUND`, `ERR_MENU_BOARD_NOT_FOUND`,
    `ERR_DISCLOSURE_PACKET_NOT_FOUND`, `ERR_VARIANCE_REQUEST_NOT_FOUND` or
    `ERR_ENFORCEMENT_ACTION_NOT_FOUND`, each with HTTP 404." PRD 2.6 rung 7
    states when that resolution happens: "Every templated path identifier
    resolves to an existing row, else that resource type's not-found error."

    Design: Corner/errors/unknown_ids_on_every_aggregate_return_their_own_not_found_error
    """
    set_clock(api)

    seen: List[str] = []
    for expected_error_id, call in _unknown_id_reads(api):
        body = validate_error(call(), expected_error_id, 404)
        assert body["error_id"] == expected_error_id
        assert body["message"].strip(), "every refusal must carry a message"
        seen.append(body["error_id"])

    assert len(set(seen)) == len(seen), (
        f"the ten aggregates must not share a not-found identifier: {seen}"
    )
    assert len(seen) == 10


def test_a_board_creation_naming_no_unit_reports_the_units_own_not_found(api):
    """A body foreign key answers with the referenced entity's identifier.

    PRD 2.6 rung 8: "Every foreign key supplied in the request body resolves to
    an existing row, else the referenced entity's not-found error. Applies to
    unit registration, unit batch registration, menu-item creation, board
    creation, listing creation, variance filing and citation opening." PRD 2.5
    fixes which identifier that is: "Foreign keys carried in a request body are
    resolved only after the path has fully resolved, and they report the
    not-found error of the entity they reference."

    Design: Corner/errors/unknown_ids_on_every_aggregate_return_their_own_not_found_error
    """
    set_clock(api)

    body: Dict[str, Any] = validate_error(
        api.create_menu_board(
            menu_board_payload(
                establishment_id=NON_EXISTENT_UUID,
                board_type=BOARD_PRIMARY_MENU_BOARD,
                succinct_statement_variant=STATEMENT_FEDERAL_DEFAULT,
            ),
            make_publisher_headers(NON_EXISTENT_UUID),
        ),
        ERR_ESTABLISHMENT_NOT_FOUND,
        404,
    )

    assert body["error_id"] == ERR_ESTABLISHMENT_NOT_FOUND
    assert body["message"].strip()
