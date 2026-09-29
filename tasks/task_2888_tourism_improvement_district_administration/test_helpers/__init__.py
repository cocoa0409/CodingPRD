"""Test infrastructure for the Tourism Improvement District Administration API.

Submodules:

* :mod:`types` — enumerations and entity shapes, named as the PRD names them
* :mod:`constants` — the literal rates, caps, thresholds and clock origin
* :mod:`api_errors` — the error catalogue of PRD 5 and its HTTP status map
* :mod:`api_client` — one method per endpoint of PRD 4
* :mod:`factories` — request payload builders
* :mod:`test_users` — identity headers for the seven roles
* :mod:`assertions` — envelope, money, ratio and identity assertions
* :mod:`fixtures` — composite state builders that use the API only
"""
