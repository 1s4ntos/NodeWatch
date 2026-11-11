"""Painel do analista: dataset → análise → investigação.

Módulos:
    score          conversão do score bruto do modelo para a escala 0–1000 e faixas
    datasets       envio seguro, catálogo e validação de datasets de transações
    tipologias     tipologias registradas no dataset (arquivo de padrões)
    armazenamento  resultados por transação em SQLite (filtros, página, contas, grafo)
    pipeline       execução da análise com etapas, progresso medido e manifesto
    sistema        medidas de desempenho e logs (sistema e ML)
    assistente     respostas locais e verificáveis (glossário e fatos da análise)

Nada aqui treina ou reajusta modelo: a pontuação usa o artefato salvo, com o
mesmo estado incremental do processamento de eventos (``src/ml/incremental``).
"""
