"""Design-job revision cycles and designer measurement-window overlap (PRD §3.2)."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    PROGRAM_MANAGER_HEADERS,
    factories,
    family_spec,
    make_retail_designer_headers,
    order_line,
)
from test_helpers import fixtures

DESIGNER = "des-1"


def _retail_world(api):
    return fixtures.setup_active_program(
        api,
        retail=True,
        store_codes=["ST-1", "ST-2"],
        families=[family_spec(base_lead_weeks=2)],
    )


def test_fourth_backward_revision_rejected(api):
    """Three backward revisions are allowed; the fourth is refused.

    PRD §3.2: "A job allows at most 3 backward revisions; a fourth is rejected with `ERR_REVISION_LIMIT_EXCEEDED`."
    PRD §3.2: "Each backward step is a revision: it increments `revision_count`, clears `quoted_total_cents` back to null, and — when the step lands on `MEASURED` from `LAYOUT_READY` — clears the stored `layout_lines` as well."
    Design: Difficulty/non_linear_state_machine/design_job_revision_cycle_bounded_by_cap
    """
    world = _retail_world(api)
    job = fixtures.create_design_job(api, world["account"], world["program"], DESIGNER)
    job_id = job["id"]

    fixtures.transition_design_job(api, job_id, "MEASURED", DESIGNER)
    fixtures.transition_design_job(
        api, job_id, "LAYOUT_READY", DESIGNER, layout_lines=[order_line(quantity=1)]
    )
    fixtures.transition_design_job(api, job_id, "QUOTED", DESIGNER)

    # Revision 1: QUOTED -> LAYOUT_READY with a fresh layout, then re-quote.
    fixtures.transition_design_job(
        api, job_id, "LAYOUT_READY", DESIGNER, layout_lines=[order_line(quantity=2)]
    )
    quoted_r1 = fixtures.transition_design_job(api, job_id, "QUOTED", DESIGNER)
    assert quoted_r1["quoted_total_cents"] == 20000

    # Revision 2: QUOTED -> MEASURED with a fresh, non-overlapping window.
    fixtures.transition_design_job(
        api, job_id, "MEASURED", DESIGNER,
        measure_window_start="2026-09-03T09:00:00Z",
        measure_window_end="2026-09-03T10:00:00Z",
    )
    fixtures.transition_design_job(
        api, job_id, "LAYOUT_READY", DESIGNER, layout_lines=[order_line(quantity=1)]
    )
    fixtures.transition_design_job(api, job_id, "QUOTED", DESIGNER)

    # Revision 3: QUOTED -> LAYOUT_READY and re-quote once more.
    fixtures.transition_design_job(
        api, job_id, "LAYOUT_READY", DESIGNER, layout_lines=[order_line(quantity=3)]
    )
    quoted_r3 = fixtures.transition_design_job(api, job_id, "QUOTED", DESIGNER)
    assert quoted_r3["quoted_total_cents"] == 30000

    blocked = api.transition_design_job(
        job_id,
        factories.design_job_transition_payload("LAYOUT_READY", layout_lines=[order_line(quantity=4)]),
        make_retail_designer_headers(DESIGNER),
    )
    validate_error(blocked, "ERR_REVISION_LIMIT_EXCEEDED")

    after = fixtures.get_design_job(api, job_id, PROGRAM_MANAGER_HEADERS)
    assert after["status"] == "QUOTED"
    assert after["revision_count"] == 3
    assert after["quoted_total_cents"] == 30000


def test_revision_clears_quote_and_stores_fresh_layout(api):
    """One backward step clears the quote and repricing reflects the new layout.

    PRD §3.2: "The designer may step backward: `QUOTED` → `LAYOUT_READY` with a fresh, non-empty set of `layout_lines` (`ERR_INVALID_REQUEST` when absent), or `QUOTED` → `MEASURED` and `LAYOUT_READY` → `MEASURED` with a fresh measurement window that is re-validated for window shape and designer overlap."
    PRD §3.2: "Each backward step is a revision: it increments `revision_count`, clears `quoted_total_cents` back to null, and — when the step lands on `MEASURED` from `LAYOUT_READY` — clears the stored `layout_lines` as well."
    Design: Difficulty/non_linear_state_machine/design_job_revision_cycle_bounded_by_cap
    """
    world = _retail_world(api)
    job = fixtures.create_design_job(api, world["account"], world["program"], DESIGNER)
    job_id = job["id"]
    quoted = fixtures.quote_design_job(api, job_id, DESIGNER, [order_line(quantity=1)])
    assert quoted["quoted_total_cents"] == 10000

    revised = fixtures.transition_design_job(
        api, job_id, "LAYOUT_READY", DESIGNER, layout_lines=[order_line(quantity=2)]
    )
    assert revised["status"] == "LAYOUT_READY"
    assert revised["revision_count"] == 1
    assert revised["quoted_total_cents"] is None

    requoted = fixtures.transition_design_job(api, job_id, "QUOTED", DESIGNER)
    assert requoted["quoted_total_cents"] == 20000
    assert requoted["revision_count"] == 1


def test_half_open_same_store_touch_and_cross_store_buffer(api):
    """Same-store windows may touch; different stores need a 30-minute gap.

    PRD §3.2: "Windows are treated as half-open intervals, so at the same `store_code` one window may end at the exact instant another begins."
    PRD §3.2: "Across two different store codes, however, the designer needs travel time: the gap between the end of one window and the start of the next must be at least 30 minutes."
    PRD §3.2: "A colliding window — whether at booking or at a later revision — is rejected with `ERR_DESIGNER_WINDOW_OVERLAP`."
    Design: Difficulty/resource_temporal_overlap/designer_measure_windows_half_open_with_cross_store_buffer
    """
    world = _retail_world(api)
    headers = make_retail_designer_headers(DESIGNER)

    def book(store_code, start, end):
        return api.create_design_job(
            factories.design_job_payload(
                world["account"]["id"], world["program"]["id"],
                store_code=store_code,
                measure_window_start=start, measure_window_end=end,
            ),
            headers,
        )

    job_a = validate_success(book("ST-1", "2026-09-02T09:00:00Z", "2026-09-02T10:00:00Z"), 201)
    assert job_a["status"] == "REQUESTED"

    # Same store, starting exactly at job_a's end: half-open adjacency passes.
    job_b = validate_success(book("ST-1", "2026-09-02T10:00:00Z", "2026-09-02T11:00:00Z"), 201)
    assert job_b["status"] == "REQUESTED"

    # Different store, starting 30 minutes into job_b's window: collides.
    colliding = book("ST-2", "2026-09-02T10:30:00Z", "2026-09-02T11:30:00Z")
    validate_error(colliding, "ERR_DESIGNER_WINDOW_OVERLAP")

    # Different store, exactly 30 minutes after job_b ends: the buffer boundary passes.
    job_d = validate_success(book("ST-2", "2026-09-02T11:30:00Z", "2026-09-02T12:30:00Z"), 201)
    assert job_d["status"] == "REQUESTED"


def test_same_store_overlap_and_sub_buffer_gap_rejected(api):
    """A true same-store overlap and a 29-minute cross-store gap both fail.

    PRD §3.2: "Among one designer's jobs in `REQUESTED` or `MEASURED`, no two windows may overlap."
    PRD §3.2: "Across two different store codes, however, the designer needs travel time: the gap between the end of one window and the start of the next must be at least 30 minutes."
    PRD §3.2: "A colliding window — whether at booking or at a later revision — is rejected with `ERR_DESIGNER_WINDOW_OVERLAP`."
    Design: Difficulty/resource_temporal_overlap/designer_measure_windows_half_open_with_cross_store_buffer
    """
    world = _retail_world(api)
    headers = make_retail_designer_headers(DESIGNER)

    def book(store_code, start, end):
        return api.create_design_job(
            factories.design_job_payload(
                world["account"]["id"], world["program"]["id"],
                store_code=store_code,
                measure_window_start=start, measure_window_end=end,
            ),
            headers,
        )

    validate_success(book("ST-1", "2026-09-02T09:00:00Z", "2026-09-02T10:00:00Z"), 201)

    # Same store, overlapping interior of the existing window.
    validate_error(
        book("ST-1", "2026-09-02T09:30:00Z", "2026-09-02T10:30:00Z"),
        "ERR_DESIGNER_WINDOW_OVERLAP",
    )
    # Different store, only 29 minutes after the existing window ends.
    validate_error(
        book("ST-2", "2026-09-02T10:29:00Z", "2026-09-02T11:29:00Z"),
        "ERR_DESIGNER_WINDOW_OVERLAP",
    )
    # Different store, exactly the 30-minute buffer: accepted.
    ok = validate_success(book("ST-2", "2026-09-02T10:30:00Z", "2026-09-02T11:30:00Z"), 201)
    assert ok["status"] == "REQUESTED"
