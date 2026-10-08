# Handoff técnico — Analise-Sinalizacao

## 1. Arquitetura relevante confirmada

Aplicação Django com:

- processamento tabular em pandas;
- análise espacial e DBSCAN no backend;
- mapa Leaflet no frontend;
- renderer Canvas para sinistros individuais;
- estado transitório da análise armazenado na sessão Django;
- waypoints (`SignalingPoint`) persistidos no banco;
- relatório HTML calculado sob demanda;
- Word gerado transitoriamente em memória.

Separação principal:

- `accidents/`: upload, importação, normalização e view do mapa;
- `analysis/`: preparação, análise espacial, critérios e payloads;
- `signaling/`: waypoints, levantamentos, filtros do relatório e DOCX;
- `templates/map.html`: interface principal;
- `static/js/map.js`: mapa e filtros;
- `static/js/signaling.js`: operações de waypoints;
- `static/js/individual_filters.js`: lógica pura dos filtros individuais.

---

## 2. Pipeline CSV → mapa

Fluxo confirmado:

```text
CSV(s)
→ accidents.services.import_accident_files()
→ leitura com pandas.read_csv(sep=";")
→ UTF-8; fallback latin-1
→ validação das colunas obrigatórias
→ concatenação
→ deduplicação por id_sinistro, keep="first"
→ exclusão de sinistros exclusivamente com ilesos
→ DataFrame consolidado filtrado
→ escolha do modo
```

Modo individual:

```text
process_individual_accidents()
→ prepare_accidents()
   → normalize()
   → validate()
   → município RIBEIRAO PRETO
   → validação geográfica
   → coordinate_status == VALID
→ filtro tipo_registro
→ filtro tipo_via
→ extract_available_periods()
→ build_individual_map_data()
→ sessão Django
→ Leaflet Canvas
```

Modo pontos elegíveis:

```text
process_accidents()
→ prepare_accidents()
→ build_occurrence_points()
→ cluster_points(DBSCAN)
→ assign_clusters_to_accidents()
→ evaluate_historical_criteria()
→ add_criterion_classification()
→ build_analysis_result()
→ build_location_summary()
→ extract_available_periods()
→ build_cluster_period_summaries()
→ build_map_data()
→ sessão Django
→ Leaflet
```

`accidents.views.analysis_view()` implementa POST/Redirect/GET. O POST processa e grava estado transitório; o GET renderiza o mapa a partir da sessão.

---

## 3. Arquivos e funções principais

### Importação e normalização

- `accidents/services.py`
  - `import_accident_files()`
  - `exclude_exclusively_uninjured_accidents()`
  - `_read_accident_file()`
- `accidents/normalizer.py`
  - `normalize()`
  - `validate()`

### Pipelines

- `analysis/pipeline.py`
  - `prepare_accidents()`
  - `process_individual_accidents()`
  - `process_accidents()`
- `analysis/periods.py`
  - `extract_available_periods()`
  - `build_cluster_period_summaries()`
- `analysis/map_data.py`
  - `build_individual_map_data()`
  - `build_map_data()`
  - `build_individual_accident_item()`

### Frontend

- `templates/map.html`
- `static/js/map.js`
- `static/js/individual_filters.js`
- `static/js/signaling.js`

### Relatórios

- `signaling/views.py`
  - `point_report()`
- `signaling/report_filters.py`
  - `IndividualReportFilters`
  - `parse_individual_report_filters()`
- `signaling/surveys.py`
  - `build_signaling_survey()`
  - `build_signaling_survey_from_items()`
- `signaling/report_generator.py`
  - geração DOCX e gráfico
- `templates/signaling/report.html`

---

## 4. Exclusão de sinistros exclusivamente com ilesos

Implementada em:

```text
accidents/services.py
exclude_exclusively_uninjured_accidents()
```

Nomes reais:

