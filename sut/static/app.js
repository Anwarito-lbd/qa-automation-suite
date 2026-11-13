(() => {
  const state = {
    token: null,
    user: null,
  };

  const els = {
    alertBanner: document.getElementById("alert-banner"),
    statusBanner: document.getElementById("status-banner"),
    authSection: document.getElementById("auth-section"),
    dashboardSection: document.getElementById("dashboard-section"),
    navUserPill: document.getElementById("nav-user-pill"),
    logoutBtn: document.getElementById("logout-btn"),
    tabLogin: document.getElementById("tab-login"),
    tabRegister: document.getElementById("tab-register"),
    loginForm: document.getElementById("login-panel"),
    registerForm: document.getElementById("register-panel"),
    depositForm: document.getElementById("deposit-form"),
    orderForm: document.getElementById("order-form"),
    refreshOrdersBtn: document.getElementById("refresh-orders-btn"),
    ordersTbody: document.getElementById("orders-tbody"),
    metricBalance: document.getElementById("metric-balance"),
    metricDeposited: document.getElementById("metric-deposited"),
    metricPending: document.getElementById("metric-pending"),
    metricSettled: document.getElementById("metric-settled"),
  };

  function formatCents(cents) {
    return `$${(Number(cents || 0) / 100).toFixed(2)}`;
  }

  function showAlert(message) {
    els.statusBanner.classList.add("hidden");
    els.alertBanner.textContent = message;
    els.alertBanner.classList.remove("hidden");
  }

  function showStatus(message) {
    els.alertBanner.classList.add("hidden");
    els.statusBanner.textContent = message;
    els.statusBanner.classList.remove("hidden");
  }

  function clearMessages() {
    els.alertBanner.classList.add("hidden");
    els.statusBanner.classList.add("hidden");
  }

  function switchTab(mode) {
    clearMessages();
    const isLogin = mode === "login";
    els.tabLogin.classList.toggle("active", isLogin);
    els.tabRegister.classList.toggle("active", !isLogin);
    els.tabLogin.setAttribute("aria-selected", String(isLogin));
    els.tabRegister.setAttribute("aria-selected", String(!isLogin));
    els.loginForm.classList.toggle("hidden", !isLogin);
    els.registerForm.classList.toggle("hidden", isLogin);
  }

  async function apiRequest(path, options = {}) {
    const headers = {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    };
    if (state.token) {
      headers.Authorization = `Bearer ${state.token}`;
    }

    const res = await fetch(path, {
      ...options,
      headers,
    });
    const text = await res.text();
    let data = null;
    if (text) {
      try {
        data = JSON.parse(text);
      } catch {
        data = { detail: text };
      }
    }
    if (!res.ok) {
      const detail =
        (data && (typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail))) ||
        `HTTP ${res.status}`;
      throw new Error(detail);
    }
    return data;
  }

  function renderAuthenticatedView() {
    const loggedIn = Boolean(state.token && state.user);
    els.authSection.classList.toggle("hidden", loggedIn);
    els.dashboardSection.classList.toggle("hidden", !loggedIn);
    els.navUserPill.classList.toggle("hidden", !loggedIn);
    els.logoutBtn.classList.toggle("hidden", !loggedIn);
    if (loggedIn) {
      els.navUserPill.textContent = `${state.user.full_name} (${state.user.role})`;
    }
  }

  function renderOrdersTable(orders) {
    els.ordersTbody.replaceChildren();
    if (!orders || orders.length === 0) {
      const tr = document.createElement("tr");
      const td = document.createElement("td");
      td.colSpan = 6;
      td.className = "empty-cell";
      td.textContent = "No transfer orders yet.";
      tr.appendChild(td);
      els.ordersTbody.appendChild(tr);
      return;
    }

    for (const order of orders) {
      const tr = document.createElement("tr");
      tr.dataset.testid = `order-row-${order.id}`;

      const tdId = document.createElement("td");
      tdId.textContent = order.id;

      const tdRecipient = document.createElement("td");
      tdRecipient.textContent = order.recipient;

      const tdAmount = document.createElement("td");
      tdAmount.textContent = `${formatCents(order.amount_cents)} ${order.currency}`;

      const tdStatus = document.createElement("td");
      const badge = document.createElement("span");
      badge.className = `badge badge-${order.status}`;
      badge.textContent = order.status;
      badge.dataset.testid = `order-status-${order.id}`;
      tdStatus.appendChild(badge);

      const tdMemo = document.createElement("td");
      tdMemo.textContent = order.memo || "-";

      const tdAction = document.createElement("td");
      if (order.status === "PENDING") {
        const cancelBtn = document.createElement("button");
        cancelBtn.type = "button";
        cancelBtn.className = "btn-danger-sm";
        cancelBtn.textContent = "Cancel";
        cancelBtn.dataset.testid = `cancel-order-${order.id}`;
        cancelBtn.addEventListener("click", async () => {
          try {
            await apiRequest(`/api/v1/orders/${encodeURIComponent(order.id)}/cancel`, {
              method: "POST",
            });
            showStatus(`Cancelled order ${order.id} and refunded ${formatCents(order.amount_cents)}.`);
            await refreshDashboard();
          } catch (err) {
            showAlert(err.message);
          }
        });
        tdAction.appendChild(cancelBtn);
      } else {
        tdAction.textContent = "-";
      }

      tr.append(tdId, tdRecipient, tdAmount, tdStatus, tdMemo, tdAction);
      els.ordersTbody.appendChild(tr);
    }
  }

  async function refreshDashboard() {
    if (!state.token) return;
    const [summary, orders] = await Promise.all([
      apiRequest("/api/v1/accounts/me"),
      apiRequest("/api/v1/orders"),
    ]);
    els.metricBalance.textContent = formatCents(summary.balance_cents);
    els.metricDeposited.textContent = formatCents(summary.total_deposited_cents);
    els.metricPending.textContent = formatCents(summary.pending_orders_cents);
    els.metricSettled.textContent = formatCents(summary.settled_orders_cents);
    renderOrdersTable(orders);
  }

  els.tabLogin.addEventListener("click", () => switchTab("login"));
  els.tabRegister.addEventListener("click", () => switchTab("register"));

  els.logoutBtn.addEventListener("click", () => {
    state.token = null;
    state.user = null;
    switchTab("login");
    renderAuthenticatedView();
    showStatus("Signed out cleanly.");
  });

  els.loginForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    clearMessages();
    const email = document.getElementById("login-email").value.trim();
    const password = document.getElementById("login-password").value;
    if (!email || !password) {
      showAlert("Email and password are required.");
      return;
    }
    try {
      const result = await apiRequest("/api/v1/auth/login", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
      state.token = result.access_token;
      state.user = result.user;
      renderAuthenticatedView();
      await refreshDashboard();
      showStatus(`Welcome back, ${result.user.full_name}.`);
    } catch (err) {
      showAlert(err.message);
    }
  });

  els.registerForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    clearMessages();
    const fullName = document.getElementById("reg-name").value.trim();
    const email = document.getElementById("reg-email").value.trim();
    const password = document.getElementById("reg-password").value;
    if (fullName.length < 2) {
      showAlert("Full name must be at least 2 characters.");
      return;
    }
    if (!email.includes("@")) {
      showAlert("Please enter a valid email address.");
      return;
    }
    if (password.length < 8) {
      showAlert("Password must be at least 8 characters.");
      return;
    }
    try {
      const result = await apiRequest("/api/v1/auth/register", {
        method: "POST",
        body: JSON.stringify({
          full_name: fullName,
          email,
          password,
        }),
      });
      state.token = result.access_token;
      state.user = result.user;
      renderAuthenticatedView();
      await refreshDashboard();
      showStatus(`Account created for ${result.user.email}.`);
    } catch (err) {
      showAlert(err.message);
    }
  });

  els.depositForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    clearMessages();
    const rawAmount = Number(document.getElementById("deposit-amount").value);
    const reference = document.getElementById("deposit-ref").value.trim();
    const amountCents = Math.round(rawAmount * 100);
    if (!Number.isFinite(rawAmount) || amountCents <= 0) {
      showAlert("Deposit amount must be greater than $0.00.");
      return;
    }
    try {
      await apiRequest("/api/v1/accounts/deposit", {
        method: "POST",
        body: JSON.stringify({ amount_cents: amountCents, reference: reference || "web-topup" }),
      });
      await refreshDashboard();
      showStatus(`Deposited ${formatCents(amountCents)} to sandbox wallet.`);
      document.getElementById("deposit-amount").value = "";
    } catch (err) {
      showAlert(err.message);
    }
  });

  els.orderForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    clearMessages();
    const recipient = document.getElementById("order-recipient").value.trim();
    const rawAmount = Number(document.getElementById("order-amount").value);
    const currency = document.getElementById("order-currency").value;
    const memo = document.getElementById("order-memo").value.trim();
    const customIdem = document.getElementById("order-idem").value.trim();

    const amountCents = Math.round(rawAmount * 100);
    if (recipient.length < 2) {
      showAlert("Recipient must be at least 2 characters.");
      return;
    }
    if (!Number.isFinite(rawAmount) || amountCents <= 0) {
      showAlert("Order amount must be greater than $0.00.");
      return;
    }

    const idemKey = customIdem || `web-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`;
    try {
      const order = await apiRequest("/api/v1/orders", {
        method: "POST",
        headers: { "Idempotency-Key": idemKey },
        body: JSON.stringify({
          recipient,
          amount_cents: amountCents,
          currency,
          memo,
        }),
      });
      await refreshDashboard();
      showStatus(`Order ${order.id} created for ${order.recipient}.`);
      document.getElementById("order-amount").value = "";
      document.getElementById("order-memo").value = "";
      document.getElementById("order-idem").value = "";
    } catch (err) {
      showAlert(err.message);
    }
  });

  els.refreshOrdersBtn.addEventListener("click", async () => {
    clearMessages();
    try {
      await refreshDashboard();
      showStatus("Ledger refreshed.");
    } catch (err) {
      showAlert(err.message);
    }
  });

  renderAuthenticatedView();
})();
