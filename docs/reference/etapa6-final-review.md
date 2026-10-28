# Atualizacao R1/R2/R3 - correcoes implementadas em 28/10/2026

As propostas R1 e R2 desta revisao foram aprovadas e implementadas. O parecer
original abaixo fica preservado como registro da causa e do roteiro condicional.

- _store verifica tamanho e SHA-256 pela leitura dos bytes persistidos ANTES de
  abrir a transacao que registra ReportArtifact. Nao chama delete em nenhuma
  falha; arquivos possivelmente orfaos ficam para reconciliacao conservadora.
- Falha de verificacao nao cria metadados. Falha de registro ou confirmacao
  ambigua do commit conserva os bytes. Retry pode reenviar fotos originais se
  ainda nao houver registro, ou reutilizar a foto ja registrada. Snapshot, numero
  e chave de idempotencia nao sao alterados.
- A reconciliacao preserva arquivos do execution_id atual em PROCESSING/STORING,
  inclusive vencidos, ate interrupcao/retomada explicita. Referencias no banco
  continuam protegidas e sao reconferidas antes de qualquer remocao.
- Cinco novos testes sem banco cobrem ordem de verificacao/registro, falha de
  leitura com cleanup indisponivel, tamanho/hash incorretos, falha de registro
  e commit ambiguo. Seis testes de reconciliacao usam arquivos exclusivos de
  testes com mtime antigo/recente, referencias e execucoes ativas. Tres novos
  testes PostgreSQL cobrem retry de fotos apos falha de leitura/registro e
  preservacao apos perda de confirmacao de um commit real.
- Regressao local: 68 testes aprovados, zero skips/falhas, usando apenas banco
  descartavel em memoria e arquivos temporarios. PostgreSQL nao foi substituido
  por essa execucao: suas credenciais nao estao disponiveis ao processo Codex.
- Check Django, sintaxe, git diff --check e makemigrations --check --dry-run
  aprovados. Nenhuma migration nova e necessaria. A 0012 nao foi aplicada em
  analise_dev; nao houve limpeza em arquivos/bancos existentes.

## R3: execucao manual ainda necessaria

Os 37 testes anteriores passaram em PostgreSQL ANTES destas correcoes. Agora
sao 27 de finalizacao + 5 de rascunhos + 8 de concorrencia + 29 contratos = 69.
Incluindo os 6 testes de reconciliacao abaixo, a coleta esperada e 75, sem skips
em PostgreSQL. Confirmar primeiro que test_analise_dev e somente descartavel,
sem dados necessarios e sem outra sessao usando-o. O Django cria e destroi esse
banco; nao usar --keepdb/--noinput automaticamente. Nao executar o comando se
host/destino nao forem os locais aprovados. Nao imprimir senhas ou DATABASES.

```powershell
. .\.venv\Scripts\Activate.ps1
. .\scripts\local-postgres-env.ps1
python -B manage.py test `
  signaling.test_report_finalization_postgresql `
  signaling.test_report_draft_concurrency `
  signaling.test_reservation_concurrency `
  signaling.test_reservations.PostgreSQLReservationContractTests `
  signaling.test_report_reconciliation `
  --verbosity 2
$LASTEXITCODE
```

O roteiro persistente do parecer abaixo permanece condicionado ao resultado
positivo dessa rodada. Nao declarar Etapa 6 homologada antes disso. Flag continua
false por padrao; nenhuma reserva, autosave, geracao DOCX, modelo ou infraestrutura
foi alterada por estas correcoes.

---

# Revisao final da Etapa 6 e homologacao local - 28/10/2026

## Parecer antes da homologacao

