"""Cross-entity gates: porting gated on employee termination, campaign open gated
on the employer group's status."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors, fixtures
from test_helpers.factories import benefit_item_payload
from test_helpers.test_users import (
    make_carrier_admin_headers,
    make_counselor_headers,
    make_group_admin_headers,
    make_policyholder_services_headers,
)


def _issued_pre_tax_policy(client):
    base = fixtures.setup_issued_policy(
        client,
        policy_overrides={"premium_mode": "PRE_TAX"},
        schedule_overrides={"monthly_premium_cents": 2200},
        benefit_items=[
            benefit_item_payload(
                event_code="Q",
                benefit_amount_cents=1000,
                max_occurrences_per_year=2,
                lifetime_max_cents=100000,
            )
        ],
    )
    return base


def test_porting_while_the_employee_is_active_is_rejected(client):
    """Port requires a terminated employee; an active employee blocks it.

    "Porting (`ISSUED` → `PORTED` or `ACTIVE` → `PORTED`) is performed by
    `PolicyholderServices` and requires the employee to be `TERMINATED` — porting
    while the employee is still active fails with `ERR_PORT_NOT_ELIGIBLE`."

    Design: Difficulty/cross_entity_state_dependency/policy_port_gated_on_employee_terminated
    """
    base = _issued_pre_tax_policy(client)

    response = client.port_policy(
        base.policy["id"], {"new_premium_mode": "PRE_TAX"},
        make_policyholder_services_headers(),
    )

    validate_error(response, api_errors.ERR_PORT_NOT_ELIGIBLE, 422)
    policy = fixtures.read_policy(client, base.policy["id"])
    assert policy["status"] == "ISSUED"


def test_port_forces_post_tax_once_the_employee_is_terminated(client):
    """After termination the port succeeds and reports POST_TAX either way.

    "The request carries a `new_premium_mode` naming `PRE_TAX` or `POST_TAX`, but
    the requester's choice is nominal: ported policies are direct-billed, so the
    policy's `premium_mode` is forced to `POST_TAX` regardless of the requested
    value, and the response reports `POST_TAX`."

    Design: Difficulty/cross_entity_state_dependency/policy_port_gated_on_employee_terminated
    """
    base = _issued_pre_tax_policy(client)
    validate_error(
        client.port_policy(
            base.policy["id"], {"new_premium_mode": "PRE_TAX"},
            make_policyholder_services_headers(),
        ),
        api_errors.ERR_PORT_NOT_ELIGIBLE,
        422,
    )

    validate_success(
        client.terminate_employee(base.employee["id"], make_group_admin_headers()), 200
    )
    ported = validate_success(
        client.port_policy(
            base.policy["id"], {"new_premium_mode": "PRE_TAX"},
            make_policyholder_services_headers(),
        ),
        200,
    )
    assert ported["status"] == "PORTED"
    assert ported["premium_mode"] == "POST_TAX", (
        "ported policies are direct-billed; got %r" % ported.get("premium_mode")
    )


def _draft_campaign_on_suspendable_group(client):
    """A DRAFT campaign whose group can be suspended and reactivated."""
    group = fixtures.create_active_group(client)
    counselor = fixtures.create_counselor(client)
    campaign = fixtures.create_campaign(client, group["id"], counselor)
    return fixtures.Bundle(group=group, counselor=counselor, campaign=campaign)


def test_opening_a_campaign_on_a_suspended_group_is_rejected(client):
    """The open gate requires an ACTIVE group; SUSPENDED fails.

    "The lead counselor opens the campaign (`DRAFT` → `OPEN`) under a battery of
    checks: the counselor must still be `ACTIVE` (`ERR_COUNSELOR_INACTIVE`), the
    employer group must be `ACTIVE` (`ERR_GROUP_INACTIVE`), and the current clock
    time must be before `window_end` (`ERR_WINDOW_EXPIRED`)."

    Design: Difficulty/cross_entity_state_dependency/campaign_open_gated_on_employer_group_active
    """
    base = _draft_campaign_on_suspendable_group(client)
    validate_success(
        client.suspend_employer_group(base.group["id"], make_carrier_admin_headers()),
        200,
    )

    response = client.open_enrollment_campaign(
        base.campaign["id"], make_counselor_headers(base.counselor["id"])
    )

    validate_error(response, api_errors.ERR_GROUP_INACTIVE, 422)
    campaign = validate_success(
        client.get_enrollment_campaign(base.campaign["id"], make_carrier_admin_headers()),
        200,
    )
    assert campaign["status"] == "DRAFT"


def test_open_succeeds_again_after_the_group_is_reactivated(client):
    """Reactivating the group restores the identical open call.

    "A suspended group can be reactivated (`SUSPENDED` → `ACTIVE`); activation
    from either `PROSPECT` or `SUSPENDED` lands on the same `ACTIVE` state."

    Design: Difficulty/cross_entity_state_dependency/campaign_open_gated_on_employer_group_active
    """
    base = _draft_campaign_on_suspendable_group(client)
    validate_success(
        client.suspend_employer_group(base.group["id"], make_carrier_admin_headers()),
        200,
    )
    validate_error(
        client.open_enrollment_campaign(
            base.campaign["id"], make_counselor_headers(base.counselor["id"])
        ),
        api_errors.ERR_GROUP_INACTIVE,
        422,
    )

    validate_success(
        client.activate_employer_group(base.group["id"], make_carrier_admin_headers()),
        200,
    )
    opened = validate_success(
        client.open_enrollment_campaign(
            base.campaign["id"], make_counselor_headers(base.counselor["id"])
        ),
        200,
    )
    assert opened["status"] == "OPEN"
