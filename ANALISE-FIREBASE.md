# Firebase no IoTEdu: análise técnica e respostas da reunião de 25/11/2026

**GT-IoTEdu · novembro de 2026.** A reunião de 25/11 decidiu "autenticação 100% via Firebase" e pediu que a
decisão fosse testada e destrinchada antes de valer, com análise técnica e não só "funciona". Este documento
traz as respostas. A prova de conceito que as sustenta está nesta pasta e roda contra um projeto Firebase
de verdade, sem emulador ([README.md](README.md)).

Os números do Firebase foram conferidos na documentação oficial em 25/11/2026 (páginas atualizadas entre 18
e 20/11/2026). Cada afirmação sobre o comportamento do sistema cita o teste que a prova. O que não foi
possível provar está dito como tal, na seção 5.

## 1. Resposta curta

1. **O Firebase ainda não está em uso.** Na reunião foi dito que o login com Google já passa por ele. O
   código mostra OAuth direto com o Google, tanto no `iotedu-dockerized` quanto no `iotedu-stack`, que é o
   que roda na UFRGS e na Unipampa. Adotar o Firebase é trabalho novo (seção 2).
2. **A decisão se sustenta para os logins pedidos**: Google, Microsoft, LDAP e CAFe terminam todos numa
   conta do Firebase, com a instituição e o papel dentro do token. Está implementado e testado: 160 testes
   do nosso código, 10 de ponta a ponta contra um projeto Firebase de verdade (plano gratuito, sem cartão)
   e 4 conferências da página num navegador (5 com o Keycloak de teste ligado), todos passando. Na tela, o
   login com Microsoft foi feito com uma conta real de um diretório do Entra ID e entrou aprovado; o com
   Google, com uma conta pessoal, ficou pendente, como deve. A aprovação do Google pelo domínio do Workspace
   ainda não rodou com token real: falta uma conta de Workspace de uma instituição (seção 5).
3. **O Firebase não conta autenticações, conta usuários ativos.** Quem entra 1 ou 30 vezes no mês conta uma
   vez. No desenho implementado não há cobrança por usuário e não é preciso cartão. Hoje são 21 usuários nas duas
   instalações (seção 4.1 e 4.2).
4. **LDAP e CAFe não são feitos pelo Firebase.** Ele não fala LDAP e o SAML dele não aceita uma federação.
   Nos dois casos o nosso backend prova quem é a pessoa e pede ao Firebase um token para ela (custom token).
   Funciona e não custa nada, mas esse código continua nosso, e no LDAP a senha da pessoa passa pelo nosso
   backend (seções 4.7 e 4.8). O mesmo molde atende a instituição que tem login único próprio, como um
   Keycloak: está implementado e foi testado com um Keycloak de verdade na frente do OpenLDAP de teste.
   Nesse caminho a senha não passa pelo nosso backend (seção 4.9).
5. **Conta por instituição ou global: depende de onde a chave do Firebase fica.** No núcleo em nuvem, um
   projeto global. No modelo atual, com uma instalação em cada instituição, um projeto por instalação,
   porque a chave que emite tokens não pode ficar no servidor de cada universidade (seção 4.4).
6. **Quatro pontos pedem decisão do grupo** antes de implementar: a configuração de contas por e-mail no
   projeto, o lugar do bind LDAP no modelo em nuvem, os dados de login nos EUA sem SLA, e o prazo de 12 horas
   para pedir login de novo (seção 6).

## 2. Antes de tudo: o que existe hoje

| | Hoje, no código | Com o Firebase |
|---|---|---|
| Google | OAuth 2.0 direto com o Google. Cada instalação cria o seu client no Google Cloud Console. | Um provedor configurado uma vez no projeto. |
| Restrição de domínio no Google | Não existe. Qualquer conta Google entra como usuário. | O backend confere o domínio do Workspace (`hd`). |
| Microsoft | Não existe. | Provedor nativo do Firebase. |
| LDAP | Não existe. | O backend faz o bind e pede um token ao Firebase. |
| CAFe | SP SAML em Django, dentro do backend. Aguarda o cadastro na federação de produção. | O mesmo SP. No fim, o backend pede um token ao Firebase. |
| IdP IoTEdu (o Keycloak da própria instalação, por OIDC) | Existe: é o terceiro login de hoje, com contas e senha no Keycloak da instalação. | Cai no caminho do login único (seção 4.9): o backend confere o token do Keycloak e pede um token ao Firebase. |
| Login único da instituição (o Keycloak, ADFS ou parecido dela) | Não existe. | O mesmo caminho, apontado para o provedor da instituição. |
| Sessão | Cookie assinado, com o e-mail dentro. | O mesmo cookie, ou o token do Firebase no cabeçalho. |

Evidência de que o Firebase não está em uso:

- Não há `firebase` em `app/frontend/package.json` nem `firebase-admin` em `app/backend/requirements.txt`, e
  nenhuma variável `FIREBASE_` nos `.env.example`. O mesmo vale para os submódulos `_backend` e `_frontend`
  do `iotedu-stack`, em todos os commits.
- `app/backend/auth/google_auth.py` troca o código de autorização direto em `oauth2.googleapis.com/token`
  e lê o perfil em `googleapis.com/oauth2/v3/userinfo`.
