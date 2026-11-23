import { Editor } from './validacao_canvas.js';

const $ = seletor => document.querySelector(seletor);
const api = './api/';
const csrf = $('meta[name="csrf-token"]').content;
const admin = document.body.dataset.perfil === 'admin';
const nomes = {
  pendente: 'Pendente', rascunho: 'Rascunho', concluida: 'Concluída', nao_avaliavel: 'Não avaliável',
};
const finalizado = status => ['concluida', 'nao_avaliavel'].includes(status);
let fila = [];
let sessao;

async function chamar(rota, corpo) {
  const resp = await fetch(api + rota, corpo
    ? { method: 'POST', body: corpo, headers: { 'X-CSRF-Token': csrf } } : {});
  if (resp.status === 403) throw new Error('Acesso expirado ou indisponível. Entre novamente.');
  const dados = await resp.json().catch(() => null);
  if (!resp.ok) throw new Error(dados?.erro || 'Falha ao comunicar com o servidor.');
  return dados;
}

function mostrar(texto, erro = false) {
  $('#mensagem').textContent = texto;
  $('#mensagem').classList.toggle('vc-erro', erro);
}

function mostrarFila(selecionado, abrir) {
  const feitas = fila.filter(i => finalizado(i.status)).length;
  $('#contagem').textContent = feitas + ' de ' + fila.length + ' finalizadas';
  $('#progresso').value = feitas;
  $('#fila').replaceChildren();
  $('#navegar')?.replaceChildren();
  for (const i of fila) {
    const linha = document.createElement('li');
    const texto = i.codigo + ' · ' + nomes[i.status];
    if (abrir) {
      const botao = document.createElement('button');
      botao.className = 'item' + (selecionado === i.codigo ? ' on' : '');
      if (selecionado === i.codigo) botao.setAttribute('aria-current', 'true');
      botao.textContent = texto;
      botao.onclick = () => abrir(i.codigo);
      linha.append(botao);
      $('#navegar').add(new Option(texto, i.codigo, false, selecionado === i.codigo));
    } else {
      linha.textContent = texto;
    }
    $('#fila').append(linha);
  }
  return feitas;
}

async function painelAdmin() {
  let emCurso = false;
  let resumo;
  let calculando = false;
  function tabela() {
    const campo = $('#resumo-estrato').value;
    const linhas = $('#resumo-linhas');
    linhas.replaceChildren();
    const formato = new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 3 });
    for (const r of resumo.filter(l => l.estrato === campo && l.metrica === 'dice')) {
      const outras = ['iou', 'erro_relativo_area_pct'].map(metrica => resumo.find(l =>
        l.estrato === campo && l.comparacao === r.comparacao && l.valor === r.valor
        && l.metrica === metrica).mediana);
      const linha = linhas.insertRow();
      for (const campo of [r.comparacao, r.valor, r.n, r.mediana, ...outras]) {
        linha.insertCell().textContent = typeof campo === 'number' ? formato.format(campo) : (campo ?? '—');
      }
    }
  }
  async function carregarResumo() {
    if (resumo || calculando) return;
    calculando = true;
    $('#vc-resultados').hidden = false;
    $('#status-resultados').textContent = 'Calculando em pixels…';
    try {
      resumo = await chamar('resultados');
      tabela();
      $('#status-resultados').textContent = 'Medianas por tipo de comparação.';
    } catch (e) {
      $('#status-resultados').textContent = e.message;
    } finally {
      calculando = false;
    }
  }
  $('#resumo-estrato').onchange = () => { if (resumo) tabela(); };
  function renderizar() {
    const feitas = mostrarFila();
    $('#situacao').textContent = sessao?.encerrada ? 'Avaliação encerrada. Comparação liberada.'
      : sessao ? 'Avaliação aberta.' : 'Sessão aguardando preparação.';
    $('#vc-acompanhamento').hidden = !sessao;
    $('#preparar').hidden = !!sessao;
    $('#pacote').hidden = !sessao;
    $('#encerrar').hidden = !sessao || !!sessao?.encerrada;
    $('#encerrar').disabled = emCurso || feitas !== fila.length;
    $('#exportar').hidden = !sessao?.encerrada;
    if (sessao?.encerrada) carregarResumo();
  }
  async function atualizar() {
    const dados = await chamar('fila');
    sessao = dados.sessao;
    fila = dados.imagens;
    renderizar();
  }
  async function acao(rota, texto) {
    if (emCurso) return;
    emCurso = true;
    $('#preparar').disabled = true;
    $('#encerrar').disabled = true;
    mostrar(texto);
    try {
      await chamar(rota, new FormData());
      mostrar('');
      await atualizar();
    } catch (e) {
      mostrar(e.message, true);
    } finally {
      emCurso = false;
      $('#preparar').disabled = false;
      renderizar();
    }
  }
  $('#preparar').onclick = () => acao('preparar', 'Preparando e conferindo os arquivos…');
  $('#encerrar').onclick = () => {
    if (confirm('Encerrar e bloquear as versões finais de todas as anotações?')) {
      acao('encerrar', 'Encerrando a sessão…');
    }
  };
  await atualizar();
  setInterval(() => {
    if (!emCurso) atualizar().catch(e => mostrar(e.message, true));
  }, 5000);
}

