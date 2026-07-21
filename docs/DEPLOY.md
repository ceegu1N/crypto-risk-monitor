# Publicação com Vercel, Neon e GitHub Actions

Esta arquitetura mantém a página acessível sem deixar o computador ligado:

```text
Vercel -> FastAPI e interface pública
Neon   -> PostgreSQL compartilhado, carteiras e histórico
GitHub Actions -> migração manual, coleta a cada 15 min e limpeza semanal
Binance -> candles e cotações públicas
```

O sistema é uma simulação educativa. Não executa ordens, não acessa corretoras
e não usa dinheiro real. A versão inicial não simula taxas, spread ou slippage;
isso fica declarado na interface.

## 1. Criar o banco no Neon

1. Crie um projeto em <https://console.neon.tech/>.
2. Use a URL direta para a migração e, se o painel oferecer, uma URL com pooling
   para a aplicação.
3. Troque `postgresql://` por `postgresql+psycopg://` nas URLs usadas pelo
   Python e mantenha `sslmode=require`.

Pela interface SQL do Neon, usando o proprietário do banco, crie dois papéis:

```sql
CREATE ROLE crypto_writer LOGIN PASSWORD 'SENHA_FORTE_DO_COLETOR';
CREATE ROLE crypto_web LOGIN PASSWORD 'SENHA_FORTE_DA_WEB';
```

Não coloque essas senhas no Git. A primeira migração concede os privilégios
necessários aos papéis. O proprietário deve ser usado somente para migrações.

## 2. Migrar o banco

No GitHub, configure em **Settings > Secrets and variables > Actions**:

| Secret | Uso |
|---|---|
| `MIGRATION_DATABASE_URL` | proprietário do banco, somente Alembic |
| `COLLECTOR_DATABASE_URL` | papel `crypto_writer`, coleta e limpeza |

Depois execute manualmente **Actions > Migrar banco > Run workflow**. O banco
precisa estar migrado antes de abrir a aplicação na Vercel.

## 3. Publicar na Vercel

1. Em <https://vercel.com/>, importe o repositório.
2. A Vercel detectará `vercel.json` e `api/index.py`.
3. Configure estas variáveis no ambiente **Production**:

| Variável | Valor |
|---|---|
| `DATABASE_URL` | URL do papel `crypto_web` |
| `SESSION_SECRET` | segredo aleatório longo |
| `SESSION_COOKIE_SECURE` | `true` |
| `OPERATOR_PASSWORD` | senha administrativa forte, se o painel for usado |
| `BINANCE_BASE_URL` | `https://data-api.binance.vision` |
| `RISK_PROFILE` | `moderate` |

4. Faça o deploy e abra `/api/health`. O retorno esperado é:

```json
{"status":"ok","database":"ok"}
```

A Vercel serve a interface e as rotas FastAPI. Ela não roda o coletor contínuo;
isso é intencional, porque a coleta periódica fica no GitHub Actions.

## 4. Configurar a coleta automática

O workflow **Coleta agendada** usa `COLLECTOR_DATABASE_URL` para executar um
ciclo a cada 15 minutos. A primeira execução busca os 90 dias iniciais; as
seguintes buscam apenas o trecho novo. Migrações são executadas separadamente
pelo workflow manual, usando a credencial do proprietário.

O GitHub pode atrasar um agendamento, então “a cada 15 minutos” é uma frequência
alvo, não uma garantia de relógio em tempo real. O lock consultivo do PostgreSQL
impede ciclos sobrepostos.

O workflow **Limpar carteiras inativas** roda semanalmente e remove carteiras
cujo `last_seen_at` está há mais de 90 dias sem atividade. A remoção inclui as
posições e operações associadas.

## 5. Como a carteira anônima funciona

Na primeira visita, a API gera um token aleatório e o envia em cookie HttpOnly.
O banco armazena somente o SHA-256 desse token, nunca o token puro. Enquanto o
cookie permanecer no navegador, o mesmo visitante reencontra a carteira, mesmo
que o computador seja desligado. Limpar cookies, usar outro navegador ou trocar
de dispositivo cria outra carteira.

Compra e venda são operações spot fictícias. A API busca uma cotação pública
atualizada no servidor, bloqueia a carteira durante a transação, valida caixa e
posição, grava o trade e atualiza o saldo em uma única transação PostgreSQL.

## 6. Limitações conhecidas

- a cotação depende da disponibilidade do endpoint público da Binance;
- o histórico só começa a ficar completo depois da primeira carga de 90 dias;
- o agendamento do GitHub não é tempo real;
- a carteira é anônima, não uma conta de usuário recuperável;
- a simulação não representa custos reais de execução;
- a hospedagem gratuita pode impor limites de uso e suspensão por inatividade.

Não publique URLs com senhas, arquivos `.env`, tokens, screenshots de secrets ou
connection strings completas.
