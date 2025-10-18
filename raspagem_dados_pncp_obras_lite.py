import io
import json
import random
import re
import sqlite3
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Set, Tuple
from urllib.parse import unquote, urlparse

import requests
from markitdown import MarkItDown

SEARCH_URL = "https://pncp.gov.br/api/search/"
BASE_PNCP = "https://pncp.gov.br/api/pncp/v1/orgaos/"
TIPOS_DOCUMENTO = ["edital"]
ORDENACAO = ["data"]
PAGES = list(range(1, 21))
TAM_PAGINA = 500
ESFERA = ""
QUERY = ""
MODALIDADE = "4"
DB_PATH = "database_licitacoes.db"
SCHEMA_PATH = Path(__file__).with_name("licitacoes_schema.sql")
HTTP_TIMEOUT = 60
REQUEST_DELAY_MIN = 0.1
REQUEST_DELAY_MAX = 0.4
MAX_ZIP_DEPTH = 3


def now() -> datetime:
    return datetime.now(timezone.utc)


def log(msg: str) -> None:
    print(f"[{now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}")


def random_pause() -> None:
    if REQUEST_DELAY_MAX <= 0:
        return
    low = max(0.0, min(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX))
    high = max(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX)
    time.sleep(random.uniform(low, high))


def resolve_readable_title(url: str) -> Tuple[str, bool]:
    content_disposition = ""
    content_type = ""
    try:
        random_pause()
        resp = requests.head(url, allow_redirects=True, timeout=10)
        content_disposition = resp.headers.get("Content-Disposition", "") or ""
        content_type = resp.headers.get("Content-Type", "") or ""
    except Exception as exc:
        log(f"HEAD metadata falhou para {url}: {exc}")

    filename_match = None
    if content_disposition:
        filename_match = re.search(r'filename\*=.*?\'\'([^;]+)', content_disposition)
        if filename_match:
            filename = unquote(filename_match.group(1))
            return filename, filename.lower().endswith(".zip")
        filename_match = re.search(r'filename="?([^";]+)"?', content_disposition)
        if filename_match:
            filename = filename_match.group(1)
            return filename, filename.lower().endswith(".zip")

    parsed = urlparse(url)
    fallback = unquote(parsed.path.split("/")[-1] or "arquivo")
    is_zip = fallback.lower().endswith(".zip") or "zip" in content_type.lower()
    return fallback, is_zip


def list_zip_contents(data: bytes, depth: int = 0, prefix: str = "") -> List[str]:
    if depth > MAX_ZIP_DEPTH:
        return []

    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            entries = []
            for info in zf.infolist():
                name = info.filename
                display = name if not prefix else f"{prefix}/{name}"
                entries.append(display)
                if not info.is_dir() and name.lower().endswith(".zip"):
                    if depth == MAX_ZIP_DEPTH:
                        continue
                    try:
                        nested_data = zf.read(info)
                    except Exception as exc:
                        log(f"LEITURA ZIP falhou para entrada {display}: {exc}")
                        continue
                    entries.extend(
                        list_zip_contents(
                            nested_data,
                            depth=depth + 1,
                            prefix=display.rstrip("/"),
                        )
                    )
            return entries
    except Exception as exc:
        log(f"LEITURA ZIP falhou: {exc}")
        return []


def collect_zip_members(url: str) -> List[str]:
    try:
        random_pause()
        resp = requests.get(url, timeout=HTTP_TIMEOUT)
        resp.raise_for_status()
    except Exception as exc:
        log(f"DOWNLOAD ZIP falhou para {url}: {exc}")
        return []
    return list_zip_contents(resp.content)


def enrich_arquivos_metadata(arquivos: List[Dict[str, Any]]) -> None:
    for arq in arquivos:
        url = arq.get("url")
        if not url:
            continue
        try:
            display_name, is_zip = resolve_readable_title(url)
            if is_zip:
                members = collect_zip_members(url)
                if members:
                    arq["titulo"] = f"{display_name} | " + "; ".join(members)
                else:
                    arq["titulo"] = display_name
            else:
                arq["titulo"] = display_name
        except Exception as exc:
            log(f"ERRO metadados arquivo {arq.get('sequencialDocumento')}: {exc}")


