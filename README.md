# poc-firebase

Prova de conceito do login do IoTEdu pelo **Firebase Authentication**, com os tipos de conta que as
instituições usam: Google, Microsoft, LDAP, CAFe e o login único próprio de uma instituição (OIDC).

Ela existe para testar a decisão "autenticação 100% via Firebase" antes de mexer no sistema. Roda contra um
projeto Firebase de verdade, sem emulador, e não depende do código do IoTEdu.

A análise completa, com custos, limites e as respostas às perguntas da reunião de 25/11/2026, está em
[ANALISE-FIREBASE.md](ANALISE-FIREBASE.md). Este README explica o que a prova faz e como rodar.

## O que foi provado

| O quê | Como | Resultado |
|---|---|---|
| A lógica do backend (regras, rotas, banco, LDAP, login único) | 160 testes automáticos | Todos passam |
| Tokens emitidos e assinados pelo Firebase | 10 testes de ponta a ponta contra o projeto real | Todos passam |
| A página, com o SDK web do Firebase | 4 conferências num Chromium sem tela; 5 com o Keycloak de teste | Todas passam |
| Login único por um Keycloak de verdade, lendo o OpenLDAP de teste | Num Chromium sem tela | Entrou; é a mesma pessoa do login por LDAP |
| Login com Microsoft, conta de um diretório do Entra ID | Feito à mão, na página | Entrou aprovado |
| Login com Google, conta pessoal | Feito à mão, na página | Ficou pendente, como deve |

Ainda não testado: Google com conta de Workspace de uma instituição, a CAFe real, o LDAP e o login único
de uma instituição, e o Active Directory.

O resumo das respostas à reunião de 25/11 está em [RELATORIO-FIREBASE.md](RELATORIO-FIREBASE.md).

## Como funciona

O Firebase vira o lugar único onde ficam as contas e de onde saem os tokens. Todos os logins terminam
igual: uma conta no Firebase com três informações gravadas por nós (os *claims*) e a sessão do sistema.

| Claim | O que guarda | Exemplo |
|---|---|---|
| `inst` | A instituição em que a pessoa está | `unia` |
| `papel` | O papel dela | `USER` |
| `estado` | Se a entrada foi aprovada | `ativo` ou `pendente` |

### Os cinco caminhos

```
Google, Microsoft   1. A página abre a janela de login do Firebase.
                    2. O Firebase devolve dois tokens: o dele e o do provedor (Google ou Microsoft).
                    3. A página manda os dois ao backend.
                    4. O backend confere os dois, decide, grava os claims e abre a sessão.

LDAP                1. A página manda usuário e senha ao backend.
                    2. O backend procura a pessoa no LDAP da instituição e testa a senha (bind), por TLS.
                    3. O backend cria a conta no Firebase, grava os claims e pede um "custom token".
                    4. A página troca o custom token por uma sessão do Firebase.

CAFe                1. Uma janela leva a pessoa ao login da universidade dela (SAML).
                    2. O SP SAML do IoTEdu confirma quem é e avisa o backend com um token de 120 segundos.
                    3. O backend cria a conta, grava os claims e guarda um código de uso único.
                    4. A página troca o código por um custom token, e o custom token por uma sessão.

Login único da      1. Uma janela leva a pessoa à tela de login da própria instituição (OIDC).
instituição         2. A instituição devolve um código ao backend, que o troca por um token assinado por ela.
                    3. O backend confere o token, cria a conta, grava os claims e guarda um código de uso único.
                    4. A página troca o código por um custom token, e o custom token por uma sessão.
```

O Firebase faz Google e Microsoft sozinho. Ele **não** fala LDAP nem aceita uma federação SAML como a
CAFe, e só fala OIDC genérico na versão paga por usuário. Nesses três casos quem prova quem é a pessoa é
o nosso backend, e o Firebase só recebe o resultado. É para isso que serve o *custom token*: um token que
o backend assina com a chave do projeto e que o Firebase troca por uma sessão.

No código, os três terminam na mesma função, `entrar_por_custom_token`, em `backend/poc/app.py`. Um
login novo desse tipo é um arquivo que prova a pessoa, uma regra em `regras.py` e uma rota.

### E se a instituição usa outra coisa?

