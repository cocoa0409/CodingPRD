"""Publishing spare-parts stocking lists and re-cutting them as parts age out.

The two bases are genuinely different algorithms, the publication consumes the
asset's version token, and the obsolescence chain only ever runs forwards.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    SERVICE_MANAGER,
    ApiErrorId,
    api_client,
    create_stocking_recommendation_payload,
    publish_recommendation,
    read_machine,
    read_recommendation,
    setup_accepted_machine,
    setup_reference_data,
)

USAGE = {"annual_usage_qty": 3650, "unit_lead_time_days": 20}


def _accepted_machine():
    return setup_accepted_machine(setup_reference_data(line={}))


def test_the_service_level_basis_covers_the_review_period_and_the_larger_factor():
    """Identical usage data diverges by a wide, predictable margin: the site needs 650
    parts on the shelf under the service-level algorithm where the lead-time algorithm
    asked for 250.

    PRD: "Under the `SERVICE_LEVEL` basis the raw figure is the daily usage multiplied
    by `unit_lead_time_days` plus a 30-day review period, multiplied by a criticality
    service factor of 1.60 for class `A`, 1.30 for class `B` or 1.05 for class `C`,
    and multiplied by the obsolescence multiplier; because it covers the review period
    as well as the lead time and carries the larger factor, it returns a strictly
    larger quantity than the lead-time basis for identical inputs whenever annual
    usage is above zero."

    Design: Corner/calculations/stocking_service_level_basis_exceeds_lead_time_demand_basis
    """
    env = publish_recommendation(
        _accepted_machine(),
        part_number="SEAL-KIT-A",
        criticality="B",
        basis="LEAD_TIME_DEMAND",
        **USAGE,
    )
    lead_time_basis = env["recommendation"]
    assert lead_time_basis["recommended_qty"] == 250

    data = validate_success(
        api_client.create_stocking_recommendation(
            create_stocking_recommendation_payload(
                env["machine"]["id"],
                read_machine(env["machine"]["id"])["version"],
                part_number="SEAL-KIT-B",
                criticality="B",
                basis="SERVICE_LEVEL",
                **USAGE,
            ),
            SERVICE_MANAGER,
        ),
        201,
    )

    assert data["basis"] == "SERVICE_LEVEL"
    assert data["recommended_qty"] == 650
    assert data["obsolescence_status"] == "ACTIVE"
    assert data["status"] == "ACTIVE"
    survivor = read_recommendation(lead_time_basis["id"])
    assert survivor["recommended_qty"] == 250
    assert survivor["status"] == "ACTIVE"


def test_publishing_a_list_consumes_the_asset_version_token_it_pinned():
    """The publication is a real write on the asset, so replaying the very token the
    first list consumed is a stale view and the second list is never cut.

    PRD: "If that value does not equal the machine's current `version`, the
    publication is rejected with `ERR_STALE_MACHINE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/stocking_recommendation_create_with_stale_machine_version_returns_412
    """
    env = _accepted_machine()
    consumed_version = read_machine(env["machine"]["id"])["version"]
    env = publish_recommendation(
        env, part_number="CAM-7", criticality="A", basis="LEAD_TIME_DEMAND", **USAGE
    )

    response = api_client.create_stocking_recommendation(
        create_stocking_recommendation_payload(
            env["machine"]["id"],
            consumed_version,
            part_number="CAM-7",
            criticality="A",
            basis="SERVICE_LEVEL",
            **USAGE,
        ),
        SERVICE_MANAGER,
    )

    validate_error(response, ApiErrorId.ERR_STALE_MACHINE_VERSION.value, 412)
    assert read_recommendation(env["recommendation"]["id"])["status"] == "ACTIVE"
    _rows, meta = validate_paginated(
        api_client.list_stocking_recommendations(
            SERVICE_MANAGER, params={"installed_machine_id": env["machine"]["id"]}
        )
    )
    assert meta["total_count"] == 1


def test_only_the_live_list_for_a_part_may_carry_an_obsolescence_notice():
    """A second list for the same part retires the first, and the retired row can no
    longer be amended even though its own obsolescence status never moved.

    PRD: "The recommendation must still be `ACTIVE` in its own lifecycle, since a
    `SUPERSEDED` row can no longer be amended
    (`ERR_INVALID_RECOMMENDATION_STATE`)."

    Design: Corner/errors/obsolescence_notice_on_superseded_recommendation_returns_409_invalid_recommendation_state
    """
    env = publish_recommendation(
        _accepted_machine(),
        part_number="CAM-7",
        criticality="A",
        basis="LEAD_TIME_DEMAND",
        **USAGE,
    )
    retired = env["recommendation"]
    env = publish_recommendation(
        env, part_number="CAM-7", criticality="A", basis="SERVICE_LEVEL", **USAGE
    )

    response = api_client.obsolescence_notice_stocking_recommendation(
        retired["id"], "NOTICE_ISSUED", SERVICE_MANAGER
    )

    validate_error(response, ApiErrorId.ERR_INVALID_RECOMMENDATION_STATE.value, 409)
    stale = read_recommendation(retired["id"])
    assert stale["status"] == "SUPERSEDED"
    assert stale["obsolescence_status"] == "ACTIVE"
    assert read_recommendation(env["recommendation"]["id"])["status"] == "ACTIVE"


def test_an_obsolescence_notice_may_never_walk_back_up_the_chain():
    """Once the part is out of production the chain has run to its end, and a notice
    naming an earlier rung is refused rather than silently ignored.

    PRD: "The payload carries a `notice_type`, which must be a strictly forward move
    along the chain from `ACTIVE` to `NOTICE_ISSUED` to `LAST_TIME_BUY` to `OBSOLETE`;
    a sideways or backward notice is refused with `ERR_OBSOLESCENCE_REGRESSION`."

    Design: Corner/errors/obsolescence_notice_backwards_returns_422_obsolescence_regression
    """
    env = publish_recommendation(
        _accepted_machine(),
        part_number="CAM-7",
        criticality="A",
        basis="LEAD_TIME_DEMAND",
        **USAGE,
    )
    validate_success(
        api_client.obsolescence_notice_stocking_recommendation(
            env["recommendation"]["id"], "OBSOLETE", SERVICE_MANAGER
        )
    )

    response = api_client.obsolescence_notice_stocking_recommendation(
        env["recommendation"]["id"], "NOTICE_ISSUED", SERVICE_MANAGER
    )

    validate_error(response, ApiErrorId.ERR_OBSOLESCENCE_REGRESSION.value, 422)
    row = read_recommendation(env["recommendation"]["id"])
    assert row["obsolescence_status"] == "OBSOLETE"
    assert row["status"] == "ACTIVE"


def test_stocking_recommendation_read_with_unknown_id_reports_its_own_not_found_code():
    """The spares read reports the recommendation's own miss code.

    PRD: "Each miss reports that entity's own not-found code:
    `ERR_CUSTOMER_NOT_FOUND`, `ERR_MACHINE_MODEL_NOT_FOUND`,
    `ERR_PRODUCT_TRIAL_NOT_FOUND`, `ERR_MACHINE_ORDER_NOT_FOUND`,
    `ERR_PRODUCTION_LINE_NOT_FOUND`, `ERR_BUILD_SLOT_NOT_FOUND`,
    `ERR_COMPONENT_NOT_FOUND`, `ERR_ACCEPTANCE_TEST_NOT_FOUND`,
    `ERR_INSTALLED_MACHINE_NOT_FOUND`, `ERR_FORMAT_KIT_NOT_FOUND`,
    `ERR_SERVICE_CONTRACT_NOT_FOUND`, `ERR_FIELD_ENGINEER_NOT_FOUND`,
    `ERR_PM_VISIT_NOT_FOUND`, `ERR_WARRANTY_CLAIM_NOT_FOUND`,
    `ERR_CLAIM_LINE_NOT_FOUND`, `ERR_STOCKING_RECOMMENDATION_NOT_FOUND` — each
    with HTTP 404."

    Design: Corner/errors/stocking_recommendation_get_unknown_id_returns_404_not_found
    """
    response = api_client.get_stocking_recommendation(
        "ffffffff-ffff-4fff-8fff-ffffffffffff", SERVICE_MANAGER
    )

    validate_error(response, ApiErrorId.ERR_STOCKING_RECOMMENDATION_NOT_FOUND.value, 404)
