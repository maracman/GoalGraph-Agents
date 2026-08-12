import React, { useEffect, useState } from 'react';

/**
 * The graph viewer's legend, fetched from the renderer rather than written out
 * again here.
 *
 * There used to be two hand-written legends, one in GraphView and one in
 * GraphLibrary, and they had drifted from the renderer and from each other.
 * Both claimed blue meant "active aim" and dashed meant "failed", when blue
 * means Go and dashed means the judge was guessing rather than checking. A
 * legend that contradicts the picture is worse than no legend, so the colours
 * now come from /api/graph_legend, which is built from the same constants the
 * renderer draws with.
 *
 * `inline` picks the compact strip that sits under an embedded viewer; the
 * default is the stacked block.
 */
const GraphLegend = ({ inline = false }) => {
  const [legend, setLegend] = useState(null);

  useEffect(() => {
    let cancelled = false;
    fetch('/api/graph_legend')
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (!cancelled && d && d.legend) setLegend(d.legend);
      })
      .catch(() => {
        /* No legend is better than a wrong one, so show nothing on failure. */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (!legend) return null;

  const nodes = legend.nodes || [];
  const edges = legend.edges || [];
  const notes = legend.notes || [];

  return (
    <div className={inline ? 'graph-legend-inline' : 'graph-legend'}>
      {!inline && <h3>Graph Legend</h3>}

      <div className="legend-row">
        {nodes.map((item) => (
          <div className="legend-item" key={`node-${item.label}`}>
            <div
              className="legend-color"
              style={{ backgroundColor: item.colour }}
              title={item.meaning || ''}
            />
            <span title={item.meaning || ''}>{item.label}</span>
          </div>
        ))}
      </div>

      <div className="legend-row">
        {edges.map((item) => (
          <div className="legend-item" key={`edge-${item.label}`}>
            <div
              className="legend-line"
              style={{
                borderTop: `2px ${item.dashed ? 'dashed' : 'solid'} ${item.colour}`,
              }}
              title={item.meaning || ''}
            />
            <span title={item.meaning || ''}>{item.label}</span>
          </div>
        ))}
        <div className="legend-item">
          <div className="legend-line" style={{ borderTop: '2px dashed #6b7280' }} />
          <span>judged, not checked</span>
        </div>
      </div>

      {notes.length > 0 && (
        <ul className="legend-notes">
          {notes.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      )}
    </div>
  );
};

export default GraphLegend;