| O que a instituição tem | Caminho | Na prova |
|---|---|---|
| Google Workspace | Google, pelo Firebase | Feito |
| Microsoft 365 ou Entra ID | Microsoft, pelo Firebase | Feito |
| OpenLDAP | LDAP | Feito, contra um OpenLDAP de teste |
| Active Directory | LDAP, com `tipo: ad` no cadastro. Se o diretório estiver sincronizado com o Entra ID, o login da Microsoft também serve. | Só o cadastro. Não foi testado contra um AD. |
| Keycloak, ADFS, Shibboleth com OIDC ou outro login único | Login único da instituição (OIDC) | Feito, contra um provedor simulado e contra um Keycloak de teste |
| CAFe | SP SAML do IoTEdu e a ponte | A ponte, com uma universidade simulada |
| Login único só com SAML, fora da CAFe | O mesmo SP SAML da CAFe, com o provedor da instituição cadastrado nele | Não foi testado |

Com Keycloak na frente do LDAP, a senha deixa de passar pelo nosso backend: ela é digitada na tela da
instituição. É a diferença prática entre os caminhos LDAP e login único.

### Quem entra na hora e quem espera

Entra na hora quem prova, pelo próprio login, que é de uma instituição cadastrada. Os outros entram como
**pendentes**, à espera de aprovação. O e-mail sozinho nunca serve de prova:

| Login | O que prova que a conta é da instituição |
|---|---|
| Google | O domínio do Google Workspace que administra a conta (campo `hd` do token do Google) |
| Microsoft | O diretório do Entra ID da conta (campo `tid` do token da Microsoft) |
| LDAP | A senha conferiu no diretório cadastrado para aquela instituição |
| CAFe | A universidade que autenticou (o que vem depois do `@` no identificador da pessoa) |
| Login único | O token veio assinado pelo provedor cadastrado para aquela instituição |

Exemplos: uma conta Gmail pessoal entra como pendente. Uma conta Microsoft de outro diretório, mesmo com
e-mail da universidade, também. A regra está em `backend/poc/regras.py`, e as instituições em
`instituicoes.yaml`.

## O que você precisa

- Docker com Compose.
- Uma conta Google, para criar o projeto Firebase. É gratuito: não precisa de cartão nem do upgrade para
  Identity Platform.
- Para a Microsoft (opcional): acesso a um diretório do Entra ID. Uma conta Microsoft pessoal sozinha não
  serve; veja o passo 3.

## Passo 1: criar o projeto Firebase

Em `console.firebase.google.com`:

1. **Criar um projeto.** Pode desligar o Analytics.
2. **Ligar o Google.** Segurança → Authentication → Vamos começar → Método de login → Google → Ativar.
   Depois abra o Google de novo na lista → "Configuração do SDK da Web" → copie o **ID do cliente da Web**.
3. **Permitir várias contas por e-mail.** Authentication → Configurações → Vinculação de contas de usuário →
   "Criar várias contas para cada provedor de identidade". Sem isso, quem entrou com Google não consegue
   entrar depois com Microsoft no mesmo e-mail.
4. **Registrar um app Web.** Na visão geral do projeto, "+ Adicionar app" → Web (`</>`). Copie `apiKey`,
   `authDomain` e `projectId`.
5. **Gerar a chave de serviço.** Configurações do projeto → Contas de serviço → Gerar nova chave privada.
   Salve o arquivo baixado como `credenciais/conta.json`, nesta pasta.
6. **Conferir** em Authentication → Configurações → Domínios autorizados que `localhost` está na lista.

## Passo 2: configurar a prova

```sh
./preparar.sh
```

O script cria o `.env`, gera os segredos locais e diz o que falta. Preencha no `.env`:

| Variável | De onde vem |
|---|---|
| `FIREBASE_PROJECT_ID` | `projectId` do app Web |
| `FIREBASE_WEB_API_KEY` | `apiKey` do app Web |
| `FIREBASE_AUTH_DOMAIN` | `authDomain` do app Web |
| `GOOGLE_WEB_CLIENT_ID` | ID do cliente da Web (passo 1, item 2). Sem ele o login com Google fica desligado. |
| `GOOGLE_HD` | Opcional. Domínio do Google Workspace cujas contas entram aprovadas na Universidade A. |
| `MS_CLIENT_ID` | ID do aplicativo no Entra ID (passo 3). Sem ele o login com Microsoft fica desligado. |
| `MS_TENANT_ID` | ID do diretório do Entra ID cujas contas entram aprovadas na Universidade A (passo 3). |
| `CAFE_SP_LOGIN_URL` | Endereço do SP SAML de verdade. Vazio, a prova usa uma universidade simulada. |
| `OIDC_EMISSOR`, `OIDC_CLIENT_ID` | Opcional. O login único da Universidade B (passo 4). Vazio, fica desligado. |

