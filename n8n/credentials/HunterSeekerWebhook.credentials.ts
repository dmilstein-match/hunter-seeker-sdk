import type { ICredentialType, INodeProperties } from "n8n-workflow";

/** The secret an endpoint was registered with (shown once under Settings → Notifications → Webhooks). */
export class HunterSeekerWebhook implements ICredentialType {
  name = "hunterSeekerWebhook";
  displayName = "Hunter-Seeker Webhook";
  documentationUrl = "https://hunter-seeker.io/for-agents";
  properties: INodeProperties[] = [
    {
      displayName: "Signing secret",
      name: "secret",
      type: "string",
      typeOptions: { password: true },
      default: "",
      description: "whsec_… — the secret shown once when the endpoint was registered; rotate it there if it was lost.",
    },
  ];
}
