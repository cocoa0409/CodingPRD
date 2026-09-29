"""Grant activation: the non-overlap rule over closed calendar-date periods."""

from test_helpers import get_success_data, validate_error
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import DeviceType, GrantStatus
from test_helpers.fixtures import (
    activate_grant,
    create_grant,
    create_partner,
    pin_clock,
    read_grant,
)
from test_helpers.test_users import OFFICER

FIRST_HALF = {"period_start_date": "2026-01-01", "period_end_date": "2026-06-30"}
TOUCHING = {"period_start_date": "2026-06-30", "period_end_date": "2026-12-31"}
NEXT_HALF = {"period_start_date": "2026-07-01", "period_end_date": "2026-12-31"}
SMOKE_ONLY = {
    "allowed_device_types": [DeviceType.SMOKE_10YR],
    "unit_rate_cents_by_type": {DeviceType.SMOKE_10YR: 2195},
}


def _partner_with_three_awards(api):
    pin_clock(api)
    partner = create_partner(api)
    incumbent = create_grant(api, partner["id"], grant_code="G-H1", **FIRST_HALF, **SMOKE_ONLY)
    activate_grant(api, incumbent["id"])
    touching = create_grant(api, partner["id"], grant_code="G-TOUCH", **TOUCHING, **SMOKE_ONLY)
    following = create_grant(api, partner["id"], grant_code="G-NEXT", **NEXT_HALF, **SMOKE_ONLY)
    return {"incumbent": incumbent, "touching": touching, "following": following}


def test_01_a_period_starting_on_the_incumbent_s_end_date_overlaps(api):
    """The single shared day of 2026-06-30 is enough to refuse activation.

    PRD: "...it enforces a **non-overlap rule**: no other grant of the same partner
    sitting in `ACTIVE` or `CLOSED` may share a device family with this grant over an
    overlapping closed date period, where each period runs inclusively from its
    `period_start_date` to its `period_end_date`."

    Design: Difficulty/resource_temporal_overlap/grant_periods_are_closed_intervals_so_a_shared_end_date_overlaps
    """
    ctx = _partner_with_three_awards(api)

    response = api.activate_grant(ctx["touching"]["id"], OFFICER)
    validate_error(response, ApiErrorId.GRANT_PERIOD_OVERLAP, 409)

    assert read_grant(api, ctx["touching"]["id"])["status"] == GrantStatus.DRAFT
    assert read_grant(api, ctx["incumbent"]["id"])["status"] == GrantStatus.ACTIVE


def test_02_a_period_starting_the_next_day_activates(api):
    """Starting on 2026-07-01 shares no day with the incumbent award.

    PRD: "A collision is rejected with `ERR_GRANT_PERIOD_OVERLAP`, which prevents the
    same device from being billable to two awards on the same day."

    Design: Difficulty/resource_temporal_overlap/grant_periods_are_closed_intervals_so_a_shared_end_date_overlaps
    """
    ctx = _partner_with_three_awards(api)
    validate_error(
        api.activate_grant(ctx["touching"]["id"], OFFICER),
        ApiErrorId.GRANT_PERIOD_OVERLAP,
        409,
    )

    activated = get_success_data(api.activate_grant(ctx["following"]["id"], OFFICER))
    assert activated["status"] == GrantStatus.ACTIVE
    assert activated["available_cents"] == 500000
    assert read_grant(api, ctx["incumbent"]["id"])["status"] == GrantStatus.ACTIVE
