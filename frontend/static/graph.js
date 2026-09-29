/* Local Cytoscape renderer for evidence-carrying transaction traces. */
(() => {
  let cy = null;
  let trace = null;
  let callbacks = {};

  const short = value => value ? `${value.slice(0, 7)}…${value.slice(-5)}` : "Unknown";
  const amountWidth = amount => Math.max(2, Math.min(9, 2 + Math.log10(Number(amount || 0) + 1) * 2));

  function nodeLabel(node) {
    if (node.role === "suspect") return "Suspect wallet";
    if (node.role === "vasp") return node.label || "Reviewed VASP";
    if (node.role === "bridge") return node.label || "Bridge";
    if (node.role === "mixer") return node.label || "Mixer";
    if (node.role === "swap") return node.label || "Swap service";
    return short(node.address);
  }

  function style() {
    return [
      { selector: "node", style: {
        "label": "data(label)", "font-family": "Inter, ui-sans-serif, system-ui, sans-serif", "font-size": 11,
        "font-weight": 700, "color": "#dce8ff", "text-valign": "bottom", "text-margin-y": 8,
        "text-wrap": "wrap", "text-max-width": 110, "text-background-opacity": 0.82,
        "text-background-color": "#07111f", "text-background-padding": 3, "text-background-shape": "roundrectangle",
        "width": 36, "height": 36, "background-color": "#506781", "border-width": 2, "border-color": "#91a7c0"
      }},
      { selector: "node[role = 'suspect']", style: { "background-color": "#e34b55", "border-color": "#ffabb3", "width": 54, "height": 54, "shadow-blur": 20, "shadow-color": "#e34b55", "shadow-opacity": 0.55 }},
      { selector: "node[role = 'observed']", style: { "background-color": "#d99c38", "border-color": "#ffd37a" }},
      { selector: "node[role = 'vasp']", style: { "shape": "round-rectangle", "background-color": "#16a678", "border-color": "#72f0b8", "width": 64, "height": 42, "shadow-blur": 20, "shadow-color": "#16a678", "shadow-opacity": 0.5 }},
      { selector: "node[role = 'bridge']", style: { "shape": "hexagon", "background-color": "#4b8cff", "border-color": "#a5c7ff" }},
      { selector: "node[role = 'mixer']", style: { "shape": "octagon", "background-color": "#a44961", "border-color": "#ff9cb3" }},
      { selector: "node[role = 'swap']", style: { "shape": "hexagon", "background-color": "#7a63df", "border-color": "#c3b8ff" }},
      { selector: "node[frontier]", style: { "shape": "diamond", "background-color": "#435166", "border-style": "dashed", "border-color": "#b4c1d3", "width": 29, "height": 29, "font-size": 10 }},
      { selector: "edge", style: {
        "width": "data(width)", "line-color": "#496887", "target-arrow-color": "#496887", "target-arrow-shape": "triangle",
        "curve-style": "bezier", "arrow-scale": 0.9, "opacity": 0.88
      }},
      { selector: "edge[relationship = 'vasp_receipt']", style: { "line-color": "#37cf93", "target-arrow-color": "#37cf93" }},
      { selector: "edge[relationship = 'bridge_interaction']", style: { "line-color": "#5c9dff", "target-arrow-color": "#5c9dff" }},
      { selector: "edge[frontier]", style: { "line-style": "dashed", "line-color": "#7c8ea8", "target-arrow-color": "#7c8ea8", "width": 1.5 }},
      { selector: ".path-active", style: { "opacity": 1, "z-index": 30, "line-color": "#65e8ff", "target-arrow-color": "#65e8ff", "border-color": "#65e8ff", "border-width": 4 }},
      { selector: ".dimmed", style: { "opacity": 0.16 }},
      { selector: ":selected", style: { "border-color": "#ffffff", "border-width": 4, "line-color": "#ffffff", "target-arrow-color": "#ffffff" }}
    ];
  }

  function buildElements(result) {
    const graph = result.graph || { edges: [], frontiers: [] };
    const nodes = (result.nodes || []).map(node => ({
      group: "nodes",
      data: { ...node, id: node.address, label: nodeLabel(node), kind: "node" }
    }));
    const edges = (graph.edges || []).map(edge => ({
      group: "edges",
      data: { ...edge, source: edge.source, target: edge.target, width: amountWidth(edge.attributed_amount || edge.transfer_amount), kind: "edge" }
    }));
    const frontierNodes = [];
    const frontierEdges = [];
    (graph.frontiers || []).forEach((frontier, index) => {
      const id = `frontier:${index}:${frontier.address}`;
      frontierNodes.push({ group: "nodes", data: { ...frontier, id, label: "Trace frontier", kind: "frontier", frontier: true, role: "frontier" } });
      frontierEdges.push({ group: "edges", data: { id: `frontier-edge:${index}:${frontier.address}`, source: frontier.address, target: id, frontier: true, kind: "frontier-edge", width: 1.5 } });
    });
    return [...nodes, ...edges, ...frontierNodes, ...frontierEdges];
  }

  function render(result, nextCallbacks = {}) {
    trace = result;
    callbacks = nextCallbacks;
    const container = document.getElementById("traceGraph");
    if (!container || !window.cytoscape) return false;
    if (cy) cy.destroy();
    cy = cytoscape({
      container,
      elements: buildElements(result),
      style: style(),
      layout: { name: "breadthfirst", directed: true, roots: `#${CSS.escape(result.graph?.root_address || "")}`, spacingFactor: 1.35, padding: 54, animate: false },
      wheelSensitivity: 0.18,
      minZoom: 0.25,
      maxZoom: 2.5
    });
    cy.on("tap", "node", event => callbacks.onSelect?.({ type: event.target.data("kind"), data: event.target.data() }));
    cy.on("tap", "edge", event => callbacks.onSelect?.({ type: event.target.data("kind"), data: event.target.data() }));
    cy.on("tap", event => { if (event.target === cy) callbacks.onClear?.(); });
    requestAnimationFrame(() => cy.fit(cy.elements(), 54));
    return true;
  }

  function highlightCandidate(candidate) {
    if (!cy || !trace?.graph?.paths) return;
    const path = trace.graph.paths.find(item => item.candidate_label_id === candidate.label_id && item.candidate_address === candidate.address);
    cy.elements().removeClass("path-active dimmed");
    if (!path) return;
    cy.elements().addClass("dimmed");
    const ids = [...path.node_addresses, ...path.edge_ids].map(id => `#${CSS.escape(id)}`).join(",");
    cy.$(ids).removeClass("dimmed").addClass("path-active");
    cy.fit(cy.$(ids), 70);
  }

  function reset() {
    if (!cy) return;
    cy.elements().removeClass("path-active dimmed");
    cy.fit(cy.elements(), 54);
  }

  function zoom(delta) {
    if (!cy) return;
    cy.zoom({ level: Math.max(0.25, Math.min(2.5, cy.zoom() + delta)), renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 } });
  }

  window.TraceGraph = { render, highlightCandidate, reset, zoom };
})();
