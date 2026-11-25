"""The app's own three.js pages (armour_gen_editor, landmark_editor, skeleton_view) served by the web UI as pages of
their own, with the shell's look put in (adapters/forge.*) and any page's adapter; the page files stay untouched."""
from pathlib import Path

HERE = Path(__file__).resolve().parent
FORGE_CSS = HERE / "adapters" / "forge.css"
FORGE_JS = HERE / "adapters" / "forge.js"


def inject(html: str, css=(), js=()) -> str:
    """Styles at the end of <head>, scripts before </body> (classic scripts: they run before the page's own module)."""
    st = "".join(f"<style>\n{Path(f).read_text(encoding='utf-8')}\n</style>\n" for f in (FORGE_CSS, *css))
    sc = "".join(f"<script>\n{Path(f).read_text(encoding='utf-8')}\n</script>\n" for f in (FORGE_JS, *js))
    html = html.replace("</head>", st + "</head>", 1)
    i = html.rfind("</body>")
    return html[:i] + sc + html[i:] if i >= 0 else html + sc
