# Diagnóstico e recuperação administrativa — etapa 3

Preparação posterior da identidade operacional e escolha de unidade transitória:
[report-systemd-supervision.md](report-systemd-supervision.md). A recuperação continua bloqueada.

## Resultado da inspeção: recuperação bloqueada

Esta etapa implementa **somente diagnóstico**. Não existe comando de recuperação,
liberação de slot, reset de estado, rotação administrativa de fencing ou encerramento
de processos. Essa é a alternativa expressamente prevista quando o encerramento
seguro não pode ser demonstrado pelos mecanismos existentes.

Fatos confirmados no código:

- `ReportPublicationSlot` associa uma tentativa a um `execution_id`; não é um lease.
- `ReportFinalizationAttempt` registra estado, datas e fencing. A etapa 4A adiciona
  identidade operacional separada para novas execuções supervisionadas; execuções
  antigas e manuais continuam sem esse vínculo, e não há atestação de término.
- `report_executor.claim` rotaciona o fencing ao iniciar. `_complete` confirma
  publicação e libera slot atomicamente. Falhas mantêm o slot.
- `report_admission.assert_execution` impede confirmação de uma execução antiga,
  mas não encerra o processo antigo nem comprova ausência de descendentes.
- `pdf_process.run_process` termina grupo/Job Object no caminho controlado. No
  Ubuntu inicia sessão própria; SIGKILL do Python pode impedir o finally e deixar
  o conversor ativo. O handle/identidade operacional não é persistido no banco.
- `reconcile_report_finalizations` não expira/libera execuções admitidas. A exclusão
  física auditada e os tombstones permanecem independentes e inalterados.

Não há como vincular uma observação atual do SO à execução histórica só com UUID,
estado, deadline, PID informado pelo operador ou ausência de heartbeat. FAILED e
INTERRUPTED também não comprovam encerramento de todos os descendentes. Não foi
criado um booleano de confirmação para contornar essa lacuna.

## Comando disponível

```text
python manage.py diagnose_report_publication
python manage.py diagnose_report_publication --attempt-id <UUID>
python manage.py diagnose_report_publication --attempt-id <UUID> --verify-files
```

Sem UUID, consulta o ocupante do slot. Com UUID, permite inspecionar também uma
tentativa cujo slot já foi liberado, útil após confirmação de commit ambígua.
Requer PostgreSQL e autocommit; funciona com todas as flags de publicação desligadas.
As migrations 0015/0016 são pré-requisito, mas não são aplicadas pelo comando.

Retorna JSON com estado do slot/tentativa, execution_id, número/versão e datas,
artefatos e verificações de consistência. Não inclui snapshot, autoria, textos do
relatório, chave de idempotência, tokens, sessão, nomes de arquivos ou caminhos.
Erros de banco são apresentados como `diagnostic_database_unavailable`, sem SQL,
credenciais ou exceções privadas. UUID não encontrado é erro de domínio.

As leituras usam duas transações curtas REPEATABLE READ READ ONLY, sem FOR UPDATE,
sem advisory lock e sem get_or_create. Um slot ausente continua ausente. Há limites
locais de espera por locks (1 s) e por statement SQL (5 s). Verificações de arquivo
ficam fora das transações, reutilizando `PrivateReportStorage` e a enumeração segura
de namespace usada pela exclusão auditada, sem chamar suas operações de mutação.

Por padrão verifica existência/tipo/tamanho; `--verify-files` verifica também hashes
com memória limitada. A listagem é limitada a 256 artefatos, 1024 arquivos de namespace
e 20 identificadores de tentativas admitidas sem slot, com indicação de truncamento.
Não varre todo o storage nem diretórios temporários e não valida visualmente PDFs.

`database_changed_during_observation=true` indica mudança entre as leituras. Mesmo
false não garante imobilidade dos arquivos, ausência de processo ou atomicidade entre
banco e filesystem. Arquivos sem referência podem estar sendo gravados por uma
transação ainda não confirmada: são contados, nunca apagados ou declarados seguros
para limpeza. Inconsistências observadas durante atividade precisam de nova leitura.

O resultado contém sempre:

```json
{"recovery":{"permitted":false,"executor_liveness":"unknown","termination_proof":"unavailable","code":"termination_proof_unavailable"}}
```

Essa saída não é uma autorização administrativa de recuperação. O comando não
persiste auditoria porque não efetua intervenção; guardar sua saída em registro
operacional restrito é possível. Auditoria transacional de recuperação fica pendente
do mecanismo de prova, sem tabela/migration fictícia nesta etapa.

## Procedimento seguro atual

1. Diagnosticar e preservar número, snapshot, slot, fencing e arquivos.
2. Se FINALIZED com marcadores completos e slot liberado, tratar como publicação
   confirmada no banco; não criar outra intenção para compensar resposta perdida.
3. Nos demais casos, manter a recuperação bloqueada. O responsável operacional
   deve impedir novas inicializações e investigar processos/descendentes por seu
   procedimento autorizado, sem usar este comando para matar PIDs arbitrários.
4. Preservar evidências de host/boot/processos e backups consistentes de banco e
   arquivos. Não executar SQL de unlock/reset, reaproveitar número ou apagar
   artefatos com confirmação ambígua como parte deste roteiro.
