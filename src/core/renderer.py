import os
import json

def get_template_path():
    script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(script_dir, "assets", "template.html")

def _load_asset(assets_dir, filename):
    try:
        path = os.path.join(assets_dir, filename)
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        print(f"Warning: Failed to load asset {filename}: {e}")
        return ""

def render_markdown(md_content, is_dark, assets_dir, scroll_x=0, scroll_y=0):
    template_path = get_template_path()
    try:
        with open(template_path, 'r', encoding='utf-8') as f:
            template = f.read()
    except Exception as e:
        return f"<html><body><h2>Error loading template</h2><p>{e}</p></body></html>"

    theme_val = "dark" if is_dark else "light"
    mermaid_theme = "dark" if is_dark else "default"

    # Read and inline all CSS and JS assets to prevent CORS / URI scheme restrictions
    style_github_markdown = _load_asset(assets_dir, "github-markdown.min.css")
    # Only the active theme's highlight.js stylesheet is embedded: an inline
    # <style> tag has no working "disabled" HTML attribute (only <link>
    # honors it), so embedding both and toggling that attribute left the
    # dark theme's colors always winning the cascade regardless of mode.
    style_highlight_theme = _load_asset(
        assets_dir, "highlight-github-dark.min.css" if is_dark else "highlight-github.min.css"
    )
    script_marked = _load_asset(assets_dir, "marked.min.js")
    script_highlight = _load_asset(assets_dir, "highlight.min.js")
    script_mermaid = _load_asset(assets_dir, "mermaid.min.js")

    # Rewrite absolute file:/// URLs to app-local:/// for images in markdown
    md_content = md_content.replace("file:///", "app-local:///")
    # Escape "</" so a literal "</script>" (or "</style>") inside the
    # document content can't prematurely close the enclosing <script> tag
    # this gets embedded in below.
    raw_md_json = json.dumps(md_content).replace("</", "<\\/")

    html = template
    html = html.replace("{{ASSETS_DIR}}", assets_dir)
    html = html.replace("{{STYLE_GITHUB_MARKDOWN}}", style_github_markdown)
    html = html.replace("{{STYLE_HIGHLIGHT_THEME}}", style_highlight_theme)
    html = html.replace("{{SCRIPT_MARKED}}", script_marked)
    html = html.replace("{{SCRIPT_HIGHLIGHT}}", script_highlight)
    html = html.replace("{{SCRIPT_MERMAID}}", script_mermaid)
    html = html.replace("{{THEME}}", theme_val)
    html = html.replace("{{MARKDOWN_JSON}}", raw_md_json)
    html = html.replace("{{MERMAID_THEME}}", mermaid_theme)
    html = html.replace("{{SCROLL_X}}", str(scroll_x))
    html = html.replace("{{SCROLL_Y}}", str(scroll_y))

    try:
        with open("/tmp/debug_rendered.html", "w", encoding="utf-8") as f:
            f.write(html)
    except Exception:
        pass

    return html
