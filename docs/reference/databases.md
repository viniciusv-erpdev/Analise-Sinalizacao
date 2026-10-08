# SQLite e PostgreSQL

## Configuração

`config/database.py` seleciona um único banco; não abre conexões e não tenta outro
backend se o PostgreSQL falhar. Não carrega `.env` automaticamente: as variáveis
precisam estar no ambiente do processo antes da inicialização do Django.

| Variável | Uso / padrão |
| --- | --- |
| `DJANGO_DB_BACKEND` | `sqlite` ou `postgresql`; padrão SQLite apenas com DEBUG ativo. Obrigatória com `DJANGO_DEBUG=False`. |
| `DJANGO_SQLITE_PATH` | Caminho do SQLite; padrão `BASE_DIR/db.sqlite3`. Use caminho absoluto para cópias e rollback. |
| `POSTGRES_DB` | Nome do banco, obrigatório em PostgreSQL. |
| `POSTGRES_USER` | Usuário, obrigatório em PostgreSQL. |
| `POSTGRES_PASSWORD` | Senha, obrigatória em PostgreSQL; preservada literalmente. |
| `POSTGRES_HOST` | Host explícito, obrigatório; normalmente `127.0.0.1` para a VM local. |
| `POSTGRES_PORT` | Porta de 1 a 65535; padrão `5432`. |
| `DJANGO_TEST_DB_NAME` | Opcional; nome exclusivo de banco de testes, diferente de `POSTGRES_DB`. Padrão Django: `test_<nome>`. |
| `DJANGO_DEBUG` | `False` em produção; não habilitar DEBUG para contornar validação. |
| `DJANGO_SECRET_KEY` | Obrigatória com DEBUG desativado; preservar a chave existente durante a transferência das sessões. |
| `DJANGO_ALLOWED_HOSTS` | Lista separada por vírgulas, obrigatória com DEBUG desativado. |

Não há valores de credenciais neste documento. Não registrar senhas no histórico
do shell, fixtures no Git, nem alterar os arquivos reais de segredos durante os
ensaios. A conexão tem timeout de 10 segundos e mantém os padrões do Django de
conexões curtas, sem pool nem transações automáticas por requisição.

Psycopg 3 é usado via `psycopg[binary]==3.3.5`, com wheels para Python 3.13/3.14.
A distribuição binária evita compilação no Windows e Ubuntu; inclui bibliotecas
cliente próprias e deve receber atualizações de segurança junto com a dependência.
A alternativa `psycopg[c]` usa libpq do sistema e exige toolchain; não foi adotada.
Não é necessário PostGIS: os modelos usam coordenadas DecimalField e o cálculo
espacial acontece em Python.