Os 37 testes PostgreSQL informados estao confirmados no arquivo
resultado-testes-etapa6.txt: 24 de finalizacao, 5 de rascunhos e 8 de reservas;
37 aprovados, zero skips, 43,281 segundos. A 0012 foi aplicada e o banco
**test_analise_dev** foi destruido ao final. Nao houve execucao PostgreSQL
adicional pelo Codex nesta revisao. O prefixo PowerShell NativeCommandError
acompanha a mensagem de criacao do banco, nao uma falha de teste do Django;
na proxima rodada registrar tambem $LASTEXITCODE.

**Nao habilitar ainda a finalizacao para homologacao persistente.** Ha uma falha
comprovada no tratamento de gravacao/leitura de artefatos e lacunas de cobertura.
As correcoes abaixo sao PROPOSTAS; nenhum arquivo de implementacao foi alterado
nesta revisao. Nao e necessaria outra migration para as correcoes propostas.
A migration 0012 e estruturalmente aditiva e consistente com os modelos, mas a
recomendacao para aplica-la no desenvolvimento fica condicionada ao fechamento
destas pendencias e a conferencia do plano/backup local.

## Problemas e menor correcao proposta

### R1 - arquivo removido depois de registrar metadados (prioridade alta)

Em signaling/report_finalization.py, _store():
1. storage.save grava o arquivo;
2. ReportArtifact.objects.create e confirmado ao sair de transaction.atomic;
3. storage.read tenta verificar o arquivo FORA da transacao;
4. qualquer excecao nesse trecho chama storage.delete(key).

Uma falha temporaria de leitura pode, portanto, apagar um arquivo valido e deixar
ReportArtifact persistido apontando para arquivo ausente. Para PHOTO, retry
preserva o registro e _execute tenta le-lo novamente, sem usar os originais
reenviados quando ja existe o registro. Isso pode impedir a recuperacao de uma
tentativa que jamais foi publicada. O teste atual de armazenamento so simula
falha em save, nao falha na leitura de verificacao apos o commit.

Comprovacao nesta revisao: injecao de falha em memoria com filesystem, ORM e
transacao simulados retornou metadata-created=True e delete-called=True.
Nao foi escrita/removida nenhuma foto real nem acessado banco nesse ensaio.
Nao e um novo teste transacional PostgreSQL e nao substitui sua regressao.

Menor correcao proposta: verificar tamanho/hash dos bytes persistidos ANTES de
registrar ReportArtifact, fora da transacao; depois registrar sob a validacao
da execucao. Em falha de verificacao/registro, conservar o arquivo como candidato
a orfao, em vez de apaga-lo imediatamente. A reconciliacao conservadora resolve
os residuos apos a carencia. Isso tambem evita exclusao em commit ambiguo de DB.
Um retry sem artefato registrado pode solicitar o reenvio dos mesmos originais;
numero, snapshot e hashes permanecem inalterados. Nao alterar arquivo finalizado.

Testes necessarios: read falha apos save; registro no banco falha apos gravacao;
commit/retorno ambiguo nao apaga arquivo referenciado; retry com as fotos originais
consegue concluir; falha de cleanup nao mascara o codigo principal.

### R2 - reconciliacao nao foi testada com arquivos antigos (cobertura)

O teste test_read_only_reconciliation_never_deletes_finalized_files chama
--delete-orphans sobre arquivos novos. Como a carencia padrao e de 24h, os
arquivos passam pela condicao de idade mesmo que a protecao por referencia
estivesse incorreta. O codigo atual verifica referencias antes da exclusao;
nao foi comprovada uma exclusao incorreta pelo comando de reconciliacao.

Menor correcao: adicionar casos com mtime anterior a carencia: PDF/DOCX/fotos
referenciados devem sobreviver; orfao antigo deve sobreviver no dry-run e ser
removido apenas com flag; orfao recente deve sobreviver; nova referencia entre
listagem e verificacao final deve impedir remocao. Cobrir tambem arquivos de
execucao ainda ativa, sobretudo se prazos administrativos forem ampliados.
Ate isso passar, homologar reconciliacao somente SEM flags de mutacao.

### R3 - contratos PostgreSQL anteriores ainda nao incluidos nesta rodada

