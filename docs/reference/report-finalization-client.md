# Etapa 7E - cliente JavaScript de finalizacao

## Inspecao e limite

Fluxo existente: signaling.js reportUrl preserva filtros da analise; botao atual
chama reservationUI.openReport. waypoint_reservation_ui.js abre dialog e iframe
srcdoc, monta ReportDraft no contexto autorizado da janela principal e conclui
flush antes do POST DOCX. Nada desse comportamento foi alterado. O novo modulo
e carregado no mapa apos WaypointReservations; nao monta controles nem cria
intencoes/requisicoes ao carregar. Nenhum botao ou publicacao automatica.

Contratos existentes (report_finalization_views.py e report_finalization.describe):
- POST /signaling/points/<id>/report-finalizations/ com mesmos filtros GET do DOCX;
  JSON exatamente idempotency_key UUID v4 e expected_revision inteiro >=0.
  Fotos: multipart com esses campos e photos repetido, sem Content-Type manual.
- GET /signaling/report-finalizations/<attempt_uuid>/ sem prova de reserva;
- POST /signaling/report-finalizations/<attempt_uuid>/retry/ com JSON {} ou
  multipart apenas photos. Nao recebe chave, textos, autor ou numero novos.
Todos exigem sessao e permissoes de finalizador; consulta/retry so do solicitante.
Tambem dependem de REPORT_FINALIZATION_ENABLED, inalterado e false por padrao.
Leitura da biblioteca nao concede finalizacao.

Resposta: 201/200 FINALIZED identifica attempt_id, report_id, version, number,
issued_at e finalized_at. 202 PROCESSING/STORING com success:false e normal;
409 FAILED/INTERRUPTED requer retry explicito. Erros podem conter attempt com
estado recuperavel. 401/403 autenticacao/permissoes/CSRF, 428 prova ausente,
409 reserva/revisao/origem/idempotencia, 503 indisponibilidade/flag/falha operacional.

## API do modulo (sem interface)

ReportFinalization.createIntent recebe manager existente, pointId, url local de
finalizacao fornecida pelo servidor (incluindo filtros exatos), expectedRevision,
photos opcionais, attemptUrl(id, retry), e opcionalmente idempotencyKey para
restaurar uma intencao. Usa UUID seguro do modulo de reservas se nao fornecida.
fetch pode ser injetado para testes. Nao aceita URLs externas.

Metodos: submit(), check(), retry(), recovery(), snapshot(). submit simultaneos
compartilham Promise. Uma intencao congela ponto, URL/filtros, revisao e lista de
File; replay conserva chave e corpo. Resultado confirmado FINALIZED e reutilizado
sem outro POST. check exige ID conhecido; sem ID, devolve unknown sem rede.
retry so existe para FAILED/INTERRUPTED conhecidos e exige chamada explicita.
Colisao de chave nunca habilita retry da tentativa alheia retornada no erro.
Nenhum timer, polling, acquire, localStorage ou heartbeat e criado pelo cliente.

Resultados estruturados: published, processing, retry_required, forbidden,
conflict, reservation_error, unavailable, error, uncertain, superseded ou unknown;
incluem recovery com chave e ID conhecido. Falha de rede, timeout, resposta
invalida ou interacao substituida nunca apagam a chave nem criam outra intencao.
Requisicoes de status possuem timeout (padrao 20s); POST usa timeout ja existente
no gerenciador de reservas. Timeout nao prova que o servidor interrompeu trabalho.

## Adaptacao minima do transporte

manager.perform recebe quinto argumento opcional {consumeErrors:true}. O padrao
continua intacto. Necessario porque o parser anterior rejeitava 202 success:false
e todos os 409 antes do consumer, tratando conflito de negocio como perda de
reserva. Cliente consome o envelope e devolve erros de reserva ao proprio manager
como ReservationError, preservando sua invalidacao. Conflitos de origem/revisao/
chave e indisponibilidade nao invalidam artificialmente a reserva. CSRF atual,
prova, sessao same-origin, renovacao normal, busy/finally e descarte de resposta
apos troca de interacao continuam sob o mesmo manager. Tokens nao sao expostos.

## Conexoes obrigatorias na 7F

- Obter URLs de reverse/data attributes no servidor, sem inventar rotas; conservar
  filtros exatos do formulario. Nao foi adicionado endpoint ou data attribute agora.
- Confirmacao explicita antes de criar intencao e chamar submit; nao ligar a
  renovacao, polling, abertura do waypoint ou geracao DOCX.
- Flush autosave, confirmar ausencia de pendencias/conflito e obter revisao salva.
  O mount atual do draft ainda nao expoe getter publico da revisao; essa adaptacao
  pequena fica para a integracao 7F, sem ler atributos internos.
- Congelar fotos originais na ordem, impedir mudanca de payload na mesma chave.
- Manter a renovacao normal enquanto aguarda; nao renovar pelo backend. O manager
  mantem busy e heartbeat durante perform. Perda real impede publicacao no servidor.
- Reter uma unica intencao por operacao para cliques/abas conforme UX aprovada.
  O modulo deduplica uma instancia; instancias/abas com chaves diferentes podem
  criar relatorios distintos. Backend so garante deduplicacao pela mesma chave.
- Persistencia apos reload nao e automatica: 7F deve guardar chave/ID e contexto
  nao secreto de forma vinculada ao usuario/waypoint e restaurar a MESMA intencao.
  Nao persistir tokens/sessao nem fotos no armazenamento do navegador. Sem ID
  conhecido, replay explicito usa mesma chave, mesmos filtros/revisao e originais;
  manager pode exigir recuperacao normal ou nova aquisicao legitima antes do POST.
- Consulta de tentativa e autorizacao de finalizador, nao da biblioteca. Nao
  exibir report_id/number como publicacao ate kind published.
- Ao fechar/trocar waypoint, ignorar resultado antigo na interface e reter chave
  para recuperacao. Modulo nao conhece ciclo do DOM; manager faz o fencing de POST.
- Operacao sincrona so homologacao: um worker Gunicorn bloquearia outras requisicoes,
  inclusive heartbeat. Nao habilitar publicacao em producao sem resolver execucao.

## Validacao local

```powershell
node --test static/js/report_finalization.test.js static/js/waypoint_reservations.test.js static/js/report_draft.test.js static/js/waypoint_reservation_ui.test.js static/js/report_characterization.test.js
python -B manage.py test signaling.test_report_finalization signaling.test_report_read_access signaling.test_authorization signaling.test_report_download --verbosity 1
python -B manage.py check
git diff --check
```

PostgreSQL: autenticar com scripts/local-postgres-env.ps1 no PowerShell, confirmar
host local e test_analise_dev descartavel antes do comando abaixo. Sem --keepdb
ou --noinput; nao executar migrate em analise_dev.

```powershell
python -B manage.py test signaling.test_report_finalization_postgresql signaling.test_report_draft_concurrency signaling.test_reservation_concurrency signaling.test_reservations.PostgreSQLReservationContractTests --verbosity 2
```

Credenciais indisponiveis ao Codex: validacao real PostgreSQL permanece pendente.
Nao ha homologacao da interface 7F nesta etapa; nao executar deploy.

## Resultado da validacao Codex

125 testes JavaScript aprovados (16 novos do cliente e regressoes de reservas,
rascunhos, modal e formulario); 79 testes Django aprovados em SQLite temporario.
Check, sintaxe JavaScript e git diff --check aprovados. PostgreSQL pendente por
ausencia de POSTGRES_PASSWORD no processo; nenhuma migration em banco existente.
