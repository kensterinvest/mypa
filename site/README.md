# MyPA landing site

The marketing / explainer landing page for MyPA, served at
**https://mypa.z-tidus.com/**. Pure static HTML/CSS/JS, no framework.

Edit `index.html` / `assets/css/style.css` / `assets/js/demo.js`. On push
to `main`, GitHub Actions deploys to GitHub Pages from this directory.

For VPS deployment, see `deploy/Caddyfile.snippet`. The production VPS
serves this site at `mypa.z-tidus.com/` root, the Angular dashboard at
`/app/`, and the API/MCP routes at their existing paths — all from the
same Caddy site block.
