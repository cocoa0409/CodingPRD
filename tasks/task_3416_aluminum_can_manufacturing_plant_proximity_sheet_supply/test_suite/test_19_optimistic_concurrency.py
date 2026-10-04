"""Optimistic concurrency on the agreement version (PRD §2.9)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    set_clock, create_plant, create_customer, create_active_agreement,
    create_line, create_qualified_format, get_agreement, create_run,
    make_customer_planner_headers, scheduler, manager, api_client,
)


class TestAmendOcc:
    def test_agreement_amend_with_stale_version_rejected_412(self, api):
        """PRD §2.9: "A `POST /supply-agreements/{id}/amend` request must carry
        `expected_agreement_version` holding the agreement `version` the client
        last observed. If the agreement's current `version` has advanced past
        the supplied value, the request is rejected with `ERR_STALE_VERSION`
        (HTTP 412)".

        Design: Corner/cross_cutting_layers/agreement_amend_with_stale_version_rejected_412
        """
        set_clock()
        plant = create_plant()
        customer = create_customer()
        agreement = create_active_agreement(plant["id"], customer["id"])
        planner = make_customer_planner_headers(customer["id"])
        reneg = validate_success(
            api.open_renegotiation(agreement["id"], planner))
        assert reneg["version"] == 3
        stale = api.amend_agreement(
            agreement["id"], {"expected_agreement_version": reneg["version"] - 1,
                              "conversion_cost_cents_per_1000": 1600}, manager())
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION, 412)
        current = get_agreement(agreement["id"])
        assert current["status"] == "RENEGOTIATING"
        assert current["conversion_cost_cents_per_1000"] == 1500
        amended = validate_success(api.amend_agreement(
            agreement["id"],
            {"expected_agreement_version": reneg["version"],
             "conversion_cost_cents_per_1000": 1600}, manager()))
        assert amended["status"] == "ACTIVE"
        assert amended["version"] == 4
        assert amended["conversion_cost_cents_per_1000"] == 1600


class TestRunCreateOcc:
    def test_run_create_with_stale_agreement_version_rejected_412(self, api):
        """PRD §2.9: "A `POST /supply-agreements/{id}/production-runs` request
        must likewise carry `expected_agreement_version` matching the
        agreement's current `version`; a mismatch is rejected with
        `ERR_STALE_VERSION` (HTTP 412)" and "creating a production run itself
        increments the parent agreement's `version` by 1".

        Design: Corner/cross_cutting_layers/run_create_with_stale_agreement_version_rejected_412
        """
        set_clock()
        plant = create_plant()
        customer = create_customer()
        agreement = create_active_agreement(plant["id"], customer["id"])
        line = create_line(plant["id"])
        fmt = create_qualified_format(plant["id"], customer["id"])
        v2 = agreement["version"]
        first = create_run(agreement["id"], line["id"], fmt["id"],
                           expected_version=v2)
        assert first["status"] == "SCHEDULED"
        assert get_agreement(agreement["id"])["version"] == v2 + 1
        resp = api.create_run(
            agreement["id"],
            {"line_id": line["id"], "format_id": fmt["id"],
             "scheduled_qty": 60000, "graphics_code": "G1",
             "window_start": "2026-09-11T08:00:00Z",
             "window_end": "2026-09-11T16:00:00Z",
             "expected_agreement_version": v2},
            scheduler())
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)
        rows, _ = validate_paginated(
            api.list_runs(manager(), params={"agreement_id": agreement["id"]}))
        assert len(rows) == 1
