"""Two exclusive resources with opposite endpoint conventions, and one released slot.

Placement windows are closed, so touching endpoints collide; reformulation
windows are half-open, so touching endpoints do not. A flagged placement stops
reserving its window at all.
"""

import pytest

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_PLACEMENT_OVERLAP,
    ERR_REFORMULATION_OVERLAP,
)
from test_helpers.assertions import assert_posture, assert_status
from test_helpers.constants import (
    DEFAULT_CLOCK,
    PLACEMENT_NON_COMPLIANT,
    PLACEMENT_PLANNED,
    PLACEMENT_VERIFIED,
    POSTURE_WARNING_REQUIRED,
    PROJECT_ABANDONED,
    PROJECT_PLANNED,
    REQUIRED_CHANNEL_LABEL,
    ROUTE_DERMAL,
)
from test_helpers.fixtures import (
    build_warned_product,
    make_bpa,
    make_product_with_component,
    make_reformulation_project,
    read_product,
    set_clock,
    verify_placement,
)
from test_helpers.test_users import (
    COMPLIANCE_ANALYST,
    LABELING_SPECIALIST,
    REGULATORY_COUNSEL,
)


# ─────────────────────────────────────────────────────────────────────────────
# Setups
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def label_slot_with_closed_window(api):
    """An APPROVED determination whose one IMPLEMENTED LABEL placement spans [06-01, 07-01]."""
    set_clock(api, DEFAULT_CLOCK)
    chemical = make_bpa(api)
    bundle = build_warned_product(
        api,
        chemical["id"],
        sku="SKU-RT1",
        route=ROUTE_DERMAL,
        effective_from="2026-06-01T00:00:00Z",
        effective_to="2026-07-01T00:00:00Z",
        product_overrides={"product_name": "Watering Can", "annual_units": 50000},
    )
    bundle["chemical"] = chemical
    return bundle


@pytest.fixture
def reformulation_slot_with_half_open_window(api):
    """A PLANNED project holding [2026-06-01, 2026-07-01) on one product and chemical."""
    set_clock(api, DEFAULT_CLOCK)
    chemical = make_bpa(api)
    base = make_product_with_component(
        api,
        chemical["id"],
        sku="SKU-RT2",
        product_overrides={"product_name": "Deck Chair", "annual_units": 50000},
    )
    project = make_reformulation_project(
        api,
        base["product"]["id"],
        chemical["id"],
        base["link"]["id"],
        30.0,
        planned_start_date="2026-06-01T00:00:00Z",
        planned_end_date="2026-07-01T00:00:00Z",
    )
    base["chemical"] = chemical
    base["project"] = project
    return base


@pytest.fixture
def verified_label_placement(api):
    """The same LABEL slot, but its occupant has been driven all the way to VERIFIED."""
    set_clock(api, DEFAULT_CLOCK)
    chemical = make_bpa(api)
    bundle = build_warned_product(
        api,
        chemical["id"],
        sku="SKU-RT3",
        route=ROUTE_DERMAL,
        effective_from="2026-06-01T00:00:00Z",
        effective_to="2026-07-01T00:00:00Z",
        product_overrides={"product_name": "Step Stool", "annual_units": 50000},
    )
    bundle["chemical"] = chemical
    bundle["placement"] = verify_placement(api, bundle["placement"]["id"])
    return bundle


def _create_placement(api, determination_id, effective_from, effective_to, detail):
    return api.create_placement(
        determination_id,
        f.placement_payload(
            REQUIRED_CHANNEL_LABEL,
            effective_from,
            effective_to,
            placement_detail=detail,
        ),
        LABELING_SPECIALIST,
    )


def _create_project(api, bundle, target, start, end):
    return api.create_reformulation_project(
        f.reformulation_payload(
            bundle["product"]["id"],
            bundle["chemical"]["id"],
            bundle["link"]["id"],
            target,
            start,
            end,
        ),
        COMPLIANCE_ANALYST,
    )


def _placements_of(api, determination_id):
    rows, _ = validate_paginated(
        api.list_placements(COMPLIANCE_ANALYST, {"determination_id": determination_id})
    )
    return rows


def _projects_of(api, product_id):
    rows, _ = validate_paginated(
        api.list_reformulation_projects(COMPLIANCE_ANALYST, {"product_id": product_id})
    )
    return rows


# ─────────────────────────────────────────────────────────────────────────────
# Closed placement windows
# ─────────────────────────────────────────────────────────────────────────────


