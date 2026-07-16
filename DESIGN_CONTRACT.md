# Visual Design Contract

Approval status: approved by the user on 2026-07-16.

The image-generation surface was unavailable during planning. The user explicitly approved the desktop, mobile portrait, and mobile landscape text concepts as the binding implementation direction.

## Locked Elements

- Deep charcoal operational default with a light print/export theme.
- Dominant horizontal wind map, compact command bar, right analysis rail, and lower analytical band.
- Cyan-to-deep-teal wind-speed scale; amber for low support; gray for missing; red only for events and risk.
- Real time positions and discrete observed-time playback with at most 200 ms visual emphasis.
- No continuous particles, interpolated frames, decorative gradients, nested cards, marketing hero, or generic atmosphere.
- Desktop, mobile portrait, and mobile landscape preserve the same time, height, quality, caveat, and selected state.
- Risk text always says theoretical advection and analysis reference, never safety or evacuation boundary.

## Visualization Inventory

| Layer | Analytical job | Renderer | Interaction and fallback | QA |
|---|---|---|---|---|
| Horizontal wind map | Show where supported wind goes, its speed, quality and event-relative direction | Canvas2D plus HTML controls | Click/keyboard selection, zoom/reset, static screenshot | U/V invariant, nonblank pixels, coordinate spot checks |
| Real time axis | Preserve actual timestamps and expose observation gaps | HTML controls | Step, play, keyboard, reduced-motion discrete state | Gap width and synchronized-state tests |
| Time-height profile | Show temporal and vertical wind-speed change without filling gaps | Canvas2D plus HTML labels | Click to select time/height | Missing cells, shared P95 scale and crosshair tests |
| Coverage matrix | Show whether conclusions have observation support | Canvas2D plus HTML labels | Click to select time/height | Observation counts and low-support tint tests |
| Rolling wind rose | Summarize direction over a historical window | SVG | Flow/from toggle; sample-insufficient fallback | Window, gap reset and direction-bin tests |
| Deterministic brief | Give a ten-second frontline read | HTML text | Always visible; screen-reader summary | Forbidden-safety-language test |

All substantial layers received local Canvas, cartographic, accessibility and visualization-testing specialist passes. No subagent delegation was authorized.

## Responsive Continuation

- Desktop 1440x900: map dominates the first viewport, brief and selected point stay in the right rail, profile and coverage remain visible below.
- Mobile portrait 390x844: map appears before analysis controls, brief follows it, and rose/profile/coverage use a three-way segmented view.
- Mobile landscape 844x390: map uses about 68% of the width, analysis uses about 32%, and the real timeline remains reachable.
- Primary touch targets are at least 44 CSS px. Hover information has tap, focus or always-visible alternatives.
