/**
 * Hunter-Seeker node — all fifteen published operations.
 *
 * Thin by design: every operation is one POST to `/v1/<operation>`, and outputs are the API's
 * typed objects, passed through. This node adds no logic of its own — the engine owns every
 * number, and a node that reshaped a response would be a second place for one to be wrong.
 *
 * WHY FIFTEEN AND NOT FIVE. It shipped with five — score, rank, verify, report, drift — and that
 * set could not close the governance loop the product exists to provide. `hs_attest_action` was
 * missing, so an integrator could never record that they acted; `hs_explain_levers` was missing,
 * so they could not obtain the `lever_token` an attestation needs; and `hs_action_evidence` was
 * missing, so they could never ask whether acting worked. Every step of attest → report →
 * evidence was unreachable except the middle one, which meant the node let someone write outcomes
 * into a ledger they could not query.
 *
 * `hs_poll_task` was missing too, and that one is structural: without it the node can only run
 * SYNCHRONOUS inline data. No `dataset_id`, no `fetch_url`, and therefore no `reading` — so the
 * whole reduction surface (`sequential`, `windowed`, `trace`, `panel`, `stream`) was unreachable
 * from the shipped integration by construction.
 *
 * `scripts/hs-surface-parity.mjs` compares this file's `/v1/...` paths against the published
 * OpenAPI document and fails when they diverge, so the gap cannot silently reopen.
 *
 * Publish via the n8n community-node GitHub Action with provenance (required since 2026-05-01).
 */
import type { IExecuteFunctions, INodeExecutionData, INodeType, INodeTypeDescription } from "n8n-workflow";

/**
 * Every operation, its REST path, and what it costs.
 *
 * `cost` is shown in the operation picker, because the single most useful thing to know before
 * choosing one is whether it spends anything: exactly ONE operation consumes a run, two consume
 * decisions, and the other twelve are free.
 */
const OPS = {
  // — orient —
  describe: { path: "/v1/describe-capabilities", label: "Describe capabilities (free)", cost: "free" },
  // — supply —
  provide: { path: "/v1/provide-dataset", label: "Provide dataset (free)", cost: "free" },
  // — run —
  rank: { path: "/v1/rank-topk", label: "Rank a table (ONE RUN)", cost: "one run" },
  poll: { path: "/v1/poll-task", label: "Poll a task (free)", cost: "free" },
  // — interrogate, all free against a ranking_ref —
  quality: { path: "/v1/model-quality", label: "Model quality (free)", cost: "free" },
  drivers: { path: "/v1/explain-drivers", label: "Explain drivers (free)", cost: "free" },
  levers: { path: "/v1/explain-levers", label: "Explain levers (free)", cost: "free" },
  brief: { path: "/v1/context-brief", label: "Context brief (free)", cost: "free" },
  // — decide —
  score: { path: "/v1/score-entity", label: "Score one entity (one decision)", cost: "one decision" },
  scoreBatch: { path: "/v1/score-batch", label: "Score many entities (one decision per row)", cost: "per row" },
  verify: { path: "/v1/verify-verdict", label: "Verify a Verdict (free)", cost: "free" },
  // — close the loop —
  attest: { path: "/v1/attest-action", label: "Attest an action (free)", cost: "free" },
  report: { path: "/v1/report-outcome", label: "Report outcome (free)", cost: "free" },
  evidence: { path: "/v1/action-evidence", label: "Action evidence (free)", cost: "free" },
  drift: { path: "/v1/drift-status", label: "Drift status (free)", cost: "free" },
} as const;

type Op = keyof typeof OPS;

/** Which operations show a given field. Declared once so the picker and the body builder cannot
 *  disagree about what an operation takes. */
const show = (...ops: Op[]) => ({ displayOptions: { show: { operation: ops as unknown as string[] } } });

