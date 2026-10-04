"""Resource shapes: creation, defaults, identity, retrieval, listing.

These tests pin the envelope and the server-managed fields the PRD grants
every caller: status at birth, version at one, and round-trippable storage.
"""

from test_helpers import factories as f
from test_helpers.api_client import same_instant
from test_helpers.api_errors import ERR_INVALID_REQUEST, ERR_PLAN_NOT_FOUND
from test_helpers.assertions import (
    assert_claim_attachment,
    get_success_data,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import (
    CLAIM_ADJUDICATED,
    PLAN_DRAFT,
    PROVIDER_ACTIVE,
    SCHEDULE_PENDING,
)
from test_helpers.fixtures import (
    adjudicated_claim,
    claim_lines,
    read_claim,
    set_clock,
    standard_stack,
    standard_stack_attachment_required,
    upload_attachment,
)
from test_helpers.test_users import ADMIN, EXAMINER, NETWORK, make_provider_headers


class TestPlanCreationShape:
    def test_plan_create_returns_declared_fields_with_draft_status(self, client):
        """A new plan is born DRAFT at version 1 with server-minted fields.

        PRD 3.1: "A plan is born in `DRAFT`. Activation by a `PlanAdmin`
        moves it `DRAFT → ACTIVE`, which requires all monetary and
        coinsurance fields to be present and non-negative and that no other
        `ACTIVE` plan carries the same `plan_code`; only an `ACTIVE` plan is
        referenceable when enrolling subscribers."
        PRD 2.4: "The `id` is a server-minted UUID string with no type
        prefix. `created_at` records the creation instant as an ISO 8601 UTC
        timestamp with three fractional digits. `updated_at` is refreshed on
        every mutation. `version` is an integer starting at 1 that increments
        on every mutation and underpins optimistic concurrency control."

        Design: Corner/entities/plan_create_returns_declared_fields_with_draft_status
        """
        set_clock(client, "2026-01-01T00:00:00Z")

        resp = client.create_plan(
            f.create_plan_payload(plan_code="DD-STD"), headers=ADMIN
        )

        data = validate_success(resp, expected_status=201)
        assert data["plan_code"] == "DD-STD"
        assert data["annual_maximum_cents"] == 150000
        assert data["status"] == PLAN_DRAFT
        assert data["version"] == 1
        assert is_valid_uuid(data["id"])
        assert data.get("created_at") and data.get("updated_at")


class TestProviderCreationDefaults:
    def test_provider_create_defaults_status_active(self, client):
        """A provider is ACTIVE from creation at version 1.

        PRD 3.2: "A provider is `ACTIVE` from creation and remains so until
        terminated."
        PRD 2.4: "`version` is an integer starting at 1 that increments on
        every mutation and underpins optimistic concurrency control."

        Design: Corner/entities/provider_create_defaults_status_active
        """
        set_clock(client, "2026-01-01T00:00:00Z")

        resp = client.create_provider(f.create_provider_payload(), headers=NETWORK)

        data = validate_success(resp, expected_status=201)
        assert data["status"] == PROVIDER_ACTIVE
        assert data["version"] == 1
        assert data["tier"] == "PPO"


class TestClaimAttachmentIsImmutable:
    def test_claim_attachment_carries_no_version_field(self, client):
        """Attachments record id and created_at — no updated_at, no version.

        PRD 2.4: "One resource deviates from this convention:
        `ClaimAttachment` records only `id` and `created_at` — it has no
        `updated_at` and no `version`, because attachments are immutable once
        uploaded; the server stamps the upload instant on the attachment
        itself as `transmitted_on`."

        Design: Corner/entities/claim_attachment_is_immutable_no_version_field
        """
        stack = standard_stack_attachment_required(client)
        resp = client.create_claim(
            f.create_claim_payload(
                stack["subscriber"]["id"],
                stack["provider"]["id"],
                lines=[
                    f.claim_line_payload(
                        cdt_code="D2740", tooth_number="14",
                        submitted_amount_cents=9000,
                    )
                ],
            ),
            headers=make_provider_headers(stack["provider"]["id"]),
        )
        claim = get_success_data(resp)
        line_id = claim_lines(client, claim["id"])[0]["id"]

        resp = client.create_claim_attachment(
            claim["id"],
            f.create_attachment_payload(
                line_id, attachment_kind="RADIOGRAPH", blob_ref="blob://xray-14"
            ),
            headers=make_provider_headers(stack["provider"]["id"]),
        )

        data = validate_success(resp, expected_status=201)
        assert_claim_attachment(data)
        assert data["attachment_kind"] == "RADIOGRAPH"
        assert data["blob_ref"] == "blob://xray-14"


class TestFeeScheduleRetrieval:
    def test_fee_schedule_get_returns_stored_window(self, client):
        """Every posted field round-trips, including a null effective_to.

        PRD 2.8: "each schedule declares `effective_from` and an optional
        `effective_to` (null meaning open-ended), and a schedule applies to
        work whose anchor date falls on or after `effective_from` and
        strictly before `effective_to`."
        PRD 3.2: "A new schedule is `PENDING` until a `NetworkManager`
        activates it; activation applies the overlap and truncation rules of
        §2.8 and triggers the predetermination recomputation cascade
        described in §3.4."

        Design: Corner/entities/fee_schedule_get_returns_stored_window
        """
        set_clock(client, "2026-01-01T00:00:00Z")
        schedule = get_success_data(
            client.create_fee_schedule(
                f.create_fee_schedule_payload(
                    tier="PREMIER",
                    entries=[
                        f.fee_schedule_entry_payload(
                            cdt_code="D0120", allowed_cents=7000
                        )
                    ],
                ),
                headers=NETWORK,
            )
        )
        assert schedule["status"] == SCHEDULE_PENDING

        resp = client.get_fee_schedule(schedule["id"], headers=NETWORK)
        data = validate_success(resp)
        assert data["tier"] == "PREMIER"
        assert same_instant(data["effective_from"], "2026-01-01T00:00:00Z")
        assert data["effective_to"] is None
        assert data["status"] == SCHEDULE_PENDING


class TestClaimsListingPagination:
    def test_claims_list_paginates_with_total_count_and_has_more(self, client):
        """limit/offset page over the full filtered set.

        PRD 2.3: "List endpoints accept two query parameters. The `limit`
        parameter caps the number of items returned; it defaults to 10 when
        omitted, accepts a minimum of 1, and is capped at a maximum of 100.
        The `offset` parameter skips a number of items from the start of the
        result set and defaults to 0. List responses are always sorted by
        `created_at` in ascending order unless otherwise specified. The
        `meta` object of a list response carries four pagination fields:
        `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/claims_list_paginates_with_total_count_and_has_more
        """
        stack = standard_stack(client)
        for service, received in (
            ("2026-02-01T00:00:00Z", "2026-02-02T00:00:00Z"),
            ("2026-03-01T00:00:00Z", "2026-03-02T00:00:00Z"),
            ("2026-04-01T00:00:00Z", "2026-04-02T00:00:00Z"),
        ):
            adjudicated_claim(
                client, stack, service_date=service, received_date=received
            )

        data, meta = validate_paginated(
            client.list_claims(
                headers=EXAMINER,
                params={"subscriber_id": stack["subscriber"]["id"], "limit": 2, "offset": 0},
            )
        )
        assert len(data) == 2
        assert meta["total_count"] == 3
        assert meta["has_more"] is True

        data, meta = validate_paginated(
            client.list_claims(
                headers=EXAMINER,
                params={"subscriber_id": stack["subscriber"]["id"], "limit": 2, "offset": 2},
            )
        )
        assert len(data) == 1
        assert meta["total_count"] == 3
        assert meta["has_more"] is False

        data, meta = validate_paginated(
            client.list_claims(
                headers=EXAMINER, params={"subscriber_id": stack["subscriber"]["id"]}
            )
        )
        assert len(data) == 3
        assert meta["limit"] == 10
        assert meta["offset"] == 0


class TestTypedNotFound:
    def test_plan_get_unknown_id_returns_plan_not_found(self, client):
        """An unallocated plan id surfaces the typed 404.

        PRD 2.10: "Next, path-parameter identifiers are resolved left to
        right — each entity type surfaces its own dedicated 404 code:
        `ERR_PLAN_NOT_FOUND`, `ERR_PROVIDER_NOT_FOUND`,
        `ERR_SUBSCRIBER_NOT_FOUND`, `ERR_DEPENDENT_NOT_FOUND`,
        `ERR_CLAIM_NOT_FOUND`, `ERR_PREDETERMINATION_NOT_FOUND`, or
        `ERR_FEE_SCHEDULE_NOT_FOUND` — and a request targeting a nested path
        is rejected at the first identifier that does not resolve, before
        deeper segments are examined."

        Design: Corner/entities/plan_get_unknown_id_returns_plan_not_found
        """
        set_clock(client, "2026-01-01T00:00:00Z")

        resp = client.get_plan(
            "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", headers=ADMIN
        )

        validate_error(resp, ERR_PLAN_NOT_FOUND, expected_status=404)


class TestClaimRequiredFields:
    def test_claim_create_missing_lines_returns_invalid_request(self, client):
        """A claim without its lines array is a shape error.

        PRD 3.5: "The payload names the `subscriber_id` and optional
        `dependent_id` (which must belong to that subscriber, on pain of
        `ERR_CROSS_REFERENCE_MISMATCH`), the `provider_id`, an optional
        `predetermination_id` referencing an approved predetermination whose
        pin should price the claim, the `service_date`, the `received_date`,
        an optional `cob_other_plan_paid_cents` amount (defaulting to zero)
        recording what the primary carrier already paid when this plan is
        secondary, an optional `tooth_missing_prior_to_coverage` map
        attesting per tooth number whether the tooth was missing before the
        member's `effective_date`, and a `lines` array."
        PRD 2.10: "Only then are required-field presence, types, and enum
        membership validated, failing with `ERR_INVALID_REQUEST` (HTTP 400),
        followed by state-transition legality (`ERR_INVALID_STATE`, HTTP 409)
        and finally the business rules described in §3."

        Design: Corner/entities/claim_create_missing_lines_returns_invalid_request
        """
        stack = standard_stack(client)

        resp = client.create_claim(
            {
                "subscriber_id": stack["subscriber"]["id"],
                "provider_id": stack["provider"]["id"],
                "service_date": "2026-02-01T00:00:00Z",
                "received_date": "2026-02-02T00:00:00Z",
            },
            headers=make_provider_headers(stack["provider"]["id"]),
        )

        validate_error(resp, ERR_INVALID_REQUEST, expected_status=400)


class TestClaimRetrieval:
    def test_claim_get_returns_stored_fields(self, client):
        """A stored claim round-trips inputs and computed totals.

        PRD 3.7: "Adjudication finalizes the claim's rollups:
        `total_submitted_cents`, `total_allowed_cents`,
        `total_plan_pay_cents`, and `total_patient_pay_cents` are the
        per-line sums across the claim."
        PRD 3.5: "Otherwise the claim moves directly `RECEIVED →
        ADJUDICATED` and the adjudication pipeline of §3.7 runs immediately."

        Design: Corner/entities/claim_get_returns_stored_fields
        """
        stack = standard_stack(client)
        claim = adjudicated_claim(client, stack)

        reread = read_claim(client, claim["id"])

        assert same_instant(reread["service_date"], "2026-02-01T00:00:00Z")
        assert reread["provider_id"] == stack["provider"]["id"]
        assert reread["subscriber_id"] == stack["subscriber"]["id"]
        assert reread["status"] == CLAIM_ADJUDICATED
        assert reread["total_submitted_cents"] == 5000
        assert reread["total_allowed_cents"] == 5000
        assert reread["total_plan_pay_cents"] == 5000
        assert reread["total_patient_pay_cents"] == 0
