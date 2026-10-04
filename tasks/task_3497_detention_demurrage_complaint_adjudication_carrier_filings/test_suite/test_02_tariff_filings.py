"""Tariff filings: parent-path existence, notice periods, publication windows,
and the carrier-version optimistic concurrency guard."""
from test_helpers import (
    MISSING_UUID,
    TEST_USERS,
    ApiErrorId,
    api_client,
    assert_tariff,
    create_tariff_payload,
    file_tariff,
    get_carrier_version,
    make_carrier_rep_headers,
    publish_tariff,
    set_logical_clock,
    setup_carrier_shipper,
    setup_published_tariff,
    validate_error,
    validate_paginated,
    validate_success,
)

DOCKET = TEST_USERS["docket_headers"]


class TestTariffCreation:
    def test_tariff_create_under_unknown_carrier_returns_carrier_not_found(self):
        """PRD §2.8: "The server validates path identifiers strictly left to
        right — the carrier first, then the tariff, license, invoice, dispute,
        complaint, proceeding, or agreement beneath it — and rejects the request
        with the not-found error for the first identifier that fails to resolve,
        without consulting later segments."

        Design: Corner/entities/tariff_create_under_unknown_carrier_returns_carrier_not_found
        """
        env = setup_carrier_shipper()
        payload = create_tariff_payload(env["carrier"]["version"],
                                        tariff_code="DD-NOPE-1")
        resp = api_client.create_tariff(MISSING_UUID, payload,
                                        make_carrier_rep_headers(MISSING_UUID))
        validate_error(resp, ApiErrorId.ERR_CARRIER_NOT_FOUND)

    def test_tariff_increase_notice_29_days_rejected_30_exact_accepted(self):
        """PRD §3.2: "An `INCREASE` requires thirty days of notice; a `NEW` or
        `DECREASE` filing requires one day. The server derives `notice_period_days`
        from the `change_type` accordingly and rejects a filing whose
        `effective_date` falls earlier than `filed_at` plus the applicable notice
        period with `ERR_EFFECTIVE_DATE_NOTICE_SHORT` (HTTP 422)."

        Design: Corner/validations/tariff_increase_notice_29_days_rejected_30_exact_accepted
        """
        env = setup_carrier_shipper()
        carrier = env["carrier"]
        rep = make_carrier_rep_headers(carrier["id"])
        v0 = carrier["version"]

        r1 = api_client.create_tariff(carrier["id"], create_tariff_payload(
            v0, tariff_code="DD-INC-1", change_type="INCREASE",
            per_diem_rate_cents=6000, effective_date="2026-09-30T00:00:00Z"), rep)
        validate_error(r1, ApiErrorId.ERR_EFFECTIVE_DATE_NOTICE_SHORT)
        assert get_carrier_version(carrier["id"]) == v0, (
            "a rejected filing must not advance the carrier's version")

        r2 = api_client.create_tariff(carrier["id"], create_tariff_payload(
            v0, tariff_code="DD-INC-2", change_type="INCREASE",
            per_diem_rate_cents=6000, effective_date="2026-10-01T00:00:00Z"), rep)
        data = validate_success(r2, 201)
        assert_tariff(data)
        assert data["notice_period_days"] == 30
        assert data["publication_status"] == "DRAFT"


