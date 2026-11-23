"""Linha de comando.

    esferoides medir        mede todas as imagens e escreve o CSV bruto
    esferoides verificar    as quatro checagens + triagem + resumo
    esferoides graficos     curvas de compactação e de forma
    esferoides revisar      abre a interface de conferência
    esferoides reconstruir  refaz o banco a partir do diário e das máscaras
"""

from __future__ import annotations

import argparse
import os
import secrets
import socket
import threading
import webbrowser
from pathlib import Path

from . import config

PORTA = 7860
SESSAO_VALIDACAO = Path("dados/validacao-cega")


def _comum(p: argparse.ArgumentParser) -> None:
    p.add_argument("--dados", default=None,
                   help=f"raiz das imagens (ou variável {config.VAR_AMBIENTE})")


def construir_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="esferoides", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="comando", required=True)

    m = sub.add_parser("medir", help="mede todas as imagens")
    _comum(m)
    m.add_argument("--limite", type=int, default=None,
                   help="processa apenas N imagens, amostradas ao longo do conjunto")

    v = sub.add_parser("verificar", help="checagens obrigatórias e triagem")
    _comum(v)

    g = sub.add_parser("graficos", help="curvas de compactação e de forma")
    _comum(g)
    g.add_argument("--brutas", action="store_true",
                   help="usa medidas_esferoides.csv em vez de medidas_final.csv")
    g.add_argument("--conferidas", action="store_true",
                   help="plota só as linhas já conferidas à mão (status=manual)")

    r = sub.add_parser("revisar", help="interface de conferência manual")
    _comum(r)
    r.add_argument("--projetos", type=Path, default=Path("dados/projetos"),
                   help="pasta privada do catálogo e dos projetos importados")
    r.add_argument("--galeria", type=Path,
                   help="galeria HTML local opcional para o projeto indicado por --dados")
    r.add_argument("--somente-sinalizadas", action="store_true",
                   help="só as imagens da triagem (padrão: todas)")
    r.add_argument("--porta", type=int, default=PORTA,
                   help="porta do Spheroid Lab (padrão: %(default)s)")
    r.add_argument("--sessao", type=Path, default=SESSAO_VALIDACAO,
                   help="pasta privada da Validação Cega")
    r.add_argument("--cookie-seguro", action="store_true", help="use quando houver HTTPS na frente")
    r.add_argument("--rede", action="store_true",
                   help="aceita conexões da rede local (iPad, notebook); exige token")
    r.add_argument("--token", default=None,
                   help="fixa o token em vez de sortear um a cada início")
    r.add_argument("--sem-cegamento", action="store_true",
                   help="mostra nome, grupo e dia na interface (só para auditoria)")
    r.add_argument("--sem-aquecer", action="store_true",
                   help="não pré-gera o cache de máscaras ao iniciar")

    c = sub.add_parser("reconstruir", help="refaz o banco a partir do diário e das máscaras")
    _comum(c)

    b = sub.add_parser("validacao", help="Validação Cega com perfis separados")
    _comum(b)
    b.add_argument("--sessao", type=Path, required=True,
                   help="pasta privada que guarda o banco SQLite da sessão")
    b.add_argument("--manifesto", type=Path,
                   help="CSV reservado da seleção existente, quando estiver fora do arquivo padrão")
    b.add_argument("--seed", type=int, default=20261119, help="semente se for necessário sortear")
    b.add_argument("--preparar", action="store_true", help="prepara e encerra sem iniciar o servidor")
    b.add_argument("--porta", type=int, default=PORTA)
    b.add_argument("--rede", action="store_true", help="permite acesso de outros computadores na LAN")
    b.add_argument("--cookie-seguro", action="store_true", help="use quando houver HTTPS na frente")

    return p


# --------------------------------------------------------------------------
def cmd_medir(args) -> None:
    from .pipeline import executar
    executar(config.caminhos(args.dados), limite=args.limite)


def cmd_verificar(args) -> None:
    from .verificacao import executar
    executar(config.caminhos(args.dados))


def cmd_graficos(args) -> None:
    from .graficos import executar
    executar(config.caminhos(args.dados), usar_final=not args.brutas,
             somente_conferidas=args.conferidas)


def cmd_reconstruir(args) -> None:
    from .revisor.contexto import Contexto
    ctx = Contexto(config.caminhos(args.dados)).montar()
    n = ctx.repo.reconstruir(
        ctx.cam.mascaras_revisadas,
        lambda m, chave=None: ctx.medir(m))
    ctx.escrever_csv_final()
    mascaras = len(list(ctx.cam.mascaras_revisadas.glob("*.png")))
    print(f"  {n} revisões reconstruídas ({mascaras} máscaras em disco)")


