# External Interactions

Location Floor Plan has no external SaaS dependency. It interacts with Nautobot's database, object permissions, REST framework, media storage for normalized background PNGs, and static assets. SVG background support requires CairoSVG at runtime.

Automation should use `/api/plugins/location-floor-plan/` endpoints and revision headers to avoid lost updates.
