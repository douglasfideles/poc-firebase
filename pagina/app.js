// Página de demonstração: os quatro logins, todos terminando numa conta do Firebase.
// Sem build: o SDK web vem do CDN oficial, com a versão fixada.
import { initializeApp } from "https://www.gstatic.com/firebasejs/13.4.0/firebase-app.js";
import {
  GoogleAuthProvider,
  OAuthProvider,
  getAuth,
  inMemoryPersistence,
  setPersistence,
  signInWithCustomToken,
  signInWithPopup,
  signOut,
} from "https://www.gstatic.com/firebasejs/13.4.0/firebase-auth.js";

const C = window.POC_CONFIG;
const auth = getAuth(initializeApp(C.firebase));
// A sessão do app é o cookie do backend. O refresh token do Firebase não fica guardado no navegador.
const pronto = setPersistence(auth, inMemoryPersistence);

const $ = (id) => document.getElementById(id);
const instituicao = () => C.instituicoes.find((i) => i.slug === $("inst").value);

function mostrarErro(texto) {
  $("erro").textContent = texto;
  $("erro").hidden = !texto;
}

async function api(caminho, opcoes = {}) {
  const r = await fetch(caminho, { credentials: "include", ...opcoes });
  let corpo = null;
  try { corpo = await r.json(); } catch { /* sem corpo */ }
  return { status: r.status, corpo };
}

const postar = (caminho, dados = {}) =>
  api(caminho, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(dados),
  });

function claimsDe(idToken) {
  const meio = idToken.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
  return JSON.parse(decodeURIComponent(escape(atob(meio))));
}

// Depois de qualquer login: o backend confere os tokens, decide e abre a sessão.
async function concluir(usuario, provedorIdToken) {
  const sessao = await postar("/api/auth/firebase/session", {
    id_token: await usuario.getIdToken(),
    provedor_id_token: provedorIdToken || null,
  });
  if (sessao.status !== 200) {
    await signOut(auth);
    throw new Error(sessao.corpo?.detail || "O backend recusou o login.");
  }
  // Os claims (instituição, papel, estado) entram no token seguinte.
  const novo = await usuario.getIdToken(true);
  const porCookie = await api("/api/me");
  const porBearer = await api("/api/me", { headers: { Authorization: `Bearer ${novo}` } });
  const painel = await api("/api/painel");

  $("resumo").textContent =
    sessao.corpo.estado === "ativo"
      ? `Entrou em ${sessao.corpo.inst}, como ${sessao.corpo.papel}.`
      : "Entrada pendente: o login não provou que a conta é de uma instituição cadastrada.";
  $("claims").textContent = JSON.stringify(claimsDe(novo), null, 2);
  $("respostas").textContent = JSON.stringify(
    { "POST /api/auth/firebase/session": sessao, "GET /api/me (cookie)": porCookie,
      "GET /api/me (Bearer)": porBearer, "GET /api/painel": painel }, null, 2);
  $("resultado").hidden = false;
}

// Fechar a janela de login ou abrir outra por cima não é erro: a pessoa só desistiu daquela tentativa.
const DESISTENCIAS = ["auth/cancelled-popup-request", "auth/popup-closed-by-user"];
const BOTOES = ["google", "microsoft", "cafe", "sair"];
let emAndamento = false;

async function tentar(acao) {
  if (emAndamento) return;  // um login por vez: o segundo clique não abre outra janela
  emAndamento = true;
  for (const b of BOTOES) $(b).setAttribute("aria-disabled", "true");
  mostrarErro("");
  try {
    await pronto;
    await acao();
    mostrarErro("");
  } catch (e) {
    if (!DESISTENCIAS.includes(e?.code)) mostrarErro(e?.message || "Não foi possível entrar.");
  } finally {
    emAndamento = false;
    for (const b of BOTOES) $(b).removeAttribute("aria-disabled");
  }
}

$("google").addEventListener("click", () => tentar(async () => {
  const provedor = new GoogleAuthProvider();
  // Com "várias contas por e-mail" ligado no projeto, o Firebase não pede o e-mail ao Google por
  // conta própria. Sem ele o token não traz `email` nem `email_verified`, e ninguém seria aprovado.
  provedor.addScope("email");
  const hd = instituicao()?.googleHd;
  // `hd` só sugere o domínio na tela do Google. Quem confere é o backend.
  provedor.setCustomParameters({ prompt: "select_account", ...(hd ? { hd } : {}) });
  const r = await signInWithPopup(auth, provedor);
  await concluir(r.user, GoogleAuthProvider.credentialFromResult(r)?.idToken);
}));

$("microsoft").addEventListener("click", () => tentar(async () => {
  const provedor = new OAuthProvider("microsoft.com");
  provedor.addScope("email");
  provedor.setCustomParameters({
    prompt: "select_account",
    tenant: instituicao()?.microsoftTenant || "organizations",
  });
  const r = await signInWithPopup(auth, provedor);
  await concluir(r.user, OAuthProvider.credentialFromResult(r)?.idToken);
}));

$("ldap").addEventListener("submit", (ev) => {
  ev.preventDefault();
  tentar(async () => {
    const r = await postar("/api/auth/ldap/login", {
      inst: $("inst").value,
      usuario: $("usuario").value,
      senha: $("senha").value,
    });
    $("senha").value = "";
    if (r.status !== 200) throw new Error(r.corpo?.detail || "Não foi possível entrar.");
    const cred = await signInWithCustomToken(auth, r.corpo.custom_token);
    await concluir(cred.user, null);
  });
});

$("cafe").addEventListener("click", () => {
  if (emAndamento) return;
  // A janela abre no próprio clique, senão o navegador a bloqueia.
  const popup = window.open("/api/auth/cafe/login", "cafe", "width=520,height=640");
  if (!popup) return mostrarErro("O navegador bloqueou a janela de login.");
  const ouvir = (ev) => {
    // Só a nossa origem e só a janela que abrimos.
    if (ev.origin !== window.location.origin || ev.source !== popup) return;
    window.removeEventListener("message", ouvir);
    tentar(async () => {
      if (ev.data?.tipo !== "cafe-ok") throw new Error("O login pela CAFe não foi concluído.");
      const r = await postar("/api/auth/cafe/token");
      if (r.status !== 200) throw new Error(r.corpo?.detail || "Não foi possível entrar.");
      const cred = await signInWithCustomToken(auth, r.corpo.custom_token);
      await concluir(cred.user, null);
    });
  };
  window.addEventListener("message", ouvir);
});

$("sair").addEventListener("click", () => tentar(async () => {
  await postar("/api/auth/logout");
  await signOut(auth);
  $("resultado").hidden = true;
}));

function atualizarBotoes() {
  const metodos = instituicao()?.metodos || [];
  $("google").disabled = !metodos.includes("google");
  $("microsoft").disabled = !metodos.includes("microsoft");
  $("cafe").disabled = !metodos.includes("cafe");
  $("ldap").hidden = !metodos.includes("ldap");
}

for (const i of C.instituicoes) {
  const o = document.createElement("option");
  o.value = i.slug;
  o.textContent = i.nome;
  $("inst").append(o);
}
$("inst").addEventListener("change", atualizarBotoes);
atualizarBotoes();

const avisos = [...(C.avisos || [])];
if (C.teste) avisos.push("Ambiente de teste: o botão da CAFe abre uma universidade simulada.");
if (avisos.length) {
  $("modo").textContent = avisos.join(" ");
  $("modo").hidden = false;
}
