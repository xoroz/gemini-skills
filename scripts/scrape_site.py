#!/usr/bin/env python3
"""
Scrape a business website and extract structured data for frontend-clone skill.
Output saved to scrapes/<domain>/data.json and raw.md

JSON schema (strictly follows the standard site-clone skeleton):
  site_url, metadata, branding, contact_info, layout_and_nav, content, assets
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Optional, List, Dict, Any
from urllib.parse import urlparse


def slugify(url: str) -> str:
    domain = urlparse(url).netloc or url
    return re.sub(r"[^a-z0-9.-]", "-", domain.lower()).strip("-")


def scrape(url: str, output_dir: Path):
    # type: (...) -> tuple
    """
    Returns (data, extra) where:
      - data   matches the standard JSON skeleton exactly
      - extra  holds additional fields used only for raw.md (services, about, etc.)
    """
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

    output_dir.mkdir(parents=True, exist_ok=True)

    # Standard JSON skeleton — strictly followed in output
    data = {
        "site_url": url,
        "metadata": {
            "title": "",
            "description": "",
            "favicon_url": "",
            "language": "",
        },
        "branding": {
            "logo_url": "",
            "color_palette": {
                "primary": [],
                "secondary": [],
                "background": [],
            },
            "typography": [],
        },
        "contact_info": {
            "emails": [],
            "phones": [],
            "social_links": {
                "facebook":  "",
                "instagram": "",
                "twitter":   "",
                "linkedin":  "",
                "youtube":   "",
                "tiktok":    "",
                "whatsapp":  "",
            },
            "physical_address": "",
        },
        "layout_and_nav": {
            "header_links": [],
            "footer_links": [],
        },
        "content": {
            "h1_headings": [],
            "h2_headings": [],
            "call_to_action_buttons": [],
            "hero_image_url": "",
            "image_gallery": [],
        },
        "assets": {
            "screenshot_file_path": "",
        },
    }

    # Extra fields — extracted for raw.md context only, NOT saved to data.json
    extra = {
        "business_name": "",
        "tagline": "",
        "services": [],
        "about": "",
        "testimonials": [],
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

        # Scroll to trigger lazy loading
        page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
        page.wait_for_timeout(800)
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(800)
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(500)

        # ── Screenshot ────────────────────────────────────────────────────
        screenshot_path = output_dir / "screenshot.png"
        page.screenshot(path=str(screenshot_path), full_page=True)
        print(f"Screenshot saved → {screenshot_path}")
        data["assets"]["screenshot_file_path"] = str(screenshot_path)

        # ── Metadata ──────────────────────────────────────────────────────
        meta = page.evaluate("""() => {
            const ogTitle  = document.querySelector('meta[property="og:title"]');
            const title    = document.querySelector('title');
            const ogDesc   = document.querySelector('meta[property="og:description"]');
            const metaDesc = document.querySelector('meta[name="description"]');
            const favicon  = (
                document.querySelector('link[rel="icon"]') ||
                document.querySelector('link[rel="shortcut icon"]') ||
                document.querySelector('link[rel="apple-touch-icon"]')
            );
            return {
                title:       (ogTitle?.content || title?.textContent || '').trim(),
                description: (ogDesc?.content  || metaDesc?.content  || '').trim(),
                favicon_url: favicon ? favicon.href : '',
                language:    document.documentElement.lang || '',
            };
        }""")
        data["metadata"].update(meta)

        # ── Business name + tagline (extra / markdown only) ───────────────
        extra["business_name"] = page.evaluate("""() => {
            const og = document.querySelector('meta[property="og:site_name"]');
            if (og) return og.content;
            const title = document.querySelector('title');
            return title ? title.textContent.split('|')[0].split('-')[0].trim() : '';
        }""")
        extra["tagline"] = meta.get("description", "")

        # ── Branding: logo ─────────────────────────────────────────────────
        data["branding"]["logo_url"] = page.evaluate("""() => {
            const logoEl = document.querySelector(
                'header img[class*="logo"], nav img[class*="logo"], ' +
                'header img[id*="logo"], nav img[id*="logo"], ' +
                'a[class*="logo"] img, a[id*="logo"] img, ' +
                '[class*="logo"] img, [id*="logo"] img, ' +
                'header img:first-of-type, nav img:first-of-type'
            );
            if (logoEl) return logoEl.src;
            const og = document.querySelector('meta[property="og:image"]');
            return og ? og.content : '';
        }""")

        # ── Branding: color palette ────────────────────────────────────────
        # Categorised into primary / secondary / background buckets
        colors = page.evaluate("""() => {
            const toHex = (rgb) => {
                const m = rgb.match(/rgba?\\((\\d+),\\s*(\\d+),\\s*(\\d+)/);
                if (!m) return null;
                const r = parseInt(m[1]), g = parseInt(m[2]), b = parseInt(m[3]);
                if (r < 5  && g < 5  && b < 5)  return null;  // skip near-black (default)
                if (r > 248 && g > 248 && b > 248) return null; // skip near-white
                return '#' + [r,g,b].map(x => x.toString(16).padStart(2,'0')).join('');
            };
            const result = { primary: [], secondary: [], background: [] };
            const seen = new Set();
            const add = (bucket, color) => {
                if (color && !seen.has(color) && result[bucket].length < 5) {
                    seen.add(color);
                    result[bucket].push(color);
                }
            };
            // 1. CSS custom properties (most reliable)
            const rootStyle = getComputedStyle(document.documentElement);
            const cssVarMap = {
                primary:    ['--primary', '--primary-color', '--color-primary', '--brand', '--accent', '--color-accent'],
                secondary:  ['--secondary', '--secondary-color', '--color-secondary'],
                background: ['--bg', '--background', '--color-bg', '--color-background', '--surface'],
            };
            for (const [bucket, vars] of Object.entries(cssVarMap)) {
                for (const v of vars) {
                    const val = rootStyle.getPropertyValue(v).trim();
                    if (val) add(bucket, val.startsWith('#') ? val : toHex(val) || val);
                }
            }
            // 2. Computed background colours of semantic layout elements → background bucket
            ['body', 'main', 'section', 'footer'].forEach(sel => {
                const el = document.querySelector(sel);
                if (el) add('background', toHex(getComputedStyle(el).backgroundColor));
            });
            // 3. Header / nav / primary buttons → primary bucket
            ['header', 'nav', '[class*="btn"]:not([class*="outline"])', '[class*="cta"]'].forEach(sel => {
                const el = document.querySelector(sel);
                if (el) {
                    add('primary', toHex(getComputedStyle(el).backgroundColor));
                    add('primary', toHex(getComputedStyle(el).color));
                }
            });
            // 4. Secondary / accent elements
            ['h1', 'h2', 'a', '[class*="accent"]'].forEach(sel => {
                const el = document.querySelector(sel);
                if (el) add('secondary', toHex(getComputedStyle(el).color));
            });
            return result;
        }""")
        data["branding"]["color_palette"] = colors

        # ── Branding: typography ───────────────────────────────────────────
        # Use page.evaluate() to read getComputedStyle fontFamily from key elements
        data["branding"]["typography"] = page.evaluate("""() => {
            const fonts = new Set();
            ['body', 'h1', 'h2', 'h3', 'p', 'button'].forEach(sel => {
                const el = document.querySelector(sel);
                if (el) {
                    const ff = getComputedStyle(el).fontFamily;
                    if (ff) fonts.add(ff.split(',')[0].replace(/['"]/g, '').trim());
                }
            });
            return [...fonts].filter(Boolean);
        }""")

        # ── Layout: header links ───────────────────────────────────────────
        data["layout_and_nav"]["header_links"] = page.evaluate("""() => {
            const links = [];
            document.querySelectorAll('nav a, header a').forEach(a => {
                const label = a.textContent.trim();
                const href  = a.getAttribute('href') || '';
                if (label && label.length < 40) links.push({ label, href });
            });
            return [...new Map(links.map(l => [l.label, l])).values()].slice(0, 12);
        }""")

        # ── Layout: footer links ───────────────────────────────────────────
        data["layout_and_nav"]["footer_links"] = page.evaluate("""() => {
            const links = [];
            document.querySelectorAll('footer a').forEach(a => {
                const label = a.textContent.trim();
                const href  = a.getAttribute('href') || '';
                if (label && label.length < 60) links.push({ label, href });
            });
            return [...new Map(links.map(l => [l.label, l])).values()].slice(0, 12);
        }""")

        # ── Contact info ───────────────────────────────────────────────────
        contact_raw = page.evaluate("""() => {
            const text = document.body.innerText;
            const html = document.body.innerHTML;

            // Phones: regex on full DOM text
            const phones = [...text.matchAll(/[+\\d][\\d\\s\\-().]{7,}/g)]
                .map(m => m[0].trim())
                .filter(p => p.replace(/\\D/g, '').length >= 8)
                .slice(0, 3);

            // Emails — three passes for maximum coverage:
            const emailSet = new Set();
            const EMAIL_RE = /[a-zA-Z0-9._%+\\-]+@[a-zA-Z0-9.\\-]+\\.[a-zA-Z]{2,}/g;

            // Pass 1: explicit mailto: links (most reliable)
            document.querySelectorAll('a[href^="mailto:"]').forEach(a => {
                const email = decodeURIComponent(a.href)
                    .replace(/^mailto:/i, '').split('?')[0].trim();
                if (email && EMAIL_RE.test(email)) emailSet.add(email);
                EMAIL_RE.lastIndex = 0;
            });

            // Pass 2: regex on visible text
            [...text.matchAll(EMAIL_RE)].forEach(m => emailSet.add(m[0]));

            // Pass 3: regex on raw HTML (catches JS-rendered or HTML-entity emails)
            const decoded = html
                .replace(/&#64;/g, '@').replace(/&amp;/g, '&')
                .replace(/\\[at\\]/gi, '@').replace(/\\(at\\)/gi, '@')
                .replace(/\\s+at\\s+/gi, '@');
            [...decoded.matchAll(EMAIL_RE)].forEach(m => emailSet.add(m[0]));

            // Physical address
            const addrEl = document.querySelector(
                'address, [class*="address"], [itemprop="address"], [class*="contact"] address'
            );
            const physical_address = addrEl
                ? addrEl.innerText.trim()
                    .split('\\n')
                    .map(l => l.trim())
                    .filter(l => l && !/^P\\.?\\s*IVA\\s+\\d/i.test(l))
                    .join('\\n')
                    .slice(0, 200)
                : '';

            // All social platforms
            const socialPatterns = {
                facebook:  /facebook\\.com/,
                instagram: /instagram\\.com/,
                twitter:   /twitter\\.com|x\\.com/,
                linkedin:  /linkedin\\.com/,
                youtube:   /youtube\\.com/,
                tiktok:    /tiktok\\.com/,
                whatsapp:  /whatsapp\\.com|wa\\.me/,
            };
            const social = {};
            document.querySelectorAll('a[href]').forEach(a => {
                const href = a.href || '';
                for (const [name, rx] of Object.entries(socialPatterns)) {
                    if (!social[name] && rx.test(href)) social[name] = href;
                }
            });

            return {
                phones,
                emails: [...emailSet].slice(0, 5),
                physical_address,
                social,
            };
        }""")
        data["contact_info"]["phones"]           = list(dict.fromkeys(contact_raw.get("phones", [])))
        data["contact_info"]["emails"]           = contact_raw.get("emails", [])
        data["contact_info"]["physical_address"] = contact_raw.get("physical_address", "")
        # Merge scraped social map into the schema skeleton (keeps empty strings for missing)
        scraped_social = contact_raw.get("social", {})
        for platform in data["contact_info"]["social_links"]:
            if scraped_social.get(platform):
                data["contact_info"]["social_links"][platform] = scraped_social[platform]

        # ── Content: H1 / H2 headings ─────────────────────────────────────
        data["content"]["h1_headings"] = page.evaluate("""() =>
            [...document.querySelectorAll('h1')]
                .map(h => h.textContent.trim()).filter(Boolean).slice(0, 5)
        """)
        data["content"]["h2_headings"] = page.evaluate("""() =>
            [...document.querySelectorAll('h2')]
                .map(h => h.textContent.trim()).filter(Boolean).slice(0, 8)
        """)

        # ── Content: CTA buttons ───────────────────────────────────────────
        data["content"]["call_to_action_buttons"] = page.evaluate("""() => {
            const btns = [];
            const sel = [
                'a.btn', 'a[class*="btn"]', 'a[class*="cta"]',
                'button[class*="btn"]', 'button[class*="cta"]',
                '.cta a', '[class*="call-to-action"] a',
                '[class*="hero"] a', '[class*="banner"] a',
            ].join(', ');
            document.querySelectorAll(sel).forEach(el => {
                const text = el.textContent.trim();
                const link = el.getAttribute('href') || el.getAttribute('data-href') || '';
                if (text && text.length < 80) btns.push({ text, link });
            });
            return [...new Map(btns.map(b => [b.text, b])).values()].slice(0, 6);
        }""")

        # ── Content: hero image ────────────────────────────────────────────
        data["content"]["hero_image_url"] = page.evaluate("""() => {
            const hero = document.querySelector(
                '.hero img, #hero img, [class*="hero"] img, header img, .banner img'
            );
            if (hero) return hero.src;
            // Fallback: first element with a background-image
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

        # ── Content: image gallery ─────────────────────────────────────────
        data["content"]["image_gallery"] = page.evaluate("""() => {
            const imgs = [];
            document.querySelectorAll('img').forEach(img => {
                const url = img.src || '';
                const w   = img.naturalWidth  || img.width  || 0;
                const h   = img.naturalHeight || img.height || 0;
                if (url && w > 200 && h > 150 && !url.includes('logo') && !url.includes('icon'))
                    imgs.push({ url, alt_text: img.alt || '' });
            });
            return imgs.slice(0, 8);
        }""")

        # ── Extra: services (for markdown only) ───────────────────────────
        extra["services"] = page.evaluate("""() => {
            const services = [];
            const sel = '[class*="service"], [class*="card"], [class*="offer"], [class*="feature"], article, .item';
            document.querySelectorAll(sel).forEach(el => {
                const heading = el.querySelector('h2,h3,h4,h5');
                const body    = el.querySelector('p');
                if (heading) services.push({
                    title:       heading.textContent.trim(),
                    description: body ? body.textContent.trim().slice(0, 200) : '',
                });
            });
            return services.slice(0, 6);
        }""")

        # ── Extra: about text (for markdown only) ─────────────────────────
        extra["about"] = page.evaluate("""() => {
            const COOKIE_KW = ['cookie', 'gdpr', 'privacy policy', 'consenso', 'informazioni sul tuo browser'];
            const isCookie  = t => COOKIE_KW.some(k => t.toLowerCase().includes(k));
            const about = document.querySelector(
                '[class*="about"], #about, [id*="about"], [class*="chi-siamo"], #chi-siamo'
            );
            if (about) {
                const t = about.innerText.trim();
                if (!isCookie(t)) return t.slice(0, 800);
            }
            const paras = [...document.querySelectorAll('p')]
                .map(p => p.textContent.trim())
                .filter(t => t.length > 80 && !isCookie(t));
            return paras.sort((a, b) => b.length - a.length)[0]?.slice(0, 800) || '';
        }""")

        # ── Extra: testimonials (for markdown only) ────────────────────────
        extra["testimonials"] = page.evaluate("""() => {
            const results = [];
            document.querySelectorAll(
                '[class*="testimon"], [class*="review"], [class*="quote"], blockquote'
            ).forEach(el => {
                const text = el.textContent.trim();
                if (text.length > 20) results.push({ quote: text.slice(0, 300) });
            });
            return results.slice(0, 3);
        }""")

        # ── Extra: raw text sections (for markdown only) ──────────────────
        extra["raw_text_sections"] = page.evaluate("""() => {
            const COOKIE_KW = ['cookie', 'gdpr', 'consenso', 'privacy policy'];
            const isCookie  = t => COOKIE_KW.some(k => t.toLowerCase().includes(k));
            const sections  = {};
            document.querySelectorAll('section, main > div, article').forEach((el, i) => {
                const text = el.innerText?.trim();
                if (text && text.length > 50 && !isCookie(text)) {
                    const id = el.id || el.className.split(' ')[0] || 'section-' + i;
                    sections[id] = text.slice(0, 600);
                }
            });
            return sections;
        }""")

        browser.close()

    return data, extra


def build_markdown(data: dict, extra: dict) -> str:
    """Build a human-readable markdown summary for create.sh to inject into AI prompts."""
    biz_name = extra.get("business_name") or data["metadata"].get("title") or "Unknown Business"
    lines = [f"# {biz_name}", ""]
    lines += [f"**Source:** {data['site_url']}", ""]

    tagline = extra.get("tagline") or data["metadata"].get("description", "")
    if tagline:
        lines += [f"**Tagline:** {tagline}", ""]

    lang = data["metadata"].get("language", "")
    if lang:
        lines += [f"**Language:** {lang}", ""]

    # Contact
    ci = data["contact_info"]
    if ci.get("physical_address"):
        lines += [f"**Address:** {ci['physical_address']}", ""]
    if ci.get("phones"):
        lines += [f"**Phone:** {', '.join(ci['phones'])}", ""]
    if ci.get("emails"):
        lines += [f"**Email:** {', '.join(ci['emails'])}", ""]

    # About
    if extra.get("about"):
        lines += ["## About", extra["about"], ""]

    # Services
    if extra.get("services"):
        lines += ["## Services"]
        for s in extra["services"]:
            lines.append(f"- **{s['title']}**: {s['description']}")
        lines.append("")

    # Social links — filter to non-empty entries only
    social = {k: v for k, v in data["contact_info"].get("social_links", {}).items() if v}
    if social:
        lines += ["## Social Links"]
        for k, v in social.items():
            lines.append(f"- {k}: {v}")
        lines.append("")

    # Navigation
    header_links = data["layout_and_nav"].get("header_links", [])
    if header_links:
        nav = ", ".join(l["label"] for l in header_links)
        lines += [f"**Nav:** {nav}", ""]

    # Headings
    if data["content"].get("h1_headings"):
        lines += [f"**H1:** {' | '.join(data['content']['h1_headings'])}", ""]
    if data["content"].get("h2_headings"):
        lines += ["## H2 Headings"]
        for h in data["content"]["h2_headings"]:
            lines.append(f"- {h}")
        lines.append("")

    # CTA buttons
    if data["content"].get("call_to_action_buttons"):
        lines += ["## Call-to-Action Buttons"]
        for b in data["content"]["call_to_action_buttons"]:
            lines.append(f"- [{b['text']}]({b['link']})")
        lines.append("")

    # Testimonials
    if extra.get("testimonials"):
        lines += ["## Testimonials"]
        for t in extra["testimonials"]:
            lines.append(f'> {t["quote"]}')
        lines.append("")

    # Colors
    cp = data["branding"].get("color_palette", {})
    any_colors = cp.get("primary") or cp.get("secondary") or cp.get("background")
    if any_colors:
        lines += ["## Brand Colors"]
        if cp.get("primary"):
            lines.append(f"- Primary:    {', '.join(cp['primary'])}")
        if cp.get("secondary"):
            lines.append(f"- Secondary:  {', '.join(cp['secondary'])}")
        if cp.get("background"):
            lines.append(f"- Background: {', '.join(cp['background'])}")
        lines.append("")

    # Typography
    if data["branding"].get("typography"):
        lines += [f"**Fonts detected:** {', '.join(data['branding']['typography'])}", ""]

    # Logo
    if data["branding"].get("logo_url"):
        lines += [f"**Logo URL:** {data['branding']['logo_url']}", ""]

    # Gallery
    gallery = data["content"].get("image_gallery", [])
    if gallery:
        lines += ["## Gallery Images (URLs for reference)"]
        for img in gallery:
            lines.append(f"- {img['url']} (alt: {img['alt_text']})")
        lines.append("")

    # Raw text sections (fallback content for AI)
    sections = extra.get("raw_text_sections", {})
    if sections:
        lines += ["## Raw Text Sections"]
        for k, v in list(sections.items())[:5]:
            lines.append(f"### {k}")
            lines.append(v[:300])
            lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Scrape a website for frontend-clone data")
    parser.add_argument("url", help="URL to scrape")
    parser.add_argument("--out", default="scrapes", help="Output base directory (default: scrapes)")
    args = parser.parse_args()

    url = args.url
    if not url.startswith("http"):
        url = "https://" + url

    slug    = slugify(url)
    out_dir = Path(args.out) / slug

    print(f"Scraping {url} → {out_dir}/")
    data, extra = scrape(url, out_dir)

    # Save JSON (strictly the schema — no extra fields)
    json_path = out_dir / "data.json"
    json_path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    print(f"Data saved → {json_path}")

    # Save human-readable markdown (includes extra fields for create.sh AI context)
    md      = build_markdown(data, extra)
    md_path = out_dir / "raw.md"
    md_path.write_text(md, encoding="utf-8")
    print(f"Summary saved → {md_path}")

    # Print truncated summary to stdout
    print("\n" + "─" * 60)
    md_lines = md.splitlines()
    print("\n".join(md_lines[:15]))
    if len(md_lines) > 15:
        print(f"... ({len(md_lines) - 15} more lines truncated. see raw.md for full details)")


if __name__ == "__main__":
    main()