export class HunterSeeker implements INodeType {
  description: INodeTypeDescription = {
    displayName: "Hunter-Seeker",
    name: "hunterSeeker",
    icon: "file:hunterSeeker.svg",
    group: ["transform"],
    version: 1,
    subtitle: '={{$parameter["operation"]}}',
    description:
      "Deterministic, signed, refusable decisions for your workflow. Agents may generate copy; they may not invent the score.",
    defaults: { name: "Hunter-Seeker" },
    inputs: ["main"],
    outputs: ["main"],
    usableAsTool: true,
    credentials: [{ name: "hunterSeekerApi", required: true }],
    properties: [
      {
        displayName: "Operation",
        name: "operation",
        type: "options",
        noDataExpression: true,
        default: "score",
        options: Object.entries(OPS).map(([k, v]) => ({ name: v.label, value: k })),
        description:
          "Exactly one operation costs a run (Rank), and it is refunded on an honest-empty or an error. Scoring costs a decision per non-refused row. Everything else is free.",
      },

      // ── refs ──────────────────────────────────────────────────────────────────────────────
      {
        displayName: "Model Ref",
        name: "modelRef",
        type: "string",
        default: "",
        ...show("score", "scoreBatch", "report", "attest", "evidence", "drift"),
        description: "model_ref from a cleared Rank. Lives 90 days.",
      },
      {
        displayName: "Ranking Ref",
        name: "rankingRef",
        type: "string",
        default: "",
        ...show("quality", "drivers", "levers", "brief"),
        description:
          "ranking_ref from a cleared Rank. The analysis behind it is cached for one HOUR, and every operation that takes it is free — run once, interrogate freely.",
      },
      {
        displayName: "Task ID",
        name: "taskId",
        type: "string",
        default: "",
        ...show("poll"),
        description: "task_id from an async Rank. Respect retry_after_ms; do not tight-loop.",
      },

      // ── rank ──────────────────────────────────────────────────────────────────────────────
      {
        displayName: "Data Source",
        name: "dataSource",
        type: "options",
        default: "datasetId",
        ...show("rank"),
        options: [
          { name: "Dataset ID (async — then Poll)", value: "datasetId" },
          { name: "Inline rows (synchronous)", value: "rows" },
          { name: "Fetch URL (async — then Poll)", value: "fetchUrl" },
        ],
        description:
          "Inline rows return the ranking immediately. A dataset_id or fetch_url returns {status:'pending', task_id} — follow it with the Poll operation. A reading requires one of the async sources.",
      },
      { displayName: "Dataset ID", name: "datasetId", type: "string", default: "sample:saas_churn", displayOptions: { show: { operation: ["rank"], dataSource: ["datasetId"] } } },
      { displayName: "Rows (JSON array)", name: "rows", type: "json", default: "[]", displayOptions: { show: { operation: ["rank"], dataSource: ["rows"] } } },
      { displayName: "Fetch URL", name: "fetchUrl", type: "string", default: "", displayOptions: { show: { operation: ["rank"], dataSource: ["fetchUrl"] } } },
      { displayName: "Entity Column", name: "entityColumn", type: "string", default: "", ...show("rank", "scoreBatch") },
      { displayName: "Outcome Column", name: "outcomeColumn", type: "string", default: "", ...show("rank") },
      {
        displayName: "Outcome Is Desirable",
        name: "outcomeIsDesirable",
        type: "options",
        default: "unstated",
        ...show("rank"),
        options: [
          { name: "Leave unstated (the engine resolves it)", value: "unstated" },
          { name: "Desirable — converted, renewed, closed", value: "yes" },
          { name: "Adverse — churned, defaulted, failed", value: "no" },
        ],
        description:
          "Whether a 'yes' is the thing you want MORE of. Unstated is forwarded as unstated, never as a guess: the levers you get back read the opposite way if this is wrong.",
      },
      {
        displayName: "Reading (JSON)",
        name: "reading",
        type: "json",
        default: "{}",
        displayOptions: { show: { operation: ["rank"], dataSource: ["datasetId", "fetchUrl"] } },
        description:
          "Optional. Reduces an EVENT table to one row per entity BEFORE ranking — {kind, version, roles, params?, label?, as_of?}. Call Describe capabilities for the published kinds, their roles and their param bounds. Leave as {} to send none.",
      },
      { displayName: "Horizon", name: "horizon", type: "string", default: "", ...show("rank"), description: "Free text, e.g. '30 days'. Optional." },
      { displayName: "Refit Of", name: "refitOf", type: "string", default: "", ...show("rank"), description: "A prior model_ref this run refreshes. Makes the response carry a drift block." },
      { displayName: "Top K", name: "topK", type: "number", default: 20, ...show("rank") },

      // ── provide dataset ───────────────────────────────────────────────────────────────────
      { displayName: "Fetch URL", name: "provideFetchUrl", type: "string", default: "", ...show("provide"), description: "A public https CSV the server downloads. Leave empty to receive an upload_url to PUT to instead." },
      { displayName: "Name", name: "datasetName", type: "string", default: "", ...show("provide") },

      // ── score ─────────────────────────────────────────────────────────────────────────────
      { displayName: "Entity ID", name: "entityId", type: "string", default: "", ...show("score", "report", "attest") },
      { displayName: "Row (JSON)", name: "row", type: "json", default: "{}", ...show("score"), description: "Every column the analysis used, with the same types." },
      { displayName: "Rows (JSON array)", name: "batchRows", type: "json", default: "[]", ...show("scoreBatch") },
      {
        displayName: "Subject Kind",
        name: "subjectKind",
        type: "options",
        default: "org",
        ...show("score", "scoreBatch", "rank"),
        options: ["person", "org", "object", "event", "other"].map((v) => ({ name: v, value: v })),
      },
      {
        displayName: "Acknowledge decision support (person-level)",
        name: "ack",
        type: "boolean",
        default: false,
        ...show("score", "scoreBatch", "rank"),
        description:
          "Required when the subject is a person and the outcome is regulated — hiring, credit, education, insurance, benefits, justice, healthcare, immigration. The result is decision-support only.",
      },

      // ── levers ────────────────────────────────────────────────────────────────────────────
      {
        displayName: "Entity IDs (comma-separated)",
        name: "entityIds",
        type: "string",
        default: "",
        ...show("levers"),
        description: "Entities from the ranking behind that ranking_ref.",
      },

      // ── brief ─────────────────────────────────────────────────────────────────────────────
      {
        displayName: "Format",
        name: "briefFormat",
        type: "options",
        default: "json",
        ...show("brief"),
        options: [{ name: "JSON", value: "json" }, { name: "Markdown", value: "markdown" }],
        description: "Both carry identical numbers — the prose is rendered from the same object.",
      },

      // ── verify ────────────────────────────────────────────────────────────────────────────
      {
        displayName: "Verdict (JSON)",
        name: "verdict",
        type: "json",
        default: "{}",
        ...show("verify"),
        description: "Pass the object exactly as received. Re-serialising it invalidates the signature, which is the point.",
      },
      { displayName: "Signature (JSON)", name: "signature", type: "json", default: "{}", ...show("verify") },

      // ── attest ────────────────────────────────────────────────────────────────────────────
      {
        displayName: "Lever Token",
        name: "leverToken",
        type: "string",
        default: "",
        ...show("attest"),
        description: "From Explain levers. Only a hash of it is stored, never the token.",
      },
      { displayName: "Post Value", name: "postValue", type: "string", default: "", ...show("attest"), description: "The feature's value AFTER you acted. Numeric values are sent as numbers." },
      { displayName: "Acted At", name: "actedAt", type: "string", default: "={{$now.toISO()}}", ...show("attest") },

      // ── report ────────────────────────────────────────────────────────────────────────────
      { displayName: "Outcome (true/false)", name: "outcome", type: "boolean", default: false, ...show("report") },
      { displayName: "Observed At", name: "observedAt", type: "string", default: "={{$now.toISO()}}", ...show("report") },
      {
        displayName: "Event ID (idempotency)",
        name: "eventId",
        type: "string",
        default: "={{$execution.id}}-{{$itemIndex}}",
        ...show("report", "attest"),
        description: "The same event_id twice is ONE row. This is what makes a retried workflow safe.",
      },
    ],
  };

