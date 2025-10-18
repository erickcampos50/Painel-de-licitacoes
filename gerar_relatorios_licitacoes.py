import csv
import sqlite3
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

DB_PATH = Path("database_licitacoes.db")
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


def sanitize_inline_value(value: Any) -> str:
    if value is None:
        return ""
    sanitized = sanitize_text(str(value))
    return " ".join(sanitized.split())


def sanitize_filename(text: str) -> str:
    allowed = "-_.abcdefghijklmnopqrstuvwxyz0123456789"
    base = "".join(ch.lower() if ch.lower() in allowed else "-" for ch in text)
    while "--" in base:
        base = base.replace("--", "-")
    return base.strip("-") or "licitacao"


def escape_html(text: Any) -> str:
    sanitized = sanitize_text(str(text))
    return sanitized.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def escape_table_text(text: Any) -> str:
    inline = sanitize_inline_value(text)
    if inline == "":
        return ""
    return escape_html(inline).replace("|", "&#124;")


def escape_table_multiline(text: Any) -> str:
    return escape_table_text(text)


def escape_markdown_link_text(text: Any) -> str:
    sanitized = sanitize_text(str(text)).strip()
    return (
        sanitized.replace("\\", "\\\\")
        .replace("[", "\\[")
        .replace("]", "\\]")
        .replace("(", "\\(")
        .replace(")", "\\)")
    )


def parse_attachment_title(raw_title: Optional[str]) -> Tuple[str, List[str]]:
    if not raw_title:
        return "", []
    cleaned = sanitize_text(str(raw_title))
    root = cleaned
    attachments: List[str] = []
    if "|" in cleaned:
        root_part, remainder = cleaned.split("|", 1)
        root = root_part.strip()
        remainder = remainder.strip()
        if remainder:
            attachments = [
                sanitize_inline_value(segment)
                for segment in remainder.split(";")
                if sanitize_inline_value(segment)
            ]
    else:
        root = cleaned.strip()
    return sanitize_inline_value(root), attachments


def build_attachment_tree(root: str, attachments: List[str]) -> Dict[str, Dict[str, Any]]:
    tree: Dict[str, Dict[str, Any]] = {}

    def insert_path(target: Dict[str, Dict[str, Any]], parts: List[str]) -> None:
        node = target
        for part in parts:
            node = node.setdefault(part, {})

    if root:
        tree[root] = {}
        base_node = tree[root]
    else:
        base_node = tree

    for raw_path in attachments:
        parts = [
            sanitize_inline_value(segment)
            for segment in raw_path.split("/")
            if sanitize_inline_value(segment)
        ]
        if not parts:
            continue
        insert_path(base_node, parts)

    if root and root not in tree:
        tree[root] = {}
    return tree


def render_attachment_tree(tree: Dict[str, Dict[str, Any]]) -> str:
    def render_children(children: Dict[str, Dict[str, Any]]) -> str:
        if not children:
            return ""
        items = sorted(children.items(), key=lambda itm: itm[0].casefold())
        parts: List[str] = ["<ul>"]
        for name, child in items:
            safe_name = escape_html(name)
            parts.append("<li>")
            parts.append(safe_name or "-")
            nested = render_children(child)
            if nested:
                parts.append(nested)
            parts.append("</li>")
        parts.append("</ul>")
        return "".join(parts)

    return render_children(tree)


def build_attachment_tree_markup(root: str, attachments: List[str]) -> str:
    tree = build_attachment_tree(root, attachments)
    markup = render_attachment_tree(tree)
    return markup


def build_items_markup(items: List[Tuple[str, str]]) -> str:
    if not items:
        return "-"
    parts = ["<ul>"]
    for desc, valor in items:
        desc_text = sanitize_inline_value(desc)
        valor_text = sanitize_inline_value(valor)
        safe_desc = escape_html(desc_text) if desc_text else "-"
        safe_valor = escape_html(valor_text) if valor_text else "-"
        parts.append(f"<li>{safe_desc} - {safe_valor}</li>")
    parts.append("</ul>")
    return "".join(parts)


def sanitize_tag_text(text: Any) -> str:
    return sanitize_inline_value(text)


