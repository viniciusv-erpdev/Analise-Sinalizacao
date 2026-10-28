# Etapa 7C - detalhes e historico publicado

GET /signaling/reports/<uuid>/, nome signaling:report-detail, acessivel pelo
numero oficial na biblioteca. Reutiliza get_official_report e
 official_versions_for da 7A. Sem novas permissoes, migrations ou alteracoes nas
reservas/finalizacao. Anonimos, usuarios sem leitura, objetos ausentes e relatorios
sem versoes publicadas retornam 404. Somente GET; respostas no-store e Vary Cookie.

Mostra numero oficial, ID historico do waypoint, maior numero de versao publicada,
sua emissao e autoria congelada; historico ordenado por issued_at decrescente,
version decrescente e UUID. Latest segue a maior versao, como na biblioteca.
Autor prioriza username historico, com fallback para full_name e Nao informado.
Datas em America/Sao_Paulo. SHA-256 e snapshot_sha256 persistido: identifica o
snapshot estruturado, nao PDF/DOCX; nao representa uma verificacao fisica nova.
Nao carrega snapshots, caminhos/artefatos privados ou usuario/waypoint atuais.
Nenhuma alteracao em registros oficiais. Sem downloads ou publicacao.

## Validacao local

Testes portaveis executaveis tambem em PostgreSQL temporario:

```powershell
. .\.venv\Scripts\Activate.ps1
. .\scripts\local-postgres-env.ps1
```

Confirmar destino local analise_dev, banco test_analise_dev descartavel sem uso
por outra sessao. Se houver duvida, interromper. Nao usar --noinput/--keepdb.
O comando seguinte cria/migra/destroi somente o banco temporario confirmado:

```powershell
python -B manage.py test signaling.test_report_detail signaling.test_report_library signaling.test_report_read_access --verbosity 2
python -B manage.py check
```

Esperado: 44 testes sem skips. Execucao Codex: 44 aprovados em SQLite temporario;
nao substitui PostgreSQL. Nenhuma migration aplicada a banco existente.

## Homologacao manual

1. Com conta autorizada e REPORT_FINALIZATION_ENABLED=false, abrir biblioteca e
   clicar no numero RTSV-2026-0001; conferir numero, waypoint e autoria historicos.
2. Conferir emissao Sao Paulo, versao mais recente e SHA-256 do snapshot com os
   metadados oficiais. Historico deve conter apenas versoes publicadas em ordem
   inversa de emissao. Nao criar/alterar versoes reais para testar: os testes
   isolados fornecem os cenarios de multiplas versoes e exclusoes historicas.
3. Usar retorno a biblioteca; conferir navbar, teclado e larguras 320/768/1280px,
   especialmente rolagem horizontal da tabela e quebra do hash.
4. Como anonimo e conta sem view_official_reports, URL direta deve retornar 404;
   UUID inexistente tambem. Permissao exclusiva de download/finalizar nao basta.
5. Confirmar ausencia de links de download, edicao ou finalizacao.

Validacao visual e PostgreSQL da nova pagina pendentes; sem avancar para 7D.
