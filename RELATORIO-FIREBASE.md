# Firebase no IoTEdu: relatório da tarefa de 25/11/2026

**GT-IoTEdu · 25/11/2026.** A reunião de 25/11 fechou, a princípio, que a autenticação passa toda pelo
Firebase, e pediu esta análise para dar segurança à decisão. A tarefa, para sexta, 27/11, é testar os
provedores e responder às perguntas técnicas: limites do plano gratuito, volume, múltiplos domínios e
conta por instituição. Este relatório responde aos cinco pontos.

**Conclusão: a análise confirma a decisão, com as ressalvas da seção 8.** Os logins que a reunião fixou
(Google, Microsoft e LDAP) funcionam com o Firebase no plano gratuito, sem cartão e sem custo por usuário.
O que falta é teste com contas e sistemas de instituições de verdade, e sete decisões do grupo.

O detalhe de cada resposta, com as fontes e o teste que a sustenta, está em
[ANALISE-FIREBASE.md](ANALISE-FIREBASE.md). Como rodar a prova de conceito está no [README.md](README.md).
Os números do Firebase vêm da documentação oficial, consultada em 25/11/2026.

## Resumo

| Ponto da tarefa | Resposta |
|---|---|
| Limites do plano gratuito | No desenho testado não há cobrança por usuário nem teto de usuários ativos, e não é preciso cartão. Os limites por minuto ficam longe do nosso uso. O de 100 contas novas por hora por endereço IP pode pegar e não foi testado. |
| Volume | O Firebase não conta autenticações. Com o upgrade pago ele conta usuários ativos; sem o upgrade, nem isso. Em 12/10 havia 21 contas nas duas instalações. Com mil instituições o pico de logins ficaria em 2% do limite. |
| Múltiplos domínios | Vários domínios de e-mail por instituição não mudam nada no Firebase: a lista é nossa. O que exige cuidado é ligar "várias contas por e-mail" no projeto. Um domínio autorizado vale para os subdomínios dele. |
| Conta por instituição | No modelo atual, um projeto por instalação. No núcleo em nuvem, um projeto global com a instituição dentro do token. O que decide é onde a chave do projeto fica. |
| Provedores | Cinco caminhos de login implementados na prova de conceito: Google, Microsoft, LDAP, CAFe e o login único próprio de uma instituição. LDAP, CAFe e login único rodaram de ponta a ponta contra um projeto Firebase de verdade. A Microsoft entrou aprovada com uma conta real. No Google, só o caminho "pendente" foi visto com conta real. Faltam os testes com contas e sistemas de instituições. |

## 1. Limites do plano gratuito

Existem dois produtos com o mesmo nome: o Firebase Authentication e o Identity Platform, que é o upgrade
pago. O desenho testado usa só o primeiro.

| | Sem o upgrade (o que foi testado) | Com o upgrade para Identity Platform |
|---|---|---|
| Google, Microsoft e custom token | Sem cobrança por usuário e sem teto de usuários ativos. | Sem cartão: 3.000 usuários ativos por dia. Com cartão: 50.000 por mês sem custo, depois de US$ 0,0055 a 0,0025 por usuário. |
| SAML e OIDC pelo próprio Firebase | Não tem. | Sem cartão: 2 usuários por dia. Com cartão: 50 por mês sem custo, por projeto, depois US$ 0,015 por usuário. |
| Tenants (um silo por instituição) | Não tem. | Sem cartão: 2 tenants. Com cartão: sem limite. |
| SLA | Não tem. | 99,95%, mas só para login com e-mail e senha e para a renovação do token. Login com Google, Microsoft e custom token não está no SLA. A compensação é crédito sobre a fatura. |
| Segundo fator e registros de auditoria | Não tem. | Tem. |

Duas páginas oficiais divergem num ponto: a de preços do Firebase lista 50 mil usuários por mês para o
projeto com upgrade e sem cartão, e as de limites e de cotas listam 3.000 por dia. Vale o menor.

LDAP, CAFe e o login único da instituição entram por **custom token**: o nosso backend prova quem é a
pessoa e pede ao Firebase um token para ela. Por isso nenhum login precisa do SAML, do OIDC ou dos tenants
do Firebase, e o custo por usuário é zero em qualquer cenário. Isso foi conferido com execução, num projeto
no plano gratuito, sem cartão e sem o upgrade.