```text
qtd_gravidade_fatal
qtd_gravidade_grave
qtd_gravidade_leve
qtd_gravidade_nao_disponivel
qtd_gravidade_ileso
```

Condição exata:

```python
accidents[OTHER_SEVERITY_COLUMNS].isna().all(axis=1)
& accidents["qtd_gravidade_ileso"].notna()
```

A regra ocorre:

```text
depois da concatenação
→ depois da deduplicação
→ antes da normalização
→ antes do município/coordenadas
→ antes dos dois modos
→ antes do DBSCAN
→ antes da elegibilidade
→ antes da sessão e dos relatórios
```

Zeros não são nulos:

- zero em fatal/grave/leve/não disponível mantém o registro;
- ileso igual a zero satisfaz `notna()`.

Medição realizada com os dois CSVs reais:

```text
deduplicados: 886.967
exclusivamente ilesos: 29.443
após exclusão: 857.524
entrada válida do clustering: 17.572
payload individual/relatórios: 10.874
violações no individual/relatório: 0
violações na entrada do clustering: 0
```

Conclusão verificada: não há evidência de regressão nessa regra.

---

## 5. Filtros de categoria e gravidade

Implementação pura em `static/js/individual_filters.js`.

Categorias atuais:

```text
Atropelamento
Choque
Colisão
Não disponível
Outros
```

Semântica:

- OR entre categorias selecionadas;
- nenhuma categoria selecionada significa todas.

Gravidade:

```text
all
fatal
non_fatal
```

Semântica combinada:

```text
categoria
AND gravidade
AND período
```

`filterVisibleAccidents()` produz a coleção visível comum.

Essa coleção alimenta:

- marker;
- contador;
- popup;
- navegação;
- halo fatal;
- contador global.

O halo existe quando pelo menos um registro atualmente visível é fatal.

---

## 6. Multisseleção temporal atual

Alteração recente ainda presente no working tree.

Arquivos centrais:

- `templates/map.html`
- `static/js/map.js`
- `static/js/individual_filters.js`
- `signaling/report_filters.py`

A interface usa controles compactos `<details>` com checkboxes.

Contrato frontend:

```javascript
years: [2022, 2024, 2026]
months: [1, 3, 6, 10]
```

Arrays vazios significam ausência de restrição:

```javascript
years: []   // todos os anos
months: []  // todos os meses disponíveis
```

Regra:

```text
ano IN selectedYears
AND
mês IN selectedMonths
```

OR dentro dos anos e meses.

A multisseleção não relê CSV, não executa pipeline e não recalcula DBSCAN.

---

## 7. availablePeriods, selectedYears e selectedMonths

`availablePeriods` é extraído por `analysis.periods.extract_available_periods()` exclusivamente dos registros processados.

Formato:

```javascript
[
  {year: 2022, months: [1, 2, 3, ...]},
  {year: 2026, months: [1, 2, 3, 4, 5, 6]}
]
```

Os anos são ordenados; os meses válidos ficam entre 1 e 12.

`monthsForYears()` em `individual_filters.js` calcula a união dos meses dos anos selecionados.

Exemplo:

```text
2025 → Jan–Dez
2026 → Jan–Jun
2025 + 2026 → Jan–Dez
2026 isolado → Jan–Jun
```

Ao remover um ano, meses que deixaram de existir na união são removidos. Se nenhum mês específico permanecer, o estado volta a “Todos os meses disponíveis”.

Novo upload substitui integralmente o estado de análise da sessão e gera novos `availablePeriods`.

---

## 8. Transporte ao relatório HTML

O link do relatório é montado por `static/js/signaling.js`, usando:

```javascript
window.getIndividualReportFilterQuery()
```

Essa função é exposta por `map.js`.

Parâmetros repetidos:

```text
analysis=<analysis_id>
year=2022
year=2024
month=1
month=3
category=collision
category=pedestrian
gravity=fatal
```

`signaling.views.point_report()`:

