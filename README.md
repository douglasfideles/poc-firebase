# poc-firebase

Prova de conceito do login do IoTEdu pelo **Firebase Authentication**, com os quatro tipos de conta que as
instituições usam: Google, Microsoft, LDAP e CAFe.

Ela existe para testar a decisão "autenticação 100% via Firebase" antes de mexer no sistema. Roda contra um
projeto Firebase de verdade, sem emulador, e não depende do código do IoTEdu.

A análise completa, com custos, limites e as respostas às perguntas da reunião de 25/11/2026, está em
[ANALISE-FIREBASE.md](ANALISE-FIREBASE.md). Este README explica o que a prova faz e como rodar.

## O que foi provado

| O quê | Como | Resultado |
|---|---|---|
| A lógica do backend (regras, rotas, banco, LDAP) | 100 testes automáticos | Todos passam |
| Tokens emitidos e assinados pelo Firebase | 9 testes de ponta a ponta contra o projeto real | Todos passam |
| A página, com o SDK web do Firebase | 3 conferências num Chromium sem tela | Todas passam |
| Login com Microsoft, conta de um diretório do Entra ID | Feito à mão, na página | Entrou aprovado |
| Login com Google, conta pessoal | Feito à mão, na página | Ficou pendente, como deve |

Ainda não testado: Google com conta de Workspace de uma instituição, a CAFe real e o LDAP de uma
instituição.

## Como funciona

O Firebase vira o lugar único onde ficam as contas e de onde saem os tokens. Os quatro logins terminam
igual: uma conta no Firebase com três informações gravadas por nós (os *claims*) e a sessão do sistema.

| Claim | O que guarda | Exemplo |
|---|---|---|
| `inst` | A instituição em que a pessoa está | `unia` |
| `papel` | O papel dela | `USER` |
| `estado` | Se a entrada foi aprovada | `ativo` ou `pendente` |

### Os quatro caminhos

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
```

O Firebase faz Google e Microsoft sozinho. Ele **não** fala LDAP nem aceita uma federação SAML como a
CAFe. Nesses dois casos quem prova quem é a pessoa é o nosso backend, e o Firebase só recebe o resultado.
É para isso que serve o *custom token*: um token que o backend assina com a chave do projeto e que o
Firebase troca por uma sessão.

### Quem entra na hora e quem espera

Entra na hora quem prova, pelo próprio login, que é de uma instituição cadastrada. Os outros entram como
**pendentes**, à espera de aprovação. O e-mail sozinho nunca serve de prova:

| Login | O que prova que a conta é da instituição |
|---|---|
| Google | O domínio do Google Workspace que administra a conta (campo `hd` do token do Google) |
| Microsoft | O diretório do Entra ID da conta (campo `tid` do token da Microsoft) |
| LDAP | A senha conferiu no diretório cadastrado para aquela instituição |
| CAFe | A universidade que autenticou (o que vem depois do `@` no identificador da pessoa) |

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

## Passo 4: rodar

```sh
docker compose up -d --build              # OpenLDAP de teste e backend
docker compose run --rm testes            # 100 testes; não precisam do projeto Firebase
docker compose run --rm testes-firebase   # 9 testes de ponta a ponta contra o Firebase
docker compose run --rm navegador         # a página num Chromium sem tela
```

Depois abra `http://localhost:8088`. A página tem os quatro logins e mostra, depois de entrar, os claims
do token e o que o backend respondeu.

| Para testar | Use |
|---|---|
| LDAP | Universidade B, usuário `ana`, `bruno` ou `carla`. A senha está em `LDAP_SENHA_PESSOAS`, no `.env`. |
| CAFe | Universidade A. O botão abre uma universidade simulada; é só clicar em Entrar. |
| Google | Universidade A. Com Gmail pessoal você entra como pendente. Para entrar aprovado, use uma conta de Workspace e ponha o domínio dela em `GOOGLE_HD`, no `.env`. |
| Microsoft | Universidade A, com uma conta do diretório informado em `MS_TENANT_ID`. |

Mudou o `instituicoes.yaml` ou o `.env`? Rode `docker compose up -d --build` de novo.

Para desligar e apagar os dados locais: `docker compose down -v`.

## Os testes

| Comando | O que roda | O que prova |
|---|---|---|
| `docker compose run --rm testes` | `tests/unit` e `tests/rotas` | O nosso código: a regra de entrada, a conferência dos tokens do Google e da Microsoft, as rotas, o LDAP (contra um OpenLDAP de verdade, com TLS), a ponte da CAFe. Aqui o Firebase é trocado por um substituto. |
| `docker compose run --rm testes-firebase` | `tests/firebase_real` | O Firebase: o custom token é aceito, os claims vêm no token, token adulterado é recusado, sair invalida a renovação. |
| `docker compose run --rm navegador` | `navegador/conferir.py` | A página, num navegador de verdade, com o SDK web falando com o Firebase. |

Os testes contra o Firebase criam contas `ldap:...` e `cafe:...` no projeto e as apagam no fim.

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
| `backend/poc/sessao.py` | Descobre quem faz o pedido, pelo cookie ou pelo token no cabeçalho. |
| `backend/poc/limite.py` | Limite de tentativas de senha, com espera crescente. |
| `backend/poc/repositorio.py` | Banco local (SQLite): pessoas e os logins de cada uma. |
| `backend/poc/config.py` | Lê o `.env` e o `instituicoes.yaml`, e recusa configuração insegura. |
| `backend/poc/app.py` | As rotas. |
| `instituicoes.yaml` | Cadastro das instituições: domínios, logins ligados, diretório Microsoft, LDAP, escopo da CAFe. |
| `pagina/` | A página de demonstração, sem etapa de build. |
| `tests/` | Os testes. |
| `navegador/` | A conferência da página num Chromium sem tela. |
| `ldap/` | A imagem do OpenLDAP de teste, com três pessoas fictícias. |
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
- **`AMBIENTE_DE_TESTE=1`**, que o `docker-compose.yml` liga, cria a universidade simulada e a rota de
  limpeza dos testes (`/demo/...`). Elas só são aceitas com a página em `localhost` e não podem existir
  numa instalação de verdade.
- **A senha do LDAP passa pelo backend.** Ela não é registrada nem guardada, e só trafega por TLS.

## Se algo der errado

| Sintoma | Causa provável |
|---|---|
| O backend não sobe | Falta um campo no `.env` ou a chave em `credenciais/conta.json`. Veja `docker compose logs backend`. |
| Botão do Google ou da Microsoft apagado | Falta `GOOGLE_WEB_CLIENT_ID` ou `MS_CLIENT_ID` no `.env`. A página mostra o aviso no topo. |
| Erro `AADSTS...` na janela da Microsoft | Quase sempre a URI de redirecionamento do aplicativo, ou o tipo de conta do aplicativo. |
| "Token do provedor inválido" | O ID do cliente no `.env` não é o do provedor ligado no Firebase. |
| Entrou, mas como pendente | A conta não prova instituição: confira `GOOGLE_HD` ou `MS_TENANT_ID` no `.env`. |
| "Muitas tentativas. Aguarde." | O limite de senha errada no LDAP. Espere o tempo indicado. |

## O que esta prova não é

- Não é o código de produção. É a prova de que o desenho funciona, com a regra de entrada escrita e
  testada. Como encaixar no sistema está na seção 8 da análise.
- O OpenLDAP e a universidade simulada da CAFe são de teste.
- As instituições do `instituicoes.yaml` são fictícias (domínios `.test`). Os identificadores reais de quem
  testa entram pelo `.env`.
