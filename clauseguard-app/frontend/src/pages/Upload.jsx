import { useState, useRef, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { UploadCloud, FileCheck, Shield, Loader2, X, CheckCircle2 } from "lucide-react";
import { uploadContract, analyzeContract, getContract } from "../api";

const STEPS = [
  { id: "extraction", label: "Extraction" },
  { id: "masking", label: "Masquage PII" },
  { id: "analysis", label: "Analyse IA" },
  { id: "review", label: "Revue humaine" },
  { id: "report", label: "Rapport" },
];

const PROGRESS_STEP_MAP = {
  upload: 0,
  calling_flow: 2,
  parsing: 2,
  done: 2,
};

export default function Upload() {
  const navigate = useNavigate();
  const fileInputRef = useRef(null);
  const [file, setFile] = useState(null);
  const [dragActive, setDragActive] = useState(false);
  const [typeContrat, setTypeContrat] = useState("prestation_services");
  const [cote, setCote] = useState("client");
  const [montant, setMontant] = useState("");
  const [parties, setParties] = useState([]);
  const [partyInput, setPartyInput] = useState("");
  const [uploadResult, setUploadResult] = useState(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [error, setError] = useState("");
  const [elapsed, setElapsed] = useState(0);
  const [progressHint, setProgressHint] = useState("");
  const pollingRef = useRef(null);
  const timerRef = useRef(null);

  const handleDrag = useCallback((e) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === "dragenter" || e.type === "dragover") setDragActive(true);
    else if (e.type === "dragleave") setDragActive(false);
  }, []);

  const handleDrop = useCallback((e) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    if (e.dataTransfer.files?.[0]) setFile(e.dataTransfer.files[0]);
  }, []);

  const handleFileChange = (e) => {
    if (e.target.files?.[0]) setFile(e.target.files[0]);
  };

  const addParty = () => {
    const value = partyInput.trim();
    if (value && !parties.includes(value)) {
      setParties([...parties, value]);
      setPartyInput("");
    }
  };

  const removeParty = (value) => {
    setParties(parties.filter((p) => p !== value));
  };

  const piiStats = uploadResult?.pii_mapping
    ? {
        emails: Object.values(uploadResult.pii_mapping).filter((v) => v.includes("@")).length,
        telephones: Object.keys(uploadResult.pii_mapping).filter((k) => k.startsWith("[PHONE_")).length,
        identifiants: Object.keys(uploadResult.pii_mapping).filter(
          (k) =>
            k.startsWith("[RIB_") ||
            k.startsWith("[IBAN_") ||
            k.startsWith("[ICE_") ||
            k.startsWith("[CIN_") ||
            k.startsWith("[CNSS_") ||
            k.startsWith("[IF_]")
        ).length,
      }
    : null;

  const stopPolling = () => {
    if (pollingRef.current) {
      clearInterval(pollingRef.current);
      pollingRef.current = null;
    }
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
  };

  const startPolling = (contractId) => {
    setElapsed(0);
    setProgressHint("calling_flow");
    timerRef.current = setInterval(() => setElapsed((prev) => prev + 1), 1000);

    const check = async () => {
      try {
        const data = await getContract(contractId);
        setProgressHint(data.progress_hint || "");
        if (data.status === "awaiting_human_review") {
          stopPolling();
          setAnalyzing(false);
          navigate(`/review/${contractId}`);
          return;
        }
        if (["parse_error", "flow_error", "error"].includes(data.status)) {
          stopPolling();
          setAnalyzing(false);
          setError(data.error_message || "L'analyse a échoué. Veuillez réessayer.");
        }
      } catch (err) {
        stopPolling();
        setAnalyzing(false);
        setError(err.message || "Une erreur est survenue.");
      }
    };

    check();
    pollingRef.current = setInterval(check, 4000);

    setTimeout(() => {
      if (pollingRef.current) {
        stopPolling();
        setAnalyzing(false);
        setError("L'analyse a dépassé le délai maximal (12 minutes). Veuillez réessayer.");
      }
    }, 12 * 60 * 1000);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!file) {
      setError("Veuillez sélectionner un fichier.");
      return;
    }
    setError("");
    stopPolling();
    try {
      const uploaded = await uploadContract(file, {
        contract_type: typeContrat,
        cote,
        montant,
        parties,
      });
      setUploadResult(uploaded);
      setAnalyzing(true);
      await analyzeContract(uploaded.contract_id);
      startPolling(uploaded.contract_id);
    } catch (err) {
      setAnalyzing(false);
      setError(err.message || "Une erreur est survenue.");
    }
  };

  const formatElapsed = (seconds) => {
    const m = Math.floor(seconds / 60)
      .toString()
      .padStart(2, "0");
    const s = (seconds % 60).toString().padStart(2, "0");
    return `${m}:${s}`;
  };

  const activeStep = Math.max(
    uploadResult ? 1 : 0,
    PROGRESS_STEP_MAP[progressHint] ?? (analyzing ? 2 : 0)
  );

  return (
    <div>
      <div className="page-header">
        <h1>Téléverser un contrat</h1>
        <p>Déposez votre contrat pour une analyse assistée. Seul le texte masqué est envoyé à l'IA.</p>
      </div>

      {error && <div className="alert alert-error">{error}</div>}

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))",
          gap: "var(--space-6)",
          alignItems: "start",
        }}
      >
        <div className="card">
          <div
            className={`dropzone ${dragActive ? "active" : ""} ${file ? "has-file" : ""}`}
            onDragEnter={handleDrag}
            onDragOver={handleDrag}
            onDragLeave={handleDrag}
            onDrop={handleDrop}
            onClick={() => fileInputRef.current?.click()}
            style={{ marginBottom: 0 }}
          >
            <input
              ref={fileInputRef}
              type="file"
              accept=".pdf,.docx,.txt"
              onChange={handleFileChange}
              hidden
            />
            {file ? (
              <div style={{ display: "flex", alignItems: "center", gap: "var(--space-3)", justifyContent: "center" }}>
                <FileCheck size={32} color="var(--color-success)" />
                <div style={{ textAlign: "left" }}>
                  <strong>{file.name}</strong>
                  <div style={{ color: "var(--color-text-muted)", fontSize: "0.85rem" }}>
                    {(file.size / 1024).toFixed(1)} Ko
                  </div>
                </div>
              </div>
            ) : (
              <div style={{ color: "var(--color-text-muted)" }}>
                <UploadCloud size={40} style={{ marginBottom: "var(--space-2)", color: "var(--color-secondary)" }} />
                <strong style={{ display: "block", color: "var(--color-primary)", fontSize: "1.1rem" }}>
                  Glissez-déposez un fichier
                </strong>
                <span>ou cliquez pour parcourir</span>
                <small style={{ display: "block", marginTop: "var(--space-1)" }}>PDF, DOCX, TXT</small>
              </div>
            )}
          </div>
        </div>

        <form onSubmit={handleSubmit} className="card" style={{ display: "flex", flexDirection: "column", gap: "var(--space-4)" }}>
          <h2 className="card-title">Contexte du contrat</h2>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: "var(--space-4)" }}>
            <div className="form-group">
              <label>Type de contrat</label>
              <select value={typeContrat} onChange={(e) => setTypeContrat(e.target.value)}>
                <option value="prestation_services">Prestation de services</option>
                <option value="contrat_vente">Contrat de vente</option>
                <option value="bail">Bail</option>
                <option value="nda">Confidentialité (NDA)</option>
                <option value="autre">Autre</option>
              </select>
            </div>
            <div className="form-group">
              <label>Côté représenté</label>
              <select value={cote} onChange={(e) => setCote(e.target.value)}>
                <option value="client">Client</option>
                <option value="fournisseur">Fournisseur</option>
                <option value="prestataire">Prestataire</option>
              </select>
            </div>
          </div>
          <div className="form-group">
            <label>Montant (optionnel)</label>
            <input
              type="text"
              value={montant}
              onChange={(e) => setMontant(e.target.value)}
              placeholder="Ex. 50 000 EUR"
            />
          </div>
          <div className="form-group">
            <label>Noms des parties</label>
            <div className="chips-input">
              {parties.map((p) => (
                <span key={p} className="chip">
                  {p}
                  <button type="button" onClick={() => removeParty(p)} aria-label="Supprimer">
                    <X size={14} />
                  </button>
                </span>
              ))}
              <input
                type="text"
                value={partyInput}
                onChange={(e) => setPartyInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    addParty();
                  }
                }}
                placeholder="Ajouter une partie..."
              />
            </div>
          </div>
          <button type="submit" className="btn-primary" disabled={!file || analyzing}>
            {analyzing ? <Loader2 size={18} className="spin" /> : <UploadCloud size={18} />}
            {analyzing ? "Traitement en cours…" : "Lancer l'analyse"}
          </button>
        </form>
      </div>

      {piiStats && (
        <div className="alert alert-info" style={{ display: "flex", alignItems: "center", gap: "var(--space-3)", marginTop: "var(--space-6)" }}>
          <Shield size={20} color="var(--color-secondary)" />
          <div>
            <strong>Protection des données</strong>
            <div style={{ fontSize: "0.9rem" }}>
              {piiStats.emails} emails, {piiStats.telephones} téléphones, {piiStats.identifiants} identifiants masqués
              avant envoi.
            </div>
          </div>
        </div>
      )}

      {analyzing && (
        <div className="card" style={{ marginTop: "var(--space-6)" }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "var(--space-4)" }}>
            <h2 className="card-title" style={{ marginBottom: 0 }}>Analyse en cours</h2>
            <span className="mono" style={{ color: "var(--color-text-muted)" }}>{formatElapsed(elapsed)}</span>
          </div>
          <div style={{ display: "flex", justifyContent: "space-between", gap: "var(--space-2)" }}>
            {STEPS.map((step, idx) => {
              const isActive = idx === activeStep;
              const isDone = idx < activeStep;
              return (
                <div
                  key={step.id}
                  style={{
                    flex: 1,
                    textAlign: "center",
                    padding: "var(--space-3) var(--space-2)",
                    borderRadius: "var(--radius)",
                    backgroundColor: isActive || isDone ? "var(--color-bg)" : "transparent",
                    border: `1px solid ${isActive ? "var(--color-secondary)" : isDone ? "var(--color-success)" : "var(--color-border)"}`,
                    color: isActive ? "var(--color-secondary)" : isDone ? "var(--color-success)" : "var(--color-text-muted)",
                    fontSize: "0.8rem",
                    fontWeight: 500,
                  }}
                >
                  <div style={{ marginBottom: "var(--space-1)" }}>
                    {isDone ? <CheckCircle2 size={18} /> : isActive ? <Loader2 size={18} className="spin" /> : <div style={{ width: 18, height: 18, margin: "0 auto", borderRadius: "50%", border: "2px solid var(--color-border)" }} />}
                  </div>
                  {step.label}
                </div>
              );
            })}
          </div>
          <p style={{ color: "var(--color-text-muted)", fontSize: "0.85rem", marginTop: "var(--space-4)", marginBottom: 0 }}>
            Cette opération peut prendre 3 à 6 minutes. Ne fermez pas la page.
          </p>
        </div>
      )}
    </div>
  );
}
