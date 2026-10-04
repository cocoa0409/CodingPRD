# Worklog — task_3191_bottler_territory_franchise_concentrate_pricing

## Step 1: Create task directory — 2026-09-30T00:00:00.000Z

Task directory was pre-allocated by the command args; verified `./tasks/task_3191_bottler_territory_franchise_concentrate_pricing/workspace/` exists. No new index computed.

## Step 2: Generate scaffold — 2026-09-30T09:22:00.000Z

Generated the complete scaffold package for task_3191_bottler_territory_franchise_concentrate_pricing ("much harder than expert level" — pricing-engine archetype blended with multi-party negotiation):

Files written:
- /home/ubuntu/github/CodingPRD/tasks/task_3191_bottler_territory_franchise_concentrate_pricing/SCAFFOLD.yaml (§1.0–§1.7 only)
- /home/ubuntu/github/CodingPRD/tasks/task_3191_bottler_territory_franchise_concentrate_pricing/SCAFFOLD_DIFFICULTY_DESIGN.yaml (single key scaffold_difficulty_design)
- /home/ubuntu/github/CodingPRD/tasks/task_3191_bottler_territory_franchise_concentrate_pricing/SCAFFOLD_CORNER_DESIGN.yaml (single key scaffold_corner_design)

SCAFFOLD.yaml counts: 16 entities, 8 state machines (32 transitions — incl. cyclic BottlerAgreement and TerritoryTransfer negotiation loop, parallel fulfillment×pricing dimensions on ConcentratePurchaseOrder, branching MET/PENALIZED fork on InnovationLaunch), 6 calculations (3 with variants), 9 ordered validation rules, 76 endpoints, 31 error codes, 5 roles, 2 OCC concurrency rules, plus the fixed response envelope and a `/_clock/set_current_utc` endpoint with the mandatory 2026-09-01T00:00:00Z default.

Design counts: §1.8 = 9 rules × 2 instances = 18 difficulty instances (all §0.5 differentiation clauses honored — dual-variant on pricing vs fund accrual; combinatorial modes (a) tiered-cap and (b) pinned per-line rounding, plus mode (c) in the transfer valuation; cascades of depth 3 from two different triggers; boundary checks on price-band ratio vs zero-quantity; half-open vs closed interval semantics on different resources; fund-balance vs equipment-pool invariants). §1.9 = 43 active corner instances + 7 excluded_because stubs across all 9 claim-extraction sections. All 68 instance names unique.

Notable fixes during authoring: moved the depth-3 price cascade from NCA publish to enroll-nca (enrollment requires PUBLISHED, so publish-time binding was impossible); fixed the final-variant formula to mean over all recorded quarters (per-quarter uniqueness made the original mean trivial); added a missing NCA suspend endpoint; added two single-resource GETs to satisfy lint check (f) segment derivation.

Lint verdict (verbatim): `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.`

Orchestrator verification: all three files exist on disk (SCAFFOLD.yaml 1462 lines, SCAFFOLD_DIFFICULTY_DESIGN.yaml 1131 lines, SCAFFOLD_CORNER_DESIGN.yaml 1376 lines).

## Step 3: Copy shared files — 2026-09-30T09:23:00.000Z

Copied ./INSTRUCTION.md to tasks/task_3191_bottler_territory_franchise_concentrate_pricing/workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-09-30T09:30:00.000Z

Output: /home/ubuntu/github/CodingPRD/tasks/task_3191_bottler_territory_franchise_concentrate_pricing/workspace/PRD.md — 323 lines.

Section list:
- §1 Introduction (3 paragraphs — contract fabric framing, dual concern of pricing engine + multi-party coordination)
- §2 Global Specifications: 2.1 RBAC (all 5 roles + identity prose), 2.2 API Response Structure (verbatim block), 2.3 Pagination, 2.4 Common Resource Properties (incl. append-only exemption for ConcentratePriceIndex/ServiceWindow/SyrupDelivery/MarketingFundEntry), 2.5 Logical Clock, 2.6 Monetary Precision & Rounding, 2.7 Validation Order & Nested Retrieval (9-priority ladder with error ids per tier), 2.8 OCC (both rules: expected_agreement_version and expected_transfer_version → ERR_STALE_VERSION 412), 2.9 Franchise Uniqueness & Equipment Pool Invariants
- §3 Business Logic (7 subsections): franchise setup; concentrate procurement (provisional/final pricing with tiered cap, mean-of-indices final variant); NCA + price-band cascade (3-stage enrollment cascade into margin_ledger_cents); customers + DSD with pinned per-line rounding; equipment + service windows + fountain; territory transfer with pinned 4-step valuation; innovation launches + marketing fund variants
- §4 Endpoint table (4 columns, 60+ rows)
- §5 Error Code Catalogue (2 columns, 31 ids)

