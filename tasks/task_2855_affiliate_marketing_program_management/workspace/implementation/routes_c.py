"""Routes: commission rate cards, tracking links and click ingestion
(PRD 3.3 and 3.4)."""

import serializers as S
import services as SV
from common import (
    CLICK_TYPES, PARTNER_TYPES, PRODUCT_CATEGORIES, ROLE_COMPLIANCE,
    ROLE_FIN_ANALYST, ROLE_FIN_CONTROLLER, ROLE_INGESTOR, ROLE_PARTNER,
    ROLE_PARTNER_MANAGER, ROLE_PROGRAM_ADMIN, authorize, body, db, fail,
    fmt_dt, get_bool, get_enum, get_enum_list, get_instant, get_int, get_str,
    new_row, ordered, paginate, parse_instant, query_filter, respond, touch,
)


def register(app):

    # -- Commission policies ------------------------------------------------

    @app.post("/commission-policies")
    def create_policy():
        authorize([ROLE_PROGRAM_ADMIN])
        payload = body()
        policy_code = get_str(payload, "policy_code", min_len=1, max_len=40)
        category = get_enum(payload, "product_category", PRODUCT_CATEGORIES)
        scope = get_enum_list(payload, "partner_type_scope", PARTNER_TYPES)
        new_rate = get_int(payload, "new_customer_rate_bps", min_v=0, max_v=2000)
        ret_rate = get_int(payload, "returning_customer_rate_bps", min_v=0,
                           max_v=2000)
        effective_from = get_instant(payload, "effective_from")
        effective_to = get_instant(payload, "effective_to")
        for row in db.policies.values():
            if row["policy_code"] == policy_code:
                fail("ERR_INVALID_REQUEST", "policy_code is already registered")
        # Deliberately no window arithmetic here: inverted and overlapping
        # windows are both legal at draft time (PRD 3.3).
        row = new_row(
            policy_code=policy_code, product_category=category,
            partner_type_scope=scope, new_customer_rate_bps=new_rate,
            returning_customer_rate_bps=ret_rate,
            effective_from=fmt_dt(effective_from),
            effective_to=fmt_dt(effective_to), status="DRAFT",
            superseded_by_policy_id=None,
        )
        db.policies[row["id"]] = row
        return respond(S.policy_out(row), 201)

    @app.get("/commission-policies/<pid>")
    def get_policy(pid):
        authorize([ROLE_PROGRAM_ADMIN, ROLE_PARTNER_MANAGER, ROLE_FIN_ANALYST,
                   ROLE_FIN_CONTROLLER])
        return respond(S.policy_out(SV.find_policy(pid)))

    @app.get("/commission-policies")
    def list_policies():
        authorize([ROLE_PROGRAM_ADMIN, ROLE_PARTNER_MANAGER, ROLE_FIN_ANALYST,
                   ROLE_FIN_CONTROLLER])
        rows = ordered(db.policies)
        rows = query_filter(rows, "status")
        rows = query_filter(rows, "product_category")
        rows = query_filter(rows, "superseded_by_policy_id")
        return paginate(rows, S.policy_out)

    @app.post("/commission-policies/<pid>/activate")
    def activate_policy(pid):
        authorize([ROLE_PROGRAM_ADMIN])
        policy = SV.find_policy(pid)
        payload = body()
        expected = get_int(payload, "expected_policy_version")
        if policy["status"] != "DRAFT":
            fail("ERR_INVALID_REQUEST", "only a DRAFT rate card may be activated")
        if expected != policy["version"]:
            fail("ERR_STALE_POLICY_VERSION",
                 "expected_policy_version does not match the rate card version")
        new_from = parse_instant(policy["effective_from"])
        new_to = parse_instant(policy["effective_to"])
        # Rule 37 outranks rule 39: ordering first, overlap second.
        if new_to <= new_from:
            fail("ERR_INVALID_EFFECTIVE_WINDOW",
                 "effective_to must be strictly after effective_from")
        equal_window = []
        for other in ordered(db.policies):
            if other["id"] == policy["id"] or other["status"] != "ACTIVE":
                continue
            if other["product_category"] != policy["product_category"]:
                continue
            if not set(other["partner_type_scope"]) & set(
                    policy["partner_type_scope"]):
                continue
            other_from = parse_instant(other["effective_from"])
            other_to = parse_instant(other["effective_to"])
            if not (new_from < other_to and other_from < new_to):
                continue  # adjacent or disjoint windows are allowed
            if other_from == new_from and other_to == new_to:
                equal_window.append(other)
                continue
            fail("ERR_POLICY_WINDOW_OVERLAP",
                 "the window overlaps an ACTIVE rate card for this category")
        for other in equal_window:
            other["status"] = "SUPERSEDED"
            other["superseded_by_policy_id"] = policy["id"]
            touch(other)
        policy["status"] = "ACTIVE"
        touch(policy)
        return respond(S.policy_out(policy))

    # -- Tracking links -----------------------------------------------------

    @app.post("/affiliates/<aid>/tracking-links")
    def mint_link(aid):
        authorize([ROLE_PROGRAM_ADMIN, ROLE_PARTNER_MANAGER])
        affiliate = SV.find_affiliate(aid)
        payload = body()
        landing_url = get_str(payload, "landing_url", min_len=1,
                              prefix="https://")
        sub_id = get_str(payload, "sub_id", min_len=1, max_len=40)
        window = get_int(payload, "cookie_window_days", required=False,
                         default=30, min_v=1, max_v=90)
        graph = get_bool(payload, "device_graph_enabled", required=False,
                         default=False)
        if affiliate["status"] in ("SUSPENDED", "TERMINATED"):
            fail("ERR_AFFILIATE_SUSPENDED",
                 "a suspended or terminated partner may not mint links")
        for link in SV.links_of(affiliate["id"]):
            if link["sub_id"] == sub_id:
                fail("ERR_INVALID_REQUEST",
                     "sub_id is already used by this partner")
        row = new_row(
            affiliate_id=affiliate["id"], landing_url=landing_url,
            sub_id=sub_id, cookie_window_days=window,
            device_graph_enabled=graph, status="ACTIVE", disabled_reason=None,
        )
        db.links[row["id"]] = row
        affiliate["tracking_link_count"] += 1
        touch(affiliate)
        return respond(S.link_out(row), 201)

    @app.get("/tracking-links/<lid>")
    def get_link(lid):
        authorize([ROLE_PROGRAM_ADMIN, ROLE_PARTNER_MANAGER, ROLE_COMPLIANCE,
                   ROLE_PARTNER, ROLE_INGESTOR])
        return respond(S.link_out(SV.find_link(lid)))

    @app.post("/tracking-links/<lid>/disable")
    def disable_link_route(lid):
        authorize([ROLE_PROGRAM_ADMIN, ROLE_PARTNER_MANAGER, ROLE_COMPLIANCE])
        link = SV.find_link(lid)
        payload = body()
        reason = get_str(payload, "reason", min_len=1)
        if link["status"] != "ACTIVE":
            fail("ERR_TRACKING_LINK_DISABLED", "the link is already disabled")
        SV.disable_link(link, reason)
        return respond(S.link_out(link))

    @app.post("/tracking-links/<lid>/clicks")
    def ingest_click(lid):
        authorize([ROLE_INGESTOR, ROLE_PROGRAM_ADMIN])
        link = SV.find_link(lid)
        payload = body()
        occurred_at = get_instant(payload, "occurred_at")
        device_id = get_str(payload, "device_id", min_len=1, max_len=64)
        click_type = get_enum(payload, "click_type", CLICK_TYPES)
        household_id = get_str(payload, "household_id", required=False,
                               default=None, min_len=1, max_len=64)
        referrer = get_str(payload, "referrer_domain", required=False,
                           default=None, min_len=1, max_len=120)
        keyword = get_str(payload, "paid_search_keyword", required=False,
                          default=None, min_len=1, max_len=120)
        trademark = get_bool(payload, "is_trademark_term", required=False,
                             default=False)
        affiliate = db.affiliates.get(link["affiliate_id"])
        if affiliate is not None and affiliate["status"] in ("SUSPENDED",
                                                            "TERMINATED"):
            fail("ERR_AFFILIATE_SUSPENDED",
                 "clicks cannot be ingested for a partner out of good standing")
        if link["status"] != "ACTIVE":
            fail("ERR_TRACKING_LINK_DISABLED",
                 "clicks cannot be ingested through a disabled link")
        row = new_row(
            mutable=False, tracking_link_id=link["id"],
            occurred_at=fmt_dt(occurred_at), device_id=device_id,
            household_id=household_id, click_type=click_type,
            referrer_domain=referrer, paid_search_keyword=keyword,
            is_trademark_term=trademark,
        )
        db.clicks[row["id"]] = row
        # Every still-unattributed order whose cookie window this click falls
        # inside has its candidate count refreshed and its version bumped.
        for conv in ordered(db.conversions):
            if conv["attribution_status"] != "UNATTRIBUTED":
                continue
            if not SV.in_cookie_window(occurred_at,
                                       parse_instant(conv["placed_at"]),
                                       link["cookie_window_days"]):
                continue
            conv["candidate_click_count"] = len(SV.eligible_clicks(conv))
            touch(conv)
        return respond(S.click_out(row), 201)

    @app.get("/tracking-links/<lid>/clicks")
    def list_link_clicks(lid):
        authorize([ROLE_PROGRAM_ADMIN, ROLE_COMPLIANCE, ROLE_INGESTOR])
        link = SV.find_link(lid)
        rows = SV.clicks_of_link(link["id"])
        rows = query_filter(rows, "click_type")
        return paginate(rows, S.click_out)
