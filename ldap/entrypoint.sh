#!/bin/sh
# Gera a CA e o certificado de teste, semeia o diretório e sobe o slapd.
set -eu

: "${LDAP_SENHA_LEITOR:?defina LDAP_SENHA_LEITOR}"
: "${LDAP_SENHA_PESSOAS:?defina LDAP_SENHA_PESSOAS}"

mkdir -p /etc/ldap/tls /certs-pub /var/lib/ldap-poc /run/slapd
cd /etc/ldap/tls
if [ ! -f ldap.key ]; then
  openssl req -x509 -newkey rsa:2048 -nodes -days 30 -subj "/CN=CA de teste IoTEdu PoC" \
    -keyout ca.key -out ca.crt 2>/dev/null
  openssl req -newkey rsa:2048 -nodes -subj "/CN=ldap" -keyout ldap.key -out ldap.csr 2>/dev/null
  printf 'subjectAltName=DNS:ldap,DNS:localhost\n' > san.ext
  openssl x509 -req -in ldap.csr -CA ca.crt -CAkey ca.key -CAcreateserial -days 30 \
    -extfile san.ext -out ldap.crt 2>/dev/null
  rm -f ca.key ldap.csr san.ext
fi
# Só a CA (pública) vai para o volume que o backend lê.
cp ca.crt /certs-pub/ca.crt
chmod 644 /certs-pub/ca.crt

hash() { slappasswd -s "$1"; }
ROOTPW=$(hash "$(openssl rand -hex 24)")
sed "s|@@ROOTPW@@|${ROOTPW}|" /etc/ldap/poc-slapd.conf > /etc/ldap/slapd-run.conf

if [ ! -f /var/lib/ldap-poc/data.mdb ]; then
  sed -e "s|@@HASH_LEITOR@@|$(hash "$LDAP_SENHA_LEITOR")|" \
      -e "s|@@HASH_ANA@@|$(hash "$LDAP_SENHA_PESSOAS")|" \
      -e "s|@@HASH_BRUNO@@|$(hash "$LDAP_SENHA_PESSOAS")|" \
      -e "s|@@HASH_CARLA@@|$(hash "$LDAP_SENHA_PESSOAS")|" \
      /etc/ldap/poc-seed.ldif > /tmp/seed.ldif
  slapadd -f /etc/ldap/slapd-run.conf -l /tmp/seed.ldif
  rm -f /tmp/seed.ldif
fi

exec slapd -f /etc/ldap/slapd-run.conf -h "ldaps://0.0.0.0:636/ ldap://0.0.0.0:389/" -d 256
