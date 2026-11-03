# Etapa 7F-C2 - exclusao fisica de relatorios oficiais

## Escopo e permissao

Backend apenas, sem botao, alteracao de reservas, deploy ou ativacao da publicacao.
Migration aditiva 0014: permissao signaling.delete_official_reports e tabelas
ReportDeletion/DeletedReportKey. Nao altera dados anteriores, FKs PROTECT existentes
ou grupos. Aplicacao em desenvolvimento/producao e manual, depois da validacao.
O codigo novo (inclusive o bloqueio de replay da finalizacao) requer essa migration.

Biblioteca, detalhes, downloads e finalizacao ja usam permissoes sem is_staff.
Nao foi removida nem acrescentada restricao de staff. A exclusao requer somente
usuario ativo autenticado + delete_official_reports, independentemente das outras
permissoes. Superusuarios ativos mantem a semantica normal do Django has_perms;
ser staff sozinho nao concede acesso. O cadastro publico/grupo analista nao recebe
a nova permissao. Administracao geral do Django nao foi alterada.

## Dependencias e exclusao

TechnicalReportVersion.report, ReportFinalizationAttempt.version e
ReportArtifact.version usam PROTECT. O servico explicito report_deletion.delete_report
remove filhos na ordem tentativa -> artefato -> versao -> relatorio, com ORM normal.
Nao altera snapshots imutaveis, nao usa update para contornar protecoes e nao faz
SQL bruto. Outros relatorios, waypoints, reservas e rascunhos sao preservados.
Tentativas do relatorio excluido sao removidas para permitir remover as versoes;
seu papel minimo de idempotencia sobrevive em hashes SHA-256 das chaves antigas.
Nenhuma outra auditoria e apagada. Exclusao do waypoint/autor nao impede a operacao.

O servico exige PostgreSQL/autocommit e usa duas transacoes separadas:

1. Autoriza, bloqueia relatorio/versoes/tentativas com NOWAIT. Contencao retorna
   conflito; nao espera pelo attempt segurando report na ordem oposta do publicador.
   Publicacoes PROCESSING/STORING bloqueiam exclusao mesmo vencidas: reconciliar
   explicitamente antes. Report lock impede inserir novas versoes por FK durante
   a exclusao; uma futura implementacao de versionamento deve respeitar esse fence.
   Revalida permissao apos locks e eventual espera do contador anual.
2. Valida todos os caminhos e namespaces privados. Captura as chaves registradas
   e arquivos nao registrados nas pastas das versoes/executores anteriores.
   Registra auditoria/outbox e hashes de idempotencia na mesma transacao que apaga
   os registros. Mantem o contador anual; se estiver ausente/atrasado, leva-o pelo
   menos ate a sequencia removida sob lock. Nenhum numero e reutilizado.
3. Somente apos confirmacao do commit, outra transacao bloqueia a outbox e remove
   arquivos. Revalida cada caminho e verifica que nenhuma referencia atual usa a
   chave. Nao apaga diretorios arbitrarios, arquivos externos ou compartilhados.
   Ausencia de arquivo e idempotente. A outbox elimina chaves concluidas e termina
   COMPLETE apenas quando tudo foi removido; PENDING/FAILED continua recuperavel.

Nao ha atomicidade entre banco e filesystem: apos commit o relatorio ja nao existe
na biblioteca, mas arquivos podem permanecer privados ate a limpeza terminar.
Isso NAO e soft-delete: snapshots, versoes, tentativas e metadados de artefatos ja
foram fisicamente removidos. HTTP 202 torna a limpeza pendente explicita.

Uma falha/resultado ambiguo do commit anterior nunca inicia unlink. Retry consulta
a auditoria com report_id unico e continua a mesma operacao. Se o commit da limpeza
falhar depois de algum unlink, a outbox anterior repete com seguranca caminhos ja
ausentes. Nenhuma falha operacional retorna caminhos ou mensagens de excecao.

## Auditoria minima e replay

ReportDeletion conserva UUID da operacao e do antigo relatorio, numero oficial,
data, responsavel (FK SET_NULL e username historico), estado de limpeza e data de
conclusao. Chaves de arquivo e IDs de versao existem somente enquanto ha limpeza
pendente; sao esvaziados na conclusao. Nao conserva snapshot, fotos ou documentos.
DeletedReportKey conserva somente o hash de cada chave e referencia a auditoria
PROTECT. Uma finalizacao com chave retirada recebe report_deleted/410, inclusive
se o solicitante tiver mudado o payload. Nao cria outro numero ou conversao.

Workers antigos nao encontram a tentativa removida. _store agora verifica o fence
antes de gravar alem da verificacao existente ao registrar metadados. Uma corrida
externa com worker interrompido/desligamento abrupto ainda pode produzir orfao
entre banco e filesystem; a reconciliacao conservadora existente deve ser mantida.
Nao excluir com publicadores ativos nem marcar tentativa interrompida sem avaliar
seu executor. Downloads ja abertos nao podem ser revogados retroativamente; em
Windows arquivos abertos podem adiar limpeza. A outbox recupera essa falha.

