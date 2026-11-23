const $ = s => document.querySelector(s);
const photo = $('#photo'), over = $('#over');
const pctx = photo.getContext('2d');
const octx = over.getContext('2d', {willReadFrequently:true});

// mascara viva: amarelo opaco onde selecionado, transparente no resto
const mask = document.createElement('canvas');
const mctx = mask.getContext('2d', {willReadFrequently:true});
const AMARELO = '#ffe600';

let itens = [], idx = -1, W = 0, H = 0;
let ferramenta = 'pincel', modo = 'add', raio = 23;
let zoom = 1, panX = 0, panY = 0, espaco = false, arrastando = false;
let pintando = false, ultimo = null, undoPilha = [], preSnap = null, bbox = null;
let laco = [], editado = false;

/* ------------------------------------------------ lista lateral */
/* ---------------------------------------------------------------------
   Cegamento: por padrão o servidor só manda um código anônimo ("#001") e a
   fila vem embaralhada, para que quem revisa não saiba experimento, grupo
   nem dia — e não desenhe o contorno que "deveria" dar. Rodando com
   --sem-cegamento os campos voltam e a interface volta a mostrá-los.
   --------------------------------------------------------------------- */
let cego = true;
const rotulo = it => cego ? it.codigo : (it.codigo + '  ' + it.rotulo);
const legendaItem = it => cego
  ? (it.sinalizada ? 'sinalizada para conferência' : 'amostragem')
  : (it.motivo || 'sem alerta');

async function carregarLista(){
  itens = await (await fetch('api/lista')).json();
  cego = !('rotulo' in (itens[0] || {}));
  if (!cego) document.body.classList.add('semCegamento');
  $('#filtro').placeholder = cego ? 'filtrar (ex.: 042, pendente, manual)'
                                  : 'filtrar (ex.: n1 LC, D0, pendente)';
  desenharLista();
  if (itens.length && idx < 0) abrir(0);
}
function desenharLista(){
  const q = $('#filtro').value.toLowerCase().trim();
  const el = $('#lista'); el.innerHTML = '';
  itens.forEach((it, i) => {
    const alvo = (rotulo(it) + ' ' + legendaItem(it) + ' ' + it.status).toLowerCase();
    if (q && !q.split(/\s+/).every(t => alvo.includes(t))) return;
    const d = document.createElement('div');
    d.className = 'item' + (i === idx ? ' on' : '');
    d.innerHTML = `<i class="dot ${it.status}"></i><div>
        <b>${rotulo(it)}</b><span>${legendaItem(it)}</span></div>`;
    d.onclick = () => abrir(i);
    el.appendChild(d);
  });
  const feito = itens.filter(x => x.status !== 'pendente').length;
  $('#prog').textContent = `${feito} de ${itens.length} revisadas`;
  $('#barra').style.width = (100 * feito / Math.max(itens.length,1)) + '%';
}
$('#filtro').oninput = desenharLista;

/* ------------------------------------------------ mascara -> canvas */
// Um PNG de mascara (0 ou 255) vira o amarelo opaco do canvas de trabalho.
// Estava copiado em quatro lugares (abrir, automatico, aplicar, limiar).
async function carregarMascara(src){
  const im = new Image(); im.src = src; await im.decode();
  const t = document.createElement('canvas'); t.width = W; t.height = H;
  const tc = t.getContext('2d', {willReadFrequently:true});
  tc.drawImage(im, 0, 0);
  const d = tc.getImageData(0, 0, W, H), p = d.data;
  for (let k = 0; k < p.length; k += 4){
    if (p[k] > 127){ p[k]=255; p[k+1]=230; p[k+2]=0; p[k+3]=255; }
    else p[k+3] = 0;
  }
  mctx.putImageData(d, 0, 0);
}

/* ------------------------------------------------ abrir imagem */
async function carregarDesvio(i){
  $('#bMagico').disabled = true; $('#bMapa').disabled = true;
  try{
    // fetch em vez de Image.src para poder ler o cabecalho X-Otsu
    const resp = await fetch('api/desvio/' + i
                             + (sigmaPadrao() ? '' : '?sigma=' + sigmaAtual()));
    limiarOtsu = +resp.headers.get('X-Otsu') || 128;
    const im = new Image();
    im.src = URL.createObjectURL(await resp.blob());
    await im.decode();
    if (i !== idx) return;                       // navegou antes de terminar
    const t = document.createElement('canvas'); t.width = W; t.height = H;
    const tc = t.getContext('2d', {willReadFrequently:true});
    tc.drawImage(im, 0, 0);
    const d = tc.getImageData(0, 0, W, H).data;
    const m = new Uint8Array(W*H);
    for (let j = 0, k = 0; j < m.length; j++, k += 4) m[j] = d[k];
    if (i !== idx) return;
    mapaDesvio = m;
    $('#bMagico').disabled = false; $('#bMapa').disabled = false;
    pintarFundo();                 // se a vista do mapa estiver ligada, redesenha
  }catch(e){ /* sem o mapa o pincel magico e a vista ficam indisponiveis */ }
}

async function abrir(i){
  if (i < 0 || i >= itens.length) return;
  idx = i; editado = false; undoPilha = []; laco = []; mapaDesvio = null;
  zerarSegmentacao();            // nenhum ajuste vaza para a proxima imagem
  const it = itens[i];
  $('#motivo').textContent = cego ? (it.sinalizada ? '⚠ sinalizada' : '')
                                  : (it.motivo ? '⚠ ' + it.motivo : '');
  $('#titulo').textContent = rotulo(it);
  $('#status').textContent = 'carregando…';

  const img = new Image();
  img.src = 'api/foto/' + i + '?t=' + Date.now();
  await img.decode();
  W = img.naturalWidth; H = img.naturalHeight;
  for (const c of [photo, over, mask]) { c.width = W; c.height = H; }
  $('#wrap').style.width = W + 'px'; $('#wrap').style.height = H + 'px';
  fotoAtual = img; pctx.drawImage(img, 0, 0);
  aplicarFiltroFoto();

  await carregarMascara('api/mascara/' + i + '?t=' + Date.now());

  enquadrar(); render(); desenharLista(); atualizarHud(it.medidas);
  $('#status').textContent = it.status === 'pendente' ? 'pendente' : 'já revisada: ' + it.status;
  carregarDesvio(i);                             // em segundo plano, libera o ✨
}

/* ------------------------------------------------ render */
let contornoPendente = false;
function render(contorno){
  octx.clearRect(0, 0, W, H);
  octx.globalAlpha = 0.30;
  octx.drawImage(mask, 0, 0);
  octx.globalAlpha = 1;
  if (contorno) desenharContorno();
  if (laco.length){
    octx.save();
    octx.strokeStyle = AMARELO; octx.lineWidth = 2/zoom; octx.setLineDash([7/zoom, 5/zoom]);
    octx.beginPath(); octx.moveTo(laco[0][0], laco[0][1]);
    laco.slice(1).forEach(p => octx.lineTo(p[0], p[1]));
    octx.stroke(); octx.restore();
    octx.fillStyle = AMARELO;
    laco.forEach(p => { octx.beginPath(); octx.arc(p[0], p[1], 4/zoom, 0, 7); octx.fill(); });
  }
}
// contorno nitido: detecta borda da mascara (roda so quando a pincelada termina)
function desenharContorno(){
  const d = mctx.getImageData(0, 0, W, H).data;
  const out = octx.createImageData(W, H), o = out.data;
  const A = (x, y) => (x < 0 || y < 0 || x >= W || y >= H) ? 0 : d[(y*W + x)*4 + 3];
  for (let y = 0; y < H; y++) for (let x = 0; x < W; x++){
    const i = (y*W + x)*4;
    if (d[i+3] > 127 && (A(x-1,y) <= 127 || A(x+1,y) <= 127 ||
                         A(x,y-1) <= 127 || A(x,y+1) <= 127)){
      o[i]=255; o[i+1]=230; o[i+2]=0; o[i+3]=255;
    }
  }
  const t = document.createElement('canvas'); t.width = W; t.height = H;
  t.getContext('2d').putImageData(out, 0, 0);
  // engrossa para continuar visivel com a imagem reduzida — teto de 2 px,
  // acima disso o custo das copias domina e trava o zoom
  const e = Math.min(2, Math.max(1, Math.round(1.4/zoom)));
  for (let dx = -e; dx <= e; dx++) for (let dy = -e; dy <= e; dy++)
    octx.drawImage(t, dx, dy);
}
function agendarContorno(){
  if (contornoPendente) return;
  contornoPendente = true;
  requestAnimationFrame(() => { contornoPendente = false; render(true); });
}

