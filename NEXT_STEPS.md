# Speculum - Next Steps & Roadmap

Documento di pianificazione per lo sviluppo futuro di Speculum, basato su ricerche sulle best practice di web archiving e analisi di tool simili.

---

## Visione: Progetto Celeste

### Il Problema

L'infosfera in lingua italiana trabocca di reperti culturali inestimabili: zine, video d'epoca, controcultura, archivi personali e molto altro. **Dove sono? Chi li salva? E soprattutto, cosa c'e dentro?**

Esempi concreti di patrimonio a rischio:
- Le migliori esibizioni live di **Lou X** (storico rapper abruzzese) su Telenorba e Videomusic, ora solo su YouTube
- I numeri di **Decoder**, storica rivista cyberpunk italiana, conservati su Archive.org dall'[Archivio Grafton 9](https://grafton9.net/)
- I materiali politici dell'**Archivio Primo Moroni**, collezionati dal collettivo [Autistici](https://www.inventati.org/apm/index.php)

Ogni giorno questi materiali rischiano di scomparire per sempre: politiche di moderazione arbitrarie, chiusura di account, bit rot su hard disk vecchi.

### La Visione

**Celeste** e un protocollo open-source per la digitalizzazione e la divulgazione di patrimoni culturali sommersi.

**Obiettivo**: creare una piattaforma a meta tra [The Public Domain Review](https://publicdomainreview.org/) e [Monoskop](https://monoskop.org/Monoskop), per scovare, raccogliere, conservare e raccontare il meglio della controcultura italiana.

### Caso d'Uso: Libreria Potlatch (Milano)

La libreria [Potlatch](https://www.instagram.com/potlatch.milano/) dispone di un ampio magazzino di libri non catalogati che contiene edizioni rare, pubblicazioni indipendenti in copia unica e opere di altissimo valore culturale.

**Obiettivi del progetto pilota**:
1. Catalogare il magazzino e digitalizzare il catalogo
2. Sviluppare un indice tematico e percorsi narrativi ("I 10 libri di Potlatch che parlano di...")
3. Selezionare libri rari e digitalizzarli (scan), liberandoli in pubblico dominio
4. Prototipare un protocollo replicabile per altre librerie indipendenti

### Come Speculum si Integra

Speculum puo evolvere per diventare l'infrastruttura tecnica di Celeste:

| Funzionalita Celeste | Implementazione Speculum |
|---------------------|--------------------------|
| Archiviazione video YouTube | Gia presente, da potenziare |
| Catalogazione con metadati culturali | Estendere modello dati |
| Percorsi tematici narrativi | Sistema Collections + export Ghost |
| Distribuzione P2P | Generazione torrent automatica |
| Ridondanza archivio | Upload automatico su Archive.org |
| Digitalizzazione documenti | Supporto PDF/scan con OCR |
| Rete di librerie | Federazione tra istanze |

### Risorse Celeste

- [Documento progetto Potlatch](https://docs.google.com/document/d/1JKwmUpXGxKLdjA8FhSaI9AKs1CxtsVEN_U8iHfId-qA/edit)
- [Call pubblica canali YouTube](https://www.instagram.com/p/DIvjHNHsMvJ/)
- [Bando Cariplo "Valore della Cultura"](https://www.fondazionecariplo.it/static/upload/tes/testo_bando-valore-della-cultura-2025.pdf)
- [Ghost CMS](https://ghost.org/) - per percorsi tematici
- [Koha](https://koha-community.org/) - sistema gestione biblioteche
- [BookStack](https://www.bookstackapp.com/) - alternativa piu semplice a Ghost

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

### Celeste-Specifiche
13. **Priorita immediata**: Partire dal potenziamento YouTube (per la call Instagram) o dalla catalogazione Potlatch?
14. **Torrent**: Usi gia Transmission o altro client? Integrare direttamente il seeding?
15. **Ghost vs integrato**: Percorsi tematici dentro Speculum o esportati verso Ghost esterno?
16. **Federazione**: Altre librerie/archivi sono gia interessati? Serve subito il multi-istanza?
17. **Metadati culturali**: Quali campi sono essenziali? (periodo storico, movimento, formato originale, provenienza, licenza, rischio scomparsa)
18. **Trascrizione video**: Serve ricerca nel parlato dei video YouTube? (Whisper integration)
19. **OCR documenti**: Prevedi di archiviare scan di zine/libri? Serve full-text search nei PDF?
20. **Archive.org**: Upload automatico per ridondanza o gestione manuale?

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

### Fase 1: Stabilita
- [x] Backup automatico database (`app/backup.py`)
- [ ] Storage dashboard con alert
- [ ] Health check endpoint migliorato

### Fase 2: Ricerca
- [x] Indicizzazione full-text (`app/search.py` - SQLite FTS5)
- [x] Ricerca nei contenuti
- [ ] Sistema di tag

### Fase 3: Standard
- [x] Export Ghost CMS (`app/export.py`)
- [x] Wayback Machine integration (`app/wayback.py`)
- [ ] Export WARC (formato ISO)
- [ ] API REST v1 documentata
- [ ] RSS feed

### Fase 4: Scalabilita (ongoing)
- [ ] Migrazione a PostgreSQL
- [ ] Redis per caching/rate limiting
- [ ] Prometheus + Grafana

---

## Roadmap Celeste (Integrazione Controcultura Italiana)

### Fase C1: YouTube Potenziato
*Per rispondere alla call pubblica sui canali YouTube*
- [ ] Import batch di interi canali YouTube
- [ ] Preservazione playlist originali con ordine
- [ ] Monitoring automatico nuovi video
- [ ] Metadati estesi (data upload, descrizione originale, commenti)
- [ ] Trascrizione automatica con Whisper (ricerca nel parlato)

### Fase C2: Metadati Culturali
*Per la catalogazione stile Potlatch*
- [ ] Campi Dublin Core (standard bibliotecario)
- [ ] Periodo storico ("anni 80", "pre-internet")
- [ ] Movimento culturale ("cyberpunk", "autonomia", "punk")
- [ ] Formato originale ("VHS", "zine cartacea", "BBS")
- [ ] Provenienza ("Archivio Primo Moroni", "collezione privata")
- [ ] Stato licenza ("pubblico dominio", "fair use", "da verificare")
- [ ] Livello rischio scomparsa (alto/medio/basso)

### Fase C3: Collezioni e Narrativa
*Per i percorsi tematici di Potlatch*
- [ ] Sistema Collections con curatore e descrizione
- [ ] Narrativa in markdown per ogni collezione
- [ ] Export compatibile Ghost/BookStack
- [ ] Pagine pubbliche per collezioni
- [ ] Embedding in siti esterni

### Fase C4: Distribuzione P2P
*Per la diffusione via torrent*
- [ ] Generazione automatica .torrent per ogni mirror
- [ ] Integrazione Transmission per seeding automatico
- [ ] Magnet link nelle pagine sito
- [ ] Statistiche download/seed
- [ ] Tracker privato opzionale

### Fase C5: Ridondanza Archive.org
*Per la preservazione a lungo termine*
- [ ] Upload automatico WARC su archive.org
- [ ] Salvataggio link permanenti nel DB
- [ ] Verifica periodica disponibilita
- [ ] Fallback automatico se mirror locale non disponibile

### Fase C6: Documenti e Scan
*Per zine, libri, materiale cartaceo digitalizzato*
- [ ] Supporto PDF con viewer integrato
- [ ] OCR automatico con Tesseract
- [ ] Full-text search nei documenti
- [ ] Supporto DJVU, CBZ/CBR (fumetti/zine)
- [ ] Estrazione copertina come thumbnail

### Fase C7: Federazione
*Per la rete di librerie e archivi*
- [ ] API pubblica documentata
- [ ] Sincronizzazione cataloghi tra istanze
- [ ] Catalogo unificato federato
- [ ] Identita visiva personalizzabile per istanza
- [ ] Sistema di crediti ai contributori

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
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) - Download YouTube
- [Whisper](https://github.com/openai/whisper) - Trascrizione audio
- [Tesseract OCR](https://github.com/tesseract-ocr/tesseract) - OCR documenti

### Standard
- [WARC ISO 28500](https://www.loc.gov/preservation/digital/formats/fdd/fdd000236.shtml)
- [Dublin Core Metadata](https://www.dublincore.org/specifications/dublin-core/)
- [robots.txt Standard](https://www.robotstxt.org/)

### Controcultura Italiana (Archivi Esistenti)
- [Archivio Grafton 9](https://grafton9.net/) - Decoder e cyberpunk italiano
- [Archivio Primo Moroni](https://www.inventati.org/apm/) - Materiali politici, collettivo Autistici
- [Archive.org - Italian Underground](https://archive.org/search?query=italian+underground)
- [Monoskop](https://monoskop.org/) - Wiki arti e culture media

### Progetti Ispiratori
- [The Public Domain Review](https://publicdomainreview.org/) - Modello per narrativa culturale
- [Monoskop](https://monoskop.org/Monoskop) - Wiki collaborativa arti/media
- [UbuWeb](https://ubu.com/) - Archivio avanguardie

### Celeste - Documenti Progetto
- [Proposta Potlatch](https://docs.google.com/document/d/1JKwmUpXGxKLdjA8FhSaI9AKs1CxtsVEN_U8iHfId-qA/edit)
- [Call canali YouTube](https://www.instagram.com/p/DIvjHNHsMvJ/)
- [Bando Cariplo 2025](https://www.fondazionecariplo.it/static/upload/tes/testo_bando-valore-della-cultura-2025.pdf)
- [Libreria Potlatch](https://www.instagram.com/potlatch.milano/)
- [Intervista Potlatch](https://www.noizona2.it/libreria-potlatch/)

### Tool per Catalogazione
- [Ghost CMS](https://ghost.org/) - Publishing platform
- [Koha](https://koha-community.org/) - Sistema gestione biblioteche
- [Invenio](https://inveniosoftware.org/) - Framework repository digitali
- [BookStack](https://www.bookstackapp.com/) - Wiki/documentazione

---

## Architettura Celeste-Speculum

```
+-----------------------------------------------------------+
|                    SPECULUM / CELESTE                      |
+-----------------------------------------------------------+
|  +----------+  +----------+  +----------+  +----------+   |
|  |   Web    |  | YouTube  |  |   Docs   |  |   Zine   |   |
|  |  Mirror  |  | Archive  |  |   Scan   |  |   PDF    |   |
|  +----+-----+  +----+-----+  +----+-----+  +----+-----+   |
|       |             |             |             |          |
|       +-------------+-------------+-------------+          |
|                           |                                |
|              +------------v------------+                   |
|              |    Metadata Layer       |                   |
|              |  - Dublin Core          |                   |
|              |  - Periodo/Movimento    |                   |
|              |  - Provenienza          |                   |
|              |  - Tags/Collezioni      |                   |
|              +------------+------------+                   |
|                           |                                |
|       +-------------------+-------------------+            |
|       v                   v                   v            |
|  +----------+       +----------+       +----------+        |
|  | Storage  |       | Archive  |       | Torrent  |        |
|  | Locale   |       |   .org   |       |  Seed    |        |
|  +----------+       +----------+       +----------+        |
|                                                            |
|  +------------------------------------------------------+  |
|  |              Frontend Pubblico                       |  |
|  |  - Catalogo navigabile                              |  |
|  |  - Percorsi tematici (Ghost-style)                  |  |
|  |  - Ricerca full-text (web + video + documenti)      |  |
|  |  - Download torrent / magnet link                   |  |
|  |  - Collezioni curate con narrativa                  |  |
|  +------------------------------------------------------+  |
|                                                            |
|  +------------------------------------------------------+  |
|  |              Federazione                             |  |
|  |  - API REST pubblica                                |  |
|  |  - Sync tra istanze (Potlatch <-> Grafton9 <-> ...) |  |
|  |  - Catalogo unificato                               |  |
|  +------------------------------------------------------+  |
+-----------------------------------------------------------+
```

---

*Documento generato il 29/12/2024 - Speculum v1.0 + Celeste*
