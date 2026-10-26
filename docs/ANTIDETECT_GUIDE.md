# 🛡️ Anti-Detect Guide — How the Shield Works, What It Covers, and Where It Ends

> **Read this before you run a farm.** This page documents the anti-detect layer as it
> actually is — what it defends against, what it cannot defend against, and what is left
> to you as the operator. It reflects the state after the v1.15.x anti-detect audit
> (findings A-01…A-29 plus the round-12/13 proxy-shape and error-stack hunts), and every
> claim marked *measured* below was verified against a real Chrome launched through the
> product's own start path, with a plain Chrome as the control in the same run.

---

## 📑 Contents

1. [The two layers of anti-detect](#1-the-two-layers-of-anti-detect)
2. [What the shield spoofs (surface map)](#2-what-the-shield-spoofs-surface-map)
3. [How the hooks stay invisible (the Proxy architecture)](#3-how-the-hooks-stay-invisible-the-proxy-architecture)
4. [What we verified against real detectors](#4-what-we-verified-against-real-detectors)
5. [Known limits — what can still expose you](#5-known-limits--what-can-still-expose-you)
6. [Operational checklist (your half of the job)](#6-operational-checklist-your-half-of-the-job)
7. [Applicability matrix — where this tool fits](#7-applicability-matrix--where-this-tool-fits)
8. [Frequently asked questions](#8-frequently-asked-questions)

---

## 1. The two layers of anti-detect

Anti-detection is two different problems, and conflating them is the most common way
farms burn:

| Layer | What it is | Who owns it here |
|---|---|---|
| **Values** | The numbers a site reads: GPU string, canvas hash, timezone, cores, fonts… | The shield — fully automated per profile |
| **Behaviour & environment** | IP reputation, TLS fingerprint, account history, human rhythm, proxy↔profile coherence | **You** — the tool helps, but cannot decide |

The shield is very good at the first layer. No JS-level tool can own the second: a
perfect fingerprint on a datacenter IP is still a datacenter IP. Section 6 lists exactly
what you must configure for the two layers to agree.

---

## 2. What the shield spoofs (surface map)

Every profile carries an independently generated, internally consistent hardware
identity. Below is what is spoofed and the class of detector it answers.

### Identity & platform

| Surface | Spoofed as | Notes |
|---|---|---|
| `navigator.userAgent` + Client Hints | Real running Chrome version, profile OS | The UA, `brands`, `uaFullVersion` and the `Sec-CH-UA` **HTTP headers** all agree (measured) |
| `userAgentData.platform` | OS name (`Windows`/`macOS`/`Linux`) | Not the legacy `Win32` — a UA-CH spec value |
| `navigator.webdriver` | `false` | Via a Proxy over the **native** getter, so `getOwnPropertyNames` and `toString` stay clean |
| `hardwareConcurrency`, `deviceMemory` | Profile values, coherent with the GPU class | Also covered in **Worker scopes** (a classic bypass) |
| Languages / locale | Profile list, `language === languages[0]` | |
| Timezone | Profile zone, DST-aware, via CDP `Emulation.setTimezoneOverride` | Browser-level: `getTimezoneOffset`, `Intl` and `Date.prototype.toString` all agree, in the main world *and* workers |

### Graphics & compute

| Surface | Spoofed as | Notes |
|---|---|---|
| WebGL vendor/renderer | Profile GPU (via the `WEBGL_debug_renderer_info` semantics: `null` until the extension is requested — like the real browser) | WebGL **and** WebGL2 (different prototypes — both hooked) |
| ~25 WebGL limits | Coherent desktop-GPU values, correct **types** (e.g. aliased ranges are `Float32Array` pairs) | |
| WebGPU `adapter.info` | Profile vendor/architecture, native `GPUAdapterInfo` shape | |
| Canvas 2D & OffscreenCanvas | Deterministic noise derived from **content + profile seed** | Same content ⇒ same hash on every read (a real browser's property); different profiles hash differently. Main and OffscreenCanvas produce the **same** image |
| WebAudio / OfflineAudioContext | Per-call phase noise; `sampleRate`/`baseLatency` pinned | |

### Devices, fonts, media

| Surface | Spoofed as | Notes |
|---|---|---|
| `enumerateDevices()` | Profile mic/cam/speaker labels on real `InputDeviceInfo` shapes | Instances carry **no own properties** (measured) |
| `getBattery()` | Profile state on a real `BatteryManager` prototype | |
| `queryLocalFonts()` | Per-profile font pool (24–42 realistic families) | Missing families are backed by a real sibling font through `@font-face src: local(...)`, so the rendering agrees with the claim |
| `speechSynthesis.getVoices()` | Platform voice pool (8–12 on Windows) | Real `SpeechSynthesisVoice` shape, no own properties |
| `navigator.plugins` / `mimeTypes` | Exact desktop-Chrome shape (5 PDF entries, 2 mimes) | Real `PluginArray`/`MimeTypeArray` prototypes |

### Geometry, time, network

| Surface | Spoofed as | Notes |
|---|---|---|
| Screen metrics & window geometry | Profile screen; the window always fits inside it, DPR coherent | The host's `devicePixelRatio` is overridden **on the window instance** (the prototype override never applies — measured) |
| `getBoundingClientRect`, `measureText` | Sub-pixel jitter, **stable per element / per string** | Same element ⇒ same rect on every read (a real renderer's property) |
| `performance.now()` | Per-profile sub-100µs jitter, monotonic | |
| WebRTC candidates | Private IPv4 / IPv6 mDNS stripped — offer, answer, trickle, constructor | No local-IP leak (measured: only `.local` names remain) |
| Loopback fetch | Blocked except the local API port | The profile's own CDP endpoint is unreachable from the page |

---

## 3. How the hooks stay invisible (the Proxy architecture)

The hardest part of anti-detect is not lying — it is lying *without leaving a mark*.
Detectors like CreepJS do not read your values first; they interrogate the **functions
themselves** (~20 structural checks per API: `'prototype' in fn`, own keys, illegal
invocation, error-stack shapes…).

Since v1.15.x every hook is a **Proxy over the native function**, never a replacement:

- the native getter runs *first*, so receiver-less access still throws the native
  `Illegal invocation` TypeError with its native stack;
- the function's shape (own keys, extendability, `toString()`) stays that of the real
  native — a proxied API answers `toString()` with the **exact original signature**;
- our own frames are spliced out of error stacks, and `Error.stackTraceLimit` is raised
  inside traps so the native tail of the stack survives;
- nothing is left on the instances: `getOwnPropertyNames(navigator)` is empty, the
  window carries no `__`-prefixed properties of ours (measured: property count identical
  to a plain Chrome).

The verification method is part of the product: a faithful port of the CreepJS lie
detector (`src/lies/index.ts`, ~20 checks × the same API targets) is replayed against a
real launched profile in every audit round — see Section 4.

---

## 4. What we verified against real detectors

Not marketing: these were actually executed against a profile launched through the
product's own start path.

| Detector / test | Result |
|---|---|
| **CreepJS lie detector** (port of `src/lies/index.ts`; 36 APIs scanned) | **0 corrupted APIs** (a plain Chrome control: 0. Before the Proxy rework: 33) |
| **CreepJS `proxy.js`** error-trace shapes (7 adversarial paths around `toString`/`setPrototypeOf`) | **6 of 7 byte-identical** to the host: type, frame count, every frame. The 7th is a V8 engine limitation shared by every JS-level tool (see Section 5) |
| **FingerprintJS BotD** (all 16 open-source detectors: distinctive properties, languages, plugins, mimeTypes, WebGL vendor, window size, RTT, notification permission, productSub…) | **All clean** — no detector fires |
| **Worker / ServiceWorker scope** | Profile values, no host leak (the classic "read it in a Worker" bypass) |
| **Cross-origin iframe (OOPIF)** | Profile values |
| Value coherence (UA ↔ brands ↔ HTTP headers; timezone offset ↔ Intl ↔ Date string; canvas ↔ DOM metrics) | Verified in the same runs |

What we **disproved along the way** (and therefore did not "fix"): `document.fonts.check()`
answers `true` for any family name in Chrome (it cannot serve as a detector); the external
`fetch` failures seen in sandboxes are CORS, not the shield; the `webdriver === true`
reading in automation harnesses comes from the harness itself.

---

## 5. Known limits — what can still expose you

Honesty here is a feature: knowing the boundaries is what keeps a farm alive.

### JS-layer limits (ours)

1. **`new Proxy(fn, …)` eval frame name (1 of 7 proxy.js traces).** V8 names the stack
   frame of an eval'd call after the *object type* — `at Proxy.eval` for a proxied
   function vs `at toString.eval` for a native one. The engine picks this name below the
   JS level; every JS-based stealth tool (including puppeteer-extra-stealth) has the same
   exposure. Closing it would mean dropping the Proxy architecture entirely — trading 33
   detectable APIs for 1 trace.
2. **Canvas noise is per-profile by design.** Two profiles rendering identical content
   produce **different** hashes — that is the anti-fingerprint property. The flip side:
   a site that sees two different "machines" behind one IP may infer a farm from the IP
   itself. Pair profiles with distinct proxies (Section 6).
3. **Font aliases render their donor.** A claimed-but-missing family is backed by a real
   sibling font, so text *renders plausibly*, but its exact metrics match the donor, not
   the claimed family's own metrics table. A detector with per-family metric tables
   could notice; in practice this requires the family to be absent on the host *and* the
   detector to know its exact metrics.
4. **`@font-face` rules exist in the CSSOM.** The alias rules (present only when a
   claimed family is missing on the host) live in a `<style>` element. They are hidden
   from `document.fonts`, but a detector walking `document.styleSheets` → `cssRules`
   could see them. Known, accepted, bounded: it fires only for missing families.

### Environment limits (yours — the tool cannot fix these)

5. **TLS / HTTP fingerprint.** ClientHello, ALPN, HTTP/2 frame ordering — visible
   **before any JS runs**. The tool ships real branded Chrome, which is the sane default,
   but a JA3-blocking WAF sees your network stack regardless of the shield.
6. **IP ↔ profile coherence.** A `Europe/Berlin` profile on a Vietnamese datacenter IP is
   a one-line contradiction. Timezone, language and proxy geo **must** be configured
   together (the generator aligns them — see Section 6).
7. **IP reputation.** A clean fingerprint does not launder a burned IP.
8. **Behavioural biometrics.** Click rhythm, scroll cadence, typing bursts. The
   synchronizer humanizes replicated input, but no tool makes a scripted farm behave like
   a person across months. Tier-1 vendors weight this heavily.

### The brutal summary

> Against value-based fingerprinting (which is what most sites actually deploy), the
> shield is production-grade: per-profile uniqueness, native shapes, verified against
> the public state of the art.
> Against tier-1 multi-signal vendors (FingerprintJS Pro, DataDome, Cloudflare), no JS
> layer is sufficient alone — they combine TLS, IP, behaviour and server-side history.
> The shield removes the *fingerprint* signal; the remaining exposure is operational.

---

## 6. Operational checklist (your half of the job)

The tool automates the values; coherence with the environment is operator work. The
fingerprint generator aligns timezone/language/GPU-class internally — but it cannot know
your proxy's geography.

**Before launching a profile at a target site, make sure:**

- [ ] **Proxy geo matches the profile timezone & language.** The generator offers
  timezone presets; pick per proxy region, or set it explicitly in the profile.
- [ ] **One profile = one stable proxy** (or a consistent mobile rotation from the same
  ASN). Changing a profile's IP country mid-life rewrites its identity mid-story.
- [ ] **Use residential/mobile IPs for anything a tier-1 vendor protects.** Datacenter
  ranges are scored before your fingerprint is even read.
- [ ] **Warm up before working.** The history seeder (`POST /api/profiles/{id}/seed-history`)
  lays a 14-day organic past; the scenario builder then adds real browsing. A profile that
  signs up for a service the day it was born is a pattern with or without a fingerprint.
- [ ] **Don't script what a human wouldn't do.** The synchronizer's humanizer (jitter,
  20–80 ms micro-delays, Bezier motorics) helps, but a 200-account signup burst from one
  subnet is detectable at the network level regardless of JS.
- [ ] **Keep profiles' `platform` consistent with what you do.** A Windows profile never
  claiming macOS-only fonts is already handled; don't undermine it by claiming an
  impossible GPU/OS combination in custom edits.
- [ ] **Check `get_stealth_status` after launch.** The CDP injector reports `applied: true`;
  if it ever fails, the profile runs **unshielded** — the API surfaces this per profile.
- [ ] **Rotate the farm's noise seeds over time.** Every generated profile already has
  unique canvas/audio seeds; when cloning profiles by hand, do not copy a fingerprint
  verbatim between accounts on the same site.

---

## 7. Applicability matrix — where this tool fits

| Scenario | Fit | Why |
|---|---|---|
| Multi-account management where each account needs its own consistent device identity | ✅ **Excellent** | The core design target |
| Classifieds / e-commerce / social multi-accounting behind residential proxies | ✅ **Good** | Fingerprint isolation + history seeding + warmup cover the common checks |
| Testing your own site's fingerprinting / bot detection | ✅ **Excellent** | The audit tooling (CreepJS/BotD replays) doubles as a QA harness |
| Automating accounts behind a **datacenter** IP against tier-1 anti-fraud | ⚠️ **Weak** | IP reputation dominates; the shield cannot compensate |
| High-frequency scripted behaviour on one site from one subnet | ⚠️ **Weak** | Behavioural/network analysis fires regardless of JS |
| Anything requiring *perfect* TLS-stack mimicry of a specific browser build | ⚠️ **Partial** | Ships real Chrome (good default); no custom TLS stack |
| Beating a specific vendor you have not tested against | ❓ **Unknown by definition** | Verify first: the live test suite (`pytest -m live`) and the replays in this repo are the template — point them at your target |

**Not an invisibility cloak.** If your use case is "evade a state-level adversary" or
"make fraud undetectable", this tool — like every JS-level tool — is the wrong
instrument, and we say so plainly.

---

## 8. Frequently asked questions

**Q: Is the shield enough on its own?**
Against value-based fingerprinting — mostly yes (Section 4). Against multi-signal tier-1
detection — no, and nothing JS-level is. Combine with clean IPs and sane behaviour
(Section 6).

**Q: Why does my canvas hash differ from another profile with the same fingerprint?**
By design. The noise seed is part of the profile. Identical hardware strings with
identical canvas hashes across "different machines" is exactly what a farm looks like.

**Q: Can I verify the shield myself?**
Yes. Launch a profile, open `https://abrahamjuliot.github.io/creepjs/` in it, and compare
the "lies" counter against the same page in your normal browser. The repo also ships the
replay tooling as tests (`tests/live/`, `pytest -m live`) — that is the same method the
audit used.

**Q: A site still detected my automation. What first?**
In order of likelihood: (1) the IP — check its reputation; (2) behaviour — signup
velocity, rhythm; (3) account history — a brand-new profile doing sensitive actions; and
only then (4) the JS layer — which the checklist and the live tests let you rule in or
out quickly. In our measurements the JS layer is the *least* likely culprit once the
shield reports `applied: true`.

**Q: What happens if the CDP injection fails?**
The profile runs unshielded. The API exposes the injector status per profile
(`GET /api/profiles/…` → stealth fields); treat a launch without `applied: true` as
"do not use this session for anything sensitive". The branded-Chrome extension path
(older Chrome only) is a fallback, not a guarantee — modern branded Chrome ignores the
`--load-extension` flag, which is why CDP injection is the production path.

**Q: Do you guarantee a specific site won't detect me?**
No, and no honest vendor can. What we guarantee is narrower and testable: the shield's
own surfaces match a real browser (Sections 2–4), and when we find a place where they
don't, we measure it, fix it and pin it with a regression test — the 30+ findings in the
[CHANGELOG](../CHANGELOG.md) were all found exactly that way.

---

*This guide tracks the state of the shield as of the v1.15.x audit. When the shield
changes materially, this page changes with it — see the
[CHANGELOG](../CHANGELOG.md) for the finding-by-finding history (A-01…A-29, rounds 12–13).*
