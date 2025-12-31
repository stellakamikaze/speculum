# Speculum Redesign - Implementation Plan

## Overview

Complete redesign of Speculum following Minimalist Monochrome design system, with UX restructuring, internationalization, and new features.

## Current State

- **Stack**: Flask + Jinja2 + Custom CSS
- **Design**: Dark Academia (warm colors, serif fonts, shadows, rounded corners)
- **Language**: Italian only
- **Structure**: Admin mixed with public pages

## Target State

- **Design**: Minimalist Monochrome (pure B&W, no shadows, sharp corners, editorial)
- **Language**: English primary + i18n (EN/IT)
- **Structure**: Public frontend / Hidden admin backend
- **New Features**: Media gallery, AI screening, Ghost integration prep

---

## Epic 1: Design System Foundation

### 1.1 Create new CSS design tokens
- Replace color palette with pure B&W (#000/#FFF)
- Remove all shadows, set border-radius to 0
- Update typography to Playfair Display + Source Serif 4
- Define line-based visual system (hairline to ultra borders)

### 1.2 Implement textures and patterns
- Horizontal lines pattern for backgrounds
- Grid pattern for editorial sections
- Noise texture for paper-like quality
- Inverted section textures (white on black)

### 1.3 Create component styles
- Buttons: Primary (black), Secondary (outline), Ghost
- Cards: Standard, Inverted, Borderless
- Inputs: Bottom-border style, thick focus state
- Typography scale (xs to 9xl)

---

## Epic 2: Internationalization (i18n)

### 2.1 Setup Flask-Babel
- Install and configure Flask-Babel
- Create translations directory structure
- Extract translatable strings

### 2.2 Create translation files
- English (en) - primary language
- Italian (it) - secondary language

### 2.3 Implement language selector
- Dropdown/toggle in header
- Persist preference in cookie/session
- Update all templates to use gettext

---

## Epic 3: UX Restructuring

### 3.1 Public Frontend Pages
- **Homepage**: Hero + media gallery + random sites + request CTA
- **Catalog**: Browse all archived sites
- **Site Detail**: View archived site with metadata
- **Search**: Full-text search
- **Request Archive**: Public submission form
- **About**: Institutional page (placeholder)
- **Privacy**: Privacy policy (placeholder)
- **Contact**: Contact form (placeholder)

### 3.2 Admin Backend (Hidden)
- Move all admin routes to /admin/*
- Single login link in footer (subtle)
- Dashboard, Users, Requests, Backup, Export
- Add/Edit sites, Categories management

### 3.3 Navigation Restructure
- Public nav: Home, Catalog, Search, Request, About
- Admin nav: Only visible after login
- Footer: About, Privacy, Contact, Login (small)

---

## Epic 4: Homepage Redesign

### 4.1 Hero Section
- Oversized typography (8xl/9xl)
- Tagline: "Preserving the web, one site at a time"
- Thick horizontal rule with decorative square
- Clear CTA: "Request an Archive"

### 4.2 Media Gallery Section
- Extract best media from crawled sites
- Horizontal scroll or grid layout
- Hover effects with border thickening
- Link to source site

### 4.3 Featured Sites Section
- Random selection of archived sites
- Card layout with site preview/screenshot
- Site name, category, crawl date
- Click to view archived site

### 4.4 Request CTA Section
- Inverted section (black bg, white text)
- Clear call-to-action for submissions
- Simple form or link to request page

---

## Epic 5: AI Integration Enhancements

### 5.1 Pre-crawl Screening
- Before crawl: fetch URL, extract metadata
- Use Ollama to generate:
  - Site description (1-2 sentences)
  - Suggested category
  - Content type (blog, portfolio, news, etc.)
  - Language detection
- Store in CulturalMetadata model

### 5.2 Post-crawl Review
- After successful crawl: re-analyze with actual content
- Update description based on crawled pages
- Extract key topics/tags
- Verify/update category suggestion

### 5.3 Ghost Integration Prep
- Sites as "entries" with rich metadata
- Export format compatible with Ghost import
- Prepare API endpoints for future Ghost sync

---

## Epic 6: Template Updates

### 6.1 Base Template
- Update to Minimalist Monochrome
- New nav structure (public vs admin)
- Language selector in header
- Updated footer with login link

### 6.2 Public Templates
- index.html (new homepage)
- catalog.html (sites listing)
- site_detail.html (archived site view)
- search.html (search results)
- request_mirror.html (submission form)
- about.html, privacy.html, contact.html (institutional)

### 6.3 Admin Templates
- admin/dashboard.html
- admin/sites.html (add/edit)
- admin/requests.html
- admin/users.html
- admin/backup.html
- admin/export.html

---

## Implementation Order

1. **Phase 1**: Design System (Epic 1) - Foundation
2. **Phase 2**: i18n Setup (Epic 2) - Before template changes
3. **Phase 3**: UX Restructure (Epic 3) - Routes and navigation
4. **Phase 4**: Templates (Epic 6) - Apply new design
5. **Phase 5**: Homepage (Epic 4) - New features
6. **Phase 6**: AI Enhancements (Epic 5) - Backend improvements

---

## Files to Create/Modify

### New Files
- `static/css/design-tokens.css` - New design system
- `translations/en/LC_MESSAGES/messages.po`
- `translations/it/LC_MESSAGES/messages.po`
- `templates/admin/base_admin.html`
- `templates/admin/*.html` (admin pages)

### Modified Files
- `static/css/style.css` - Complete rewrite
- `templates/base.html` - New structure
- `templates/*.html` - Apply new design + i18n
- `app/__init__.py` - Add i18n, restructure routes
- `app/models.py` - Extend CulturalMetadata

---

## Success Criteria

- [ ] Pure black & white design, no colors
- [ ] Sharp corners everywhere (0px radius)
- [ ] No shadows, line-based depth
- [ ] Oversized editorial typography
- [ ] English as primary language
- [ ] Language switcher functional
- [ ] Admin hidden from public
- [ ] Media gallery on homepage
- [ ] AI pre-screening working
- [ ] Ghost-compatible export
