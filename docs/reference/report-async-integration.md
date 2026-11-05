# Integração controlada HTTP / despachante / lançador — 4C.4

Implementação local, desabilitada por padrão. Nenhum serviço é instalado. Os
procedimentos abaixo são para homologação futura autorizada, não para produção.

## Fluxo e autoridades

1. POST `points/<id>/report-finalizations/` verifica sessão, permissões, CSRF,
   reserva, revisão, fotos e formulário. Com a nova flag, chama `admit()` sem
   renderizar DOCX/PDF. O commit preserva snapshot, originais privados, número,
   chave/fingerprint e slot global. Nenhuma chamada ao lançador ocorre no HTTP.
2. Retorna 202 com accepted, attempt_id, state, status_url e Location. O success
   existente continua significando FINALIZED, não admissão. Busy é 409 sem fila;
   configuração incompleta é 503. publication_state_unknown indica possível commit
   ambíguo: reutilizar a chave em vez de criar outra intenção após timeout.
3. GET `report-finalizations/<uuid>/` exige permissões e o próprio solicitante,
   inclusive para staff. Dispensa reserva ativa; usa no-store e não expõe snapshot,
   execution_id, identidade, recibo ou caminhos. Acrescenta publication_phase e
   requires_reconciliation. FINALIZED não atesta término físico do cgroup.
4. O comando separado analise_dispatch lê somente report_dispatch_candidate().
   Não usa ORM, snapshot, storage ou API systemd no caminho ativo.
5. report_dispatch_prepare() usa o mesmo advisory lock e lock do slot, revalidando
   proprietário/execution_id, ADMITTED, barreira/geração, contrato v1, release
   aprovada e ausência de derivados/execuções concorrentes. Prepara identidade,
   ReportLaunch REQUESTED e ReportDispatchDelivery atomicamente, com evento
   DISPATCH_DELIVERY_PREPARED. Não consome autorização systemd.
6. Apenas retorno fresco, depois do commit confirmado, permite UMA entrega
   SOCK_SEQPACKET ao socket fixo. O cliente autentica root por SO_PEERCRED e envia
   somente protocolo, operação e UUIDs. O lançador autentica analise_dispatch por
   mensagem e valida catálogo root, manifesto, bundle, host/boot e intenção.
7. Só o lançador consome autorização e persiste recibo/UNCERTAIN antes da chamada
   ao manager. O executor analise_app valida identidade observada e, para entregas
   ativas, o recibo correspondente antes de rotacionar execution_id. Confirmação de
   FINALIZED e liberação do slot continuam transacionais e protegidas por fencing,
   independentemente de sessão ou reserva ativa.

O diagnóstico diagnose_report_dispatch --dry-run continua somente leitura e agora
reconhece entrega persistida como incerta. Usa credenciais próprias, não as mínimas
do despachante ativo; seu ORM diagnóstico não foi reutilizado para conceder autoridade.

## Incerteza e limites conservadores

ReportDispatchDelivery é append-only, OneToOne com o lançamento. Seu UUID é a chave
da mensagem e do recibo. Dois despachantes não obtêm duas entregas frescas. Timeout,
recusa, erro de conexão, resposta perdida, queda antes do envio ou commit de resultado
desconhecido NÃO permitem reenvio automático, mesmo com launch REQUESTED e sem recibo.
A próxima chamada retorna DELIVERY_UNCERTAIN. Não existe API para limpar/rearmar.

Uma publicação que nunca iniciou pode ficar bloqueada: ausência de resposta não
comprova ausência de início. Um job observado permanece UNCERTAIN; a invocação fica
persistida no binding do executor. Não foi adicionada prova de término.

A barreira pode fechar depois da preparação: o lançador revalida geração e recusa
o início. Reabrir a barreira não rearma a entrega. DEPLOYING permanece recusado
enquanto houver admissão/identidade/lançamento sem prova de término. Mesmo após
FINALIZED e slot vazio, a regra atual bloqueia nova intenção distinta/deploy
enquanto existir a identidade. Esta etapa não flexibiliza essa regra e não
implementa recuperação; operação contínua depende da futura prova de encerramento.

## Configuração futura

HTTP requer REPORT_FINALIZATION_ENABLED, REPORT_ADMISSION_ENABLED,
REPORT_EXECUTOR_ENABLED, REPORT_SYSTEMD_SUPERVISION_ENABLED e a nova
REPORT_ASYNC_PUBLICATION_ENABLED. Os defaults permanecem false. Não os habilitar
em produção nesta etapa. Com gates novos desligados, o fluxo síncrono permanece.
O serviço legado recusa novas mutações quando admissão ou integração assíncrona
está habilitada, além de checar slot/barreira/histórico. Retry assíncrono é replay,
sem fotos substitutas e sem reiniciar execução falha/incerta.

Executar futuramente como analise_dispatch com ambiente separado do HTTP:

```text
python -B manage.py dispatch_report_publication --settings=config.report_dispatch_settings
```

