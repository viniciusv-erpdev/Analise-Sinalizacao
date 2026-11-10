"""Configuracao do Gunicorn para Analise-Sinalizacao."""

workers = 2
worker_class = "sync"
bind = "127.0.0.1:8000"

timeout = 120

accesslog = "-"
errorlog = "-"