## Passo 3 (opcional): ligar a Microsoft

1. Em `portal.azure.com` → Microsoft Entra ID → Registros de aplicativo → Novo registro.
   - Tipos de conta: "Contas em qualquer diretório organizacional" para atender várias instituições. "Somente
     minha organização" serve para testar com o seu próprio diretório.
   - URI de redirecionamento, tipo Web: `https://<projectId>.firebaseapp.com/__/auth/handler`
2. Copie o **ID do aplicativo (cliente)** e o **ID do diretório (locatário)**.
3. Certificados e segredos → Novo segredo do cliente → copie o **Valor**. Ele tem validade e precisa ser
   renovado.
4. No Firebase: Authentication → Método de login → Adicionar novo provedor → Microsoft. Cole o ID do
   aplicativo e o segredo.
5. No `.env`, ponha o ID do aplicativo em `MS_CLIENT_ID` e o ID do diretório em `MS_TENANT_ID`.

Registrar o aplicativo exige um diretório do Entra ID. Uma conta Microsoft pessoal não registra aplicativo
fora de um diretório. Quem não tem um diretório de organização consegue um com uma assinatura do Azure.

## Passo 4 (opcional): ligar o Keycloak de teste

A Universidade D já entra por um login único simulado, sem configurar nada. Este passo liga um Keycloak de
verdade como login único da Universidade B, lendo as pessoas do mesmo OpenLDAP de teste.

1. No `.env`:
   ```
   OIDC_EMISSOR=http://localhost:8089/realms/unib
   OIDC_CLIENT_ID=iotedu-poc
   ```
   O `OIDC_SEGREDO` já foi gerado pelo `preparar.sh`.
2. Depois do passo 5, suba o Keycloak: `docker compose --profile sso up -d keycloak`. Ele demora cerca de
   um minuto para responder.

Na página, a Universidade B passa a ter dois logins para a mesma pessoa: o formulário do LDAP e o botão do
Keycloak. O console do Keycloak fica em `http://localhost:8089`, usuário `admin`, senha em
`KEYCLOAK_ADMIN_SENHA`.

## Passo 5: rodar

```sh
docker compose up -d --build              # OpenLDAP de teste e backend
docker compose --profile teste build      # as imagens dos testes; refaça depois de mudar o código
docker compose run --rm testes            # 160 testes; não precisam do projeto Firebase
docker compose run --rm testes-firebase   # 10 testes de ponta a ponta contra o Firebase
docker compose run --rm navegador         # a página num Chromium sem tela
```

Depois abra `http://localhost:8088`. A página tem os cinco logins e mostra, depois de entrar, os claims
do token e o que o backend respondeu.

| Para testar | Use |
|---|---|
| LDAP | Universidade B, usuário `ana`, `bruno` ou `carla`. A senha está em `LDAP_SENHA_PESSOAS`, no `.env`. |
| CAFe | Universidade A. O botão abre uma universidade simulada; é só clicar em Entrar. |
| Login único | Universidade D. O botão abre um provedor simulado; é só clicar em Entrar. Com o passo 4, a Universidade B abre o Keycloak: usuário `ana`, mesma senha do LDAP. |
| Google | Universidade A. Com Gmail pessoal você entra como pendente. Para entrar aprovado, use uma conta de Workspace e ponha o domínio dela em `GOOGLE_HD`, no `.env`. |
| Microsoft | Universidade A, com uma conta do diretório informado em `MS_TENANT_ID`. |

Mudou o `instituicoes.yaml` ou o `.env`? Rode `docker compose up -d --build` de novo.

Para desligar e apagar os dados locais: `docker compose down -v`.

## Os testes

| Comando | O que roda | O que prova |
|---|---|---|
| `docker compose run --rm testes` | `tests/unit` e `tests/rotas` | O nosso código: a regra de entrada, a conferência dos tokens do Google e da Microsoft, as rotas, o LDAP (contra um OpenLDAP de verdade, com TLS), a ponte da CAFe, o login único (contra o provedor simulado). Aqui o Firebase é trocado por um substituto. |
| `docker compose run --rm testes-firebase` | `tests/firebase_real` | O Firebase: o custom token é aceito, os claims vêm no token, token adulterado é recusado, sair invalida a renovação. |
| `docker compose run --rm navegador` | `navegador/conferir.py` | A página, num navegador de verdade, com o SDK web falando com o Firebase. |

Os testes contra o Firebase criam contas `ldap:...`, `cafe:...` e `oidc:...` no projeto e as apagam no
fim.