function aplicarTransform(){
  $('#wrap').style.transform = `translate(${panX}px,${panY}px) scale(${zoom})`;
  atualizarCursor();
}
function enquadrar(){
  const st = $('#stage').getBoundingClientRect();
  zoom = Math.min((st.width - 40)/W, (st.height - 40)/H);
  panX = (st.width - W*zoom)/2; panY = (st.height - H*zoom)/2;
  aplicarTransform(); agendarContorno();
}

/* ------------------------------------------------ pintura */
function paraImagem(ev){
  const r = $('#wrap').getBoundingClientRect();
  return [(ev.clientX - r.left)/zoom, (ev.clientY - r.top)/zoom];
}
function marcaBox(x, y, r){
  const b = [x-r, y-r, x+r, y+r];
  bbox = bbox ? [Math.min(bbox[0],b[0]), Math.min(bbox[1],b[1]),
                 Math.max(bbox[2],b[2]), Math.max(bbox[3],b[3])] : b;
}
/* =====================================================================
   PINCEL MÁGICO
   Dentro do disco do pincel, separa "objeto" de "fundo" pelo mesmo mapa
   |flat−1| que a segmentação automática usa, só que com Otsu LOCAL. Se as
   duas classes se separam bem (o pincel está em cima de uma borda), pinta
   só o lado do objeto — a seleção "gruda" no contorno. Se a janela é
   homogênea (pincel fundo dentro do esferoide, ou fundo dentro do poço),
   não há borda para grudar e ele age como pincel comum.
   ===================================================================== */
let mapaDesvio = null;                 // Uint8Array W*H, ou null se não carregou
let limiarOtsu = 128;                  // Otsu global da imagem, vindo do servidor
let magico = false, sensib = 0;        // sensib desloca o limiar (−60..+60)
const FRAC_MIN = 0.03;                 // abaixo disto o dab "não pegou nada"
let rascunho = null, rascunhoR = -1;

function dabMagico(cx, cy, r, apagar){
  cx = Math.round(cx); cy = Math.round(cy);
  const x0 = Math.max(0, cx - r), x1 = Math.min(W - 1, cx + r);
  const y0 = Math.max(0, cy - r), y1 = Math.min(H - 1, cy + r);
  if (x1 < x0 || y1 < y0) return false;
  const r2 = r * r;
  const t = Math.max(1, Math.min(254, limiarOtsu - sensib));

  // conta antes de pintar: se o disco quase não tem pixel do lado procurado,
  // não há borda aqui para grudar e vale mais o pincel comum
  let nDisco = 0, nAlvo = 0;
  for (let y = y0; y <= y1; y++){
    const dy = y - cy;
    for (let x = x0; x <= x1; x++){
      const dx = x - cx;
      if (dx*dx + dy*dy > r2) continue;
      nDisco++;
      const v = mapaDesvio[y*W + x];
      if (apagar ? (v <= t) : (v > t)) nAlvo++;
    }
  }
  if (nDisco < 12 || nAlvo / nDisco < FRAC_MIN) return false;

  const w = x1 - x0 + 1, h = y1 - y0 + 1;
  if (!rascunho || rascunhoR !== r){
    rascunho = document.createElement('canvas'); rascunhoR = r;
  }
  rascunho.width = w; rascunho.height = h;
  const rc = rascunho.getContext('2d');
  const im = rc.createImageData(w, h), p = im.data;
  for (let y = y0; y <= y1; y++){
    const dy = y - cy;
    for (let x = x0; x <= x1; x++){
      const dx = x - cx;
      if (dx*dx + dy*dy > r2) continue;
      const v = mapaDesvio[y*W + x];
      // adicionar: só o lado do objeto. apagar: só o lado do fundo.
      if (apagar ? (v <= t) : (v > t)){
        const k = ((y - y0)*w + (x - x0))*4;
        p[k] = 255; p[k+1] = 230; p[k+2] = 0; p[k+3] = 255;
      }
    }
  }
  rc.putImageData(im, 0, 0);
  mctx.save();
  mctx.globalCompositeOperation = apagar ? 'destination-out' : 'source-over';
  mctx.drawImage(rascunho, x0, y0);
  mctx.restore();
  marcaBox(cx, cy, r + 2);
  editado = true;
  return true;
}

function pincel(x0, y0, x1, y1, apagar, ev){
  // pressao da caneta modula a espessura (35%..100%) quando ligada
  let r = raio;
  if (usarPressao && ev && ev.pointerType === 'pen' && ev.pressure > 0)
    r = Math.max(1.5, raio * (0.35 + 0.65 * ev.pressure));

  if (magico && mapaDesvio){
    // percorre o segmento em passos de r/2 e tenta grudar em cada posição;
    // onde não houver borda, cai no traço comum daquele trecho
    const d = Math.hypot(x1 - x0, y1 - y0);
    const passos = Math.max(1, Math.ceil(d / Math.max(2, r/2)));
    let algum = false;
    for (let k = 1; k <= passos; k++){
      const t = k/passos;
      algum = dabMagico(x0 + (x1-x0)*t, y0 + (y1-y0)*t, Math.round(r), apagar) || algum;
    }
    if (algum) return;
  }

  mctx.save();
  mctx.globalCompositeOperation = apagar ? 'destination-out' : 'source-over';
  mctx.strokeStyle = AMARELO; mctx.fillStyle = AMARELO;
  mctx.lineWidth = r*2; mctx.lineCap = 'round'; mctx.lineJoin = 'round';
  mctx.beginPath(); mctx.moveTo(x0, y0); mctx.lineTo(x1, y1); mctx.stroke();
  mctx.beginPath(); mctx.arc(x1, y1, r, 0, 7); mctx.fill();
  mctx.restore();
  marcaBox(x0, y0, r + 2); marcaBox(x1, y1, r + 2);
  editado = true;
}
function preencherLaco(apagar){
  if (laco.length < 3) { laco = []; render(true); return; }
  snapshotInicio();
  mctx.save();
  mctx.globalCompositeOperation = apagar ? 'destination-out' : 'source-over';
  mctx.fillStyle = AMARELO;
  mctx.beginPath(); mctx.moveTo(laco[0][0], laco[0][1]);
  laco.slice(1).forEach(p => mctx.lineTo(p[0], p[1]));
  mctx.closePath(); mctx.fill();
  mctx.restore();
  laco.forEach(p => marcaBox(p[0], p[1], 2));
  editado = true; laco = []; fecharSnapshot(); render(true); medirNoServidor();
}
function snapshotInicio(){ preSnap = mctx.getImageData(0, 0, W, H); bbox = null; }
function fecharSnapshot(){
  if (!preSnap || !bbox) { preSnap = null; return; }
  let [x0,y0,x1,y1] = bbox.map(Math.round);
  x0 = Math.max(0,x0); y0 = Math.max(0,y0);
  x1 = Math.min(W,x1); y1 = Math.min(H,y1);
  const w = x1-x0, h = y1-y0;
  if (w > 0 && h > 0){
    const t = document.createElement('canvas'); t.width = W; t.height = H;
    t.getContext('2d').putImageData(preSnap, 0, 0);
    undoPilha.push({x:x0, y:y0, d:t.getContext('2d').getImageData(x0, y0, w, h)});
    if (undoPilha.length > 40) undoPilha.shift();
  }
  preSnap = null; bbox = null;
}
function desfazer(){
  const u = undoPilha.pop(); if (!u) return;
  mctx.clearRect(u.x, u.y, u.d.width, u.d.height);
  mctx.putImageData(u.d, u.x, u.y);
  render(true); medirNoServidor();
}

