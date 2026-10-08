# Visão geral do projeto

## O que este sistema faz

Este projeto processa arquivos CSV de sinistros, valida e consolida os dados, analisa ocorrência e clusters geográficos, e oferece uma interface para visualizar acidentes em um mapa e gerar relatórios de sinalização em pontos específicos.

A aplicação combina:

- processamento tabular em pandas;
- validação geográfica e análise espacial em Python;
- visualização no frontend com Leaflet/JavaScript;
- persistência de pontos de sinalização e intervenções em Django ORM;
- geração de relatório em Word a partir de dados da sessão e do ponto.

## Apps e responsabilidades

### `accidents/`

Responsável pela entrada do dado bruto:

- leitura e validação de CSVs;
- deduplicação por `id_sinistro`;
- exclusão de sinistros em que a única gravidade preenchida é `ileso`;
- preparação do dataframe para os modos de análise.

Arquivos principais:

- `accidents/services.py`
- `accidents/views.py`
- `accidents/urls.py`

### `analysis/`

Responsável pela análise espacial e pela montagem do payload de mapa:

- validação de município e coordenadas;
- geração de pontos de ocorrência e clusters;
- critérios históricos e classificação de clusters;
- resumo de localizações e períodos disponíveis.

Arquivos principais:

- `analysis/pipeline.py`
- `analysis/occurrences.py`
- `analysis/criteria.py`
- `analysis/map_data.py`
- `analysis/periods.py`

### `signaling/`

Responsável pelo cadastro de pontos de sinalização e geração do relatório:

- modelos de ponto, intervenção e problemas;
- busca de PGTs em Overpass;
- filtros do relatório individual;
- formulário e geração do DOCX.

Arquivos principais:

- `signaling/models.py`
- `signaling/views.py`
- `signaling/report_filters.py`
- `signaling/report_generator.py`
- `signaling/overpass.py`

### Frontend e templates

- `templates/map.html`: interface principal da análise.
- `static/js/map.js`: mapa, filtros e estado do cliente.
- `static/js/individual_filters.js`: lógica dos filtros individuais.
- `static/js/report_characterization.js`: parte do relatório.

## Fluxo principal

1. O usuário envia um ou mais CSVs na rota principal.
2. `accidents.services.import_accident_files()` lê os arquivos, concatena, deduplica e aplica a regra de ilesos.
3. `analysis.pipeline.prepare_accidents()` filtra por município e coordenas válidas.
4. O sistema escolhe entre dois modos:
   - `clusters`: gera pontos/cluster, critérios históricos e payload agregado;
   - `individual`: prepara sinistros válidos para visualização individual.
5. O resultado é salvo na sessão Django como estado transitório para renderização do mapa.
6. Quando um ponto de sinalização é criado/selecionado, o relatório usa os dados do mapa em sessão e aplica filtros específicos para o ponto.
7. O relatório final pode ser renderizado em HTML e baixado em DOCX.

## Persistido vs transitório

### Persistido no banco

- `SignalingPoint`
- `SignalingIntervention`
- `SignalingPointProblem`
- metadados de estado e raio de busca do ponto

### Transitório em sessão

- `ANALYSIS_SESSION_KEY` em `signaling.surveys`
- `view_mode`, `map_data`, `import_summary`, `available_periods`, `analysis_id`

Esse estado é usado para manter a análise atual sem persistir o payload bruto em banco.

## Regras de negócio importantes

- Os sinistros com `qtd_gravidade_ileso` como única gravidade preenchida são removidos antes da análise.
- A análise considera apenas registros municipais válidos e com coordenadas válidas.
- A rota principal usa `POST` para processar e `GET` para renderizar o estado em sessão.
- O relatório de ponto depende da análise individual em sessão e não do banco principal de acidentes.
- A busca de PGTs usa Overpass e tem falhas tratadas como erro operacional, não como falha do domínio.

## Onde procurar por domínio

- Importação e normalização: `accidents/services.py`, `accidents/normalizer.py`
- Pipeline de análise: `analysis/pipeline.py`, `analysis/*.py`
- Frontend/mapa: `templates/map.html`, `static/js/map.js`, `static/js/individual_filters.js`
- Relatórios de sinalização: `signaling/views.py`, `signaling/report_filters.py`, `signaling/report_generator.py`
- Testes relevantes: `accidents/test_main_flow.py`, `signaling/test_report_download.py`, `signaling/test_report_generator.py`

## Documentação de referência

- [reference/accident-pipeline.md](reference/accident-pipeline.md)
- [reference/signaling-and-reports.md](reference/signaling-and-reports.md)
- [reference/databases.md](reference/databases.md)

Documentos históricos e de auditoria ficam em [history/](history/).