Limites que valem mesmo sem o upgrade:

| Limite | Valor | Onde pode pegar |
|---|---|---|
| Logins com custom token (LDAP, CAFe, login único) | 45.000 por minuto, por projeto | Não pega. |
| Logins com Google e Microsoft | Não há linha própria na página de limites. O teto geral da API é de 180.000 pedidos por minuto, por projeto. | Não pega. |
| Renovações de token | 18.000 por minuto, por projeto | Com mil instituições, 28% se todos estivessem logados ao mesmo tempo. |
| Contas novas | 100 por hora, por endereço IP | Pode pegar na primeira semana de uma instituição, se o campus inteiro sair por um IP só. Não foi possível testar. |
| Claims gravados por nós | 1.000 bytes por conta | Usamos três campos curtos. |
| Domínios autorizados | A lista não aceita `*`, mas um domínio vale para os subdomínios dele | Com os painéis em subdomínios de um domínio nosso, basta um cadastro (seção 3). |
| Projetos por conta Google | Cerca de 5 a 10 sem cartão | Pesa na opção de um projeto por instituição. |

O que pode pesar: sem o upgrade não há SLA; e, em qualquer plano, o Firebase Authentication processa os
dados só nos EUA.

## 2. Volume

**O Firebase não conta autenticações.** Sem o upgrade não há contagem nenhuma. Com o upgrade, a unidade é o
usuário ativo (por dia sem cartão, por mês com cartão): quem entra 1 ou 30 vezes conta uma vez. O "15 mil
autenticações grátis" citado nas reuniões de 05/10 e 23/10 não existe nas páginas de preço.

Em 12/10/2026, data da última contagem, havia 8 contas no banco da UFRGS e 13 no da Unipampa. São contas
cadastradas, não usuários ativos no mês. Para projetar, esta análise usa 300 usuários ativos por mês por
instituição, o mesmo valor da projeção de custos de outubro. É uma hipótese: o grupo ainda não tem uma
projeção de usuários.

| Cenário | Usuários ativos no mês | Autenticações no mês (teto) | Logins por minuto na hora mais cheia | Parte do limite de 45.000 por minuto | Custo no desenho testado (US$/mês) |
|:---|---:|---:|---:|---:|---:|
| Contagem de 12/10 (duas instalações) | 21 | 462 | 0,1 | 0,000% | 0,00 |
| 10 instituições | 3.000 | 66.000 | 10,0 | 0,022% | 0,00 |
| 100 instituições | 30.000 | 660.000 | 100,0 | 0,222% | 0,00 |
| 1.000 instituições | 300.000 | 6.600.000 | 1.000,0 | 2,222% | 0,00 |

O teto de autenticações supõe um login por dia útil por pessoa (22 no mês), que é o que o corte de 12
horas da seção 8 produz. A hora mais cheia supõe 20% dos usuários do mês entrando na mesma hora. As duas
são hipóteses desta análise; mudar o valor em `projecao.py` refaz as tabelas. O número de autenticações
não entra em cota de uso nem em custo: só importa para os limites por minuto.

A verificação do token no backend usa as chaves públicas do Google, sem chamada ao Firebase a cada pedido,
e não aparece em nenhuma tabela de limites. Isso vale enquanto a checagem de revogação estiver desligada.

Se o upgrade for feito um dia, por causa do segundo fator ou dos registros de auditoria, a cota de 50 mil
usuários sem custo cobre até 166 instituições de 300 usuários.

## 3. Múltiplos domínios

"Domínio" aparece em quatro lugares, e cada um se resolve de um jeito.

| Onde | O que acontece | O que fazer |
|---|---|---|
| Domínios de e-mail de uma instituição | Nada muda no Firebase. O provedor Google é um só para todas as contas. | A lista de domínios é nossa, por instituição, e quem confere é o backend. |
| Endereços do painel | O Firebase só aceita login vindo dos domínios autorizados no projeto. Um domínio autorizado vale para os subdomínios dele. | Com os painéis em subdomínios de um domínio nosso, basta um cadastro. Só um painel em domínio próprio da instituição pede cadastro a mais. |
| Diretórios da Microsoft | O Firebase tem uma só configuração Microsoft por projeto. | O aplicativo no Entra ID tem de ser multilocatário. É provável que o administrador de cada universidade precise autorizá-lo uma vez. Só se confirma com um diretório real. |
| O mesmo e-mail em dois provedores | Um projeto novo vem com "uma conta por e-mail". Quem entrou com Google não entra depois com Microsoft no mesmo e-mail institucional. Quem chegar primeiro com um e-mail alheio trava o dono, a menos que o dono entre por um provedor que o Firebase considera confiável para aquele endereço. | Ligar no console "criar várias contas para cada provedor de identidade". No banco da prova de conceito a chave da pessoa é o par (provedor, identificador). No sistema de hoje ainda é o e-mail. |

