"use strict";

const REFRESH_INTERVAL_MS = 60_000;

const state = {
  market: [],
  alerts: [],
  portfolio: null,
  rules: [],
  riskProfile: { profile: "moderate", custom_base_profile: null },
  system: null,
  runs: [],
  authenticated: false,
  selectedSymbol: "BTCBRL",
  selectedPeriod: "24h",
  alertFilter: "active",
  currentView: "market",
  refreshing: false,
  charts: { market: null, asset: null, portfolio: null },
};

const viewMeta = {
  market: ["Visão geral", "Mercado"],
  asset: ["Análise", "Ativo"],
  portfolio: ["Exposição", "Portfólio"],
  alerts: ["Exceções", "Alertas"],
  rules: ["Configuração", "Regras"],
  system: ["Operação", "Sistema"],
};

window.addEventListener("DOMContentLoaded", () => {
  bindNavigation();
  bindControls();
  refreshIcons();
  refreshAll();
  window.setInterval(() => {
    if (!document.hidden) refreshAll();
  }, REFRESH_INTERVAL_MS);
});

function bindNavigation() {
  document.querySelectorAll(".nav-item[data-view]").forEach((button) => {
    button.addEventListener("click", () => setView(button.dataset.view));
  });
}

function bindControls() {
  document.getElementById("refresh-button").addEventListener("click", refreshAll);
  document.getElementById("login-button").addEventListener("click", () => {
    if (state.authenticated) {
      logout();
    } else {
      openDialog("login-dialog");
    }
  });
  document.querySelector("[data-open-asset]").addEventListener("click", () => setView("asset"));
  document.getElementById("asset-selector").addEventListener("change", (event) => {
    state.selectedSymbol = event.target.value;
    syncSelectedAsset();
    loadAssetCandles();
  });
  document.querySelectorAll("[data-period]").forEach((button) => {
    button.addEventListener("click", () => {
      document.querySelectorAll("[data-period]").forEach((item) => item.classList.remove("is-active"));
      button.classList.add("is-active");
      state.selectedPeriod = button.dataset.period;
      loadAssetCandles();
    });
  });
  document.getElementById("alert-filter").addEventListener("change", (event) => {
    state.alertFilter = event.target.value;
    renderAlerts();
  });
  document.getElementById("add-position-button").addEventListener("click", () => openTradeDialog());
  document.getElementById("reset-simulator-button").addEventListener("click", resetSimulator);
  document.getElementById("login-form").addEventListener("submit", handleLogin);
  document.getElementById("position-form").addEventListener("submit", handleTradeSubmit);
  document.getElementById("trade-side").addEventListener("change", syncTradeFields);
  document.getElementById("portfolio-table").addEventListener("click", handlePortfolioAction);
  document.getElementById("alerts-table").addEventListener("click", handleAlertAction);
  document.getElementById("rules-list").addEventListener("click", handleRuleAction);
  document.getElementById("risk-profile-select").addEventListener("change", handleProfileChange);
  document.getElementById("reset-risk-profile").addEventListener("click", handleProfileReset);
}