def cmd_revisar(args) -> None:
    from werkzeug.serving import ThreadedWSGIServer

    from .revisor.projetos import criar_app_projetos
    from .revisor.rede import ips_locais, qr_ascii

    class ServidorProjetos(ThreadedWSGIServer):
        allow_reuse_address = os.name != "nt"

        def server_bind(self):
            if os.name == "nt":
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            super().server_bind()

    cam = config.caminhos(args.dados) if args.dados or os.environ.get(config.VAR_AMBIENTE) else None
    if args.galeria is not None and (cam is None or not args.galeria.is_file()):
        raise SystemExit("Passe uma galeria HTML existente e a pasta do projeto em --dados.")

    senhas = _senhas_validacao()
    validacao = None
    if cam is not None and any(senhas.values()):
        try:
            validacao = _app_validacao(cam, args, senhas)
        except (OSError, ValueError, KeyError) as exc:
            raise SystemExit(str(exc)) from exc

    token = (args.token or secrets.token_urlsafe(6)) if args.rede else None
    app = criar_app_projetos(args.projetos, origem=cam, token=token,
                            cego=not args.sem_cegamento,
                            somente_sinalizadas=args.somente_sinalizadas,
                            aquecer=not args.sem_aquecer, validacao=validacao, galeria=args.galeria)
    host = "0.0.0.0" if args.rede else "127.0.0.1"
    servidor = ServidorProjetos(host, args.porta, app)

    if args.rede:
        local = f"http://127.0.0.1:{servidor.port}/?t={token}"
        print("\n  === ABERTO NA REDE LOCAL ===")
        print("  Quem estiver na rede e tiver o link abaixo pode editar as revisões.")
        for ip in ips_locais():
            url = f"http://{ip}:{servidor.port}/?t={token}"
            print(f"\n  no tablet, abra:  {url}")
            if validacao is not None:
                print(f"  Validação Cega: http://{ip}:{servidor.port}/validacao/")
            qr = qr_ascii(url)
            if qr:
                print("\n" + qr + "\n")
        print(f"  neste computador: {local}")
        print(f"\n  token desta sessão: {token}")
        print("  (--token SEUTOKEN mantém o mesmo link entre reinícios)")
    else:
        local = f"http://127.0.0.1:{servidor.port}/"
        print(f"\n  Spheroid Lab · Projetos: {local}")
        print("  (--rede para acessar do iPad ou de outro aparelho)")

    print("\n  (Ctrl+C aqui encerra o servidor)\n")
    navegador = threading.Timer(0.3, webbrowser.open, args=(local,))
    navegador.daemon = True
    navegador.start()
    servidor.serve_forever()


def _senhas_validacao():
    return {perfil: os.environ.get(f"ESFEROIDES_VALIDACAO_{perfil.upper()}", "")
            for perfil in ("admin", "avaliadora")}


def _app_validacao(cam, args, senhas, manifesto=None, seed=20261119):
    from .revisor.validacao_amostra import preparar_amostra
    from .revisor.validacao_app import criar_app_validacao
    from .revisor.validacao_banco import BancoValidacao

    banco = BancoValidacao(args.sessao.resolve() / "validacao.db")
    return criar_app_validacao(banco, senhas, lambda: preparar_amostra(cam, manifesto, seed),
                              args.cookie_seguro)


def cmd_validacao(args) -> None:
    from .revisor.rede import ips_locais
    from .revisor.validacao_amostra import preparar_amostra
    from .revisor.validacao_banco import BancoValidacao

    cam = config.caminhos(args.dados)
    try:
        if args.preparar:
            banco = BancoValidacao(args.sessao.resolve() / "validacao.db")
            if banco.fila()[0]:
                raise ValueError("A sessão já foi preparada.")
            amostra, registro = preparar_amostra(cam, args.manifesto, args.seed)
            banco.preparar(amostra, registro)
            print(f"48 imagens preparadas ({registro['metodo']}) em {banco.caminho}")
            return
        app = _app_validacao(cam, args, _senhas_validacao(), args.manifesto, args.seed)
    except (OSError, ValueError, KeyError) as exc:
        raise SystemExit(str(exc)) from exc

    host = "0.0.0.0" if args.rede else "127.0.0.1"
    print(f"Validação Cega: http://127.0.0.1:{args.porta}/validacao/")
    if args.rede:
        for ip in ips_locais():
            print(f"  Na rede local: http://{ip}:{args.porta}/validacao/")
    app.run(host=host, port=args.porta, debug=False, threaded=True)


COMANDOS = {"medir": cmd_medir, "verificar": cmd_verificar, "validacao": cmd_validacao,
            "graficos": cmd_graficos, "revisar": cmd_revisar,
            "reconstruir": cmd_reconstruir}


def main(argv: list[str] | None = None) -> int:
    args = construir_parser().parse_args(argv)
    COMANDOS[args.comando](args)
    return 0
