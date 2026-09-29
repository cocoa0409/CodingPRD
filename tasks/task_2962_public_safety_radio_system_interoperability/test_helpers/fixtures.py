"""Composite setup builders.

The harness relaunches the API server before every individual test, so every
test starts against an empty database and each builder below constructs its
preconditions from scratch through the PRD's own endpoints. Builders use
``get_success_data`` so a broken precondition reports the server's own error id
rather than surfacing as an opaque assertion deep inside a test.

No builder asserts business behaviour — that is the tests' job. Builders only
reach the state a test needs and return the created rows.
"""

from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient
from .constants import (
    ACTION_ASSIGN,
    CAUSE_COMMERCIAL_POWER_LOSS,
    CAUSE_INCIDENT_SURGE,
    CAUSE_SCHEDULED_WORK,
    DECISION_APPROVE,
    EVENT_MAJOR_INCIDENT,
    EVENT_PLANNED_MAINTENANCE,
    EVENT_UNPLANNED_OUTAGE,
    EV_ACTION_BACKUP_ENGAGED,
    EV_ACTION_DECLARE_SURGE,
    EV_ACTION_ESCALATE,
    KEYSET_DECISION_APPROVE,
    KIND_NORMAL,
    PATCH_DECISION_ACTIVATE,
)
from .test_users import (
    CHANGE_CONTROL_BOARD,
    FLEET_ENGINEER,
    KEY_CUSTODIAN,
    RF_ENGINEER,
    SECURITY_OFFICER,
    SYSTEM_ADMIN,
    make_agency_radio_manager_headers,
    make_dispatcher_headers,
)


# --- Logical clock --------------------------------------------------------


def set_clock(api: ApiClient, to_iso8601: str) -> Dict[str, Any]:
    """Move the logical clock; only a `SystemAdmin` may do so."""
    return get_success_data(
        api.set_clock(f.clock_payload(to_iso8601), SYSTEM_ADMIN), 200
    )


# --- Member agencies ------------------------------------------------------


def register_agency(api: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    """Register one member agency and return the created row."""
    return get_success_data(
        api.create_agency(f.agency_payload(**kwargs), SYSTEM_ADMIN), 201
    )


def read_agency(api: ApiClient, agency_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_agency(agency_id, SYSTEM_ADMIN), 200)


def set_console_config(api: ApiClient, agency_id: str, **kwargs: Any) -> Dict[str, Any]:
    """Reconfigure console positions and recorder retention as the agency's own
    `AgencyRadioManager`."""
    return get_success_data(
        api.update_console_config(
            agency_id,
            f.console_config_payload(**kwargs),
            make_agency_radio_manager_headers(agency_id),
        ),
        200,
    )


def assess_fees(
    api: ApiClient, agency_id: str, period_start: str, period_end: str
) -> Dict[str, Any]:
    """Book an assessment, reading the agency's current `version` for the pin."""
    version = read_agency(api, agency_id)["version"]
    return get_success_data(
        api.create_fee_assessment(
            agency_id,
            f.fee_assessment_payload(period_start, period_end, version),
            SYSTEM_ADMIN,
        ),
        200,
    )


def pay(api: ApiClient, agency_id: str, amount_cents: int) -> Dict[str, Any]:
    return get_success_data(
        api.create_payment(agency_id, f.payment_payload(amount_cents), SYSTEM_ADMIN),
        200,
    )


# --- Sites and coverage ---------------------------------------------------


def register_site(api: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    return get_success_data(api.create_site(f.site_payload(**kwargs), SYSTEM_ADMIN), 201)


def read_site(api: ApiClient, site_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_site(site_id, SYSTEM_ADMIN), 200)


def survey_site(
    api: ApiClient, site_id: str, covered_test_points: int, total_test_points: int
) -> Dict[str, Any]:
    """File drive-test results, reading the site's current `version` for the pin."""
    version = read_site(api, site_id)["version"]
    return get_success_data(
        api.submit_coverage(
            site_id,
            f.coverage_payload(covered_test_points, total_test_points, version),
            RF_ENGINEER,
        ),
        200,
    )


def site_with_coverage(
    api: ApiClient, covered_test_points: int, total_test_points: int, **kwargs: Any
) -> Dict[str, Any]:
    """Register a site and immediately drive-test it to a known coverage class."""
    site = register_site(api, **kwargs)
    return survey_site(api, site["id"], covered_test_points, total_test_points)


# --- Programming templates ------------------------------------------------


def create_template(api: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_template(f.template_payload(**kwargs), FLEET_ENGINEER), 201
    )


def publish_template(api: ApiClient, template_id: str) -> Dict[str, Any]:
    return get_success_data(api.publish_template(template_id, FLEET_ENGINEER), 200)


def published_template(api: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    """Author a root template and publish it in one step."""
    template = create_template(api, **kwargs)
    return publish_template(api, template["id"])


def read_template(api: ApiClient, template_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_template(template_id, FLEET_ENGINEER), 200)


def revise_template(api: ApiClient, template_id: str, **kwargs: Any) -> Dict[str, Any]:
    """Create a revision superseding this template, reading its `version` for
    the pin."""
    version = read_template(api, template_id)["version"]
    return get_success_data(
        api.create_template_revision(
            template_id, f.template_revision_payload(version, **kwargs), FLEET_ENGINEER
        ),
        201,
    )


# --- Programming change requests -----------------------------------------


def create_change_request(
    api: ApiClient, template_id: str, target_agency_id: str, **kwargs: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_change_request(
            f.change_request_payload(template_id, target_agency_id, **kwargs),
            FLEET_ENGINEER,
        ),
        201,
    )


def submit_change_request(
    api: ApiClient, change_request_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(
        api.submit_change_request(change_request_id, headers or FLEET_ENGINEER), 200
    )


def review_change_request(
    api: ApiClient,
    change_request_id: str,
    decision: str,
    review_comment: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api.review_change_request(
            change_request_id,
            f.review_decision_payload(decision, review_comment),
            headers or CHANGE_CONTROL_BOARD,
        ),
        200,
    )


def approved_change_request(
    api: ApiClient, template_id: str, target_agency_id: str, **kwargs: Any
) -> Dict[str, Any]:
    """Open, submit and approve a change request in one step."""
    request = create_change_request(api, template_id, target_agency_id, **kwargs)
    submit_change_request(api, request["id"])
    return review_change_request(api, request["id"], DECISION_APPROVE)


def deploy_change_request(api: ApiClient, change_request_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.deploy_change_request(change_request_id, FLEET_ENGINEER), 200
    )


# --- Subscriber units ----------------------------------------------------


def add_unit(api: ApiClient, agency_id: str, **kwargs: Any) -> Dict[str, Any]:
    """Add a radio to the agency's inventory as its own `AgencyRadioManager`."""
    return get_success_data(
        api.create_unit(
            f.unit_payload(agency_id, **kwargs),
            make_agency_radio_manager_headers(agency_id),
        ),
        201,
    )


def read_unit(api: ApiClient, unit_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_unit(unit_id, SYSTEM_ADMIN), 200)


def lifecycle(
    api: ApiClient,
    unit_id: str,
    agency_id: str,
    action: str,
    template_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Drive one unit lifecycle action as the owning agency."""
    return get_success_data(
        api.unit_lifecycle(
            unit_id,
            f.lifecycle_payload(action, template_id),
            make_agency_radio_manager_headers(agency_id),
        ),
        200,
    )


def assigned_unit(
    api: ApiClient, agency_id: str, template_id: str, **kwargs: Any
) -> Dict[str, Any]:
    """Add a radio and take it from `INVENTORY` to `ASSIGNED`."""
    unit = add_unit(api, agency_id, **kwargs)
    return lifecycle(api, unit["id"], agency_id, ACTION_ASSIGN, template_id)


def assigned_units(
    api: ApiClient, agency_id: str, template_id: str, count: int, **kwargs: Any
) -> List[Dict[str, Any]]:
    """Build `count` assigned radios for one agency, in creation order."""
    return [assigned_unit(api, agency_id, template_id, **kwargs) for _ in range(count)]


# --- Keysets and OTAR ----------------------------------------------------


def create_keyset(api: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_keyset(f.keyset_payload(**kwargs), KEY_CUSTODIAN), 201
    )


def decide_keyset(
    api: ApiClient,
    keyset_id: str,
    decision: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api.decide_keyset(
            keyset_id,
            f.keyset_decision_payload(decision),
            headers or SECURITY_OFFICER,
        ),
        200,
    )


def active_keyset(api: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    """Create a keyset and have a `SecurityOfficer` approve it into `ACTIVE`."""
    keyset = create_keyset(api, **kwargs)
    return decide_keyset(api, keyset["id"], KEYSET_DECISION_APPROVE)


def compromise_keyset(api: ApiClient, keyset_id: str) -> Dict[str, Any]:
    return get_success_data(api.compromise_keyset(keyset_id, SECURITY_OFFICER), 200)


def schedule_campaign(
    api: ApiClient, keyset_id: str, agency_id: str, **kwargs: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_otar_campaign(
            f.otar_campaign_payload(keyset_id, agency_id, **kwargs), KEY_CUSTODIAN
        ),
        201,
    )


def execute_campaign(api: ApiClient, campaign_id: str) -> Dict[str, Any]:
    return get_success_data(api.execute_otar_campaign(campaign_id, KEY_CUSTODIAN), 200)


def keyed_fleet(
    api: ApiClient,
    agency_id: str,
    keyset_id: str,
    window_start: str,
    window_end: str,
    execute_at: str,
) -> Dict[str, Any]:
    """Run one rekey campaign to completion so the agency's assigned radios are
    `KEYED`. Leaves the logical clock inside the campaign window."""
    campaign = schedule_campaign(
        api, keyset_id, agency_id, window_start=window_start, window_end=window_end
    )
    set_clock(api, execute_at)
    return execute_campaign(api, campaign["id"])


# --- Talkgroups and patches ----------------------------------------------


def create_talkgroup(
    api: ApiClient, owner_agency_id: str, home_site_id: str, **kwargs: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_talkgroup(
            f.talkgroup_payload(owner_agency_id, home_site_id, **kwargs),
            make_agency_radio_manager_headers(owner_agency_id),
        ),
        201,
    )


def read_talkgroup(api: ApiClient, talkgroup_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_talkgroup(talkgroup_id, SYSTEM_ADMIN), 200)


def talkgroup_action(
    api: ApiClient, talkgroup_id: str, owner_agency_id: str, action: str
) -> Dict[str, Any]:
    return get_success_data(
        api.talkgroup_status(
            talkgroup_id,
            f.talkgroup_status_payload(action),
            make_agency_radio_manager_headers(owner_agency_id),
        ),
        200,
    )


def request_patch(
    api: ApiClient,
    source_talkgroup_id: str,
    target_talkgroup_id: str,
    requesting_agency_id: str,
    **kwargs: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_interop_patch(
            f.interop_patch_payload(
                source_talkgroup_id,
                target_talkgroup_id,
                requesting_agency_id,
                **kwargs,
            ),
            make_dispatcher_headers(requesting_agency_id),
        ),
        201,
    )


def decide_patch(
    api: ApiClient, patch_id: str, requesting_agency_id: str, decision: str
) -> Dict[str, Any]:
    return get_success_data(
        api.decide_interop_patch(
            patch_id,
            f.patch_decision_payload(decision),
            make_dispatcher_headers(requesting_agency_id),
        ),
        200,
    )


def active_patch(
    api: ApiClient,
    source_talkgroup_id: str,
    target_talkgroup_id: str,
    requesting_agency_id: str,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Request a patch and activate it inside its reserved window."""
    patch = request_patch(
        api,
        source_talkgroup_id,
        target_talkgroup_id,
        requesting_agency_id,
        **kwargs,
    )
    return decide_patch(api, patch["id"], requesting_agency_id, PATCH_DECISION_ACTIVATE)


def release_patch(
    api: ApiClient, patch_id: str, requesting_agency_id: str
) -> Dict[str, Any]:
    return get_success_data(
        api.release_interop_patch(
            patch_id, make_dispatcher_headers(requesting_agency_id)
        ),
        200,
    )


# --- Site events ---------------------------------------------------------


def open_site_event(api: ApiClient, site_id: str, **kwargs: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_site_event(f.site_event_payload(site_id, **kwargs), RF_ENGINEER), 201
    )


def advance_event(
    api: ApiClient,
    event_id: str,
    action: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api.advance_site_event(event_id, f.advance_payload(action), headers or RF_ENGINEER),
        200,
    )


def outage_on_backup(
    api: ApiClient, site_id: str, cause: str = CAUSE_COMMERCIAL_POWER_LOSS
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Open an `UNPLANNED_OUTAGE` and engage backup power.

    Returns the freshly opened event and the event as it stands on backup power.
    """
    event = open_site_event(
        api, site_id, event_class=EVENT_UNPLANNED_OUTAGE, cause=cause
    )
    return event, advance_event(api, event["id"], EV_ACTION_BACKUP_ENGAGED)


def escalate(api: ApiClient, event_id: str) -> Dict[str, Any]:
    return advance_event(api, event_id, EV_ACTION_ESCALATE)


def declare_surge(api: ApiClient, site_id: str) -> Dict[str, Any]:
    """Open a `MAJOR_INCIDENT` and declare a surge; reserved to a `SystemAdmin`."""
    event = open_site_event(
        api, site_id, event_class=EVENT_MAJOR_INCIDENT, cause=CAUSE_INCIDENT_SURGE
    )
    return advance_event(api, event["id"], EV_ACTION_DECLARE_SURGE, SYSTEM_ADMIN)


def planned_maintenance(
    api: ApiClient, site_id: str, window_start: str, window_end: str
) -> Dict[str, Any]:
    """Open a `PLANNED_MAINTENANCE` event with its mandatory window pair."""
    return open_site_event(
        api,
        site_id,
        event_class=EVENT_PLANNED_MAINTENANCE,
        cause=CAUSE_SCHEDULED_WORK,
        window_start=window_start,
        window_end=window_end,
    )


# --- Talkpath requests ---------------------------------------------------


def request_talkpath(
    api: ApiClient,
    site_id: str,
    talkgroup_id: str,
    unit_id: str,
    owner_agency_id: str,
    request_kind: str = KIND_NORMAL,
    site_event_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Submit one talkpath request as the dispatcher of the talkgroup's owner."""
    return get_success_data(
        api.create_talkpath_request(
            f.talkpath_payload(
                site_id, talkgroup_id, unit_id, request_kind, site_event_id
            ),
            make_dispatcher_headers(owner_agency_id),
        ),
        201,
    )


def release_talkpath(
    api: ApiClient, request_id: str, owner_agency_id: str
) -> Dict[str, Any]:
    return get_success_data(
        api.release_talkpath_request(
            request_id, make_dispatcher_headers(owner_agency_id)
        ),
        200,
    )


# --- Whole-fleet scenario -------------------------------------------------


def fleet_on_site(
    api: ApiClient,
    unit_count: int = 1,
    channel_capacity: int = 8,
    agency_kwargs: Optional[Dict[str, Any]] = None,
    site_kwargs: Optional[Dict[str, Any]] = None,
    template_kwargs: Optional[Dict[str, Any]] = None,
    talkgroup_kwargs: Optional[Dict[str, Any]] = None,
    unit_kwargs: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build one agency with a site, a published template, a talkgroup homed on
    that site, and `unit_count` assigned radios.

    Returns a dict with keys ``agency``, ``site``, ``template``, ``talkgroup``
    and ``units``.
    """
    agency = register_agency(api, **(agency_kwargs or {}))
    site_args = dict(site_kwargs or {})
    site_args.setdefault("channel_capacity", channel_capacity)
    site = register_site(api, **site_args)
    template = published_template(api, **(template_kwargs or {}))
    talkgroup = create_talkgroup(
        api, agency["id"], site["id"], **(talkgroup_kwargs or {})
    )
    units = assigned_units(
        api, agency["id"], template["id"], unit_count, **(unit_kwargs or {})
    )
    return {
        "agency": agency,
        "site": site,
        "template": template,
        "talkgroup": talkgroup,
        "units": units,
    }
