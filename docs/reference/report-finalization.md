# Finalizacao oficial de relatorios - Etapa 6

## Estado e limites de uso

Backend opt-in para homologacao sincrona. `REPORT_FINALIZATION_ENABLED` e false
por padrao. Nenhuma interface, biblioteca, edicao, download de arquivo arquivado
ou tarefa de producao foi adicionada. A migration 0012 precisa de revisao e
aplicacao manual no ambiente autorizado. Nao houve aplicacao em banco existente.
A validacao operacional e visual no Ubuntu continua pendente.

## Modelos e fonte historica

- TechnicalReport: UUID permanente, waypoint opcional SET_NULL, identificacao
  historica, ano/sequencia unicos e datas de reserva/atribuicao do numero.
- TechnicalReportVersion: versao numerada unica no relatorio, snapshot JSON,
  schema_version=1, hashes do snapshot/origem, identidade congelada do autor,
  emissao e finalizacao. Entradas historicas nao podem ser alteradas por save ou
  update ordinarios do ORM. SQL direto continua sendo responsabilidade administrativa.
- ReportFinalizationAttempt: UUID, chave de idempotencia UUID v4 globalmente unica,
  solicitante, hash da intencao, execucao, prazo, estado e codigo seguro da falha.
- ReportArtifact: PDF, DOCX original e fotos; chave privada unica, ordinal,
  MIME, tamanho, SHA-256 e metadados. Sem binarios no PostgreSQL.
- ReportAnnualCounter: uma linha por ano, bloqueada antes do incremento.

O snapshot e a fonte de uma futura edicao. Inclui formulario completo confirmado,
revisao, coordenadas/status/raio, intervencoes e observacoes, textos historicos dos
problemas/solucoes, filtros normalizados e seus rotulos, levantamento e somente
os sinistros selecionados dentro do raio, autoria, emissao, numero e fotos.
Nao inclui toda a sessao, cookies, IDs de sessao, tokens ou geracao da reserva.
O esquema e o renderizador possuem versao explicita. A nova edicao devera criar
outra TechnicalReportVersion e novos ReportArtifacts, nunca atualizar a anterior.
O renderizador do snapshot nao consulta o waypoint, o rascunho ou a sessao.
Ampliar filtros/raio para sinistros que nao foram arquivados exige novo dataset.

A reproducao exata de bytes/layout nao e garantida com outras versoes de fontes,
Python, templates ou LibreOffice. Por isso PDF e DOCX originais sao preservados,
alem dos dados editaveis. Logos/icones e regras de renderizacao ainda dependem
da versao do codigo instalada; os originais arquivados preservam a representacao.

## Contrato HTTP

Todas as rotas exigem login, view_signalingpoint, generate_signaling_report e
**signaling.finalize_technicalreport**. A nova permissao apenas e declarada na
migration. Nao e atribuida ao grupo analista/cadastro publico. Provisionar apenas
um grupo administrativo aprovado de finalizadores e auditar permissoes aditivas.
Consulta e retomada sao limitadas ao solicitante original, inclusive para staff.
Nao existe bypass baseado no UUID nem URL publica de arquivo.

### Criar

POST /signaling/points/<id>/report-finalizations/?analysis=<analise>&year=2026

Headers: CSRF e os tres X-Waypoint-* do protocolo atual. Nunca colocar credenciais
na URL ou em logs. JSON sem fotos:

```json
{"idempotency_key":"UUID-v4-gerado-uma-vez-por-intencao","expected_revision":3}
```

Com fotos: multipart com exatamente idempotency_key, expected_revision e fotos
repetidas no campo photos (csrfmiddlewaretoken permitido). Nao aceita textos do
formulario, autor, numero ou caminho de arquivo. Os textos vem da revisao SALVA;
antes de chamar, o futuro frontend deve concluir o autosave e obter a revisao.
Filtros de year/month/category/gravity usam o contrato da geracao DOCX atual.
A primeira captura exige analise individual valida na sessao do solicitante.

