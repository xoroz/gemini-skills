---
name: frontend-clone
description: Generate a polished landing page using real data scraped from an existing business website. Combines frontend-design visual quality with actual business content. Use when asked to clone, redesign, or rebuild a site with real data.
license: Complete terms in LICENSE.txt
---

This skill generates a production-grade landing page populated with **real data scraped from an existing website**. It follows the same design standards as `frontend-design` but replaces placeholder content with actual business information.

## Step 1 — Scrape the target site

Before writing any code, run the scraper to collect real business data:

```bash
venv/bin/python scripts/scrape_site.py <URL>
```

This creates `scrapes/<domain>/data.json` and `scrapes/<domain>/raw.md` with:
- Business name, tagline, description
- Services / offerings
- Contact info (address, phone, email)
- Social media links
- Nav structure
- Detected brand colors and fonts
- Gallery image URLs (for reference only — do NOT hotlink)
- Testimonials (if found)
- Raw text sections

Read `scrapes/<domain>/raw.md` to understand the business before generating the page.

## Step 2 — Design Direction

Apply the **same design standards as `frontend-design`**:

- **Typography**: Pick a Google Fonts pairing that fits the business niche. If the scrape detected a font, prefer it or a harmonious companion. NEVER use Inter, Roboto, Arial, or system fonts.
- **Color palette**: Base the palette on detected brand colors from the scrape. Adapt to a 3-4 color system with CSS custom properties. If no useful colors were detected, choose a fitting palette for the niche.
- **Tone**: Match the business personality — a travel agency feels adventurous and warm; a law firm feels authoritative and minimal; a restaurant feels inviting and sensory.

## Step 3 — Populate with real data

Use the scraped data to fill every section with real content:

| Section | Data source |
|---------|-------------|
| **Business name / logo text** | `business_name` |
| **Nav links** | `nav_links` (adapt to page anchors) |
| **Hero headline** | `tagline` or derived from `description` |
| **Hero subtitle** | `description` or `about` (truncated) |
| **Services cards** | `services` list (use scraped titles + descriptions) |
| **About section** | `about` text |
| **Contact info** | `address`, `phone`, `email` |
| **Social links** | `social_links` map |
| **Testimonials** | `testimonials` (if scraped) |
| **Footer** | business name + social icons |

If a field is empty, write natural-sounding placeholder text fitting the business type — do NOT leave visible gaps or lorem ipsum.

## Step 4 — Structural Blueprint

Follow the **exact same 9-section structure** as `frontend-design`:

```text
1. Header/Nav    → sticky, flex: logo left · nav links center · CTA button right · hamburger for mobile
2. Hero          → full-width background image, overlay, headline, subtitle, 2 CTA buttons
3. Services      → 3-6 service cards with Font Awesome icons, title, short description
4. Gallery       → 2-3 images in a grid with hover overlay captions
5. About         → split layout: image left, text right (or reversed)
6. Process       → 3-4 numbered steps with icons or image
7. Testimonials  → 1-3 customer quotes with name and role (no avatar images)
8. Contact       → split: info (address, phone, social links) + form (name, email, phone, message, submit)
9. Footer        → logo, social icons, copyright line
```

## Mobile Navigation (REQUIRED)

Every page MUST include a working hamburger menu. Use this exact checkbox-toggle pattern:

```html
<input type="checkbox" id="nav-toggle" class="nav-toggle-checkbox">
<label for="nav-toggle" class="nav-toggle-label" aria-label="Menu">
  <i class="fas fa-bars"></i>
</label>
```

```css
.nav-toggle-checkbox { display: none; }
.nav-toggle-label { display: none; cursor: pointer; font-size: 1.5rem; }

@media (max-width: 768px) {
  .nav-toggle-label { display: block; }
  .nav-links {
    display: none;
    position: absolute;
    top: 100%;
    left: 0;
    right: 0;
    background: var(--color-bg);
    flex-direction: column;
    padding: 1rem;
  }
  .nav-toggle-checkbox:checked ~ .nav-links { display: flex; }
  .nav-cta { display: none; }
}
```

## Scroll Reveal Animations (REQUIRED)

Include this JavaScript before `</body>`:

```html
<script>
  const revealEls = document.querySelectorAll('.reveal');
  const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        entry.target.classList.add('revealed');
        observer.unobserve(entry.target);
      }
    });
  }, { threshold: 0.15 });
  revealEls.forEach(el => observer.observe(el));

  window.addEventListener('scroll', () => {
    document.querySelector('header').classList.toggle('scrolled', window.scrollY > 50);
  });

  document.querySelectorAll('a[href^="#"]').forEach(a => {
    a.addEventListener('click', e => {
      e.preventDefault();
      const target = document.querySelector(a.getAttribute('href'));
      if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  });
</script>
```

## Asset & File Rules

### Images — CRITICAL

- ALL images are PRE-GENERATED in the `assets/` folder. Do NOT hotlink to the scraped site's images.
- Use **only** these 6 files (WebP format):
  - `assets/hero.webp`
  - `assets/gallery-1.webp`
  - `assets/gallery-2.webp`
  - `assets/workshop.webp`
  - `assets/detail.webp`
  - `assets/process.webp`
- Reference with relative paths: `src="assets/hero.webp"`
- **NEVER** reference scraped image URLs in `<img src>` or CSS `background-image`
- The scraped image URLs in `raw.md` are for **content/alt-text inspiration only**
- Every `<img>` MUST have descriptive `alt` text based on the real business
- Use ALL 6 images. Do not skip any.

### Separate HTML and CSS

- **NEVER** put CSS inside `<style>` tags in the HTML file.
- **NEVER** use inline `style="..."` attributes.
- All CSS goes in `style.css`, linked in `<head>`: `<link rel="stylesheet" href="style.css">`
- Use `@import` for Google Fonts at the top of `style.css`.

### CDN Links

- Font Awesome: `<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.0/css/all.min.css">`
- Do NOT add `integrity=` or `crossorigin=` attributes.

### JavaScript Safety

- **NEVER** use `window` as a variable name in loops or callbacks. Use `el` or `element`.
- All JS inline in a `<script>` tag before `</body>`. No external `.js` files.

## CSS Requirements

`style.css` must include:

1. **CSS custom properties** at `:root` for all colors and font families
2. **Reset**: `*, *::before, *::after { margin: 0; padding: 0; box-sizing: border-box; }`
3. **Responsive breakpoint** at `max-width: 768px`
4. **Hero section**: `min-height: 90vh`, dark overlay via `::before` pseudo-element
5. **Hover effects** on buttons, nav links, service cards, gallery items
6. **Smooth transitions**: `transition: all 0.3s ease`
7. **`.reveal` / `.revealed` animation classes**
8. **Header `.scrolled` state** with background and shadow

```css
.reveal {
  opacity: 0;
  transform: translateY(30px);
  transition: opacity 0.6s ease, transform 0.6s ease;
}
.reveal.revealed {
  opacity: 1;
  transform: translateY(0);
}
```

## Expected Output Structure

```
project/
├── assets/
│   ├── hero.webp
│   ├── gallery-1.webp
│   ├── gallery-2.webp
│   ├── workshop.webp
│   ├── detail.webp
│   └── process.webp
├── index.html
└── style.css
```

## Output Rules

### No Preamble — CRITICAL

- For HTML: first character MUST be `<`
- For CSS: first character MUST be `@` or `/` or `:`
- Do NOT wrap output in markdown code blocks
- Do NOT output anything after `</html>`
- Do NOT explain font or color choices before the code
