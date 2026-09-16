# AgentLens public website

Static HTML, CSS, and JavaScript. No build step or runtime framework.
Product SDK, CLI, engine, tests, and release files are outside this change.

## Preview

From the repository root:

```sh
python -m http.server 8765 --bind 127.0.0.1
```

Open <http://127.0.0.1:8765/>.

## Editorial redesign

All page and component surfaces now use a white background, with dark text for
contrast. The original green 3D lens, red failure node, hero headline, layout,
and interactions remain. Selection states retain subtle green/red tints.

Page sequence:
1. Navigation and hero.
2. Large six-event investigation with selectable input/output, tool, latency,
   and cost fields; adjacent cause, evidence, confidence, and fix.
3. One interactive failure map instead of six feature cards.
4. Two restrained compatibility rows around a large centered statement.
5. Local-first editorial statement.
6. Asymmetric installation CTA.
7. Editorial footer with existing destinations only.

Removed the workflow strip, audience cards, separate provider cards, privacy
diagram, repeated setup panels, and standalone terminal showcase. CLI output is
now a native disclosure inside the investigation. Source installation remains a
disclosure beside the final command.

The user-supplied references inform whitespace, hierarchy, asymmetric columns,
and the integration-row composition, not another company's identity or copy.
IBM Plex Sans and JetBrains Mono retain the technical voice; the serif footer
statement provides an editorial finish. No additional 3D objects were added.

## Assets and references

- `agentlens-lens.svg` and `agentlens-mark.svg` preserve the AgentLens identity.
  SVG shading and restrained CSS perspective require no WebGL or canvas.
- OpenAI and Anthropic symbols are locally served SVGs from
  <https://svgl.app/library/openai.svg> and
  <https://svgl.app/library/anthropic_black.svg>.
  Names/symbols identify technologies, not endorsements or partnerships.
- Other technology names are typeset labels, not invented official logos.
- ui-ux-pro-max informed hierarchy, editorial spacing, contrast, responsive
  layout, keyboard focus, and reduced-motion decisions.
- Earlier 21st references were Animated Beam by Dillion Verma and 3D Card Effect
  by Manu Arora. Only their interaction concepts informed the original hero.
  No component framework or animation dependency was installed.

## Behavior and truthfulness

The investigation is explicitly illustrative: the local demo's routing failure
extended with a retry. Timings are simulated, cost is not recorded, and no
customer data or live model call is implied. The 0.85 score is evidence strength,
not a calibrated probability of correctness. Failure-map examples describe the
evidence needed, not universal classifier coverage.

OpenAI and Anthropic capture applies to supported SDK methods. LangGraph is
scoped to the documented patch/compilation and stream-mode limits.
CrewAI, AutoGen, and PydanticAI are conditional provider passthrough, not verified
native framework integrations. Privacy wording distinguishes local diagnosis,
opt-in remote diagnosis, the agent's own API calls, and best-effort anonymization.

Hero animation finishes within 4.6 seconds; replay is explicit. Two slow opposing
logo rows pause offscreen, in a hidden document, on hover/focus, and with a pause
button. Reduced motion removes animations and shows the original logo groups
without duplicate visual tracks. Repeated groups are hidden from assistive
technology. Without JS, technology names wrap into static rows.

Trace and failure buttons expose selected states and update labelled live
regions. Copy buttons announce success or an actionable failure. Mobile
navigation closes with Escape and returns focus to its control. CLI and source
installation use native disclosures; deep links open them.

## Verification

Checked September 16, 2026:

- Desktop/tablet/mobile viewport checks; no document horizontal overflow.
- Visually inspected hero, investigation, evidence, failure map, integration
  rows, local-first section, installation CTA, and footer.
- All six trace selections and six failure selections update correctly.
- Tested keyboard trace selection, mobile menu/Escape, clipboard confirmation,
  marquee pause state, and CLI disclosure link.
- No browser console errors or broken images in the checked session.
- One h1, no duplicate IDs, no broken local anchors or missing local assets.
- White-theme contrast token checks: primary text 16.20:1, muted text 6.47:1,
  green text 5.32:1, selected failure text 6.32:1.
- Reduced-motion CSS/JS reviewed; no OS preference emulation or formal
  screen-reader/cross-browser certification performed.
- `node --check website/app.js` and `git diff --check` pass.
- No website build/lint framework is configured. Product tests are outside scope.

The page and its seven local assets total about 76 KB uncompressed / 21 KB gzip,
excluding Google Fonts. Fonts use display=swap and local fallbacks. Compression
figures are estimates, not a claim about hosting configuration. No trackers,
third-party scripts, raster hero assets, or new dependencies were added.
