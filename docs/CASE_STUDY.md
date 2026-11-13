# Engineering Case Study: Zero-Flake Multi-Layer QA Automation for Financial Ledgers

## 1. Motivation & Problem Statement

In distributed FinTech and payment-processing systems, quality failures rarely originate from simple happy-path regressions. High-severity incidents stem from:
- **Double-debiting under network retries** (broken `Idempotency-Key` semantics or non-atomic read-modify-write transactions).
- **Conservation-of-money violations** across multi-step order hold, cancellation, and settlement state transitions.
- **Authorization & privilege-escalation gaps** across multi-tenant or role-tiered endpoints (`customer`, `analyst`, `admin`).
- **UI/API contract drift & frontend regressions** (unhandled form errors, missing accessibility labels, mobile viewport overflow, uncaught JS runtime exceptions).
- **Mobile client desynchronization & runtime crashes** (`FATAL EXCEPTION` / ANR regressions caught too late without automated logcat gating).

Traditional QA architectures frequently invert the test pyramid—relying heavily on slow, brittle UI scripts coupled to shared staging environments—producing flaky CI pipelines and weak coverage of concurrency or state-space edge cases.

This project demonstrates a **Staff-Engineer / PhD-grade Multi-Layer QA Automation Framework** paired with a bundled, deterministic System Under Test (**AegisPay Sandbox**, `sut/`) so every layer runs hermetically in local environments and GitHub Actions CI.

---

## 2. Formal Fault Model & System Invariants

The AegisPay SUT (`sut/database.py`, `sut/app.py`, `sut/models.py`) models an integer-cent FinTech wallet and transfer-order engine backed by SQLite ACID transactions (`BEGIN IMMEDIATE`). Our QA suite formalizes and enforces five core invariants:

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

## 3. Multi-Layer Architecture & Engineering Trade-Offs

### Layer 1: API Contract & Hypothesis Stateful Verification (`tests/api/`)
Rather than writing dozens of repetitive unit tests, Layer 1 combines:
1. **12 deterministic API contract tests** covering JWT signature/expiry verification, RBAC matrix boundaries, idempotency replay/conflict, sliding-window `429` + `Retry-After` headers, and OpenAPI schema invariants (`p50 = 63.03 ms`).
2. **4 Hypothesis property-based & stateful tests (`tests/api/test_properties.py`)**:
   - Boundary & unicode/SQLi/XSS payload fuzzing (`40 + 40 + 30` examples) asserting zero `500 Internal Server Error` responses.
   - `LedgerStateMachine(RuleBasedStateMachine)` running `25` randomized multi-user operational histories (`18` steps each) against a reference Python shadow ledger and asserting Invariants 1–3 after every step.

### Layer 2: Headless Browser E2E, Accessibility & Responsive Audits (`tests/web/`)
Layer 2 launches an isolated `uvicorn` HTTP server on an ephemeral localhost port (`live_server_url` fixture) and drives real headless Chromium via Playwright across both **Desktop (`1280x800`)** and **Mobile (`390x844`)** viewports:
- **Real Defect Discovered During E2E Authoring**: During initial implementation, `test_web_registration_login_and_invalid_credentials_alert` failed at `expect(page.get_by_test_id("login-form")).to_be_visible()` after signing out. Root cause inspection showed the `logout-btn` handler in `sut/static/app.js` hid the dashboard without calling `switchTab("login")`, leaving the user stranded on the `Create Account` tab! Fixing `sut/static/app.js` resolved a genuine usability bug caught directly by Layer 2.
- **Console Error Hygiene**: Every test attaches `console` and `pageerror` listeners. Negative tests explicitly allow only the expected Chromium network resource status log (`status of 401` / `status of 422`) during deliberate negative probes, while happy-path and mobile responsive tests assert `console_errors == []` and `page_errors == []`.
- **Accessibility & Overflow**: Evaluates semantic landmarks (`<header>`, `<main>`, `<nav>`), explicit `<label for="...">` associations for every `<input>`/`<select>`, and `document.documentElement.scrollWidth <= window.innerWidth` at `390x844`.

### Layer 3: Android Mobile POM & ADB Health/Logcat Harness (`tests/mobile/`)
To keep CI fast and deterministic without requiring nested virtualization (KVM) for an Android AVD, Layer 3 cleanly separates test intent from driver transport:
- **Page Object Model (`qa_framework/mobile/pages/`)**: `LoginPage`, `WalletDashboardPage`, and `TransferOrderPage` interact exclusively through `MobileDriver` and `Locator(using, value)` (`accessibility id`, `id`, `xpath`).
- **Dual-Mode Driver (`qa_framework/mobile/driver.py`)**:
  - `MockAppiumBackend` routes W3C WebDriver commands to `DeterministicMobileBridge` (`sut/mobile_bridge.py`), which renders an authentic `<hierarchy>` Android UIAutomator2 XML tree, resolves locators via `xml.etree.ElementTree`, and calls the live FastAPI SUT endpoints so mobile UI actions mutate real SQLite state.
  - `HttpAppiumBackend` speaks the standard W3C WebDriver HTTP REST protocol (`/session`, `/element`, `/click`, `/value`, `/source`) to an Appium 2.x server when `QA_MOBILE_MODE=appium`.
- **ADB Diagnostic & Logcat Gate (`qa_framework/mobile/adb.py`)**: Validates device state (`device`), Android SDK (`>= 30`), package installation (`com.aegispay.wallet`), cold-start `am start -W` latency (`312 ms <= 2000 ms` budget), memory `dumpsys meminfo` (`68,420 KB <= 250,000 KB` budget), and zero fatal/ANR patterns in `logcat` (verified via a fault-injection test).

---

## 4. Measured Execution Telemetry

Observed from `reports/qa-summary.json` after final edits:
- **Total Suite**: `24/24 passed` (`100.0%`), `39.662 s` wall clock.
- **Layer 1 (API & Property)**: `16/16 passed`, `p50 = 63.03 ms`, `p95 = 5261.98 ms`, `max = 11460.14 ms` (`TestLedgerStateMachine`).
- **Layer 2 (Web E2E)**: `4/4 passed`, `p50 = 1156.49 ms`, `p95 = 1391.39 ms`, `total = 4707.27 ms`.
- **Layer 3 (Mobile Appium/ADB)**: `4/4 passed`, `p50 = 121.00 ms`, `p95 = 685.87 ms`, `total = 1006.70 ms`.
- **Static Quality Gates**: `ruff check .` (0 errors), `ruff format --check .` (clean), `mypy --strict` (`Success: no issues found in 35 source files`).
