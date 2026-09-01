/**
 * Hunter-Seeker node — Score · Rank · Verify · Report outcome · Drift.
 * Thin: every operation is one POST to /v1/<operation>; outputs are the API's typed objects.
 * Publish via the n8n community-node GitHub Action with provenance (required since 2026-05-01).
 */
import type { IExecuteFunctions, INodeExecutionData, INodeType, INodeTypeDescription } from "n8n-workflow";

const OPS = {
  score: { path: "/v1/score-entity", label: "Score one entity", fields: ["modelRef", "row", "subjectKind", "ack"] },
  rank: { path: "/v1/rank-topk", label: "Rank a table (one run)", fields: ["datasetId", "entityColumn", "outcomeColumn", "subjectKind", "ack"] },
  verify: { path: "/v1/verify-verdict", label: "Verify a Verdict", fields: ["verdict", "signature"] },
  report: { path: "/v1/report-outcome", label: "Report outcome", fields: ["modelRef", "entityId", "outcome", "observedAt", "eventId"] },
  drift: { path: "/v1/drift-status", label: "Drift status", fields: ["modelRef"] },
} as const;

export class HunterSeeker implements INodeType {
  description: INodeTypeDescription = {
    displayName: "Hunter-Seeker",
    name: "hunterSeeker",
    icon: "file:hunterSeeker.svg",
    group: ["transform"],
    version: 1,
    subtitle: '={{$parameter["operation"]}}',
    description: "Deterministic, signed, refusable decisions for your workflow. Agents may generate copy; they may not invent the score.",
    defaults: { name: "Hunter-Seeker" },
    inputs: ["main"],
    outputs: ["main"],
    usableAsTool: true,
    credentials: [{ name: "hunterSeekerApi", required: true }],
    properties: [
      { displayName: "Operation", name: "operation", type: "options", noDataExpression: true, default: "score",
        options: Object.entries(OPS).map(([k, v]) => ({ name: v.label, value: k })) },
      { displayName: "Model Ref", name: "modelRef", type: "string", default: "", displayOptions: { show: { operation: ["score", "report", "drift"] } }, description: "model_ref from a cleared rank" },
      { displayName: "Row (JSON)", name: "row", type: "json", default: "{}", displayOptions: { show: { operation: ["score"] } } },
      { displayName: "Dataset ID", name: "datasetId", type: "string", default: "sample:saas_churn", displayOptions: { show: { operation: ["rank"] } } },
      { displayName: "Entity Column", name: "entityColumn", type: "string", default: "", displayOptions: { show: { operation: ["rank"] } } },
      { displayName: "Outcome Column", name: "outcomeColumn", type: "string", default: "", displayOptions: { show: { operation: ["rank"] } } },
      { displayName: "Subject Kind", name: "subjectKind", type: "options", default: "org", options: ["person", "org", "object", "event", "other"].map((v) => ({ name: v, value: v })), displayOptions: { show: { operation: ["score", "rank"] } } },
      { displayName: "Acknowledge decision support (person-level)", name: "ack", type: "boolean", default: false, displayOptions: { show: { operation: ["score", "rank"] } } },
      { displayName: "Verdict (JSON)", name: "verdict", type: "json", default: "{}", displayOptions: { show: { operation: ["verify"] } } },
      { displayName: "Signature (JSON)", name: "signature", type: "json", default: "{}", displayOptions: { show: { operation: ["verify"] } } },
      { displayName: "Entity ID", name: "entityId", type: "string", default: "", displayOptions: { show: { operation: ["report"] } } },
      { displayName: "Outcome (true/false)", name: "outcome", type: "boolean", default: false, displayOptions: { show: { operation: ["report"] } } },
      { displayName: "Observed At", name: "observedAt", type: "string", default: "={{$now.toISO()}}", displayOptions: { show: { operation: ["report"] } } },
      { displayName: "Event ID (idempotency)", name: "eventId", type: "string", default: "={{$execution.id}}-{{$itemIndex}}", displayOptions: { show: { operation: ["report"] } } },
    ],
  };

  async execute(this: IExecuteFunctions): Promise<INodeExecutionData[][]> {
    const items = this.getInputData();
    const out: INodeExecutionData[] = [];
    const creds = (await this.getCredentials("hunterSeekerApi")) as { baseUrl: string };
    for (let i = 0; i < items.length; i++) {
      const op = this.getNodeParameter("operation", i) as keyof typeof OPS;
      const p = (n: string) => this.getNodeParameter(n, i, undefined) as any;
      const json = (n: string) => { const v = p(n); return typeof v === "string" ? JSON.parse(v) : v; };
      let body: Record<string, unknown>;
      switch (op) {
        case "score": body = { model_ref: p("modelRef"), row: json("row"), subject_kind: p("subjectKind"), acknowledge_decision_support: p("ack") }; break;
        case "rank": body = { data: { dataset_id: p("datasetId") }, entity_column: p("entityColumn"), outcome_column: p("outcomeColumn"), subject_kind: p("subjectKind"), acknowledge_decision_support: p("ack"), idempotency_key: `${this.getExecutionId()}-${i}` }; break;
        case "verify": body = { verdict: json("verdict"), signature: json("signature") }; break;
        case "report": body = { model_ref: p("modelRef"), outcomes: [{ entity_id: p("entityId"), outcome: p("outcome"), observed_at: p("observedAt"), event_id: p("eventId") }] }; break;
        case "drift": body = { model_ref: p("modelRef") }; break;
      }
      const res = await this.helpers.httpRequestWithAuthentication.call(this, "hunterSeekerApi", { method: "POST", baseURL: creds.baseUrl, url: OPS[op].path, body, json: true });
      out.push({ json: res as any, pairedItem: { item: i } });
    }
    return [out];
  }
}
