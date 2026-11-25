# OpenLDAP de teste, com TLS e três pessoas fictícias. Não usar fora do teste.
FROM debian:bookworm-slim
RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends slapd ldap-utils openssl ca-certificates \
 && rm -rf /var/lib/apt/lists/*
COPY slapd.conf /etc/ldap/poc-slapd.conf
COPY seed.ldif /etc/ldap/poc-seed.ldif
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
EXPOSE 389 636
ENTRYPOINT ["/entrypoint.sh"]
