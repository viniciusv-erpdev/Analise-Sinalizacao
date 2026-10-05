# Primeira camada de deploy

Arquitetura planejada: **Nginx -> Gunicorn -> Django -> SQLite**.
Gunicorn executa a aplicação WSGI; systemd inicia o processo no boot, supervisiona sua execução e reinicia em caso de falha. SQLite permanece inalterado.

## Template do serviço

Substitua em `gunicorn.service.example`:

- `<APP_USER>`: usuário Linux que executará a aplicação.
- `<PROJECT_PATH>`: caminho absoluto da raiz do projeto, onde está `manage.py`.
- `<VENV_PATH>`: caminho absoluto do virtualenv deste projeto no Ubuntu.
- `<ENV_FILE_PATH>`: caminho absoluto de um arquivo de ambiente externo ao checkout, em um diretório administrativo como `/etc`. O caminho definitivo depende do servidor.

O comando usa `<VENV_PATH>/bin/gunicorn`, `config.wsgi:application`, **1 worker síncrono** e bind exclusivo em **127.0.0.1:8000**. A porta não deve ser exposta diretamente aos usuários. O virtualenv não precisa ser ativado por shell. `gunicorn==26.2.0` já está declarado em `requirements.txt`; nenhuma dependência foi instalada nesta etapa.

O serviço roda em primeiro plano, registra saída no journal e reinicia em falhas após 5 segundos, com limite de 5 tentativas em 60 segundos. A parada permite até 45 segundos antes de encerramento forçado. O timeout de worker permanece no padrão do Gunicorn (30 segundos); processamento pesado de CSV/relatórios poderá exigir ajuste após medição no servidor. Não houve tuning nesta etapa.

## Ambiente e permissões futuras

O arquivo indicado por `EnvironmentFile` é obrigatório e deverá ser criado **somente no servidor, fora do Git**, com linhas `NOME=valor` (sem `export`):

- `DJANGO_SECRET_KEY`: segredo real de produção.
- `DJANGO_DEBUG=False`.
- `DJANGO_ALLOWED_HOSTS`: hosts reais autorizados, separados por vírgulas.

Proteja esse arquivo com proprietário `root` e modo `0600`. O gerenciador systemd do sistema lê o arquivo e fornece as variáveis ao processo; o usuário da aplicação não precisa ler o arquivo diretamente. Não há segredo real nem arquivo de ambiente criado neste repositório.

O usuário do serviço precisará de acesso de leitura ao projeto e ao virtualenv, execução dos binários e travessia dos diretórios pais. Precisará também de **escrita em `<PROJECT_PATH>/db.sqlite3` e no diretório `<PROJECT_PATH>`**, pois SQLite cria arquivos auxiliares junto ao banco. Proprietários e permissões serão definidos no servidor; nada foi alterado agora.

O usuário também precisará de um diretório temporário gravável e de local gravável para o cache/configuração do Matplotlib. Se os locais padrão do servidor não atenderem, defina `TMPDIR` e `MPLCONFIGDIR` no mesmo arquivo de ambiente, apontando para diretórios previamente criados e graváveis pelo serviço. Nenhuma mudança no código ou caminho definitivo foi necessária nesta etapa.

## Comandos previstos no Ubuntu

Após substituir os placeholders, preparar o ambiente e instalar o template como `/etc/systemd/system/gunicorn.service`, estão previstos:

```sh
sudo systemctl daemon-reload
sudo systemctl enable gunicorn.service
sudo systemctl start gunicorn.service
sudo systemctl status gunicorn.service
sudo journalctl -u gunicorn.service -n 100 --no-pager
```

**Esses comandos não foram executados**: esta etapa foi preparada no Windows, fora do servidor Linux definitivo. O nome `gunicorn.service` acima é o nome proposto para instalação do template; ajuste os comandos se escolher outro nome.

Nginx, arquivos estáticos em produção, HTTPS, preparação do servidor e ajustes baseados em medições ficam para etapas posteriores. O template não serve arquivos estáticos por si só.
