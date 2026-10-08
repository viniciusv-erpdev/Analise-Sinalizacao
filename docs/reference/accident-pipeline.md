# Referência: processamento de acidentes

## Responsabilidade

Este domínio cobre a ingestão, validação e preparação dos dados de acidentes para a análise espacial.

Arquivos centrais:

- `accidents/services.py`
- `accidents/normalizer.py`
- `analysis/pipeline.py`
- `analysis/geography.py`
- `analysis/map_data.py`
- `analysis/periods.py`

## Fluxo de dados

1. O usuário envia CSV(s) na rota principal.
2. `import_accident_files()` lê cada CSV com `pandas.read_csv(..., sep=';')`, tenta UTF-8 e depois latin-1.
3. Os arquivos são concatenados e deduplicados por `id_sinistro`.
4. `exclude_exclusively_uninjured_accidents()` remove registros em que todas as severidades relevantes são nulas e `qtd_gravidade_ileso` está preenchido.
5. `prepare_accidents()` normaliza e valida o dataframe, filtra por município `RIBEIRAO PRETO` e valida coordenadas com o polígono municipal.
6. O resultado é dividido em dois modos:
   - `process_individual_accidents()`: foco em sinistros individuais válidos;
   - `process_accidents()`: gera pontos, clusters, critérios históricos e payload para mapa agregado.

## Invariantes e regras de negócio

- Colunas obrigatórias do CSV: `id_sinistro`, `data_sinistro`, `latitude`, `longitude`, `tp_sinistro_primario`, `logradouro`, `numero_logradouro`, `municipio`, `qtd_gravidade_fatal`, `qtd_gravidade_grave`, `qtd_gravidade_leve`, `qtd_gravidade_nao_disponivel`, `qtd_gravidade_ileso`.
- A regra de exclusão de ilesos é aplicada antes da normalização e antes do restante da análise.
- A análise usa apenas registros com coordenadas válidas dentro do município registrado.
- Dados de análise e payloads são enviados para a sessão Django e renderizados pelo frontend.

## Modo individual vs modo clusters

### Individual

- usa `process_individual_accidents()`;
- aplica filtros de `record_type` e `road_type` específicos;
- salva métricas em `filtered.attrs["individual_metrics"]`;
- expõe períodos disponíveis via `available_periods`.

### Clusters

- usa `process_accidents()`;
- gera `build_occurrence_points()` + `cluster_points()`;
- associa clusters a acidentes;
- avalia critérios históricos em `analysis/criteria.py`;
- monta `build_analysis_result()` e `build_location_summary()`;
- calcula resumos por período e cluster.

## Persistência e sessão

A análise atual é guardada em `request.session` por `accidents.views.analysis_view()`. Os dados persistidos em sessão incluem:

- `analysis_id`
- `view_mode`
- `map_data`
- `import_summary`
- `available_periods`

Esse estado é o contrato utilizado pelo frontend e pelo relatório de sinalização.

## Testes relevantes

- `accidents/tests.py`
- `accidents/test_main_flow.py`
- `scripts/test_*.py` para exploração de CSVs reais

Esses testes cobrem importação, deduplicação, exclusão de ilesos, normalização, coordenadas, estágio individual e fluxo principal.