/* ---------------------------------------------------------------------
   Ponteiros. No iPad convivem dois tipos: a caneta desenha e o dedo
   navega. Assim que uma Apple Pencil e detectada, o dedo passa
   automaticamente para "mover" — e o que resolve a rejeicao de palma,
   porque a mao apoiada na tela chega como pointerType 'touch' e deixa de
   pintar. Em tela sem caneta o dedo desenha. O botao 👆 permite forcar.
   --------------------------------------------------------------------- */
const stage = $('#stage');
const pontos = new Map();          // ponteiros de toque ativos
let temCaneta = false, dedoDesenha = true, dedoManual = false;
let usarPressao = false, gesto = null, idPintando = null;

function atualizarBotaoDedo(){
  $('#bDedo').textContent = '👆 dedo: ' + (dedoDesenha ? 'desenhar' : 'mover');
  $('#bDedo').classList.toggle('on', dedoDesenha);
}
function detectarCaneta(ev){
  if (ev.pointerType === 'pen' && !temCaneta){
    temCaneta = true;
    if (!dedoManual){ dedoDesenha = false; atualizarBotaoDedo(); }
    $('#status').textContent = 'caneta detectada — dedo passou a mover a imagem';
  }
}
const desenhaCom = ev => ev.pointerType === 'pen' ? true
                       : ev.pointerType === 'touch' ? dedoDesenha : true;

stage.addEventListener('contextmenu', e => e.preventDefault());

stage.addEventListener('pointerdown', ev => {
  // controles sobrepostos ao stage (botão do painel de métricas, etc.): sem isto
  // o pointerdown borbulha até aqui, o stage captura o ponteiro, o `click` do
  // botão nunca dispara — e ainda começa uma pincelada por baixo do painel
  if (ev.target.closest('[data-ui]')) return;
  if (idx < 0) return;
  detectarCaneta(ev);
  if (ev.pointerType === 'touch'){
    pontos.set(ev.pointerId, [ev.clientX, ev.clientY]);
    // dois dedos = zoom/mover; se um traco tinha comecado, desfaz o toque solto
    if (pontos.size === 2){
      if (pintando){ pintando = false; idPintando = null; fecharSnapshot(); desfazer(); }
      const p = [...pontos.values()];
      gesto = {d: dist(p[0], p[1]), m: meio(p[0], p[1]), zoom, panX, panY};
      return;
    }
    if (pontos.size > 2) return;
  }
  if (espaco || ev.button === 1 || !desenhaCom(ev)){
    arrastando = [ev.clientX - panX, ev.clientY - panY];
    stage.classList.add('drag'); stage.setPointerCapture(ev.pointerId); return;
  }
  const [x, y] = paraImagem(ev);
  if (ferramenta === 'laco'){
    if (ev.button === 2) preencherLaco(true); else { laco.push([x, y]); render(true); }
    return;
  }
  pintando = true; idPintando = ev.pointerId; snapshotInicio();
  const apagar = (modo === 'del') !== (ev.altKey || ev.button === 2);
  pincel(x, y, x, y, apagar, ev); ultimo = [x, y];
  stage.setPointerCapture(ev.pointerId); render();
});

stage.addEventListener('pointermove', ev => {
  if (!pintando && !gesto && !arrastando && ev.target.closest('[data-ui]')) return;
  if (ev.pointerType === 'touch' && pontos.has(ev.pointerId))
    pontos.set(ev.pointerId, [ev.clientX, ev.clientY]);
  if (gesto && pontos.size >= 2){                       // pinca: zoom + arrasto
    const p = [...pontos.values()];
    const d = dist(p[0], p[1]), m = meio(p[0], p[1]);
    const z = Math.min(8, Math.max(0.08, gesto.zoom * (d / gesto.d)));
    const r = stage.getBoundingClientRect();
    const ix = (gesto.m[0] - r.left - gesto.panX) / gesto.zoom;
    const iy = (gesto.m[1] - r.top  - gesto.panY) / gesto.zoom;
    zoom = z;
    panX = (m[0] - r.left) - ix * z;
    panY = (m[1] - r.top)  - iy * z;
    aplicarTransform();
    return;
  }
  if (arrastando){ panX = ev.clientX - arrastando[0]; panY = ev.clientY - arrastando[1];
    aplicarTransform(); return; }
  if (!pintando || ev.pointerId !== idPintando) return;
  // getCoalescedEvents recupera as amostras que o navegador agrupou num so
  // evento — sem isso um traco rapido de caneta vira uma reta entre dois pontos
  const amostras = ev.getCoalescedEvents ? ev.getCoalescedEvents() : [ev];
  const apagar = (modo === 'del') !== (ev.altKey || (ev.buttons & 2) !== 0);
  for (const a of (amostras.length ? amostras : [ev])){
    const [x, y] = paraImagem(a);
    pincel(ultimo[0], ultimo[1], x, y, apagar, a); ultimo = [x, y];
  }
  render(); agendarPrevia();
});

function encerrar(ev){
  if (ev && ev.pointerType === 'touch') pontos.delete(ev.pointerId);
  if (pontos.size < 2 && gesto){ gesto = null; agendarContorno(); }
  if (arrastando){ arrastando = false; stage.classList.remove('drag'); }
  if (pintando && (!ev || ev.pointerId === idPintando)){
    pintando = false; idPintando = null;
    fecharSnapshot(); render(true); medirNoServidor();
  }
}
addEventListener('pointerup', encerrar);
addEventListener('pointercancel', encerrar);

const dist = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1]);
const meio = (a, b) => [(a[0] + b[0])/2, (a[1] + b[1])/2];

/* ---- circulo do pincel acompanhando o ponteiro ---- */
let cursorXY = null;
function atualizarCursor(ev){
  const c = $('#cursor');
  if (ev) cursorXY = [ev.clientX, ev.clientY];
  if (!cursorXY || ferramenta === 'laco' || idx < 0){ c.style.display = 'none'; return; }
  const r = stage.getBoundingClientRect();
  const lado = raio * 2 * zoom;
  c.style.display = lado > 3 ? 'block' : 'none';
  c.style.left = (cursorXY[0] - r.left) + 'px';
  c.style.top  = (cursorXY[1] - r.top)  + 'px';
  c.style.width = c.style.height = lado + 'px';
  c.classList.toggle('apagar', modo === 'del');
  c.classList.toggle('magico', magico && !!mapaDesvio);
}
stage.addEventListener('pointermove', ev => {
  if (ev.pointerType !== 'touch' || dedoDesenha) atualizarCursor(ev);
});
stage.addEventListener('pointerleave', () => { cursorXY = null; atualizarCursor(); });

// previa ao vivo: no toque o scan de 1,4 milhao de pixels e mais caro, entao
// limita a uma a cada 120 ms em vez de uma por quadro
let previaPendente = false, ultimaPrevia = 0;
function agendarPrevia(){
  if (previaPendente) return;
  const agora = performance.now();
  const espera = Math.max(0, 120 - (agora - ultimaPrevia));
  previaPendente = true;
  setTimeout(() => {
    previaPendente = false; ultimaPrevia = performance.now();
    atualizarHud(previaLocal(), true);
  }, espera);
}
stage.addEventListener('wheel', ev => {
  if (ev.target.closest('[data-ui]')) return;   // roda sobre o card nao da zoom
  ev.preventDefault();
  const r = $('#wrap').getBoundingClientRect();
  const ix = (ev.clientX - r.left)/zoom, iy = (ev.clientY - r.top)/zoom;
  const z = Math.min(8, Math.max(0.08, zoom * (ev.deltaY < 0 ? 1.15 : 1/1.15)));
  panX -= (ix*z - ix*zoom); panY -= (iy*z - iy*zoom); zoom = z;
  aplicarTransform(); agendarContorno();
}, {passive:false});