O comando de 37 testes nao inclui os 29 testes herdados por
signaling.test_reservations.PostgreSQLReservationContractTests. Eles eram parte
dos skips da rodada anterior. Executar essa classe diretamente evita o skip
esperado da classe especifica de recusa SQLite. Nao chamar tudo de validado
em PostgreSQL com base apenas nos 37 casos.

## Conferencia dos dez pontos

| Item | Resultado e limite |
| --- | --- |
| 1. PostgreSQL sem skips | 37/37 confirmados; faltam os 29 contratos anteriores e os casos adicionais R1/R2. |
| 2. Concorrencia/idempotencia/reserva | Nenhuma falha nos 37. Numero anual, mesma chave, revisao, expiracao durante conversao, retomada concorrente e execucao antiga estao cobertos. Persistencia tem R1. |
| 3. Migration 0012 | Cinco CreateModel e quatro AddConstraint; constraints adicionais tambem declaradas nos CreateModel. Sem alteracao de campos existentes, RunPython, RunSQL, remocao ou backfill. FK para waypoint e opcional SET_NULL. Consistencia makemigrations aprovada. |
| 4. Desabilitada | REPORT_FINALIZATION_ENABLED usa false por padrao. Nao alterar TIME_ZONE global. |
| 5. Permissoes | A migration declara finalize_technicalreport, nao concede. register_analyst apenas associa analista. Consulta real de grupos locais ainda precisa ser feita no terminal autenticado; permissoes sao aditivas. |
| 6. Arquivos privados | Raiz absoluta obrigatoria; codigo rejeita checkout, STATIC_ROOT, STATICFILES_DIRS e MEDIA_ROOT configurados. Sem URL ou endpoint de download. Exemplo Nginx serve somente STATIC_ROOT. Nginx efetivo Ubuntu e ACL Windows nao foram inspecionados; conferir antes de habilitar qualquer ambiente. |
| 7. Recuperacao | Conversao/timeout/expiracao preservam tentativa, snapshot e numero; retry exige reserva/origem/permissoes e troca execution_id. Ha R1 no armazenamento. |
| 8. Independencia historica | Snapshot schema_version=1 e fotos/DOCX/PDF preservam versao. Waypoint SET_NULL, rascunho nao e FK da versao. render_snapshot nao consulta waypoint/rascunho/sessao. Reproducao exata depende de codigo/fontes; originais sao a representacao preservada. |
| 9. Reconciliacao | Dry-run por padrao, flags explicitas, carencia e rechecagem de referencias. Ampliar testes R2 antes de permitir limpeza. |
| 10. Homologacao | Procedimento abaixo; passos de escrita sao condicionais a R1/R2 corrigidos e testes aprovados. |

Snapshots tem protecao de campos historicos em save/update ordinarios, mas nao
sao um armazenamento WORM nem defesa contra SQL administrativo. Nao ha endpoint
de edicao. Uma futura edicao deve criar outra versao e novos arquivos. O campo
finalized_at pode ser alterado via QuerySet.update, pois nao participa dessa
protecao; endurecer esse caminho antes de introduzir rotinas que o utilizem.
Atualmente a publicacao usa save e nenhum endpoint expoe essa alteracao.

## Roteiro condicional de homologacao local

### A. Consultas e testes antes de tocar analise_dev

No PowerShell do repositorio:

```powershell
. .\.venv\Scripts\Activate.ps1
. .\scripts\local-postgres-env.ps1
python -B manage.py shell -c "from django.conf import settings; d=settings.DATABASES['default']; print({k:d.get(k) for k in ['ENGINE','NAME','HOST','PORT']}); print('TEST:',d.get('TEST',{}).get('NAME')); print('FINALIZATION_ENABLED:',settings.REPORT_FINALIZATION_ENABLED)"
python -B manage.py check
python -B manage.py makemigrations --check --dry-run
python -B manage.py showmigrations signaling
python -B manage.py migrate signaling 0012 --plan
python -B manage.py sqlmigrate signaling 0012
```

