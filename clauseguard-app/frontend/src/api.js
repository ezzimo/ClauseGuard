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

async function uploadContract(file, context) {
  const headers = await authHeaders();
  const formData = new FormData();
  formData.append("file", file);
  formData.append("contract_type", context.contract_type || "");
  formData.append("cote", context.cote || "");
  formData.append("montant", context.montant || "");
  formData.append("parties", JSON.stringify(context.parties || []));
  const res = await fetch(`${API_URL}/api/contracts/upload`, {
    method: "POST",
    headers,
    body: formData,
  });
  if (!res.ok) throw new Error("Échec de l'envoi du contrat");
  return res.json();
}

async function analyzeContract(contractId) {
  const headers = await authHeaders();
  const res = await fetch(`${API_URL}/api/contracts/${contractId}/analyze`, {
    method: "POST",
    headers,
  });
  if (!res.ok) throw new Error("Échec de l'analyse");
  return res.json();
}

async function getContract(contractId) {
  const headers = await authHeaders();
  const res = await fetch(`${API_URL}/api/contracts/${contractId}`, { headers });
  if (!res.ok) throw new Error("Contrat introuvable");
  return res.json();
}

async function submitDecisions(contractId, decisions) {
  const headers = await authHeaders();
  const res = await fetch(`${API_URL}/api/contracts/${contractId}/decisions`, {
    method: "POST",
    headers: { ...headers, "Content-Type": "application/json" },
    body: JSON.stringify({ decisions }),
  });
  if (!res.ok) throw new Error("Échec de l'enregistrement des décisions");
  return res.json();
}

async function generateReport(contractId) {
  const headers = await authHeaders();
  const res = await fetch(`${API_URL}/api/contracts/${contractId}/report`, {
    method: "POST",
    headers,
  });
  if (!res.ok) throw new Error("Échec de la génération du rapport");
  return res.json();
}

async function getReport(contractId) {
  const headers = await authHeaders();
  const res = await fetch(`${API_URL}/api/contracts/${contractId}/report`, { headers });
  if (!res.ok) throw new Error("Rapport introuvable");
  return res.json();
}

export {
  API_URL,
  login,
  uploadContract,
  analyzeContract,
  getContract,
  submitDecisions,
  generateReport,
  getReport,
};
