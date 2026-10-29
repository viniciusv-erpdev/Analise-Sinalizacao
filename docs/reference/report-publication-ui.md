# Etapa 7F-B - publicacao oficial pela interface

## Fluxo e arquivos

O modal da 7F-A agora recebe URLs geradas por reverse, usuario autenticado e flag
do servidor. ReportPublicationPreview apresenta os estados; ReportPublicationFlow
coordena confirmacao, registro local e Web Locks; ReportFinalization continua
responsavel pelo contrato HTTP da 7E. O cliente aceita attemptId para restaurar
uma consulta, mas nao faz rede ao criar uma instancia.

Confirmar so habilita com permissao renderizada, REPORT_FINALIZATION_ENABLED,
reserva confiavel, formulario valido, autosave salvo/confirmado sem pendencias,
fotos dentro dos limites e navegador compativel. A confirmacao revalida, conclui
flush, captura revisao/fotos, calcula hashes e revalida novamente antes de enviar.
JPEG/PNG: ate 10 fotos, 10 MiB individual, 24 MiB total. Zero fotos e permitido;
conteudo, dimensoes e demais regras continuam sendo validados no backend.

A publicacao congela edicao/submit DOCX e bloqueia fechamento/navegacao normal
ate terminar a operacao. Nao muda o fluxo DOCX fora desse periodo. Heartbeat e
busy do manager sao os existentes; nao ha novo polling, renovacao ou acquire.
Cancelamento do modal, abertura, autosave e polling nao publicam.

201/200 com estado FINALIZED confirma numero/versao. 202 e somente processamento,
com consulta manual por Recuperar tentativa. O link de detalhes aparece apenas
se a permissao view_official_reports foi validada ao renderizar; a pagina de
 destino revalida a autorizacao. Permissao de finalizar nao implica leitura.

## Recuperacao, recarga e abas

Registro local rtsv.publication.v1.u<usuario>.p<waypoint>, criado ANTES do primeiro
POST. Contem UUID de idempotencia, revisao, URL/filtros originais, hashes/tamanho/
tipo das fotos, ID e estado publico da tentativa. Nao contem tokens de reserva,
cookies, sessao, textos, snapshot, fotos ou caminhos privados. A URL preserva o
identificador de analise e filtros porque integram o fingerprint do backend;
isso nao substitui autenticacao nem permite acessar outra sessao.

Web Locks exclusivo no mesmo nome protege abas do mesmo usuario/origem/perfil.
Nova aba le o mesmo registro sob a trava e nao gera outra chave. Clique repetido
compartilha Promise. Sem Web Locks, Web Crypto ou armazenamento duravel, novos
POSTs ficam bloqueados (usar localhost/HTTPS e navegador compativel).

Abertura/reload apenas le registro local, sem rede. Recuperar tentativa consulta
GET quando conhece attempt_id, mesmo sem reserva. Sem ID, faz replay explicito
com a MESMA chave/revisao/filtros/fotos, usando o protocolo normal de reserva.
Apos recarga, originais nao ficam no navegador: reenvio/retry exige reselecionar
as mesmas fotos na mesma ordem; hashes sao conferidos. Mesmo quando o servidor
ja arquivou algumas fotos, a interface exige originais para retomar conservadoramente.
Retomar primeiro consulta o estado; so FAILED/INTERRUPTED permite POST retry {} ou
multipart photos. A chave e numero anteriores permanecem. PROCESSING/STORING nao
sao reiniciados pelo cliente; tentativas interrompidas ainda precisam do processo
operacional de reconciliacao ja existente quando necessario, sem limpeza automatica.

Preparar outro relatorio e acao separada, seguida de nova confirmacao. So remove
o registro LOCAL corrente apos sucesso/falha terminal (reconsultado por GET),
um conflito de revisao anterior a captura sem tentativa, ou rejeicao de payload
400 na PRIMEIRA resposta confirmada sem tentativa. Um 400 recebido depois de uma
falha ambigua nao autoriza descartar a chave. Estados incertos, falta de permissao,
colisao de chave e operacoes ativas nao permitem iniciar outra intencao. Nenhum
registro oficial, snapshot ou numero e removido. Nova chave so nasce na confirmacao
seguinte, nunca pelo reset isolado.