So consultas. Esperado: PostgreSQL em 127.0.0.1, analise_dev, TEST test_analise_dev,
flag False, 0011 aplicada e 0012 pendente. Se host/nome/usuario nao forem os locais
aprovados, ou o plano incluir operacoes inesperadas, PARAR. Nao imprimir DATABASES
inteiro, cookies ou headers. As credenciais permanecem na sessao que executou o
script; nenhum arquivo de credenciais deve ser criado.

Depois das correcoes, confirmar test_analise_dev exclusivamente descartavel e
sem outra sessao usando-o. Este comando cria/migra/limpa/destroi SOMENTE o banco
de testes confirmado, sem --noinput e sem --keepdb:

```powershell
python -B manage.py test `
  signaling.test_report_finalization_postgresql `
  signaling.test_report_draft_concurrency `
  signaling.test_reservation_concurrency `
  signaling.test_reservations.PostgreSQLReservationContractTests `
  --verbosity 2
$LASTEXITCODE
```

Antes de acrescentar os testes propostos, a coleta esperada e 66 (37+29), zero
skips e exit code 0. Depois de R1/R2 a contagem aumentara. Rodar tambem os testes
unitarios/integrais de armazenamento, snapshot, DOCX e PDF:

```powershell
python -B manage.py test signaling.test_report_finalization signaling.test_report_finalization_pdf signaling.test_report_generator signaling.test_report_download signaling.test_pdf_conversion signaling.test_pdf_integration --verbosity 2
$LASTEXITCODE
```

Distinguir conversor simulado nos testes transacionais de LibreOffice REAL nas
integracoes PDF. Nao tratar skip de dependencia como sucesso da conversao real.

### B. Backup e migration MANUAL, apenas apos aprovar R1/R2

Passos NAO executados pelo Codex. Conferir novamente analise_dev local e ter
backup recuperavel. Se pg_dump ja estiver instalado, exemplo de backup (grava
somente arquivo de backup fora do repositorio; pede senha sem inclui-la no comando):

```powershell
$backupDir = Join-Path $env:LOCALAPPDATA 'AnaliseSinalizacao\backups-homologacao'
New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
$backupFile = Join-Path $backupDir ('analise_dev-antes-0012-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.dump')
pg_dump --host=$env:POSTGRES_HOST --port=$env:POSTGRES_PORT --username=$env:POSTGRES_USER --dbname=analise_dev --format=custom --file=$backupFile --password
$LASTEXITCODE
```

Se pg_dump nao estiver disponivel, usar a ferramenta administrativa ja aprovada,
sem instalar programas automaticamente. Verificar que o backup foi concluido e
pode ser restaurado. Se ja houver artefatos privados, copiar tambem esse diretorio
em janela consistente. Nao executar restore sobre o banco de desenvolvimento.

Somente apos revisao/backup e autorizacao local da pessoa operadora:

```powershell
python -B manage.py migrate signaling 0012
python -B manage.py showmigrations signaling
```

Esse e o passo que MODIFICA O SCHEMA de analise_dev. Nao faz deploy e nao deve
ser executado contra outro ambiente. Nao conceder permissao ao grupo analista.

### C. Configuracao temporaria e usuario exclusivamente de testes

Apenas variaveis deste PowerShell, sem editar .env/settings:

```powershell
$env:REPORT_FINALIZATION_ENABLED = 'true'
$env:REPORT_PRIVATE_ROOT = Join-Path $env:LOCALAPPDATA 'AnaliseSinalizacao\reports-homologacao'
New-Item -ItemType Directory -Path $env:REPORT_PRIVATE_ROOT -Force | Out-Null
icacls $env:REPORT_PRIVATE_ROOT
# Opcional se o executavel ja instalado nao for localizado automaticamente:
# $env:REPORT_LIBREOFFICE_EXECUTABLE = 'C:\Program Files\LibreOffice\program\soffice.com'
python -B manage.py shell
```

New-Item cria a pasta privada; icacls apenas consulta. Conferir ACL: nenhum acesso
amplo indevido; chmod nao substitui ACL Windows. Nao adicionar alias/location no
Nginx nem colocar a pasta em MEDIA/STATIC/repo. O caminho concreto precisa passar
por PrivateReportStorage. Nao usar producao. O shell abaixo escreve apenas em
analise_dev local depois das verificacoes; nao colar sua saida com segredos.

No shell Django, executar este bloco (nome exclusivo; se existir, parar e escolher
outro, sem alterar uma conta existente):

```python
from getpass import getpass
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission, Group
from signaling.report_storage import PrivateReportStorage
assert settings.DEBUG
assert settings.DATABASES['default']['ENGINE'] == 'django.db.backends.postgresql'
assert settings.DATABASES['default']['NAME'] == 'analise_dev'
assert settings.DATABASES['default']['HOST'] == '127.0.0.1'
assert settings.REPORT_FINALIZATION_ENABLED
storage = PrivateReportStorage()
finalize_perm = Permission.objects.get(content_type__app_label='signaling', content_type__model='technicalreport', codename='finalize_technicalreport')
assert not Group.objects.filter(name='analista', permissions=finalize_perm).exists(), 'STOP: revisar concessao ja existente em analista'
User = get_user_model()
assert not User.objects.filter(username='homologacao_etapa6').exists()
password = getpass('Senha EXCLUSIVA da conta sintetica: ')
user = User.objects.create_user(username='homologacao_etapa6', password=password, first_name='Autor', last_name='Sintetico')
del password
point_perms = [Permission.objects.get(content_type__app_label='signaling', content_type__model='signalingpoint', codename=code) for code in ('view_signalingpoint','add_signalingpoint','change_signalingpoint','generate_signaling_report')]
user.user_permissions.set([*point_perms, finalize_perm])
assert not user.is_staff and not user.is_superuser and not user.groups.exists()
print('Usuario sintetico criado; permissoes diretas explicitas, sem alterar analista.')
```

Add/change servem apenas para preparar waypoint/rascunho sinteticos pelos endpoints
normais. Finalizacao em si exige view/report/finalize. Nenhuma permissao de delete,
staff ou superuser e necessaria. Nunca guardar a senha no arquivo de roteiro.

### D. Geracao sintetica pelo backend real, com CSRF e reserva normais

Ainda no shell Django: o bloco abaixo usa Client LOCAL em processo, login real,
CSRF ativo, endpoints normais e LibreOffice REAL; nao usa mocks, nao liga servidor,
nao chama producao e nao e uma nova interface do produto. Cria uma sessao de
homologacao com dados ficticios e preserva os registros/artefatos no banco local.

Colar o bloco de uma vez; a reserva nao e renovada artificialmente. Se o TTL
expirar, esperar erro controlado e retomar apenas pelo protocolo normal. Este
ensaio curto nao comprova o heartbeat do navegador; verificar o mapa separadamente.

```python
from datetime import datetime
from io import BytesIO
from uuid import uuid4
from django.test import Client
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image
from signaling.models import ReportFinalizationAttempt
from signaling.report_snapshots import OFFICIAL_TIMEZONE, digest
from signaling.surveys import ANALYSIS_SESSION_KEY

