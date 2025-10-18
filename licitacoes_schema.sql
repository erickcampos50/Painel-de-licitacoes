CREATE TABLE IF NOT EXISTS licitacoes (
    id TEXT PRIMARY KEY,
    "index" TEXT,
    doc_type TEXT,
    title TEXT,
    description TEXT,
    item_url TEXT,
    document_type TEXT,
    createdAt DATETIME,
    numero TEXT,
    ano INTEGER,
    numero_sequencial INTEGER,
    numero_sequencial_compra_ata INTEGER,
    numero_controle_pncp TEXT,
    orgao_id TEXT,
    orgao_cnpj TEXT,
    orgao_nome TEXT,
    orgao_subrogado_id TEXT,
    orgao_subrogado_nome TEXT,
    unidade_id TEXT,
    unidade_codigo TEXT,
    unidade_nome TEXT,
    esfera_id TEXT,
    esfera_nome TEXT,
    poder_id TEXT,
    poder_nome TEXT,
    municipio_id TEXT,
    municipio_nome TEXT,
    uf TEXT,
    modalidade_licitacao_id TEXT,
    modalidade_licitacao_nome TEXT,
    situacao_id TEXT,
    situacao_nome TEXT,
    data_publicacao_pncp DATETIME,
    data_atualizacao_pncp DATETIME,
    data_assinatura DATETIME,
    data_inicio_vigencia DATETIME,
    data_fim_vigencia DATETIME,
    cancelado BOOLEAN,
    valor_global REAL,
    tem_resultado BOOLEAN,
    tipo_id TEXT,
    tipo_nome TEXT,
    tipo_contrato_id TEXT,
    tipo_contrato_nome TEXT,
    fonte_orcamentaria_id TEXT,
    fonte_orcamentaria TEXT,
    fonte_orcamentaria_nome TEXT,
    exigencia_conteudo_nacional BOOLEAN,
    tipo_margem_preferencia TEXT,
    tipo_margem_preferencia_id TEXT,
    tipo_margem_preferencia_nome TEXT
);

CREATE INDEX IF NOT EXISTS idx_licitacoes_controle
  ON licitacoes(numero_controle_pncp);

CREATE TABLE IF NOT EXISTS itens (
    id_licitacao TEXT,
    numeroItem INTEGER,
    descricao TEXT,
    valor_total REAL,
    PRIMARY KEY (id_licitacao, numeroItem)
);

CREATE TABLE IF NOT EXISTS arquivos (
    id_licitacao TEXT,
    sequencial_documento INTEGER,
    url TEXT,
    titulo TEXT,
    status_ativo BOOLEAN,
    PRIMARY KEY (id_licitacao, sequencial_documento)
);

CREATE TABLE IF NOT EXISTS arquivo_markdown (
    id_licitacao TEXT,
    sequencial_documento INTEGER,
    nome_arquivo TEXT,
    conteudo_markdown TEXT,
    convertido_com_sucesso BOOLEAN,
    erro TEXT,
    timestamp TEXT,
    PRIMARY KEY(id_licitacao, sequencial_documento)
);
