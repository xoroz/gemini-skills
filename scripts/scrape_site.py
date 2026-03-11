#!/usr/bin/env python3
"""
Scrape a business website and extract structured data for frontend-clone skill.
Output saved to scrapes/<domain>/data.json and raw.md
"""

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

def slugify(url: str) -> str:
    domain = urlparse(url).netloc or url
    return re.sub(r"[^a-z0-9.-]", "-", domain.lower()).strip("-")


def scrape(url: str, output_dir: Path) -> dict:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

    output_dir.mkdir(parents=True, exist_ok=True)

    data = {
        "source_url": url,
        "business_name": "",
        "tagline": "",
        "description": "",
        "services": [],
        "about": "",
        "address": "",
        "phone": [],
        "email": [],
        "social_links": {},
        "gallery_images": [],
        "hero_image": "",
        "testimonials": [],
        "nav_links": [],
        "colors": [],
        "fonts": [],
        "raw_text_sections": {},
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()

        print(f"Loading {url} …", flush=True)
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(2500)
        except PWTimeout:
            print("WARNING: page load timed out, continuing with partial content")

        # Dismiss common cookie/GDPR banners
        banner_selectors = [
            "button[id*='accept']", "button[class*='accept']",
            "button[id*='cookie']", "button[class*='cookie']",
            "a[id*='accept']", "a[class*='accept']",
            "#cookieConsentButton", ".cc-btn.cc-allow", ".cc-accept",
            "[data-action='accept']", "[aria-label*='accett']",
            "button:text('Accetta')", "button:text('Accept')",
            "button:text('Accetto')", "button:text('OK')",
            "button:text('Agree')", "button:text('Allow')",
        ]
        for sel in banner_selectors:
            try:
                btn = page.locator(sel).first
                if btn.is_visible(timeout=500):
                    btn.click(timeout=1000)
                    page.wait_for_timeout(800)
                    print(f"Dismissed cookie banner: {sel}")
                    break
            except Exception:
                pass

        # Scroll page to trigger lazy loading
        page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
        page.wait_for_timeout(800)
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(800)
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(500)

        # Screenshot for reference
        screenshot_path = output_dir / "screenshot.png"
        page.screenshot(path=str(screenshot_path), full_page=True)
        print(f"Screenshot saved → {screenshot_path}")

        # ── Business name ──────────────────────────────────────────────────
        data["business_name"] = page.evaluate("""() => {
            const og = document.querySelector('meta[property="og:site_name"]');
            if (og) return og.content;
            const title = document.querySelector('title');
            return title ? title.textContent.split('|')[0].split('-')[0].trim() : '';
        }""")

        # ── Meta description / tagline ─────────────────────────────────────
        data["tagline"] = page.evaluate("""() => {
            const og = document.querySelector('meta[property="og:description"]');
            const meta = document.querySelector('meta[name="description"]');
            return (og || meta)?.content || '';
        }""")

        # ── Nav links ──────────────────────────────────────────────────────
        data["nav_links"] = page.evaluate("""() => {
            const links = [];
            document.querySelectorAll('nav a, header a').forEach(a => {
                const text = a.textContent.trim();
                const href = a.getAttribute('href') || '';
                if (text && text.length < 40 && !href.startsWith('http'))
                    links.push({ text, href });
            });
            return [...new Map(links.map(l => [l.text, l])).values()].slice(0, 10);
        }""")

        # ── Hero image ─────────────────────────────────────────────────────
        data["hero_image"] = page.evaluate("""() => {
            const hero = document.querySelector(
                '.hero img, #hero img, [class*="hero"] img, header img, .banner img'
            );
            if (hero) return hero.src;
            const bg = [...document.querySelectorAll('*')].find(el => {
                const s = window.getComputedStyle(el).backgroundImage;
                return s && s !== 'none' && s.includes('url');
            });
            if (bg) {
                const m = window.getComputedStyle(bg).backgroundImage.match(/url\\(["']?([^"')]+)/);
                return m ? m[1] : '';
            }
            return '';
        }""")

        # ── Gallery images (first 6 meaningful images) ─────────────────────
        data["gallery_images"] = page.evaluate("""() => {
            const imgs = [];
            document.querySelectorAll('img').forEach(img => {
                const src = img.src || '';
                const w = img.naturalWidth || img.width || 0;
                const h = img.naturalHeight || img.height || 0;
                if (src && w > 200 && h > 150 && !src.includes('logo') && !src.includes('icon'))
                    imgs.push({ src, alt: img.alt || '', width: w, height: h });
            });
            return imgs.slice(0, 8);
        }""")

        # ── Services ───────────────────────────────────────────────────────
        data["services"] = page.evaluate("""() => {
            const services = [];
            const sel = '[class*="service"], [class*="card"], [class*="offer"], [class*="feature"], article, .item';
            const candidates = document.querySelectorAll(sel);
            candidates.forEach(el => {
                const heading = el.querySelector('h2,h3,h4,h5');
                const body = el.querySelector('p');
                if (heading) services.push({
                    title: heading.textContent.trim(),
                    description: body ? body.textContent.trim().slice(0, 200) : ''
                });
            });
            return services.slice(0, 6);
        }""")

        # ── About text ─────────────────────────────────────────────────────
        data["about"] = page.evaluate("""() => {
            const COOKIE_KEYWORDS = ['cookie', 'gdpr', 'privacy policy', 'consenso', 'informazioni sul tuo browser'];
            const isCookieText = t => COOKIE_KEYWORDS.some(k => t.toLowerCase().includes(k));

            const about = document.querySelector(
                '[class*="about"], #about, [id*="about"], [class*="chi-siamo"], #chi-siamo'
            );
            if (about) {
                const t = about.innerText.trim();
                if (!isCookieText(t)) return t.slice(0, 800);
            }
            // fallback: longest paragraph that isn't cookie text
            const paras = [...document.querySelectorAll('p')]
                .map(p => p.textContent.trim())
                .filter(t => t.length > 80 && !isCookieText(t));
            return paras.sort((a, b) => b.length - a.length)[0]?.slice(0, 800) || '';
        }""")

        # ── Contact info ───────────────────────────────────────────────────
        contact_data = page.evaluate("""() => {
            const text = document.body.innerText;

            // Phone numbers
            const phones = [...text.matchAll(/[+\\d][\\d\\s\\-().]{7,}/g)]
                .map(m => m[0].trim())
                .filter(p => p.replace(/\\D/g,'').length >= 8)
                .slice(0, 3);

            // Emails
            const emails = [...text.matchAll(/[a-zA-Z0-9._%+\\-]+@[a-zA-Z0-9.\\-]+\\.[a-zA-Z]{2,}/g)]
                .map(m => m[0])
                .slice(0, 3);

            // Address: look for address tag or heuristic
            const addrEl = document.querySelector('address, [class*="address"], [itemprop="address"]');
            const address = addrEl ? addrEl.innerText.trim().slice(0, 200) : '';

            return { phones, emails, address };
        }""")
        # Deduplicate phones and emails
        data["phone"] = list(dict.fromkeys(contact_data.get("phones", [])))
        data["email"] = list(dict.fromkeys(contact_data.get("emails", [])))
        data["address"] = contact_data.get("address", "")

        # ── Social links ───────────────────────────────────────────────────
        data["social_links"] = page.evaluate("""() => {
            const map = {};
            const patterns = {
                facebook: /facebook\\.com/,
                instagram: /instagram\\.com/,
                twitter: /twitter\\.com|x\\.com/,
                linkedin: /linkedin\\.com/,
                youtube: /youtube\\.com/,
                tiktok: /tiktok\\.com/,
                whatsapp: /whatsapp\\.com|wa\\.me/,
            };
            document.querySelectorAll('a[href]').forEach(a => {
                const href = a.href || '';
                for (const [name, rx] of Object.entries(patterns)) {
                    if (rx.test(href) && !map[name]) map[name] = href;
                }
            });
            return map;
        }""")

        # ── Testimonials ───────────────────────────────────────────────────
        data["testimonials"] = page.evaluate("""() => {
            const results = [];
            document.querySelectorAll(
                '[class*="testimon"], [class*="review"], [class*="quote"], blockquote'
            ).forEach(el => {
                const text = el.textContent.trim();
                if (text.length > 20) results.push({ quote: text.slice(0, 300) });
            });
            return results.slice(0, 3);
        }""")

        # ── Colors (CSS custom props + computed bg/fg) ──────────────────────
        data["colors"] = page.evaluate("""() => {
            const root = document.documentElement;
            const style = getComputedStyle(root);
            const colors = [];
            // Try CSS variables
            ['--color', '--primary', '--secondary', '--accent', '--bg', '--text'].forEach(v => {
                const val = style.getPropertyValue(v).trim();
                if (val) colors.push({ var: v, value: val });
            });
            // Fallback: sample bg colors of major elements
            ['body','header','footer','nav'].forEach(sel => {
                const el = document.querySelector(sel);
                if (el) {
                    const bg = getComputedStyle(el).backgroundColor;
                    if (bg && bg !== 'rgba(0, 0, 0, 0)') colors.push({ element: sel, bg });
                }
            });
            return colors.slice(0, 10);
        }""")

        # ── Fonts ──────────────────────────────────────────────────────────
        data["fonts"] = page.evaluate("""() => {
            const fonts = new Set();
            ['body','h1','h2','h3'].forEach(sel => {
                const el = document.querySelector(sel);
                if (el) fonts.add(getComputedStyle(el).fontFamily.split(',')[0].replace(/['"]/g,'').trim());
            });
            return [...fonts];
        }""")

        # ── Full page text sections ─────────────────────────────────────────
        data["raw_text_sections"] = page.evaluate("""() => {
            const COOKIE_KEYWORDS = ['cookie', 'gdpr', 'consenso', 'privacy policy'];
            const isCookieText = t => COOKIE_KEYWORDS.some(k => t.toLowerCase().includes(k));
            const sections = {};
            document.querySelectorAll('section, main > div, article').forEach((el, i) => {
                const text = el.innerText?.trim();
                if (text && text.length > 50 && !isCookieText(text)) {
                    const id = el.id || el.className.split(' ')[0] || `section-${i}`;
                    sections[id] = text.slice(0, 600);
                }
            });
            return sections;
        }""")

        browser.close()

    return data


def main():
    parser = argparse.ArgumentParser(description="Scrape a website for frontend-clone data")
    parser.add_argument("url", help="URL to scrape")
    parser.add_argument("--out", default="scrapes", help="Output base directory (default: scrapes)")
    args = parser.parse_args()

    url = args.url
    if not url.startswith("http"):
        url = "https://" + url

    slug = slugify(url)
    out_dir = Path(args.out) / slug

    print(f"Scraping {url} → {out_dir}/")
    data = scrape(url, out_dir)

    # Save JSON
    json_path = out_dir / "data.json"
    json_path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    print(f"Data saved → {json_path}")

    # Save human-readable markdown summary
    md = build_markdown(data)
    md_path = out_dir / "raw.md"
    md_path.write_text(md, encoding="utf-8")
    print(f"Summary saved → {md_path}")

    # Print summary to stdout
    print("\n" + "─" * 60)
    print(md)


def build_markdown(d: dict) -> str:
    lines = [f"# {d['business_name'] or 'Unknown Business'}", ""]
    lines += [f"**Source:** {d['source_url']}", ""]

    if d["tagline"]:
        lines += [f"**Tagline:** {d['tagline']}", ""]

    if d["about"]:
        lines += ["## About", d["about"], ""]

    if d["address"]:
        lines += [f"**Address:** {d['address']}", ""]
    if d["phone"]:
        lines += [f"**Phone:** {', '.join(d['phone'])}", ""]
    if d["email"]:
        lines += [f"**Email:** {', '.join(d['email'])}", ""]

    if d["services"]:
        lines += ["## Services"]
        for s in d["services"]:
            lines.append(f"- **{s['title']}**: {s['description']}")
        lines.append("")

    if d["social_links"]:
        lines += ["## Social Links"]
        for k, v in d["social_links"].items():
            lines.append(f"- {k}: {v}")
        lines.append("")

    if d["testimonials"]:
        lines += ["## Testimonials"]
        for t in d["testimonials"]:
            lines.append(f'> {t["quote"]}')
        lines.append("")

    if d["nav_links"]:
        nav = ", ".join(l["text"] for l in d["nav_links"])
        lines += [f"**Nav:** {nav}", ""]

    if d["colors"]:
        lines += ["## Detected Colors"]
        for c in d["colors"]:
            lines.append(f"- {c}")
        lines.append("")

    if d["fonts"]:
        lines += [f"**Fonts detected:** {', '.join(d['fonts'])}", ""]

    if d["gallery_images"]:
        lines += ["## Gallery Images (URLs for reference)"]
        for img in d["gallery_images"]:
            lines.append(f"- {img['src']} (alt: {img['alt']})")
        lines.append("")

    if d["raw_text_sections"]:
        lines += ["## Raw Text Sections"]
        for k, v in list(d["raw_text_sections"].items())[:5]:
            lines.append(f"### {k}")
            lines.append(v[:300])
            lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    main()