async function painelAvaliadora() {
  let atual;
  let ocupada = false;
  let alterada = false;
  let temporizador;
  const url = codigo => 'anotacao/' + encodeURIComponent(codigo);
  const editor = new Editor(alterar, controles);

  function controles() {
    const pronta = !!atual && !editor.wrap.hidden && !ocupada;
    const editavel = pronta && !sessao?.encerrada;
    editor.editavel = editavel;
    const vertices = editor.poligono.length;
    $('#ferramentas').disabled = !editavel;
    $('#decisao').disabled = !editavel;
    $('#camada').disabled = !!vertices || !!editor.gesto;
    document.querySelectorAll('[data-ferramenta]').forEach(b => {
      b.disabled = !!vertices || !!editor.gesto;
    });
    $('#fecharPoligono').disabled = vertices < 3;
    $('#desfazer').disabled = !vertices && !editor.passado.length;
    $('#refazer').disabled = !!vertices || !editor.futuro.length;
    $('#navegar').disabled = ocupada || !fila.length;
    const posicao = fila.findIndex(i => i.codigo === atual?.codigo);
    $('#anterior').disabled = !pronta || posicao < 1;
    $('#proxima').disabled = !pronta || posicao === fila.length - 1;
    $('#nivelZoom').textContent = editor.wrap.hidden ? '' : Math.round(editor.zoom * 100) + '%';
  }

  function atualizarSituacao() {
    $('#situacao').textContent = sessao?.encerrada ? 'Sessão encerrada · ' + nomes[atual.status]
      : nomes[atual.status || 'pendente'];
  }

  function alterar(imediato = true) {
    alterada = true;
    mostrar('Alterações aguardando salvamento.');
    clearTimeout(temporizador);
    temporizador = setTimeout(() => salvar('rascunho'), imediato ? 0 : 450);
  }

  async function salvar(status, motivo = '') {
    clearTimeout(temporizador);
    if (!atual || ocupada || sessao?.encerrada) return false;
    if (editor.poligono.length || editor.gesto) {
      mostrar('Feche ou desfaça o polígono e termine o traço antes de salvar.', true);
      return false;
    }
    ocupada = true;
    controles();
    mostrar('Salvando…');
    try {
      const dados = new FormData();
      dados.set('status', status);
      dados.set('versao', atual.versao ?? '');
      dados.set('nota', $('#nota').value);
      dados.set('ambigua', $('#ambigua').checked ? '1' : '0');
      dados.set('motivo', motivo);
      const [externa, interna] = await Promise.all(['externa', 'interna'].map(c => editor.png(c)));
      dados.set('externa', externa, 'externa.png');
      dados.set('interna', interna, 'interna.png');
      Object.assign(atual, await chamar(url(atual.codigo), dados), { motivo });
      fila.find(i => i.codigo === atual.codigo).status = atual.status;
      alterada = false;
      mostrarFila(atual.codigo, abrir);
      atualizarSituacao();
      mostrar('Salvo.');
      return true;
    } catch (e) {
      mostrar(e.message, true);
      return false;
    } finally {
      ocupada = false;
      controles();
    }
  }

  async function abrir(codigo) {
    if (ocupada || codigo === atual?.codigo) return;
    if (editor.poligono.length || editor.gesto) {
      mostrar('Feche ou desfaça o polígono e termine o traço antes de mudar de imagem.', true);
      $('#navegar').value = atual.codigo;
      return;
    }
    if (alterada && !await salvar('rascunho')) {
      $('#navegar').value = atual.codigo;
      return;
    }
    ocupada = true;
    controles();
    try {
      const estado = await chamar('fila');
      sessao = estado.sessao;
      fila = estado.imagens;
      const dados = await chamar(url(codigo));
      await editor.abrir(api + 'foto/' + encodeURIComponent(codigo),
        dados.versao ? api + url(codigo) + '/' + dados.versao : null);
      atual = dados;
      $('#codigo').textContent = codigo;
      $('#nota').value = atual.nota || '';
      $('#ambigua').checked = !!atual.ambigua;
      mostrarFila(codigo, abrir);
      atualizarSituacao();
      mostrar(atual.motivo || '');
    } catch (e) {
      mostrar(e.message, true);
      $('#navegar').value = atual?.codigo || '';
    } finally {
      ocupada = false;
      controles();
    }
  }

  function passo(direcao) {
    const seguinte = fila[fila.findIndex(i => i.codigo === atual.codigo) + direcao];
    if (seguinte) abrir(seguinte.codigo);
  }
  $('#navegar').onchange = e => abrir(e.target.value);
  $('#anterior').onclick = () => passo(-1);
  $('#proxima').onclick = () => passo(1);
  $('#salvar').onclick = () => salvar(alterada || !atual.versao ? 'rascunho' : atual.status, atual.motivo);
  $('#concluir').onclick = () => salvar('concluida');
  $('#nota').oninput = () => alterar(false);
  $('#ambigua').onchange = () => alterar();
  const dialogo = $('#justificar');
  $('#excluir').onclick = () => {
    clearTimeout(temporizador);
    $('#motivo').value = atual.motivo || '';
    dialogo.returnValue = '';
    dialogo.showModal();
  };
  dialogo.onclose = () => {
    if (dialogo.returnValue === 'confirmar') salvar('nao_avaliavel', $('#motivo').value.trim());
    else if (alterada) alterar();
  };
  $('#camada').onchange = e => { editor.camada = e.target.value; };
  $('#diametro').oninput = e => { editor.diametro = Number(e.target.value); };
  $('#opacidade').oninput = e => {
    editor.opacidade = Number(e.target.value) / 100;
    editor.renderizar();
  };
  $('#fecharPoligono').onclick = () => editor.fechar();
  $('#desfazer').onclick = () => editor.desfazer();
  $('#refazer').onclick = () => editor.transitar(editor.futuro, editor.passado);
  $('#enquadrar').onclick = () => editor.enquadrar();
  $('#maisZoom').onclick = () => editor.ampliar(1.25);
  $('#menosZoom').onclick = () => editor.ampliar(0.8);
  const mover = $('#mover');
  mover.onclick = () => {
    editor.mover = !editor.mover;
    mover.setAttribute('aria-pressed', editor.mover);
    mover.classList.toggle('on', editor.mover);
    editor.stage.classList.toggle('vc-pan', editor.mover);
  };
  for (const botao of document.querySelectorAll('[data-ferramenta]')) {
    botao.onclick = () => {
      editor.ferramenta = botao.dataset.ferramenta;
      for (const b of document.querySelectorAll('[data-ferramenta]')) {
        b.classList.toggle('on', b === botao);
        b.setAttribute('aria-pressed', b === botao);
      }
    };
  }
  document.addEventListener('keydown', e => {
    if (!editor.editavel || e.target.matches('textarea, input, select') || dialogo.open) return;
    if (e.key === 'Escape' && editor.poligono.length) {
      editor.poligono = [];
      editor.renderizar();
    }
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') {
      e.preventDefault();
      if (e.shiftKey) editor.transitar(editor.futuro, editor.passado);
      else editor.desfazer();
    }
  });
  window.addEventListener('beforeunload', e => {
    if (!alterada && !editor.poligono.length) return;
    e.preventDefault();
    e.returnValue = '';
  });
  const dados = await chamar('fila');
  sessao = dados.sessao;
  fila = dados.imagens;
  mostrarFila(null, abrir);
  if (fila.length) {
    await abrir((fila.find(i => i.status === 'rascunho')
      || fila.find(i => !finalizado(i.status)) || fila[0]).codigo);
  } else {
    $('#situacao').textContent = 'A sessão ainda está sendo preparada.';
  }
}

(admin ? painelAdmin() : painelAvaliadora()).catch(e => mostrar(e.message, true));