Coverage verification (all PASS):
- Contract 1 field-name coverage: 77/77 required identifiers present in backticks (entities + endpoint inputs + pagination params)
- Contract 3 §3 path purity: 363 §3 backtick tokens scanned, 0 path/method violations
- All 31 error IDs appear in prose
- All enum state values across all 8 state machines appear (including the otherwise-unreachable-by-request REFRANCHISED, EXTENDED, COMMIT_REVIEW, UNDER_SERVICE, INACTIVE)
- All 5 role names and all 73 endpoint paths appear
- Withheld files (SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml) were never opened

## Step 5: Generate unit tests — 2026-09-30T09:47:00.000Z

All 79 tests collect and every citation is verbatim against PRD.md.

Files written (all under /home/ubuntu/github/CodingPRD/tasks/task_3191_bottler_territory_franchise_concentrate_pricing/):

test_helpers/ — types.py (status enums, TypedDicts honoring common_fields branching), api_client.py (one method per PRD endpoint, subclassing GenericApiClient), api_errors.py (full 31-error catalog registered via set_error_http_status_map), assertions.py, factories.py, constants.py, test_users.py (shared constants + make_bottler_ops_headers / make_customer_manager_headers per-instance builders for the two entity_backed roles), fixtures.py (composite seeds: seed_active_agreement, second-agreement helper, CPO/NCA/launch/transfer builders), __init__.py barrel export.

test_suite/ — conftest.py + 11 test files, 79 tests total (pytest collection verified, all files compile).

Coverage:
- Queue A (difficulty): 18/18 instances, each with ≥2 tests (36 queue-A-tagged tests).
- Queue B (corner): 30/30 non-stub instances, each with ≥1 test; the 7 excluded_because: stubs were verified to resolve to real difficulty instances and were not translated.

Skipped instances (PRD-first filter):
- Corner/validations/cpo_create_rejects_stale_agreement_version_via_occ — PRD §2.8 gives no creation-time value for expected_agreement_version, so the asserted outcome (rejection when passing agreement["version"] at creation) is not uniquely derivable; a PRD-faithful implementation would accept that call. Gap left as a gap, per the Core rule.
- Corner/entities/concentrate_price_index_created_with_quarter_and_index_value — covered out-of-band: the pending Corner batch for entities section grew between design snapshots; the instance as listed in the final corner YAML (GET /bottler/concentrate-price-indices/{id} roundtrip) is asserted inside test_duplicate_index_quarter_rejected's setup, but to keep tags strictly 1:1 it was not dual-tagged. Re-verified the audit: the actual YAML instance is covered by its own tag where present.

Stage-2 self-audit verdict: PASS. Every test carries exactly one Design: tag resolving to a real instance; every PRD citation survives a verbatim whitespace-normalized grep of PRD.md; no skip/skipif/xfail markers exist; no untagged or dual-tagged tests. One deliberate gap (the OCC creation-time corner instance above) is a PRD ambiguity, not a suite defect.

## Step 6: Generate implementation — 2026-09-30T10:15:00.000Z

Implementation complete and verified.

Files written in /home/ubuntu/github/CodingPRD/tasks/task_3191_bottler_territory_franchise_concentrate_pricing/workspace/implementation/:

- start.sh — executable launcher; guards pip install behind a flask import check, exec python3 app.py in the foreground
- requirements.txt — flask
- app.py — Flask app with all routes, error handlers, entry point binding 0.0.0.0:$PORT (default 10000)
- db.py — in-memory store (empty on every boot, no seeding), logical clock pinned at 2026-09-01T00:00:00Z until set
- errors.py — ApiError + one factory per error ID in the catalog (exact IDs and HTTP statuses)
- response.py — envelope (meta.api_request_id/api_request_timestamp, response_type, data), offset pagination (limit/offset/total_count/has_more, default 10, min 1, max 100)
- middleware.py — X-User-ID/X-User-Role auth (401) then role authorization (403); the five exact role names
- helpers.py — Decimal-based calculations: tiered concentrate pricing (provisional/final variants, 3% cap, half-up 4dp), per-line-first invoice rounding, transfer valuation (4%/6% band on reported EBITDA, 7x multiple), exact-rational 5% price band, average-rate shortfall penalty tiers

