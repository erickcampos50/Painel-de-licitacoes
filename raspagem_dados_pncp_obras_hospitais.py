# teste_fluxo.py
import asyncio
import io
import aiohttp
import sqlite3
import requests
import re
import json
import random
import zipfile
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Sequence, Set, Tuple
from urllib.parse import unquote, urlparse

from markitdown import MarkItDown

# ============ CONFIG ============
# https://pncp.gov.br/app/editais?pagina=1&esferas=F&q=hospital&status=todos&modalidades=4
SEARCH_URL = "https://pncp.gov.br/api/search/"
BASE_PNCP = "https://pncp.gov.br/api/pncp/v1/orgaos/"
TIPOS_DOCUMENTO = ["edital"]  # ["edital","ata"]
ORDENACAO = ["data"]  # ["data","-data","relevancia"]
PAGES = list(range(1, 2))
TAM_PAGINA = 4
ESFERA = ""
QUERY = ""
MODALIDADE = ""
MAX_CONN = 5
DB_PATH = "database_licitacoes_2.db"
HTTP_TIMEOUT = aiohttp.ClientTimeout(total=60)
REQUEST_DELAY_MIN = 0.1
REQUEST_DELAY_MAX = 0.4
MAX_ZIP_DEPTH = 3

SQL_SCHEMA = """
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
"""


# ============ HELPERS ============
def now() -> datetime:
    return datetime.now(timezone.utc)


def log(msg: str) -> None:
    print(f"[{now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}")


async def random_pause() -> None:
    if REQUEST_DELAY_MAX <= 0:
        return
    low = max(0.0, min(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX))
    high = max(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX)
    await asyncio.sleep(random.uniform(low, high))


async def resolve_readable_title(
    session: aiohttp.ClientSession, url: str
) -> Tuple[str, bool]:
    content_disposition = ""
    content_type = ""
    try:
        await random_pause()
        async with session.head(url, allow_redirects=True) as resp:
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


async def collect_zip_members(
    session: aiohttp.ClientSession, url: str
) -> List[str]:
    try:
        await random_pause()
        async with session.get(url) as resp:
            resp.raise_for_status()
            data = await resp.read()
    except Exception as exc:
        log(f"DOWNLOAD ZIP falhou para {url}: {exc}")
        return []

    return list_zip_contents(data)


async def enrich_arquivos_metadata(
    session: aiohttp.ClientSession, arquivos: List[Dict[str, Any]]
) -> None:
    for arq in arquivos:
        url = arq.get("url")
        if not url:
            continue
        try:
            display_name, is_zip = await resolve_readable_title(session, url)
            if is_zip:
                members = await collect_zip_members(session, url)
                if members:
                    arq["titulo"] = f"{display_name} | " + "; ".join(members)
                else:
                    arq["titulo"] = display_name
            else:
                arq["titulo"] = display_name
        except Exception as exc:
            log(f"ERRO metadados arquivo {arq.get('sequencialDocumento')}: {exc}")


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


def init_db() -> None:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.executescript(SQL_SCHEMA)
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


# ============ FETCH ============
async def _fetch_search_page(
    session: aiohttp.ClientSession, params: Dict[str, Any]
) -> List[Dict[str, Any]]:
    try:
        await random_pause()
        async with session.get(SEARCH_URL, params=params) as resp:
            if resp.status != 200:
                log(
                    f"ERRO search pagina {params['pagina']} ({params['tipos_documento']} / {params['ordenacao']}): HTTP {resp.status}"
                )
                return []
            data = await resp.json()
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


async def fetch_search(session: aiohttp.ClientSession) -> List[Dict[str, Any]]:
    tasks = []
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
                tasks.append(asyncio.create_task(_fetch_search_page(session, params)))
    results: List[Dict[str, Any]] = []
    for task in asyncio.as_completed(tasks):
        results.extend(await task)
    return results


async def _fetch_endpoint(
    session: aiohttp.ClientSession,
    url: str,
    params: Dict[str, Any],
    label: str,
    lic_id: str,
) -> List[Dict[str, Any]]:
    try:
        await random_pause()
        async with session.get(url, params=params) as resp:
            if resp.status != 200:
                log(f"ERRO {label} {lic_id}: HTTP {resp.status}")
                return []
            data = await resp.json()
            if isinstance(data, list):
                return data
            return data.get("items", [])
    except Exception as exc:
        log(f"ERRO {label} {lic_id}: {exc}")
        return []


async def fetch_itens(
    session: aiohttp.ClientSession, org: str, ano: int, seq: int, lic_id: str
) -> List[Dict[str, Any]]:
    url = f"{BASE_PNCP}{org}/compras/{ano}/{seq}/itens"
    params = {"pagina": 1, "tamanhoPagina": 2}
    return await _fetch_endpoint(session, url, params, "ITENS", lic_id)


async def fetch_arquivos(
    session: aiohttp.ClientSession, org: str, ano: int, seq: int, lic_id: str
) -> List[Dict[str, Any]]:
    url = f"{BASE_PNCP}{org}/compras/{ano}/{seq}/arquivos"
    params = {"pagina": 1, "tamanhoPagina": 2}
    return await _fetch_endpoint(session, url, params, "ARQUIVOS", lic_id)


# ============ MARKDOWN ============
async def convert_and_save_markdown(
    lic_id: str, seq_doc: int, url: str
) -> None:
    if not url:
        log(f"MARKDOWN {lic_id}/{seq_doc}: URL ausente, pulando")
        return
    ok, err = await asyncio.to_thread(convert_and_save_markdown_sync, lic_id, seq_doc, url)
    status = "convertido" if ok else f"erro {err}"
    log(f"MARKDOWN {lic_id}/{seq_doc}: {status}")


