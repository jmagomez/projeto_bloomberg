# Pipeline ETL de Ações — "Sua Própria Bloomberg"

Pipeline de dados que coleta cotações diárias de uma ação da B3 (ex.: PETR4), trata os dados e os carrega em um banco SQLite, na arquitetura medalhão (raw → silver → gold).

## Estrutura

```
projeto_bloomberg/
├── scripts/
│   ├── extract_petr4.py      # baixa cotações da API Alpha Vantage -> data/raw/*.json
│   ├── transform_petr4.py    # limpa e padroniza -> data/silver/*.csv
│   ├── load_petr4.py         # carrega no SQLite -> data/gold/petr4.db
│   ├── query_petr4.py        # consulta o banco e imprime análises
│   └── run_etl_pipeline.py   # executa extract -> transform -> load -> query
├── data/
│   ├── raw/     # dados brutos (JSON) — inclui um arquivo de exemplo
│   ├── silver/  # dados tratados (CSV)
│   └── gold/    # banco de dados (SQLite)
├── index.html   # dashboard interativo (GitHub Pages)
├── .env.example
└── requirements.txt
```

## Como rodar

1. Instale as dependências:
   ```
   pip install -r requirements.txt
   ```

2. **(Opcional) Para coletar dados novos**, obtenha uma chave gratuita da [Alpha Vantage](https://www.alphavantage.co/support/#api-key), copie `.env.example` para `.env` e preencha `ALPHA_VANTAGE_API_KEY`. Depois rode o pipeline completo:
   ```
   cd scripts
   python run_etl_pipeline.py
   ```

3. **Para testar sem chave de API**, o projeto já inclui um arquivo de dados brutos de exemplo em `data/raw/`. Basta rodar as etapas a partir do transform:
   ```
   python scripts/transform_petr4.py
   python scripts/load_petr4.py
   python scripts/query_petr4.py
   ```

## Dashboard

O `index.html` mostra os dados tratados em um dashboard interativo (preço, volume, variação diária). Publicado via GitHub Pages.
