# Admissão persistente de relatórios — etapa 1

Diagnóstico somente leitura e alternativas para recuperação segura:
[report-recovery.md](report-recovery.md).

## Escopo e contrato

`signaling.report_admission.admit` é um serviço **interno**, sem rota HTTP. A etapa 2
adicionou um [executor manual independente](report-executor.md), sem integração HTTP.
`REPORT_ADMISSION_ENABLED=false` por padrão. Não habilitar em produção
nesta etapa. A flag existente `REPORT_FINALIZATION_ENABLED` não foi habilitada.

O serviço recebe `point_id`, identidade/credenciais da reserva, `user_id`, chave
UUID v4, revisão esperada, parâmetros dos filtros, análise individual e fotos
preparadas por `report_snapshots.prepare_photos` (metadados e bytes). Valida sessão,
permissões, titularidade, reserva, revisão, formulário, análise e fotos. Reutiliza
`report_finalization.prepare_intention`, snapshots, contador anual e artefatos.

Retorna `ReportFinalizationAttempt` em `ADMITTED`, com `admitted_at` preenchido e
`deadline=NULL`. Esse retorno significa que snapshot, originais e titularidade
global foram confirmados no banco. Não gera DOCX/PDF nem inicia subprocessos.
Não guarda request, cookies, provas da reserva ou uploads abertos na intenção.

O fingerprint mantém a semântica legada: ponto, revisão, parâmetros da query e
metadados das fotos. A análise não compõe o fingerprint: repetir uma chave recupera
a intenção original, não substitui sua análise pela sessão atual. Outra intenção
exige outra chave. Replays conhecidos revalidam usuário/permissões, mas não exigem
reserva/análise atuais e são permitidos com o slot ocupado. Chave conflitante
retorna `idempotency_key_conflict`; chave tombstonada mantém `report_deleted`.

## Exclusividade e transações

`ReportPublicationSlot` tem chave primária restrita a 1. Constraints exigem que
tentativa e `execution_id` estejam ambos preenchidos ou ambos vazios; a FK PROTECT
impede excluir sua tentativa enquanto ela ocupa o slot. Não é um lease.

`coordination()` usa `pg_try_advisory_xact_lock` e lock NOWAIT do singleton. A
segunda intenção retorna `publication_busy` (409), sem número, tentativa ou arquivo.
Uma chave ainda não confirmada por outra transação pode receber busy; repetir a
mesma chave depois do commit recupera o resultado. Não há espera/fila para admissão.
O advisory lock serializa a transação; o singleton preserva a ocupação após commit,
reinício e perda da conexão. **Nenhum deadline libera o slot.**

Ordem: coordenação → slot → ponto → reserva → rascunho → contador. Não existe
transação de conversão. A transação de admissão cobre validação/captura e escrita
local limitada dos originais (até os limites existentes de fotos), verificação e
registro de artefatos; assim não há tentativa ADMITTED com entradas incompletas.
O mutex global é não bloqueante, mas espera por locks de ponto/contador e I/O local
ainda pode prolongar a primeira admissão. Não configurar storage remoto sob esse
contrato sem rever o estágio de preparação e seus limites.

Falha antes do commit desfaz slot, metadados e incremento do contador. Falha depois
de uma admissão confirmada preserva o número e sua lacuna, como no fluxo existente.
Arquivos escritos não são apagados no caminho de exceção: a confirmação do commit
pode ser ambígua. A reconciliação continua usando carência e rechecagem; no PostgreSQL
também coordena a remoção com admissões em andamento. Todo namespace do ocupante
do slot é preservado. Esta etapa não muda a política de exclusão física auditada.

## Estados e autorização posterior

- `ADMITTED`: intenção completa e autorizada; execução ainda não iniciada.
- `PROCESSING` / `STORING`: estados utilizados pelo executor independente da etapa 2.
- `FINALIZED`: publicação concluída.
- `FAILED`: falha registrada, sem liberação automática do slot.
- `INTERRUPTED`: exige reconciliação; não significa prova de morte do executor.

