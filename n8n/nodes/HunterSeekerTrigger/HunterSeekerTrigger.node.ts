import { createHmac, timingSafeEqual } from "node:crypto";
import type {
  IDataObject,
  INodeType,
  INodeTypeDescription,
  IWebhookFunctions,
  IWebhookResponseData,
} from "n8n-workflow";

/**
 * The Hunter-Seeker Trigger (Datagoat unit 23): the event bus as an n8n trigger. Register this
 * workflow's webhook URL under Settings → Notifications → Webhooks (or with `hs_register_webhook`),
 * paste the secret into the credential, pick the events, and every signed delivery starts the
 * workflow with the event's body — `{ id, type, ledger_kind, ref, at, workspace_id }`, names,
 * ids and timestamps only. A delivery whose Standard-Webhooks signature does not verify (or whose
 * timestamp is more than five minutes off) is answered 401 and starts nothing.
 */
export const WEBHOOK_EVENTS = [
  "run.completed",
  "run.honest_empty",
  "verdict.drift",
  "evidence.updated",
  "escalate",
  "trial.concluded",
  "source.stale",
  "source.paused",
  "agent.kind_live",
  "policy.changed",
  "binding.confirmed",
  "verify.failed",
] as const;

export const TIMESTAMP_TOLERANCE_S = 5 * 60;

/** The receiver's check, the same arithmetic as the sender's: HMAC-SHA256 over id.timestamp.body. */
export function verifySignature(
  secret: string,
  headers: Record<string, string | undefined>,
  body: string,
  now: number = Math.floor(Date.now() / 1000),
): { ok: true; id: string } | { ok: false; reason: string } {
  const id = headers["webhook-id"];
  const ts = headers["webhook-timestamp"];
  const sig = headers["webhook-signature"];
  if (!id || !ts || !sig) return { ok: false, reason: "missing_headers" };
  const timestamp = Number(ts);
  if (!Number.isInteger(timestamp)) return { ok: false, reason: "bad_timestamp" };
  if (Math.abs(now - timestamp) > TIMESTAMP_TOLERANCE_S) return { ok: false, reason: "stale" };
  const raw = secret.startsWith("whsec_") ? secret.slice("whsec_".length) : secret;
  const want = Buffer.from(
    createHmac("sha256", Buffer.from(raw, "base64")).update(`${id}.${timestamp}.${body}`).digest("base64"),
  );
  for (const part of sig.split(/\s+/)) {
    if (!part.startsWith("v1,")) continue;
    const got = Buffer.from(part.slice(3));
    if (got.length === want.length && timingSafeEqual(got, want)) return { ok: true, id };
  }
  return { ok: false, reason: "no_match" };
}

export class HunterSeekerTrigger implements INodeType {
  description: INodeTypeDescription = {
    displayName: "Hunter-Seeker Trigger",
    name: "hunterSeekerTrigger",
    icon: "file:hunterSeeker.svg",
    group: ["trigger"],
    version: 1,
    subtitle: "={{$parameter[\"events\"].join(\", \")}}",
    description:
      "Starts the workflow on a signed Hunter-Seeker webhook: drift fired, a run came back honest-empty, a decision went to the Approval queue, a trial concluded, a receipt failed verification, and the rest of the event bus.",
    defaults: { name: "Hunter-Seeker Trigger" },
    inputs: [],
    outputs: ["main"],
    credentials: [{ name: "hunterSeekerWebhook", required: true }],
    webhooks: [{ name: "default", httpMethod: "POST", responseMode: "onReceived", path: "hunter-seeker" }],
    properties: [
      {
        displayName: "Events",
        name: "events",
        type: "multiOptions",
        default: ["verdict.drift", "run.honest_empty", "escalate"],
        options: WEBHOOK_EVENTS.map((v) => ({ name: v, value: v })),
        description:
          "Which events start the workflow. Deliveries of other events are acknowledged (200) and ignored, so one endpoint can serve several workflows.",
      },
    ],
  };

  async webhook(this: IWebhookFunctions): Promise<IWebhookResponseData> {
    const creds = (await this.getCredentials("hunterSeekerWebhook")) as { secret: string };
    const req = this.getRequestObject() as unknown as { rawBody?: Buffer | string; body?: unknown };
    const headerData = this.getHeaderData() as Record<string, string | undefined>;
    const raw =
      typeof req.rawBody === "string"
        ? req.rawBody
        : req.rawBody
          ? Buffer.from(req.rawBody).toString("utf8")
          : JSON.stringify(this.getBodyData());
    const v = verifySignature(creds.secret, headerData, raw);
    if (!v.ok) {
      return {
        webhookResponse: {
          status: 401,
          body: {
            type: "about:blank",
            title: "Unverified delivery",
            status: 401,
            code: `signature_${v.reason}`,
            detail: "The Standard-Webhooks signature did not verify under this credential's secret.",
            remedy: "Paste the endpoint's current secret (rotate it under Settings → Notifications if it was lost).",
          },
        },
      };
    }
    const body = this.getBodyData() as { type?: string };
    const events = this.getNodeParameter("events", []) as string[];
    if (events.length > 0 && !events.includes(String(body.type ?? "")))
      return { webhookResponse: { status: 200, body: { ignored: true, type: body.type ?? null } } };
    return {
      webhookResponse: { status: 200, body: { received: true, id: v.id } },
      workflowData: [this.helpers.returnJsonArray([body as IDataObject])],
    };
  }
}
