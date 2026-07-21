# Crypto Market & Portfolio Risk Monitor

Aplicação para acompanhar risco de mercado e de um portfólio simulado nos pares
BTC/BRL, ETH/BRL, SOL/BRL e USDT/BRL. O projeto coleta candles públicos da
Binance, preserva o histórico no PostgreSQL, aplica regras explicáveis e mantém
o ciclo de vida dos alertas em uma interface responsiva.

> Ferramenta educacional e de monitoramento. Não executa ordens, não recomenda
> investimentos e não substitui análise financeira ou de compliance.

![Visão geral do dashboard](docs/assets/dashboard-overview.png)

## O que já funciona

- coleta incremental de candles concluídos de 15 minutos;
- persistência idempotente e snapshots de risco no PostgreSQL;
- retorno, volatilidade realizada, drawdown, volume e atraso dos dados;
- portfólio simulado com exposição, concentração e P/L opcional;
- regras configuráveis e histórico auditável de alertas;
- perfis conservador, moderado, agressivo e personalizado, com restauração;
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

Chart.js e Lucide são servidos localmente em versões fixadas. O dashboard não
depende de CDNs no navegador, e as respectivas licenças acompanham os arquivos
em `app/web/static/vendor/`.

## Execução local

Pré-requisitos: Python 3.12 e uma instância PostgreSQL acessível.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --requirement requirements-dev.lock
Copy-Item .env.example .env
```

Edite `DATABASE_URL`, `OPERATOR_PASSWORD` e `SESSION_SECRET` no `.env`. Esse
modo usa uma conexão única por simplicidade de desenvolvimento. Em seguida:

```powershell
powershell -ExecutionPolicy Bypass -File .\run_local.ps1
```

Abra `http://127.0.0.1:8000`. Para encerrar:

```powershell
powershell -ExecutionPolicy Bypass -File .\stop_local.ps1
```

Os logs e PIDs ficam em `.runtime/`, que não é versionado.
A documentação interativa da API fica em `http://127.0.0.1:8000/docs`.

As dependências de produção e desenvolvimento estão congeladas em
`requirements.lock` e `requirements-dev.lock`. O `pyproject.toml` continua sendo
a fonte das faixas aceitas; os arquivos de lock registram a resolução exata usada
no Docker e no CI.

## Execução com Docker

O Compose inicia PostgreSQL, aplica a migração uma única vez e só então libera o
coletor e a aplicação web:

```powershell
Copy-Item .env.example .env
docker compose up --build -d
docker compose ps
```

Troque no `.env` as três senhas de banco (`POSTGRES_ADMIN_PASSWORD`,
`WRITER_DB_PASSWORD` e `WEB_DB_PASSWORD`), a senha do operador e o segredo de
sessão antes de usar fora da sua máquina. O Compose separa o usuário
administrativo das credenciais limitadas do coletor e da aplicação web. O
dashboard ficará em
`http://127.0.0.1:8000` e o banco em `127.0.0.1:5433`.

Quando `SESSION_COOKIE_SECURE=true`, a aplicação recusa a senha e o segredo de
exemplo. Assim, uma publicação HTTPS mal configurada falha na inicialização em
vez de ficar disponível com credenciais previsíveis.

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

Na auditoria final desta versão, 93 testes passaram. Ruff e Bandit não
registraram achados, e o `pip-audit` não encontrou vulnerabilidades conhecidas
nos dois arquivos de lock. A imagem final não-root, baseada em Python 3.12 e
Alpine 3.24, também ficou sem vulnerabilidades conhecidas no Docker Scout. O
Compose foi reconstruído com banco vazio: coletou os quatro pares, manteve 2.688
candles únicos após uma coleta repetida e preservou o histórico depois do
reinício. As seis áreas do dashboard foram conferidas em 1440×900, 1024×768 e
390×844 sem erros de console ou sobreposição horizontal.

Alterações em posições, perfis e limites aparecem imediatamente na interface.
Os alertas correspondentes são reavaliados pelo coletor no ciclo seguinte, para
que todas as condições permaneçam associadas a uma execução auditável.

## Fonte dos dados

Os candles são consultados no endpoint público oficial
`https://data-api.binance.vision`. Somente candles já encerrados são persistidos;
uma janela ainda em formação não entra nas métricas. O histórico inicial padrão
é de sete dias e as atualizações posteriores são incrementais.

## Publicação

O repositório inclui `render.yaml` para a interface, um workflow agendado para a
coleta e instruções para PostgreSQL gerenciado no Neon. Nenhuma conta ou recurso
é criado automaticamente. O procedimento completo, incluindo segredos e
limitações dos planos gratuitos, está em [docs/DEPLOY.md](docs/DEPLOY.md).
