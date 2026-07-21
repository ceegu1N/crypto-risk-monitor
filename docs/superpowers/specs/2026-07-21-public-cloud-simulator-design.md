# Simulador Publico De Portfolio Cripto

## Objetivo

Transformar o monitor atual em uma demonstracao publica na qual cada visitante
recebe uma carteira anonima e independente com R$ 10.000 ficticios. O usuario
pode comprar e vender ativos pelos precos de mercado, acompanhar resultado e
risco e retornar posteriormente ao mesmo portfolio sem criar uma conta.

O produto continua educacional: nao executa ordens, nao acessa corretoras, nao
aceita depositos e nao recomenda investimentos.

## Escopo Da Primeira Versao Publica

- negociacao simulada apenas no mercado spot, sem alavancagem ou venda a
  descoberto;
- saldo inicial de R$ 10.000 por carteira;
- pares BTC/BRL, ETH/BRL, SOL/BRL, USDT/BRL, ADA/BRL, PEPE/BRL e NEAR/BRL;
- compra por valor em reais e venda por quantidade ou total da posicao;
- saldo disponivel, patrimonio, preco medio, resultado realizado e nao
  realizado, concentracao e historico de operacoes;
- periodos graficos de 1 dia, 7 dias, 1 mes e 3 meses;
- botao para reiniciar a simulacao;
- nenhuma taxa, spread ou slippage na primeira versao, com essa simplificacao
  declarada na interface.

Nao entram nesta etapa cadastro, recuperacao entre dispositivos, ranking,
gamificacao, ativos escolhidos livremente, derivativos ou integracao com conta
real.

## Identidade Anonima E Retencao

No primeiro acesso, o backend cria uma carteira e devolve um token aleatorio em
cookie persistente. O cookie usa `HttpOnly`, `Secure` na nuvem, `SameSite=Lax` e
validade deslizante de 90 dias. O banco guarda apenas o hash do token.

Cada requisicao identifica a carteira pelo cookie. O saldo, as posicoes e as
operacoes permanecem no PostgreSQL, nunca no cookie ou no `localStorage`. Ao
apagar os cookies, mudar de navegador ou trocar de aparelho, o visitante recebe
uma nova carteira e nao consegue recuperar a anterior.

Carteiras sem atividade por mais de 90 dias e seus dados dependentes sao
removidas por uma tarefa agendada. Nenhum dado pessoal e solicitado.

## Modelo De Dados E Operacoes

O banco recebe entidades para carteira anonima e operacao simulada. Cada posicao
fica vinculada a uma carteira, eliminando a carteira global existente. Uma
operacao de compra ou venda ocorre em uma unica transacao do PostgreSQL:

1. bloquear a carteira durante a alteracao;
2. validar saldo, quantidade, ativo e limites numericos;
3. obter no servidor uma cotacao publica recente da Binance;
4. registrar a operacao com preco e horario;
5. atualizar saldo, quantidade e custo medio;
6. confirmar tudo em conjunto ou desfazer tudo em caso de erro.

Compras acima do saldo e vendas acima da posicao sao rejeitadas. Se a Binance
nao fornecer uma cotacao valida, a operacao nao e executada. O historico de
mercado e compartilhado; somente carteira, posicoes e operacoes sao individuais.

## Dados De Mercado E Graficos

Os candles continuam tendo granularidade de 15 minutos e somente candles
encerrados sao persistidos. A coleta em nuvem roda pelo GitHub Actions a cada 15
minutos, sujeita aos atrasos normais do agendador.

Um backfill idempotente preenche ate 90 dias de historico para os sete pares. O
processo pagina a API da Binance, registra progresso e pode ser repetido sem
duplicar candles.

Para proteger API, banco e navegador, os graficos recebem no maximo algumas
centenas de pontos:

| Periodo | Agregacao esperada |
|---|---|
| 1D | candles de 15 minutos |
| 7D | blocos de 1 hora |
| 1M | blocos de 4 horas |
| 3M | blocos de 12 horas |

Cada bloco conserva abertura, maxima, minima, fechamento e volume. A agregacao
ocorre no servidor; o navegador nao recebe todos os registros brutos.

## Arquitetura De Nuvem

```text
Binance publica -> GitHub Actions -> Neon PostgreSQL
                                         ^
Navegador -> Vercel FastAPI + dashboard -+
```

- **Vercel:** publica FastAPI, arquivos estaticos e previews por alteracao;
- **Neon:** persiste mercado, carteiras, posicoes, operacoes e alertas;
- **GitHub Actions:** executa migracoes controladas, coleta incremental,
  backfill manual e limpeza de carteiras expiradas;
- **Docker Compose:** permanece como ambiente local reproduzivel e nao participa
  da execucao da Vercel.

A aplicacao web usa a conexao com pool do Neon. Migracoes e coleta usam conexoes
diretas e papeis com privilegios separados. Segredos ficam apenas nas variaveis
da Vercel e nos GitHub Secrets.

## Experiencia Publica E Administracao

O visitante pode consultar mercado, operar a propria carteira, visualizar risco
e reiniciar a simulacao sem senha. Regras globais, transicoes administrativas de
alertas e diagnosticos sensiveis continuam protegidos pelo acesso de operador ou
deixam de aparecer na navegacao publica.

A interface deve explicar de forma curta que o saldo e ficticio, que os precos
vem da Binance e que a simulacao inicial nao considera taxas ou slippage.

## Protecoes

- token anonimo imprevisivel e armazenado como hash;
- cookie seguro e inacessivel a JavaScript;
- validacao de valores no backend com `Decimal`;
- transacoes e bloqueio de linha para evitar saldo negativo em cliques
  simultaneos;
- limites de tamanho e frequencia para operacoes;
- consultas parametrizadas pelo SQLAlchemy;
- credenciais de banco com menor privilegio;
- nenhum segredo ou token real no repositorio;
- limpeza de sessoes expiradas e registros dependentes.

## Testes E Criterios De Aceitacao

- visitante novo recebe exatamente R$ 10.000;
- o mesmo cookie recupera a mesma carteira apos reinicio da aplicacao;
- cookies diferentes nao acessam dados um do outro;
- compra reduz saldo e cria ou atualiza posicao corretamente;
- venda atualiza saldo, quantidade e resultado realizado;
- operacoes invalidas nao alteram parcialmente o banco;
- reinicio restaura saldo e remove posicoes e historico daquela carteira;
- os sete pares sao coletados sem duplicacao;
- os quatro periodos retornam pontos ordenados e agregados corretamente;
- carteiras inativas por mais de 90 dias sao removidas;
- testes, cobertura minima, lint, auditorias e migracoes continuam aprovados;
- dashboard e fluxos de compra e venda sao verificados em desktop e celular;
- preview da Vercel e banco Neon passam por uma verificacao funcional antes de
  promover a versao publica.

## Estrategias Rejeitadas

- guardar saldo no `localStorage`: facil de adulterar e sem validacao central;
- guardar toda a carteira no cookie: limite de tamanho e exposicao desnecessaria;
- usar uma carteira global: visitantes alterariam os mesmos dados;
- usar Vercel Cron para coleta frequente: o plano Hobby limita a frequencia;
- enviar 90 dias de candles de 15 minutos ao navegador: carga e visualizacao
  ruins;
- adicionar cadastro nesta etapa: amplia seguranca, suporte e escopo sem ser
  necessario para a demonstracao.
