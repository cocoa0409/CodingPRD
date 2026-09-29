"""Domain test helpers for the Rail Demurrage & Detention Billing Dispute service.

Layering:

    constants.py   - literal enum members, defaults and reference-chain instants
    api_errors.py  - the 59 error ids and their fixed HTTP statuses
    types.py       - TypedDict shapes for every persisted resource
    test_users.py  - X-User-Role / X-User-ID header builders
    api_client.py  - one method per declared endpoint (51 of them)
    assertions.py  - domain assertions and instant/pagination helpers
    factories.py   - request payload builders
    fixtures.py    - phased composite setup helpers

The generic envelope validators, the pagination validator and the race
helpers all come from ``prd_bench_local_runner.testing`` and are never
re-implemented here.
"""
