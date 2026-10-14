
#!/usr/bin/env python3
"""Converte notícias universitárias em RSS com conteúdo quando disponível."""
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

LOG = logging.getLogger('universidades-rss')
HEADERS = {'User-Agent': 'Mozilla/5.0 (compatible; UniversidadesRSS/1.1; +https://github.com/)'}
IGNORE = {'carregar mais notícias', 'notícias', 'pesquisa', 'veja também', 'saiba mais', 'leia mais'}
CONTENT_NS = 'http://purl.org/rss/1.0/modules/content/'
ET.register_namespace('content', CONTENT_NS)


def canonical_url(href, base):
    url = urljoin(base, href)
    p = urlsplit(url)
    if p.scheme not in ('http', 'https'):
        return None
    return urlunsplit((p.scheme, p.netloc.lower(), p.path.rstrip('/') or '/', '', ''))


def extract_items(page_html, source):
    soup = BeautifulSoup(page_html, 'html.parser')
    base = source['url']
    prefix = source.get('link_prefix', '/noticias/')
    base_parts = urlsplit(base)
    items, seen = [], set()
    for a in soup.select('a[href]'):
        url = canonical_url(a.get('href', ''), base)
        if not url:
            continue
        parts = urlsplit(url)
        if parts.netloc.removeprefix('www.') != base_parts.netloc.removeprefix('www.'):
            continue
        if not parts.path.startswith(prefix):
            continue
        tail = parts.path[len(prefix):].strip('/')
        if not re.match(r'^\d{3,}-', tail):
            continue
        title = re.sub(r'\s+', ' ', ' '.join(a.stripped_strings)).strip()
        if not title:
            img = a.find('img', alt=True)
            title = img.get('alt', '').strip() if img else ''
        if not 22 <= len(title) <= 250 or title.casefold() in IGNORE or url in seen:
            continue
        seen.add(url)
        items.append({'title': title, 'url': url})
    return items


def extract_article(page_html, url):
    """Extrai o conteúdo principal; não publica menus ou rodapés como texto."""
    soup = BeautifulSoup(page_html, 'html.parser')
    selectors = [
        '[itemprop="articleBody"]', '.article-body', '.article-content',
        '.news-content', '.noticia-conteudo', '.conteudo-noticia',
        '.texto-noticia', '.texto', 'article', 'main article',
    ]
    candidates = []
    for selector in selectors:
        for node in soup.select(selector):
            paragraphs = node.find_all(['p', 'h2', 'h3', 'ul', 'ol', 'blockquote', 'figure'])
            length = sum(len(p.get_text(' ', strip=True)) for p in paragraphs)
            if length >= 120:
                candidates.append((length, node))
        if candidates:
            break
    if not candidates:
        meta = soup.find('meta', attrs={'name': 'description'}) or soup.find(
            'meta', attrs={'property': 'og:description'}
        )
        summary = meta.get('content', '').strip() if meta else ''
        return f'<p>{html.escape(summary)}</p>' if summary else ''

    node = max(candidates, key=lambda pair: pair[0])[1]
    clone = BeautifulSoup(str(node), 'html.parser')
    for unwanted in clone.select(
        'script, style, nav, footer, aside, form, iframe, button, '
        '.share, .social, .related, .publicidade'
    ):
        unwanted.decompose()

    output = []
    for element in clone.find_all(
        ['p', 'h2', 'h3', 'ul', 'ol', 'blockquote', 'figure']
    ):
        if element.find_parent(
            ['p', 'h2', 'h3', 'ul', 'ol', 'blockquote', 'figure']
        ):
            continue

        if element.name == 'figure':
            image = element.find('img')
            if image:
                src = image.get('data-src') or image.get('src')
                absolute = canonical_url(src, url) if src else None
                if absolute:
                    alt = html.escape(image.get('alt', ''), quote=True)
                    output.append(
                        f'<p><img src="{html.escape(absolute, quote=True)}" '
                        f'alt="{alt}" /></p>'
                    )
            continue

        text = element.get_text(' ', strip=True)
        if not text:
            continue

        if element.name in ('ul', 'ol'):
            lis = ''.join(
                f'<li>{html.escape(li.get_text(" ", strip=True))}</li>'
                for li in element.find_all('li', recursive=False)
            )
            if lis:
                output.append(f'<{element.name}>{lis}</{element.name}>')

        elif element.name == 'p':
            p = BeautifulSoup(str(element), 'html.parser').find('p')
            for a in p.find_all('a', href=True):
                absolute = canonical_url(a['href'], url)
                if absolute:
                    a['href'] = absolute
                else:
                    a.unwrap()

            for tag in list(p.find_all(True)):
                if tag.name not in ('a', 'strong', 'em', 'b', 'i', 'br'):
                    tag.unwrap()
                elif tag.name == 'a':
                    tag.attrs = {'href': tag['href']}
                else:
                    tag.attrs = {}

            output.append(str(p))
        else:
            output.append(
                f'<{element.name}>{html.escape(text)}</{element.name}>'
            )

    return '\n'.join(output)