class TestPlacementClosedWindows:
    def test_a_window_starting_at_the_occupant_s_end_collides(
        self, api, label_slot_with_closed_window
    ):
        """Both ends are inclusive, so 2026-07-01 is still inside the existing window.

        PRD: "Two windows for the same determination and the same channel collide when the new window's start is at or before the existing window's end **and** the existing window's start is at or before the new window's end. Because both ends are inclusive, two windows that merely touch — where the new start equals the existing end — **do** collide."

        Design: Difficulty/resource_temporal_overlap/placement_closed_windows_collide_on_touching_endpoint
        """
        bundle = label_slot_with_closed_window
        validate_error(
            _create_placement(
                api,
                bundle["determination"]["id"],
                "2026-07-01T00:00:00Z",
                "2026-08-01T00:00:00Z",
                "Touching window",
            ),
            ERR_PLACEMENT_OVERLAP,
            409,
        )

    def test_a_window_starting_one_day_later_is_accepted(
        self, api, label_slot_with_closed_window
    ):
        """The nearest non-colliding start is one day past the occupant's end.

        PRD: "A newly created placement has `status` `PLANNED`, `implemented_by_user_id` null and `remediation_count` 0, and its creation recomputes the determination's `covered_channel_count` and the product's `compliance_posture`."

        Design: Difficulty/resource_temporal_overlap/placement_closed_windows_collide_on_touching_endpoint
        """
        bundle = label_slot_with_closed_window
        placement = get_success_data(
            _create_placement(
                api,
                bundle["determination"]["id"],
                "2026-07-02T00:00:00Z",
                "2026-08-01T00:00:00Z",
                "Disjoint window",
            )
        )
        assert_status(placement, PLACEMENT_PLANNED)
        assert placement["remediation_count"] == 0

    def test_an_open_ended_window_swallows_every_later_window(
        self, api, label_slot_with_closed_window
    ):
        """A null effective_to is positive infinity, so a window inside the tail collides.

        PRD: "**Warning placement windows are CLOSED at both ends.** A placement is described by `effective_from` and an optional `effective_to`; a null `effective_to` means open-ended and is treated as positive infinity."

        Design: Difficulty/resource_temporal_overlap/placement_closed_windows_collide_on_touching_endpoint
        """
        bundle = label_slot_with_closed_window
        open_ended = get_success_data(
            _create_placement(
                api,
                bundle["determination"]["id"],
                "2026-09-01T00:00:00Z",
                f.OMIT,
                "Open ended window",
            )
        )
        assert open_ended["effective_to"] is None
        validate_error(
            _create_placement(
                api,
                bundle["determination"]["id"],
                "2026-10-01T00:00:00Z",
                "2026-11-01T00:00:00Z",
                "Inside the open tail",
            ),
            ERR_PLACEMENT_OVERLAP,
            409,
        )

    def test_only_the_accepted_windows_leave_rows_behind(
        self, api, label_slot_with_closed_window
    ):
        """Four creates, two refusals, and exactly three placements on the slot.

        PRD: "Overlap is judged against existing placements of the same determination on the same channel whose status is not `NON_COMPLIANT`; a flagged placement no longer reserves its window."

        Design: Difficulty/resource_temporal_overlap/placement_closed_windows_collide_on_touching_endpoint
        """
        bundle = label_slot_with_closed_window
        validate_error(
            _create_placement(
                api,
                bundle["determination"]["id"],
                "2026-07-01T00:00:00Z",
                "2026-08-01T00:00:00Z",
                "Touching window",
            ),
            ERR_PLACEMENT_OVERLAP,
            409,
        )
        get_success_data(
            _create_placement(
                api,
                bundle["determination"]["id"],
                "2026-07-02T00:00:00Z",
                "2026-08-01T00:00:00Z",
                "Disjoint window",
            )
        )
        get_success_data(
            _create_placement(
                api,
                bundle["determination"]["id"],
                "2026-09-01T00:00:00Z",
                f.OMIT,
                "Open ended window",
            )
        )
        validate_error(
            _create_placement(
                api,
                bundle["determination"]["id"],
                "2026-10-01T00:00:00Z",
                "2026-11-01T00:00:00Z",
                "Inside the open tail",
            ),
            ERR_PLACEMENT_OVERLAP,
            409,
        )
        assert len(_placements_of(api, bundle["determination"]["id"])) == 3


# ─────────────────────────────────────────────────────────────────────────────
# Half-open reformulation windows
# ─────────────────────────────────────────────────────────────────────────────


