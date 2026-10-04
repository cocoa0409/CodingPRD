"""Validation rules: temporal gates, referential integrity, fiscal bounds,
attachments, schedule coverage, and optimistic concurrency."""

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_COB_CONFIG_INVALID,
    ERR_CROSS_REFERENCE_MISMATCH,
    ERR_INVALID_ATTACHMENT,
    ERR_INVALID_PLAN_CONFIG,
    ERR_NO_FEE_SCHEDULE,
    ERR_NOT_FOUND,
    ERR_RETROACTIVE_PREDETERMINATION,
    ERR_STALE_VERSION,
    ERR_TIMELY_FILING,
)
from test_helpers.assertions import (
    get_success_data,
    validate_error,
    validate_paginated,
)
from test_helpers.constants import (
    CLAIM_PENDED_ATTACHMENTS,
    PREDET_UNDER_REVIEW,
)
from test_helpers.fixtures import (
    assign_predetermination,
    claim_lines,
    create_dependent,
    create_predetermination,
    create_subscriber,
    read_predetermination,
    set_clock,
    standard_stack,
)
from test_helpers.test_users import (
    ADMIN,
    EXAMINER,
    make_provider_headers,
    make_reviewer_headers,
)


class TestTimelyFiling:
    def test_timely_filing_rejects_claim_received_after_365_days(self, client):
        """A claim received on day 369 is refused; nothing persists.

        PRD 3.5: "The timely-filing rule rejects a claim whose
        `received_date` falls more than three hundred sixty-five days after
        the `service_date` — a claim received on the three-hundred-sixty-fifth
        day itself is timely, one received later is refused with
        `ERR_TIMELY_FILING` (HTTP 422)."

        Design: Corner/validations/timely_filing_rejects_claim_received_after_365_days
        """
        stack = standard_stack(client)

        resp = client.create_claim(
            f.create_claim_payload(
                stack["subscriber"]["id"],
                stack["provider"]["id"],
                service_date="2026-01-01T00:00:00Z",
                received_date="2027-01-05T00:00:00Z",
            ),
            headers=make_provider_headers(stack["provider"]["id"]),
        )

        validate_error(resp, ERR_TIMELY_FILING, expected_status=422)
        data, meta = validate_paginated(
            client.list_claims(
                headers=EXAMINER,
                params={"subscriber_id": stack["subscriber"]["id"]},
            )
        )
        assert data == [], "a refused claim never persists"


class TestRetroactivePredetermination:
    def test_retroactive_predetermination_rejected(self, client):
        """A planned date before the logical clock cannot be estimated.

        PRD 3.4: "Predeterminations are forward-looking by definition: a
        `planned_service_date` earlier than the logical clock is rejected
        with `ERR_RETROACTIVE_PREDETERMINATION` (HTTP 422)."

        Design: Corner/validations/retroactive_predetermination_rejected
        """
        stack = standard_stack(client)
        set_clock(client, "2026-06-01T00:00:00Z")

        resp = client.create_predetermination(
            f.create_predetermination_payload(
                stack["subscriber"]["id"],
                stack["provider"]["id"],
                planned_service_date="2026-05-01T00:00:00Z",
            ),
            headers=make_provider_headers(stack["provider"]["id"]),
        )

        validate_error(resp, ERR_RETROACTIVE_PREDETERMINATION, expected_status=422)


class TestCrossReferenceIntegrity:
    def test_claim_with_dependent_of_other_subscriber_returns_cross_reference_mismatch(self, client):
        """A dependent id from another family is a referential violation.

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

        Design: Corner/validations/claim_with_dependent_of_other_subscriber_returns_cross_reference_mismatch
        """
        stack = standard_stack(client)
        other = create_subscriber(
            client,
            stack["plan"]["id"],
            member_id="M-OTHER",
            full_name="Olga Other",
        )
        other_child = create_dependent(client, other["id"], full_name="Kid Other")

        resp = client.create_claim(
            f.create_claim_payload(
                stack["subscriber"]["id"],
                stack["provider"]["id"],
                dependent_id=other_child["id"],
            ),
            headers=make_provider_headers(stack["provider"]["id"]),
        )

        validate_error(resp, ERR_CROSS_REFERENCE_MISMATCH, expected_status=422)


class TestCobConfigPairing:
    def test_subscriber_secondary_without_external_plan_id_returns_cob_config_invalid(self, client):
        """SECONDARY without the other carrier's identifier is refused.

        PRD 3.3: "When `cob_priority` is `SECONDARY`, the enrollment must
        name the other carrier in `other_plan_external_id`; when it is
        `PRIMARY` or `NONE`, that field must be empty. Violating this pairing
        is rejected with `ERR_COB_CONFIG_INVALID` (HTTP 422)."

        Design: Corner/validations/subscriber_secondary_without_external_plan_id_returns_cob_config_invalid
        """
        stack = standard_stack(client)

        resp = client.create_subscriber(
            {
                "plan_id": stack["plan"]["id"],
                "member_id": "M-BADCOB",
                "full_name": "Bad Cob",
                "date_of_birth": "1980-01-01T00:00:00Z",
                "effective_date": "2026-01-01T00:00:00Z",
                "cob_priority": "SECONDARY",
            },
            headers=ADMIN,
        )

        validate_error(resp, ERR_COB_CONFIG_INVALID, expected_status=422)


