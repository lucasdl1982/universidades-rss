import unittest
from converter import extract_items, make_rss
from xml.etree import ElementTree as ET

SOURCE = {"id":"icmc-usp", "title":"ICMC", "description":"Notícias", "url":"https://www.icmc.usp.br/noticias", "link_prefix":"/noticias/"}
class TestConverter(unittest.TestCase):
    def test_extract(self):
        html = '''<a href="/noticias/pesquisa">Pesquisa</a><a href="/noticias/6500-nova-descoberta-na-usp">Pesquisa em inteligência artificial desenvolve ferramenta para estudantes</a>'''
        items = extract_items(html, SOURCE)
        self.assertEqual(len(items), 1)
        self.assertIn('6500', items[0]['url'])
    def test_xml(self):
        xml = make_rss(SOURCE, [{"title":"Uma notícia", "url":"https://www.icmc.usp.br/noticias/6500-exemplo"}])
        self.assertEqual(ET.fromstring(xml).findtext('./channel/item/title'), 'Uma notícia')
if __name__ == '__main__': unittest.main()