class TestTariffPublication:
    def test_tariff_publish_happy_path_sets_published_immediately(self):
        """PRD §3.2: "A successful publication moves `publication_status` to
        `PUBLISHED`, where the tariff remains unless the enforcement cascade of
        §2.10 suspends it. A carrier's catalogue of tariff publications is
        listable by every role."

        Design: Corner/state_machines/tariff_publish_happy_path_sets_published_immediately
        """
        env = setup_carrier_shipper()
        carrier = env["carrier"]
        tariff = file_tariff(carrier["id"], tariff_code="DD-COR-1")
        set_logical_clock("2026-09-03T00:00:00Z")
        data = validate_success(api_client.publish_tariff(
            tariff["id"], make_carrier_rep_headers(carrier["id"])), 200)
        assert data["publication_status"] == "PUBLISHED"

        rows, _meta = validate_paginated(api_client.list_tariffs(carrier["id"], DOCKET))
        assert len(rows) == 1
        assert rows[0]["id"] == tariff["id"]
        assert rows[0]["publication_status"] == "PUBLISHED"

    def test_tariff_publish_twice_returns_not_in_draft(self):
        """PRD §3.2: "the tariff must stand in `DRAFT`, otherwise
        `ERR_TARIFF_NOT_IN_DRAFT` (HTTP 409)".

        Design: Corner/state_machines/tariff_publish_twice_returns_not_in_draft
        """
        env = setup_published_tariff()
        carrier = env["carrier"]
        tariff = env["tariff"]
        resp = api_client.publish_tariff(tariff["id"],
                                         make_carrier_rep_headers(carrier["id"]))
        validate_error(resp, ApiErrorId.ERR_TARIFF_NOT_IN_DRAFT)
        rows, _meta = validate_paginated(api_client.list_tariffs(carrier["id"], DOCKET))
        assert len(rows) == 1
        assert rows[0]["publication_status"] == "PUBLISHED"

    def test_publish_before_effective_date_rejected_at_effective_accepted(self):
        """PRD §3.2: "the logical clock must have reached the tariff's
        `effective_date`, otherwise `ERR_PUBLISH_WINDOW_NOT_REACHED` (HTTP 422)."

        Design: Corner/validations/publish_before_effective_date_rejected_at_effective_accepted
        """
        env = setup_carrier_shipper()
        carrier = env["carrier"]
        rep = make_carrier_rep_headers(carrier["id"])
        tariff = file_tariff(carrier["id"], tariff_code="DD-PUB-1",
                             effective_date="2026-09-10T00:00:00Z")

        set_logical_clock("2026-09-09T23:59:59Z")
        r1 = api_client.publish_tariff(tariff["id"], rep)
        validate_error(r1, ApiErrorId.ERR_PUBLISH_WINDOW_NOT_REACHED)
        rows, _ = validate_paginated(api_client.list_tariffs(carrier["id"], DOCKET))
        assert rows[0]["publication_status"] == "DRAFT"

        set_logical_clock("2026-09-10T00:00:00Z")
        data = validate_success(api_client.publish_tariff(tariff["id"], rep), 200)
        assert data["publication_status"] == "PUBLISHED"


class TestTariffFilingOcc:
    def test_tariff_filing_stale_carrier_version_returns_412(self):
        """PRD §2.9: "Filing a tariff publication against a carrier requires the
        request to carry `expected_carrier_version`, the caller's last observed
        `version` of that carrier; when another write — a sibling filing, or an
        enforcement-driven suspension — has advanced the carrier's version since
        the caller last read it, the filing is rejected with `ERR_STALE_VERSION`
        (HTTP 412), and the filer must re-observe the carrier before filing."
        PRD §2.9: "Both guarded writes increment the parent resource's `version`
        by one on success".

        Design: Corner/complexity_layers/tariff_filing_stale_carrier_version_returns_412
        """
        env = setup_carrier_shipper()
        carrier = env["carrier"]
        rep = make_carrier_rep_headers(carrier["id"])
        v0 = carrier["version"]

        d1 = validate_success(api_client.create_tariff(carrier["id"],
            create_tariff_payload(v0, tariff_code="DD-OCC-1"), rep), 201)
        assert d1["tariff_code"] == "DD-OCC-1"
        v1 = get_carrier_version(carrier["id"])
        assert v1 == v0 + 1, "a successful filing advances the carrier version by one"

        r2 = api_client.create_tariff(carrier["id"], create_tariff_payload(
            v0, tariff_code="DD-OCC-2", free_time_days=3,
            per_diem_rate_cents=6000), rep)
        validate_error(r2, ApiErrorId.ERR_STALE_VERSION)
        rows, _meta = validate_paginated(api_client.list_tariffs(carrier["id"], DOCKET))
        assert [t["tariff_code"] for t in rows] == ["DD-OCC-1"], (
            "the stale filing stored nothing")

        v_now = get_carrier_version(carrier["id"])
        d3 = validate_success(api_client.create_tariff(carrier["id"],
            create_tariff_payload(v_now, tariff_code="DD-OCC-3", free_time_days=3,
                                  per_diem_rate_cents=6000), rep), 201)
        assert d3["tariff_code"] == "DD-OCC-3"
        assert get_carrier_version(carrier["id"]) == v_now + 1
