"""Inclusive boundaries: the 300-respondent panel, and an empty certified research set."""

from prd_bench_local_runner.testing import validate_error, validate_success
from test_helpers import api_errors as e
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers.constants import (
    NEG_NETWORK_OFFER,
    POSTURE_OPEN,
    SCREENING_CERTIFIED,
    SCREENING_FIELDED,
    SCREENING_INVALIDATED,
)
from test_helpers.fixtures import build_scenario
from test_helpers.test_users import business_affairs_headers, research_analyst_headers

WRAP_STAMP = "2026-09-26T00:00:00.000Z"


def test_a_two_hundred_and_ninety_nine_panel_fields_but_cannot_certify(api):
    """The sample-size gate lives on certification, not on fielding.

    PRD 3.6: "its `panel_size` must be at least 300 respondents, else
    `ERR_TEST_SAMPLE_TOO_SMALL`."

    Design: Difficulty/boundary_precision_check/test_certification_boundary_at_panel_size_exactly_three_hundred
    """
    ctx = build_scenario(api, "wrapped")

    screening = validate_success(
        api.field_screening(
            ctx.pilot_order_id,
            f.screening_payload(ctx.pilot_order_version, panel_size=299),
            research_analyst_headers(),
        ),
        201,
    )
    assert screening["status"] == SCREENING_FIELDED
    assert screening["panel_size"] == 299
    assert screening["certified_at"] is None
    a.assert_score(screening["weighted_raw_score"], 65.71, "weighted_raw_score")
    a.assert_score(screening["norm_adjusted_score"], 63.8, "norm_adjusted_score")

    refused = api.certify_screening(screening["id"], research_analyst_headers())
    validate_error(refused, e.ERR_TEST_SAMPLE_TOO_SMALL, 422)

    rows = validate_success(
        api.list_screenings(ctx.pilot_order_id, research_analyst_headers())
    )
    still = next(row for row in rows if row["id"] == screening["id"])
    assert still["status"] == SCREENING_FIELDED, "the refused certification changed nothing"
    assert still["certified_at"] is None


def test_a_panel_of_exactly_three_hundred_certifies(api):
    """300 is admissible because the floor is inclusive, and it invalidates the 299 panel.

    PRD 3.6: "every earlier screening on the same pilot order whose `status` is `FIELDED`
    or `CERTIFIED` is moved to `INVALIDATED` in the same request, and the pilot order's
    `version` is incremented by 1."

    Design: Difficulty/boundary_precision_check/test_certification_boundary_at_panel_size_exactly_three_hundred
    """
    ctx = build_scenario(api, "wrapped")

    small = validate_success(
        api.field_screening(
            ctx.pilot_order_id,
            f.screening_payload(ctx.pilot_order_version, panel_size=299),
            research_analyst_headers(),
        ),
        201,
    )
    pilot = validate_success(
        api.get_pilot_order(ctx.pilot_order_id, research_analyst_headers())
    )
    assert pilot["version"] == ctx.pilot_order_version + 1

    edge = validate_success(
        api.field_screening(
            ctx.pilot_order_id,
            f.screening_payload(pilot["version"], panel_size=300),
            research_analyst_headers(),
        ),
        201,
    )
    a.assert_score(edge["weighted_raw_score"], 65.71, "weighted_raw_score")
    a.assert_score(edge["norm_adjusted_score"], 63.8, "norm_adjusted_score")

    certified = validate_success(
        api.certify_screening(edge["id"], research_analyst_headers())
    )
    assert certified["status"] == SCREENING_CERTIFIED
    a.assert_instant(certified["certified_at"], WRAP_STAMP, "certified_at")

    rows = validate_success(
        api.list_screenings(ctx.pilot_order_id, research_analyst_headers())
    )
    by_id = {row["id"]: row for row in rows}
    assert by_id[small["id"]]["status"] == SCREENING_INVALIDATED
    assert by_id[edge["id"]]["status"] == SCREENING_CERTIFIED


def test_a_fielded_but_uncertified_screening_does_not_open_a_negotiation(api):
    """A 63.8 screening left FIELDED is no research of record, so the opening is refused.

    PRD 3.7: "The project must have at least one `CERTIFIED` screening on one of its
    pilot orders, else `ERR_NO_CERTIFIED_TEST`."

    Design: Difficulty/boundary_precision_check/negotiation_blocked_when_the_certified_screening_set_is_empty
    """
    ctx = build_scenario(api, "screened")

    rows = validate_success(
        api.list_screenings(ctx.pilot_order_id, research_analyst_headers())
    )
    screening = next(row for row in rows if row["id"] == ctx.screening_id)
    assert screening["status"] == SCREENING_FIELDED
    a.assert_score(screening["norm_adjusted_score"], 63.8, "norm_adjusted_score")

    refused = api.create_negotiation(
        f.negotiation_payload(ctx.project_id), business_affairs_headers()
    )
    validate_error(refused, e.ERR_NO_CERTIFIED_TEST, 422)

    slate = validate_success(api.get_slate(ctx.slate_id, business_affairs_headers()))
    a.assert_slate_episode_ledger(
        slate, committed=0, reserved=0, available=20, posture=POSTURE_OPEN
    )
    assert (
        validate_success(
            api.list_project_negotiations(ctx.project_id, business_affairs_headers())
        )
        == []
    ), "the refused opening reserved nothing and created nothing"


def test_certifying_that_same_screening_opens_the_negotiation(api):
    """Nothing about the term sheet changes; only the screening's status does.

    PRD 3.7: "The slate's `reserved_episode_count` rises by `episode_count`,
    `available_episode_count` falls by the same, `posture` is recomputed, and the slate's
    `version` is incremented by 1."

    Design: Difficulty/boundary_precision_check/negotiation_blocked_when_the_certified_screening_set_is_empty
    """
    ctx = build_scenario(api, "certified")

    rows = validate_success(
        api.list_screenings(ctx.pilot_order_id, research_analyst_headers())
    )
    screening = next(row for row in rows if row["id"] == ctx.screening_id)
    assert screening["status"] == SCREENING_CERTIFIED

    opening = validate_success(
        api.create_negotiation(
            f.negotiation_payload(ctx.project_id), business_affairs_headers()
        ),
        201,
    )
    assert opening["status"] == NEG_NETWORK_OFFER
    assert opening["round_number"] == 1
    a.assert_cents(
        opening["total_license_commitment_cents"], 300000000, "total_license_commitment_cents"
    )

    slate = validate_success(api.get_slate(ctx.slate_id, business_affairs_headers()))
    a.assert_slate_episode_ledger(
        slate, committed=0, reserved=10, available=10, posture=POSTURE_OPEN
    )