Requer REPORT_DISPATCH_ENABLED=true, REPORT_DISPATCH_DSN do papel restrito e
REPORT_EXECUTOR_RELEASE_ID da release instalada. Ausentes/false por padrão.
BASE_DIR deriva da release instalada; o backend ORM desse perfil é dummy. Não lê
credenciais PostgreSQL/SECRET_KEY HTTP nem storage. Não colocar DSN em argumentos.
O comando exige UID/GID analise_dispatch sem grupos suplementares alheios, distinto
de analise_app e fora de seus grupos. Não provisiona contas, serviços ou loop.
É one-shot, sem fila: supervisão futura poderá repetir descoberta, nunca reenviar
uma entrega persistida. Saída JSON contém outcomes/launch_id, sem dados privados.

Migration nova: 0021_dispatch_delivery_api, após 0020. Cria tabela e duas funções
SECURITY DEFINER, search_path pg_catalog, EXECUTE revogado de PUBLIC. Não cria
papéis/grants. Aplicação futura exige autorização separada e revisão de migrate
--plan no banco correto. deploy/report-launcher-grants.sql.example descreve dono
NOLOGIN, dispatcher com EXECUTE apenas nas duas funções e projeção aprovada, sem
tabelas brutas; launcher runtime mantém as quatro funções anteriores. O guard
recusa administrador, memberships, CREATE no schema, leitura/escrita de tabelas
públicas e autoridade sobre funções do lançador. HTTP não pode ser dono/admin ou
membro desses papéis. Instalação de contas, pg_hba e DSNs segregados é separada.
O papel HTTP precisa dos direitos normais da admissão, mas não pode receber DML
em releases aprovadas, identidades, lançamentos, entregas, recibos, eventos ou
barreira. Revisar esses grants antes de qualquer ativação; não migrar como dono
HTTP e presumir que as fronteiras SQL ficaram protegidas automaticamente.

O root informado à função de preparação é metadado, nunca autoridade para executar
um caminho. O catálogo root do lançador continua autorizando raiz, executável,
ambiente e inventário. Não existe entrada de caminho ou argumento systemd pelo
HTTP. Preservar storage analise_app 0700/0600, sem acesso ao dispatcher. O ambiente
do executor mantém sua allowlist atual, sem flags HTTP/dispatcher ou DSN dispatcher.
Provisionamento e CD devem seguir também report-launcher.md: releases imutáveis,
barreira de deploy, retenção de releases referenciadas e nenhuma alteração em uso.

## Testes e homologação

Com cluster e banco PostgreSQL exclusivamente descartáveis:

```text
python manage.py test signaling.test_report_async_postgresql signaling.test_report_active_dispatcher signaling.test_report_admission_postgresql signaling.test_report_operations_postgresql signaling.test_report_dispatcher_postgresql signaling.test_report_launcher_postgresql signaling.test_report_supervision_postgresql signaling.test_report_finalization_postgresql --noinput
```

Cobrem autorização/CSRF/proprietário, reserva/revisão, idempotência, concorrência
admissão/despacho/deploy, papéis SQL reais, entrega perdida, banco/commit ambíguo,
fencing, confirmação/liberação atômicas e regressão legada. Catálogo/manager/host e
artefatos finais sintéticos não são homologação operacional. Nenhuma unidade,
conversão ou publicação real é executada.

Homologação futura isolada deve comprovar contas reais, recusa como analise_app,
socket, DSNs e grants efetivos, ausência de acesso ao storage, catálogo/release
imutáveis, HTTP 202/status privado, unidade única, execução fora do HTTP, startup
real, cgroup/descendentes, recursos e artefatos. Ensaiar queda antes/depois da
entrega, ACK perdido, falha de DB e fechamento da barreira, sem unidades duplicadas
ou recuperação por timeout. Registrar evidências; mocks não aprovam esses itens.

Não reverter a migration nem apagar entregas/recibos para desbloquear. Desabilitar
novas admissões não revoga intenção admitida. Drenar e manter release executora
disponível antes de trocar código. Prova de término/recuperação permanece pendente.

## Validação local realizada

Na revisão final desta etapa: 154 testes Python das suítes acima passaram, sem
skips, com `--parallel 2` em bancos clonados de um cluster PostgreSQL descartável.
O teste específico dos grants mínimos também passou sem conceder UPDATE sobre a
release aprovada ao dono da função. Os 15 testes portáteis de report_launcher e os
43 testes JavaScript de report_finalization/report_publication_flow passaram.
manage.py check, makemigrations --check --dry-run e git diff --check passaram.
O perfil dedicado carregou e recusou o comando com dispatch_disabled por padrão.
As migrations foram aplicadas somente nos bancos temporários de testes.

Os quatro testes Unix do lançador têm aprovação anterior informada pelo usuário
no GitHub Actions; não foram reexecutados no Windows nesta etapa. O novo caminho
ativo HTTP/dispatcher/socket/systemd ainda precisa da homologação integrada descrita
acima. Nenhuma VM, flag operacional, CD, serviço ou permissão do storage foi alterado.