function setView(view) {
  if (!viewMeta[view]) return;
  state.currentView = view;
  document.querySelectorAll(".nav-item").forEach((item) => item.classList.toggle("is-active", item.dataset.view === view));
  document.querySelectorAll(".view-panel").forEach((panel) => panel.classList.toggle("is-active", panel.dataset.viewPanel === view));
  document.getElementById("view-eyebrow").textContent = viewMeta[view][0];
  document.getElementById("view-title").textContent = viewMeta[view][1];
  if (view === "asset") loadAssetCandles();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

async function refreshAll() {
  if (state.refreshing) return;
  state.refreshing = true;
  const refreshButton = document.getElementById("refresh-button");
  refreshButton.disabled = true;
  refreshButton.setAttribute("aria-busy", "true");
  refreshButton.classList.add("is-spinning");
  hideBanner();
  try {
    const resources = [
      { label: "mercado", load: api("/api/market"), apply: (value) => { state.market = value; } },
      { label: "alertas", load: api("/api/alerts"), apply: (value) => { state.alerts = value; } },
      { label: "portfólio", load: api("/api/portfolio"), apply: (value) => { state.portfolio = value; } },
      { label: "regras", load: api("/api/rules"), apply: (value) => { state.rules = value; } },
      { label: "perfil", load: api("/api/settings/risk-profile"), apply: (value) => { state.riskProfile = value; } },
      { label: "sistema", load: api("/api/system"), apply: (value) => { state.system = value; } },
      { label: "execuções", load: api("/api/system/runs?limit=12"), apply: (value) => { state.runs = value; } },
      { label: "sessão", load: api("/api/auth/session"), apply: (value) => { state.authenticated = value.authenticated; } },
    ];
    const results = await Promise.allSettled(resources.map((resource) => resource.load));
    const failed = [];
    results.forEach((result, index) => {
      if (result.status === "fulfilled") {
        resources[index].apply(result.value);
      } else {
        failed.push(resources[index].label);
      }
    });
    if (!state.market.some((item) => item.symbol === state.selectedSymbol) && state.market.length) {
      state.selectedSymbol = state.market[0].symbol;
    }
    renderAll();
    if (results[0].status === "fulfilled" && state.market.length) await loadMarketChart();
    if (results[0].status === "fulfilled" && state.currentView === "asset") {
      await loadAssetCandles();
    }
    setSystemState(results[0].status === "fulfilled" && results[5].status === "fulfilled");
    if (failed.length) showBanner(`Atualização parcial: falha em ${failed.join(", ")}.`);
  } catch (error) {
    showBanner(error.message || "Não foi possível atualizar o painel.");
    setSystemState(false);
  } finally {
    state.refreshing = false;
    refreshButton.disabled = false;
    refreshButton.removeAttribute("aria-busy");
    refreshButton.classList.remove("is-spinning");
    refreshIcons();
  }
}

function renderAll() {
  renderOperatorState();
  renderMarket();
  renderAssetControls();
  renderAssetSummary();
  renderPortfolio();
  renderAlerts();
  renderRules();
  renderSystem();
  refreshIcons();
}

function renderMarket() {
  const priced = state.market.filter((item) => item.price_brl !== null);
  const activeAlerts = state.alerts.filter((item) => item.condition_active);
  const staleThreshold = ruleThreshold("stale_market_data", 45);
  const highestVolatility = priced.reduce((best, item) => {
    if (item.volatility_24h_pct === null) return best;
    return !best || item.volatility_24h_pct > best.volatility_24h_pct ? item : best;
  }, null);
  const staleAssets = priced.filter((item) => item.staleness_minutes !== null && item.staleness_minutes >= staleThreshold);

  document.getElementById("market-kpis").innerHTML = [
    metricCard("radio", "Ativos com preço", `${priced.length}/${state.market.length}`, "Pares monitorados"),
    metricCard("bell", "Alertas ativos", activeAlerts.length, activeAlerts.length ? "Exigem leitura" : "Sem exceções abertas", activeAlerts.length ? "is-warning" : "is-positive"),
    metricCard("waves", "Maior volatilidade", highestVolatility ? formatPct(highestVolatility.volatility_24h_pct) : "--", highestVolatility ? displaySymbol(highestVolatility.symbol) : "Histórico insuficiente", highestVolatility ? "is-warning" : ""),
    metricCard("clock-3", "Dados atrasados", staleAssets.length, staleAssets.length ? `Acima de ${formatNumber(staleThreshold)} min` : "Coleta dentro do limite", staleAssets.length ? "is-negative" : "is-positive"),
  ].join("");

  document.getElementById("market-assets").innerHTML = state.market.map(assetCard).join("");
  document.querySelectorAll(".asset-card[data-symbol]").forEach((card) => {
    card.addEventListener("click", () => {
      state.selectedSymbol = card.dataset.symbol;
      syncSelectedAsset();
      setView("asset");
    });
  });

  document.getElementById("market-updated").textContent = newestMarketTime();
  document.getElementById("active-alert-count").textContent = activeAlerts.length;
  document.getElementById("market-alerts").innerHTML = activeAlerts.length
    ? activeAlerts.slice(0, 5).map(compactAlert).join("")
    : '<div class="empty-state"><i data-lucide="badge-check"></i><p>Nenhuma condição ativa.</p></div>';
}

function renderAssetControls() {
  const options = state.market.map((item) => `<option value="${escapeHtml(item.symbol)}" ${item.symbol === state.selectedSymbol ? "selected" : ""}>${escapeHtml(displaySymbol(item.symbol))} · ${escapeHtml(item.display_name)}</option>`).join("");
  document.getElementById("asset-selector").innerHTML = options;
  document.getElementById("position-symbol").innerHTML = options;
}

function renderAssetSummary() {
  const item = selectedAsset();
  if (!item) {
    document.getElementById("asset-kpis").innerHTML = metricCard("circle-off", "Ativo", "--", "Sem dados");
    return;
  }
  document.getElementById("asset-kpis").innerHTML = [
    metricCard("badge-dollar-sign", "Último preço", formatBRL(item.price_brl), displaySymbol(item.symbol)),
    metricCard("timer", "Retorno em 1h", formatPct(item.return_1h_pct), "Variação do preço", changeClass(item.return_1h_pct)),
    metricCard("calendar-clock", "Retorno em 24h", formatPct(item.return_24h_pct), "Variação do preço", changeClass(item.return_24h_pct)),
    metricCard("waves", "Volatilidade em 24h", formatPct(item.volatility_24h_pct), "Oscilação realizada", item.volatility_24h_pct >= ruleThreshold("volatility_24h", 4) ? "is-warning" : ""),
  ].join("");
  document.getElementById("asset-definitions").innerHTML = [
    definition("Retorno", "Compara o preço atual com o preço observado no início da janela."),
    definition("Volatilidade", "Resume a dispersão dos retornos de 15 minutos ao longo de 24 horas."),
    definition("Drawdown", `Preço atual em relação ao maior preço da janela: ${formatPct(item.drawdown_7d_pct)}.`),
    definition("Volume relativo", `Volume do candle atual dividido pela média anterior: ${formatRatio(item.volume_ratio)}.`),
    definition("Atualização", item.calculated_at ? formatDateTime(item.calculated_at) : "Ainda não calculada."),
    definition(
      "Risco atual",
      item.risk_reasons?.length
        ? item.risk_reasons.map((reason) => reason.label).join("; ")
        : "Nenhuma regra ativa foi ultrapassada para este ativo.",
    ),
  ].join("");
}

async function loadMarketChart() {
  const data = await safeApi(`/api/assets/${encodeURIComponent(state.selectedSymbol)}/candles?period=24h&limit=192`);
  renderPriceChart("market", "market-chart", "market-chart-empty", data || []);
  document.getElementById("market-chart-title").textContent = `${displaySymbol(state.selectedSymbol)} · 24 horas`;
}

async function loadAssetCandles() {
  if (!state.market.length) return;
  renderAssetSummary();
  const data = await safeApi(`/api/assets/${encodeURIComponent(state.selectedSymbol)}/candles?period=${state.selectedPeriod}&limit=500`);
  renderAssetChart(data || []);
  document.getElementById("asset-chart-title").textContent = `${displaySymbol(state.selectedSymbol)} · ${state.selectedPeriod}`;
  refreshIcons();
}

function renderPriceChart(slot, canvasId, emptyId, rows) {
  destroyChart(slot);
  toggleChart(canvasId, emptyId, rows.length > 0);
  if (!rows.length || typeof Chart === "undefined") return;
  state.charts[slot] = new Chart(document.getElementById(canvasId), {
    type: "line",
    data: {
      labels: rows.map((row) => shortTime(row.opened_at)),
      datasets: [{ label: "Preço (BRL)", data: rows.map((row) => row.close), borderColor: "#087f7b", backgroundColor: "rgba(8,127,123,.09)", borderWidth: 2, pointRadius: 0, tension: 0.18, fill: true }],
    },
    options: chartOptions(false),
  });
}

function renderAssetChart(rows) {
  destroyChart("asset");
  toggleChart("asset-chart", "asset-chart-empty", rows.length > 0);
  if (!rows.length || typeof Chart === "undefined") return;
  state.charts.asset = new Chart(document.getElementById("asset-chart"), {
    type: "bar",
    data: {
      labels: rows.map((row) => shortTime(row.opened_at)),
      datasets: [
        { type: "line", label: "Preço (BRL)", data: rows.map((row) => row.close), yAxisID: "y", borderColor: "#087f7b", borderWidth: 2, pointRadius: 0, tension: 0.16, order: 0 },
        { type: "bar", label: "Volume (BRL)", data: rows.map((row) => row.volume), yAxisID: "y1", backgroundColor: "rgba(55,119,168,.22)", borderWidth: 0, order: 1 },
      ],
    },
    options: chartOptions(true),
  });
}

function renderPortfolio() {
  const data = state.portfolio || { positions: [] };
  document.getElementById("portfolio-kpis").innerHTML = [
    metricCard("landmark", "Valor da carteira", formatBRL(data.total_value_brl), `${data.positions.length || 0} posições`),
    metricCard("banknote", "Caixa disponível", formatBRL(data.cash_brl), "BRL virtual"),
    metricCard("chart-no-axes-column-increasing", "Resultado total", formatBRL(data.pnl_brl), formatPct(data.pnl_pct), changeClass(data.pnl_brl)),
    metricCard("history", "P/L realizado", formatBRL(data.realized_pnl_brl), "Operações encerradas", changeClass(data.realized_pnl_brl)),
    metricCard("database", "Cotação das posições", data.market_data_ready ? "Atualizada" : "Aguardando", "Último snapshot", data.market_data_ready ? "is-positive" : "is-warning"),
  ].join("");
  document.getElementById("portfolio-note").textContent = `${data.disclaimer || ""} A carteira fica associada a este navegador por até 90 dias; limpar os cookies cria uma nova carteira.`;
  document.getElementById("portfolio-table").innerHTML = data.positions.length
    ? data.positions.map(positionRow).join("")
    : '<tr><td colspan="5">Nenhuma posição. Use Operar para simular uma compra.</td></tr>';
  document.getElementById("trade-table").innerHTML = data.recent_trades?.length
    ? data.recent_trades.map(tradeRow).join("")
    : '<tr><td colspan="5">Nenhuma operação registrada.</td></tr>';
  renderPortfolioChart(data.positions);
  refreshIcons();
}

function renderPortfolioChart(positions) {
  destroyChart("portfolio");
  const valued = positions.filter((item) => item.current_value_brl !== null);
  toggleChart("portfolio-chart", "portfolio-empty", valued.length > 0);
  if (!valued.length || typeof Chart === "undefined") return;
  state.charts.portfolio = new Chart(document.getElementById("portfolio-chart"), {
    type: "doughnut",
    data: {
      labels: valued.map((item) => displaySymbol(item.symbol)),
      datasets: [{ data: valued.map((item) => item.current_value_brl), backgroundColor: ["#d98926", "#536fa6", "#6d4da0", "#278767", "#2d8c9a", "#a45187", "#b66b0f"], borderColor: "#ffffff", borderWidth: 3 }],
    },
    options: { responsive: true, maintainAspectRatio: false, cutout: "66%", plugins: { legend: { position: "bottom", labels: { boxWidth: 10, usePointStyle: true, padding: 16 } } } },
  });
}

function renderAlerts() {
  const filtered = state.alerts.filter((item) => {
    if (state.alertFilter === "all") return true;
    if (state.alertFilter === "active") return item.condition_active;
    return item.status === state.alertFilter;
  });
  document.getElementById("alerts-table").innerHTML = filtered.map(alertRow).join("");
  document.getElementById("alerts-empty").classList.toggle("is-hidden", filtered.length > 0);
  refreshIcons();
}

function renderRules() {
  const profile = state.riskProfile.profile || state.rules[0]?.profile || "moderate";
  document.getElementById("risk-profile-select").value = profile;
  document.getElementById("reset-risk-profile").disabled = profile !== "custom";
  document.getElementById("rules-list").innerHTML = state.rules.map((rule) => `
    <article class="rule-row" data-rule-id="${rule.id}" data-rule-code="${escapeHtml(rule.code)}">
      <div class="rule-name"><strong>${escapeHtml(rule.label)}</strong><small>${escapeHtml(rule.metric)} · ${escapeHtml(rule.scope)}</small></div>
      <span class="severity-pill" data-severity="${escapeHtml(rule.severity)}">${severityLabel(rule.severity)}</span>
      <div class="rule-threshold"><input type="number" step="any" value="${rule.threshold}" aria-label="Limite de ${escapeHtml(rule.label)}"><span>${escapeHtml(rule.unit)}</span></div>
      <div class="table-actions">
        <label class="toggle" title="Ativar regra"><input type="checkbox" ${rule.enabled ? "checked" : ""} aria-label="Ativar ${escapeHtml(rule.label)}"><span class="toggle-track"></span></label>
        <button type="button" class="icon-button icon-button--small" data-save-rule title="Salvar regra" aria-label="Salvar regra"><i data-lucide="save"></i></button>
      </div>
    </article>`).join("");
}

function renderSystem() {
  const run = state.system?.latest_ingestion;
  const oldestStaleness = state.market.reduce((max, item) => item.staleness_minutes === null ? max : Math.max(max, item.staleness_minutes), 0);
  document.getElementById("system-kpis").innerHTML = [
    metricCard("database", "Banco de dados", "Online", "PostgreSQL acessível", "is-positive"),
    metricCard("download", "Última ingestão", run ? statusLabel(run.status) : "Sem execução", run?.finished_at ? formatDateTime(run.finished_at) : "Aguardando coleta", run?.status === "failed" ? "is-negative" : ""),
    metricCard("clock", "Maior defasagem", state.market.some((item) => item.calculated_at) ? formatMinutes(oldestStaleness) : "--", "Entre os quatro ativos", oldestStaleness >= ruleThreshold("stale_market_data", 45) ? "is-warning" : ""),
  ].join("");
  document.getElementById("system-detail").innerHTML = run ? `
    <div class="surface-heading"><div><span class="surface-kicker">Execução</span><h3>Última coleta registrada</h3></div><span class="status-pill" data-status="${run.status === "success" ? "resolved" : "new"}">${statusLabel(run.status)}</span></div>
    <dl><dt>Início</dt><dd>${formatDateTime(run.started_at)}</dd><dt>Duração</dt><dd>${run.duration_ms ?? "--"} ms</dd><dt>Candles recebidos</dt><dd>${run.candles_received}</dd><dt>Candles processados</dt><dd>${run.candles_upserted}</dd><dt>Erro</dt><dd>${escapeHtml(run.error_message || "Nenhum")}</dd></dl>` : '<div class="empty-state"><i data-lucide="hourglass"></i><p>Nenhuma coleta registrada.</p></div>';
  document.getElementById("system-runs-table").innerHTML = state.runs.length
    ? state.runs.map(runRow).join("")
    : '<tr><td colspan="6">Nenhuma execução registrada.</td></tr>';
}

async function handleLogin(event) {
  event.preventDefault();
  if (event.submitter?.value === "cancel") {
    closeDialog("login-dialog");
    return;
  }
  const error = document.getElementById("login-error");
  error.classList.add("is-hidden");
  try {
    await api("/api/auth/login", { method: "POST", body: JSON.stringify({ password: document.getElementById("operator-password").value }) });
    state.authenticated = true;
    document.getElementById("operator-password").value = "";
    closeDialog("login-dialog");
    renderOperatorState();
    toast("Sessão de operador iniciada.");
  } catch {
    error.classList.remove("is-hidden");
  }
}

async function logout() {
  await safeApi("/api/auth/logout", { method: "POST" });
  state.authenticated = false;
  renderOperatorState();
  toast("Sessão encerrada.");
}

function renderOperatorState() {
  const indicator = document.getElementById("operator-state");
  indicator.classList.toggle("is-authenticated", state.authenticated);
  indicator.innerHTML = state.authenticated ? '<i data-lucide="shield-check"></i> Operador' : '<i data-lucide="lock-keyhole"></i> Leitura';
  document.getElementById("login-button").title = state.authenticated ? "Encerrar sessão" : "Acesso do operador";
  refreshIcons();
}

function requireLogin() {
  if (state.authenticated) return true;
  openDialog("login-dialog");
  toast("Autenticação necessária.");
  return false;
}

function recoverOperatorSession(error) {
  if (error.status !== 401) return false;
  state.authenticated = false;
  renderOperatorState();
  openDialog("login-dialog");
  toast("Sua sessão expirou. Entre novamente.", true);
  return true;
}

function openTradeDialog() {
  document.getElementById("trade-side").value = "buy";
  document.getElementById("position-symbol").value = state.selectedSymbol;
  document.getElementById("trade-notional").value = "";
  document.getElementById("trade-quantity").value = "";
  document.getElementById("position-error").classList.add("is-hidden");
  syncTradeFields();
  openDialog("position-dialog");
}

function syncTradeFields() {
  const isBuy = document.getElementById("trade-side").value === "buy";
  document.getElementById("trade-notional-field").classList.toggle("is-hidden", !isBuy);
  document.getElementById("trade-quantity-field").classList.toggle("is-hidden", isBuy);
  document.getElementById("trade-notional").required = isBuy;
  document.getElementById("trade-quantity").required = !isBuy;
}

async function handleTradeSubmit(event) {
  event.preventDefault();
  if (event.submitter?.value === "cancel") {
    closeDialog("position-dialog");
    return;
  }
  const symbol = document.getElementById("position-symbol").value;
  const side = document.getElementById("trade-side").value;
  const payload = side === "buy"
    ? { side, notional_brl: Number(document.getElementById("trade-notional").value) }
    : { side, quantity: Number(document.getElementById("trade-quantity").value) };
  try {
    const result = await api(`/api/portfolio/trades/${encodeURIComponent(symbol)}`, { method: "POST", body: JSON.stringify(payload) });
    state.portfolio = result.portfolio;
    closeDialog("position-dialog");
    renderPortfolio();
    toast(side === "buy" ? "Compra simulada registrada." : "Venda simulada registrada.");
  } catch (error) {
    const message = document.getElementById("position-error");
    message.textContent = error.message;
    message.classList.remove("is-hidden");
  }
}

async function resetSimulator() {
  if (!window.confirm("Resetar a carteira para R$ 10.000 e apagar as operações?")) return;
  const payload = await safeApi("/api/portfolio/reset", { method: "POST" });
  if (!payload) return;
  state.portfolio = payload;
  renderPortfolio();
  toast("Carteira resetada.");
}

async function handlePortfolioAction(event) {
  const button = event.target.closest("button[data-action]");
  if (!button || !requireLogin()) return;
  const position = state.portfolio.positions.find((item) => item.symbol === button.dataset.symbol);
  if (button.dataset.action === "edit") openPositionDialog(position);
  if (button.dataset.action === "delete") {
    try {
      await api(`/api/portfolio/positions/${encodeURIComponent(button.dataset.symbol)}`, { method: "DELETE" });
      state.portfolio = await api("/api/portfolio");
      renderPortfolio();
      toast("Posição removida; alertas serão reavaliados na próxima coleta.");
    } catch (error) {
      if (recoverOperatorSession(error)) return;
      toast(error.message, true);
    }
  }
}

async function handleAlertAction(event) {
  const historyButton = event.target.closest("button[data-alert-history]");
  if (historyButton) {
    try {
      const events = await api(`/api/alerts/${historyButton.dataset.alertHistory}/events`);
      document.getElementById("alert-events-list").innerHTML = events.length
        ? events.map(alertEventItem).join("")
        : '<div class="empty-state"><p>Nenhum evento registrado.</p></div>';
      openDialog("alert-events-dialog");
    } catch (error) {
      toast(error.message, true);
    }
    return;
  }
  const button = event.target.closest("button[data-alert-status]");
  if (!button || !requireLogin()) return;
  try {
    await api(`/api/alerts/${button.dataset.alertId}`, { method: "PATCH", body: JSON.stringify({ status: button.dataset.alertStatus }) });
    state.alerts = await api("/api/alerts");
    renderAlerts();
    renderMarket();
    toast("Estado do alerta atualizado.");
  } catch (error) {
    if (recoverOperatorSession(error)) return;
    toast(error.message, true);
  }
}

async function handleRuleAction(event) {
  const button = event.target.closest("button[data-save-rule]");
  if (!button || !requireLogin()) return;
  const row = button.closest("[data-rule-id]");
  const payload = { threshold: Number(row.querySelector('input[type="number"]').value), enabled: row.querySelector('input[type="checkbox"]').checked };
  try {
    await api(`/api/settings/rules/${row.dataset.ruleCode}`, { method: "PUT", body: JSON.stringify(payload) });
    [state.rules, state.riskProfile] = await Promise.all([api("/api/rules"), api("/api/settings/risk-profile")]);
    renderRules();
    refreshIcons();
    toast("Regra atualizada; será aplicada na próxima coleta.");
  } catch (error) {
    if (recoverOperatorSession(error)) return;
    toast(error.message, true);
  }
}

async function handleProfileChange(event) {
  if (!requireLogin()) {
    event.target.value = state.riskProfile.profile;
    return;
  }
  try {
    state.riskProfile = await api("/api/settings/risk-profile", {
      method: "PUT",
      body: JSON.stringify({ profile: event.target.value }),
    });
    state.rules = await api("/api/rules");
    renderAll();
    toast(
      `Perfil ${profileLabel(state.riskProfile.profile)} ativado; regras serão aplicadas na próxima coleta.`,
    );
  } catch (error) {
    event.target.value = state.riskProfile.profile;
    if (recoverOperatorSession(error)) return;
    toast(error.message, true);
  }
}

async function handleProfileReset() {
  if (!requireLogin()) return;
  try {
    state.riskProfile = await api("/api/settings/risk-profile/reset", { method: "POST" });
    state.rules = await api("/api/rules");
    renderAll();
    toast("Limites personalizados restaurados; serão aplicados na próxima coleta.");
  } catch (error) {
    if (recoverOperatorSession(error)) return;
    toast(error.message, true);
  }
}

function metricCard(icon, label, value, meta, valueClass = "") {
  return `<article class="metric-card"><span class="metric-label">${escapeHtml(label)}<i data-lucide="${icon}"></i></span><strong class="metric-value ${valueClass}">${escapeHtml(String(value ?? "--"))}</strong><span class="metric-meta">${escapeHtml(String(meta ?? ""))}</span></article>`;
}

function assetCard(item) {
  const change = item.return_24h_pct;
  return `<button type="button" class="asset-card ${item.symbol === state.selectedSymbol ? "is-selected" : ""}" data-symbol="${escapeHtml(item.symbol)}"><span class="asset-card__top"><span class="asset-symbol"><span class="asset-icon" data-asset="${escapeHtml(item.symbol)}">${escapeHtml(item.symbol.slice(0, 2))}</span><span><strong>${escapeHtml(displaySymbol(item.symbol))}</strong><small>${escapeHtml(item.display_name)}</small></span></span><span class="change-pill ${changeClass(change) || "is-neutral"}">${formatPct(change)}</span></span><strong class="asset-price">${formatBRL(item.price_brl)}</strong><span class="asset-card__bottom"><span>Vol. ${formatPct(item.volatility_24h_pct)}</span><span>${item.staleness_minutes === null ? "Sem dados" : `${Math.round(item.staleness_minutes)} min`}</span></span></button>`;
}

function compactAlert(item) {
  return `<article class="compact-alert" data-severity="${escapeHtml(item.severity)}"><div class="compact-alert__top"><strong>${escapeHtml(item.label)}</strong><span class="severity-pill" data-severity="${escapeHtml(item.severity)}">${severityLabel(item.severity)}</span></div><p>${escapeHtml(item.symbol ? displaySymbol(item.symbol) : "Portfólio")} · ${escapeHtml(item.message)}</p></article>`;
}

function definition(title, body) {
  return `<article class="definition-item"><strong>${escapeHtml(title)}</strong><p>${escapeHtml(body)}</p></article>`;
}

function positionRow(item) {
  return `<tr><td><strong>${escapeHtml(displaySymbol(item.symbol))}</strong></td><td class="table-number">${formatNumber(item.quantity, 8)}</td><td class="table-number">${formatBRL(item.average_price_brl)}</td><td class="table-number">${formatBRL(item.current_value_brl)}</td><td class="table-number ${changeClass(item.pnl_brl)}">${formatBRL(item.pnl_brl)}</td></tr>`;
}

function tradeRow(item) {
  const label = item.side === "buy" ? "Compra" : "Venda";
  return `<tr><td>${formatDateTime(item.executed_at)}</td><td><span class="status-pill" data-status="${item.side === "buy" ? "resolved" : "acknowledged"}">${label}</span></td><td>${escapeHtml(displaySymbol(item.symbol))}</td><td class="table-number">${formatNumber(item.quantity, 8)}</td><td class="table-number">${formatBRL(item.notional_brl)}</td></tr>`;
}

function alertRow(item) {
  const actions = item.status === "new" ? `<button class="icon-button icon-button--small" type="button" data-alert-id="${item.id}" data-alert-status="acknowledged" title="Reconhecer" aria-label="Reconhecer alerta"><i data-lucide="eye"></i></button><button class="icon-button icon-button--small" type="button" data-alert-id="${item.id}" data-alert-status="dismissed" title="Dispensar" aria-label="Dispensar alerta"><i data-lucide="bell-off"></i></button>` : item.status === "acknowledged" ? `<button class="icon-button icon-button--small" type="button" data-alert-id="${item.id}" data-alert-status="resolved" title="Resolver" aria-label="Resolver alerta"><i data-lucide="check"></i></button>` : "";
  return `<tr><td><span class="severity-pill" data-severity="${escapeHtml(item.severity)}">${severityLabel(item.severity)}</span></td><td><strong>${escapeHtml(item.label)}</strong></td><td>${escapeHtml(item.symbol ? displaySymbol(item.symbol) : "Portfólio")}</td><td class="table-number">${formatNumber(item.observed, 2)}</td><td><span class="status-pill" data-status="${escapeHtml(item.status)}">${statusLabel(item.status)}</span></td><td>${formatDateTime(item.last_triggered_at)}</td><td><div class="table-actions"><button class="icon-button icon-button--small" type="button" data-alert-history="${item.id}" title="Ver histórico" aria-label="Ver histórico do alerta"><i data-lucide="history"></i></button>${actions}</div></td></tr>`;
}

function alertEventItem(item) {
  return `<article class="event-item"><strong>${escapeHtml(alertActionLabel(item.action))}</strong><small>${formatDateTime(item.created_at)} · ${escapeHtml(item.actor)}</small></article>`;
}

function runRow(item) {
  return `<tr><td>${escapeHtml(item.source)}</td><td><span class="status-pill" data-status="${item.status === "success" ? "resolved" : "new"}">${statusLabel(item.status)}</span></td><td>${formatDateTime(item.started_at)}</td><td class="table-number">${item.duration_ms ?? "--"} ms</td><td class="table-number">${item.candles_received}</td><td class="table-number">${item.candles_upserted}</td></tr>`;
}

function alertActionLabel(value) {
  return { triggered: "Condição detectada", aggravated: "Condição agravada", repeated: "Condição ainda ativa", acknowledged: "Reconhecido", resolved: "Normalizado", dismissed: "Dispensado", reopened: "Reaberto", condition_cleared: "Condição encerrada", disabled: "Regra desativada", profile_changed: "Perfil alterado" }[value] || value;
}

function chartOptions(withVolume) {
  const scales = {
    x: { grid: { display: false }, ticks: { maxTicksLimit: 8, color: "#718087", font: { size: 10 } } },
    y: { type: "linear", axis: "y", position: "left", grid: { color: "rgba(115,132,140,.12)" }, ticks: { color: "#718087", callback: (value) => compactBRL(value) } },
  };
  if (withVolume) scales.y1 = { type: "linear", axis: "y", position: "right", grid: { drawOnChartArea: false }, beginAtZero: true, ticks: { color: "#718087", callback: (value) => compactBRL(value) } };
  return { responsive: true, maintainAspectRatio: false, interaction: { mode: "index", intersect: false }, animation: { duration: 250 }, plugins: { legend: { display: withVolume, position: "bottom", labels: { boxWidth: 10, usePointStyle: true } }, tooltip: { callbacks: { label: (context) => context.dataset.yAxisID === "y1" ? ` Volume (BRL): ${formatBRL(context.raw)}` : ` Preço: ${formatBRL(context.raw)}` } } }, scales: withVolume ? scales : { x: scales.x, y: scales.y } };
}

function toggleChart(canvasId, emptyId, hasData) {
  document.getElementById(canvasId).parentElement.classList.toggle("is-hidden", !hasData);
  document.getElementById(emptyId).classList.toggle("is-hidden", hasData);
}

function destroyChart(slot) {
  if (state.charts[slot]) state.charts[slot].destroy();
  state.charts[slot] = null;
}

function syncSelectedAsset() {
  document.querySelectorAll(".asset-card").forEach((card) => card.classList.toggle("is-selected", card.dataset.symbol === state.selectedSymbol));
  document.getElementById("asset-selector").value = state.selectedSymbol;
  renderAssetSummary();
}

function selectedAsset() {
  return state.market.find((item) => item.symbol === state.selectedSymbol) || null;
}

async function api(path, options = {}) {
  const response = await fetch(path, { headers: { "Content-Type": "application/json", ...(options.headers || {}) }, ...options });
  if (response.status === 204) return null;
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(payload.detail || `Falha HTTP ${response.status}`);
    error.status = response.status;
    throw error;
  }
  return payload;
}

