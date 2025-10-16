import sqlite3
from pathlib import Path
from typing import Any, Iterable, List, Optional

DB_PATH = Path("database_licitacoes_hospitais.db")
OUTPUT_DIR = Path("relatorios_licitacoes")

LICITACAO_FIELDS: List[tuple[str, str]] = [
    ("numero_controle_pncp", "Número PNCP"),
    ("numero", "Número do Processo"),
    ("ano", "Ano"),
    ("modalidade_licitacao_nome", "Modalidade"),
    ("orgao_nome", "Órgão"),
    ("orgao_cnpj", "CNPJ do Órgão"),
    ("esfera_nome", "Esfera"),
    ("municipio_nome", "Município"),
    ("uf", "UF"),
    ("situacao_nome", "Situação"),
    ("valor_global", "Valor Global"),
    ("data_publicacao_pncp", "Data Publicação PNCP"),
    ("data_atualizacao_pncp", "Data Atualização PNCP"),
    ("data_assinatura", "Data Assinatura"),
    ("data_inicio_vigencia", "Início Vigência"),
    ("data_fim_vigencia", "Fim Vigência"),
    ("tem_resultado", "Tem Resultado"),
    ("cancelado", "Cancelado"),
]


def ensure_output_dir() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def connect_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def format_bool(value: Any) -> str:
    if value in (None, ""):
        return "-"
    if isinstance(value, bool):
        return "Sim" if value else "Não"
    if str(value).lower() in {"true", "1"}:
        return "Sim"
    if str(value).lower() in {"false", "0"}:
        return "Não"
    return str(value)


def format_currency(value: Any) -> str:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return str(value) if value not in (None, "") else "-"
    return f"R$ {num:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def format_value(key: str, value: Any) -> str:
    if value in (None, ""):
        return "-"
    if key == "valor_global":
        return format_currency(value)
    if key in {"tem_resultado", "cancelado"}:
        return format_bool(value)
    return str(value)