Google e Microsoft não entram nos testes automáticos, porque as telas de login deles não aceitam navegador
automatizado. O roteiro para conferir à mão está na seção 5 da análise.

## O que tem em cada pasta

| Caminho | O que é |
|---|---|
| `backend/poc/regras.py` | Quem entra na hora, quem fica pendente, quem é recusado. Não usa rede; é a parte a levar para o sistema. |
| `backend/poc/provedores.py` | Confere o token do Google e o da Microsoft: assinatura, audiência, emissor e validade. |
| `backend/poc/firebase.py` | As chamadas ao Firebase: verificar token, criar conta, gravar claims, emitir custom token. |
| `backend/poc/ldap_auth.py` | Busca e bind no LDAP da instituição, com TLS. |
| `backend/poc/ponte_cafe.py` | Recebe o token do SP SAML e devolve os dados da pessoa. |
| `backend/poc/oidc_auth.py` | Fala com o login único da instituição: descoberta, PKCE, troca do código e conferência do token. |
| `backend/poc/demo_oidc.py` | O login único simulado. Só existe no ambiente de teste. |
| `backend/poc/conferir_ldap.py` | Confere o cadastro LDAP de uma instituição, passo a passo. |
| `backend/poc/sessao.py` | Descobre quem faz o pedido, pelo cookie ou pelo token no cabeçalho. |
| `backend/poc/limite.py` | Limite de tentativas de senha, com espera crescente. |
| `backend/poc/repositorio.py` | Banco local (SQLite): pessoas e os logins de cada uma. |
| `backend/poc/config.py` | Lê o `.env` e o `instituicoes.yaml`, e recusa configuração insegura. |
| `backend/poc/app.py` | As rotas. |
| `instituicoes.yaml` | Cadastro das instituições: domínios, logins ligados, diretório Microsoft, LDAP, escopo da CAFe, login único. |
| `pagina/` | A página de demonstração, sem etapa de build. |
| `tests/` | Os testes. |
| `navegador/` | A conferência da página num Chromium sem tela. |
| `ldap/` | A imagem do OpenLDAP de teste, com três pessoas fictícias. |
| `keycloak/` | O realm do Keycloak de teste (passo 4). |
| `projecao.py` | Gera as tabelas de usuários ativos, cota e custo da análise. |
| `credenciais/` | A chave de serviço do projeto. Não entra no git. |

## As rotas

| Rota | O que faz |
|---|---|
| `POST /api/auth/firebase/session` | Recebe o token do Firebase (e o do provedor), confere, decide e abre a sessão. |
| `POST /api/auth/ldap/login` | Confere usuário e senha no LDAP e devolve um custom token. |
| `GET /api/auth/cafe/login` | Começa o login pela CAFe, numa janela. |
| `GET /api/auth/cafe/finish` | Recebe o token do SP SAML. |
| `POST /api/auth/cafe/token` | Troca o código de uso único pelo custom token. |
| `GET /api/auth/oidc/login?inst=...` | Começa o login único da instituição, numa janela. |
| `GET /api/auth/oidc/callback` | Recebe o código do provedor, troca pelo token dele e confere. |
| `POST /api/auth/oidc/token` | Troca o código de uso único pelo custom token. |
| `POST /api/auth/logout` | Encerra a sessão e invalida a renovação no Firebase. |
| `GET /api/me` | Quem está logado. Aceita o cookie ou `Authorization: Bearer <token do Firebase>`. |
| `GET /api/painel` | Exemplo de rota que exige entrada aprovada. |

## Segredos e cuidados

- **`credenciais/conta.json` é o arquivo mais sensível.** Quem o tem entra como qualquer conta do projeto.
  Ele e o `.env` estão no `.gitignore`; confira com `git status` antes de qualquer commit.
- **Se a chave ou o segredo da Microsoft vazarem, troque.** A chave: Configurações do projeto → Contas de
  serviço → gerenciar chaves. O segredo: Certificados e segredos, no Entra ID, e depois no provedor
  Microsoft do Firebase.
- **O backend recusa configuração insegura.** Ele não sobe sem projeto e sem chave, com o emulador do
  Firebase configurado, ou com segredo curto ou padrão. A mensagem de erro diz o que falta:
  `docker compose logs backend`.
- **`AMBIENTE_DE_TESTE=1`**, que o `docker-compose.yml` liga, cria a universidade simulada, o login único
  simulado e a rota de limpeza dos testes (`/demo/...`). Elas só são aceitas com a página em `localhost`
  e não podem existir numa instalação de verdade. Fora dele, o provedor do login único tem de ser `https`.
