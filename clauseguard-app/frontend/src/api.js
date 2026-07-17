const API_URL = "";

let token = localStorage.getItem("cg_token") || "";

async function login() {
  const res = await fetch(`${API_URL}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: "clauseguard", password: "clauseguard" }),
  });
  if (!res.ok) throw new Error("Échec de l'authentification");
  const data = await res.json();
  token = data.access_token;
  localStorage.setItem("cg_token", token);
}

async function authHeaders() {
  if (!token) await login();
  return { Authorization: `Bearer ${token}` };
}

async function fetchWithAuth(url, options = {}) {
  const headers = await authHeaders();
  const res = await fetch(url, {
    ...options,
    headers: { ...headers, ...options.headers },
  });

  if (res.status === 401) {
    await login();
    const freshHeaders = await authHeaders();
    return fetch(url, {
      ...options,
      headers: { ...freshHeaders, ...options.headers },
    });
  }

  return res;
}

async function listContracts() {
  const res = await fetchWithAuth(`${API_URL}/api/contracts`);
  if (!res.ok) throw new Error("Échec du chargement des contrats");
  return res.json();
}

async function uploadContract(file, context) {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("contract_type", context.contract_type || "");
  formData.append("cote", context.cote || "");
  formData.append("montant", context.montant || "");
  formData.append("parties", JSON.stringify(context.parties || []));
  const res = await fetchWithAuth(`${API_URL}/api/contracts/upload`, {
    method: "POST",
    body: formData,
  });
  if (!res.ok) throw new Error("Échec de l'envoi du contrat");
  return res.json();
}

async function analyzeContract(contractId) {
  const res = await fetchWithAuth(`${API_URL}/api/contracts/${contractId}/analyze`, {
    method: "POST",
  });
  if (!res.ok) throw new Error("Échec de l'analyse");
  return res.json();
}

async function getContract(contractId) {
  const res = await fetchWithAuth(`${API_URL}/api/contracts/${contractId}`);
  if (!res.ok) throw new Error("Contrat introuvable");
  return res.json();
}

async function submitDecisions(contractId, decisions) {
  const res = await fetchWithAuth(`${API_URL}/api/contracts/${contractId}/decisions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ decisions }),
  });
  if (!res.ok) throw new Error("Échec de l'enregistrement des décisions");
  return res.json();
}

async function generateReport(contractId) {
  const res = await fetchWithAuth(`${API_URL}/api/contracts/${contractId}/report`, {
    method: "POST",
  });
  if (!res.ok) throw new Error("Échec de la génération du rapport");
  return res.json();
}

async function getReport(contractId) {
  const res = await fetchWithAuth(`${API_URL}/api/contracts/${contractId}/report`);
  if (!res.ok) throw new Error("Rapport introuvable");
  return res.json();
}

async function recoverReport(contractId) {
  const res = await fetchWithAuth(`${API_URL}/api/contracts/${contractId}/report?recover=true`, {
    method: "POST",
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || "Échec de la récupération du rapport");
  }
  return res.json();
}

async function downloadReportPdf(contractId) {
  const res = await fetchWithAuth(`${API_URL}/api/contracts/${contractId}/report/pdf`);
  if (!res.ok) throw new Error("Échec du téléchargement du PDF");
  const blob = await res.blob();
  const disposition = res.headers.get("Content-Disposition") || "";
  const match = disposition.match(/filename="?([^"]+)"?/);
  const filename = match ? match[1] : `ClauseGuard_Rapport_${contractId.slice(0, 8)}.pdf`;
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

async function getActivity(limit = 15) {
  const res = await fetchWithAuth(`${API_URL}/api/activity?limit=${limit}`);
  if (!res.ok) throw new Error("Échec du chargement de l'activité");
  return res.json();
}

export {
  API_URL,
  login,
  listContracts,
  uploadContract,
  analyzeContract,
  getContract,
  submitDecisions,
  generateReport,
  getReport,
  recoverReport,
  downloadReportPdf,
  getActivity,
};
