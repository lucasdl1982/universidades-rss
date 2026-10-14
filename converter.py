
#!/usr/bin/env python3
"""Converte notícias universitárias em feeds RSS 2.0 com texto completo."""

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

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; UniversidadesRSS/1.2; "
        "+https://github.com/)"
    )
}

IGNORE = {
    "carregar mais notícias",
    "notícias",
    "pesquisa",
    "veja também",
    "saiba mais",
    "leia mais",
}

CONTENT_NS = "http://purl.org/rss/1.0/modules/content/"
ET.register_namespace("content", CONTENT_NS)


def canonical_url(href, base):
    """Transforma URLs relativas em absolutas."""
    if not href:
        return None

    url = urljoin(base, href)
    parts = urlsplit(url)

    if parts.scheme not in ("http", "https"):
        return None

    return urlunsplit((
        parts.scheme,
        parts.netloc.lower(),
        parts.path.rstrip("/") or "/",
        parts.query,
        "",
    ))


def extract_items(page_html, source):
    """Extrai os links das matérias na página de notícias."""
    soup = BeautifulSoup(page_html, "html.parser")

    base = source["url"]
    prefix = source.get("link_prefix", "/noticias/")
    base_parts = urlsplit(base)

    items = []
    seen = set()

    for a in soup.select("a[href]"):
        url = canonical_url(a.get("href", ""), base)

        if not url:
            continue

        parts = urlsplit(url)

        if (
            parts.netloc.removeprefix("www.")
            != base_parts.netloc.removeprefix("www.")
        ):
            continue

        if not parts.path.startswith(prefix):
            continue

        tail = parts.path[len(prefix):].strip("/")

        # Exemplo: 7736-icmc-abre-vagas...
        if not re.match(r"^\d{3,}-", tail):
            continue

        title = re.sub(
            r"\s+", " ", " ".join(a.stripped_strings)
        ).strip()

        if not title:
            image = a.find("img", alt=True)
            title = image.get("alt", "").strip() if image else ""

        if not 22 <= len(title) <= 250:
            continue

        if title.casefold() in IGNORE:
            continue

        if url in seen:
            continue

        seen.add(url)

        items.append({
            "title": title,
            "url": url,
        })

    return items


def parse_publication_date(soup):
    """Lê a data publicada no site, sem inventar datas."""
    node = soup.select_one(".noticia-data")

    if node is None:
        return None

    text = node.get_text(" ", strip=True)
    match = re.search(r"\b(\d{2})/(\d{2})/(\d{4})\b", text)

    if not match:
        return None

    day, month, year = map(int, match.groups())

    try:
        # Data do site sem horário: meio-dia em São Paulo.
        from datetime import timedelta

        local_tz = timezone(timedelta(hours=-3))
        return datetime(
            year, month, day, 12, 0, 0, tzinfo=local_tz
        )
    except ValueError:
        return None


def extract_article(page_html, url):
    """Extrai o corpo real das notícias do ICMC-USP."""
    soup = BeautifulSoup(page_html, "html.parser")

    # Seletor confirmado no código-fonte do ICMC-USP.
    node = soup.select_one(".noticias-texto")
    
    LOG.warning(
        "DIAGNOSTICO %s: noticias-texto=%s, "
        "noticias=%d, paragrafos=%d, html=%d caracteres",
        url,
        node is not None,
        len(soup.select("[class*='noticia']")),
        len(soup.select("p")),
        len(page_html),
    )


    if node is None:
        LOG.warning(
            "Corpo da notícia não encontrado: %s", url
        )
        return {
            "content": "",
            "subtitle": "",
            "published": None,
        }

    subtitle_node = soup.select_one(".noticia-subtitulo")

    subtitle = (
        subtitle_node.get_text(" ", strip=True)
        if subtitle_node else ""
    )

    published = parse_publication_date(soup)

    # Faz uma cópia do HTML do corpo da notícia.
    content = BeautifulSoup(str(node), "html.parser")

    # Remove janelas, scripts e controles.
    for unwanted in content.select(
        "script, style, iframe, form, button, "
        ".modal-noticias, .modal, .social, .share"
    ):
        unwanted.decompose()

    # Corrige URLs dos links.
    for a in content.select("a[href]"):
        absolute = canonical_url(a["href"], url)

        if absolute:
            a["href"] = absolute
        else:
            a.unwrap()

    # Corrige URLs das imagens.
    for img in content.select("img"):
        src = img.get("data-src") or img.get("src")

        if src:
            absolute = canonical_url(src, url)

            if absolute:
                img["src"] = absolute

    # Remove atributos de estilo e scripts embutidos.
    allowed_attrs = {
        "a": {"href", "title"},
        "img": {"src", "alt", "title"},
    }

    for tag in content.find_all(True):
        permitted = allowed_attrs.get(tag.name, set())

        for attr in list(tag.attrs):
            if attr not in permitted:
                del tag.attrs[attr]

    # Preserva o HTML interno da reportagem.
    root = content.select_one(".noticias-texto")

    if root is None:
        body_html = ""
    else:
        body_html = "".join(str(child) for child in root.contents)

    # Remove conteúdo composto apenas por espaços.
    plain = BeautifulSoup(
        body_html, "html.parser"
    ).get_text(" ", strip=True)

    if not plain:
        body_html = ""

    # Acrescenta o subtítulo antes do texto, se existir.
    if subtitle and body_html:
        body_html = (
            f"<p><strong>{html.escape(subtitle)}</strong></p>"
            + body_html
        )

    return {
        "content": body_html,
        "subtitle": subtitle,
        "published": published,
    }