def escape_yaml(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


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
    lines.append("| Seq. | Arquivo | Conteudo | Status | Link | Conversão |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for arq in arquivos:
        seq = arq["sequencial_documento"]
        raw_title = arq["titulo"] if "titulo" in arq.keys() else None
        root_title, attachments = parse_attachment_title(raw_title)
        titulo_base = root_title or (arq["titulo"] or "-")
        titulo_limpo = sanitize_inline_value(titulo_base) or "-"
        titulo_cell = escape_table_text(titulo_limpo)

        conteudo_cell = "-"
        if attachments:
            conteudo_cell = build_attachment_tree_markup(root_title or titulo_limpo, attachments) or "-"

        status_label = "Ativo" if arq["status_ativo"] else "Inativo"
        status_cell = escape_table_text(status_label)

        link_value = arq["url"] or ""
        link_cell = f"[link]({link_value})" if link_value else "-"

        conversao = "OK" if arq["convertido_com_sucesso"] else "Falha"
        if arq["convertido_com_sucesso"] is None:
            conversao = "Não processado"
        conversao_cell = escape_table_text(conversao)
        lines.append(f"| {seq} | {titulo_cell} | {conteudo_cell} | {status_cell} | {link_cell} | {conversao_cell} |")
    lines.append("")
    lines.append("> *Aviso sobre anexos: As listas e o conteúdo textual abaixo foram obtidos por conversão automática dos arquivos originais através da ferramenta Markitdown. Podem existir diferenças em relação ao conteúdo dos documentos oficiais, utilize sempre as versões disponíveis no PNCP para conferência.*")
    lines.append("")

    for arq in arquivos:
        seq = arq["sequencial_documento"]
        titulo = sanitize_inline_value(arq["titulo"] or f"Documento {seq}") or f"Documento {seq}"
        lines.append(f"### Documento {seq}: {primary_document_title(titulo)}")
        lines.append("")
        if arq["url"]:
            link_text = escape_markdown_link_text(arq["url"])
            url_display = f"[{link_text}]({arq['url']})"
        else:
            url_display = "-"
        lines.append(f"- URL: {url_display}")
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
    # Ajusta rotas antigas para o novo segmento esperado.
    item_url = item_url.replace("/compras/", "/editais/")
    if item_url.startswith("http://") or item_url.startswith("https://"):
        return item_url
    base = "https://pncp.gov.br/app"
    return f"{base}{item_url}"


def primary_document_title(titulo: str) -> str:
    if " | " in titulo:
        return titulo.split(" | ", 1)[0]
    return titulo


def build_tags(lic: sqlite3.Row, itens: List[sqlite3.Row], arquivos: List[sqlite3.Row]) -> List[str]:
    tags: List[str] = []
    for key, label in LICITACAO_FIELDS:
        raw_value = format_value(key, lic[key])
        if not raw_value or raw_value == "-":
            continue
        tag = sanitize_tag_text(f"{label}: {raw_value}")
        if tag and tag not in tags:
            tags.append(tag)

    for item in itens:
        descricao = item["descricao"] if "descricao" in item.keys() else None
        desc_tag = sanitize_tag_text(descricao) if descricao else ""
        if desc_tag and desc_tag not in tags:
            tags.append(desc_tag)

    for arq in arquivos:
        raw_title = arq["titulo"] if "titulo" in arq.keys() else None
        root, attachments = parse_attachment_title(raw_title)

        root_tag = sanitize_tag_text(root) if root else ""
        if root_tag and root_tag not in tags:
            tags.append(root_tag)

        for attachment in attachments:
            full_tag = sanitize_tag_text(attachment)
            if full_tag and full_tag not in tags:
                tags.append(full_tag)
            base_name = sanitize_tag_text(attachment.split("/")[-1])
            if base_name and base_name not in tags:
                tags.append(base_name)
    return tags


def build_front_matter(lic: sqlite3.Row, itens: List[sqlite3.Row], arquivos: List[sqlite3.Row]) -> str:
    identifier = lic["numero_controle_pncp"] or lic["numero"] or lic["id"]
    title_text = sanitize_tag_text(f"Licitação {identifier}")
    slug = sanitize_filename(str(identifier))
    tags = build_tags(lic, itens, arquivos)

    lines = ["---", f'title: "{escape_yaml(title_text)}"', f'slug: "{escape_yaml(slug)}"']

    data_publicacao = lic["data_publicacao_pncp"] if "data_publicacao_pncp" in lic.keys() else None
    if data_publicacao:
        lines.append(f'date: "{escape_yaml(sanitize_tag_text(data_publicacao))}"')

    data_atualizacao = lic["data_atualizacao_pncp"] if "data_atualizacao_pncp" in lic.keys() else None
    if data_atualizacao:
        lines.append(f'lastmod: "{escape_yaml(sanitize_tag_text(data_atualizacao))}"')

    if tags:
        lines.append("tags:")
        for tag in tags:
            lines.append(f'  - "{escape_yaml(tag)}"')

    lines.append("---")
    lines.append("")
    return "\n".join(lines)


def build_document(lic: sqlite3.Row, itens: List[sqlite3.Row], arquivos: List[sqlite3.Row]) -> str:
    sections = [
        build_front_matter(lic, itens, arquivos),
        build_header(lic),
        build_info_table(lic),
        build_itens_section(itens),
        build_arquivos_section(arquivos),
    ]
    return "\n".join(section for section in sections if section.strip())


def build_attachment_table(entries: List[Dict[str, Any]]) -> str:
    lines = [
        "| Licitacao | Detalhes | Orgao | Descricao | Objeto | Arquivo | Conteudo | Link | Status | Itens |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]

    sorted_entries = sorted(
        entries,
        key=lambda item: (
            item["orgao"].casefold() if item["orgao"] else "",
            item["identifier"],
            item["arquivo"].casefold() if item["arquivo"] else "",
        ),
    )

    for entry in sorted_entries:
        identifier_cell = escape_table_text(entry["identifier"])
        detalhes_cell = f"[Abrir relatorio]({entry['report_path']})"
        orgao_cell = escape_table_text(entry["orgao"]) if entry["orgao"] else "-"
        descricao_cell = escape_table_multiline(entry["descricao"]) if entry.get("descricao") else "-"
        objeto_cell = escape_table_multiline(entry["objeto"]) if entry.get("objeto") else "-"
        arquivo_cell = escape_table_text(entry["arquivo"]) if entry["arquivo"] else "-"

        conteudo_cell = "-"
        if entry["conteudo"]:
            conteudo_cell = build_attachment_tree_markup(entry["arquivo"], entry["conteudo"]) or "-"

        link_target = entry["url"]
        link_cell = f"[download]({link_target})" if link_target else "-"

        status_cell = escape_table_text(entry["status"]) if entry["status"] else "-"
        itens_cell = build_items_markup(entry["itens"]) if entry.get("itens") else "-"

        lines.append(
            f"| {identifier_cell} | {detalhes_cell} | {orgao_cell} | {descricao_cell} | {objeto_cell} | {arquivo_cell} | {conteudo_cell} | {link_cell} | {status_cell} | {itens_cell} |"
        )

    if len(lines) == 2:
        lines.append("| - | - | - | - | - | - | - | - | - | - |")

    return "\n".join(lines)


def build_attachments_overview(entries: List[Dict[str, Any]]) -> str:
    table = build_attachment_table(entries)
    lines = [
        "---",
        'title: "Arquivos disponiveis"',
        'slug: "arquivos-disponiveis"',
        "---",
        "",
        "# Arquivos disponiveis",
        "",
        "Lista consolidada de anexos das licitacoes gerada automaticamente.",
        "",
        "[Baixar CSV](arquivos.csv)",
        "",
        table,
        "",
        "> *Atualizado automaticamente a partir dos dados mais recentes do PNCP.*",
        "",
    ]
    return "\n".join(lines)


def build_home_page(entries: List[Dict[str, Any]]) -> str:
    table = build_attachment_table(entries)
    lines = [
        "---",
        'title: "Painel de Licitacoes"',
        "---",
        "",
        "# Painel de Licitacoes",
        "",
        "Centralize licitacoes, anexos e atualizacoes do PNCP em um unico lugar.",
        "",
        "## Como buscar",
        "",
        "- Use a lupa do topo para localizar termos, CNPJs ou numeros PNCP.",
        "- Clique nas tags exibidas na barra lateral para refinar rapidamente os resultados.",
        "- Ao abrir um relatorio, utilize `Ctrl+F` ou `Cmd+F` para encontrar trechos especificos.",
        "",
        "[Baixar tabela completa (CSV)](arquivos.csv)",
        "",
        "## Arquivos disponiveis",
        "",
        table,
        "",
        "> *As informacoes sao atualizadas periodicamente a partir dos dados publicos do PNCP.*",
        "",
    ]
    return "\n".join(lines)


def write_attachments_csv(path: Path, entries: List[Dict[str, Any]]) -> None:
    headers = [
        "Licitacao",
        "Relatorio",
        "Orgao",
        "Descricao",
        "Objeto",
        "Arquivo",
        "Conteudo",
        "Link",
        "Status",
        "Itens",
    ]

    sorted_entries = sorted(
        entries,
        key=lambda item: (
            item["orgao"].casefold() if item["orgao"] else "",
            item["identifier"],
            item["arquivo"].casefold() if item["arquivo"] else "",
        ),
    )

    with path.open("w", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(headers)

        for entry in sorted_entries:
            to_csv_text = lambda value: sanitize_tag_text(value) if value else ""

            conteudo = "; ".join(to_csv_text(item) for item in entry["conteudo"]) if entry["conteudo"] else ""
            itens = "; ".join(
                f"{to_csv_text(descricao)} ({to_csv_text(valor)})"
                for descricao, valor in entry.get("itens", [])
                if descricao or valor
            )

            writer.writerow(
                [
                    to_csv_text(entry["identifier"]),
                    to_csv_text(entry["report_path"]),
                    to_csv_text(entry["orgao"]),
                    to_csv_text(entry.get("descricao", "")),
                    to_csv_text(entry.get("objeto", "")),
                    to_csv_text(entry["arquivo"]),
                    conteudo,
                    entry["url"],
                    to_csv_text(entry["status"]),
                    itens,
                ]
            )


def document_filename(lic: sqlite3.Row) -> Path:
    identifier = lic["numero_controle_pncp"] or lic["numero"] or lic["id"]
    slug = sanitize_filename(str(identifier))
    return OUTPUT_DIR / f"{slug}.md"


def save_document(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def generate_documents() -> None:
    ensure_output_dir()
    conn = connect_db()
    attachments_entries: List[Dict[str, Any]] = []
    try:
        for lic in fetch_licitacoes(conn):
            itens = fetch_itens(conn, lic["id"])
            arquivos = fetch_arquivos(conn, lic["id"])
            markdown = build_document(lic, itens, arquivos)
            output_path = document_filename(lic)
            save_document(output_path, markdown + "\n")

            identifier = lic["numero_controle_pncp"] or lic["numero"] or lic["id"]
            orgao = sanitize_inline_value(lic["orgao_nome"]) or "-"

            descricao_base = lic["title"] or ""
            if not descricao_base and lic["description"]:
                descricao_base = sanitize_text(str(lic["description"])).split("\n", 1)[0]
            descricao = sanitize_inline_value(descricao_base)

            for arq in arquivos:
                raw_title = arq["titulo"] if "titulo" in arq.keys() else None
                root_title, attachments = parse_attachment_title(raw_title)
                seq = arq["sequencial_documento"]
                nome_arquivo_base = root_title or sanitize_text(str(raw_title or f"Documento {seq}")).strip()
                nome_arquivo = sanitize_inline_value(nome_arquivo_base) or "-"
                status_label = "Ativo" if arq["status_ativo"] else "Inativo"

                item_resumo = [
                    (
                        sanitize_inline_value(item["descricao"]) or "-",
                        sanitize_inline_value(format_currency(item["valor_total"])) or "-",
                    )
                    for item in itens
                ]

                conteudo_limpo = [
                    sanitize_inline_value(segment)
                    for segment in attachments
                    if sanitize_inline_value(segment)
                ]

                attachments_entries.append(
                    {
                        "identifier": str(identifier),
                        "report_path": output_path.name,
                        "orgao": orgao,
                        "descricao": descricao,
                        "objeto": sanitize_inline_value(lic["description"]),
                        "arquivo": nome_arquivo,
                        "status": status_label,
                        "url": arq["url"] or "",
                        "conteudo": conteudo_limpo,
                        "itens": item_resumo,
                    }
                )
    finally:
        conn.close()

    home_path = OUTPUT_DIR / "index.md"
    home_content = build_home_page(attachments_entries)
    save_document(home_path, home_content + "\n")

    overview_path = OUTPUT_DIR / "arquivos.md"
    overview_content = build_attachments_overview(attachments_entries)
    save_document(overview_path, overview_content + "\n")

    csv_path = OUTPUT_DIR / "arquivos.csv"
    write_attachments_csv(csv_path, attachments_entries)


if __name__ == "__main__":
    generate_documents()