class TestPlanConfigBounds:
    def test_plan_with_coinsurance_over_100_returns_invalid_plan_config(self, client):
        """A 150% coinsurance lies outside the declared bounds.

        PRD 2.5: "Plan configuration is bounded:
        `preventive_coinsurance_pct`, `basic_coinsurance_pct`, and
        `major_coinsurance_pct` must each be at least 0 and at most 100, and
        `annual_maximum_cents` and `deductible_cents` must be non-negative. A
        plan creation request violating these bounds is rejected with
        `ERR_INVALID_PLAN_CONFIG` (HTTP 422)."

        Design: Corner/validations/plan_with_coinsurance_over_100_returns_invalid_plan_config
        """
        set_clock(client, "2026-01-01T00:00:00Z")

        resp = client.create_plan(
            f.create_plan_payload(
                plan_code="DD-BAD", preventive_coinsurance_pct=150
            ),
            headers=ADMIN,
        )

        validate_error(resp, ERR_INVALID_PLAN_CONFIG, expected_status=422)


class TestAttachmentShape:
    def test_attachment_with_undeclared_kind_returns_invalid_attachment(self, client):
        """A kind outside the declared set is refused and the claim stays pended.

        PRD 3.5: "Providers supply missing documentation by uploading
        attachments: each attachment names the `claim_line_id` it supports —
        which must belong to the same claim, else
        `ERR_CROSS_REFERENCE_MISMATCH` — an `attachment_kind` of `RADIOGRAPH`,
        `NARRATIVE`, `PERIO_CHART`, or `PHOTO`, and an opaque `blob_ref`
        storage reference. A submission missing `blob_ref` or
        `attachment_kind`, or presenting a kind outside the declared set,
        fails with `ERR_INVALID_ATTACHMENT` (HTTP 400)."

        Design: Corner/validations/attachment_with_undeclared_kind_returns_invalid_attachment
        """
        entries = [
            f.fee_schedule_entry_payload(
                cdt_code="D2740", allowed_cents=10000, category="MAJOR",
                requires_attachment=True,
            ),
        ]
        stack = standard_stack(client, entries=entries)
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
        assert claim["status"] == CLAIM_PENDED_ATTACHMENTS
        line_id = claim_lines(client, claim["id"])[0]["id"]

        resp = client.create_claim_attachment(
            claim["id"],
            f.create_attachment_payload(
                line_id, attachment_kind="XRAY", blob_ref="blob://bad"
            ),
            headers=make_provider_headers(stack["provider"]["id"]),
        )

        validate_error(resp, ERR_INVALID_ATTACHMENT, expected_status=400)
        reread = get_success_data(client.get_claim(claim["id"], headers=EXAMINER))
        assert reread["status"] == CLAIM_PENDED_ATTACHMENTS


class TestScheduleCoverageGate:
    def test_claim_with_unpriced_cdt_returns_no_fee_schedule(self, client):
        """An active schedule lacking the code cannot price the line.

        PRD 3.5: "The schedule gate verifies that an `ACTIVE` fee schedule
        covers the rendering provider's tier at the service date and contains
        an entry for every `cdt_code` on the claim; failure is
        `ERR_NO_FEE_SCHEDULE`."

        Design: Corner/validations/claim_with_unpriced_cdt_returns_no_fee_schedule
        """
        stack = standard_stack(client)

        resp = client.create_claim(
            f.create_claim_payload(
                stack["subscriber"]["id"],
                stack["provider"]["id"],
                lines=[
                    f.claim_line_payload(
                        cdt_code="D9999", tooth_number="",
                        submitted_amount_cents=5000,
                    )
                ],
            ),
            headers=make_provider_headers(stack["provider"]["id"]),
        )

        validate_error(resp, ERR_NO_FEE_SCHEDULE, expected_status=422)


class TestOptimisticConcurrency:
    def test_predet_approve_with_stale_version_returns_stale_version(self, client):
        """Approving a view one version behind the truth is refused.

        PRD 2.9: "Approving a predetermination requires
        `expected_predetermination_version` in the request body, carrying the
        `version` of the predetermination as the approving reviewer last
        observed it. If the predetermination's current `version` has advanced
        — for instance because a reassignment recomputed the estimate — the
        approval is rejected with `ERR_STALE_VERSION` (HTTP 412), so a
        reviewer never approves an estimate they have not seen."

        Design: Corner/validations/predet_approve_with_stale_version_returns_stale_version
        """
        stack = standard_stack(client)
        predet = create_predetermination(
            client, stack["subscriber"]["id"], stack["provider"]
        )
        assigned = assign_predetermination(client, predet["id"], "rev-1")

        resp = client.approve_predetermination(
            predet["id"],
            {"expected_predetermination_version": assigned["version"] - 1},
            headers=make_reviewer_headers("rev-1"),
        )

        validate_error(resp, ERR_STALE_VERSION, expected_status=412)
        reread = read_predetermination(client, predet["id"])
        assert reread["status"] == PREDET_UNDER_REVIEW


class TestBodyForeignKeyResolution:
    def test_claim_with_unknown_subscriber_id_returns_not_found(self, client):
        """An unresolvable body foreign key is the generic 404.

        PRD 2.10: "Foreign-key references in request bodies (`plan_id`,
        `subscriber_id`, `dependent_id`, `provider_id`,
        `predetermination_id`, `claim_line_id`) resolve next, failing with
        the generic `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/validations/claim_with_unknown_subscriber_id_returns_not_found
        """
        stack = standard_stack(client)

        resp = client.create_claim(
            f.create_claim_payload(
                "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2",
                stack["provider"]["id"],
            ),
            headers=make_provider_headers(stack["provider"]["id"]),
        )

        validate_error(resp, ERR_NOT_FOUND, expected_status=404)