def sanitize_text(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def sanitize_filename(text: str) -> str:
    allowed = "-_.abcdefghijklmnopqrstuvwxyz0123456789"
    base = "".join(ch.lower() if ch.lower() in allowed else "-" for ch in text)
    while "--" in base:
        base = base.replace("--", "-")
    return base.strip("-") or "licitacao"


def fetch_licitacoes(conn: sqlite3.Connection) -> Iterable[sqlite3.Row]:
    query = """
        SELECT id, title, description, item_url, numero, ano, numero_controle_pncp,
               modalidade_licitacao_nome, orgao_nome, orgao_cnpj, esfera_nome,
               municipio_nome, uf, situacao_nome, valor_global,
               data_publicacao_pncp, data_atualizacao_pncp,
               data_assinatura, data_inicio_vigencia, data_fim_vigencia,
               tem_resultado, cancelado
        FROM licitacoes
        ORDER BY data_publicacao_pncp DESC
    """
    return conn.execute(query)


def fetch_itens(conn: sqlite3.Connection, lic_id: str) -> List[sqlite3.Row]:
    query = """
        SELECT numeroItem, descricao, valor_total
        FROM itens
        WHERE id_licitacao = ?
        ORDER BY numeroItem
    """
    return conn.execute(query, (lic_id,)).fetchall()


def fetch_arquivos(conn: sqlite3.Connection, lic_id: str) -> List[sqlite3.Row]:
    query = """
        SELECT a.sequencial_documento,
               a.titulo,
               a.url,
               a.status_ativo,
               m.conteudo_markdown,
               m.convertido_com_sucesso,
               m.erro
        FROM arquivos a
        LEFT JOIN arquivo_markdown m
          ON m.id_licitacao = a.id_licitacao
         AND m.sequencial_documento = a.sequencial_documento
        WHERE a.id_licitacao = ?
        ORDER BY a.sequencial_documento
    """
    return conn.execute(query, (lic_id,)).fetchall()


def build_header(lic: sqlite3.Row) -> str:
    numero = lic["numero"] or lic["numero_controle_pncp"] or lic["id"]
    title = lic["title"] or ""
    lines = [f"# Licitação {numero}", ""]

    link_pncp = build_pncp_link(lic)
    lines.append("> **Aviso:** Este relatório é gerado automaticamente a partir de dados públicos do PNCP.")
    lines.append("> **Responsabilidade:** É de total responsabilidade do interessado validar todas as informações diretamente na fonte oficial antes de utilizá-las.")
    if link_pncp:
        lines.append(f"> [Acessar licitação no PNCP]({link_pncp})")
    lines.append("")

    if title:
        lines.append(f"_{sanitize_text(title).strip()}_")
        lines.append("")
    if lic["description"]:
        lines.append("## Descrição")
        lines.append("")
        lines.append(sanitize_text(lic["description"]).strip())
        lines.append("")
    return "\n".join(lines)


def build_info_table(lic: sqlite3.Row) -> str:
    lines = ["## Dados Principais", ""]
    lines.append("| Campo | Valor |")
    lines.append("| --- | --- |")
    for key, label in LICITACAO_FIELDS:
        value = format_value(key, lic[key])
        lines.append(f"| {label} | {value} |")
    lines.append("")
    return "\n".join(lines)


def build_itens_section(itens: List[sqlite3.Row]) -> str:
    if not itens:
        return ""
    lines = ["## Itens", ""]
    lines.append("| Item | Descrição | Valor Total |")
    lines.append("| --- | --- | --- |")
    for item in itens:
        num = item["numeroItem"] if item["numeroItem"] is not None else "-"
        desc = sanitize_text(item["descricao"] or "-").replace("\n", "<br>")
        valor = format_currency(item["valor_total"])
        lines.append(f"| {num} | {desc} | {valor} |")
    lines.append("")
    return "\n".join(lines)


def build_arquivos_section(arquivos: List[sqlite3.Row]) -> str:
    if not arquivos:
        return ""
    lines = ["## Documentos Anexos", ""]
    lines.append("| Seq. | Título | Status | Link | Conversão |")
    lines.append("| --- | --- | --- | --- | --- |")
    for arq in arquivos:
        seq = arq["sequencial_documento"]
        titulo = sanitize_text(arq["titulo"] or "-").replace("\n", "<br>")
        status = "Ativo" if arq["status_ativo"] else "Inativo"
        link = arq["url"] or "-"
        conversao = "OK" if arq["convertido_com_sucesso"] else "Falha"
        if arq["convertido_com_sucesso"] is None:
            conversao = "Não processado"
        lines.append(f"| {seq} | {titulo} | {status} | [link]({link}) | {conversao} |")
    lines.append("")
    lines.append("> *Aviso sobre anexos: As listas e o conteúdo textual abaixo foram obtidos por conversão automática dos arquivos originais (principalmente PDFs). Podem existir diferenças em relação aos documentos oficiais; utilize sempre as versões disponíveis no PNCP para conferência.*")
    lines.append("")

    for arq in arquivos:
        seq = arq["sequencial_documento"]
        titulo = sanitize_text(arq["titulo"] or f"Documento {seq}")
        lines.append(f"### Documento {seq}: {primary_document_title(titulo)}")
        lines.append("")
        lines.append(f"- URL: {arq['url'] or '-'}")
        status = "Ativo" if arq["status_ativo"] else "Inativo"
        lines.append(f"- Status: {status}")
        conversao = "Sucesso" if arq["convertido_com_sucesso"] else "Falha"
        if arq["convertido_com_sucesso"] is None:
            conversao = "Não processado"
        lines.append(f"- Conversão: {conversao}")
        if arq["erro"]:
            lines.append(f"- Erro: {sanitize_text(arq['erro']).strip()}")
        lines.append("")
        if arq["conteudo_markdown"]:
            lines.append("#### Conteúdo convertido")
            lines.append("")
            lines.append(sanitize_text(arq["conteudo_markdown"]).strip())
            lines.append("")
    return "\n".join(lines)


def build_pncp_link(lic: sqlite3.Row) -> Optional[str]:
    if "item_url" not in lic.keys():
        return None
    item_url = lic["item_url"]
    if not item_url:
        return None
    if item_url.startswith("http://") or item_url.startswith("https://"):
        return item_url
    base = "https://pncp.gov.br/app"
    return f"{base}{item_url}"


def primary_document_title(titulo: str) -> str:
    if " | " in titulo:
        return titulo.split(" | ", 1)[0]
    return titulo


def build_document(lic: sqlite3.Row, itens: List[sqlite3.Row], arquivos: List[sqlite3.Row]) -> str:
    sections = [
        build_header(lic),
        build_info_table(lic),
        build_itens_section(itens),
        build_arquivos_section(arquivos),
    ]
    return "\n".join(section for section in sections if section.strip())


def document_filename(lic: sqlite3.Row) -> Path:
    identifier = lic["numero_controle_pncp"] or lic["numero"] or lic["id"]
    slug = sanitize_filename(str(identifier))
    return OUTPUT_DIR / f"{slug}.md"


def save_document(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def generate_documents() -> None:
    ensure_output_dir()
    conn = connect_db()
    try:
        for lic in fetch_licitacoes(conn):
            itens = fetch_itens(conn, lic["id"])
            arquivos = fetch_arquivos(conn, lic["id"])
            markdown = build_document(lic, itens, arquivos)
            save_document(document_filename(lic), markdown + "\n")
    finally:
        conn.close()


if __name__ == "__main__":
    generate_documents()
