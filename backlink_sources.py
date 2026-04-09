#!/usr/bin/env python3
"""
Sources HTTP de backlinks (sans navigateur).

Chaque fonction prend un `domain` (ex: "formalogistics.com") et retourne
un set d'URLs qui mentionnent / linkent vers ce domaine.

Ces sources ne nécessitent que `requests` (pas de Playwright/Chromium),
donc elles tournent partout.
"""

import json
import re
import time
from urllib.parse import urlparse, quote

import requests

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
}


def extract_domain(url: str) -> str:
    """Nettoie une URL pour en extraire le domaine racine (sans www)."""
    if not url:
        return ""
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return url
    return host[4:] if host.startswith("www.") else host


def _safe_get(url, **kwargs):
    kwargs.setdefault("headers", DEFAULT_HEADERS)
    kwargs.setdefault("timeout", 30)
    return requests.get(url, **kwargs)


# ---------------------------------------------------------------------------
# 1. GitHub code search
# ---------------------------------------------------------------------------
def fetch_github_code(domain: str, token: str = None, max_pages: int = 10) -> set:
    """
    Fichiers sur GitHub qui contiennent le domaine cible (code, docs, README).
    Retourne les URLs HTML des fichiers trouvés.

    - Sans token: 10 req/min (authenticated search).
    - Avec token: 30 req/min + plus de résultats.
    """
    results = set()
    headers = dict(DEFAULT_HEADERS)
    headers["Accept"] = "application/vnd.github+json"
    if token:
        headers["Authorization"] = f"Bearer {token}"

    for page in range(1, max_pages + 1):
        try:
            r = requests.get(
                "https://api.github.com/search/code",
                params={
                    "q": f'"{domain}"',
                    "per_page": 100,
                    "page": page,
                },
                headers=headers,
                timeout=30,
            )
        except Exception as e:
            print(f"  [!] GitHub request failed: {e}")
            break

        if r.status_code == 401:
            print("  [!] GitHub: 401 (code search requires authentication)")
            break
        if r.status_code == 403:
            print(f"  [!] GitHub rate-limited: {r.headers.get('X-RateLimit-Reset')}")
            break
        if r.status_code != 200:
            print(f"  [!] GitHub status {r.status_code}: {r.text[:200]}")
            break

        data = r.json()
        items = data.get("items", [])
        if not items:
            break
        for it in items:
            html_url = it.get("html_url")
            if html_url:
                results.add(html_url)

        if len(items) < 100:
            break
        time.sleep(2)  # respect rate limit

    return results


# ---------------------------------------------------------------------------
# 2. HackerNews via Algolia
# ---------------------------------------------------------------------------
def fetch_hackernews(domain: str) -> set:
    """
    Posts/commentaires HN qui mentionnent ou linkent vers le domaine.
    API: https://hn.algolia.com/api
    """
    results = set()
    try:
        r = _safe_get(
            "https://hn.algolia.com/api/v1/search",
            params={"query": domain, "hitsPerPage": 1000, "tags": "story,comment"},
        )
        data = r.json()
    except Exception as e:
        print(f"  [!] HackerNews: {e}")
        return results

    for hit in data.get("hits", []):
        oid = hit.get("objectID")
        if oid:
            results.add(f"https://news.ycombinator.com/item?id={oid}")
    return results


# ---------------------------------------------------------------------------
# 3. Wikipedia exturlusage (toutes langues courantes)
# ---------------------------------------------------------------------------
def fetch_wikipedia(domain: str, langs=("en", "fr", "es", "de", "it", "pt", "nl")) -> set:
    """
    Articles Wikipedia (toutes langues) qui contiennent un lien externe
    vers le domaine. API publique MediaWiki.
    """
    results = set()
    for lang in langs:
        try:
            r = _safe_get(
                f"https://{lang}.wikipedia.org/w/api.php",
                params={
                    "action": "query",
                    "list": "exturlusage",
                    "euquery": domain,
                    "eunamespace": 0,
                    "eulimit": 500,
                    "format": "json",
                },
            )
            data = r.json()
        except Exception as e:
            print(f"  [!] Wikipedia {lang}: {e}")
            continue
        for item in data.get("query", {}).get("exturlusage", []):
            title = item.get("title", "").replace(" ", "_")
            if title:
                results.add(f"https://{lang}.wikipedia.org/wiki/{quote(title)}")
    return results