Limites: nao limpar localStorage de tentativa incerta, nao trocar origem/perfil
ou dispositivo para tentar publica-la novamente. Esses ambientes nao compartilham
Web Locks/registro. A exclusividade e idempotencia continuam sendo impostas no
PostgreSQL, mas intencoes deliberadas com chaves diferentes podem produzir outros
relatorios. Nao ha deduplicacao semantica global adicionada. Revogacao de permissoes
e perda de reserva sao sempre revalidadas no backend. Se o browser encerrar o
processo, a chave ja gravada permite recuperacao; nao prova cancelamento do servidor.

## Validacao automatizada

```powershell
node --test static/js/report_publication_flow.test.js static/js/report_publication_preview.test.js static/js/report_finalization.test.js static/js/report_draft.test.js static/js/waypoint_reservation_ui.test.js static/js/waypoint_reservations.test.js static/js/report_characterization.test.js
python -B manage.py test signaling.test_report_download signaling.test_authorization signaling.test_report_finalization signaling.test_report_read_access --verbosity 2
python -B manage.py check
git diff --check
```

## PostgreSQL temporario

```powershell
. .\.venv\Scripts\Activate.ps1
. .\scripts\local-postgres-env.ps1
python -B manage.py shell -c "from django.conf import settings; d=settings.DATABASES['default']; assert d['ENGINE']=='django.db.backends.postgresql'; print({k:d.get(k) for k in ['ENGINE','NAME','HOST','PORT']}); print('TEST:',d.get('TEST',{}).get('NAME') or 'test_'+d['NAME'])"
```

Confirmar host local, analise_dev e test_analise_dev descartavel, sem outra sessao.
Parar se o destino nao estiver confirmado. O comando seguinte cria/migra/destroi
somente o banco temporario; sem --noinput/--keepdb. Nao executar migrate em bancos
existentes.

```powershell
python -B manage.py test signaling.test_report_download signaling.test_authorization signaling.test_report_finalization signaling.test_report_read_access signaling.test_report_finalization_postgresql signaling.test_report_draft_concurrency signaling.test_reservation_concurrency signaling.test_reservations.PostgreSQLReservationContractTests --verbosity 2
$LASTEXITCODE
```

Todos os testes PostgreSQL devem efetivamente executar, sem skips por credenciais.
Essa suite reutiliza concorrencia/idempotencia, expiracao e revogacao durante
conversao da Etapa 6. Nao substituir por SQLite para homologar esses contratos.

## Homologacao local real (somente dados sinteticos)

Usar conta individual de homologacao ja explicitamente autorizada a finalizar;
se precisar de permissoes, concede-las manualmente so a essa conta. Nao alterar
o grupo analista. Verificar que LibreOffice e armazenamento privado local ja
estao configurados conforme Etapa 6; nao instalar ou alterar infraestrutura.
A permissao de leitura e opcional/independente para o link de sucesso.

A flag permanece false por padrao. Habilitar somente na sessao local do terminal,
preservando o valor anterior:

```powershell
$etapa7fPreviousFlag = $env:REPORT_FINALIZATION_ENABLED
try {
    $env:REPORT_FINALIZATION_ENABLED = 'true'
    python -B manage.py check
    python -B manage.py runserver 127.0.0.1:8000
} finally {
    if ($null -eq $etapa7fPreviousFlag) {
        Remove-Item Env:REPORT_FINALIZATION_ENABLED -ErrorAction SilentlyContinue
    } else {
        $env:REPORT_FINALIZATION_ENABLED = $etapa7fPreviousFlag
    }
}
```

1. Abrir analise individual SINTETICA e waypoint reservado, preencher campos
   obrigatorios e aguardar Salvo. Gerar Word deve funcionar como antes.
2. Publicar relatorio oficial abre o modal sem POST/UUID. Confirmar exibe numero,
   versao e link autorizado apenas apos FINALIZED; clique duplo deve gerar uma
   unica operacao. Conferir PDF, DOCX e fotos pelos endpoints privados existentes.
3. Repetir com texto pendente, autosave com falha, campo obrigatorio vazio e fotos
   invalidas: nao deve permitir publicacao local pendente; backend continua validando.
4. Em duas abas no MESMO perfil/origem, a reserva impede edicao concorrente; a
   trava/registro impede outra intencao da mesma conta/waypoint. Nao contornar a
   reserva para testar. Os testes JS exercitam as duas instancias simultaneas.
5. No ambiente sintetico, simular perda de resposta/offline apos envio. Nao clicar
   Preparar outro relatorio nem limpar dados locais. Restaurar rede e usar Recuperar
   tentativa; se reserva expirou, fechar e reabrir pelo protocolo normal. Com ID,
   GET de status pode ser feito sem reserva. Sem ID, replay exige reserva valida.
