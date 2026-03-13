---
name: frontend-design
description: Create distinctive, production-grade business landing pages. Use this skill when building web pages or components. Generates creative, polished single-file HTML+CSS that works reliably on first attempt.
license: Complete terms in LICENSE.txt
---

This skill guides creation of business landing pages that are visually polished and structurally reliable. The goal is a one-shot page that looks professional, loads fast, and works perfectly on mobile.

## Design Direction

Before coding, commit to a cohesive design direction based on the business niche:

- **Typography**: Pick a distinctive Google Fonts pairing — one display font for headings, one readable font for body. NEVER use Inter, Roboto, Arial, or system fonts.
- **Color palette**: 3-4 colors max using CSS custom properties. A dark primary, a strong accent, and neutrals. Match the niche (warm golds for luxury, clean blues for professional, rich greens for organic, etc.).
- **Tone**: Professional and polished. Not flashy-for-the-sake-of-flashy. The page should feel like it was designed by a human for this specific business.

## Structural Blueprint

Every landing page MUST contain exactly these 9 sections in this order. Do not duplicate or skip any section.

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

Every page MUST include a working hamburger menu for mobile. Use this pattern:

```html
<!-- In the nav -->
<input type="checkbox" id="nav-toggle" class="nav-toggle-checkbox">
<label for="nav-toggle" class="nav-toggle-label" aria-label="Menu">
  <i class="fas fa-bars"></i>
</label>
```

```css
/* Hide checkbox */
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

Adapt class names and colors to match the page design, but the checkbox-toggle pattern is mandatory.

## Scroll Reveal Animations (REQUIRED)

Include this JavaScript at the bottom of the HTML (inside a `<script>` tag) for scroll-triggered reveal animations:

```html
<script>
  // Scroll reveal
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

  // Sticky header shadow on scroll
  window.addEventListener('scroll', () => {
    document.querySelector('header').classList.toggle('scrolled', window.scrollY > 50);
  });

  // Smooth scroll for anchor links
  document.querySelectorAll('a[href^="#"]').forEach(a => {
    a.addEventListener('click', e => {
      e.preventDefault();
      const target = document.querySelector(a.getAttribute('href'));
      if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  });
</script>
```

Add `class="reveal"` to each major section (`<section>`). In the CSS, include:

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

## Asset & File Rules

### Images — CRITICAL

- ALL images are PRE-GENERATED in the `assets/` folder. Do NOT generate images.
- Use **only** these 6 files (WebP format):
  - `assets/hero.webp` — hero background
  - `assets/gallery-1.webp` — gallery item 1
  - `assets/gallery-2.webp` — gallery item 2
  - `assets/workshop.webp` — about/workspace section
  - `assets/detail.webp` — detail/feature highlight
  - `assets/process.webp` — process/how-it-works section
- Reference with relative paths: `src="assets/hero.webp"`
- **NEVER** reference any other image files (no `logo.png`, no `dummy.png`, no `avatar.png`)
- **NEVER** use external image URLs (no unsplash.com, no placeholder services)
- Every `<img>` MUST have descriptive `alt` text
- Use ALL 6 images. Do not skip any.

### Separate HTML and CSS

- **NEVER** put CSS inside `<style>` tags in the HTML file.
- **NEVER** use inline `style="..."` attributes in HTML elements.
- All CSS goes in `style.css`, linked in `<head>`: `<link rel="stylesheet" href="style.css">`
- Use `@import` for Google Fonts at the top of `style.css`.

### CDN Links

- Use Font Awesome for icons: `<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.0/css/all.min.css">`
- Do NOT add `integrity=` or `crossorigin=` attributes to any CDN link.

### JavaScript Safety

- **NEVER** use `window` as a variable name in loops or callbacks (e.g., `forEach(window => ...)`). Use `el` or `element`.
- Do NOT link to external `.js` files (no `<script src="script.js">`). All JS goes inline in a `<script>` tag before `</body>`.

## CSS Requirements

The CSS (`style.css`) must include:

1. **CSS custom properties** at `:root` for all colors and font families
2. **Reset**: `*, *::before, *::after { margin: 0; padding: 0; box-sizing: border-box; }`
3. **Responsive breakpoint** at `max-width: 768px` for all grid/flex layouts
4. **Hero section**: `min-height: 90vh`, background image with dark overlay using `::before` pseudo-element, text on top with `position: relative` and `z-index: 1`
5. **Hover effects** on buttons, nav links, service cards, and gallery items
6. **Smooth transitions** on interactive elements: `transition: all 0.3s ease`
7. **The `.reveal` / `.revealed` animation classes** as shown above
8. **Header `.scrolled` state** with background color and shadow

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

When outputting code, start IMMEDIATELY with the code. Do NOT output explanation, commentary, font choices, color palettes, or thinking text before the code.

- For HTML: Your very first character MUST be `<` (the start of `<!DOCTYPE html>`)
- For CSS: Your very first character MUST be `@` (for `@import`) or `/` (for `/* comment */`) or `:` (for `:root`)
- Do NOT wrap output in markdown code blocks (no triple backticks)
- Do NOT output anything after the closing `</html>` tag
