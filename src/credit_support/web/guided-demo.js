"use strict";

Object.assign(words.en, {
  demoRoleLabel: "Demo role", demoTitle: "Explore a prepared case",
  demoIntro: "Try each role in your own synthetic workspace. No account or API key is needed.",
  tryDemo: "Try demo", chooseDemoRole: "Choose where to begin. You can switch roles during the tour.",
  demoAnalystDescription: "Inspect the prepared analysis and its sources.",
  demoReviewerDescription: "Record an independent simulated decision.",
  demoAuditorDescription: "Trace events and download verified reports.",
  demoCost: "Fictitious data and a simulated model. No OpenAI charges.",
  technicalAccess: "Advanced workspace access", privateDemo: "YOUR PRIVATE DEMO",
  restartDemo: "Restart demo", endDemo: "End demo", demoSession: "Demo session",
  demoPreparing: "Preparing your isolated synthetic case…",
  demoExpired: "Your demo session expired. Start a new demo to continue.",
  demoEnded: "Demo ended. Start again for a fresh synthetic case.",
  demoCapacity: "The demonstration is at capacity. Please try again later.",
  demoExpires: "Session expires", demoAnalystTitle: "1. Understand the analysis",
  demoAnalystGuide: "Your example statement is included. Inspect its facts and source evidence, then switch to Reviewer to record an assessment.",
  demoReviewerTitle: "2. Record a human assessment",
  demoReviewerGuide: "Read the findings, choose a simulated decision, and enter your reason in Independent review. You can review this evaluation once.",
  demoAuditorTitle: "3. Trace and export",
  demoAuditorGuide: "Inspect the audit trail and download the JSON or PDF report. The human review state is separate from the policy outcome.",
  demoReviewedTitle: "Assessment recorded",
  demoReviewedGuide: "The decision is retained in the history. Switch to Auditor to inspect it, or restart for a fresh example.",
  demoEvidence: "Inspect evidence", demoReview: "Try Reviewer", demoAudit: "Try Auditor",
  demoAuditTrail: "Open audit trail", demoAnalyst: "Demo analyst",
  demoReviewer: "Demo reviewer", demoAuditor: "Demo auditor"
});
Object.assign(words.es, {
  demoRoleLabel: "Rol de demostración", demoTitle: "Explora un expediente preparado",
  demoIntro: "Prueba cada rol en tu propio espacio sintético. No necesitas una cuenta ni una clave API.",
  tryDemo: "Probar demo", chooseDemoRole: "Elige dónde comenzar. Puedes cambiar de rol durante el recorrido.",
  demoAnalystDescription: "Consulta el análisis preparado y sus fuentes.",
  demoReviewerDescription: "Registra una decisión simulada independiente.",
  demoAuditorDescription: "Consulta los eventos y descarga informes verificados.",
  demoCost: "Datos ficticios y modelo simulado. Sin cargos de OpenAI.",
  technicalAccess: "Acceso avanzado al espacio de trabajo", privateDemo: "TU DEMO PRIVADA",
  restartDemo: "Reiniciar demo", endDemo: "Finalizar demo", demoSession: "Sesión demo",
  demoPreparing: "Preparando tu expediente sintético aislado…",
  demoExpired: "Tu sesión demo venció. Inicia una nueva para continuar.",
  demoEnded: "Demo finalizada. Puedes comenzar con otro expediente ficticio.",
  demoCapacity: "La demostración alcanzó su capacidad. Inténtalo más tarde.",
  demoExpires: "La sesión vence", demoAnalystTitle: "1. Comprende el análisis",
  demoAnalystGuide: "El documento de ejemplo ya está incluido. Consulta sus datos y evidencia; después cambia a Revisor para registrar una evaluación.",
  demoReviewerTitle: "2. Registra una evaluación humana",
  demoReviewerGuide: "Lee los hallazgos, elige una decisión simulada y escribe el motivo en Revisión independiente. Solo puedes revisar esta evaluación una vez.",
  demoAuditorTitle: "3. Consulta y exporta",
  demoAuditorGuide: "Consulta la auditoría y descarga el informe JSON o PDF. El estado de revisión humana es independiente del resultado de política.",
  demoReviewedTitle: "Evaluación registrada",
  demoReviewedGuide: "La decisión queda en el historial. Cambia a Auditor para consultarla o reinicia con un ejemplo nuevo.",
  demoEvidence: "Examinar evidencia", demoReview: "Probar Revisor", demoAudit: "Probar Auditor",
  demoAuditTrail: "Abrir auditoría", demoAnalyst: "Analista demo",
  demoReviewer: "Revisor demo", demoAuditor: "Auditor demo"
});