def init_db() -> None:
    if not SCHEMA_PATH.exists():
        raise FileNotFoundError(f"Arquivo de schema não encontrado: {SCHEMA_PATH}")
    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.executescript(schema_sql)
    conn.commit()
    conn.close()


def normalize_value(value: Any) -> Any:
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return value


def get_existing_ids() -> Set[str]:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM licitacoes")
    rows = {row[0] for row in cursor.fetchall()}
    conn.close()
    return rows


def persist_licitacoes(items: Iterable[Dict[str, Any]]) -> int:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    cursor = conn.cursor()
    inserted = 0
    for item in items:
        cols = list(item.keys())
        placeholders = ",".join("?" for _ in cols)
        cols_escaped = [f'"{col}"' if col.lower() == "index" else col for col in cols]
        values = [normalize_value(item[col]) for col in cols]
        cursor.execute(
            f"INSERT OR IGNORE INTO licitacoes ({','.join(cols_escaped)}) "
            f"VALUES ({placeholders})",
            values,
        )
        inserted += cursor.rowcount
    conn.commit()
    conn.close()
    return inserted


def persist_relations(
    lic_id: str,
    itens: Sequence[Dict[str, Any]],
    arquivos: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    cursor = conn.cursor()

    inserted_itens = 0
    for obj in itens:
        cursor.execute(
            """
            INSERT OR IGNORE INTO itens (id_licitacao, numeroItem, descricao, valor_total)
            VALUES (?,?,?,?)
            """,
            (lic_id, obj.get("numeroItem"), obj.get("descricao"), obj.get("valorTotal")),
        )
        inserted_itens += cursor.rowcount

    inserted_arquivos = 0
    markdown_targets: List[Tuple[str, int, str]] = []
    for arq in arquivos:
        cursor.execute(
            """
            INSERT OR IGNORE INTO arquivos
            (id_licitacao, sequencial_documento, url, titulo, status_ativo)
            VALUES (?,?,?,?,?)
            """,
            (
                lic_id,
                arq.get("sequencialDocumento"),
                arq.get("url"),
                arq.get("titulo"),
                arq.get("statusAtivo"),
            ),
        )
        if cursor.rowcount:
            seq_doc = arq.get("sequencialDocumento")
            url_val = arq.get("url")
            if seq_doc is not None and url_val:
                markdown_targets.append((lic_id, seq_doc, url_val))
        inserted_arquivos += cursor.rowcount

    conn.commit()
    conn.close()
    return {
        "inserted_itens": inserted_itens,
        "total_itens": len(itens),
        "inserted_arquivos": inserted_arquivos,
        "total_arquivos": len(arquivos),
        "markdown_targets": markdown_targets,
    }


def load_recovery_candidates() -> List[Tuple[Any, ...]]:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT
            l.id,
            l.orgao_cnpj,
            l.ano,
            l.numero_sequencial,
            (SELECT COUNT(*) FROM itens WHERE id_licitacao = l.id) AS n_itens,
            (SELECT COUNT(*) FROM arquivos WHERE id_licitacao = l.id) AS n_arquivos
        FROM licitacoes l
        """
    )
    rows = cursor.fetchall()
    conn.close()
    return rows


def convert_and_save_markdown_sync(lic_id: str, seq_doc: int, url: str) -> Tuple[bool, str]:
    try:
        cd = requests.head(url, allow_redirects=True, timeout=10).headers.get(
            "Content-Disposition", ""
        )
        fname_match = re.search(r'filename="?([^";]+)"?', cd or "")
        fname = fname_match.group(1) if fname_match else f"{lic_id}_{seq_doc}"
    except Exception:
        fname = f"{lic_id}_{seq_doc}"

    md = MarkItDown(enable_plugins=False)
    try:
        text = md.convert(url).text_content
        ok, err = True, ""
    except Exception as exc:
        text = "Não foi possível converter para markdown"
        ok, err = False, str(exc)

    conn = sqlite3.connect(DB_PATH, timeout=30)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT OR REPLACE INTO arquivo_markdown
        (id_licitacao, sequencial_documento, nome_arquivo, conteudo_markdown,
         convertido_com_sucesso, erro, timestamp)
        VALUES (?,?,?,?,?,?,?)
        """,
        (lic_id, seq_doc, fname, text, ok, err, now().isoformat()),
    )
    conn.commit()
    conn.close()
    return ok, err