## Endpoint

POST /signaling/reports/<uuid:report_id>/delete/
Content-Type: application/json; sessao autenticada e CSRF normal obrigatorios.

Payload estrito:

    {"operation_id":"<UUID v4 estavel>","confirm_number":"RTSV-2026-0002"}

Nao aceitar autor/caminho/artefato fornecido pelo cliente. confirm_number deve
coincidir exatamente com o numero do relatorio e fornece confirmacao explicita.
Uma repeticao autorizada para o mesmo relatorio retorna a mesma auditoria e tenta
retomar limpeza. Reutilizar operation_id em outro relatorio retorna 409.

200: exclusao/limpeza concluidas. 202: report_deleted=true mas limpeza pendente,
nao apresentar como conclusao integral. 400: payload/confirmacao invalidos.
401/403: autenticacao/permissao/CSRF. 404: inexistente ou nunca publicado.
409: contencao, publicacao ativa, namespace inseguro ou operacao conflitante.
503: backend/configuracao/transacao indisponivel; repetir a MESMA operacao apos
recuperar ambiente. Nunca recriar um relatorio para recuperar sua exclusao.
Respostas sao privadas e no-store. GET nao modifica nada (405).

## Recuperacao operacional

Comando novo e somente consulta por padrao:

    python -B manage.py cleanup_report_deletions

Apos revisar ambiente, auditoria e operacao, remocao requer autorizacao explicita:

    python -B manage.py cleanup_report_deletions --apply --operation <UUID>

Nao executado em dados existentes nesta implementacao. O comando nao publica,
nao altera reservas e somente usa outboxes de exclusoes anteriormente confirmadas.
Backup deve incluir PostgreSQL (auditoria, hashes de replay, contador e outbox) e
armazenamento privado de forma consistente. Exclusao aqui nao purga backups ou
copias ja baixadas. Politica de retencao de backups precisa de decisao operacional.

## Validacao e homologacao local

Utilizar SOMENTE relatorio sintetico descartavel e banco temporario autenticado.
Nao executar migrate automaticamente em analise_dev ou producao. Com credenciais
PostgreSQL locais do script existente e destino test_analise_dev confirmado:

    .\.venv\Scripts\Activate.ps1
    . .\scripts\local-postgres-env.ps1
    python -B manage.py test signaling.test_report_deletion signaling.test_report_deletion_postgresql signaling.test_report_finalization_postgresql signaling.test_report_read_access signaling.test_report_library signaling.test_report_detail signaling.test_report_artifacts signaling.test_report_download signaling.test_report_reconciliation --verbosity 2

Nao usar --noinput/--keepdb automaticamente. Testes TransactionTestCase criam dados
e arquivos exclusivamente temporarios. SQLite simula apenas o guard de backend;
nao e evidencia de concorrencia PostgreSQL. A suite PostgreSQL verifica exclusoes
simultaneas, contencao com lock de publicacao, versao ativa e revogacao durante
espera de contador. Conversao real continua sendo a homologacao separada existente.

Depois de revisar/aplicar manualmente 0014 no desenvolvimento autorizado: conceder
a permissao individual a um usuario de testes NAO staff; nunca ao grupo publico.
Criar/publicar um relatorio sintetico com fotos pelo fluxo homologado. No navegador
ja autenticado, emitir o POST com CSRF usando UUID estavel e confirm_number exato.
Conferir resposta, ausencia da biblioteca/detalhes/downloads, remocao dos arquivos,
auditoria sem snapshot e contador preservado. Repetir o POST com mesmo UUID, testar
sem permissao e GET; nenhum documento adicional pode ser removido. Replay da chave
de publicacao antiga deve retornar 410 e nao reservar nova numeracao.

## Pendencias para 7F-C3

Botao/modal de exclusao, confirmacao do numero, feedback de 202/409/503 e retomada
explicita usando UUID estavel. Nao existe UI de exclusao nesta etapa. Antes de
liberar: concluir testes PostgreSQL sem skips, homologar exclusao sintetica e
recuperacao de limpeza, aprovar retencao de auditoria/backups e concessao de acesso.

Resultados desta implementacao: suite ampliada com 164 testes Django aprovada em
SQLite temporario; depois de ampliar os casos de recuperacao, os 21 testes
especificos de exclusao passaram. Sao suites sobrepostas. Tambem passaram 151
testes JavaScript, check, verificacao de migration sem drift e git diff --check.
Os quatro testes novos de locks PostgreSQL e a regressao transacional anterior
NAO foram executados por ausencia de credenciais no processo; nao estao homologados.

A 7F-C3 tambem deve tratar a tentativa antiga retirada (410 no replay da chave;
404 ao consultar um attempt removido), sem apagar automaticamente uma intencao
incerta ou recriar o relatorio excluido. Nenhuma mudanca de interface foi feita.
