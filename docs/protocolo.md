# Protocolo e fórmulas

O Spheroid Lab mede projeções 2D. Áreas são expressas em **px²**, comprimentos em **px** e índices de forma são adimensionais.

## Segmentação

Para a imagem em cinza $I$ e o filtro gaussiano $G_\sigma$, o fundo $B$, a imagem corrigida $F$ e o mapa de desvio $D$ são:

```math
B=G_{60}*I,\qquad F=\frac{I}{B+10^{-6}},\qquad D=G_3*|F-1|.
```

A máscara inicial é $`D>T_{\mathrm{Otsu}}`$. O algoritmo preenche vazios internos, remove componentes com menos de 15.000 px², aplica abertura com disco de raio 8 px e preenche vazios novamente. Registra a contagem de componentes e seleciona o maior componente conexo, $M_0$. A máscara final é:

```math
M=\mathrm{preencher}\left(\left[G_6*M_0>0{,}5\right]\right).
```

O traçado manual entra no pós-processamento com preenchimento, seleção do maior componente e a mesma suavização. No revisor, o mapa é convertido para 8 bits a partir do percentil 99,5. O controle usa $`\sigma_{\mathrm{fundo}}\in\{30,45,60,90,120,180\}`$ e deslocamento $\delta\in[-60,60]$:

```math
D_8=\left\lfloor255\,\mathrm{clip}\left(\frac{D}{\max(Q_{99{,}5}(D),10^{-9})},0,1\right)\right\rfloor,\qquad T_8=\mathrm{clip}\!\left(T_{\mathrm{Otsu}}(D_8)+\delta,1,254\right).
```

A quantização pode mudar o contorno mesmo com $\delta=0$. A medição em lote usa o mapa em ponto flutuante. Exposição e contraste da interface atuam na visualização. [Parâmetros](../src/esferoides/config.py) · [Segmentação](../src/esferoides/segmentacao.py).

## Medidas da máscara

$`M(x,y)\in\{0,1\}`$ indica os pixels da região medida, $P$ é o perímetro e $A_{\mathrm{convexa}}$ é a área do fecho convexo rasterizado. Os comprimentos $L$ e $l$ vêm da elipse de segundos momentos. Para os autovalores normalizados $\lambda_{\max}$ e $\lambda_{\min}$, valem $L=4\sqrt{\lambda_{\max}}$ e $l=4\sqrt{\lambda_{\min}}$.

| Métrica e coluna | Fórmula ou estimador | Interpretação |
|---|---|---|
| Área projetada, `area_px` | $A=\sum_{x,y}M(x,y)$ | Número de pixels da região, em px². |
| Perímetro, `perimetro_px` | `regionprops.perimeter` | Estimativa em px com conectividade 4, baseada nos centros dos pixels de borda. |
| Circularidade, `circularidade` | $\displaystyle C=\frac{4\pi A}{P^2}$ | Índice que combina área e perímetro. |
| Roundness, `roundness` | $\displaystyle R=\frac{4A}{\pi L^2}$ | Arredondamento em função do eixo maior. |
| Aspect ratio, `aspect_ratio` | $\displaystyle AR=\frac{L}{\max(l,1\ \mathrm{px})}$ | Alongamento da elipse de momentos. O código usa piso de 1 px no denominador de $L/l$. |
| Solidity geométrica, `solidity` | $\displaystyle S=\frac{A}{A_{\mathrm{convexa}}}$ | Fração ocupada do fecho convexo. |
| Diâmetro equivalente, `diam_equiv_px` | $\displaystyle D_{\mathrm{eq}}=2\sqrt{\frac{A}{\pi}}$ | Diâmetro, em px, do círculo com a mesma área projetada. |
| Feret máximo, `feret_max_px` | $\displaystyle F_{\max}=\max_{p,q\in\partial H}\left\Vert p-q\right\Vert_{2}$ | Maior distância em px entre pontos do contorno do fecho convexo $H$, estimado por `regionprops.feret_diameter_max`. |
| Eixo menor, `eixo_menor_px` | $l$ | Comprimento em px. O rótulo histórico `feret_min_px` é lido como eixo menor. MinFeret exige um estimador de calibre mínimo. |
| Circularidade sem suavização, `circularidade_sem_suavizar` | $\displaystyle C_0=\frac{4\pi A_0}{P_0^2}$ | A fórmula da circularidade no maior componente antes da suavização. |

