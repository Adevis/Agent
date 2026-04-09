# Backlink Scraper Agent

Agent qui scrape les backlinks via l'outil gratuit SEO SpyGlass de link-assistant.com, filtre les sites d'articles/blogs, déduplique et envoie la liste sur un webhook Discord.

## Installation

```bash
pip install -r requirements.txt
playwright install chromium
```

## Configuration

Définir le webhook Discord :

```bash
export DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/XXX/YYY"
```

ou le passer en paramètre `--webhook`.

## Utilisation

### URLs en arguments

```bash
python backlink_agent.py https://example.com https://autre-site.fr
```

### Fichier d'URLs

```bash
python backlink_agent.py -f urls.txt
```

### Options

- `-f, --file` : fichier texte (une URL par ligne)
- `-w, --webhook` : webhook Discord (sinon variable `DISCORD_WEBHOOK_URL`)
- `--include-articles` : désactive le filtrage des sites d'articles/blogs
- `--headful` : lance Chromium en mode visible (debug)

## Filtrage des sites d'articles

Par défaut, l'agent exclut les URLs dont le hostname ou le path contient des mots-clés comme : `blog`, `article`, `news`, `press`, `actualite`, `magazine`, `medium.com`, `substack.com`, `wordpress`, etc.

Pour ajuster cette liste, modifier `ARTICLE_KEYWORDS` dans `backlink_agent.py`.