class TestReformulationHalfOpenWindows:
    def test_a_project_starting_at_the_occupant_s_end_is_accepted(
        self, api, reformulation_slot_with_half_open_window
    ):
        """The same touching pair that collides on a label does not collide here.

        PRD: "Project windows are **half-open**, so two windows collide only when the new start is strictly before the existing end and the existing start is strictly before the new end — a project starting at the exact instant another ends does **not** collide."

        Design: Difficulty/resource_temporal_overlap/reformulation_half_open_windows_allow_touching_endpoint
        """
        bundle = reformulation_slot_with_half_open_window
        assert_status(bundle["project"], PROJECT_PLANNED)
        touching = get_success_data(
            _create_project(
                api, bundle, 20.0, "2026-07-01T00:00:00Z", "2026-08-01T00:00:00Z"
            )
        )
        assert_status(touching, PROJECT_PLANNED)

    def test_a_project_straddling_the_seam_is_refused(
        self, api, reformulation_slot_with_half_open_window
    ):
        """2026-06-15 to 2026-07-15 genuinely intersects both neighbours, so it collides.

        PRD: "A project may not be opened whose window collides with an existing non-terminal project on the same product and chemical pair; collision is refused with `ERR_REFORMULATION_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/reformulation_half_open_windows_allow_touching_endpoint
        """
        bundle = reformulation_slot_with_half_open_window
        get_success_data(
            _create_project(
                api, bundle, 20.0, "2026-07-01T00:00:00Z", "2026-08-01T00:00:00Z"
            )
        )
        validate_error(
            _create_project(
                api, bundle, 10.0, "2026-06-15T00:00:00Z", "2026-07-15T00:00:00Z"
            ),
            ERR_REFORMULATION_OVERLAP,
            409,
        )

    def test_abandoning_a_project_releases_its_window(
        self, api, reformulation_slot_with_half_open_window
    ):
        """Only non-terminal projects hold the slot, so the abandoned window may be reused.

        PRD: "Abandoning takes the project to `ABANDONED` from any of `PLANNED`, `IN_PROGRESS` or `VERIFICATION` with no cascade beyond the version bump."

        Design: Difficulty/resource_temporal_overlap/reformulation_half_open_windows_allow_touching_endpoint
        """
        bundle = reformulation_slot_with_half_open_window
        abandoned = get_success_data(
            api.reformulation_transition(
                bundle["project"]["id"],
                f.action_payload("ABANDON"),
                COMPLIANCE_ANALYST,
            )
        )
        assert_status(abandoned, PROJECT_ABANDONED)

        reused = get_success_data(
            _create_project(
                api, bundle, 10.0, "2026-06-01T00:00:00Z", "2026-06-20T00:00:00Z"
            )
        )
        assert_status(reused, PROJECT_PLANNED)

    def test_the_two_conventions_are_deliberate_counterparts(
        self, api, reformulation_slot_with_half_open_window
    ):
        """Three project rows survive the whole sequence, one of them terminal.

        PRD: "This is the deliberate counterpart to the closed windows used for warning placements: two intervals with touching endpoints collide on a label placement and do not collide on a reformulation project."

        Design: Difficulty/resource_temporal_overlap/reformulation_half_open_windows_allow_touching_endpoint
        """
        bundle = reformulation_slot_with_half_open_window
        get_success_data(
            _create_project(
                api, bundle, 20.0, "2026-07-01T00:00:00Z", "2026-08-01T00:00:00Z"
            )
        )
        validate_error(
            _create_project(
                api, bundle, 10.0, "2026-06-15T00:00:00Z", "2026-07-15T00:00:00Z"
            ),
            ERR_REFORMULATION_OVERLAP,
            409,
        )
        get_success_data(
            api.reformulation_transition(
                bundle["project"]["id"],
                f.action_payload("ABANDON"),
                COMPLIANCE_ANALYST,
            )
        )
        get_success_data(
            _create_project(
                api, bundle, 10.0, "2026-06-01T00:00:00Z", "2026-06-20T00:00:00Z"
            )
        )
        assert len(_projects_of(api, bundle["product"]["id"])) == 3

# ─────────────────────────────────────────────────────────────────────────────
# A flagged placement stops reserving its window
# ─────────────────────────────────────────────────────────────────────────────