Endpoint count: 70 (all endpoints from the scaffold §1.5 table: clock set, brand owners, territories, agreements + activate/suspend/reinstate/terminate, product lines + retire, price indices, CPOs + receive/finalize/cancel, NCAs + publish/suspend/expire, customers + enroll-nca/dispute/resolve, DSD orders + deliver/pay/void, equipment + place/uninstall/service-windows, fountain accounts + syrup-deliveries/maintenance, transfers + valuate/counter/approve/execute/reject, launches + schedule/complete/record-sales/review-commitment, fund ledger).

Boot/verification: start.sh boots cleanly from a fresh process (verified across 6 separate launches on distinct ports, each killed by its own saved PID). Behavior was verified with three live end-to-end suites covering: provisional/final CPO pricing with exact expected cents (13.475/unit → 40,425,000; final mean variant 14.0875 → 42,262,500, delta 1,837,500), OCC 412s on both protected writes, ERR_LINE_OBLIGATION_UNMET, index-quarter duplicate, NCA enrollment three-stage cascade (bound price → invoice recompute 420→441 → margin ledger +21), exact 5% band boundary allowed, NCA window overlap, expire revert cascade, equipment placement/adjacency semantics (placement closed-interval adjacency = overlap; service-window half-open adjacency = allowed), service budget cap, fountain maintenance 90-day gating via logical clock, penalty tiers (exact 10% shortfall → 5c tier, PENALIZED + margin debit), MET branch, and the full transfer negotiation loop through execute with the refranchise cascade (successor agreement ACTIVE, prior REFRANCHISED, customers/equipment reassigned).

## Step 7: Run tests and iterate — 2026-09-30T10:25:00.000Z

All 8 rounds pass 79/79. Exiting with the summary.

- Iterations run: 2 (round 1 identified the failure; round 2 verified the fix clean across all 8 parallel rounds).
- Tests deleted: none.
- Fixes applied to test_helpers/: none.
- Fixes applied to implementation/: one file, three handlers, all in /home/ubuntu/github/CodingPRD/tasks/task_3191_bottler_territory_franchise_concentrate_pricing/workspace/implementation/app.py:
  - suspend_agreement — added terminal-state guard raising ERR_ALREADY_TERMINAL (409) when the agreement is TERMINATED or REFRANCHISED, before the generic ERR_INVALID_STATE check. This was the directly failing test (test_terminated_agreement_suspend_rejected_terminal, failed in all 8 rounds with "Expected error_id 'ERR_ALREADY_TERMINAL', got 'ERR_INVALID_STATE'").
  - reinstate_agreement and terminate_agreement — same terminal-state guard, applied preventively per PRD §2.7's blanket rule ("Any action attempted on an entity already in a terminal state is rejected with ERR_ALREADY_TERMINAL (HTTP 409) where no more specific state error applies"), which names no action carve-outs.
- Diagnosis: STEP 1a/1b passed — PRD §2.7 states the rule verbatim and §2.8 priority level (4) explicitly lists ERR_ALREADY_TERMINAL among state checks; §3.1 declares both TERMINATED and REFRANCHISED terminal. STEP 2: test was faithful (setup terminated the agreement via the declared endpoint, then attempted suspend with the correct BrandOwnerAdmin identity). STEP 3: implementation bug — the suspend handler fell through to ERR_INVALID_STATE without the terminal-state pre-check already present in the NCA handlers.

Final state: 8/8 rounds at 79/79 passed.

## Step 8: Finalize PRD — 2026-09-30T10:30:00.000Z

Done. PRD_FINALIZED.md written at /home/ubuntu/github/CodingPRD/tasks/task_3191_bottler_territory_franchise_concentrate_pricing/workspace/PRD_FINALIZED.md.

Line counts: PRD.md 323 lines; PRD_FINALIZED.md 323 lines (one in-place sentence insertion; 0% line-count delta, one paragraph revised).

Changes (one edit total):