/* ------------------------------------------------ acoes */
async function enviar(acao){
  if (idx < 0) return;
  $('#status').textContent = 'salvando…';
  const corpo = {acao};
  if (acao === 'manual') corpo.mascara = exportar();
  // o deslocamento de limiar fica gravado: sem isso nao da para, depois, checar
  // se os contornos ajustados a mao diferem sistematicamente dos demais
  const nota = notaDosAjustes();
  if (nota) corpo.nota = nota;
  const r = await (await fetch('api/salvar/' + idx, {method:'POST',
    headers:{'Content-Type':'application/json'}, body: JSON.stringify(corpo)})).json();
  itens[idx].status = r.status; itens[idx].medidas = r.medidas;
  desenharLista(); atualizarHud(r.medidas);
  $('#status').textContent = 'salvo: ' + r.status;
  proximaPendente();
}
function exportar(){
  const t = document.createElement('canvas'); t.width = W; t.height = H;
  const c = t.getContext('2d');
  c.fillStyle = '#000'; c.fillRect(0, 0, W, H);
  c.drawImage(mask, 0, 0);
  return t.toDataURL('image/png');
}
function proximaPendente(){
  for (let k = idx + 1; k < itens.length; k++)
    if (itens[k].status === 'pendente') return abrir(k);
  if (idx + 1 < itens.length) abrir(idx + 1);
}
/* ---------- painel de medidas ao vivo ---------------------------------- */
const num = v => v == null || Number.isNaN(+v) ? '—'
                 : Math.round(+v).toLocaleString('pt-BR');
const dec = (v, n=2) => v == null || Number.isNaN(+v) ? '—' : (+v).toFixed(n);

/* O painel fica COLAPSADO por padrão: expandido ele cobre um pedaço grande da
   imagem justamente no canto onde se costuma corrigir borda. Colapsado mostra só
   a área. O botão de expandir é o único elemento clicável — o resto do painel
   segue com pointer-events:none para nunca engolir uma pincelada. */
let hudMin = true, ultimaMedida = null, ultimaEhPrevia = false;
try { hudMin = localStorage.getItem('hudMin') !== '0'; } catch (e) { /* sem storage */ }

function alternarHud(){
  hudMin = !hudMin;
  try { localStorage.setItem('hudMin', hudMin ? '1' : '0'); } catch (e) { /* ignora */ }
  atualizarHud(ultimaMedida, ultimaEhPrevia);
}

function atualizarHud(m, previa){
  const it = itens[idx] || {};
  const a = it.auto || {};
  ultimaMedida = m; ultimaEhPrevia = !!previa;
  const hud = $('#hud');
  hud.classList.toggle('min', hudMin);
  const botao = `<button class="alt" data-ui type="button" title="${
    hudMin ? 'Mostrar todas as métricas (H)' : 'Recolher (H)'}">${hudMin ? '▸' : '▾'}</button>`;

  if (!m){ hud.innerHTML = botao + '<span class="compacto">sem medida</span>'; return; }

  if (hudMin){
    hud.innerHTML = botao + `<span class="compacto">${num(m.area_px)}<em> px</em></span>`
      + (previa ? '<span class="pt">prévia</span>' : '');
    return;
  }
  // sob cegamento nao ha coluna de limiar: os limiares variam por dia e
  // mostra-los entregaria de que dia e a imagem
  const lim = (v, l) => (!cego && v != null && l != null && v < l);
  const delta = (v, ref) => (v == null || ref == null || Number.isNaN(+ref)) ? ''
        : (Math.abs(v - ref) < Math.max(1, 0.005*Math.abs(ref)) ? '=' :
           (v > ref ? '▲ ' : '▼ ') + Math.round(100*(v - ref)/Math.abs(ref)) + '%');
  const col3 = (l) => cego ? '' : (l == null ? '' : 'lim ' + dec(l));
  hud.innerHTML = botao + `
    <span class="tag ${previa ? 'previa' : 'medido'}">${previa ? 'prévia · pincel ativo' : 'medido'}</span>
    <table>
      <tr><td>área</td><td>${num(m.area_px)} px</td><td>${delta(m.area_px, a.area_px)}</td></tr>
      <tr><td>d<sub>eq</sub></td><td>${num(m.diam_equiv_px)} px</td><td>${delta(m.diam_equiv_px, a.diam_equiv_px)}</td></tr>
      <tr><td>circularidade</td><td class="${lim(m.circularidade, it.lim_circ) ? 'alerta' : ''}">${dec(m.circularidade)}</td><td>${col3(it.lim_circ)}</td></tr>
      <tr><td>solidity</td><td class="${lim(m.solidity, it.lim_sol) ? 'alerta' : ''}">${dec(m.solidity)}</td><td>${col3(it.lim_sol)}</td></tr>
      <tr><td>feret máx / eixo menor</td><td>${num(m.feret_max_px)} / ${num(m.eixo_menor_px)}</td><td></td></tr>
      <tr><td>toca a borda</td><td>${m.toca_borda ? 'sim' : 'não'}</td><td></td></tr>
    </table>
    <div class="dica"><b>Regra: meça só o maior corpo contíguo.</b> Grumos e células
      soltas em volta NÃO entram no contorno, mesmo que pareçam parte do agregado.
      Um satélite com 4% da área derruba a solidity em ~40%.
      <br><br>Contorno frouxo e irregular pode ser legítimo. Só corrija se estiver de
      fato errado: crescente, anel aberto, pegando a parede do poço, ou um objeto que
      não é o agregado.</div>`;
}

/* prévia instantânea enquanto o pincel está ativo: área e solidity saem exatas
   do proprio canvas; circularidade depende do perimetro suavizado e so vem do
   servidor, para nao mostrar um numero que nao bate com o final. */
function previaLocal(){
  const d = mctx.getImageData(0, 0, W, H).data;
  let area = 0; const pts = [];
  for (let y = 0; y < H; y++){
    let x0 = -1, x1 = -1;
    for (let x = 0; x < W; x++){
      if (d[(y*W + x)*4 + 3] > 127){ area++; if (x0 < 0) x0 = x; x1 = x; }
    }
    if (x0 >= 0){ pts.push([x0, y]); pts.push([x1, y]); }
  }
  if (!area) return null;
  const h = envoltoria(pts);
  return {area_px: area, diam_equiv_px: 2*Math.sqrt(area/Math.PI),
          circularidade: null, solidity: h > 0 ? area/h : null,
          feret_max_px: null, eixo_menor_px: null, toca_borda: null};
}
// cadeia monotona de Andrew — o casco dos extremos de cada linha e o casco do conjunto
function envoltoria(p){
  if (p.length < 3) return 0;
  p = p.slice().sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  const cruz = (o, a, b) => (a[0]-o[0])*(b[1]-o[1]) - (a[1]-o[1])*(b[0]-o[0]);
  const meia = arr => { const h = [];
    for (const q of arr){ while (h.length >= 2 && cruz(h[h.length-2], h[h.length-1], q) <= 0) h.pop(); h.push(q); }
    h.pop(); return h; };
  const hull = meia(p).concat(meia(p.slice().reverse()));
  let s = 0;
  for (let i = 0; i < hull.length; i++){
    const a = hull[i], b = hull[(i+1) % hull.length];
    s += a[0]*b[1] - b[0]*a[1];
  }
  return Math.abs(s)/2;
}