Resposta finalizada 201: attempt_id, report_id, version, number, state,
issued_at e finalized_at, sem caminho privado. Emissao ISO com offset de Sao Paulo.
Repeticao da mesma chave/payload retorna a mesma identificacao sem reconverter;
201/200 para finalizado, 202 enquanto em andamento, 409 se falhou/interrompeu.
Chave reutilizada com outra intencao retorna 409 idempotency_key_conflict.
Uma repeticao finalizada e leitura, por isso nao exige reserva ainda ativa.
Nao reutilizar uma chave para outra intencao nem gerar outra chave automaticamente
apos timeout de rede. Consultar o estado primeiro.

### Consultar e retomar

GET /signaling/report-finalizations/<attempt_uuid>/
POST /signaling/report-finalizations/<attempt_uuid>/retry/

Consulta nao renova nem exige reserva. Retry exige CSRF, headers de uma reserva
valida e JSON {} (ou multipart apenas photos para reenviar originais que faltam).
Pode usar uma nova aquisicao legitima pelo protocolo existente, preservando
snapshot, autor, numero e emissao congelados. As fotos reenviadas precisam ter
exatamente ordem, bytes e metadados originais. Retry nunca edita o snapshot.
Se waypoint/rascunho/itens mudaram, retorna report_source_changed: revisar o
formulario e iniciar NOVA intencao, mantendo o registro anterior e sua lacuna.
Caso o waypoint tenha sido excluido, uma tentativa inacabada nao pode publicar;
os relatorios ja finalizados e seus arquivos permanecem independentes.

401/403: autenticacao/autorizacao; 428: headers ausentes; 409: reserva/revisao/
origem/execucao invalidada; 400: dados invalidos; 503: desabilitado/conversor/
armazenamento/falha operacional. Falhas posteriores a criacao retornam tambem
attempt com identificacao e estado recuperavel. Erros nao incluem diagnostico
privado do LibreOffice, conteudo do documento ou caminhos.

## Transacoes, numero e emissao

Ordem: waypoint -> reserva -> rascunho -> tentativa -> contador anual.
A primeira captura materializa a origem sob o protocolo atual. Levantamento e
validacoes caras ocorrem fora desse bloqueio. Uma segunda transacao compara
a origem integral (incluindo filhos e revisao), reserva numero e persiste snapshot.
O contador anual usa chave unica/get_or_create e SELECT FOR UPDATE, nao MAX+1.
Constraints unicas garantem ano/sequencia e chave de idempotencia.

Numero e emissao usam o MESMO instante congelado, convertido explicitamente para
America/Sao_Paulo. Por exemplo 2027-01-01 01:30 UTC ainda e 2026-12-31 22:30 em
Sao Paulo: numero RTSV-2026-NNNN. Timestamps Django continuam armazenados em UTC;
TIME_ZONE global nao foi alterado. Limite explicito de 9999 numeros por ano;
exceder exige uma decisao sobre formato, nao reaproveitamento.

O numero e reservado antes da conversao para constar no documento. So e atribuido
oficialmente na publicacao. Falhas preservam numero reservado e geram lacunas.
Retentativa usa o mesmo numero. Nunca remover tentativas/contadores para liberar
numeros. Falhas antes do commit inicial nao constituem reserva oficial persistida.

Geracao DOCX, LibreOffice e arquivos sao processados SEM transacao/locks abertos.
O servico recusa execucao dentro de transacao ambiente/ATOMIC_REQUESTS. Uma terceira
transacao revalida sessao, permissoes, reserva, origem e execucao apos esperas,
marca a versao finalizada e atribui numero. Um PDF no disco nao equivale a publicacao.

## Reserva durante conversao e frontend futuro

O futuro frontend deve manter o MESMO gerenciador de reservas montado e executar
a renovacao normal enquanto aguarda o POST. Nao desmontar o waypoint, liberar a
reserva, suspender seu heartbeat nem criar outro polling/heartbeat para finalizar.
Enviar um POST longo nao renova a reserva. O backend nunca a adquire/renova por
conta propria. Expiracao durante conversao resulta em falha recuperavel, snapshot
mantido, numero nao atribuido e nenhum relatorio publicado. Reaquisicao so pelo
protocolo normal, seguida de retry explicito se a origem ainda corresponder.

