## Step 1: Create task directory — 2026-09-05T15:56:15.767426900Z

Created /home/ubuntu/github/CodingPRD/tasks/task_2914_airline_distribution_offer_content_management and its workspace/ subdirectory (index pre-assigned by orchestrator invocation; no auto-allocation performed).


## Step 2: Generate scaffold — 2026-09-05T17:07:24.655562422Z

All three scaffold artifacts are complete and lint-clean.

**Files** (all in `/home/ubuntu/github/CodingPRD/tasks/task_2914_airline_distribution_offer_content_management/`):
- `SCAFFOLD.yaml` — 2132 lines, §1.0–§1.7 only (no `scaffold_difficulty_design` / `scaffold_corner_design` keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1378 lines, single key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — 2613 lines, single key `scaffold_corner_design`

**Counts**
- §1.1 entities: 14 (Channel, SurchargeRule, DistributionPartner, FareFiling, AncillaryProduct, BundleDefinition, AgencyAgreement, CorporateContract, Offer, OfferItem, Order, ServiceRequest, PartnerCertification, ConnectivityTest); 7 state machines, 2 concurrency rules, 8 calculations (2 dual-variant), 32 validation priorities, 43 errors, 6 roles (segregation of duties)
- §1.5 endpoints: 43 (`api_prefix: ""`)
- §1.8: 9 rule_ids × 2 instances = **18 instances**, all nine differentiation clauses honoured
- §1.9: **9 sections / 85 instances** — 57 full `test_recipe` instances + 28 `excluded_because` stubs (entities 12, state_machines 11, calculations 15, validations 12, endpoints 6, errors 17, rbac 4, cross_cutting_complexity_layers 7, consistency_model 1)

**Verification**
- All three files parse with `yaml.safe_load`; instance names unique within §1.9 and zero overlap with §1.8; every stub cites an existing §1.8 instance and carries no `test_recipe`; every `${var}` in every call and assert is bound by an earlier `captures:` (0 unbound); all 43 declared errors are reachable (34 triggered directly in §1.9, the rest triggered in §1.8 and stubbed); all money/score literals produced by executed `Decimal`/`ROUND_HALF_UP` code in `/tmp/task_2914_scaffold/`.

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
(Coverage line from the same run: 43 endpoints, 14 entities, 18 §1.8 instances, 57 §1.9 instances, 683 calls scanned.)

**Two things to note**
1. `workspace/` (empty dir) and `worklog.md` (4 lines) are untouched — original 15:56 timestamps; nothing was deleted, moved, or written inside `workspace/`, and no processes were killed.
2. I stripped the single leading line `Generate task harder than expert level!` from `SCAFFOLD.yaml`'s `scenario:` block (the domain text itself is verbatim). That directive otherwise propagates from the scenario key into PRD.md; re-linted clean afterwards.

Orchestrator note: verified independently — `grep -rn "harder than expert" SCAFFOLD*.yaml` returns nothing, so the difficulty directive cannot reach PRD.md via the scaffold.

## Step 3: Copy shared files — 2026-09-05T17:07:24.669511503Z

Copied /home/ubuntu/github/CodingPRD/INSTRUCTION.md → workspace/INSTRUCTION.md (53 lines).

## Step 4: Generate PRD — 2026-09-05T17:19:53.377376549Z

PRD generated at `workspace/PRD.md`.

## Truncation check

- **Line count: 458** (94,408 bytes), built as 6 incremental chunks (1 Write + 5 `cat >>` heredocs), never a single giant Write.
- Document ends at a real section boundary: the last row of the §5 Error Code Catalogue table, complete and pipe-terminated. Last 3 lines verbatim:
  ```
  | `ERR_READINESS_BELOW_MINIMUM` | 422 Unprocessable Entity |
  | `ERR_CONTRACT_CAP_EXCEEDED` | 422 Unprocessable Entity |
  | `ERR_PAYMENT_AMOUNT_MISMATCH` | 422 Unprocessable Entity |
  ```
- No audit footer, no contract-report block inside PRD.md.

## Section list

§1 Introduction (3 paragraphs) · §2 Global Specifications — 2.1 Distribution Actors and RBAC, 2.2 API Response Structure (verbatim), 2.3 Pagination and List Ordering, 2.4 Resource Identity/Versioning/Audit Trail, 2.5 The Logical Clock and Window Arithmetic, 2.6 Money, Percentages and Rounding Discipline, 2.7 Optimistic Concurrency on Distribution Content, 2.8 Content Access Tiers, 2.9 Cascade Propagation and Hierarchical Consistency, 2.10 Validation Precedence and Path Resolution, 2.11 Regulatory Display and Disclosure Acknowledgement · §3 Business Logic — 3.1 Channel Configuration/Content Policy/Surcharge Structure, 3.2 Fare Content: Filing/Activation/Revision/Catalogue, 3.3 Distribution Partners, Incentive Agreements and the Negotiation Cycle, 3.4 Corporate Contracts and Negotiated-Fare Traceability, 3.5 Constructing and Publishing a Channel Offer, 3.6 Orders: Payment and Fulfilment as Independent Dimensions, 3.7 Servicing Parity: Change/Refund/Void, 3.8 Connectivity Certification and the Shared Test Environments, 3.9 Distribution Cost per Booking, Two Ways · §4 Endpoint Definitions (43 rows, 4 columns) · §5 Error Code Catalogue (43 rows, 2 columns).

## Hard Contract Reports

Field coverage check: entities[].fields 123/123 present, 0 missing; endpoints request_body/input 82/82; query_params 20/20; path_params 1/1. Status: PASS. (Verified with a script that strips fenced code blocks, extracts every backticked token, and diffs against the scaffold — first pass surfaced exactly one miss, `order_id`, which was added to §3.7.)

Rule coverage check: validations[] with priority 32/32 expressed in prose (§2.10 states the full 1→32 precedence with each error_id and each applies_to scope enumerated); concurrency_rules[] OCC rejections 2/2 (write_endpoint + expected_partner_version / expected_fare_filing_version + ERR_STALE_PARTNER_VERSION / ERR_STALE_FARE_FILING_VERSION + HTTP 412 all named in §2.7, framed purely as stale-version, no "simultaneously"/"race" wording); state_machines[].transitions 46/46 across FareFiling, AgencyAgreement, Offer, Order (both dimensions), ServiceRequest, PartnerCertification, ConnectivityTest — every from/to pair, every precondition paired with its error_id, every side effect including all 4 refund-apply hops and all 4 CERTIFIED→REVOKED hops; calculations[] 8/8 fully expressed in prose with no operator syntax and no fuzzy words (offer_line_pricing round-then-sum pinning, surcharge_amount inclusive threshold + round-before-clamp, agency_incentive_accrual 5-step marginal walk with the 0.025 reference divisor, distribution_cost_per_booking both variants, certification_readiness_score STRICT/PROVISIONAL, refund_settlement 5 pinned steps, disclosure_completeness with the empty-required-set boundary, connectivity_slot_occupation Rules A and B); validations[] conditions 32/32 matchable to error_id; endpoints side_effects/applies_to 43/43; entities[].fields structured content 123/123 reconstructible from prose (SurchargeRule and OfferItem explicitly declared to carry only id and created_at, with updated_at and version absent); sibling-branch symmetry 7/7 groups with equal prose density, 0 asymmetric. Status: PASS.

Path purity check (§3 only): 797 backtick tokens scanned, 0 starting with `/`, 0 bare HTTP-method tokens, 0 method+path combined tokens. Status: PASS.

## Notes

- §2.2 verified byte-identical to `section-2.2-response-structure.md`.
- Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped or referenced; their mtimes are unchanged.
- No difficulty meta-language present (scan for "harder than", "expert level", "approximat*", "roughly", "conservativ*" returns nothing — one incidental "deliberately conservative" was reworded to "deliberately narrow in scope").
- One scaffold internal inconsistency reconciled rather than invented around: §1.4 priority 32 and the CAPTURE precondition say `payment_amount_cents` must equal `Offer.total_cents`, while the §1.6 error condition says `Order.net_revenue_cents`. Since `net_revenue_cents` is frozen to `Offer.total_cents` at order creation these are the same figure, and §3.6 says so explicitly.
- Unknown-role handling reconciled to the §1.6 catalogue (unknown role name → `ERR_UNAUTHENTICATED` 401; recognised-but-unlisted role or ownership mismatch → `ERR_UNAUTHORIZED` 403).

Orchestrator verification: independently ran `wc -l` (458), `tail -25` (ends on the complete final `ERR_PAYMENT_AMOUNT_MISMATCH` table row), `grep -n "^#"` (28 headings, §1 through §5 all present and in order), and a difficulty-leak grep (no match). PRD accepted, no regeneration needed.

## Step 6: Generate implementation — 2026-09-05T17:50:11.886368347Z

Implementation is complete, compiles, boots from a fresh process, and passes an end-to-end smoke run with zero failures.

## Modules (all under `workspace/implementation/`)

| File | Lines | Role |
|---|---|---|
| `app.py` | 72 | `create_app()`, blueprint registration, `ApiError`/`HTTPException`/bare-`Exception` handlers, `app.run(host="0.0.0.0", port=$PORT)` |
| `store.py` | 144 | in-memory `Store` (14 dicts), logical clock (`2026-08-01T00:00:00.000Z`), `now/new_id/iso/parse_instant`, per-request-idempotent `bump()`, sort keys, `get_or_404` |
| `errors.py` | 72 | `ApiError`, all 45 error ids → HTTP status, default messages |
| `envelope.py` | 75 | object/list/error envelopes, `pagination()`, `paginate()` |
| `validators.py` | 212 | typed body/query extractors (int rejects bool, `Decimal` scales, instants, enums, string arrays) |
| `auth.py` | 63 | six roles, 401 vs 403 split, entity-backed `Actor.require_owner` |
| `serializers.py` | 272 | one `*_out` per entity; mutable vs immutable shapes |
| `calc.py` | 198 | pure C1–C8 arithmetic (pricing, surcharge, marginal incentive bands, dual cost + dual readiness variants, refund settlement, disclosure diff, closed-interval slot geometry) |
| `services.py` | 292 | validity states, lazy expiry, ledger recomputes, readiness refresh, reserved minutes, all cascades |
| `routing.py` | 64 | `Pending`/`resolve_owned`/`precheck_self`/`precheck_ref` so §2.10 ordering (403 before 404 before body checks) holds |
| `routes/clock.py` | 19 | clock |
| `routes/channels.py` | 139 | channels, content policy, surcharge rules |
| `routes/partners.py` | 40 | distribution partners |
| `routes/fares.py` | 268 | filings, state machine, revisions, ancillaries, bundles |
| `routes/agreements.py` | 172 | agreements, OCC, negotiation rounds, SoD |
| `routes/contracts.py` | 98 | corporate contracts |
| `routes/offers.py` | 251 | offer construction/pricing, items, publish |
| `routes/orders.py` | 273 | orders, payment, fulfilment, service-request opening |
| `routes/servicing.py` | 132 | review, quantification, apply |
| `routes/certifications.py` | 297 | certifications, slot scheduling, outcomes, decisions |
| `routes/__init__.py` | 1 | package marker |
| `start.sh` | 15 | `PORT` default, flask presence check, `exec python3 app.py` (foreground) |
| `requirements.txt` | 1 | `flask` |

Total 3170 lines. Every module `py_compile`-clean; `__pycache__` removed.

## Endpoints

**43 of 43** from the PRD §4 table, verified by set-diffing Flask's `url_map` against the table: zero missing, zero extra.

## Smoke evidence

Port **27431** (fresh boot after `kill $(lsof -ti tcp:27431)`; port confirmed free again at the end — no broad `pkill` was ever used).

Boot log: `* Running on all addresses (0.0.0.0)` / `* Running on http://127.0.0.1:27431` (Werkzeug 3.1.8, Python 3.14.4), answering ~4s after launch.

Request/response pair:

```
POST /channels  (X-User-Role: PlatformAdmin)  ->  HTTP/1.1 201 CREATED
{"meta":{"api_request_id":"req_EE8WRRWTEPU9TELL0NO2","api_request_timestamp":"2026-08-01T00:00:00.000Z"},
 "response_type":"object","data":{"id":"46882091-...","created_at":"2026-08-01T00:00:00.000Z",
 "version":1,"channel_code":"NDC-SMOKE","content_tier_rank":3,...,"booking_count":0,
 "activity_cost_cents":0,"cost_per_booking_flat_cents":0,"cost_per_booking_activity_cents":0}}
```

The ~45-call script (`/tmp/task_2914_impl/smoke.py`, scratch only) reported `grep -c FAIL` → **0** across channel/surcharge, partners, filing lifecycle, catalogue, agreement negotiation with SoD, offer pricing, publish, order, capture, ledgers, ticketing, full refund lifecycle, certification with slot-buffer conflict, clock move, and 9 negative paths (401 missing/blank/unknown role, 403 role-not-listed, 400 bad limit, 404, 409 duplicate, 412 stale version, 422 partner type).

Arithmetic cross-checks against the PRD text:
- Lines: `(1,FARE,YFLEX,250000,262500)`, `(2,BUNDLE_ANCILLARY,BAG20,4000,3780)`, `(3,BUNDLE_ANCILLARY,SEAT-XL,2500,2363)` (2362.5 half-up), `(4,SURCHARGE,GDSFEE,5373,5000)` — raw 5373 clamped to `max_cents`, list=raw/net=clamped.
- Incentive accrual `6567` = 273643 × 0.010 × 1.5 (multiplier) × 1.6 (0.04/0.025), capped then rounded once.
- Refund settlement `base 266280 → fee 13314 (5%) → total 252966 → clawback 2530` (252966 × 0.010, tier as stored at approval, audit-only — confirmed against PRD lines 313–320: the clawback is *not* subtracted from `incentive_accrued_cents`).
- Refund cascade decremented `booking_count` 1→0 and zeroed both channel cost-per-booking variants.

Isolation held: `test_suite/`, `test_helpers/`, and all sibling `task_*/` directories were never read; only `workspace/implementation/` was written, plus scratch under `/tmp/task_2914_impl/`.

Orchestrator note: Steps 5 and 6 were launched as background agents in immediate succession while `test_suite/` was still empty, preserving the impl generator's physical isolation from the test artifact.

## Step 5: Generate unit tests — 2026-09-05T18:38:11.24170189Z

Stage 1 + Stage 2 are complete. Every non-stub instance in both design indices is translated; nothing was skipped.

## Output files (task root)

`test_helpers/` (2,476 lines): `__init__.py` 76, `api_client.py` 361, `api_errors.py` 110, `assertions.py` 360, `constants.py` 204, `factories.py` 436, `fixtures.py` 618, `test_users.py` 98, `types.py` 213.

`test_suite/` (5,648 lines, 99 tests): `conftest.py` 49; `test_02` 142/4, `test_03` 173/2, `test_04` 109/2, `test_05` 155/2, `test_06` 141/3, `test_07` 97/2, `test_08` 250/5, `test_09` 425/7, `test_10` 434/8, `test_11` 182/3, `test_12` 295/4, `test_13` 531/12, `test_14` 369/7, `test_15_pricing_calculations` 492/7, `test_16_validation_boundaries` 330/6, `test_17_endpoint_behaviours` 371/6, `test_18_error_catalogue` 481/10, `test_19_rbac_and_ownership` 293/4, `test_20_cross_cutting_layers` 329/5 (lines/tests).

## Coverage

- **§1.8 (queue A, Difficulty)**: 18 instances translated, **0 skipped** — 42 tests (≥2 per instance).
- **§1.9 (queue B, Corner)**: **57 non-stub instances translated, 0 skipped** — 57 tests (≥1 each). The 29 `- excluded_because:` stubs were deliberately not translated. Per-section: entities 12, state_machines 7, calculations 7, validations 6, endpoints 6, errors 10, rbac 4, cross_cutting_complexity_layers 4, consistency_model 1.
- `verify_tags.py`: covered 18/18 and 57/57, `dangling tags: []`, 99 tagged docstrings — exactly one `Design:` line per test, always the last docstring line.

## Verification performed

- `python3 -m py_compile` clean on all 28 files.
- Verbatim-quote checker over all 242 PRD citations: **checked 242, bad 0** (whitespace-normalised grep against `workspace/PRD.md`).
- Unused/undefined-name scan: no unused imports, no undefined symbols.
- No occurrence of the word "scaffold" anywhere in emitted code; no duplicate test function names; `__pycache__` removed.

## Fixes made to earlier files while verifying

- `test_suite/test_10_certification_and_test_slots.py`: four citations had silently dropped the PRD's markdown emphasis (`**The teardown-buffer rule**`, `on **both** sides`, `**The environment capacity rule**`/`applies **no** buffer`, `recomputation of **both** readiness variants`), which made them non-verbatim. Restored.
- `test_suite/test_14_state_machine_walks.py`: removed an unused `PRICING_ANALYST_HEADERS` import.

## PRD-first corrections against inaccurate design-index recipes (no test weakened, no gap papered over)

- Contract's third validity value is **`LAPSED`** (index said `EXPIRED`) — §3.4.
- Certification environments are exactly **`CERT_ENV_A`/`CERT_ENV_B`** (index invented `CORNER_ENV`/`OTHER_ENV`) — §3.8.
- Design-index HTTP statuses are unreliable (several recipes claim 422 where the PRD map says 409/412), so `validate_error` is never passed `expected_status`; `api_errors.HTTP_STATUS_CODES` governs.
- Blank-header cases send `""`, never whitespace (requests raises `InvalidHeader`).
- The bulk-suspension recipe's two co-`ACTIVE` FRA-JFK ECONOMY filings are legal because §3.2's exclusivity key includes `fare_basis_code`.
- Money is sent as JSON integers throughout; every instant literal is a full ISO-8601 instant with milliseconds and `Z`.

Nothing was written inside `workspace/`; `worklog.md` untouched; no server started, no process killed; scratch files confined to `/tmp/task_2914_tests/`.

Orchestrator note: verified `test_helpers/` and `test_suite/` are both at the task root (not under `workspace/`), and `workspace/` contains only INSTRUCTION.md, PRD.md, implementation/, run_sweep.sh.

## Step 7: Run tests and iterate — 2026-09-05T18:59:53.372628686Z

All 8 rounds are green.

## Summary

**Iterations run:** 2 (sweep 1 → diagnose/fix → sweep 2 clean).

**Tests deleted:** none. All four failures were test-artifact bugs under STEP 2 (TEST IS WRONG); every asserted rule was verbatim-covered by PRD and uniquely derivable, so nothing failed STEP 1a/1b.

**Fixes applied to `test_helpers/`:** none required. The four historically common fixture pitfalls were already absent (money as ints, full 3-digit ISO instants, `""` blank headers, `canonical_instant` normalisation).

**Fixes applied to `test_suite/`:**

1. `test_suite/test_16_validation_boundaries.py` — `test_the_sale_window_closes_on_its_own_end_instant` (line ~155): `validate_success(api.create_offer(...))` defaulted to `expected_status=200`, but PRD §4 states "Operations that bring a new resource into existence return HTTP 201 with the created resource in `data`". Added `expected_status=201`. The fix makes the test stricter/more PRD-faithful, not weaker.
2. Same file — `test_the_travel_window_includes_its_own_end_instant` (line ~188): identical missing `expected_status=201` on the on-the-bound `create_offer`.
3. `test_suite/test_18_error_catalogue.py` — `test_a_corporate_account_cannot_enter_connectivity_certification` (line ~236): identical missing `expected_status=201` on the accepted `create_certification`.
4. `test_suite/test_09_servicing_refund_settlement.py` — `test_refund_apply_is_blocked_until_the_channel_carries_refund_parity` (line ~370): the test asserted `revised["version"] == channel["version"] + 1` against a creation-time snapshot (v1), but the intervening `fx.capture_payment` legitimately bumps the channel to v2 under PRD §2.9 ("Every hop of every cascade refreshes the touched resource's `updated_at` and increases its `version` by 1") plus the §3.6 capture cascade (booking count + distribution-cost recompute). Rebased the assertion on a fresh `fx.read_channel` taken immediately before the revision, preserving the PRD §3.1 "+1 on content-policy revision" rule. Empirically confirmed via a manual probe on port 27431: 1 → 2 (capture) → 3 (revise); server since killed by port, port now free.

**Fixes applied to `implementation/`:** none. The implementation was PRD-faithful in all four cases; no endpoint, field, side effect, or seeded data was added or removed.

**Final sweep (all 8 rounds, quoted from the results files):**

| file | passed/total |
|---|---|
| `results.1.json` | 99/99 (mtime 2026-09-05 18:51:35.322878027 +0000) |
| `results.2.json` | 99/99 (18:51:35.185242385) |
| `results.3.json` | 99/99 (18:51:35.252322157) |
| `results.4.json` | 99/99 (18:51:35.320491659) |
| `results.5.json` | 99/99 (18:51:35.321257901) |
| `results.6.json` | 99/99 (18:51:35.379727414) |
| `results.7.json` | 99/99 (18:51:35.195221286) |
| `results.8.json` | 99/99 (18:51:35.319738026) |

All files live in `workspace/implementation/`, `failed == 0` in every round, zero flakiness across the union. `worklog.md` untouched; scratch confined to `/tmp/task_2914_step7/`.

Orchestrator verification: independently re-read all 8 `results.$i.json` with a json loader — every file reports `passed=99 total=99 failed=0`, mtimes clustered at 2026-09-05T18:51:35Z (one joined sweep, not eight staggered relaunches). The sweep ran through `workspace/run_sweep.sh` under `setsid nohup`, so no round was reaped; `sweep.round.1.log` shows 99 PASSED / 0 FAILED and a clean `Duration: 171.5s` + port-release line. Step 8 is NOT skipped: Step 7 recorded 4 `test_suite/` fixes (0 deletions, 0 `implementation/` fixes).

## Step 8: Finalize PRD — 2026-09-05T19:08:45.424204723Z

## PRD.md vs PRD_FINALIZED.md
- Line counts: 458 → 458 (0.0% line delta). Word count 13,165 → 13,244 (+79 words, +0.6%). One sentence inserted inside one existing paragraph; no new sections.

## Changes
- **§2.9 Cascade Propagation and Hierarchical Consistency** — *insert* — added one sentence pinning that the `updated_at`/`version` stamp is applied **at most once per resource per request**, so a resource touched by two hops of the same request (channel on a payment capture; channel on hops two and four of an applied refund) gains exactly +1 in total, not +1 per hop — `implementation/store.py:99-112` (the `bump()` helper's per-request `g._touched` guard, the only place `version` is ever incremented), exercised at `implementation/routes/orders.py:169-176` and `implementation/routes/servicing.py:104-118`.

## Pre-edit search log (the one edit)
(a) **Subject identified:** how many times a single resource's `version`/`updated_at` may advance within one request, specifically the channel under the payment-capture cascade (Step 7 item 4's rebased assertion).

(b) **Impl paths enumerated:** grepped `"version"` and `bump(` across all of `implementation/` and read every hit — `store.py:99-112` (`bump`, idempotent per request via `flask.g._touched` keyed on object identity; `store.py:111` is the **sole** version increment in the codebase, and `store.py:121` sets `version: 1` at creation). Read every multi-touch site: `routes/orders.py:158-181` (CAPTURE → `recompute_booking_count` then `recompute_channel_costs`, i.e. two channel touches; VOID branch touches no channel), `services.py:188-206` (both recompute helpers call `bump(channel)`), `routes/servicing.py:100-131` (REFUND: order once, channel at hop 2 and hop 4, agreement once via `recompute_agreement_accrual`; CHANGE: order once + channel costs once; VOID: order only), `services.py:22-26` (lazy offer expiry — can bump an offer on a GET, and coexists with a later bump in the same request), `services.py:248-292` (offer-withdrawal loops, `suspend_/reinstate_agreements_for_pair`, `set_partner_certification_status`), `routes/agreements.py:57,77`, `routes/fares.py:165,213`, `routes/channels.py:97,127`, `routes/certifications.py:171,217,225,238-292` (including REVOKE, which runs `_cancel_scheduled_tests` and `suspend_agreements_for_pair` in the same request). Every enumerated path is consistent with "+1 in total per resource per request"; multi-hop repeats only ever occur on the same resource, never producing +2. Also re-read PRD §3.6, §3.7, §3.9, §2.4 and §2.7 to confirm no existing sentence claims a per-hop count that the new wording would contradict.

(c) **Wording adjustment:** scoped the claim to "per resource per request" (not "per cascade") so distinct resources each still take their own +1; kept the original per-hop sentence verbatim and appended the cap rather than rewriting it; named the two concrete multi-touch cascades as illustrations ("as ... does") rather than as an exhaustive list, so the rule stays true for paths Step 7 never exercised (lazy expiry, revoke fan-out, agreement supersede).

## Items that needed no edit
- Diff items 1-3 (missing `expected_status=201` on `create_offer` / `create_certification`): pure test-artifact bugs. PRD §4 already states verbatim that "Operations that bring a new resource into existence return HTTP 201 with the created resource in `data`", and all 14 creation handlers in `implementation/` pass `201` to `respond_object`. No silence, no mismatch, no PRD change.
- Diff item 4 was partly a pure test bug (stale snapshot) but did expose a genuine PRD/impl divergence in the *count* of version increments, which is the single edit above. A fresh implementer reading PRD.md literally would have produced +2 on the channel per capture.

Orchestrator verification: `diff PRD.md PRD_FINALIZED.md` shows exactly one changed line (the §2.9 paragraph), confirming the patch is genuinely minimal and that PRD_FINALIZED.md is not byte-identical.

## Step 9: Complete PRD — 2026-09-05T19:35:34.871723770Z

Run as THREE sequential module-partitioned passes over one shared `workspace/PRD_COMPLETED.md` (pass 1 performed the `cp` from PRD_FINALIZED.md; passes 2 and 3 edited in place and were explicitly forbidden to re-copy). A single-shot full-impl scan reliably under-scans a 3,170-line implementation, so the 21 impl modules were partitioned: pass 1 = core/cross-cutting, pass 2 = arithmetic + content/commercial domain, pass 3 = transactional/order-lifecycle domain.

### Overall totals
- `PRD_FINALIZED.md` 458 lines / 94,879 chars → `PRD_COMPLETED.md` 462 lines / 114,369 chars (**+19,490 chars, +4 lines**).
- **54 edits total: 49 ambiguity-pins, 5 mismatch-revisions.**
- 100 changed lines vs PRD_FINALIZED.md; 28 headings unchanged (no section added or removed); §5 still carries all 43 `ERR_*` rows; file still ends at `| `ERR_PAYMENT_AMOUNT_MISMATCH` | 422 Unprocessable Entity |`.

### Pass 1 — core layer (app.py, store.py, errors.py, envelope.py, validators.py, auth.py, routing.py, serializers.py, routes/clock.py)
462 lines / 102,473 chars. **16 ambiguity-pins, 1 mismatch-revision.**
- §2.1 — insert — ambiguity — role names matched exactly (no case-folding/trimming); `X-User-ID` taken verbatim — `auth.py:53-59`
- §2.1 — insert — ambiguity — ownership compares the target's own `partner_id`, a sub-resource's via its parent, targets with no partner reference are unrestricted, and top-level lists are never ownership-filtered — `auth.py:37-47`, `routing.py:26-42`
- §2.2 — insert — ambiguity — `api_request_id` = `req_` + exactly 20 chars from `[A-Z0-9]` — `envelope.py:10,18-19`
- §2.2 — insert — ambiguity — `api_request_timestamp` read from the logical clock, not host wall time — `envelope.py:22-23`
- §2.3 — insert — ambiguity — `limit`/`offset` base-10 integers (non-integer → 400), empty value = absent, offset past the end = empty page — `envelope.py:50-70`
- §2.3 — insert — ambiguity — `created_at` ties broken by insertion order (total, stable) — `store.py:130-131`, `services.py:34`
- §2.3 — insert — ambiguity — filter semantics: empty filter = absent, out-of-domain enum → 400, identifier/code filters never resolved (empty page, not 404), filters conjunctive and applied before pagination — `validators.py:199-212`
- §2.4 — insert — ambiguity — every other declared field always present, valueless ones rendered as JSON `null` not omitted — `serializers.py:20-30,166-189`
- §2.5 — insert — ambiguity — `current_utc` required; clock moves forward or backward freely; response is 200 with `data` = `{"current_utc": ...}` — `routes/clock.py:12-19`
- §2.5 — insert — ambiguity — accepted client instant syntax (bare date, `T`/`t`/space, optional seconds/fraction, `Z`/`z`/`±HH:MM`/`±HHMM`, missing zone = UTC); anything else 400 — `store.py:68-96`
- §2.6 — insert — ambiguity — money/count fields accept only JSON integers (`1000.0`, booleans, numeric strings → 400) — `validators.py:83-90`
- §2.6 — insert — ambiguity — percentages accept any JSON number but not booleans/strings; excess decimals → 400 — `validators.py:105-128`
- §2.10 step 2 — insert — ambiguity — body-borne owner fields checked at step 2, before shape and resolution — `routing.py:45-64`
- §2.10 step 3 — insert — ambiguity — absent/empty body = `{}`, non-object → 400, explicit `null` ≡ omitted, undeclared fields ignored, strings never trimmed — `validators.py:16-29`
- §3.4 — **revise — mismatch** — `account_code` is NOT printed onto offers/orders (PRD claimed it was); it lives only on the contract — `serializers.py:154` vs `166-189,206-223`
- §4 — insert — ambiguity — a trailing slash names the same endpoint — `app.py:35`
- §5 — insert — ambiguity — unrouted path → `ERR_INVALID_REQUEST` 404, unsupported method → same id 405, internal failure → `ERR_INTERNAL` 500 (the one id outside the table) — `app.py:45-61`
Cross-check: all 43 catalogued ids match `errors.py:ERROR_HTTP` exactly (0 mismatches, 0 PRD-only); every `ERR_*` raised anywhere in impl is catalogued.

### Pass 2 — arithmetic + content/commercial (calc.py, services.py, routes/{channels,partners,fares,agreements,contracts}.py)
462 lines / 109,539 chars (+7,066). **20 ambiguity-pins, 2 mismatch-revisions.**
- §3.1 — revise — mismatch — `content_markup_pct` narrowed to non-surcharge lines; surcharge lines never carry the markup — `services.py:103-171`
- §3.1 — insert — ambiguity — `required_disclosure_codes`: any entry count, non-distinct entries, no per-code length limit — `routes/channels.py:40`
- §3.1 — revise — ambiguity — content-policy revision: `content_tier_rank` recomputed only when `content_tier` supplied; omitted/`null` fields untouched; bodyless call still bumps `version` — `routes/channels.py:77-98`
- §3.1 — insert — ambiguity — `surcharge_code` not unique within a channel — `routes/channels.py:105`
- §3.1 — insert — ambiguity — `max_cents` required, clamps/threshold unbounded above, `max>=min` is a shape check preceding channel path resolution — `routes/channels.py:111-114`
- §3.2 — insert — ambiguity — `reason` up to 2,000 chars, validated then discarded; `to_state` accepted from all six states so `DRAFT`/`SUPERSEDED`/self is 409 not 400 — `routes/fares.py:140-152`
- §3.2 — insert — ambiguity — a `DistributionManager` naming any `to_state` but `SUSPENDED` gets `ERR_UNAUTHORIZED`, decided before the filing id resolves — `routes/fares.py:144-148`
- §3.2 — insert — ambiguity — `expected_fare_filing_version` below 1 is 400, not 412 — `routes/fares.py:178`
- §3.2 — insert — ambiguity — a revision's `filed_by_user_id` is the reviser's, not the base's — `routes/fares.py:206`
- §3.2 — insert — ambiguity — `origin`/`destination` filters compared verbatim, case-sensitively, unvalidated — `routes/fares.py:121-125`
- §3.2 — revise — ambiguity — duplicate `ancillary_code` is `ERR_INVALID_REQUEST`, case-sensitive — `routes/fares.py:229-230`
- §3.2 — revise — ambiguity — duplicate `bundle_code` is `ERR_INVALID_REQUEST` decided before member resolution; `ancillary_codes` entries need not be distinct; first unresolvable entry reported; `bundle_discount_pct` required — `routes/fares.py:248-258`
- §3.3 — insert — ambiguity — `iata_code`/`partner_name` not unique; `home_country` form-checked only — `routes/partners.py:19-22`
- §3.3 — insert — ambiguity — `expected_partner_version` below 1 is 400, not 412 — `routes/agreements.py:35`
- §3.3 — insert — ambiguity — the open-agreement supersede is confined to agreement rows: no offer withdrawal, no ledger or cost recompute even for a `SIGNED` row — `routes/agreements.py:52-57`
- §3.3 — insert — ambiguity — action↔role binding (`ERR_UNAUTHORIZED`) enforced after 404/400 but after the §2.1 ownership check; `note` 2,000 chars, discarded — `routes/agreements.py:115-131`
- §3.3 — revise — ambiguity — omitted `proposed_incentive_pct` on `COUNTER`/`PROPOSE` leaves the stored percentage; supplied on `ACCEPT`/`WITHDRAW` it is validated then ignored — `routes/agreements.py:155-170`
- §3.3 — insert — ambiguity — no negotiation action has an edge out of `SIGNED`/`SUSPENDED`; agreements discoverable by `partner_id`, `channel_id`, `status` — `routes/agreements.py:90-110,134-139`
- §3.3 — insert — ambiguity — suspend/reinstate sweep the whole pair, so a pair can carry more than one `SIGNED` agreement; "the" signed agreement is the most recently created — `services.py:58-66,282-286`
- §3.3 — insert — ambiguity — every accrual recomputation bumps `updated_at`/`version` even when both figures are unchanged; `incentive_multiplier` read live — `services.py:209-223`
- §3.4 — insert — ambiguity — `negotiated_fare_filing_id` need not be private or in any state and may be shared across contracts; `account_code` not unique; contracts have no status and no update; `corporate_partner_id` resolves first — `routes/contracts.py:37-47`
- §3.5/§3.9 — insert — ambiguity — one priced line per array entry (repeats yield repeat lines; a code in both arrays yields one of each kind); `booking_count` re-derived as the PAID-population size, not an independent counter — `services.py:122-144,188-204`

### Pass 3 — transactional/order-lifecycle (routes/{offers,orders,servicing,certifications}.py)
462 lines / 114,369 chars (+4,830). **13 ambiguity-pins, 2 mismatch-revisions.**
- §3.3 — revise — mismatch — `certification_status` was described as "computed from the partner's certification records"; it is written outright by each certification event (last writer wins across channels), never aggregated — `services.py:289`, `routes/certifications.py:75,277,282,287,293`
- §3.7 — revise — mismatch — "Channel parity is verified first" was backwards: the refund's still-`PAID` re-check precedes the parity check (matching §2.10 steps 11 → 16) — `routes/servicing.py:91,95`
- §3.4 — insert — ambiguity — `corporate_tracking_ref` is a string of 1 to 120 characters — `routes/orders.py:35`
- §3.5 — insert — ambiguity — trip fields recorded as supplied and never compared to the filing's `origin`/`destination`/`cabin` (only `departure_date` checked); `ancillary_codes` unbounded and echoed verbatim in submission order; body-reference resolution order pinned; no `partner_type`/certification gate at construction — `routes/offers.py:23-53,74-83,129`
- §3.5 — insert — ambiguity — lazy expiry fires only on the three single-offer operations; neither `GET /offers` nor `GET /offers/{id}/items` applies it, so a stale-live offer still lists as `CONSTRUCTED`/`PUBLISHED` — `routes/offers.py:169,228` vs `173-216`
- §3.6 — insert/revise — ambiguity — `payment_amount_cents` required on `CAPTURE`, ignored on `VOID`, non-negative integer (shape before mismatch); both actions leave only from `AUTHORIZED` — `routes/orders.py:149-158`
- §3.6 — insert — ambiguity — capture credits the named agreement whatever status it now sits in — `routes/orders.py:171-175`
- §3.6 — insert — ambiguity — the `FLY`-is-DistributionManager refusal comes after path resolution and shape but before transition legality; ownership still first — `routes/orders.py:187-194`
- §3.7 — insert — ambiguity — `reason` up to 2,000 chars, validated then discarded on both review and apply; `APPROVE`/`REJECT` leave `reviewed_by_user_id` as the review starter — `routes/servicing.py:47,62,79`
- §3.7 — insert — ambiguity — no parity flag governs a void — `routes/servicing.py:95-100`
- §3.7 — insert — ambiguity — only the refund branch re-examines the order; a change applies to an already-cancelled order and a void to an already-captured one with no ledger reversal — `routes/servicing.py:120-128`
- §3.8 — insert — ambiguity — `partner_id` resolved before `channel_id`; certifications filterable by `partner_id`/`channel_id`/`status`/`env_code`, tests by `status` alone — `routes/certifications.py:42-47,95-98,180`
- §3.8 — insert — ambiguity — both interval rules count scheduled tests regardless of owning certification — `services.py:87-97`, `routes/certifications.py:134-156`
- §3.8 — insert — ambiguity — the reported test's own `version` bumps; `mandatory_failed_count` increments before the readiness recompute; a `score` sent with `CANCELLED` is range-checked then discarded — `routes/certifications.py:211-225`
- §3.8 — insert — ambiguity — `readiness_variant` defaults to `STRICT` — `routes/certifications.py:250`
- §3.8 — insert — ambiguity — `certified_variant` untouched by reinstate; `readiness_variant` validated then ignored on suspend/reinstate/revoke — `routes/certifications.py:274-296`

Dead/unreachable code deliberately NOT documented (documenting it would put behavior in the PRD that the impl never exhibits): `services.recompute_reserved_minutes` (imported by routes/certifications.py, never called) and the second `SUSPENDED → ACTIVE` role guard at `routes/fares.py:154` (unreachable behind an earlier gate).

Pass 3 closing judgement: every behavior in the transactional partition now traces to a PRD sentence. One residual soft spot left deliberately unedited — §3.5's "Seven conditions" narrates the offer gates in a different order than it evaluates them, but §2.10's numbered precedence (steps 8, 17, 21, 22, 23, 27, 31) plus its closing note fixes the actual order unambiguously, so duplicating it would have added prose without removing ambiguity.

Orchestrator verification: `cmp` confirms PRD_COMPLETED.md is NOT byte-identical to PRD_FINALIZED.md (the known failure mode where the scan silently never ran); 100 changed lines; heading list diff is empty; tail ends on the complete final §5 row; 43 `ERR_*` rows intact. Step 9 edited documentation only — no implementation file was touched — so the Step 7 green sweep (8/8 rounds at 99/99) still holds.

## Pipeline complete — 2026-09-05T19:35:34.871723770Z
