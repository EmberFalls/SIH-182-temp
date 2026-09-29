/**
 * VASP Trace — Landing Page Interactive Engine
 * Zeabur-inspired 3D Topographic Binary Wave, Text Scrambler & Forensics Sandbox
 */

(function () {
  "use strict";

  // ==========================================
  // 1. 3D Topographic Binary Wave Canvas
  // ==========================================
  function initBinaryWaveCanvas() {
    const canvas = document.getElementById("binaryWaveCanvas");
    if (!canvas) return;

    const ctx = canvas.getContext("2d", { alpha: true });
    if (!ctx) return;

    const FONT_SIZE = 11;
    const CELL_WIDTH = 9.5;
    const CELL_HEIGHT = 12.5;
    const FONT_SPEC = `500 ${FONT_SIZE}px "IBM Plex Mono", "Geist Mono", monospace`;

    let width = 0;
    let height = 0;
    let cols = 0;
    let rows = 0;
    let dpr = 1;

    let grid = [];
    const mouse = { x: -9999, y: -9999, targetX: -9999, targetY: -9999 };

    function initGrid(newCols, newRows) {
      const newGrid = [];
      for (let r = 0; r < newRows; r++) {
        const row = [];
        for (let c = 0; c < newCols; c++) {
          row.push((grid[r] && grid[r][c]) ? grid[r][c] : {
            val: Math.random() > 0.5 ? "1" : "0",
            lastFlip: 0,
          });
        }
        newGrid.push(row);
      }
      grid = newGrid;
      cols = newCols;
      rows = newRows;
    }

    function handleResize() {
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      width = window.innerWidth;
      height = window.innerHeight;

      canvas.width = Math.floor(width * dpr);
      canvas.height = Math.floor(height * dpr);
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;

      initGrid(Math.ceil(width / CELL_WIDTH) + 2, Math.ceil(height / CELL_HEIGHT) + 2);
    }

    handleResize();

    let animationFrameId = 0;
    const startTime = performance.now();

    function render(now) {
      const t = (now - startTime) * 0.001;

      mouse.x += (mouse.targetX - mouse.x) * 0.12;
      mouse.y += (mouse.targetY - mouse.y) * 0.12;

      ctx.save();
      ctx.scale(dpr, dpr);
      ctx.clearRect(0, 0, width, height);

      ctx.font = FONT_SPEC;
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";

      const hoverRadius = 140;
      const hoverRadiusSq = hoverRadius * hoverRadius;

      for (let r = 0; r < rows; r++) {
        const py = r * CELL_HEIGHT + CELL_HEIGHT * 0.5;
        const ny = (r / rows) * 2 - 1;

        for (let c = 0; c < cols; c++) {
          const px = c * CELL_WIDTH + CELL_WIDTH * 0.5;
          const nx = (c / cols) * 2 - 1;

          // Multi-harmonic 3D wave topography
          const w1 = Math.sin(nx * 3.2 - ny * 2.1 + t * 0.75);
          const w2 = Math.cos(nx * 2.0 + ny * 3.5 - t * 0.55);
          const rx = nx - 0.45;
          const ry = ny + 0.35;
          const distOrigin = Math.sqrt(rx * rx + ry * ry);
          const w3 = Math.sin(distOrigin * 6.5 - t * 1.1);

          let elevation = w1 * 0.45 + w2 * 0.35 + w3 * 0.20;

          // Mouse deflection lens
          const dx = px - mouse.x;
          const dy = py - mouse.y;
          const dsq = dx * dx + dy * dy;
          let hoverFactor = 0;

          if (dsq < hoverRadiusSq) {
            hoverFactor = 1 - Math.sqrt(dsq) / hoverRadius;
            elevation += hoverFactor * 0.75;
          }

          const normElev = Math.max(0, Math.min(1, (elevation + 0.85) / 1.7));
          const ridge = Math.pow(normElev, 2.2);

          // Dynamic 0/1 mutation on active ridges
          const cell = grid[r][c];
          if (cell) {
            const flipProbability = 0.003 + ridge * 0.06 + hoverFactor * 0.25;

            if (Math.random() < flipProbability && now - cell.lastFlip > 180) {
              if (ridge > 0.65 && Math.random() < 0.4) {
                cell.val = Math.sin(c * 0.4 + t * 2.5) > 0 ? "1" : "0";
              } else {
                cell.val = cell.val === "1" ? "0" : "1";
              }
              cell.lastFlip = now;
            }
          }

          // Elevation color grading
          let fillStyle;
          if (hoverFactor > 0.05) {
            const a = Math.min(1, 0.25 + hoverFactor * 0.75);
            fillStyle = `rgba(243, 232, 255, ${a.toFixed(2)})`;
          } else if (ridge > 0.72) {
            const a = Math.min(0.96, 0.6 + (ridge - 0.72) * 1.4);
            fillStyle = `rgba(240, 230, 255, ${a.toFixed(2)})`;
          } else if (ridge > 0.45) {
            const a = 0.22 + (ridge - 0.45) * 1.2;
            fillStyle = `rgba(168, 85, 247, ${a.toFixed(2)})`;
          } else if (ridge > 0.22) {
            const a = 0.08 + (ridge - 0.22) * 0.6;
            fillStyle = `rgba(129, 140, 248, ${a.toFixed(2)})`;
          } else {
            fillStyle = "rgba(148, 163, 184, 0.065)";
          }

          ctx.fillStyle = fillStyle;
          ctx.fillText((cell ? cell.val : "0"), px, py);
        }
      }

      ctx.restore();
      animationFrameId = requestAnimationFrame(render);
    }

    animationFrameId = requestAnimationFrame(render);

    const onMouseMove = (e) => {
      const rect = canvas.getBoundingClientRect();
      mouse.targetX = e.clientX - rect.left;
      mouse.targetY = e.clientY - rect.top;
    };

    const onMouseLeave = () => {
      mouse.targetX = -9999;
      mouse.targetY = -9999;
    };

    window.addEventListener("mousemove", onMouseMove, { passive: true });
    window.addEventListener("mouseleave", onMouseLeave, { passive: true });
    window.addEventListener("resize", handleResize, { passive: true });
  }

  // ==========================================
  // 2. Scrambler Word Animation
  // ==========================================
  function initScrambler() {
    const targetElement = document.getElementById("scrambleWord");
    if (!targetElement) return;

    const WORDS = [
      "disputed flows",
      "VASP attribution",
      "cross-chain hops",
      "evidence manifests",
      "sahyog drafts",
      "custodial endpoints"
    ];
    const SCRAMBLE_CHARS = "010101ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz!@#$%^&*";

    let wordIndex = 0;
    let scrambleTimer = null;

    targetElement.textContent = WORDS[0];

    setInterval(() => {
      wordIndex = (wordIndex + 1) % WORDS.length;
      const targetWord = WORDS[wordIndex];
      let frame = 0;
      const maxFrames = 12;

      if (scrambleTimer) clearInterval(scrambleTimer);

      scrambleTimer = setInterval(() => {
        frame++;
        if (frame >= maxFrames) {
          targetElement.textContent = targetWord;
          targetElement.style.fontFamily = "'IBM Plex Sans', sans-serif";
          targetElement.style.color = "#ffffff";
          if (scrambleTimer) clearInterval(scrambleTimer);
        } else {
          targetElement.style.fontFamily = "'IBM Plex Mono', monospace";
          targetElement.style.color = "#c084fc";
          const scrambled = targetWord
            .split("")
            .map((char, i) => {
              if (char === " ") return " ";
              if (frame > (i / targetWord.length) * maxFrames) return char;
              return SCRAMBLE_CHARS[Math.floor(Math.random() * SCRAMBLE_CHARS.length)];
            })
            .join("");
          targetElement.textContent = scrambled;
        }
      }, 45);
    }, 3600);
  }

  // ==========================================
  // 3. Forensics Simulation Sandbox
  // ==========================================
  const SANDBOX_SCENARIOS = [
    {
      id: "s1",
      label: "Live Binance USDT Inflow",
      badge: "CONFIRMED_ATTRIBUTED",
      color: "#34d399",
      metrics: {
        "Attributed Flow": "125,000 USDT",
        "Trace Hops": "2 confirmed",
        "Target VASP": "Binance Custody",
        "Tamper Proof": "0x9a8f...4e12"
      },
      meters: [
        { name: "Evidence Confidence", value: 0.98 },
        { name: "Provider Provenance Integrity", value: 1.0 },
        { name: "Attribution Defensibility", value: 0.92 },
        { name: "LE Action Readiness", value: 0.95 }
      ],
      note: "Exact ERC-20 transfer event verified with confirmed on-chain receipt log. Candidate matches verified VASP label registry entry with reviewed custody proof."
    },
    {
      id: "s2",
      label: "Multi-Hop Layering Evasion",
      badge: "ANOMALY_FLAGGED",
      color: "#fbbf24",
      metrics: {
        "Disputed Amount": "45,200 USDT",
        "Chain Depth": "4 hops",
        "Peeling Clusters": "3 detected",
        "Unresolved Trace": "12.4%"
      },
      meters: [
        { name: "Peeling Velocity Score", value: 0.84 },
        { name: "Intermediary Split Index", value: 0.76 },
        { name: "Hop Frontier Coverage", value: 0.80 },
        { name: "Retained Balance Gaps", value: 0.68 }
      ],
      note: "Peeling chain detected with automated micro-splitting. Intermediate addresses flagged as ephemeral pass-through wallets with low retention time."
    },
    {
      id: "s3",
      label: "Wormhole Bridge Route",
      badge: "BRIDGE_RESOLVED",
      color: "#38bdf8",
      metrics: {
        "Bridge Protocol": "Wormhole EVM",
        "Sequence ID": "0x7b23...918a",
        "Source Origin": "Ethereum Mainnet",
        "Target Network": "Polygon PoS"
      },
      meters: [
        { name: "Sequence Matching Score", value: 1.0 },
        { name: "VAA Log Extraction", value: 0.96 },
        { name: "Cross-Chain Continuity", value: 0.91 },
        { name: "Routing Feasibility", value: 0.88 }
      ],
      note: "Deterministic cross-chain link resolved using exact matching VAA protocol message identifier. Eliminates heuristic false-positive bridge attribution."
    },
    {
      id: "s4",
      label: "High-Risk Sanction Inflow",
      badge: "SANCTIONS_ALERT",
      color: "#f87171",
      metrics: {
        "Inflow Volume": "310,000 USDT",
        "Sanction Source": "OFAC SDN List",
        "Direct Counterparty": "1 hop",
        "Requisition Code": "91 CrPC / Freeze"
      },
      meters: [
        { name: "Sanctions Exposure", value: 0.99 },
        { name: "Risk Severity Level", value: 0.94 },
        { name: "Attribution Certainty", value: 1.0 },
        { name: "Immediate Escalation", value: 0.97 }
      ],
      note: "Direct counterparty identified on OFAC SDN digital currency list. Prepared court-admissible evidentiary package with immutable hash for immediate freezing notice."
    }
  ];

  function renderSandboxScenario(index) {
    const scenario = SANDBOX_SCENARIOS[index];
    if (!scenario) return;

    // Update Tab buttons
    const tabBtns = document.querySelectorAll(".sandbox-tab-btn");
    tabBtns.forEach((btn, i) => {
      if (i === index) {
        btn.classList.add("active");
      } else {
        btn.classList.remove("active");
      }
    });

    // Update Metrics
    const metricsContainer = document.getElementById("sandboxMetrics");
    if (metricsContainer) {
      metricsContainer.innerHTML = Object.entries(scenario.metrics)
        .map(([k, v]) => `
          <div>
            <div class="sandbox-metric-key">${k}</div>
            <div class="sandbox-metric-val">${v}</div>
          </div>
        `)
        .join("");
    }

    // Update Meters
    const metersContainer = document.getElementById("sandboxMeters");
    if (metersContainer) {
      metersContainer.innerHTML = scenario.meters
        .map(m => `
          <div class="sandbox-meter-card">
            <div class="sandbox-meter-header">
              <span class="sandbox-meter-name">${m.name}</span>
              <span class="sandbox-meter-pct">${Math.round(m.value * 100)}%</span>
            </div>
            <div class="sandbox-bar-track">
              <div class="sandbox-bar-fill" style="width: ${Math.round(m.value * 100)}%; background-color: ${scenario.color};"></div>
            </div>
          </div>
        `)
        .join("");
    }

    // Update Note
    const noteContainer = document.getElementById("sandboxNote");
    if (noteContainer) {
      noteContainer.innerHTML = `
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style="flex-shrink: 0; margin-top: 1px;">
          <circle cx="12" cy="12" r="10"></circle>
          <line x1="12" y1="16" x2="12" y2="12"></line>
          <line x1="12" y1="8" x2="12.01" y2="8"></line>
        </svg>
        <div><strong>Evidentiary Finding:</strong> ${scenario.note}</div>
      `;
    }
  }

  function initSandbox() {
    const tabsContainer = document.getElementById("sandboxTabs");
    if (!tabsContainer) return;

    tabsContainer.innerHTML = SANDBOX_SCENARIOS.map((s, i) => `
      <button class="sandbox-tab-btn ${i === 0 ? "active" : ""}" data-index="${i}">
        <div class="sandbox-dot" style="background-color: ${s.color}"></div>
        <span>${s.label}</span>
        <span class="sandbox-pill" style="color: ${s.color}">${s.badge}</span>
      </button>
    `).join("");

    tabsContainer.addEventListener("click", (e) => {
      const btn = e.target.closest(".sandbox-tab-btn");
      if (!btn) return;
      const index = parseInt(btn.getAttribute("data-index"), 10);
      renderSandboxScenario(index);
    });

    renderSandboxScenario(0);
  }

  // ==========================================
  // 4. Workbench View Switcher & Agent Input
  // ==========================================
  window.launchWorkbench = function (initialAddress) {
    const landingView = document.getElementById("landingView");
    const workbenchView = document.getElementById("workbenchView");
    const navLandingToggle = document.getElementById("navLandingToggle");

    if (landingView && workbenchView) {
      landingView.style.display = "none";
      workbenchView.style.display = "block";
      window.scrollTo({ top: 0, behavior: "smooth" });

      if (navLandingToggle) {
        navLandingToggle.style.display = "inline-flex";
      }

      setTimeout(() => {
        window.dispatchEvent(new Event("resize"));
      }, 50);

      if (initialAddress && typeof initialAddress === "string") {
        const v2Dialog = document.getElementById("v2CaseDialog");
        const v2Form = document.getElementById("v2CaseForm");
        if (v2Dialog && v2Form) {
          const walletInput = v2Form.querySelector('[name="wallet"]');
          if (walletInput) {
            walletInput.value = initialAddress.trim();
          }
          if (initialAddress.startsWith("T")) {
            const chainSelect = v2Form.querySelector('[name="chain"]');
            if (chainSelect) chainSelect.value = "TRON";
          } else if (initialAddress.startsWith("0x")) {
            const chainSelect = v2Form.querySelector('[name="chain"]');
            if (chainSelect) chainSelect.value = "ETHEREUM";
          }
          v2Dialog.showModal();
        }
      }
    }
  };

  window.showLandingPage = function () {
    const landingView = document.getElementById("landingView");
    const workbenchView = document.getElementById("workbenchView");
    const navLandingToggle = document.getElementById("navLandingToggle");

    if (landingView && workbenchView) {
      workbenchView.style.display = "none";
      landingView.style.display = "block";
      window.scrollTo({ top: 0, behavior: "smooth" });

      setTimeout(() => {
        window.dispatchEvent(new Event("resize"));
      }, 50);

      if (navLandingToggle) {
        navLandingToggle.style.display = "none";
      }
    }
  };

  function initAgentInput() {
    const agentForm = document.getElementById("agentPromptForm");
    const agentInput = document.getElementById("agentPromptInput");
    const uploadBtn = document.getElementById("agentUploadBtn");

    if (agentForm) {
      agentForm.addEventListener("submit", (e) => {
        e.preventDefault();
        const query = agentInput ? agentInput.value.trim() : "";
        window.launchWorkbench(query);
      });
    }

    if (uploadBtn) {
      uploadBtn.addEventListener("click", () => {
        window.launchWorkbench();
        const importDialog = document.getElementById("recordedImportDialog");
        if (importDialog) importDialog.showModal();
      });
    }
  }

  // Initialize all on DOM load
  document.addEventListener("DOMContentLoaded", () => {
    initBinaryWaveCanvas();
    initScrambler();
    initSandbox();
    initAgentInput();
  });
})();