O ponto dos subdomínios foi testado em 25/11, num navegador, com o projeto de teste: com `localhost` na
lista, o login a partir de `unia.localhost` e de `painel.unia.localhost` chegou à tela do Google; a partir
de `127.0.0.1`, que não está na lista, o Firebase respondeu `auth/unauthorized-domain`. Falta repetir com
um domínio de verdade.

O e-mail nunca serve de prova de que a pessoa é da instituição. A prova muda por provedor: o domínio do
Workspace no Google (`hd`), o diretório no Entra ID (`tid`), o bind no LDAP, o escopo do identificador na
CAFe e a assinatura do provedor no login único. No Google, na Microsoft e na CAFe, quem não prova entra
como pendente, à espera do gestor de rede.

Três ressalvas sobre essas provas:

- **No LDAP e no login único, ter conta no diretório ou no provedor cadastrado já aprova.** Um provedor que
  aceita cadastro livre não serve de prova. É pergunta para fazer a cada instituição antes de ligar.
- **Na CAFe, a prova confia no escopo que o SP entrega.** Falta conferir que o SP restringe o escopo por
  universidade.
- **O e-mail junta dois logins numa pessoa só** quando é de um domínio da instituição e veio do diretório,
  da CAFe, do Entra ID, ou verificado pelo Google ou pelo login único. Numa instituição em que a pessoa
  edita o próprio e-mail no diretório, isso permitiria assumir o cadastro de um colega. Está na seção 8.

## 4. Conta por instituição ou uma global

O que a reunião chamou de "conta Firebase" é o que o console chama de projeto. A reunião de 25/11 não
decidiu entre global e por instituição; só perguntou. Em 23/10 ficou registrado "uma conta global do
IoTEdu", pensando na nuvem.

As três opções funcionam. A diferença está em quem garante o isolamento e em onde fica a chave. No ADR-0006
as letras são outras: lá, A é a opção dos tenants e B é a do claim.

| | A. Um projeto global, instituição no token | B. Um projeto, um tenant por instituição | C. Um projeto por instituição |
|---|---|---|---|
| Quem isola as instituições | Nós, pelo claim e pela conferência no banco. | O Google. | O Google. |
| Upgrade e cartão | Não precisa. | Precisa do upgrade e, a partir do terceiro tenant, do cartão. | Não precisa. |
| Instituição nova | Uma linha de cadastro. | Criar o tenant e os provedores dele. | Criar o projeto, os provedores, a chave e o domínio. Esbarra na cota de projetos. |
| Se a chave do projeto vaza | Emite token para qualquer pessoa de qualquer instituição. | Idem. | Só para aquela instituição. |
| Implementado na prova | Sim. | Não. | Não. |

Para emitir custom token e gravar claims, o backend precisa da chave de serviço do projeto, e quem tem essa
chave entra como qualquer pessoa. Por isso a recomendação depende de onde o backend roda:

- **No modelo atual, com uma instalação em cada instituição: opção C**, um projeto por instalação. Um
  projeto global obrigaria a pôr a mesma chave no servidor de cada universidade. Esta recomendação é nova;
  não estava em nenhum registro anterior.
- **No núcleo em nuvem: opção A**, um projeto global com a chave só no núcleo. Mantém o que foi registrado
  em 23/10. Rever para a opção B se uma instituição exigir, por contrato, isolamento de contas no provedor.

## 5. Provedores testados

A reunião fixou três logins sem discussão (LDAP, Google e Microsoft) e o critério "o que os seis primeiros
adotantes precisam". A lista do que cada um usa ainda não existe; só a UFSM foi citada, com OpenLDAP. A
CAFe e o login único da instituição foram testados além do pedido.

Todos os caminhos terminam igual: uma conta no Firebase com a instituição, o papel e o estado gravados
no token, e a sessão do sistema.

