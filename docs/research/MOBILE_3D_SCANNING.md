# Mobile 3D scanning — feasibility research & POC plan

Status: **research / pre-POC** · Date: 2026-10-21

The question: can a phone app use the hardware behind face unlock (and
anything else on the phone) to scan real objects, rooms and heads, recognise
what they are, and measure them accurately enough to be useful for AI and
education?

**Short answer: yes, but mostly on iPhone, and the accuracy depends on which
sensor and how far away the object is.** A head or a shoe can be scanned to
about 1 mm. A sofa or a room to about 1 cm. A screw thread or a ring size
needs better than any phone can do. The rest of this doc explains why and
proposes a POC that proves those numbers on real objects.

---

## 1. Reality check: does face unlock mean 3D scanning?

Only some face unlock systems are 3D.

| Phone family | Face unlock hardware | Usable as a 3D scanner? |
|---|---|---|
| **Every iPhone with Face ID** (iPhone X, 2017, onward) | **TrueDepth**: IR dot projector (structured light) + IR camera, front-facing | **Yes.** Apps can read it through AVFoundation depth data and ARKit face tracking |
| iPhone Pro / iPad Pro (12 Pro, 2020, onward) | Also a rear **LiDAR** (direct time-of-flight) | **Yes**, for objects and rooms at 0.3–5 m |
| Honor Magic 7 Pro, Huawei Mate Pro line (Mate 20 Pro → Mate 60 Pro) | Front 3D depth (ToF / structured light) | Hardware exists, but **no standard public API**. Vendor-specific, not worth building on |
| Google Pixel 4 (2019) | Soli radar + IR face unlock | Discontinued. Pixel 5 onward went back to 2D |
| Samsung Galaxy S10 5G / Note10+ / S20+ | ToF sensor | Removed after 2020 |
| **Most Android phones today** | **2D selfie camera only** (it compares a photo) | **No depth hardware.** Only ML/motion-estimated depth via ARCore |

**Real-life example:** a Samsung Galaxy S24 unlocks with your face the same
way a photo-tagging app recognises you. It looks at a flat picture. An iPhone
16 sprays roughly 30,000 invisible infrared dots on your face and measures how
the pattern bends. That is real 3D. That's why Samsung says its face unlock
isn't secure enough for banking apps, and Apple's is.

**Implication:** a cross-platform "scan anything at 1 mm" app isn't possible
today. On Android you get estimated depth (good for AR placement, poor for
measuring). **The POC should be iOS-first.** Android can follow later with a
reduced feature set.

---

## 2. The three sensors and what each is good for

