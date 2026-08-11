#!/usr/bin/env python3
"""Render a saved graph with the app's own renderer and screenshot it.

pyvis lays out with physics, so a screenshot taken too early catches the graph
mid-settle: wait, freeze, fit, then zoom slightly past fit - fit alone leaves
labels too small at README width. Requires Chrome and a running app is NOT
needed (the HTML is self-contained).

    python3 studies/capture_graph.py <graphml-path-relative-to-src> <out.png> [zoom] [hide_nogo]
"""
import os
import subprocess
import sys

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

INJECT = """
<script>
setTimeout(function () {
  try {
    if (typeof network !== 'undefined') {
      network.setOptions({physics: {enabled: false}});
      network.fit({animation: false});
      network.moveTo({scale: network.getScale() * %(zoom)s, animation: false});
    }
  } catch (e) {}
}, 2500);
</script>
"""


def capture(graph_rel, out_png, zoom=1.2, hide_nogo=False,
            width=1500, height=950):
    sys.path.insert(0, os.path.join(ROOT, 'src'))
    os.chdir(os.path.join(ROOT, 'src'))
    import app
    name = os.path.basename(out_png).replace('.png', '')
    html = app.visualize_graph_pyvis(graph_rel, f'cap_{name}',
                                     hide_nogo=hide_nogo)
    html_path = os.path.join(ROOT, 'src', 'static', html)
    with open(html_path) as f:
        doc = f.read()
    doc = doc.replace('</body>', INJECT % {'zoom': zoom} + '</body>')
    with open(html_path, 'w') as f:
        f.write(doc)
    out = out_png if os.path.isabs(out_png) else os.path.join(ROOT, out_png)
    subprocess.run([CHROME, '--headless', '--disable-gpu', '--hide-scrollbars',
                    f'--window-size={width},{height}',
                    f'--screenshot={out}', '--virtual-time-budget=9000',
                    f'file://{html_path}'], capture_output=True, timeout=90)
    os.remove(html_path)
    return out, os.path.getsize(out) if os.path.exists(out) else 0


if __name__ == '__main__':
    g, o = sys.argv[1], sys.argv[2]
    zoom = float(sys.argv[3]) if len(sys.argv) > 3 else 1.2
    hide = len(sys.argv) > 4 and sys.argv[4] == 'hide_nogo'
    print(capture(g, o, zoom=zoom, hide_nogo=hide))