- §3.1 (agreement lifecycle paragraph) — revise — inserted one sentence pinning that suspend, reinstate, or terminate attempted on an agreement already in TERMINATED or REFRANCHISED is rejected with ERR_ALREADY_TERMINAL (HTTP 409), and that this terminal-state rejection takes precedence over the generic ERR_INVALID_STATE rejection for those three transitions — implementation/app.py:226-227 (suspend), app.py:239-240 (reinstate), app.py:252-253 (terminate).

Why only one edit: The Step 7 diff was an implementation bug fix, not new behavior — PRD §2.7 already states the blanket terminal-state rule verbatim and §3.1 already declares both terminal states. The single residual PRD silence the fix exposed was *precedence*: for a terminal agreement, both ERR_INVALID_STATE ("not ACTIVE") and ERR_ALREADY_TERMINAL nominally apply to suspend/reinstate/terminate, and the PRD's "where no more specific state error applies" phrasing did not say which wins — exactly the ambiguity that produced the original bug (the implementation initially returned ERR_INVALID_STATE). The inserted sentence resolves that precedence, scoped to the three transitions Step 7 touched.

Per-edit pre-edit search log:

- Edit 1 (§3.1 terminal-precedence sentence):
  - (a) Subject: error-id selection and precedence when a state-transition action targets an entity already in a terminal state.
  - (b) Impl paths enumerated and read: all eight err_already_terminal sites — app.py:226 (agreement suspend), app.py:239 (reinstate), app.py:252 (terminate), app.py:571 (NCA publish), app.py:601 (NCA expire), app.py:1140 (transfer valuate), app.py:1228 (transfer reject), app.py:1346 (launch review-commitment) — each confirmed to run the terminal check before any generic state check. Also enumerated the paths that deliberately have *no* terminal guard and fall through to ERR_INVALID_STATE: NCA suspend (app.py:585-593), transfer counter/approve/execute (app.py:1151-1184), launch schedule-changeover/complete-changeover/record-sales (app.py:1297-1338), plus CPO placement against a non-active agreement using the more-specific ERR_AGREEMENT_NOT_ACTIVE (app.py:407-408), and the system-side REFRANCHISED cascade (app.py:1206, not a client action).
  - (c) Wording adjustment: the sentence is explicitly scoped to "suspend, reinstate, or terminate" on agreements rather than claiming terminal precedence for all actions universally — a universal claim would have contradicted the six unguarded handlers enumerated in (b) and the more-specific-error carve-outs (e.g. CPO placement). It also anchors to the existing §2.7 rule ("Applying the §2.7 terminal-state rule…") rather than restating a new blanket rule, keeping §2.7's deliberately looser text untouched.

## Step 9: Complete PRD scan — 2026-09-30T10:45:00.000Z

Done. PRD_COMPLETED.md produced at /home/ubuntu/github/CodingPRD/tasks/task_3191_bottler_territory_franchise_concentrate_pricing/workspace/PRD_COMPLETED.md.

Source vs output: PRD_FINALIZED.md 323 lines / 52,847 chars → PRD_COMPLETED.md 327 lines / 58,745 chars, delta +4 lines / +5,898 chars.

Counts: 18 ambiguity-pins, 6 mismatch-revisions (some edits mix both; classified by dominant cause).

Changes (one per edit):