6. Recarregar a pagina apos resposta incerta: a chave deve permanecer e nao deve
   surgir POST automatico. Reabrir modal, reselecionar originais se necessario e
   recuperar. Se retornar 202, consultar novamente explicitamente apos processamento.
7. Testar Retomar em falha recuperavel controlada de homologacao; nao corromper
   artefatos reais. Consultar estado antes do retry. Testes isolados cobrem timeout,
   falha de conversao e expiracao sem publicar indevidamente.
8. Durante publicacao, fechamento/Escape/Word e navegacao normal devem ser bloqueados;
   encerramento forcado do navegador nao cancela trabalho no servidor. Depois de
   sucesso, o registro continua apontando para o mesmo relatorio. Novo relatorio
   exige Preparar outro relatorio e outra confirmacao deliberada.
9. Conta sem finalize nao ve a acao. Conta sem view_official_reports nao recebe link.
   Desligar a flag e reiniciar servidor local deve desabilitar confirmacao.
10. Inspecionar teclado, foco, scroll do iframe e larguras 320/768/1280.

## Prova de ausencia de duplicacao

Guardar apenas a chave de idempotencia da intencao sintetica (DevTools Application,
registro local acima); nao copiar tokens/cookies. Antes/depois de clique duplo,
recarga e recuperacao, executar consulta administrativa SOMENTE LEITURA:

```powershell
python -B manage.py shell -c "from uuid import UUID; from signaling.models import ReportFinalizationAttempt as A,TechnicalReportVersion as V; q=A.objects.filter(idempotency_key=UUID('COLE-A-CHAVE-UUID-SINTETICA')); print('tentativas:',q.count()); a=q.get(); print('estado:',a.state,'relatorio:',a.version.report.official_number,'versao:',a.version.version); print('versoes do relatorio:',V.objects.filter(report_id=a.version.report_id).count())"
```

Registrar tambem a contagem inicial de tentativas da conta/waypoint sinteticos,
antes da PRIMEIRA confirmacao, para detectar inclusive chaves diferentes. Substituir
USUARIO_DE_HOMOLOGACAO e ID_WAYPOINT_SINTETICO na consulta somente leitura:

```powershell
python -B manage.py shell -c "from signaling.models import ReportFinalizationAttempt as A; print(A.objects.filter(requested_by__username='USUARIO_DE_HOMOLOGACAO',version__report__waypoint_history__id=ID_WAYPOINT_SINTETICO).count())"
```

A contagem cresce em um na primeira intencao e permanece igual em cliques duplos,
recarga, consulta e replay. Retomar tambem conserva a mesma tentativa. Somente
Preparar outro relatorio + nova confirmacao deliberada deve criar outra chave.

Esperado: 1 tentativa por chave, mesmo report_id/numero/versao em todas as respostas,
sem nova conversao/numero por replay. Para um relatorio novo desta etapa: 1 versao,
um PDF e um DOCX; fotos com ordinais unicos. Nao usar apenas o contador anual como
prova: lacunas legitimas existem. Nao modificar RTSV-2026-0001 nem seus artefatos
para fazer testes de falha.

## Producao e pendencias

Sem deploy, migrations, novos modelos ou alteracoes de conversao. Continua opt-in
para homologacao. Um unico worker Gunicorn sincrono pode bloquear heartbeat e
expirar reserva durante LibreOffice; isso impede publicacao pelo backend. Nao
habilitar em producao antes de resolver a estrategia operacional aprovada.
PostgreSQL real, navegador/Web Locks reais, LibreOffice e inspecao visual desta
nova interface sao pendencias de homologacao; testes SQLite nao as substituem.

## Resultados desta implementacao

156 testes JavaScript aprovados, sem skips; 81 testes Django aprovados em SQLite
temporario (incluindo renderizacao autorizada/URLs, DOCX, autorizacao, snapshot e
politica de leitura). A fixture inicial do teste de filtro foi corrigida para
incluir sinistro sintetico de 2026; nenhuma regra de filtros foi alterada.
Check, sintaxe e diff --check executados. Nenhuma migration adicional necessaria.
A validacao real PostgreSQL da 7E foi aceita conforme resultado informado pelo
usuario; ela nao substitui a homologacao PostgreSQL e visual desta nova interface.

Se o contexto/fotos originais forem irrecuperaveis e a tentativa permanecer
incerta, solicitar verificacao administrativa no PostgreSQL pela chave antes de
remover qualquer registro local. Nao improvisar nova intencao para contornar isso.