client = Client(enforce_csrf_checks=True, HTTP_HOST='127.0.0.1')
assert client.login(username='homologacao_etapa6', password=getpass('Senha da conta sintetica: '))
assert client.get(reverse('login')).status_code == 200
csrf = client.cookies[settings.CSRF_COOKIE_NAME].value

def post_json(url, body, proof=None):
    return client.post(url, body, content_type='application/json', HTTP_X_CSRFTOKEN=csrf, **(proof or {}))

response = post_json(reverse('signaling:create-point'), {'latitude': '-21.170000', 'longitude': '-47.810000', 'status': 'INCOMPLETE'})
assert response.status_code == 201
point_id = response.json()['id']
response = post_json(reverse('signaling:acquire-reservation', args=[point_id]), {'interaction_id': str(uuid4())})
assert response.status_code == 201
grant = response.json()
proof = {'HTTP_X_WAYPOINT_TOKEN': grant['token'], 'HTTP_X_WAYPOINT_INTERACTION': grant['interaction_id'], 'HTTP_X_WAYPOINT_GENERATION': str(grant['generation'])}
del grant
now = datetime.now(OFFICIAL_TIMEZONE)
fields = {'inspection_address':'Via FICTICIA - homologacao Etapa 6', 'inspection_date':now.date().isoformat(), 'inspector_name':'Vistoriador sintetico', 'technical_analysis':'Analise tecnica inteiramente sintetica. Sem sinistros reais.', 'pgts':['Escola ficticia','Unidade ficticia']}
response = post_json(reverse('signaling:report-draft', args=[point_id]), {'expected_revision':0, 'fields':fields}, proof)
assert response.status_code == 200
revision = response.json()['revision']
session = client.session
session[ANALYSIS_SESSION_KEY] = {'view_mode':'individual', 'analysis_id':'homologacao-etapa6', 'map_data':[{'id':'SINTETICO-ETAPA6-001', 'latitude':-21.17, 'longitude':-47.81, 'year':now.year, 'month':now.month, 'category':'collision', 'date':now.strftime('%d/%m/%Y'), 'accident_type':'Colisao ficticia', 'record_type':'SINISTRO NAO FATAL', 'street':'Via ficticia de homologacao', 'modes':[]}]}
session.save()
original_photos = []
for color in ('red','blue'):
    stream = BytesIO()
    Image.new('RGB', (160,100), color).save(stream, 'PNG')
    original_photos.append(stream.getvalue())