const demoController = {
  session: null,
  expiryTimer: null,
  get active() { return this.session !== null; },
  clear() {
    if (this.expiryTimer) clearTimeout(this.expiryTimer);
    this.expiryTimer = null;
    this.session = null;
    $("demo-role").hidden = true;
    $("demo-role-label").hidden = true;
    $("demo-guide").hidden = true;
  },
  async start(role) {
    notify(t("demoPreparing"));
    const data = await json("/v1/demo/sessions", {
      method: "POST", headers: {"X-Demo-Request": "1"}, body: JSON.stringify({role})
    });
    this.clear();
    this.session = data;
    token = data.role_tokens[role];
    actor = await json("/v1/me");
    directory = [];
    $("login").hidden = true;
    $("app").hidden = false;
    $("signout").hidden = false;
    language();
    this.expiryTimer = setTimeout(() => {
      clearWorkspace();
      notify(t("demoExpired"), true);
    }, Math.max(0, new Date(data.expires_at).getTime() - Date.now()));
    await poll(data.case_id, data.evaluation_id);
    await loadCases();
    await openCase(data.case_id, data.evaluation_id);
    language();
    notify("");
  },
  async switchRole(role) {
    if (!this.session || !this.session.role_tokens[role]) return;
    token = this.session.role_tokens[role];
    actor = await json("/v1/me");
    directory = [];
    await loadCases();
    await openCase(this.session.case_id, this.session.evaluation_id);
    language();
    $("reason").value = "";
    $("decision").value = "";
    notify("");
  },
  async end() {
    if (this.active) {
      try { await api("/v1/demo/session/end", {method: "POST"}); }
      catch { /* Local credentials are cleared even if the server is unreachable. */ }
    }
    clearWorkspace();
    notify(t("demoEnded"));
  },
  render() {
    const active = this.active && !!actor?.guided_demo;
    $("demo-role").hidden = !active;
    $("demo-role-label").hidden = !active;
    $("demo-guide").hidden = !active || !workspace;
    if (!active) return;
    $("identity").textContent = `${t("demoSession")} · ${t(actor.role)}`;
    $("signout").textContent = t("endDemo");
    $("demo-role").value = actor.role;
    $("demo-role").disabled = busy;
    $("restart-demo").disabled = busy;
    $("demo-next").disabled = busy;
    $("new-case-toggle").hidden = true;
    $("new-case-form").hidden = true;
    $("analyst-tools").hidden = true;
    $("assignment-form").hidden = true;
    if (!workspace) return;
    const reviewed = !!review?.review;
    const titles = {analyst: "demoAnalystTitle", reviewer: reviewed ? "demoReviewedTitle" : "demoReviewerTitle", auditor: "demoAuditorTitle"};
    const guides = {analyst: "demoAnalystGuide", reviewer: reviewed ? "demoReviewedGuide" : "demoReviewerGuide", auditor: "demoAuditorGuide"};
    $("demo-guide-title").textContent = t(titles[actor.role]);
    $("demo-guide-text").textContent = t(guides[actor.role]);
    $("demo-expiry").textContent = `${t("demoExpires")}: ${when(this.session.expires_at)}`;
    $("demo-next").textContent = t(actor.role === "analyst" ? "demoEvidence" : actor.role === "reviewer" ? "demoAudit" : "demoAuditTrail");
    $("members").replaceChildren();
    workspace.members.forEach(member => {
      const row = el("div", t(`demo${member.role[0].toUpperCase() + member.role.slice(1)}`), "member");
      row.append(el("small", t(member.role)));
      $("members").append(row);
    });
    if (review?.review) $("review-detail").textContent = t("demoReviewer");
  }
};

$("try-demo").addEventListener("click", () => {
  $("demo-roles").hidden = false;
  $("try-demo").hidden = true;
});
document.querySelectorAll("[data-demo-role]").forEach(button => {
  button.addEventListener("click", () => run(() => demoController.start(button.dataset.demoRole)));
});
$("demo-role").addEventListener("change", () => run(() => demoController.switchRole($("demo-role").value)));
$("restart-demo").addEventListener("click", () => run(async () => {
  const role = actor.role;
  await demoController.end();
  await demoController.start(role);
}));
$("demo-next").addEventListener("click", () => {
  if (actor.role === "reviewer") run(() => demoController.switchRole("auditor"));
  else $(actor.role === "analyst" ? "tab-evidence" : "tab-audit").click();
});

json("/v1/demo/config").then(config => {
  $("guided-entry").hidden = !config.enabled;
  $("technical-access").hidden = !!config.public_demo;
  if (config.public_demo) {
    words.en.localWorkspace = "Public demonstration workspace";
    words.es.localWorkspace = "Espacio de demostración público";
    language();
  }
  $("technical-access").open = !config.enabled;
}).catch(() => { $("technical-access").open = true; });
language();
