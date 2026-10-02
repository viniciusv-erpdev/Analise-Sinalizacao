# Estabilização do fluxo principal — 30/09/2026

## Estado inicial e componentes

Working tree inicialmente limpo, branch `vinicius`, commit `922e5b7`.
Foram lidos `docs/codex-handoff.md` e `docs/AGENTS.md`. O handoff ainda
descreve como locais alterações que já estão commitadas.

Fluxo conferido no código:

- `accidents/services.py`: leitura CSV, consolidação, deduplicação e exclusão de ilesos.
- `accidents/normalizer.py`, `analysis/pipeline.py`, `analysis/geography.py`:
  normalização, município/coordenadas e seleção do modo.
- `analysis/occurrences.py`, `spatial.py`, `criteria.py`, `periods.py`,
  `map_data.py`: ocorrências, clusters, critérios, períodos e payloads.
- `accidents/views.py`: POST/Redirect/GET e estado de análise na sessão.
- `templates/map.html`, `static/js/map.js`, `individual_filters.js`,
  `signaling.js`: payload JSON, filtros e links de relatório.
- `signaling/views.py`, `models.py`, `surveys.py`, `report_filters.py`:
  waypoint, raio persistido, seleção de sinistros e relatório HTML.
- `signaling/forms.py`, `templates/signaling/report.html`,
  `signaling/templates/signaling/widgets/pgt_list.html`,
  `static/js/report_characterization.js`: caracterização e PGTs transitórios.
- `signaling/overpass.py`: integração HTTP auxiliar.
- `signaling/report_generator.py`: DOCX em memória a partir do formulário validado.

## Auditoria anterior à criação dos testes

| Testes existentes | Cobertura | Lacuna encontrada |
| --- | --- | --- |
| `accidents/tests.py` | CSV, encoding, deduplicação, nulos/zeros, ilesos, normalização, pipelines, períodos, payloads e critérios históricos | Uploads HTTP geralmente mockam o pipeline; mapa vazio também usa mocks |
| `signaling/tests.py`, `test_surveys.py` | CRUD de waypoints/intervenções, raio, Haversine e GET do relatório | Dados de análise são preparados manualmente, sem upload real |
| `test_report_filters.py`, `test_report_download.py` | Parâmetros repetidos, filtros, download, formulários, fotos e rejeição de análise antiga | Sessões montadas manualmente; transporte de filtros para Word testado com gerador mockado |
| `test_report_generator.py` | DOCX, XML, estilos, gráficos, fotos e conteúdo | Entrada direta no gerador, sem os dados reais do upload |
| `test_characterization.py` | Card, validação, texto/Unicode, Word e não persistência | Sessão artificial; não percorre a sequência falha do endpoint PGT → relatório |
| `test_overpass.py`, `test_pgt_endpoint.py` | Categorias, node/way/relation, erros HTTP, CSRF, raio e respostas | Falhas testadas separadamente do upload/HTML/Word |
| Testes Node de filtros e caracterização | Lógica dos filtros, query e eventos da lista PGT com DOM mínimo | Sem navegador real, Leaflet ou cliques nos controles da página completa |

Os arquivos em `scripts/test_*.py` incluem scripts exploratórios que leem CSVs
reais. Não foram tratados como substitutos da suíte automatizada de integração.

Regressões que poderiam escapar: alteração de campos/tipos entre CSV, payload e
sessão; perda de alguma dimensão dos filtros no DOCX real; uso de raio antigo
após atualização; falha do relatório depois de erro PGT; permanência dos dados de
upload anterior; erro quando a preparação produz zero registros.

## Incidente TemplateDoesNotExist

O widget `PGTListWidget.template_name`, em `signaling/forms.py`, referencia
`signaling/widgets/pgt_list.html`. O arquivo existe e está versionado no local
convencional: `signaling/templates/signaling/widgets/pgt_list.html`.

O relatório renderiza `{{ form.pgts }}`, sem `{% include %}`. O JavaScript
cria as linhas novas no DOM; não carrega o partial por HTTP.

`signaling` está em `INSTALLED_APPS`; `APP_DIRS=True`; o renderizador padrão
de formulários procura templates nos apps. A configuração não precisa mudar.

Na investigação anterior desta conversa, o servidor iniciou antes de existir
`signaling/templates`. O Django usa cache em `get_app_template_dirs()`; aquele
processo conservou uma lista que não incluía o novo diretório. O mecanismo foi
reproduzido, e recarregar o processo resolveu sem alteração de conteúdo.

A suíte já possuía GETs que renderizavam o widget. Eles passaram porque iniciavam
processos depois de o diretório existir. Não reproduziam o ciclo de vida do
`runserver` já ativo. Um arquivo realmente ausente, nome errado ou caminho
incompatível seria detectado por esses GETs.

O novo teste exige renderização de `signaling/report.html` e do widget após
upload real, inclusive com coleção vazia. Isso não garante a renovação do cache
de outro processo. Após criar novos diretórios de templates, reiniciar o servidor
e fazer um GET com análise individual disponível continua sendo uma verificação
operacional necessária.

