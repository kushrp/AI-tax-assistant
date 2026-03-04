const state = {
  returnId: null,
  returnYear: 2025,
  documents: [],
  facts: [],
};
const API_BASE_URL = String(window.TAX_ASSISTANT_API_BASE_URL || "").replace(/\/$/, "");

const refs = {
  activeReturn: document.querySelector("#active-return"),
  readinessPill: document.querySelector("#readiness-pill"),
  documentList: document.querySelector("#document-list"),
  factSelect: document.querySelector("#fact-select"),
  factsOutput: document.querySelector("#facts-output"),
  issuesOutput: document.querySelector("#issues-output"),
  optimizeOutput: document.querySelector("#optimize-output"),
  exportOutput: document.querySelector("#export-output"),
  activityOutput: document.querySelector("#activity-output"),
};

function logActivity(message, data = null) {
  const lines = [];
  const now = new Date().toLocaleTimeString();
  lines.push(`[${now}] ${message}`);
  if (data) {
    lines.push(JSON.stringify(data, null, 2));
  }

  refs.activityOutput.textContent = `${lines.join("\n")}\n\n${refs.activityOutput.textContent}`.trim();
}

function ensureReturn() {
  if (!state.returnId) {
    throw new Error("Create a return first.");
  }
}

async function apiJson(path, options = {}) {
  const response = await fetch(apiPath(path), {
    headers: {
      ...(options.headers || {}),
    },
    ...options,
  });

  const contentType = response.headers.get("content-type") || "";
  const body = contentType.includes("application/json") ? await response.json() : await response.text();

  if (!response.ok) {
    const detail = body?.detail ?? body;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail, null, 2));
  }

  return body;
}

function apiPath(path) {
  if (!API_BASE_URL) {
    return path;
  }
  if (path.startsWith("http://") || path.startsWith("https://")) {
    return path;
  }
  return `${API_BASE_URL}${path}`;
}

function setReturnId(returnId, taxYear) {
  state.returnId = returnId;
  state.returnYear = taxYear;
  state.documents = [];
  state.facts = [];
  refs.activeReturn.textContent = returnId;

  document.querySelector('#upload-form input[name="tax_year"]').value = String(taxYear);
  refs.readinessPill.textContent = "In progress";
  refs.readinessPill.className = "readiness-bad";
  refs.factsOutput.textContent = "";
  refs.issuesOutput.textContent = "";
  refs.optimizeOutput.textContent = "";
  refs.exportOutput.textContent = "";
  renderDocuments();
}

function renderDocuments() {
  refs.documentList.innerHTML = "";
  if (state.documents.length === 0) {
    const li = document.createElement("li");
    li.textContent = "No documents uploaded yet.";
    refs.documentList.appendChild(li);
    return;
  }

  for (const doc of state.documents) {
    const li = document.createElement("li");

    const label = document.createElement("span");
    const extractionStatus = doc.latest_extraction_status || "not_extracted";
    label.textContent =
      `${doc.file_name} [${doc.doc_type}] (${doc.source_type}) | ` +
      `facts=${doc.facts_extracted} | extraction=${extractionStatus}`;

    const extractBtn = document.createElement("button");
    extractBtn.textContent = "Extract";
    extractBtn.type = "button";
    extractBtn.addEventListener("click", async () => {
      await runExtraction(doc.id);
    });

    li.append(label, extractBtn);
    refs.documentList.appendChild(li);
  }
}

function renderFacts(facts) {
  state.facts = facts;
  refs.factsOutput.textContent = JSON.stringify(facts, null, 2);

  refs.factSelect.innerHTML = "";
  for (const fact of facts) {
    const opt = document.createElement("option");
    opt.value = fact.id;
    opt.textContent = `${fact.form_line_ref} = ${fact.value}`;
    refs.factSelect.appendChild(opt);
  }
}

async function refreshReadiness() {
  ensureReturn();
  const readiness = await apiJson(`/v1/returns/${state.returnId}/readiness`);
  refs.readinessPill.textContent = readiness.ready_to_file ? "Ready" : "Blocked";
  refs.readinessPill.className = readiness.ready_to_file ? "readiness-good" : "readiness-bad";
  logActivity("Readiness loaded", readiness);
  return readiness;
}

async function loadDocuments() {
  ensureReturn();
  const docs = await apiJson(`/v1/returns/${state.returnId}/documents`);
  state.documents = docs;
  renderDocuments();
  logActivity("Documents loaded", { count: docs.length });
  return docs;
}

async function runExtraction(documentId) {
  const result = await apiJson(`/v1/documents/${documentId}/extract`, {
    method: "POST",
  });
  logActivity(`Extraction finished for ${documentId}`, result);
  await loadDocuments();
  await refreshReadiness().catch(() => null);
  return result;
}

document.querySelector("#create-return-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = new FormData(event.currentTarget);

  try {
    const payload = {
      tax_year: Number(form.get("tax_year")),
      primary_state: String(form.get("primary_state") || "").toUpperCase(),
      filing_status: String(form.get("filing_status") || "mfj"),
    };

    const created = await apiJson("/v1/returns", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    setReturnId(created.id, created.tax_year);
    logActivity("Return created", created);
    await loadDocuments();
  } catch (error) {
    logActivity("Create return failed", { error: error.message });
  }
});

