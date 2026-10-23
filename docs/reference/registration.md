# Cadastro público

`/accounts/register/` usa o formulário nativo de criação de usuário, estendido em
`accounts/forms.py`. O e-mail é obrigatório, tem espaços externos removidos e é
armazenado em minúsculas. A busca de duplicatas também considera e-mails legados
com espaços externos. Usuários e senhas seguem as validações nativas do Django.

`accounts/services.py` cria a conta e associa o grupo existente **analista** na
mesma transação. Não cria grupos, copia permissões nem modifica contas existentes.
Contas novas ficam ativas, sem staff/superuser e sem permissões diretas. O cadastro
não faz login automático. O redirecionamento ao login conserva somente um `next`
aceitável pelo host/esquema atual; o login continua usando a validação nativa.

## Provisionamento e operação

Antes de habilitar em homologação e produção, um administrador deve conferir no
Django Admin a existência do grupo com o nome exato `analista` e suas permissões.
Comparar com a política aprovada para os analistas; o código não define uma lista
paralela de permissões. Não incluir poderes administrativos nesse grupo. Validar
com uma conta nova o acesso de leitura, criação/edição e relatórios autorizado.
Esses ambientes não são verificados automaticamente nem acessados pelos testes.

`DJANGO_REGISTRATION_ENABLED=False` bloqueia GET/POST de cadastro com HTTP 403,
sem afetar login ou usuários existentes. O padrão é True. Grupo ausente ou erro de
persistência retorna HTTP 503 com mensagem genérica e registro interno sem dados
do formulário. A chave de configuração inválida impede a inicialização.

Cadastro público concede acesso imediato. CSRF não limita automação. Recomenda-se
limitar POSTs de `/accounts/register/` no proxy confiável por IP, com janela e burst
medidos em homologação, retornando 429. Considerar usuários atrás do mesmo NAT e
monitorar volume total; não confiar em X-Forwarded-For recebido diretamente da
internet. Não há limitador de aplicação ou serviço externo nesta etapa. Desabilitar
cadastros durante abuso é uma medida disponível. A existência de usuário/e-mail
pode ser inferida pelas mensagens de duplicidade exigidas pelo formulário.

## Limite de unicidade do e-mail

A consulta do formulário não garante unicidade entre requisições simultâneas nem
contra outros escritores (Admin, scripts). Não há constraint ou migration nova.
A transação garante a indivisibilidade da conta e associação, não a exclusividade
do e-mail. Username mantém sua constraint nativa; conflitos de persistência são
tratados com falha genérica, sem sucesso parcial.

Uma garantia global exige proposta de esquema separada: primeiro inventariar
colisões após normalização, inclusive contas administrativas; decidir manualmente
como resolver cada colisão e os e-mails vazios; depois definir uma constraint ou
índice único apropriado ao backend sobre o valor normalizado, com estratégia para
novas gravações durante a implantação. Não apagar, mesclar ou alterar registros
existentes automaticamente. Qualquer DDL/migration precisa de aprovação prévia.

## Validação

Executar `python manage.py check` e
`python manage.py test signaling.test_registration signaling.test_authorization`
em ambiente de testes isolado. Os testes provisionam seu próprio grupo e não
comprovam o provisionamento dos ambientes reais nem unicidade concorrente de e-mail.
Não há mudanças no protocolo de reservas ou nos workflows.