def make_rss(source, items):
    rss = ET.Element('rss', version='2.0')
    channel = ET.SubElement(rss, 'channel')

    for key, value in (
        ('title', source['title']),
        ('link', source['url']),
        ('description', source['description']),
        ('language', 'pt-br'),
        ('lastBuildDate', email.utils.format_datetime(datetime.now(timezone.utc))),
    ):
        ET.SubElement(channel, key).text = value

    for article in items:
        node = ET.SubElement(channel, 'item')
        ET.SubElement(node, 'title').text = article['title']
        ET.SubElement(node, 'link').text = article['url']
        ET.SubElement(node, 'guid', isPermaLink='true').text = article['url']

        content = article.get('content', '')
        if content:
            plain = BeautifulSoup(
                content, 'html.parser'
            ).get_text(' ', strip=True)
            ET.SubElement(node, 'description').text = plain[:600]
            ET.SubElement(
                node, f'{{{CONTENT_NS}}}encoded'
            ).text = content

    ET.indent(rss, space='  ')
    return ET.tostring(
        rss, encoding='utf-8', xml_declaration=True
    )


def build(config_path, output_dir):
    config = yaml.safe_load(
        config_path.read_text(encoding='utf-8')
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers.update(HEADERS)

    errors, links = [], []
    cache = {}

    for source in config['feeds']:
        feed_id = source['id']
        if not re.fullmatch(r'[a-z0-9-]+', feed_id):
            raise ValueError(f'ID de feed inválido: {feed_id}')

        try:
            response = session.get(source['url'], timeout=25)
            response.raise_for_status()

            items = extract_items(response.text, source)
            if not items:
                raise RuntimeError(
                    'Nenhum artigo encontrado; revise os seletores do site'
                )

            for item in items:
                try:
                    if item['url'] not in cache:
                        article_response = session.get(
                            item['url'], timeout=25
                        )
                        article_response.raise_for_status()
                        cache[item['url']] = extract_article(
                            article_response.text, item['url']
                        )

                    item['content'] = cache[item['url']]

                except requests.RequestException as exc:
                    LOG.warning(
                        'Sem texto para %s: %s', item['url'], exc
                    )

            (output_dir / f'{feed_id}.xml').write_bytes(
                make_rss(source, items)
            )

            LOG.info(
                '%s: %d artigos (%d com conteúdo)',
                feed_id,
                len(items),
                sum(bool(i.get('content')) for i in items)
            )

            links.append((
                source['title'],
                f'{feed_id}.xml',
                len(items)
            ))

        except (requests.RequestException, RuntimeError) as exc:
            LOG.error('Falha em %s: %s', feed_id, exc)
            errors.append(feed_id)

    listing = '\n'.join(
        f'<li><a href="{html.escape(name)}">'
        f'{html.escape(title)}</a> ({count} itens)</li>'
        for title, name, count in links
    )

    (output_dir / 'index.html').write_text(
        '<!doctype html><html lang="pt-br">'
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<title>Feeds universitários</title>'
        '<body><h1>Feeds universitários</h1>'
        '<p>Copie o endereço de cada feed para o Inoreader.</p>'
        '<ul>' + listing + '</ul></body></html>',
        encoding='utf-8',
    )

    (output_dir / '.nojekyll').touch()

    if errors:
        raise RuntimeError(
            'Feeds que falharam: ' + ', '.join(errors)
        )


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--config', type=Path, default=Path('sources.yml')
    )
    parser.add_argument(
        '--out', type=Path, default=Path('site')
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format='%(levelname)s %(message)s'
    )
    build(args.config, args.out)