async function safeApi(path, options = {}) {
  try {
    return await api(path, options);
  } catch (error) {
    showBanner(error.message);
    return null;
  }
}

function openDialog(id) {
  const dialog = document.getElementById(id);
  if (!dialog.open) dialog.showModal();
  refreshIcons();
}

function closeDialog(id) {
  const dialog = document.getElementById(id);
  if (dialog.open) dialog.close();
}

function showBanner(message) {
  const banner = document.getElementById("system-banner");
  banner.textContent = message;
  banner.classList.remove("is-hidden");
}

function hideBanner() {
  document.getElementById("system-banner").classList.add("is-hidden");
}

function toast(message, isError = false) {
  const region = document.getElementById("toast-region");
  const item = document.createElement("div");
  item.className = `toast${isError ? " is-error" : ""}`;
  item.textContent = message;
  region.appendChild(item);
  setTimeout(() => item.remove(), 3600);
}

function setSystemState(ok) {
  const dot = document.getElementById("sidebar-status-dot");
  dot.classList.toggle("is-ok", ok);
  dot.classList.toggle("is-error", !ok);
  document.getElementById("sidebar-status-label").textContent = ok ? "Sistema online" : "Falha de conexão";
  document.getElementById("sidebar-status-time").textContent = ok ? `Atualizado ${new Date().toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })}` : "Verifique a API";
}