# ============ PIPELINE ============
async def process_licitacao(
    session: aiohttp.ClientSession,
    licitacao: Dict[str, Any],
    markdown_tasks: List[asyncio.Task],
) -> None:
    lic_id = licitacao.get("id")
    org = licitacao.get("orgao_cnpj")
    ano = licitacao.get("ano")
    seq = licitacao.get("numero_sequencial")

    if not lic_id or org is None or ano is None or seq is None:
        log(f"DADOS INCOMPLETOS {lic_id}: pulando enriquecimento.")
        return

    itens_task = asyncio.create_task(fetch_itens(session, org, ano, seq, lic_id))
    arquivos_task = asyncio.create_task(fetch_arquivos(session, org, ano, seq, lic_id))
    itens, arquivos = await asyncio.gather(itens_task, arquivos_task)

    if arquivos:
        await enrich_arquivos_metadata(session, arquivos)

    info = await asyncio.to_thread(persist_relations, lic_id, itens, arquivos)

    if info["inserted_itens"]:
        exemplo = (
            json.dumps(itens[0], ensure_ascii=False)[:120] + "..."
            if itens
            else ""
        )
        log(
            f"ITENS {lic_id}: inseridos {info['inserted_itens']} de {info['total_itens']}. {exemplo}"
        )
    if info["inserted_arquivos"]:
        exemplo = (
            json.dumps(arquivos[0], ensure_ascii=False)[:120] + "..."
            if arquivos
            else ""
        )
        log(
            f"ARQUIVOS {lic_id}: inseridos {info['inserted_arquivos']} de {info['total_arquivos']}. {exemplo}"
        )

    for lic, seq_doc, url in info["markdown_targets"]:
        markdown_tasks.append(asyncio.create_task(convert_and_save_markdown(lic, seq_doc, url)))


async def recuperar_para_licitacao(
    session: aiohttp.ClientSession,
    registro: Tuple[Any, ...],
    markdown_tasks: List[asyncio.Task],
) -> None:
    lic_id, org, ano, seq, n_itens, n_arquivos = registro

    if not lic_id or org is None or ano is None or seq is None:
        log(f"DADOS INCOMPLETOS {lic_id}: não foi possível recuperar faltantes.")
        return

    itens: List[Dict[str, Any]] = []
    arquivos: List[Dict[str, Any]] = []
    tasks: List[Tuple[str, asyncio.Task]] = []

    if n_itens == 0:
        tasks.append(("itens", asyncio.create_task(fetch_itens(session, org, ano, seq, lic_id))))
    if n_arquivos == 0:
        tasks.append(
            ("arquivos", asyncio.create_task(fetch_arquivos(session, org, ano, seq, lic_id)))
        )

    for label, task in tasks:
        result = await task
        if label == "itens":
            itens = result
        else:
            arquivos = result

    if not itens and not arquivos:
        return

    if arquivos:
        await enrich_arquivos_metadata(session, arquivos)

    info = await asyncio.to_thread(persist_relations, lic_id, itens, arquivos)

    if info["inserted_itens"]:
        log(f"RECUPERADO ITENS {lic_id}: {info['inserted_itens']} registros.")
    if info["inserted_arquivos"]:
        log(f"RECUPERADO ARQUIVOS {lic_id}: {info['inserted_arquivos']} registros.")

    for lic, seq_doc, url in info["markdown_targets"]:
        markdown_tasks.append(asyncio.create_task(convert_and_save_markdown(lic, seq_doc, url)))


async def recuperar_faltantes(
    session: aiohttp.ClientSession, markdown_tasks: List[asyncio.Task]
) -> None:
    registros = await asyncio.to_thread(load_recovery_candidates)
    pendentes = [reg for reg in registros if reg[4] == 0 or reg[5] == 0]
    if not pendentes:
        return

    log(f"RECUPERAR: {len(pendentes)} licitações com dados faltantes.")
    tasks = [
        asyncio.create_task(recuperar_para_licitacao(session, reg, markdown_tasks))
        for reg in pendentes
    ]
    await asyncio.gather(*tasks)


# ============ MAIN ============
async def main() -> None:
    init_db()

    connector = aiohttp.TCPConnector(limit=MAX_CONN)
    async with aiohttp.ClientSession(connector=connector, timeout=HTTP_TIMEOUT) as session:
        primarios = await fetch_search(session)
        if not primarios:
            log("Nenhum resultado retornado pela busca.")
            return

        ids_all = {p["id"] for p in primarios}
        existing_ids = await asyncio.to_thread(get_existing_ids)
        novos = ids_all - existing_ids
        log(f"NOVOS {len(novos)} / TOTAL {len(ids_all)}")

        inseridos = await asyncio.to_thread(persist_licitacoes, primarios)
        if inseridos:
            log(f"LICITAÇÕES: inseridos {inseridos} registros.")

        markdown_tasks: List[asyncio.Task] = []

        novos_itens = [item for item in primarios if item["id"] in novos]
        if novos_itens:
            log(f"PROCESSAR NOVOS: {len(novos_itens)} registros.")
            process_tasks = [
                asyncio.create_task(process_licitacao(session, item, markdown_tasks))
                for item in novos_itens
            ]
            await asyncio.gather(*process_tasks)

        await recuperar_faltantes(session, markdown_tasks)

        if markdown_tasks:
            await asyncio.gather(*markdown_tasks)


if __name__ == "__main__":
    asyncio.run(main())