let temporizadorMedida = null;
function medirNoServidor(){
  clearTimeout(temporizadorMedida);
  temporizadorMedida = setTimeout(async () => {
    const meu = idx;
    try{
      const r = await (await fetch('api/medir/' + meu, {method:'POST',
        headers:{'Content-Type':'application/json'},
        body: JSON.stringify({mascara: exportar()})})).json();
      if (meu === idx) atualizarHud(r.medidas, false);
    }catch(e){ /* navegou para outra imagem no meio — ignora */ }
  }, 260);
}

$('#bOk').onclick = () => enviar(editado ? 'manual' : 'ok');
$('#bSalvar').onclick = () => enviar('manual');
$('#bExcluir').onclick = () => {
  const el = $('#aviso'); el.style.display = 'block';
  el.textContent = 'Excluída por qualidade de imagem — registrada no CSV.';
  setTimeout(() => el.style.display = 'none', 1800);
  enviar('excluido');
};
$('#bPrev').onclick = () => abrir(idx - 1);
$('#bNext').onclick = () => abrir(idx + 1);
$('#bUndo').onclick = desfazer;
$('#bFit').onclick = enquadrar;
$('#bLimpar').onclick = () => { snapshotInicio(); marcaBox(W/2, H/2, Math.max(W,H));
  mctx.clearRect(0,0,W,H); editado = true; fecharSnapshot(); render(true);
  atualizarHud(null); };
$('#bAuto').onclick = async () => {
  const r = await fetch('api/reverter/' + idx, {method:'POST'});
  await carregarMascara(URL.createObjectURL(await r.blob()));
  itens[idx].status = 'pendente'; editado = false; undoPilha = [];
  zerarSegmentacao();
  desenharLista(); render(true); medirNoServidor();
  $('#status').textContent = 'revertida ao automático';
};
$('#bAplicar').onclick = async () => {
  $('#status').textContent = 'processando…';
  const r = await (await fetch('api/aplicar/' + idx, {method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({mascara: exportar()})})).json();
  capturarDesfazerIntegral();
  await carregarMascara(r.mascara);
  render(true); atualizarHud(r.medidas);
  editado = true; $('#status').textContent = 'pós-processamento aplicado';
};

function ferr(f){ ferramenta = f; laco = [];
  $('#tPincel').classList.toggle('on', f === 'pincel');
  $('#tLaco').classList.toggle('on', f === 'laco'); render(true); atualizarCursor(); }
function mod(m){ modo = m;
  $('#mAdd').classList.toggle('on', m === 'add');
  $('#mDel').classList.toggle('on', m === 'del'); atualizarCursor(); }
$('#tPincel').onclick = () => ferr('pincel');
$('#tLaco').onclick = () => ferr('laco');
$('#mAdd').onclick = () => mod('add');
$('#mDel').onclick = () => mod('del');
$('#tam').oninput = e => { raio = +e.target.value/2; $('#tamV').textContent = e.target.value;
  atualizarCursor(); };

$('#bMagico').onclick = () => {
  magico = !magico;
  $('#bMagico').classList.toggle('on', magico);
  $('#wSensib').style.display = magico ? '' : 'none';
  $('#status').textContent = magico
    ? 'pincel mágico ligado — a seleção gruda na borda de maior contraste'
    : 'pincel mágico desligado';
  atualizarCursor();
};
$('#sensib').oninput = e => { sensib = +e.target.value;
  $('#sensibV').textContent = (sensib > 0 ? '+' : '') + sensib; };
/* =====================================================================
   AJUSTE RÁPIDO
   ---------------------------------------------------------------------
   Exposição e contraste controlam a imagem exibida.
   Limiar e escala do fundo controlam a proposta de contorno e ficam
   registrados na nota ao salvar.
   ===================================================================== */
const SIGMAS = [30, 45, 60, 90, 120, 180];   // espelha segmentacao.SIGMAS_FUNDO
const I_SIGMA_PADRAO = 2;                    // 60, o do protocolo

let expo = 0, contr = 0, limOff = 0, iSigma = I_SIGMA_PADRAO;
let verMapa = false, fotoAtual = null;
try {
  expo = +localStorage.getItem('ajExpo') || 0;
  contr = +localStorage.getItem('ajContr') || 0;
} catch (e) { /* sem storage: começa neutro */ }

const sinalV = v => (v > 0 ? '+' : '') + v;
const sigmaAtual = () => SIGMAS[iSigma];
const sigmaPadrao = () => iSigma === I_SIGMA_PADRAO;

/* exposição em paradas de diafragma (±2), que é como o olho lê "mais claro";
   uma escala linear amontoa tudo que interessa no primeiro terço do curso */
function aplicarFiltroFoto(){
  photo.style.filter = (expo || contr)
    ? `brightness(${Math.pow(2, expo/50).toFixed(3)}) contrast(${Math.max(0.1, 1 + contr/100).toFixed(3)})`
    : '';
}

function sincronizarAjustes(){
  for (const [ctrl, saida, v] of [['#aExpo', '#aExpoV', expo],
                                  ['#aContr', '#aContrV', contr],
                                  ['#aLim', '#aLimV', limOff]]){
    $(ctrl).value = v;
    $(saida).textContent = sinalV(v);
    $(ctrl).closest('.lin').classList.toggle('mexida', v !== 0);
  }
  $('#aSigma').value = iSigma;
  $('#aSigmaV').textContent = sigmaAtual();
  $('#aSigma').closest('.lin').classList.toggle('mexida', !sigmaPadrao());
  $('#bAjustes').textContent =
    (limOff || !sigmaPadrao()) ? '🎚 Ajustes ⚠'       // mexeu no que mede
    : (expo || contr || verMapa) ? '🎚 Ajustes •'     // só no que se vê
    : '🎚 Ajustes';
}

function alternarAjustes(abrirCard){
  const el = $('#ajustes');
  el.hidden = !(abrirCard === undefined ? el.hidden : abrirCard);
  $('#bAjustes').classList.toggle('on', !el.hidden);
}

/* snapshot integral para o desfazer, como o ✕ Limpar faz: os controles de
   segmentação trocam a máscara inteira, e um Ctrl+Z tem que devolver o traço */
function capturarDesfazerIntegral(){
  if (idx < 0 || !W) return;
  snapshotInicio(); marcaBox(W/2, H/2, Math.max(W, H)); fecharSnapshot();
}

/* ---- vista do mapa de desvio ------------------------------------------
   Troca a foto pelo sinal |flat−1| que está sendo cortado, com o que está
   ACIMA do corte em ciano. É o que torna o limiar legível: dá para ver a
   borda apagada por onde o contorno vazou, em vez de adivinhar. Usa o mapa
   que o navegador já baixou para o pincel mágico — nenhuma requisição nova. */
let bufMapa = null;
function desenharMapa(){
  if (!mapaDesvio || !W) return;
  const t = Math.max(1, Math.min(254, limiarOtsu + limOff));
  if (!bufMapa || bufMapa.width !== W) bufMapa = pctx.createImageData(W, H);
  const p = bufMapa.data;
  for (let i = 0, k = 0; i < mapaDesvio.length; i++, k += 4){
    const v = mapaDesvio[i];
    if (v > t){ p[k] = v*0.30; p[k+1] = 110 + v*0.45; p[k+2] = 150 + v*0.40; }
    else      { p[k] = p[k+1] = p[k+2] = v*0.85; }
    p[k+3] = 255;
  }
  pctx.putImageData(bufMapa, 0, 0);
}
function desenharFoto(){
  if (fotoAtual) pctx.drawImage(fotoAtual, 0, 0);
}
function pintarFundo(){ if (verMapa) desenharMapa(); else desenharFoto(); }

function alternarMapa(){
  if (!mapaDesvio) return;
  verMapa = !verMapa;
  $('#bMapa').classList.toggle('on', verMapa);
  $('#bMapa').textContent = verMapa ? '👁 voltar para a foto' : '👁 ver o mapa de desvio';
  pintarFundo(); sincronizarAjustes();
  $('#status').textContent = verMapa
    ? 'mapa |flat−1| — o ciano é o que está acima do corte'
    : '';
}

