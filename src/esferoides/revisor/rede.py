"""Acesso pela rede local: descoberta de IP, QR code e token.

Quando o servidor sai do 127.0.0.1, qualquer aparelho da rede alcança a porta.
Passa a valer um token — vai uma vez na URL (`?t=...`) e fica num cookie. Não é
criptografia: é uma tranca simples para o aparelho errado não mexer nas revisões
por engano. Numa rede compartilhada, prefira uma VPN (Tailscale e afins), que
dispensa expor porta.
"""

from __future__ import annotations

import socket
import sys


def ips_locais() -> list[str]:
    achados: list[str] = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))          # não envia nada, só escolhe a rota
        achados.append(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith(("127.", "169.254.")) and ip not in achados:
                achados.append(ip)
    except OSError:
        pass
    return achados


def qr_ascii(url: str) -> str | None:
    """QR em blocos de meia-altura, para apontar a câmera do tablet."""
    try:
        import qrcode
    except ImportError:
        return None
    try:                       # o console do Windows costuma vir em cp1252
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        return None            # sem UTF-8 o QR sairia como lixo; melhor omitir

    q = qrcode.QRCode(border=1)
    q.add_data(url)
    q.make(fit=True)
    m = q.get_matrix()
    linhas = []
    for y in range(0, len(m), 2):
        linha = ""
        for x in range(len(m[0])):
            cima = m[y][x]
            baixo = m[y + 1][x] if y + 1 < len(m) else False
            linha += "█" if cima and baixo else "▀" if cima else "▄" if baixo else " "
        linhas.append("  " + linha)
    return "\n".join(linhas)
