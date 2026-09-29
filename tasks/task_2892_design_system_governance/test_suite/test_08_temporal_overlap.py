"""
Two interval-exclusivity rules that disagree about their own endpoints.

Deprecation windows are half-open and therefore tolerate an exact touch, while
adoption windows are closed and therefore do not. Both rules are scoped, and the
scoping is as much the subject here as the arithmetic of the overlap test.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers.api_errors import ERR_SCAN_WINDOW_OVERLAP
from test_helpers.assertions import (
    assert_append_only_row,
    assert_decimal_equals,
    assert_fields,
    assert_page_meta,
)
from test_helpers.constants import (
    DASHBOARD_VIEW_LATEST,
    DASHBOARD_VIEW_TRAILING,
    GUIDE_MISSING,
    LIFECYCLE_ACTIVE,
    PLAN_DRAFT,
    SCAN_KIND_CODE_SCAN,
    SCAN_KIND_DESIGN_LINT,
)
from test_helpers.factories import adoption_scan_payload, deprecation_plan_payload
from test_helpers.fixtures import (
    governance_base,
    make_plan,
    make_team,
    pin_clock,
    read_component,
    read_team,
)
from test_helpers.test_users import make_design_system_lead_headers, make_system_admin_headers

FIRST_PLAN = ("2026-08-01T00:00:00.000Z", "2026-08-20T00:00:00.000Z", "2026-09-25T00:00:00.000Z")
TOUCHING_PLAN = ("2026-09-25T00:00:00.000Z", "2026-10-20T00:00:00.000Z", "2026-11-25T00:00:00.000Z")
JUNE_WINDOW = ("2026-06-01T00:00:00.000Z", "2026-06-30T00:00:00.000Z")


def _component_with_a_drafted_plan(api):
    """An experimental component holding one drafted deprecation window."""
    base = governance_base(
        api,
        team_name="Navigation Team",
        team_slug="navigation-team",
        component_name="Legacy Tabs",
        component_slug="legacy-tabs",
    )
    first = make_plan(api, base["component_id"], *FIRST_PLAN)
    assert_fields(
        first,
        {"state": PLAN_DRAFT, "required_notice_days": 14, "actual_notice_days": 19},
        "first plan",
    )
    base["first_plan_id"] = first["id"]
    return base


def test_a_plan_announced_exactly_at_an_existing_removal_instant_is_admitted(api):
    """The window excludes its own end, so touching plans do not collide.

    PRD: "Because the interval excludes its own end, touching windows do not collide: a new `announced_at` exactly equal to an existing `removal_at` is permitted."

    Design: Difficulty/resource_temporal_overlap/deprecation_windows_touching_at_removal_instant_are_admitted
    """
    scenario = _component_with_a_drafted_plan(api)

    second = validate_success(
        api.create_deprecation_plan(
            scenario["component_id"],
            deprecation_plan_payload(*TOUCHING_PLAN),
            make_design_system_lead_headers(),
        ),
        201,
    )
    assert_fields(
        second,
        {
            "state": PLAN_DRAFT,
            "required_notice_days": 14,
            "actual_notice_days": 25,
            "blocked_dependent_count": 0,
            "rescinded_at": None,
            "migration_guide_state": GUIDE_MISSING,
        },
        "second plan",
    )
    assert second["id"] != scenario["first_plan_id"]


def test_both_touching_plans_are_listed_under_the_untouched_component(api):
    """Drafting a second window changes nothing about the component itself.

    PRD: "The plan takes its `component_id` from the request path, is created with a 201 response in `state` `DRAFT` with `blocked_dependent_count` at 0 and `rescinded_at` null, and its `migration_guide_state` starts at `DRAFT` when a `migration_guide_url` was supplied and at `MISSING` otherwise."

    Design: Difficulty/resource_temporal_overlap/deprecation_windows_touching_at_removal_instant_are_admitted
    """
    scenario = _component_with_a_drafted_plan(api)

    make_plan(api, scenario["component_id"], *TOUCHING_PLAN)

    rows, meta = validate_paginated(
        api.list_deprecation_plans(
            scenario["component_id"], make_design_system_lead_headers()
        )
    )
    assert_page_meta(meta, total_count=2, has_more=False)
    assert scenario["first_plan_id"] in [row["id"] for row in rows]
    assert read_component(api, scenario["component_id"])["lifecycle_state"] == LIFECYCLE_ACTIVE


def _team_with_one_june_code_scan(api):
    """
    A team carrying a single code scan over the whole of June.

    Ninety of its hundred observed instances resolved to the design system, so the
    scan's ratio is 90.00 and the blended index reads 63.00 with the design-lint
    channel still empty.
    """
    pin_clock(api)
    team = make_team(api, name="Metrics Team", slug="metrics-team")
    scan = validate_success(
        api.create_adoption_scan(
            team["id"],
            adoption_scan_payload(
                *JUNE_WINDOW,
                system_instance_count=90,
                legacy_instance_count=10,
                one_off_instance_count=0,
                scan_kind=SCAN_KIND_CODE_SCAN,
            ),
            make_system_admin_headers(),
        ),
        201,
    )
    assert_append_only_row(scan, "adoption scan")
    assert_decimal_equals(scan["adoption_ratio"], 90.00, 2, "adoption_ratio")
    return {"team_id": team["id"], "scan_id": scan["id"]}


def test_a_scan_starting_on_an_existing_window_end_collides_within_its_channel(api):
    """The adoption window is closed at both ends, so an exact touch collides.

    PRD: "A new scan collides with any existing scan of the same `team_id` and the same `scan_kind` whose closed window shares even a single instant with the new one, and because both endpoints of the interval are inclusive, exact adjacency is a collision too: a new `window_start_at` equal to an existing `window_end_at` is refused with `ERR_SCAN_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/adoption_scans_sharing_one_endpoint_instant_collide_for_the_same_kind
    """
    scenario = _team_with_one_june_code_scan(api)

    validate_error(
        api.create_adoption_scan(
            scenario["team_id"],
            adoption_scan_payload(
                "2026-06-30T00:00:00.000Z",
                "2026-07-31T00:00:00.000Z",
                system_instance_count=95,
                legacy_instance_count=5,
                scan_kind=SCAN_KIND_CODE_SCAN,
            ),
            make_system_admin_headers(),
        ),
        ERR_SCAN_WINDOW_OVERLAP,
        409,
    )


def test_the_collided_scan_is_not_filed_and_the_index_does_not_move(api):
    """A refused measurement leaves the channel with exactly one row.

    PRD: "The **latest-scan** view takes, for each of the two channels, the `adoption_ratio` of the single most recent scan in that channel's recency order, treating a channel with no scans at all as 0.00."

    Design: Difficulty/resource_temporal_overlap/adoption_scans_sharing_one_endpoint_instant_collide_for_the_same_kind
    """
    scenario = _team_with_one_june_code_scan(api)

    validate_error(
        api.create_adoption_scan(
            scenario["team_id"],
            adoption_scan_payload(
                "2026-06-30T00:00:00.000Z",
                "2026-07-31T00:00:00.000Z",
                scan_kind=SCAN_KIND_CODE_SCAN,
            ),
            make_system_admin_headers(),
        ),
        ERR_SCAN_WINDOW_OVERLAP,
    )

    rows, meta = validate_paginated(
        api.list_adoption_scans(scenario["team_id"], make_system_admin_headers())
    )
    assert_page_meta(meta, total_count=1, has_more=False)
    assert [row["id"] for row in rows] == [scenario["scan_id"]]

    team = read_team(api, scenario["team_id"])
    assert_decimal_equals(team["adoption_index_latest"], 63.00, 2, "adoption_index_latest")


def _team_with_overlapping_windows_on_two_channels(api):
    """
    The same team's design-lint window deliberately straddles its code-scan one.

    The lint scan runs from mid-June into July, which overlaps the June code scan
    on fifteen days; the two channels are nonetheless independent.
    """
    scenario = _team_with_one_june_code_scan(api)
    lint = validate_success(
        api.create_adoption_scan(
            scenario["team_id"],
            adoption_scan_payload(
                "2026-06-15T00:00:00.000Z",
                "2026-07-31T00:00:00.000Z",
                system_instance_count=60,
                legacy_instance_count=40,
                one_off_instance_count=0,
                scan_kind=SCAN_KIND_DESIGN_LINT,
            ),
            make_system_admin_headers(),
        ),
        201,
    )
    scenario["lint"] = lint
    return scenario


def test_windows_on_different_channels_may_overlap_freely(api):
    """The collision domain is the team and the channel together.

    PRD: "Different channels never collide with each other."

    Design: Difficulty/resource_temporal_overlap/adoption_scan_overlap_is_scoped_per_scan_kind_not_per_team
    """
    scenario = _team_with_overlapping_windows_on_two_channels(api)

    lint = scenario["lint"]
    assert_append_only_row(lint, "design lint scan")
    assert lint["scan_kind"] == SCAN_KIND_DESIGN_LINT
    assert_decimal_equals(lint["adoption_ratio"], 60.00, 2, "adoption_ratio")

    _rows, meta = validate_paginated(
        api.list_adoption_scans(scenario["team_id"], make_system_admin_headers())
    )
    assert_page_meta(meta, total_count=2, has_more=False)


def test_the_admitted_cross_channel_scan_blends_into_both_index_views(api):
    """Both channels now carry one row, so the two views agree at 81.00.

    PRD: "A team's adoption index is a weighted blend of its two channels, in which `CODE_SCAN` carries a weight of 0.70 and `DESIGN_LINT` a weight of 0.30."

    Ninety at 0.70 plus sixty at 0.30 is 81.00 under either variant, because each
    channel has a single row for the trailing average to take.

    Design: Difficulty/resource_temporal_overlap/adoption_scan_overlap_is_scoped_per_scan_kind_not_per_team
    """
    scenario = _team_with_overlapping_windows_on_two_channels(api)

    team = read_team(api, scenario["team_id"])
    assert_decimal_equals(team["adoption_index_latest"], 81.00, 2, "adoption_index_latest")
    assert_decimal_equals(
        team["adoption_index_trailing"], 81.00, 2, "adoption_index_trailing"
    )

    latest = validate_success(
        api.get_team_dashboard(
            scenario["team_id"],
            make_system_admin_headers(),
            {"view": DASHBOARD_VIEW_LATEST},
        )
    )
    assert_fields(
        latest,
        {
            "view": DASHBOARD_VIEW_LATEST,
            "adoption_index": 81.00,
            "code_scan_ratio": 90.00,
            "design_lint_ratio": 60.00,
            "scanned_kind_count": 2,
        },
        "dashboard",
    )
    trailing = validate_success(
        api.get_team_dashboard(
            scenario["team_id"],
            make_system_admin_headers(),
            {"view": DASHBOARD_VIEW_TRAILING},
        )
    )
    assert_fields(
        trailing,
        {"view": DASHBOARD_VIEW_TRAILING, "adoption_index": 81.00},
        "dashboard",
    )