def _fetch_search_page(params: Dict[str, Any]) -> List[Dict[str, Any]]:
    try:
        random_pause()
        resp = requests.get(SEARCH_URL, params=params, timeout=HTTP_TIMEOUT)
        if resp.status_code != 200:
            log(
                f"ERRO search pagina {params['pagina']} ({params['tipos_documento']} / {params['ordenacao']}): HTTP {resp.status_code}"
            )
            return []
        data = resp.json()
    except Exception as exc:
        log(
            f"ERRO search pagina {params['pagina']} ({params['tipos_documento']} / {params['ordenacao']}): {exc}"
        )
        return []

    items = data.get("items", [])
    log(
        f"SEARCH página {params['pagina']} ({params['tipos_documento']} / {params['ordenacao']}): {len(items)} itens"
    )
    return items


def fetch_search() -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    for ordem in ORDENACAO:
        for doc in TIPOS_DOCUMENTO:
            for pg in PAGES:
                params = {
                    "pagina": pg,
                    "tam_pagina": TAM_PAGINA,
                    "ordenacao": ordem,
                    "tipos_documento": doc,
                    "status": "todos",
                    "esferas": ESFERA,
                    "modalidades": MODALIDADE,
                    "q": QUERY,
                }
                results.extend(_fetch_search_page(params))
    return results


def _fetch_endpoint(
    url: str,
    params: Dict[str, Any],
    label: str,
    lic_id: str,
) -> List[Dict[str, Any]]:
    try:
        random_pause()
        resp = requests.get(url, params=params, timeout=HTTP_TIMEOUT)
        if resp.status_code != 200:
            log(f"ERRO {label} {lic_id}: HTTP {resp.status_code}")
            return []
        data = resp.json()
        if isinstance(data, list):
            return data
        return data.get("items", [])
    except Exception as exc:
        log(f"ERRO {label} {lic_id}: {exc}")
        return []


def fetch_itens(
    org: str, ano: int, seq: int, lic_id: str
) -> List[Dict[str, Any]]:
    url = f"{BASE_PNCP}{org}/compras/{ano}/{seq}/itens"
    params = {"pagina": 1, "tamanhoPagina": 2}
    return _fetch_endpoint(url, params, "ITENS", lic_id)


def fetch_arquivos(
    org: str, ano: int, seq: int, lic_id: str
) -> List[Dict[str, Any]]:
    url = f"{BASE_PNCP}{org}/compras/{ano}/{seq}/arquivos"
    params = {"pagina": 1, "tamanhoPagina": 2}
    return _fetch_endpoint(url, params, "ARQUIVOS", lic_id)


def process_licitacao(licitacao: Dict[str, Any]) -> List[Tuple[str, int, str]]:
    lic_id = licitacao.get("id")
    org = licitacao.get("orgao_cnpj")
    ano = licitacao.get("ano")
    seq = licitacao.get("numero_sequencial")

    if not lic_id or org is None or ano is None or seq is None:
        log(f"DADOS INCOMPLETOS {lic_id}: pulando enriquecimento.")
        return []

    log(f"ENRIQUECER {lic_id}: solicitando itens e arquivos do PNCP.")

    itens = fetch_itens(org, ano, seq, lic_id)
    arquivos = fetch_arquivos(org, ano, seq, lic_id)

    if arquivos:
        enrich_arquivos_metadata(arquivos)

    info = persist_relations(lic_id, itens, arquivos)

    if info["inserted_itens"]:
        exemplo = (
            json.dumps(itens[0], ensure_ascii=False)[:120] + "..."
            if itens
            else ""
        )
        log(
            f"ITENS {lic_id}: inseridos {info['inserted_itens']} de {info['total_itens']}. {exemplo}"
        )
    elif info["total_itens"]:
        log(f"ITENS {lic_id}: já existentes ({info['total_itens']}).")
    if info["inserted_arquivos"]:
        exemplo = (
            json.dumps(arquivos[0], ensure_ascii=False)[:120] + "..."
            if arquivos
            else ""
        )
        log(
            f"ARQUIVOS {lic_id}: inseridos {info['inserted_arquivos']} de {info['total_arquivos']}. {exemplo}"
        )
    elif info["total_arquivos"]:
        log(f"ARQUIVOS {lic_id}: já existentes ({info['total_arquivos']}).")

    return info["markdown_targets"]