| | **TrueDepth** (front) | **LiDAR** (rear, Pro models) | **RGB camera + photogrammetry / ML** (any phone) |
|---|---|---|---|
| How it works | Projected IR dot pattern, triangulated | Pulsed laser, measures time of flight | Many photos from different angles, matched features → 3D |
| Depth map | 640×480 @ up to 30 fps | 256×192 @ 60 fps (ARKit `sceneDepth`) | n/a (computed offline, seconds to minutes) |
| Sweet-spot range | ~20–50 cm (arm's length) | ~0.3–5 m | depends on object size |
| Best for | **Faces, heads, ears, hands, small objects** | **Rooms, furniture, large objects, quick measurements** | **Detailed textured models of objects** (Apple Object Capture) |
| Weak at | Anything beyond ~1 m; scanning *someone else* (the sensor faces the user) | Objects smaller than ~10 cm; thin edges | Shiny, transparent, featureless surfaces (white mug, glass) |
| Apple API | `AVCaptureDepthDataOutput`, ARKit `ARFaceTrackingConfiguration` (1,220-vertex face mesh) | ARKit `sceneReconstruction`, `RoomPlan`, raycasting | RealityKit `ObjectCaptureSession` + `PhotogrammetrySession` (iOS 17+, needs LiDAR device) |

**Real-life examples:**
- **TrueDepth:** eyewear brands such as Topology fit custom frames from a
  selfie scan. Hearing-aid and earbud makers have prototyped ear scans the
  same way. Bellus3D sold an iPhone face-scanning app for dentists until 2022.
- **LiDAR:** Apple's own *Measure* app, IKEA's room-planning tools, and
  real-estate apps (Polycam, Canvas) that produce floor plans with RoomPlan.
- **Photogrammetry:** museum and e-commerce product scans (Polycam,
  Scaniverse, Luma). You walk around a trainer, and two minutes later there's
  a textured 3D model.

---

## 3. How accurate is it? (published evidence)

| Use | Sensor | Reported accuracy | Source |
|---|---|---|---|
| Live human face vs. professional 3dMDface system | iPhone 11 Pro TrueDepth (Bellus3D) | **0.86 ± 0.31 mm** RMS; 97% of landmarks within 2 mm | Heliyon 2023 (29 participants) |
| Face vs. dental CBCT (X-ray 3D) | iPhone 13 Pro (EM3D app) | **0.39 ± 0.36 mm** mean | Dentistry Journal 2024 (30 patients) |
| Phone face scanners in general vs. professional | mixed | worse than pro scanners, but within **< 1.5 mm** (clinically acceptable) | JMIR 2020 meta-analysis |
| Outlier: face vs. CBCT | TrueDepth (Bellus3D Dental Pro) | deviations **> 3 mm** in places | Thurzo et al. |
| Small objects (> 10 cm side) | iPhone 12 Pro LiDAR | **± 1 cm** absolute | Scientific Reports 2021 (Luetzenburg et al.) |
| Large scene (130 m cliff) | iPhone 12 Pro LiDAR | ± 10 cm | same |
| Small/medium objects | iPhone 12/13/15 Pro LiDAR (Scaniverse) | **< 1% of object size**; large plain surfaces deviate locally | Geodetski vestnik 2025 |
| Small geometric objects | iPhone 12 Pro LiDAR | "low accuracy". Small objects are hard for LiDAR alone | Erciyes Univ. study |
| Any Android (ARCore depth-from-motion) | RGB + motion (+ ToF if present) | Google: most accurate at 0.5–5 m; poor on textureless surfaces; independent tests found little gain | Google ARCore docs; Research Square preprint |

### What that means in everyday terms

| Task | Accuracy needed | Feasible on a phone? |
|---|---|---|
| Will this sofa fit through my door? | ~2 cm | ✅ LiDAR, easily |
| Room floor plan for a carpet quote | ~1–5 cm | ✅ LiDAR + RoomPlan |
| Box dimensions for a shipping quote | ~0.5–1 cm | ✅ LiDAR (box > 10 cm) |
| Head circumference / hat or helmet size | ~3–5 mm | ✅ TrueDepth head scan |
| Glasses frame fit (pupil distance, nose bridge) | ~1 mm | ✅ TrueDepth, the best-documented case |
| Shoe/foot size | ~2–3 mm | ⚠️ Possible with photogrammetry + reference object |
| Ring size | ~0.2 mm | ❌ Below phone accuracy |
| Machined part / screw thread | ~0.05 mm | ❌ Needs a dedicated scanner or caliper |

**Rule of thumb:** expect about 1 mm for faces at arm's length with TrueDepth,
and about 1 cm (or 1% of size) for objects and rooms with LiDAR. Photogrammetry
gets to a few mm on a textured object, and you can improve absolute scale by
putting a known reference in the frame, such as a credit card
(85.60 × 53.98 mm, ISO/IEC 7810) or an A4 sheet.

---

## 4. "Recognise objects": the AI half

Depth gives you *shape and size*. Recognition gives you *what it is*. The
app combines them:

1. **On-device, real-time:** Apple Vision + Core ML (e.g. a YOLO model
   converted to Core ML) draws a box around "chair", "bottle", "laptop" at
   30 fps, with no network needed.
2. **Depth fusion:** take the detected box, read the LiDAR/TrueDepth depth
   inside it, convert to 3D points with the camera intrinsics, and fit an
   oriented bounding box. That gives width × height × depth in cm.
3. **Semantic layer (cloud LLM, optional):** send the photo + measured
   dimensions to a vision LLM (Claude) for richer answers: "IKEA Poäng
   armchair, ~68 × 82 × 100 cm, fits the 75 cm alcove with 7 cm spare."

**Real-life example:** point the phone at a parcel. On-device detection
says "box". LiDAR says 32 × 24 × 18 cm. The LLM adds "fits Royal Mail
Medium Parcel (61 × 46 × 46 cm), 2 kg limit". You then save it to MyPA as
a record.

---

## 5. Education & AI uses

- **Science/maths classes:** measure real objects, compute volume and
  surface area, and compare against the formula (cylinder volume on a real
  tin can).
- **Biology/anatomy:** 3D models of specimens, skulls, plants, viewable in
  AR on any iPhone (USDZ opens natively in Quick Look).
- **History/art:** students scan museum replicas or local landmarks into
  a shared class collection.
- **AI datasets:** each scan produces paired RGB + depth + mesh + label,
  which is exactly the training data 3D-vision models need. A scanning
  app is also a data-collection tool.
- **Personal archive (MyPA):** "my head is 57 cm, hat size M", "living room
  is 4.2 × 3.6 m", "the alcove is 75 cm wide", all saved as durable,
  searchable facts any AI can recall later.

---

## 5a. Existing apps (market check, Oct 2026)

Each building block already ships as a product. Nobody combines all of them.

| Category | Apps | Notes |
|---|---|---|
| Object / room 3D scanning | Polycam, Scaniverse (Niantic Spatial), KIRI Engine, RealityScan (Epic), 3D Scanner App | Polycam Pro ≈ $27/mo; Scaniverse on-device scanning free; KIRI free room/scene scans |
| Face / head scanning (TrueDepth) | Heges, EM3D, Orch / OpticALLY 3D Scan; Bellus3D (discontinued 2022) | Developers claim ~0.5 mm; EM3D independently validated at 0.39 mm vs CBCT |
| Quick measurement | Apple Measure (built in), Google Measure | AR point-to-point; auto-detects some objects |
| Box / parcel dimensioning | Parcel Measure, vMeasure, EazyMeasure; PackageX VisionSDK (SDK) | LiDAR iPhones only; ~1 cm claimed |
| Rooms / floor plans | Polycam, Canvas, magicplan, Room Planner (RoomPlan-based) | |
| Built into products | Apple Personalized Spatial Audio (TrueDepth ear scan), eyewear try-on/frame sizing apps | Proves TrueDepth is good enough for consumer fitting |

**Gap:** these are single-purpose tools. Scans stay inside each app's own
cloud, measurements aren't structured data, and nothing remembers "my
alcove is 75 cm" so an AI can use it later. The opportunity is the
*combination*: scan → recognise → measure → structured record in a
user-owned archive (MyPA) that any AI can query, plus education workflows.
The POC can also reuse these apps as accuracy baselines.

---

## 6. Recommended architecture

**Native iOS (Swift + SwiftUI + ARKit/RealityKit), iOS 17+.**

Why not React Native / Flutter: the valuable parts (TrueDepth depth streams,
LiDAR scene mesh, Object Capture, RoomPlan) are Apple-native APIs with thin or
missing cross-platform plugins. You'd write them natively anyway and gain
little. The scanning core must be native, and the UI shell can be SwiftUI.

```
┌──────────────────────── iOS app (SwiftUI) ────────────────────────┐
│  Mode picker:  [Face/Head]  [Object]  [Room]  [Quick measure]     │
│                                                                   │
│  TrueDepth module   LiDAR module          Object Capture module   │
│  ARFaceTracking     ARKit sceneDepth      ObjectCaptureSession    │
│  + depth stream     + raycast + RoomPlan  + PhotogrammetrySession │
│        │                  │                       │               │
│        └──────── Measurement engine ──────────────┘               │
│             (point cloud → OBB, distances, circumference)         │
│                           │                                       │
│        Vision/Core ML detector (on-device labels)                 │
│                           │                                       │
│        Export: USDZ / OBJ / PLY + JSON measurements               │
└───────────────────────────┬───────────────────────────────────────┘
                            │ (optional, user-initiated)
             MyPA API ── store record + thumbnail + metrics
             Claude vision ── semantic description
```

Development needs: a Mac with Xcode, an Apple Developer account (free account
for 7-day device installs; $99/yr for TestFlight/App Store), and a physical
iPhone (the simulator has no depth sensors). An iPhone **Pro** (12 Pro or
newer) is needed for LiDAR/Object Capture. Any Face ID iPhone covers TrueDepth.

---

## 7. POC proposal: "prove the numbers"

The POC's job is to measure our own accuracy against known ground truth.
Polish can wait.

### Scope (3 demos, ~2–3 weeks for one iOS developer)

| # | Demo | Sensor | Output | Pass criterion |
|---|---|---|---|---|
| 1 | **Quick measure:** tap two points or auto-box a detected object | LiDAR | W × H × D in cm + label | Box dims within **±1 cm** on 5 reference objects |
| 2 | **Face/head scan:** guided slow head turn | TrueDepth | mesh (PLY/USDZ) + interpupillary distance, face width, head circumference | IPD within **±1 mm** of a ruler/optician value; head circumference within **±5 mm** of tape measure |
| 3 | **Object scan:** walk around an object | Object Capture | textured USDZ + dimensions | Dims within **±2–3 mm** on a textured object (e.g. a shoebox) |

### Test protocol (repeatable, cheap ground truth)

- Credit card (85.60 × 53.98 mm), A4 sheet (210 × 297 mm), a 330 ml can
  (Ø 66 mm × 115 mm), a shoebox measured with a tape measure, a doorway.
- 10 scans per object, at 2 distances, 2 lighting conditions.
- Report mean error, standard deviation, and worst case in a CSV. That
  table becomes the honest accuracy claim for the product page.

### Out of scope for the POC

Android, accounts/sync, cloud processing, a polished UI, App Store submission.

---

## 8. MyPA integration (after the POC)

- A scan becomes a MyPA item (e.g. kind `note` or a new `scan`/`measurement`
  kind) with structured fields: `label`, `dimensions_mm`, `sensor`,
  `confidence`, `scanned_at`.
- **Current constraint:** `mypa/attachments.py` `ALLOWED_MIMES` accepts only
  images, PDF and audio. Storing the 3D model itself would need
  `model/vnd.usdz+zip` / `model/obj` / PLY support, plus magic-byte checks and
  size caps (scans run 5–50 MB). For the first iteration, store a **JPEG
  thumbnail + JSON measurements**, which already works today. Keep the mesh
  on the phone.

---

## 9. Privacy & legal (important for face scans)

- **Face geometry is biometric data.** It's special-category data under
  GDPR/UK GDPR, and covered by Illinois BIPA and similar US laws. You need
  explicit consent and a stated retention period, and should default to
  on-device processing.
- **Apple App Store Review Guideline 5.1.2(vi):** data from ARKit / depth /
  face-mapping APIs may not be used for advertising or data mining.
  Educational and measurement uses are fine, but say what you collect.
- **Children (education use):** extra rules (COPPA, UK Age Appropriate
  Design Code). Head scans of students need guardian consent. Object and
  room scans are much lower risk.
- MyPA's self-hosted, encrypted model is a genuine advantage here, because
  scans never have to touch a vendor cloud.

---

## 10. Known risks

- **Small objects and LiDAR:** below ~10 cm, LiDAR alone is unreliable. Use
  photogrammetry or TrueDepth (close range) instead.
- **Scanning other people's heads:** TrueDepth faces the user, so self-scan
  works (guided head turn with audio cues), but scanning someone else means
  pointing the screen away. Fallback: rear LiDAR/photogrammetry at lower
  detail.
- **Reflective, transparent, black or featureless surfaces** (glass, chrome,
  white walls) break every phone method.
- **Device/OS regressions:** Apple developer forums report Object Capture
  failing on iPhone 17 Pro under iOS 26.x (`sensorFailed`), while the same
  code works on an iPhone 12 Pro. Test on several devices early.
- **Non-Pro iPhones have no LiDAR** (including base iPhone 17 / Air), so the
  app must degrade gracefully to TrueDepth-only + estimated depth.

---

## Sources

- JMIR 2020 meta-analysis, mobile face scanners: https://www.jmir.org/2020/10/e22228
- Heliyon 2023, iPhone 11 Pro/Bellus3D vs 3dMDface: https://doaj.org/article/dd7bd738e3ff42a094f9ff97aaae512c
- Dentistry Journal 2024, iPhone 13 Pro vs CBCT: https://doaj.org/article/fc7110691b6648708cf5a8d0be2edc74
- Accuracy of mobile-device-compatible 3D scanners (Univ. of Iowa): https://iro.uiowa.edu/esploro/outputs/journalArticle/Accuracy-of-Mobile-Device-Compatible-3D-Scanners/9984914020302771
- Oral Maxillofac Surg 2024: https://link.springer.com/article/10.1007/s10006-024-01322-2
- Scientific Reports 2021, iPhone 12 Pro LiDAR in geosciences: https://doaj.org/article/05f6da2bb22e4343bec5db6fcf0ecf88
- iPhone 12 Pro LiDAR, geometric objects & indoor mapping: https://avesis.erciyes.edu.tr/yayin/a99156bd-ffe3-4421-af12-b3fd8af6118e/investigation-of-geometric-object-and-indoor-mapping-capacity-of-apple-iphone-12-pro-lidar
- Geodetski vestnik 2025, iPhone LiDAR with Scaniverse: https://geodetski-vestnik.com/arhiv/70/1/47_Yanchuk.pdf
- FIG 2022, iPhone 13 Pro LiDAR for inventory: https://fig.net/resources/proceedings/fig_proceedings/fig2022/papers/ts03g/TS03G_zaczek-peplinska_kowalska_11458_abs.pdf
- ISPRS 2024, iOS LiDAR apps: https://isprs-archives.copernicus.org/articles/XLVIII-2-W8-2024/431/2024/
- Apple AVDepthData accuracy: https://developer.apple.com/documentation/avfoundation/avdepthdata/accuracy
- Apple ObjectCaptureSession: https://developer.apple.com/documentation/realitykit/objectcapturesession
- Object Capture iPhone 17 Pro / iOS 26 reports: https://developer.apple.com/forums/thread/828928 · https://developer.apple.com/forums/thread/827216
- TrueDepth depth format discussion: https://developer.apple.com/forums/thread/707861
- Google ARCore Depth API: https://developers.google.com/ar/develop/depth
- ARCore depth & anchor stability preprint: https://www.researchsquare.com/article/rs-10991704
- Galaxy S10 5G 3D face unlock: https://www.androidcentral.com/galaxy-s10-5g-finally-has-3d-face-unlock-iphones
- Honor Magic7 Pro 3D face recognition: https://m.gsmarena.com/honor_magic7_pro-review-2786p2.php
- Huawei Mate series 3D face recognition: https://www.huaweicentral.com/all-huawei-mate-70-series-models-rumored-to-use-3d-face-recognition/amp/