| Login | Como entra | Contra o que foi testado | Resultado | O que falta |
|---|---|---|---|---|
| Google | Provedor do Firebase. O backend confere o domínio do Workspace. | Testes automáticos do nosso código, com token assinado por uma chave local. Na tela, com uma conta pessoal. | A conta pessoal ficou pendente, como deve. A aprovação pelo domínio do Workspace ainda não rodou com token real. | Conta de Workspace de uma instituição. |
| Microsoft | Provedor do Firebase. O backend confere o diretório do Entra ID. | Testes automáticos. Na tela, com uma conta real de um diretório do Entra ID. | Entrou aprovado. | Conta de outro diretório, para ver o pedido de autorização do administrador. |
| LDAP | O backend faz o bind por TLS e pede um custom token. | Um OpenLDAP de verdade, em container. Ponta a ponta com o Firebase e num navegador. | Passou. | O diretório de uma instituição. Active Directory: só o cadastro foi preparado. |
| CAFe | O SP SAML que o IoTEdu já tem avisa o backend, que pede um custom token. | Uma universidade simulada no lugar do SP. Ponta a ponta com o Firebase e num navegador. | Passou. | A CAFe real: o SP aguarda o cadastro na federação. |
| Login único da instituição (OIDC) | O backend confere o token do provedor da instituição e pede um custom token. | Um provedor simulado, ponta a ponta com o Firebase e num navegador. Um Keycloak de verdade (26.4.7) na frente do OpenLDAP de teste, num navegador. | Passou. Pelo Keycloak e pelo LDAP, a mesma pessoa virou um usuário só. | O provedor de uma instituição. |

Rodada de 25/11/2026, contra o projeto Firebase de teste:

| O que roda | Resultado |
|---|---|
| Testes do nosso código (regra de entrada, rotas, banco, LDAP, CAFe, login único) | 160 de 160 passaram |
| Testes de ponta a ponta, com tokens emitidos e assinados pelo Firebase | 10 de 10 passaram |
| A página num Chromium sem tela, com o SDK web do Firebase | 4 de 4 passaram; com o Keycloak ligado, 5 de 5 |

O que os testes com o Firebase de verdade provam: o custom token do backend é aceito no plano gratuito; a
instituição já vem no primeiro token; token adulterado, com o conteúdo trocado ou sem assinatura é
recusado; e sair invalida a renovação. O token que já tinha sido emitido continua valendo por até uma hora.

Dois pontos sobre os provedores que a reunião não tinha:

- **No LDAP, a senha da pessoa passa pelo nosso backend.** Hoje o backend do IoTEdu não recebe senha em
  nenhum login: Google, CAFe e o IdP IoTEdu (um Keycloak, por OIDC) autenticam fora dele. Na prova de
  conceito a senha não é registrada nem guardada, e há um limite de tentativas com espera crescente.
- **Com Keycloak (ou outro login único) na frente do diretório, a senha não passa pelo nosso backend**, e a
  instituição não precisa abrir o LDAP para o IoTEdu. No núcleo em nuvem, é o caminho que não depende de
  alcançar o diretório. O teste foi na própria máquina, com o Keycloak na mesma rede do backend; falta um
  provedor público, por HTTPS. O sistema atual já tem um login OIDC com o Keycloak da própria instalação;
  o caminho novo segue o mesmo desenho, apontado para o provedor da instituição.

## 6. Esforço para adotar

| Login | No Firebase | Fora do Firebase | Código nosso |
|---|---|---|---|
| Google | Ligar o provedor. | Nada. | A conferência do domínio do Workspace. |
| Microsoft | Ligar o provedor e colar o identificador e o segredo. | Registrar um aplicativo no Entra ID, num diretório de quem opera a plataforma. O segredo tem validade. | A conferência do diretório, no mesmo arquivo do Google. |
| LDAP | Nada. | A instituição cria uma conta de serviço só de leitura e informa endereço, base e certificado. | O bind e o limite de tentativas. |
| CAFe | Nada. | O cadastro do SP na federação, que já estava pendente. | A ponte entre o SP que já existe e o Firebase. |
| Login único da instituição | Nada. | A instituição registra o IoTEdu como cliente no provedor dela. | O cliente OIDC. |
| Apple e redes sociais | Provedores do Firebase. A Apple exige o programa de desenvolvedores, que é pago. | Registrar um aplicativo em cada uma. | Uma entrada na tabela de provedores. Não provam instituição: quem entra por elas fica sempre pendente. |

