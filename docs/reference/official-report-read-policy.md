# Etapa 7A - politica centralizada de leitura

## Escopo

Somente autorizacao e querysets reutilizaveis em signaling/report_read_access.py.
Sem novas URLs, views, interface, downloads de bytes ou mudancas no armazenamento,
no protocolo de reservas ou na transacao de finalizacao. APIs da Etapa 6 permanecem
inalteradas, inclusive sua propria flag/permissoes; ainda nao passam por esta nova
camada. A integracao de futuros endpoints fica para subetapas aprovadas posteriores.

## Permissoes

- signaling.view_official_reports: ler relatatorios e versoes PUBLICADOS de forma
  compartilhada, sem exigir view_signalingpoint ou finalize_technicalreport.
- signaling.download_official_reports: acessar metadados de artefatos publicados
  somente quando TAMBEM houver view_official_reports. Nao implementa download.
- Tentativas: continuam exigindo view_signalingpoint, generate_signaling_report e
  finalize_technicalreport, limitadas ao requested_by do proprio solicitante.
  A permissao da biblioteca nao concede acesso a tentativas alheias nao publicadas.

A migration 0013_official_report_read_permissions altera somente as opcoes Meta
por AlterModelOptions, preservando default_permissions=() e finalize_technicalreport.
As novas Permission sao criadas pelo post_migrate do Django; nenhuma associacao
com grupos/usuarios e criada. Sem RunPython, RunSQL, alteracao de tabelas ou dados
historicos. Nao aplicar automaticamente em analise_dev ou producao.

Cada chamada consulta um usuario ativo atual e permissoes atuais, sem reutilizar
caches de permissoes de objetos antigos. is_staff nao implica acesso; superusuarios
ativos mantem a semantica administrativa padrao de has_perms do Django. Nao ha
bypass especial adicionado. Permissoes de grupos sao aditivas como no restante
projeto; concessoes existentes/manuais continuam sob responsabilidade administrativa.

## Contrato para futuros consumidores

- official_reports_for(user): relatorios com pelo menos uma versao publicada,
  sem duplicar relatorios quando houver mais de uma versao publicada.
- official_versions_for(user): somente versoes publicadas.
- official_artifacts_for(user): somente metadados dos artefatos de versoes
  publicadas; exige visualizacao E download, inclusive para obter storage_key.
- own_finalization_attempts_for(user): tentativas do solicitante com as permissoes
  atuais de finalizador. Inclui seus estados correntes, sem expor tentativas alheias.
- get_official_report, get_official_version, get_official_artifact e
  get_own_finalization_attempt: buscas sobre esses escopos. O acesso ao artefato
  fica vinculado a ID do relatorio E numero da versao, alem do ID do artefato.

Usuarios sem autorizacao recebem queryset .none(): contagens e paginacao nao
consultam objetos fora do escopo. Getters retornam o MESMO Http404 para ausencia,
objeto fora de escopo ou identificador malformado. Nenhum endpoint e criado aqui;
nao ha novo contrato HTTP de login/redirecionamento nesta etapa.

Uma versao publicada exige, simultaneamente:
1. report.number_assigned_at preenchido;
2. version.finalized_at preenchido;
3. tentativa associada em FINALIZED.

Arquivos ausentes/corrompidos nao apagam a existencia historica da publicacao.
O escopo de artefatos exige os registros; integridade fisica continua sendo
responsabilidade do armazenamento e do futuro endpoint protegido.

Nao se exige reserva ou REPORT_FINALIZATION_ENABLED. Nenhuma leitura adquire,
renova, libera reserva ou consulta a sessao original. SET_NULL do waypoint/autor/
solicitante preserva os registros publicados, snapshot e identidade historica.

O consumidor deve comecar PELO queryset autorizado, antes de filtrar, contar,
paginar, buscar versoes ou artefatos. Nao buscar objeto com objects.get para depois
verificar acesso. Nao usar queryset em cache entre requisicoes. Nao entregar
models/snapshots/chaves inteiros como JSON: a serializacao segura sera definida
nas futuras views. Esta e uma fronteira da aplicacao, nao RLS nem protecao contra
ORM/SQL administrativo arbitrario.

## Testes e validacao local

Suite portavel: signaling.test_report_read_access, 18 casos. Cobre matriz de
permissoes, estados de publicacao, ausencia de reserva/reserva de outro usuario,
flag desabilitada, historico apos exclusoes, tentativas privadas, artefatos ligados
a relatorio/versao, revogacao apesar de cache, grupos explicitos e cadastro publico.
Tambem verifica que consultas negadas nao pesquisam tabelas de relatorios e que
leituras nao modificam versoes/tentativas/rascunhos.

A execucao local usa apenas banco de testes SQLite EM MEMORIA, nunca como prova
de PostgreSQL. Credenciais PostgreSQL nao disponiveis ao processo Codex. Para
validacao real, no PowerShell autenticado do operador:

```powershell
. .\.venv\Scripts\Activate.ps1
. .\scripts\local-postgres-env.ps1
python -B manage.py shell -c "from django.conf import settings; d=settings.DATABASES['default']; assert d['ENGINE']=='django.db.backends.postgresql'; print({k:d.get(k) for k in ['ENGINE','NAME','HOST','PORT']}); print('TEST:',d.get('TEST',{}).get('NAME'))"
python -B manage.py check
python -B manage.py makemigrations --check --dry-run
python -B manage.py showmigrations signaling
python -B manage.py migrate signaling 0013 --plan
```

Esses comandos sao consultas. Conferir host local, analise_dev e test_analise_dev;
nao imprimir DATABASES inteiro ou senhas. Nao executar migrate sem --plan nesta
etapa. Confirmar test_analise_dev exclusivamente descartavel e nao usado por outra
sessao. O comando abaixo cria/migra/destroi SOMENTE o banco temporario confirmado:

```powershell
python -B manage.py test `
  signaling.test_report_read_access `
  signaling.test_report_finalization_postgresql `
  signaling.test_report_draft_concurrency `
  signaling.test_reservation_concurrency `
  signaling.test_reservations.PostgreSQLReservationContractTests `
  signaling.test_report_reconciliation `
  --verbosity 2
$LASTEXITCODE
```

Esperado: 93 testes (18 novos + 75 da validacao anterior), zero skips inesperados,
exit code 0. Nao usar --noinput ou --keepdb automaticamente. Se o destino nao
estiver confirmado como local/descartavel, parar. Nenhum teste desse comando deve
ser substituido por simulacao de locks SQLite. A suite nova nao abre arquivos.

A Etapa 7B depende de aprovacao separada. A finalizacao continua false por padrao;
nenhum endpoint publico de biblioteca existe e nenhuma permissao foi concedida
pelo codigo desta etapa.


## Evidencias da execucao no Codex

- Nova suite: 18 testes aprovados em banco temporario em memoria.
- Regressao focada (politica, snapshots, reconciliacao, DOCX, autorizacao e
  accounts): 107 testes aprovados, zero falhas/erros/skips.
- Django check e makemigrations --check --dry-run: aprovados, sem divergencias.
- PostgreSQL real: pendente por ausencia de credenciais no processo; nenhuma
  tentativa de contornar autenticacao. Usar o comando de 93 testes acima.
- A 0013 foi exercitada somente no banco temporario dos testes. Nenhuma migration
  aplicada em analise_dev/producao. Sem alteracao do armazenamento privado,
  reservas, transacao de finalizacao, URLs ou templates nesta etapa.