5. Escolher e implementar um contrato verificável entre supervisor e aplicação
   antes de autorizar uma recuperação. Declaração humana isolada não basta.

O comando antigo `reconcile_report_finalizations` continua disponível com seus
limites existentes; não é um substituto para provar encerramento ou liberar o slot.
Em particular, não usar `--mark-interrupted` como evidência de morte de executor.

## Alternativas propostas para aprovação

| Alternativa | Evidência técnica e condições | Trade-off |
| --- | --- | --- |
| A — supervisor identificado por cgroup (recomendada) | Vincular execution_id a host/boot, invocação e cgroup de origem; consultar supervisor confiável, impedir relançamento e confirmar o grupo inteiro vazio | Permite recuperação localizada; exige integração confiável com o supervisor e impedir escape/migração de processos |
| B — novo boot comprovado do host | Registrar identidade de host/boot no início e obter observação autenticada de boot diferente, cobrindo todos os hosts executores | Forte para execuções anteriores ao reboot, mas disruptiva; sem registro histórico de origem não resolve as tentativas atuais |
| C — isolamento operacional completo | Evidência externa confiável de encerramento/isolamento de todos os ambientes capazes de executar a intenção, com inicialização bloqueada | Pode servir a execuções antigas sem rastreio, mas tem maior custo e requer um protocolo de atestação próprio |

O sumiço de uma unidade/cgroup não comprova encerramento por si só; é preciso
vincular a evidência ao grupo original e impedir migração/escape. Consultar apenas
MainPID ou o nome do processo é insuficiente. Nenhuma dessas alternativas foi
implementada ou declarada disponível no servidor nesta etapa.

## Contrato proposto para futura supervisão systemd

As decisões abaixo são propostas, não configuração aplicada:

| Área | Contrato necessário |
| --- | --- |
| Identidade | Persistir execution_id, host confiável, boot, identidade de invocação/unidade e cgroup; PID só com instante de criação e contexto, nunca como prova isolada |
| Inicialização | Registrar identidade junto ao claim e impedir lançamento fora do supervisor; migração de execuções antigas sem identidade exige procedimento separado |
| Encerramento | SIGTERM com período de graça para o finally; escalonamento supervisionado de todo o grupo, seguido de comprovação de ausência de descendentes |
| Descendentes | Abranger Python, launcher e LibreOffice, mesmo com nova sessão POSIX; impedir migração para fora do grupo supervisionado |
| Diretórios | Checkout somente leitura; storage privado persistente fora de static/media; workspace/perfil temporário por execução, identificável para limpeza posterior segura |
| Usuário/permissões | Conta dedicada sem privilégio para matar processos arbitrários, alterar cgroups ou forjar atestação; mecanismo privilegiado separado e restrito para evidência operacional |
| Recursos | Medir limites agregados de memória/CPU/disco/processos e tempo total; timeout do conversor não cobre toda geração DOCX; encerramento por limite mantém slot para reconciliação |
| Reinício | Não reassumir PROCESSING/STORING por restart ou deadline; só executar ADMITTED legítima. Novo boot não libera slot automaticamente |
| Deploy | Bloquear lançamentos, drenar ou encerrar o grupo sob supervisão, guardar evidências e compatibilidade do renderizador, e somente então atualizar/reconciliar |
| Auditoria futura | Evento único/idempotente com operador, motivo, evidência verificada, tentativa e epochs anterior/novo, estado e resultado; nunca snapshot/credenciais pessoais |

Para a alternativa A, o encerramento de todo o grupo deve seguir o contrato do
[systemd.kill](https://www.freedesktop.org/software/systemd/man/latest/systemd.kill.html).
A documentação do [cgroup v2](https://docs.kernel.org/admin-guide/cgroup-v2.html)
define herança e possibilidade de migração, que precisam ser consideradas na prova.
Validar interfaces/versões efetivas no Ubuntu de homologação antes de implementar.

Depois de estabelecer a prova, uma futura recuperação deverá bloquear
coordenação → slot → tentativa, comparar também o execution_id esperado pelo
operador e a identidade atestada, recusar confirmação já concluída/inconsistências,
rotacionar fencing e registrar auditoria na mesma transação. Dois administradores
com a mesma epoch não poderão efetuar duas intervenções. Nenhum arquivo é removido
nessa transação; eventual preparação de retry deve preservar originais e metadados
ambíguos até resolução explícita. Essas alterações dependem da alternativa aprovada.

## Testes e limites desta entrega

`signaling.test_report_diagnostics_postgresql` cobre ausência de efeitos colaterais,
consultas concorrentes, leitura durante locks do executor, fencing/slot inconsistente,
arquivos ausentes/corrompidos/sem referência, mudanças durante observação, privacidade
e falha de banco. Suítes existentes continuam cobrindo executor, fencing e legado.

Testes de recuperação bem-sucedida, disputa entre recuperadores e auditoria da
intervenção não foram simulados: recuperação não foi habilitada sem prova confiável.
Não houve migration nova, aplicação de migrations no banco principal, ativação de
flags, configuração de serviço, alteração de interface/política de exclusão ou deploy.