/* ---- prévia local do limiar -------------------------------------------
   Buffers reaproveitados: são ~15 MB por passada e o arrasto dispara uma por
   quadro. Alocar de novo a cada quadro entrega o trabalho ao coletor de lixo
   bem no momento em que a interface precisa estar fluida. */
let bufN = -1, bFg, bRot, bPil, bDentro, bVisto, bImg;
function prepararBuffers(){
  const N = W*H;
  if (bufN !== N){
    bufN = N;
    bFg = new Uint8Array(N); bRot = new Int32Array(N); bPil = new Int32Array(N);
    bDentro = new Uint8Array(N); bVisto = new Uint8Array(N);
    bImg = mctx.createImageData(W, H);
  } else {
    bRot.fill(0); bDentro.fill(0); bVisto.fill(0); bImg.data.fill(0);
  }
}

/* Limiar + maior componente + preenchimento de buracos, sobre o mapa |flat−1|.
   Deliberadamente SEM a abertura de disco 8 e SEM a suavização: as duas são
   caras demais para rodar por quadro em 1,4 milhão de pixels, e o servidor as
   aplica ao soltar. Conferido contra o scikit-image: área idêntica ao pixel. */
function contornoLocal(t){
  const N = W*H;
  prepararBuffers();
  for (let i = 0; i < N; i++) bFg[i] = mapaDesvio[i] > t ? 1 : 0;

  let melhor = 0, melhorArea = 0, r = 0;
  for (let s = 0; s < N; s++){
    if (!bFg[s] || bRot[s]) continue;
    r++; let topo = 0, area = 0;
    bPil[topo++] = s; bRot[s] = r;
    while (topo){
      const q = bPil[--topo]; area++;
      const x = q % W, y = (q - x)/W;
      if (x > 0     && bFg[q-1] && !bRot[q-1]){ bRot[q-1] = r; bPil[topo++] = q-1; }
      if (x < W - 1 && bFg[q+1] && !bRot[q+1]){ bRot[q+1] = r; bPil[topo++] = q+1; }
      if (y > 0     && bFg[q-W] && !bRot[q-W]){ bRot[q-W] = r; bPil[topo++] = q-W; }
      if (y < H - 1 && bFg[q+W] && !bRot[q+W]){ bRot[q+W] = r; bPil[topo++] = q+W; }
    }
    if (area > melhorArea){ melhorArea = area; melhor = r; }
  }
  if (!melhor) return null;
  for (let i = 0; i < N; i++) bDentro[i] = bRot[i] === melhor ? 1 : 0;

  // buracos: inunda o FUNDO a partir da moldura; fundo não alcançado é buraco
  let topo = 0;
  const por = q => { if (!bDentro[q] && !bVisto[q]){ bVisto[q] = 1; bPil[topo++] = q; } };
  for (let x = 0; x < W; x++){ por(x); por((H-1)*W + x); }
  for (let y = 0; y < H; y++){ por(y*W); por(y*W + W - 1); }
  while (topo){
    const q = bPil[--topo];
    const x = q % W, y = (q - x)/W;
    if (x > 0)     por(q-1);
    if (x < W - 1) por(q+1);
    if (y > 0)     por(q-W);
    if (y < H - 1) por(q+W);
  }
  let area = 0;
  for (let i = 0; i < N; i++){
    if (!bDentro[i] && !bVisto[i]) bDentro[i] = 1;
    if (bDentro[i]) area++;
  }
  return {dentro: bDentro, area};
}

function pintarLocal(dentro){
  const p = bImg.data;
  for (let i = 0, k = 0; i < dentro.length; i++, k += 4){
    if (dentro[i]){ p[k]=255; p[k+1]=230; p[k+2]=0; p[k+3]=255; }
  }
  mctx.putImageData(bImg, 0, 0);
}

let previaLimPendente = false;
function agendarPreviaLimiar(){
  if (!mapaDesvio || previaLimPendente || idx < 0) return;
  previaLimPendente = true;
  requestAnimationFrame(() => {
    previaLimPendente = false;
    const r = contornoLocal(Math.max(1, Math.min(254, limiarOtsu + limOff)));
    if (!r) mctx.clearRect(0, 0, W, H); else pintarLocal(r.dentro);
    editado = true;
    if (verMapa) desenharMapa();            // o ciano acompanha o corte
    render(true);
    // só área e diâmetro: circularidade e solidity dependem do contorno final,
    // e mostrar um valor que não vai bater com o medido seria pior que um traço
    atualizarHud(r ? {area_px: r.area, diam_equiv_px: 2*Math.sqrt(r.area/Math.PI),
                      circularidade: null, solidity: null, feret_max_px: null,
                      eixo_menor_px: null, toca_borda: null} : null, true);
  });
}

let limTimer = null, limSessao = false;
async function segmentarNoServidor(){
  const meu = idx, off = limOff, sig = sigmaAtual();
  $('#status').textContent = 'recalculando o contorno…';
  try{
    const r = await (await fetch('api/limiar/' + meu, {method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({deslocamento: off, sigma_fundo: sig})})).json();
    if (meu !== idx || off !== limOff || sig !== sigmaAtual()) return;   // mexeu no meio
    await carregarMascara(r.mascara);
    limiarOtsu = r.otsu;
    editado = true;
    if (verMapa) desenharMapa();
    render(true); atualizarHud(r.medidas, false);
    $('#aEstado').textContent = `Otsu ${r.otsu} → ${r.limiar}`
      + (sigmaPadrao() ? '' : ` · σ${r.sigma_fundo}`);
    $('#status').textContent = r.vazia
      ? '⚠ nenhum objeto sobrou com esse ajuste'
      : 'contorno recalculado';
  }catch(e){ $('#status').textContent = 'não consegui recalcular o contorno'; }
}

function iniciarSessao(){
  if (!limSessao){ limSessao = true; capturarDesfazerIntegral(); }
}

function mexerLimiar(v){
  if (idx < 0) return;
  iniciarSessao();
  limOff = v;
  sincronizarAjustes();
  agendarPreviaLimiar();
  clearTimeout(limTimer);
  limTimer = setTimeout(segmentarNoServidor, 320);
}

/* A escala do fundo refaz o MAPA, não só o corte: um gaussiano de σ até 180 em
   1,4 milhão de pixels não roda por quadro no navegador. Então ela só age ao
   soltar (evento `change`), e o mapa novo desce do servidor antes de qualquer
   prévia — senão a prévia local usaria o mapa velho e mostraria outra coisa. */
async function mexerSigma(k){
  if (idx < 0 || k === iSigma) return;
  iniciarSessao();
  iSigma = k; sincronizarAjustes();
  $('#status').textContent = `refazendo o mapa de desvio (σ ${sigmaAtual()})…`;
  await carregarDesvio(idx);
  if (idx < 0) return;
  agendarPreviaLimiar();
  clearTimeout(limTimer);
  limTimer = setTimeout(segmentarNoServidor, 60);
}

/* zera SÓ os controles; não mexe na máscara. Quem chama depois de trocar a
   máscara por outra via (abrir, ↺ Automático) já tem o contorno certo na tela */
function zerarSegmentacao(){
  clearTimeout(limTimer);
  limOff = 0; iSigma = I_SIGMA_PADRAO; limSessao = false;
  $('#aEstado').textContent = '';
  sincronizarAjustes();
}

/* o que foi usado, para a nota do registro — vazio quando nada saiu do padrão */
function notaDosAjustes(){
  const partes = [];
  if (limOff) partes.push('limiar Otsu ' + sinalV(limOff));
  if (!sigmaPadrao()) partes.push('fundo σ' + sigmaAtual());
  return partes.join(' · ');
}