def make_rss(source, items):
    """Monta o documento RSS com descrição e conteúdo HTML."""
    rss = ET.Element("rss", version="2.0")
    channel = ET.SubElement(rss, "channel")

    channel_data = (
        ("title", source["title"]),
        ("link", source["url"]),
        ("description", source["description"]),
        ("language", "pt-br"),
        (
            "lastBuildDate",
            email.utils.format_datetime(
                datetime.now(timezone.utc)
            ),
        ),
    )

    for key, value in channel_data:
        ET.SubElement(channel, key).text = value

    for article in items:
        node = ET.SubElement(channel, "item")

        ET.SubElement(node, "title").text = article["title"]
        ET.SubElement(node, "link").text = article["url"]

        ET.SubElement(
            node, "guid", isPermaLink="true"
        ).text = article["url"]

        published = article.get("published")

        if published:
            ET.SubElement(node, "pubDate").text = (
                email.utils.format_datetime(published)
            )

        content = article.get("content", "")

        if content:
            plain = BeautifulSoup(
                content, "html.parser"
            ).get_text(" ", strip=True)

            ET.SubElement(
                node, "description"
            ).text = plain[:1000]

            ET.SubElement(
                node, f"{{{CONTENT_NS}}}encoded"
            ).text = content

        elif article.get("subtitle"):
            ET.SubElement(
                node, "description"
            ).text = article["subtitle"]

    ET.indent(rss, space="  ")

    return ET.tostring(
        rss,
        encoding="utf-8",
        xml_declaration=True,
    )


def build(config_path, output_dir):
    """Consulta as fontes e gera um arquivo XML para cada feed."""
    config = yaml.safe_load(
        config_path.read_text(encoding="utf-8")
    )

    sources = config["feeds"]
    output_dir.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers.update(HEADERS)

    errors = []
    links = []
    cache = {}

    for source in sources:
        feed_id = source["id"]

        if not re.fullmatch(r"[a-z0-9-]+", feed_id):
            raise ValueError(
                f"ID de feed inválido: {feed_id}"
            )

        try:
            response = session.get(
                source["url"],
                timeout=25,
            )
            response.raise_for_status()

            items = extract_items(
                response.text,
                source,
            )

            if not items:
                raise RuntimeError(
                    "Nenhum artigo encontrado; "
                    "revise os seletores do site"
                )

            for item in items:
                try:
                    article_url = item["url"]

                    if article_url not in cache:
                        article_response = session.get(
                            article_url,
                            timeout=25,
                        )
                        article_response.raise_for_status()

                        cache[article_url] = extract_article(
                            article_response.text,
                            article_url,
                        )

                    item.update(cache[article_url])

                except requests.RequestException as exc:
                    LOG.warning(
                        "Erro ao buscar artigo %s: %s",
                        item["url"],
                        exc,
                    )

            output_file = output_dir / f"{feed_id}.xml"

            output_file.write_bytes(
                make_rss(source, items)
            )

            with_content = sum(
                bool(item.get("content"))
                for item in items
            )

            LOG.info(
                "%s: %d artigos (%d com conteúdo)",
                feed_id,
                len(items),
                with_content,
            )

            links.append((
                source["title"],
                f"{feed_id}.xml",
                len(items),
            ))

        except (
            requests.RequestException,
            RuntimeError,
        ) as exc:
            LOG.error(
                "Falha em %s: %s",
                feed_id,
                exc,
            )
            errors.append(feed_id)

    # Cria uma página com links para os feeds.
    listing = "\n".join(
        '<li><a href="{}">{}</a> ({} itens)</li>'.format(
            html.escape(name, quote=True),
            html.escape(title),
            count,
        )
        for title, name, count in links
    )

    index_html = (
        '<!doctype html>'
        '<html lang="pt-br">'
        '<head>'
        '<meta charset="utf-8">'
        '<meta name="viewport" '
        'content="width=device-width, initial-scale=1">'
        '<title>Feeds universitários</title>'
        '</head>'
        '<body>'
        '<h1>Feeds universitários</h1>'
        '<p>Copie o endereço de cada feed '
        'para o Inoreader.</p>'
        '<ul>'
        + listing +
        '</ul>'
        '</body>'
        '</html>'
    )

    (output_dir / "index.html").write_text(
        index_html,
        encoding="utf-8",
    )

    (output_dir / ".nojekyll").touch()

    if errors:
        raise RuntimeError(
            "Feeds que falharam: "
            + ", ".join(errors)
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--config",
        type=Path,
        default=Path("sources.yml"),
    )

    parser.add_argument(
        "--out",
        type=Path,
        default=Path("site"),
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(message)s",
    )

    build(args.config, args.out)
