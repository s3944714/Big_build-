"""
Shared visual styling across all pages. Injected via st.markdown(unsafe_allow_html=True) -
the one approach that reliably works across Streamlit versions for typography-level tweaks
that aren't exposed as first-class theming options (font-family, heading weight/spacing,
content width). Deliberately does NOT hardcode background/text colours - that would fight
Streamlit's own light/dark theme switching, which the app should keep respecting.
"""
import streamlit as st


def inject_global_styles() -> None:
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

        html, body, [class*="css"] {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
        }

        /* Headings: tighter letter-spacing and heavier weight reads as "designed" rather than
        the default markdown-report look - this is the single highest-leverage typography
        change for making a Streamlit app feel like a built product rather than a notebook
        export. */
        h1 {
            font-weight: 800 !important;
            letter-spacing: -0.02em;
            font-size: 2.6rem !important;
        }
        h2 {
            font-weight: 700 !important;
            letter-spacing: -0.01em;
        }
        h3, h4, h5 {
            font-weight: 600 !important;
        }

        /* Body/markdown text: slightly larger and more generous line-height than Streamlit's
        default - small, cramped body text is what makes a dashboard feel like a debug view
        rather than something meant to be read. */
        p, li {
            font-size: 1.02rem;
            line-height: 1.65;
        }

        /* Content width: generous, not capped tight - a tight cap (previously 1400px) directly
        fights a full-width map/table, which is the actual priority for this app. Still capped
        at 1900px rather than removed entirely, purely as a sane ceiling for extreme ultrawide
        monitors - on any normal desktop/laptop this is effectively full width. */
        .block-container {
            max-width: 1900px;
            padding-top: 2rem;
        }

        /* st.metric styling - bigger, bolder values read as genuine headline numbers rather
        than small debug-panel text, which matters most on the landing page's "At a glance"
        row where these numbers ARE the pitch. */
        [data-testid="stMetricValue"] {
            font-size: 2.1rem !important;
            font-weight: 800 !important;
        }
        [data-testid="stMetricLabel"] {
            font-size: 0.9rem !important;
            opacity: 0.7;
        }

        /* Bordered containers (st.container(border=True), used throughout for grouped
        sidebar controls and callouts): a touch of corner rounding and a soft shadow reads as
        an intentional card rather than Streamlit's flat default border - subtle enough to
        not fight either theme. */
        div[data-testid="stVerticalBlockBorderWrapper"] {
            border-radius: 12px !important;
            box-shadow: 0 1px 3px rgba(0,0,0,0.06);
        }

        /* Dividers: Streamlit's default <hr> is quite heavy/dark - a lighter, more restrained
        rule reads as a section break rather than a hard visual wall. */
        hr {
            opacity: 0.15;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )