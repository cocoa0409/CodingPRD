"""
Composite setup helpers — core hub/site/region hierarchy.

Uses get_success_data() (lenient validator) so setup failures surface as clear
"Setup failed" errors rather than confusing assertion failures.
"""
from prd_bench_local_runner.testing import get_success_data, NON_EXISTENT_UUID

from .api_client import api_client
from .factories import (
    create_hub_payload,
    create_print_site_payload,
    create_region_payload,
)
from .test_users import (
    PLATFORM_ADMIN,
    PRINT_OPS,
    DELIVERY_MANAGER,
    NEWSROOM_MANAGER,
    CUSTOMER_SERVICE,
    AUDITOR,
)
from .constants import CLOCK_2026_09_01


def set_clock(current_utc: str = CLOCK_2026_09_01):
    """Advance the server's logical clock. Returns the parsed data payload."""
    return get_success_data(api_client.set_current_utc(
        {"current_utc": current_utc}, PLATFORM_ADMIN))


def create_hub(**overrides):
    """Create a region hub. Returns the hub data dict."""
    return get_success_data(api_client.create_hub(
        create_hub_payload(**overrides), PLATFORM_ADMIN))


def create_hub_with_clock(current_utc: str = CLOCK_2026_09_01, **overrides):
    """Set the logical clock first, then create a hub. Returns the hub."""
    set_clock(current_utc)
    return create_hub(**overrides)


def get_hub(hub_id):
    """Read a hub. Returns the hub data dict."""
    return get_success_data(api_client.get_hub(hub_id, PRINT_OPS))


def hub_version(hub_id):
    """Read the hub's current version token."""
    return get_hub(hub_id)["version"]


def get_compliance(hub_id):
    """Read the hub's legal-notice compliance projection."""
    return get_success_data(api_client.get_hub_compliance(hub_id, AUDITOR))


def create_site(hub_id, **overrides):
    """Create a print site inside a hub. Returns the site data dict."""
    return get_success_data(api_client.create_print_site(
        hub_id, create_print_site_payload(**overrides), PRINT_OPS))


def create_region(hub_id, **overrides):
    """Create a region inside a hub. Returns the region data dict."""
    return get_success_data(api_client.create_region(
        hub_id, create_region_payload(**overrides), PRINT_OPS))


def setup_hub_site_region(site_overrides=None, region_overrides=None,
                          clock=CLOCK_2026_09_01, hub_overrides=None):
    """Clock + hub + one print site + one region.

    Returns (hub, site, region). The site is created before the region so the
    common prefix of nearly every fixture chain is available in one call.
    """
    hub = create_hub_with_clock(clock, **(hub_overrides or {}))
    site = create_site(hub["id"], **(site_overrides or {}))
    region = create_region(hub["id"], **(region_overrides or {}))
    return hub, site, region


def setup_hub_with_two_sites(site_overrides=None, clock=CLOCK_2026_09_01):
    """Clock + hub + sites KOT (PRIORITY) and CED (PROPORTIONAL).

    Returns (hub, site_kot, site_ced).
    """
    from .constants import SITE_CED
    hub = create_hub_with_clock(clock)
    site_kot = create_site(hub["id"], **(site_overrides or {}))
    site_ced = create_site(hub["id"], **SITE_CED)
    return hub, site_kot, site_ced


def setup_two_regions(hub_id):
    """Two regions (North priority 1, South priority 2) in a hub."""
    from .constants import REGION_SOUTH
    north = create_region(hub_id)
    south = create_region(hub_id, **REGION_SOUTH)
    return north, south


def create_position(region_id, **overrides):
    """Create a newsroom position inside a region. Returns the position dict."""
    from .factories import create_newsroom_position_payload
    return get_success_data(api_client.create_newsroom_position(
        region_id, create_newsroom_position_payload(**overrides), NEWSROOM_MANAGER))


def list_sites(hub_id):
    """List a hub's print sites."""
    return get_success_data(api_client.list_print_sites(hub_id, PRINT_OPS))


def list_regions(hub_id):
    """List a hub's regions."""
    return get_success_data(api_client.list_regions(hub_id, PRINT_OPS))


def get_site(site_id):
    """Read a print site."""
    return get_success_data(api_client.get_print_site(site_id, PRINT_OPS))


def get_region(region_id):
    """Read a region."""
    return get_success_data(api_client.get_region(region_id, PRINT_OPS))