key = str(uuid4())
url = reverse('signaling:finalize-report', args=[point_id]) + '?analysis=homologacao-etapa6'

def payload():
    return {'idempotency_key':key, 'expected_revision':str(revision), 'photos':[SimpleUploadedFile('foto-sintetica.png', data, content_type='image/png') for data in original_photos]}

try:
    response = client.post(url, payload(), HTTP_X_CSRFTOKEN=csrf, **proof)
    result = response.json()
    print({'http':response.status_code, 'code':result.get('code'), 'state':result.get('state')})
    assert response.status_code == 201, 'Se falhou, preservar attempt e investigar codigo sem imprimir proof'
    attempt = ReportFinalizationAttempt.objects.select_related('version__report').get(pk=result['attempt_id'])
    version = attempt.version
    assert attempt.state == 'FINALIZED' and version.finalized_at
    assert digest(version.snapshot) == version.snapshot_sha256
    assert version.author_id == user.pk
    assert version.report.year == version.issued_at.astimezone(OFFICIAL_TIMEZONE).year
    assert version.artifacts.count() == 4
    for artifact in version.artifacts.order_by('kind','ordinal'):
        data = storage.read(artifact)
        print({'kind':artifact.kind, 'ordinal':artifact.ordinal, 'size':len(data), 'integrity':'OK'})
    photos = list(version.artifacts.filter(kind='PHOTO').order_by('ordinal'))
    assert [storage.read(a) for a in photos] == original_photos
    repeated = client.post(url, payload(), HTTP_X_CSRFTOKEN=csrf, **proof)
    assert repeated.status_code in (200,201)
    assert repeated.json()['report_id'] == result['report_id']
    assert version.artifacts.count() == 4
    print({'number':result['number'], 'report_id':result['report_id'], 'attempt_id':result['attempt_id']})
finally:
    release = post_json(reverse('signaling:release-reservation', args=[point_id]), {}, proof)
    print({'release_http':release.status_code})
    del proof
