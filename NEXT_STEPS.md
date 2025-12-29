# Speculum - Next Steps & Roadmap

Documento di pianificazione per lo sviluppo futuro di Speculum, basato su ricerche sulle best practice di web archiving e analisi di tool simili.

---

## Domande per Definire le Priorita

### Scala e Storage
1. **Quanti siti pensi di archiviare?** Decine, centinaia, o migliaia?
2. **Quali sono i limiti di storage su Unraid?** Serve un sistema di alert quando lo spazio scende sotto una soglia?
3. **Vuoi archiviare anche siti molto grandi** (es. forum con migliaia di pagine) o principalmente siti piccoli/medi?

### Utenti e Accesso
4. **Chi sono gli utenti che richiedono mirror?** Conosciuti o completamente anonimi?
5. **Serve un sistema anti-spam** (captcha, validazione email) per le richieste pubbliche?
6. **Vuoi permettere ad altri utenti di sfogliare i mirror** o solo tu come admin?

### Funzionalita
7. **Ti serve cercare dentro i contenuti archiviati** (full-text search) o basta la ricerca per nome/URL?
8. **Vuoi vedere le differenze tra versioni** di un sito nel tempo?
9. **Interessa l'integrazione con Wayback Machine** per recuperare versioni storiche?

### Notifiche e Integrazioni
10. **Usi gia Telegram?** Ti interesserebbero anche notifiche email o webhook?
11. **Hai altri servizi su Unraid** con cui vorresti integrare Speculum?
12. **Ti interessa un'API REST** per automazioni esterne?

---

## Funzionalita Proposte

### Alta Priorita (Utilita Immediata)

