"""Rotas da prova de conceito.

Quatro logins, um só resultado: uma conta no Firebase com a instituição, o papel e o estado nos
claims, e a sessão do app.

- Google e Microsoft: o navegador faz o login no Firebase e manda os tokens para `/session`.
- LDAP: o backend prova a senha e devolve um custom token.
- CAFe: o SP SAML que já existe prova a pessoa; o backend devolve um custom token.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import secrets
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from itsdangerous import BadSignature, URLSafeTimedSerializer
from pydantic import BaseModel, Field, SecretStr
from starlette.middleware.sessions import SessionMiddleware

from . import firebase as fb
from . import ldap_auth, ponte_cafe
from .config import Config
from .limite import Limitador
from .provedores import PROVEDORES, TokenDeProvedorInvalido, VerificadorJWKS, VerificadorProvedor
from .regras import ATIVO, RECUSADO, ProvaLogin, decidir
from .repositorio import Repositorio, Usuario
from .sessao import UsuarioAtual, exigir_ativo, exigir_login_recente, resolver

ERRO_DE_SENHA = "Usuário ou senha inválidos."
VALIDADE_ESTADO_CAFE_S = 600
VALIDADE_TROCA_S = 60


class PedidoSessao(BaseModel):
    id_token: str = Field(min_length=20, max_length=8192)
    provedor_id_token: str | None = Field(default=None, max_length=8192)


class PedidoLdap(BaseModel):
    inst: str = Field(min_length=1, max_length=64)
    usuario: str = Field(min_length=1, max_length=64)
    senha: SecretStr  # nunca aparece em repr nem em log


def criar_app(cfg: Config, web_dir: str | Path | None = None,
              verificador: VerificadorProvedor | None = None) -> FastAPI:
    fb.iniciar(cfg)
    repo = Repositorio(cfg.db_caminho)
    verificador = verificador or VerificadorJWKS(cfg.google_client_id, cfg.ms_client_id)
    limite_usuario = Limitador(livres=3)
    limite_ip = Limitador(livres=20)
    assinador = URLSafeTimedSerializer(cfg.sessao_segredo, salt="cafe-estado")
    trocas: dict[str, tuple[str, float]] = {}  # hash do código -> (uid, expira)
    trava_trocas = threading.Lock()
    https = cfg.origem_front.startswith("https://")

    app = FastAPI(title="IoTEdu · PoC de login com Firebase", docs_url=None, redoc_url=None)
    app.add_middleware(
        SessionMiddleware,
        secret_key=cfg.sessao_segredo,
        max_age=int(cfg.max_idade_login_h * 3600),
        same_site="lax",
        https_only=https,
    )

    @app.middleware("http")
    async def cabecalhos(request: Request, call_next):
        resposta = await call_next(request)
        resposta.headers["X-Content-Type-Options"] = "nosniff"
        resposta.headers["Referrer-Policy"] = "no-referrer"  # o token de ponte da CAFe vem na URL
        if request.url.path.startswith("/api/"):
            resposta.headers["Cache-Control"] = "no-store"
        return resposta

    @app.exception_handler(RequestValidationError)
    async def erro_de_validacao(request: Request, exc: RequestValidationError) -> JSONResponse:
        # O erro padrão do FastAPI devolve o valor recebido. Num login, esse valor é a senha.
        erros = [{"loc": list(e.get("loc", ())), "msg": e.get("msg", ""), "type": e.get("type", "")}
                 for e in exc.errors()]
        return JSONResponse({"detail": erros}, status_code=422)

    # ------------------------------------------------------------------ apoio
    def conferir_origem(request: Request) -> None:
        """Contra CSRF de login: POST só com JSON e, se o navegador mandar Origin, da nossa origem."""
        if not request.headers.get("content-type", "").lower().startswith("application/json"):
            raise HTTPException(status_code=415, detail="Envie JSON.")
        origem = request.headers.get("origin")
        if origem and origem.rstrip("/") != cfg.origem_front:
            raise HTTPException(status_code=403, detail="Origem não aceita.")

    def usuario_atual(request: Request) -> UsuarioAtual:
        return resolver(request, repo, cfg.max_idade_login_h)

    def efetivo(usuario: Usuario) -> tuple[str | None, str, str]:
        """(instituição, papel, estado) que vão para os claims e para a sessão."""
        inst = usuario.instituicao if usuario.estado == ATIVO else None
        return inst, usuario.papel, usuario.estado

    def abrir_sessao(request: Request, uid: str, usuario: Usuario, auth_time) -> dict:
        if not usuario.is_active or usuario.estado == RECUSADO:
            raise HTTPException(status_code=403, detail="Conta sem acesso.")
        inst, papel, estado = efetivo(usuario)
        request.session.clear()
        request.session.update({"uid": uid, "email": usuario.email, "inst": inst, "papel": papel,
                                "estado": estado, "auth_time": auth_time})
        return {"estado": estado, "inst": inst, "papel": papel, "nome": usuario.nome,
                "email": usuario.email}

    def entrar_por_custom_token(prova: ProvaLogin, uid: str) -> str:
        """LDAP e CAFe: decide, grava a pessoa e os claims, e só então emite o custom token."""
        decisao = decidir(prova, cfg.instituicoes)
        if decisao.estado == RECUSADO:
            raise HTTPException(status_code=403, detail=decisao.motivo)
        usuario = repo.upsert(prova, decisao, uid)
        if not usuario.is_active or usuario.estado == RECUSADO:
            raise HTTPException(status_code=403, detail="Conta sem acesso.")
        fb.garantir_usuario(uid, usuario.nome)
        fb.gravar_claims(uid, *efetivo(usuario))
        return uid

    # ------------------------------------------------------------------ dados para a página
    @app.get("/config.js")
    def config_js() -> Response:
        dados = {
            "firebase": {"apiKey": cfg.web_api_key, "authDomain": cfg.auth_domain,
                         "projectId": cfg.projeto},
            "origem": cfg.origem_front,
            "teste": cfg.ambiente_de_teste,
            "avisos": list(cfg.avisos),
            "instituicoes": [
                {"slug": i.slug, "nome": i.nome, "metodos": list(i.metodos),
                 "googleHd": i.google_hd[0] if i.google_hd else None,
                 "microsoftTenant": cfg.ms_tenant if cfg.ms_tenant in i.microsoft_tid else None}
                for i in cfg.instituicoes.values()
            ],
        }
        corpo = "window.POC_CONFIG = " + json.dumps(dados).replace("</", "<\\/") + ";\n"
        return Response(corpo, media_type="application/javascript",
                        headers={"Cache-Control": "no-store"})

    # ------------------------------------------------------------------ Google e Microsoft
    @app.post("/api/auth/firebase/session")
    def criar_sessao(pedido: PedidoSessao, request: Request) -> dict:
        conferir_origem(request)
        try:
            claims = fb.verificar_id_token(pedido.id_token)
        except fb.TokenInvalido:
            raise HTTPException(status_code=401, detail="Token inválido.")
        exigir_login_recente(claims.get("auth_time"), cfg.max_idade_login_h)

        uid = claims["uid"]
        info = claims.get("firebase") or {}
        provedor_fb = info.get("sign_in_provider")

        if provedor_fb == "custom":
            # LDAP e CAFe: a pessoa já foi decidida e gravada quando o custom token saiu.
            usuario = repo.por_firebase_uid(uid)
            if usuario is None or not uid.startswith(fb.PREFIXOS_CUSTOM):
                raise HTTPException(status_code=401, detail="Conta desconhecida.")
            return abrir_sessao(request, uid, usuario, claims.get("auth_time"))

        if provedor_fb not in PROVEDORES:
            raise HTTPException(status_code=403, detail="Método de login não aceito.")

        federados = (info.get("identities") or {}).get(provedor_fb) or []
        if len(federados) != 1:
            raise HTTPException(status_code=401, detail="Conta sem identidade do provedor.")

        hd = tid = None
        email, verificado, nome = None, False, claims.get("name") or ""
        if pedido.provedor_id_token:
            try:
                cp = verificador.verificar(provedor_fb, pedido.provedor_id_token)
            except TokenDeProvedorInvalido:
                raise HTTPException(status_code=401, detail="Token do provedor inválido.")
            # O token do provedor tem de ser da mesma conta que o Firebase autenticou.
            if cp.sujeito != federados[0]:
                raise HTTPException(status_code=401, detail="Token do provedor é de outra conta.")
            hd, tid = cp.hd, cp.tid
            email, verificado, nome = cp.email, cp.email_verificado, cp.nome or nome
        # Sem o token do provedor não há prova de instituição: a pessoa entra como pendente.

        prova = ProvaLogin(provedor=PROVEDORES[provedor_fb], sujeito=federados[0], nome=nome,
                           email=email, email_verificado=verificado, hd=hd, tid=tid)
        decisao = decidir(prova, cfg.instituicoes)
        if decisao.estado == RECUSADO:
            raise HTTPException(status_code=403, detail=decisao.motivo)
        usuario = repo.upsert(prova, decisao, uid)
        resposta = abrir_sessao(request, uid, usuario, claims.get("auth_time"))
        # Os claims entram no próximo ID token: o navegador renova logo depois desta chamada.
        fb.gravar_claims(uid, *efetivo(usuario))
        return resposta

    # ------------------------------------------------------------------ LDAP
    @app.post("/api/auth/ldap/login")
    def ldap_login(pedido: PedidoLdap, request: Request) -> Response:
        conferir_origem(request)
        inst = cfg.instituicoes.get(pedido.inst)
        if inst is None or inst.ldap is None or "ldap" not in inst.metodos:
            raise HTTPException(status_code=400, detail="Instituição sem login LDAP.")

        nome_usuario = pedido.usuario.strip()
        chave_u = f"u:{inst.slug}:{nome_usuario.lower()}"
        chave_ip = f"ip:{request.client.host if request.client else '?'}"
        espera = max(limite_usuario.espera(chave_u), limite_ip.espera(chave_ip))
        if espera > 0:
            return JSONResponse({"detail": "Muitas tentativas. Aguarde."}, status_code=429,
                                headers={"Retry-After": str(math.ceil(espera))})

        try:
            attrs = ldap_auth.autenticar(inst.ldap, nome_usuario,
                                         pedido.senha.get_secret_value(),
                                         os.environ.get(inst.ldap.senha_env, ""))
        except ldap_auth.LdapIndisponivel:
            raise HTTPException(status_code=503, detail="Diretório da instituição indisponível.")
        if attrs is None:
            limite_usuario.falha(chave_u)
            limite_ip.falha(chave_ip)
            # A mesma resposta para "não existe" e "senha errada".
            raise HTTPException(status_code=401, detail=ERRO_DE_SENHA)
        limite_usuario.sucesso(chave_u)

        uid_ldap = attrs.uid.strip().lower()
        prova = ProvaLogin(provedor="ldap", sujeito=f"{inst.slug}:{uid_ldap}", nome=attrs.nome,
                           email=attrs.mail, inst_ldap=inst.slug)
        uid = entrar_por_custom_token(prova, f"ldap:{inst.slug}:{uid_ldap}")
        return JSONResponse({"custom_token": fb.emitir_custom_token(uid)})

    # ------------------------------------------------------------------ CAFe
    def pagina_popup(tipo: str, status: int = 200) -> HTMLResponse:
        # Nada sensível na mensagem, e só para a origem do painel (nunca "*").
        alvo = json.dumps(cfg.origem_front).replace("</", "<\\/")
        html = ("<!doctype html><meta charset='utf-8'><title>IoTEdu</title>"
                "<p>Pode fechar esta janela.</p><script>"
                f"if (window.opener) window.opener.postMessage({{tipo: {json.dumps(tipo)}}}, {alvo});"
                "window.close();</script>")
        return HTMLResponse(html, status_code=status)

    @app.get("/api/auth/cafe/login")
    def cafe_login() -> Response:
        """Abre no popup. Marca o navegador que começou o login e manda para o SP."""
        # Sem o SP de verdade configurado, o ambiente de teste usa a "CAFe simulada".
        destino = cfg.cafe_sp_login_url or ("/demo/cafe/sp" if cfg.ambiente_de_teste else None)
        if not destino:
            raise HTTPException(status_code=503, detail="SP da CAFe não configurado.")
        r = RedirectResponse(destino, status_code=303)
        r.set_cookie("cafe_estado", assinador.dumps(secrets.token_urlsafe(16)),
                     max_age=VALIDADE_ESTADO_CAFE_S, httponly=True, samesite="lax", secure=https,
                     path="/api/auth/cafe")
        return r

    @app.get("/api/auth/cafe/finish")
    def cafe_finish(request: Request, token: str = "") -> Response:
        """Recebe o JWT de ponte do SP. Mesmo endereço e mesmo formato do app de hoje."""
        try:
            assinador.loads(request.cookies.get("cafe_estado", ""), max_age=VALIDADE_ESTADO_CAFE_S)
        except BadSignature:
            # Ninguém neste navegador começou um login: o link veio de fora.
            return pagina_popup("cafe-erro", 400)
        try:
            attrs = ponte_cafe.validar(token, cfg.ponte_segredo, repo.registrar_ponte)
        except ponte_cafe.PonteInvalida:
            r = pagina_popup("cafe-erro", 400)
            r.delete_cookie("cafe_estado", path="/api/auth/cafe")
            return r

        prova = ProvaLogin(provedor="cafe", sujeito=attrs.eppn, nome=attrs.nome, email=attrs.email,
                           eppn=attrs.eppn)
        try:
            uid = entrar_por_custom_token(prova, f"cafe:{attrs.eppn}")
        except HTTPException:
            r = pagina_popup("cafe-erro", 403)
            r.delete_cookie("cafe_estado", path="/api/auth/cafe")
            return r

        # O custom token não vai pela janela: fica um código de uso único num cookie HttpOnly.
        codigo = secrets.token_urlsafe(32)
        with trava_trocas:
            agora = time.time()
            for k in [k for k, (_, exp) in trocas.items() if exp < agora]:
                del trocas[k]
            trocas[hashlib.sha256(codigo.encode()).hexdigest()] = (uid, agora + VALIDADE_TROCA_S)
        r = pagina_popup("cafe-ok")
        r.delete_cookie("cafe_estado", path="/api/auth/cafe")
        r.set_cookie("cafe_troca", codigo, max_age=VALIDADE_TROCA_S, httponly=True,
                     samesite="strict", secure=https, path="/api/auth/cafe")
        return r

    @app.post("/api/auth/cafe/token")
    def cafe_token(request: Request) -> Response:
        """A janela principal troca o código (cookie) pelo custom token. Vale uma vez."""
        conferir_origem(request)
        codigo = request.cookies.get("cafe_troca", "")
        with trava_trocas:
            uid, expira = trocas.pop(hashlib.sha256(codigo.encode()).hexdigest(), ("", 0.0))
        if not uid or expira < time.time():
            raise HTTPException(status_code=401, detail="Login pela CAFe não concluído.")
        r = JSONResponse({"custom_token": fb.emitir_custom_token(uid)})
        r.delete_cookie("cafe_troca", path="/api/auth/cafe")
        return r

    # ------------------------------------------------------------------ sessão
    @app.post("/api/auth/logout")
    def logout(request: Request) -> dict:
        conferir_origem(request)
        uid = request.session.get("uid")
        request.session.clear()
        if uid:
            fb.encerrar_sessoes(uid)  # o navegador não renova mais o ID token
        return {"ok": True}

    @app.get("/api/me")
    def me(atual: UsuarioAtual = Depends(usuario_atual)) -> dict:
        return {"uid": atual.uid, "usuario_id": atual.usuario_id, "email": atual.email,
                "nome": atual.nome, "inst": atual.inst,
                "papel": atual.papel, "estado": atual.estado, "via": atual.via}

    @app.get("/api/painel")
    def painel(atual: UsuarioAtual = Depends(usuario_atual)) -> dict:
        """Exemplo de rota que exige entrada aprovada, conferida no banco."""
        exigir_ativo(atual, repo)
        return {"inst": atual.inst, "mensagem": f"Painel de {atual.inst}"}

    # ------------------------------------------------------------------ só no ambiente de teste
    if cfg.ambiente_de_teste:
        @app.get("/demo/cafe/sp", response_class=HTMLResponse)
        def demo_sp() -> str:
            """Faz o papel do SP SAML e do IdP da CAFe. Só existe com AMBIENTE_DE_TESTE=1."""
            return ("<!doctype html><meta charset='utf-8'><title>CAFe simulada</title>"
                    "<body style='font-family:sans-serif;max-width:28rem;margin:2rem auto'>"
                    "<h1>CAFe simulada</h1><p>Esta tela só existe no ambiente de teste. Ela faz o papel "
                    "do SP SAML e da universidade.</p><form method='post'>"
                    "<p><label>eduPersonPrincipalName<br><input name='eppn' "
                    "value='ana@unia.test' size='32'></label></p>"
                    "<p><label>mail<br><input name='email' value='ana@unia.test' size='32'></label>"
                    "</p><p><label>Nome<br><input name='nome' value='Ana'></label> "
                    "<label>Sobrenome<br><input name='sobrenome' value='Teste'></label></p>"
                    "<button>Entrar</button></form></body>")

        @app.post("/demo/cafe/sp")
        async def demo_sp_entrar(request: Request) -> Response:
            f = {k: v[0] for k, v in parse_qs((await request.body()).decode()).items()}
            token = ponte_cafe.emitir_demo(f.get("eppn", ""), f.get("email", ""),
                                           f.get("nome", ""), f.get("sobrenome", ""),
                                           cfg.ponte_segredo)
            return RedirectResponse(f"/api/auth/cafe/finish?token={token}", status_code=303)

        @app.post("/demo/reset")
        def demo_reset() -> dict:
            fb.apagar_contas(repo.uids_custom())  # as contas de teste criadas no projeto
            repo.limpar()
            limite_usuario.limpar()
            limite_ip.limpar()
            with trava_trocas:
                trocas.clear()
            return {"ok": True}

    if web_dir and Path(web_dir).is_dir():
        app.mount("/", StaticFiles(directory=str(web_dir), html=True), name="web")
    return app
