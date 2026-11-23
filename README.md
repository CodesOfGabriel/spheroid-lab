# Spheroid Lab

Aplicação local para medir **forma e área projetada de esferoides em micrografias 2D de campo claro**. Importe imagens, revise os contornos no navegador e obtenha os resultados em CSV. Os dados ficam na máquina que executa a aplicação.

Autor principal: [Gabriel Santos (@CodesOfGabriel)](https://github.com/CodesOfGabriel).

## Instalação

Instale Python 3.11 ou mais recente. Clone este repositório pelo botão **Code** do GitHub e abra um terminal na pasta clonada.

**Windows, PowerShell**

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install .
.\.venv\Scripts\python.exe -m esferoides revisar --sem-aquecer
```

**Linux e macOS**

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install .
./.venv/bin/python -m esferoides revisar --sem-aquecer
```

Abra [http://127.0.0.1:7860/](http://127.0.0.1:7860/). Clique em **+ Novo projeto**, dê um nome e selecione a pasta raiz das imagens. Ao concluir a importação, o aplicativo abre o revisor. Nas próximas sessões, clique no card do projeto. Mantenha o terminal aberto e use **Ctrl+C** para encerrar.

Com o ambiente virtual ativado, `spheroid-lab revisar` também funciona. No Windows, `.\iniciar-spheroid-lab.cmd` usa o código do checkout se o Python disponível no terminal já tiver as dependências.

## Preparar as imagens

Use PNGs com um esferoide principal por imagem. Os nomes abaixo são ilustrativos.

```text
meu-experimento/
├── n1/
│   ├── d0/
│   │   ├── D0 A1.png
│   │   └── D0 B1.png
│   └── d1/
│       ├── D1 A1.png
│       └── D1 B1.png
└── n2/
    └── d0/
        └── D0 A1.png
```

- `n1`, `n2` etc. identificam conjuntos ou placas. Registre quais placas pertencem à mesma execução biológica.
- `d0`, `d1` etc. identificam os tempos. O dia no nome do PNG precisa coincidir com o da pasta. Projetos de tempo único também são aceitos.
- `A` e `B` são códigos de grupo compostos por letras. Mantenha o mesmo grupo e número do esferoide nos diferentes tempos da série. Use `.png` em minúsculas.
- Comece com algumas fotos representativas. O filtro automático remove objetos menores que **15.000 px²**. Escala de aquisição, contraste e artefatos influenciam a segmentação. Confira visualmente as máscaras antes de analisar os resultados. [Protocolo e parâmetros](docs/protocolo.md#segmentação).

Para importar um projeto já processado, inclua `_analise` com `resultados/medidas_esferoides.csv` e os arquivos de revisão. Para trabalhar diretamente sobre uma pasta existente, use `revisar --dados CAMINHO`. A pasta vinculada precisa ter o CSV automático e permitir gravação em `_analise`. Se só tiver imagens, use **Novo projeto** ou execute `medir --dados CAMINHO`.

## Revisar e exportar

1. Abra **Conferência** e compare a foto com a máscara. Clique em **Contorno OK** para registrar a aceitação ou edite com pincel, laço ou pincel mágico e clique em **Salvar correção**. Use **Excluir imagem** quando a qualidade comprometer a medição.
2. No **Ajuste rápido**, exposição e contraste mudam a visualização. Limiar e escala do fundo geram uma proposta de contorno. Os parâmetros usados são registrados ao salvar.
3. Abra **Resultados** para resumir as correções manuais e **Galeria** para navegar pelas imagens. Os modos C/T e de quatro grupos pressupõem os códigos `LC`, `LT`, `HC` e `HT`. Os CSVs preservam os demais códigos.
4. Abra `_analise/resultados/`. `medidas_esferoides.csv` contém as medidas automáticas. `medidas_final.csv` é atualizado ao salvar ou reverter uma decisão. Use `status` e `revisado_em` para identificar as decisões.

| Estado | Significado |
|---|---|
| `ok` | Medida automática. Quando `revisado_em` está preenchido, o contorno foi aceito explicitamente. |
| `manual` | Contorno corrigido manualmente. |
| `excluido` | Imagem excluída por decisão registrada, com medidas vazias. |
| `falha` | Medição automática sem contorno mensurável. |

Projetos importados ficam em `dados/projetos/<id>/arquivos/`. Projetos vinculados gravam na pasta original. Use `--projetos CAMINHO` para escolher outro catálogo. Para backup, encerre a aplicação e copie o catálogo, as pastas vinculadas e as sessões de validação que quiser preservar.

### Linha de comando

Use `python -m esferoides` seguido de um subcomando. `ESFEROIDES_DADOS` pode definir a pasta usada em lugar de `--dados`.

| Subcomando | Resultado |
|---|---|
| `revisar` | Abre o catálogo. `--porta` muda a porta e `--dados` vincula um projeto existente. |
| `medir --dados CAMINHO` | Gera o CSV automático, imagens de conferência e folhas de contato. |
| `verificar --dados CAMINHO` | Gera triagem e resumo descritivo. As faixas de diâmetro e evolução temporal são heurísticas de um protocolo de referência. |
| `graficos --dados CAMINHO` | Gera figuras para o desenho D0–D3 e LC/LT/HC/HT. `--conferidas` usa apenas correções manuais. Para outros desenhos, use o painel agregado ou analise o CSV. |
| `reconstruir --dados CAMINHO` | Reconstitui as decisões usando o diário e as máscaras. Faça backup antes de executar. |
| `validacao --help` | Mostra as opções do módulo opcional de Validação Cega. |

O servidor usa localhost por padrão. `--rede` ativa o acesso pela rede local e protege o revisor por token. Guarde o link completo como credencial de escrita. A Validação Cega usa autenticação própria.

## Métodos e desenvolvimento

- [Protocolo, fórmulas e limites](docs/protocolo.md)
- [Validação Cega e métricas de concordância](docs/validacao-cega.md)
- [Decisões de implementação](docs/decisoes.md)
- [Licença MIT](LICENSE)

Para rodar os testes com dados sintéticos, instale com `python -m pip install -e ".[dev]"` e execute `python -m pytest`. Para a suíte opcional de canvas, use `node --test tests/test_validacao_canvas.mjs`.

## English quick start

Clone this repository and install it with Python 3.11+ using `python -m pip install .` in a virtual environment. Run `python -m esferoides revisar --sem-aquecer` and open [localhost:7860](http://127.0.0.1:7860/). Click **Novo projeto** and select a root folder with files such as `n1/d0/D0 A1.png`. Inspect and correct the masks in **Conferência**. Measurements are saved under `_analise/resultados/`. The [methods and formulas](docs/protocolo.md) report 2D measurements in pixel units.