Estados: PROCESSING -> STORING -> FINALIZED; FAILED ou INTERRUPTED para recuperacao.
Prazo padrao de execucao 900s; conversao 60s. O identificador por execucao impede
que resposta/processo antigo publique ou altere o estado de uma retomada.
Uma tentativa ativa dentro do prazo retorna 202, sem disparar outra conversao.
Apos o prazo pode ser retomada com reserva valida; retomadas concorrentes tem
um unico vencedor. Nunca finalizar automaticamente um processo interrompido.

## Armazenamento, falhas e backup

REPORT_PRIVATE_ROOT deve ser absoluto, fora do checkout, STATIC_ROOT e MEDIA_ROOT.
Nao configurar location/alias Nginx nem URL publica para esse diretorio.
Arquivos exclusivos: <version_uuid>/<execution_uuid>/<artifact_uuid>.<ext>.
Nome amigavel nos metadados: RTSV-2026-0001-v1.pdf/docx; fotos ordenadas -foto-N.
Cada nova versao/execucao usa arquivos novos. JPEG/PNG originais: ate 10 arquivos,
10 MiB cada, 24 MiB no conjunto, 20 megapixels por imagem. Formato e conteudo sao
validados pelo Pillow; nomes/MIME enviados pelo cliente nao determinam o caminho.
Snapshot limitado a 8 MiB; demais limites do conversor permanecem ativos.
Originais podem conter EXIF/GPS: estao privados, devem integrar a politica de
acesso/retencao e nunca ser incluidos em logs ou dados de sessao arquivados.

Arquivos usam criacao exclusiva, fsync, SHA-256 e leitura de verificacao antes
de publicar. Diretorios novos 0700 e arquivos 0600 no Unix; no Windows conferir
ACL do diretorio (chmod nao substitui ACL). O usuario do processo precisa somente
ler/escrever no raiz privado e no temporario, executar LibreOffice e ler fontes.
O backend de armazenamento e isolado; futura migracao deve copiar arquivos,
verificar hashes e preservar as chaves. Nao servir .url desse armazenamento.

Banco e filesystem nao tem commit atomico. Queda entre gravacao e registro pode
deixar orfaos; falhas nao publicam. Fotos ja registradas sao preservadas no retry.
Derivados nao publicados de uma execucao anterior deixam de ser referenciados
quando a retomada comeca; os arquivos viram candidatos a reconciliacao.
Nao apagar derivados de tentativas falhas arbitrariamente nem arquivos finalizados.
Se uma foto nao chegou a ser registrada antes da queda, reenviar originais no
retry; se arquivo REFERENCIADO estiver corrompido/perdido, restaurar de backup,
sem sobrescrever silenciosamente o original.

Auditoria administrativa READ-ONLY:

```powershell
python manage.py reconcile_report_finalizations
```

Mutacoes APENAS mediante revisao operacional: --mark-interrupted marca execucoes
vencidas; --delete-orphans remove somente arquivos sem referencia e antigos
(--grace-hours 24 por padrao, minimo 1). Nao publica, nao renova reserva e nunca
remove arquivo ainda referenciado. Os comandos nao foram executados em banco
existente. Retencao de tentativas falhas e politica de limpeza exigem revisao
antes da biblioteca; nao ha exclusao de relatorio nesta etapa.

Backup deve incluir PostgreSQL E todo o raiz privado, com janela consistente ou
manifesto e verificacao de SHA-256. Testar restauracao dos dois juntos; so pg_dump
nao recupera PDFs/fotos. Controlar espaco e acesso no destino de backup.

## Homologacao local: ordem e efeitos

1. Revisar diff/migration. A etapa abaixo de testes nao requer migrar analise_dev.
2. No SEU PowerShell, ativar venv e autenticar sem exibir senha:

```powershell
. .\.venv\Scripts\Activate.ps1
. .\scripts\local-postgres-env.ps1
python manage.py shell -c "from django.conf import settings; d=settings.DATABASES['default']; print({k:d.get(k) for k in ['ENGINE','NAME','HOST','PORT']}); print('TEST_NAME:', d.get('TEST',{}).get('NAME'))"
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py showmigrations signaling
```

