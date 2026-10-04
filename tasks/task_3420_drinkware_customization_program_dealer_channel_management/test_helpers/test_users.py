"""Pre-built role headers for every role in the PRD (section 2.1).

Identity rules from the PRD:
- Dealer is entity-backed: X-User-ID must equal the Dealer record's id for any
  ownership-gated call (own record, own applications, own allocations,
  dealer-source claims). Use make_dealer_headers(dealer["id"]) there; the
  shared TEST_USERS["dealer_headers"] constant is a fallback ONLY for tests
  whose outcome does not depend on dealer ownership (400/404 probes).
- Buyer ownership is keyed on buyer_ref == X-User-ID. Use make_buyer_headers
  with the same buyer_ref used in the payload.
- FieldInspector ownership: inspector_user_id on the application must equal
  the acting X-User-ID. Use make_field_inspector_headers(inspector_id).
- Segregation of duties at application decide requires the deciding
  ChannelManager's X-User-ID to differ from both the inspection recorder and
  the docs reviewer, so the shared ChannelManager constants are distinct
  identities (cm-admin opens, cm-docs reviews, cm-1 decides).
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque roles — canonical shared identities.
    "platform_admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
    "channel_manager_headers": build_user_headers("cm-1", "ChannelManager"),
    "channel_manager_admin_headers": build_user_headers("cm-admin", "ChannelManager"),
    "channel_manager_docs_headers": build_user_headers("cm-docs", "ChannelManager"),
    "field_inspector_headers": build_user_headers("fi-1", "FieldInspector"),
    "buyer_headers": build_user_headers("buyer-std", "Buyer"),
    "prepress_tech_headers": build_user_headers("pp-1", "PrepressTech"),
    "production_lead_headers": build_user_headers("pl-1", "ProductionLead"),
    "warranty_agent_headers": build_user_headers("wa-1", "WarrantyAgent"),
    "customer_care_headers": build_user_headers("cc-1", "CustomerCare"),
    # Dealer fallback for non-ownership tests ONLY. Never use for
    # ownership-gated calls — build per-instance via make_dealer_headers.
    "dealer_headers": build_user_headers("test-dealer-1", "Dealer"),
}


def make_dealer_headers(user_id: str) -> dict:
    """Dealer role headers bound to a specific Dealer record id.

    Mandatory for every ownership-gated call: pass the actual dealer's id
    (e.g. make_dealer_headers(dealer["id"]) after creating the dealer).
    """
    return build_user_headers(user_id, "Dealer")


def make_buyer_headers(user_id: str) -> dict:
    """Buyer role headers. The user_id must equal the buyer_ref of every
    order/proof/claim the caller acts on."""
    return build_user_headers(user_id, "Buyer")


def make_field_inspector_headers(user_id: str) -> dict:
    """FieldInspector role headers. The user_id must equal the
    inspector_user_id assigned on the application being scheduled/recorded."""
    return build_user_headers(user_id, "FieldInspector")


def make_channel_manager_headers(user_id: str) -> dict:
    """ChannelManager role headers with a caller-chosen identity; distinct
    identities are required wherever segregation of duties is exercised."""
    return build_user_headers(user_id, "ChannelManager")


def make_platform_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_prepress_tech_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PrepressTech")


def make_production_lead_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ProductionLead")


def make_warranty_agent_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "WarrantyAgent")


def make_customer_care_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "CustomerCare")