def recuperar_para_licitacao(
    registro: Tuple[Any, ...],
) -> List[Tuple[str, int, str]]:
    lic_id, org, ano, seq, n_itens, n_arquivos = registro

    if not lic_id or org is None or ano is None or seq is None:
        log(f"DADOS INCOMPLETOS {lic_id}: não foi possível recuperar faltantes.")
        return []

    log(
        f"RECUPERAR {lic_id}: itens armazenados={n_itens}, arquivos armazenados={n_arquivos}. Solicitando faltantes."
    )

    itens: List[Dict[str, Any]] = []
    arquivos: List[Dict[str, Any]] = []

    if n_itens == 0:
        itens = fetch_itens(org, ano, seq, lic_id)
    if n_arquivos == 0:
        arquivos = fetch_arquivos(org, ano, seq, lic_id)

    if not itens and not arquivos:
        return []

    if arquivos:
        enrich_arquivos_metadata(arquivos)

    info = persist_relations(lic_id, itens, arquivos)

    if info["inserted_itens"]:
        log(f"RECUPERADO ITENS {lic_id}: {info['inserted_itens']} registros.")
    if info["inserted_arquivos"]:
        log(f"RECUPERADO ARQUIVOS {lic_id}: {info['inserted_arquivos']} registros.")

    return info["markdown_targets"]


def recuperar_faltantes() -> List[Tuple[str, int, str]]:
    registros = load_recovery_candidates()
    pendentes = [reg for reg in registros if reg[4] == 0 or reg[5] == 0]
    if not pendentes:
        log("RECUPERAR: nenhum registro com itens/arquivos pendentes.")
        return []

    log(f"RECUPERAR: {len(pendentes)} licitações com dados faltantes.")
    acumulado: List[Tuple[str, int, str]] = []
    for reg in pendentes:
        acumulado.extend(recuperar_para_licitacao(reg))
    return acumulado


def main() -> None:
    init_db()

    log("INÍCIO: processo de raspagem PNCP (modo lite).")

    primarios = fetch_search()
    if not primarios:
        log("Nenhum resultado retornado pela busca.")
        return

    ids_all = {p["id"] for p in primarios if "id" in p}
    existing_ids = get_existing_ids()
    novos = ids_all - existing_ids
    log(f"NOVOS {len(novos)} / TOTAL {len(ids_all)}")

    inseridos = persist_licitacoes(primarios)
    if inseridos:
        log(f"LICITAÇÕES: inseridos {inseridos} registros.")
    else:
        log("LICITAÇÕES: todos os registros já estavam armazenados.")

    markdown_targets: List[Tuple[str, int, str]] = []
    novos_itens = [item for item in primarios if item.get("id") in novos]
    if novos_itens:
        log(f"PROCESSAR NOVOS: enriquecendo {len(novos_itens)} registros inéditos.")
        for item in novos_itens:
            markdown_targets.extend(process_licitacao(item))
    else:
        log("PROCESSAR NOVOS: nenhum registro inédito para enriquecer.")

    markdown_targets.extend(recuperar_faltantes())

    if not markdown_targets:
        log("MARKDOWN: nenhum documento pendente para conversão.")
        return

    log(f"MARKDOWN: iniciando conversão de {len(markdown_targets)} documentos.")
    convertidos = 0
    falhas = 0
    for lic, seq_doc, url in markdown_targets:
        ok, err = convert_and_save_markdown_sync(lic, seq_doc, url)
        if ok:
            convertidos += 1
            log(f"MARKDOWN OK {lic}/{seq_doc}: conteúdo salvo com sucesso.")
        else:
            falhas += 1
            log(f"MARKDOWN ERRO {lic}/{seq_doc}: {err}")

    log(
        f"MARKDOWN: finalizado com {convertidos} conversões bem-sucedidas e {falhas} falhas."
    )


if __name__ == "__main__":
    main()
