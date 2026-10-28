# Etapa 7B - biblioteca de relatorios oficiais

## Escopo entregue

GET /signaling/reports/, nome de URL signaling:report-library. Pagina Django
renderizada no servidor; sem novo JavaScript, dependencias ou endpoints de
detalhes/downloads/historico/finalizacao. Bootstrap reutiliza a mesma versao e
integridade ja usadas no projeto. Nenhuma migration adicional e necessaria.

A precondicao PostgreSQL da 7A foi considerada aprovada por confirmacao explicita
do usuario nesta conversa. Nao foi reexecutada em PostgreSQL pelo Codex.

Arquivos novos: signaling/report_library.py; signaling/report_library_views.py;
templates/signaling/report_library.html; static/css/report-library.css;
signaling/test_report_library.py; este documento.
Arquivos alterados: signaling/report_read_access.py (helper publico de checagem,
mesma politica); signaling/urls.py; templates/includes/navbar.html;
static/css/app-shell.css (estilo do novo link); docs/reference/signaling-and-reports.md.

## Autorizacao e dados

Anonimos sao direcionados ao login; autenticados sem view_official_reports recebem
403 antes de qualquer consulta aos relatorios. Somente download/finalizacao nao
concede leitura. Navbar usa a permissao para mostrar o link; a verificacao efetiva
ocorre novamente no servidor, pela politica centralizada e usuario ativo atual.
Respostas sao privadas/no-store e variam por Cookie. Nenhum grupo e alterado.

O queryset autorizado e criado ANTES dos filtros, contagem e paginacao. Cada
relatorio aparece uma vez; a maior versao com finalizacao oficial fornece emissao,
autoria e numero da versao. Uma versao posterior pendente/falha nao substitui a
ultima publicada. Numero precisa estar atribuido, versao finalizada e tentativa
em FINALIZED, conforme 7A. Nenhuma reserva ou flag de conversao e exigida.

A tabela mostra numero, emissao em America/Sao_Paulo, full_name/username congelados,
ID historico do waypoint e versao. Nao usa FK atual de autor/waypoint para exibir
ou filtrar. Snapshots, tentativas, caminhos privados e credenciais nao sao carregados
na listagem. Subqueries trazem somente metadados, sem consultas por linha. Nenhum
arquivo e aberto ou gerado. A selecao da ultima versao ocorre antes de filtrar.

## Filtros e paginacao

Todos via GET e validados por formulario Django; ORM parametrizado, sem SQL
construido com dados do navegador:

- number: numero completo RTSV-AAAA-NNNN, com ano/sequencia positivos;
- year: ano do NUMERO oficial, nao necessariamente o ano da ultima versao;
- issued_from / issued_to: datas AAAA-MM-DD, inclusivas em America/Sao_Paulo;
- author: parte do nome completo ou username HISTORICO da ultima versao publicada;
- waypoint: ID positivo do waypoint HISTORICO;
- page: pagina positiva; 20 registros fixos por pagina.

Filtros combinam por AND. Intervalos invertidos, valores invalidos e parametros
repetidos de filtro retornam 400 com mensagens, sem executar consulta de relatorios.
Filtros validos sem correspondencia retornam 200 com resultado vazio. Pagina
invalida/inexistente retorna 404. Os links preservam filtros e substituem page;
parametros desconhecidos nao sao propagados.

Ordenacao: emissao da ultima versao publicada decrescente, ano/sequencia oficiais
decrescentes e UUID para desempate deterministico. O total conta relatorios, nao
versoes. Todos os textos historicos sao escapados pelo template.

## Validacao executada

16 testes novos da biblioteca, cobrindo autenticacao/permissao, flag false,
ultima versao publicada, ausencia de duplicacao, ordenacao, filtros individuais e
combinados, datas na virada de ano UTC/Sao Paulo, erros de filtros/paginas,
paginacao, exclusoes historicas, navbar, escaping e ausencia de N+1/snapshots.
A expectativa inicial de teste para data final isolada foi corrigida: esse filtro
inclui naturalmente todos os relatorios anteriores ao limite, nao apenas aquele
da data exata. O codigo do filtro nao precisou de alteracao para esse caso.

Regressao local: 122 testes aprovados, zero falhas/erros/skips (biblioteca, 7A,
snapshots/reconciliacao, DOCX, autorizacao e accounts), usando somente banco de
testes EM MEMORIA criado/destruido pelo Django. Check e makemigrations --check
--dry-run aprovados. Isso nao substitui a validacao PostgreSQL desta nova query.
Nenhuma migration aplicada em banco existente. Nenhuma alteracao em producao.

## Homologacao local segura

No PowerShell autenticado, SEM imprimir senhas:

```powershell
. .\.venv\Scripts\Activate.ps1
. .\scripts\local-postgres-env.ps1
python -B manage.py shell -c "from django.conf import settings; d=settings.DATABASES['default']; assert d['ENGINE']=='django.db.backends.postgresql'; print({k:d.get(k) for k in ['ENGINE','NAME','HOST','PORT']}); print('TEST:',d.get('TEST',{}).get('NAME')); print('FINALIZATION:',settings.REPORT_FINALIZATION_ENABLED)"
python -B manage.py check
python -B manage.py makemigrations --check --dry-run
python -B manage.py showmigrations signaling
```

Conferir analise_dev/host local e test_analise_dev descartavel, sem outra sessao
usando-o. Se o destino nao estiver confirmado, parar. O comando abaixo cria,
migra e destroi SOMENTE esse banco de testes confirmado, sem --noinput/--keepdb:

```powershell
python -B manage.py test `
  signaling.test_report_library `
  signaling.test_report_read_access `
  signaling.test_report_finalization_postgresql `
  signaling.test_report_draft_concurrency `
  signaling.test_reservation_concurrency `
  signaling.test_reservations.PostgreSQLReservationContractTests `
  signaling.test_report_reconciliation `
  --verbosity 2
$LASTEXITCODE
```

Esperado: 109 testes (16 novos + 93 da rodada 7A), zero skips inesperados, exit 0.
Credenciais PostgreSQL nao estavam disponiveis ao Codex; nao houve tentativa de
contornar autenticacao. Nenhuma instalacao de browser/automacao foi realizada.

Para navegador: a 0013 da 7A deve estar aplicada MANUALMENTE no desenvolvimento
aprovado, e uma conta de testes deve ter view_official_reports explicitamente.
Se a migration/permissao ainda faltar, nao executar migrate nem conceder ao grupo
analista automaticamente. A 7B nao exige outra migration nem habilitar finalizacao.

```powershell
python -B manage.py runserver
```

Manter REPORT_FINALIZATION_ENABLED=false (remover somente overrides temporarios
criados pelo operador, preservando valores que ja existiam). Abrir
http://127.0.0.1:8000/signaling/reports/ autenticado com a conta de leitura:

1. Conferir numero/emissao/autoria/waypoint/versao do relatorio sintetico existente.
2. Testar cada filtro, combinacoes e Limpar filtros. Data final sozinha deve incluir
   todas as emissoes anteriores ao limite. Conferir fuso Sao Paulo.
3. Com mais de 20 registros SINTETICOS, navegar entre paginas mantendo filtros.
   Os testes ja produzem esse conjunto exclusivamente no banco descartavel;
   nao criar registros reais em massa apenas para demonstrar paginacao.
4. Conferir link Relatorios no mapa/na biblioteca e retorno ao mapa. Conta sem
   permissao nao deve ver o link e deve receber 403 ao usar a URL diretamente.
   Anonimo deve ir ao login. Download/finalizacao isolados nao liberam a pagina.
5. Inspecionar em larguras 320, 768 e 1280px: formulario em uma/duas/tres colunas,
   tabela com rolagem horizontal localizada, navbar utilizavel e foco por teclado.
6. Conferir que nao ha links de download/detalhes ou botoes de finalizacao e que
   a pagina funciona sem reserva/analise em sessao. Nao excluir dados de
   desenvolvimento para testar historico; os testes isolados cobrem exclusoes.

Validacao visual real em navegador e PostgreSQL desta nova etapa permanecem
pendentes ate essa homologacao. Nenhuma implantacao ou avancos para 7C.

## Revisao da retomada

Estado existente preservado: URL, view, politica 7A, queryset ORM, template e
navbar estavam integrados. Nenhuma reimplementacao ou migration foi necessaria.
Acrescentado teste que impede filtros sobre autores/emissoes de versoes antigas
ou pendentes: a selecao usa exclusivamente a ultima versao publicada.
Reexecutados 122 testes de regressao com sucesso e, apos essa adicao, os 16 testes
da biblioteca tambem passaram (123 testes distintos cobertos, zero skips).
Check, diff --check e verificacao de migrations sem alteracoes aprovados.
As execucoes locais usaram banco de testes SQLite em memoria; a senha PostgreSQL
nao estava disponivel ao processo. PostgreSQL e inspecao visual continuam pendentes.
Arquivos preexistentes da Etapa 6/7A, .gitignore e folder.svg foram preservados.

## Ajustes de apresentacao apos homologacao PostgreSQL

Usuario confirmou 109 testes PostgreSQL aprovados e homologacao visual inicial.
A tabela prioriza author_identity.username congelado na versao, originado da
identidade preservada na finalizacao. Sem username, usa full_name historico;
sem ambos, mostra "Nao informado". Esse fallback nao recupera usernames ausentes.
Nenhuma consulta ao usuario atual, alteracao de snapshot ou mudanca nos filtros:
o filtro de autor continua buscando nome e username historicos.
Navbar reutiliza folder.svg com rotulo acessivel; retorno ao mapa usa estilo
secundario com seta decorativa. O fluxo atual do waypoint somente gera DOCX;
nao publica relatorios. A integracao de finalizacao permanece fora desta tarefa.