#### 1. Backup e Disaster Recovery
- **Export automatico del database** in formato JSON/SQL
- **Lista siti esportabile** per reimportazione rapida
- **Checksum dei file** per verificare integrita (bagit)
- Riferimento: [Best Practices for Digital Content Archiving](https://web.tapereal.com/blog/6-best-practices-for-digital-content-archiving-2024/)

#### 2. Storage Dashboard
- **Spazio usato/disponibile** per volume
- **Alert configurabili** quando spazio < X%
- **Dimensione per sito** con ordinamento
- **Pulizia automatica** siti piu vecchi (opzionale)

#### 3. Ricerca Full-Text
- **Indicizzazione contenuti HTML** con Whoosh o Elasticsearch
- **Ricerca per parole chiave** nei siti archiviati
- **Highlight dei risultati** nelle pagine
- Riferimento: ArchiveBox usa full-text search integrato

#### 4. Screenshot Automatici
- **Generazione thumbnail** al completamento crawl
- **Playwright o Selenium** per rendering JavaScript
- **Full-page screenshot** opzionale
- Riferimento: [How to take screenshots with Playwright](https://playwright.dev/python/docs/screenshots)

#### 5. Formato WARC (Standard ISO)
- **Esportazione in WARC** per compatibilita con altri tool
- **Standard ISO 28500:2009** usato da Library of Congress, Internet Archive
- **Compressione GZIP** per risparmio spazio
- Riferimento: [WARC Format - Library of Congress](https://www.loc.gov/preservation/digital/formats/fdd/fdd000236.shtml)

---

### Media Priorita (Nice to Have)

#### 6. Sistema di Tag
- **Tag multipli per sito** oltre alla categoria singola
- **Filtro per tag** nella vista catalogo
- **Tag cloud** per navigazione visuale

#### 7. Collections/Progetti
- **Raggruppare siti** in collezioni tematiche
- **Condivisione collezioni** con link pubblico
- **Export collezione** come archivio ZIP

#### 8. Diff tra Versioni
- **Confronto visuale** tra crawl successivi
- **Highlight modifiche** nel testo
- **Timeline** delle versioni di un sito

#### 9. RSS Feed
- **Feed delle nuove archiviazioni**
- **Feed per categoria**
- **Feed personalizzati** per utenti registrati

#### 10. API REST Pubblica
```
GET  /api/v1/sites
GET  /api/v1/sites/{id}
POST /api/v1/sites
GET  /api/v1/search?q=keyword
GET  /api/v1/categories
```
- **Autenticazione API key**
- **Rate limiting per key**
- **Documentazione OpenAPI/Swagger**

#### 11. Notifiche Email
- **Alternativa a Telegram**
- **Template HTML** per notifiche
- **Digest giornaliero/settimanale**

#### 12. Captcha per Richieste
- **hCaptcha o reCAPTCHA** per form pubblici
- **Honeypot fields** come alternativa leggera
- **Rate limiting per IP** (gia presente, da rafforzare)

---

### Bassa Priorita (Future)

#### 13. PWA (Progressive Web App)
- **Installabile su mobile**
- **Notifiche push**
- **Offline browsing** del catalogo

#### 14. Wayback Machine Integration
- **Import da archive.org** di versioni storiche
- **Confronto con versione attuale**
- **Fallback automatico** se sito irraggiungibile

#### 15. Statistiche Avanzate
- **Grafici trend** (siti aggiunti nel tempo, spazio usato)
- **Analytics per categoria**
- **Report PDF** esportabili

#### 16. Multi-User Permissions
- **Ruoli granulari** (viewer, editor, admin per categoria)
- **Audit log** delle azioni
- **Two-factor authentication**

---

## Miglioramenti Tecnici

### Infrastruttura

| Miglioramento | Descrizione | Priorita |
|---------------|-------------|----------|
| **Redis per rate limiting** | Persistenza tra restart, clustering | Alta |
| **Celery per crawl** | Code di lavoro robuste, retry automatici | Media |
| **PostgreSQL** | Sostituire SQLite per scalabilita | Media |
| **S3-compatible storage** | Per mirror su cloud | Bassa |

### Monitoring & Observability

Riferimenti:
- [Flask Monitoring with Prometheus and Grafana](https://grafana.com/docs/grafana-cloud/monitor-applications/asserts/enable-prom-metrics-collection/application-frameworks/flask/)
- [Python Flask API Monitoring with OpenTelemetry](https://www.fosstechnix.com/python-flask-api-monitoring-with-opentelemetry-prometheus-and-grafana/)

| Componente | Descrizione |
|------------|-------------|
| **Prometheus metrics** | Endpoint `/metrics` con metriche custom |
| **Grafana dashboard** | Visualizzazione crawl, errori, storage |
| **Health checks** | Endpoint `/health` dettagliato |
| **Structured logging** | JSON logs per analisi con Loki |
| **Alerting** | Alert su errori, spazio disco, crawl falliti |

### Crawling Avanzato

Riferimenti:
- [ArchiveBox](https://archivebox.io/) - Self-hosted web archiving
- [Anti-Bot Bypass Best Practices](https://help.apify.com/en/articles/1961361-several-tips-on-how-to-bypass-website-anti-scraping-protections)

| Feature | Descrizione |
|---------|-------------|
| **Rotating User-Agent** | Pool di UA realistici |
| **Proxy support** | Rotazione IP per siti protetti |
| **JavaScript rendering** | Playwright per SPA (gia parziale) |
| **Robots.txt respect** | Opzione per rispettare/ignorare |
| **Rate limiting adattivo** | Rallentare se il sito risponde lento |
| **Retry intelligente** | Backoff esponenziale |

---

## Confronto con Tool Esistenti

### ArchiveBox
**Pro:**
- Multi-formato (HTML, PDF, WARC, screenshot, media)
- CLI + Web UI + API
- Community attiva

**Contro:**
- Setup piu complesso
- Richiede piu risorse

**Cosa prendere:**
- Esportazione WARC
- Screenshot automatici
- Estrazione articoli (readability)

Riferimento: [ArchiveBox GitHub](https://github.com/ArchiveBox/ArchiveBox)

### HTTrack
**Pro:**
- Semplice e affidabile
- Basso consumo risorse

**Contro:**
- Solo HTML statico
- No JavaScript rendering

**Cosa prendere:**
- Logica di mirroring ricorsivo (gia presente con wget)

Riferimento: [HTTrack vs ArchiveBox](https://www.saashub.com/compare-archivebox-vs-httrack)

### Browsertrix
**Pro:**
- Crawling JavaScript avanzato
- Formato WARC nativo

**Contro:**
- Piu complesso
- Richiede Kubernetes per scalare

**Cosa prendere:**
- Logica di crawling per SPA

Riferimento: [Awesome Web Archiving](https://github.com/iipc/awesome-web-archiving)

---

## Roadmap Suggerita

### Fase 1: Stabilita (1-2 settimane)
- [ ] Backup automatico database
- [ ] Storage dashboard con alert
- [ ] Screenshot automatici con Playwright
- [ ] Health check endpoint migliorato

### Fase 2: Ricerca (2-3 settimane)
- [ ] Indicizzazione full-text
- [ ] Ricerca nei contenuti
- [ ] Sistema di tag

### Fase 3: Standard (3-4 settimane)
- [ ] Export WARC
- [ ] API REST v1
- [ ] RSS feed

### Fase 4: Scalabilita (ongoing)
- [ ] Migrazione a PostgreSQL
- [ ] Redis per caching/rate limiting
- [ ] Prometheus + Grafana

---

## Risorse e Riferimenti

### Best Practices
- [Digital Preservation - CUNY](https://guides.cuny.edu/digital-toolkit/preservation)
- [6 Best Practices for Digital Archiving 2024](https://web.tapereal.com/blog/6-best-practices-for-digital-content-archiving-2024/)
- [WARC Implementation Guidelines](https://iipc.github.io/warc-specifications/guidelines/warc-implementation-guidelines/)

### Tool e Librerie
- [ArchiveBox](https://archivebox.io/)
- [Awesome Web Archiving](https://github.com/iipc/awesome-web-archiving)
- [Playwright Python](https://playwright.dev/python/)
- [Flask Prometheus Exporter](https://github.com/rycus86/prometheus_flask_exporter)

### Standard
- [WARC ISO 28500](https://www.loc.gov/preservation/digital/formats/fdd/fdd000236.shtml)
- [robots.txt Standard](https://www.robotstxt.org/)

---

*Documento generato il 29/12/2024 - Speculum v1.0*