## Testes de integração adicionados

Arquivo: `accidents/test_main_flow.py`.

1. Dois CSVs → deduplicação/ilesos → preparação individual → sessão → JSON do mapa.
   Verifica primeira ocorrência, zeros, município/coordenadas, tipo de via/registro,
   categorias, gravidade, períodos e contadores.
2. CSV → modo elegível real. Uma região fica abaixo do limiar; duplicata ou ileso
   indevidamente incluído tornaria essa região elegível. A outra região é elegível.
3. Upload cujos registros são todos excluídos → mapa vazio nos dois modos.
4. Upload → criação HTTP de waypoint → relatório com filtros repetidos, card/widget
   e raio; alteração HTTP do raio repercute no relatório e no payload do mapa.
5. HTML e DOCX reais compartilham os mesmos IDs filtrados; caracterização e lista
   final chegam ao Word; XML é válido; banco e sessão não recebem caracterização.
6. Timeout HTTP mockado → endpoint PGT 503 → HTML 200 → Word com PGT manual.
7. Overpass sem resultados → HTML e formulário inválido com lista vazia renderizam;
   Word continua funcionando com campos opcionais vazios.
8. Novo upload substitui a análise e invalida URLs com identificador anterior,
   preservando o waypoint.

A sessão dos novos testes é criada pelo upload, não preenchida artificialmente.
O polígono municipal versionado e o pipeline são reais. Apenas a chamada HTTP
externa é mockada, incluindo um bloqueio explícito contra acessos inesperados.
Não foi adicionada dependência.

## Bugs e correções mínimas

### Asserção obsoleta do relatório

Antes das alterações, a suíte executou 212 testes: 211 passaram e um falhou.
`test_html_shows_chart_accidents_and_intervention_details` exigia `Status:`,
mas o template exibe a condição diretamente. Foi alterada apenas essa asserção
para verificar `<strong>Adequada</strong>`, mantendo as demais verificações.

### Pipeline elegível vazio

O novo teste de exclusão total falhou no modo `clusters` com:

```text
ValueError: You are trying to merge on float64 and object columns for key 'latitude'.
```

`build_occurrence_points()` criava um DataFrame vazio cujas coordenadas eram
`object`, enquanto os sinistros preparados usavam `float64`. A associação
posterior falhava. Os testes anteriores de upload vazio/exclusão mockavam essa
etapa e não detectavam o erro.

Correção em `analysis/occurrences.py`: no retorno vazio, conservar os tipos
originais de latitude/longitude usando `astype`. O fluxo não vazio permanece
igual. Não foram alterados DBSCAN, critérios, filtros, regra de ilesos ou esquema.

## Limitações restantes

- Sem teste automatizado em navegador real do Leaflet, controles, links e download.
  A query usada no teste HTTP segue o contrato; não é extraída de um clique real.
- Sem automação do ciclo de vida/reload de servidor iniciado antes de novos arquivos.
- Sem validação visual de layout, responsividade ou abertura no Microsoft Word.
- Sem consulta real ao Overpass; disponibilidade e completude OSM não são garantidas.
- CSVs pequenos e sintéticos; não há medição de desempenho/carga dos arquivos reais.
- A sequência de edição/remoção PGT no navegador e envio real de formulário permanece
  dividida entre os testes Node de DOM mínimo e os testes HTTP/DOCX.

## Execuções e resultados reais

| Comando | Resultado |
| --- | --- |
| `.venv\Scripts\python.exe -B manage.py test accidents signaling --noinput` antes das alterações | 212 testes; 211 passaram; falha conhecida de `Status:` |
| `.venv\Scripts\python.exe -B manage.py test accidents.test_main_flow --noinput --verbosity 2` na primeira rodada | 7 testes passaram |
| `.venv\Scripts\python.exe -B manage.py test accidents.test_main_flow.UploadFlowTests.test_upload_with_only_excluded_accidents_renders_empty_map_in_both_modes --noinput` antes da correção | 1 teste com erro no subcaso `clusters` |
| `.venv\Scripts\python.exe -B manage.py test accidents.test_main_flow --noinput` após correção | 8 testes passaram |
| `.venv\Scripts\python.exe -B manage.py test accidents signaling --noinput` final | 220 testes passaram |
| `node --test static/js/individual_filters.test.js static/js/report_characterization.test.js` | 27 testes passaram |
| `.venv\Scripts\python.exe -B manage.py check` | Sem problemas |
| `git diff --check` | Sem erros de whitespace |

As execuções Django usaram banco de teste isolado. Nenhuma chamada real ao
Overpass foi feita. Não houve commit.

Arquivos desta rodada:

- `accidents/test_main_flow.py`: oito testes novos.
- `analysis/occurrences.py`: preservação dos tipos no caso vazio.
- `signaling/test_report_download.py`: correção de uma asserção obsoleta.
- `docs/estabilizacao-fluxo-principal.md`: esta auditoria.
