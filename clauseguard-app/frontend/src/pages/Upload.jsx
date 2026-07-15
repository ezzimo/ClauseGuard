import { useState, useRef, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { uploadContract, analyzeContract, getContract } from "../api";

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
  const [step, setStep] = useState("");
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
        emails: Object.values(uploadResult.pii_mapping).filter((v) =>
          v.includes("@")
        ).length,
        telephones: Object.keys(uploadResult.pii_mapping).filter((k) =>
          k.startsWith("[PHONE_")
        ).length,
        identifiants: Object.keys(uploadResult.pii_mapping).filter((k) =>
          k.startsWith("[SIRET_") || k.startsWith("[SIREN_")
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
    timerRef.current = setInterval(() => {
      setElapsed((prev) => prev + 1);
    }, 1000);

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
        if (
          data.status === "parse_error" ||
          data.status === "flow_error" ||
          data.status === "error"
        ) {
          stopPolling();
          setAnalyzing(false);
          setError(
            data.error_message ||
              "L'analyse a échoué. Veuillez réessayer."
          );
          return;
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
        setError(
          "L'analyse a dépassé le délai maximal (12 minutes). Veuillez réessayer."
        );
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
      setStep("upload");
      const uploaded = await uploadContract(file, {
        contract_type: typeContrat,
        cote,
        montant,
        parties,
      });
      setUploadResult(uploaded);
      setStep("analyze");
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

  const progressLabels = {
    calling_flow: "Appel du moteur d'analyse...",
    parsing: "Analyse et structuration des résultats...",
    done: "Finalisation...",
  };

  return (
    <div className="upload-page">
      <h1>Charger un contrat</h1>
      <p className="subtitle">
        Déposez votre contrat pour une analyse assistée. Seul le texte masqué est envoyé à la
        plateforme d'analyse.
      </p>

      {error && <div className="alert alert-error">{error}</div>}

      <form onSubmit={handleSubmit} className="upload-form">
        <div
          className={`dropzone ${dragActive ? "active" : ""} ${file ? "has-file" : ""}`}
          onDragEnter={handleDrag}
          onDragOver={handleDrag}
          onDragLeave={handleDrag}
          onDrop={handleDrop}
          onClick={() => fileInputRef.current?.click()}
        >
          <input
            ref={fileInputRef}
            type="file"
            accept=".pdf,.docx,.txt"
            onChange={handleFileChange}
            hidden
          />
          {file ? (
            <div className="file-info">
              <strong>{file.name}</strong>
              <span>{(file.size / 1024).toFixed(1)} Ko</span>
            </div>
          ) : (
            <div className="dropzone-placeholder">
              <strong>Glissez-déposez un fichier</strong>
              <span>ou cliquez pour parcourir</span>
              <small>PDF, DOCX, TXT</small>
            </div>
          )}
        </div>

        <div className="context-form">
          <h2>Contexte du contrat</h2>
          <div className="form-row">
            <label>
              Type de contrat
              <select value={typeContrat} onChange={(e) => setTypeContrat(e.target.value)}>
                <option value="prestation_services">Prestation de services</option>
                <option value="contrat_vente">Contrat de vente</option>
                <option value="bail">Bail</option>
                <option value="nda">Confidentialité (NDA)</option>
                <option value="autre">Autre</option>
              </select>
            </label>
            <label>
              Côté représenté
              <select value={cote} onChange={(e) => setCote(e.target.value)}>
                <option value="client">Client</option>
                <option value="fournisseur">Fournisseur</option>
                <option value="prestataire">Prestataire</option>
              </select>
            </label>
          </div>
          <div className="form-row">
            <label>
              Montant (optionnel)
              <input
                type="text"
                value={montant}
                onChange={(e) => setMontant(e.target.value)}
                placeholder="Ex. 50 000 EUR"
              />
            </label>
          </div>
          <label>
            Noms des parties
            <div className="chips-input">
              {parties.map((p) => (
                <span key={p} className="chip">
                  {p}
                  <button type="button" onClick={() => removeParty(p)}>
                    x
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
          </label>
        </div>

        <button type="submit" className="btn-primary" disabled={!file || analyzing}>
          {analyzing ? "Traitement en cours..." : "Lancer l'analyse"}
        </button>
      </form>

      {piiStats && (
        <div className="pii-banner">
          <strong>Protection des données</strong>
          <span>
            {piiStats.emails} emails, {piiStats.telephones} téléphones, {piiStats.identifiants}{" "}
            identifiants masqués avant envoi.
          </span>
        </div>
      )}

      {analyzing && (
        <div className="loading-steps">
          <h3>Analyse en cours</h3>
          <p className="timer">{formatElapsed(elapsed)}</p>
          <p className="progress-label">
            {progressLabels[progressHint] || progressLabels.calling_flow}
          </p>
          <p className="progress-subtitle">
            Cette opération peut prendre 3 à 6 minutes.
          </p>
          <ul>
            <li className={step === "upload" || uploadResult ? "done" : ""}>
              Envoi du contrat
            </li>
            <li className={step === "analyze" ? "active" : uploadResult ? "done" : ""}>
              Analyse par l'IA
            </li>
            <li className={uploadResult ? "active" : ""}>Préparation de la revue</li>
          </ul>
        </div>
      )}
    </div>
  );
}
