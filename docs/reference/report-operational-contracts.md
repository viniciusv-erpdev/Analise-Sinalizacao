# Contratos operacionais persistentes — etapa 4C.1

Descoberta somente de leitura implementada posteriormente:
[report-dispatcher.md](report-dispatcher.md). Não há despacho ativo.

Implementação: `signaling/report_operations.py`; integração com admissão,
supervisão, executor, fluxo síncrono e diagnóstico existentes. Não há dispatcher,
launcher, chamadas de início/parada systemd, endpoint HTTP novo, recuperação ou
comando administrativo instalado. Todas as flags existentes mantêm seus defaults.

## Fronteira de confiança e compatibilidade

Cada admissão nova grava `execution_contract`: protocolos de admissão, snapshot,
renderizador e launcher. Alterações incompatíveis exigem incrementar o protocolo
correspondente em `execution_contract()`. O contrato não altera o snapshot original.
Tentativas anteriores recebem `{}` pela migration: não há backfill que invente
compatibilidade; o novo caminho de lançamento as recusa.

`ReportReleaseAuthorization` é um catálogo persistido de aprovação administrativa,
com release, SHA-256 do bundle, SHA-256 do manifesto, contrato e identificador UUID
do responsável. Não existe API HTTP ou aprovação automática desse catálogo.
As linhas são imutáveis pelo save/update/delete ordinários do ORM. O cadastro deve
ser feito futuramente por uma autoridade administrativa autenticada e restrita.
Ainda não há procedimento de cadastramento, revogação ou grants SQL nesta etapa.

O ID da release isoladamente não autoriza: é necessária aprovação persistida,
digests bem formados e contrato exatamente compatível com admissão e código atual.
O registro de lançamento fixa também o hash do contrato. O futuro launcher deve
verificar os bytes do bundle/manifesto contra os digests aprovados, usando paths e
propriedades de catálogo root-owned, sem confiar em paths recebidos do banco/HTTP.
Esta etapa persiste esse contrato, mas NÃO atesta os arquivos instalados, não
verifica assinaturas nem torna seguro executar um bundle apenas porque está no DB.
Privilégios SQL amplos podem forjar aprovações: separar papéis permanece obrigatório.

## Lançamento e autorização de uma única chamada

`ReportLaunch` é OneToOne com a identidade operacional já existente. Não duplica
snapshot, fotos, número ou tentativa. Sua FK PROTECT preserva a identidade histórica;
a FK da identidade para tentativa continua SET_NULL, preservando exclusão física
auditada. Eventos operacionais contêm UUIDs/códigos, sem conteúdo do relatório.

| Operação | Resultado persistente |
| --- | --- |
| `request_launch(identity_id=...)` | REQUESTED; pedido confirmado, ainda sem autorização para chamar systemd |
| `begin_dispatch(launch_id=..., actor=UUID, event_id=UUID)` | UNCERTAIN + dispatch_id exclusivo; só o primeiro chamador recebe ticket |
| Repetição exata de begin_dispatch | Retorna None; nunca concede outro início |
| `observe_launch(..., job_id=...)` | Registra job, sem concluir que a unidade começou |
| `observe_launch(..., invocation_id=...)` | CONFIRMED: início observado, não publicação concluída |
| `observe_launch(..., invocation_id=..., terminal_result=...)` | TERMINAL_OBSERVED; não é prova verificada de término |

Todas as mutações exigem PostgreSQL, autocommit externo e usam a mesma
`report_admission.coordination()` (mutex transacional e slot persistente). Não
mantêm transação durante qualquer futura chamada externa. Concorrência pode
retornar `publication_busy`; um pedido conhecido pode ser consultado/repetido,
mas um ticket consumido nunca é reemitido. Eventos repetidos com outro payload
retornam conflito. Eventos e transições confirmam ou fazem rollback juntos.

O chamador só pode usar um ticket devolvido por begin_dispatch APÓS seu retorno e
commit reconhecido. O futuro launcher não pode reconstruir autorização para uma
nova chamada lendo um dispatch_id antigo. Se o commit perder o ACK, o processo
cair antes da chamada ou o ACK systemd não chegar, tratar como início incerto.
Não existe expiração, cancelamento/reenvio ou reset automático do lançamento.
Um job/resultado desconhecido ou unidade ausente nunca é evidência de não início.