Consultas/checks apenas. Confirmar localhost, analise_dev e test_analise_dev,
usuario local, ausencia de producao. Nunca imprimir DATABASES inteiro.
3. Confirmar que test_analise_dev e exclusivamente descartavel, nao contem dados
que devam sobreviver, nao e usado por outra sessao e nao e analise_dev. Se houver
duvida, PARAR. O Django cria/aplica schema/limpa/exclui o banco DE TESTES; nao usa
analise_dev para os testes. Se perguntar sobre banco ja existente, nao confirmar
exclusao antes dessa verificacao. Nao usar --noinput ou --keepdb automaticamente.
4. Testes que MODIFICAM SOMENTE o banco descartavel confirmado:

```powershell
python manage.py test signaling.test_report_finalization_postgresql signaling.test_report_draft_concurrency signaling.test_reservation_concurrency --verbosity 2
python manage.py test signaling.test_report_finalization signaling.test_report_finalization_pdf signaling.test_report_generator signaling.test_report_download signaling.test_report_drafts signaling.test_authorization signaling.test_reservations signaling.test_pdf_conversion signaling.test_pdf_integration --verbosity 2
```

A primeira suite exige PostgreSQL real; ignorados em SQLite nao sao evidencia de
concorrencia. O conversor da suite transacional e simulado para controlar falhas;
test_report_finalization_pdf e test_pdf_integration executam LibreOffice REAL,
sem banco, quando instalado. Enviar apenas resumo, nomes de falhas/erros, sem
headers, dados reais, senhas ou traceback de configuracoes.
5. Para homologar o HTTP manualmente, primeiro revisar backup e aplicar 0012
MANUALMENTE somente em banco local autorizado. Esta documentacao nao e execucao
nem autorizacao de producao. Provisionar a permissao nova manualmente, sem
atribui-la a analista/cadastro publico. Escolher raiz privado fora do repositorio
com ACL restrita. Na sessao de homologacao:

```powershell
$env:REPORT_FINALIZATION_ENABLED = 'true'
$env:REPORT_PRIVATE_ROOT = Join-Path $env:LOCALAPPDATA 'AnaliseSinalizacao\reports-homologacao'
# Opcional se nao encontrado automaticamente: caminho absoluto administrativo.
# $env:REPORT_LIBREOFFICE_EXECUTABLE = 'C:\Program Files\LibreOffice\program\soffice.com'
python manage.py runserver
```

Nao adicionar botao nesta etapa. Pelo navegador autenticado, importar somente
sinistros sinteticos, adquirir reserva pelo mapa, preencher campos obrigatorios,
esperar autosave confirmado e anotar a revisao. Um operador autorizado pode usar
DevTools com o contexto do gerenciador EXISTENTE para fazer o POST acima, sem
copiar/expor tokens em mensagens. Manter a pagina/gerenciador vivos durante o POST.
Nao inventar uma reserva nem abrir o endpoint diretamente como navegacao GET.

Verificar: numero/autor/emissao no arquivo privado por ferramenta administrativa;
repetir MESMA chave/payload sem reconverter; outra chave gera novo numero;
remover permissao/liberar/expirar reserva durante conversao deve impedir publicacao;
retry com nova reserva normal e mesma origem deve usar mesmo numero/snapshot;
alterar rascunho/filhos bloqueia retry/publicacao; excluir waypoint depois de
finalizado preserva historico/arquivos; revisar fotos e hashes. Gerar DOCX pela
rota antiga antes/depois. Testar timeout, conversor ausente e raiz sem permissao
apenas em ambiente descartavel; nao corromper arquivo de homologacao util.
6. Ao terminar, parar servidor e remover flags APENAS da sessao local:

```powershell
Remove-Item Env:REPORT_FINALIZATION_ENABLED
Remove-Item Env:REPORT_PRIVATE_ROOT
```

Nao remover arquivos/bancos automaticamente. Revisar retencao apos homologacao.

## Producao: bloqueios para habilitacao futura

