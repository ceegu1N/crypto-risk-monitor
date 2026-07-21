# Public Cloud Simulator Implementation Plan

> For agentic workers: use inline task execution with checkpoints. Steps use checkbox syntax for tracking.

**Goal:** Transform the existing monitor into a public anonymous spot-portfolio simulator with seven BRL assets, up to three months of chart history, and a Vercel/Neon deployment path.

**Architecture:** Market candles remain shared in PostgreSQL and are collected by GitHub Actions. Each browser receives a persistent anonymous identity cookie whose hash points to an independent portfolio and trade history. Vercel serves FastAPI and the dashboard, Neon stores durable state, and Docker Compose remains the local development environment.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy, Alembic, PostgreSQL/Neon, Pydantic, Binance public market-data API, vanilla JavaScript, Chart.js, Vercel Functions, GitHub Actions, Docker Compose.

---

### Task 1: Add portfolio and trade persistence

**Files:**
- Modify: app/models.py
- Create: migrations/versions/0008_anonymous_simulator.py
- Test: tests/integration/test_database.py
- Test: tests/unit/test_schemas.py

- [ ] Write failing tests for two portfolios owning the same asset independently, decimal cash, one trade per portfolio, invalid sides, negative cash, zero quantities, and duplicate identity hashes.
- [ ] Run the focused tests and confirm they fail because the new entities do not exist.
- [ ] Add AnonymousPortfolio with UUID id, SHA-256 identity_hash, cash_brl initialized to 10000, last_seen_at, and created_at.
- [ ] Add SimulatedPosition keyed by portfolio_id and asset_id with quantity, average_price_brl, and updated_at.
- [ ] Add SimulatedTrade with portfolio_id, asset_id, side, quantity, price_brl, notional_brl, executed_at, and source.
- [ ] Add PostgreSQL constraints for positive numeric values, side in buy/sell, indexes on last_seen_at and portfolio_id/executed_at, and cascade deletes only for portfolio-owned rows.
- [ ] Write Alembic revision 0008_anonymous_simulator. Do not delete the legacy global portfolio table yet.
- [ ] Run database tests, alembic upgrade head, and alembic check.
- [ ] Commit with: git commit -m "feat: add anonymous simulator persistence"

### Task 2: Implement anonymous identity and simulated trading

**Files:**
- Modify: app/main.py
- Modify: app/api/dependencies.py
- Modify: app/api/schemas.py
- Create: app/services/simulator.py
- Modify: app/api/routes.py
- Test: tests/unit/test_simulator.py
- Test: tests/integration/test_api.py

- [ ] Test first visit creates exactly R$ 10,000, the same cookie recovers the portfolio, different cookies are isolated, reset works, and unavailable quotes do not create trades.
- [ ] Create a random 32-byte token in a persistent cookie named __Host-crypto_guest. Hash the token before lookup. Use a 90-day sliding max age, HttpOnly, SameSite=Lax, and Secure when HTTPS is active. Keep the operator session separate.
- [ ] Implement get_or_create_portfolio, execute_trade, portfolio_summary, list_trades, and reset_portfolio in app/services/simulator.py.
- [ ] Execute trades inside one PostgreSQL transaction with SELECT FOR UPDATE on the portfolio row. Validate values, fetch a fresh public Binance quote, append the trade, update cash and average cost, and commit atomically.
- [ ] Reject purchases above cash, sales above position quantity, unknown assets, non-positive decimals, and trades when the quote is unavailable. The first release has no fee, spread, or slippage.
- [ ] Add public routes for /api/simulator, /api/simulator/trades, /api/simulator/trade, and /api/simulator/reset. Return HTTP 409 for insufficient balance, insufficient quantity, or unavailable quotes.
- [ ] Run the focused simulator and API tests.
- [ ] Commit with: git commit -m "feat: add anonymous simulated trading"

### Task 3: Add ADA, PEPE, NEAR and three-month history

**Files:**
- Modify: app/config.py
- Modify: .env.example
- Modify: app/web/templates/index.html
- Modify: app/web/static/app.js
- Modify: app/api/routes.py
- Create: scripts/backfill_history.py
- Test: tests/unit/test_config.py
- Test: tests/unit/test_binance.py
- Test: tests/integration/test_collector.py
- Test: tests/integration/test_api.py