Quando há ReportLaunch, o bind do executor exige dispatch iniciado, estado
UNCERTAIN/CONFIRMED, contrato compatível e invocação observada correspondente,
quando disponível. Preserva rotação/fencing transacional existentes. O caminho
manual 4A SEM ReportLaunch continua compatível; o futuro dispatcher/launcher deve
usar obrigatoriamente o novo contrato, sem converter o caminho manual em fallback.
Claims manuais também respeitam a barreira. Nada inicia automaticamente ao importar
ou consultar esses serviços.

## Barreira de deploy

`ReportDeploymentBarrier` é singleton. Ausência equivale a OPEN com geração UUID
zero; consultas não criam linha. A primeira transição cria a linha sob coordenação.

`transition_barrier(expected_generation=UUID, target=..., actor=UUID, event_id=UUID)`:

| Transição | Condição |
| --- | --- |
| OPEN → DRAINING | Fecha novas admissões, preparações, claims e autorizações de início |
| DRAINING → DEPLOYING | Exige quiescência no mesmo lock que protege admissão/lançamento |
| DRAINING → OPEN | Cancelamento administrativo explícito da drenagem; não declara deploy seguro |
| DEPLOYING → OPEN | Conclusão administrativa explícita; exige quiescência novamente |

Cada transição gera nova geração UUID e evento auditado. Operador antigo não pode
reabrir uma manutenção posterior. Replay exato retorna a geração original, sem
reaplicar a transição: consultar barrier_status para conhecer a geração ATUAL.
Não há timeout de reabertura. Falha de banco desfaz estado e evento juntos;
ack perdido exige leitura, não decisão por ausência de resposta.

Fechar não revoga processamento já assumido: ele pode concluir e liberar o slot
normalmente. Novos claims são bloqueados; uma admissão ainda não iniciada pode
exigir cancelar explicitamente DRAINING, executá-la e fechar novamente. Um ticket
emitido antes do fechamento pode já estar em trânsito; o lançamento persistido
impede DEPLOYING, mesmo com slot vazio. Nunca manter locks SQL durante deploy.

Quiescência exige slot vazio e nenhuma tentativa não FINALIZED. Exige também
ausência de identidades/lançamentos sem término verificável. Como NÃO há verificador
de término nesta etapa, TODOS os registros de identidade/lançamento são conservados
como impedimentos, inclusive históricos FINALIZED e TERMINAL_OBSERVED. Isso é
intencional: nenhum booleano de operador ou evento terminal remove o impedimento.
Uma próxima etapa precisará de prova durável e validada, sem apagar histórico.

Admissão nova e mutações síncronas legadas também recusam identidade/lançamento
operacional pendente mesmo com slot vazio, incluindo histórico manual 4A sem prova.
Replays conhecidos continuam leitura. Nenhuma
operação deste módulo libera slot, reaproveita número ou apaga artefatos.

## Integração futura e limites

Dispatcher local não privilegiado e launcher mínimo separado devem autenticar
seus chamadores; actor UUID é correlação de auditoria, NÃO autenticação. Estes
serviços internos não devem ser expostos diretamente ao HTTP. O futuro deploy
precisa adquirir a barreira e exigir DEPLOYING antes de tocar releases. Esta etapa
não impede um CD/root externo de ignorar o protocolo; CD permanece desativado.

Executor e Gunicorn continuam previstos como analise_app. Nenhuma permissão do
storage 0600/0700, usuário de VM ou autorização systemd foi modificada. Unidade,
InvocationID e descendentes continuam sob o contrato 4A. Recuperação permanece
bloqueada e o diagnóstico informa término verificável indisponível, barreira e
contagens globais de identidades/lançamentos pendentes sem expor paths privados.

## Migration e validação

`0018_report_operational_contracts` depende de 0017; cria quatro modelos e o campo
de compatibilidade da tentativa. Não modifica snapshots nem dados oficiais, não
cria singleton antecipadamente e não inventa prova para histórico. Não foi aplicada
ao banco principal/produção. Aplicação futura autorizada: revisar `migrate --plan`
e executar `migrate signaling 0018_report_operational_contracts` no banco correto.

`signaling.test_report_operations_postgresql` usa conexões PostgreSQL distintas,
fixtures sintéticas, falhas específicas e transações reais. Não chama systemd,
LibreOffice, nem publica documentos. Cobre exclusão mútua, transições, fencing,
compatibilidade, rollback, barreira e corridas. Homologação do futuro launcher e
prova de término não são simuladas como se já existissem.
