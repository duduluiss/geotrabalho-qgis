# Script de publicação do GeoTrabalho no GitHub
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

Write-Host "Iniciando publicador do GeoTrabalho para o GitHub..." -ForegroundColor Cyan
python github_auto_publish.py start
python github_auto_publish.py complete
