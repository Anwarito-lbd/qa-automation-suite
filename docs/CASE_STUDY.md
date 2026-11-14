# Engineering Case Study: Zero-Flake 4-Layer QA Automation for Financial Ledgers & Cross-Platform Runtimes

## 1. Motivation & Problem Statement

In distributed FinTech, mobile, and real-time client systems, production incidents rarely originate from isolated happy-path bugs. High-severity failures stem from:
- **Double-debiting under network retries** (broken `Idempotency-Key` semantics or non-atomic read-modify-write transactions).
- **Conservation-of-money violations** across multi-step order hold, cancellation, and settlement state transitions.
- **Authorization & privilege-escalation gaps** across multi-tenant or role-tiered endpoints (`customer`, `analyst`, `admin`).
- **Browser engine blind spots & UI/API drift** (form errors, missing `<label for>` accessibility bindings, mobile viewport overflow, JS runtime errors).
- **Mobile client desynchronization & runtime crashes** (`FATAL EXCEPTION` / ANR regressions caught only after manual smoke runs).
- **Engine/Client frame-budget regressions & defect triage bottlenecks** (`Ensure condition failed`, `AvgFPS`/`P95FrameTimeMs`/`PeakMemoryMB` regressions in Unreal Engine builds, and un-deduplicated CI failure noise).

Traditional QA architectures invert the test pyramid—coupling brittle UI scripts to shared staging environments—producing flaky CI pipelines and manual triage overhead.

This repository delivers a **Staff-Engineer / PhD-grade 4-Layer QA Automation Framework** paired with a bundled, deterministic System Under Test (**AegisPay Clearing**, `sut/`) plus cross-language **Kotlin/Gradle**, **Selenium WebDriver**, **Unreal Engine 5 Gauntlet**, **JIRA REST API v3**, and **Declarative Jenkins** CI integrations so every verification tier runs deterministically in local and cloud CI pipelines.

---

## 2. Formal Fault Model & System Invariants

The AegisPay SUT (`sut/database.py`, `sut/app.py`, `sut/models.py`) models an integer-cent clearing wallet and transfer-order engine backed by SQLite ACID transactions (`BEGIN IMMEDIATE`). The framework formalizes and enforces five core system invariants:

### Invariant 1: Conservation of Money (Zero-Leakage Ledger)
For every user $u$ at any point in time $t$, let $D_u(t)$ be the sum of all `DEPOSIT` ledger entries, $B_u(t)$ be `users.balance_cents`, $P_u(t)$ be the sum of `PENDING` orders, and $S_u(t)$ be the sum of `SETTLED` orders:

$$B_u(t) + P_u(t) + S_u(t) = D_u(t), \quad B_u(t) \ge 0$$

`CANCELLED` orders release their hold back into $B_u(t)$ via an `ORDER_RELEASE` ledger entry, keeping the invariant exact across arbitrary interleavings.

### Invariant 2: Idempotency-Key Linearizability
Given a user $u$, endpoint $e$, idempotency key $k$, and canonical SHA-256 request digest $H(\text{payload})$:
- If $(u, e, k)$ has not been committed, execution commits atomically with the order and ledger hold in the same SQLite transaction.
- If $(u, e, k)$ exists with $H(\text{payload}) = H_{\text{stored}}$, the server replays the exact cached response (`X-Idempotency-Replayed: true`) with zero additional balance mutation.
- If $(u, e, k)$ exists with $H(\text{payload}) \neq H_{\text{stored}}$, the server rejects the request with `409 Conflict`.

### Invariant 3: Order State Machine Monotonicity
Orders follow a strict directed acyclic graph:
`PENDING -> CANCELLED` (by owner or admin) or `PENDING -> SETTLED` (admin only). Both `CANCELLED` and `SETTLED` are absorbing terminal states; any subsequent state transition raises `InvalidStateTransitionError` (`409 Conflict`).

### Invariant 4: Role-Based Access Control (RBAC) & Bootstrap Isolation
- Elevated role provisioning (`admin`, `analyst`) requires a constant-time (`hmac.compare_digest`) match on `X-Admin-Provision-Key` (`403 Forbidden` otherwise).
- Customers are isolated to their own orders (`403` on cross-tenant read/cancel) and denied `/api/v1/audit/logs` and `/api/v1/admin/*`.
- Analysts have read-only access to `/api/v1/audit/logs` and global order listings (`all_users=true`) but are blocked from settling orders (`403`).

### Invariant 5: Deterministic Rate-Limit Windowing
`SlidingWindowRateLimiter` (`sut/rate_limit.py`) accepts an injectable monotonic clock `Callable[[], float]`. In QA (`tests/api/test_rate_limit_and_schema.py`), `FakeClock` advances simulated time instantaneously past the 10-second window—eliminating `time.sleep()` flakiness and CI slowdowns.

---

## 3. 4-Layer Architecture & Engineering Trade-Offs

### Layer 1: API Contract, Hypothesis Stateful Verification & JIRA Triage (`tests/api/`)
1. **12 deterministic API contract tests** covering JWT signature/expiry verification, RBAC matrix boundaries, idempotency replay/conflict, sliding-window `429` + `Retry-After` headers, and OpenAPI schema invariants.
2. **4 Hypothesis property-based & stateful tests (`tests/api/test_properties.py`)**:
   - Boundary & unicode/SQLi/XSS payload fuzzing (`40 + 40 + 30` examples) asserting zero `500 Internal Server Error` responses.
   - `LedgerStateMachine(RuleBasedStateMachine)` running `25` randomized multi-user operational histories (`18` steps each) against a reference Python shadow ledger and asserting Invariants 1–3 after every step.
