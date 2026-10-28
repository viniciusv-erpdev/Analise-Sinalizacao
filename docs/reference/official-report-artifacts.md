# Etapa 7D - arquivos oficiais privados

## Contrato

GET /signaling/reports/<report_uuid>/versions/<version>/artifacts/<artifact_uuid>/view/
GET /signaling/reports/<report_uuid>/versions/<version>/artifacts/<artifact_uuid>/download/

Nomes: signaling:report-artifact-view e signaling:report-artifact-download.
View aceita PDF e PHOTO inline; DOCX somente attachment pelo download. Download
aceita PDF, DOCX e PHOTO. IDs de artefatos sao UUIDs; nao recebe caminhos.
Ambas as permissoes view_official_reports e download_official_reports sao
obrigatorias pela politica 7A. Ausencia de autenticacao, permissao, objeto ou
publicacao resulta em 404. Tambem valida vinculo report/version/artifact.
Nao exige reserva nem REPORT_FINALIZATION_ENABLED. Nenhuma concessao automatica.

Detalhes consultam somente metadados autorizados (UUID, kind, ordinal, version)
para mostrar acoes e fotografias em ordem. Fotos abrem em nova aba com acesso
protegido, sem miniaturas publicas. Nenhum storage_key vai para o HTML.

## Integridade

PrivateReportStorage.open_verified usa o layout existente da Etapa 6 e as mesmas
restricoes de caminhos/symlinks. Verifica tamanho e SHA-256 em blocos de 128 KiB,
reposiciona e entrega o mesmo descritor para FileResponse, que o fecha ao fim.
Nao altera read/save/delete nem arquivos existentes. Arquivo ausente/corrompido
retorna 404 generico sem bytes. MIME e extensao devem corresponder ao kind;
Content-Disposition usa nome gerado de numero oficial/versao/ordinal.
Cache-Control private, no-store, Vary Cookie e nosniff nas respostas de arquivo.

A verificacao exige ler todo o arquivo antes do primeiro byte da resposta, com
custo de I/O proporcional ao tamanho (e uma segunda leitura para entrega), mas
memoria limitada por bloco. Usa worker sincrono durante a entrega. Nao implementa
Range parcial nesta etapa. A integridade assume armazenamento imutavel e acesso
de escrita restrito ao usuario do servico; alteracao maliciosa do arquivo aberto
pelo sistema operacional durante a entrega requer isolamento operacional.
Nenhuma dependencia, migration ou mudanca transacional de finalizacao.

## Homologacao local

No PowerShell autenticado:

```powershell
. .\.venv\Scripts\Activate.ps1
. .\scripts\local-postgres-env.ps1
```

Antes dos testes, confirmar host local, analise_dev como desenvolvimento e
 test_analise_dev descartavel e sem outra sessao. Se houver duvida, interromper.
O comando cria/migra/destroi apenas o banco temporario confirmado; nao usar
--noinput ou --keepdb automaticamente:

```powershell
python -B manage.py test signaling.test_report_artifacts signaling.test_report_detail signaling.test_report_library signaling.test_report_read_access signaling.test_report_finalization signaling.test_report_reconciliation --verbosity 2
python -B manage.py check
git diff --check
```

1. Manter finalizacao desabilitada. Usar conta de testes com AMBAS as permissoes
   ja concedidas explicitamente pelo administrador (nenhum grupo automatico).
2. Biblioteca: abrir RTSV-2026-0001. Conferir arquivos de cada versao publicada.
3. Visualizar PDF: nova aba, documento abre; Network mostra application/pdf,
   inline, private/no-store e nosniff. Baixar PDF/DOCX e conferir abertura normal.
4. Visualizar/baixar fotos; conferir ordem e originais preservados. Comparar
   Get-FileHash -Algorithm SHA256 dos downloads com ReportArtifact.sha256 por
   consulta administrativa autorizada, sem publicar caminhos privados.
5. Conta somente leitura: detalhes permanecem acessiveis, acoes de arquivos nao
   aparecem e URLs copiadas retornam 404. Anonimo tambem recebe 404.
6. Alterar UUID/versao na URL deve resultar em 404. Nao modificar arquivos reais
   para testar corrupcao: os testes usam arquivos sinteticos temporarios.
