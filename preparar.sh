#!/bin/sh
# Prepara o .env: gera os segredos que faltam e deixa os campos do Firebase para preencher.
# Só acrescenta o que falta: nunca muda um valor que já está no .env.
set -eu
cd "$(dirname "$0")"
umask 077
touch .env
mkdir -p credenciais
aleatorio() { python3 -c "import secrets; print(secrets.token_urlsafe($1))"; }
gerar() { grep -q "^$1=" .env || echo "$1=$(aleatorio "$2")" >> .env; }
campo() { grep -q "^$1=" .env || echo "$1=" >> .env; }
gerar SESSAO_SEGREDO 48
gerar CAFE_PONTE_SEGREDO 48
gerar LDAP_SENHA_LEITOR 24
gerar LDAP_SENHA_PESSOAS 18
gerar OIDC_SEGREDO 32
gerar KEYCLOAK_ADMIN_SENHA 18
for c in FIREBASE_PROJECT_ID FIREBASE_WEB_API_KEY FIREBASE_AUTH_DOMAIN GOOGLE_WEB_CLIENT_ID GOOGLE_HD MS_CLIENT_ID MS_TENANT_ID CAFE_SP_LOGIN_URL OIDC_EMISSOR OIDC_CLIENT_ID; do
  campo "$c"
done
faltam=""
for c in FIREBASE_PROJECT_ID FIREBASE_WEB_API_KEY FIREBASE_AUTH_DOMAIN; do
  grep -q "^$c=." .env || faltam="$faltam $c"
done
[ -f credenciais/conta.json ] || echo "Falta a chave de serviço do projeto em credenciais/conta.json."
[ -z "$faltam" ] || echo "Falta preencher no .env:$faltam"
[ -n "$faltam" ] || [ ! -f credenciais/conta.json ] || echo "Pronto: docker compose up -d --build"
