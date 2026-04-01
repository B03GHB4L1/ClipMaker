"""
ClipMaker — Streamlit Theme Patcher
Run this ONCE to eliminate the sidebar flash on page navigation.
It injects the ClipMaker CSS directly into Streamlit's index.html.

Usage:
    python patch_streamlit.py

To revert:
    python patch_streamlit.py --revert
"""

import sys
import os
import re

MARKER_START = "<!-- CLIPMAKER_THEME_START -->"
MARKER_END   = "<!-- CLIPMAKER_THEME_END -->"

CSS = """
@import url('https://fonts.googleapis.com/css2?family=Iosevka+Charon+Mono:ital,wght@0,300;0,400;0,500;0,700;1,400;1,500&family=Inter:wght@400;500;600;700;800;900&display=swap');
html,body,[class*="css"]{font-family:'Inter',sans-serif!important;background-color:#0e0e0e;}
.block-container{background-color:#0e0e0e!important;}
section[data-testid="stSidebar"]{background:#131313!important;border-right:1px solid rgba(255,255,255,0.05)!important;}
section[data-testid="stSidebar"] [data-testid="stSidebarNavLink"] span{
    font-family:'Iosevka Charon Mono',monospace!important;
    font-size:10px!important;font-weight:500!important;
    letter-spacing:0.18em!important;text-transform:uppercase!important;
    color:#adaaaa!important;
}
section[data-testid="stSidebar"] [data-testid="stSidebarNavLink"]:hover span{color:#DFFF00!important;}
section[data-testid="stSidebar"] [aria-current="page"] span{color:#DFFF00!important;}
section[data-testid="stSidebar"] [aria-current="page"]{background:#202020!important;border-right:3px solid #DFFF00!important;}
h1,h2,h3,h4,h5,h6{font-family:'Iosevka Charon Mono',monospace!important;text-transform:uppercase!important;}
h1{font-weight:700!important;}
h2,h3,h4,h5,h6{font-weight:500!important;}
"""

def find_streamlit_index():
    try:
        import streamlit
        path = os.path.join(os.path.dirname(streamlit.__file__), "static", "index.html")
        if os.path.exists(path):
            return path
    except ImportError:
        pass
    # Try common locations
    candidates = [
        # macOS — user installs (pip install --user) and Homebrew Python
        os.path.expanduser("~/Library/Python/3.11/lib/python/site-packages/streamlit/static/index.html"),
        os.path.expanduser("~/Library/Python/3.12/lib/python/site-packages/streamlit/static/index.html"),
        os.path.expanduser("~/Library/Python/3.10/lib/python/site-packages/streamlit/static/index.html"),
        os.path.expanduser("~/Library/Python/3.9/lib/python/site-packages/streamlit/static/index.html"),
        "/usr/local/lib/python3.11/site-packages/streamlit/static/index.html",
        "/usr/local/lib/python3.12/site-packages/streamlit/static/index.html",
        "/usr/local/lib/python3.10/site-packages/streamlit/static/index.html",
        "/opt/homebrew/lib/python3.11/site-packages/streamlit/static/index.html",
        "/opt/homebrew/lib/python3.12/site-packages/streamlit/static/index.html",
        "/opt/homebrew/lib/python3.10/site-packages/streamlit/static/index.html",
        # Linux — user installs
        os.path.expanduser("~/.local/lib/python3.11/site-packages/streamlit/static/index.html"),
        os.path.expanduser("~/.local/lib/python3.10/site-packages/streamlit/static/index.html"),
        os.path.expanduser("~/.local/lib/python3.9/site-packages/streamlit/static/index.html"),
        # Windows
        r"C:\Users\{}\AppData\Local\Programs\Python\Python311\Lib\site-packages\streamlit\static\index.html".format(os.environ.get("USERNAME", "")),
        r"C:\Users\{}\AppData\Roaming\Python\Python311\site-packages\streamlit\static\index.html".format(os.environ.get("USERNAME", "")),
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return None


def patch(index_path):
    with open(index_path, "r", encoding="utf-8") as f:
        content = f.read()

    if MARKER_START in content:
        print("Already patched. Run with --revert first if you want to re-patch.")
        return False

    inject = f"\n{MARKER_START}\n<style>{CSS}</style>\n{MARKER_END}\n"
    # Inject just before </head>
    if "</head>" not in content:
        print("Could not find </head> in index.html — unexpected format.")
        return False

    # Backup
    backup = index_path + ".clipmaker_backup"
    if not os.path.exists(backup):
        with open(backup, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"Backup saved to: {backup}")

    patched = content.replace("</head>", inject + "</head>", 1)
    with open(index_path, "w", encoding="utf-8") as f:
        f.write(patched)
    print(f"Patched: {index_path}")
    print("Restart Streamlit for changes to take effect.")
    return True


def revert(index_path):
    with open(index_path, "r", encoding="utf-8") as f:
        content = f.read()

    if MARKER_START not in content:
        print("No ClipMaker patch found.")
        return

    cleaned = re.sub(
        rf"\n?{re.escape(MARKER_START)}.*?{re.escape(MARKER_END)}\n?",
        "", content, flags=re.DOTALL
    )
    with open(index_path, "w", encoding="utf-8") as f:
        f.write(cleaned)
    print(f"Reverted: {index_path}")
    print("Restart Streamlit for changes to take effect.")


if __name__ == "__main__":
    index = find_streamlit_index()
    if not index:
        print("Could not find Streamlit's index.html automatically.")
        print("Please provide the path manually:")
        index = input("Path: ").strip().strip('"')
        if not os.path.exists(index):
            print("File not found.")
            sys.exit(1)

    print(f"Found: {index}")

    if "--revert" in sys.argv:
        revert(index)
    else:
        patch(index)
