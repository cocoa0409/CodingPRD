"""Operator identity: authentication, role authorization, provider scoping and
segregation of duties."""
import pytest

from test_helpers import (
    ApiErrorId,
    UNKNOWN_UUIDS,
    claim_line_payload,
    create_claim_payload,
    get_claim,
    get_events,
    lines_by_number,
    make_headers,
    make_provider_rep_headers,
    override_claim,
    set_clock,
    setup_imaging_environment,
    setup_pended_auth_missing_claim,
    submit_claim,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import CLAIMS_EXAMINER, CLAIMS_INTAKE, NETWORK_MANAGER, create_provider


class TestRoleAuthorization:
    def test_a_network_manager_is_denied_every_claim_read(self, api):
        """PRD §2.1: "A `NetworkManager` is deliberately denied read access to claims,
        service lines, remittance advices and adjudication events; those requests are
        rejected with `ERR_FORBIDDEN_ROLE`."

        Design: Corner/rbac/network_manager_cannot_read_claims_and_gets_forbidden_role
        """
        env = setup_imaging_environment(
            plan_overrides={"plan_code": "RB-1", "name": "RBAC Plan One"},
            provider_overrides={"npi": "5000000001", "name": "RB1 Clinic"},
            member_overrides={"member_number": "M-RB-1"},
        )
        submit_claim(
            env["member"]["id"],
            env["provider"]["id"],
            [claim_line_payload(1, "73721", 1, 60000, "2026-02-10")],
            "CLM-RB-1",
        )
        validate_error(
            api.list_claims(NETWORK_MANAGER, params={"member_id": env["member"]["id"]}),
            ApiErrorId.ERR_FORBIDDEN_ROLE.value,
            expected_status=403,
        )
        _rows, meta = validate_paginated(
            api.list_claims(CLAIMS_EXAMINER, params={"member_id": env["member"]["id"]})
        )
        assert meta["total_count"] == 1, "The same read succeeds for an examiner"

    def test_a_claims_intake_operator_cannot_run_an_adjudication_pass(self, api):
        """PRD §2.1: "A **`ClaimsExaminer`** owns the adjudication desk. Exclusively, a
        `ClaimsExaminer` runs adjudication passes, finalizes claims into remittances, voids
        finalized claims and creates adjustment claims."
        PRD §2.1: "Once the caller is authenticated, the engine confirms that the named role
        appears in the authorized-role list for the requested endpoint (see §4); a role that
        is authenticated but not authorized receives `ERR_FORBIDDEN_ROLE` and HTTP 403."

        Design: Corner/rbac/claims_intake_cannot_run_adjudication_and_gets_forbidden_role
        """
        env = setup_imaging_environment(
            plan_overrides={"plan_code": "RB-2", "name": "RBAC Plan Two"},
            provider_overrides={"npi": "5000000002", "name": "RB2 Clinic"},
            member_overrides={"member_number": "M-RB-2"},
        )
        claim = submit_claim(
            env["member"]["id"],
            env["provider"]["id"],
            [claim_line_payload(1, "73721", 1, 60000, "2026-02-10")],
            "CLM-RB-2",
        )
        validate_error(
            api.adjudicate_claim(claim["id"], CLAIMS_INTAKE),
            ApiErrorId.ERR_FORBIDDEN_ROLE.value,
            expected_status=403,
        )
        after = get_claim(claim["id"])
        assert after["status"] == "RECEIVED"
        assert after["adjudication_pass"] == 0


class TestAuthentication:
    def test_an_unrecognised_role_header_is_rejected_before_anything_else(self, api):
        """PRD §2.1: "Every request to the API — without exception, including reads — must
        carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`,
        naming the authority under which the principal acts. If either header is absent, or
        if `X-User-Role` carries a value outside the seven roles enumerated below, the
        request is rejected with `ERR_UNAUTHENTICATED` and HTTP 401. This check precedes
        every other check in the system."

        Design: Corner/rbac/request_with_an_unrecognised_role_header_returns_unauthenticated
        """
        set_clock()
        unknown_role = make_headers("u-unknown-1", "UnknownRole")
        validate_error(
            api.get_claim(UNKNOWN_UUIDS[9], unknown_role),
            ApiErrorId.ERR_UNAUTHENTICATED.value,
            expected_status=401,
        )
        validate_error(
            api.get_claim(UNKNOWN_UUIDS[9], {"X-User-ID": "u-unknown-1"}),
            ApiErrorId.ERR_UNAUTHENTICATED.value,
            expected_status=401,
        )


class TestProviderScoping:
    def test_a_provider_rep_cannot_read_another_providers_claim(self, api):
        """PRD §2.1: "A `ProviderRep` that submits a claim must supply a `provider_id` equal
        to its own `X-User-ID`, and a `ProviderRep` that reads a claim, a list of claims, a
        list of service lines, a claim's remittance advices, or a claim's adjudication events
        may only reach rows whose owning claim has a `provider_id` equal to its `X-User-ID`.
        A violation of either rule is rejected with `ERR_PROVIDER_SCOPE_VIOLATION` and HTTP
        403."
        PRD §2.1: "The seventh role is different: when `X-User-Role` is `ProviderRep`,
        `X-User-ID` is the `id` of the acting `Provider`, and ownership checks on any
        claim-side resource compare the claim's `provider_id` to `X-User-ID`."

        Design: Corner/rbac/provider_rep_cannot_read_another_providers_claim
        """
        env = setup_imaging_environment(
            plan_overrides={"plan_code": "RB-4", "name": "RBAC Plan Four"},
            provider_overrides={"npi": "5000000004", "name": "RB4 Alpha"},
            member_overrides={"member_number": "M-RB-4"},
        )
        other_provider = create_provider(npi="5000000005", name="RB4 Beta")
        claim = submit_claim(
            env["member"]["id"],
            other_provider["id"],
            [claim_line_payload(1, "73721", 1, 60000, "2026-02-10")],
            "CLM-RB-4",
        )

        validate_error(
            api.get_claim(claim["id"], make_provider_rep_headers(env["provider"]["id"])),
            ApiErrorId.ERR_PROVIDER_SCOPE_VIOLATION.value,
            expected_status=403,
        )
        owned = validate_success(
            api.get_claim(claim["id"], make_provider_rep_headers(other_provider["id"]))
        )
        assert owned["id"] == claim["id"], "The billing provider's own rep may read it"

    def test_a_provider_rep_may_submit_a_claim_for_its_own_provider_id(self, api):
        """PRD §3.4: "Claims arrive from two directions — a `ClaimsIntake` operator keying an
        837 transaction on a provider's behalf, or a `ProviderRep` submitting for itself —
        and both take the same shape."
        PRD §2.1: "A `ProviderRep` that submits a claim must supply a `provider_id` equal to
        its own `X-User-ID`, and a `ProviderRep` that reads a claim, a list of claims, a list
        of service lines, a claim's remittance advices, or a claim's adjudication events may
        only reach rows whose owning claim has a `provider_id` equal to its `X-User-ID`. A
        violation of either rule is rejected with `ERR_PROVIDER_SCOPE_VIOLATION` and HTTP
        403."

        Design: Corner/rbac/provider_rep_may_submit_a_claim_for_its_own_provider_id
        """
        env = setup_imaging_environment(
            plan_overrides={"plan_code": "RB-5", "name": "RBAC Plan Five"},
            provider_overrides={"npi": "5000000006", "name": "RB5 Clinic"},
            member_overrides={"member_number": "M-RB-5"},
        )
        payload = create_claim_payload(
            env["member"]["id"],
            env["provider"]["id"],
            [claim_line_payload(1, "73721", 1, 60000, "2026-02-10")],
            claim_number="CLM-RB-5",
        )
        claim = validate_success(
            api.create_claim(payload, make_provider_rep_headers(env["provider"]["id"])), 201
        )
        assert claim["status"] == "RECEIVED"
        assert claim["provider_id"] == env["provider"]["id"]


class TestSegregationOfDuties:
    def test_a_director_other_than_the_examiner_may_release_the_pend(self, api):
        """PRD §3.8: "Only a `MedicalDirector` may issue one, only against a claim whose
        `status` is `PENDED` — any other status is refused with `ERR_CLAIM_NOT_PENDED` — and
        only when the acting `X-User-ID` differs from the claim's
        `last_adjudicated_by_user_id`; a director attempting to release a pend they
        themselves produced is refused with `ERR_SEGREGATION_OF_DUTIES` and HTTP 403."
        PRD §3.9: "An event records the `claim_id` it belongs to, the `pass_number` — the
        claim's `adjudication_pass` at the moment of appending — an `event_type` drawn from
        `INTAKE`, `DUPLICATE_REJECT`, `ADJUDICATE`, `OVERRIDE`, `FINALIZE`, `VOID`, `ADJUST`,
        `COB_POST` and `ELIG_REPEND`, the claim's `from_status` before the event and
        `to_status` after it, the `reason_code` the event stamped (whether a
        `pend_reason_code` or a `deny_reason_code`, and null when the event stamped neither),
        the `actor_role` which is the caller's `X-User-Role` or the literal `system` for
        automatic transitions, the `actor_user_id` which is the caller's `X-User-ID` or null
        for automatic transitions, and `occurred_at` stamped from the logical clock."

        Design: Corner/rbac/medical_director_with_a_different_user_id_releases_a_pended_claim
        """
        env = setup_pended_auth_missing_claim(
            examiner_user_id="u-examiner-6", claim_number="CLM-RB-6"
        )
        assert env["claim"]["status"] == "PENDED"
        assert env["claim"]["pend_reason_code"] == "PEND_AUTH_MISSING"

        released = override_claim(env["claim"]["id"], "APPROVE", user_id="u-md-6")
        assert released["status"] == "ADJUDICATED"
        assert released["pend_reason_code"] is None
        assert released["total_allowed_cents"] == 40000

        line = lines_by_number(env["claim"]["id"])[1]
        assert line["line_status"] == "PRICED"
        assert line["authorization_id"] is None, (
            "The relaxed selector found no grant at all, so nothing is consumed"
        )

        override_events = [
            event for event in get_events(env["claim"]["id"]) if event["event_type"] == "OVERRIDE"
        ]
        assert len(override_events) == 1
        assert override_events[0]["actor_user_id"] == "u-md-6"
