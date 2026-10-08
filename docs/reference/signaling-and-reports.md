# Referência: sinalização e relatórios

## Responsabilidade

Este domínio cobre a análise de pontos de sinalização, integração com PGTs e geração de relatórios a partir dos sinistros selecionados.

Arquivos centrais:

- `signaling/models.py`
- `signaling/views.py`
- `signaling/forms.py`
- `signaling/report_filters.py`
- `signaling/report_generator.py`
- `signaling/overpass.py`
- `signaling/services.py`
- `signaling/surveys.py`

## Entidades persistidas

`SignalingPoint` representa um ponto georreferenciado com:

- latitude e longitude;
- status (`OK`, `INCOMPLETE`, `ABSENT`);
- raio de busca em metros;
- intervenções e problemas associados.

`SignalingIntervention` mantém a intervenção aplicada ao ponto e seu status/observações.

`SignalingPointProblem` liga um problema de geometria/segurança a uma solução válida.

## Fluxo do ponto e relatório

1. O usuário cria ou seleciona um ponto de sinalização.
2. O endpoint `search_point_pgts` consulta Overpass para localizar PGTs próximos ao ponto.
3. O relatório usa a análise atual em sessão para filtrar os sinistros relevantes ao ponto.
4. `parse_individual_report_filters()` aplica filtros por categoria, gravidade e períodos.
5. `build_signaling_survey_from_items()` monta o survey do ponto com ocorrências e intervenções.
6. O template `templates/signaling/report.html` renderiza o HTML do relatório.
7. Ao confirmar, `generate_signaling_report()` gera o DOCX em memória e devolve o arquivo para download.

## Integrações e limitações

- `signaling.overpass` faz a busca externa por PGTs; falhas são tratadas como `OverpassUnavailable`.
- O WorkFlow principal usa dados da sessão, não uma nova leitura do banco de acidentes.
- O relatório final é emitido sob demanda; não há persistência do documento gerado em banco.

## Regras de negócio relevantes

- O raio do ponto tem intervalo validado entre `MIN_SIGNALING_SEARCH_RADIUS_METERS` e `MAX_SIGNALING_SEARCH_RADIUS_METERS`.
- O relatório individual exige que a análise ativa em sessão seja do tipo `individual`.
- Filtros repetidos e parâmetros inválidos são rejeitados antes da geração do Word.
- O conjunto de soluções e problemas é validado por catálogo e por `CheckConstraint` no modelo.

## Frontend relevante

A interface do mapa e do relatório depende de:

- `templates/map.html`
- `static/js/map.js`
- `static/js/individual_filters.js`
- `static/js/report_characterization.js`

Esses arquivos implementam seleções, filtros visíveis, links de relatório e apresentação de itens do formulário.

## Testes relevantes

- `signaling/tests.py`
- `signaling/test_report_download.py`
- `signaling/test_report_generator.py`
- `signaling/test_report_filters.py`
- `signaling/test_overpass.py`
- `signaling/test_pgt_endpoint.py`

Esses testes cobrem ponto, raio, filtros, geração do DOCX e integrações externas mockadas.
