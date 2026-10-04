"""Interconnection: study windows, rework cycle, phase gates, allocation,
withdrawal cascade, and queue-position invariants."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_interconnection_request,
    create_project,
    create_study_payload,
    get_success_data,
    validate_error,
    validate_success,
)

AUDITOR_ROLE = None  # populated via fixture injection


def _new_project(api, headers, name, capacity, cluster=None):
    return create_project(name=name, target_capacity_mw=capacity)


def test_study_window_closed_interval_with_buffer(
    api, developer_admin_headers, origination_manager_headers
):
    """PRD §3.2: "Scoping is rejected with `ERR_STUDY_WINDOW_CONFLICT` (HTTP
    409) when another study of the same phase exists on the same cluster whose
    window, widened by a 5-calendar-day buffer on each side, collides with the
    new one — concretely, when the existing study's `window_end` is at least
    the new `window_start` minus 5 days and its `window_start` is at most the
    new `window_end` plus 5 days."

    Design: Difficulty/resource_temporal_overlap/study_window_closed_interval_with_buffer
    """
    p1 = create_project(name="Study Farm 1", target_capacity_mw=80)
    p2 = create_project(name="Study Farm 2", target_capacity_mw=70)
    r1 = create_interconnection_request(p1["id"], "CL-S", 80)
    r2 = create_interconnection_request(p2["id"], "CL-S", 70)
    get_success_data(
        api.transition_interconnection_request(r1["id"], {"to": "FEASIBILITY_STUDY"}, origination_manager_headers)
    )
    get_success_data(
        api.create_study(
            r1["id"],
            create_study_payload(
                phase="SYSTEM_IMPACT",
                window_start="2027-02-01T00:00:00Z",
                window_end="2027-03-10T00:00:00Z",
            ),
            origination_manager_headers,
        )
    )
    # Existing buffered end: 2027-03-10 + 5 days = 2027-03-15. Start there: conflict.
    resp = api.create_study(
        r2["id"],
        create_study_payload(
            phase="SYSTEM_IMPACT",
            window_start="2027-03-15T00:00:00Z",
            window_end="2027-04-15T00:00:00Z",
        ),
        origination_manager_headers,
    )
    validate_error(resp, ApiErrorId.ERR_STUDY_WINDOW_CONFLICT)
    # One day later: strictly beyond the buffered end, so it is clean.
    ok = validate_success(
        api.create_study(
            r2["id"],
            create_study_payload(
                phase="SYSTEM_IMPACT",
                window_start="2027-03-16T00:00:00Z",
                window_end="2027-04-16T00:00:00Z",
            ),
            origination_manager_headers,
        ),
        expected_status=201,
    )
    assert ok["status"] == "SCOPED"


def test_study_window_conflict_other_phase_not_checked(
    api, developer_admin_headers, origination_manager_headers
):
    """PRD §3.2: "Scoping is rejected with `ERR_STUDY_WINDOW_CONFLICT` (HTTP
    409) when another study of the same phase exists on the same cluster whose
    window, widened by a 5-calendar-day buffer on each side, collides with the
    new one".

    Design: Difficulty/resource_temporal_overlap/study_window_closed_interval_with_buffer
    """
    p1 = create_project(name="Study Farm Ph1", target_capacity_mw=80)
    p2 = create_project(name="Study Farm Ph2", target_capacity_mw=70)
    r1 = create_interconnection_request(p1["id"], "CL-SPH", 80)
    r2 = create_interconnection_request(p2["id"], "CL-SPH", 70)
    # An existing FEASIBILITY study on the cluster does not block a
    # SYSTEM_IMPACT study with an overlapping window (the rule is same-phase).
    get_success_data(
        api.create_study(
            r1["id"],
            create_study_payload(
                phase="FEASIBILITY",
                window_start="2027-02-01T00:00:00Z",
                window_end="2027-03-10T00:00:00Z",
            ),
            origination_manager_headers,
        )
    )
    ok = validate_success(
        api.create_study(
            r2["id"],
            create_study_payload(
                phase="SYSTEM_IMPACT",
                window_start="2027-02-15T00:00:00Z",
                window_end="2027-03-15T00:00:00Z",
            ),
            origination_manager_headers,
        ),
        expected_status=201,
    )
    assert ok["phase"] == "SYSTEM_IMPACT"


def test_study_deficiency_rework_cycle(
    api, developer_admin_headers, origination_manager_headers
):
    """PRD §3.2: "A deficient study re-enters `IN_PROGRESS` through the rework
    loop, and each such rework increments the study's `rework_count`, which
    starts at 0. `ACCEPTED` is terminal for a study."
    PRD §3.2: "Moving from `FEASIBILITY_STUDY` to `SYSTEM_IMPACT_STUDY`
    requires that the most recently created (by `created_at`) `FEASIBILITY`-
    phase study of the request be `ACCEPTED`".

    Design: Difficulty/non_linear_state_machine/study_deficiency_rework_cycle
    """
    p = create_project(name="Rework Farm", technology="SOLAR", target_capacity_mw=60,
                       resource_class="C")
    r = create_interconnection_request(p["id"], "CL-RW", 60)
    get_success_data(
        api.transition_interconnection_request(r["id"], {"to": "FEASIBILITY_STUDY"}, origination_manager_headers)
    )
    study = get_success_data(
        api.create_study(
            r["id"],
            create_study_payload(
                phase="FEASIBILITY",
                window_start="2026-10-01T00:00:00Z",
                window_end="2026-10-31T00:00:00Z",
            ),
            origination_manager_headers,
        )
    )
    get_success_data(api.transition_study(study["id"], {"to": "IN_PROGRESS"}, origination_manager_headers))
    get_success_data(api.transition_study(study["id"], {"to": "DELIVERED"}, origination_manager_headers))
    get_success_data(api.transition_study(study["id"], {"to": "DEFICIENT"}, origination_manager_headers))
    get_success_data(api.transition_study(study["id"], {"to": "IN_PROGRESS"}, origination_manager_headers))
    get_success_data(api.transition_study(study["id"], {"to": "DELIVERED"}, origination_manager_headers))
    accepted = get_success_data(
        api.transition_study(study["id"], {"to": "ACCEPTED"}, origination_manager_headers)
    )
    assert accepted["rework_count"] == 1
    assert accepted["status"] == "ACCEPTED"
    # The reworked ACCEPTED unblocks the phase gate.
    advanced = get_success_data(
        api.transition_interconnection_request(
            r["id"], {"to": "SYSTEM_IMPACT_STUDY"}, origination_manager_headers
        )
    )
    assert advanced["status"] == "SYSTEM_IMPACT_STUDY"


def test_study_deficient_twice_rework_count_accumulates(
    api, developer_admin_headers, origination_manager_headers
):
    """PRD §3.2: "A deficient study re-enters `IN_PROGRESS` through the rework
    loop, and each such rework increments the study's `rework_count`, which
    starts at 0."

    Design: Difficulty/non_linear_state_machine/study_deficiency_rework_cycle
    """
    p = create_project(name="Rework Farm 2", technology="WIND", target_capacity_mw=60)
    r = create_interconnection_request(p["id"], "CL-RW2", 60)
    get_success_data(
        api.transition_interconnection_request(r["id"], {"to": "FEASIBILITY_STUDY"}, origination_manager_headers)
    )
    study = get_success_data(
        api.create_study(
            r["id"],
            create_study_payload(
                phase="FEASIBILITY",
                window_start="2026-10-01T00:00:00Z",
                window_end="2026-10-31T00:00:00Z",
            ),
            origination_manager_headers,
        )
    )
    for _ in range(2):
        get_success_data(api.transition_study(study["id"], {"to": "IN_PROGRESS"}, origination_manager_headers))
        get_success_data(api.transition_study(study["id"], {"to": "DELIVERED"}, origination_manager_headers))
        get_success_data(api.transition_study(study["id"], {"to": "DEFICIENT"}, origination_manager_headers))
    get_success_data(api.transition_study(study["id"], {"to": "IN_PROGRESS"}, origination_manager_headers))
    current = get_success_data(api.get_study(study["id"], origination_manager_headers))
    assert current["rework_count"] == 2


def test_phase_advance_requires_accepted_study(
    api, developer_admin_headers, origination_manager_headers
):
    """PRD §3.2: "Moving from `FEASIBILITY_STUDY` to `SYSTEM_IMPACT_STUDY`
    requires that the most recently created (by `created_at`) `FEASIBILITY`-
    phase study of the request be `ACCEPTED`, failing with
    `ERR_PHASE_STUDY_NOT_ACCEPTED` (HTTP 409) otherwise."

    Design: Corner/validations/phase_advance_requires_accepted_study
    """
    p = create_project(name="Gate Study Farm", technology="SOLAR", target_capacity_mw=65)
    r = create_interconnection_request(p["id"], "CL-GS", 65)
    get_success_data(
        api.transition_interconnection_request(r["id"], {"to": "FEASIBILITY_STUDY"}, origination_manager_headers)
    )
    study = get_success_data(
        api.create_study(
            r["id"],
            create_study_payload(
                phase="FEASIBILITY",
                window_start="2026-10-01T00:00:00Z",
                window_end="2026-10-31T00:00:00Z",
            ),
            origination_manager_headers,
        )
    )
    get_success_data(api.transition_study(study["id"], {"to": "IN_PROGRESS"}, origination_manager_headers))
    get_success_data(api.transition_study(study["id"], {"to": "DELIVERED"}, origination_manager_headers))
    # DELIVERED is not ACCEPTED: the gate stays closed.
    resp = api.transition_interconnection_request(
        r["id"], {"to": "SYSTEM_IMPACT_STUDY"}, origination_manager_headers
    )
    validate_error(resp, ApiErrorId.ERR_PHASE_STUDY_NOT_ACCEPTED)
    current = get_success_data(
        api.get_interconnection_request(r["id"], origination_manager_headers)
    )
    assert current["status"] == "FEASIBILITY_STUDY"


def test_facilities_gate_requires_upgrade_allocation(
    api, developer_admin_headers, origination_manager_headers
):
    """PRD §3.2: "Moving from `SYSTEM_IMPACT_STUDY` to `FACILITIES_STUDY`
    requires both that the latest `SYSTEM_IMPACT` study be `ACCEPTED` (same
    error) and that `upgrade_allocated` be true for this request (otherwise
    `ERR_UPGRADE_ALLOCATION_REQUIRED`, HTTP 409)."

    Design: Corner/validations/facilities_gate_requires_upgrade_allocation
    """
    p = create_project(name="Alloc Gate Farm", technology="WIND", target_capacity_mw=85)
    r = create_interconnection_request(p["id"], "CL-AG", 85)
    get_success_data(
        api.transition_interconnection_request(r["id"], {"to": "FEASIBILITY_STUDY"}, origination_manager_headers)
    )
    for phase, window in (
        ("FEASIBILITY", ("2026-10-01T00:00:00Z", "2026-10-31T00:00:00Z")),
        ("SYSTEM_IMPACT", ("2026-11-06T00:00:00Z", "2026-12-15T00:00:00Z")),
    ):
        study = get_success_data(
            api.create_study(
                r["id"],
                create_study_payload(phase=phase, window_start=window[0], window_end=window[1]),
                origination_manager_headers,
            )
        )
        for to in ("IN_PROGRESS", "DELIVERED", "ACCEPTED"):
            get_success_data(api.transition_study(study["id"], {"to": to}, origination_manager_headers))
        if phase == "FEASIBILITY":
            get_success_data(
                api.transition_interconnection_request(
                    r["id"], {"to": "SYSTEM_IMPACT_STUDY"}, origination_manager_headers
                )
            )
    resp = api.transition_interconnection_request(
        r["id"], {"to": "FACILITIES_STUDY"}, origination_manager_headers
    )
    validate_error(resp, ApiErrorId.ERR_UPGRADE_ALLOCATION_REQUIRED)
    current = get_success_data(
        api.get_interconnection_request(r["id"], origination_manager_headers)
    )
    assert current["status"] == "SYSTEM_IMPACT_STUDY"