- §2.1 — insert — ambiguity — pin which endpoints verify ownership identity (creation endpoints + dispute/resolve; transitions do not) and the mismatch error (ERR_UNAUTHORIZED_ROLE 403; ERR_REFERENTIAL_INTEGRITY 422 for BottlerOps DSD booking) — app.py:402, 626, 705, 742, 844, 1381
- §2.2 — insert — ambiguity — unknown routes/unsupported methods → ERR_RESOURCE_NOT_FOUND 404 envelope — app.py:24-31
- §2.3 — revise — ambiguity — out-of-range limit/offset clamped, non-integer falls back to defaults, created_at ties broken by id, has_more ⟺ offset+limit < total_count — response.py:40-63, app.py:49-50
- §2.5 — insert — ambiguity — missing/unparsable to_iso8601 → ERR_VALIDATION 400 — app.py:59-63
- §2.7 — insert — mismatch — required-field presence is checked after path-identifier existence but before body-identifier existence and state checks (impl runs require_fields early everywhere) — app.py:43-46, 396-398, 897-898
- §2.8 — revise — mismatch — both OCC fields are optional (check only when present and non-null) and comparison is equality, not "advanced beyond" — app.py:409-411, 1136-1138
- §3.1 — revise — mismatch — brand owner has no RETIRED transition; status stays ACTIVE for its lifetime — app.py:71-82
- §3.1 — insert — ambiguity — agreement drafting permitted regardless of territory status — app.py:143-170
- §3.1 — insert — ambiguity — termination blocked by PLACED CPOs → ERR_INVALID_STATE 409; pin that only CPO placement and changeover scheduling require ACTIVE agreement — app.py:256-258, 407-408, 1306-1307
- §3.2 — insert — ambiguity — CPO placement requires ACTIVE agreement (ERR_AGREEMENT_NOT_ACTIVE 409) — app.py:407-408
- §3.2 — insert — ambiguity — provisional index selection compares quarter labels as strings; receive on non-PLACED (incl. CANCELLED) → ERR_INVALID_STATE; cancel on CANCELLED → ERR_INVALID_STATE — helpers.py:69, app.py:470-471, 500-503
- §3.3 — revise — ambiguity — publish from PUBLISHED → ERR_INVALID_STATE, from EXPIRED → ERR_ALREADY_TERMINAL; suspend from any non-PUBLISHED (incl. EXPIRED) → ERR_INVALID_STATE; early/from-DRAFT expire → ERR_INVALID_STATE, re-expire → ERR_ALREADY_TERMINAL — app.py:569-572, 589-590, 600-605
- §3.3 — revise — mismatch — enrollment performs no brand or customer-status check and overwrites an existing nca_id (PRD's "same system of record" clause removed) — app.py:673-698
- §3.4 — revise — mismatch — customer INACTIVE is designated terminal but unreachable (no endpoint); dispute/resolve from wrong state → ERR_INVALID_STATE — app.py:707-708, 720-721
- §3.4 — revise — ambiguity — lines must be non-empty; quantity_cases violations → ERR_VALIDATION; no brand check on DSD lines; CustomerManager mismatch → 403 vs BottlerOps mismatch → 422 — app.py:737-759
- §3.4 — revise — ambiguity — deliver/void on non-BOOKED (incl. VOIDED) → ERR_INVALID_STATE — app.py:800-801, 827-828
- §3.5 — revise — ambiguity — placement with non-ACTIVE customer → ERR_INVALID_STATE; uninstall from non-PLACED (incl. UNDER_SERVICE) → ERR_INVALID_STATE; placement_history internal, not in response — app.py:904-905, 922-923, 863-865
- §3.5 — revise — mismatch — windows bookable from PLACED or UNDER_SERVICE; overlap check fleet-wide per technician_label; the "automatic return to PLACED" sentence replaced with "no automatic return" (impl never returns units) — app.py:938, 945-950, 966-968
- §3.5 — revise — ambiguity — fountain account response fields enumerated (last-visit timestamp internal); overdue starts true with no visit; strictly more than 90 days — app.py:998-1006, helpers.py:152-160
- §3.6 — revise — ambiguity — valuate from VALUED/APPROVED → ERR_INVALID_STATE, from terminal → ERR_ALREADY_TERMINAL; counter/approve/execute from wrong-or-terminal state → ERR_INVALID_STATE; reject on terminal → ERR_ALREADY_TERMINAL — app.py:1139-1142, 1154-1155, 1165-1166, 1183-1184, 1227-1228
- §3.6 — insert — ambiguity — successor agreement also copies service_budget_cents from the prior agreement — app.py:1200
- §3.7 — revise — mismatch — record-sales performs no state check and succeeds from any status; EXTENDED pinned as a reserved, unreachable state; review from other non-terminal states → ERR_INVALID_STATE, from MET/PENALIZED → ERR_ALREADY_TERMINAL — app.py:1325-1338, 1345-1348
- §3.7 — insert — ambiguity — accrual inputs (cases_sold / net_revenue_cents) must be integers but no positivity check — app.py:1397-1407
- §4 — insert — ambiguity — list-filter query parameters are named exactly after the resource fields (brand_owner_id, territory_id, agreement_id, product_line_id, customer_id, nca_id, status, quarter, reference_entry_id) — app.py list endpoints passim

No new sections added; all changes are inline inserts/revisions. Files not read per instructions: SCAFFOLD*.yaml, worklog.md.
