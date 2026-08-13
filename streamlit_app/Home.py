import streamlit as st

from style import inject_global_styles
from data_loader import load_gold_table, load_trend_table


# Animated 3D particle-network visual for the hero - Three.js via a components.v1.html iframe,
# not injected through st.markdown(unsafe_allow_html=True), because raw <script> tags in
# st.markdown are unreliable across Streamlit versions (often stripped or not re-executed on
# rerun). components.v1.html guarantees the script actually runs, at the cost of rendering in
# its own iframe - which is also why this sits in its own hero column rather than attempting a
# true full-page background: an iframe can't reliably paint "behind" content outside it via
# z-index tricks, so a robust in-flow placement was chosen over a fragile one.
#
# Colours match the app's existing Okabe-Ito palette (1_Dashboard.py's ARCHETYPE_COLORS) -
# vermillion particles, blue connections - so this reads as part of the same visual system
# rather than a decorative add-on with its own unrelated colour choices. Particles drift and
# slowly rotate; connecting lines redraw between nearby particles each frame, evoking a
# network of data points - a deliberate thematic tie to "a network of LGA data", not just
# motion for its own sake.
HERO_ANIMATION_HTML = """
<div id="hero-canvas-container" style="width:100%; height:420px;"></div>
<script src="https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.min.js"></script>
<script>
(function() {
  const container = document.getElementById('hero-canvas-container');
  const width = container.clientWidth;
  const height = container.clientHeight;

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(60, width / height, 0.1, 1000);
  camera.position.z = 45;

  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setSize(width, height);
  renderer.setPixelRatio(window.devicePixelRatio);
  container.appendChild(renderer.domElement);

  // Bounds widened (x: 70 -> 170, count: 90 -> 160) to match the container going from a
  // ~40%-width side column to full page width - keeping the old narrow bounds would have
  // just stretched a small clustered scene into a lot of empty space at the edges rather
  // than actually filling the wider canvas.
  const PARTICLE_COUNT = 160;
  const positions = [];
  const particles = [];
  for (let i = 0; i < PARTICLE_COUNT; i++) {
    const x = (Math.random() - 0.5) * 170;
    const y = (Math.random() - 0.5) * 50;
    const z = (Math.random() - 0.5) * 50;
    positions.push(x, y, z);
    particles.push({ x, y, z, vx: (Math.random()-0.5)*0.02, vy: (Math.random()-0.5)*0.02, vz: (Math.random()-0.5)*0.02 });
  }

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));

  const material = new THREE.PointsMaterial({ color: 0xD55E00, size: 0.9, transparent: true, opacity: 0.85 });
  const points = new THREE.Points(geometry, material);
  scene.add(points);

  const lineMaterial = new THREE.LineBasicMaterial({ color: 0x0072B2, transparent: true, opacity: 0.25 });
  const lineGeometry = new THREE.BufferGeometry();
  let linePositions = [];

  function updateLines() {
    linePositions = [];
    const MAX_DIST = 18;
    for (let i = 0; i < particles.length; i++) {
      for (let j = i + 1; j < particles.length; j++) {
        const dx = particles[i].x - particles[j].x;
        const dy = particles[i].y - particles[j].y;
        const dz = particles[i].z - particles[j].z;
        const dist = Math.sqrt(dx*dx + dy*dy + dz*dz);
        if (dist < MAX_DIST) {
          linePositions.push(particles[i].x, particles[i].y, particles[i].z);
          linePositions.push(particles[j].x, particles[j].y, particles[j].z);
        }
      }
    }
    lineGeometry.setAttribute('position', new THREE.Float32BufferAttribute(linePositions, 3));
  }

  const lines = new THREE.LineSegments(lineGeometry, lineMaterial);
  scene.add(lines);

  let frame = 0;
  function animate() {
    requestAnimationFrame(animate);
    frame += 1;

    for (let i = 0; i < particles.length; i++) {
      const p = particles[i];
      p.x += p.vx; p.y += p.vy; p.z += p.vz;
      if (Math.abs(p.x) > 85) p.vx *= -1;
      if (Math.abs(p.y) > 25) p.vy *= -1;
      if (Math.abs(p.z) > 25) p.vz *= -1;
      positions[i*3] = p.x; positions[i*3+1] = p.y; positions[i*3+2] = p.z;
    }
    geometry.attributes.position.needsUpdate = true;

    if (frame % 3 === 0) updateLines();

    points.rotation.y += 0.0015;
    lines.rotation.y += 0.0015;

    renderer.render(scene, camera);
  }
  animate();

  window.addEventListener('resize', function() {
    const w = container.clientWidth;
    const h = container.clientHeight;
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    renderer.setSize(w, h);
  });
})();
</script>
"""


