# PostgreSQL local - desenvolvimento e testes
# Nunca utilizar credenciais de produção.

$env:DJANGO_DB_BACKEND = "postgresql"
$env:POSTGRES_DB = "analise_dev"
$env:POSTGRES_USER = "analise_dev_user"
$env:POSTGRES_HOST = "127.0.0.1"
$env:POSTGRES_PORT = "5432"
$env:DJANGO_TEST_DB_NAME = "test_analise_dev"

# Solicita a senha sem exibi-la no terminal.
$senha = Read-Host "Senha do PostgreSQL local" -AsSecureString
$env:POSTGRES_PASSWORD = [System.Net.NetworkCredential]::new("", $senha).Password
Remove-Variable senha

Write-Host "Ambiente PostgreSQL local configurado."