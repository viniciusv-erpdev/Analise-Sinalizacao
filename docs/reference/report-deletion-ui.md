# Etapa 7F-C3 - interface de exclusao definitiva

Pre-requisito informado pelo usuario: 78 testes PostgreSQL da 7F-C2 aprovados.
Esta etapa reutiliza o backend e a migration 0014 existentes. Nao ha nova migration,
permissao, endpoint, polling ou alteracao de reservas/publicacao.

## Componentes

report_library_views informa can_delete_reports usando a politica centralizada e
usuario fresco. report_detail mostra botao vermelho com delete-signal-icon.svg
existente, somente com permissao. A pagina ainda exige view_official_reports;
downloads mantem as duas permissoes anteriores. is_staff nao participa.

report_deletion.js monta dialog nativo, confirma numero exato sem trim, envia POST
com JSON, cookie same-origin e CSRF do template. Acoes nao publicam nada. Abrir,
fechar, digitar ou carregar pagina nao chama API nem cria operation_id. Um clique
explicito confirmado cria UUID v4 seguro, grava o journal e so entao envia. Duplo
clique compartilha requisicao. Cancelar/Escape ficam bloqueados durante envio; o
foco e o scroll sao restaurados ao fechar. Sem JavaScript o botao fica oculto.

## Intencao e recuperacao

localStorage: rtsv.deletion.v1.u<usuario>.<relatorio>. Guarda somente schema,
usuario/relatorio, numero oficial, operationId e estado; nao guarda token CSRF,
cookies, dados de sessao, snapshots, fotos ou caminhos privados. Exige escrita com
leitura de confirmacao antes do POST. Se indisponivel/corrompido, bloqueia exclusao
sem sobrescrever uma chave incerta. Nao limpar storage para recuperar timeout.
Outras abas/perfis continuam sujeitos a idempotencia e locks do backend; nenhuma
trava visual substitui a autorizacao. Chaves locais sao separadas por usuario.

200 so e sucesso integral com success=true, report_deleted=true, COMPLETE,
numero esperado e UUID de operacao valido. Retorna a biblioteca com filtros, mas
sem page: excluir a ultima linha pode invalidar a pagina anterior.
202 so indica registros removidos e limpeza pendente. Nao redireciona nem declara
conclusao integral; oferece Retomar limpeza ou retorno manual a biblioteca.
403/401: acesso/sessao, sem retry no modal atual. 404: ausente/inacessivel, sem
presumir sucesso. 409: conflito com recuperacao explicita, exceto chave conflitante
ou namespace inseguro, que exigem revisao. Erros 5xx, rede, timeout de 30s e envelopes
inesperados sao resultados ambiguos: preservam UUID. Nunca mostra corpo de erro.

Na biblioteca, apenas usuarios autorizados veem aviso para journals pendentes do
proprio usuario. A verificacao reenvia POST com a MESMA intencao/confirmacao anterior;
nao existe GET de status de exclusao. Nenhuma chamada automatica e feita ao montar.
Assim e possivel recuperar depois que o relatorio ja nao possui pagina de detalhes.
Sucesso limpa o journal e atualiza a biblioteca, preservando filtros sem page.
Uma pagina recarregada reavalia permissoes/CSRF e permite nova verificacao explicita.

## Homologacao local (somente documentos sinteticos)

1. Confirmar 0014 aplicada manualmente no desenvolvimento autorizado. Nao aplicar
   automaticamente nem usar um documento real para demonstracao.
2. Usuario nao staff com view_official_reports, download_official_reports e
   delete_official_reports: abrir biblioteca/detalhes; conferir botoes anteriores.
3. Abrir modal, conferir numero e aviso de permanencia/versoes/arquivos. Cancelar
   e Escape nao podem produzir POST nem UUID. Testar teclado e larguras 320/768/1280.
4. Digitar numero incompleto/com espaco: confirmar continua desabilitado. Numero
   exato permite enviar uma vez; duplo clique nao duplica. CSRF deve ser enviado.
5. Com retorno 200, conferir redirecionamento, ausencia do documento e preservacao
   de outro relatorio. Conferir filtros mantidos; pagina volta a primeira.
6. Simular respostas com mocks/testes locais: 202 deve exibir pendencia e permitir
   recuperar mesma UUID. Para falha real de rede, usar DevTools offline em um
   documento sintetico; restaurar e Verificar exclusao, sem gerar outro UUID.
7. Depois de timeout/202, voltar a biblioteca ou recarregar: aviso deve recuperar
   journal proprio, mesmo que detalhes retornem 404. POST de recuperacao usa a
   UUID original. Nao injetar falhas em arquivos reais do ambiente.
8. Usuario somente leitor/staff sem delete nao recebe botao ou aviso. Backend
   continua retornando 403 ao POST sem permissao. Nao conceder acesso ao analista.

## Limites e validacao

Homologacao visual no navegador permanece necessaria. localStorage foi escolhido
para sobreviver a recarga; dados nao migram entre navegadores/perfis e nao devem
ser apagados enquanto ha resultado ambiguo. Sem Web Storage a exclusao fica
bloqueada. Download ja iniciado e backups obedecem aos limites da 7F-C2.
Permissao revogada durante envio continua sendo decidida no servidor.

Os testes Django desta etapa usam banco temporario e arquivos sinteticos. Neste
processo nao ha credenciais PostgreSQL; a aprovacao PostgreSQL anterior foi
informada pelo usuario e nao substitui validacao dos testes novos em PostgreSQL.
Nao houve deploy, aplicacao de migration em analise_dev ou exclusao de dados reais.

Com PowerShell autenticado e test_analise_dev descartavel confirmado:

    .\.venv\Scripts\Activate.ps1
    . .\scripts\local-postgres-env.ps1
    python -B manage.py test signaling.test_report_detail signaling.test_report_library signaling.test_report_deletion signaling.test_report_deletion_postgresql signaling.test_report_read_access signaling.test_report_artifacts signaling.test_report_finalization_postgresql --verbosity 2

JavaScript:

    node --test static/js/report_deletion.test.js static/js/report_detail.test.js

Nao usar --noinput/--keepdb automaticamente. Nenhuma dependencia foi adicionada.

Validacao executada: 170 testes Django em SQLite temporario, 218 testes JavaScript,
manage.py check, makemigrations --check --dry-run, node --check e git diff --check
aprovados. Sem migration nova, exclusao real ou deploy. Homologacao visual e
execucao dos testes novos em PostgreSQL autenticado permanecem pendentes.
