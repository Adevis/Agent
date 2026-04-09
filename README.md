# Agent Multi-Sources de Backlinks

Agent qui interroge plusieurs sources publiques pour trouver les backlinks d'un domaine, filtre les sites d'articles/blogs, déduplique, et exporte en fichier texte et/ou vers un webhook Discord.

## Sources

**HTTP (aucune installation lourde requise)** :
- `github` — GitHub code search (nécessite un token)
- `hackernews` — posts/commentaires HN via Algolia
- `wikipedia` — articles Wikipedia (7 langues) qui linkent vers le domaine
- `reddit` — posts Reddit mentionnant le domaine
- `commoncrawl` — pages indexées par Common Crawl
- `openlinkprofiler` — OpenLinkProfiler (best effort)
- `wayback` — captures Wayback Machine du domaine

**Navigateur (optionnel)** :
- `spyglass` — SEO SpyGlass de link-assistant.com (nécessite Playwright + Chromium)

## Installation

### Minimale (sources HTTP uniquement)

```bash
pip install requests
```

### Complète (avec SEO SpyGlass)

```bash
pip install -r requirements.txt
pip install playwright
playwright install chromium
```

## Configuration

### Webhook Discord (optionnel)

```bash
export DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/XXX/YYY"
```

### Token GitHub (requis pour la source `github`)

Créer un token sur https://github.com/settings/tokens (aucun scope nécessaire, le token public suffit pour la recherche de code).

```bash
export GITHUB_TOKEN="ghp_xxxxxxxxxxxx"
```

## Utilisation

### Scan simple (toutes les sources HTTP par défaut)

```bash
python backlink_agent.py https://formalogistics.com/
```

### Sources spécifiques

```bash
python backlink_agent.py https://formalogistics.com/ -s github,wikipedia,openlinkprofiler
```

### Avec SEO SpyGlass en plus

```bash
python backlink_agent.py https://formalogistics.com/ --spyglass
```

### Fichier d'URLs

```bash
python backlink_agent.py -f urls.txt -o resultats.txt
```

### Options

- `-f, --file` : fichier texte (une URL par ligne)
- `-s, --sources` : sources actives, séparées par virgule
- `-w, --webhook` : webhook Discord (ou variable `DISCORD_WEBHOOK_URL`)
- `-o, --output` : fichier de sortie (défaut : `backlinks.txt`)
- `--github-token` : token GitHub (ou variable `GITHUB_TOKEN`)
- `--spyglass` : active SEO SpyGlass (nécessite Playwright)
- `--include-articles` : désactive le filtrage des sites d'articles/blogs
- `--no-file` : désactive l'écriture fichier
- `--headful` : navigateur visible (debug pour `--spyglass`)

## Filtrage des sites d'articles

Par défaut, l'agent exclut les URLs dont le hostname ou le path contient des mots-clés comme : `blog`, `article`, `news`, `press`, `actualite`, `magazine`, `medium.com`, `substack.com`, `wordpress`, etc.

Pour ajuster cette liste, éditer `ARTICLE_KEYWORDS` dans `backlink_agent.py`.

## Note sur les résultats

Aucune source gratuite ne donne 100% des backlinks (même Ahrefs n'en a qu'une fraction). En combinant les sources ci-dessus, vous obtiendrez en général quelques centaines à quelques milliers de liens uniques pour un domaine moyen. Pour du volume et de la précision industriels, il faudrait passer par des APIs payantes (Ahrefs, Majestic, SEMrush).
