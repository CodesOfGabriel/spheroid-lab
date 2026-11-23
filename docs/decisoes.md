# Decisões de implementação

- A fila de conferência usa códigos estáveis para o mesmo conjunto e semente. A chave fica na pasta local. A galeria e as comparações por grupos podem revelar o delineamento. Use a Validação Cega quando a pessoa avaliadora precisar de acesso restrito às imagens codificadas.
- O revisor guarda o traçado original e aplica o pós-processamento ao medir. SQLite, diário e máscaras preservam as decisões. Os CSVs são saídas derivadas.
- A contagem de componentes após o filtro de área é um indicador de segmentação. Uma contagem de satélites exigiria uma definição operacional e validação próprias.
- A suavização usa uma escala fixa em pixels. A coluna `circularidade_sem_suavizar` ajuda a avaliar o efeito da etapa em objetos de tamanhos diferentes.
- A exposição e o contraste se aplicam à imagem exibida. Limiar e escala do fundo alteram a proposta de máscara.
- As saídas mantêm unidades em pixels. Registre a escala de aquisição e os estimadores antes de comparar ferramentas.

Veja o [protocolo e as fórmulas](protocolo.md).
