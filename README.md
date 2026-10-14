# Feeds universitários — ICMC-USP

Conversor gratuito de listagens de notícias para RSS 2.0. Cada fonte definida em `sources.yml` gera seu próprio `.xml`.

## Publicar no GitHub

1. Crie um **repositório público** no GitHub (ex.: `universidades-rss`).
2. Envie **todos os arquivos**, incluindo a pasta oculta `.github/workflows/rss.yml`, para a branch `main`.
3. Em **Settings → Pages → Build and deployment → Source**, escolha **GitHub Actions**.
4. Abra **Actions → Atualizar feeds universitarios → Run workflow** e aguarde o deploy.
5. Seu feed terá formato `https://SEU-USUARIO.github.io/universidades-rss/icmc-usp.xml` e `.../icmc-usp-pesquisa.xml` (ajuste usuário e nome do repositório).
6. Cole cada URL no campo **Adicionar feed** do Inoreader.

O workflow também roda aproximadamente a cada seis horas (o agendamento pode atrasar). O repositório e os feeds são públicos.

## Executar no computador (opcional)

```bash
python -m pip install -r requirements.txt
python converter.py --out site
```

## Acrescentar universidades

Adicione outro bloco `feeds` no arquivo `sources.yml` com `id`, `title`, `url`, `description` e `link_prefix`. **A extração precisa ser testada para cada site**: o extrator atual usa caminhos de artigos do ICMC-USP e pode não funcionar em outras universidades sem adaptação.

## Limitações

- O site pode alterar o HTML e interromper a extração; nesse caso, o workflow falha em vez de publicar um feed vazio.
- A página de listagem pode mostrar só os artigos mais recentes; o conversor não percorre o botão "Carregar mais".
- Sem data de publicação confiável, o RSS não inclui `pubDate` por artigo.
- O feed contém título e link, não copia integralmente o texto das matérias.
- É necessário validar a extração na primeira execução do GitHub Actions. Este projeto não foi executado contra o site real nesta entrega.