`admitted_at` distingue o contrato durável do legado. Após admissão, fechamento,
liberação, expiração da reserva e logout não revogam a intenção. O executor usa
`load_inputs(attempt_id, execution_id)` sem sessão, usuário corrente ou waypoint
mutável. A função verifica snapshot, metadados e bytes das fotos.

`assert_execution` deve ser chamado em transação em **cada confirmação de resultado**,
mantendo seus locks até o commit. Confere slot, tentativa, estado, `execution_id`
em ambos e hash do snapshot; não usa reserva nem prazo HTTP. O carregamento de
entradas sozinho não autoriza uma confirmação posterior. Início e conclusão com
liberação transacional pertencem ao executor da etapa 2; não há takeover automático.

`retry_admission` permite recuperar uma admissão conhecida. Falhas ou execuções
iniciadas retornam `admission_reconciliation_required`, mantendo o slot. Não há
retry que reassuma por timeout: o supervisor futuro precisa provar encerramento,
rotacionar o fencing e decidir a retomada atomicamente. Uma tentativa diferente
não pode fazer retry enquanto o slot está ocupado.

O comando de reconciliação existente não altera estados de tentativas admitidas,
mesmo vencidas, e não libera slots. A proteção legada por reserva permanece nos
outros fluxos de edição e na publicação síncrona.

## Compatibilidade, migrations e rollout

Com admissão desabilitada e slot vazio, `finalize`/`retry` mantêm execução síncrona.
O registro e retry legados participam da coordenação transacional para impedir
corrida com admissão, mas não retêm o mutex durante conversão. Admissão rejeita
execuções legadas ainda PROCESSING/STORING ou INTERRUPTED (timeout não comprova
encerramento). Slot ocupado bloqueia novas operações
legadas mesmo se a flag de admissão tiver sido desligada posteriormente.

Com `REPORT_ADMISSION_ENABLED=true`, novas publicações/retries síncronos são
bloqueados. Replays permanecem leitura; tentativa admitida não concluída retornada
pela rota legada recebe 409 `admission_executor_unavailable`, nunca um novo 202
sem executor. Nenhuma rota pública chama `admit` nesta etapa.

Migrations novas: `0015_persistent_report_admission` (campos/estado/slot) e
`0016_admission_invariants` (constraint do estado ADMITTED). Aplicar em homologação
autorizada pelo procedimento normal, após revisar `migrate --plan`:

```text
python manage.py migrate --plan
python manage.py migrate signaling 0016_admission_invariants
```

Não foram aplicadas no banco do projeto. O singleton é criado sob coordenação
quando necessário, sem depender de seed descartado pelo flush dos testes.

O comando executor, transições/fencing e confirmação atômica foram implementados na
etapa 2. Permanecem pendentes o supervisor e a recuperação com prova de término. Depois integrar
HTTP 202/status e UI ao executor real. Drenar Gunicorn e execuções legadas antes
de mudar o modo em todos os processos; a flag não cancela conversões antigas.
Não usar o timeout do legado/reconciliação como prova operacional de encerramento.
Manter compatibilidade de snapshot/renderizador e evitar migrar/retirar esta tabela
com slot ocupado. A exclusão de uma publicação concluída continua física/auditada;
o executor libera seu slot na transação de conclusão.

## Validação

`signaling.test_report_admission_postgresql` usa TransactionTestCase e conexões
PostgreSQL distintas para exclusividade, contenção, replays, rollback, fencing,
reinício HTTP simulado, persistência das fotos e interação com legado/reconciliação.
Mocks são usados para falhas/ack ambíguo e para proibir renderização, nunca para
substituir locks PostgreSQL. Reinício de VM, crash do SO, executor/systemd e
durabilidade conjunta de banco/filesystem continuam sendo ensaios futuros.