```

Nao imprimir grant, proof, cookies, senha ou a sessao. Se falhar, guardar somente
attempt_id/codigo, preservando dados. Uma intencao nova consome novo numero: nao
rodar este bloco repetidamente sem decidir o que esta sendo testado.

### E. Conferir artefatos e documento sem novo endpoint

Ainda no shell (somente se o bloco anterior finalizou):

```python
from docx import Document
from pypdf import PdfReader
pdf_artifact = version.artifacts.get(kind='PDF')
docx_artifact = version.artifacts.get(kind='DOCX')
pdf = storage.read(pdf_artifact)
word = storage.read(docx_artifact)
assert len(PdfReader(BytesIO(pdf), strict=True).pages) > 0
assert Document(BytesIO(word)).paragraphs
print('Estrutura PDF/DOCX e hashes aprovados.')
```

Para inspecao visual, localizar os caminhos privados APENAS no shell administrativo
local por storage.root / artifact.storage_key e abrir com visualizador do SO.
Nao publicar caminhos/URLs nem copiar arquivos para MEDIA/STATIC/repo.
Conferir titulo, numero, autor autenticado (nao o vistoriador), data Sao Paulo,
analise final, PGTs, linha sintetica, fotos vermelha/azul na ordem, tabelas,
acentuacao, fontes, margens e paginas em branco. Nenhuma assinatura digital e
atribuida. O nome amigavel esta em download_name, nao e a chave fisica do arquivo.

A independencia apos exclusao de waypoint/rascunho esta coberta nos testes
PostgreSQL aprovados. Nao excluir registros do desenvolvimento para provar isso.
A ausencia da sessao pode ser verificada nesta sessao sintetica removendo somente
ANALYSIS_SESSION_KEY e renderizando version.snapshot com as fotos arquivadas;
nenhum acesso ao ponto/rascunho e necessario.

Para o navegador, iniciar runserver nesta configuracao temporaria, entrar com a
conta sintetica, usar somente dados ficticios e gerar DOCX pela rota existente.
Confirmar autosave e renovacoes normais no Network. Nao ha botao de finalizacao
nesta etapa: o exercicio da API foi feito no bloco local acima. Nao criar heartbeat
extra para a prova nem extrair headers secretos para colar em arquivos/chat.

### F. Falhas, reconciliacao e encerramento

Executar casos de conversor indisponivel/timeout/expiracao/revogacao/interrupcao
na suite isolada, nao danificar arquivos validos para simular falhas em analise_dev.
Depois de R1/R2 corrigidos, verificar que retry conserva snapshot/numero e que
somente a execucao vigente publica. Durante homologacao persistente, comando
permitido inicialmente e somente leitura:

```powershell
python -B manage.py reconcile_report_finalizations
```

Nao executar --delete-orphans nem --mark-interrupted ate revisar os casos e os
alvos. O dry-run pode identificar uma tentativa vencida mas nunca a finaliza.
Backup precisa incluir DB e raiz privada; testar restauracao em ambiente separado,
sem sobrescrever desenvolvimento nem tentar renumerar o historico.

Ao terminar, sair do shell/parar runserver. Remover apenas variaveis criadas para
a homologacao; se ja existiam antes, restaurar seus valores anteriores em vez de
apaga-los. Nao excluir bancos, arquivos, relatorios ou contadores. Pode desativar
somente o usuario sintetico apos confirmar seu nome/id, preservando autoria.
A funcionalidade deve voltar a False em novo processo sem override temporario.

Producao continua bloqueada: validar Ubuntu/LibreOffice/fontes, Nginx efetivo,
ACL/backup/restauracao e capacidade para manter renovacoes durante conversao.
Um worker Gunicorn sincrono pode bloquear heartbeat e expirar reserva; nao elevar
apenas timeout e considerar resolvido. Nenhuma infraestrutura ou fila foi alterada.
