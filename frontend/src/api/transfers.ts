import { request } from "./client";
import type {
  CreateTransferRequest,
  CreateTransferResponse,
  SenderPanelResponse,
} from "./types";

export function createTransfer(
  body: CreateTransferRequest,
): Promise<CreateTransferResponse> {
  return request<CreateTransferResponse>("/api/transfers", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function getSenderPanel(manageToken: string): Promise<SenderPanelResponse> {
  return request<SenderPanelResponse>(`/s/${encodeURIComponent(manageToken)}`);
}

export function deleteSenderTransfer(manageToken: string): Promise<void> {
  return request<void>(`/s/${encodeURIComponent(manageToken)}`, { method: "DELETE" });
}

export function revokeSenderTransfer(manageToken: string): Promise<void> {
  return request<void>(`/s/${encodeURIComponent(manageToken)}/revoke`, {
    method: "POST",
  });
}
