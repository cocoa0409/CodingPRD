"""Every parameterized endpoint resolves its own path segment to its own
entity-specific 404 (PRD §2.9).
"""

from test_helpers import (
    AUDITOR,
    HEALTH,
    PLANNER,
    PLANT,
    PROCUREMENT,
    SALES,
    NON_EXISTENT_UUID,
    api_client,
    validate_error,
)
from test_helpers import ApiErrorId as ERR


def test_unknown_ids_return_entity_specific_404s(api):
    """One sweep across eleven resource families proves no two share a
    generic not-found.

    PRD §2.9: "Requests that address nested resources are validated strictly
    left to right along the path: the server resolves the first identifier,
    then the next, and rejects with the 404 belonging to the *first*
    identifier that does not resolve, without examining the rest of the path.
    Each resource family has its own not-found error: `ERR_COMPLEX_NOT_FOUND`,
    `ERR_HOUSE_NOT_FOUND`, `ERR_FLOCK_NOT_FOUND`,
    `ERR_CERTIFICATION_NOT_FOUND`, `ERR_DISEASE_EVENT_NOT_FOUND`,
    `ERR_DEPOPULATION_ORDER_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`,
    `ERR_COMMITMENT_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`,
    `ERR_SETTLEMENT_NOT_FOUND`, `ERR_FEED_CONTRACT_NOT_FOUND`,
    `ERR_PACKING_RUN_NOT_FOUND`, and `ERR_CAPITAL_PROJECT_NOT_FOUND`."

    Design: Corner/errors/unknown_ids_return_entity_specific_404s
    """
    u = NON_EXISTENT_UUID
    cases = [
        (api.get_house(u, PLANNER), ERR.ERR_HOUSE_NOT_FOUND),
        (api.get_customer(u, SALES), ERR.ERR_CUSTOMER_NOT_FOUND),
        (api.get_commitment(u, SALES), ERR.ERR_COMMITMENT_NOT_FOUND),
        (api.get_order(u, PLANNER), ERR.ERR_ORDER_NOT_FOUND),
        (api.finalize_settlement(u, SALES), ERR.ERR_SETTLEMENT_NOT_FOUND),
        (
            api.receive_feed_contract(u, {"tons": 1, "spot_cents_per_ton": 100},
                                      PROCUREMENT),
            ERR.ERR_FEED_CONTRACT_NOT_FOUND,
        ),
        (api.verify_packing_run(u, PLANT), ERR.ERR_PACKING_RUN_NOT_FOUND),
        (
            api.approve_capital_project(u, PLANNER),
            ERR.ERR_CAPITAL_PROJECT_NOT_FOUND,
        ),
        (
            api.record_certification_result(u, {"result": "PASSED"}, AUDITOR),
            ERR.ERR_CERTIFICATION_NOT_FOUND,
        ),
        (api.get_disease_event(u, HEALTH), ERR.ERR_DISEASE_EVENT_NOT_FOUND),
        (
            api.complete_depopulation_order(u, HEALTH),
            ERR.ERR_DEPOPULATION_ORDER_NOT_FOUND,
        ),
    ]
    for response, expected in cases:
        validate_error(response, expected)