$('#bAjustes').addEventListener('click', () => alternarAjustes());
$('#bAjustesFechar').addEventListener('click', () => alternarAjustes(false));
$('#bMapa').addEventListener('click', alternarMapa);
$('#aExpo').addEventListener('input', e => {
  expo = +e.target.value; aplicarFiltroFoto(); sincronizarAjustes();
  try { localStorage.setItem('ajExpo', expo); } catch (err) { /* ignora */ }
});
$('#aContr').addEventListener('input', e => {
  contr = +e.target.value; aplicarFiltroFoto(); sincronizarAjustes();
  try { localStorage.setItem('ajContr', contr); } catch (err) { /* ignora */ }
});
$('#aLim').addEventListener('input', e => mexerLimiar(+e.target.value));
$('#aLim').addEventListener('change', () => { limSessao = false; });
$('#aSigma').addEventListener('input', e => {
  $('#aSigmaV').textContent = SIGMAS[+e.target.value];   // só o rótulo, ao vivo
});
$('#aSigma').addEventListener('change', e => mexerSigma(+e.target.value));
$('#bAjustesZerar').addEventListener('click', () => {
  expo = 0; contr = 0;
  try { localStorage.removeItem('ajExpo'); localStorage.removeItem('ajContr'); }
  catch (e) { /* ignora */ }
  aplicarFiltroFoto();

  // "tudo" e tudo: um `else if` aqui deixava o limiar de pe quando as DUAS
  // metades estavam fora do padrao — que e justamente quando mais se aperta
  // este botao. Zera o limiar primeiro e deixa a rota refazer o contorno uma
  // vez so, com os dois ja no padrao.
  const trocarSigma = !sigmaPadrao();
  if (!trocarSigma && !limOff){ sincronizarAjustes(); return; }
  iniciarSessao();
  limOff = 0;
  if (trocarSigma) mexerSigma(I_SIGMA_PADRAO);
  else mexerLimiar(0);
  sincronizarAjustes();
});

aplicarFiltroFoto(); sincronizarAjustes();

$('#bDedo').onclick = () => { dedoDesenha = !dedoDesenha; dedoManual = true; atualizarBotaoDedo(); };
$('#bPressao').onclick = () => { usarPressao = !usarPressao;
  $('#bPressao').classList.toggle('on', usarPressao); };
$('#bLista').onclick = () => {
  const a = $('#app');
  if (matchMedia('(max-width:900px)').matches) a.classList.toggle('comLista');
  else a.classList.toggle('semLista');
  if (idx >= 0) setTimeout(enquadrar, 60);
};

// ajusta as dicas e o padrao do dedo conforme o aparelho
if (matchMedia('(pointer:coarse)').matches){
  $('.dicaTeclado').style.display = 'none';
  $('.dicaToque').style.display = '';
}
atualizarBotaoDedo();

addEventListener('keydown', e => {
  if (e.target.tagName === 'INPUT') return;
  if (e.code === 'Space'){ espaco = true; stage.classList.add('pan'); e.preventDefault(); return; }
  if (e.ctrlKey && e.key.toLowerCase() === 'z'){ desfazer(); e.preventDefault(); return; }
  if (e.ctrlKey && e.key === 'Enter'){ enviar('manual'); e.preventDefault(); return; }
  switch(e.key){
    case 'b': case 'B': ferr('pincel'); break;
    case 'l': case 'L': ferr('laco'); break;
    case 'm': case 'M': if (!$('#bMagico').disabled) $('#bMagico').click(); break;
    case 'h': case 'H': alternarHud(); break;
    case 'j': case 'J': alternarAjustes(); break;
    case 'v': case 'V': if (!$('#bMapa').disabled) alternarMapa(); break;
    case 'a': case 'A': mod('add'); break;
    case 'e': case 'E': mod('del'); break;
    case '[': $('#tam').value = Math.max(4, +$('#tam').value - 8); $('#tam').oninput({target:$('#tam')}); break;
    case ']': $('#tam').value = Math.min(260, +$('#tam').value + 8); $('#tam').oninput({target:$('#tam')}); break;
    case '0': enquadrar(); break;
    case 'ArrowLeft': abrir(idx - 1); break;
    case 'ArrowRight': abrir(idx + 1); break;
    case 'x': case 'X': $('#bExcluir').click(); break;
    case 'Enter': if (ferramenta === 'laco' && laco.length >= 3) preencherLaco(modo === 'del');
                  else $('#bOk').click(); break;
    case 'Escape': laco = []; render(true); break;
  }
});
addEventListener('keyup', e => {
  if (e.code === 'Space'){ espaco = false; stage.classList.remove('pan'); }
});
addEventListener('resize', () => { if (idx >= 0) enquadrar(); });

carregarLista();

/* =====================================================================
   ABA DE RESULTADOS
   Só linhas conferidas à mão. Gráficos em SVG inline: mediana com faixa
   interquartil, um painel por métrica, x = dia.
   ===================================================================== */
const CORG = {C: '#2a78d6', T: '#eb6834'};      // paleta validada p/ daltonismo
const TINTA = '#f2f2f0', TINTA2 = '#a7a7a2', MUDO = '#77776f', GRADE = '#2c2c31';

/* Tres modos, do mais cego para o menos cego. O desenho e fatorial 2x2 —
   glicose (L/H) x tratamento (C/T) — e o modo 2 mostra as quatro celulas dele.
   O modo 1 continua existindo porque agrega as duas glicoses e portanto tem o
   dobro do n: e o efeito principal do tratamento. O modo 2 e o unico que mostra
   se esse efeito depende da glicose, que e a interacao, e o agregado esconde. */
const MODOS = [
  {rot: 'Mostrar por grupo',  dica: 'o agregado por dia não revela grupo nenhum'},
  {rot: 'Ver os 4 grupos',    dica: '⚠ controle vs tratado (as duas glicoses agregadas) — você deixou de estar cego'},
  {rot: 'Ocultar grupos',     dica: '⚠ LC · LT · HC · HT — o desenho fatorial inteiro; você deixou de estar cego'},
];
let modoRes = 0, cacheRes = null;

const FACETAS = [['L', 'Baixa glicose'], ['H', 'Alta glicose']];

const METRICAS = [
  ['area_norm_D0', 'Área normalizada pelo D0',
   'só esferoides cujo D0 também já foi conferido', true],
  ['diam_equiv_px', 'Diâmetro equivalente (px)', '', false],
  ['circularidade', 'Circularidade  4πA/P²', 'com a suavização σ=6 da etapa 9', false],
  ['circularidade_sem_suavizar', 'Circularidade sem suavizar',
   'análise de sensibilidade: a etapa 9 não é neutra em escala', false],
  ['solidity', 'Solidity  A / A convexa', '', false],
];

function trocarAba(qual){
  const res = qual === 'res';
  const conf = qual === 'conf';
  const galeria = qual === 'galeria';
  const painel = $('#painelGaleria');
  $('#painelResultados').hidden = !res;
  $('#painelConferencia').hidden = !conf;
  painel.hidden = !galeria;
  $('#abaRes').classList.toggle('on', res);
  $('#abaConf').classList.toggle('on', conf);
  $('#abaGaleria').classList.toggle('on', galeria);
  if (galeria && !painel.hasAttribute('src')) painel.src = 'galeria/';
  if (res) carregarResultados();
}
$('#abaConf').onclick = () => trocarAba('conf');
$('#abaRes').onclick = () => trocarAba('res');
$('#abaGaleria').onclick = () => trocarAba('galeria');
$('#bAtualizar').onclick = () => carregarResultados();
$('#bGrupos').onclick = () => {
  modoRes = (modoRes + 1) % 3;
  $('#bGrupos').classList.toggle('on', modoRes > 0);
  $('#bGrupos').textContent = MODOS[modoRes].rot;
  $('#dicaGrupos').textContent = MODOS[modoRes].dica;
  carregarResultados();
};

async function carregarResultados(){
  const r = await (await fetch('api/resultados' + (modoRes ? '?grupos=1' : ''))).json();
  cacheRes = r;
  desenharCartoes(r);
  desenharGraficos(r);
  $('#resumoAba').textContent = `${r.n_conferidas} de ${r.n_total} conferidas`;
}