- [ ] Change default symbols to BTCBRL,ETHBRL,SOLBRL,USDTBRL,ADABRL,PEPEBRL,NEARBRL and add tests for the seven defaults.
- [ ] Create scripts/backfill_history.py with --days 90, --symbol, and --once options. Reuse BinanceClient.fetch_candles and IngestionService, print progress, and rely on the unique candle constraint for safe reruns.
- [ ] Replace the API period mapping with 1d, 7d, 1m, and 3m. Aggregate raw candles on the server and return no more than 500 points.
- [ ] Use 15-minute points for 1d, hourly points for 7d, four-hour points for 1m, and twelve-hour points for 3m. Preserve open, high, low, close, volume, and ascending timestamps.
- [ ] Add accessible chart controls for 1D, 7D, 1M, and 3M. Do not add a one-year option.
- [ ] Test pagination, duplicate safety, incomplete-candle exclusion, all period mappings, ascending timestamps, and bounded response size.
- [ ] Commit with: git commit -m "feat: expand assets and three-month charts"

### Task 4: Redesign the public portfolio interface

**Files:**
- Modify: app/web/templates/index.html
- Modify: app/web/static/app.js
- Modify: app/web/static/app.css
- Test: tests/integration/test_web.py

- [ ] Show cash, total value, P/L, concentration, positions, and recent operations.
- [ ] Add a buy/sell form with asset selection, BRL amount or quantity, current quote preview, and confirmation.
- [ ] Add fictitious-balance, no-fee, and no-real-trading disclaimers near the action area.
- [ ] Add reset confirmation, success/error toasts, disabled submit states, empty states, stale-market warnings, and a new-portfolio message.
- [ ] Remove the legacy global portfolio editor from public navigation while keeping admin rule controls protected.
- [ ] Run web tests, node --check app/web/static/app.js, and the local visual audit at desktop and 390x844 widths.
- [ ] Commit with: git commit -m "feat: add public simulator interface"

### Task 5: Prepare Vercel, Neon, and scheduled operations

**Files:**
- Create: vercel.json
- Create: api/index.py
- Create: .github/workflows/migrate.yml
- Modify: .github/workflows/collect.yml
- Modify: docs/DEPLOY.md
- Modify: README.md
- Test: tests/unit/test_project_configuration.py

- [ ] Expose the FastAPI factory through api/index.py and configure Vercel routing. Keep the web process stateless apart from Neon.
- [ ] Use a pooled Neon URL for web requests and a direct owner URL only for Alembic migrations.
- [ ] Add a manual migration workflow using MIGRATION_DATABASE_URL.
- [ ] Update collection defaults and schedule incremental collection every 15 minutes. Add manual backfill and cleanup of portfolios inactive for 90 days.
- [ ] Document Vercel variables, Neon roles, GitHub secrets, cookie behavior, first backfill, free-tier cold starts, migration order, and disabling the public deployment.
- [ ] Validate JSON and the Vercel entrypoint locally, then run the existing Docker Compose configuration.
- [ ] Commit with: git commit -m "feat: prepare vercel neon deployment"

### Task 6: Full verification and beta release

**Files:**
- Modify: README.md only if commands or limitations change
- Test: all files under tests/

- [ ] Run the full suite with coverage, Ruff, Bandit, pip-audit, compile checks, JavaScript syntax checks, git diff --check, Alembic checks, and the Docker Compose audit.
- [ ] Start with an empty test database, backfill seven assets, open two independent browser sessions, trade in each, restart the app, and verify identity, balance, history, reset, and isolation.
- [ ] Create Neon roles, apply migrations, configure secrets, deploy a Vercel preview, run health and simulator smoke tests, inspect logs, and only then promote production.
- [ ] Document cold starts, scheduled-collector delays, anonymous-cookie loss, lack of fees/slippage, no real trading, and the three-month boundary.
- [ ] Confirm clean main, passing checks, and a public health endpoint.

