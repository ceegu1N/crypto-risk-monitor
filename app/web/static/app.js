"use strict";

const state = {
  market: [],
  alerts: [],
  portfolio: null,
  rules: [],
  system: null,
  authenticated: false,
  selectedSymbol: "BTCBRL",
  selectedPeriod: "24h",
  alertFilter: "active",
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
  document.getElementById("add-position-button").addEventListener("click", () => {
    if (requireLogin()) openPositionDialog();
  });
  document.getElementById("login-form").addEventListener("submit", handleLogin);
  document.getElementById("position-form").addEventListener("submit", handlePositionSave);
  document.getElementById("portfolio-table").addEventListener("click", handlePortfolioAction);
  document.getElementById("alerts-table").addEventListener("click", handleAlertAction);
  document.getElementById("rules-list").addEventListener("click", handleRuleAction);
}

function setView(view) {
  if (!viewMeta[view]) return;
  document.querySelectorAll(".nav-item").forEach((item) => item.classList.toggle("is-active", item.dataset.view === view));
  document.querySelectorAll(".view-panel").forEach((panel) => panel.classList.toggle("is-active", panel.dataset.viewPanel === view));
  document.getElementById("view-eyebrow").textContent = viewMeta[view][0];
  document.getElementById("view-title").textContent = viewMeta[view][1];
  if (view === "asset") loadAssetCandles();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

async function refreshAll() {
  const refreshButton = document.getElementById("refresh-button");
  refreshButton.classList.add("is-spinning");
  hideBanner();
  try {
    const [market, alerts, portfolio, rules, system, session] = await Promise.all([
      api("/api/market"),
      api("/api/alerts"),
      api("/api/portfolio"),
      api("/api/rules"),
      api("/api/system"),
      api("/api/auth/session"),
    ]);
    state.market = market;
    state.alerts = alerts;
    state.portfolio = portfolio;
    state.rules = rules;
    state.system = system;
    state.authenticated = session.authenticated;
    if (!state.market.some((item) => item.symbol === state.selectedSymbol) && state.market.length) {
      state.selectedSymbol = state.market[0].symbol;
    }
    renderAll();
    await loadMarketChart();
    setSystemState(true);
  } catch (error) {
    showBanner(error.message || "Não foi possível atualizar o painel.");
    setSystemState(false);
  } finally {
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
  const highestVolatility = priced.reduce((best, item) => {
    if (item.volatility_24h_pct === null) return best;
    return !best || item.volatility_24h_pct > best.volatility_24h_pct ? item : best;
  }, null);
  const staleAssets = priced.filter((item) => item.staleness_minutes !== null && item.staleness_minutes >= 45);

  document.getElementById("market-kpis").innerHTML = [
    metricCard("radio", "Ativos com preço", `${priced.length}/${state.market.length}`, "Pares monitorados"),
    metricCard("bell", "Alertas ativos", activeAlerts.length, activeAlerts.length ? "Exigem leitura" : "Sem exceções abertas", activeAlerts.length ? "is-warning" : "is-positive"),
    metricCard("waves", "Maior volatilidade", highestVolatility ? formatPct(highestVolatility.volatility_24h_pct) : "--", highestVolatility ? displaySymbol(highestVolatility.symbol) : "Histórico insuficiente", highestVolatility ? "is-warning" : ""),
    metricCard("clock-3", "Dados atrasados", staleAssets.length, staleAssets.length ? "Acima de 45 min" : "Coleta dentro do limite", staleAssets.length ? "is-negative" : "is-positive"),
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
    metricCard("waves", "Volatilidade em 24h", formatPct(item.volatility_24h_pct), "Oscilação realizada", item.volatility_24h_pct >= 4 ? "is-warning" : ""),
  ].join("");
  document.getElementById("asset-definitions").innerHTML = [
    definition("Retorno", "Compara o preço atual com o preço observado no início da janela."),
    definition("Volatilidade", "Resume a dispersão dos retornos de 15 minutos ao longo de 24 horas."),
    definition("Drawdown", `Preço atual em relação ao maior preço da janela: ${formatPct(item.drawdown_7d_pct)}.`),
    definition("Volume relativo", `Volume do candle atual dividido pela média anterior: ${formatRatio(item.volume_ratio)}.`),
    definition("Atualização", item.calculated_at ? formatDateTime(item.calculated_at) : "Ainda não calculada."),
    definition("Escopo", "Indicadores de mercado; não estimam risco regulatório nem recomendam operação."),
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
  const data = await safeApi(`/api/assets/${encodeURIComponent(state.selectedSymbol)}/candles?period=${state.selectedPeriod}&limit=672`);
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
    data: {
      labels: rows.map((row) => shortTime(row.opened_at)),
      datasets: [
        { type: "line", label: "Preço (BRL)", data: rows.map((row) => row.close), yAxisID: "price", borderColor: "#087f7b", borderWidth: 2, pointRadius: 0, tension: 0.16 },
        { type: "bar", label: "Volume", data: rows.map((row) => row.volume), yAxisID: "volume", backgroundColor: "rgba(55,119,168,.22)", borderWidth: 0 },
      ],
    },
    options: chartOptions(true),
  });
}

function renderPortfolio() {
  const data = state.portfolio || { positions: [] };
  document.getElementById("portfolio-kpis").innerHTML = [
    metricCard("landmark", "Valor atual", formatBRL(data.total_value_brl), `${data.positions.length || 0} posições`),
    metricCard("chart-no-axes-column-increasing", "Resultado", formatBRL(data.pnl_brl), formatPct(data.pnl_pct), changeClass(data.pnl_brl)),
    metricCard("pie-chart", "Maior posição", formatPct(data.max_weight_pct), "Concentração", data.max_weight_pct >= 60 ? "is-warning" : ""),
    metricCard("flame", "Ativos voláteis", formatPct(data.volatile_asset_share_pct), "Parcela sem USDT", data.volatile_asset_share_pct >= 90 ? "is-warning" : ""),
  ].join("");
  document.getElementById("portfolio-note").textContent = data.risk_contribution_note || "";
  document.getElementById("portfolio-table").innerHTML = data.positions.length
    ? data.positions.map(positionRow).join("")
    : "";
  renderPortfolioChart(data.positions);
}

function renderPortfolioChart(positions) {
  destroyChart("portfolio");
  toggleChart("portfolio-chart", "portfolio-empty", positions.length > 0);
  if (!positions.length || typeof Chart === "undefined") return;
  state.charts.portfolio = new Chart(document.getElementById("portfolio-chart"), {
    type: "doughnut",
    data: {
      labels: positions.map((item) => displaySymbol(item.symbol)),
      datasets: [{ data: positions.map((item) => item.current_value_brl), backgroundColor: ["#d98926", "#536fa6", "#6d4da0", "#278767"], borderColor: "#ffffff", borderWidth: 3 }],
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
  document.getElementById("rules-list").innerHTML = state.rules.map((rule) => `
    <article class="rule-row" data-rule-id="${rule.id}">
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
    metricCard("clock", "Maior defasagem", state.market.some((item) => item.calculated_at) ? formatMinutes(oldestStaleness) : "--", "Entre os quatro ativos", oldestStaleness >= 45 ? "is-warning" : ""),
  ].join("");
  document.getElementById("system-detail").innerHTML = run ? `
    <div class="surface-heading"><div><span class="surface-kicker">Execução</span><h3>Última coleta registrada</h3></div><span class="status-pill" data-status="${run.status === "success" ? "resolved" : "new"}">${statusLabel(run.status)}</span></div>
    <dl><dt>Início</dt><dd>${formatDateTime(run.started_at)}</dd><dt>Duração</dt><dd>${run.duration_ms ?? "--"} ms</dd><dt>Candles recebidos</dt><dd>${run.candles_received}</dd><dt>Candles processados</dt><dd>${run.candles_upserted}</dd><dt>Erro</dt><dd>${escapeHtml(run.error_message || "Nenhum")}</dd></dl>` : '<div class="empty-state"><i data-lucide="hourglass"></i><p>Nenhuma coleta registrada.</p></div>';
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

function openPositionDialog(position = null) {
  document.getElementById("position-symbol").value = position?.symbol || state.selectedSymbol;
  document.getElementById("position-quantity").value = position?.quantity || "";
  document.getElementById("position-cost").value = position?.cost_basis_brl || "";
  document.getElementById("position-error").classList.add("is-hidden");
  openDialog("position-dialog");
}

async function handlePositionSave(event) {
  event.preventDefault();
  if (event.submitter?.value === "cancel") {
    closeDialog("position-dialog");
    return;
  }
  const symbol = document.getElementById("position-symbol").value;
  const quantity = Number(document.getElementById("position-quantity").value);
  const costRaw = document.getElementById("position-cost").value;
  const payload = { quantity, cost_basis_brl: costRaw ? Number(costRaw) : null };
  try {
    await api(`/api/portfolio/positions/${encodeURIComponent(symbol)}`, { method: "PUT", body: JSON.stringify(payload) });
    state.portfolio = await api("/api/portfolio");
    closeDialog("position-dialog");
    renderPortfolio();
    toast("Posição salva.");
  } catch (error) {
    if (error.status === 401) return requireLogin();
    const message = document.getElementById("position-error");
    message.textContent = error.message;
    message.classList.remove("is-hidden");
  }
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
      toast("Posição removida.");
    } catch (error) {
      toast(error.message, true);
    }
  }
}

async function handleAlertAction(event) {
  const button = event.target.closest("button[data-alert-status]");
  if (!button || !requireLogin()) return;
  try {
    await api(`/api/alerts/${button.dataset.alertId}`, { method: "PATCH", body: JSON.stringify({ status: button.dataset.alertStatus }) });
    state.alerts = await api("/api/alerts");
    renderAlerts();
    renderMarket();
    toast("Estado do alerta atualizado.");
  } catch (error) {
    toast(error.message, true);
  }
}

async function handleRuleAction(event) {
  const button = event.target.closest("button[data-save-rule]");
  if (!button || !requireLogin()) return;
  const row = button.closest("[data-rule-id]");
  const payload = { threshold: Number(row.querySelector('input[type="number"]').value), enabled: row.querySelector('input[type="checkbox"]').checked };
  try {
    await api(`/api/rules/${row.dataset.ruleId}`, { method: "PATCH", body: JSON.stringify(payload) });
    state.rules = await api("/api/rules");
    renderRules();
    refreshIcons();
    toast("Regra atualizada.");
  } catch (error) {
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
  return `<tr><td><strong>${escapeHtml(displaySymbol(item.symbol))}</strong><br><small>${formatNumber(item.quantity, 8)}</small></td><td class="table-number">${formatBRL(item.current_value_brl)}</td><td class="table-number">${formatPct(item.weight_pct)}</td><td class="table-number ${changeClass(item.pnl_brl)}">${formatBRL(item.pnl_brl)}</td><td><div class="table-actions"><button class="icon-button icon-button--small" type="button" data-action="edit" data-symbol="${escapeHtml(item.symbol)}" title="Editar posição" aria-label="Editar posição"><i data-lucide="pencil"></i></button><button class="icon-button icon-button--small" type="button" data-action="delete" data-symbol="${escapeHtml(item.symbol)}" title="Remover posição" aria-label="Remover posição"><i data-lucide="trash-2"></i></button></div></td></tr>`;
}

function alertRow(item) {
  const actions = item.status === "new" ? `<button class="icon-button icon-button--small" type="button" data-alert-id="${item.id}" data-alert-status="acknowledged" title="Reconhecer" aria-label="Reconhecer alerta"><i data-lucide="eye"></i></button><button class="icon-button icon-button--small" type="button" data-alert-id="${item.id}" data-alert-status="dismissed" title="Dispensar" aria-label="Dispensar alerta"><i data-lucide="bell-off"></i></button>` : item.status === "acknowledged" ? `<button class="icon-button icon-button--small" type="button" data-alert-id="${item.id}" data-alert-status="resolved" title="Resolver" aria-label="Resolver alerta"><i data-lucide="check"></i></button>` : "";
  return `<tr><td><span class="severity-pill" data-severity="${escapeHtml(item.severity)}">${severityLabel(item.severity)}</span></td><td><strong>${escapeHtml(item.label)}</strong></td><td>${escapeHtml(item.symbol ? displaySymbol(item.symbol) : "Portfólio")}</td><td class="table-number">${formatNumber(item.observed, 2)}</td><td><span class="status-pill" data-status="${escapeHtml(item.status)}">${statusLabel(item.status)}</span></td><td>${formatDateTime(item.last_triggered_at)}</td><td><div class="table-actions">${actions}</div></td></tr>`;
}

function chartOptions(withVolume) {
  const scales = {
    x: { grid: { display: false }, ticks: { maxTicksLimit: 8, color: "#718087", font: { size: 10 } } },
    price: { position: "left", grid: { color: "rgba(115,132,140,.12)" }, ticks: { color: "#718087", callback: (value) => compactBRL(value) } },
  };
  if (withVolume) scales.volume = { position: "right", grid: { display: false }, ticks: { display: false }, beginAtZero: true };
  return { responsive: true, maintainAspectRatio: false, interaction: { mode: "index", intersect: false }, animation: { duration: 250 }, plugins: { legend: { display: withVolume, position: "bottom", labels: { boxWidth: 10, usePointStyle: true } }, tooltip: { callbacks: { label: (context) => context.dataset.yAxisID === "volume" ? ` Volume: ${formatNumber(context.raw, 2)}` : ` Preço: ${formatBRL(context.raw)}` } } }, scales: withVolume ? scales : { x: scales.x, y: scales.price } };
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
  const digits = Math.abs(Number(value)) < 10 ? 4 : 2;
  return new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL", minimumFractionDigits: 2, maximumFractionDigits: digits }).format(value);
}

function compactBRL(value) {
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

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[character]);
}

function refreshIcons() {
  if (window.lucide) window.lucide.createIcons({ attrs: { "aria-hidden": "true" } });
}
