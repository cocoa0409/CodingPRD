"""Cross-cutting layers: optimistic concurrency on voids, and the immediate
consistency of computed totals on the create response."""

from test_helpers import factories as f
from test_helpers.api_errors import ERR_STALE_VERSION
from test_helpers.assertions import get_success_data, validate_error, validate_success
from test_helpers.constants import CLAIM_ADJUDICATED
from test_helpers.fixtures import adjudicated_claim, standard_stack
from test_helpers.test_users import EXAMINER, make_provider_headers


class TestClaimVoidOptimisticConcurrency:
    def test_claim_void_with_stale_version_returns_stale_version(self, client):
        """Voiding a view one version behind the truth is refused.

        PRD 2.9: "Voiding a claim requires `expected_claim_version`, carrying
        the `version` of the claim as the examiner last observed it. If the
        claim's `version` has advanced since — for instance because another
        examiner has just paid it — the void is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting/claim_void_with_stale_version_returns_stale_version
        """
        stack = standard_stack(client)
        claim = adjudicated_claim(client, stack)

        resp = client.void_claim(
            claim["id"],
            {"expected_claim_version": claim["version"] - 1},
            headers=EXAMINER,
        )

        validate_error(resp, ERR_STALE_VERSION, expected_status=412)
        reread = get_success_data(client.get_claim(claim["id"], headers=EXAMINER))
        assert reread["status"] == CLAIM_ADJUDICATED


class TestImmediateConsistency:
    def test_claim_post_response_includes_computed_totals_immediately(self, client):
        """The create response itself carries the adjudicated totals.

        PRD 3.5: "Otherwise the claim moves directly `RECEIVED →
        ADJUDICATED` and the adjudication pipeline of §3.7 runs immediately."
        PRD 3.7: "Adjudication finalizes the claim's rollups:
        `total_submitted_cents`, `total_allowed_cents`,
        `total_plan_pay_cents`, and `total_patient_pay_cents` are the
        per-line sums across the claim."

        Design: Corner/consistency/claim_post_response_includes_computed_totals_immediately
        """
        stack = standard_stack(client)

        resp = client.create_claim(
            f.create_claim_payload(
                stack["subscriber"]["id"],
                stack["provider"]["id"],
                lines=[
                    f.claim_line_payload(
                        cdt_code="D2391", tooth_number="19",
                        submitted_amount_cents=10000,
                    )
                ],
            ),
            headers=make_provider_headers(stack["provider"]["id"]),
        )

        data = validate_success(resp, expected_status=201)
        assert data["status"] == CLAIM_ADJUDICATED
        assert data["total_submitted_cents"] == 10000
        assert data["total_allowed_cents"] == 10000
        assert data["total_plan_pay_cents"] == 8000, (
            "floor(10000 * 80/100) == 8000, got %r" % data["total_plan_pay_cents"]
        )
