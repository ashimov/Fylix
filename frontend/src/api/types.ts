export interface FileDescriptor {
  filename: string;
  size: number;
}

export interface CreateTransferRequest {
  sender_email: string;
  recipient_emails: string[];
  message?: string | null;
  ttl_days: number;
  files: FileDescriptor[];
}

export interface CreateTransferResponse {
  transfer_id: string;
  download_token: string;
  manage_token: string;
  upload_urls: Record<string, string>;
  expires_at: string;
}

export interface FileInfo {
  filename: string;
  size_bytes: number;
  mime_type: string;
}

export interface DownloadInfo {
  ip: string;
  country?: string | null;
  ua?: string | null;
  started_at: string;
  completed_at?: string | null;
  bytes_sent?: number | null;
  aborted: boolean;
}

export interface SenderPanelResponse {
  transfer_id: string;
  status: string;
  sender_email: string;
  recipient_emails: string[];
  message?: string | null;
  created_at: string;
  expires_at: string;
  download_token?: string | null;
  files: FileInfo[];
  downloads: DownloadInfo[];
}
