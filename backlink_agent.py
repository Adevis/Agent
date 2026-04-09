#!/usr/bin/env python3
"""
Agent de scraping de backlinks via SEO SpyGlass (link-assistant.com)
- Scan une liste d'URLs
- Récupère les backlinks
- Filtre les sites d'articles/blogs
- Déduplique
- Envoie les résultats sur Discord via webhook
"""

import argparse
import asyncio
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

import requests
from playwright.async_api import async_playwright, TimeoutError as PWTimeout

SPYGLASS_URL = (
    "https://www.link-assistant.com/fr/seo-spyglass/free-backlink-checker-tool.html"
)

# Mots-clés qui identifient un site/page de type article/blog/news
ARTICLE_KEYWORDS = [
    "article", "articles",
    "blog", "blogs", "blogspot",
    "post", "posts",
    "news", "newsroom",
    "press", "presse",
    "actualite", "actualites", "actu",
    "journal", "journaux",
    "magazine", "mag",
    "media", "medias",
    "story", "stories",
    "publication", "publications",
    "wordpress", "medium.com", "substack.com",
    "tribune", "gazette", "chronique",
    "editorial", "editoriaux",
]


def is_article_site(url: str) -> bool:
    """Retourne True si l'URL ressemble à un site/page d'article ou blog."""
    if not url:
        return True
    try:
        parsed = urlparse(url)
    except Exception:
        return True

    host = (parsed.netloc or "").lower()
    path = (parsed.path or "").lower()
    full = f"{host}{path}"

    for kw in ARTICLE_KEYWORDS:
        # Match sur le hostname ou comme segment du path
        if kw in host:
            return True
        if re.search(rf"(^|[/_-]){re.escape(kw)}([/_-]|$)", path):
            return True
        if kw in full and len(kw) > 6:
            return True
    return False


def normalize_url(url: str) -> str:
    """Normalise une URL pour la déduplication."""
    url = url.strip()
    if not url:
        return ""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        p = urlparse(url)
        netloc = p.netloc.lower().lstrip("www.")
        path = p.path.rstrip("/")
        return f"{p.scheme}://{netloc}{path}"
    except Exception:
        return url


async def _accept_cookies(page):
    """Accepte les bannières cookies si présentes."""
    selectors = [
        "button:has-text('Accepter')",
        "button:has-text('Tout accepter')",
        "button:has-text('Accept all')",
        "button:has-text('Accept')",
        "#onetrust-accept-btn-handler",
        "[aria-label*='accept' i]",
    ]
    for sel in selectors:
        try:
            btn = await page.query_selector(sel)
            if btn:
                await btn.click(timeout=2000)
                await page.wait_for_timeout(500)
                return
        except Exception:
            continue


async def _submit_url(page, target_url: str):
    """Remplit le formulaire SEO SpyGlass et soumet l'URL cible."""
    input_selectors = [
        "input[name='domain']",
        "input[type='text']",
        "input[type='url']",
        "input[placeholder*='domain' i]",
        "input[placeholder*='site' i]",
        "input[placeholder*='URL' i]",
    ]
    filled = False
    for sel in input_selectors:
        try:
            el = await page.query_selector(sel)
            if el:
                await el.fill(target_url)
                filled = True
                break
        except Exception:
            continue
    if not filled:
        raise RuntimeError("Champ de saisie introuvable sur SEO SpyGlass")

    submit_selectors = [
        "button[type='submit']",
        "input[type='submit']",
        "button:has-text('Check')",
        "button:has-text('Vérifier')",
        "button:has-text('Analyser')",
        "button:has-text('Rechercher')",
    ]
    for sel in submit_selectors:
        try:
            btn = await page.query_selector(sel)
            if btn:
                await btn.click()
                return
        except Exception:
            continue
    # Fallback: pression Entrée
    await page.keyboard.press("Enter")


async def _extract_backlinks(page) -> set:
    """Extrait les backlinks depuis la page de résultats."""
    backlinks = set()

    # Attendre l'apparition des résultats
    result_selectors = [
        "table",
        ".results",
        "[class*='result']",
        "[class*='backlink']",
    ]
    for sel in result_selectors:
        try:
            await page.wait_for_selector(sel, timeout=30000)
            break
        except PWTimeout:
            continue

    # Délai supplémentaire pour le rendu AJAX
    await page.wait_for_timeout(3000)

    # Récupérer tous les liens externes de la zone résultats
    anchors = await page.query_selector_all("table a[href], .results a[href], [class*='result'] a[href], [class*='backlink'] a[href]")
    if not anchors:
        anchors = await page.query_selector_all("a[href]")

    for a in anchors:
        try:
            href = await a.get_attribute("href")
        except Exception:
            continue
        if not href:
            continue
        if href.startswith(("javascript:", "mailto:", "#")):
            continue
        if not href.startswith(("http://", "https://")):
            continue
        # Ignorer les liens internes au site de SEO SpyGlass
        if "link-assistant.com" in href:
            continue
        backlinks.add(href)

    # Essayer également d'extraire les textes en clair de type URL (certaines cellules ne sont pas des <a>)
    try:
        text = await page.inner_text("body")
        for match in re.findall(r"https?://[^\s\"'<>]+", text):
            if "link-assistant.com" in match:
                continue
            backlinks.add(match.rstrip(".,);"))
    except Exception:
        pass

    return backlinks


