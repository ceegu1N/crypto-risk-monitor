# Crypto Market & Portfolio Risk Monitor

Aplicação para acompanhar risco de mercado e de um portfólio simulado nos pares
BTC/BRL, ETH/BRL, SOL/BRL e USDT/BRL. O projeto coleta candles públicos da
Binance, preserva o histórico no PostgreSQL, aplica regras explicáveis e mantém
o ciclo de vida dos alertas em uma interface responsiva.

> Ferramenta educacional e de monitoramento. Não executa ordens, não recomenda
> investimentos e não substitui análise financeira ou de compliance.

## O que já funciona

- coleta incremental de candles concluídos de 15 minutos;
- persistência idempotente e snapshots de risco no PostgreSQL;
- retorno, volatilidade realizada, drawdown, volume e atraso dos dados;
- portfólio simulado com exposição, concentração e P/L opcional;
- regras configuráveis e histórico auditável de alertas;
- notificação opcional por Discord;
- API FastAPI e dashboard para desktop e celular;
- sessão protegida para alterações de regras e posições.

## Arquitetura

```text
Binance pública -> coletor Python -> PostgreSQL -> serviços de risco
                                             -> API FastAPI -> dashboard
                                             -> alertas -> Discord opcional
```

Python é responsável pela integração e pelos cálculos. O PostgreSQL mantém o
estado compartilhado entre o coletor e a aplicação web, aplica restrições de
integridade e permite consultar o histórico sem depender da memória de um único
processo.

## Execução local

Pré-requisitos: Python 3.12 e uma instância PostgreSQL acessível.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

Edite `DATABASE_URL`, `OPERATOR_PASSWORD` e `SESSION_SECRET` no `.env`. Em
seguida:

```powershell
powershell -ExecutionPolicy Bypass -File .\run_local.ps1
```

Abra `http://127.0.0.1:8000`. Para encerrar:

```powershell
powershell -ExecutionPolicy Bypass -File .\stop_local.ps1
```

Os logs e PIDs ficam em `.runtime/`, que não é versionado.

## Execução com Docker

O Compose inicia PostgreSQL, aplica a migração uma única vez e só então libera o
coletor e a aplicação web:

```powershell
Copy-Item .env.example .env
docker compose up --build -d
docker compose ps
```

Troque no `.env` as senhas de banco, a senha do operador e o segredo de sessão
antes de usar fora da sua máquina. O dashboard ficará em
`http://127.0.0.1:8000` e o banco em `127.0.0.1:5433`.

```powershell
# Acompanhar a coleta
docker compose logs -f collector

# Encerrar sem apagar o histórico
docker compose down

# Encerrar e remover também o volume do PostgreSQL
docker compose down -v
```

O último comando apaga os dados locais e deve ser usado apenas quando a intenção
for reconstruir o ambiente do zero.

## Comandos individuais

Eles são úteis para entender e diagnosticar cada etapa:

```powershell
# Estrutura e dados de referência
.\.venv\Scripts\python.exe -m alembic upgrade head

# Um ciclo de coleta
.\.venv\Scripts\python.exe -m app.collector --once

# Coletor contínuo
.\.venv\Scripts\python.exe -m app.collector

# Aplicação web
.\.venv\Scripts\python.exe -m uvicorn app.main:create_app --factory --reload
```

## Testes

Os testes de integração exigem um PostgreSQL separado definido em
`TEST_DATABASE_URL`.

```powershell
$env:TEST_DATABASE_URL="postgresql+psycopg://postgres:postgres@localhost:55432/crypto_risk_test"
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check .
```

## Fonte dos dados

Os candles são consultados no endpoint público oficial
`https://data-api.binance.vision`. Somente candles já encerrados são persistidos;
uma janela ainda em formação não entra nas métricas. O histórico inicial padrão
é de sete dias e as atualizações posteriores são incrementais.
