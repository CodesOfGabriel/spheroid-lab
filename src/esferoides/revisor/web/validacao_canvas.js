// O canvas tem sempre os pixels originais. A câmera só transforma a exibição.
export function pontoNaImagem(x, y, retangulo, largura, altura) {
  return [
    (x - retangulo.left) * largura / retangulo.width,
    (y - retangulo.top) * altura / retangulo.height,
  ];
}

const cores = { externa: '#ffe600', interna: '#60dfff' };
const camadas = Object.keys(cores);

function carregarImagem(url) {
  const imagem = new Image();
  imagem.src = url;
  return imagem.decode().then(() => imagem);
}

export class Editor {
  constructor(mudou, atualizou) {
    this.mudou = mudou;
    this.atualizou = atualizou;
    this.stage = document.querySelector('#vc-stage');
    this.wrap = document.querySelector('#vc-wrap');
    this.foto = document.querySelector('#vc-foto');
    this.overlay = document.querySelector('#vc-mascara');
    this.ctx = this.overlay.getContext('2d');
    this.mascaras = Object.fromEntries(camadas.map(c => [
      c, document.createElement('canvas').getContext('2d', { willReadFrequently: true }),
    ]));
    this.camada = 'externa';
    this.ferramenta = 'poligono';
    this.diametro = 26;
    this.opacidade = 0.35;
    this.mover = false;
    this.zoom = 1;
    this.poligono = [];
    this.passado = [];
    this.futuro = [];
    this.stage.addEventListener('pointerdown', event => this.iniciar(event));
    this.stage.addEventListener('pointermove', event => this.arrastar(event));
    this.stage.addEventListener('pointerup', event => this.terminar(event));
    this.stage.addEventListener('pointercancel', event => this.terminar(event, true));
    this.stage.addEventListener('wheel', event => {
      if (this.wrap.hidden) return;
      event.preventDefault();
      const caixa = this.stage.getBoundingClientRect();
      this.ampliar(event.deltaY < 0 ? 1.18 : 1 / 1.18,
        event.clientX - caixa.left, event.clientY - caixa.top);
    }, { passive: false });
    new ResizeObserver(() => {
      if (!this.wrap.hidden && this.enquadrada) this.enquadrar();
    }).observe(this.stage);
  }

  async abrir(fotoUrl, anotacaoUrl) {
    const [foto, ...mascaras] = await Promise.all([
      carregarImagem(fotoUrl),
      ...camadas.map(c => anotacaoUrl ? carregarImagem(anotacaoUrl + '/' + c) : null),
    ]);
    this.w = foto.naturalWidth;
    this.h = foto.naturalHeight;
    const telas = [this.foto, this.overlay, ...camadas.map(c => this.mascaras[c].canvas)];
    for (const tela of telas) {
      tela.width = this.w;
      tela.height = this.h;
    }
    this.foto.getContext('2d').drawImage(foto, 0, 0);
    for (const [i, c] of camadas.entries()) {
      if (!mascaras[i]) continue;
      const ctx = this.mascaras[c];
      ctx.drawImage(mascaras[i], 0, 0);
      const pixels = ctx.getImageData(0, 0, this.w, this.h);
      for (let k = 0; k < pixels.data.length; k += 4) {
        pixels.data[k + 3] = pixels.data[k];
      }
      ctx.putImageData(pixels, 0, 0);
      this.colorir(c);
    }
    this.passado = [];
    this.futuro = [];
    this.poligono = [];
    this.gesto = null;
    this.wrap.hidden = false;
    this.enquadrar();
  }

  colorir(camada) {
    const ctx = this.mascaras[camada];
    ctx.globalCompositeOperation = 'source-in';
    ctx.fillStyle = cores[camada];
    ctx.fillRect(0, 0, this.w, this.h);
    ctx.globalCompositeOperation = 'source-over';
  }

  renderizar() {
    const ctx = this.ctx;
    ctx.clearRect(0, 0, this.w, this.h);
    ctx.globalAlpha = this.opacidade;
    for (const c of camadas) ctx.drawImage(this.mascaras[c].canvas, 0, 0);
    ctx.globalAlpha = 1;
    if (this.poligono.length) {
      ctx.strokeStyle = ctx.fillStyle = cores[this.camada];
      ctx.lineWidth = 2 / this.zoom;
      this.tracar(ctx, this.poligono);
      if (this.cursor) ctx.lineTo(...this.cursor);
      ctx.stroke();
      for (const [x, y] of this.poligono) {
        ctx.beginPath();
        ctx.arc(x, y, 3 / this.zoom, 0, 2 * Math.PI);
        ctx.fill();
      }
    }
    this.atualizou();
  }

  transformar() {
    this.wrap.style.transform = 'translate(' + this.x + 'px,' + this.y + 'px) scale(' + this.zoom + ')';
    this.renderizar();
  }

  enquadrar() {
    if (this.wrap.hidden) return;
    const { width, height } = this.stage.getBoundingClientRect();
    this.zoom = Math.min(1, (width - 20) / this.w, (height - 20) / this.h);
    this.x = (width - this.w * this.zoom) / 2;
    this.y = (height - this.h * this.zoom) / 2;
    this.enquadrada = true;
    this.transformar();
  }