class TestFlaggedPlacementReleasesItsWindow:
    def test_a_duplicate_window_is_refused_while_the_occupant_is_verified(
        self, api, verified_label_placement
    ):
        """VERIFIED is not NON_COMPLIANT, so the occupant still reserves its window.

        PRD: "Overlap is judged against existing placements of the same determination on the same channel whose status is not `NON_COMPLIANT`; a flagged placement no longer reserves its window."

        Design: Difficulty/resource_temporal_overlap/non_compliant_placement_releases_its_overlap_window
        """
        bundle = verified_label_placement
        assert_status(bundle["placement"], PLACEMENT_VERIFIED)
        validate_error(
            _create_placement(
                api,
                bundle["determination"]["id"],
                "2026-06-01T00:00:00Z",
                "2026-07-01T00:00:00Z",
                "Duplicate window while A is VERIFIED",
            ),
            ERR_PLACEMENT_OVERLAP,
            409,
        )

    def test_flagging_the_occupant_empties_the_coverage_and_the_posture(
        self, api, verified_label_placement
    ):
        """The flag is a legal edge out of VERIFIED and it drives the product off WARNING_ACTIVE.

        PRD: "A `RegulatoryCounsel` may flag a placement non-compliant from either `VERIFIED → NON_COMPLIANT` or `IMPLEMENTED → NON_COMPLIANT`, and the system applies the same flag as part of a determination revocation."

        Design: Difficulty/resource_temporal_overlap/non_compliant_placement_releases_its_overlap_window
        """
        bundle = verified_label_placement
        flagged = get_success_data(
            api.placement_transition(
                bundle["placement"]["id"],
                f.action_payload("FLAG_NON_COMPLIANT"),
                REGULATORY_COUNSEL,
            )
        )
        assert_status(flagged, PLACEMENT_NON_COMPLIANT)

        determination = get_success_data(
            api.get_determination(bundle["determination"]["id"], COMPLIANCE_ANALYST)
        )
        assert determination["covered_channel_count"] == 0
        assert_posture(
            read_product(api, bundle["product"]["id"]), POSTURE_WARNING_REQUIRED
        )

    def test_the_released_window_may_be_reused_exactly(
        self, api, verified_label_placement
    ):
        """The identical request that was refused a moment ago is now accepted.

        PRD: "Overlap is judged against existing placements of the same determination on the same channel whose status is not `NON_COMPLIANT`; a flagged placement no longer reserves its window."

        Design: Difficulty/resource_temporal_overlap/non_compliant_placement_releases_its_overlap_window
        """
        bundle = verified_label_placement
        validate_error(
            _create_placement(
                api,
                bundle["determination"]["id"],
                "2026-06-01T00:00:00Z",
                "2026-07-01T00:00:00Z",
                "Duplicate window while A is VERIFIED",
            ),
            ERR_PLACEMENT_OVERLAP,
            409,
        )
        get_success_data(
            api.placement_transition(
                bundle["placement"]["id"],
                f.action_payload("FLAG_NON_COMPLIANT"),
                REGULATORY_COUNSEL,
            )
        )
        replacement = get_success_data(
            _create_placement(
                api,
                bundle["determination"]["id"],
                "2026-06-01T00:00:00Z",
                "2026-07-01T00:00:00Z",
                "Reprinted sticker",
            )
        )
        assert_status(replacement, PLACEMENT_PLANNED)

    def test_the_replacement_immediately_reserves_the_window_itself(
        self, api, verified_label_placement
    ):
        """A third identical request is refused because the PLANNED replacement now holds the slot.

        PRD: "Two windows for the same determination and the same channel collide when the new window's start is at or before the existing window's end **and** the existing window's start is at or before the new window's end. Because both ends are inclusive, two windows that merely touch — where the new start equals the existing end — **do** collide."

        Design: Difficulty/resource_temporal_overlap/non_compliant_placement_releases_its_overlap_window
        """
        bundle = verified_label_placement
        get_success_data(
            api.placement_transition(
                bundle["placement"]["id"],
                f.action_payload("FLAG_NON_COMPLIANT"),
                REGULATORY_COUNSEL,
            )
        )
        get_success_data(
            _create_placement(
                api,
                bundle["determination"]["id"],
                "2026-06-01T00:00:00Z",
                "2026-07-01T00:00:00Z",
                "Reprinted sticker",
            )
        )
        validate_error(
            _create_placement(
                api,
                bundle["determination"]["id"],
                "2026-06-01T00:00:00Z",
                "2026-07-01T00:00:00Z",
                "Third attempt at the same window",
            ),
            ERR_PLACEMENT_OVERLAP,
            409,
        )
        assert len(_placements_of(api, bundle["determination"]["id"])) == 2