1. recupera o estado da sessão;
2. exige análise individual;
3. valida filtros com `parse_individual_report_filters()`;
4. aplica-os ao `map_data`;
5. aplica o raio do waypoint via `build_signaling_survey_from_items()`;
6. gera o contexto HTML.

O backend valida:

- vínculo com `analysis_id`;
- anos disponíveis;
- meses 1–12;
- meses pertencentes à união dos anos selecionados;
- categorias;
- gravidade.

Uma combinação individual inexistente, como Out/2026, não invalida a seleção se outubro existir em outro ano selecionado.

---

## 9. Preservação no Word

O formulário HTML usa POST na mesma URL atual, incluindo a query string.

Assim, os parâmetros repetidos continuam disponíveis durante o POST.

`point_report()` recalcula o mesmo filtro e o mesmo `survey`, depois chama:

```python
generate_signaling_report(
    point,
    survey,
    form.cleaned_data,
    photos,
)
```

HTML e Word recebem a mesma coleção final.

O DOCX:

- é gerado em `BytesIO`;
- não é salvo no servidor;
- não cria model;
- não persiste campos do formulário;
- não persiste fotos.

---

## 10. Pontos elegíveis, DBSCAN e critérios

Confirmado em `analysis/pipeline.py`.

DBSCAN:

```python
cluster_points(
    points,
    radius_meters=20,
    min_samples=1,
)
```

Os critérios históricos são avaliados depois da associação dos acidentes aos clusters.

A multisseleção temporal não recalcula:

- DBSCAN;
- clusters;
- janelas históricas;
- elegibilidade;
- critérios do CONTRAN.

Ela filtra apenas a visualização dos pontos historicamente elegíveis usando `cluster_period_summaries`.

Os filtros de critérios continuam separados e usam OR.

Decisão de negócio vigente: o período não deve alterar a elegibilidade histórica.

---

## 11. Waypoints e raio

`SignalingPoint` é persistido no banco.

Cada waypoint possui:

```text
search_radius_meters
default: 50
mínimo: 10
máximo: 300
```

O mesmo valor é usado por:

- círculo Leaflet;
- cálculo Haversine do relatório;
- texto “Raio analisado”.

O relatório inclui acidente quando:

```text
distance <= search_radius_meters
```

Waypoints, intervenções e raio são independentes dos filtros visuais do mapa.

O relatório usa:

```text
análise individual
AND filtros individuais transportados
AND raio persistido do waypoint
```

---

## 12. Testes relevantes existentes

### Backend/importação

`accidents/tests.py` cobre:

- regra estrita de ilesos;
- zeros versus nulos;
- ileso igual a zero;
- vazio versus espaços;
- múltiplos CSVs;
- deduplicação antes da exclusão;
- contador;
- ausência dos excluídos na entrada individual;
- ausência dos excluídos na elegibilidade;
- extração de períodos.

### Filtros frontend

`static/js/individual_filters.test.js` cobre:

- categoria;
- gravidade;
- multiperíodo;
- anos não consecutivos;
- união dos meses;
- grupos coincidentes;
- badge;
- popup;
- índice;
- halo;
- query do relatório.

Última execução:

```text
16 testes JavaScript
16 passaram
```

### Relatório

- `signaling/test_report_filters.py`
- `signaling/test_report_download.py`
- `signaling/test_report_generator.py`
- `signaling/test_surveys.py`

Há teste recente confirmando múltiplos anos/meses no HTML e no Word.

Testes Django direcionados mais recentes:

```text
63 testes
63 passaram
```

---

## 13. Alterações recentes desta conversa

### Implementadas e já presentes no histórico

- exclusão compartilhada de sinistros exclusivamente com ilesos;
- contador dessa exclusão no resumo do upload.

Commit identificado:

```text
0ebe7f9 removes accidents without victims from processing
```

### Presentes como modificações locais

