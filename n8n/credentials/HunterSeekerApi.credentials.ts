import type { IAuthenticateGeneric, ICredentialTestRequest, ICredentialType, INodeProperties } from "n8n-workflow";

export class HunterSeekerApi implements ICredentialType {
  name = "hunterSeekerApi";
  displayName = "Hunter-Seeker API";
  documentationUrl = "https://hunter-seeker.net/for-agents";
  properties: INodeProperties[] = [
    { displayName: "Machine key", name: "apiKey", type: "string", typeOptions: { password: true }, default: "", description: "hsk_live_… or hsk_test_… (test keys reach only the sample datasets)" },
    { displayName: "Base URL", name: "baseUrl", type: "string", default: "https://hunter-seeker.net/api" },
  ];
  authenticate: IAuthenticateGeneric = { type: "generic", properties: { headers: { Authorization: "=Bearer {{$credentials.apiKey}}" } } };
  test: ICredentialTestRequest = { request: { baseURL: "={{$credentials.baseUrl}}", url: "/v1/describe-capabilities", method: "POST", body: {} } };
}
