# Imagery brief

Per the visual design brief, the site uses real photography for warmth.
The current build ships SVG/CSS placeholders that work fine standalone;
when you have time, drop the photos below into `assets/img/` and the CSS
will pick them up.

All listed Unsplash searches are free for commercial use under the
Unsplash license. Pick whichever crop fits — these are search-term
starting points, not a curated set.

## 1. Hero — vintage card catalog (currently SVG placeholder)

- **Search:** `card catalog library` / `index drawer wood`
- **File:** `assets/img/hero-catalog.jpg`
- **Aspect:** ~3:4 portrait, ~720×960 minimum
- **Treatment:** lift shadows toward `#3F2E1F`, desaturate ~15%, subtle warm grain
- **Replace:** swap the `<svg>` inside `.hero-art` for `<img src="assets/img/hero-catalog.jpg" alt="A vintage library card catalog">`

## 2. Pull-quote backdrop — handwritten Moleskine

- **Search:** `handwritten journal notes` / `fountain pen notebook`
- **File:** `assets/img/notebook.jpg`
- **Use:** background of the `.pullquote` section at 8% opacity, or as a section break image between hero and demo
- **Aspect:** wide 16:6, ~1600×600

## 3. "Honest about security" section — brass key on leather ledger

- **Search:** `brass key ledger leather` / `key book antique`
- **File:** `assets/img/key-ledger.jpg`
- **Use:** thumbnail to the left of the security copy on wide screens

## 4. "How it connects" section — manila folder filing

- **Search:** `manila folder filing cabinet hand` / `archive office vintage`
- **File:** `assets/img/folder.jpg`
- **Use:** background of the `.integrate` section at low opacity, or section divider

## 5. Footer band — tidy study desk

- **Search:** `writing desk lamp warm` / `study desk books`
- **File:** `assets/img/desk.jpg`
- **Use:** full-width band above the footer, ~1800×500
- **Treatment:** desaturate + warm-shift, the photograph should feel
  intentionally muted

## Treatment recipe (for the colour-grading consistency)

Open in any image editor, apply:

1. Lift shadows toward `#3F2E1F` (warm brown) by ~20%
2. Desaturate the whole image by 15%
3. Add a Curves point: input 240 → output 232 (slight highlight rolloff)
4. Add 4% film grain overlay (warm tone, fine grain)
5. Export at 80% JPEG quality, ~200KB target

The site reads fine without the photos — they're polish. Ship without
if it's blocking you, add later.
