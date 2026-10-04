"""Breadth tests: endpoint surface — sub-resource listing, the error envelope,
and optimistic concurrency on record ingest."""

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    get_vehicle,
    make_network_admin_headers,
    make_source_operator_headers,
    register_source,
    setup_network,
    setup_network_with_source,
    submit_inspection,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestSourceRecordsSubresource:
    def test_source_records_list_contains_submissions(self, api, admin_headers):
        """PRD §3.1: "each source exposes the list of records it has submitted, filterable by `status`."

        Design: Corner/endpoints/fk_reverse_reachability_source_records
        """
        network, source = setup_network_with_source(api)
        submit_inspection(api, source["id"], "1HGCM82633A004352", 100, idempotency_key="k-i1", payload_ref="i1")
        submit_inspection(api, source["id"], "2HGCM82633A004352", 200, idempotency_key="k-i2", payload_ref="i2")
        resp = api.list_source_records(source["id"], admin_headers)
        data, meta = validate_paginated(resp)
        assert meta["total_count"] == 2, f"source submitted 2 records, got {meta['total_count']}"
        assert {r["vin"] for r in data} == {"1HGCM82633A004352", "2HGCM82633A004352"}


class TestErrorEnvelopeShape:
    def test_error_response_carries_declared_envelope(self, api, admin_headers):
        """PRD §2.2: "All error API responses (4xx status codes) follow this standard envelope format" with "`response_type`: "error"" and a `data` object carrying "`error_id`" and "`message`".

        Design: Corner/endpoints/response_envelope_shape_on_error
        """
        setup_network(api)
        resp = api.get_vehicle(NON_EXISTENT_UUID, admin_headers)
        body = resp.json()
        assert resp.status_code == 404
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == "ERR_NOT_FOUND"
        assert isinstance(body["data"]["message"], str) and body["data"]["message"]
        assert body["meta"]["api_request_id"], "error meta must carry api_request_id"


class TestOccOnRecordIngest:
    def test_stale_expected_vehicle_version_rejected_current_accepted(self, api, admin_headers):
        """PRD §2.8: "Submitting a history record against a vehicle requires the request to carry `expected_vehicle_version`, the client last-observed `version` of the target `Vehicle`. If the vehicle's current `version` differs — because rollup recomputation on any record ingest, withdrawal, or supersession bumps it — the submission is rejected with `ERR_STALE_VERSION` (HTTP 412), forcing the client to re-read before writing."

        Design: Corner/endpoints/occ_stale_version_on_record_ingest
        """
        network, source = setup_network_with_source(api)
        first = submit_inspection(api, source["id"], "1HGCM82633A004352", 100)
        vehicle_id = first["vehicle_id"]
        observed_version = get_vehicle(api, vehicle_id)["version"]

        ok = api.create_record(
            {
                "vin": "1HGCM82633A004352",
                "source_id": source["id"],
                "record_type": "ACCIDENT",
                "event_date": "2026-09-01",
                "damage_severity": 3,
                "payload_ref": "a1",
                "idempotency_key": "k-a1",
                "expected_vehicle_version": observed_version,
            },
            make_source_operator_headers(source["id"]),
        )
        validate_success(ok, expected_status=201)
        assert get_vehicle(api, vehicle_id)["version"] == observed_version + 1, (
            "ingest recomputes rollups and increments the vehicle version"
        )

        stale = api.create_record(
            {
                "vin": "1HGCM82633A004352",
                "source_id": source["id"],
                "record_type": "ACCIDENT",
                "event_date": "2026-09-01",
                "damage_severity": 4,
                "payload_ref": "a2",
                "idempotency_key": "k-a2",
                "expected_vehicle_version": observed_version,
            },
            make_source_operator_headers(source["id"]),
        )
        validate_error(stale, ApiErrorId.STALE_VERSION)