`n_objetos` conta os componentes da máscara que chega à etapa de seleção. `toca_borda` vale 1 quando a caixa da região medida alcança um limite da imagem e 0 nos demais casos. [Código das medidas](../src/esferoides/medidas.py) · [Documentação de regionprops](https://scikit-image.org/docs/stable/api/skimage.measure.html#skimage.measure.regionprops).

## Séries temporais e resumos

Para o mesmo esferoide na mesma placa, com referência válida em D0, a coluna `area_norm_D0` é:

```math
A_{\mathrm{rel}}(t)=\frac{A_t}{A_{D0}}.
```

A aba **Resultados** usa apenas correções manuais e exige um D0 manual para a normalização. A triagem calcula variação relativa entre tempos disponíveis a partir de D1 e relata o percentual quando sinaliza um aumento:

```math
\Delta A(t_1,t_0)\,[\%]=100\,\frac{A_{t_{1}}-A_{t_{0}}}{A_{t_{0}}}.
```

O denominador deve ser positivo. Para tempos consecutivos, use $t_1=t$ e $t_0=t-1$. O CSV principal exporta as áreas e a área normalizada. Os gráficos mostram mediana e o intervalo de $Q_{25}$ a $Q_{75}$. O relatório de triagem também exporta médias e desvios padrão amostrais por grupo e dia. Separe as unidades biológicas independentes e mantenha o pareamento por esferoide em análises inferenciais.

## Vazios e comparação entre programas

No **revisor padrão**, área e perímetro vêm da mesma máscara final, após o preenchimento dos vazios. Na **Validação Cega**, a máscara segmentada humana pode subtrair regiões internas. Nesse caso, a área conta os pixels restantes e o perímetro externo vem da silhueta preenchida. A comparação por silhueta preenche as duas máscaras. [Fórmulas de concordância](validacao-cega.md#métricas-de-concordância).

A comparação numérica entre programas depende da máscara, do tratamento de vazios, do perímetro e dos eixos, dos componentes incluídos e da calibração. O diâmetro equivalente descreve a projeção 2D. Uma estimativa tridimensional exige dados ou hipóteses adicionais.

## Fórmulas de referência sem cálculo no aplicativo

**Mean Gray Value (MGV)** é a intensidade média dos $N$ pixels de uma região de interesse:

```math
MGV=\frac{1}{N}\sum_{i=1}^{N} I_i.
```

**Índice óptico normalizado (MGVi)** usa os extremos observados dentro de cada experimento biológico independente:

```math
{MGVi}_{i}=\frac{MGV_{\max}-MGV_i}{MGV_{\max}-MGV_{\min}}.
```

O índice varia de 0 a 1 quando o intervalo é positivo. Valores maiores correspondem a micrografias relativamente mais escuras sob condições de aquisição padronizadas. Um intervalo zero deixa o índice indefinido.

**Área calibrada** usa dimensões físicas verificadas para cada pixel, $s_x$ e $s_y$, em µm:

```math
A_{\mu\mathrm{m}^2}=N_{\mathrm{pixels}}\,s_x\,s_y.
```

**Liberação de LDH** usa as atividades do ensaio bioquímico em unidades comparáveis:

```math
LDH_{\mathrm{liberada}}\,[\%]=100\,\frac{LDH_{\mathrm{extra}}}{LDH_{\mathrm{extra}}+LDH_{\mathrm{intra}}}.
```

Essas quatro fórmulas são referências metodológicas externas ao CSV do aplicativo. [Artigo de referência, Molecular Biology Reports](https://link.springer.com/article/10.1007/s11033-026-12715-9).