function desenharCartoes(r){
  const pct = 100 * r.n_conferidas / Math.max(r.n_total, 1);
  const porDia = Object.entries(r.por_dia)
    .map(([d, v]) => `D${d} ${v.conferidas}/${v.total}`).join(' · ');
  $('#cartoes').innerHTML = `
    <div class="cartao"><div class="v">${r.n_conferidas}</div>
      <div class="r">imagens conferidas de ${r.n_total}</div>
      <div class="b"><i style="width:${pct.toFixed(1)}%"></i></div></div>
    <div class="cartao"><div class="v">${r.n_series_completas}</div>
      <div class="r">esferoides com todos os dias do projeto conferidos</div></div>
    <div class="cartao" style="min-width:230px"><div class="v" style="font-size:13px;
      font-weight:600;line-height:1.6">${porDia}</div>
      <div class="r">conferidas por dia</div></div>`;
}

function desenharGraficos(r){
  // no modo 4 grupos o cartao ocupa duas colunas: sao dois paineis lado a lado
  const largo = modoRes === 2 ? ' larga' : '';
  $('#graficos').innerHTML = METRICAS.map(([met, titulo, nota, normalizada]) => {
    const svg = grafico(r, met, normalizada);
    return `<div class="gr${largo}"><h3>${titulo}</h3>
      <p>${nota || '&nbsp;'}</p>${svg}</div>`;
  }).join('');
}

function grafico(r, met, normalizada){
  const W = 340, H = 172, ML = 46, MR = 12, MT = 10, MB = 26, GAP = 20;

  const pontos = lista => lista.filter(x => x[met] && x[met].n)
    .map(x => ({d: x.dia, ...x[met]})).sort((a, b) => a.d - b.d);
  const cor = t => ({cor: CORG[t], nome: t === 'C' ? 'Controle' : 'Tratado'});

  /* Um painel por nivel de glicose no modo fatorial. Nao e enfeite: o efeito do
     tratamento so e legivel DENTRO de cada nivel, e o efeito da glicose so e
     legivel comparando os dois paineis. Os dois compartilham a escala y — sem
     isso a comparacao entre paineis nao vale nada. */
  let paineis;
  if (modoRes === 2 && r.grupos4)
    paineis = FACETAS.map(([g, nome]) => ({titulo: nome, series: ['C', 'T'].map(t =>
      ({...cor(t), pts: pontos(r.grupos4.filter(x => x.grupo === g + t))}))}));
  else if (modoRes === 1 && r.grupos)
    paineis = [{titulo: '', series: ['C', 'T'].map(t =>
      ({...cor(t), pts: pontos(r.grupos.filter(x => x.trat === t))}))}];
  else
    paineis = [{titulo: '', series: [{cor: CORG.C, nome: 'conferidas',
                                      pts: pontos(r.series)}]}];

  const todos = paineis.flatMap(p => p.series.flatMap(s => s.pts));
  if (!todos.length)
    return `<div class="vazio">ainda sem dado conferido para esta métrica</div>`;

  let lo = Math.min(...todos.map(p => p.q1)), hi = Math.max(...todos.map(p => p.q3));
  if (normalizada) lo = Math.min(lo, 0);
  if (hi - lo < 1e-9) { hi = lo + 1; }
  const pad = (hi - lo) * 0.12; lo -= pad; hi += pad;
  const Y = v => MT + (1 - (v - lo) / (hi - lo)) * (H - MT - MB);
  const dec = Math.abs(hi) > 20 ? 0 : 2;
  const dias = Object.keys(r.por_dia).map(Number);
  const primeiro = Math.min(...dias), intervalo = Math.max(...dias) - primeiro;

  const painel = (p, k) => {
    const dx = k * (W + GAP);
    const X = d => dx + ML + (intervalo ? (d - primeiro) / intervalo : 0.5) * (W - ML - MR);
    const ticks = [lo, (lo + hi) / 2, hi].map(v =>
      `<line x1="${dx + ML}" y1="${Y(v).toFixed(1)}" x2="${dx + W - MR}"
         y2="${Y(v).toFixed(1)}" stroke="${GRADE}" stroke-width="1"/>` +
      (k ? '' : `<text x="${ML - 6}" y="${(Y(v) + 3.5).toFixed(1)}" fill="${MUDO}"
         font-size="9.5" text-anchor="end">${v.toFixed(dec)}</text>`)).join('');
    const eixoX = dias.map(d =>
      `<text x="${X(d)}" y="${H - 8}" fill="${MUDO}" font-size="10"
         text-anchor="middle">D${d}</text>`).join('');
    const ns = p.series.filter(s => s.pts.length)
                       .flatMap(s => s.pts.map(q => q.n));
    const cab = p.titulo
      ? `<text x="${dx + ML}" y="${MT - 1}" fill="${TINTA2}" font-size="10.5"
           font-weight="600">${p.titulo}</text>
         <text x="${dx + W - MR}" y="${MT - 1}" fill="${MUDO}" font-size="9.5"
           text-anchor="end">n≥${ns.length ? Math.min(...ns) : 0}</text>` : '';
    const corpo = p.series.map(s => {
      if (!s.pts.length) return '';
      const faixa = s.pts.map(q => `${X(q.d).toFixed(1)},${Y(q.q3).toFixed(1)}`).join(' ')
        + ' ' + s.pts.slice().reverse()
            .map(q => `${X(q.d).toFixed(1)},${Y(q.q1).toFixed(1)}`).join(' ');
      const linha = s.pts.map(q => `${X(q.d).toFixed(1)},${Y(q.mediana).toFixed(1)}`).join(' ');
      const bolas = s.pts.map(q =>
        `<circle cx="${X(q.d).toFixed(1)}" cy="${Y(q.mediana).toFixed(1)}" r="3.4"
           fill="${s.cor}" stroke="#17171a" stroke-width="1.3">
           <title>${p.titulo ? p.titulo + ' · ' : ''}${s.nome} D${q.d} — mediana ${q.mediana.toFixed(3)} (n=${q.n})</title></circle>`).join('');
      return `<polygon points="${faixa}" fill="${s.cor}" opacity="0.16"/>
        <polyline points="${linha}" fill="none" stroke="${s.cor}" stroke-width="2"
          stroke-linejoin="round" stroke-linecap="round"/>${bolas}`;
    }).join('');
    return ticks + eixoX + cab + corpo;
  };

  const LW = paineis.length * W + (paineis.length - 1) * GAP;
  const svg = `<svg viewBox="0 0 ${LW} ${H}" role="img">${
    paineis.map(painel).join('')}</svg>`;

  const nmin = s => s.pts.length ? Math.min(...s.pts.map(q => q.n)) : 0;
  let legenda;
  if (modoRes === 0) {
    legenda = `<span>mediana e faixa interquartil · n≥${nmin(paineis[0].series[0])}</span>`;
  } else if (modoRes === 1) {
    legenda = paineis[0].series.map(s =>
      `<span><i style="background:${s.cor}"></i>${s.nome} (n≥${nmin(s)})</span>`).join('');
  } else {
    legenda = ['C', 'T'].map(t =>
      `<span><i style="background:${CORG[t]}"></i>${cor(t).nome}</span>`).join('')
      + `<span style="color:var(--muted)">painel = glicose · LC LT HC HT</span>`;
  }
  return `${svg}<div class="legenda">${legenda}</div>`;
}

// delegado no container: o innerHTML do painel é reescrito a cada medida, então
// um listener preso ao botão morreria no primeiro re-render
$('#hud').addEventListener('click', ev => {
  if (ev.target.closest('.alt')) { ev.stopPropagation(); alternarHud(); }
});
$('#hud').addEventListener('pointerdown', ev => {
  if (ev.target.closest('.alt')) ev.stopPropagation();
});