Nao houve alteracao de Gunicorn/Nginx/infra. Um worker sincrono ocupado pode impedir
renovacoes HTTP e fazer a reserva expirar corretamente durante conversao. O timeout
Gunicorn usual (30s) tambem pode matar uma conversao de 60s. Aumentar apenas timeout
nao resolve capacidade, consumo de CPU/memoria ou queda de heartbeat.
Antes de habilitar: validar Ubuntu/fontes/layout/ACL/backup/restauracao; dimensionar
capacidade para renovacoes e conversoes, limites globais de concorrencia/espaco,
monitoracao e reconciliacao de execucoes interrompidas. Alternativa recomendada:
processamento em executor/servico supervisionado e limitado, mantendo pedido e
snapshot no banco e revalidando a publicacao. Uma fila dedicada exige desenho e
aprovacao posteriores; nenhuma foi implementada. Frontend/biblioteca/downloads
privados/versionamento operacional continuam fora desta etapa.


## Evidencias desta implementacao (28/10/2026)

- Django check: sem problemas. makemigrations --check --dry-run: sem alteracoes.
- Sintaxe AST de 13 arquivos Python e git diff --check: aprovados.
- Suite focada final: 206 testes descobertos; 153 passaram; 53 ignorados.
  Ignorados: 24 novos testes PostgreSQL de finalizacao e 29 contratos PostgreSQL
  existentes. Nao foram simulados com SQLite como prova de concorrencia.
- As regressoes funcionais usaram apenas SQLite de testes EM MEMORIA, criado e
  descartado pelo Django. As migrations foram exercitadas exclusivamente nele.
- Conversao REAL de snapshot oficial sintetico: passou, incluindo numero,
  autoria e emissao de Sao Paulo. As duas integracoes LibreOffice preexistentes
  tambem passaram. Isso nao substitui a validacao visual/operacional Ubuntu.
- Na primeira rodada ampla, o teste antigo de timeout do supervisor falhou por
  ausencia de child.pid (processo encerrado antes da sincronizacao). A repeticao
  isolada passou, assim como a rodada final completa; nenhum codigo do supervisor
  foi alterado para mascarar o resultado.
- PostgreSQL: variaveis de autenticacao ausentes neste processo; o script local
  solicita senha interativa e nao transfere o ambiente de outro terminal para
  este processo. Nao foram lidos/criados arquivos de credenciais nem modificada
  a autenticacao. Rodar a suite transacional no PowerShell autenticado acima.
- Nenhuma migration aplicada em analise_dev/banco existente; nenhum deploy.

A homologacao de concorrencia permanece PENDENTE ate executar os 24 testes no
PostgreSQL real. O teste de conversao demorada usa duas conexoes e eventos:
pausa o conversor, adquire o lock do waypoint na outra conexao (prova de que nao
ficou bloqueado), expira a reserva no banco e libera o conversor; a publicacao
deve falhar e a retomada legitima deve preservar snapshot e numero.


## Arquivos desta etapa

Modificados: config/settings.py; signaling/models.py; signaling/report_generator.py;
signaling/urls.py; docs/reference/signaling-and-reports.md.

Criados: signaling/migrations/0012_official_technical_reports.py;
signaling/report_finalization.py; signaling/report_finalization_views.py;
signaling/report_snapshots.py; signaling/report_storage.py;
signaling/management/__init__.py; signaling/management/commands/__init__.py;
signaling/management/commands/reconcile_report_finalizations.py;
signaling/test_report_finalization.py; signaling/test_report_finalization_postgresql.py;
signaling/test_report_finalization_pdf.py; docs/reference/report-finalization.md.

Verificacao complementar apos a rodada de 206: 11 testes sem banco passaram,
incluindo a distincao de HTTP 401 para sessao encerrada, 403 para autorizacao e
409 para reserva expirada durante a etapa de conversao/publicacao. Nao houve
nova alteracao de modelos ou migrations nessa verificacao complementar.


## Correcoes R1/R2/R3 posteriores a revisao

Implementadas conforme aprovado; detalhes e comando PostgreSQL conjunto atualizado
em [etapa6-final-review.md](etapa6-final-review.md). Verificacao de artefatos ocorre
antes do registro; falhas deixam bytes para reconciliacao, sem unlink imediato.
Execucoes PROCESSING/STORING, inclusive vencidas, protegem seus arquivos sem
referencia ate interrupcao explicita ou troca de execucao. Snapshot e numero nao
mudam. Arquivo adicional: signaling/test_report_reconciliation.py.
Os resultados anteriores nao comprovam a regressao PostgreSQL das correcoes:
a rodada conjunta de 75 testes permanece pendente no terminal autenticado.
