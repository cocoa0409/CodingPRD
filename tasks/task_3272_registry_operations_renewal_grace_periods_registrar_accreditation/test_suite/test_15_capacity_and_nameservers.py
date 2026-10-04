"""Capacity summary and nameserver tests (PRD §3.4)."""
from test_helpers import (
    ApiErrorId,
    get_success_data,
    make_admin_headers,
    make_operator_headers,
    setup_active_domain,
    validate_error,
    validate_success,
)


class TestCapacitySummary:
    def test_aggregates_and_flags_below_commitment(self, api):
        """PRD §3.4: "The registry's resolution-infrastructure commitment is
        observable through a capacity summary: `provisioned_qps` is the sum of
        `capacity_qps` across all nameservers (nameservers are never
        soft-deleted, so the sum covers every row), `commitment_qps` is the
        contracted commitment of 8,000 queries per second,
        `utilization_ratio` is the exact unrounded decimal ratio of
        provisioned to committed capacity, and the reported `status` is `OK`
        when the ratio is at least 1.0 and `BELOW_COMMITMENT` otherwise."

        Design: Corner/calculations/capacity_summary_aggregates_and_flags_below_commitment
        """
        for hostname, ip, qps in (
            ("ns1.alpha.example", "192.0.2.10", 3000),
            ("ns2.alpha.example", "192.0.2.11", 4000),
        ):
            resp = api.create_nameserver(
                {"hostname": hostname, "ip_addresses": [ip],
                 "capacity_qps": qps},
                make_admin_headers(),
            )
            get_success_data(resp, expected_status=201)

        resp = api.get_capacity_summary(make_admin_headers())
        summary = validate_success(resp)
        assert summary["provisioned_qps"] == 7000
        assert summary["commitment_qps"] == 8000
        assert summary["utilization_ratio"] == 0.875
        assert summary["status"] == "BELOW_COMMITMENT"

        resp = api.create_nameserver(
            {"hostname": "ns3.alpha.example", "ip_addresses": ["192.0.2.12"],
             "capacity_qps": 2000},
            make_admin_headers(),
        )
        get_success_data(resp, expected_status=201)

        resp = api.get_capacity_summary(make_admin_headers())
        summary = validate_success(resp)
        assert summary["provisioned_qps"] == 9000
        assert summary["utilization_ratio"] == 1.125
        assert summary["status"] == "OK"

    def test_ok_boundary_at_exactly_1_0(self, api):
        """PRD §3.4: "the reported `status` is `OK` when the ratio is at
        least 1.0 and `BELOW_COMMITMENT` otherwise."
        PRD §3.4: "`commitment_qps` is the contracted commitment of 8,000
        queries per second".

        Design: Corner/calculations/capacity_summary_aggregates_and_flags_below_commitment
        """
        for i, qps in enumerate((3000, 3000, 2000)):
            resp = api.create_nameserver(
                {"hostname": f"ns-boundary-{i}.example",
                 "ip_addresses": [f"192.0.2.{20 + i}"], "capacity_qps": qps},
                make_admin_headers(),
            )
            get_success_data(resp, expected_status=201)

        resp = api.get_capacity_summary(make_admin_headers())
        summary = validate_success(resp)
        assert summary["provisioned_qps"] == 8000
        assert summary["utilization_ratio"] == 1.0
        assert summary["status"] == "OK"


class TestNameserverCapacityFloor:
    def test_below_minimum_rejected_at_boundary(self, api):
        """PRD §3.4: "Every individual nameserver must provision at least
        2,000 queries per second; anything less is rejected with
        `ERR_CAPACITY_BELOW_MINIMUM`."

        Design: Corner/calculations/nameserver_below_minimum_capacity_rejected
        """
        resp = api.create_nameserver(
            {"hostname": "ns-weak.example", "ip_addresses": ["198.51.100.1"],
             "capacity_qps": 1999},
            make_admin_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_CAPACITY_BELOW_MINIMUM)

        resp = api.create_nameserver(
            {"hostname": "ns-floor.example", "ip_addresses": ["198.51.100.2"],
             "capacity_qps": 2000},
            make_admin_headers(),
        )
        get_success_data(resp, expected_status=201)

    def test_one_above_minimum_accepted(self, api):
        """PRD §3.4: "Every individual nameserver must provision at least
        2,000 queries per second; anything less is rejected with
        `ERR_CAPACITY_BELOW_MINIMUM`."

        Design: Corner/calculations/nameserver_below_minimum_capacity_rejected
        """
        resp = api.create_nameserver(
            {"hostname": "ns-below.example", "ip_addresses": ["198.51.100.3"],
             "capacity_qps": 1},
            make_admin_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_CAPACITY_BELOW_MINIMUM)

        resp = api.create_nameserver(
            {"hostname": "ns-above.example", "ip_addresses": ["198.51.100.4"],
             "capacity_qps": 2001},
            make_admin_headers(),
        )
        get_success_data(resp, expected_status=201)


class TestNameserverDeletion:
    def test_delete_blocked_while_linked(self, api):
        """PRD §3.4: "A nameserver still referenced by any non-`DELETED`
        domain cannot be deleted — the attempt fails with
        `ERR_NAMESERVER_IN_USE`."

        Design: Corner/endpoints/nameserver_delete_blocked_while_linked
        """
        registrar, _schedule, domain = setup_active_domain(
            clock="2027-04-01T00:00:00Z", name="ns-domain")
        resp = api.create_nameserver(
            {"hostname": "ns1.ns-domain.example",
             "ip_addresses": ["203.0.113.5"], "capacity_qps": 2500},
            make_admin_headers(),
        )
        nameserver = get_success_data(resp, expected_status=201)
        resp = api.link_nameserver(
            domain["id"], nameserver["id"],
            make_operator_headers(registrar["id"]),
        )
        get_success_data(resp, expected_status=201)

        resp = api.delete_nameserver(nameserver["id"], make_admin_headers())
        validate_error(resp, ApiErrorId.ERR_NAMESERVER_IN_USE)

        resp = api.get_nameserver(nameserver["id"], make_admin_headers())
        still_there = get_success_data(resp)
        assert still_there["id"] == nameserver["id"]

    def test_delete_unlinked_nameserver_succeeds(self, api):
        """PRD §3.4: "A nameserver still referenced by any non-`DELETED`
        domain cannot be deleted — the attempt fails with
        `ERR_NAMESERVER_IN_USE`."
        PRD §4: "The nameserver deletion endpoint returns `204 No Content`
        with no response body."

        Design: Corner/endpoints/nameserver_delete_blocked_while_linked
        """
        resp = api.create_nameserver(
            {"hostname": "ns-free.example", "ip_addresses": ["203.0.113.9"],
             "capacity_qps": 2500},
            make_admin_headers(),
        )
        nameserver = get_success_data(resp, expected_status=201)

        resp = api.delete_nameserver(nameserver["id"], make_admin_headers())
        assert resp.status_code == 204

        resp = api.get_nameserver(nameserver["id"], make_admin_headers())
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