  ampliar(fator, px = this.stage.clientWidth / 2, py = this.stage.clientHeight / 2) {
    if (this.wrap.hidden || this.gesto) return;
    const novo = Math.max(0.1, Math.min(8, this.zoom * fator));
    this.x = px - (px - this.x) * novo / this.zoom;
    this.y = py - (py - this.y) * novo / this.zoom;
    this.zoom = novo;
    this.enquadrada = false;
    this.transformar();
  }

  coordenadas(event) {
    return pontoNaImagem(event.clientX, event.clientY, this.wrap.getBoundingClientRect(), this.w, this.h);
  }

  iniciar(event) {
    if (this.wrap.hidden || this.gesto || !event.isPrimary || ![0, 1].includes(event.button)) return;
    if (this.mover || event.button === 1 || event.altKey) {
      this.gesto = { pan: true, px: event.clientX, py: event.clientY, x: this.x, y: this.y };
    } else {
      if (!this.editavel) return;
      const ponto = this.coordenadas(event);
      if (ponto[0] < 0 || ponto[1] < 0 || ponto[0] >= this.w || ponto[1] >= this.h) return;
      if (this.ferramenta === 'poligono') {
        const primeiro = this.poligono[0];
        if (primeiro && this.poligono.length >= 3
            && Math.hypot(primeiro[0] - ponto[0], primeiro[1] - ponto[1]) * this.zoom < 9) {
          this.fechar();
        } else {
          this.poligono.push(ponto);
          this.renderizar();
        }
        return;
      }
      this.gesto = { antes: this.snapshot(this.camada), ponto };
      this.pincelar(ponto, ponto);
    }
    event.preventDefault();
    this.stage.setPointerCapture(event.pointerId);
  }

  arrastar(event) {
    if (!event.isPrimary || this.wrap.hidden) return;
    const g = this.gesto;
    if (g?.pan) {
      this.x = g.x + event.clientX - g.px;
      this.y = g.y + event.clientY - g.py;
      this.enquadrada = false;
      this.transformar();
    } else if (g) {
      const ponto = this.coordenadas(event);
      this.pincelar(g.ponto, ponto);
      g.ponto = ponto;
    } else if (this.poligono.length) {
      this.cursor = this.coordenadas(event);
      this.renderizar();
    }
  }

  terminar(event, cancelado = false) {
    if (!event.isPrimary || !this.gesto) return;
    const { antes } = this.gesto;
    this.gesto = null;
    if (antes && cancelado) {
      this.restaurar(antes);
      this.renderizar();
    } else if (antes) {
      this.commit(antes);
    }
    this.atualizou();
  }

  pincelar(a, b) {
    const ctx = this.mascaras[this.camada];
    ctx.save();
    ctx.fillStyle = ctx.strokeStyle = cores[this.camada];
    if (this.ferramenta === 'borracha') ctx.globalCompositeOperation = 'destination-out';
    ctx.lineWidth = this.diametro;
    ctx.lineCap = 'round';
    this.tracar(ctx, [a, b]);
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(...b, this.diametro / 2, 0, 2 * Math.PI);
    ctx.fill();
    ctx.restore();
    this.renderizar();
  }

  tracar(ctx, [primeiro, ...resto]) {
    ctx.beginPath();
    ctx.moveTo(...primeiro);
    for (const ponto of resto) ctx.lineTo(...ponto);
  }

  fechar() {
    if (!this.editavel || this.poligono.length < 3) return;
    const antes = this.snapshot(this.camada);
    const ctx = this.mascaras[this.camada];
    ctx.fillStyle = cores[this.camada];
    this.tracar(ctx, this.poligono);
    ctx.closePath();
    ctx.fill('evenodd');
    this.poligono = [];
    this.cursor = null;
    this.commit(antes);
  }

  snapshot(camada) {
    return { camada, pixels: this.mascaras[camada].getImageData(0, 0, this.w, this.h) };
  }

  restaurar({ camada, pixels }) {
    this.mascaras[camada].putImageData(pixels, 0, 0);
  }

  commit(antes) {
    const depois = this.snapshot(antes.camada);
    for (let k = 3; k < depois.pixels.data.length; k += 4) {
      depois.pixels.data[k] = depois.pixels.data[k] >= 128 ? 255 : 0;
    }
    this.restaurar(depois);
    this.passado.push(antes);
    if (this.passado.length > 12) this.passado.shift();
    this.futuro = [];
    this.renderizar();
    this.mudou();
  }

  desfazer() {
    if (!this.editavel) return;
    if (this.poligono.length) {
      this.poligono.pop();
      this.renderizar();
      return;
    }
    this.transitar(this.passado, this.futuro);
  }

  transitar(origem, destino) {
    if (!this.editavel || this.gesto || !origem.length) return;
    const versao = origem.pop();
    destino.push(this.snapshot(versao.camada));
    this.restaurar(versao);
    this.renderizar();
    this.mudou();
  }

  async png(camada) {
    const tela = document.createElement('canvas');
    tela.width = this.w;
    tela.height = this.h;
    const ctx = tela.getContext('2d');
    const pixels = this.snapshot(camada).pixels;
    for (let k = 0; k < pixels.data.length; k += 4) {
      pixels.data[k] = pixels.data[k + 1] = pixels.data[k + 2] = pixels.data[k + 3];
      pixels.data[k + 3] = 255;
    }
    ctx.putImageData(pixels, 0, 0);
    return new Promise((resolve, reject) => tela.toBlob(
      blob => blob ? resolve(blob) : reject(new Error('Não foi possível gerar o PNG.')), 'image/png'));
  }
}