- multisseleção de anos e meses;
- contrato temporal por parâmetros repetidos;
- validação backend de coleções;
- união de meses por anos;
- testes de multiperíodo.

Estado observado no fim da última investigação:

```text
 M .gitignore
 M accidents/tests.py
 M signaling/report_filters.py
 M signaling/test_report_download.py
 M signaling/test_report_filters.py
 M static/js/individual_filters.js
 M static/js/individual_filters.test.js
 M static/js/map.js
 M templates/map.html
```

A modificação de `.gitignore` não foi feita durante a implementação da multisseleção nesta conversa e deve ser preservada como alteração do usuário.

---

## 14. Problemas conhecidos e pendências

### Confirmado

Existe um teste preexistente de relatório esperando o literal:

```text
Status:
```

O template atual mostra diretamente o valor, como:

```text
Adequada
```

Esse teste falha na suíte combinada, mas não está relacionado aos filtros temporais nem à exclusão de ilesos.

### Pendente de validação visual

Não houve navegador interativo disponível para validar visualmente:

- dropdowns de multisseleção;
- responsividade;
- remoção dinâmica de meses;
- fluxo completo mapa → HTML → Word;
- alternância de modos.

### Investigação futura solicitada, mas não realizada

Relação conceitual entre:

- filtro temporal visual;
- janelas históricas de um e três anos;
- representação dos pontos elegíveis.

A decisão atual é não recalcular elegibilidade.

### Hipótese descartada

A multisseleção não contorna a exclusão de ilesos. Medições reais encontraram zero IDs excluídos nos payloads posteriores.

### Hipótese ainda contextual

Um aumento visual de sinistros pode ser consequência legítima de selecionar mais anos/meses. Para atribuir um aumento específico, é necessário conhecer o snapshot dos filtros daquela sessão.

---

## 15. Decisões de negócio que não devem ser alteradas

- Exclusão de ilesos usa estritamente nulo/não nulo.
- Zero não equivale a nulo.
- Deduplicação ocorre antes da exclusão e mantém a primeira ocorrência.
- Agrupamento visual usa coordenadas exatamente iguais.
- Não usar tolerância, DBSCAN ou proximidade nesse agrupamento.
- Categoria usa OR.
- Gravidade combina por AND com categoria e período.
- Anos usam OR.
- Meses usam OR.
- Ano e mês combinam por AND.
- Meses disponíveis são a união dos anos selecionados.
- Não fabricar combinações ano/mês inexistentes.
- Período não recalcula elegibilidade histórica.
- Relatório usa filtros individuais + raio.
- Relatório não depende dos filtros históricos dos pontos elegíveis.
- Waypoints continuam persistentes.
- Acidentes permanecem transitórios.
- Não usar DataFrame global.
- DOCX e fotos não são persistidos.
- Não alterar DBSCAN, critérios históricos ou raio de clustering sem tarefa específica.
- Não criar models ou migrations para filtros/relatórios.

---

## 16. Ordem recomendada de leitura

Uma nova sessão deve começar por:

1. `AGENTS.md`
2. `accidents/services.py`
3. `accidents/views.py`
4. `accidents/normalizer.py`
5. `analysis/pipeline.py`
6. `analysis/periods.py`
7. `analysis/map_data.py`
8. `templates/map.html`
9. `static/js/individual_filters.js`
10. `static/js/map.js`
11. `static/js/signaling.js`
12. `signaling/report_filters.py`
13. `signaling/views.py`
14. `signaling/surveys.py`
15. `signaling/report_generator.py`
16. `templates/signaling/report.html`
17. `accidents/tests.py`
18. `static/js/individual_filters.test.js`
19. `signaling/test_report_filters.py`
20. `signaling/test_report_download.py`

Antes de editar, executar somente para inspeção:

```text
git status --short
git diff
```

Isso é necessário porque há alterações locais legítimas ainda não commitadas.