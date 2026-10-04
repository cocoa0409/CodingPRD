"""Clock-dependent refresh.

`is_expired` is defined against the logical clock (PRD 3.3: "true once the
logical clock has reached or passed that instant"), and `usage_gb` excludes
expired content (PRD 3.1), so both are a pure function of the clock.  Moving
the clock therefore changes them without any write endpoint being called --
the only operation in the whole API that is not driven by an explicit
transition.  This module re-evaluates the derived state lazily, once per
clock value, before a request is served.
"""

import recompute
from store import store


def refresh():
    if store.refreshed_token == store.clock_token:
        return
    touched_accounts = set()
    for bset in store.sets.values():
        if not store.all_versions_of_set(bset["id"]):
            continue
        before = ({v["id"]: (v["is_expired"], v["recoverable_until_utc"])
                   for v in store.all_versions_of_set(bset["id"])})
        recompute.recompute_version_flags(store, bset)
        after = ({v["id"]: (v["is_expired"], v["recoverable_until_utc"])
                  for v in store.all_versions_of_set(bset["id"])})
        if before != after:
            recompute.recompute_set(store, bset)
            touched_accounts.add(bset["account_id"])

    for account_id in touched_accounts:
        account = store.accounts.get(account_id)
        if account is not None:
            recompute.recompute_account_usage(store, account)
            recompute.recompute_all_agents(store, account_id)

    store.refreshed_token = store.clock_token