def _render_hero_animation(html: str, height: int) -> None:
    """st.iframe is the current API for this (components.v1.html is deprecated, removal
    already past its stated date in newer Streamlit releases) - but st.iframe isn't present
    in every installed Streamlit version yet, confirmed the hard way (AttributeError on an
    older install). Try the current API, fall back to the older one, rather than requiring a
    specific version - this also protects against Streamlit Community Cloud (Process 6)
    potentially running a different version than whatever's on your laptop."""
    if hasattr(st, "iframe"):
        st.iframe(html, height=height)
    else:
        import streamlit.components.v1 as components
        components.html(html, height=height)


def home_page() -> None:
    inject_global_styles()

    gold_df = load_gold_table()
    trend_df = load_trend_table()

    # --- Hero: text on top (full width, no longer sharing a column), animation full-width
    # below - same "give it its own row, not a squeezed column" treatment as the dashboard's
    # map, and for the same reason: a visual this deliberate deserves real screen space.
    st.markdown(
        "<div style='padding: 3rem 0 0.5rem 0;'>"
        "<div style='font-size: 0.95rem; font-weight: 600; letter-spacing: 0.08em; "
        "text-transform: uppercase; opacity: 0.65;'>VIDA Data &amp; IT Graduate Program — Portfolio Project</div>"
        "</div>",
        unsafe_allow_html=True,
    )
    # Custom-sized headline rather than st.title - the hero deliberately goes bigger than
    # the global h1 size (set in style.py, used for every other section heading on the
    # page), to give this one spot real visual weight rather than reading as "just a large
    # section title". Bumped back up (3.6rem -> 4.4rem) now that it has the full row again.
    st.markdown(
        "<h1 style='font-size: 4.4rem !important; line-height: 1.05; margin: 0.2rem 0 1.5rem 0; "
        "max-width: 1100px;'>Where Should Victoria Build Next?</h1>",
        unsafe_allow_html=True,
    )
    st.markdown(
        "<div style='font-size: 1.3rem; line-height: 1.6; max-width: 820px; opacity: 0.9;'>"
        "A data-driven infrastructure investment priority model across Victoria's 79 Local "
        "Government Areas — combining population growth, crash severity, traffic volume, and "
        "dwelling approvals into a single, explainable score, cross-validated with unsupervised "
        "clustering."
        "</div>",
        unsafe_allow_html=True,
    )

    st.write("")
    st.write("")
    # st.button + st.switch_page(page_object) instead of st.page_link(path_string) -
    # page_link has a confirmed, still-open history of path-resolution bugs across
    # Streamlit versions (KeyError: 'url_pathname' among them -
    # github.com/streamlit/streamlit/issues/8070, #8080, #10572). Passing the actual Page
    # object to switch_page sidesteps path resolution entirely.
    #
    # Bigger tap target for the hero's primary CTA - custom padding via a wrapping div
    # rather than relying on Streamlit's default button size, which reads as
    # secondary-action-sized even with type="primary".
    st.markdown(
        "<style>div[data-testid='stButton'] > button {"
        "padding: 0.85rem 2rem !important; font-size: 1.1rem !important; font-weight: 600 !important;"
        "}</style>",
        unsafe_allow_html=True,
    )
    if st.button("Open the interactive dashboard →", type="primary"):
        st.switch_page(dashboard_page)

    st.write("")
    # NOTE: verified the JS syntax parses cleanly (node --check) and this Python call raises
    # no exception, but WebGL rendering itself needs an actual browser/GPU context that isn't
    # available to verify from here - check this visually before trusting it.
    # Height bumped 420 -> 600 to match the width jump (was in a ~40%-width column, now full
    # width) - same "bigger container needs a bigger visual, not just a stretched one"
    # reasoning as the map. HERO_ANIMATION_HTML's particle field bounds were widened to match
    # (see near its definition) so particles fill the wider canvas instead of clustering in
    # the middle with empty space at the edges.
    _render_hero_animation(HERO_ANIMATION_HTML, height=600)

    st.write("")
    st.divider()

    # --- Key findings, pulled live from the data - not hardcoded ---
    st.subheader("At a glance")

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("LGAs analysed", len(gold_df))

    with col2:
        if len(gold_df) > 0:
            top = gold_df.sort_values("priority_score", ascending=False).iloc[0]
            st.metric("Highest priority", top["LGA"], help=top["archetype"])

    with col3:
        hotspot_count = (gold_df["archetype"] == "Growth Hotspot – High Strain").sum()
        st.metric("LGAs in Growth Hotspot", int(hotspot_count))

    with col4:
        if trend_df is not None:
            rising = int(trend_df["trending_up"].sum())
            st.metric("LGAs with rising traffic", f"{rising} / {len(trend_df)}")
        else:
            st.metric("Trend model", "Not yet run")

    st.divider()

    # --- The pitch, in plain terms ---
    st.subheader("What this actually does")
    st.markdown(
        "Most infrastructure-priority tools either hide their logic in a black-box model or "
        "reduce a genuinely multi-dimensional problem to one number nobody can interrogate. This "
        "project does neither: every LGA's score is a transparent sum of four measurable "
        "factors, each independently adjustable, and the same ranking is cross-checked against a "
        "completely separate unsupervised clustering model — two different methods, checked "
        "against each other, not just asserted."
    )
    st.markdown(
        "**This is a directional, proxy prioritisation tool, not a capital-planning-grade causal "
        "model** — open government data has no true \"infrastructure spend\" variable, so it "
        "surfaces where growth is outpacing capacity, and leaves the investment decision to the "
        "people who actually hold that context."
    )

    st.divider()

    # --- How it was built ---
    st.subheader("How it was built")
    b1, b2, b3 = st.columns(3)

    with b1:
        with st.container(border=True):
            st.markdown("##### Data & Composite Score")
            st.markdown(
                "Five Victorian and Commonwealth open datasets, ingested and joined in Databricks "
                "(PySpark). A transparent weighted score combines growth pressure and existing "
                "strain — adjustable live in the dashboard."
            )

    with b2:
        with st.container(border=True):
            st.markdown("##### K-Means Validation")
            st.markdown(
                "An independent clustering model (scikit-learn) segments LGAs into priority "
                "archetypes. Cross-checked against the composite score's own ranking — agreement "
                "between two unrelated methods is the actual evidence, not either one alone."
            )

    with b3:
        with st.container(border=True):
            st.markdown("##### Trend Forecast")
            st.markdown(
                "A simple linear trend fitted on historical traffic volume (2005–2015) and "
                "validated against a held-out year (2019) — flags which LGAs are trending toward "
                "higher strain, not just where they sit today."
            )

    st.divider()
    st.caption(
        "Data sources: Victoria in Future population projections, Victorian Road Crash Data, "
        "Traffic Signal Volume and Historical AADT (Dept. of Transport and Planning), Building "
        "Permit Activity Data (Building and Plumbing Commission), ABS ASGS LGA boundaries."
    )


# --- Navigation router ---
# st.navigation/st.Page (current recommended API) instead of the legacy pages/-folder
# auto-discovery + string-based st.page_link - that older mechanism is what threw the
# KeyError: 'url_pathname' in the first place. set_page_config must be called exactly once,
# here, before pg.run() - it was removed from pages/1_Dashboard.py for this reason; calling
# it twice raises its own error under this navigation model.
st.set_page_config(page_title="Where Should Victoria Build Next?", layout="wide")

home = st.Page(home_page, title="Home", url_path="", default=True)
dashboard_page = st.Page("1_Dashboard.py", title="Dashboard")
docs_page = st.Page("2_Documentation.py", title="How it works")

pg = st.navigation([home, dashboard_page, docs_page])
pg.run()