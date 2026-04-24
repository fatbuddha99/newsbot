const state = {
  focusMode: true,
  query: "",
};

const terminalLog = document.getElementById("terminalLog");
const headlinesList = document.getElementById("headlinesList");
const analysisOutput = document.getElementById("analysisOutput");
const queryInput = document.getElementById("queryInput");
const modeValue = document.getElementById("modeValue");
const storyCount = document.getElementById("storyCount");
const refreshStatus = document.getElementById("refreshStatus");
const focusToggle = document.getElementById("focusToggle");
const refreshButton = document.getElementById("refreshButton");
const commandForm = document.getElementById("commandForm");
const AUTO_REFRESH_MS = 15 * 60 * 1000;

function logLine(text, tone = "neutral") {
  const line = document.createElement("div");
  line.className = `terminal-line terminal-line--${tone}`;
  line.textContent = text;
  terminalLog.prepend(line);
}

function renderHeadlines(items) {
  headlinesList.innerHTML = "";

  if (!items.length) {
    const empty = document.createElement("div");
    empty.className = "headline-card headline-card--empty";
    empty.textContent = "No stories matched the current scan.";
    headlinesList.append(empty);
    return;
  }

  items.forEach((item, index) => {
    const card = document.createElement("article");
    card.className = "headline-card";

    const scoreClass = item.signalScore > 0 ? "score--high" : item.signalScore < 0 ? "score--low" : "score--flat";
    const matches = Array.isArray(item.scoreMatches) && item.scoreMatches.length
      ? item.scoreMatches.join(" | ")
      : "No matched heuristics";

    card.innerHTML = `
      <div class="headline-top">
        <span class="headline-rank">${String(index + 1).padStart(2, "0")}</span>
        <span class="headline-source">${item.source}</span>
        <span class="headline-score ${scoreClass}">SIG ${item.signalScore}</span>
      </div>
      <a class="headline-title" href="${item.link}" target="_blank" rel="noreferrer">${item.title}</a>
      <div class="headline-meta">
        <span>${item.pubDate || "No timestamp"}</span>
        <span>${matches}</span>
      </div>
    `;

    headlinesList.append(card);
  });
}

function renderAnalysis(analysis) {
  if (!analysis) {
    analysisOutput.textContent = "No analysis returned.";
    return;
  }

  if (analysis.ok) {
    analysisOutput.textContent = analysis.text;
    return;
  }

  analysisOutput.textContent = analysis.error || "Analysis unavailable.";
}

function syncModeUi() {
  modeValue.textContent = state.focusMode ? "FOCUS" : "FULL";
  focusToggle.textContent = `Focus: ${state.focusMode ? "ON" : "OFF"}`;
  refreshStatus.textContent = "Every 15 min";
}

async function runScan() {
  const params = new URLSearchParams({
    focus: state.focusMode ? "1" : "0",
    analysis: "1",
  });

  if (state.query) {
    params.set("query", state.query);
  }

  try {
    const response = await fetch(`/api/scan?${params.toString()}`);
    if (!response.ok) {
      throw new Error(`Scan failed with status ${response.status}`);
    }

    const data = await response.json();
    renderHeadlines(data.items || []);
    renderAnalysis(data.analysis);
    storyCount.textContent = `${data.shownItems || 0} stories`;

    const errorCount = Array.isArray(data.sourceErrors) ? data.sourceErrors.length : 0;
    logLine(`Scan complete. ${data.totalItems || 0} scored items, ${errorCount} source errors.`, errorCount ? "warn" : "success");

    if (errorCount) {
      data.sourceErrors.forEach((sourceError) => {
        logLine(`[${sourceError.source}] ${sourceError.error}`, "warn");
      });
    }

    if (data.analysis && data.analysis.error && !data.analysis.ok) {
      logLine(`AI analysis unavailable: ${data.analysis.error}`, "warn");
    }
  } catch (error) {
    renderHeadlines([]);
    renderAnalysis({ error: String(error) });
    storyCount.textContent = "0 stories";
    logLine(`Terminal error: ${error}`, "error");
  }
}

commandForm.addEventListener("submit", (event) => {
  event.preventDefault();
  state.query = queryInput.value.trim();
  runScan();
});

focusToggle.addEventListener("click", () => {
  state.focusMode = !state.focusMode;
  syncModeUi();
  logLine(`Focus mode ${state.focusMode ? "enabled" : "disabled"}.`, "info");
  runScan();
});

refreshButton.addEventListener("click", () => {
  logLine("Manual refresh requested.", "info");
  runScan();
});

syncModeUi();
runScan();
window.setInterval(() => {
  logLine("Auto refresh triggered (15 min cadence).", "info");
  runScan();
}, AUTO_REFRESH_MS);
