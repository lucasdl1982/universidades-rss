#!/usr/bin/env python3
"""Converte listagens públicas de notícias universitárias em RSS 2.0.

Não inventa datas de publicação: quando não identificadas, omite pubDate.
"""
import argparse
import email.utils
import html
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit
from xml.etree import ElementTree as ET

import requests
import yaml
from bs4 import BeautifulSoup

LOG = logging.getLogger("universidades-rss")
HEADERS = {"User-Agent": "UniversidadesRSS/1.0 (+RSS pessoal; contato via repositorio GitHub)"}
IGNORE = {"carregar mais notícias", "notícias", "pesquisa", "veja também", "saiba mais", "leia mais"}


def canonical_url(href, base):
    url = urljoin(base, href)
    p = urlsplit(url)
    if p.scheme not in ("http", "https"):
        return None
    return urlunsplit((p.scheme, p.netloc.lower(), p.path.rstrip("/") or "/", "", ""))


def extract_items(page_html, source):
    """Seleciona links para matérias, descartando menus e categorias.

    A estrutura do ICMC pode mudar: os seletores são intencionalmente
    conservadores, para não publicar links de navegação como notícias.
    """
    soup = BeautifulSoup(page_html, "html.parser")
    base = source["url"]
    prefix = source.get("link_prefix", "/noticias/")
    base_parts = urlsplit(base)
    items = []
    seen = set()

    # Títulos frequentemente estão em h2/h3/h4 ou cartões de listagem.
    for a in soup.select('a[href]'):
        url = canonical_url(a.get("href", ""), base)
        if not url:
            continue
        parts = urlsplit(url)
        if parts.netloc.removeprefix("www.") != base_parts.netloc.removeprefix("www."):
            continue
        if not parts.path.startswith(prefix):
            continue
        tail = parts.path[len(prefix):].strip("/")
        # Matérias do ICMC têm caminho de artigo, não a raiz ou categorias.
        if not re.match(r"^\d{3,}-", tail):
            continue
        title = " ".join(a.stripped_strings)
        if not title:
            image = a.find("img", alt=True)
            title = image.get("alt", "").strip() if image else ""
        title = re.sub(r"\s+", " ", title).strip()
        if len(title) < 22 or title.casefold() in IGNORE:
            continue
        # Evita usar menus e elementos auxiliares como título.
        if len(title) > 250:
            continue
        if url in seen:
            continue
        seen.add(url)
        items.append({"title": title, "url": url})
    return items


def make_rss(source, items):
    rss = ET.Element("rss", version="2.0")
    channel = ET.SubElement(rss, "channel")
    for key, value in (("title", source["title"]), ("link", source["url"]),
                       ("description", source["description"]), ("language", "pt-br"),
                       ("lastBuildDate", email.utils.format_datetime(datetime.now(timezone.utc)))):
        ET.SubElement(channel, key).text = value
    for article in items:
        node = ET.SubElement(channel, "item")
        ET.SubElement(node, "title").text = article["title"]
        ET.SubElement(node, "link").text = article["url"]
        ET.SubElement(node, "guid", isPermaLink="true").text = article["url"]
        # Não usa a data da execução como data da notícia.
    ET.indent(rss, space="  ")
    return ET.tostring(rss, encoding="utf-8", xml_declaration=True)


def build(config_path, output_dir):
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    sources = config["feeds"]
    output_dir.mkdir(parents=True, exist_ok=True)
    links = []
    errors = []
    for source in sources:
        feed_id = source["id"]
        if not re.fullmatch(r"[a-z0-9-]+", feed_id):
            raise ValueError(f"ID de feed inválido: {feed_id}")
        try:
            response = requests.get(source["url"], headers=HEADERS, timeout=25)
            response.raise_for_status()
            items = extract_items(response.text, source)
            if not items:
                raise RuntimeError("Nenhum artigo encontrado; revise os seletores do site")
            (output_dir / f"{feed_id}.xml").write_bytes(make_rss(source, items))
            LOG.info("%s: %d artigos", feed_id, len(items))
            links.append((source["title"], f"{feed_id}.xml", len(items)))
        except (requests.RequestException, RuntimeError) as exc:
            LOG.error("Falha em %s: %s", feed_id, exc)
            errors.append(feed_id)
    # Índice simples para facilitar copiar os endereços.
    listing = "\n".join(f'<li><a href="{html.escape(name)}">{html.escape(title)}</a> ({count} itens)</li>'
                        for title, name, count in links)
    (output_dir / "index.html").write_text(
        '<!doctype html><html lang="pt-br"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<title>Feeds universitários</title><body><h1>Feeds universitários</h1>'
        '<p>Copie o endereço de cada feed para o Inoreader.</p><ul>' + listing + '</ul></body></html>',
        encoding="utf-8")
    (output_dir / ".nojekyll").touch()
    if errors:
        raise RuntimeError("Feeds que falharam: " + ", ".join(errors))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("sources.yml"))
    parser.add_argument("--out", type=Path, default=Path("site"))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    build(args.config, args.out)
