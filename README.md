# Crypto Market & Portfolio Risk Monitor

Aplicação educacional para acompanhar risco de mercado e testar operações em
uma carteira simulada de R$ 10.000 nos pares BTC/BRL, ETH/BRL, SOL/BRL,
USDT/BRL, ADA/BRL, PEPE/BRL e NEAR/BRL.

> Não executa ordens, não acessa corretoras e não constitui recomendação financeira.

## Demonstração

A aplicação está disponível em [crypto-risk-monitor-mu.vercel.app](https://crypto-risk-monitor-mu.vercel.app).

## O que o projeto entrega

- candles públicos da Binance coletados a cada 15 minutos e preservados no PostgreSQL;
- métricas explicáveis de retorno, volatilidade, drawdown, volume financeiro em BRL e atraso;
- carteira anônima persistente por cookie, com R$ 10.000 fictícios;
- compra, venda, reset e histórico de operações spot sem dinheiro real;
- gráficos de 24h, 7d, 1M e 3M, agregados no servidor para permanecerem leves;
- alertas de mercado com regras configuráveis e histórico auditável;
- interface responsiva em FastAPI, preparada para Vercel;
- coleta, migração e limpeza agendadas por GitHub Actions.

## Arquitetura

```text
Binance pública -> coletor Python -> PostgreSQL -> métricas e alertas
                                      -> API FastAPI -> interface responsiva
Vercel           -> serve API e interface
GitHub Actions   -> migração manual, coleta a cada 15 min, limpeza semanal
```

O PostgreSQL é a fonte compartilhada de estado: mantém candles, snapshots,
carteiras e operações mesmo quando a aplicação é reiniciada. A carteira de cada
visitante é identificada por um token aleatório em cookie; somente o hash desse
token é armazenado. Limpar os cookies ou trocar de navegador cria outra carteira.
A retenção da carteira é deslizante e dura 90 dias desde o último acesso.

Quando uma correção de interpretação de dados é necessária, o workflow manual
`Corrigir volume histórico` rebaixa os candles encerrados da janela escolhida e
faz upsert no PostgreSQL. Neste projeto, ele é usado uma vez para substituir o
volume da moeda-base pelo volume financeiro da moeda de cotação (BRL), sem
alterar preços, operações simuladas ou carteiras.

A cotação usada em uma operação simulada é buscada no endpoint público da
Binance no momento da operação. A versão inicial não simula taxas, spread ou
slippage, e isso é informado ao usuário.

## Execução local

Pré-requisitos: Python 3.12 e PostgreSQL acessível.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --requirement requirements-dev.lock
Copy-Item .env.example .env
powershell -ExecutionPolicy Bypass -File .\run_local.ps1
```

Abra `http://127.0.0.1:8000`. Para usar Docker:

```powershell
Copy-Item .env.example .env
docker compose up --build -d
docker compose ps
```

O Compose inicia PostgreSQL, migra o banco e libera o coletor e o servidor web.

## Testes e qualidade

```powershell
$env:TEST_DATABASE_URL="postgresql+psycopg://postgres:postgres@localhost:55432/crypto_risk_test"
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check .
```

Na última verificação local, **106 testes passaram**. O projeto também mantém
locks de dependências, migrations Alembic, checks de integridade no banco,
permissões separadas para web/coletor e imagem Docker não-root.

## Publicação

O entrypoint `api/index.py` e o `vercel.json` preparam a aplicação para Vercel.
O Neon fornece o PostgreSQL gerenciado. O passo a passo de secrets, migração,
deploy, coleta e limpeza está em [docs/DEPLOY.md](docs/DEPLOY.md).

## Fonte de dados

Os candles e cotações vêm do endpoint público oficial
[`data-api.binance.vision`](https://data-api.binance.vision). Somente candles
encerrados entram no histórico.