- **A senha do LDAP passa pelo backend.** Ela não é registrada nem guardada, e só trafega por TLS. No
  login único ela não passa: a pessoa a digita na tela da instituição.

## Ligar uma instituição de verdade

O cadastro fica no `instituicoes.yaml`. O que pedir a cada instituição:

**LDAP (OpenLDAP ou Active Directory).** O endereço `ldaps://`, a base onde ficam as pessoas, uma conta de
serviço só de leitura e o certificado da CA que assinou o certificado do servidor. O backend precisa
alcançar a porta 636 do diretório.

```yaml
  ufx:
    nome: Universidade X
    dominios: [ufx.edu.br]
    metodos: [ldap]
    ldap:
      tipo: openldap            # ou ad
      url: ldaps://ldap.ufx.edu.br:636
      base: ou=people,dc=ufx,dc=edu,dc=br
      bind_dn: cn=iotedu,ou=services,dc=ufx,dc=edu,dc=br
      senha_env: LDAP_UFX_SENHA  # a senha da conta de serviço vem do ambiente, nunca do arquivo
      ca: /certs/ufx-ca.crt
```

Com `tipo: ad` o filtro passa a procurar por `sAMAccountName` e ignora conta desativada. Se o diretório
foge do padrão, `filtro`, `attr_uid`, `attr_mail` e `attr_nome` podem ser escritos no cadastro.

Antes de abrir o login para as pessoas, confira o cadastro. O comando diz em qual passo parou: conexão e
certificado, conta de serviço, base, filtro, atributos e, por fim, o login de uma pessoa.

```sh
docker compose exec backend python -m poc.conferir_ldap unib        # até a leitura da base
docker compose exec backend python -m poc.conferir_ldap unib ana    # pede a senha e testa o login
```

**Login único (OIDC).** A instituição registra o IoTEdu como cliente no provedor dela, com o fluxo de
código de autorização e o endereço de retorno `https://<painel>/api/auth/oidc/callback`, e informa o
emissor, o identificador do cliente e o segredo.

```yaml
    metodos: [oidc]
    oidc:
      rotulo: Login único da UFX
      emissor: https://sso.ufx.edu.br/realms/ufx
      client_id: iotedu
      segredo_env: OIDC_UFX_SEGREDO
```

Quem tem conta no provedor entra aprovado naquela instituição. O e-mail só liga o login a uma pessoa que
já existe quando o provedor diz que o verificou e ele é de um domínio da instituição.

**CAFe.** O SP SAML é o que o IoTEdu já tem; ele precisa estar cadastrado na federação. Aqui entram o
endereço dele em `CAFE_SP_LOGIN_URL`, o mesmo segredo de ponte nos dois lados (`CAFE_PONTE_SEGREDO`) e o
escopo da instituição em `cafe_escopos`.

## Se algo der errado

| Sintoma | Causa provável |
|---|---|
| O backend não sobe | Falta um campo no `.env` ou a chave em `credenciais/conta.json`. Veja `docker compose logs backend`. |
| Botão do Google ou da Microsoft apagado | Falta `GOOGLE_WEB_CLIENT_ID` ou `MS_CLIENT_ID` no `.env`. A página mostra o aviso no topo. |
| Erro `AADSTS...` na janela da Microsoft | Quase sempre a URI de redirecionamento do aplicativo, ou o tipo de conta do aplicativo. |
| "Token do provedor inválido" | O ID do cliente no `.env` não é o do provedor ligado no Firebase. |
| Entrou, mas como pendente | A conta não prova instituição: confira `GOOGLE_HD` ou `MS_TENANT_ID` no `.env`. |
| "Muitas tentativas. Aguarde." | O limite de senha errada no LDAP. Espere o tempo indicado. |
| "O login da instituição não foi concluído." | O provedor está fora do ar, o segredo do cliente não confere ou o endereço de retorno não está cadastrado nele. Veja `docker compose logs backend`. |

## O que esta prova não é

- Não é o código de produção. É a prova de que o desenho funciona, com a regra de entrada escrita e
  testada. Como encaixar no sistema está na seção 8 da análise.
- O OpenLDAP, o Keycloak, a universidade simulada da CAFe e o login único simulado são de teste.
- As instituições do `instituicoes.yaml` são fictícias (domínios `.test`). Os identificadores reais de quem
  testa entram pelo `.env`.
