---
name: frontend-design
description: Create distinctive, production-grade frontend interfaces with high design quality. Use this skill when the user asks to build web components, pages, or applications. Generates creative, polished code that avoids generic AI aesthetics.
license: Complete terms in LICENSE.txt
---

This skill guides creation of distinctive, production-grade frontend interfaces that avoid generic "AI slop" aesthetics. Implement real working code with exceptional attention to aesthetic details and creative choices.

The user provides frontend requirements: a component, page, application, or interface to build. They may include context about the purpose, audience, or technical constraints.

## Design Thinking

Before coding, understand the context and commit to a BOLD aesthetic direction:

- **Purpose**: What problem does this interface solve? Who uses it?
- **Tone**: Pick an extreme: brutally minimal, maximalist chaos, retro-futuristic, organic/natural, luxury/refined, playful/toy-like, editorial/magazine, brutalist/raw, art deco/geometric, soft/pastel, industrial/utilitarian, etc. There are so many flavors to choose from. Use these for inspiration but design one that is true to the aesthetic direction.
- **Constraints**: Technical requirements (framework, performance, accessibility).
- **Differentiation**: What makes this UNFORGETTABLE? What's the one thing someone will remember?

**CRITICAL**: Choose a clear conceptual direction and execute it with precision. Bold maximalism and refined minimalism both work - the key is intentionality, not intensity.

Then implement working code (HTML/CSS/JS, React, Vue, etc.) that is:

- Production-grade and functional
- Visually striking and memorable
- Cohesive with a clear aesthetic point-of-view
- Meticulously refined in every detail

## Frontend Aesthetics Guidelines

Focus on:

- **Typography**: Choose fonts that are beautiful, unique, and interesting. Avoid generic fonts like Arial and Inter; opt instead for distinctive choices that elevate the frontend's aesthetics; unexpected, characterful font choices. Pair a distinctive display font with a refined body font.
- **Color & Theme**: Commit to a cohesive aesthetic. Use CSS variables for consistency. Dominant colors with sharp accents outperform timid, evenly-distributed palettes.
- **Motion**: Use animations for effects and micro-interactions. Prioritize CSS-only solutions for HTML. Use Motion library for React when available. Focus on high-impact moments: one well-orchestrated page load with staggered reveals (animation-delay) creates more delight than scattered micro-interactions. Use scroll-triggering and hover states that surprise.
- **Spatial Composition**: Unexpected layouts. Asymmetry. Overlap. Diagonal flow. Grid-breaking elements. Generous negative space OR controlled density.
- **Backgrounds & Visual Details**: Create atmosphere and depth rather than defaulting to solid colors. Add contextual effects and textures that match the overall aesthetic. Apply creative forms like gradient meshes, noise textures, geometric patterns, layered transparencies, dramatic shadows, decorative borders, custom cursors, and grain overlays.

NEVER use generic AI-generated aesthetics like overused font families (Inter, Roboto, Arial, system fonts), cliched color schemes (particularly purple gradients on white backgrounds), predictable layouts and component patterns, and cookie-cutter design that lacks context-specific character.

Interpret creatively and make unexpected choices that feel genuinely designed for the context. No design should be the same. Vary between light and dark themes, different fonts, different aesthetics. NEVER converge on common choices (Space Grotesk, for example) across generations.

**IMPORTANT**: Match implementation complexity to the aesthetic vision. Maximalist designs need elaborate code with extensive animations and effects. Minimalist or refined designs need restraint, precision, and careful attention to spacing, typography, and subtle details. Elegance comes from executing the vision well.

Remember: Claude is capable of extraordinary creative work. Don't hold back, show what can truly be created when thinking outside the box and committing fully to a distinctive vision.

## Asset & File Structure Rules

**CRITICAL**: Every frontend project MUST follow these rules:

### Local Assets Only — No External Image URLs

- **NEVER** use external image URLs (no `unsplash.com`, no `placeholder.com`, no CDN-hosted images).
- All images MUST be local files in an `assets/` folder with relative paths.
- If images already exist in the `assets/` folder, just reference them. Do NOT regenerate.
- If no images exist yet, use the **nano-banana-pro** skill to generate them before building the HTML.
- Reference images as: `src="assets/image-name.png"` (relative paths).
- Every `<img>` tag MUST have descriptive `alt` text.

### Separate CSS File

- **NEVER** put CSS inside `<style>` tags in the HTML file.
- All CSS goes in a separate `style.css` file.
- Link it in the HTML `<head>`: `<link rel="stylesheet" href="style.css">`
- Use `@import` for Google Fonts at the top of `style.css`.

### JavaScript Safety

- **NEVER** use `window` as a variable name in loops or callbacks (e.g. `forEach(window => ...)`). Use `el` or `element` instead.
- All page content MUST be visible without JavaScript. If using scroll-reveal animations, elements must be visible by default in CSS. Only hide them via JS after the script loads — so if JS fails, content is still visible.
- Prefer CSS animations (`@keyframes`, `transition`) over JS where possible.
- Keep inline scripts minimal and bug-free.

### Expected Output Structure

```
project/
├── assets/
│   ├── hero.png
│   ├── gallery-1.png
│   └── ...
├── index.html
└── style.css
```

### Workflow

1. **Check if images exist** in the `assets/` folder. If they do, skip to step 3.
2. **Generate images** using nano-banana-pro into the `assets/` folder (only if needed).
3. **Build the HTML** referencing local `assets/` paths. Use ALL available images.
4. **Write the CSS** in a separate `style.css` file.
5. **Never use placeholder or external image URLs**

## Output Rules

### No Preamble

When outputting code, start IMMEDIATELY with the code. Do NOT output explanation, commentary, or thinking text before the code. Your very first character should be `<` (the start of `<!DOCTYPE html>`).

### Combined HTML + CSS Output

When generating both HTML and CSS together, use this delimiter format:

```
<!DOCTYPE html>
<html lang="...">
...
</html>
===STYLE_CSS===
@import url('...');
:root { ... }
...
```

Output the complete HTML first, then `===STYLE_CSS===` on its own line, then the complete CSS. No markdown code blocks, just raw code.
