# Painel de Licitacoes

Projeto de coleta e tratamento de dados do Portal Nacional de Contratacoes Publicas (PNCP). O script principal realiza consultas assincornas na API oficial, persiste os resultados em um banco SQLite e realiza download de arquivos relacionados aos editais.

## Pre-requisitos

- Python 3.12 ou superior
- Acesso a internet para consultar a API do PNCP
- `sqlite3` instalado caso queira inspecionar o banco de dados gerado
- Opcional (Windows ou PowerShell 7+): utilitarios `curl` e `markitdown` CLI para usar o conversor de arquivos

## Configuracao rapida

1. Crie e ative um ambiente virtual:
   - Linux/macOS: `python3 -m venv .venv && source .venv/bin/activate`
   - Windows PowerShell: `python -m venv .venv ; .\.venv\Scripts\Activate.ps1`
2. Atualize o `pip` (opcional): `pip install --upgrade pip`
3. Instale as dependencias: `pip install -r requirements.txt`

O ambiente virtual criado em `.venv` nao deve ser versionado.

## Executando a coleta

1. Ajuste os parametros desejados no topo de `raspagem_dados_pncp_obras_hospitais.py` (consulta, pagina, modalidade, etc.).
2. Execute o coletor: `python raspagem_dados_pncp_obras_hospitais.py`
3. Os dados serao gravados em `database_licitacoes_2.db` no mesmo diretorio. O script cria automaticamente as tabelas `licitacoes`, `itens`, `arquivos` e `arquivo_markdown`.

O script utiliza `asyncio` e `aiohttp` para fazer requisicoes em paralelo respeitando pausas aleatorias configuraveis, e tenta baixar e inspecionar anexos dos editais. A biblioteca `markitdown` eh usada para tentar converter anexos para Markdown.

## Visualizacao dos relatorios com MkDocs

Com os arquivos Markdown em `relatorios_licitacoes/`, e possivel disponibilizar uma interface de consulta usando MkDocs:

1. Gere os relatorios atualizados: `python gerar_relatorios_licitacoes.py`.
2. Sirva o site localmente: `mkdocs serve`.
3. Acesse `http://127.0.0.1:8000/` para buscar, filtrar e navegar pelos relatorios.
4. A Home traz a lista consolidada de anexos com busca integrada; a pagina *Arquivos disponiveis* oferece a mesma tabela com links internos e downloads.

Os pacotes `mkdocs` e `mkdocs-material` estao listados em `requirements.txt`. Reinstale as dependencias se ja tiver configurado o ambiente anteriormente.

## Conversao de documentos (PowerShell)

O arquivo `conversor_para_markdown.py` contem um script PowerShell pensado para Windows. Ele faz leitura da tabela `arquivos`, baixa anexos pendentes e salva o resultado convertido em Markdown na tabela `arquivo_markdown`. Para usa-lo:

```powershell
pwsh ./conversor_para_markdown.py
```

Certifique-se de ter `sqlite3.exe`, `curl.exe` e o comando `markitdown` instalados no ambiente do PowerShell.

## Testes e verificacoes

Nao ha testes automatizados inclusos. Uma verificacao rapida de sintaxe pode ser feita com:

```bash
python -m compileall raspagem_dados_pncp_obras_hospitais.py
```

Recomenda-se criar tarefas de teste que validem integracoes com o banco e a API conforme o projeto evoluir.

## Estrutura principal

- `raspagem_dados_pncp_obras_hospitais.py`: coletor principal que consulta a API do PNCP e armazena os dados.
- `conversor_para_markdown.py`: script PowerShell para converter anexos em Markdown e registrar os resultados.
- `licitacoes_schema.sql`: schema inicial usado para criar as tabelas do banco SQLite.
- `requirements.txt`: lista de dependencias Python.
