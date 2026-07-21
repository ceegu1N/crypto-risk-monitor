# Publicação com Neon, Render e GitHub Actions

Este roteiro publica a interface sem manter um computador ligado. A divisão de
responsabilidades é:

```text
GitHub Actions -> coleta e avalia alertas
Neon          -> mantém PostgreSQL e histórico
Render        -> serve API e dashboard
```

Nenhuma dessas etapas executa ordens ou acessa conta de corretora. A coleta usa
somente o endpoint público de candles da Binance.

## 1. Preparar o repositório

1. Publique o projeto em um repositório GitHub.
2. Confirme que o workflow `CI` passa na aba **Actions**.
3. Não envie o arquivo `.env`; ele está no `.gitignore`.

O Render foi configurado com `autoDeployTrigger: checksPass`, portanto uma nova
versão só será implantada depois que os checks vinculados passarem.

## 2. Criar o PostgreSQL no Neon

1. Crie um projeto em <https://console.neon.tech/>.
2. Escolha uma região próxima à região `Virginia` usada no `render.yaml`.
3. No painel do projeto, clique em **Connect**.
4. Selecione a conexão **direct**, sem o sufixo `-pooler` no host.
5. Copie a connection string com `sslmode=require` e
   `channel_binding=require`.
6. Troque apenas o início `postgresql://` por `postgresql+psycopg://`.

Exemplo estrutural, sem credenciais reais:

```text
postgresql+psycopg://USUARIO:SENHA@HOST.neon.tech/BANCO?sslmode=require&channel_binding=require
```

Use a conexão direta porque o mesmo endereço executará as migrações Alembic.
O Neon recomenda conexão direta para ferramentas de migração; o volume pequeno
deste projeto não exige um pooler para a aplicação.

## 3. Aplicar a migração inicial

Esta etapa é opcional antes do primeiro deploy, porque o comando do Render já
executa `alembic upgrade head`. Para testar a conexão antecipadamente:

```powershell
$env:DATABASE_URL="postgresql+psycopg://..."
.\.venv\Scripts\python.exe -m alembic upgrade head
```

O comando é idempotente: se o banco já estiver na revisão atual, ele não recria
as tabelas nem apaga dados.

## 4. Criar o serviço no Render

1. Em <https://dashboard.render.com/>, escolha **New > Blueprint**.
2. Conecte o repositório que contém `render.yaml`.
3. Revise o serviço `crypto-risk-monitor`.
4. Preencha `DATABASE_URL` com a URL direta do Neon.
5. Crie uma senha forte para `OPERATOR_PASSWORD`.
6. Aceite a geração automática de `SESSION_SECRET`.
7. Inicie o deploy.

O serviço usa a imagem definida no `Dockerfile`, aplica as migrações e inicia a
aplicação na porta 8000. O Render verifica `/api/health` antes de liberar o
tráfego.

## 5. Configurar a coleta no GitHub

No repositório, acesse **Settings > Secrets and variables > Actions** e crie:

| Secret | Obrigatório | Conteúdo |
|---|---:|---|
| `DATABASE_URL` | sim | mesma URL direta do Neon |
| `DISCORD_WEBHOOK_URL` | não | webhook do canal de alertas |

Depois, em **Actions > Coleta agendada**, execute **Run workflow** uma vez. O
resultado esperado termina com quatro ativos processados e zero erros. A agenda
automática roda aos minutos 17 e 47 de cada hora.

O agendamento do GitHub é periódico, não tempo real, e pode atrasar quando a
plataforma está congestionada. O lock consultivo do PostgreSQL impede que uma
execução sobreposta faça uma segunda coleta simultânea.

## 6. Verificações após publicar

1. Abra `https://SEU-SERVICO.onrender.com/api/health`.
2. Confirme `{"status":"ok","database":"ok"}`.
3. Abra o dashboard e verifique os quatro ativos.
4. Entre como operador e salve uma posição simulada pequena.
5. Confira a execução mais recente na página **Sistema**.
6. Se configurou Discord, reduza temporariamente um limite para provocar um
   alerta controlado e depois restaure o valor.

## Limitações dos planos gratuitos

- O serviço web do Render pode suspender por inatividade; a primeira abertura
  depois disso sofre um cold start.
- O compute do Neon pode suspender quando ocioso e levar alguns segundos para
  reativar.
- O horário do GitHub Actions não é garantia de execução no minuto exato.
- Um worker contínuo gratuito não faz parte desta arquitetura; localmente, o
  coletor contínuo continua disponível no Docker Compose.

Esses comportamentos alteram latência e frequência, mas não a integridade dos
dados: candles são gravados por chave única e a próxima coleta busca o trecho
faltante.

## Segredos por ambiente

Render:

- `DATABASE_URL`;
- `OPERATOR_PASSWORD`;
- `SESSION_SECRET` gerado pelo próprio Render;
- `DISCORD_WEBHOOK_URL`, somente se a web também precisar dele no futuro.

GitHub Actions:

- `DATABASE_URL`;
- `DISCORD_WEBHOOK_URL`, opcional.

Não coloque senhas no `render.yaml`, nos workflows, no README ou em screenshots.

## Referências operacionais

- Render Blueprint: <https://render.com/docs/blueprint-spec>
- Docker no Render: <https://render.com/docs/docker>
- Health checks do Render: <https://render.com/docs/health-checks>
- Python com Neon: <https://neon.com/docs/guides/python>
- Pooling e migrações no Neon: <https://neon.com/docs/connect/connection-pooling>