- A "Google Auth Platform" citada na reunião é a seção de OAuth do Google Cloud Console (tela de
  consentimento e clients). Ela não é o Firebase Authentication. O Firebase emite um token próprio, assinado
  com outras chaves ([verify-id-tokens](https://firebase.google.com/docs/auth/admin/verify-id-tokens)).

Não foi possível conferir o `.env` de produção. O client do Google pode ter sido criado num projeto que
também tem o Firebase ligado, mas o código não o usa.

## 3. Como o login fica

Os caminhos terminam todos no mesmo lugar: uma conta no Firebase com três claims gravados por nós
(`inst`, `papel`, `estado`) e a sessão do app.

```
Google, Microsoft        navegador ──popup──> Firebase ──ID token──> navegador
                         navegador ──ID token do Firebase + ID token do provedor──> backend
                         backend: confere os dois, decide, grava os claims, abre a sessão

LDAP                     navegador ──usuário e senha──> backend ──busca e bind (TLS)──> LDAP da instituição
                         backend: decide, grava os claims, pede o custom token ao Firebase
                         navegador ──custom token──> Firebase ──ID token──> navegador ──> backend (sessão)

CAFe                     popup ──SAML──> SP do IoTEdu (o que já existe) ──JWT de 120 s──> backend
                         backend: decide, grava os claims, guarda um código de uso único
                         navegador ──código──> backend ──custom token──> navegador ──> Firebase ──> backend (sessão)

Login único              popup ──> tela de login da instituição (OIDC) ──código──> backend
da instituição           backend ──código──> provedor da instituição ──ID token assinado──> backend
                         backend: confere o token, decide, grava os claims, guarda um código de uso único
                         navegador ──código──> backend ──custom token──> navegador ──> Firebase ──> backend (sessão)
```

A regra de entrada é a da decisão D33: entra na hora quem prova pelo login que é da instituição, e os
outros ficam pendentes da aprovação do gestor de rede. O que conta como prova muda por provedor:

| Login | O que prova que a conta é da instituição | Por que não o e-mail |
|---|---|---|
| Google | O claim `hd` do ID token do Google: o domínio do Workspace que administra a conta. | Qualquer pessoa cria uma conta Google pessoal com o e-mail da universidade. |
| Microsoft | O claim `tid` do ID token da Microsoft: o diretório do Entra ID. | Qualquer organização cria no próprio diretório uma conta com o e-mail que quiser. A Microsoft orienta a nunca autorizar por e-mail. |
| LDAP | O bind deu certo no diretório cadastrado para aquela instituição. | O diretório de uma instituição pode ter um e-mail de outra. |
| CAFe | O escopo do `eduPersonPrincipalName`, o que vem depois do `@`. | O atributo `mail` é livre. |
| Login único da instituição | O ID token veio assinado pelo provedor cadastrado para aquela instituição. | O provedor pode deixar a pessoa digitar o próprio e-mail. |

O ID token do Firebase não carrega `hd` nem `tid`. Por isso o navegador manda também o ID token do
provedor, que ele recebe no popup, e o backend só o aceita com assinatura, audiência, emissor e validade
conferidos, e se ele for da mesma conta que o Firebase autenticou.

A chave de uma pessoa no banco é o par (provedor, identificador no provedor), e não o e-mail. O e-mail só
liga um login novo a uma pessoa que já existe quando o login provou esse e-mail e a instituição é a mesma.

## 4. As perguntas da reunião

### 4.1 Quantas autenticações vamos ter por mês?

O Firebase não mede autenticações. Sem o upgrade não há contagem nenhuma. Com o upgrade, a unidade é o
**usuário ativo** (por dia sem cartão, por mês com cartão): uma conta que entrou pelo menos uma vez no
período. Quem entra de novo no mesmo período não conta outra vez
([preços do Identity Platform](https://cloud.google.com/identity-platform/pricing)). O "15 mil
autenticações grátis" citado em reuniões anteriores não existe nas páginas de preço.

Em 12/10/2026 havia 8 contas no banco da UFRGS e 13 no da Unipampa (contagem da troca daquele dia, no
`HISTORICO-MODULARIZACAO.md` do `iotedu-stack`). São contas cadastradas, não usuários ativos no mês, e a
contagem não foi refeita. Para frente, a análise usa 300 usuários por mês por instituição, o mesmo valor da
projeção de custos de outubro. É uma hipótese: o grupo ainda não tem uma projeção de usuários.

O número de logins só importa para os limites por minuto, que estão muito longe:

<!-- tabela:pico -->
| Cenário | Usuários ativos no mês | Logins no mês (teto) | Logins por minuto na hora mais cheia | Parte do limite de 45.000 por minuto | Renovações por minuto com todos logados, sobre 18.000 |
|:---|---:|---:|---:|---:|---:|
| UFRGS, hoje | 8 | 176 | 0,0 | 0,000% | 0,001% |
| Unipampa, hoje | 13 | 286 | 0,0 | 0,000% | 0,001% |
| 6 instituições | 1.800 | 39.600 | 6,0 | 0,013% | 0,167% |
| 10 instituições | 3.000 | 66.000 | 10,0 | 0,022% | 0,278% |
| 50 instituições | 15.000 | 330.000 | 50,0 | 0,111% | 1,389% |
| 100 instituições | 30.000 | 660.000 | 100,0 | 0,222% | 2,778% |
| 1.000 instituições | 300.000 | 6.600.000 | 1.000,0 | 2,222% | 27,778% |
<!-- /tabela -->

O teto de logins no mês supõe um login por dia de uso, que é o que o corte de 12 horas da seção 6 produz.
A hora mais cheia supõe 20% dos usuários do mês entrando na mesma hora. As duas são hipóteses desta
análise, e mudar o valor em `projecao.py` refaz a tabela. Mesmo com mil instituições, o pico fica em 2% do
limite de logins.

A verificação do token no backend é local, com as chaves públicas do Google em cache. Ela não aparece em
nenhuma tabela de limites, e o backend só procura o Google de tempos em tempos, para atualizar essas chaves.
Isso vale enquanto a checagem de revogação estiver desligada
([verify-id-tokens](https://firebase.google.com/docs/auth/admin/verify-id-tokens)).

### 4.2 Quanto o gratuito suporta, e quando passa a custar?

Existem dois produtos com o mesmo nome. Ligar o segundo é um botão no console, e não achei procedimento
oficial para voltar atrás.

| | Firebase Authentication, sem o upgrade | Com o upgrade para Identity Platform |
|---|---|---|
| Google, Microsoft, custom token | Sem cobrança por usuário e sem teto de usuários ativos. | Sem cartão: 3.000 usuários ativos por dia. Com cartão: 50.000 por mês sem custo, depois de US$ 0,0055 a 0,0025 por usuário. |
| SAML e OIDC genérico | Não tem. | Sem cartão: 2 usuários por dia. Com cartão: 50 por mês sem custo, depois US$ 0,015 por usuário. |
| Tenants (silo por instituição) | Não tem. | Sem cartão: 2 tenants. Com cartão: sem limite. |
| SLA | Não tem. | 99,95%, mas só para login com e-mail e senha e para a renovação do token ([SLA](https://cloud.google.com/identity-platform/sla)). Login com Google, Microsoft e custom token não está coberto. A compensação é crédito sobre a fatura. |
| Segundo fator, registros de auditoria, funções de bloqueio | Não tem. | Tem. |

Fontes: [visão geral do Firebase Auth](https://firebase.google.com/docs/auth),
[comparação dos produtos](https://docs.cloud.google.com/identity-platform/docs/product-comparison),
[cotas do Identity Platform](https://docs.cloud.google.com/identity-platform/quotas),
[SLA](https://cloud.google.com/identity-platform/sla).

As páginas oficiais divergem num ponto: a de preços do Firebase lista 50 mil usuários por mês para o
projeto com upgrade e sem cartão, e as de limites e de cotas listam 3.000 por dia. A tabela usa o menor.
A franquia de 50 usuários de SAML e OIDC é por projeto.

**O desenho implementado fica na coluna da esquerda.** Como LDAP, CAFe e o login único da instituição
entram por custom token, nenhum login precisa de SAML, OIDC ou tenants do Firebase. Não há upgrade, não há cartão e não há cobrança
por usuário.

<!-- tabela:uso -->
| Cenário | Usuários ativos no mês | Sem o upgrade, como na PoC (US$/mês) | Com o upgrade, sem cartão (teto de 3.000 por dia) | Com o upgrade, com cartão (US$/mês) | A mais, se a CAFe fosse SAML nativo (US$/mês) |
|:---|---:|---:|---:|---:|---:|
| UFRGS, hoje | 8 | 0,00 | cabe | 0,00 | 0,00 |
| Unipampa, hoje | 13 | 0,00 | cabe | 0,00 | 0,00 |
| 6 instituições | 1.800 | 0,00 | cabe | 0,00 | 12,75 |
| 10 instituições | 3.000 | 0,00 | cabe | 0,00 | 21,75 |
| 50 instituições | 15.000 | 0,00 | não cabe | 0,00 | 111,75 |
| 100 instituições | 30.000 | 0,00 | não cabe | 0,00 | 224,25 |
| 1.000 instituições | 300.000 | 0,00 | não cabe | 1.195,00 | 2.249,25 |
<!-- /tabela -->

A última coluna mostra quanto custaria a mais se a CAFe passasse pelo SAML do próprio Firebase, com metade
dos usuários federados. É a conta que o projeto vinha usando (US$ 2,25 por instituição). O desenho com
custom token zera essa linha.

Se um dia o upgrade for feito, por causa do SLA ou do segundo fator, a cota de 50 mil cobre:

<!-- tabela:limiares -->
| Limite | Com 300 usuários por instituição | Com 3.000 por instituição |
|:---|---:|---:|
| Cota mensal sem custo (50 mil usuários ativos, com cartão) | até 166 instituições | até 16 instituições |
| Teto diário sem cartão (3.000 usuários ativos por dia) | até 33 instituições | até 3 instituições |
<!-- /tabela -->

Limites que valem nos dois produtos ([limites do Firebase Auth](https://firebase.google.com/docs/auth/limits)):

| Limite | Valor | Onde pode pegar |
|---|---|---|
| Logins com custom token | 45.000 por minuto, por projeto | Não pega (tabela da seção 4.1). |
| Renovações de token | 18.000 por minuto, por projeto | Com mil instituições chegaria a 28% se todos estivessem logados ao mesmo tempo. |
| Contas novas | 100 por hora, **por endereço IP** | Pode pegar na primeira semana de uma instituição: o campus inteiro sai por um IP só. A página não diz a quais logins o limite se aplica. Fica para o teste com projeto real. |
| Claims gravados por nós | 1.000 bytes por conta | Usamos três campos curtos. |
| Validade do ID token | 1 hora | O navegador renova sozinho. |
| Logins com Google e Microsoft | Sem linha própria. O teto geral da API é de 180.000 pedidos por minuto, por projeto | Não pega. |
| Domínios autorizados | A lista não aceita `*`, mas um domínio vale para os subdomínios dele | Com os painéis em subdomínios de um domínio nosso, basta um cadastro (seção 4.3). |
| Projetos por conta Google | Cerca de 5 a 10 sem cartão | Pesa na opção de um projeto por instituição (seção 4.4). |

### 4.3 Com múltiplos domínios, o que acontece?

"Domínio" aparece em quatro lugares, e cada um se resolve de um jeito.

**Domínios de e-mail da instituição.** Uma universidade pode ter mais de um. No Firebase nada muda: o
provedor Google é um só para todas as contas Google. A lista de domínios é nossa, por instituição
(`dominios` e `google_hd` em `instituicoes.yaml`), e quem a confere é o backend.
Teste: `test_google_com_conta_da_instituicao_entra_e_usa_o_painel`.

**Endereços do painel.** O Firebase só aceita login a partir dos domínios da lista de domínios autorizados
do projeto. A lista não aceita `*`, mas um domínio cadastrado vale para os subdomínios dele: é o que o
código do SDK web faz, e foi conferido num navegador em 25/11. Com `localhost` na lista, o login a partir de
`unia.localhost` e de `painel.unia.localhost` chegou à tela do Google; a partir de `127.0.0.1`, que não
está na lista, o Firebase respondeu `auth/unauthorized-domain`. Com um subdomínio por instituição (D24)
sob um domínio nosso, basta um cadastro. Só um painel em domínio próprio da instituição pede cadastro a
mais. Falta repetir com um domínio de verdade. Além disso, o endereço de retorno cadastrado no Google e na
Microsoft passa a ser um só, o do Firebase, e não mais um por instalação como hoje.

**Diretórios da Microsoft.** O Firebase tem uma só configuração Microsoft por projeto. O aplicativo
registrado no Entra ID tem de ser multilocatário, e cada universidade provavelmente precisa que o
administrador dela autorize o aplicativo uma vez. Isso só se confirma com um diretório real.

**O mesmo e-mail em dois provedores.** Um projeto Firebase novo vem com "uma conta por e-mail"
([login com Google](https://firebase.google.com/docs/auth/web/google-signin), erro
`account-exists-with-different-credential`). Com essa opção:

- quem entrou com Google não consegue entrar depois com Microsoft no mesmo e-mail (o Firebase responde que
  a conta já existe com outra credencial);
- quem chegar primeiro com um e-mail alheio, a partir de um diretório Microsoft qualquer, trava o login do
  dono do e-mail. A exceção é o dono entrar por um provedor que o Firebase considera confiável para aquele
  endereço (o Google, para contas hospedadas no Google): nesse caso o provedor confiável substitui o outro
  ([gerência de usuários](https://docs.cloud.google.com/identity-platform/docs/concepts-manage-users)).

A saída é ligar no console a opção "criar várias contas para cada provedor de identidade". Ela combina com
o nosso desenho, em que a chave é o par (provedor, identificador). O lado do backend está testado em
`test_email_so_afirmado_nao_assume_a_conta_de_quem_ja_existe` e
`test_google_e_cafe_da_mesma_pessoa_viram_um_usuario_so`. Com a opção ligada o Firebase deixa de pôr o
e-mail no token; o backend usa o e-mail do token do provedor, que é o que ele já conferia. O comportamento
do Firebase nos dois modos está na lista de conferência manual da seção 5.

### 4.4 Uma conta Firebase por instituição ou uma global?

As três opções funcionam. A diferença está em quem garante o isolamento e em onde fica a chave.

| | A. Um projeto global, instituição no claim | B. Um projeto, um tenant por instituição | C. Um projeto por instituição |
|---|---|---|---|
| Quem isola as instituições | Nós: o claim `inst` e a conferência no banco. | O Google: usuários e provedores separados por tenant. | O Google: projetos separados. |
| Upgrade e cartão | Não precisa. | Precisa do upgrade e, a partir do terceiro tenant, do cartão. | Não precisa. |
| Custo por usuário | Zero. | Zero até 50 mil por mês, depois cobra. | Zero. |
| Configurar Google e Microsoft | Uma vez. | Uma vez por tenant. | Uma vez por projeto. |
| Instituição nova | Uma linha de cadastro. | Criar o tenant e os provedores dele. | Criar o projeto, os provedores, a chave e o domínio. Esbarra na cota de 5 a 10 projetos. |
| Pessoa em duas instituições | Uma conta, uma instituição ativa por vez. | Duas contas. | Duas contas. |
| Dependência do Google | Média: lemos um claim comum do JWT. | Alta: o tenant vem de um campo do Google. | Média, multiplicada pelo número de projetos. |
| Se a chave do projeto vaza | Emite token para qualquer pessoa de qualquer instituição. | Idem. | Só para aquela instituição. |
| Implementado aqui | Sim. | Não. | Não. O backend só aceita token do projeto dele, que é o que separa um projeto do outro. |

A última linha de risco decide. Para emitir custom token e gravar claims, o backend precisa da chave de
serviço do projeto, e quem tem essa chave entra como qualquer pessoa.

- **No núcleo em nuvem: opção A.** Um projeto global, com a chave só no núcleo. É a inclinação que o
  ADR-0006 já tinha, agora implementada e testada. Fica o gatilho de rever para a opção B se uma instituição exigir, por
  contrato, isolamento de contas no provedor.
- **No modelo atual, com uma instalação em cada instituição: opção C.** Um projeto por instalação, do mesmo
  jeito que hoje cada instalação cria o seu client do Google. Um projeto global obrigaria a pôr a mesma
  chave no servidor de cada universidade. O projeto de teste desta prova de conceito é desse tipo: um
  projeto, uma instalação.

Há um meio-termo para o modelo atual, se o grupo quiser um projeto só desde já: as instalações usam o
projeto global apenas para Google e Microsoft, sem chave nenhuma, porque verificar o token só exige as
chaves públicas. O papel e a instituição continuam no banco local, como hoje, e LDAP e CAFe esperam o
núcleo.

### 4.5 O modelo em nuvem muda alguma coisa?

Muda cinco coisas.

1. **Onde fica a chave e quantos projetos são** (seção 4.4): de um projeto por instalação para um projeto
   global com a chave só no núcleo.
2. **O LDAP deixa de estar ao alcance.** Hoje o backend está na rede da universidade e alcança o LDAP dela.
   O núcleo em nuvem não alcança. Há dois caminhos, e nenhum foi testado: a instituição libera LDAPS para o
   endereço do núcleo, ou o bind roda no sistema que fica na instituição, que devolve ao núcleo uma
   afirmação assinada, como a ponte da CAFe faz. No segundo, falta decidir por onde a senha trafega.
   Para a instituição que tem login único próprio há um terceiro caminho (seção 4.9): o núcleo só precisa
   alcançar o endereço público do provedor dela, por HTTPS, e o diretório não é exposto. Ele foi testado
   na própria máquina, com o provedor na mesma rede do backend; falta um provedor público.
3. **Os endereços do painel entram na lista do Firebase** um a um, por API (seção 4.3).
4. **A instituição passa a vir do token.** No desenho implementado o claim `inst` leva a instituição ativa, o
   backend nunca a tira do pedido, e antes de uma ação que altera algo confere no banco se a pessoa ainda é
   da instituição (D12). Teste: `test_token_sem_claims_e_tratado_como_pendente`.
5. **O que hoje fica na memória de um processo precisa ir para um lugar compartilhado.** Na prova de
   conceito são três itens: o contador de tentativas de senha, o código de troca do login da CAFe e do
   login único, e os logins únicos em andamento. Com mais de uma cópia da API eles vão para o cache
   compartilhado ou para o banco (D20).

O que não muda: a verificação do token é local, então o núcleo não precisa rodar no Google, e o volume de
logins não se aproxima de nenhum limite.

### 4.6 Qual o esforço para Microsoft, Apple e os outros? Quem testa?

O esforço tem duas partes: o que se configura em consoles e o que é código nosso.

| Login | No Firebase | Fora do Firebase | Código na prova de conceito | Prova de instituição |
|---|---|---|---|---|
| Google | Ligar o provedor. | Nada: o Firebase cria o client. | `provedores.py`, dividido com a Microsoft (106 linhas). | `hd` |
| Microsoft | Ligar o provedor e colar o ID e o segredo. | Registrar o aplicativo no Entra ID. O segredo tem validade e precisa ser renovado. | O mesmo arquivo. | `tid` |
| LDAP | Nada. | A instituição cria uma conta de serviço só de leitura e informa endereço, base e a CA. | `ldap_auth.py` (97 linhas) e `limite.py` (61). | bind |
| CAFe | Nada. | O cadastro do SP na federação, que já estava pendente. | `ponte_cafe.py` (79 linhas), mais o SP Django que já existe. | escopo |
| Login único da instituição (OIDC) | Nada. | A instituição registra o IoTEdu como cliente no provedor dela e informa o emissor, o identificador e o segredo. | `oidc_auth.py` (192 linhas). | emissor |
| Apple | Provedor nativo. | Exige participar do programa de desenvolvedores da Apple, que é pago (o valor não foi conferido). | Uma entrada na tabela de provedores e o verificador do token. | Não há: a conta é pessoal. |
| Facebook, GitHub, X e outras redes | Provedores nativos. O Instagram, citado na reunião, não está entre eles, pelo que lembro da lista; não conferi nesta rodada. | Registrar um aplicativo em cada uma. | Uma entrada na tabela. | Não há: a conta é pessoal. |

Três observações sobre a tabela.

- **Rede social não prova instituição.** Quem entra com Apple, Facebook ou uma conta Google pessoal fica
  sempre pendente, à espera do gestor de rede. Ligar esses provedores é barato, mas eles só servem para o
  caso de aprovação manual. Para as primeiras instituições, os três que importam são os que a reunião
  listou: Google, Microsoft e LDAP, mais a CAFe.
- **O Firebase não reduz o código de login.** A prova de conceito tem cerca de 2.200 linhas de Python (eram 1.400 antes do
  login único e das ferramentas de teste), contra cerca de 1.500 do login atual. A diferença é o que essas linhas fazem: cobrem dois logins que não existiam
  (Microsoft e LDAP), a regra de entrada por instituição, que hoje não existe para o Google, e os cuidados
  de segurança da seção 6. O que o Firebase tira de nós é o protocolo OAuth com cada provedor, a emissão e
  a renovação de tokens e a guarda das contas.
- **Um provedor novo do tipo OAuth custa pouco depois do primeiro.** A Microsoft entrou no mesmo arquivo do
  Google, com uma regra a mais.

**Achado ao tentar ligar a Microsoft (25/11/2026).** Registrar o aplicativo exige um diretório do Entra ID.
Uma conta Microsoft pessoal não registra mais aplicativo fora de um diretório, e o programa de
desenvolvedores do Microsoft 365 não liberou o ambiente de teste para a conta usada. Restam dois caminhos:
uma assinatura do Azure, que traz um diretório (a gratuita pede verificação de identidade), ou o diretório
de uma organização. Para o produto, o registro tem de ficar num diretório de quem opera a plataforma, e
não numa conta pessoal. Isso liga a Microsoft à pendência que já existia, "quem opera a plataforma". O
teste desta rodada usa o diretório de uma assinatura pessoal do Azure, com o aplicativo restrito a esse
diretório; para várias universidades ele precisa ser multilocatário.

Quem testa, e com o quê:

| O que falta testar | Do que precisa |
|---|---|
| Google de verdade | Um projeto Firebase de teste e uma conta de Workspace de uma instituição. |
| Microsoft de verdade | O mesmo projeto, um aplicativo registrado no Entra ID e uma conta de universidade que use Microsoft. |
| LDAP de verdade | O endereço, a base e uma conta de serviço do OpenLDAP de uma instituição (a UFSM foi citada). |
| CAFe de verdade | O cadastro do SP, pelo menos na federação de homologação. |
| Login único de verdade | Uma instituição que tenha Keycloak, ADFS ou parecido, e o registro do IoTEdu como cliente nele. |

A pergunta que a reunião mandou para o grupo dos líderes de implantação, "como são gerenciadas as contas
institucionais?", define quais dessas linhas são urgentes. O roteiro para criar o projeto de teste está no
[README.md](README.md).

### 4.7 LDAP

O Firebase e o Identity Platform não têm provedor LDAP. O caminho que a documentação dá para um sistema de
login próprio é o custom token
([custom-auth](https://firebase.google.com/docs/auth/web/custom-auth)): o backend autentica a pessoa do
jeito dele e pede ao Firebase um token para ela.

O que a prova de conceito faz, contra um OpenLDAP de verdade (versão 2.5, em container, com TLS):

1. Procura a pessoa com uma conta de serviço só de leitura. Tem de achar exatamente uma entrada.
2. Faz o bind com o DN achado e a senha digitada, sempre por TLS, conferindo o certificado com a CA que a
   instituição informou.
3. Grava a pessoa e os claims e emite o custom token. O navegador o troca por uma sessão do Firebase.

O que isso traz de novo para o projeto:

- **A senha institucional da pessoa passa pelo nosso backend.** Hoje nenhum login do IoTEdu toca em senha.
  O código não a registra nem a guarda, e um teste achou e fechou um vazamento: a mensagem de erro padrão do
  FastAPI devolvia o conteúdo recebido, inclusive a senha (`test_a_senha_nunca_aparece_na_resposta_de_erro`).
- **Tentativa de senha é problema nosso.** Há um limite com atraso crescente, por pessoa e por endereço.
  Não é bloqueio rígido, mas também não impede que alguém atrapalhe outra pessoa: quem erra a senha de um
  colega a cada poucos minutos mantém o login dele em espera, e o contador por endereço não zera quando
  alguém acerta, o que pesa num campus que sai por um IP só. O ajuste fica para o encaixe
  (`test_ldap_atrasa_depois_de_erros_seguidos_ate_para_a_senha_certa`).
- **O e-mail que o diretório informa só vale se for de um domínio da própria instituição**
  (`test_ldap_email_de_outra_instituicao_nao_e_aceito_como_prova`).

Active Directory também fala LDAP. O cadastro aceita `tipo: ad`, que troca o filtro (busca por
`sAMAccountName` e ignora conta desativada) e os atributos lidos. O código do bind é o mesmo. Isso não foi
testado contra um Active Directory: o que os testes provam é só que o cadastro monta o filtro certo
(`test_active_directory_muda_so_o_filtro_e_os_atributos`). Duas diferenças conhecidas ficam para o teste
real: o `sAMAccountName` pode ser renomeado, e o identificador que não muda é o `objectGUID`; e uma
instituição com o diretório sincronizado com o Entra ID pode usar o login da Microsoft em vez do LDAP.

Para o primeiro contato com o diretório de uma instituição há um comando que confere o cadastro passo a
passo e diz onde parou: conexão e certificado, conta de serviço, base, filtro, atributos e o login de uma
pessoa (`python -m poc.conferir_ldap`, no README). Ele usa o mesmo código da rota
(`test_conferencia_do_ldap_passa_com_o_diretorio_de_teste_e_diz_onde_parou`).

A biblioteca usada, `ldap3`, teve a última versão estável em 2021. Funciona com Python 3.11, mas os avisos
da execução mostram que ela usa funções que versões mais novas do Python removem. É um risco de manutenção. As alternativas (`python-ldap`, `bonsai`) exigem compilar bibliotecas do sistema.

A alternativa é pôr um Keycloak na frente do LDAP: a senha deixa de passar pelo nosso código, ao preço de
mais uma peça para operar. Ela foi implementada e testada, e está na seção 4.9.

### 4.8 CAFe

O SAML do Firebase só existe com o upgrade e aceita um provedor de identidade por configuração: um
identificador, um endereço e um certificado. Não importa os metadados de uma federação, não tem serviço de
descoberta e só aceita login iniciado pelo nosso lado
([SAML no Identity Platform](https://docs.cloud.google.com/identity-platform/docs/web/saml)). Para a CAFe
seria preciso cadastrar cada universidade à mão e fazer a nossa própria tela de escolha. Não achei relato
de uso do Firebase com federação acadêmica.

O caminho testado é o que o consultor recomendou em 16/11: manter o SP SAML que o app já tem e, quando ele
termina, emitir um custom token. A prova de conceito recebe o JWT de 120 segundos exatamente no formato que
`app/backend/auth/base/views.py` emite hoje, então o SP não muda.

O que a prova de conceito acrescenta ao que existe:

- o token de ponte só vale uma vez (`test_cafe_token_de_ponte_so_vale_uma_vez`);
- um link de fora, para um navegador que não começou o login, é recusado
  (`test_cafe_link_de_fora_sem_ter_comecado_o_login_e_recusado`);
- o token do Firebase não trafega entre janelas: a janela do login só avisa que terminou, para a origem
  exata do painel, e a janela principal busca o token (`test_cafe_do_sp_ate_o_painel`). Hoje o app envia os
  dados com destino `"*"`;
- o segredo da ponte é próprio. Hoje é o mesmo que assina a sessão;
- o CPF que o SP coloca no token é descartado.

O que continua pendente não é do Firebase: o cadastro do SP na federação, e a pergunta feita à RNP sobre um
SP único para todas as instituições. A prova de conceito amarra a pessoa à instituição pelo escopo do
`eduPersonPrincipalName`. Seria mais firme o SP passar também o identificador da universidade que
autenticou, e isso é um campo a mais no JWT.

### 4.9 Outros logins: o login único da própria instituição

A reunião listou Google, Microsoft, LDAP e CAFe. Falta um caso comum: a instituição que já tem um login
único próprio (Keycloak, ADFS, Shibboleth com OIDC, Authentik). Todos falam OpenID Connect.

O Firebase tem provedor OIDC genérico, mas só com o upgrade para Identity Platform, na faixa cobrada por
usuário (seção 4.2), e com um provedor cadastrado por configuração. O caminho implementado é o mesmo do
LDAP e da CAFe: quem fala com o provedor da instituição é o nosso backend, e o Firebase recebe um custom
token. Não há upgrade nem custo por usuário.

O que a prova de conceito faz (`backend/poc/oidc_auth.py`):

1. Leva a pessoa, numa janela, à tela de login da instituição. O pedido leva um estado, um `nonce` e o
   desafio PKCE. O `nonce` e o verificador PKCE ficam no backend; o navegador só leva o estado, assinado.
2. Recebe o código de volta, confere o estado e troca o código pelo ID token, direto com o provedor.
3. Confere o ID token: assinatura com as chaves que o provedor publica, emissor igual ao cadastrado,
   audiência igual ao nosso cliente, validade e o `nonce` daquele login. Token sem assinatura ou assinado
   com segredo compartilhado não é aceito.
4. Grava a pessoa e os claims e entrega o custom token pelo mesmo mecanismo da CAFe: a janela só avisa
   que terminou, e a janela principal busca o token.

Foi testado de duas formas:

- **Contra um provedor simulado**, que roda dentro do ambiente de teste e fala o protocolo de verdade.
  É o que os testes automáticos usam, inclusive os de ponta a ponta com o Firebase e o do navegador.
- **Contra um Keycloak de verdade** (versão 26.4.7, em container), configurado para ler as pessoas do
  OpenLDAP de teste. A conferência no navegador entra primeiro pelo LDAP direto e depois pelo Keycloak, com
  a senha digitada na tela dele. Passou: a conta no Firebase é outra (`oidc:unib:...`), a instituição vem
  no token, e os dois logins viram a mesma pessoa no nosso banco, porque o Keycloak afirma o e-mail como
  verificado. O teste foi na própria máquina, por HTTP, com o Keycloak na mesma rede do backend. Falta um
  provedor público, por HTTPS.

O que isso muda em relação ao LDAP direto:

| | LDAP direto | Keycloak (ou outro login único) na frente |
|---|---|---|
| A senha da pessoa | Passa pelo nosso backend. | Não passa. É digitada na tela da instituição. |
| Limite de tentativas de senha | É nosso (`limite.py`). | É do provedor. |
| Segundo fator | Não há. | O que o provedor tiver. |
| O que a instituição abre para o IoTEdu | A porta LDAPS do diretório e uma conta de serviço. | Um cliente registrado no provedor. O diretório não é exposto. |
| No núcleo em nuvem | O núcleo não alcança o diretório (seção 4.5). | Funciona: o provedor é um endereço HTTPS público. |
| Peças para operar | Nenhuma a mais. | O provedor, que é da instituição. |

Limites do que foi feito:

- **Quem tem conta no provedor entra aprovado naquela instituição.** Se o provedor da instituição aceita
  cadastro livre, isso deixa de ser prova. É pergunta para fazer a cada instituição antes de ligar.
- **O e-mail só liga o login a uma pessoa que já existe quando o provedor diz que o verificou** e ele é de
  um domínio da instituição (`test_login_unico_email_nao_verificado_nao_assume_a_conta_de_quem_ja_existe`).
  No Keycloak com LDAP isso depende da opção "Trust Email" do diretório.
- **Sair do IoTEdu não encerra a sessão no provedor.** Quem clicar de novo no botão entra sem digitar a
  senha, enquanto a sessão do provedor durar. O corte de 12 horas continua valendo do nosso lado.
- **Um provedor só com SAML, fora da CAFe, não usa este caminho.** Ele entra pelo mesmo SP SAML da CAFe,
  com o provedor cadastrado nele. Não foi testado.

## 5. O que foi testado

Não há emulador. Os testes se dividem pelo que cada um precisa para rodar.

| Grupo | Precisa de | Situação em 25/11/2026 |
|---|---|---|
| A. Regras, verificadores e rotas | Só do Docker. O Firebase é trocado por um substituto; o OpenLDAP é de verdade. | **160 testes, todos passando.** |
| B. Ponta a ponta com o Firebase | Do projeto Firebase de teste, com a chave de serviço. | **10 testes e 4 conferências num navegador (5 com o Keycloak de teste), todos passando.** |
| C. Google e Microsoft na tela | Do projeto e de uma pessoa com conta em cada um. | **Microsoft com conta de diretório: aprovado. Google com conta pessoal: pendente, como esperado.** Os outros passos do roteiro ainda não foram feitos. |

### A. O que já roda: o nosso código

```
$ docker compose run --rm testes
160 passed, 35 warnings in 127.57s (0:02:07)
```

Nestes testes, as quatro chamadas ao Firebase (verificar o token, criar a conta, gravar os claims, emitir o
custom token) vão para um substituto que registra o que o backend pediu. Os tokens do Google e da Microsoft
são assinados com uma chave local e passam pelo verificador de produção. O LDAP é o OpenLDAP de teste, com
TLS. Eles provam a nossa lógica; não provam nada sobre o Firebase.

| Assunto | Testes | O que fica provado |
|---|---:|---|
| Regra de entrada | 16 | Para cada provedor, quem entra na hora, quem fica pendente e quem é recusado. |
| Tokens do Google e da Microsoft | 10 | O verificador recusa audiência errada, assinatura de outra chave, token vencido, emissor que não bate com o diretório e token sem assinatura. |
| Ponte da CAFe, limite, partida | 41 | O token de ponte vence, não se repete e não aceita outro segredo. O serviço não sobe sem projeto, sem chave, com o emulador configurado ou com segredo curto ou padrão. As rotas de teste só existem em localhost. |
| Projeção | 3 | As contas de custo batem com a tabela de preços. |
| Rotas de Google e Microsoft | 11 | Sessão por cookie, claims gravados, acesso só com o token, conta pessoal pendente, diretório estranho pendente, token do provedor forjado ou de outra conta recusado. |
| Cliente do login único | 23 | O ID token do provedor é recusado com emissor, audiência ou `nonce` errados, vencido, assinado por outra chave, sem assinatura ou com segredo compartilhado. A descoberta incoerente ou insegura é recusada. |
| Rotas de LDAP | 14 | Senha certa entra. Senha errada e usuário inexistente dão a mesma resposta. Injeção no filtro não passa. Com outra CA a conexão não é feita. O servidor de teste recusa senha fora de TLS, e o nosso lado não sobe com endereço `ldap://`. A conferência do cadastro diz em qual passo parou. |
| Rotas da CAFe | 7 | Do token de ponte ao painel, e as recusas da seção 4.8. |
| Rotas do login único | 20 | Do provedor simulado ao painel. Link de fora, estado trocado, volta repetida, código inventado e token com claim errado são recusados. E-mail não verificado não assume o cadastro de outra pessoa. |
| A mesma pessoa em dois logins | 2 | E-mail provado junta os logins numa pessoa só. E-mail só afirmado não junta. |
| Tokens que não podem valer, sessão | 13 | Login antigo, conta desconhecida e login por senha são recusados. Pedido de outra origem é recusado. Sair encerra a sessão e pede ao Firebase para invalidar a renovação. A senha não volta em mensagem de erro. |

Os avisos da saída são da biblioteca `ldap3`, que usa funções antigas do Python (seção 4.7).

### B. O Firebase de verdade

O projeto de teste está no plano gratuito (Spark), sem cartão e sem o upgrade para Identity Platform, com o
Google ligado e a opção "várias contas por e-mail" ativada. Os tokens são emitidos e assinados pelo
Firebase, e as trocas passam pela API pública dele, a mesma que o SDK web usa.

```
$ docker compose run --rm testes-firebase
..........                                                               [100%]
10 passed in 28.01s

$ docker compose run --rm navegador
Chromium 159.0.8154.6
PASSOU  LDAP: entra, mostra cookie e Bearer, sai
PASSOU  LDAP: senha errada mostra o erro e não entra
PASSOU  CAFe: popup, aviso entre janelas e troca do código
PASSOU  Login único (OIDC): popup no provedor, volta e troca do código
PASSOU  Keycloak na frente do LDAP: senha na tela dele, mesma pessoa do LDAP
5 de 5 passaram
```

| Teste | O que fica provado |
|---|---|
| `test_ldap_de_ponta_a_ponta_com_token_assinado_pelo_firebase` | O custom token do backend é aceito, e o primeiro ID token já traz a instituição, o papel e o estado. |
| `test_cafe_de_ponta_a_ponta_com_o_sp_simulado` | O mesmo, pelo caminho da CAFe. O teste emite o token de ponte no lugar do SP. |
| `test_login_unico_de_ponta_a_ponta_com_o_provedor_simulado` | O mesmo, pelo login único da instituição. |
| `test_o_token_do_firebase_vale_sozinho_no_cabecalho` | O backend aceita o ID token real sem cookie. |
| `test_token_com_assinatura_adulterada_e_recusado` | Token mexido não passa. |
| `test_token_com_o_conteudo_trocado_e_recusado` | Ninguém muda a própria instituição ou papel editando o token. |
| `test_token_sem_assinatura_e_recusado` | O backend não aceita token sem assinatura. |
| `test_o_firebase_recusa_custom_token_que_o_backend_nao_assinou` | Só a nossa chave emite custom token. |
| `test_renovar_o_token_mantem_os_claims` | A renovação de hora em hora mantém a instituição. |
| `test_depois_de_sair_o_firebase_nao_renova_mais_o_token` | Sair invalida a renovação. |
| Navegador: LDAP, senha errada, CAFe, login único e, com o Keycloak de teste ligado, o login por ele | A página `pagina/`, com o SDK web (13.4.0), num Chromium sem tela. |

As contas que esses testes criam no projeto (`ldap:...`, `cafe:...` e `oidc:...`) são apagadas no fim; o projeto ficou
com zero contas depois da rodada.

Isso responde, com execução, três pontos que antes eram só leitura de documentação: LDAP e CAFe funcionam
por custom token no plano gratuito, sem o upgrade; os claims gravados antes do custom token já vêm no
primeiro token; e sair invalida a renovação no Firebase.

### C. Conferência manual: Google e Microsoft

As telas de login do Google e da Microsoft não aceitam navegador automatizado. Com o backend no ar, em
`http://localhost:8088`, dois passos foram feitos em 25/11/2026 e conferidos no banco do backend e nas
contas do projeto:

- **Microsoft, conta de um diretório do Entra ID.** Entrou como ativa na instituição que tem aquele
  diretório cadastrado. O token da Microsoft chegou ao navegador pelo Firebase, passou no verificador de
  produção (assinatura, audiência, emissor do próprio diretório) e trouxe o `tid` e o `oid`; o `oid` é o
  identificador que o Firebase guarda para a conta. O Firebase não pôs e-mail na conta e a deixou como "não
  verificada", o que confirma a escolha de provar pelo diretório e não pelo e-mail. Isso fecha a pendência
  da D33 para o caso de um diretório só. A conta é do dono do diretório de teste; o pedido de autorização
  do administrador em diretório de terceiros continua sem resposta.
- **Google, conta pessoal.** Entrou como pendente, e o painel recusou o acesso.

O teste com o Google mostrou um detalhe que está na ajuda do Firebase
([várias contas por e-mail](https://support.google.com/firebase/answer/9134820)) e tinha passado: com "várias contas por
e-mail" ligado, o Firebase não pede o e-mail ao Google por conta própria, e o token do Google chega sem
`email` e sem `email_verified`. A página passou a pedir o escopo `email`. Essa correção ainda não foi
conferida com uma conta de Workspace.

O roteiro completo:

| Passo | Resultado esperado | O que responde |
|---|---|---|
| Entrar com uma conta Gmail pessoal | Entra como pendente; o painel responde 403. | Conta pessoal não prova instituição. |
| Entrar com uma conta de Workspace cujo domínio está em `google_hd` | Entra como ativo na instituição. | Se o `hd` chega no token do Google. |
| Entrar com uma conta Microsoft de universidade | Ativo se o diretório está em `microsoft_tid`; pendente se não está. | A pendência da D33: se o `tid` chega, o que o Firebase informa no e-mail, e se aparece pedido de autorização do administrador. |
| Entrar com Google e depois com Microsoft no mesmo e-mail, com "uma conta por e-mail" | O segundo login falha. | O padrão do Firebase (seção 4.3). |
| Repetir com "várias contas por e-mail" | Os dois entram; no banco viram uma pessoa só se o e-mail foi provado. | A configuração recomendada. |
| Mais de 100 pessoas novas numa hora, do mesmo endereço | Não dá para fazer à mão. | O limite por IP fica sem prova até a primeira instituição entrar. |

Também ficam fora desta rodada a CAFe real (o SP aguarda o cadastro na federação) e o LDAP de uma
instituição.

## 6. Achados e decisões que o grupo precisa tomar

**1. Ligar "várias contas por e-mail" no projeto.** Sem isso, o segundo provedor com o mesmo e-mail é
barrado, e um e-mail pode ser ocupado por quem não é o dono (seção 4.3). Recomendação: ligar.

**2. Onde roda o bind LDAP no modelo em nuvem** (seção 4.5). Depende do que as instituições aceitam abrir e
do desenho do sistema que fica nelas. Enquanto não houver resposta, o LDAP só funciona no modelo atual. A
instituição que tem login único próprio não depende dessa resposta (seção 4.9).

**3. Dados de login nos EUA e sem SLA.** O Firebase Authentication processa dados só nos EUA e não oferece
escolha de região ([privacidade do Firebase](https://firebase.google.com/support/privacy)). Sem o upgrade
não há SLA. No desenho implementado vão para o Firebase o nome de exibição e, para Google e Microsoft, o e-mail.
Para LDAP, CAFe e login único o e-mail fica só no nosso banco. É assunto para os encarregados de dados, que já estava
nas pendências.

**4. Prazo para pedir login de novo.** O refresh token do Firebase não expira. Sem um corte nosso, quem
saiu da universidade continua entrando para sempre. A prova de conceito recusa login feito há mais de 12
horas (`test_login_feito_ha_mais_de_doze_horas_e_recusado_mesmo_com_token_novo`). O valor é uma proposta;
hoje a sessão dura 14 dias.

**5. Uma aprovação pode levar até uma hora para aparecer no token.** Os claims só entram no token seguinte.
Depois de um login o navegador renova na hora. Depois de uma aprovação pelo gestor de rede, a pessoa
precisa renovar ou entrar de novo. Também já estava nas pendências (D12).

**6. Sair não mata na hora o token que já foi emitido.** Ele vale até uma hora. O ADR-0005 previa consultar
a revogação só nas operações sensíveis. A prova de conceito não implementa essa consulta.

**7. A chave de serviço do projeto vira o segredo mais sensível do sistema.** Quem a tem emite token para
qualquer conta. O backend só emite custom token para os logins que ele mesmo prova
(`test_custom_token_so_para_logins_que_o_backend_prova`), mas a chave em si precisa de cofre e de rodízio.

**8. Três pontos do login atual que a análise expôs e que valem mesmo sem o Firebase:** o login com Google
não restringe domínio nem confere se o e-mail foi verificado; os dados do login vão para a janela principal
com destino `"*"`; e um mesmo segredo assina a sessão, a ponte da CAFe e serve ao Django.

## 7. O que rever nos documentos que já existem

Nada foi alterado neles. São sugestões.

| Documento | O que diz | O que a análise mostra |
|---|---|---|
| ADR-0005 | A CAFe exige o upgrade para Identity Platform, de US$ 22 a 112 por mês. | Com custom token depois do SP, não exige. O upgrade vira opção, por SLA ou segundo fator. |
| ADR-0005 | Não há sessão no servidor. | A prova de conceito aceita o token direto e também mantém o cookie atual, para o encaixe ser pequeno. A escolha continua aberta. |
| ADR-0006 | Duas opções: tenants ou um projeto com claim. Inclinação pela segunda. | A segunda foi implementada e testada contra um projeto real no plano gratuito, sem upgrade. Falta a terceira opção na tabela, um projeto por instituição, que é a indicada para o modelo atual. |
| `PROJECAO-POR-INSTITUICOES.md` | Identidade custa US$ 2,25 por instituição por mês. | No desenho implementado, zero. |
| Resumo de decisões, D33 | Falta testar o e-mail verificado da conta Microsoft de universidade. | A prova passa a ser o `tid`, e o e-mail deixa de ser necessário. Confirmado com conta real de um diretório do Entra ID: o `tid` chega, e o Firebase não marca o e-mail como verificado. |
| Notas de 23/10 | "O Firebase já é usado hoje, numa conta global." | Não é usado. |

## 8. Como encaixar no app

O encaixe não foi feito. O lugar é o `iotedu-stack` (submódulos `_backend` e `_frontend`), que é o que
roda em produção. Os caminhos abaixo são os do `iotedu-dockerized`, iguais no que importa.

1. **Banco** (`app/backend/db/models.py`): uma tabela de identidades (provedor, identificador, conta no
   Firebase, usuário). Na instituição: domínios aceitos, domínio do Workspace, diretório da Microsoft,
   escopo da CAFe e os dados do LDAP. Hoje a instituição não tem nenhum desses campos, e o vínculo é por
   faixa de IP.
2. **Sessão** (`app/backend/auth/dependencies.py`): a sessão guarda o e-mail, e todas as rotas partem dele.
   Passa a guardar o identificador do usuário, porque nem todo login traz um e-mail provado. São as
   funções `get_authenticated_user` e `get_effective_user_id`, mais quatro pontos que leem a sessão direto.
3. **Rotas novas**: as de `backend/poc/app.py`. A regra (`regras.py`), os verificadores (`provedores.py`)
   e o cliente do login único (`oidc_auth.py`) entram como estão.
4. **CAFe** (`app/backend/auth/cafe_auth.py`): o `cafe_finish` é trocado pelo da prova de conceito. O SP
   Django não muda.
5. **Google** (`app/backend/auth/google_auth.py`): sai o fluxo OAuth. Ficam as rotas de perfil.
6. **Painel** (`app/frontend/app/login/LoginPageClient.tsx`): o SDK web do Firebase entra como dependência;
   o popup do Google passa a ser o do Firebase; entram o botão da Microsoft, o formulário do LDAP e o
   botão do login único da instituição. O `pagina/app.js` desta pasta é o modelo.
7. **Liga e desliga por método** (`auth/login_methods.py`, no `iotedu-stack`): hoje vale para a instalação
   inteira. Passa a valer por instituição.

## 9. Próximos passos

1. Terminar a conferência manual (grupo C da seção 5): Google com conta de Workspace de uma instituição, e
   Microsoft com conta de um diretório que não seja o do próprio aplicativo, para ver o pedido de
   autorização do administrador.
2. Levar ao grupo as decisões 1 a 4 da seção 6.
3. Com a resposta dos líderes de implantação sobre as contas institucionais, escolher a primeira
   instituição para o teste real de LDAP. Perguntar também quais têm login único próprio (Keycloak, ADFS):
   para essas, o caminho da seção 4.9 dispensa abrir o diretório.
4. Decidir se o encaixe começa já no modelo atual (um projeto por instalação) ou espera o núcleo.

## Premissas da projeção

As tabelas das seções 4.1 e 4.2 saem de `projecao.py`. Mudar um valor ali e rodar
`python3 projecao.py --relatorio ANALISE-FIREBASE.md` refaz todas.

<!-- tabela:premissas -->
| Premissa | Valor | De onde vem |
|:---|---:|:---|
| usuários ativos por mês, por instituição | 300 | premissa do projeto (v7, PROJECAO-POR-INSTITUICOES.md) |
| o mesmo, hipótese alta | 3.000 | hipótese desta análise: dez vezes a premissa do projeto |
| usuários ativos por mês sem custo, faixa comum (com o upgrade, plano Blaze) | 50.000 | cloud.google.com/identity-platform/pricing |
| usuários ativos por dia, faixa comum (com o upgrade, sem cartão) | 3.000 | firebase.google.com/docs/auth |
| usuários ativos por mês sem custo, SAML e OIDC (com o upgrade, plano Blaze) | 50 | cloud.google.com/identity-platform/pricing |
| US$ por usuário ativo por mês, SAML e OIDC, acima da cota | 0,015 | cloud.google.com/identity-platform/pricing |
| dias de uso por mês, por pessoa | 22 | hipótese desta análise: dias úteis; com o corte de 12 horas, é um login por dia de uso |
| parte dos usuários do mês que entra no dia mais cheio | 0,30 | hipótese desta análise |
| parte dos usuários do mês que entra na hora mais cheia | 0,20 | hipótese desta análise |
| logins com custom token por minuto, por projeto | 45.000 | firebase.google.com/docs/auth/limits |
| renovações de token por minuto, por projeto | 18.000 | firebase.google.com/docs/auth/limits |
| contas novas por hora, por endereço IP | 100 | firebase.google.com/docs/auth/limits |
<!-- /tabela -->

Com a hipótese alta, de 3.000 usuários por instituição:

<!-- tabela:uso_alto -->
| Cenário | Usuários ativos no mês | Sem o upgrade, como na PoC (US$/mês) | Com o upgrade, sem cartão (teto de 3.000 por dia) | Com o upgrade, com cartão (US$/mês) | A mais, se a CAFe fosse SAML nativo (US$/mês) |
|:---|---:|---:|---:|---:|---:|
| UFRGS, hoje | 8 | 0,00 | cabe | 0,00 | 0,00 |
| Unipampa, hoje | 13 | 0,00 | cabe | 0,00 | 0,00 |
| 6 instituições | 18.000 | 0,00 | não cabe | 0,00 | 134,25 |
| 10 instituições | 30.000 | 0,00 | não cabe | 0,00 | 224,25 |
| 50 instituições | 150.000 | 0,00 | não cabe | 505,00 | 1.124,25 |
| 100 instituições | 300.000 | 0,00 | não cabe | 1.195,00 | 2.249,25 |
| 1.000 instituições | 3.000.000 | 0,00 | não cabe | 10.815,00 | 22.499,25 |
<!-- /tabela -->

## Fontes

Documentação oficial, conferida em 25/11/2026:

- Firebase Authentication, visão geral e planos: <https://firebase.google.com/docs/auth>
- Limites: <https://firebase.google.com/docs/auth/limits>
- Preços do Identity Platform: <https://cloud.google.com/identity-platform/pricing>
- Cotas do Identity Platform: <https://docs.cloud.google.com/identity-platform/quotas>
- Comparação dos dois produtos: <https://docs.cloud.google.com/identity-platform/docs/product-comparison>
- SLA: <https://cloud.google.com/identity-platform/sla>
- Verificação do ID token: <https://firebase.google.com/docs/auth/admin/verify-id-tokens>
- Custom token: <https://firebase.google.com/docs/auth/admin/create-custom-tokens>
- Claims: <https://firebase.google.com/docs/auth/admin/custom-claims>
- Sessões e revogação: <https://firebase.google.com/docs/auth/admin/manage-sessions>
- Multi-tenancy: <https://docs.cloud.google.com/identity-platform/docs/multi-tenancy>
- Microsoft no Firebase: <https://firebase.google.com/docs/auth/web/microsoft-oauth>
- Claims do ID token da Microsoft: <https://learn.microsoft.com/en-us/entra/identity-platform/id-token-claims-reference>
- Validação de claims da Microsoft: <https://learn.microsoft.com/en-us/entra/identity-platform/claims-validation>
- `hd` no Google: <https://developers.google.com/identity/openid-connect/openid-connect>
- SAML no Identity Platform: <https://docs.cloud.google.com/identity-platform/docs/web/saml>
- Login com Google e contas com o mesmo e-mail: <https://firebase.google.com/docs/auth/web/google-signin>
- Privacidade e local dos dados: <https://firebase.google.com/support/privacy>

Do projeto:

Os caminhos abaixo são do repositório `iotedu-dockerized`.

- Transcrição da reunião: `docs/arquitetura/25-11-2026-transcricaoReuniao.txt`
- Login atual: `app/backend/auth/` e, no `iotedu-stack`, `docs/pt-br/funcionamento.md`
- Usuários de hoje: `HISTORICO-MODULARIZACAO.md` do `iotedu-stack`
- Decisões anteriores: `docs/arquitetura/mvp/adr/0005-*.md`, `0006-*.md` e o resumo de decisões
  (D12, D24, D33)
- Recomendação do custom token: reunião de 16/11 com o especialista convidado