7. Conferir responsividade, foco e retorno a biblioteca. Sem edicao/finalizacao.

Validacao real PostgreSQL depende das credenciais do terminal autenticado;
validacao visual dos arquivos preexistentes permanece manual. Nao avancar a 7E.

## Resultado automatizado

73 testes aprovados, zero falhas/erros/skips, em banco SQLite temporario.
Inclui 7 testes novos de arquivos e regressoes 6/7A/7B/7C. Check, sintaxe de
5 modulos e git diff --check aprovados. PostgreSQL pendente: POSTGRES_PASSWORD
nao disponivel ao processo. Testes usam arquivos sinteticos com o layout da
Etapa 6; abertura dos artefatos reais RTSV-2026-0001 permanece manual.

## Correcao dos testes PostgreSQL

Causa identificada no ciclo da resposta, nao na criacao dos usuarios:
HttpResponseBase.close emite request_finished; chamadas manuais response.close
nos testes de streaming contornavam closing_iterator_wrapper do cliente Django.
Esse wrapper desliga temporariamente close_old_connections durante o fechamento.
Sem o wrapper, a conexao PostgreSQL dentro do atomic de TestCase era fechada,
contaminando os proximos testes da classe. SQLite em memoria ignora close e
ocultava o defeito. A ordem influencia qual teste evidencia a conexao fechada.

Agora todos os streams sao consumidos pelo cliente, que fecha os descritores.
O teste de fechamento verifica arquivo fechado, nenhuma chamada a connection.close
e uma consulta ORM posterior, sem reconectar. Dados comuns ficam em
report_test_fixtures.py (funcao e mixin sem TestCase/setUp); biblioteca, detalhes e
artefatos nao chamam o setUp de outra classe. Todos continuam django.test.TestCase.
Nenhuma mudanca na implementacao de autorizacao, armazenamento ou streaming.

Validacao PostgreSQL manual: confirmar host local e test_analise_dev descartavel,
sem outra execucao utilizando esse banco, antes de executar. Nenhum --keepdb ou
--noinput. Nao aplicar migrations em analise_dev.

```powershell
. .\.venv\Scripts\Activate.ps1
. .\scripts\local-postgres-env.ps1
python -B manage.py test signaling.test_report_artifacts --verbosity 2
python -B manage.py test signaling.test_report_artifacts signaling.test_report_detail signaling.test_report_library signaling.test_report_read_access signaling.test_report_finalization signaling.test_report_reconciliation --verbosity 2
python -B manage.py test signaling.test_report_artifacts signaling.test_report_detail signaling.test_report_library signaling.test_report_read_access --reverse --verbosity 2
python -B manage.py check
git diff --check
```

Esperados: 7 testes isolados, 73 conjuntos e 51 em ordem inversa, sem skips.
Repetir tambem o comando original de 84 testes usado na homologacao, pois sua
composicao completa nao foi fornecida nesta solicitacao. Credenciais PostgreSQL
indisponiveis ao Codex; correcao ainda depende dessa validacao real.

## Refinamento visual dos detalhes

Versoes publicadas agora usam cards sem tabela; mesma ordenacao e endpoints.
PDF recebe acao principal, seguida dos downloads; fotos autorizadas ficam em
 details/summary com quantidade e acoes individuais. Detalhes tecnicos recolhem
o hash completo do snapshot, sempre selecionavel. Copia e aprimoramento opcional:
sem Clipboard API o controle fica oculto; em falha, oferece copia manual.
Conta sem download continua vendo metadados/hash, sem arquivos ou contagens.
Agrupamento PDF/DOCX/PHOTO e somente apresentacao dos metadados ja autorizados.
Nenhuma alteracao em autorizacao, armazenamento ou documentos oficiais.

Conferencia manual: abrir RTSV-2026-0001 na biblioteca; testar Visualizar relatorio
em nova aba, downloads PDF/DOCX, abrir Fotografias e conferir contagem/links.
Abrir Detalhes tecnicos e testar Copiar SHA-256 (localhost/HTTPS); conferir hash
colado e fallback se clipboard negado. Repetir com teclado e larguras 320/768/1280.
Conta somente leitura nao deve ver acoes de arquivos. Multiplas versoes devem
seguir emissao decrescente com um unico destaque Mais recente.
