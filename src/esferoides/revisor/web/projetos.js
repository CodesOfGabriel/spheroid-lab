const novo = document.querySelector('#novo');
const janela = document.querySelector('#janela');
const formulario = document.querySelector('#importar');
const nome = document.querySelector('#nome');
const pasta = document.querySelector('#pasta');
const criar = document.querySelector('#criar');
const cancelar = document.querySelector('#cancelar');
const mensagem = document.querySelector('#mensagem');
const aviso = document.querySelector('#aviso');

function mostrar(elemento, texto) {
  elemento.textContent = texto;
  elemento.hidden = !texto;
}

function montarCard(projeto) {
  const card = document.createElement(projeto.url ? 'a' : 'article');
  card.className = 'projeto';
  if (projeto.url) card.href = projeto.url;

  if (projeto.capa) {
    const imagem = document.createElement('img');
    imagem.src = projeto.capa;
    imagem.alt = '';
    imagem.loading = 'lazy';
    imagem.addEventListener('error', () => imagem.remove(), {once: true});
    card.append(imagem);
  }

  const texto = document.createElement('div');
  texto.className = 'projeto-texto';
  const titulo = document.createElement('h2');
  titulo.textContent = projeto.nome;
  const detalhes = document.createElement('p');
  detalhes.textContent = projeto.disponivel
    ? `${projeto.fotos} ${projeto.fotos === 1 ? 'foto' : 'fotos'}`
    : 'Fotos ou CSV de medidas indisponíveis';
  texto.append(titulo, detalhes);
  card.append(texto);
  if (projeto.url) {
    const seta = document.createElement('span');
    seta.className = 'abrir';
    seta.setAttribute('aria-hidden', 'true');
    seta.textContent = '↗';
    card.append(seta);
  }
  novo.before(card);
}

async function carregarProjetos() {
  try {
    const resposta = await fetch('/api/projetos');
    if (!resposta.ok) throw new Error();
    (await resposta.json()).forEach(montarCard);
  } catch {
    mostrar(aviso, 'Não foi possível carregar os projetos. Atualize a página para tentar novamente.');
  }
}

novo.addEventListener('click', () => janela.showModal());
cancelar.addEventListener('click', () => janela.close());
janela.addEventListener('cancel', evento => {
  if (criar.disabled) evento.preventDefault();
});
janela.addEventListener('close', () => {
  formulario.reset();
  mostrar(mensagem, '');
  novo.focus();
});
pasta.addEventListener('change', () => {
  const primeiraFoto = pasta.files[0];
  if (primeiraFoto && !nome.value.trim()) {
    nome.value = primeiraFoto.webkitRelativePath.split('/')[0].slice(0, 80);
  }
});

formulario.addEventListener('submit', async evento => {
  evento.preventDefault();
  const dados = new FormData();
  dados.append('nome', nome.value.trim());
  for (const arquivo of pasta.files) {
    const relativo = arquivo.webkitRelativePath;
    if (/^[^/]+\/(?:n[1-9]\d*\/d(?:0|[1-9]\d*)\/[^/]+\.png|_analise\/(?:resultados|mascaras_auto|mascaras_revisadas|mapas_desvio)\/.+\.(?:csv|png|jsonl?|db(?:-wal)?))$/.test(relativo)) {
      dados.append('arquivos', arquivo, relativo);
    }
  }
  criar.disabled = cancelar.disabled = true;
  mostrar(mensagem, 'Importando os arquivos e preparando as medidas…');
  let abrindo = false;
  try {
    const resposta = await fetch('/api/projetos', {method: 'POST', body: dados});
    const dadosResposta = await resposta.json().catch(() => ({}));
    if (!resposta.ok) {
      const erro = resposta.status === 413 ? 'A pasta ultrapassa o limite de importação.'
        : dadosResposta.erro || 'Tente importar a pasta novamente.';
      mostrar(mensagem, erro);
      return;
    }
    abrindo = true;
    location.assign(dadosResposta.url);
  } catch {
    mostrar(mensagem, 'A conexão caiu durante a importação. Confira a lista de projetos antes de tentar novamente.');
  } finally {
    if (!abrindo) criar.disabled = cancelar.disabled = false;
  }
});

carregarProjetos();
