# Nova Autopilot: Pluggable Licensed Media Provider Architecture

This document specifies the multi-source pluggable licensed media architecture for `nova-autopilot` v8.0+.
It enables parallel discovery across 16 free and public-domain licensed sources, automated copyleft/non-commercial filtering, deduplication via perceptual difference hashing, and an offline local media library.

---

## 1. Provider Matrix

| Provider Name | Provider ID | Media Types | Authentication | Rate Limit | Cache TTL | Domain Priority | License Model | Terms / Signup URL |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Pixabay** | `pixabay` | Video, Image | `PIXABAY_API_KEY` | 90 req/min | 24 hours | Tech, Business, Space, Nature | Pixabay Content License (Free Commercial) | [pixabay.com/api/docs](https://pixabay.com/api/docs/) |
| **Pexels** | `pexels` | Video, Image | `PEXELS_API_KEY` (Opt) | 50 req/min | 24 hours | Tech, Business, Nature | Pexels License (Free Commercial) | [pexels.com/api](https://www.pexels.com/api/) |
| **NASA Library** | `nasa_library` | Video, Image | **Keyless** | 60 req/min | 48 hours | Space, Science | US Government Work (Public Domain) | [images-api.nasa.gov](https://images-api.nasa.gov) |
| **Wikimedia Commons** | `wikimedia_commons`| Image, Video | **Keyless** | 60 req/min | 48 hours | Science, History, Space, Nature | Filtered CC0, PDM, CC-BY (SA/NC rejected) | [commons.wikimedia.org](https://commons.wikimedia.org) |
| **Openverse** | `openverse` | Image | **Keyless** | 60 req/min | 48 hours | Tech, Nature, Business | Commercial CC0, PDM, CC-BY | [api.openverse.org](https://api.openverse.org) |
| **Internet Archive** | `internet_archive` | Video, Image | **Keyless** | 40 req/min | 72 hours | History, Culture | Prelinger / Public Domain | [archive.org/advancedsearch.php](https://archive.org) |
| **The Met Museum** | `met_museum` | Image | **Keyless** | 50 req/min | 72 hours | History, Art | CC0 1.0 Universal Open Access | [metmuseum.github.io](https://metmuseum.github.io) |
| **Cleveland Museum** | `cleveland_museum` | Image | **Keyless** | 60 req/min | 72 hours | History, Art | CC0 1.0 Universal Open Access | [clevelandart.org/open-access](https://www.clevelandart.org/open-access) |
| **Art Institute Chicago** | `artic` | Image | **Keyless** | 60 req/min | 72 hours | History, Art | CC0 Public Domain (Cloudflare Protected) | [api.artic.edu](https://api.artic.edu) |
| **Smithsonian** | `smithsonian` | Image | `SMITHSONIAN_API_KEY` | 50 req/min | 72 hours | History, Science, Space | CC0 1.0 Universal Open Access | [api.data.gov/signup](https://api.data.gov/signup/) |
| **Europeana** | `europeana` | Image | `EUROPEANA_API_KEY` | 50 req/min | 72 hours | History, Art | Open Reusability (CC0, PDM, CC-BY) | [pro.europeana.eu/page/get-api](https://pro.europeana.eu/page/get-api) |
| **Freesound** | `freesound` | Audio | `FREESOUND_API_KEY` | 60 req/min | 72 hours | Audio SFX | Creative Commons 0 (CC0) | [freesound.org/help/developers](https://freesound.org/help/developers/) |
| **Unsplash** | `unsplash` | Image | `UNSPLASH_ACCESS_KEY` | 50 req/min | 24 hours | Nature, Business | Unsplash Commercial License | [unsplash.com/developers](https://unsplash.com/developers) |
| **Procedural Motion** | `procedural_motion` | Video (Rendered) | **Keyless** (Local) | Unlimited | 168 hours | All Domains (Fallback) | Procedural CC0 / Public Domain | Procedural Animation Engine (`nova/animation/templates.py`) |
| **SEC EDGAR** | `sec_gov` | Image, Document | **Keyless** (User-Agent) | 60 req/min | 72 hours | Business, Tech, Finance | US Government Work (17 U.S.C. § 105) | [sec.gov/edgar/searchedgar/companysearch](https://www.sec.gov) |
| **Library of Congress** | `loc` | Image | **Keyless** | 30 req/min | 72 hours | History, Culture, Government | Public Domain / CC0 (Cloudflare challenge noted) | [loc.gov/apis](https://www.loc.gov/apis/) |
| **Procedural Maps** | `generated_maps` | Image | **Keyless** (Local) | 300 req/min | 168 hours | Tech, Business | 100% Synthetic CC0 Public Domain | Local Vector Synthesis |
| **Coverr** | `coverr` | Video | `COVERR_API_KEY` | 30 req/min | 24 hours | - | **DISABLED**: Free API restricts commercial broadcast | [coverr.co](https://coverr.co) |
| **Jamendo** | `jamendo` | Audio | `JAMENDO_CLIENT_ID` | 30 req/min | 24 hours | - | **DISABLED**: Free API non-commercial only; Content ID claims | [developer.jamendo.com](https://developer.jamendo.com) |

---

## 2. Domain & Niche Routing Priorities

Routing directs search queries to domain-specialized providers first, falling back to general providers:

```yaml
domain_routing:
  space:
    - nasa_library
    - pixabay
    - pexels
    - wikimedia_commons
    - openverse
  science:
    - nasa_library
    - wikimedia_commons
    - pixabay
    - smithsonian
    - openverse
    - pexels
  tech:
    - pixabay
    - pexels
    - openverse
    - wikimedia_commons
    - generated_maps
  business:
    - pixabay
    - pexels
    - openverse
    - generated_maps
    - wikimedia_commons
  history:
    - met_museum
    - artic
    - cleveland_museum
    - wikimedia_commons
    - internet_archive
    - smithsonian
  art:
    - met_museum
    - artic
    - cleveland_museum
    - europeana
    - smithsonian
  nature:
    - pixabay
    - pexels
    - openverse
    - wikimedia_commons
    - smithsonian
```

---

## 3. Strict License Compliance Engine (`nova/licensing/`)

Nova Autopilot enforces automated copyright clearance. A video with even one incompatible asset is strictly rejected at the Quality Gate.

### Approved Commercial Licenses
- **Creative Commons Zero (CC0 1.0 Universal)**: Complete waiver of copyright. Commercial and modification allowed without attribution.
- **Public Domain Mark (PDM / US Government Work)**: NASA and US federal works. Free for commercial educational documentaries with polite courtesy line.
- **Pixabay Content License**: Free for commercial and non-commercial use across print and digital without attribution.
- **Pexels License**: Free for commercial and non-commercial use; modifications permitted.
- **Creative Commons Attribution (CC-BY 2.0 / 3.0 / 4.0)**: Permitted with compiled creator credits in `credits.json` and video description.

### Prohibited Licenses (Strict Rejection)
- **CC BY-SA (ShareAlike / Copyleft)**: **STRICTLY REJECTED**. The ShareAlike clause forces derivative videos to inherit the copyleft license, conflicting with YouTube Standard Licensing and channel monetization.
- **CC BY-NC / NC-SA / NC-ND (NonCommercial)**: **STRICTLY REJECTED**. Monetized, ad-supported, or sponsored channels violate the NonCommercial covenant.
- **CC BY-ND (NoDerivatives)**: **STRICTLY REJECTED**. Video editing, resizing, subtitles, motion zoom, and cropping constitute derivative works.
- **All Rights Reserved / Editorial Only**: **STRICTLY REJECTED**. Lacks automated programmatic commercial clearance.

---

## 4. Architectural Decision Records (ADRs)

### ADR-01: Rejection of Web Scraping for Mixkit, Videvo, Videezy, Life of Vids
- **Context**: Sites like Mixkit and Videezy offer free clips on the web but lack documented public developer APIs.
- **Decision**: **REJECT**. Web scraping violates terms of service, breaks unpredictably upon DOM changes, and risks IP blocks and legal liability. Nova Autopilot only integrates with official, documented REST APIs.

### ADR-02: Rejection of General Image Search (Google, Bing, Pinterest)
- **Context**: General image engines return millions of images for any query.
- **Decision**: **REJECT**. General web search engines index copyrighted material without licensing provenance. Automated ingestion risks DMCA takedowns and copyright strikes.

### ADR-03: Default Disabling of Coverr API
- **Context**: Coverr provides high quality stock video footage.
- **Decision**: **DISABLED BY DEFAULT**. Coverr's Free API Developer Terms explicitly forbid commercial monetization on video platforms without a paid enterprise tier and mandate embedding a visible clickable logo overlay, which damages short video retention and aesthetics.

### ADR-04: Default Disabling of Jamendo API
- **Context**: Jamendo provides an extensive library of independent music tracks.
- **Decision**: **DISABLED BY DEFAULT**. Jamendo's Free Developer API restricts usage strictly to non-commercial projects. Furthermore, free catalog tracks trigger automated YouTube Content ID claims, muting or demonetizing videos.

### ADR-05: Adoption of Open Access Museum APIs (Met, Cleveland, Chicago)
- **Context**: Historic and scientific visuals are difficult to source on commercial stock sites without heavy fees.
- **Decision**: **APPROVED**. The Metropolitan Museum of Art, Cleveland Museum of Art, and Art Institute of Chicago maintain world-class Open Access collections licensed under CC0. When combined with the v8 motion engine (Ken Burns zoom/pan and parallax), these provide rich visual coverage for history, science, tech origins, and culture.

### ADR-06: SEC EDGAR Integration for Business & Finance
- **Context**: Business, corporate finance, and sensitive news stories frequently lack relevant stock video footage, leading to misleading or generic photos.
- **Decision**: **APPROVED**. The SEC EDGAR system provides public domain regulatory disclosures, company registrations, and financial filings under 17 U.S.C. § 105. When tickers or corporate entities are referenced, official filings are retrieved with a custom declared User-Agent.

### ADR-07: Library of Congress Handling (Cloudflare Bot Challenge)
- **Context**: The Library of Congress search API provides rich historical media but protects search endpoints with Cloudflare Bot Challenge (HTTP 403) from automated scripts.
- **Decision**: **HANDLED GRACEFULLY**. The LOC provider tests connection and fails gracefully without crashing the pipeline, while caching public catalog metadata where reachable. For automated rendering, museum open access collections and Wikimedia Commons serve as primary historical sources.

---

## 5. Local Media Library Operations (`nova/library/`)

The local media library caches verified, licensed footage to enable offline rendering and eliminate API rate limit bottlenecks.

### CLI Commands
```bash
# List indexed library assets
python -m nova library list --limit 20

# Prefetch licensed assets for high-demand niche themes
python -m nova library prefetch --niche ai_tech --limit 2
python -m nova library prefetch --niche space --limit 2

# Inspect disk storage usage
python -m nova library stats

# Run LRU cleanup (strictly protects assets in queued/published videos)
python -m nova library clean --max-gb 20.0
```

### Storage Cap & LRU Eviction Rules
1. Default cap is 20.0 GB.
2. Before eviction, the database scans all videos with status `queued`, `scheduled`, or `published`.
3. Assets referenced in active videos are marked `is_protected = 1` and are **immune** from eviction.
4. Unprotected assets are evicted in order of `last_used_at ASC, usage_count ASC` until disk usage drops below 85% of threshold.