3. **2 JIRA REST API v3 integration tests (`tests/api/test_jira_reporter.py`)**:
   - Verifies Atlassian Document Format (ADF) issue payload construction (`build_adf_issue_payload`), JQL fingerprint deduplication (`compute_defect_fingerprint`), multipart file attachment uploads, and deterministic JSON dry-run export via `httpx.MockTransport`.

### Layer 2: Dual-Engine Browser E2E, Accessibility & Editorial Portal UX (`tests/web/`)
Layer 2 launches an isolated `uvicorn` HTTP server on an ephemeral localhost port (`live_server_url` fixture) and verifies the **AegisPay Clearing** Swiss-ledger portal across **Playwright Chromium** (`4` tests) AND **Selenium WebDriver** (`2` cross-engine parity tests):
- **Real Defect Caught During Initial E2E Authoring**: `test_web_registration_login_and_invalid_credentials_alert` failed at `expect(page.get_by_test_id("login-form")).to_be_visible()` after signing out because `logout-btn` in `sut/static/app.js` omitted `switchTab("login")`. Fixing the handler resolved a real state-reset bug.
- **Console Error Hygiene**: Playwright tests attach `console` and `pageerror` listeners, verifying zero uncaught exceptions in happy-path and mobile responsive flows while permitting only explicit `401`/`422` network console entries during deliberate negative tests.
- **Accessibility & Overflow**: Evaluates semantic landmarks (`<header>`, `<main>`, `<nav>`), explicit `<label for="...">` bindings for all inputs/selects, and `scrollWidth <= innerWidth` at `390x844` across both Playwright and Selenium.

### Layer 3: Cross-Language Mobile QA — Python Appium/ADB & Kotlin Appium Java-Client (`tests/mobile/` & `mobile-kotlin/`)
- **Python Page Object Model & Dual-Mode Driver (`qa_framework/mobile/`)**: `LoginPage`, `WalletDashboardPage`, and `TransferOrderPage` use `MockAppiumBackend` (`DeterministicMobileBridge` XML `<hierarchy>` + live FastAPI state) or `HttpAppiumBackend` (real Appium 2.x W3C REST) controlled via `QA_MOBILE_MODE`, plus `AdbBridge` gating cold-start latency (`<= 2000 ms`), PSS memory (`<= 250,000 KB`), and fatal/ANR `logcat` signatures.
- **Kotlin / Gradle / JUnit5 / Appium Java-Client (`mobile-kotlin/`)**: Implements strongly typed Kotlin Page Objects (`LoginPage.kt`, `WalletDashboardPage.kt`) compiled against `io.appium:java-client:9.3.0` on JDK 21 and JUnit Jupiter `5.11.3`. An embedded W3C WebDriver `HttpServer` exercises `AndroidDriver` session creation, element lookup, typing, clicking, and screen assertions hermetically in CI.

### Layer 4: Unreal Engine 5 Gauntlet & Frame-Budget Automation (`qa_framework/unreal/` & `tests/unreal/`)
- **Command & Telemetry Adapter (`qa_framework/unreal/gauntlet.py`)**: Generates cross-platform `RunUAT.bat` / `RunUAT.sh` `RunUnreal` Gauntlet commands (`GauntletConfig`) and parses `LogAutomationController` pass/fail records, `LogOutputDevice: Error: Ensure condition failed`, `Fatal error:`/`Unhandled Exception:` crash lines, and `LogFPSChart` (`AvgFPS`, `P95FrameTimeMs`, `PeakMemoryMB`) against `UnrealPerformanceBudget` thresholds.
- **C++ Automation Spec (`qa_framework/unreal/cpp/AegisPayGauntletTests.cpp`)**: Reference UE5 `IMPLEMENT_SIMPLE_AUTOMATION_TEST` smoke check validating wallet ledger endpoint readiness from inside the game client module.
- **Closed-Loop JIRA Triage**: Regression test verifies that failed UE5 telemetry triggers automated `Highest`-priority JIRA defect generation with log excerpts.

---

## 4. Measured Execution Telemetry

Observed from `reports/qa-summary.json` (`32/32` pytest cases passed) and `mobile-kotlin/` (`1/1` Kotlin/JUnit5 test passed) after all final code and UI edits:
- **Total Suite**: `33/33` automated tests passed (`100.0%`); pytest wall clock `66.07 s`.
- **Layer 1 (API, Property & JIRA)**: `18/18` passed, `p50 = 35.16 ms`, `p95 = 5380.92 ms`, `max = 13701.30 ms` (`TestLedgerStateMachine`).
- **Layer 2 (Web E2E: Playwright + Selenium)**: `6/6` passed, `p50 = 2036.64 ms`, `p95 = 3608.45 ms`, `total = 13913.80 ms`.
- **Layer 3 (Mobile Appium/ADB + Kotlin)**: `4/4` Python passed (`p50 = 245.67 ms`, `p95 = 2305.45 ms`, `total = 3117.57 ms`) + `1/1` Kotlin Gradle `AegisMobileContractTest` passed.
- **Layer 4 (Unreal Gauntlet & Log Gate)**: `4/4` passed, `p50 = 1.71 ms`, `p95 = 460.05 ms`, `total = 544.63 ms`.
- **Static Quality Gates**: `ruff check .` (`0` errors), `ruff format --check .` (all `46` Python files formatted), `mypy sut qa_framework tests scripts` (`Success: no issues found in 43 source files`).