document.querySelector("#upload-form").addEventListener("submit", async (event) => {
  event.preventDefault();

  try {
    ensureReturn();

    const form = new FormData(event.currentTarget);
    const docYear = Number(form.get("tax_year") || state.returnYear);

    const payload = new FormData();
    payload.append("return_id", state.returnId);
    payload.append("tax_year", String(docYear));
    payload.append("owner", String(form.get("owner") || "taxpayer"));
    payload.append("source_type", String(form.get("source_type") || "csv"));
    payload.append("file", form.get("file"));

    const uploaded = await apiJson("/v1/documents/upload", {
      method: "POST",
      body: payload,
    });

    logActivity("Document uploaded", uploaded);
    await loadDocuments();
    event.currentTarget.reset();
    document.querySelector('#upload-form input[name="tax_year"]').value = String(state.returnYear);
  } catch (error) {
    logActivity("Upload failed", { error: error.message });
  }
});

document.querySelector("#load-docs-btn").addEventListener("click", async () => {
  try {
    await loadDocuments();
  } catch (error) {
    logActivity("Load docs failed", { error: error.message });
  }
});

document.querySelector("#extract-all-btn").addEventListener("click", async () => {
  try {
    ensureReturn();
    const result = await apiJson(`/v1/returns/${state.returnId}/extract-all`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ force: false }),
    });
    logActivity("Extract all finished", result);
    await loadDocuments();
    await refreshReadiness();
  } catch (error) {
    logActivity("Extract all failed", { error: error.message });
  }
});

document.querySelector("#load-facts-btn").addEventListener("click", async () => {
  try {
    ensureReturn();
    const facts = await apiJson(`/v1/returns/${state.returnId}/facts`);
    renderFacts(facts);
    logActivity("Facts loaded", { count: facts.length });
  } catch (error) {
    logActivity("Load facts failed", { error: error.message });
  }
});

document.querySelector("#load-issues-btn").addEventListener("click", async () => {
  try {
    ensureReturn();
    const issues = await apiJson(`/v1/returns/${state.returnId}/issues`);
    refs.issuesOutput.textContent = JSON.stringify(issues, null, 2);
    logActivity("Issues loaded", { count: issues.length });
    await refreshReadiness();
  } catch (error) {
    logActivity("Load issues failed", { error: error.message });
  }
});

document.querySelector("#load-readiness-btn").addEventListener("click", async () => {
  try {
    await refreshReadiness();
  } catch (error) {
    logActivity("Readiness failed", { error: error.message });
  }
});

document.querySelector("#optimize-btn").addEventListener("click", async () => {
  try {
    ensureReturn();
    const result = await apiJson(`/v1/returns/${state.returnId}/optimize`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ include_itemized: true }),
    });
    refs.optimizeOutput.textContent = JSON.stringify(result, null, 2);
    logActivity("Optimization complete", { scenarios: result.scenarios?.length || 0 });
  } catch (error) {
    logActivity("Optimize failed", { error: error.message });
  }
});

document.querySelector("#attest-form").addEventListener("submit", async (event) => {
  event.preventDefault();

  try {
    ensureReturn();
    const form = new FormData(event.currentTarget);
    const payload = {
      fact_id: String(form.get("fact_id") || ""),
      rationale: String(form.get("rationale") || ""),
    };
    const actorId = String(form.get("actor_id") || "taxpayer-1");
    const role = String(form.get("role") || "taxpayer");

    const result = await apiJson(`/v1/returns/${state.returnId}/attest`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "x-user-id": actorId,
        "x-role": role,
      },
      body: JSON.stringify(payload),
    });

    logActivity("Attestation recorded", result);
    await refreshReadiness();
  } catch (error) {
    logActivity("Attestation failed", { error: error.message });
  }
});

document.querySelector("#approve-form").addEventListener("submit", async (event) => {
  event.preventDefault();

  try {
    ensureReturn();
    const form = new FormData(event.currentTarget);
    const payload = {
      decision: String(form.get("decision") || "approved"),
      notes: String(form.get("notes") || ""),
    };
    const actorId = String(form.get("actor_id") || "taxpayer-1");
    const role = String(form.get("role") || "taxpayer");

    const result = await apiJson(`/v1/returns/${state.returnId}/approve`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "x-user-id": actorId,
        "x-role": role,
      },
      body: JSON.stringify(payload),
    });

    logActivity("Approval recorded", result);
  } catch (error) {
    logActivity("Approval failed", { error: error.message });
  }
});

document.querySelector("#export-btn").addEventListener("click", async () => {
  try {
    ensureReturn();
    const packet = await apiJson(`/v1/returns/${state.returnId}/export/freetaxusa`);
    refs.exportOutput.textContent = JSON.stringify(packet, null, 2);
    logActivity("Export successful", {
      fields: packet.fields?.length || 0,
      unresolved_question_queue: packet.unresolved_question_queue?.length || 0,
    });
    await refreshReadiness();
  } catch (error) {
    refs.exportOutput.textContent = `Export blocked:\n${error.message}`;
    logActivity("Export blocked", { error: error.message });
    await refreshReadiness().catch(() => null);
  }
});

renderDocuments();
