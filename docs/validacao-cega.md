# Validação Cega

Módulo opcional para comparar uma máscara de referência com a anotação humana independente. Ele usa uma sessão SQLite separada, preserva as versões das anotações e fornece à pessoa avaliadora apenas imagens codificadas e as próprias anotações.

## Preparar a sessão

A preparação embutida atende ao **protocolo de referência** com PNGs de 1368 × 1038 px e 48 estratos (3 placas, D0 a D3 e grupos LC, LT, HC e HT). Para outros desenhos, use o revisor padrão. Nenhum conjunto de imagens, manifesto ou sessão é distribuído com o aplicativo.

- Disponibilize as micrografias na [estrutura de pastas do revisor](../README.md#preparar-as-imagens) e as máscaras editadas em `_analise/mascaras_revisadas/`, com o nome `<placa>_<nome-da-foto-com-espaços-trocados-por-underscores>.png`.
- A preparação lê `_analise/resultados/morfometria_imagej.csv`. A tabela de referência precisa ter as colunas `experimento,dia,grupo,Label,status,Area,replica`. As linhas elegíveis têm `status=manual`, com nome de PNG em `Label` e área da referência em pixels.
- O sorteio seleciona uma imagem por estrato. Use `--seed N` para controlar a semente. O módulo aceita uma seleção anterior via `--manifesto CSV`, com colunas `codigo,chave,experimento,grupo,dia` e códigos `CEGO001` ou `IMG-001` no formato de três dígitos.
- A preparação verifica a área da máscara de referência e registra hashes. Quando usa uma seleção arquivada, pode ler as máscaras finais e os arquivos de proveniência ao lado dela. Sem essas versões, reconstrói a referência com o maior componente e suavização gaussiana de 6 px e exige igualdade da área com a tabela.
- A exportação de micrografias para a avaliação remove metadados. Confirme visualmente que os pixels da imagem não contêm rótulos identificáveis.

```text
python -m esferoides validacao --dados "../meu-experimento" --sessao "./dados/validacao-cega" --preparar
```

## Abrir a sessão

Defina `ESFEROIDES_VALIDACAO_ADMIN` e `ESFEROIDES_VALIDACAO_AVALIADORA` no ambiente do servidor, com senhas distintas de no mínimo 16 caracteres. Guarde-as em um gerenciador de senhas. Gere uma senha com `python -c "import secrets; print(secrets.token_urlsafe(24))"`.

```text
python -m esferoides revisar --dados "../meu-experimento" --sessao "./dados/validacao-cega"
```

Acesse [Validação Cega](http://127.0.0.1:7860/validacao/). O perfil administrador pode preparar a sessão vazia, acompanhar o progresso e exportar. O perfil avaliador pode abrir e anotar as imagens codificadas. Para uso na rede local, `--rede` abre o serviço na LAN. Compartilhe apenas o endereço da validação e a senha desse perfil pelo canal privado da pesquisa. O token do revisor dá acesso às fotos originais e às decisões. Use `--cookie-seguro` quando servir a aplicação por trás de HTTPS.

## Anotar e exportar

1. Abra **Silhueta externa** e desenhe o contorno com polígono ou pincel.
2. Na camada **Regiões internas**, marque o fundo contido na silhueta. A máscara segmentada usa a silhueta após subtrair essas regiões.
3. Registre ambiguidades. Use **Concluir imagem** ou **Marcar como não avaliável** com justificativa.
4. Depois de concluir a fila, use **Encerrar avaliação** como administrador. A sessão encerrada preserva as versões finais e libera o relatório.
5. Em **Exportar validação cega**, obtenha o ZIP com CSVs, máscaras, HTML, gráficos e proveniência. O ZIP contém a chave reservada. Armazene-o como dado privado.

## Métricas de concordância

Sejam $O$ a máscara oficial e $H$ a máscara humana, na mesma grade. O relatório compara as máscaras segmentadas e, separadamente, as silhuetas preenchidas. Para cada comparação, exporta:

```math
\mathrm{Dice}=\frac{2|O\cap H|}{|O|+|H|},\qquad
\mathrm{IoU}=\frac{|O\cap H|}{|O\cup H|}.
```

```math
\Delta A=A_H-A_O,\qquad
\mathrm{erro\ relativo}\,[\%]=100\,\frac{|A_H-A_O|}{A_O}.
```

Denominadores nulos produzem medidas ausentes. Para os descritores da máscara, a área é a soma dos pixels, o perímetro externo usa a silhueta preenchida, a circularidade vale $4\pi A/P_{\mathrm{externo}}^2$ e a solidez vale $A/A_{\mathrm{convexa}}$. A diferença absoluta para uma medida $x$ é $|x_H-x_O|$.

O gráfico de Bland–Altman usa a média do par $(A_H+A_O)/2$ no eixo horizontal e $d=A_H-A_O$ no vertical. O viés é a média $\bar d$ e os limites descritivos são $\bar d\pm1{,}96s_d$, com desvio padrão amostral $s_d$. Os limites são calculados quando há pelo menos dois pares. O resumo estratificado traz número de pares válidos, mediana, Q1 e Q3. [Código do relatório](../src/esferoides/revisor/validacao_relatorio.py).