O Firebase não reduz o código de login. Ele tira de nós o protocolo com o Google e a Microsoft, a emissão
e a renovação dos tokens e a guarda das contas. A regra de quem entra em qual instituição continua nossa.
O encaixe no sistema não foi feito; o roteiro está na seção 8 da análise.

## 7. O que não foi testado

| O que falta | Do que precisa |
|---|---|
| Um domínio autorizado cobrindo subdomínios, com domínio de verdade | Um domínio nosso com dois subdomínios apontando para o painel. |
| Google com conta de instituição | Uma conta de Google Workspace de uma universidade. |
| Microsoft com várias universidades | Um aplicativo multilocatário e uma conta de um diretório que não seja o do aplicativo. |
| LDAP de uma instituição | O endereço, a base e uma conta de serviço só de leitura (a UFSM foi citada). |
| Active Directory | Um diretório AD de teste ou de uma instituição. |
| CAFe real | O cadastro do SP, pelo menos na federação de homologação. |
| Login único de uma instituição | Uma instituição com Keycloak, ADFS ou parecido. |
| Limite de 100 contas novas por hora por IP | A primeira instituição entrando de verdade. |
| O Firebase com "uma conta por e-mail" e com "várias contas" | Duas contas, Google e Microsoft, com o mesmo e-mail. O que o relatório diz vem da documentação. |
| Mais de uma cópia do backend | Levar para um lugar compartilhado o que hoje fica na memória de um processo: tentativas de senha, logins em andamento e códigos de troca. |

## 8. Decisões que o grupo precisa tomar

1. **Ligar "várias contas por e-mail" no projeto.** Recomendação: ligar.
2. **Onde roda o bind LDAP no modelo em nuvem.** O núcleo não alcança o diretório da instituição. Para quem
   tem login único próprio, a pergunta deixa de existir.
3. **Dados de login nos EUA e sem SLA.** É assunto para os encarregados de dados.
4. **A CAFe com a conta no Firebase.** Com custom token, a CAFe dispensa o upgrade que o ADR-0005 dava como
   necessário. Mas em 23/10 houve a objeção de que pôr o Google no caminho das identidades institucionais
   pode ter implicação jurídica. Aqui a universidade continua autenticando a pessoa, e a conta dela passa
   a existir no Firebase, só com o nome. Depende da resposta da RNP e dos encarregados de dados.
5. **Prazo para pedir login de novo.** O token de renovação do Firebase não expira sozinho. A prova de
   conceito recusa login feito há mais de 12 horas. Hoje a sessão vale 14 dias sem uso e se renova a cada
   acesso. No login único, pedir login de novo não obriga a digitar a senha: enquanto a sessão no provedor
   da instituição durar, a pessoa volta direto.
6. **Quem opera a plataforma.** O registro do aplicativo da Microsoft e a chave do projeto têm de ficar com
   quem opera, e não numa conta pessoal.
7. **Quando o e-mail junta dois logins numa pessoa.** Hoje basta o e-mail ser de um domínio da instituição
   e vir do diretório, da CAFe ou do Entra ID. A opção mais fechada é só juntar quando o provedor diz que
   verificou o e-mail, ou quando o gestor de rede confirma.

Uma correção a um documento anterior: a resposta à reunião de 05/10 dizia que o plano gratuito, sem o
upgrade, tinha teto de 3.000 usuários ativos por dia. Relendo a documentação, esse teto é do projeto com
upgrade e sem cartão. Sem o upgrade não há teto.

## Como conferir

```sh
./preparar.sh                             # gera os segredos; depois preencha o bloco do Firebase no .env
docker compose up -d --build              # OpenLDAP de teste e backend
docker compose --profile teste build      # as imagens dos testes; refaça depois de mudar o código
docker compose run --rm testes            # testes do nosso código
docker compose run --rm testes-firebase   # ponta a ponta contra o projeto Firebase
docker compose run --rm navegador         # a página num Chromium sem tela
```

Depois, `http://localhost:8088` tem os cinco logins numa página só. O passo a passo, inclusive o Keycloak
de teste, está no [README.md](README.md).