async def scrape_backlinks(urls, headless=True, include_articles=False):
    """Scrape les backlinks pour la liste d'URLs fournie."""
    all_backlinks = set()
    per_url_results = {}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            ),
            locale="fr-FR",
        )
        page = await context.new_page()

        for target in urls:
            print(f"[*] Analyse de: {target}", flush=True)
            found = set()
            try:
                await page.goto(SPYGLASS_URL, wait_until="domcontentloaded", timeout=60000)
                await _accept_cookies(page)
                await _submit_url(page, target)
                found = await _extract_backlinks(page)
            except Exception as e:
                print(f"  [!] Erreur pour {target}: {e}", flush=True)

            filtered = set()
            for link in found:
                norm = normalize_url(link)
                if not norm:
                    continue
                if not include_articles and is_article_site(norm):
                    continue
                filtered.add(norm)

            per_url_results[target] = filtered
            all_backlinks |= filtered
            print(f"  -> {len(filtered)} backlinks retenus ({len(found)} bruts)", flush=True)

        await browser.close()

    return all_backlinks, per_url_results


def send_to_discord(webhook_url: str, backlinks, per_url_results):
    """Envoie les backlinks sur Discord en respectant la limite de 2000 caractères."""
    if not backlinks:
        requests.post(webhook_url, json={"content": "Aucun backlink trouvé."})
        return

    header = f"**Backlinks trouvés: {len(backlinks)} (hors sites d'articles)**"
    lines = [header, ""]
    for target, links in per_url_results.items():
        lines.append(f"__{target}__ — {len(links)} liens")
        for link in sorted(links):
            lines.append(f"• {link}")
        lines.append("")

    # Découpage en chunks de 1900 caractères
    chunks = []
    current = ""
    for line in lines:
        if len(current) + len(line) + 1 > 1900:
            if current:
                chunks.append(current)
            current = line
        else:
            current = f"{current}\n{line}" if current else line
    if current:
        chunks.append(current)

    for chunk in chunks:
        r = requests.post(webhook_url, json={"content": chunk})
        if r.status_code >= 300:
            print(f"[!] Discord webhook error {r.status_code}: {r.text}", flush=True)


def save_to_file(output_path: str, backlinks, per_url_results):
    """Sauvegarde les backlinks dans un fichier texte."""
    path = Path(output_path)
    lines = []
    lines.append(f"# Backlinks trouvés: {len(backlinks)} (hors sites d'articles)")
    lines.append(f"# Généré depuis SEO SpyGlass")
    lines.append("")

    for target, links in per_url_results.items():
        lines.append(f"## {target} — {len(links)} liens")
        for link in sorted(links):
            lines.append(link)
        lines.append("")

    lines.append("## Tous les backlinks uniques (dédupliqués)")
    for link in sorted(backlinks):
        lines.append(link)

    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"[*] {len(backlinks)} backlinks sauvegardés dans {path.resolve()}", flush=True)


def load_urls(args) -> list:
    urls = []
    if args.urls:
        urls.extend(args.urls)
    if args.file:
        path = Path(args.file)
        if not path.exists():
            print(f"Erreur: fichier {path} introuvable", file=sys.stderr)
            sys.exit(1)
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                urls.append(line)
    # dédup tout en gardant l'ordre
    seen = set()
    unique = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            unique.append(u)
    return unique


def main():
    parser = argparse.ArgumentParser(
        description="Scraper de backlinks SEO SpyGlass (sortie: fichier texte et/ou Discord)",
    )
    parser.add_argument("urls", nargs="*", help="URLs à analyser")
    parser.add_argument("-f", "--file", help="Fichier texte contenant une URL par ligne")
    parser.add_argument(
        "-w", "--webhook",
        default=os.environ.get("DISCORD_WEBHOOK_URL"),
        help="URL du webhook Discord (optionnel, ou variable DISCORD_WEBHOOK_URL)",
    )
    parser.add_argument(
        "-o", "--output",
        default="backlinks.txt",
        help="Fichier de sortie pour les backlinks (défaut: backlinks.txt)",
    )
    parser.add_argument("--no-file", action="store_true",
                        help="Désactive l'écriture dans un fichier")
    parser.add_argument("--include-articles", action="store_true",
                        help="Ne pas filtrer les sites d'articles/blogs")
    parser.add_argument("--headful", action="store_true",
                        help="Lancer le navigateur en mode visible (debug)")
    args = parser.parse_args()

    urls = load_urls(args)
    if not urls:
        parser.error("Fournissez au moins une URL (en argument ou via -f)")

    print(f"[*] {len(urls)} URL(s) à analyser", flush=True)
    backlinks, per_url = asyncio.run(
        scrape_backlinks(urls, headless=not args.headful, include_articles=args.include_articles)
    )

    print(f"[*] Total backlinks uniques: {len(backlinks)}", flush=True)

    if not args.no_file:
        save_to_file(args.output, backlinks, per_url)

    if args.webhook:
        send_to_discord(args.webhook, backlinks, per_url)
        print("[*] Envoi Discord terminé", flush=True)
    else:
        print("[*] Pas de webhook Discord fourni, envoi ignoré", flush=True)


if __name__ == "__main__":
    main()