function newestMarketTime() {
  const dates = state.market.map((item) => item.calculated_at).filter(Boolean).map((value) => new Date(value));
  if (!dates.length) return "Sem coleta";
  return `Atualizado ${formatDateTime(new Date(Math.max(...dates)))}`;
}

function displaySymbol(symbol) {
  return symbol?.endsWith("BRL") ? `${symbol.slice(0, -3)}/BRL` : symbol || "--";
}

function formatBRL(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "--";
  const numeric = Math.abs(Number(value));
  const digits = numeric < 0.01 ? 8 : numeric < 10 ? 4 : 2;
  return new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL", minimumFractionDigits: digits, maximumFractionDigits: digits }).format(value);
}

function compactBRL(value) {
  if (Math.abs(Number(value)) < 0.01) return formatBRL(value);
  return new Intl.NumberFormat("pt-BR", { notation: "compact", style: "currency", currency: "BRL", maximumFractionDigits: 1 }).format(value);
}

function formatPct(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "--";
  return `${Number(value).toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}%`;
}

function formatRatio(value) {
  if (value === null || value === undefined) return "--";
  return `${formatNumber(value, 2)}x`;
}

function formatNumber(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "--";
  return Number(value).toLocaleString("pt-BR", { maximumFractionDigits: digits });
}