# ---------------------------------------------------------------------------
# 4. Reddit search
# ---------------------------------------------------------------------------
def fetch_reddit(domain: str) -> set:
    """Posts Reddit qui contiennent le domaine (via l'endpoint JSON public)."""
    results = set()
    try:
        r = _safe_get(
            "https://www.reddit.com/search.json",
            params={"q": f"site:{domain}", "limit": 100, "sort": "new"},
        )
        data = r.json()
    except Exception as e:
        print(f"  [!] Reddit: {e}")
        return results

    for child in data.get("data", {}).get("children", []):
        perm = child.get("data", {}).get("permalink")
        if perm:
            results.add(f"https://www.reddit.com{perm}")
    return results


# ---------------------------------------------------------------------------
# 5. Common Crawl URL index (pages dont l'URL matche le domaine)
# ---------------------------------------------------------------------------
def fetch_commoncrawl(domain: str, max_indexes: int = 2) -> set:
    """
    Interroge le dernier (ou les derniers) index Common Crawl pour lister les
    URLs capturées du domaine. Utile pour découvrir des pages indexées.

    Note: cela donne surtout les pages DU domaine, pas les pages qui linkent
    vers lui. Pour un vrai graphe de backlinks, il faudrait télécharger le
    "host-level webgraph" de Common Crawl (plusieurs GB).
    """
    results = set()
    try:
        r = _safe_get("https://index.commoncrawl.org/collinfo.json")
        indexes = r.json()
    except Exception as e:
        print(f"  [!] CommonCrawl collinfo: {e}")
        return results

    for idx in indexes[:max_indexes]:
        api = idx.get("cdx-api")
        if not api:
            continue
        try:
            r = _safe_get(
                api,
                params={"url": f"*.{domain}", "output": "json", "limit": 1000},
                stream=True,
            )
            for line in r.iter_lines():
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    u = entry.get("url")
                    if u:
                        results.add(u)
                except Exception:
                    continue
        except Exception as e:
            print(f"  [!] CommonCrawl {idx.get('id')}: {e}")
    return results


# ---------------------------------------------------------------------------
# 6. OpenLinkProfiler (best effort, parsing HTML)
# ---------------------------------------------------------------------------
def fetch_openlinkprofiler(domain: str) -> set:
    """
    Scrape OpenLinkProfiler.org pour en extraire les backlinks.
    Best effort: le site peut charger ses résultats via JS (dans ce cas
    retourne peu/pas de liens).
    """
    results = set()
    url = f"https://www.openlinkprofiler.org/r/{domain}"
    try:
        r = _safe_get(url)
    except Exception as e:
        print(f"  [!] OpenLinkProfiler: {e}")
        return results
    if r.status_code != 200:
        print(f"  [!] OpenLinkProfiler status {r.status_code}")
        return results

    # Extract URLs from hrefs and from visible text
    for m in re.findall(r'href=["\'](https?://[^"\'>\s]+)', r.text):
        if domain in m or "openlinkprofiler.org" in m:
            continue
        results.add(m)
    return results


# ---------------------------------------------------------------------------
# 7. Wayback Machine CDX (captures des pages du domaine)
# ---------------------------------------------------------------------------
def fetch_wayback(domain: str, limit: int = 2000) -> set:
    """
    Pages capturées par la Wayback Machine pour ce domaine (historique).
    Comme Common Crawl: ce sont des URLs DU domaine, pas de ses référents.
    """
    results = set()
    try:
        r = _safe_get(
            "https://web.archive.org/cdx/search/cdx",
            params={
                "url": f"{domain}/*",
                "output": "json",
                "fl": "original",
                "collapse": "urlkey",
                "limit": limit,
            },
        )
        data = r.json()
    except Exception as e:
        print(f"  [!] Wayback: {e}")
        return results

    if not data or len(data) < 2:
        return results
    for row in data[1:]:
        if row:
            results.add(row[0])
    return results


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
ALL_SOURCES = {
    "github": fetch_github_code,
    "hackernews": fetch_hackernews,
    "wikipedia": fetch_wikipedia,
    "reddit": fetch_reddit,
    "commoncrawl": fetch_commoncrawl,
    "openlinkprofiler": fetch_openlinkprofiler,
    "wayback": fetch_wayback,
}