  async execute(this: IExecuteFunctions): Promise<INodeExecutionData[][]> {
    const items = this.getInputData();
    const out: INodeExecutionData[] = [];
    const creds = (await this.getCredentials("hunterSeekerApi")) as { baseUrl: string };

    for (let i = 0; i < items.length; i++) {
      const op = this.getNodeParameter("operation", i) as Op;
      const p = (n: string, d?: unknown) => this.getNodeParameter(n, i, d) as any;
      const json = (n: string) => {
        const v = p(n);
        return typeof v === "string" ? JSON.parse(v) : v;
      };
      /** Omit an empty optional rather than sending "" — an empty string is a VALUE, and the
       *  engine would be right to reject it or to treat it as a stated blank. */
      const opt = (k: string, v: unknown) => (v === "" || v === undefined || v === null ? {} : { [k]: v });
      /** `{}` in a JSON field means "not supplied". Same reason. */
      const optObj = (k: string, v: Record<string, unknown>) => (v && Object.keys(v).length ? { [k]: v } : {});

      let body: Record<string, unknown>;
      switch (op) {
        case "describe":
          body = {};
          break;

        case "provide":
          body = { ...opt("fetch_url", p("provideFetchUrl")), ...opt("name", p("datasetName")) };
          break;

        case "rank": {
          const source = p("dataSource") as "datasetId" | "rows" | "fetchUrl";
          const data =
            source === "rows" ? { rows: json("rows") }
              : source === "fetchUrl" ? { fetch_url: p("fetchUrl") }
                : { dataset_id: p("datasetId") };
          const desirable = p("outcomeIsDesirable") as "unstated" | "yes" | "no";
          body = {
            data,
            entity_column: p("entityColumn"),
            outcome_column: p("outcomeColumn"),
            subject_kind: p("subjectKind"),
            acknowledge_decision_support: p("ack"),
            page: { k: p("topK") },
            idempotency_key: `${this.getExecutionId()}-${i}`,
            ...opt("horizon", p("horizon")),
            ...opt("refit_of", p("refitOf")),
            // Forwarded ONLY when stated. Sending a default here would make this node author a
            // polarity the user never gave, and every lever would read the wrong way round.
            ...(desirable === "unstated" ? {} : { outcome_is_desirable: desirable === "yes" }),
            ...(source === "rows" ? {} : optObj("reading", json("reading"))),
          };
          break;
        }

        case "poll":
          body = { task_id: p("taskId") };
          break;

        case "quality":
        case "drivers":
          body = { ranking_ref: p("rankingRef") };
          break;

        case "levers":
          body = {
            ranking_ref: p("rankingRef"),
            entity_ids: String(p("entityIds")).split(",").map((s) => s.trim()).filter(Boolean),
          };
          break;

        case "brief":
          body = { ranking_ref: p("rankingRef"), format: p("briefFormat") };
          break;

        case "score":
          body = {
            model_ref: p("modelRef"),
            entity_id: p("entityId"),
            row: json("row"),
            subject_kind: p("subjectKind"),
            acknowledge_decision_support: p("ack"),
          };
          break;

        case "scoreBatch":
          body = {
            model_ref: p("modelRef"),
            rows: json("batchRows"),
            subject_kind: p("subjectKind"),
            acknowledge_decision_support: p("ack"),
            ...opt("entity_column", p("entityColumn")),
          };
          break;

        case "verify":
          body = { verdict: json("verdict"), signature: json("signature") };
          break;

        case "attest": {
          const raw = p("postValue");
          const n = Number(raw);
          body = {
            model_ref: p("modelRef"),
            entity_id: p("entityId"),
            lever_token: p("leverToken"),
            // A numeric-looking post_value is sent as a NUMBER. The engine compares it against the
            // lever's own scale, and "5" is not 5 to a comparison that respects types.
            post_value: raw !== "" && !Number.isNaN(n) ? n : raw,
            acted_at: p("actedAt"),
            ...opt("event_id", p("eventId")),
          };
          break;
        }

        case "report":
          body = {
            model_ref: p("modelRef"),
            outcomes: [{
              entity_id: p("entityId"),
              outcome: p("outcome"),
              observed_at: p("observedAt"),
              event_id: p("eventId"),
            }],
          };
          break;

        case "evidence":
        case "drift":
          body = { model_ref: p("modelRef") };
          break;
      }

      const res = await this.helpers.httpRequestWithAuthentication.call(this, "hunterSeekerApi", {
        method: "POST",
        baseURL: creds.baseUrl,
        url: OPS[op].path,
        body,
        json: true,
      });
      out.push({ json: res as any, pairedItem: { item: i } });
    }
    return [out];
  }
}
