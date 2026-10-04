"""Corner coverage — calculations: fair-queue head selection by priority
rank, the two unmet-demand report variants, and the autoclave batch ceiling."""

from test_helpers import (
    TEST_USERS,
    begin_service_payload,
    complete_encounter_with_referral,
    create_event_in_service,
    create_event_site_locked,
    create_unpacked_sterilizer_manifest,
    get_success_data,
    issue_ticket,
    setup_event_with_open_encounter,
    setup_event_with_queued_ticket,
    validate_error,
    validate_paginated,
    validate_success,
)

ED = TEST_USERS["event_director_headers"]
QM = TEST_USERS["queue_marshal_headers"]
SL = TEST_USERS["station_lead_headers"]
ST = TEST_USERS["sterilization_tech_headers"]


def test_queue_head_vulnerable_priority_overrides_arrival(api):
    """PRD §3.6: "the head of the queue is the ticket that sorts first by
    priority rank, where `VULNERABLE` ranks ahead of `STANDARD`, then by
    earliest `arrival_utc`, then by earliest `created_at`" and "fails with
    `ERR_NOT_QUEUE_HEAD` if the named ticket is not the fair-sequence head for
    its service."

    Design: Corner/calculations/queue_head_vulnerable_priority_overrides_arrival
    """
    event = create_event_in_service()
    standard = issue_ticket(
        event["id"],
        patient_ref="P-STD",
        arrival_utc="2026-10-03T10:00:00Z",
        priority_tier="STANDARD",
    )
    vulnerable = issue_ticket(
        event["id"],
        patient_ref="P-VUL",
        arrival_utc="2026-10-03T10:05:00Z",
        priority_tier="VULNERABLE",
    )

    # The earlier-arriving STANDARD ticket is behind the VULNERABLE one.
    response = api.call_ticket(event["id"], standard["id"], QM)
    validate_error(response, "ERR_NOT_QUEUE_HEAD")

    called = get_success_data(api.call_ticket(event["id"], vulnerable["id"], QM))
    assert called["status"] == "CALLED"


def test_unmet_demand_report_variants_diverge(api):
    """PRD §3.8: "In the `OBSERVED_ONLY` variant,
    `estimated_unserved_beyond_queue` is zero" and "In the
    `WITH_EXTRAPOLATION` variant, the report extrapolates demand that never
    reached ticketing: the extrapolation factor is one plus the ratio of
    tickets still `QUEUED` at the end-of-service cascade to the event's
    `tickets_served_count` (with a served count of zero treated as one to keep
    the ratio defined). The `estimated_unserved_beyond_queue` is then the
    observed count multiplied by that factor, rounded half-up, minus the
    observed count itself."

    Design: Corner/calculations/unmet_demand_report_variants_diverge
    """
    # IN_SERVICE event with one SERVED ticket and two QUEUED tickets that the
    # end-of-service cascade turns away: observed=2, queue_at_close=2,
    # served=1 -> factor=3 -> round_half_up(2*3)-2 = 4.
    ctx = setup_event_with_open_encounter()
    issue_ticket(ctx["id"], patient_ref="P-U2", arrival_utc="2026-10-03T10:05:00Z")
    issue_ticket(ctx["id"], patient_ref="P-U3", arrival_utc="2026-10-03T10:10:00Z")
    get_success_data(
        api.complete_encounter(ctx["id"], ctx["encounter_id"], {}, SL)
    )
    get_success_data(api.end_service(ctx["id"], ED))

    observed_report = validate_success(
        api.generate_unmet_demand_report(
            ctx["id"], {"report_variant": "OBSERVED_ONLY"}, ED
        ),
        201,
    )
    assert observed_report["turned_away_count"] == 2
    assert observed_report["estimated_unserved_beyond_queue"] == 0

    extrapolated_report = validate_success(
        api.generate_unmet_demand_report(
            ctx["id"], {"report_variant": "WITH_EXTRAPOLATION"}, ED
        ),
        201,
    )
    assert extrapolated_report["turned_away_count"] == 2
    assert extrapolated_report["estimated_unserved_beyond_queue"] == 4


def test_sterilization_batch_max_enforced(api):
    """PRD §2.8: "An autoclave cycle may carry at most 24 instrument kits —
    `instrument_batch_size` must be at least 1 and at most 24, and a larger
    request is rejected with `ERR_BATCH_TOO_LARGE`."

    Design: Corner/calculations/sterilization_batch_max_enforced
    """
    event = create_event_site_locked(
        event_overrides={
            "host_state_code": "KY",
            "service_date": "2027-05-15",
            "doors_open_utc": "2027-05-15T10:00:00Z",
            "total_patient_capacity": 10,
        },
        site_overrides={
            "site_type": "ARENA",
            "state_code": "KY",
            "square_footage": 30000,
            "has_loading_dock": True,
            "sterilization_capable": True,
        },
    )
    create_unpacked_sterilizer_manifest(event["id"])

    cycle = validate_success(
        api.start_sterilization_cycle(
            event["id"], {"instrument_batch_size": 24}, ST
        ),
        201,
    )
    assert cycle["status"] == "RUNNING"

    response = api.start_sterilization_cycle(
        event["id"], {"instrument_batch_size": 25}, ST
    )
    validate_error(response, "ERR_BATCH_TOO_LARGE")