function formatMinutes(value) {
  if (value === null || value === undefined) return "--";
  return `${Math.round(value)} min`;
}

function formatDateTime(value) {
  if (!value) return "--";
  return new Date(value).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
}

function shortTime(value) {
  return new Date(value).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function changeClass(value) {
  if (value === null || value === undefined || Number(value) === 0) return "is-neutral";
  return Number(value) > 0 ? "is-positive" : "is-negative";
}

function severityLabel(value) {
  return { warning: "Atenção", high: "Alto", critical: "Crítico" }[value] || value;
}

function statusLabel(value) {
  return { new: "Novo", acknowledged: "Reconhecido", resolved: "Resolvido", dismissed: "Dispensado", success: "Sucesso", failed: "Falhou", running: "Executando" }[value] || value;
}

function profileLabel(value) {
  return { conservative: "Conservador", moderate: "Moderado", aggressive: "Agressivo", custom: "Personalizado" }[value] || "Sem perfil";
}

function ruleThreshold(code, fallback) {
  const threshold = Number(state.rules.find((rule) => rule.code === code)?.threshold);
  return Number.isFinite(threshold) ? threshold : fallback;
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[character]);
}

function refreshIcons() {
  if (window.lucide) window.lucide.createIcons({ attrs: { "aria-hidden": "true" } });
}