Confirmar a versão do servidor antes do ensaio: Django 6.1 documenta PostgreSQL
15 ou superior. Preferir uma versão ainda mantida pelo PostgreSQL.
Referências: [Django](https://docs.djangoproject.com/en/6.1/ref/databases/),
[Psycopg](https://www.psycopg.org/psycopg3/docs/basic/install.html).

## Auditoria do código

- SQLite estava fixado em `config/settings.py`. `manage.py`, WSGI e ASGI usam o
  mesmo settings. `SignalingConfig` não executa trabalho de banco na inicialização.
- Quatro modelos em `signaling/models.py`: ponto, intervenção, problema e solução.
  IDs BigAutoField; filhos com FK/CASCADE; problemas e soluções têm UNIQUE/CHECK.
  Intervenções repetidas são permitidas desde a migration 0003.
- `accidents/models.py` não tem modelos e accidents não está em INSTALLED_APPS.
  Acidentes analisados ficam na sessão padrão de banco do Django, não em uma
  tabela de acidentes. Incluir auth, contenttypes, admin e sessions na migração.
- Sete migrations 0001–0007, sem SQL bruto. A 0007 copia soluções por ORM com o
  alias da conexão e impede reversão que descarte múltiplas soluções. Não reverter
  o esquema como estratégia de rollback entre bancos.
- Não foram encontrados comandos de gerenciamento próprios nem PRAGMA, SQL bruto,
  acesso direto ao sqlite3 ou pandas.to_sql/read_sql no código Python do projeto.
- Serviços usam atomic/savepoints e select_for_update na substituição de soluções.
  PostgreSQL aplica bloqueio de linha; SQLite não valida a mesma concorrência.
- PostgreSQL pode recusar strings longas, valores fora da precisão decimal,
  números fora da faixa dos campos, FKs órfãs e violações de UNIQUE/CHECK que
  passaram no SQLite. Validators/choices não são automaticamente executados por
  save/bulk_create. A combinação problema/solução é validada no serviço/clean,
  não por CHECK entre tabelas. Validar dados antes de importar.
- Os testes existentes cobrem ORM, atomic/rollback, UNIQUE/CHECK, migrations,
  sessões e relatórios. A CI existente roda apenas accidents.test_main_flow em
  SQLite e permanece inalterada. Nenhuma auditoria dos registros reais de
  produção foi executada.

## Testes em cada backend

Usar ambiente de desenvolvimento/homologação e credenciais próprias, nunca o
usuário/banco de produção. O runner cria e remove SOMENTE o banco de teste; o
usuário de teste precisa de CREATEDB. Não reutilizar um banco existente nem usar
`--keepdb` no primeiro ensaio. Não definir TEST como banco real.

Com `DJANGO_DEBUG=True` e `DJANGO_DB_BACKEND=sqlite`:

```text
python manage.py check
python manage.py test config.test_database signaling.test_database_compatibility signaling.tests signaling.test_intersection_problems signaling.test_migrations accidents.test_main_flow
```

Repetir os mesmos comandos com `DJANGO_DB_BACKEND=postgresql`, POSTGRES_* de
homologação e `DJANGO_TEST_DB_NAME` exclusivo. No Ubuntu, expandir a aceitação para
`python manage.py test signaling accidents` para cobrir relatórios e sessões.
Não rodar os testes no serviço de produção. O teste novo de fixture preserva IDs,
valores decimais, Unicode, timestamps, relações e verifica o próximo ID dos quatro
modelos após loaddata. Bloqueio/concorrência entre conexões e desempenho exigem
ensaio PostgreSQL adicional; sucesso em SQLite não comprova esses aspectos.

## Procedimento manual de migração

Este roteiro não foi executado. PostgreSQL e um banco de destino NOVO e exclusivo
precisam estar provisionados pelo administrador. Não carregar a fixture sobre
um banco com dados existentes. Todos os comandos de escrita abaixo têm como
alvo esse novo banco, fora do serviço ativo, até a aprovação do corte.

### 1. Preparar e ensaiar

1. Registrar revisão do código, versões Python/Django/driver/PostgreSQL e ambiente
   atual. Usar exatamente a mesma revisão e migrations no ensaio e no corte.
2. Fazer backup verificável do SQLite pelo mecanismo de backup do SQLite, que
   considera WAL/journal. Copiar somente db.sqlite3 com escritores ativos não é
   backup consistente. Testar abertura/restauração da cópia; guardar backup e
   fixture fora do repositório, com acesso restrito. Preservar original, segredos,
   media e configuração de execução atual.
3. Nunca executar migrate na origem real. Selecionar SQLite apontando
   `DJANGO_SQLITE_PATH` para uma CÓPIA do backup. Verificar `showmigrations --plan`
   e, por conexão somente leitura na cópia, `PRAGMA integrity_check` e
   `PRAGMA foreign_key_check`: esperar `ok` e nenhum órfão.
4. Se a cópia estiver em migrations antigas, aplicar migrations apenas nessa
   cópia de trabalho e revisar a conversão 0007. A fixture precisa corresponder
   ao esquema atual do destino. Guardar também o backup anterior à conversão.
5. Com o banco de origem de trabalho parado para gravações, validar:

```bash
python manage.py shell --no-imports < scripts/validate_persistence.py > /caminho/restrito/origem-manifest.json
python manage.py dumpdata contenttypes auth.permission --all --format xml --natural-foreign --natural-primary --indent 2 --output /caminho/restrito/catalogo.xml
python manage.py dumpdata --all --format xml --natural-foreign --exclude contenttypes --exclude auth.permission --indent 2 --output /caminho/restrito/transferencia.xml
```

Usar XML: o serializer JSON padrão do Django trunca microssegundos dos timestamps.
XML preserva a precisão e recusa caracteres de controle não representáveis;
interromper e investigar se houver esse erro, sem limpar dados automaticamente.

O script somente lê. Verifica FKs (inclusive tabelas M2M), full_clean nos quatro
modelos de domínio e produz contagens/hashes normalizados por modelo, com
timestamps completos. Interromper
se houver qualquer erro. Corrigir dados somente em procedimento separado,
revisado e autorizado; nunca descartar registros para fazer a carga passar.
O script carrega os registros serializados em memória: avaliar o tamanho das
sessões e a RAM no ensaio. Não incluir a saída no repositório.

`--all` evita perder registros por filtros de managers. `--natural-foreign`
reconcilia referências às permissões/content types gerados por migrate. O catálogo
é exportado separadamente com chaves primárias naturais e carregado primeiro:
isso preserva também permissões e content types personalizados/antigos, associando
os existentes por identidade natural. Não usar `--natural-primary` no dump principal:
preservar PKs de usuários, grupos e sinalização. A ordem de carga é obrigatória.
Não exportar django_migrations: o destino registra sua própria aplicação do
histórico. O script compara content types/permissões por identidade natural,
sem exigir seus IDs físicos. Ligações M2M são comparadas pelo conteúdo no pai,
com contagens/FKs adicionais nas tabelas intermediárias.

### 2. Carregar e validar o destino de ensaio

Selecionar PostgreSQL explicitamente no ambiente administrativo, conferir host,
usuário e nome do banco NOVO, instalar requisitos no virtualenv de ensaio e executar:

```bash
python manage.py check
python manage.py migrate --plan
python manage.py migrate
python manage.py loaddata /caminho/restrito/catalogo.xml
python manage.py loaddata /caminho/restrito/transferencia.xml
python manage.py shell --no-imports < scripts/validate_persistence.py > /caminho/restrito/destino-manifest.json
diff -u /caminho/restrito/origem-manifest.json /caminho/restrito/destino-manifest.json
python manage.py migrate --check
```

Exigir igualdade dos manifestos, integridade referencial, preservação das PKs,
coordenadas, timestamps, problemas/soluções e sessões. As tabelas geradas precisam
ter a mesma identidade natural; diferenças exigem investigação. Histórico admin
usa GenericForeignKey/object_id: revisar seus alvos separadamente (referências a
objetos já excluídos podem ser históricas legítimas). Validar login, grupos e
permissões, mapa, edição de pontos e geração de DOCX usando o destino de ensaio.
Manter SECRET_KEY, cookies e serializer de sessão para preservar sessões; revisar
expiração antes de considerar ausência de uma sessão como perda.

### 3. Sequências

loaddata usa o mecanismo de reset de sequências do backend do Django. Não assumir
que isso basta: conferir cada tabela com ID automático, inclusive auth/admin e
M2M. Listar tabelas/colunas identity ou serial no catálogo PostgreSQL; para cada
uma, consultar `pg_get_serial_sequence('tabela', 'id')`, `MAX(id)` e `last_value,
is_called` da sequência retornada. O próximo valor deve superar MAX(id); tabela
vazia exige sequência em estado inicial válido. Não chamar nextval só para ler:
isso modifica a sequência. A comparação de manifestos não valida sequências.

Se necessário, gerar SQL revisável para todos os apps com sequências:

```bash
python manage.py sqlsequencereset signaling auth admin contenttypes > /caminho/restrito/sequencias.sql
```

Revisar e executar esse arquivo somente no destino novo pelo cliente administrativo
PostgreSQL; conferir novamente o estado. Sessions usa chave textual. Não executar
reset na origem. O teste de fixture verifica inserções após a carga nos quatro
modelos de domínio; no ensaio testar também criação de usuários/grupos e relações
M2M. IDs podem conter lacunas legítimas.

### 4. Corte controlado e rollback

1. Reservar janela de manutenção. O administrador deve interromper TODOS os
   escritores (requisições, sessões e processos auxiliares), usando seu processo
   operacional existente. Não permitir escrita nos dois bancos simultaneamente.
2. Fazer novo backup consistente final; repetir o processo numa cópia final e num
   novo destino exclusivo. Não reutilizar o destino de ensaio com seus dados.
   Repetir manifestos, integridade e sequências antes de liberar tráfego.
3. O administrador deve definir DJANGO_DB_BACKEND=postgresql e POSTGRES_* no
   ambiente do serviço existente e reiniciar por seu processo habitual.
   Este trabalho não altera Nginx, Gunicorn, systemd nem arquivos reais de segredos.
4. Antes de reabrir gravações, validar login, leitura dos pontos/mapa e relatório,
   observando logs sem credenciais. Preservar backup SQLite e um backup PostgreSQL
   da carga validada. Liberar gravações somente depois da aceitação.
5. Se falhar antes de novas gravações: manter manutenção, restaurar explicitamente
   DJANGO_DB_BACKEND=sqlite e o caminho do SQLite preservado, mesma revisão/chave,
   e reiniciar pelo processo existente. Não reverter migrations nem excluir bancos.
6. Se já houve gravações no PostgreSQL: parar escritores e fazer backup dos dois
   lados. Voltar diretamente ao SQLite antigo perderia essas gravações. Exigir
   reconciliação/exportação para uma NOVA cópia SQLite compatível, validar novamente
   contagens/hashes/FKs e obter aprovação operacional antes de mudar o serviço.
   Não há sincronização automática nem rollback transparente.

## Limitações

Não instala PostgreSQL nem valida a VM. Testes reais PostgreSQL, permissões do
usuário, backup/restauração, tamanho das sessões, concorrência e duração da janela
precisam ser confirmados manualmente. Erros de configuração agora impedem iniciar
produção sem escolha explícita; preparar essa variável antes de adotar o código,
mesmo enquanto o banco continuar SQLite.
